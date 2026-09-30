from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
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


@dataclass(frozen=True)
class QualityChoice:
    label: str
    height: int | None
    source_video_codec: str
    source_audio_codec: str
    direct_premiere: bool


@dataclass(frozen=True)
class MediaAnalysis:
    platform: str
    title: str
    choices: tuple[QualityChoice, ...]
    default_label: str


def _candidate_roots(app_root: Path) -> Iterable[Path]:
    yield app_root / "tools" / "bin"
    yield app_root / "legacy" / "downloader-v5.16.1" / "bin"
    local = os.environ.get("LOCALAPPDATA")
    if local:
        yield Path(local) / "MediaDownloaderPremiere" / "bin"


def resolve_tools(app_root: Path | None = None) -> Toolset:
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
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
        "или desktop\\bootstrap_tools.ps1."
    )


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_streaming(
    command: list[str],
    *,
    status: StatusCallback,
    progress: ProgressCallback,
    log: LogCallback,
    cwd: Path | None = None,
) -> int:
    log("$ " + subprocess.list2cmdline(command))
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creation_flags(),
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
    candidates = [app_root / "cookies.txt", app_root.parent / "cookies.txt"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "MediaDownloaderPremiere" / "cookies.txt")
    for path in candidates:
        if path.is_file():
            return ["--cookies", str(path)]
    return []


def _common_ytdlp_args(tools: Toolset, app_root: Path) -> list[str]:
    args = [
        str(tools.yt_dlp),
        "--ignore-config",
        "--no-color",
        "--no-playlist",
        "--ffmpeg-location",
        str(tools.ffmpeg.parent),
    ]
    if tools.deno:
        args += ["--js-runtimes", f"deno:{tools.deno}"]
    args += _cookies_args(app_root)
    return args


def _parse_json_output(output: str) -> dict:
    text = output.strip()
    if not text:
        raise RuntimeError("yt-dlp не вернул данные о видео.")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    raise RuntimeError("Не удалось разобрать данные о видео.")


def _codec_family(codec: str | None, *, audio: bool = False) -> str:
    value = (codec or "").lower()
    if not value or value == "none":
        return "без аудио" if audio else "неизвестно"
    if value.startswith("avc1") or value == "h264":
        return "H.264"
    if value.startswith("vp09") or value.startswith("vp9"):
        return "VP9"
    if value.startswith("av01") or value.startswith("av1"):
        return "AV1"
    if value.startswith("hev1") or value.startswith("hvc1") or value.startswith("hevc"):
        return "HEVC"
    if value.startswith("mp4a") or value.startswith("aac"):
        return "AAC"
    if value.startswith("opus"):
        return "Opus"
    if value.startswith("vorbis"):
        return "Vorbis"
    return codec or ("аудио" if audio else "видео")


def _best_codec_name(formats: list[dict], *, audio: bool = False) -> str:
    key = "acodec" if audio else "vcodec"
    candidates = [item for item in formats if str(item.get(key) or "none") != "none"]
    if not candidates:
        return "без аудио" if audio else "неизвестно"
    candidates.sort(
        key=lambda item: (
            float(item.get("tbr") or 0),
            float(item.get("abr") or 0),
            float(item.get("vbr") or 0),
        ),
        reverse=True,
    )
    return _codec_family(str(candidates[0].get(key) or ""), audio=audio)


def _h264_available(formats: list[dict]) -> bool:
    return any(
        _codec_family(str(item.get("vcodec") or "")) == "H.264"
        for item in formats
        if str(item.get("vcodec") or "none") != "none"
    )


def _aac_available(formats: list[dict]) -> bool:
    return any(
        _codec_family(str(item.get("acodec") or ""), audio=True) == "AAC"
        for item in formats
        if str(item.get("acodec") or "none") != "none"
    )


def _choice_label(height: int | None, video_codec: str, audio_codec: str, direct: bool) -> str:
    prefix = f"{height}p" if height else "Лучшее доступное"
    if direct:
        return f"{prefix} — MP4 H.264 + AAC"
    return f"{prefix} — {video_codec} + {audio_codec} → MP4 H.264 + AAC"


