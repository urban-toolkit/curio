"""``scout.routing@1``: SCOUT's weather-aware routing in Curio (#662, step 20).

The proof: the package's port of SCOUT's routing, on the cut of SCOUT's own road
graph and the Data Catalog's SCOUT WRF forecast, gives what SCOUT's own
``calculate_weather_route`` gave on them, recorded once by
``scripts/scout/reference_routing.py`` in SCOUT's stack (``fixtures/scout_routing/``,
see its ``ATTRIBUTION.md``). For each of SCOUT's eight recorded runs the weather
GNN's input is the same bit for bit, the routes are the same node for node, and
the metrics agree within 1e-3, with the GNN run as the Model Catalog's ONNX
model ``model.scout.weather-gnn`` instead of torch. SCOUT's run starts at the weather
step SCOUT read (``time_index``), so the proof feeds that step.

SCOUT's bugs the port fixes, each test pairing what SCOUT's run recorded with
what the port does: ``distance_m`` held kilometres; the data loader kept the
first start time; a mode with more routes than output names raised IndexError;
the hourly weather steps were read as 15-minute steps; and the origin's
longitude was checked against the northern edge.

The node: its template, with the widgets its manifest declares resolved as a run
resolves them, reads the WRF forecast and the GNN model by id and runs in the sandbox
with its package's modules (#719), on the roads the shipped example's Data
Loading node hands on, the Data Catalog's ``data.osm.chicago-downtown-roads``
(written by ``scripts/build_chicago_downtown_roads.py``): one GeoDataFrame, the
layer its layer chip ``[!! input_0:table_osm_roads !!]`` reads. It returns
``(routes, metrics)``.

Package code is imported inside each test, through a run's staged copy of the
package's modules, so a checkout without the package or its libraries fails
each test on its own and no bytecode lands in ``packages/``.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib
import json
import re
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE = REPO / "packages" / "scout.routing@1"
SOURCES = PACKAGE / "sources"
MODULE = "scout_routing"
NODE_TYPE = "scout.routing/weather-routing"
PYTHON_TYPE = "curio.builtin/computation-analysis"
DATAFLOW = REPO / "docs" / "examples" / "dataflows" / "WeatherRouting.json"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scout_routing"
REFERENCE = FIXTURES / "routing_reference.json"
#: The roads the example loads from the Data Catalog.
ROADS_ID = "data.osm.chicago-downtown-roads"
EXAMPLE_ROADS = REPO / "datasets" / f"{ROADS_ID}@1" / "data" / "roads.parquet"
#: The coordinate system an Autark data node names on each layer it hands on
#: (``autkDataCompile.ts``): World Mercator, the CRS Autark keeps its layers in.
CRS_3395 = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3395"}}

#: SCOUT's WRF forecast: one bundle dataset, a NetCDF file per variable.
WEATHER_ID = "data.scout.chicago-weather-2025-07-06"
WEATHER_VARIABLES = ("RAIN", "T2", "WSPD10", "WDIR10", "RH2")
GNN_ID = "model.scout.weather-gnn"
GNN_DIR = REPO / "models" / f"{GNN_ID}@1"
SCOUT_COMMIT = "b98369e50b2972c0fc22180f56da0ac99a98a545"
#: SCOUT's recorded runs, each one process (``loader-time`` is two calls in one).
CASES = ["default", "custom-k1", "custom-k2", "custom-k3", "single-factor", "default-later",
         "custom-k3-later", "loader-time"]
METRICS = ("distance", "duration", "rain_exposure", "heat_exposure", "wind_exposure", "humidity_exposure")
#: How far the port's metrics may be from SCOUT's: the GNN's ONNX outputs are
#: within 1e-4 of torch's, and an exposure sums a route's edges.
TOLERANCE = 1e-3

#: SCOUT's weather routing example (``routing_reference.json``'s ``example``):
#: the widget values the shipped dataflow's Weather Routing node holds.
EXAMPLE_VALUES = {
    "origin": {"lat": 41.896438, "lon": -87.659758},
    "destination": {"lat": 41.861649, "lon": -87.614034},
    "mode": "Default weights",
    "K": 1,
    "time": "2025-07-06T00:00:00",
    "rain": 0.85834,
    "wind": 0.01657,
}
#: Its two routes on the roads the dataflow loads from the Data Catalog
#: (OpenStreetMap today, not SCOUT's snapshot, so close to SCOUT's but not the same): per
#: route, ``(route, route_index, points, distance km, duration min, rain
#: exposure, wind exposure)``. As in SCOUT's, the weather-aware route trades
#: time and wind for less rain.
EXAMPLE = [
    ("fastest-route", 0, 299, 7.3598173248939185, 10.102611935770371, 2201.0672464370728, 610.4986320510507),
    ("weighted-route", 1, 264, 7.646003063522548, 12.365133939742854, 1992.3714365959167, 742.6831955313683),
]
#: The example's two scenarios, each keeping one of the routes: SCOUT's C and
#: D, in SCOUT's colors.
EXAMPLE_SCENARIOS = {
    "fastest": ("Fastest route", "#42A5F5", "fastest-route"),
    "weather-aware": ("Weather-aware route", "#00838F", "weighted-route"),
}
#: Each Compare Scenarios chart's metric, in the dataflow's order.
EXAMPLE_CHARTS = ["duration", "distance", "rain_exposure", "wind_exposure"]


def _template() -> dict:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    (template,) = manifest["templates"]
    return template


def _source() -> str:
    return (PACKAGE / _template()["source"]).read_text(encoding="utf-8")


def _reference() -> dict:
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def _data_file(dataset_id: str) -> Path:
    root = REPO / "datasets" / f"{dataset_id}@1"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return root / manifest["dataFile"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _weather_file(name: str) -> Path:
    """The file of WRF variable *name* in the weather bundle."""
    return REPO / "datasets" / f"{WEATHER_ID}@1" / "data" / f"{name}.nc"


def _weather() -> dict:
    return {name: str(_weather_file(name)) for name in WEATHER_VARIABLES}


def _gnn_file() -> Path:
    manifest = json.loads((GNN_DIR / "manifest.json").read_text(encoding="utf-8"))
    return GNN_DIR / manifest["entry"]


def _model():
    """The weather GNN as the node gets it: what ``curio_load_model`` returns
    for ``model.scout.weather-gnn``."""
    from utk_curio.sandbox.util.catalog_helpers import CurioModel

    return CurioModel(GNN_ID, str(GNN_DIR))


def _scout_graph():
    """SCOUT's graph cut, rebuilt from its two tables as SCOUT's run rebuilt it:
    the nodes in row order, then the edges in row order."""
    import networkx as nx
    import pyarrow.parquet as pq

    nodes = pq.read_table(FIXTURES / "roads_nodes.parquet")
    edges = pq.read_table(FIXTURES / "roads_edges.parquet")
    G = nx.MultiDiGraph(crs=nodes.schema.metadata[b"crs"].decode())
    ids, xs, ys = (nodes.column(c).to_pylist() for c in ("osmid", "x", "y"))
    G.add_nodes_from((n, {"x": x, "y": y}) for n, x, y in zip(ids, xs, ys))
    columns = [edges.column(c).to_pylist() for c in ("u", "v", "key", "length", "speed_kph", "travel_time")]
    for u, v, key, length, speed, travel in zip(*columns):
        G.add_edge(u, v, key=key, length=length, speed_kph=speed, travel_time=travel)
    return G


def _digest(items) -> str:
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()


@contextlib.contextmanager
def scout_routing(tmp_path):
    """The package's modules, importable the way a run of its node imports
    them: staged into a folder of the run's own."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run"
    run.mkdir()
    staged = stage_package_modules({"root": str(SOURCES), "names": [MODULE]}, str(run))
    assert staged == {"root": "package_modules", "names": [MODULE]}, staged
    with importable(str(run / staged["root"]), staged["names"]):
        yield SimpleNamespace(
            routing=importlib.import_module(f"{MODULE}.weather_routing"),
            weights=importlib.import_module(f"{MODULE}.weight_calculation"),
            roads=importlib.import_module(f"{MODULE}.road_graph"),
        )


