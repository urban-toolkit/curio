"""SCOUT's flood example in Curio, made of Curio's own nodes (#662, step 18).

The shipped test dataflow ``FloodScenarios.json`` does what SCOUT's
``simulate_flood_projection`` does with no SCOUT code: three Data Loading nodes
read the region's window of the Data Catalog's crops of SCOUT's rasters
(``curio_load_data(..., bounds=...)``), a Raster Calculator per scenario takes
the depth with nature-based solutions (NbS) where the class is a chosen one and
the depth without elsewhere (``choose``), and a Raster Statistics node gives the
median and the mean.

The proof: SCOUT's own function (``fixtures/scout_flood/``, copied unchanged)
and the dataflow's nodes, run on the crops in the sandbox, give the same cells,
transform, median and mean, for each period and for no, some and all NbS, on
the example region and an inner one. And the crops stand for SCOUT's rasters:
what SCOUT's function computes from the crops is what it computed from SCOUT's
own 2592 by 2064 cell files (``PINS``, printed by
``scripts/build_scout_flood_datasets.py --pins``). Both regions' corners lie on
the edges of SCOUT's cells, where SCOUT's window read takes whole cells.

Sandbox modules are imported inside each test, so a checkout without them
fails each test on its own.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
DATAFLOW = REPO / "docs" / "examples" / "dataflows" / "FloodScenarios.json"
SCOUT_FUNCTION = Path(__file__).resolve().parent / "fixtures" / "scout_flood" / "flood_simulation.py"
NODE_CODE_TS = REPO / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "raster" / "rasterNodeCode.ts"
LOADING = "curio.builtin/data-loading"
CALCULATOR = "curio.builtin/raster-calculator"
STATISTICS = "curio.builtin/raster-statistics"
PARAMETER = "curio.builtin/parameter"
COMPARE = "curio.builtin/compare-scenarios"

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
#: The dataflow's region, (top, left, bottom, right): the edges of SCOUT's
#: columns 2016 to 2271 and rows 1552 to 1807.
EXAMPLE = (41.4669317349186, -90.48363204845099, 41.44098884583301, -90.4576891593654)
#: An inner region: the edges of SCOUT's columns 2061 to 2215 and rows 1599 to 1758.
INNER = (41.46216878262555, -90.4790717749789, 41.44595447694705, -90.46336416635286)
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
    "inner-2020-some": (INNER, "2020 - 2040", ["Retention ponds", "Permeable pavements"]),
}
_EXAMPLE_TRANSFORM = (0.00010133941049058334, 0.0, -90.48363204845099, 0.0, -0.00010133941049058334, 41.4669317349186)
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
    "inner-2020-some": Pin(shape=(160, 155), median=6.025075276692708, mean=6.1729098187306795,
        cells="87577a29b0ac9f642e0d208087094c909a47f69a7433e45f9fcf175001f5cfce",
        transform=(0.00010133941049058334, 0.0, -90.4790717749789, 0.0, -0.00010133941049058334, 41.46216878262555)),
}


def _data_file(dataset_id: str) -> Path:
    root = REPO / "datasets" / f"{dataset_id}@1"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return root / manifest["dataFile"]


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
# The crops stand for SCOUT's files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", sorted(CASES))
def test_scouts_function_on_the_crops_gives_what_it_gave_on_scouts_files(tmp_path, monkeypatch, case):
    """On the crops SCOUT's function writes the cells, transform, median and
    mean it wrote from SCOUT's full files."""
    import numpy as np

    region, period, chosen = CASES[case]
    profile, cells, _tags, metrics = run_scout(tmp_path, monkeypatch, region, period, chosen)
    pin = PINS[case]
    assert cells.shape == pin.shape
    assert hashlib.sha256(cells.tobytes()).hexdigest() == pin.cells
    assert tuple(profile["transform"])[:6] == pytest.approx(pin.transform, abs=1e-12)
    assert (float(np.nanmedian(cells)), float(np.nanmean(cells))) == (pin.median, pin.mean)
    median, mean = _scout_numbers(metrics)
    assert median == pin.median
    assert mean == pytest.approx(pin.mean, rel=1e-12)
    # Not two empty windows agreeing: the region holds depths.
    assert int(np.isfinite(cells).sum()) > 1000


