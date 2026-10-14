"""Published dashboards: a dataflow its owner lets others run.

The owner publishes a snapshot of the saved dataflow under a secret link token
(``models.PublishedDashboard``). Whoever holds the link, signed in or not as
the owner chose, runs that snapshot on the server with their own values for
the widgets of its pinned tiles, as a published app does:

- the run executes as the owner (their packages, datasets and keys), under a
  key of its own that tags its artifacts in the sandbox;
- it writes nothing of the owner's: no output or saved file installed, no run
  record, no journal entry (``node_exec.NodeRun.published``);
- a viewer sends values, never code, and only for the widgets a pinned tile
  shows, each checked against its widget's kind (:func:`check_inputs`);
- runs are capped per link and rate-limited per link and per address, and the
  same values on the same snapshot reuse the last run (:func:`start_run`);
- a viewer reads a run's events with their logs taken out, and only the
  artifacts the run produced (:func:`allows_artifact`).

Runs live in this process (``PUBLISHED_REGISTRY``) and are dropped with their
cache entry once they have been finished for ``FINISHED_TTL_SECONDS``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator, Optional

from utk_curio.backend.app.common.job_registry import JobRefused, JobRegistry
from utk_curio.backend.app.common.token_bucket import TokenBucket
from utk_curio.backend.extensions import commit_with_retry, db
from utk_curio.backend.app.published.models import ACCESS_LEVELS, PublishedDashboard

log = logging.getLogger(__name__)

#: Runs of one link that may go at once.
MAX_ACTIVE_RUNS_PER_LINK = 3
#: How long a finished run keeps its events and artifacts readable, and its cache entry.
FINISHED_TTL_SECONDS = 30 * 60
#: How long a run may go before it is cancelled.
MAX_RUN_SECONDS = 15 * 60
#: Runs one address may start on one link: a burst, refilled over ten minutes.
ADDRESS_BURST, ADDRESS_PER_SECOND = 10, 10 / 600
#: Runs one link may start in all: a burst, refilled over an hour.
LINK_BURST, LINK_PER_SECOND = 60, 60 / 3600
#: Code that saves or reads files a dataflow saved: those files are installed
#: into the owner's catalog, which a published run never writes.
_SAVED_FILE_CALLS = re.compile(r"\bcurio_(save_file|save_folder|computed_path)\s*\(")
#: The keys of an output that name an artifact.
_ARTIFACT_KEYS = ("path", "dataset", "filename", "fileName")

PUBLISHED_REGISTRY = JobRegistry(
    name="published",
    kinds=("published",),
    max_active_per_user=MAX_ACTIVE_RUNS_PER_LINK,
    finished_ttl_seconds=FINISHED_TTL_SECONDS,
    max_events=5000,
    busy_message="This run is already going.",
    cap_message=(
        f"This dashboard already has {MAX_ACTIVE_RUNS_PER_LINK} runs going. "
        "Wait for one to finish, then run again."
    ),
)


class PublishError(Exception):
    """A refusal, with the HTTP status the route answers with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Publishing (the owner)
# ---------------------------------------------------------------------------

def _owned_project(user, project_id: str):
    from utk_curio.backend.app.projects import repositories as projects_repo
    from utk_curio.backend.app.users.capabilities import run_refusal

    refusal = run_refusal(user)
    if refusal:
        raise PublishError(refusal.replace("Runs on the server", "Publishing a dashboard"), 403)
    try:
        return projects_repo.get_for_user(project_id, user.id)
    except projects_repo.NotFoundError as exc:
        raise PublishError("Dataflow not found.", 404) from exc


def _nodes(spec: dict) -> list[dict]:
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    nodes = dataflow.get("nodes") if isinstance(dataflow, dict) else None
    return [n for n in nodes or [] if isinstance(n, dict) and n.get("id")]


def input_schema(spec: dict) -> list[dict]:
    """The inputs a viewer may set: each widget of each pinned tile."""
    from utk_curio.backend.app.execution.code_references import effective_value, normalize_widgets

    schema = []
    for node in _nodes(spec):
        if not node.get("dashboardPinned"):
            continue
        for widget in normalize_widgets((node.get("metadata") or {}).get("widgets")):
            if widget.get("type") == "file":
                continue
            schema.append({
                "nodeId": node["id"],
                "name": widget["name"],
                "type": widget["type"],
                "label": widget.get("label") or widget["name"],
                "options": widget.get("options") or {},
                "value": effective_value(widget),
            })
    return schema