def _plan(routing, reference, case, graph=None):
    """The port's routing for one of SCOUT's recorded calls, from the weather
    step SCOUT read."""
    call = case["call"]
    return routing.plan_weather_route(
        graph if graph is not None else _scout_graph(), reference["routing_box"], _weather(), _model(),
        call["origin_"], call["destination_"], mode=call["mode"], K=call["K"],
        time_index=case["time_index"], minutes_into_step=0, rain=call["rain"], wind=call["wind"],
    )


# ---------------------------------------------------------------------------
# The proof
# ---------------------------------------------------------------------------

def test_the_reference_is_scouts_own_run_on_the_committed_data():
    """``routing_reference.json`` was written by SCOUT's code at SCOUT's commit,
    in SCOUT's stack, from exactly the files this checkout holds."""
    reference = _reference()
    assert reference["scout_commit"] == SCOUT_COMMIT
    made = reference["made_with"]
    assert (made["torch"], made["torch_geometric"], made["osmnx"], made["networkx"], made["numpy"]) == (
        "2.2.2", "2.6.1", "2.0.6", "3.2.1", "1.23.5")
    assert made["python"].startswith("3.9.")
    assert reference["datasets"] == {f"{WEATHER_ID}/{n}.nc": _sha256(_weather_file(n)) for n in WEATHER_VARIABLES}
    assert reference["road_graph"] == {n: _sha256(FIXTURES / n) for n in ("roads_nodes.parquet", "roads_edges.parquet")}
    assert sorted(reference["cases"]) == sorted(CASES)
    default = reference["cases"]["default"][0]
    assert (default["orig_node"], default["dest_node"]) == (11270582174, 7161112104)
    assert (default["graph"]["nodes"], default["graph"]["edges"]) == (23084, 25574)
    assert reference["routing_box"] == [-87.66415405273438, 41.85790252685547, -87.61231994628906, 41.899658203125]


def test_each_of_scouts_routes_is_the_only_answer_to_its_search():
    """Identical routes are not luck: in SCOUT's run each route is the only
    shortest path for the weight it minimizes, or the K shortest paths' weights
    strictly increase, so a search that visits ties in another order cannot pick
    another route."""
    for name, calls in _reference()["cases"].items():
        for case in calls:
            for route in case["routes"]:
                checks = route["checks"]
                if "only_shortest_path" in checks:
                    assert checks["only_shortest_path"], (name, route["weight_type"])
                else:
                    assert checks["k_order_strict"] and checks["matches_k_shortest"], (name, route["weight_type"])


@pytest.mark.parametrize("name", CASES)
def test_the_port_routes_as_scout_did(tmp_path, name):
    import numpy as np

    reference = _reference()
    paths = reference["paths"]
    with scout_routing(tmp_path) as m:
        for case in reference["cases"][name]:
            plan = _plan(m.routing, reference, case)
            G = plan["graph"]
            # The graph SCOUT routed on, in SCOUT's order.
            assert (G.number_of_nodes(), G.number_of_edges()) == (case["graph"]["nodes"], case["graph"]["edges"])
            assert _digest([int(n) for n in G.nodes]) == case["graph"]["node_order_sha256"]
            assert _digest([[int(u), int(v), int(k)] for u, v, k in G.edges(keys=True)]) == case["graph"]["edge_order_sha256"]
            assert (plan["orig_node"], plan["dest_node"]) == (case["orig_node"], case["dest_node"])
            assert plan["trip_time_seconds"] == case["trip_time_seconds"]
            # The GNN's input, bit for bit, and its output, as ONNX gives it.
            gnn = plan["gnn"]
            assert hashlib.sha256(gnn["x"].tobytes()).hexdigest() == case["gnn"]["x_sha256"]
            assert hashlib.sha256(gnn["edge_index"].tobytes()).hexdigest() == case["gnn"]["edge_index_sha256"]
            assert gnn["x"].shape == (case["gnn"]["nodes"], 7) and gnn["edge_index"].shape == (2, case["gnn"]["edges"])
            assert gnn["prediction"].astype(np.float64).mean(axis=0).tolist() == pytest.approx(
                case["gnn"]["prediction_mean"], abs=1e-5)
            # The routes, node for node, and their metrics.
            assert [(r["weight_type"], r["route_index"]) for r in plan["routes"]] == [
                (r["weight_type"], r["route_index"]) for r in case["routes"]]
            assert [[int(n) for n in r["route"]] for r in plan["routes"]] == [paths[r["path"]] for r in case["routes"]]
            for ours, theirs in zip(plan["routes"], case["routes"]):
                for metric in METRICS:
                    assert abs(float(ours[metric]) - theirs[metric]) <= TOLERANCE, (name, theirs["weight_type"], metric)
            routes, metrics = m.routing.route_tables(plan)
            assert list(routes["distance_m"]) == pytest.approx([r["length_m"] for r in case["routes"]], abs=1e-6)
            assert list(routes["distance_m"]) == pytest.approx([1000 * r["distance"] for r in case["routes"]], rel=1e-12)
            assert list(metrics["route"]) == [r["weight_type"] for r in case["routes"]]


