from __future__ import annotations

import logging
import queue
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import desktop_app
import desktop_v8
import desktop_v11  # noqa: F401  # premium UI + multilingual + audio-only SRT
import video_converter

APP_VERSION = "1.7.0"
desktop_app.APP_NAME = f"ZNAMBO Transcriber v{APP_VERSION}"

_base_build_ui = desktop_app.DesktopApp._build_ui
_base_set_busy = desktop_app.DesktopApp._set_busy
_base_poll_events = desktop_app.DesktopApp._poll_events


def build_ui_v17(self) -> None:
    _base_build_ui(self)

    parent = self.start_button.master
    self.convert_button = tk.Button(
        parent,
        text="◫   Конвертировать видео",
        command=self._open_converter,
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
        highlightbackground="#355F9D",
        highlightcolor="#355F9D",
    )
    self.convert_button.pack(fill="x", pady=(8, 0))
    desktop_v8._hover(self.convert_button, desktop_v8.PANEL_2, "#1A2440")


def set_busy_v17(self, busy: bool) -> None:
    _base_set_busy(self, busy)
    if hasattr(self, "convert_button"):
        self.convert_button.configure(state="disabled" if busy else "normal")


def open_converter(self) -> None:
    media_path = Path(self.selected_file.get().strip().strip('"'))
    if not media_path.is_file():
        messagebox.showerror(
            desktop_app.APP_NAME,
            "Сначала выбери или перетащи видеофайл.",
        )
        return
    if media_path.suffix.lower() not in video_converter.VIDEO_EXTENSIONS:
        messagebox.showerror(
            desktop_app.APP_NAME,
            "Для конвертации нужен видеофайл: MOV, MP4, MKV, AVI, MTS, WebM и т. п.",
        )
        return

    dialog = tk.Toplevel(self.root)
    dialog.title("Конвертация видео")
    dialog.configure(bg=desktop_v8.BG)
    dialog.geometry("650x360")
    dialog.resizable(False, False)
    dialog.transient(self.root)
    dialog.grab_set()

    frame = tk.Frame(dialog, bg=desktop_v8.PANEL, padx=28, pady=24)
    frame.pack(fill="both", expand=True, padx=14, pady=14)

    tk.Label(
        frame,
        text="Конвертация видео",
        bg=desktop_v8.PANEL,
        fg=desktop_v8.TEXT,
        font=("Segoe UI", 20, "bold"),
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        frame,
        text=media_path.name,
        bg=desktop_v8.PANEL,
        fg=desktop_v8.TEXT_2,
        font=("Segoe UI", 9),
        anchor="w",
    ).pack(fill="x", pady=(3, 18))

    tk.Label(
        frame,
        text="Профиль",
        bg=desktop_v8.PANEL,
        fg=desktop_v8.TEXT_2,
        font=("Segoe UI", 10),
        anchor="w",
    ).pack(fill="x")

    profile_var = tk.StringVar(value="MP4 для Premiere — максимальное качество")
    combo = ttk.Combobox(
        frame,
        textvariable=profile_var,
        values=list(video_converter.CONVERSION_PROFILES),
        state="readonly",
        style="Premium.TCombobox",
        font=("Segoe UI", 10),
    )
    combo.pack(fill="x", pady=(7, 10))

    description = tk.StringVar()
    def refresh_description(*_args) -> None:
        profile = video_converter.CONVERSION_PROFILES.get(profile_var.get(), {})
        description.set(str(profile.get("description", "")))

    profile_var.trace_add("write", refresh_description)
    refresh_description()

    tk.Label(
        frame,
        textvariable=description,
        bg=desktop_v8.PANEL,
        fg=desktop_v8.TEXT_3,
        font=("Segoe UI", 9),
        justify="left",
        anchor="w",
        wraplength=570,
    ).pack(fill="x", pady=(0, 16))

    warning = (
        "1:1 = настоящий remux без перекодирования. Если исходный кодек нельзя положить "
        "в выбранный контейнер, FFmpeg остановится — тогда выбери профиль Premiere/ProRes. "
        "При перекодировании разрешение и FPS не меняются, все аудиодорожки сохраняются."
    )
    tk.Label(
        frame,
        text=warning,
        bg=desktop_v8.PANEL_3,
        fg=desktop_v8.TEXT_2,
        font=("Segoe UI", 9),
        justify="left",
        anchor="w",
        wraplength=570,
        padx=14,
        pady=11,
    ).pack(fill="x", pady=(0, 18))

    buttons = tk.Frame(frame, bg=desktop_v8.PANEL)
    buttons.pack(fill="x")

    def start() -> None:
        chosen = profile_var.get()
        dialog.grab_release()
        dialog.destroy()
        self._start_conversion(media_path, chosen)

    cancel = tk.Button(
        buttons,
        text="Отмена",
        command=dialog.destroy,
        bg=desktop_v8.PANEL_2,
        fg=desktop_v8.TEXT_2,
        activebackground="#1A2440",
        activeforeground=desktop_v8.TEXT,
        bd=0,
        padx=20,
        pady=10,
        cursor="hand2",
    )
    cancel.pack(side="right")

    go = tk.Button(
        buttons,
        text="Конвертировать",
        command=start,
        bg=desktop_v8.BLUE,
        fg="white",
        activebackground="#4B89FF",
        activeforeground="white",
        bd=0,
        padx=24,
        pady=10,
        font=("Segoe UI", 10, "bold"),
        cursor="hand2",
    )
    go.pack(side="right", padx=(0, 10))


