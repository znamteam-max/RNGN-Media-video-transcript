"""Turning tool output into short, human messages (the full log stays available)."""
from __future__ import annotations

import re


class UserFacingError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "unknown", hint: str = "", details: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.hint = hint
        self.details = details


_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("disk", ("no space left", "errno 28", "not enough space", "недостаточно места")),
    ("private", ("private video", "this video is private", "video is private")),
    ("auth", (
        "sign in to confirm", "not a bot", "login required", "requires authentication",
        "use --cookies", "cookies-from-browser", "log in to", "login to", "account to view",
        "inappropriate for some users", "age-restricted", "confirm your age",
    )),
    ("rate_limit", ("http error 429", "too many requests")),
    ("forbidden", ("http error 403", "403 forbidden", "forbidden")),
    ("geo", (
        "not available in your country", "geo restrict", "geo-restrict", "geoblocked",
        "ip address is blocked", "not available in your region",
    )),
    ("unavailable", (
        "video unavailable", "has been removed", "does not exist", "http error 404",
        "no video formats found", "this video is not available", "is not available",
    )),
    ("unsupported", ("unsupported url",)),
    ("format", ("requested format is not available",)),
    ("timeout", ("timed out", "timeout", "read operation timed out")),
    ("network", (
        "getaddrinfo", "network is unreachable", "name or service not known",
        "unable to download webpage", "connection reset", "connection refused",
        "failed to establish a new connection", "temporary failure in name resolution",
        "remote end closed connection", "ssl", "urlopen error",
    )),
    ("ffmpeg", ("ffmpeg не смог", "conversion failed", "error while decoding", "invalid data found")),
]

_MESSAGES: dict[str, tuple[str, str]] = {
    "disk": ("На диске закончилось место.", "Освободи место или выбери другую папку в настройках."),
    "private": ("Это закрытое видео.", "Нужен вход: загрузи файл cookies в «Настройки → Вход на сайты»."),
    "auth": (
        "{site} требует вход в аккаунт.",
        "Войди на сайт в Firefox или загрузи файл cookies в «Настройки → Вход на сайты», затем повтори.",
    ),
    "rate_limit": ("{site} временно ограничил запросы.", "Подожди несколько минут и нажми «Повторить»."),
    "forbidden": ("{site} отклонил запрос.", "Нажми «Повторить». Если не поможет — включи вход на сайт в настройках."),
    "geo": ("{site} не пускает с этого подключения.", "Включи VPN (или выключи, если он включён) и нажми «Повторить»."),
    "unavailable": ("Видео недоступно или удалено.", "Проверь ссылку в браузере."),
    "unsupported": ("Этот сайт не поддерживается.", "Пришли ссылку разработчику — проверим."),
    "format": ("Выбранное качество недоступно.", "Выбери другое качество и повтори."),
    "timeout": ("{site} слишком долго отвечает.", "Проверь интернет и нажми «Повторить»."),
    "network": ("Нет связи с сайтом.", "Проверь интернет или VPN и нажми «Повторить»."),
    "ffmpeg": ("Не удалось обработать файл.", "Файл может быть повреждён. Подробности — в журнале задания."),
    "cancelled": ("Отменено.", ""),
    "unknown": ("Не получилось.", "Открой «Подробности» и скопируй журнал — по нему видно причину."),
}

# Errors where another YouTube client or cookies will not help.
NO_RETRY_KINDS = {"unavailable", "geo", "disk", "ffmpeg", "unsupported"}


def classify(text: str) -> str:
    value = (text or "").lower()
    for kind, needles in _PATTERNS:
        if any(needle in value for needle in needles):
            return kind
    return "unknown"


def friendly(kind: str, site: str = "Сайт") -> tuple[str, str]:
    message, hint = _MESSAGES.get(kind, _MESSAGES["unknown"])
    return message.format(site=site or "Сайт"), hint


def last_error_lines(lines: list[str], limit: int = 6) -> str:
    """The yt-dlp/ffmpeg lines that actually explain a failure."""
    picked = [line for line in lines if re.search(r"\b(ERROR|WARNING)\b|error", line, re.IGNORECASE)]
    return "\n".join((picked or lines)[-limit:]).strip()