# ---------------------------------------------------------------------------
# SCOUT's bugs, fixed
# ---------------------------------------------------------------------------

def test_distance_m_is_metres_where_scout_wrote_kilometres(tmp_path):
    """SCOUT's route GeoJSON named the length ``distance_m`` and wrote kilometres
    there (its run's own files); the port's ``distance_m`` is metres."""
    reference = _reference()
    recorded = reference["scout_bugs"]["distance_m_holds_kilometres"]["routes"]
    assert recorded and all(r["scout_distance_m"] == r["distance"] for r in recorded)
    assert all(r["length_m"] == pytest.approx(1000 * r["scout_distance_m"], rel=1e-12) for r in recorded)
    with scout_routing(tmp_path) as m:
        routes, metrics = m.routing.route_tables(_plan(m.routing, reference, reference["cases"]["default"][0]))
    assert list(routes["distance_m"]) == pytest.approx([r["length_m"] for r in recorded], abs=1e-6)
    assert list(routes["distance_m"]) == pytest.approx([1000 * r["scout_distance_m"] for r in recorded], rel=1e-12)
    # The table keeps SCOUT's own kilometres, under SCOUT's name for them.
    assert list(metrics["distance"]) == pytest.approx([r["distance"] for r in recorded], abs=TOLERANCE)


def test_each_call_reads_its_own_start_time(tmp_path):
    """SCOUT kept one DataLoader per process with the first time it was given:
    its run asked for steps 1 and then 17 and the loader stayed at 1. The port
    keeps nothing between calls: two calls in one process read their own steps,
    each as a fresh process does."""
    reference = _reference()
    recorded = reference["scout_bugs"]["loader_keeps_first_time"]
    assert (recorded["asked"], recorded["loader_kept"]) == ([1, 17], [1, 1])
    first, second = reference["cases"]["loader-time"]
    fresh = {1: reference["cases"]["default"][0], 17: reference["cases"]["default-later"][0]}
    with scout_routing(tmp_path) as m:
        assert not hasattr(m.routing, "get_data_loader")
        graph = _scout_graph()
        for case in (first, second):
            plan = _plan(m.routing, reference, case, graph=graph)
            assert plan["time_index"] == case["time_index"]
            assert hashlib.sha256(plan["gnn"]["x"].tobytes()).hexdigest() == fresh[case["time_index"]]["gnn"]["x_sha256"]
    assert fresh[1]["gnn"]["x_sha256"] != fresh[17]["gnn"]["x_sha256"]


@pytest.mark.parametrize("name, count", [("custom-k1", 3), ("custom-k2", 5), ("custom-k3", 7), ("single-factor", 3)])
def test_every_route_is_a_row_where_scout_ran_past_its_output_names(tmp_path, name, count):
    """SCOUT named each route's metrics file after its list of output names, two
    in its example, and raised IndexError at the third route; the port returns
    every route as a row."""
    reference = _reference()
    (case,) = reference["cases"][name]
    assert case["call"]["outputs"] == ["C", "D"]
    assert case["error"]["type"] == "IndexError" and case["error"]["where"] == "weather_routing.py:371"
    assert len(case["routes"]) == count
    with scout_routing(tmp_path) as m:
        routes, metrics = m.routing.route_tables(_plan(m.routing, reference, case))
    assert len(routes) == len(metrics) == count
    assert list(zip(metrics["route"], metrics["route_index"])) == [
        (r["weight_type"], r["route_index"]) for r in case["routes"]]


def _hours_in_history(path: Path) -> list[str]:
    import netCDF4

    with netCDF4.Dataset(path) as ds:
        history = ds.getncattr("history")
    return sorted(set(re.findall(r"_d01_(\d{4}-\d\d-\d\d_\d\d:\d\d:\d\d)\.nc", history)))


def test_a_start_time_reads_the_hourly_step_it_falls_in(tmp_path):
    """The WRF files hold one step an hour from their START_DATE (the inputs
    their history lists), while SCOUT counted 15-minute steps from 2025-07-06
    00:00 plus 1: its 00:00 read step 1 (01:00 UTC) and its 04:00 step 17 (17:00
    UTC). The port reads a start time as local time in the files' time zone and
    takes the hourly step it falls in."""
    from datetime import datetime, timedelta

    import netCDF4

    steps = _reference()["scout_bugs"]["time_read_as_quarter_hours"]["scout_steps"]
    assert steps["default"] == [1] and steps["default-later"] == [17]
    rain = _weather_file("RAIN")
    with netCDF4.Dataset(rain) as ds:
        start, zone, count = ds.getncattr("START_DATE"), ds.getncattr("timezone"), len(ds.dimensions["Time"])
    first = datetime.strptime(start, "%Y-%m-%d_%H:%M:%S")
    assert (start, zone, count) == ("2025-07-06_00:00:00", "America/Chicago", 49)
    assert _hours_in_history(rain) == [(first + timedelta(hours=h)).strftime("%Y-%m-%d_%H:%M:%S") for h in range(count)]
    with scout_routing(tmp_path) as m:
        index = m.routing.weather_time_index
        assert index("2025-07-06T00:00:00", start, "UTC", count) == (0, 0)
        assert index("2025-07-06T04:00:00", start, "UTC", count) == (4, 0)
        # Noon in Chicago (CDT) is 17:00 UTC, the step SCOUT read for its 04:00.
        assert index("2025-07-06T12:00:00", start, zone, count) == (17, 0)
        assert index("2025-07-06T12:40:00", start, zone, count) == (17, 40)
        assert index("2025-07-05T19:00:00", start, zone, count) == (0, 0)
        with pytest.raises(ValueError, match="outside the weather data, which runs from 2025-07-05T19:00:00 to "
                                             "2025-07-07T19:00:00 there"):
            index("2025-07-05T18:59:00", start, zone, count)


