"""``scout.flood@1``: SCOUT's flood function in Curio (#662, step 18).

The proof: SCOUT's own ``simulate_flood_projection`` (``fixtures/scout_flood/``,
copied unchanged) and the package's port, run as SCOUT's flood example runs it on
the Data Catalog's crops of SCOUT's rasters, write the same depth raster (profile,
cells and tags) and the same median and mean, for each period and for no, some
and all nature-based solutions (NbS). And the crops stand for SCOUT's full
rasters: what SCOUT's function computes from the crops is what it computed from
SCOUT's own 2592 by 2064 cell files (``PINS``, printed by
``scripts/build_scout_flood_datasets.py --pins``), so the port on the crops gives
SCOUT's results.

The node: its template, with the widgets its manifest declares resolved as a run
resolves them, reads the seven datasets by id through ``curio_data_path`` and runs
in the sandbox with its package's modules (#719). It returns ``(depth, metrics)``,
the two nodes the shipped example puts after it pick each part, and the depth is
a raster the Autark node's raster path (#718) loads.

Package code is imported inside each test, through a run's staged copy of the
package's modules, so a checkout without the package fails each test on its own
and no bytecode lands in ``packages/``.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "scout.flood@1"
SOURCES = PACKAGE / "sources"
MODULE = "scout_flood"
NODE_TYPE = "scout.flood/flood-projection"
PYTHON_TYPE = "curio.builtin/computation-analysis"
DATAFLOW = REPO / "docs" / "examples" / "dataflows" / "FloodScenarios.json"
SCOUT_FUNCTION = Path(__file__).resolve().parent / "fixtures" / "scout_flood" / "flood_simulation.py"

CLASSES = "data.scout.flood-nbs-classes"
PERIODS = ("2020 - 2040", "2050 - 2080", "2080 - 2100")
ALL_NBS = [
    "Bioswales/Infiltration trenches", "Permeable pavements", "Retention ponds",
    "Infiltration trench", "Bioswales", "Constructed wetlands",
]


def _depth_id(period: str, nbs: bool) -> str:
    start, end = period.split(" - ")
    return f"data.scout.flood-depth-{start}-{end}-{'nbs' if nbs else 'no-nbs'}"


DATASET_IDS = [CLASSES] + [_depth_id(p, nbs) for p in PERIODS for nbs in (True, False)]

#: The name SCOUT's function reads each dataset's file under.
SCOUT_NAMES = {CLASSES: "NBS_others_5m_4326_cropped_cleaned_resampled.tif"}
for _period in PERIODS:
    _stem = _period.replace(" - ", "_")
    SCOUT_NAMES[_depth_id(_period, True)] = f"{_stem}_NbS_4326_cropped.tif"
    SCOUT_NAMES[_depth_id(_period, False)] = f"{_stem}_noNbS_4326_cropped.tif"

#: SCOUT's grid: the transform of every one of its seven rasters.
SCOUT_GRID = (0.00010133941049058334, 0.0, -90.6879323, 0.0, -0.00010133941049058334, 41.62421049999999)
#: Where the crops start on it, and their size.
CROP_COLUMN, CROP_ROW, CROP_SIZE = 1984, 1520, 320
#: The template's default corners, (top, left, bottom, right).
EXAMPLE = (41.4669, -90.4836, 41.441, -90.4577)
#: What the Autark node's raster path loads at its own size (utils/raster/rasterLoad.ts).
AUTARK_MAX_CELLS = 2048 * 2048
AUTARK_MAX_SIDE = 8192


@dataclass(frozen=True)
class Pin:
    """What SCOUT's function computed from SCOUT's full files: the shape, the
    sha256 of the cells and the transform of the raster it wrote, and the median
    and mean of those cells."""

    shape: tuple
    median: float
    mean: float
    cells: str
    transform: tuple


#: Region (top, left, bottom, right), period and chosen NbS, as
#: ``PROOF_CASES`` in ``scripts/build_scout_flood_datasets.py``.
CASES = {
    "example-2020-all": (EXAMPLE, "2020 - 2040", ALL_NBS),
    "example-2020-none": (EXAMPLE, "2020 - 2040", []),
    "example-2050-none": (EXAMPLE, "2050 - 2080", []),
    "example-2050-all": (EXAMPLE, "2050 - 2080", ALL_NBS),
    "example-2080-some": (EXAMPLE, "2080 - 2100", ["Bioswales", "Constructed wetlands"]),
    "inner-2020-some": ((41.46213, -90.47912, 41.44587, -90.46345), "2020 - 2040", ["Retention ponds", "Permeable pavements"]),
}
_EXAMPLE_TRANSFORM = (0.00010133941049058334, 0.0, -90.4836, 0.0, -0.00010133941049058334, 41.4669)
PINS = {
    "example-2020-all": Pin(shape=(256, 256), median=3.7056172688802085, mean=4.743663890809282,
        cells="b6ffa6fca5f0824c76122c3127f1e98075ddc008bb51de586622c57b11b8f5e9",
        transform=_EXAMPLE_TRANSFORM),
    "example-2020-none": Pin(shape=(256, 256), median=5.788970947265625, mean=5.822848300261312,
        cells="33af69bd2a6ae9d049a8b216c017db200f5b629cecfa5affe9cb54a682f1d6df",
        transform=_EXAMPLE_TRANSFORM),
    "example-2050-none": Pin(shape=(256, 256), median=7.083333333333334, mean=5.64559364726481,
        cells="6349a837a654c0c76ecdde8a8884277a7ecd18e391abddadca639d36673d1999",
        transform=_EXAMPLE_TRANSFORM),
    "example-2050-all": Pin(shape=(256, 256), median=5.666666666666667, mean=5.202220484662029,
        cells="0dd696715f4d25b44544c4cc8b62c5601285c58c7793cea4f25a67051df089c0",
        transform=_EXAMPLE_TRANSFORM),
    "example-2080-some": Pin(shape=(256, 256), median=5.801829020182292, mean=5.399905484745865,
        cells="984f29f3547ddb9652c4cadf930dddb4c264c794f6cea3dd0af6160d53c97018",
        transform=_EXAMPLE_TRANSFORM),
    "inner-2020-some": Pin(shape=(160, 155), median=5.997294108072917, mean=6.153190826617249,
        cells="0957596fb642f1a6881bfcf0cd55bd6640b36a3df405750ee742bc11600637db",
        transform=(0.00010133941049058334, 0.0, -90.47912, 0.0, -0.00010133941049058334, 41.46213)),
}


def _template() -> dict:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    (template,) = manifest["templates"]
    return template


def _source() -> str:
    return (PACKAGE / _template()["source"]).read_text(encoding="utf-8")


def _data_file(dataset_id: str) -> Path:
    root = REPO / "datasets" / f"{dataset_id}@1"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return root / manifest["dataFile"]


def _rasters() -> dict:
    """The port's ``rasters``, as the template builds it from the catalog."""
    rasters = {"classes": str(_data_file(CLASSES))}
    for period in PERIODS:
        rasters[period] = (str(_data_file(_depth_id(period, True))), str(_data_file(_depth_id(period, False))))
    return rasters


