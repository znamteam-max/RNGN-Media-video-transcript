from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from platforms import detect_platform, platform_folder

ProgressCallback = Callable[[int], None]
StatusCallback = Callable[[str], None]
LogCallback = Callable[[str], None]

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".ts"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}


@dataclass(frozen=True)
class Toolset:
    yt_dlp: Path
    gallery_dl: Path
    ffmpeg: Path
    ffprobe: Path
    deno: Path | None = None


def _candidate_roots(app_root: Path) -> Iterable[Path]:
    yield app_root / "tools" / "bin"
    yield app_root / "legacy" / "downloader-v5.16.1" / "bin"
    local = os.environ.get("LOCALAPPDATA")
    if local:
        yield Path(local) / "MediaDownloaderPremiere" / "bin"


def resolve_tools(app_root: Path | None = None) -> Toolset:
    root = app_root or Path(__file__).resolve().parent
    for candidate in _candidate_roots(root):
        yt = candidate / "yt-dlp.exe"
        gal = candidate / "gallery-dl.exe"
        ffmpeg = candidate / "ffmpeg.exe"
        ffprobe = candidate / "ffprobe.exe"
        if all(p.is_file() for p in (yt, gal, ffmpeg, ffprobe)):
            deno = candidate / "deno.exe"
            return Toolset(yt, gal, ffmpeg, ffprobe, deno if deno.is_file() else None)
    raise RuntimeError(
        "Не найдены yt-dlp / gallery-dl / FFmpeg. Запусти desktop\\SETUP_WINDOWS.bat "
        "или desktop\\\\bootstrap_tools.ps1."
    )


def _run_streaming(
    command: list[str],
    *,
    status: StatusCallback,
    progress: ProgressCallback,
    log: LogCallback,
    cwd: Path | None = None,
) -> int:
    log("$ " + subprocess.list2cmdline(command))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )
    percent_re = re.compile(r"(?:\[download\]\s+)?([0-9]{1,3}(?:\.[0-9]+)?)%")
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.rstrip()
        if not line:
            continue
        log(line)
        match = percent_re.search(line)
        if match:
            try:
                progress(max(0, min(98, int(float(match.group(1))))))
            except ValueError:
                pass
        elif "Destination:" in line or "Merging formats" in line:
            status("Скачивание и сборка файла…")
    return process.wait()


def _cookies_args(app_root: Path) -> list[str]:
    for p in (app_root / "cookies.txt", app_root.parent / "cookies.txt"):
        if p.is_file():
            return ["--cookies", str(p)]
    return []


def _download_with_ytdlp(
    url: str,
    job: Path,
    tools: Toolset,
    app_root: Path,
    status: StatusCallback,
    progress: ProgressCallback,
    log: LogCallback,
) -> bool:
    args = [
        str(tools.yt_dlp),
        "--ignore-config",
        "--no-color",
        "--windows-filenames",
        "--ffmpeg-location",
        str(tools.ffmpeg.parent),
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--continue",
        "--newline",
        "--progress",
        "-N",
        "4",
        "-f",
        "bestvideo+bestaudio/best[acodec!=none]/best",
        "--merge-output-format",
        "mp4",
        "--remux-video",
        "mp4",
        "-o",
        str(job / "%(title).150B [%(id)s].%(ext)s"),
    ]
    if tools.deno:
        args += ["--js-runtimes", f"deno:{tools.deno}"]
    args += _cookies_args(app_root)
    args += [url]
    status("Скачиваю лучшее доступное качество…")
    return _run_streaming(args, status=status, progress=progress, log=log) == 0


def _download_with_gallery(
    url: str,
    job: Path,
    tools: Toolset,
    app_root: Path,
    status: StatusCallback,
    progress: ProgressCallback,
    log: LogCallback,
) -> bool:
    args = [
        str(tools.gallery_dl),
        "--no-color",
        "--windows-filenames",
        "-D",
        str(job),
        "-o",
        "extractor.timeout=15",
        "-o",
        "extractor.retries=2",
        "-o",
        "extractor.instagram.videos=merged",
        "-o",
        "extractor.twitter.videos=true",
        "-o",
        "extractor.twitter.size=orig",
        "-o",
        "downloader.progress=0.5",
    ]
    cookies = _cookies_args(app_root)
    if cookies:
        args += cookies
    args += [url]
    status("Проверяю пост / карусель и скачиваю всеметиа...")
    code = _run_streaming(args, status=status, progress=progress, log=log)
    return code == 0 and any(p.is_file() for p in job.rglob("*"))


