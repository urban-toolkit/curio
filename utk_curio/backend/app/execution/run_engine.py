"""A dataflow run on the server: Run All, or a node's play button, with no
browser needed.

:func:`plan_run` decides what runs, as Run All and ``playNodesUpTo`` decide it
on the canvas: every node, or one node and the ancestors whose outputs the
canvas could not reuse, in the levels ``run_plan.topological_levels`` gives.
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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional

from utk_curio.backend.app.execution.code_references import CodeReferenceError
from utk_curio.backend.app.execution.run_plan import ancestors, node_role, topological_levels
from utk_curio.backend.app.execution.workflow_spec import WorkflowSpec, parse_workflow_dict

#: How much of a node's stdout and stderr an event carries: the end.
TAIL_CHARS = 4000

CYCLE_REASON = "It is part of a cycle, so a run cannot put it in order."
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


@dataclass
class Plan:
    spec: WorkflowSpec
    steps: dict
    levels: list
    unplanned: dict
    reuse: dict
    target_node_id: Optional[str] = None


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
    reuse: Optional[dict] = None,
    templates: Optional[dict] = None,
    labels: Optional[dict] = None,
) -> Plan:
    """What a run of *spec_dict* executes.

    Without *target_node_id*, every node. With it, the node and its ancestors,
    less the ancestors in *reuse* (``{nodeId: output}``): the outputs a canvas
    still holds for nodes it judged need no new run. The target always runs.
    *labels* (``node_names.template_labels``) name each step as its node's
    header does.
    """
    spec = parse_workflow_dict(spec_dict, templates=templates)
    saved = {
        n["id"]: n for n in ((spec_dict or {}).get("dataflow") or {}).get("nodes") or []
        if isinstance(n, dict) and n.get("id")
    }
    all_ids = [n.id for n in spec.nodes]
    kept_reuse: dict = {}
    if target_node_id:
        if target_node_id not in saved:
            raise PlanError(f"node {target_node_id!r} is not in the dataflow")
        wanted = ancestors(target_node_id, spec.edges)
        kept_reuse = {
            node_id: {k: v for k, v in ref.items() if k in _INPUT_KEYS}
            for node_id, ref in (reuse or {}).items()
            if node_id in wanted and node_id != target_node_id and _is_ref(ref)
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
    for level, node_id in placed:
        parsed = by_id[node_id]
        node = saved.get(node_id, {})
        steps[node_id] = Step(
            node_id=node_id,
            label=node_label(node, labels),
            node_type=parsed.raw_type,
            engine=parsed.engine,
            level=level,
            role=node_role(node, templates),
            node=node,
            content=parsed.content or "",
        )
    return Plan(
        spec=spec, steps=steps, levels=levels, unplanned=unplanned,
        reuse=kept_reuse, target_node_id=target_node_id or None,
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
    language = "javascript" if step.engine == "javascript" else "python"
    try:
        # Its widgets, its wired circles and the dataflow's shared tags, as the
        # canvas and the headless runner resolve them.
        node = next(n for n in plan.spec.nodes if n.id == step.node_id)
        code = plan.spec.node_code(node, language, step.content)
    except CodeReferenceError as exc:
        # The node's own failure, reported without asking the sandbox.
        return _Outcome("error", {}, stderr=str(exc), started_at=started, finished_at=time.time())
    # Python is indented as PythonInterpreter.ts posts it; JavaScript goes as
    # written, as JavaScriptInterpreter.ts posts it (an indented `import` is
    # no longer a module's own).
    sent = code if language == "javascript" else play_indent(code)
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
            input_ref = node_input(plan.spec, node_id, outputs)
            if step.role == "forward":
                if input_ref is not None:
                    outputs[node_id] = input_ref
                yield settle(step, "forwarded")
            elif step.role == "browser":
                yield settle(step, "browser")
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
