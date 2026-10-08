"""Cut SCOUT's routing data down to what Curio keeps: weather around Chicago, roads around the proof.

SCOUT (https://github.com/urban-toolkit/scout) routes on its whole Chicago road
graph, `backend/data/osm/processed/chicago/roads.pkl.gz` (40 MB, a pickled
networkx MultiDiGraph of 637,237 nodes and 741,271 edges), with five WRF weather
files under `backend/models/routing/weather_data/` (393 MB). This script writes
two cuts: the weather into the Data Catalog, each dataset with its manifest,
and the roads as the scout.routing proof's test fixture (a Curio road graph
comes from a Curio roads layer, so SCOUT's graph is not a dataset):

- Weather, one bundle dataset, `data.scout.chicago-weather-2025-07-06`: the five
  variables (RAIN, T2, RH2, WSPD10, WDIR10), `data/<variable>.nc` listed by its
  `data/bundle.json`, each still a NetCDF file of its own with its grid, its 88 global attributes and its variable attributes. Kept:
  every grid cell of a box around SCOUT's Chicago graph (its node extent, plus
  WEATHER_MARGIN_CELLS cells on every side), and all 49 hourly time steps (SCOUT
  counts steps from the file's first, so the time axis stays whole). Values are
  copied bit for bit; the variables are stored with zlib (level 2, with shuffle,
  as the source stores T2, XLAT and XLONG). The NCO `history` attribute gains one
  line naming this cut, and a global attribute `timezone` (TIMEZONE) says the
  local time a start time is read in: the files' own times are UTC (`GMT`, 0).
- Roads: SCOUT's graph inside GRAPH_BOX, a box around the routing example's
  origin and destination with at least 0.02 degrees beyond the box SCOUT routes
  in, stored as two Parquet tables instead of a pickle, in the proof's fixture
  folder (`utk_curio/backend/tests/test_packages/fixtures/scout_routing/`):
  - `roads_nodes.parquet`: `osmid`, `x`, `y` (every node attribute SCOUT's
    graph has);
  - `roads_edges.parquet`: `u`, `v`, `key`, `length`, `speed_kph`,
    `travel_time` (the edge attributes SCOUT's routing reads; the other 36, OSM
    tags and metadata and the geometry, are left out).
  Both carry the graph's `crs` in their Parquet metadata. `read_road_graph` below
  rebuilds the MultiDiGraph: nodes in row order, then edges in row order. The
  edge rows are in an order that gives every node its successors AND its
  predecessors in the order SCOUT's graph holds them, so networkx's searches
  (bidirectional Dijkstra reads predecessors) visit them as they do in SCOUT.
  GRAPH_BOX holds more than twice the nodes of the box SCOUT routes in, so the
  subgraph view SCOUT's `load_graph` takes iterates its nodes in the same order on
  this cut as on SCOUT's whole graph (networkx iterates a view by its node set
  when that set is under half the graph).

Usage, in any Python 3.9 or later with numpy, scipy, netCDF4, networkx, pyarrow
and geopandas (the reading of SCOUT's pickle happens only here):

    python scripts/scout/crop_routing_data.py --scout <SCOUT checkout>

It writes the weather into the repository's `datasets/`, or into `--catalog
<folder>`, the roads into the fixture folder, or into `--fixtures <folder>`, and,
with `--report`, a JSON of every check. It exits with status 1 when a check
fails. A rerun in the same environment writes the same bytes.
"""

import argparse
import gzip
import heapq
import json
import pickle
import sys
from pathlib import Path

import netCDF4 as nc
import networkx as nx
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.spatial import cKDTree

from scout_checkout import (BLOBS, CATALOG, FIXTURES, PERMISSION, ROAD_EDGES_FILE, ROAD_NODES_FILE, ROUTING,
                            SCOUT_COMMIT, SCOUT_URL, WEATHER_ID, WEATHER_INDEX, WEATHER_VARIABLES, blob_ids,
                            check_scout_checkout, sha256, weather_file, write_manifest, write_weather_bundle)

