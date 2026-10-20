"""Raster math is Scout's (the plan answering komar41's review of his #914,
step 3, his issues 2 and 8).

The Raster Calculator's operations, ``choose``, statistics, writing, content
names and grid checks are the Scout package's module
``scout_rasters.raster_algebra``: ``raster_calculate(operation, rasters,
codes=None, ...)``, which writes where ``output_file`` says, and
``raster_statistics(...)``, with the arguments the old helpers took.
``absolute=True`` gives the size of a result, such as how much a depth
changed. SCOUT's tile helpers, ``tile_bounds`` and ``mosaic_web_tiles``, are
the package's too (``scout_rasters.web_tiles``).

A node reaches them by importing them: the Raster Calculator's own code, or a
node of a package that names Scout in ``dependencies.packages``, as Deep
Umbra does for ``tile_bounds``. A plain Python node no longer has them:
``curio_raster_calculate`` and ``curio_raster_statistics`` refuse, naming the
Raster Calculator. So the flood dataflow's two Average depth by period nodes,
which choose each period's depth, are Raster Calculators, whose input circles
take the layers they read beside rasters. Core keeps only what Compare
Scenarios' raster Difference subtracts with, until Compare is removed.

Package code is imported inside each test, through a run's staged copy of the
package's modules, so a checkout without it fails each test on its own and no
bytecode lands in ``packages/``.
"""
from __future__ import annotations

import ast
import contextlib
import importlib
import json
import math
import os
import textwrap
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[4]
SCOUT = REPO / "packages" / "curio.scout@1"
SOURCES = SCOUT / "sources"
MODULE = "scout_rasters"
STARTER = SOURCES / "raster-calculator.py"
CALCULATOR = "curio.scout/raster-calculator"
DEEP_UMBRA = REPO / "packages" / "model.scout.deep-umbra@1"
SHADOW = "model.scout.deep-umbra/accumulated-shadow"
FLOOD = REPO / "docs" / "examples" / "dataflows" / "quad-cities-flood-vulnerability.json"
#: The flood dataflow's node that averages each period's depth, in each scenario.
AVERAGE = "Average depth by period"
#: A node of no package, which a run hands no package's modules.
PLAIN = "curio.builtin/data-transformation"
#: What left core for the package. Curio's own code defines none of them.
MOVED = (
    "curio_raster_calculate", "curio_raster_statistics", "raster_calculate", "raster_statistics",
    "operate", "in_codes", "masked_bands", "dataset_grid", "write_raster", "_content_name",
    "tile_corner", "tile_bounds", "mosaic_web_tiles",
)
#: What core keeps for Compare Scenarios' raster Difference until Compare is
#: removed: the envelope subtraction and the grid checks it calls.
ENVELOPES = REPO / "utk_curio" / "sandbox" / "util" / "envelope_difference.py"
ENVELOPE_NAMES = {"RasterAlgebraError", "js_number", "grid_differences", "describe_grid", "subtract_envelopes"}
#: Folders of ``utk_curio/`` that hold no app code.
NOT_APP = {"tests", "node_modules", "dist", "__pycache__", "_shipped"}


