from __future__ import annotations

import os
import subprocess
import sys
import queue
import re
import threading
import time
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from downloader import MediaAnalysis, analyze_media, download_media, validate_clip_range
from platforms import detect_platform, platform_folder
from transcriber import LANGUAGES, MODEL_PROFILES, transcribe_media
from youtube_subtitles import (
    SubtitleInfo,
    SubtitleTrack,
    analyze_youtube_subtitles,
    download_youtube_subtitle,
)

APP_NAME = "RNGN Media"
APP_VERSION = "0.3.5"

BG = "#F3F5F8"
CARD = "#FFFFFF"
TEXT = "#18212F"
MUTED = "#697386"
BORDER = "#D9E0E8"
ACCENT = "#FF6B2C"
ACCENT_DARK = "#E5571C"
DARK = "#111827"
LOG_FG = "#D7DEE8"
SUCCESS = "#17834A"
UI_FONT = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"
MONO_FONT = "Menlo" if sys.platform == "darwin" else "Consolas"


def default_output_dir() -> Path:
    videos = Path.home() / "Videos"
    base = videos if videos.exists() else Path.home()
    return base / "RNGN Media"


def clean_pasted_url(value: str) -> str:
    text = (value or "").strip()
    match = re.search(r"https?://[^\s<>\"']+", text)
    if match:
        text = match.group(0)
    return text.rstrip(".,;)]}>")


