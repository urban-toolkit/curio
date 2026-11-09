"""The ``ai.utk.uhvi@1`` package's UHVI Zonal Stats, run the way the canvas runs it.

UHVI Zonal Stats holds the call of ``zonal_mean``, the function of the
package's module ``uhvi_statistics``. Its template's source is run as the
sandbox runs it (``input_names.call_as_node``), with the module staged as the
sandbox stages a node's modules (the ``package_modules`` fixture), on a raster
of four by four cells, one of them nodata, and four zones over it.

The values pinned below are what the node's code gave before it moved into
the module: the old starter, run on these inputs with geopandas 1.1.3 and
rasterio 1.5.0, gave them, and the new code gave the same results, warnings
and errors, to the last bit. UHVI Loader and UHVI Zones hold a path and the
read of it, as a loader does, and no logic.

The libraries are imported inside the tests, so a checkout without one fails
its tests alone.
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "ai.utk.uhvi@1"
PACKAGE_ID = "ai.utk.uhvi"
SOURCE = PACKAGE / "sources" / "uhvi-zonal.py"
#: The package's module, which holds UHVI Zonal Stats' logic.
MODULE = "uhvi_statistics"

NODATA = -9999.0
#: The raster's cells: the one in row 1, column 1 is nodata.
UHVI = [
    [0.0, 1.0, 2.0, 3.0],
    [4.0, NODATA, 6.0, 7.0],
    [8.0, 9.0, 10.0, 11.0],
    [12.0, 13.0, 14.0, 15.0],
]
ZONES = ["top-left", "bottom-right", "nodata-cell", "off-raster"]
NAN = float("nan")
#: Each zone's mean: the top-left four cells but the nodata one, the
#: bottom-right four, the nodata cell alone (no value) and none.
MEANS = [(0.0 + 1.0 + 4.0) / 3, (10.0 + 11.0 + 14.0 + 15.0) / 4, NAN, NAN]


def _same(values, expected) -> bool:
    """Whether two lists of floats are equal, NaN where the other is NaN."""
    return len(values) == len(expected) and all(
        math.isnan(value) if math.isnan(wanted) else value == pytest.approx(wanted, abs=1e-9)
        for value, wanted in zip(values, expected)
    )


def run_node(value, slots):
    """UHVI Zonal Stats' output for *value* on the circles *slots*, its code
    run as the sandbox runs it. The module must be staged
    (``package_modules``)."""
    from utk_curio.sandbox.util.input_names import call_as_node

    body = "\n".join("    " + line for line in SOURCE.read_text(encoding="utf-8").splitlines())
    return call_as_node(body, {}, value, slots)


@pytest.fixture()
def package_modules(tmp_path):
    """While the test runs, the package's module imports by name, staged into
    a folder of the run's own as the sandbox stages it
    (``staging.stage_package_modules``). Yields what was staged."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run-uhvi"
    run.mkdir()
    staged = stage_package_modules({"root": str(PACKAGE / "sources"), "names": [MODULE]}, str(run))
    with importable(str(run / staged["root"]), staged["names"]):
        yield staged


