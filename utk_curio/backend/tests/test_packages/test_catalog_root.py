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

from utk_curio.backend.app.packages import seed as packages_seed
from utk_curio.backend.app.packages import services as packages_services
from utk_curio.backend.app.packages import routes as packages_routes
from utk_curio.backend.app.packages.storage import catalog_root

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


def test_the_default_is_the_committed_catalog(monkeypatch):
    """Unset means the repo, so a developer's publish still lands there."""
    monkeypatch.delenv("CURIO_PACKAGES_ROOT", raising=False)
    assert catalog_root() == REPO_CATALOG


def test_every_module_resolves_the_same_root(monkeypatch, tmp_path):
    """Three modules used to carry three copies of the same path expression."""
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(tmp_path / "catalog"))
    resolved = {
        packages_routes._catalog_root(),
        packages_seed._catalog_root(),
        packages_services.catalog_root(),
    }
    assert resolved == {(tmp_path / "catalog").resolve()}


def test_a_publish_goes_where_the_override_points(
    client, user_and_token, tmp_curio, monkeypatch, tmp_path,
):
    """The whole point: a test publish must not reach the committed catalog."""
    _, token = user_and_token
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(catalog))

    resp = client.post(
        "/api/packages/factory/publish-catalog",
        json=_draft(),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)

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
    assert client.post(
        "/api/packages/factory/publish-catalog",
        json=_draft(), headers=_auth(token),
    ).status_code == 201

    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(theirs))
    listed = client.get("/api/packages/catalog", headers=_auth(token)).get_json()
    assert "ai.test.relocatable@1" not in {
        p["dirName"] for p in listed["packages"]
    }, "a publish under one catalog root showed up under another"
