"""Persistent job queue for the unified app (survives restarts) and the runner that feeds the backend.

States: pending → running → done | failed | cancelled. A job left "running" by a closed/crashed app returns to
pending on the next start. Pause is job-level: the running image finishes, the queue stops before the next job.
When the backend reports that the PC is short of GPU/RAM, the job stays pending with the reason and is retried
after ``recheck_seconds`` — nothing is killed. Only one backend job runs at a time.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .settings import atomic_write_json, data_dir, quarantine

PENDING, RUNNING, DONE, FAILED, CANCELLED = "pending", "running", "done", "failed", "cancelled"
STATE_LABELS = {PENDING: "대기", RUNNING: "생성 중", DONE: "완료", FAILED: "실패", CANCELLED: "취소됨"}


@dataclass
class Job:
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: str = PENDING
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    waiting_reason: str = ""
    progress: float = 0.0
    message: str = ""
    chosen: int | None = None          # candidate index sent to the editor


class JobQueue:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else data_dir() / "queue.json"
        self.lock = threading.RLock()
        self.jobs: list[Job] = []
        self.paused = False
        self.recovered_note = ""
        self.load()

    def load(self) -> None:
        with self.lock:
            if not self.path.exists():
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                jobs = [Job(**{k: v for k, v in item.items() if k in Job.__dataclass_fields__}) for item in data["jobs"]]
            except (OSError, ValueError, KeyError, TypeError):
                kept = quarantine(self.path)
                self.recovered_note = f"대기열 파일이 손상되어 새로 시작했습니다(원본: {kept.name})."
                self.jobs, self.paused = [], False
                return
            self.paused = bool(data.get("paused"))
            self.jobs = jobs
            for job in self.jobs:
                if job.state == RUNNING:          # app closed mid-job: run it again
                    job.state, job.started, job.progress, job.message = PENDING, None, 0.0, "다시 시작 대기"
            self.save()

    def save(self) -> None:
        with self.lock:
            atomic_write_json(self.path, {"version": 1, "paused": self.paused, "jobs": [asdict(j) for j in self.jobs]})

    def add(self, payload: dict[str, Any]) -> Job:
        with self.lock:
            job = Job(payload=payload)
            self.jobs.append(job)
            self.save()
            return job

    def get(self, job_id: str) -> Job | None:
        return next((job for job in self.jobs if job.id == job_id), None)

    def pending(self) -> list[Job]:
        return [job for job in self.jobs if job.state == PENDING]

    def cancel(self, job_id: str) -> bool:
        with self.lock:
            job = self.get(job_id)
            if job is None or job.state != PENDING:
                return False
            job.state, job.finished = CANCELLED, time.time()
            self.save()
            return True

    def retry(self, job_id: str) -> bool:
        with self.lock:
            job = self.get(job_id)
            if job is None or job.state not in (FAILED, CANCELLED):
                return False
            job.state, job.error, job.result, job.started, job.finished = PENDING, None, None, None, None
            job.progress, job.message = 0.0, ""
            self.save()
            return True

    def remove(self, ids: list[str]) -> int:
        with self.lock:
            before = len(self.jobs)
            self.jobs = [j for j in self.jobs if j.id not in ids or j.state == RUNNING]
            self.save()
            return before - len(self.jobs)

    def set_paused(self, paused: bool) -> None:
        with self.lock:
            self.paused = paused
            self.save()


class Runner:
    """One job at a time on a background thread. ``execute(job) -> JobOutcome`` talks to the backend."""

    def __init__(self, queue: JobQueue, execute: Callable[[Job], Any], on_change: Callable[[], None] | None = None,
                 recheck_seconds: float = 20.0):
        self.queue = queue
        self.execute = execute
        self.on_change = on_change or (lambda: None)
        self.recheck_seconds = recheck_seconds
        self.status = "대기열 정지"
        self.current: Job | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.cancel_current: Callable[[], None] = lambda: None
        self.closing = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self.queue.set_paused(False)
        if not self.running:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="studio-queue", daemon=True)
            self._thread.start()
        self._wake.set()
        self.on_change()

    def pause_after_current(self) -> None:
        self.queue.set_paused(True)
        self.status = "현재 작업 후 일시정지" if self.current else "일시정지됨"
        self.on_change()

    def shutdown(self) -> None:
        """App closing: the running job is stopped and returns to pending (it runs again after restart)."""
        self.closing = True
        self._stop.set()
        self._wake.set()
        if self.current is not None:
            self.cancel_current()

    def poke(self) -> None:
        self._wake.set()

    def run_next(self) -> str:
        with self.queue.lock:
            if self.queue.paused:
                return "paused"
            pending = self.queue.pending()
            if not pending:
                return "empty"
            job = pending[0]
            job.state, job.started, job.message, job.progress = RUNNING, time.time(), "시작", 0.0
            self.queue.save()
        self.current = job
        self.status = "생성 중"
        self.on_change()
        try:
            outcome = self.execute(job)
        except Exception as exc:  # never lose the queue
            outcome = type("O", (), {"status": "failed", "result": {}, "reasons": [],
                                     "error": {"code": "UNKNOWN", "message": str(exc), "action": "'실패 재시도'를 눌러 주세요."}})()
        with self.queue.lock:
            self.current = None
            if self.closing and outcome.status in ("cancelled", "failed"):
                job.state, job.started, job.message, job.progress = PENDING, None, "다시 시작 대기", 0.0
                result = "closing"
            elif outcome.status == "waiting":
                job.state, job.started = PENDING, None
                job.waiting_reason = "; ".join(outcome.reasons) or "PC 자원 부족"
                job.message = "PC 사용 중 — 자원 대기"
                result = "waiting"
            elif outcome.status == "done":
                job.state, job.result, job.finished, job.progress = DONE, outcome.result, time.time(), 1.0
                job.waiting_reason, job.message = "", "완료"
                result = "ran"
            elif outcome.status == "cancelled":
                job.state, job.finished, job.message = CANCELLED, time.time(), "취소됨"
                result = "ran"
            else:
                job.state, job.error, job.finished = FAILED, outcome.error, time.time()
                job.message = (outcome.error or {}).get("message", "실패")
                result = "ran"
            self.queue.save()
        self.on_change()
        return result

    def _loop(self) -> None:
        while not self._stop.is_set():
            status = self.run_next()
            if status == "ran":
                continue
            if status == "closing":
                break
            self.status = {"paused": "일시정지됨", "empty": "대기 작업 없음",
                           "waiting": "PC 사용 중 — 자원 대기"}.get(status, status)
            self.on_change()
            self._wake.clear()
            self._wake.wait(self.recheck_seconds if status == "waiting" else 3600)
        self.on_change()