GRAPH_PICKLE = "backend/data/osm/processed/chicago/roads.pkl.gz"
ROADS_LAYER = "backend/data/osm/processed/chicago/roads.feather"
# The bbox of the roads layer SCOUT's routing example cuts (its data layer node,
# `roi.value`, as xmin, ymin, xmax, ymax). SCOUT routes inside the bounds of the
# roads that layer keeps, which reach a little beyond it.
EXAMPLE_LAYER_BBOX = (-87.662, 41.859, -87.613, 41.898)
# xmin, ymin, xmax, ymax of the road graph Curio keeps.
GRAPH_BOX = (-87.69, 41.835, -87.585, 41.92)
GRAPH_MARGIN_MIN = 0.02  # degrees GRAPH_BOX must reach beyond SCOUT's routing box
WEATHER_MARGIN_CELLS = 2
# The time zone of the place the weather covers, in which a start time is read.
TIMEZONE = "America/Chicago"
NODE_COLUMNS = ("osmid", "x", "y")
EDGE_ATTRIBUTES = ("length", "speed_kph", "travel_time")
EDGE_COLUMNS = ("u", "v", "key") + EDGE_ATTRIBUTES
COMPRESSION = {"zlib": True, "complevel": 2, "shuffle": True}
WEATHER_NAMES = {
    "RAIN": ("Rain", "Hourly rain (RAIN)"),
    "T2": ("Temperature at 2 m", "The temperature at 2 m (T2, in kelvin)"),
    "RH2": ("Relative Humidity at 2 m", "The relative humidity at 2 m (RH2, in percent)"),
    "WSPD10": ("Wind Speed at 10 m", "The wind speed at 10 m (WSPD10, in metres per second)"),
    "WDIR10": ("Wind Direction at 10 m", "The wind direction at 10 m (WDIR10, in degrees)"),
}
WEATHER_TAGS = ["netcdf", "weather", "wrf", "scout", "chicago", "2025-07-06"]


# Roads.

def read_road_graph(nodes_path, edges_path):
    """The road graph from its two Parquet tables: nodes in row order, then edges."""
    nodes = pq.read_table(nodes_path)
    edges = pq.read_table(edges_path)
    crs = nodes.schema.metadata[b"crs"].decode()
    G = nx.MultiDiGraph(crs=crs)
    ids, xs, ys = (nodes.column(c).to_pylist() for c in NODE_COLUMNS)
    G.add_nodes_from((n, {"x": x, "y": y}) for n, x, y in zip(ids, xs, ys))
    columns = [edges.column(c).to_pylist() for c in EDGE_COLUMNS]
    for u, v, key, *values in zip(*columns):
        G.add_edge(u, v, key=key, **dict(zip(EDGE_ATTRIBUTES, values)))
    return G


def nodes_in_box(G, box):
    xmin, ymin, xmax, ymax = box
    return [n for n, d in G.nodes(data=True)
            if xmin <= d["x"] <= xmax and ymin <= d["y"] <= ymax]


