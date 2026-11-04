"""``curio.rasterization@1``: Rasterization, SCOUT's raster nodes in Curio.

SCOUT Rasters (``scout.rasters@1``) and SCOUT Comparison
(``scout.comparison@1``) became one package, Scout, on the owner's call
(2026-10-20), and Scout two packages by what their nodes do (2026-11-04):
Rasterization, the Raster Calculator and Rasterize Buildings, with the SCOUT
tag, and the Vega-Lite package (``curio.vega-lite@1``,
``test_vega_lite_package.py``), the fifteen charts. Each id they replaced is
retired with no alias (a clean install), so no file Curio ships names one, as
a package or in a node type, and no file in the repository names Scout's.

The guides (``docs/*.md``) are not in the CI image this suite runs in;
``packagesInGuides.test.ts`` reads them.

Every file is read inside its test, so a checkout without the package fails
test by test rather than at collection.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PACKAGE_ID = "curio.rasterization"
PACKAGE = REPO / "packages" / f"{PACKAGE_ID}@1"

#: The two packages Scout replaced, retired with no alias.
RETIRED = ("scout.rasters", "scout.comparison")
#: Either retired id as a whole id: a package (``scout.rasters@1``,
#: ``packages/scout.comparison@1/``) or the package of a node type
#: (``scout.comparison/donuts``). The Python module ``scout_rasters`` keeps its
#: name, and its underscore is not a dot.
RETIRED_ID = re.compile(r"(?<![\w.-])scout\.(?:rasters|comparison)(?![\w-])")
#: Scout's id, which Rasterization and the Vega-Lite package replaced, as a
#: whole id: its package (``@1``) or the package of a node type. Written so
#: that this file names it in no text this module reads.
SCOUT_ID = re.compile(r"(?<![\w.-])curio\.scout(?![\w-])")

#: Its templates, in the palette's order.
TEMPLATES = ["raster-calculator", "rasterize-buildings"]

#: What Curio ships beside its code (``utk_curio/shipped.py``), and the code
#: with the agents' prompts, from the repository's root.
SHIPPED = (
    "packages", "agents", "skills", "datasets", "discovery", "docs/examples", "docs/schemas",
    "docs/bring-your-own-model", "scripts", "utk_curio",
)
#: Folders under those that hold no shipped text: the test suites, which name
#: the retired ids to look for them, built and installed files, caches, a pip
#: build's copy of the catalogs, and the data and weights the catalogs carry.
SKIPPED_DIRS = {
    "utk_curio/backend/tests",
    "utk_curio/sandbox/tests",
    "utk_curio/frontend/urban-workflows/src/tests",
    "utk_curio/frontend/urban-workflows/vendor",
    "utk_curio/_shipped",
    "docs/examples/dataflows/expected_outputs",
}
#: The test suites, which name Scout's id nowhere either, and the files at
#: the repository's root that build and start Curio.
TESTS = ("utk_curio/backend/tests", "utk_curio/sandbox/tests", "utk_curio/frontend/urban-workflows/src/tests")
ROOT_FILES = ("setup.py", "MANIFEST.in", "pyproject.toml", "curio.py", "package.json")
SKIPPED_DIR_NAMES = {"node_modules", "dist", "__pycache__"}
#: A dataset's ``data/`` and a model package's ``models/``: files, not text.
CARRIED = {("datasets", "data"), ("packages", "models")}
#: The kinds of text file Curio ships.
TEXT = {".py", ".json", ".md", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".txt", ".sh",
        ".yml", ".yaml", ".html", ".css", ".toml", ".cfg", ".in", ".csv"}


def _manifest() -> dict:
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def _skipped(relative: str, skipped_dirs: set[str]) -> bool:
    parts = relative.split("/")
    return (
        relative in skipped_dirs
        or parts[-1] in SKIPPED_DIR_NAMES
        or parts[-1].startswith(".")
        or (len(parts) == 3 and (parts[0], parts[2]) in CARRIED)
    )


def _area(relative: str) -> str:
    """``docs/examples`` for a file under it, else the top folder."""
    parts = relative.split("/")
    return "/".join(parts[:2]) if parts[0] == "docs" else parts[0]


def _text_under(tops, skipped_dirs: set[str]):
    """``(path from the root, text)`` of each text file under *tops*, leaving
    out the folders *skipped_dirs* names."""
    for top in tops:
        for dirpath, dirnames, filenames in os.walk(REPO / top):
            here = Path(dirpath)
            dirnames[:] = sorted(
                d for d in dirnames if not _skipped((here / d).relative_to(REPO).as_posix(), skipped_dirs)
            )
            for filename in sorted(filenames):
                path = here / filename
                if path.suffix in TEXT and not filename.endswith(".geojson"):
                    yield path.relative_to(REPO).as_posix(), path.read_text(encoding="utf-8", errors="replace")


def _shipped_text():
    """``(path from the root, text)`` of each text file Curio ships."""
    yield from _text_under(SHIPPED, SKIPPED_DIRS)


def _named(pattern: re.Pattern, texts) -> tuple[list[str], Counter]:
    named, read = [], Counter()
    for relative, text in texts:
        read[_area(relative)] += 1
        for match in pattern.finditer(text):
            named.append(f"{relative}:{text.count(chr(10), 0, match.start()) + 1}: {match.group()}")
    return named, read


def test_rasterization_is_one_package_from_curio_under_mit():
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    manifest = load_package_manifest(PACKAGE)
    assert (manifest.package_id, manifest.major, manifest.name, manifest.publisher, manifest.license) == (
        PACKAGE_ID, 1, "Rasterization", "Curio", "MIT",
    )
    assert manifest.read_only is True and manifest.kind == "node"
    assert _manifest()["version"] == "1.0.0"


def test_it_holds_the_two_raster_nodes_only():
    """The Raster Calculator, then Rasterize Buildings, each in its place in the
    package's palette group, with the raster module they import. A chart that
    compares scenarios is a node of the Vega-Lite package, not of this one."""
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    templates = _manifest()["templates"]
    assert [t["id"] for t in templates] == TEMPLATES
    assert [t["paletteOrder"] for t in templates] == list(range(len(TEMPLATES)))
    assert [t.template_id for t in load_package_manifest(PACKAGE).templates] == TEMPLATES
    assert not [t["id"] for t in templates if t.get("grammarId")]
    assert not list(PACKAGE.rglob("*.vl.json"))
    assert (PACKAGE / "sources" / "scout_rasters" / "raster_algebra.py").is_file()


def test_it_carries_the_scout_tag_and_its_raster_nodes_rasters():
    """SCOUT's raster nodes tag a dataflow SCOUT, from this package's
    manifest; the Vega-Lite package's charts tag it nothing."""
    manifest = _manifest()
    assert manifest["dataflowCategories"] == {"tags": ["SCOUT"]}
    assert {t["id"]: t["dataflowCategories"] for t in manifest["templates"]} == {
        template: {"dataTypes": ["Rasters"]} for template in TEMPLATES
    }


