"""A dataflow run on the server: Run All, a node's play button, or an
automatic run after a widget or Parameter change (#845), with no browser
needed.

:func:`plan_run` decides what runs, as Run All and ``playNodesUpTo`` decide it
on the canvas: every node, or one or several nodes and the ancestors whose
outputs the canvas could not reuse, in the levels
``run_plan.topological_levels`` gives.
:func:`run_events` walks the plan level by level, as ``usePlayAll`` does:

- every node of a level starts at once; the sandbox's own pool sets how many
  really run together;
- a node fed by one that failed or was skipped is skipped, with a reason that
  names that node, and the other branches go on;
- a node fed by one only the browser can make waits for a tab;
- each executed node gets its code and input the way Play shapes them:
  references resolved (``WorkflowSpec.node_code``), every line indented by
  four spaces, one upstream's output as it is, several as an ``outputs``
  bundle in circle order;
- an Autark node whose document only loads data gets its document with its
  references resolved and no input, as its run in the browser reads none; the
  caller's *execute* compiles it as the browser does, and a failed attempt is
  tried once more, as ``runDataInBackend`` tries it;
- a sandbox that cannot be asked fails that node, as the browser shows it.

Executing a node is the caller's *execute* (``node_exec`` in a real run), and
the engine writes nothing: it yields ``(kind, payload)`` events and the caller
records them.

The headless runner in ``runner.py`` (Solve's validation and an agent's run
through a node) still walks its own way: one node after another, stopping at
the first failure, with seeded code sent straight to the sandbox. Both read
upstreams, input circles, references and roles from the same places.
"""
from __future__ import annotations

import threading
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from typing import Callable, Iterator, Optional

from utk_curio.backend.app.execution.autk_spec_kind import is_autk_data_node
from utk_curio.backend.app.execution.code_references import CodeReferenceError
from utk_curio.backend.app.execution.run_plan import (
    ancestors,
    missing_type_message,
    node_role,
    topological_levels,
)
from utk_curio.backend.app.execution.workflow_spec import WorkflowSpec, parse_workflow_dict

#: How much of a node's stdout and stderr an event carries: the end.
TAIL_CHARS = 4000

CYCLE_REASON = "It is part of a cycle, so a run cannot put it in order."
#: How often an Autark data node is tried before its failure stands, as
#: ``autkLayerMaterialize.ts::runDataInBackend`` tries it.
AUTK_DATA_ATTEMPTS = 2
#: What a node passes downstream: an artifact reference, or an ``outputs``
#: bundle's ``data``.
_INPUT_KEYS = ("path", "filename", "dataset", "dataType", "data")


class PlanError(ValueError):
    """The run cannot be planned, e.g. its target is not in the dataflow."""


@dataclass
class Step:
    node_id: str
    label: str
    node_type: str
    engine: str
    level: int
    role: str
    node: dict = field(repr=False)
    content: str = field(default="", repr=False)
    #: An Autark node whose document only loads data (``autk_spec_kind``): run
    #: as the JavaScript its document compiles to, on no input.
    autk_data: bool = False
    #: *content* is the code to send as it is, not the node's own: a map an
    #: Interaction node is plugged into, run as its edits (``map_edit_code``).
    prepared: bool = False


@dataclass
class Plan:
    spec: WorkflowSpec
    steps: dict
    levels: list
    unplanned: dict
    reuse: dict
    target_node_id: Optional[str] = None
    target_node_ids: list = field(default_factory=list)
    #: The saved node dicts, by id: what an Interaction node's edit log
    #: (``metadata.editFeatures``) is read from.
    saved: dict = field(default_factory=dict, repr=False)


def node_label(node: dict, labels: Optional[dict] = None) -> str:
    """What a run calls a node: the name its canvas header shows
    (``node_names.saved_node_label``, with *labels* the project's template
    labels), which also titles the output the run saves (#775)."""
    from utk_curio.backend.app.execution.node_names import saved_node_label

    return saved_node_label(node, labels) or str(node.get("id") or "")


def play_indent(code: str) -> str:
    """Indent every line by four spaces and end each with a newline, exactly as
    ``PythonInterpreter.ts`` does before posting a node's code."""
    return "".join("    " + line + "\n" for line in code.split("\n"))


def _is_ref(value) -> bool:
    return isinstance(value, dict) and bool(value.get("path") or value.get("data"))


