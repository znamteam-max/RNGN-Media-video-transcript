from __future__ import annotations

import logging
import queue
import threading
import traceback
from pathlib import Path
from threading import Event
import tkinter as tk
from tkinter import messagebox, ttk

import desktop_app
import desktop_v8
import desktop_v12  # noqa: F401
from media_downloader import (
    MediaDownloadCancelled,
    MediaDownloader,
    detect_platform,
    open_download_folder,
)

APP_VERSION = "0.1.0"
desktop_app.APP_NAME = f"RNGN Media Studio v{APP_VERSION}"

_base_build_ui = desktop_app.DesktopApp._build_ui
_base_set_busy = desktop_app.DesktopApp._set_busy
_base_poll_events = desktop_app.DesktopApp._poll_events

MODE_LABELS = {
    "Видео для Premiere — MP4 H.264 + AAC": "premiere",
    "Видео — как отдаёт платформа": "original",
    "Только оригинальный звук — WAV": "audio",
}


def _safe_downloader() -> MediaDownloader:
    return MediaDownloader()


def build_ui_unified(self) -> None:
    _base_build_ui(self)
    self.root.title(desktop_app.APP_NAME)
    self.root.geometry("940x920")
    self.root.minsize(820, 760)

    self.download_events: queue.Queue[tuple[str, object]] = queue.Queue()
    self.download_cancel = Event()
    self.download_busy = False
    self.download_analysis_after = None
    self.download_last_platform = "Другой источник"

    parent = self.start_button.master
    shell = tk.Frame(parent, bg=desktop_v8.BORDER, bd=0, highlightthickness=0)
    shell.pack(fill="x", pady=(14, 0))
    panel = tk.Frame(shell, bg=desktop_v8.PANEL, padx=16, pady=15)
    panel.pack(fill="x", padx=1, pady=1)

    tk.Label(
        panel, text="Скачать медиа",
        bg=desktop_v8.PANEL, fg=desktop_v8.TEXT,
        font=("Segoe UI", 13, "bold"), anchor="w",
    ).pack(fill="x")
    tk.Label(
        panel,
        text=(
            "Вставь ссылку — YouTube / VK / TikTok / Instagram / X определятся "
            "автоматически. Доступные качества появятся сами."
        ),
        bg=desktop_v8.PANEL, fg=desktop_v8.TEXT_2,
        font=("Segoe UI", 9), anchor="w", justify="left", wraplength=760,
    ).pack(fill="x", pady=(3, 10))

    self.download_url = tk.StringVar()
    self.download_url_entry = tk.Entry(
        panel, textvariable=self.download_url,
        bg=desktop_v8.PANEL_3, fg=desktop_v8.TEXT,
        insertbackground=desktop_v8.TEXT, relief="flat", bd=0,
        font=("Segoe UI", 10), highlightthickness=1,
        highlightbackground=desktop_v8.BORDER, highlightcolor=desktop_v8.BLUE,
    )
    self.download_url_entry.pack(fill="x", ipady=9)

    self.download_platform = tk.StringVar(value="Вставь ссылку")
    tk.Label(
        panel, textvariable=self.download_platform,
        bg=desktop_v8.PANEL, fg=desktop_v8.TEXT_3,
        font=("Segoe UI", 9), anchor="w",
    ).pack(fill="x", pady=(6, 10))

    options = tk.Frame(panel, bg=desktop_v8.PANEL)
    options.pack(fill="x")

    left = tk.Frame(options, bg=desktop_v8.PANEL)
    left.pack(side="left", fill="x", expand=True, padx=(0, 6))
    tk.Label(
        left, text="Качество", bg=desktop_v8.PANEL,
        fg=desktop_v8.TEXT_2, font=("Segoe UI", 9), anchor="w",
    ).pack(fill="x")
    self.download_quality = tk.StringVar(value="Лучшее доступное")
    self.download_quality_combo = ttk.Combobox(
        left, textvariable=self.download_quality,
        values=["Лучшее доступное"], state="readonly",
        style="Premium.TCombobox", font=("Segoe UI", 9),
    )
    self.download_quality_combo.pack(fill="x", pady=(5, 0))

    right = tk.Frame(options, bg=desktop_v8.PANEL)
    right.pack(side="left", fill="x", expand=True, padx=(6, 0))
    tk.Label(
        right, text="Что получить", bg=desktop_v8.PANEL,
        fg=desktop_v8.TEXT_2, font=("Segoe UI", 9), anchor="w",
    ).pack(fill="x")
    self.download_mode = tk.StringVar(value=next(iter(MODE_LABELS)))
    self.download_mode_combo = ttk.Combobox(
        right, textvariable=self.download_mode,
        values=list(MODE_LABELS), state="readonly",
        style="Premium.TCombobox", font=("Segoe UI", 9),
    )
    self.download_mode_combo.pack(fill="x", pady=(5, 0))

    self.download_status = tk.StringVar(value="Готово к ссылке")
    tk.Label(
        panel, textvariable=self.download_status,
        bg=desktop_v8.PANEL, fg=desktop_v8.TEXT_2,
        font=("Segoe UI", 9), anchor="w",
    ).pack(fill="x", pady=(11, 5))

    self.download_progress = ttk.Progressbar(panel, maximum=100, mode="determinate")
    self.download_progress.pack(fill="x")

    actions = tk.Frame(panel, bg=desktop_v8.PANEL)
    actions.pack(fill="x", pady=(10, 0))

    self.download_button = tk.Button(
        actions, text="Скачать", command=self._toggle_media_download,
        bg=desktop_v8.BLUE, fg="white", activebackground="#4B89FF",
        activeforeground="white", bd=0, padx=22, pady=9,
        font=("Segoe UI", 10, "bold"), cursor="hand2",
    )
    self.download_button.pack(side="left")
    desktop_v8._hover(self.download_button, desktop_v8.BLUE, "#4B89FF")

    self.download_refresh_button = tk.Button(
        actions, text="Обновить варианты", command=self._start_media_analysis,
        bg=desktop_v8.PANEL_2, fg=desktop_v8.TEXT_2,
        activebackground="#1A2440", activeforeground=desktop_v8.TEXT,
        bd=0, padx=14, pady=9, cursor="hand2",
    )
    self.download_refresh_button.pack(side="left", padx=(8, 0))
    desktop_v8._hover(self.download_refresh_button, desktop_v8.PANEL_2, "#1A2440")

    self.download_folder_button = tk.Button(
        actions, text="Папка загрузок",
        command=lambda: open_download_folder(self.download_last_platform),
        bg=desktop_v8.PANEL_2, fg=desktop_v8.TEXT_2,
        activebackground="#1A2440", activeforeground=desktop_v8.TEXT,
        bd=0, padx=14, pady=9, cursor="hand2",
    )
    self.download_folder_button.pack(side="left", padx=(8, 0))
    desktop_v8._hover(self.download_folder_button, desktop_v8.PANEL_2, "#1A2440")

    self.download_url.trace_add("write", lambda *_: self._schedule_media_analysis())


