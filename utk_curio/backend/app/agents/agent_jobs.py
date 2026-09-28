"""Detached, re-attachable agent jobs (memo dev/115, DEC-073) — DEC-021's
single-process slice.

A Solve batch or a per-node Solve used to run INSIDE the HTTP request: the
browser tab was the process boundary, so closing the panel ended the run
(``GeneratorExit`` → the batch finished early) and a data fetch that takes
minutes could not be trusted to complete. Here the event generator runs in a
daemon thread; the HTTP handler merely SUBSCRIBES — it replays what already
happened and tails what follows — and a disconnect only unsubscribes.

Modeled on ``packages/build_jobs.py``: an in-process registry under one lock,
one live job per attachment, per-user backpressure, terminal jobs kept for a
bounded time so a reconnecting client can still replay them. Jobs do not
survive a backend restart by design — that is what :func:`reconcile_builder_session`
is for: a builder session left ``solving`` by a process that is gone becomes
``interrupted`` (DEC-021's word for expired nonterminal work), and Retry is a
NEW execution linked to it; nothing is ever replayed automatically.

Liveness IS the lease in the documented single-process topology (OQ-009's
default posture): a job is alive iff this process holds it. A multi-instance
deployment needs a durable owner and stays gated by OQ-009 — the registry is
never the source of truth for anything but liveness and the event log; the
persisted ``builderSession`` remains the record.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterator

log = logging.getLogger(__name__)

#: dev/123: ``evaluation-run`` joins the two Solve kinds so an evaluation gets
#: the same detached-job machinery — event replay, per-user backpressure, SSE
#: re-attachment and the liveness-is-the-lease rule — instead of a second
#: liveness model, which would pre-empt ``OQ-009``.
JOB_KINDS = ("solve-batch", "solve-node", "evaluation-run")

#: Backpressure: concurrent live jobs per user (each drives ≤3 sandbox runs).
MAX_ACTIVE_JOBS_PER_USER = 2
#: A finished job stays subscribable this long so a reload can replay it.
FINISHED_TTL_SECONDS = 15 * 60
#: The bounded event log per job (a 25-node batch with rounds fits easily).
MAX_EVENTS_PER_JOB = 2000

_SENTINEL = None


class JobRefused(ValueError):
    """A job could not start: one already runs for the attachment, or the
    user is at the backpressure cap. Carries the HTTP status routes use."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


@dataclass
class AgentJob:
    job_id: str  # = the execution id — identity and correlation id
    kind: str
    user_key: str
    project_id: str
    attachment_id: str
    status: str = "running"  # running | done | error
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    heartbeat_at: float = field(default_factory=time.time)
    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS_PER_JOB))
    subscribers: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None

    @property
    def live(self) -> bool:
        return self.status == "running"

    def to_payload(self) -> dict[str, Any]:
        """The liveness projection the attachment card carries (docs/11:178's
        "dock running dots") — no event bodies."""
        return {
            "executionId": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "startedAt": self.started_at,
            "heartbeatAt": self.heartbeat_at,
            "finishedAt": self.finished_at,
            "events": len(self.events),
        }


_LOCK = threading.Lock()
_JOBS: dict[str, AgentJob] = {}
_BY_ATTACHMENT: dict[tuple[str, str], str] = {}


def reset_registry() -> None:
    """Test seam: drop every job (threads already running finish unobserved)."""
    with _LOCK:
        _JOBS.clear()
        _BY_ATTACHMENT.clear()


def is_live(job_id: object) -> bool:
    """True iff THIS process holds a running job with that id."""
    if not isinstance(job_id, str) or not job_id:
        return False
    with _LOCK:
        job = _JOBS.get(job_id)
    return job is not None and job.live


def live_job(user_key: str, attachment_id: str) -> AgentJob | None:
    with _LOCK:
        job_id = _BY_ATTACHMENT.get((user_key, attachment_id))
        job = _JOBS.get(job_id) if job_id else None
    return job if job is not None and job.live else None


def latest_job(user_key: str, attachment_id: str) -> AgentJob | None:
    """The attachment's running job, or its most recent finished one still
    within the replay TTL."""
    sweep_finished()
    with _LOCK:
        job_id = _BY_ATTACHMENT.get((user_key, attachment_id))
        return _JOBS.get(job_id) if job_id else None


def get_job(job_id: str) -> AgentJob | None:
    with _LOCK:
        return _JOBS.get(job_id)


def _active_count(user_key: str) -> int:
    return sum(1 for job in _JOBS.values() if job.user_key == user_key and job.live)


