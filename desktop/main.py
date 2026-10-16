"""RNGN Media desktop entry point: a native window with the HTML interface from ui/."""
from __future__ import annotations

import os
import sys


def system_prefers_dark() -> bool:
    if os.name == "nt":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return value == 0
        except OSError:
            return False
    if sys.platform == "darwin":
        import subprocess

        result = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True)
        return "Dark" in (result.stdout or "")
    return False


def set_dark_titlebar(window, dark: bool) -> None:
    """Windows 11 title bar follows the app theme, not only the system one."""
    if os.name != "nt":
        return
    try:
        import ctypes

        hwnd = int(window.native.Handle.ToInt64())
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def main() -> None:
    import webview
    from webview.dom import DOMEventHandler

    from rngn import APP_NAME, paths
    from rngn.api import Api

    api = Api()
    size = api._settings.get("window") or {}
    theme = api._settings.get("theme") or "system"
    dark = theme == "dark" or (theme == "system" and system_prefers_dark())

    window = webview.create_window(
        APP_NAME,
        url=str(paths.ui_dir() / "index.html"),
        js_api=api,
        width=int(size.get("width") or 1200),
        height=int(size.get("height") or 820),
        min_size=(980, 660),
        background_color="#0E1014" if dark else "#F4F5F7",
        text_select=True,
    )
    api._attach(window)
    api._on_theme = lambda value: set_dark_titlebar(
        window, value == "dark" or (value == "system" and system_prefers_dark())
    )

    def on_closing():
        if api._jobs.active_count():
            if not window.create_confirmation_dialog(
                APP_NAME, "Задания ещё выполняются. Закрыть программу и остановить их?"
            ):
                return False
        try:
            api._settings.update({"window": {"width": int(window.width), "height": int(window.height)}})
        except Exception:
            pass
        return True

    def on_drop(event: dict) -> None:
        files = [
            item.get("pywebviewFullPath")
            for item in (event.get("dataTransfer") or {}).get("files") or []
            if item.get("pywebviewFullPath")
        ]
        if files:
            api._emit({"type": "files_dropped", "files": api.describe_files(files)})

    def on_loaded() -> None:
        api._on_theme(api._settings.get("theme") or "system")
        window.dom.document.events.dragover += DOMEventHandler(lambda _e: None, True, False, debounce=500)
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, False)

    window.events.closing += on_closing
    window.events.loaded += on_loaded

    debug_port = os.environ.get("RNGN_DEBUG_PORT")  # developer checks over DevTools, never in normal runs
    if debug_port and debug_port.isdigit():
        webview.settings["REMOTE_DEBUGGING_PORT"] = int(debug_port)

    storage = paths.data_dir() / "webview"
    icon = paths.assets_dir() / "rngn-media.ico"
    webview.start(
        debug=bool(os.environ.get("RNGN_DEBUG")),
        icon=str(icon) if icon.is_file() else None,
        private_mode=False,
        storage_path=str(storage),
    )
    api._shutdown()


if __name__ == "__main__":
    main()
