"""memo dev/95 — Dataflow Builder → Researcher delegation (dev/90 Follow-up D).

Commit 1 surface: the FIFTH runtime-supplied-inputs application — a tool-less
``research.notes.compose`` child gets the runtime-run search, the installed
presentation-template candidates, and the reply schema as INPUTS (DEC-063:
an instruction must be executable on every path its agent runs on)."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents import tools as agent_tools
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
        pkg = tmp_path / ".curio" / "users" / "guest" / "packages" / dir_name
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
            proj = (tmp_path / ".curio" / "users" / "guest" / "projects"
                    / enlist_project)
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
