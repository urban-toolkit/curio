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
        """dev/93 D5: still recoverable data, but now the parent is told WHAT
        was wrong and told not to rename the package. The old message ("refine
        the delegation inputs and try again") carried no parse error, so the
        parent's "refinement" was to re-delegate under a different package id
        — which is how one weather question produced two packages."""
        _, token = user_and_token
        pid = _project(client, token)
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _delegate_tail(),
            "I sketched an approach but produced no draft.",
            "Understood — I'll tell the user.",
        ])
        run = _run(client, token, pid, att_id)
        parts = run.get_json()["content"]
        assert all(p["type"] != "proposal" for p in parts)
        # The parent's next turn carries the real reason and the guardrail.
        handed_back = calls[-1][-1]["content"]
        assert "no JSON build request found" in handed_back
        assert "different package name" in handed_back
        # And the delegation card reports the OUTCOME, not just that the child
        # ran: "ok" beside "produced no draft" is what taught the parent
        # nothing (content.py derives the label from what we pass here).
        card = next(p for p in parts if p["type"] == "delegation")
        assert card["status"] == "failed"

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


class TestAuthoringInputEnrichment:
    """dev/90 A8 — tool-less authoring delegates receive the build-request
    contract server-side (the dev/67-6 enrichment pattern): the live child
    invented 'package'/'behaviors'/'behaviorKey' twice because no one in the
    delegation chain had ever seen the schema."""

    def test_authoring_capabilities_gain_the_contract(self):
        from utk_curio.backend.app.agents.services import (
            _BUILD_REQUEST_CONTRACT,
            _enriched_delegate_inputs,
        )

        for capability in ("node.kind.author", "package.build", "package.extend"):
            enriched = _enriched_delegate_inputs(
                "guest", "p1", {}, capability, {"look": "post-it"})
            assert enriched["buildRequestContract"] is _BUILD_REQUEST_CONTRACT
            assert enriched["look"] == "post-it"
        # The contract counters the observed invention explicitly.
        text = json.dumps(_BUILD_REQUEST_CONTRACT)
        assert "reverse-DNS" in text
        assert "behaviorKey" in text and "Do NOT invent" in text
        # dev/90 A15: the runtime field contract is spelled out — the live
        # bundle read data.content/nodeState.appearance and rendered blank.
        assert "data.code" in text and "data.content" in text
        assert "data.appearance.backgroundColor" in text

    def test_model_supplied_contract_is_never_overwritten(self):
        from utk_curio.backend.app.agents.services import _enriched_delegate_inputs

        enriched = _enriched_delegate_inputs(
            "guest", "p1", {}, "node.kind.author",
            {"buildRequestContract": {"custom": True}})
        assert enriched["buildRequestContract"] == {"custom": True}

    def test_ordinary_capabilities_are_untouched(self):
        from utk_curio.backend.app.agents.services import _enriched_delegate_inputs

        enriched = _enriched_delegate_inputs(
            "guest", "p1", {}, "workflow.suggest", {"x": 1})
        assert enriched == {"x": 1}

    def test_the_child_sees_the_contract(self, client, user_and_token, tmp_curio,
                                         monkeypatch):
        # Route-level: the CHILD's user message carries the schema.
        _, token = user_and_token
        pid = _project(client, token)
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _delegate_tail(),
            json.dumps({"packageDraft": _draft()}),
            "Proposed.",
        ])
        run = _run(client, token, pid, att_id)
        assert run.status_code == 200, run.get_data(as_text=True)
        # The child call is the TWO-message list (own system + the framed
        # inputs) — parent calls alias the parent's one growing list, whose
        # system also mentions "Package Builder" (the Researcher instruction).
        child_calls = [
            c for c in calls
            if len(c) == 2 and str(c[-1].get("content", "")).startswith(
                "[delegated task from")
        ]
        assert child_calls, "the delegate child call is missing"
        child_user_msg = child_calls[0][-1]["content"]
        assert "buildRequestContract" in child_user_msg
        assert "reverse-DNS" in child_user_msg
        assert "registerBehavior" in child_user_msg


