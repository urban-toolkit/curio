"""``scout.raster-conversion@1``: SCOUT's building rasterizer in Curio (#662, step 17).

The proof: the package's ``convert_to_raster.py`` is SCOUT's, but for the lines
marked ``# Curio:``, and SCOUT's call on the buildings SCOUT committed for its
high-rise shadow example writes the four zoom-16 height tiles SCOUT committed
for them, byte for byte. Both are SCOUT's own files, copied unchanged into
``fixtures/scout/`` (see its ``ATTRIBUTION.md``).

The nodes: Rasterize Buildings, its widgets resolved the way a run resolves
them, runs SCOUT's call on its input GeoDataFrame in the sandbox with its
package's modules (#719), saves SCOUT's tiles as the dataflow's computed
dataset "tiles" (``curio_save_folder``) and returns a table of them. Mosaic
Tiles reads them back (``curio_computed_path``) and returns one raster, the
mosaic of SCOUT's tiles, which the Autark node's raster path (#718) loads.
Each widget reaches the call.

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
MOSAIC_TYPE = "scout.raster-conversion/mosaic-tiles"
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
#: Where each of SCOUT's tiles lies in the mosaic, ``(row, column)`` of tiles.
TILE_SLOTS = {
    "16_16814_24355.png": (0, 0), "16_16815_24355.png": (0, 1),
    "16_16814_24356.png": (1, 0), "16_16815_24356.png": (1, 1),
}
#: What #718's Autark raster path loads at its own size (utils/raster/rasterLoad.ts).
AUTARK_MAX_CELLS = 4096 * 4096
AUTARK_MAX_SIDE = 8192


def _templates() -> dict:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    return {template["id"]: template for template in manifest["templates"]}


def _template(template_id: str = "rasterize-buildings") -> dict:
    return _templates()[template_id]


def _gray(path):
    """A tile's gray levels as ints: one 8-bit channel, 256 by 256, the format
    Deep Umbra decodes."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        assert image.format == "PNG" and image.mode == "L" and image.size == (256, 256), (
            image.format, image.mode, image.size,
        )
        return np.asarray(image).astype(int)


def _levels(heights, max_height=550.0):
    """A mosaic's heights in metres back as gray levels."""
    import numpy as np

    return np.clip(np.rint(heights * 255.0 / max_height), 0, 255).astype(int)


@contextlib.contextmanager
def scout_modules(tmp_path):
    """``(convert_to_raster, mosaic)``, importable the way a run of the
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
            importlib.import_module(f"{MODULE}.mosaic"),
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


def _with_values(template_id="rasterize-buildings", **values) -> list:
    """A template's widgets, with *values* set as a user sets them."""
    widgets = [dict(widget) for widget in _template(template_id)["widgets"]]
    for widget in widgets:
        if widget["name"] in values:
            widget["value"] = values[widget["name"]]
    return widgets


#: The id the backend gives the saved tiles; any id does in process.
TILES_ID = "computed.test.files.tiles"


def _run(template_id, input_art, data_type, workspace, *, values=(), computed=None):
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.app.worker import execute_code

    template = _template(template_id)
    source = (PACKAGE / template["source"]).read_text(encoding="utf-8")
    widgets = _with_values(template_id, **dict(values))
    code, problems = resolve_references(source, widgets, "python", inputs=[{"slot": 0}])
    assert problems == [], problems
    computed = computed or {}
    return execute_code(
        textwrap.indent(code, "    "), input_art, f"scout.raster-conversion/{template_id}", data_type,
        save_dataset=False, media_dir=str(workspace / "media"),
        package_modules={"root": str(SOURCES), "names": [MODULE]},
        dataset_paths=computed.pop("_paths", None), computed=computed,
    )


def rasterize(buildings, workspace, **values):
    """Rasterize Buildings, its widgets at *values*, on *buildings*: its result."""
    from utk_curio.sandbox.app.worker import _worker_init
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    _worker_init()
    art_id = save_to_duckdb(buildings, node_id="buildings")
    return _run("rasterize-buildings", art_id, "geodataframe", workspace, values=values, computed={"canSave": True})


def _saved_tiles(result) -> Path:
    """The folder of tiles Rasterize Buildings saved, as the backend would
    install it: its files beside a ``bundle.json``."""
    [entry] = result["output"]["savedFiles"]
    assert (entry["name"], entry["kind"]) == ("tiles", "folder"), entry
    folder = Path(entry["path"])
    (folder.parent / "bundle.json").write_text("{}", encoding="utf-8")
    return folder


