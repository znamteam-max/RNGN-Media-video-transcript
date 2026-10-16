from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Folder that holds the EXE (packaged) or the `desktop/` source folder."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def ui_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_root())) / "ui"
    return app_root() / "ui"


def assets_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_root())) / "assets"
    return app_root() / "assets"


def data_dir() -> Path:
    override = os.environ.get("RNGN_DATA_DIR")  # isolated settings/history for test runs
    local = os.environ.get("LOCALAPPDATA")
    if override:
        path = Path(override)
    elif local:
        path = Path(local) / "RNGN-Media"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "RNGN Media"
    else:
        path = Path.home() / ".rngn-media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def znambo_dir() -> Path | None:
    """Data folder of the older ZNAMBO Transcriber app (models and CUDA libraries)."""
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "ZNAMBO Transcriber" if local else None


def default_output_dir() -> Path:
    videos = Path.home() / "Videos"
    if sys.platform == "darwin":
        videos = Path.home() / "Movies"
    base = videos if videos.exists() else Path.home()
    return base / "RNGN Media"
