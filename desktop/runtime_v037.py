from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import downloader as core
from platforms import detect_platform


class OperationCancelled(RuntimeError):
    pass


_SELECTED_BROWSER: str | None = None
_PATCH_LOCK = threading.Lock()


def _cancelled(event: threading.Event | None) -> bool:
    return bool(event and event.is_set())


def _raise_if_cancelled(event: threading.Event | None) -> None:
    if _cancelled(event):
        raise OperationCancelled("Операция отменена пользователем.")


def _browser_cookie_sources() -> list[tuple[str, str]]:
    """Return installed browsers in a useful retry order for yt-dlp cookies."""
    found: list[tuple[str, str]] = []
    home = Path.home()

    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", home))
        roaming = Path(os.environ.get("APPDATA", home))
        candidates = [
            ("chrome", "Google Chrome", local / "Google" / "Chrome" / "User Data"),
            ("edge", "Microsoft Edge", local / "Microsoft" / "Edge" / "User Data"),
            ("brave", "Brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
            ("firefox", "Firefox", roaming / "Mozilla" / "Firefox"),
        ]
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
        candidates = [
            ("chrome", "Google Chrome", base / "Google" / "Chrome"),
            ("edge", "Microsoft Edge", base / "Microsoft Edge"),
            ("brave", "Brave", base / "BraveSoftware" / "Brave-Browser"),
            ("firefox", "Firefox", base / "Firefox"),
        ]
    else:
        candidates = [
            ("chrome", "Google Chrome", home / ".config" / "google-chrome"),
            ("chromium", "Chromium", home / ".config" / "chromium"),
            ("brave", "Brave", home / ".config" / "BraveSoftware" / "Brave-Browser"),
            ("firefox", "Firefox", home / ".mozilla" / "firefox"),
        ]

    for key, label, path in candidates:
        if path.exists():
            found.append((key, label))
    return found


def _looks_like_auth_error(text: str) -> bool:
    value = (text or "").lower()
    needles = (
        "sign in to confirm",
        "not a bot",
        "login required",
        "authentication",
        "cookies-from-browser",
        "private video",
    )
    return any(needle in value for needle in needles)


def _run_capture_cancellable(
    command: list[str],
    *,
    timeout_seconds: int,
    log: Callable[[str], None],
    cancel_event: threading.Event | None,
) -> tuple[int, str, str, bool]:
    log("$ " + subprocess.list2cmdline(command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=core._creation_flags(),
    )
    deadline = time.monotonic() + timeout_seconds
    while True:
        if _cancelled(cancel_event):
            core._terminate_process_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=2)
            except Exception:
                stdout, stderr = "", ""
            raise OperationCancelled("Операция отменена пользователем.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            core._terminate_process_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=2)
            except Exception:
                stdout, stderr = "", ""
            return -9, stdout, stderr, True
        try:
            stdout, stderr = process.communicate(timeout=min(0.25, remaining))
            return process.returncode or 0, stdout, stderr, False
        except subprocess.TimeoutExpired:
            continue


def _streaming_runner(cancel_event: threading.Event | None):
    def run(
        command: list[str],
        *,
        status: Callable[[str], None],
        progress: Callable[[int], None],
        log: Callable[[str], None],
        cwd: Path | None = None,
    ) -> int:
        _raise_if_cancelled(cancel_event)
        log("$ " + subprocess.list2cmdline(command))
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=core._creation_flags(),
        )
        lines: queue.Queue[str | None] = queue.Queue()

        def reader() -> None:
            try:
                assert process.stdout is not None
                for raw in process.stdout:
                    lines.put(raw)
            finally:
                lines.put(None)

        threading.Thread(target=reader, daemon=True).start()
        percent_re = re.compile(r"(?:\[download\]\s+)?([0-9]{1,3}(?:\.[0-9]+)?)%")
        reader_done = False
        while True:
            if _cancelled(cancel_event):
                log("[cancel] Останавливаю активный процесс и его дочерние процессы…")
                core._terminate_process_tree(process)
                raise OperationCancelled("Операция отменена пользователем.")

            try:
                item = lines.get(timeout=0.15)
            except queue.Empty:
                item = ""

            if item is None:
                reader_done = True
            elif item:
                line = item.rstrip()
                if line:
                    log(line)
                    match = percent_re.search(line)
                    if match:
                        try:
                            progress(max(0, min(98, int(float(match.group(1))))))
                        except ValueError:
                            pass
                    elif "Destination:" in line or "Merging formats" in line:
                        status("Скачивание и сборка файла…")

            if process.poll() is not None and reader_done:
                return process.returncode or 0

    return run


def analyze_media(
    url: str,
    *,
    app_root: Path | None = None,
    status: Callable[[str], None] = lambda _s: None,
    progress: Callable[[int], None] = lambda _p: None,
    log: Callable[[str], None] = lambda _s: None,
    timeout_seconds: int = 12,
    cancel_event: threading.Event | None = None,
) -> core.MediaAnalysis:
    global _SELECTED_BROWSER

    url = (url or "").strip()
    if not url:
        raise ValueError("Вставь ссылку.")

    _raise_if_cancelled(cancel_event)
    root = app_root or Path(__file__).resolve().parent
    tools = core.resolve_tools(root)
    platform = detect_platform(url)
    progress(5)

    common = core._common_ytdlp_args(tools, root) + [
        "--socket-timeout", "7",
        "--retries", "1",
        "--extractor-retries", "1",
        "--fragment-retries", "1",
        "--skip-download",
        "--dump-single-json",
    ]

    attempts: list[tuple[str, list[str], int, str | None]] = [
        ("обычный клиент", [], timeout_seconds, None),
    ]
    if platform == "YouTube":
        attempts.append((
            "резервный YouTube-клиент",
            ["--extractor-args", "youtube:player_client=web_embedded"],
            8,
            None,
        ))
        if not core._cookies_args(root):
            sources = _browser_cookie_sources()
            if _SELECTED_BROWSER:
                sources.sort(key=lambda item: item[0] != _SELECTED_BROWSER)
            for source, label in sources:
                attempts.append((
                    f"авторизация через {label}",
                    ["--cookies-from-browser", source],
                    12,
                    source,
                ))

    errors: list[str] = []
    had_timeout = False
    auth_seen = False

    for index, (label, extra, timeout, browser_source) in enumerate(attempts, start=1):
        _raise_if_cancelled(cancel_event)
        status(f"Анализ форматов · попытка {index}/{len(attempts)} · {label}")
        log(f"[analysis] Попытка {index}/{len(attempts)}: {label}; таймаут {timeout} с")
        if browser_source:
            log(f"[auth] YouTube запросил вход; пробую cookies из браузера: {browser_source}")
        code, stdout, stderr, timed_out = _run_capture_cancellable(
            common + extra + [url],
            timeout_seconds=timeout,
            log=log,
            cancel_event=cancel_event,
        )
        had_timeout = had_timeout or timed_out

        if stderr.strip():
            auth_seen = auth_seen or _looks_like_auth_error(stderr)
            for line in stderr.splitlines():
                if line.strip():
                    log(line.rstrip())
            errors.append(stderr.strip())

        if stdout.strip():
            try:
                info = core._parse_json_output(stdout)
                choices = core.quality_choices_from_info(info)
                default_label = core._default_quality_label(choices)
                if browser_source:
                    _SELECTED_BROWSER = browser_source
                    log(f"[auth] Cookies из {browser_source} сработали; использую их для загрузки.")
                progress(100)
                status(f"Форматы получены · вариантов: {len(choices)}")
                return core.MediaAnalysis(
                    platform=platform,
                    title=str(info.get("title") or ""),
                    choices=choices,
                    default_label=default_label,
                )
            except Exception as exc:
                errors.append(str(exc))
                log(f"[analysis] Ответ получен, но не разобран: {exc}")

        if timed_out:
            log(f"[analysis] Попытка {index} остановлена по таймауту.")
        elif code != 0:
            log(f"[analysis] yt-dlp завершился с кодом {code}.")

    if platform == "YouTube" and auth_seen:
        installed = ", ".join(label for _key, label in _browser_cookie_sources())
        if installed:
            raise RuntimeError(
                "YouTube требует авторизацию. Программа автоматически попробовала cookies из "
                f"установленных браузеров ({installed}), но не получила рабочую сессию. "
                "Войди в YouTube в одном из этих браузеров, обнови страницу YouTube и нажми «Проверить ещё раз»."
            )
        raise RuntimeError(
            "YouTube требует авторизацию. На этом компьютере не найден поддерживаемый браузер с cookies. "
            "Установи Chrome, Edge, Brave или Firefox, войди в YouTube и повтори проверку."
        )

    raise RuntimeError(core._friendly_analysis_error(errors, had_timeout))


def _with_browser_cookies(source: str | None):
    class Patch:
        def __enter__(self):
            self.old = core._cookies_args
            if source:
                core._cookies_args = lambda _root: ["--cookies-from-browser", source]
            return self

        def __exit__(self, exc_type, exc, tb):
            core._cookies_args = self.old
            return False

    return Patch()


def download_media(
    url: str,
    output_root: Path,
    *,
    status: Callable[[str], None] = lambda _s: None,
    progress: Callable[[int], None] = lambda _p: None,
    log: Callable[[str], None] = lambda _s: None,
    app_root: Path | None = None,
    quality: str = "1080p — MP4 H.264 + AAC",
    clip_start: float | None = None,
    clip_end: float | None = None,
    cancel_event: threading.Event | None = None,
) -> list[Path]:
    global _SELECTED_BROWSER

    _raise_if_cancelled(cancel_event)
    root = app_root or Path(__file__).resolve().parent
    platform = detect_platform((url or "").strip())
    original_streaming = core._run_streaming
    core._run_streaming = _streaming_runner(cancel_event)

    try:
        if platform != "YouTube" or core._cookies_args(root):
            return core.download_media(
                url,
                output_root,
                status=status,
                progress=progress,
                log=log,
                app_root=root,
                quality=quality,
                clip_start=clip_start,
                clip_end=clip_end,
            )

        sources = _browser_cookie_sources()
        ordered: list[str | None] = [None]
        if _SELECTED_BROWSER:
            ordered.append(_SELECTED_BROWSER)
        ordered += [key for key, _label in sources if key != _SELECTED_BROWSER]

        last_error: Exception | None = None
        with _PATCH_LOCK:
            for source in ordered:
                _raise_if_cancelled(cancel_event)
                try:
                    if source:
                        label = next((label for key, label in sources if key == source), source)
                        status(f"YouTube требует вход · пробую {label}…")
                        log(f"[auth] Повтор загрузки с cookies из браузера: {source}")
                    with _with_browser_cookies(source):
                        outputs = core.download_media(
                            url,
                            output_root,
                            status=status,
                            progress=progress,
                            log=log,
                            app_root=root,
                            quality=quality,
                            clip_start=clip_start,
                            clip_end=clip_end,
                        )
                    if source:
                        _SELECTED_BROWSER = source
                    return outputs
                except OperationCancelled:
                    raise
                except Exception as exc:
                    last_error = exc
                    if source is None or _looks_like_auth_error(str(exc)):
                        continue
                    log(f"[auth] {source} не дал рабочую YouTube-сессию: {exc}")
                    continue

        installed = ", ".join(label for _key, label in sources)
        suffix = (
            f" Программа попробовала: {installed}. Войди в YouTube в одном из этих браузеров и повтори."
            if installed
            else " Войди в YouTube в Chrome, Edge, Brave или Firefox и повтори."
        )
        raise RuntimeError("YouTube не дал скачать видео без авторизации." + suffix) from last_error
    finally:
        core._run_streaming = original_streaming
