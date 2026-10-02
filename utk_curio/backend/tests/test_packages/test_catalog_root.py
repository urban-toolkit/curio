"""Where the shared package catalog lives, and who may move it.

``<repo_root>/packages/`` is committed, and publishing into it is a
deliberate developer action: the package is meant to show up in ``git
status`` and be reviewed. What it must not be is the one directory every
process on the machine shares regardless of what else it was given its own
copy of.

It was exactly that. Two backends with separate ``CURIO_STATE_DIR``,
``CURIO_SHARED_DATA``, databases, users and sandboxes still shared this path,
because it was computed from the module's own file location: a publish on the
first appeared in the second's catalog listing, and landed untracked in the
git-managed tree. Under pytest-xdist that is one worker's fixture package
showing up in another worker's catalog mid-test, and a run killed at the
wrong moment leaving a package directory behind.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from utk_curio.backend.app.packages import service as packages_service
from utk_curio.backend.app.packages.repositories.catalog_dir import catalog_root

PACKAGES_APP = Path(__file__).resolve().parents[2] / "app" / "packages"

REPO_CATALOG = Path(__file__).resolve().parents[4] / "packages"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _draft():
    return {
        "manifest": {
            "id": "ai.test.relocatable",
            "version": "1.0.0",
            "createdAt": "2000-01-01T00:00:00Z",
            "name": "Relocatable",
            "publisher": "Tests",
            "description": "Published by the catalog-root test",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "demo", "label": "Demo", "category": "computation",
                "engine": "python", "editor": "code", "hasCode": True,
                "hasWidgets": False, "hasGrammar": False,
                "inputPorts": [],
                "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                "source": "sources/demo.py",
            }],
        },
        "sources": {"demo": {"filename": "demo.py",
                             "code": "def run():\n    return {}\n"}},
    }


def _install_and_publish(client, token) -> int:
    """Save the draft into the caller's store, then publish that copy."""
    installed = client.post("/api/packages/factory/install", json=_draft(), headers=_auth(token))
    assert installed.status_code == 201, installed.get_data(as_text=True)
    return client.post(
        "/api/packages/factory/publish-catalog",
        json={"dirName": "ai.test.relocatable@1"},
        headers=_auth(token),
    ).status_code


def test_the_default_is_the_committed_catalog(monkeypatch):
    """Unset means the repo, so a developer's publish still lands there."""
    monkeypatch.delenv("CURIO_PACKAGES_ROOT", raising=False)
    assert catalog_root() == REPO_CATALOG


def test_every_module_resolves_the_same_root(monkeypatch, tmp_path):
    """Three modules used to carry three copies of the same path expression.

    Since memo dev/143 there is ONE, in ``repositories.catalog_dir``: the
    routes, the seeder and the facade read it rather than carrying a copy, so
    the override has exactly one place to be honoured.
    """
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(tmp_path / "catalog"))
    assert catalog_root() == (tmp_path / "catalog").resolve()
    assert packages_service.catalog_root is catalog_root
    definitions = [
        f.relative_to(PACKAGES_APP).as_posix()
        for f in PACKAGES_APP.rglob("*.py")
        if "def catalog_root(" in f.read_text() or "def _catalog_root(" in f.read_text()
    ]
    assert definitions == ["repositories/catalog_dir.py"], definitions


def test_a_publish_goes_where_the_override_points(
    client, user_and_token, tmp_curio, monkeypatch, tmp_path,
):
    """The whole point: a test publish must not reach the committed catalog."""
    _, token = user_and_token
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(catalog))

    assert _install_and_publish(client, token) == 201

    published = catalog / "ai.test.relocatable@1"
    assert published.is_dir(), f"published nothing into {catalog}"
    assert not (REPO_CATALOG / "ai.test.relocatable@1").exists(), (
        "the publish reached the committed catalog; a test run would dirty "
        "the working tree and leak the package to every other worker"
    )


def test_a_publish_is_invisible_to_a_differently_rooted_catalog(
    client, user_and_token, tmp_curio, monkeypatch, tmp_path,
):
    """Two roots, two listings. This is the cross-worker case."""
    mine, theirs = tmp_path / "mine", tmp_path / "theirs"
    for d in (mine, theirs):
        d.mkdir()
    _, token = user_and_token

    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(mine))
    assert _install_and_publish(client, token) == 201

    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(theirs))
    listed = client.get("/api/packages/catalog", headers=_auth(token)).get_json()
    assert "ai.test.relocatable@1" not in {
        p["dirName"] for p in listed["packages"]
    }, "a publish under one catalog root showed up under another"
