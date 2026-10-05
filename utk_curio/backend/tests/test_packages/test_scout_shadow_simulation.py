"""``scout.shadow-simulation@1``: SCOUT's Deep Umbra shadow simulation in Curio.

The proof: the package's Simulate Shadows, running the Model Catalog's ONNX
export of Deep Umbra (``model.scout.deep-umbra``), turns the height tiles SCOUT
committed for its high-rise shadow example into the summer shadows SCOUT's
TensorFlow Deep Umbra committed for them, each within one gray level, and into
SCOUT's metrics, within a minute. It does so on SCOUT's own tiles (the model
alone) and on the tiles Rasterize Buildings makes from SCOUT's buildings (the
whole Curio pipeline). SCOUT's files are copied unchanged into
``fixtures/scout/`` (see its ``ATTRIBUTION.md``).

The node: its template, with its season widget resolved the way a run resolves
it, runs in the sandbox on Rasterize Buildings' output, with the model handed
to ``curio_load_model`` as the backend hands it, and returns
``(mosaic, tiles, summary)``.

The tests need onnxruntime, which the package brings when it is installed; a
checkout without it skips them.
"""
from __future__ import annotations

import base64
import contextlib
import importlib
import io
import json
import re
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("onnxruntime")

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "scout.shadow-simulation@1"
SOURCES = PACKAGE / "sources"
MODULE = "scout_shadow_simulation"
NODE_TYPE = "scout.shadow-simulation/simulate-shadows"
MODEL_ID = "model.scout.deep-umbra"
MODEL_DIR = REPO / "models" / "model.scout.deep-umbra@1"

RASTER_PACKAGE = REPO / "packages" / "scout.raster-conversion@1"
RASTER_MODULE = "scout_raster_conversion"
RASTER_NODE_TYPE = "scout.raster-conversion/rasterize-buildings"

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scout"
BUILDINGS = FIXTURES / "A_buildings.geojson"
SCOUT_TILES = FIXTURES / "A_rasters"
SCOUT_SHADOWS = FIXTURES / "A_shadows"
SCOUT_METRICS = FIXTURES / "A_shadows_metric.csv"
TILE_NAMES = [
    "16_16814_24355.png",
    "16_16814_24356.png",
    "16_16815_24355.png",
    "16_16815_24356.png",
]


def _template(package=PACKAGE) -> dict:
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    (template,) = manifest["templates"]
    return template


def _gray(path_or_png):
    """A tile's gray levels as ints, from its file or its ``png`` value."""
    import numpy as np
    from PIL import Image

    source = path_or_png if isinstance(path_or_png, Path) else io.BytesIO(base64.b64decode(path_or_png))
    with Image.open(source) as image:
        pixels = np.asarray(image)
    return (pixels[:, :, 0] if pixels.ndim == 3 else pixels).astype(int)


def _worst(ours, theirs) -> int:
    import numpy as np

    return int(np.abs(ours - theirs).max())


def _scout_metrics():
    import pandas as pd

    return pd.read_csv(SCOUT_METRICS).iloc[0]


def _model():
    from utk_curio.sandbox.util.catalog_helpers import CurioModel

    return CurioModel(MODEL_ID, str(MODEL_DIR))


@contextlib.contextmanager
def _modules(tmp_path):
    """``(rasterize node_outputs, shadow node_outputs)``, staged as a run stages them."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    with contextlib.ExitStack() as stack:
        loaded = []
        for sources, module in ((RASTER_PACKAGE / "sources", RASTER_MODULE), (SOURCES, MODULE)):
            run = tmp_path / f"run-{module}"
            run.mkdir()
            staged = stage_package_modules({"root": str(sources), "names": [module]}, str(run))
            stack.enter_context(importable(str(run / staged["root"]), staged["names"]))
            loaded.append(importlib.import_module(f"{module}.node_outputs"))
        yield tuple(loaded)


def _rasterized(rasterize, tmp_path):
    import geopandas as gpd

    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return rasterize.rasterize_buildings(
        gpd.read_file(BUILDINGS), attribute="height", zoom=16, max_height=550.0,
        output_file=lambda name: str(out / name),
    )


def _assert_scouts_shadows(shadows, summary):
    import numpy as np

    names = [f"{r.zoom}_{r.x}_{r.y}.png" for r in shadows.itertuples(index=False)]
    assert names == TILE_NAMES
    worst, built = {}, {}
    for r in shadows.itertuples(index=False):
        name = f"{r.zoom}_{r.x}_{r.y}.png"
        mine, buildings = _gray(r.png), _gray(SCOUT_TILES / name) > 0
        # SCOUT's metrics read the ground; there the shadows are SCOUT's.
        worst[name] = _worst(np.where(buildings, 0, mine), np.where(buildings, 0, _gray(SCOUT_SHADOWS / name)))
        # Under a building Deep Umbra gives next to nothing; the node says 0.
        built[name] = int(mine[buildings].max(initial=0))
    assert all(levels <= 1 for levels in worst.values()), worst
    assert all(level == 0 for level in built.values()), built
    # Not two blank images agreeing: each of SCOUT's shadows holds shadow.
    assert all(_gray(SCOUT_SHADOWS / name).max() > 0 for name in TILE_NAMES)
    scout = _scout_metrics()
    for column in ("Mean Acc shadow", "Median Acc shadow"):
        assert summary[column].iloc[0] == pytest.approx(scout[column], abs=1.0), column


# ---------------------------------------------------------------------------
# The proof
# ---------------------------------------------------------------------------

def test_scouts_tiles_become_scouts_committed_shadows(tmp_path):
    """The model alone: SCOUT's committed height tiles, through Curio's ONNX
    Deep Umbra, give SCOUT's committed summer shadows and metrics."""
    with _modules(tmp_path) as (rasterize, shadow):
        mosaic, tiles = _rasterized(rasterize, tmp_path)
        tiles = tiles.copy()
        for i, row in tiles.iterrows():
            name = f"{row.zoom}_{row.x}_{row.y}.png"
            tiles.at[i, "png"] = base64.b64encode((SCOUT_TILES / name).read_bytes()).decode("ascii")
        out, shadows, summary = shadow.simulate_shadows(
            (mosaic, tiles), _model(), "summer", lambda name: str(tmp_path / name),
        )
        out.close()
        mosaic.close()
    _assert_scouts_shadows(shadows, summary)


