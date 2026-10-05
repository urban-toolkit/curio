"""``scout.shadow@1``: SCOUT's Deep Umbra shadow model in Curio (#662, step 19).

The node reads a height raster, the mosaic of Rasterize Buildings
(``scout.raster-conversion@1``), runs Deep Umbra on every zoom-16 tile of it and
returns the accumulated shadow as a raster on the same grid. SCOUT's metrics,
the mean and median over the ground, are a Raster Statistics node's
(``curio.builtin@1``) with the heights as its mask, as the shipped dataflow
``ScoutShadows.json`` wires it.

The proof starts from SCOUT's own files, copied unchanged into
``fixtures/scout/`` (see its ``ATTRIBUTION.md``): SCOUT's committed height tiles
of both scenarios of its high-rise shadow example become one mosaic each,
written by Rasterize Buildings' own ``write_mosaic``. Then:

- the mosaic gives back SCOUT's tiles, gray level for gray level, and the
  generator's three inputs are the ones SCOUT's file-reading
  ``load_input_grid`` builds, to the bit;
- with the ONNX export of SCOUT's generator that Curio ships (the Model Catalog
  model ``model.scout.deep-umbra@1``), loaded as ``curio_load_model`` loads it,
  in summer, the shadow of each tile, in SCOUT's 8 bits, is SCOUT's committed
  shadow tile;
- the dataflow's Raster Statistics node, run as it is written on the node's
  shadow raster and the mosaic, gives SCOUT's committed mean and median.

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
import json
import os
import re
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "scout.shadow@1"
SOURCES = PACKAGE / "sources"
MODULE = "scout_shadow"
NODE_TYPE = "scout.shadow/accumulated-shadow"
STATISTICS_TYPE = "curio.builtin/raster-statistics"
MODEL_ID = "model.scout.deep-umbra"
MODEL_DIR = REPO / "models" / "model.scout.deep-umbra@1"
MODEL = MODEL_DIR / "files" / "deep_umbra.onnx"
#: The file ``scripts/scout/export_deep_umbra.py`` writes, in the environment its
#: docstring pins.
MODEL_SHA256 = "67afb9d2d56bd0a12164e6e651214d56860ff689728c5b6f29486f21c3cb188e"
BUILDINGS = REPO / "datasets" / "data.scout.loop-buildings@1" / "data" / "loop-buildings.geojson"
DATAFLOW = REPO / "docs" / "examples" / "dataflows" / "ScoutShadows.json"
RASTER_PACKAGE = REPO / "packages" / "scout.raster-conversion@1"
RASTER_MODULE = "scout_raster_conversion"

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
    model's folder, which the backend resolves from the Model Catalog."""
    from utk_curio.sandbox.util.catalog_helpers import CurioModel

    return CurioModel(MODEL_ID, str(MODEL_DIR))


@contextlib.contextmanager
def staged(tmp_path, sources: Path, module: str, *names: str):
    """*module*'s submodules *names*, importable the way a run of the package's
    node imports them: staged into a folder of the run's own."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / f"run-{module}"
    run.mkdir()
    staged_modules = stage_package_modules({"root": str(sources), "names": [module]}, str(run))
    assert staged_modules == {"root": "package_modules", "names": [module]}, staged_modules
    with importable(str(run / staged_modules["root"]), staged_modules["names"]):
        yield tuple(importlib.import_module(f"{module}.{name}") for name in names)


def shadow_modules(tmp_path):
    """``(deep_umbra, node_outputs)``, as the node imports them."""
    return staged(tmp_path, SOURCES, MODULE, "deep_umbra", "node_outputs")


def _mosaic(tmp_path, scenario: str = "A", *, zoom: int = 16, max_height: float = 550) -> Path:
    """SCOUT's committed height tiles of *scenario* as one mosaic, written by
    Rasterize Buildings' own ``write_mosaic``, as its node hands them on. With
    *zoom*, the tiles are named at that zoom level instead."""
    folder = tmp_path / f"mosaic-{scenario}-{zoom}-{max_height:g}"
    folder.mkdir()
    with staged(folder, RASTER_PACKAGE / "sources", RASTER_MODULE, "node_outputs") as (raster_outputs,):
        tiles = raster_outputs.read_tiles(str(FIXTURES / f"{scenario}_rasters")).assign(zoom=zoom)
        return Path(raster_outputs.write_mosaic(tiles, max_height, str(folder / "mosaic.tif")))


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


def run_node(value, workspace, *, data_type="raster", model=True, fails=False, **values):
    """Run the node's template, its widget at *values*, on *value* in the
    sandbox, in process, with the model resolved as the backend resolves it
    (or, without *model*, as a Curio without it does): ``(artifact id, the
    raster)``, or with *fails* the node's error text."""
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    code, problems = resolve_references(_source(), _with_values(**values), "python", inputs=[{"slot": 0}])
    assert problems == [], problems
    result = _execute(
        code, value, NODE_TYPE, workspace, data_type=data_type,
        package_modules={"root": str(SOURCES), "names": [MODULE]},
        models={MODEL_ID: str(MODEL_DIR)} if model else {},
    )
    if fails:
        assert result["stderr"], f"the node ran: {result['output']}"
        return result["stderr"]
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "raster", result["output"]
    return result["output"]["path"], load_from_duckdb(result["output"]["path"])


