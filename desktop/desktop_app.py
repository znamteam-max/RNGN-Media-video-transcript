from __future__ import annotations

import gc
import logging
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import py7zr
import requests
from tkinterdnd2 import DND_FILES, TkinterDnD

APP_NAME = "ZNAMBO Transcriber"
APP_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ZNAMBO Transcriber"
MODEL_DIR = APP_DIR / "models"
CUDA_LIB_DIR = APP_DIR / "cuda-libs"
LOG_DIR = APP_DIR / "logs"
DOWNLOAD_DIR = Path.home() / "Downloads"

CUDA_ARCHIVE_URL = (
    "https://github.com/Purfview/whisper-standalone-win/releases/download/libs/"
    "cuBLAS.and.cuDNN_CUDA12_win_v3.7z"
)
REQUIRED_CUDA_DLLS = ("cublas64_12.dll", "cudnn64_9.dll")

MODEL_PROFILES = {
    "Точная — large-v3": {"model": "large-v3", "beam_size": 5},
    "Быстрая — large-v3-turbo": {"model": "large-v3-turbo", "beam_size": 3},
}
LANGUAGES = {
    "Русский": "ru",
    "Определить автоматически": None,
    "Английский": "en",
}

_dll_handles: list[object] = []
_registered_cuda_dirs: set[str] = set()


def _register_cuda_dir(path: Path) -> None:
    if not path.is_dir():
        return
    key = str(path.resolve()).lower()
    if key in _registered_cuda_dirs:
        return

    os.environ["PATH"] = f"{path};{os.environ.get('PATH', '')}"
    if hasattr(os, "add_dll_directory"):
        try:
            _dll_handles.append(os.add_dll_directory(str(path)))
        except OSError:
            pass
    _registered_cuda_dirs.add(key)


def _prepare_cuda_paths() -> None:
    candidates = [
        CUDA_LIB_DIR,
        Path(r"C:\ZNAMBO-Transcriber\cuda-libs"),
    ]
    extra = os.getenv("ZNAMBO_CUDA_LIBS")
    if extra:
        candidates.insert(0, Path(extra))
    for candidate in candidates:
        _register_cuda_dir(candidate)


def _folder_has_cuda_runtime(path: Path) -> bool:
    if not path.is_dir():
        return False
    available = {item.name.lower() for item in path.glob("*.dll")}
    return all(name.lower() in available for name in REQUIRED_CUDA_DLLS)


def local_cuda_runtime_ready() -> bool:
    return _folder_has_cuda_runtime(CUDA_LIB_DIR) or _folder_has_cuda_runtime(
        Path(r"C:\ZNAMBO-Transcriber\cuda-libs")
    )


def nvidia_driver_name() -> str | None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=flags,
            check=False,
        )
        if result.returncode == 0:
            names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if names:
                return names[0]
    except Exception:
        pass
    return None


def install_cuda_runtime(progress_callback, status_callback) -> int:
    CUDA_LIB_DIR.mkdir(parents=True, exist_ok=True)
    status_callback("Скачивание CUDA 12 + cuDNN 9…")

    with tempfile.TemporaryDirectory(prefix="znambo-cuda-", dir=str(APP_DIR)) as tmp:
        tmp_dir = Path(tmp)
        archive_path = tmp_dir / "cuda-runtime.7z"
        extract_dir = tmp_dir / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        with requests.get(
            CUDA_ARCHIVE_URL,
            stream=True,
            timeout=(20, 180),
            headers={"User-Agent": "ZNAMBO-Transcriber/1.1"},
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", "0") or "0")
            downloaded = 0
            with archive_path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        progress_callback(min(82, int(downloaded / total * 82)))

        status_callback("Распаковка CUDA-библиотек…")
        progress_callback(84)
        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            archive.extractall(path=extract_dir)

        dlls = list(extract_dir.rglob("*.dll"))
        if not dlls:
            raise RuntimeError("В скачанном архиве CUDA не найдено DLL-файлов.")

        names = {item.name.lower() for item in dlls}
        missing = [name for name in REQUIRED_CUDA_DLLS if name.lower() not in names]
        if missing:
            raise RuntimeError(
                "Архив CUDA не содержит обязательные библиотеки: " + ", ".join(missing)
            )

        progress_callback(92)
        status_callback("Установка CUDA-библиотек…")
        for dll in dlls:
            shutil.copy2(dll, CUDA_LIB_DIR / dll.name)

    _register_cuda_dir(CUDA_LIB_DIR)
    if not _folder_has_cuda_runtime(CUDA_LIB_DIR):
        raise RuntimeError("CUDA-библиотеки скопированы не полностью.")

    progress_callback(100)
    return len(list(CUDA_LIB_DIR.glob("*.dll")))


_prepare_cuda_paths()

import ctranslate2  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

from transcribe import SUPPORTED_EXTENSIONS, readable_timestamp, safe_stem  # noqa: E402


APP_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)
CUDA_LIB_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "desktop.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8",
)