class _Grid:
    """A stand-in for a NetCDF file: one row of five cells, each step's cells
    holding the step's number."""

    def __init__(self, steps=30):
        import numpy as np

        values = np.repeat(np.arange(steps, dtype=np.float32)[:, None, None], 5, axis=2)
        self.variables = {
            "RAIN": values,
            "XLAT": np.zeros((1, 5), dtype=np.float32),
            "XLONG": np.arange(5, dtype=np.float32)[None, :],
        }


def _zoned_graph():
    """Five zones of a trip, zone z + 1 over cell z only."""
    import networkx as nx

    G = nx.MultiDiGraph()
    for zone in range(1, 6):
        x = zone - 1
        G.add_node(f"a{zone}", x=x - 0.1, y=-0.1)
        G.add_node(f"b{zone}", x=x + 0.1, y=0.1)
        G.add_edge(f"a{zone}", f"b{zone}", zone=zone)
    return G


@pytest.mark.parametrize("into, steps", [(0, [10, 10, 10, 10, 11]), (30, [10, 10, 11, 11, 11])])
def test_each_15_minute_zone_reads_the_hour_it_starts_in(tmp_path, into, steps):
    """SCOUT gave zone t + 1 of a trip step ``start + t``, a step a quarter of an
    hour; the port gives it the hourly step the trip is in when the zone starts."""
    with scout_routing(tmp_path) as m:
        stitched = m.weights.stitchDataset(
            _zoned_graph(), _Grid(), trip_time_seconds=[900.0 * (t + 1) for t in range(5)],
            variable_name="RAIN", starting_time=10, minutes_into_step=into)
    assert stitched[0].tolist() == steps
    assert steps != [10, 11, 12, 13, 14]  # what SCOUT's stitching gave


def test_an_origin_north_of_the_roads_is_refused(tmp_path):
    """SCOUT checked an origin's longitude against the roads' northern edge
    (``origin[1] > ymax``), which a longitude never exceeds in Chicago, so an
    origin north of the roads passed. The port checks each point's latitude and
    longitude against the roads' bounds."""
    reference = _reference()
    xmin, ymin, xmax, ymax = reference["routing_box"]
    north = (ymax + 0.01, (xmin + xmax) / 2)
    destination = reference["cases"]["default"][0]["call"]["destination_"]
    # SCOUT's condition, as it reads (weather_routing.py, b98369e5, lines 117 to 120).
    origin = north
    dest = (destination["lat"], destination["lon"])
    scout_refuses = (origin[0] < ymin or origin[1] > ymax or origin[1] < xmin or origin[1] > xmax
                     or dest[0] < ymin or dest[0] > ymax or dest[1] < xmin or dest[1] > xmax)
    assert scout_refuses is False
    case = copy.deepcopy(reference["cases"]["default"][0])
    case["call"]["origin_"] = {"lat": north[0], "lon": north[1]}
    with scout_routing(tmp_path) as m:
        with pytest.raises(ValueError, match=r"The origin \(41\.90965[0-9]*, -87\.638[0-9]*\) is outside the roads"):
            _plan(m.routing, reference, case)
        case["call"]["origin_"] = reference["cases"]["default"][0]["call"]["origin_"]
        case["call"]["destination_"] = {"lat": (ymin + ymax) / 2, "lon": xmax + 0.01}
        with pytest.raises(ValueError, match="The destination .* is outside the roads"):
            _plan(m.routing, reference, case)


# ---------------------------------------------------------------------------
# The road graph from a Curio roads layer
# ---------------------------------------------------------------------------

def _layer(rows, crs="EPSG:4326"):
    import geopandas as gpd
    from shapely.geometry import LineString

    return gpd.GeoDataFrame(
        [{k: v for k, v in row.items() if k != "line"} for row in rows],
        geometry=[LineString(row["line"]) for row in rows], crs=crs,
    )


def test_a_line_is_cut_at_every_point_and_shared_points_are_one_node(tmp_path):
    a, b, c, d = (-87.63, 41.88), (-87.629, 41.88), (-87.628, 41.88), (-87.629, 41.881)
    roads = _layer([
        {"line": [a, b, c], "highway": "secondary", "maxspeed": "30 mph"},
        {"line": [b, d], "highway": "residential"},
    ])
    with scout_routing(tmp_path) as m:
        G, bounds = m.roads.road_graph(roads)
    points = sorted((data["x"], data["y"]) for _, data in G.nodes(data=True))
    assert points == sorted([a, b, c, d])
    assert G.number_of_edges() == 6  # three segments, both ways
    assert bounds == pytest.approx((-87.63, 41.88, -87.628, 41.881))
    speeds = {data["highway"]: data["speed_kph"] for _, _, data in G.edges(data=True)}
    assert speeds["secondary"] == pytest.approx(48.28, abs=0.01)  # 30 mph
    for _, _, data in G.edges(data=True):
        assert data["travel_time"] == pytest.approx(data["length"] / (data["speed_kph"] / 3.6), abs=0.05)


@pytest.mark.parametrize("oneway, along, against", [("yes", True, False), ("-1", False, True), ("no", True, True), (None, True, True)])
def test_oneway_keeps_a_road_to_its_direction(tmp_path, oneway, along, against):
    a, b = (-87.63, 41.88), (-87.629, 41.88)
    # A two-way road beside it keeps both ends reachable, as the largest
    # strongly connected part needs.
    roads = _layer([{"line": [a, b], "highway": "secondary", "oneway": oneway},
                    {"line": [a, (-87.6295, 41.8805), b], "highway": "residential"}])
    with scout_routing(tmp_path) as m:
        G, _bounds = m.roads.road_graph(roads)
    ids = {(data["x"], data["y"]): n for n, data in G.nodes(data=True)}
    direct = {(u, v) for u, v, data in G.edges(data=True) if data["highway"] == "secondary"}
    assert ((ids[a], ids[b]) in direct, (ids[b], ids[a]) in direct) == (along, against)


