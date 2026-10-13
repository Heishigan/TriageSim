"""Background jobs (case building, model downloads, experiment runs) with progress."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable

from ..logs import log


@dataclass
class Job:
    id: str
    kind: str
    label: str
    state: str = "running"          # running | done | failed | stopped
    progress: dict = field(default_factory=dict)
    result: dict | None = None
    error: str | None = None
    started: float = field(default_factory=time.time)
    stop: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "state": self.state,
                "progress": self.progress, "result": self.result, "error": self.error,
                "seconds": round(time.time() - self.started, 1)}


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, label: str, work: Callable[[Job], dict | None], job_id: str | None = None) -> Job:
        job = Job(id=job_id or uuid.uuid4().hex[:12], kind=kind, label=label)

        def runner():
            try:
                job.result = work(job)
                job.state = "stopped" if job.stop.is_set() else "done"
            except Exception as exc:  # report, never crash the server
                job.state, job.error = "failed", f"{exc}"
                job.progress["trace"] = traceback.format_exc(limit=3)
                log.error("%s '%s' failed: %s\n%s", kind, label, exc, traceback.format_exc(limit=6))

        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=runner, daemon=True, name=f"job-{kind}-{job.id}").start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def running(self, kind: str | None = None) -> list[Job]:
        return [j for j in self._jobs.values() if j.state == "running" and (kind is None or j.kind == kind)]

    def all(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.started, reverse=True)
