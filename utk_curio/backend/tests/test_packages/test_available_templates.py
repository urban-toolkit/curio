"""Tests for ``services.available_templates`` (memo dev/48).

The single source of template knowledge for agent node creation: seeded
``curio.builtin@<highest-major>`` plus the project's package lockfile —
nothing else, and unreadable packages are skipped.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.packages import services as packages_services
from utk_curio.backend.app.packages.storage import user_packageages_dir
from utk_curio.backend.app.projects import services as projects_services


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture()
def alice_project(client, user_and_token):
    _, token = user_and_token
    body = {
        "name": "tmpl-proj",
        "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
        "outputs": [],
    }
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201
    return resp.get_json()["id"]


def _template(template_id, label, *, editor="code", has_code=None, has_grammar=None, description=""):
    t = {
        "id": template_id,
        "label": label,
        "category": "computation",
        "engine": "python",
        "editor": editor,
        "description": description,
        "inputPorts": [],
        "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
    }
    if has_code is not None:
        t["hasCode"] = has_code
    if has_grammar is not None:
        t["hasGrammar"] = has_grammar
    return t


def _write_package(user_key, package_id, major, templates, *, broken=False):
    d = user_packageages_dir(user_key) / f"{package_id}@{major}"
    d.mkdir(parents=True, exist_ok=True)
    if broken:
        (d / "manifest.json").write_text("{not json", encoding="utf-8")
        return
    manifest = {
        "id": package_id,
        "version": f"{major}.0.0",
        "name": package_id,
        "publisher": "Test",
        "description": "test",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": major},
        "permissions": [],
        "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": templates,
        "createdAt": "2026-06-01T12:00:00Z",
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _lockfile_add(user_key, project_id, dir_name):
    from utk_curio.backend.app.packages.spec_packages import set_project_packages
    from utk_curio.backend.app.projects import storage as projects_storage

    spec = projects_storage.read_spec(user_key, project_id)
    current = set(spec.get("dataflow", {}).get("packages") or [])
    entries = current | {dir_name}
    set_project_packages(spec, entries)
    projects_storage.write_spec(user_key, project_id, spec)


class TestAvailableTemplates:
    def test_builtin_plus_lockfile_only(self, user_and_token, alice_project, tmp_curio):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("computation-analysis", "Computation")])
        _write_package(key, "ai.test.locked", 1, [_template("locked-kind", "Locked")])
        _write_package(key, "ai.test.storeonly", 1, [_template("store-kind", "StoreOnly")])
        _lockfile_add(key, alice_project, "ai.test.locked@1")

        ids = {t["id"] for t in packages_services.available_templates(key, alice_project)}
        # Builtin is always in scope; a store-installed package NOT in the
        # project lockfile is not (dev/48 permitted scope).
        assert ids == {"curio.builtin/computation-analysis", "ai.test.locked/locked-kind"}

    def test_authorable_flag_from_manifest(self, user_and_token, alice_project, tmp_curio):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [
            _template("code-kind", "Code", editor="code"),
            _template("grammar-kind", "Grammar", editor="grammar"),
            _template("widget-kind", "Widgets", editor="widgets", has_code=False),
        ])
        by_id = {t["id"]: t for t in packages_services.available_templates(key, alice_project)}
        assert by_id["curio.builtin/code-kind"]["authorable"] is True
        assert by_id["curio.builtin/grammar-kind"]["authorable"] is True
        assert by_id["curio.builtin/widget-kind"]["authorable"] is False

    def test_unreadable_package_is_skipped(self, user_and_token, alice_project, tmp_curio):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("ok-kind", "OK")])
        _write_package(key, "ai.test.broken", 1, [], broken=True)
        _lockfile_add(key, alice_project, "ai.test.broken@1")
        ids = {t["id"] for t in packages_services.available_templates(key, alice_project)}
        assert ids == {"curio.builtin/ok-kind"}

    def test_highest_builtin_major_wins(self, user_and_token, alice_project, tmp_curio):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("shared-kind", "Old")])
        _write_package(key, "curio.builtin", 2, [_template("shared-kind", "New")])
        by_id = {t["id"]: t for t in packages_services.available_templates(key, alice_project)}
        assert by_id["curio.builtin/shared-kind"]["label"] == "New"

    def test_missing_project_degrades_to_builtin_only(self, user_and_token, tmp_curio):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("only-kind", "Only")])
        ids = {t["id"] for t in packages_services.available_templates(key, "no-such-project")}
        assert ids == {"curio.builtin/only-kind"}
