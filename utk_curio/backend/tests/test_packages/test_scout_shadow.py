"""``model.scout.deep-umbra@1``: SCOUT's Deep Umbra shadow model in Curio (#662, step 19).

Deep Umbra is a model package: its weights under ``models/``, its node
(Accumulated Shadow, with its Season widget and a three-line cell) and its
module ``deep_umbra``. The package's license is its code's, MIT; the model
block holds the weights' license, SCOUT's permission.

The node reads a height raster, the one raster of Rasterize Buildings
(``curio.scout@1``), runs Deep Umbra on every zoom-16 tile of it
that holds heights and returns the accumulated shadow as a raster on the same
grid. SCOUT's metrics, the mean and median over the ground, are the
statistics of a Raster Calculator (``curio.scout@1`` too) with the heights as
its mask, as the shipped dataflow ``chicago-loop-shadow-towers.json`` wires it.

The proof starts from SCOUT's own files, copied unchanged into
``fixtures/scout/`` (see its ``ATTRIBUTION.md``): SCOUT's committed height tiles
of both scenarios of its high-rise shadow example become one mosaic each,
written by Rasterize Buildings' own ``write_mosaic``. Then:

- the mosaic gives back SCOUT's tiles, gray level for gray level, and the
  generator's three inputs are the ones SCOUT's file-reading
  ``load_input_grid`` builds, to the bit;
- with the ONNX export of SCOUT's generator that Curio ships (the weights of
  the model package), loaded as ``curio_load_model`` loads it, in summer, the
  shadow of each tile, in SCOUT's 8 bits, is SCOUT's committed shadow tile;
- the dataflow's Raster Calculator of statistics, run as it is written on the
  node's shadow raster and the mosaic, gives SCOUT's committed mean and median;
- on a tile set with a gap, as ``convert_raster`` leaves one where no building
  is near a tile, the mosaic has no data there, the node predicts only the
  tiles written, and the statistics count the ground of those tiles only, as
  SCOUT's ``run_shadow_model`` does.

Within a tolerance, not equal. Deep Umbra normalizes each layer by the tile's own
mean and variance, which makes its float32 output sensitive to the order of its
sums: ``scripts/scout/export_deep_umbra.py`` measured TensorFlow's own float32
run up to 0.016 from a float64 run of the same generator, on an output from -1 to
1, and onnxruntime within 0.0177 of TensorFlow. onnxruntime's output is the same
on 1 to 16 intra-op threads and moves from 17 on, by up to 0.027, as its sums are
split differently; Curio leaves the thread count to onnxruntime, so a machine
with more cores sees the second result. On SCOUT's tiles, up to 16 threads give
one gray level on up to 686 of a tile's 65,536 pixels (2 on 2 of them) and the
metrics within 0.013 minutes; 32 threads give up to 5 levels on up to 3,267
pixels (5%), the mean within 0.052 minutes and the median within 0.012. So a
tile may differ by at most 6 gray levels on at most 6% of its pixels, the mean
by at most 0.1 minutes and the median by at most 0.05. What a wrong call gives is
far outside that: the latitude off by one degree, 25 levels or more on 39% of a
tile's pixels or more and the mean off by 1.8 minutes or more; a wrong season,
200 levels or more; the export with BatchNorm on its stored averages instead of
the tile's statistics, a raw output 2.0 away where the right export is 0.0177.

The node: its template, its widget resolved the way a run resolves it, runs in
the sandbox with its package's modules (#719) and the model as the backend
resolves it.

Package code is imported inside each test, through a run's staged copy of the
package's modules, so a checkout without the package or its libraries fails each
test on its own and no bytecode lands in ``packages/``.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.util
import json
import os
import re
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
MODEL_ID = "model.scout.deep-umbra"
PACKAGE = REPO / "packages" / f"{MODEL_ID}@1"
SOURCES = PACKAGE / "sources"
MODULE = "deep_umbra"
NODE_TYPE = "model.scout.deep-umbra/accumulated-shadow"
CALCULATOR_TYPE = "curio.scout/raster-calculator"
RASTERIZE_TYPE = "curio.scout/rasterize-buildings"
#: The line a Raster Calculator's code takes statistics with.
STATISTICS_CALL = re.compile(r"^return raster_statistics\(", re.M)
MODEL = PACKAGE / "models" / "deep_umbra.onnx"
#: The node's cell, as a drop writes it: the module's call, the model by its id,
#: and the call on the input with the Season widget.
CELL = (
    "from deep_umbra import accumulated_shadow\n"
    'model = curio_load_model("model.scout.deep-umbra")\n'
    "return accumulated_shadow(input_0, season=[!! season !!], model=model, output_file=curio_output_file)\n"
)
#: The weights' license and publisher, in the model block; the code is MIT.
WEIGHTS_LICENSE = "Used with the permission of SCOUT's authors"
WEIGHTS_PUBLISHER = "SCOUT (urban-toolkit/scout)"
SCOUT = "https://github.com/urban-toolkit/scout"
#: The file ``scripts/scout/export_deep_umbra.py`` writes, in the environment its
#: docstring pins.
MODEL_SHA256 = "67afb9d2d56bd0a12164e6e651214d56860ff689728c5b6f29486f21c3cb188e"
BUILDINGS = REPO / "datasets" / "data.scout.loop-buildings@1" / "data" / "loop-buildings.geojson"
DATAFLOW = REPO / "docs" / "examples" / "dataflows" / "chicago-loop-shadow-towers.json"
#: The Autark map after the Compare Scenarios node in Difference: towers
#: removed minus existing, on a diverging scale centered on no change.
DIFFERENCE_MAP_DOCUMENT = {"map": {"layerRefs": [{
    "dataRef": "[!! input_0 !!]",
    "getFnv": "band_1",
    "colorMapInterpolator": "interpolateRdBu",
    "colorMapCenter": 0,
    "title": "Shadow change (minutes)",
}]}}
#: The color range both scenarios' shadow maps share, in minutes: from 0 to a
#: whole summer day of shadow, the most Deep Umbra's output stands for in any
#: season.
SHADOW_RANGE = [0, 720]
EXAMPLE = REPO / "docs" / "examples" / "24-scout-shadow-model-chicago-loop.json"
RASTER_PACKAGE = REPO / "packages" / "curio.scout@1"
RASTER_MODULE = "scout_rasters"
#: The modules a run of Scout's Raster Calculator is handed, and those a run
#: of Accumulated Shadow is: its own, then Scout's, which its package names in
#: ``dependencies.packages`` (``python_modules.modules_for_node``).
RASTER_MODULES = {"root": str(RASTER_PACKAGE / "sources"), "names": [RASTER_MODULE]}
SHADOW_MODULES = [{"root": str(SOURCES), "names": [MODULE]}, RASTER_MODULES]

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scout"
TILE_NAMES = [
    "16_16814_24355.png",
    "16_16814_24356.png",
    "16_16815_24355.png",
    "16_16815_24356.png",
]
#: SCOUT's example: tiles x 16814 and 16815, y 24355 and 24356, at zoom 16.
GRID = (16, 16814, 24355, 2, 2)
TILE_PIXELS = 256 * 256

#: The tolerance the module docstring explains.
MAX_LEVELS = 6
MAX_SHARE = 0.06
MAX_MEAN_MINUTES = 0.1
MAX_MEDIAN_MINUTES = 0.05

#: The buildings SCOUT's second scenario removes (the dataset's manifest names them).
REMOVED_IDS = [8, 10, 12, 13, 14, 18, 19, 31, 34, 51, 66, 77, 82, 106, 122]
#: The Interaction node (#662, #958; its type is still the Edit Features node's).
INTERACTION_TYPE = "curio.builtin/edit-features"
#: Towers removed's Interaction node, its edit log: one removal of those
#: buildings, matched on building_id, under a label.
TOWERS_LOG = {
    "key": "building_id",
    "edits": [{"op": "remove", "ids": REMOVED_IDS, "label": "SCOUT's 15 removed buildings"}],
}
#: The code the node writes from that log (``editFeaturesCode`` in
#: ``utils/editFeatures/editFeatures.ts``): one call of ``curio_edit_features``.
TOWERS_CODE = (
    "# Edit Features writes this code from its edit list: each edit, in the\n"
    "# order it was made, on the features whose key is one of its ids. It is\n"
    "# written again when the list changes.\n"
    "return curio_edit_features(input_0, [\n"
    '    {"op": "remove", "ids": [' + ", ".join(str(i) for i in REMOVED_IDS) + '], "label": "SCOUT\'s 15 removed buildings"},\n'
    '], key="building_id")\n'
)


def _manifest() -> dict:
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def _template() -> dict:
    (template,) = _manifest()["templates"]
    return template


def _source() -> str:
    return (PACKAGE / _template()["source"]).read_text(encoding="utf-8")


def _gray(path):
    """A tile's gray levels as ints, from its file."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        assert image.format == "PNG" and image.mode == "L" and image.size == (256, 256), (
            image.format, image.mode, image.size,
        )
        return np.asarray(image).astype(int)


