"""SCOUT's edge weights from a graph network's weather predictions.

Ported from SCOUT (https://github.com/urban-toolkit/scout),
backend/models/routing/scripts/weight_calculation.py. What changed:

- The graph network runs as an ONNX model through onnxruntime (``gnn_predict``),
  the Data Catalog's data.scout.weather-gnn, in place of SCOUT's torch
  ``NodeRegressor`` loaded from rain_model.pth. Its inputs are the arrays SCOUT
  hands torch, as numpy arrays.
- The edge weights are stored as Python floats. SCOUT computes them in float32
  and, under numpy 1, its routing sums them in float64; numpy 2 would sum
  float32 values in float32.
- A trip's 15-minute zones read the weather's hourly step each zone starts in
  (``stitchDataset``), where SCOUT read one step further per zone.
- ``GNN_weight_calculations`` takes the weather files only: SCOUT also passed
  it its loader's masked slices and grid, which only ``train_GNN_model`` read.
  ``train_GNN_model`` (which SCOUT runs only when rain_model.pth is missing),
  ``classic_weight_calculations`` and ``get_element_at_point`` (which nothing
  calls) are left out.

The weather at each node is the value of the WRF cell nearest to it
(``build_grid_kdtree``): the WRF grid is a Lambert conformal one, given cell
by cell in XLAT and XLONG, which Curio's raster readers (north-up grids) do not
sample.
"""

import numpy as np
import networkx as nx

import geopandas as gpd
from shapely.geometry import Point
from scipy.spatial import cKDTree

#: The minutes each zone of a trip covers (calculate_isochrones).
ZONE_MINUTES = 15


def gnn_predict(session, x, edge_index):
    """The graph network's five weather values at each node: an onnxruntime
    session of data.scout.weather-gnn on SCOUT's node features and edges."""
    return session.run(["prediction"], {"x": x, "edge_index": edge_index})[0]


def build_grid_kdtree(lats_arr, lons_arr):
    """Builds a k-d tree from flattened grid coordinates for fast nearest-neighbor lookup."""
    grid_points = np.vstack((lats_arr.flatten(), lons_arr.flatten())).T
    return cKDTree(grid_points)


def get_values_at_points_kdtree(grid_vals, kdtree, points_latlon):
    """Gets weather values from a grid for specific points using a pre-built k-d tree."""
    _, indices = kdtree.query(points_latlon, k=1)
    flat_vals = grid_vals.flatten()
    return flat_vals[indices]