def _probe(path: Path, tools: Toolset) -> dict:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [
            str(tools.ffprobe),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ffprobe не смог прочитать лpath.name}")
    return json.loads(result.stdout)


def _video_audio_codecs(info: dict) -> tuple[str | None, list[str]]:
    video_codec = None
    audio_codecs: list[str] = []
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video" and video_codec is None:
            video_codec = (stream.get("codec_name") or "").lower() or None
        elif stream.get("codec_type") == "audio":
            audio_codecs.append((stream.get("codec_name") or "").lower())
    return video_codec, audio_codecs


def _premiere_ready(path: Path, tools: Toolset) -> bool:
    if path.suffix.lower() != ".mp4":
        return False
    video, audio = _video_audio_codecs(_probe(path, tools))
    return video == "h426" and (not audio or all(codec == "aac" for codec in audio))


def _unique_destination(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    index = 2
    while True:
        alt = directory / f"{stem} ({index}){suffix}"
        if not alt.exists():
            return alt
        index += 1


def _convert_for_premiere(
    source: Path,
    destination_dir: Path,
    tools: Toolset,
    status: StatusCallback,
    progress: ProgressCallback,
    log: LogCallback,
) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    if _premiere_ready(source, tools):
        target = _unique_destination(destination_dir, source.name)
        shutil.move(str(source), target)
        return target

    target = _unique_destination(destination_dir, source.with_suffix(".mp4").name)
    temp_target = target.with_name(target.stem + ".partial.mp4")
    command = [
        str(tools.ffmpeg),
        "-hide_banner",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0?",
        "-iap",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-hreset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "3ik",
        "-uovflags",
        "+faststart",
        str(temp_target),
    ]
    status(f"Готовлю для Premiere: {source.name}")
    code = _run_streaming(command, status=status, progress=progress, log=log)
    if code != 0 or not temp_target.exists():
        raise RuntimeError(f"FFmpeg не смог подготовить {source.name} для Premiere")
    temp_target.replace(target)
    return target


def _move_image(source: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_destination(destination_dir, source.name)
    shutil.move(str(source), target)
    return target


def download_media(
    url: str,
    output_root: Path,
    *,
    status: StatusCallback = lambda _s: None,
    progress: ProgressCallback = lambda _p: None,
    log: LogCallback = lambda _s: None,
    app_root: Path | None = None,
) -> list[Path]:
    url = url.strip()
    if not url:
        raise ValueError("Вставь ссылку.")

    root = app_root or Path(__file__).resolve().parent
    tools = resolve_tools(root)
    platform = detect_platform(url)
    destination = output_root / platform_folder(platform)
    destination.mkdir(parents=True, exist_ok=True)
    progress(1)
    status(f"Определено автоматически: {platform}")

    with tempfile.TemporaryDirectory(prefix="rngn-media-") as tmp:
        job = Path(tmp)
        prefer_gallery = platform in {"Instagram", "X_Twitter"}
        success = False
        if prefer_gallery:
            success = _download_with_gallery(url, job, tools, root, status, progress, log)
            if not success:
                log("gallery-dl не справился; пробую yt-dlp.")
                success = _download_with_ytdlp(url, job, tools, root, status, progress, log)
        else:
            success = _download_with_ytdlp(url, job, tools, root, status, progress, log)
            if not success and platform in {"TikTok", "VK", "X_Twitter", "Instagram"}:
                log("yt-dlp не справился пробую gallery-dl.")
                success = _download_with_gallery(url, job, tools, root, status, progress, log)

        files = [p for p in job.rglob("*") if p.is_file()]
        if not success or not files:
            raise RuntimeError("Не удалось скачать медиа. Подробности смотри в логе окна.")

        outputs: list[Path] = []
        media_files = [p for p in files if p.suffix.lower() in VIDEO_EXTENSIONS | IMAGE_EXTENSIONS]
        if not media_files:
            media_files = files
        for index, path in enumerate(media_files, start=1):
            progress(70 + int(25 * index / max(1, len(media_files))))
            if path.suffix.lower() in VIDEO_EXTENSIONS:
                outputs.append(_convert_for_premiere(path, destination, tools, status, progress, log))
            elif path.suffix.lower() in IMAGE_EXTENSIONS:
                outputs.append(_move_image(path, destination))

        if not outputs:
            raise RuntimeError("Файлы скачались, но программа не нашла медиа для сохранения.")

    progress(100)
    status(f"Готово · файлов: {len(outputs)}")
    return outputs