@contextlib.contextmanager
def scout_module(tmp_path, name: str):
    """``scout_rasters.<name>``, importable the way a run of the package's node
    imports it: staged into a folder of the run's own."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run"
    run.mkdir()
    staged = stage_package_modules({"root": str(SOURCES), "names": [MODULE]}, str(run))
    assert staged == {"root": "package_modules", "names": [MODULE]}, staged
    with importable(str(run / staged["root"]), staged["names"]):
        yield importlib.import_module(f"{MODULE}.{name}")


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


def _values(dataset) -> list:
    return [[None if math.isnan(v) else float(v) for v in row] for row in dataset.read(1)]


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    return lambda name: str(folder / name)


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


def test_the_packages_raster_calculate_and_raster_statistics_work(tmp_path, out):
    """``raster_calculate`` takes the operation, the rasters and the codes the
    old helper took, and writes its raster where ``output_file`` says;
    ``raster_statistics`` gives the one row of statistics, nodata left out."""
    a = _raster(tmp_path / "a.tif", [[5.0, 7.0], [-9999.0, 1.5]])
    b = _raster(tmp_path / "b.tif", [[1.0, 2.0], [3.0, 0.25]])
    classes = _raster(tmp_path / "classes.tif", [[21, 0], [43, 21]], dtype="uint8", nodata=0)
    with scout_module(tmp_path, "raster_algebra") as algebra:
        difference = algebra.raster_calculate("subtract", [a, b], output_file=out)
        chosen = algebra.raster_calculate("choose", [classes, a, b], [21], output_file=out)
        table = algebra.raster_statistics(a)
        masked = algebra.raster_statistics(a, mask=classes, mask_values=[21])
    assert _values(difference) == [[4.0, 5.0], [None, 1.25]]
    assert os.path.dirname(difference.name) == os.path.dirname(out("x"))
    # 21 is chosen, a nodata class is no class, and 43 is not chosen.
    assert _values(chosen) == [[5.0, 2.0], [3.0, 1.5]]
    assert table.to_dict("records") == [{"mean": 4.5, "median": 5.0, "min": 1.5, "max": 7.0, "count": 3}]
    assert masked.to_dict("records") == [{"mean": 3.25, "median": 3.25, "min": 1.5, "max": 5.0, "count": 2}]


def test_absolute_gives_the_size_of_the_change(tmp_path, out):
    """komar41's issue 8: ``absolute=True`` gives the size of the result, so
    either subtraction gives how much a depth changed, 0 where it did not,
    and a cell with no value keeps none. Without it the result keeps its
    sign. The Raster Calculator's starter lists the option."""
    before = _raster(tmp_path / "before.tif", [[1.0, 4.0, 2.0, -9999.0]])
    after = _raster(tmp_path / "after.tif", [[3.0, 1.0, 2.0, 5.0]])
    with scout_module(tmp_path, "raster_algebra") as algebra:
        signed = algebra.raster_calculate("subtract", [after, before], output_file=out)
        sizes = [
            algebra.raster_calculate("subtract", pair, absolute=True, output_file=out)
            for pair in ([after, before], [before, after])
        ]
    assert _values(signed) == [[2.0, -3.0, 0.0, None]]
    for size in sizes:
        assert _values(size) == [[2.0, 3.0, 0.0, None]]
    starter = STARTER.read_text(encoding="utf-8")
    assert 'raster_calculate("subtract", [input_1, input_0], absolute=True, output_file=curio_output_file)' in starter


@pytest.mark.parametrize("call", [
    'curio_raster_calculate("subtract", [input_0, input_1])',
    "curio_raster_statistics(input_0, mask=input_1, mask_values=[1])",
])
def test_a_plain_python_node_calling_the_old_helpers_is_refused(workspace, call):
    """A Data Transformation, a node of no package, that calls a raster helper
    every Python node used to have, on two rasters on one grid, a call those
    helpers ran, is told to use a Raster Calculator and where its functions
    are."""
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    a = _raster(workspace / "a.tif", [[5.0, 7.0]])
    b = _raster(workspace / "b.tif", [[1.0, 0.0]], dtype="uint8", nodata=None)
    _worker_init()
    file_path = repr([save_to_duckdb(value, node_id=f"upstream-{i}") for i, value in enumerate((a, b))])
    result = execute_code(
        textwrap.indent(f"return {call}\n", "    "), file_path, PLAIN, "outputs",
        save_dataset=False, media_dir=str(workspace / "media"), input_slots=[0, 1],
    )
    name = call.split("(")[0]
    assert f"{name} was renamed: use a Raster Calculator node" in result["stderr"], result
    assert "from scout_rasters.raster_algebra import" in result["stderr"], result["stderr"]