def run_node(buildings, workspace, *, fails=False, **values):
    """Run Rasterize Buildings, its widgets at *values*, on *buildings*, then
    Mosaic Tiles on what it saved and returned, in the sandbox, in process:
    ``(artifact id, mosaic)``, or with *fails* Rasterize's ``(stdout, stderr)``."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = rasterize(buildings, workspace, **values)
    if fails:
        assert result["stderr"], f"the node ran: {result['output']}"
        return result["stdout"], result["stderr"]
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "dataframe", result["output"]
    folder = _saved_tiles(result)
    mosaicked = _run(
        "mosaic-tiles", result["output"]["path"], "dataframe", workspace,
        computed={"names": {"tiles": TILES_ID}, "_paths": {TILES_ID: str(folder.parent / "bundle.json")}},
    )
    assert mosaicked["stderr"] == "", mosaicked["stderr"]
    assert mosaicked["output"]["dataType"] == "raster", mosaicked["output"]
    return mosaicked["output"]["path"], load_from_duckdb(mosaicked["output"]["path"])


# ---------------------------------------------------------------------------
# The proof
# ---------------------------------------------------------------------------

def test_scouts_file_changes_only_the_marked_lines():
    """The lines Curio changes in SCOUT's file are the ones it marks: pygeos's
    import and three calls, ``.array.data``, a GeoDataFrame read as it is
    rather than from a file, the maximum height, and the making and emptying
    of the output folder taken out, since ``curio_save_folder`` gives an
    empty one."""
    text = (SOURCES / MODULE / "convert_to_raster.py").read_text(encoding="utf-8")
    marked = [line.split("# Curio:")[0].strip() for line in text.splitlines() if "# Curio:" in line]
    assert marked == [
        "import shapely",
        "arr_flat, part_indices = shapely.get_parts(arr, return_index=True)",
        "arr_flat2, ring_indices = shapely.get_rings(arr_flat, return_index=True)",
        "coords, indices = shapely.get_coordinates(arr_flat2, return_index=True)",
        "geometries = spatialpandas_from_pygeos(np.asarray(source.geometry.array))",
        "def convert_raster(vector_in: str, attribute: str, zoom: int, raster_out: str, max_height: float = 550):",
        "gdf = vector_in if isinstance(vector_in, gpd.GeoDataFrame) else gpd.read_file(vector_in)",
        "",
        "ddelayed = compute_tile(gdf, i, j, zoom, max_height, raster_out)",
    ]
    assert "raster_out.mkdir" not in text and "file.unlink()" not in text
    assert "pygeos." not in text.replace("# Curio: pygeos.", "")
    # SCOUT's own lines Curio keeps.
    for line in ("import cv2", "success_ = cv2.imwrite(filename_, values)", "ds.Canvas.polygons = polygons",
                 "gdf = gdf.to_crs(epsg=3395)", "print(f\"Feature '{attribute}' not supported for layer\")"):
        assert line in text, line


def test_scouts_buildings_become_scouts_committed_tiles(tmp_path):
    """SCOUT's call, on SCOUT's committed buildings, writes SCOUT's committed
    tiles: the same four files, byte for byte."""
    with scout_modules(tmp_path) as (convert, _mosaic):
        out = tmp_path / "A_rasters"
        out.mkdir()  # as curio_save_folder gives it
        convert.convert_raster(vector_in=str(BUILDINGS), attribute="height", zoom=16, raster_out=str(out))
    assert sorted(p.name for p in out.iterdir()) == TILE_NAMES
    for name in TILE_NAMES:
        assert (out / name).read_bytes() == (SCOUT_TILES / name).read_bytes(), name
    # Not two blank images agreeing: each of SCOUT's tiles holds buildings.
    assert all(_gray(SCOUT_TILES / name).max() > 0 for name in TILE_NAMES)


def test_a_geodataframe_becomes_the_same_tiles_as_scouts_file(tmp_path):
    """The node hands SCOUT's call its input GeoDataFrame, not a file: the
    tiles are SCOUT's committed ones all the same."""
    with scout_modules(tmp_path) as (convert, _mosaic):
        out = tmp_path / "from_frame"
        out.mkdir()  # as curio_save_folder gives it
        convert.convert_raster(vector_in=_buildings(), attribute="height", zoom=16, raster_out=str(out))
    assert sorted(p.name for p in out.iterdir()) == TILE_NAMES
    for name in TILE_NAMES:
        assert (out / name).read_bytes() == (SCOUT_TILES / name).read_bytes(), name


# ---------------------------------------------------------------------------
# The mosaic
# ---------------------------------------------------------------------------

