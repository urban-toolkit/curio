"""Observable package-build jobs — lifecycle, cancellation, backpressure (memo dev/89 §3.9).

One job per (user, input digest). The digest — :func:`build_models.request_digest`
over the immutable request — is the build's identity AND its correlation id:
retrying the same request re-attaches to the running job or returns the
cached ``ready`` one instead of spawning a duplicate build.

Phases are stable and forward-only::

    queued → resolving → compiling → validating → previewing → packaging → ready

with terminal ``failed`` / ``cancelled`` / ``expired``. A pipeline may skip
phases it does not need (a package with no behavior source never previews) —
it may never move backwards.

Everything a job records (events, failure reasons) passes through
:func:`build_workspace.sanitize_diagnostic` before storage, so nothing that
leaves this module carries host paths, environment values, or tokens.

The registry is in-process (module state under one lock). Jobs do not
survive a backend restart — the artifact staging store and the immutable
request do, so a lost job is re-run by digest, landing on the identical
artifact (dev/89 §3.1). Agent services observe jobs through these functions;
they never control worker processes directly.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from utk_curio.backend.app.packages.build_models import (
    PackageBuildRequest,
    PackageBuildResult,
    request_digest,
)
from utk_curio.backend.app.packages.build_workspace import sanitize_diagnostic

PHASE_ORDER = (
    "queued", "resolving", "compiling", "validating", "probing", "previewing",
    "packaging", "ready",
)
TERMINAL_PHASES = ("ready", "failed", "cancelled", "expired")

# Backpressure (dev/89 §3.9): cap concurrent (non-terminal) builds per user
# rather than spawning unbounded workers.
MAX_ACTIVE_JOBS_PER_USER = 2

# Terminal jobs kept for status queries before pruning (oldest first).
MAX_TERMINAL_JOBS_PER_USER = 20

# A ready job whose artifact was never applied expires with its staged
# artifact (build_staging.DEFAULT_TTL_SECONDS) — kept numerically separate so
# the two policies can diverge deliberately, never accidentally.
READY_JOB_TTL_SECONDS = 24 * 60 * 60

_MAX_EVENTS_PER_JOB = 50
_EVENT_MESSAGE_MAX_CHARS = 500


class JobError(ValueError):
    """Raised on illegal transitions and malformed job operations."""


class JobRefused(JobError):
    """Raised when backpressure refuses a new job (too many active builds)."""


@dataclass
class BuildJob:
    """One build's observable state. Mutate only through module functions."""

    build_id: str  # the request digest — identity and correlation id
    user_key: str
    request: PackageBuildRequest
    phase: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: PackageBuildResult | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def to_payload(self) -> dict[str, Any]:
        """The status payload routes/agents may see — no request bodies, no
        paths; the events are pre-sanitized at record time."""
        return {
            "buildId": self.build_id,
            "phase": self.phase,
            "terminal": self.phase in TERMINAL_PHASES,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "events": [dict(e) for e in self.events],
            "result": self.result.to_payload() if self.result is not None else None,
        }


_LOCK = threading.Lock()
_JOBS: dict[tuple[str, str], BuildJob] = {}


def reset_registry() -> None:
    """Test seam: drop every job."""
    with _LOCK:
        _JOBS.clear()


def _record_event(job: BuildJob, phase: str, message: str) -> None:
    text = sanitize_diagnostic(str(message))[:_EVENT_MESSAGE_MAX_CHARS]
    job.events.append({"at": time.time(), "phase": phase, "message": text})
    if len(job.events) > _MAX_EVENTS_PER_JOB:
        del job.events[: len(job.events) - _MAX_EVENTS_PER_JOB]
    job.updated_at = time.time()


def _active_count(user_key: str) -> int:
    return sum(
        1 for (uk, _), job in _JOBS.items()
        if uk == user_key and job.phase not in TERMINAL_PHASES
    )


def _prune_terminal(user_key: str) -> None:
    terminal = sorted(
        ((key, job) for key, job in _JOBS.items()
         if key[0] == user_key and job.phase in TERMINAL_PHASES),
        key=lambda item: item[1].updated_at,
    )
    for key, _ in terminal[: max(0, len(terminal) - MAX_TERMINAL_JOBS_PER_USER)]:
        del _JOBS[key]


def create_job(user_key: str, request: PackageBuildRequest) -> tuple[BuildJob, bool]:
    """Create (or re-attach to) the job for *request*; returns ``(job, created)``.

    Idempotent by input digest (dev/89 §3.9): an active job or a cached
    ``ready`` job for the same digest is returned as-is (``created=False``).
    A failed/cancelled/expired job is superseded by a fresh one. Refuses with
    :class:`JobRefused` when the user already has
    ``MAX_ACTIVE_JOBS_PER_USER`` builds in flight.
    """
    digest = request_digest(request)
    key = (user_key, digest)
    # Expire this user's stale ``ready`` jobs first. Nothing else called
    # ``sweep_expired_jobs``: there is no scheduler and no lifecycle route, so
    # READY_JOB_TTL_SECONDS was a constant with no effect and a ready job stayed
    # ready forever, holding its staged artifact against a request whose inputs
    # may have moved on. Doing it here ties the sweep to the one moment the user
    # is demonstrably still building, at the cost of a short walk over their own
    # jobs.
    sweep_expired_jobs(user_key)
    with _LOCK:
        existing = _JOBS.get(key)
        if existing is not None:
            if existing.phase not in TERMINAL_PHASES or existing.phase == "ready":
                return existing, False
            # failed/cancelled/expired: a retry supersedes it.
            del _JOBS[key]
        if _active_count(user_key) >= MAX_ACTIVE_JOBS_PER_USER:
            raise JobRefused(
                f"too many active builds ({MAX_ACTIVE_JOBS_PER_USER}); wait for "
                "one to finish or cancel it"
            )
        job = BuildJob(build_id=digest, user_key=user_key, request=request)
        _record_event(job, "queued", "build queued")
        _JOBS[key] = job
        _prune_terminal(user_key)
        return job, True


