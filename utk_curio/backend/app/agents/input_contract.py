"""The shape of ``arg`` for one node — stated, and enforced before the sandbox.

Memo dev/128, from the owner's sentence: *"The merge node always outputs a list
called `arg`, where each item in this list corresponds to the linked nodes in
the order of their connections to the input handles of the merge node. Your
attempts always used `arg` alone; when I changed it to `arg[0]`, it worked
correctly."*

The runtime knows this per node. ``runner.run_through_node`` decides it in one
place: a node with no code of its own (a merge, a pool, a passive view) passes
ONE upstream's value straight through, and assembles MORE than one into a list
tagged ``dataType: "outputs"``; ``workflow_spec.upstream_nodes`` already orders
those sources by ``in_0``, ``in_1``, … — which is the owner's sentence exactly.
So the shape of ``arg`` is a fact available before a line is generated, and
this module is the ONE place that reads it.

Two halves, both deterministic:

- ``arg_shape`` — ``list`` (with its slots, in handle order), ``single`` or
  ``none``. A merge with ONE connected input is ``single``, because that is
  what the runner does; the naive "upstream is a merge → index it" rule would
  produce the mirror bug.
- ``check`` — with a list-shaped ``arg``, an attribute access on it (``arg.crs``,
  or ``gdf = arg`` followed by ``gdf.to_crs(...)``, the owner's exact code) is
  provably wrong: a list has no such attribute. Refused BEFORE the sandbox
  runs, in the ``DEC-072`` pattern, and the refusal is the next round's error.

Legitimate uses of a list are never refused: ``arg[0]``, ``arg[0].crs``,
iteration, ``len(arg)``, ``pd.concat(arg)``, returning it.
"""

from __future__ import annotations

import ast
import logging

log = logging.getLogger(__name__)

KIND_LIST = "list"
KIND_SINGLE = "single"
KIND_NONE = "none"

#: How far to look through nodes that hold no code of their own.
_WALK_MAX_DEPTH = 4
#: Slots described in a refusal / an input (a merge takes at most five).
MAX_SLOTS = 8
#: Bounds for the text that rides a prompt.
_GOAL_CHARS = 120
_COLUMNS_PER_SLOT = 12


def _graph(spec: dict | None):
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    try:
        return parse_workflow_dict(spec or {})
    except Exception:
        return None


def arg_shape(spec: dict | None, node_id: str) -> dict:
    """What ``arg`` will be for *node_id*, read the way the runner reads it.

    ``{"kind": "list", "length": N, "slots": [{argIndex, upstreamNodeId, goal,
    upstreamNodeType}], "via": "<pass-through node id>"}``, ``{"kind":
    "single", upstreamNodeId, goal, upstreamNodeType}`` or ``{"kind": "none"}``.
    """
    graph = _graph(spec)
    if graph is None:
        return {"kind": KIND_NONE}
    nodes = {n.id: n for n in graph.nodes}
    # The parsed NodeSpec carries type and category, not the node's goal — the
    # human label lives in the raw spec, which is where the slot table reads it.
    goals = {
        n.get("id"): str(n.get("goal") or "")[:_GOAL_CHARS]
        for n in ((spec or {}).get("dataflow") or {}).get("nodes") or []
        if isinstance(n, dict)
    }

    def _describe(nid: str, arg_index: int | None = None) -> dict:
        node = nodes.get(nid)
        row = {
            # dev/128: NOT "nodeId"/"nodeType" — the child's own inputs already
            # carry both keys for the node being generated, and one key with two
            # meanings misleads a reader (model or test) about whose it is.
            "upstreamNodeId": nid,
            "goal": goals.get(nid, ""),
            "upstreamNodeType": str(getattr(node, "raw_type", "") or "") if node else "",
        }
        if arg_index is not None:
            row["argIndex"] = arg_index
        return row

    def _resolve(target: str, depth: int) -> dict:
        try:
            ups = graph.upstream_nodes(target)
        except Exception:
            return {"kind": KIND_NONE}
        if not ups:
            return {"kind": KIND_NONE}
        if len(ups) > 1:
            # Only a merge accepts several inputs; the runner assembles them.
            return {
                "kind": KIND_LIST,
                "length": len(ups),
                "via": target,
                "slots": [_describe(u, i) for i, u in enumerate(ups[:MAX_SLOTS])],
            }
        upstream = ups[0]
        node = nodes.get(upstream)
        if node is not None and getattr(node, "category", "code") != "code" and depth < _WALK_MAX_DEPTH:
            # A pass-through: what IT receives is what this node receives.
            return _resolve(upstream, depth + 1)
        return {"kind": KIND_SINGLE, **_describe(upstream)}

    return _resolve(node_id, 0)


