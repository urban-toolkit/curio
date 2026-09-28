"""dev/123 — one user policy, three callers.

The policy an evaluation plays used to exist twice: in the remote CLI driver
and in the deterministic test driver. Two copies of a rule is one rule that
will drift, and a UI run, a CLI run and a CI run that decided differently would
be measuring three things while reporting one number.

These tests pin the decisions, and pin that every caller resolves the same one.
"""

from __future__ import annotations

import inspect

import pytest

from utk_curio.backend.app.agents.evaluation import live as live_mod
from utk_curio.backend.app.agents.evaluation import policy as policy_mod
from utk_curio.backend.app.agents.evaluation.fixtures import fixture_paths, load_fixture

FIXTURES = [load_fixture(path) for path in fixture_paths()]
WITH_DATASETS = next(f for f in FIXTURES if f.required["datasets"])
WITH_PACKAGE = next(f for f in FIXTURES if f.required["packages"])


def _proposal(tool: str, **pins) -> dict:
    return {"type": "proposal", "proposalId": "p-1", "tool": tool, "pins": pins}


class TestTheDecisions:
    def test_a_plan_is_applied_whole(self):
        policy = policy_mod.UserPolicy.for_fixture(WITH_DATASETS)
        decision = policy.decide(_proposal("dataflow.plan.write"))
        assert decision.apply is True
        assert decision.pending is False

    def test_a_required_dataset_install_is_applied(self):
        policy = policy_mod.UserPolicy.for_fixture(WITH_DATASETS)
        wanted = WITH_DATASETS.required["datasets"][0]
        decision = policy.decide(_proposal("dataset.install", datasetId=wanted))
        assert decision.apply is True
        assert decision.target == wanted

    def test_a_dataset_nobody_asked_for_is_left_pending_with_its_reason(self):
        policy = policy_mod.UserPolicy.for_fixture(WITH_DATASETS)
        decision = policy.decide(
            _proposal("dataset.install", datasetId="data.something.else")
        )
        assert decision.pending is True
        assert "not required by this fixture" in decision.reason
        assert decision.target == "data.something.else"

    def test_a_required_package_install_is_applied_and_another_is_not(self):
        policy = policy_mod.UserPolicy.for_fixture(WITH_PACKAGE)
        wanted = WITH_PACKAGE.required["packages"][0]
        assert policy.decide(_proposal("package.install", dirName=wanted)).apply
        assert policy.decide(
            _proposal("package.install", dirName="curio.unrelated@1")
        ).pending

    def test_a_required_specialist_install_is_applied(self):
        """dev/106 (DEC-068): a specialist the run needs but the project lacks.
        Refusing it would fail the run for a reason the fixture never asked
        about."""
        policy = policy_mod.UserPolicy.for_fixture(WITH_DATASETS)
        decision = policy.decide(_proposal("project.install"))
        assert decision.apply is True

    @pytest.mark.parametrize(
        "tool",
        ["node.content.write", "node.create", "package.draft.apply",
         "node.template.create", ""],
    )
    def test_everything_else_is_a_decision_a_person_makes(self, tool):
        policy = policy_mod.UserPolicy.for_fixture(WITH_DATASETS)
        decision = policy.decide(_proposal(tool))
        assert decision.pending is True
        assert "a person makes" in decision.reason

    def test_the_target_comes_from_pins_never_from_params(self):
        """A proposal part carries PINS — the revision-safety basis the apply
        endpoint re-checks. It has no params echo, and reading one is how the
        first cut of this rule silently declined every install it was offered
        (dev/122 F-c)."""
        policy = policy_mod.UserPolicy.for_fixture(WITH_DATASETS)
        wanted = WITH_DATASETS.required["datasets"][0]
        params_only = {
            "tool": "dataset.install", "params": {"datasetId": wanted}, "pins": {},
        }
        assert policy.decide(params_only).pending is True

    def test_decide_all_keeps_order(self):
        policy = policy_mod.UserPolicy.for_fixture(WITH_DATASETS)
        decisions = policy.decide_all([
            _proposal("dataflow.plan.write"),
            _proposal("node.content.write"),
        ])
        assert [d.tool for d in decisions] == [
            "dataflow.plan.write", "node.content.write",
        ]


class TestEveryCallerSharesIt:
    def test_the_remote_cli_driver_calls_the_shared_policy(self):
        source = inspect.getsource(live_mod.LiveRun._apply_under_policy)
        assert "policy_mod.UserPolicy.for_fixture" in source
        # And it no longer decides for itself.
        assert "required[\"datasets\"]" not in source
        assert "wanted_packages" not in source

    def test_the_deterministic_driver_calls_the_shared_policy(self):
        from utk_curio.backend.tests.test_agents import _reconstruction_driver

        source = inspect.getsource(_reconstruction_driver.InProcessDriver.apply_under_policy)
        assert "policy_mod.UserPolicy" in source
        assert "wanted_datasets" not in source

    def test_no_second_copy_of_the_decision_exists(self):
        """The property, enforced by the decision's own words rather than by a
        loose grep for field names (which matched an unrelated comment in
        ``node_context.py`` on the first attempt).

        Two markers, each unique: the pin-name mapping that identifies an
        install's target, and the sentence a pending install is reported with.
        """
        from pathlib import Path

        root = Path(__file__).resolve().parents[4]
        searched = list((root / "utk_curio/backend/app/agents").rglob("*.py")) + [
            root / "utk_curio/backend/tests/test_agents/_reconstruction_driver.py",
            root / "utk_curio/tools/agent_eval.py",
        ]
        mapping_hits, reason_hits = [], []
        for path in searched:
            text = path.read_text(encoding="utf-8")
            if "_TARGET_PIN" in text:
                mapping_hits.append(path.name)
            if "not required by this fixture" in text:
                reason_hits.append(path.name)
        assert mapping_hits == ["policy.py"], mapping_hits
        assert reason_hits == ["policy.py"], reason_hits
