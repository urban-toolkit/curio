"""SCOUT's flood example in Curio, made of Curio's own nodes, on SCOUT's whole grid (#662, step 18; #819).

The shipped test dataflow ``quad-cities-flood-vulnerability.json`` does what SCOUT's
``simulate_flood_projection`` does with no SCOUT code: three Data Loading nodes
read the region's window of SCOUT's rasters, which the Data Catalog holds whole
(``curio_load_data(..., bounds=...)``), a Raster Calculator per scenario takes
the depth with nature-based solutions (NbS) where the class is a chosen one and
the depth without elsewhere (``choose``), a second takes the depth's
statistics, the median and the mean among them, and an Autark map draws the
depth. Its Parameter nodes
hold SCOUT's flood example's corners, which take every cell of SCOUT's 2592 by
2064 cell grid, and its period, 2020 - 2040.

The proof: the catalog's rasters are SCOUT's files, since what SCOUT's own
function (``fixtures/scout_flood/``, copied unchanged) computes from them is
what it computed from SCOUT's own files (``PINS``, printed by
``scripts/build_scout_flood_datasets.py --pins``); and the dataflow's nodes,
run in the sandbox, give the same cells, transform, median and mean as SCOUT's
function, for each period and for no, some and all NbS, on SCOUT's corners and
on two regions inside them. At the dataflow's own settings that is a median
flood depth of 7.164 m without NbS and 4.900 m with every NbS in 2020 - 2040.

The dataflow also weighs the flood against CDC/ATSDR's Social Vulnerability
Index (SVI), as komar41's FloodRisk example in #914 does: two more Data
Loading nodes read CDC's census tracts and USGS's waterways, a Data
Transformation keeps the 28 tracts that NHD's stream and river areas touch, an
Autark map draws their SVI percentile, and in each scenario one Data
Transformation averages the depth over each tract's land and another over the
riverside land in each of SCOUT's three periods, the water left out and dry
land counted as 0 m. Compare Scenarios takes the size of the change in each
tract's mean depth, which an Autark map draws, and charts vulnerability
against depth and the mean depth by period. The nodes, run in the sandbox,
give what this file computes from the datasets on its own.

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
DATAFLOW = REPO / "docs" / "examples" / "dataflows" / "quad-cities-flood-vulnerability.json"
SCOUT_FUNCTION = Path(__file__).resolve().parent / "fixtures" / "scout_flood" / "flood_simulation.py"
NODE_CODE_TS = REPO / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "raster" / "rasterNodeCode.ts"
COMPARE_CODE_TS = REPO / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "compare" / "compareCode.ts"
LOADING = "curio.builtin/data-loading"
CALCULATOR = "curio.builtin/raster-calculator"
#: What a Raster Calculator's code returns: an operation cell by cell, which
#: gives a raster, or statistics, which give a table of one row.
CALCULATE = "curio_raster_calculate"
STATISTICS = "curio_raster_statistics"
PARAMETER = "curio.builtin/parameter"
COMPARE = "curio.builtin/compare-scenarios"
MAP = "curio.builtin/autk-grammar"
TRANSFORMATION = "curio.builtin/data-transformation"

CLASSES = "data.scout.flood-nbs-classes"
#: CDC/ATSDR's SVI census tracts and USGS's NHD waterways on SCOUT's grid.
TRACTS = "data.cdc.quad-cities-svi-tracts"
WATERWAYS = "data.usgs.quad-cities-waterways"
PERIODS = ("2020 - 2040", "2050 - 2080", "2080 - 2100")
ALL_NBS = [
    "Bioswales/Infiltration trenches", "Permeable pavements", "Retention ponds",
    "Infiltration trench", "Bioswales", "Constructed wetlands",
]


def _depth_id(period: str, nbs: bool) -> str:
    start, end = period.split(" - ")
    return f"data.scout.flood-depth-{start}-{end}-{'nbs' if nbs else 'no-nbs'}"


#: SCOUT's seven rasters, and every dataset the dataflow reads.
RASTER_IDS = [CLASSES] + [_depth_id(p, nbs) for p in PERIODS for nbs in (True, False)]
DATASET_IDS = RASTER_IDS + [TRACTS, WATERWAYS]

#: The name SCOUT's function reads each dataset's file under.
SCOUT_NAMES = {CLASSES: "NBS_others_5m_4326_cropped_cleaned_resampled.tif"}
for _period in PERIODS:
    _stem = _period.replace(" - ", "_")
    SCOUT_NAMES[_depth_id(_period, True)] = f"{_stem}_NbS_4326_cropped.tif"
    SCOUT_NAMES[_depth_id(_period, False)] = f"{_stem}_noNbS_4326_cropped.tif"

#: SCOUT's grid: the transform every one of its seven rasters holds, and its
#: size in rows and columns.
SCOUT_GRID = (0.00010133941049058334, 0.0, -90.6879323, 0.0, -0.00010133941049058334, 41.62421049999999)
SCOUT_SHAPE = (2064, 2592)
#: SCOUT's flood example's corners, (top, left, bottom, right): the dataflow's
#: defaults. Every cell of SCOUT's grid has its centre inside them.
SCOUT_REGION = (41.6242105, -90.6879323, 41.4150156, -90.4252158)
#: A region on the edges of SCOUT's columns 2016 to 2271 and rows 1552 to
#: 1807, 256 by 256 cells that hold every NbS class code.
EXAMPLE = (41.4669317349186, -90.48363204845099, 41.44098884583301, -90.4576891593654)
#: An inner region: the edges of SCOUT's columns 2061 to 2215 and rows 1599 to 1758.
INNER = (41.46216878262555, -90.4790717749789, 41.44595447694705, -90.46336416635286)
#: What the Autark node's raster path loads at its own size (utils/raster/rasterLoad.ts).
AUTARK_MAX_CELLS = 4096 * 4096
AUTARK_MAX_SIDE = 8192

#: The color range both scenarios' depth maps share, in metres: from 0 to the
#: deepest flood of any period, with or without NbS, 10.67 m, rounded up to a
#: whole metre.
DEPTH_RANGE = [0, 11]

#: Each scenario's Autark map of its depth, over the range both maps share.
MAP_DOCUMENT = {"map": {"layerRefs": [{
    "dataRef": "[!! input_0 !!]",
    "getFnv": "band_1",
    "colorMapInterpolator": "interpolateBlues",
    "colorMapRange": DEPTH_RANGE,
    "title": "Flood depth (m)",
}]}}

#: The Autark map after the Compare Scenarios node in Difference: the size of
#: the change in depth, a difference with no sign, on a sequential scale.
DIFFERENCE_MAP_DOCUMENT = {"map": {"layerRefs": [{
    "dataRef": "[!! input_0 !!]",
    "getFnv": "band_1",
    "colorMapInterpolator": "interpolateOranges",
    "title": "Absolute flood depth change (m)",
}]}}

#: The Autark map of the riverside tracts' SVI percentile, over the whole
#: range a percentile takes, so a color is one ranking among every US tract.
VULNERABILITY_MAP_DOCUMENT = {"map": {"layerRefs": [{
    "dataRef": "[!! input_0 !!]",
    "getFnv": "RPL_THEMES",
    "getFnvType": "quantitative",
    "colorMapInterpolator": "interpolateReds",
    "colorMapRange": [0, 1],
    "title": "Social vulnerability (SVI percentile)",
}]}}

#: The Autark map after the Compare Scenarios node that subtracts the tracts'
#: mean depths: the size of each tract's change, on the depth change's scale.
TRACT_CHANGE_MAP_DOCUMENT = {"map": {"layerRefs": [{
    "dataRef": "[!! input_0 !!]",
    "getFnv": "mean_depth_m",
    "getFnvType": "quantitative",
    "colorMapInterpolator": "interpolateOranges",
    "title": "Absolute change in mean flood depth (m)",
}]}}

#: CDC's columns, which the riverside tracts keep.
TRACT_COLUMNS = ["FIPS", "LOCATION", "E_TOTPOP", "RPL_THEMES"]
#: NHD's stream and river areas, whose tracts are the riverside ones.
RIVER = 460
#: The riverside tracts at the dataflow's corners: how many, and their people.
RIVERSIDE_TRACTS = 28
RIVERSIDE_PEOPLE = 81021
#: Their land on SCOUT's grid, in km2: their cells, less NHD's water.
RIVERSIDE_LAND_KM2 = 202.568
#: The mean flood depth over the riverside tracts' land in each period, in
#: metres, without NbS and with every NbS: dry land counts as 0 m.
PERIOD_DEPTHS = {
    "No NbS": {"2020 - 2040": 1.988, "2050 - 2080": 1.923, "2080 - 2100": 2.237},
    "NbS": {"2020 - 2040": 1.337, "2050 - 2080": 1.691, "2080 - 2100": 1.872},
}
#: The mean Earth's radius, in km: a cell's area on SCOUT's grid in degrees.
EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Pin:
    """What SCOUT's function computed from SCOUT's own files: the shape, the
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
    "scout-2020-none": (SCOUT_REGION, "2020 - 2040", []),
    "scout-2020-all": (SCOUT_REGION, "2020 - 2040", ALL_NBS),
    "scout-2050-none": (SCOUT_REGION, "2050 - 2080", []),
    "scout-2050-all": (SCOUT_REGION, "2050 - 2080", ALL_NBS),
    "scout-2080-none": (SCOUT_REGION, "2080 - 2100", []),
    "scout-2080-all": (SCOUT_REGION, "2080 - 2100", ALL_NBS),
    "example-2020-all": (EXAMPLE, "2020 - 2040", ALL_NBS),
    "example-2020-none": (EXAMPLE, "2020 - 2040", []),
    "example-2050-none": (EXAMPLE, "2050 - 2080", []),
    "example-2050-all": (EXAMPLE, "2050 - 2080", ALL_NBS),
    "example-2080-some": (EXAMPLE, "2080 - 2100", ["Bioswales", "Constructed wetlands"]),
    "inner-2020-some": (INNER, "2020 - 2040", ["Retention ponds", "Permeable pavements"]),
}
#: The transform SCOUT's function writes for SCOUT's corners: SCOUT's grid,
#: its top edge at the corner it was given.
_SCOUT_TRANSFORM = (0.00010133941049058334, 0.0, -90.6879323, 0.0, -0.00010133941049058334, 41.6242105)
_EXAMPLE_TRANSFORM = (0.00010133941049058334, 0.0, -90.48363204845099, 0.0, -0.00010133941049058334, 41.4669317349186)
PINS = {
    "scout-2020-none": Pin(shape=SCOUT_SHAPE, median=7.163970947265625, mean=6.346452299531106,
        cells="1501511ebdf08d2fcd0d33a055e14c41f880d140a11fa51ddd977ae9b1458354",
        transform=_SCOUT_TRANSFORM),
    "scout-2020-all": Pin(shape=SCOUT_SHAPE, median=4.900075276692708, mean=5.312285760833436,
        cells="d42a7b1ab4be06e297aad402aafc5df60317b1ad71749b8ef92d726995a4c128",
        transform=_SCOUT_TRANSFORM),
    "scout-2050-none": Pin(shape=SCOUT_SHAPE, median=7.083333333333334, mean=4.972232118870031,
        cells="af290b28fcde4cd128979652045922f3ef188b0d954f1a1f85877c64beffb3d6",
        transform=_SCOUT_TRANSFORM),
    "scout-2050-all": Pin(shape=SCOUT_SHAPE, median=5.666666666666667, mean=4.703412297068202,
        cells="6eb732fe69d2eaf966846f984306b4531619dcaaa2c1684fdf53bb1f0df2d77a",
        transform=_SCOUT_TRANSFORM),
    "scout-2080-none": Pin(shape=SCOUT_SHAPE, median=6.723846435546875, mean=5.678816496936588,
        cells="be1f7ca75e57268046af6337867bec98ac2cc3e424c281f14c10973df0e9feee",
        transform=_SCOUT_TRANSFORM),
    "scout-2080-all": Pin(shape=SCOUT_SHAPE, median=6.10040283203125, mean=5.290108160655499,
        cells="fdedc685824ae64c36a135c9a6839bc9c2fbfa5f03bd2aecb4d7a79238dd546c",
        transform=_SCOUT_TRANSFORM),
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
    as it reads one, on the catalog's rasters: ``(profile, cells, tags, metrics)``
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
# The catalog's rasters are SCOUT's files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", sorted(CASES))
def test_scouts_function_on_the_catalogs_rasters_gives_what_it_gave_on_scouts_files(tmp_path, monkeypatch, case):
    """On the catalog's rasters SCOUT's function writes the cells, transform,
    median and mean it wrote from SCOUT's own files."""
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


@pytest.mark.parametrize("dataset_id", RASTER_IDS)
def test_each_raster_is_scouts_whole_file(dataset_id):
    """Each dataset holds SCOUT's raster whole: its grid, every cell of it,
    compressed losslessly, and the two inner regions lie on its cell edges."""
    import rasterio
    from rasterio.windows import from_bounds

    manifest = json.loads((REPO / "datasets" / f"{dataset_id}@1" / "manifest.json").read_text(encoding="utf-8"))
    # SCOUT's data is used with its authors' permission and names no license.
    assert manifest["format"] == "geotiff" and manifest["publisher"] == "SCOUT (urban-toolkit/scout)", manifest
    assert manifest["license"] == "", manifest["license"]
    assert "used with the permission of SCOUT's authors" in manifest["description"]
    assert f"SCOUT's {SCOUT_NAMES[dataset_id]} whole: 2592 by 2064 cells" in manifest["description"]
    assert "The quad-cities-flood-vulnerability test dataflow reads it." in manifest["description"]
    with rasterio.open(_data_file(dataset_id)) as raster:
        assert raster.crs.to_epsg() == 4326 and raster.count == 1
        assert (raster.height, raster.width) == SCOUT_SHAPE
        assert tuple(raster.transform)[:6] == SCOUT_GRID
        assert raster.profile["compress"] == "deflate"
        if dataset_id == CLASSES:
            assert raster.dtypes == ("uint8",) and raster.nodata == 0
        else:
            assert raster.dtypes == ("float64",) and raster.nodata == -1.7976931348623157e308
        for (top, left, bottom, right), corner, size in (
            (EXAMPLE, (2016, 1552), (256, 256)), (INNER, (2061, 1599), (155, 160)),
        ):
            window = from_bounds(left, bottom, right, top, transform=raster.transform)
            # On cell edges: a window of whole cells.
            for value in (window.col_off, window.row_off, window.width, window.height):
                assert value == pytest.approx(round(value), abs=1e-6)
            assert (round(window.col_off), round(window.row_off)) == corner
            assert (round(window.width), round(window.height)) == size


def test_scouts_corners_take_every_cell_of_scouts_grid():
    """The window the dataflow's loaders read for SCOUT's corners: the cells
    whose centres lie inside them, every cell of SCOUT's grid."""
    import rasterio

    from utk_curio.sandbox.util.rasters import window_of

    top, left, bottom, right = SCOUT_REGION
    with rasterio.open(_data_file(CLASSES)) as raster:
        window = window_of(raster, (left, bottom, right, top), CLASSES)
    assert (window.col_off, window.row_off, window.width, window.height) == (0, 0, 2592, 2064)


def test_the_class_raster_holds_every_nbs_code():
    """Each of SCOUT's NbS codes, and no other, lies in SCOUT's grid and in
    the example region inside it."""
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(_data_file(CLASSES)) as raster:
        whole = raster.read(1)
        top, left, bottom, right = EXAMPLE
        region = raster.read(1, window=from_bounds(left, bottom, right, top, transform=raster.transform))
    for cells in (whole, region):
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


def _starters_statistics() -> str:
    """The statistics a Raster Calculator's code starts by showing: its lines
    from ``# Statistics:`` to the statistics call, that call uncommented, as a
    node that takes them holds them."""
    lines = _starter("RASTER_CALCULATOR_CODE").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("# Statistics:")]
    calls = [i for i, line in enumerate(lines) if line.startswith("#   return curio_raster_statistics(")]
    assert len(starts) == len(calls) == 1 and starts[0] < calls[0], lines
    return "\n".join([*lines[starts[0]:calls[0]], lines[calls[0]][len("#   "):], ""])


