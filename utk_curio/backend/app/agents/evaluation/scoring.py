"""Scoring a reconstruction (memo dev/121, ``DEC-077``).

Five dimensions, fixed weights, and one rule that overrides all of them: an
invented resource caps the score at zero. Everything else is a proportion, and
anything the run could not measure is excluded from its denominator rather than
counted as a failure -- a sandbox outage is not a wrong answer (``DEC-073``),
and a node kind the sandbox cannot run is not a broken node (``DEC-076``).

The weights live here as constants because they describe the harness's opinion
of what matters; a fixture owns only its thresholds. Categories are the
vocabulary a report groups failures by, so a reader can tell "it built the
wrong shape" from "it invented a dataset" from "the contract cannot express
this".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from utk_curio.backend.app.agents.evaluation.compare import Comparison

#: Dimension weights. Their sum is 1.0 (test-pinned).
WEIGHTS = {
    "templates": 0.25,
    "topology": 0.25,
    "dependencies": 0.15,
    "intents": 0.15,
    "execution": 0.20,
}

#: One category per finding. A report row carries at least one, or ``pass``.
CATEGORIES = (
    "pass",
    "capability-gap",        # suffixed with the need, e.g. capability-gap:interaction-edge
    "fabrication",
    "missing-node",
    "extra-node",
    "topology",
    "dependency-unresolved",
    "dependency-unrequested",
    "intent-mismatch",
    "execution-failed",
    "refused",
    "timeout",
    "provider-error",
    "harness-error",
)

#: A verification status that means "we never found out", not "it failed".
_NOT_MEASURED_STATUSES = ("pending", "not-executable", "skipped", "not-attempted")


@dataclass(frozen=True)
class Dimension:
    name: str
    value: float | None      # None = not measured
    weight: float
    detail: str = ""

    @property
    def measured(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class Score:
    dimensions: tuple = ()
    total: float = 0.0
    categories: tuple = ()
    capped_by_fabrication: bool = False
    notes: tuple = ()

    def as_dict(self) -> dict:
        return {
            "total": round(self.total, 4),
            "dimensions": {
                d.name: (None if d.value is None else round(d.value, 4))
                for d in self.dimensions
            },
            "weights": {d.name: d.weight for d in self.dimensions},
            "categories": list(self.categories),
            "cappedByFabrication": self.capped_by_fabrication,
            "notes": list(self.notes),
        }

    def dimension(self, name: str) -> Dimension | None:
        for dimension in self.dimensions:
            if dimension.name == name:
                return dimension
        return None

    def meets(self, thresholds: Mapping) -> bool:
        """Whether the score clears the fixture's bars. A dimension that was
        not measured cannot fail its threshold -- there is nothing to judge."""
        if self.total < float(thresholds.get("pass", 1.0)):
            return False
        for dimension in self.dimensions:
            bar = thresholds.get(dimension.name)
            if bar is None or dimension.value is None:
                continue
            if dimension.value < float(bar):
                return False
        return True


def _f1(agreed: int, expected_total: int, actual_total: int) -> float | None:
    """Harmonic mean of precision and recall over a multiset.

    ``None`` when there was nothing to compare on either side: a graph with no
    edges (a two-node example) has no topology to be right or wrong about.
    """
    if expected_total == 0 and actual_total == 0:
        return None
    if agreed == 0:
        return 0.0
    precision = agreed / actual_total if actual_total else 0.0
    recall = agreed / expected_total if expected_total else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


@dataclass(frozen=True)
class IntentOutcome:
    """One fixture intent, judged against the node it matched."""

    ref: str
    satisfied: bool | None   # None = not measurable this run
    detail: str = ""


@dataclass(frozen=True)
class ExecutionOutcome:
    """Per-node verification, as the persisted spec recorded it.

    ``status`` is the node's ``verification.status`` -- never the plan ledger's
    word, which reads ``validated`` for a node that merely could not run
    (dev/118 F6) and would over-credit a reconstruction.
    """

    node: str
    status: str
    executable: bool = True

    @property
    def measured(self) -> bool:
        return self.executable and self.status not in _NOT_MEASURED_STATUSES

    @property
    def passed(self) -> bool:
        return self.status in ("verified", "solved", "passed")


def evaluate_intents(
    intents: Iterable,
    *,
    texts: Mapping,
    output_kinds: Mapping | None = None,
) -> tuple:
    """Judge each fixture intent against the reconstructed node's own words.

    ``texts`` maps an expected ref to the goal/intent text of the node it
    matched; a ref with no entry was never built, which the node dimensions
    already penalise, so it is not measurable here rather than counted twice.
    """
    kinds = dict(output_kinds or {})
    outcomes: list = []
    for intent in intents:
        ref = str(intent.get("ref") or "")
        text = texts.get(ref)
        if text is None:
            outcomes.append(IntentOutcome(ref=ref, satisfied=None, detail="node not built"))
            continue
        lowered = str(text).lower()
        mentions = [str(m).lower() for m in (intent.get("mustMention") or [])]
        missing = [m for m in mentions if m not in lowered]
        wanted_kind = intent.get("outputKind")
        actual_kind = kinds.get(ref)
        problems: list = []
        if mentions and missing:
            problems.append("mentions none of " + ", ".join(repr(m) for m in missing))
        if wanted_kind:
            if actual_kind is None:
                # No execution evidence this run: the words still count, the
                # kind is simply unknown.
                pass
            elif str(actual_kind) != str(wanted_kind):
                problems.append(f"produced {actual_kind!r}, expected {wanted_kind!r}")
        if not mentions and not wanted_kind:
            outcomes.append(IntentOutcome(ref=ref, satisfied=None, detail="nothing asserted"))
            continue
        outcomes.append(
            IntentOutcome(
                ref=ref,
                satisfied=not problems,
                detail="; ".join(problems),
            )
        )
    return tuple(outcomes)


def score_reconstruction(
    comparison: Comparison,
    *,
    intents: Iterable = (),
    execution: Iterable = (),
    refused: bool = False,
    predicted_refusal: bool = False,
    timed_out: bool = False,
    provider_error: str | None = None,
    harness_error: str | None = None,
) -> Score:
    """Turn a comparison (plus the run's outcomes) into a score and categories."""
    categories: list = []
    notes: list = list(comparison.notes)

    templates = _f1(
        comparison.templates.agreed,
        comparison.templates.expected_total,
        comparison.templates.actual_total,
    )
    topology = _f1(
        comparison.edges.agreed,
        comparison.edges.expected_total,
        comparison.edges.actual_total,
    )
    # Jaccard over the dependency sets: the overlap of what the fixture
    # required and what the reconstruction declared, divided by their union.
    # A fixture that requires nothing and a reconstruction that declares
    # nothing agree perfectly about nothing, which is not a measurement.
    dependency_diff = comparison.dependencies
    dependencies = (
        None if dependency_diff.union == 0 else dependency_diff.agreed / dependency_diff.union
    )
    declared_diff = dependency_diff.differences

    intent_outcomes = tuple(intents)
    measured_intents = [o for o in intent_outcomes if o.satisfied is not None]
    intents_value = (
        sum(1 for o in measured_intents if o.satisfied) / len(measured_intents)
        if measured_intents
        else None
    )

    execution_outcomes = tuple(execution)
    measured_execution = [o for o in execution_outcomes if o.measured]
    execution_value = (
        sum(1 for o in measured_execution if o.passed) / len(measured_execution)
        if measured_execution
        else None
    )

    dimensions = (
        Dimension("templates", templates, WEIGHTS["templates"],
                  f"{comparison.templates.agreed} of {comparison.templates.expected_total} kinds"),
        Dimension("topology", topology, WEIGHTS["topology"],
                  f"{comparison.edges.agreed} of {comparison.edges.expected_total} edges"),
        Dimension("dependencies", dependencies, WEIGHTS["dependencies"],
                  f"{declared_diff} declared-dependency differences"),
        Dimension("intents", intents_value, WEIGHTS["intents"],
                  f"{len(measured_intents)} measurable"),
        Dimension("execution", execution_value, WEIGHTS["execution"],
                  f"{len(measured_execution)} executable nodes measured"),
    )

    measured = [d for d in dimensions if d.measured]
    weight_sum = sum(d.weight for d in measured)
    total = (
        sum(d.value * d.weight for d in measured) / weight_sum if weight_sum else 0.0
    )

    for kind, count in comparison.capability_gaps:
        categories.append(f"capability-gap:{kind}")
        notes.append(f"{count} expected {kind} edge(s) the agent contract cannot express")
    if comparison.fabricated:
        categories.append("fabrication")
    if comparison.unmatched_expected or comparison.templates.missing:
        categories.append("missing-node")
    if comparison.unmatched_actual or comparison.templates.extra:
        categories.append("extra-node")
    if (
        comparison.edges.missing
        or comparison.edges.extra
        or comparison.edges.kind_mismatch
        or comparison.edges.slot_mismatch
    ):
        categories.append("topology")
    if (
        comparison.dependencies.datasets_missing
        or comparison.dependencies.packages_missing
    ):
        categories.append("dependency-unresolved")
    if (
        comparison.dependencies.datasets_extra
        or comparison.dependencies.packages_extra
    ):
        categories.append("dependency-unrequested")
    if any(o.satisfied is False for o in intent_outcomes):
        categories.append("intent-mismatch")
    if any(o.measured and not o.passed for o in execution_outcomes):
        categories.append("execution-failed")
    if refused:
        categories.append("refused")
        if predicted_refusal:
            notes.append("the fixture predicted this refusal, so it is not a failure")
    if timed_out:
        categories.append("timeout")
    if provider_error:
        categories.append("provider-error")
        notes.append(f"provider error: {provider_error}")
    if harness_error:
        categories.append("harness-error")
        notes.append(f"harness error: {harness_error}")

    capped = bool(comparison.fabricated)
    if capped:
        # An invented template, package, dataset, path or URL is never partial
        # credit: the reconstruction refers to something that does not exist.
        total = 0.0
        notes.append(
            "score capped at 0: invented "
            + ", ".join(f"{kind} {literal!r}" for kind, literal in comparison.fabricated)
        )

    if not categories:
        categories.append("pass")

    return Score(
        dimensions=dimensions,
        total=total,
        categories=tuple(dict.fromkeys(categories)),
        capped_by_fabrication=capped,
        notes=tuple(notes),
    )
