"""The training job record: append-only events, projected state (dev/122).

One file per job under ``.curio/users/<key>/agents/training/<jobId>.json``.

Two design points worth stating, because both were choices.

**The provider owns the job; this file owns the account's knowledge of it.** A
fine-tune runs for minutes to hours at the endpoint, so nothing local runs
alongside it — which is also why this does not pre-empt ``OQ-009``: no worker,
no work queue, no ownership handoff of any kind. Status is always what the provider last said, with the
time it said it, so a restart loses nothing and no phantom "running" job can
outlive the process that started it.

**Events append; state is projected.** The record's history is the honest part:
a `consented` event with no `submitted` after it means consent was given and
nothing was sent, which is exactly what a crash between those two steps should
look like. The projection (status, trained model, activation) is recomputed
from the events, never edited in place.

The job id is minted here and validated before it becomes a path segment — the
discipline ``sessions.py``'s ``SESSION_ID_RE`` exists for. The provider's own
job id is a field, never a filename.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from utk_curio.backend.app.agents.storage import user_agents_dir
from utk_curio.backend.app.common.file_locks import exclusive_lock

RECORD_VERSION = 1

#: Any value that becomes a path segment is checked first, never trusted.
JOB_ID_RE = re.compile(r"^train-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")

_LOCK_NAMESPACE = "agents-training"

#: Event kinds, in the order a healthy job produces them.
EVENT_KINDS = (
    "consented",     # the audit record, written BEFORE anything is sent
    "uploaded",      # the endpoint accepted the training file
    "submitted",     # the endpoint accepted the job
    "status",        # what the endpoint said, and when
    "cancelled",     # the endpoint confirmed a cancel
    "evaluated",     # a gate record was written for the trained model
    "activated",     # the account's model was switched to the trained one
    "rolled-back",   # ...and switched back
    "error",         # a step failed; the reason is the endpoint's or ours
)


class TrainingRecordError(Exception):
    """A record could not be read or written."""


def new_job_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"train-{stamp}-{secrets.token_hex(4)}"


def training_dir(user_key: str) -> Path:
    return user_agents_dir(user_key) / "training"


def record_path(user_key: str, job_id: str) -> Path:
    if not JOB_ID_RE.match(job_id or ""):
        raise TrainingRecordError(f"invalid training job id: {job_id!r}")
    return training_dir(user_key) / f"{job_id}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class TrainingRecord:
    """One job, as this account knows it."""

    job_id: str
    provider: dict = field(default_factory=dict)
    dataset: dict = field(default_factory=dict)
    consent: dict = field(default_factory=dict)
    provider_job_id: str | None = None
    status: str = "consented"
    raw_status: str = ""
    status_read_at: str = ""
    trained_model: str | None = None
    usage: dict = field(default_factory=lambda: {"trainedTokens": None})
    cost: dict | None = None
    evaluation: dict | None = None
    activation: dict = field(
        default_factory=lambda: {
            "activatedAt": None, "previousModel": None, "rolledBackAt": None,
        }
    )
    events: list = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    error: str | None = None

    # ── projection ────────────────────────────────────────────────────────
    @property
    def terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")

    @property
    def submitted(self) -> bool:
        return any(e.get("kind") == "submitted" for e in self.events)

    @property
    def consented_only(self) -> bool:
        """Consent given, nothing sent — what a crash between the two looks
        like, and it must read as exactly that."""
        return not self.submitted and any(
            e.get("kind") == "consented" for e in self.events
        )

    @property
    def activated(self) -> bool:
        return bool(self.activation.get("activatedAt")) and not self.activation.get(
            "rolledBackAt"
        )

    def as_dict(self) -> dict:
        return {
            "recordVersion": RECORD_VERSION,
            "jobId": self.job_id,
            "provider": dict(self.provider),
            "dataset": dict(self.dataset),
            "consent": dict(self.consent),
            "providerJobId": self.provider_job_id,
            "status": self.status,
            "rawStatus": self.raw_status,
            "statusReadAt": self.status_read_at,
            "trainedModel": self.trained_model,
            "usage": dict(self.usage),
            "cost": self.cost,
            "evaluation": self.evaluation,
            "activation": dict(self.activation),
            "events": [dict(e) for e in self.events],
            "createdAt": self.created_at,
            "error": self.error,
            "submitted": self.submitted,
            "consentedOnly": self.consented_only,
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "TrainingRecord":
        return cls(
            job_id=str(payload.get("jobId") or ""),
            provider=dict(payload.get("provider") or {}),
            dataset=dict(payload.get("dataset") or {}),
            consent=dict(payload.get("consent") or {}),
            provider_job_id=payload.get("providerJobId"),
            status=str(payload.get("status") or "consented"),
            raw_status=str(payload.get("rawStatus") or ""),
            status_read_at=str(payload.get("statusReadAt") or ""),
            trained_model=payload.get("trainedModel"),
            usage=dict(payload.get("usage") or {"trainedTokens": None}),
            cost=payload.get("cost"),
            evaluation=payload.get("evaluation"),
            activation=dict(
                payload.get("activation")
                or {"activatedAt": None, "previousModel": None, "rolledBackAt": None}
            ),
            events=[dict(e) for e in (payload.get("events") or []) if isinstance(e, Mapping)],
            created_at=str(payload.get("createdAt") or _now()),
            error=payload.get("error"),
        )

    def append(self, kind: str, **detail) -> dict:
        """Add an event. Events are only ever appended."""
        if kind not in EVENT_KINDS:
            raise TrainingRecordError(f"unknown training event kind: {kind!r}")
        event = {"at": _now(), "kind": kind, **detail}
        self.events.append(event)
        return event


def write(user_key: str, record: TrainingRecord) -> Path:
    """Persist a record atomically under the account's own lock."""
    path = record_path(user_key, record.job_id)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".lock"
    lock_path.touch(exist_ok=True)
    with exclusive_lock(lock_path, namespace=_LOCK_NAMESPACE, key=str(user_key)):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(record.as_dict(), handle, indent=2)
            handle.flush()
            # The consent event must be on disk before anything is uploaded
            # (dev/87: every export appends an audit record before the content
            # is served), so this fsync is the contract, not caution.
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    return path


