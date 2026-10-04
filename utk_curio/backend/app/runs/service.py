"""Dataflow runs on the server: start one, read them, follow one, cancel one.

A run executes the saved dataflow on a thread of its own (``runs/jobs.py``),
so it goes on whether or not any browser is open. Its record is the
``dataflow_run`` row and one ``dataflow_run_step`` row per node; the thread
writes them as ``run_engine.run_events`` yields. The sign-in token that
started the run tags its artifacts in the sandbox, as Play's does; it lives
on the thread only, never in a table, an event or a log line.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Iterator, Optional

from utk_curio.backend.extensions import commit_with_retry, db
from utk_curio.backend.app.runs import jobs
from utk_curio.backend.app.runs import repositories as runs_repo
from utk_curio.backend.app.runs.models import ACTIVE_RUN_STATUSES, DataflowRun, DataflowRunStep

log = logging.getLogger(__name__)


class RunError(Exception):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def _at(timestamp: Optional[float]) -> Optional[datetime]:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)


def _iso(moment: Optional[datetime]) -> Optional[str]:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.isoformat()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def current_code_hashes(user, project_id: str) -> dict:
    """``{nodeId: digest}`` of each node's code in the dataflow as saved now,
    hashed as a step hashes the code it ran."""
    from utk_curio.backend.app.execution.runtime_journal import normalized_code_sha256
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    spec = storage.read_spec(_user_dir_key(user), project_id) or {}
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    return {
        node["id"]: normalized_code_sha256(node.get("content") or "")
        for node in nodes if isinstance(node, dict) and node.get("id")
    }


def step_payload(step: DataflowRunStep, current: Optional[dict] = None) -> dict:
    """*current* (:func:`current_code_hashes`) adds ``codeCurrent``: whether the
    node still holds the code this step ran, so a canvas opened later can show
    the step's output as the node's own."""
    payload = {
        "nodeId": step.node_id,
        "label": step.label,
        "nodeType": step.node_type,
        "level": step.level,
        "role": step.role,
        "status": step.status,
        "startedAt": _iso(step.started_at),
        "finishedAt": _iso(step.finished_at),
        "durationMs": step.duration_ms,
        "outputPath": step.output_path,
        "outputType": step.output_type,
        "installedDatasetId": step.installed_dataset_id,
        "codeSha256": step.code_sha256,
        "stdoutTail": step.stdout_tail,
        "stderrTail": step.stderr_tail,
        "skipReason": step.skip_reason,
        "missingModule": json.loads(step.missing_module) if step.missing_module else None,
    }
    if current is not None:
        payload["codeCurrent"] = bool(step.code_sha256) and current.get(step.node_id) == step.code_sha256
    return payload


def run_payload(run: DataflowRun, *, steps: bool = False, current: Optional[dict] = None) -> dict:
    payload = {
        "id": run.id,
        "projectId": run.project_id,
        "projectName": run.project.name if run.project is not None else None,
        "trigger": run.trigger,
        "targetNodeId": run.target_node_id,
        "wholeDataflow": run.whole_dataflow,
        "rerunOf": run.rerun_of,
        "specRevision": run.spec_revision,
        "status": run.status,
        "createdAt": _iso(run.created_at),
        "startedAt": _iso(run.started_at),
        "finishedAt": _iso(run.finished_at),
        "counts": {
            "ok": run.ok_count, "failed": run.failed_count,
            "skipped": run.skipped_count, "waiting": run.waiting_count,
        },
        "error": run.error,
        "live": jobs.REGISTRY.is_live(run.id),
    }
    if steps:
        payload["steps"] = [step_payload(step, current) for step in run.steps]
    return payload


# ---------------------------------------------------------------------------
# Restarts
# ---------------------------------------------------------------------------

def interrupt_runs_of_other_processes() -> int:
    """A run left queued or running by another backend process was cut off by
    a restart: it, and its steps that had not finished, become ``interrupted``.
    Nothing runs again by itself. Returns how many runs changed."""

    def _apply() -> int:
        stale = DataflowRun.query.filter(
            DataflowRun.status.in_(ACTIVE_RUN_STATUSES),
            db.or_(DataflowRun.boot_id.is_(None), DataflowRun.boot_id != jobs.BOOT_ID),
        ).all()
        now = datetime.now(timezone.utc)
        for run in stale:
            run.status = "interrupted"
            run.finished_at = run.finished_at or now
            run.error = run.error or "The backend restarted while this run was going."
            for step in run.steps:
                if step.status in ("pending", "running"):
                    step.status = "interrupted"
        return len(stale)

    return commit_with_retry(_apply)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def get_run(user, run_id: str) -> DataflowRun:
    """A run of *user*'s, or 404."""
    interrupt_runs_of_other_processes()
    run = runs_repo.get_run(run_id)
    if run is None or run.user_id != user.id:
        raise RunError("Run not found.", 404)
    return run


