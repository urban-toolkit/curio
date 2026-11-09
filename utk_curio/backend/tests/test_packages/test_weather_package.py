"""The ``curio.weather@1`` nodes, run the way the canvas runs them.

UTCI from raster + weather, UTCI Zonal Mean, Reproject census to EPSG:3395 and
Project gt_65 column hold their settings and a call of a function of the
package's modules: ``weather_utci``'s ``utci_grid``, and ``weather_census``'s
``utci_zonal_mean``, ``reproject_census`` and ``gt65_column``. The three
loaders hold the read of a Data Catalog dataset. Each template's source, its
references resolved as a run resolves them, is run as the sandbox runs it
(``input_names.call_as_node``), with the package's modules staged as the
sandbox stages a node's modules (the ``package_modules`` fixture), on inputs
built here: a mean radiant temperature raster of three rows of four cells,
three hours of Milan's ERA5 table, and census polygons over the raster.

The values pinned below are what the nodes' code gave before it moved into
the modules: the old starters, run on these inputs with pythermalcomfort
3.9.8, rasterstats 0.21.0 and geopandas 1.1.3, gave them, and the new code
gave the same results, warnings and errors, to the last bit.

The libraries are imported inside the tests, so a checkout without one fails
its tests alone.
"""

from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "curio.weather@1"
PACKAGE_ID = "curio.weather"
#: The package's modules: the index, and the steps over the census polygons.
MODULES = ["weather_census", "weather_utci"]
#: Each starter that calls a module: its import, its settings with their
#: values, and the call it returns, its references written as a run writes
#: them.
STARTERS = {
    "utci-compute": (
        "from weather_utci import utci_grid",
        {"TIMESTAMP": 12, "UPSCALE_FACTOR": 1.0},
        "utci_grid(input_0, input_1, timestamp=TIMESTAMP, upscale_factor=UPSCALE_FACTOR)",
    ),
    "utci-zonal": (
        "from weather_census import utci_zonal_mean",
        {},
        "utci_zonal_mean(input_0, input_1, input_2)",
    ),
    "census-reproject": (
        "from weather_census import reproject_census",
        {"SOURCE_CRS": 32632, "TARGET_CRS": 3395},
        "reproject_census(input_0, source_crs=SOURCE_CRS, target_crs=TARGET_CRS)",
    ),
    "gt65-projection": (
        "from weather_census import gt65_column",
        {},
        "gt65_column(input_0)",
    ),
}
#: The chips each starter reads its inputs through (#706, #707).
CHIPS = {
    "utci-compute": ["[!! input_0 !!]", "[!! input_1 !!]"],
    "utci-zonal": ["[!! input_0 !!]", "[!! input_1 !!]", "[!! input_2 !!]"],
    "census-reproject": [],
    "gt65-projection": [],
}
#: What each module offers node code: its ``__all__``.
OFFERED = {
    "weather_utci": ["utci_grid"],
    "weather_census": ["utci_zonal_mean", "reproject_census", "gt65_column"],
}

NODATA = -9999.0
#: Mean radiant temperature in degrees C: the last cell of the second row is
#: nodata, and 65, 68 and 70 are over 30 degrees above the air at noon.
MRT = [
    [40.0, 50.0, 60.0, 70.0],
    [45.0, 55.0, 65.0, NODATA],
    [35.0, 52.0, 68.0, 62.0],
]
NAN = float("nan")
#: UTCI of each cell at noon (it 12: Td 34.9, Wind 1.8, RH 34) and at 13 (Td
#: 35.9, Wind 1.2, RH 32), as the old code gave it.
UTCI_AT_NOON = [[35.9, 38.3, 40.7, 43.2], [37.1, 39.5, 41.9, NAN], [34.7, 38.7, 42.7, 41.2]]
UTCI_AT_13 = [[36.9, 39.3, 41.8, 44.3], [38.1, 40.6, 43.1, NAN], [35.7, 39.8, 43.8, 42.3]]
#: Read at half its width and height, the raster is one row of two cells: the
#: nearest cells are 55 and the nodata cell.
UTCI_AT_HALF_SIZE = [[39.5, NAN]]
#: The census polygons' mean UTCI at noon: the top-left four cells, the
#: top-right four but the nodata cell, the nodata cell alone, and none.
MEANS_AT_NOON = [(35.9 + 38.3 + 37.1 + 39.5) / 4, (40.7 + 43.2 + 41.9) / 3, NAN, NAN]
#: The bounds, in EPSG:3395, of the two polygons Reproject census keeps of
#: the table ``_merged`` builds.
KEPT_BOUNDS = [
    (1001875.4171394621, 5615423.331886688, 1001903.7411858232, 5615451.65593305),
    (1001875.4171394621, 5615409.16978548, 1001932.0650538257, 5615423.331931277),
]


