"""The context a browser sends beside each chat message of an attached agent (memo dev/44), for a run of ``agent_eval.py skills``.

A chat's every send composes it from the canvas (``composeAgentRunContext``
in the canvas's ``src/services/agents/agentRunContext.ts``), and the run
request carries it as its ``context``: each read the agent's manifest
declares (``inputs.reads``), in that order, as a labeled line, such as
``Target node: {...}`` for the node the agent is attached to, or
``Current Trill: {...}`` for the whole dataflow. A skill evaluation sends the
message to the route a browser sends it to, so it sends this beside it, or
its runs would hold less than a user's run holds.

Python cannot call the canvas's TypeScript, and no server code composes a
chat's context (the server's ``node_context`` composes a delegated run's
neighborhood, another thing), so this module repeats it, label for label.
``test_skill_eval_context.py`` runs the canvas's own cases through it and
checks each label against the TypeScript.

Where an evaluation's context differs from a browser's, and why:

- The dataflow is the one the server holds, not the canvas's live Trill: an
  evaluation's dataflow is open in no tab, so no node of it is unsaved, and
  the two hold the same nodes and edges. Its top-level fields are those the
  canvas composes (its name, its task, no packages).
- No node has run, since an evaluation has no sandbox, so a node's
  ``current_input`` and ``current_output`` are what the canvas says of a node
  that never ran: nothing feeds it, or it waits for input from the nodes
  wired into it, none of which ran either.

Pure, as the rest of ``evaluation/`` is: it takes the dataflow as a value.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from utk_curio.backend.app.execution.run_plan import is_interaction_edge

#: What the canvas says of a node with no output (``nodeRuntimeSummary.ts``).
NEVER_EXECUTED = "never-executed"
#: What the canvas says of a node that received nothing, which no edge feeds.
NO_INPUT = "no upstream input"
#: What the canvas says of a node with no input yet that data edges feed:
#: it waits for input, wired from these nodes, and of each, that it has not
#: run (``WIRED_INPUT`` in ``nodeRuntimeSummary.ts``).
WAITING = "waiting for input"
WIRED_FROM = ": wired from "
FEEDER = "node "
NOT_RUN = ", which has not run"
BETWEEN = "; "
MORE = "and {n} more"
#: Every word above, which the canvas's summary must write too.
WIRED_INPUT = (WAITING, WIRED_FROM, FEEDER, NOT_RUN, BETWEEN, MORE)
#: The most nodes it names before it counts the rest (``LISTED_SLOTS``).
LISTED = 6

#: The label each fragment starts with, as the canvas writes it.
CURRENT_TRILL = "Current Trill: "
NODE_ID = "Node ID: "
SUBTASK = "Subtask: "
TASK = "Task: "
NODE_CONTENT = "Node content: "
NODE_TYPE = "Node type: "
WORKFLOW = "Workflow: "
MISSION = "Mission: "
NODE_INTENT = "Node intent: "
TARGET_NODE = "Target node: "
CONNECTION = "Connection: the output of node "
CONNECTION_INTO = " into the input of node "
#: Every label above, which the canvas's composer must write too.
LABELS = (CURRENT_TRILL, NODE_ID, SUBTASK, TASK, NODE_CONTENT, NODE_TYPE, WORKFLOW, MISSION,
          NODE_INTENT, TARGET_NODE, CONNECTION, CONNECTION_INTO)


def _json(value) -> str:
    """*value* as ``JSON.stringify`` writes it: no spaces, no escaped non-ASCII."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _declared(value) -> str:
    return f" (declared: {value.strip()})" if isinstance(value, str) and value.strip() else ""


def _dataflow(spec: Mapping | None) -> Mapping:
    flow = (spec or {}).get("dataflow") if isinstance(spec, Mapping) else None
    return flow if isinstance(flow, Mapping) else {}


def trill(spec: Mapping | None, name: str, goal: str) -> dict:
    """The Trill the canvas composes of the dataflow *spec* holds
    (``TrillGenerator.generateTrill``, called as the composer calls it):
    its nodes and edges, then *name*, *goal* as its task, its timestamp, no
    packages, and its datasets and scenarios when it has some."""
    flow = _dataflow(spec)
    out = {
        "nodes": [dict(node) for node in flow.get("nodes") or [] if isinstance(node, Mapping)],
        "edges": [dict(edge) for edge in flow.get("edges") or [] if isinstance(edge, Mapping)],
        "name": name,
        "task": goal,
        "timestamp": flow.get("timestamp"),
        "provenance_id": name,
        "packages": [],
    }
    if flow.get("datasets"):
        out["datasets"] = list(flow["datasets"])
    if flow.get("scenarios"):
        out["scenarios"] = list(flow["scenarios"])
    return {"dataflow": out}


def _node(spec: Mapping | None, node_id: str | None) -> Mapping | None:
    if not node_id:
        return None
    return next((node for node in _dataflow(spec).get("nodes") or []
                 if isinstance(node, Mapping) and node.get("id") == node_id), None)


