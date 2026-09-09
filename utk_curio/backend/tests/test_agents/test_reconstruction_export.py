"""dev/121 — the fine-tuning export, the live runner's refusals, and the CLI.

The export exists so approved fixtures can later become prompt -> expected
pairs. Its whole value is in what it refuses: an unreviewed prompt is not
training data, and a held-out fixture that leaked into training makes every
number after it meaningless. Both refusals are tested here, and so is the
absence of any code path that trains anything.

Offline: no stack, no provider, no network.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from utk_curio.backend.app.agents.evaluation import export as export_mod
from utk_curio.backend.app.agents.evaluation import live as live_mod
from utk_curio.backend.app.agents.evaluation.fixtures import (
    Fixture,
    fixture_paths,
    load_fixture,
)

FIXTURES = [load_fixture(path) for path in fixture_paths()]


def _approved(fixture: Fixture, *, split: str | None = None) -> Fixture:
    data = json.loads(json.dumps(fixture.data))
    data["review"] = {
        "status": "approved",
        "draftedBy": data["review"].get("draftedBy"),
        "reviewedBy": "the owner",
        "reviewedAt": "2026-09-09T00:00:00Z",
    }
    if split:
        data["split"] = split
    return Fixture(path=fixture.path, data=data)


class TestSplits:
    def test_every_split_has_fixtures_to_draw_from(self):
        summary = export_mod.split_summary(FIXTURES)
        assert set(summary) == {"train", "validation", "heldout"}
        assert all(counts["total"] > 0 for counts in summary.values()), summary

    def test_only_the_train_split_may_feed_training(self):
        assert export_mod.TRAINABLE_SPLITS == ("train",)

    def test_a_training_export_refuses_the_heldout_split(self):
        with pytest.raises(export_mod.ExportRefused) as refusal:
            export_mod.rows_for_split(FIXTURES, split="heldout", purpose="training")
        assert "held-out" in str(refusal.value)

    def test_a_training_export_refuses_the_validation_split(self):
        with pytest.raises(export_mod.ExportRefused):
            export_mod.rows_for_split(FIXTURES, split="validation", purpose="training")

    def test_an_unknown_split_is_refused_rather_than_empty(self):
        with pytest.raises(export_mod.ExportRefused):
            export_mod.rows_for_split(FIXTURES, split="test", purpose="evaluation")


class TestReviewGate:
    def test_nothing_exports_while_every_prompt_is_unreviewed(self):
        """The corpus ships pending review, so an export today refuses and
        says why -- rather than quietly producing an empty file."""
        assert all(not f.approved for f in FIXTURES)
        with pytest.raises(export_mod.ExportRefused) as refusal:
            export_mod.rows_for_split(FIXTURES, split="train")
        assert "awaiting review" in str(refusal.value)

    def test_an_approved_fixture_exports(self):
        approved = [_approved(f) for f in FIXTURES if f.split == "train"]
        rows = export_mod.rows_for_split(approved, split="train", purpose="training")
        assert rows
        assert {row.split for row in rows} == {"train"}

    def test_an_export_row_carries_the_prompt_and_its_answer_key(self):
        approved = [_approved(FIXTURES[0], split="train")]
        row = export_mod.rows_for_split(approved, split="train")[0]
        payload = row.as_dict()
        assert payload["prompt"] == FIXTURES[0].prompt
        assert payload["expected"] == FIXTURES[0].expected
        assert payload["required"] == FIXTURES[0].required
        assert payload["fixtureSha256"]
        assert payload["source"].startswith("docs/examples/")

    def test_the_unapproved_escape_hatch_exists_but_not_for_training(self):
        rows = export_mod.rows_for_split(
            FIXTURES, split="train", purpose="evaluation", require_approved=False
        )
        assert rows, "an evaluation export may draw on unreviewed prompts"
        from utk_curio.tools.agent_eval import main

        assert main([
            "export", "--split", "train", "--purpose", "training",
            "--include-unapproved", "--out", "/dev/null",
        ]) == 3


class TestWriting:
    def test_rows_are_written_one_json_object_per_line(self, tmp_path):
        approved = [_approved(f, split="train") for f in FIXTURES[:3]]
        rows = export_mod.rows_for_split(approved, split="train")
        target = tmp_path / "out" / "train.jsonl"
        written = export_mod.write_jsonl(rows, target)
        lines = target.read_text(encoding="utf-8").strip().splitlines()
        assert written == len(lines) == 3
        for line in lines:
            payload = json.loads(line)
            assert set(payload) == {
                "fixtureId", "prompt", "context", "expected", "required",
                "split", "fixtureSha256", "source",
            }

    def test_nothing_in_the_export_module_trains_anything(self):
        """The module's contract, asserted rather than asserted-in-prose: no
        provider, no network, no job."""
        source = (
            __import__("pathlib").Path(export_mod.__file__).read_text(encoding="utf-8")
        )
        for forbidden in (
            "run_chat_completion", "urllib", "requests", "fine_tun", "openai",
        ):
            assert forbidden not in source, forbidden


class TestLiveRunnerRefusals:
    def test_the_live_runner_refuses_without_the_opt_in_flag(self):
        with pytest.raises(live_mod.LiveEvalRefused) as refusal:
            live_mod.require_opt_in({})
        assert "CURIO_EVAL_LIVE" in str(refusal.value)

    @pytest.mark.parametrize("value", ["1", "true", "yes"])
    def test_the_flag_is_honoured(self, value):
        live_mod.require_opt_in({live_mod.LIVE_ENV_FLAG: value})

    def test_an_unreachable_backend_is_a_refusal_not_a_traceback(self):
        client = live_mod.HttpClient(base_url="http://127.0.0.1:59999", token="x")
        with pytest.raises(live_mod.LiveEvalRefused) as refusal:
            client.request("/api/auth/me")
        assert "could not reach" in str(refusal.value)

    def test_an_account_with_no_provider_is_refused_before_any_project(self):
        class _Client(live_mod.HttpClient):
            def json(self, path, *, method="GET", payload=None):
                assert path == "/api/auth/me", f"it asked for {path} first"
                return {}

        run = live_mod.LiveRun(
            client=_Client(base_url="http://x", token="t"),
            templates={},
            report=live_mod.RunReport(run_id="r"),
        )
        with pytest.raises(live_mod.LiveEvalRefused) as refusal:
            run.provider_record()
        assert "AI Settings" in str(refusal.value)

    def test_the_provider_record_keeps_the_host_and_never_a_key(self):
        class _Client(live_mod.HttpClient):
            def json(self, path, *, method="GET", payload=None):
                return {
                    "llmApiType": "openai_compatible",
                    "llmBaseUrl": "http://192.168.1.9:11434/v1",
                    "llmModel": "gemma-4",
                    "llmApiKey": "sk-should-never-be-read",
                }

        run = live_mod.LiveRun(
            client=_Client(base_url="http://x", token="t"),
            templates={},
            report=live_mod.RunReport(run_id="r"),
        )
        record = run.provider_record()
        assert record.base_url_host == "192.168.1.9:11434"
        assert record.model == "gemma-4"
        assert "sk-should-never-be-read" not in json.dumps(record.as_dict())

    def test_the_fixture_budget_is_bounded_and_defaulted(self):
        assert live_mod.fixture_budget_s({}) == live_mod.DEFAULT_FIXTURE_BUDGET_S
        assert live_mod.fixture_budget_s({live_mod.BUDGET_ENV: "60"}) == 60
        assert live_mod.fixture_budget_s({live_mod.BUDGET_ENV: "1"}) == 30
        assert live_mod.fixture_budget_s({live_mod.BUDGET_ENV: "nonsense"}) == (
            live_mod.DEFAULT_FIXTURE_BUDGET_S
        )

    def test_heavy_fixtures_carry_their_skip_into_the_report(self):
        run = live_mod.LiveRun(
            client=live_mod.HttpClient(base_url="http://x", token="t"),
            templates={},
            report=live_mod.RunReport(run_id="r"),
            include_external=False,
        )
        streetvision = next(
            f for f in FIXTURES if f.fixture_id == "10-street-vision-cv-analysis"
        )
        skips = run.skip_reasons(streetvision)
        assert skips, "example 10's external-service skip must be visible"
        assert all(entry["reason"] for entry in skips)
        opted_in = replace(run, include_external=True)
        assert not opted_in.skip_reasons(streetvision)


class TestTheCli:
    def test_list_prints_every_fixture_and_its_split(self, capsys):
        from utk_curio.tools.agent_eval import main

        assert main(["list"]) == 0
        out = capsys.readouterr().out
        assert "31 fixtures" in out
        assert "01-vega-lite-chained-transforms" in out
        assert "pending-owner-review" in out

    def test_run_refuses_without_the_flag(self, capsys, monkeypatch):
        from utk_curio.tools.agent_eval import main

        monkeypatch.delenv(live_mod.LIVE_ENV_FLAG, raising=False)
        assert main(["run", "--token", "t"]) == 3
        assert "opt-in" in capsys.readouterr().err

    def test_run_refuses_without_a_token(self, capsys, monkeypatch):
        from utk_curio.tools.agent_eval import main

        monkeypatch.setenv(live_mod.LIVE_ENV_FLAG, "1")
        monkeypatch.delenv("CURIO_EVAL_TOKEN", raising=False)
        assert main(["run"]) == 2
        assert "never reads a provider key" in capsys.readouterr().err

    def test_export_refuses_a_heldout_training_export(self, capsys, tmp_path):
        from utk_curio.tools.agent_eval import main

        assert main([
            "export", "--split", "heldout", "--purpose", "training",
            "--out", str(tmp_path / "x.jsonl"),
        ]) == 3
        assert "held-out" in capsys.readouterr().err

    def test_the_cli_has_no_train_verb(self):
        from utk_curio.tools.agent_eval import build_parser

        actions = [
            action for action in build_parser()._actions
            if getattr(action, "choices", None) and "list" in (action.choices or {})
        ]
        assert actions, "the subcommand action was not found"
        assert set(actions[0].choices) == {"list", "run", "export"}
