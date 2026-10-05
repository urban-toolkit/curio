"""SCOUT's weather-aware routing: the weather of each street, then routes.

Ported from SCOUT (https://github.com/urban-toolkit/scout), folder
backend/models/routing/scripts: ``calculate_isochrones`` and
``get_estimated_ETA`` (calculate_isochrones.py), ``stitchDataset``,
``create_zone_polygons``, ``build_grid_kdtree``,
``get_values_at_points_kdtree``, ``prepare_node_features_and_edges`` and
``GNN_weight_calculations`` (weight_calculation.py), and the weights and
routes of ``calculate_weather_route`` (weather_routing.py). The functions keep
SCOUT's names and arithmetic, its order of weather variables and its default
weights. Changes from SCOUT's files:

- The GNN is the Model Catalog's ``model.scout.weather-gnn``, an ONNX export
  of SCOUT's ``rain_model.pth`` run through ``CurioModel.run``: no PyTorch or
  PyTorch Geometric. SCOUT trains a new model when the file is missing; Curio
  only runs the trained one.
- The weather is a ``{variable: (steps, rows, cols) array}`` dict and 2D
  ``lats`` and ``lons``, from the Data Catalog's table, instead of NetCDF
  datasets read with netCDF4.
- No osmnx: ``nearest_node`` is the haversine nearest neighbour osmnx's
  ``nearest_nodes`` finds on an unprojected graph, and ``k_shortest_paths``
  is osmnx's (Yen's algorithm, ``nx.shortest_simple_paths``, on the DiGraph
  that keeps the lightest of parallel edges).
- ``create_zone_polygons`` builds its hulls with shapely, not a GeoSeries'
  ``unary_union``: the same shapes.
- SCOUT's routes go to GeoJSON and CSV files named by the dataflow; here they
  are returned (``node_outputs``). Its ``distance_m`` holds kilometres, so
  the distance is ``distance_km`` here.
"""

import itertools
from datetime import datetime

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import MultiPoint, Point

#: SCOUT's default weights ("Default weights" mode), from entropy weighting.
#: SCOUT's comments give 0.09648 to wind and 0.01657 to humidity, but its
#: code, kept here, gives them the other way round.
DEFAULT_WEIGHTS = {"rain": 0.85834, "heat": 0.02850, "humidity": 0.09648, "wind": 0.01657}
MODES = ("Default weights", "Custom weights", "Single-factor weights")
CONDITIONS = ("rain", "heat", "wind", "humidity")
#: The first time of SCOUT's weather run, which its time index counts from.
WEATHER_START = "2025-07-06T00:00:00"
EARTH_RADIUS_M = 6_371_009


# calculate_isochrones.py -----------------------------------------------------


def calculate_isochrones(G, orig, route):
    """Give each edge a ``zone``: 1 for the edges reached within the first
    15 minutes from *orig*, 2 within 30, and so on to the trip's length.
    Later the zones are used to stitch the weather of different times."""
    for u, v, k, data in G.edges(data=True, keys=True):
        data['zone'] = 0
        data['time'] = data['length'] / (data['speed_kph'] * 1000 / 3600)

    travel_times = get_estimated_ETA(G, route)
    trip_times_seconds = [t * 60 for t in travel_times]
    for zone_num, trip_time in enumerate(sorted(trip_times_seconds), start=1):
        subgraph = nx.ego_graph(G, orig, radius=trip_time, distance='time')
        for u, v, k in subgraph.edges(keys=True):
            if G.has_edge(u, v, k) and G[u][v][k]["zone"] == 0:
                G[u][v][k]["zone"] = zone_num

    return trip_times_seconds


