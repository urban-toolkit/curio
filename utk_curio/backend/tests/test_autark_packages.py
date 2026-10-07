"""Curio takes Autark from npm.

autk-compute, autk-db, autk-map and autk-plot come from the registry at their
4.x release, with autk-core, one copy of each, in the frontend's tree and in
the repo root's, which the sandbox's Node and the Discovery Catalog's
OpenStreetMap downloads load autk-db from. autk-grammar is the one Autark
package Curio still installs from a tarball of its own
(``utk_curio/frontend/urban-workflows/vendor/autark/``), and its Autark
dependencies resolve to those same copies.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows"
VENDOR = FRONTEND / "vendor" / "autark"
REGISTRY = "https://registry.npmjs.org"
FROM_NPM = ("autk-compute", "autk-db", "autk-map", "autk-plot")

#: Each npm tree, and the Autark packages its package.json names.
TREES = {
    "frontend": (FRONTEND, FROM_NPM),
    "repo root": (REPO_ROOT, ("autk-db",)),
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def test_only_the_grammar_is_vendored():
    tarballs = sorted(path.name for path in VENDOR.glob("*.tgz")) if VENDOR.is_dir() else []
    assert [name for name in tarballs if not name.startswith("urban-toolkit-autk-grammar-")] == []
