from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable

APP_DATA = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "RNGN Media Studio"
COOKIE_FILE = APP_DATA / "cookies.txt"
DEFAULT_OUTPUT_ROOT = Path.home() / "Videos" / "RNGN Media Studio"
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".mts", ".m2ts"
}


class MediaDownloadError(RuntimeError):
    pass


class MediaDownloadCancelled(MediaDownloadError):
    pass


@dataclass(frozen=True)
class MediaInfo:
    platform: str
    title: str
    qualities: tuple[int, ...]
    duration: float | None
    item_count: int
    extractor: str


def detect_platform(url: str) -> str:
    value = (url or "").strip().lower()
    if "youtube.com/" in value or "youtu.be/" in value:
        return "YouTube"
    if "vk.com/" in value or "vkvideo.ru/" in value:
        return "VK"
    if "tiktok.com/" in value:
        return "TikTok"
    if "instagram.com/" in value:
        return "Instagram"
    if "twitter.com/" in value or "x.com/" in value:
        return "X (Twitter)"
    return "Другой источник"


def platform_folder(platform: str) -> str:
    return {
        "YouTube": "YouTube",
        "VK": "VK",
        "TikTok": "TikTok",
        "Instagram": "Instagram",
        "X (Twitter)": "X",
    }.get(platform, "Other")