def _levels(ours, theirs) -> tuple[int, int]:
    """``(largest gray-level difference, pixels that differ)`` between two tiles."""
    import numpy as np

    differ = np.abs(ours - theirs)
    return int(differ.max()), int((differ > 0).sum())


def _within(measured: dict) -> bool:
    return all(levels <= MAX_LEVELS and pixels <= MAX_SHARE * TILE_PIXELS for levels, pixels in measured.values())


def _metrics_within(ours, scouts) -> bool:
    """``(mean, median)`` within the tolerance of SCOUT's."""
    return (abs(ours[0] - scouts[0]) <= MAX_MEAN_MINUTES
            and abs(ours[1] - scouts[1]) <= MAX_MEDIAN_MINUTES)


def _metrics(path: Path) -> tuple[float, float]:
    """A metrics CSV's one row: the mean and the median accumulated shadow."""
    header, row = path.read_text(encoding="utf-8").strip().splitlines()
    assert header == "Mean Acc shadow,Median Acc shadow", header
    mean, median = (float(value) for value in row.split(","))
    return mean, median


def _session():
    import onnxruntime as ort

    return ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])


def _model():
    """Deep Umbra as the node gets it: what ``curio_load_model`` returns for the
    package's folder, which holds its manifest and its weights."""
    from utk_curio.sandbox.util.catalog_helpers import CurioModel

    return CurioModel(MODEL_ID, str(PACKAGE))


def _resolved_models(code: str) -> dict:
    """``{model id: folder}`` for the models *code* loads, as the backend
    resolves them for a run (``packages.service.resolve_model_dirs``), for an
    account whose store holds the package, as one seeded for the examples
    does (models run only from the store)."""
    from utk_curio.backend.app.datasets.domain.code_refs import model_ids_in_code
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir
    from utk_curio.backend.app.packages.service import resolve_model_dirs

    if not (package_dir("guest", PACKAGE.name) / "manifest.json").is_file():
        install_package_from_directory("guest", PACKAGE)
    return resolve_model_dirs("guest", model_ids_in_code(code))


@contextlib.contextmanager
def staged(tmp_path, sources: Path, module: str, *names: str, also=()):
    """*module*'s submodules *names*, importable the way a run of the package's
    node imports them: staged into a folder of the run's own, with the modules
    *also* names (``{"root", "names"}`` each) staged beside it."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / f"run-{module}"
    run.mkdir()
    staged_modules = stage_package_modules([{"root": str(sources), "names": [module]}, *also], str(run))
    wanted = [module, *(name for source in also for name in source["names"])]
    assert staged_modules == {"root": "package_modules", "names": wanted}, staged_modules
    with importable(str(run / staged_modules["root"]), staged_modules["names"]):
        yield tuple(importlib.import_module(f"{module}.{name}") for name in names)


def shadow_modules(tmp_path):
    """``(deep_umbra, node_outputs)``, as the node imports them, beside the
    Scout modules its node is handed."""
    return staged(tmp_path, SOURCES, MODULE, "deep_umbra", "node_outputs", also=[RASTER_MODULES])


def _mosaic(tmp_path, scenario: str = "A", *, zoom: int = 16, max_height: float = 550) -> Path:
    """SCOUT's committed height tiles of *scenario* as one mosaic, written by
    Rasterize Buildings' own ``write_mosaic``, as its node hands them on. With
    *zoom*, the tiles are named at that zoom level instead."""
    return _mosaic_of(tmp_path, FIXTURES / f"{scenario}_rasters", f"mosaic-{scenario}-{zoom}-{max_height:g}",
                      zoom=zoom, max_height=max_height)


def _mosaic_of(tmp_path, tiles: Path, name: str, *, zoom: int = 16, max_height: float = 550) -> Path:
    """The height tiles in the folder *tiles* as one mosaic, written by
    Rasterize Buildings' own ``read_tiles`` and ``write_mosaic``."""
    folder = tmp_path / name
    folder.mkdir()
    with staged(folder, RASTER_PACKAGE / "sources", RASTER_MODULE, "node_outputs") as (raster_outputs,):
        table = raster_outputs.read_tiles(str(tiles)).assign(zoom=zoom)
        return Path(raster_outputs.write_mosaic(table, max_height, str(folder / "mosaic.tif")))


def _open(path):
    import rasterio

    return rasterio.open(path)


def _block(cells, column: int, row: int):
    return cells[256 * row:256 * (row + 1), 256 * column:256 * (column + 1)]


def _tile_name(column: int, row: int) -> str:
    zoom, x, y, _columns, _rows = GRID
    return f"{zoom}_{x + column}_{y + row}.png"


def _scouts_input_grid(folder: Path, date: str, zoom: int, i: int, j: int):
    """SCOUT's ``load_input_grid`` (``deep_umbra.py`` at b98369e5), reading the
    tile and its neighbours from SCOUT's PNG files, with numpy and Pillow in
    place of its TensorFlow reads: the reference the port's inputs are held to."""
    import numpy as np
    from PIL import Image

    all_input = np.zeros((256 * 3, 256 * 3, 1), dtype=np.float32)
    for x in range(-1, 2):
        for y in range(-1, 2):
            filepath = "%s/%d_%d_%d.png" % (folder, zoom, i + y, j + x)
            if os.path.isfile(filepath):
                with Image.open(filepath) as image:
                    tile = np.asarray(image).reshape(256, 256, 1).astype(np.float32)
                all_input[256 + 256 * x:256 + 256 * (x + 1), 256 + 256 * y:256 + 256 * (y + 1)] = tile
    n = float(2 ** zoom)
    lat_rad = np.arctan(np.sinh(np.float32(3.14159265359 * (1.0 - 2.0 * float(j) / n))))
    latitude = lat_rad / np.float32(0.017453292519943295)
    all_input = all_input[128:-128, 128:-128]
    all_lat = np.full((512, 512, 1), latitude, dtype=np.float32)
    value = 0 if date == "winter" else 1 if date in ("spring", "fall") else 2
    all_date = np.full((512, 512, 1), value, dtype=np.float32)
    return all_input, all_lat, all_date


