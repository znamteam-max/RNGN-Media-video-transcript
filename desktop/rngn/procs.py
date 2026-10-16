"""Child processes that can be cancelled and are never left running after exit."""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

LogCallback = Callable[[str], None]


class OperationCancelled(RuntimeError):
    def __init__(self, message: str = "Операция отменена.") -> None:
        super().__init__(message)


def creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def terminate_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags(),
                timeout=5,
            )
        else:
            process.kill()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


_live: set[subprocess.Popen] = set()
_live_lock = threading.Lock()


def _register(process: subprocess.Popen) -> None:
    with _live_lock:
        _live.add(process)


def _unregister(process: subprocess.Popen) -> None:
    with _live_lock:
        _live.discard(process)


def kill_all() -> None:
    """Stop every child process this app started (used when the window closes)."""
    with _live_lock:
        processes = list(_live)
    for process in processes:
        terminate_tree(process)


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._processes: set[subprocess.Popen] = set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            terminate_tree(process)

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelled()

    def wait(self, seconds: float) -> bool:
        return self._event.wait(seconds)

    def attach(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._processes.add(process)
        if self._event.is_set():
            terminate_tree(process)

    def detach(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._processes.discard(process)


NEVER = CancelToken()


def _popen(command: list[str], *, cwd: Path | None, merge_stderr: bool) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags(),
    )


def run_capture(
    command: list[str],
    *,
    timeout: float,
    log: LogCallback = lambda _s: None,
    token: CancelToken = NEVER,
) -> tuple[int, str, str, bool]:
    """Run to completion, return (code, stdout, stderr, timed_out)."""
    token.raise_if_cancelled()
    log("$ " + subprocess.list2cmdline(command))
    process = _popen(command, cwd=None, merge_stderr=False)
    _register(process)
    token.attach(process)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if token.cancelled:
                terminate_tree(process)
                raise OperationCancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate_tree(process)
                try:
                    stdout, stderr = process.communicate(timeout=3)
                except Exception:
                    stdout, stderr = "", ""
                return -9, stdout or "", stderr or "", True
            try:
                stdout, stderr = process.communicate(timeout=min(0.25, remaining))
            except subprocess.TimeoutExpired:
                continue
            if token.cancelled:  # killed by cancel() while we were waiting
                raise OperationCancelled()
            return process.returncode or 0, stdout or "", stderr or "", False
    finally:
        token.detach(process)
        _unregister(process)


def run_streaming(
    command: list[str],
    *,
    on_line: Callable[[str], None],
    log: LogCallback = lambda _s: None,
    token: CancelToken = NEVER,
    cwd: Path | None = None,
) -> int:
    """Run with stdout+stderr merged; every non-empty line goes to `on_line`."""
    token.raise_if_cancelled()
    log("$ " + subprocess.list2cmdline(command))
    process = _popen(command, cwd=cwd, merge_stderr=True)
    _register(process)
    token.attach(process)
    lines: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        try:
            assert process.stdout is not None
            for raw in process.stdout:
                lines.put(raw)
        finally:
            lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    try:
        while True:
            if token.cancelled:
                terminate_tree(process)
                raise OperationCancelled()
            try:
                item = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                code = process.wait()
                if token.cancelled:  # killed by cancel() while we were reading
                    raise OperationCancelled()
                return code
            line = item.rstrip()
            if line:
                on_line(line)
    finally:
        if process.poll() is None:
            terminate_tree(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        if process.stdout is not None:
            try:
                process.stdout.close()
            except OSError:
                pass
        token.detach(process)
        _unregister(process)


class Report:
    """Where a long operation sends its stage text, progress (None = unknown) and log lines."""

    def __init__(
        self,
        status: Callable[[str], None] | None = None,
        progress: Callable[[float | None], None] | None = None,
        log: LogCallback | None = None,
    ) -> None:
        self.status = status or (lambda _s: None)
        self.progress = progress or (lambda _p: None)
        self.log = log or (lambda _s: None)


QUIET = Report()
