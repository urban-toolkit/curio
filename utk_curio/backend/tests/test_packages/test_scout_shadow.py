"""``scout.shadow@1``: SCOUT's Deep Umbra shadow model in Curio (#662, step 19).

The package's ``deep_umbra.py`` is SCOUT's, but for the lines marked
``# Curio:``: TensorFlow's calls are numpy's and OpenCV's, the generator is the
ONNX export of SCOUT's (the Model Catalog model ``model.scout.deep-umbra@1``,
run with onnxruntime as it is), and the output folder is the one
``curio_save_folder`` gives. Its ``run_shadow_model`` reads the zoom-16 height
tiles Rasterize Buildings (``scout.raster-conversion@1``) saved in the dataflow
writes SCOUT's shadow tiles and returns SCOUT's metrics, where SCOUT saves them
as a CSV. The package's own ``mosaic`` joins the shadow tiles into one raster in
minutes, on the grid of the height mosaic; the node returns it with the metrics,
which the shipped dataflow ``ScoutShadows.json`` charts with Compare Scenarios.

The proof starts from SCOUT's own files, copied unchanged into
``fixtures/scout/`` (see its ``ATTRIBUTION.md``): SCOUT's committed height tiles
of both scenarios of its high-rise shadow example, in summer, become SCOUT's
committed shadow tiles and SCOUT's committed metrics.

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

The node: its template, its widgets resolved the way a run resolves them, runs
in the sandbox with its package's modules (#719), the model as the backend
resolves it, and the height tiles as the backend resolves a saved name.

Package code is imported inside each test, through a run's staged copy of the
package's modules, so a checkout without the package or its libraries fails each
test on its own and no bytecode lands in ``packages/``.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import re
import shutil
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "scout.shadow@1"
SOURCES = PACKAGE / "sources"
MODULE = "scout_shadow"
NODE_TYPE = "scout.shadow/accumulated-shadow"
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
TILE_PIXELS = 256 * 256

#: The tolerance the module docstring explains.
MAX_LEVELS = 6
MAX_SHARE = 0.06
MAX_MEAN_MINUTES = 0.1
MAX_MEDIAN_MINUTES = 0.05

#: The buildings SCOUT's second scenario removes (the dataset's manifest names them).
REMOVED_IDS = [8, 10, 12, 13, 14, 18, 19, 31, 34, 51, 66, 77, 82, 106, 122]

#: The ids the backend gives the saved tiles; any id does in process.
TILES_ID = "computed.test.files.tiles"


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


def _metrics_of(table) -> tuple[float, float]:
    """The metrics ``run_shadow_model`` returns: the mean and the median accumulated shadow."""
    assert list(table.columns) == ["Mean Acc shadow", "Median Acc shadow"], list(table.columns)
    (mean, median), = table.itertuples(index=False)
    return float(mean), float(median)


def _metrics(path: Path) -> tuple[float, float]:
    """A metrics CSV's one row: the mean and the median accumulated shadow."""
    header, row = path.read_text(encoding="utf-8").strip().splitlines()
    assert header == "Mean Acc shadow,Median Acc shadow", header
    mean, median = (float(value) for value in row.split(","))
    return mean, median


def _session():
    import onnxruntime as ort

    return ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])


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
    """``(deep_umbra, mosaic)``, as the node imports them."""
    return staged(tmp_path, SOURCES, MODULE, "deep_umbra", "mosaic")


def _height_mosaic(tmp_path, scenario: str = "A") -> Path:
    """SCOUT's committed height tiles of *scenario* as one raster, written by
    Mosaic Tiles' own ``mosaic``."""
    folder = tmp_path / f"heights-{scenario}"
    folder.mkdir()
    with staged(folder, RASTER_PACKAGE / "sources", RASTER_MODULE, "mosaic") as (raster_mosaic,):
        with raster_mosaic.mosaic(str(FIXTURES / f"{scenario}_rasters"), 16, 550,
                                  lambda name: str(folder / name)) as mosaic:
            return Path(mosaic.name)


def _saved_tiles(tmp_path, scenario: str = "A") -> Path:
    """SCOUT's committed height tiles of *scenario* as the backend keeps a saved
    folder: the files under ``data/files/``, beside its ``bundle.json``."""
    data = tmp_path / f"saved-{scenario}" / "data"
    shutil.copytree(FIXTURES / f"{scenario}_rasters", data / "files")
    (data / "bundle.json").write_text("{}", encoding="utf-8")
    return data / "bundle.json"


def _block(cells, column: int, row: int):
    return cells[256 * row:256 * (row + 1), 256 * column:256 * (column + 1)]


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


