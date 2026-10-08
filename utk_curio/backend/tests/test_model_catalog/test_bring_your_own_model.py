"""The worked example of docs/BRINGING-MODELS.md works as the guide says.

``docs/bring-your-own-model/`` holds a model folder and a node package a reader
copies into ``models/`` and ``packages/``. These tests read them where they
are: the model's manifest is one the Model Catalog takes, the package is one
the Node Catalog takes, and the guide's two nodes, the one that makes a height
raster and Local Relief, run in the sandbox as a dataflow runs them, with the
answer the guide states.
"""

from __future__ import annotations

import hashlib
import json
import re
import textwrap
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[4]
EXAMPLE = REPO / "docs" / "bring-your-own-model"
GUIDE = REPO / "docs" / "BRINGING-MODELS.md"
MODEL_DIR = EXAMPLE / "model.example.local-relief@1"
PACKAGE_DIR = EXAMPLE / "example.local-relief@1"
SOURCES = PACKAGE_DIR / "sources"
MODEL_ID = "model.example.local-relief"


def _guide_block(after: str) -> str:
    """The first ```python block in the guide after the line holding *after*."""
    text = GUIDE.read_text(encoding="utf-8")
    start = text.index(after)
    match = re.search(r"```python\n(.*?)```", text[start:], re.S)
    assert match, f"no python block after {after!r} in the guide"
    return match.group(1)


def test_the_models_manifest_is_one_the_model_catalog_takes():
    from utk_curio.backend.app.model_catalog.domain.manifest import parse_manifest

    raw = json.loads((MODEL_DIR / "manifest.json").read_text(encoding="utf-8"))
    manifest = parse_manifest(raw, dir_name=MODEL_DIR.name)
    assert (manifest.id, manifest.runtime, manifest.task) == (MODEL_ID, "onnx", "image-to-image")
    entry = MODEL_DIR / raw["entry"]
    assert entry.is_file()
    assert raw["sizeBytes"] == entry.stat().st_size
    assert raw["node"] == "example.local-relief/local-relief@1"


def test_the_package_is_one_the_node_catalog_takes_and_its_integrity_holds():
    from utk_curio.backend.app.packages.repositories.archive import load_package_manifest_from_dir

    load_package_manifest_from_dir(PACKAGE_DIR)
    recorded = json.loads((PACKAGE_DIR / "integrity.json").read_text(encoding="utf-8"))["sha256"]
    on_disk = {
        str(path.relative_to(PACKAGE_DIR)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(PACKAGE_DIR.rglob("*"))
        if path.is_file() and path.name != "integrity.json" and "__pycache__" not in path.parts
    }
    assert recorded == on_disk


def test_the_onnx_file_answers_as_the_guide_says():
    """A 100 m tower alone on flat ground: +96 m at the tower, -4 m beside it
    (the guide's numbers), on a raster of a size the export never traced."""
    import onnxruntime as ort

    session = ort.InferenceSession(str(MODEL_DIR / "files" / "local_relief.onnx"), providers=["CPUExecutionProvider"])
    height = np.zeros((1, 1, 9, 13), np.float32)
    height[0, 0, 4, 6] = 100
    (relief,) = session.run(None, {"height": height})
    assert relief.shape == height.shape
    assert relief[0, 0, 4, 6] == pytest.approx(96)
    assert relief[0, 0, 4, 5] == pytest.approx(-4)
    assert relief[0, 0, 0, 0] == pytest.approx(0)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    release_connection()
    init_db()
    yield tmp_path
    release_connection()


def _run(code, workspace, *, file_path="", data_type="", **extra):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code

    _worker_init()
    result = execute_code(
        textwrap.indent(code, "    "), file_path, "curio.builtin/computation-analysis", data_type,
        save_dataset=False, media_dir=str(workspace / "media"), **extra,
    )
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "raster", result["output"]
    return result["output"]["path"]


def test_the_guides_two_nodes_run_in_the_sandbox_as_a_dataflow_runs_them(workspace):
    """The guide's Make Heights code, then the package's Local Relief code
    with the model resolved as the backend resolves it."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    heights_id = _run(_guide_block("**Make Heights**"), workspace)
    heights = load_from_duckdb(heights_id)
    assert (heights.width, heights.height, str(heights.crs)) == (64, 64, "EPSG:3857")

    node_code = (SOURCES / "local-relief.py").read_text(encoding="utf-8")
    relief_id = _run(
        node_code, workspace, file_path=heights_id, data_type="raster",
        package_modules={"root": str(SOURCES), "names": ["local_relief"]},
        models={MODEL_ID: str(MODEL_DIR)},
    )
    relief = load_from_duckdb(relief_id)
    assert (relief.width, relief.height, relief.crs, relief.transform) == (
        heights.width, heights.height, heights.crs, heights.transform,
    )
    values = relief.read(1)
    h = heights.read(1).astype(np.float64)
    # Each cell against the numpy reference: height minus the 5 by 5 mean.
    expected = np.empty_like(h)
    for r in range(h.shape[0]):
        for c in range(h.shape[1]):
            expected[r, c] = h[r, c] - h[max(0, r - 2):r + 3, max(0, c - 2):c + 3].mean()
    assert np.abs(values - expected).max() < 1e-3
    # As the guide says: flat ground and the tower's flat top at 0, its edge
    # above the street (red), the street beside it below (blue).
    assert values[0, 0] == pytest.approx(0) and values[37, 43] == pytest.approx(0)
    assert values[30, 36] > 40 and values[29, 36] < -10