def format_transcript(parts: list[tuple[float, str]], timestamps: bool) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    current_start = 0.0
    current_length = 0

    for start, text in parts:
        if not current:
            current_start = start
        current.append(text)
        current_length += len(text) + 1

        if current_length >= 700 or (
            text.endswith((".", "!", "?")) and current_length >= 350
        ):
            body = " ".join(current).strip()
            paragraphs.append(
                f"[{readable_timestamp(current_start)}] {body}" if timestamps else body
            )
            current = []
            current_length = 0

    if current:
        body = " ".join(current).strip()
        paragraphs.append(
            f"[{readable_timestamp(current_start)}] {body}" if timestamps else body
        )

    return "\n\n".join(paragraphs).strip() + "\n"


def open_folder(path: Path) -> None:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        subprocess.Popen(["explorer.exe", str(path)])


class TranscriptionEngine:
    def __init__(self) -> None:
        self.model: WhisperModel | None = None
        self.model_name: str | None = None
        self.device = "cpu"
        self.compute_type = "int8"
        self.gpu_visible = False
        self.refresh_gpu()

    def refresh_gpu(self) -> None:
        try:
            self.gpu_visible = ctranslate2.get_cuda_device_count() > 0
        except Exception:
            self.gpu_visible = False

    def unload(self) -> None:
        self.model = None
        self.model_name = None
        gc.collect()

    def _load(
        self, model_name: str, prefer_gpu: bool
    ) -> tuple[WhisperModel, str, str]:
        target_device = "cuda" if prefer_gpu and self.gpu_visible else "cpu"
        target_compute = "float16" if target_device == "cuda" else "int8"

        if (
            self.model is not None
            and self.model_name == model_name
            and self.device == target_device
            and self.compute_type == target_compute
        ):
            return self.model, self.device, self.compute_type

        self.unload()
        logging.info(
            "Loading model=%s device=%s compute_type=%s",
            model_name,
            target_device,
            target_compute,
        )
        model = WhisperModel(
            model_name,
            device=target_device,
            compute_type=target_compute,
            download_root=str(MODEL_DIR),
        )
        self.model = model
        self.model_name = model_name
        self.device = target_device
        self.compute_type = target_compute
        return model, target_device, target_compute

    @staticmethod
    def _looks_like_cuda_runtime_error(exc: BaseException) -> bool:
        text = str(exc).lower()
        needles = (
            "cublas",
            "cudnn",
            "cuda",
            "nvidia",
            "driver version is insufficient",
            "library",
        )
        return any(item in text for item in needles)

    def transcribe(
        self,
        media_path: Path,
        profile: dict[str, object],
        language: str | None,
        timestamps: bool,
        progress_callback,
        status_callback,
    ) -> tuple[Path, str]:
        model_name = str(profile["model"])
        beam_size = int(profile["beam_size"])

        self.refresh_gpu()
        attempts = [True, False] if self.gpu_visible else [False]
        last_error: Exception | None = None

        for attempt_index, prefer_gpu in enumerate(attempts):
            parts: list[tuple[float, str]] = []
            try:
                status_callback(
                    f"Загрузка {model_name}. При первом запуске модель скачивается один раз…"
                )
                model, actual_device, _ = self._load(
                    model_name, prefer_gpu=prefer_gpu
                )
                device_name = "NVIDIA GPU" if actual_device == "cuda" else "CPU"
                status_callback(f"Распознавание на {device_name}")

                segments, info = model.transcribe(
                    str(media_path),
                    language=language,
                    beam_size=beam_size,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 700},
                    condition_on_previous_text=True,
                    temperature=0.0,
                    word_timestamps=False,
                )
                duration = float(getattr(info, "duration", 0.0) or 0.0)

                for segment in segments:
                    text = segment.text.strip()
                    if not text:
                        continue
                    parts.append((float(segment.start), text))
                    if duration > 0:
                        progress = min(
                            98, max(1, int(float(segment.end) / duration * 100))
                        )
                        progress_callback(progress)

                if not parts:
                    raise RuntimeError("Речь в файле не обнаружена.")

                output_name = f"{safe_stem(media_path)}.transcript.txt"
                output_path = DOWNLOAD_DIR / output_name
                output_path.write_text(
                    format_transcript(parts, timestamps),
                    encoding="utf-8-sig",
                )
                return output_path, device_name
            except Exception as exc:
                last_error = exc
                logging.exception("Transcription attempt failed")
                if (
                    prefer_gpu
                    and attempt_index == 0
                    and self._looks_like_cuda_runtime_error(exc)
                ):
                    status_callback(
                        "GPU недоступен без CUDA-библиотек. Переключаюсь на CPU…"
                    )
                    self.unload()
                    continue
                raise

        raise last_error or RuntimeError("Не удалось выполнить транскрибацию.")


