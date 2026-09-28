from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

# Compatibility shim used by desktop_app.py.
# The CUDA archive uses the BCJ2 filter, which the pure-Python py7zr package
# cannot currently extract. 7-Zip's small standalone 7zr.exe supports 7z,
# LZMA and BCJ2, so we use it without requiring a system-wide installation.

SEVEN_ZIP_URL = "https://www.7-zip.org/a/7zr.exe"
APP_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ZNAMBO Transcriber"
TOOLS_DIR = APP_DIR / "tools"
CACHED_7ZR = TOOLS_DIR / "7zr.exe"


def _find_system_7zip() -> Path | None:
    for command in ("7z", "7zz", "7za", "7zr"):
        found = shutil.which(command)
        if found:
            return Path(found)

    candidates = [
        Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "7-Zip" / "7z.exe",
        Path(os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "7-Zip" / "7z.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _download_7zr() -> Path:
    if CACHED_7ZR.is_file() and CACHED_7ZR.stat().st_size > 100_000:
        return CACHED_7ZR

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = CACHED_7ZR.with_suffix(".download")
    temp_path.unlink(missing_ok=True)

    request = urllib.request.Request(
        SEVEN_ZIP_URL,
        headers={"User-Agent": "ZNAMBO-Transcriber/1.2"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response, temp_path.open("wb") as output:
            shutil.copyfileobj(response, output)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(
            "Не удалось скачать официальный распаковщик 7-Zip (7zr.exe). "
            "Проверь интернет-соединение и повтори настройку GPU."
        ) from exc

    if not temp_path.is_file() or temp_path.stat().st_size < 100_000:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError("Скачанный 7zr.exe выглядит повреждённым или пустым.")

    os.replace(temp_path, CACHED_7ZR)
    return CACHED_7ZR


def _get_extractor() -> Path:
    return _find_system_7zip() or _download_7zr()


class SevenZipFile:
    """Minimal API compatible with the calls used by desktop_app.py."""

    def __init__(self, file, mode: str = "r", *args, **kwargs) -> None:
        if mode not in {"r", "rb"}:
            raise ValueError("ZNAMBO 7z compatibility layer supports read mode only")
        self.archive_path = Path(file)

    def __enter__(self) -> "SevenZipFile":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def extractall(self, path=None, *args, **kwargs) -> None:
        destination = Path(path or Path.cwd())
        destination.mkdir(parents=True, exist_ok=True)
        extractor = _get_extractor()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        result = subprocess.run(
            [
                str(extractor),
                "x",
                str(self.archive_path),
                f"-o{destination}",
                "-y",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=flags,
            check=False,
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "unknown 7-Zip error").strip()
            raise RuntimeError(
                f"7-Zip не смог распаковать CUDA-архив (код {result.returncode}): {details}"
            )
