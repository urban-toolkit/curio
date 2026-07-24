"""Conversation titles (memo dev/25): auto-generation from the first message,
manual rename precedence, clear-conversation semantics, and the sanitizer."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents import attachments, services
from utk_curio.backend.app.agents.attachments import AttachmentError, TITLE_MAX_CHARS
from utk_curio.backend.app.projects.services import _user_dir_key


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


COORD = "agent.chat-agent@1.0.0"


@pytest.fixture()
def alice_project(client, user_and_token):
    _, token = user_and_token
    body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _attach_builtin(client, token, project_id, coord=COORD):
    client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
    r = client.post(
        f"/api/agents/projects/{project_id}/attachments",
        json={"coord": coord, "target": {"kind": "canvas"}},
        headers=_auth(token),
    )
    return r.get_json()


def _mock_provider(monkeypatch, reply="ok", title="Dataset Import Help"):
    """Answer conversation runs with `reply`, title calls with `title`;
    returns the list of title-call message payloads for assertions."""
    title_calls = []

    def _fake_run(config, messages, **kwargs):
        if messages and messages[0].get("content") == services.TITLE_PROMPT:
            title_calls.append((messages, kwargs))
            return title
        return reply

    monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
    return title_calls


class TestSetTitle:
    """attachments.set_title: the single mutator behind auto + manual writes."""

    def _spec_with_attachment(self):
        spec = {"dataflow": {"nodes": [], "edges": [], "packages": []}}
        attachments.attach(
            spec, COORD, {"kind": "canvas"}, attachment_id="a1", session_id="s1"
        )
        return spec

    def test_attach_records_omit_title(self):
        spec = self._spec_with_attachment()
        record = attachments.get_attachment(spec, "a1")
        assert "title" not in record and "titleEdited" not in record

    def test_auto_write_sets_title_and_bumps_revision(self):
        spec = self._spec_with_attachment()
        record = attachments.set_title(spec, "a1", "Dataset Import Help", edited=False)
        assert record["title"] == "Dataset Import Help"
        assert not record.get("titleEdited")
        assert record["revision"] == 2

    def test_auto_write_skips_an_existing_title(self):
        spec = self._spec_with_attachment()
        attachments.set_title(spec, "a1", "First Title", edited=False)
        record = attachments.set_title(spec, "a1", "Second Title", edited=False)
        assert record["title"] == "First Title"
        assert record["revision"] == 2  # no bump on the skipped write

    def test_manual_write_sets_edited_and_wins(self):
        spec = self._spec_with_attachment()
        record = attachments.set_title(spec, "a1", "My Name", edited=True)
        assert record["title"] == "My Name"
        assert record["titleEdited"] is True
        assert record["revision"] == 2
        # A later auto write never touches a manual title.
        record = attachments.set_title(spec, "a1", "Auto Title", edited=False)
        assert record["title"] == "My Name"
        assert record["revision"] == 2
        # Nor does an auto clear (conversation clear).
        record = attachments.set_title(spec, "a1", None, edited=False)
        assert record["title"] == "My Name"

    def test_auto_clear_drops_an_auto_title_only(self):
        spec = self._spec_with_attachment()
        attachments.set_title(spec, "a1", "Auto Title", edited=False)
        record = attachments.set_title(spec, "a1", None, edited=False)
        assert "title" not in record
        assert record["revision"] == 3
        # Clearing an already-untitled record is a no-op (no bump).
        record = attachments.set_title(spec, "a1", None, edited=False)
        assert record["revision"] == 3

    def test_manual_validation(self):
        spec = self._spec_with_attachment()
        with pytest.raises(AttachmentError):
            attachments.set_title(spec, "a1", "", edited=True)
        with pytest.raises(AttachmentError):
            attachments.set_title(spec, "a1", "   ", edited=True)
        with pytest.raises(AttachmentError):
            attachments.set_title(spec, "a1", None, edited=True)
        with pytest.raises(AttachmentError):
            attachments.set_title(spec, "a1", "x" * (TITLE_MAX_CHARS + 1), edited=True)
        with pytest.raises(AttachmentError):
            attachments.set_title(spec, "a1", 42, edited=True)

    def test_unknown_attachment_returns_none(self):
        spec = self._spec_with_attachment()
        assert attachments.set_title(spec, "ghost", "T", edited=True) is None


class TestSanitizeTitle:
    def test_plain_title_passes(self):
        assert services.sanitize_title("Dataset Import Help") == "Dataset Import Help"

    def test_quotes_newlines_and_period_stripped(self):
        assert services.sanitize_title('"Dataset\nImport   Help."\n') == "Dataset Import Help"
        assert services.sanitize_title("“Smart Quotes Title”") == "Smart Quotes Title"
        assert services.sanitize_title("`Backtick Title`") == "Backtick Title"

    def test_over_cap_truncated(self):
        out = services.sanitize_title("word " * 30)
        assert out is not None and len(out) <= TITLE_MAX_CHARS
        assert not out.endswith(" ")

    def test_empty_and_non_string_rejected(self):
        assert services.sanitize_title("") is None
        assert services.sanitize_title('""') is None
        assert services.sanitize_title("   \n  ") is None
        assert services.sanitize_title(None) is None
        assert services.sanitize_title(42) is None


class TestAutoTitleRoutes:
    def test_first_run_generates_and_persists_a_title(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        title_calls = _mock_provider(monkeypatch, title='"Dataset Import Help."')
        _, token = user_and_token
        att = _attach_builtin(client, token, alice_project)
        assert att["title"] is None and att["titleEdited"] is False
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att['attachmentId']}/run",
            json={"message": "help me import a dataset"}, headers=_auth(token),
        )
        assert r.status_code == 200
        # The title call carried the first user message and the small cap.
        assert len(title_calls) == 1
        messages, kwargs = title_calls[0]
        assert messages[1] == {"role": "user", "content": "help me import a dataset"}
        assert kwargs.get("max_output_tokens") == services.TITLE_MAX_OUTPUT_TOKENS
        # Persisted, sanitized, and exposed on the listing.
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["title"] == "Dataset Import Help"
        assert listed[0]["titleEdited"] is False

    def test_second_run_does_not_retrigger(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        title_calls = _mock_provider(monkeypatch)
        _, token = user_and_token
        att_id = _attach_builtin(client, token, alice_project)["attachmentId"]
        url = f"/api/agents/projects/{alice_project}/attachments/{att_id}/run"
        client.post(url, json={"message": "q1"}, headers=_auth(token))
        client.post(url, json={"message": "q2"}, headers=_auth(token))
        assert len(title_calls) == 1

    def test_failed_title_call_leaves_reply_intact_and_title_null(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == services.TITLE_PROMPT:
                raise RuntimeError("title provider down")
            return "the reply"

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        _, token = user_and_token
        att_id = _attach_builtin(client, token, alice_project)["attachmentId"]
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert r.status_code == 200
        assert r.get_json()["reply"] == "the reply"
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["title"] is None

    def test_garbage_title_output_is_not_persisted(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _mock_provider(monkeypatch, title='""')
        _, token = user_and_token
        att_id = _attach_builtin(client, token, alice_project)["attachmentId"]
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["title"] is None

    def test_stream_first_run_sets_title_after_done(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _fake_stream(config, messages, **kwargs):
            yield "hi"

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.stream_chat_completion", _fake_stream
        )
        _mock_provider(monkeypatch, title="Stream Title Words")
        _, token = user_and_token
        att_id = _attach_builtin(client, token, alice_project)["attachmentId"]
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        r.get_data()  # consume the stream
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["title"] == "Stream Title Words"

    def test_aborted_stream_sets_no_title(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _flaky(config, messages, **kwargs):
            yield "par"
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.stream_chat_completion", _flaky
        )
        title_calls = _mock_provider(monkeypatch)
        _, token = user_and_token
        att_id = _attach_builtin(client, token, alice_project)["attachmentId"]
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
            json={"message": "q1"}, headers=_auth(token),
        )
        r.get_data()
        assert title_calls == []


class TestManualTitleRoutes:
    def test_patch_title_persists_sets_edited_and_bumps_revision(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        att = _attach_builtin(client, token, alice_project)
        r = client.patch(
            f"/api/agents/projects/{alice_project}/attachments/{att['attachmentId']}",
            json={"title": "  My Custom Name  "}, headers=_auth(token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        card = r.get_json()
        assert card["title"] == "My Custom Name"
        assert card["titleEdited"] is True
        assert card["revision"] == att["revision"] + 1
        assert card["name"] == att["name"]  # the template name never changes
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["title"] == "My Custom Name"

    def test_patch_title_validation_and_404(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        att_id = _attach_builtin(client, token, alice_project)["attachmentId"]
        url = f"/api/agents/projects/{alice_project}/attachments/{att_id}"
        assert client.patch(url, json={"title": ""}, headers=_auth(token)).status_code == 400
        assert client.patch(url, json={"title": "   "}, headers=_auth(token)).status_code == 400
        assert client.patch(url, json={"title": None}, headers=_auth(token)).status_code == 400
        assert client.patch(url, json={"title": 42}, headers=_auth(token)).status_code == 400
        assert client.patch(
            url, json={"title": "x" * (TITLE_MAX_CHARS + 1)}, headers=_auth(token)
        ).status_code == 400
        assert client.patch(
            f"/api/agents/projects/{alice_project}/attachments/ghost",
            json={"title": "T"}, headers=_auth(token),
        ).status_code == 404

    def test_manual_title_suppresses_generation(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        title_calls = _mock_provider(monkeypatch)
        _, token = user_and_token
        att_id = _attach_builtin(client, token, alice_project)["attachmentId"]
        # Rename before any message: auto-generation must never fire.
        client.patch(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}",
            json={"title": "Named Before First Message"}, headers=_auth(token),
        )
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        assert title_calls == []
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["title"] == "Named Before First Message"

    def test_manual_rename_landing_mid_run_beats_the_auto_write(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        # The title call itself simulates a concurrent manual rename: it lands
        # a manual title before the auto write re-checks the spec.
        _, token = user_and_token
        att_id = _attach_builtin(client, token, alice_project)["attachmentId"]
        user, _ = user_and_token
        ukey = _user_dir_key(user)

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == services.TITLE_PROMPT:
                services.update_attachment_title(ukey, alice_project, att_id, "Manual Wins")
                return "Auto Title"
            return "ok"

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["title"] == "Manual Wins"
        assert listed[0]["titleEdited"] is True


class TestClearConversation:
    def test_clear_drops_an_auto_title_and_regenerates(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        title_calls = _mock_provider(monkeypatch)
        _, token = user_and_token
        att_id = _attach_builtin(client, token, alice_project)["attachmentId"]
        run_url = f"/api/agents/projects/{alice_project}/attachments/{att_id}/run"
        client.post(run_url, json={"message": "q1"}, headers=_auth(token))
        client.delete(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        )
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["title"] is None
        # The next first message regenerates.
        client.post(run_url, json={"message": "q2"}, headers=_auth(token))
        assert len(title_calls) == 2
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["title"] == "Dataset Import Help"

    def test_clear_keeps_a_manual_title(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        title_calls = _mock_provider(monkeypatch)
        _, token = user_and_token
        att_id = _attach_builtin(client, token, alice_project)["attachmentId"]
        client.patch(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}",
            json={"title": "Keep Me"}, headers=_auth(token),
        )
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        client.delete(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
            headers=_auth(token),
        )
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["title"] == "Keep Me"
        assert listed[0]["titleEdited"] is True
        # And messaging again still never regenerates over it.
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q2"}, headers=_auth(token),
        )
        assert title_calls == []


class TestTitlePreservedAcrossSaves:
    def test_title_survives_a_canvas_save(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _mock_provider(monkeypatch)
        _, token = user_and_token
        att_id = _attach_builtin(client, token, alice_project)["attachmentId"]
        client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/run",
            json={"message": "q1"}, headers=_auth(token),
        )
        # A canvas save omits the agent sections; preserve_agent_state carries
        # agentAttachments — including the title — forward.
        client.put(
            f"/api/projects/{alice_project}",
            json={
                "name": "p",
                "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
                "outputs": [],
            },
            headers=_auth(token),
        )
        listed = client.get(
            f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)
        ).get_json()["attachments"]
        assert listed[0]["title"] == "Dataset Import Help"