def _same(values, expected) -> bool:
    """Whether two lists of rows of floats are equal, NaN where the other is
    NaN, within a millionth."""
    if len(values) != len(expected):
        return False
    for row, wanted in zip(values, expected):
        if len(row) != len(wanted):
            return False
        for value, other in zip(row, wanted):
            if math.isnan(other):
                if not math.isnan(value):
                    return False
            elif value != pytest.approx(other, abs=1e-6):
                return False
    return True


def _manifest() -> dict:
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def _template_source(template: str) -> str:
    (entry,) = [t for t in _manifest()["templates"] if t["id"] == template]
    return (PACKAGE / entry["source"]).read_text(encoding="utf-8")


def node_code(template: str, **settings) -> str:
    """The template's code with *settings* set, as a person edits them, and
    its references written as a run writes them."""
    from utk_curio.backend.app.execution.code_references import resolve_references

    code = _template_source(template)
    for name, value in settings.items():
        code, count = re.subn(rf"^{name} = .*$", f"{name} = {value!r}", code, count=1, flags=re.M)
        assert count == 1, f"{template} sets no {name}"
    resolved, problems = resolve_references(code, [], "python", inputs=[{"slot": k} for k in range(3)])
    assert problems == [], problems
    return resolved


def run_node(template: str, value, slots, **settings):
    """The node's output for *value* on the circles *slots*, its code run as
    the sandbox runs it. The package's modules must be staged
    (``package_modules``)."""
    from utk_curio.sandbox.util.input_names import call_as_node

    body = "\n".join("    " + line for line in node_code(template, **settings).splitlines())
    return call_as_node(body, {}, value, slots)


@pytest.fixture()
def package_modules(tmp_path):
    """While the test runs, the package's modules import by name, staged into
    a folder of the run's own as the sandbox stages them
    (``staging.stage_package_modules``). Yields what was staged."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run-weather"
    run.mkdir()
    staged = stage_package_modules({"root": str(PACKAGE / "sources"), "names": MODULES}, str(run))
    with importable(str(run / staged["root"]), staged["names"]):
        yield staged


@pytest.fixture()
def mrt(tmp_path):
    """``MRT`` as a GeoTIFF of 10 m cells in EPSG:32632, its corner at
    (500000, 5000030), opened as Milan MRT Loader opens one."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    path = tmp_path / "mrt.tif"
    values = np.asarray(MRT, dtype="float32")
    with rasterio.open(
        path, "w", driver="GTiff", width=4, height=3, count=1, dtype="float32",
        crs="EPSG:32632", transform=from_origin(500000, 5000030, 10, 10), nodata=NODATA,
    ) as handle:
        handle.write(values, 1)
    with rasterio.open(path) as dataset:
        yield dataset


def _weather():
    """Three hours of Milan's ERA5 table, it 11 to 13, with two of its other
    columns."""
    import pandas as pd

    return pd.DataFrame({
        "%iy": [2022, 2022, 2022],
        "it": [11, 12, 13],
        "Wind": [2.2, 1.8, 1.2],
        "RH": [37, 34, 32],
        "Td": [33.8, 34.9, 35.9],
        "press": [100.0, 99.96, 99.92],
    })


def _census(crs="EPSG:32632"):
    """Four census polygons over ``MRT``'s cells: the top-left four, the
    top-right four (the nodata cell among them), the nodata cell alone, and
    one off the raster, with their ``gt_65`` and a ``name``."""
    import geopandas as gpd
    from shapely.geometry import box

    return gpd.GeoDataFrame(
        {"name": ["a", "b", "c", "d"], "gt_65": [120, 85, 40, 7]},
        geometry=[
            box(500000, 5000010, 500020, 5000030),
            box(500020, 5000010, 500040, 5000030),
            box(500032, 5000012, 500038, 5000018),
            box(600000, 5000000, 600010, 5000010),
        ],
        crs=crs,
    )


