"""Local Relief, the example model package: its weights reach a node and give numpy's answer.

``docs/bring-your-own-model/model.example.local-relief@1/`` is a node package
of kind ``model``: its manifest's ``model`` block names the ONNX graph under
``models/``, and ``curio_load_model`` reads that block. Its graph takes a
height raster and returns each cell's height minus the mean of the 5 by 5
cells around it (the cells that are there, at the edge), which numpy computes
cell by cell here.

The code under test is imported inside each test, so a tree without it fails
test by test.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
LOCAL_RELIEF = REPO / "docs" / "bring-your-own-model" / "model.example.local-relief@1"
MODEL_ID = "model.example.local-relief"


def _reference(height: np.ndarray, window: int = 5) -> np.ndarray:
    """Each cell's height minus the mean of the window around it, by hand."""
    rows, cols = height.shape
    half = window // 2
    out = np.empty_like(height, dtype=np.float64)
    for r in range(rows):
        for c in range(cols):
            around = height[max(0, r - half):r + half + 1, max(0, c - half):c + half + 1]
            out[r, c] = height[r, c] - around.mean()
    return out


def _tower() -> np.ndarray:
    """A 9 by 9 raster of ground with one 25 m tower in the middle: the
    tower stands 24 m above the mean of its 5 by 5 cells."""
    heights = np.zeros((9, 9), dtype=np.float32)
    heights[4, 4] = 25.0
    return heights


def _model():
    from utk_curio.sandbox.util.catalog_helpers import CurioModel

    return CurioModel(MODEL_ID, str(LOCAL_RELIEF))


def test_local_relief_equals_numpys_5_by_5_mean_difference():
    model = _model()
    rng = np.random.default_rng(0)
    cases = {
        "64 by 64 random": rng.uniform(0, 300, (64, 64)),
        "37 by 90 random": rng.uniform(0, 300, (37, 90)),
        "flat": np.full((20, 20), 12.0),
        "one tower": _tower(),
    }
    for name, height in cases.items():
        heights = height.astype(np.float32)
        (relief,) = model.run({"height": heights[np.newaxis, np.newaxis]})
        assert relief.shape == (1, 1) + heights.shape, name
        assert np.abs(relief[0, 0] - _reference(heights)).max() <= 1e-3, name


def test_the_loaded_model_reads_its_block():
    model = _model()
    assert model.manifest["runtime"] == "onnx"
    assert model.manifest["entry"] == "models/local_relief.onnx"
    assert model.manifest["task"] == "image-to-image"
    assert model.labels == []


def test_the_nodes_module_writes_the_relief_on_the_input_grid(tmp_path):
    """``sources/local_relief/run.py``, which the node's code calls: the result
    is a raster on the input's grid, a cell with no data reads as ground for
    its neighbours and has no data itself."""
    import rasterio
    from rasterio.transform import from_origin

    spec = importlib.util.spec_from_file_location(
        "local_relief_run_under_test", LOCAL_RELIEF / "sources" / "local_relief" / "run.py",
    )
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)

    rng = np.random.default_rng(1)
    heights = rng.uniform(0, 80, (12, 15)).astype(np.float32)
    heights[3, 7] = -9999.0
    transform = from_origin(-87.63, 41.88, 0.0001, 0.0001)
    path = tmp_path / "heights.tif"
    with rasterio.open(path, "w", driver="GTiff", width=15, height=12, count=1, dtype="float32",
                       crs="EPSG:4326", transform=transform, nodata=-9999.0) as out:
        out.write(heights, 1)

    with rasterio.open(path) as raster:
        result = run.local_relief(raster, _model(), output_file=lambda name: str(tmp_path / name))
    try:
        assert (result.width, result.height, result.crs.to_epsg()) == (15, 12, 4326)
        assert result.transform == transform
        relief = result.read(1)
    finally:
        result.close()
    ground = heights.copy()
    ground[3, 7] = 0.0
    expected = _reference(ground)
    assert np.isnan(relief[3, 7])
    mask = ~np.isnan(relief)
    assert mask.sum() == 12 * 15 - 1
    assert np.abs(relief[mask] - expected[mask]).max() <= 1e-3


def _namespace():
    import pandas as pd

    return {"np": np, "pd": pd}


_CODE = (
    "    import numpy as np\n"
    "    model = curio_load_model('model.example.local-relief')\n"
    "    heights = np.zeros((9, 9), dtype=np.float32)\n"
    "    heights[4, 4] = 25.0\n"
    "    (relief,) = model.run({'height': heights[np.newaxis, np.newaxis]})\n"
    "    print('relief', round(float(relief[0, 0, 4, 4]), 4))\n"
    "    return round(float(relief[0, 0, 4, 4]), 4)\n"
)


def test_curio_load_model_runs_a_model_package_in_process():
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.db import init_db

    _worker_init()
    init_db()
    result = execute_code(_CODE, "", "PYTHON_COMPUTATION", "", save_dataset=False,
                          models={MODEL_ID: str(LOCAL_RELIEF)})
    assert result["stderr"] == ""
    assert "relief 24.0" in "\n".join(result["stdout"])


def test_an_isolated_child_runs_a_staged_model_package(tmp_path):
    from utk_curio.sandbox.isolation import child
    from utk_curio.sandbox.util import staging

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    staged = staging.stage_model_dirs({MODEL_ID: str(LOCAL_RELIEF)}, scratch)
    assert (scratch / staged[MODEL_ID] / "models" / "local_relief.onnx").is_file()
    request = {
        "code": _CODE, "node_type": "model.example.local-relief/local-relief", "data_type": "",
        "scratch_dir": str(scratch), "input": {"kind": "none"}, "dataset_paths": {},
        "models": staged, "session_imports": [], "limits": {},
    }
    result = child.run_node(request, _namespace)
    assert result["ok"], result["stderr"]
    assert result["output"]["value"] == pytest.approx(24.0)
