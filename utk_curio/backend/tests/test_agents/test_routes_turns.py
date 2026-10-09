"""Integration tests for the /api/agents run routes (routes/turns.py).

What a run or a streamed run does: its replies, records, tool rounds and
the proposals it mints."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.packages import service as packages_service
from utk_curio.backend.app.agents.repositories import ledger
from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.projects.services import _user_dir_key

from utk_curio.backend.tests._support.agent_routes import (
    _auth,
    db_user,
)

# Imported for their helpers. conftest.py runs each class only in the
# file that defines it, never again here.
from utk_curio.backend.tests.test_agents.test_routes_proposals import (
    TestDataflowPlanMint,
    TestDestructiveReplan,
    TestNodeCreate,
)


class TestRun:
    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        # Chat is dual-compatible (node + canvas), so a canvas attachment is valid.
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def test_run_dispatches_instruction_as_system(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents.domain import builtin

        # A first run also fires the post-reply title call (memo dev/25), so
        # capture every call and assert on the conversation run (the first).
        calls = []

        def _fake_run(config, messages, **kwargs):
            calls.append(messages)
            return "hello from the model"

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "explain this node"},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["reply"] == "hello from the model"
        msgs = calls[0]
        assert msgs[0]["role"] == "system"
        # dev/06 parity: the system turn composes the preamble + instruction,
        # exactly as every legacy call site did.
        preamble = builtin.read_prompt_text("agent.chat-agent@1.0.0", "system")
        instruction = builtin.read_instruction_text("agent.chat-agent@1.0.0")
        from utk_curio.backend.app.agents.domain import content as content_mod

        # dev/39: the runtime-owned structured-tail instruction composes last,
        # followed by the read tools the chat agent is granted.
        assert msgs[0]["content"].startswith(
            f"{preamble}\n\n{instruction}\n\n{content_mod.TAIL_INSTRUCTION}"
        )
        assert "- dataflow.read:" in msgs[0]["content"]
        assert msgs[1] == {"role": "user", "content": "explain this node"}

    def test_run_unknown_attachment_404(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/nope/run",
            json={"message": "hi"},
            headers=_auth(token),
        )
        assert r.status_code == 404

    def test_run_empty_message_400(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "   "},
            headers=_auth(token),
        )
        assert r.status_code == 400


class TestStreamRun:
    """SSE run path (memo dev/22): deltas → done, persistence parity with run."""

    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def _events(self, resp):
        out = []
        for block in resp.get_data(as_text=True).strip().split("\n\n"):
            lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
            out.append((lines["event"], json.loads(lines["data"])))
        return out

    def test_stream_deltas_then_done_and_persists_once(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _fake_stream(config, messages, **kwargs):
            yield "hel"
            yield "lo"

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _fake_stream
        )
        # The first stream run fires the post-reply title call (memo dev/25);
        # stub the blocking port so it never reaches a real provider.
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda c, m, **kw: "Stream Title",
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 200
        assert r.mimetype == "text/event-stream"
        events = self._events(r)
        # The execution handshake precedes the first delta (memo dev/37) and
        # done carries the enriched typed payload.
        assert events[0][0] == "execution"
        execution_id = events[0][1]["executionId"]
        assert execution_id
        assert events[1:3] == [("delta", {"text": "hel"}), ("delta", {"text": "lo"})]
        # No provider-reported usage → no interim usage event (dev/80): the
        # done frame follows the deltas directly, now carrying durationMs.
        done_name, done_payload = events[3]
        assert done_name == "done"
        assert done_payload.pop("durationMs") >= 0
        assert done_payload == {
            "reply": "hello", "executionId": execution_id, "usage": None, "content": [],
        }
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert [(t["role"], t["text"]) for t in turns] == [("user", "q1"), ("agent", "hello")]

    def test_stream_provider_error_emits_error_and_persists_marker(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _flaky(config, messages, **kwargs):
            yield "par"
            raise RuntimeError("boom")

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _flaky
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        events = self._events(r)
        assert events[0][0] == "execution"
        assert events[1] == ("delta", {"text": "par"})
        assert events[-1][0] == "error"
        assert "boom" in events[-1][1]["error"]
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        # The partial text is NOT persisted — user turn + display-only marker.
        assert [(t["role"], bool(t.get("error"))) for t in turns] == [("user", False), ("agent", True)]
        assert "boom" in turns[1]["text"]

    def test_stream_validation_errors_are_plain_json(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/ghost/run/stream",
            json={"message": "hi"}, headers=_auth(token),
        )
        assert r.status_code == 404
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "   "}, headers=_auth(token),
        )
        assert r.status_code == 400

    def test_stream_context_includes_prior_session(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = []

        def _fake_stream(config, messages, **kwargs):
            calls.append(messages)
            yield "ok"

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _fake_stream
        )
        # Stub the blocking port: the first run's title call must not reach a
        # real provider (memo dev/25).
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda c, m, **kw: "Stream Title",
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        for msg in ("q1", "q2"):
            r = client.post(
                f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
                json={"message": msg}, headers=_auth(token),
            )
            r.get_data()  # consume the stream so the exchange persists
        assert [(m["role"], m["content"]) for m in calls[1][1:]] == [
            ("user", "q1"), ("assistant", "ok"), ("user", "q2"),
        ]


class TestExecutionRecords:
    """Execution records on agent turns (memo dev/37): every completed run
    pins its DEC-031 reproducibility inputs and Actual usage on the transcript
    — the transcript IS the run history."""

    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def _mock_provider(self, monkeypatch, reply="ok", usage=None):
        """Stub the blocking port; ``usage`` (when given) is written into the
        ``usage_out`` sink for conversation runs. Title calls answer out of
        band and report a token cost of their own."""
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers

        calls = []

        def _fake_run(config, messages, usage_out=None, **kwargs):
            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                if usage_out is not None:
                    usage_out.update({"inputTokens": 5, "outputTokens": 3})
                return "Exec Title"
            calls.append(messages)
            if usage is not None and usage_out is not None:
                usage_out.update(usage)
            return reply

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return calls

    def _turns(self, client, token, project_id, att_id):
        return client.get(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]

    def test_run_persists_execution_record_with_pins_and_usage(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers
        # Read at call time: the suite's conftest stands in for the operator
        # and patches the config module, so an import-time snapshot would see
        # the (empty) shipped defaults.
        from utk_curio.backend import config as backend_config

        DEFAULT_LLM_API_TYPE = backend_config.DEFAULT_LLM_API_TYPE
        DEFAULT_LLM_MODEL = backend_config.DEFAULT_LLM_MODEL

        self._mock_provider(monkeypatch, usage={"inputTokens": 12, "outputTokens": 34})
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 200
        body = r.get_json()
        # The blocking response carries the same two new fields (memo dev/37).
        assert body["executionId"]
        assert body["usage"] == {"inputTokens": 12, "outputTokens": 34}
        turns = self._turns(client, token, alice_project, att_id)
        assert "execution" not in turns[0]  # user turns carry no record
        execution = turns[1]["execution"]
        assert execution["executionId"] == body["executionId"]
        assert execution["status"] == "ok"
        assert execution["usage"] == {"inputTokens": 12, "outputTokens": 34}
        assert isinstance(execution["durationMs"], int) and execution["durationMs"] >= 0
        pins = execution["pins"]
        assert pins["coord"] == "agent.chat-agent@1.0.0"
        assert pins["intentEdited"] is False
        # Built-in roster manifests carry no prompt digest — tolerated null.
        assert pins["promptSha256"] is None
        # Unconfigured test user → the deployment-default provider (DEC-039).
        assert pins["provider"] == DEFAULT_LLM_API_TYPE
        assert pins["model"] == DEFAULT_LLM_MODEL
        assert pins["llm"] == {"configId": None, "label": "Deployment default",
                               "baseUrlHost": "127.0.0.1:9", "source": "deployment"}
        # dev/39: granted tools are pinned; the registry ships empty.
        assert pins["tools"] == ["dataflow.read", "node.read", "node.runtime.read"]
        # One pin left: the run caps and the budget it used to record are gone.
        assert pins["policy"] == {
            "maxOutputTokens": policy.DEPLOYMENT_MAX_OUTPUT_TOKENS,
        }

    def test_run_usage_null_when_provider_reports_none(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        self._mock_provider(monkeypatch)  # sink never touched (proxy strips usage)
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.get_json()["usage"] is None
        turns = self._turns(client, token, alice_project, att_id)
        # Actual-or-absent (memo dev/11): never estimated into the field.
        assert turns[1]["execution"]["usage"] is None
        assert turns[1]["execution"]["status"] == "ok"

    def test_provider_error_records_error_execution(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _boom(config, messages, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _boom)
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 502
        turns = self._turns(client, token, alice_project, att_id)
        execution = turns[1]["execution"]
        assert execution["status"] == "error"
        assert execution["usage"] is None
        assert execution["pins"]["coord"] == "agent.chat-agent@1.0.0"

    def test_edited_intent_is_pinned(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        self._mock_provider(monkeypatch)
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        client.patch(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}",
            json={"intent": "custom instructions"}, headers=_auth(token),
        )
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["execution"]["pins"]["intentEdited"] is True

    def test_stream_persists_execution_record(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _fake_stream(config, messages, usage_out=None, **kwargs):
            yield "hel"
            yield "lo"
            if usage_out is not None:
                usage_out.update({"inputTokens": 7, "outputTokens": 9})

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _fake_stream
        )
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda c, m, **kw: "Stream Title",
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        blocks = [b for b in r.get_data(as_text=True).strip().split("\n\n")]
        events = [
            (lines["event"], json.loads(lines["data"]))
            for lines in (dict(l.split(": ", 1) for l in b.splitlines() if ": " in l) for b in blocks)
        ]
        turns = self._turns(client, token, alice_project, att_id)
        execution = turns[1]["execution"]
        assert execution["status"] == "ok"
        assert execution["usage"] == {"inputTokens": 7, "outputTokens": 9}
        assert execution["pins"]["coord"] == "agent.chat-agent@1.0.0"
        # The SSE envelope correlates with the persisted record (memo dev/37):
        # execution first, done enriched with the same id and Actual usage.
        assert events[0] == ("execution", {"executionId": execution["executionId"]})
        # dev/80: the round's Actual sums stream as an interim usage event.
        assert ("usage", {"usage": {"inputTokens": 7, "outputTokens": 9}}) in events
        done_name, done_payload = events[-1]
        assert done_name == "done"
        # dev/80: done carries the SAME duration the persisted record keeps.
        assert done_payload.pop("durationMs") == execution["durationMs"]
        assert done_payload == {
            "reply": "hello",
            "executionId": execution["executionId"],
            "usage": {"inputTokens": 7, "outputTokens": 9},
            "content": [],
        }

    def test_stream_error_records_error_execution(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _flaky(config, messages, **kwargs):
            yield "par"
            raise RuntimeError("boom")

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _flaky
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        r.get_data()
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["execution"]["status"] == "error"

    def test_title_call_writes_no_execution_record(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The dev/25 auto-title call is internal housekeeping, not an execution:
        # a first run makes two provider calls but exactly one record exists.
        calls = self._mock_provider(monkeypatch, usage={"inputTokens": 1, "outputTokens": 2})
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert len(calls) == 1  # the conversation run; the title call is untracked
        turns = self._turns(client, token, alice_project, att_id)
        assert sum(1 for t in turns if "execution" in t) == 1

    def test_daily_usage_counters_include_the_title_call(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The counters cover every provider call this account paid for — the
        # conversation run (12/34) plus the recordless title call (5/3) — so
        # they may exceed what the transcript's execution records sum to.
        from utk_curio.backend.app.projects.services import _user_dir_key

        self._mock_provider(monkeypatch, usage={"inputTokens": 12, "outputTokens": 34})
        user, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert ledger.aggregates(_user_dir_key(user))["usage"] == {
            "inputTokens": 17, "outputTokens": 37,
        }

    def test_the_ledger_counts_the_run_and_the_title_call(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # This read through the account and per-dataflow settings payloads.
        # Both endpoints are gone, so the ledger is the record: it is written
        # from the token counts each completion already returns, and nothing
        # exposes it over HTTP.
        self._mock_provider(monkeypatch, usage={"inputTokens": 12, "outputTokens": 34})
        user, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        agg = ledger.aggregates(_user_dir_key(user))
        # The title call is counted as tokens but not as a run, so the token
        # total exceeds what the single execution record reports.
        assert agg["usage"] == {"inputTokens": 17, "outputTokens": 37}
        assert agg["runs"] == 1

    def test_uploaded_definition_prompt_digest_is_pinned(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # A digest-stamped definition (upload-import, memo dev/36) pins the
        # exact prompt bytes that dispatched (DEC-031).
        import hashlib

        self._mock_provider(monkeypatch)
        user, token = user_and_token
        prompt_text = "You explain things."
        digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        r = client.post(
            "/api/agents/imports/upload",
            json={
                "manifest": {
                    "id": "agent.pinned",
                    "name": "Pinned",
                    "category": "canvas",
                    "version": "1.0.0",
                    "capabilities": [{"id": "chat.reply", "contractVersion": "1"}],
                    "compatibleTargets": [{"kind": "canvas", "requires": []}],
                    "prompts": {"instruction": {"path": "prompts/instruction.txt", "variables": []}},
                    "provenance": {"publisher": "alice", "trust": "imported"},
                },
                "prompts": {"prompts/instruction.txt": prompt_text},
            },
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        att_id = self._attach_builtin(client, token, alice_project, coord="agent.pinned@1.0.0")
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["execution"]["pins"]["promptSha256"] == digest


class TestToolGrants:
    """Tool-contract substrate on the run path (memo dev/39): declarations are
    never grants; required-but-ungranted refuses the run before admission."""

    def _upload_install_attach(self, client, token, project_id, tools_section):
        coord = "agent.tooled@1.0.0"
        r = client.post(
            "/api/agents/imports/upload",
            json={
                "manifest": {
                    "id": "agent.tooled",
                    "name": "Tooled",
                    "category": "canvas",
                    "version": "1.0.0",
                    "capabilities": [{"id": "chat.reply", "contractVersion": "1"}],
                    "compatibleTargets": [{"kind": "canvas", "requires": []}],
                    "prompts": {"instruction": {"path": "prompts/i.txt", "variables": []}},
                    "tools": tools_section,
                    "provenance": {"publisher": "alice", "trust": "imported"},
                },
                "prompts": {"prompts/i.txt": "You help."},
            },
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        att = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return att.get_json()["attachmentId"]

    def test_required_ungranted_tool_refuses_the_run_without_consuming_quota(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects.services import _user_dir_key

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda c, m, **kw: "never reached",
        )
        user, token = user_and_token
        att_id = self._upload_install_attach(
            client, token, alice_project, [{"id": "ghost.tool", "required": True}]
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 422
        assert "ghost.tool" in r.get_json()["error"]
        # Validation-stage refusal: no quota consumed, nothing persisted.
        assert ledger.aggregates(_user_dir_key(user))["runs"] == 0
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert turns == []

    def test_optional_ungranted_tool_runs_and_pins_no_grant(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda c, m, **kw: "ok",
        )
        _, token = user_and_token
        att_id = self._upload_install_attach(
            client, token, alice_project, [{"id": "ghost.tool", "required": False}]
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 200
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert turns[1]["execution"]["pins"]["tools"] == []

    def test_unknown_optional_tools_are_dropped_with_a_warning(self, client, user_and_token, tmp_curio, alice_project, monkeypatch, caplog):
        """An agent saved when the Discovery tools were datalake.* still runs
        without them, and the log names each tool it does not get."""
        import logging

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda c, m, **kw: "ok",
        )
        _, token = user_and_token
        att_id = self._upload_install_attach(
            client, token, alice_project,
            [{"id": "datalake.search", "required": False}, {"id": "datalake.acquire", "required": False}],
        )
        with caplog.at_level(logging.WARNING):
            r = client.post(
                f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
                json={"message": "q1"}, headers=_auth(token),
            )
        assert r.status_code == 200
        warnings = [
            rec.getMessage() for rec in caplog.records
            if rec.levelno == logging.WARNING and "datalake.search" in rec.getMessage()
        ]
        assert len(warnings) == 1, caplog.text
        assert "datalake.acquire" in warnings[0]
        assert "agent.tooled@1.0.0" in warnings[0]
        assert "discovery." in warnings[0]
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert turns[1]["execution"]["pins"]["tools"] == []

    def test_registered_read_tool_is_granted_and_pinned(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents.application import tools as tools_mod
        from utk_curio.backend.app.agents.application.tools import ToolContract

        monkeypatch.setitem(
            tools_mod.REGISTRY,
            "ghost.tool",
            ToolContract(id="ghost.tool", contract_version="1", effect="read", description="d"),
        )
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda c, m, **kw: "ok",
        )
        _, token = user_and_token
        att_id = self._upload_install_attach(
            client, token, alice_project, [{"id": "ghost.tool", "required": True}]
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 200
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert turns[1]["execution"]["pins"]["tools"] == ["ghost.tool"]


class TestRunContext:
    """The ephemeral grounded-context pipeline (memo dev/44): client-composed
    live-canvas inputs ride one provider message per send — fresh every time,
    never persisted, byte-identical runs without it."""

    def _attach(self, client, token, project_id, coord="agent.node-content-builder@1.0.0"):
        r = client.put(
            f"/api/projects/{project_id}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1", "content": "x"}], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert r.status_code == 200
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "node", "targetId": "n1"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def _mock_run(self, monkeypatch):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers

        calls = []

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return "ok"

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return calls

    def test_context_rides_one_message_before_the_user_turn(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = self._mock_run(monkeypatch)
        _, token = user_and_token
        att_id = self._attach(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "write it", "context": "Current Trill: {...}\n Node ID: n1"},
            headers=_auth(token),
        )
        assert r.status_code == 200
        msgs = calls[0]
        assert msgs[-1] == {"role": "user", "content": "write it"}
        assert msgs[-2]["role"] == "user"
        assert msgs[-2]["content"].startswith("[attachment context — current canvas state]\n")
        assert "Current Trill" in msgs[-2]["content"]
        # Ephemeral: the transcript persists only what the user saw.
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert [t["text"] for t in turns] == ["write it", "ok"]

    def test_context_is_recomposed_not_replayed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = self._mock_run(monkeypatch)
        _, token = user_and_token
        att_id = self._attach(client, token, alice_project)
        url = f"/api/agents/projects/{alice_project}/attachments/{att_id}/run"
        client.post(url, json={"message": "q1", "context": "STATE-A"}, headers=_auth(token))
        client.post(url, json={"message": "q2", "context": "STATE-B"}, headers=_auth(token))
        second = calls[1]
        joined = "\n".join(m["content"] for m in second)
        assert "STATE-B" in joined
        assert "STATE-A" not in joined  # never stale, never replayed from history

    def test_absent_context_is_byte_identical(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = self._mock_run(monkeypatch)
        _, token = user_and_token
        att_id = self._attach(client, token, alice_project)
        url = f"/api/agents/projects/{alice_project}/attachments/{att_id}/run"
        client.post(url, json={"message": "q1"}, headers=_auth(token))
        # system + user only — no context frame anywhere (regression pin).
        assert [m["role"] for m in calls[0]] == ["system", "user"]
        assert not any("[attachment context" in m["content"] for m in calls[0])

    def test_context_is_bounded_with_a_visible_marker(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers

        calls = self._mock_run(monkeypatch)
        _, token = user_and_token
        att_id = self._attach(client, token, alice_project)
        big = "x" * (policy.CONTEXT_MAX_CHARS + 500)
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q", "context": big}, headers=_auth(token),
        )
        ctx_msg = calls[0][-2]["content"]
        assert "truncated: context exceeded" in ctx_msg
        assert len(ctx_msg) < policy.CONTEXT_MAX_CHARS + 200

    def test_non_string_context_is_a_400(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        att_id = self._attach(client, token, alice_project)
        for url_suffix in ("run", "run/stream"):
            r = client.post(
                f"/api/agents/projects/{alice_project}/attachments/{att_id}/{url_suffix}",
                json={"message": "q", "context": {"not": "a string"}},
                headers=_auth(token),
            )
            assert r.status_code == 400
            assert "'context'" in r.get_json()["error"]

    def test_stream_carries_the_context_too(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = []

        def _fake_stream(config, messages, **kwargs):
            calls.append(messages)
            yield "ok"

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _fake_stream
        )
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda c, m, **kw: "Title",
        )
        _, token = user_and_token
        att_id = self._attach(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q", "context": "LIVE-TRILL"}, headers=_auth(token),
        )
        r.get_data()
        assert "LIVE-TRILL" in calls[0][-2]["content"]

    def test_attachment_card_exposes_the_declared_reads(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        self._attach(client, token, alice_project)
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        # The dev/38 grounded mapping for Node Content Builder, verbatim.
        assert cards[0]["reads"] == ["dataflowContext", "nodeId", "subtask", "workflowGoal"]


class TestToolLoop:
    """The bounded read-tool execution loop (memo dev/41): granted reads
    execute with normalized events; everything else refuses loudly to the
    model, invisibly to the user; grant-less runs stay byte-identical to T2."""

    def _save_node(self, client, token, project_id, node):
        r = client.put(
            f"/api/projects/{project_id}",
            json={"name": "p", "spec": {"dataflow": {"nodes": [node], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)

    def _install_attach(self, client, token, project_id, coord, target):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": target},
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        return r.get_json()["attachmentId"]

    def _sse_events(self, resp):
        out = []
        for block in resp.get_data(as_text=True).strip().split("\n\n"):
            lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
            out.append((lines["event"], json.loads(lines["data"])))
        return out

    TOOL_TAIL = '```curio.v1\n{"toolRequest": {"tool": "node.read", "params": {}}}\n```'

    def test_granted_read_tool_executes_with_events_and_record(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = []

        def _fake_stream(config, messages, usage_out=None, **kwargs):
            calls.append(messages)
            if usage_out is not None:
                usage_out.update({"inputTokens": len(calls), "outputTokens": len(calls) * 2})
            if len(calls) == 1:
                yield "Let me look at the node.\n"
                yield self.TOOL_TAIL
            else:
                yield "It prints 1."

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _fake_stream
        )
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda c, m, **kw: "Loop Title",
        )
        _, token = user_and_token
        self._save_node(client, token, alice_project, {"id": "n1", "type": "CODE", "content": "print(1)"})
        att_id = self._install_attach(
            client, token, alice_project, "agent.chat-agent@1.0.0",
            {"kind": "node", "targetId": "n1"},
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "explain"}, headers=_auth(token),
        )
        events = self._sse_events(r)
        kinds = [k for k, _ in events]
        # Normalized ordering (dev/03:344 vocabulary over the T1 envelope).
        assert kinds.index("tool_requested") < kinds.index("tool_started") < kinds.index("tool_result")
        assert kinds.index("tool_result") < kinds.index("done")
        tool_result = next(p for k, p in events if k == "tool_result")
        assert tool_result == {"tool": "node.read", "status": "ok"}
        deltas = "".join(p["text"] for k, p in events if k == "delta")
        assert "curio.v1" not in deltas  # the request tail never flashed
        done = events[-1][1]
        assert done["reply"] == "Let me look at the node.\n\nIt prints 1."
        # The grant-aware instruction listed the granted tool.
        assert "- node.read:" in calls[0][0]["content"]
        # The tool result (node JSON) reached the second call as framed data.
        second_ctx = calls[1][-1]["content"]
        assert second_ctx.startswith("[tool result] node.read: ok")
        assert "print(1)" in second_ctx
        # Execution record: toolCalls + usage summed across both rounds.
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        execution = turns[1]["execution"]
        assert execution["usage"] == {"inputTokens": 3, "outputTokens": 6}
        (call,) = execution["toolCalls"]
        assert call["tool"] == "node.read" and call["status"] == "ok"
        assert isinstance(call["durationMs"], int)
        assert turns[1]["text"] == "Let me look at the node.\n\nIt prints 1."

    def test_an_egress_refusal_reaches_the_chat_with_its_reason(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        """#447: a web.fetch the egress policy refuses reaches the user with the
        refusal's reason, live on the tool_result event and on the saved turn, so
        a refused address no longer looks like a site that is down."""
        from utk_curio.backend.app.agents.infrastructure import egress

        def _refuse(url, **kwargs):
            raise egress.EgressRefused(
                "host '127.0.0.1' resolves to a non-public address (127.0.0.1) - refused"
            )

        monkeypatch.setattr(egress, "fetch", _refuse)
        calls = []

        def _fake_stream(config, messages, usage_out=None, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                yield (
                    '```curio.v1\n{"toolRequest": {"tool": "web.fetch", '
                    '"params": {"url": "http://127.0.0.1/data.json"}}}\n```'
                )
            else:
                yield "I could not reach that address."

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _fake_stream
        )
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda c, m, **kw: "Fetch Title",
        )
        _, token = user_and_token
        att_id = self._install_attach(
            client, token, alice_project, "agent.node-researcher@1.0.0", {"kind": "canvas"},
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "check the data endpoint"}, headers=_auth(token),
        )
        events = self._sse_events(r)
        tool_result = next(p for k, p in events if k == "tool_result")
        assert tool_result["tool"] == "web.fetch" and tool_result["status"] == "error"
        assert "egress policy" in tool_result["reason"]
        assert "non-public address" in tool_result["reason"]
        # The model still got the refusal as its tool result.
        assert "refused by the egress policy" in calls[1][-1]["content"]
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        (call,) = turns[1]["execution"]["toolCalls"]
        assert call["tool"] == "web.fetch" and call["status"] == "error"
        assert call["reason"] == tool_result["reason"]

    def test_a_failure_reason_is_one_bounded_line_without_url_queries(self):
        """#447: the reason is shown in the chat and saved with the turn, so it is
        one bounded line, and a URL's query string (where a search provider's key
        rides) never reaches it. A call that succeeded has no reason at all."""
        from utk_curio.backend.app.agents.application import tool_rounds

        failure = (
            "the search provider failed: HTTPSConnectionPool(host='search.example.org', "
            "port=443): Max retries exceeded with url: /api?q=parks&key=sk-live-0123456789abcdef "
            "(Caused by NewConnectionError('connection refused'))"
        )
        reason = tool_rounds._failure_reason("error", failure)
        assert reason.startswith("the search provider failed: ")
        assert "/api?" in reason and "sk-live-0123456789abcdef" not in reason
        assert tool_rounds._failure_reason(
            "refused", "the plan's revision targets are invalid:\n- node 'x' is unknown"
        ) == "the plan's revision targets are invalid:"
        assert len(tool_rounds._failure_reason("error", "tool failed: " + "x" * 5000)) <= 300
        assert tool_rounds._failure_reason("ok", "{}") is None
        assert tool_rounds._failure_reason("proposed", "") is None

    def test_ungranted_request_is_refused_to_the_model_only(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.solve import session as packages_session
            from utk_curio.backend.app.agents.application.solve import simulation
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import delegates
            from utk_curio.backend.app.agents.application.turns import policy
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            if len(calls) == 1:
                return '```curio.v1\n{"toolRequest": {"tool": "dataflow.read", "params": {}}}\n```'
            return "Done without it."

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        _, token = user_and_token
        # Chat agent declares no tools → nothing granted.
        client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": "agent.node-researcher@1.0.0"}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": "agent.node-researcher@1.0.0", "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        assert r.status_code == 200
        assert r.get_json()["reply"] == "Done without it."
        assert "not granted" in calls[1][-1]["content"]
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        (call,) = turns[1]["execution"]["toolCalls"]
        assert call["status"] == "refused"

    def test_round_cap_bounds_the_loop(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.solve import session as packages_session
            from utk_curio.backend.app.agents.application.solve import simulation
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import delegates
            from utk_curio.backend.app.agents.application.turns import policy
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return f"Round {len(calls)}.\n" + TestToolLoop.TOOL_TAIL  # always wants more

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        _, token = user_and_token
        self._save_node(client, token, alice_project, {"id": "n1", "content": "x"})
        att_id = self._install_attach(
            client, token, alice_project, "agent.chat-agent@1.0.0",
            {"kind": "node", "targetId": "n1"},
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        assert r.status_code == 200
        assert len(calls) == 4  # MAX_TOOL_ROUNDS executions + the final call
        # The last tool result told the model to answer with what it has.
        assert "answer with what you have" in calls[3][-1]["content"]
        body = r.get_json()
        # The dangling fourth READ request was dropped; all round text kept
        # (dev/73: only a mutate dangle earns the cutoff card).
        assert body["reply"] == "Round 1.\n\nRound 2.\n\nRound 3.\n\nRound 4."
        assert body["content"] == []
        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        assert len(turns[1]["execution"]["toolCalls"]) == 3

    def test_mutate_request_never_executes_in_the_loop(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.solve import session as packages_session
            from utk_curio.backend.app.agents.application.solve import simulation
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import delegates
            from utk_curio.backend.app.agents.application.turns import policy
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            if len(calls) == 1:
                return (
                    '```curio.v1\n{"toolRequest": {"tool": "node.content.write", '
                    '"params": {"nodeId": "n1", "content": "pwned"}}}\n```'
                )
            return "Proposed."

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        user, token = user_and_token
        self._save_node(client, token, alice_project, {"id": "n1", "content": "original"})
        att_id = self._install_attach(
            client, token, alice_project, "agent.node-content-builder@1.0.0",
            {"kind": "node", "targetId": "n1"},
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        assert r.status_code == 200
        # The spec is untouched: the loop NEVER executes a mutation (DEC-006).
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        assert spec["dataflow"]["nodes"][0]["content"] == "original"

    def test_grantless_system_turn_is_byte_identical_to_t2(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.agents.domain import builtin
        from utk_curio.backend.app.agents.domain import content as content_mod
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers

        calls = []

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return "ok"

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        user, token = user_and_token
        # No built-in card is both tool-free and delegate-free, so an owned
        # definition that declares neither stands in for a grant-less run.
        coord = "agent.plain-helper@1.0.0"
        storage.write_definition(_user_dir_key(user), coord, {
            "id": "agent.plain-helper", "name": "Plain Helper", "category": "node",
            "version": "1.0.0",
            "capabilities": [{"id": "conversation.respond", "contractVersion": "1"}],
            "compatibleTargets": [{"kind": "node", "requires": []}],
            "provenance": {"publisher": "curio", "trust": "imported"},
            "prompts": {"instruction": {"path": "prompts/instruction.txt", "variables": []}},
        }, {"prompts/instruction.txt": "Answer briefly."})
        self._save_node(client, token, alice_project, {"id": "n1", "type": "CODE", "content": "x"})
        att_id = self._install_attach(
            client, token, alice_project, coord, {"kind": "node", "targetId": "n1"},
        )
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        system = calls[0][0]["content"]
        assert system == f"Answer briefly.\n\n{content_mod.TAIL_INSTRUCTION}"
        assert "You may also use these tools" not in system
        assert "delegateRequest" not in system


class TestStructuredContent:
    """Structured-tail protocol end-to-end (memo dev/39, DEC-043): a valid
    terminal curio.v1 block becomes typed parts on the turn and the envelope;
    anything else fails open to visible text."""

    TAIL = '```curio.v1\n{"suggestedPrompts": {"primary": "Next step", "alternatives": ["Alt"]}}\n```'
    PARTS = [{"type": "suggestedPrompts", "primary": "Next step", "alternatives": ["Alt"]}]

    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def _mock_run(self, monkeypatch, replies):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers

        calls = []

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Content Title"
            calls.append(messages)
            return replies[len(calls) - 1]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return calls

    def _mock_stream(self, monkeypatch, deltas):
        def _fake_stream(config, messages, **kwargs):
            yield from deltas

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _fake_stream
        )
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn',
            lambda c, m, **kw: "Stream Title",
        )

    def _turns(self, client, token, project_id, att_id):
        return client.get(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]

    def _sse_events(self, resp):
        out = []
        for block in resp.get_data(as_text=True).strip().split("\n\n"):
            lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
            out.append((lines["event"], json.loads(lines["data"])))
        return out

    def test_run_strips_valid_tail_and_persists_parts(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        calls = self._mock_run(monkeypatch, [f"Answer.\n{self.TAIL}", "second"])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        body = r.get_json()
        assert body["reply"] == "Answer."
        assert body["content"] == self.PARTS
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["text"] == "Answer."
        assert turns[1]["content"] == self.PARTS
        # The tail never re-enters provider context on the next turn.
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q2"}, headers=_auth(token),
        )
        assert {"role": "assistant", "content": "Answer."} in calls[1]
        # (Only the system turn mentions curio.v1 — via the tail instruction.)
        assert not any("curio.v1" in m["content"] for m in calls[1] if m["role"] != "system")

    def test_run_invalid_tail_stays_visible_verbatim(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        reply = "Answer.\n```curio.v1\n{broken\n```"
        self._mock_run(monkeypatch, [reply])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        body = r.get_json()
        assert body["reply"] == reply  # fail-open: nothing stripped
        assert body["content"] == []
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["text"] == reply
        assert "content" not in turns[1]

    def test_stream_withholds_tail_and_emits_content_event(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The fence marker is split across delta boundaries on purpose.
        self._mock_stream(
            monkeypatch,
            ["Answer.\n``", '`curio.v1\n{"suggestedPrompts": {"primary": "Next step", ', '"alternatives": ["Alt"]}}', "\n```"],
        )
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        events = self._sse_events(r)
        deltas = "".join(p["text"] for kind, p in events if kind == "delta")
        # The tail never flashed into the live transcript.
        assert "curio.v1" not in deltas
        assert deltas == "Answer.\n"
        kinds = [k for k, _ in events]
        assert kinds.index("content") < kinds.index("done")
        content_event = next(p for k, p in events if k == "content")
        assert content_event == {"parts": self.PARTS}
        done = events[-1][1]
        assert done["reply"] == "Answer."
        assert done["content"] == self.PARTS
        turns = self._turns(client, token, alice_project, att_id)
        assert turns[1]["text"] == "Answer."
        assert turns[1]["content"] == self.PARTS

    def test_stream_mid_reply_block_is_flushed_not_typed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # A closed block followed by prose is body text (false positive).
        full = "Syntax:\n" + self.TAIL + "\nUse it like so."
        self._mock_stream(monkeypatch, ["Syntax:\n", self.TAIL, "\nUse it like so."])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        events = self._sse_events(r)
        assert "content" not in [k for k, _ in events]
        deltas = "".join(p["text"] for kind, p in events if kind == "delta")
        assert deltas == full  # everything streamed, nothing swallowed
        assert events[-1][1]["reply"] == full
        assert events[-1][1]["content"] == []

    def test_stream_invalid_terminal_tail_is_flushed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        full = "Answer.\n```curio.v1\n{broken\n```"
        self._mock_stream(monkeypatch, ["Answer.\n", "```curio.v1\n{broken\n```"])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        events = self._sse_events(r)
        assert "content" not in [k for k, _ in events]
        deltas = "".join(p["text"] for kind, p in events if kind == "delta")
        assert deltas == full
        assert events[-1][1]["reply"] == full

    def test_stream_ending_on_partial_marker_is_flushed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        self._mock_stream(monkeypatch, ["Answer ``", "`cu"])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        events = self._sse_events(r)
        deltas = "".join(p["text"] for kind, p in events if kind == "delta")
        assert deltas == "Answer ```cu"
        assert events[-1][1]["reply"] == "Answer ```cu"

    def test_legacy_json_reply_passes_through_untouched(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Planner-style agents whose whole reply is machine JSON (no fence):
        # byte-identical passthrough for their legacy consumers.
        reply = '{"dataflow": {"nodes": [], "edges": []}}'
        self._mock_run(monkeypatch, [reply])
        _, token = user_and_token
        att_id = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.get_json()["reply"] == reply
        assert r.get_json()["content"] == []


class TestRunsAreRecordedNotRationed:
    """What replaced the metering classes.

    ``TestLedgerAndPricing`` asserted that reservations settled with a pinned
    price, that ``costUsd`` rode the execution record, and that a configured
    budget with no price denied the run. ``TestQuotaAdmission`` asserted both
    run paths 429'd once a daily limit was hit. Curio does not cap or price
    agent runs any more, so both claims are gone and the opposite is asserted
    here: runs are recorded, never refused.
    """

    def _attach_builtin(self, client, token, project_id, coord="agent.chat-agent@1.0.0"):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
        r = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        )
        return r.get_json()["attachmentId"]

    def _mock_run(self, monkeypatch, reply="ok"):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers

        def _fake_run(config, messages, **kwargs):
            # The usage sink is what the ledger records; a mock that ignores it
            # would make the token assertions below vacuous.
            sink = kwargs.get("usage_out")
            if sink is not None:
                sink["inputTokens"] = 12
                sink["outputTokens"] = 34
            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            return reply

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run
        )

    def test_many_runs_all_succeed_and_all_count(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        # The old ceiling was 200/day and an env var could lower it. Neither
        # exists, so nothing here can 429 for usage.
        self._mock_run(monkeypatch)
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "2")  # deliberately ignored
        user, token = user_and_token
        att = self._attach_builtin(client, token, alice_project)
        url = f"/api/agents/projects/{alice_project}/attachments/{att}/run"
        for _ in range(5):
            r = client.post(url, json={"message": "q"}, headers=_auth(token))
            assert r.status_code == 200, r.get_data(as_text=True)
        assert ledger.aggregates(_user_dir_key(user))["runs"] == 5

    def test_no_execution_record_carries_a_usd_figure(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        # Curio ships no price table, so a cost would have to be invented.
        self._mock_run(monkeypatch)
        _, token = user_and_token
        att = self._attach_builtin(client, token, alice_project)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        assert r.status_code == 200
        raw = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att}/session",
            headers=_auth(token),
        ).get_data(as_text=True)
        assert "costUsd" not in raw
        assert "actualSpendTodayUsd" not in raw

    def test_the_ledger_records_tokens_and_nothing_monetary(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        self._mock_run(monkeypatch)
        user, token = user_and_token
        att = self._attach_builtin(client, token, alice_project)
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        agg = ledger.aggregates(_user_dir_key(user))
        assert agg["usage"]["inputTokens"] > 0
        # No spend, no cost, no ceiling: the ledger records tokens and runs.
        assert set(agg) == {"runs", "byTemplate", "byAttachment", "usage"}


class TestOutputCapReachesTheProvider:
    """The one claim that outlived the settings screens.

    ``TestProjectAgentDefaults`` and ``TestSettingsScreensApi`` covered three
    policy scopes, tighten-only writes, optimistic revisions and a lazy
    materialization path. All six endpoints behind them are gone: nothing in
    the interface could reach them once the limits UI was removed, and the only
    field they still exposed was ``maxOutputTokens``. That field still matters,
    because it is passed to every provider - it is just a deployment constant
    now rather than something a user can override.
    """

    COORD = "agent.chat-agent@1.0.0"

    def _install_and_attach(self, client, token, project_id):
        client.post(
            f"/api/agents/projects/{project_id}/install",
            json={"coord": self.COORD}, headers=_auth(token),
        )
        return client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]

    def test_the_deployment_cap_is_what_every_run_sends(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        # seen[0] is the conversation run; a first run adds the small-capped
        # title call after it.
        seen = []

        def _fake(config, messages, max_output_tokens=None, **kwargs):
            seen.append(max_output_tokens)
            return "ok"

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake)
        _, token = user_and_token
        att = self._install_and_attach(client, token, alice_project)
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att}/run",
            json={"message": "q"}, headers=_auth(token),
        )
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers

        assert seen[0] == policy.DEPLOYMENT_MAX_OUTPUT_TOKENS

    def test_the_retired_settings_endpoints_are_gone(self, app):
        # A guard on the removal: re-adding one should be a decision, not a
        # symbol that quietly reappears.
        #
        # Asserted against the URL map rather than a request. Since #279 an
        # unregistered route does answer 404, so a status assertion would work
        # now - but the map is the more direct statement of "this rule is gone",
        # and it cannot be satisfied by a 404 that came from somewhere else.
        #
        # ``/api/agents/settings`` was one of them and is taken again, by the
        # account's catalog settings (test_catalog_settings.py): a different
        # contract that shares only the path.
        rules = {str(r.rule) for r in app.url_map.iter_rules()}
        for gone in (
            "/api/agents/projects/<project_id>/defaults/<coord>",
            "/api/agents/projects/<project_id>/attachments/<attachment_id>/settings",
        ):
            assert gone not in rules, gone

    def test_install_writes_no_defaults_record(self, client, user_and_token, tmp_curio, alice_project):
        from utk_curio.backend.app.projects import storage as projects_storage

        user, token = user_and_token
        self._install_and_attach(client, token, alice_project)
        spec = projects_storage.read_spec(_user_dir_key(user), alice_project)
        # `dataflow.agentDefaults` was materialized per install to hold the
        # per-dataflow policy record. Nothing edits it, so nothing writes it.
        assert "agentDefaults" not in spec.get("dataflow", {})


class TestReuseLadder:
    """dev/93 D4 — the reuse ladder: reuse → ENLIST → author.

    The live failure this class pins: a Researcher asked "what's the weather
    in Paris?" reported "there is no installed notes template on your canvas"
    and delegated package authoring TWICE in one run, producing two
    near-duplicate packages — while a perfectly good notes package sat in the
    user's store, invisible because this project's lockfile did not name it
    and unreachable because the agent had no way to enlist it.
    """

    COORD = "agent.researcher@1.0.0"

    def _write_store_package(self, user_key, dir_name, package_id, template_id, label):
        """A package in the user's STORE but not in any project lockfile —
        e.g. one a previous project's Package Builder authored."""
        import json as _json

        from utk_curio.backend.app.packages.repositories.store import user_packages_dir

        d = user_packages_dir(user_key) / dir_name
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(_json.dumps({
            "id": package_id,
            "version": "1.0.0",
            "name": "Simple Notes",
            "publisher": "Package Builder",
            "description": "Colored note surfaces.",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": template_id, "label": label,
                "category": "visualization", "engine": "javascript",
                "editor": "none", "behavior": "note-behavior",
                "hasCode": False, "description": "A note surface.",
                "inputPorts": [], "outputPorts": [],
            }],
            "createdAt": "2026-08-01T12:00:00Z",
        }), encoding="utf-8")

    def _write_builtin_package(self, user_key, templates=None):
        return TestNodeCreate()._write_builtin_package(user_key, templates)

    def _setup(self, client, user, token, project_id, monkeypatch, replies=None):
        # Borrow the node-create harness but bind it to THIS class, so the
        # attachment is the Researcher (the agent that holds package.install).
        return TestNodeCreate()._setup.__func__(
            self, client, user=user, token=token, project_id=project_id,
            monkeypatch=monkeypatch, replies=replies,
        )

    def _run(self, client, token, project_id, att_id, message="what's the weather in Paris?"):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
            json={"message": message}, headers=_auth(token),
        )

    def test_roster_offers_the_enlistable_package_with_its_dir_name(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        att_id, calls = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=["ok"],
        )
        self._write_store_package(key, "curio.notes@1", "curio.notes", "note-surface", "Note")
        self._run(client, token, alice_project, att_id)
        system = calls[0][0]["content"]

        # The distinction the single-bucket roster could not express.
        assert "Installed but NOT enlisted in this project" in system
        assert "- curio.notes/note-surface — Note" in system
        # The dirName a package.install proposal takes, so nothing is guessed.
        assert "(package curio.notes@1)" in system
        assert "do NOT" in system and "duplicate package" in system

    def test_enlisted_package_leaves_the_not_enlisted_section(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        att_id, calls = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=["ok"],
        )
        self._write_store_package(key, "curio.notes@1", "curio.notes", "note-surface", "Note")
        from utk_curio.backend.app.packages.application import agent_reads
        from utk_curio.backend.app.packages.application import project_packages
        from utk_curio.backend.app.packages.application import store_reads
        from utk_curio.backend.app.packages.application import templates as packages_templates
        project_packages.install_to_project(key, alice_project, "curio.notes@1")

        self._run(client, token, alice_project, att_id)
        system = calls[0][0]["content"]
        # Now it is usable, so it belongs to the available half only. Assert on
        # the roster's own marker — the dirName suffix only the enlist section
        # emits — because the instruction text names that section by title.
        assert "(package curio.notes@1)" not in system
        assert "- curio.notes/note-surface — Note" in system

    # dev/105 D1 — the live 2026-08-25 failure: the model quoted the manifest
    # id `curio.notes` (the spelling its own prose used), the mint exact-matched
    # the dirName, and the refusal named packages.catalog — a tool the
    # Researcher does not hold. Every spelling the roster teaches must mint the
    # SAME proposal, pinned to the canonical dirName.
    @pytest.mark.parametrize("spelling", [
        "curio.notes", "curio.notes/note-surface", "curio.notes/note-surface@1",
    ])
    def test_enlist_accepts_every_spelling_the_roster_teaches(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch, spelling
    ):
        import json as _json

        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        install_tail = (
            "```curio.v1\n"
            + _json.dumps({"toolRequest": {"tool": "package.install", "params": {
                "dirName": spelling, "reason": "notes need it",
            }}})
            + "\n```"
        )
        att_id, calls = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=[install_tail, "Proposed."],
        )
        self._write_store_package(key, "curio.notes@1", "curio.notes", "note-surface", "Note")
        resp = self._run(client, token, alice_project, att_id)
        assert resp.status_code == 200
        proposal = next(p for p in resp.get_json()["content"] if p["type"] == "proposal")
        assert proposal["tool"] == "package.install"
        assert proposal["pins"]["dirName"] == "curio.notes@1"  # canonical, not the model's spelling
        (install_result,) = self._results(calls)
        assert install_result.startswith("[tool result] package.install: proposed")

    # dev/105 D2 — a parameter refusal is a millisecond correction, not a
    # provider round. Live: search + two refusals = MAX_TOOL_ROUNDS, and the
    # ladder's AUTHOR rung was unreachable. Here two misses cost nothing and
    # the third request still mints.
    def _install_req(self, dir_name):
        import json as _json

        return (
            "```curio.v1\n"
            + _json.dumps({"toolRequest": {"tool": "package.install", "params": {
                "dirName": dir_name, "reason": "x",
            }}})
            + "\n```"
        )

    def _execution(self, client, token, project_id, att_id):
        turns = client.get(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        return turns[-1]["execution"]

    @staticmethod
    def _results(calls):
        """Every tool result the model was handed, in order. The fake provider
        records the ONE mutable message list by reference, so ``calls[i][-1]``
        is always the run's FINAL message, whatever ``i`` — read the history."""
        return [
            m["content"] for m in calls[-1]
            if m["role"] == "user" and m["content"].startswith("[tool result]")
        ]

    def test_parameter_refusals_do_not_spend_rounds(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        from utk_curio.backend.app.agents.application import tool_rounds as agent_services
        from utk_curio.backend.app.projects.services import _user_dir_key

        assert agent_services.MAX_TOOL_ROUNDS == 3  # the arithmetic below assumes it
        user, token = user_and_token
        key = _user_dir_key(user)
        att_id, calls = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=[
                self._install_req("curio.nothing"),   # free correction 1
                self._install_req("curio.nada"),      # free correction 2
                self._install_req("curio.notes@1"),   # round 1 — mints
                "Proposed.",
            ],
        )
        self._write_store_package(key, "curio.notes@1", "curio.notes", "note-surface", "Note")
        resp = self._run(client, token, alice_project, att_id)
        assert resp.status_code == 200
        proposal = next(p for p in resp.get_json()["content"] if p["type"] == "proposal")
        assert proposal["pins"]["dirName"] == "curio.notes@1"
        # Neither refusal told the model the budget was gone.
        miss1, miss2, minted = self._results(calls)
        assert "not in the Nodes Catalog" in miss1 and "not in the Nodes Catalog" in miss2
        for r in (miss1, miss2, minted):
            assert "No further tool calls" not in r
        execution = self._execution(client, token, alice_project, att_id)
        assert [c["status"] for c in execution["toolCalls"]] == ["refused", "refused", "proposed"]
        assert execution["refusedRounds"] == 2

    def test_refusal_cap_then_refusals_count_as_rounds_until_the_cutoff(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """A model that never corrects still hits dev/73's cap: refusals 3–5
        spend the three rounds, and the request at the cap gets the cutoff
        card instead of silently vanishing."""
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        att_id, calls = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=[
                self._install_req(f"curio.miss{i}") for i in range(5)
            ] + [self._install_req("curio.notes@1"), "never reached"],
        )
        self._write_store_package(key, "curio.notes@1", "curio.notes", "note-surface", "Note")
        resp = self._run(client, token, alice_project, att_id)
        parts = resp.get_json()["content"]
        assert all(p["type"] != "proposal" for p in parts)
        assert any("package.install" in json.dumps(p) and p["type"] != "proposal" for p in parts), parts
        results = self._results(calls)
        assert len(results) == 5
        assert all("No further tool calls" not in r for r in results[:4])
        assert "No further tool calls" in results[4]  # the 5th miss was the last round
        execution = self._execution(client, token, alice_project, att_id)
        assert len(execution["toolCalls"]) == 5
        assert execution["refusedRounds"] == 2

    def test_catalog_unavailable_refusal_still_counts_as_a_round(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """A refusal that cost real work (a broken catalog) is not a parameter
        error — it keeps spending rounds so a dead store can never loop."""
        from utk_curio.backend.app.packages.application import agent_reads
        from utk_curio.backend.app.packages.application import project_packages
        from utk_curio.backend.app.packages.application import store_reads
        from utk_curio.backend.app.packages.application import templates as packages_templates

        def boom(*_a, **_k):
            raise RuntimeError("store on fire")

        monkeypatch.setattr(packages_service, "agent_catalog_overview", boom)
        user, token = user_and_token
        att_id, calls = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=[
                self._install_req("curio.notes@1") for _ in range(4)
            ] + ["never reached"],
        )
        resp = self._run(client, token, alice_project, att_id)
        assert resp.status_code == 200
        results = self._results(calls)
        assert len(results) == 3 and all("Nodes Catalog is unavailable" in r for r in results)
        assert all("No further tool calls" not in r for r in results[:2])
        assert "No further tool calls" in results[2]  # round 3 of 3
        execution = self._execution(client, token, alice_project, att_id)
        assert len(execution["toolCalls"]) == 3  # the 4th request hit the cap
        assert "refusedRounds" not in execution

    # dev/105 S1 — the live roster: twelve built-in CODE templates plus an
    # enlisted Python compute node (not authorable, filtered from Available),
    # and no note template anywhere on the list — so the model reached for the
    # node type it saw on the canvas. A note-composing run is now told, in the
    # roster itself, that nothing listed renders a note and where the rung is.
    def test_roster_says_when_nothing_available_renders_a_note(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        import json as _json

        from utk_curio.backend.app.packages.application import agent_reads
        from utk_curio.backend.app.packages.application import project_packages
        from utk_curio.backend.app.packages.application import store_reads
        from utk_curio.backend.app.packages.application import templates as packages_templates
        from utk_curio.backend.app.packages.repositories.store import user_packages_dir
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        # A compute-only package, enlisted: authorable=False → not listable.
        d = user_packages_dir(key) / "curio.postits@1"
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(_json.dumps({
            "id": "curio.postits", "version": "1.0.0", "name": "Post-it Notes",
            "publisher": "Package Builder", "description": "", "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [], "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "post-it-note", "label": "Post-it Note", "category": "computation",
                "engine": "python", "editor": "none", "hasCode": False,
                "inputPorts": [], "outputPorts": [{"cardinality": "1", "types": ["JSON"]}],
                "source": "sources/default.py",
            }],
            "createdAt": "2026-08-21T16:42:23Z",
        }), encoding="utf-8")
        (d / "sources").mkdir(exist_ok=True)
        (d / "sources" / "default.py").write_text("def main(): return {}\n")
        project_packages.install_to_project(key, alice_project, "curio.postits@1")
        # And the real note template sits in the store, not enlisted.
        self._write_store_package(key, "curio.notes@1", "curio.notes", "note-surface", "Note")

        att_id, calls = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=["ok"],
        )
        self._run(client, token, alice_project, att_id)
        system = calls[0][0]["content"]
        assert "Available node templates" in system  # the built-ins are listed…
        assert "None of these renders a note" in system  # …and named as not-notes
        assert "curio.postits/post-it-note" not in system  # the trap is not offered
        assert "(package curio.notes@1)" in system  # the way out still is

        # The line is for note-composing runs only: enlist the note package and
        # it disappears; a Dataflow Builder never sees it.
        project_packages.install_to_project(key, alice_project, "curio.notes@1")
        att2, calls2 = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=["ok"],
        )
        self._run(client, token, alice_project, att2)
        assert "None of these renders a note" not in calls2[0][0]["content"]
        helper = TestDataflowPlanMint()
        att3, calls3 = helper._setup(
            client, user, token, alice_project, monkeypatch, replies=["ok"],
        )
        helper._run(client, token, alice_project, att3)
        assert "None of these renders a note" not in calls3[0][0]["content"]

    # dev/105 A2 — the A13 default is narrow: a research.notes.compose run, a
    # PRESENTATION template, no color given. Everything else is byte-unchanged.
    def _create_req(self, node_type, **extra):
        import json as _json

        return (
            "```curio.v1\n"
            + _json.dumps({"toolRequest": {"tool": "node.create", "params": {
                "nodeType": node_type, "content": "hello", **extra,
            }}})
            + "\n```"
        )

    def test_a13_default_fills_only_an_omitted_color_on_a_note_template(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        from utk_curio.backend.app.packages.domain import node_appearance
        from utk_curio.backend.app.packages.application import agent_reads
        from utk_curio.backend.app.packages.application import project_packages
        from utk_curio.backend.app.packages.application import store_reads
        from utk_curio.backend.app.packages.application import templates as packages_templates
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        att_id, calls = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=[
                self._create_req("curio.notes/note-surface", title="Question"),        # → yellow
                self._create_req("curio.notes/note-surface", appearance={"backgroundColor": "pink"}),  # wins
                self._create_req("curio.notes/note-surface"),                          # → green (index 2)
                "done",
            ],
        )
        self._write_store_package(key, "curio.notes@1", "curio.notes", "note-surface", "Note")
        project_packages.install_to_project(key, alice_project, "curio.notes@1")
        resp = self._run(client, token, alice_project, att_id)
        spec_nodes_before = None  # proposals only; nothing lands without Apply
        proposals = [p for p in resp.get_json()["content"] if p["type"] == "proposal"]
        assert len(proposals) == 3
        # The mirrored proposals carry the normalized colors + the title.
        att = next(
            a for a in self._spec(client, token, alice_project)["dataflow"]["agentAttachments"]
            if a["attachmentId"] == att_id
        )
        mirrored = [att["activeProposal"]] + list(att.get("queuedProposals") or [])
        by_id = {p["proposalId"]: p for p in mirrored}
        ordered = [by_id[p["proposalId"]] for p in proposals]
        norm = lambda c: node_appearance.normalize_appearance({"backgroundColor": c})
        assert [p.get("appearance") for p in ordered] == [norm("yellow"), norm("pink"), norm("green")]
        assert ordered[0]["title"] == "Question" and "title" not in ordered[1]
        assert spec_nodes_before is None

    def test_a13_default_never_touches_other_agents_or_code_templates(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        from utk_curio.backend.app.packages.application import agent_reads
        from utk_curio.backend.app.packages.application import project_packages
        from utk_curio.backend.app.packages.application import store_reads
        from utk_curio.backend.app.packages.application import templates as packages_templates
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        self._write_store_package(key, "curio.notes@1", "curio.notes", "note-surface", "Note")
        project_packages.install_to_project(key, alice_project, "curio.notes@1")
        # A Researcher creating a CODE node: no default.
        att_id, _ = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=[self._create_req("curio.builtin/computation-analysis"), "done"],
        )
        resp = self._run(client, token, alice_project, att_id)
        (proposal,) = [p for p in resp.get_json()["content"] if p["type"] == "proposal"]
        att = next(
            a for a in self._spec(client, token, alice_project)["dataflow"]["agentAttachments"]
            if a["attachmentId"] == att_id
        )
        assert "appearance" not in att["activeProposal"]
        # A Node Builder creating a NOTE without a color: no default either.
        helper = TestNodeCreate()
        att2, _ = helper._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=[self._create_req("curio.notes/note-surface"), "done"],
        )
        resp2 = helper._run(client, token, alice_project, att2)
        (proposal2,) = [p for p in resp2.get_json()["content"] if p["type"] == "proposal"]
        att2_row = next(
            a for a in self._spec(client, token, alice_project)["dataflow"]["agentAttachments"]
            if a["attachmentId"] == att2
        )
        assert "appearance" not in att2_row["activeProposal"]

    def _spec(self, client, token, project_id):
        return client.get(f"/api/projects/{project_id}", headers=_auth(token)).get_json()["spec"]

    # dev/105 A3 — honest degradation at the install apply: no notes on the
    # request, or a package with no presentation template → enlist only, SAID.
    def _apply(self, client, token, project_id, att_id, proposal_id):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply",
            headers=_auth(token),
        )

    def _turn_texts(self, client, token, project_id, att_id):
        turns = client.get(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        return [t["text"] for t in turns]

    def test_install_apply_without_notes_enlists_only_and_says_so(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        att_id, _ = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=[self._install_req("curio.notes@1"), "ok"],
        )
        self._write_store_package(key, "curio.notes@1", "curio.notes", "note-surface", "Note")
        resp = self._run(client, token, alice_project, att_id)
        (proposal,) = [p for p in resp.get_json()["content"] if p["type"] == "proposal"]
        assert proposal["summary"] == "Install package · Simple Notes"  # no "to follow"
        body = self._apply(client, token, alice_project, att_id, proposal["proposalId"]).get_json()
        assert body["followUpProposals"] == []
        assert body["requiresRegistryRefresh"] is True  # dev/105 A4: enlisting alone changes the lockfile
        assert "No notes rode this request" in self._turn_texts(client, token, alice_project, att_id)[-1]

    def test_install_apply_with_notes_but_no_presentation_template_says_why(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        import json as _json

        from utk_curio.backend.app.packages.repositories.store import user_packages_dir
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        # A store-only CODE package: enlistable, but nothing in it renders a note.
        d = user_packages_dir(key) / "curio.tools@1"
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(_json.dumps({
            "id": "curio.tools", "version": "1.0.0", "name": "Tools", "publisher": "x",
            "description": "", "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [], "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "tool", "label": "Tool", "category": "computation", "engine": "python",
                "editor": "code", "hasCode": True, "inputPorts": [], "outputPorts": [],
                "source": "sources/default.py",
            }],
            "createdAt": "2026-08-21T16:42:23Z",
        }), encoding="utf-8")
        (d / "sources").mkdir(exist_ok=True)
        (d / "sources" / "default.py").write_text("def main(): return {}\n")
        req = (
            "```curio.v1\n"
            + _json.dumps({"toolRequest": {"tool": "package.install", "params": {
                "dirName": "curio.tools@1", "reason": "x",
                "notes": [{"title": "Question", "content": "q?"}],
            }}})
            + "\n```"
        )
        att_id, _ = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=[req, "ok"],
        )
        resp = self._run(client, token, alice_project, att_id)
        (proposal,) = [p for p in resp.get_json()["content"] if p["type"] == "proposal"]
        assert proposal["summary"].endswith("· 1 note to follow")
        body = self._apply(client, token, alice_project, att_id, proposal["proposalId"]).get_json()
        assert body["installedPackage"]["dirName"] == "curio.tools@1"  # enlisted anyway
        assert body["followUpProposals"] == []
        last = self._turn_texts(client, token, alice_project, att_id)[-1]
        assert "has no presentation (note) template" in last

    def test_enlist_miss_hint_names_only_sources_this_run_can_read(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """A true miss refuses with the roster list the Researcher DOES see and
        never with packages.catalog, which it is not granted (DEC-063)."""
        import json as _json

        user, token = user_and_token
        install_tail = (
            "```curio.v1\n"
            + _json.dumps({"toolRequest": {"tool": "package.install", "params": {
                "dirName": "curio.nothing", "reason": "x",
            }}})
            + "\n```"
        )
        att_id, calls = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=[install_tail, "ok"],
        )
        resp = self._run(client, token, alice_project, att_id)
        assert all(p["type"] != "proposal" for p in resp.get_json()["content"])
        (correction,) = self._results(calls)
        assert "not in the Nodes Catalog" in correction
        assert "Installed but NOT enlisted in this project" in correction
        assert "packages.catalog" not in correction

    def test_enlist_then_create_places_a_note_on_the_reused_template(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """The whole rung, end to end: the store-only package is PROPOSABLE
        (it used to refuse as "not in the Nodes Catalog"), applying it enlists
        the package, and the template is then a legal node.create nodeType."""
        import json as _json

        from utk_curio.backend.app.packages.application import agent_reads
        from utk_curio.backend.app.packages.application import project_packages
        from utk_curio.backend.app.packages.application import store_reads
        from utk_curio.backend.app.packages.application import templates as packages_templates
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        install_tail = (
            "```curio.v1\n"
            + _json.dumps({"toolRequest": {"tool": "package.install", "params": {
                "dirName": "curio.notes@1",
                "reason": "the notes template this answer needs already exists",
            }}})
            + "\n```"
        )
        att_id, calls = self._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=[install_tail, "Proposed — review it above."],
        )
        self._write_store_package(key, "curio.notes@1", "curio.notes", "note-surface", "Note")
        assert "curio.notes/note-surface" not in {
            t["id"] for t in packages_templates.available_templates(key, alice_project)
        }

        resp = self._run(client, token, alice_project, att_id)
        assert resp.status_code == 200
        proposal = next(
            p for p in resp.get_json()["content"] if p["type"] == "proposal"
        )
        assert proposal["tool"] == "package.install"
        assert proposal["pins"]["dirName"] == "curio.notes@1"

        applied = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert applied.status_code == 200, applied.get_json()

        # Enlisted: the template the agent wanted to reuse is now instantiable.
        assert "curio.notes/note-surface" in {
            t["id"] for t in packages_templates.available_templates(key, alice_project)
        }

    def test_run_without_the_install_grant_sees_no_enlist_section(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """The section names a door; only a run that can open it is shown one.
        The Node Builder creates nodes but cannot enlist packages."""
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        helper = TestNodeCreate()
        att_id, calls = helper._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=["ok"],
        )
        self._write_store_package(key, "curio.notes@1", "curio.notes", "note-surface", "Note")
        helper._run(client, token, alice_project, att_id)
        system = calls[0][0]["content"]
        assert "Available node templates" in system
        assert "Installed but NOT enlisted" not in system
        assert "(package curio.notes@1)" not in system


