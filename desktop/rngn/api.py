"""Bridge between the HTML interface (window.pywebview.api.*) and the engine."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import APP_NAME, APP_VERSION, converter, downloader, gpu, paths, subtitles, tools, transcriber, updater
from .errors import UserFacingError
from .jobs import JobManager
from .platforms import detect_platform, extract_urls, platform_label
from .procs import CancelToken, OperationCancelled, Report, creation_flags
from .settings import Settings


def _error(exc: Exception) -> dict:
    if isinstance(exc, UserFacingError):
        return {"ok": False, "error": {"message": str(exc), "hint": exc.hint, "kind": exc.kind, "details": exc.details}}
    if isinstance(exc, ValueError):
        return {"ok": False, "error": {"message": str(exc), "hint": "", "kind": "input", "details": ""}}
    return {"ok": False, "error": {"message": "Не получилось.", "hint": "Подробности в журнале.", "kind": "unknown",
                                   "details": str(exc)}}


# ---- clipboard ------------------------------------------------------------------------

def read_clipboard() -> str:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        for _ in range(5):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.05)
        else:
            return ""
        try:
            handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
            if not handle:
                return ""
            pointer = kernel32.GlobalLock(handle)
            try:
                return ctypes.wstring_at(pointer) if pointer else ""
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    if sys.platform == "darwin":
        return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
    return ""


def write_clipboard(text: str) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        data = (text or "").encode("utf-16-le") + b"\x00\x00"
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            pointer = kernel32.GlobalLock(handle)
            ctypes.memmove(pointer, data, len(data))
            kernel32.GlobalUnlock(handle)
            return bool(user32.SetClipboardData(13, handle))
        finally:
            user32.CloseClipboard()
    if sys.platform == "darwin":
        subprocess.run(["pbcopy"], input=text or "", text=True)
        return True
    return False


# ---- API --------------------------------------------------------------------------------

class Api:
    def __init__(self) -> None:
        self._window = None
        self._emit_lock = threading.Lock()
        self._settings = Settings()
        self._jobs = JobManager(self._settings, self._emit)
        self._analysis_token: CancelToken | None = None
        self._analysis_lock = threading.Lock()
        self._tools_state: dict = {}
        self._ready = threading.Event()
        self._on_theme = lambda _value: None

    # Not exposed to JS (leading underscore).
    def _attach(self, window) -> None:
        self._window = window

    def _emit(self, event: dict) -> None:
        window = self._window
        if window is None or not self._ready.is_set():
            return
        payload = json.dumps(event, ensure_ascii=False)
        with self._emit_lock:
            try:
                window.run_js(f"window.rngn && window.rngn.receive({payload})")
            except Exception:
                pass

    def _background_start(self) -> None:
        """Housekeeping that must not slow down the first paint."""
        downloader.cleanup_temp(self._settings.output_root)
        if self._settings.get("auto_update_tools", default=True):
            try:
                self._tools_state = updater.update_tools()
            except Exception as exc:
                self._tools_state = {"error": str(exc)}
            self._emit({"type": "tools", "tools": self._tools_view()})
        if self._settings.get("check_app_updates", default=True):
            if time.time() - float(self._settings.get("last_app_check", default=0) or 0) > 6 * 3600:
                try:
                    update = updater.check_app_update()
                    self._settings.update({"app_update": update, "last_app_check": time.time()})
                except Exception:
                    update = self._settings.get("app_update")
            else:
                update = self._settings.get("app_update")
            if update and tools.version_key(update.get("version")) > tools.version_key(APP_VERSION):
                self._emit({"type": "app_update", "update": update})

    def _shutdown(self) -> None:
        if self._analysis_token:
            self._analysis_token.cancel()
        self._jobs.shutdown()

    def _tools_view(self) -> dict:
        versions = tools.read_versions()
        view = {}
        for name in ("yt-dlp", "gallery-dl"):
            entry = versions.get(name) or {}
            current = max(entry.get("bundled") or "", entry.get("user") or "", key=tools.version_key)
            view[name] = {
                "version": current or None,
                "checked": entry.get("checked"),
                "status": (self._tools_state.get(name) or {}).get("status"),
            }
        return view

    def _cookies_view(self) -> dict:
        found = tools.cookies_file()
        return {
            "file": str(found) if found else None,
            "own": bool(found and found == tools.user_cookies_file()),
            "domains": tools.cookie_domains(found) if found else [],
        }

    # ---- startup ------------------------------------------------------------------------

    def bootstrap(self) -> dict:
        self._ready.set()
        threading.Thread(target=self._background_start, name="startup", daemon=True).start()
        return {
            "app": {"name": APP_NAME, "version": APP_VERSION,
                    "platform": "windows" if os.name == "nt" else ("mac" if sys.platform == "darwin" else "linux")},
            "settings": self._settings.snapshot(),
            "jobs": self._jobs.list(),
            "gpu": gpu.status(),
            "models": transcriber.models_status(),
            "languages": [{"id": key, "label": label} for key, label, _code in transcriber.LANGUAGE_OPTIONS],
            "profiles": converter.PROFILES,
            "tools": self._tools_view(),
            "cookies": self._cookies_view(),
            "update": self._settings.get("app_update"),
        }

    # ---- links ----------------------------------------------------------------------------

    def analyze(self, text: str) -> dict:
        urls = extract_urls(text or "")
        if not urls:
            return {"ok": False, "error": {"message": "Здесь нет ссылки.", "hint": "Скопируй адрес видео из браузера.",
                                           "kind": "input", "details": ""}}
        if len(urls) > 1:
            return {"ok": True, "kind": "batch",
                    "urls": [{"url": url, "site": platform_label(detect_platform(url), url)} for url in urls]}
        with self._analysis_lock:
            if self._analysis_token:
                self._analysis_token.cancel()
            token = CancelToken()
            self._analysis_token = token
        url = urls[0]
        try:
            info = downloader.analyze_media(url, token=token)
            return {"ok": True, "kind": "media", "info": info.to_dict()}
        except OperationCancelled:
            return {"ok": False, "cancelled": True}
        except Exception as exc:
            result = _error(exc)
            result["url"] = url
            result["site"] = platform_label(detect_platform(url), url)
            return result

    def cancel_analysis(self) -> bool:
        with self._analysis_lock:
            if self._analysis_token:
                self._analysis_token.cancel()
                return True
        return False

    def subtitle_tracks(self, url: str) -> dict:
        try:
            info = subtitles.analyze_subtitles(url)
            return {"ok": True, "info": info.to_dict()}
        except Exception as exc:
            return _error(exc)

    # ---- jobs -------------------------------------------------------------------------------

    def _download_params(self, params: dict) -> dict:
        clip = params.get("clip")
        result = {
            "url": str(params.get("url") or ""),
            "mode": params.get("mode") if params.get("mode") in {"video", "audio"} else "video",
            "height": int(params["height"]) if params.get("height") else None,
            "exact": bool(params.get("exact")),
            "audio_format": params.get("audio_format") or "mp3",
            "clip": [float(clip[0]), float(clip[1])] if clip else None,
            "access": params.get("access"),
            "output_root": str(self._settings.output_root),
        }
        if params.get("transcribe_after"):
            result["transcribe_after"] = self._settings.get("transcribe")
        return result

    def start_download(self, params: dict) -> dict:
        meta = {
            "site": params.get("site") or platform_label(detect_platform(params.get("url", "")), params.get("url", "")),
            "thumbnail": params.get("thumbnail") or "",
            "url": params.get("url"),
            "duration": params.get("duration"),
        }
        job = self._jobs.submit("download", params.get("title") or params.get("url") or "Видео",
                               self._download_params(params), meta=meta)
        return job.to_dict()

    def start_batch(self, urls: list, params: dict) -> list:
        created = []
        for url in urls or []:
            item = dict(params or {})
            item.update({"url": url, "exact": False, "clip": None, "access": None, "title": url, "thumbnail": ""})
            created.append(self.start_download(item))
        return created

    def start_subtitles(self, params: dict) -> dict:
        job_params = {
            "url": params.get("url"),
            "track": params.get("track") or {},
            "formats": params.get("formats") or ["txt", "srt"],
            "title": params.get("title") or "",
            "output_root": str(self._settings.output_root),
        }
        meta = {"site": params.get("site") or "", "thumbnail": params.get("thumbnail") or "", "url": params.get("url")}
        title = f"{params.get('title') or 'Субтитры'} · {((params.get('track') or {}).get('name') or '')}".strip(" ·")
        return self._jobs.submit("subtitles", title, job_params, meta=meta).to_dict()

    def start_transcribe(self, files: list, options: dict | None = None) -> list:
        options = {**(self._settings.get("transcribe") or {}), **(options or {})}
        created = []
        for file in files or []:
            path = Path(file)
            params = {
                "file": str(path),
                "model": options.get("model", "turbo"),
                "language": options.get("language", "mixed"),
                "timestamps": bool(options.get("timestamps")),
                "formats": options.get("formats") or ["txt", "srt"],
                "use_gpu": bool(options.get("use_gpu", True)),
                "output_root": str(self._settings.output_root),
            }
            created.append(self._jobs.submit("transcribe", path.stem, params, meta={"file": str(path)}).to_dict())
        return created

    def start_convert(self, files: list, profile: str) -> list:
        created = []
        label = converter.PROFILES_BY_ID.get(profile, {}).get("label", "")
        for file in files or []:
            path = Path(file)
            params = {"file": str(path), "profile": profile, "output_root": str(self._settings.output_root)}
            created.append(self._jobs.submit("convert", f"{path.stem} → {label}", params, meta={"file": str(path)}).to_dict())
        return created

    def setup_gpu(self) -> dict:
        return self._jobs.submit("gpu_setup", "Ускорение NVIDIA", {}).to_dict()

    def cancel_job(self, job_id: str) -> bool:
        return self._jobs.cancel(job_id)

    def retry_job(self, job_id: str) -> dict | None:
        job = self._jobs.retry(job_id)
        return job.to_dict() if job else None

    def remove_job(self, job_id: str) -> bool:
        return self._jobs.remove(job_id)

    def clear_finished(self) -> int:
        return self._jobs.clear_finished()

    def job_log(self, job_id: str, since: int = 0) -> dict:
        return self._jobs.log(job_id, int(since or 0))

    # ---- files --------------------------------------------------------------------------------

    def describe_files(self, files: list) -> list:
        result = []
        for file in files or []:
            path = Path(str(file))
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            kind = "video" if suffix in converter.VIDEO_INPUTS else ("audio" if suffix in downloader.AUDIO_EXTENSIONS else "other")
            result.append({"path": str(path), "name": path.name, "size": path.stat().st_size, "kind": kind,
                           "transcribable": suffix in transcriber.SUPPORTED_EXTENSIONS})
        return result

    def pick_files(self, purpose: str = "media") -> list:
        if self._window is None:
            return []
        import webview

        if purpose == "cookies":
            types = ("Файл cookies (*.txt)", "Все файлы (*.*)")
            multiple = False
        elif purpose == "video":
            types = ("Видео (*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v;*.ts;*.mts;*.m2ts;*.wmv;*.flv)", "Все файлы (*.*)")
            multiple = True
        else:
            types = (
                "Аудио и видео (*.mp3;*.m4a;*.wav;*.aac;*.flac;*.ogg;*.opus;*.wma;*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v;*.ts;*.mts;*.m2ts)",
                "Все файлы (*.*)",
            )
            multiple = True
        chosen = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=multiple, file_types=types)
        return [str(item) for item in (chosen or [])]

    def pick_folder(self) -> dict:
        if self._window is None:
            return self._settings.snapshot()
        import webview

        chosen = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=str(self._settings.output_root))
        if chosen:
            folder = chosen[0] if isinstance(chosen, (list, tuple)) else chosen
            return self._settings.update({"output_root": str(folder)})
        return self._settings.snapshot()

    def open_path(self, path: str) -> bool:
        target = Path(path or "")
        if not target.exists():
            if not target.suffix:
                target.mkdir(parents=True, exist_ok=True)
            else:
                return False
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=False)
        else:
            subprocess.run(["xdg-open", str(target)], check=False)
        return True

    def reveal_path(self, path: str) -> bool:
        target = Path(path or "")
        if not target.exists():
            return self.open_path(str(target.parent)) if target.parent.exists() else False
        if os.name == "nt":
            subprocess.run(["explorer", f"/select,{target}"], check=False, creationflags=creation_flags())
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(target)], check=False)
        else:
            subprocess.run(["xdg-open", str(target.parent)], check=False)
        return True

    def open_output(self, sub: str = "") -> bool:
        folder = self._settings.output_root / sub if sub else self._settings.output_root
        folder.mkdir(parents=True, exist_ok=True)
        return self.open_path(str(folder))

    def open_url(self, url: str) -> bool:
        if not str(url or "").startswith("https://"):
            return False
        webbrowser.open(url)
        return True

    def read_clipboard(self) -> str:
        try:
            return read_clipboard()
        except Exception:
            return ""

    def copy_text(self, text: str) -> bool:
        try:
            return write_clipboard(text)
        except Exception:
            return False

    # ---- settings -------------------------------------------------------------------------

    def save_settings(self, patch: dict) -> dict:
        result = self._settings.update(patch or {})
        if "theme" in (patch or {}):
            self._on_theme(result.get("theme") or "system")
        return result

    def gpu_status(self) -> dict:
        return gpu.status()

    def import_cookies(self) -> dict:
        chosen = self.pick_files("cookies")
        if not chosen:
            return {"ok": False, "cancelled": True, "cookies": self._cookies_view()}
        source = Path(chosen[0])
        if not tools.looks_like_cookies_file(source):
            return {"ok": False, "error": {"message": "Это не файл cookies.",
                                           "hint": "Нужен файл в формате Netscape (cookies.txt).", "kind": "input"},
                    "cookies": self._cookies_view()}
        shutil.copyfile(source, tools.user_cookies_file())
        return {"ok": True, "cookies": self._cookies_view()}

    def remove_cookies(self) -> dict:
        tools.user_cookies_file().unlink(missing_ok=True)
        return self._cookies_view()

    def update_tools_now(self) -> dict:
        try:
            self._tools_state = updater.update_tools(force=True)
        except Exception as exc:
            self._tools_state = {"error": str(exc)}
        return self._tools_view()

    def check_app_update(self) -> dict | None:
        try:
            update = updater.check_app_update()
        except Exception:
            return None
        self._settings.update({"app_update": update, "last_app_check": time.time()})
        return update