def publish_refusal(spec: dict) -> Optional[str]:
    """Why *spec* cannot be published, or None."""
    nodes = _nodes(spec)
    if not any(n.get("dashboardPinned") for n in nodes):
        return "Pin at least one node to the dashboard before publishing it."
    saving = [
        (n.get("metadata") or {}).get("packageTemplateLabel") or n.get("title") or n["id"]
        for n in nodes
        if isinstance(n.get("content"), str) and _SAVED_FILE_CALLS.search(n["content"])
    ]
    if saving:
        return (
            "This dataflow saves files from its code (" + ", ".join(sorted(map(str, saving))[:5])
            + "), which a published run cannot do yet: its runs save nothing of yours."
        )
    return None


def _payload(row: PublishedDashboard) -> dict:
    spec = json.loads(row.spec_json)
    return {
        "projectId": row.project_id,
        "token": row.token,
        "access": row.access,
        "specRevision": row.spec_revision,
        "publishedAt": row.updated_at.isoformat() if row.updated_at else None,
        "inputs": input_schema(spec),
    }


def get_publication(user, project_id: str) -> Optional[dict]:
    _owned_project(user, project_id)
    row = db.session.get(PublishedDashboard, project_id)
    return _payload(row) if row else None


def publish(user, project_id: str, access: str) -> dict:
    """Publish the saved dataflow as it is now, or publish it again: the
    snapshot is replaced, the link kept."""
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    if access not in ACCESS_LEVELS:
        raise PublishError(f"'access' must be one of {', '.join(ACCESS_LEVELS)}.")
    _owned_project(user, project_id)
    ukey = _user_dir_key(user)
    spec = storage.read_spec(ukey, project_id)
    if spec is None:
        raise PublishError("Dataflow not found.", 404)
    refusal = publish_refusal(spec)
    if refusal:
        raise PublishError(refusal, 422)
    spec_json = json.dumps(spec)
    revision = storage.spec_revision(ukey, project_id)

    def apply():
        row = db.session.get(PublishedDashboard, project_id)
        if row is None:
            row = PublishedDashboard(project_id=project_id, user_id=user.id, token=secrets.token_urlsafe(24))
            db.session.add(row)
        row.access = access
        row.spec_json = spec_json
        row.spec_revision = revision
        return row

    return _payload(commit_with_retry(apply))


def unpublish(user, project_id: str) -> None:
    _owned_project(user, project_id)

    def apply():
        row = db.session.get(PublishedDashboard, project_id)
        if row is not None:
            db.session.delete(row)

    commit_with_retry(apply)


# ---------------------------------------------------------------------------
# What a viewer sends
# ---------------------------------------------------------------------------

def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _within(value, options: dict) -> bool:
    low, high = options.get("min"), options.get("max")
    return (not _finite(low) or value >= low) and (not _finite(high) or value <= high)


def _choices(options: dict) -> list:
    return [c for c in options.get("choices") or [] if isinstance(c, str)]


_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?(Z|[+-]\d{2}:?\d{2})?$")
_MAX_TEXT = 2000
_MAX_LIST = 1000


def value_problem(widget: dict, value) -> Optional[str]:
    """Why *value* is not one the widget could hold, or None."""
    kind, options = widget.get("type"), widget.get("options") or {}
    if kind in ("number", "slider"):
        if not _finite(value):
            return "a number"
        return None if _within(value, options) else "a number within its range"
    if kind == "checkbox":
        return None if isinstance(value, bool) else "true or false"
    if kind == "text":
        return None if isinstance(value, str) and len(value) <= _MAX_TEXT else f"a text of at most {_MAX_TEXT} characters"
    if kind == "choice":
        return None if isinstance(value, str) and value in _choices(options) else "one of its choices"
    if kind in ("checkbox-group", "multi-select"):
        allowed = set(_choices(options))
        ok = isinstance(value, list) and all(isinstance(v, str) and v in allowed for v in value)
        return None if ok else "a list of its choices"
    if kind == "datetime":
        return None if isinstance(value, str) and _DATETIME.match(value) else "a date and time"
    if kind == "location":
        ok = (
            isinstance(value, dict) and set(value) == {"lat", "lon"}
            and _finite(value["lat"]) and -90 <= value["lat"] <= 90
            and _finite(value["lon"]) and -180 <= value["lon"] <= 180
        )
        return None if ok else "a latitude and longitude"
    if kind == "number-list":
        ok = isinstance(value, list) and len(value) <= _MAX_LIST and all(_finite(v) for v in value)
        return None if ok else "a list of numbers"
    if kind == "text-list":
        ok = isinstance(value, list) and len(value) <= _MAX_LIST and all(
            isinstance(v, str) and len(v) <= _MAX_TEXT for v in value
        )
        return None if ok else "a list of texts"
    if kind == "range":
        ok = (
            isinstance(value, list) and len(value) == 2 and all(_finite(v) for v in value)
            and value[0] <= value[1] and _within(value[0], options) and _within(value[1], options)
        )
        return None if ok else "a low and a high number within its range"
    return "a value a viewer can set"


