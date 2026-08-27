"""memo dev/96 — the rich package-draft review card's bounded payload.

The Apply text has always said the user reviews "the diff, dependencies,
and preview"; ``_draft_card_payload`` finally puts that slice on the part —
every list capped WITH its true total (the A6 bounded-part lesson; the
no-silent-caps rule), blocks sorted ahead of notes so a cap can never hide
one, absent sections absent."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.services import (
    _DRAFT_CARD_MAX_DEP_ROWS,
    _DRAFT_CARD_MAX_FILES,
    _DRAFT_CARD_MAX_FINDINGS,
    _draft_card_payload,
)
from utk_curio.backend.app.packages.build_models import (
    PackageBuildResult,
    parse_build_request,
)


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _request(*, nodes=None, files=None):
    return parse_build_request({
        "mode": "create",
        "manifest": {
            "id": "ai.test.card", "version": "1.0.0", "name": "Card",
            "publisher": "t", "description": "d",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [], "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "card-kind", "label": "Card", "category": "computation",
                "engine": "python", "editor": "code", "hasCode": True,
                "hasWidgets": False, "hasGrammar": False,
                "inputPorts": [], "outputPorts": [],
            }],
        },
        "files": files or {"starters/card-kind/Default.py": {"text": "return arg\n"}},
        **({"nodes": nodes} if nodes else {}),
    })


def _result(*, diff=None, sbom=None, preview=None):
    return PackageBuildResult(
        status="ready", input_digest="a" * 64, artifact_digest="b" * 64,
        diff=diff or {}, dependencies={"sbom": sbom} if sbom else {},
        preview=preview,
    )


class TestDraftCardComposer:
    def test_files_and_templates_cap_with_honest_totals(self):
        diff = {
            "files": {"added": [f"sources/f{i}.py" for i in range(50)],
                      "modified": ["a.py"], "preserved": [f"p{i}" for i in range(14)]},
            "templates": {"added": [f"kind-{i}" for i in range(12)],
                          "modified": [], "preserved": ["old-kind"]},
        }
        card = _draft_card_payload(_request(), _result(diff=diff))
        assert len(card["files"]["added"]) == _DRAFT_CARD_MAX_FILES
        assert card["files"]["addedTotal"] == 50      # nothing silently dropped
        assert card["files"]["modifiedTotal"] == 1
        assert card["files"]["preservedTotal"] == 14  # 0 would also be stated
        assert len(card["templates"]["added"]) == 10
        assert card["templates"]["addedTotal"] == 12
        assert card["templates"]["preservedTotal"] == 1

    def test_blocks_sort_ahead_so_the_cap_never_hides_one(self):
        findings = ([{"severity": "note", "code": f"n{i}", "message": "m"}
                     for i in range(_DRAFT_CARD_MAX_FINDINGS)]
                    + [{"severity": "block", "code": "the-block", "message": "bad"}])
        card = _draft_card_payload(_request(), _result(sbom={
            "python": [], "js": {"direct": [], "lock": {}},
            "findings": findings, "blocked": True,
        }))
        deps = card["dependencies"]
        assert deps["blocked"] is True
        assert deps["findings"][0]["code"] == "the-block"  # first, despite arriving last
        assert deps["findingsTotal"] == _DRAFT_CARD_MAX_FINDINGS + 1

    def test_dependency_rows_and_caps(self):
        sbom = {
            "python": [{"name": f"lib{i}", "constraint": "1.0.0"} for i in range(14)],
            "js": {"direct": [{"name": "marked", "constraint": "^12",
                               "resolvedVersion": "12.0.0"}], "lock": {}},
            "findings": [], "blocked": False,
        }
        card = _draft_card_payload(_request(), _result(sbom=sbom))
        deps = card["dependencies"]
        assert len(deps["python"]) == _DRAFT_CARD_MAX_DEP_ROWS
        assert deps["pythonTotal"] == 14
        assert deps["js"] == [{"name": "marked", "version": "12.0.0"}]

    def test_absent_sections_stay_absent(self):
        card = _draft_card_payload(_request(), _result())
        assert "dependencies" not in card
        assert "preview" not in card
        assert "requestedNodes" not in card
        assert card["files"]["preservedTotal"] == 0  # 0 is information

    def test_preview_verdicts_and_skip_honesty(self):
        preview = {
            "status": "skipped",
            "reasons": ["preview SKIPPED BY OPERATOR POLICY "
                        "(CURIO_BUILD_PREVIEW_POLICY=skip; no pinned runner is "
                        "configured) — this custom behavior was NOT rendered "
                        "before review", "r2", "r3", "r4"],
            "states": {}, "runnerVersion": "",
        }
        card = _draft_card_payload(_request(), _result(preview=preview))
        assert card["preview"]["status"] == "skipped"
        assert "SKIPPED BY OPERATOR POLICY" in card["preview"]["reasons"][0]
        assert len(card["preview"]["reasons"]) == 3 and card["preview"]["reasonsTotal"] == 4

    def test_preview_per_template_failed_states(self):
        preview = {
            "status": "failed", "reasons": ["note-kind/error: runtime/console errors: boom"],
            "states": {"note-kind": {
                "success": {"consoleErrors": [], "width": 100, "height": 80},
                "error": {"consoleErrors": ["boom"], "width": 100, "height": 80},
            }},
            "runnerVersion": "preview-runner/1",
        }
        card = _draft_card_payload(_request(), _result(preview=preview))
        assert card["preview"]["templates"] == [
            {"templateId": "note-kind", "ok": False, "failedStates": ["error"]}]

    def test_requested_nodes_rows(self):
        nodes = [{"templateId": "card-kind", "title": f"Note {i}",
                  "content": "x", "appearance": {"backgroundColor": "yellow"}}
                 for i in range(10)]
        card = _draft_card_payload(_request(nodes=nodes), _result())
        assert card["requestedNodes"]["total"] == 10
        assert len(card["requestedNodes"]["rows"]) == 8
        # The build request normalizes palette names at parse — the card
        # carries the CANONICAL hex (one color truth, dev/89).
        assert card["requestedNodes"]["rows"][0] == {"title": "Note 0",
                                                     "color": "#fef3c0"}

    def test_payload_size_ceiling(self):
        # Worst case stays a small part (the A6 lesson, pinned numerically).
        diff = {"files": {"added": [f"sources/{'f' * 100}{i}.py" for i in range(200)],
                          "modified": [f"m{i}" for i in range(200)],
                          "preserved": [f"p{i}" for i in range(500)]},
                "templates": {"added": [f"k{i}" for i in range(50)],
                              "modified": [f"j{i}" for i in range(50)],
                              "preserved": []}}
        sbom = {"python": [{"name": f"l{i}", "constraint": "1.0"} for i in range(99)],
                "js": {"direct": [{"name": f"d{i}", "resolvedVersion": "1"}
                                  for i in range(99)], "lock": {}},
                "findings": [{"severity": "warn", "code": f"c{i}",
                              "message": "M" * 900} for i in range(99)],
                "blocked": False}
        preview = {"status": "failed", "reasons": ["R" * 900] * 40,
                   "states": {f"tpl-{i}": {"error": {"consoleErrors": ["e"]}}
                              for i in range(40)}, "runnerVersion": "x"}
        nodes = [{"templateId": "card-kind", "title": "T" * 60, "content": "x"}
                 for _ in range(16)]  # MAX_REQUESTED_NODES bound
        card = _draft_card_payload(_request(nodes=nodes),
                                   _result(diff=diff, sbom=sbom, preview=preview))
        assert len(json.dumps(card)) < 20_000


class TestDraftCardOnTheMintedPart:
    def test_e2e_part_and_mirror_carry_the_card(self, client, user_and_token,
                                                tmp_curio, monkeypatch):
        # The existing draft lane, re-driven: the PART (reload-safe render
        # source) and the mirror both carry the composed slice.
        from utk_curio.backend.tests.test_agents.test_routes import (
            TestPackageBuilderTools,
            _auth as routes_auth,
        )

        _, token = user_and_token
        resp = client.post("/api/projects", json={
            "name": "p", "spec": {"dataflow": {"nodes": [], "edges": [],
                                               "packages": []}}, "outputs": [],
        }, headers=routes_auth(token))
        pid = resp.get_json()["id"]
        from utk_curio.backend.app.packages import build_jobs

        build_jobs.reset_registry()
        helper = TestPackageBuilderTools()
        att_id, _ = helper._setup(
            client, token, pid, monkeypatch,
            replies=[helper._draft_tail(helper._draft_params()), "Proposed."],
        )
        run = helper._run(client, token, pid, att_id)
        proposal = next(p for p in run.get_json()["content"]
                        if p["type"] == "proposal")
        draft = proposal["draft"]
        assert draft["mode"] == "create" and draft["target"] == helper.TARGET
        assert draft["files"]["addedTotal"] >= 1
        assert "starters/note-kind/Default.py" in draft["files"]["added"]
        assert draft["requestedNodes"]["total"] == 1
        assert draft["requestedNodes"]["rows"][0]["color"] == "#fbd3e0"  # pink, normalized
        # Reload path: the persisted turn's part carries it too.
        turns = client.get(
            f"/api/agents/projects/{pid}/attachments/{att_id}/session",
            headers=routes_auth(token)).get_json()["turns"]
        persisted = next(p for t in turns for p in t.get("content", [])
                         if p.get("type") == "proposal")
        assert persisted["draft"]["files"]["addedTotal"] >= 1


class TestDependencyHomeOnTheCard:
    """dev/97: the card states where the python deps will LIVE — the same
    routing core the install applies (one rule, two adapters)."""

    def _backend_request(self, *, warm=False):
        kinds = [{
            "id": "counter-kind", "label": "Counter", "category": "computation",
            "engine": "python", "editor": "none", "hasCode": False,
            "hasWidgets": False, "hasGrammar": False,
            "inputPorts": [], "outputPorts": [],
            "backendHandler": "word-count",
        }]
        if warm:
            kinds.append({
                "id": "warm-kind", "label": "Warm", "category": "computation",
                "engine": "python", "editor": "code", "hasCode": True,
                "hasWidgets": False, "hasGrammar": False,
                "inputPorts": [], "outputPorts": [],
            })
        return parse_build_request({
            "mode": "create",
            "manifest": {
                "id": "ai.test.card", "version": "1.0.0", "name": "Card",
                "publisher": "t", "description": "d",
                "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
                "permissions": ["server-code"],
                "dependencies": {"packages": {}, "python": {}, "js": {}},
                "backend": {"entry": "backend/handler.py",
                            "handlers": [{"name": "word-count"}]},
                "templates": kinds,
            },
            "files": {"backend/handler.py": {"text": "def handle(p):\n    return {}\n"}},
        })

    def _sbom(self):
        return {"python": [{"name": "tinylib", "constraint": "1.0.0"}],
                "js": {"direct": [], "lock": {}}, "findings": [], "blocked": False}

    def test_overlay_both_and_host_homes(self):
        overlay = _draft_card_payload(self._backend_request(), _result(sbom=self._sbom()))
        assert overlay["dependencies"]["home"] == "overlay"
        both = _draft_card_payload(self._backend_request(warm=True),
                                   _result(sbom=self._sbom()))
        assert both["dependencies"]["home"] == "both"
        host = _draft_card_payload(_request(), _result(sbom=self._sbom()))
        assert host["dependencies"]["home"] == "host"
