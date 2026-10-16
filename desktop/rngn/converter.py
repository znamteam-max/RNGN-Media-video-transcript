"""Video conversion presets (ported from ZNAMBO Transcriber v1.7.0), NVIDIA encoding when available."""
from __future__ import annotations

import uuid
from pathlib import Path

from .downloader import (
    AUDIO_EXTENSIONS,
    media_duration,
    nvenc_available,
    probe,
    run_ffmpeg_with_progress,
    stream_codecs,
    unique_destination,
)
from .errors import UserFacingError
from .procs import NEVER, QUIET, CancelToken, OperationCancelled, Report
from .tools import resolve_tools
from .transcriber import safe_stem

VIDEO_INPUTS = {".mov", ".mp4", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts", ".ts", ".wmv", ".flv"}
MP4_AUDIO_COPY_CODECS = {"aac", "alac", "mp3", "ac3", "eac3"}

PROFILES: list[dict] = [
    {
        "id": "premiere",
        "label": "MP4 для Premiere",
        "description": "H.264, исходные разрешение и частота кадров, очень высокое качество.",
        "ext": ".mp4",
        "suffix": ".premiere",
        "audio_only": False,
    },
    {
        "id": "hevc",
        "label": "MP4 H.265",
        "description": "Файл заметно меньше при высоком качестве.",
        "ext": ".mp4",
        "suffix": ".hevc",
        "audio_only": False,
    },
    {
        "id": "prores",
        "label": "MOV ProRes 422 HQ",
        "description": "Монтажный формат без потерь на глаз. Файл очень большой.",
        "ext": ".mov",
        "suffix": ".prores",
        "audio_only": False,
    },
    {
        "id": "remux_mp4",
        "label": "MP4 без перекодирования",
        "description": "Меняется только контейнер, качество 1:1. Секунды вместо минут.",
        "ext": ".mp4",
        "suffix": ".remux",
        "audio_only": False,
    },
    {
        "id": "remux_mov",
        "label": "MOV без перекодирования",
        "description": "Контейнер MOV, видео и звук копируются бит в бит.",
        "ext": ".mov",
        "suffix": ".remux",
        "audio_only": False,
    },
    {
        "id": "remux_mkv",
        "label": "MKV без перекодирования",
        "description": "Самый терпимый контейнер: переносятся все дорожки.",
        "ext": ".mkv",
        "suffix": ".remux",
        "audio_only": False,
    },
    {
        "id": "audio_wav",
        "label": "Звук · WAV",
        "description": "Несжатый звук для монтажа.",
        "ext": ".wav",
        "suffix": "",
        "audio_only": True,
    },
    {
        "id": "audio_mp3",
        "label": "Звук · MP3",
        "description": "MP3 320 кбит/с — откроется где угодно.",
        "ext": ".mp3",
        "suffix": "",
        "audio_only": True,
    },
]
PROFILES_BY_ID = {profile["id"]: profile for profile in PROFILES}


def accepts(path: Path, profile_id: str) -> bool:
    profile = PROFILES_BY_ID.get(profile_id)
    suffix = path.suffix.lower()
    if not profile:
        return False
    return suffix in VIDEO_INPUTS or (profile["audio_only"] and suffix in AUDIO_EXTENSIONS)


def _video_args(profile_id: str, gpu: bool) -> tuple[list[str], str]:
    if profile_id == "premiere":
        if gpu:
            return (
                ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "16", "-b:v", "0",
                 "-profile:v", "high", "-pix_fmt", "yuv420p"],
                "видеокарта",
            )
        return (["-c:v", "libx264", "-preset", "slow", "-crf", "10", "-pix_fmt", "yuv420p"], "процессор")
    if profile_id == "hevc":
        if gpu:
            return (
                ["-c:v", "hevc_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "20", "-b:v", "0",
                 "-tag:v", "hvc1"],
                "видеокарта",
            )
        return (["-c:v", "libx265", "-preset", "slow", "-crf", "14", "-tag:v", "hvc1"], "процессор")
    if profile_id == "prores":
        return (["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0"], "процессор")
    return ([], "")


