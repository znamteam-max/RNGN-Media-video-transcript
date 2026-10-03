from __future__ import annotations

import ctypes
import gc
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[int], None]
StatusCallback = Callable[[str], None]
LogCallback = Callable[[str], None]

SUPPORTED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts", ".mts", ".m2ts",
}

MODEL_PROFILES = {
    "Быстрая — large-v3-turbo (рекомендуется)": {"model": "large-v3-turbo", "beam_size": 3},
    "Точная — large-v3 (медленнее на CPU)": {"model": "large-v3", "beam_size": 5},
}

MIXED_LANGUAGE_SENTINEL = "__mixed__"
LANGUAGES = {
    "Авто · микс языков": MIXED_LANGUAGE_SENTINEL,
    "Авто · один язык": None,
    "Русский": "ru",
    "English": "en",
    "Français": "fr",
    "Español": "es",
    "中文": "zh",
    "Deutsch": "de",
    "Português": "pt",
    "Italiano": "it",
    "日本語": "ja",
    "한국어": "ko",
    "العربية": "ar",
}

LANGUAGE_DISPLAY = {
    "ru": "Русский",
    "en": "English",
    "fr": "Français",
    "es": "Español",
    "zh": "中文",
    "de": "Deutsch",
    "pt": "Português",
    "it": "Italiano",
    "ja": "日本語",
    "ko": "한국어",
    "ar": "العربية",
}

MIXED_MAX_SPEECH_SECONDS = 18.0
MIXED_MIN_SILENCE_MS = 350
MIXED_SPEECH_PAD_MS = 180


@dataclass
class Word:
    start: float
    end: float
    text: str


def _app_data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "RNGN-Media"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "RNGN Media"
    return Path.home() / ".rngn-media"


def _safe_stem(path: Path) -> str:
    stem = re.sub(r"[^\w .()\-]+", "_", path.stem, flags=re.UNICODE).strip(" .")
    return stem or "transcript"


def _timestamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _readable_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _language_label(code: str | None) -> str:
    if not code:
        return "не определён"
    return LANGUAGE_DISPLAY.get(code, code)


def _cuda_available() -> bool:
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() <= 0:
            return False
        if os.name == "nt":
            try:
                ctypes.WinDLL("cublas64_12.dll")
            except OSError:
                return False
        return True
    except Exception:
        return False


def _looks_like_cuda_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    needles = ("cublas", "cudnn", "cuda", "nvcuda", "dll", "driver")
    return any(n in text for n in needles)


def _clean_join(words: list[Word]) -> str:
    text = " ".join(w.text.strip() for w in words if w.text.strip())
    text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _build_cues(words: list[Word]) -> list[tuple[float, float, str]]:
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
            candidate_text = _clean_join(group + [candidate])
            sentence_end = bool(re.search(r"[.!?…][\"'»”)]?$", group[-1].text.strip()))
            if len(candidate_text) > max_chars or duration > max_seconds or gap > pause_break:
                break
            if sentence_end and (group[-1].end - group[0].start) >= min_seconds:
                break
            group.append(candidate)
            j += 1
        text = _clean_join(group)
        if text:
            start = max(0.0, group[0].start)
            end = max(start + min_seconds, group[-1].end)
            if cues and start <= cues[-1][1]:
                start = cues[-1][1] + 0.001
                end = max(end, start + min_seconds)
            cues.append((start, end, text))
        i = max(j, i + 1)
    return cues


def _format_txt(segments: list[tuple[float, str]], with_timestamps: bool) -> str:
    if with_timestamps:
        return "\n".join(f"[{_readable_timestamp(start)}] {text}" for start, text in segments).strip() + "\n"
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


def _append_transcribed_segments(
    segments_iter,
    *,
    offset: float,
    make_srt: bool,
    segments_text: list[tuple[float, str]],
    words: list[Word],
) -> float:
    last_end = offset
    for segment in segments_iter:
        start = offset + float(segment.start)
        end = offset + float(segment.end)
        text = (segment.text or "").strip()
        if text:
            segments_text.append((start, text))
        if make_srt and getattr(segment, "words", None):
            for word in segment.words:
                wtext = (getattr(word, "word", "") or "").strip()
                if not wtext:
                    continue
                words.append(
                    Word(
                        offset + float(word.start),
                        offset + float(word.end),
                        wtext,
                    )
                )
        last_end = max(last_end, end)
    return last_end


