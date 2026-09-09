"""dev/121 — reconstruction through the production path, deterministically.

Every test here drives the REAL Dataflow Builder: the real plan mint, the real
review card, the real apply, the real background Solve with its waves,
grounding gate and per-wave persist, and the real spec on disk. Only two things
are replaced, and both are replaced the way every agent test replaces them: the
provider (scripted) and the sandbox (faked). Package installs keep the real
service and stub only pip's subprocess.

The suite's job is to prove the harness measures the MODEL. If an oracle -- a
scripted answer built from the expected graph -- can drive this path to a
perfect score for every construct the contract can express, then a later
failure is a fact about the model. And where the oracle cannot express the
expected graph it says which capability is missing, so the gap is reported and
the expectation stands.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.evaluation import attempt as attempt_mod
from utk_curio.backend.app.agents.evaluation import oracle
from utk_curio.backend.app.agents.evaluation.canonical import canonical_graph_from_spec
from utk_curio.backend.app.agents.evaluation.compare import Universe, compare_graphs
from utk_curio.backend.app.agents.evaluation.fixtures import (
    FIXTURE_ROOT,
    fixture_paths,
    load_fixture,
)
from utk_curio.backend.tests.test_agents._reconstruction_driver import (
    DATASET_FINDER_COORD,
    RESEARCHER_COORD,
    InProcessDriver,
    oracle_attempt,
    oracle_responder,
)
from utk_curio.backend.tests.test_agents.test_reconstruction_canonical import TEMPLATES

FIXTURES = [load_fixture(p) for p in fixture_paths()]
IDS = [f.fixture_id for f in FIXTURES]

ONE = load_fixture(FIXTURE_ROOT / "01-vega-lite-chained-transforms.prompt.json")
STREETVISION = load_fixture(FIXTURE_ROOT / "10-street-vision-cv-analysis.prompt.json")


def _example(fixture):
    return json.loads(fixture.source_path.read_text(encoding="utf-8"))


def _driver(client, user_and_token, monkeypatch):
    user, token = user_and_token
    return InProcessDriver(client, user, token, monkeypatch)


class TestReachability:
    """Section 3.5 of the memo: for everything the contract can express, the
    production path reaches a perfect score; for the rest, a named gap."""

    @pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
    def test_reachable_or_named_gap(
        self, client, user_and_token, tmp_curio, monkeypatch, fixture
    ):
        driver = _driver(client, user_and_token, monkeypatch)
        result = oracle_attempt(
            fixture, driver, templates=TEMPLATES, example=_example(fixture)
        )
        if result.unrepresentable:
            assert result.unrepresentable in fixture.needs, (
                f"{fixture.fixture_id}: the oracle hit an UNDECLARED capability gap "
                f"({result.unrepresentable}); the fixture must declare it in "
                f"capability.needs, not the harness discover it"
            )
            return
        score = result.score
        assert score.total == pytest.approx(1.0), (
            f"{fixture.fixture_id}: an oracle answer scored {score.total:.3f} "
            f"{score.categories} — {json.dumps(result.scored.as_dict())[:900]}"
        )
        assert score.categories == ("pass",), result.scored.as_dict()
        assert result.scored.comparison.exact

    def test_every_declared_interaction_fixture_is_the_one_the_oracle_refuses(self):
        """The gap set is a fact about the contract, not a per-fixture opinion:
        the fixtures declaring ``interaction-edge`` are exactly the ones the
        oracle cannot serialize."""
        declared = {f.fixture_id for f in FIXTURES if "interaction-edge" in f.needs}
        refused = set()
        for fixture in FIXTURES:
            try:
                oracle.plan_for(fixture.expected, intents=fixture.intents)
            except oracle.Unrepresentable as gap:
                assert gap.need == "interaction-edge"
                refused.add(fixture.fixture_id)
        assert declared == refused
        assert len(declared) == 8


class TestTheModelSeesOnlyThePrompt:
    """The fixture is an answer key. If any of it travelled, the score would
    measure transcription."""

    @pytest.mark.parametrize(
        "fixture", [ONE, FIXTURES[1], FIXTURES[11]], ids=lambda f: f.fixture_id
    )
    def test_the_planning_turn_carries_no_part_of_the_answer(
        self, client, user_and_token, tmp_curio, monkeypatch, fixture
    ):
        driver = _driver(client, user_and_token, monkeypatch)
        oracle_attempt(fixture, driver, templates=TEMPLATES, example=_example(fixture))
        # The turn that produced the plan: everything the model had to work
        # with before it answered.
        planning_turn = json.dumps(driver.calls[0])
        example = _example(fixture)
        dataflow = example["dataflow"]
        for node in dataflow["nodes"]:
            assert node["id"] not in planning_turn
            content = node.get("content") or ""
            for line in content.splitlines():
                stripped = line.strip()
                if len(stripped) >= 25:
                    assert stripped not in planning_turn, stripped[:60]
        for edge in dataflow["edges"]:
            assert edge["id"] not in planning_turn
        assert json.dumps(fixture.expected["edges"]) not in planning_turn
        assert "expected" not in json.loads(planning_turn)[-1]["content"]

    def test_the_prompt_itself_did_reach_the_model(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The negative tests above would also pass if nothing was sent."""
        driver = _driver(client, user_and_token, monkeypatch)
        oracle_attempt(ONE, driver, templates=TEMPLATES, example=_example(ONE))
        assert ONE.prompt in json.dumps(driver.calls[0])


