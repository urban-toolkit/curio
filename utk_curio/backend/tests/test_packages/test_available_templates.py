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


def _template(template_id, label, *, editor="code", has_code=None, has_grammar=None, description="", input_ports=None):
    t = {
        "id": template_id,
        "label": label,
        "category": "computation",
        "engine": "python",
        "editor": editor,
        "description": description,
        "inputPorts": input_ports if input_ports is not None else [],
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


class TestParseCardinality:
    """dev/67-3 (DEC-051) — one parser for the schema's cardinality grammar."""

    def test_all_schema_forms(self):
        from utk_curio.backend.app.packages.manifest import parse_cardinality

        assert parse_cardinality("1") == (1, 1)
        assert parse_cardinality("2") == (2, 2)
        assert parse_cardinality("n") == (0, None)
        assert parse_cardinality("[1,n]") == (1, None)
        assert parse_cardinality("[0,2]") == (0, 2)
        assert parse_cardinality("[1,2]") == (1, 2)
        # Unparseable fails OPEN — the schema owns the grammar.
        assert parse_cardinality("") == (0, None)
        assert parse_cardinality("banana") == (0, None)


class TestInputArity:
    """dev/67-3 (DEC-051) — maxIncomingEdges is the RENDERED truth: one edge
    per rendered handle (handles = ports); merge-flow's slots are the sole
    multi-edge surface."""

    def _templates(self, user_and_token, alice_project, tmp_curio):
        from utk_curio.backend.app.projects import services as projects_services

        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [
            _template("data-loading", "Load", input_ports=[]),
            _template("computation-analysis", "Compute",
                      input_ports=[{"types": ["DATAFRAME"], "cardinality": "[1,n]"}]),
            _template("spatial-join", "Spatial Join",
                      input_ports=[{"types": ["GEODATAFRAME"], "cardinality": "1"},
                                   {"types": ["GEODATAFRAME"], "cardinality": "1"}]),
            _template("merge-flow", "Merge",
                      input_ports=[{"types": ["DATAFRAME"], "cardinality": "[1,n]"}]),
        ])
        return {
            t["id"]: t
            for t in packages_services.available_templates(key, alice_project)
        }

    def test_rendered_capacity_rules(self, user_and_token, alice_project, tmp_curio):
        by_id = self._templates(user_and_token, alice_project, tmp_curio)
        assert by_id["curio.builtin/data-loading"]["maxIncomingEdges"] == 0
        # Declared [1,n] is NOT enforceable capacity — the input plumbing is
        # scalar per handle (a second edge silently overwrites data.input).
        assert by_id["curio.builtin/computation-analysis"]["maxIncomingEdges"] == 1
        assert by_id["curio.builtin/spatial-join"]["maxIncomingEdges"] == 2
        # Merge's rendered slot machinery wins over its declared [1,n].
        assert by_id["curio.builtin/merge-flow"]["maxIncomingEdges"] == 5

    def test_declared_cardinality_survives_as_metadata(self, user_and_token, alice_project, tmp_curio):
        by_id = self._templates(user_and_token, alice_project, tmp_curio)
        assert by_id["curio.builtin/computation-analysis"]["inputs"] == [
            {"types": ["DATAFRAME"], "min": 1, "max": None},
        ]
        assert by_id["curio.builtin/spatial-join"]["inputs"] == [
            {"types": ["GEODATAFRAME"], "min": 1, "max": 1},
            {"types": ["GEODATAFRAME"], "min": 1, "max": 1},
        ]
