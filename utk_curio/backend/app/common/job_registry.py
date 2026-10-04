"""Detached, re-attachable background jobs in this process.

A job runs an event generator on a daemon thread. Every event is appended to
the job's bounded log and fanned out to live subscribers; an HTTP handler only
subscribes, replaying what already happened and tailing what follows, so a
client that disconnects only unsubscribes and the job keeps running.

One :class:`JobRegistry` per kind of work: agent jobs key on an attachment,
dataflow runs on a dataflow. Each registry allows one live job per key, caps
live jobs per user, and keeps finished jobs for a while so a reconnecting
client can still replay them. Jobs do not survive a restart: the registry is
the source of truth for liveness and the event log only, and whatever owns
the work persists its own record.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

log = logging.getLogger(__name__)

_SENTINEL = None


class JobRefused(ValueError):
    """A job could not start: one already runs for its key, or the user is at
    the cap. Carries the HTTP status routes use."""

    def __init__(self, message: str, status: int = 409, job_id: str | None = None):
        super().__init__(message)
        self.status = status
        self.job_id = job_id


@dataclass
class Job:
    job_id: str
    kind: str
    user_key: str
    project_id: str
    key: str
    max_events: int = 2000
    status: str = "running"  # running | done | error
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    heartbeat_at: float = field(default_factory=time.time)
    events: deque = field(default=None)
    subscribers: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None
    # Secret values taken out of a failure before it is published or logged.
    redact_values: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if self.events is None:
            self.events = deque(maxlen=self.max_events)

    @property
    def live(self) -> bool:
        return self.status == "running"

    def to_payload(self) -> dict[str, Any]:
        """The liveness projection, without event bodies."""
        return {
            "executionId": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "startedAt": self.started_at,
            "heartbeatAt": self.heartbeat_at,
            "finishedAt": self.finished_at,
            "events": len(self.events),
        }


class JobRegistry:
    """Live jobs of one kind of work, under one lock.

    *busy_message* is the refusal when a job already runs for a key,
    *cap_message* the one when a user is at *max_active_per_user*.
    """

    def __init__(
        self,
        *,
        name: str,
        kinds: Iterable[str],
        max_active_per_user: int,
        finished_ttl_seconds: float,
        max_events: int,
        busy_message: str,
        cap_message: str,
    ):
        self.name = name
        self.kinds = tuple(kinds)
        self.max_active_per_user = max_active_per_user
        self.finished_ttl_seconds = finished_ttl_seconds
        self.max_events = max_events
        self.busy_message = busy_message
        self.cap_message = cap_message
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[tuple[str, str], str] = {}

    def reset(self) -> None:
        """Test seam: drop every job (threads already running finish unobserved)."""
        with self._lock:
            self._jobs.clear()
            self._by_key.clear()

    def is_live(self, job_id: object) -> bool:
        """True iff this process holds a running job with that id."""
        if not isinstance(job_id, str) or not job_id:
            return False
        with self._lock:
            job = self._jobs.get(job_id)
        return job is not None and job.live

    def live_job(self, user_key: str, key: str) -> Job | None:
        with self._lock:
            job_id = self._by_key.get((user_key, key))
            job = self._jobs.get(job_id) if job_id else None
        return job if job is not None and job.live else None

    def latest_job(self, user_key: str, key: str) -> Job | None:
        """The key's running job, or its most recent finished one still within
        the replay window."""
        self.sweep_finished()
        with self._lock:
            job_id = self._by_key.get((user_key, key))
            return self._jobs.get(job_id) if job_id else None

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _active_count(self, user_key: str) -> int:
        return sum(1 for job in self._jobs.values() if job.user_key == user_key and job.live)

    def check_can_start(self, user_key: str, key: str) -> None:
        """Raise :class:`JobRefused` when a job may not start. Called before the
        caller persists anything, so a refusal leaves nothing behind."""
        self.sweep_finished()
        with self._lock:
            current = self._by_key.get((user_key, key))
            if current and (job := self._jobs.get(current)) is not None and job.live:
                raise JobRefused(self.busy_message, 409, job_id=job.job_id)
            if self._active_count(user_key) >= self.max_active_per_user:
                raise JobRefused(self.cap_message, 429)

    def start(
        self,
        *,
        user_key: str,
        project_id: str,
        key: str,
        kind: str,
        job_id: str,
        events: Iterator[tuple[str, Any]],
        app_context: Callable | None = None,
        redact_values: dict | None = None,
    ) -> Job:
        """Register *job_id* and drive *events* (a ``(kind, payload)`` generator)
        on a daemon thread. An exception in the generator becomes a terminal
        ``error`` event, never a lost job, with *redact_values* taken out of its
        text."""
        if kind not in self.kinds:
            raise ValueError(f"unknown job kind {kind!r}")
        self.check_can_start(user_key, key)
        job = Job(
            job_id=job_id, kind=kind, user_key=user_key, project_id=project_id,
            key=key, max_events=self.max_events, redact_values=dict(redact_values or {}),
        )
        with self._lock:
            self._jobs[job_id] = job
            self._by_key[(user_key, key)] = job_id
        if app_context is None:
            # The generator runs outside the request; give it the app context
            # the request had (config, extensions) when one is available.
            try:
                from flask import current_app, has_app_context

                if has_app_context():
                    app_context = current_app._get_current_object().app_context
            except Exception:  # not under Flask (unit tests, tools): run bare
                app_context = None
        thread = threading.Thread(
            target=self._run, args=(job, events, app_context), daemon=True,
            name=f"{self.name}-job-{kind}-{job_id[:8]}",
        )
        job.thread = thread
        thread.start()
        return job

    def _run(self, job: Job, events: Iterator[tuple[str, Any]], app_context=None) -> None:
        status = "done"
        try:
            if app_context is not None:
                with app_context():
                    for item in events:
                        self.publish(job, item)
            else:
                for item in events:
                    self.publish(job, item)
        except Exception as exc:  # the generator's failure is an event, not a lost job
            from utk_curio.common.redaction import redact

            log.error("%s job %s (%s) failed:\n%s", self.name, job.job_id, job.kind,
                      redact(traceback.format_exc(), job.redact_values))
            self.publish(job, ("error", f"job failed: {(redact(str(exc), job.redact_values) or '')[:300]}"))
            status = "error"
        finally:
            with job.lock:
                job.status = status
                job.finished_at = time.time()
                job.heartbeat_at = job.finished_at
                for q in job.subscribers:
                    q.put(_SENTINEL)
                job.subscribers.clear()

    @staticmethod
    def publish(job: Job, item: tuple[str, Any]) -> None:
        with job.lock:
            job.events.append(item)
            job.heartbeat_at = time.time()
            for q in job.subscribers:
                q.put(item)

    @staticmethod
    def heartbeat(job: Job) -> None:
        """Touch the job's liveness clock without an event (a long sandbox run)."""
        with job.lock:
            job.heartbeat_at = time.time()

    @staticmethod
    def subscribe(job: Job) -> Iterator[tuple[str, Any]]:
        """Replay the job's log, then tail live events until the job finishes.
        A finished job replays and ends. Leaving the generator early (a client
        disconnect) only unsubscribes: the job keeps running."""
        q: queue.Queue = queue.Queue()
        with job.lock:
            snapshot = list(job.events)
            finished = not job.live
            if not finished:
                job.subscribers.append(q)
        try:
            for item in snapshot:
                yield item
            if finished:
                return
            while True:
                item = q.get()
                if item is _SENTINEL:
                    return
                yield item
        finally:
            with job.lock:
                if q in job.subscribers:
                    job.subscribers.remove(q)

    def sweep_finished(self, now: float | None = None) -> int:
        """Drop finished jobs older than the replay window. Returns how many."""
        now = time.time() if now is None else now
        dropped = 0
        with self._lock:
            for job_id in [
                jid for jid, job in self._jobs.items()
                if not job.live and job.finished_at is not None
                and now - job.finished_at > self.finished_ttl_seconds
            ]:
                job = self._jobs.pop(job_id)
                key = (job.user_key, job.key)
                if self._by_key.get(key) == job_id:
                    self._by_key.pop(key, None)
                dropped += 1
        return dropped