def read(user_key: str, job_id: str) -> TrainingRecord | None:
    try:
        payload = json.loads(
            record_path(user_key, job_id).read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise TrainingRecordError(f"could not read training job {job_id}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TrainingRecordError(f"training job {job_id} is not an object")
    version = payload.get("recordVersion")
    if isinstance(version, int) and version > RECORD_VERSION:
        # Readable, not writable: a newer Curio wrote it and this one must not
        # rewrite what it may not understand.
        record = TrainingRecord.from_dict(payload)
        record.error = (
            f"this record was written by a newer Curio (version {version}); "
            "it is shown but will not be modified"
        )
        return record
    return TrainingRecord.from_dict(payload)


def list_records(user_key: str) -> list:
    """Every job this account has, newest first."""
    directory = training_dir(user_key)
    if not directory.is_dir():
        return []
    out: list = []
    for path in sorted(directory.glob("train-*.json"), reverse=True):
        if path.name.endswith(".tmp.json"):
            continue
        try:
            record = read(user_key, path.stem)
        except TrainingRecordError:
            continue
        if record is not None:
            out.append(record)
    return out


def in_flight(user_key: str) -> TrainingRecord | None:
    """The account's live job, if it has one.

    One at a time, deliberately: a fine-tune costs money and the failure mode
    of a double-click is worse than the inconvenience of waiting.
    """
    for record in list_records(user_key):
        if record.submitted and not record.terminal:
            return record
    return None


def fold_provider_status(record: TrainingRecord, job) -> TrainingRecord:
    """Fold what the endpoint just said into the record as an event.

    The projection follows the provider; it is never set locally, so the record
    cannot disagree with the endpoint about what happened.
    """
    record.provider_job_id = job.id or record.provider_job_id
    record.status = job.status
    record.raw_status = job.raw_status or job.status
    record.status_read_at = _now()
    if job.trained_model:
        record.trained_model = job.trained_model
    if job.trained_tokens is not None:
        record.usage["trainedTokens"] = job.trained_tokens
    if job.error:
        record.error = job.error
    record.append(
        "status",
        status=job.status,
        rawStatus=job.raw_status or job.status,
        trainedModel=job.trained_model,
        trainedTokens=job.trained_tokens,
        error=job.error,
    )
    return record


def estimate_cost(record: TrainingRecord, price_per_mtoken: Iterable | None) -> dict | None:
    """A USD figure only when an operator supplied a rate, labelled as theirs.

    Curio has no price table and will not invent one — the same rule the usage
    ledger and the evaluation report follow.
    """
    tokens = record.usage.get("trainedTokens")
    if not price_per_mtoken or not isinstance(tokens, int):
        return None
    rates = list(price_per_mtoken)
    if not rates:
        return None
    rate = float(rates[0])
    return {
        "operatorSupplied": True,
        "ratePerMTokenTrained": rate,
        "estimatedUsd": round(tokens / 1_000_000 * rate, 4),
        "trainedTokens": tokens,
    }
