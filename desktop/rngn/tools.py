"""Locating the bundled media tools (yt-dlp, gallery-dl, FFmpeg, Deno) and their arguments."""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from . import paths


@dataclass(frozen=True)
class Toolset:
    yt_dlp: Path
    gallery_dl: Path
    ffmpeg: Path
    ffprobe: Path
    deno: Path | None = None
    # Folder with yt-dlp-plugins and the PO Token provider (parent of bin/).
    bundle_root: Path | None = None


def exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _candidate_roots(app_root: Path) -> Iterable[Path]:
    override = os.environ.get("RNGN_TOOLS_DIR")  # dev runs from source: point at an installed copy
    if override:
        yield Path(override)
    yield app_root / "tools" / "bin"
    # PyInstaller .app on macOS: Contents/MacOS/RNGN Media
    if sys.platform == "darwin" and app_root.name == "MacOS":
        yield app_root.parent / "Resources" / "tools" / "bin"
    yield app_root / "legacy" / "downloader-v5.16.1" / "bin"
    local = os.environ.get("LOCALAPPDATA")
    if local:
        yield Path(local) / "MediaDownloaderPremiere" / "bin"
    if sys.platform == "darwin":
        yield Path.home() / "Library" / "Application Support" / "RNGN Media" / "tools" / "bin"


def user_tools_dir() -> Path:
    """Writable folder for tool updates (Program Files is read-only for the app)."""
    path = paths.data_dir() / "tools" / "bin"
    path.mkdir(parents=True, exist_ok=True)
    return path


def versions_file() -> Path:
    return paths.data_dir() / "tools" / "versions.json"


