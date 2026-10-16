"""Existing subtitles (YouTube and any yt-dlp site) -> SRT / VTT / TXT, without Whisper."""
from __future__ import annotations

import html
import json
import re
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import errors
from .errors import UserFacingError
from .platforms import detect_platform, platform_label
from .procs import NEVER, QUIET, CancelToken, Report, run_capture
from .tools import Toolset, pot_provider_args, resolve_tools, ytdlp_base_args

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.youtube.com/",
    "Origin": "https://www.youtube.com",
}

SUBTITLE_FORMATS = ("txt", "srt", "vtt")


@dataclass(frozen=True)
class SubtitleTrack:
    language_code: str
    language_name: str
    source: str  # "manual" | "auto"
    base_url: str = ""
    original: bool = False

    @property
    def id(self) -> str:
        return f"{self.source}:{self.language_code}"

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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.language_code,
            "name": self.language_name,
            "source": self.source,
            "source_label": self.source_label,
            "original": self.is_original,
            "label": self.label,
            "base_url": self.base_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SubtitleTrack":
        return cls(
            language_code=str(data.get("code") or ""),
            language_name=str(data.get("name") or data.get("code") or ""),
            source=str(data.get("source") or "manual"),
            base_url=str(data.get("base_url") or ""),
            original=bool(data.get("original")),
        )


@dataclass(frozen=True)
class SubtitleInfo:
    video_id: str
    title: str
    tracks: tuple[SubtitleTrack, ...]

    def to_dict(self) -> dict:
        return {"video_id": self.video_id, "title": self.title, "tracks": [t.to_dict() for t in self.tracks]}