def plan_run(
    spec_dict: dict,
    *,
    target_node_id: Optional[str] = None,
    target_node_ids: Optional[list] = None,
    reuse: Optional[dict] = None,
    templates: Optional[dict] = None,
    labels: Optional[dict] = None,
    packages=None,
) -> Plan:
    """What a run of *spec_dict* executes.

    Without a target, every node. With *target_node_id*, or several nodes in
    *target_node_ids*, those nodes and their ancestors, less the ancestors in
    *reuse* (``{nodeId: output}``): the outputs a canvas still holds for nodes
    it judged need no new run. A target always runs. *labels*
    (``node_names.template_labels``) name each step as its node's header does.
    *packages* (a ``TemplateGrammars``, the account's when the run has one)
    reads what each node's template declares (``run_plan.node_role``).
    """
    spec = parse_workflow_dict(spec_dict, templates=templates, labels=labels)
    saved = {
        n["id"]: n for n in ((spec_dict or {}).get("dataflow") or {}).get("nodes") or []
        if isinstance(n, dict) and n.get("id")
    }
    all_ids = [n.id for n in spec.nodes]
    targets = [target_node_id] if target_node_id else list(target_node_ids or [])
    kept_reuse: dict = {}
    if targets:
        for node_id in targets:
            if node_id not in saved:
                raise PlanError(f"node {node_id!r} is not in the dataflow")
        wanted = set().union(*(ancestors(node_id, spec.edges) for node_id in targets))
        kept_reuse = {
            node_id: {k: v for k, v in ref.items() if k in _INPUT_KEYS}
            for node_id, ref in (reuse or {}).items()
            if node_id in wanted and node_id not in targets and _is_ref(ref)
        }
        run_ids = [n for n in all_ids if n in wanted and n not in kept_reuse]
    else:
        run_ids = list(all_ids)
    run_set = set(run_ids)
    edges = [e for e in spec.edges if e.get("source") in run_set and e.get("target") in run_set]
    levels = topological_levels(run_ids, edges)
    levelled = {node_id for level in levels for node_id in level}
    unplanned = {n: CYCLE_REASON for n in run_ids if n not in levelled}

    by_id = {n.id: n for n in spec.nodes}
    steps: dict = {}
    placed = [(index, node_id) for index, level in enumerate(levels) for node_id in level]
    placed += [(len(levels), node_id) for node_id in unplanned]
    if packages is None:
        from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

        packages = TemplateGrammars.for_account()
    for level, node_id in placed:
        parsed = by_id[node_id]
        node = saved.get(node_id, {})
        role = node_role(node, templates, packages)
        autk_data = role == "run" and is_autk_data_node(node)
        steps[node_id] = Step(
            node_id=node_id,
            label=node_label(node, labels),
            node_type=parsed.raw_type,
            # The compiled document is JavaScript, whatever the template says.
            engine="javascript" if autk_data else parsed.engine,
            level=level,
            role=role,
            node=node,
            content=parsed.content or "",
            autk_data=autk_data,
        )
    return Plan(
        spec=spec, steps=steps, levels=levels, unplanned=unplanned,
        reuse=kept_reuse, target_node_id=target_node_id or None,
        target_node_ids=[] if target_node_id else targets,
        saved=saved,
    )


def node_input(spec: WorkflowSpec, node_id: str, outputs: dict):
    """What *node_id* reads: nothing, one upstream's output, or an ``outputs``
    bundle in circle order. ``None`` until every wired circle has a value, as
    on the canvas, where a node never runs on part of its inputs."""
    upstreams = spec.upstream_nodes(node_id)
    if not upstreams:
        return None
    values = [outputs.get(upstream) for upstream in upstreams]
    if any(value is None for value in values):
        return None
    if len(values) == 1:
        return values[0]
    return {"dataType": "outputs", "data": values}


_EDIT_FEATURES_TYPE = "edit-features"


