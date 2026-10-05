"""``scout.flood-simulation@1``: SCOUT's flood projection in Curio.

The proof: the package's port of SCOUT's ``simulate_flood_projection``, on a
block of Curio's dataset ``data.scout.quad-cities-flood``, gives the rasters
and metrics SCOUT's own function, imported unchanged, wrote for the same
block of SCOUT's float64 files: the same cells with no depth, every depth
within float32 rounding, the median and mean within a micrometre. Three
cases: 2020-2040 with every NbS and with none, and 2050-2080 with none.
``scripts/generate_scout_flood_fixture.py`` recorded them into
``fixtures/scout/flood/`` (see its ``ATTRIBUTION.md``).

The dataset: one manifest over seven files in ``data/``, SCOUT's names,
listed by ``data/bundle.json``; a node reads one by name with
``curio_load_data(id, part="<file>")``.

The example: example 25's own nodes, its Data Loading code reading the block
by name, both Simulate Flood nodes, Raster Statistics and the two Compare
Scenarios nodes, run in the sandbox with their widgets resolved as a run
resolves them.
"""
from __future__ import annotations

import base64
import contextlib
import importlib
import json
import re
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "scout.flood-simulation@1"
SOURCES = PACKAGE / "sources"
MODULE = "scout_flood_simulation"
NODE_TYPE = "scout.flood-simulation/simulate-flood"
EXAMPLE = REPO / "docs" / "examples" / "25-scout-flooding.json"
DATASET_ID = "data.scout.quad-cities-flood"
DATASET = REPO / "datasets" / f"{DATASET_ID}@1"
FILES = [
    "NBS_others_5m.tif",
    "2020_2040_NbS.tif", "2020_2040_noNbS.tif",
    "2050_2080_NbS.tif", "2050_2080_noNbS.tif",
    "2080_2100_NbS.tif", "2080_2100_noNbS.tif",
]

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scout" / "flood"
BLOCK = FIXTURES / "block" / "data"
CASES = json.loads((FIXTURES / "block.json").read_text(encoding="utf-8"))["cases"]
ALL_NBS = CASES["2020_2040_all"]["nbs"]


def _template() -> dict:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    (template,) = manifest["templates"]
    return template


def _example():
    """Example 25's dataflow, and its nodes by id."""
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))["dataflow"]
    return spec, {n["id"]: n for n in spec["nodes"]}


@contextlib.contextmanager
def _modules(tmp_path):
    """``(flood_simulation, node_outputs)``, staged as a run stages them."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run"
    run.mkdir()
    staged = stage_package_modules({"root": str(SOURCES), "names": [MODULE]}, str(run))
    with importable(str(run / staged["root"]), staged["names"]):
        yield (
            importlib.import_module(f"{MODULE}.flood_simulation"),
            importlib.import_module(f"{MODULE}.node_outputs"),
        )


@contextlib.contextmanager
def _block_rasters(year):
    """The block's classes, and *year*'s depths with NbS and without."""
    import rasterio

    period = year.replace(" - ", "_")
    names = ["NBS_others_5m.tif", f"{period}_NbS.tif", f"{period}_noNbS.tif"]
    with contextlib.ExitStack() as stack:
        yield tuple(stack.enter_context(rasterio.open(BLOCK / name)) for name in names)


def _scout(case):
    """SCOUT's raster values, grid and metrics for *case*."""
    import pandas as pd
    import rasterio

    with rasterio.open(FIXTURES / f"scout_{case}.tif") as src:
        values, transform = src.read(1), src.transform
    return values, transform, pd.read_csv(FIXTURES / f"scout_{case}.csv").iloc[0]


def _assert_scouts(raster, case):
    import numpy as np

    ref, transform, _metrics = _scout(case)
    ours = raster.read(1)
    assert ours.shape == ref.shape
    assert np.allclose(list(raster.transform)[:6], list(transform)[:6], rtol=0, atol=1e-9)
    assert np.array_equal(np.isnan(ours), np.isnan(ref))
    cells = ~np.isnan(ref)
    assert cells.any()
    assert np.allclose(ours[cells], ref[cells], rtol=2 ** -23, atol=0)


