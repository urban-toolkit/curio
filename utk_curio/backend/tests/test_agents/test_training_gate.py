"""dev/122 — the gate, activation and rollback.

The gate is the part of this feature that is worth arguing about, so these
tests state the argument. Four refusals, each with its own fix. No threshold,
because none is justifiable and a platform-set one would be Curio judging a
model on the user's behalf. And nothing that grades — no agent, no model, least
of all the candidate — anywhere in the path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.agents import testing_provider
from utk_curio.backend.app.agents.evaluation.fixtures import fixture_paths, load_fixture
from utk_curio.backend.app.agents.training import gate as gate_mod
from utk_curio.backend.app.agents.training import records as records_mod
from utk_curio.backend.app.agents.training import service as training_service
from utk_curio.backend.tests.test_agents.test_training_routes import (  # noqa: F401
    API_KEY, account, approved_corpus, _auth,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
HELDOUT = [f for f in (load_fixture(p) for p in fixture_paths()) if f.split == "heldout"]


def _digests(fixtures=None):
    return {f.fixture_id: f.fixture_sha256() for f in (fixtures or HELDOUT)}


def _gate(**overrides):
    payload = dict(
        trained_model="ft:base:curio-plans:abc",
        split="heldout",
        run_id="eval-1",
        fixture_digests=_digests(),
        scores={f.fixture_id: 0.94 for f in HELDOUT},
        categories={f.fixture_id: ["pass"] for f in HELDOUT},
        evaluated_via="agent_eval --model",
    )
    payload.update(overrides)
    return gate_mod.GateRecord(**payload)


class TestTheFourRefusals:
    def test_no_evaluation_at_all(self):
        with pytest.raises(gate_mod.GateRefused) as refusal:
            gate_mod.check(
                gate=None, trained_model="ft:x", corpus_digests=_digests()
            )
        assert "no evaluation exists" in str(refusal.value)
        assert "have not evaluated" in str(refusal.value)

    def test_an_evaluation_of_a_different_model(self):
        with pytest.raises(gate_mod.GateRefused) as refusal:
            gate_mod.check(
                gate=_gate(trained_model="ft:someone-else"),
                trained_model="ft:base:curio-plans:abc",
                corpus_digests=_digests(),
            )
        assert "says nothing about this one" in str(refusal.value)

    def test_an_evaluation_on_the_wrong_split(self):
        with pytest.raises(gate_mod.GateRefused) as refusal:
            gate_mod.check(
                gate=_gate(split="train"),
                trained_model="ft:base:curio-plans:abc",
                corpus_digests=_digests(),
            )
        assert "measures memorisation" in str(refusal.value)

    def test_an_evaluation_whose_corpus_has_moved(self):
        stale = dict(_digests())
        first = sorted(stale)[0]
        stale[first] = "0" * 64
        with pytest.raises(gate_mod.GateRefused) as refusal:
            gate_mod.check(
                gate=_gate(fixture_digests=stale),
                trained_model="ft:base:curio-plans:abc",
                corpus_digests=_digests(),
            )
        assert "changed since this evaluation" in str(refusal.value)

    def test_an_evaluation_with_no_digests_cannot_be_checked(self):
        with pytest.raises(gate_mod.GateRefused) as refusal:
            gate_mod.check(
                gate=_gate(fixture_digests={}),
                trained_model="ft:base:curio-plans:abc",
                corpus_digests=_digests(),
            )
        assert "no fixture digests" in str(refusal.value)

    def test_a_job_with_no_trained_model_has_nothing_to_activate(self):
        with pytest.raises(gate_mod.GateRefused) as refusal:
            gate_mod.check(gate=_gate(), trained_model="", corpus_digests=_digests())
        assert "nothing to activate" in str(refusal.value)

    def test_a_matching_evaluation_passes(self):
        checked = gate_mod.check(
            gate=_gate(),
            trained_model="ft:base:curio-plans:abc",
            corpus_digests=_digests(),
        )
        assert checked.run_id == "eval-1"


class TestTheGateIsNotAThreshold:
    def test_a_low_score_still_satisfies_the_gate(self):
        """Deliberate: Curio does not decide that a trained model is good
        enough. It refuses to let you activate one you have not evaluated."""
        checked = gate_mod.check(
            gate=_gate(scores={f.fixture_id: 0.0 for f in HELDOUT}),
            trained_model="ft:base:curio-plans:abc",
            corpus_digests=_digests(),
        )
        assert gate_mod.summary(checked)["meanScore"] == 0.0

    def test_the_summary_reports_numbers_and_says_it_draws_no_conclusion(self):
        summary = gate_mod.summary(_gate())
        assert summary["meanScore"] == 0.94
        assert summary["split"] == "heldout"
        assert summary["comparator"] == "deterministic"
        assert "your call" in summary["note"]

    def test_the_record_says_which_mechanism_scored_it(self):
        """So a reader never has to wonder whether a model graded itself."""
        assert _gate().as_dict()["comparator"] == "deterministic"

    def test_no_agent_or_model_appears_in_the_gate_or_activation_path(self):
        """DEC-055 has no authority here and dev/11's rule survives: the
        approval path contains no completion call and no evaluator agent."""
        import re

        forbidden = re.compile(
            r"(run_chat_completion|stream_chat_completion|generated-content-evaluator"
            r"|delegate|content\.quality\.evaluate)"
        )
        for name in ("gate.py", "records.py", "consent.py", "dataset.py"):
            source = (
                REPO_ROOT / "utk_curio/backend/app/agents/training" / name
            ).read_text(encoding="utf-8")
            assert not forbidden.search(source), name
        service_source = (
            REPO_ROOT / "utk_curio/backend/app/agents/training/service.py"
        ).read_text(encoding="utf-8")
        # The service talks to the provider for TUNING only — never for a
        # completion, and never to an evaluator agent.
        assert "run_chat_completion" not in service_source
        assert "generated-content-evaluator" not in service_source


class TestGateStorage:
    def test_a_gate_round_trips_beside_its_job(self, tmp_curio):
        job_id = records_mod.new_job_id()
        gate_mod.write_gate("1", job_id, _gate())
        assert gate_mod.gate_path("1", job_id).name == f"{job_id}.gate.json"
        read_back = gate_mod.read_gate("1", job_id)
        assert read_back.trained_model == "ft:base:curio-plans:abc"
        assert read_back.fixture_digests == _digests()

    def test_a_missing_gate_is_none_not_an_error(self, tmp_curio):
        assert gate_mod.read_gate("1", records_mod.new_job_id()) is None

    def test_a_malformed_job_id_cannot_place_a_gate(self):
        with pytest.raises(records_mod.TrainingRecordError):
            gate_mod.gate_path("1", "../evil")

    def test_the_heldout_digests_come_from_the_corpus(self):
        digests = gate_mod.heldout_digests(
            [load_fixture(p) for p in fixture_paths()]
        )
        assert digests == _digests()
        assert len(digests) >= 1


class TestActivationThroughTheRoutes:
    def _succeeded_job(self, client, account):
        testing_provider.script_fine_tuning()
        preview = client.post(
            "/api/agents/training/dataset/preview", json={},
            headers=_auth(account["token"]),
        ).get_json()
        record = client.post(
            "/api/agents/training/jobs",
            json={
                "baseModel": "scripted-base",
                "rowsDigest": preview["consent"]["rowsDigest"],
                "confirmed": True,
            },
            headers=_auth(account["token"]),
        ).get_json()
        testing_provider.script_fine_tuning(statuses=["succeeded"])
        final = client.get(
            f"/api/agents/training/jobs/{record['jobId']}",
            headers=_auth(account["token"]),
        ).get_json()
        assert final["status"] == "succeeded"
        return final

    def test_activation_is_refused_without_an_evaluation(
        self, client, account, approved_corpus
    ):
        job = self._succeeded_job(client, account)
        response = client.post(
            f"/api/agents/training/jobs/{job['jobId']}/activate",
            headers=_auth(account["token"]),
        )
        assert response.status_code == 409
        assert "no evaluation exists" in response.get_json()["error"]
        # And the panel is told what is missing rather than shown a dead button.
        status = client.get(
            f"/api/agents/training/jobs/{job['jobId']}",
            headers=_auth(account["token"]),
        ).get_json()
        assert status["gate"]["satisfied"] is False
        assert "no evaluation" in status["gate"]["reason"]

    def test_activation_then_rollback_moves_the_account_model_both_ways(
        self, client, account, approved_corpus
    ):
        job = self._succeeded_job(client, account)
        gate_mod.write_gate(
            account["key"], job["jobId"], _gate(trained_model=job["trainedModel"])
        )
        status = client.get(
            f"/api/agents/training/jobs/{job['jobId']}",
            headers=_auth(account["token"]),
        ).get_json()
        assert status["gate"]["satisfied"] is True

        activated = client.post(
            f"/api/agents/training/jobs/{job['jobId']}/activate",
            headers=_auth(account["token"]),
        )
        assert activated.status_code == 200, activated.get_json()
        payload = activated.get_json()
        assert payload["activation"]["previousModel"] == "scripted"
        assert payload["activation"]["activatedAt"]
        assert payload["evaluation"]["meanScore"] == 0.94
        me = client.get("/api/auth/me", headers=_auth(account["token"])).get_json()
        assert me["llm_model"] == job["trainedModel"]

        rolled = client.post(
            f"/api/agents/training/jobs/{job['jobId']}/rollback",
            headers=_auth(account["token"]),
        )
        assert rolled.status_code == 200
        assert rolled.get_json()["activation"]["rolledBackAt"]
        assert "back on 'scripted'" in rolled.get_json()["rollbackNote"]
        me = client.get("/api/auth/me", headers=_auth(account["token"])).get_json()
        assert me["llm_model"] == "scripted"

    def test_a_gate_for_another_model_does_not_authorise_this_one(
        self, client, account, approved_corpus
    ):
        job = self._succeeded_job(client, account)
        gate_mod.write_gate(
            account["key"], job["jobId"], _gate(trained_model="ft:something-else")
        )
        response = client.post(
            f"/api/agents/training/jobs/{job['jobId']}/activate",
            headers=_auth(account["token"]),
        )
        assert response.status_code == 409
        assert "says nothing about this one" in response.get_json()["error"]

    def test_a_gate_whose_corpus_moved_is_stale(
        self, client, account, approved_corpus
    ):
        job = self._succeeded_job(client, account)
        stale = dict(_digests())
        stale[sorted(stale)[0]] = "9" * 64
        gate_mod.write_gate(
            account["key"], job["jobId"],
            _gate(trained_model=job["trainedModel"], fixture_digests=stale),
        )
        response = client.post(
            f"/api/agents/training/jobs/{job['jobId']}/activate",
            headers=_auth(account["token"]),
        )
        assert response.status_code == 409
        assert "changed since this evaluation" in response.get_json()["error"]

    def test_an_unfinished_job_cannot_be_activated(
        self, client, account, approved_corpus
    ):
        testing_provider.script_fine_tuning()
        preview = client.post(
            "/api/agents/training/dataset/preview", json={},
            headers=_auth(account["token"]),
        ).get_json()
        record = client.post(
            "/api/agents/training/jobs",
            json={
                "baseModel": "scripted-base",
                "rowsDigest": preview["consent"]["rowsDigest"],
                "confirmed": True,
            },
            headers=_auth(account["token"]),
        ).get_json()
        response = client.post(
            f"/api/agents/training/jobs/{record['jobId']}/activate",
            headers=_auth(account["token"]),
        )
        assert response.status_code == 409
        assert "nothing to activate yet" in response.get_json()["error"]

    def test_rollback_without_an_activation_is_refused(
        self, client, account, approved_corpus
    ):
        job = self._succeeded_job(client, account)
        response = client.post(
            f"/api/agents/training/jobs/{job['jobId']}/rollback",
            headers=_auth(account["token"]),
        )
        assert response.status_code == 409
        assert "nothing to roll back" in response.get_json()["error"]

    def test_an_account_left_on_a_trained_model_is_reported(
        self, client, account, approved_corpus
    ):
        """An evaluation switches the account's model temporarily. If that is
        interrupted, the account is on a trained model with no activation
        record — and the panel must say so rather than leave it silent."""
        job = self._succeeded_job(client, account)
        client.patch(
            "/api/auth/me", json={"llm_model": job["trainedModel"]},
            headers=_auth(account["token"]),
        )
        check = training_service.account_model_check(account["user"], account["key"])
        assert check["trainedInCurio"] is True
        assert check["unrecorded"] is True
        assert check["jobId"] == job["jobId"]

    def test_an_activated_model_is_not_reported_as_unrecorded(
        self, client, account, approved_corpus
    ):
        job = self._succeeded_job(client, account)
        gate_mod.write_gate(
            account["key"], job["jobId"], _gate(trained_model=job["trainedModel"])
        )
        client.post(
            f"/api/agents/training/jobs/{job['jobId']}/activate",
            headers=_auth(account["token"]),
        )
        check = training_service.account_model_check(account["user"], account["key"])
        assert check["trainedInCurio"] is True
        assert check["unrecorded"] is False

    def test_activation_never_touches_the_key(
        self, client, account, approved_corpus
    ):
        job = self._succeeded_job(client, account)
        gate_mod.write_gate(
            account["key"], job["jobId"], _gate(trained_model=job["trainedModel"])
        )
        payload = client.post(
            f"/api/agents/training/jobs/{job['jobId']}/activate",
            headers=_auth(account["token"]),
        ).get_json()
        assert API_KEY not in json.dumps(payload)
        me = client.get("/api/auth/me", headers=_auth(account["token"])).get_json()
        assert me["has_llm_api_key"] is True
        assert "llm_api_key" not in me


class TestTheEvalToolsGateFlags:
    def test_gate_for_requires_a_model(self, capsys, monkeypatch):
        from utk_curio.tools.agent_eval import main

        monkeypatch.setenv("CURIO_EVAL_LIVE", "1")
        assert main([
            "run", "--token", "t", "--gate-for", "train-20260101T000000Z-abcdef01",
        ]) == 2
        assert "needs --model" in capsys.readouterr().err

    def test_the_flags_exist_and_default_to_off(self):
        from utk_curio.tools.agent_eval import build_parser

        args = build_parser().parse_args(["run"])
        assert args.model == ""
        assert args.gate_for == ""