def get_job(user_key: str, build_id: str) -> BuildJob | None:
    with _LOCK:
        return _JOBS.get((user_key, build_id))


def list_jobs(user_key: str) -> list[BuildJob]:
    with _LOCK:
        return sorted(
            (job for (uk, _), job in _JOBS.items() if uk == user_key),
            key=lambda j: j.created_at,
        )


def _phase_index(phase: str) -> int:
    try:
        return PHASE_ORDER.index(phase)
    except ValueError:
        raise JobError(f"unknown phase {phase!r}") from None


def advance(job: BuildJob, phase: str, message: str = "") -> None:
    """Move *job* forward to *phase* (forward-only; phases may be skipped)."""
    with _LOCK:
        if job.phase in TERMINAL_PHASES:
            raise JobError(f"job {job.build_id} is terminal ({job.phase})")
        if _phase_index(phase) <= _phase_index(job.phase):
            raise JobError(
                f"illegal transition {job.phase!r} → {phase!r}: phases are forward-only"
            )
        job.phase = phase
        _record_event(job, phase, message or f"entered {phase}")


def fail(job: BuildJob, message: str) -> None:
    with _LOCK:
        if job.phase in TERMINAL_PHASES:
            raise JobError(f"job {job.build_id} is terminal ({job.phase})")
        job.phase = "failed"
        _record_event(job, "failed", message)


def cancel_job(user_key: str, build_id: str) -> bool:
    """Request cancellation. Returns True when a non-terminal job was found.

    The cancel event reaches any in-flight worker (build_workspace honors it
    mid-process); a queued/never-executing job is marked cancelled here, and
    :func:`execute` marks a running one cancelled at its next checkpoint.
    """
    with _LOCK:
        job = _JOBS.get((user_key, build_id))
        if job is None or job.phase in TERMINAL_PHASES:
            return False
        job.cancel_event.set()
        if job.phase == "queued":
            job.phase = "cancelled"
            _record_event(job, "cancelled", "cancelled before execution")
        return True


def attach_result(job: BuildJob, result: PackageBuildResult) -> None:
    with _LOCK:
        job.result = result
        job.updated_at = time.time()


def execute(job: BuildJob, steps: list[tuple[str, Callable[[BuildJob], None]]]) -> BuildJob:
    """Run *steps* — ``(phase, fn)`` pairs — with cancellation checkpoints.

    Each step's phase is entered before its fn runs; a raising step fails the
    job with a sanitized reason; a set cancel event between (or during) steps
    marks the job cancelled and runs nothing further. A job that survives
    every step becomes ``ready``. Never raises for build failures — the job
    record is the outcome.
    """
    for phase, fn in steps:
        if job.cancel_event.is_set():
            with _LOCK:
                if job.phase not in TERMINAL_PHASES:
                    job.phase = "cancelled"
                    _record_event(job, "cancelled", "cancelled between phases")
            return job
        try:
            advance(job, phase)
            fn(job)
        except JobError:
            raise  # controller misuse is a programming error, never a build outcome
        except Exception as exc:  # noqa: BLE001 — a build failure is data
            if job.cancel_event.is_set():
                with _LOCK:
                    if job.phase not in TERMINAL_PHASES:
                        job.phase = "cancelled"
                        _record_event(job, "cancelled", "cancelled mid-phase")
                return job
            fail(job, f"{phase} failed: {exc}")
            return job
    if job.cancel_event.is_set():
        with _LOCK:
            if job.phase not in TERMINAL_PHASES:
                job.phase = "cancelled"
                _record_event(job, "cancelled", "cancelled after the last phase")
        return job
    advance(job, "ready", "build ready for review")
    return job


def sweep_expired_jobs(
    user_key: str, *, ttl_seconds: float = READY_JOB_TTL_SECONDS, now: float | None = None
) -> list[str]:
    """Mark ``ready`` jobs older than *ttl_seconds* as ``expired``.

    Mirrors the staged-artifact TTL: an expired proposal must be rebuilt from
    its immutable request — Apply never rebuilds silently (dev/89 §6).
    Returns the expired build ids.
    """
    current = time.time() if now is None else now
    expired: list[str] = []
    with _LOCK:
        for (uk, _), job in _JOBS.items():
            if uk != user_key or job.phase != "ready":
                continue
            if current - job.updated_at < ttl_seconds:
                continue
            job.phase = "expired"
            _record_event(job, "expired", "staged artifact TTL elapsed — rebuild to review")
            expired.append(job.build_id)
    return expired