def check_inputs(spec: dict, inputs: object) -> dict:
    """*inputs* (``{nodeId: {widgetName: value}}``) checked against the inputs
    the snapshot lets a viewer set; anything else is refused with a 422."""
    if inputs is None:
        return {}
    if not isinstance(inputs, dict):
        raise PublishError("'inputs' must map node ids to widget values.", 422)
    allowed = {(i["nodeId"], i["name"]): i for i in input_schema(spec)}
    checked: dict = {}
    for node_id, values in inputs.items():
        if not isinstance(values, dict):
            raise PublishError("'inputs' must map node ids to widget values.", 422)
        for name, value in values.items():
            widget = allowed.get((node_id, name))
            if widget is None:
                raise PublishError(f"{name!r} is not an input of this dashboard.", 422)
            problem = value_problem(widget, value)
            if problem:
                raise PublishError(f"{widget['label']} must be {problem}.", 422)
            checked.setdefault(node_id, {})[name] = value
    return checked


def with_inputs(spec: dict, inputs: dict) -> dict:
    """A copy of *spec* whose widgets hold the viewer's values."""
    spec = json.loads(json.dumps(spec))
    for node in _nodes(spec):
        values = inputs.get(node["id"])
        if not values:
            continue
        for widget in (node.get("metadata") or {}).get("widgets") or []:
            if isinstance(widget, dict) and widget.get("name") in values:
                widget["value"] = values[widget["name"]]
    return spec


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

@dataclass
class PublishedRun:
    run_id: str
    key: str
    project_id: str
    cache_key: str
    steps: dict = field(default_factory=dict)  # nodeId -> {"role", "status", "label"}
    status: str = "queued"
    artifacts: set = field(default_factory=set)
    created_at: float = field(default_factory=time.time)


_LOCK = threading.Lock()
_RUNS: dict[str, PublishedRun] = {}
_CACHE: dict[str, str] = {}
_BUCKETS: dict[tuple, TokenBucket] = {}


def reset_for_tests() -> None:
    with _LOCK:
        _RUNS.clear()
        _CACHE.clear()
        _BUCKETS.clear()
    PUBLISHED_REGISTRY.reset()


def _sweep() -> None:
    """Drop the runs the registry no longer holds, and their cache entries."""
    PUBLISHED_REGISTRY.sweep_finished()
    with _LOCK:
        for run_id in [r for r in _RUNS if PUBLISHED_REGISTRY.get_job(r) is None]:
            run = _RUNS.pop(run_id)
            if _CACHE.get(run.cache_key) == run_id:
                del _CACHE[run.cache_key]


def _take(bucket_key: tuple, burst: int, per_second: float) -> bool:
    now = time.monotonic()
    with _LOCK:
        bucket = _BUCKETS.get(bucket_key)
        if bucket is None:
            bucket = _BUCKETS[bucket_key] = TokenBucket(burst, per_second, now)
        return bucket.take(now)


def describe(token: str) -> dict:
    """What a viewer's page needs to know about a link."""
    row = PublishedDashboard.query.filter_by(token=token).first()
    if row is None:
        raise PublishError("This dashboard is not published, or its link has changed.", 404)
    spec = json.loads(row.spec_json)
    return {
        "projectId": row.project_id,
        "access": row.access,
        "specRevision": row.spec_revision,
        "inputs": input_schema(spec),
    }