class TestDecoratedRequestReply:
    """dev/90 A10 route replay of the 12:55 live session: the Researcher's
    reply carried the delegateRequest block AND a terminal suggestedPrompts
    block — the terminal-only tail rule demoted the request to inert text
    (delegations: null, parts: [suggestedPrompts], fence visible in chat)."""

    LIVE_SHAPE_REPLY = (
        "Based on the search results, the current weather in Paris is 73F.\n\n"
        "I will place this finding as a note on your canvas.\n\n"
        "```curio.v1\n"
        '{"delegateRequest": {"capability": "node.kind.author", '
        '"inputs": {"requirements": "square post-it note, markdown body"}}}\n'
        "```\n\n"
        "```curio.v1\n"
        '{"suggestedPrompts": {"primary": "Check another city?"}}\n'
        "```"
    )

    def test_decorated_delegate_request_executes(self, client, user_and_token,
                                                 tmp_curio, monkeypatch):
        _, token = user_and_token
        pid = _project(client, token)
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            self.LIVE_SHAPE_REPLY,
            json.dumps({"packageDraft": _draft()}),  # the child's draft
            "Proposed — the note awaits your review.",
        ])
        run = _run(client, token, pid, att_id,
                   message="What's the weather in Paris?")
        assert run.status_code == 200, run.get_data(as_text=True)
        parts = run.get_json()["content"]
        # The request EXECUTED: delegation trace + minted proposal, and no
        # raw fence text anywhere in the visible reply.
        assert any(p["type"] == "delegation" for p in parts)
        proposal = next(p for p in parts if p["type"] == "proposal")
        assert proposal["tool"] == "package.draft.apply"
        assert "delegateRequest" not in run.get_json().get("text", "")
        assert len(calls) >= 3  # parent, child, parent follow-up


