"""Local speech-to-text with faster-whisper: NVIDIA GPU when possible, CPU otherwise."""
from __future__ import annotations

import gc
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import gpu, paths
from .errors import UserFacingError
from .procs import NEVER, QUIET, CancelToken, OperationCancelled, Report

SUPPORTED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts", ".mts", ".m2ts",
}

MODELS = {
    "turbo": {
        "model": "large-v3-turbo",
        "beam_size": 3,
        "label": "Быстрая",
        "description": "large-v3-turbo · почти та же точность, в 3–4 раза быстрее",
        "size": 1_620_000_000,
    },
    "large": {
        "model": "large-v3",
        "beam_size": 5,
        "label": "Точная",
        "description": "large-v3 · максимум точности, медленнее",
        "size": 3_090_000_000,
    },
}

MIXED_LANGUAGE_SENTINEL = "__mixed__"
# id -> (label, whisper code)
LANGUAGE_OPTIONS: list[tuple[str, str, str | None]] = [
    ("mixed", "Авто · микс языков", MIXED_LANGUAGE_SENTINEL),
    ("auto", "Авто · один язык", None),
    ("ru", "Русский", "ru"),
    ("en", "English", "en"),
    ("uk", "Українська", "uk"),
    ("fr", "Français", "fr"),
    ("es", "Español", "es"),
    ("de", "Deutsch", "de"),
    ("it", "Italiano", "it"),
    ("pt", "Português", "pt"),
    ("tr", "Türkçe", "tr"),
    ("zh", "中文", "zh"),
    ("ja", "日本語", "ja"),
    ("ko", "한국어", "ko"),
    ("ar", "العربية", "ar"),
]
LANGUAGES = {label: code for _id, label, code in LANGUAGE_OPTIONS}
LANGUAGE_DISPLAY = {code: label for _id, label, code in LANGUAGE_OPTIONS if code and code != MIXED_LANGUAGE_SENTINEL}
OUTPUT_FORMATS = ("txt", "srt", "vtt")

MIXED_MAX_SPEECH_SECONDS = 18.0
MIXED_MIN_SILENCE_MS = 350
MIXED_SPEECH_PAD_MS = 180

# Settings that keep Whisper from looping on one phrase (ported from ZNAMBO Transcriber,
# without the n-gram ban that can distort normal repeated speech).
DECODE_OPTIONS = {
    "condition_on_previous_text": False,
    "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    "compression_ratio_threshold": 2.4,
    "log_prob_threshold": -1.0,
    "no_speech_threshold": 0.6,
}


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class TranscriptResult:
    outputs: list[Path]
    device: str
    duration: float
    elapsed: float
    languages: dict[str, float] = field(default_factory=dict)
    dropped_loops: int = 0

    def summary(self) -> str:
        minutes, seconds = divmod(int(self.elapsed), 60)
        where = "видеокарта" if self.device == "cuda" else "процессор"
        text = f"Готово за {minutes}:{seconds:02d} · {where}"
        if len(self.languages) > 1:
            total = sum(self.languages.values()) or 1.0
            parts = sorted(self.languages.items(), key=lambda item: item[1], reverse=True)[:3]
            text += " · " + ", ".join(f"{language_label(code)} {value / total:.0%}" for code, value in parts)
        return text


def language_label(code: str | None) -> str:
    if not code:
        return "не определён"
    return LANGUAGE_DISPLAY.get(code, code)


def language_code(language_id: str) -> str | None:
    for option_id, _label, code in LANGUAGE_OPTIONS:
        if option_id == language_id:
            return code
    return MIXED_LANGUAGE_SENTINEL


# ---- formatting ---------------------------------------------------------------------

def safe_stem(path: Path) -> str:
    stem = re.sub(r"[^\w .()\-\[\]]+", "_", path.stem, flags=re.UNICODE).strip(" .")
    return stem or "transcript"


def srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def readable_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def clean_join(words: list[Word]) -> str:
    text = " ".join(word.text.strip() for word in words if word.text.strip())
    text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def wrap_cue(text: str, width: int = 42) -> str:
    """At most two balanced lines, the way editors expect subtitles."""
    if len(text) <= width:
        return text
    words = text.split()
    best = text
    best_score = None
    for index in range(1, len(words)):
        first, second = " ".join(words[:index]), " ".join(words[index:])
        score = max(len(first), len(second))
        if best_score is None or score < best_score:
            best, best_score = f"{first}\n{second}", score
    return best


def build_cues(words: list[Word]) -> list[tuple[float, float, str]]:
    max_chars = 84
    max_seconds = 6.0
    pause_break = 0.65
    min_seconds = 0.55
    cues: list[tuple[float, float, str]] = []
    i = 0
    while i < len(words):
        group = [words[i]]
        j = i + 1
        while j < len(words):
            candidate = words[j]
            duration = candidate.end - group[0].start
            gap = candidate.start - group[-1].end
            sentence_end = bool(re.search(r"[.!?…][\"'»”)]?$", group[-1].text.strip()))
            if len(clean_join(group + [candidate])) > max_chars or duration > max_seconds or gap > pause_break:
                break
            if sentence_end and (group[-1].end - group[0].start) >= min_seconds:
                break
            group.append(candidate)
            j += 1
        text = clean_join(group)
        if text:
            start = max(0.0, group[0].start)
            end = max(start + min_seconds, group[-1].end)
            if cues and start <= cues[-1][1]:
                start = cues[-1][1] + 0.001
                end = max(end, start + min_seconds)
            cues.append((start, end, text))
        i = max(j, i + 1)
    return cues