def with_schemas(shape: dict, rows: list | None) -> dict:
    """Enrich a shape's slots with the column summaries dev/127 already
    fetched (matched by ``nodeId``) — data, never invention: a slot whose
    upstream has not run keeps its goal and type alone."""
    if not isinstance(shape, dict) or not rows:
        return shape
    by_node = {
        str(r.get("nodeId")): r.get("schema")
        for r in rows
        if isinstance(r, dict) and r.get("schema")
    }  # dev/127's rows are keyed by nodeId; the slots name it upstreamNodeId
    if not by_node:
        return shape
    if shape.get("kind") == KIND_LIST:
        slots = []
        for slot in shape.get("slots") or []:
            schema = by_node.get(str(slot.get("upstreamNodeId")))
            slots.append({**slot, "schema": _trim_schema(schema)} if schema else slot)
        return {**shape, "slots": slots}
    if shape.get("kind") == KIND_SINGLE:
        schema = by_node.get(str(shape.get("upstreamNodeId")))
        return {**shape, "schema": _trim_schema(schema)} if schema else shape
    return shape


def _trim_schema(schema: object) -> object:
    """A slot carries the columns and the shape, not the sample rows: the
    sample already rides ``upstreamOutputs`` and one copy is enough."""
    if not isinstance(schema, dict):
        return schema
    trimmed = {k: v for k, v in schema.items() if k != "sampleRows"}
    columns = trimmed.get("columns")
    if isinstance(columns, list) and len(columns) > _COLUMNS_PER_SLOT:
        trimmed["columns"] = columns[:_COLUMNS_PER_SLOT]
        trimmed["columnsElided"] = len(columns) - _COLUMNS_PER_SLOT
    return trimmed


def describe(shape: dict | None) -> str:
    """One line for a prompt, a card or a log."""
    if not isinstance(shape, dict):
        return ""
    if shape.get("kind") == KIND_LIST:
        parts = []
        for slot in shape.get("slots") or []:
            label = slot.get("goal") or slot.get("upstreamNodeId") or "?"
            schema = slot.get("schema") if isinstance(slot.get("schema"), dict) else None
            columns = (
                ", ".join(str(c.get("name")) for c in (schema.get("columns") or [])[:6])
                if schema else ""
            )
            parts.append(
                f"arg[{slot.get('argIndex')}] = {label}" + (f" ({columns})" if columns else "")
            )
        return f"arg is a list of {shape.get('length')} inputs — " + "; ".join(parts)
    if shape.get("kind") == KIND_SINGLE:
        label = shape.get("goal") or shape.get("upstreamNodeId") or "the upstream node"
        return f"arg IS the value {label} returned"
    return "this node has no input"


# ── the check ────────────────────────────────────────────────────────────────


def _names_bound_to_arg(tree: ast.AST) -> set[str]:
    """Names assigned DIRECTLY from ``arg`` — ``gdf = arg`` (the owner's code).

    A name bound to ``arg[0]`` is not one of these: it holds a slot, which is
    the correct form.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if isinstance(node.value, ast.Name) and node.value.id == "arg":
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
        elif isinstance(node.value, ast.Name) and node.value.id in bound:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
    return bound


def check(code: object, shape: dict | None) -> dict | None:
    """The ONE rule: with a list-shaped ``arg``, an attribute access on it is
    wrong. Returns ``{"attribute", "name", "line"}`` or None.

    Only ``kind: list`` is judged. A syntax error is not this gate's business
    (the sandbox reports it), and a candidate that never mentions ``arg``
    cannot violate a contract about it.
    """
    if not isinstance(shape, dict) or shape.get("kind") != KIND_LIST:
        return None
    if not isinstance(code, str) or "arg" not in code:
        return None
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    bound = _names_bound_to_arg(tree) | {"arg"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        value = node.value
        # `arg[0].crs` is an attribute of a SUBSCRIPT — correct, never refused.
        if isinstance(value, ast.Name) and value.id in bound:
            return {
                "attribute": node.attr,
                "name": value.id,
                "line": getattr(node, "lineno", 0),
            }
    return None


def refusal_text(shape: dict, violation: dict) -> str:
    """What the model is told, and what a human reads in the trail."""
    name = violation.get("name") or "arg"
    attribute = violation.get("attribute") or "?"
    line = violation.get("line") or 0
    used = f"{name}.{attribute}" + (f" (line {line})" if line else "")
    slots = []
    for slot in (shape.get("slots") or [])[:MAX_SLOTS]:
        label = slot.get("goal") or slot.get("upstreamNodeId") or "?"
        schema = slot.get("schema") if isinstance(slot.get("schema"), dict) else None
        detail = ""
        if schema:
            columns = ", ".join(
                str(c.get("name")) for c in (schema.get("columns") or [])[:8]
            )
            kind = schema.get("kind") or ""
            detail = f" — {kind}" + (f": {columns}" if columns else "")
        slots.append(f"arg[{slot.get('argIndex')}] = {label}{detail}")
    body = "; ".join(slots)
    via = shape.get("via")
    return (
        f"input contract refused — this node is fed through a merge"
        + (f" ({via})" if via else "")
        + f", so `arg` is a LIST of {shape.get('length')} inputs in the merge's "
        "input-handle order: " + body + ". "
        f"Your code used `{used}`: a list has no attribute {attribute!r}. "
        "Index the slot you need (`arg[0]`, `arg[1]`, …) — `arg` alone is the list itself."
    )