def quality_choices_from_info(info: dict) -> tuple[QualityChoice, ...]:
    formats = [item for item in (info.get("formats") or []) if isinstance(item, dict)]
    audio_formats = [
        item
        for item in formats
        if str(item.get("acodec") or "none") != "none"
        and str(item.get("vcodec") or "none") == "none"
    ]
    if not audio_formats:
        audio_formats = [item for item in formats if str(item.get("acodec") or "none") != "none"]

    aac_any = _aac_available(audio_formats)
    fallback_audio = "AAC" if aac_any else _best_codec_name(audio_formats, audio=True)

    heights = sorted(
        {
            int(item["height"])
            for item in formats
            if item.get("height")
            and str(item.get("vcodec") or "none") != "none"
            and int(item["height"]) > 0
        },
        reverse=True,
    )

    choices: list[QualityChoice] = []
    for height in heights:
        video_formats = [
            item
            for item in formats
            if int(item.get("height") or 0) == height
            and str(item.get("vcodec") or "none") != "none"
        ]
        h264 = _h264_available(video_formats)
        source_video = "H.264" if h264 else _best_codec_name(video_formats)
        direct = h264 and aac_any
        label = _choice_label(height, source_video, fallback_audio, direct)
        choices.append(QualityChoice(label, height, source_video, fallback_audio, direct))

    if choices:
        return tuple(choices)

    video_formats = [item for item in formats if str(item.get("vcodec") or "none") != "none"]
    source_video = "H.264" if _h264_available(video_formats) else _best_codec_name(video_formats)
    direct = _h264_available(video_formats) and aac_any
    return (
        QualityChoice(
            _choice_label(None, source_video, fallback_audio, direct),
            None,
            source_video,
            fallback_audio,
            direct,
        ),
    )


