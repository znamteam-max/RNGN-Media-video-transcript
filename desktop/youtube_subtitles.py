from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from downloader import Toolset, resolve_tools
from platforms import detect_platform

StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[int], None]
LogCallback = Callable[[str], None]

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(frozen=True)
class SubtitleTrack:
    language_code: str
    language_name: str
    source: str  # "manual" | "auto"
    base_url: str = ""
    original: bool = False

    @property
    def source_label(self) -> str:
        return "вручную" if self.source == "manual" else "авто"

    @property
    def is_original(self) -> bool:
        return self.original or self.language_code.lower().endswith("-orig")

    @property
    def label(self) -> str:
        original = " · оригинал" if self.is_original else ""
        return f"{self.language_name} ({self.language_code}) — {self.source_label}{original}"


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


def _run_capture(
    command: list[str],
    log: LogCallback,
    *,
    timeout_seconds: int = 30,
) -> subprocess.CompletedProcess[str]:
    log("$ " + subprocess.list2cmdline(command))
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_creation_flags(),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("YouTube отвечает слишком долго. Повтори попытку.") from exc
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


def _language_name(code: str, formats: object = None) -> str:
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
            0 if track.is_original else 1,
            0 if track.source == "manual" else 1,
            preferred.get(track.language_code.split("-")[0].lower(), 9),
            track.language_name.casefold(),
            track.language_code.casefold(),
        )
    )
    return tuple(tracks)


