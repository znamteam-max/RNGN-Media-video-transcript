from __future__ import annotations

import gc
import logging
from pathlib import Path

import desktop_app
import desktop_v7
import desktop_v8  # noqa: F401  # premium UI + robust single-language engine
from faster_whisper.audio import decode_audio

APP_VERSION = "1.4.0"
MULTILINGUAL_SENTINEL = "__multilingual_auto__"
MULTILINGUAL_CHUNK_SECONDS = 30

# Expose a real mixed-language mode in the existing language selector.
desktop_app.LANGUAGES = {
    "Русский": "ru",
    "Мультиязычный — авто": MULTILINGUAL_SENTINEL,
    "Определить автоматически": None,
    "Английский": "en",
}

desktop_app.APP_NAME = f"ZNAMBO Transcriber v{APP_VERSION}"

# desktop_v8 imports desktop_v7, so at this point this is the robust
# anti-repetition single-language implementation from v1.2/v1.3.
_single_language_transcribe = desktop_app.TranscriptionEngine.transcribe


def multilingual_transcribe(
    self,
    media_path: Path,
    profile: dict[str, object],
    language: str | None,
    timestamps: bool,
    progress_callback,
    status_callback,
) -> tuple[Path, str]:
    # Every existing language mode continues to use the proven robust engine.
    if language != MULTILINGUAL_SENTINEL:
        return _single_language_transcribe(
            self,
            media_path,
            profile,
            language,
            timestamps,
            progress_callback,
            status_callback,
        )

    model_name = str(profile["model"])
    beam_size = int(profile["beam_size"])

    self.refresh_gpu()
    attempts = [True, False] if self.gpu_visible else [False]
    last_error: Exception | None = None

    status_callback("Мультиязычный режим: декодирование аудиодорожки…")
    progress_callback(1)
    audio = decode_audio(str(media_path), sampling_rate=desktop_v7.SAMPLE_RATE)
    total_samples = len(audio)
    if total_samples < desktop_v7.SAMPLE_RATE // 2:
        raise RuntimeError("В файле не удалось найти достаточно аудио для распознавания.")

    total_duration = total_samples / desktop_v7.SAMPLE_RATE
    chunk_samples = desktop_v7.SAMPLE_RATE * MULTILINGUAL_CHUNK_SECONDS

    try:
        for attempt_index, prefer_gpu in enumerate(attempts):
            parts: list[tuple[float, str]] = []
            detected_languages: dict[str, int] = {}
            dropped_loops = 0

            try:
                status_callback(
                    f"Загрузка {model_name}. При первом запуске модель скачивается один раз…"
                )
                model, actual_device, _ = self._load(
                    model_name,
                    prefer_gpu=prefer_gpu,
                )
                device_name = "NVIDIA GPU" if actual_device == "cuda" else "CPU"

                # Crucial difference from the normal Auto mode: every 30-second
                # window is sent with language=None. faster-whisper therefore
                # performs language detection again for every window instead of
                # locking the whole film to the first detected language.
                for chunk_start in range(0, total_samples, chunk_samples):
                    chunk_end = min(total_samples, chunk_start + chunk_samples)
                    chunk_audio = audio[chunk_start:chunk_end]
                    if len(chunk_audio) < desktop_v7.SAMPLE_RATE // 2:
                        continue

                    start_seconds = chunk_start / desktop_v7.SAMPLE_RATE
                    end_seconds = chunk_end / desktop_v7.SAMPLE_RATE
                    status_callback(
                        f"Мультиязычный · {device_name}: "
                        f"{desktop_app.readable_timestamp(start_seconds)}–"
                        f"{desktop_app.readable_timestamp(end_seconds)}"
                    )

                    segments, info = desktop_v7._decode_segments(
                        model,
                        chunk_audio,
                        None,
                        beam_size,
                    )
                    clean, bad = desktop_v7._collect_clean_segments(segments)

                    detected = str(getattr(info, "language", "") or "").strip()
                    probability = float(
                        getattr(info, "language_probability", 0.0) or 0.0
                    )
                    if detected:
                        detected_languages[detected] = detected_languages.get(detected, 0) + 1
                        logging.info(
                            "Multilingual chunk %.2f-%.2f detected language=%s probability=%.3f",
                            start_seconds,
                            end_seconds,
                            detected,
                            probability,
                        )

                    if bad:
                        dropped_loops += bad
                        status_callback(
                            "Обнаружено зацикливание Whisper. "
                            "Перезапускаю этот 30-секундный участок…"
                        )
                        logging.warning(
                            "Multilingual retry %.2f-%.2f because %d loop segment(s) were detected",
                            start_seconds,
                            end_seconds,
                            bad,
                        )
                        # Retry still uses language=None, so a failed Serbian,
                        # English, etc. window is never forced into the language
                        # detected in any neighboring window.
                        clean = desktop_v7._retry_chunk_in_small_windows(
                            model,
                            chunk_audio,
                            None,
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

                languages_summary = ", ".join(
                    f"{code}:{count}"
                    for code, count in sorted(
                        detected_languages.items(),
                        key=lambda item: item[1],
                        reverse=True,
                    )
                )
                logging.info(
                    "Multilingual transcription complete version=%s duration=%.1fs parts=%d "
                    "dropped_loops=%d device=%s languages=%s",
                    APP_VERSION,
                    total_duration,
                    len(parts),
                    dropped_loops,
                    device_name,
                    languages_summary or "unknown",
                )
                return output_path, device_name

            except Exception as exc:
                last_error = exc
                logging.exception("Multilingual transcription attempt failed")
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


desktop_app.TranscriptionEngine.transcribe = multilingual_transcribe


if __name__ == "__main__":
    logging.info("Starting ZNAMBO Transcriber v%s multilingual", APP_VERSION)
    desktop_app.DesktopApp().run()