def set_busy_unified(self, busy: bool) -> None:
    _base_set_busy(self, busy)
    if hasattr(self, "download_button") and self.download_busy:
        self.download_button.configure(state="normal")
    elif hasattr(self, "download_button"):
        self.download_button.configure(state="disabled" if busy else "normal")
    if hasattr(self, "download_refresh_button"):
        self.download_refresh_button.configure(state="disabled" if busy else "normal")


def schedule_media_analysis(self) -> None:
    url = self.download_url.get().strip()
    platform = detect_platform(url)
    self.download_last_platform = platform
    self.download_platform.set(
        f"{platform} · определено автоматически" if url else "Вставь ссылку"
    )
    if not url:
        return

    if self.download_analysis_after is not None:
        try:
            self.root.after_cancel(self.download_analysis_after)
        except Exception:
            pass
    if url.startswith(("http://", "https://")) and len(url) >= 14:
        self.download_analysis_after = self.root.after(
            700, self._start_media_analysis
        )


def start_media_analysis(self) -> None:
    url = self.download_url.get().strip()
    if not url.startswith(("http://", "https://")):
        return
    self.download_analysis_after = None
    self.download_status.set("Анализирую ссылку…")
    self.download_refresh_button.configure(state="disabled")
    threading.Thread(
        target=self._media_analysis_worker, args=(url,), daemon=True
    ).start()


def media_analysis_worker(self, url: str) -> None:
    try:
        info = _safe_downloader().analyze(url)
        self.download_events.put(("media_analysis_done", info))
    except Exception as exc:
        logging.error("Media analysis error\n%s", traceback.format_exc())
        self.download_events.put(("media_analysis_error", str(exc)))


def toggle_media_download(self) -> None:
    if self.download_busy:
        self.download_cancel.set()
        self.download_status.set("Отменяю…")
        return

    url = self.download_url.get().strip()
    if not url.startswith(("http://", "https://")):
        messagebox.showerror(desktop_app.APP_NAME, "Вставь ссылку на видео.")
        return

    quality_text = self.download_quality.get()
    quality = None
    if quality_text.endswith("p"):
        try:
            quality = int(quality_text[:-1])
        except ValueError:
            quality = None

    mode = MODE_LABELS.get(self.download_mode.get(), "premiere")
    self.download_cancel.clear()
    self.download_busy = True
    self.download_progress["value"] = 0
    self.download_status.set("Подготовка…")
    self.download_button.configure(text="Отменить")
    self.download_refresh_button.configure(state="disabled")
    self.start_button.configure(state="disabled")
    if hasattr(self, "subtitle_button"):
        self.subtitle_button.configure(state="disabled")
    if hasattr(self, "convert_button"):
        self.convert_button.configure(state="disabled")

    threading.Thread(
        target=self._media_download_worker,
        args=(url, quality, mode),
        daemon=True,
    ).start()