def test_tiles_lie_side_by_side_on_their_own_grid(tmp_path):
    """Two diagonal tiles make a 2 by 2 mosaic: each in its slot, the tile
    missing between them 0, the corner SCOUT's own."""
    import cv2
    import numpy as np

    folder = tmp_path / "tiles"
    folder.mkdir()
    cv2.imwrite(str(folder / "5_10_20.png"), np.full((256, 256), 51, dtype=np.uint8))
    cv2.imwrite(str(folder / "5_11_21.png"), np.full((256, 256), 102, dtype=np.uint8))
    with scout_modules(tmp_path) as (_convert, mosaic):
        raster = mosaic.mosaic(str(folder), 5, 255, lambda name: str(tmp_path / name))
        west, north = mosaic.corner(10, 20, 5)
        east, _ = mosaic.corner(11, 20, 5)
    with raster:
        cells = raster.read(1)
        assert cells.shape == (512, 512) and raster.dtypes[0] == "float32"
        assert (cells[:256, :256] == 51).all() and (cells[256:, 256:] == 102).all()
        assert (cells[:256, 256:] == 0).all() and (cells[256:, :256] == 0).all()
        assert raster.transform.c == west and raster.transform.f == north
        assert raster.transform.a == (east - west) / 256
        assert raster.descriptions == ("height (m)",)
        assert {k: raster.tags()[k] for k in ("zoom", "tile_x", "tile_y", "tile_size", "max_height")} == {
            "zoom": "5", "tile_x": "10", "tile_y": "20", "tile_size": "256", "max_height": "255.0",
        }


# ---------------------------------------------------------------------------
# The template
# ---------------------------------------------------------------------------

def test_the_template_declares_the_widgets_its_source_reads():
    template = _template()
    assert template["hasWidgets"] is True
    assert {w["name"]: w["default"] for w in template["widgets"]} == {
        "attribute": "height", "zoom": 16, "max_height": 550, "tiles": "tiles",
    }
    assert template["outputPorts"] == [{"cardinality": "1", "types": ["DATAFRAME"]}]
    source = (PACKAGE / template["source"]).read_text(encoding="utf-8")
    assert re.findall(r"\[!!\s*(\w+)\s*!!\]", source) == [
        "tiles", "attribute", "zoom", "max_height", "zoom", "max_height",
    ]
    assert "curio_save_folder([!! tiles !!])" in source


def test_mosaic_tiles_reads_what_rasterize_saves():
    """Mosaic Tiles' one widget is the name Rasterize Buildings saved the
    tiles under; its input says the zoom and the maximum height."""
    template = _template("mosaic-tiles")
    assert template["hasWidgets"] is True
    assert [(w["name"], w["default"]) for w in template["widgets"]] == [("tiles", "tiles")]
    assert template["inputPorts"] == [{"cardinality": "1", "types": ["DATAFRAME"]}]
    assert template["outputPorts"] == [{"cardinality": "1", "types": ["RASTER"]}]
    source = (PACKAGE / template["source"]).read_text(encoding="utf-8")
    assert "curio_computed_path([!! tiles !!])" in source


def test_rasterize_returns_a_table_of_the_tiles_it_saved(workspace):
    result = rasterize(_buildings(), workspace)
    assert result["stderr"] == "", result["stderr"]
    folder = _saved_tiles(result)
    assert sorted(p.name for p in folder.iterdir() if p.is_file()) == TILE_NAMES
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    table = load_from_duckdb(result["output"]["path"])
    assert list(table.columns) == ["zoom", "x", "y", "max_height"]
    assert [tuple(row) for row in table[["x", "y"]].itertuples(index=False)] == [
        (16814, 24355), (16814, 24356), (16815, 24355), (16815, 24356),
    ]
    assert set(table["zoom"]) == {16} and set(table["max_height"]) == {550.0}


def test_rasterize_cannot_save_in_a_dataflow_never_saved(workspace):
    from utk_curio.sandbox.app.worker import _worker_init
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    _worker_init()
    art_id = save_to_duckdb(_buildings(), node_id="buildings")
    result = _run("rasterize-buildings", art_id, "geodataframe", workspace,
                  computed={"canSave": False, "reason": "Save the dataflow first."})
    assert "Save the dataflow first." in result["stderr"]


def test_the_shipped_dataflow_runs_the_template_as_the_palette_drops_it():
    """``BuildingRasters.json`` is how its CI run reaches this package: its
    nodes hold the templates' own sources and widgets, so the dataflow cannot
    drift from what the package ships, and Mosaic Tiles reads Rasterize's table."""
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]
    assert spec["packages"] == ["scout.raster-conversion@1"]
    (node,) = [n for n in spec["nodes"] if n["type"] == NODE_TYPE]
    template = _template()
    assert node["content"] == (PACKAGE / template["source"]).read_text(encoding="utf-8")
    assert node["metadata"]["widgets"] == template["widgets"]
    (mosaic,) = [n for n in spec["nodes"] if n["type"] == MOSAIC_TYPE]
    assert mosaic["content"] == (PACKAGE / _template("mosaic-tiles")["source"]).read_text(encoding="utf-8")
    assert [(e["source"], e["target"]) for e in spec["edges"] if e["target"] == mosaic["id"]] == [(node["id"], mosaic["id"])]