def edge_insertion_order(G, nodes, keep):
    """The (u, v) pairs among *nodes*, ordered so that adding them in turn gives
    every node its successors and its predecessors in G's order.

    Each node's successor list and predecessor list (both cut to *keep*) are
    chains the order must follow; a topological sort of the pairs under those
    chains, taking the pair that comes first in G's own edge order whenever there
    is a choice, gives one. G's own insertion order satisfies the chains, so one
    always exists.
    """
    pairs = [(u, v) for u in nodes for v in G._succ[u] if v in keep]
    index = {pair: i for i, pair in enumerate(pairs)}
    after = [[] for _ in pairs]
    waiting = [0] * len(pairs)

    def chain(seq):
        for a, b in zip(seq, seq[1:]):
            after[a].append(b)
            waiting[b] += 1

    for u in nodes:
        chain([index[(u, v)] for v in G._succ[u] if v in keep])
    for v in nodes:
        chain([index[(u, v)] for u in G._pred[v] if u in keep])
    ready = [i for i, w in enumerate(waiting) if w == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        i = heapq.heappop(ready)
        order.append(i)
        for j in after[i]:
            waiting[j] -= 1
            if waiting[j] == 0:
                heapq.heappush(ready, j)
    if len(order) != len(pairs):
        raise SystemExit("the successor and predecessor orders contradict each other")
    return [pairs[i] for i in order]


def parquet_metadata(extra):
    meta = {"crs": "EPSG:4326", "source": (
        f"SCOUT {SCOUT_COMMIT} {GRAPH_PICKLE} (git blob {BLOBS[GRAPH_PICKLE]}), "
        f"nodes with x and y inside {list(GRAPH_BOX)}; made by scripts/scout/crop_routing_data.py")}
    meta.update(extra)
    return {k: str(v) for k, v in meta.items()}


def write_table(columns, types, path, metadata):
    table = pa.table({name: pa.array(values, type=types[name]) for name, values in columns.items()})
    table = table.replace_schema_metadata(metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")


def routing_box_of_example(scout):
    """The bounds of the roads SCOUT's example data layer keeps (server.py crop_gdf: `gdf.cx`)."""
    import geopandas as gpd

    roads = gpd.read_feather(Path(scout) / ROADS_LAYER)
    xmin, ymin, xmax, ymax = EXAMPLE_LAYER_BBOX
    return [float(b) for b in roads.cx[xmin:xmax, ymin:ymax].total_bounds]


def crop_roads(scout, G, fixtures, report):
    routing_box = routing_box_of_example(scout)
    margins = [routing_box[0] - GRAPH_BOX[0], routing_box[1] - GRAPH_BOX[1],
               GRAPH_BOX[2] - routing_box[2], GRAPH_BOX[3] - routing_box[3]]
    nodes = nodes_in_box(G, GRAPH_BOX)
    keep = set(nodes)
    routing_nodes = nodes_in_box(G, routing_box)
    pairs = edge_insertion_order(G, nodes, keep)
    rows = {c: [] for c in EDGE_COLUMNS}
    for u, v in pairs:
        for key, data in G._succ[u][v].items():
            for name, value in zip(EDGE_COLUMNS, (u, v, key) + tuple(data[a] for a in EDGE_ATTRIBUTES)):
                rows[name].append(value)
    nodes_path, edges_path = Path(fixtures) / ROAD_NODES_FILE, Path(fixtures) / ROAD_EDGES_FILE
    meta = parquet_metadata({"box": list(GRAPH_BOX)})
    write_table({"osmid": nodes, "x": [G.nodes[n]["x"] for n in nodes], "y": [G.nodes[n]["y"] for n in nodes]},
                {"osmid": pa.int64(), "x": pa.float64(), "y": pa.float64()}, nodes_path, meta)
    edge_meta = dict(meta, order=(
        "add the rows in this order: each node then has its successors and predecessors in SCOUT's order"))
    write_table(rows, {"u": pa.int64(), "v": pa.int64(), "key": pa.int64(), "length": pa.float64(),
                       "speed_kph": pa.float64(), "travel_time": pa.float64()}, edges_path, edge_meta)

    # The tables rebuild SCOUT's graph, cut to the box, exactly.
    R = read_road_graph(nodes_path, edges_path)
    problems = []
    if list(R.nodes) != nodes:
        problems.append("node order")
    if R.graph != {"crs": G.graph["crs"]}:
        problems.append("graph attributes")
    for n in nodes:
        if R.nodes[n] != G.nodes[n]:
            problems.append(f"node {n} attributes")
        if list(R._succ[n]) != [v for v in G._succ[n] if v in keep]:
            problems.append(f"node {n} successor order")
        if list(R._pred[n]) != [u for u in G._pred[n] if u in keep]:
            problems.append(f"node {n} predecessor order")
    for u, v, key, data in R.edges(keys=True, data=True):
        source = G._succ[u][v][key]
        if any(type(data[a]) is not float or data[a] != source[a] for a in EDGE_ATTRIBUTES):
            problems.append(f"edge {u} {v} {key} attributes")
    if list(R.edges(keys=True)) != [(u, v, k) for u in nodes for v in G._succ[u] if v in keep for k in G._succ[u][v]]:
        problems.append("edge iteration order")
    view_order_kept = 2 * len(routing_nodes) < len(nodes)
    position = {n: i for i, n in enumerate(nodes)}
    pred_order_not_node_order = sum(
        1 for v in nodes
        if [u for u in G._pred[v] if u in keep] != sorted((u for u in G._pred[v] if u in keep), key=position.get))
    report["roads"] = {
        "example_layer_bbox": list(EXAMPLE_LAYER_BBOX),
        "routing_box_from_roads_layer": routing_box,
        "graph_box": list(GRAPH_BOX),
        "margins_beyond_routing_box": margins,
        "nodes": len(nodes), "edges": R.number_of_edges(),
        "nodes_in_routing_box": len(routing_nodes),
        "view_iterates_like_scouts_whole_graph": view_order_kept,
        # Nodes whose predecessors a plain node-by-node edge order would put out of SCOUT's order.
        "nodes_whose_predecessor_order_needs_the_row_order": pred_order_not_node_order,
        "files": {p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)} for p in (nodes_path, edges_path)},
        "rebuilt_graph_problems": problems[:20],
    }
    if min(margins) < GRAPH_MARGIN_MIN:
        problems.append(f"GRAPH_BOX reaches only {min(margins):.4f} degrees beyond SCOUT's routing box")
    if not view_order_kept:
        problems.append("GRAPH_BOX holds less than twice the routing box's nodes")
    return problems


