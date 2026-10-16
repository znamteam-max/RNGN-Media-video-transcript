"""Job queue: downloads run in one lane, transcription/conversion in another, so both
can work at the same time. Every job can be cancelled, retried and is kept in history."""
from __future__ import annotations

import json
import queue
import threading
import time
import traceback
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import converter, downloader, errors, gpu, paths, subtitles, transcriber
from .errors import UserFacingError
from .procs import CancelToken, OperationCancelled, Report, kill_all
from .settings import Settings
from .tools import Access

LANES = {
    "download": "net",
    "subtitles": "net",
    "transcribe": "work",
    "convert": "work",
    "gpu_setup": "setup",
}
ACTIVE_STATES = {"queued", "running"}
HISTORY_LIMIT = 200


@dataclass
class Job:
    id: str
    kind: str
    title: str
    params: dict
    meta: dict = field(default_factory=dict)
    state: str = "queued"
    progress: float | None = 0.0
    stage: str = "В очереди"
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    outputs: list[str] = field(default_factory=list)
    summary: str = ""
    error: dict | None = None
    parent: str | None = None
    log: deque = field(default_factory=lambda: deque(maxlen=4000))
    log_seq: int = 0
    token: CancelToken = field(default_factory=CancelToken)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "meta": self.meta,
            "state": self.state,
            "progress": None if self.progress is None else round(self.progress, 1),
            "stage": self.stage,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "outputs": self.outputs,
            "summary": self.summary,
            "error": self.error,
            "parent": self.parent,
            "log_seq": self.log_seq,
            "params": self.params,
        }

    @classmethod
    def from_history(cls, data: dict) -> "Job":
        job = cls(
            id=str(data.get("id") or uuid.uuid4().hex[:8]),
            kind=str(data.get("kind") or "download"),
            title=str(data.get("title") or ""),
            params=dict(data.get("params") or {}),
            meta=dict(data.get("meta") or {}),
        )
        job.state = str(data.get("state") or "done")
        job.progress = data.get("progress")
        job.stage = str(data.get("stage") or "")
        job.created = float(data.get("created") or time.time())
        job.started = data.get("started")
        job.finished = data.get("finished")
        job.outputs = [str(item) for item in data.get("outputs") or []]
        job.summary = str(data.get("summary") or "")
        job.error = data.get("error")
        job.parent = data.get("parent")
        return job