def map_edit_code(plan: Plan, node_id: str) -> Optional[str]:
    """The Python an Autark map forwards its layers through when an Interaction
    node is plugged into it, or None.

    In the browser the map applies the node's edit log to the layers it draws
    and hands those on (``mapLayerEdits.ts``). A run on the server cannot draw
    the map, so it forwarded the map's inputs as they came, the node's log
    among them, and the nodes below never saw the edits. This names each layer
    after its circle (``input_k``, as the map's document does), leaves the
    Interaction node's circle out, and applies the log with the sandbox's own
    ``curio_edit_features``."""
    node = plan.saved.get(node_id) or {}
    if not str(node.get("type") or "").endswith("autk-grammar"):
        return None
    from utk_curio.backend.app.execution.workflow_spec import input_slot

    edges = plan.spec._data_edges_to(node_id)
    circle, settings = None, None
    for edge in edges:
        source = plan.saved.get(edge.get("source")) or {}
        if str(source.get("type") or "").split("@")[0].endswith(_EDIT_FEATURES_TYPE):
            circle = input_slot(edge)
            settings = (source.get("metadata") or {}).get("editFeatures") or {}
            break
    if circle is None:
        return None
    slots = [input_slot(e) for e in edges if input_slot(e) != circle]
    layers = ", ".join(f"({k}, input_{k})" for k in slots)
    return "\n".join([
        "# The map's layers, with the edits of the Interaction node plugged into it.",
        "import json as _json",
        f"_settings = _json.loads({json.dumps(json.dumps(settings))})",
        "_layers = []",
        f"for _k, _v in [{layers}]:",
        "    if hasattr(_v, 'columns'):",
        "        _meta = dict(getattr(_v, 'metadata', None) or {})",
        "        _v = _v.copy()",
        "        _v.metadata = {**_meta, 'name': f'input_{_k}'}",
        "    _layers.append(_v)",
        "return curio_edit_features(",
        "    _layers, _settings.get('edits') or [], key=_settings.get('key'), layer=_settings.get('layer'),",
        "    keys=_settings.get('keys'), new_layers=_settings.get('newLayers'), crs=_settings.get('crs'),",
        ")",
    ])


def _tail(text) -> str:
    if isinstance(text, list):
        text = "\n".join(str(line) for line in text)
    return str(text or "")[-TAIL_CHARS:]


@dataclass
class _Outcome:
    status: str
    output: dict
    stdout: str = ""
    stderr: str = ""
    reply: dict = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0


def _execute_step(plan: Plan, step: Step, input_ref, execute) -> _Outcome:
    started = time.time()
    # An Autark document's references resolve as a spec's do.
    language = "json" if step.autk_data else "javascript" if step.engine == "javascript" else "python"
    try:
        # Its widgets, its wired circles and the dataflow's shared tags, as the
        # canvas and the headless runner resolve them.
        node = next(n for n in plan.spec.nodes if n.id == step.node_id)
        code = step.content if step.prepared else plan.spec.node_code(node, language, step.content)
    except CodeReferenceError as exc:
        # The node's own failure, reported without asking the sandbox.
        return _Outcome("error", {}, stderr=str(exc), started_at=started, finished_at=time.time())
    # Python is indented as PythonInterpreter.ts posts it; JavaScript goes as
    # written, as JavaScriptInterpreter.ts posts it (an indented `import` is
    # no longer a module's own), and so does an Autark document.
    sent = play_indent(code) if language == "python" else code
    attempts = AUTK_DATA_ATTEMPTS if step.autk_data else 1
    for _attempt in range(attempts):
        outcome = _attempt_step(step, sent, input_ref, execute, started)
        if outcome.status == "ok":
            break
    return outcome


def _attempt_step(step: Step, sent: str, input_ref, execute, started: float) -> _Outcome:
    try:
        reply = execute(step, sent, input_ref) or {}
    except Exception as exc:  # a sandbox that cannot be asked fails this node only
        payload = getattr(exc, "payload", None)
        message = (payload or {}).get("message") if isinstance(payload, dict) else None
        return _Outcome(
            "error", {}, stderr=message or f"{type(exc).__name__}: {exc}",
            started_at=started, finished_at=time.time(),
        )
    output = reply.get("output") if isinstance(reply.get("output"), dict) else {}
    ok = bool(output.get("path"))
    return _Outcome(
        "ok" if ok else "error", output,
        stdout=_tail(reply.get("stdout")), stderr=_tail(reply.get("stderr")),
        reply=reply, started_at=started, finished_at=time.time(),
    )


def _blocked(plan: Plan, node_id: str, status: dict) -> Optional[tuple[str, str]]:
    """Why *node_id* does not run: ``("skipped", reason)`` when a node feeding
    it failed or was skipped, ``("waiting", reason)`` when one only the
    browser makes, else ``None``."""
    waiting_on = None
    for upstream in plan.spec.upstream_nodes(node_id):
        if upstream in plan.reuse:
            continue
        state = status.get(upstream)
        name = plan.steps[upstream].label if upstream in plan.steps else upstream
        if state in ("error", "skipped", "cancelled", "interrupted"):
            return "skipped", (
                f'No data yet: The node feeding this one, "{name}", failed. '
                "Open it to see the error."
            )
        if state in ("browser", "waiting") and waiting_on is None:
            waiting_on = name
    if waiting_on is not None:
        return "waiting", (
            f'Waits for the canvas: "{waiting_on}" makes its data in the browser, '
            "so this node runs when the dataflow is open."
        )
    return None