def test_a_layer_without_a_crs_is_read_as_autark_reads_it(tmp_path):
    """An Autark node hands a Python node its layer with no CRS, in EPSG:3395
    metres; a layer in degrees with no CRS is read as EPSG:4326, and one with a
    projected CRS is moved to it."""
    a, b = (-87.63, 41.88), (-87.629, 41.88)
    lonlat = _layer([{"line": [a, b], "highway": "secondary"}])
    with scout_routing(tmp_path) as m:
        expected = m.roads.road_graph(lonlat)[1]
        mercator = lonlat.to_crs(3395)
        for layer in (mercator, mercator.set_crs(None, allow_override=True), lonlat.set_crs(None, allow_override=True)):
            assert m.roads.road_graph(layer)[1] == pytest.approx(expected, abs=1e-9)


def test_the_graph_keeps_its_largest_strongly_connected_part(tmp_path):
    a, b, c = (-87.63, 41.88), (-87.629, 41.88), (-87.628, 41.88)
    island = [(-87.60, 41.90), (-87.599, 41.90)]
    roads = _layer([
        {"line": [a, b, c], "highway": "secondary"},
        {"line": [c, (-87.627, 41.88)], "highway": "secondary", "oneway": "yes"},  # a dead end
        {"line": island, "highway": "residential"},
    ])
    with scout_routing(tmp_path) as m:
        G, bounds = m.roads.road_graph(roads)
    assert sorted((data["x"], data["y"]) for _, data in G.nodes(data=True)) == sorted([a, b, c])
    # The routes still run inside the bounds of the whole layer, as SCOUT's do.
    assert bounds == pytest.approx((-87.63, 41.88, -87.599, 41.90))


def test_an_empty_layer_says_why(tmp_path):
    with scout_routing(tmp_path) as m:
        with pytest.raises(ValueError, match="The roads layer is empty"):
            m.roads.road_graph(_layer([]))


# ---------------------------------------------------------------------------
# The template and the datasets
# ---------------------------------------------------------------------------

def test_the_template_declares_the_widgets_its_source_reads():
    template = _template()
    assert template["hasWidgets"] is True
    assert {w["name"]: w["default"] for w in template["widgets"]} == {
        "origin": {"lat": 41.868, "lon": -87.636}, "destination": {"lat": 41.889, "lon": -87.624},
        "mode": "Default weights", "K": 1, "time": "2025-07-06T12:00:00", "rain": 0.85834, "wind": 0.01657,
    }
    mode = next(w for w in template["widgets"] if w["name"] == "mode")
    assert mode["options"] == {"choices": ["Default weights", "Custom weights", "Single-factor weights"],
                               "display": "dropdown"}
    assert re.findall(r"\[!!\s*(\w+)\s*!!\]", _source()) == ["origin", "destination", "mode", "K", "time", "rain", "wind"]


