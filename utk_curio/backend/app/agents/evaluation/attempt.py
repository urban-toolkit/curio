"""Scoring one reconstruction attempt (memo dev/121).

The step between "the run finished" and "here is a number", shared by every
tier so a scripted run and a live run are judged by exactly the same code.
Values in, values out: the persisted spec, the Solve results, a template index
and a fixture -- no client, no store, no provider.

Two mappings matter here and both go through the comparator's node matching
rather than through the plan's own ref map. A scripted oracle happens to use
the fixture's refs, but a model does not: it invents its own, so anything that
depends on knowing which built node answers which expected node has to come
from the structural match. That is what makes the same function usable live.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from utk_curio.backend.app.agents.evaluation.canonical import (
    CanonicalGraph,
    TemplateIndex,
    canonical_graph_from_spec,
)
from utk_curio.backend.app.agents.evaluation.compare import (
    Comparison,
    Universe,
    compare_graphs,
)
from utk_curio.backend.app.agents.evaluation.dependencies import referenced_sources
from utk_curio.backend.app.agents.evaluation.scoring import (
    ExecutionOutcome,
    Score,
    evaluate_intents,
    score_reconstruction,
)

#: Edge kinds the plan contract cannot express on this branch. Passed to the
#: comparator so the expected edges become named capability gaps rather than
#: wrong scores.
#:
#: EMPTY since dev/125 (dev/121 F2): dev/112's ``edges[].kind`` and
#: ``plan_topology.py`` are on this branch now, so ``interaction`` left this
#: tuple and the eight T2 fixtures score on their own declared expectations --
#: with no fixture edited, exactly as dev/121 promised. The parameter stays
#: (and the comparator's gap machinery keeps its tests) because the NEXT
#: unexpressible construct should be nameable the same way, not discovered
#: prompt by prompt.
UNEXPRESSIBLE_EDGE_KINDS: tuple[str, ...] = ()

#: Solve statuses that mean "we never found out".
_UNMEASURED = ("pending", "not-attempted", "skipped")


@dataclass(frozen=True)
class AttemptScore:
    """Everything one attempt produced, ready for a report row."""

    expected: CanonicalGraph
    actual: CanonicalGraph
    comparison: Comparison
    score: Score
    intent_details: tuple = ()
    execution_details: tuple = ()

    def as_dict(self) -> dict:
        comparison = self.comparison
        return {
            "templates": {
                "agreed": comparison.templates.agreed,
                "missing": [list(m) for m in comparison.templates.missing],
                "extra": [list(e) for e in comparison.templates.extra],
                "expectedTotal": comparison.templates.expected_total,
                "actualTotal": comparison.templates.actual_total,
            },
            "edges": {
                "agreed": comparison.edges.agreed,
                "missing": list(comparison.edges.missing),
                "extra": list(comparison.edges.extra),
                "kindMismatch": list(comparison.edges.kind_mismatch),
                "slotMismatch": list(comparison.edges.slot_mismatch),
                "expectedTotal": comparison.edges.expected_total,
                "actualTotal": comparison.edges.actual_total,
            },
            "dependencies": {
                "datasetsMissing": list(comparison.dependencies.datasets_missing),
                "datasetsExtra": list(comparison.dependencies.datasets_extra),
                "packagesMissing": list(comparison.dependencies.packages_missing),
                "packagesExtra": list(comparison.dependencies.packages_extra),
                "undeclaredDatasetIds": list(comparison.dependencies.undeclared_dataset_ids),
                "undeclaredPaths": list(comparison.dependencies.undeclared_paths),
                "undeclaredUrls": list(comparison.dependencies.undeclared_urls),
            },
            "fabricated": [list(f) for f in comparison.fabricated],
            "capabilityGaps": [list(g) for g in comparison.capability_gaps],
            "contentMissing": list(comparison.content_missing),
            "intents": [
                {"ref": d.ref, "satisfied": d.satisfied, "detail": d.detail}
                for d in self.intent_details
            ],
            "execution": [
                {"node": d.node, "status": d.status, "executable": d.executable}
                for d in self.execution_details
            ],
            "notes": list(comparison.notes),
        }


def spec_nodes(spec: Mapping) -> list:
    inner = spec.get("dataflow")
    dataflow = inner if isinstance(inner, Mapping) else spec
    return [n for n in (dataflow.get("nodes") or []) if isinstance(n, Mapping)]


def intent_texts(
    *,
    expected_refs: Iterable,
    comparison: Comparison,
    actual: CanonicalGraph,
    actual_spec: Mapping,
) -> dict:
    """``{expected ref: the built node's own words}``.

    The built node is found through the structural match, so this works for a
    model that named everything differently. A ref with no match is absent
    rather than empty: "not built" and "built with nothing to say" are
    different findings.
    """
    refs = list(expected_refs)
    nodes = spec_nodes(actual_spec)
    texts: dict = {}
    for expected_index, actual_index in comparison.matching:
        if expected_index >= len(refs):
            continue
        if actual_index >= len(actual.origins):
            continue
        original = actual.origins[actual_index]
        if original >= len(nodes):
            continue
        node = nodes[original]
        words = " ".join(
            str(node.get(field) or "")
            for field in ("goal", "title", "intent")
        ).strip()
        texts[refs[expected_index]] = words
    return texts


def execution_outcomes(
    solve_results: Mapping,
    *,
    actual_spec: Mapping,
    templates: TemplateIndex,
) -> tuple:
    """Per-node verification, read from the Solve results.

    The node's own ``verification.status`` decides -- never the plan ledger,
    which records ``validated`` for a node that merely could not run (dev/118
    F6) and would credit a reconstruction for work nobody did.
    """
    from utk_curio.backend.app.packages.services import canonical_template_id

    by_id = {str(n.get("id")): n for n in spec_nodes(actual_spec)}
    outcomes: list = []
    for node_id, result in (solve_results or {}).items():
        if not isinstance(result, Mapping):
            continue
        node = by_id.get(str(node_id)) or {}
        facts = templates.get(canonical_template_id(node.get("type")))
        executable = bool(getattr(facts, "executable", False))
        verification = result.get("verification")
        status = ""
        if isinstance(verification, Mapping) and verification.get("status"):
            status = str(verification["status"])
        else:
            status = str(result.get("status") or "")
        if status == "not-executable":
            executable = False
        if status == "solved" and executable:
            status = "verified"
        outcomes.append(
            ExecutionOutcome(node=str(node_id), status=status, executable=executable)
        )
    return tuple(outcomes)


def score_attempt(
    fixture,
    *,
    actual_spec: Mapping,
    templates: TemplateIndex,
    example: Mapping,
    universe: Universe | None = None,
    solve_results: Mapping | None = None,
    unexpressible_kinds: Iterable = UNEXPRESSIBLE_EDGE_KINDS,
    refused: bool = False,
    timed_out: bool = False,
    provider_error: str | None = None,
    harness_error: str | None = None,
) -> AttemptScore:
    """Compare the persisted reconstruction against the fixture and score it."""
    expected_refs = [n["ref"] for n in fixture.expected["nodes"]]
    expected = canonical_graph_from_spec(
        example,
        templates=templates,
        sources=referenced_sources(example, templates=templates),
    )
    actual = canonical_graph_from_spec(
        actual_spec,
        templates=templates,
        sources=referenced_sources(actual_spec, templates=templates),
    )
    slot_sensitive = [
        str(intent.get("ref"))
        for intent in fixture.intents
        if intent.get("slotOrderMatters")
    ]
    comparison = compare_graphs(
        expected,
        actual,
        universe=universe,
        required_datasets=fixture.required["datasets"],
        required_packages=fixture.required["packages"],
        required_paths=fixture.required.get("paths") or (),
        unexpressible_kinds=unexpressible_kinds,
        slot_sensitive_refs=slot_sensitive,
        expected_refs=expected_refs,
    )
    comparison = _pair_interchangeable_by_words(
        comparison,
        expected=expected,
        actual=actual,
        actual_spec=actual_spec,
        fixture=fixture,
        expected_refs=expected_refs,
    )
    texts = intent_texts(
        expected_refs=expected_refs,
        comparison=comparison,
        actual=actual,
        actual_spec=actual_spec,
    )
    execution = execution_outcomes(
        solve_results or {}, actual_spec=actual_spec, templates=templates
    )
    kinds = _output_kinds(solve_results or {}, actual_spec=actual_spec)
    intent_details = evaluate_intents(
        fixture.intents,
        texts=texts,
        output_kinds=_kinds_by_ref(kinds, comparison=comparison, actual=actual,
                                   expected_refs=expected_refs, actual_spec=actual_spec),
    )
    score = score_reconstruction(
        comparison,
        intents=intent_details,
        execution=execution,
        refused=refused,
        predicted_refusal=bool(fixture.capability.get("skip")),
        timed_out=timed_out,
        provider_error=provider_error,
        harness_error=harness_error,
    )
    return AttemptScore(
        expected=expected,
        actual=actual,
        comparison=comparison,
        score=score,
        intent_details=intent_details,
        execution_details=execution,
    )


def _pair_interchangeable_by_words(
    comparison: Comparison,
    *,
    expected: CanonicalGraph,
    actual: CanonicalGraph,
    actual_spec: Mapping,
    fixture,
    expected_refs: Iterable,
) -> Comparison:
    """Break structural ties with the fixture's own words.

    Example 01's two aggregation branches are automorphic -- one groups by
    feature type, the other by neighborhood, and structurally they are the same
    node in the same place. No structural matcher can tell them apart, so a
    reordered reconstruction paired them arbitrarily and the fixture's per-node
    word assertions failed on a graph that was perfectly correct. That was a
    harness defect reported as a model defect, which is the worst kind.

    So after the structural match, pairs of expected nodes that are truly
    interchangeable (identical canonical nodes, and their partners identical
    too) may swap partners when the swap satisfies more of the fixture's word
    assertions. Interchangeable means the swap provably cannot change any
    structural finding: the edge diff is computed over positions whose nodes
    are equal.
    """
    intents = [dict(i) for i in fixture.intents if i.get("mustMention")]
    if len(intents) < 2:
        return comparison
    refs = list(expected_refs)
    index_of_ref = {ref: index for index, ref in enumerate(refs)}
    mapping = dict(comparison.matching)

    def satisfied(current: Mapping) -> int:
        texts = intent_texts(
            expected_refs=refs,
            comparison=Comparison(matching=tuple(sorted(current.items()))),
            actual=actual,
            actual_spec=actual_spec,
        )
        count = 0
        for intent in intents:
            text = str(texts.get(str(intent.get("ref")), "")).lower()
            if text and all(
                str(word).lower() in text for word in intent.get("mustMention") or ()
            ):
                count += 1
        return count

    best = satisfied(mapping)
    candidates = [
        index_of_ref[str(i["ref"])]
        for i in intents
        if str(i.get("ref")) in index_of_ref
    ]
    for position, left in enumerate(candidates):
        for right in candidates[position + 1:]:
            if left not in mapping or right not in mapping:
                continue
            if expected.nodes[left] != expected.nodes[right]:
                continue
            if actual.nodes[mapping[left]] != actual.nodes[mapping[right]]:
                continue
            trial = dict(mapping)
            trial[left], trial[right] = trial[right], trial[left]
            score = satisfied(trial)
            if score > best:
                mapping, best = trial, score
    if dict(comparison.matching) == mapping:
        return comparison
    from dataclasses import replace

    return replace(comparison, matching=tuple(sorted(mapping.items())))


def _output_kinds(solve_results: Mapping, *, actual_spec: Mapping) -> dict:
    """``{node id: the data type the run produced}`` -- today always empty.

    The Solve payload records each attempt's ROUND kind (``executed``,
    ``ungrounded-source``, ``upstream-blocker``) and not the artifact's data
    type, so there is no channel from a verified run to "it produced a
    GeoDataFrame". Reading the round kind as a data type is how the first cut
    of this module reported four false intent mismatches, which is why this
    function exists to return nothing rather than something plausible.

    A fixture's ``outputKind`` therefore stays UNMEASURED and is excluded from
    the score's denominator, exactly like a column-schema assertion (dev/115
    F4 / dev/118 F3). When the runtime journal carries the type, this is the
    one place that changes.
    """
    return {}


def _kinds_by_ref(
    kinds_by_node: Mapping,
    *,
    comparison: Comparison,
    actual: CanonicalGraph,
    expected_refs: Iterable,
    actual_spec: Mapping,
) -> dict:
    refs = list(expected_refs)
    nodes = spec_nodes(actual_spec)
    out: dict = {}
    for expected_index, actual_index in comparison.matching:
        if expected_index >= len(refs) or actual_index >= len(actual.origins):
            continue
        original = actual.origins[actual_index]
        if original >= len(nodes):
            continue
        node_id = str(nodes[original].get("id") or "")
        if node_id in kinds_by_node:
            out[refs[expected_index]] = kinds_by_node[node_id]
    return out
