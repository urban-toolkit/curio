"""The shape of a node's inputs, stated and enforced before the sandbox.

Memo dev/128, from the owner's dataflow: two loaders fed a merge, and the code
generated for the node after it read the merge's list of inputs as one frame,
round after round, until the owner indexed it by hand.

A node's code reads each input circle as its own variable, ``input_k`` for
circle k (``sandbox/util/input_names.py``), usually through its chip,
``[!! input_k !!]``. The runtime knows what each holds before a line is
generated: ``runner.run_through_node`` hands a node one value per wired circle,
in circle order (``workflow_spec.upstream_nodes``, ``in``, ``in_1``, ...), and
a node with no code of its own (a pool, a passive view) passes what it received
straight through. This module is the ONE place that reads it.

Two halves, both deterministic:

- ``arg_shape``: one of :data:`KINDS`.
  - ``single``: one circle, one value, read by its chip.
  - ``several``: several circles, one value each, each read by its own chip.
  - ``gathered``: one circle that a pool (or a port that takes many) hands
    several edges' values on, as a list: ``input_k[0]``, ``input_k[1]``, ....
  - ``none``: no input.
- ``check``: with a ``gathered`` input, an attribute access on that circle's
  input (``input_0.crs``, or ``gdf = input_0`` followed by
  ``gdf.to_crs(...)``, the owner's exact mistake) is provably wrong: a list has
  no such attribute. Refused BEFORE the sandbox runs, in the ``DEC-072``
  pattern, and the refusal is the next round's error. The code is judged as it
  runs, with its input chips resolved.

Legitimate uses of a list are never refused: ``input_0[0]``,
``input_0[0].crs``, iteration, ``len(input_0)``, ``pd.concat(input_0)``,
returning it.

``list``, the kind of the one input variable a node once had, is refused
wherever a shape is read (:data:`LIST_REFUSED`).
"""

from __future__ import annotations

import ast
import logging
import re

log = logging.getLogger(__name__)

KIND_SINGLE = "single"
KIND_SEVERAL = "several"
KIND_GATHERED = "gathered"
KIND_NONE = "none"

#: Every kind a node's inputs can be.
KINDS = (KIND_SINGLE, KIND_SEVERAL, KIND_GATHERED, KIND_NONE)

#: Why a shape of kind ``list`` is refused.
LIST_REFUSED = (
    'The input contract kind "list" is gone: a node reads "several" circles, one '
    'value each, or one circle that "gathered" several edges\' values as a list.'
)

#: How far to look through nodes that hold no code of their own.
_WALK_MAX_DEPTH = 4
#: Slots described in a refusal / an input.
MAX_SLOTS = 8
#: Bounds for the text that rides a prompt.
_GOAL_CHARS = 120
_COLUMNS_PER_SLOT = 12


def _kind(shape: dict) -> str | None:
    """The shape's kind; ``list`` is refused."""
    kind = shape.get("kind")
    if kind == "list":
        raise ValueError(LIST_REFUSED)
    return kind


def _graph(spec: dict | None):
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    try:
        return parse_workflow_dict(spec or {})
    except Exception:
        return None


