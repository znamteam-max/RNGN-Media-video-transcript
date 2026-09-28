from __future__ import annotations

import gc
import logging
import re
import textwrap
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import desktop_app
import desktop_v7
from faster_whisper.audio import decode_audio

SAMPLE_RATE = 16000
SUBTITLE_CHUNK_SECONDS = 30
MULTILINGUAL_SENTINEL = "__multilingual_auto__"
MAX_CUE_CHARS = 82
MAX_LINE_CHARS = 42
MAX_CUE_SECONDS = 5.8
PAUSE_BREAK_SECONDS = 0.65


@dataclass
class TimedWord:
    text: str
    start: float
    end: float


@dataclass
class RefWord:
    text: str
    char_start: int
    char_end: int
    start: float | None = None
    end: float | None = None


def _norm(text: str) -> str:
    found = re.findall(r"\w+(?:[’'\-]\w+)*", text.casefold().replace("ё", "е"), flags=re.UNICODE)
    return "".join(found)


def _strip_existing_timecodes(text: str) -> str:
    text = text.lstrip("\ufeff")
    text = re.sub(
        r"(?m)^\s*\[(?:\d{1,2}:)?\d{2}:\d{2}(?:[.,]\d{1,3})?\]\s*",
        "",
        text,
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return text.strip()


def _srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000.0)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _clean_join(words: list[str]) -> str:
    text = " ".join(item.strip() for item in words if item.strip())
    text = re.sub(r"\s+([,.;:!?…%)\]»])", r"\1", text)
    text = re.sub(r"([«(\[])\s+", r"\1", text)
    return text.strip()


def _wrap_cue(text: str) -> str:
    lines = textwrap.wrap(
        text.strip(),
        width=MAX_LINE_CHARS,
        break_long_words=False,
        break_on_hyphens=False,
        replace_whitespace=True,
    )
    if len(lines) <= 2:
        return "\n".join(lines)
    # Cue grouping normally prevents this, but never produce a 3+ line block.
    return lines[0] + "\n" + " ".join(lines[1:])


def _write_srt(path: Path, cues: list[tuple[float, float, str]]) -> None:
    rows: list[str] = []
    for index, (start, end, text) in enumerate(cues, start=1):
        rows.append(str(index))
        rows.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        rows.append(_wrap_cue(text))
        rows.append("")
    path.write_text("\n".join(rows).rstrip() + "\n", encoding="utf-8-sig")


def _fallback_words(segment) -> list[TimedWord]:
    text = str(getattr(segment, "text", "") or "").strip()
    tokens = re.findall(r"\S+", text)
    if not tokens:
        return []
    start = float(getattr(segment, "start", 0.0) or 0.0)
    end = float(getattr(segment, "end", start) or start)
    duration = max(0.05, end - start)
    step = duration / len(tokens)
    return [
        TimedWord(token, start + i * step, start + (i + 1) * step)
        for i, token in enumerate(tokens)
    ]


def _decode_word_chunk(model, audio_chunk, language: str | None, beam_size: int):
    segments, info = model.transcribe(
        audio_chunk,
        language=language,
        beam_size=beam_size,
        best_of=5,
        vad_filter=True,
        vad_parameters={
            "threshold": 0.5,
            "min_silence_duration_ms": 350,
            "max_speech_duration_s": 28,
        },
        condition_on_previous_text=False,
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        compression_ratio_threshold=2.2,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6,
        repetition_penalty=1.12,
        no_repeat_ngram_size=3,
        max_new_tokens=128,
        word_timestamps=True,
    )
    return segments, info


