"""dev/121 — the comparator, the scorer and the report.

These tests decide what the harness will call right and wrong, so each one
states a judgement in the terms the brief used: an equivalent reordered graph
passes; a missing node, wrong topology, unresolved dependency or fabricated
resource fails, and fails for the stated reason; a construct the contract
cannot express is a capability failure rather than a lowered bar.

Offline: values in, values out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.evaluation.canonical import (
    CanonicalGraph,
    CEdge,
    CNode,
    Sources,
    canonical_graph_from_spec,
)
from utk_curio.backend.app.agents.evaluation.compare import Universe, compare_graphs
from utk_curio.backend.app.agents.evaluation.report import (
    AttemptRecord,
    Digests,
    ProviderRecord,
    RunReport,
    digest_of,
    scrub,
)
from utk_curio.backend.app.agents.evaluation.scoring import (
    WEIGHTS,
    ExecutionOutcome,
    IntentOutcome,
    evaluate_intents,
    score_reconstruction,
)
from utk_curio.backend.tests.test_agents.test_reconstruction_canonical import TEMPLATES

REPO_ROOT = Path(__file__).resolve().parents[4]

LOADER = "curio.builtin/data-loading"
TRANSFORM = "curio.builtin/data-transformation"
VEGA = "curio.builtin/vis-vega"
POOL = "curio.builtin/data-pool"
MERGE = "curio.builtin/merge-flow"

UNIVERSE = Universe(
    templates=frozenset(TEMPLATES),
    dataset_ids=frozenset({"data.x.y", "data.projectsidewalk.chicago-labels"}),
    package_dir_names=frozenset({"curio.weather@1", "curio.streetvision@1"}),
)


def _spec(nodes, edges, **rest):
    return {"dataflow": {"nodes": nodes, "edges": edges, **rest}}


def _node(node_id, node_type, content="return 1", **extra):
    return {"id": node_id, "type": node_type, "content": content, **extra}


def _edge(source, target, **extra):
    return {"id": f"e-{source}-{target}", "source": source, "target": target, **extra}


def _graph(spec, sources=None):
    return canonical_graph_from_spec(spec, templates=TEMPLATES, sources=sources)


CHAIN = _spec(
    [_node("l", LOADER), _node("t", TRANSFORM), _node("v", VEGA, content="{}")],
    [_edge("l", "t"), _edge("t", "v")],
)


class TestEquivalentGraphsPass:
    def test_the_same_graph_compares_exactly(self):
        comparison = compare_graphs(_graph(CHAIN), _graph(CHAIN), universe=UNIVERSE)
        assert comparison.exact
        score = score_reconstruction(comparison)
        assert score.total == 1.0
        assert score.categories == ("pass",)

    def test_a_reordered_graph_with_new_ids_compares_exactly(self):
        rebuilt = _spec(
            [
                _node("uuid-9", VEGA, content="{\"mark\": \"bar\"}", x=880, y=12),
                _node("uuid-3", TRANSFORM, content="df = arg\nreturn df", x=440),
                _node("uuid-1", LOADER, content="import pandas\nreturn pandas.DataFrame()"),
            ],
            [_edge("uuid-3", "uuid-9"), _edge("uuid-1", "uuid-3")],
        )
        comparison = compare_graphs(_graph(CHAIN), _graph(rebuilt), universe=UNIVERSE)
        assert comparison.exact, comparison
        assert score_reconstruction(comparison).total == 1.0

    def test_a_symmetric_fan_out_built_in_either_order_passes(self):
        expected = _spec(
            [_node("l", LOADER), _node("a", TRANSFORM), _node("b", TRANSFORM)],
            [_edge("l", "a"), _edge("l", "b")],
        )
        built = _spec(
            [_node("x", LOADER), _node("y", TRANSFORM), _node("z", TRANSFORM)],
            [_edge("x", "z"), _edge("x", "y")],
        )
        comparison = compare_graphs(_graph(expected), _graph(built), universe=UNIVERSE)
        assert comparison.exact
        assert score_reconstruction(comparison).total == 1.0

    def test_asymmetric_branches_are_paired_by_structure_not_by_position(self):
        """The pairing must survive the two branches being built in the other
        order: refinement separates the transform that feeds two charts from
        the one that feeds one, whichever index it landed on."""
        expected = _spec(
            [
                _node("l", LOADER), _node("t1", TRANSFORM), _node("t2", TRANSFORM),
                _node("v1", VEGA, content="{}"), _node("v2", VEGA, content="{}"),
                _node("v3", VEGA, content="{}"),
            ],
            [
                _edge("l", "t1"), _edge("l", "t2"), _edge("t1", "v1"),
                _edge("t1", "v2"), _edge("t2", "v3"),
            ],
        )
        built = _spec(
            [
                _node("A", LOADER), _node("B", TRANSFORM), _node("C", TRANSFORM),
                _node("D", VEGA, content="{}"), _node("E", VEGA, content="{}"),
                _node("F", VEGA, content="{}"),
            ],
            [
                _edge("A", "C"), _edge("A", "B"), _edge("C", "D"),
                _edge("C", "E"), _edge("B", "F"),
            ],
        )
        comparison = compare_graphs(_graph(expected), _graph(built), universe=UNIVERSE)
        assert comparison.exact, comparison


class TestWrongGraphsFail:
    def test_a_missing_node_is_a_missing_node(self):
        short = _spec([_node("l", LOADER), _node("t", TRANSFORM)], [_edge("l", "t")])
        comparison = compare_graphs(_graph(CHAIN), _graph(short), universe=UNIVERSE)
        assert not comparison.exact
        assert comparison.templates.missing == ((VEGA, 1),)
        score = score_reconstruction(comparison)
        assert "missing-node" in score.categories
        assert score.total < 1.0

    def test_an_extra_node_nobody_asked_for_is_reported(self):
        longer = _spec(
            [_node("l", LOADER), _node("t", TRANSFORM), _node("v", VEGA, content="{}"),
             _node("x", TRANSFORM)],
            [_edge("l", "t"), _edge("t", "v"), _edge("v", "x")],
        )
        comparison = compare_graphs(_graph(CHAIN), _graph(longer), universe=UNIVERSE)
        assert comparison.templates.extra == ((TRANSFORM, 1),)
        assert "extra-node" in score_reconstruction(comparison).categories

    def test_a_wrong_template_is_both_missing_and_extra(self):
        wrong = _spec(
            [_node("l", LOADER), _node("t", "curio.builtin/computation-analysis"),
             _node("v", VEGA, content="{}")],
            [_edge("l", "t"), _edge("t", "v")],
        )
        comparison = compare_graphs(_graph(CHAIN), _graph(wrong), universe=UNIVERSE)
        assert comparison.templates.missing == ((TRANSFORM, 1),)
        assert comparison.templates.extra == (("curio.builtin/computation-analysis", 1),)

    def test_wrong_topology_with_the_right_nodes_fails_on_topology(self):
        rewired = _spec(
            [_node("l", LOADER), _node("t", TRANSFORM), _node("v", VEGA, content="{}")],
            [_edge("l", "t"), _edge("l", "v")],
        )
        comparison = compare_graphs(_graph(CHAIN), _graph(rewired), universe=UNIVERSE)
        assert comparison.templates.missing == () and comparison.templates.extra == ()
        assert comparison.edges.missing or comparison.edges.extra
        score = score_reconstruction(comparison)
        assert "topology" in score.categories
        assert score.dimension("templates").value == 1.0
        assert score.dimension("topology").value < 1.0

    def test_a_disconnected_graph_scores_zero_topology(self):
        loose = _spec(
            [_node("l", LOADER), _node("t", TRANSFORM), _node("v", VEGA, content="{}")], []
        )
        comparison = compare_graphs(_graph(CHAIN), _graph(loose), universe=UNIVERSE)
        assert score_reconstruction(comparison).dimension("topology").value == 0.0

    def test_a_swapped_merge_slot_is_reported_only_when_order_matters(self):
        expected = _spec(
            [_node("a", LOADER), _node("b", TRANSFORM), _node("m", MERGE, content="")],
            [_edge("a", "m", targetHandle="in_0"), _edge("b", "m", targetHandle="in_1")],
        )
        swapped = _spec(
            [_node("a", LOADER), _node("b", TRANSFORM), _node("m", MERGE, content="")],
            [_edge("a", "m", targetHandle="in_1"), _edge("b", "m", targetHandle="in_0")],
        )
        expected_graph = _graph(expected)
        refs = expected_graph.default_refs()
        indifferent = compare_graphs(expected_graph, _graph(swapped), universe=UNIVERSE,
                                     expected_refs=refs)
        assert not indifferent.edges.slot_mismatch
        merge_ref = refs[[n.type for n in expected_graph.nodes].index(MERGE)]
        sensitive = compare_graphs(
            expected_graph, _graph(swapped), universe=UNIVERSE,
            expected_refs=refs, slot_sensitive_refs=[merge_ref],
        )
        assert sensitive.edges.slot_mismatch
        assert "topology" in score_reconstruction(sensitive).categories


class TestFabrication:
    def test_an_invented_template_caps_the_score_at_zero(self):
        invented = _spec(
            [_node("l", LOADER), _node("t", "someone.invented/magic"),
             _node("v", VEGA, content="{}")],
            [_edge("l", "t"), _edge("t", "v")],
        )
        comparison = compare_graphs(_graph(CHAIN), _graph(invented), universe=UNIVERSE)
        assert ("template", "someone.invented/magic") in comparison.fabricated
        score = score_reconstruction(comparison)
        assert score.total == 0.0
        assert score.capped_by_fabrication
        assert "fabrication" in score.categories

    def test_an_invented_dataset_id_caps_the_score(self):
        built = _graph(CHAIN, sources=Sources(dataset_ids=("data.invented.nowhere",)))
        comparison = compare_graphs(_graph(CHAIN), built, universe=UNIVERSE)
        assert ("dataset", "data.invented.nowhere") in comparison.fabricated
        assert score_reconstruction(comparison).total == 0.0

    def test_an_invented_package_caps_the_score(self):
        spec = _spec([_node("l", LOADER)], [], packages=["curio.invented@1"])
        comparison = compare_graphs(_graph(_spec([_node("l", LOADER)], [])), _graph(spec),
                                    universe=UNIVERSE)
        assert ("package", "curio.invented@1") in comparison.fabricated

    def test_a_path_nobody_named_is_fabricated_but_a_required_one_is_not(self):
        built = _graph(CHAIN, sources=Sources(paths=("data/guessed.csv",)))
        comparison = compare_graphs(_graph(CHAIN), built, universe=UNIVERSE)
        assert ("path", "data/guessed.csv") in comparison.fabricated
        allowed = compare_graphs(
            _graph(CHAIN), built, universe=UNIVERSE, required_paths=["data/guessed.csv"]
        )
        assert not allowed.fabricated

    def test_an_unlisted_url_is_fabricated_and_the_vega_schema_is_not(self):
        vega = _graph(CHAIN, sources=Sources(urls=("https://vega.github.io/schema/v6.json",)))
        assert not compare_graphs(_graph(CHAIN), vega, universe=UNIVERSE).fabricated
        elsewhere = _graph(CHAIN, sources=Sources(urls=("https://data.example/api.json",)))
        comparison = compare_graphs(_graph(CHAIN), elsewhere, universe=UNIVERSE)
        assert ("url", "https://data.example/api.json") in comparison.fabricated


class TestDependencies:
    def test_an_unresolved_dependency_fails(self):
        comparison = compare_graphs(
            _graph(CHAIN), _graph(CHAIN), universe=UNIVERSE,
            required_datasets=["data.x.y"],
        )
        assert comparison.dependencies.datasets_missing == ("data.x.y",)
        score = score_reconstruction(comparison)
        assert "dependency-unresolved" in score.categories
        assert score.dimension("dependencies").value == 0.0

    def test_a_declared_dependency_that_was_asked_for_scores_one(self):
        built = _spec(
            [_node("l", LOADER, content='p = curio_dataset_path("data.x.y")')],
            [],
            datasets=[{"datasetId": "data.x.y"}],
        )
        comparison = compare_graphs(
            _graph(_spec([_node("l", LOADER)], [])), _graph(built),
            universe=UNIVERSE, required_datasets=["data.x.y"],
        )
        assert comparison.dependencies.datasets_missing == ()
        assert score_reconstruction(comparison).dimension("dependencies").value == 1.0

    def test_a_dependency_nobody_asked_for_is_its_own_category(self):
        built = _spec([_node("l", LOADER)], [], packages=["curio.weather@1"])
        comparison = compare_graphs(
            _graph(_spec([_node("l", LOADER)], [])), _graph(built), universe=UNIVERSE
        )
        assert comparison.dependencies.packages_extra == ("curio.weather@1",)
        assert "dependency-unrequested" in score_reconstruction(comparison).categories


class TestCapabilityGaps:
    """The brief's rule: an unsupported construct is an explicit capability
    failure, and the expected workflow is never weakened to make it pass."""

    EXPECTED = _spec(
        [_node("p", POOL, content=""), _node("v", VEGA, content="{}")],
        [_edge("p", "v"), _edge("p", "v", type="Interaction")],
    )

    def test_an_unexpressible_edge_is_a_capability_gap_not_a_topology_error(self):
        built = _spec(
            [_node("p", POOL, content=""), _node("v", VEGA, content="{}")],
            [_edge("p", "v")],
        )
        comparison = compare_graphs(
            _graph(self.EXPECTED), _graph(built), universe=UNIVERSE,
            unexpressible_kinds=["interaction"],
        )
        assert comparison.capability_gaps == (("interaction-edge", 1),)
        assert comparison.edges.missing == ()
        score = score_reconstruction(comparison)
        assert "capability-gap:interaction-edge" in score.categories
        assert "topology" not in score.categories
        # The data half still scored, and it scored perfectly.
        assert score.dimension("topology").value == 1.0

    def test_without_the_declared_gap_the_same_run_is_a_topology_failure(self):
        built = _spec(
            [_node("p", POOL, content=""), _node("v", VEGA, content="{}")],
            [_edge("p", "v")],
        )
        comparison = compare_graphs(
            _graph(self.EXPECTED), _graph(built), universe=UNIVERSE
        )
        assert comparison.capability_gaps == ()
        assert comparison.edges.missing
        assert "topology" in score_reconstruction(comparison).categories

    def test_the_expected_graph_still_carries_the_edge(self):
        assert len(_graph(self.EXPECTED).interaction_edges()) == 1


class TestIntents:
    def test_a_node_whose_words_match_satisfies_its_intent(self):
        outcomes = evaluate_intents(
            [{"ref": "transform1", "mustMention": ["agreement", "severity"]}],
            texts={"transform1": "Derive the agreement ratio and a severity tier"},
        )
        assert outcomes[0].satisfied is True

    def test_a_node_whose_words_miss_fails_with_the_missing_words_named(self):
        outcomes = evaluate_intents(
            [{"ref": "transform1", "mustMention": ["agreement", "severity"]}],
            texts={"transform1": "Clean the table"},
        )
        assert outcomes[0].satisfied is False
        assert "agreement" in outcomes[0].detail and "severity" in outcomes[0].detail
        assert "intent-mismatch" in score_reconstruction(
            compare_graphs(_graph(CHAIN), _graph(CHAIN), universe=UNIVERSE),
            intents=outcomes,
        ).categories

    def test_an_unbuilt_node_is_not_measurable_rather_than_failed(self):
        outcomes = evaluate_intents(
            [{"ref": "loader1", "mustMention": ["roads"]}], texts={}
        )
        assert outcomes[0].satisfied is None
        score = score_reconstruction(
            compare_graphs(_graph(CHAIN), _graph(CHAIN), universe=UNIVERSE), intents=outcomes
        )
        assert score.dimension("intents").value is None
        assert "intent-mismatch" not in score.categories

    def test_a_wrong_output_kind_fails_but_an_unknown_one_does_not(self):
        wrong = evaluate_intents(
            [{"ref": "loader1", "outputKind": "geodataframe"}],
            texts={"loader1": "Load the polygons"},
            output_kinds={"loader1": "dataframe"},
        )
        assert wrong[0].satisfied is False
        unknown = evaluate_intents(
            [{"ref": "loader1", "outputKind": "geodataframe"}],
            texts={"loader1": "Load the polygons"},
        )
        assert unknown[0].satisfied is True


class TestExecutionDimension:
    def test_verified_nodes_score_and_not_executable_ones_are_excluded(self):
        comparison = compare_graphs(_graph(CHAIN), _graph(CHAIN), universe=UNIVERSE)
        score = score_reconstruction(
            comparison,
            execution=[
                ExecutionOutcome("a", "verified"),
                ExecutionOutcome("b", "verified"),
                ExecutionOutcome("c", "not-executable", executable=False),
            ],
        )
        assert score.dimension("execution").value == 1.0
        assert "execution-failed" not in score.categories

    def test_a_failed_node_lowers_the_dimension_and_names_the_category(self):
        score = score_reconstruction(
            compare_graphs(_graph(CHAIN), _graph(CHAIN), universe=UNIVERSE),
            execution=[ExecutionOutcome("a", "verified"), ExecutionOutcome("b", "failed")],
        )
        assert score.dimension("execution").value == 0.5
        assert "execution-failed" in score.categories

    def test_a_sandbox_outage_is_not_measured_and_not_a_failure(self):
        """dev/115 (DEC-073): a node left pending because the sandbox was
        unreachable is not a content failure, so it cannot be a score failure."""
        score = score_reconstruction(
            compare_graphs(_graph(CHAIN), _graph(CHAIN), universe=UNIVERSE),
            execution=[ExecutionOutcome("a", "pending")],
        )
        assert score.dimension("execution").value is None
        assert "execution-failed" not in score.categories
        assert score.total == 1.0

    def test_a_timeout_is_its_own_category(self):
        score = score_reconstruction(
            compare_graphs(_graph(CHAIN), _graph(CHAIN), universe=UNIVERSE), timed_out=True
        )
        assert "timeout" in score.categories


class TestRefusalsAndErrors:
    def test_a_refusal_is_reported_and_a_predicted_one_is_explained(self):
        """dev/94 (DEC-063): a schema-recognised decline is a run that produced
        an answer. It is reported, and where the fixture predicted it the score
        says so instead of calling it a failure."""
        comparison = compare_graphs(_graph(CHAIN), CanonicalGraph(), universe=UNIVERSE)
        score = score_reconstruction(comparison, refused=True, predicted_refusal=True)
        assert "refused" in score.categories
        assert any("predicted this refusal" in note for note in score.notes)

    def test_a_provider_error_and_a_harness_error_are_distinguishable(self):
        comparison = compare_graphs(_graph(CHAIN), _graph(CHAIN), universe=UNIVERSE)
        assert "provider-error" in score_reconstruction(
            comparison, provider_error="502 from the endpoint"
        ).categories
        assert "harness-error" in score_reconstruction(
            comparison, harness_error="KeyError in the driver"
        ).categories


class TestWeightsAndThresholds:
    def test_the_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)

    def test_the_weights_live_in_the_harness_not_in_a_fixture(self):
        fixture_path = (
            REPO_ROOT / "docs/examples/prompts/01-vega-lite-chained-transforms.prompt.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert "weights" not in fixture
        assert set(fixture["thresholds"]) <= {"pass", *WEIGHTS}

    def test_an_unmeasured_dimension_cannot_fail_its_threshold(self):
        score = score_reconstruction(
            compare_graphs(_graph(CHAIN), _graph(CHAIN), universe=UNIVERSE)
        )
        assert score.dimension("execution").value is None
        assert score.meets({"pass": 1.0, "execution": 1.0})

    def test_a_measured_dimension_below_its_threshold_fails(self):
        rewired = _spec(
            [_node("l", LOADER), _node("t", TRANSFORM), _node("v", VEGA, content="{}")],
            [_edge("l", "t"), _edge("l", "v")],
        )
        score = score_reconstruction(
            compare_graphs(_graph(CHAIN), _graph(rewired), universe=UNIVERSE)
        )
        assert not score.meets({"pass": 0.0, "topology": 1.0})


class TestReport:
    def _attempt(self, fixture_id="01", categories=("pass",), total=1.0):
        comparison = compare_graphs(_graph(CHAIN), _graph(CHAIN), universe=UNIVERSE)
        score = score_reconstruction(comparison)
        return AttemptRecord(
            fixture_id=fixture_id,
            tier="T0",
            latency_ms=1234,
            usage={"inputTokens": 100, "outputTokens": 50},
            digests=Digests(fixture_sha256="a" * 64, prompt_sha256="b" * 64),
            score=score,
            comparison={"edges": {"agreed": comparison.edges.agreed}},
            transcript=[{"role": "user", "content": "build me a dataflow"}],
            review_status="pending-owner-review",
        )

    def test_the_report_records_what_a_score_needs_to_be_trusted(self):
        report = RunReport(
            run_id="eval-test",
            mode="live",
            provider=ProviderRecord(api_type="openai_compatible", base_url_host="localhost",
                                    model="gemma-4"),
        )
        report.add(self._attempt())
        payload = report.as_dict()
        assert payload["kind"] == "evaluation-report"
        assert payload["isReleaseGate"] is False
        assert payload["provider"]["model"] == "gemma-4"
        assert payload["attempts"][0]["digests"]["promptSha256"]
        assert payload["attempts"][0]["usage"] == {"inputTokens": 100, "outputTokens": 50}
        assert payload["unreviewedPrompts"] == 1

    def test_no_cost_is_invented_and_an_operator_rate_is_labelled(self):
        report = RunReport(run_id="eval-test")
        report.add(self._attempt())
        assert report.cost() is None
        assert "no price table" in report.as_markdown()
        priced = RunReport(run_id="eval-priced", price_per_mtoken=(1.0, 2.0))
        priced.add(self._attempt())
        cost = priced.cost()
        assert cost["operatorSupplied"] is True
        assert cost["estimatedUsd"] == pytest.approx(100 / 1e6 + 2 * 50 / 1e6)

    def test_the_markdown_says_it_is_not_a_gate_and_lists_categories(self):
        report = RunReport(run_id="eval-test")
        report.add(self._attempt())
        markdown = report.as_markdown()
        assert "not a release gate" in markdown
        assert "| `pass` | 1 |" in markdown
        assert "not yet owner-approved" in markdown

    def test_a_report_is_written_as_json_and_markdown(self, tmp_path):
        report = RunReport(run_id="eval-written")
        report.add(self._attempt())
        json_path, markdown_path = report.write(tmp_path)
        assert json.loads(json_path.read_text())["runId"] == "eval-written"
        assert markdown_path.read_text().startswith("# Agent reconstruction evaluation")

    def test_the_histogram_counts_every_category_across_attempts(self):
        report = RunReport(run_id="eval-hist")
        first = self._attempt("01")
        second = self._attempt("02")
        second.score = score_reconstruction(
            compare_graphs(
                _graph(CHAIN),
                _graph(_spec([_node("l", LOADER)], [])),
                universe=UNIVERSE,
            )
        )
        report.add(first)
        report.add(second)
        histogram = report.category_histogram()
        assert histogram["pass"] == 1
        assert histogram["missing-node"] == 1

    def test_nothing_secret_reaches_the_report(self):
        record = self._attempt()
        record.transcript = [
            {"role": "assistant",
             "content": 'headers = {"Authorization": "Bearer sk-livekey1234567890abcdef"}'},
        ]
        record.error = 'api_key = "sk-anotherlongsecretvalue123456"'
        payload = record.as_dict()
        blob = json.dumps(payload)
        assert "sk-livekey1234567890abcdef" not in blob
        assert "sk-anotherlongsecretvalue123456" not in blob
        assert "redacted" in blob

    def test_a_known_secret_value_is_redacted_by_name(self):
        assert "hunter2000000000" not in str(
            scrub("the key is hunter2000000000", values={"census": "hunter2000000000"})
        )

    def test_the_roster_digest_is_order_independent(self):
        assert digest_of(["b", "a"]) == digest_of(["a", "b"])
        assert digest_of(["a"]) != digest_of(["a", "b"])