def _merged(crs="EPSG:32632"):
    """What UTCI Zonal Mean hands Reproject census: geometry, ``mean`` and
    ``gt_65``, with a mean of 0, one below 0 and one missing."""
    import geopandas as gpd
    from shapely.geometry import box

    return gpd.GeoDataFrame(
        {"mean": [41.25, 0.0, -3.5, NAN, 39.0], "gt_65": [120, 85, 40, 7, 64]},
        geometry=[
            box(500000, 5000010, 500020, 5000030),
            box(500020, 5000010, 500040, 5000030),
            box(500032, 5000012, 500038, 5000018),
            box(600000, 5000000, 600010, 5000010),
            box(500000, 5000000, 500040, 5000010),
        ],
        crs=crs,
    )


# ---------------------------------------------------------------------------
# The package
# ---------------------------------------------------------------------------

def test_the_package_ships_two_modules_beside_its_seven_templates():
    """The index's module and the census polygons' module: only
    ``weather_utci`` loads ``pythermalcomfort``, whose code numba compiles as
    it loads, so UTCI Zonal Mean and Reproject census never load it."""
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.repositories.python_modules import module_names

    manifest = load_package_manifest(PACKAGE)
    assert [t.template_id for t in manifest.templates] == [
        "mrt-load", "weather-load", "census-load", "utci-compute", "utci-zonal", "census-reproject",
        "gt65-projection",
    ]
    assert module_names(PACKAGE, manifest) == frozenset(MODULES)
    imported = {}
    for module in MODULES:
        tree = ast.parse((PACKAGE / "sources" / f"{module}.py").read_text(encoding="utf-8"))
        imported[module] = sorted(
            {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
            | {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        )
    assert imported == {
        "weather_census": ["numpy", "rasterstats"],
        "weather_utci": ["numpy", "pythermalcomfort", "rasterio"],
    }, imported


def test_a_run_of_each_node_is_handed_the_packages_modules(tmp_curio):
    """A run of any node of the package is handed both modules
    (``python_modules.modules_for_node``), so its code imports them by name."""
    from utk_curio.backend.app.packages.application.python_modules import modules_for_node
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir

    install_package_from_directory("guest", PACKAGE)
    handed = {"root": str(package_dir("guest", PACKAGE.name) / "sources"), "names": MODULES}
    for template in _manifest()["templates"]:
        assert modules_for_node("guest", f"{PACKAGE_ID}/{template['id']}") == handed, template["id"]


@pytest.mark.parametrize("template", sorted(STARTERS))
def test_each_starter_is_its_settings_and_a_call_into_a_module(template):
    """A node's logic is in functions of its package's modules, and its code
    holds its settings and a short call: its docstring, the import of one
    function of a module, its settings as constants, and the return of that
    function's call, which reads every setting. UTCI from raster + weather and
    UTCI Zonal Mean read their inputs through chips (#706)."""
    imported, settings, call = STARTERS[template]
    code = _template_source(template)
    assert "utk_curio" not in code
    assert [chip for chip in CHIPS[template] if chip not in code] == [], code
    tree = ast.parse("def node():\n" + "\n".join("    " + line for line in node_code(template).splitlines()))
    body = tree.body[0].body
    kinds = [type(statement).__name__ for statement in body]
    assert kinds == ["Expr", "ImportFrom", *["Assign"] * len(settings), "Return"], kinds
    assert isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str), ast.dump(body[0])
    assert ast.unparse(body[1]) == imported
    assigned = {
        statement.targets[0].id: ast.literal_eval(statement.value)
        for statement in body[2:-1]
        if len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name)
    }
    assert assigned == settings
    assert ast.unparse(body[-1].value) == call