class TestFindingsReconciliation:
    """dev/90 A12 — the parent's findings are authoritative note content:
    the live artifacts showed EMPTY notes and CHILD-INVENTED filler
    ('This is a *Post-it* note!', 'Check the data loading node for errors')
    because the findings never reached the child. The runtime now marries
    the parent's facts with the child's look."""

    WEATHER_NOTES = [
        {"title": "Weather in Paris",
         "content": "73°F–76°F, mostly cloudy, light rain — https://w.test/paris",
         "color": "yellow"},
    ]

    def test_notes_extraction_shapes(self):
        from utk_curio.backend.app.agents.services import _notes_from_delegate_inputs

        rows = _notes_from_delegate_inputs({"notes": self.WEATHER_NOTES})
        assert rows[0]["content"].startswith("73°F")
        assert rows[0]["appearance"] == {"backgroundColor": "yellow"}
        # findings alias; appearance-shaped color; malformed rows skipped.
        rows = _notes_from_delegate_inputs({"findings": [
            {"content": "x", "appearance": {"backgroundColor": "#336699"}},
            {"title": "no content"}, "not-a-dict", {"content": "   "},
        ]})
        assert len(rows) == 1 and rows[0]["appearance"]["backgroundColor"] == "#336699"
        assert _notes_from_delegate_inputs({}) is None
        assert _notes_from_delegate_inputs({"notes": []}) is None

    def _mint_with(self, client, token, pid, monkeypatch, child_nodes):
        draft = _draft()
        draft["nodes"] = child_nodes
        tail = ('```curio.v1\n{"delegateRequest": {"capability": "node.kind.author", '
                '"inputs": {"requirements": "post-it look", "notes": '
                + json.dumps(self.WEATHER_NOTES) + "}}}\n```")
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            tail,
            json.dumps({"packageDraft": draft}),
            "Proposed.",
        ])
        run = _run(client, token, pid, att_id, message="weather in Paris?")
        assert run.status_code == 200, run.get_data(as_text=True)
        parts = run.get_json()["content"]
        proposal = next(p for p in parts if p["type"] == "proposal")
        return att_id, proposal, calls

    def _apply_and_read_notes(self, client, user, token, pid, att_id, proposal):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        resp = client.post(
            f"/api/agents/projects/{pid}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply", headers=_auth(token))
        assert resp.status_code == 200, resp.get_data(as_text=True)
        with client.application.app_context():
            user_key = _user_dir_key(user)
        spec = projects_storage.read_spec(user_key, pid)
        return [n for n in spec["dataflow"]["nodes"]
                if n["type"].startswith("ai.agent.notes/")]

    def test_empty_child_nodes_get_the_findings(self, client, user_and_token,
                                                tmp_curio, monkeypatch):
        # Live artifact 1: the child sent no/empty nodes → notes were empty.
        user, token = user_and_token
        pid = _project(client, token)
        att_id, proposal, calls = self._mint_with(client, token, pid, monkeypatch,
                                                  child_nodes=[])
        assert "runtime-reconciled" in calls[2][-1]["content"]
        notes = self._apply_and_read_notes(client, user, token, pid, att_id, proposal)
        assert len(notes) == 1
        assert "73°F" in notes[0]["content"]
        assert notes[0]["title"] == "Weather in Paris"
        assert notes[0]["metadata"]["appearance"]["backgroundColor"] == "#fef3c0"

    def test_child_filler_content_is_replaced_verbatim(self, client, user_and_token,
                                                       tmp_curio, monkeypatch):
        # Live artifact 2: the child invented placeholder notes — the
        # parent's findings replace them wholesale.
        user, token = user_and_token
        pid = _project(client, token)
        filler = [
            {"templateId": "note-kind", "title": "Instructions",
             "content": "This is a *Post-it* note!\n- Supports bullets"},
            {"templateId": "note-kind", "title": "Reminder",
             "content": "Check the data loading node for errors."},
        ]
        att_id, proposal, _ = self._mint_with(client, token, pid, monkeypatch,
                                              child_nodes=filler)
        notes = self._apply_and_read_notes(client, user, token, pid, att_id, proposal)
        assert len(notes) == 1  # the findings define the note set, not the filler
        assert "73°F" in notes[0]["content"]
        assert all("Post-it note!" not in n["content"] for n in notes)
        assert all(n.get("title") != "Reminder" for n in notes)

    def test_without_notes_inputs_the_draft_is_untouched(self, client, user_and_token,
                                                         tmp_curio, monkeypatch):
        # No findings supplied → the child's nodes stand (create-without-notes
        # is a legitimate authoring request).
        user, token = user_and_token
        pid = _project(client, token)
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _delegate_tail(),  # inputs carry only the look
            json.dumps({"packageDraft": _draft()}),  # child's own note rides
            "Proposed.",
        ])
        run = _run(client, token, pid, att_id)
        proposal = next(p for p in run.get_json()["content"] if p["type"] == "proposal")
        assert "runtime-reconciled" not in calls[2][-1]["content"]
        notes = self._apply_and_read_notes(client, user, token, pid, att_id, proposal)
        assert notes[0]["content"] == "# Findings"  # the draft's own node