def recognize_timed_words(
    engine,
    media_path: Path,
    profile: dict[str, object],
    language: str | None,
    progress_callback,
    status_callback,
) -> tuple[list[TimedWord], str]:
    model_name = str(profile["model"])
    beam_size = int(profile["beam_size"])
    multilingual = language == MULTILINGUAL_SENTINEL

    engine.refresh_gpu()
    attempts = [True, False] if engine.gpu_visible else [False]
    last_error: Exception | None = None

    status_callback("Субтитры: декодирование аудиодорожки…")
    progress_callback(1)
    audio = decode_audio(str(media_path), sampling_rate=SAMPLE_RATE)
    total_samples = len(audio)
    if total_samples < SAMPLE_RATE // 2:
        raise RuntimeError("В файле не удалось найти достаточно аудио для субтитров.")

    chunk_samples = SAMPLE_RATE * SUBTITLE_CHUNK_SECONDS

    try:
        for attempt_index, prefer_gpu in enumerate(attempts):
            try:
                model, actual_device, _ = engine._load(model_name, prefer_gpu=prefer_gpu)
                device_name = "NVIDIA GPU" if actual_device == "cuda" else "CPU"
                result: list[TimedWord] = []
                effective_language = None if multilingual else language

                for chunk_start in range(0, total_samples, chunk_samples):
                    chunk_end = min(total_samples, chunk_start + chunk_samples)
                    chunk_audio = audio[chunk_start:chunk_end]
                    if len(chunk_audio) < SAMPLE_RATE // 2:
                        continue

                    offset = chunk_start / SAMPLE_RATE
                    end_seconds = chunk_end / SAMPLE_RATE
                    status_callback(
                        f"Субтитры · {device_name}: "
                        f"{desktop_app.readable_timestamp(offset)}–"
                        f"{desktop_app.readable_timestamp(end_seconds)}"
                    )

                    chunk_language = None if multilingual else effective_language
                    segments, info = _decode_word_chunk(
                        model,
                        chunk_audio,
                        chunk_language,
                        beam_size,
                    )

                    if effective_language is None and not multilingual:
                        detected = str(getattr(info, "language", "") or "").strip()
                        if detected:
                            effective_language = detected
                            logging.info("Subtitle language fixed to %s", detected)

                    for segment in segments:
                        segment_text = str(getattr(segment, "text", "") or "").strip()
                        if not segment_text or desktop_v7._looks_like_loop(segment_text):
                            if segment_text:
                                logging.warning("Dropped subtitle repetition loop: %r", segment_text[:240])
                            continue

                        segment_words = list(getattr(segment, "words", None) or [])
                        if segment_words:
                            for word in segment_words:
                                text = str(getattr(word, "word", "") or "").strip()
                                if not text:
                                    continue
                                start = offset + float(getattr(word, "start", 0.0) or 0.0)
                                end = offset + float(getattr(word, "end", 0.0) or 0.0)
                                if end <= start:
                                    end = start + 0.04
                                result.append(TimedWord(text, start, end))
                        else:
                            for word in _fallback_words(segment):
                                result.append(
                                    TimedWord(word.text, offset + word.start, offset + word.end)
                                )

                    progress_callback(min(96, max(2, int(chunk_end / total_samples * 96))))

                if not result:
                    raise RuntimeError("Речь в файле не обнаружена.")

                # Guard against rare timestamp regressions.
                cleaned: list[TimedWord] = []
                last_start = 0.0
                for word in result:
                    start = max(last_start, word.start)
                    end = max(start + 0.02, word.end)
                    cleaned.append(TimedWord(word.text, start, end))
                    last_start = start
                return cleaned, device_name

            except Exception as exc:
                last_error = exc
                logging.exception("Subtitle timing attempt failed")
                if (
                    prefer_gpu
                    and attempt_index == 0
                    and engine._looks_like_cuda_runtime_error(exc)
                ):
                    status_callback("GPU недоступен. Переключаю субтитры на CPU…")
                    engine.unload()
                    continue
                raise

        raise last_error or RuntimeError("Не удалось построить тайминги субтитров.")
    finally:
        del audio
        gc.collect()


def _recognized_cues(words: list[TimedWord]) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    i = 0
    while i < len(words):
        j = i
        while j + 1 < len(words):
            current = words[i : j + 2]
            candidate = _clean_join([item.text for item in current])
            duration = current[-1].end - current[0].start
            if len(candidate) > MAX_CUE_CHARS or duration > MAX_CUE_SECONDS:
                break
            j += 1
            gap = words[j + 1].start - words[j].end if j + 1 < len(words) else 0.0
            text_now = _clean_join([item.text for item in words[i : j + 1]])
            if (
                (re.search(r"[.!?…][\"'»”)]?$", text_now) and duration >= 0.9)
                or (gap >= PAUSE_BREAK_SECONDS and duration >= 0.8)
            ):
                break

        group = words[i : j + 1]
        text = _clean_join([item.text for item in group])
        if text:
            cues.append((group[0].start, max(group[0].start + 0.12, group[-1].end), text))
        i = j + 1
    return _deoverlap(cues)


def _reference_words(text: str) -> list[RefWord]:
    return [
        RefWord(match.group(0), match.start(), match.end())
        for match in re.finditer(r"\w+(?:[’'\-]\w+)*", text, flags=re.UNICODE)
    ]


def _recognized_tokens(words: list[TimedWord]) -> tuple[list[str], list[int]]:
    tokens: list[str] = []
    owners: list[int] = []
    for index, word in enumerate(words):
        found = re.findall(
            r"\w+(?:[’'\-]\w+)*",
            word.text.casefold().replace("ё", "е"),
            flags=re.UNICODE,
        )
        for token in found:
            normalized = _norm(token)
            if normalized:
                tokens.append(normalized)
                owners.append(index)
    return tokens, owners


