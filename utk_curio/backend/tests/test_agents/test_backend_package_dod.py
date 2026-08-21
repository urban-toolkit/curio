"""memo dev/91 commit 6 — the backend-package DOD: the agent lane REFUSES a
violating draft with the finding in the model's face (the A4 refusal rule),
the Package Builder's prompt carries the ONE backend authoring contract
(and no longer the dev/89 refusal paragraph), and the server-owned
buildRequestContract teaches the same schema (the A8 lesson — nobody invents
a schema they were shown). The happy path — mint with real-worker probe →
card trust edge → Apply promotes + pins → route computes — is pinned by
``TestBackendDraftEndToEnd`` (commit 4); this suite owns the refusal and
contract surfaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.tests.test_agents.test_routes import (
    TestBackendDraftEndToEnd,
    TestPackageBuilderTools,
    _auth,
)

_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "llm-prompts" / "package_build_instruction.txt"
)


@pytest.fixture(autouse=True)
def _fresh_build_jobs():
    from utk_curio.backend.app.packages import build_jobs

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
        text = _PROMPT_PATH.read_text(encoding="utf-8")
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
            "dev/89 Follow-up B",
        ):
            assert marker in text, marker

    def test_the_dev89_refusal_paragraph_is_gone(self):
        text = _PROMPT_PATH.read_text(encoding="utf-8")
        assert "out of scope: report that it awaits" not in text
        # The scan families are named so the model authors within them.
        assert "subprocess/multiprocessing/ctypes" in text
        assert "eval/exec/compile/__import__/importlib" in text

    def test_build_request_contract_teaches_the_backend_keys(self):
        from utk_curio.backend.app.agents.services import _BUILD_REQUEST_CONTRACT

        text = json.dumps(_BUILD_REQUEST_CONTRACT)
        for marker in (
            "backend/handler.py",
            "timeoutClass",
            "backendHandler",
            "server-code",
            "server-network",
            "def handle(payload)",
            "CURIO_PKG_DATA_DIR",
            "Follow-up B",
        ):
            assert marker in text, marker
        # The shape names the handler grammar and the payload contract.
        assert "'content': <editor text>" in text
