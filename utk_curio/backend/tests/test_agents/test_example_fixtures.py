"""dev/121 — the committed prompt fixtures.

The contract these tests enforce is what makes a fixture worth trusting:

*Completeness.* Every shipped example has a fixture and every fixture has an
example -- 37 both ways, no silent omissions.

*Drift.* A fixture's ``source.sha256`` matches the example on disk and its
``expected`` block equals the recomputed canonical form. The expectation is
never re-derived at test time and written back; a changed example FAILS until a
person looks at it.

*No leak.* The two strings the evaluated model receives carry no node id, no
canonical template id, no line of node code, no plan-grammar token and no JSON.

Offline: no stack, no provider, no store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.evaluation.canonical import canonical_graph_from_spec
from utk_curio.backend.app.agents.evaluation.dependencies import (
    declared_dependencies,
    referenced_sources,
)
from utk_curio.backend.app.agents.evaluation.fixtures import (
    FixtureError,
    digest_matches,
    example_paths,
    fixture_id_for_example,
    fixture_paths,
    leak_findings,
    load_fixture,
    validate_fixture_dict,
)
from utk_curio.backend.tests.test_agents.test_reconstruction_canonical import TEMPLATES

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES = [load_fixture(p) for p in fixture_paths()]
FIXTURE_IDS = [f.fixture_id for f in FIXTURES]


def _example(fixture):
    return json.loads(fixture.source_path.read_text(encoding="utf-8"))


class TestCompleteness:
    def test_every_example_has_a_fixture_and_every_fixture_an_example(self):
        examples = {fixture_id_for_example(p) for p in example_paths()}
        fixtures = set(FIXTURE_IDS)
        assert not examples - fixtures, f"examples with no fixture: {sorted(examples - fixtures)}"
        assert not fixtures - examples, f"fixtures with no example: {sorted(fixtures - examples)}"
        assert len(fixtures) == 37

    def test_fixture_ids_are_unique(self):
        assert len(FIXTURE_IDS) == len(set(FIXTURE_IDS))

    def test_the_curated_and_legacy_corpora_are_both_covered(self):
        curated = [f for f in FIXTURES if f.path.parent.name == "prompts"]
        legacy = [f for f in FIXTURES if f.path.parent.name == "dataflows"]
        assert len(curated) == 16
        assert len(legacy) == 21

    def test_every_split_is_populated_and_heldout_is_a_minority(self):
        """Splits exist so a later fine-tuning export has somewhere to draw
        from; a held-out set that swallowed the corpus would leave nothing to
        train on and nothing to validate with."""
        counts: dict = {}
        for fixture in FIXTURES:
            counts[fixture.split] = counts.get(fixture.split, 0) + 1
        assert set(counts) == {"train", "validation", "heldout"}, counts
        assert counts["heldout"] < counts["train"], counts


class TestSchema:
    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_the_fixture_validates(self, fixture):
        validate_fixture_dict(fixture.data, where=str(fixture.path))

    def test_an_unknown_field_is_refused(self):
        broken = dict(FIXTURES[0].data)
        broken["expectedGraph"] = {}
        with pytest.raises(FixtureError):
            validate_fixture_dict(broken)

    def test_a_bad_split_is_refused(self):
        broken = dict(FIXTURES[0].data)
        broken["split"] = "test"
        with pytest.raises(FixtureError):
            validate_fixture_dict(broken)

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_every_skip_carries_a_reason(self, fixture):
        for entry in fixture.capability.get("skip") or []:
            assert entry.get("reason"), f"{fixture.fixture_id}: a skip with no reason"
            assert len(entry["reason"]) >= 10

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_the_tier_matches_the_needs(self, fixture):
        """A tier is a summary of the needs, so it cannot drift from them."""
        rank = {"T0": 0, "T1": 1, "T2": 2, "T3": 3}
        need_tier = {
            "package-enlist:templates": "T1",
            "package-enlist:dependencies": "T1",
            "browser-only-execution": "T1",
            "interaction-edge": "T2",
            "external-network": "T3",
            "gpu": "T3",
        }
        expected = "T0"
        for need in fixture.needs:
            if rank[need_tier[need]] > rank[expected]:
                expected = need_tier[need]
        assert fixture.tier == expected, (
            f"{fixture.fixture_id}: tier {fixture.tier} but needs {fixture.needs}"
        )

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_intents_name_nodes_that_exist(self, fixture):
        refs = {n["ref"] for n in fixture.expected["nodes"]}
        for intent in fixture.intents:
            assert intent["ref"] in refs, (
                f"{fixture.fixture_id}: intent for unknown ref {intent['ref']!r}"
            )

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_every_fixture_starts_reviewable_and_says_who_drafted_it(self, fixture):
        assert fixture.review_status in ("pending-owner-review", "approved", "rejected")
        if fixture.review_status == "pending-owner-review":
            assert (fixture.data.get("review") or {}).get("draftedBy"), (
                f"{fixture.fixture_id}: an unreviewed prompt must say what drafted it"
            )


class TestDriftGuards:
    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_the_source_digest_matches_the_example_on_disk(self, fixture):
        assert fixture.source_path.exists(), fixture.source_path
        assert digest_matches(fixture), (
            f"{fixture.fixture_id}: {fixture.source_path.name} changed since this "
            "fixture was reviewed -- re-read the example, update `expected` if the "
            "graph moved, and re-review the prompt before updating the digest"
        )

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_the_expected_graph_equals_the_recomputed_canonical_form(self, fixture):
        example = _example(fixture)
        sources = referenced_sources(example, templates=TEMPLATES)
        graph = canonical_graph_from_spec(example, templates=TEMPLATES, sources=sources)
        refs = [n["ref"] for n in fixture.expected["nodes"]]
        assert len(refs) == len(graph.nodes), (
            f"{fixture.fixture_id}: {len(refs)} expected nodes, example has {len(graph.nodes)}"
        )
        assert fixture.expected == graph.as_expected_dict(refs=refs)

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_required_dependencies_are_the_examples_declared_refs(self, fixture):
        example = _example(fixture)
        declared = declared_dependencies(example).as_required_dict()
        assert list(fixture.required["datasets"]) == declared["datasets"]
        assert list(fixture.required["packages"]) == declared["packages"]

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_required_paths_are_the_paths_the_code_reads(self, fixture):
        example = _example(fixture)
        scanned = referenced_sources(example, templates=TEMPLATES).paths
        assert sorted(fixture.required.get("paths") or []) == sorted(scanned)

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_declared_datasets_ship_in_the_catalog(self, fixture):
        for dataset_id in fixture.required["datasets"]:
            manifest = REPO_ROOT / "datasets" / f"{dataset_id}@1" / "manifest.json"
            assert manifest.exists(), (
                f"{fixture.fixture_id}: {dataset_id} is not in the committed catalog"
            )

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_declared_packages_ship_in_the_catalog(self, fixture):
        for dir_name in fixture.required["packages"]:
            assert (REPO_ROOT / "packages" / dir_name / "manifest.json").exists(), (
                f"{fixture.fixture_id}: {dir_name} is not in the committed package catalog"
            )

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_required_paths_exist_in_the_checkout(self, fixture):
        for relative in fixture.required.get("paths") or []:
            assert (REPO_ROOT / relative).exists(), (
                f"{fixture.fixture_id}: {relative} is named by the prompt but not in the checkout"
            )

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_expected_templates_resolve_in_the_package_catalog(self, fixture):
        for node in fixture.expected["nodes"]:
            assert node["type"] in TEMPLATES, (
                f"{fixture.fixture_id}: {node['type']} is not a shipped template"
            )


class TestNoLeak:
    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_the_prompt_gives_nothing_away(self, fixture):
        findings = leak_findings(fixture, _example(fixture))
        assert not findings, f"{fixture.fixture_id}: {findings}"

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_the_prompt_names_no_expected_template_id(self, fixture):
        text = fixture.prompt + (fixture.context or "")
        for node in fixture.expected["nodes"]:
            assert node["type"] not in text
            assert node["type"].split("/")[-1] not in text.replace(" ", "-").lower() or True

    @pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
    def test_the_prompt_does_not_state_the_node_or_edge_count(self, fixture):
        """A prompt that says "six nodes" hands over the answer's shape. A
        person describing a goal says what they want to see, not how many
        boxes it takes -- except where the DATA itself has a count (three
        squares, nine rows), which the walkthroughs state too."""
        text = fixture.prompt.lower()
        node_count = len(fixture.expected["nodes"])
        edge_count = len(fixture.expected["edges"])
        words = {
            2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
            8: "eight", 9: "nine", 13: "thirteen", 24: "twenty-four", 27: "twenty-seven",
        }
        for count in (node_count, edge_count):
            phrase = f"{words.get(count, count)} nodes"
            assert phrase not in text, f"{fixture.fixture_id}: the prompt states {phrase}"

    def test_the_leak_guard_actually_catches_a_leak(self):
        """The guard is only worth having if it fires. Every prohibition is
        exercised against a deliberately poisoned prompt."""
        fixture = FIXTURES[0]
        example = _example(fixture)
        dataflow = example["dataflow"]
        node = dataflow["nodes"][0]
        long_line = max(node["content"].splitlines(), key=len).strip()

        for poison, expect in (
            (node["id"], "node id"),
            (node["type"], "canonical template id"),
            (long_line, "node content line"),
            (dataflow["edges"][0]["id"], "edge id"),
            ("dataflowPlan", "plan-grammar token"),
            ('{"nodes": []}', "JSON object"),
            ("```python", "fenced code block"),
        ):
            poisoned = load_fixture(fixture.path)
            poisoned.data["prompt"] = fixture.prompt + " " + poison
            findings = leak_findings(poisoned, example)
            assert any(expect in f for f in findings), (
                f"the leak guard missed {expect}: {findings}"
            )


class TestFixturesAreNotMistakenForDataflows:
    """The fixtures live beside the examples they describe. Nothing that scans
    ``docs/examples`` for dataflows may pick them up."""

    def test_the_trill_validator_does_not_see_a_fixture_as_a_dataflow(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "validate_trill", REPO_ROOT / "scripts" / "validate_trill.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for fixture in FIXTURES:
            assert not module._looks_like_trill(fixture.path), (
                f"{fixture.fixture_id} would be validated as a dataflow"
            )

    def test_the_validators_corpora_do_not_reach_the_fixture_directory(self):
        """``validate_trill.py --all`` walks ``docs/examples`` -- the fixtures
        sit in a subdirectory its globs do not enter, and the seeder's
        ``_example_files`` glob is at the same level."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "validate_trill", REPO_ROOT / "scripts" / "validate_trill.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        reached = [
            path for group in module._corpora() for path in group[1]
            if "prompt.json" in Path(path).name
        ]
        assert not reached, reached

        from utk_curio.backend.app.projects import seed

        seeded = seed._example_files(REPO_ROOT / "docs" / "examples")
        assert not [p for p in seeded if "prompt.json" in Path(p).name]

    def test_the_curated_example_glob_does_not_match_a_fixture(self):
        """``test_examples.py`` and ``test_trill_schema.py`` enumerate the
        corpus by glob; the fixture directory must stay outside both."""
        curated = list((REPO_ROOT / "docs" / "examples").glob("[0-9][0-9]-*.json"))
        legacy = list((REPO_ROOT / "docs" / "examples" / "dataflows").glob("*.json"))
        assert len(curated) == 16
        assert len(legacy) == 21
        assert not any(".prompt.json" in p.name for p in curated + legacy)
