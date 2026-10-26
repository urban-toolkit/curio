"""A dashboard viewer's runs: a visitor changes a pinned control and the
dataflow runs again on the server, which never changes the dataflow or its
owner's Data Catalog.

Anyone who can open the dashboard starts one: the page needs no sign-in. What
a viewer may change is what the pins put on the page (:func:`dashboard_controls`):
the widget of a pinned Parameter node and every widget of a pinned node,
except the kinds ``contracts/dashboardRuns.json`` keeps read-only, a text or a
file, whose free value could name another of the owner's datasets or files.
Each value is checked as the Widgets tab checks it (``check_widget_value``).

What runs: the saved dataflow with the values laid over it in memory, planned
as a server run plans one (``run_engine.plan_run``). Its targets are the nodes
whose outputs the tiles read (``dashboard_source_node_ids``) that the change
reaches, or that have no saved output; the owner's saved outputs stand in for
every node the change does not reach, but one the page needs and cannot read
(:func:`_plan_for_the_page`). Each step runs in the owner's store as
Play runs it there (``node_exec``), with no connection key: a node whose code
reads one stops and says so. Nothing it makes is installed, recorded or
journaled, and the saved spec is never written.

What is kept: each step's output, under a key of what made it, as viewers
made it (``runs/kept.py``: ``step_key``, ``keep``), so a visitor who opens
the page or picks values someone ran before gets the outputs at once, and a
request for a run already going joins it. Kept outputs go after their time or
past their budget, with their artifacts, by the sweep ``kept.py`` describes;
a run sweeps at its end, and at the first start after a restart.

A step only a browser runs (an Autark compute node, a Spatial Join) is the
page's. The run ends asking for it (``needs_canvas``), as a canvas's run on
the server does; the page runs the node and sends what it made
(:func:`keep_tab_result`), and its next start, with the same token, runs the
steps below on that (``browserOutputs``). The server cannot check what a
browser sends, so that output and every one made from it are kept for that
page alone, for ``kept.TAB_OWN_HOURS``.

Limits, constants as a server run's are: a budget per visitor address and
overall (``common/address_limiter.py``) of the runs of values a visitor tries
(opening the page costs nothing, nor does the one start that goes on from the
steps a run left to its page), a few live runs per dashboard, and at most half
the sandbox's isolated pool running a viewer's node at once, so viewers never
take every slot from signed-in users.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import secrets
import threading
import time
import uuid
from typing import Iterator, Optional

from utk_curio.backend.app.common.address_limiter import AddressLimiter
from utk_curio.backend.app.common.job_registry import JobRefused, JobRegistry
from utk_curio.backend.app.execution.sandbox_client import sandbox_request
from utk_curio.backend.app.runs import jobs
from utk_curio.backend.app.runs.kept import (
    SANDBOX_SESSIONS_TIMEOUT,
    call_key,
    canonical,
    datasets_read,
    digest,
    forget_sessions,
    keep,
    kept_output,
    packages_fingerprint,
    prune_quietly,
    readable_output,
    step_call,
)
from utk_curio.backend.app.runs.service import RunError
from utk_curio.backend.extensions import db
from utk_curio.common import shared_constants
from utk_curio.common.exec_pool import exec_parallelism
from utk_curio.common.kept_sessions import new_session_id

log = logging.getLogger(__name__)

#: Runs one dashboard may have going at once.
MAX_LIVE_RUNS_PER_DASHBOARD = 2
#: Runs a minute from one visitor address, and from all of them.
RUNS_PER_ADDRESS_PER_MINUTE = 10
RUNS_PER_MINUTE = 120
#: A finished run stays followable this long.
FINISHED_TTL_SECONDS = 15 * 60
MAX_EVENTS_PER_RUN = 5000
#: The most a page's result of a step only a browser runs may weigh.
MAX_TAB_RESULT_BYTES = 64 * 1024 ** 2
#: The shapes that result comes in, as an Autark node hands on its layers: one
#: layer (``geodataframe``), or several (``outputs``).
TAB_RESULT_KINDS = frozenset({"geodataframe", "outputs"})

NO_KEYS_MESSAGE = (
    "This node reads an API key (curio_secret), and a run a dashboard's viewer "
    "starts uses none. Open the dataflow to run it."
)

_CONTRACT = shared_constants.read("dashboardRuns")
#: The widget kinds a viewer never changes, though their node is pinned.
READ_ONLY_WIDGET_KINDS = frozenset(_CONTRACT["readOnlyWidgetKinds"])
#: The header a tab sends its run's token in.
RUN_TOKEN_HEADER = _CONTRACT["runTokenHeader"]

REGISTRY = JobRegistry(
    name="dashboard-run",
    kinds=("dashboard",),
    # A run's "user" is its dashboard: the cap is per dashboard.
    max_active_per_user=MAX_LIVE_RUNS_PER_DASHBOARD,
    finished_ttl_seconds=FINISHED_TTL_SECONDS,
    max_events=MAX_EVENTS_PER_RUN,
    busy_message="This dashboard already runs these values.",
    cap_message=(
        f"At most {MAX_LIVE_RUNS_PER_DASHBOARD} runs go at once on this dashboard; "
        "try again in a moment."
    ),
)

_LIMITER = AddressLimiter(RUNS_PER_ADDRESS_PER_MINUTE, RUNS_PER_MINUTE)

#: Nodes a viewer's runs may have running at once, across the server.
STEP_SLOTS = max(1, exec_parallelism() // 2)
_SLOTS = threading.BoundedSemaphore(STEP_SLOTS)

_RUNS_LOCK = threading.Lock()
#: ``{run id: {"projectId", "token", "browserSteps"}}`` of the runs this
#: process holds: the steps a run leaves to the page are its browser steps.
_RUNS: dict[str, dict] = {}
_pruned_since_start = threading.Event()


def reset() -> None:
    """Test seam: drop every live run, the address budgets and the boot sweep."""
    REGISTRY.reset()
    _LIMITER.reset()
    with _RUNS_LOCK:
        _RUNS.clear()
    _pruned_since_start.clear()


# ---------------------------------------------------------------------------
# What a viewer may change
# ---------------------------------------------------------------------------

def dashboard_controls(spec: dict) -> dict:
    """``{(node id, widget name): widget}``: the controls the pins put on the
    page that a viewer may change. Every widget of a pinned node, a pinned
    Parameter node's one included, but the read-only kinds."""
    from utk_curio.backend.app.projects.dashboard_payload import is_pinned

    controls: dict = {}
    for node in ((spec or {}).get("dataflow") or {}).get("nodes") or []:
        if not isinstance(node, dict) or not node.get("id") or not is_pinned(node):
            continue
        widgets = (node.get("metadata") or {}).get("widgets") or []
        for widget in widgets if isinstance(widgets, list) else []:
            if not isinstance(widget, dict) or not isinstance(widget.get("name"), str):
                continue
            if widget.get("type") in READ_ONLY_WIDGET_KINDS:
                continue
            controls[(node["id"], widget["name"])] = widget
    return controls


