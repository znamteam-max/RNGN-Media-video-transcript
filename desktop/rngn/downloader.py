"""Link analysis and downloading through yt-dlp / gallery-dl, with Premiere-ready output."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from . import errors
from .errors import UserFacingError
from .platforms import GALLERY_FIRST, detect_platform, platform_folder, platform_label
from .procs import NEVER, QUIET, CancelToken, OperationCancelled, Report, creation_flags, run_capture, run_streaming
from .tools import Access, Toolset, browser_cookie_sources, cookies_file, resolve_tools, ytdlp_base_args

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".ts", ".flv", ".avi"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".opus", ".ogg", ".wav", ".flac", ".weba"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic"}
AUDIO_FORMATS = ("mp3", "m4a", "wav")


# ---- quality choices ----------------------------------------------------------------

@dataclass(frozen=True)
class QualityChoice:
    height: int | None
    label: str
    note: str
    direct: bool
    fps: int | None = None
    size: int | None = None

    def to_dict(self) -> dict:
        return {
            "height": self.height,
            "label": self.label,
            "note": self.note,
            "direct": self.direct,
            "fps": self.fps,
            "size": self.size,
        }


def _codec_family(codec: str | None) -> str:
    value = (codec or "").strip().lower()
    if not value or value in {"unknown", "none"}:
        return "не определён"
    if value.startswith("avc") or value == "h264":
        return "H.264"
    if value.startswith(("vp09", "vp9")):
        return "VP9"
    if value.startswith(("av01", "av1")):
        return "AV1"
    if value.startswith(("hev1", "hvc1", "hevc", "h265")):
        return "HEVC"
    if value.startswith(("mp4a", "aac")):
        return "AAC"
    if value.startswith("opus"):
        return "Opus"
    if value.startswith("vorbis"):
        return "Vorbis"
    return codec or "?"


def _codec_state(item: dict, key: str) -> str:
    if key not in item or item.get(key) is None:
        return "unknown"
    value = str(item.get(key) or "").strip().lower()
    if not value or value == "unknown":
        return "unknown"
    if value == "none":
        return "none"
    return "present"


def _format_size(item: dict) -> int:
    return int(item.get("filesize") or item.get("filesize_approx") or 0)


def audio_summary(info: dict, formats: list[dict]) -> tuple[str, bool]:
    """(description, aac_available). Never claims "no audio" when the source simply
    does not report codecs (VK and HLS manifests often omit them)."""
    with_audio = [item for item in formats if _codec_state(item, "acodec") == "present"]
    if with_audio:
        families = {_codec_family(str(item.get("acodec"))) for item in with_audio}
        if "AAC" in families:
            return "AAC", True
        return sorted(families)[0], False
    if _codec_state(info, "acodec") == "present":
        family = _codec_family(str(info.get("acodec")))
        return family, family == "AAC"
    states = [_codec_state(item, "acodec") for item in formats]
    if states and all(state == "none" for state in states):
        return "без звука", False
    return "звук: не определён источником", False


def quality_choices_from_info(info: dict) -> list[QualityChoice]:
    formats = [item for item in (info.get("formats") or []) if isinstance(item, dict)]
    audio_name, aac_any = audio_summary(info, formats)
    best_audio = max(
        (
            _format_size(item)
            for item in formats
            if _codec_state(item, "acodec") == "present" and _codec_state(item, "vcodec") == "none"
        ),
        default=0,
    )

    heights = sorted(
        {
            int(item["height"])
            for item in formats
            if item.get("height") and _codec_state(item, "vcodec") != "none" and int(item["height"]) > 0
        },
        reverse=True,
    )

    choices: list[QualityChoice] = []
    for height in heights:
        at_height = [
            item
            for item in formats
            if int(item.get("height") or 0) == height and _codec_state(item, "vcodec") != "none"
        ]
        families = {
            _codec_family(str(item.get("vcodec")))
            for item in at_height
            if _codec_state(item, "vcodec") == "present"
        }
        h264 = "H.264" in families
        direct = h264 and aac_any
        fps = max((int(item.get("fps") or 0) for item in at_height), default=0) or None
        h264_sizes = [_format_size(item) for item in at_height if _codec_family(str(item.get("vcodec"))) == "H.264"]
        sizes = h264_sizes if h264 and any(h264_sizes) else [_format_size(item) for item in at_height]
        size = (max(sizes, default=0) + best_audio) or None
        if direct:
            note = "H.264 + AAC · без перекодирования"
        elif families - {"не определён"}:
            source = " / ".join(sorted(families - {"не определён"}))
            note = f"{source} → перекодирую в H.264"
        else:
            note = "кодек проверю после скачивания"
        if audio_name.startswith("звук:"):
            note += " · " + audio_name
        choices.append(QualityChoice(height, f"{height}p", note, direct, fps, size))

    if choices:
        return choices

    families = {
        _codec_family(str(item.get("vcodec")))
        for item in formats
        if _codec_state(item, "vcodec") == "present"
    }
    direct = "H.264" in families and aac_any
    note = "лучшее доступное"
    if audio_name.startswith("звук:"):
        note += " · " + audio_name
    return [QualityChoice(None, "Лучшее", note, direct)]


def default_height(choices: list[QualityChoice], preferred: int = 1080) -> int | None:
    heights = [choice.height for choice in choices if choice.height]
    if not heights:
        return None
    if preferred in heights:
        return preferred
    lower = [height for height in heights if height < preferred]
    return max(lower) if lower else min(heights)


# ---- timecodes ----------------------------------------------------------------------

def parse_timecode(value: str) -> float:
    text = (value or "").strip().replace(",", ".")
    if not text:
        raise ValueError("Таймкод пустой.")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError("Используй формат СС, ММ:СС или ЧЧ:ММ:СС.")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError("Таймкод должен содержать только цифры и двоеточия.") from exc
    if any(number < 0 for number in numbers):
        raise ValueError("Таймкод не может быть отрицательным.")
    if len(numbers) == 1:
        return numbers[0]
    if len(numbers) == 2:
        minutes, seconds = numbers
        if seconds >= 60:
            raise ValueError("Секунды в ММ:СС должны быть меньше 60.")
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    if minutes >= 60 or seconds >= 60:
        raise ValueError("Минуты и секунды в ЧЧ:ММ:СС должны быть меньше 60.")
    return hours * 3600 + minutes * 60 + seconds


def validate_clip_range(start_text: str, end_text: str, duration: float | None = None) -> tuple[float, float]:
    start = parse_timecode(start_text)
    end = parse_timecode(end_text)
    if end <= start:
        raise ValueError("Конец отрезка должен быть позже начала.")
    if duration and start >= duration:
        raise ValueError("Начало отрезка дальше конца видео.")
    return start, end


def _seconds_arg(seconds: float) -> str:
    value = max(0.0, float(seconds))
    return str(int(value)) if value.is_integer() else f"{value:.3f}".rstrip("0").rstrip(".")


def _clip_tag(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}.{minutes:02d}.{secs:02d}"


# ---- analysis -----------------------------------------------------------------------

@dataclass
class MediaInfo:
    url: str
    platform: str
    site: str
    kind: str = "video"  # video | playlist
    title: str = ""
    uploader: str = ""
    duration: float | None = None
    thumbnail: str = ""
    is_live: bool = False
    choices: list[QualityChoice] = field(default_factory=list)
    default_height: int | None = None
    audio_note: str = ""
    access: Access | None = None
    entries: list[dict] = field(default_factory=list)
    subtitle_tracks: int = 0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "platform": self.platform,
            "site": self.site,
            "kind": self.kind,
            "title": self.title,
            "uploader": self.uploader,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
            "is_live": self.is_live,
            "choices": [choice.to_dict() for choice in self.choices],
            "default_height": self.default_height,
            "audio_note": self.audio_note,
            "access": self.access.to_dict() if self.access else None,
            "entries": self.entries,
            "subtitle_tracks": self.subtitle_tracks,
        }


_INFO_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_INFO_LOCK = threading.Lock()


def cached_info(url: str) -> dict | None:
    with _INFO_LOCK:
        return _INFO_CACHE.get(url)


def _remember_info(url: str, info: dict) -> None:
    with _INFO_LOCK:
        _INFO_CACHE[url] = info
        _INFO_CACHE.move_to_end(url)
        while len(_INFO_CACHE) > 12:
            _INFO_CACHE.popitem(last=False)


def parse_json_output(output: str) -> dict:
    text = (output or "").strip()
    if not text:
        raise RuntimeError("yt-dlp не вернул данные о видео.")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
    raise RuntimeError("Не удалось разобрать данные о видео.")


def youtube_attempts() -> list[Access]:
    return [
        Access(None, None, "обычный режим"),
        Access("mweb", None, "mweb + PO Token"),
        Access("web_embedded", None, "резервный web_embedded"),
    ]


def browser_attempts(platform: str) -> list[Access]:
    client = "default,web_embedded" if platform == "YouTube" else None
    return [Access(client, key, f"вход через {label}") for key, label in browser_cookie_sources()]


def _best_thumbnail(info: dict) -> str:
    thumb = str(info.get("thumbnail") or "")
    if thumb:
        return thumb
    thumbs = [item for item in (info.get("thumbnails") or []) if isinstance(item, dict) and item.get("url")]
    if thumbs:
        thumbs.sort(key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0))
        return str(thumbs[-1]["url"])
    return ""


def media_info_from_json(url: str, info: dict, access: Access | None) -> MediaInfo:
    platform = detect_platform(url)
    site = platform_label(platform, url)
    if info.get("_type") == "playlist" or (info.get("entries") and not info.get("formats")):
        entries = []
        for entry in info.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            link = str(entry.get("url") or entry.get("webpage_url") or "")
            if platform == "YouTube" and entry.get("id") and not link.startswith("http"):
                link = f"https://www.youtube.com/watch?v={entry['id']}"
            if link:
                entries.append(
                    {"url": link, "title": str(entry.get("title") or ""), "duration": entry.get("duration")}
                )
        return MediaInfo(
            url=url,
            platform=platform,
            site=site,
            kind="playlist",
            title=str(info.get("title") or "Плейлист"),
            uploader=str(info.get("uploader") or info.get("channel") or ""),
            thumbnail=_best_thumbnail(info),
            entries=entries,
            access=access,
        )

    from .subtitles import tracks_from_info  # subtitles reads this module's cache

    choices = quality_choices_from_info(info)
    formats = [item for item in (info.get("formats") or []) if isinstance(item, dict)]
    audio_note, _ = audio_summary(info, formats)
    duration = info.get("duration")
    return MediaInfo(
        url=url,
        platform=platform,
        site=site,
        title=str(info.get("title") or info.get("id") or ""),
        uploader=str(info.get("uploader") or info.get("channel") or info.get("uploader_id") or ""),
        duration=float(duration) if duration else None,
        thumbnail=_best_thumbnail(info),
        is_live=bool(info.get("is_live")),
        choices=choices,
        default_height=default_height(choices),
        audio_note=audio_note,
        access=access,
        subtitle_tracks=len(tracks_from_info(info)),
    )


def analyze_media(
    url: str,
    *,
    token: CancelToken = NEVER,
    report: Report = QUIET,
    app_root: Path | None = None,
) -> MediaInfo:
    url = (url or "").strip()
    if not url:
        raise ValueError("Вставь ссылку.")
    tools = resolve_tools(app_root)
    platform = detect_platform(url)
    site = platform_label(platform, url)

    common = [
        "--socket-timeout", "10",
        "--retries", "1",
        "--extractor-retries", "1",
        "--skip-download",
        "--flat-playlist",
        "--dump-single-json",
    ]
    attempts = youtube_attempts() if platform == "YouTube" else [Access(None, None, "обычный режим")]
    has_cookie_file = cookies_file(app_root) is not None
    browsers_added = False
    seen_text: list[str] = []
    index = 0
    while index < len(attempts):
        access = attempts[index]
        index += 1
        token.raise_if_cancelled()
        report.status(f"Проверяю ссылку · {access.label}")
        report.log(f"[analysis] попытка {index}/{len(attempts)}: {access.label}")
        timeout = 25 if index == 1 else 15
        command = ytdlp_base_args(tools, access, app_root) + common + [url]
        code, stdout, stderr, timed_out = run_capture(command, timeout=timeout, log=report.log, token=token)
        for line in stderr.splitlines():
            if line.strip():
                report.log(line.rstrip())
        seen_text.append(stderr)
        if timed_out:
            seen_text.append("timed out")
            report.log(f"[analysis] попытка {index} остановлена по таймауту {timeout} с")

        if stdout.strip():
            try:
                info = parse_json_output(stdout)
                _remember_info(url, info)
                result = media_info_from_json(url, info, access)
                report.log(f"[analysis] готово: «{result.title}», вариантов качества: {len(result.choices)}")
                return result
            except Exception as exc:
                report.log(f"[analysis] ответ не разобран: {exc}")

        kind = errors.classify(stderr)
        if kind in errors.NO_RETRY_KINDS:
            break
        if kind in {"auth", "private"} and not browsers_added and not has_cookie_file:
            attempts += browser_attempts(platform)
            browsers_added = True

    text = "\n".join(seen_text)
    kind = errors.classify(text)
    message, hint = errors.friendly(kind, site)
    raise UserFacingError(message, kind=kind, hint=hint, details=errors.last_error_lines(text.splitlines()))


# ---- downloading --------------------------------------------------------------------

@dataclass
class DownloadRequest:
    url: str
    output_root: Path
    mode: str = "video"  # video | audio
    height: int | None = None
    exact: bool = False
    audio_format: str = "mp3"
    clip: tuple[float, float] | None = None
    access: Access | None = None
    gpu_encoder: bool = True


def format_selector(height: int | None, exact: bool) -> str:
    if height and exact:
        return (
            f"bv*[height={height}][vcodec^=avc1]+ba[acodec^=mp4a]/"
            f"bv*[height={height}]+ba/b[height={height}]/"
            f"bv*[height<={height}]+ba/b[height<={height}]/b"
        )
    if height:
        return (
            f"bv*[height<={height}][vcodec^=avc1]+ba[acodec^=mp4a]/"
            f"bv*[height<={height}]+ba/b[height<={height}]/b"
        )
    return "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/bv*+ba/b"


_TEMPLATE_PREFIX = "RNGNPROG|"
PROGRESS_TEMPLATE = (
    "download:"
    + _TEMPLATE_PREFIX
    + "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s|%(info.format_id)s"
)
_FORMATS_RE = re.compile(r"Downloading \d+ format\(s\):\s*(\S+)")
_PERCENT_RE = re.compile(r"([0-9]{1,3}(?:\.[0-9]+)?)%")


def human_speed(raw: str) -> str:
    text = (raw or "").strip()
    if not text or "N/A" in text or "Unknown" in text or text == "NA":
        return ""
    for src, dst in (("GiB/s", " ГБ/с"), ("MiB/s", " МБ/с"), ("KiB/s", " КБ/с")):
        if text.endswith(src):
            return text[: -len(src)].strip() + dst
    return text


class YtdlpProgress:
    """Maps yt-dlp output to one monotonic 0..span progress across video+audio parts."""

    def __init__(self, report: Report, span: float, what: str) -> None:
        self.report = report
        self.span = span
        self.what = what
        self.parts = 1
        self.part_index = 0
        self.current_format: str | None = None
        self.best = 0.0
        self.lines: list[str] = []

    def _weights(self) -> list[float]:
        if self.parts == 2:
            return [0.85, 0.15]
        return [1.0 / self.parts] * self.parts

    def on_line(self, line: str) -> None:
        if line.startswith(_TEMPLATE_PREFIX):
            self._on_progress(line[len(_TEMPLATE_PREFIX):])
            return
        self.lines.append(line)
        if len(self.lines) > 400:
            del self.lines[:100]
        self.report.log(line)
        match = _FORMATS_RE.search(line)
        if match:
            self.parts = max(1, match.group(1).count("+") + 1)
        if line.startswith("[Merger]"):
            self.report.status("Собираю видео и звук в один файл…")
        elif line.startswith("[ExtractAudio]"):
            self.report.status("Конвертирую звук…")
        elif line.startswith(("[VideoRemuxer]", "[FixupM3u8]", "[FixupM4a]")):
            self.report.status("Привожу файл в порядок…")

    def _on_progress(self, payload: str) -> None:
        percent_raw, speed_raw, eta_raw, format_id = (payload.split("|") + ["", "", "", ""])[:4]
        format_id = format_id.strip()
        if format_id and format_id != "NA" and self.current_format is not None and format_id != self.current_format:
            self.part_index = min(self.part_index + 1, max(0, self.parts - 1))
        if format_id and format_id != "NA":
            self.current_format = format_id
        match = _PERCENT_RE.search(percent_raw)
        speed = human_speed(speed_raw)
        eta = (eta_raw or "").strip()
        bits = [speed] if speed else []
        if eta and eta not in {"NA", "N/A", "Unknown"}:
            bits.append(f"осталось {eta}")
        detail = " · ".join(bits)
        if not match:
            self.report.progress(None)
            self.report.status(self.what + (f" · {detail}" if detail else ""))
            return
        pct = max(0.0, min(100.0, float(match.group(1))))
        weights = self._weights()
        idx = min(self.part_index, len(weights) - 1)
        overall = sum(weights[:idx]) + weights[idx] * pct / 100.0
        value = overall * self.span
        if value >= self.best:
            self.best = value
            self.report.progress(value)
        self.report.status(f"{self.what} · {overall * 100:.0f}%" + (f" · {detail}" if detail else ""))


def _hide_folder(path: Path) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
    except Exception:
        pass


def temp_root(output_root: Path) -> Path:
    """Temporary job folders live next to the results so the final move is a rename."""
    root = output_root / ".rngn-temp"
    root.mkdir(parents=True, exist_ok=True)
    _hide_folder(root)
    return root


def cleanup_temp(output_root: Path) -> None:
    root = output_root / ".rngn-temp"
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)


def _download_with_ytdlp(
    req: DownloadRequest,
    job: Path,
    tools: Toolset,
    access: Access | None,
    report: Report,
    token: CancelToken,
    span: float,
) -> tuple[bool, list[str]]:
    args = ytdlp_base_args(tools, access) + [
        "--windows-filenames",
        "--socket-timeout", "15",
        "--retries", "5",
        "--fragment-retries", "10",
        "--continue",
        "--newline",
        "--progress",
        "--progress-template", PROGRESS_TEMPLATE,
        "-N", "4",
    ]
    if req.mode == "audio":
        fmt = req.audio_format if req.audio_format in AUDIO_FORMATS else "mp3"
        selector = "ba[ext=m4a]/ba/b" if fmt == "m4a" else "ba/b"
        args += ["-f", selector, "-x", "--audio-format", fmt]
        if fmt == "mp3":
            args += ["--audio-quality", "0"]
        what = "Скачиваю звук"
    else:
        args += [
            "-f", format_selector(req.height, req.exact),
            "--merge-output-format", "mp4",
            "--remux-video", "mp4",
        ]
        what = "Скачиваю видео"

    name = "%(title).150B [%(id)s]"
    if req.clip:
        start, end = req.clip
        section = f"*{_seconds_arg(start)}-{_seconds_arg(end)}"
        args += ["--download-sections", section, "--force-keyframes-at-cuts"]
        name += f" {_clip_tag(start)}-{_clip_tag(end)}"
        what = "Скачиваю отрезок"
        report.log(f"Отрезок: {section}")

    args += ["-o", str(job / f"{name}.%(ext)s"), req.url]
    report.status(f"{what}…")
    tracker = YtdlpProgress(report, span, what)
    code = run_streaming(args, on_line=tracker.on_line, token=token, log=report.log)
    produced = any(path.is_file() and not path.name.endswith((".part", ".ytdl")) for path in job.rglob("*"))
    return code == 0 and produced, tracker.lines


def _download_with_gallery(
    req: DownloadRequest, job: Path, tools: Toolset, report: Report, token: CancelToken
) -> tuple[bool, list[str]]:
    args = [
        str(tools.gallery_dl),
        "--no-color",
        "--windows-filenames",
        "-D", str(job),
        "-o", "extractor.timeout=20",
        "-o", "extractor.retries=2",
        "-o", "extractor.instagram.videos=merged",
        "-o", "extractor.twitter.videos=true",
        "-o", "extractor.twitter.size=orig",
    ]
    cookies = cookies_file()
    if cookies:
        args += ["--cookies", str(cookies)]
    args += [req.url]
    report.status("Скачиваю пост / карусель целиком…")
    report.progress(None)
    lines: list[str] = []

    def on_line(line: str) -> None:
        lines.append(line)
        report.log(line)

    code = run_streaming(args, on_line=on_line, token=token, log=report.log)
    return code == 0 and any(path.is_file() for path in job.rglob("*")), lines


def _clear_folder(folder: Path) -> None:
    for leftover in list(folder.rglob("*")):
        if leftover.is_file():
            leftover.unlink(missing_ok=True)


def download_media(
    req: DownloadRequest,
    *,
    token: CancelToken = NEVER,
    report: Report = QUIET,
    app_root: Path | None = None,
) -> list[Path]:
    url = (req.url or "").strip()
    if not url:
        raise ValueError("Вставь ссылку.")
    if req.clip and req.clip[1] <= req.clip[0]:
        raise ValueError("Конец отрезка должен быть позже начала.")

    tools = resolve_tools(app_root)
    platform = detect_platform(url)
    site = platform_label(platform, url)
    destination = req.output_root / platform_folder(platform)
    destination.mkdir(parents=True, exist_ok=True)
    job = temp_root(req.output_root) / uuid.uuid4().hex[:12]
    job.mkdir(parents=True, exist_ok=True)
    report.progress(0)
    span = 85.0

    try:
        success = False
        collected: list[str] = []
        gallery_tried = False

        if platform in GALLERY_FIRST and req.mode == "video" and not req.clip:
            gallery_tried = True
            success, lines = _download_with_gallery(req, job, tools, report, token)
            collected += lines
            if not success:
                report.log("gallery-dl не справился, пробую yt-dlp.")
                _clear_folder(job)

        if not success:
            candidates: list[Access | None] = [req.access] if req.access else []
            candidates += youtube_attempts() if platform == "YouTube" else [None]
            attempts: list[Access | None] = []
            seen: set[tuple] = set()
            for item in candidates:
                key = (item.client, item.browser) if item else (None, None)
                if key not in seen:
                    seen.add(key)
                    attempts.append(item)
            browsers_added = False
            index = 0
            while index < len(attempts) and not success:
                access = attempts[index]
                index += 1
                token.raise_if_cancelled()
                if index > 1:
                    _clear_folder(job)
                    label = access.label if access else "обычный режим"
                    report.log(f"[download] новая попытка {index}/{len(attempts)}: {label}")
                    report.status(f"Пробую другой способ · {label}")
                success, lines = _download_with_ytdlp(req, job, tools, access, report, token, span)
                collected += lines
                if success:
                    break
                kind = errors.classify("\n".join(lines[-40:]))
                if kind in errors.NO_RETRY_KINDS:
                    break
                if kind in {"auth", "private"} and not browsers_added and cookies_file(app_root) is None:
                    attempts += browser_attempts(platform)
                    browsers_added = True

        if not success and not gallery_tried and req.mode == "video" and not req.clip and platform != "YouTube":
            report.log("yt-dlp не справился, пробую gallery-dl.")
            _clear_folder(job)
            success, lines = _download_with_gallery(req, job, tools, report, token)
            collected += lines

        files = [path for path in job.rglob("*") if path.is_file() and not path.name.endswith((".part", ".ytdl"))]
        if not success or not files:
            text = "\n".join(collected[-80:])
            kind = errors.classify(text)
            message, hint = errors.friendly(kind, site)
            raise UserFacingError(message, kind=kind, hint=hint, details=errors.last_error_lines(collected))

        media = [
            path for path in files if path.suffix.lower() in VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS
        ] or files
        videos = [path for path in media if path.suffix.lower() in VIDEO_EXTENSIONS]
        outputs: list[Path] = []
        for path in media:
            token.raise_if_cancelled()
            if path.suffix.lower() in VIDEO_EXTENSIONS and req.mode == "video":
                share = (100.0 - span) / max(1, len(videos))
                base = span + share * videos.index(path)
                outputs.append(
                    prepare_for_premiere(
                        path,
                        destination,
                        tools,
                        report=report,
                        token=token,
                        progress_base=base,
                        progress_span=share,
                        gpu_encoder=req.gpu_encoder,
                    )
                )
            else:
                outputs.append(move_unique(path, destination))
        if not outputs:
            raise UserFacingError("Файлы скачались, но среди них нет медиа.", kind="unknown")
        report.progress(100)
        report.status(f"Готово · файлов: {len(outputs)}")
        return outputs
    finally:
        shutil.rmtree(job, ignore_errors=True)


# ---- post-processing ------------------------------------------------------------------

def unique_destination(directory: Path, filename: str) -> Path:
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


def move_unique(source: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = unique_destination(destination_dir, source.name)
    shutil.move(str(source), target)
    return target


def probe(path: Path, tools: Toolset) -> dict:
    result = subprocess.run(
        [str(tools.ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags(),
    )
    if result.returncode != 0:
        raise UserFacingError(
            f"Не удалось прочитать файл {path.name}.",
            kind="ffmpeg",
            hint="Файл может быть повреждён или это не медиа.",
            details=result.stderr.strip(),
        )
    return json.loads(result.stdout or "{}")


def stream_codecs(info: dict) -> tuple[str | None, list[str]]:
    video_codec = None
    audio_codecs: list[str] = []
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video" and video_codec is None:
            if (stream.get("disposition") or {}).get("attached_pic"):
                continue
            video_codec = (stream.get("codec_name") or "").lower() or None
        elif stream.get("codec_type") == "audio":
            audio_codecs.append((stream.get("codec_name") or "").lower())
    return video_codec, audio_codecs


def media_duration(info: dict) -> float:
    try:
        return float((info.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        return 0.0


_NVENC_CACHE: dict[str, bool] = {}


def nvenc_available(tools: Toolset, codec: str = "h264_nvenc") -> bool:
    """True when this PC can encode on an NVIDIA GPU (checked once per run)."""
    key = f"{tools.ffmpeg}|{codec}"
    if key in _NVENC_CACHE:
        return _NVENC_CACHE[key]
    ok = False
    try:
        result = subprocess.run(
            [
                str(tools.ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "color=c=black:s=256x256:d=0.2", "-c:v", codec, "-f", "null", "-",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags(),
            timeout=20,
        )
        ok = result.returncode == 0
    except Exception:
        ok = False
    _NVENC_CACHE[key] = ok
    return ok


def run_ffmpeg_with_progress(
    command: list[str],
    *,
    duration: float,
    report: Report,
    token: CancelToken,
    base: float,
    span: float,
    what: str,
) -> tuple[int, list[str]]:
    """Run ffmpeg that has `-progress pipe:1` in `command`; map out_time to base..base+span."""
    lines: list[str] = []
    best = [base]

    def on_line(line: str) -> None:
        key, sep, value = line.partition("=")
        if sep and key and " " not in key and not line.startswith("["):
            if key in {"out_time_us", "out_time_ms"} and duration > 0:
                try:
                    current = int(value) / 1_000_000.0
                except ValueError:
                    return
                fraction = max(0.0, min(1.0, current / duration))
                value_pct = base + span * fraction
                if value_pct >= best[0]:
                    best[0] = value_pct
                    report.progress(value_pct)
                report.status(f"{what} · {fraction * 100:.0f}%")
            return
        lines.append(line)
        if len(lines) > 300:
            del lines[:100]
        report.log(line)

    code = run_streaming(command, on_line=on_line, token=token, log=report.log)
    return code, lines


def h264_encoder_args(tools: Toolset, gpu_encoder: bool) -> tuple[list[str], str]:
    if gpu_encoder and nvenc_available(tools):
        return (
            [
                "-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "19",
                "-b:v", "0", "-profile:v", "high", "-pix_fmt", "yuv420p",
            ],
            "NVIDIA",
        )
    return (
        ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p"],
        "CPU",
    )


def prepare_for_premiere(
    source: Path,
    destination_dir: Path,
    tools: Toolset,
    *,
    report: Report = QUIET,
    token: CancelToken = NEVER,
    progress_base: float = 85.0,
    progress_span: float = 15.0,
    gpu_encoder: bool = True,
) -> Path:
    """MP4 + H.264 + AAC that opens in Premiere; copy streams whenever possible."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    info = probe(source, tools)
    video_codec, audio_codecs = stream_codecs(info)
    duration = media_duration(info)
    report.log(
        f"FFprobe: видео={video_codec or 'нет'}; звук={', '.join(audio_codecs) or 'нет дорожки'}; "
        f"длительность={duration:.1f} с"
    )

    if video_codec is None:
        return move_unique(source, destination_dir)

    audio_ok = not audio_codecs or all(codec == "aac" for codec in audio_codecs)
    if source.suffix.lower() == ".mp4" and video_codec == "h264" and audio_ok:
        report.progress(progress_base + progress_span)
        return move_unique(source, destination_dir)

    target = unique_destination(destination_dir, source.with_suffix(".mp4").name)
    partial = destination_dir / f".rngn-{uuid.uuid4().hex}.partial.mp4"
    audio_args = ["-c:a", "copy"] if audio_ok else ["-c:a", "aac", "-b:a", "320k"]
    base_cmd = [
        str(tools.ffmpeg), "-hide_banner", "-y", "-i", str(source),
        "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn",
    ]
    tail = ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(partial)]

    plans: list[tuple[list[str], str]] = []
    if video_codec == "h264":
        plans.append((["-c:v", "copy"], "Упаковываю в MP4"))
    else:
        encoder, where = h264_encoder_args(tools, gpu_encoder)
        place = "видеокарта" if where == "NVIDIA" else "процессор"
        plans.append((encoder, f"Перекодирую в H.264 для Premiere ({place})"))
        if where == "NVIDIA":
            cpu_encoder, _ = h264_encoder_args(tools, False)
            plans.append((cpu_encoder, "Перекодирую в H.264 для Premiere (процессор)"))

    last_lines: list[str] = []
    try:
        for video_args, what in plans:
            token.raise_if_cancelled()
            report.status(what + "…")
            code, last_lines = run_ffmpeg_with_progress(
                base_cmd + video_args + audio_args + tail,
                duration=duration,
                report=report,
                token=token,
                base=progress_base,
                span=progress_span,
                what=what,
            )
            if code == 0 and partial.is_file() and partial.stat().st_size > 0:
                partial.replace(target)
                source.unlink(missing_ok=True)
                return target
            partial.unlink(missing_ok=True)
            report.log(f"[ffmpeg] «{what}» не сработало (код {code}).")
    except OperationCancelled:
        partial.unlink(missing_ok=True)
        raise
    raise UserFacingError(
        f"FFmpeg не смог подготовить {source.name} для Premiere.",
        kind="ffmpeg",
        hint="Подробности — в журнале задания.",
        details="\n".join(last_lines[-12:]).strip(),
    )
