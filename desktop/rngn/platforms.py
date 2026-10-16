from __future__ import annotations

import re
from urllib.parse import urlparse

# Folder name on disk -> host suffixes. Anything else still downloads (yt-dlp knows
# 1800+ sites); it just lands in "Other".
_PLATFORM_HOSTS: dict[str, tuple[str, ...]] = {
    "YouTube": ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    "VK": ("vk.com", "vkvideo.ru", "vk.video", "vk.ru"),
    "TikTok": ("tiktok.com",),
    "Instagram": ("instagram.com",),
    "X_Twitter": ("x.com", "twitter.com", "t.co"),
    "Rutube": ("rutube.ru",),
    "Dzen": ("dzen.ru",),
    "OK": ("ok.ru",),
    "Vimeo": ("vimeo.com",),
    "Twitch": ("twitch.tv",),
    "Facebook": ("facebook.com", "fb.watch"),
    "Reddit": ("reddit.com", "redd.it"),
}

PLATFORM_LABELS = {
    "YouTube": "YouTube",
    "VK": "VK Видео",
    "TikTok": "TikTok",
    "Instagram": "Instagram",
    "X_Twitter": "X (Twitter)",
    "Rutube": "Rutube",
    "Dzen": "Дзен",
    "OK": "Одноклассники",
    "Vimeo": "Vimeo",
    "Twitch": "Twitch",
    "Facebook": "Facebook",
    "Reddit": "Reddit",
}

# Sites where gallery-dl is the better first choice (posts, carousels, photos).
GALLERY_FIRST = {"Instagram", "X_Twitter"}

_URL_RE = re.compile(r"https?://[^\s<>\"'\]\[)(]+", re.IGNORECASE)


def host_of(url: str) -> str:
    try:
        return (urlparse((url or "").strip()).hostname or "").lower()
    except Exception:
        return ""


def detect_platform(url: str) -> str:
    host = host_of(url)
    if not host:
        return "Other"
    for platform, suffixes in _PLATFORM_HOSTS.items():
        for suffix in suffixes:
            if host == suffix or host.endswith("." + suffix):
                return platform
    return "Other"


def platform_folder(platform: str) -> str:
    return platform if platform in _PLATFORM_HOSTS else "Other"


def platform_label(platform: str, url: str = "") -> str:
    if platform in PLATFORM_LABELS:
        return PLATFORM_LABELS[platform]
    host = host_of(url)
    return host[4:] if host.startswith("www.") else (host or "Сайт")


def clean_pasted_url(value: str) -> str:
    text = (value or "").strip()
    match = _URL_RE.search(text)
    if match:
        text = match.group(0)
    return text.rstrip(".,;)]}>")


def extract_urls(text: str) -> list[str]:
    """All distinct links in pasted text, in order (one per line or mixed with words)."""
    seen: set[str] = set()
    result: list[str] = []
    for match in _URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,;)]}>")
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result
