from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from downloader import Toolset, resolve_tools
from platforms import detect_platform

StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[int], None]
LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class SubtitleTrack:
    language_code: str
    language_name: str
    source: str  # "manual" | "auto"

    @property
    def source_label(self) -> str:
        return "вручную" if self.source == "manual" else "авто"

    @property
    def label(self) -> str:
        return f"{self.language_name} ({self.language_code}) — {self.source_label}"


@dataclass(frozen=True)
class SubtitleInfo:
    video_id: str
    title: str
    tracks: tuple[SubtitleTrack, ...]


_LANGUAGE_NAMES = {
    "ru": "Русский",
    "en": "English",
    "uk": "Українська",
    "be": "Беларуская",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "it": "Italiano",
    "pt": "Português",
    "pl": "Polski",
    "tr": "Türkçe",
    "ar": "العربية",
    "zh": "中文",
    "ja": "日本語",
    "ko": "한국어",
}


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _cookies_args(app_root: Path) -> list[str]:
    candidates = (
        app_root / "cookies.txt",
        app_root.parent / "cookies.txt",
    )
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates += (Path(local) / "MediaDownloaderPremiere" / "cookies.txt",)
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


def _run_capture(command: list[str], log: LogCallback) -> subprocess.CompletedProcess[str]:
    log("$ " + subprocess.list2cmdline(command))
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creation_flags(),
    )
    if result.stderr.strip():
        for line in result.stderr.splitlines():
            if line.strip():
                log(line.rstrip())
    return result


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
    raise RuntimeError("Не удалось разобрать ответ yt-dlp при анализе субтитров.")


def _language_name(code: str, formats: object) -> str:
    base = code.split("-")[0].lower()
    known = _LANGUAGE_NAMES.get(base)
    if known:
        return known
    if isinstance(formats, list):
        for item in formats:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                return name
    return code


def tracks_from_info(info: dict) -> tuple[SubtitleTrack, ...]:
    tracks: list[SubtitleTrack] = []
    seen: set[tuple[str, str]] = set()
    for key, source in (("subtitles", "manual"), ("automatic_captions", "auto")):
        mapping = info.get(key) or {}
        if not isinstance(mapping, dict):
            continue
        for code, formats in mapping.items():
            code = str(code).strip()
            if not code or code == "live_chat":
                continue
            if not isinstance(formats, list) or not formats:
                continue
            marker = (source, code)
            if marker in seen:
                continue
            seen.add(marker)
            tracks.append(
                SubtitleTrack(
                    language_code=code,
                    language_name=_language_name(code, formats),
                    source=source,
                )
            )

    preferred = {"ru": 0, "en": 1}
    tracks.sort(
        key=lambda track: (
            0 if track.source == "manual" else 1,
            preferred.get(track.language_code.split("-")[0].lower(), 9),
            track.language_name.casefold(),
            track.language_code.casefold(),
        )
    )
    return tuple(tracks)