# Weather.

def weather_window(G, lat, lon):
    """Row and column ranges of the grid cells around SCOUT's graph, plus the margin."""
    xs = np.array([d["x"] for _, d in G.nodes(data=True)])
    ys = np.array([d["y"] for _, d in G.nodes(data=True)])
    inside = (lat >= ys.min()) & (lat <= ys.max()) & (lon >= xs.min()) & (lon <= xs.max())
    rows = np.where(inside.any(axis=1))[0]
    cols = np.where(inside.any(axis=0))[0]
    m = WEATHER_MARGIN_CELLS
    r0, r1 = max(int(rows.min()) - m, 0), min(int(rows.max()) + m + 1, lat.shape[0])
    c0, c1 = max(int(cols.min()) - m, 0), min(int(cols.max()) + m + 1, lat.shape[1])
    # Every node's nearest grid cell, the way SCOUT finds it (a k-d tree on
    # latitude and longitude), must be inside the window.
    tree = cKDTree(np.vstack((lat.flatten(), lon.flatten())).T)
    _, flat = tree.query(np.column_stack([ys, xs]), k=1)
    i, j = np.unravel_index(flat, lat.shape)
    covered = bool(np.all((i >= r0) & (i < r1) & (j >= c0) & (j < c1)))
    extent = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
    return (r0, r1), (c0, c1), covered, extent


def history_line(name, rows, cols, steps):
    return (f"curio scripts/scout/crop_routing_data.py: Time 0,{steps - 1} south_north {rows[0]},{rows[1] - 1} "
            f"west_east {cols[0]},{cols[1] - 1} of SCOUT's {ROUTING}/weather_data/{name}.nc "
            f"(git blob {BLOBS[f'{ROUTING}/weather_data/{name}.nc']}, SCOUT {SCOUT_COMMIT}); "
            f"added timezone {TIMEZONE}")