class TestDraftCorrectionRounds:
    """dev/93 D5 — the delegated package draft was the ONE mutation lane with
    no correction rounds.

    The live failure: the Researcher's first ``node.kind.author`` delegation
    came back unparseable, the runtime discarded it and said "refine the
    delegation inputs and try again" with no parse error attached, and the
    parent's idea of refining was to re-delegate under a DIFFERENT package id
    — so one question about the weather in Paris produced ``curio.notes`` and
    then ``curio.postits``, near-identical, in a single run. Plans have had
    correction rounds since dev/54 and generated node content since dev/67;
    this closes the gap.
    """

    def test_second_attempt_parses_and_mints_exactly_one_proposal(
            self, client, user_and_token, tmp_curio, monkeypatch):
        """The regression for the duplicate package: a first reply that does
        not parse must be CORRECTED, not abandoned — one proposal, one package,
        no second authoring attempt."""
        _, token = user_and_token
        pid = _project(client, token)
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _delegate_tail(),
            # The realistic weak-model failure: a bare JSON body containing an
            # embedded source file, cut off mid-string by the output cap.
            '{"mode": "create", "manifest": {"id": "ai.agent.notes", "templ',
            json.dumps({"packageDraft": _draft()}),          # the correction
            "Proposed — review it above.",
        ])
        run = _run(client, token, pid, att_id)
        parts = run.get_json()["content"]
        proposals = [p for p in parts if p["type"] == "proposal"]
        assert len(proposals) == 1, "exactly one draft proposal, never two"
        assert proposals[0]["tool"] == "package.draft.apply"
        # The delegate was actually re-run with the real error to fix.
        retry = next(
            (c for c in calls if any("validationError" in str(m.get("content", ""))
                                     for m in c)),
            None,
        )
        assert retry is not None, "the delegate must be re-run with the error"
        sent = " ".join(str(m.get("content", "")) for m in retry)
        assert "previousAttempt" in sent
        # The error is the real one, not a vague "try again".
        assert "did not parse" in sent
        assert "cut off" in sent
        card = next(p for p in parts if p["type"] == "delegation")
        assert card["status"] == "ok"

    def test_a_rename_mid_correction_is_a_failed_correction_not_a_new_package(
            self, client, user_and_token, tmp_curio, monkeypatch):
        """Edge case 33/35: the package id from the first parseable draft is
        pinned. A delegate that renames instead of fixing is failing the
        correction — renaming is precisely the move that created duplicates."""
        _, token = user_and_token
        pid = _project(client, token)
        bad = _draft(color="rgb(1,2,3)")           # the appearance utility refuses
        renamed = _draft()
        renamed["manifest"] = {**renamed["manifest"], "id": "ai.agent.notes2"}
        renamed["target"] = "ai.agent.notes2@1"
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _delegate_tail(),
            json.dumps({"packageDraft": bad}),
            json.dumps({"packageDraft": renamed}),
            "I'll report the failure.",
        ])
        run = _run(client, token, pid, att_id)
        parts = run.get_json()["content"]
        assert all(p["type"] != "proposal" for p in parts), (
            "a renamed package must not sneak through as a fresh draft"
        )
        # The rename was named as the problem and fed back to the delegate
        # that did it, rather than being accepted as a second package.
        everything = " ".join(
            str(m.get("content", "")) for c in calls for m in c
        )
        assert "changed the package id" in everything
        assert "duplicate package" in everything
        # And the parent is told not to solve this by renaming either.
        assert "different package name" in calls[-1][-1]["content"]

    def test_a_terminal_refusal_is_not_retried(
            self, client, user_and_token, tmp_curio, monkeypatch):
        """Edge case 31/37: a policy or permission verdict is the build
        service's answer, not a typo. Retrying would spend the parent's rounds
        arriving at the same refusal."""
        from utk_curio.backend.app.agents import services as services_mod

        assert not services_mod._draft_refusal_is_correctable(
            "backend policy blocked: subprocess is not permitted"
        )
        assert not services_mod._draft_refusal_is_correctable(
            "package ai.agent.notes@1 is already installed in this project"
        )
        # A malformed draft or a failed probe is exactly what a model can fix.
        assert services_mod._draft_refusal_is_correctable(
            "invalid build request: manifest.templates[0].id is required"
        )
        assert services_mod._draft_refusal_is_correctable(
            "the handler probe failed for handler.py"
        )

    def test_verbose_extractor_explains_each_failure_shape(self):
        from utk_curio.backend.app.agents.services import (
            _extract_draft_params_verbose,
        )

        _, why = _extract_draft_params_verbose("I could not author it.")
        assert "no JSON build request found" in why
        _, why = _extract_draft_params_verbose('{"mode": "create", ')
        assert "did not parse" in why and "cut off" in why
        _, why = _extract_draft_params_verbose(json.dumps({"answer": 42}))
        assert "not a build request" in why and "answer" in why
        _, why = _extract_draft_params_verbose("")
        assert "no text at all" in why
        params, why = _extract_draft_params_verbose(json.dumps(_draft()))
        assert params is not None and why == ""


def _ukey(client, user):
    """The user's storage dir key (imported lazily, like the older tests)."""
    from utk_curio.backend.app.projects.services import _user_dir_key

    with client.application.app_context():
        return _user_dir_key(user)


