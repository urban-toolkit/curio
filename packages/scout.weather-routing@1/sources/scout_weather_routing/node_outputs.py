"""The Weather-Aware Routes node's four outputs, made with the port of
SCOUT's routing (``weather_routing``). Curio's own code, beside the port.

The node's input is the roads of the area to route in (SCOUT's data layer,
its ``roi`` cut with ``.cx``). Its code reads the road network from the Data
Catalog's ``data.osm.chicago-roads``, and SCOUT's five WRF NetCDF files of
6 July 2025 from ``data.scout.chicago-weather-2025-07-06``, one file each (``part=``).
As SCOUT does, the graph is the network's nodes inside the area's bounds and
the edges between them.

- **routes**: one row per route, a LineString through its nodes, with its
  ``route`` label, SCOUT's ``weight_type`` and ``route_index``,
  ``distance_km``, ``duration_min`` and the exposure to each condition.
- **endpoints**: the origin and destination, at the road nodes they snap to.
- **ribbons**: each route as a band *width* metres wide, for a map: Autark
  draws a line at a fixed width its document cannot change, and a band at the
  width it has on the ground.
- **metrics**: the routes' measures as long rows (``route``, ``metric``,
  ``value``), for a chart that compares them, as SCOUT's comparison nodes do.
"""

from datetime import datetime

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

from .weather_routing import (
    CONDITIONS,
    MODES,
    GNN_weight_calculations,
    calculate_isochrones,
    calculate_routes,
    nearest_node,
    time_to_global_index,
    weights_for,
)

ROAD_COLUMNS = ("u", "v", "key", "length", "speed_kph", "travel_time")
#: SCOUT's weather files, one variable each.
VARIABLES = ("RAIN", "T2", "WSPD10", "WDIR10", "RH2")
METRICS = (
    ("duration", "Travel time (minutes)"),
    ("distance", "Distance (km)"),
    ("rain_exposure", "Rain exposure"),
    ("wind_exposure", "Wind exposure"),
    ("heat_exposure", "Heat exposure"),
    ("humidity_exposure", "Humidity exposure"),
)


def routing_inputs(arg, roads, weather):
    """The area's roads from *arg*, and *roads* and *weather*, checked."""
    area = arg[0] if isinstance(arg, (tuple, list)) and len(arg) == 1 else arg
    if not isinstance(area, pd.DataFrame) or "geometry" not in area.columns:
        raise ValueError(
            "Weather-Aware Routes reads the roads of the area to route in: connect the Data Loading "
            "node that cuts them from data.scout.chicago-weather-2025-07-06."
        )
    if area.empty:
        raise ValueError("No road reaches into the area; widen its box.")
    missing = [c for c in ROAD_COLUMNS + ("geometry",) if c not in roads.columns]
    if missing:
        raise ValueError(f"The road network has no column {', '.join(missing)}.")
    absent = [v for v in VARIABLES if v not in weather or v not in weather[v]]
    if absent:
        raise ValueError(f"The weather has no {', '.join(absent)}; read SCOUT's {', '.join(VARIABLES)} files.")
    return area


def road_network(roads):
    """SCOUT's MultiDiGraph from its edges table, in the table's order: each
    node at the end of its edges' geometries, each edge with its key,
    ``length``, ``speed_kph`` and ``travel_time``."""
    G = nx.MultiDiGraph(crs="EPSG:4326")
    coords = {}
    for u, v, geometry in zip(roads["u"], roads["v"], roads.geometry):
        line = geometry.coords
        coords.setdefault(int(u), line[0])
        coords.setdefault(int(v), line[-1])
    # Nodes in the order their first edge leaves them, so the graph lists its
    # edges in the table's order, SCOUT's.
    for node in dict.fromkeys(int(u) for u in roads["u"]):
        G.add_node(node, x=coords[node][0], y=coords[node][1])
    for node, (x, y) in coords.items():
        if node not in G:
            G.add_node(node, x=x, y=y)
    for u, v, key, length, speed, travel in zip(roads["u"], roads["v"], roads["key"], roads["length"],
                                                roads["speed_kph"], roads["travel_time"]):
        G.add_edge(int(u), int(v), key=int(key), length=float(length), speed_kph=float(speed),
                   travel_time=float(travel))
    return G


def crop(G, bounds):
    """SCOUT's ``load_graph`` crop: the nodes inside *bounds* (west, south,
    east, north) and the edges between them."""
    xmin, ymin, xmax, ymax = bounds
    inside = [n for n, d in G.nodes(data=True) if ymin <= d["y"] <= ymax and xmin <= d["x"] <= xmax]
    return G.subgraph(inside).copy()


def weather_grids(weather):
    """``(grids, lats, lons, start)`` from SCOUT's WRF files, *weather*
    ``{variable: xarray Dataset}``: each variable as a ``(steps, rows, cols)``
    array, the cells' latitudes and longitudes (the same at every step), and
    the run's first time."""
    grids = {v: np.asarray(weather[v][v].values, dtype=np.float32) for v in VARIABLES}
    rain = weather["RAIN"]
    lats, lons = np.asarray(rain["XLAT"].values)[0], np.asarray(rain["XLONG"].values)[0]
    start = datetime.strptime(rain.attrs["START_DATE"], "%Y-%m-%d_%H:%M:%S")
    return grids, lats, lons, start


def location(value, name):
    if not isinstance(value, dict) or "lat" not in value or "lon" not in value:
        raise ValueError(f"The {name} is a location, {{'lat': ..., 'lon': ...}}.")
    return float(value["lat"]), float(value["lon"])


