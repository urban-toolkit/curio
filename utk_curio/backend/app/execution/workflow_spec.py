"""Workflow spec model + topology (promoted from the Playwright test tree,
memo dev/67-7).

Single source: the e2e suite imports THIS module through a shim, so the
headless runner and the browser tests read one semantics — Kahn ordering that
skips Interaction edges, merge ``in_N`` input ordering, the legacy/namespaced
type mapping, and the code/grammar/datapool/passive classification.
"""

import json
import os
import re
from dataclasses import dataclass
from collections import deque


def merge_slot_index(edge: dict) -> int | None:
    """Which merge slot an edge feeds: ``in_0`` → 0, or None.

    The HANDLE is the authority, exactly as the canvas reads it
    (``mergeFlowUtils.parseHandleIndex(e.targetHandle)`` → the order Play
    assembles ``arg`` in). The edge id's ``in_N`` suffix is the canvas's own
    legacy encoding and stays as a fallback for specs saved that way.

    dev/128, from a field failure: agent-applied edges carry a UUID id and the
    slot in ``targetHandle`` (dev/67-3 made handles explicit), so reading only
    the id left every plan-created merge unordered — sorted lexicographically
    by UUID. A node then validated against ``arg`` in one order and ran at Play
    in another: dataflow ``00708324`` passed *"solved · pass after 1 round"* and
    failed on Play with ``KeyError: 'tract_id'``, because validation handed it
    ``[population, boundaries]`` and Play handed it ``[boundaries, population]``.
    """
    if not isinstance(edge, dict):
        return None
    for key in ("targetHandle", "target_handle"):
        handle = edge.get(key)
        if isinstance(handle, str):
            m = re.match(r"^in_(\d+)$", handle.strip())
            if m:
                return int(m.group(1))
    # e.g. ``…78504in_0`` (no hyphen before ``in_``) — the canvas's edge ids.
    m = re.search(r"in_(\d+)$", str(edge.get("id") or ""))
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Data model: parse workflow JSON into structured specs
# ---------------------------------------------------------------------------

GRAMMAR_TYPES = {"VIS_VEGA", "AUTK_GRAMMAR"}
# Python-content code nodes — the only ones that can be Python-seeded /
# Python-exec'd by the programmatic runner. JS_COMPUTATION is a CODE node
# but its content is JavaScript, so it must be excluded from this set.
# dev/120: every member must have a namespaced spelling in NAMESPACED_TO_LEGACY
# (test-pinned) — a legacy name no canvas can produce is a phantom, and two
# (CONSTANTS, FLOW_SWITCH) lived here after main had already removed them.
# These tables are the OFFLINE FALLBACK (DEC-076): the template roster decides
# executability whenever it is reachable; do not grow them.
PY_CODE_TYPES = {
    "DATA_LOADING", "DATA_TRANSFORMATION",
    "DATA_EXPORT", "COMPUTATION_ANALYSIS",
}
CODE_TYPES = PY_CODE_TYPES | {"JS_COMPUTATION"}

# Subset of CODE_TYPES whose frontend component passes ``code={true}``
# to ``NodeEditor``, meaning they render a "code" tab with a Monaco editor.
# The remaining CODE_TYPES member (DATA_EXPORT) uses ``code={false}`` and has
# no code tab.
CODE_EDITOR_TYPES = {
    "DATA_LOADING", "DATA_TRANSFORMATION",
    "COMPUTATION_ANALYSIS",
    "JS_COMPUTATION",
}


# Map from package-namespaced node-type ids (the format every workflow JSON
# has used since commit f787905 migrated built-ins onto the curio.builtin@1
# manifest) back to the legacy uppercase identifiers this test module
# classifies and dispatches against. Without this, `classify_node` returns
# `"passive"` for every node and `_execute_all_playable_nodes` silently
# skips the entire workflow, turning the suite into a render-only smoke test.
# Legacy uppercase ids that already appear in JSON pass through unchanged.
NAMESPACED_TO_LEGACY: dict[str, str] = {
    "curio.builtin/data-loading":         "DATA_LOADING",
    "curio.builtin/data-transformation":  "DATA_TRANSFORMATION",
    "curio.builtin/data-export":          "DATA_EXPORT",
    "curio.builtin/computation-analysis": "COMPUTATION_ANALYSIS",
    "curio.builtin/data-summary":         "DATA_SUMMARY",
    "curio.builtin/js-computation":       "JS_COMPUTATION",
    "curio.builtin/vis-vega":             "VIS_VEGA",
    "curio.builtin/vis-simple":           "VIS_SIMPLE",
    "curio.builtin/data-pool":            "DATA_POOL",
    "curio.builtin/merge-flow":           "MERGE_FLOW",
    "curio.builtin/autk-grammar":         "AUTK_GRAMMAR",
}


