from __future__ import annotations

import os
import queue
import subprocess
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from downloader import download_media
from platforms import detect_platform
from transcriber import LANGUAGES, MODEL_PROFILES, transcribe_media

APP_NAME = "RNGN Media"
APP_VERSION = "0.1.0"


def default_output_dir() -> Path:
    videos = Path.home() / "Videos"
    base = videos if videos.exists() else Path.home()
    return base / "RNGN Media"


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("920x720")
        self.root.minsize(820, 620)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False

        self.output_root = tk.StringVar(value=str(default_output_dir()))
        self.url = tk.StringVar()
        self.platform = tk.StringVar(value="Платформа определится автоматически")
        self.media_file = tk.StringVar()
        self.model_profile = tk.StringVar(value="Точная — large-v3")
        self.language = tk.StringVar(value="Авто")
        self.timestamps = tk.BooleanVar(value=False)
        self.make_srt = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Готов к работе")
        self.progress = tk.IntVar(value=0)

        self._build_ui()
        self.url.trace_add("write", self._on_url_changed)
        self.root.after(120, self._poll_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="RNGN Media", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Скачивание медиа + транскрибация в одной программе",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(0, 14))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        self._build_download_tab(notebook)
        self._build_transcribe_tab(notebook)

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Label(footer, textvariable=self.status).pack(side="left")
        ttk.Progressbar(footer, variable=self.progress, maximum=100, length=260).pack(side="right")

    def _build_download_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=18)
        notebook.add(frame, text="Скачать медиа")

        ttk.Label(frame, text="Ссылка").pack(anchor="w")
        ttk.Entry(frame, textvariable=self.url).pack(fill="x", pady=(4, 4))
        ttk.Label(frame, textvariable=self.platform).pack(anchor="w", pady=(0, 14))

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text="Куда сохранять").pack(side="left")
        ttk.Button(row, text="Выбрать папку", command=self._choose_output).pack(side="right")
        ttk.Entry(frame, textvariable=self.output_root).pack(fill="x", pady=(4, 14))

        self.download_button = ttk.Button(frame, text="Скачать", command=self._start_download)
        self.download_button.pack(anchor="w")

        ttk.Label(
            frame,
            text=(
                "Платформу выбирать не нужно. Ссылка определяется автоматически: "
                "YouTube / VK / TikTok / Instagram / X. Видео приводится к MP4 H.264 + AAC для Premiere."
            ),
            wraplength=800,
        ).pack(anchor="w", pady=(14, 10))

        self.download_log = tk.Text(frame, height=17, wrap="word")
        self.download_log.pack(fill="both", expand=True)
        self.download_log.configure(state="disabled")

    def _build_transcribe_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=18)
        notebook.add(frame, text="Транскрибировать")

        file_row = ttk.Frame(frame)
        file_row.pack(fill="x")
        ttk.Label(file_row, text="Аудио или видео").pack(side="left")
        ttk.Button(file_row, text="Выбрать файл", command=self._choose_media).pack(side="right")
        ttk.Entry(frame, textvariable=self.media_file).pack(fill="x", pady=(4, 14))

        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        left = ttk.Frame(controls)
        left.pack(side="left", fill="x", expand=True, padx=(0, 8))
        right = ttk.Frame(controls)
        right.pack(side="left", fill="x", expand=True, padx=(8, 0))

        ttk.Label(left, text="Модель").pack(anchor="w")
        ttk.Combobox(left, textvariable=self.model_profile, values=list(MODEL_PROFILES), state="readonly").pack(fill="x")
        ttk.Label(right, text="Язык").pack(anchor="w")
        ttk.Combobox(right, textvariable=self.language, values=list(LANGUAGES), state="readonly").pack(fill="x")

        options = ttk.Frame(frame)
        options.pack(fill="x", pady=14)
        ttk.Checkbutton(options, text="Сделать SRT", variable=self.make_srt).pack(side="left")
        ttk.Checkbutton(options, text="Таймкоды в TXT", variable=self.timestamps).pack(side="left", padx=18)

        self.transcribe_button = ttk.Button(frame, text="Транскрибировать", command=self._start_transcribe)
        self.transcribe_button.pack(anchor="w")

        ttk.Label(
            frame,
            text="Модель скачивается один раз. При доступной NVIDIA программа пробует GPU и автоматически откатывается на CPU при проблемах CUDA.",
            wraplength=800,
        ).pack(anchor="w", pady=(14, 10))

        self.transcribe_log = tk.Text(frame, height=17, wrap="word")
        self.transcribe_log.pack(fill="both", expand=True)
        self.transcribe_log.configure(state="disabled")

    def _on_url_changed(self, *_args) -> None:
        value = self.url.get().strip()
        self.platform.set(
            f"Определено автоматически: {detect_platform(value)}" if value else "Платформа определится автоматически"
        )

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_root.get() or str(default_output_dir()))
        if selected:
            self.output_root.set(selected)

    def _choose_media(self) -> None:
        selected = filedialog.askopenfilename(title="Выбери аудио или видео")
        if selected:
            self.media_file.set(selected)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.download_button.configure(state=state)
        self.transcribe_button.configure(state=state)
        if not busy:
            self.progress.set(0)

    def _post(self, kind: str, payload: object) -> None:
        self.events.put((kind, payload))

    def _start_download(self) -> None:
        if self.busy:
            return
        url = self.url.get().strip()
        if not url:
            messagebox.showerror(APP_NAME, "Вставь ссылку.")
            return
        out = Path(self.output_root.get()).expanduser()
        self._set_busy(True)
        self.status.set("Запускаю скачивание...")
        threading.Thread(target=self._download_worker, args=(url, out), daemon=True).start()

    def _download_worker(self, url: str, out: Path) -> None:
        try:
            outputs = download_media(
                url,
                out,
                status=lambda s: self._post("status", s),
                progress=lambda p: self._post("progress", p),
                log=lambda s: self._post("download_log", s),
            )
            self._post("done", ("Скачивание завершено", outputs))
        except Exception as exc:
            self._post("error", f"{exc}\n\n{traceback.format_exc()}")

    def _start_transcribe(self) -> None:
        if self.busy:
            return
        media = Path(self.media_file.get()).expanduser()
        if not media.is_file():
            messagebox.showerror(APP_NAME, "Выбери существующий аудио- или видеофайл.")
            return
        out = Path(self.output_root.get()).expanduser() / "Transcripts"
        self._set_busy(True)
        self.status.set("Запускаю транскрибацию...")
        threading.Thread(target=self._transcribe_worker, args=(media, out), daemon=True).start()

    def _transcribe_worker(self, media: Path, out: Path) -> None:
        try:
            outputs = transcribe_media(
                media,
                out,
                profile_name=self.model_profile.get(),
                language_name=self.language.get(),
                with_timestamps=self.timestamps.get(),
                make_srt=self.make_srt.get(),
                status=lambda s: self._post("status", s),
                progress=lambda p: self._post("progress", p),
                log=lambda s: self._post("transcribe_log", s),
            )
            self._post("done", ("Транскрибация завершена", outputs))
        except Exception as exc:
            self._post("error", f"{exc}\n\n{traceback.format_exc()}")

    def _append_log(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.insert("end", text + "\n")
        widget.see("end")
        widget.configure(state="disabled")

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self.status.set(str(payload))
                elif kind == "progress":
                    self.progress.set(int(payload))
                elif kind == "download_log":
                    self._append_log(self.download_log, str(payload))
                elif kind == "transcribe_log":
                    self._append_log(self.transcribe_log, str(payload))
                elif kind == "done":
                    title, outputs = payload  # type: ignore[misc]
                    self.progress.set(100)
                    self.status.set(str(title))
                    self._set_busy(False)
                    paths = "\n".join(str(p) for p in outputs)
                    messagebox.showinfo(APP_NAME, f"{title}\n\n{paths}")
                elif kind == "error":
                    self._set_busy(False)
                    self.status.set("Ошибка")
                    messagebox.showerror(APP_NAME, str(payload))
        except queue.Empty:
            pass
        self.root.after(120, self._poll_events)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