def _returns(node: dict) -> str:
    """The raster algebra call a Raster Calculator's code returns, on its one
    uncommented ``return`` line: ``CALCULATE`` or ``STATISTICS``."""
    calls = re.findall(r"^return (curio_raster_\w+)\(", node["content"], re.M)
    assert len(calls) == 1, node["content"]
    return calls[0]


def _calculators(call: str) -> list:
    """The Raster Calculators whose code returns *call*, in the dataflow's order."""
    return [n for n in _nodes(CALCULATOR) if _returns(n) == call]


def _code_note(name: str) -> list[str]:
    """The comment lines ``compareCode.ts`` starts a Compare Scenarios node's code with."""
    source = COMPARE_CODE_TS.read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = \[(.*?)\];", source, re.S)
    assert match, f"{name} is not in {COMPARE_CODE_TS}"
    return [ast.literal_eval(line.strip().rstrip(",")) for line in match.group(1).strip().splitlines()]


def _literal_dict(source: str, name: str) -> dict:
    """The dict literal *source* assigns to *name*, wherever it is."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not assigned in the source")


def _scout_classes() -> dict:
    return _literal_dict(SCOUT_FUNCTION.read_text(encoding="utf-8"), "dict_use_NBS_classes")


def _function_body(code: str) -> str:
    """A node's code as the sandbox runs it, the body of ``userCode`` under its
    header, made a module body for ast."""
    from utk_curio.sandbox.util.input_names import user_code_header

    body = textwrap.indent(code, "    ")
    return f"{user_code_header(body)}\n{body}"


def _feeds(spec: dict, node_id: str) -> dict:
    """``{circle: source id}`` of the edges into *node_id*."""
    return {e["targetHandle"]: e["source"] for e in spec["edges"] if e["target"] == node_id}


def _loader_of(dataset_id: str) -> dict:
    """The one Data Loading node whose code reads *dataset_id*."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code

    (loader,) = [n for n in _nodes(LOADING) if dataset_id in dataset_ids_in_code(n["content"])]
    return loader


def _members(spec: dict) -> set:
    return {node_id for scenario in spec["scenarios"] for node_id in scenario["nodes"]}


def _riverside(spec: dict) -> dict:
    """The Data Transformation in no scenario: the riverside tracts."""
    members = _members(spec)
    (riverside,) = [n for n in spec["nodes"] if n["type"] == TRANSFORMATION and n["id"] not in members]
    return riverside


def _scenario_parts(spec: dict) -> dict:
    """Each scenario's nodes by their part, one node per part: its Raster
    Calculator that chooses the depth (``choose``), the one of statistics, its
    depth map, and its Data Transformations, the one with the NbS widget
    averaging by period and the other per tract (``tract depth``)."""
    nodes = {n["id"]: n for n in spec["nodes"]}
    parts = {}
    for scenario in spec["scenarios"]:
        found = {}
        for node in (nodes[i] for i in scenario["nodes"]):
            if node["type"] == CALCULATOR:
                part = "choose" if _returns(node) == CALCULATE else "statistics"
            elif node["type"] == MAP:
                part = "depth map"
            elif node["type"] == TRANSFORMATION:
                part = "by period" if node["metadata"].get("widgets") else "tract depth"
            else:
                raise AssertionError(f"{scenario['id']} holds a {node['type']} node")
            assert part not in found, (scenario["id"], part)
            found[part] = node
        parts[scenario["id"]] = found
    return parts


def _compares(spec: dict) -> dict:
    """Each Compare Scenarios node, by the part of the scenarios both its
    inputs are and its mode: ``("choose", "difference")`` subtracts the depths."""
    part_of = {node["id"]: part for parts in _scenario_parts(spec).values() for part, node in parts.items()}
    found = {}
    for compare in [n for n in spec["nodes"] if n["type"] == COMPARE]:
        (part,) = {part_of[source] for source in _feeds(spec, compare["id"]).values()}
        key = (part, compare["metadata"]["compareScenarios"]["mode"])
        assert key not in found, key
        found[key] = compare
    return found


def _map_after(spec: dict, node_id: str) -> dict:
    """The one Autark map *node_id* feeds, which reads nothing else."""
    kinds = {n["id"]: n["type"] for n in spec["nodes"]}
    (map_id,) = [e["target"] for e in spec["edges"] if e["source"] == node_id and kinds[e["target"]] == MAP]
    assert [(e["source"], e["sourceHandle"], e["targetHandle"]) for e in spec["edges"] if e["target"] == map_id] == [
        (node_id, "out", "in"),
    ]
    (found,) = [n for n in spec["nodes"] if n["id"] == map_id]
    return found


def test_the_dataflow_is_made_of_curios_own_nodes():
    """No package: three Parameter nodes; five Data Loading nodes, three for
    the seven rasters and one each for the tracts and the waterways; a Data
    Transformation keeping the riverside tracts; two Raster Calculators per
    scenario, one choosing the depth and one taking its statistics, an Autark
    map of the depth and two Data Transformations, the depth per tract and by
    period; five Compare Scenarios nodes; Autark maps of the vulnerability, of
    the change in depth and of the change per tract; and the nine datasets.
    Nothing is pinned to the dashboard: a difference of SCOUT's whole grid is
    over a dashboard page's 25 MB."""
    spec = _dataflow()
    assert spec["packages"] == []
    assert all(n["type"].startswith("curio.builtin/") for n in spec["nodes"])
    assert [ref["datasetId"] for ref in spec["datasets"]] == DATASET_IDS
    counts = {}
    for n in spec["nodes"]:
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    assert counts == {PARAMETER: 3, LOADING: 5, CALCULATOR: 4, TRANSFORMATION: 5, MAP: 5, COMPARE: 5}
    assert sorted(_returns(n) for n in _nodes(CALCULATOR)) == [CALCULATE, CALCULATE, STATISTICS, STATISTICS]
    assert [n["id"] for n in spec["nodes"] if n.get("dashboardPinned")] == []