def test_the_template_reads_the_wrf_forecast_and_the_gnn_by_id():
    """The weather is the Data Catalog's WRF forecast, one bundle of a NetCDF
    file per variable, each file's path read by the dataset's id and the
    file's name (``curio_data_path(id, part=...)``); the GNN is a Model Catalog
    model, named by a literal ``curio_load_model`` call."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code, model_ids_in_code
    from utk_curio.backend.app.model_catalog.domain.manifest import load_manifest

    assert dataset_ids_in_code(_source()) == [WEATHER_ID]
    assert model_ids_in_code(_source()) == [GNN_ID]
    for name in WEATHER_VARIABLES:
        assert f'"{name}": curio_data_path("{WEATHER_ID}", part="{name}.nc"),' in _source()
    root = REPO / "datasets" / f"{WEATHER_ID}@1"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["format"], manifest["dataFile"]) == ("bundle", "data/bundle.json")
    assert (manifest["publisher"], manifest["license"]) == ("SCOUT (urban-toolkit/scout)", "")
    assert "used with the permission of SCOUT's authors" in manifest["description"]
    parts = json.loads((root / "data" / "bundle.json").read_text(encoding="utf-8"))["parts"]
    assert sorted((p["file"], p["format"]) for p in parts) == sorted(
        (f"data/{n}.nc", "netcdf") for n in WEATHER_VARIABLES)
    gnn = load_manifest(GNN_DIR)
    assert (gnn.runtime, gnn.task, gnn.labels, gnn.input) == ("onnx", "node-regression", (), None)
    assert gnn.publisher == "SCOUT (urban-toolkit/scout)"
    assert "SCOUT's authors" in gnn.license
    assert not (REPO / "datasets" / "data.scout.weather-gnn@1").exists()


def test_the_gnn_takes_any_road_graph():
    """The ONNX model's node and edge counts are free: x is nodes by 7 float32,
    edge_index 2 by edges int64, prediction nodes by 5."""
    import onnxruntime as ort

    session = ort.InferenceSession(str(_gnn_file()), providers=["CPUExecutionProvider"])
    shapes = {i.name: (i.type, i.shape) for i in session.get_inputs()}
    assert [i.name for i in session.get_inputs()] == ["x", "edge_index"]
    assert shapes["x"][0] == "tensor(float)" and shapes["x"][1][1] == 7 and isinstance(shapes["x"][1][0], str)
    assert shapes["edge_index"][0] == "tensor(int64)" and shapes["edge_index"][1][0] == 2
    assert isinstance(shapes["edge_index"][1][1], str)
    (output,) = session.get_outputs()
    assert output.name == "prediction" and output.shape[1] == 5
    assert _sha256(_gnn_file()).startswith("602fe4a5")


def test_the_package_declares_the_libraries_it_imports():
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["license"], manifest["publisher"]) == ("MIT", "Curio")
    assert sorted(manifest["dependencies"]["python"]) == [
        "netCDF4", "networkx", "onnxruntime", "osmnx", "scikit-learn", "scipy"]
    imported = set()
    for path in (SOURCES / MODULE).glob("*.py"):
        imported |= set(re.findall(r"^(?:import|from) (\w+)", path.read_text(encoding="utf-8"), re.MULTILINE))
    assert {"netCDF4", "networkx", "osmnx", "scipy"} <= imported
    # No torch: the GNN runs as ONNX.
    assert not imported & {"torch", "torch_geometric"}


# ---------------------------------------------------------------------------
# The shipped example
# ---------------------------------------------------------------------------

def _dataflow() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]


def test_the_shipped_dataflow_runs_scouts_example():
    """``WeatherRouting.json`` is SCOUT's weather routing example and how its CI
    run reaches this package: one Weather Routing node holding the template's
    source and widgets, set as SCOUT's example sets them, whose code resolves
    with nothing left over. Two scenarios share it, each keeping one of its
    routes, the fastest (SCOUT's C) or the weather-aware one (D): a node with
    the route as a band the map outlines, and one with its metrics. The second
    scenario's nodes are copies of the first's, one line apart."""
    from utk_curio.backend.app.execution.code_references import resolve_references

    spec = _dataflow()
    assert spec["packages"] == ["scout.routing@1"]
    assert sorted(ref["datasetId"] for ref in spec["datasets"]) == sorted([ROADS_ID, WEATHER_ID])
    nodes = {n["id"]: n for n in spec["nodes"]}
    (routing,) = [n for n in spec["nodes"] if n["type"] == NODE_TYPE]
    assert routing["content"] == _source()
    widgets = routing["metadata"]["widgets"]
    assert [{k: v for k, v in w.items() if k != "value"} for w in widgets] == _template()["widgets"]
    assert {w["name"]: w["value"] for w in widgets} == EXAMPLE_VALUES
    scout = _reference()["example"]["arguments"]
    assert EXAMPLE_VALUES == {
        "origin": scout["origin_"], "destination": scout["destination_"], "mode": scout["mode"],
        "K": scout["K"], "time": scout["time_"], "rain": scout["rain"], "wind": scout["wind"]}
    code, problems = resolve_references(routing["content"], widgets, "python", inputs=[{"slot": 0}])
    assert problems == [], problems
    assert 'time_="2025-07-06T00:00:00"' in code and 'mode="Default weights"' in code
    assert [(s["id"], s["name"], s["color"]) for s in spec["scenarios"]] == [
        (sid, name, color) for sid, (name, color, _route) in EXAMPLE_SCENARIOS.items()]
    for scenario in spec["scenarios"]:
        assert routing["id"] not in scenario["nodes"]
        parts = [nodes[i] for i in scenario["nodes"]]
        assert all(n["type"] == PYTHON_TYPE for n in parts) and len(parts) == 2
        assert all([e["source"] for e in spec["edges"] if e["target"] == n["id"]] == [routing["id"]] for n in parts)
        route = EXAMPLE_SCENARIOS[scenario["id"]][2]
        assert all(f'== "{route}"' in n["content"] for n in parts), [n["content"] for n in parts]
    (fastest, weather_aware) = spec["scenarios"]
    copies = {nodes[i]["metadata"]["copiedFrom"][-1] for i in weather_aware["nodes"]}
    assert copies == set(fastest["nodes"])


def test_the_shipped_dataflows_compare_nodes_chart_the_four_metrics():
    """As in SCOUT's example, the two routes are compared on four bar charts,
    one per metric: each a Compare Scenarios node holding the code it writes
    for its two inputs (``utils/compare/compareCode.ts``), the fastest route in
    circle 0 and the weather-aware one in circle 1, one bar per scenario."""
    spec = _dataflow()
    entries = ('    ("fastest", "Fastest route", [!! input_0 !!]),\n'
               '    ("weather-aware", "Weather-aware route", [!! input_1 !!]),\n])\n')
    compares = [n for n in spec["nodes"] if n["type"] == "curio.builtin/compare-scenarios"]
    labels = [{"scenario": sid, "name": name, "color": color} for sid, (name, color, _r) in EXAMPLE_SCENARIOS.items()]
    scenario_of = {i: s["id"] for s in spec["scenarios"] for i in s["nodes"]}
    charted = []
    for node in compares:
        settings = node["metadata"]["compareScenarios"]
        assert settings["inputs"] == labels and settings["mode"] == "chart"
        assert node["content"].endswith(f"return curio_stack_scenarios([\n{entries}"), node["content"]
        assert settings["chart"]["preset"] == "bar"
        charted.append(settings["chart"]["y"])
        sources = {e["targetHandle"]: e["source"] for e in spec["edges"] if e["target"] == node["id"]}
        assert {handle: scenario_of[s] for handle, s in sources.items()} == {"in": "fastest", "in_1": "weather-aware"}
        assert all("input_0[1]" in _node(spec, s)["content"] for s in sources.values())
    assert charted == EXAMPLE_CHARTS


def _node(spec, node_id):
    return next(n for n in spec["nodes"] if n["id"] == node_id)


def test_the_shipped_dataflows_roads_come_from_the_catalog_and_autark_maps_them():
    """A Data Loading node loads the roads of SCOUT's routing area from the
    Data Catalog, marked as roads for Autark, and the dataflow declares the
    dataset. The Weather Routing node takes them straight on its one input, and
    its layer chip reads them as the roads layer: no node in between.
    The map draws each scenario's route in its color, SCOUT's, with a darker
    outline, and its legend names the scenarios (Curio's ``scenario`` key)."""
    spec = _dataflow()
    nodes = {n["id"]: n for n in spec["nodes"]}
    autark = {n["id"]: json.loads(n["content"]) for n in spec["nodes"] if n["type"] == "curio.builtin/autk-grammar"}
    (map_id,) = autark
    assert list(autark[map_id]) == ["map"]
    (loader,) = [n for n in spec["nodes"] if n["type"] == "curio.builtin/data-loading"]
    loader_id = loader["id"]
    assert f'roads = curio_load_data("{ROADS_ID}")\n' in loader["content"]
    assert 'roads.metadata = {"layerType": "roads"}\n' in loader["content"]
    assert ROADS_ID in [ref["datasetId"] for ref in spec["datasets"]]
    (routing,) = [n["id"] for n in spec["nodes"] if n["type"] == NODE_TYPE]
    assert {e["target"] for e in spec["edges"] if e["source"] == loader_id} == {routing, map_id}
    assert [(e["source"], e["targetHandle"]) for e in spec["edges"] if e["target"] == routing] == [(loader_id, "in")]
    assert "    [!! input_0:table_osm_roads !!],\n" in nodes[routing]["content"]
    layers = autark[map_id]["map"]["layerRefs"]
    assert [layer["dataRef"] for layer in layers] == ["[!! input_0 !!]", "[!! input_1 !!]", "[!! input_2 !!]"]
    assert [layer.get("scenario") for layer in layers] == [None, *EXAMPLE_SCENARIOS]
    scenario_of = {i: s["id"] for s in spec["scenarios"] for i in s["nodes"]}
    sources = {e["targetHandle"]: e["source"] for e in spec["edges"] if e["target"] == map_id}
    assert [scenario_of.get(sources[h]) for h in ("in_1", "in_2")] == list(EXAMPLE_SCENARIOS)
    assert all("input_0[0]" in nodes[sources[h]]["content"] for h in ("in_1", "in_2"))
    assert not any("getFnv" in layer or "colorMapInterpolator" in layer for layer in layers)


def test_the_templates_layer_chip_reads_autarks_layer_array():
    """An Autark node with only a data section hands on its layers as an array
    of ``{name, type, geojson}``, each FeatureCollection naming EPSG:3395
    (``autkDataCompile.ts``). The template's layer chip runs as the call that
    picks the roads layer out of it by its table name, as a GeoDataFrame in
    that CRS with the tags routing reads; an input without that layer is
    refused with the layers it has."""
    import geopandas as gpd

    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.input_layers import curio_layer

    loaded = [{"name": "table_osm_parks"}, {"name": "table_osm_roads", "columns": ["highway", "oneway"]}]
    code, problems = resolve_references(_source(), _with_values(), "python", inputs=[{"slot": 0, "layers": loaded}])
    assert problems == [], problems
    assert '    curio_layer(input_0, "table_osm_roads", 0),\n' in code
    _code, problems = resolve_references(_source(), _with_values(), "python",
                                         inputs=[{"slot": 0, "layers": [{"name": "table_osm_buildings"}]}])
    assert problems == [{
        "reference": "[!! input_0:table_osm_roads !!]",
        "message": "[!! input_0:table_osm_roads !!]: input_0 has no layer table_osm_roads. "
                   "Its layers are table_osm_buildings.",
    }]

    feature = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[-9754301.3, 5114043.4], [-9754316.7, 5114043.8]]},
        "properties": {"highway": "secondary", "oneway": "yes", "name": "W Adams St", "lanes": "3"},
    }
    layers = [
        {"name": "table_osm_roads", "type": "roads",
         "geojson": {"type": "FeatureCollection", "features": [feature], "crs": CRS_3395}},
        {"name": "table_osm_parks", "type": "parks",
         "geojson": {"type": "FeatureCollection", "features": [], "crs": CRS_3395}},
    ]
    roads = curio_layer(layers, "table_osm_roads", 0)
    assert isinstance(roads, gpd.GeoDataFrame) and roads.crs.to_epsg() == 3395
    assert list(roads.columns) == ["geometry", "highway", "oneway", "name", "lanes"]
    assert roads.iloc[0]["highway"] == "secondary" and roads.iloc[0]["oneway"] == "yes"
    # The roads the node tests route on are the example's dataset: lines and
    # the tags routing reads, and the street's name.
    roads = gpd.read_parquet(EXAMPLE_ROADS)
    assert roads.crs.to_epsg() == 4326
    assert list(roads.columns) == ["highway", "oneway", "maxspeed", "name", "geometry"]


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