def arg_shape(spec: dict | None, node_id: str) -> dict:
    """What *node_id*'s inputs will be, read the way the runner reads them.

    ``{"kind": "several", "length": N, "circles": [...], "slots": [{circle,
    chip, upstreamNodeId, goal, upstreamNodeType}]}``: one value per circle,
    each read by its own chip, so a node wired on ``in`` and ``in_3`` reads its
    second input as ``[!! input_3 !!]``, which runs as ``input_3``.
    ``{"kind": "gathered", "length": N, "circles": [k], "slots": [{argIndex,
    chip, ...}], "via": "<node id>"}``: one circle that holds several edges'
    values as a list, ``input_k[argIndex]`` each.
    ``{"kind": "single", upstreamNodeId, goal, upstreamNodeType, chip}`` or
    ``{"kind": "none"}``.
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

    try:
        own_circles = graph.input_slots(node_id)
    except Exception:
        own_circles = []
    # The chip the node's code reads its one input by, when it has one.
    own_circle = own_circles[0] if own_circles else 0
    own_chip = _chip(own_circle)

    def _gathered(ups: list, via: str, circle: int) -> dict:
        chip = _chip(circle)
        return {
            "kind": KIND_GATHERED,
            "length": len(ups),
            "circles": [circle],
            "via": via,
            "slots": [{**_describe(upstream, i), "chip": f"{chip}[{i}]"} for i, upstream in enumerate(ups[:MAX_SLOTS])],
        }

    def _resolve(target: str, depth: int) -> dict:
        try:
            ups = graph.upstream_nodes(target)
        except Exception:
            return {"kind": KIND_NONE}
        if not ups:
            return {"kind": KIND_NONE}
        if len(ups) > 1:
            if target != node_id:
                # Through a pass-through the node has one circle, which holds
                # the pass-through's inputs as a list.
                return _gathered(ups, target, own_circle)
            circles = graph.input_slots(target)
            if len(set(circles)) == 1:
                # Several edges on one circle: that circle's list.
                return _gathered(ups, target, circles[0])
            # Several circles: each its own variable, read by its own chip.
            slots = []
            for i, upstream in enumerate(ups[:MAX_SLOTS]):
                slots.append({**_describe(upstream), "circle": circles[i], "chip": _chip(circles[i])})
            return {"kind": KIND_SEVERAL, "length": len(ups), "circles": circles, "slots": slots}
        upstream = ups[0]
        node = nodes.get(upstream)
        if node is not None and getattr(node, "category", "code") != "code" and depth < _WALK_MAX_DEPTH:
            # A pass-through: what IT receives is what this node receives.
            return _resolve(upstream, depth + 1)
        return {"kind": KIND_SINGLE, **_describe(upstream), "chip": own_chip}

    return _resolve(node_id, 0)


def with_schemas(shape: dict, rows: list | None) -> dict:
    """Enrich a shape's slots with the column summaries dev/127 already
    fetched (matched by ``nodeId``) — data, never invention: a slot whose
    upstream has not run keeps its goal and type alone."""
    if not isinstance(shape, dict):
        return shape
    kind = _kind(shape)
    if not rows:
        return shape
    by_node = {
        str(r.get("nodeId")): r.get("schema")
        for r in rows
        if isinstance(r, dict) and r.get("schema")
    }  # dev/127's rows are keyed by nodeId; the slots name it upstreamNodeId
    if not by_node:
        return shape
    if kind in (KIND_SEVERAL, KIND_GATHERED):
        slots = []
        for slot in shape.get("slots") or []:
            schema = by_node.get(str(slot.get("upstreamNodeId")))
            slots.append({**slot, "schema": _trim_schema(schema)} if schema else slot)
        return {**shape, "slots": slots}
    if kind == KIND_SINGLE:
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
    kind = _kind(shape)
    if kind in (KIND_SEVERAL, KIND_GATHERED):
        parts = []
        for slot in shape.get("slots") or []:
            label = slot.get("goal") or slot.get("upstreamNodeId") or "?"
            schema = slot.get("schema") if isinstance(slot.get("schema"), dict) else None
            columns = (
                ", ".join(str(c.get("name")) for c in (schema.get("columns") or [])[:6])
                if schema else ""
            )
            parts.append(
                f"{_slot_chip(slot)} = {label}" + (f" ({columns})" if columns else "")
            )
        if kind == KIND_SEVERAL:
            return f"{shape.get('length')} inputs, one per circle: " + "; ".join(parts)
        return f"{_circle_name(shape)} is a list of {shape.get('length')} inputs: " + "; ".join(parts)
    if kind == KIND_SINGLE:
        label = shape.get("goal") or shape.get("upstreamNodeId") or "the upstream node"
        return f"{shape.get('chip') or _chip(0)} IS the value {label} returned"
    return "this node has no input"


def _circle_name(shape: dict) -> str:
    """The variable a gathered input arrives in: ``input_<its circle>``."""
    circles = shape.get("circles") or [0]
    return f"input_{circles[0]}"


def _slot_chip(slot: dict) -> str:
    """The chip a slot of a several or gathered input is read by."""
    return slot.get("chip") or _chip(slot.get("argIndex"))


def _chip(position) -> str:
    """The chip code reads input *position* by."""
    from utk_curio.backend.app.execution.code_references import (
        input_reference_inner,
        reference_text,
    )

    return reference_text(input_reference_inner(position if isinstance(position, int) else None))


# ── the check ────────────────────────────────────────────────────────────────


def _names_bound_to(tree: ast.AST, names: set[str]) -> set[str]:
    """*names*, and the names assigned DIRECTLY from one of them (``gdf =
    input_0``), and, in turn, from those.

    A name bound to ``input_0[0]`` is not one of these: it holds a slot, which
    is the correct form.
    """
    bound: set[str] = set(names)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if isinstance(node.value, ast.Name) and node.value.id in bound:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
    return bound


def check(code: object, shape: dict | None) -> dict | None:
    """The ONE rule: with a gathered input, an attribute access on it is
    wrong. Returns ``{"attribute", "name", "line"}`` or None.

    Only ``kind: gathered`` is judged, on the code as it runs: its input chips
    become ``input_k``. A syntax error is not this gate's business (the
    sandbox reports it), and a candidate that never mentions the list's circle
    cannot violate a contract about it.
    """
    if not isinstance(shape, dict) or _kind(shape) != KIND_GATHERED:
        return None
    if not isinstance(code, str):
        return None
    from utk_curio.backend.app.execution.code_references import REFERENCE_RE, resolve_references

    circles = shape.get("circles") or [0]
    inputs = [{"slot": circle} for circle in circles]
    code, _ = resolve_references(code, (), "python", inputs)
    # #662: what is left is a widget or a shared tag, a value when the node
    # runs; standing in as one, it keeps the code parseable for this gate.
    code = REFERENCE_RE.sub("None", code)
    names = {f"input_{circle}" for circle in circles}
    if not any(re.search(rf"\b{name}\b", code) for name in names):
        return None
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    bound = _names_bound_to(tree, names)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        value = node.value
        # `input_0[0].crs` is an attribute of a SUBSCRIPT: correct, never refused.
        if isinstance(value, ast.Name) and value.id in bound:
            return {
                "attribute": node.attr,
                "name": value.id,
                "line": getattr(node, "lineno", 0),
            }
    return None


def refusal_text(shape: dict, violation: dict) -> str:
    """What the model is told, and what a human reads in the trail."""
    _kind(shape)
    circle = _circle_name(shape)
    name = violation.get("name") or circle
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
        slots.append(f"{_slot_chip(slot)} = {label}{detail}")
    body = "; ".join(slots)
    chips = [_slot_chip(slot) for slot in (shape.get("slots") or [])[:2]] or [f"{circle}[0]", f"{circle}[1]"]
    return (
        f"input contract refused: {shape.get('length')} inputs reach this node on "
        f"one circle, so `{circle}` is a LIST of them in order: " + body + ". "
        f"Your code used `{used}`: a list has no attribute {attribute!r}. "
        f"Read the input you need by its index ({', '.join(chips)}, ...): "
        f"`{circle}` alone is the list itself."
    )
