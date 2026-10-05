"""``scout.raster-conversion@1``: SCOUT's building rasterizer in Curio (#662, step 17).

The proof: the package's port of SCOUT's ``convert_raster``, called as SCOUT's
high-rise shadow example calls it, turns the buildings SCOUT committed for that
example into the four zoom-16 height tiles SCOUT committed for them, each
within one gray level. Both are SCOUT's own files, copied unchanged into
``fixtures/scout/`` (see its ``ATTRIBUTION.md``).

The node: its template, with the widgets its manifest declares, resolved the
way a run resolves a node's widgets, runs in the sandbox with its package's
modules (#719). It returns ``(mosaic, tiles)``: the tiles are SCOUT's, the
mosaic is one raster the Autark node's raster path (#718) loads, and each
widget reaches the call.

Package code is imported inside each test, through a run's staged copy of the
package's modules, so a checkout without the package or its libraries fails
each test on its own and no bytecode lands in ``packages/``.
"""
from __future__ import annotations

import contextlib
import importlib
import json
import re
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "scout.raster-conversion@1"
SOURCES = PACKAGE / "sources"
MODULE = "scout_raster_conversion"
NODE_TYPE = "scout.raster-conversion/rasterize-buildings"
DATAFLOW = REPO / "docs" / "examples" / "dataflows" / "BuildingRasters.json"

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scout"
BUILDINGS = FIXTURES / "A_buildings.geojson"
SCOUT_TILES = FIXTURES / "A_rasters"
TILE_NAMES = [
    "16_16814_24355.png",
    "16_16814_24356.png",
    "16_16815_24355.png",
    "16_16815_24356.png",
]
#: What #718's Autark raster path loads at its own size (utils/raster/rasterLoad.ts).
AUTARK_MAX_CELLS = 2048 * 2048
AUTARK_MAX_SIDE = 8192


def _template() -> dict:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    (template,) = manifest["templates"]
    return template


def _gray(path_or_png):
    """A tile's gray levels as ints, from its file or its ``png`` value; the
    format Deep Umbra decodes: one 8-bit channel, 256 by 256."""
    import base64
    import io

    import numpy as np
    from PIL import Image

    source = path_or_png if isinstance(path_or_png, Path) else io.BytesIO(base64.b64decode(path_or_png))
    with Image.open(source) as image:
        assert image.format == "PNG" and image.mode == "L" and image.size == (256, 256), (
            image.format, image.mode, image.size,
        )
        return np.asarray(image).astype(int)


def _worst(ours, theirs) -> int:
    import numpy as np

    return int(np.abs(ours - theirs).max())


@contextlib.contextmanager
def scout_modules(tmp_path):
    """``(convert_to_raster, node_outputs)``, importable the way a run of the
    package's node imports them: staged into a folder of the run's own."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run"
    run.mkdir()
    staged = stage_package_modules({"root": str(SOURCES), "names": [MODULE]}, str(run))
    assert staged == {"root": "package_modules", "names": [MODULE]}, staged
    with importable(str(run / staged["root"]), staged["names"]):
        yield (
            importlib.import_module(f"{MODULE}.convert_to_raster"),
            importlib.import_module(f"{MODULE}.node_outputs"),
        )


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A sandbox store of the test's own, as the sandbox suites make one."""
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    release_connection()
    init_db()
    yield tmp_path
    release_connection()


def _buildings():
    import geopandas as gpd

    return gpd.read_file(BUILDINGS)


def _with_values(**values) -> list:
    """The manifest's widgets, with *values* set as a user sets them."""
    widgets = [dict(widget) for widget in _template()["widgets"]]
    for widget in widgets:
        if widget["name"] in values:
            widget["value"] = values[widget["name"]]
    return widgets


def run_node(buildings, workspace, *, fails=False, **values):
    """Run the node's template, its widgets at *values*, on *buildings* in the
    sandbox, in process: ``(artifact id, output)``, or with *fails* the
    node's error text."""
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    template = _template()
    source = (PACKAGE / template["source"]).read_text(encoding="utf-8")
    code, problems = resolve_references(source, _with_values(**values), "python", inputs=[{"slot": 0}])
    assert problems == [], problems
    _worker_init()
    art_id = save_to_duckdb(buildings, node_id="buildings")
    result = execute_code(
        textwrap.indent(code, "    "), art_id, NODE_TYPE, "geodataframe",
        save_dataset=False, media_dir=str(workspace / "media"),
        package_modules={"root": str(SOURCES), "names": [MODULE]},
    )
    if fails:
        assert result["stderr"], f"the node ran: {result['output']}"
        return result["stderr"]
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "outputs", result["output"]
    return result["output"]["path"], load_from_duckdb(result["output"]["path"])