def run_node(workspace, tmp_path, *, scenario="A", **values):
    """Run the node's template, its widgets at *values*, on Rasterize
    Buildings' table of SCOUT's *scenario* tiles, with the tiles saved under
    ``tiles`` and the model resolved as the backend resolves them, in process:
    ``(the sandbox's result, the raster, SCOUT's metrics)``."""
    import pandas as pd

    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    code, problems = resolve_references(_source(), _with_values(**values), "python", inputs=[{"slot": 0}])
    assert problems == [], problems
    table = pd.DataFrame([
        {"zoom": 16, "x": int(name.split("_")[1]), "y": int(name.split("_")[2][:-4]), "max_height": 550.0}
        for name in TILE_NAMES
    ])
    result = _execute(
        code, table, NODE_TYPE, workspace, data_type="dataframe",
        package_modules={"root": str(SOURCES), "names": [MODULE]},
        models={MODEL_ID: str(MODEL_DIR)},
        dataset_paths={TILES_ID: str(_saved_tiles(tmp_path, scenario))},
        computed={"names": {values.get("tiles", "tiles"): TILES_ID}, "canSave": True},
    )
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "outputs", result["output"]
    shadow, metrics = load_from_duckdb(result["output"]["path"])
    return result, shadow, metrics


def _dataflow() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]


# ---------------------------------------------------------------------------
# SCOUT's file
# ---------------------------------------------------------------------------

def test_scouts_file_changes_only_the_marked_lines():
    """The lines Curio changes in SCOUT's ``deep_umbra.py`` are the ones it
    marks: TensorFlow's calls become numpy's and OpenCV's, the generator the
    ONNX export, the output folder the one ``curio_save_folder`` gives, the
    metrics returned rather than saved as a CSV, and the training code and
    unused imports are left out."""
    text = (SOURCES / MODULE / "deep_umbra.py").read_text(encoding="utf-8")
    marked = [line.split("# Curio:")[0].strip() for line in text.splitlines() if "# Curio:" in line]
    assert marked == [
        "import onnxruntime as ort",
        "",
        "n = np.power(2, zoom)",
        "lat_rad = np.arctan(np.sinh(np.float32(",
        "filename = '{}/{}_{}_{}.png'.format(path, zoom, i, j)",
        "filename = filename.replace('\\\"', \"\")",
        "input_image = cv2.imread(filename, cv2.IMREAD_UNCHANGED)",
        "input_image = input_image.reshape(256, 256, -1)[:, :, 0]",
        "input_image = np.reshape(input_image, (256, 256, 1))",
        "input_image = input_image.astype(np.float32)",
        "all_input = np.zeros((256*3, 256*3, 1), dtype=np.float32)",
        "all_input[indices[..., 0], indices[..., 1]] = iinput",
        "all_lat = np.ones((512, 512), dtype=np.float32)",
        "all_lat = float(latitude) * all_lat",
        "all_lat = np.reshape(all_lat, (512, 512, 1))",
        "all_date = np.ones((512, 512), dtype=np.float32)",
        "all_date = float(value) * all_date",
        "all_date = np.reshape(all_date, (512, 512, 1))",
        'prediction = generator.run(None, dict(zip(("height", "latitude", "date"), concat)))[0]',
        "prediction = prediction[:, 128:-128, 128:-128, :]",
        "",
        "def get_deep_shadow(model_path):",
        "_DEEP_SHADOW = ort.InferenceSession(model_path)",
        "model_path: str):",
        "deep_shadow = get_deep_shadow(model_path)",
        "",
        "deep_shadow,",
        "",
        "return df",
    ]
    code = "\n".join(line.split("#")[0] for line in text.splitlines())
    assert "tensorflow" not in code and "tf." not in code
    # SCOUT's own lines Curio keeps.
    for line in (
        "def load_input_grid(path, date, zoom, i, j):",
        "if os.path.isfile(filepath):",
        "input_image = (input_image / 127.5) - 1",
        "lat_image = ((lat_image + 90) / 90.0) - 1",
        "factor = 360 if season == 'winter' else 540 if season == 'spring' else 720",
        "vals = arr_norm[input_height == 0] * factor  # 1D view into arr_norm",
        'gray_u8 = (arr_norm * 255).astype("uint8")',
        "cv2.imwrite(out_path, gray_u8)",
        "'Mean Acc shadow': mean_val,",
    ):
        assert line in text, line