def analyze_youtube_subtitles(
    url: str,
    *,
    app_root: Path | None = None,
    status: StatusCallback = lambda _s: None,
    progress: ProgressCallback = lambda _p: None,
    log: LogCallback = lambda _s: None,
) -> SubtitleInfo:
    url = url.strip()
    if detect_platform(url) != "YouTube":
        raise ValueError("Для этого раздела нужна ссылка на YouTube-видео.")

    root = app_root or Path(__file__).resolve().parent
    tools = resolve_tools(root)
    progress(5)
    status("Проверяю доступные субтитры YouTube…")
    command = _common_ytdlp_args(tools, root) + [
        "--skip-download",
        "--dump-single-json",
        url,
    ]
    result = _run_capture(command, log)
    info = _parse_json_output(result.stdout)
    tracks = tracks_from_info(info)
    if not tracks:
        reason = ""
        if result.returncode != 0:
            reason = " yt-dlp также вернул ошибку; смотри лог."
        raise RuntimeError(f"У этого видео не найдено доступных субтитров.{reason}")

    progress(100)
    return SubtitleInfo(
        video_id=str(info.get("id") or ""),
        title=str(info.get("title") or "YouTube video"),
        tracks=tracks,
    )


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _safe_name(text: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', "_", text)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:150] or "youtube-subtitles"


def _ffmpeg_vtt_to_srt(vtt: Path, srt: Path, tools: Toolset, log: LogCallback) -> None:
    command = [
        str(tools.ffmpeg),
        "-hide_banner",
        "-y",
        "-i",
        str(vtt),
        str(srt),
    ]
    result = _run_capture(command, log)
    if result.returncode != 0 or not srt.is_file():
        raise RuntimeError("FFmpeg не смог преобразовать субтитры VTT в SRT.")


def _clean_caption_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{\\[^}]+\}", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def srt_to_text(srt_text: str) -> str:
    cue_texts: list[str] = []
    for block in re.split(r"\r?\n\s*\r?\n", srt_text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        text = _clean_caption_text(" ".join(lines[timing_index + 1 :]))
        if not text:
            continue
        if cue_texts:
            prev = cue_texts[-1]
            if text == prev or prev.startswith(text):
                continue
            if len(prev) >= 5 and text.startswith(prev):
                cue_texts[-1] = text
                continue
        cue_texts.append(text)

    paragraphs: list[str] = []
    current: list[str] = []
    length = 0
    for text in cue_texts:
        current.append(text)
        length += len(text)
        if length >= 700 or (length >= 350 and re.search(r'[.!?…]["\'»”)]?$', text)):
            paragraphs.append(" ".join(current).strip())
            current = []
            length = 0
    if current:
        paragraphs.append(" ".join(current).strip())
    return "\n\n".join(paragraphs).strip() + ("\n" if paragraphs else "")


def download_youtube_subtitle(
    url: str,
    track: SubtitleTrack,
    output_dir: Path,
    *,
    title_hint: str = "",
    app_root: Path | None = None,
    status: StatusCallback = lambda _s: None,
    progress: ProgressCallback = lambda _p: None,
    log: LogCallback = lambda _s: None,
) -> list[Path]:
    url = url.strip()
    if detect_platform(url) != "YouTube":
        raise ValueError("Для этого раздела нужна ссылка на YouTube-видео.")

    root = app_root or Path(__file__).resolve().parent
    tools = resolve_tools(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress(5)

    with tempfile.TemporaryDirectory(prefix="rngn-youtube-subs-") as tmp:
        job = Path(tmp)
        source_flag = "--write-subs" if track.source == "manual" else "--write-auto-subs"
        command = _common_ytdlp_args(tools, root) + [
            "--skip-download",
            "--windows-filenames",
            source_flag,
            "--sub-langs",
            track.language_code,
            "--sub-format",
            "vtt",
            "--convert-subs",
            "srt",
            "-o",
            str(job / "%(title).150B [%(id)s].%(ext)s"),
            url,
        ]
        status(f"Скачиваю субтитры: {track.label}")
        result = _run_capture(command, log)
        progress(70)

        srt_candidates = sorted(job.rglob("*.srt"))
        if not srt_candidates:
            vtt_candidates = sorted(job.rglob("*.vtt"))
            if vtt_candidates:
                fallback_srt = job / "subtitle.srt"
                _ffmpeg_vtt_to_srt(vtt_candidates[0], fallback_srt, tools, log)
                srt_candidates = [fallback_srt]

        if not srt_candidates:
            suffix = "" if result.returncode == 0 else f" Код yt-dlp: {result.returncode}."
            raise RuntimeError(f"Не удалось получить выбранную дорожку субтитров.{suffix}")

        source_srt = srt_candidates[0]
        title = _safe_name(title_hint or source_srt.stem)
        source_tag = "manual" if track.source == "manual" else "auto"
        code = _safe_name(track.language_code)
        base = f"{title}.{code}.{source_tag}"

        target_srt = _unique_path(output_dir / f"{base}.srt")
        shutil.copy2(source_srt, target_srt)

        transcript = srt_to_text(source_srt.read_text(encoding="utf-8-sig", errors="replace"))
        target_txt = _unique_path(output_dir / f"{base}.txt")
        target_txt.write_text(transcript, encoding="utf-8-sig")

    progress(100)
    status("Субтитры готовы · TXT + SRT")
    return [target_txt, target_srt]