@contextlib.contextmanager
def scout_flood(tmp_path):
    """The port's module, importable the way a run of the package's node
    imports it: staged into a folder of the run's own."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run"
    run.mkdir()
    staged = stage_package_modules({"root": str(SOURCES), "names": [MODULE]}, str(run))
    assert staged == {"root": "package_modules", "names": [MODULE]}, staged
    with importable(str(run / staged["root"]), staged["names"]):
        yield importlib.import_module(f"{MODULE}.flood_simulation")


def _scout_function():
    spec = importlib.util.spec_from_file_location("scout_original_flood_simulation", SCOUT_FUNCTION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.simulate_flood_projection


def run_scout(tmp_path, monkeypatch, region, period, chosen):
    """SCOUT's function as SCOUT's flood example calls it, in a folder laid out
    as it reads one, on the catalog's crops: ``(profile, cells, tags, metrics)``
    of the raster and the metrics file it writes."""
    import rasterio

    folder = tmp_path / "scout"
    rasters = folder / "models" / "flooding" / "data_substitutes"
    rasters.mkdir(parents=True)
    for dataset_id, name in SCOUT_NAMES.items():
        (rasters / name).symlink_to(_data_file(dataset_id))
    monkeypatch.chdir(folder)
    top, left, bottom, right = region
    _scout_function()(f"{left!r}, {top!r}", f"{right!r}, {bottom!r}", "A", year=period, use_NBS_classes=list(chosen))
    with rasterio.open(folder / "data" / "served" / "raster" / "A.tif") as raster:
        written = (dict(raster.profile), raster.read(1), raster.tags())
    metrics = (folder / "data" / "served" / "metric" / "A.csv").read_text(encoding="utf-8")
    return (*written, metrics)


def _scout_numbers(metrics: str) -> tuple[float, float]:
    """The median and the mean SCOUT's metrics file holds."""
    header, row = metrics.splitlines()[:2]
    assert header == "median flood depth,mean flood depth", header
    median, mean = (float(value) for value in row.split(","))
    return median, mean