# ---------------------------------------------------------------------------
# The proof
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", sorted(CASES))
def test_the_port_reproduces_scouts_projection(tmp_path, case):
    """SCOUT's function on SCOUT's float64 block, against the port on Curio's
    float32 block: the same raster and the same metrics."""
    year, nbs = CASES[case]["year"], CASES[case]["nbs"]
    with _modules(tmp_path) as (_flood, outputs), _block_rasters(year) as rasters:
        raster = outputs.simulate_flood(rasters, nbs, lambda name: str(tmp_path / name))
    try:
        _assert_scouts(raster, case)
        _ref, _transform, metrics = _scout(case)
        tags = raster.tags()
        assert tags["nbs"] == ("; ".join(nbs) or "none")
        for column, tag in (("median flood depth", "median_flood_depth"), ("mean flood depth", "mean_flood_depth")):
            assert float(tags[tag]) == pytest.approx(metrics[column], abs=1e-6), column
    finally:
        raster.close()


def test_the_solutions_change_the_depth():
    """Not two identical projections agreeing: with every NbS the block floods
    less deep than with none."""
    assert _scout("2020_2040_all")[2]["median flood depth"] < _scout("2020_2040_none")[2]["median flood depth"]


def test_no_depth_is_nan_however_scout_marks_it(tmp_path):
    """SCOUT marks a missing depth as NaN, or, in one file, as the float64
    nodata value; the projection holds NaN for both, and its metrics leave
    them out."""
    import numpy as np

    with _modules(tmp_path) as (flood, _outputs):
        classes = np.array([[21, 0, 21, 0]], dtype="uint8")
        nbs = np.array([[1.0, 9.0, np.nan, 9.0]])
        no_nbs = np.array([[9.0, 2.0, 9.0, -1.7976931348623157e308]])
        combined = flood.combine(classes, nbs, no_nbs, ["Bioswales/Infiltration trenches"], -1.7976931348623157e308)
        assert combined[0, :2].tolist() == [1.0, 2.0] and np.isnan(combined[0, 2:]).all()
        assert flood.metrics(combined) == {"median flood depth": 1.5, "mean flood depth": 1.5}
        assert flood.metrics(np.full((2, 2), np.nan)) == {"median flood depth": None, "mean flood depth": None}


def test_scouts_names_choose_scouts_codes(tmp_path):
    with _modules(tmp_path) as (flood, _outputs):
        assert flood.nbs_codes(ALL_NBS) == {21, 31, 43, 52, 71, 81, 90, 95}
        assert flood.nbs_codes(["Bioswales"]) == {71, 81}
        assert flood.nbs_codes([]) == set()
        with pytest.raises(ValueError, match="No nature-based solution is called 'Rain gardens'"):
            flood.nbs_codes(["Rain gardens"])


def test_an_input_the_node_cannot_read_says_why(tmp_path):
    from utk_curio.sandbox.util.rasters import read_window

    with _modules(tmp_path) as (_flood, outputs), _block_rasters("2020 - 2040") as (classes, nbs, no_nbs):
        out = lambda name: str(tmp_path / name)  # noqa: E731
        with pytest.raises(ValueError, match=re.escape("Simulate Flood reads three rasters")):
            outputs.simulate_flood((classes, nbs), [], out)
        # A depth read over other bounds than the classes.
        t = nbs.transform
        smaller = read_window(nbs, (t.c, t.f + 100 * t.e, t.c + 100 * t.a, t.f), out, name="nbs")
        try:
            with pytest.raises(ValueError, match="on one grid; nbs is 100 by 100 cells"):
                outputs.simulate_flood((classes, smaller, no_nbs), [], out)
        finally:
            smaller.close()


# ---------------------------------------------------------------------------
# The dataset, the template and the example
# ---------------------------------------------------------------------------

