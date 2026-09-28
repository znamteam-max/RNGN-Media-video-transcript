from __future__ import annotations

import logging
import queue
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

import desktop_app
import desktop_v8
import desktop_v9  # noqa: F401  # premium UI + multilingual transcription
import subtitle_audio_engine

APP_VERSION = "1.6.0"
desktop_app.APP_NAME = f"ZNAMBO Transcriber v{APP_VERSION}"

_base_build_ui = desktop_app.DesktopApp._build_ui
_base_set_busy = desktop_app.DesktopApp._set_busy
_base_poll_events = desktop_app.DesktopApp._poll_events


def build_ui_v16(self) -> None:
    _base_build_ui(self)

    parent = self.start_button.master
    self.subtitle_button = tk.Button(
        parent,
        text="▤   Создать точные субтитры SRT",
        command=self._start_subtitles,
        bg=desktop_v8.PANEL_2,
        fg=desktop_v8.TEXT,
        activebackground="#1A2440",
        activeforeground=desktop_v8.TEXT,
        disabledforeground="#586477",
        bd=0,
        relief="flat",
        padx=18,
        pady=12,
        font=("Segoe UI", 10, "bold"),
        cursor="hand2",
        highlightthickness=1,
        highlightbackground="#6245C5",
        highlightcolor="#6245C5",
    )
    self.subtitle_button.pack(fill="x", pady=(8, 0))
    desktop_v8._hover(self.subtitle_button, desktop_v8.PANEL_2, "#1A2440")

    try:
        self.open_file_button.configure(text="▤   Открыть результат\n      TXT / SRT")
    except Exception:
        pass


def set_busy_v16(self, busy: bool) -> None:
    _base_set_busy(self, busy)
    if hasattr(self, "subtitle_button"):
        self.subtitle_button.configure(state="disabled" if busy else "normal")


def start_subtitles(self) -> None:
    media_path = Path(self.selected_file.get().strip().strip('"'))
    if not media_path.is_file():
        messagebox.showerror(
            desktop_app.APP_NAME,
            "Сначала выбери или перетащи исходный аудио- или видеофайл.",
        )
        return
    if media_path.suffix.lower() not in desktop_app.SUPPORTED_EXTENSIONS:
        messagebox.showerror(
            desktop_app.APP_NAME,
            f"Формат {media_path.suffix or '(без расширения)'} не поддерживается.",
        )
        return

    self._set_busy(True)
    self.open_file_button.configure(state="disabled")
    self.progress["value"] = 0
    self.last_output = None
    self.status.set("Анализ речи и точных границ слов…")

    profile = dict(desktop_app.MODEL_PROFILES[self.profile.get()])
    language = desktop_app.LANGUAGES[self.language.get()]

    threading.Thread(
        target=self._subtitle_worker,
        args=(media_path, profile, language),
        daemon=True,
    ).start()


def subtitle_worker(
    self,
    media_path: Path,
    profile: dict[str, object],
    language: str | None,
) -> None:
    try:
        output_path, device_name = subtitle_audio_engine.generate_audio_srt(
            self.engine,
            media_path,
            profile,
            language,
            progress_callback=lambda value: self.events.put(("progress", value)),
            status_callback=lambda text: self.events.put(("status", text)),
        )
        self.events.put(("subtitle_done", (output_path, device_name)))
    except Exception as exc:
        logging.error("Fatal audio-only subtitle error\n%s", traceback.format_exc())
        self.events.put(("subtitle_error", str(exc)))


def poll_events_v16(self) -> None:
    passthrough: list[tuple[str, object]] = []
    try:
        while True:
            kind, payload = self.events.get_nowait()
            if kind == "subtitle_done":
                output_path, device_name = payload  # type: ignore[misc]
                self.last_output = Path(output_path)
                self.progress["value"] = 100
                self.status.set(f"SRT готов: {self.last_output.name}")
                self.device.set(f"Word-level тайминги построены на {device_name}")
                self._set_busy(False)
                self.open_file_button.configure(state="normal")
                messagebox.showinfo(
                    desktop_app.APP_NAME,
                    "Субтитры готовы.\n\n"
                    "Текст и тайминги получены только из аудиодорожки.\n"
                    "Формат времени: HH:MM:SS,mmm.\n\n"
                    f"{self.last_output}",
                )
            elif kind == "subtitle_error":
                self.status.set("Ошибка создания субтитров")
                self._set_busy(False)
                self.device.set(self._device_summary())
                messagebox.showerror(
                    desktop_app.APP_NAME,
                    "Не удалось создать субтитры:\n\n"
                    f"{payload}\n\nЛог: {desktop_app.LOG_DIR / 'desktop.log'}",
                )
            else:
                passthrough.append((kind, payload))
    except queue.Empty:
        pass

    for item in passthrough:
        self.events.put(item)
    _base_poll_events(self)


desktop_app.DesktopApp._build_ui = build_ui_v16
desktop_app.DesktopApp._set_busy = set_busy_v16
desktop_app.DesktopApp._start_subtitles = start_subtitles
desktop_app.DesktopApp._subtitle_worker = subtitle_worker
desktop_app.DesktopApp._poll_events = poll_events_v16


if __name__ == "__main__":
    logging.info("Starting ZNAMBO Transcriber v%s audio-only SRT", APP_VERSION)
    desktop_app.DesktopApp().run()