def _scouts_run_shadow_model(folder: Path, season: str):
    """SCOUT's ``run_shadow_model`` (``deep_umbra.py`` at b98369e5) on the
    height tiles in *folder*, with its ``predict_shadow`` and
    ``normalize_input``, and the ONNX export of its generator in place of the
    TensorFlow one: ``({tile file: its shadow from 0 to 1}, the minutes its
    metrics take)``. It predicts each tile file the folder holds, in name
    order, and its metrics take the ground of those tiles only, the pixels
    whose height level is 0; it writes no file here."""
    import numpy as np

    generator = _session()
    factor = 360 if season == "winter" else 540 if season == "spring" else 720
    shadows, all_vals = {}, []
    for png_path in sorted(folder.glob("*.png")):
        zoom, i, j = (int(part) for part in png_path.stem.split("_"))
        input_height, input_lat, input_date = _scouts_input_grid(folder, season, zoom, i, j)
        input_height = (input_height / 127.5) - 1
        input_lat = ((input_lat + 90) / 90.0) - 1
        input_date = input_date - 1
        concat = [plane.reshape(1, 512, 512, 1) for plane in (input_height, input_lat, input_date)]
        prediction = generator.run(None, dict(zip(("height", "latitude", "date"), concat)))[0]
        prediction = prediction[:, 128:-128, 128:-128, :].reshape(256, 256)
        input_height = concat[0][:, 128:-128, 128:-128, :].reshape(256, 256)
        input_height = (input_height + 1) * 127.5
        arr = prediction
        arr_min, arr_max = float(arr.min()), float(arr.max())
        if arr_max > arr_min:
            arr_norm = (arr - (-1.0)) / (1.0 - (-1.0))
        else:
            arr_norm = np.zeros_like(arr)
        vals = arr_norm[input_height == 0] * factor
        all_vals.append(vals.ravel())
        shadows[png_path.name] = arr_norm
    return shadows, np.concatenate(all_vals)


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


def _with_values(**values) -> list:
    """The manifest's widgets, with *values* set as a user sets them."""
    widgets = [dict(widget) for widget in _template()["widgets"]]
    for widget in widgets:
        if widget["name"] in values:
            widget["value"] = values[widget["name"]]
    return widgets


def _execute(code, value, node_type, workspace, *, data_type, **extra):
    """Run *code* on *value* as a node's play does, in process: the sandbox's
    result. With *data_type* ``outputs``, *value* is one value per input
    circle, each saved as its own upstream output, as a run hands them on."""
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    _worker_init()
    if data_type == "outputs":
        file_path = repr([
            {"path": save_to_duckdb(item, node_id=f"upstream-{slot}"), "dataType": "raster"}
            for slot, item in enumerate(value)
        ])
    else:
        file_path = save_to_duckdb(value, node_id="upstream")
    return execute_code(
        textwrap.indent(code, "    "), file_path, node_type, data_type,
        save_dataset=False, media_dir=str(workspace / "media"), **extra,
    )


def run_node(value, workspace, *, data_type="raster", model=True, models=None, fails=False,
             code=None, widgets=None, **values):
    """Run the node's template (or *code* with *widgets*), its widget at
    *values*, on *value* in the sandbox, in process, with the model resolved
    as the backend resolves it (or, without *model*, as a Curio that could
    not give it does; *models* names the folders instead): ``(artifact id,
    the raster)``, or with *fails* the node's error text."""
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    source = _source() if code is None else code
    code, problems = resolve_references(
        source, _with_values(**values) if widgets is None else widgets, "python", inputs=[{"slot": 0}],
    )
    assert problems == [], problems
    if models is None:
        models = _resolved_models(source) if model else {}
    result = _execute(
        code, value, NODE_TYPE, workspace, data_type=data_type,
        package_modules=SHADOW_MODULES,
        models=models,
    )
    if fails:
        assert result["stderr"], f"the node ran: {result['output']}"
        return result["stderr"]
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "raster", result["output"]
    return result["output"]["path"], load_from_duckdb(result["output"]["path"])


def _dataflow() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]


def _with_range(content: str, color_range: list) -> str:
    """*content*, a map document of one layer, with *color_range* as the
    layer's ``colorMapRange`` after its scheme, written as the Autark node
    writes a document: JSON indented by two spaces."""
    document = json.loads(content)
    (layer,) = document["map"]["layerRefs"]
    ranged = {}
    for key, value in layer.items():
        ranged[key] = value
        if key == "colorMapInterpolator":
            ranged["colorMapRange"] = color_range
    assert "colorMapRange" in ranged, layer
    document["map"]["layerRefs"] = [ranged]
    return json.dumps(document, indent=2)


def _takes_statistics(node: dict) -> bool:
    """Whether *node* is a Raster Calculator whose code returns statistics."""
    return node["type"] == CALCULATOR_TYPE and bool(STATISTICS_CALL.search(node["content"]))


def _statistics_code() -> str:
    """The code of the dataflow's Raster Calculators of statistics (both
    scenarios' are one)."""
    codes = {node["content"] for node in _dataflow()["nodes"] if _takes_statistics(node)}
    assert len(codes) == 1, codes
    return codes.pop()


def statistics_table(shadow, heights, workspace):
    """The dataflow's Raster Calculator of statistics, its code as written, on
    *shadow* (input_0) and *heights* (input_1, the mask): its one-row table."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = _execute(_statistics_code(), (shadow, heights), CALCULATOR_TYPE, workspace, data_type="outputs",
                      package_modules=RASTER_MODULES)
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "dataframe", result["output"]
    table = load_from_duckdb(result["output"]["path"])
    assert list(table.columns) == ["mean", "median", "min", "max", "count"], list(table.columns)
    return table


def run_statistics(shadow, heights, workspace) -> tuple[float, float]:
    """The dataflow's Raster Calculator of statistics on *shadow* and *heights*: ``(mean, median)``."""
    table = statistics_table(shadow, heights, workspace)
    return float(table["mean"].iloc[0]), float(table["median"].iloc[0])


# ---------------------------------------------------------------------------
# The proof
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario", ["A", "B"])
def test_the_mosaic_gives_back_scouts_tiles_and_inputs(tmp_path, scenario):
    """Rasterize Buildings' mosaic of SCOUT's tiles, read as Deep Umbra reads
    it, is SCOUT's tiles gray level for gray level, on SCOUT's tile grid; and
    each tile's neighbourhood gives the generator SCOUT's three inputs, to the
    bit, in each season."""
    import numpy as np

    # The mosaic first: its writer stages Scout's modules, which Deep Umbra's
    # staged modules import too, and one name loads from one place at a time.
    mosaic_path = _mosaic(tmp_path, scenario)
    with shadow_modules(tmp_path) as (deep_umbra, outputs), _open(mosaic_path) as mosaic:
        grid = outputs.tile_grid(mosaic)
        assert grid == GRID, grid
        levels = outputs.gray_levels(mosaic)
        assert levels.dtype == np.float32 and levels.shape == (512, 512)
        padded = np.pad(levels, 256)
        zoom, x, y, columns, rows = grid
        for row in range(rows):
            for column in range(columns):
                name = _tile_name(column, row)
                assert np.array_equal(_block(levels, column, row), _gray(FIXTURES / f"{scenario}_rasters" / name)), name
                for season in ("summer", "spring", "winter"):
                    ours = deep_umbra.load_input_grid(outputs.neighbourhood(padded, column, row), season, zoom, x + column, y + row)
                    scouts = _scouts_input_grid(FIXTURES / f"{scenario}_rasters", season, zoom, x + column, y + row)
                    for plane, mine, theirs in zip(("height", "latitude", "date"), ours, scouts):
                        assert mine.dtype == theirs.dtype == np.float32 and mine.shape == theirs.shape == (512, 512, 1)
                        assert mine.tobytes() == theirs.tobytes(), (name, season, plane)
        # The neighbourhoods are not all ground: every tile sees buildings.
        assert all(_block(levels, c, r).max() > 0 for r in range(rows) for c in range(columns))


