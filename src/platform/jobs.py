from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class QueryJob:
    id: str
    status: str
    kind: str
    pool: str
    created_at: str
    progress: int = 0
    total: int = 0
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    # 换池或再点刷新时由接口置位。取数循环看到它就停，不再给已经离开的那一池打行情。
    cancel_event: threading.Event = field(default_factory=threading.Event)


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, QueryJob] = {}

    def create(self, kind: str, pool: str, total: int) -> QueryJob:
        job = QueryJob(
            id=uuid.uuid4().hex[:12],
            status="running",
            kind=kind,
            pool=pool,
            created_at=datetime.now().isoformat(timespec="seconds"),
            total=total,
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> QueryJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def finish(self, job_id: str, result: dict) -> None:
        with self._lock:
            job = self._jobs[job_id]
            # 已经取消的任务不能再被收成 done，否则旧池的结果会盖住新池。
            if job.status != "running":
                return
            job.status = "done"
            job.progress = job.total
            job.result = result

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.status != "running":
                return
            job.status = "error"
            job.error = error

    def advance(self, job_id: str, step: int = 1) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "running":
                return
            job.progress = min(job.total, job.progress + max(0, int(step)))

    def request_cancel(self, job_id: str) -> QueryJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.cancel_event.set()
            if job.status == "running":
                job.status = "cancelled"
                job.error = "已取消"
            return job

    def spawn(self, target: Callable, *args) -> None:
        threading.Thread(target=target, args=args, daemon=True).start()


jobs = JobStore()


def job_payload(job: QueryJob) -> dict:
    body = {
        "job_id": job.id,
        "status": job.status,
        "kind": job.kind,
        "pool": job.pool,
        "progress": job.progress,
        "total": job.total,
        "error": job.error,
        "created_at": job.created_at,
    }
    if job.status == "done":
        body.update(job.result)
    return body
