"""memo dev/91 commit 6 — the backend-package DOD: the agent lane REFUSES a
violating draft with the finding in the model's face (the A4 refusal rule),
a package-writing run holds the ONE backend authoring contract, once, as the
skill ``package-contract`` it is handed (and no longer the dev/89 refusal
paragraph), and the server-owned buildRequestContract teaches the draft's
shape (the A8 lesson — nobody invents a schema they were shown). The happy
path — mint with real-worker probe → card trust edge → Apply promotes + pins
→ route computes — is pinned by ``TestBackendDraftEndToEnd`` (commit 4); this
suite owns the refusal and contract surfaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_routes_proposals import (
    TestBackendDraftEndToEnd,
    TestPackageBuilderTools,
)

_PROMPT_PATH = (
    Path(__file__).resolve().parents[4] / "agents" / "agent.curio.node-builder@1" / "prompts"
    / "package_build_instruction.md"
)


def _prompt() -> str:
    """What a package-writing run of the Node Builder holds of its agent
    text: the skills it is handed, the package backend contract among them,
    then its prompt's source, rendered."""
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import agent_text, builtin

    coord = "agent.curio.node-builder@1"
    run = skill_runs.for_delegated("4242", "p", builtin.get_builtin_manifest(coord), "package.build", {}, None,
                                   builtin.read_prompt_text(coord, "system"))
    return f"{skill_runs.skills_text(run) or ''}\n\n{agent_text.render(_PROMPT_PATH)}"


@pytest.fixture(autouse=True)
def _fresh_build_jobs():
    from utk_curio.backend.app.packages.builder import jobs as build_jobs

    build_jobs.reset_registry()
    yield
    build_jobs.reset_registry()


@pytest.fixture()
def alice_project(client, user_and_token):
    _, token = user_and_token
    body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
            "outputs": []}
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