def test_every_height_level_comes_back_exactly(tmp_path):
    """Each of the 256 levels Rasterize Buildings writes as metres (level times
    550 over 255, in float32) reads back as that level; level 0, the ground, is
    every height under 1.08 m, the condition the Raster Calculator of
    statistics keeps."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    levels = np.arange(256, dtype=np.float32).reshape(16, 16)
    path = tmp_path / "levels.tif"
    with rasterio.open(path, "w", driver="GTiff", width=16, height=16, count=1, dtype="float32",
                       crs="EPSG:3395", transform=from_origin(0, 0, 1, 1)) as out:
        out.write(levels * np.float32(550.0 / 255.0), 1)
    with shadow_modules(tmp_path) as (_deep_umbra, outputs), rasterio.open(path) as raster:
        assert np.array_equal(outputs.gray_levels(raster), levels)
        heights = raster.read(1)
        assert np.array_equal(heights < 1.08, levels == 0)
    assert "where=lambda height: height < 1.08" in _statistics_code()


@pytest.mark.parametrize("scenario", ["A", "B"])
def test_scouts_rasters_become_scouts_committed_shadows(workspace, tmp_path, scenario, record_property):
    """SCOUT's call, in summer, on the mosaic of SCOUT's committed height tiles:
    each tile's shadow, in the 8 bits SCOUT writes, is SCOUT's committed shadow
    tile; and the dataflow's Raster Calculator of statistics, on the node's
    shadow raster with the mosaic as its mask, gives SCOUT's mean and median, within the
    tolerance. The measured numbers are recorded in the run's JUnit report
    either way, with what the session ran on."""
    import onnxruntime as ort

    heights_path = _mosaic(tmp_path, scenario)
    measured = {}
    with shadow_modules(tmp_path) as (_deep_umbra, outputs), _open(heights_path) as heights:
        shadows = outputs.shadow_tiles(heights, "summer", _model())
        shadow = outputs.accumulated_shadow(heights, "summer", _model(), lambda name: str(tmp_path / name))
    for (column, row), fraction in shadows.items():
        name = _tile_name(column, row)
        measured[name] = _levels((fraction * 255).astype("uint8").astype(int),
                                 _gray(FIXTURES / f"{scenario}_shadows" / name))
    assert sorted(measured) == TILE_NAMES
    with shadow, _open(heights_path) as heights:
        ours = run_statistics(shadow, heights, workspace)
    scouts = _metrics(FIXTURES / f"{scenario}_shadows_metric.csv")
    differences = [abs(a - b) for a, b in zip(ours, scouts)]
    record_property("tiles (largest levels, pixels differing)", json.dumps(measured))
    record_property("metrics (mean, median)", json.dumps({"ours": ours, "scout": scouts, "differences": differences}))
    record_property("onnxruntime", json.dumps({"version": ort.__version__, "cpus": os.cpu_count()}))
    assert _within(measured), (
        f"(largest gray-level difference, pixels that differ) per tile, against at most "
        f"{MAX_LEVELS} levels on {MAX_SHARE:.1%} of {TILE_PIXELS} pixels: {measured}"
    )
    assert _metrics_within(ours, scouts), (
        f"(mean, median) minutes: ours {ours}, SCOUT's {scouts}, differences {differences}, "
        f"against at most ({MAX_MEAN_MINUTES}, {MAX_MEDIAN_MINUTES})"
    )
    # Not blank tiles agreeing: every one of SCOUT's tiles holds full shadow
    # and open ground.
    for name in TILE_NAMES:
        gray = _gray(FIXTURES / f"{scenario}_shadows" / name)
        assert gray.max() >= 250 and (gray < 10).mean() > 0.1, name


def test_on_a_tile_set_with_a_gap_only_the_written_tiles_count_as_in_scouts_function(workspace, tmp_path):
    """SCOUT's committed A tiles without the south-east one: a tile set with a
    gap, as ``convert_raster`` leaves one where no building is near a tile.
    Rasterize Buildings' writer gives the gap no data; the node predicts only
    the three tiles written and gives the gap no shadow; and the dataflow's
    Raster Calculator of statistics counts the ground of the written tiles
    only.

    Against SCOUT's ``run_shadow_model`` on the same three files: each written
    tile's shadow is SCOUT's, cell for cell (both read the gap as ground
    around its neighbours); the ground count is SCOUT's exactly; and the mean
    and median are SCOUT's, but for SCOUT summing in float32 where the
    statistics sum in float64. Filled as ground, the gap's 65,536 cells
    would count too."""
    import shutil

    import numpy as np

    gap = _tile_name(1, 1)
    folder = tmp_path / "A_rasters_with_a_gap"
    folder.mkdir()
    for name in TILE_NAMES:
        if name != gap:
            shutil.copy(FIXTURES / "A_rasters" / name, folder / name)
    scouts_shadows, scouts_ground = _scouts_run_shadow_model(folder, "summer")
    assert sorted(scouts_shadows) == sorted(set(TILE_NAMES) - {gap})

    heights_path = _mosaic_of(tmp_path, folder, "mosaic-with-a-gap")
    with _open(heights_path) as heights:
        assert (heights.width, heights.height) == (512, 512)
        assert np.isnan(_block(heights.read(1), 1, 1)).all(), (
            f"the gap {gap} holds heights, as if Rasterize Buildings had written it"
        )
    _art_id, shadow = run_node(_open(heights_path), workspace)
    try:
        with _open(heights_path) as heights:
            assert (shadow.crs, shadow.transform, shadow.width, shadow.height) == (
                heights.crs, heights.transform, heights.width, heights.height,
            )
        cells = shadow.read(1)
        for row in range(2):
            for column in range(2):
                name = _tile_name(column, row)
                block = _block(cells, column, row)
                if name == gap:
                    assert np.isnan(block).all(), f"the gap {gap} has a shadow, and SCOUT predicts no tile there"
                else:
                    assert np.array_equal(block, scouts_shadows[name] * np.float32(720)), name
        with _open(heights_path) as heights:
            table = statistics_table(shadow, heights, workspace)
    finally:
        shadow.close()
    ours = {key: float(table[key].iloc[0]) for key in ("count", "mean", "median")}
    scouts = {"count": float(scouts_ground.size), "mean": float(np.mean(scouts_ground)),
              "median": float(np.median(scouts_ground))}
    assert ours["count"] == scouts["count"], f"ground cells counted: ours {ours}, SCOUT's {scouts}"
    assert 3 * 256 * 256 * 0.1 < ours["count"] < 3 * 256 * 256, ours
    assert abs(ours["mean"] - scouts["mean"]) <= 1e-3, (ours, scouts)
    assert abs(ours["median"] - scouts["median"]) <= 1e-3, (ours, scouts)


def test_the_model_is_the_export_of_scouts_generator():
    """The committed file is what the export script wrote, and reads and writes
    what the port feeds it: three (1, 512, 512, 1) planes, one tile at a time."""
    assert hashlib.sha256(MODEL.read_bytes()).hexdigest() == MODEL_SHA256
    session = _session()
    assert [(i.name, i.shape, i.type) for i in session.get_inputs()] == [
        (name, [1, 512, 512, 1], "tensor(float)") for name in ("height", "latitude", "date")
    ]
    assert [(o.name, o.shape, o.type) for o in session.get_outputs()] == [
        ("shadow", [1, 512, 512, 1], "tensor(float)")
    ]
    # The package's model block says how to run them: an image-to-image graph
    # on 512 by 512 NHWC float32 planes, which the node feeds itself.
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    manifest = load_package_manifest(PACKAGE)
    block = manifest.model
    assert (manifest.package_id, manifest.kind, block.runtime, block.type, block.entry) == (
        MODEL_ID, "model", "onnx", "image-to-image", "models/deep_umbra.onnx",
    )
    assert (block.input.width, block.input.height, block.input.dtype, block.input.layout) == (
        512, 512, "float32", "NHWC",
    )
    assert block.labels == ()
    assert block.size_bytes == MODEL.stat().st_size


def test_the_weights_stay_out_of_the_pip_package(monkeypatch):
    """``MANIFEST.in`` ships ``packages/`` in the sdist, which the wheel is built
    from (``publish-pip-to-pypi.yml``), and ``setup.py``'s ``egg_info`` leaves
    out Deep Umbra's weights, which its manifest names in
    ``downloadOnFirstUse``: they stay in the repository, and a pip install
    downloads them the first time the node runs. The rest of the package
    ships, so a pip install lists the model and has its node. The rules are
    applied the way setuptools applies them, every line in order, then
    ``setup.py``'s step, to the files under ``packages/``, ``models/`` and
    ``datasets/``: of the packages' and models' files only Deep Umbra's weights
    stay out, and the weather GNN's weights, DDRNet23-Slim's graph and the
    buildings dataset still ship."""
    from setuptools._distutils.filelist import FileList

    monkeypatch.chdir(REPO)
    files = FileList()
    files.set_allfiles(sorted(
        path.relative_to(REPO).as_posix()
        for folder in ("packages", "models", "datasets") for path in (REPO / folder).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ))
    for line in (REPO / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            files.process_template_line(line)
    spec = importlib.util.spec_from_file_location("_curio_setup", REPO / "setup.py")
    setup_py = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup_py)
    setup_py.leave_out_first_use_files(files)
    shipped = set(files.files)
    weights = MODEL.relative_to(REPO).as_posix()
    assert weights in files.allfiles
    assert [
        path for path in files.allfiles if path.startswith(("packages/", "models/")) and path not in shipped
    ] == [weights]
    for rel in ("manifest.json", "integrity.json", "sources/accumulated-shadow.py", "sources/deep_umbra/node_outputs.py"):
        assert (PACKAGE / rel).relative_to(REPO).as_posix() in shipped, rel
    # The rest still ships: the weather GNN's weights, DDRNet23-Slim's graph
    # and the buildings dataset.
    assert "packages/model.scout.weather-gnn@1/models/weather_gnn.onnx" in shipped
    assert "packages/model.curio.ddrnet23-slim@1/models/ddrnet23_slim.onnx" in shipped
    assert BUILDINGS.relative_to(REPO).as_posix() in shipped


def test_the_package_is_a_model_package_whose_code_and_weights_have_their_own_licenses():
    """The package's license is its code's, MIT, published by Curio, which
    ported it; its model block holds the weights' license, SCOUT's permission,
    with SCOUT as their publisher. It is read-only, it validates against the
    node-package schema, and the package and Model Catalog folders it replaces
    are gone."""
    from jsonschema import Draft202012Validator

    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    schema = json.loads((REPO / "docs" / "schemas" / "node-package.v4.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(_manifest())
    manifest = load_package_manifest(PACKAGE)
    assert (manifest.package_id, manifest.kind, manifest.license, manifest.publisher, manifest.read_only) == (
        MODEL_ID, "model", "MIT", "Curio", True,
    )
    block = manifest.model
    assert (block.license, block.publisher, block.homepage) == (WEIGHTS_LICENSE, WEIGHTS_PUBLISHER, SCOUT)
    # The date the catalogs show: the day SCOUT's ports and models shipped.
    assert _manifest()["createdAt"] == "2026-10-05T00:00:00Z"
    assert not (REPO / "packages" / "scout.shadow@1").exists()
    assert not (REPO / "models" / f"{MODEL_ID}@1").exists()


# ---------------------------------------------------------------------------
# The template
# ---------------------------------------------------------------------------

def test_the_template_reads_the_season_and_loads_the_model_by_its_id():
    """A raster in, a raster out; the season is SCOUT's three choices, drawn as
    radio buttons; the cell is three lines: the module's call, the model named
    by its id in a literal ``curio_load_model`` call the backend resolves before
    the run, and the call on the input with the Season widget."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code, model_ids_in_code

    assert _source() == CELL
    template = _template()
    assert template["inputPorts"] == [{"cardinality": "1", "types": ["RASTER"]}]
    assert template["outputPorts"] == [{"cardinality": "1", "types": ["RASTER"]}]
    assert template["hasWidgets"] is True
    assert template["widgets"] == [{
        "name": "season", "type": "choice", "label": "Season", "default": "summer",
        "options": {"choices": ["spring", "summer", "winter"], "display": "radio"},
    }]
    source = _source()
    assert re.findall(r"\[!!\s*(@?\w+)\s*!!\]", source) == ["season"]
    assert model_ids_in_code(source) == [MODEL_ID]
    assert dataset_ids_in_code(source) == []
    assert _manifest()["dependencies"]["python"] == {
        "numpy": "", "onnxruntime": ">=1.17", "pyproj": ">=3.7.2", "rasterio": ">=1.4",
    }


