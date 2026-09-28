"""Semantic comparison of two canonical graphs (memo dev/121).

The question is never "are these two files the same" -- they never are. It is
"did the agent build the dataflow the person asked for": the same kinds of
node, wired the same way, reading the same declared data, inventing nothing.
So the comparison is structural and set-based, and it says WHY it differs in
terms a report can categorize.

Matching pairs nodes across the two graphs by colour refinement (the same
Weisfeiler-Leman signature the canonical labeling uses, computed jointly so a
colour means the same thing on both sides), then improves the pairing by
bounded swapping within a colour class to agree on as many edges as possible.
Nodes with no partner are missing (expected, unbuilt) or extra (built,
unasked). Two truly interchangeable nodes make either pairing correct, which is
why the swap search is an optimization and not a correctness requirement.

Unrepresentable constructs are separated from wrong ones. An expected edge the
plan contract on this branch cannot express -- a bidirectional interaction link
-- is attributed to a CAPABILITY GAP when the fixture declared that need, never
counted as a topology error and never quietly dropped from the expectation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from utk_curio.backend.app.agents.evaluation.canonical import CanonicalGraph, CEdge
from utk_curio.backend.app.agents.evaluation.dependencies import url_allowed

#: Swap passes allowed while improving a pairing. Each pass is monotone (a swap
#: is kept only when it agrees on more edges), so this bounds work, not quality.
_SWAP_PASSES = 8

#: Colour-refinement rounds. Three is enough to separate every node the shipped
#: corpus distinguishes; more cannot hurt but costs time on the live path.
_REFINEMENT_ROUNDS = 3


@dataclass(frozen=True)
class Universe:
    """What exists, as the run saw it -- the fabrication baseline.

    Every field is a snapshot a transport read from a production surface: the
    template roster (``available_templates``), the catalog listing
    (``list_catalog``), the committed package catalog, and the fixture's own
    allowed URL prefixes. A resource outside all of them was invented.
    """

    templates: frozenset = field(default_factory=frozenset)
    dataset_ids: frozenset = field(default_factory=frozenset)
    package_dir_names: frozenset = field(default_factory=frozenset)
    allowed_url_prefixes: tuple = ("https://vega.github.io/schema/",)
    #: Paths the user named in the conversation (the DEC-072 typed-path route).
    allowed_paths: frozenset = field(default_factory=frozenset)


@dataclass(frozen=True)
class TemplateDiff:
    missing: tuple = ()   # (type, count) expected more than built
    extra: tuple = ()     # (type, count) built more than expected
    agreed: int = 0
    expected_total: int = 0
    actual_total: int = 0


@dataclass(frozen=True)
class EdgeDiff:
    agreed: int = 0
    missing: tuple = ()          # expected edges with no counterpart
    extra: tuple = ()            # built edges nobody asked for
    kind_mismatch: tuple = ()    # right endpoints, wrong kind
    slot_mismatch: tuple = ()    # right endpoints and kind, wrong merge slot
    expected_total: int = 0
    actual_total: int = 0


@dataclass(frozen=True)
class DependencyDiff:
    datasets_missing: tuple = ()
    datasets_extra: tuple = ()
    packages_missing: tuple = ()
    packages_extra: tuple = ()
    #: Sources the code reads that the fixture did not declare.
    undeclared_dataset_ids: tuple = ()
    undeclared_paths: tuple = ()
    undeclared_urls: tuple = ()
    #: How many dependencies the fixture required, and how many the
    #: reconstruction declared -- the two sizes a set overlap needs.
    required_total: int = 0
    declared_total: int = 0

    @property
    def agreed(self) -> int:
        return self.required_total - len(self.datasets_missing) - len(self.packages_missing)

    @property
    def union(self) -> int:
        return self.agreed + len(self.datasets_missing) + len(self.packages_missing) + (
            len(self.datasets_extra) + len(self.packages_extra)
        )

    @property
    def differences(self) -> int:
        return (
            len(self.datasets_missing) + len(self.packages_missing)
            + len(self.datasets_extra) + len(self.packages_extra)
        )


@dataclass(frozen=True)
class Comparison:
    matching: tuple = ()          # (expected index, actual index) pairs
    #: Matched nodes the example filled but the reconstruction left empty.
    #: Reported, not scored: the plan contract leaves content to Solve and to
    #: separate reviewed content steps, so an empty grammar node is a stage of
    #: the workflow rather than a wrong node -- but a reader should see it.
    content_missing: tuple = ()
    unmatched_expected: tuple = ()
    unmatched_actual: tuple = ()
    templates: TemplateDiff = field(default_factory=TemplateDiff)
    edges: EdgeDiff = field(default_factory=EdgeDiff)
    dependencies: DependencyDiff = field(default_factory=DependencyDiff)
    fabricated: tuple = ()        # (kind, literal) -- invented resources
    capability_gaps: tuple = ()   # ("interaction-edge", count) etc.
    notes: tuple = ()

    @property
    def exact(self) -> bool:
        """Structural exactness. ``content_missing`` is not part of it: see
        the field's own note."""
        return not (
            self.unmatched_expected
            or self.unmatched_actual
            or self.templates.missing
            or self.templates.extra
            or self.edges.missing
            or self.edges.extra
            or self.edges.kind_mismatch
            or self.edges.slot_mismatch
            or self.fabricated
            or self.capability_gaps
        )


