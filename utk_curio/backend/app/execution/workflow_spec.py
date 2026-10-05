"""Workflow spec model + topology (promoted from the Playwright test tree,
memo dev/67-7).

Single source: the e2e suite imports THIS module through a shim, so the
headless runner and the browser tests read one semantics — Kahn ordering that
skips Interaction edges, ``in_N`` input ordering, the legacy/namespaced
type mapping, and the code/grammar/datapool/passive classification.
"""

import json
import os
import re
from dataclasses import dataclass, field
from collections import deque

from utk_curio.backend.app.execution.code_references import (
    CodeReferenceError,
    normalize_selections,
    normalize_widgets,
    resolve_references,
)

#: The node that holds one shared widget, which any node's code names as
#: ``[!! @name !!]``. Kept in sync with ``PARAMETER_NODE_TYPE`` in
#: ``src/utils/references/sharedParameters.ts``.
PARAMETER_TYPE = "curio.builtin/parameter"


def named_input_slot(edge: dict) -> int | None:
    """Which input circle an edge names: ``in`` → 0, ``in_N`` → N, or None.

    The HANDLE is the authority, exactly as the canvas reads it
    (``inputSlots.inputSlotOf(e.targetHandle)`` → the order Play assembles
    ``arg`` in). The edge id's ``in_N`` suffix is the canvas's own legacy
    encoding and stays as a fallback for specs saved with no handle; an edge
    whose handle is ``in`` is circle 0 whatever its id says.

    dev/128, from a field failure: agent-applied edges carry a UUID id and the
    slot in ``targetHandle`` (dev/67-3 made handles explicit), so reading only
    the id left every plan-created fan-in unordered, sorted lexicographically
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
            text = handle.strip()
            if text == "in":
                return 0
            m = re.match(r"^in_(\d+)$", text)
            if m:
                return int(m.group(1))
    # e.g. ``...78504in_1`` (no hyphen before ``in_``): the canvas's edge ids.
    m = re.search(r"in_(\d+)$", str(edge.get("id") or ""))
    return int(m.group(1)) if m else None


def input_slot(edge: dict) -> int:
    """The circle an edge feeds: ``in_N`` is circle N, and the plain ``in``
    handle (or none) is circle 0."""
    index = named_input_slot(edge)
    return index if index is not None else 0


def slot_handle_id(slot: int) -> str:
    """The handle id of circle *slot*; ``slotHandleId`` in ``utils/inputSlots.ts``."""
    return "in" if slot == 0 else f"in_{slot}"


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
    "COMPUTATION_ANALYSIS",
}
CODE_TYPES = PY_CODE_TYPES | {"JS_COMPUTATION"}

# The CODE_TYPES that render a "code" tab with a Monaco editor: all of them.
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
    "curio.builtin/autk-grammar":         "AUTK_GRAMMAR",
}


# workflow_spec.py -> execution/ -> app/ -> backend/ -> utk_curio/ -> repo_root/packages/
_PACKAGES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "packages"
)
_package_code_types: dict[str, str] | None = None


def package_code_types() -> dict[str, str]:
    """Shipped package templates that are Python code nodes, by namespaced id.

    A template with ``behavior: "code"``, ``engine: "python"`` and a code
    editor renders and runs like a Computation Analysis node, so the e2e suite
    plays it, reads its editor, and executes it for the ground truth like one.
    Without this, a package's code node reads as passive and its output is
    never computed, so every node downstream compares against its input.
    """
    global _package_code_types
    if _package_code_types is None:
        found: dict[str, str] = {}
        for entry in sorted(os.listdir(_PACKAGES_DIR)) if os.path.isdir(_PACKAGES_DIR) else []:
            path = os.path.join(_PACKAGES_DIR, entry, "manifest.json")
            if entry.startswith("curio.builtin@") or not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            for template in manifest.get("templates") or []:
                if (template.get("behavior"), template.get("engine"), template.get("editor")) == (
                    "code", "python", "code",
                ):
                    found[f"{manifest['id']}/{template['id']}"] = "COMPUTATION_ANALYSIS"
        _package_code_types = found
    return _package_code_types


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
    if node_type in NAMESPACED_TO_LEGACY:
        return NAMESPACED_TO_LEGACY[node_type]
    return package_code_types().get(node_type, node_type)


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
        "passive"  : no standard editor and no play button (e.g. VIS_SIMPLE)
    """
    if node_type in GRAMMAR_TYPES:
        return "grammar"
    if node_type == "DATA_POOL":
        return "datapool"
    if node_type in CODE_TYPES:
        return "code"
    # VIS_SIMPLE, COMMENTS, or any unknown type
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
    #: #662: the node's widgets (``metadata.widgets``), which its
    #: ``[!! name !!]`` references resolve against.
    widgets: list = field(default_factory=list)
    #: #662: the node's selection tags (``metadata.selections``), each holding
    #: the ids its ``[!! selection name !!]`` references resolve to.
    selections: list = field(default_factory=list)

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

    def _data_edges_to(self, node_id: str) -> list[dict]:
        """The data-flow edges into *node_id*, in circle order."""
        edges_to = [
            e for e in self.edges
            if e["target"] == node_id and e.get("type") != "Interaction"
        ]

        def sort_key(e: dict) -> tuple:
            return (input_slot(e), str(e.get("id") or ""))

        return sorted(edges_to, key=sort_key)

    def upstream_nodes(self, node_id: str) -> list[str]:
        """Return source node IDs feeding into *node_id* (data-flow edges only).

        Interaction edges are excluded because they carry selection state,
        not data.

        Sources are ordered by the circle they feed: the plain ``in`` handle
        first, then ``in_1``, ``in_2``, … — the same authority the canvas uses
        to build ``arg`` at Play (``inputSlots``), with the edge id's legacy
        ``in_N`` suffix as a fallback (dev/128).
        """
        return [e["source"] for e in self._data_edges_to(node_id)]

    def input_slots(self, node_id: str) -> list[int]:
        """The circles of *node_id* that have an edge, in order."""
        return [input_slot(e) for e in self._data_edges_to(node_id)]

    def shared_widgets(self) -> list:
        """The widgets the dataflow's Parameter nodes hold, in node order: what
        a ``[!! @name !!]`` reference names (#662). A Parameter node has no
        edge, so its value reaches a node through this list, not an input."""
        return [
            widget
            for n in self.nodes
            if isinstance(n.raw_type, str) and n.raw_type.split("@", 1)[0] == PARAMETER_TYPE
            for widget in n.widgets
        ]

    def node_code(self, node, language: str, content: str | None = None) -> str:
        """*node*'s code (or *content* in its place) with its references
        resolved as the canvas resolves them before a run: its widgets, its
        wired circles, the shared tags and its selection tags. Raises
        ``CodeReferenceError``."""
        return resolve_code_references(
            node.content if content is None else content,
            node.widgets,
            language,
            self.input_slots(node.id),
            self.shared_widgets(),
            node.selections,
        )

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
            widgets=normalize_widgets((n.get("metadata") or {}).get("widgets")),
            selections=normalize_selections((n.get("metadata") or {}).get("selections")),
        )
        for n in dataflow["nodes"]
    ]

    edges = [
        {
            "id": e["id"],
            "source": e["source"],
            "target": e["target"],
            "type": e.get("type"),
            # dev/128: the input handle is what orders a node's inputs, and
            # dropping it here is what made an agent-applied fan-in unordered.
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
            widgets=normalize_widgets((n.get("metadata") or {}).get("widgets")),
            selections=normalize_selections((n.get("metadata") or {}).get("selections")),
        ))
    edges = [
        {
            "id": e.get("id"),
            "source": e.get("source"),
            "target": e.get("target"),
            "type": e.get("type"),
            # dev/128: see the twin projection above: the handle is the node's
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
# The reference shape mirrors ``parse_input_ref`` in
# ``backend/app/execution/node_exec.py``: ``{"path": <artifact id | list of refs>,
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

    Passive and browser-only nodes (VIS_*, DATA_POOL, a JS node in a Python
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


def resolve_code_references(
    code: str, widgets=(), language: str = "python", input_slots=(), shared=(), selections=()
) -> str:
    """Replace a node's references with code, exactly as the frontend does
    before posting to the sandbox (#662): widget references with their values,
    input and column references by *input_slots*, the circles that have an
    edge, shared references with the values of the *shared* widgets
    (``WorkflowSpec.shared_widgets``), and selection references with the ids
    the node's *selections* hold (``metadata.selections``).

    Raises ``CodeReferenceError`` naming every reference that cannot be
    resolved: an old ``[!! name$TYPE$default !!]`` marker, a name the node has
    no widget or selection tag for, an input with no edge, a Parameter node
    that is missing or named twice, or a selection holding more ids than a tag
    takes.
    """
    inputs = [{"slot": slot} for slot in input_slots]
    resolved, problems = resolve_references(code, widgets, language, inputs, shared, selections)
    if problems:
        raise CodeReferenceError("\n".join(p["message"] for p in problems))
    return resolved