def test_scouts_buildings_become_scouts_committed_shadows(tmp_path):
    """The whole pipeline: SCOUT's buildings, through Rasterize Buildings and
    Simulate Shadows, give SCOUT's committed summer shadows and metrics."""
    with _modules(tmp_path) as (rasterize, shadow):
        mosaic, tiles = _rasterized(rasterize, tmp_path)
        out, shadows, summary = shadow.simulate_shadows(
            (mosaic, tiles), _model(), "summer", lambda name: str(tmp_path / name),
        )
        out.close()
        mosaic.close()
    _assert_scouts_shadows(shadows, summary)


# ---------------------------------------------------------------------------
# The template
# ---------------------------------------------------------------------------

def test_the_template_declares_the_widget_its_source_reads():
    template = _template()
    assert template["hasWidgets"] is True
    assert {w["name"]: w["default"] for w in template["widgets"]} == {"season": "summer"}
    source = (PACKAGE / template["source"]).read_text(encoding="utf-8")
    assert re.findall(r"\[!!\s*(\w+)\s*!!\]", source) == ["season"]
    assert f'curio_load_model("{MODEL_ID}")' in source


# ---------------------------------------------------------------------------
# The node, in the sandbox
# ---------------------------------------------------------------------------

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


def _run(package, module, node_type, input_art, data_type, workspace, values=None, models=None):
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.app.worker import execute_code

    template = _template(package)
    widgets = [dict(w) for w in template["widgets"]]
    for widget in widgets:
        if widget["name"] in (values or {}):
            widget["value"] = values[widget["name"]]
    source = (package / template["source"]).read_text(encoding="utf-8")
    code, problems = resolve_references(source, widgets, "python", inputs=[{"slot": 0}])
    assert problems == [], problems
    return execute_code(
        textwrap.indent(code, "    "), input_art, node_type, data_type,
        save_dataset=False, media_dir=str(workspace / "media"),
        package_modules={"root": str(package / "sources"), "names": [module]},
        models=models,
    )


def run_pipeline(workspace, *, season="summer"):
    """Rasterize Buildings, then Simulate Shadows on its output, each as its
    template in the sandbox: the shadow node's result."""
    import geopandas as gpd

    from utk_curio.sandbox.app.worker import _worker_init
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    _worker_init()
    buildings = save_to_duckdb(gpd.read_file(BUILDINGS), node_id="buildings")
    rasters = _run(RASTER_PACKAGE, RASTER_MODULE, RASTER_NODE_TYPE, buildings, "geodataframe", workspace)
    assert rasters["stderr"] == "", rasters["stderr"]
    # One edge from a node that returns a tuple: the backend sends it as a
    # file, never as "outputs", the several-inputs list (execution/node_exec.py).
    return _run(
        PACKAGE, MODULE, NODE_TYPE, rasters["output"]["path"], "file", workspace,
        values={"season": season}, models={MODEL_ID: str(MODEL_DIR)},
    )


def test_the_node_returns_scouts_shadows_and_their_mosaic(workspace):
    import numpy as np
    import rasterio

    from utk_curio.sandbox.util.parsers import load_from_duckdb
    from utk_curio.sandbox.util.rasters import epsg_name

    result = run_pipeline(workspace)
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "outputs", result["output"]
    mosaic, shadows, summary = load_from_duckdb(result["output"]["path"])
    try:
        assert list(shadows.columns) == ["zoom", "x", "y", "png", "mean_shadow_min"]
        _assert_scouts_shadows(shadows, summary)
        assert summary["season"].iloc[0] == "summer"

        assert isinstance(mosaic, rasterio.io.DatasetReader)
        assert epsg_name(mosaic.crs) == "EPSG:3395"
        assert (mosaic.width, mosaic.height, mosaic.count) == (512, 512, 1)
        cells = mosaic.read(1)
        # Deep Umbra's tanh can land a hair past -1 or 1; SCOUT does not clip.
        assert -0.01 <= cells.min() and cells.max() <= 720.01
        # Each tile's block is its shadow in minutes: its gray level over 255, times 720.
        for r in shadows.itertuples(index=False):
            col, row = r.x - 16814, r.y - 24355
            block = cells[256 * row:256 * (row + 1), 256 * col:256 * (col + 1)]
            assert np.allclose(block, _gray(r.png) / 255.0 * 720, atol=720 / 255.0 + 1e-3)
    finally:
        mosaic.close()


def test_the_season_reaches_the_model(workspace):
    """Winter counts 360 minutes and casts other shadows than summer."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = run_pipeline(workspace, season="winter")
    assert result["stderr"] == "", result["stderr"]
    mosaic, shadows, summary = load_from_duckdb(result["output"]["path"])
    try:
        assert summary["season"].iloc[0] == "winter"
        assert mosaic.read(1).max() <= 360.01
        assert mosaic.tags()["day_minutes"] == "360"
        differs = [
            _worst(_gray(r.png), _gray(SCOUT_SHADOWS / f"{r.zoom}_{r.x}_{r.y}.png")) > 1
            for r in shadows.itertuples(index=False)
        ]
        assert any(differs)
    finally:
        mosaic.close()