def media_download_worker(self, url: str, quality: int | None, mode: str) -> None:
    try:
        files = _safe_downloader().download(
            url, quality, mode,
            progress_callback=lambda value: self.download_events.put(
                ("media_download_progress", value)
            ),
            status_callback=lambda text: self.download_events.put(
                ("media_download_status", text)
            ),
            cancel_event=self.download_cancel,
        )
        self.download_events.put(("media_download_done", files))
    except MediaDownloadCancelled as exc:
        self.download_events.put(("media_download_cancelled", str(exc)))
    except Exception as exc:
        logging.error("Media download error\n%s", traceback.format_exc())
        self.download_events.put(("media_download_error", str(exc)))


def finish_download_busy(self) -> None:
    self.download_busy = False
    self.download_button.configure(text="Скачать", state="normal")
    self.download_refresh_button.configure(state="normal")
    self.start_button.configure(state="normal")
    if hasattr(self, "subtitle_button"):
        self.subtitle_button.configure(state="normal")
    if hasattr(self, "convert_button"):
        self.convert_button.configure(state="normal")


def poll_events_unified(self) -> None:
    if hasattr(self, "download_events"):
        try:
            while True:
                kind, payload = self.download_events.get_nowait()
                if kind == "media_analysis_done":
                    info = payload
                    self.download_last_platform = info.platform
                    details = [info.platform, info.title]
                    if info.item_count > 1:
                        details.append(f"{info.item_count} файлов")
                    self.download_platform.set(" · ".join(details))
                    values = ["Лучшее доступное"] + [
                        f"{height}p" for height in info.qualities
                    ]
                    self.download_quality_combo.configure(values=values)
                    self.download_quality.set(values[0])
                    self.download_status.set("Варианты готовы")
                    self.download_refresh_button.configure(state="normal")
                elif kind == "media_analysis_error":
                    self.download_status.set(
                        "Не удалось получить варианты. Скачать всё равно можно."
                    )
                    self.download_refresh_button.configure(state="normal")
                elif kind == "media_download_progress":
                    self.download_progress["value"] = int(payload)
                elif kind == "media_download_status":
                    self.download_status.set(str(payload))
                elif kind == "media_download_done":
                    files = [Path(item) for item in payload]
                    self.download_progress["value"] = 100
                    self.download_status.set(f"Готово · {len(files)} файл(а/ов)")
                    self._finish_download_busy()
                    names = "\n".join(path.name for path in files[:8])
                    messagebox.showinfo(
                        desktop_app.APP_NAME,
                        "Скачивание завершено.\n\n"
                        f"{names}\n\n"
                        "Файлы лежат в Videos\\RNGN Media Studio.",
                    )
                elif kind == "media_download_cancelled":
                    self.download_status.set("Отменено")
                    self._finish_download_busy()
                elif kind == "media_download_error":
                    self.download_status.set("Ошибка скачивания")
                    self._finish_download_busy()
                    messagebox.showerror(
                        desktop_app.APP_NAME,
                        "Не удалось скачать медиа:\n\n"
                        f"{payload}\n\n"
                        "Если платформа требует вход, положи cookies.txt в:\n"
                        "%LOCALAPPDATA%\\RNGN Media Studio\\cookies.txt",
                    )
        except queue.Empty:
            pass
    _base_poll_events(self)


desktop_app.DesktopApp._build_ui = build_ui_unified
desktop_app.DesktopApp._set_busy = set_busy_unified
desktop_app.DesktopApp._schedule_media_analysis = schedule_media_analysis
desktop_app.DesktopApp._start_media_analysis = start_media_analysis
desktop_app.DesktopApp._media_analysis_worker = media_analysis_worker
desktop_app.DesktopApp._toggle_media_download = toggle_media_download
desktop_app.DesktopApp._media_download_worker = media_download_worker
desktop_app.DesktopApp._finish_download_busy = finish_download_busy
desktop_app.DesktopApp._poll_events = poll_events_unified


if __name__ == "__main__":
    logging.info("Starting RNGN Media Studio v%s", APP_VERSION)
    desktop_app.DesktopApp().run()
