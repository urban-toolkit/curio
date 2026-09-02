"""memo dev/95 — Dataflow Builder → Researcher delegation (dev/90 Follow-up D).

Commit 1 surface: the FIFTH runtime-supplied-inputs application — a tool-less
``research.notes.compose`` child gets the runtime-run search, the installed
presentation-template candidates, and the reply schema as INPUTS (DEC-063:
an instruction must be executable on every path its agent runs on)."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents import tools as agent_tools
from utk_curio.backend.app.common.user_storage import users_base
from utk_curio.backend.app.agents.services import (
    _NOTES_REPLY_CONTRACT,
    _delegated_search_results,
    _enriched_delegate_inputs,
)


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ── the runtime-run search ───────────────────────────────────────────────────
class TestDelegatedSearch:
    def test_missing_question_is_an_honest_error(self):
        for bad in (None, "", "   ", 42):
            out = _delegated_search_results(bad)
            assert "error" in out and "question" in out["error"]

    def test_ok_results_are_bounded(self, monkeypatch):
        rows = [{"title": "t" * 999, "url": "https://e.test/" + "u" * 999,
                 "snippet": "s" * 999} for _ in range(9)]
        monkeypatch.setattr(
            agent_tools, "_execute_web_search",
            lambda params: ("ok", json.dumps({"results": rows})))
        out = _delegated_search_results("weather in Paris")
        assert out["query"] == "weather in Paris"
        assert len(out["results"]) == 5  # row cap
        for row in out["results"]:
            assert set(row) == {"title", "url", "snippet"}
            assert all(len(v) <= 300 for v in row.values())  # field cap

    def test_provider_error_rides_in_verbatim(self, monkeypatch):
        monkeypatch.setattr(
            agent_tools, "_execute_web_search",
            lambda params: ("error", "web search is not configured "
                            "(set CURIO_SEARCH_URL) — …"))
        out = _delegated_search_results("anything")
        assert "CURIO_SEARCH_URL" in out["error"]

    def test_malformed_provider_json_is_honest(self, monkeypatch):
        monkeypatch.setattr(
            agent_tools, "_execute_web_search", lambda params: ("ok", "[not json"))
        out = _delegated_search_results("anything")
        assert "malformed" in out["error"]


# ── the enrichment branch ────────────────────────────────────────────────────
class TestNotesComposeEnrichment:
    def test_all_three_inputs_injected(self, tmp_curio, monkeypatch):
        monkeypatch.setattr(
            agent_tools, "_execute_web_search",
            lambda params: ("ok", json.dumps({"results": [
                {"title": "T", "url": "https://e.test", "snippet": "S"}]})))
        enriched = _enriched_delegate_inputs(
            "guest", "p1", {}, "research.notes.compose",
            {"question": "what's the weather in Paris?"})
        assert enriched["searchResults"]["results"][0]["title"] == "T"
        assert enriched["notesReplyContract"] is _NOTES_REPLY_CONTRACT
        assert isinstance(enriched["notesTemplates"], list)
        assert enriched["question"] == "what's the weather in Paris?"

    def test_model_supplied_keys_always_win(self, tmp_curio, monkeypatch):
        def _never(params):  # pragma: no cover — must not run
            raise AssertionError("the runtime must not re-search supplied results")

        monkeypatch.setattr(agent_tools, "_execute_web_search", _never)
        supplied = {"question": "q", "searchResults": {"results": []},
                    "notesTemplates": [{"id": "x/y"}],
                    "notesReplyContract": {"mine": True}}
        enriched = _enriched_delegate_inputs(
            "guest", "p1", {}, "research.notes.compose", supplied)
        assert enriched == supplied

    def test_contract_teaches_the_a13_row_and_the_honesty_rule(self):
        text = json.dumps(_NOTES_REPLY_CONTRACT)
        for marker in ("inputs.searchResults", "NEVER invent findings",
                       "title 'Question', color yellow", "notesTemplates",
                       "empty notes list is valid"):
            assert marker in text, marker


# ── the presentation-template candidates ─────────────────────────────────────
class TestPresentationTemplates:
    def _install(self, tmp_path, monkeypatch, *, dir_name="curio.notes@1",
                 enlist_project=None):
        monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
        # ``users_base()``, not a literal: under CURIO_TESTING the tree is
        # ``.curio/test/users/``, so a hand-built ``.curio/users/`` is invisible
        # to the code under test. Called after the monkeypatch above, which is
        # the env it reads.
        pkg = users_base() / "guest" / "packages" / dir_name
        pkg.mkdir(parents=True)
        manifest = {
            "id": dir_name.split("@")[0], "version": "1.0.0", "name": "Notes",
            "publisher": "t", "description": "d",
            "compatibility": {"major": int(dir_name.split("@")[1])},
            "permissions": [],
            "templates": [
                {"id": "note-surface", "label": "Note", "category": "visualization",
                 "engine": "javascript", "editor": "none", "hasCode": False,
                 "behavior": "note-behavior", "inputPorts": [], "outputPorts": [],
                 "description": "a post-it note"},
                {"id": "note-tool", "label": "Note tool", "category": "computation",
                 "engine": "python", "editor": "code", "hasCode": True,
                 "inputPorts": [], "outputPorts": []},
            ],
        }
        (pkg / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if enlist_project:
            proj = users_base() / "guest" / "projects" / enlist_project
            proj.mkdir(parents=True, exist_ok=True)
            (proj / "spec.trill.json").write_text(json.dumps({
                "dataflow": {"nodes": [], "edges": [], "packages": [dir_name]},
            }), encoding="utf-8")
        return pkg

    def test_only_enlisted_presentation_templates_listed(self, tmp_path, monkeypatch):
        from utk_curio.backend.app.packages.services import presentation_templates

        self._install(tmp_path, monkeypatch, enlist_project="p1")
        rows = presentation_templates("guest", "p1")
        assert rows == [{"id": "curio.notes/note-surface", "label": "Note",
                         "description": "a post-it note"}]

    def test_installed_but_not_enlisted_is_excluded(self, tmp_path, monkeypatch):
        from utk_curio.backend.app.packages.services import presentation_templates

        self._install(tmp_path, monkeypatch)  # no project lockfile entry
        assert presentation_templates("guest", "p-other") == []


# ── the reply parser (commit 2) ──────────────────────────────────────────────
class TestExtractNotesReply:
    def test_bare_and_fenced_objects_parse(self):
        from utk_curio.backend.app.agents.services import _extract_notes_reply

        payload = {"answer": "A", "notes": [{"title": "Q", "content": "c"}]}
        assert _extract_notes_reply(json.dumps(payload)) == payload
        fenced = "Here you go:\n```json\n" + json.dumps(payload) + "\n```"
        assert _extract_notes_reply(fenced) == payload
        answer_only = {"answer": "search unavailable", "notes": []}
        assert _extract_notes_reply(json.dumps(answer_only)) == answer_only

    def test_schema_only_never_prose_intent(self):
        from utk_curio.backend.app.agents.services import _extract_notes_reply

        for text in (
            "I made two notes for you!",
            json.dumps({"answer": "no notes key"}),
            json.dumps({"notes": "not-a-list"}),
            json.dumps([{"notes": []}]),
            "", None,
        ):
            assert _extract_notes_reply(text) is None


# ── the mint's degraded paths (unit — they return before any store) ─────────
class TestMintDegradedPaths:
    def _mint(self, text, granted=("node.create",), tmp_path=None, monkeypatch=None):
        from utk_curio.backend.app.agents.services import _mint_notes_from_delegate

        if monkeypatch is not None and tmp_path is not None:
            monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
        return _mint_notes_from_delegate(
            "guest", "p1", {"granted": list(granted)}, text)

    def test_contract_miss_is_failed_with_the_contract_named(self):
        parts, text, outcome = self._mint("prose, not the schema")
        assert parts == [] and outcome == "failed"
        assert "notes reply contract" in text

    def test_empty_notes_is_a_valid_answer_only_reply(self):
        parts, text, outcome = self._mint(
            json.dumps({"answer": "It is 21°C.", "notes": []}))
        assert parts == [] and outcome == "ok" and text == "It is 21°C."

    def test_missing_grant_keeps_notes_as_text(self):
        parts, text, outcome = self._mint(
            json.dumps({"answer": "A", "notes": [{"content": "c"}]}), granted=())
        assert parts == [] and outcome == "failed"
        assert "not granted node.create" in text and text.startswith("A")

    def test_no_template_skips_notes_and_names_the_researcher(
            self, tmp_path, monkeypatch):
        parts, text, outcome = self._mint(
            json.dumps({"answer": "A", "notes": [{"content": "c"}]}),
            tmp_path=tmp_path, monkeypatch=monkeypatch)
        assert parts == [] and outcome == "ok"
        assert "notes skipped" in text and "Researcher" in text
        parts2, text2, outcome2 = self._mint(
            json.dumps({"answer": "A", "nodeType": "ghost/tpl",
                        "notes": [{"content": "c"}]}),
            tmp_path=tmp_path, monkeypatch=monkeypatch)
        assert parts2 == [] and outcome2 == "ok" and "not available" in text2


# ── the DFB E2E lane (commit 2 wiring + A16 sequence) ────────────────────────
DFB = "agent.dataflow-builder@1.0.0"
RESEARCHER = "agent.researcher@1.0.0"


def _notes_pkg_manifest() -> dict:
    return {
        "id": "curio.notes", "version": "1.0.0", "name": "Notes",
        "publisher": "t", "description": "d", "compatibility": {"major": 1},
        "permissions": [],
        "templates": [{
            "id": "note-surface", "label": "Note", "category": "visualization",
            "engine": "javascript", "editor": "none", "hasCode": False,
            "behavior": "note-behavior", "inputPorts": [], "outputPorts": [],
            "description": "a post-it note",
        }],
    }


class TestDataflowBuilderNotesLane:
    def _setup(self, client, user, token, monkeypatch, replies):
        from utk_curio.backend.app.projects.services import _user_dir_key

        resp = client.post("/api/projects", json={
            "name": "p",
            "spec": {"dataflow": {"nodes": [], "edges": [],
                                  "packages": ["curio.notes@1"]}},
            "outputs": [],
        }, headers=_auth(token))
        assert resp.status_code == 201
        pid = resp.get_json()["id"]
        with client.application.app_context():
            user_key = _user_dir_key(user)
        pkg = users_base() / user_key / "packages" / "curio.notes@1"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "manifest.json").write_text(
            json.dumps(_notes_pkg_manifest()), encoding="utf-8")
        for coord in (DFB, RESEARCHER):
            client.post(f"/api/agents/projects/{pid}/install",
                        json={"coord": coord}, headers=_auth(token))
        att_id = client.post(
            f"/api/agents/projects/{pid}/attachments",
            json={"coord": DFB, "target": {"kind": "canvas"}},
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
        monkeypatch.setattr(
            agent_tools, "_execute_web_search",
            lambda params: ("ok", json.dumps({"results": [
                {"title": "Paris weather", "url": "https://w.test",
                 "snippet": "21C clear"}]})))
        return pid, att_id, calls

    def _delegate_tail(self):
        return ('```curio.v1\n{"delegateRequest": {"capability": '
                '"research.notes.compose", "inputs": '
                '{"question": "what\'s the weather in Paris?"}}}\n```')

    def _child_reply(self):
        return json.dumps({
            "answer": "It is about 21°C and clear in Paris.",
            "nodeType": "curio.notes/note-surface",
            "notes": [
                {"title": "Question",
                 "content": "what's the weather in Paris?", "color": "yellow"},
                {"title": "Weather in Paris",
                 "content": "**Now:** ~21°C, clear\n\n- [source](https://w.test)",
                 "color": "green"},
            ],
        })

    def test_full_lane_delegate_two_cards_apply_both(
            self, client, user_and_token, tmp_curio, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        pid, att_id, calls = self._setup(client, user, token, monkeypatch, replies=[
            self._delegate_tail(),   # parent round 1: delegate
            self._child_reply(),     # CHILD (Researcher): the schema reply
            "Answered — review the notes above.",  # parent round 2
        ])
        run = client.post(
            f"/api/agents/projects/{pid}/attachments/{att_id}/run",
            json={"message": "what's the weather in Paris?"},
            headers=_auth(token))
        assert run.status_code == 200, run.get_data(as_text=True)
        parts = run.get_json()["content"]
        proposals = [p for p in parts if p["type"] == "proposal"]
        assert len(proposals) == 2  # the A13 row, jointly pending (A16)
        assert all(p["tool"] == "node.create" and p["status"] == "pending"
                   for p in proposals)
        assert proposals[0]["preview"] == "what's the weather in Paris?"
        assert "21°C" in proposals[1]["preview"]
        # The child saw runtime-gathered inputs, not tools.
        child_prompt = json.dumps(calls[1])
        assert "searchResults" in child_prompt and "21C clear" in child_prompt
        assert "notesReplyContract" in child_prompt
        # The delegation card reports ok with the answer riding the summary.
        delegation = next(p for p in parts if p["type"] == "delegation")
        assert delegation["status"] == "ok"

        # Apply BOTH — out of order, per A16.
        for proposal in reversed(proposals):
            resp = client.post(
                f"/api/agents/projects/{pid}/attachments/{att_id}"
                f"/proposals/{proposal['proposalId']}/apply",
                headers=_auth(token))
            assert resp.status_code == 200, resp.get_data(as_text=True)
        with client.application.app_context():
            user_key = _user_dir_key(user)
        spec = projects_storage.read_spec(user_key, pid)
        nodes = spec["dataflow"]["nodes"]
        assert len(nodes) == 2
        colors = sorted(n["metadata"]["appearance"]["backgroundColor"]
                        for n in nodes)
        assert colors == sorted(["#fff9b1", "#c7f5c4"]) or len(set(colors)) == 2

    def test_notes_shaped_prose_outside_delegation_never_mints(
            self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        pid, att_id, _ = self._setup(client, user, token, monkeypatch, replies=[
            self._child_reply(),  # the model TEXT carries a notes payload
            "done",
        ])
        run = client.post(
            f"/api/agents/projects/{pid}/attachments/{att_id}/run",
            json={"message": "hi"}, headers=_auth(token))
        assert run.status_code == 200
        assert all(p["type"] != "proposal" for p in run.get_json()["content"])


# ── the prompts carry the contract (commit 3) ────────────────────────────────
class TestPromptsCarryTheDelegationContract:
    def test_dfb_prompt_teaches_the_research_delegation(self):
        from utk_curio.backend.app.agents import builtin

        text = builtin.read_prompt_text("agent.dataflow-builder@1.0.0", "instruction")
        for marker in (
            '"research.notes.compose"',
            '{"question": "<their question>"}',
            "Never answer research questions from memory",
            "the notes mirror the chat",
            "notes were skipped",
            "point the user at the Researcher",
        ):
            assert marker in text, marker

    def test_researcher_prompt_carries_the_delegate_posture(self):
        from utk_curio.backend.app.agents import builtin

        text = builtin.read_prompt_text("agent.researcher@1.0.0", "instruction")
        for marker in (
            "[delegated task from",
            "inputs.searchResults",
            "inputs.notesTemplates",
            "inputs.notesReplyContract",
            "EXACTLY ONE JSON object",
            "say search was unavailable",
            "NEVER invent findings",
            "never emit a tool request",
        ):
            assert marker in text, marker