def _finished(step: Step, status: str, **fields) -> tuple[str, dict]:
    payload = {"nodeId": step.node_id, "status": status}
    payload.update({k: v for k, v in fields.items() if v is not None})
    return "step_finished", payload


def run_events(
    plan: Plan,
    execute: Callable,
    *,
    cancelled: Optional[threading.Event] = None,
    wrap: Callable = lambda fn: fn,
) -> Iterator[tuple[str, dict]]:
    """Walk *plan* and yield its events.

    *execute(step, code, input_ref)* runs one node and returns its reply
    (``stdout``, ``stderr``, ``output``, ...); *wrap* wraps the work handed to
    the level's threads (an app context in a real run). Once *cancelled* is
    set, nothing new starts, and a node that finishes afterwards is cancelled
    and its output dropped.
    """
    cancelled = cancelled or threading.Event()
    outputs: dict = {node_id: dict(ref) for node_id, ref in plan.reuse.items()}
    status: dict = {}
    counts = {"ok": 0, "failed": 0, "skipped": 0, "waiting": 0}

    def settle(step: Step, state: str, **fields):
        status[step.node_id] = state
        if state == "ok":
            counts["ok"] += 1
        elif state == "error":
            counts["failed"] += 1
        elif state == "skipped":
            counts["skipped"] += 1
        elif state == "waiting":
            counts["waiting"] += 1
        return _finished(step, state, **fields)

    yield "run_started", {"nodeIds": list(plan.steps)}
    for node_id, reason in plan.unplanned.items():
        yield settle(plan.steps[node_id], "skipped", skipReason=reason)

    for level in plan.levels:
        ready = []
        for node_id in level:
            step = plan.steps[node_id]
            if cancelled.is_set():
                yield settle(step, "cancelled")
                continue
            blocked = _blocked(plan, node_id, status)
            if blocked is not None:
                yield settle(step, blocked[0], skipReason=blocked[1])
                continue
            # A document that only loads data reads no input.
            input_ref = None if step.autk_data else node_input(plan.spec, node_id, outputs)
            edit_code = map_edit_code(plan, node_id) if step.role == "forward" and input_ref is not None else None
            if edit_code:
                # A map with an Interaction node plugged in hands on its layers
                # with the node's edits, as it does in the browser.
                ready.append((replace(step, engine="python", content=edit_code, prepared=True), input_ref))
            elif step.role == "forward":
                if input_ref is not None:
                    outputs[node_id] = input_ref
                yield settle(step, "forwarded")
            elif step.role == "browser":
                yield settle(step, "browser")
            elif step.role == "missing":
                # No installed package provides its type, so nothing can run
                # it: it fails, naming the type, and what it feeds is skipped.
                yield settle(step, "error", stderrTail=missing_type_message(step.node_type))
            else:
                ready.append((step, input_ref))
        if not ready:
            continue
        with ThreadPoolExecutor(max_workers=len(ready)) as pool:
            futures = {}
            for step, input_ref in ready:
                if cancelled.is_set():
                    yield settle(step, "cancelled")
                    continue
                yield "step_started", {"nodeId": step.node_id, "startedAt": time.time()}
                work = wrap(lambda s=step, i=input_ref: _execute_step(plan, s, i, execute))
                futures[pool.submit(work)] = step
            for future in as_completed(futures):
                step = futures[future]
                outcome = future.result()
                timing = {
                    "startedAt": outcome.started_at,
                    "finishedAt": outcome.finished_at,
                    "durationMs": int((outcome.finished_at - outcome.started_at) * 1000),
                }
                if cancelled.is_set():
                    yield settle(step, "cancelled", **timing)
                    continue
                if outcome.status == "ok":
                    outputs[step.node_id] = {
                        k: v for k, v in outcome.output.items() if k in _INPUT_KEYS
                    }
                    if step.prepared:
                        # The nodes below read the edited layers; the map itself
                        # is still the browser's to draw, as a forwarded map is.
                        yield settle(step, "forwarded", **timing)
                        continue
                # The reply Play would have had, its stdout and stderr cut to
                # the same tails: the event log is kept in memory.
                reply = (
                    {**outcome.reply, "stdout": outcome.stdout, "stderr": outcome.stderr}
                    if outcome.reply else None
                )
                yield settle(
                    step, outcome.status,
                    output=outcome.output or None,
                    stdoutTail=outcome.stdout,
                    stderrTail=outcome.stderr,
                    reply=reply,
                    **timing,
                )

    if cancelled.is_set():
        final = "cancelled"
    elif counts["failed"]:
        final = "failed"
    elif counts["waiting"]:
        final = "needs_canvas"
    else:
        final = "succeeded"
    yield "run_finished", {"status": final, **counts}