def _align_reference(text: str, recognized: list[TimedWord]) -> tuple[list[RefWord], float]:
    ref_words = _reference_words(text)
    if not ref_words:
        raise RuntimeError("В выбранном TXT нет слов для синхронизации.")

    ref_tokens = [_norm(item.text) for item in ref_words]
    rec_tokens, owners = _recognized_tokens(recognized)
    if not rec_tokens:
        raise RuntimeError("Не удалось получить слова с таймингами из медиа.")

    matcher = SequenceMatcher(None, ref_tokens, rec_tokens, autojunk=False)
    mapping: dict[int, int] = {}
    matched = 0
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            ref_index = block.a + offset
            rec_token_index = block.b + offset
            mapping[ref_index] = owners[rec_token_index]
            matched += 1

    ratio = matched / max(1, len(ref_words))
    if len(ref_words) >= 20 and ratio < 0.18:
        raise RuntimeError(
            "Готовый TXT слишком сильно отличается от речи в выбранном медиа. "
            "Проверь, что это текст именно этого видео/аудио."
        )

    for ref_index, word_index in mapping.items():
        ref_words[ref_index].start = recognized[word_index].start
        ref_words[ref_index].end = recognized[word_index].end

    # Interpolate unmatched runs between reliable matched anchors. This preserves
    # the user's edited wording while keeping timing anchored to real speech.
    index = 0
    total_end = recognized[-1].end
    while index < len(ref_words):
        if ref_words[index].start is not None:
            index += 1
            continue
        run_start = index
        while index < len(ref_words) and ref_words[index].start is None:
            index += 1
        run_end = index

        left_index = run_start - 1
        right_index = run_end if run_end < len(ref_words) else None
        left_time = (
            float(ref_words[left_index].end)
            if left_index >= 0 and ref_words[left_index].end is not None
            else 0.0
        )
        right_time = (
            float(ref_words[right_index].start)
            if right_index is not None and ref_words[right_index].start is not None
            else total_end
        )
        count = run_end - run_start
        if right_time <= left_time:
            right_time = left_time + max(0.12 * count, 0.12)

        weights = [max(1, len(ref_words[pos].text)) for pos in range(run_start, run_end)]
        total_weight = float(sum(weights))
        cursor = left_time
        span = right_time - left_time
        for pos, weight in zip(range(run_start, run_end), weights):
            duration = span * (weight / total_weight)
            ref_words[pos].start = cursor
            ref_words[pos].end = cursor + max(0.02, duration)
            cursor += duration

    return ref_words, ratio


def _reference_cues(text: str, words: list[RefWord]) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    i = 0
    while i < len(words):
        j = i
        while j + 1 < len(words):
            next_j = j + 1
            end_char = words[next_j + 1].char_start if next_j + 1 < len(words) else len(text)
            candidate = text[words[i].char_start:end_char].strip()
            duration = float(words[next_j].end or 0.0) - float(words[i].start or 0.0)
            if len(candidate) > MAX_CUE_CHARS or duration > MAX_CUE_SECONDS:
                break
            j = next_j
            next_gap = (
                float(words[j + 1].start or 0.0) - float(words[j].end or 0.0)
                if j + 1 < len(words)
                else 0.0
            )
            current_end_char = words[j + 1].char_start if j + 1 < len(words) else len(text)
            current_text = text[words[i].char_start:current_end_char].strip()
            if (
                (re.search(r"[.!?…][\"'»”)]?$", current_text) and duration >= 0.9)
                or (next_gap >= PAUSE_BREAK_SECONDS and duration >= 0.8)
            ):
                break

        end_char = words[j + 1].char_start if j + 1 < len(words) else len(text)
        cue_text = re.sub(r"\s+", " ", text[words[i].char_start:end_char]).strip()
        start = float(words[i].start or 0.0)
        end = float(words[j].end or start + 0.12)
        if cue_text:
            cues.append((start, max(start + 0.12, end), cue_text))
        i = j + 1
    return _deoverlap(cues)


def _deoverlap(cues: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    result: list[tuple[float, float, str]] = []
    for index, (start, end, text) in enumerate(cues):
        start = max(0.0, start)
        if index + 1 < len(cues):
            next_start = max(0.0, cues[index + 1][0])
            if end >= next_start and next_start > start:
                end = max(start + 0.05, next_start - 0.001)
        end = max(start + 0.05, end)
        result.append((start, end, text))
    return result


def generate_srt(
    engine,
    media_path: Path,
    profile: dict[str, object],
    language: str | None,
    reference_txt: Path | None,
    progress_callback,
    status_callback,
) -> tuple[Path, str, float | None]:
    words, device_name = recognize_timed_words(
        engine,
        media_path,
        profile,
        language,
        progress_callback,
        status_callback,
    )
    progress_callback(97)

    match_ratio: float | None = None
    if reference_txt is not None:
        status_callback("Синхронизация готового TXT со словами в медиа…")
        try:
            reference_text = reference_txt.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            reference_text = reference_txt.read_text(encoding="utf-8", errors="replace")
        reference_text = _strip_existing_timecodes(reference_text)
        aligned, match_ratio = _align_reference(reference_text, words)
        cues = _reference_cues(reference_text, aligned)
    else:
        status_callback("Сборка SRT по точным word-level таймингам…")
        cues = _recognized_cues(words)

    if not cues:
        raise RuntimeError("Не удалось сформировать ни одного блока субтитров.")

    output = desktop_app.DOWNLOAD_DIR / f"{desktop_app.safe_stem(media_path)}.subtitles.srt"
    _write_srt(output, cues)
    progress_callback(100)
    logging.info(
        "SRT complete media=%s cues=%d reference=%s match_ratio=%s device=%s",
        media_path,
        len(cues),
        bool(reference_txt),
        f"{match_ratio:.3f}" if match_ratio is not None else "n/a",
        device_name,
    )
    return output, device_name, match_ratio