def _dataflow() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]


def _statistics_code() -> str:
    """The code of the dataflow's Raster Statistics nodes (both scenarios' are one)."""
    codes = {node["content"] for node in _dataflow()["nodes"] if node["type"] == STATISTICS_TYPE}
    assert len(codes) == 1, codes
    return codes.pop()


def run_statistics(shadow, heights, workspace) -> tuple[float, float]:
    """The dataflow's Raster Statistics node, its code as written, on *shadow*
    (input 0) and *heights* (input 1, the mask): ``(mean, median)``."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = _execute(_statistics_code(), (shadow, heights), STATISTICS_TYPE, workspace, data_type="outputs")
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "dataframe", result["output"]
    table = load_from_duckdb(result["output"]["path"])
    assert list(table.columns) == ["mean", "median", "min", "max", "count"], list(table.columns)
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

    with shadow_modules(tmp_path) as (deep_umbra, outputs), _open(_mosaic(tmp_path, scenario)) as mosaic:
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
    every height under 1.08 m, the condition the Raster Statistics node keeps."""
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
    tile; and the dataflow's Raster Statistics node, on the node's shadow raster
    with the mosaic as its mask, gives SCOUT's mean and median, within the
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
    # A Model Catalog model, as Curio's other ONNX models are, that the Model
    # Catalog reads: an image-to-image graph the node feeds itself.
    from utk_curio.backend.app.model_catalog.domain.manifest import load_manifest

    manifest = load_manifest(MODEL_DIR)
    assert (manifest.id, manifest.runtime, manifest.task, manifest.entry) == (
        MODEL_ID, "onnx", "image-to-image", "files/deep_umbra.onnx",
    )
    assert manifest.size_bytes == MODEL.stat().st_size


