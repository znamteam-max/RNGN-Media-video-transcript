from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

import av
import imageio_ffmpeg

import desktop_app

VIDEO_EXTENSIONS = {
    ".mov", ".mp4", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts", ".ts", ".wmv", ".flv",
}

CONVERSION_PROFILES = {
    "MP4 для Premiere — максимальное качество": {
        "ext": ".mp4",
        "mode": "h264_premiere",
        "description": "H.264, исходное разрешение/FPS, очень высокое качество; все аудиодорожки сохраняются.",
    },
    "MP4 H.265 — высокое качество": {
        "ext": ".mp4",
        "mode": "hevc",
        "description": "HEVC/H.265 для меньшего размера при высоком качестве; все аудиодорожки сохраняются.",
    },
    "MOV ProRes 422 HQ — монтаж": {
        "ext": ".mov",
        "mode": "prores",
        "description": "Монтажный ProRes 422 HQ; крупный файл, без изменения разрешения и FPS.",
    },
    "MP4 без перекодирования — 1:1": {
        "ext": ".mp4",
        "mode": "remux",
        "description": "Меняется только контейнер. Видео/аудио копируются бит-в-бит, если кодеки совместимы с MP4.",
    },
    "MOV без перекодирования — 1:1": {
        "ext": ".mov",
        "mode": "remux",
        "description": "Меняется только контейнер. Все потоки копируются бит-в-бит, если кодеки совместимы с MOV.",
    },
    "MKV без перекодирования — 1:1": {
        "ext": ".mkv",
        "mode": "remux",
        "description": "Самый универсальный remux: все потоки копируются без потери качества.",
    },
}

MP4_AUDIO_COPY_CODECS = {"aac", "alac", "mp3", "ac3", "eac3"}


def _unique_output(input_path: Path, ext: str, suffix: str) -> Path:
    base = desktop_app.DOWNLOAD_DIR / f"{desktop_app.safe_stem(input_path)}{suffix}{ext}"
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = base.with_name(f"{base.stem} ({index}){base.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _probe(path: Path) -> tuple[float, list[str], str | None]:
    duration = 0.0
    audio_codecs: list[str] = []
    video_codec: str | None = None
    with av.open(str(path)) as container:
        if container.duration is not None:
            duration = float(container.duration) / 1_000_000.0
        for stream in container.streams:
            codec_name = getattr(getattr(stream, "codec_context", None), "name", None)
            if stream.type == "video" and video_codec is None:
                video_codec = str(codec_name or "unknown")
            elif stream.type == "audio":
                audio_codecs.append(str(codec_name or "unknown"))
    return duration, audio_codecs, video_codec


def _run_ffmpeg(command: list[str], duration: float, progress_callback, status_callback) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    logging.info("FFmpeg command: %s", " ".join(command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )

    assert process.stdout is not None
    progress_callback(1)
    for raw in process.stdout:
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "out_time_us" and duration > 0:
            try:
                current = int(value) / 1_000_000.0
                progress_callback(min(98, max(1, int(current / duration * 98))))
            except ValueError:
                pass
        elif key == "speed":
            status_callback(f"Конвертация видео · {value}")

    stderr_text = ""
    if process.stderr is not None:
        stderr_text = process.stderr.read()
    code = process.wait()
    if code != 0:
        tail = "\n".join(stderr_text.strip().splitlines()[-18:])
        raise RuntimeError(
            "FFmpeg не смог выполнить конвертацию.\n\n"
            + (tail or f"Код выхода: {code}")
        )


def convert_video(
    input_path: Path,
    profile_name: str,
    progress_callback,
    status_callback,
) -> Path:
    if profile_name not in CONVERSION_PROFILES:
        raise RuntimeError("Неизвестный профиль конвертации.")
    if input_path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise RuntimeError("Для конвертации выбери видеофайл.")

    profile = CONVERSION_PROFILES[profile_name]
    mode = str(profile["mode"])
    ext = str(profile["ext"])

    status_callback("Анализ видео и аудиодорожек…")
    duration, audio_codecs, video_codec = _probe(input_path)
    logging.info(
        "Convert input=%s video_codec=%s audio_codecs=%s duration=%.3f profile=%s",
        input_path,
        video_codec,
        audio_codecs,
        duration,
        profile_name,
    )

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    if not Path(ffmpeg).is_file():
        raise RuntimeError("Встроенный FFmpeg не найден.")

    suffix_map = {
        "h264_premiere": ".premiere",
        "hevc": ".hevc",
        "prores": ".prores",
        "remux": ".remux",
    }
    output = _unique_output(input_path, ext, suffix_map.get(mode, ".converted"))
    temp = output.with_name(output.stem + ".partial" + output.suffix)
    if temp.exists():
        temp.unlink()

    base = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-progress",
        "pipe:1",
        "-nostats",
    ]

    if mode == "remux":
        # Exact stream copy: no video/audio re-encoding at all.
        command = base + ["-map", "0", "-c", "copy"]
        if ext in {".mp4", ".mov"}:
            command += ["-movflags", "+faststart"]
        command += [str(temp)]
        status_callback("Remux 1:1 · без перекодирования…")
    elif mode == "h264_premiere":
        # Preserve original dimensions and frame rate. CRF 10 is visually near-lossless
        # for typical camera/phone source while remaining very Premiere-friendly.
        command = base + [
            "-map", "0:v:0?",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "10",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ]
        if audio_codecs and all(codec in MP4_AUDIO_COPY_CODECS for codec in audio_codecs):
            command += ["-c:a", "copy"]
        else:
            command += ["-c:a", "aac", "-b:a", "320k"]
        command += [str(temp)]
        status_callback("MP4 для Premiere · максимальное качество…")
    elif mode == "hevc":
        command = base + [
            "-map", "0:v:0?",
            "-map", "0:a?",
            "-c:v", "libx265",
            "-preset", "slow",
            "-crf", "14",
            "-tag:v", "hvc1",
            "-movflags", "+faststart",
        ]
        if audio_codecs and all(codec in MP4_AUDIO_COPY_CODECS for codec in audio_codecs):
            command += ["-c:a", "copy"]
        else:
            command += ["-c:a", "aac", "-b:a", "320k"]
        command += [str(temp)]
        status_callback("MP4 H.265 · высокое качество…")
    elif mode == "prores":
        command = base + [
            "-map", "0:v:0?",
            "-map", "0:a?",
            "-c:v", "prores_ks",
            "-profile:v", "3",
            "-vendor", "apl0",
            "-c:a", "pcm_s24le",
            str(temp),
        ]
        status_callback("MOV ProRes 422 HQ · монтажный файл…")
    else:
        raise RuntimeError("Этот режим конвертации пока не реализован.")

    try:
        _run_ffmpeg(command, duration, progress_callback, status_callback)
        if not temp.is_file() or temp.stat().st_size <= 0:
            raise RuntimeError("FFmpeg завершился без готового видеофайла.")
        temp.replace(output)
        progress_callback(100)
        logging.info("Video conversion complete output=%s size=%d", output, output.stat().st_size)
        return output
    except Exception:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass
        raise