def read_versions() -> dict:
    try:
        return json.loads(versions_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_versions(data: dict) -> None:
    target = versions_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def version_key(value: str | None) -> tuple[int, ...]:
    """yt-dlp/gallery-dl versions look like 2026.08.19 or 1.30.2; compare numerically."""
    return tuple(int(part) for part in re.findall(r"\d+", value or ""))


def _updated_copy(name: str, bundled: Path) -> Path:
    """Use a self-updated copy only when it is known to be newer than the bundled one."""
    candidate = user_tools_dir() / exe(name)
    if not candidate.is_file():
        return bundled
    info = read_versions().get(name) or {}
    if version_key(info.get("user")) > version_key(info.get("bundled")):
        return candidate
    return bundled


def resolve_tools(app_root: Path | None = None, *, allow_updates: bool = True) -> Toolset:
    root = app_root or paths.app_root()
    checked: list[str] = []
    for candidate in _candidate_roots(root):
        checked.append(str(candidate))
        yt = candidate / exe("yt-dlp")
        gal = candidate / exe("gallery-dl")
        ffmpeg = candidate / exe("ffmpeg")
        ffprobe = candidate / exe("ffprobe")
        if all(path.is_file() for path in (yt, gal, ffmpeg, ffprobe)):
            deno = candidate / exe("deno")
            tools = Toolset(yt, gal, ffmpeg, ffprobe, deno if deno.is_file() else None, candidate.parent)
            if allow_updates:
                tools = replace(
                    tools,
                    yt_dlp=_updated_copy("yt-dlp", yt),
                    gallery_dl=_updated_copy("gallery-dl", gal),
                )
            return tools

    where = "\n".join(f"• {path}" for path in checked)
    raise RuntimeError(
        "Не найдены встроенные yt-dlp / gallery-dl / FFmpeg. "
        "Переустанови RNGN Media. Проверенные папки:\n" + where
    )


# ---- cookies -------------------------------------------------------------------------

def user_cookies_file() -> Path:
    return paths.data_dir() / "cookies.txt"


def cookies_file(app_root: Path | None = None) -> Path | None:
    root = app_root or paths.app_root()
    candidates = [user_cookies_file(), root / "cookies.txt", root.parent / "cookies.txt"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "MediaDownloaderPremiere" / "cookies.txt")
    for path in candidates:
        if path.is_file():
            return path
    return None


def cookie_domains(path: Path) -> list[str]:
    """Readable list of sites a Netscape cookies.txt covers (for the settings screen)."""
    domains: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip() or (line.startswith("#") and not line.startswith("#HttpOnly_")):
                continue
            host = line.split("\t", 1)[0].replace("#HttpOnly_", "").lstrip(".").lower()
            parts = host.split(".")
            if len(parts) >= 2:
                domains.add(".".join(parts[-2:]))
    except OSError:
        return []
    return sorted(domains)


def looks_like_cookies_file(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return False
    if "Netscape HTTP Cookie File" in head or "# HTTP Cookie File" in head:
        return True
    return any(line.count("\t") >= 6 for line in head.splitlines() if not line.startswith("#"))


def browser_cookie_sources() -> list[tuple[str, str]]:
    """Installed browsers in retry order. On Windows Firefox goes first: Chrome and Edge
    encrypt cookies in a way yt-dlp usually cannot read."""
    home = Path.home()
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", home))
        roaming = Path(os.environ.get("APPDATA", home))
        candidates = [
            ("firefox", "Firefox", roaming / "Mozilla" / "Firefox"),
            ("chrome", "Google Chrome", local / "Google" / "Chrome" / "User Data"),
            ("edge", "Microsoft Edge", local / "Microsoft" / "Edge" / "User Data"),
            ("brave", "Brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
        ]
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
        candidates = [
            ("chrome", "Google Chrome", base / "Google" / "Chrome"),
            ("firefox", "Firefox", base / "Firefox"),
            ("edge", "Microsoft Edge", base / "Microsoft Edge"),
            ("brave", "Brave", base / "BraveSoftware" / "Brave-Browser"),
            ("safari", "Safari", home / "Library" / "Cookies"),
        ]
    else:
        candidates = [
            ("firefox", "Firefox", home / ".mozilla" / "firefox"),
            ("chrome", "Google Chrome", home / ".config" / "google-chrome"),
            ("chromium", "Chromium", home / ".config" / "chromium"),
            ("brave", "Brave", home / ".config" / "BraveSoftware" / "Brave-Browser"),
        ]
    return [(key, label) for key, label, path in candidates if path.exists()]


# ---- yt-dlp arguments ---------------------------------------------------------------

def pot_provider_args(tools: Toolset) -> list[str]:
    tools_root = tools.bundle_root or tools.ffmpeg.parent.parent
    plugin_dir = tools_root / "yt-dlp-plugins"
    plugin_zip = plugin_dir / "bgutil-ytdlp-pot-provider.zip"
    server_home = tools_root / "bgutil-ytdlp-pot-provider" / "server"
    if not (plugin_zip.is_file() and server_home.is_dir() and tools.deno and tools.deno.is_file()):
        return []
    return [
        "--plugin-dirs",
        str(plugin_dir),
        "--extractor-args",
        f"youtubepot-bgutilscript:server_home={server_home}",
    ]


@dataclass(frozen=True)
class Access:
    """How yt-dlp reached the source: YouTube player client and/or browser cookies."""
    client: str | None = None
    browser: str | None = None
    label: str = "обычный режим"

    def to_dict(self) -> dict:
        return {"client": self.client, "browser": self.browser, "label": self.label}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Access | None":
        if not data:
            return None
        return cls(data.get("client"), data.get("browser"), data.get("label") or "обычный режим")


def ytdlp_base_args(tools: Toolset, access: Access | None = None, app_root: Path | None = None) -> list[str]:
    args = [
        str(tools.yt_dlp),
        "--ignore-config",
        "--no-color",
        "--no-playlist",
        "--encoding",
        "utf-8",
        "--ffmpeg-location",
        str(tools.ffmpeg.parent),
    ]
    if tools.deno:
        args += ["--js-runtimes", f"deno:{tools.deno}"]
    args += pot_provider_args(tools)
    if access and access.browser:
        args += ["--cookies-from-browser", access.browser]
    else:
        cookies = cookies_file(app_root)
        if cookies:
            args += ["--cookies", str(cookies)]
    if access and access.client:
        args += ["--extractor-args", f"youtube:player_client={access.client}"]
    return args
