from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import app as base
from runtime_v037 import OperationCancelled, analyze_media, download_media


base.APP_VERSION = "0.3.7"


class App(base.App):
    def __init__(self) -> None:
        self._quality_cancel = threading.Event()
        self._download_cancel = threading.Event()
        self._download_active = False
        super().__init__()

        # Put cancellation exactly where the user expects it: next to Download.
        self.cancel_download_button = ttk.Button(
            self.download_button.master,
            text="Отменить",
            style="Secondary.TButton",
            command=self._cancel_download_flow,
            state="disabled",
        )
        self.cancel_download_button.pack(side="left", padx=(8, 0))
        self.root.after(150, self._refresh_cancel_button)

    def _log_box(self, parent: ttk.Frame, height: int = 12) -> tk.Text:
        toolbar = ttk.Frame(parent, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 7))

        log_frame = ttk.Frame(parent, style="Card.TFrame")
        log_frame.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(log_frame, orient="vertical")
        scroll.pack(side="right", fill="y")

        log = tk.Text(
            log_frame,
            height=height,
            wrap="word",
            bg=base.DARK,
            fg=base.LOG_FG,
            insertbackground="white",
            selectbackground="#334155",
            relief="flat",
            padx=10,
            pady=10,
            font=(base.MONO_FONT, 9),
            yscrollcommand=scroll.set,
        )
        log.pack(side="left", fill="both", expand=True)
        scroll.configure(command=log.yview)
        log.configure(state="disabled")

        def selected_text() -> str:
            try:
                return log.get("sel.first", "sel.last")
            except tk.TclError:
                return ""

        def copy_text(value: str) -> None:
            if not value:
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.status.set("Лог скопирован в буфер обмена")

        def copy_selected(_event=None):
            copy_text(selected_text())
            return "break"

        def copy_all(_event=None):
            copy_text(log.get("1.0", "end-1c"))
            return "break"

        def select_all(_event=None):
            log.tag_add("sel", "1.0", "end-1c")
            log.mark_set("insert", "1.0")
            log.see("1.0")
            return "break"

        def clear_log() -> None:
            log.configure(state="normal")
            log.delete("1.0", "end")
            log.configure(state="disabled")

        ttk.Button(
            toolbar,
            text="Копировать лог",
            style="Secondary.TButton",
            command=copy_all,
        ).pack(side="right")
        ttk.Button(
            toolbar,
            text="Очистить",
            style="Secondary.TButton",
            command=clear_log,
        ).pack(side="right", padx=(0, 6))

        menu = tk.Menu(log, tearoff=False)
        menu.add_command(label="Копировать выделенное", command=copy_selected)
        menu.add_command(label="Копировать весь лог", command=copy_all)
        menu.add_separator()
        menu.add_command(label="Выделить всё", command=select_all)

        def show_menu(event):
            log.focus_set()
            menu.tk_popup(event.x_root, event.y_root)
            return "break"

        log.bind("<Control-a>", select_all, add="+")
        log.bind("<Control-A>", select_all, add="+")
        log.bind("<Control-c>", copy_selected, add="+")
        log.bind("<Control-C>", copy_selected, add="+")
        log.bind("<Button-3>", show_menu, add="+")
        return log

    def _refresh_cancel_button(self) -> None:
        try:
            active = bool(self.quality_analyzing or self._download_active)
            self.cancel_download_button.configure(state="normal" if active else "disabled")
            self.root.after(150, self._refresh_cancel_button)
        except tk.TclError:
            pass

    def _cancel_download_flow(self) -> None:
        if not (self.quality_analyzing or self._download_active):
            return
        self._quality_cancel.set()
        self._download_cancel.set()
        self.cancel_download_button.configure(state="disabled")
        self.status.set("Отменяю операцию…")
        self.quality_status.set("Отменяю проверку…") if self.quality_analyzing else None
        self._append_log(self.download_log, "[cancel] Пользователь нажал «Отменить».")

    def _finish_quality_cancel(self) -> None:
        self.quality_analyzing = False
        self.quality_refresh_button.configure(state="normal", text="Проверить ещё раз")
        self.quality_status.set("Проверка отменена. Можно вставить другую ссылку или проверить ещё раз.")
        self.progress.set(0)
        self.status.set("Отменено")

    def _finish_download_cancel(self) -> None:
        self._download_active = False
        self._set_busy(False)
        self.progress.set(0)
        self.status.set("Скачивание отменено")
        self._append_log(self.download_log, "[cancel] Операция остановлена.")

    def _start_quality_analysis(self, url: str | None = None) -> None:
        self._quality_cancel.clear()
        super()._start_quality_analysis(url)

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
                cancel_event=self._quality_cancel,
            )
            self._post("media_analysis", (url, analysis))
        except OperationCancelled:
            self.root.after(0, self._finish_quality_cancel)
        except Exception as exc:
            self._post("quality_error", (url, str(exc)))
        finally:
            stop_heartbeat.set()

    def _start_download(self) -> None:
        self._download_cancel.clear()
        was_busy = self.busy
        super()._start_download()
        if not was_busy and self.busy:
            self._download_active = True

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
                cancel_event=self._download_cancel,
            )
            title = "Фрагмент сохранён" if clip_start is not None else "Скачивание завершено"
            self._post("done", (title, outputs, "download_log"))
        except OperationCancelled:
            self.root.after(0, self._finish_download_cancel)
        except Exception as exc:
            self._post("error", f"{exc}\n\n{traceback.format_exc()}")
        finally:
            self._download_active = False


if __name__ == "__main__":
    App().run()