def _check_values(controls: dict, values) -> list[str]:
    """What is wrong with *values* (``{nodeId: {widget: value}}``), one line
    each; empty when every value names a control and suits it."""
    from utk_curio.backend.app.execution.code_references import check_widget_value

    if not isinstance(values, dict):
        return ["'values' must map node ids to their widgets' values."]
    problems = []
    for node_id, by_name in values.items():
        if not isinstance(by_name, dict):
            problems.append(f"The values of {node_id} must name each widget and its value.")
            continue
        for name, value in by_name.items():
            widget = controls.get((node_id, name))
            if widget is None:
                problems.append(f"{name} on {node_id} is not a control this dashboard lets a viewer change.")
                continue
            problem = check_widget_value(widget, value)
            if problem:
                problems.append(f"{widget.get('label') or name}: {problem}")
    return problems


def _with_values(spec: dict, values: dict) -> dict:
    """A copy of *spec* with each control set to its value. The saved spec is
    never touched."""
    overlaid = copy.deepcopy(spec)
    for node in (overlaid.get("dataflow") or {}).get("nodes") or []:
        chosen = values.get(node.get("id")) if isinstance(node, dict) else None
        if not chosen:
            continue
        for widget in (node.get("metadata") or {}).get("widgets") or []:
            if isinstance(widget, dict) and widget.get("name") in chosen:
                widget["value"] = chosen[widget["name"]]
    return overlaid


def _control_values(controls: dict) -> dict:
    """``{"node/widget": value}`` of every control as it stands."""
    from utk_curio.backend.app.execution.code_references import effective_value

    return {f"{node_id}/{name}": effective_value(widget) for (node_id, name), widget in controls.items()}


# ---------------------------------------------------------------------------
# What the change reaches
# ---------------------------------------------------------------------------

