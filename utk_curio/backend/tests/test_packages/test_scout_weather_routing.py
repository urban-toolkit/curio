"""``scout.weather-routing@1``: SCOUT's weather-aware routing, ported.

The proof is SCOUT's own output. ``fixtures/scout/weather_routing`` holds what
SCOUT's ``calculate_weather_route`` wrote (routes as GeoJSON, metrics as CSV)
for two scenarios of its routing use case, from 1256 West Chicago Avenue to
1410 South Special Olympics Drive: its defaults ("Default weights", rain and
wind, leaving 2025-07-06 00:00) and "Single-factor weights" with rain 0.6 and
wind 0.3 leaving at 06:00 (see ``ATTRIBUTION.md`` there). The node, with the
Model Catalog's ONNX export of SCOUT's GNN and the Data Catalog's cut of its
road graph and WRF run of 6 July 2025, must draw the same routes through the same nodes and
measure them as SCOUT does.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import re
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("onnxruntime")
pytest.importorskip("xarray")

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "scout.weather-routing@1"
SOURCES = PACKAGE / "sources"
MODULE = "scout_weather_routing"
NODE_TYPE = "scout.weather-routing/weather-aware-routes"
MODEL_ID = "model.scout.weather-gnn"
MODEL_DIR = REPO / "models" / "model.scout.weather-gnn@1"
DATASET_ID = "data.scout.chicago-weather-2025-07-06"
BUNDLE = REPO / "datasets" / f"{DATASET_ID}@1" / "data" / "bundle.json"
ROADS_ID = "data.osm.chicago-roads"
ROADS = REPO / "datasets" / f"{ROADS_ID}@1" / "data" / "chicago-roads.parquet"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scout" / "weather_routing"
VARIABLES = ("RAIN", "T2", "WSPD10", "WDIR10", "RH2")

#: SCOUT's data layer for the use case, its roi: west, south, east, north.
ROI = (-87.662, 41.859, -87.613, 41.898)
ORIGIN = {"lat": 41.896438, "lon": -87.659758}
DESTINATION = {"lat": 41.861649, "lon": -87.614034}
SCENARIOS = {
    "default": dict(mode="Default weights", k=1, time="2025-07-06T00:00:00",
                    conditions={"rain": 0.85834, "wind": 0.01657}),
    "single": dict(mode="Single-factor weights", k=1, time="2025-07-06T06:00:00",
                   conditions={"rain": 0.6, "wind": 0.3}),
}
#: SCOUT names its outputs C, D, E in the order of its routes.
LETTERS = "CDE"


def _template() -> dict:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    (template,) = manifest["templates"]
    return template


def _model():
    from utk_curio.sandbox.util.catalog_helpers import CurioModel

    return CurioModel(MODEL_ID, str(MODEL_DIR))


def _part(name):
    from utk_curio.sandbox.util.catalog_helpers import bundle_part, read_dataset

    return read_dataset(*bundle_part(str(BUNDLE), name))


def _roads():
    from utk_curio.sandbox.util.catalog_helpers import read_dataset

    return read_dataset(str(ROADS), "parquet")


def _area(roads):
    west, south, east, north = ROI
    return roads.cx[west:east, south:north]


@contextlib.contextmanager
def _node_outputs(tmp_path):
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    staged = stage_package_modules({"root": str(SOURCES), "names": [MODULE]}, str(tmp_path))
    with importable(str(tmp_path / staged["root"]), staged["names"]):
        yield importlib.import_module(f"{MODULE}.node_outputs")


def _assert_scouts_routes(name, routes, endpoints):
    import numpy as np
    import pandas as pd

    folder = FIXTURES / name
    assert len(routes) == len(list(folder.glob("route_[A-Z].geojson")))
    for letter, row in zip(LETTERS, routes.itertuples(index=False)):
        (scout,) = json.loads((folder / f"route_{letter}.geojson").read_text())["features"]
        assert row.weight_type == scout["properties"]["weight_type"]
        # The same road nodes, in the same order.
        assert np.allclose(np.array(scout["geometry"]["coordinates"]), np.array(row.geometry.coords))
        metrics = pd.read_csv(folder / f"{letter}.csv").iloc[0]
        ours = {"distance": row.distance_km, "duration": row.duration_min, "rain_exposure": row.rain_exposure,
                "heat_exposure": row.heat_exposure, "wind_exposure": row.wind_exposure,
                "humidity_exposure": row.humidity_exposure}
        for column, value in ours.items():
            assert value == pytest.approx(metrics[column], rel=1e-4, abs=1e-6), (name, letter, column)
    for kind in ("origin", "destination"):
        (scout,) = json.loads((folder / f"route_{kind}.geojson").read_text())["features"]
        point = endpoints.loc[endpoints["kind"] == kind].geometry.iloc[0]
        assert np.allclose(scout["geometry"]["coordinates"], [point.x, point.y])


# ---------------------------------------------------------------------------
# The proof
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_node_draws_scouts_routes(name, tmp_path):
    roads = _roads()
    weather = {variable: _part(f"{variable}.nc") for variable in VARIABLES}
    with _node_outputs(tmp_path) as node:
        routes, endpoints, ribbons, metrics = node.weather_routes(
            _area(roads), roads, weather, _model(), ORIGIN, DESTINATION, **SCENARIOS[name],
        )
    _assert_scouts_routes(name, routes, endpoints)
    # Weighing the weather changes the route: not two fastest routes agreeing.
    assert routes.geometry.iloc[0] != routes.geometry.iloc[1]
    assert set(metrics["route"]) == set(routes["route"])
    assert set(metrics["metric"]) == {"Travel time (minutes)", "Distance (km)", "Rain exposure", "Wind exposure"}
    # One band per route, as wide as asked, around the route it draws.
    assert list(ribbons["route"]) == list(routes["route"])
    assert set(ribbons.geom_type) == {"Polygon"}
    utm = routes.estimate_utm_crs()
    for line, band in zip(routes.to_crs(utm).geometry, ribbons.to_crs(utm).geometry):
        assert band.contains(line.interpolate(0.5, normalized=True))
        assert band.area == pytest.approx(line.length * 40.0, rel=0.05)


def test_the_onnx_gnn_reads_any_graph():
    """The graph takes any number of nodes and edges, as SCOUT's GNN does."""
    import numpy as np

    rng = np.random.default_rng(0)
    for nodes, edges in ((5, 8), (300, 900)):
        x = rng.normal(size=(nodes, 7)).astype(np.float32)
        edge_index = rng.integers(0, nodes, size=(2, edges)).astype(np.int64)
        (weather,) = _model().run({"x": x, "edge_index": edge_index})
        assert weather.shape == (nodes, 5)


