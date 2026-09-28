"""Evaluation run records (memo dev/123, ``DEC-079``).

One file per run under ``.curio/users/<key>/agents/evaluation/<runId>.json``,
append-only in its events with the state projected from them — the shape
dev/122's training records proved out, reused rather than reinvented.

What a record has to carry is set by the correction: *"enough metadata to
reproduce and inspect a run, including the fixture, provider and model, agent
and prompt digests, generated project ID, normalized comparison, metrics,
failures, latency, and token usage. Never store or expose API keys or
connection secrets."* So the provider is recorded as its **kind, host and
model** — the config object itself is never serialized, and the key is never
read here at all.

Events are the honest part. A run that stopped in `installing` has the phases
it reached and nothing after, which is what "where did it get to" means; the
projection is a convenience over that, never a substitute.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from utk_curio.backend.app.agents.storage import user_agents_dir
from utk_curio.backend.app.common.file_locks import exclusive_lock

RECORD_VERSION = 1

#: Any value that becomes a path segment is validated first, never trusted
#: (the ``sessions.py`` discipline).
RUN_ID_RE = re.compile(r"^eval-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")

_LOCK_NAMESPACE = "agents-evaluation"

#: The phases a run moves through, in order. Forward-only: a phase never goes
#: backwards, so "where did it get to" has one answer.
PHASES = (
    "preparing",      # fixture loaded, provider resolved
    "project",        # the isolated project created and marked
    "provisioning",   # the fixture's datasets and packages installed
    "installing",     # the Dataflow Builder + its required closure, attached
    "prompting",      # the prompt sent through the normal runtime
    "reviewing",      # proposals decided by the shared policy, applied
    "solving",        # the real Solve, with verification
    "scoring",        # the persisted spec compared with the reference
    "done",
)

TERMINAL_PHASES = ("done", "failed", "cancelled", "interrupted")

EVENT_KINDS = (
    "phase",          # entered a phase
    "auto-applied",   # a proposal applied on the user's behalf, and why allowed
    "left-pending",   # a proposal the policy did not apply, and why
    "refused",        # a proposal the authorization refused
    "note",
    "error",
    "cancel-requested",
)


class EvaluationRecordError(Exception):
    """A record could not be read or written."""


def new_run_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"eval-{stamp}-{secrets.token_hex(4)}"


def evaluation_dir(user_key: str) -> Path:
    return user_agents_dir(user_key) / "evaluation"


def record_path(user_key: str, run_id: str) -> Path:
    if not RUN_ID_RE.match(run_id or ""):
        raise EvaluationRecordError(f"invalid evaluation run id: {run_id!r}")
    return evaluation_dir(user_key) / f"{run_id}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class EvaluationRecord:
    """One run, as this account knows it."""

    run_id: str
    fixture_id: str = ""
    #: Kind, host and model only. The config is never serialized and the key is
    #: never read here (``RISK-SECRET-001``).
    provider: dict = field(default_factory=dict)
    digests: dict = field(default_factory=dict)
    project_id: str | None = None
    attachment_id: str | None = None
    phase: str = "preparing"
    review_status: str = ""
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    latency_ms: int = 0
    usage: dict = field(default_factory=lambda: {"inputTokens": 0, "outputTokens": 0})
    score: dict | None = None
    comparison: dict | None = None
    failures: list = field(default_factory=list)
    applied: list = field(default_factory=list)
    pending: list = field(default_factory=list)
    events: list = field(default_factory=list)
    cancel_requested: bool = False
    error: str | None = None

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES

    @property
    def running(self) -> bool:
        return not self.terminal

    def as_dict(self) -> dict:
        return {
            "recordVersion": RECORD_VERSION,
            "runId": self.run_id,
            "fixtureId": self.fixture_id,
            "provider": dict(self.provider),
            "digests": dict(self.digests),
            "projectId": self.project_id,
            "attachmentId": self.attachment_id,
            "phase": self.phase,
            "reviewStatus": self.review_status,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "latencyMs": self.latency_ms,
            "usage": dict(self.usage),
            "score": self.score,
            "comparison": self.comparison,
            "failures": [dict(f) for f in self.failures],
            "applied": [dict(a) for a in self.applied],
            "pending": [dict(p) for p in self.pending],
            "events": [dict(e) for e in self.events],
            "cancelRequested": self.cancel_requested,
            "error": self.error,
            "terminal": self.terminal,
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "EvaluationRecord":
        return cls(
            run_id=str(payload.get("runId") or ""),
            fixture_id=str(payload.get("fixtureId") or ""),
            provider=dict(payload.get("provider") or {}),
            digests=dict(payload.get("digests") or {}),
            project_id=payload.get("projectId"),
            attachment_id=payload.get("attachmentId"),
            phase=str(payload.get("phase") or "preparing"),
            review_status=str(payload.get("reviewStatus") or ""),
            started_at=str(payload.get("startedAt") or _now()),
            finished_at=payload.get("finishedAt"),
            latency_ms=int(payload.get("latencyMs") or 0),
            usage=dict(payload.get("usage") or {"inputTokens": 0, "outputTokens": 0}),
            score=payload.get("score"),
            comparison=payload.get("comparison"),
            failures=[dict(f) for f in (payload.get("failures") or [])],
            applied=[dict(a) for a in (payload.get("applied") or [])],
            pending=[dict(p) for p in (payload.get("pending") or [])],
            events=[dict(e) for e in (payload.get("events") or [])],
            cancel_requested=bool(payload.get("cancelRequested")),
            error=payload.get("error"),
        )

    def append(self, kind: str, **detail) -> dict:
        if kind not in EVENT_KINDS:
            raise EvaluationRecordError(f"unknown evaluation event kind: {kind!r}")
        event = {"at": _now(), "kind": kind, **detail}
        self.events.append(event)
        return event

    def enter(self, phase: str, **detail) -> dict:
        """Move forward into *phase*. Forward-only, so a record cannot claim to
        have gone back to a phase it already left."""
        if phase not in PHASES and phase not in TERMINAL_PHASES:
            raise EvaluationRecordError(f"unknown evaluation phase: {phase!r}")
        if phase in PHASES and self.phase in PHASES:
            if PHASES.index(phase) < PHASES.index(self.phase):
                raise EvaluationRecordError(
                    f"cannot go back from {self.phase!r} to {phase!r}"
                )
        self.phase = phase
        if phase in TERMINAL_PHASES:
            self.finished_at = _now()
        return self.append("phase", phase=phase, **detail)

    def fail(self, phase: str, detail: str) -> dict:
        """Record where it stopped and why, then finish."""
        self.failures.append({"phase": phase, "detail": str(detail)})
        self.error = str(detail)
        return self.enter("failed", failedIn=phase)


def write(user_key: str, record: EvaluationRecord) -> Path:
    path = record_path(user_key, record.run_id)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".lock"
    lock_path.touch(exist_ok=True)
    with exclusive_lock(lock_path, namespace=_LOCK_NAMESPACE, key=str(user_key)):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(record.as_dict(), handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    return path


def read(user_key: str, run_id: str) -> EvaluationRecord | None:
    try:
        payload = json.loads(record_path(user_key, run_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise EvaluationRecordError(f"could not read evaluation {run_id}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvaluationRecordError(f"evaluation {run_id} is not an object")
    return EvaluationRecord.from_dict(payload)


def list_records(user_key: str, *, limit: int = 50) -> list:
    directory = evaluation_dir(user_key)
    if not directory.is_dir():
        return []
    out: list = []
    for path in sorted(directory.glob("eval-*.json"), reverse=True)[:limit]:
        if path.name.endswith(".tmp.json"):
            continue
        try:
            record = read(user_key, path.stem)
        except EvaluationRecordError:
            continue
        if record is not None:
            out.append(record)
    return out


def in_flight(user_key: str) -> EvaluationRecord | None:
    """The account's live run, if it has one.

    One at a time: a run installs packages, calls a model and executes code, so
    two at once would compete for the same account's background budget and make
    both slower and harder to read.
    """
    for record in list_records(user_key):
        if record.running:
            return record
    return None


def reconcile(user_key: str, record: EvaluationRecord) -> EvaluationRecord:
    """A run left running by a process that no longer holds it is `interrupted`.

    The ``DEC-073`` pattern: liveness is the lease, so a record that claims to
    be running while no job owns it is stale rather than true. Nothing is
    replayed.
    """
    from utk_curio.backend.app.agents import agent_jobs

    if record.terminal:
        return record
    if agent_jobs.is_live(record.run_id):
        return record
    record.append("note", detail="the process that owned this run is gone")
    record.enter("interrupted")
    write(user_key, record)
    return record


def cancel_path(user_key: str, run_id: str) -> Path:
    """The cancel sentinel's own file.

    A cancel is a request from a DIFFERENT writer than the run, and the run
    rewrites its whole record at every phase — so putting the request in that
    record is a lost update waiting to happen, and it happened: the flag was
    clobbered between the cancel's read and its write, the run never saw it,
    and the event vanished. Two writers now never share a file. The run is the
    only writer of its record; the canceller is the only writer of this
    sentinel; and the run appends the event itself when it observes one, so the
    event is always in the copy that owns it.
    """
    if not RUN_ID_RE.match(run_id or ""):
        raise EvaluationRecordError(f"invalid evaluation run id: {run_id!r}")
    return evaluation_dir(user_key) / f"{run_id}.cancel"


def request_cancel(user_key: str, run_id: str) -> EvaluationRecord:
    record = read(user_key, run_id)
    if record is None:
        raise EvaluationRecordError(f"no evaluation run {run_id}")
    if record.terminal:
        return record
    path = cancel_path(user_key, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_now(), encoding="utf-8")
    # The returned projection says the request was accepted; the run's own copy
    # gains the event when it observes the sentinel.
    record.cancel_requested = True
    return record


def cancel_requested(user_key: str, run_id: str) -> bool:
    """Whether somebody asked this run to stop."""
    try:
        return cancel_path(user_key, run_id).exists()
    except EvaluationRecordError:
        return False


def clear_cancel(user_key: str, run_id: str) -> None:
    """Remove the sentinel once the run has acted on it."""
    try:
        cancel_path(user_key, run_id).unlink(missing_ok=True)
    except (OSError, EvaluationRecordError):
        pass
