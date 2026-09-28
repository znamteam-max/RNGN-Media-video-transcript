from __future__ import annotations

import gc
import logging
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

import desktop_app
import desktop_v7
from faster_whisper.audio import decode_audio

SAMPLE_RATE = 16000
WINDOW_SECONDS = 24.0
OVERLAP_SECONDS = 1.5
MULTILINGUAL_SENTINEL = "__multilingual_auto__"
MAX_CUE_CHARS = 78
MAX_LINE_CHARS = 40
MAX_CUE_SECONDS = 4.8
MIN_CUE_SECONDS = 0.18
PAUSE_BREAK_SECONDS = 0.48


@dataclass
class TimedWord:
    text: str
    start: float
    end: float


def srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000.0)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _clean_join(words: list[str]) -> str:
    text = " ".join(item.strip() for item in words if item.strip())
    text = re.sub(r"\s+([,.;:!?…%)\]»])", r"\1", text)
    text = re.sub(r"([«(\[])\s+", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _wrap(text: str) -> str:
    lines = textwrap.wrap(
        text.strip(),
        width=MAX_LINE_CHARS,
        break_long_words=False,
        break_on_hyphens=False,
        replace_whitespace=True,
    )
    if len(lines) <= 2:
        return "\n".join(lines)
    # The cue builder normally prevents 3+ lines. Keep at most two visually.
    return lines[0] + "\n" + " ".join(lines[1:])


def _write_srt(path: Path, cues: list[tuple[float, float, str]]) -> None:
    rows: list[str] = []
    for index, (start, end, text) in enumerate(cues, start=1):
        rows.extend(
            [
                str(index),
                f"{srt_time(start)} --> {srt_time(end)}",
                _wrap(text),
                "",
            ]
        )
    path.write_text("\n".join(rows).rstrip() + "\n", encoding="utf-8-sig")


def _decode_words(model, audio_chunk, language: str | None, beam_size: int):
    return model.transcribe(
        audio_chunk,
        language=language,
        beam_size=beam_size,
        best_of=5,
        vad_filter=True,
        vad_parameters={
            "threshold": 0.45,
            "min_speech_duration_ms": 120,
            "min_silence_duration_ms": 250,
            "speech_pad_ms": 180,
            "max_speech_duration_s": 22,
        },
        condition_on_previous_text=False,
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8),
        compression_ratio_threshold=2.2,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.62,
        repetition_penalty=1.15,
        no_repeat_ngram_size=3,
        max_new_tokens=128,
        word_timestamps=True,
    )


def _extract_words(
    segments,
    *,
    absolute_offset: float,
    owner_start: float,
    owner_end: float,
    is_last_window: bool,
) -> list[TimedWord]:
    out: list[TimedWord] = []
    for segment in segments:
        segment_text = str(getattr(segment, "text", "") or "").strip()
        if not segment_text or desktop_v7._looks_like_loop(segment_text):
            if segment_text:
                logging.warning("Dropped subtitle repetition loop: %r", segment_text[:240])
            continue

        for item in list(getattr(segment, "words", None) or []):
            text = str(getattr(item, "word", "") or "").strip()
            if not text:
                continue
            start = absolute_offset + float(getattr(item, "start", 0.0) or 0.0)
            end = absolute_offset + float(getattr(item, "end", 0.0) or 0.0)
            if end <= start:
                end = start + 0.02
            midpoint = (start + end) / 2.0
            # Each overlapping window owns only its central timeline. The overlap
            # gives Whisper acoustic context but prevents duplicate words.
            if midpoint < owner_start:
                continue
            if not is_last_window and midpoint >= owner_end:
                continue
            out.append(TimedWord(text=text, start=max(0.0, start), end=max(start + 0.02, end)))
    return out


def _dedupe_and_monotonize(words: list[TimedWord]) -> list[TimedWord]:
    if not words:
        return []
    words.sort(key=lambda item: (item.start, item.end))
    out: list[TimedWord] = []
    for word in words:
        norm = re.sub(r"\W+", "", word.text.casefold(), flags=re.UNICODE)
        if out:
            prev = out[-1]
            prev_norm = re.sub(r"\W+", "", prev.text.casefold(), flags=re.UNICODE)
            if norm and norm == prev_norm and abs(word.start - prev.start) < 0.32:
                # Keep the wider acoustic boundary when overlap produced a duplicate.
                out[-1] = TimedWord(prev.text, min(prev.start, word.start), max(prev.end, word.end))
                continue
        start = word.start
        end = max(start + 0.02, word.end)
        if out and start < out[-1].start:
            start = out[-1].start
            end = max(start + 0.02, end)
        out.append(TimedWord(word.text, start, end))
    return out