def normalize_type(node_type: str) -> str:
    """Return the legacy uppercase id for *node_type*, or pass-through.

    dev/119 hotfix: palette-dragged nodes persist the VERSIONED canonical id
    (``curio.builtin/data-loading@1``, the trill contract's own words); the
    lookup used to see the ``@1`` and fall through to "passive", so the runner
    refused a user's real Data Loading code as not executable while the gate
    (which did strip the version) had said it was. Strip first, like
    ``packages/spec_packages.unversioned_node_type``.
    """
    if isinstance(node_type, str) and "@" in node_type:
        node_type = node_type.split("@", 1)[0]
    return NAMESPACED_TO_LEGACY.get(node_type, node_type)


def is_executable_kind(node_type: str, templates: dict | None = None) -> bool:
    """dev/118 (DEC-075) → dev/119 (DEC-076): whether the sandbox can RUN a
    node of this kind. With a roster snapshot the template's own facts decide
    (``executable``); without one the legacy ``code`` category is the offline
    fallback. Accepts namespaced ids with or without an ``@version`` suffix."""
    if not isinstance(node_type, str) or not node_type:
        return False
    category, _engine = _classify_with_roster(node_type, templates)
    return category == "code"


#: dev/134: the content kinds ``content_kind`` answers with — the same four the
#: roster derives (``packages.services.template_content_kind``).
CONTENT_KIND_CODE = "code"
CONTENT_KIND_GRAMMAR = "grammar"
CONTENT_KIND_NOTE = "note"
CONTENT_KIND_NONE = "none"

#: The offline fallback for a grammar kind's grammar id, used only when there is
#: no roster snapshot (the legacy tables' equivalent for ``grammarId``).
_LEGACY_GRAMMAR_IDS = {"VIS_VEGA": "vega-lite", "AUTK_GRAMMAR": "autk-grammar"}


def content_kind(node_type: str, templates: dict | None = None) -> str:
    """What kind of content a node of this type carries (memo dev/134).

    The write gate's routing, beside ``is_executable_kind`` and derived the same
    way: with a roster snapshot the template's own facts decide
    (``contentKind``), and without one the legacy category tables answer —
    ``code`` runs, ``grammar`` is a validated document, and ``datapool`` /
    ``passive`` author nothing at all (they render or forward their input).
    """
    if not isinstance(node_type, str) or not node_type:
        return CONTENT_KIND_NONE
    if templates:
        key = node_type.split("@", 1)[0]
        row = templates.get(key)
        if isinstance(row, dict) and row.get("contentKind"):
            return str(row["contentKind"])
    legacy = normalize_type(node_type)
    category = classify_node(legacy)
    if category == "code":
        return CONTENT_KIND_CODE
    if category == "grammar":
        return CONTENT_KIND_GRAMMAR
    return CONTENT_KIND_NONE


def grammar_id_of(node_type: str, templates: dict | None = None) -> str | None:
    """Which grammar a ``grammar`` node's document is written in, or None."""
    if not isinstance(node_type, str) or not node_type:
        return None
    if templates:
        row = templates.get(node_type.split("@", 1)[0])
        if isinstance(row, dict) and row.get("grammar"):
            return str(row["grammar"])
    return _LEGACY_GRAMMAR_IDS.get(normalize_type(node_type))


def classify_node(node_type: str) -> str:
    """Classify a workflow node type string into a test category.

    Categories:
        "code"     – has a Monaco code editor and a play button
        "grammar"  – has a JSON / grammar editor and a play button
        "datapool" – has ``#data-tabs`` but NO play button
        "passive"  – no standard editor and no play button (e.g. MERGE_FLOW, VIS_SIMPLE)
    """
    if node_type in GRAMMAR_TYPES:
        return "grammar"
    if node_type == "DATA_POOL":
        return "datapool"
    if node_type in CODE_TYPES:
        return "code"
    # MERGE_FLOW, VIS_SIMPLE, COMMENTS, or any unknown type
    return "passive"


