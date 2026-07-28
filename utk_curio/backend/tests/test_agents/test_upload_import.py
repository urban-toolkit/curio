"""Upload-import (memo dev/36): user-authored definitions, fail-closed."""

from __future__ import annotations

import hashlib
import json

import pytest

from utk_curio.backend.app.agents import storage
from utk_curio.backend.app.projects.services import _user_dir_key


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture()
def alice_project(client, user_and_token):
    _, token = user_and_token
    body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


INSTRUCTION = "You are the heat-risk summarizer. Answer with three bullet points."


def _payload(agent_id="agent.heat-risk-summarizer", version="1.0.0", **manifest_over):
    manifest = {
        "id": agent_id,
        "name": "Heat Risk Summarizer",
        "category": "node",
        "version": version,
        "purpose": "Summarize heat-risk outputs.",
        "capabilities": [{"id": "node.explain", "contractVersion": "1"}],
        "compatibleTargets": [{"kind": "node", "requires": []}, {"kind": "canvas", "requires": []}],
        "prompts": {
            "instruction": {"path": "prompts/instruction.txt", "variables": []},
        },
        "provenance": {"publisher": "karla"},
    }
    manifest.update(manifest_over)
    return {"manifest": manifest, "prompts": {"prompts/instruction.txt": INSTRUCTION}}


def _upload(client, token, payload=None):
    return client.post(
        "/api/agents/imports/upload", json=payload or _payload(), headers=_auth(token)
    )


class TestUploadImport:
    def test_upload_creates_owned_publishable_import(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        r = _upload(client, token)
        assert r.status_code == 201, r.get_data(as_text=True)
        card = r.get_json()
        assert card["scope"] == "my-imports"
        assert card["imported"] is True
        assert card["publishable"] is True  # reachable at last
        assert card["provenance"]["trust"] == "imported"
        # Bytes on disk with the server-stamped digest.
        ukey = _user_dir_key(user)
        d = storage.agent_definition_dir(ukey, card["dirName"])
        stored = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        assert stored["prompts"]["instruction"]["sha256"] == hashlib.sha256(
            INSTRUCTION.encode("utf-8")
        ).hexdigest()
        assert (d / "prompts/instruction.txt").read_text(encoding="utf-8") == INSTRUCTION
        # And it is listed in My Imports.
        listed = client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"]
        assert card["dirName"] in {a["dirName"] for a in listed}

    def test_full_loop_upload_publish_install_attach_run(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        calls = []

        def _fake_run(config, messages, **kwargs):
            calls.append(messages)  # call 1 = the run; call 2 = dev/25 auto-title
            return "three bullets"

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _fake_run
        )
        _, token = user_and_token
        coord = _upload(client, token).get_json()["dirName"]
        # Publish (imported-only) now genuinely works for a user definition.
        assert (
            client.post("/api/agents/publications", json={"coord": coord}, headers=_auth(token)).status_code
            == 201
        )
        cat = client.get("/api/agents/catalog", headers=_auth(token)).get_json()["agents"]
        mine = next(a for a in cat if a["dirName"] == coord)
        assert mine["published"] is True
        # Install → attach → run with the uploaded prompt as the system turn.
        client.post(
            f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token)
        )
        att = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att}/run",
            json={"message": "summarize"},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        from utk_curio.backend.app.agents import content as content_mod

        # dev/39: the runtime-owned structured-tail instruction composes last.
        assert calls[0][0] == {
            "role": "system",
            "content": f"{INSTRUCTION}\n\n{content_mod.TAIL_INSTRUCTION}",
        }

    def test_trust_is_forced_to_imported(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        payload = _payload(provenance={"publisher": "evil", "trust": "built-in"})
        card = _upload(client, token, payload).get_json()
        assert card["provenance"]["trust"] == "imported"
        assert card["publishable"] is True

    def test_duplicate_coordinate_is_409_immutable(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        assert _upload(client, token).status_code == 201
        r = _upload(client, token)
        assert r.status_code == 409
        assert "immutable" in r.get_json()["error"]
        # A bumped version is a new immutable artifact.
        assert _upload(client, token, _payload(version="1.0.1")).status_code == 201

    def test_shadowing_a_materialized_builtin_is_409(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        client.post(
            "/api/agents/imports", json={"coord": "agent.chat-agent@1.0.0"}, headers=_auth(token)
        )  # materializes the built-in into the store
        r = _upload(client, token, _payload(agent_id="agent.chat-agent", version="1.0.0"))
        assert r.status_code == 409

    def test_missing_and_extra_prompt_files_400(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        payload = _payload()
        payload["prompts"] = {}
        r = _upload(client, token, payload)
        assert r.status_code == 400 and "missing" in r.get_json()["error"]
        payload = _payload()
        payload["prompts"]["prompts/unreferenced.txt"] = "extra"
        r = _upload(client, token, payload)
        assert r.status_code == 400 and "not referenced" in r.get_json()["error"]

    def test_traversal_prompt_path_rejected(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        payload = _payload()
        payload["manifest"]["prompts"]["instruction"]["path"] = "../../evil.txt"
        payload["prompts"] = {"../../evil.txt": "boom"}
        r = _upload(client, token, payload)
        assert r.status_code == 400
        # Nothing escaped the store.
        assert not (storage.user_agents_dir("1").parent / "evil.txt").exists()

    def test_size_limits_413(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        payload = _payload()
        payload["prompts"]["prompts/instruction.txt"] = "x" * (256 * 1024 + 1)
        assert _upload(client, token, payload).status_code == 413
        payload = _payload()
        payload["prompts"] = {f"prompts/f{i}.txt": "x" for i in range(17)}
        assert _upload(client, token, payload).status_code == 413

    def test_malformed_manifest_and_body_400(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        assert _upload(client, token, {"manifest": "junk", "prompts": {}}).status_code == 400
        payload = _payload(id="curio.not-an-agent")
        assert _upload(client, token, payload).status_code == 400
        payload = _payload()
        payload["prompts"] = {"prompts/instruction.txt": 42}
        assert _upload(client, token, payload).status_code == 400

    def test_upload_never_auto_installs_or_publishes(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        coord = _upload(client, token).get_json()["dirName"]
        installed = client.get(
            f"/api/agents/projects/{alice_project}", headers=_auth(token)
        ).get_json()["agents"]
        assert coord not in {a["dirName"] for a in installed}
        cat = client.get("/api/agents/catalog", headers=_auth(token)).get_json()["agents"]
        mine = next((a for a in cat if a["dirName"] == coord), None)
        assert mine is None or mine["published"] is False
