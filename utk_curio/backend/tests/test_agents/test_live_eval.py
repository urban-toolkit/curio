"""dev/121 — the live-model evaluation, as a test you have to ask for twice.

Marked ``live_eval``, so it is deselected unless ``--live-eval`` is passed, and
the runner itself refuses without ``CURIO_EVAL_LIVE=1``. It calls the
evaluation account's configured provider once per fixture against a RUNNING
stack.

What it asserts is deliberately not the scores. Live model quality is an
observation, and a suite that failed when a model had a bad day would be
switched off within a week -- so the assertions are about the REPORT: that a run
happened, that it recorded what a score needs to be trusted (provider, model,
prompt and instruction digests, attempts, latency, usage), that no secret
reached the file, and that nothing in it claims to be a gate. Read the numbers
in ``report.md``; act on them by writing a fixture or a memo, not by watching a
red build.
"""

from __future__ import annotations

import json
import os

import pytest

from utk_curio.backend.app.agents.evaluation import live as live_mod
from utk_curio.backend.app.agents.evaluation.fixtures import fixture_paths, load_fixture
from utk_curio.backend.app.agents.evaluation.report import RunReport, new_run_id
from utk_curio.tools.agent_eval import template_index

pytestmark = pytest.mark.live_eval

BACKEND_ENV = "CURIO_EVAL_BACKEND_URL"
TOKEN_ENV = "CURIO_EVAL_TOKEN"
TIER_ENV = "CURIO_EVAL_TIERS"


@pytest.fixture(scope="module")
def live_client():
    try:
        # Two opt-ins on purpose: the pytest flag says "run this test", the
        # environment flag says "yes, call a real model". Neither implies the
        # other, and a missing one is a skip with its reason, not an error.
        live_mod.require_opt_in()
    except live_mod.LiveEvalRefused as refusal:
        pytest.skip(str(refusal))
    token = os.environ.get(TOKEN_ENV)
    if not token:
        pytest.skip(
            f"{TOKEN_ENV} is not set: the live evaluation needs a bearer token "
            "for an account whose AI Settings name a provider and a model"
        )
    base_url = os.environ.get(BACKEND_ENV, "http://localhost:5002")
    client = live_mod.HttpClient(base_url=base_url, token=token)
    try:
        client.json("/api/auth/me")
    except live_mod.LiveEvalRefused as refusal:
        pytest.skip(str(refusal))
    return client


def _fixtures(tiers: tuple) -> list:
    return [
        fixture for fixture in (load_fixture(path) for path in fixture_paths())
        if fixture.tier in tiers
    ]


def test_a_live_run_produces_a_trustworthy_report(live_client, tmp_path):
    tiers = tuple(
        tier.strip() for tier in os.environ.get(TIER_ENV, "T0").split(",") if tier.strip()
    )
    fixtures = _fixtures(tiers)
    assert fixtures, f"no fixtures in tiers {tiers}"
    examples = {
        fixture.fixture_id: json.loads(
            fixture.source_path.read_text(encoding="utf-8")
        )
        for fixture in fixtures
    }
    report = RunReport(run_id=new_run_id("eval-test"), mode="live")
    run = live_mod.LiveRun(
        client=live_client,
        templates=template_index(),
        report=report,
        tiers=tiers,
    )
    run.run(fixtures, examples=examples)

    payload = report.as_dict()
    assert payload["isReleaseGate"] is False
    assert payload["kind"] == "evaluation-report"
    assert payload["provider"]["model"], "the report must name the model that answered"
    assert len(payload["attempts"]) == len(fixtures)

    for record in report.attempts:
        assert record.latency_ms >= 0
        assert record.digests.prompt_sha256
        assert record.digests.fixture_sha256
        # Which instruction bytes answered: the same prompt against a changed
        # instruction is a different run (dev/95 pins those bytes).
        assert record.digests.agent_instruction_sha256
        assert record.score is not None or record.error, (
            f"{record.fixture_id}: neither a score nor an error was recorded"
        )

    # A written report a person can read, and no key in it.
    json_path, markdown_path = report.write(tmp_path)
    blob = json_path.read_text(encoding="utf-8")
    token = os.environ[TOKEN_ENV]
    assert token not in blob, "the account token reached the report"
    assert "not a release gate" in markdown_path.read_text(encoding="utf-8")

    # The scores are the OUTPUT, printed for a person to read rather than
    # asserted: a suite that failed on a model's bad day would be switched off.
    print(markdown_path.read_text(encoding="utf-8"))