def test_its_module_is_deep_umbra_and_exports_the_cells_call(tmp_path):
    """The plumbing is the package's one module, ``deep_umbra``: SCOUT's
    functions (``deep_umbra.py``) and the node's input and output
    (``node_outputs.py``), with ``accumulated_shadow``, which the cell imports,
    exported by the module itself. A missing model is ``curio_load_model``'s
    to say, not the module's."""
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.repositories.python_modules import module_names

    assert module_names(PACKAGE, load_package_manifest(PACKAGE)) == frozenset({MODULE})
    assert sorted(path.name for path in (SOURCES / MODULE).glob("*.py")) == [
        "__init__.py", "deep_umbra.py", "node_outputs.py",
    ]
    with staged(tmp_path, SOURCES, MODULE, "node_outputs", also=[RASTER_MODULES]) as (outputs,):
        package = importlib.import_module(MODULE)
        assert package.accumulated_shadow is outputs.accumulated_shadow
        assert not hasattr(outputs, "open_model") and not hasattr(outputs, "MISSING_MODEL")


def test_the_package_writes_its_raster_with_curios_mosaic_helper():
    """The shadow raster is written by Curio's mosaic helper, and its tiles
    placed by Scout's tile bounds, which the package names in
    ``dependencies.packages``: not a copy of either in the package."""
    modules = (SOURCES / MODULE).glob("*.py")
    text = "\n".join(path.read_text(encoding="utf-8") for path in modules)
    assert "from utk_curio.sandbox.util.rasters import mosaic_rasters\n" in text
    assert "from scout_rasters.web_tiles import tile_bounds\n" in text
    assert _manifest()["dependencies"]["packages"] == {RASTER_PACKAGE.name: "*"}
    assert "rasterio.open(path, \"w\"" not in text and "Window(" not in text
    assert "def write_mosaic" not in text and "def tile_bounds" not in text


