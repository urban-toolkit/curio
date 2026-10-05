"""``scout.shadow@1``: SCOUT's Deep Umbra shadow model in Curio (#662, step 19).

The proof: the package's port of SCOUT's ``run_shadow_model``, called as SCOUT's
high-rise shadow example calls it, in summer, with the ONNX export of SCOUT's
generator that Curio ships (the Data Catalog dataset ``data.scout.deep-umbra@1``),
turns SCOUT's committed height tiles of both of the example's scenarios into
SCOUT's committed shadow tiles and metrics. All are SCOUT's own files, copied
unchanged into ``fixtures/scout/`` (see its ``ATTRIBUTION.md``).

Within a tolerance, not equal. Deep Umbra normalizes each layer by the tile's own
mean and variance, and two float32 runs of it differ by up to about 0.017 on a
few pixels of its output from -1 to 1: ``scripts/scout/export_deep_umbra.py``
measured TensorFlow's own float32 run 0.016 from a float64 run of the same
generator, and the ONNX run no farther. On SCOUT's tiles that is one gray level
on up to 691 of a tile's 65,536 pixels and two on 2 of them, where TensorFlow
2.12 rerunning SCOUT's own code differs from SCOUT's files by one level on up to
13 pixels and the float64 run by one level on up to 588. So a tile may differ by
at most 3 gray levels on at most 1.5% of its pixels, and each metric by at most
0.05 minutes. Moving averages in place of each tile's statistics, a wrong season
or a wrong latitude miss by far more.

The node: its template, its widget resolved the way a run resolves it, runs in
the sandbox with its package's modules (#719) and the model as the backend
resolves it. It returns ``(mosaic, metrics)``.

Package code is imported inside each test, through a run's staged copy of the
package's modules, so a checkout without the package or its libraries fails each
test on its own and no bytecode lands in ``packages/``.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib
import json
import re
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "scout.shadow@1"
SOURCES = PACKAGE / "sources"
MODULE = "scout_shadow"
NODE_TYPE = "scout.shadow/accumulated-shadow"
MODEL_ID = "data.scout.deep-umbra"
MODEL_DIR = REPO / "datasets" / "data.scout.deep-umbra@1"
MODEL = MODEL_DIR / "data" / "deep_umbra.onnx"
#: The file ``scripts/scout/export_deep_umbra.py`` writes, in the environment its
#: docstring pins.
MODEL_SHA256 = "67afb9d2d56bd0a12164e6e651214d56860ff689728c5b6f29486f21c3cb188e"
BUILDINGS = REPO / "datasets" / "data.scout.loop-buildings@1" / "data" / "loop-buildings.geojson"
DATAFLOW = REPO / "docs" / "examples" / "dataflows" / "ScoutShadows.json"
RASTER_PACKAGE = REPO / "packages" / "scout.raster-conversion@1"

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scout"
TILE_NAMES = [
    "16_16814_24355.png",
    "16_16814_24356.png",
    "16_16815_24355.png",
    "16_16815_24356.png",
]
TILE_PIXELS = 256 * 256

#: The tolerance the module docstring explains.
MAX_LEVELS = 3
MAX_SHARE = 0.015
MAX_MINUTES = 0.05

#: The buildings SCOUT's second scenario removes (the dataset's manifest names them).
REMOVED_IDS = [8, 10, 12, 13, 14, 18, 19, 31, 34, 51, 66, 77, 82, 106, 122]


def _manifest() -> dict:
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def _template() -> dict:
    (template,) = _manifest()["templates"]
    return template


def _source() -> str:
    return (PACKAGE / _template()["source"]).read_text(encoding="utf-8")


def _gray(path_or_png):
    """A tile's gray levels as ints, from its file or its ``png`` value."""
    import io

    import numpy as np
    from PIL import Image

    source = path_or_png if isinstance(path_or_png, Path) else io.BytesIO(base64.b64decode(path_or_png))
    with Image.open(source) as image:
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
    """``(deep_umbra, node_outputs)``, as the node imports them."""
    return staged(tmp_path, SOURCES, MODULE, "deep_umbra", "node_outputs")


