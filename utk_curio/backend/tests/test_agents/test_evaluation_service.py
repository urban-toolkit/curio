"""dev/123 — an evaluation run through the product, deterministically.

The scripted provider stands in for the model; everything else is the real
thing: the real project creation, the real install with its required closure,
the real runtime turn, the real apply endpoint, the real Solve, the real
comparator. So what these tests prove is the ORCHESTRATION — isolation, the
closure, the narrow automated approval, the phases, the record, and the
refusals — which is exactly the part a live run cannot check for you.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.agents import agent_jobs, testing_provider
from utk_curio.backend.app.agents.evaluation import authorization as auth_mod
from utk_curio.backend.app.agents.evaluation import oracle
from utk_curio.backend.app.agents.evaluation import records as records_mod
from utk_curio.backend.app.agents.evaluation import service as evaluation_service
from utk_curio.backend.app.agents.evaluation.canonical import canonical_graph_from_spec
from utk_curio.backend.app.agents.evaluation.fixtures import FIXTURE_ROOT, load_fixture
from utk_curio.backend.tests.test_agents.test_reconstruction_canonical import TEMPLATES

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURE = load_fixture(FIXTURE_ROOT / "01-vega-lite-chained-transforms.prompt.json")
API_KEY = "sk-evaluation-lane-secret-0002"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def account(client, user_and_token, tmp_curio):
    user, token = user_and_token
    response = client.patch(
        "/api/auth/me",
        json={
            "llm_api_type": "testing", "llm_model": "scripted",
            "llm_api_key": API_KEY, "llm_base_url": "http://scripted.example.com/v1",
        },
        headers=_auth(token),
    )
    assert response.status_code == 200, response.get_json()
    from utk_curio.backend.app.projects.services import _user_dir_key

    agent_jobs.reset_registry()
    yield {"user": user, "token": token, "key": _user_dir_key(user)}
    agent_jobs.reset_registry()


def _script_the_model(monkeypatch, fixture=FIXTURE):
    """A model that answers with a correct plan, then the nodes' code.

    The oracle again — not because a live model would, but because a
    deterministic run has to end in a score, and the score is what the phases
    are carrying.
    """
    from utk_curio.backend.app.agents import services as services_mod

    example = json.loads(fixture.source_path.read_text(encoding="utf-8"))
    graph = canonical_graph_from_spec(example, templates=TEMPLATES)
    plan = oracle.plan_for(
        fixture.expected, intents=fixture.intents,
        source_hints=oracle.source_hints_for(
            fixture.expected, example=example, origins=graph.origins,
            paths=fixture.required.get("paths") or (),
        ),
        synthetic_refs=oracle.synthetic_refs_for(
            fixture.expected, example=example, origins=graph.origins
        ),
    )
    contents = oracle.content_replies(
        fixture.expected, example=example, origins=graph.origins,
        only_executable=False,
    )
    calls = []

    def _fake_run(config, messages, **kwargs):
        if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
            return "Evaluation"
        calls.append(messages)
        if len(calls) == 1:
            return plan.as_reply()
        blob = str(messages[-1].get("content") or "")
        start = blob.find("{")
        intent = ""
        if start >= 0:
            try:
                inputs, _ = json.JSONDecoder().raw_decode(blob[start:])
                intent = str(inputs.get("intent") or "")
            except ValueError:
                intent = ""
        for ref in sorted(contents, key=len, reverse=True):
            if ref in intent:
                return contents[ref]
        return "# no content for this node\nreturn None"

    monkeypatch.setattr(
        "utk_curio.backend.app.agents.services.run_chat_completion", _fake_run
    )
    monkeypatch.setattr(
        "utk_curio.backend.app.execution.runner._http_exec",
        lambda endpoint, payload: {
            "stdout": [], "stderr": "",
            "output": {"path": "art-1", "dataType": "geodataframe"},
        },
    )
    return calls


def _run(client, account, fixture_id=FIXTURE.fixture_id):
    """Start a run and drain its job, so the test sees a finished record."""
    response = client.post(
        "/api/agents/evaluation/runs",
        json={"fixtureId": fixture_id}, headers=_auth(account["token"]),
    )
    assert response.status_code == 201, response.get_json()
    run_id = response.get_json()["runId"]
    job = agent_jobs.get_job(run_id)
    assert job is not None
    job.thread.join(timeout=120)
    return records_mod.read(account["key"], run_id)


class TestReadiness:
    def test_a_configured_account_is_ready_and_names_its_model(
        self, client, account
    ):
        payload = client.get(
            "/api/agents/evaluation/readiness", headers=_auth(account["token"])
        ).get_json()
        assert payload["configured"] is True
        assert payload["provider"]["model"] == "scripted"
        assert payload["provider"]["baseUrlHost"] == "scripted.example.com"
        assert payload["source"] == "account"
        assert API_KEY not in json.dumps(payload)

    def test_a_model_from_the_start_command_counts_as_configured(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The owner's requirement: a model configured by `curio.py start
        --llm-model` is as real as one typed into AI Settings, so the panel
        must not tell an operator who passed the flag that they configured
        nothing."""
        from utk_curio.backend.app.agents import provider_config

        user, token = user_and_token
        for attribute in ("llm_api_type", "llm_base_url", "llm_api_key", "llm_model"):
            setattr(user, attribute, None)
        monkeypatch.setattr(provider_config, "DEFAULT_LLM_API_TYPE", "openai_compatible")
        monkeypatch.setattr(
            provider_config, "DEFAULT_LLM_BASE_URL", "https://sage200.example.edu/v1"
        )
        monkeypatch.setattr(provider_config, "DEFAULT_LLM_API_KEY", "sk-deployment")
        monkeypatch.setattr(provider_config, "DEFAULT_LLM_MODEL", "gemma4")
        from utk_curio.backend import config as backend_config

        monkeypatch.setattr(backend_config, "DEFAULT_LLM_API_TYPE", "openai_compatible")
        monkeypatch.setattr(
            backend_config, "DEFAULT_LLM_BASE_URL", "https://sage200.example.edu/v1"
        )
        monkeypatch.setattr(backend_config, "DEFAULT_LLM_API_KEY", "sk-deployment")
        monkeypatch.setattr(backend_config, "DEFAULT_LLM_MODEL", "gemma4")

        payload = evaluation_service.readiness(user)
        assert payload["configured"] is True
        assert payload["source"] == "deployment"
        assert payload["provider"]["model"] == "gemma4"
        assert payload["deployment"]["baseUrlHost"] == "sage200.example.edu"
        assert payload["deployment"]["hasApiKey"] is True
        assert "sk-deployment" not in json.dumps(payload)

    def test_an_unconfigured_account_is_blocked_with_an_actionable_reason(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        from utk_curio.backend.app.agents import provider_config

        user, _token = user_and_token
        for attribute in ("llm_api_type", "llm_base_url", "llm_api_key", "llm_model"):
            setattr(user, attribute, None)
        for name in (
            "DEFAULT_LLM_API_TYPE", "DEFAULT_LLM_BASE_URL",
            "DEFAULT_LLM_API_KEY", "DEFAULT_LLM_MODEL",
        ):
            monkeypatch.setattr(provider_config, name, "")
        payload = evaluation_service.readiness(user)
        assert payload["configured"] is False
        assert payload["source"] == "none"
        assert payload["reason"]


class TestFixtureSelectionAndReview:
    def test_every_fixture_is_offered_with_what_a_person_needs(self, client, account):
        payload = client.get(
            "/api/agents/evaluation/fixtures", headers=_auth(account["token"])
        ).get_json()
        assert len(payload["fixtures"]) == 31
        one = next(
            f for f in payload["fixtures"] if f["fixtureId"] == FIXTURE.fixture_id
        )
        assert one["prompt"] == FIXTURE.prompt
        assert one["tier"] and one["split"] and one["reviewStatus"]
        assert one["expectedNodes"] > 0

    def test_no_route_ever_returns_the_expected_graph(self, client, account):
        """The reference stays server-side: a client that could ask for it is
        one network hop from putting it in a prompt."""
        payload = client.get(
            "/api/agents/evaluation/fixtures", headers=_auth(account["token"])
        ).get_json()
        blob = json.dumps(payload)
        assert "expected" not in payload["fixtures"][0]
        for node in FIXTURE.expected["nodes"]:
            assert node["ref"] not in blob or node["ref"] in FIXTURE.prompt

    def test_a_prompt_can_be_approved_from_the_panel(self, client, account, monkeypatch):
        """The owner's ask: approving belongs in the interface, because the one
        hand-edit of the JSON produced a status the schema rejected."""
        import shutil

        target = FIXTURE_ROOT / "dataflows" / "Vega.prompt.json"
        backup = json.loads(target.read_text(encoding="utf-8"))
        try:
            response = client.post(
                f"/api/agents/evaluation/fixtures/Vega/review",
                json={"status": "approved"}, headers=_auth(account["token"]),
            )
            assert response.status_code == 200, response.get_json()
            payload = response.get_json()
            assert payload["status"] == "approved"
            assert payload["reviewedBy"]
            assert payload["reviewedAt"]
            on_disk = json.loads(target.read_text(encoding="utf-8"))
            assert on_disk["review"]["status"] == "approved"
            # Only the review block moved.
            assert on_disk["expected"] == backup["expected"]
            assert on_disk["prompt"] == backup["prompt"]
            assert on_disk["split"] == backup["split"]

            # ...and it can be taken back, which is why a typo is no longer
            # something to fix by hand.
            back = client.post(
                f"/api/agents/evaluation/fixtures/Vega/review",
                json={"status": "pending-owner-review"},
                headers=_auth(account["token"]),
            ).get_json()
            assert back["status"] == "pending-owner-review"
            assert back["reviewedBy"] is None
        finally:
            target.write_text(json.dumps(backup, indent=2) + "\n", encoding="utf-8")

    def test_an_invalid_status_is_refused(self, client, account):
        response = client.post(
            "/api/agents/evaluation/fixtures/Vega/review",
            json={"status": "papproved"}, headers=_auth(account["token"]),
        )
        assert response.status_code == 400
        assert "may be set to" in response.get_json()["error"]

    def test_an_unknown_fixture_is_a_404(self, client, account):
        response = client.post(
            "/api/agents/evaluation/fixtures/nope/review",
            json={"status": "approved"}, headers=_auth(account["token"]),
        )
        assert response.status_code == 404


class TestTheRun:
    def test_a_run_walks_its_phases_and_scores(self, client, account, monkeypatch):
        _script_the_model(monkeypatch)
        record = _run(client, account)
        phases = [e["phase"] for e in record.events if e["kind"] == "phase"]
        assert phases == [
            "preparing", "project", "provisioning", "installing",
            "prompting", "reviewing", "solving", "scoring", "done",
        ], phases
        assert record.phase == "done"
        assert record.score["total"] == pytest.approx(1.0), record.comparison
        assert record.latency_ms >= 0

    def test_the_run_creates_a_new_project_and_touches_no_other(
        self, client, account, monkeypatch
    ):
        body = {
            "name": "mine", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
            "outputs": [],
        }
        mine = client.post(
            "/api/projects", json=body, headers=_auth(account["token"])
        ).get_json()["id"]
        before = client.get(
            f"/api/projects/{mine}", headers=_auth(account["token"])
        ).get_json()["spec"]

        _script_the_model(monkeypatch)
        record = _run(client, account)

        assert record.project_id and record.project_id != mine
        after = client.get(
            f"/api/projects/{mine}", headers=_auth(account["token"])
        ).get_json()["spec"]
        assert after == before, "the caller's own project was modified"

    def test_the_project_is_marked_named_and_kept_for_inspection(
        self, client, account, monkeypatch
    ):
        _script_the_model(monkeypatch)
        record = _run(client, account)
        detail = client.get(
            f"/api/projects/{record.project_id}", headers=_auth(account["token"])
        ).get_json()
        listed = client.get("/api/projects", headers=_auth(account["token"])).get_json()
        names = [
            row.get("name") for row in (
                listed if isinstance(listed, list) else listed.get("projects") or []
            )
        ]
        assert any(FIXTURE.fixture_id in str(name) for name in names), names
        marker = auth_mod.marker_of(detail["spec"])
        assert marker is not None
        assert marker.run_id == record.run_id
        # The graph is the evidence, so it stays — and it has to be a graph the
        # CANVAS can draw, which is what "displayed in the project" means. The
        # loader needs both arrays (``ProjectLoader.hasLoadableDataflow``) and
        # each node needs the id, type and position it renders from; an edge
        # whose endpoint is not a node in the same spec draws nothing.
        dataflow = detail["spec"]["dataflow"]
        assert isinstance(dataflow["nodes"], list) and dataflow["nodes"]
        assert isinstance(dataflow["edges"], list) and dataflow["edges"]
        node_ids = set()
        for node in dataflow["nodes"]:
            assert node.get("id"), node
            assert node.get("type"), node
            assert isinstance(node.get("x"), (int, float)), node
            assert isinstance(node.get("y"), (int, float)), node
            node_ids.add(node["id"])
        for edge in dataflow["edges"]:
            assert edge["source"] in node_ids, edge
            assert edge["target"] in node_ids, edge
        # The identity fields the canvas title and provenance keys read.
        assert isinstance(dataflow.get("name"), str) and dataflow["name"]

    def test_the_agent_arrives_with_its_required_closure(
        self, client, account, monkeypatch
    ):
        """dev/106 (DEC-068): installing the Dataflow Builder installs what it
        requires, through the normal flow rather than a shortcut."""
        _script_the_model(monkeypatch)
        record = _run(client, account)
        installed = {
            row["dirName"] for row in client.get(
                f"/api/agents/projects/{record.project_id}",
                headers=_auth(account["token"]),
            ).get_json()["agents"]
        }
        assert "agent.dataflow-builder@1.0.0" in installed
        assert "agent.node-content-builder@1.0.0" in installed

    def test_the_prompt_is_all_the_model_received(self, client, account, monkeypatch):
        calls = _script_the_model(monkeypatch)
        _run(client, account)
        planning_turn = json.dumps(calls[0])
        assert FIXTURE.prompt in planning_turn
        example = json.loads(FIXTURE.source_path.read_text(encoding="utf-8"))
        for node in example["dataflow"]["nodes"]:
            assert node["id"] not in planning_turn
            for line in (node.get("content") or "").splitlines():
                if len(line.strip()) >= 25:
                    assert line.strip() not in planning_turn
        assert json.dumps(FIXTURE.expected["edges"]) not in planning_turn

    def test_every_apply_is_authorized_and_recorded(
        self, client, account, monkeypatch
    ):
        _script_the_model(monkeypatch)
        record = _run(client, account)
        applied = [e for e in record.events if e["kind"] == "auto-applied"]
        assert applied, record.events
        assert all(e["runId"] == record.run_id for e in applied)
        assert {e["tool"] for e in applied} == {"dataflow.plan.write"}
        assert record.applied[0]["status"] == "applied"

    def test_the_record_carries_what_reproduces_a_run_and_no_key(
        self, client, account, monkeypatch
    ):
        _script_the_model(monkeypatch)
        record = _run(client, account)
        payload = record.as_dict()
        assert payload["fixtureId"] == FIXTURE.fixture_id
        assert payload["provider"]["model"] == "scripted"
        assert payload["digests"]["fixtureSha256"]
        assert payload["digests"]["promptSha256"]
        assert payload["digests"]["agentInstructionSha256"]
        assert payload["digests"]["rosterDigest"]
        assert payload["projectId"] and payload["attachmentId"]
        assert payload["comparison"] and payload["score"]
        blob = json.dumps(payload)
        assert API_KEY not in blob
        on_disk = records_mod.record_path(account["key"], record.run_id).read_text()
        assert API_KEY not in on_disk

    def test_the_score_matches_what_the_shared_scorer_computes(
        self, client, account, monkeypatch
    ):
        """The service must not have its own idea of correct: the same spec
        scored through ``attempt.score_attempt`` gives the same number."""
        from utk_curio.backend.app.agents.evaluation import attempt as attempt_mod
        from utk_curio.backend.app.projects import storage as projects_storage

        _script_the_model(monkeypatch)
        record = _run(client, account)
        spec = projects_storage.read_spec(account["key"], record.project_id)
        example = json.loads(FIXTURE.source_path.read_text(encoding="utf-8"))
        again = attempt_mod.score_attempt(
            FIXTURE, actual_spec=spec, templates=evaluation_service.template_index(),
            example=example,
        )
        assert again.score.total == pytest.approx(record.score["total"])

    def test_a_proposal_the_policy_declines_is_recorded_as_pending(
        self, client, account, monkeypatch
    ):
        """A content write is a decision a person makes; an unattended run
        leaves it and says so."""
        from utk_curio.backend.app.agents import services as services_mod

        calls = []

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Evaluation"
            calls.append(messages)
            # A node.create request: granted to the Dataflow Builder, and
            # deliberately not a kind an evaluation applies.
            return (
                "Here is a node.\n```curio.v1\n"
                + json.dumps({"toolRequest": {"tool": "node.create", "params": {
                    "nodeType": "curio.builtin/computation-analysis",
                    "content": "return 1",
                }}})
                + "\n```"
            )

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _fake_run
        )
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec",
            lambda endpoint, payload: {
                "stdout": [], "stderr": "",
                "output": {"path": "a", "dataType": "dataframe"},
            },
        )
        record = _run(client, account)
        pending = [e for e in record.events if e["kind"] == "left-pending"]
        assert pending, record.events
        assert "a person makes" in pending[0]["reason"]
        assert record.phase == "done"

    def test_a_refusing_model_is_scored_not_crashed_on(
        self, client, account, monkeypatch
    ):
        from utk_curio.backend.app.agents import services as services_mod

        def _prose(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Evaluation"
            return "I cannot build that with the templates available."

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _prose
        )
        record = _run(client, account)
        assert record.phase == "done"
        assert "refused" in record.score["categories"]
        assert record.score["total"] < 1.0

    def test_a_provider_failure_records_where_it_stopped(
        self, client, account, monkeypatch
    ):
        from utk_curio.backend.app.agents import services as services_mod

        def _boom(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Evaluation"
            raise RuntimeError("the endpoint went away")

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _boom
        )
        record = _run(client, account)
        assert record.phase in ("failed", "done")
        assert record.failures or record.score
        if record.failures:
            assert record.failures[0]["phase"] in ("prompting", "reviewing")

    def test_only_one_run_at_a_time(self, client, account, monkeypatch):
        _script_the_model(monkeypatch)
        first = client.post(
            "/api/agents/evaluation/runs", json={"fixtureId": FIXTURE.fixture_id},
            headers=_auth(account["token"]),
        )
        assert first.status_code == 201
        second = client.post(
            "/api/agents/evaluation/runs", json={"fixtureId": FIXTURE.fixture_id},
            headers=_auth(account["token"]),
        )
        agent_jobs.get_job(first.get_json()["runId"]).thread.join(timeout=120)
        assert second.status_code == 409
        assert "already running" in second.get_json()["error"]

    def test_a_cancel_is_recorded_and_stops_the_run(self, client, account, monkeypatch):
        # A slow model, so the cancel lands mid-run rather than after it: with
        # the instant scripted provider the run finishes first and the test
        # would assert nothing.
        import time as _time

        from utk_curio.backend.app.agents import services as services_mod

        def _slow(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Evaluation"
            _time.sleep(1.5)
            return "I need more time."

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _slow
        )
        started = client.post(
            "/api/agents/evaluation/runs", json={"fixtureId": FIXTURE.fixture_id},
            headers=_auth(account["token"]),
        ).get_json()
        cancelled = client.post(
            f"/api/agents/evaluation/runs/{started['runId']}/cancel",
            headers=_auth(account["token"]),
        )
        assert cancelled.status_code == 200
        assert cancelled.get_json()["cancelRequested"] is True
        agent_jobs.get_job(started["runId"]).thread.join(timeout=120)
        record = records_mod.read(account["key"], started["runId"])
        assert record.terminal
        assert "cancel-requested" in [e["kind"] for e in record.events]

    def test_an_unknown_run_is_a_404_and_a_malformed_id_a_400(self, client, account):
        assert client.get(
            "/api/agents/evaluation/runs/eval-20260101T000000Z-deadbeef",
            headers=_auth(account["token"]),
        ).status_code == 404
        assert client.get(
            "/api/agents/evaluation/runs/not-a-run-id",
            headers=_auth(account["token"]),
        ).status_code == 400

    def test_the_listing_names_the_run(self, client, account, monkeypatch):
        _script_the_model(monkeypatch)
        record = _run(client, account)
        listing = client.get(
            "/api/agents/evaluation/runs", headers=_auth(account["token"])
        ).get_json()
        assert [r["runId"] for r in listing["runs"]] == [record.run_id]
        assert listing["inFlight"] is None

    def test_an_unconfigured_account_cannot_start_a_run(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        from utk_curio.backend.app.agents import provider_config

        user, token = user_and_token
        for name in (
            "DEFAULT_LLM_API_TYPE", "DEFAULT_LLM_BASE_URL",
            "DEFAULT_LLM_API_KEY", "DEFAULT_LLM_MODEL",
        ):
            monkeypatch.setattr(provider_config, name, "")
        response = client.post(
            "/api/agents/evaluation/runs", json={"fixtureId": FIXTURE.fixture_id},
            headers=_auth(token),
        )
        assert response.status_code == 400
        assert "AI Settings" in response.get_json()["error"]
        from utk_curio.backend.app.projects.services import _user_dir_key

        assert records_mod.list_records(_user_dir_key(user)) == []


class TestTheAutomatedApprovalIsNarrow:
    def test_it_refuses_in_an_ordinary_project(self):
        """The assertion that keeps the grant honest."""
        with pytest.raises(auth_mod.AutoApplyRefused) as refusal:
            auth_mod.assert_may_auto_apply(
                {"dataflow": {"nodes": []}}, run_id="eval-1",
                proposal={"tool": "dataflow.plan.write"},
            )
        assert "not an evaluation project" in str(refusal.value)

    def test_it_refuses_another_runs_project(self):
        spec = auth_mod.mark_spec({}, auth_mod.new_marker("eval-old", "01"))
        with pytest.raises(auth_mod.AutoApplyRefused) as refusal:
            auth_mod.assert_may_auto_apply(
                spec, run_id="eval-new", proposal={"tool": "dataflow.plan.write"}
            )
        assert "not a standing permission" in str(refusal.value)

    @pytest.mark.parametrize(
        "tool", ["node.content.write", "node.create", "package.draft.apply",
                 "node.template.create"],
    )
    def test_it_refuses_a_kind_no_unattended_run_may_apply(self, tool):
        spec = auth_mod.mark_spec({}, auth_mod.new_marker("eval-1", "01"))
        with pytest.raises(auth_mod.AutoApplyRefused):
            auth_mod.assert_may_auto_apply(
                spec, run_id="eval-1", proposal={"tool": tool}
            )

    def test_it_allows_exactly_the_policy_kinds_in_its_own_project(self):
        spec = auth_mod.mark_spec({}, auth_mod.new_marker("eval-1", "01"))
        from utk_curio.backend.app.agents.evaluation.policy import APPLICABLE_TOOLS

        for tool in APPLICABLE_TOOLS:
            auth_mod.assert_may_auto_apply(
                spec, run_id="eval-1", proposal={"tool": tool}
            )

    def test_no_agents_review_policy_was_widened(self):
        """Nothing global changed: the Dataflow Builder still reviews before
        applying, everywhere."""
        from utk_curio.backend.app.agents import builtin

        spec = next(
            s for s in builtin.BUILTIN_AGENTS
            if s.agent_id == "agent.dataflow-builder"
        )
        assert spec.review_policy == "review-before-apply"


class TestTheTranscriptCarriesTheEvaluation:
    """The panel keeps the report; the CHAT has to carry it too.

    A person who opens the generated project looks at the Dataflow Builder's
    conversation to understand what happened, and production's own turns stop
    at the Solve card — nothing there said what the run was or how it scored.
    """

    def _turns(self, client, account, record):
        session = client.get(
            f"/api/agents/projects/{record.project_id}/attachments/"
            f"{record.attachment_id}/session",
            headers=_auth(account["token"]),
        )
        assert session.status_code == 200, session.get_json()
        return session.get_json()["turns"]

    def _cards(self, turns, title):
        return [
            part
            for turn in turns
            for part in (turn.get("content") or [])
            if isinstance(part, dict)
            and part.get("type") == "card"
            and part.get("title") == title
        ]

    def test_the_report_lands_in_the_chat_after_the_run(
        self, client, account, monkeypatch
    ):
        _script_the_model(monkeypatch)
        record = _run(client, account)
        turns = self._turns(client, account, record)
        cards = self._cards(turns, "Evaluation report")
        assert len(cards) == 1, [t.get("text") for t in turns]
        lines = " ".join(cards[0]["lines"])
        assert "Overall accuracy 100%" in lines
        assert "Templates: 100%" in lines
        assert "no model graded this" in lines
        assert "stayed on the server" in lines
        # The story reads in order: the prompt, the plan, the apply, the Solve,
        # then the verdict.
        assert turns[0]["role"] == "user"
        assert turns[-1] is turns[-1] and self._cards([turns[-1]], "Evaluation report")

    def test_the_run_still_scores_the_same_and_the_project_is_reachable(
        self, client, account, monkeypatch
    ):
        """The transcript is an addition, not a change to what is measured."""
        _script_the_model(monkeypatch)
        record = _run(client, account)
        assert record.score["total"] == pytest.approx(1.0)
        detail = client.get(
            f"/api/projects/{record.project_id}", headers=_auth(account["token"])
        ).get_json()
        assert detail["spec"]["dataflow"]["nodes"]

    def test_nothing_is_appended_before_the_model_answers(
        self, client, account, monkeypatch
    ):
        """The session is the model's context (``run_attachment``), so a turn
        written ahead of the prompt would change what is being measured."""
        calls = _script_the_model(monkeypatch)
        _run(client, account)
        sent = json.dumps(calls)
        assert "Evaluation report" not in sent
        assert "Overall accuracy" not in sent

    def test_the_report_carries_no_piece_of_the_reference(
        self, client, account, monkeypatch
    ):
        """Aggregates and category names, never the example itself: these turns
        become context for any later conversation in the kept project."""
        _script_the_model(monkeypatch)
        record = _run(client, account)
        lines = " ".join(
            self._cards(self._turns(client, account, record), "Evaluation report")[0][
                "lines"
            ]
        )
        assert str(FIXTURE.data["source"]["path"]) not in lines
        example = json.loads(FIXTURE.source_path.read_text(encoding="utf-8"))
        for node in (example.get("dataflow") or {}).get("nodes") or []:
            content = str(node.get("content") or "").strip()
            if len(content) > 40:
                assert content[:40] not in lines

    def test_a_cancelled_run_says_so_in_the_chat(
        self, client, account, monkeypatch
    ):
        import time as _time

        from utk_curio.backend.app.agents import services as services_mod

        def _slow(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Evaluation"
            _time.sleep(1.5)
            return "I need more time."

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _slow
        )
        started = client.post(
            "/api/agents/evaluation/runs", json={"fixtureId": FIXTURE.fixture_id},
            headers=_auth(account["token"]),
        ).get_json()
        # Cancel once the agent is attached — before that there is no transcript
        # to post into, and the assertion would pass by being skipped. The slow
        # model holds the run in ``prompting`` while this waits.
        for _ in range(200):
            pending = records_mod.read(account["key"], started["runId"])
            if pending and pending.attachment_id:
                break
            _time.sleep(0.05)
        assert pending and pending.attachment_id, "the run never got as far as attaching"
        client.post(
            f"/api/agents/evaluation/runs/{started['runId']}/cancel",
            headers=_auth(account["token"]),
        )
        agent_jobs.get_job(started["runId"]).thread.join(timeout=120)
        record = records_mod.read(account["key"], started["runId"])
        assert record.phase == "cancelled", record.phase
        cards = self._cards(
            self._turns(client, account, record), "Evaluation stopped"
        )
        assert len(cards) == 1
        assert "cancelled" in " ".join(cards[0]["lines"]).lower()
        assert "yours to keep or delete" in " ".join(cards[0]["lines"])


class TestTheRunsGraphSurvivesAClientSave:
    """The defect this class exists for: a finished run with a score and an
    EMPTY canvas.

    A canvas save is a whole-spec ``PUT`` carrying the browser's live nodes and
    no revision basis. A project opened before the plan was applied therefore
    holds an empty graph, and its next save — an auto-save is enough — wrote
    that emptiness over the run's six nodes.
    """

    def _mark(self, client, account, *, run_id, phase, nodes):
        """A project marked for a run in *phase*, holding *nodes*."""
        from utk_curio.backend.app.agents.evaluation import records as rec_mod

        record = rec_mod.EvaluationRecord(
            run_id=run_id, fixture_id=FIXTURE.fixture_id,
        )
        record.enter(phase)
        rec_mod.write(account["key"], record)
        spec = auth_mod.mark_spec(
            {"dataflow": {"nodes": list(nodes), "edges": [], "packages": []}},
            auth_mod.new_marker(run_id, FIXTURE.fixture_id),
        )
        created = client.post(
            "/api/projects",
            json={"name": "Evaluation · test", "spec": spec, "outputs": []},
            headers=_auth(account["token"]),
        )
        assert created.status_code in (200, 201), created.get_json()
        return created.get_json()["id"]

    def _put(self, client, account, project_id, nodes):
        return client.put(
            f"/api/projects/{project_id}",
            json={
                "spec": {"dataflow": {"nodes": list(nodes), "edges": []}},
                "name": "Evaluation · test",
            },
            headers=_auth(account["token"]),
        )

    def _nodes(self, client, account, project_id):
        return client.get(
            f"/api/projects/{project_id}", headers=_auth(account["token"])
        ).get_json()["spec"]["dataflow"]["nodes"]

    def test_a_stale_canvas_cannot_empty_a_finished_runs_dataflow(
        self, client, account
    ):
        node = {"id": "n1", "type": "curio.builtin/data-loading", "x": 0, "y": 0}
        project_id = self._mark(
            client, account, run_id="eval-20260101T000000Z-aaaaaaaa",
            phase="done", nodes=[node],
        )
        refused = self._put(client, account, project_id, [])
        assert refused.status_code == 409, refused.get_json()
        assert "no nodes at all" in refused.get_json()["error"]
        assert "reload the project" in refused.get_json()["error"]
        assert self._nodes(client, account, project_id) == [node]

    def test_a_real_edit_to_a_finished_evaluation_project_still_saves(
        self, client, account
    ):
        """The project is the user's to change — only emptying it is refused."""
        node = {"id": "n1", "type": "curio.builtin/data-loading", "x": 0, "y": 0}
        extra = {"id": "n2", "type": "curio.builtin/data-transformation", "x": 9, "y": 9}
        project_id = self._mark(
            client, account, run_id="eval-20260101T000000Z-bbbbbbbb",
            phase="done", nodes=[node],
        )
        saved = self._put(client, account, project_id, [node, extra])
        assert saved.status_code == 200, saved.get_json()
        assert len(self._nodes(client, account, project_id)) == 2

    def test_a_save_is_refused_while_the_run_is_still_writing(
        self, client, account
    ):
        project_id = self._mark(
            client, account, run_id="eval-20260101T000000Z-cccccccc",
            phase="solving", nodes=[],
        )
        refused = self._put(
            client, account, project_id,
            [{"id": "mine", "type": "curio.builtin/data-loading", "x": 0, "y": 0}],
        )
        assert refused.status_code == 409, refused.get_json()
        assert "still building this project" in refused.get_json()["error"]

    def test_an_ordinary_project_can_still_be_emptied(self, client, account):
        """Nothing global changed: this guard knows only evaluation projects."""
        created = client.post(
            "/api/projects",
            json={
                "name": "mine",
                "spec": {"dataflow": {
                    "nodes": [{"id": "n1", "type": "curio.builtin/data-loading",
                               "x": 0, "y": 0}],
                    "edges": [], "packages": [],
                }},
                "outputs": [],
            },
            headers=_auth(account["token"]),
        ).get_json()
        emptied = self._put(client, account, created["id"], [])
        assert emptied.status_code == 200, emptied.get_json()
        assert self._nodes(client, account, created["id"]) == []