def GNN_weight_calculations(G,
                            rain_ds,
                            time,
                            heat_ds,
                            wind_speed_ds,
                            wind_dir_ds,
                            humidity_ds,
                            trip_time_seconds,
                            rain_weight=0.85834,
                            heat_weight=0.02850,
                            wind_weight=0.09648,
                            humidity_weight=0.01668,
                            *,
                            session,
                            minutes_into_step=0):
    """
    Use a GNN to predict rain in any given node and use that vector to apply weights to the graph edges as a matrix operation.

    This modifies the weights for travel_time into a new variable "rain_weight", so that the routing algorithm can optimize for the fastest route given current weather events.

    Parameters:
    G (networkx.MultiDiGraph): The street graph.
    rain_ds (NC): 3D array of rain data (time, lat, lon).
    heat_ds (NC): 3D array of heat data (time, lat, lon).
    wind_speed_ds (NC): 3D array of wind speed data (time, lat, lon).
    wind_dir_ds (NC): 3D array of wind direction data (time, lat, lon).
    humidity_ds (NC): 3D array of humidity data (time, lat, lon).
    time (int): The weather's step the trip starts in.
    trip_time_seconds (list): List of trip times in seconds for which to stitch datasets.
    session: The onnxruntime session of the weather GNN.
    minutes_into_step (int): How far into its step the trip starts.

    Default penalty lambda based calculated previously with entropy weights.
    rain_weight: 0.85834
    heat_weight: 0.02850
    wind_weight: 0.09648
    rh_weight: 0.01668

    Returns the GNN's input and output: ``{"x", "edge_index", "prediction"}``.
    """

    stitch = dict(starting_time=time, trip_time_seconds=trip_time_seconds, minutes_into_step=minutes_into_step)
    rain_stitched = stitchDataset(G, rain_ds, variable_name='RAIN', **stitch)
    heat_stitched = stitchDataset(G, heat_ds, variable_name='T2', **stitch)
    wind_speed_stitched = stitchDataset(G, wind_speed_ds, variable_name='WSPD10', **stitch)
    wind_dir_stitched = stitchDataset(G, wind_dir_ds, variable_name='WDIR10', **stitch)
    humidity_stitched = stitchDataset(G, humidity_ds, variable_name='RH2', **stitch)

    # Extract 2D spatial grids
    lats_raw = rain_ds.variables['XLAT'][:]
    lons_raw = rain_ds.variables['XLONG'][:]
    if lats_raw.ndim == 3:
        lats_2d = np.array(lats_raw[0, :, :])
        lons_2d = np.array(lons_raw[0, :, :])
    else:
        lats_2d = np.array(lats_raw)
        lons_2d = np.array(lons_raw)
    node_ids = list(G.nodes)
    coords = np.array([[G.nodes[n]['y'], G.nodes[n]['x']] for n in node_ids])  # lat, lon

    # We build our variables to input to the GNN
    x, edge_index, node_ids = prepare_node_features_and_edges(
        G, rain_stitched, heat_stitched, wind_speed_stitched, wind_dir_stitched, humidity_stitched,
        lats_2d, lons_2d, coords
    )

    # Model makes predictions
    preds = gnn_predict(session, x, edge_index)
    prediction = preds
    preds = np.nan_to_num(preds, nan=0.0)

    rain_pred_node = np.clip(preds[:, 0], 0, None)
    heat_pred_node = preds[:, 1]
    humidity_pred_node = np.clip(preds[:, 2], 0, 1)
    wind_speed_pred_node = np.clip(preds[:, 3], 0, None)
    wind_dir_pred_node = preds[:, 4]  # allow negative for direction

    # Create edge index
    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
    edges_list = list(G.edges(keys=True))
    v_idx = np.array([id_to_idx[v] for _, v, _ in edges_list])

    travel_lengths = np.array([G[u][v][k].get("travel_time", 1.0) for u, v, k in edges_list], dtype=np.float32)

    # Get predicted weather values at edge target nodes
    rain_pred_at_v = rain_pred_node[v_idx]
    heat_pred_at_v = heat_pred_node[v_idx]
    humidity_pred_at_v = humidity_pred_node[v_idx]
    wind_speed_pred_at_v = wind_speed_pred_node[v_idx]
    wind_dir_pred_at_v = wind_dir_pred_node[v_idx]

    # Calculate all edge weights in a vectorized manner
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

    # Perform bulk assignment of the new weights to the graph edges, as the
    # Python floats SCOUT's routing summed them as.
    for name, weights in (("rain_weight", rain_w), ("heat_weight", heat_w), ("humidity_weight", humidity_w),
                          ("wind_weight", wind_w), ("wind_dir_weight", wind_dir_w), ("total_weight", total_w)):
        nx.set_edge_attributes(G, dict(zip(edges_list, (float(w) for w in weights))), name)

    return {"x": x, "edge_index": edge_index, "prediction": prediction}