def crop_weather_file(src, dst, name, rows, cols):
    (r0, r1), (c0, c1) = rows, cols
    dst.parent.mkdir(parents=True, exist_ok=True)
    with nc.Dataset(src) as s, nc.Dataset(dst, "w", format="NETCDF4") as d:
        s.set_auto_maskandscale(False)
        steps = len(s.dimensions["Time"])
        for a in s.ncattrs():
            value = s.getncattr(a)
            if a == "history":
                value = history_line(name, rows, cols, steps) + "\n" + value
            d.setncattr(a, value)
        d.setncattr("timezone", TIMEZONE)
        sizes = {"Time": None, "south_north": r1 - r0, "west_east": c1 - c0}
        for dim in s.dimensions:
            d.createDimension(dim, sizes[dim])
        for vname, var in s.variables.items():
            if var.dimensions != ("Time", "south_north", "west_east"):
                raise SystemExit(f"{name}.nc: unexpected variable {vname} {var.dimensions}")
            # The weather variable is read one time step at a time; the
            # coordinates repeat at every step, so one chunk compresses them.
            chunks = (1 if vname == name else steps, r1 - r0, c1 - c0)
            out = d.createVariable(vname, var.dtype, var.dimensions, chunksizes=chunks, **COMPRESSION)
            out.set_auto_maskandscale(False)
            for a in var.ncattrs():
                out.setncattr(a, var.getncattr(a))
            out[:] = var[:, r0:r1, c0:c1]


def check_weather_file(src, dst, rows, cols):
    (r0, r1), (c0, c1) = rows, cols
    problems = []
    with nc.Dataset(src) as s, nc.Dataset(dst) as d:
        s.set_auto_maskandscale(False)
        d.set_auto_maskandscale(False)
        if d.data_model != s.data_model:
            problems.append("data model")
        for a in s.ncattrs():
            same = np.array_equal(np.asarray(s.getncattr(a)), np.asarray(d.getncattr(a)))
            if a != "history" and (not same or type(s.getncattr(a)) is not type(d.getncattr(a))):
                problems.append(f"global attribute {a}")
        if d.ncattrs() != s.ncattrs() + ["timezone"] or not d.getncattr("history").endswith(s.getncattr("history")):
            problems.append("global attribute list or history")
        if d.getncattr("timezone") != TIMEZONE:
            problems.append("timezone")
        if not d.dimensions["Time"].isunlimited() or len(d.dimensions["Time"]) != len(s.dimensions["Time"]):
            problems.append("Time dimension")
        for vname, var in s.variables.items():
            out = d.variables[vname]
            if out.dtype != var.dtype or out.dimensions != var.dimensions or out.ncattrs() != var.ncattrs():
                problems.append(f"variable {vname} type, dimensions or attribute list")
            for a in var.ncattrs():
                if not np.array_equal(np.asarray(var.getncattr(a)), np.asarray(out.getncattr(a))):
                    problems.append(f"variable {vname} attribute {a}")
            if np.asarray(out[:]).tobytes() != np.ascontiguousarray(var[:, r0:r1, c0:c1]).tobytes():
                problems.append(f"variable {vname} values")
    return problems


def weather_description(steps, cells, lat, lon):
    files = "; ".join(f"{name}.nc, {WEATHER_NAMES[name][1][0].lower()}{WEATHER_NAMES[name][1][1:]}"
                      for name in WEATHER_VARIABLES)
    return (
        f"SCOUT's WRF-Chem 4.5.1 forecast of 2025-07-06 00:00 UTC over Chicago, the weather the scout.routing "
        f"package reads: five NetCDF files, {steps} hourly steps from 2025-07-06 00:00 to 2025-07-08 00:00 UTC "
        f"on its 1 km Lambert conformal grid, cut to the {cells[0]} by {cells[1]} cells around SCOUT's Chicago "
        f"road graph (latitude {lat[0]:.2f} to {lat[1]:.2f}, longitude {lon[0]:.2f} to {lon[1]:.2f}): {files}. "
        f"Each file's global attribute timezone ({TIMEZONE}) is the time zone the package reads a start time in. "
        f'Read one with curio_load_data("{WEATHER_ID}", part="RAIN.nc"), or its path with '
        f'curio_data_path("{WEATHER_ID}", part="RAIN.nc"). From SCOUT, {SCOUT_URL}, {ROUTING}/weather_data/, '
        f"{PERMISSION}."
    )