def _default_quality_label(choices: tuple[QualityChoice, ...]) -> str:
    exact = next((choice.label for choice in choices if choice.height == 1080), None)
    if exact:
        return exact
    lower = [choice for choice in choices if choice.height is not None and choice.height < 1080]
    if lower:
        return max(lower, key=lambda choice: choice.height or 0).label
    higher = [choice for choice in choices if choice.height is not None]
    if higher:
        return min(higher, key=lambda choice: choice.height or 99999).label
    return choices[0].label


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_creation_flags(),
                timeout=5,
            )
        else:
            process.kill()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _run_analysis_capture(
    command: list[str],
    *,
    timeout_seconds: int,
    log: LogCallback,
) -> tuple[int, str, str, bool]:
    log("$ " + subprocess.list2cmdline(command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creation_flags(),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return process.returncode or 0, stdout, stderr, False
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=3)
        except Exception:
            stdout, stderr = "", ""
        return -9, stdout, stderr, True


def _friendly_analysis_error(messages: list[str], timed_out: bool) -> str:
    text = "\n".join(messages).lower()
    if "429" in text or "too many requests" in text:
        return (
            "YouTube временно ограничил запросы (HTTP 429). "
            "Можно скачать 1080p без предварительного анализа или повторить проверку чуть позже."
        )
    if "403" in text or "forbidden" in text:
        return (
            "YouTube отклонил запрос анализа (HTTP 403). "
            "Можно скачать 1080p без предварительного анализа."
        )
    if "sign in" in text or "login" in text or "private video" in text:
        return "Для этого видео YouTube требует авторизацию."
    if "video unavailable" in text or "unavailable" in text:
        return "Видео недоступно для анализа с текущего подключения."
    if timed_out:
        return (
            "YouTube слишком долго отвечает на запрос форматов. "
            "Анализ остановлен по таймауту; можно скачать 1080p без анализа."
        )
    return (
        "Не удалось быстро получить список форматов. "
        "Можно скачать 1080p без предварительного анализа или повторить проверку."
    )


def analyze_media(
    url: str,
    *,
    app_root: Path | None = None,
    status: StatusCallback = lambda _s: None,
    progress: ProgressCallback = lambda _p: None,
    log: LogCallback = lambda _s: None,
    timeout_seconds: int = 12,
) -> MediaAnalysis:
    url = url.strip()
    if not url:
        raise ValueError("Вставь ссылку.")

    root = app_root or Path(__file__).resolve().parent
    tools = resolve_tools(root)
    platform = detect_platform(url)
    progress(5)

    common = _common_ytdlp_args(tools, root) + [
        "--socket-timeout",
        "7",
        "--retries",
        "1",
        "--extractor-retries",
        "1",
        "--fragment-retries",
        "1",
        "--skip-download",
        "--dump-single-json",
    ]

    attempts: list[tuple[str, list[str], int]] = [("обычный клиент", [], timeout_seconds)]
    if platform == "YouTube":
        attempts.append(
            (
                "резервный YouTube-клиент",
                ["--extractor-args", "youtube:player_client=web_embedded"],
                8,
            )
        )

    errors: list[str] = []
    had_timeout = False

    for index, (label, extra, timeout) in enumerate(attempts, start=1):
        status(f"Анализ форматов · попытка {index}/{len(attempts)} · {label}")
        log(f"[analysis] Попытка {index}/{len(attempts)}: {label}; таймаут {timeout} с")
        command = common + extra + [url]
        code, stdout, stderr, timed_out = _run_analysis_capture(
            command,
            timeout_seconds=timeout,
            log=log,
        )
        had_timeout = had_timeout or timed_out

        if stderr.strip():
            for line in stderr.splitlines():
                if line.strip():
                    log(line.rstrip())
            errors.append(stderr.strip())

        if stdout.strip():
            try:
                info = _parse_json_output(stdout)
                choices = quality_choices_from_info(info)
                default_label = _default_quality_label(choices)
                progress(100)
                status(f"Форматы получены · вариантов: {len(choices)}")
                return MediaAnalysis(
                    platform=platform,
                    title=str(info.get("title") or ""),
                    choices=choices,
                    default_label=default_label,
                )
            except Exception as exc:
                errors.append(str(exc))
                log(f"[analysis] Ответ получен, но не разобран: {exc}")

        if timed_out:
            log(f"[analysis] Попытка {index} остановлена по таймауту.")
        elif code != 0:
            log(f"[analysis] yt-dlp завершился с кодом {code}.")

    raise RuntimeError(_friendly_analysis_error(errors, had_timeout))


def _height_from_quality(quality: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{3,4})p", quality or "")
    return int(match.group(1)) if match else None


def _format_selector(quality: str) -> str:
    height = _height_from_quality(quality)
    unverified = "без анализа" in (quality or "").lower()
    if height and unverified:
        return (
            f"bestvideo[height<={height}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            f"bestvideo[height<={height}]+bestaudio/"
            f"best[height<={height}]/best"
        )
    if height:
        return (
            f"bestvideo[height={height}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            f"bestvideo[height={height}]+bestaudio/"
            f"best[height={height}]"
        )
    return "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo+bestaudio/best"


def _download_with_ytdlp(
    url: str,
    job: Path,
    tools: Toolset,
    app_root: Path,
    status: StatusCallback,
    progress: ProgressCallback,
    log: LogCallback,
    quality: str,
) -> bool:
    args = _common_ytdlp_args(tools, app_root) + [
        "--windows-filenames",
        "--socket-timeout",
        "10",
        "--retries",
        "3",
        "--fragment-retries",
        "5",
        "--continue",
        "--newline",
        "--progress",
        "-N",
        "4",
        "-f",
        _format_selector(quality),
        "--merge-output-format",
        "mp4",
        "--remux-video",
        "mp4",
        "-o",
        str(job / "%(title).150B [%(id)s].%(ext)s"),
        url,
    ]
    status(f"Скачиваю: {quality}…")
    log(f"Выбранное качество: {quality}")
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
    status("Проверяю пост / карусель и скачиваю все медиа…")
    code = _run_streaming(args, status=status, progress=progress, log=log)
    return code == 0 and any(path.is_file() for path in job.rglob("*"))


def _probe(path: Path, tools: Toolset) -> dict:
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
        creationflags=_creation_flags(),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ffprobe не смог прочитать {path.name}")
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
    info = _probe(source, tools)
    video_codec, audio_codecs = _video_audio_codecs(info)

    if source.suffix.lower() == ".mp4" and video_codec == "h264" and (
        not audio_codecs or all(codec == "aac" for codec in audio_codecs)
    ):
        target = _unique_destination(destination_dir, source.name)
        shutil.move(str(source), target)
        return target

    target = _unique_destination(destination_dir, source.with_suffix(".mp4").name)
    temp_target = destination_dir / f".rngn-{uuid.uuid4().hex}.partial.mp4"

    video_args = ["-c:v", "copy"] if video_codec == "h264" else [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18"
    ]
    audio_ready = bool(audio_codecs) and all(codec == "aac" for codec in audio_codecs)
    audio_args = ["-c:a", "copy"] if audio_ready else ["-c:a", "aac", "-b:a", "320k"]

    command = [
        str(tools.ffmpeg),
        "-hide_banner",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
        *video_args,
        *audio_args,
        "-movflags",
        "+faststart",
        str(temp_target),
    ]
    status(f"Готовлю для Premiere: {source.name}")
    ffmpeg_lines: list[str] = []

    def capture(line: str) -> None:
        ffmpeg_lines.append(line)
        log(line)

    code = _run_streaming(command, status=status, progress=progress, log=capture)
    if code != 0 or not temp_target.exists():
        temp_target.unlink(missing_ok=True)
        detail = "\n".join(ffmpeg_lines[-12:]).strip()
        suffix = f"\n\nПоследние строки FFmpeg:\n{detail}" if detail else ""
        raise RuntimeError(f"FFmpeg не смог подготовить {source.name} для Premiere.{suffix}")

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
    quality: str = "1080p — MP4 H.264 + AAC",
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
                success = _download_with_ytdlp(url, job, tools, root, status, progress, log, quality)
        else:
            success = _download_with_ytdlp(url, job, tools, root, status, progress, log, quality)
            if not success and platform in {"TikTok", "VK", "X_Twitter", "Instagram"}:
                log("yt-dlp не справился; пробую gallery-dl.")
                success = _download_with_gallery(url, job, tools, root, status, progress, log)

        files = [path for path in job.rglob("*") if path.is_file()]
        if not success or not files:
            raise RuntimeError("Не удалось скачать медиа. Подробности смотри в логе окна.")

        outputs: list[Path] = []
        media_files = [
            path
            for path in files
            if path.suffix.lower() in VIDEO_EXTENSIONS | IMAGE_EXTENSIONS
        ]
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