# ---------------------------------------------------------------------------
# The node, in the sandbox
# ---------------------------------------------------------------------------

def test_the_node_returns_the_mosaic_of_scouts_tiles(workspace):
    import rasterio

    from utk_curio.sandbox.util.rasters import epsg_name

    _art_id, mosaic = run_node(_buildings(), workspace)
    with mosaic:
        assert isinstance(mosaic, rasterio.io.DatasetReader)
        assert epsg_name(mosaic.crs) == "EPSG:3395"
        assert (mosaic.width, mosaic.height, mosaic.count) == (512, 512, 1)
        assert mosaic.dtypes[0] == "float32"
        levels = _levels(mosaic.read(1))
        # Columns of tiles run west to east with x, rows north to south with y.
        for name, (row, col) in TILE_SLOTS.items():
            block = levels[256 * row:256 * (row + 1), 256 * col:256 * (col + 1)]
            assert (block == _gray(SCOUT_TILES / name)).all(), name


def test_the_mosaic_lies_on_the_tiles_corners(workspace):
    """The mosaic's grid is the tiles' own: its corners are the outer corners
    of its corner tiles in EPSG:3395, where ``compute_tile`` draws them."""
    from pyproj import Transformer

    _art_id, mosaic = run_node(_buildings(), workspace)
    with mosaic:
        to_3395 = Transformer.from_crs(4326, 3395, always_xy=True)
        west, north = to_3395.transform(*_tile_corner(16814, 24355, 16))
        east, south = to_3395.transform(*_tile_corner(16816, 24357, 16))
        a, b, c, d, e, f = tuple(mosaic.transform)[:6]
        assert b == 0 and d == 0
        assert c == pytest.approx(west, abs=1e-6) and f == pytest.approx(north, abs=1e-6)
        assert c + 512 * a == pytest.approx(east, abs=1e-6)
        # Rows of tiles differ in height by millionths of a cell.
        assert f + 512 * e == pytest.approx(south, abs=0.01 * abs(e))


def _tile_corner(x, y, zoom):
    """``(lon, lat)`` of a tile's north-west corner, as SCOUT's ``num2deg``."""
    import math

    n = 2.0 ** zoom
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return x / n * 360.0 - 180.0, lat


def test_the_mosaic_is_a_raster_the_autark_node_loads(workspace):
    """What #718's raster route serves for the node's output, and what the
    Autark node then requires of it: an EPSG CRS, a north-up grid, at most
    4096 by 4096 cells and 8192 on a side."""
    from rasterio.io import MemoryFile

    from utk_curio.sandbox.util.rasters import serve_raster

    art_id, mosaic = run_node(_buildings(), workspace)
    with mosaic:
        payload, meta = serve_raster(art_id, max_cells=AUTARK_MAX_CELLS, max_side=AUTARK_MAX_SIDE)
        assert meta["crs"] == "EPSG:3395"
        a, b, c, d, e, f = meta["transform"]
        assert b == 0 and d == 0 and a > 0 and e < 0
        assert (meta["width"], meta["height"], meta["count"]) == (512, 512, 1)
        with MemoryFile(payload) as memory, memory.open() as served:
            assert served.crs == mosaic.crs and served.transform == mosaic.transform
            assert (served.read(1) == mosaic.read(1)).all()


def test_each_widget_reaches_the_call(workspace):
    """A value set in each widget changes what the node returns."""
    import numpy as np

    _art_id, default = run_node(_buildings(), workspace)
    with default:
        levels = _levels(default.read(1))

    _art_id, zoomed = run_node(_buildings(), workspace, zoom=15)
    with zoomed:
        assert (zoomed.tags()["zoom"], zoomed.tags()["tile_x"], zoomed.tags()["tile_y"]) == ("15", "8407", "12177")
        assert (zoomed.width, zoomed.height) == (256, 512)

    # Half the maximum height: every gray level doubles.
    _art_id, lower = run_node(_buildings(), workspace, max_height=275)
    with lower:
        assert lower.tags()["max_height"] == "275.0"
        doubled = _levels(lower.read(1), 275.0)
    assert int(np.abs(doubled - np.clip(2 * levels, 0, 255)).max()) <= 1
    assert doubled.max() > levels.max()


def test_a_column_other_than_height_is_scouts_unsupported_feature(workspace):
    """SCOUT rasterizes ``height`` only: for another column it prints so and
    writes no tile, and the node says it wrote none."""
    renamed = _buildings().rename(columns={"height": "roof_m"})
    stdout, stderr = run_node(renamed, workspace, fails=True, attribute="roof_m")
    assert "Feature 'roof_m' not supported for layer" in "\n".join(stdout)
    assert "wrote no tiles" in stderr