def _write_store_package(user_key, dir_name, package_id, name, template_ids,
                         description="Colored note surfaces."):
    """A package in the user's store — one a previous project's Package Builder
    authored, which never enters the committed catalog."""
    from utk_curio.backend.app.packages.storage import user_packageages_dir

    d = user_packageages_dir(user_key) / dir_name
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({
        "id": package_id,
        "version": "1.0.0",
        "name": name,
        "publisher": "Package Builder",
        "description": description,
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [],
        "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": [{
            "id": t, "label": t.replace("-", " ").title(),
            "category": "visualization", "engine": "javascript",
            "editor": "none", "behavior": "note-behavior",
            "hasCode": False, "description": "A note surface.",
            "inputPorts": [], "outputPorts": [],
        } for t in template_ids],
        "createdAt": "2026-08-01T12:00:00Z",
    }), encoding="utf-8")
    return d


class TestAuthoringDelegateReuseEvidence:
    """dev/94 — the Package Builder's instruction opens with "Reuse first.
    Before authoring anything, read packages.catalog … never a duplicate
    package", and it holds that tool only as a direct ATTACHMENT. As a DEC-046
    delegate it runs structurally tool-less — which is the path packages are
    actually authored on — so its first instruction was unexecutable and it had
    no way to know. The runtime now serves the evidence, exactly as it already
    serves the build-request contract (dev/90 A8) and verification results
    (dev/67-4).
    """

    def _evidence(self, client, user, pid):
        from utk_curio.backend.app.agents import services as services_mod

        key = _ukey(client, user)
        return key, services_mod._authoring_reuse_evidence(key, pid)

    def test_store_package_is_reported_with_its_dir_name_and_templates(
            self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        pid = _project(client, token)
        key = _ukey(client, user)
        _write_store_package(key, "curio.notes@1", "curio.notes", "Simple Notes",
                             ["note-surface"])

        _, evidence = self._evidence(client, user, pid)
        row = next(p for p in evidence["packages"] if p["dirName"] == "curio.notes@1")
        # The dirName is what the caller would enlist; the template id is what
        # a `mode: "extend"` draft would name.
        assert row["name"] == "Simple Notes"
        assert row["templates"] == ["curio.notes/note-surface"]
        # Guidance, not an override of the delegate's own instruction.
        assert "author nothing" in evidence["note"]

    def test_installed_in_project_distinguishes_enlisted_from_store_only(
            self, client, user_and_token, tmp_curio):
        """Both answers are actionable and they differ: enlisted means "extend
        or reuse it", store-only means "report it, the caller can enlist it".
        Collapsing them would recreate the one-bucket mistake of dev/93 D4."""
        from utk_curio.backend.app.packages import services as packages_services

        user, token = user_and_token
        pid = _project(client, token)
        key = _ukey(client, user)
        _write_store_package(key, "curio.notes@1", "curio.notes", "Simple Notes",
                             ["note-surface"])
        _write_store_package(key, "curio.tags@1", "curio.tags", "Tags",
                             ["tag-surface"])
        packages_services.install_to_project(key, pid, "curio.tags@1")

        _, evidence = self._evidence(client, user, pid)
        rows = {p["dirName"]: p for p in evidence["packages"]}
        assert rows["curio.tags@1"]["installedInProject"] is True
        assert rows["curio.notes@1"]["installedInProject"] is False

    def test_authoring_delegate_inputs_carry_the_evidence(
            self, client, user_and_token, tmp_curio):
        from utk_curio.backend.app.agents import services as services_mod

        user, token = user_and_token
        pid = _project(client, token)
        key = _ukey(client, user)
        _write_store_package(key, "curio.notes@1", "curio.notes", "Simple Notes",
                             ["note-surface"])

        enriched = services_mod._enriched_delegate_inputs(
            key, pid, {}, "node.kind.author", {"look": "post-it"},
        )
        # The dev/90 A8 contract still rides along — this adds, never replaces.
        assert "buildRequestContract" in enriched
        assert enriched["look"] == "post-it"
        assert "curio.notes@1" in json.dumps(enriched["existingPackages"])

    def test_a_parent_supplied_view_is_never_overwritten(
            self, client, user_and_token, tmp_curio):
        from utk_curio.backend.app.agents import services as services_mod

        user, token = user_and_token
        pid = _project(client, token)
        key = _ukey(client, user)
        _write_store_package(key, "curio.notes@1", "curio.notes", "Simple Notes",
                             ["note-surface"])

        enriched = services_mod._enriched_delegate_inputs(
            key, pid, {}, "node.kind.author", {"existingPackages": "mine"},
        )
        assert enriched["existingPackages"] == "mine"

    def test_non_authoring_capabilities_are_untouched(
            self, client, user_and_token, tmp_curio):
        from utk_curio.backend.app.agents import services as services_mod

        user, token = user_and_token
        pid = _project(client, token)
        key = _ukey(client, user)
        _write_store_package(key, "curio.notes@1", "curio.notes", "Simple Notes",
                             ["note-surface"])

        enriched = services_mod._enriched_delegate_inputs(
            key, pid, {}, "node.content.generate", {"nodeType": "x"},
        )
        assert "existingPackages" not in enriched

    def test_payload_is_bounded_and_truncation_is_logged(
            self, client, user_and_token, tmp_curio, caplog):
        """delegation._frame_inputs bounds NOTHING (only the child's reply is
        capped), so the payload has to bound itself — and a dropped row is
        logged rather than silently vanishing."""
        from utk_curio.backend.app.agents import services as services_mod

        user, token = user_and_token
        pid = _project(client, token)
        key = _ukey(client, user)
        cap = services_mod._REUSE_EVIDENCE_MAX_PACKAGES
        for i in range(cap + 3):
            _write_store_package(
                key, f"ai.test.p{i:03d}@1", f"ai.test.p{i:03d}", f"P{i}",
                [f"t{j}" for j in range(services_mod._REUSE_EVIDENCE_MAX_TEMPLATES + 2)],
                description="D" * (services_mod._REUSE_EVIDENCE_DESC_CHARS + 50),
            )

        with caplog.at_level("WARNING"):
            evidence = services_mod._authoring_reuse_evidence(key, pid)
        assert len(evidence["packages"]) == cap
        assert "truncated" in caplog.text
        for row in evidence["packages"]:
            assert len(row["description"]) <= services_mod._REUSE_EVIDENCE_DESC_CHARS
            assert len(row.get("templates", [])) <= (
                services_mod._REUSE_EVIDENCE_MAX_TEMPLATES
            )

    def test_a_broken_registry_degrades_to_no_evidence(
            self, client, user_and_token, tmp_curio, monkeypatch, caplog):
        """Honest absence, and never an exception into the delegation path —
        the same posture nodeContext and verification degrade with."""
        from utk_curio.backend.app.agents import services as services_mod
        from utk_curio.backend.app.packages import services as packages_services

        user, token = user_and_token
        pid = _project(client, token)
        key = _ukey(client, user)
        monkeypatch.setattr(
            packages_services, "agent_catalog_overview",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("registry down")),
        )
        with caplog.at_level("WARNING"):
            assert services_mod._authoring_reuse_evidence(key, pid) is None
        assert "reuse evidence" in caplog.text
        # And the delegation still gets its contract and proceeds.
        enriched = services_mod._enriched_delegate_inputs(
            key, pid, {}, "node.kind.author", {"look": "x"},
        )
        assert "existingPackages" not in enriched
        assert "buildRequestContract" in enriched

    def test_the_delegate_actually_receives_it_in_its_framed_inputs(
            self, client, user_and_token, tmp_curio, monkeypatch):
        """The regression for the reported duplication, at its source: a
        Researcher delegating node.kind.author while curio.notes@1 sits in the
        store. Today the child's context could not contain that fact, so it
        authored curio.notes and then curio.postits in one run."""
        user, token = user_and_token
        pid = _project(client, token)
        key = _ukey(client, user)
        _write_store_package(key, "curio.notes@1", "curio.notes", "Simple Notes",
                             ["note-surface"])
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _delegate_tail(),
            "curio.notes@1 already does this — I authored nothing.",
            "You already have a notes package; I can enlist it.",
        ])
        _run(client, token, pid, att_id)

        framed = " ".join(
            str(m.get("content", "")) for c in calls for m in c
            if "delegated task from" in str(m.get("content", ""))
        )
        assert framed, "the child must have received a framed task"
        assert "curio.notes@1" in framed
        assert "curio.notes/note-surface" in framed
        # Nothing was authored, and nothing was minted.
        assert all(
            p["type"] != "proposal"
            for p in _run(client, token, pid, att_id).get_json()["content"]
        )