def _signatures(graph: CanonicalGraph) -> list:
    """Per-node refinement signature, as comparable values (not ranks), so the
    same structure produces the same signature in both graphs."""
    in_adj: list = [[] for _ in graph.nodes]
    out_adj: list = [[] for _ in graph.nodes]
    for edge in graph.edges:
        in_adj[edge.dst].append((edge.src, edge.kind, -1 if edge.slot is None else edge.slot))
        out_adj[edge.src].append((edge.dst, edge.kind))
    colours = [(node.type, node.role, node.executable) for node in graph.nodes]
    for _ in range(_REFINEMENT_ROUNDS):
        colours = [
            (
                colours[i],
                tuple(sorted((colours[src], kind, slot) for src, kind, slot in in_adj[i])),
                tuple(sorted((colours[dst], kind) for dst, kind in out_adj[i])),
            )
            for i in range(len(colours))
        ]
    return colours


def _agreed_edges(
    expected: CanonicalGraph,
    actual: CanonicalGraph,
    mapping: Mapping,
) -> int:
    actual_keys = {(e.src, e.dst, e.kind) for e in actual.edges}
    count = 0
    for edge in expected.edges:
        src, dst = mapping.get(edge.src), mapping.get(edge.dst)
        if src is None or dst is None:
            continue
        if (src, dst, edge.kind) in actual_keys:
            count += 1
    return count


def _match_nodes(expected: CanonicalGraph, actual: CanonicalGraph) -> tuple:
    """Pair nodes across the graphs; return (mapping, unmatched_expected,
    unmatched_actual, notes)."""
    expected_sig = _signatures(expected)
    actual_sig = _signatures(actual)

    # Colour classes: first by full refinement signature, then, for whatever is
    # left over, by the node's own attributes -- so a node whose neighbourhood
    # differs still pairs with its own kind and is reported as a topology
    # difference rather than as a missing node plus an extra one.
    mapping: dict = {}
    used_actual: set = set()
    notes: list = []

    for keying in ("signature", "attributes"):
        expected_groups: dict = {}
        actual_groups: dict = {}
        for index, node in enumerate(expected.nodes):
            if index in mapping:
                continue
            key = expected_sig[index] if keying == "signature" else (node.type, node.role)
            expected_groups.setdefault(key, []).append(index)
        for index, node in enumerate(actual.nodes):
            if index in used_actual:
                continue
            key = actual_sig[index] if keying == "signature" else (node.type, node.role)
            actual_groups.setdefault(key, []).append(index)
        for key, expected_indices in expected_groups.items():
            candidates = actual_groups.get(key) or []
            for expected_index, actual_index in zip(expected_indices, candidates):
                mapping[expected_index] = actual_index
                used_actual.add(actual_index)
            if keying == "attributes" and len(expected_indices) > 1 and candidates:
                notes.append(
                    f"{len(expected_indices)} nodes of kind {key[0]} paired by attributes "
                    "after refinement could not separate them"
                )

    # Improve the pairing by swapping within a class: monotone, bounded, and
    # only ever needed where a class held more than one node.
    classes: dict = {}
    for expected_index in mapping:
        classes.setdefault(expected_sig[expected_index], []).append(expected_index)
    best = _agreed_edges(expected, actual, mapping)
    for _ in range(_SWAP_PASSES):
        improved = False
        for members in classes.values():
            if len(members) < 2:
                continue
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    a, b = members[i], members[j]
                    mapping[a], mapping[b] = mapping[b], mapping[a]
                    score = _agreed_edges(expected, actual, mapping)
                    if score > best:
                        best, improved = score, True
                    else:
                        mapping[a], mapping[b] = mapping[b], mapping[a]
        if not improved:
            break

    unmatched_expected = tuple(i for i in range(len(expected.nodes)) if i not in mapping)
    unmatched_actual = tuple(i for i in range(len(actual.nodes)) if i not in used_actual)
    return mapping, unmatched_expected, unmatched_actual, tuple(notes)