def _transcribe_mixed_language(
    model,
    media_path: Path,
    *,
    beam_size: int,
    make_srt: bool,
    status: StatusCallback,
    progress: ProgressCallback,
    log: LogCallback,
) -> tuple[list[tuple[float, str]], list[Word], float, dict[str, float]]:
    from faster_whisper import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    status("Авто-микс · анализирую речь и смену языков…")
    audio = decode_audio(str(media_path), sampling_rate=16000)
    duration = len(audio) / 16000.0
    if duration <= 0:
        raise RuntimeError("В файле не найден аудиопоток.")

    speech_chunks = get_speech_timestamps(
        audio,
        VadOptions(
            min_speech_duration_ms=180,
            max_speech_duration_s=MIXED_MAX_SPEECH_SECONDS,
            min_silence_duration_ms=MIXED_MIN_SILENCE_MS,
            speech_pad_ms=MIXED_SPEECH_PAD_MS,
        ),
        sampling_rate=16000,
    )
    if not speech_chunks:
        speech_chunks = [{"start": 0, "end": len(audio)}]

    log(
        "mixed-language mode: "
        f"speech_chunks={len(speech_chunks)} max_chunk={MIXED_MAX_SPEECH_SECONDS:.0f}s"
    )

    segments_text: list[tuple[float, str]] = []
    words: list[Word] = []
    detected_seconds: dict[str, float] = {}

    for index, chunk in enumerate(speech_chunks, start=1):
        start_sample = max(0, int(chunk.get("start", 0)))
        end_sample = min(len(audio), int(chunk.get("end", len(audio))))
        if end_sample <= start_sample:
            continue

        offset = start_sample / 16000.0
        chunk_audio = audio[start_sample:end_sample]
        chunk_duration = len(chunk_audio) / 16000.0

        segments_iter, info = model.transcribe(
            chunk_audio,
            language=None,
            beam_size=beam_size,
            vad_filter=False,
            word_timestamps=make_srt,
            condition_on_previous_text=False,
        )

        code = str(getattr(info, "language", "") or "")
        probability = float(getattr(info, "language_probability", 0.0) or 0.0)
        if code:
            detected_seconds[code] = detected_seconds.get(code, 0.0) + chunk_duration

        label = _language_label(code)
        status(
            f"Авто-микс · {label} {probability:.0%} · "
            f"{_readable_timestamp(offset)} · фрагмент {index}/{len(speech_chunks)}"
        )
        log(
            f"language chunk {index}/{len(speech_chunks)} "
            f"{_readable_timestamp(offset)}-{_readable_timestamp(offset + chunk_duration)}: "
            f"{code or 'unknown'} ({probability:.1%})"
        )

        _append_transcribed_segments(
            segments_iter,
            offset=offset,
            make_srt=make_srt,
            segments_text=segments_text,
            words=words,
        )
        progress(min(96, max(5, int(5 + 91 * end_sample / len(audio)))))

    segments_text.sort(key=lambda item: item[0])
    words.sort(key=lambda item: (item.start, item.end))
    return segments_text, words, duration, detected_seconds


