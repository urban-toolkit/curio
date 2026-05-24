"""Unit tests for :mod:`utk_curio.backend.app.packages.catalog_family`."""

from __future__ import annotations

import pytest

from utk_curio.backend.app.packages.catalog_family import (
    CatalogReleaseTriple,
    catalog_release_collision_groups,
    family_key_for_manifest,
)
from utk_curio.backend.app.packages.manifest import ManifestError, load_packageage_manifest
from utk_curio.backend.app.packages.package_channel import normalize_distribution_channel


def test_normalize_distribution_channel():
    assert normalize_distribution_channel(None) == "stable"
    assert normalize_distribution_channel("beta") == "beta"
    assert normalize_distribution_channel("BAD TOKEN!") == "stable"


def test_catalog_release_collision_groups_finds_duplicate():
    g = catalog_release_collision_groups(
        [
            ("a@1", CatalogReleaseTriple("root@1", "stable", "1.0.0")),
            ("b@1", CatalogReleaseTriple("root@1", "stable", "1.0.0")),
        ]
    )
    assert len(g) == 1
    assert set(g[0]["dirNames"]) == {"a@1", "b@1"}


def test_family_key_for_manifest_fork_and_singleton():
    from utk_curio.backend.app.packages.manifest import PackageLineage, PackageLineageCoord, PackageManifest

    alone = PackageManifest(
        package_id="solo",
        major=1,
        version="1.0",
        name="",
        publisher="",
        description="",
        license=None,
    )
    assert family_key_for_manifest(alone) == "solo@1"

    fork = PackageManifest(
        package_id="fork",
        major=2,
        version="1.0",
        name="",
        publisher="",
        description="",
        license=None,
        lineage=PackageLineage(
            forked_from=PackageLineageCoord("parent", 1),
            root=PackageLineageCoord("rootfam", 1),
        ),
    )
    assert family_key_for_manifest(fork) == "rootfam@1"


def test_manifest_distribution_wrong_type(tmp_path):
    d = tmp_path / "ai.test.chan@1"
    d.mkdir()
    manifest = {
        "id": "ai.test.chan",
        "version": "1.0.0",
        "name": "Chan",
        "publisher": "T",
        "description": "d",
        "license": "MIT",
        "compatibility": {"major": 1},
        "permissions": [],
        "dependencies": {"packages": {}, "python": {}, "js": {}},
        "kinds": [{
            "id": "k",
            "label": "K",
            "category": "computation",
            "engine": "python",
            "editor": "code",
            "hasCode": True,
            "hasWidgets": False,
            "hasGrammar": False,
            "inputPorts": [],
            "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "templateDir": "templates/k",
            "defaultTemplate": "templates/k/Default.py",
        }],
        "distribution": "oops",
    }
    (d / "manifest.json").write_text(__import__("json").dumps(manifest))
    with pytest.raises(ManifestError, match="distribution must be an object"):
        load_packageage_manifest(d)