def _template_diff(expected: CanonicalGraph, actual: CanonicalGraph) -> TemplateDiff:
    expected_counts = expected.type_counts()
    actual_counts = actual.type_counts()
    missing = tuple(
        (node_type, count - actual_counts.get(node_type, 0))
        for node_type, count in sorted(expected_counts.items())
        if count > actual_counts.get(node_type, 0)
    )
    extra = tuple(
        (node_type, count - expected_counts.get(node_type, 0))
        for node_type, count in sorted(actual_counts.items())
        if count > expected_counts.get(node_type, 0)
    )
    agreed = sum(
        min(count, actual_counts.get(node_type, 0))
        for node_type, count in expected_counts.items()
    )
    return TemplateDiff(
        missing=missing,
        extra=extra,
        agreed=agreed,
        expected_total=len(expected.nodes),
        actual_total=len(actual.nodes),
    )


def _describe(graph: CanonicalGraph, edge: CEdge) -> dict:
    return {
        "from": graph.nodes[edge.src].type if edge.src < len(graph.nodes) else "?",
        "to": graph.nodes[edge.dst].type if edge.dst < len(graph.nodes) else "?",
        "kind": edge.kind,
        "slot": edge.slot,
    }


def _edge_diff(
    expected: CanonicalGraph,
    actual: CanonicalGraph,
    mapping: Mapping,
    *,
    unexpressible_kinds: Iterable = (),
    slot_sensitive_expected_nodes: Iterable = (),
) -> tuple:
    """Edge diff plus the capability gaps it accounts for."""
    unexpressible = {str(k) for k in unexpressible_kinds}
    slot_sensitive = {int(i) for i in slot_sensitive_expected_nodes}

    actual_by_ends: dict = {}
    for edge in actual.edges:
        actual_by_ends.setdefault((edge.src, edge.dst), []).append(edge)
    consumed: set = set()

    agreed = 0
    missing: list = []
    kind_mismatch: list = []
    slot_mismatch: list = []
    gap_counts: dict = {}

    for edge in expected.edges:
        if edge.kind in unexpressible:
            gap_counts[edge.kind] = gap_counts.get(edge.kind, 0) + 1
            continue
        src, dst = mapping.get(edge.src), mapping.get(edge.dst)
        candidates = actual_by_ends.get((src, dst)) or [] if src is not None and dst is not None else []
        same_kind = [c for c in candidates if c.kind == edge.kind and id(c) not in consumed]
        if same_kind:
            chosen = same_kind[0]
            consumed.add(id(chosen))
            if chosen.slot != edge.slot and edge.dst in slot_sensitive:
                slot_mismatch.append(
                    {**_describe(expected, edge), "builtSlot": chosen.slot}
                )
            else:
                agreed += 1
            continue
        other_kind = [c for c in candidates if id(c) not in consumed]
        if other_kind:
            chosen = other_kind[0]
            consumed.add(id(chosen))
            kind_mismatch.append({**_describe(expected, edge), "builtKind": chosen.kind})
            continue
        missing.append(_describe(expected, edge))

    extra = tuple(
        _describe(actual, edge) for edge in actual.edges if id(edge) not in consumed
    )
    expected_scored = sum(1 for e in expected.edges if e.kind not in unexpressible)
    diff = EdgeDiff(
        agreed=agreed,
        missing=tuple(missing),
        extra=extra,
        kind_mismatch=tuple(kind_mismatch),
        slot_mismatch=tuple(slot_mismatch),
        expected_total=expected_scored,
        actual_total=len(actual.edges),
    )
    gaps = tuple(sorted((f"{kind}-edge", count) for kind, count in gap_counts.items()))
    return diff, gaps


