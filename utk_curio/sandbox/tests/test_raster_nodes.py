"""Curio's raster algebra in a Python node: ``curio_raster_calculate`` and
``curio_raster_statistics``, which every Python node's code can call, run in
process and in an isolated child: a raster on the inputs' grid, and a table of
one row. (They were once the Raster Calculator and Raster Statistics nodes'
starter code; those kinds are Python nodes now.)

Every test imports the sandbox's modules itself, so a checkout without them
fails test by test rather than at collection.
"""
from __future__ import annotations

import json
import math
import textwrap
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
PYTHON = "curio.builtin/computation-analysis"

CALCULATE = 'return curio_raster_calculate("subtract", [input_0, input_1])\n'
STATISTICS = "return curio_raster_statistics(input_0, mask=input_1)\n"

#: The Python node that maps the change between an example's scenarios.
EXAMPLE_CALCULATORS = {
    "FloodScenarios": "8bdc7401-d983-5420-b863-b9aba4c4a397",
    "WhatIfShadows": "7465bb33-9916-53fe-806b-90becc9aa805",
}


def _raster(path, values, *, dtype="float64", nodata=-9999.0):
    import rasterio
    from affine import Affine

    array = np.asarray(values, dtype=dtype)
    with rasterio.open(
        path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0], count=1, dtype=dtype,
        crs="EPSG:4326", transform=Affine(0.001, 0.0, -90.5, 0.0, -0.001, 41.5), nodata=nodata,
    ) as target:
        target.write(array, 1)
    return rasterio.open(path)


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


def run_in_process(code, inputs, node_type, workspace):
    """Run *code* on *inputs* as a Python node's play does: one raster, or a
    tuple of them, one per input circle, which reach the node as a list of
    their outputs. ``(output, the value it holds)``."""
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    _worker_init()
    if isinstance(inputs, tuple):
        file_path = repr([save_to_duckdb(value, node_id=f"upstream-{i}") for i, value in enumerate(inputs)])
        data_type = "outputs"
    else:
        file_path, data_type = save_to_duckdb(inputs, node_id="upstream"), "raster"
    result = execute_code(
        textwrap.indent(code, "    "), file_path, node_type, data_type,
        save_dataset=False, media_dir=str(workspace / "media"),
    )
    assert result["stderr"] == "", result["stderr"]
    return result["output"], load_from_duckdb(result["output"]["path"])


def test_a_python_node_calculates_over_two_inputs(workspace):
    a = _raster(workspace / "a.tif", [[5.0, 7.0], [-9999.0, 1.5]])
    b = _raster(workspace / "b.tif", [[1.0, 2.0], [3.0, 0.25]])
    output, result = run_in_process(CALCULATE, (a, b), PYTHON, workspace)
    try:
        assert output["dataType"] == "raster"
        assert result.dtypes[0] == "float64"
        cells = result.read(1)
        assert cells[0].tolist() == [4.0, 5.0]
        assert math.isnan(cells[1, 0]) and cells[1, 1] == 1.25
        assert tuple(result.transform)[:6] == tuple(a.transform)[:6]
    finally:
        result.close()


def test_a_python_node_chooses_by_class(workspace):
    classes = _raster(workspace / "classes.tif", [[21, 0, 43]], dtype="uint8", nodata=0)
    nbs = _raster(workspace / "nbs.tif", [[1.0, 2.0, 3.0]])
    no_nbs = _raster(workspace / "no_nbs.tif", [[10.0, 20.0, 30.0]])
    code = 'return curio_raster_calculate("choose", [input_0, input_1, input_2], codes=[21, 31])\n'
    _output, result = run_in_process(code, (classes, nbs, no_nbs), PYTHON, workspace)
    try:
        assert result.read(1).tolist() == [[1.0, 20.0, 30.0]]
    finally:
        result.close()


@pytest.mark.parametrize("example", ["FloodScenarios", "WhatIfShadows"])
def test_an_examples_python_node_maps_the_absolute_change_between_its_scenarios(workspace, example):
    """The code SCOUT's flood and shadow examples map the change between their
    scenarios with, in a Python node: input 1 minus input 0, as its size."""
    flow = json.loads((REPO / "docs" / "examples" / "dataflows" / f"{example}.json").read_text(encoding="utf-8"))
    (node,) = [n for n in flow["dataflow"]["nodes"] if n["id"] == EXAMPLE_CALCULATORS[example]]
    assert node["type"] == PYTHON
    reference = _raster(workspace / "reference.tif", [[1.0, 2.0], [-9999.0, 4.0]])
    comparison = _raster(workspace / "comparison.tif", [[0.5, 2.0], [3.0, 6.0]])
    _output, result = run_in_process(node["content"], (reference, comparison), PYTHON, workspace)
    try:
        cells = result.read(1)
        assert cells[0].tolist() == [0.5, 0.0]
        assert math.isnan(cells[1, 0]) and cells[1, 1] == 2.0
    finally:
        result.close()


def test_a_python_node_summarises_a_raster_into_one_row(workspace):
    a = _raster(workspace / "a.tif", [[1.0, 2.0, -9999.0], [3.0, 4.0, 5.0]])
    output, table = run_in_process(STATISTICS, a, PYTHON, workspace)
    assert output["dataType"] == "dataframe"
    assert table.to_dict("records") == [{"mean": 3.0, "median": 3.0, "min": 1.0, "max": 5.0, "count": 5}]


def test_the_steps_run_in_an_isolated_child(tmp_path):
    """The child installs the same helpers: a raster it returns is written in
    its scratch directory, which the parent keeps."""
    from utk_curio.sandbox.isolation import child, zygote

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _raster(scratch / "a.tif", [[5.0, 7.0]]).close()
    _raster(scratch / "b.tif", [[1.0, 2.0]]).close()
    inputs = {"kind": "sequence", "container": "list",
              "items": [{"kind": "raster", "file": "a.tif"}, {"kind": "raster", "file": "b.tif"}]}

    def run(code, node_type):
        manifest = child.run_node({
            "code": textwrap.indent(code, "    "), "node_type": node_type, "data_type": "outputs",
            "scratch_dir": str(scratch), "input": inputs, "session_imports": [], "limits": {},
        }, zygote.build_namespace_template)
        assert manifest["ok"], manifest["stderr"]
        return manifest

    calculated = run(CALCULATE, PYTHON)
    child.write_result(calculated, str(scratch))
    from utk_curio.sandbox.isolation import supervisor

    descriptor = supervisor.read_child_manifest(str(scratch))["output"]
    assert descriptor["kind"] == "raster"
    import rasterio

    with rasterio.open(scratch / descriptor["file"]) as written:
        assert written.read(1).tolist() == [[4.0, 5.0]]

    counted = run("return curio_raster_statistics(input_0, where=lambda value: value > 6)\n", PYTHON)
    child.write_result(counted, str(scratch))
    assert supervisor.read_child_manifest(str(scratch))["output"]["kind"] == "dataframe"
