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

The registry itself is ``common/job_registry.py``, shared with dataflow runs;
this module keys it by attachment.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

from utk_curio.backend.app.common.job_registry import Job, JobRefused, JobRegistry

JOB_KINDS = ("solve-batch", "solve-node")

#: Backpressure: concurrent live jobs per user (each drives ≤3 sandbox runs).
MAX_ACTIVE_JOBS_PER_USER = 2
#: A finished job stays subscribable this long so a reload can replay it.
FINISHED_TTL_SECONDS = 15 * 60
#: The bounded event log per job (a 25-node batch with rounds fits easily).
MAX_EVENTS_PER_JOB = 2000

__all__ = ["JobRefused"]

_REGISTRY = JobRegistry(
    name="agent",
    kinds=JOB_KINDS,
    max_active_per_user=MAX_ACTIVE_JOBS_PER_USER,
    finished_ttl_seconds=FINISHED_TTL_SECONDS,
    max_events=MAX_EVENTS_PER_JOB,
    busy_message="a job is already running for this attachment",
    cap_message=(
        f"at most {MAX_ACTIVE_JOBS_PER_USER} background jobs may run at once; "
        "wait for one to finish"
    ),
)


def reset_registry() -> None:
    """Test seam: drop every job (threads already running finish unobserved)."""
    _REGISTRY.reset()


def is_live(job_id: object) -> bool:
    """True iff THIS process holds a running job with that id."""
    return _REGISTRY.is_live(job_id)


def live_job(user_key: str, attachment_id: str) -> Job | None:
    return _REGISTRY.live_job(user_key, attachment_id)


def latest_job(user_key: str, attachment_id: str) -> Job | None:
    """The attachment's running job, or its most recent finished one still
    within the replay TTL."""
    return _REGISTRY.latest_job(user_key, attachment_id)


def get_job(job_id: str) -> Job | None:
    return _REGISTRY.get_job(job_id)


def check_can_start(user_key: str, attachment_id: str) -> None:
    """Raise :class:`JobRefused` when a job may not start — called BEFORE the
    caller persists any in-flight state, so a refusal leaves nothing behind."""
    _REGISTRY.check_can_start(user_key, attachment_id)


def start_job(
    *,
    user_key: str,
    project_id: str,
    attachment_id: str,
    kind: str,
    job_id: str,
    events: Iterator[tuple[str, Any]],
    app_context=None,
    redact_values: dict | None = None,
) -> Job:
    """Register *job_id* and drive *events* (a ``(kind, payload)`` generator)
    in a daemon thread. Every item is appended to the job's log and fanned
    out to live subscribers; the generator's own ``finally`` blocks (the
    Solve ``_finish`` persist) run inside the thread exactly as they did
    inside the request. An exception in the generator becomes a terminal
    ``error`` event, never a lost job, with *redact_values* taken out of its
    text."""
    return _REGISTRY.start(
        user_key=user_key, project_id=project_id, key=attachment_id, kind=kind,
        job_id=job_id, events=events, app_context=app_context,
        redact_values=redact_values,
    )


def heartbeat(job: Job) -> None:
    """Touch the job's liveness clock without an event (a long sandbox run)."""
    JobRegistry.heartbeat(job)


def subscribe(job: Job) -> Iterator[tuple[str, Any]]:
    """Replay the job's log, then tail live events until the job finishes.
    A finished job replays and ends. Leaving the generator early (a client
    disconnect) only unsubscribes — the job keeps running."""
    return JobRegistry.subscribe(job)


def sweep_finished(now: float | None = None) -> int:
    """Drop finished jobs older than the replay TTL. Returns how many."""
    return _REGISTRY.sweep_finished(now)


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