def test_a_place_outside_the_area_is_refused(tmp_path):
    roads = _roads()
    weather = {variable: _part(f"{variable}.nc") for variable in VARIABLES}
    with _node_outputs(tmp_path) as node, pytest.raises(ValueError, match="outside the area's roads"):
        node.weather_routes(_area(roads), roads, weather, _model(), {"lat": 41.95, "lon": -87.65},
                            DESTINATION, **SCENARIOS["default"])


# ---------------------------------------------------------------------------
# The template
# ---------------------------------------------------------------------------

def test_the_template_declares_the_widgets_its_source_reads():
    template = _template()
    assert template["hasWidgets"] is True
    declared = {w["name"] for w in template["widgets"]}
    source = (PACKAGE / template["source"]).read_text(encoding="utf-8")
    assert set(re.findall(r"\[!!\s*(\w+)\s*!!\]", source)) == declared
    assert f'curio_load_model("{MODEL_ID}")' in source
    assert f'curio_load_data("{ROADS_ID}")' in source
    assert f'curio_load_data("{DATASET_ID}", part="RAIN.nc")' in source
    defaults = {w["name"]: w["default"] for w in template["widgets"]}
    assert defaults["origin"] == ORIGIN and defaults["destination"] == DESTINATION
    assert defaults["mode"] == "Default weights" and defaults["conditions"] == ["rain", "wind"]


# ---------------------------------------------------------------------------
# The node, in the sandbox
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    release_connection()
    init_db()
    yield tmp_path
    release_connection()


def test_the_node_runs_in_the_sandbox(workspace):
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    _worker_init()
    area = save_to_duckdb(_area(_roads()), node_id="area")
    template = _template()
    source = (PACKAGE / template["source"]).read_text(encoding="utf-8")
    code, problems = resolve_references(source, [dict(w) for w in template["widgets"]], "python",
                                        inputs=[{"slot": 0}])
    assert problems == [], problems
    result = execute_code(
        textwrap.indent(code, "    "), area, NODE_TYPE, "geodataframe",
        save_dataset=False, media_dir=str(workspace / "media"),
        dataset_paths={DATASET_ID: str(BUNDLE), ROADS_ID: str(ROADS)},
        package_modules={"root": str(SOURCES), "names": [MODULE]},
        models={MODEL_ID: str(MODEL_DIR)},
    )
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "outputs", result["output"]
    routes, endpoints, ribbons, metrics = load_from_duckdb(result["output"]["path"])
    _assert_scouts_routes("default", routes, endpoints)
    assert list(metrics.columns) == ["route", "metric", "value"]