def _resolved_code(parsed, node) -> Optional[str]:
    """A node's code as a run sends it, its widgets and shared values written
    in; None for a node with no code."""
    from utk_curio.backend.app.execution.code_references import CodeReferenceError

    if node.category == "grammar":
        language = "json"
    elif node.category == "code":
        language = "javascript" if node.engine == "javascript" else "python"
    else:
        return None
    try:
        return parsed.node_code(node, language, node.content or "")
    except CodeReferenceError:
        return None


def _reached(saved_parsed, overlaid_parsed) -> set:
    """The nodes the values change: those whose code a run sends differs, and
    every node below them."""
    saved_nodes = {node.id: node for node in saved_parsed.nodes}
    changed = set()
    for node in overlaid_parsed.nodes:
        before = saved_nodes.get(node.id)
        if before is None:
            continue
        if _resolved_code(overlaid_parsed, node) != _resolved_code(saved_parsed, before):
            changed.add(node.id)
    below: dict = {}
    for node in overlaid_parsed.nodes:
        for upstream in overlaid_parsed.upstream_nodes(node.id):
            below.setdefault(upstream, set()).add(node.id)
    reached, frontier = set(changed), list(changed)
    while frontier:
        for child in below.get(frontier.pop(), ()):
            if child not in reached:
                reached.add(child)
                frontier.append(child)
    return reached


# ---------------------------------------------------------------------------
# Starting, joining and following a run
# ---------------------------------------------------------------------------

def _saved_state(user_key: str, project_id: str):
    """The saved spec and its saved outputs that can be read
    (``services._saved_outputs``). A step reads the owner's output as its
    input whatever session it runs in, from the file the owner's store holds
    (``node_exec.resolve_saved_inputs``)."""
    from utk_curio.backend.app.projects.services import _saved_outputs

    spec, readable, _missing = _saved_outputs(user_key, project_id)
    return spec, readable


def _public(payload: dict) -> dict:
    """An event as a viewer receives it: no reply and no printed text (the
    dashboard shows no node's print), but the artifact ids its output holds,
    which the page reads through the dashboard's output routes."""
    public = {key: value for key, value in (payload or {}).items() if key not in ("reply", "stdoutTail")}
    ids = ((payload or {}).get("reply") or {}).get("artifactIds")
    if ids:
        public["artifactIds"] = list(ids)
    return public