def _tiles(scenario: str = "A"):
    """SCOUT's height tiles of *scenario* as Rasterize Buildings returns them:
    one row per tile with ``zoom``, ``x``, ``y`` and its PNG in base64."""
    import pandas as pd

    rows = []
    for name in TILE_NAMES:
        zoom, x, y = (int(part) for part in name[:-4].split("_"))
        png = base64.b64encode((FIXTURES / f"{scenario}_rasters" / name).read_bytes()).decode("ascii")
        rows.append({"zoom": zoom, "x": x, "y": y, "png": png})
    return pd.DataFrame(rows, columns=["zoom", "x", "y", "png"])


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


def run_node(value, workspace, *, data_type="dataframe", model=True, fails=False, **values):
    """Run the node's template, its widget at *values*, on *value* in the
    sandbox, in process, with the model resolved as the backend resolves it
    (or, without *model*, as a Curio without it does): ``(artifact id, output)``,
    or with *fails* the node's error text."""
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    code, problems = resolve_references(_source(), _with_values(**values), "python", inputs=[{"slot": 0}])
    assert problems == [], problems
    _worker_init()
    art_id = save_to_duckdb(value, node_id="tiles")
    result = execute_code(
        textwrap.indent(code, "    "), art_id, NODE_TYPE, data_type,
        save_dataset=False, media_dir=str(workspace / "media"),
        package_modules={"root": str(SOURCES), "names": [MODULE]},
        dataset_paths={MODEL_ID: str(MODEL)} if model else {},
        dataset_formats={MODEL_ID: {"format": "onnx"}} if model else {},
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

@pytest.mark.parametrize("scenario", ["A", "B"])
def test_scouts_rasters_become_scouts_committed_shadows(tmp_path, scenario):
    """SCOUT's call, on SCOUT's committed height tiles, writes SCOUT's committed
    shadow tiles and metrics: the same four files, within the tolerance."""
    out = tmp_path / f"{scenario}_shadows"
    metrics_out = tmp_path / f"{scenario}_shadows_metric"
    with shadow_modules(tmp_path) as (deep_umbra, _outputs):
        deep_umbra.run_shadow_model(
            rasters_in=str(FIXTURES / f"{scenario}_rasters"),
            season="summer",
            rasters_out=str(out),
            metrics_out=str(metrics_out),
            generator=_session(),
        )
    assert sorted(p.name for p in out.iterdir()) == TILE_NAMES
    committed = FIXTURES / f"{scenario}_shadows"
    measured = {name: _levels(_gray(out / name), _gray(committed / name)) for name in TILE_NAMES}
    assert _within(measured), (
        f"(largest gray-level difference, pixels that differ) per tile, against at most "
        f"{MAX_LEVELS} levels on {MAX_SHARE:.1%} of {TILE_PIXELS} pixels: {measured}"
    )
    ours, scouts = _metrics(Path(f"{metrics_out}.csv")), _metrics(FIXTURES / f"{scenario}_shadows_metric.csv")
    differences = [abs(a - b) for a, b in zip(ours, scouts)]
    assert all(d <= MAX_MINUTES for d in differences), (
        f"(mean, median) minutes: ours {ours}, SCOUT's {scouts}, differences {differences}, "
        f"against at most {MAX_MINUTES}"
    )
    # Not blank tiles agreeing: every one of SCOUT's tiles holds full shadow
    # and open ground.
    for name in TILE_NAMES:
        gray = _gray(committed / name)
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
    manifest = json.loads((MODEL_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["id"], manifest["format"], manifest["dataFile"]) == (MODEL_ID, "onnx", "data/deep_umbra.onnx")


def test_the_model_stays_out_of_the_pip_package(monkeypatch):
    """``MANIFEST.in`` ships ``datasets/`` in the sdist, which the wheel is built
    from (``publish-pip-to-pypi.yml``), and leaves the model's folder out: it
    stays in the repository only. The rules are applied the way setuptools
    applies them, to the files under ``datasets/``."""
    from setuptools._distutils.filelist import FileList

    monkeypatch.chdir(REPO)
    files = FileList()
    files.set_allfiles(sorted(
        path.relative_to(REPO).as_posix() for path in (REPO / "datasets").rglob("*") if path.is_file()
    ))
    for line in (REPO / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(("include ", "recursive-include datasets", "prune datasets", "exclude ")):
            files.process_template_line(line)
    shipped = set(files.files)
    model = MODEL.relative_to(REPO).as_posix()
    assert model in files.allfiles
    assert not [path for path in shipped if path.startswith("datasets/data.scout.deep-umbra@1/")], sorted(shipped)
    # The rest of the catalog still ships, the buildings beside the model included.
    assert BUILDINGS.relative_to(REPO).as_posix() in shipped
    assert len(shipped) == len(files.allfiles) - len(list(MODEL_DIR.rglob("*.*")))


# ---------------------------------------------------------------------------
# The template
# ---------------------------------------------------------------------------

def test_the_template_reads_the_season_and_loads_the_model_by_its_id():
    """The season is SCOUT's three choices, drawn as radio buttons; the model is
    named as a literal the backend resolves before the run."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code

    template = _template()
    assert template["hasWidgets"] is True
    assert template["widgets"] == [{
        "name": "season", "type": "choice", "label": "Season", "default": "summer",
        "options": {"choices": ["spring", "summer", "winter"], "display": "radio"},
    }]
    source = _source()
    assert re.findall(r"\[!!\s*(@?\w+)\s*!!\]", source) == ["season"]
    assert dataset_ids_in_code(source) == [MODEL_ID]
    assert _manifest()["dependencies"]["python"] == {"onnxruntime": ">=1.17", "rasterio": ">=1.4"}


# ---------------------------------------------------------------------------
# The node, in the sandbox
# ---------------------------------------------------------------------------

def test_the_node_returns_the_shadow_mosaic_and_scouts_metrics(workspace, tmp_path):
    """SCOUT's A tiles in: SCOUT's metrics within the tolerance, and a mosaic in
    minutes whose blocks are the port's own shadow tiles, on the rasterizer's grid."""
    import rasterio
    from pyproj import Transformer

    from utk_curio.sandbox.util.rasters import epsg_name

    _art_id, (mosaic, metrics) = run_node(_tiles("A"), workspace)
    try:
        assert list(metrics.columns) == ["season", "mean_minutes", "median_minutes"]
        assert len(metrics) == 1 and metrics["season"].iloc[0] == "summer"
        ours = (float(metrics["mean_minutes"].iloc[0]), float(metrics["median_minutes"].iloc[0]))
        scouts = _metrics(FIXTURES / "A_shadows_metric.csv")
        assert all(abs(a - b) <= MAX_MINUTES for a, b in zip(ours, scouts)), (ours, scouts)

        assert isinstance(mosaic, rasterio.io.DatasetReader)
        assert epsg_name(mosaic.crs) == "EPSG:3395"
        assert (mosaic.width, mosaic.height, mosaic.count, mosaic.dtypes[0]) == (512, 512, 1, "float32")
        assert mosaic.tags()["season"] == "summer" and mosaic.tags()["minutes"] == "720"
        cells = mosaic.read(1)

        out = tmp_path / "port"
        with shadow_modules(tmp_path) as (deep_umbra, _outputs):
            deep_umbra.run_shadow_model(str(FIXTURES / "A_rasters"), "summer", str(out), str(tmp_path / "m"), _session())
        # Columns of tiles run west to east with x, rows north to south with y.
        for name, (row, col) in {
            "16_16814_24355.png": (0, 0), "16_16815_24355.png": (0, 1),
            "16_16814_24356.png": (1, 0), "16_16815_24356.png": (1, 1),
        }.items():
            block = cells[256 * row:256 * (row + 1), 256 * col:256 * (col + 1)]
            # The tile truncates the shadow to 8 bits; the mosaic keeps it.
            fraction = block / 720.0 * 255.0 - _gray(out / name)
            assert fraction.min() >= -1e-3 and fraction.max() < 1 + 1e-3, (name, fraction.min(), fraction.max())

        # The grid is the rasterizer's: the outer corners of the corner tiles.
        to_3395 = Transformer.from_crs(4326, 3395, always_xy=True)
        west, north = to_3395.transform(*_tile_corner(16814, 24355, 16))
        east, south = to_3395.transform(*_tile_corner(16816, 24357, 16))
        a, b, c, d, e, f = tuple(mosaic.transform)[:6]
        assert b == 0 and d == 0
        assert c == pytest.approx(west, abs=1e-6) and f == pytest.approx(north, abs=1e-6)
        assert c + 512 * a == pytest.approx(east, abs=1e-6)
        assert f + 512 * e == pytest.approx(south, abs=0.01 * abs(e))
    finally:
        mosaic.close()


def _tile_corner(x, y, zoom):
    """``(lon, lat)`` of a tile's north-west corner."""
    import math

    n = 2.0 ** zoom
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return x / n * 360.0 - 180.0, lat


def test_the_mosaic_is_a_raster_the_autark_node_loads(workspace):
    """What #718's raster route serves for the tuple's first part: an EPSG CRS,
    a north-up grid, inside the Autark node's caps."""
    from rasterio.io import MemoryFile

    from utk_curio.sandbox.util.rasters import serve_raster

    art_id, (mosaic, _metrics) = run_node(_tiles("A"), workspace)
    try:
        payload, meta = serve_raster(art_id, part=0, max_cells=2048 * 2048, max_side=8192)
        assert meta["crs"] == "EPSG:3395"
        a, b, c, d, e, f = meta["transform"]
        assert b == 0 and d == 0 and a > 0 and e < 0
        assert (meta["width"], meta["height"], meta["count"]) == (512, 512, 1)
        with MemoryFile(payload) as memory, memory.open() as served:
            assert served.crs == mosaic.crs and served.transform == mosaic.transform
            assert (served.read(1) == mosaic.read(1)).all()
    finally:
        mosaic.close()


def test_the_season_reaches_the_call(workspace):
    """Each season its own sun and its own minutes: winter counts 360 for a day
    in shadow, spring 540, summer 720."""
    import numpy as np

    results = {}
    for season in ("winter", "spring", "summer"):
        _art_id, (mosaic, metrics) = run_node(_tiles("A"), workspace, season=season)
        try:
            cells = mosaic.read(1)
            results[season] = (float(np.nanmax(cells)), float(metrics["mean_minutes"].iloc[0]),
                               metrics["season"].iloc[0], mosaic.tags()["minutes"])
        finally:
            mosaic.close()
    for season, minutes in (("winter", 360), ("spring", 540), ("summer", 720)):
        top, mean, named, tagged = results[season]
        assert named == season and tagged == str(minutes), results
        assert 0.5 * minutes < top <= minutes + 1e-3, results
    means = [results[season][1] for season in ("winter", "spring", "summer")]
    assert len(set(round(m, 3) for m in means)) == 3, results


def test_the_rasterizers_tuple_is_read_and_its_height_scale_checked(tmp_path):
    """Wired straight to Rasterize Buildings, the node gets its ``(mosaic,
    tiles)``: it reads the tiles, and the mosaic's maximum height, which Deep
    Umbra needs at 550 m."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    def mosaic_drawn_with(max_height):
        path = tmp_path / f"mosaic-{max_height}.tif"
        profile = {"driver": "GTiff", "width": 2, "height": 2, "count": 1, "dtype": "float32",
                   "crs": "EPSG:3395", "transform": from_origin(0, 0, 1, 1)}
        with rasterio.open(path, "w", **profile) as out:
            out.write(np.zeros((2, 2), dtype="float32"), 1)
            out.update_tags(max_height=float(max_height))
        return rasterio.open(path)

    with shadow_modules(tmp_path) as (_deep_umbra, outputs):
        tiles = _tiles("A")
        for max_height in (550, 275):
            mosaic = mosaic_drawn_with(max_height)
            try:
                found, scale = outputs.tiles_of([mosaic, tiles])
                assert found is tiles and scale == float(max_height)
            finally:
                mosaic.close()
        outputs.check_tiles(tiles, 550.0, "summer")
        with pytest.raises(ValueError, match="Set Rasterize Buildings' Maximum height to 550"):
            outputs.check_tiles(tiles, 275.0, "summer")


@pytest.mark.parametrize(
    "change, sentence",
    [
        ("zoom 15", "Deep Umbra reads zoom-16 tiles, and these are zoom 15"),
        ("no tiles", "Accumulated Shadow has no tiles to read"),
        ("not tiles", "Accumulated Shadow reads the tiles of Rasterize Buildings"),
    ],
)
def test_tiles_deep_umbra_cannot_read_are_refused_in_a_sentence(workspace, change, sentence):
    tiles = _tiles("A")
    if change == "zoom 15":
        tiles["zoom"] = 15
    elif change == "no tiles":
        tiles = tiles.iloc[0:0]
    else:
        tiles = tiles.drop(columns=["png"])
    error = run_node(tiles, workspace, fails=True)
    assert sentence in error, error


def test_a_curio_without_the_model_says_how_to_add_it(workspace):
    """A pip install has no ``datasets/data.scout.deep-umbra@1``: the backend
    resolves no file for the model, and the node says what to copy where."""
    error = run_node(_tiles("A"), workspace, model=False, fails=True)
    for words in (
        "data.scout.deep-umbra@1, and this Curio does not have it",
        "not in the pip package",
        "copy the repository's folder datasets/data.scout.deep-umbra@1",
        "--catalog-root",
    ):
        assert words in error, error


def test_another_failure_to_open_the_model_is_not_hidden(tmp_path):
    """Only a missing model reads as missing: onnxruntime absent, say, keeps its own sentence."""
    with shadow_modules(tmp_path) as (_deep_umbra, outputs):
        def load():
            raise RuntimeError("This dataset is an ONNX model, which runs on onnxruntime, and this Curio does not have it")

        with pytest.raises(RuntimeError, match="runs on onnxruntime") as raised:
            outputs.open_model(load)
        assert "pip package" not in str(raised.value)


# ---------------------------------------------------------------------------
# The shipped dataflow
# ---------------------------------------------------------------------------

def _dataflow() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]


def test_the_shipped_dataflow_runs_the_packages_as_the_palette_drops_them():
    """``ScoutShadows.json`` is how its CI run reaches this package: its nodes
    hold the templates' own sources and widgets, the shadow nodes reading the
    season from the one Parameter node both scenarios share."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code

    spec = _dataflow()
    assert spec["packages"] == ["scout.raster-conversion@1", "scout.shadow@1"]
    assert [ref["datasetId"] for ref in spec["datasets"]] == ["data.scout.loop-buildings", MODEL_ID]
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
        assert dataset_ids_in_code(node["content"]) == [MODEL_ID]
    (parameter,) = by_type["curio.builtin/parameter"]
    assert parameter["metadata"]["widgets"] == _template()["widgets"]

    (loader,) = by_type["curio.builtin/data-loading"]
    assert dataset_ids_in_code(loader["content"]) == ["data.scout.loop-buildings"]
    assert len(by_type["curio.builtin/compare-scenarios"]) == 2


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

    with staged(tmp_path, RASTER_PACKAGE / "sources", "scout_raster_conversion", "convert_to_raster") as (convert,):
        for scenario, layer in layers.items():
            out = tmp_path / f"{scenario}_rasters"
            convert.convert_raster(vector_in=layer, attribute="height", zoom=16, raster_out=str(out))
            assert sorted(p.name for p in out.iterdir()) == TILE_NAMES, scenario
            worst = {name: _levels(_gray(out / name), _gray(FIXTURES / f"{scenario}_rasters" / name))[0]
                     for name in TILE_NAMES}
            assert all(levels <= 1 for levels in worst.values()), (scenario, worst)