def transcribe_media(
    media_path: Path,
    output_dir: Path,
    *,
    profile_name: str = "Быстрая — large-v3-turbo (рекомендуется)",
    language_name: str = "Авто · микс языков",
    with_timestamps: bool = False,
    make_srt: bool = True,
    status: StatusCallback = lambda _s: None,
    progress: ProgressCallback = lambda _p: None,
    log: LogCallback = lambda _s: None,
) -> list[Path]:
    media_path = Path(media_path)
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    if media_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Неподдерживаемый формат: {media_path.suffix}")

    profile = MODEL_PROFILES.get(profile_name, MODEL_PROFILES["Быстрая — large-v3-turbo (рекомендуется)"])
    language = LANGUAGES.get(language_name, MIXED_LANGUAGE_SENTINEL)
    mixed_language = language == MIXED_LANGUAGE_SENTINEL
    output_dir.mkdir(parents=True, exist_ok=True)
    model_dir = _app_data_dir() / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise RuntimeError("Не установлен faster-whisper. Переустанови RNGN Media.") from exc

    prefer_gpu = _cuda_available()
    attempts = [("cuda", "float16"), ("cpu", "int8")] if prefer_gpu else [("cpu", "int8")]
    last_error: Exception | None = None

    for attempt_index, (device, compute_type) in enumerate(attempts, start=1):
        model = None
        try:
            progress(3)
            if device == "cpu":
                status(
                    f"Подготавливаю {profile['model']} на CPU… "
                    "Первый запуск может занять несколько минут из-за загрузки модели."
                )
            else:
                status(f"Подготавливаю {profile['model']} · NVIDIA GPU…")
            log(
                f"model={profile['model']} device={device} compute_type={compute_type} "
                f"language_mode={'mixed' if mixed_language else (language or 'auto-single')}"
            )
            model = WhisperModel(
                str(profile["model"]),
                device=device,
                compute_type=compute_type,
                download_root=str(model_dir),
                cpu_threads=max(1, min(8, os.cpu_count() or 4)),
                num_workers=1,
            )
            log("Модель загружена. Начинаю распознавание.")

            if mixed_language:
                segments_text, words, duration, detected_seconds = _transcribe_mixed_language(
                    model,
                    media_path,
                    beam_size=int(profile["beam_size"]),
                    make_srt=make_srt,
                    status=status,
                    progress=progress,
                    log=log,
                )
                if detected_seconds:
                    summary = ", ".join(
                        f"{_language_label(code)} {seconds:.0f}с"
                        for code, seconds in sorted(
                            detected_seconds.items(),
                            key=lambda item: item[1],
                            reverse=True,
                        )
                    )
                    log(f"detected languages: {summary}")
            else:
                status(f"Распознавание · {'NVIDIA GPU' if device == 'cuda' else 'CPU'}…")
                segments_iter, info = model.transcribe(
                    str(media_path),
                    language=language,
                    beam_size=int(profile["beam_size"]),
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 700},
                    word_timestamps=make_srt,
                )
                duration = float(getattr(info, "duration", 0.0) or 0.0)
                segments_text = []
                words = []
                for segment in segments_iter:
                    text = (segment.text or "").strip()
                    if text:
                        segments_text.append((float(segment.start), text))
                    if make_srt and getattr(segment, "words", None):
                        for word in segment.words:
                            wtext = (getattr(word, "word", "") or "").strip()
                            if not wtext:
                                continue
                            words.append(Word(float(word.start), float(word.end), wtext))
                    if duration > 0:
                        progress(min(96, max(5, int(5 + 91 * float(segment.end) / duration))))

            if not segments_text:
                raise RuntimeError("Речь в файле не обнаружена.")

            base = _safe_stem(media_path)
            txt_path = output_dir / f"{base}.transcript.txt"
            txt_path.write_text(_format_txt(segments_text, with_timestamps), encoding="utf-8-sig")
            outputs = [txt_path]

            if make_srt:
                if not words:
                    cues = []
                    segs = list(segments_text)
                    for idx, (start, text) in enumerate(segs):
                        end = segs[idx + 1][0] - 0.05 if idx + 1 < len(segs) else start + 4.0
                        cues.append((start, max(start + 0.55, end), text))
                else:
                    cues = _build_cues(words)
                srt_path = output_dir / f"{base}.subtitles.srt"
                blocks = [
                    f"{idx}\n{_timestamp(start)} --> {_timestamp(end)}\n{text}"
                    for idx, (start, end, text) in enumerate(cues, start=1)
                ]
                srt_path.write_text("\n\n".join(blocks).rstrip() + "\n", encoding="utf-8-sig")
                outputs.append(srt_path)

            progress(100)
            status(f"Готово · {' + '.join(p.suffix.lstrip('.') for p in outputs)}")
            return outputs
        except Exception as exc:
            last_error = exc
            log(f"transcription attempt {attempt_index} failed: {exc}")
            if device == "cuda" and _looks_like_cuda_error(exc):
                status("GPU недоступен. Переключаюсь на CPU…")
                if model is not None:
                    del model
                gc.collect()
                continue
            raise

    raise RuntimeError("Не удалось выполнить транскрибацию.") from last_error