def convert_media(
    input_path: Path,
    profile_id: str,
    output_dir: Path,
    *,
    gpu_encoder: bool = True,
    token: CancelToken = NEVER,
    report: Report = QUIET,
) -> Path:
    source = Path(input_path)
    profile = PROFILES_BY_ID.get(profile_id)
    if profile is None:
        raise UserFacingError("Неизвестный профиль конвертации.", kind="unknown")
    if not source.is_file():
        raise UserFacingError("Файл не найден.", kind="unknown", hint=str(source))
    if not accepts(source, profile_id):
        raise UserFacingError(
            "Этот файл нельзя конвертировать в выбранный формат.",
            kind="unsupported",
            hint="Для видеопрофилей нужен видеофайл; для звука подойдёт и аудио.",
        )

    tools = resolve_tools()
    report.status("Изучаю дорожки файла…")
    report.progress(0)
    info = probe(source, tools)
    video_codec, audio_codecs = stream_codecs(info)
    duration = media_duration(info)
    report.log(f"Вход: видео={video_codec}; звук={audio_codecs}; длительность={duration:.1f} с; профиль={profile_id}")
    if not profile["audio_only"] and video_codec is None:
        raise UserFacingError("В файле нет видеодорожки.", kind="unsupported", hint="Выбери профиль «Звук».")
    if profile["audio_only"] and not audio_codecs:
        raise UserFacingError("В файле нет звуковой дорожки.", kind="unsupported")

    output_dir.mkdir(parents=True, exist_ok=True)
    target = unique_destination(output_dir, f"{safe_stem(source)}{profile['suffix']}{profile['ext']}")
    partial = output_dir / f".rngn-{uuid.uuid4().hex}.partial{profile['ext']}"
    base = [
        str(tools.ffmpeg), "-hide_banner", "-y", "-i", str(source),
        "-map_metadata", "0", "-progress", "pipe:1", "-nostats",
    ]
    ext = profile["ext"]
    mp4_audio = ["-c:a", "copy"] if audio_codecs and all(c in MP4_AUDIO_COPY_CODECS for c in audio_codecs) else [
        "-c:a", "aac", "-b:a", "320k"
    ]

    plans: list[tuple[list[str], str]] = []
    if profile_id.startswith("remux"):
        maps = ["-map", "0"] if ext == ".mkv" else ["-map", "0:v?", "-map", "0:a?"]
        extra = ["-movflags", "+faststart"] if ext in {".mp4", ".mov"} else []
        plans.append((maps + ["-c", "copy"] + extra, "Меняю контейнер 1:1"))
    elif profile_id == "audio_wav":
        plans.append((["-vn", "-map", "0:a:0", "-c:a", "pcm_s16le"], "Достаю звук в WAV"))
    elif profile_id == "audio_mp3":
        plans.append((["-vn", "-map", "0:a:0", "-c:a", "libmp3lame", "-b:a", "320k"], "Достаю звук в MP3"))
    else:
        maps = ["-map", "0:v:0?", "-map", "0:a?", "-map_chapters", "0"]
        codec = "h264_nvenc" if profile_id == "premiere" else "hevc_nvenc"
        use_gpu = gpu_encoder and profile_id in {"premiere", "hevc"} and nvenc_available(tools, codec)
        audio = ["-c:a", "pcm_s24le"] if profile_id == "prores" else mp4_audio
        container = ["-movflags", "+faststart"] if ext == ".mp4" else []
        video, where = _video_args(profile_id, use_gpu)
        plans.append((maps + video + audio + container, f"{profile['label']} · {where}"))
        if use_gpu:
            cpu_video, _ = _video_args(profile_id, False)
            plans.append((maps + cpu_video + audio + container, f"{profile['label']} · процессор"))

    last: list[str] = []
    try:
        for args, what in plans:
            token.raise_if_cancelled()
            report.status(what + "…")
            code, last = run_ffmpeg_with_progress(
                base + args + [str(partial)],
                duration=duration, report=report, token=token, base=0.0, span=99.0, what=what,
            )
            if code == 0 and partial.is_file() and partial.stat().st_size > 0:
                partial.replace(target)
                report.progress(100)
                report.status("Готово")
                return target
            partial.unlink(missing_ok=True)
            report.log(f"[ffmpeg] «{what}» не сработало (код {code}).")
    except OperationCancelled:
        partial.unlink(missing_ok=True)
        raise
    hint = "Попробуй профиль «MKV без перекодирования»." if profile_id.startswith("remux") else "Подробности — в журнале."
    raise UserFacingError("FFmpeg не смог сконвертировать файл.", kind="ffmpeg", hint=hint,
                          details="\n".join(last[-12:]))
