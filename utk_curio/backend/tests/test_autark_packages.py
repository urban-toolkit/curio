"""Curio takes Autark from npm, autk-db and autk-map aside.

autk-grammar, autk-compute and autk-plot come from the registry, with
autk-core, one copy of each, in the frontend's tree; the repo root's tree,
which the sandbox's Node and the Discovery Catalog's OpenStreetMap downloads
load autk-db from, takes autk-db, autk-core and autk-grammar, whose data entry
imports autk-db alone, the same way. Curio vendors two Autark packages, each
from its tarball in ``utk_curio/frontend/urban-workflows/vendor/autark/``
(whose README says how it was packed), until Autark releases their changes:

- autk-db 4.1.1-curio.2, packed from urban-toolkit/autark#132 (a heatmap's
  avg, sum, min and max cells hold their values, not zeros, a normalized band
  holds its rescaled values, and each band has a label of its own), one copy in each
  tree, which autk-grammar's data adapter uses too (an npm override in each);
- autk-map 4.1.1-curio.4, packed from urban-toolkit/autark#118 (a raster
  colored with one color function), autark#120 (a destroyed map releases its
  shared SSAO textures), autark#121 (a legend's end labels inside its ramp)
  and autark#122 (numbers under a categorical color map drawn in their legend
  label's color), one copy in the frontend's tree, which autk-grammar's maps
  use too (an npm override).

The Autark packages, all but autk-grammar, which is released on its own, are
one release, 4.1.0 or later: from 4.1.0 on, autk-map draws a map on demand
(adapters/node/autkMapDrawing). The vendored autk-db and autk-map are release
4.1.1 with those changes. autk-grammar is one exact release: 4.1.0 or later, which
lists the maps a run drew (`AutkGrammar.maps`), where Curio takes a node's
maps from (`grammarMaps`); 4.5.0 or later, whose map layers take
``pointSize``; 5.0.0 or later, whose keys Curio's documents and loaders
use (``wgslFunction``, a join's ``dataRef`` and ``joinDataRef``); 5.2.0
or later, in both trees, whose data adapter loads every source Curio's
loaders hand it and sets up a document's ``workspaces``, whose plots take the
keys of their colors, ticks, titles and selection, and whose compute reads a
pass's ``fromFeature`` table as the run's GeoJSON source gave it; 5.4.0
or later, in both trees, whose maps take the map keys of autk-map, whose
camera takes a center and a tour, and whose compute runs windows and
clusters passes; 5.5.1 or later, in both trees, whose passes keep their
results in autk-db (``writeBack``), whose sources run after compute
(``after``, its ``dataPhases``), whose heatmap without ``groupBy`` counts its
rows and whose heatmap entry without ``aggregateFn`` is refused; and 5.6.0 or
later, in both trees, whose batched passes pack every polygon of a building
part and read a road of several lines from its first point. Nothing else is
vendored.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows"
VENDOR = FRONTEND / "vendor" / "autark"
REGISTRY = "https://registry.npmjs.org"

#: Each npm tree, and the Autark packages its package.json names.
TREES = {
    "frontend": (FRONTEND, ("autk-grammar", "autk-compute", "autk-db", "autk-map", "autk-plot")),
    "repo root": (REPO_ROOT, ("autk-db", "autk-grammar")),
}

#: The package released apart from the others.
GRAMMAR = "autk-grammar"

#: The first Autark release whose maps draw on demand.
ON_DEMAND_RELEASE = (4, 1, 0)

#: The first autk-grammar release that lists the maps a run drew.
GRAMMAR_MAPS_RELEASE = (4, 1, 0)

#: The first autk-grammar release whose map layers take ``pointSize``.
GRAMMAR_POINT_SIZE_RELEASE = (4, 5, 0)

#: The first autk-grammar release with the keys Curio's documents and loaders
#: use: ``wgslFunction``, and a join's ``dataRef`` and ``joinDataRef``.
GRAMMAR_KEYS_RELEASE = (5, 0, 0)

#: The first autk-grammar release whose data adapter loads the sources Curio's
#: loaders hand it (``sql``, ``update``, ``drop``, ``tagSets``) and sets up a
#: document's ``workspaces``, whose plots take the keys Curio's documents write
#: (``colorMapInterpolator``, ``axisLabels``, ``selection``, ...), and whose
#: compute reads a ``fromFeature`` table as the run's GeoJSON source gave it,
#: which Curio's map nodes rely on.
GRAMMAR_SOURCES_AND_PLOTS_RELEASE = (5, 2, 0)

#: The first autk-grammar release whose maps take every key Curio's documents
#: and agents write of autk-map (``terrain``, ``pickedComps``, ``skippedComps``,
#: ``widthBy``, ``legend``, ``layerType``, ``showUi``, a style's colors, ...),
#: whose camera takes a ``center`` and a ``motion`` and exports the player Curio
#: plays a tour with (``playCameraMotion``), and whose compute runs ``windows``
#: and ``clusters`` passes.
GRAMMAR_MAPS_CAMERA_AND_COMPUTE_RELEASE = (5, 4, 0)

#: The first autk-grammar release whose passes keep their results in autk-db
#: (``writeBack``), whose sources run after compute (``after: 'compute'``) and
#: whose two entries export the split a node runs them by (``dataPhases``),
#: whose heatmap without ``groupBy`` counts its rows, whose heatmap entry without
#: ``aggregateFn`` is refused, and whose map that starts with a raster is placed
#: at the raster.
GRAMMAR_WRITE_BACK_RELEASE = (5, 5, 1)

#: The first autk-grammar release whose batched entries that read the geometry
#: pack each polygon of a MultiPolygon or a GeometryCollection as a feature of
#: its own, so a shadow pass's ``geometry.coordinates.0`` reads every polygon of
#: a building part, and which hands autk-compute a MultiLineString's lines as one
#: line, so a pass over roads reads each road's first points.
GRAMMAR_EVERY_POLYGON_RELEASE = (5, 6, 0)

#: The vendored Autark packages: each one's tarball in vendor/autark/, its
#: version and its npm integrity.
AUTK_DB = {
    "tarball": "urban-toolkit-autk-db-4.1.1-curio.2.tgz",
    "version": "4.1.1-curio.2",
    "integrity": "sha512-vYoV3Q0Juj7KxiCdLcqRJmxm8egmC8EELxcLg5Pz/sg4oONGiW6s9Egizuka0IwcCim9dhS55tdVGrNITxbwwg==",
}
AUTK_MAP = {
    "tarball": "urban-toolkit-autk-map-4.1.1-curio.4.tgz",
    "version": "4.1.1-curio.4",
    "integrity": "sha512-tzW/tZVMZ1ARnlj6C/DjmZejmdZ0Jg/maAu4nYB9XiPagTAwbtyR1viEDHY/H3ekfTsDISTeeGoVwBowgz/wkQ==",
}

#: Each tree's vendored packages: the one tarball in vendor/autark/ each
#: installs it from, named from the tree's package.json.
VENDORED = {
    "frontend": {"autk-db": AUTK_DB, "autk-map": AUTK_MAP},
    "repo root": {"autk-db": AUTK_DB},
}

#: Where each tree's package.json names vendor/autark/ from.
VENDOR_FROM = {
    "frontend": "vendor/autark",
    "repo root": "utk_curio/frontend/urban-workflows/vendor/autark",
}

#: The vendored packages an npm override gives the packages that depend on
#: them, in each tree: autk-grammar asks for autk-db ^4.1.1 and autk-map
#: ^4.1.1, which the prereleases do not satisfy, so without the override it
#: gets its own copy of each from npm. Nothing depends on autk-grammar.
OVERRIDDEN = {
    "frontend": ("autk-db", "autk-map"),
    "repo root": ("autk-db",),
}

#: The dependencies of autk-db 4.1.1 on npm, which the vendored autk-db keeps.
AUTK_DB_DEPENDENCIES = {
    "@duckdb/duckdb-wasm": "^1.33.1-dev57.0",
    "@osmix/pbf": "^0.0.10",
    "@turf/turf": "^7.4.0",
    "@types/emscripten": "^1.41.6",
    "@urban-toolkit/autk-core": "4.1.1",
    "apache-arrow": "^21.2.0",
    "geotiff": "^3.0.5",
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _vendored(tree: str, name: str) -> dict | None:
    """The vendored package *name* of *tree*, or None when it comes from npm."""
    return VENDORED[tree].get(name)


def _spec(tree: str, vendored: dict) -> str:
    return f"file:{VENDOR_FROM[tree]}/{vendored['tarball']}"


def _manifest_in(tarball: Path) -> dict:
    """The package.json an npm tarball holds."""
    with tarfile.open(tarball) as archive:
        return json.load(archive.extractfile("package/package.json"))


def _release(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("-")[0].split("."))


@pytest.mark.parametrize("tree", sorted(TREES))
def test_package_json_names_each_release(tree):
    root, packages = TREES[tree]
    dependencies = _read(root / "package.json")["dependencies"]
    for name in packages:
        spec = dependencies.get(f"@urban-toolkit/{name}", "")
        vendored = _vendored(tree, name)
        if vendored:
            assert spec == _spec(tree, vendored), (
                f"the {tree} package.json takes @urban-toolkit/{name} as {spec!r}, not {_spec(tree, vendored)!r}"
            )
            continue
        if name == GRAMMAR:
            # Released apart from the others: one exact release, with the keys Curio writes.
            assert re.fullmatch(r"\d+\.\d+\.\d+", spec) and _release(spec) >= GRAMMAR_KEYS_RELEASE, (
                f"the {tree} package.json takes @urban-toolkit/{name} as {spec!r}, "
                f"not one release from npm, 5.0.0 or later"
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
                vendored["version"], _spec(tree, vendored), vendored["integrity"],
            ), f"the {tree} lockfile takes {name} as {version} from {entry.get('resolved')!r}"
            continue
        if name == GRAMMAR:
            assert re.fullmatch(r"\d+\.\d+\.\d+", version) and _release(version) >= GRAMMAR_KEYS_RELEASE, (
                f"the {tree} lockfile has {name} {version}, not one release, 5.0.0 or later"
            )
        else:
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


def test_the_grammar_takes_the_keys_curio_writes():
    entries = _read(FRONTEND / "package-lock.json")["packages"]
    version = entries.get(f"node_modules/@urban-toolkit/{GRAMMAR}", {}).get("version", "")
    assert version, "the frontend lockfile has no autk-grammar"
    assert _release(version) >= GRAMMAR_KEYS_RELEASE, (
        f"the frontend lockfile takes autk-grammar {version}, which does not read the keys Curio's documents "
        f"use (wgslFunction, a join's dataRef and joinDataRef): 5.0.0 is the first that does"
    )


@pytest.mark.parametrize("tree", sorted(TREES))
def test_the_grammar_loads_the_sources_and_draws_the_plot_keys_curio_uses(tree):
    """Both trees take autk-grammar 5.2.0 or later: the frontend's loader and
    plots, and the sandbox's loader of a run on the server, which imports its
    data entry."""
    root, _packages = TREES[tree]
    spec = _read(root / "package.json")["dependencies"].get(f"@urban-toolkit/{GRAMMAR}", "")
    version = _read(root / "package-lock.json")["packages"].get(f"node_modules/@urban-toolkit/{GRAMMAR}", {}).get("version", "")
    for what, held in (("package.json", spec), ("lockfile", version)):
        assert re.fullmatch(r"\d+\.\d+\.\d+", held) and _release(held) >= GRAMMAR_SOURCES_AND_PLOTS_RELEASE, (
            f"the {tree} {what} takes autk-grammar {held!r}, which does not load sql, update and drop sources or "
            f"workspaces, draw a plot's colors, ticks, titles and selection, or read a pass's fromFeature table as "
            f"its source gave it: 5.2.0 is the first that does"
        )
    assert spec == version, f"the {tree} package.json takes autk-grammar {spec}, its lockfile {version}"


@pytest.mark.parametrize("tree", sorted(TREES))
def test_the_grammar_draws_the_map_keys_and_runs_the_camera_and_compute_keys_curio_uses(tree):
    """Both trees take autk-grammar 5.4.0 or later: its map, camera and compute
    keys, which a node's run draws and its agents write, and the sandbox's
    loader, which imports its data entry, of the same release."""
    root, _packages = TREES[tree]
    spec = _read(root / "package.json")["dependencies"].get(f"@urban-toolkit/{GRAMMAR}", "")
    version = _read(root / "package-lock.json")["packages"].get(f"node_modules/@urban-toolkit/{GRAMMAR}", {}).get("version", "")
    for what, held in (("package.json", spec), ("lockfile", version)):
        assert re.fullmatch(r"\d+\.\d+\.\d+", held) and _release(held) >= GRAMMAR_MAPS_CAMERA_AND_COMPUTE_RELEASE, (
            f"the {tree} {what} takes autk-grammar {held!r}, which does not draw a map's terrain, its picked and hidden "
            f"features, its line widths, legend, layer types, colors and controls, play a camera's center and tour, "
            f"or run windows and clusters passes: 5.4.0 is the first that does"
        )
    assert spec == version, f"the {tree} package.json takes autk-grammar {spec}, its lockfile {version}"


@pytest.mark.parametrize("tree", sorted(TREES))
def test_the_grammar_keeps_pass_results_and_runs_sources_after_compute(tree):
    """Both trees take autk-grammar 5.5.1 or later: a node's run keeps a pass's
    result in autk-db and runs its sources after compute, and both loaders, the
    sandbox's of the same release, load a section's sources after compute after
    the others, through its ``dataPhases``."""
    root, _packages = TREES[tree]
    spec = _read(root / "package.json")["dependencies"].get(f"@urban-toolkit/{GRAMMAR}", "")
    version = _read(root / "package-lock.json")["packages"].get(f"node_modules/@urban-toolkit/{GRAMMAR}", {}).get("version", "")
    for what, held in (("package.json", spec), ("lockfile", version)):
        assert re.fullmatch(r"\d+\.\d+\.\d+", held) and _release(held) >= GRAMMAR_WRITE_BACK_RELEASE, (
            f"the {tree} {what} takes autk-grammar {held!r}, which does not keep a pass's result in autk-db "
            f"(writeBack), run a source after compute (after, dataPhases), count a heatmap's rows without groupBy "
            f"or refuse a heatmap entry without aggregateFn: 5.5.1 is the first that does"
        )
    assert spec == version, f"the {tree} package.json takes autk-grammar {spec}, its lockfile {version}"


@pytest.mark.parametrize("tree", sorted(TREES))
def test_the_grammar_packs_every_polygon_of_a_building_part_and_reads_a_road_of_several_lines(tree):
    """Both trees take autk-grammar 5.6.0 or later: the shadow passes of
    examples 06, 07 and 38 read every polygon of a building part OpenStreetMap
    maps as one element of several polygons, and every road of several lines
    from its first point."""
    root, _packages = TREES[tree]
    spec = _read(root / "package.json")["dependencies"].get(f"@urban-toolkit/{GRAMMAR}", "")
    version = _read(root / "package-lock.json")["packages"].get(f"node_modules/@urban-toolkit/{GRAMMAR}", {}).get("version", "")
    for what, held in (("package.json", spec), ("lockfile", version)):
        assert re.fullmatch(r"\d+\.\d+\.\d+", held) and _release(held) >= GRAMMAR_EVERY_POLYGON_RELEASE, (
            f"the {tree} {what} takes autk-grammar {held!r}, whose batched passes pack a building part of several "
            f"polygons as a box of zeros and a road of several lines as zeros: 5.6.0 is the first that packs every "
            f"polygon and each road's first points"
        )
    assert spec == version, f"the {tree} package.json takes autk-grammar {spec}, its lockfile {version}"


def test_vendor_autark_holds_the_vendored_packages_each_tree_installs_and_overrides():
    tarballs = sorted({vendored["tarball"] for packages in VENDORED.values() for vendored in packages.values()})
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
        expected = {f"@urban-toolkit/{name}": _spec(tree, vendored) for name, vendored in VENDORED[tree].items()}
        assert local == expected, f"the {tree} package.json installs {local} from files"
        overridden = {
            name: spec for name, spec in manifest.get("overrides", {}).items() if name.startswith("@urban-toolkit/")
        }
        expected = {f"@urban-toolkit/{name}": f"$@urban-toolkit/{name}" for name in OVERRIDDEN[tree]}
        assert overridden == expected, f"the {tree} package.json overrides {overridden}"


@pytest.mark.parametrize("name", sorted({name for packages in VENDORED.values() for name in packages}))
def test_each_vendored_tarball_is_the_package_and_integrity_the_lockfiles_name(name):
    """The tarball in vendor/autark/ is, byte for byte, the one each lockfile
    that takes it names: npm ci refuses any other."""
    (vendored,) = {json.dumps(packages[name], sort_keys=True) for packages in VENDORED.values() if name in packages}
    vendored = json.loads(vendored)
    tarball = VENDOR / vendored["tarball"]
    digest = "sha512-" + base64.b64encode(hashlib.sha512(tarball.read_bytes()).digest()).decode("ascii")
    assert digest == vendored["integrity"], f"{tarball.name} is {digest}, not {vendored['integrity']}"
    manifest = _manifest_in(tarball)
    assert (manifest["name"], manifest["version"]) == (f"@urban-toolkit/{name}", vendored["version"])


def test_the_vendored_autk_db_keeps_the_dependencies_of_autk_db_4_1_1():
    """autk-db 4.1.1-curio.2 is release 4.1.1 with three changes of its code, so
    it depends on what 4.1.1 depends on, and each tree's lockfile installs
    those."""
    assert _manifest_in(VENDOR / AUTK_DB["tarball"])["dependencies"] == AUTK_DB_DEPENDENCIES
    for tree, (root, _packages) in TREES.items():
        entry = _read(root / "package-lock.json")["packages"]["node_modules/@urban-toolkit/autk-db"]
        assert entry.get("dependencies") == AUTK_DB_DEPENDENCIES, f"the {tree} lockfile's autk-db depends on {entry}"