def cues_from_segments(segments: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    cues = []
    for index, (start, end, text) in enumerate(segments):
        if index + 1 < len(segments):
            end = min(end, segments[index + 1][0] - 0.05)
        cues.append((start, max(start + 0.55, end), text))
    return cues


def format_txt(segments: list[tuple[float, str]], with_timestamps: bool) -> str:
    if with_timestamps:
        return "\n".join(f"[{readable_time(start)}] {text}" for start, text in segments).strip() + "\n"
    paragraphs: list[str] = []
    current: list[str] = []
    length = 0
    for _, text in segments:
        current.append(text)
        length += len(text)
        if length >= 700 or (length >= 350 and re.search(r"[.!?…][\"'»”)]?$", text)):
            paragraphs.append(" ".join(current).strip())
            current = []
            length = 0
    if current:
        paragraphs.append(" ".join(current).strip())
    return "\n\n".join(p for p in paragraphs if p).strip() + "\n"


def format_srt(cues: list[tuple[float, float, str]]) -> str:
    blocks = [
        f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{wrap_cue(text)}"
        for index, (start, end, text) in enumerate(cues, start=1)
    ]
    return "\n\n".join(blocks).rstrip() + "\n"


def format_vtt(cues: list[tuple[float, float, str]]) -> str:
    blocks = ["WEBVTT", ""]
    for start, end, text in cues:
        blocks.append(f"{srt_time(start).replace(',', '.')} --> {srt_time(end).replace(',', '.')}")
        blocks.append(wrap_cue(text))
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"


# ---- loop protection ------------------------------------------------------------------

def _normalized(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def looks_like_internal_loop(text: str) -> bool:
    """Obvious hallucination loops inside one segment; normal repeated speech passes."""
    words = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
    if len(words) < 24:
        return False
    trigrams = [tuple(words[i : i + 3]) for i in range(len(words) - 2)]
    if trigrams and len(set(trigrams)) / len(trigrams) < 0.22:
        return True
    for size in range(2, min(9, len(words) // 4 + 1)):
        pattern = words[:size]
        repeats = 0
        pos = 0
        while pos + size <= len(words) and words[pos : pos + size] == pattern:
            repeats += 1
            pos += size
        if repeats >= 5 and pos >= len(words) * 0.7:
            return True
    return False


class LoopFilter:
    """Drops loop segments and more than two identical segments in a row."""

    def __init__(self) -> None:
        self.previous = ""
        self.streak = 0
        self.dropped = 0

    def keep(self, text: str) -> bool:
        normalized = _normalized(text)
        if not normalized:
            return False
        if looks_like_internal_loop(text):
            self.dropped += 1
            return False
        if normalized == self.previous:
            self.streak += 1
        else:
            self.previous = normalized
            self.streak = 1
        if self.streak > 2:
            self.dropped += 1
            return False
        return True


# ---- models -----------------------------------------------------------------------------

def _repo_folder(model_name: str) -> str:
    from faster_whisper.utils import _MODELS

    repo = _MODELS.get(model_name, model_name)
    return "models--" + repo.replace("/", "--")


def model_roots() -> list[Path]:
    roots = [paths.data_dir() / "models"]
    znambo = paths.znambo_dir()
    if znambo:
        roots.append(znambo / "models")
    roots.append(Path(r"C:\ZNAMBO-Transcriber\models"))
    return roots


def find_model(model_name: str) -> Path | None:
    """Cache folder that already holds this model (RNGN's own or ZNAMBO Transcriber's)."""
    folder = _repo_folder(model_name)
    for root in model_roots():
        snapshots = root / folder / "snapshots"
        if snapshots.is_dir() and any(snapshots.glob("*/model.bin")):
            return root
    return None


def models_status() -> list[dict]:
    result = []
    for key, profile in MODELS.items():
        root = find_model(str(profile["model"]))
        result.append(
            {
                "id": key,
                "label": profile["label"],
                "description": profile["description"],
                "installed": root is not None,
                "location": str(root) if root else None,
                "shared_with_znambo": bool(root and paths.znambo_dir() and str(root).startswith(str(paths.znambo_dir()))),
                "size_mb": int(profile["size"]) // 1_000_000,
            }
        )
    return result


def _folder_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def ensure_model(model_key: str, *, token: CancelToken = NEVER, report: Report = QUIET) -> Path:
    profile = MODELS.get(model_key, MODELS["turbo"])
    name = str(profile["model"])
    found = find_model(name)
    if found:
        return found
    root = paths.data_dir() / "models"
    root.mkdir(parents=True, exist_ok=True)
    expected = int(profile["size"])
    target = root / _repo_folder(name)
    outcome: dict = {}

    def worker() -> None:
        try:
            from faster_whisper.utils import download_model

            download_model(name, cache_dir=str(root))
            outcome["ok"] = True
        except Exception as exc:  # reported below
            outcome["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    report.status(f"Скачиваю модель «{profile['label']}» (один раз)…")
    while thread.is_alive():
        if token.wait(1.0):
            raise OperationCancelled()
        done = _folder_size(target) if target.exists() else 0
        report.progress(min(99.0, done / expected * 100.0))
        report.status(
            f"Скачиваю модель «{profile['label']}» (один раз) · {done / 1e9:.2f} из {expected / 1e9:.1f} ГБ"
        )
    if "error" in outcome:
        raise UserFacingError(
            "Не удалось скачать модель распознавания.",
            kind="network",
            hint="Проверь интернет или VPN и повтори. Модель скачивается один раз.",
            details=str(outcome["error"]),
        )
    return root


_model_lock = threading.Lock()
_cached: dict = {"key": None, "model": None}


def release_model() -> None:
    with _model_lock:
        _cached["key"] = None
        _cached["model"] = None
        gc.collect()


def _load_model(name: str, device: str, compute_type: str, root: Path):
    key = (name, device, compute_type, str(root))
    with _model_lock:
        if _cached["key"] == key and _cached["model"] is not None:
            return _cached["model"]
        _cached["key"] = None
        _cached["model"] = None
        gc.collect()
        from faster_whisper import WhisperModel

        model = WhisperModel(
            name,
            device=device,
            compute_type=compute_type,
            download_root=str(root),
            local_files_only=True,
            cpu_threads=max(1, min(8, os.cpu_count() or 4)),
            num_workers=1,
        )
        _cached["key"] = key
        _cached["model"] = model
        return model


def cuda_ready() -> bool:
    if os.name == "nt" and gpu.activate() is None:
        return False
    return gpu.cuda_device_count() > 0


def _looks_like_cuda_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(needle in text for needle in ("cublas", "cudnn", "cuda", "nvcuda", ".dll", "driver", "out of memory"))


# ---- transcription --------------------------------------------------------------------

def _collect(segments_iter, *, offset: float, need_words: bool, loop_filter: LoopFilter, token: CancelToken,
             segments: list, words: list[Word], on_progress) -> None:
    for segment in segments_iter:
        token.raise_if_cancelled()
        text = (segment.text or "").strip()
        start = offset + float(segment.start)
        end = offset + float(segment.end)
        if text and loop_filter.keep(text):
            segments.append((start, end, text))
            if need_words and getattr(segment, "words", None):
                for word in segment.words:
                    value = (getattr(word, "word", "") or "").strip()
                    if value:
                        words.append(Word(offset + float(word.start), offset + float(word.end), value))
        on_progress(end)


def _transcribe_mixed(model, media: Path, *, beam_size: int, need_words: bool, token: CancelToken,
                      report: Report, where: str, loop_filter: LoopFilter):
    from faster_whisper import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    report.status("Авто-микс языков · ищу речь…")
    audio = decode_audio(str(media), sampling_rate=16000)
    duration = len(audio) / 16000.0
    if duration <= 0:
        raise UserFacingError("В файле нет звуковой дорожки.", kind="ffmpeg")
    chunks = get_speech_timestamps(
        audio,
        VadOptions(
            min_speech_duration_ms=180,
            max_speech_duration_s=MIXED_MAX_SPEECH_SECONDS,
            min_silence_duration_ms=MIXED_MIN_SILENCE_MS,
            speech_pad_ms=MIXED_SPEECH_PAD_MS,
        ),
        sampling_rate=16000,
    ) or [{"start": 0, "end": len(audio)}]
    report.log(f"mixed-language: speech_chunks={len(chunks)}")

    segments: list = []
    words: list[Word] = []
    languages: dict[str, float] = {}
    for index, chunk in enumerate(chunks, start=1):
        token.raise_if_cancelled()
        start_sample = max(0, int(chunk.get("start", 0)))
        end_sample = min(len(audio), int(chunk.get("end", len(audio))))
        if end_sample <= start_sample:
            continue
        offset = start_sample / 16000.0
        piece = audio[start_sample:end_sample]
        segments_iter, info = model.transcribe(
            piece, language=None, beam_size=beam_size, vad_filter=False, word_timestamps=need_words, **DECODE_OPTIONS
        )
        code = str(getattr(info, "language", "") or "")
        if code:
            languages[code] = languages.get(code, 0.0) + len(piece) / 16000.0
        _collect(segments_iter, offset=offset, need_words=need_words, loop_filter=loop_filter, token=token,
                 segments=segments, words=words, on_progress=lambda _end: None)
        pct = 100.0 * end_sample / len(audio)
        report.progress(min(99.0, pct))
        report.status(f"Распознаю речь · {pct:.0f}% · {language_label(code)} · {where}")
    segments.sort(key=lambda item: item[0])
    words.sort(key=lambda item: (item.start, item.end))
    return segments, words, duration, languages


def _unique(path: Path) -> Path:
    """`name.transcript.txt` -> `name (2).transcript.txt` when the file already exists."""
    if not path.exists():
        return path
    suffix = "".join(path.suffixes[-2:]) if len(path.suffixes) >= 2 else path.suffix
    base = path.name[: -len(suffix)] if suffix else path.name
    index = 2
    while True:
        candidate = path.with_name(f"{base} ({index}){suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def transcribe_media(
    media_path: Path,
    output_dir: Path,
    *,
    model_key: str = "turbo",
    language_id: str = "mixed",
    with_timestamps: bool = False,
    formats: tuple[str, ...] = ("txt", "srt"),
    allow_gpu: bool = True,
    token: CancelToken = NEVER,
    report: Report = QUIET,
) -> TranscriptResult:
    media = Path(media_path)
    if not media.is_file():
        raise UserFacingError("Файл не найден.", kind="unknown", hint=str(media))
    if media.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UserFacingError(f"Формат {media.suffix} не поддерживается.", kind="unsupported",
                              hint="Подойдут MP3, M4A, WAV, MP4, MOV, MKV и другие.")
    formats = tuple(fmt for fmt in OUTPUT_FORMATS if fmt in formats) or ("txt",)
    need_words = "srt" in formats or "vtt" in formats
    profile = MODELS.get(model_key, MODELS["turbo"])
    code = language_code(language_id)
    mixed = code == MIXED_LANGUAGE_SENTINEL
    output_dir.mkdir(parents=True, exist_ok=True)

    root = ensure_model(model_key, token=token, report=report)
    token.raise_if_cancelled()

    use_cuda = allow_gpu and cuda_ready()
    attempts = [("cuda", "float16"), ("cpu", "int8")] if use_cuda else [("cpu", "int8")]
    if not use_cuda:
        report.log("NVIDIA-ускорение недоступно: распознаю на процессоре.")
    started = time.monotonic()
    last_error: Exception | None = None

    for device, compute_type in attempts:
        where = "видеокарта" if device == "cuda" else "процессор"
        try:
            report.progress(0)
            report.status(f"Загружаю модель «{profile['label']}» · {where}…")
            report.log(f"model={profile['model']} device={device} compute={compute_type} language={language_id}")
            model = _load_model(str(profile["model"]), device, compute_type, root)
            token.raise_if_cancelled()
            loop_filter = LoopFilter()
            if mixed:
                segments, words, duration, languages = _transcribe_mixed(
                    model, media, beam_size=int(profile["beam_size"]), need_words=need_words,
                    token=token, report=report, where=where, loop_filter=loop_filter,
                )
            else:
                report.status(f"Распознаю речь · {where}…")
                segments_iter, info = model.transcribe(
                    str(media),
                    language=code,
                    beam_size=int(profile["beam_size"]),
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 700},
                    word_timestamps=need_words,
                    **DECODE_OPTIONS,
                )
                duration = float(getattr(info, "duration", 0.0) or 0.0)
                detected = str(getattr(info, "language", "") or "")
                languages = {detected: duration} if detected else {}
                segments, words = [], []

                def on_progress(end: float) -> None:
                    if duration > 0:
                        pct = min(99.0, 100.0 * end / duration)
                        report.progress(pct)
                        report.status(f"Распознаю речь · {pct:.0f}% · {where}")

                _collect(segments_iter, offset=0.0, need_words=need_words, loop_filter=loop_filter, token=token,
                         segments=segments, words=words, on_progress=on_progress)

            if not segments:
                raise UserFacingError("Речь в файле не найдена.", kind="unknown",
                                      hint="Проверь, что в файле есть звук с голосом.")
            if loop_filter.dropped:
                report.log(f"Убрано зацикленных фрагментов: {loop_filter.dropped}")

            base = safe_stem(media)
            outputs: list[Path] = []
            if "txt" in formats:
                target = _unique(output_dir / f"{base}.transcript.txt")
                target.write_text(format_txt([(s, t) for s, _e, t in segments], with_timestamps), encoding="utf-8-sig")
                outputs.append(target)
            if need_words:
                cues = build_cues(words) if words else cues_from_segments(segments)
                if "srt" in formats:
                    target = _unique(output_dir / f"{base}.subtitles.srt")
                    target.write_text(format_srt(cues), encoding="utf-8-sig")
                    outputs.append(target)
                if "vtt" in formats:
                    target = _unique(output_dir / f"{base}.subtitles.vtt")
                    target.write_text(format_vtt(cues), encoding="utf-8")
                    outputs.append(target)
            result = TranscriptResult(outputs, device, duration, time.monotonic() - started, languages, loop_filter.dropped)
            report.progress(100)
            report.status(result.summary())
            report.log(result.summary())
            return result
        except (OperationCancelled, UserFacingError):
            raise
        except Exception as exc:
            last_error = exc
            report.log(f"Распознавание ({device}) не удалось: {exc}")
            if device == "cuda" and _looks_like_cuda_error(exc):
                report.status("Видеокарта не справилась, переключаюсь на процессор…")
                release_model()
                continue
            raise UserFacingError("Не удалось расшифровать файл.", kind="unknown", details=str(exc)) from exc
    raise UserFacingError("Не удалось расшифровать файл.", kind="unknown", details=str(last_error))