class DesktopApp:
    def __init__(self) -> None:
        self.root = TkinterDnD.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("840x680")
        self.root.minsize(740, 620)
        self.root.configure(bg="#0d1117")

        self.engine = TranscriptionEngine()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.selected_file = tk.StringVar()
        self.language = tk.StringVar(value="Русский")
        self.profile = tk.StringVar(value="Точная — large-v3")
        self.timestamps = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Готов к работе")
        self.device = tk.StringVar(value=self._device_summary())
        self.last_output: Path | None = None

        self._build_ui()
        self._apply_startup_file()
        self.root.after(150, self._poll_events)

    def _device_summary(self) -> str:
        name = nvidia_driver_name()
        if not name:
            return "NVIDIA не обнаружена · будет использоваться CPU"
        if local_cuda_runtime_ready():
            return f"{name} · CUDA-библиотеки готовы"
        return f"{name} · CUDA проверится при запуске; при необходимости нажми «Настроить GPU»"

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#0d1117")
        style.configure("Card.TFrame", background="#161b22")
        style.configure("TLabel", background="#0d1117", foreground="#f0f6fc")
        style.configure("Muted.TLabel", background="#0d1117", foreground="#8b949e")
        style.configure("Card.TLabel", background="#161b22", foreground="#f0f6fc")
        style.configure(
            "CardMuted.TLabel", background="#161b22", foreground="#8b949e"
        )
        style.configure("TButton", padding=(14, 9))
        style.configure("TCombobox", padding=6)
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#21262d",
            background="#2f81f7",
            bordercolor="#21262d",
            lightcolor="#2f81f7",
            darkcolor="#2f81f7",
        )

        outer = ttk.Frame(self.root, padding=28)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="ZNAMBO — транскрибация",
            font=("Segoe UI", 24, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Перетащи M4A, MP3, WAV, MP4 или другой медиафайл. "
                "Готовый TXT автоматически сохраняется в Downloads."
            ),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 18))

        card = ttk.Frame(outer, style="Card.TFrame", padding=22)
        card.pack(fill="x")

        self.drop_zone = tk.Label(
            card,
            text="ПЕРЕТАЩИ ФАЙЛ СЮДА\nили нажми «Выбрать файл»",
            bg="#0d1117",
            fg="#8b949e",
            activebackground="#0d1117",
            activeforeground="#f0f6fc",
            relief="groove",
            bd=2,
            padx=18,
            pady=24,
            font=("Segoe UI", 11, "bold"),
        )
        self.drop_zone.pack(fill="x")
        self.drop_zone.drop_target_register(DND_FILES)
        self.drop_zone.dnd_bind("<<Drop>>", self._on_drop)
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind("<<Drop>>", self._on_drop)

        file_row = ttk.Frame(card, style="Card.TFrame")
        file_row.pack(fill="x", pady=(12, 15))
        self.file_entry = ttk.Entry(file_row, textvariable=self.selected_file)
        self.file_entry.pack(side="left", fill="x", expand=True)
        self.file_entry.drop_target_register(DND_FILES)
        self.file_entry.dnd_bind("<<Drop>>", self._on_drop)
        ttk.Button(
            file_row, text="Выбрать файл…", command=self._choose_file
        ).pack(side="left", padx=(10, 0))

        controls = ttk.Frame(card, style="Card.TFrame")
        controls.pack(fill="x", pady=(0, 8))

        left = ttk.Frame(controls, style="Card.TFrame")
        left.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Label(left, text="Язык", style="CardMuted.TLabel").pack(anchor="w")
        ttk.Combobox(
            left,
            textvariable=self.language,
            values=list(LANGUAGES),
            state="readonly",
        ).pack(fill="x", pady=(6, 0))

        right = ttk.Frame(controls, style="Card.TFrame")
        right.pack(side="left", fill="x", expand=True, padx=(8, 0))
        ttk.Label(right, text="Режим", style="CardMuted.TLabel").pack(anchor="w")
        ttk.Combobox(
            right,
            textvariable=self.profile,
            values=list(MODEL_PROFILES),
            state="readonly",
        ).pack(fill="x", pady=(6, 0))

        ttk.Checkbutton(
            card,
            text="Добавить таймкоды в итоговый TXT",
            variable=self.timestamps,
        ).pack(anchor="w", pady=(12, 15))

        self.start_button = ttk.Button(
            card, text="Начать транскрибацию", command=self._start
        )
        self.start_button.pack(anchor="w")

        progress_card = ttk.Frame(outer, style="Card.TFrame", padding=22)
        progress_card.pack(fill="x", pady=(18, 0))
        ttk.Label(
            progress_card, textvariable=self.status, style="Card.TLabel"
        ).pack(anchor="w")
        ttk.Label(
            progress_card, textvariable=self.device, style="CardMuted.TLabel"
        ).pack(anchor="w", pady=(4, 10))
        self.progress = ttk.Progressbar(
            progress_card, maximum=100, mode="determinate"
        )
        self.progress.pack(fill="x")

        buttons = ttk.Frame(progress_card, style="Card.TFrame")
        buttons.pack(fill="x", pady=(14, 0))
        self.open_file_button = ttk.Button(
            buttons,
            text="Открыть TXT",
            command=self._open_result,
            state="disabled",
        )
        self.open_file_button.pack(side="left")
        ttk.Button(
            buttons,
            text="Открыть Downloads",
            command=lambda: open_folder(DOWNLOAD_DIR),
        ).pack(side="left", padx=(8, 0))
        self.gpu_button = ttk.Button(
            buttons,
            text="Настроить NVIDIA GPU",
            command=self._setup_gpu,
        )
        self.gpu_button.pack(side="left", padx=(8, 0))
        ttk.Button(
            buttons, text="Логи", command=lambda: open_folder(LOG_DIR)
        ).pack(side="left", padx=(8, 0))

        hint = (
            "Модель скачивается один раз при первом использовании. "
            "Кнопка «Настроить NVIDIA GPU» скачивает примерно 810 МБ CUDA 12/cuDNN 9 "
            "в AppData текущего пользователя — админские права не нужны. "
            "Если GPU всё равно недоступен, программа автоматически перейдёт на CPU."
        )
        ttk.Label(
            outer, text=hint, style="Muted.TLabel", wraplength=780
        ).pack(anchor="w", pady=(16, 0))

    def _apply_startup_file(self) -> None:
        if len(sys.argv) < 2:
            return
        candidate = Path(sys.argv[1].strip().strip('"'))
        if candidate.is_file():
            self._set_file(candidate, show_error=False)

    def _set_file(self, path: Path, *, show_error: bool = True) -> bool:
        path = path.expanduser()
        if not path.is_file():
            if show_error:
                messagebox.showerror(APP_NAME, "Перетащенный файл не найден.")
            return False
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            if show_error:
                messagebox.showerror(
                    APP_NAME,
                    f"Формат {path.suffix or '(без расширения)'} не поддерживается.",
                )
            return False
        self.selected_file.set(str(path))
        self.drop_zone.configure(
            text=f"ВЫБРАН ФАЙЛ\n{path.name}",
            fg="#f0f6fc",
        )
        return True

    def _on_drop(self, event) -> str:
        try:
            items = self.root.tk.splitlist(event.data)
        except Exception:
            items = [str(event.data)]
        if items:
            self._set_file(Path(items[0]))
        return "break"

    def _choose_file(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        path = filedialog.askopenfilename(
            title="Выберите аудио или видео",
            filetypes=[("Аудио и видео", patterns), ("Все файлы", "*.*")],
        )
        if path:
            self._set_file(Path(path))

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.start_button.configure(state=state)
        self.gpu_button.configure(state=state)

    def _start(self) -> None:
        media_path = Path(self.selected_file.get().strip().strip('"'))
        if not media_path.is_file():
            messagebox.showerror(
                APP_NAME, "Выбери или перетащи существующий аудио- или видеофайл."
            )
            return
        if media_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            messagebox.showerror(
                APP_NAME,
                f"Формат {media_path.suffix or '(без расширения)'} не поддерживается.",
            )
            return

        self._set_busy(True)
        self.open_file_button.configure(state="disabled")
        self.progress["value"] = 0
        self.last_output = None
        self.status.set("Подготовка…")

        profile = dict(MODEL_PROFILES[self.profile.get()])
        language = LANGUAGES[self.language.get()]
        timestamps = bool(self.timestamps.get())

        threading.Thread(
            target=self._worker,
            args=(media_path, profile, language, timestamps),
            daemon=True,
        ).start()

    def _worker(
        self,
        media_path: Path,
        profile: dict[str, object],
        language: str | None,
        timestamps: bool,
    ) -> None:
        try:
            output_path, device_name = self.engine.transcribe(
                media_path,
                profile,
                language,
                timestamps,
                progress_callback=lambda value: self.events.put(
                    ("progress", value)
                ),
                status_callback=lambda text: self.events.put(("status", text)),
            )
            self.events.put(("done", (output_path, device_name)))
        except Exception as exc:
            logging.error("Fatal transcription error\n%s", traceback.format_exc())
            self.events.put(("error", str(exc)))

    def _setup_gpu(self) -> None:
        name = nvidia_driver_name()
        if not name:
            messagebox.showinfo(
                APP_NAME,
                "NVIDIA-видеокарта или драйвер NVIDIA не обнаружены. "
                "Транскрибация будет работать на CPU.",
            )
            return

        if _folder_has_cuda_runtime(CUDA_LIB_DIR):
            messagebox.showinfo(
                APP_NAME,
                f"CUDA-библиотеки уже установлены.\n\n{CUDA_LIB_DIR}",
            )
            self.device.set(self._device_summary())
            return

        confirmed = messagebox.askyesno(
            APP_NAME,
            "Для GPU нужно скачать CUDA 12 + cuDNN 9.\n\n"
            "Размер загрузки — около 810 МБ.\n"
            "Файлы сохранятся только для текущего пользователя.\n\n"
            "Скачать и установить сейчас?",
        )
        if not confirmed:
            return

        self._set_busy(True)
        self.open_file_button.configure(state="disabled")
        self.progress["value"] = 0
        self.status.set("Подготовка установки GPU…")
        threading.Thread(target=self._gpu_worker, daemon=True).start()

    def _gpu_worker(self) -> None:
        try:
            count = install_cuda_runtime(
                progress_callback=lambda value: self.events.put(
                    ("gpu_progress", value)
                ),
                status_callback=lambda text: self.events.put(
                    ("gpu_status", text)
                ),
            )
            self.events.put(("gpu_done", count))
        except Exception as exc:
            logging.error("CUDA setup error\n%s", traceback.format_exc())
            self.events.put(("gpu_error", str(exc)))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind in {"progress", "gpu_progress"}:
                    self.progress["value"] = int(payload)
                elif kind in {"status", "gpu_status"}:
                    self.status.set(str(payload))
                elif kind == "done":
                    output_path, device_name = payload  # type: ignore[misc]
                    self.last_output = Path(output_path)
                    self.progress["value"] = 100
                    self.status.set(f"Готово: {self.last_output.name}")
                    self.device.set(f"Обработано на {device_name}")
                    self._set_busy(False)
                    self.open_file_button.configure(state="normal")
                    messagebox.showinfo(
                        APP_NAME,
                        f"Транскрипция готова.\n\n{self.last_output}",
                    )
                elif kind == "error":
                    self.status.set("Ошибка")
                    self._set_busy(False)
                    self.device.set(self._device_summary())
                    messagebox.showerror(
                        APP_NAME,
                        "Не удалось выполнить транскрибацию:\n\n"
                        f"{payload}\n\nЛог: {LOG_DIR / 'desktop.log'}",
                    )
                elif kind == "gpu_done":
                    self.engine.unload()
                    self.engine.refresh_gpu()
                    self.progress["value"] = 100
                    self.status.set("GPU настроена")
                    self.device.set(self._device_summary())
                    self._set_busy(False)
                    messagebox.showinfo(
                        APP_NAME,
                        f"CUDA 12/cuDNN 9 установлены.\n"
                        f"DLL-файлов: {payload}\n\n"
                        f"{CUDA_LIB_DIR}\n\n"
                        "Теперь транскрибация попробует NVIDIA GPU.",
                    )
                elif kind == "gpu_error":
                    self.status.set("Ошибка настройки GPU")
                    self.device.set(self._device_summary())
                    self._set_busy(False)
                    messagebox.showerror(
                        APP_NAME,
                        "Не удалось автоматически настроить GPU:\n\n"
                        f"{payload}\n\nЛог: {LOG_DIR / 'desktop.log'}",
                    )
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def _open_result(self) -> None:
        if not self.last_output or not self.last_output.is_file():
            return
        try:
            os.startfile(str(self.last_output))  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    DesktopApp().run()
