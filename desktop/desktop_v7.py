from __future__ import annotations

import gc
import logging
import re
from collections import Counter
from pathlib import Path

import desktop_app
from faster_whisper.audio import decode_audio

APP_VERSION = "1.2.0"
SAMPLE_RATE = 16000
PRIMARY_CHUNK_SECONDS = 120
RETRY_CHUNK_SECONDS = 30

# Make the running build obvious in the title bar and dialogs.
desktop_app.APP_NAME = f"ZNAMBO Transcriber v{APP_VERSION}"


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower().replace("ё", "е"), flags=re.UNICODE)


def _normalized(text: str) -> str:
    return " ".join(_words(text))


def _looks_like_loop(text: str) -> bool:
    """Detect decoder hallucination loops without penalizing short natural repeats."""
    words = _words(text)
    if len(words) < 10:
        return False

    counts = Counter(words)
    if counts.most_common(1)[0][1] / len(words) >= 0.55:
        return True

    unique_ratio = len(counts) / len(words)
    if len(words) >= 20 and unique_ratio <= 0.18:
        return True

    if len(words) >= 18:
        trigrams = [tuple(words[i : i + 3]) for i in range(len(words) - 2)]
        if trigrams and len(set(trigrams)) / len(trigrams) <= 0.18:
            return True

    # Catch a short phrase repeated five or more times through most of a segment.
    for size in range(1, min(8, len(words) // 5 + 1)):
        for start in range(min(size, len(words))):
            pattern = words[start : start + size]
            if not pattern:
                continue
            pos = start
            repeats = 0
            while pos + size <= len(words) and words[pos : pos + size] == pattern:
                repeats += 1
                pos += size
            if repeats >= 5 and (pos - start) >= len(words) * 0.65:
                return True

    return False


def _decode_segments(
    model,
    audio_chunk,
    language: str | None,
    beam_size: int,
    *,
    retry_mode: bool = False,
):
    temperatures = (
        (0.2, 0.4, 0.6, 0.8, 1.0)
        if retry_mode
        else (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    )
    segments, info = model.transcribe(
        audio_chunk,
        language=language,
        beam_size=1 if retry_mode else beam_size,
        best_of=5,
        vad_filter=True,
        vad_parameters={
            "threshold": 0.5,
            "min_silence_duration_ms": 500,
            "max_speech_duration_s": 28,
        },
        condition_on_previous_text=False,
        temperature=temperatures,
        compression_ratio_threshold=2.2,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6,
        repetition_penalty=1.20 if retry_mode else 1.12,
        no_repeat_ngram_size=3,
        max_new_tokens=96 if retry_mode else 128,
        word_timestamps=False,
    )
    return segments, info


def _collect_clean_segments(segments) -> tuple[list[tuple[float, str]], int]:
    output: list[tuple[float, str]] = []
    bad = 0
    previous = ""
    same_streak = 0

    for segment in segments:
        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue

        if _looks_like_loop(text):
            bad += 1
            logging.warning(
                "Dropped repetition-loop segment %.2f-%.2f: %r",
                float(getattr(segment, "start", 0.0)),
                float(getattr(segment, "end", 0.0)),
                text[:240],
            )
            continue

        normalized = _normalized(text)
        if normalized and normalized == previous:
            same_streak += 1
        else:
            previous = normalized
            same_streak = 1

        if same_streak > 2:
            bad += 1
            logging.warning("Dropped repeated consecutive segment: %r", text[:240])
            continue

        output.append((float(segment.start), text))

    return output, bad


def _retry_chunk_in_small_windows(
    model,
    audio_chunk,
    language: str | None,
    beam_size: int,
) -> list[tuple[float, str]]:
    recovered: list[tuple[float, str]] = []
    retry_samples = SAMPLE_RATE * RETRY_CHUNK_SECONDS

    for offset_samples in range(0, len(audio_chunk), retry_samples):
        small = audio_chunk[offset_samples : offset_samples + retry_samples]
        if len(small) < SAMPLE_RATE // 2:
            continue
        segments, _ = _decode_segments(
            model,
            small,
            language,
            beam_size,
            retry_mode=True,
        )
        clean, _ = _collect_clean_segments(segments)
        offset_seconds = offset_samples / SAMPLE_RATE
        recovered.extend((offset_seconds + start, text) for start, text in clean)

    return recovered


def robust_transcribe(
    self,
    media_path: Path,
    profile: dict[str, object],
    language: str | None,
    timestamps: bool,
    progress_callback,
    status_callback,
) -> tuple[Path, str]:
    model_name = str(profile["model"])
    beam_size = int(profile["beam_size"])

    self.refresh_gpu()
    attempts = [True, False] if self.gpu_visible else [False]
    last_error: Exception | None = None

    status_callback("Декодирование аудиодорожки…")
    progress_callback(1)
    audio = decode_audio(str(media_path), sampling_rate=SAMPLE_RATE)
    total_samples = len(audio)
    if total_samples < SAMPLE_RATE // 2:
        raise RuntimeError("В файле не удалось найти достаточно аудио для распознавания.")

    total_duration = total_samples / SAMPLE_RATE
    primary_samples = SAMPLE_RATE * PRIMARY_CHUNK_SECONDS

    try:
        for attempt_index, prefer_gpu in enumerate(attempts):
            parts: list[tuple[float, str]] = []
            effective_language = language
            dropped_loops = 0

            try:
                status_callback(
                    f"Загрузка {model_name}. При первом запуске модель скачивается один раз…"
                )
                model, actual_device, _ = self._load(
                    model_name, prefer_gpu=prefer_gpu
                )
                device_name = "NVIDIA GPU" if actual_device == "cuda" else "CPU"

                for chunk_start in range(0, total_samples, primary_samples):
                    chunk_end = min(total_samples, chunk_start + primary_samples)
                    chunk_audio = audio[chunk_start:chunk_end]
                    start_seconds = chunk_start / SAMPLE_RATE
                    end_seconds = chunk_end / SAMPLE_RATE
                    status_callback(
                        f"Распознавание на {device_name}: "
                        f"{desktop_app.readable_timestamp(start_seconds)}–"
                        f"{desktop_app.readable_timestamp(end_seconds)}"
                    )

                    segments, info = _decode_segments(
                        model,
                        chunk_audio,
                        effective_language,
                        beam_size,
                    )
                    clean, bad = _collect_clean_segments(segments)

                    if effective_language is None:
                        detected = str(getattr(info, "language", "") or "").strip()
                        if detected:
                            effective_language = detected
                            logging.info("Detected language fixed to %s", effective_language)

                    if bad:
                        dropped_loops += bad
                        status_callback(
                            "Обнаружено зацикливание Whisper. "
                            "Перезапускаю этот участок по 30 секунд…"
                        )
                        logging.warning(
                            "Retrying %.2f-%.2f because %d loop segment(s) were detected",
                            start_seconds,
                            end_seconds,
                            bad,
                        )
                        clean = _retry_chunk_in_small_windows(
                            model,
                            chunk_audio,
                            effective_language,
                            beam_size,
                        )

                    parts.extend((start_seconds + start, text) for start, text in clean)
                    progress_callback(
                        min(98, max(2, int(chunk_end / total_samples * 98)))
                    )

                if not parts:
                    raise RuntimeError("Речь в файле не обнаружена.")

                output_name = f"{desktop_app.safe_stem(media_path)}.transcript.txt"
                output_path = desktop_app.DOWNLOAD_DIR / output_name
                output_path.write_text(
                    desktop_app.format_transcript(parts, timestamps),
                    encoding="utf-8-sig",
                )
                logging.info(
                    "Transcription complete version=%s duration=%.1fs parts=%d dropped_loops=%d device=%s",
                    APP_VERSION,
                    total_duration,
                    len(parts),
                    dropped_loops,
                    device_name,
                )
                return output_path, device_name

            except Exception as exc:
                last_error = exc
                logging.exception("Robust transcription attempt failed")
                if (
                    prefer_gpu
                    and attempt_index == 0
                    and self._looks_like_cuda_runtime_error(exc)
                ):
                    status_callback(
                        "GPU недоступен. Переключаюсь на CPU и продолжаю…"
                    )
                    self.unload()
                    continue
                raise

        raise last_error or RuntimeError("Не удалось выполнить транскрибацию.")
    finally:
        del audio
        gc.collect()


desktop_app.TranscriptionEngine.transcribe = robust_transcribe


if __name__ == "__main__":
    logging.info("Starting ZNAMBO Transcriber v%s", APP_VERSION)
    desktop_app.DesktopApp().run()