@dataclass
class NodeSpec:
    """Expected properties of a single node parsed from the workflow JSON."""
    id: str
    type: str            # legacy uppercase id, e.g. "DATA_LOADING", "VIS_VEGA"
    raw_type: str        # original on-the-wire id, e.g. "curio.builtin/data-loading"
    x: float
    y: float
    content: str         # raw content string (may be empty for DataPool)
    in_type: str         # "DEFAULT", "DATAFRAME", etc.
    out_type: str
    category: str        # "code" | "grammar" | "datapool" | "passive"
    #: dev/119: the template's engine when a roster classified this node —
    #: "python" | "javascript"; the legacy tables' answer otherwise.
    engine: str = "python"

    @property
    def has_play_button(self) -> bool:
        """Only code and grammar nodes expose a play button."""
        return self.category in ("code", "grammar")


@dataclass
class WorkflowSpec:
    """Expected structure of a complete workflow parsed from JSON."""
    filepath: str
    name: str
    nodes: list          # list[NodeSpec]
    edges: list          # list[dict]  –  each: {id, source, target, type?}

    @property
    def nodes_count(self) -> int:
        return len(self.nodes)

    @property
    def edges_count(self) -> int:
        """Count all edges, including Interaction-type edges.

        Workflow JSON files contain two kinds of edges:

        1. **Regular edges** – standard data-flow connections between an
           ``out`` handle and an ``in`` handle (``type`` is ``None`` or
           absent).

        2. **Interaction edges** – ``type == 'Interaction'``.  These link
           ``in/out`` handles and represent a bidirectional interaction
           channel (e.g. brushing / highlighting) between visualisation
           nodes.

        Both kinds are rendered as ``.react-flow__edge`` DOM elements by
        the frontend, so the total count must match what the canvas shows.
        """
        return len(self.edges)

    @property
    def interaction_edges_count(self) -> int:
        """Count Interaction-type edges.

        Interaction edges (``type == 'Interaction'``) use ``in/out``
        handles on both source and target nodes (visible in their edge
        IDs, e.g. ``…in/out-…in/out``).  They represent a bidirectional
        interaction channel – for instance, brushing a bar in a Vega
        chart highlights the corresponding geometry on an Autark map, and
        vice-versa.

        The frontend does **not** render these as ``.react-flow__edge``
        elements; instead they are managed by a dedicated interaction
        layer.  Use this count when you need to verify interaction
        wiring separately from the standard data-flow edge count.
        """
        return sum(1 for e in self.edges if e.get("type") == "Interaction")

    def upstream_nodes(self, node_id: str) -> list[str]:
        """Return source node IDs feeding into *node_id* (data-flow edges only).

        Interaction edges are excluded because they carry selection state,
        not data.

        For ``MERGE_FLOW`` targets, sources are ordered by their input handle
        ``in_0``, ``in_1``, … — the same authority the canvas uses to build
        ``arg`` at Play (``mergeFlowUtils``), with the edge id's legacy
        ``in_N`` suffix as a fallback (dev/128).
        """
        node_map = {n.id: n for n in self.nodes}
        target = node_map.get(node_id)
        edges_to = [
            e for e in self.edges
            if e["target"] == node_id and e.get("type") != "Interaction"
        ]
        if target and target.type == "MERGE_FLOW" and len(edges_to) > 1:

            def sort_key(e: dict) -> tuple:
                idx = merge_slot_index(e)
                return (idx if idx is not None else 10**9, str(e.get("id") or ""))

            edges_to = sorted(edges_to, key=sort_key)
        return [e["source"] for e in edges_to]

    def topo_sorted_nodes(self) -> list:
        """Return nodes in topological (dependency) order using Kahn's algorithm.

        Source / root nodes come first so upstream nodes execute before
        downstream ones.  If cycles exist the remaining nodes are appended
        at the end.
        """
        node_map = {n.id: n for n in self.nodes}
        in_degree = {n.id: 0 for n in self.nodes}
        adj: dict[str, list[str]] = {n.id: [] for n in self.nodes}

        for edge in self.edges:
            # Skip Interaction edges to match upstream_nodes(): they carry
            # selection state, not data, and may form cycles with the
            # data-flow edges (e.g. example 09's VIS_VEGA↔DATA_POOL pair).
            # Including them here makes Kahn's algorithm unable to drain the
            # queue and forces a nodes-list-order fallback that can visit a
            # downstream code node before its data upstream is in outputs.
            if edge.get("type") == "Interaction":
                continue
            src, tgt = edge["source"], edge["target"]
            if src in adj and tgt in in_degree:
                adj[src].append(tgt)
                in_degree[tgt] += 1

        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        ordered: list[NodeSpec] = []

        while queue:
            nid = queue.popleft()
            ordered.append(node_map[nid])
            for neighbour in adj[nid]:
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        # Append any remaining nodes (cycles or disconnected)
        visited = {n.id for n in ordered}
        for n in self.nodes:
            if n.id not in visited:
                ordered.append(n)

        return ordered