def recognize_audio_words(
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

    status_callback("SRT: анализ аудиодорожки…")
    progress_callback(1)
    audio = decode_audio(str(media_path), sampling_rate=SAMPLE_RATE)
    total_samples = len(audio)
    if total_samples < SAMPLE_RATE // 2:
        raise RuntimeError("В файле не удалось найти достаточно аудио для субтитров.")

    total_duration = total_samples / SAMPLE_RATE
    owner_samples = int(WINDOW_SECONDS * SAMPLE_RATE)
    overlap_samples = int(OVERLAP_SECONDS * SAMPLE_RATE)

    try:
        for attempt_index, prefer_gpu in enumerate(attempts):
            try:
                model, actual_device, _ = engine._load(model_name, prefer_gpu=prefer_gpu)
                device_name = "NVIDIA GPU" if actual_device == "cuda" else "CPU"
                result: list[TimedWord] = []
                fixed_language = None if multilingual else language

                for owner_start_sample in range(0, total_samples, owner_samples):
                    owner_end_sample = min(total_samples, owner_start_sample + owner_samples)
                    decode_start_sample = max(0, owner_start_sample - overlap_samples)
                    decode_end_sample = min(total_samples, owner_end_sample + overlap_samples)
                    chunk = audio[decode_start_sample:decode_end_sample]
                    if len(chunk) < SAMPLE_RATE // 2:
                        continue

                    decode_offset = decode_start_sample / SAMPLE_RATE
                    owner_start = owner_start_sample / SAMPLE_RATE
                    owner_end = owner_end_sample / SAMPLE_RATE
                    status_callback(
                        f"SRT · {device_name}: "
                        f"{desktop_app.readable_timestamp(owner_start)}–"
                        f"{desktop_app.readable_timestamp(owner_end)}"
                    )

                    chunk_language = None if multilingual else fixed_language
                    segments, info = _decode_words(model, chunk, chunk_language, beam_size)

                    if fixed_language is None and not multilingual:
                        detected = str(getattr(info, "language", "") or "").strip()
                        probability = float(getattr(info, "language_probability", 0.0) or 0.0)
                        if detected and probability >= 0.55:
                            fixed_language = detected
                            logging.info(
                                "Subtitle language fixed to %s probability=%.3f",
                                detected,
                                probability,
                            )

                    result.extend(
                        _extract_words(
                            segments,
                            absolute_offset=decode_offset,
                            owner_start=owner_start,
                            owner_end=owner_end,
                            is_last_window=owner_end_sample >= total_samples,
                        )
                    )
                    progress_callback(min(96, max(2, int(owner_end_sample / total_samples * 96))))

                cleaned = _dedupe_and_monotonize(result)
                if not cleaned:
                    raise RuntimeError("Речь в файле не обнаружена.")
                logging.info(
                    "Audio word timing complete duration=%.3fs words=%d device=%s",
                    total_duration,
                    len(cleaned),
                    device_name,
                )
                return cleaned, device_name

            except Exception as exc:
                last_error = exc
                logging.exception("Audio-only subtitle timing attempt failed")
                if prefer_gpu and attempt_index == 0 and engine._looks_like_cuda_runtime_error(exc):
                    status_callback("GPU недоступен. Переключаю SRT на CPU…")
                    engine.unload()
                    continue
                raise

        raise last_error or RuntimeError("Не удалось построить тайминги субтитров.")
    finally:
        del audio
        gc.collect()


def _build_cues(words: list[TimedWord]) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    i = 0
    while i < len(words):
        j = i
        while j + 1 < len(words):
            next_j = j + 1
            group = words[i : next_j + 1]
            candidate = _clean_join([w.text for w in group])
            duration = group[-1].end - group[0].start
            gap_after_current = words[next_j].start - words[j].end

            if len(candidate) > MAX_CUE_CHARS or duration > MAX_CUE_SECONDS:
                break

            j = next_j
            current_text = _clean_join([w.text for w in words[i : j + 1]])
            next_gap = words[j + 1].start - words[j].end if j + 1 < len(words) else 0.0
            if (
                (re.search(r"[.!?…][\"'»”)]?$", current_text) and duration >= 0.65)
                or (next_gap >= PAUSE_BREAK_SECONDS and duration >= 0.55)
                or (gap_after_current >= PAUSE_BREAK_SECONDS and duration >= 0.55)
            ):
                break

        group = words[i : j + 1]
        text = _clean_join([w.text for w in group])
        if text:
            start = group[0].start
            end = max(start + MIN_CUE_SECONDS, group[-1].end)
            cues.append((start, end, text))
        i = j + 1

    # Prevent cue overlap while preserving millisecond precision.
    adjusted: list[tuple[float, float, str]] = []
    for idx, (start, end, text) in enumerate(cues):
        if idx + 1 < len(cues):
            next_start = cues[idx + 1][0]
            if end >= next_start and next_start > start:
                end = max(start + 0.05, next_start - 0.001)
        adjusted.append((max(0.0, start), max(start + 0.05, end), text))
    return adjusted


def generate_audio_srt(
    engine,
    media_path: Path,
    profile: dict[str, object],
    language: str | None,
    progress_callback,
    status_callback,
) -> tuple[Path, str]:
    words, device_name = recognize_audio_words(
        engine,
        media_path,
        profile,
        language,
        progress_callback,
        status_callback,
    )
    progress_callback(97)
    status_callback("SRT: сборка фраз по word-level таймингам…")
    cues = _build_cues(words)
    if not cues:
        raise RuntimeError("Не удалось сформировать ни одного блока субтитров.")

    output = desktop_app.DOWNLOAD_DIR / f"{desktop_app.safe_stem(media_path)}.subtitles.srt"
    _write_srt(output, cues)
    progress_callback(100)
    logging.info(
        "Audio-only SRT complete media=%s words=%d cues=%d device=%s",
        media_path,
        len(words),
        len(cues),
        device_name,
    )
    return output, device_name