def test_the_dataset_is_seven_files_under_one_manifest():
    """One manifest; SCOUT's seven files side by side in data/, on one grid,
    each listed by data/bundle.json under its own name."""
    import rasterio

    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == DATASET_ID and manifest["format"] == "bundle"
    assert manifest["dataFile"] == "data/bundle.json"
    parts = json.loads((DATASET / "data" / "bundle.json").read_text(encoding="utf-8"))["parts"]
    assert [p["file"] for p in parts] == [f"data/{name}" for name in FILES]
    assert {(p["kind"], p["format"]) for p in parts} == {("raster", "geotiff")}
    assert sorted(p.name for p in (DATASET / "data").iterdir()) == sorted([*FILES, "bundle.json"])
    grids = set()
    for name in FILES:
        with rasterio.open(DATASET / "data" / name) as src, rasterio.open(BLOCK / name) as block:
            grids.add((str(src.crs), tuple(src.transform)[:6], src.width, src.height))
            assert src.dtypes == block.dtypes == (("uint8",) if name.startswith("NBS") else ("float32",))
    assert len(grids) == 1


def test_curio_load_data_reads_one_file_by_name(tmp_path):
    """The dataset's own bundle, read as a node reads it: one file by its
    name or its label, windowed by bounds, and a name it does not have
    refused with the names it does."""
    from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers

    namespace = {}
    install_catalog_helpers(
        namespace, data_path=lambda _id: str(DATASET / "data" / "bundle.json"),
        formats={DATASET_ID: {"format": "bundle"}}, collections=None, media_dir=str(tmp_path), models=None,
    )
    load = namespace["curio_load_data"]
    with load(DATASET_ID, part="2020_2040_NbS.tif") as by_name, \
            load(DATASET_ID, part="Flood depth 2020-2040 with NbS") as by_label:
        assert by_name.name == by_label.name and by_name.name.endswith("2020_2040_NbS.tif")
        assert (by_name.width, by_name.height) == (2592, 2064)
        t = by_name.transform
        box = (t.c, t.f + 10 * t.e, t.c + 20 * t.a, t.f)
    with load(DATASET_ID, part="2020_2040_NbS.tif", bounds=box) as window:
        assert (window.width, window.height) == (20, 10)
    with pytest.raises(ValueError, match=r"has no file 'rain\.tif'; its files are NBS_others_5m\.tif, 2020_2040_NbS"):
        load(DATASET_ID, part="rain.tif")


def test_the_template_declares_the_widget_its_source_reads():
    template = _template()
    assert template["hasWidgets"] is True
    (widget,) = template["widgets"]
    assert widget["name"] == "nbs" and widget["type"] == "checkbox-group"
    assert widget["default"] == ALL_NBS == widget["options"]["choices"]
    source = (PACKAGE / template["source"]).read_text(encoding="utf-8")
    assert re.findall(r"\[!!\s*(\w+)\s*!!\]", source) == ["nbs"]


def test_the_example_runs_the_template_as_the_palette_drops_it():
    spec, nodes = _example()
    assert spec["packages"] == ["scout.flood-simulation@1"]
    assert [d["datasetId"] for d in spec["datasets"]] == [DATASET_ID]
    floods = [n for n in nodes.values() if n["type"] == NODE_TYPE]
    assert len(floods) == 2
    source = (PACKAGE / _template()["source"]).read_text(encoding="utf-8")
    assert all(n["content"] == source for n in floods)
    assert sorted(len(n["metadata"]["widgets"][0]["value"]) for n in floods) == [0, len(ALL_NBS)]
    # Each scenario holds one of them.
    scenario_nodes = {node_id for s in spec["scenarios"] for node_id in s["nodes"]}
    assert {n["id"] for n in floods} <= scenario_nodes


def test_the_examples_default_area_fits_an_autark_map():
    """The default box reads inside the dataset, and at most 2048 by 2048 cells."""
    import rasterio

    from utk_curio.sandbox.util.rasters import window_of

    _spec, nodes = _example()
    (loader,) = [n for n in nodes.values() if n["type"] == "curio.builtin/data-loading"]
    box = {w["name"]: w["default"] for w in loader["metadata"]["widgets"]}
    with rasterio.open(DATASET / "data" / FILES[0]) as classes:
        window = window_of(classes, (box["west"], box["south"], box["east"], box["north"]), DATASET_ID)
    assert int(window.width) * int(window.height) <= 2048 * 2048
    assert max(int(window.width), int(window.height)) <= 8192


# ---------------------------------------------------------------------------
# The example's nodes, in the sandbox
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