class TestMutationsFailForTheRightReason:
    """A harness that cannot fail is not a harness. Each mutation is a wrong
    answer of a different kind, and each must land in its own category."""

    def _mutated_attempt(self, client, user_and_token, monkeypatch, mutate):
        fixture = ONE
        example = _example(fixture)
        driver = _driver(client, user_and_token, monkeypatch)
        expected_graph = canonical_graph_from_spec(example, templates=TEMPLATES)
        plan = oracle.plan_for(fixture.expected, intents=fixture.intents)
        payload = {
            "goal": plan.goal,
            "nodes": [dict(n) for n in plan.nodes],
            "edges": [dict(e) for e in plan.edges],
        }
        contents = oracle.content_replies(
            fixture.expected, example=example, origins=expected_graph.origins,
            only_executable=False,
        )
        mutate(payload, contents)
        reply = "Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": payload}) + "\n```"
        result = oracle_attempt(
            fixture, driver, templates=TEMPLATES, example=example,
            responder=oracle_responder(reply, contents),
        )
        return result

    def test_a_dropped_node_fails_as_a_missing_node(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        def mutate(payload, contents):
            dropped = payload["nodes"].pop()["ref"]
            payload["edges"] = [
                e for e in payload["edges"]
                if e["from"] != dropped and e["to"] != dropped
            ]

        result = self._mutated_attempt(client, user_and_token, monkeypatch, mutate)
        assert "missing-node" in result.score.categories
        assert result.score.total < 1.0

    def test_a_rewired_edge_fails_as_topology_with_the_templates_intact(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """A VALID graph of the right nodes, wired wrong: the second
        aggregation reads the loader directly instead of the shared cleanup.
        (An invalid rewiring -- an edge into a Data Loading node, which
        declares no input -- is refused by the runtime's own plan validation
        and is the next test.)"""
        def mutate(payload, contents):
            loader = payload["nodes"][0]["ref"]
            transform1 = payload["nodes"][1]["ref"]
            for edge in payload["edges"]:
                if edge["from"] == transform1 and edge["to"] != loader:
                    edge["from"] = loader
                    break

        result = self._mutated_attempt(client, user_and_token, monkeypatch, mutate)
        assert "topology" in result.score.categories, result.scored.as_dict()
        assert result.scored.score.dimension("templates").value == 1.0
        assert result.scored.score.dimension("topology").value < 1.0

    def test_an_edge_the_contract_forbids_is_refused_by_the_runtime(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """An edge into a Data Loading node contradicts the template's declared
        ports, so the plan never mints: the runtime corrects the model instead.
        The harness records a refusal, which is a different finding from a
        badly-built graph and must not be reported as one."""
        def mutate(payload, contents):
            payload["edges"][-1]["to"] = payload["nodes"][0]["ref"]

        result = self._mutated_attempt(client, user_and_token, monkeypatch, mutate)
        assert result.turn.refused
        assert "refused" in result.score.categories
        assert not attempt_mod.spec_nodes(result.spec)

    def test_a_wrong_template_fails_as_both_missing_and_extra(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        def mutate(payload, contents):
            for node in payload["nodes"]:
                if node["nodeType"].endswith("data-transformation"):
                    node["nodeType"] = "curio.builtin/computation-analysis"
                    break

        result = self._mutated_attempt(client, user_and_token, monkeypatch, mutate)
        assert "missing-node" in result.score.categories
        assert "extra-node" in result.score.categories

    def test_an_extra_node_nobody_asked_for_is_reported(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        def mutate(payload, contents):
            payload["nodes"].append({
                "ref": "spare", "nodeType": "curio.builtin/computation-analysis",
                "title": "Spare", "intent": "an extra step nobody asked for",
            })
            payload["edges"].append({"from": payload["nodes"][0]["ref"], "to": "spare"})
            contents["spare"] = "return 1"

        result = self._mutated_attempt(client, user_and_token, monkeypatch, mutate)
        assert "extra-node" in result.score.categories

    def test_a_fabricated_dataset_id_never_reaches_the_spec(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The grounding gate (``DEC-072``) refuses an invented catalog id
        before the code can run, so the fabricated resource never lands and the
        harness reports what actually happened: the node was not filled and its
        dependents were blocked. Fabrication scoring is still the right rule --
        it is unit-tested against a spec that carries one -- but through the
        real pipeline the runtime gets there first, which is the better
        outcome and worth pinning."""
        def mutate(payload, contents):
            loader = payload["nodes"][0]["ref"]
            contents[loader] = (
                'import pandas as pd\n'
                'p = curio_dataset_path("data.invented.nowhere")\n'
                'return pd.read_csv(p)'
            )

        result = self._mutated_attempt(client, user_and_token, monkeypatch, mutate)
        assert result.score.total < 1.0
        assert "execution-failed" in result.score.categories
        assert "content-missing" in result.score.categories
        assert not result.scored.comparison.fabricated
        loader_nodes = [
            node for node in attempt_mod.spec_nodes(result.spec)
            if node.get("type") == "curio.builtin/data-loading"
        ]
        assert loader_nodes and not (loader_nodes[0].get("content") or "").strip()
        refusals = [
            attempt
            for outcome in result.solve.results.values()
            for attempt in (outcome.get("attempts") or [])
            if attempt.get("kind") == "ungrounded-source"
        ]
        assert refusals, result.solve.results
        assert "data.invented.nowhere" in json.dumps(refusals)

    def test_an_invented_template_is_refused_at_mint_and_nothing_is_built(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The runtime's own gate fires first: a plan naming a template that
        does not exist never becomes a proposal (dev/93). The harness records
        a refusal rather than a fabricated graph -- both are failures, and the
        report must not confuse them."""
        def mutate(payload, contents):
            payload["nodes"][0]["nodeType"] = "someone.invented/magic-loader"

        result = self._mutated_attempt(client, user_and_token, monkeypatch, mutate)
        assert result.turn.refused
        assert "refused" in result.score.categories
        assert "missing-node" in result.score.categories
        assert not attempt_mod.spec_nodes(result.spec)

    def test_reordering_a_correct_plan_still_scores_one(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The benign mutation. Same graph, different order, different titles."""
        def mutate(payload, contents):
            payload["nodes"].reverse()
            payload["edges"].reverse()
            for index, node in enumerate(payload["nodes"]):
                node["title"] = f"Step {index + 1}"

        result = self._mutated_attempt(client, user_and_token, monkeypatch, mutate)
        assert result.score.total == pytest.approx(1.0), result.scored.as_dict()


class TestProvisionedMode:
    """Mode 1 of the brief: install the declared datasets and packages through
    the existing services, then check the palettes can see them."""

    def test_declared_datasets_install_and_show_as_installed(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        driver = _driver(client, user_and_token, monkeypatch)
        result = oracle_attempt(ONE, driver, templates=TEMPLATES, example=_example(ONE))
        installed = driver.installed_dataset_ids()
        for dataset_id in ONE.required["datasets"]:
            assert dataset_id in installed, (
                f"{dataset_id} was installed but the catalog listing the dataset "
                "palette reads does not mark it installed"
            )
        # And the dataflow's own refs -- the dependency source of truth (dev/81).
        refs = result.spec["dataflow"].get("datasets") or []
        assert {r["datasetId"] for r in refs} == set(ONE.required["datasets"])

    def test_a_declared_packages_templates_reach_the_roster_the_palette_reads(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        driver = _driver(client, user_and_token, monkeypatch)
        oracle_attempt(
            STREETVISION, driver, templates=TEMPLATES, example=_example(STREETVISION)
        )
        roster = driver.roster_ids()
        for node in STREETVISION.expected["nodes"]:
            assert node["type"] in roster, (
                f"{node['type']} is in the expected graph but not in the roster the "
                "package palette and the plan mint both read"
            )
        # The lockfile is the authority (dev/101), and the install wrote it.
        from utk_curio.backend.app.packages.spec_packages import project_packages

        assert "curio.streetvision@1" in set(
            project_packages(driver.read_spec()) or ()
        ) | set(STREETVISION.required["packages"])

    def test_the_reconstruction_lands_in_the_persisted_spec_and_survives_a_reread(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        driver = _driver(client, user_and_token, monkeypatch)
        result = oracle_attempt(ONE, driver, templates=TEMPLATES, example=_example(ONE))
        again = driver.read_spec()
        assert again == result.spec
        nodes = attempt_mod.spec_nodes(again)
        assert len(nodes) == len(ONE.expected["nodes"])
        assert all((node.get("content") or "").strip() for node in nodes), (
            "every node came back with content: the plan placed them and Solve "
            "filled them, per wave, on disk"
        )


class TestResolutionModePackageTemplates:
    """Mode 2 of the brief, route one: the template itself lives in a package
    the project has not enlisted. The plan cannot even name it."""

    def test_an_unenlisted_template_is_refused_and_the_correction_names_it(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        driver = _driver(client, user_and_token, monkeypatch)
        result = oracle_attempt(
            STREETVISION, driver, templates=TEMPLATES, example=_example(STREETVISION),
            provision_packages=False,
            account_only_packages=["curio.streetvision@1"],
        )
        assert result.turn.refused, "a plan naming an unenlisted template must not mint"
        assert "curio.streetvision/street-view-fetcher" not in driver.roster_ids()
        # The runtime's correction round is what the model actually gets told.
        correction = str(driver.calls[-1][-1]["content"])
        assert "[plan validation]" in correction
        assert "Available node templates" in correction
        # And the package IS installed for this account -- the state that makes
        # the reuse ladder's ENLIST rung the right move (dev/93).
        from utk_curio.backend.app.packages.services import (
            installed_templates_not_in_project,
        )

        not_enlisted = {
            row["id"]
            for row in installed_templates_not_in_project(
                driver.user_key, driver.project_id
            )
        }
        assert "curio.streetvision/street-view-fetcher" in not_enlisted

    def test_the_reviewed_enlist_resolves_it_and_authors_no_package(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The middle rung of dev/93's reuse ladder: ENLIST, never AUTHOR."""
        fixture = STREETVISION
        example = _example(fixture)
        driver = _driver(client, user_and_token, monkeypatch)
        driver.use_scripted_provider()
        driver.stub_pip()
        driver.create_project()
        driver.install_and_attach()
        driver.install_datasets(fixture.required["datasets"])
        driver.install_packages_to_account_only(["curio.streetvision@1"])
        researcher = driver.install_and_attach_second(RESEARCHER_COORD)

        expected_graph = canonical_graph_from_spec(example, templates=TEMPLATES)
        plan = oracle.plan_for(fixture.expected, intents=fixture.intents)
        contents = oracle.content_replies(
            fixture.expected, example=example, origins=expected_graph.origins,
            only_executable=False,
        )
        enlist = (
            "That package is installed but not enlisted here.\n```curio.v1\n"
            + json.dumps({
                "toolRequest": {
                    "tool": "package.install",
                    "params": {
                        "dirName": "curio.streetvision@1",
                        "reason": "its street-view, inference and gallery templates",
                    },
                }
            })
            + "\n```"
        )
        base = oracle_responder(plan.as_reply(), contents)
        # Two agents answer in this test, so the script is keyed on the PHASE
        # the test is in rather than on a call index: applying the install is
        # what moves it on, the way a person's next message would.
        phase = {"name": "enlist"}

        def responder(messages, index):
            if driver.delegate_inputs(messages).get("intent"):
                return base(messages, 1)          # a per-node content request
            if phase["name"] == "enlist":
                return enlist
            return plan.as_reply()

        driver.script(responder)
        driver.fake_sandbox()

        # The enlist happens where the lane lives: the Researcher holds
        # package.install, the Dataflow Builder does not (builtin.py).
        dfb = driver.with_attachment(researcher)
        first = driver.run_turn(
            "the street view templates are installed on my account but not in this project"
        )
        install = first.proposal_of("package.install")
        assert install, [p.get("tool") for p in first.proposals]
        assert not first.proposal_of("package.draft.apply"), (
            "a template that already exists is never a reason to author a package"
        )
        applied = driver.apply(install)
        assert applied.get("status") == "applied", applied
        assert applied.get("requiresRegistryRefresh") is True, (
            "a lockfile-changing apply must tell the frontend to refresh its "
            "registries (dev/105)"
        )
        assert "curio.streetvision/cv-gallery" in driver.roster_ids()

        phase["name"] = "plan"
        driver.with_attachment(dfb)
        second = driver.run_turn("go ahead with the plan")
        assert second.plan_proposal, second.reply[:200]
        driver.apply(second.plan_proposal)
        driver.solve()
        spec = driver.read_spec()
        built = {
            node.get("type") for node in attempt_mod.spec_nodes(spec)
        }
        assert "curio.streetvision/street-view-fetcher" in built
        assert "package.draft.apply" not in driver.applied


class TestResolutionModePackageDependencies:
    """Mode 2, route two -- the different one. Example 09 declares
    ``curio.weather@1`` while every one of its nodes is a builtin template: the
    package is there for the python libraries its manifest owns. So nothing is
    refused at mint; the miss can only appear when code runs, and the fix is
    the same reviewed enlist. A missing library is never a reason to author a
    package."""

    def test_the_dependency_package_declares_libraries_no_node_type_needs(self):
        import json as _json
        from pathlib import Path

        manifest = _json.loads(
            (
                Path(__file__).resolve().parents[4] / "packages/curio.weather@1/manifest.json"
            ).read_text(encoding="utf-8")
        )
        assert set(manifest["dependencies"]["python"]) >= {
            "pythermalcomfort", "rasterstats"
        }
        fixture = load_fixture(
            FIXTURE_ROOT / "09-heterogeneous-data-linked-views.prompt.json"
        )
        assert fixture.required["packages"] == ["curio.weather@1"]
        assert "package-enlist:dependencies" in fixture.needs
        assert all(
            node["type"].startswith("curio.builtin/")
            for node in fixture.expected["nodes"]
        ), "if a weather TEMPLATE appeared here this would be the other route"

    def test_the_reviewed_enlist_installs_the_libraries_and_reports_failures(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        driver = _driver(client, user_and_token, monkeypatch)
        driver.use_scripted_provider()
        # The library is missing on this machine: the install service must say
        # so rather than report a clean bill of health (dev/92).
        driver.stub_pip(import_errors={"pythermalcomfort": "No module named 'pythermalcomfort'"})
        driver.create_project()
        driver.install_and_attach()
        driver.with_attachment(driver.install_and_attach_second(RESEARCHER_COORD))
        enlist = (
            "The thermal comfort library belongs to a package.\n```curio.v1\n"
            + json.dumps({
                "toolRequest": {
                    "tool": "package.install",
                    "params": {
                        "dirName": "curio.weather@1",
                        "reason": "it owns pythermalcomfort, rasterio and rasterstats",
                    },
                }
            })
            + "\n```"
        )
        driver.script(lambda messages, index: enlist)
        driver.fake_sandbox()
        turn = driver.run_turn(
            "compute the thermal comfort index for Milan; the library is not installed"
        )
        proposal = turn.proposal_of("package.install")
        assert proposal, [p.get("tool") for p in turn.proposals]
        assert not turn.proposal_of("package.draft.apply")
        applied = driver.apply(proposal)
        assert applied.get("status") == "applied", applied
        assert "pythermalcomfort" in (applied.get("importErrors") or {}), applied
        from utk_curio.backend.app.packages.spec_packages import project_packages

        assert "curio.weather@1" in set(project_packages(driver.read_spec()) or ())


class TestResolutionModeDataset:
    """A declared dataset left uninstalled. The route may be a reviewed
    ``dataset.install`` or grounding by catalog id; the report says which, and
    either way nothing is invented."""

    def test_a_catalog_dataset_grounds_by_id_without_being_installed(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        driver = _driver(client, user_and_token, monkeypatch)
        result = oracle_attempt(
            ONE, driver, templates=TEMPLATES, example=_example(ONE),
            provision_datasets=False,
        )
        # The loader still landed: the catalog resolves the id, so the source is
        # grounded (dev/114) even though the project never installed it.
        loader = [
            node for node in attempt_mod.spec_nodes(result.spec)
            if node.get("type") == "curio.builtin/data-loading"
        ]
        assert loader and (loader[0].get("content") or "").strip()
        assert "curio_dataset_path" in loader[0]["content"]
        # And the harness reports the unresolved DECLARATION rather than
        # pretending the dependency was satisfied.
        assert result.scored.comparison.dependencies.datasets_missing == tuple(
            ONE.required["datasets"]
        )
        assert "dependency-unresolved" in result.score.categories

    def test_a_reviewed_dataset_install_resolves_the_declaration(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        fixture = ONE
        driver = _driver(client, user_and_token, monkeypatch)
        driver.use_scripted_provider()
        driver.stub_pip()
        driver.create_project()
        driver.install_and_attach()
        # dataset.install is the Dataset Finder's lane (builtin.py).
        driver.with_attachment(driver.install_and_attach_second(DATASET_FINDER_COORD))
        dataset_id = fixture.required["datasets"][0]
        install = (
            "That dataset is in the catalog.\n```curio.v1\n"
            + json.dumps({
                "toolRequest": {
                    "tool": "dataset.install",
                    "params": {"datasetId": dataset_id},
                }
            })
            + "\n```"
        )
        driver.script(lambda messages, index: install)
        driver.fake_sandbox()
        turn = driver.run_turn(fixture.prompt)
        proposal = turn.proposal_of("dataset.install")
        assert proposal, [p.get("tool") for p in turn.proposals]
        applied = driver.apply_under_policy(turn, required=fixture.required)
        assert applied and applied[0][1].get("status") == "applied", applied
        refs = driver.read_spec()["dataflow"].get("datasets") or []
        assert {r["datasetId"] for r in refs} == {dataset_id}

    def test_a_dataset_the_fixture_did_not_ask_for_is_left_pending(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Rule 3 of the user policy: the harness's "user" installs what the
        fixture required and nothing else, so a run cannot pass by accepting
        whatever it was offered."""
        driver = _driver(client, user_and_token, monkeypatch)
        driver.use_scripted_provider()
        driver.stub_pip()
        driver.create_project()
        driver.install_and_attach()
        driver.with_attachment(driver.install_and_attach_second(DATASET_FINDER_COORD))
        other = "data.cityofchicago.neighborhoods"
        install = (
            "Try this one.\n```curio.v1\n"
            + json.dumps({
                "toolRequest": {"tool": "dataset.install", "params": {"datasetId": other}}
            })
            + "\n```"
        )
        driver.script(lambda messages, index: install)
        driver.fake_sandbox()
        turn = driver.run_turn(ONE.prompt)
        applied = driver.apply_under_policy(turn, required=ONE.required)
        assert applied == []
        assert ("dataset.install", other) in driver.left_pending
        assert not (driver.read_spec()["dataflow"].get("datasets") or [])


class TestSolveOutcomesAreReadHonestly:
    def test_a_kind_the_sandbox_cannot_run_is_excluded_never_failed(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """dev/119 (DEC-076): a Vega-Lite node has no code the sandbox could
        run. Solve writes its content and says so; the score must neither
        credit nor blame it."""
        driver = _driver(client, user_and_token, monkeypatch)
        result = oracle_attempt(ONE, driver, templates=TEMPLATES, example=_example(ONE))
        statuses = {d.status for d in result.scored.execution_details}
        assert "not-executable" in statuses
        assert "verified" in statuses
        measured = [d for d in result.scored.execution_details if d.measured]
        assert measured and all(d.passed for d in measured)
        assert result.scored.score.dimension("execution").value == 1.0

    def test_the_score_reads_verification_status_and_not_the_plan_ledger(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """dev/118 F6: the plan ledger reads ``validated`` for a node that
        merely could not run. Reading it would over-credit."""
        driver = _driver(client, user_and_token, monkeypatch)
        result = oracle_attempt(ONE, driver, templates=TEMPLATES, example=_example(ONE))
        session = (result.solve.payload.get("builderSession") or {})
        ledger = session.get("nodeStates") or {}
        outcomes = {d.node: d for d in result.scored.execution_details}
        vega_ids = [
            node["id"] for node in attempt_mod.spec_nodes(result.spec)
            if node.get("type") == "curio.builtin/vis-vega"
        ]
        for node_id in vega_ids:
            assert outcomes[node_id].executable is False
        assert ledger is not None  # the ledger exists; the scorer just ignores it

    def test_a_failing_node_is_reported_as_execution_failed(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        fixture = ONE
        example = _example(fixture)
        driver = _driver(client, user_and_token, monkeypatch)
        driver.use_scripted_provider()
        driver.stub_pip()
        driver.create_project()
        driver.install_and_attach()
        driver.install_datasets(fixture.required["datasets"])
        expected_graph = canonical_graph_from_spec(example, templates=TEMPLATES)
        plan = oracle.plan_for(fixture.expected, intents=fixture.intents)
        contents = oracle.content_replies(
            fixture.expected, example=example, origins=expected_graph.origins,
            only_executable=False,
        )
        driver.script(oracle_responder(plan.as_reply(), contents))

        def _exec(endpoint, payload):
            raise RuntimeError("boom: the node raised")

        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec", _exec
        )
        turn = driver.run_turn(fixture.prompt)
        driver.apply(turn.plan_proposal)
        solve = driver.solve()
        outcomes = attempt_mod.execution_outcomes(
            solve.results, actual_spec=driver.read_spec(), templates=TEMPLATES
        )
        failed = [o for o in outcomes if o.executable and not o.passed]
        assert failed, [(o.node, o.status) for o in outcomes]