# ---------------------------------------------------------------------------
# The proof
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", sorted(CASES))
def test_scouts_function_on_the_crops_gives_what_it_gave_on_scouts_files(tmp_path, monkeypatch, case):
    """The crops stand for SCOUT's rasters: on them SCOUT's function writes the
    cells, transform, median and mean it wrote from SCOUT's full files."""
    import numpy as np

    region, period, chosen = CASES[case]
    profile, cells, _tags, metrics = run_scout(tmp_path, monkeypatch, region, period, chosen)
    pin = PINS[case]
    assert cells.shape == pin.shape
    assert hashlib.sha256(cells.tobytes()).hexdigest() == pin.cells
    assert tuple(profile["transform"])[:6] == pytest.approx(pin.transform, abs=1e-12)
    median, mean = _scout_numbers(metrics)
    assert median == pin.median
    assert mean == pytest.approx(pin.mean, rel=1e-12)
    # Not two empty windows agreeing: the region holds depths.
    assert int(np.isfinite(cells).sum()) > 1000


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_port_writes_what_scouts_function_writes(tmp_path, monkeypatch, case):
    """The port, given the corners as Curio locations, returns the raster SCOUT
    writes (the same profile, cells and tags) and SCOUT's metrics, exactly."""
    region, period, chosen = CASES[case]
    profile, cells, tags, metrics = run_scout(tmp_path, monkeypatch, region, period, chosen)
    top, left, bottom, right = region
    out = tmp_path / "out"
    out.mkdir()
    with scout_flood(tmp_path) as port:
        depth, table = port.simulate_flood_projection(
            {"lat": top, "lon": left}, {"lat": bottom, "lon": right}, lambda name: str(out / name),
            year=period, use_NBS_classes=list(chosen), rasters=_rasters(),
        )
    try:
        assert dict(depth.profile) == profile
        assert depth.read(1).tobytes() == cells.tobytes()
        assert depth.tags() == tags
    finally:
        depth.close()
    assert table.to_csv(index=False) == metrics
    assert (float(table["median flood depth"][0]), float(table["mean flood depth"][0])) == _scout_numbers(metrics)