# ---------------------------------------------------------------------------
# The proof
# ---------------------------------------------------------------------------

def test_scouts_buildings_become_scouts_committed_tiles(tmp_path):
    """SCOUT's call, on SCOUT's committed buildings, writes SCOUT's committed
    tiles: the same four files, each within one gray level."""
    with scout_modules(tmp_path) as (convert, _outputs):
        out = tmp_path / "A_rasters"
        convert.convert_raster(vector_in=str(BUILDINGS), attribute="height", zoom=16, raster_out=str(out))
    assert sorted(p.name for p in out.iterdir()) == TILE_NAMES
    worst = {name: _worst(_gray(out / name), _gray(SCOUT_TILES / name)) for name in TILE_NAMES}
    assert all(levels <= 1 for levels in worst.values()), worst
    # Not two blank images agreeing: each of SCOUT's tiles holds buildings.
    assert all(_gray(SCOUT_TILES / name).max() > 0 for name in TILE_NAMES)


def test_the_eight_bit_conversion_is_opencvs(tmp_path):
    """``create_image`` writes with Pillow what ``cv2.imwrite`` wrote: a float
    image rounded half to even, saturated to 0..255, NaN and infinities 0."""
    import numpy as np

    with scout_modules(tmp_path) as (convert, _outputs):
        values = np.array([[0.4, 0.5, 1.5, 2.5, 254.5, 255.5, 300.0, -3.0, np.nan, np.inf, -np.inf]])
        assert convert.to_uint8(values).tolist() == [[0, 0, 2, 2, 254, 255, 255, 0, 0, 0, 0]]


# ---------------------------------------------------------------------------
# The template
# ---------------------------------------------------------------------------

def test_the_template_declares_the_widgets_its_source_reads():
    template = _template()
    assert template["hasWidgets"] is True
    assert {w["name"]: w["default"] for w in template["widgets"]} == {
        "attribute": "height", "zoom": 16, "max_height": 550,
    }
    source = (PACKAGE / template["source"]).read_text(encoding="utf-8")
    assert re.findall(r"\[!!\s*(\w+)\s*!!\]", source) == ["attribute", "zoom", "max_height"]


def test_the_shipped_dataflow_runs_the_template_as_the_palette_drops_it():
    """``BuildingRasters.json`` is how its CI run reaches this package: its node
    holds the template's own source and widgets, so the dataflow cannot drift
    from what the package ships."""
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]
    assert spec["packages"] == ["scout.raster-conversion@1"]
    (node,) = [n for n in spec["nodes"] if n["type"] == NODE_TYPE]
    template = _template()
    assert node["content"] == (PACKAGE / template["source"]).read_text(encoding="utf-8")
    assert node["metadata"]["widgets"] == template["widgets"]


# ---------------------------------------------------------------------------
# The node, in the sandbox
# ---------------------------------------------------------------------------

def test_the_node_returns_scouts_tiles_and_their_mosaic(workspace):
    import numpy as np
    import rasterio

    from utk_curio.sandbox.util.rasters import epsg_name

    _art_id, (mosaic, tiles) = run_node(_buildings(), workspace)
    try:
        assert list(tiles.columns) == ["zoom", "x", "y", "png"]
        names = [f"{r.zoom}_{r.x}_{r.y}.png" for r in tiles.itertuples(index=False)]
        assert names == TILE_NAMES
        grays = {f"{r.zoom}_{r.x}_{r.y}.png": _gray(r.png) for r in tiles.itertuples(index=False)}
        worst = {name: _worst(grays[name], _gray(SCOUT_TILES / name)) for name in TILE_NAMES}
        assert all(levels <= 1 for levels in worst.values()), worst

        assert isinstance(mosaic, rasterio.io.DatasetReader)
        assert epsg_name(mosaic.crs) == "EPSG:3395"
        assert (mosaic.width, mosaic.height, mosaic.count) == (512, 512, 1)
        assert mosaic.dtypes[0] == "float32"
        cells = mosaic.read(1)
        # Columns of tiles run west to east with x, rows north to south with y.
        for name, (row, col) in {
            "16_16814_24355.png": (0, 0), "16_16815_24355.png": (0, 1),
            "16_16814_24356.png": (1, 0), "16_16815_24356.png": (1, 1),
        }.items():
            block = cells[256 * row:256 * (row + 1), 256 * col:256 * (col + 1)]
            assert np.allclose(block, grays[name] * (550.0 / 255.0), atol=1e-3), name
    finally:
        mosaic.close()