@pytest.mark.parametrize("dataset_id", DATASET_IDS)
def test_each_crop_keeps_scouts_grid(dataset_id):
    """A crop lies on SCOUT's grid, at whole cells, and holds the example's
    region with 32 cells to spare on every side."""
    import rasterio
    from rasterio.windows import from_bounds

    manifest = json.loads((REPO / "datasets" / f"{dataset_id}@1" / "manifest.json").read_text(encoding="utf-8"))
    # SCOUT's data is used with its authors' permission and names no license.
    assert manifest["format"] == "geotiff" and manifest["publisher"] == "SCOUT (urban-toolkit/scout)", manifest
    assert manifest["license"] == "", manifest["license"]
    assert "used with the permission of SCOUT's authors" in manifest["description"]
    assert "the area the FloodScenarios test dataflow reads" in manifest["description"]
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
        for top, left, bottom, right in (EXAMPLE, INNER):
            window = from_bounds(left, bottom, right, top, transform=crop.transform)
            # On cell edges: a window of whole cells.
            for value in (window.col_off, window.row_off, window.width, window.height):
                assert value == pytest.approx(round(value), abs=1e-6)
        window = from_bounds(EXAMPLE[1], EXAMPLE[2], EXAMPLE[3], EXAMPLE[0], transform=crop.transform)
        assert round(window.col_off) == 32 and round(window.row_off) == 32
        assert round(window.width) == round(window.height) == CROP_SIZE - 64


def test_the_class_crop_holds_every_nbs_code():
    """Each of SCOUT's NbS codes, and no other, lies in the example's region."""
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(_data_file(CLASSES)) as crop:
        top, left, bottom, right = EXAMPLE
        cells = crop.read(1, window=from_bounds(left, bottom, right, top, transform=crop.transform))
    present = {int(code) for code in np.unique(cells)}
    assert present == {0, *_scout_classes()}, present


# ---------------------------------------------------------------------------
# The shipped dataflow
# ---------------------------------------------------------------------------

def _dataflow() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]


def _nodes(kind: str) -> list:
    return [n for n in _dataflow()["nodes"] if n["type"] == kind]


def _parameters() -> dict:
    return {n["metadata"]["widgets"][0]["name"]: n["metadata"]["widgets"][0] for n in _nodes(PARAMETER)}


