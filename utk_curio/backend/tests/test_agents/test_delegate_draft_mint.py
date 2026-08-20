"""dev/90 commit 3 — the delegate-draft mint: a successful package-authoring
delegation whose bounded child reply parses as a build request becomes a
runtime-minted, reviewed ``package.draft.apply`` proposal at the parent's
attachment (the dev/73 one-mint-policy extended). Covers the payload
extractor, the happy Researcher→Package Builder path, recoverable failures
(unparseable reply, invalid draft), the grant gate, and injection resistance
(draft-shaped text outside the delegation-result path never mints).
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.services import _extract_draft_params
from utk_curio.backend.app.packages import build_jobs

RESEARCHER = "agent.researcher@1.0.0"
PACKAGE_BUILDER = "agent.package-builder@1.0.0"
NODE_BUILDER = "agent.node-builder@1.0.0"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _draft(color="pink"):
    return {
        "mode": "create",
        "target": "ai.agent.notes@1",
        "manifest": {
            "id": "ai.agent.notes",
            "version": "1.0.0",
            "name": "Agent Notes",
            "publisher": "Agent",
            "description": "Post-it style notes",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "note-kind", "label": "Research note",
                "category": "visualization", "engine": "python",
                "editor": "code", "hasCode": True, "hasWidgets": False,
                "hasGrammar": False, "inputPorts": [], "outputPorts": [],
                "templateDir": "starters/note-kind",
                "defaultTemplate": "starters/note-kind/Default.py",
            }],
        },
        "files": {"starters/note-kind/Default.py": {"text": "return arg\n"}},
        "nodes": [{
            "templateId": "note-kind", "title": "Note",
            "content": "# Findings", "appearance": {"backgroundColor": color},
        }],
    }


class TestExtractDraftParams:
    def test_bare_json_object(self):
        assert _extract_draft_params(json.dumps(_draft()))["target"] == "ai.agent.notes@1"

    def test_fenced_block_and_package_draft_wrapper(self):
        text = ("Here is the draft you asked for:\n\n```json\n"
                + json.dumps({"packageDraft": _draft()}) + "\n```\n")
        assert _extract_draft_params(text)["mode"] == "create"
        plain_fence = "```\n" + json.dumps(_draft()) + "\n```"
        assert _extract_draft_params(plain_fence)["mode"] == "create"

    def test_chatty_json_without_draft_shape_is_none(self):
        # Arbitrary JSON never parses as a draft by accident: mode+manifest
        # are both required.
        assert _extract_draft_params(json.dumps({"mode": "create"})) is None
        assert _extract_draft_params(json.dumps({"manifest": {}})) is None
        assert _extract_draft_params(json.dumps({"answer": 42})) is None
        assert _extract_draft_params(json.dumps([_draft()])) is None

    def test_prose_and_empty_are_none(self):
        assert _extract_draft_params("I could not author the package.") is None
        assert _extract_draft_params("") is None
        assert _extract_draft_params(None) is None

    def test_instruction_faithful_tool_request_shape_unwraps(self):
        # dev/90 A7 — the live failure: a tool-less child following its own
        # tool teaching emits a curio.v1 package.draft.apply toolRequest; the
        # extractor unwraps the params (and never executes anything).
        tail = ("Here is the draft.\n\n```curio.v1\n"
                + json.dumps({"toolRequest": {"tool": "package.draft.apply",
                                              "params": _draft()}})
                + "\n```")
        assert _extract_draft_params(tail)["target"] == "ai.agent.notes@1"
        # Bare (unfenced) toolRequest JSON works too.
        bare = json.dumps({"toolRequest": {"tool": "package.draft.apply",
                                           "params": _draft()}})
        assert _extract_draft_params(bare)["mode"] == "create"
        # A DIFFERENT tool's request never unwraps into a draft.
        other = json.dumps({"toolRequest": {"tool": "node.create",
                                            "params": _draft()}})
        assert _extract_draft_params(other) is None


def _delegate_tail(inputs='{"look": "post-it style notes"}'):
    return (
        '```curio.v1\n{"delegateRequest": {"capability": "node.kind.author", '
        '"inputs": ' + inputs + "}}\n```"
    )


def _project(client, token):
    resp = client.post("/api/projects", json={
        "name": "p",
        "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
        "outputs": [],
    }, headers=_auth(token))
    assert resp.status_code == 201
    return resp.get_json()["id"]


def _setup(client, token, project_id, monkeypatch, *, parent=RESEARCHER, replies):
    """Install parent + Package Builder, attach the parent (canvas), and
    script the shared provider mock (parent and child calls in order)."""
    client.post(f"/api/agents/projects/{project_id}/install",
                json={"coord": parent}, headers=_auth(token))
    client.post(f"/api/agents/projects/{project_id}/install",
                json={"coord": PACKAGE_BUILDER}, headers=_auth(token))
    att_id = client.post(
        f"/api/agents/projects/{project_id}/attachments",
        json={"coord": parent, "target": {"kind": "canvas"}},
        headers=_auth(token),
    ).get_json()["attachmentId"]
    calls = []

    def _fake_run(config, messages, **kwargs):
        from utk_curio.backend.app.agents import services as services_mod

        if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
            return "Title"
        calls.append(messages)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    monkeypatch.setattr(
        "utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
    return att_id, calls


def _run(client, token, project_id, att_id, message="post-it my findings"):
    return client.post(
        f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
        json={"message": message}, headers=_auth(token),
    )


@pytest.fixture(autouse=True)
def _fresh_jobs():
    build_jobs.reset_registry()
    yield
    build_jobs.reset_registry()


class TestDelegateDraftMint:
    def test_researcher_delegation_mints_the_reviewed_draft(
            self, client, user_and_token, tmp_curio, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        pid = _project(client, token)
        child_reply = "```json\n" + json.dumps({"packageDraft": _draft()}) + "\n```"
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _delegate_tail(),          # parent round 1: delegate authoring
            child_reply,               # CHILD (Package Builder): the draft
            "Proposed — review above.",  # parent round 2: final prose
        ])
        run = _run(client, token, pid, att_id)
        assert run.status_code == 200, run.get_data(as_text=True)
        parts = run.get_json()["content"]
        proposal = next(p for p in parts if p["type"] == "proposal")
        assert proposal["tool"] == "package.draft.apply"
        assert proposal["pins"]["target"] == "ai.agent.notes@1"
        # The delegation trace rides the same turn (dev/72 compact entry).
        assert any(p["type"] == "delegation" for p in parts)
        # The parent's follow-up round saw the mint outcome, not raw JSON.
        assert "proposal" in calls[2][-1]["content"]

        # Apply promotes + creates the note with the normalized color.
        resp = client.post(
            f"/api/agents/projects/{pid}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["requiresRegistryRefresh"] is True
        assert body["installedPackage"]["dirName"] == "ai.agent.notes@1"
        created = body["createdNodes"][0]
        assert created["metadata"]["appearance"]["backgroundColor"] == "#fbd3e0"
        with client.application.app_context():
            user_key = _user_dir_key(user)
        spec = projects_storage.read_spec(user_key, pid)
        assert any(n.get("metadata", {}).get("appearance", {}).get("backgroundColor")
                   == "#fbd3e0" for n in spec["dataflow"]["nodes"])

    def test_unparseable_child_reply_is_recoverable_data(
            self, client, user_and_token, tmp_curio, monkeypatch):
        _, token = user_and_token
        pid = _project(client, token)
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _delegate_tail(),
            "I sketched an approach but produced no draft.",
            "Understood — I'll refine the requirements.",
        ])
        run = _run(client, token, pid, att_id)
        parts = run.get_json()["content"]
        assert all(p["type"] != "proposal" for p in parts)
        assert "no parseable package draft" in calls[2][-1]["content"]

    def test_invalid_draft_refuses_via_the_one_mint_path(
            self, client, user_and_token, tmp_curio, monkeypatch):
        _, token = user_and_token
        pid = _project(client, token)
        bad = _draft(color="rgb(1,2,3)")  # the shared appearance utility refuses
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _delegate_tail(),
            json.dumps({"packageDraft": bad}),
            "ok",
        ])
        run = _run(client, token, pid, att_id)
        assert all(p["type"] != "proposal" for p in run.get_json()["content"])
        assert "invalid build request" in calls[2][-1]["content"]

    def test_parent_without_the_grant_keeps_text_only(
            self, client, user_and_token, tmp_curio, monkeypatch):
        # Node Builder delegates authoring (dev/89) but does NOT declare
        # package.draft.apply — the child's draft stays text, never a mint.
        _, token = user_and_token
        pid = _project(client, token)
        att_id, calls = _setup(client, token, pid, monkeypatch, parent=NODE_BUILDER,
                               replies=[
                                   _delegate_tail(),
                                   json.dumps(_draft()),
                                   "Summarizing the draft for you.",
                               ])
        run = _run(client, token, pid, att_id)
        assert all(p["type"] != "proposal" for p in run.get_json()["content"])
        assert "not\ngranted" in calls[2][-1]["content"] or (
            "not granted" in calls[2][-1]["content"].replace("\n", " "))

    def test_draft_shaped_chat_text_never_mints(
            self, client, user_and_token, tmp_curio, monkeypatch):
        # Injection resistance: only the delegation-result path mints. A
        # PARENT reply carrying draft-shaped JSON as prose is just text.
        _, token = user_and_token
        pid = _project(client, token)
        att_id, _ = _setup(client, token, pid, monkeypatch, replies=[
            "Here is a draft you could apply yourself:\n\n"
            + json.dumps({"packageDraft": _draft()}),
        ])
        run = _run(client, token, pid, att_id)
        parts = run.get_json()["content"]
        assert all(p["type"] != "proposal" for p in parts)


class TestLargeLookSpecDelegation:
    """dev/90 A6 — the live-screenshot regression: the Researcher's authoring
    delegation carries the FULL post-it look specification plus findings
    (well past the classic 3KB inputs cap) and must still parse, delegate,
    and mint — never fail open as visible JSON text."""

    def test_researcher_delegation_with_full_look_spec_mints(
            self, client, user_and_token, tmp_curio, monkeypatch):
        _, token = user_and_token
        pid = _project(client, token)
        look_spec = {
            "look": "post-it note",
            "requirements": (
                "a roughly square note surface with a small header title and a "
                "scrollable bounded body; safe plain text or simple markdown "
                "(headings, bullets, bold, https links) — never raw HTML; a "
                "quiet placeholder when empty; per-instance "
                "appearance.backgroundColor from the palette or six-digit hex "
                "with readable derived text; no Run control, no ports, no code "
                "editor, no Python, no network. " + "detail " * 700
            ),
            "findings": [
                {"title": "Weather in Paris",
                 "content": "68-77°F, rain likely — https://weather.test/paris"},
            ],
        }
        tail = _delegate_tail(inputs=json.dumps(look_spec))
        assert len(tail.encode()) > 4096  # past the classic whole-tail cap
        att_id, _ = _setup(client, token, pid, monkeypatch, replies=[
            tail,
            json.dumps({"packageDraft": _draft()}),
            "Proposed — the note awaits your review.",
        ])
        run = _run(client, token, pid, att_id, message="what's the weather in Paris?")
        assert run.status_code == 200, run.get_data(as_text=True)
        parts = run.get_json()["content"]
        proposal = next(p for p in parts if p["type"] == "proposal")
        assert proposal["tool"] == "package.draft.apply"
        # The delegation EXECUTED — its trace exists and no raw JSON text of
        # the request leaked into the visible reply parts.
        assert any(p["type"] == "delegation" for p in parts)
        texts = [p.get("text", "") for p in parts if p.get("type") == "markdown"]
        assert not any("delegateRequest" in t for t in texts)


class TestChildAnswersInToolRequestShape:
    """dev/90 A7 route replay of the live screenshots: the Package Builder
    child answers with its instruction's curio.v1 toolRequest tail (it is
    tool-less as a delegate) — the runtime unwraps and mints anyway."""

    def test_delegation_mints_from_the_tool_request_reply(
            self, client, user_and_token, tmp_curio, monkeypatch):
        _, token = user_and_token
        pid = _project(client, token)
        child_reply = (
            "I authored the Research Notes package as requested.\n\n"
            "```curio.v1\n"
            + json.dumps({"toolRequest": {"tool": "package.draft.apply",
                                          "params": _draft()}})
            + "\n```"
        )
        att_id, _ = _setup(client, token, pid, monkeypatch, replies=[
            _delegate_tail(),
            child_reply,
            "Proposed — the notes package awaits your review.",
        ])
        run = _run(client, token, pid, att_id)
        assert run.status_code == 200, run.get_data(as_text=True)
        parts = run.get_json()["content"]
        proposal = next(p for p in parts if p["type"] == "proposal")
        assert proposal["tool"] == "package.draft.apply"
        assert proposal["pins"]["target"] == "ai.agent.notes@1"