def test_the_parameters_hold_scouts_period_and_corners():
    """SCOUT's flood example's period and corners, as its own dataflow sets them."""
    parameters = _parameters()
    assert set(parameters) == {"timeline", "topleft", "bottomright"}
    timeline = parameters["timeline"]
    assert timeline["type"] == "choice" and timeline["options"] == {"choices": list(PERIODS), "display": "radio"}
    assert timeline["default"] == "2020 - 2040"
    top, left, bottom, right = SCOUT_REGION
    assert parameters["topleft"]["type"] == parameters["bottomright"]["type"] == "location"
    assert parameters["topleft"]["default"] == {"lat": top, "lon": left}
    assert parameters["bottomright"]["default"] == {"lat": bottom, "lon": right}


def test_the_loaders_read_their_datasets_by_id_and_the_rasters_with_the_regions_bounds():
    """Each Data Loading node reads its datasets by literal id, the only kind a
    run resolves: SCOUT's rasters with the bounds the corners give, and the
    tracts and the waterways whole, since they are cut to SCOUT's grid."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code

    read = sorted(tuple(dataset_ids_in_code(n["content"])) for n in _nodes(LOADING))
    assert read == sorted([
        (CLASSES,),
        tuple(_depth_id(p, True) for p in PERIODS),
        tuple(_depth_id(p, False) for p in PERIODS),
        (TRACTS,),
        (WATERWAYS,),
    ])
    for loader in _nodes(LOADING):
        ids = dataset_ids_in_code(loader["content"])
        windowed = re.findall(r"curio_load_data\(\"[^\"]+\", bounds=bounds\)", loader["content"])
        whole = re.findall(r"curio_load_data\(\"[^\"]+\"\)", loader["content"])
        if set(ids) <= set(RASTER_IDS):
            assert (len(windowed), len(whole)) == (len(ids), 0), loader["content"]
        else:
            assert (len(windowed), len(whole)) == (0, len(ids)) == (0, 1), loader["content"]


def test_each_scenario_chooses_by_scouts_classes_takes_the_statistics_and_maps_the_depth():
    """The two Raster Calculators that choose hold one code, SCOUT's class
    table, and differ in the solutions their widget chooses; the NbS scenario
    is a copy of the other. Each feeds a Raster Calculator holding the
    statistics its code starts by showing, and an Autark map of its depth."""
    from utk_curio.backend.app.execution.code_references import resolve_references

    spec = _dataflow()
    nodes = {n["id"]: n for n in spec["nodes"]}
    calculators = _calculators(CALCULATE)
    (code,) = {n["content"] for n in calculators}
    for calculator in calculators:
        # The code reads its widget through a chip, so it parses once resolved,
        # as a run sends it.
        resolved, problems = resolve_references(code, calculator["metadata"]["widgets"], "python")
        assert problems == [], (calculator["id"], problems)
        assert _literal_dict(_function_body(resolved), "NBS_CLASSES") == _scout_classes()
    assert "return curio_raster_calculate(\"choose\", [input_0, input_1, input_2], codes=codes)" in code
    assert {n["content"] for n in _calculators(STATISTICS)} == {_starters_statistics()}

    loaders = {
        "classes": _loader_of(CLASSES)["id"],
        "nbs": _loader_of(_depth_id(PERIODS[0], True))["id"],
        "no-nbs": _loader_of(_depth_id(PERIODS[0], False))["id"],
    }
    assert len(set(loaders.values())) == 3, loaders
    scenarios = {s["id"]: s for s in spec["scenarios"]}
    assert set(scenarios) == {"no-nbs", "nbs"}
    chosen = {}
    for scenario in scenarios.values():
        members = [nodes[i] for i in scenario["nodes"]]
        assert sorted(n["type"] for n in members) == sorted([MAP, CALCULATOR, CALCULATOR, TRANSFORMATION, TRANSFORMATION])
        (calculator,) = [n for n in members if n["type"] == CALCULATOR and _returns(n) == CALCULATE]
        (statistics,) = [n for n in members if n["type"] == CALCULATOR and _returns(n) == STATISTICS]
        (depth_map,) = [n for n in members if n["type"] == MAP]
        feeds = {e["targetHandle"]: e["source"] for e in spec["edges"] if e["target"] == calculator["id"]}
        assert feeds == {"in": loaders["classes"], "in_1": loaders["nbs"], "in_2": loaders["no-nbs"]}
        assert [e["source"] for e in spec["edges"] if e["target"] == statistics["id"]] == [calculator["id"]]
        assert [e["source"] for e in spec["edges"] if e["target"] == depth_map["id"]] == [calculator["id"]]
        (widget,) = calculator["metadata"]["widgets"]
        assert {k: widget[k] for k in ("name", "type", "default", "options")} == {
            "name": "use_NBS_classes", "type": "checkbox-group", "default": ALL_NBS, "options": {"choices": ALL_NBS},
        }
        chosen[scenario["name"]] = widget["value"]
    assert chosen == {"No NbS": [], "NbS": ALL_NBS}
    copies = {nodes[i]["metadata"]["copiedFrom"][-1] for i in scenarios["nbs"]["nodes"]}
    assert copies == set(scenarios["no-nbs"]["nodes"])


def test_each_scenarios_map_draws_its_depth_in_blues_with_its_legend_titled():
    """Each Autark map holds one document: the depth's band in autk-grammar's
    blues, over the range both maps share, its legend titled by the grammar's
    ``title``, valid for the grammar."""
    from utk_curio.backend.app.agents.domain import document_validation

    members = {node_id for scenario in _dataflow()["scenarios"] for node_id in scenario["nodes"]}
    maps = [n for n in _nodes(MAP) if n["id"] in members]
    assert len(maps) == 2
    for depth_map in maps:
        assert json.loads(depth_map["content"]) == MAP_DOCUMENT, depth_map["content"]
        named = depth_map["content"].replace("[!! input_0 !!]", "input_0")
        assert document_validation.validate(MAP, named) == {"status": document_validation.STATUS_VALID}


def test_both_scenarios_maps_share_one_color_range_that_holds_every_depth():
    """The two scenarios' depth maps color over one range, so a color is the
    same depth on both: each holds the same ``colorMapRange``. It runs from 0
    to the deepest flood of any period, with or without NbS, rounded up to a
    whole metre, at the dataflow's corners, which take every cell of SCOUT's
    grid; another region only narrows it."""
    import numpy as np
    import rasterio

    spec = _dataflow()
    nodes = {n["id"]: n for n in spec["nodes"]}
    ranges = {}
    for scenario in spec["scenarios"]:
        (map_id,) = [node_id for node_id in scenario["nodes"] if nodes[node_id]["type"] == MAP]
        (layer,) = json.loads(nodes[map_id]["content"])["map"]["layerRefs"]
        ranges[scenario["id"]] = layer.get("colorMapRange")
    assert ranges == {"no-nbs": DEPTH_RANGE, "nbs": DEPTH_RANGE}, ranges

    deepest = 0.0
    for period in PERIODS:
        for nbs in (True, False):
            with rasterio.open(_data_file(_depth_id(period, nbs))) as raster:
                cells = np.ma.masked_invalid(raster.read(1, masked=True).astype("float64")).compressed()
            assert cells.size > 0 and float(cells.min()) >= DEPTH_RANGE[0], (period, nbs)
            deepest = max(deepest, float(cells.max()))
    assert deepest <= DEPTH_RANGE[1] < deepest + 1, (deepest, DEPTH_RANGE)


def test_an_autark_map_after_the_difference_draws_the_change_in_depth_on_a_sequential_scale():
    """The Compare Scenarios node in Difference draws no map of its own: an
    Autark map after it, in no scenario, draws the size of NbS minus No NbS, a
    difference with no sign, on a sequential scale, its legend titled by the
    grammar's ``title``, valid for the grammar."""
    from utk_curio.backend.app.agents.domain import document_validation

    spec = _dataflow()
    difference = _compares(spec)[("choose", "difference")]
    difference_map = _map_after(spec, difference["id"])
    assert difference_map["id"] not in _members(spec)
    assert json.loads(difference_map["content"]) == DIFFERENCE_MAP_DOCUMENT, difference_map["content"]
    named = difference_map["content"].replace("[!! input_0 !!]", "input_0")
    assert document_validation.validate(MAP, named) == {"status": document_validation.STATUS_VALID}


def test_the_riverside_tracts_read_cdcs_tracts_and_nhds_waterways_and_a_map_draws_their_vulnerability():
    """A Data Transformation in no scenario reads the SVI tracts on circle 0
    and the waterways on circle 1. An Autark map after it, in no scenario,
    draws each tract's SVI percentile in reds over the whole range a percentile
    takes, its legend titled by the grammar's ``title``, valid for the grammar."""
    from utk_curio.backend.app.agents.domain import document_validation

    spec = _dataflow()
    riverside = _riverside(spec)
    assert _feeds(spec, riverside["id"]) == {"in": _loader_of(TRACTS)["id"], "in_1": _loader_of(WATERWAYS)["id"]}
    vulnerability_map = _map_after(spec, riverside["id"])
    assert vulnerability_map["id"] not in _members(spec)
    assert json.loads(vulnerability_map["content"]) == VULNERABILITY_MAP_DOCUMENT, vulnerability_map["content"]
    named = vulnerability_map["content"].replace("[!! input_0 !!]", "input_0")
    assert document_validation.validate(MAP, named) == {"status": document_validation.STATUS_VALID}


def test_each_scenario_averages_its_depth_over_each_tracts_land_and_in_each_period():
    """In each scenario, Tract depth reads its Flood depth on circle 0, the
    riverside tracts on circle 1 and the waterways on circle 2; Average depth
    by period reads the riverside tracts and the waterways, and SCOUT's seven
    rasters itself, by literal id with the corners' bounds, choosing the
    depth with SCOUT's class table and the same solutions as its scenario's
    Flood depth. Each holds one code in both scenarios, and the NbS ones are
    copies of the No NbS ones."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
    from utk_curio.backend.app.execution.code_references import resolve_references

    spec = _dataflow()
    parts = _scenario_parts(spec)
    riverside, waterways = _riverside(spec)["id"], _loader_of(WATERWAYS)["id"]
    for scenario, part in parts.items():
        assert _feeds(spec, part["tract depth"]["id"]) == {
            "in": part["choose"]["id"], "in_1": riverside, "in_2": waterways,
        }, scenario
        assert _feeds(spec, part["by period"]["id"]) == {"in": riverside, "in_1": waterways}, scenario
        assert part["by period"]["metadata"]["widgets"] == part["choose"]["metadata"]["widgets"], scenario
    for name in ("tract depth", "by period"):
        (code,) = {part[name]["content"] for part in parts.values()}
        assert parts["nbs"][name]["metadata"]["copiedFrom"] == [parts["no-nbs"][name]["id"]], name
        assert "copiedFrom" not in parts["no-nbs"][name]["metadata"], name
    by_period = parts["no-nbs"]["by period"]
    assert sorted(dataset_ids_in_code(by_period["content"])) == sorted(RASTER_IDS)
    calls = re.findall(r"curio_load_data\(\"[^\"]+\", bounds=bounds\)", by_period["content"])
    assert len(calls) == len(RASTER_IDS), by_period["content"]
    shared = list(_parameters().values())
    resolved, problems = resolve_references(by_period["content"], by_period["metadata"]["widgets"], "python", shared=shared)
    assert problems == [], problems
    assert _literal_dict(_function_body(resolved), "NBS_CLASSES") == _scout_classes()


def test_an_autark_map_after_the_tract_difference_draws_the_size_of_each_tracts_change():
    """The Compare Scenarios node that subtracts the scenarios' tract depths
    draws no map of its own: an Autark map after it, in no scenario, draws the
    size of each tract's change in mean depth on the depth change's scale, its
    legend titled by the grammar's ``title``, valid for the grammar."""
    from utk_curio.backend.app.agents.domain import document_validation

    spec = _dataflow()
    change = _compares(spec)[("tract depth", "difference")]
    change_map = _map_after(spec, change["id"])
    assert change_map["id"] not in _members(spec)
    assert json.loads(change_map["content"]) == TRACT_CHANGE_MAP_DOCUMENT, change_map["content"]
    named = change_map["content"].replace("[!! input_0 !!]", "input_0")
    assert document_validation.validate(MAP, named) == {"status": document_validation.STATUS_VALID}


def test_every_nodes_code_resolves_with_nothing_left_over():
    from utk_curio.backend.app.execution.code_references import resolve_references

    shared = list(_parameters().values())
    for n in _dataflow()["nodes"]:
        if n["type"] in (LOADING, CALCULATOR, TRANSFORMATION):
            code, problems = resolve_references(n["content"], n["metadata"].get("widgets") or [], "python", shared=shared)
            assert problems == [], (n["id"], problems)
            assert "[!!" not in code
            compile(_function_body(code), n["id"], "exec")