class TestDatasetFinderTools:
    """dev/50 — catalog.search grounds the catalog lane in the real Data
    Catalog; dataset.install is the reviewed catalog-lane mutation over the
    existing dataset-only install flow."""

    COORD = "agent.dataset-finder@1.0.0"

    def _seed_dataset(self, user, filename="cities.csv"):
        from utk_curio.backend.app.datasets.install.installer import install_imported_file
        from utk_curio.backend.app.projects.services import _user_dir_key

        result = install_imported_file(
            _user_dir_key(user), b"a,b\n1,2\n", filename, "csv"
        )
        return result.manifest.id

    def _search_tail(self, extra=""):
        return (
            '```curio.v1\n{"toolRequest": {"tool": "catalog.search", '
            f'"params": {{{extra}}}}}}}\n```'
        )

    def _install_tail(self, dataset_id):
        return (
            '```curio.v1\n{"toolRequest": {"tool": "dataset.install", '
            f'"params": {{"datasetId": "{dataset_id}"}}}}}}\n```'
        )

    def _setup(self, client, token, project_id, monkeypatch, replies):
        client.post(f"/api/agents/projects/{project_id}/install", json={"coord": self.COORD}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.solve import session as packages_session
            from utk_curio.backend.app.agents.application.solve import simulation
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import delegates
            from utk_curio.backend.app.agents.application.turns import policy
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return replies[min(len(calls) - 1, len(replies) - 1)]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return att_id, calls

    def _run(self, client, token, project_id, att_id, message="find data"):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
            json={"message": message}, headers=_auth(token),
        )

    def _proposal_from_run(self, response):
        return next(p for p in response.get_json()["content"] if p["type"] == "proposal")

    def _apply(self, client, token, project_id, att_id, proposal_id):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply",
            headers=_auth(token),
        )

    def test_catalog_search_returns_seeded_rows(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        dataset_id = self._seed_dataset(user)
        att_id, calls = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._search_tail(), "Found it."],
        )
        r = self._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        result_msg = calls[1][-1]["content"]
        assert "[tool result] catalog.search: ok" in result_msg
        assert dataset_id in result_msg
        assert '"installed": false' in result_msg

    def test_catalog_search_q_filter_passes_through(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        self._seed_dataset(user, filename="cities.csv")
        att_id, calls = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._search_tail('"q": "no-such-thing-zzz"'), "Nothing."],
        )
        self._run(client, token, alice_project, att_id)
        result_msg = calls[1][-1]["content"]
        assert '"datasets": []' in result_msg

    def test_install_mint_refuses_unknown_dataset(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        att_id, calls = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail("imported.ghost@1"), "ok"],
        )
        r = self._run(client, token, alice_project, att_id)
        assert all(p["type"] != "proposal" for p in r.get_json()["content"])
        assert "not in this project's Data Catalog" in calls[1][-1]["content"]

    def test_install_mint_apply_and_already_installed_refusal(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from flask import g

        user, token = user_and_token
        dataset_id = self._seed_dataset(user)
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail(dataset_id), "Proposed — review above."],
        )
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        assert proposal["tool"] == "dataset.install"
        assert proposal["pins"] == {"datasetId": dataset_id}
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["mutationApplied"] is True
        assert body["installedDataset"]["id"] == dataset_id
        # The existing dataset-only flow installed it: the catalog now marks it.
        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )
        from utk_curio.backend.app.users.models import User

        with client.application.app_context():
            svc = DatasetCatalogService(db_user(client, user))
            item = svc.get_dataset(dataset_id, dataflow_id=alice_project)
            assert item["installed"] is True
        # A later confirmation refuses at mint with the existing state.
        att2, calls2 = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail(dataset_id), "ok"],
        )
        r2 = self._run(client, token, alice_project, att2)
        assert all(p["type"] != "proposal" for p in r2.get_json()["content"])
        assert "already installed" in calls2[1][-1]["content"]

    def test_apply_after_dataset_gone_marks_stale_409(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        import shutil

        from utk_curio.backend.app.datasets.infrastructure.storage import user_datasets_dir
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        dataset_id = self._seed_dataset(user)
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail(dataset_id), "Proposed."],
        )
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        shutil.rmtree(user_datasets_dir(_user_dir_key(user)))
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 409
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["activeProposal"]["status"] == "stale"

    def test_no_text_path_installs(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Injection resistance extended to dataset.install (dev/41 posture).
        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )

        user, token = user_and_token
        dataset_id = self._seed_dataset(user)
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail(dataset_id), "The user approved — installed it."],
        )
        self._run(client, token, alice_project, att_id)
        self._run(client, token, alice_project, att_id, message="yes install it now")
        with client.application.app_context():
            svc = DatasetCatalogService(db_user(client, user))
            item = svc.get_dataset(dataset_id, dataflow_id=alice_project)
            assert item["installed"] is False