def route_label(record, records):
    same = [r for r in records if r["weight_type"] == record["weight_type"]]
    return record["weight_type"] if len(same) == 1 else f"{record['weight_type']} {record['route_index'] + 1}"


def route_ribbons(routes, width):
    """*routes* as bands *width* metres wide, in EPSG:4326, buffered in the
    UTM zone of the routes, with the routes' columns."""
    if not width > 0:
        raise ValueError("The route width on the map is a number of metres above 0.")
    utm = routes.estimate_utm_crs()
    bands = routes.to_crs(utm).buffer(width / 2.0, cap_style="round", join_style="round")
    return gpd.GeoDataFrame(routes.drop(columns="geometry"), geometry=bands.to_crs("EPSG:4326").to_numpy(),
                            crs="EPSG:4326")


def weather_routes(arg, roads, weather, model, origin, destination, mode, k, time, conditions, width=40.0):
    """``(routes, endpoints, ribbons, metrics)``: SCOUT's weather-aware routes
    in the area *arg* from *origin* to *destination* (``{"lat", "lon"}``)
    leaving at *time*, for *mode* and the *conditions* chosen,
    ``{condition: weight}``; *width* is the ribbons' width in metres.
    *roads* is the road network, *weather* SCOUT's WRF files, ``{variable:
    xarray Dataset}``, and *model* ``curio_load_model("model.scout.weather-gnn")``."""
    if mode not in MODES:
        raise ValueError(f"The mode is one of {', '.join(MODES)}, not {mode!r}.")
    unknown = [c for c in conditions if c not in CONDITIONS]
    if unknown:
        raise ValueError(f"The weather conditions are {', '.join(CONDITIONS)}, not {', '.join(unknown)}.")
    if mode != "Default weights" and not conditions:
        raise ValueError(f"'{mode}' routes for the conditions chosen: choose at least one.")
    K = int(k)
    if K < 1:
        raise ValueError("K, the number of routes for each condition, is at least 1.")
    area = routing_inputs(arg, roads, weather)
    origin, destination = location(origin, "origin"), location(destination, "destination")

    xmin, ymin, xmax, ymax = area.total_bounds
    for name, (lat, lon) in (("origin", origin), ("destination", destination)):
        if not (ymin <= lat <= ymax and xmin <= lon <= xmax):
            raise ValueError(
                f"The {name} ({lat:.5f}, {lon:.5f}) is outside the area's roads, "
                f"{xmin:.4f} to {xmax:.4f} longitude and {ymin:.4f} to {ymax:.4f} latitude."
            )

    grids, lats, lons, start = weather_grids(weather)
    steps = next(iter(grids.values())).shape[0]
    try:
        index = time_to_global_index(time, start)
    except ValueError as exc:
        raise ValueError(f"The start time is a date and time like 2025-07-06T00:00:00, not {time!r}.") from exc
    if not 0 <= index < steps:
        last = start + (steps - 2) * pd.Timedelta(minutes=15)
        raise ValueError(f"The weather covers {start:%Y-%m-%d %H:%M} to {last:%Y-%m-%d %H:%M}; "
                         f"{time} is outside it.")

    G = crop(road_network(roads), (xmin, ymin, xmax, ymax))
    orig_node = nearest_node(G, *origin)
    dest_node = nearest_node(G, *destination)
    try:
        route = nx.shortest_path(G, orig_node, dest_node, weight="travel_time")
    except nx.NetworkXNoPath as exc:
        raise ValueError("No road inside the area joins the origin to the destination; widen the area.") from exc
    trip_times_seconds = calculate_isochrones(G, orig_node, route)

    rain_weight, heat_weight, wind_weight, humidity_weight = weights_for(mode, conditions)
    GNN_weight_calculations(G, model, grids, lats, lons, time=index, trip_time_seconds=trip_times_seconds,
                            rain_weight=rain_weight, heat_weight=heat_weight,
                            wind_weight=wind_weight, humidity_weight=humidity_weight)
    records = calculate_routes(G, orig_node, dest_node, mode, K, list(conditions))

    rows = []
    for record in records:
        rows.append({
            "route": route_label(record, records),
            "weight_type": record["weight_type"],
            "route_index": record["route_index"],
            "distance_km": record["distance"],
            "duration_min": record["duration"],
            "rain_exposure": record["rain_exposure"],
            "heat_exposure": record["heat_exposure"],
            "wind_exposure": record["wind_exposure"],
            "humidity_exposure": record["humidity_exposure"],
            "route_number": len(rows) + 1,
            "geometry": LineString([(G.nodes[n]["x"], G.nodes[n]["y"]) for n in record["route"]]),
        })
    routes = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")

    first = records[0]["route"]
    endpoints = gpd.GeoDataFrame(
        {"kind": ["origin", "destination"]},
        geometry=[Point(G.nodes[first[0]]["x"], G.nodes[first[0]]["y"]),
                  Point(G.nodes[first[-1]]["x"], G.nodes[first[-1]]["y"])],
        crs="EPSG:4326",
    )

    shown = [(key, label) for key, label in METRICS
             if not key.endswith("_exposure") or key.split("_")[0] in conditions]
    metrics = pd.DataFrame(
        [{"route": route_label(r, records), "metric": label, "value": float(r[key])}
         for key, label in shown for r in records],
        columns=["route", "metric", "value"],
    )

    return routes, endpoints, route_ribbons(routes, float(width)), metrics