def _starter(name: str) -> str:
    source = NODE_CODE_TS.read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = `([^`]*)`;", source)
    assert match, f"{name} is not in {NODE_CODE_TS}"
    return match.group(1)


def _literal_dict(source: str, name: str) -> dict:
    """The dict literal *source* assigns to *name*, wherever it is."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not assigned in the source")


def _scout_classes() -> dict:
    return _literal_dict(SCOUT_FUNCTION.read_text(encoding="utf-8"), "dict_use_NBS_classes")


def _function_body(code: str) -> str:
    """A node's code as the sandbox runs it, the body of ``userCode``, made a
    module body for ast."""
    return "def userCode(arg):\n" + textwrap.indent(code, "    ")


def test_the_dataflow_is_made_of_curios_own_nodes():
    """No package: three Parameter nodes, three Data Loading nodes, a Raster
    Calculator and a Raster Statistics node per scenario, two Compare
    Scenarios nodes, and the seven crops."""
    spec = _dataflow()
    assert spec["packages"] == []
    assert all(n["type"].startswith("curio.builtin/") for n in spec["nodes"])
    assert [ref["datasetId"] for ref in spec["datasets"]] == DATASET_IDS
    counts = {}
    for n in spec["nodes"]:
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    assert counts == {PARAMETER: 3, LOADING: 3, CALCULATOR: 2, STATISTICS: 2, COMPARE: 2}


def test_the_parameters_hold_the_period_and_the_regions_corners():
    parameters = _parameters()
    assert set(parameters) == {"timeline", "topleft", "bottomright"}
    timeline = parameters["timeline"]
    assert timeline["type"] == "choice" and timeline["options"] == {"choices": list(PERIODS), "display": "radio"}
    assert timeline["default"] == PERIODS[0]
    top, left, bottom, right = EXAMPLE
    assert parameters["topleft"]["type"] == parameters["bottomright"]["type"] == "location"
    assert parameters["topleft"]["default"] == {"lat": top, "lon": left}
    assert parameters["bottomright"]["default"] == {"lat": bottom, "lon": right}


def test_the_loaders_read_the_crops_by_id_with_the_regions_bounds():
    """Each Data Loading node reads its datasets by literal id, the only kind a
    run resolves, with the bounds the corners give."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code

    read = sorted(tuple(dataset_ids_in_code(n["content"])) for n in _nodes(LOADING))
    assert read == sorted([
        (CLASSES,),
        tuple(_depth_id(p, True) for p in PERIODS),
        tuple(_depth_id(p, False) for p in PERIODS),
    ])
    for loader in _nodes(LOADING):
        calls = re.findall(r"curio_load_data\(\"[^\"]+\", bounds=bounds\)", loader["content"])
        assert len(calls) == len(dataset_ids_in_code(loader["content"])), loader["content"]


def test_each_scenario_chooses_by_scouts_classes_and_takes_the_statistics():
    """The two Raster Calculators hold one code, SCOUT's class table, and
    differ in the solutions their widget chooses; the NbS scenario is a copy of
    the other. Each feeds a Raster Statistics node that holds the code it starts
    with."""
    from utk_curio.backend.app.execution.code_references import resolve_references

    spec = _dataflow()
    nodes = {n["id"]: n for n in spec["nodes"]}
    calculators = _nodes(CALCULATOR)
    (code,) = {n["content"] for n in calculators}
    for calculator in calculators:
        # The code reads its widget through a chip, so it parses once resolved,
        # as a run sends it.
        resolved, problems = resolve_references(code, calculator["metadata"]["widgets"], "python")
        assert problems == [], (calculator["id"], problems)
        assert _literal_dict(_function_body(resolved), "NBS_CLASSES") == _scout_classes()
    assert "return curio_raster_calculate(\"choose\", arg, codes=codes)" in code
    assert {n["content"] for n in _nodes(STATISTICS)} == {_starter("RASTER_STATISTICS_CODE")}

    loaders = {}
    for n in _nodes(LOADING):
        if CLASSES in n["content"]:
            loaders["classes"] = n["id"]
        elif "-no-nbs\"" in n["content"]:
            loaders["no-nbs"] = n["id"]
        else:
            loaders["nbs"] = n["id"]
    scenarios = {s["id"]: s for s in spec["scenarios"]}
    assert set(scenarios) == {"no-nbs", "nbs"}
    chosen = {}
    for scenario in scenarios.values():
        members = [nodes[i] for i in scenario["nodes"]]
        assert sorted(n["type"] for n in members) == [CALCULATOR, STATISTICS]
        (calculator,) = [n for n in members if n["type"] == CALCULATOR]
        (statistics,) = [n for n in members if n["type"] == STATISTICS]
        feeds = {e["targetHandle"]: e["source"] for e in spec["edges"] if e["target"] == calculator["id"]}
        assert feeds == {"in": loaders["classes"], "in_1": loaders["nbs"], "in_2": loaders["no-nbs"]}
        assert [e["source"] for e in spec["edges"] if e["target"] == statistics["id"]] == [calculator["id"]]
        (widget,) = calculator["metadata"]["widgets"]
        assert {k: widget[k] for k in ("name", "type", "default", "options")} == {
            "name": "use_NBS_classes", "type": "checkbox-group", "default": ALL_NBS, "options": {"choices": ALL_NBS},
        }
        chosen[scenario["name"]] = widget["value"]
    assert chosen == {"No NbS": [], "NbS": ALL_NBS}
    copies = {nodes[i]["metadata"]["copiedFrom"][-1] for i in scenarios["nbs"]["nodes"]}
    assert copies == set(scenarios["no-nbs"]["nodes"])


def test_every_nodes_code_resolves_with_nothing_left_over():
    from utk_curio.backend.app.execution.code_references import resolve_references

    shared = list(_parameters().values())
    for n in _dataflow()["nodes"]:
        if n["type"] in (LOADING, CALCULATOR, STATISTICS):
            code, problems = resolve_references(n["content"], n["metadata"].get("widgets") or [], "python", shared=shared)
            assert problems == [], (n["id"], problems)
            assert "[!!" not in code
            compile(_function_body(code), n["id"], "exec")


def test_the_shipped_dataflows_compare_nodes_hold_the_code_they_write():
    """Each Compare Scenarios node holds the code it writes for its two inputs,
    No NbS in circle 0 and NbS in circle 1 (``utils/compare/compareCode.ts``):
    one in Difference, NbS minus No NbS, and one charting the median depth."""
    spec = _dataflow()
    entries = '    ("no-nbs", "No NbS", [!! input 0 !!]),\n    ("nbs", "NbS", [!! input 1 !!]),\n])\n'
    compares = {n["metadata"]["compareScenarios"]["mode"]: n for n in _nodes(COMPARE)}
    assert set(compares) == {"difference", "chart"}
    labels = [
        {"scenario": "no-nbs", "name": "No NbS", "color": "#e76f51"},
        {"scenario": "nbs", "name": "NbS", "color": "#2a9d8f"},
    ]
    for mode, call in (("difference", "curio_difference_scenarios"), ("chart", "curio_stack_scenarios")):
        node = compares[mode]
        assert node["metadata"]["compareScenarios"]["inputs"] == labels
        assert node["content"].endswith(f"return {call}([\n{entries}"), node["content"]
    assert compares["chart"]["metadata"]["compareScenarios"]["chart"] == {"preset": "bar", "y": "median"}
    scenario_of = {i: s["id"] for s in spec["scenarios"] for i in s["nodes"]}
    kinds = {n["id"]: n["type"] for n in spec["nodes"]}
    for mode, kind in (("difference", CALCULATOR), ("chart", STATISTICS)):
        sources = {e["targetHandle"]: e["source"] for e in spec["edges"] if e["target"] == compares[mode]["id"]}
        assert {h: (scenario_of[s], kinds[s]) for h, s in sources.items()} == {
            "in": ("no-nbs", kind), "in_1": ("nbs", kind),
        }


# ---------------------------------------------------------------------------
# The proof: the dataflow's nodes, in the sandbox, give what SCOUT's gives
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


def _execute(code, file_path, node_type, data_type, workspace, **kwargs):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code

    _worker_init()
    return execute_code(
        textwrap.indent(code, "    "), file_path, node_type, data_type,
        save_dataset=False, media_dir=str(workspace / "media"), **kwargs,
    )


def run_dataflow(workspace, region=EXAMPLE, period=PERIODS[0], chosen=ALL_NBS, *, fails=False):
    """Run the dataflow's loaders, one Raster Calculator and its Raster
    Statistics node, as Run All runs them in the sandbox, with the Parameter
    nodes at *region* and *period* and the calculator's widget at *chosen*:
    ``(depth artifact id, depth, statistics)``, or with *fails* the first error."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    top, left, bottom, right = region
    values = {"timeline": period, "topleft": {"lat": top, "lon": left}, "bottomright": {"lat": bottom, "lon": right}}
    shared = []
    for name, widget in _parameters().items():
        shared.append({**copy.deepcopy(widget), "value": values[name]})

    def run(node, file_path, data_type, widgets=()):
        code, problems = resolve_references(node["content"], list(widgets), "python", shared=shared)
        assert problems == [], problems
        paths = {i: str(_data_file(i)) for i in dataset_ids_in_code(code)}
        result = _execute(code, file_path, node["type"], data_type, workspace, dataset_paths=paths)
        if result["stderr"]:
            if fails:
                return None, result["stderr"]
            raise AssertionError(result["stderr"])
        return result["output"], None

    loaded = {}
    for loader in _nodes(LOADING):
        output, error = run(loader, "", "")
        if error:
            return error
        assert output["dataType"] == "raster", output
        loaded[loader["id"]] = output["path"]
    spec = _dataflow()
    calculator = _nodes(CALCULATOR)[0]
    feeds = {e["targetHandle"]: e["source"] for e in spec["edges"] if e["target"] == calculator["id"]}
    inputs = repr([loaded[feeds[handle]] for handle in ("in", "in_1", "in_2")])
    widgets = [{**w, "value": list(chosen)} for w in calculator["metadata"]["widgets"]]
    depth, error = run(calculator, inputs, "outputs", widgets)
    if error:
        return error
    assert depth["dataType"] == "raster", depth
    statistics, error = run(_nodes(STATISTICS)[0], depth["path"], "raster")
    if error:
        return error
    assert statistics["dataType"] == "dataframe", statistics
    return depth["path"], load_from_duckdb(depth["path"]), load_from_duckdb(statistics["path"])


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_dataflow_gives_what_scouts_function_gives(workspace, monkeypatch, case):
    """The same cells, transform, median and mean, exactly, as SCOUT's function
    on the same crops, region, period and solutions."""
    import numpy as np

    region, period, chosen = CASES[case]
    profile, cells, _tags, _metrics = run_scout(workspace / "s", monkeypatch, region, period, chosen)
    monkeypatch.chdir(workspace)
    _art, depth, table = run_dataflow(workspace, region, period, chosen)
    try:
        assert depth.dtypes == ("float64",)
        ours = depth.read(1)
        # Every value and every nodata cell. A nodata cell is NaN in both; SCOUT
        # keeps the NaN bits its source file had, Curio writes one NaN.
        assert ours.shape == cells.shape
        assert np.array_equal(ours, cells, equal_nan=True)
        assert np.array_equal(np.isnan(ours), np.isnan(cells))
        assert tuple(depth.transform)[:6] == pytest.approx(tuple(profile["transform"])[:6], abs=1e-12)
        assert depth.crs == profile["crs"]
    finally:
        depth.close()
    assert list(table.columns) == ["mean", "median", "min", "max", "count"]
    row = table.iloc[0]
    assert (float(row["median"]), float(row["mean"])) == (float(np.nanmedian(cells)), float(np.nanmean(cells)))
    assert (float(row["median"]), float(row["mean"])) == (PINS[case].median, PINS[case].mean)
    assert int(row["count"]) == int(np.count_nonzero(~np.isnan(cells)))


def test_the_depth_is_a_raster_autark_loads(workspace, monkeypatch):
    """The calculator's depth is what #718's raster route serves the Autark
    node, inside its caps, on the region's cells: SCOUT's for the NbS scenario."""
    import numpy as np
    from rasterio.io import MemoryFile

    from utk_curio.sandbox.util.rasters import serve_raster

    _profile, cells, _tags, _metrics = run_scout(workspace / "s", monkeypatch, *CASES["example-2020-all"])
    monkeypatch.chdir(workspace)
    art_id, depth, _table = run_dataflow(workspace)
    try:
        stored = depth.read(1)
    finally:
        depth.close()
    payload, meta = serve_raster(art_id, max_cells=AUTARK_MAX_CELLS, max_side=AUTARK_MAX_SIDE)
    assert meta["crs"] == "EPSG:4326" and (meta["width"], meta["height"], meta["count"]) == (256, 256, 1)
    a, b, c, d, e, f = meta["transform"]
    assert b == 0 and d == 0 and a > 0 and e < 0
    assert (c, f) == pytest.approx((EXAMPLE[1], EXAMPLE[0]), abs=1e-12)
    with MemoryFile(payload) as memory, memory.open() as served:
        assert served.read(1).tobytes() == stored.tobytes()
        assert np.array_equal(served.read(1), cells, equal_nan=True)


@pytest.mark.parametrize(
    "settings, sentence",
    [
        ({"region": (41.5, EXAMPLE[1], EXAMPLE[2], EXAMPLE[3])},
         "reach past data.scout.flood-nbs-classes, which covers west -90.48687490958669"),
        ({"region": (EXAMPLE[2], EXAMPLE[3], EXAMPLE[0], EXAMPLE[1])},
         "are not (west, south, east, north) with west less than east and south less than north"),
        ({"period": "2030"}, "There is no flood projection for '2030'. The periods: 2020 - 2040, 2050 - 2080, 2080 - 2100."),
    ],
)
def test_a_setting_the_dataflow_cannot_use_says_why(workspace, settings, sentence):
    error = run_dataflow(workspace, fails=True, **settings)
    assert isinstance(error, str) and sentence in error, error