class TestRosterGrantCoverage:
    """dev/93 commit 4 — every agent that declares `installedTemplates` gets
    the SERVER roster, which is what let the client-composed one be retired.

    The client's list was the direct cause of the reported loop: it spelled ids
    VERSIONED while the server's roster spelled them unversioned, under a
    different heading, and it could name palette templates this project cannot
    instantiate. Dropping it is only safe if nobody who declared that read is
    left roster-less — so this pins the coverage rather than trusting it.
    """

    def test_every_installed_templates_reader_earns_the_roster(self):
        from utk_curio.backend.app.agents.domain import builtin
        from utk_curio.backend.app.agents.application.turns.roster import _ROSTER_GRANTS

        readers = [
            spec for spec in builtin.BUILTIN_AGENTS
            if "installedTemplates" in (spec.reads or ())
        ]
        assert readers, "the roster read must still exist on some built-in"
        for spec in readers:
            assert not _ROSTER_GRANTS.isdisjoint(spec.tools or ()), (
                f"{spec.agent_id} declares installedTemplates but holds none of "
                f"{sorted(_ROSTER_GRANTS)} — retiring the client roster would "
                "leave it with no template vocabulary at all"
            )

    def test_package_recommendation_run_carries_the_roster(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """It holds package.install and no node.create, so before commit 4 it
        was the agent that would have been stranded."""
        helper = TestDataflowPlanMint()
        user, token = user_and_token
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["noted"], coord="agent.package-recommendation@1.0.0",
        )
        helper._run(client, token, alice_project, att_id)
        assert "Available node templates" in calls[0][0]["content"]

    def test_package_builder_run_carries_the_roster(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """An AUTHORING agent especially needs to see what already exists —
        not seeing it is how one weather question produced two near-identical
        note packages."""
        helper = TestDataflowPlanMint()
        user, token = user_and_token
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["noted"], coord="agent.package-builder@1.0.0",
        )
        helper._run(client, token, alice_project, att_id)
        assert "Available node templates" in calls[0][0]["content"]

    def test_an_agent_with_no_roster_grant_still_gets_none(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """The gate widened, it did not dissolve: the chat agent proposes
        nothing and needs no template vocabulary."""
        helper = TestDataflowPlanMint()
        user, token = user_and_token
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["chatting"], coord="agent.chat-agent@1.0.0",
        )
        helper._run(client, token, alice_project, att_id)
        assert "Available node templates" not in calls[0][0]["content"]


