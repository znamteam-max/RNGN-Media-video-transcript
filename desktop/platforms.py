from __future__ import annotations

from urllib.parse import urlparse


def detect_platform(url: str) -> str:
    try:
        host = (urlparse(url.strip()).hostname or "").lower()
    except Exception:
        return "Other"

    if host == "youtu.be" or host.endswith(".youtu.be") or host == "youtube.com" or host.endswith(".youtube.com"):
        return "YouTube"
    if host == "vk.com" or host.endswith(".vk.com") or host == "vkvideo.ru" or host.endswith(".vkvideo.ru") or host == "vk.video" or host.endswith(".vk.video"):
        return "VK"
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "TikTok"
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "Instagram"
    if host in {"x.com", "twitter.com", "t.co"} or host.endswith(".x.com") or host.endswith(".twitter.com"):
        return "X_Twitter"
    return "Other"


def platform_folder(platform: str) -> str:
    return platform if platform in {"YouTube", "VK", "TikTok", "Instagram", "X_Twitter"} else "Other"
