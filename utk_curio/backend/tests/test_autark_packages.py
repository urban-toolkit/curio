"""Curio takes Autark from npm.

autk-grammar, autk-compute, autk-db, autk-map and autk-plot come from the
registry, with autk-core, one copy of each, in the frontend's tree; the repo
root's tree, which the sandbox's Node and the Discovery Catalog's OpenStreetMap
downloads load autk-db from, takes autk-db and autk-core the same way. The
Autark packages, all but autk-grammar, which is released on its own, are one
release, 4.1.0 or later: from 4.1.0 on, autk-map draws a map on demand
(adapters/node/autkMapDrawing). Curio vendors no Autark package.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows"
REGISTRY = "https://registry.npmjs.org"

#: Each npm tree, and the Autark packages its package.json names.
TREES = {
    "frontend": (FRONTEND, ("autk-grammar", "autk-compute", "autk-db", "autk-map", "autk-plot")),
    "repo root": (REPO_ROOT, ("autk-db",)),
}

#: The package released apart from the others.
GRAMMAR = "autk-grammar"

#: The first Autark release whose maps draw on demand.
ON_DEMAND_RELEASE = (4, 1, 0)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _release(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("-")[0].split("."))


@pytest.mark.parametrize("tree", sorted(TREES))
def test_package_json_names_the_4x_release(tree):
    root, packages = TREES[tree]
    dependencies = _read(root / "package.json")["dependencies"]
    for name in packages:
        spec = dependencies.get(f"@urban-toolkit/{name}", "")
        assert re.fullmatch(r"[\^~]?4\.\d+\.\d+", spec), (
            f"the {tree} package.json takes @urban-toolkit/{name} as {spec!r}, not a 4.x release from npm"
        )


@pytest.mark.parametrize("tree", sorted(TREES))
def test_the_lockfile_takes_one_copy_of_each_from_the_registry(tree):
    root, packages = TREES[tree]
    entries = _read(root / "package-lock.json")["packages"]
    for name in (*packages, "autk-core"):
        top = f"node_modules/@urban-toolkit/{name}"
        copies = sorted(path for path in entries if path == top or path.endswith(f"/{top}"))
        assert copies == [top], f"the {tree} lockfile holds these copies of {name}: {copies}"
        entry = entries[top]
        version = entry.get("version", "")
        assert version.startswith("4."), f"the {tree} lockfile has {name} {version}"
        assert entry.get("resolved") == f"{REGISTRY}/@urban-toolkit/{name}/-/{name}-{version}.tgz", (
            f"the {tree} lockfile resolves {name} to {entry.get('resolved')!r}"
        )
        assert str(entry.get("integrity", "")).startswith("sha512-"), f"{name} has no integrity in the {tree} lockfile"


@pytest.mark.parametrize("tree", sorted(TREES))
def test_the_autark_packages_are_one_release_whose_maps_draw_on_demand(tree):
    root, packages = TREES[tree]
    entries = _read(root / "package-lock.json")["packages"]
    versions = {
        name: entries.get(f"node_modules/@urban-toolkit/{name}", {}).get("version", "")
        for name in (*packages, "autk-core")
        if name != GRAMMAR
    }
    assert len(set(versions.values())) == 1, f"the {tree} lockfile mixes Autark releases: {versions}"
    release = next(iter(versions.values()))
    assert _release(release) >= ON_DEMAND_RELEASE, (
        f"the {tree} lockfile takes Autark {release}, whose maps do not draw on demand: 4.1.0 is the first that does"
    )


def test_no_autark_package_is_vendored():
    assert not (FRONTEND / "vendor" / "autark").exists()
    for tree, (root, _packages) in TREES.items():
        manifest = _read(root / "package.json")
        local = [
            name for name, spec in manifest["dependencies"].items()
            if name.startswith("@urban-toolkit/") and spec.startswith("file:")
        ]
        assert local == [], f"the {tree} package.json installs {local} from files"
        overridden = [name for name in manifest.get("overrides", {}) if name.startswith("@urban-toolkit/")]
        assert overridden == [], f"the {tree} package.json overrides {overridden}"