def start_viewer_run(
    project_id: str, values, *, address: str,
    token: Optional[str] = None, browser_outputs: Optional[dict] = None,
) -> dict:
    """Run *project_id*'s dashboard with *values* (``{nodeId: {widget:
    value}}``) laid over its saved controls, or join the run of the same
    values already going.

    A saved result answers whoever made it: the owner's saved output stands in
    for every node the values do not reach, but one the page needs and cannot
    read (:func:`_plan_for_the_page`), and an output kept from an earlier run
    (:func:`step_key`) for every step someone ran before; only what neither
    holds runs. Opening the page, with the saved values, costs the visitor's
    address nothing: only the values a visitor tries count against its
    budget, and a start that joins a run costs nothing either.

    *browser_outputs* (``{nodeId: path}``) are what the page made of the
    steps a run of these values left to it (:func:`keep_tab_result`), under
    that run's *token*: they stand in for those steps, the steps below them
    run on them, and what those make is kept for that page alone. The run
    is followed with the same token. The first such start after a run costs
    nothing, that run having been counted (:func:`_continues_a_run`).

    Answers ``{"runId", "token", "joined", "nodeIds"}``, the token being what
    the tab follows the run with; ``runId`` is None when nothing needs to run
    (the values are the saved ones and every tile has its saved output)."""
    from flask import current_app

    from utk_curio.backend.app.execution.node_names import template_labels
    from utk_curio.backend.app.execution.run_engine import PlanError
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict
    from utk_curio.backend.app.packages.service import roster_templates
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.dashboard_payload import dashboard_source_node_ids
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.app.projects.services import _owner_user_dir_key
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    if not _pruned_since_start.is_set():
        _pruned_since_start.set()
        prune_quietly()
    project = db.session.get(Project, project_id)
    if project is None:
        raise RunError("Dashboard not found.", 404)
    user_key = _owner_user_dir_key(project)
    spec, saved = _saved_state(user_key, project_id)
    if spec is None:
        raise RunError("Dashboard not found.", 404)

    controls = dashboard_controls(spec)
    problems = _check_values(controls, values if values is not None else {})
    if problems:
        raise RunError(" ".join(problems), 422, problems=problems)
    overlaid = _with_values(spec, values or {})
    tab = _tab_outputs(project_id, browser_outputs, token) if browser_outputs else {}

    templates = roster_templates(user_key, project_id)
    labels = template_labels(user_key, project_id)
    packages = TemplateGrammars.for_account(user_key)
    reached = _reached(
        parse_workflow_dict(spec, templates=templates, labels=labels),
        parse_workflow_dict(overlaid, templates=templates, labels=labels),
    )
    saved_by_node = {ref.node_id: ref for ref in saved}
    targets = sorted(
        node_id for node_id in dashboard_source_node_ids(overlaid, packages)
        if node_id in reached or node_id not in saved_by_node
    )
    if not targets:
        return {"runId": None, "token": None, "joined": False, "nodeIds": []}
    reuse = {
        node_id: {"path": ref.filename, "dataType": ref.data_type or ""}
        for node_id, ref in saved_by_node.items() if node_id not in reached
    }
    reuse.update(tab)
    # The page holds the tiles' saved outputs it opened with, and its own results.
    held = (dashboard_source_node_ids(spec, packages) & set(saved_by_node)) | set(tab)
    try:
        plan = _plan_for_the_page(
            overlaid, targets, reuse, held,
            templates=templates, labels=labels, packages=packages,
        )
    except PlanError as exc:
        raise RunError(str(exc), 422) from exc

    _forget_finished_runs()
    dashboard = f"dashboard:{project_id}"
    run_key = hashlib.sha256(canonical({
        "revision": storage.spec_revision(user_key, project_id),
        "values": _control_values(dashboard_controls(overlaid)),
        "targets": targets,
        "tab": sorted((node_id, output.get("path")) for node_id, output in tab.items()),
    }).encode("utf-8")).hexdigest()
    live = REGISTRY.live_job(dashboard, run_key)
    if live is not None:
        with _RUNS_LOCK:
            known = _RUNS.get(live.job_id)
        if known is not None:
            return {"runId": live.job_id, "token": known["token"], "joined": True, "nodeIds": list(plan.steps)}
    tried = _control_values(dashboard_controls(overlaid)) != _control_values(controls)
    # Going on from the steps a run left to its page: that run was counted.
    paid = bool(tab) and _continues_a_run(token)
    if tried and not paid and not _LIMITER.allow(address or "unknown", time.monotonic()):
        raise RunError("Too many runs from here at once; wait a minute and change the control again.", 429)
    try:
        REGISTRY.check_can_start(dashboard, run_key)
    except JobRefused as exc:
        raise RunError(str(exc), exc.status, runId=exc.job_id) from exc

    run_id = str(uuid.uuid4())
    # The page's results are read with the token they were kept under.
    token = token if tab else secrets.token_urlsafe(32)
    app = current_app._get_current_object()
    events = _run_events(
        app, project_id, project.user_id, plan, user_key,
        private_to=digest(token) if tab else None, tainted=_below(plan, tab),
    )
    browser_steps = [node_id for node_id, step in plan.steps.items() if step.role == "browser"]
    with _RUNS_LOCK:
        _RUNS[run_id] = {"projectId": project_id, "token": token, "browserSteps": browser_steps}
    try:
        REGISTRY.start(
            user_key=dashboard, project_id=project_id, key=run_key,
            kind="dashboard", job_id=run_id, events=events, app_context=app.app_context,
        )
    except JobRefused as exc:
        with _RUNS_LOCK:
            _RUNS.pop(run_id, None)
        raise RunError(str(exc), exc.status, runId=exc.job_id) from exc
    return {"runId": run_id, "token": token, "joined": False, "nodeIds": list(plan.steps)}


def _continues_a_run(token: Optional[str]) -> bool:
    """Whether *token* is that of a run which left steps to its page and was
    not gone on from yet; from now on it has been, so a page that sends its
    results again pays for the start that follows."""
    with _RUNS_LOCK:
        for known in _RUNS.values():
            if known.get("token") == token and known.get("browserSteps") and not known.get("continued"):
                known["continued"] = True
                return True
    return False


def _forget_finished_runs() -> None:
    """Drop the tokens of runs the registry no longer holds."""
    REGISTRY.sweep_finished()
    with _RUNS_LOCK:
        for run_id in [rid for rid in _RUNS if REGISTRY.get_job(rid) is None]:
            _RUNS.pop(run_id, None)