class JobManager:
    def __init__(self, settings: Settings, emit: Callable[[dict], None]) -> None:
        self.settings = settings
        self.emit = emit
        self.jobs: "OrderedDict[str, Job]" = OrderedDict()
        self._lock = threading.RLock()
        self._dirty: set[str] = set()
        self._queues: dict[str, queue.Queue[str]] = {lane: queue.Queue() for lane in set(LANES.values())}
        self._closing = threading.Event()
        self.history_file = paths.data_dir() / "history.json"
        self._load_history()
        for lane, lane_queue in self._queues.items():
            threading.Thread(target=self._lane_worker, args=(lane_queue,), name=f"lane-{lane}", daemon=True).start()
        threading.Thread(target=self._pump, name="job-events", daemon=True).start()

    # ---- public API -------------------------------------------------------------------

    def submit(self, kind: str, title: str, params: dict, *, meta: dict | None = None, parent: str | None = None) -> Job:
        if kind not in LANES:
            raise ValueError(f"unknown job kind {kind}")
        job = Job(id=uuid.uuid4().hex[:10], kind=kind, title=title or "Задание", params=params, meta=meta or {},
                  parent=parent)
        with self._lock:
            self.jobs[job.id] = job
            self._dirty.add(job.id)
        self._queues[LANES[kind]].put(job.id)
        return job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job or job.state not in ACTIVE_STATES:
                return False
            job.token.cancel()
            if job.state == "queued":
                self._finish(job, "cancelled", stage="Отменено")
            else:
                job.stage = "Отменяю…"
                self._dirty.add(job.id)
        return True

    def retry(self, job_id: str) -> Job | None:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job or job.state in ACTIVE_STATES:
                return None
            return self.submit(job.kind, job.title, dict(job.params), meta=dict(job.meta))

    def remove(self, job_id: str) -> bool:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job or job.state in ACTIVE_STATES:
                return False
            del self.jobs[job_id]
        self._save_history()
        self.emit({"type": "job_removed", "id": job_id})
        return True

    def clear_finished(self) -> int:
        with self._lock:
            finished = [job_id for job_id, job in self.jobs.items() if job.state not in ACTIVE_STATES]
            for job_id in finished:
                del self.jobs[job_id]
        self._save_history()
        self.emit({"type": "jobs_reset", "jobs": self.list()})
        return len(finished)

    def list(self) -> list[dict]:
        with self._lock:
            return [job.to_dict() for job in reversed(self.jobs.values())]

    def log(self, job_id: str, since: int = 0) -> dict:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return {"lines": [], "seq": 0}
            lines = list(job.log)
            seq = job.log_seq
        start = max(0, len(lines) - max(0, seq - since)) if since else 0
        return {"lines": lines[start:], "seq": seq}

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for job in self.jobs.values() if job.state in ACTIVE_STATES)

    def shutdown(self) -> None:
        self._closing.set()
        with self._lock:
            for job in self.jobs.values():
                if job.state in ACTIVE_STATES:
                    job.token.cancel()
        kill_all()
        self._save_history()

    # ---- internals --------------------------------------------------------------------

    def _report(self, job: Job) -> Report:
        def status(text: str) -> None:
            with self._lock:
                if job.stage != text:
                    job.stage = text
                    self._dirty.add(job.id)

        def progress(value: float | None) -> None:
            with self._lock:
                job.progress = None if value is None else max(0.0, min(100.0, float(value)))
                self._dirty.add(job.id)

        def log(line: str) -> None:
            with self._lock:
                job.log.append(f"{time.strftime('%H:%M:%S')}  {line}")
                job.log_seq += 1

        return Report(status, progress, log)

    def _finish(self, job: Job, state: str, *, stage: str = "", error: dict | None = None) -> None:
        job.state = state
        job.finished = time.time()
        if stage:
            job.stage = stage
        job.error = error
        if state == "done":
            job.progress = 100.0
        self._dirty.add(job.id)
        threading.Thread(target=self._save_history, daemon=True).start()

    def _lane_worker(self, lane_queue: "queue.Queue[str]") -> None:
        while not self._closing.is_set():
            try:
                job_id = lane_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            with self._lock:
                job = self.jobs.get(job_id)
                if not job or job.state != "queued":
                    continue
                job.state = "running"
                job.started = time.time()
                job.stage = "Начинаю…"
                self._dirty.add(job.id)
            report = self._report(job)
            try:
                outputs, summary = self._execute(job, report)
                with self._lock:
                    job.outputs = [str(path) for path in outputs]
                    job.summary = summary
                    self._finish(job, "done", stage=summary or "Готово")
                self.emit({"type": "job_done", "id": job.id, "title": job.title, "summary": job.summary})
                self._after_done(job)
            except OperationCancelled:
                with self._lock:
                    self._finish(job, "cancelled", stage="Отменено")
            except UserFacingError as exc:
                report.log(f"ОШИБКА: {exc}")
                if exc.details:
                    report.log(exc.details)
                with self._lock:
                    self._finish(job, "error", stage=str(exc),
                                 error={"message": str(exc), "hint": exc.hint, "kind": exc.kind})
            except Exception as exc:
                report.log("ОШИБКА: " + "".join(traceback.format_exception(exc)).strip())
                kind = errors.classify(str(exc))
                message, hint = errors.friendly(kind)
                with self._lock:
                    self._finish(job, "error", stage=message, error={"message": message, "hint": hint, "kind": kind})

    def _pump(self) -> None:
        while not self._closing.is_set():
            time.sleep(0.15)
            with self._lock:
                if not self._dirty:
                    continue
                payload = [self.jobs[job_id].to_dict() for job_id in self._dirty if job_id in self.jobs]
                self._dirty.clear()
            if payload:
                try:
                    self.emit({"type": "jobs", "jobs": payload})
                except Exception:
                    pass

    def _output_root(self, params: dict) -> Path:
        value = params.get("output_root") or self.settings.get("output_root")
        return Path(value).expanduser() if value else self.settings.output_root

    def _execute(self, job: Job, report: Report) -> tuple[list[Path], str]:
        params = job.params
        token = job.token
        if job.kind == "download":
            clip = params.get("clip")
            request = downloader.DownloadRequest(
                url=params["url"],
                output_root=self._output_root(params),
                mode=params.get("mode", "video"),
                height=params.get("height"),
                exact=bool(params.get("exact")),
                audio_format=params.get("audio_format", "mp3"),
                clip=(float(clip[0]), float(clip[1])) if clip else None,
                access=Access.from_dict(params.get("access")),
                gpu_encoder=bool(self.settings.get("gpu_encoder", default=True)),
            )
            outputs = downloader.download_media(request, token=token, report=report)
            names = ", ".join(path.name for path in outputs[:2])
            more = f" и ещё {len(outputs) - 2}" if len(outputs) > 2 else ""
            return outputs, f"Сохранено: {names}{more}"
        if job.kind == "subtitles":
            track = subtitles.SubtitleTrack.from_dict(params["track"])
            outputs = subtitles.download_subtitle(
                params["url"],
                track,
                self._output_root(params) / "Subtitles",
                formats=tuple(params.get("formats") or ("txt", "srt")),
                title_hint=params.get("title") or job.title,
                token=token,
                report=report,
            )
            return outputs, "Сохранено: " + " + ".join(path.suffix.lstrip(".").upper() for path in outputs)
        if job.kind == "transcribe":
            result = transcriber.transcribe_media(
                Path(params["file"]),
                self._output_root(params) / "Transcripts",
                model_key=params.get("model", "turbo"),
                language_id=params.get("language", "mixed"),
                with_timestamps=bool(params.get("timestamps")),
                formats=tuple(params.get("formats") or ("txt", "srt")),
                allow_gpu=bool(params.get("use_gpu", True)),
                token=token,
                report=report,
            )
            return result.outputs, result.summary()
        if job.kind == "convert":
            output = converter.convert_media(
                Path(params["file"]),
                params.get("profile", "premiere"),
                self._output_root(params) / "Converted",
                gpu_encoder=bool(self.settings.get("gpu_encoder", default=True)),
                token=token,
                report=report,
            )
            return [output], f"Сохранено: {output.name}"
        if job.kind == "gpu_setup":
            folder = gpu.install(token=token, report=report)
            self.emit({"type": "gpu", "status": gpu.status()})
            return [folder], "Ускорение NVIDIA включено"
        raise ValueError(f"unknown job kind {job.kind}")

    def _after_done(self, job: Job) -> None:
        """Download with «сразу расшифровать» queues the transcription of the result."""
        follow = job.params.get("transcribe_after")
        if job.kind != "download" or not follow:
            return
        media = [
            Path(path) for path in job.outputs
            if Path(path).suffix.lower() in transcriber.SUPPORTED_EXTENSIONS
        ]
        if not media:
            return
        options = follow if isinstance(follow, dict) else self.settings.get("transcribe", default={})
        params = {
            "file": str(media[0]),
            "model": options.get("model", "turbo"),
            "language": options.get("language", "mixed"),
            "timestamps": bool(options.get("timestamps")),
            "formats": options.get("formats") or ["txt", "srt"],
            "use_gpu": bool(options.get("use_gpu", True)),
            "output_root": job.params.get("output_root"),
        }
        self.submit("transcribe", job.title, params, meta={**job.meta, "file": str(media[0])}, parent=job.id)

    def _load_history(self) -> None:
        try:
            items = json.loads(self.history_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(items, list):
            return
        for item in reversed(items[:HISTORY_LIMIT]):
            if isinstance(item, dict):
                job = Job.from_history(item)
                if job.state in ACTIVE_STATES:
                    job.state = "error"
                    job.error = {"message": "Программа была закрыта во время работы.", "hint": "Нажми «Повторить».",
                                 "kind": "cancelled"}
                self.jobs[job.id] = job

    def _save_history(self) -> None:
        with self._lock:
            items = [job.to_dict() for job in reversed(self.jobs.values()) if job.state not in ACTIVE_STATES]
        try:
            tmp = self.history_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(items[:HISTORY_LIMIT], ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.history_file)
        except OSError:
            pass
