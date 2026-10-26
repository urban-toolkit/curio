"""``curio.scout@1``: Scout, SCOUT's one node package in Curio (the plan
answering komar41's review of his #914, step 10).

SCOUT Rasters (``scout.rasters@1``) and SCOUT Comparison
(``scout.comparison@1``) became one package, Scout, on the owner's call
(2026-10-20): the Raster Calculator and Rasterize Buildings, then the charts,
in one manifest published by Curio under MIT. The two old ids are retired
with no alias (a clean install), so no file Curio ships names either of them,
as a package or in a node type. The seven charts of SCOUT Comparison became
fifteen when Compare Scenarios' presets and Dots with a range joined them
(the plan answering komar41's review, step 6.2).

The guides (``docs/*.md``) are not in the CI image this suite runs in;
``scoutPackageInGuides.test.ts`` reads them.

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
PACKAGE_ID = "curio.scout"
PACKAGE = REPO / "packages" / f"{PACKAGE_ID}@1"

#: The two packages Scout replaced, retired with no alias.
RETIRED = ("scout.rasters", "scout.comparison")
#: Either retired id as a whole id: a package (``scout.rasters@1``,
#: ``packages/scout.comparison@1/``) or the package of a node type
#: (``scout.comparison/donuts``). The Python module ``scout_rasters`` keeps its
#: name, and its underscore is not a dot.
RETIRED_ID = re.compile(r"(?<![\w.-])scout\.(?:rasters|comparison)(?![\w-])")

#: Scout's templates, in the palette's order: the two raster nodes, then the
#: fifteen charts.
TEMPLATES = [
    "raster-calculator",
    "rasterize-buildings",
    "lines-with-band",
    "curves-by-group",
    "bars-with-error-bars",
    "ensemble-strips",
    "stacked-bars-with-totals",
    "donuts",
    "weighted-matrix",
    "dots-with-a-range",
    "bars",
    "grouped-bars",
    "lines",
    "points",
    "pie",
    "lollipops",
    "table",
]

#: What Curio ships beside its code (``utk_curio/shipped.py``), and the code
#: with the agents' prompts, from the repository's root.
SHIPPED = (
    "packages", "agents", "datasets", "discovery", "docs/examples", "docs/schemas",
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
SKIPPED_DIR_NAMES = {"node_modules", "dist", "__pycache__"}
#: A dataset's ``data/`` and a model package's ``models/``: files, not text.
CARRIED = {("datasets", "data"), ("packages", "models")}
#: The kinds of text file Curio ships.
TEXT = {".py", ".json", ".md", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".txt", ".sh",
        ".yml", ".yaml", ".html", ".css", ".toml", ".cfg", ".in", ".csv"}


def _manifest() -> dict:
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def _skipped(relative: str) -> bool:
    parts = relative.split("/")
    return (
        relative in SKIPPED_DIRS
        or parts[-1] in SKIPPED_DIR_NAMES
        or parts[-1].startswith(".")
        or (len(parts) == 3 and (parts[0], parts[2]) in CARRIED)
    )


def _area(relative: str) -> str:
    """``docs/examples`` for a file under it, else the top folder."""
    parts = relative.split("/")
    return "/".join(parts[:2]) if parts[0] == "docs" else parts[0]


def _shipped_text():
    """``(path from the root, text)`` of each text file Curio ships."""
    for top in SHIPPED:
        for dirpath, dirnames, filenames in os.walk(REPO / top):
            here = Path(dirpath)
            dirnames[:] = sorted(d for d in dirnames if not _skipped((here / d).relative_to(REPO).as_posix()))
            for filename in sorted(filenames):
                path = here / filename
                if path.suffix in TEXT and not filename.endswith(".geojson"):
                    yield path.relative_to(REPO).as_posix(), path.read_text(encoding="utf-8", errors="replace")


def test_scout_is_one_package_from_curio_under_mit():
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    manifest = load_package_manifest(PACKAGE)
    assert (manifest.package_id, manifest.major, manifest.name, manifest.publisher, manifest.license) == (
        PACKAGE_ID, 1, "Scout", "Curio", "MIT",
    )
    assert manifest.read_only is True and manifest.kind == "node"
    assert _manifest()["version"] == "1.1.0"


def test_it_holds_the_templates_of_the_two_packages_it_replaced_and_eight_more_charts():
    """Both raster nodes, then the seven charts, then Dots with a range and
    Compare Scenarios' seven presets, each in its place in the package's
    palette group."""
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    templates = _manifest()["templates"]
    assert [t["id"] for t in templates] == TEMPLATES
    assert [t["paletteOrder"] for t in templates] == list(range(len(TEMPLATES)))
    assert [t.template_id for t in load_package_manifest(PACKAGE).templates] == TEMPLATES


def test_the_two_packages_it_replaced_are_gone():
    folders = sorted(p.name for p in (REPO / "packages").iterdir() if p.name.split("@")[0] in RETIRED)
    assert folders == []
    ids = {
        json.loads(path.read_text(encoding="utf-8"))["id"]
        for path in (REPO / "packages").glob("*/manifest.json")
    }
    assert PACKAGE_ID in ids
    assert not ids & set(RETIRED), sorted(ids & set(RETIRED))


def test_no_shipped_file_names_a_retired_package_or_its_node_types():
    """Not a dataflow's node or lockfile, a prompt fixture, a manifest, a
    package's README or code, a script, nor the app or the agents' prompts."""
    named, read = [], Counter()
    for relative, text in _shipped_text():
        read[_area(relative)] += 1
        for match in RETIRED_ID.finditer(text):
            named.append(f"{relative}:{text.count(chr(10), 0, match.start()) + 1}: {match.group()}")
    # The walk reads every place it names: not a pass on an empty tree.
    least = {"packages": 20, "agents": 5, "datasets": 10, "docs/examples": 50, "scripts": 10, "utk_curio": 1000}
    assert {top: read[top] for top in least if read[top] < least[top]} == {}, read
    assert not named, "\n".join(named)
