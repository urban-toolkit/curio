"""Download jobs: what is running, how far along, and who may see it.

A download is a job rather than a request because a 64 MiB file from a
municipal portal can outlast any comfortable request timeout, and because the
page wants a progress bar rather than a spinner.

Modelled on ``streetvision/jobs.py``, which is the existing precedent, with
three things that store does not have and this one needs:

- **records are keyed by (user, job)**, and ``get`` returns nothing for a
  foreign job. ``streetvision``'s ``get_job(job_id)`` returns anyone's;
- **cancellation**, checked between chunks, so a user who started a download of
  something enormous is not stuck watching it;
- **a TTL sweep**, so finished records do not accumulate for the life of the
  process.

Honest about what it is not: process-local, and lost on restart. A job in
flight when the backend stops is simply gone, and the page reports that rather
than waiting forever. Surviving a restart means a table and a worker, which is
a bigger change than this bound is worth today.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

#: Terminal states. Anything else is still moving.
TERMINAL = frozenset({"completed", "failed", "refused", "cancelled"})

#: How long a finished record stays readable. Long enough for a page that was
#: backgrounded to come back and collect its result.
TTL_SECONDS = 15 * 60


@dataclass
class DownloadJob:
    job_id: str
    user_key: str
    source_dir: str
    resource_id: str
    status: str = "queued"
    bytes_read: int = 0
    #: From ``Content-Length`` when the portal sends one. A hint: it is the
    #: portal's claim, not a bound, and the cap is enforced against bytes
    #: actually written.
    total_bytes: int | None = None
    stage_message: str = "Queued"
    error: str | None = None
    dataset_id: str | None = None
    dataset: dict[str, Any] | None = None
    already_present: bool = False
    unchanged: bool = False
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def to_row(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "status": self.status,
            "bytesRead": self.bytes_read,
            "totalBytes": self.total_bytes,
            "stageMessage": self.stage_message,
            "error": self.error,
            "datasetId": self.dataset_id,
            "dataset": self.dataset,
            "alreadyPresent": self.already_present,
            "unchanged": self.unchanged,
            "sourceId": self.source_dir,
            "resourceId": self.resource_id,
        }


class JobStore:
    def __init__(self, ttl_seconds: int = TTL_SECONDS) -> None:
        self._jobs: dict[tuple[str, str], DownloadJob] = {}
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_seconds

    def create(self, user_key: str, source_dir: str, resource_id: str) -> DownloadJob:
        job = DownloadJob(
            job_id=uuid.uuid4().hex,
            user_key=user_key,
            source_dir=source_dir,
            resource_id=resource_id,
        )
        with self._lock:
            self._sweep_locked()
            self._jobs[(user_key, job.job_id)] = job
        return job

    def get(self, user_key: str, job_id: str) -> DownloadJob | None:
        """This user's job, or None.

        Keyed by the pair, so asking for someone else's id is indistinguishable
        from asking for one that does not exist - which is the right answer to
        both.
        """
        with self._lock:
            self._sweep_locked()
            return self._jobs.get((user_key, job_id))

    def cancel(self, user_key: str, job_id: str) -> bool:
        job = self.get(user_key, job_id)
        if job is None:
            return False
        if job.status in TERMINAL:
            return False
        job._cancel.set()
        job.stage_message = "Cancelling…"
        return True

    def finish(self, job: DownloadJob, status: str, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(job, key, value)
        job.status = status
        job.finished_at = time.monotonic()

    def _sweep_locked(self) -> None:
        now = time.monotonic()
        stale = [
            key
            for key, job in self._jobs.items()
            if job.finished_at is not None and now - job.finished_at > self.ttl_seconds
        ]
        for key in stale:
            self._jobs.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._jobs.clear()


#: Process-wide, like the store it is modelled on. The docstring says why.
jobs = JobStore()


def run_in_background(target: Callable[[], None]) -> threading.Thread:
    """Start a job worker.

    A daemon thread so a download in flight never holds up a shutdown: the job
    is lost either way, and blocking the process to finish one would just make
    the restart slower without saving it.
    """
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread
