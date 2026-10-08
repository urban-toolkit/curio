"""``scout.flood@1``: SCOUT's Quad Cities flood projection in Curio (#662).

The package's ``flood_simulation.py`` is SCOUT's ``simulate_flood_projection``
but for the lines marked ``# Curio:``: the folder it reads SCOUT's rasters from
and the raster's file are arguments, the rasters have the bundle's short names,
and it returns SCOUT's metrics as a table instead of writing a CSV. Its Flood
Projection node hands it the Data Catalog's bundle ``data.scout.quad-cities-flood``
(SCOUT's seven rasters) and the file the raster goes to, and returns
``(depth, metrics)``. The shipped dataflow
``FloodScenarios.json`` runs it twice, with no nature-based solution (NbS) and
with all six, on SCOUT's flood example's corners and period, and compares the
two as SCOUT's example does: a map of each depth, a map of how much it changes,
and a table of the median flood depth.

The proof: SCOUT's own function (``fixtures/scout_flood/``, copied unchanged),
on the bundle, gives what it gave on SCOUT's own files (``PINS``, printed by
``scripts/build_scout_flood_datasets.py --pins``); and the node, in the
sandbox, gives the same cells, transform and metrics as SCOUT's function, and
the dataflow's nodes after it take the depth and SCOUT's own median.

Sandbox modules are imported inside each test, so a checkout without them
fails each test on its own.
"""
from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "scout.flood@1"
SOURCES = PACKAGE / "sources"
MODULE = "scout_flood"
NODE_TYPE = "scout.flood/flood-projection"
DATAFLOW = REPO / "docs" / "examples" / "dataflows" / "FloodScenarios.json"
SCOUT_FUNCTION = Path(__file__).resolve().parent / "fixtures" / "scout_flood" / "flood_simulation.py"
PYTHON = "curio.builtin/computation-analysis"
PARAMETER = "curio.builtin/parameter"
COMPARE = "curio.builtin/compare-scenarios"
MAP = "curio.builtin/autk-grammar"

DATASET_ID = "data.scout.quad-cities-flood"
DATASET = REPO / "datasets" / f"{DATASET_ID}@1"
PARTS = DATASET / "data"
PERIODS = ("2020 - 2040", "2050 - 2080", "2080 - 2100")
ALL_NBS = [
    "Bioswales/Infiltration trenches", "Permeable pavements", "Retention ponds",
    "Infiltration trench", "Bioswales", "Constructed wetlands",
]
#: Each raster's name in the bundle, and SCOUT's name for it.
FILES = {"nbs_classes.tif": "NBS_others_5m_4326_cropped_cleaned_resampled.tif"}
for _period in PERIODS:
    for _kind in ("NbS", "noNbS"):
        _stem = f"{_period.replace(' - ', '_')}_{_kind}"
        FILES[f"{_stem}.tif"] = f"{_stem}_4326_cropped.tif"

#: SCOUT's grid: the transform of every one of its seven rasters, and its size.
SCOUT_GRID = (0.00010133941049058334, 0.0, -90.6879323, 0.0, -0.00010133941049058334, 41.6242105)
SCOUT_SHAPE = (2064, 2592)
#: The transform SCOUT's files hold: the same grid, its top edge as stored.
SCOUT_FILE_GRID = (0.00010133941049058334, 0.0, -90.6879323, 0.0, -0.00010133941049058334, 41.62421049999999)
#: SCOUT's flood example's corners, (top, left, bottom, right): the whole grid.
SCOUT_REGION = (41.6242105, -90.6879323, 41.4150156, -90.4252158)
#: The edges of SCOUT's columns 2061 to 2215 and rows 1599 to 1758.
INNER = (41.46216878262555, -90.4790717749789, 41.44595447694705, -90.46336416635286)
#: What an Autark map loads at its own size (utils/raster/rasterLoad.ts).
AUTARK_MAX_CELLS = 4096 * 4096
AUTARK_MAX_SIDE = 8192


@dataclass(frozen=True)
class Pin:
    """What SCOUT's function computed from SCOUT's own files: the shape, the
    sha256 of the cells and the transform of the raster it wrote, and the median
    and mean of those cells, its metrics."""

    shape: tuple
    median: float
    mean: float
    cells: str
    transform: tuple


#: Region, period and chosen NbS, as ``PROOF_CASES`` in
#: ``scripts/build_scout_flood_datasets.py``.
CASES = {
    "scout-2020-none": (SCOUT_REGION, "2020 - 2040", []),
    "scout-2020-all": (SCOUT_REGION, "2020 - 2040", ALL_NBS),
    "scout-2050-none": (SCOUT_REGION, "2050 - 2080", []),
    "scout-2050-all": (SCOUT_REGION, "2050 - 2080", ALL_NBS),
    "scout-2080-none": (SCOUT_REGION, "2080 - 2100", []),
    "scout-2080-all": (SCOUT_REGION, "2080 - 2100", ALL_NBS),
    "inner-2080-some": (INNER, "2080 - 2100", ["Bioswales", "Constructed wetlands"]),
}
PINS = {
    "scout-2020-none": Pin(shape=SCOUT_SHAPE, median=7.163970947265625, mean=6.346452299531106,
        cells="1501511ebdf08d2fcd0d33a055e14c41f880d140a11fa51ddd977ae9b1458354", transform=SCOUT_GRID),
    "scout-2020-all": Pin(shape=SCOUT_SHAPE, median=4.900075276692708, mean=5.312285760833436,
        cells="d42a7b1ab4be06e297aad402aafc5df60317b1ad71749b8ef92d726995a4c128", transform=SCOUT_GRID),
    "scout-2050-none": Pin(shape=SCOUT_SHAPE, median=7.083333333333334, mean=4.972232118870031,
        cells="af290b28fcde4cd128979652045922f3ef188b0d954f1a1f85877c64beffb3d6", transform=SCOUT_GRID),
    "scout-2050-all": Pin(shape=SCOUT_SHAPE, median=5.666666666666667, mean=4.703412297068202,
        cells="6eb732fe69d2eaf966846f984306b4531619dcaaa2c1684fdf53bb1f0df2d77a", transform=SCOUT_GRID),
    "scout-2080-none": Pin(shape=SCOUT_SHAPE, median=6.723846435546875, mean=5.678816496936588,
        cells="be1f7ca75e57268046af6337867bec98ac2cc3e424c281f14c10973df0e9feee", transform=SCOUT_GRID),
    "scout-2080-all": Pin(shape=SCOUT_SHAPE, median=6.10040283203125, mean=5.290108160655499,
        cells="fdedc685824ae64c36a135c9a6839bc9c2fbfa5f03bd2aecb4d7a79238dd546c", transform=SCOUT_GRID),
    "inner-2080-some": Pin(shape=(160, 155), median=6.119740804036458, mean=5.74535352265079,
        cells="ab2f5158be4f2467324464ec98aa318d0859c6e1a2c382333e7a0e6400f02abf",
        transform=(0.00010133941049058334, 0.0, -90.4790717749789, 0.0, -0.00010133941049058334, 41.46216878262555)),
}


def _manifest() -> dict:
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def _template() -> dict:
    (template,) = _manifest()["templates"]
    return template


def _source() -> str:
    return (PACKAGE / _template()["source"]).read_text(encoding="utf-8")


def _scout_function():
    import importlib.util

    spec = importlib.util.spec_from_file_location("scout_original_flood_simulation", SCOUT_FUNCTION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.simulate_flood_projection


def _corners(region) -> tuple[str, str]:
    """SCOUT's ``"lon, lat"`` text of *region*'s corners."""
    top, left, bottom, right = region
    return f"{left!r}, {top!r}", f"{right!r}, {bottom!r}"


def run_scout(tmp_path, monkeypatch, region, period, chosen):
    """SCOUT's function as SCOUT's flood example calls it, in a folder laid out
    as it reads one, on the bundle's parts: ``(profile, cells, metrics)`` of
    the raster and the metrics file it writes."""
    import rasterio

    folder = tmp_path / "scout"
    rasters = folder / "models" / "flooding" / "data_substitutes"
    rasters.mkdir(parents=True)
    for name, scouts in FILES.items():
        (rasters / scouts).symlink_to(PARTS / name)
    monkeypatch.chdir(folder)
    _scout_function()(*_corners(region), "A", year=period, use_NBS_classes=list(chosen))
    with rasterio.open(folder / "data" / "served" / "raster" / "A.tif") as raster:
        written = (dict(raster.profile), raster.read(1))
    metrics = (folder / "data" / "served" / "metric" / "A.csv").read_text(encoding="utf-8")
    return (*written, metrics)


def _scout_numbers(metrics: str) -> tuple[float, float]:
    """The median and the mean SCOUT's metrics file holds."""
    header, row = metrics.splitlines()[:2]
    assert header == "median flood depth,mean flood depth", header
    median, mean = (float(value) for value in row.split(","))
    return median, mean


# ---------------------------------------------------------------------------
# SCOUT's file and SCOUT's rasters
# ---------------------------------------------------------------------------

def test_scouts_file_changes_only_the_marked_lines():
    """The package's ``flood_simulation.py`` is SCOUT's but for the lines it
    marks: the rasters' folder and the raster's file are arguments, the rasters
    have the bundle's shorter names, and the metrics are returned, not written
    to a CSV. The lines it leaves out are SCOUT's CSV's."""
    import difflib

    ours = (SOURCES / MODULE / "flood_simulation.py").read_text(encoding="utf-8").splitlines()
    scouts = SCOUT_FUNCTION.read_text(encoding="utf-8").splitlines()
    marked = [line.split("# Curio:")[0].strip() for line in ours if "# Curio:" in line]
    assert marked == [
        'data_dir="./models/flooding/data_substitutes",',
        "output_path=None,",
        'mask_path = f"{data_dir}/nbs_classes.tif"',
        'nbs_flood_path = f"{data_dir}/{year}_NbS.tif"',
        'nonbs_flood_path = f"{data_dir}/{year}_noNbS.tif"',
        'output_path = output_path or f"./data/served/raster/{output}.tif"',
        "return df",
    ]
    unmarked = [line for line in ours if "# Curio:" not in line]
    changes = [line for line in difflib.ndiff(scouts, unmarked) if line[:2] in ("- ", "+ ")]
    assert changes == [
        '-     mask_path = "./models/flooding/data_substitutes/NBS_others_5m_4326_cropped_cleaned_resampled.tif"',
        '-     nbs_flood_path = f"./models/flooding/data_substitutes/{year}_NbS_4326_cropped.tif"',
        '-     nonbs_flood_path = f"./models/flooding/data_substitutes/{year}_noNbS_4326_cropped.tif"',
        '-     output_path = f"./data/served/raster/{output}.tif"',
        '-         metric_path = f"./data/served/metric/{output}.csv"',
        "- ",
        "-         os.makedirs(os.path.dirname(metric_path), exist_ok=True)",
        "-         df.to_csv(metric_path, index=False)",
        "- ",
    ]


def test_the_bundle_holds_scouts_seven_rasters_on_scouts_grid():
    import rasterio

    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["id"], manifest["format"], manifest["dataFile"]) == (DATASET_ID, "bundle", "data/bundle.json")
    assert manifest["publisher"] == "SCOUT (urban-toolkit/scout)"
    assert manifest["license"] == "to be confirmed"
    assert "used with the permission of SCOUT's authors" in manifest["description"]
    bundle = json.loads((DATASET / "data" / "bundle.json").read_text(encoding="utf-8"))
    assert [part["file"] for part in bundle["parts"]] == [f"data/{name}" for name in FILES]
    assert {(part["kind"], part["format"]) for part in bundle["parts"]} == {("raster", "geotiff")}
    for name in FILES:
        with rasterio.open(PARTS / name) as part:
            assert part.crs.to_epsg() == 4326 and part.count == 1
            assert (part.height, part.width) == SCOUT_SHAPE
            assert tuple(part.transform)[:6] == SCOUT_FILE_GRID
            if name == "nbs_classes.tif":
                assert part.dtypes == ("uint8",) and part.nodata == 0
            else:
                assert part.dtypes == ("float64",) and part.nodata == -1.7976931348623157e308


@pytest.mark.parametrize("case", sorted(CASES))
def test_scouts_function_on_the_bundle_gives_what_it_gave_on_scouts_files(tmp_path, monkeypatch, case):
    import numpy as np

    region, period, chosen = CASES[case]
    profile, cells, metrics = run_scout(tmp_path, monkeypatch, region, period, chosen)
    pin = PINS[case]
    assert cells.shape == pin.shape
    assert hashlib.sha256(cells.tobytes()).hexdigest() == pin.cells
    assert tuple(profile["transform"])[:6] == pytest.approx(pin.transform, abs=1e-12)
    assert (float(np.nanmedian(cells)), float(np.nanmean(cells))) == (pin.median, pin.mean)
    median, mean = _scout_numbers(metrics)
    assert median == pin.median
    assert mean == pytest.approx(pin.mean, rel=1e-12)
    assert int(np.isfinite(cells).sum()) > 1000


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
    """The manifest's widgets, with *values* set as a user sets them."""
    widgets = [dict(widget) for widget in _template()["widgets"]]
    for widget in widgets:
        if widget["name"] in values:
            widget["value"] = values[widget["name"]]
    return widgets


def _execute(code, file_path, node_type, data_type, workspace, **extra):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code

    _worker_init()
    return execute_code(
        textwrap.indent(code, "    "), file_path, node_type, data_type,
        save_dataset=False, media_dir=str(workspace / "media"), **extra,
    )


def run_node(workspace, region=SCOUT_REGION, period=PERIODS[0], chosen=ALL_NBS, *, fails=False):
    """Run the node's template with its widgets at *region*, *period* and
    *chosen*, the dataset resolved as the backend resolves it, in process:
    ``(the sandbox's result, the depth raster, the metrics table)``, or with
    *fails* the error."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    top, left, bottom, right = region
    widgets = _with_values(
        topleft={"lat": top, "lon": left}, bottomright={"lat": bottom, "lon": right},
        timeline=period, use_NBS_classes=list(chosen),
    )
    code, problems = resolve_references(_source(), widgets, "python")
    assert problems == [], problems
    assert dataset_ids_in_code(code) == [DATASET_ID]
    result = _execute(
        code, "", NODE_TYPE, "", workspace,
        package_modules={"root": str(SOURCES), "names": [MODULE]},
        dataset_paths={DATASET_ID: str(DATASET / "data" / "bundle.json")},
    )
    if fails:
        return result["stderr"]
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "outputs", result["output"]
    depth, metrics = load_from_duckdb(result["output"]["path"])
    return result, depth, metrics


def _dataflow() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]


def _nodes(kind: str) -> list:
    return [n for n in _dataflow()["nodes"] if n["type"] == kind]


def _picker_code(part: str) -> str:
    """The code of the dataflow's nodes that take *part* of Flood Projection's
    ``(depth, metrics)``: ``input_0[0]`` or ``input_0[1]``, one code for both
    scenarios."""
    codes = {n["content"] for n in _nodes(PYTHON) if n["content"].rstrip().endswith(f"return {part}")}
    assert len(codes) == 1, codes
    return codes.pop()


def run_picker(workspace, artifact, part):
    """The dataflow's node that takes *part*, its code as written, on the
    Flood Projection artifact *artifact*: the sandbox's result."""
    result = _execute(_picker_code(part), artifact, PYTHON, "file", workspace)
    assert result["stderr"] == "", result["stderr"]
    return result


@pytest.mark.parametrize("case", ["scout-2020-none", "scout-2020-all", "scout-2080-all", "inner-2080-some"])
def test_the_node_gives_what_scouts_function_gives(workspace, monkeypatch, case):
    """The same cells, transform and metrics, exactly, as SCOUT's function,
    and no file saved besides the raster; the dataflow's node after it takes
    SCOUT's median, under SCOUT's name."""
    import numpy as np

    region, period, chosen = CASES[case]
    profile, cells, metrics = run_scout(workspace / "s", monkeypatch, region, period, chosen)
    monkeypatch.chdir(workspace)
    result, depth, table = run_node(workspace, region, period, chosen)
    try:
        ours = depth.read(1)
        assert depth.dtypes == ("float64",)
        assert ours.shape == cells.shape
        assert np.array_equal(ours, cells, equal_nan=True)
        assert tuple(depth.transform)[:6] == pytest.approx(tuple(profile["transform"])[:6], abs=1e-12)
        assert depth.crs == profile["crs"]
    finally:
        depth.close()
    assert "savedFiles" not in result["output"]
    assert list(table.columns) == ["median flood depth", "mean flood depth"]
    assert (float(table["median flood depth"].iloc[0]), float(table["mean flood depth"].iloc[0])) == (
        _scout_numbers(metrics))
    assert float(table["median flood depth"].iloc[0]) == PINS[case].median
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    picked = run_picker(workspace, result["output"]["path"], "input_0[1]")
    assert picked["output"]["dataType"] == "dataframe", picked["output"]
    assert load_from_duckdb(picked["output"]["path"]).equals(table)


def test_the_depth_is_a_raster_autark_loads_whole(workspace):
    """SCOUT's whole grid fits an Autark map at its own size, as the raster
    route serves it."""
    from utk_curio.sandbox.util.rasters import serve_raster

    result, depth, _metrics = run_node(workspace)
    depth.close()
    # The dataflow's node that takes the depth hands the map a raster.
    picked = run_picker(workspace, result["output"]["path"], "input_0[0]")
    assert picked["output"]["dataType"] == "raster", picked["output"]
    _payload, meta = serve_raster(picked["output"]["path"], max_cells=AUTARK_MAX_CELLS, max_side=AUTARK_MAX_SIDE)
    assert meta["crs"] == "EPSG:4326"
    assert (meta["height"], meta["width"], meta["count"]) == (*SCOUT_SHAPE, 1)


def test_two_scenarios_write_files_of_their_own(workspace):
    """Two runs with different solutions never share a raster file."""
    _first, a, _ma = run_node(workspace, chosen=[])
    _second, b, _mb = run_node(workspace, chosen=ALL_NBS)
    try:
        assert a.name != b.name
        assert (a.read(1) != b.read(1)).any()
    finally:
        a.close()
        b.close()


def test_a_period_scout_has_no_projection_for_fails(workspace):
    error = run_node(workspace, period="2030", fails=True)
    assert "None_NbS.tif" in error, error


# ---------------------------------------------------------------------------
# The shipped dataflow
# ---------------------------------------------------------------------------

def test_the_shipped_dataflow_is_scouts_flood_example():
    """Three Parameter nodes both scenarios share (the period and SCOUT's
    corners); per scenario a Flood Projection node, a node taking its depth
    for its map, and one taking SCOUT's metrics, named after the scenario; an
    absolute difference of the two depths and a table of the two medians. No NbS has no solution chosen,
    All NbS all six, a copy of it."""
    from utk_curio.backend.app.execution.code_references import resolve_references

    spec = _dataflow()
    assert spec["packages"] == ["scout.flood@1"]
    assert [ref["datasetId"] for ref in spec["datasets"]] == [DATASET_ID]
    counts = {}
    for n in spec["nodes"]:
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    assert counts == {PARAMETER: 3, NODE_TYPE: 2, PYTHON: 4, MAP: 2, COMPARE: 2}

    parameters = {n["metadata"]["widgets"][0]["name"]: n["metadata"]["widgets"][0] for n in _nodes(PARAMETER)}
    template = {w["name"]: w for w in _template()["widgets"]}
    for name in ("timeline", "topleft", "bottomright"):
        assert parameters[name] == template[name]

    nodes = {n["id"]: n for n in spec["nodes"]}
    into = {(e["target"], e["targetHandle"]): e["source"] for e in spec["edges"]}
    scenarios = {s["id"]: s for s in spec["scenarios"]}
    assert [(s["id"], s["name"]) for s in spec["scenarios"]] == [("no-nbs", "No NbS"), ("all-nbs", "All NbS")]
    chosen = {}
    for scenario in spec["scenarios"]:
        parts = [nodes[i] for i in scenario["nodes"]]
        assert sorted(n["type"] for n in parts) == sorted([NODE_TYPE, PYTHON, PYTHON, MAP])
        assert {n["title"] for n in parts} == {
            f"Flood Projection - {scenario['name']}", f"Depth - {scenario['name']}",
            f"Metrics - {scenario['name']}", f"Flood depth map - {scenario['name']}",
        }
        members = {n["title"].split(" - ")[0]: n for n in parts}
        projection = members["Flood Projection"]
        # The template's code below its docstring, reading the region and the
        # period from the Parameter nodes.
        shared_code = _source().split('"""', 2)[2]
        for name in ("topleft", "bottomright", "timeline"):
            shared_code = shared_code.replace(f"[!! {name} !!]", f"[!! @{name} !!]")
        assert projection["content"].split('"""', 2)[2] == shared_code
        code, problems = resolve_references(projection["content"], projection["metadata"]["widgets"], "python",
                                            shared=list(parameters.values()))
        assert problems == [] and "[!!" not in code, problems
        assert members["Depth"]["content"] == _picker_code("input_0[0]")
        assert members["Metrics"]["content"] == _picker_code("input_0[1]")
        assert into[(members["Depth"]["id"], "in")] == projection["id"]
        assert into[(members["Metrics"]["id"], "in")] == projection["id"]
        assert into[(members["Flood depth map"]["id"], "in")] == members["Depth"]["id"]
        widgets = {w["name"]: w for w in projection["metadata"]["widgets"]}
        assert set(widgets) == {"use_NBS_classes"}
        chosen[scenario["id"]] = widgets["use_NBS_classes"]["value"]
    assert chosen == {"no-nbs": [], "all-nbs": ALL_NBS}
    copies = {nodes[i]["metadata"]["copiedFrom"][-1] for i in scenarios["all-nbs"]["nodes"]}
    assert copies == set(scenarios["no-nbs"]["nodes"])

    compares = {n["metadata"]["compareScenarios"]["mode"]: n for n in _nodes(COMPARE)}
    difference, table = compares["difference"], compares["chart"]
    assert difference["metadata"]["compareScenarios"]["difference"] == {"colors": "interpolateBlues", "absolute": True}
    assert difference["content"].endswith("], absolute=True)")
    assert table["metadata"]["compareScenarios"]["chart"] == {"preset": "pie", "y": "median flood depth", "aggregate": "none"}
    scenario_of = {i: s["id"] for s in spec["scenarios"] for i in s["nodes"]}
    for node, part in ((difference, "Depth"), (table, "Metrics")):
        sources = {h: into[(node["id"], h)] for h in ("in", "in_1")}
        assert {h: (scenario_of[s], nodes[s]["title"]) for h, s in sources.items()} == {
            "in": ("no-nbs", f"{part} - No NbS"), "in_1": ("all-nbs", f"{part} - All NbS"),
        }
