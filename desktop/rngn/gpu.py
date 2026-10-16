"""NVIDIA acceleration for Whisper: find (or download once) the CUDA 12 + cuDNN 9 DLLs.

The installer does not ship them (~800 MB). On PCs that had ZNAMBO Transcriber the
libraries are already in its data folder, so they are reused from there.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from . import paths
from .errors import UserFacingError
from .procs import NEVER, QUIET, CancelToken, OperationCancelled, Report, creation_flags

ARCHIVE_URL = (
    "https://github.com/Purfview/whisper-standalone-win/releases/download/libs/"
    "cuBLAS.and.cuDNN_CUDA12_win_v3.7z"
)
ARCHIVE_SIZE_HINT = 810 * 1024 * 1024
REQUIRED_DLLS = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn_ops64_9.dll")
PRELOAD_ORDER = ("cublasLt64_12.dll", "cublas64_12.dll")

_lock = threading.Lock()
_active_dir: Path | None = None
_handles: list = []
_gpu_cache: dict | None = None


def own_libs_dir() -> Path:
    return paths.data_dir() / "cuda-libs"


def candidate_dirs() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    extra = os.environ.get("RNGN_CUDA_LIBS")
    if extra:
        found.append((Path(extra), "env"))
    found.append((own_libs_dir(), "rngn"))
    znambo = paths.znambo_dir()
    if znambo:
        found.append((znambo / "cuda-libs", "znambo"))
    found.append((Path(r"C:\ZNAMBO-Transcriber\cuda-libs"), "znambo"))
    cuda_path = os.environ.get("CUDA_PATH")
    if cuda_path:
        found.append((Path(cuda_path) / "bin", "cuda"))
    return found


def _has_runtime(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    names = {item.name.lower() for item in folder.glob("*.dll")}
    return all(name.lower() in names for name in REQUIRED_DLLS)


def find_libs() -> tuple[Path, str] | None:
    if os.name != "nt":
        return None
    for folder, source in candidate_dirs():
        if _has_runtime(folder):
            return folder, source
    return None


def activate() -> Path | None:
    """Make the CUDA DLLs loadable for this process. Safe to call many times."""
    global _active_dir
    with _lock:
        if _active_dir is not None:
            return _active_dir
        found = find_libs()
        if not found:
            return None
        folder, _source = found
        os.environ["PATH"] = f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"
        if hasattr(os, "add_dll_directory"):
            try:
                _handles.append(os.add_dll_directory(str(folder)))
            except OSError:
                pass
        for name in PRELOAD_ORDER:
            try:
                _handles.append(ctypes.WinDLL(str(folder / name)))
            except OSError:
                pass
        _active_dir = folder
        return folder


def nvidia_gpu() -> dict | None:
    """Name/driver/memory of the first NVIDIA GPU, or None (cached)."""
    global _gpu_cache
    if _gpu_cache is not None:
        return _gpu_cache or None
    info: dict = {}
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=6,
            creationflags=creation_flags(),
        )
        line = (result.stdout or "").strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else ""
        if line:
            name, driver, memory = [part.strip() for part in (line.split(",") + ["", ""])[:3]]
            info = {"name": name, "driver": driver, "memory_mb": int(memory) if memory.isdigit() else None}
    except Exception:
        info = {}
    _gpu_cache = info
    return info or None


def cuda_device_count() -> int:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def status() -> dict:
    gpu = nvidia_gpu()
    found = find_libs()
    return {
        "supported": os.name == "nt",
        "gpu": gpu,
        "libs_dir": str(found[0]) if found else None,
        "libs_source": found[1] if found else None,
        "ready": bool(gpu and found),
        "download_mb": ARCHIVE_SIZE_HINT // (1024 * 1024),
    }


def install(*, token: CancelToken = NEVER, report: Report = QUIET) -> Path:
    """Download the CUDA runtime archive once and keep only the DLLs."""
    if os.name != "nt":
        raise UserFacingError("Ускорение NVIDIA доступно только в Windows.", kind="cuda")
    if not nvidia_gpu():
        raise UserFacingError(
            "Видеокарта NVIDIA не найдена.",
            kind="cuda",
            hint="Проверь, что установлен драйвер NVIDIA. Без него расшифровка идёт на процессоре.",
        )
    target = own_libs_dir()
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cuda-", dir=str(paths.data_dir())) as tmp:
        archive = Path(tmp) / "cuda-runtime.7z"
        report.status("Скачиваю библиотеки NVIDIA (один раз)…")
        report.log(f"Источник: {ARCHIVE_URL}")
        request = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "RNGN-Media"})
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as output:
            total = int(response.headers.get("Content-Length") or 0) or ARCHIVE_SIZE_HINT
            done = 0
            while True:
                if token.cancelled:
                    raise OperationCancelled()
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                done += len(chunk)
                elapsed = max(0.1, time.monotonic() - started)
                speed = done / elapsed / (1024 * 1024)
                report.progress(min(90.0, done / total * 90.0))
                report.status(
                    f"Скачиваю библиотеки NVIDIA · {done // (1024 * 1024)} из {total // (1024 * 1024)} МБ · {speed:.1f} МБ/с"
                )
        report.status("Распаковываю библиотеки…")
        report.progress(92)
        extract = Path(tmp) / "x"
        try:
            import py7zr

            with py7zr.SevenZipFile(archive, mode="r") as seven:
                seven.extractall(path=extract)
        except Exception as exc:
            raise UserFacingError("Не удалось распаковать архив NVIDIA.", kind="cuda", details=str(exc)) from exc
        dlls = list(extract.rglob("*.dll"))
        names = {item.name.lower() for item in dlls}
        missing = [name for name in REQUIRED_DLLS if name.lower() not in names]
        if missing:
            raise UserFacingError("В архиве NVIDIA нет нужных файлов.", kind="cuda", details=", ".join(missing))
        for dll in dlls:
            shutil.copy2(dll, target / dll.name)
    report.progress(100)
    report.status("Ускорение NVIDIA готово")
    return target