def check_can_start(user_key: str, attachment_id: str) -> None:
    """Raise :class:`JobRefused` when a job may not start — called BEFORE the
    caller persists any in-flight state, so a refusal leaves nothing behind."""
    sweep_finished()
    with _LOCK:
        current = _BY_ATTACHMENT.get((user_key, attachment_id))
        if current and (job := _JOBS.get(current)) is not None and job.live:
            raise JobRefused("a job is already running for this attachment", 409)
        if _active_count(user_key) >= MAX_ACTIVE_JOBS_PER_USER:
            raise JobRefused(
                f"at most {MAX_ACTIVE_JOBS_PER_USER} background jobs may run at once — "
                "wait for one to finish", 429,
            )


def start_job(
    *,
    user_key: str,
    project_id: str,
    attachment_id: str,
    kind: str,
    job_id: str,
    events: Iterator[tuple[str, Any]],
    app_context=None,
) -> AgentJob:
    """Register *job_id* and drive *events* (a ``(kind, payload)`` generator)
    in a daemon thread. Every item is appended to the job's log and fanned
    out to live subscribers; the generator's own ``finally`` blocks (the
    Solve ``_finish`` persist) run inside the thread exactly as they did
    inside the request. An exception in the generator becomes a terminal
    ``error`` event, never a lost job."""
    if kind not in JOB_KINDS:
        raise ValueError(f"unknown job kind {kind!r}")
    check_can_start(user_key, attachment_id)
    job = AgentJob(job_id=job_id, kind=kind, user_key=user_key,
                   project_id=project_id, attachment_id=attachment_id)
    with _LOCK:
        _JOBS[job_id] = job
        _BY_ATTACHMENT[(user_key, attachment_id)] = job_id
    if app_context is None:
        # The generator runs outside the request; give it the app context the
        # request had (config, extensions) when one is available.
        try:
            from flask import current_app, has_app_context

            if has_app_context():
                app_context = current_app._get_current_object().app_context
        except Exception:  # not under Flask (unit tests, tools) — run bare
            app_context = None
    thread = threading.Thread(target=_run, args=(job, events, app_context), daemon=True,
                              name=f"agent-job-{kind}-{job_id[:8]}")
    job.thread = thread
    thread.start()
    return job


def _run(job: AgentJob, events: Iterator[tuple[str, Any]], app_context=None) -> None:
    status = "done"
    try:
        if app_context is not None:
            with app_context():
                for item in events:
                    _publish(job, item)
        else:
            for item in events:
                _publish(job, item)
    except Exception as exc:  # the generator's failure is an EVENT, not a lost job
        log.exception("agent job %s (%s) failed", job.job_id, job.kind)
        _publish(job, ("error", f"job failed: {str(exc)[:300]}"))
        status = "error"
    finally:
        with job.lock:
            job.status = status
            job.finished_at = time.time()
            job.heartbeat_at = job.finished_at
            for q in job.subscribers:
                q.put(_SENTINEL)
            job.subscribers.clear()


def _publish(job: AgentJob, item: tuple[str, Any]) -> None:
    with job.lock:
        job.events.append(item)
        job.heartbeat_at = time.time()
        for q in job.subscribers:
            q.put(item)


def heartbeat(job: AgentJob) -> None:
    """Touch the job's liveness clock without an event (a long sandbox run)."""
    with job.lock:
        job.heartbeat_at = time.time()


def subscribe(job: AgentJob) -> Iterator[tuple[str, Any]]:
    """Replay the job's log, then tail live events until the job finishes.
    A finished job replays and ends. Leaving the generator early (a client
    disconnect) only unsubscribes — the job keeps running."""
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


def sweep_finished(now: float | None = None) -> int:
    """Drop finished jobs older than the replay TTL. Returns how many."""
    now = time.time() if now is None else now
    dropped = 0
    with _LOCK:
        for job_id in [
            jid for jid, job in _JOBS.items()
            if not job.live and job.finished_at is not None
            and now - job.finished_at > FINISHED_TTL_SECONDS
        ]:
            job = _JOBS.pop(job_id)
            key = (job.user_key, job.attachment_id)
            if _BY_ATTACHMENT.get(key) == job_id:
                _BY_ATTACHMENT.pop(key, None)
            dropped += 1
    return dropped


def reconcile_builder_session(session: dict, now: float | None = None) -> bool:
    """DEC-021 reconciliation, in-process form: a builder session still
    ``solving`` whose execution this process does not hold is expired
    nonterminal work → ``interrupted``. Mutates *session* in place and returns
    True when it changed. Nothing is re-run; the persisted ``nodeRuns`` keep
    their ``pending``/``failed`` values so Retry (a new, linked execution)
    targets exactly what was not finished."""
    if not isinstance(session, dict) or session.get("phase") != "solving":
        return False
    execution_id = session.get("solveExecutionId")
    if is_live(execution_id):
        return False
    now = time.time() if now is None else now
    session["phase"] = "interrupted"
    session["interruptedAt"] = now
    if isinstance(execution_id, str) and execution_id:
        session["interruptedExecutionId"] = execution_id
    session.pop("solvingSince", None)
    session.pop("solveExecutionId", None)
    session.pop("cancelRequested", None)
    return True
