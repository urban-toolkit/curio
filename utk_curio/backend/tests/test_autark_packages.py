"""Curio takes Autark from npm, autk-map aside.

autk-grammar, autk-compute, autk-db and autk-plot come from the registry at
their 4.x release, with autk-core, one copy of each, in the frontend's tree;
the repo root's tree, which the sandbox's Node and the Discovery Catalog's
OpenStreetMap downloads load autk-db from, takes autk-db and autk-core the same
way. autk-map is the one Autark package Curio vendors: 4.0.0-curio.1, packed
from urban-toolkit/autark#115 (on-demand rendering) until Autark releases it,
one copy in the frontend's tree, which autk-grammar's maps use too (an npm
override). Nothing else is vendored.
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

#: The one vendored Autark package, in the frontend's tree: its tarball in
#: vendor/autark/, its version and its npm integrity.
VENDORED_NAME = "autk-map"
VENDORED_TARBALL = "urban-toolkit-autk-map-4.0.0-curio.1.tgz"
VENDORED_VERSION = "4.0.0-curio.1"
VENDORED_INTEGRITY = (
    "sha512-kqvk0DJpRQ++ZkoBQVE9bxkJmb+7lY+UZVibzzFbhCifh3qu3pKD7y1ps6Y8pCG+BrSMZC0R8KOMzPC2AONWhQ=="
)
VENDORED_SPEC = f"file:vendor/autark/{VENDORED_TARBALL}"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _vendored(tree: str, name: str) -> bool:
    return tree == "frontend" and name == VENDORED_NAME


@pytest.mark.parametrize("tree", sorted(TREES))
def test_package_json_names_the_4x_release(tree):
    root, packages = TREES[tree]
    dependencies = _read(root / "package.json")["dependencies"]
    for name in packages:
        spec = dependencies.get(f"@urban-toolkit/{name}", "")
        if _vendored(tree, name):
            assert spec == VENDORED_SPEC, (
                f"the {tree} package.json takes @urban-toolkit/{name} as {spec!r}, not {VENDORED_SPEC!r}"
            )
            continue
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
        if _vendored(tree, name):
            assert (version, entry.get("resolved"), entry.get("integrity")) == (
                VENDORED_VERSION, VENDORED_SPEC, VENDORED_INTEGRITY,
            ), f"the {tree} lockfile takes {name} as {version} from {entry.get('resolved')!r}"
            continue
        assert version.startswith("4."), f"the {tree} lockfile has {name} {version}"
        assert entry.get("resolved") == f"{REGISTRY}/@urban-toolkit/{name}/-/{name}-{version}.tgz", (
            f"the {tree} lockfile resolves {name} to {entry.get('resolved')!r}"
        )
        assert str(entry.get("integrity", "")).startswith("sha512-"), f"{name} has no integrity in the {tree} lockfile"


def test_autk_map_is_the_one_vendored_autark_package():
    vendor = FRONTEND / "vendor" / "autark"
    assert sorted(path.name for path in vendor.iterdir()) == ["README.md", VENDORED_TARBALL]
    assert VENDORED_TARBALL in (vendor / "README.md").read_text(encoding="utf-8")
    for tree, (root, _packages) in TREES.items():
        manifest = _read(root / "package.json")
        local = {
            name: spec for name, spec in manifest["dependencies"].items()
            if name.startswith("@urban-toolkit/") and spec.startswith("file:")
        }
        expected = {f"@urban-toolkit/{VENDORED_NAME}": VENDORED_SPEC} if tree == "frontend" else {}
        assert local == expected, f"the {tree} package.json installs {local} from files"
    # autk-grammar asks for autk-map ^4.0.0, which the prerelease does not
    # satisfy: without the override it gets its own copy from npm.
    overrides = _read(FRONTEND / "package.json").get("overrides", {})
    assert overrides.get(f"@urban-toolkit/{VENDORED_NAME}") == f"$@urban-toolkit/{VENDORED_NAME}", overrides