def test_the_model_stays_out_of_the_pip_package(monkeypatch):
    """``MANIFEST.in`` ships ``models/`` in the sdist, which the wheel is built
    from (``publish-pip-to-pypi.yml``), and leaves Deep Umbra's folder out: it
    stays in the repository only. The rules are applied the way setuptools
    applies them, to the files under ``models/``; the Model Catalog's other
    models still ship, and so does the Data Catalog's buildings dataset."""
    from setuptools._distutils.filelist import FileList

    monkeypatch.chdir(REPO)
    files = FileList()
    files.set_allfiles(sorted(
        path.relative_to(REPO).as_posix()
        for folder in ("models", "datasets") for path in (REPO / folder).rglob("*") if path.is_file()
    ))
    for line in (REPO / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(("include ", "recursive-include models", "prune models",
                            "recursive-include datasets", "prune datasets", "exclude ")):
            files.process_template_line(line)
    shipped = set(files.files)
    model = MODEL.relative_to(REPO).as_posix()
    assert model in files.allfiles
    assert not [path for path in shipped if path.startswith("models/model.scout.deep-umbra@1/")], sorted(shipped)
    # The rest still ships: DDRNet23-Slim's graph and the buildings dataset.
    assert "models/model.curio.ddrnet23-slim@1/files/ddrnet23_slim.onnx" in shipped
    assert BUILDINGS.relative_to(REPO).as_posix() in shipped
    assert len(shipped) == len(files.allfiles) - len([p for p in MODEL_DIR.rglob("*") if p.is_file()])


# ---------------------------------------------------------------------------
# The template
# ---------------------------------------------------------------------------

def test_the_template_reads_the_season_and_loads_the_model_by_its_id():
    """A raster in, a raster out; the season is SCOUT's three choices, drawn as
    radio buttons; the model is named as a literal ``curio_load_model`` call the
    backend resolves from the Model Catalog before the run."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code, model_ids_in_code

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
    assert _manifest()["dependencies"]["python"] == {"onnxruntime": ">=1.17", "rasterio": ">=1.4"}


def test_the_package_writes_its_raster_with_curios_mosaic_helper():
    """The shadow raster is written by Curio's raster helpers, not a copy of
    them in the package."""
    modules = (SOURCES / MODULE).glob("*.py")
    text = "\n".join(path.read_text(encoding="utf-8") for path in modules)
    assert "from utk_curio.sandbox.util.rasters import mosaic_rasters, tile_bounds" in text
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

    from utk_curio.sandbox.util.raster_algebra import statistics

    path = _mosaic(tmp_path, "A")
    results = {}
    for season in ("winter", "spring", "summer"):
        _art_id, shadow = run_node(_open(path), workspace, season=season)
        try:
            with _open(path) as heights:
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


def test_the_rasterizers_tuple_is_read_and_its_height_scale_checked(tmp_path):
    """Wired straight to Rasterize Buildings, the node gets its ``(mosaic,
    tiles)`` and reads the mosaic; a mosaic drawn with a maximum height other
    than the 550 m Deep Umbra needs is refused in a sentence."""
    import pandas as pd

    with shadow_modules(tmp_path) as (_deep_umbra, outputs):
        with _open(_mosaic(tmp_path, "A")) as mosaic:
            tiles = pd.DataFrame({"zoom": [16], "x": [16814], "y": [24355], "png": [""]})
            assert outputs.height_raster([mosaic, tiles]) is mosaic
            assert outputs.height_raster(mosaic) is mosaic
            assert outputs.gray_levels(mosaic).max() > 0
        with _open(_mosaic(tmp_path, "A", max_height=275)) as mosaic:
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


def test_a_curio_without_the_model_says_how_to_add_it(workspace, tmp_path):
    """A pip install has no ``models/model.scout.deep-umbra@1``: the backend
    resolves no folder for the model, and the node says what to copy where."""
    error = run_node(_open(_mosaic(tmp_path, "A")), workspace, model=False, fails=True)
    for words in (
        "the Model Catalog model model.scout.deep-umbra@1, and this Curio does not have it",
        "not in the pip package",
        "copy the repository's folder models/model.scout.deep-umbra@1",
        "--models-root",
    ):
        assert words in error, error


def test_another_failure_to_open_the_model_is_not_hidden(tmp_path):
    """Only a missing model reads as missing: a model folder with no readable
    manifest, say, keeps its own sentence, and so does another model missing
    (one dragged onto the node in Deep Umbra's place)."""
    with shadow_modules(tmp_path) as (_deep_umbra, outputs):
        def unreadable():
            raise RuntimeError("Model 'model.scout.deep-umbra' has no readable manifest: [Errno 2] No such file")

        with pytest.raises(RuntimeError, match="no readable manifest") as raised:
            outputs.open_model(unreadable)
        assert "pip package" not in str(raised.value)

        def another():
            raise RuntimeError("Model 'imported.x1f3a9c2b7d40' is not available in this environment - "
                               "drag a model from the Model Catalog onto this node, then run it again.")

        with pytest.raises(RuntimeError, match="imported.x1f3a9c2b7d40") as raised:
            outputs.open_model(another)
        assert "pip package" not in str(raised.value)


# ---------------------------------------------------------------------------
# The shipped dataflow
# ---------------------------------------------------------------------------

def test_the_shipped_dataflow_runs_the_packages_as_the_palette_drops_them():
    """``ScoutShadows.json`` is how its CI run reaches this package: its nodes
    hold the templates' own sources and widgets, the shadow nodes reading the
    season from the one Parameter node both scenarios share; each scenario's
    Raster Statistics node reads its shadow on input 0 and its heights, the
    mask, on input 1; the chart reads the statistics, the difference the shadows.
    The model is no dataset of the dataflow: the shadow nodes' code names it,
    and the Model Catalog holds it."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code, model_ids_in_code

    spec = _dataflow()
    assert spec["packages"] == ["scout.raster-conversion@1", "scout.shadow@1"]
    assert [ref["datasetId"] for ref in spec["datasets"]] == ["data.scout.loop-buildings"]
    nodes = {node["id"]: node for node in spec["nodes"]}
    by_type: dict[str, list] = {}
    for node in spec["nodes"]:
        by_type.setdefault(node["type"], []).append(node)

    (raster_template,) = json.loads((RASTER_PACKAGE / "manifest.json").read_text(encoding="utf-8"))["templates"]
    raster_source = (RASTER_PACKAGE / raster_template["source"]).read_text(encoding="utf-8")
    rasterizers = by_type["scout.raster-conversion/rasterize-buildings"]
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
    statistics = by_type[STATISTICS_TYPE]
    assert len(statistics) == 2
    for node in statistics:
        shadow, heights = nodes[into[(node["id"], "in")]], nodes[into[(node["id"], "in_1")]]
        assert shadow["type"] == NODE_TYPE
        assert heights["type"] == "curio.builtin/computation-analysis"
        assert into[(shadow["id"], "in")] == heights["id"]
        assert nodes[into[(heights["id"], "in")]]["type"] == "scout.raster-conversion/rasterize-buildings"
        assert heights["content"].rstrip().endswith("return arg[0]")
    chart, difference = sorted(by_type["curio.builtin/compare-scenarios"],
                               key=lambda n: n["metadata"]["compareScenarios"]["mode"])
    assert chart["metadata"]["compareScenarios"]["mode"] == "chart"
    assert chart["metadata"]["compareScenarios"]["chart"]["y"] == "mean"
    assert {nodes[into[(chart["id"], h)]]["type"] for h in ("in", "in_1")} == {STATISTICS_TYPE}
    assert {nodes[into[(difference["id"], h)]]["type"] for h in ("in", "in_1")} == {NODE_TYPE}


def test_the_two_scenarios_are_scouts_two_building_sets(tmp_path):
    """"Existing" rasterizes the shipped buildings, SCOUT's A; "Towers removed"
    runs its node's code first, which leaves SCOUT's B. Each gives the height
    tiles SCOUT committed for it, so the dataflow's two shadow runs are the
    proof's two."""
    import geopandas as gpd

    spec = _dataflow()
    nodes = {node["id"]: node for node in spec["nodes"]}
    scenarios = {scenario["name"]: scenario for scenario in spec["scenarios"]}
    assert sorted(scenarios) == ["Existing", "Towers removed"]
    types = {name: sorted(nodes[n]["type"] for n in scenario["nodes"]) for name, scenario in scenarios.items()}
    assert types["Towers removed"] == sorted([*types["Existing"], "curio.builtin/data-transformation"]), types
    (remove,) = [nodes[n] for n in scenarios["Towers removed"]["nodes"]
                 if nodes[n]["type"] == "curio.builtin/data-transformation"]
    assert f"REMOVED = {REMOVED_IDS}" in remove["content"]

    namespace: dict = {}
    exec("def remove(arg):\n" + textwrap.indent(remove["content"], "    "), namespace)
    buildings = gpd.read_file(BUILDINGS)
    assert list(buildings["building_id"]) == list(range(123))
    layers = {"A": buildings, "B": namespace["remove"](buildings)}
    assert len(layers["B"]) == 108

    with staged(tmp_path, RASTER_PACKAGE / "sources", RASTER_MODULE, "convert_to_raster") as (convert,):
        for scenario, layer in layers.items():
            out = tmp_path / f"{scenario}_rasters"
            convert.convert_raster(vector_in=layer, attribute="height", zoom=16, raster_out=str(out))
            assert sorted(p.name for p in out.iterdir()) == TILE_NAMES, scenario
            worst = {name: _levels(_gray(out / name), _gray(FIXTURES / f"{scenario}_rasters" / name))[0]
                     for name in TILE_NAMES}
            assert all(levels <= 1 for levels in worst.values()), (scenario, worst)