_LANGUAGE_NAMES = {
    "ru": "Русский",
    "en": "English",
    "uk": "Українська",
    "be": "Беларуская",
    "kk": "Қазақ",
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


def _language_name(code: str, formats: object = None) -> str:
    base = code.split("-")[0].lower()
    known = _LANGUAGE_NAMES.get(base)
    if known:
        return known
    if isinstance(formats, list):
        for item in formats:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    return name
    return code


def tracks_from_info(info: dict) -> tuple[SubtitleTrack, ...]:
    """Manual tracks plus original-language auto captions. YouTube also lists ~150
    machine translations under automatic_captions; those are skipped."""
    tracks: list[SubtitleTrack] = []
    seen: set[tuple[str, str]] = set()
    auto = info.get("automatic_captions") or {}
    auto_codes = [str(code) for code in auto] if isinstance(auto, dict) else []
    has_orig = any(code.lower().endswith("-orig") for code in auto_codes)
    video_language = str(info.get("language") or "").split("-")[0].lower()

    for key, source in (("subtitles", "manual"), ("automatic_captions", "auto")):
        mapping = info.get(key) or {}
        if not isinstance(mapping, dict):
            continue
        for code, formats in mapping.items():
            code = str(code).strip()
            if not code or code == "live_chat" or not isinstance(formats, list) or not formats:
                continue
            if source == "auto":
                if has_orig and not code.lower().endswith("-orig"):
                    continue
                if not has_orig and video_language and code.split("-")[0].lower() != video_language:
                    continue
            marker = (source, code)
            if marker in seen:
                continue
            seen.add(marker)
            tracks.append(SubtitleTrack(code, _language_name(code, formats), source))

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


def extract_video_id(url: str) -> str:
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
                    try:
                        return json.loads(text[start : index + 1])
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


def _fast_youtube_tracks(url: str, report: Report) -> SubtitleInfo:
    video_id = extract_video_id(url)
    if not video_id:
        raise RuntimeError("Не удалось определить id YouTube-видео.")
    report.log("Быстрый поиск дорожек через страницу YouTube…")
    request = urllib.request.Request(f"https://www.youtube.com/watch?v={video_id}&hl=en", headers=_REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=12) as response:
        page = response.read().decode("utf-8", errors="replace")

    player = _balanced_json_after_marker(page, "ytInitialPlayerResponse")
    raw_tracks = (
        player.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
    )
    title = str(player.get("videoDetails", {}).get("title") or "YouTube video")
    if not isinstance(raw_tracks, list) or not raw_tracks:
        return SubtitleInfo(video_id, title, ())

    tracks: list[SubtitleTrack] = []
    for index, item in enumerate(raw_tracks):
        if not isinstance(item, dict) or not item.get("baseUrl"):
            continue
        code = str(item.get("languageCode") or "unknown")
        tracks.append(
            SubtitleTrack(
                language_code=code,
                language_name=_youtube_label(item.get("name")) or _language_name(code),
                source="auto" if item.get("kind") == "asr" else "manual",
                base_url=str(item["baseUrl"]),
                original=index == 0,
            )
        )
    tracks.sort(key=lambda track: (0 if track.is_original else 1, 0 if track.source == "manual" else 1))
    return SubtitleInfo(video_id, title, tuple(tracks))


def _ytdlp_info(url: str, tools: Toolset, report: Report, token: CancelToken) -> dict:
    from .downloader import cached_info, parse_json_output

    cached = cached_info(url)
    if cached is not None:
        return cached
    command = ytdlp_base_args(tools) + ["--skip-download", "--dump-single-json", url]
    code, stdout, stderr, timed_out = run_capture(command, timeout=30, log=report.log, token=token)
    for line in stderr.splitlines():
        if line.strip():
            report.log(line.rstrip())
    if not stdout.strip():
        kind = "timeout" if timed_out else errors.classify(stderr)
        message, hint = errors.friendly(kind, platform_label(detect_platform(url), url))
        raise UserFacingError(message, kind=kind, hint=hint, details=errors.last_error_lines(stderr.splitlines()))
    return parse_json_output(stdout)


def analyze_subtitles(
    url: str,
    *,
    token: CancelToken = NEVER,
    report: Report = QUIET,
    app_root: Path | None = None,
) -> SubtitleInfo:
    url = (url or "").strip()
    if not url:
        raise ValueError("Вставь ссылку.")
    report.status("Ищу субтитры…")
    if detect_platform(url) == "YouTube":
        try:
            info = _fast_youtube_tracks(url, report)
            if info.tracks:
                return info
            report.log("На странице YouTube дорожек нет, проверяю через yt-dlp.")
        except Exception as exc:
            report.log(f"Быстрый способ не сработал: {exc}")
    token.raise_if_cancelled()
    tools = resolve_tools(app_root)
    data = _ytdlp_info(url, tools, report, token)
    return SubtitleInfo(
        video_id=str(data.get("id") or ""),
        title=str(data.get("title") or "Видео"),
        tracks=tracks_from_info(data),
    )


# ---- format conversion ---------------------------------------------------------------

def clean_caption_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{\\[^}]+\}", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def srt_timestamp(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def json3_to_srt(data: dict) -> str:
    blocks: list[str] = []
    last_text = ""
    index = 1
    for event in data.get("events") or []:
        if not isinstance(event, dict) or not isinstance(event.get("segs"), list):
            continue
        text = clean_caption_text("".join(str(seg.get("utf8") or "") for seg in event["segs"] if isinstance(seg, dict)))
        if not text or text == last_text:
            continue
        start = int(event.get("tStartMs") or 0)
        end = max(start + 300, start + int(event.get("dDurationMs") or 2000))
        blocks.append(f"{index}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{text}")
        last_text = text
        index += 1
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def _vtt_timestamp(value: str) -> str:
    value = value.strip().replace(".", ",")
    return "00:" + value if len(value.split(":")) == 2 else value