def test_the_shipped_dataflows_compare_nodes_hold_the_code_they_write():
    """Each Compare Scenarios node holds the code it writes for its two inputs,
    No NbS in circle 0 and NbS in circle 1 (``utils/compare/compareCode.ts``):
    in Difference, the size of NbS minus No NbS of the depths, and of the
    tracts' mean depths joined on their FIPS code; as charts, the median depth
    in bars, each tract's SVI percentile against its mean depth in points, and
    the mean depth of each period in grouped bars, one bar per period and
    scenario, as it is."""
    spec = _dataflow()
    entries = ['    ("no-nbs", "No NbS", [!! input_0 !!]),', '    ("nbs", "NbS", [!! input_1 !!]),']
    compares = _compares(spec)
    labels = [
        {"scenario": "no-nbs", "name": "No NbS", "color": "#e76f51"},
        {"scenario": "nbs", "name": "NbS", "color": "#2a9d8f"},
    ]
    stack = "\n".join([*_code_note("STACK_CODE_NOTE"), "return curio_stack_scenarios([", *entries, "])", ""])
    expected = {
        ("choose", "difference"): (
            {"difference": {"absolute": True}},
            "\n".join([*_code_note("ABSOLUTE_CODE_NOTE"), "return curio_difference_scenarios([", *entries,
                       "], absolute=True)", ""]),
        ),
        ("statistics", "chart"): ({"chart": {"preset": "bar", "y": "median"}}, stack),
        ("tract depth", "difference"): (
            {"difference": {"absolute": True, "key": "FIPS"}},
            "\n".join([*_code_note("ABSOLUTE_CODE_NOTE"), "return curio_difference_scenarios([", *entries,
                       '], absolute=True, key="FIPS")', ""]),
        ),
        ("tract depth", "chart"): ({"chart": {"preset": "scatter", "x": "RPL_THEMES", "y": "mean_depth_m"}}, stack),
        ("by period", "chart"): (
            {"chart": {"preset": "grouped-bar", "x": "period", "y": "mean_depth_m", "aggregate": "none"}}, stack,
        ),
    }
    assert set(compares) == set(expected)
    parts = _scenario_parts(spec)
    for (part, mode), (settings, code) in expected.items():
        node = compares[(part, mode)]
        assert node["metadata"]["compareScenarios"] == {"inputs": labels, "mode": mode, **settings}, (part, mode)
        assert node["content"] == code, (part, mode)
        assert _feeds(spec, node["id"]) == {"in": parts["no-nbs"][part]["id"], "in_1": parts["nbs"][part]["id"]}
        assert node["id"] not in _members(spec)


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


def _shared(region=None, period=None) -> list:
    """The Parameter nodes' widgets, at *region* and *period* when given, else
    at the values the dataflow holds."""
    values = {}
    if region is not None:
        top, left, bottom, right = region
        values.update({"topleft": {"lat": top, "lon": left}, "bottomright": {"lat": bottom, "lon": right}})
    if period is not None:
        values["timeline"] = period
    shared = []
    for name, widget in _parameters().items():
        widget = copy.deepcopy(widget)
        if name in values:
            widget["value"] = values[name]
        shared.append(widget)
    return shared


def _runner(workspace, shared, *, fails=False):
    """Runs one node of the dataflow as Run All runs it in the sandbox, its
    references resolved against *shared*: ``(output, error)``."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
    from utk_curio.backend.app.execution.code_references import resolve_references

    def run(node, file_path, data_type, widgets=(), circles=0):
        inputs = [{"slot": slot} for slot in range(circles)]
        code, problems = resolve_references(node["content"], list(widgets), "python", inputs=inputs, shared=shared)
        assert problems == [], problems
        paths = {i: str(_data_file(i)) for i in dataset_ids_in_code(code)}
        result = _execute(code, file_path, node["type"], data_type, workspace, dataset_paths=paths)
        if result["stderr"]:
            if fails:
                return None, result["stderr"]
            raise AssertionError(result["stderr"])
        return result["output"], None

    return run


def _run_loaders(run) -> tuple[dict, str | None]:
    """Every Data Loading node: SCOUT's rasters come out rasters, and the
    tracts and the waterways layers."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code

    loaded = {}
    for loader in _nodes(LOADING):
        output, error = run(loader, "", "")
        if error:
            return loaded, error
        rasters = set(dataset_ids_in_code(loader["content"])) <= set(RASTER_IDS)
        assert output["dataType"] == ("raster" if rasters else "geodataframe"), output
        loaded[loader["id"]] = output["path"]
    return loaded, None


def _run_riverside_part(run, loaded: dict, depths: dict) -> dict:
    """The riverside tracts, then each scenario's Tract depth on its Flood
    depth (*depths*, the output of its Raster Calculator that chooses, by
    scenario) and its Average depth by period, as Run All runs them: the
    output of each, ``"riverside"`` and ``(scenario, part)``."""
    spec = _dataflow()
    riverside = _riverside(spec)
    waterways = loaded[_loader_of(WATERWAYS)["id"]]
    found = {}
    output, _ = run(riverside, repr([loaded[_loader_of(TRACTS)["id"]], waterways]), "outputs")
    assert output["dataType"] == "geodataframe", output
    found["riverside"] = output["path"]
    for scenario, parts in _scenario_parts(spec).items():
        output, _ = run(parts["tract depth"], repr([depths[scenario], found["riverside"], waterways]), "outputs")
        assert output["dataType"] == "geodataframe", output
        found[(scenario, "tract depth")] = output["path"]
        by_period = parts["by period"]
        output, _ = run(by_period, repr([found["riverside"], waterways]), "outputs", by_period["metadata"]["widgets"])
        assert output["dataType"] == "dataframe", output
        found[(scenario, "by period")] = output["path"]
    return found