def get_estimated_ETA(G, route):
    """15 minute segments until the route's travel time: [15, 30, 45, 60]
    for a 1 hour trip."""
    total_time_sec = sum(
        G[u][v][0]['time']
        for u, v in zip(route[:-1], route[1:])
    )
    return list(range(15, int(total_time_sec // 60) + 15, 15))


# weight_calculation.py -------------------------------------------------------


def build_grid_kdtree(lats_arr, lons_arr):
    """A k-d tree of the grid's cells, for the nearest cell of a point."""
    grid_points = np.vstack((lats_arr.flatten(), lons_arr.flatten())).T
    return cKDTree(grid_points)


def get_values_at_points_kdtree(grid_vals, kdtree, points_latlon):
    """The grid's value at each point, from its nearest cell."""
    _, indices = kdtree.query(points_latlon, k=1)
    flat_vals = grid_vals.flatten()
    return flat_vals[indices]


def create_zone_polygons(G):
    """A convex hull for each zone, of its edges' end points."""
    zones = {}
    for u, v, k, data in G.edges(keys=True, data=True):
        zone = data.get("zone", 0)
        if zone == 0:
            continue
        zones.setdefault(zone, []).append(Point(G.nodes[u]["x"], G.nodes[u]["y"]))
        zones.setdefault(zone, []).append(Point(G.nodes[v]["x"], G.nodes[v]["y"]))

    zone_polygons = {}
    for zone, points in zones.items():
        unique_pts = list({(p.x, p.y): p for p in points}.values())
        if len(unique_pts) >= 3:
            zone_polygons[zone] = MultiPoint(unique_pts).convex_hull
        elif len(unique_pts) == 2:
            zone_polygons[zone] = MultiPoint(unique_pts).buffer(0.001)
        elif len(unique_pts) == 1:
            zone_polygons[zone] = unique_pts[0].buffer(0.001)
    return zone_polygons


def stitchDataset(G, grid, lats, lons, trip_time_seconds, starting_time=17):
    """One grid of *grid* (``(steps, rows, cols)``) in which each zone's
    cells hold the zone's time: zone 1 the starting step, zone 2 the next.
    A cell in no zone's box is 0."""
    tdim = grid.shape[0]
    if not trip_time_seconds:
        return np.array(grid[starting_time, :, :])

    loaded_data = []
    for t in range(len(trip_time_seconds)):
        idx = min(starting_time + t, tdim - 1)
        loaded_data.append(np.array(grid[idx, :, :]))

    zone_polygons = create_zone_polygons(G)
    stitched = np.zeros_like(loaded_data[0], dtype=np.float32)

    # Zones are laid down in the order their edges come; a later one
    # overwrites an earlier one where their boxes overlap, as in SCOUT.
    for zone, polygon in zone_polygons.items():
        minx, miny, maxx, maxy = polygon.bounds
        zone_mask = (lats >= miny) & (lats <= maxy) & (lons >= minx) & (lons <= maxx)
        if not np.any(zone_mask):
            continue
        time_index = zone - 1
        if time_index < 0 or time_index >= len(loaded_data):
            continue
        stitched[zone_mask] = loaded_data[time_index][zone_mask]

    return stitched


def prepare_node_features_and_edges(G, rain_grid, heat_grid, wind_speed_grid, wind_dir_grid,
                                    humidity_grid, lats, lons, coords):
    """The GNN's inputs: ``x``, each node's latitude, longitude and the
    weather of its nearest cell, and ``edge_index``, each edge's two nodes."""
    grid_kdtree = build_grid_kdtree(lats, lons)
    node_ids = list(G.nodes)

    def at_nodes(grid):
        if grid is None:
            return np.zeros(len(coords))
        values = get_values_at_points_kdtree(grid, grid_kdtree, coords)
        return np.nan_to_num(values, nan=np.nanmedian(values))

    x = np.column_stack([
        coords[:, 0],
        coords[:, 1],
        at_nodes(rain_grid),
        at_nodes(heat_grid),
        at_nodes(wind_speed_grid),
        at_nodes(wind_dir_grid),
        at_nodes(humidity_grid),
    ]).astype(np.float32)

    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
    edges = [[id_to_idx[u_n], id_to_idx[v_n]] for u_n, v_n in G.edges()]
    edge_index = np.array(edges, dtype=np.int64).T.reshape(2, -1)
    if edge_index.size == 0:
        raise ValueError("The road network inside the area has no edges.")
    return x, edge_index, node_ids


def GNN_weight_calculations(G, model, weather, lats, lons, time, trip_time_seconds,
                            rain_weight=0.85834, heat_weight=0.02850,
                            wind_weight=0.09648, humidity_weight=0.01668):
    """The GNN's weather at every node, and from it each edge's weights:
    ``rain_weight``, ``heat_weight``, ``humidity_weight``, ``wind_weight``,
    ``wind_dir_weight`` and ``total_weight``, beside its ``travel_time``.

    *model* is ``curio_load_model("model.scout.weather-gnn")``; *weather*
    maps ``RAIN``, ``T2``, ``WSPD10``, ``WDIR10`` and ``RH2`` to
    ``(steps, rows, cols)`` grids on *lats* and *lons*."""
    def stitch(variable):
        return stitchDataset(G, weather[variable], lats, lons, starting_time=time,
                             trip_time_seconds=trip_time_seconds)

    node_ids = list(G.nodes)
    coords = np.array([[G.nodes[n]['y'], G.nodes[n]['x']] for n in node_ids])
    x, edge_index, node_ids = prepare_node_features_and_edges(
        G, stitch("RAIN"), stitch("T2"), stitch("WSPD10"), stitch("WDIR10"), stitch("RH2"),
        lats, lons, coords,
    )

    (preds,) = model.run({"x": x, "edge_index": edge_index})
    preds = np.nan_to_num(preds, nan=0.0)

    rain_pred_node = np.clip(preds[:, 0], 0, None)
    heat_pred_node = preds[:, 1]
    humidity_pred_node = np.clip(preds[:, 2], 0, 1)
    wind_speed_pred_node = np.clip(preds[:, 3], 0, None)
    wind_dir_pred_node = preds[:, 4]  # allow negative for direction

    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
    edges_list = list(G.edges(keys=True))
    v_idx = np.array([id_to_idx[v] for _, v, _ in edges_list])
    travel_lengths = np.array([G[u][v][k].get("travel_time", 1.0) for u, v, k in edges_list], dtype=np.float32)

    # The predicted weather at each edge's target node.
    rain_pred_at_v = rain_pred_node[v_idx]
    heat_pred_at_v = heat_pred_node[v_idx]
    humidity_pred_at_v = humidity_pred_node[v_idx]
    wind_speed_pred_at_v = wind_speed_pred_node[v_idx]
    wind_dir_pred_at_v = wind_dir_pred_node[v_idx]

    rain_w = abs((rain_pred_at_v * rain_weight) + (travel_lengths * (1 - rain_weight)))
    heat_w = abs((heat_pred_at_v * heat_weight) + (travel_lengths * (1 - heat_weight)))
    humidity_w = abs((humidity_pred_at_v * humidity_weight) + (travel_lengths * (1 - humidity_weight)))
    wind_w = abs((wind_speed_pred_at_v * wind_weight) + (travel_lengths * (1 - wind_weight)))
    wind_dir_w = (wind_dir_pred_at_v * wind_weight) + (travel_lengths * (1 - wind_weight))

    total_w = (
        (rain_weight * rain_pred_at_v) +
        (wind_weight * wind_speed_pred_at_v) +
        (heat_weight * heat_pred_at_v) +
        (humidity_weight * humidity_pred_at_v) +
        (travel_lengths * (1 - (rain_weight + wind_weight + heat_weight + humidity_weight)))
    )

    for name, values in (("rain_weight", rain_w), ("heat_weight", heat_w), ("humidity_weight", humidity_w),
                         ("wind_weight", wind_w), ("wind_dir_weight", wind_dir_w), ("total_weight", total_w)):
        nx.set_edge_attributes(G, dict(zip(edges_list, values)), name)


# weather_routing.py ----------------------------------------------------------


def time_to_global_index(time_string, start_time):
    """SCOUT's index of a time in its weather run: 1 for the first quarter
    hour after *start_time*, 2 for the next. (It reads the step after the
    time it is given; kept as SCOUT does it.)"""
    dt = datetime.strptime(time_string, "%Y-%m-%dT%H:%M:%S")
    diff_minutes = int((dt - start_time).total_seconds() // 60)
    return diff_minutes // 15 + 1


def nearest_node(G, lat, lon):
    """The node nearest (*lat*, *lon*) on the sphere, as osmnx's
    ``nearest_nodes`` finds it on an unprojected graph."""
    node_ids = list(G.nodes)
    ys = np.deg2rad(np.array([G.nodes[n]["y"] for n in node_ids], dtype=float))
    xs = np.deg2rad(np.array([G.nodes[n]["x"] for n in node_ids], dtype=float))
    lat, lon = np.deg2rad(lat), np.deg2rad(lon)
    a = np.sin((ys - lat) / 2) ** 2 + np.cos(lat) * np.cos(ys) * np.sin((xs - lon) / 2) ** 2
    return node_ids[int(np.argmin(a))]


def k_shortest_paths(G, orig, dest, k, weight):
    """osmnx's ``k_shortest_paths``: the *k* lightest simple paths, by Yen's
    algorithm, on the DiGraph that keeps the lightest of parallel edges."""
    D = G.copy()
    parallels = ((u, v) for u, v in D.edges(keys=False) if len(D.get_edge_data(u, v)) > 1)
    to_remove = []
    for u, v in set(parallels):
        k_min, _ = min(D.get_edge_data(u, v).items(), key=lambda x: x[1][weight])
        to_remove.extend((u, v, key) for key in D[u][v] if key != k_min)
    D.remove_edges_from(to_remove)
    yield from itertools.islice(nx.shortest_simple_paths(nx.DiGraph(D), orig, dest, weight), 0, k)


def weights_for(mode, conditions):
    """``(rain, heat, wind, humidity)`` weights for *mode*; *conditions*
    maps each condition chosen to the weight given it."""
    if mode == "Default weights":
        return (DEFAULT_WEIGHTS["rain"], DEFAULT_WEIGHTS["heat"], DEFAULT_WEIGHTS["wind"],
                DEFAULT_WEIGHTS["humidity"])
    weights = tuple(conditions.get(c, 0) for c in ("rain", "heat", "wind", "humidity"))
    if mode == "Custom weights":
        if sum(conditions.values()) > 1.0:
            raise ValueError("In 'Custom weights' mode, the weather weights may add up to 1 at most.")
    elif any(w < 0 or w > 1 for w in weights):
        raise ValueError("In 'Single-factor weights' mode, each weather weight is between 0 and 1.")
    return weights


def route_record(G, route, weight_type, route_index, conditions):
    """A route and SCOUT's measures of it: distance in km, duration in
    minutes, and the exposure to each chosen condition (0 for the others)."""
    def exposure(condition):
        return nx.path_weight(G, route, weight=f"{condition}_weight") if condition in conditions else 0
    return {
        "route": route,
        "weight_type": weight_type,
        "route_index": route_index,
        "distance": nx.path_weight(G, route, weight='length') / 1000,
        "duration": nx.path_weight(G, route, weight='travel_time') / 60,
        "rain_exposure": exposure("rain"),
        "heat_exposure": exposure("heat"),
        "wind_exposure": exposure("wind"),
        "humidity_exposure": exposure("humidity"),
    }


def calculate_routes(G, orig_node, dest_node, mode, K, conditions):
    """SCOUT's routes for *mode*, after the weights are on *G*:

    - Default weights: the fastest route and the one lightest by
      ``total_weight``.
    - Custom weights: the *K* lightest routes for each chosen condition's
      weight, and the fastest.
    - Single-factor weights: the lightest route for each chosen condition's
      weight, and the fastest.
    """
    routes_data = []
    if mode == "Default weights":
        route_fastest = nx.shortest_path(G, orig_node, dest_node, weight="travel_time")
        route_total = nx.shortest_path(G, orig_node, dest_node, weight="total_weight")
        routes_data.append(route_record(G, route_fastest, "fastest-route", 0, conditions))
        routes_data.append(route_record(G, route_total, "weighted-route", 1, conditions))
        return routes_data

    if mode == "Custom weights":
        for weight in conditions:
            try:
                k_paths = list(k_shortest_paths(G, orig_node, dest_node, K, f"{weight}_weight"))
                for i in range(K):
                    routes_data.append(route_record(G, k_paths[i], f"{weight}-aware-route", i, conditions))
            except Exception as e:  # as SCOUT: fewer routes than K, or none
                print(f"Could not calculate route for {weight}: {e}")
    else:
        i = 1
        for weight in conditions:
            try:
                route = nx.shortest_path(G, orig_node, dest_node, weight=f"{weight}_weight")
                routes_data.append(route_record(G, route, f"{weight}-aware-route", i, conditions))
                i += 1
            except Exception as e:
                print(f"Could not calculate route for {weight}: {e}")

    route_fastest = nx.shortest_path(G, orig_node, dest_node, weight="travel_time")
    routes_data.append(route_record(G, route_fastest, "fastest-route", 0, conditions))
    return routes_data