class TestViolatingBackendDraftRefused:
    def _violating_params(self, line: str) -> dict:
        params = TestBackendDraftEndToEnd()._backend_draft_params()
        params["files"]["backend/handler.py"]["text"] = (
            f"{line}\n" + params["files"]["backend/handler.py"]["text"]
        )
        return params

    @pytest.mark.parametrize("line,marker", [
        ("import subprocess", "process spawning"),
        ("import ctypes", "pure Python"),
        ("from flask import Flask", "resident services"),
        # Network without the server-network permission: the fix is named.
        ("import requests", "server-network"),
    ])
    def test_refusal_carries_the_finding_and_the_fix(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
            line, marker):
        _, token = user_and_token
        helper = TestPackageBuilderTools()
        att_id, calls = helper._setup(
            client, token, alice_project, monkeypatch,
            replies=[helper._draft_tail(self._violating_params(line)),
                     "Understood — revising."],
        )
        run = helper._run(client, token, alice_project, att_id,
                          message="build a word counter with a backend")
        assert run.status_code == 200
        # No proposal minted; nothing staged or installed.
        assert all(p["type"] != "proposal" for p in run.get_json()["content"])
        refusal = calls[1][-1]["content"]
        assert "backend policy blocked" in refusal
        assert marker in refusal
        assert "backend/handler.py:1" in refusal  # file:line — diagnosable

    def test_probe_failure_refusal_names_the_handler(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        helper = TestPackageBuilderTools()
        params = TestBackendDraftEndToEnd()._backend_draft_params()
        params["files"]["backend/handler.py"]["text"] = "import not_a_real_module\n"
        att_id, calls = helper._setup(
            client, token, alice_project, monkeypatch,
            replies=[helper._draft_tail(params), "Understood."],
        )
        run = helper._run(client, token, alice_project, att_id)
        assert all(p["type"] != "proposal" for p in run.get_json()["content"])
        refusal = calls[1][-1]["content"]
        assert "backend probe failed for handler 'word-count'" in refusal
        assert "not_a_real_module" in refusal


class TestPromptCarriesTheBackendContract:
    def test_backend_contract_markers_present(self):
        text = _prompt()
        for marker in (
            "ONE backend contract",
            '"entry": "backend/<file>.py"',
            "def handle(payload)",
            "HANDLERS dict",
            "'server-code' permission",
            "'server-network'",
            "backendHandler",
            '{"content": <the node\'s editor text>, "input": <upstream JSON or null>}',
            "CURIO_PKG_DATA_DIR",
            "probe phase",
            "naming the Curio activation lifecycle or the deferred secret mediation",
        ):
            assert marker in text, marker

    def test_the_dev89_refusal_paragraph_is_gone(self):
        text = _prompt()
        assert "out of scope: report that it awaits" not in text
        # The scan families are named so the model authors within them.
        assert "subprocess/multiprocessing/ctypes" in text
        assert "eval/exec/compile/__import__/importlib" in text

    def test_a_package_writing_run_is_taught_the_backend_keys(self):
        from utk_curio.backend.app.agents.application.turns.delegates import _build_request_contract

        contract = _build_request_contract()
        shape = json.dumps(contract["shape"])
        for marker in ("backend/handler.py", "timeoutClass", "backendHandler"):
            assert marker in shape, marker
        # The rest of the backend contract is the skill the run is handed,
        # not a second copy in its inputs: the run is taught each key by its
        # system turn and the contract its inputs carry.
        assert "backendContract" not in contract
        held = _prompt()
        taught = f"{held}\n{json.dumps(contract)}"
        for marker in (
            "backend/handler.py",
            "timeoutClass",
            "backendHandler",
            "server-code",
            "server-network",
            "def handle(payload)",
            "CURIO_PKG_DATA_DIR",
            "Curio activation lifecycle",
        ):
            assert marker in taught, marker
        for marker in ("server-code", "server-network", "def handle(payload)", "CURIO_PKG_DATA_DIR",
                       "Curio activation lifecycle"):
            assert marker in held, marker
        # The backend contract names the handler grammar and the payload contract.
        assert held.count('{"content": <the node\'s editor text>, "input": <upstream JSON or null>}') == 1

    def test_the_run_holds_the_one_backend_contract_once(self):
        from utk_curio.backend.app.agents.application.turns.delegates import _build_request_contract
        from utk_curio.backend.app.agents.domain import agent_text, skills

        assert "package-contract" in [folder.name for folder in skills.shipped_folders()]
        shared = agent_text.skill_text("package-contract")
        assert shared.startswith("## Backend contract\n\nServer-side compute follows ONE backend contract")
        assert "backendContract" not in _build_request_contract()
        assert _prompt().count(shared) == 1
        assert shared not in agent_text.render(_PROMPT_PATH)


class TestLazyImportContract:
    """dev/97 (Option A): the probe runs before deps install — a
    module-level import of a DECLARED dep refuses naming the lazy-import
    fix in the model's face, and the lazy version of the same draft passes;
    the one backend contract a package-writing run is handed teaches the
    rule, once (A15)."""

    def _dep_params(self, entry_src: str) -> dict:
        params = TestBackendDraftEndToEnd()._backend_draft_params()
        params["dependencies"] = {"python": {"tiny-lib": "1.0.0"}}
        params["files"]["backend/handler.py"]["text"] = entry_src
        return params

    def test_module_level_declared_dep_refuses_naming_the_fix(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        helper = TestPackageBuilderTools()
        att_id, calls = helper._setup(
            client, token, alice_project, monkeypatch,
            replies=[helper._draft_tail(self._dep_params(
                # dist 'tiny-lib' → import 'tiny_lib' (the -/_ drift tolerated)
                "import tiny_lib\ndef handle(payload):\n    return {}\n")),
                "Understood."],
        )
        run = helper._run(client, token, alice_project, att_id)
        assert all(p["type"] != "proposal" for p in run.get_json()["content"])
        refusal = calls[1][-1]["content"]
        assert "backend probe failed" in refusal
        assert "DECLARED python dependency" in refusal
        assert "INSIDE your handler function" in refusal
        assert "does NOT exist at build time" in refusal

    def test_lazy_import_of_the_same_dep_passes_the_probe(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        helper = TestPackageBuilderTools()
        att_id, _ = helper._setup(
            client, token, alice_project, monkeypatch,
            replies=[helper._draft_tail(self._dep_params(
                "def handle(payload):\n"
                "    import tiny_lib  # lazy per the dev/97 contract\n"
                "    return {'v': tiny_lib.V}\n")),
                "Proposed."],
        )
        run = helper._run(client, token, alice_project, att_id)
        proposal = next(p for p in run.get_json()["content"]
                        if p["type"] == "proposal")
        assert proposal["status"] == "pending"
        assert proposal["draft"]["dependencies"]["home"] == "overlay"

    def test_undeclared_missing_module_gets_no_lazy_advice(
            self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        _, token = user_and_token
        helper = TestPackageBuilderTools()
        att_id, calls = helper._setup(
            client, token, alice_project, monkeypatch,
            replies=[helper._draft_tail(self._dep_params(
                "import totally_undeclared\ndef handle(payload):\n    return {}\n")),
                "Understood."],
        )
        helper._run(client, token, alice_project, att_id)
        refusal = calls[1][-1]["content"]
        assert "totally_undeclared" in refusal
        assert "DECLARED python dependency" not in refusal  # honest: not declared

    def test_the_run_is_taught_the_rule_once(self):
        from utk_curio.backend.app.agents.application.turns.delegates import _build_request_contract

        text = _prompt()
        assert text.count("Import declared python dependencies INSIDE your handler function") == 1
        assert "isolated overlay" in text
        assert text.count("fails the probe by construction") == 1
        assert "backendContract" not in _build_request_contract()