def vtt_to_srt(vtt: str) -> str:
    blocks: list[str] = []
    index = 1
    current_time = ""
    current_text: list[str] = []

    def flush() -> None:
        nonlocal index, current_time, current_text
        if current_time and current_text:
            text = clean_caption_text(" ".join(current_text))
            if text:
                blocks.append(f"{index}\n{current_time}\n{text}")
                index += 1
        current_time = ""
        current_text = []

    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE")):
            if not line:
                flush()
            continue
        if "-->" in line:
            flush()
            left, right = [part.strip().split(" ", 1)[0] for part in line.split("-->", 1)]
            current_time = f"{_vtt_timestamp(left)} --> {_vtt_timestamp(right)}"
            continue
        if current_time:
            current_text.append(line)
    flush()
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def xml_to_srt(xml: str) -> str:
    blocks: list[str] = []
    index = 1
    for match in re.finditer(
        r'<text\b[^>]*start="([0-9.]+)"[^>]*dur="([0-9.]+)"[^>]*>(.*?)</text>', xml, flags=re.IGNORECASE | re.DOTALL
    ):
        text = clean_caption_text(match.group(3))
        if not text:
            continue
        start_s, duration_s = float(match.group(1)), float(match.group(2))
        blocks.append(
            f"{index}\n{srt_timestamp(int(start_s * 1000))} --> "
            f"{srt_timestamp(int((start_s + max(duration_s, 0.3)) * 1000))}\n{text}"
        )
        index += 1
    if blocks:
        return "\n\n".join(blocks).strip() + "\n"
    for match in re.finditer(
        r'<p\b[^>]*\bt="([0-9]+)"[^>]*\bd="([0-9]+)"[^>]*>(.*?)</p>', xml, flags=re.IGNORECASE | re.DOTALL
    ):
        text = clean_caption_text(match.group(3))
        if not text:
            continue
        start, duration = int(match.group(1)), int(match.group(2))
        blocks.append(f"{index}\n{srt_timestamp(start)} --> {srt_timestamp(max(start + 300, start + duration))}\n{text}")
        index += 1
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def srt_to_vtt(srt_text: str) -> str:
    out = ["WEBVTT", ""]
    for block in re.split(r"\r?\n\s*\r?\n", srt_text.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        timing = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing < 0:
            continue
        out.append(lines[timing].replace(",", "."))
        out.extend(lines[timing + 1 :])
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def srt_to_text(srt_text: str) -> str:
    cue_texts: list[str] = []
    for block in re.split(r"\r?\n\s*\r?\n", srt_text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        text = clean_caption_text(" ".join(lines[timing_index + 1 :]))
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


# ---- downloading a track ------------------------------------------------------------

def _caption_url(base_url: str, fmt: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    params = [(key, value) for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if key != "fmt"]
    if fmt:
        params.append(("fmt", fmt))
    params.extend(
        [
            ("c", "WEB"),
            ("cver", "2.20260506.01.00"),
            ("cplayer", "UNIPLAYER"),
            ("cplatform", "DESKTOP"),
            ("cbr", "Chrome"),
            ("cbrver", "137.0.0.0"),
            ("cos", "Windows"),
            ("cosver", "10.0"),
        ]
    )
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(params)))


def _download_direct_track(track: SubtitleTrack, report: Report, token: CancelToken) -> str:
    last_error: Exception | None = None
    for fmt in ("json3", "vtt", ""):
        token.raise_if_cancelled()
        try:
            report.log(f"Беру дорожку {track.language_code} напрямую · {fmt or 'xml'}…")
            request = urllib.request.Request(_caption_url(track.base_url, fmt), headers=_REQUEST_HEADERS)
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8", errors="replace")
            if not body.strip():
                raise RuntimeError("YouTube вернул пустой ответ.")
            if fmt == "json3":
                srt = json3_to_srt(json.loads(body))
            elif fmt == "vtt" or body.lstrip().startswith("WEBVTT"):
                srt = vtt_to_srt(body)
            else:
                srt = xml_to_srt(body)
            if srt.strip():
                return srt
            raise RuntimeError("Дорожка получена, но текста в ней нет.")
        except Exception as exc:
            last_error = exc
            report.log(f"Прямая загрузка {fmt or 'xml'} не сработала: {exc}")
    raise last_error or RuntimeError("YouTube не отдал выбранную дорожку.")


def _download_with_ytdlp(
    url: str, track: SubtitleTrack, tools: Toolset, report: Report, token: CancelToken
) -> str:
    if detect_platform(url) == "YouTube":
        attempts = [
            ("mweb", ["--extractor-args", "youtube:player_client=mweb"]),
            ("web_embedded", ["--extractor-args", "youtube:player_client=web_embedded"]),
            ("tv", ["--extractor-args", "youtube:player_client=tv"]),
            ("default", []),
        ]
    else:
        attempts = [("default", [])]
    source_flag = "--write-subs" if track.source == "manual" else "--write-auto-subs"
    collected: list[str] = []
    with tempfile.TemporaryDirectory(prefix="rngn-subs-") as tmp:
        job = Path(tmp)
        for name, extra in attempts:
            token.raise_if_cancelled()
            for old in job.glob("*"):
                old.unlink(missing_ok=True)
            command = ytdlp_base_args(tools) + extra + [
                "--skip-download",
                "--windows-filenames",
                source_flag,
                "--sub-langs", track.language_code,
                "--sub-format", "vtt/srt/best",
                "--convert-subs", "srt",
                "-o", str(job / "%(id)s.%(ext)s"),
                url,
            ]
            report.log(f"Резервный способ yt-dlp · {name}")
            _code, _out, err, _timed = run_capture(command, timeout=45, log=report.log, token=token)
            collected += err.splitlines()
            for line in err.splitlines():
                if line.strip():
                    report.log(line.rstrip())
            found = sorted(job.glob("*.srt"))
            if found:
                return found[0].read_text(encoding="utf-8-sig", errors="replace")

    hint = (
        "Возможно, сайт временно ограничил этот компьютер. Повтори позже."
        if pot_provider_args(tools)
        else "Повтори позже."
    )
    raise UserFacingError("Сайт не отдал выбранную дорожку субтитров.", kind="unknown", hint=hint,
                          details=errors.last_error_lines(collected))


def _safe_name(text: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', "_", text)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:150] or "subtitles"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def download_subtitle(
    url: str,
    track: SubtitleTrack,
    output_dir: Path,
    *,
    formats: tuple[str, ...] = ("txt", "srt"),
    title_hint: str = "",
    token: CancelToken = NEVER,
    report: Report = QUIET,
    app_root: Path | None = None,
) -> list[Path]:
    url = (url or "").strip()
    output_dir.mkdir(parents=True, exist_ok=True)
    report.progress(10)
    report.status(f"Скачиваю субтитры · {track.language_name}")

    srt_text = ""
    if track.base_url:
        try:
            srt_text = _download_direct_track(track, report, token)
        except UserFacingError:
            raise
        except Exception as exc:
            report.log(f"Прямая загрузка не сработала: {exc}")
    if not srt_text:
        report.progress(30)
        srt_text = _download_with_ytdlp(url, track, resolve_tools(app_root), report, token)

    report.progress(80)
    base = f"{_safe_name(title_hint or 'Субтитры')}.{_safe_name(track.language_code)}.{track.source}"
    wanted = [fmt for fmt in SUBTITLE_FORMATS if fmt in formats] or ["txt", "srt"]
    outputs: list[Path] = []
    for fmt in wanted:
        if fmt == "srt":
            content = srt_text
        elif fmt == "vtt":
            content = srt_to_vtt(srt_text)
        else:
            content = srt_to_text(srt_text)
        target = _unique_path(output_dir / f"{base}.{fmt}")
        target.write_text(content, encoding="utf-8-sig" if fmt != "vtt" else "utf-8")
        outputs.append(target)
    report.progress(100)
    report.status("Субтитры готовы · " + " + ".join(fmt.upper() for fmt in wanted))
    return outputs