def _extract_video_id(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host == "youtu.be" or host.endswith(".youtu.be"):
        value = parsed.path.strip("/").split("/")[0]
        return value if re.fullmatch(r"[A-Za-z0-9_-]{11}", value or "") else ""
    if host == "youtube.com" or host.endswith(".youtube.com"):
        params = urllib.parse.parse_qs(parsed.query)
        value = (params.get("v") or [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", value or ""):
            return value
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed", "v"}:
            value = parts[1]
            return value if re.fullmatch(r"[A-Za-z0-9_-]{11}", value or "") else ""
    return ""


def _balanced_json_after_marker(text: str, marker: str) -> dict:
    marker_index = text.find(marker)
    while marker_index >= 0:
        start = text.find("{", marker_index)
        if start < 0:
            break
        depth = 0
        in_string = False
        escaping = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaping:
                    escaping = False
                elif char == "\\":
                    escaping = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    snippet = text[start : index + 1]
                    try:
                        return json.loads(snippet)
                    except json.JSONDecodeError:
                        break
        marker_index = text.find(marker, marker_index + len(marker))
    raise RuntimeError("Не удалось прочитать список субтитров со страницы YouTube.")


def _youtube_label(value: object) -> str:
    if isinstance(value, dict):
        simple = value.get("simpleText")
        if isinstance(simple, str):
            return simple
        runs = value.get("runs")
        if isinstance(runs, list):
            return "".join(str(item.get("text") or "") for item in runs if isinstance(item, dict))
    return ""


def _fast_caption_info(url: str, log: LogCallback) -> SubtitleInfo:
    video_id = _extract_video_id(url)
    if not video_id:
        raise RuntimeError("Не удалось определить YouTube video id.")

    watch_url = f"https://www.youtube.com/watch?v={video_id}&hl=en"
    log("Быстрый поиск дорожек через страницу YouTube…")
    request = urllib.request.Request(watch_url, headers=_REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=12) as response:
        page = response.read().decode("utf-8", errors="replace")

    player = _balanced_json_after_marker(page, "ytInitialPlayerResponse")
    raw_tracks = (
        player.get("captions", {})
        .get("playerCaptionsTracklistRenderer", {})
        .get("captionTracks", [])
    )
    if not isinstance(raw_tracks, list) or not raw_tracks:
        raise RuntimeError("Для этого видео не найдено доступных субтитров.")

    tracks: list[SubtitleTrack] = []
    for index, item in enumerate(raw_tracks):
        if not isinstance(item, dict):
            continue
        code = str(item.get("languageCode") or "unknown")
        name = _youtube_label(item.get("name")) or _language_name(code)
        base_url = str(item.get("baseUrl") or "")
        if not base_url:
            continue
        tracks.append(
            SubtitleTrack(
                language_code=code,
                language_name=name,
                source="auto" if item.get("kind") == "asr" else "manual",
                base_url=base_url,
                original=index == 0,
            )
        )

    if not tracks:
        raise RuntimeError("YouTube показал субтитры, но не отдал ссылки на дорожки.")

    tracks.sort(key=lambda track: (0 if track.is_original else 1, 0 if track.source == "manual" else 1))
    title = str(player.get("videoDetails", {}).get("title") or "YouTube video")
    return SubtitleInfo(video_id=video_id, title=title, tracks=tuple(tracks))


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

    progress(5)
    status("Ищу оригинальные дорожки YouTube…")

    try:
        info = _fast_caption_info(url, log)
        progress(100)
        status(f"Субтитры найдены · дорожек: {len(info.tracks)}")
        return info
    except Exception as exc:
        log(f"Быстрый способ не сработал: {exc}")
        log("Переключаюсь на резервный анализ yt-dlp.")

    root = app_root or Path(__file__).resolve().parent
    tools = resolve_tools(root)
    command = _common_ytdlp_args(tools, root) + [
        "--skip-download",
        "--dump-single-json",
        url,
    ]
    result = _run_capture(command, log, timeout_seconds=25)
    info = _parse_json_output(result.stdout)
    tracks = tracks_from_info(info)
    if not tracks:
        raise RuntimeError("У этого видео не найдено доступных субтитров.")

    progress(100)
    status(f"Субтитры найдены · дорожек: {len(tracks)}")
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


def _clean_caption_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{\\[^}]+\}", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _srt_timestamp(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def _json3_to_srt(data: dict) -> str:
    blocks: list[str] = []
    last_text = ""
    index = 1
    for event in data.get("events") or []:
        if not isinstance(event, dict) or not isinstance(event.get("segs"), list):
            continue
        text = _clean_caption_text("".join(str(seg.get("utf8") or "") for seg in event["segs"] if isinstance(seg, dict)))
        if not text or text == last_text:
            continue
        start = int(event.get("tStartMs") or 0)
        duration = int(event.get("dDurationMs") or 2000)
        end = max(start + 300, start + duration)
        blocks.append(f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}")
        last_text = text
        index += 1
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def _download_direct_track(track: SubtitleTrack, log: LogCallback) -> str:
    parsed = urllib.parse.urlparse(track.base_url)
    params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    params = [(key, value) for key, value in params if key != "fmt"]
    params.append(("fmt", "json3"))
    direct_url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(params)))
    log(f"Скачиваю оригинальную дорожку {track.language_code} напрямую с YouTube…")
    request = urllib.request.Request(direct_url, headers=_REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8", errors="replace")
    data = json.loads(body)
    srt = _json3_to_srt(data)
    if not srt.strip():
        raise RuntimeError("YouTube вернул пустую дорожку.")
    return srt


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

    output_dir.mkdir(parents=True, exist_ok=True)
    progress(5)
    status(f"Скачиваю субтитры: {track.label}")

    srt_text = ""
    if track.base_url:
        try:
            srt_text = _download_direct_track(track, log)
        except Exception as exc:
            log(f"Прямая загрузка дорожки не сработала: {exc}")

    if not srt_text:
        root = app_root or Path(__file__).resolve().parent
        tools = resolve_tools(root)
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
                "vtt/srt/best",
                "--convert-subs",
                "srt",
                "-o",
                str(job / "%(title).150B [%(id)s].%(ext)s"),
                url,
            ]
            result = _run_capture(command, log, timeout_seconds=35)
            srt_candidates = sorted(job.rglob("*.srt"))
            if not srt_candidates:
                suffix = "" if result.returncode == 0 else f" Код yt-dlp: {result.returncode}."
                raise RuntimeError(f"Не удалось получить выбранную дорожку субтитров.{suffix}")
            srt_text = srt_candidates[0].read_text(encoding="utf-8-sig", errors="replace")

    progress(75)
    title = _safe_name(title_hint or "YouTube")
    source_tag = "manual" if track.source == "manual" else "auto"
    code = _safe_name(track.language_code)
    base = f"{title}.{code}.{source_tag}"

    target_srt = _unique_path(output_dir / f"{base}.srt")
    target_srt.write_text(srt_text, encoding="utf-8-sig")

    transcript = srt_to_text(srt_text)
    target_txt = _unique_path(output_dir / f"{base}.txt")
    target_txt.write_text(transcript, encoding="utf-8-sig")

    progress(100)
    status("Субтитры готовы · TXT + SRT")
    return [target_txt, target_srt]