def test_deep_umbra_declares_scout_and_its_node_is_handed_scouts_modules(tmp_curio):
    """Deep Umbra's node imports ``tile_bounds`` from Scout, which its
    manifest names in ``dependencies.packages``: a run of Accumulated Shadow
    is handed Deep Umbra's module and Scout's, its own first, as any node of
    a package that names another is (``python_modules.modules_for_node``)."""
    from utk_curio.backend.app.packages.application.python_modules import modules_for_node
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir

    manifest = json.loads((DEEP_UMBRA / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dependencies"]["packages"] == {"curio.scout@1": "*"}
    for package in (SCOUT, DEEP_UMBRA):
        install_package_from_directory("guest", package)
    assert modules_for_node("guest", SHADOW) == [
        {"root": str(package_dir("guest", DEEP_UMBRA.name) / "sources"), "names": ["deep_umbra"]},
        {"root": str(package_dir("guest", SCOUT.name) / "sources"), "names": [MODULE]},
    ]
    outputs = (DEEP_UMBRA / "sources" / "deep_umbra" / "node_outputs.py").read_text(encoding="utf-8")
    assert "from scout_rasters.web_tiles import tile_bounds" in outputs


def test_the_flood_dataflows_averages_by_period_are_raster_calculators():
    """The flood dataflow's two Average depth by period nodes choose each
    period's depth with the package's ``raster_calculate``, and a node of no
    package is handed no package's modules, so both are Raster Calculators.
    They read the riverside tracts and the waterways, two layers, which the
    calculator's input circles take beside rasters, as its starter says. No
    node of the dataflow calls the old helpers."""
    spec = json.loads(FLOOD.read_text(encoding="utf-8"))["dataflow"]
    averages = [n for n in spec["nodes"] if (n.get("metadata") or {}).get("packageTemplateLabel") == AVERAGE]
    assert len(averages) == 2, [n["id"] for n in averages]
    for node in averages:
        assert node["type"] == CALCULATOR, (node["id"], node["type"])
        assert "\nfrom scout_rasters.raster_algebra import raster_calculate\n" in node["content"], node["content"]
        assert (
            'raster_calculate("choose", [classes, nbs, none], codes=codes, output_file=curio_output_file)'
            in node["content"]
        ), node["content"]
    assert [n["id"] for n in spec["nodes"] if "curio_raster_" in (n.get("content") or "")] == []
    manifest = json.loads((SCOUT / "manifest.json").read_text(encoding="utf-8"))
    (calculator,) = [t for t in manifest["templates"] if t["id"] == "raster-calculator"]
    assert [sorted(port["types"]) for port in calculator["inputPorts"]] == [["GEODATAFRAME", "RASTER"]]
    assert "zones or a mask" in STARTER.read_text(encoding="utf-8")


def _app_modules():
    """Every Python file of Curio's own code, by its path from the repository."""
    for dirpath, dirnames, filenames in os.walk(REPO / "utk_curio"):
        dirnames[:] = sorted(d for d in dirnames if d not in NOT_APP and not d.startswith("."))
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                path = Path(dirpath) / filename
                yield path, path.relative_to(REPO).as_posix()


def test_no_core_module_defines_the_moved_functions():
    """None of the moved functions is defined in Curio's own code, the old
    module is gone, and the package defines each of them. Core keeps only
    Compare Scenarios' raster Difference: the envelope subtraction and the
    grid checks it calls, in a module of their own."""
    found = []
    for path, relative in _app_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        found += [
            f"{relative}:{node.lineno} {node.name}"
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in MOVED
        ]
    assert found == [], found
    assert not (REPO / "utk_curio" / "sandbox" / "util" / "raster_algebra.py").exists()
    defined = set()
    for module in ("raster_algebra.py", "web_tiles.py"):
        tree = ast.parse((SOURCES / MODULE / module).read_text(encoding="utf-8"))
        defined |= {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert set(MOVED) - {"curio_raster_calculate", "curio_raster_statistics"} <= defined, defined
    kept = ast.parse(ENVELOPES.read_text(encoding="utf-8"))
    public = {
        node.name for node in kept.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_")
    }
    assert public == ENVELOPE_NAMES, public