class MediaDownloader:
    def __init__(self) -> None:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        self.tools_dir = self._find_tools_dir()
        self.ytdlp = self._required_tool("yt-dlp.exe")
        self.deno = self._required_tool("deno.exe")
        self.ffmpeg = self._required_tool("ffmpeg.exe")
        self.gallery = self._optional_tool("gallery-dl.exe")

    @staticmethod
    def _resource_root() -> Path:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
        return Path(__file__).resolve().parent

    def _find_tools_dir(self) -> Path:
        root = self._resource_root()
        candidates = [
            root / "tools",
            root / "vendor" / "tools",
            Path(__file__).resolve().parent / "vendor" / "tools",
        ]
        for candidate in candidates:
            if (candidate / "yt-dlp.exe").is_file():
                return candidate
        return candidates[0]

    def _required_tool(self, name: str) -> Path:
        path = self.tools_dir / name
        if not path.is_file():
            raise MediaDownloadError(
                f"Не найден компонент {name}. Переустанови RNGN Media Studio."
            )
        return path

    def _optional_tool(self, name: str) -> Path | None:
        path = self.tools_dir / name
        return path if path.is_file() else None

    def _common_args(self, url: str) -> list[str]:
        args = [
            str(self.ytdlp),
            "--ignore-config",
            "--no-warnings",
            "--socket-timeout", "25",
            "--retries", "4",
            "--fragment-retries", "4",
            "--ffmpeg-location", str(self.tools_dir),
            "--js-runtimes", f"deno:{self.deno}",
        ]
        if COOKIE_FILE.is_file() and COOKIE_FILE.stat().st_size > 0:
            args += ["--cookies", str(COOKIE_FILE)]
        if detect_platform(url) == "YouTube":
            args += ["--no-playlist"]
        return args

    @staticmethod
    def _json_from_output(stdout: str) -> dict | None:
        text = (stdout or "").strip()
        if not text:
            return None
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            pass
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _primary_entry(info: dict) -> dict:
        entries = info.get("entries")
        if isinstance(entries, list):
            for item in entries:
                if isinstance(item, dict):
                    return item
        return info

    @staticmethod
    def _has_media_formats(info: dict) -> bool:
        item = MediaDownloader._primary_entry(info)
        formats = item.get("formats")
        if not isinstance(formats, list):
            return bool(item.get("url"))
        return any(
            isinstance(fmt, dict)
            and (
                fmt.get("vcodec") not in (None, "none")
                or fmt.get("acodec") not in (None, "none")
            )
            for fmt in formats
        )

    @staticmethod
    def _qualities(info: dict) -> tuple[int, ...]:
        item = MediaDownloader._primary_entry(info)
        values: set[int] = set()
        for fmt in item.get("formats") or []:
            if not isinstance(fmt, dict) or fmt.get("vcodec") in (None, "none"):
                continue
            height = fmt.get("height")
            if isinstance(height, (int, float)) and height > 0:
                values.add(int(height))
        return tuple(sorted(values, reverse=True))

    def _analysis_attempts(self, url: str) -> list[list[str]]:
        if detect_platform(url) != "YouTube":
            return [[]]
        return [
            [],
            ["--extractor-args", "youtube:player_client=android_vr"],
            ["--extractor-args", "youtube:player_client=web_safari"],
            ["--extractor-args", "youtube:player_client=web_embedded"],
        ]

    def analyze(self, url: str) -> MediaInfo:
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise MediaDownloadError("Вставь полную ссылку http:// или https://.")

        last_error = ""
        for extra in self._analysis_attempts(url):
            command = self._common_args(url) + [
                "--dump-single-json", "--skip-download", *extra, url
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=120,
                check=False,
            )
            info = self._json_from_output(result.stdout)

            # Важный фикс из рабочей v5.16.1: если JSON реальный и содержит
            # медиа-форматы, принимаем его даже при ненулевом exit code yt-dlp.
            if info and self._has_media_formats(info):
                item = self._primary_entry(info)
                entries = info.get("entries")
                item_count = (
                    len([entry for entry in entries if isinstance(entry, dict)])
                    if isinstance(entries, list)
                    else 1
                )
                duration = item.get("duration")
                try:
                    duration_value = float(duration) if duration is not None else None
                except (TypeError, ValueError):
                    duration_value = None
                return MediaInfo(
                    platform=detect_platform(url),
                    title=str(item.get("title") or info.get("title") or "Без названия"),
                    qualities=self._qualities(info),
                    duration=duration_value,
                    item_count=max(1, item_count),
                    extractor=str(
                        item.get("extractor_key") or info.get("extractor_key") or ""
                    ),
                )
            last_error = (result.stderr or result.stdout or "").strip()

        tail = "\n".join(last_error.splitlines()[-10:])
        raise MediaDownloadError(
            "Не удалось получить варианты медиа."
            + (f"\n\n{tail}" if tail else "")
        )

    @staticmethod
    def _format_selector(quality: int | None, mode: str) -> str:
        height = f"[height<={quality}]" if quality else ""
        if mode == "premiere":
            return (
                f"bestvideo{height}[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                f"bestvideo{height}[vcodec^=avc1]+bestaudio/"
                f"bestvideo{height}+bestaudio/"
                f"best{height}/best"
            )
        return f"bestvideo{height}+bestaudio/best{height}/best"

    @staticmethod
    def _snapshot(folder: Path) -> dict[Path, tuple[int, int]]:
        result: dict[Path, tuple[int, int]] = {}
        if not folder.is_dir():
            return result
        for path in folder.iterdir():
            if path.is_file():
                try:
                    stat = path.stat()
                    result[path] = (stat.st_size, stat.st_mtime_ns)
                except OSError:
                    pass
        return result

    @staticmethod
    def _changed_files(
        folder: Path, before: dict[Path, tuple[int, int]]
    ) -> list[Path]:
        ignored_suffixes = {".part", ".ytdl", ".temp", ".tmp"}
        changed: list[Path] = []
        if not folder.is_dir():
            return changed
        for path in folder.iterdir():
            if not path.is_file() or path.suffix.lower() in ignored_suffixes:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            previous = before.get(path)
            current = (stat.st_size, stat.st_mtime_ns)
            if previous != current and stat.st_size > 0:
                changed.append(path)
        return sorted(changed, key=lambda p: p.stat().st_mtime_ns)

    def _run_process(
        self,
        command: list[str],
        cancel_event: Event,
        progress_callback: Callable[[int], None],
        status_callback: Callable[[str], None],
    ) -> tuple[int, str]:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines: list[str] = []
        assert process.stdout is not None
        for raw in process.stdout:
            if cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise MediaDownloadCancelled("Скачивание отменено.")

            line = raw.strip()
            if not line:
                continue
            lines.append(line)
            lines = lines[-200:]

            match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
            if match:
                try:
                    progress_callback(
                        min(92, max(1, int(float(match.group(1)) * 0.92)))
                    )
                except ValueError:
                    pass
            elif "[Merger]" in line:
                status_callback("Объединяю видео и оригинальный звук…")
            elif "[ExtractAudio]" in line:
                status_callback("Готовлю WAV с оригинальным звуком…")
            elif "[download] Destination:" in line:
                status_callback("Скачиваю медиа…")
        return process.wait(), "\n".join(lines)

    def _gallery_fallback(
        self,
        url: str,
        folder: Path,
        cancel_event: Event,
        status_callback: Callable[[str], None],
    ) -> tuple[int, str]:
        if self.gallery is None:
            return 1, "gallery-dl не установлен"
        status_callback("Основной способ не сработал. Пробую gallery-dl…")
        process = subprocess.Popen(
            [str(self.gallery), "--no-mtime", "-D", str(folder), url],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines: list[str] = []
        assert process.stdout is not None
        for raw in process.stdout:
            if cancel_event.is_set():
                process.terminate()
                raise MediaDownloadCancelled("Скачивание отменено.")
            line = raw.strip()
            if line:
                lines.append(line)
        return process.wait(), "\n".join(lines[-100:])

    def _is_premiere_ready(self, path: Path) -> bool:
        if path.suffix.lower() not in {".mp4", ".mov"}:
            return False
        result = subprocess.run(
            [str(self.ffmpeg), "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=30,
            check=False,
        )
        probe = (result.stderr or "") + "\n" + (result.stdout or "")
        has_video = bool(re.search(r"Video:\s+h264\b", probe, re.I))
        audio_lines = re.findall(r"Audio:\s+([^\s,]+)", probe, re.I)
        audio_ok = not audio_lines or all(codec.lower() == "aac" for codec in audio_lines)
        return has_video and audio_ok

    def _to_premiere(
        self,
        path: Path,
        cancel_event: Event,
        status_callback: Callable[[str], None],
    ) -> Path:
        if self._is_premiere_ready(path):
            return path

        output = path.with_name(path.stem + ".premiere.mp4")
        temp = output.with_name(output.stem + ".partial.mp4")
        temp.unlink(missing_ok=True)
        status_callback(f"Конвертирую для Premiere: {path.name}")

        process = subprocess.Popen(
            [
                str(self.ffmpeg),
                "-hide_banner", "-y",
                "-i", str(path),
                "-map", "0:v:0?",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "17",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "320k",
                "-movflags", "+faststart",
                str(temp),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        while process.poll() is None:
            if cancel_event.is_set():
                process.terminate()
                temp.unlink(missing_ok=True)
                raise MediaDownloadCancelled("Конвертация отменена.")
            time.sleep(0.2)

        stderr = process.stderr.read() if process.stderr else ""
        if process.returncode != 0 or not temp.is_file() or temp.stat().st_size <= 0:
            temp.unlink(missing_ok=True)
            tail = "\n".join(stderr.splitlines()[-12:])
            raise MediaDownloadError(
                "FFmpeg не смог подготовить файл для Premiere."
                + (f"\n\n{tail}" if tail else "")
            )

        temp.replace(output)
        try:
            path.unlink()
        except OSError:
            pass
        return output

    def download(
        self,
        url: str,
        quality: int | None,
        mode: str,
        progress_callback: Callable[[int], None],
        status_callback: Callable[[str], None],
        cancel_event: Event,
    ) -> list[Path]:
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise MediaDownloadError("Вставь полную ссылку на медиа.")

        platform = detect_platform(url)
        folder = DEFAULT_OUTPUT_ROOT / platform_folder(platform)
        folder.mkdir(parents=True, exist_ok=True)
        before = self._snapshot(folder)

        command = self._common_args(url) + [
            "--newline",
            "--no-overwrites",
            "--windows-filenames",
            "-o", str(folder / "%(title).180B [%(id)s].%(ext)s"),
        ]

        if mode == "audio":
            command += [
                "-f", "bestaudio/best",
                "-x", "--audio-format", "wav", "--audio-quality", "0",
            ]
        else:
            command += ["-f", self._format_selector(quality, mode)]
            if mode == "premiere":
                command += ["--merge-output-format", "mp4"]
        command += [url]

        status_callback(f"{platform}: начинаю скачивание…")
        code, log = self._run_process(
            command, cancel_event, progress_callback, status_callback
        )
        files = self._changed_files(folder, before)

        if code != 0 and not files and platform in {"Instagram", "TikTok", "X (Twitter)"}:
            fallback_code, fallback_log = self._gallery_fallback(
                url, folder, cancel_event, status_callback
            )
            files = self._changed_files(folder, before)
            if fallback_code != 0 and not files:
                log = f"{log}\n{fallback_log}".strip()

        if not files:
            tail = "\n".join(log.splitlines()[-16:])
            raise MediaDownloadError(
                "Скачивание не создало ни одного файла."
                + (f"\n\n{tail}" if tail else "")
            )

        if mode == "premiere":
            videos = [p for p in files if p.suffix.lower() in VIDEO_EXTENSIONS]
            converted = [
                self._to_premiere(p, cancel_event, status_callback) for p in videos
            ]
            files = [
                p for p in files if p.suffix.lower() not in VIDEO_EXTENSIONS
            ] + converted

        progress_callback(100)
        status_callback("Готово")
        return files


def open_download_folder(platform: str | None = None) -> None:
    folder = DEFAULT_OUTPUT_ROOT
    if platform:
        folder = folder / platform_folder(platform)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(folder))  # type: ignore[attr-defined]
    except Exception:
        subprocess.Popen(["explorer.exe", str(folder)])