# ---------------------------------------------------------------------------
# The node, in the sandbox
# ---------------------------------------------------------------------------

def test_the_node_returns_the_shadow_raster_on_its_inputs_grid(workspace, tmp_path):
    """The mosaic of SCOUT's A tiles in: a raster in minutes on the input's own
    grid, each tile the port's shadow times summer's 720 minutes."""
    import numpy as np
    import rasterio

    path = _mosaic(tmp_path, "A")
    _art_id, shadow = run_node(_open(path), workspace)
    try:
        assert isinstance(shadow, rasterio.io.DatasetReader)
        with _open(path) as heights:
            assert (shadow.crs, shadow.transform, shadow.width, shadow.height) == (
                heights.crs, heights.transform, heights.width, heights.height,
            )
        assert (shadow.count, shadow.dtypes[0]) == (1, "float32")
        # NaN names the nodata, as Curio's raster tools write it: a GeoTIFF that
        # names none is read by autk-db with 0 as its nodata, and every cell in
        # the sun would drop out of an Autark map and a Compare Scenarios Difference.
        assert shadow.nodata is not None and np.isnan(shadow.nodata), shadow.nodata
        assert shadow.tags()["season"] == "summer" and shadow.tags()["minutes"] == "720"
        cells = shadow.read(1)
        with shadow_modules(tmp_path) as (_deep_umbra, outputs), _open(path) as heights:
            fractions = outputs.shadow_tiles(heights, "summer", _model())
        assert sorted(fractions) == [(0, 0), (0, 1), (1, 0), (1, 1)]
        for (column, row), fraction in fractions.items():
            assert np.array_equal(_block(cells, column, row), fraction * np.float32(720)), (column, row)
    finally:
        shadow.close()


def test_the_raster_is_one_the_autark_node_loads(workspace, tmp_path):
    """What #718's raster route serves for the node's output: an EPSG CRS, a
    north-up grid, inside the Autark node's caps."""
    from rasterio.io import MemoryFile

    from utk_curio.sandbox.util.rasters import serve_raster

    art_id, shadow = run_node(_open(_mosaic(tmp_path, "A")), workspace)
    try:
        payload, meta = serve_raster(art_id, max_cells=2048 * 2048, max_side=8192)
        assert meta["crs"] == "EPSG:3395"
        a, b, c, d, e, f = meta["transform"]
        assert b == 0 and d == 0 and a > 0 and e < 0
        assert (meta["width"], meta["height"], meta["count"]) == (512, 512, 1)
        with MemoryFile(payload) as memory, memory.open() as served:
            assert served.crs == shadow.crs and served.transform == shadow.transform
            assert (served.read(1) == shadow.read(1)).all()
    finally:
        shadow.close()


def test_the_season_reaches_the_call(workspace, tmp_path):
    """Each season its own sun and its own minutes: winter counts 360 for a day
    in shadow, spring 540, summer 720."""
    import numpy as np

    path = _mosaic(tmp_path, "A")
    results = {}
    for season in ("winter", "spring", "summer"):
        _art_id, shadow = run_node(_open(path), workspace, season=season)
        try:
            # Scout's statistics, staged after the node's run, which stages its own.
            (tmp_path / season).mkdir()
            with staged(tmp_path / season, RASTER_PACKAGE / "sources", RASTER_MODULE, "raster_algebra") as (algebra,), \
                    _open(path) as heights:
                statistics = algebra.raster_statistics
                mean = float(statistics((shadow, heights), where=lambda height: height < 1.08)["mean"].iloc[0])
            results[season] = (float(np.nanmax(shadow.read(1))), mean, shadow.tags()["season"], shadow.tags()["minutes"])
        finally:
            shadow.close()
    for season, minutes in (("winter", 360), ("spring", 540), ("summer", 720)):
        top, mean, named, tagged = results[season]
        assert named == season and tagged == str(minutes), results
        assert 0.5 * minutes < top <= minutes + 1e-3, results
    means = [results[season][1] for season in ("winter", "spring", "summer")]
    assert len(set(round(m, 3) for m in means)) == 3, results


def test_the_node_reads_the_rasterizers_one_raster_and_checks_its_height_scale(tmp_path):
    """Wired straight to Rasterize Buildings, the node reads the one raster it
    returns; a raster with a table beside it is not a height raster and is
    refused in a sentence; and a raster drawn with a maximum height other than
    the 550 m Deep Umbra needs is refused in a sentence."""
    import pandas as pd

    # The mosaics first: their writer stages Scout's modules, which Deep
    # Umbra's staged modules import too, and one name loads from one place at a time.
    mosaic_path, too_low_path = _mosaic(tmp_path, "A"), _mosaic(tmp_path, "A", max_height=275)
    with shadow_modules(tmp_path) as (_deep_umbra, outputs):
        with _open(mosaic_path) as mosaic:
            assert outputs.height_raster(mosaic) is mosaic
            assert outputs.gray_levels(mosaic).max() > 0
            table = pd.DataFrame({"zoom": [16], "x": [16814], "y": [24355]})
            for value in ((mosaic, table), [mosaic, table], table):
                with pytest.raises(ValueError, match="Accumulated Shadow reads a raster of building heights"):
                    outputs.height_raster(value)
        with _open(too_low_path) as mosaic:
            with pytest.raises(ValueError, match="Set Rasterize Buildings' Maximum height to 550"):
                outputs.gray_levels(mosaic)


def _off_grid(tmp_path, change: str):
    """The mosaic of SCOUT's A tiles, rewritten with one thing changed."""
    import rasterio
    from rasterio.transform import Affine

    with _open(_mosaic(tmp_path, "A")) as mosaic:
        cells, crs, transform = mosaic.read(1), mosaic.crs, mosaic.transform
    a, b, c, d, e, f = tuple(transform)[:6]
    if change == "corner":
        transform = Affine(a, b, c + a / 2, d, e, f)
    elif change == "crs":
        crs = "EPSG:4326"
    elif change == "size":
        cells = cells[:, :500]
    path = tmp_path / f"off-grid-{change}.tif"
    profile = {"driver": "GTiff", "width": cells.shape[1], "height": cells.shape[0], "count": 1,
               "dtype": "float32", "crs": crs, "transform": transform}
    with rasterio.open(path, "w", **profile) as out:
        out.write(cells, 1)
    return _open(path)


@pytest.mark.parametrize(
    "change, sentence",
    [
        ("zoom 15", "Deep Umbra reads zoom-16 tiles, and this raster is at zoom 15"),
        ("not a raster", "Accumulated Shadow reads a raster of building heights"),
        ("crs", "Deep Umbra reads heights in EPSG:3395 (World Mercator) on SCOUT's tile grid, and this raster is in EPSG:4326"),
        ("corner", "This one's corner is not a tile's corner"),
        ("size", "This one is not a whole number of tiles"),
    ],
)
def test_rasters_deep_umbra_cannot_read_are_refused_in_a_sentence(workspace, tmp_path, change, sentence):
    import pandas as pd

    if change == "zoom 15":
        value = _open(_mosaic(tmp_path, "A", zoom=15))
    elif change == "not a raster":
        value = pd.DataFrame({"zoom": [16], "x": [16814], "y": [24355], "png": [""]})
    else:
        value = _off_grid(tmp_path, change)
    data_type = "dataframe" if change == "not a raster" else "raster"
    error = run_node(value, workspace, data_type=data_type, fails=True)
    assert sentence in error, error


