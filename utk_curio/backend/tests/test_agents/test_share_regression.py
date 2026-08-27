"""Share-surface regression suite (tracking rule 9; DEC-032, memo dev/12).

The agents feature must introduce **no agent-private data as a new shared
surface** in Curio's existing flow-sharing. The unauthenticated shared route
returns the project spec — which on disk carries the backend-owned agent
sections (install lockfile, attachments with intents/titles/session ids,
project defaults). This suite proves the shared payload excludes them, that
sanitization never mutates the on-disk truth, and that per-project agent
endpoints stay owner-only.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents import project_agents
from utk_curio.backend.app.projects.services import _user_dir_key


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


SECRET_INTENT = "secret internal instruction about layoffs"
SECRET_TITLE = "Confidential Budget Review"


class TestStripAgentState:
    def test_strips_agent_sections_and_keeps_the_rest(self):
        spec = {
            "dataflow": {
                "nodes": [{"id": "n1"}],
                "packages": ["curio.builtin@1"],
                "agents": ["agent.chat-agent@1.0.0"],
                "agentAttachments": [{"attachmentId": "a", "sessionId": "s", "intent": "x"}],
                "agentDefaults": {"agent.chat-agent@1.0.0": {"revision": 1, "settings": {}}},
            }
        }
        out = project_agents.strip_agent_state(spec)
        assert out["dataflow"]["nodes"] == [{"id": "n1"}]
        assert out["dataflow"]["packages"] == ["curio.builtin@1"]
        for key in project_agents._AGENT_SPEC_KEYS:
            assert key not in out["dataflow"]
        # Non-mutating: the source spec keeps its sections.
        assert "agents" in spec["dataflow"] and "agentAttachments" in spec["dataflow"]

    def test_tolerates_missing_and_malformed(self):
        assert project_agents.strip_agent_state(None) is None
        assert project_agents.strip_agent_state({}) == {}
        same = {"dataflow": "junk"}
        assert project_agents.strip_agent_state(same) == same


@pytest.fixture()
def shared_project_with_agent_state(client, user_and_token, tmp_curio, monkeypatch):
    """A project with the full agent-private surface: install + attachment
    (edited intent + manual title) + a persisted chat session."""
    monkeypatch.setattr(
        "utk_curio.backend.app.agents.services.run_chat_completion", lambda c, m, **kw: "ok"
    )
    user, token = user_and_token
    body = {
        "name": "p",
        "spec": {"dataflow": {"nodes": [{"id": "n1"}], "edges": [], "packages": []}},
        "outputs": [],
    }
    project_id = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
    coord = "agent.chat-agent@1.0.0"
    client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord}, headers=_auth(token))
    att = client.post(
        f"/api/agents/projects/{project_id}/attachments",
        json={"coord": coord, "target": {"kind": "canvas"}},
        headers=_auth(token),
    ).get_json()
    client.patch(
        f"/api/agents/projects/{project_id}/attachments/{att['attachmentId']}",
        json={"intent": SECRET_INTENT},
        headers=_auth(token),
    )
    client.patch(
        f"/api/agents/projects/{project_id}/attachments/{att['attachmentId']}",
        json={"title": SECRET_TITLE},
        headers=_auth(token),
    )
    client.post(
        f"/api/agents/projects/{project_id}/attachments/{att['attachmentId']}/run",
        json={"message": "hello"},
        headers=_auth(token),
    )
    return {"user": user, "token": token, "project_id": project_id, "attachment": att}


class TestSharedRouteExcludesAgentPrivateData:
    def test_shared_payload_has_no_agent_sections_or_private_strings(
        self, client, shared_project_with_agent_state
    ):
        ctx = shared_project_with_agent_state
        r = client.get(f"/api/projects/{ctx['project_id']}/shared")  # unauthenticated
        assert r.status_code == 200, r.get_data(as_text=True)
        raw = r.get_data(as_text=True)
        body = r.get_json()

        dataflow = body["spec"]["dataflow"]
        for key in ("agents", "agentAttachments", "agentDefaults"):
            assert key not in dataflow, f"shared spec leaked dataflow.{key}"
        # The non-agent graph is intact for the shared viewer.
        assert dataflow["nodes"] == [{"id": "n1"}]

        for private in (
            "agentAttachments",
            "agentDefaults",
            "agent.chat-agent",
            ctx["attachment"]["attachmentId"],
            ctx["attachment"]["sessionId"],
            SECRET_INTENT,
            SECRET_TITLE,
        ):
            assert private not in raw, f"shared payload leaked {private!r}"

    def test_sanitization_never_mutates_the_on_disk_spec(
        self, client, shared_project_with_agent_state
    ):
        from utk_curio.backend.app.projects import storage as projects_storage

        ctx = shared_project_with_agent_state
        client.get(f"/api/projects/{ctx['project_id']}/shared").get_data()
        ukey = _user_dir_key(ctx["user"])
        spec = projects_storage.read_spec(ukey, ctx["project_id"])
        assert spec["dataflow"]["agents"] == ["agent.chat-agent@1.0.0"]
        att = spec["dataflow"]["agentAttachments"][0]
        assert att["intent"] == SECRET_INTENT and att["title"] == SECRET_TITLE
        # `agentDefaults` is no longer written: it held the per-dataflow half
        # of a policy editor whose surfaces were removed. It is still stripped
        # from a shared spec, which the sibling case above asserts.
        assert "agentDefaults" not in spec["dataflow"]

    def test_agent_endpoints_stay_owner_only(
        self, client, shared_project_with_agent_state, guest_user_and_token
    ):
        ctx = shared_project_with_agent_state
        _, other_token = guest_user_and_token
        att_id = ctx["attachment"]["attachmentId"]
        for path in (
            f"/api/agents/projects/{ctx['project_id']}/attachments",
            f"/api/agents/projects/{ctx['project_id']}/attachments/{att_id}/session",
        ):
            r = client.get(path, headers=_auth(other_token))
            assert r.status_code == 404, f"{path} not owner-only: {r.status_code}"
            assert ctx["attachment"]["sessionId"] not in r.get_data(as_text=True)