def test_scouts_lon_lat_text_gives_the_same_as_locations(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    with scout_flood(tmp_path) as port:
        top, left, bottom, right = EXAMPLE
        by_text = port.simulate_flood_projection(
            f"{left}, {top}", f"{right}, {bottom}", lambda name: str(out / name), rasters=_rasters(),
        )
        by_location = port.simulate_flood_projection(
            {"lat": top, "lon": left}, {"lat": bottom, "lon": right}, lambda name: str(out / name), rasters=_rasters(),
        )
    try:
        assert by_text[0].name == by_location[0].name
        assert by_text[1].equals(by_location[1])
    finally:
        by_text[0].close()
        by_location[0].close()


# ---------------------------------------------------------------------------
# The crops
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dataset_id", DATASET_IDS)
def test_each_crop_keeps_scouts_grid(dataset_id):
    """A crop lies on SCOUT's grid, at whole cells, and holds the example's
    region with 32 cells to spare on every side."""
    import rasterio
    from rasterio.windows import from_bounds

    manifest = json.loads((REPO / "datasets" / f"{dataset_id}@1" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "geotiff" and manifest["publisher"] == "SCOUT", manifest
    assert "urban-toolkit/scout" in manifest["description"]
    with rasterio.open(_data_file(dataset_id)) as crop:
        assert crop.crs.to_epsg() == 4326
        assert (crop.width, crop.height, crop.count) == (CROP_SIZE, CROP_SIZE, 1)
        a, b, c, d, e, f = tuple(crop.transform)[:6]
        assert (a, b, d, e) == (SCOUT_GRID[0], 0.0, 0.0, SCOUT_GRID[4])
        assert (c - SCOUT_GRID[2]) / a == pytest.approx(CROP_COLUMN, abs=1e-6)
        assert (f - SCOUT_GRID[5]) / e == pytest.approx(CROP_ROW, abs=1e-6)
        if dataset_id == CLASSES:
            assert crop.dtypes == ("uint8",) and crop.nodata == 0
        else:
            assert crop.dtypes == ("float64",) and crop.nodata == -1.7976931348623157e308
        top, left, bottom, right = EXAMPLE
        window = from_bounds(left, bottom, right, top, transform=crop.transform)
        assert window.col_off >= 32 and window.row_off >= 32
        assert window.col_off + window.width <= CROP_SIZE - 32
        assert window.row_off + window.height <= CROP_SIZE - 32


def test_the_class_crop_holds_every_nbs_code(tmp_path):
    """Each of the six choices changes something in the example's region."""
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds

    with scout_flood(tmp_path) as port:
        codes = sorted(port.NBS_CLASSES)
        assert port.NBS_NAMES == ALL_NBS
    with rasterio.open(_data_file(CLASSES)) as crop:
        top, left, bottom, right = EXAMPLE
        cells = crop.read(1, window=from_bounds(left, bottom, right, top, transform=crop.transform))
    present = {int(code) for code in np.unique(cells)}
    assert present == {0, *codes}, present


# ---------------------------------------------------------------------------
# The template
# ---------------------------------------------------------------------------

def test_the_template_names_the_seven_datasets_it_reads():
    """The node reads its rasters by literal ``curio_data_path("<id>")`` calls,
    the only kind a run resolves, and they are the seven SCOUT crops."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code

    assert dataset_ids_in_code(_source()) == DATASET_IDS
    shipped = sorted(p.name for p in (REPO / "datasets").glob("data.scout.flood-*"))
    assert shipped == sorted(f"{dataset_id}@1" for dataset_id in DATASET_IDS)


def test_the_template_declares_the_widgets_its_source_reads(tmp_path):
    template = _template()
    assert template["hasWidgets"] is True and template["inputPorts"] == []
    widgets = {w["name"]: w for w in template["widgets"]}
    assert [w["name"] for w in template["widgets"]] == ["topleft", "bottomright", "year", "use_NBS_classes"]
    assert widgets["topleft"]["type"] == widgets["bottomright"]["type"] == "location"
    top, left, bottom, right = EXAMPLE
    assert widgets["topleft"]["default"] == {"lat": top, "lon": left}
    assert widgets["bottomright"]["default"] == {"lat": bottom, "lon": right}
    assert widgets["year"]["type"] == "choice" and widgets["year"]["options"]["display"] == "radio"
    assert widgets["year"]["options"]["choices"] == list(PERIODS) and widgets["year"]["default"] == PERIODS[0]
    assert widgets["use_NBS_classes"]["type"] == "checkbox-group"
    assert widgets["use_NBS_classes"]["options"]["choices"] == ALL_NBS
    assert widgets["use_NBS_classes"]["default"] == ALL_NBS
    with scout_flood(tmp_path) as port:
        assert list(port.PERIODS) == list(PERIODS)
    assert re.findall(r"\[!!\s*(\w+)\s*!!\]", _source()) == ["topleft", "bottomright", "year", "use_NBS_classes"]


# ---------------------------------------------------------------------------
# The shipped dataflow
# ---------------------------------------------------------------------------

def _dataflow() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]


def test_the_shipped_dataflow_runs_the_template_with_the_shared_period():
    """``FloodScenarios.json`` is how its CI run reaches this package. Its two
    Flood Projection nodes hold the template's source with one change, the
    period read from the timeline Parameter node, and the template's widgets
    with their NbS choice; their code resolves with nothing left over."""
    from utk_curio.backend.app.execution.code_references import resolve_references

    spec = _dataflow()
    assert spec["packages"] == ["scout.flood@1"]
    assert [ref["datasetId"] for ref in spec["datasets"]] == DATASET_IDS
    nodes = {n["id"]: n for n in spec["nodes"]}
    (parameter,) = [n for n in spec["nodes"] if n["type"] == "curio.builtin/parameter"]
    (timeline,) = parameter["metadata"]["widgets"]
    year = next(w for w in _template()["widgets"] if w["name"] == "year")
    assert timeline["name"] == "timeline"
    assert {k: timeline[k] for k in ("type", "default", "options")} == {k: year[k] for k in ("type", "default", "options")}

    floods = [n for n in spec["nodes"] if n["type"] == NODE_TYPE]
    assert len(floods) == 2
    expected_code = _source().replace("[!! year !!]", "[!! @timeline !!]")
    assert expected_code != _source()
    chosen = {}
    for node in floods:
        assert node["content"] == expected_code
        widgets = node["metadata"]["widgets"]
        values = [w.pop("value") for w in copy.deepcopy(widgets) if w["name"] == "use_NBS_classes"]
        assert [{k: v for k, v in w.items() if k != "value"} for w in widgets] == _template()["widgets"]
        chosen[node["id"]] = values[0]
        code, problems = resolve_references(node["content"], widgets, "python", shared=[timeline])
        assert problems == [], problems
        assert "year=\"2020 - 2040\"" in code

    scenarios = {s["id"]: s for s in spec["scenarios"]}
    assert set(scenarios) == {"no-nbs", "nbs"}
    by_name = {}
    for scenario in scenarios.values():
        (flood,) = [nodes[i] for i in scenario["nodes"] if nodes[i]["type"] == NODE_TYPE]
        by_name[scenario["name"]] = flood
        pickers = sorted(nodes[i]["content"].splitlines()[-1] for i in scenario["nodes"] if i != flood["id"])
        assert pickers == ["return arg[0]", "return arg[1]"]
    assert chosen[by_name["No NbS"]["id"]] == [] and chosen[by_name["NbS"]["id"]] == ALL_NBS
    # The NbS scenario is a copy of the other: each node names the one it came from.
    copies = {nodes[i]["metadata"]["copiedFrom"][-1] for i in scenarios["nbs"]["nodes"]}
    assert copies == set(scenarios["no-nbs"]["nodes"])


def test_the_shipped_dataflows_compare_nodes_hold_the_code_they_write():
    """Each Compare Scenarios node holds the code it writes for its two inputs,
    No NbS in circle 0 and NbS in circle 1 (``utils/compare/compareCode.ts``):
    one in Difference, NbS minus No NbS, and one charting the median depth."""
    spec = _dataflow()
    entries = '    ("no-nbs", "No NbS", [!! input 0 !!]),\n    ("nbs", "NbS", [!! input 1 !!]),\n])\n'
    compares = {n["metadata"]["compareScenarios"]["mode"]: n for n in spec["nodes"]
                if n["type"] == "curio.builtin/compare-scenarios"}
    assert set(compares) == {"difference", "chart"}
    labels = [
        {"scenario": "no-nbs", "name": "No NbS", "color": "#e76f51"},
        {"scenario": "nbs", "name": "NbS", "color": "#2a9d8f"},
    ]
    for mode, call in (("difference", "curio_difference_scenarios"), ("chart", "curio_stack_scenarios")):
        node = compares[mode]
        assert node["metadata"]["compareScenarios"]["inputs"] == labels
        assert node["content"].endswith(f"return {call}([\n{entries}"), node["content"]
    assert compares["chart"]["metadata"]["compareScenarios"]["chart"] == {"preset": "bar", "y": "median flood depth"}
    sources = {e["targetHandle"]: e["source"] for e in spec["edges"] if e["target"] == compares["difference"]["id"]}
    scenario_of = {i: s["id"] for s in spec["scenarios"] for i in s["nodes"]}
    assert {handle: scenario_of[node] for handle, node in sources.items()} == {"in": "no-nbs", "in_1": "nbs"}


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


def _with_values(**values) -> list:
    widgets = [dict(widget) for widget in _template()["widgets"]]
    for widget in widgets:
        if widget["name"] in values:
            widget["value"] = values[widget["name"]]
    return widgets


def _execute(code, input_path, node_type, data_type, workspace, **kwargs):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code

    _worker_init()
    return execute_code(
        textwrap.indent(code, "    "), input_path, node_type, data_type,
        save_dataset=False, media_dir=str(workspace / "media"), **kwargs,
    )


def run_node(workspace, *, fails=False, **values):
    """Run the node's template, its widgets at *values*, in the sandbox, in
    process, with the datasets its code names resolved: ``(artifact id,
    (depth, metrics))``, or with *fails* the node's error text."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    code, problems = resolve_references(_source(), _with_values(**values), "python")
    assert problems == [], problems
    result = _execute(
        code, "", NODE_TYPE, "", workspace,
        dataset_paths={i: str(_data_file(i)) for i in dataset_ids_in_code(code)},
        package_modules={"root": str(SOURCES), "names": [MODULE]},
    )
    if fails:
        assert result["stderr"], f"the node ran: {result['output']}"
        return result["stderr"]
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "outputs", result["output"]
    return result["output"]["path"], load_from_duckdb(result["output"]["path"])


def test_the_node_returns_the_depth_and_the_metrics_scouts_function_gives(workspace, monkeypatch):
    import rasterio

    from utk_curio.sandbox.util.rasters import epsg_name

    _art_id, (depth, metrics) = run_node(workspace, use_NBS_classes=[])
    try:
        assert isinstance(depth, rasterio.io.DatasetReader)
        assert epsg_name(depth.crs) == "EPSG:4326" and depth.dtypes == ("float64",)
        assert (depth.height, depth.width) == PINS["example-2020-none"].shape
        assert hashlib.sha256(depth.read(1).tobytes()).hexdigest() == PINS["example-2020-none"].cells
    finally:
        depth.close()
    assert list(metrics.columns) == ["median flood depth", "mean flood depth"]
    assert float(metrics["median flood depth"][0]) == PINS["example-2020-none"].median
    assert float(metrics["mean flood depth"][0]) == pytest.approx(PINS["example-2020-none"].mean, rel=1e-12)


def test_the_example_picks_each_part_and_the_depth_is_a_raster_autark_loads(workspace):
    """The two nodes after Flood Projection in each scenario of the example take
    its depth raster and its metrics row; the depth is what #718's raster route
    serves the Autark node, inside its caps."""
    import rasterio
    from rasterio.io import MemoryFile

    from utk_curio.sandbox.util.parsers import load_from_duckdb
    from utk_curio.sandbox.util.rasters import serve_raster

    art_id, (depth, metrics) = run_node(workspace)
    depth.close()
    nodes = {n["id"]: n for n in _dataflow()["nodes"]}
    pickers = {nodes[e["target"]]["content"].splitlines()[-1]: nodes[e["target"]]["content"]
               for e in _dataflow()["edges"] if nodes[e["source"]]["type"] == NODE_TYPE}
    # A circle fed by a node that returned a tuple reaches the sandbox as one
    # stored value (backend execution/node_exec.parse_input_ref).
    picked_depth = _execute(pickers["return arg[0]"], art_id, PYTHON_TYPE, "file", workspace)
    picked_metrics = _execute(pickers["return arg[1]"], art_id, PYTHON_TYPE, "file", workspace)
    assert picked_depth["stderr"] == "" and picked_metrics["stderr"] == ""
    assert picked_depth["output"]["dataType"] == "raster", picked_depth["output"]
    assert picked_metrics["output"]["dataType"] == "dataframe", picked_metrics["output"]
    assert load_from_duckdb(picked_metrics["output"]["path"]).equals(metrics)

    payload, meta = serve_raster(
        picked_depth["output"]["path"], max_cells=AUTARK_MAX_CELLS, max_side=AUTARK_MAX_SIDE,
    )
    assert meta["crs"] == "EPSG:4326" and (meta["width"], meta["height"], meta["count"]) == (256, 256, 1)
    a, b, c, d, e, f = meta["transform"]
    assert b == 0 and d == 0 and a > 0 and e < 0
    assert (c, f) == pytest.approx((EXAMPLE[1], EXAMPLE[0]), abs=1e-12)
    with MemoryFile(payload) as memory, memory.open() as served:
        stored = load_from_duckdb(picked_depth["output"]["path"])
        try:
            assert isinstance(stored, rasterio.io.DatasetReader)
            assert served.read(1).tobytes() == stored.read(1).tobytes()
            assert hashlib.sha256(served.read(1).tobytes()).hexdigest() == PINS["example-2020-all"].cells
        finally:
            stored.close()
    # The node's tuple itself, part 0, is what a map wired straight to it reads.
    _payload, straight = serve_raster(art_id, part=0, max_cells=AUTARK_MAX_CELLS, max_side=AUTARK_MAX_SIDE)
    assert straight == meta


def test_each_widget_reaches_the_call(workspace):
    import numpy as np

    def cells(**values):
        _art_id, (depth, metrics) = run_node(workspace, **values)
        try:
            return depth.read(1), float(metrics["median flood depth"][0])
        finally:
            depth.close()

    default, default_median = cells()
    assert default_median == PINS["example-2020-all"].median
    none, none_median = cells(use_NBS_classes=[])
    assert none_median == PINS["example-2020-none"].median
    later, later_median = cells(year="2050 - 2080")
    assert later_median == PINS["example-2050-all"].median
    top, left, bottom, right = CASES["inner-2020-some"][0]
    inner, _ = cells(topleft={"lat": top, "lon": left}, bottomright={"lat": bottom, "lon": right},
                     use_NBS_classes=CASES["inner-2020-some"][2])
    assert inner.shape == PINS["inner-2020-some"].shape
    assert hashlib.sha256(inner.tobytes()).hexdigest() == PINS["inner-2020-some"].cells
    assert not np.array_equal(default, none, equal_nan=True) and not np.array_equal(default, later, equal_nan=True)


@pytest.mark.parametrize(
    "values, sentence",
    [
        ({"topleft": {"lat": 41.5, "lon": -90.4836}}, "reaches past the flood rasters, which cover longitude -90.4869"),
        ({"topleft": {"lat": 41.441, "lon": -90.4577}, "bottomright": {"lat": 41.4669, "lon": -90.4836}},
         "must be north and west of the bottom-right corner"),
        ({"year": "2030"}, "There is no flood projection for '2030'"),
    ],
)
def test_a_setting_the_node_cannot_use_says_why(workspace, values, sentence):
    error = run_node(workspace, fails=True, **values)
    assert sentence in error, error
