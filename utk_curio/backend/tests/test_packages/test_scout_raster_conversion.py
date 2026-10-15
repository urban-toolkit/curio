"""``scout.raster-conversion@1``: SCOUT's building rasterizer in Curio (#662, step 17).

The proof: the package's port of SCOUT's ``convert_raster``, called as SCOUT's
high-rise shadow example calls it, turns the buildings SCOUT committed for that
example into the four zoom-16 height tiles SCOUT committed for them, each
within one gray level. Both are SCOUT's own files, copied unchanged into
``fixtures/scout/`` (see its ``ATTRIBUTION.md``).

The node: its template, with the widgets its manifest declares, resolved the
way a run resolves a node's widgets, runs in the sandbox with its package's
modules (#719). It returns one raster of heights: SCOUT's tiles side by side,
no data where ``convert_raster`` wrote no tile, a raster the Autark node's
raster path (#718) loads; and each widget reaches the call.

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
AUTARK_MAX_CELLS = 4096 * 4096
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
    assert result["output"]["dataType"] == "raster", result["output"]
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


def test_its_one_output_is_a_raster():
    """One buildings layer in, one raster of heights out: no table of tiles."""
    template = _template()
    assert template["inputPorts"] == [{"cardinality": "1", "types": ["GEODATAFRAME"]}]
    assert template["outputPorts"] == [{"cardinality": "1", "types": ["RASTER"]}]


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

def _levels(cells):
    """A raster's heights back as the gray levels they were drawn from (level
    times 550 over 255), checked to be whole levels."""
    import numpy as np

    levels = np.asarray(cells, dtype="float64") * (255.0 / 550.0)
    assert np.abs(levels - np.rint(levels)).max() < 1e-3
    return np.rint(levels).astype(int)


def _blocks(cells, columns: int = 2, rows: int = 2) -> dict:
    """``{(column, row): the tile's 256 by 256 cells}``; columns of tiles run
    west to east with x, rows north to south with y."""
    return {
        (column, row): cells[256 * row:256 * (row + 1), 256 * column:256 * (column + 1)]
        for row in range(rows) for column in range(columns)
    }


def test_the_node_returns_one_raster_of_scouts_tiles(workspace):
    """One raster out: SCOUT's four tiles side by side in EPSG:3395, each cell
    a height in metres whose gray level is within one of SCOUT's committed
    tile's. NaN names its no data, and no cell is no data, since a building
    lies near every one of the four tiles."""
    import numpy as np
    import rasterio

    from utk_curio.sandbox.util.rasters import epsg_name

    _art_id, raster = run_node(_buildings(), workspace)
    try:
        assert isinstance(raster, rasterio.io.DatasetReader)
        assert epsg_name(raster.crs) == "EPSG:3395"
        assert (raster.width, raster.height, raster.count) == (512, 512, 1)
        assert raster.dtypes[0] == "float32"
        assert raster.nodata is not None and np.isnan(raster.nodata), raster.nodata
        assert raster.descriptions == ("height (m)",)
        cells = raster.read(1)
        assert not np.isnan(cells).any()
        tags = raster.tags()
        assert (tags["zoom"], tags["tile_x"], tags["tile_y"], tags["max_height"]) == ("16", "16814", "24355", "550.0")
        worst = {
            f"16_{16814 + column}_{24355 + row}.png": _worst(_levels(block), _gray(SCOUT_TILES / f"16_{16814 + column}_{24355 + row}.png"))
            for (column, row), block in _blocks(cells).items()
        }
        assert sorted(worst) == TILE_NAMES
        assert all(levels <= 1 for levels in worst.values()), worst
    finally:
        raster.close()


def test_tiles_convert_raster_never_writes_are_no_data(workspace, tmp_path):
    """Two buildings in diagonal tiles: SCOUT's ``convert_raster`` writes those
    two tiles and not the two beside them, as it writes a tile only where a
    building is near. The raster spans the four, and the two it never wrote
    are no data, which a masked read leaves out, while each written tile is
    ``convert_raster``'s, its ground a height of 0."""
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import box

    zoom, x, y = 16, 16814, 24355
    centres = [_tile_corner(x + 0.5, y + 0.5, zoom), _tile_corner(x + 1.5, y + 1.5, zoom)]
    buildings = gpd.GeoDataFrame(
        {"height": [120.0, 300.0]},
        geometry=[box(lon - 0.0005, lat - 0.0003, lon + 0.0005, lat + 0.0003) for lon, lat in centres],
        crs="EPSG:4326",
    )
    with scout_modules(tmp_path) as (convert, _outputs):
        written_folder = tmp_path / "written"
        convert.convert_raster(vector_in=buildings, attribute="height", zoom=zoom, raster_out=str(written_folder))
    written = sorted(p.name for p in written_folder.iterdir())
    assert written == [f"{zoom}_{x}_{y}.png", f"{zoom}_{x + 1}_{y + 1}.png"], written

    _art_id, raster = run_node(buildings, workspace)
    try:
        assert (raster.width, raster.height) == (512, 512)
        assert (raster.tags()["tile_x"], raster.tags()["tile_y"]) == (str(x), str(y))
        assert raster.nodata is not None and np.isnan(raster.nodata), raster.nodata
        holding = []
        for (column, row), block in _blocks(raster.read(1)).items():
            name = f"{zoom}_{x + column}_{y + row}.png"
            if np.isnan(block).all():
                continue
            holding.append(name)
            assert not np.isnan(block).any(), f"{name} is written and partly no data"
            assert np.array_equal(_levels(block), _gray(written_folder / name)), name
        assert sorted(holding) == written, f"tiles holding heights {holding}, tiles written {written}"
        # Only the written tiles' cells are values: 2 tiles of 256 by 256.
        assert int(raster.read(1, masked=True).count()) == 2 * 256 * 256
    finally:
        raster.close()


def test_the_mosaic_lies_on_the_tiles_corners(workspace):
    """The raster's grid is the tiles' own: its corners are the outer corners
    of its corner tiles in EPSG:3395, where ``compute_tile`` draws them."""
    from pyproj import Transformer

    _art_id, mosaic = run_node(_buildings(), workspace)
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
    """What #718's raster route serves for the node's raster, and what the
    Autark node then requires of it: an EPSG CRS, a north-up grid, at most
    4096 by 4096 cells and 8192 on a side."""
    from rasterio.io import MemoryFile

    from utk_curio.sandbox.util.rasters import serve_raster

    art_id, mosaic = run_node(_buildings(), workspace)
    try:
        payload, meta = serve_raster(art_id, max_cells=AUTARK_MAX_CELLS, max_side=AUTARK_MAX_SIDE)
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
    """A value set in each widget changes the raster the node returns."""
    import numpy as np

    default = run_node(_buildings(), workspace)[1]
    try:
        heights = default.read(1)
        levels = _levels(heights)

        # Zoom 15: one column of two tiles, x 8407 and y 12177 to 12178.
        with run_node(_buildings(), workspace, zoom=15)[1] as zoomed:
            tags = zoomed.tags()
            assert (tags["zoom"], tags["tile_x"], tags["tile_y"]) == ("15", "8407", "12177"), tags
            assert (zoomed.width, zoomed.height) == (256, 512)

        # Half the maximum height: every gray level doubles.
        with run_node(_buildings(), workspace, max_height=275)[1] as lower:
            assert lower.tags()["max_height"] == "275.0"
            assert (lower.width, lower.height) == (default.width, default.height)
            doubled = np.rint(lower.read(1).astype("float64") * (255.0 / 275.0)).astype(int)
            assert _worst(doubled, np.clip(2 * levels, 0, 255)) <= 1
            assert doubled.max() > levels.max()

        renamed = _buildings().rename(columns={"height": "roof_m"})
        with run_node(renamed, workspace, attribute="roof_m")[1] as by_column:
            assert np.array_equal(by_column.read(1), heights)
    finally:
        default.close()


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