def _run_events(
    app, project_id: str, owner_id: int, plan, user_key: str,
    *, private_to: Optional[str] = None, tainted: frozenset = frozenset(),
) -> Iterator[tuple[str, dict]]:
    """The run's thread: drive the engine with :func:`execute`, keep what
    each step makes, pass each event on as a viewer receives it. A step in
    *tainted* is built on what a page sent: what it makes is kept for that
    page alone (*private_to*)."""
    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.execution.run_engine import run_events
    from utk_curio.backend.app.users.connection_keys import secret_names
    from utk_curio.backend.app.users.models import User

    packages = packages_fingerprint(user_key)

    def execute(step, code, input_ref):
        jobs.hold_point()
        owner = db.session.get(User, owner_id)
        call = step_call(plan, step, code, input_ref)
        if call.engine == "python" and secret_names(call.code):
            return {"stdout": [], "stderr": NO_KEYS_MESSAGE, "output": {"path": "", "dataType": "str"}}
        key = call_key(
            call, packages=packages, node_type=step.node_type,
            datasets=datasets_read(call.code, project_id, owner),
        )
        private = private_to if step.node_id in tainted else None
        kept = kept_output(project_id, key, private)
        if kept is not None:
            output, ids = kept
            return {"stdout": [], "stderr": "", "output": output, "artifactIds": ids}
        session_id = new_session_id()
        node_run = node_exec.NodeRun(
            code=call.code, node_type=step.node_type,
            # No node id: a viewer's run writes nothing to the owner's runtime
            # journal (``record_runtime_outcome``) and installs nothing.
            node_id=None, input=call.input, dataflow_id=project_id, node_name=step.label,
            save_output_dataset=False, input_slots=call.slots,
        )
        run_node = node_exec.execute_js_node if call.engine == "javascript" else node_exec.execute_python_node
        with _SLOTS:
            reply, _status = run_node(owner, session_id, node_run)
        output = reply.get("output") if isinstance(reply.get("output"), dict) else {}
        if output.get("path"):
            return {**reply, "artifactIds": keep(project_id, step.node_id, key, session_id, output, private)}
        forget_sessions([session_id])
        return reply

    def wrap(fn):
        def in_context():
            with app.app_context():
                return fn()
        return in_context

    try:
        for kind, payload in run_events(plan, execute, cancelled=threading.Event(), wrap=wrap):
            yield kind, _public(payload)
    finally:
        prune_quietly()


def _known_run(project_id: str, run_id: str, token: Optional[str]) -> dict:
    with _RUNS_LOCK:
        known = _RUNS.get(run_id)
    if known is None or known["projectId"] != project_id:
        raise RunError("This run is over. Change a control to run again.", 404)
    if not token or not secrets.compare_digest(str(token), known["token"]):
        raise RunError("This run is not yours to follow.", 403)
    return known


def follow(project_id: str, run_id: str, token: Optional[str]) -> Iterator[tuple[str, dict]]:
    """The run's events, replayed and then tailed while it goes."""
    _known_run(project_id, run_id, token)
    job = REGISTRY.get_job(run_id)
    if job is None:
        with _RUNS_LOCK:
            _RUNS.pop(run_id, None)
        raise RunError("This run is over. Change a control to run again.", 404)
    return REGISTRY.subscribe(job)


# ---------------------------------------------------------------------------
# The steps a run leaves to the page
# ---------------------------------------------------------------------------

def _tab_result_problem(value) -> Optional[str]:
    """What is wrong with a page's result of a browser step, or None: it is
    one layer or several, as an Autark node hands its layers on, each the
    layer itself. A layer named by an output's id is refused: the steps below
    read the result in a kept session, which reads what any kept run made,
    and the sandbox reads each output such a result names
    (``worker._expand_outputs_wrapper``)."""
    if not isinstance(value, dict) or value.get("dataType") not in TAB_RESULT_KINDS:
        kinds = " or ".join(sorted(TAB_RESULT_KINDS))
        return f"A page's result of a step must be an object whose dataType is {kinds}."
    if not isinstance(value.get("data"), (dict, list)):
        return "A page's result of a step must carry its data."
    if value.get("dataType") == "outputs" and isinstance(value["data"], list) and not all(
        isinstance(layer, dict) and "path" not in layer for layer in value["data"]
    ):
        return "A page's result of a step must hold its layers, not name outputs."
    return None