def _run_both_scenarios_riverside_part(workspace) -> dict:
    """Run All's path to the riverside part at the dataflow's own settings:
    the loaders, each scenario's Raster Calculator that chooses, then the
    riverside part (:func:`_run_riverside_part`), with each output loaded."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    run = _runner(workspace, _shared())
    loaded, error = _run_loaders(run)
    assert error is None, error
    depths = {}
    for scenario, parts in _scenario_parts(_dataflow()).items():
        depth, _statistics, error = _run_scenario(run, loaded, parts["choose"], parts["statistics"])
        assert error is None, error
        depths[scenario] = depth["path"]
    paths = _run_riverside_part(run, loaded, depths)
    return {"run": run, "paths": paths, **{key: load_from_duckdb(path) for key, path in paths.items()}}


def _run_scenario(run, loaded: dict, calculator: dict, statistics: dict, chosen=None):
    """One scenario's Raster Calculator that chooses, its widget at *chosen*
    when given, else at the value the dataflow holds, then its Raster
    Calculator of statistics: ``(depth output, statistics output, error)``."""
    spec = _dataflow()
    feeds = {e["targetHandle"]: e["source"] for e in spec["edges"] if e["target"] == calculator["id"]}
    inputs = repr([loaded[feeds[handle]] for handle in ("in", "in_1", "in_2")])
    widgets = calculator["metadata"]["widgets"]
    if chosen is not None:
        widgets = [{**w, "value": list(chosen)} for w in widgets]
    depth, error = run(calculator, inputs, "outputs", widgets)
    if error:
        return None, None, error
    assert depth["dataType"] == "raster", depth
    statistics_output, error = run(statistics, depth["path"], "raster")
    if error:
        return depth, None, error
    assert statistics_output["dataType"] == "dataframe", statistics_output
    return depth, statistics_output, None


def run_dataflow(workspace, region=None, period=None, chosen=ALL_NBS, *, fails=False):
    """Run the dataflow's loaders and one scenario's two Raster Calculators,
    the one that chooses, then the one of statistics, as Run All runs them in
    the sandbox, with the Parameter
    nodes at *region* and *period* (the dataflow's own when not given) and the
    calculator's widget at *chosen*: ``(depth artifact id, depth, statistics)``,
    or with *fails* the first error."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    run = _runner(workspace, _shared(region, period), fails=fails)
    loaded, error = _run_loaders(run)
    if error:
        return error
    depth, statistics, error = _run_scenario(run, loaded, _calculators(CALCULATE)[0], _calculators(STATISTICS)[0], chosen)
    if error:
        return error
    return depth["path"], load_from_duckdb(depth["path"]), load_from_duckdb(statistics["path"])


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_dataflow_gives_what_scouts_function_gives(workspace, monkeypatch, case):
    """The same cells, transform, median and mean, exactly, as SCOUT's function
    on the same rasters, region, period and solutions."""
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
        assert ours.shape == cells.shape == PINS[case].shape
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


#: SCOUT's median and mean flood depth on its whole grid, without NbS and with
#: every NbS, for two periods (``PINS``).
SCOUT_DEPTHS = {
    "2020 - 2040": {"No NbS": (7.163970947265625, 6.346452299531106), "NbS": (4.900075276692708, 5.312285760833436)},
    "2050 - 2080": {"No NbS": (7.083333333333334, 4.972232118870031), "NbS": (5.666666666666667, 4.703412297068202)},
}


@pytest.mark.parametrize("period", sorted(SCOUT_DEPTHS))
def test_both_scenarios_at_the_dataflows_corners_give_scouts_median_and_mean(workspace, monkeypatch, period):
    """Run All's path at the dataflow's own corners: the loaders once, then
    each scenario's Raster Calculator that chooses, with the solutions its
    widget holds, and its Raster Calculator of statistics. Without NbS the
    median flood depth is 7.164 m
    and with every NbS 4.900 m in 2020 - 2040; 7.083 m and 5.667 m in
    2050 - 2080, SCOUT's numbers on its whole grid."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    monkeypatch.chdir(workspace)
    spec = _dataflow()
    nodes = {n["id"]: n for n in spec["nodes"]}
    run = _runner(workspace, _shared(period=period))
    loaded, error = _run_loaders(run)
    assert error is None, error
    found = {}
    for scenario in spec["scenarios"]:
        members = [nodes[i] for i in scenario["nodes"]]
        (calculator,) = [n for n in members if n["type"] == CALCULATOR and _returns(n) == CALCULATE]
        (statistics,) = [n for n in members if n["type"] == CALCULATOR and _returns(n) == STATISTICS]
        depth, table, error = _run_scenario(run, loaded, calculator, statistics)
        assert error is None, error
        raster = load_from_duckdb(depth["path"])
        try:
            assert (raster.height, raster.width) == SCOUT_SHAPE
        finally:
            raster.close()
        row = load_from_duckdb(table["path"]).iloc[0]
        found[scenario["name"]] = (float(row["median"]), float(row["mean"]))
    assert found == SCOUT_DEPTHS[period]


def test_the_depth_is_a_raster_autark_loads(workspace, monkeypatch):
    """The calculator's depth is what #718's raster route serves the Autark
    node, at its own size, inside its caps: SCOUT's whole grid, SCOUT's cells
    for the NbS scenario."""
    import numpy as np
    from rasterio.io import MemoryFile

    from utk_curio.sandbox.util.rasters import serve_raster

    _profile, cells, _tags, _metrics = run_scout(workspace / "s", monkeypatch, *CASES["scout-2020-all"])
    monkeypatch.chdir(workspace)
    art_id, depth, _table = run_dataflow(workspace)
    try:
        stored = depth.read(1)
    finally:
        depth.close()
    payload, meta = serve_raster(art_id, max_cells=AUTARK_MAX_CELLS, max_side=AUTARK_MAX_SIDE)
    assert meta["crs"] == "EPSG:4326" and (meta["width"], meta["height"], meta["count"]) == (2592, 2064, 1)
    a, b, c, d, e, f = meta["transform"]
    assert b == 0 and d == 0 and a > 0 and e < 0
    assert (c, f) == pytest.approx((SCOUT_REGION[1], SCOUT_REGION[0]), abs=1e-12)
    with MemoryFile(payload) as memory, memory.open() as served:
        assert served.read(1).tobytes() == stored.tobytes()
        assert np.array_equal(served.read(1), cells, equal_nan=True)


@pytest.mark.parametrize(
    "settings, sentence",
    [
        ({"region": (41.7, SCOUT_REGION[1], SCOUT_REGION[2], SCOUT_REGION[3])},
         "reach past data.scout.flood-nbs-classes, which covers west -90.6879323"),
        ({"region": (SCOUT_REGION[2], SCOUT_REGION[3], SCOUT_REGION[0], SCOUT_REGION[1])},
         "are not (west, south, east, north) with west less than east and south less than north"),
        ({"period": "2030"}, "There is no flood projection for '2030'. The periods: 2020 - 2040, 2050 - 2080, 2080 - 2100."),
    ],
)
def test_a_setting_the_dataflow_cannot_use_says_why(workspace, settings, sentence):
    error = run_dataflow(workspace, fails=True, **settings)
    assert isinstance(error, str) and sentence in error, error


# ---------------------------------------------------------------------------
# The riverside tracts: the nodes, in the sandbox, give what this file computes
# from the datasets on its own
# ---------------------------------------------------------------------------

def _riverside_by_hand():
    """The tracts that NHD's stream and river areas touch, and NHD's water,
    read from the datasets' files with geopandas."""
    import geopandas as gpd

    tracts = gpd.read_file(_data_file(TRACTS))
    water = gpd.read_file(_data_file(WATERWAYS))
    rivers = water[water["FTYPE"] == RIVER].union_all()
    return tracts[tracts.intersects(rivers)].reset_index(drop=True), water


def _grid_by_hand():
    """SCOUT's grid, every cell of which the dataflow's corners take: its
    transform, its shape, and each cell's area in km2 on the mean Earth's
    sphere, between its row's two edges."""
    import numpy as np
    import rasterio

    with rasterio.open(_data_file(CLASSES)) as raster:
        transform, shape = raster.transform, raster.shape
    edges = np.radians(transform.f + transform.e * np.arange(shape[0] + 1))
    rows = EARTH_RADIUS_KM ** 2 * np.radians(abs(transform.a)) * np.abs(np.sin(edges[:-1]) - np.sin(edges[1:]))
    return transform, shape, np.broadcast_to(rows[:, None], shape)


def _depth_by_hand(period: str, chosen):
    """The depth a scenario's Flood depth holds, from SCOUT's three rasters:
    with NbS where the cell's class is a chosen solution, without elsewhere,
    and 0 m where the raster it reads has no depth."""
    import numpy as np
    import rasterio

    codes = [code for code, name in _scout_classes().items() if name in chosen]
    with rasterio.open(_data_file(CLASSES)) as raster:
        classes = raster.read(1)
    depths = []
    for nbs in (True, False):
        with rasterio.open(_data_file(_depth_id(period, nbs))) as raster:
            depths.append(np.ma.filled(raster.read(1, masked=True).astype("float64"), np.nan))
    picked = np.where(np.isin(classes, codes), depths[0], depths[1])
    return np.where(np.isfinite(picked), picked, 0.0)


def _inside(shapes, transform, shape):
    """The cells whose centres lie in *shapes*."""
    from rasterio.features import geometry_mask

    return geometry_mask(list(shapes), out_shape=shape, transform=transform, invert=True)


CHOSEN = {"no-nbs": [], "nbs": ALL_NBS}


def test_the_riverside_tracts_are_the_28_tracts_nhds_rivers_touch(workspace, monkeypatch):
    """The Data Transformation keeps the tracts NHD's stream and river areas
    touch, with CDC's columns and outlines: 28 tracts in the three counties,
    where 81,021 people live, each with an SVI percentile."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    monkeypatch.chdir(workspace)
    run = _runner(workspace, _shared())
    loaded, error = _run_loaders(run)
    assert error is None, error
    riverside = _riverside(_dataflow())
    output, _ = run(riverside, repr([loaded[_loader_of(TRACTS)["id"]], loaded[_loader_of(WATERWAYS)["id"]]]), "outputs")
    ours = load_from_duckdb(output["path"])
    expected, _water = _riverside_by_hand()
    assert list(ours.columns) == [*TRACT_COLUMNS, "geometry"]
    assert ours.crs.to_epsg() == 4326
    assert list(ours["FIPS"]) == list(expected["FIPS"])
    assert ours.geometry.geom_equals_exact(expected.geometry, tolerance=1e-9).all()
    assert len(ours) == RIVERSIDE_TRACTS and int(ours["E_TOTPOP"].sum()) == RIVERSIDE_PEOPLE
    assert {code[:5] for code in ours["FIPS"]} == {"19163", "17161", "17073"}
    assert ours["RPL_THEMES"].between(0, 1).all()


def test_each_tracts_depth_is_its_lands_mean_weighted_by_area(workspace, monkeypatch):
    """Each scenario's Tract depth gives every riverside tract the mean depth
    of its cells that are not water, each cell weighted by its area, for the
    period the scenario maps (2020 - 2040), and that land's area: what this
    file computes cell by cell from SCOUT's rasters, tract by tract."""
    import numpy as np

    monkeypatch.chdir(workspace)
    ran = _run_both_scenarios_riverside_part(workspace)
    tracts, water = _riverside_by_hand()
    transform, shape, area = _grid_by_hand()
    wet = _inside(water.geometry, transform, shape)
    lands = [_inside([outline], transform, shape) & ~wet for outline in tracts.geometry]
    land_km2 = np.array([float(area[land].sum()) for land in lands])
    for scenario, chosen in CHOSEN.items():
        ours = ran[(scenario, "tract depth")]
        assert list(ours.columns) == [*TRACT_COLUMNS, "geometry", "mean_depth_m", "land_km2"], scenario
        assert ours.crs.to_epsg() == 4326
        assert list(ours["FIPS"]) == list(tracts["FIPS"]), scenario
        weighted = _depth_by_hand(PERIODS[0], chosen) * area
        means = np.array([float(weighted[land].sum()) for land in lands]) / land_km2
        assert ours["land_km2"].to_numpy() == pytest.approx(land_km2, abs=6e-4), scenario
        assert ours["mean_depth_m"].to_numpy() == pytest.approx(means, abs=6e-4), scenario
        assert (ours["mean_depth_m"] >= 0).all() and (ours["mean_depth_m"] <= DEPTH_RANGE[1]).all()
    assert float(land_km2.sum()) == pytest.approx(RIVERSIDE_LAND_KM2, abs=5e-3)


def test_each_period_average_is_the_riverside_lands_mean_and_agrees_with_the_tracts(workspace, monkeypatch):
    """Each scenario's Average depth by period gives, for each of SCOUT's
    three periods, the mean depth over all the riverside tracts' land with its
    scenario's solutions: what this file computes from SCOUT's rasters, and
    lower with every NbS in each period. For the period both scenarios map,
    it is their Tract depth averaged with each tract's land as its weight."""
    import numpy as np

    monkeypatch.chdir(workspace)
    ran = _run_both_scenarios_riverside_part(workspace)
    tracts, water = _riverside_by_hand()
    transform, shape, area = _grid_by_hand()
    land = _inside(tracts.geometry, transform, shape) & ~_inside(water.geometry, transform, shape)
    for scenario, chosen in CHOSEN.items():
        name = "NbS" if chosen else "No NbS"
        table = ran[(scenario, "by period")]
        assert list(table.columns) == ["period", "mean_depth_m", "land_km2"]
        assert table.to_dict("records") == [
            {"period": period, "mean_depth_m": PERIOD_DEPTHS[name][period], "land_km2": RIVERSIDE_LAND_KM2}
            for period in PERIODS
        ], scenario
        for period in PERIODS:
            depth = _depth_by_hand(period, chosen)
            assert round(float((depth * area)[land].sum()) / float(area[land].sum()), 3) == PERIOD_DEPTHS[name][period]
        per_tract = ran[(scenario, "tract depth")]
        weighted = float(np.average(per_tract["mean_depth_m"], weights=per_tract["land_km2"]))
        assert weighted == pytest.approx(PERIOD_DEPTHS[name][PERIODS[0]], abs=1e-3), scenario
    for period in PERIODS:
        assert PERIOD_DEPTHS["NbS"][period] < PERIOD_DEPTHS["No NbS"][period], period


def test_the_compare_nodes_give_the_columns_their_map_and_charts_read(workspace, monkeypatch):
    """Run in the sandbox on the riverside part's outputs: the difference
    joins the two scenarios' tracts on their FIPS code and gives each tract
    the size of its change in mean depth, which its map reads (in 2020 -
    2040, 23 tracts change, by up to 1.603 m, and 5 do not); the scatter's
    stacked table holds every tract in both scenarios with the SVI percentile
    and the mean depth its chart reads, and the grouped bars' one row per
    period and scenario."""
    import numpy as np
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    monkeypatch.chdir(workspace)
    ran = _run_both_scenarios_riverside_part(workspace)
    run, paths = ran["run"], ran["paths"]
    compares = _compares(_dataflow())
    outputs = {}
    for key, part in ((("tract depth", "difference"), "tract depth"), (("tract depth", "chart"), "tract depth"),
                      (("by period", "chart"), "by period")):
        output, _ = run(compares[key], repr([paths[("no-nbs", part)], paths[("nbs", part)]]), "outputs", circles=2)
        outputs[key] = load_from_duckdb(output["path"])

    none, nbs = ran[("no-nbs", "tract depth")], ran[("nbs", "tract depth")]
    change = outputs[("tract depth", "difference")]
    assert change.crs.to_epsg() == 4326
    assert list(change["FIPS"]) == list(none["FIPS"])
    assert change.geometry.geom_equals_exact(ran["riverside"].geometry, tolerance=1e-9).all()
    sizes = np.abs(nbs["mean_depth_m"].to_numpy() - none["mean_depth_m"].to_numpy())
    assert change["mean_depth_m"].to_numpy() == pytest.approx(sizes, abs=1e-12)
    assert list(change["change"]) == ["unchanged" if size == 0 else "changed" for size in sizes]
    assert (int((sizes > 0).sum()), int((sizes == 0).sum()), float(sizes.max())) == (23, 5, pytest.approx(1.603))
    for column in ("RPL_THEMES", "E_TOTPOP", "land_km2"):
        assert (change[column] == 0).all(), column

    points = outputs[("tract depth", "chart")]
    assert len(points) == 2 * RIVERSIDE_TRACTS
    assert list(points["scenario_name"]) == ["No NbS"] * RIVERSIDE_TRACTS + ["NbS"] * RIVERSIDE_TRACTS
    for column in ("RPL_THEMES", "mean_depth_m"):
        assert str(points[column].dtype) == "float64" and points[column].notna().all(), column

    bars = outputs[("by period", "chart")]
    assert list(bars.columns) == ["scenario", "scenario_name", "period", "mean_depth_m", "land_km2"]
    assert [(row["scenario_name"], row["period"], row["mean_depth_m"]) for row in bars.to_dict("records")] == [
        (name, period, PERIOD_DEPTHS[name][period]) for name in ("No NbS", "NbS") for period in PERIODS
    ]
