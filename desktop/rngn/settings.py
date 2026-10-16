"""User choices that survive restarts (folder, theme, quality, model, language...)."""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

from . import paths

DEFAULTS: dict = {
    "output_root": "",
    "theme": "system",  # system | light | dark
    "download": {
        "mode": "video",  # video | audio | subtitles
        "height": 1080,
        "audio_format": "mp3",
        "transcribe_after": False,
        "subtitle_formats": ["txt", "srt"],
    },
    "transcribe": {
        "model": "turbo",
        "language": "mixed",
        "timestamps": False,
        "formats": ["txt", "srt"],
        "use_gpu": True,
    },
    "convert": {"profile": "premiere"},
    "gpu_encoder": True,
    "auto_update_tools": True,
    "check_app_updates": True,
    "last_tools_check": 0,
    "last_app_check": 0,
    "app_update": None,
    "window": {"width": 1200, "height": 820},
}

_CHOICES = {
    ("theme",): {"system", "light", "dark"},
    ("download", "mode"): {"video", "audio", "subtitles"},
    ("download", "audio_format"): {"mp3", "m4a", "wav"},
    ("transcribe", "model"): {"turbo", "large"},
}


def _merge(base: dict, patch: dict, path: tuple = ()) -> dict:
    for key, value in patch.items():
        if key not in base:
            continue
        here = path + (key,)
        if isinstance(base[key], dict) and isinstance(value, dict):
            _merge(base[key], value, here)
            continue
        allowed = _CHOICES.get(here)
        if allowed is not None and value not in allowed:
            continue
        base[key] = value
    return base


class Settings:
    def __init__(self, file: Path | None = None) -> None:
        self.file = file or (paths.data_dir() / "settings.json")
        self._lock = threading.Lock()
        self._data = copy.deepcopy(DEFAULTS)
        try:
            stored = json.loads(self.file.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                _merge(self._data, stored)
        except (OSError, ValueError):
            pass
        if not self._data.get("output_root"):
            self._data["output_root"] = str(paths.default_output_dir())

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def get(self, *keys, default=None):
        with self._lock:
            value = self._data
            for key in keys:
                if not isinstance(value, dict) or key not in value:
                    return default
                value = value[key]
            return copy.deepcopy(value)

    @property
    def output_root(self) -> Path:
        return Path(self.get("output_root") or paths.default_output_dir()).expanduser()

    def update(self, patch: dict) -> dict:
        with self._lock:
            _merge(self._data, patch or {})
            self._save_locked()
            return copy.deepcopy(self._data)

    def _save_locked(self) -> None:
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.file)
        except OSError:
            pass