def _feeders(spec: Mapping | None, node_id) -> list[str]:
    """The nodes wired into *node_id* by data edges, once each in the edges'
    order (``feedersOf``): an interaction edge carries a selection, not data."""
    flow = _dataflow(spec)
    nodes = {node.get("id") for node in flow.get("nodes") or []
             if isinstance(node, Mapping) and isinstance(node.get("id"), str)}
    feeders: list[str] = []
    for edge in flow.get("edges") or []:
        if not isinstance(edge, Mapping) or edge.get("target") != node_id or is_interaction_edge(edge):
            continue
        source = edge.get("source")
        if isinstance(source, str) and source and source in nodes and source not in feeders:
            feeders.append(source)
    return feeders


def _input(spec: Mapping | None, node: Mapping) -> str:
    """What the canvas says a node that never ran received (``summarizeNodeInput``):
    nothing, as no edge feeds it, or nothing yet, from the nodes wired into
    it, which never ran either."""
    feeders = _feeders(spec, node.get("id"))
    if not feeders:
        return f"{NO_INPUT}{_declared(node.get('in'))}"
    named = []
    for feeder_id in feeders[:LISTED]:
        kind = (_node(spec, feeder_id) or {}).get("type")
        typed = f" ({kind})" if isinstance(kind, str) and kind else ""
        named.append(f"{FEEDER}{feeder_id}{typed}{NOT_RUN}")
    if len(feeders) > LISTED:
        named.append(MORE.replace("{n}", str(len(feeders) - LISTED)))
    return f"{WAITING}{_declared(node.get('in'))}{WIRED_FROM}{BETWEEN.join(named)}"


def _never_ran(spec: Mapping | None, node: Mapping) -> dict:
    """What the canvas says a node that never ran received and produced."""
    return {"current_input": _input(spec, node),
            "current_output": f"{NEVER_EXECUTED}{_declared(node.get('out'))}"}


def _target_id(target: Mapping | None, kind: str) -> str | None:
    if isinstance(target, Mapping) and target.get("kind") == kind:
        found = target.get("targetId")
        return str(found) if found else None
    return None


def fragment(read: str, target: Mapping | None, spec: Mapping | None, name: str, goal: str) -> str | None:
    """The line *read* adds to the context of an agent attached to *target*,
    or None when it adds none (``readFragment``)."""
    node_id = _target_id(target, "node")
    node = _node(spec, node_id)
    if read in ("dataflowContext", "graphContext"):
        return CURRENT_TRILL + _json(trill(spec, name, goal))
    if read == "nodeId":
        return NODE_ID + node_id if node_id else None
    if read == "subtask":
        return SUBTASK + node["goal"] if node and node.get("goal") else None
    if read == "workflowGoal":
        return TASK + goal if goal else None
    if read == "connectionSide":
        edge_id = _target_id(target, "connection")
        edge = next((e for e in _dataflow(spec).get("edges") or []
                     if isinstance(e, Mapping) and edge_id and e.get("id") == edge_id), None)
        if not edge or not edge.get("source") or not edge.get("target"):
            return None
        return f"{CONNECTION}{edge['source']}{CONNECTION_INTO}{edge['target']}"
    if read == "nodeContext":
        if node is None:
            return None
        return _json({"id": node.get("id"), "type": node.get("type") or "", "content": node.get("content") or "",
                      **_never_ran(spec, node)})
    if read in ("codeContext", "nodeContent"):
        return NODE_CONTENT + node["content"] if node and node.get("content") else None
    if read == "nodeType":
        return NODE_TYPE + node["type"] if node and node.get("type") else None
    if read == "mission":
        parts = [WORKFLOW + name if name else None, MISSION + goal if goal else None]
        lines = [part for part in parts if part]
        return "\n".join(lines) if lines else None
    if read == "nodeIntent":
        return NODE_INTENT + node["goal"] if node and node.get("goal") else None
    if read == "targetContext":
        if node_id:
            if node is None:
                return None
            return TARGET_NODE + _json({"id": node.get("id"), "type": node.get("type") or "",
                                        "goal": node.get("goal") or "", "content": node.get("content") or "",
                                        **_never_ran(spec, node)})
        return CURRENT_TRILL + _json(trill(spec, name, goal))
    # installedTemplates (retired: the server lists the templates), and the
    # reads with no chat-time source: connectionSide off a connection,
    # keywords, currentTask, userMessage, externalSelection, catalog.
    return None


def compose(reads: Iterable[str], target: Mapping | None, spec: Mapping | None, *, name: str,
            goal: str) -> str | None:
    """The context a browser sends beside a message to an agent that
    declares *reads*, attached to *target* of the dataflow *spec* holds,
    whose canvas is named *name* with the goal *goal*; None when no read
    composes anything (``composeAgentRunContext``). On the canvas
    ``targetContext`` already is the whole dataflow, so ``dataflowContext``
    adds nothing there."""
    reads = [str(read) for read in reads or ()]
    whole = "targetContext" in reads and _target_id(target, "node") is None
    lines = [fragment(read, target, spec, name, goal) for read in reads
             if not (read == "dataflowContext" and whole)]
    found = [line for line in lines if line is not None]
    return "\n".join(found) if found else None