def _dependency_diff(
    actual: CanonicalGraph,
    *,
    required_datasets: Iterable,
    required_packages: Iterable,
    required_paths: Iterable,
    universe: Universe,
) -> tuple:
    """Dependency diff and the fabrication findings the sources imply."""
    required_ds = {str(d) for d in required_datasets}
    required_pk = {str(p) for p in required_packages}
    required_ph = {str(p) for p in required_paths}

    diff = DependencyDiff(
        required_total=len(required_ds) + len(required_pk),
        declared_total=len(actual.datasets) + len(actual.packages),
        datasets_missing=tuple(sorted(required_ds - set(actual.datasets))),
        datasets_extra=tuple(sorted(set(actual.datasets) - required_ds)),
        packages_missing=tuple(sorted(required_pk - set(actual.packages))),
        packages_extra=tuple(sorted(set(actual.packages) - required_pk)),
        undeclared_dataset_ids=tuple(
            sorted(set(actual.sources.dataset_ids) - required_ds)
        ),
        undeclared_paths=tuple(sorted(set(actual.sources.paths) - required_ph)),
        undeclared_urls=tuple(
            sorted(
                url for url in actual.sources.urls
                if not url_allowed(url, universe.allowed_url_prefixes)
            )
        ),
    )

    fabricated: list = []
    for node in actual.nodes:
        if universe.templates and node.type not in universe.templates:
            fabricated.append(("template", node.type))
    for dir_name in sorted(actual.packages):
        if universe.package_dir_names and dir_name not in universe.package_dir_names:
            fabricated.append(("package", dir_name))
    for dataset_id in sorted(set(actual.sources.dataset_ids) | set(actual.datasets)):
        if universe.dataset_ids and dataset_id not in universe.dataset_ids:
            fabricated.append(("dataset", dataset_id))
    for path in sorted(actual.sources.paths):
        allowed = set(universe.allowed_paths) | required_ph
        if path not in allowed:
            fabricated.append(("path", path))
    for url in diff.undeclared_urls:
        fabricated.append(("url", url))
    # Order-stable and duplicate-free: a report row per invented resource.
    unique: list = []
    for item in fabricated:
        if item not in unique:
            unique.append(item)
    return diff, tuple(unique)


def compare_graphs(
    expected: CanonicalGraph,
    actual: CanonicalGraph,
    *,
    universe: Universe | None = None,
    required_datasets: Iterable = (),
    required_packages: Iterable = (),
    required_paths: Iterable = (),
    unexpressible_kinds: Iterable = (),
    slot_sensitive_refs: Iterable = (),
    expected_refs: Iterable = (),
) -> Comparison:
    """Compare a reconstruction against the expectation.

    ``unexpressible_kinds`` names edge kinds the agent contract cannot express
    in this run (``"interaction"`` on this branch): those expected edges become
    capability gaps instead of topology failures. ``slot_sensitive_refs`` names
    expected nodes whose merge input ORDER matters, per the fixture -- elsewhere
    a swapped slot is not a defect.
    """
    universe = universe or Universe()
    refs = list(expected_refs) if expected_refs else []
    sensitive_indices = [
        refs.index(ref) for ref in slot_sensitive_refs if refs and ref in refs
    ]

    mapping, unmatched_expected, unmatched_actual, notes = _match_nodes(expected, actual)
    edge_diff, gaps = _edge_diff(
        expected,
        actual,
        mapping,
        unexpressible_kinds=unexpressible_kinds,
        slot_sensitive_expected_nodes=sensitive_indices,
    )
    dependency_diff, fabricated = _dependency_diff(
        actual,
        required_datasets=required_datasets,
        required_packages=required_packages,
        required_paths=required_paths,
        universe=universe,
    )
    if not expected.exact_labeling or not actual.exact_labeling:
        notes = notes + (
            "a canonical labeling hit its budget; this comparison is best-effort",
        )
    content_missing = tuple(
        expected.nodes[expected_index].type
        for expected_index, actual_index in sorted(mapping.items())
        if expected.nodes[expected_index].has_content
        and not actual.nodes[actual_index].has_content
    )
    return Comparison(
        matching=tuple(sorted(mapping.items())),
        content_missing=content_missing,
        unmatched_expected=unmatched_expected,
        unmatched_actual=unmatched_actual,
        templates=_template_diff(expected, actual),
        edges=edge_diff,
        dependencies=dependency_diff,
        fabricated=fabricated,
        capability_gaps=gaps,
        notes=notes,
    )