def test_a_curio_without_the_model_says_where_it_comes_from(workspace, tmp_path):
    """When the backend resolves no folder for the model (one never added, or a
    pip install that could not download its weights), ``curio_load_model``
    names the model, says to add it with the Model Catalog's Add, and where a
    model that ships with Curio comes from: a pip install downloads its
    weights from GitHub the first time a node runs it, and a clone holds them
    in ``packages/``. Copying folders by hand is not one of the ways."""
    error = run_node(_open(_mosaic(tmp_path, "A")), workspace, model=False, fails=True)
    for words in (
        f"Model '{MODEL_ID}' is not one of your models: add it with Add in the Model Catalog",
        "this Curio could not give it to the node",
        "A pip install downloads",
        "from GitHub the first time a node runs it",
        "raw.githubusercontent.com",
        "a clone of https://github.com/urban-toolkit/curio holds them in packages/",
    ):
        assert words in error, error
    assert "copy the repository's folder" not in error, error


def test_another_failure_to_load_the_model_keeps_its_own_sentence(workspace, tmp_path):
    """Only a model the backend gave no folder reads as missing: a folder
    whose manifest cannot be read keeps its own sentence."""
    unreadable = tmp_path / "no-manifest"
    unreadable.mkdir()
    error = run_node(_open(_mosaic(tmp_path, "A")), workspace, models={MODEL_ID: str(unreadable)}, fails=True)
    assert f"Model '{MODEL_ID}' has no readable manifest" in error, error
    assert "this Curio could not give it to the node" not in error, error


# ---------------------------------------------------------------------------
# The shipped dataflow
# ---------------------------------------------------------------------------

def test_the_shipped_dataflow_runs_the_packages_as_the_palette_drops_them():
    """``chicago-loop-shadow-towers.json`` is how its CI run reaches this package: its nodes
    hold the templates' own sources and widgets, the shadow nodes reading the
    season from the one Parameter node both scenarios share; each scenario's
    Raster Calculator of statistics reads its shadow on input_0 and its
    heights, the mask, on input_1, straight from Rasterize Buildings, which feeds the
    shadow node too; each scenario maps its own shadow, with example 24's map;
    the chart reads the statistics, the difference the shadows, and an Autark
    map after the difference, in no scenario, draws the change in shadow.
    The model is no dataset of the dataflow: the shadow nodes' code names it by
    id, and the lockfile names its package, so opening the dataflow adds it."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code, model_ids_in_code

    spec = _dataflow()
    assert spec["packages"] == ["curio.scout@1", f"{MODEL_ID}@1"]
    assert [ref["datasetId"] for ref in spec["datasets"]] == ["data.scout.loop-buildings"]
    nodes = {node["id"]: node for node in spec["nodes"]}
    by_type: dict[str, list] = {}
    for node in spec["nodes"]:
        by_type.setdefault(node["type"], []).append(node)

    (raster_template,) = [
        t for t in json.loads((RASTER_PACKAGE / "manifest.json").read_text(encoding="utf-8"))["templates"]
        if t["id"] == "rasterize-buildings"
    ]
    raster_source = (RASTER_PACKAGE / raster_template["source"]).read_text(encoding="utf-8")
    rasterizers = by_type[RASTERIZE_TYPE]
    assert len(rasterizers) == 2
    for node in rasterizers:
        assert node["content"] == raster_source
        assert node["metadata"]["widgets"] == raster_template["widgets"]

    shadows = by_type[NODE_TYPE]
    assert len(shadows) == 2
    for node in shadows:
        assert node["content"] == _source().replace("[!! season !!]", "[!! @season !!]")
        assert not node["metadata"].get("widgets")
        assert model_ids_in_code(node["content"]) == [MODEL_ID]
        assert dataset_ids_in_code(node["content"]) == []
    (parameter,) = by_type["curio.builtin/parameter"]
    assert parameter["metadata"]["widgets"] == _template()["widgets"]

    (loader,) = by_type["curio.builtin/data-loading"]
    assert dataset_ids_in_code(loader["content"]) == ["data.scout.loop-buildings"]

    into = {(edge["target"], edge["targetHandle"]): edge["source"] for edge in spec["edges"]}
    statistics = by_type[CALCULATOR_TYPE]
    assert len(statistics) == 2 and all(_takes_statistics(node) for node in statistics)
    for node in statistics:
        shadow, heights = nodes[into[(node["id"], "in")]], nodes[into[(node["id"], "in_1")]]
        assert shadow["type"] == NODE_TYPE
        assert heights["type"] == RASTERIZE_TYPE
        assert into[(shadow["id"], "in")] == heights["id"]
    assert "curio.builtin/computation-analysis" not in by_type, "a node still picks a part of the rasterizer's output"

    # Each scenario's shadow on a map of its own: example 24's shadow map, over
    # the range both scenarios' maps share, fed by the scenario's Accumulated
    # Shadow and inside the scenario.
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))["dataflow"]
    example_into = {(edge["target"], edge["targetHandle"]): edge["source"] for edge in example["edges"]}
    example_types = {node["id"]: node["type"] for node in example["nodes"]}
    (shadow_map,) = [node for node in example["nodes"] if node["type"] == "curio.builtin/autk-grammar"
                     and example_types[example_into[(node["id"], "in")]] == NODE_TYPE]
    assert len(by_type["curio.builtin/autk-grammar"]) == 3
    for scenario in spec["scenarios"]:
        members = set(scenario["nodes"])
        (shadow_id,) = [n for n in members if nodes[n]["type"] == NODE_TYPE]
        maps = [n for n in members if nodes[n]["type"] == "curio.builtin/autk-grammar"]
        assert len(maps) == 1, (scenario["name"], maps)
        assert into[(maps[0], "in")] == shadow_id, scenario["name"]
        assert nodes[maps[0]]["content"] == _with_range(shadow_map["content"], SHADOW_RANGE), scenario["name"]
    chart, difference = sorted(by_type["curio.builtin/compare-scenarios"],
                               key=lambda n: n["metadata"]["compareScenarios"]["mode"])
    assert chart["metadata"]["compareScenarios"]["mode"] == "chart"
    assert chart["metadata"]["compareScenarios"]["chart"]["y"] == "mean"
    assert {nodes[into[(chart["id"], h)]]["type"] for h in ("in", "in_1")} == {CALCULATOR_TYPE}
    assert all(_takes_statistics(nodes[into[(chart["id"], h)]]) for h in ("in", "in_1"))
    assert {nodes[into[(difference["id"], h)]]["type"] for h in ("in", "in_1")} == {NODE_TYPE}

    # The difference draws no map of its own: an Autark map after it, in no
    # scenario, draws the change in shadow on a scale centered on no change,
    # valid for the grammar.
    from utk_curio.backend.app.agents.domain import document_validation

    members = {node_id for scenario in spec["scenarios"] for node_id in scenario["nodes"]}
    (difference_map,) = [n for n in by_type["curio.builtin/autk-grammar"] if n["id"] not in members]
    assert into[(difference_map["id"], "in")] == difference["id"]
    assert [e["sourceHandle"] for e in spec["edges"] if e["target"] == difference_map["id"]] == ["out"]
    assert json.loads(difference_map["content"]) == DIFFERENCE_MAP_DOCUMENT, difference_map["content"]
    named = difference_map["content"].replace("[!! input_0 !!]", "input_0")
    assert document_validation.validate(
        "curio.builtin/autk-grammar", named,
    ) == {"status": document_validation.STATUS_VALID}


def test_both_scenarios_shadow_maps_share_one_color_range_up_to_the_longest_shadow(tmp_path):
    """The two scenarios' shadow maps color over one range, so a color is the
    same minutes of shadow on both: each holds the same ``colorMapRange``, from
    0 to the most minutes Deep Umbra's output stands for in any season, a cell
    in shadow all day in summer. Valid for the grammar."""
    from utk_curio.backend.app.agents.domain import document_validation

    spec = _dataflow()
    nodes = {node["id"]: node for node in spec["nodes"]}
    ranges = {}
    for scenario in spec["scenarios"]:
        (map_id,) = [n for n in scenario["nodes"] if nodes[n]["type"] == "curio.builtin/autk-grammar"]
        content = nodes[map_id]["content"]
        (layer,) = json.loads(content)["map"]["layerRefs"]
        ranges[scenario["id"]] = layer.get("colorMapRange")
        named = content.replace("[!! input_0 !!]", "input_0")
        assert document_validation.validate(
            "curio.builtin/autk-grammar", named,
        ) == {"status": document_validation.STATUS_VALID}
    assert ranges == {"existing": SHADOW_RANGE, "towers-removed": SHADOW_RANGE}, ranges
    with shadow_modules(tmp_path) as (deep_umbra, node_outputs):
        longest = max(deep_umbra.season_factor(season) for season in node_outputs.SEASONS)
    assert SHADOW_RANGE == [0, longest]


def test_example_24_holds_the_node_as_the_palette_drops_it_and_its_code_runs(workspace, tmp_path):
    """Example 24's Accumulated Shadow node is the template as dropped: the
    three-line cell and the Season widget. Its lockfile names the model
    package beside the rasterizer's, so opening the example adds the model.
    Its code, run with its widget as saved, gives summer's shadow."""
    from utk_curio.backend.app.datasets.domain.code_refs import model_ids_in_code

    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))["dataflow"]
    assert spec["packages"] == ["curio.scout@1", f"{MODEL_ID}@1"]
    (node,) = [node for node in spec["nodes"] if node["type"] == NODE_TYPE]
    assert node["content"] == _source() == CELL
    assert node["metadata"]["widgets"] == _template()["widgets"]
    assert model_ids_in_code(node["content"]) == [MODEL_ID]
    _art_id, shadow = run_node(
        _open(_mosaic(tmp_path, "A")), workspace, code=node["content"], widgets=node["metadata"]["widgets"],
    )
    try:
        assert (shadow.tags()["season"], shadow.tags()["minutes"]) == ("summer", "720")
    finally:
        shadow.close()