@pytest.fixture()
def raster(tmp_path):
    """``UHVI`` as a GeoTIFF of 10 m cells in EPSG:32632, its corner at
    (500000, 5000040), opened as UHVI Loader opens one."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    path = tmp_path / "uhvi.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=4, height=4, count=1, dtype="float32",
        crs="EPSG:32632", transform=from_origin(500000, 5000040, 10, 10), nodata=NODATA,
    ) as handle:
        handle.write(np.asarray(UHVI, dtype="float32"), 1)
    with rasterio.open(path) as dataset:
        yield dataset


def _zones(crs="EPSG:32632"):
    """``ZONES`` over the raster's cells, in *crs*: the top-left two by two,
    the bottom-right two by two, a square inside the nodata cell, and one off
    the raster."""
    import geopandas as gpd
    from shapely.geometry import box

    zones = gpd.GeoDataFrame(
        {"zone": ZONES},
        geometry=[
            box(500000, 5000020, 500020, 5000040),
            box(500020, 5000000, 500040, 5000020),
            box(500012, 5000022, 500018, 5000028),
            box(600000, 5000000, 600010, 5000010),
        ],
        crs=None if crs is None else "EPSG:32632",
    )
    return zones if crs in (None, "EPSG:32632") else zones.to_crs(crs)


# ---------------------------------------------------------------------------
# The package
# ---------------------------------------------------------------------------

def test_the_package_ships_one_module_beside_its_three_templates():
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.repositories.python_modules import module_names

    manifest = load_package_manifest(PACKAGE)
    assert [(t.template_id, t.source) for t in manifest.templates] == [
        ("uhvi-load", "sources/uhvi-load.py"),
        ("uhvi-zones", "sources/uhvi-zones.py"),
        ("uhvi-zonal", "sources/uhvi-zonal.py"),
    ]
    assert module_names(PACKAGE, manifest) == frozenset({MODULE})


def test_a_run_of_each_node_is_handed_the_module(tmp_curio):
    """A run of any node of the package is handed its module
    (``python_modules.modules_for_node``), so its code imports it by name."""
    from utk_curio.backend.app.packages.application.python_modules import modules_for_node
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir

    install_package_from_directory("guest", PACKAGE)
    handed = {"root": str(package_dir("guest", PACKAGE.name) / "sources"), "names": [MODULE]}
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    for template in manifest["templates"]:
        assert modules_for_node("guest", f"{PACKAGE_ID}/{template['id']}") == handed, template["id"]


def test_the_starter_is_a_call_into_the_module():
    """A node's logic is in functions of its package's modules, and its code
    holds its settings and a short call: UHVI Zonal Stats has no settings, so
    its code is its docstring, the import of ``zonal_mean`` and the return of
    its call on both input circles, so a circle with no edge is None."""
    code = SOURCE.read_text(encoding="utf-8")
    assert "utk_curio" not in code
    body = ast.parse("def node():\n" + "\n".join("    " + line for line in code.splitlines())).body[0].body
    assert [type(statement).__name__ for statement in body] == ["Expr", "ImportFrom", "Return"]
    assert isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str), ast.dump(body[0])
    assert ast.unparse(body[1]) == f"from {MODULE} import zonal_mean"
    assert ast.unparse(body[2].value) == "zonal_mean(input_0, input_1)"


def test_the_module_offers_zonal_mean_and_says_what_it_does(package_modules):
    """What node code calls is what the module's ``__all__`` names: a function
    the module defines, whose docstring's first paragraph says what it does,
    and the module defines no other public function. It imports nothing of
    Curio's and calls no ``curio_`` function."""
    import importlib
    import inspect

    module = importlib.import_module(MODULE)
    assert list(module.__all__) == ["zonal_mean"]
    public = sorted(
        attr for attr, value in vars(module).items()
        if inspect.isfunction(value) and value.__module__ == MODULE and not attr.startswith("_")
    )
    assert public == ["zonal_mean"]
    first = " ".join((inspect.getdoc(module.zonal_mean) or "").split("\n\n")[0].split())
    assert "uhvi_mean" in first, first
    tree = ast.parse(inspect.getsource(module))
    imported = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    imported += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in imported if name.split(".")[0] == "utk_curio"], imported
    assert not [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id.startswith("curio_")]


# ---------------------------------------------------------------------------
# The node, run
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raster_first", [True, False], ids=["raster-on-circle-0", "zones-on-circle-0"])
def test_the_mean_of_each_zone_with_the_inputs_either_way_round(package_modules, raster, raster_first):
    """Each zone's mean over the cells whose center it holds, nodata left
    out, NaN for a zone over no cell with a value: a copy of the zones with
    ``uhvi_mean``, named ``uhvi_zonal``. The zones handed in are left as they
    are."""
    zones = _zones()
    out = run_node([raster, zones] if raster_first else [zones, raster], [0, 1])
    assert list(out.columns) == ["zone", "geometry", "uhvi_mean"]
    assert out["zone"].tolist() == ZONES
    assert out.crs.to_epsg() == 32632
    assert _same(out["uhvi_mean"].tolist(), MEANS), out["uhvi_mean"].tolist()
    assert out.__dict__["metadata"] == {"name": "uhvi_zonal"}
    assert list(zones.columns) == ["zone", "geometry"]


@pytest.mark.parametrize("crs", [None, "EPSG:4326"], ids=["without-a-crs", "in-wgs84"])
def test_zones_take_the_rasters_crs(package_modules, raster, crs):
    """Zones with no CRS are given the raster's; zones in another are
    reprojected to it. Either way each zone's mean is the same."""
    out = run_node([raster, _zones(crs)], [0, 1])
    assert out.crs.to_epsg() == 32632
    assert _same(out["uhvi_mean"].tolist(), MEANS), out["uhvi_mean"].tolist()


@pytest.mark.parametrize("inputs, slots, got", [
    ("raster", [0], "['DatasetReader']"),
    ("zones", [1], "['GeoDataFrame']"),
    ("raster and a table", [0, 1], "['DatasetReader', 'DataFrame']"),
], ids=["raster-alone", "zones-alone-on-circle-1", "raster-and-a-table"])
def test_anything_but_a_raster_and_zones_is_refused_with_what_came(package_modules, raster, inputs, slots, got):
    import pandas as pd

    value = {
        "raster": raster,
        "zones": _zones(),
        "raster and a table": [raster, pd.DataFrame({"a": [1]})],
    }[inputs]
    with pytest.raises(RuntimeError) as raised:
        run_node(value, slots)
    assert str(raised.value) == f"UHVI Zonal Stats expects a Raster + GeoDataFrame pair. Got: {got}"