def _example_roads_layers_artifact():
    """The example's roads as an Autark node that loads OpenStreetMap hands
    roads on: its layer array, the roads layer's lines in EPSG:3395 metres under
    their table name, beside another layer, so the node's layer chip has to
    pick the roads by name."""
    import geopandas as gpd

    from utk_curio.sandbox.util.parsers import save_to_duckdb

    roads = gpd.read_parquet(EXAMPLE_ROADS).to_crs(3395)
    lines = json.loads(roads.to_json())
    lines["crs"] = CRS_3395
    layers = [
        {"name": "table_osm_parks", "type": "parks",
         "geojson": {"type": "FeatureCollection", "features": [], "crs": CRS_3395}},
        {"name": "table_osm_roads", "type": "roads", "geojson": lines},
    ]
    return save_to_duckdb(layers, node_id="osm")


def _example_roads_artifact():
    """The example's roads as its Data Loading node hands them on: the
    dataset as ``curio_load_data`` gives it, one GeoDataFrame with no layer
    name, marked as roads for Autark."""
    import geopandas as gpd

    from utk_curio.sandbox.util.parsers import save_to_duckdb

    roads = gpd.read_parquet(EXAMPLE_ROADS)
    roads.metadata = {"layerType": "roads"}
    return save_to_duckdb(roads, node_id="roads")


