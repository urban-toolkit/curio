"""Every committed package under ``packages/`` must load and serialize.

``test_builtin_package.py`` covers ``curio.builtin@1`` specifically. This walks
the whole shipped catalog, so a new entry is exercised the moment it is
committed rather than whenever someone remembers to add a test: both
``curio.example-ui@1`` and ``curio.weather@1`` landed with no coverage at all.

The catalog is baked into the deploy image, so a manifest that fails to load
here is a package that silently vanishes from every user's Browse tab.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.packages.manifest import load_packageage_manifest
from utk_curio.backend.app.packages.routes import _catalog_root, _manifest_to_payload

CATALOG = _catalog_root()
PACKAGE_DIRS = sorted(p for p in CATALOG.glob("*@*") if (p / "manifest.json").is_file())
IDS = [p.name for p in PACKAGE_DIRS]


def test_the_catalog_is_not_empty():
    # Guards the walk itself: a bad glob would turn every test below into a
    # vacuous pass.
    assert PACKAGE_DIRS, f"no packages discovered under {CATALOG}"


@pytest.mark.parametrize("package_root", PACKAGE_DIRS, ids=IDS)
def test_manifest_loads(package_root: Path):
    assert load_packageage_manifest(package_root) is not None


@pytest.mark.parametrize("package_root", PACKAGE_DIRS, ids=IDS)
def test_manifest_serializes_to_a_catalog_payload(package_root: Path):
    payload = _manifest_to_payload(load_packageage_manifest(package_root))
    assert payload["dirName"] == package_root.name
    assert payload["templates"], "a package with no templates adds nothing to the palette"


@pytest.mark.parametrize("package_root", PACKAGE_DIRS, ids=IDS)
def test_dir_name_matches_the_declared_id_and_major(package_root: Path):
    raw = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))
    expected = f"{raw['id']}@{raw['compatibility']['major']}"
    assert package_root.name == expected


@pytest.mark.parametrize("package_root", PACKAGE_DIRS, ids=IDS)
def test_declared_sources_and_behavior_bundle_exist(package_root: Path):
    """A template's ``source`` and the package's ``behaviorScript`` are paths.

    A missing bundle is the failure mode AUTHORING-NODES.md calls out: the node
    renders as an empty code editor with only a console warning.
    """
    raw = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))

    bundle = raw.get("behaviorScript")
    if bundle:
        assert (package_root / bundle).is_file(), f"missing behaviorScript {bundle}"

    for template in raw["templates"]:
        source = template.get("source")
        if source:
            assert (package_root / source).is_file(), (
                f"template {template['id']} declares a missing source {source}"
            )