def test_the_modules_offer_the_functions_their_all_names(package_modules):
    """What node code calls is what each module's ``__all__`` names: each name
    is a function the module defines, whose docstring's first paragraph says
    what it does, and the module defines no other public function. Each
    starter calls one of them, and no module imports Curio's code or calls a
    ``curio_`` function."""
    import importlib
    import inspect

    for name, offered in OFFERED.items():
        module = importlib.import_module(name)
        assert list(module.__all__) == offered, (name, module.__all__)
        public = sorted(
            attr for attr, value in vars(module).items()
            if inspect.isfunction(value) and value.__module__ == name and not attr.startswith("_")
        )
        assert public == sorted(offered), (name, public)
        for function in offered:
            assert (inspect.getdoc(getattr(module, function)) or "").split("\n\n")[0].strip(), (name, function)
        tree = ast.parse(inspect.getsource(module))
        names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        names += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not [m for m in names if m.split(".")[0] == "utk_curio"], (name, names)
        assert not [n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id.startswith("curio_")], name
    for starter in STARTERS.values():
        module, function = starter[0].removeprefix("from ").split(" import ")
        assert function in OFFERED[module] and starter[2].startswith(f"{function}("), starter[0]


# ---------------------------------------------------------------------------
# UTCI from raster + weather
# ---------------------------------------------------------------------------

def test_utci_from_raster_and_weather_at_noon(package_modules, mrt):
    """The index of each cell under the weather of hour 12: NaN where the
    raster has no value, and a value for the cells over 30 degrees above the
    air, which pythermalcomfort's default would make NaN. The grid is lists,
    and its shape ``[width, height]``."""
    grid, shape = run_node("utci-compute", [mrt, _weather()], [0, 1])
    assert isinstance(grid, list) and all(isinstance(row, list) for row in grid)
    assert shape == [4, 3]
    assert _same(grid, UTCI_AT_NOON), grid


def test_utci_from_raster_and_weather_reads_the_hour_its_timestamp_names(package_modules, mrt):
    grid, shape = run_node("utci-compute", [mrt, _weather()], [0, 1], TIMESTAMP=13)
    assert shape == [4, 3]
    assert _same(grid, UTCI_AT_13), grid


def test_utci_from_raster_and_weather_reads_the_raster_at_its_upscale_factor(package_modules, mrt):
    grid, shape = run_node("utci-compute", [mrt, _weather()], [0, 1], UPSCALE_FACTOR=0.5)
    assert shape == [2, 1]
    assert _same(grid, UTCI_AT_HALF_SIZE), grid


def test_utci_from_raster_and_weather_fails_on_an_hour_the_table_lacks(package_modules, mrt):
    with pytest.raises(IndexError, match="index 0 is out of bounds for axis 0 with size 0"):
        run_node("utci-compute", [mrt, _weather()], [0, 1], TIMESTAMP=99)


def test_the_milan_weather_dataset_says_its_temperature_is_the_air_temperature_utci_reads():
    """``utci_grid`` hands the ``Td`` column to pythermalcomfort as ``tdb``, its
    dry-bulb air temperature, so the dataset's description, which agents read,
    names the air temperature and no dew point."""
    module = (PACKAGE / "sources" / "weather_utci.py").read_text(encoding="utf-8")
    assert re.search(r'tdb = float\(hour\["Td"\]', module), "utci_grid no longer reads Td as tdb"
    manifest = json.loads((REPO / "datasets" / "data.utk.milan-era5-weather@1" / "manifest.json").read_text())
    assert "air temperature" in manifest["description"], manifest["description"]
    assert "dew point" not in manifest["description"], manifest["description"]


# ---------------------------------------------------------------------------
# UTCI Zonal Mean
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pair", [tuple, list], ids=["a-tuple", "a-list"])
def test_utci_zonal_mean_of_each_census_polygon(package_modules, mrt, pair):
    """Each polygon's mean over the cells whose center it holds, NaN cells
    left out, and NaN for a polygon over no cell with a value. The polygons
    keep their geometry, ``mean`` and ``gt_65``, and the table handed in
    gains ``mean`` too."""
    census = _census()
    out = run_node("utci-zonal", [mrt, pair([UTCI_AT_NOON, [4, 3]]), census], [0, 1, 2])
    assert list(out.columns) == ["geometry", "mean", "gt_65"]
    assert out.crs.to_epsg() == 32632
    assert out["gt_65"].tolist() == [120, 85, 40, 7]
    assert _same([out["mean"].tolist()], [MEANS_AT_NOON]), out["mean"].tolist()
    assert out.geometry.geom_equals(_census().geometry).all()
    assert _same([census["mean"].tolist()], [MEANS_AT_NOON]), census.columns


