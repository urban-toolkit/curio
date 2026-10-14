"""What kind of step an Autark document describes, decided as the canvas
decides it.

The twin of ``classifyAutkSpec`` and ``classifyAutkSpecString`` in
``utils/autkSpecKind.ts``; ``utils/autkSpecKind.cases.json`` beside it holds
the cases both run. ``render`` draws a map or a plot, ``compute`` runs WGSL
over layers, ``data`` only loads sources, and anything else is ``unknown``.
"""
from __future__ import annotations

import json

#: The step each top-level family describes (``FAMILY_KIND``).
FAMILY_KIND = {"map": "render", "plot": "render", "compute": "compute", "data": "data"}

#: Drawing wins over computing, and computing over loading.
KIND_ORDER = ("render", "compute", "data")

AUTK_GRAMMAR = "AUTK_GRAMMAR"


def classify_autk_spec(spec) -> str:
    """``render``, ``compute``, ``data`` or ``unknown`` for a parsed document.
    A map or a plot counts as soon as it is named; a step list only when it
    holds a step."""
    if not isinstance(spec, dict):
        return "unknown"

    def names(family: str) -> bool:
        if FAMILY_KIND[family] == "render":
            return spec.get(family) is not None
        value = spec.get(family)
        return isinstance(value, list) and len(value) > 0

    for kind in KIND_ORDER:
        if any(FAMILY_KIND[family] == kind and names(family) for family in FAMILY_KIND):
            return kind
    return "unknown"


def _not_json(constant: str):
    raise ValueError(f"{constant} is not JSON")


def classify_autk_spec_string(spec_text) -> str:
    """:func:`classify_autk_spec` for a document as text, read as
    ``JSON.parse`` reads it."""
    if not isinstance(spec_text, str) or not spec_text.strip():
        return "unknown"
    try:
        return classify_autk_spec(json.loads(spec_text, parse_constant=_not_json))
    except ValueError:
        return "unknown"


def is_autk_data_node(node: dict) -> bool:
    """An Autark node of a saved dataflow whose document only loads data."""
    from utk_curio.backend.app.execution.workflow_spec import normalize_type

    node_type = (node or {}).get("type")
    return (
        isinstance(node_type, str)
        and normalize_type(node_type) == AUTK_GRAMMAR
        and classify_autk_spec_string(node.get("content")) == "data"
    )