def crop_weather(scout, G, catalog, report):
    base = Path(scout) / ROUTING / "weather_data"
    with nc.Dataset(base / "RAIN.nc") as ds:
        ds.set_auto_maskandscale(False)
        xlat, xlong = np.asarray(ds.variables["XLAT"][:]), np.asarray(ds.variables["XLONG"][:])
    problems = []
    if not (np.all(xlat == xlat[0]) and np.all(xlong == xlong[0])):
        problems.append("XLAT or XLONG changes over time")
    rows, cols, covered, extent = weather_window(G, xlat[0], xlong[0])
    if not covered:
        problems.append("a graph node's nearest grid cell is outside the window")
    lat, lon = xlat[0, rows[0]:rows[1], cols[0]:cols[1]], xlong[0, rows[0]:rows[1], cols[0]:cols[1]]
    lat_range, lon_range = [float(lat.min()), float(lat.max())], [float(lon.min()), float(lon.max())]
    cells = [rows[1] - rows[0], cols[1] - cols[0]]
    files = {}
    for name in WEATHER_VARIABLES:
        src, dst = base / f"{name}.nc", weather_file(catalog, name)
        with nc.Dataset(src) as s:
            same_grid = (np.array_equal(np.asarray(s.variables["XLAT"][0]), xlat[0])
                         and np.array_equal(np.asarray(s.variables["XLONG"][0]), xlong[0]))
        if not same_grid:
            problems.append(f"{name}.nc is on another grid")
        crop_weather_file(src, dst, name, rows, cols)
        file_problems = check_weather_file(src, dst, rows, cols)
        problems += [f"{name}.nc: {p}" for p in file_problems]
        files[f"{name}.nc"] = {"bytes": dst.stat().st_size, "sha256": sha256(dst), "problems": file_problems}
    write_weather_bundle(catalog, {name: WEATHER_NAMES[name][0] for name in WEATHER_VARIABLES})
    write_manifest(catalog, WEATHER_ID, name="SCOUT Chicago weather, 6 July 2025", fmt="bundle",
                   data_file=WEATHER_INDEX,
                   description=weather_description(int(xlat.shape[0]), cells, lat_range, lon_range),
                   tags=WEATHER_TAGS)
    report["weather"] = {
        "graph_extent": extent,
        "south_north": [rows[0], rows[1] - 1], "west_east": [cols[0], cols[1] - 1],
        "cells": cells, "time_steps": int(xlat.shape[0]),
        "latitude_range": lat_range, "longitude_range": lon_range,
        "every_node_nearest_cell_inside": covered,
        "files": files,
        "bytes": sum(f["bytes"] for f in files.values()),
    }
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--scout", required=True, help="a SCOUT checkout at SCOUT_COMMIT")
    parser.add_argument("--catalog", default=str(CATALOG), help="the catalog folder to write the weather into (datasets/)")
    parser.add_argument("--fixtures", default=str(FIXTURES), help="the folder to write the roads into (the proof's fixtures)")
    parser.add_argument("--report", help="write every check as JSON here")
    args = parser.parse_args()
    paths = [f"{ROUTING}/weather_data/{v}.nc" for v in WEATHER_VARIABLES] + [GRAPH_PICKLE, ROADS_LAYER]
    check_scout_checkout(args.scout, paths)
    with gzip.open(Path(args.scout) / GRAPH_PICKLE, "rb") as f:
        G = pickle.load(f)  # SCOUT's own file, checked above; Curio keeps no pickle
    report = {"scout_commit": SCOUT_COMMIT, "scout_files": blob_ids(paths),
              "networkx": nx.__version__, "netCDF4": nc.__version__, "pyarrow": pa.__version__}
    problems = crop_weather(args.scout, G, args.catalog, report)
    problems += crop_roads(args.scout, G, args.fixtures, report)
    report["problems"] = problems
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("weather", "roads")}, indent=2))
    if problems:
        print("FAILED:\n  " + "\n  ".join(problems[:40]))
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
