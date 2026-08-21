"""memo dev/91 commit 4 — the /api/packages/<dir>/backend/<handler> route's
status matrix (§6): auth, body shape, bounds, unknown targets, and the
handler-error passthrough (a well-formed ok:false reply is a 200 — the
envelope IS the diagnosis; only worker/contract failures are 5xx)."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.packages import backend_contract as bc

PKG = "ai.test.counter@1"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _backend_manifest(manifest_dict) -> dict:
    m = manifest_dict(package_id="ai.test.counter")
    m["permissions"] = ["server-code"]
    m["backend"] = {
        "entry": "backend/handler.py",
        "handlers": [{"name": "word-count", "timeoutClass": "quick"},
                     {"name": "boom", "timeoutClass": "quick"}],
    }
    return m


_HANDLER = (
    "def _count(payload):\n"
    "    return {'words': len(str(payload.get('text', '')).split())}\n"
    "def _boom(payload):\n"
    "    raise RuntimeError('the handler exploded')\n"
    "HANDLERS = {'word-count': _count, 'boom': _boom}\n"
)


@pytest.fixture()
def installed_backend_pkg(client, user_and_token, tmp_curio, manifest_dict, make_archive):
    from utk_curio.backend.app.packages import backend_runtime
    from utk_curio.backend.app.packages.installer import install_packageage_from_archive
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    with client.application.app_context():
        user_key = _user_dir_key(user)
    archive = make_archive(manifest=_backend_manifest(manifest_dict),
                           extra_files={"backend/handler.py": _HANDLER.encode()})
    install_packageage_from_archive(user_key, archive)
    backend_runtime.record_entry_pin(user_key, PKG)
    return user_key, token


class TestBackendRouteMatrix:
    def test_happy_path_computes(self, client, installed_backend_pkg):
        _, token = installed_backend_pkg
        r = client.post(f"/api/packages/{PKG}/backend/word-count",
                        json={"payload": {"text": "a b"}}, headers=_auth(token))
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["reply"]["ok"] is True and body["reply"]["result"] == {"words": 2}
        assert body["invocationId"] and body["entryDigest"]

    def test_handler_error_reply_is_a_200_with_the_envelope(self, client,
                                                            installed_backend_pkg):
        _, token = installed_backend_pkg
        r = client.post(f"/api/packages/{PKG}/backend/boom",
                        json={"payload": {}}, headers=_auth(token))
        assert r.status_code == 200
        reply = r.get_json()["reply"]
        assert reply["ok"] is False and reply["kind"] == "handler-error"
        assert "the handler exploded" in reply["error"]

    def test_auth_is_required(self, client, installed_backend_pkg):
        r = client.post(f"/api/packages/{PKG}/backend/word-count",
                        json={"payload": {}})
        assert r.status_code == 401

    def test_missing_payload_member_is_422(self, client, installed_backend_pkg):
        _, token = installed_backend_pkg
        for body in (None, [], {"text": "no payload key"}):
            r = client.post(f"/api/packages/{PKG}/backend/word-count",
                            data=json.dumps(body), headers=_auth(token))
            assert r.status_code == 422, body
            assert "payload" in r.get_json()["error"]

    def test_unknown_package_and_handler_404(self, client, installed_backend_pkg):
        _, token = installed_backend_pkg
        r = client.post("/api/packages/ai.test.ghost@1/backend/word-count",
                        json={"payload": {}}, headers=_auth(token))
        assert r.status_code == 404
        r2 = client.post(f"/api/packages/{PKG}/backend/ghost",
                         json={"payload": {}}, headers=_auth(token))
        assert r2.status_code == 404
        assert "word-count" in r2.get_json()["error"]  # names the declared set

    def test_oversized_payload_is_413_before_any_worker(self, client,
                                                        installed_backend_pkg):
        _, token = installed_backend_pkg
        blob = "x" * (bc.PAYLOAD_MAX_BYTES + 8192)
        r = client.post(f"/api/packages/{PKG}/backend/word-count",
                        data=json.dumps({"payload": blob}), headers=_auth(token))
        assert r.status_code == 413
        assert "request bound" in r.get_json()["error"]