@pytest.mark.parametrize("scenario", ["A", "B"])
def test_scouts_rasters_become_scouts_committed_shadows(tmp_path, scenario, record_property):
    """SCOUT's ``run_shadow_model``, in summer, on SCOUT's committed height
    tiles, with the exported generator: the shadow tiles it writes are SCOUT's
    committed ones and the metrics it returns SCOUT's CSV, within the tolerance. The
    measured numbers are recorded in the run's JUnit report either way."""
    out = tmp_path / "shadows"
    out.mkdir()  # as curio_save_folder gives it
    with shadow_modules(tmp_path) as (deep_umbra, _mosaic):
        deep_umbra._DEEP_SHADOW = None
        metrics = deep_umbra.run_shadow_model(str(FIXTURES / f"{scenario}_rasters"), "summer", str(out),
                                              model_path=str(MODEL))
    assert sorted(p.name for p in out.iterdir()) == TILE_NAMES
    measured = {name: _levels(_gray(out / name), _gray(FIXTURES / f"{scenario}_shadows" / name)) for name in TILE_NAMES}
    ours, scouts = _metrics_of(metrics), _metrics(FIXTURES / f"{scenario}_shadows_metric.csv")
    record_property("gray_levels", json.dumps(measured))
    record_property("metrics", json.dumps({"ours": ours, "scouts": scouts}))
    assert _within(measured), measured
    assert _metrics_within(ours, scouts), (ours, scouts)


def test_the_mosaic_lies_on_the_height_mosaics_grid(tmp_path):
    """The shadow mosaic of SCOUT's committed shadow tiles shares the height
    mosaic's grid, so the two maps line up; each cell is its tile's
    gray level times the season's minutes over 255."""
    import numpy as np
    import rasterio

    with shadow_modules(tmp_path) as (_deep_umbra, mosaic):
        with mosaic.mosaic(str(FIXTURES / "A_shadows"), "summer", lambda name: str(tmp_path / name)) as shadow, \
                rasterio.open(_height_mosaic(tmp_path)) as heights:
            assert (shadow.crs, shadow.transform, shadow.width, shadow.height) == (
                heights.crs, heights.transform, heights.width, heights.height,
            )
            assert np.isnan(shadow.nodata) and shadow.descriptions == ("accumulated shadow (min)",)
            assert {k: shadow.tags()[k] for k in ("zoom", "season", "minutes")} == {
                "zoom": "16", "season": "summer", "minutes": "720",
            }
            cells = shadow.read(1)
            for index, name in enumerate(sorted(TILE_NAMES)):
                x, y = int(name.split("_")[1]) - 16814, int(name.split("_")[2][:-4]) - 24355
                expected = _gray(FIXTURES / "A_shadows" / name) * (720.0 / 255.0)
                assert np.allclose(_block(cells, x, y), expected, rtol=0, atol=1e-4), name


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
    from (``publish-pip-to-pypi.yml``), and leaves Deep Umbra's graph out: it
    stays in the repository, and a pip install downloads it the first time the
    node runs. Its manifest ships, so a pip install's Model Catalog lists the
    model. The rules are applied the way setuptools applies them, every line
    in order, to the files under ``models/`` and ``datasets/``: of the Model
    Catalog's files only the graph stays out, and the Data Catalog's buildings
    dataset still ships."""
    from setuptools._distutils.filelist import FileList

    monkeypatch.chdir(REPO)
    files = FileList()
    files.set_allfiles(sorted(
        path.relative_to(REPO).as_posix()
        for folder in ("models", "datasets") for path in (REPO / folder).rglob("*") if path.is_file()
    ))
    for line in (REPO / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            files.process_template_line(line)
    shipped = set(files.files)
    model = MODEL.relative_to(REPO).as_posix()
    assert model in files.allfiles
    assert [path for path in files.allfiles if path.startswith("models/") and path not in shipped] == [model]
    assert (MODEL_DIR / "manifest.json").relative_to(REPO).as_posix() in shipped
    # The rest still ships: DDRNet23-Slim's graph and the buildings dataset.
    assert "models/model.curio.ddrnet23-slim@1/files/ddrnet23_slim.onnx" in shipped
    assert BUILDINGS.relative_to(REPO).as_posix() in shipped

# ---------------------------------------------------------------------------
# The template
# ---------------------------------------------------------------------------

def test_the_template_reads_the_saved_tiles_and_runs_the_onnx_file():
    """Rasterize Buildings' table in, a raster and SCOUT's metrics out. The season is SCOUT's three
    choices; the tiles are read by their saved name, and the shadow tiles and
    the shadow tiles are saved under a name of their own; the model is named as a
    literal ``curio_load_model`` call, and its ONNX file is run as it is."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code, model_ids_in_code

    template = _template()
    assert template["inputPorts"] == [{"cardinality": "1", "types": ["DATAFRAME"]}]
    assert template["outputPorts"] == [{"cardinality": "[1,n]", "types": ["RASTER", "DATAFRAME"]}]
    assert [(w["name"], w["default"]) for w in template["widgets"]] == [
        ("season", "summer"), ("tiles", "tiles"), ("shadows", "shadows"),
    ]
    assert template["widgets"][0]["options"] == {"choices": ["spring", "summer", "winter"], "display": "radio"}
    source = _source()
    assert re.findall(r"\[!!\s*(@?\w+)\s*!!\]", source) == ["shadows", "tiles", "season", "season"]
    assert 'model_path=curio_load_model("model.scout.deep-umbra").entry' in source
    assert model_ids_in_code(source) == [MODEL_ID]
    assert dataset_ids_in_code(source) == []
    assert not (SOURCES / MODULE / "node_outputs.py").exists()