def prepare_node_features_and_edges(G, rain_grid, heat_grid, wind_speed_grid, wind_dir_grid, humidity_grid, lats, lons, coords):
    """The GNN's input: ``x`` (float32, one row per node: lat, lon, rain, heat,
    wind speed, wind direction, humidity), ``edge_index`` (int64, the source and
    target row of each edge) and the node ids in row order."""

    grid_kdtree = build_grid_kdtree(lats, lons)

    node_ids = list(G.nodes)

    if rain_grid is not None:
        rain_nodes = get_values_at_points_kdtree(rain_grid, grid_kdtree, coords)
        rain_nodes = np.nan_to_num(rain_nodes, nan=np.nanmedian(rain_nodes))
    else:
        rain_nodes = np.zeros(len(coords))

    if heat_grid is not None:
        heat_nodes = get_values_at_points_kdtree(heat_grid, grid_kdtree, coords)
        heat_nodes = np.nan_to_num(heat_nodes, nan=np.nanmedian(heat_nodes))
    else:
        heat_nodes = np.zeros(len(coords))

    if wind_speed_grid is not None:
        wind_speed_nodes = get_values_at_points_kdtree(wind_speed_grid, grid_kdtree, coords)
        wind_speed_nodes = np.nan_to_num(wind_speed_nodes, nan=np.nanmedian(wind_speed_nodes))
    else:
        wind_speed_nodes = np.zeros(len(coords))

    if wind_dir_grid is not None:
        wind_dir_nodes = get_values_at_points_kdtree(wind_dir_grid, grid_kdtree, coords)
        wind_dir_nodes = np.nan_to_num(wind_dir_nodes, nan=np.nanmedian(wind_dir_nodes))
    else:
        wind_dir_nodes = np.zeros(len(coords))

    if humidity_grid is not None:
        humidity_nodes = get_values_at_points_kdtree(humidity_grid, grid_kdtree, coords)
        humidity_nodes = np.nan_to_num(humidity_nodes, nan=np.nanmedian(humidity_nodes))
    else:
        humidity_nodes = np.zeros(len(coords))

    # Node features (lat, lon, and weather data). SCOUT turns the float64 table
    # into a float32 tensor; astype rounds to the same float32 values.
    x_np = np.column_stack([
        coords[:, 0],
        coords[:, 1],
        rain_nodes,
        heat_nodes,
        wind_speed_nodes,
        wind_dir_nodes,
        humidity_nodes,
    ])
    x = np.ascontiguousarray(x_np.astype(np.float32))

    # Build edge_index
    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
    edges = []
    for u_n, v_n, data in G.edges(data=True):
        edges.append([id_to_idx[u_n], id_to_idx[v_n]])
    edge_index = np.ascontiguousarray(np.array(edges, dtype=np.int64).reshape(-1, 2).T)
    if edge_index.size == 0:
        raise RuntimeError("Edge index is empty!")

    return x, edge_index, node_ids


def stitchDataset(G, dataset, trip_time_seconds, variable_name, starting_time=17, minutes_into_step=0, step_minutes=60):
    """Stitch together time slices from a dataset based on zones in the graph G.

    Zone ``t + 1`` covers the trip's minutes ``15 t`` to ``15 (t + 1)`` and takes
    the step the trip is in when the zone starts: ``starting_time`` and
    ``minutes_into_step`` say where the trip starts, and the steps are
    ``step_minutes`` long.
    """

    # Handle empty trip times (e.g. start/end are same node)
    if not trip_time_seconds:
        # Just load the single starting time slice
        slice_data = np.array(dataset.variables[variable_name][starting_time, :, :])
        return slice_data

    # Preload time slices
    tdim = dataset.variables[variable_name].shape[0]
    loaded_data = []
    for t in range(len(trip_time_seconds)):
        idx = min(starting_time + (minutes_into_step + ZONE_MINUTES * t) // step_minutes, tdim - 1)
        slice_data = np.array(dataset.variables[variable_name][idx, :, :])
        loaded_data.append(slice_data)

    zone_polygons = create_zone_polygons(G)

    # Extract 2D spatial grids
    lats_raw = dataset.variables['XLAT'][:]
    lons_raw = dataset.variables['XLONG'][:]

    if lats_raw.ndim == 3:
        lats = np.array(lats_raw[0, :, :])
        lons = np.array(lons_raw[0, :, :])
    else:
        lats = np.array(lats_raw)
        lons = np.array(lons_raw)

    stitched = np.zeros_like(loaded_data[0], dtype=np.float32)

    # Assign each zone its corresponding time slice
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


def create_zone_polygons(G):
    """Create a convex hull polygon for each zone based on edge endpoints."""
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
            zone_polygons[zone] = gpd.GeoSeries(unique_pts).union_all().convex_hull
        elif len(unique_pts) == 2:
            zone_polygons[zone] = gpd.GeoSeries(unique_pts).union_all().buffer(0.001)
        elif len(unique_pts) == 1:
            zone_polygons[zone] = unique_pts[0].buffer(0.001)
    return zone_polygons