def is_paste_shortcut(keycode: int, keysym: str) -> bool:
    key = (keysym or "").lower()
    return keycode == 86 or key in {"v", "cyrillic_em", "м"}


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("1040x820")
        self.root.minsize(920, 720)
        self.root.configure(bg=BG)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.quality_analyzing = False
        self.quality_started_at = 0.0
        self.subtitle_analyzing = False
        self.quality_after_id: str | None = None
        self.subtitle_after_id: str | None = None

        self.output_root = tk.StringVar(value=str(default_output_dir()))
        self.download_output = tk.StringVar()
        self.transcript_output = tk.StringVar()
        self.subtitle_output = tk.StringVar()

        self.url = tk.StringVar()
        self.platform = tk.StringVar(value="Вставь ссылку — платформа определится автоматически")
        self.quality = tk.StringVar(value="")
        self.quality_status = tk.StringVar(value="После вставки ссылки покажу только реально доступные варианты.")
        self.quality_values: list[str] = []
        self.clip_start = tk.StringVar()
        self.clip_end = tk.StringVar()
        self.clip_status = tk.StringVar(
            value="Для YouTube и VK можно скачать только нужный отрезок."
        )

        self.media_file = tk.StringVar()
        self.model_profile = tk.StringVar(value="Быстрая — large-v3-turbo (рекомендуется)")
        self.language = tk.StringVar(value="Авто")
        self.timestamps = tk.BooleanVar(value=False)
        self.make_srt = tk.BooleanVar(value=True)

        self.subtitle_url = tk.StringVar()
        self.subtitle_track_label = tk.StringVar()
        self.subtitle_info: SubtitleInfo | None = None
        self.subtitle_tracks: list[SubtitleTrack] = []
        self.subtitle_status = tk.StringVar(value="Вставь YouTube-ссылку — дорожки найдутся автоматически.")

        self.status = tk.StringVar(value="Готов к работе")
        self.progress = tk.IntVar(value=0)

        self._configure_styles()
        self._build_ui()

        self.url.trace_add("write", self._on_url_changed)
        self.subtitle_url.trace_add("write", self._on_subtitle_url_changed)
        self.output_root.trace_add("write", self._refresh_output_paths)
        self._refresh_output_paths()
        self.root.after(120, self._poll_events)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=(UI_FONT, 10))
        style.configure("App.TFrame", background=BG)
        style.configure("Header.TFrame", background=DARK)
        style.configure("HeaderTitle.TLabel", background=DARK, foreground="white", font=(UI_FONT, 24, "bold"))
        style.configure("HeaderSub.TLabel", background=DARK, foreground="#C7D0DC", font=(UI_FONT, 10))
        style.configure("Version.TLabel", background="#263244", foreground="#F8FAFC", padding=(8, 4), font=(UI_FONT, 9, "bold"))

        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#E7EBF0",
            foreground="#556274",
            padding=(18, 10),
            font=(UI_FONT, 10, "bold"),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", CARD), ("active", "#F0F3F6")],
            foreground=[("selected", TEXT), ("active", TEXT)],
        )

        style.configure(
            "Card.TLabelframe",
            background=CARD,
            bordercolor=BORDER,
            borderwidth=1,
            relief="solid",
            padding=14,
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=CARD,
            foreground=TEXT,
            font=(UI_FONT, 11, "bold"),
        )
        style.configure("Card.TFrame", background=CARD)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT)
        style.configure("Muted.Card.TLabel", background=CARD, foreground=MUTED)
        style.configure("Success.Card.TLabel", background=CARD, foreground=SUCCESS, font=(UI_FONT, 10, "bold"))

        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="white",
            bordercolor=ACCENT,
            padding=(16, 9),
            font=(UI_FONT, 10, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_DARK), ("disabled", "#E9A487")],
            foreground=[("disabled", "#FFF4EF")],
        )
        style.configure("Secondary.TButton", padding=(12, 7))
        style.configure("TEntry", fieldbackground="white", bordercolor=BORDER, padding=6)
        style.configure("TCombobox", fieldbackground="white", bordercolor=BORDER, padding=5)
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#E5EAF0", bordercolor="#E5EAF0")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="Header.TFrame", padding=(20, 16))
        header.pack(fill="x", pady=(0, 14))

        header_text = ttk.Frame(header, style="Header.TFrame")
        header_text.pack(side="left", fill="x", expand=True)
        ttk.Label(header_text, text="RNGN Media", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(
            header_text,
            text="Скачивание · транскрибация · YouTube-субтитры",
            style="HeaderSub.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        ttk.Label(header, text=f"v{APP_VERSION}", style="Version.TLabel").pack(side="right", anchor="n")

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        self._build_download_tab(notebook)
        self._build_transcribe_tab(notebook)
        self._build_subtitles_tab(notebook)

        footer = ttk.Frame(outer, style="App.TFrame")
        footer.pack(fill="x", pady=(12, 0))
        ttk.Label(footer, textvariable=self.status, background=BG, foreground=MUTED).pack(side="left")
        ttk.Progressbar(footer, variable=self.progress, maximum=100, length=280).pack(side="right")

    def _tab_frame(self, notebook: ttk.Notebook, title: str) -> ttk.Frame:
        frame = ttk.Frame(notebook, style="App.TFrame", padding=(6, 12))
        notebook.add(frame, text=title)
        return frame

    def _card(self, parent: ttk.Frame, title: str) -> ttk.LabelFrame:
        card = ttk.LabelFrame(parent, text=title, style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, 12))
        return card

    def _url_entry(self, parent: ttk.Frame, variable: tk.StringVar) -> ttk.Entry:
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x")
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Очистить", style="Secondary.TButton", command=lambda: variable.set("")).pack(
            side="left", padx=(8, 0)
        )

        def paste_clipboard(_event=None):
            try:
                value = self.root.clipboard_get()
            except tk.TclError:
                return "break"
            url = clean_pasted_url(value)
            if url:
                variable.set(url)
                entry.icursor("end")
            return "break"

        def control_key(event):
            if is_paste_shortcut(getattr(event, "keycode", 0), getattr(event, "keysym", "")):
                return paste_clipboard(event)
            return None

        menu = tk.Menu(entry, tearoff=False)
        menu.add_command(label="Вставить", command=paste_clipboard)
        menu.add_command(label="Копировать", command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="Вырезать", command=lambda: entry.event_generate("<<Cut>>"))

        def show_menu(event):
            entry.focus_set()
            menu.tk_popup(event.x_root, event.y_root)

        entry.bind("<Control-KeyPress>", control_key, add="+")
        entry.bind("<Shift-Insert>", paste_clipboard, add="+")
        entry.bind("<Button-3>", show_menu)
        return entry

    def _output_controls(self, parent: ttk.Frame, variable: tk.StringVar) -> None:
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Entry(row, textvariable=variable, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(
            row,
            text="Открыть",
            style="Secondary.TButton",
            command=lambda: self._open_folder(Path(variable.get())),
        ).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Изменить", style="Secondary.TButton", command=self._choose_output).pack(
            side="left", padx=(6, 0)
        )

    def _log_box(self, parent: ttk.Frame, height: int = 12) -> tk.Text:
        log = tk.Text(
            parent,
            height=height,
            wrap="word",
            bg=DARK,
            fg=LOG_FG,
            insertbackground="white",
            selectbackground="#334155",
            relief="flat",
            padx=10,
            pady=10,
            font=(MONO_FONT, 9),
        )
        log.pack(fill="both", expand=True)
        log.configure(state="disabled")
        return log

    def _build_download_tab(self, notebook: ttk.Notebook) -> None:
        frame = self._tab_frame(notebook, "Скачать медиа")

        source = self._card(frame, "1. Ссылка")
        self.download_url_entry = self._url_entry(source, self.url)
        ttk.Label(source, textvariable=self.platform, style="Muted.Card.TLabel").pack(anchor="w", pady=(8, 0))

        quality = self._card(frame, "2. Качество")
        self.quality_combo = ttk.Combobox(quality, textvariable=self.quality, values=[], state="disabled")
        self.quality_combo.pack(fill="x")
        quality_row = ttk.Frame(quality, style="Card.TFrame")
        quality_row.pack(fill="x", pady=(8, 0))
        ttk.Label(quality_row, textvariable=self.quality_status, style="Muted.Card.TLabel").pack(side="left")
        self.quality_refresh_button = ttk.Button(
            quality_row,
            text="Проверить ещё раз",
            style="Secondary.TButton",
            command=self._start_quality_analysis,
        )
        self.quality_refresh_button.pack(side="right")

        clip = self._card(frame, "3. Фрагмент по таймкодам · необязательно")
        clip_row = ttk.Frame(clip, style="Card.TFrame")
        clip_row.pack(fill="x")

        start_box = ttk.Frame(clip_row, style="Card.TFrame")
        start_box.pack(side="left", fill="x", expand=True, padx=(0, 7))
        ttk.Label(start_box, text="От", style="Card.TLabel").pack(anchor="w")
        self.clip_start_entry = ttk.Entry(start_box, textvariable=self.clip_start, state="disabled")
        self.clip_start_entry.pack(fill="x", pady=(4, 0))

        end_box = ttk.Frame(clip_row, style="Card.TFrame")
        end_box.pack(side="left", fill="x", expand=True, padx=(7, 0))
        ttk.Label(end_box, text="До", style="Card.TLabel").pack(anchor="w")
        self.clip_end_entry = ttk.Entry(end_box, textvariable=self.clip_end, state="disabled")
        self.clip_end_entry.pack(fill="x", pady=(4, 0))

        ttk.Label(
            clip,
            textvariable=self.clip_status,
            style="Muted.Card.TLabel",
        ).pack(anchor="w", pady=(8, 0))

        output = self._card(frame, "4. Сохранение")
        self._output_controls(output, self.download_output)

        action = ttk.Frame(frame, style="App.TFrame")
        action.pack(fill="x", pady=(0, 12))
        self.download_button = ttk.Button(
            action,
            text="Скачать видео",
            style="Accent.TButton",
            command=self._start_download,
            state="disabled",
        )
        self.download_button.pack(side="left")

        log_card = self._card(frame, "Технический лог")
        self.download_log = self._log_box(log_card, height=8)

    def _build_transcribe_tab(self, notebook: ttk.Notebook) -> None:
        frame = self._tab_frame(notebook, "Транскрибировать")

        source = self._card(frame, "1. Исходный файл")
        row = ttk.Frame(source, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.media_file).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Выбрать файл", style="Secondary.TButton", command=self._choose_media).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(
            source,
            text="Видео не копируется: программа читает исходник на месте и создаёт только TXT/SRT.",
            style="Muted.Card.TLabel",
        ).pack(anchor="w", pady=(8, 0))

        settings = self._card(frame, "2. Настройки")
        grid = ttk.Frame(settings, style="Card.TFrame")
        grid.pack(fill="x")
        left = ttk.Frame(grid, style="Card.TFrame")
        left.pack(side="left", fill="x", expand=True, padx=(0, 7))
        right = ttk.Frame(grid, style="Card.TFrame")
        right.pack(side="left", fill="x", expand=True, padx=(7, 0))
        ttk.Label(left, text="Модель", style="Card.TLabel").pack(anchor="w")
        ttk.Combobox(left, textvariable=self.model_profile, values=list(MODEL_PROFILES), state="readonly").pack(fill="x", pady=(4, 0))
        ttk.Label(right, text="Язык", style="Card.TLabel").pack(anchor="w")
        ttk.Combobox(right, textvariable=self.language, values=list(LANGUAGES), state="readonly").pack(fill="x", pady=(4, 0))

        checks = ttk.Frame(settings, style="Card.TFrame")
        checks.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(checks, text="Сделать SRT", variable=self.make_srt).pack(side="left")
        ttk.Checkbutton(checks, text="Таймкоды в TXT", variable=self.timestamps).pack(side="left", padx=(18, 0))

        output = self._card(frame, "3. Результат")
        self._output_controls(output, self.transcript_output)

        action = ttk.Frame(frame, style="App.TFrame")
        action.pack(fill="x", pady=(0, 12))
        self.transcribe_button = ttk.Button(
            action,
            text="Транскрибировать",
            style="Accent.TButton",
            command=self._start_transcribe,
        )
        self.transcribe_button.pack(side="left")

        log_card = self._card(frame, "Технический лог")
        self.transcribe_log = self._log_box(log_card, height=10)

    def _build_subtitles_tab(self, notebook: ttk.Notebook) -> None:
        frame = self._tab_frame(notebook, "YouTube субтитры")

        source = self._card(frame, "1. YouTube-ссылка")
        self.subtitle_url_entry = self._url_entry(source, self.subtitle_url)
        subtitle_row = ttk.Frame(source, style="Card.TFrame")
        subtitle_row.pack(fill="x", pady=(8, 0))
        ttk.Label(subtitle_row, textvariable=self.subtitle_status, style="Muted.Card.TLabel").pack(side="left")
        self.subtitle_analyze_button = ttk.Button(
            subtitle_row,
            text="Обновить дорожки",
            style="Secondary.TButton",
            command=self._start_subtitle_analysis,
        )
        self.subtitle_analyze_button.pack(side="right")

        track_card = self._card(frame, "2. Дорожка")
        self.subtitle_track_combo = ttk.Combobox(
            track_card,
            textvariable=self.subtitle_track_label,
            values=[],
            state="disabled",
        )
        self.subtitle_track_combo.pack(fill="x")

        output = self._card(frame, "3. Результат")
        self._output_controls(output, self.subtitle_output)

        action = ttk.Frame(frame, style="App.TFrame")
        action.pack(fill="x", pady=(0, 12))
        self.subtitle_download_button = ttk.Button(
            action,
            text="Сохранить TXT + SRT",
            style="Accent.TButton",
            command=self._start_subtitle_download,
            state="disabled",
        )
        self.subtitle_download_button.pack(side="left")

        log_card = self._card(frame, "Технический лог")
        self.subtitle_log = self._log_box(log_card, height=10)

    def _on_url_changed(self, *_args) -> None:
        value = clean_pasted_url(self.url.get())
        platform = detect_platform(value) if value else ""
        self.platform.set(
            f"Определено: {platform}" if platform and platform != "Other"
            else ("Ссылка пока не распознана" if value else "Вставь ссылку — платформа определится автоматически")
        )
        self._refresh_output_paths()
        clip_supported = platform in {"YouTube", "VK"}
        clip_state = "normal" if clip_supported else "disabled"
        self.clip_start_entry.configure(state=clip_state)
        self.clip_end_entry.configure(state=clip_state)
        if clip_supported:
            self.clip_status.set(
                "Необязательно. Введи оба таймкода: 01:23 или 00:01:23. "
                "Скачается только этот отрезок."
            )
        else:
            self.clip_start.set("")
            self.clip_end.set("")
            self.clip_status.set("Вырезание по таймкодам доступно для YouTube и VK.")

        if self.quality_after_id:
            self.root.after_cancel(self.quality_after_id)
            self.quality_after_id = None

        self.quality_values = []
        self.quality_combo.configure(values=[], state="disabled")
        self.quality.set("")
        self.download_button.configure(state="disabled")

        if platform and platform != "Other":
            self.quality_status.set("Проверяю реальные форматы источника…")
            self.quality_after_id = self.root.after(650, lambda snapshot=value: self._start_quality_analysis(snapshot))
        else:
            self.quality_status.set("После вставки ссылки покажу только реально доступные варианты.")

    def _on_subtitle_url_changed(self, *_args) -> None:
        value = clean_pasted_url(self.subtitle_url.get())
        if self.subtitle_after_id:
            self.root.after_cancel(self.subtitle_after_id)
            self.subtitle_after_id = None

        self.subtitle_info = None
        self.subtitle_tracks = []
        self.subtitle_track_label.set("")
        self.subtitle_track_combo.configure(values=[], state="disabled")
        self.subtitle_download_button.configure(state="disabled")

        if value and detect_platform(value) == "YouTube":
            self.subtitle_status.set("Ищу оригинальные дорожки…")
            self.subtitle_after_id = self.root.after(500, lambda snapshot=value: self._start_subtitle_analysis(snapshot))
        else:
            self.subtitle_status.set("Вставь YouTube-ссылку — дорожки найдутся автоматически.")

    def _refresh_output_paths(self, *_args) -> None:
        root = Path(self.output_root.get() or default_output_dir()).expanduser()
        platform = detect_platform(self.url.get().strip()) if self.url.get().strip() else ""
        self.download_output.set(str(root / platform_folder(platform)) if platform and platform != "Other" else str(root))
        self.transcript_output.set(str(root / "Transcripts"))
        self.subtitle_output.set(str(root / "YouTube_Subtitles"))

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_root.get() or str(default_output_dir()))
        if selected:
            self.output_root.set(selected)

    def _choose_media(self) -> None:
        selected = filedialog.askopenfilename(title="Выбери аудио или видео")
        if selected:
            self.media_file.set(selected)

    def _open_folder(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Не удалось открыть папку:\n{path}\n\n{exc}")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.transcribe_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.download_button.configure(state="disabled")
            self.subtitle_download_button.configure(state="disabled")
        else:
            if self.quality_values and not self.quality_analyzing:
                self.download_button.configure(state="normal")
            if self.subtitle_tracks and not self.subtitle_analyzing:
                self.subtitle_download_button.configure(state="normal")
        if not busy:
            self.progress.set(0)

    def _post(self, kind: str, payload: object) -> None:
        self.events.put((kind, payload))

    def _start_quality_analysis(self, url: str | None = None) -> None:
        if self.quality_analyzing:
            return
        target = clean_pasted_url(url or self.url.get())
        if not target or detect_platform(target) == "Other":
            return

        self.quality_analyzing = True
        self.quality_started_at = time.monotonic()
        self.quality_combo.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.quality_refresh_button.configure(state="disabled", text="Проверяю…")
        self.quality_status.set("Подключаюсь к источнику и читаю реальные форматы…")
        self.progress.set(6)
        threading.Thread(target=self._quality_worker, args=(target,), daemon=True).start()

    def _quality_worker(self, url: str) -> None:
        stop_heartbeat = threading.Event()
        started = time.monotonic()

        def heartbeat() -> None:
            while not stop_heartbeat.wait(2):
                elapsed = int(time.monotonic() - started)
                self._post("quality_heartbeat", (url, elapsed))

        threading.Thread(target=heartbeat, daemon=True).start()

        try:
            analysis = analyze_media(
                url,
                status=lambda s: self._post("quality_status", s),
                progress=lambda p: self._post("quality_progress", p),
                log=lambda s: self._post("download_log", s),
            )
            self._post("media_analysis", (url, analysis))
        except Exception as exc:
            self._post("quality_error", (url, str(exc)))
        finally:
            stop_heartbeat.set()

    def _start_download(self) -> None:
        if self.busy:
            return

        url = clean_pasted_url(self.url.get())
        if not url:
            messagebox.showerror(APP_NAME, "Вставь ссылку.")
            return
        if not self.quality.get():
            messagebox.showerror(APP_NAME, "Сначала дождись определения доступного качества.")
            return

        platform = detect_platform(url)
        start_text = self.clip_start.get().strip()
        end_text = self.clip_end.get().strip()
        clip_start: float | None = None
        clip_end: float | None = None

        if start_text or end_text:
            if platform not in {"YouTube", "VK"}:
                messagebox.showerror(APP_NAME, "Фрагменты по таймкодам работают только для YouTube и VK.")
                return
            if not start_text or not end_text:
                messagebox.showerror(APP_NAME, "Для фрагмента укажи оба таймкода: «От» и «До».")
                return
            try:
                clip_start, clip_end = validate_clip_range(start_text, end_text)
            except ValueError as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return

        out = Path(self.output_root.get()).expanduser()
        quality = self.quality.get()
        self._set_busy(True)
        self.status.set("Запускаю скачивание…")
        threading.Thread(
            target=self._download_worker,
            args=(url, out, quality, clip_start, clip_end),
            daemon=True,
        ).start()

    def _download_worker(
        self,
        url: str,
        out: Path,
        quality: str,
        clip_start: float | None,
        clip_end: float | None,
    ) -> None:
        try:
            outputs = download_media(
                url,
                out,
                status=lambda s: self._post("status", s),
                progress=lambda p: self._post("progress", p),
                log=lambda s: self._post("download_log", s),
                quality=quality,
                clip_start=clip_start,
                clip_end=clip_end,
            )
            title = "Фрагмент сохранён" if clip_start is not None else "Скачивание завершено"
            self._post("done", (title, outputs, "download_log"))
        except Exception as exc:
            self._post("error", f"{exc}\n\n{traceback.format_exc()}")

    def _start_transcribe(self) -> None:
        if self.busy:
            return
        media = Path(self.media_file.get()).expanduser()
        if not media.is_file():
            messagebox.showerror(APP_NAME, "Выбери существующий аудио- или видеофайл.")
            return

        out = Path(self.transcript_output.get()).expanduser()
        self._set_busy(True)
        self.status.set("Запускаю транскрибацию…")
        threading.Thread(
            target=self._transcribe_worker,
            args=(
                media,
                out,
                self.model_profile.get(),
                self.language.get(),
                self.timestamps.get(),
                self.make_srt.get(),
            ),
            daemon=True,
        ).start()

    def _transcribe_worker(
        self,
        media: Path,
        out: Path,
        profile_name: str,
        language_name: str,
        with_timestamps: bool,
        make_srt: bool,
    ) -> None:
        stop_heartbeat = threading.Event()
        started = time.monotonic()

        def heartbeat() -> None:
            while not stop_heartbeat.wait(8):
                elapsed = int(time.monotonic() - started)
                minutes, seconds = divmod(elapsed, 60)
                self._post("transcribe_heartbeat", f"Обработка идёт · {minutes:02d}:{seconds:02d}")

        threading.Thread(target=heartbeat, daemon=True).start()

        try:
            outputs = transcribe_media(
                media,
                out,
                profile_name=profile_name,
                language_name=language_name,
                with_timestamps=with_timestamps,
                make_srt=make_srt,
                status=lambda s: self._post("status", s),
                progress=lambda p: self._post("progress", p),
                log=lambda s: self._post("transcribe_log", s),
            )
            self._post("done", ("Транскрибация завершена", outputs, "transcribe_log"))
        except Exception as exc:
            self._post("error", f"{exc}\n\n{traceback.format_exc()}")
        finally:
            stop_heartbeat.set()

    def _start_subtitle_analysis(self, url: str | None = None) -> None:
        if self.subtitle_analyzing:
            return
        target = clean_pasted_url(url or self.subtitle_url.get())
        if not target or detect_platform(target) != "YouTube":
            return
        self.subtitle_analyzing = True
        self.subtitle_analyze_button.configure(state="disabled")
        self.subtitle_track_combo.configure(state="disabled")
        self.subtitle_download_button.configure(state="disabled")
        self.subtitle_status.set("Ищу оригинальные дорожки YouTube…")
        threading.Thread(target=self._subtitle_analysis_worker, args=(target,), daemon=True).start()

    def _subtitle_analysis_worker(self, url: str) -> None:
        try:
            info = analyze_youtube_subtitles(
                url,
                status=lambda s: self._post("subtitle_status", s),
                progress=lambda _p: None,
                log=lambda s: self._post("subtitle_log", s),
            )
            self._post("subtitle_tracks", (url, info))
        except Exception as exc:
            self._post("subtitle_error", (url, str(exc)))

    def _start_subtitle_download(self) -> None:
        if self.busy:
            return
        if not self.subtitle_tracks or self.subtitle_info is None:
            messagebox.showerror(APP_NAME, "Сначала дождись списка дорожек.")
            return

        selected = self.subtitle_track_label.get()
        track = next((item for item in self.subtitle_tracks if item.label == selected), None)
        if track is None:
            messagebox.showerror(APP_NAME, "Выбери дорожку субтитров.")
            return

        url = clean_pasted_url(self.subtitle_url.get())
        out = Path(self.subtitle_output.get()).expanduser()
        self._set_busy(True)
        self.status.set("Сохраняю субтитры…")
        threading.Thread(
            target=self._subtitle_download_worker,
            args=(url, track, out, self.subtitle_info.title),
            daemon=True,
        ).start()

    def _subtitle_download_worker(self, url: str, track: SubtitleTrack, out: Path, title_hint: str) -> None:
        try:
            outputs = download_youtube_subtitle(
                url,
                track,
                out,
                title_hint=title_hint,
                status=lambda s: self._post("status", s),
                progress=lambda p: self._post("progress", p),
                log=lambda s: self._post("subtitle_log", s),
            )
            self._post("done", ("YouTube-субтитры сохранены", outputs, "subtitle_log"))
        except Exception as exc:
            self._post("error", f"{exc}\n\n{traceback.format_exc()}")

    def _append_log(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.insert("end", text + "\n")
        widget.see("end")
        widget.configure(state="disabled")

    def _log_widget(self, channel: str) -> tk.Text:
        return {
            "download_log": self.download_log,
            "transcribe_log": self.transcribe_log,
            "subtitle_log": self.subtitle_log,
        }[channel]

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()

                if kind == "status":
                    self.status.set(str(payload))
                elif kind == "progress":
                    self.progress.set(int(payload))
                elif kind == "quality_status":
                    self.quality_status.set(str(payload))
                elif kind == "quality_progress":
                    self.progress.set(int(payload))
                elif kind == "quality_heartbeat":
                    url, elapsed = payload  # type: ignore[misc]
                    if self.quality_analyzing and clean_pasted_url(self.url.get()) == url:
                        self.quality_status.set(
                            f"Анализ ещё идёт · {elapsed} с. "
                            "Если YouTube тормозит, максимум примерно 20 с, затем включится резервный режим."
                        )
                        self.progress.set(min(80, 8 + int(elapsed) * 3))
                elif kind == "subtitle_status":
                    self.subtitle_status.set(str(payload))
                elif kind == "transcribe_heartbeat":
                    self.status.set(str(payload))
                elif kind == "download_log":
                    self._append_log(self.download_log, str(payload))
                elif kind == "transcribe_log":
                    self._append_log(self.transcribe_log, str(payload))
                elif kind == "subtitle_log":
                    self._append_log(self.subtitle_log, str(payload))

                elif kind == "media_analysis":
                    url, analysis = payload  # type: ignore[misc]
                    self.quality_analyzing = False
                    self.quality_refresh_button.configure(state="normal", text="Проверить ещё раз")
                    if clean_pasted_url(self.url.get()) != url:
                        continue
                    assert isinstance(analysis, MediaAnalysis)
                    self.quality_values = [choice.label for choice in analysis.choices]
                    self.quality_combo.configure(values=self.quality_values, state="readonly")
                    self.quality.set(analysis.default_label)
                    has_unknown_audio = any(
                        "звук: не определён источником" in label
                        for label in self.quality_values
                    )
                    if has_unknown_audio:
                        self.quality_status.set(
                            "Источник не сообщает аудиокодек заранее. "
                            "После скачивания FFprobe проверит реальный файл и сохранит звук, если он есть."
                        )
                    else:
                        self.quality_status.set(
                            f"Проверено по источнику · доступно вариантов: {len(self.quality_values)}"
                        )
                    if not self.busy:
                        self.download_button.configure(state="normal")

                elif kind == "quality_error":
                    url, error = payload  # type: ignore[misc]
                    self.quality_analyzing = False
                    self.quality_refresh_button.configure(state="normal", text="Проверить ещё раз")
                    if clean_pasted_url(self.url.get()) != url:
                        continue

                    self._append_log(self.download_log, f"[analysis] {error}")
                    self.quality_values = [
                        "1080p — без анализа → MP4 H.264 + AAC",
                        "720p — без анализа → MP4 H.264 + AAC",
                        "Лучшее доступное — без анализа → MP4 H.264 + AAC",
                    ]
                    self.quality_combo.configure(values=self.quality_values, state="readonly")
                    self.quality.set(self.quality_values[0])
                    self.quality_status.set(
                        f"{error}  Можно скачать сейчас в резервном режиме или нажать «Проверить ещё раз»."
                    )
                    self.progress.set(0)
                    if not self.busy:
                        self.download_button.configure(state="normal")

                elif kind == "subtitle_tracks":
                    url, info = payload  # type: ignore[misc]
                    self.subtitle_analyzing = False
                    self.subtitle_analyze_button.configure(state="normal")
                    if clean_pasted_url(self.subtitle_url.get()) != url:
                        continue
                    assert isinstance(info, SubtitleInfo)
                    self.subtitle_info = info
                    self.subtitle_tracks = list(info.tracks)
                    labels = [track.label for track in self.subtitle_tracks]
                    self.subtitle_track_combo.configure(values=labels, state="readonly")
                    if labels:
                        original_index = next(
                            (index for index, track in enumerate(self.subtitle_tracks) if track.is_original),
                            0,
                        )
                        self.subtitle_track_label.set(labels[original_index])
                        if not self.busy:
                            self.subtitle_download_button.configure(state="normal")
                    self.subtitle_status.set(f"{info.title} · дорожек: {len(labels)}")

                elif kind == "subtitle_error":
                    url, error = payload  # type: ignore[misc]
                    self.subtitle_analyzing = False
                    self.subtitle_analyze_button.configure(state="normal")
                    if clean_pasted_url(self.subtitle_url.get()) != url:
                        continue
                    self.subtitle_status.set(f"Не удалось получить дорожки: {error}")

                elif kind == "done":
                    title, outputs, channel = payload  # type: ignore[misc]
                    outputs = [Path(path) for path in outputs]
                    self.progress.set(100)
                    self.status.set(str(title))
                    self._set_busy(False)
                    widget = self._log_widget(str(channel))
                    self._append_log(widget, "")
                    self._append_log(widget, "СОХРАНЕНО:")
                    for path in outputs:
                        self._append_log(widget, str(path))
                    paths = "\n".join(str(path) for path in outputs)
                    open_now = messagebox.askyesno(
                        APP_NAME,
                        f"{title}\n\n{paths}\n\nОткрыть папку с результатом?",
                    )
                    if open_now and outputs:
                        self._open_folder(outputs[0].parent)

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