def test_utci_zonal_mean_places_a_smaller_grid_by_its_shape(package_modules, mrt):
    """A grid read at half the raster's size covers it with cells twice as
    wide and three times as tall: one is the first polygon's, and the other
    is nodata."""
    out = run_node("utci-zonal", [mrt, (UTCI_AT_HALF_SIZE, [2, 1]), _census()], [0, 1, 2])
    assert _same([out["mean"].tolist()], [[39.5, NAN, NAN, NAN]]), out["mean"].tolist()


def test_utci_zonal_mean_keeps_a_census_without_a_crs_as_it_is(package_modules, mrt):
    out = run_node("utci-zonal", [mrt, (UTCI_AT_NOON, [4, 3]), _census(None)], [0, 1, 2])
    assert out.crs is None
    assert _same([out["mean"].tolist()], [MEANS_AT_NOON]), out["mean"].tolist()


def test_utci_zonal_mean_refuses_a_grid_that_is_not_two_dimensional(package_modules, mrt):
    with pytest.raises(ValueError, match=re.escape("Expected 2D UTCI array, got shape=(1, 3, 4), ndim=3")):
        run_node("utci-zonal", [mrt, ([UTCI_AT_NOON], [4, 3]), _census()], [0, 1, 2])


# ---------------------------------------------------------------------------
# Reproject census to EPSG:3395
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("crs", ["EPSG:32632", None], ids=["in-utm", "without-a-crs"])
def test_reproject_census_keeps_the_positive_means_in_world_mercator(package_modules, crs):
    """The polygons in EPSG:3395, those whose mean is 0, below 0 or missing
    left out, named ``census`` through ``__dict__``, so pandas does not warn
    of an attribute set on a slice of a table."""
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = run_node("census-reproject", _merged(crs), [0])
    assert [str(w.message) for w in caught if "new attribute name" in str(w.message)] == []
    assert out.crs.to_epsg() == 3395
    assert list(out.index) == [0, 4]
    assert list(out.columns) == ["mean", "gt_65", "geometry"]
    assert out["mean"].tolist() == [41.25, 39.0] and out["gt_65"].tolist() == [120, 64]
    for bounds, wanted in zip(out.geometry.bounds.itertuples(index=False), KEPT_BOUNDS):
        assert tuple(bounds) == pytest.approx(wanted, abs=1e-3)
    assert out.__dict__["metadata"] == {"name": "census"}


def test_reproject_census_refuses_a_table_in_another_crs(package_modules):
    with pytest.raises(ValueError, match="already has a CRS which is not equal to the passed CRS"):
        run_node("census-reproject", _merged("EPSG:4326"), [0])


# ---------------------------------------------------------------------------
# Project gt_65 column
# ---------------------------------------------------------------------------

def test_project_gt65_column_keeps_that_column_alone(package_modules):
    """A table of ``gt_65`` alone, its geometry left out, on the same index."""
    import geopandas as gpd

    out = run_node("gt65-projection", _census(), [0])
    assert not isinstance(out, gpd.GeoDataFrame)
    assert list(out.columns) == ["gt_65"]
    assert list(out.index) == [0, 1, 2, 3]
    assert out["gt_65"].tolist() == [120, 85, 40, 7]


# ---------------------------------------------------------------------------
# The three, wired as the README wires them
# ---------------------------------------------------------------------------

def test_the_three_nodes_wired_together(package_modules, mrt):
    """The index, its mean over the census polygons, and the polygons in
    EPSG:3395: the two polygons with a mean, in their order."""
    utci = run_node("utci-compute", [mrt, _weather()], [0, 1])
    merged = run_node("utci-zonal", [mrt, utci, _census()], [0, 1, 2])
    out = run_node("census-reproject", merged, [0])
    assert list(out.index) == [0, 1]
    assert out["mean"].tolist() == pytest.approx(MEANS_AT_NOON[:2], abs=1e-6)
    assert out["gt_65"].tolist() == [120, 85]
    assert out.crs.to_epsg() == 3395
    assert out.__dict__["metadata"] == {"name": "census"}