def test_deep_umbra_depends_on_it_and_finds_it_in_the_catalog():
    """Deep Umbra's node imports ``scout_rasters.web_tiles``, so its package
    names Rasterization in ``dependencies.packages``, and the catalog holds
    the package by that name."""
    umbra = json.loads((REPO / "packages" / "model.scout.deep-umbra@1" / "manifest.json").read_text(encoding="utf-8"))
    assert umbra["dependencies"]["packages"] == {f"{PACKAGE_ID}@1": "*"}
    assert _manifest()["id"] == PACKAGE_ID and _manifest()["compatibility"]["major"] == 1
    imports = (REPO / "packages" / "model.scout.deep-umbra@1" / "sources" / "deep_umbra" / "node_outputs.py")
    assert "from scout_rasters.web_tiles import tile_bounds" in imports.read_text(encoding="utf-8")


def test_a_shipped_dataflow_lists_rasterization_only_when_it_holds_one_of_its_nodes():
    """Example 06 and the charts dataflow hold no raster node, so neither lists
    Rasterization; the dataflows with a Raster Calculator or Rasterize
    Buildings do."""
    listed, holding = set(), set()
    for path in sorted((REPO / "docs" / "examples").rglob("*.json")):
        if any(part in path.parts for part in ("prompts", "expected_outputs")):
            continue
        spec = json.loads(path.read_text(encoding="utf-8"))
        dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
        if not isinstance(dataflow, dict):
            continue
        relative = path.relative_to(REPO).as_posix()
        if f"{PACKAGE_ID}@1" in (dataflow.get("packages") or []):
            listed.add(relative)
        if any(str(node.get("type", "")).startswith(f"{PACKAGE_ID}/") for node in dataflow.get("nodes") or []):
            holding.add(relative)
    assert listed == holding
    assert "docs/examples/24-scout-shadow-model-chicago-loop.json" in holding
    assert "docs/examples/06-back-bay-road-sunlight.json" not in listed
    assert "docs/examples/dataflows/scenario-comparison-charts.json" not in listed


def test_the_packages_it_replaced_are_gone():
    folders = sorted(
        p.name for p in (REPO / "packages").iterdir() if p.name.split("@")[0] in (*RETIRED, "curio" + ".scout")
    )
    assert folders == []
    ids = {
        json.loads(path.read_text(encoding="utf-8"))["id"]
        for path in (REPO / "packages").glob("*/manifest.json")
    }
    assert {PACKAGE_ID, "curio.vega-lite"} <= ids
    assert not ids & {*RETIRED, "curio" + ".scout"}, sorted(ids & {*RETIRED, "curio" + ".scout"})


def test_no_shipped_file_names_a_retired_package_or_its_node_types():
    """Not a dataflow's node or lockfile, a prompt fixture, a manifest, a
    package's README or code, a script, nor the app or the agents' prompts."""
    named, read = _named(RETIRED_ID, _shipped_text())
    # The walk reads every place it names: not a pass on an empty tree.
    least = {"packages": 20, "agents": 5, "datasets": 10, "docs/examples": 50, "scripts": 10, "utk_curio": 1000}
    assert {top: read[top] for top in least if read[top] < least[top]} == {}, read
    assert not named, "\n".join(named)


def test_no_file_names_scouts_package_or_its_node_types():
    """Not a file Curio ships, its tests, nor the files at the root that build
    and start it: no dataflow, fixture, manifest, skill or eval, agent text,
    script, code or test names the package Rasterization and the Vega-Lite
    package replaced, so nothing maps its node types to theirs on load either.
    The guides and the workflows are checked by
    ``packagesInGuides.test.ts``, on a checkout that holds them."""
    texts = [
        *_text_under(SHIPPED, SKIPPED_DIRS - set(TESTS)),
        *((name, (REPO / name).read_text(encoding="utf-8")) for name in ROOT_FILES if (REPO / name).is_file()),
    ]
    named, read = _named(SCOUT_ID, texts)
    # The walk reads every place it names, the test suites among them.
    least = {"packages": 20, "agents": 5, "skills": 10, "docs/examples": 50, "scripts": 10, "utk_curio": 2500}
    assert {top: read[top] for top in least if read[top] < least[top]} == {}, read
    assert read["setup.py"] == 1, read
    assert not named, "\n".join(named)