def list_project_runs(user, project_id: str, *, whole_dataflow=None, limit=50, offset=0) -> list:
    from utk_curio.backend.app.projects import repositories as projects_repo

    try:
        projects_repo.get_for_user(project_id, user.id)
    except projects_repo.NotFoundError as exc:
        raise RunError("Dataflow not found.", 404) from exc
    interrupt_runs_of_other_processes()
    return runs_repo.list_project_runs(
        project_id, whole_dataflow=whole_dataflow, limit=limit, offset=offset,
    )


def list_user_runs(user, *, status=None, whole_dataflow=None, limit=50, offset=0) -> list:
    interrupt_runs_of_other_processes()
    try:
        return runs_repo.list_user_runs(
            user.id, status=status, whole_dataflow=whole_dataflow, limit=limit, offset=offset,
        )
    except ValueError as exc:
        raise RunError(str(exc), 400) from exc


def replay_from_steps(run: DataflowRun) -> Iterator[tuple[str, dict]]:
    """The events of a run nobody holds any more, rebuilt from its record."""
    yield "run_started", {"nodeIds": [step.node_id for step in run.steps]}
    for step in run.steps:
        if step.status in ("pending", "running"):
            continue
        payload = {"nodeId": step.node_id, "status": step.status}
        for key, value in (
            ("output", {"path": step.output_path, "dataType": step.output_type}
             if step.output_path else None),
            ("stdoutTail", step.stdout_tail), ("stderrTail", step.stderr_tail),
            ("skipReason", step.skip_reason), ("durationMs", step.duration_ms),
        ):
            if value is not None:
                payload[key] = value
        yield "step_finished", payload
    if run.status not in ACTIVE_RUN_STATUSES:
        yield "run_finished", {
            "status": run.status, "ok": run.ok_count, "failed": run.failed_count,
            "skipped": run.skipped_count, "waiting": run.waiting_count,
        }


def follow(run: DataflowRun) -> Iterator[tuple[str, dict]]:
    """The run's events: replayed and then tailed while this process holds it,
    rebuilt from its record once it does not."""
    job = jobs.REGISTRY.get_job(run.id)
    if job is not None:
        yield from jobs.REGISTRY.subscribe(job)
    else:
        yield from replay_from_steps(run)


# ---------------------------------------------------------------------------
# Starting
# ---------------------------------------------------------------------------

def start_run(
    user,
    token: Optional[str],
    project_id: str,
    *,
    target_node_id: Optional[str] = None,
    reuse: Optional[dict] = None,
    spec_revision: Optional[int] = None,
    trigger: Optional[str] = None,
    rerun_of: Optional[str] = None,
) -> DataflowRun:
    """Run *project_id*'s saved dataflow, or one node of it, on a thread of its
    own. Refused for a user who may not save it, for a revision that is not the
    saved one, while the dataflow already runs, and past the account's cap."""
    from flask import current_app

    from utk_curio.backend.app.execution.run_engine import PlanError, plan_run
    from utk_curio.backend.app.packages.service import roster_templates
    from utk_curio.backend.app.projects import repositories as projects_repo
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.users.capabilities import run_refusal

    refusal = run_refusal(user)
    if refusal:
        raise RunError(refusal, 403)
    try:
        projects_repo.get_for_user(project_id, user.id)
    except projects_repo.NotFoundError as exc:
        raise RunError("Dataflow not found.", 404) from exc
    ukey = _user_dir_key(user)
    spec = storage.read_spec(ukey, project_id)
    if spec is None:
        raise RunError("Dataflow not found.", 404)
    current = storage.spec_revision(ukey, project_id)
    if spec_revision is not None and int(spec_revision) != current:
        raise RunError(
            "The dataflow changed since this tab saved it. Save it again, then run.",
            409, specRevision=current,
        )
    try:
        plan = plan_run(
            spec, target_node_id=target_node_id, reuse=reuse,
            templates=roster_templates(ukey, project_id),
        )
    except PlanError as exc:
        raise RunError(str(exc), 422) from exc

    user_key = str(user.id)
    try:
        jobs.REGISTRY.check_can_start(user_key, project_id)
    except jobs.JobRefused as exc:
        raise RunError(str(exc), exc.status, runId=exc.job_id) from exc

    run = runs_repo.create_run(
        project_id=project_id,
        user_id=user.id,
        trigger=trigger or ("node" if target_node_id else "all"),
        target_node_id=target_node_id,
        rerun_of=rerun_of,
        spec_revision=current,
        boot_id=jobs.BOOT_ID,
        steps=[
            {"node_id": s.node_id, "label": s.label, "node_type": s.node_type,
             "level": s.level, "role": s.role}
            for s in plan.steps.values()
        ],
    )
    run_id = run.id
    app = current_app._get_current_object()
    events = _run_thread(app, run_id, user.id, token, project_id, plan, spec)
    try:
        jobs.REGISTRY.start(
            user_key=user_key, project_id=project_id, key=project_id,
            kind="run", job_id=run_id, events=events,
            app_context=app.app_context,
            # A failure's text never carries the token into an event or a log.
            redact_values={"session": token} if token else None,
        )
    except jobs.JobRefused as exc:
        # Lost a race with another start between the check and here.
        runs_repo.update_run(
            run_id, status="cancelled", error=str(exc),
            finished_at=datetime.now(timezone.utc),
        )
        raise RunError(str(exc), exc.status, runId=exc.job_id) from exc
    return runs_repo.get_run(run_id)