def keep_tab_result(project_id: str, run_id: str, node_id: str, token: Optional[str], value) -> dict:
    """Keep *value*, what the page following *run_id* made of *node_id*, one
    of the steps that run left to it, for that page alone: the server cannot
    check what a browser sends. It is written to the sandbox as it came, never
    run. Answers ``{"output", "artifactIds"}``; the page's next start names
    the output as that step's (``browserOutputs``)."""
    known = _known_run(project_id, run_id, token)
    if node_id not in known.get("browserSteps", ()):
        raise RunError("That step is not one this run left to the page.", 409)
    problem = _tab_result_problem(value)
    if problem:
        raise RunError(problem, 422)
    session_id = new_session_id()
    response = sandbox_request(
        "post", "/artifact-sessions/store",
        label="/artifact-sessions/store", timeout=SANDBOX_SESSIONS_TIMEOUT,
        data=json.dumps({"sessionId": session_id, "value": value, "nodeType": "dashboard-tab"}),
        headers={"Content-Type": "application/json"},
    )
    try:
        output = (response.json() or {}).get("output") or {}
    except ValueError:
        output = {}
    if not output.get("path"):
        forget_sessions([session_id])
        raise RunError("The page's result could not be kept; change the control to run again.", 502)
    private_to = digest(str(token))
    key = hashlib.sha256(canonical({
        "page": private_to, "run": run_id, "node": node_id, "path": output["path"],
    }).encode("utf-8")).hexdigest()
    return {"output": output, "artifactIds": keep(project_id, node_id, key, session_id, output, private_to)}


def _tab_outputs(project_id: str, browser_outputs, token: Optional[str]) -> dict:
    """``{nodeId: output}`` of the page's results a start names, each one the
    page holding *token* sent for that node (:func:`keep_tab_result`)."""
    if not isinstance(browser_outputs, dict) or not all(
        isinstance(node_id, str) and isinstance(path, str) for node_id, path in browser_outputs.items()
    ):
        raise RunError("'browserOutputs' must map node ids to the outputs the page sent.", 422)
    if not token:
        raise RunError("A start that names the page's results needs the token they were kept under.", 403)
    outputs = {}
    for node_id, path in browser_outputs.items():
        entry = readable_output(project_id, path, token)
        if entry.node_id != node_id or entry.private_to is None:
            raise RunError(f"{path} is not a result this page sent for {node_id}.", 403)
        outputs[node_id] = json.loads(entry.output)
    return outputs


def _below(plan, nodes) -> frozenset:
    """The steps of *plan* that read, directly or not, one of *nodes*."""
    reached = set(nodes)
    below = set()
    for level in plan.levels:
        for node_id in level:
            if any(upstream in reached for upstream in plan.spec.upstream_nodes(node_id)):
                reached.add(node_id)
                below.add(node_id)
    return frozenset(below)


def _plan_for_the_page(spec: dict, targets: list, reuse: dict, held: set, **options):
    """The run's plan (``run_engine.plan_run`` with *options*), where no saved
    output stands in for a node the page needs and cannot read.

    The page plays the steps left to it on what it holds (*held*: the tiles'
    saved outputs it opened with, and its own results) and on what the run
    sends; the dashboard's routes read only what runs kept, never the owner's
    other saved outputs. So a node whose saved output feeds such a step,
    directly or through nodes that forward what reaches them, runs too, and
    its output reaches the page as a step's does (a kept one answers at once).
    """
    from utk_curio.backend.app.execution.run_engine import plan_run

    reuse = dict(reuse)
    while True:
        plan = plan_run(spec, target_node_ids=targets, reuse=reuse, **options)
        unread = _unread_by_the_page(plan, held)
        if not unread:
            return plan
        for node_id in unread:
            del reuse[node_id]


def _unread_by_the_page(plan, held: set) -> set:
    """The nodes of *plan* whose saved outputs stand in for an input of a step
    the page plays, or of a node forwarding to one, that the page does not
    hold (*held*)."""
    walk = [node_id for node_id, step in plan.steps.items() if step.role == "browser"]
    seen, unread = set(), set()
    while walk:
        node_id = walk.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        for upstream in plan.spec.upstream_nodes(node_id):
            if upstream in plan.reuse:
                if upstream not in held:
                    unread.add(upstream)
            elif upstream in plan.steps and plan.steps[upstream].role == "forward":
                walk.append(upstream)
    return unread