class TestSnapshotCostAndCoherence:
    """dev/99 R1.1/R1.2 through the real agent paths: one snapshot per run,
    and a cost that does not grow with plan size."""

    def _walks_for_plan_of(self, size, client, user_and_token, tmp_curio,
                           alice_project, monkeypatch):
        from utk_curio.backend.app.packages.application import agent_reads
        from utk_curio.backend.app.packages.application import project_packages
        from utk_curio.backend.app.packages.application import store_reads
        from utk_curio.backend.app.packages.application import templates as packages_templates

        helper = TestDataflowPlanMint()
        user, token = user_and_token
        nodes = [
            {"ref": f"n{i}", "nodeType": "curio.builtin/computation-analysis",
             "title": f"Step {i}", "intent": "work"}
            for i in range(size)
        ]
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["plan.\n" + helper._plan_tail(nodes=nodes, edges=[])],
        )
        walks = {"n": 0}
        real = store_reads._store_index
        monkeypatch.setattr(
            store_reads, "_store_index",
            lambda uk: (walks.__setitem__("n", walks["n"] + 1), real(uk))[1],
        )
        body = helper._run(client, token, alice_project, att_id).get_json()
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        assert len(proposal["plan"]["nodes"]) == size
        return walks["n"]

    def test_plan_mint_cost_does_not_grow_with_plan_size(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """The R1.2 invariant, stated as the thing that actually matters: a
        run takes a small CONSTANT number of store snapshots (the roster, the
        fan-in view, the batch resolution) and resolving twelve nodes costs no
        more than resolving two. Before batching, each node re-walked the
        store — and once readers hold the seed lock, re-acquired it."""
        small = self._walks_for_plan_of(
            2, client, user_and_token, tmp_curio, alice_project, monkeypatch,
        )
        large = self._walks_for_plan_of(
            12, client, user_and_token, tmp_curio, alice_project, monkeypatch,
        )
        assert small == large, (
            f"cost scaled with plan size: {small} walks for 2 nodes, {large} for 12"
        )

    def test_roster_halves_come_from_one_snapshot(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """Both roster sections must describe the same instant: fetched
        separately, a package could appear in one half and be missing from the
        other."""
        from utk_curio.backend.app.packages.application import agent_reads
        from utk_curio.backend.app.packages.application import project_packages
        from utk_curio.backend.app.packages.application import store_reads
        from utk_curio.backend.app.packages.application import templates as packages_templates

        user, token = user_and_token
        ladder = TestReuseLadder()
        att_id, calls = ladder._setup(
            client, user=user, token=token, project_id=alice_project,
            monkeypatch=monkeypatch, replies=["ok"],
        )
        from utk_curio.backend.app.projects.services import _user_dir_key
        ladder._write_store_package(
            _user_dir_key(user), "curio.notes@1", "curio.notes", "note-surface", "Note",
        )

        landscapes = {"n": 0}
        real = agent_reads.template_landscape
        monkeypatch.setattr(
            packages_service, "template_landscape",
            lambda uk, pid: (landscapes.__setitem__("n", landscapes["n"] + 1), real(uk, pid))[1],
        )
        ladder._run(client, token, alice_project, att_id)
        system = calls[0][0]["content"]

        assert "Available node templates" in system
        assert "Installed but NOT enlisted in this project" in system
        assert landscapes["n"] == 1, "both roster halves must share ONE snapshot"


class TestPlanCorrectionRounds:
    """dev/54 — the primary path made self-correcting: imperfect plan
    attempts feed precise errors back and re-round; failure at the cap is
    loud, never silent."""

    def _bad_json_tail(self):
        # A realistic slip: unquoted key — JSON breakage.
        return '```curio.v1\n{"dataflowPlan": {"goal": "g", nodes: []}}\n```'

    def _wrong_id_tail(self):
        import json as _json

        plan = {"goal": "g", "nodes": [
            {"ref": "a", "nodeType": "data-loading",  # missing package prefix
             "title": "Load", "intent": "load"},
        ], "edges": []}
        return f"```curio.v1\n{_json.dumps({'dataflowPlan': plan})}\n```"

    def test_invalid_json_then_corrected_mints(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[
                "Attempt one.\n" + self._bad_json_tail(),
                "Here we go.\n" + helper._plan_tail(),
            ],
        )
        r = helper._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        body = r.get_json()
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        assert proposal["tool"] == "dataflow.plan.write"
        # The correction round carried the precise error.
        correction = calls[1][-1]["content"]
        assert "[plan validation]" in correction
        assert "not valid JSON" in correction
        # The invalid attempt never reached the user: no raw tail, no
        # attempt-one prose in the persisted reply.
        assert "curio.v1" not in body["reply"]
        assert "Attempt one." not in body["reply"]
        assert body["reply"].startswith("Here we go.")

    def test_wrong_template_id_then_corrected_mints(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The previously dead one-shot mint refusal now self-corrects.
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[
                "Try.\n" + self._wrong_id_tail(),
                "Fixed.\n" + helper._plan_tail(),
            ],
        )
        r = helper._run(client, token, alice_project, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        assert proposal["status"] == "pending"
        assert "not an available template" in calls[1][-1]["content"]

    def test_persistent_failure_caps_loudly(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Nope.\n" + self._bad_json_tail()],  # repeats forever
        )
        r = helper._run(client, token, alice_project, att_id)
        body = r.get_json()
        # Three corrective rounds (dev/73: MAX_TOOL_ROUNDS=3) consumed the
        # shared budget; the fourth attempt fails LOUDLY: the raw tail is
        # released (fail-open transparency) and the error card explains.
        assert len(calls) == 4
        assert all(p["type"] != "proposal" for p in body["content"])
        card = next(p for p in body["content"] if p["type"] == "card")
        assert card["title"] == "Plan not proposable"
        assert "not valid JSON" in card["lines"][0]
        assert "curio.v1" in body["reply"]  # the model's text is never lost

    def test_plan_rounds_share_the_tool_budget(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # A tool round plus corrective rounds draw from ONE budget: read tool
        # (1) + correction (2) + still-bad plan → cap.
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        read_tail = '```curio.v1\n{"toolRequest": {"tool": "dataflow.read", "params": {}}}\n```'
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[read_tail, "Plan.\n" + self._bad_json_tail()],
        )
        r = helper._run(client, token, alice_project, att_id)
        body = r.get_json()
        # calls: tool round, bad plan, correction, correction (script repeats
        # bad; dev/73 budget = 3) → cap.
        assert len(calls) == 4
        assert any(p["type"] == "card" and p["title"] == "Plan not proposable" for p in body["content"])

    def test_ungranted_agents_keep_failopen_behavior(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Regression: a non-plan agent's invalid plan-ish tail streams as raw
        # text exactly as before — no corrections, no cards.
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            coord="agent.chat-agent@1.0.0",
            replies=["idea!\n" + self._bad_json_tail()],
        )
        body = helper._run(client, token, alice_project, att_id).get_json()
        assert len(calls) == 1
        assert "curio.v1" in body["reply"]
        assert all(p.get("type") != "card" for p in body["content"])

    def test_stream_correction_holds_raw_tail_and_emits_plan_revision(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        import json as _json

        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(client, user, token, alice_project, monkeypatch, replies=["ignored"])
        script = [
            "Attempt.\n" + self._bad_json_tail(),
            "Done.\n" + helper._plan_tail(),
        ]
        calls = []

        def _fake_stream(config, messages, **kwargs):
            calls.append(messages)
            reply = script[min(len(calls) - 1, 1)]
            for i in range(0, len(reply), 9):
                yield reply[i : i + 9]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _fake_stream)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "plan it"}, headers=_auth(token),
        )
        events = []
        for block in r.get_data(as_text=True).strip().split("\n\n"):
            lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
            events.append((lines["event"], _json.loads(lines["data"])))
        kinds = [k for k, _ in events]
        assert (
            kinds.index("plan_revision")
            < kinds.index("review_required")
            < kinds.index("done")
        )
        # The invalid tail never streamed as text.
        text = "".join(p.get("text", "") for k, p in events if k == "delta")
        assert "curio.v1" not in text
        done = events[-1][1]
        assert any(p["type"] == "proposal" for p in done["content"])


class TestPlanToolRequestForm:
    """dev/55 — the grants paragraph teaches the generic toolRequest syntax,
    so the runtime honors it: both plan forms mint identically."""

    def _tool_form_tail(self, nested=True, bad_type=False):
        import json as _json

        plan = {
            "goal": "heat analysis",
            "nodes": [
                {"ref": "a",
                 "nodeType": "data-loading" if bad_type else "curio.builtin/computation-analysis",
                 "title": "Load", "intent": "load the data"},
                {"ref": "b", "nodeType": "curio.builtin/computation-analysis",
                 "title": "Analyze", "intent": "compute stats"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        }
        params = {"dataflowPlan": plan} if nested else plan
        body = _json.dumps({"toolRequest": {"tool": "dataflow.plan.write", "params": params}})
        return f"```curio.v1\n{body}\n```"

    def _run_with(self, client, user, token, project_id, monkeypatch, replies):
        helper = TestDataflowPlanMint()
        att_id, calls = helper._setup(client, user, token, project_id, monkeypatch, replies=replies)
        r = helper._run(client, token, project_id, att_id)
        return r, calls

    def test_nested_tool_form_mints_the_same_proposal(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        r, _ = self._run_with(
            client, user, token, alice_project, monkeypatch,
            replies=["Planning.\n" + self._tool_form_tail(nested=True), "Proposed — review above."],
        )
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        assert proposal["tool"] == "dataflow.plan.write"
        assert proposal["status"] == "pending"
        assert [n["title"] for n in proposal["plan"]["nodes"]] == ["Load", "Analyze"]

    def test_direct_params_tool_form_mints_too(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        r, _ = self._run_with(
            client, user, token, alice_project, monkeypatch,
            replies=["Planning.\n" + self._tool_form_tail(nested=False), "Proposed."],
        )
        assert any(p["type"] == "proposal" for p in r.get_json()["content"])

    def test_large_tool_form_plan_parses_and_mints(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        import json as _json

        user, token = user_and_token
        plan = {"goal": "big", "nodes": [
            {"ref": f"n{i}", "nodeType": "curio.builtin/computation-analysis",
             "title": f"Step {i}", "intent": "y" * 200}
            for i in range(40)
        ], "edges": []}
        body = _json.dumps({"toolRequest": {"tool": "dataflow.plan.write", "params": {"dataflowPlan": plan}}})
        assert len(body.encode()) > 4096  # past the classic caps
        r, _ = self._run_with(
            client, user, token, alice_project, monkeypatch,
            replies=[f"Planning.\n```curio.v1\n{body}\n```", "Proposed."],
        )
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        assert len(proposal["plan"]["nodes"]) == 40

    def test_invalid_tool_form_feeds_errors_back_and_corrects(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The user's exact scenario: the model uses the toolRequest syntax with
        # a wrong template id — previously "no proposal flow exists" and the
        # model apologizing; now the refusal carries the errors and the next
        # round mints.
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        r, calls = self._run_with(
            client, user, token, alice_project, monkeypatch,
            replies=[
                "Planning.\n" + self._tool_form_tail(bad_type=True),
                "Fixed.\n" + helper._plan_tail(),
            ],
        )
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        assert proposal["status"] == "pending"
        feedback = calls[1][-1]["content"]
        assert "dataflow.plan.write" in feedback
        assert "not an available template" in feedback
        assert "no proposal flow exists" not in feedback

    def test_other_tools_params_cap_is_regression_pinned(self):
        import json as _json

        from utk_curio.backend.app.agents.domain import content as content_mod

        big = {"toolRequest": {"tool": "node.read", "params": {"x": "y" * 2000}}}
        assert content_mod.parse_parts(_json.dumps(big)) is None


class TestToolRequestRecovery:
    """#245 — a tool request the parser could not take must never fold into the
    chat as raw JSON.

    Plans got fence-agnostic recognition (dev/56) and correction rounds
    (dev/54); tool requests never did, so a node.create in a ```json fence, or
    one followed by a closing sentence, or one whose params were correctable,
    was demoted to inert text — and for a mutate tool that text is a whole
    source file rendered under an Apply button that never existed.
    """

    def _helper(self):
        return TestNodeCreate()

    def _json_fence(self, content="print('recovered')", trailing="Click Apply above."):
        import json as _json

        block = _json.dumps({"toolRequest": {"tool": "node.create", "params": {
            "nodeType": "curio.builtin/computation-analysis", "content": content}}})
        return f"Here is the node.\n\n```json\n{block}\n```\n\n{trailing}"

    def _run(self, client, user, token, project, monkeypatch, replies):
        helper = self._helper()
        att_id, calls = helper._setup(
            client, user=user, token=token, project_id=project,
            monkeypatch=monkeypatch, replies=replies,
        )
        return helper._run(client, token, project, att_id), calls, att_id, helper

    def test_json_fence_request_mints_and_strips_the_block(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        r, calls, _, _ = self._run(
            client, user, token, alice_project, monkeypatch,
            replies=[self._json_fence(), "Proposed."],
        )
        body = r.get_json()
        assert any(p["type"] == "proposal" for p in body["content"])
        # The block is stripped; the model's own prose survives.
        assert "toolRequest" not in body["reply"]
        assert "```" not in body["reply"]
        assert "Click Apply above." in body["reply"]

    def test_non_terminal_curio_fence_is_recovered(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # extract_content deliberately refuses a non-terminal block (dev/90
        # A10's conservative boundary); recovery claims it at the runtime layer.
        import json as _json

        user, token = user_and_token
        block = _json.dumps({"toolRequest": {"tool": "node.create", "params": {
            "nodeType": "curio.builtin/computation-analysis", "content": "print(1)"}}})
        reply = f"Adding it.\n\n```curio.v1\n{block}\n```\n\nDone."
        r, _, _, _ = self._run(client, user, token, alice_project, monkeypatch,
                               replies=[reply, "Proposed."])
        body = r.get_json()
        assert any(p["type"] == "proposal" for p in body["content"])
        assert "toolRequest" not in body["reply"]

    def test_large_content_survives_recovery(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Both halves of #245 at once: a wrong fence AND a body past the old cap.
        user, token = user_and_token
        source = "import pandas as pd\n# analysis\n" * 400
        r, _, att_id, helper = self._run(
            client, user, token, alice_project, monkeypatch,
            replies=[self._json_fence(content=source), "Proposed."],
        )
        proposal = helper._proposal_from_run(r)
        assert proposal["tool"] == "node.create"
        assert "import pandas" not in r.get_json()["reply"]
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.get_json()["createdNode"]["content"] == source.strip()

    def test_broken_json_request_corrects_then_mints(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        broken = ('Attempt one.\n\n```curio.v1\n'
                  '{"toolRequest": {"tool": "node.create", "params": {oops}\n```')
        helper = self._helper()
        r, calls, _, _ = self._run(
            client, user, token, alice_project, monkeypatch,
            replies=[broken, helper._create_tail_json(content="print('fixed')"), "Proposed."],
        )
        assert len(calls) >= 2
        # `calls` aliases the live message list, so scan the whole conversation
        # rather than indexing a snapshot that no longer exists.
        feedback = "\n".join(m["content"] for m in calls[-1] if isinstance(m.get("content"), str))
        assert "[tool validation]" in feedback
        assert "not valid JSON" in feedback
        body = r.get_json()
        assert any(p["type"] == "proposal" for p in body["content"])
        # The invalid attempt never reaches the user — not its prose, not its JSON.
        assert "Attempt one." not in body["reply"]
        assert "toolRequest" not in body["reply"]

    def test_oversized_content_corrects_instead_of_leaking(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Past PROPOSAL_CONTENT_MAX_CHARS the parser and the mint agree, so the
        # model gets a correctable refusal naming the real field.
        from utk_curio.backend.app.agents.domain import content as content_mod

        user, token = user_and_token
        helper = self._helper()
        r, calls, _, _ = self._run(
            client, user, token, alice_project, monkeypatch,
            replies=[
                helper._create_tail_json(
                    content="x" * (content_mod.PROPOSAL_CONTENT_MAX_CHARS + 1)),
                helper._create_tail_json(content="print('small enough')"),
                "Proposed.",
            ],
        )
        feedback = "\n".join(m["content"] for m in calls[-1] if isinstance(m.get("content"), str))
        assert "[tool validation]" in feedback
        assert "params.content is" in feedback  # the error names the real field
        body = r.get_json()
        assert any(p["type"] == "proposal" for p in body["content"])
        assert "x" * 200 not in body["reply"]

    def test_persistent_failure_contains_the_raw_json(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        """The deliberate inverse of the plan cap, which asserts
        ``"curio.v1" in body["reply"]``.

        A plan tail is a spec the user can read, so dev/54 releases it at the
        cap. A mutate request's params are an entire source file — releasing
        that IS the #245 bug, so the block drops and the card explains instead.
        """
        user, token = user_and_token
        broken = ('```curio.v1\n{"toolRequest": {"tool": "node.create", '
                  '"params": {oops}\n```')
        r, calls, _, _ = self._run(client, user, token, alice_project, monkeypatch,
                                   replies=[broken])
        body = r.get_json()
        assert len(calls) == 4  # the shared MAX_TOOL_ROUNDS budget, then the cap
        assert all(p["type"] != "proposal" for p in body["content"])
        card = next(p for p in body["content"] if p["type"] == "card")
        assert card["title"] == "Proposal not created"
        assert "not valid JSON" in card["lines"][0]
        assert "curio.v1" not in body["reply"]
        assert "toolRequest" not in body["reply"]

    def test_echoed_syntax_does_not_burn_a_round(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The tail instruction's own literal template is valid JSON. Correcting
        # a model that merely quoted it would spend the budget on nothing.
        user, token = user_and_token
        echoed = ('To create a node I would send:\n\n```json\n'
                  '{"toolRequest": {"tool": "<tool id>", "params": {}}}\n```')
        r, calls, _, _ = self._run(client, user, token, alice_project, monkeypatch,
                                   replies=[echoed])
        assert len(calls) == 1
        assert "<tool id>" in r.get_json()["reply"]  # fail-open, untouched

    def test_ungranted_tool_is_not_claimed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # A request naming a tool this run does not hold stays the model's text.
        import json as _json

        user, token = user_and_token
        block = _json.dumps({"toolRequest": {"tool": "package.install",
                                             "params": {"dirName": "x@1"}}})
        r, calls, _, _ = self._run(client, user, token, alice_project, monkeypatch,
                                   replies=[f"Consider:\n\n```json\n{block}\n```"])
        assert len(calls) == 1
        assert "package.install" in r.get_json()["reply"]

    def test_stream_holds_the_raw_request_tail(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        import json as _json

        user, token = user_and_token
        helper = self._helper()
        att_id, _ = helper._setup(client, user=user, token=token, project_id=alice_project,
                                  monkeypatch=monkeypatch, replies=["ignored"])
        script = [
            '```curio.v1\n{"toolRequest": {"tool": "node.create", "params": {oops}\n```',
            helper._create_tail_json(content="print('fixed')"),
            "Proposed.",
        ]
        calls = []

        def _fake_stream(config, messages, **kwargs):
            calls.append(messages)
            reply = script[min(len(calls) - 1, len(script) - 1)]
            for i in range(0, len(reply), 9):
                yield reply[i:i + 9]

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _fake_stream)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "build it"}, headers=_auth(token),
        )
        events = []
        for block in r.get_data(as_text=True).strip().split("\n\n"):
            lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
            if "event" in lines:
                events.append((lines["event"], _json.loads(lines["data"])))
        kinds = [k for k, _ in events]
        assert "tool_revision" in kinds
        # The invalid tail never streamed as text.
        text = "".join(p.get("text", "") for k, p in events if k == "delta")
        assert "curio.v1" not in text and "toolRequest" not in text
        done = events[-1][1]
        assert any(p["type"] == "proposal" for p in done["content"])


class TestFenceAgnosticPlanRecognition:
    """dev/56 — the user's exact scenario: a valid plan in a ```json fence
    with prose after it must mint; the runtime meets the model where it
    writes."""

    def _json_fence_reply(self, bad_type=False, trailing="Click the Apply button above to place it."):
        import json as _json

        plan = {
            "goal": "heat analysis",
            "nodes": [
                {"ref": "a",
                 "nodeType": "data-loading" if bad_type else "curio.builtin/computation-analysis",
                 "title": "Load", "intent": "load the data"},
                {"ref": "b", "nodeType": "curio.builtin/computation-analysis",
                 "title": "Analyze", "intent": "compute stats"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        }
        return (
            "Here is your plan:\n\n```json\n"
            + _json.dumps({"dataflowPlan": plan}, indent=2)
            + "\n```\n\n"
            + trailing
        )

    def test_valid_json_fence_plan_mints_and_strips_the_block(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[self._json_fence_reply()],
        )
        r = helper._run(client, token, alice_project, att_id)
        body = r.get_json()
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        assert proposal["tool"] == "dataflow.plan.write"
        assert proposal["status"] == "pending"
        # The prose stays; the raw JSON block is gone — the card is the home.
        assert "Here is your plan:" in body["reply"]
        assert "```" not in body["reply"]
        # The mirror drives the strip Apply button too.
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["activeProposal"]["tool"] == "dataflow.plan.write"
        assert cards[0]["builderSession"]["phase"] == "plan_review"

    def test_invalid_json_fence_plan_corrects_with_fence_guidance(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=[
                self._json_fence_reply(bad_type=True),
                "Fixed.\n" + helper._plan_tail(),
            ],
        )
        r = helper._run(client, token, alice_project, att_id)
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        assert proposal["status"] == "pending"
        feedback = calls[1][-1]["content"]
        assert "not an available template" in feedback
        assert "curio.v1" in feedback  # the fence guidance

    def test_remove_only_bare_json_fence_mints(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # dev/61 — the "clear the canvas" scenario: a BARE remove-only plan
        # (no "nodes" key) in a ```json fence must mint, not leak.
        import json as _json

        user, token = user_and_token
        helper = TestDestructiveReplan()
        plan = {"goal": "clear the canvas",
                "removeNodes": ["old-loader", "cleaner"], "removeEdges": []}
        reply = (
            "Removing everything:\n\n```json\n"
            + _json.dumps(plan, indent=2)
            + "\n```\n\nReview and apply the plan."
        )
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch, replies=[reply],
        )
        body = helper._run(client, token, alice_project, att_id, message="clear the canvas").get_json()
        proposal = next(p for p in body["content"] if p["type"] == "proposal")
        assert {v["id"] for v in proposal["plan"]["removals"]} == {"old-loader", "cleaner"}
        assert "```" not in body["reply"]
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["builderSession"]["phase"] == "plan_review"

    def test_ungranted_agents_keep_json_fences_verbatim(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            coord="agent.chat-agent@1.0.0",
            replies=[self._json_fence_reply()],
        )
        body = helper._run(client, token, alice_project, att_id).get_json()
        assert len(calls) == 1
        assert "```json" in body["reply"]  # byte-identical for non-plan agents
        assert all(p["type"] != "proposal" for p in body["content"])

    def test_stream_json_fence_plan_mints_with_review_required(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        import json as _json

        user, token = user_and_token
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(client, user, token, alice_project, monkeypatch, replies=["ignored"])
        reply = self._json_fence_reply()
        calls = []

        def _fake_stream(config, messages, **kwargs):
            calls.append(messages)
            for i in range(0, len(reply), 11):
                yield reply[i : i + 11]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn', _fake_stream)
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "plan it"}, headers=_auth(token),
        )
        events = []
        for block in r.get_data(as_text=True).strip().split("\n\n"):
            lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
            events.append((lines["event"], _json.loads(lines["data"])))
        kinds = [k for k, _ in events]
        assert "review_required" in kinds
        done = events[-1][1]
        assert any(p["type"] == "proposal" for p in done["content"])
        assert "```" not in done["reply"]


class TestVerifiedDiscovery:
    """dev/67-4 (DEC-053) — the Dataset Finder stops laundering: every
    external candidate row carries a deterministic verification verdict, and
    research.verify delegates receive runtime-verified evidence (DEC-046
    children are tool-less — the runtime verifies, the child synthesizes)."""

    def _candidates_reply(self, rows):
        import json as _json

        payload = {"datasetCandidates": {"lanes": {"external": rows, "catalog": []}}}
        return f"Here are candidate sources.\n```curio.v1\n{_json.dumps(payload)}\n```"

    def test_external_rows_carry_verification_verdicts(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **kw: (
                {"status": "verified", "httpStatus": 200, "checkedAt": "now",
                 "provider": "socrata", "datasetId": "abcd-1234"}
                if url else
                {"status": "unverified", "detail": "no probeable URL — the identifier was never checked",
                 "checkedAt": "now"}
            ),
        )
        rows = [
            {"name": "Chicago Heat", "sourceType": "api",
             "url": "https://data.cityofchicago.org/resource/abcd-1234.json"},
            {"name": "Some Portal Guess", "sourceType": "portal"},  # no URL
        ]
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch,
            coord="agent.dataset-finder@1.0.0",
            replies=[self._candidates_reply(rows)],
        )
        body = helper._run(client, token, alice_project, att_id).get_json()
        part = next(p for p in body["content"] if p["type"] == "datasetCandidates")
        verified, unverified = part["lanes"]["external"]
        assert verified["verification"]["status"] == "verified"
        assert verified["verification"]["datasetId"] == "abcd-1234"
        # A row with no probeable URL is LOUDLY unverified — never implied.
        assert unverified["verification"]["status"] == "unverified"
        assert "never checked" in unverified["verification"]["detail"]

    def test_rows_carry_the_access_verdict_and_a_manual_row_its_steps(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """dev/132: the same probe now also answers *what can you do with it* —
        fetch it (delegate the code) or download it from the portal (steps +
        Import). Read from the observation, never from the row's prose."""
        user, token = user_and_token
        observations = {
            "https://data.cityofchicago.org/resource/abcd-1234.json": {
                "status": "verified", "httpStatus": 200,
                "contentType": "application/json", "sampleKeys": ["a"], "checkedAt": "now",
            },
            "https://geosampa.prefeitura.sp.gov.br/downloads": {
                "status": "verified", "httpStatus": 200, "contentType": "text/html",
                "pageTitle": "GeoSampa — Downloads", "checkedAt": "now",
            },
        }
        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **kw: observations.get(url) or {
                "status": "unverified", "detail": "no probeable URL", "checkedAt": "now",
            },
        )
        rows = [
            {"name": "Chicago Heat", "sourceType": "api",
             "url": "https://data.cityofchicago.org/resource/abcd-1234.json"},
            {"name": "Setores GeoSampa", "sourceType": "portal", "format": "Shapefile (zip)",
             "url": "https://geosampa.prefeitura.sp.gov.br/downloads"},
        ]
        helper = TestDataflowPlanMint()
        att_id, _ = helper._setup(
            client, user, token, alice_project, monkeypatch,
            coord="agent.dataset-finder@1.0.0",
            replies=[self._candidates_reply(rows)],
        )
        body = helper._run(client, token, alice_project, att_id).get_json()
        part = next(p for p in body["content"] if p["type"] == "datasetCandidates")
        api_row, portal_row = part["lanes"]["external"]
        assert api_row["access"] == "fetchable"
        assert "application/json" in api_row["accessWhy"]
        assert "downloadSteps" not in api_row  # nothing to teach: code fetches it
        assert portal_row["access"] == "manual-download"
        assert "GeoSampa" in portal_row["accessWhy"]
        steps = portal_row["downloadSteps"]
        assert steps[0].endswith("https://geosampa.prefeitura.sp.gov.br/downloads")
        assert "Shapefile (zip)" in " ".join(steps)
        assert steps[-1].startswith("Then use Import dataset below")

    def test_research_verify_delegates_get_runtime_evidence(self, tmp_curio, monkeypatch):
        from utk_curio.backend.app.agents.application import catalog
        from utk_curio.backend.app.agents.application.solve import session as packages_session
        from utk_curio.backend.app.agents.application.solve import simulation
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.turns import delegates
        from utk_curio.backend.app.agents.application.turns import policy
        from utk_curio.backend.app.agents.application.turns import titles
        from utk_curio.backend.app.agents.infrastructure import providers

        monkeypatch.setattr(
            'utk_curio.backend.app.agents.application.verify.verify_external_source',
            lambda url, **kw: {"status": "unreachable", "httpStatus": 404,
                               "detail": "the endpoint answered 404", "checkedAt": "now"},
        )
        enriched = delegates._enriched_delegate_inputs(
            "4242", "p-any", {}, "research.verify",
            {"url": "https://data.example.gov/resource/fake-0000.json", "question": "does it exist?"},
        )
        assert enriched["verification"]["status"] == "unreachable"
        assert enriched["question"] == "does it exist?"  # model keys survive
        # No URL → no fabricated evidence.
        assert delegates._enriched_delegate_inputs(
            "4242", "p-any", {}, "research.verify", {"question": "?"},
        ) == {"question": "?"}

    def test_researcher_is_installable_and_grants_web_tools(self, client, user_and_token, tmp_curio, alice_project):
        user, token = user_and_token
        r = client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": "agent.node-researcher@1.0.0"}, headers=_auth(token),
        )
        assert r.status_code == 201
        from utk_curio.backend.app.agents.domain import builtin

        m = builtin.get_builtin_manifest("agent.node-researcher@1.0.0")
        assert [t.id for t in m.tools] == ["web.search", "web.fetch", "node.read"]
        assert m.capability_ids == ["research.verify", "research.summarize"]


class TestPackageRecommendationTools:
    """dev/84 — packages.catalog grounds recommendations in the real Nodes
    Catalog; package.install is the reviewed mutation over the existing
    package install flow (permissions dialog client-side, conflict re-check
    and lockfile write server-side)."""

    COORD = "agent.package-recommendation@1.0.0"
    PKG = "curio.weather@1"

    @pytest.fixture(autouse=True)
    def _stub_pip(self, monkeypatch):
        # The weather fixture declares real python deps; never shell out to
        # pip inside a test (same posture as test_packages/conftest.py).
        from utk_curio.backend.app.packages.infrastructure import pip_runner
        from utk_curio.backend.app.packages.infrastructure.pip_runner import InstallReport

        monkeypatch.setattr(
            pip_runner, "install_python_deps",
            lambda deps: InstallReport(installed=[], skipped=list(deps or {})),
        )

    def _catalog_tail(self, extra=""):
        return (
            '```curio.v1\n{"toolRequest": {"tool": "packages.catalog", '
            f'"params": {{{extra}}}}}}}\n```'
        )

    def _install_tail(self, dir_name, reason="the proposed node imports rasterio"):
        return (
            '```curio.v1\n{"toolRequest": {"tool": "package.install", '
            f'"params": {{"dirName": "{dir_name}", "reason": "{reason}"}}}}}}\n```'
        )

    def _setup(self, client, token, project_id, monkeypatch, replies):
        client.post(
            f"/api/agents/projects/{project_id}/install",
            json={"coord": self.COORD}, headers=_auth(token),
        )
        att_id = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        calls = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents.application import catalog
            from utk_curio.backend.app.agents.application.solve import session as packages_session
            from utk_curio.backend.app.agents.application.solve import simulation
            from utk_curio.backend.app.agents.application import spec_reads
            from utk_curio.backend.app.agents.application.turns import delegates
            from utk_curio.backend.app.agents.application.turns import policy
            from utk_curio.backend.app.agents.application.turns import titles
            from utk_curio.backend.app.agents.infrastructure import providers

            if messages and messages[0].get("content") == titles.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return replies[min(len(calls) - 1, len(replies) - 1)]

        monkeypatch.setattr('utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn', _fake_run)
        return att_id, calls

    def _run(self, client, token, project_id, att_id, message="what packages do I need"):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
            json={"message": message}, headers=_auth(token),
        )

    def _proposal_from_run(self, response):
        return next(p for p in response.get_json()["content"] if p["type"] == "proposal")

    def _apply(self, client, token, project_id, att_id, proposal_id):
        return client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply",
            headers=_auth(token),
        )

    def _lockfile(self, client, user, project_id):
        from utk_curio.backend.app.packages.application.project_packages import get_project_lockfile
        from utk_curio.backend.app.projects.services import _user_dir_key

        with client.application.app_context():
            return get_project_lockfile(_user_dir_key(user), project_id)

    def test_packages_catalog_tool_grounds_the_rows(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        att_id, calls = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._catalog_tail(), "Here are the options."],
        )
        r = self._run(client, token, alice_project, att_id)
        assert r.status_code == 200
        result_msg = calls[1][-1]["content"]
        assert "[tool result] packages.catalog: ok" in result_msg
        assert self.PKG in result_msg
        assert '"builtin": true' in result_msg  # curio.builtin row flagged

    def test_install_mint_apply_writes_the_project_lockfile(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail(self.PKG), "Proposed — review above."],
        )
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        assert proposal["tool"] == "package.install"
        assert proposal["pins"] == {"dirName": self.PKG}
        assert "rasterio" in proposal["preview"]  # the why-needed rationale
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["mutationApplied"] is True
        assert body["installedPackage"] == {"dirName": self.PKG, "name": "Weather Analysis"}
        assert self.PKG in self._lockfile(client, user, alice_project)

    def test_apply_says_when_an_installed_library_cannot_be_imported(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        """The applied turn is the last place this is connectable to the package.

        pip counts matching metadata as satisfaction, so a wheel whose native
        extension cannot load installs without complaint - and this apply threw
        the install's verdict away, logged "Applied: package installed", and
        left the user to meet it as a node ImportError with nothing tying the
        two together. Reported, not refused: the package IS installed and the
        repair is the user's.
        """
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        monkeypatch.setattr(
            pip_runner, "import_failures",
            lambda deps: {"rasterio": "ImportError: DLL load failed"},
        )
        user, token = user_and_token
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail(self.PKG), "Proposed - review above."],
        )
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])

        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        # The install stands ...
        assert body["mutationApplied"] is True
        assert self.PKG in self._lockfile(client, user, alice_project)
        # ... and it says which library and why.
        assert body["importErrors"] == {"rasterio": "ImportError: DLL load failed"}

        turns = client.get(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        ).get_json()["turns"]
        applied = [t for t in turns if "package installed" in json.dumps(t)]
        assert applied, turns
        text = json.dumps(applied[-1])
        assert "rasterio" in text and "cannot be imported" in text, text

    def test_apply_stays_quiet_when_the_libraries_work(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        """The success control: a working package must not grow a warning."""
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        monkeypatch.setattr(pip_runner, "import_failures", lambda deps: {})
        user, token = user_and_token
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail(self.PKG), "Proposed - review above."],
        )
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])

        body = resp.get_json()
        assert body["mutationApplied"] is True
        assert "importErrors" not in body, body

    def test_mint_refuses_builtin_unknown_and_installed(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.packages.application.project_packages import install_to_project
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        att_id, calls = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail("curio.builtin@1"), "ok"],
        )
        r = self._run(client, token, alice_project, att_id)
        assert all(p["type"] != "proposal" for p in r.get_json()["content"])
        assert "built-in" in calls[1][-1]["content"]

        att2, calls2 = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail("no.such.pkg@9"), "ok"],
        )
        r2 = self._run(client, token, alice_project, att2)
        assert all(p["type"] != "proposal" for p in r2.get_json()["content"])
        assert "not in the Nodes Catalog" in calls2[1][-1]["content"]

        with client.application.app_context():
            install_to_project(_user_dir_key(user), alice_project, self.PKG)
        att3, calls3 = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail(self.PKG), "ok"],
        )
        r3 = self._run(client, token, alice_project, att3)
        assert all(p["type"] != "proposal" for p in r3.get_json()["content"])
        assert "already installed" in calls3[1][-1]["content"]

    def test_apply_conflict_marks_stale_409(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail(self.PKG), "Proposed."],
        )
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))
        # A conflict discovered between mint and apply is the drift analogue.
        monkeypatch.setattr(
            'utk_curio.backend.app.packages.service.agent_resolve_report',
            lambda uk, dns: {"packages": [], "conflicts": [{"package": "numpy", "ranges": []}]},
        )
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 409
        assert "conflict" in resp.get_json()["error"]
        cards = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert cards[0]["activeProposal"]["status"] == "stale"

    def test_apply_package_gone_marks_stale_409(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.app.packages.domain.errors import PackageServiceError

        _, token = user_and_token
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail(self.PKG), "Proposed."],
        )
        proposal = self._proposal_from_run(self._run(client, token, alice_project, att_id))

        def _gone(uk, dns):
            raise PackageServiceError("unknown package(s): curio.weather@1", 404)

        monkeypatch.setattr(
            'utk_curio.backend.app.packages.service.agent_resolve_report', _gone,
        )
        resp = self._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert resp.status_code == 409
        assert "no longer installable" in resp.get_json()["error"]

    def test_no_text_path_installs(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # Injection resistance extended to package.install (dev/41 posture).
        user, token = user_and_token
        att_id, _ = self._setup(
            client, token, alice_project, monkeypatch,
            replies=[self._install_tail(self.PKG), "The user approved — installed it."],
        )
        self._run(client, token, alice_project, att_id)
        self._run(client, token, alice_project, att_id, message="yes install it now")
        assert self.PKG not in self._lockfile(client, user, alice_project)