def _run_thread(app, run_id, user_id, token, project_id, plan, spec) -> Iterator[tuple[str, dict]]:
    """The run's thread: drive the engine, record each event, pass it on."""
    from utk_curio.backend import config
    from utk_curio.backend.app.execution import node_exec, runtime_journal
    from utk_curio.backend.app.execution.run_engine import run_events
    from utk_curio.backend.app.execution.save_policy import (
        records_output_on_save,
        should_save_output_on_run,
    )
    from utk_curio.backend.app.projects.dashboard_payload import dashboard_source_node_ids
    from utk_curio.backend.app.projects.schemas import OutputRef
    from utk_curio.backend.app.projects.services import record_node_outputs
    from utk_curio.backend.app.scenario_catalog.domain.parts import scenario_source_node_ids
    from utk_curio.backend.app.users.models import User

    default_save = bool(config.CURIO_DEFAULT_SAVE_NODE_OUTPUT)
    # What a pinned tile reads and what a scenario's context and outcomes
    # produce, saved whatever each node's own toggle says: the canvas's
    # `savedSourceNodeIds`.
    sources = dashboard_source_node_ids(spec) | scenario_source_node_ids(spec)
    cancelled = jobs.cancel_flag(run_id)

    def execute(step, code, input_ref):
        jobs.hold_point()
        # The request that started the run is gone: load the account here.
        user = db.session.get(User, user_id)
        node_run = node_exec.NodeRun(
            code=code,
            node_type=step.node_type,
            node_id=step.node_id,
            input=input_ref,
            dataflow_id=project_id,
            node_name=step.label,
            save_output_dataset=should_save_output_on_run(
                step.node, default_save, step.node_id in sources,
            ),
        )
        run_node = (
            node_exec.execute_js_node if step.engine == "javascript"
            else node_exec.execute_python_node
        )
        reply, _status = run_node(user, token, node_run)
        return reply

    def wrap(fn):
        def in_context():
            with app.app_context():
                return fn()
        return in_context

    try:
        runs_repo.update_run(run_id, status="running", started_at=datetime.now(timezone.utc))
        for kind, payload in run_events(plan, execute, cancelled=cancelled, wrap=wrap):
            if kind == "step_started":
                runs_repo.update_step(
                    run_id, payload["nodeId"], status="running", started_at=_at(payload["startedAt"]),
                )
            elif kind == "step_finished":
                _record_step(run_id, plan.steps[payload["nodeId"]], payload, runtime_journal)
                output = payload.get("output") or {}
                step = plan.steps[payload["nodeId"]]
                if payload["status"] == "ok" and records_output_on_save(
                    step.node, default_save, sources,
                ):
                    try:
                        record_node_outputs(db.session.get(User, user_id), project_id, [OutputRef(
                            node_id=step.node_id,
                            filename=output.get("dataset") or output.get("path"),
                            data_type=output.get("dataType"),
                        )])
                    except Exception:  # noqa: BLE001 - the run goes on; the output is just not recorded
                        log.exception("run %s could not record the output of %s", run_id, step.node_id)
            elif kind == "run_finished":
                runs_repo.update_run(
                    run_id, status=payload["status"], finished_at=datetime.now(timezone.utc),
                    ok_count=payload["ok"], failed_count=payload["failed"],
                    skipped_count=payload["skipped"], waiting_count=payload["waiting"],
                )
            yield kind, payload
    except Exception as exc:
        runs_repo.update_run(
            run_id, status="failed", finished_at=datetime.now(timezone.utc),
            error=f"The run stopped: {type(exc).__name__}: {str(exc)[:300]}",
        )
        raise
    finally:
        jobs.drop_cancel_flag(run_id)


