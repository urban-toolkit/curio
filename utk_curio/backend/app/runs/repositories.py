"""Database access for dataflow runs.

Every write commits through ``commit_with_retry``: runs are written from the
thread that executes them as well as from requests, and SQLite refuses a write
that lost a race with another writer. The changes passed to it only touch
ORM rows, so replaying them is safe.

Retention runs on every new run, per dataflow: a run is deleted once it is
older than ``RETENTION_DAYS`` and not among the newest ``KEEP_PER_KIND`` runs
of its kind (whole dataflow, or a single node) for that dataflow. An active
run is never deleted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional
from uuid import uuid4

from utk_curio.backend.extensions import commit_with_retry, db
from utk_curio.backend.app.runs.models import (
    ACTIVE_RUN_STATUSES,
    RUN_STATUSES,
    STEP_ROLES,
    STEP_STATUSES,
    TRIGGERS,
    DataflowRun,
    DataflowRunStep,
)

#: How much of a step's stdout and stderr is kept: the end, where a
#: traceback's last line is.
TAIL_CHARS = 4000
#: Runs of each kind a dataflow always keeps, however old.
KEEP_PER_KIND = 50
#: Age past which a run beyond the newest ``KEEP_PER_KIND`` of its kind goes.
RETENTION_DAYS = 30

_RUN_FIELDS = frozenset({
    "status", "started_at", "finished_at", "ok_count", "failed_count",
    "skipped_count", "waiting_count", "error",
})
_STEP_FIELDS = frozenset({
    "status", "started_at", "finished_at", "duration_ms", "output_path",
    "output_type", "installed_dataset_id", "code_sha256", "stdout_tail",
    "stderr_tail", "skip_reason",
})


class NotFoundError(Exception):
    pass


def _check(value, allowed, field: str) -> None:
    if value not in allowed:
        raise ValueError(f"{field} must be one of {', '.join(allowed)}, not {value!r}")


def _tail(text) -> Optional[str]:
    if text is None:
        return None
    text = str(text)
    return text[-TAIL_CHARS:]


def _naive_utc(moment: datetime) -> datetime:
    """*moment* as naive UTC, the way the DateTime columns hand it back."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def create_run(
    *,
    project_id: str,
    user_id: int,
    trigger: str,
    target_node_id: Optional[str] = None,
    rerun_of: Optional[str] = None,
    spec_revision: Optional[int] = None,
    boot_id: Optional[str] = None,
    steps: Iterable[dict] = (),
) -> DataflowRun:
    """Insert a queued run with one pending step per entry of *steps*.

    Each step is a dict with ``node_id`` and optionally ``label``,
    ``node_type``, ``level`` and ``role``. Prunes the dataflow's old runs.
    """
    _check(trigger, TRIGGERS, "trigger")
    step_specs = []
    for step in steps:
        role = step.get("role", "run")
        _check(role, STEP_ROLES, "role")
        if not step.get("node_id"):
            raise ValueError("every step needs a node_id")
        step_specs.append({
            "node_id": str(step["node_id"]),
            "label": step.get("label"),
            "node_type": step.get("node_type"),
            "level": int(step.get("level") or 0),
            "role": role,
        })
    run_id = str(uuid4())

    def _apply() -> DataflowRun:
        run = DataflowRun(
            id=run_id,
            project_id=project_id,
            user_id=user_id,
            trigger=trigger,
            target_node_id=target_node_id or None,
            rerun_of=rerun_of,
            spec_revision=spec_revision,
            status="queued",
            boot_id=boot_id,
        )
        run.steps = [DataflowRunStep(status="pending", **spec) for spec in step_specs]
        db.session.add(run)
        return run

    run = commit_with_retry(_apply)
    prune_project_runs(project_id)
    return run


def get_run(run_id: str) -> Optional[DataflowRun]:
    return db.session.get(DataflowRun, run_id)


def list_project_runs(
    project_id: str,
    *,
    whole_dataflow: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[DataflowRun]:
    """A dataflow's runs, newest first; *whole_dataflow* narrows to one kind."""
    query = DataflowRun.query.filter_by(project_id=project_id)
    query = _of_kind(query, whole_dataflow)
    return (
        query.order_by(DataflowRun.created_at.desc(), DataflowRun.id.desc())
        .offset(offset).limit(limit).all()
    )


def list_user_runs(
    user_id: int,
    *,
    status: Optional[str] = None,
    whole_dataflow: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[DataflowRun]:
    """Every run a user started, newest first, optionally of one status and kind."""
    query = DataflowRun.query.filter_by(user_id=user_id)
    if status is not None:
        _check(status, RUN_STATUSES, "status")
        query = query.filter(DataflowRun.status == status)
    query = _of_kind(query, whole_dataflow)
    return (
        query.order_by(DataflowRun.created_at.desc(), DataflowRun.id.desc())
        .offset(offset).limit(limit).all()
    )


def _of_kind(query, whole_dataflow: Optional[bool]):
    if whole_dataflow is True:
        return query.filter(DataflowRun.target_node_id.is_(None))
    if whole_dataflow is False:
        return query.filter(DataflowRun.target_node_id.isnot(None))
    return query


def update_run(run_id: str, **fields) -> DataflowRun:
    """Set *fields* on a run. Only its outcome and timing can change."""
    unknown = set(fields) - _RUN_FIELDS
    if unknown:
        raise ValueError(f"a run's {', '.join(sorted(unknown))} cannot change")
    if "status" in fields:
        _check(fields["status"], RUN_STATUSES, "status")

    def _apply() -> DataflowRun:
        run = get_run(run_id)
        if run is None:
            raise NotFoundError(f"run {run_id} not found")
        for name, value in fields.items():
            setattr(run, name, value)
        return run

    return commit_with_retry(_apply)


def update_step(run_id: str, node_id: str, **fields) -> DataflowRunStep:
    """Set *fields* on one step; stdout and stderr keep their last ``TAIL_CHARS``."""
    unknown = set(fields) - _STEP_FIELDS
    if unknown:
        raise ValueError(f"a step's {', '.join(sorted(unknown))} cannot change")
    if "status" in fields:
        _check(fields["status"], STEP_STATUSES, "status")
    for name in ("stdout_tail", "stderr_tail"):
        if name in fields:
            fields[name] = _tail(fields[name])

    def _apply() -> DataflowRunStep:
        step = DataflowRunStep.query.filter_by(run_id=run_id, node_id=node_id).first()
        if step is None:
            raise NotFoundError(f"run {run_id} has no step for node {node_id}")
        for name, value in fields.items():
            setattr(step, name, value)
        return step

    return commit_with_retry(_apply)


def prune_project_runs(project_id: str, *, now: Optional[datetime] = None) -> int:
    """Apply the retention rule to one dataflow's runs; returns how many went.

    Deleted through the ORM so each run's steps go with it.
    """
    cutoff = _naive_utc((now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS))

    def _apply() -> int:
        removed = 0
        for whole in (True, False):
            runs = _of_kind(DataflowRun.query.filter_by(project_id=project_id), whole).order_by(
                DataflowRun.created_at.desc(), DataflowRun.id.desc()
            ).all()
            for run in runs[KEEP_PER_KIND:]:
                if run.status in ACTIVE_RUN_STATUSES:
                    continue
                if _naive_utc(run.created_at) < cutoff:
                    db.session.delete(run)
                    removed += 1
        return removed

    return commit_with_retry(_apply)
