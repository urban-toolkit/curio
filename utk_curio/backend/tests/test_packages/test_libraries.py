"""Tests for the per-user 'Installed libraries' surface.

Covers the storage helpers (``libraries.py``) and the HTTP endpoints
(``GET/POST/DELETE /api/packages/libraries``). The pip runner is stubbed
by ``conftest.py`` so these tests don't shell out.
"""

from __future__ import annotations

import json

from utk_curio.backend.app.packages import libraries as libs


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_load_missing_file_returns_empty(tmp_curio):
    data = libs.list_standalone("guest")
    assert data == {"python": [], "js": []}


def test_add_then_list_round_trip(tmp_curio):
    libs.add_library("guest", "python", "numpy")
    libs.add_library("guest", "python", "scikit-learn==1.4.0")
    data = libs.list_standalone("guest")
    assert sorted(data["python"]) == ["numpy", "scikit-learn==1.4.0"]
    assert data["js"] == []


def test_add_is_idempotent(tmp_curio):
    libs.add_library("guest", "python", "numpy")
    libs.add_library("guest", "python", "numpy")
    assert libs.list_standalone("guest")["python"] == ["numpy"]


def test_add_rejects_unknown_kind(tmp_curio):
    try:
        libs.add_library("guest", "rust", "tokio")
    except ValueError as e:
        assert "kind" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_remove_idempotent(tmp_curio):
    libs.add_library("guest", "python", "numpy")
    libs.remove_library("guest", "python", "numpy")
    libs.remove_library("guest", "python", "numpy")  # already gone
    assert libs.list_standalone("guest")["python"] == []


def test_corrupt_file_is_treated_as_empty(tmp_curio):
    p = libs._path("guest")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert libs.list_standalone("guest") == {"python": [], "js": []}


def test_package_derived_reads_installed_manifests(
    tmp_curio, install_packageage, manifest_dict,
):
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.pyheavy",
            python_deps={"torch": ">=2.0", "transformers": "~=4.30"},
        ),
    )
    derived = libs.package_derived("guest")
    derived_python = sorted([(e.name, e.spec) for e in derived if e.kind == "python"])
    assert ("torch", ">=2.0") in derived_python
    assert ("transformers", "~=4.30") in derived_python
    assert all(e.source.startswith("ai.test.pyheavy@") for e in derived if e.kind == "python")


def test_aggregate_combines_standalone_and_package(
    tmp_curio, install_packageage, manifest_dict,
):
    libs.add_library("guest", "python", "scikit-learn==1.4")
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.combine",
            python_deps={"numpy": "^1.26"},
        ),
    )
    agg = libs.aggregate("guest")
    assert agg.standalone["python"] == ["scikit-learn==1.4"]
    package_names = {e.name for e in agg.from_packages}
    assert "numpy" in package_names


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

class TestLibraryRoutes:
    def test_list_empty_for_fresh_user(self, client, user_and_token):
        _, token = user_and_token
        resp = client.get("/api/packages/libraries", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["standalone"] == {"python": [], "js": []}
        # Fresh user is auto-seeded with curio.builtin@1 which has no deps
        assert isinstance(body["fromPackages"], list)

    def test_post_python_then_list(self, client, user_and_token):
        _, token = user_and_token
        resp = client.post(
            "/api/packages/libraries",
            json={"kind": "python", "spec": "numpy"},
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        listed = client.get("/api/packages/libraries", headers=_auth(token)).get_json()
        assert listed["standalone"]["python"] == ["numpy"]

    def test_post_rejects_empty_spec(self, client, user_and_token):
        _, token = user_and_token
        resp = client.post(
            "/api/packages/libraries",
            json={"kind": "python", "spec": "  "},
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_post_js_returns_501_not_supported(self, client, user_and_token):
        _, token = user_and_token
        resp = client.post(
            "/api/packages/libraries",
            json={"kind": "js", "spec": "lodash"},
            headers=_auth(token),
        )
        assert resp.status_code == 501

    def test_delete_round_trip(self, client, user_and_token):
        _, token = user_and_token
        client.post(
            "/api/packages/libraries",
            json={"kind": "python", "spec": "numpy"},
            headers=_auth(token),
        )
        resp = client.delete(
            "/api/packages/libraries/python/numpy",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["standalone"]["python"] == []

    def test_post_includes_package_derived_in_list(
        self, client, user_and_token, install_packageage, manifest_dict,
    ):
        from utk_curio.backend.app.projects.services import _user_dir_key
        user, token = user_and_token
        install_packageage(
            _user_dir_key(user),
            manifest=manifest_dict(
                package_id="ai.test.routes",
                python_deps={"requests": ">=2.0"},
            ),
        )
        body = client.get("/api/packages/libraries", headers=_auth(token)).get_json()
        derived_names = [e["name"] for e in body["fromPackages"]]
        assert "requests" in derived_names