def _record_step(run_id, step, payload, runtime_journal) -> None:
    output = payload.get("output") or {}
    reply = payload.get("reply") or {}
    installed = reply.get("installedDataset") if isinstance(reply.get("installedDataset"), dict) else {}
    fields = {
        "status": payload["status"],
        "finished_at": _at(payload.get("finishedAt")) or datetime.now(timezone.utc),
        "skip_reason": payload.get("skipReason"),
    }
    if payload.get("startedAt") is not None:
        fields["started_at"] = _at(payload["startedAt"])
    if payload.get("durationMs") is not None:
        fields["duration_ms"] = payload["durationMs"]
    if step.role == "run" and payload["status"] in ("ok", "error", "cancelled"):
        fields.update(
            output_path=output.get("path") or None,
            output_type=output.get("dataType") or None,
            installed_dataset_id=installed.get("id"),
            code_sha256=runtime_journal.normalized_code_sha256(step.content),
            stdout_tail=payload.get("stdoutTail"),
            stderr_tail=payload.get("stderrTail"),
            missing_module=json.dumps(reply["missingModule"]) if reply.get("missingModule") else None,
        )
    runs_repo.update_step(run_id, step.node_id, **fields)


# ---------------------------------------------------------------------------
# Cancel, run again, and what a tab reports
# ---------------------------------------------------------------------------

def cancel_run(user, run_id: str) -> DataflowRun:
    """Stop *run_id* before its next node starts. The node already running
    finishes, and its output is dropped."""
    run = get_run(user, run_id)
    flag = jobs.existing_cancel_flag(run_id)
    if run.status not in ACTIVE_RUN_STATUSES or flag is None:
        raise RunError("This run is not going.", 409)
    flag.set()
    return run


def rerun(user, token: Optional[str], run_id: str) -> DataflowRun:
    """Run what *run_id* ran again: the whole dataflow, or the same node."""
    run = get_run(user, run_id)
    return start_run(
        user, token, run.project_id,
        target_node_id=run.target_node_id, trigger="rerun", rerun_of=run.id,
    )


def report_browser_step(user, run_id: str, node_id: str, *, status: str, message: str = "") -> DataflowRun:
    """A tab ran a node only the browser can, or one that waited for it, and
    says how it went. Once nothing waits any more, the run has its outcome."""
    if status not in ("ok", "error"):
        raise RunError("status must be ok or error", 400)
    run = get_run(user, run_id)
    if run.status in ACTIVE_RUN_STATUSES:
        # The server's part ends first; its outcome would overwrite a report.
        raise RunError("The run is still going; report once it has finished.", 409)
    step = next((s for s in run.steps if s.node_id == node_id), None)
    if step is None:
        raise RunError("This run has no such node.", 404)
    if step.role != "browser" and step.status != "waiting":
        raise RunError("Only a node the browser runs can be reported.", 409)
    runs_repo.update_step(
        run_id, node_id, status=status, finished_at=datetime.now(timezone.utc),
        stderr_tail=message if status == "error" else None, skip_reason=None,
    )
    run = runs_repo.get_run(run_id)
    if run.status == "needs_canvas":
        waiting = sum(1 for s in run.steps if s.status == "waiting")
        failed = sum(1 for s in run.steps if s.status == "error")
        ok = sum(1 for s in run.steps if s.status == "ok")
        fields = {"waiting_count": waiting, "failed_count": failed, "ok_count": ok}
        if not waiting:
            fields["status"] = "failed" if failed else "succeeded"
        runs_repo.update_run(run_id, **fields)
    return runs_repo.get_run(run_id)