def test_example_24_feeds_the_rasterizers_one_raster_to_the_node_and_the_mask():
    """Example 24's Rasterize Buildings feeds its one raster straight to the
    height map, to Accumulated Shadow and to the mask (input_1) of the Raster
    Calculator of statistics, with no node in between; the statistics read the
    shadow on input_0, and a map draws the shadow."""
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))["dataflow"]
    nodes = {node["id"]: node for node in spec["nodes"]}
    into = {(edge["target"], edge["targetHandle"]): edge["source"] for edge in spec["edges"]}
    out_of: dict[str, list[str]] = {}
    for edge in spec["edges"]:
        out_of.setdefault(edge["source"], []).append(nodes[edge["target"]]["type"])
    (rasterizer,) = [n for n, node in nodes.items() if node["type"] == RASTERIZE_TYPE]
    (shadow,) = [n for n, node in nodes.items() if node["type"] == NODE_TYPE]
    (statistics,) = [n for n, node in nodes.items() if node["type"] == CALCULATOR_TYPE]
    assert _takes_statistics(nodes[statistics])
    assert sorted(out_of[rasterizer]) == sorted(["curio.builtin/autk-grammar", NODE_TYPE, CALCULATOR_TYPE])
    assert into[(shadow, "in")] == rasterizer
    assert (into[(statistics, "in")], into[(statistics, "in_1")]) == (shadow, rasterizer)
    assert sorted(out_of[shadow]) == sorted([CALCULATOR_TYPE, "curio.builtin/autk-grammar"])
    assert "curio.builtin/computation-analysis" not in {node["type"] for node in nodes.values()}


def test_the_two_scenarios_are_scouts_two_building_sets(tmp_path):
    """"Existing" rasterizes the shipped buildings, SCOUT's A. "Towers removed"
    reads them through its Interaction node, its lever: the node's edit log
    holds one removal, labelled, of the 15 buildings SCOUT's B leaves out,
    matched on building_id, and its code is the code the node writes from that
    log. Run as the node runs, that code leaves SCOUT's B. Each layer, read as
    Rasterize Buildings reads it, gives the height tiles SCOUT committed for
    it, so the dataflow's two shadow runs are the proof's two."""
    import geopandas as gpd

    spec = _dataflow()
    nodes = {node["id"]: node for node in spec["nodes"]}
    scenarios = {scenario["name"]: scenario for scenario in spec["scenarios"]}
    assert sorted(scenarios) == ["Existing", "Towers removed"]
    types = {name: sorted(nodes[n]["type"] for n in scenario["nodes"]) for name, scenario in scenarios.items()}
    assert types["Towers removed"] == sorted([*types["Existing"], INTERACTION_TYPE]), types
    (lever,) = [nodes[n] for n in scenarios["Towers removed"]["nodes"] if nodes[n]["type"] == INTERACTION_TYPE]
    assert lever["metadata"]["editFeatures"] == TOWERS_LOG, lever["metadata"].get("editFeatures")
    assert lever["content"] == TOWERS_CODE, lever["content"]

    # The lever reads the buildings, the context both scenarios share, and
    # Towers removed's rasterizer reads the lever.
    into = {(edge["target"], edge["targetHandle"]): edge["source"] for edge in spec["edges"]}
    (loader,) = [n for n, node in nodes.items() if node["type"] == "curio.builtin/data-loading"]
    assert into[(lever["id"], "in")] == loader
    (rasterizer,) = [n for n in scenarios["Towers removed"]["nodes"]
                     if nodes[n]["type"] == RASTERIZE_TYPE]
    assert into[(rasterizer, "in")] == lever["id"]

    from utk_curio.sandbox.util.feature_edits import edit_features
    from utk_curio.sandbox.util.input_names import call_as_node

    buildings = gpd.read_file(BUILDINGS)
    assert list(buildings["building_id"]) == list(range(123))
    removed = call_as_node(
        textwrap.indent(lever["content"], "    "), {"curio_edit_features": edit_features}, buildings, [0],
    )
    layers = {"A": buildings, "B": removed}
    assert len(layers["B"]) == 108
    assert sorted(layers["B"]["building_id"]) == sorted(set(range(123)) - set(REMOVED_IDS))

    with staged(tmp_path, RASTER_PACKAGE / "sources", RASTER_MODULE, "convert_to_raster", "node_outputs") as (
        convert, outputs,
    ):
        for scenario, layer in layers.items():
            out = tmp_path / f"{scenario}_rasters"
            # As the node reads a layer: its heights, on a fresh index.
            convert.convert_raster(
                vector_in=outputs.height_layer(layer, "height"), attribute="height", zoom=16, raster_out=str(out),
            )
            assert sorted(p.name for p in out.iterdir()) == TILE_NAMES, scenario
            worst = {name: _levels(_gray(out / name), _gray(FIXTURES / f"{scenario}_rasters" / name))[0]
                     for name in TILE_NAMES}
            assert all(levels <= 1 for levels in worst.values()), (scenario, worst)
