"""Curio takes Autark from npm, autk-map and autk-grammar aside.

autk-compute, autk-db and autk-plot come from the registry, with autk-core,
one copy of each, in the frontend's tree; the repo root's tree, which the
sandbox's Node and the Discovery Catalog's OpenStreetMap downloads load
autk-db from, takes autk-db and autk-core the same way. Two Autark packages
are vendored in the frontend's tree, one copy each, from tarballs in
``utk_curio/frontend/urban-workflows/vendor/autark/`` (its README says how
each was packed):

- autk-map 4.1.1-curio.4, packed from urban-toolkit/autark#118 (a raster
  colored with one color function), autark#120 (a destroyed map releases its
  shared SSAO textures), autark#121 (a legend's end labels inside its ramp)
  and autark#122 (numbers under a categorical color map drawn in their legend
  label's color) until Autark releases them, which autk-grammar's maps use
  too (an npm override);
- autk-grammar 4.5.0-curio.1, packed from urban-toolkit/autk-grammar#22 (a
  points layer's ``pointSize``, in meters on the ground) until autk-grammar
  releases it.

The Autark packages, all but autk-grammar, which is released on its own, are
one release, 4.1.0 or later: from 4.1.0 on, autk-map draws a map on demand
(adapters/node/autkMapDrawing). The vendored autk-map is release 4.1.1 with
those four changes. autk-grammar is 4.1.0 or later: from 4.1.0 on, it lists
the maps a run drew (`AutkGrammar.maps`), which is where Curio takes a node's
maps from (`grammarMaps`); and 4.5.0 or later, whose map layers take
``pointSize``. Nothing else is vendored.
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

#: Each npm tree, and the Autark packages its package.json names.
TREES = {
    "frontend": (FRONTEND, ("autk-grammar", "autk-compute", "autk-db", "autk-map", "autk-plot")),
    "repo root": (REPO_ROOT, ("autk-db",)),
}

#: The package released apart from the others.
GRAMMAR = "autk-grammar"

#: The first Autark release whose maps draw on demand.
ON_DEMAND_RELEASE = (4, 1, 0)

#: The first autk-grammar release that lists the maps a run drew.
GRAMMAR_MAPS_RELEASE = (4, 1, 0)

#: The first autk-grammar release whose map layers take ``pointSize``.
GRAMMAR_POINT_SIZE_RELEASE = (4, 5, 0)

#: The vendored Autark packages, in the frontend's tree: each one's tarball in
#: vendor/autark/, its version and its npm integrity.
VENDORED = {
    "autk-map": {
        "tarball": "urban-toolkit-autk-map-4.1.1-curio.4.tgz",
        "version": "4.1.1-curio.4",
        "integrity": "sha512-tzW/tZVMZ1ARnlj6C/DjmZejmdZ0Jg/maAu4nYB9XiPagTAwbtyR1viEDHY/H3ekfTsDISTeeGoVwBowgz/wkQ==",
    },
    "autk-grammar": {
        "tarball": "urban-toolkit-autk-grammar-4.5.0-curio.1.tgz",
        "version": "4.5.0-curio.1",
        "integrity": "sha512-Ig7qgplmqBBHp+lAiZDzJknD/BH0zrWvuRqu9ZSOtpNorBq8I9KvEDYJLu5MtZDhZH2fyUg5LhuNi4jVWGGfTg==",
    },
}

#: The vendored packages an npm override gives the packages that depend on
#: them: autk-grammar asks for autk-map ^4.1.1, which the prerelease does not
#: satisfy, so without the override it gets its own copy from npm. Nothing
#: depends on autk-grammar.
OVERRIDDEN = ("autk-map",)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _vendored(tree: str, name: str) -> dict | None:
    """The vendored package *name* of *tree*, or None when it comes from npm."""
    return VENDORED.get(name) if tree == "frontend" else None


def _spec(vendored: dict) -> str:
    return f"file:vendor/autark/{vendored['tarball']}"


def _release(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("-")[0].split("."))


@pytest.mark.parametrize("tree", sorted(TREES))
def test_package_json_names_the_4x_release(tree):
    root, packages = TREES[tree]
    dependencies = _read(root / "package.json")["dependencies"]
    for name in packages:
        spec = dependencies.get(f"@urban-toolkit/{name}", "")
        vendored = _vendored(tree, name)
        if vendored:
            assert spec == _spec(vendored), (
                f"the {tree} package.json takes @urban-toolkit/{name} as {spec!r}, not {_spec(vendored)!r}"
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
        vendored = _vendored(tree, name)
        if vendored:
            assert (version, entry.get("resolved"), entry.get("integrity")) == (
                vendored["version"], _spec(vendored), vendored["integrity"],
            ), f"the {tree} lockfile takes {name} as {version} from {entry.get('resolved')!r}"
            continue
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
    for name, version in list(versions.items()):
        vendored = _vendored(tree, name)
        if vendored:
            # A vendored package is its release with changes of its own.
            assert version == vendored["version"], (
                f"the {tree} lockfile has {name} {version}, not {vendored['version']}"
            )
            versions[name] = vendored["version"].split("-")[0]
    assert len(set(versions.values())) == 1, f"the {tree} lockfile mixes Autark releases: {versions}"
    release = next(iter(versions.values()))
    assert _release(release) >= ON_DEMAND_RELEASE, (
        f"the {tree} lockfile takes Autark {release}, whose maps do not draw on demand: 4.1.0 is the first that does"
    )


def test_the_grammar_lists_the_maps_a_run_drew():
    entries = _read(FRONTEND / "package-lock.json")["packages"]
    version = entries.get(f"node_modules/@urban-toolkit/{GRAMMAR}", {}).get("version", "")
    assert version, "the frontend lockfile has no autk-grammar"
    assert _release(version) >= GRAMMAR_MAPS_RELEASE, (
        f"the frontend lockfile takes autk-grammar {version}, which does not list the maps a run drew "
        f"(AutkGrammar.maps): 4.1.0 is the first that does"
    )


def test_the_grammars_map_layers_take_a_point_size():
    entries = _read(FRONTEND / "package-lock.json")["packages"]
    version = entries.get(f"node_modules/@urban-toolkit/{GRAMMAR}", {}).get("version", "")
    assert version, "the frontend lockfile has no autk-grammar"
    assert _release(version) >= GRAMMAR_POINT_SIZE_RELEASE, (
        f"the frontend lockfile takes autk-grammar {version}, whose map layers take no pointSize: "
        f"4.5.0 is the first whose do"
    )


def test_autk_map_and_autk_grammar_are_the_vendored_autark_packages():
    tarballs = sorted(vendored["tarball"] for vendored in VENDORED.values())
    assert sorted(path.name for path in VENDOR.iterdir()) == ["README.md", *tarballs]
    readme = (VENDOR / "README.md").read_text(encoding="utf-8")
    for tarball in tarballs:
        assert tarball in readme, f"vendor/autark/README.md does not say what {tarball} is"
    for tree, (root, _packages) in TREES.items():
        manifest = _read(root / "package.json")
        local = {
            name: spec for name, spec in manifest["dependencies"].items()
            if name.startswith("@urban-toolkit/") and spec.startswith("file:")
        }
        expected = (
            {f"@urban-toolkit/{name}": _spec(vendored) for name, vendored in VENDORED.items()}
            if tree == "frontend" else {}
        )
        assert local == expected, f"the {tree} package.json installs {local} from files"
        overridden = {
            name: spec for name, spec in manifest.get("overrides", {}).items() if name.startswith("@urban-toolkit/")
        }
        expected = (
            {f"@urban-toolkit/{name}": f"$@urban-toolkit/{name}" for name in OVERRIDDEN}
            if tree == "frontend" else {}
        )
        assert overridden == expected, f"the {tree} package.json overrides {overridden}"