# ---------------------------------------------------------------------------
# The node, in the sandbox
# ---------------------------------------------------------------------------

def test_the_node_saves_scouts_outputs_and_returns_their_mosaic(workspace, tmp_path):
    """On the tiles saved under ``tiles``, in summer: the shadow tiles are
    saved under their name, and nothing else is; the node returns the shadow
    tiles' mosaic, on the height mosaic's grid, and SCOUT's metrics as
    ``run_shadow_model`` returns them."""
    import numpy as np
    import rasterio

    result, shadow, metrics = run_node(workspace, tmp_path)
    saved = {entry["name"]: entry for entry in result["output"]["savedFiles"]}
    assert sorted(saved) == ["shadows"] and saved["shadows"]["kind"] == "folder"
    tiles = Path(saved["shadows"]["path"])
    assert sorted(p.name for p in tiles.iterdir()) == TILE_NAMES
    assert _metrics_within(_metrics_of(metrics), _metrics(FIXTURES / "A_shadows_metric.csv"))
    with shadow, rasterio.open(_height_mosaic(tmp_path)) as heights:
        assert (shadow.crs, shadow.transform, shadow.shape) == (heights.crs, heights.transform, heights.shape)
        cells = shadow.read(1)
        for name in TILE_NAMES:
            x, y = int(name.split("_")[1]) - 16814, int(name.split("_")[2][:-4]) - 24355
            expected = _gray(tiles / name) * (720.0 / 255.0)
            assert np.allclose(_block(cells, x, y), expected, rtol=0, atol=1e-4), name


def test_the_season_and_the_names_reach_the_call(workspace, tmp_path):
    result, shadow, _metrics_table = run_node(workspace, tmp_path, season="winter", shadows="winter-shadows",
                                              tiles="heights")
    with shadow:
        assert (shadow.tags()["season"], shadow.tags()["minutes"]) == ("winter", "360")
    assert sorted(entry["name"] for entry in result["output"]["savedFiles"]) == ["winter-shadows"]


# ---------------------------------------------------------------------------
# The shipped dataflow
# ---------------------------------------------------------------------------

