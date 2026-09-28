from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import ctranslate2
from faster_whisper import WhisperModel


SUPPORTED_EXTENSIONS = {
    ".m4a",
    ".mp3",
    ".wav",
    ".flac",
    ".ogg",
    ".opus",
    ".aac",
    ".wma",
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".m4v",
}


@dataclass(frozen=True)
class TranscriptionSettings:
    model: str = "large-v3"
    device: str = "auto"
    compute_type: str = "auto"
    language: str | None = None
    beam_size: int = 5
    vad_min_silence_ms: int = 700
    initial_prompt: str | None = None


@dataclass(frozen=True)
class SegmentData:
    id: int
    start: float
    end: float
    text: str
    avg_logprob: float | None
    no_speech_prob: float | None


def is_supported_media(path_or_name: str | Path) -> bool:
    return Path(path_or_name).suffix.lower() in SUPPORTED_EXTENSIONS


def resolve_device(preference: str) -> str:
    preference = preference.strip().lower()
    if preference in {"cuda", "cpu"}:
        return preference
    if preference != "auto":
        raise ValueError("device must be one of: auto, cuda, cpu")
    return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"


def resolve_compute_type(preference: str, device: str) -> str:
    preference = preference.strip().lower()
    if preference != "auto":
        return preference
    return "float16" if device == "cuda" else "int8"


def timestamp(seconds: float, *, srt: bool = False) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def readable_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def safe_stem(path: Path) -> str:
    stem = re.sub(r"[^\w .()\-]+", "_", path.stem, flags=re.UNICODE).strip(" .")
    return stem or "transcript"


def build_model(
    settings: TranscriptionSettings,
    model_dir: Path,
) -> tuple[WhisperModel, str, str]:
    device = resolve_device(settings.device)
    compute_type = resolve_compute_type(settings.compute_type, device)

    logging.info(
        "Loading model=%s device=%s compute_type=%s model_dir=%s",
        settings.model,
        device,
        compute_type,
        model_dir,
    )
    model = WhisperModel(
        settings.model,
        device=device,
        compute_type=compute_type,
        download_root=str(model_dir),
    )
    return model, device, compute_type


def transcribe_with_model(
    media_path: Path,
    output_dir: Path,
    model: WhisperModel,
    settings: TranscriptionSettings,
    *,
    device: str,
    compute_type: str,
) -> list[Path]:
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    if not is_supported_media(media_path):
        raise ValueError(f"Unsupported media format: {media_path.suffix}")

    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = safe_stem(media_path)
    txt_path = output_dir / f"{base_name}.transcript.txt"
    srt_path = output_dir / f"{base_name}.transcript.srt"
    vtt_path = output_dir / f"{base_name}.transcript.vtt"
    json_path = output_dir / f"{base_name}.transcript.json"

    logging.info("Transcribing %s", media_path)
    segments_generator, info = model.transcribe(
        str(media_path),
        language=settings.language,
        beam_size=settings.beam_size,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": settings.vad_min_silence_ms},
        condition_on_previous_text=True,
        initial_prompt=settings.initial_prompt,
        temperature=0.0,
        word_timestamps=False,
    )

    segments: list[SegmentData] = []
    for segment in segments_generator:
        text = segment.text.strip()
        if not text:
            continue
        item = SegmentData(
            id=len(segments) + 1,
            start=float(segment.start),
            end=float(segment.end),
            text=text,
            avg_logprob=_optional_float(getattr(segment, "avg_logprob", None)),
            no_speech_prob=_optional_float(getattr(segment, "no_speech_prob", None)),
        )
        segments.append(item)
        print(
            f"[{readable_timestamp(item.start)} -> {readable_timestamp(item.end)}] "
            f"{item.text}",
            flush=True,
        )

    metadata = {
        "source_file": media_path.name,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": settings.model,
        "device": device,
        "compute_type": compute_type,
        "requested_language": settings.language,
        "detected_language": getattr(info, "language", None),
        "language_probability": _optional_float(
            getattr(info, "language_probability", None)
        ),
        "duration_seconds": _optional_float(getattr(info, "duration", None)),
        "duration_after_vad_seconds": _optional_float(
            getattr(info, "duration_after_vad", None)
        ),
        "segments": [asdict(segment) for segment in segments],
    }

    _write_txt(txt_path, media_path.name, metadata, segments)
    _write_srt(srt_path, segments)
    _write_vtt(vtt_path, segments)
    json_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logging.info("Created %s output files for %s", 4, media_path.name)
    return [txt_path, srt_path, vtt_path, json_path]


def transcribe_file(
    media_path: Path,
    output_dir: Path,
    model_dir: Path,
    settings: TranscriptionSettings,
) -> list[Path]:
    model, device, compute_type = build_model(settings, model_dir)
    return transcribe_with_model(
        media_path,
        output_dir,
        model,
        settings,
        device=device,
        compute_type=compute_type,
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _write_txt(
    path: Path,
    source_name: str,
    metadata: dict[str, Any],
    segments: Iterable[SegmentData],
) -> None:
    lines = [
        f"Файл: {source_name}",
        f"Язык: {metadata.get('detected_language') or 'не определён'}",
        f"Модель: {metadata['model']}",
        "",
    ]
    for segment in segments:
        lines.append(f"[{readable_timestamp(segment.start)}] {segment.text}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_srt(path: Path, segments: Iterable[SegmentData]) -> None:
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n"
            f"{timestamp(segment.start, srt=True)} --> "
            f"{timestamp(segment.end, srt=True)}\n"
            f"{segment.text}"
        )
    path.write_text("\n\n".join(blocks).rstrip() + "\n", encoding="utf-8")


def _write_vtt(path: Path, segments: Iterable[SegmentData]) -> None:
    blocks = ["WEBVTT"]
    for segment in segments:
        blocks.append(
            f"{timestamp(segment.start)} --> {timestamp(segment.end)}\n"
            f"{segment.text}"
        )
    path.write_text("\n\n".join(blocks).rstrip() + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe a local audio/video file with faster-whisper."
    )
    parser.add_argument("media", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(os.getenv("WHISPER_MODEL_DIR", "models")),
    )
    parser.add_argument(
        "--model",
        default=os.getenv("WHISPER_MODEL", "large-v3"),
    )
    parser.add_argument(
        "--device",
        default=os.getenv("WHISPER_DEVICE", "auto"),
        choices=["auto", "cuda", "cpu"],
    )
    parser.add_argument(
        "--compute-type",
        default=os.getenv("WHISPER_COMPUTE_TYPE", "auto"),
    )
    parser.add_argument(
        "--language",
        default=os.getenv("WHISPER_LANGUAGE") or None,
        help="Language code, for example ru or en. Omit for auto-detection.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args = parse_args()
    settings = TranscriptionSettings(
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        initial_prompt=os.getenv("WHISPER_INITIAL_PROMPT") or None,
    )
    outputs = transcribe_file(
        args.media.resolve(),
        args.output_dir.resolve(),
        args.model_dir.resolve(),
        settings,
    )
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