def _cache_key(row: PublishedDashboard, inputs: dict) -> str:
    raw = json.dumps({"rev": row.spec_revision, "at": str(row.updated_at), "inputs": inputs}, sort_keys=True)
    return hashlib.sha256(f"{row.project_id}:{raw}".encode()).hexdigest()


def _collect_artifacts(value, into: set) -> None:
    """Every artifact name *value* holds, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _ARTIFACT_KEYS and isinstance(item, str) and item.strip():
                into.add(item.strip())
            else:
                _collect_artifacts(item, into)
    elif isinstance(value, list):
        for item in value:
            _collect_artifacts(item, into)


def _error_line(stderr) -> Optional[str]:
    """A viewer's view of a failure: its last line, without file paths."""
    text = "\n".join(stderr) if isinstance(stderr, list) else str(stderr or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    line = re.sub(r"(/[^\s/:'\"]+)+/?", "<path>", lines[-1])
    return line[:300]


def _viewer_event(kind: str, payload: dict) -> dict:
    """*payload* as a viewer reads it: outputs and timing, never logs."""
    if kind != "step_finished":
        return payload
    out = {k: payload[k] for k in ("nodeId", "status", "output", "startedAt", "finishedAt", "durationMs", "skipReason") if k in payload}
    reply = payload.get("reply") or {}
    error = _error_line(payload.get("stderrTail") or reply.get("stderr")) if payload.get("status") == "error" else None
    if reply or error:
        out["reply"] = {
            "output": reply.get("output") or payload.get("output") or {},
            "input": reply.get("input") or "",
            "stdout": [],
            "stderr": error or "",
        }
    return out


def start_run(token: str, inputs: object, *, user=None, address: str = "") -> dict:
    """Start a run of the snapshot behind *token* with *inputs*, or reuse the
    last run of the same values. ``{runId, key, cached}``."""
    from flask import current_app

    from utk_curio.backend.app.execution.node_names import template_labels
    from utk_curio.backend.app.execution.run_engine import PlanError, plan_run
    from utk_curio.backend.app.packages.service import roster_templates
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.users.models import User

    row = PublishedDashboard.query.filter_by(token=token).first()
    if row is None:
        raise PublishError("This dashboard is not published, or its link has changed.", 404)
    if row.access == "signed-in" and (user is None or getattr(user, "is_guest", False)):
        raise PublishError("Sign in to run this dashboard.", 401)
    spec = json.loads(row.spec_json)
    checked = check_inputs(spec, inputs)
    cache_key = _cache_key(row, checked)

    _sweep()
    with _LOCK:
        cached = _RUNS.get(_CACHE.get(cache_key, ""))
    if cached is not None and cached.status in ("queued", "running", "succeeded", "needs_canvas"):
        return {"runId": cached.run_id, "key": cached.key, "cached": True}

    if not _take(("address", token, address), ADDRESS_BURST, ADDRESS_PER_SECOND):
        raise PublishError("Too many runs from here. Wait a few minutes, then run again.", 429)
    if not _take(("link", token), LINK_BURST, LINK_PER_SECOND):
        raise PublishError("This dashboard has been run too often in the last hour. Try again later.", 429)

    owner = db.session.get(User, row.user_id)
    if owner is None:
        raise PublishError("This dashboard is not published, or its link has changed.", 404)
    ukey = _user_dir_key(owner)
    run_spec = with_inputs(spec, checked)
    try:
        plan = plan_run(
            run_spec,
            templates=roster_templates(ukey, row.project_id),
            labels=template_labels(ukey, row.project_id),
        )
    except PlanError as exc:
        raise PublishError(str(exc), 422) from exc

    user_key = f"published:{row.project_id}"
    run = PublishedRun(
        run_id=secrets.token_hex(16), key=secrets.token_urlsafe(24),
        project_id=row.project_id, cache_key=cache_key,
        steps={s.node_id: {"role": s.role, "status": "pending", "label": s.label} for s in plan.steps.values()},
    )
    try:
        PUBLISHED_REGISTRY.check_can_start(user_key, run.run_id)
    except JobRefused as exc:
        raise PublishError(str(exc), exc.status) from exc
    with _LOCK:
        _RUNS[run.run_id] = run
        _CACHE[cache_key] = run.run_id
    app = current_app._get_current_object()
    try:
        PUBLISHED_REGISTRY.start(
            user_key=user_key, project_id=row.project_id, key=run.run_id,
            kind="published", job_id=run.run_id,
            events=_run_thread(app, run, row.user_id, plan),
            app_context=app.app_context,
            redact_values={"key": run.key},
        )
    except JobRefused as exc:
        with _LOCK:
            _RUNS.pop(run.run_id, None)
            _CACHE.pop(cache_key, None)
        raise PublishError(str(exc), exc.status) from exc
    return {"runId": run.run_id, "key": run.key, "cached": False}


def _run_thread(app, run: PublishedRun, owner_id: int, plan) -> Iterator[tuple[str, dict]]:
    """Drive the engine as the owner, saving nothing, and pass each event on
    as a viewer reads it."""
    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.execution.run_engine import run_events
    from utk_curio.backend.app.users.models import User

    cancelled = threading.Event()
    _CANCEL[run.run_id] = cancelled
    timer = threading.Timer(MAX_RUN_SECONDS, cancelled.set)
    timer.daemon = True
    timer.start()

    def execute(step, code, input_ref):
        owner = db.session.get(User, owner_id)
        node_run = node_exec.NodeRun(
            code=code,
            node_type=step.node_type,
            node_id=step.node_id,
            input=input_ref,
            dataflow_id=run.project_id,
            node_name=step.label,
            save_output_dataset=False,
            input_slots=tuple(plan.spec.input_slots(step.node_id)) or None,
            published=True,
        )
        run_node = (
            node_exec.execute_js_node if step.engine == "javascript"
            else node_exec.execute_python_node
        )
        reply, _status = run_node(owner, run.key, node_run)
        return reply

    def wrap(fn):
        def in_context():
            with app.app_context():
                return fn()
        return in_context

    run.status = "running"
    try:
        for kind, payload in run_events(plan, execute, cancelled=cancelled, wrap=wrap):
            if kind == "step_started" and payload.get("nodeId") in run.steps:
                run.steps[payload["nodeId"]]["status"] = "running"
            elif kind == "step_finished":
                if payload.get("nodeId") in run.steps:
                    run.steps[payload["nodeId"]]["status"] = payload.get("status")
                found: set = set()
                _collect_artifacts(payload.get("output"), found)
                _collect_artifacts((payload.get("reply") or {}).get("output"), found)
                with _LOCK:
                    run.artifacts |= found
            elif kind == "run_finished":
                run.status = payload.get("status") or "failed"
            yield kind, _viewer_event(kind, payload)
    except Exception:
        run.status = "failed"
        raise
    finally:
        timer.cancel()
        _CANCEL.pop(run.run_id, None)
        if run.status in ("queued", "running"):
            run.status = "cancelled" if cancelled.is_set() else "failed"


_CANCEL: dict[str, threading.Event] = {}


def get_run(run_id: str, key: str) -> PublishedRun:
    """The run *key* opens; a wrong key reads as no run at all."""
    _sweep()
    with _LOCK:
        run = _RUNS.get(run_id)
    if run is None or not key or not secrets.compare_digest(run.key, key):
        raise PublishError("This run has ended and its results have expired. Run again.", 404)
    return run


def run_payload(run: PublishedRun) -> dict:
    return {
        "id": run.run_id,
        "status": run.status,
        "steps": [
            {"nodeId": node_id, "role": step["role"], "status": step["status"], "label": step["label"]}
            for node_id, step in run.steps.items()
        ],
    }


def follow(run: PublishedRun) -> Iterator[tuple[str, dict]]:
    job = PUBLISHED_REGISTRY.get_job(run.run_id)
    if job is None:
        return iter(())
    return PUBLISHED_REGISTRY.subscribe(job)


def cancel(run: PublishedRun) -> None:
    flag = _CANCEL.get(run.run_id)
    if flag is not None:
        flag.set()


def allows_artifact(run: PublishedRun, file_name: str) -> bool:
    with _LOCK:
        return file_name in run.artifacts


def note_artifacts(run: PublishedRun, served: object) -> None:
    """Artifact names inside an artifact the run served (a bundle's parts),
    which the viewer may then read too."""
    found: set = set()
    _collect_artifacts(served, found)
    if found:
        with _LOCK:
            run.artifacts |= found