def _run(node, input_art, data_type, workspace, *, values=None, inputs=1):
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.app.worker import execute_code

    widgets = [dict(w) for w in node["metadata"].get("widgets", [])]
    for widget in widgets:
        if widget["name"] in (values or {}):
            widget["value"] = values[widget["name"]]
    code, problems = resolve_references(
        node["content"], widgets, "python", inputs=[{"slot": slot} for slot in range(inputs)],
    )
    assert problems == [], problems
    result = execute_code(
        textwrap.indent(code, "    "), input_art, node["type"], data_type,
        save_dataset=False, media_dir=str(workspace / "media"),
        package_modules={"root": str(SOURCES), "names": [MODULE]} if node["type"] == NODE_TYPE else None,
        dataset_paths={DATASET_ID: str(BLOCK / "bundle.json")},
        dataset_formats={DATASET_ID: {"format": "bundle"}},
    )
    assert result["stderr"] == "", result["stderr"]
    return result["output"]["path"]


def test_the_examples_nodes_reproduce_scout(workspace):
    """The loader reads the block's files by name for 2020-2040 (the
    dataset's id resolved to the block); each Simulate Flood node gives
    SCOUT's projection for its scenario, Raster Statistics SCOUT's median,
    the Difference node subtracts with NbS from without, and the Chart node
    stacks one row per scenario."""
    import rasterio
    from rasterio.io import MemoryFile

    from utk_curio.sandbox.app.worker import _worker_init
    from utk_curio.sandbox.util.parsers import load_from_duckdb
    from utk_curio.sandbox.util.scenario_difference import is_raster_request

    _worker_init()
    _spec, nodes = _example()
    loader = next(n for n in nodes.values() if n["type"] == "curio.builtin/data-loading")
    floods = {len(n["metadata"]["widgets"][0]["value"]): n for n in nodes.values() if n["type"] == NODE_TYPE}
    stats = next(n for n in nodes.values() if n["type"] == "curio.builtin/raster-statistics")
    compares = {n["metadata"]["compareScenarios"]["mode"]: n for n in nodes.values()
                if n["type"] == "curio.builtin/compare-scenarios"}

    with rasterio.open(BLOCK / FILES[0]) as block:
        west, south, east, north = block.bounds.left, block.bounds.bottom, block.bounds.right, block.bounds.top
    loaded = _run(loader, "", "file", workspace,
                  values={"west": west, "south": south, "east": east, "north": north, "timeline": "2020 - 2040"})

    projected = {}
    for count, case in ((len(ALL_NBS), "2020_2040_all"), (0, "2020_2040_none")):
        projected[case] = _run(floods[count], loaded, "file", workspace)
        raster = load_from_duckdb(projected[case])
        try:
            _assert_scouts(raster, case)
        finally:
            raster.close()

    medians, stat_of = {}, {}
    for case, art in projected.items():
        stat_of[case] = _run(stats, art, "file", workspace)
        medians[case] = float(load_from_duckdb(stat_of[case])["median"].iloc[0])
        assert medians[case] == pytest.approx(_scout(case)[2]["median flood depth"], abs=1e-5)

    # Input 0 is the scenario without NbS, the reference; input 1 the one with
    # them. Two rasters make the request the sandbox's API completes through
    # Autark (scenario_difference.complete_raster_difference, tested in the
    # sandbox suite): each side its scenario and its raster.
    pair = repr([projected["2020_2040_none"], projected["2020_2040_all"]])
    request = load_from_duckdb(_run(compares["difference"], pair, "outputs", workspace, inputs=2))
    assert is_raster_request(request), request
    assert (request["reference"]["name"], request["comparison"]["name"]) == ("No NbS", "With NbS")
    for role, case in (("reference", "2020_2040_none"), ("comparison", "2020_2040_all")):
        with MemoryFile(base64.b64decode(request[role]["geotiff"])) as memory, memory.open() as side:
            _assert_scouts(side, case)

    chart = load_from_duckdb(_run(
        compares["chart"], repr([stat_of["2020_2040_none"], stat_of["2020_2040_all"]]), "outputs", workspace, inputs=2,
    ))
    assert list(chart["scenario_name"]) == ["No NbS", "With NbS"]
    assert list(chart["median"]) == pytest.approx([medians["2020_2040_none"], medians["2020_2040_all"]])