def run_node(workspace, *, fails=False, layers=False, **values):
    """Run the node's template, its widgets at *values*, on the example's roads
    as its Data Loading node hands them on (with *layers*, as an Autark node's
    layer array) in the sandbox, in process, with the datasets and the model
    its code names resolved: ``(artifact id, (routes, metrics))``, or with
    *fails* the node's error text."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code, model_ids_in_code
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    code, problems = resolve_references(_source(), _with_values(**values), "python", inputs=[{"slot": 0}])
    assert problems == [], problems
    artifact, data_type = (_example_roads_layers_artifact(), "list") if layers else (_example_roads_artifact(), "geodataframe")
    result = _execute(
        code, artifact, NODE_TYPE, data_type, workspace,
        dataset_paths={i: str(_data_file(i)) for i in dataset_ids_in_code(code)},
        models={i: str(REPO / "models" / f"{i}@1") for i in model_ids_in_code(code)},
        package_modules={"root": str(SOURCES), "names": [MODULE]},
    )
    if fails:
        assert result["stderr"], f"the node ran: {result['output']}"
        return result["stderr"]
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "outputs", result["output"]
    return result["output"]["path"], load_from_duckdb(result["output"]["path"])


def _rows(routes, metrics):
    return [(r["route"], int(r["route_index"]), len(line.coords), float(r["distance"]), float(r["duration"]),
             float(r["rain_exposure"]), float(r["wind_exposure"]))
            for (_i, r), line in zip(metrics.iterrows(), routes.geometry)]


def _assert_rows(rows, expected):
    assert [row[:3] for row in rows] == [row[:3] for row in expected]
    for ours, pinned in zip(rows, expected):
        assert ours[3:5] == pytest.approx(pinned[3:5], abs=1e-9), ours
        assert ours[5:] == pytest.approx(pinned[5:], abs=TOLERANCE), ours


def test_the_node_routes_over_autarks_roads_as_the_example_does(workspace):
    _art_id, (routes, metrics) = run_node(workspace, **EXAMPLE_VALUES)
    assert routes.crs.to_epsg() == 4326
    assert list(routes.columns) == ["weight_type", "route_index", "distance_m", "duration_minutes", "rain_exposure",
                                    "heat_exposure", "wind_exposure", "humidity_exposure", "geometry"]
    assert list(metrics.columns) == ["route", "route_index", *METRICS]
    _assert_rows(_rows(routes, metrics), EXAMPLE)
    assert list(routes["distance_m"]) == pytest.approx([1000 * d for d in metrics["distance"]], rel=1e-12)
    # Each route runs from the origin to the destination, inside SCOUT's box.
    for line in routes.geometry:
        assert line.coords[0] == routes.geometry.iloc[-1].coords[0]
        assert line.coords[-1] == routes.geometry.iloc[-1].coords[-1]
    xmin, ymin, xmax, ymax = routes.total_bounds
    assert -87.665 < xmin and xmax < -87.612 and 41.857 < ymin and ymax < 41.90


def test_the_node_routes_over_an_autark_layer_array_too(workspace):
    """The layers an Autark node that loads OpenStreetMap hands on, its roads
    under their table name beside another layer, are read by the template's
    chip too: the same roads in EPSG:3395 give the same routes."""
    _art_id, (routes, metrics) = run_node(workspace, layers=True, **EXAMPLE_VALUES)
    assert routes.crs.to_epsg() == 4326
    _assert_rows(_rows(routes, metrics), EXAMPLE)


def test_the_example_picks_each_part(workspace):
    """The two nodes of each scenario take its route, as a 30 m band, a
    polygon the map outlines, and that route's row of the metrics."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    spec = _dataflow()
    nodes = {n["id"]: n for n in spec["nodes"]}
    art_id, (routes, metrics) = run_node(workspace, **EXAMPLE_VALUES)
    for scenario in spec["scenarios"]:
        pick = EXAMPLE_SCENARIOS[scenario["id"]][2]
        codes = [nodes[i]["content"] for i in scenario["nodes"]]
        (route_code,) = [c for c in codes if "input_0[0]" in c]
        (metrics_code,) = [c for c in codes if "input_0[1]" in c]
        picked = _execute(route_code, art_id, PYTHON_TYPE, "file", workspace)
        assert picked["stderr"] == "", picked["stderr"]
        assert picked["output"]["dataType"] == "geodataframe", picked["output"]
        band = load_from_duckdb(picked["output"]["path"])
        assert list(band["weight_type"]) == [pick]
        assert list(band.geometry.geom_type) == ["Polygon"]
        assert band.geometry.iloc[0].covers(routes[routes["weight_type"] == pick].geometry.iloc[0])
        picked = _execute(metrics_code, art_id, PYTHON_TYPE, "file", workspace)
        assert picked["stderr"] == "" and picked["output"]["dataType"] == "dataframe", picked
        row = load_from_duckdb(picked["output"]["path"])
        assert row.reset_index(drop=True).equals(metrics[metrics["route"] == pick].reset_index(drop=True))


def test_each_widget_reaches_the_call(workspace):
    def run(**values):
        _art_id, (routes, metrics) = run_node(workspace, **values)
        return _rows(routes, metrics), routes.geometry.iloc[-1].coords[0]

    default, start = run()
    assert [row[:2] for row in default] == [("fastest-route", 0), ("weighted-route", 1)]
    assert [row[:2] for row in run(mode="Single-factor weights")[0]] == [
        ("rain-aware-route", 1), ("wind-aware-route", 2), ("fastest-route", 0)]
    assert [row[:2] for row in run(mode="Custom weights", K=2)[0]] == [
        ("rain-aware-route", 0), ("rain-aware-route", 1), ("wind-aware-route", 0), ("wind-aware-route", 1),
        ("fastest-route", 0)]
    # Midnight in Chicago reads another hour of the weather: the same routes,
    # other exposures.
    midnight, _start = run(time="2025-07-06T00:00:00")
    assert [row[:3] for row in midnight] == [row[:3] for row in default]
    assert [row[3:5] for row in midnight] == [row[3:5] for row in default]
    assert abs(midnight[0][5] - default[0][5]) > 1.0
    # Another origin: the routes start elsewhere.
    _moved, moved_start = run(origin={"lat": 41.875, "lon": -87.630})
    assert moved_start != start


@pytest.mark.parametrize(
    "values, sentence",
    [
        ({"origin": {"lat": 41.95, "lon": -87.62}}, "The origin (41.95, -87.62) is outside the roads"),
        ({"time": "2025-07-08T12:00:00"}, "is outside the weather data, which runs from 2025-07-05T19:00:00"),
        ({"mode": "Custom weights", "rain": 0.6, "wind": 0.6}, "the weather weights must add up to at most 1.0"),
        ({"mode": "Fastest"}, "There is no route mode 'Fastest'"),
    ],
)
def test_a_setting_the_node_cannot_use_says_why(workspace, values, sentence):
    error = run_node(workspace, fails=True, **values)
    assert sentence in error, error
