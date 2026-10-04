"""Dataflow runs live in this process: the job registry keyed by dataflow.

A run's thread drives ``run_engine.run_events`` and records what it yields; a
browser that follows the run only subscribes, so closing it changes nothing.
The tables are the record; this holds liveness, the event log and the
cancel flags. ``BOOT_ID`` names this process: a run left queued or running
by another one was cut off by a restart.
"""
from __future__ import annotations

import threading
import uuid

from utk_curio.backend.app.common.job_registry import JobRefused, JobRegistry

#: Runs one account may have going at once.
MAX_ACTIVE_RUNS_PER_USER = 2
#: A finished run stays subscribable this long; after that its steps replay it.
FINISHED_TTL_SECONDS = 15 * 60
MAX_EVENTS_PER_RUN = 5000

BOOT_ID = str(uuid.uuid4())

__all__ = ["JobRefused", "REGISTRY", "BOOT_ID", "cancel_flag", "drop_cancel_flag"]

REGISTRY = JobRegistry(
    name="run",
    kinds=("run",),
    max_active_per_user=MAX_ACTIVE_RUNS_PER_USER,
    finished_ttl_seconds=FINISHED_TTL_SECONDS,
    max_events=MAX_EVENTS_PER_RUN,
    busy_message="This dataflow is already running.",
    cap_message=(
        f"At most {MAX_ACTIVE_RUNS_PER_USER} runs may go at once on your account; "
        "wait for one to finish."
    ),
)

_CANCEL_LOCK = threading.Lock()
_CANCEL: dict[str, threading.Event] = {}


def cancel_flag(run_id: str) -> threading.Event:
    """The flag a run's thread checks before it starts anything new."""
    with _CANCEL_LOCK:
        return _CANCEL.setdefault(run_id, threading.Event())


def existing_cancel_flag(run_id: str) -> threading.Event | None:
    with _CANCEL_LOCK:
        return _CANCEL.get(run_id)


def drop_cancel_flag(run_id: str) -> None:
    with _CANCEL_LOCK:
        _CANCEL.pop(run_id, None)
