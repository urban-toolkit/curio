"""Canonical graph form: a dataflow spec reduced to what a reconstruction can
be judged on (memo dev/121).

What survives normalization: the canonical unversioned template id of every
node, its derived role, whether the sandbox can run it, whether it carries
content, and the edges with their kind (data or interaction) and merge slot.

What is dropped, because a model cannot be asked to reproduce it and a person
would not care: node and edge ids (the runtime mints its own), positions,
widths and heights, timestamps, ``provenance_id``, ``metadata.keywords``, the
order nodes and edges appear in the file, and the node code itself -- code is
judged by executing it (Solve's verdict), never by string equality (dev/03
section 19: *a curated semantic-output rubric rather than byte equality*).

The canonical form is order-independent, and that takes more than sorting by
attributes: a graph whose nodes carry identical attributes (example 01's three
Data Transformation nodes, example 05's five loaders) would otherwise hand its
indices out in file order, so reversing the file would reverse the edges. So
the node order is a canonical LABELING -- colour refinement to a fixed point,
then individualization with backtracking, keeping the lexicographically
smallest edge tuple -- which makes equality of two canonical graphs mean they
are isomorphic. Truly interchangeable nodes (a symmetric fan-out) are
automorphic, so whichever one wins an index cannot change the result.

One vocabulary (``DEC-062``): node types go through
``packages.services.canonical_template_id`` -- the same canonicaliser the plan
grammar uses at its parse boundary -- and executability comes from the
``DEC-076`` derivation (``packages.services.template_is_executable``), never
from a name list kept here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from utk_curio.backend.app.packages.services import (
    canonical_template_id,
    template_is_executable,
)

#: Spec edges materialized for an interaction link carry ``type: "Interaction"``
#: (the trill form the canvas writes) and symmetric ``in/out`` handles. Both
#: spellings appear in the shipped corpus, so both are recognised.
INTERACTION_EDGE_TYPE = "Interaction"
_SYMMETRIC_HANDLE = "in/out"

#: A single-input port. Merge slots are ``in_0``..``in_4`` (DEC-051 arity).
_DEFAULT_HANDLES = ("", "in", "out", "DEFAULT", "default")

ROLES = (
    "loader",
    "transform",
    "analysis",
    "visualization",
    "grammar",
    "pool",
    "merge",
    "export",
    "endpoint",
    "presentation",
)


@dataclass(frozen=True)
class TemplateFacts:
    """The manifest facts a role and an executability verdict are derived from.

    Deliberately the manifest's own field names: this is a VALUE built by the
    caller (from ``packages/*/manifest.json`` in a checkout, or from a roster
    row where the fields exist), never a second table of node kinds. The
    attribute names match what ``packages.services.template_is_executable``
    reads, so the ``DEC-076`` derivation is reused rather than restated.
    """

    template_id: str
    category: str = "computation"
    engine: str = "python"
    editor: str = "code"
    has_code: bool = False
    has_grammar: bool = False
    behavior: str | None = None
    backend_handler: str | None = None

    @property
    def executable(self) -> bool:
        return bool(template_is_executable(self))


TemplateIndex = Mapping[str, TemplateFacts]


@dataclass(frozen=True)
class CNode:
    """One node, stripped to what is comparable."""

    type: str
    role: str
    executable: bool
    has_content: bool

    def sort_key(self) -> tuple:
        return (self.type, self.role, not self.executable, not self.has_content)


@dataclass(frozen=True)
class CEdge:
    """One edge as a pair of node indices into the sorted node tuple."""

    src: int
    dst: int
    kind: str = "data"
    slot: int | None = None

    def sort_key(self) -> tuple:
        return (self.src, self.dst, self.kind, -1 if self.slot is None else self.slot)


@dataclass(frozen=True)
class Sources:
    """What the graph's code actually reads -- the fabrication baseline."""

    dataset_ids: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    urls: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "datasetIds": list(self.dataset_ids),
            "paths": list(self.paths),
            "urls": list(self.urls),
        }


@dataclass(frozen=True)
class CanonicalGraph:
    """A dataflow reduced to its comparable shape."""

    nodes: tuple[CNode, ...] = ()
    edges: tuple[CEdge, ...] = ()
    datasets: frozenset = field(default_factory=frozenset)
    packages: frozenset = field(default_factory=frozenset)
    sources: Sources = field(default_factory=Sources)
    #: Whether the canonical labeling search finished (it always does for the
    #: shipped corpus). Excluded from equality on purpose: it describes how the
    #: value was computed, not what the graph is -- but a report says so, and a
    #: comparison of two graphs where either is False is best-effort.
    exact_labeling: bool = field(default=True, compare=False)

    def type_counts(self) -> dict:
        counts: dict = {}
        for node in self.nodes:
            counts[node.type] = counts.get(node.type, 0) + 1
        return counts

    def interaction_edges(self) -> tuple:
        return tuple(e for e in self.edges if e.kind == "interaction")

    def default_refs(self) -> list:
        """Readable, deterministic handles over the canonical node order:
        ``loader1``, ``transform1``, ``transform2``, ``visualization1``...

        Refs are labels a fixture author can read, not identity: they are
        positional over the canonical order, so recomputing a fixture's
        expected block with its own refs is a like-for-like comparison.
        """
        counters: dict = {}
        names: list = []
        for node in self.nodes:
            counters[node.role] = counters.get(node.role, 0) + 1
            names.append(f"{node.role}{counters[node.role]}")
        return names

    def as_expected_dict(self, refs: Iterable | None = None) -> dict:
        """The fixture's ``expected`` block for this graph.

        Refs are positional (``n0``, ``n1``, ...) over the sorted node order,
        so the same graph always writes the same fixture text.
        """
        names = list(refs) if refs is not None else self.default_refs()
        if len(names) != len(self.nodes):
            raise ValueError("refs must name every node")
        return {
            "nodes": [
                {
                    "ref": names[i],
                    "type": n.type,
                    "role": n.role,
                    "executable": n.executable,
                    "hasContent": n.has_content,
                }
                for i, n in enumerate(self.nodes)
            ],
            "edges": [
                {
                    "from": names[e.src],
                    "to": names[e.dst],
                    "kind": e.kind,
                    **({"slot": e.slot} if e.slot is not None else {}),
                }
                for e in self.edges
            ],
            "sources": self.sources.as_dict(),
        }


def role_for_template(
    facts: TemplateFacts | None,
    *,
    has_incoming_data_edge: bool,
) -> str:
    """The node's intended role, derived from its template's manifest facts and
    its position in the graph -- never from its name (``DEC-062``).

    The one structural input is ``has_incoming_data_edge``: a ``data``-category
    code template is a *loader* at the head of a flow and a *transform* once
    something feeds it, which is exactly the distinction the walkthroughs draw
    and the only one the manifest cannot make on its own.

    An unknown template (not in the index) is ``endpoint``: the harness knows
    nothing that would let it run, so it claims nothing.
    """
    if facts is None:
        return "endpoint"
    behavior = (facts.behavior or "").strip()
    if behavior == "data-pool":
        return "pool"
    if facts.category == "flow" or behavior == "merge-flow":
        return "merge"
    if behavior == "data-export":
        return "export"
    if facts.category in ("vis_grammar", "vis_simple"):
        return "visualization"
    if facts.has_grammar:
        return "grammar"
    if facts.category == "presentation":
        return "presentation"
    if not facts.has_code:
        # A widget or endpoint node: its work happens in the browser, in a
        # package backend handler, or in a dedicated service (dev/119's honest
        # "it has no code the sandbox could run").
        return "endpoint"
    if facts.category == "computation":
        return "analysis"
    if facts.category == "data":
        return "transform" if has_incoming_data_edge else "loader"
    return "analysis"


def edge_kind(edge: Mapping) -> str:
    """``"interaction"`` for a bidirectional link, ``"data"`` otherwise.

    Both spellings the corpus carries count: the trill ``type: "Interaction"``
    the canvas writes, and the symmetric ``in/out`` handles dev/112 specifies
    for the plan path.
    """
    if str(edge.get("type") or "") == INTERACTION_EDGE_TYPE:
        return "interaction"
    handles = (str(edge.get("sourceHandle") or ""), str(edge.get("targetHandle") or ""))
    if all(h == _SYMMETRIC_HANDLE for h in handles):
        return "interaction"
    return "data"


def edge_slot(edge: Mapping) -> int | None:
    """The merge input index from ``targetHandle: "in_N"``; ``None`` for a
    single-input port (``DEFAULT``, ``in``, absent, or a symmetric handle)."""
    handle = edge.get("targetHandle")
    if not isinstance(handle, str):
        return None
    text = handle.strip()
    if text in _DEFAULT_HANDLES:
        return None
    if text.startswith("in_"):
        tail = text[3:]
        if tail.isdigit():
            return int(tail)
    return None


#: Node visits allowed while searching for a canonical labeling. Reached only
#: by a graph with large non-automorphic symmetry; the corpus's biggest example
#: (27 nodes) settles in well under a hundred. On exhaustion the search keeps
#: the best order it found and reports ``exact=False`` so a caller can say so
#: rather than quietly comparing two differently-labeled graphs.
_LABELING_BUDGET = 20000


def _refine(colors: list, in_adj: list, out_adj: list) -> list:
    """Colour refinement (Weisfeiler-Leman) to a fixed point.

    A node's next colour is its current colour plus the multiset of its
    incoming ``(colour, kind, slot)`` and outgoing ``(colour, kind)`` -- so a
    Data Transformation that feeds two charts separates from one that feeds a
    single chart without either of them being named.
    """
    current = list(colors)
    while True:
        signatures = [
            (
                current[i],
                tuple(sorted((current[src], kind, slot) for src, kind, slot in in_adj[i])),
                tuple(sorted((current[dst], kind) for dst, kind, _ in out_adj[i])),
            )
            for i in range(len(current))
        ]
        ranks = {sig: rank for rank, sig in enumerate(sorted(set(signatures)))}
        nxt = [ranks[sig] for sig in signatures]
        if nxt == current:
            return current
        current = nxt


def _edge_tuple(order: list, in_adj: list) -> tuple:
    """The edge multiset expressed over a candidate labeling -- the value the
    canonical search minimizes."""
    position = {original: index for index, original in enumerate(order)}
    edges = []
    for dst_original, incoming in enumerate(in_adj):
        dst = position[dst_original]
        for src_original, kind, slot in incoming:
            edges.append((position[src_original], dst, kind, -1 if slot is None else slot))
    return tuple(sorted(edges))


def _canonical_order(attr_keys: list, in_adj: list, out_adj: list) -> tuple:
    """A canonical node order for the graph, and whether it is exact.

    Individualization-refinement: refine; if every colour class is a singleton
    the order is forced; otherwise individualize each member of the smallest
    ambiguous class in turn and keep the branch whose edge tuple is smallest.
    """
    size = len(attr_keys)
    if size <= 1:
        return list(range(size)), True

    initial_ranks = {key: rank for rank, key in enumerate(sorted(set(attr_keys)))}
    budget = [_LABELING_BUDGET]
    best: dict = {"edges": None, "order": None}
    exact = [True]

    def search(colors: list) -> None:
        refined = _refine(colors, in_adj, out_adj)
        classes: dict = {}
        for index, colour in enumerate(refined):
            classes.setdefault(colour, []).append(index)
        ambiguous = [members for members in classes.values() if len(members) > 1]
        if not ambiguous:
            order = sorted(range(size), key=lambda i: refined[i])
            edges = _edge_tuple(order, in_adj)
            if best["edges"] is None or edges < best["edges"]:
                best["edges"], best["order"] = edges, order
            return
        target = min(ambiguous, key=lambda members: (len(members), refined[members[0]]))
        for member in target:
            if budget[0] <= 0:
                exact[0] = False
                break
            budget[0] -= 1
            # Individualize: this node alone keeps its colour, the rest of its
            # class moves up, so refinement can distinguish what follows.
            individualized = [c * 2 + 1 for c in refined]
            individualized[member] = refined[member] * 2
            search(individualized)

    search([initial_ranks[key] for key in attr_keys])
    if best["order"] is None:  # budget exhausted before any leaf
        return sorted(range(size), key=lambda i: (attr_keys[i], i)), False
    return best["order"], exact[0]


def _node_has_content(node: Mapping) -> bool:
    content = node.get("content")
    return isinstance(content, str) and bool(content.strip())


def canonical_graph_from_spec(
    spec: Mapping,
    *,
    templates: TemplateIndex,
    sources: Sources | None = None,
) -> CanonicalGraph:
    """Reduce a trill spec (or a bare ``dataflow`` object) to canonical form.

    ``templates`` is the manifest-facts index for role and executability;
    ``sources`` is the code scan from :mod:`.dependencies`, passed in so this
    module stays a pure shape reducer.
    """
    inner = spec.get("dataflow")
    dataflow = inner if isinstance(inner, Mapping) else spec
    raw_nodes = [n for n in (dataflow.get("nodes") or []) if isinstance(n, Mapping)]
    raw_edges = [e for e in (dataflow.get("edges") or []) if isinstance(e, Mapping)]

    kinds = [edge_kind(e) for e in raw_edges]
    fed_by_data = {
        str(e.get("target"))
        for e, kind in zip(raw_edges, kinds)
        if kind == "data" and e.get("target") is not None
    }

    prepared: list = []
    for node in raw_nodes:
        node_id = str(node.get("id") or "")
        canonical = canonical_template_id(node.get("type"))
        facts = templates.get(canonical)
        prepared.append(
            (
                node_id,
                CNode(
                    type=canonical,
                    role=role_for_template(
                        facts, has_incoming_data_edge=node_id in fed_by_data
                    ),
                    executable=bool(facts.executable) if facts else False,
                    has_content=_node_has_content(node),
                ),
            )
        )

    # Adjacency over ORIGINAL indices, so the canonical labeling below can be
    # computed before any index is handed out. A dangling edge is a defect of
    # the spec, not of a reconstruction: it is dropped here and reported by the
    # schema suite that owns spec validity.
    original_of_id: dict = {}
    for index, (node_id, _) in enumerate(prepared):
        if node_id:
            original_of_id.setdefault(node_id, index)
    in_adj: list = [[] for _ in prepared]
    out_adj: list = [[] for _ in prepared]
    for edge, kind in zip(raw_edges, kinds):
        src = original_of_id.get(str(edge.get("source")))
        dst = original_of_id.get(str(edge.get("target")))
        if src is None or dst is None:
            continue
        slot = edge_slot(edge)
        in_adj[dst].append((src, kind, -1 if slot is None else slot))
        out_adj[src].append((dst, kind, -1 if slot is None else slot))

    attr_keys = [cnode.sort_key() for _, cnode in prepared]
    order, exact = _canonical_order(attr_keys, in_adj, out_adj)
    position_of_original = {original: index for index, original in enumerate(order)}
    nodes = [prepared[original][1] for original in order]

    edges: list = []
    for dst_original, incoming in enumerate(in_adj):
        for src_original, kind, slot in incoming:
            edges.append(
                CEdge(
                    src=position_of_original[src_original],
                    dst=position_of_original[dst_original],
                    kind=kind,
                    slot=None if slot < 0 else slot,
                )
            )

    declared_datasets = frozenset(
        str(ref.get("datasetId"))
        for ref in (dataflow.get("datasets") or [])
        if isinstance(ref, Mapping) and ref.get("datasetId")
    )
    declared_packages = frozenset(
        str(entry) for entry in (dataflow.get("packages") or []) if isinstance(entry, str)
    )

    return CanonicalGraph(
        nodes=tuple(nodes),
        edges=tuple(sorted(edges, key=lambda e: e.sort_key())),
        datasets=declared_datasets,
        packages=declared_packages,
        sources=sources or Sources(),
        exact_labeling=exact,
    )