def test_the_mosaic_lies_on_the_tiles_corners(workspace):
    """The mosaic's grid is the tiles' own: its corners are the outer corners
    of its corner tiles in EPSG:3395, where ``compute_tile`` draws them."""
    from pyproj import Transformer

    _art_id, (mosaic, _tiles) = run_node(_buildings(), workspace)
    try:
        to_3395 = Transformer.from_crs(4326, 3395, always_xy=True)
        west, north = to_3395.transform(*_tile_corner(16814, 24355, 16))
        east, south = to_3395.transform(*_tile_corner(16816, 24357, 16))
        a, b, c, d, e, f = tuple(mosaic.transform)[:6]
        assert b == 0 and d == 0
        assert c == pytest.approx(west, abs=1e-6) and f == pytest.approx(north, abs=1e-6)
        assert c + 512 * a == pytest.approx(east, abs=1e-6)
        # Rows of tiles differ in height by millionths of a cell.
        assert f + 512 * e == pytest.approx(south, abs=0.01 * abs(e))
    finally:
        mosaic.close()


def _tile_corner(x, y, zoom):
    """``(lon, lat)`` of a tile's north-west corner, as SCOUT's ``num2deg``."""
    import math

    n = 2.0 ** zoom
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return x / n * 360.0 - 180.0, lat


def test_the_mosaic_is_a_raster_the_autark_node_loads(workspace):
    """What #718's raster route serves for the tuple's first part, and what
    the Autark node then requires of it: an EPSG CRS, a north-up grid, at
    most 2048 by 2048 cells and 8192 on a side."""
    from rasterio.io import MemoryFile

    from utk_curio.sandbox.util.rasters import serve_raster

    art_id, (mosaic, _tiles) = run_node(_buildings(), workspace)
    try:
        payload, meta = serve_raster(art_id, part=0, max_cells=AUTARK_MAX_CELLS, max_side=AUTARK_MAX_SIDE)
        assert meta["crs"] == "EPSG:3395"
        a, b, c, d, e, f = meta["transform"]
        assert b == 0 and d == 0 and a > 0 and e < 0
        assert (meta["width"], meta["height"], meta["count"]) == (512, 512, 1)
        with MemoryFile(payload) as memory, memory.open() as served:
            assert served.crs == mosaic.crs and served.transform == mosaic.transform
            assert (served.read(1) == mosaic.read(1)).all()
    finally:
        mosaic.close()


def test_each_widget_reaches_the_call(workspace):
    """A value set in each widget changes what the node returns."""
    import numpy as np

    default = run_node(_buildings(), workspace)[1]
    try:
        tiles = default[1]

        zoomed = run_node(_buildings(), workspace, zoom=15)[1]
        zoomed[0].close()
        assert {int(z) for z in zoomed[1]["zoom"]} == {15}
        assert sorted(zip(zoomed[1]["x"], zoomed[1]["y"])) == [(8407, 12177), (8407, 12178)]

        # Half the maximum height: every gray level doubles.
        lower = run_node(_buildings(), workspace, max_height=275)[1]
        lower[0].close()
        assert len(lower[1]) == len(tiles)
        for ours, half in zip(lower[1]["png"], tiles["png"]):
            assert _worst(_gray(ours), np.clip(2 * _gray(half), 0, 255)) <= 1
        assert max(_gray(png).max() for png in lower[1]["png"]) > max(_gray(png).max() for png in tiles["png"])

        renamed = _buildings().rename(columns={"height": "roof_m"})
        by_column = run_node(renamed, workspace, attribute="roof_m")[1]
        by_column[0].close()
        assert list(by_column[1]["png"]) == list(tiles["png"])
    finally:
        default[0].close()


@pytest.mark.parametrize(
    "change, sentence",
    [
        ("no crs", "The buildings layer has no CRS"),
        ("no such column", "The buildings layer has no column 'floors'"),
        ("no rows", "The buildings layer has no geometries to rasterize"),
    ],
)
def test_a_layer_the_node_cannot_read_says_why(workspace, change, sentence):
    buildings = _buildings()
    values = {}
    if change == "no crs":
        buildings = buildings.set_crs(None, allow_override=True)
    elif change == "no such column":
        values = {"attribute": "floors"}
    else:
        buildings = buildings.iloc[0:0]
    error = run_node(buildings, workspace, fails=True, **values)
    assert sentence in error, error