def parse_workflow(filepath: str) -> WorkflowSpec:
    """Read a workflow JSON file and return a ``WorkflowSpec``.

    Forces UTF-8 — Windows defaults to cp1252 here, which mangles
    non-ASCII content (e.g. "Niterói" in Regression.json) and breaks
    string-equality checks against the Monaco editor value.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.loads(f.read())

    dataflow = data["dataflow"]

    nodes = [
        NodeSpec(
            # Normalize at parse time so the rest of the test module can
            # keep comparing against canonical legacy ids (e.g.
            # `node.type == "DATA_POOL"`). The raw namespaced string is
            # preserved on `raw_type` for any sandbox-facing callsite that
            # needs the on-the-wire id.
            id=n["id"],
            type=normalize_type(n["type"]),
            raw_type=n["type"],
            x=float(n.get("x", 0)),
            y=float(n.get("y", 0)),
            content=n.get("content", ""),
            in_type=n.get("in", "DEFAULT"),
            out_type=n.get("out", "DEFAULT"),
            category=classify_node(normalize_type(n["type"])),
        )
        for n in dataflow["nodes"]
    ]

    edges = [
        {
            "id": e["id"],
            "source": e["source"],
            "target": e["target"],
            "type": e.get("type"),
            # dev/128: the input handle is what orders a merge's inputs, and
            # dropping it here is what made an agent-applied merge unordered.
            "targetHandle": e.get("targetHandle") or e.get("target_handle"),
            "sourceHandle": e.get("sourceHandle") or e.get("source_handle"),
        }
        for e in dataflow["edges"]
    ]

    return WorkflowSpec(
        filepath=filepath,
        name=data.get("name", os.path.basename(filepath)),
        nodes=nodes,
        edges=edges,
    )



def _classify_with_roster(raw_type: str, templates: dict | None) -> tuple[str, str]:
    """dev/119 (DEC-076): ``(category, engine)`` for a node type. With a
    roster snapshot (``{canonical_id: {"executable", "engine"}}``, unversioned
    keys) the template's own facts decide; without one — or for a type the
    roster does not know — the legacy tables answer, as the offline fallback."""
    legacy = normalize_type(raw_type)
    legacy_category = classify_node(legacy)
    legacy_engine = "javascript" if legacy == "JS_COMPUTATION" else "python"
    if not templates:
        return legacy_category, legacy_engine
    key = raw_type.split("@", 1)[0] if isinstance(raw_type, str) else raw_type
    row = templates.get(key)
    if not isinstance(row, dict):
        return legacy_category, legacy_engine
    engine = row.get("engine") or legacy_engine
    if row.get("executable"):
        return "code", engine
    # Known to the roster and not executable: never "code", whatever the
    # legacy table thought (data-pool and grammar kinds keep their categories).
    return (legacy_category if legacy_category != "code" else "passive"), engine


def parse_workflow_dict(data: dict, *, name: str = "", templates: dict | None = None) -> WorkflowSpec:
    """Build a :class:`WorkflowSpec` from an in-memory project spec dict —
    the app-side entry (`projects_storage.read_spec` output); byte-equivalent
    field mapping to :func:`parse_workflow`. ``templates`` (dev/119): the
    roster snapshot that classifies executability; None → the legacy tables."""
    dataflow = (data or {}).get("dataflow") or {}
    nodes = []
    for n in dataflow.get("nodes") or []:
        if not (isinstance(n, dict) and n.get("id")):
            continue
        raw_type = n.get("type", "")
        category, engine = _classify_with_roster(raw_type, templates)
        nodes.append(NodeSpec(
            id=n["id"],
            type=normalize_type(raw_type),
            raw_type=raw_type,
            x=float(n.get("x", 0) or 0),
            y=float(n.get("y", 0) or 0),
            content=n.get("content", ""),
            in_type=n.get("in", "DEFAULT"),
            out_type=n.get("out", "DEFAULT"),
            category=category,
            engine=engine,
        ))
    edges = [
        {
            "id": e.get("id"),
            "source": e.get("source"),
            "target": e.get("target"),
            "type": e.get("type"),
            # dev/128: see the twin projection above — the handle is the merge's
            # slot authority, the same one the canvas uses at Play.
            "targetHandle": e.get("targetHandle") or e.get("target_handle"),
            "sourceHandle": e.get("sourceHandle") or e.get("source_handle"),
        }
        for e in dataflow.get("edges") or []
        if isinstance(e, dict)
    ]
    return WorkflowSpec(
        filepath="", name=name or (data or {}).get("name", ""), nodes=nodes, edges=edges
    )


# ---------------------------------------------------------------------------
# Input resolution: what a node receives from the nodes above it
# ---------------------------------------------------------------------------
#
# Every non-browser runner needs this and must agree with the others and with
# the canvas: the headless ``runner``, ``test_frontend.utils`` (expected
# outputs for the E2E comparisons) and ``tests/stress`` (the CI load harness).
# One copy, here, is what stops them drifting apart.
#
# The reference shape mirrors ``_parse_input_ref`` in
# ``backend/app/api/routes.py``: ``{"path": <artifact id | list of refs>,
# "dataType": <sandbox data type | "outputs">}``.


def resolve_node_input(spec, node_id: str, outputs: dict) -> dict:
    """Return the input reference for *node_id*, for a node about to execute.

    Raises ``KeyError`` when an upstream has not produced an output yet: for a
    node that is being executed, a missing upstream is a bug in the caller's
    ordering, not something to paper over.
    """
    upstreams = spec.upstream_nodes(node_id)
    if not upstreams:
        return {"path": "", "dataType": ""}
    if len(upstreams) == 1:
        return dict(outputs[upstreams[0]])
    return {"path": [outputs[uid] for uid in upstreams], "dataType": "outputs"}


def propagate_node_input(spec, node_id: str, outputs: dict) -> dict | None:
    """Return what a *non-executing* node passes downstream, or ``None``.

    Passive and browser-only nodes (VIS_*, MERGE_FLOW, a JS node in a Python
    runner) produce nothing of their own, so they forward what is above them.
    Unlike ``resolve_node_input`` this tolerates gaps: whole branches of a
    dataflow may never have run in the runner that is asking.
    """
    upstreams = spec.upstream_nodes(node_id)
    if len(upstreams) == 1 and upstreams[0] in outputs:
        return dict(outputs[upstreams[0]])
    if len(upstreams) > 1:
        return {
            "path": [outputs[uid] for uid in upstreams if uid in outputs],
            "dataType": "outputs",
        }
    return None


# ---------------------------------------------------------------------------
# Node source shaping: deterministic seeding and widget defaults, the two
# things the canvas applies to a node's code before sending it
# ---------------------------------------------------------------------------

_SEED_PREFIX = (
    "import numpy as _np; _np.random.seed({seed}); "
    "import random as _rnd; _rnd.seed({seed})\n"
)


def seed_node_code(code: str, seed: int = 42) -> str:
    """Prepend deterministic random-seed lines to *code*.

    Underscore-prefixed aliases (``_np``, ``_rnd``) never shadow the user's
    own ``import numpy as np``.
    """
    return _SEED_PREFIX.format(seed=seed) + code


_WIDGET_RE = re.compile(r"\[!!\s*(.*?)\s*!!\]")


def resolve_widget_placeholders(code: str) -> str:
    """Replace ``[!! name$type$default !!]`` widget markers with defaults —
    exactly as the frontend does before posting to the sandbox."""

    def _replace(m):
        parts = m.group(1).split("$")
        if len(parts) >= 3:
            return parts[2]
        return m.group(0)

    return _WIDGET_RE.sub(_replace, code)