def test_the_shipped_dataflow_runs_the_packages_as_the_palette_drops_them():
    """``ScoutShadows.json`` is how its CI run reaches this package: its nodes
    hold the templates' own sources and widgets, the shadow nodes reading the
    season from the one Parameter node both scenarios share. Each scenario
    saves its tiles and its shadow tiles under names of its own;
    its Accumulated Shadow reads Rasterize Buildings' table and its tiles, and
    two nodes take its (shadow, metrics) apart. The chart reads SCOUT's
    metrics, one value per scenario, with no aggregate, the difference and the
    map the shadow. The model is no dataset of
    the dataflow."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code, model_ids_in_code

    spec = _dataflow()
    assert spec["packages"] == ["scout.raster-conversion@1", "scout.shadow@1"]
    assert [ref["datasetId"] for ref in spec["datasets"]] == ["data.scout.loop-buildings"]
    nodes = {node["id"]: node for node in spec["nodes"]}
    by_type: dict[str, list] = {}
    for node in spec["nodes"]:
        by_type.setdefault(node["type"], []).append(node)
    into = {(edge["target"], edge["targetHandle"]): edge["source"] for edge in spec["edges"]}

    raster_templates = {
        t["id"]: t for t in json.loads((RASTER_PACKAGE / "manifest.json").read_text(encoding="utf-8"))["templates"]
    }

    def unset(widgets):
        return [{k: v for k, v in w.items() if k != "value"} for w in widgets]

    def value(node, name):
        (widget,) = [w for w in node["metadata"]["widgets"] if w["name"] == name]
        return widget.get("value", widget["default"])

    rasterizers = by_type["scout.raster-conversion/rasterize-buildings"]
    mosaics = by_type["scout.raster-conversion/mosaic-tiles"]
    shadows = by_type[NODE_TYPE]
    assert len(rasterizers) == len(mosaics) == len(shadows) == 2
    for node, template_id in [(n, "rasterize-buildings") for n in rasterizers] + [(n, "mosaic-tiles") for n in mosaics]:
        template = raster_templates[template_id]
        assert node["content"] == (RASTER_PACKAGE / template["source"]).read_text(encoding="utf-8")
        assert unset(node["metadata"]["widgets"]) == template["widgets"]
    for node in shadows:
        assert node["content"] == _source().replace("[!! season !!]", "[!! @season !!]")
        # The season is the Parameter node's, shared by both scenarios.
        assert unset(node["metadata"]["widgets"]) == _template()["widgets"][1:]
        assert model_ids_in_code(node["content"]) == [MODEL_ID]
        assert dataset_ids_in_code(node["content"]) == []
        rasterizer = nodes[into[(node["id"], "in")]]
        assert rasterizer["type"] == "scout.raster-conversion/rasterize-buildings"
        assert value(node, "tiles") == value(rasterizer, "tiles")
    for mosaic in mosaics:
        assert value(mosaic, "tiles") == value(nodes[into[(mosaic["id"], "in")]], "tiles")
    names = sorted((value(n, "tiles"), value(n, "shadows")) for n in shadows)
    assert names == [("tiles", "shadows"), ("tiles-towers-removed", "shadows-towers-removed")]

    (parameter,) = by_type["curio.builtin/parameter"]
    assert parameter["metadata"]["widgets"] == [_template()["widgets"][0]]
    (loader,) = by_type["curio.builtin/data-loading"]
    assert dataset_ids_in_code(loader["content"]) == ["data.scout.loop-buildings"]

    assert "curio.builtin/raster-statistics" not in by_type
    pickers = by_type["curio.builtin/computation-analysis"]
    assert len(pickers) == 4
    for node in pickers:
        assert nodes[into[(node["id"], "in")]]["type"] == NODE_TYPE
        assert node["content"].splitlines()[-1] in ("return input_0[0]", "return input_0[1]")
    chart, difference = sorted(by_type["curio.builtin/compare-scenarios"],
                               key=lambda n: n["metadata"]["compareScenarios"]["mode"])
    assert chart["metadata"]["compareScenarios"]["mode"] == "chart"
    assert chart["metadata"]["compareScenarios"]["chart"]["y"] == "Mean Acc shadow"
    # One row per scenario: each bar is SCOUT's mean as it is.
    assert chart["metadata"]["compareScenarios"]["chart"]["aggregate"] == "none"
    for compare, part in ((chart, "return input_0[1]"), (difference, "return input_0[0]")):
        for handle in ("in", "in_1"):
            picker = nodes[into[(compare["id"], handle)]]
            assert picker["content"].splitlines()[-1] == part, (compare["id"], handle)
    shadow_maps = [n for n in by_type["curio.builtin/autk-grammar"] if "Accumulated shadow" in n["content"]]
    assert len(shadow_maps) == 2
    for themap in shadow_maps:
        assert nodes[into[(themap["id"], "in")]]["content"].splitlines()[-1] == "return input_0[0]"


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
    exec("def remove(input_0):\n" + textwrap.indent(remove["content"], "    "), namespace)
    buildings = gpd.read_file(BUILDINGS)
    assert list(buildings["building_id"]) == list(range(123))
    layers = {"A": buildings, "B": namespace["remove"](buildings)}
    assert len(layers["B"]) == 108

    with staged(tmp_path, RASTER_PACKAGE / "sources", RASTER_MODULE, "convert_to_raster") as (convert,):
        for scenario, layer in layers.items():
            # The GeoDataFrame itself, into an empty folder, as Rasterize
            # Buildings hands them to SCOUT's call.
            out = tmp_path / f"{scenario}_rasters"
            out.mkdir()
            convert.convert_raster(vector_in=layer, attribute="height", zoom=16, raster_out=str(out))
            assert sorted(p.name for p in out.iterdir()) == TILE_NAMES, scenario
            for name in TILE_NAMES:
                assert (out / name).read_bytes() == (FIXTURES / f"{scenario}_rasters" / name).read_bytes(), (
                    scenario, name,
                )

