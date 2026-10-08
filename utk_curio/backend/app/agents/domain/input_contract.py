"""The shape of a node's inputs — stated, and enforced before the sandbox.

Memo dev/128, from the owner's sentence: *"The merge node always outputs a list
called `arg`, where each item in this list corresponds to the linked nodes in
the order of their connections to the input handles of the merge node. Your
attempts always used `arg` alone; when I changed it to `arg[0]`, it worked
correctly."*

A node's code reads each input circle as its own variable, ``input_k`` for
circle k (``sandbox/util/input_names.py``), usually through its chip,
``[!! input_k !!]``. The runtime knows what each holds before a line is
generated, and this module is the ONE place that reads it:

- ``arg_shape``: ``several`` (one value per circle, with their slots),
  ``single`` (one circle), ``list`` (one circle that a node with no code of its
  own, a pool or a merge, hands SEVERAL values on, in a list) or ``none``.
- ``check`` — with a ``list``, an attribute access on that circle's input
  (``input_0.crs``, or ``gdf = input_0`` followed by ``gdf.to_crs(...)``, the
  owner's exact mistake) is provably wrong: a list has no such attribute.
  Refused BEFORE the sandbox runs, in the ``DEC-072`` pattern, and the refusal
  is the next round's error. The code is judged as it runs, with its input
  chips resolved.

Legitimate uses of a list are never refused: ``input_0[0]``, ``input_0[0].crs``,
iteration, ``len(input_0)``, ``pd.concat(input_0)``, returning it.
"""

from __future__ import annotations

import ast
import logging
import re

log = logging.getLogger(__name__)

KIND_LIST = "list"
KIND_SEVERAL = "several"
KIND_SINGLE = "single"
KIND_NONE = "none"

#: How far to look through nodes that hold no code of their own.
_WALK_MAX_DEPTH = 4
#: Slots described in a refusal / an input.
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
    """What *node_id*'s inputs will be, read the way the runner reads them.

    ``{"kind": "several", "length": N, "circles": [...], "slots": [{circle,
    chip, upstreamNodeId, goal, upstreamNodeType}]}``: one value per circle,
    each read by its own chip, so a node wired on ``in`` and ``in_3`` reads its
    second input as ``[!! input_3 !!]``, which runs as ``input_3``.
    ``{"kind": "list", "length": N, "circles": [k], "slots": [{argIndex, chip,
    ...}], "via": "<node id>"}``: one circle that a node with no code of its own
    hands several values on, ``input_k[argIndex]`` each.
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
    own_chip = _chip(own_circles[0] if own_circles else 0)

    def _resolve(target: str, depth: int) -> dict:
        try:
            ups = graph.upstream_nodes(target)
        except Exception:
            return {"kind": KIND_NONE}
        if not ups:
            return {"kind": KIND_NONE}
        if len(ups) > 1:
            # Several input circles. On the node itself each is its own
            # variable, read by its circle's chip; through a pass-through the
            # node has one input, a list of them, read by index.
            direct = target == node_id
            circles = graph.input_slots(target) if direct else own_circles
            slots = []
            for i, upstream in enumerate(ups[:MAX_SLOTS]):
                if direct:
                    row = _describe(upstream)
                    row["circle"] = circles[i]
                    row["chip"] = _chip(circles[i])
                else:
                    row = _describe(upstream, i)
                    row["chip"] = f"{own_chip}[{i}]"
                slots.append(row)
            shape = {
                "kind": KIND_SEVERAL if direct else KIND_LIST,
                "length": len(ups),
                "circles": circles,
                "slots": slots,
            }
            if not direct:
                shape["via"] = target
            return shape
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
    if not isinstance(shape, dict) or not rows:
        return shape
    by_node = {
        str(r.get("nodeId")): r.get("schema")
        for r in rows
        if isinstance(r, dict) and r.get("schema")
    }  # dev/127's rows are keyed by nodeId; the slots name it upstreamNodeId
    if not by_node:
        return shape
    if shape.get("kind") in (KIND_LIST, KIND_SEVERAL):
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
    if shape.get("kind") in (KIND_LIST, KIND_SEVERAL):
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
        if shape.get("kind") == KIND_SEVERAL:
            return f"{shape.get('length')} inputs, one per circle: " + "; ".join(parts)
        return (
            f"{_circle_name(shape)} is a list of {shape.get('length')} inputs: " + "; ".join(parts)
        )
    if shape.get("kind") == KIND_SINGLE:
        label = shape.get("goal") or shape.get("upstreamNodeId") or "the upstream node"
        return f"{shape.get('chip') or _chip(0)} IS the value {label} returned"
    return "this node has no input"


def _circle_name(shape: dict) -> str:
    """The variable a list-shaped input arrives in: ``input_<its circle>``."""
    circles = shape.get("circles") or [0]
    return f"input_{circles[0]}"


def _slot_chip(slot: dict) -> str:
    """The chip a slot of a several- or list-shaped input is read by."""
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
    """Names assigned DIRECTLY from one of *names* — ``gdf = input_0`` — and,
    in turn, from those.

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
    """The ONE rule: with a list-shaped input, an attribute access on it is
    wrong. Returns ``{"attribute", "name", "line"}`` or None.

    Only ``kind: list`` is judged, on the code as it runs: its input chips
    become ``input_k``. A syntax error is not this gate's business (the
    sandbox reports it), and a candidate that never mentions the list's
    circle cannot violate a contract about it.
    """
    if not isinstance(shape, dict) or shape.get("kind") != KIND_LIST:
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
        # `input_0[0].crs` is an attribute of a SUBSCRIPT — correct, never refused.
        if isinstance(value, ast.Name) and value.id in bound:
            return {
                "attribute": node.attr,
                "name": value.id,
                "line": getattr(node, "lineno", 0),
            }
    return None


def refusal_text(shape: dict, violation: dict) -> str:
    """What the model is told, and what a human reads in the trail."""
    name = violation.get("name") or _circle_name(shape)
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
    chips = [_slot_chip(slot) for slot in (shape.get("slots") or [])[:2]] or [_chip(0), _chip(1)]
    circle = _circle_name(shape)
    return (
        f"input contract refused: {shape.get('length')} inputs reach this node through "
        f"one circle, so `{circle}` is a LIST of them in order: " + body + ". "
        f"Your code used `{used}`: a list has no attribute {attribute!r}. "
        f"Read the input you need by its index ({', '.join(chips)}, ...): "
        f"`{circle}` alone is the list itself."
    )