def start_conversion(self, media_path: Path, profile_name: str) -> None:
    self._set_busy(True)
    self.open_file_button.configure(state="disabled")
    self.progress["value"] = 0
    self.last_output = None
    self.status.set("Подготовка видеоконвертации…")

    threading.Thread(
        target=self._conversion_worker,
        args=(media_path, profile_name),
        daemon=True,
    ).start()


def conversion_worker(self, media_path: Path, profile_name: str) -> None:
    try:
        output_path = video_converter.convert_video(
            media_path,
            profile_name,
            progress_callback=lambda value: self.events.put(("progress", value)),
            status_callback=lambda text: self.events.put(("status", text)),
        )
        self.events.put(("conversion_done", (output_path, profile_name)))
    except Exception as exc:
        logging.error("Fatal video conversion error\n%s", traceback.format_exc())
        self.events.put(("conversion_error", str(exc)))


def poll_events_v17(self) -> None:
    passthrough: list[tuple[str, object]] = []
    try:
        while True:
            kind, payload = self.events.get_nowait()
            if kind == "conversion_done":
                output_path, profile_name = payload  # type: ignore[misc]
                self.last_output = Path(output_path)
                self.progress["value"] = 100
                self.status.set(f"Видео готово: {self.last_output.name}")
                self.device.set(str(profile_name))
                self._set_busy(False)
                self.open_file_button.configure(state="normal")
                messagebox.showinfo(
                    desktop_app.APP_NAME,
                    "Конвертация завершена.\n\n"
                    "Файл сохранён в Downloads.\n\n"
                    f"{self.last_output}",
                )
            elif kind == "conversion_error":
                self.status.set("Ошибка конвертации видео")
                self._set_busy(False)
                self.device.set(self._device_summary())
                messagebox.showerror(
                    desktop_app.APP_NAME,
                    "Не удалось конвертировать видео:\n\n"
                    f"{payload}\n\n"
                    "Если это был режим 1:1, вероятнее всего исходный кодек несовместим "
                    "с выбранным контейнером. Выбери профиль «MP4 для Premiere».\n\n"
                    f"Лог: {desktop_app.LOG_DIR / 'desktop.log'}",
                )
            else:
                passthrough.append((kind, payload))
    except queue.Empty:
        pass

    for item in passthrough:
        self.events.put(item)
    _base_poll_events(self)


desktop_app.DesktopApp._build_ui = build_ui_v17
desktop_app.DesktopApp._set_busy = set_busy_v17
desktop_app.DesktopApp._open_converter = open_converter
desktop_app.DesktopApp._start_conversion = start_conversion
desktop_app.DesktopApp._conversion_worker = conversion_worker
desktop_app.DesktopApp._poll_events = poll_events_v17


if __name__ == "__main__":
    logging.info("Starting ZNAMBO Transcriber v%s with audio-only SRT and video conversion", APP_VERSION)
    desktop_app.DesktopApp().run()
