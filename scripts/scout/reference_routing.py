"""Run SCOUT's own weather routing on Curio's cuts of its data and record the routes it finds.

SCOUT (https://github.com/urban-toolkit/scout) routes with
`calculate_weather_route` in `backend/models/routing/scripts/weather_routing.py`.
This script runs that function, unchanged, in a throwaway environment with
SCOUT's stack (the one export_weather_gnn.py lists), on the road graph and
weather that crop_routing_data.py cuts, and records what it returns and the files
it writes as the JSON fixture Curio's `scout.routing@1` proof compares with.

SCOUT's function reads fixed paths under its backend folder, so the script lays
one out per run, in a work folder:

    models/routing/scripts/   SCOUT's four modules, as committed
    models/routing/gnn/       rain_model.pth, as committed
    models/routing/weather_data/<VAR>.nc     the weather cuts
    data/osm/processed/chicago/roads.pkl.gz  the road graph rebuilt from the
                                             Parquet cut (a pickle only here,
                                             because SCOUT's loader reads one)
    data/served/vector/baselayer_roads.geojson  the roads layer SCOUT's example
                                             data layer cuts from roads.feather
                                             (server.py: `gdf.cx`, geometry only,
                                             written as GeoJSON); SCOUT routes
                                             inside its bounds

Each case runs in a fresh process with the arguments of SCOUT's weather routing
example (`backend/data/dataflows/4833827e401c4e01b041e02481fdacd4.json`: origin,
destination, start time, rain and wind weights, outputs C and D), changing only
what the case says:

- `default`: the example itself, mode "Default weights" (K is not read);
- `custom-k1`, `custom-k2`, `custom-k3`: mode "Custom weights" with K = 1, 2, 3;
- `single-factor`: mode "Single-factor weights", SCOUT's third mode;
- `default-later`, `custom-k3-later`: the same at LATER_TIME, when it rains;
- `loader-time`: the example and then `default-later` in one process.

It records, from the function's own variables when it returns or raises (a trace
on that one frame), each route's node ids, SCOUT's metrics, the files SCOUT
wrote, and the error SCOUT raised. A torch forward hook records the GNN's input
and output. It also checks, per route, that the route is the only shortest path
for the edge weight it minimizes (or, for K shortest paths, that the first K + 1
path weights strictly increase), and how far the next path is: a search that
visits nodes in another order, or weights a little off, still finds these routes.

Validation (`--report`):
- `--full`: `default` and `custom-k3` again on SCOUT's whole graph and whole
  weather files: the cut must give the same GNN input and output bit for bit and
  the same routes and metrics.
- `--onnx <file>`: the crop cases again with the GNN's output replaced by
  onnxruntime's on the same input: the routes must not change.

The SCOUT bugs the port fixes, as this run shows them, are under `scout_bugs`.

    python scripts/scout/reference_routing.py --scout <SCOUT checkout> --work <scratch folder> \\
        --out routing_reference.json [--report report.json] [--full] [--onnx <file>]

It reads the weather cut from the repository's `datasets/` (or `--catalog
<folder>`) and the road graph cut from the proof's fixture folder,
`utk_curio/backend/tests/test_packages/fixtures/scout_routing/` (or `--fixtures
<folder>`). It exits with status 1 when a check fails.
"""

import argparse
import ast
import contextlib
import copy
import gzip
import hashlib
import io
import itertools
import json
import os
import pickle
import platform
import shutil
import subprocess
import sys
import time as clock
import traceback
from pathlib import Path

from scout_checkout import (BLOBS, CATALOG, FIXTURES, ROAD_EDGES_FILE, ROAD_NODES_FILE, ROUTING, SCOUT_COMMIT,
                            WEATHER_IDS, WEATHER_VARIABLES, blob_ids, check_scout_checkout, data_file, git_blob_id,
                            sha256)

MODULES = ("__init__.py", "weather_routing.py", "weight_calculation.py", "load_static.py",
           "calculate_isochrones.py")
CHECKPOINT = f"{ROUTING}/gnn/rain_model.pth"
EXAMPLE_DATAFLOW = "backend/data/dataflows/4833827e401c4e01b041e02481fdacd4.json"
FRONTEND_EXAMPLE = "frontend/src/examples/weatherRoutingComparisonWorkflow.ts"
ROADS_LAYER = "backend/data/osm/processed/chicago/roads.feather"
GRAPH_PICKLE = "backend/data/osm/processed/chicago/roads.pkl.gz"
SERVER = "backend/server.py"
# SCOUT turns a start time into a weather time index as minutes since
# 2025-07-06T00:00 over 15, plus 1. It rains over the routing box at index 17.
LATER_TIME = "2025-07-06T04:00:00"
LOADED_LINE = "Loaded trained GNN model."
# Which edge attribute each SCOUT route minimizes.
FASTEST, WEIGHTED = "fastest-route", "weighted-route"


def criterion(weight_type):
    if weight_type == FASTEST:
        return "travel_time"
    if weight_type == WEIGHTED:
        return "total_weight"
    return weight_type.replace("-aware-route", "") + "_weight"


# The example's arguments, read from SCOUT's saved dataflow.

def example_arguments(scout):
    flow = json.loads((Path(scout) / EXAMPLE_DATAFLOW).read_text())
    code_node = next(n for n in flow["nodes"] if "calculate_weather_route" in n["data"].get("code", ""))
    layer = next(n for n in flow["nodes"] if n["type"] == "dataLayerNode")["data"]["value"]["data_layer"]
    widgets = {w["variable"]: w["value"] for w in code_node["data"]["widgetOutputs"]}
    names = {}
    for statement in ast.parse(code_node["data"]["code"]).body:
        if isinstance(statement, ast.Assign):
            names[statement.targets[0].id] = ast.literal_eval(statement.value)
    call = {"datafile": names["datafile"], "input": names["input"], "outputs": names["outputs"],
            "origin_": widgets["origin"], "destination_": widgets["destination"], "mode": widgets["mode"],
            "K": widgets["k"], "time_": widgets["time"], "rain": widgets["rain"], "wind": widgets["wind"]}
    return call, layer["roi"]


def cases(example):
    def call(**changes):
        c = copy.deepcopy(example)
        c.update(changes)
        return c

    later = call(time_=LATER_TIME)
    return {
        "default": [call()],
        "custom-k1": [call(mode="Custom weights", K=1)],
        "custom-k2": [call(mode="Custom weights", K=2)],
        "custom-k3": [call(mode="Custom weights", K=3)],
        "single-factor": [call(mode="Single-factor weights")],
        "default-later": [later],
        "custom-k3-later": [call(mode="Custom weights", K=3, time_=LATER_TIME)],
        "loader-time": [call(), later],
    }


# Work folders laid out like SCOUT's backend.

def scout_roads_layer(scout, roi, path):
    """SCOUT's data layer node for OSM roads (server.py: crop_gdf, select_features, to_file)."""
    import geopandas as gpd

    gdf = gpd.read_feather(Path(scout) / ROADS_LAYER)
    xmin, ymin, xmax, ymax = map(float, roi["value"])
    gdf_cut = gdf.cx[xmin:xmax, ymin:ymax]
    gdf_out = gdf_cut[["geometry"]]  # the example asks for no attributes
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf_out.to_file(path, driver="GeoJSON")


def lay_out(scout, work, weather_files, graph_source, roi, roads_layer):
    if work.exists():
        shutil.rmtree(work)
    scripts = work / "models/routing/scripts"
    scripts.mkdir(parents=True)
    for name in MODULES:
        shutil.copyfile(Path(scout) / ROUTING / "scripts" / name, scripts / name)
    (work / "models/routing/gnn").mkdir(parents=True)
    shutil.copyfile(Path(scout) / CHECKPOINT, work / "models/routing/gnn/rain_model.pth")
    weather = work / "models/routing/weather_data"
    weather.mkdir(parents=True)
    for name in WEATHER_VARIABLES:
        (weather / f"{name}.nc").symlink_to(Path(weather_files[name]).resolve())
    graph = work / "data/osm/processed/chicago/roads.pkl.gz"
    graph.parent.mkdir(parents=True)
    if isinstance(graph_source, Path):
        graph.symlink_to(graph_source)
    else:
        with gzip.open(graph, "wb") as f:
            pickle.dump(graph_source, f)
    (work / "data/served/vector").mkdir(parents=True)
    (work / "data/served/metric").mkdir(parents=True)
    shutil.copyfile(roads_layer, work / "data/served/vector/baselayer_roads.geojson")


# One case, in its own process.

def order_digest(items):
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()


def number(value):
    return None if value is None else float(value)


def path_checks(G, orig, dest, route, attr, cache, k_index=None, k=None):
    """Whether *route* is the only answer for minimizing *attr*, and its margin.

    The weights are summed as networkx sums them in SCOUT's run (the GNN-based
    weights are float32), so a tie here is a tie SCOUT's search met.
    """
    import networkx as nx
    import osmnx as ox

    def k_shortest(count):
        if (attr, count) not in cache:
            cache[(attr, count)] = list(ox.routing.k_shortest_paths(G, orig, dest, count, weight=attr))
        return cache[(attr, count)]

    result = {"criterion": attr, "weight": number(nx.path_weight(G, route, weight=attr))}
    if k_index is None:
        shortest = list(itertools.islice(nx.all_shortest_paths(G, orig, dest, weight=attr, method="dijkstra"), 2))
        result["only_shortest_path"] = len(shortest) == 1 and shortest[0] == route
        best_two = k_shortest(2)
        if len(best_two) == 2:
            result["gap_to_next_path"] = number(
                nx.path_weight(G, best_two[1], weight=attr) - nx.path_weight(G, best_two[0], weight=attr))
    else:
        paths = k_shortest(k + 1)
        weights = [nx.path_weight(G, p, weight=attr) for p in paths]
        result["k_shortest_weights"] = [number(w) for w in weights]
        result["k_order_strict"] = all(a < b for a, b in zip(weights, weights[1:]))
        result["matches_k_shortest"] = len(paths) > k_index and paths[k_index] == route
        if k_index + 1 < len(weights):
            result["gap_to_next_path"] = number(weights[k_index + 1] - weights[k_index])
    return result


def read_outputs(work):
    files = {}
    for path in sorted((work / "data/served/metric").glob("*.csv")):
        files[f"metric/{path.name}"] = path.read_text()
    for path in sorted((work / "data/served/vector").glob("route_*.geojson")):
        data = json.loads(path.read_text())
        files[f"vector/{path.name}"] = [
            {"properties": f["properties"], "geometry_type": f["geometry"]["type"],
             "coordinates": len(f["geometry"]["coordinates"]) if f["geometry"]["type"] == "LineString" else
             f["geometry"]["coordinates"]}
            for f in data["features"]]
    return files


def clear_outputs(work):
    for path in (work / "data/served/metric").glob("*.csv"):
        path.unlink()
    for path in (work / "data/served/vector").glob("route_*.geojson"):
        path.unlink()


def worker(spec_path):
    spec = json.loads(Path(spec_path).read_text())
    work = Path(spec["work"])
    os.chdir(work)  # SCOUT's code opens ./models/... and ./data/...
    sys.path.insert(0, str(work))
    import networkx as nx
    import numpy as np
    import torch

    session = None
    if spec.get("onnx"):
        import onnxruntime as ort

        session = ort.InferenceSession(spec["onnx"], providers=["CPUExecutionProvider"])
    gnn_calls = []

    def gnn_hook(module, args, output):
        if type(module).__name__ != "NodeRegressor":
            return None
        record = {"x": args[0].detach().cpu().numpy(), "edge_index": args[1].detach().cpu().numpy(),
                  "prediction": output.detach().cpu().numpy()}
        gnn_calls.append(record)
        if session is None:
            return None
        onnx_out = session.run(["prediction"], {"x": record["x"], "edge_index": record["edge_index"]})[0]
        record["onnx"] = onnx_out
        return torch.from_numpy(onnx_out)

    torch.nn.modules.module.register_module_forward_hook(gnn_hook)
    from models.routing.scripts import weather_routing as wr

    target = wr.calculate_weather_route.__code__
    results = []
    for n, call in enumerate(spec["calls"]):
        clear_outputs(work)
        seen = {}

        def local_trace(frame, event, arg):
            if event == "return":
                seen.update(frame.f_locals)
            return local_trace

        def global_trace(frame, event, arg):
            return local_trace if frame.f_code is target else None

        out, error, started = io.StringIO(), None, clock.time()
        calls_before = len(gnn_calls)
        sys.settrace(global_trace)
        try:
            with contextlib.redirect_stdout(out):
                wr.calculate_weather_route(**call)
        except Exception as exc:  # SCOUT's own errors are part of what it gives
            tb = traceback.extract_tb(exc.__traceback__)[-1]
            error = {"type": type(exc).__name__, "message": str(exc),
                     "where": f"{Path(tb.filename).name}:{tb.lineno}", "code": tb.line}
        finally:
            sys.settrace(None)
        seconds = clock.time() - started
        G = seen["G"]
        routes, cache = [], {}
        for route in seen.get("routes_data", []):
            attr = criterion(route["weight_type"])
            k_index = route["route_index"] if call["mode"] == "Custom weights" and route["weight_type"] != FASTEST else None
            entry = {
                "weight_type": route["weight_type"], "route_index": route["route_index"],
                "nodes": [int(v) for v in route["route"]],
                "distance": number(route["distance"]), "duration": number(route["duration"]),
                "rain_exposure": number(route["rain_exposure"]), "heat_exposure": number(route["heat_exposure"]),
                "wind_exposure": number(route["wind_exposure"]),
                "humidity_exposure": number(route["humidity_exposure"]),
                "length_m": number(nx.path_weight(G, route["route"], weight="length")),
            }
            entry["checks"] = path_checks(G, seen["orig_node"], seen["dest_node"], route["route"], attr, cache,
                                          k_index, call["K"] if k_index is not None else None)
            routes.append(entry)
        gnn = gnn_calls[calls_before:]
        npz = Path(spec["npz_prefix"] + f"-{n}.npz")
        if gnn:
            arrays = {k: v for k, v in gnn[-1].items()}
            np.savez_compressed(npz, **arrays)
        loader = wr._data_loader
        results.append({
            "call": call, "seconds": round(seconds, 1), "error": error,
            "loaded_trained_model": LOADED_LINE in out.getvalue(),
            "checkpoint_unchanged": git_blob_id(work / "models/routing/gnn/rain_model.pth") == BLOBS[CHECKPOINT],
            "time_index": int(seen["time"]), "loader_time": int(loader.time),
            "loader_rain_slice_sha256": hashlib.sha256(
                np.ascontiguousarray(np.asarray(loader.rain_data[0], dtype=np.float32)).tobytes()).hexdigest(),
            "roads_layer_bounds": [number(seen[k]) for k in ("xmin", "ymin", "xmax", "ymax")],
            "graph": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(),
                      "node_order_sha256": order_digest([int(v) for v in G.nodes]),
                      "edge_order_sha256": order_digest([[int(u), int(v), int(k)] for u, v, k in G.edges(keys=True)])},
            "orig_node": int(seen["orig_node"]), "dest_node": int(seen["dest_node"]),
            "trip_time_seconds": [number(t) for t in seen["trip_times_seconds"]],
            "weather_conditions": seen["weather_conditions"],
            "weights": {k: number(seen[k]) for k in ("rain_weight", "heat_weight", "wind_weight", "humidity_weight")},
            "routes": routes, "files": read_outputs(work),
            "gnn": None if not gnn else {
                "npz": str(npz), "nodes": int(gnn[-1]["x"].shape[0]), "edges": int(gnn[-1]["edge_index"].shape[1]),
                "x_sha256": hashlib.sha256(gnn[-1]["x"].tobytes()).hexdigest(),
                "edge_index_sha256": hashlib.sha256(gnn[-1]["edge_index"].tobytes()).hexdigest(),
                "prediction_sha256": hashlib.sha256(gnn[-1]["prediction"].tobytes()).hexdigest(),
                "prediction_mean": [float(v) for v in gnn[-1]["prediction"].astype(np.float64).mean(axis=0)],
                "onnx_max_abs_diff": (float(np.abs(gnn[-1]["onnx"].astype(np.float64)
                                                   - gnn[-1]["prediction"].astype(np.float64)).max())
                                      if "onnx" in gnn[-1] else None),
            },
            "stdout_tail": out.getvalue().splitlines()[-6:],
        })
    Path(spec["result"]).write_text(json.dumps(results, indent=1) + "\n")


def run_case(script, work, name, calls, out_dir, onnx=None):
    spec = {"work": str(work), "calls": calls, "onnx": str(onnx) if onnx else None,
            "result": str(out_dir / f"{name}.json"), "npz_prefix": str(out_dir / name)}
    spec_path = out_dir / f"{name}.spec.json"
    spec_path.write_text(json.dumps(spec, indent=1))
    log = out_dir / f"{name}.log"
    with open(log, "w") as f:
        done = subprocess.run([sys.executable, str(script), "--worker", str(spec_path)], cwd=str(work),
                              stdout=f, stderr=subprocess.STDOUT)
    if done.returncode != 0:
        raise SystemExit(f"case {name} failed, see {log}")
    return json.loads((out_dir / f"{name}.json").read_text())


# Comparisons.

def same_routes(a, b):
    return [r["nodes"] for r in a["routes"]] == [r["nodes"] for r in b["routes"]]


def metric_diff(a, b):
    keys = ("distance", "duration", "rain_exposure", "heat_exposure", "wind_exposure", "humidity_exposure",
            "length_m")
    diffs = [abs(ra[k] - rb[k]) for ra, rb in zip(a["routes"], b["routes"]) for k in keys]
    rel = [abs(ra[k] - rb[k]) / max(abs(rb[k]), 1.0) for ra, rb in zip(a["routes"], b["routes"]) for k in keys]
    return {"max_abs": max(diffs, default=0.0), "max_rel": max(rel, default=0.0)}


def checks_of(result):
    """Every route is the only one its criterion allows."""
    problems = []
    for r in result["routes"]:
        c = r["checks"]
        if "only_shortest_path" in c and not c["only_shortest_path"]:
            problems.append(f"{r['weight_type']} {r['route_index']}: another path is as short")
        if "k_order_strict" in c and not (c["k_order_strict"] and c["matches_k_shortest"]):
            problems.append(f"{r['weight_type']} {r['route_index']}: K shortest paths tie or differ")
    if not result["loaded_trained_model"] or not result["checkpoint_unchanged"]:
        problems.append("SCOUT did not load rain_model.pth as committed")
    return problems


def scout_bugs(results, validation):
    """The SCOUT bugs the port fixes, as this run shows them."""
    bugs = {}
    default = results.get("default", [None])[0]
    if default and not default["error"]:
        written = {}
        for name, features in default["files"].items():
            if name.startswith("vector/route_") and name not in ("vector/route_origin.geojson",
                                                                  "vector/route_destination.geojson"):
                for feature in features:
                    p = feature["properties"]
                    written[(p["weight_type"], p["route_index"])] = p["distance_m"]
        bugs["distance_m_holds_kilometres"] = {
            "what": ("SCOUT's route GeoJSON property distance_m holds the route's length in kilometres "
                     "(nx.path_weight(G, route, 'length') / 1000, the CSV's distance). The port's distance_m "
                     "is the length in metres, length_m below; SCOUT's km distance stays as it is."),
            "routes": [{"weight_type": r["weight_type"], "route_index": r["route_index"],
                        "scout_distance_m": written.get((r["weight_type"], r["route_index"])),
                        "distance": r["distance"], "length_m": r["length_m"]} for r in default["routes"]],
        }
    if "loader-time" in validation:
        bugs["loader_keeps_first_time"] = dict(
            what=("get_data_loader(time) makes one DataLoader per process with the first time it is given and "
                  "never updates it, so later calls' load_*_data return the first call's time step. In the GNN "
                  "path those arrays feed only train_GNN_model (not run: rain_model.pth exists); the GNN reads "
                  "the requested time through stitchDataset. So routes and metrics follow the requested time and "
                  "only the loader's own state is stale. The port reads the time each call asks for."),
            **validation["loader-time"])
    overflow = {}
    for name in ("default", "custom-k1", "custom-k2", "custom-k3", "single-factor", "custom-k3-later"):
        if name in results:
            r = results[name][0]
            overflow[name] = {"mode": r["call"]["mode"], "K": r["call"]["K"], "routes": len(r["routes"]),
                              "outputs": r["call"]["outputs"], "error": r["error"],
                              "files_written": sorted(r["files"])}
    bugs["more_routes_than_outputs"] = {
        "what": ("SCOUT names each route's metrics CSV after outputs[j], and each route group's GeoJSON too. "
                 "'Custom weights' makes 2K + 1 routes for rain and wind (K per factor, plus the fastest) and "
                 "'Single-factor weights' 3, so with the example's two names both raise IndexError after writing "
                 "C.csv and D.csv, before any route GeoJSON. Their routes in the cases are SCOUT's, read from the "
                 "function's variables when it raised. The port returns every route as a row of one table "
                 "instead of a list of names."),
        "cases": overflow,
    }
    bugs["time_read_as_quarter_hours"] = {
        "what": ("SCOUT's WRF files hold 49 hourly steps from 2025-07-06 00:00 UTC (their NCO history lists "
                 "hourly inputs), while time_to_global_index counts 15-minute steps from 2025-07-06T00:00 plus 1, "
                 "so SCOUT's 00:00 reads the 01:00 UTC step, its 04:00 the 17:00 UTC step, and each 15-minute "
                 "zone of a trip the next hour's. The cases record SCOUT as it runs: each case's time_index is "
                 "the step SCOUT read. The port reads a start time as local time in the weather's time zone and "
                 "takes the hourly UTC step it falls in."),
        "scout_steps": {name: [c["time_index"] for c in calls] for name, calls in results.items()},
    }
    bugs["bounds_check_compares_longitude_with_latitude"] = (
        "SCOUT checks the origin against the road graph's bounds with origin[1] > ymax, the longitude against "
        "the northern latitude, which never holds, so an origin north of the graph passes the check. The port "
        "checks the origin's latitude against ymax.")
    return bugs


def path_table(results):
    """Every distinct route's node ids, once: cases share routes (K=1 and 2 are K=3's first ones)."""
    paths, index = [], {}
    for calls in results.values():
        for result in calls:
            for route in result["routes"]:
                key = tuple(route["nodes"])
                if key not in index:
                    index[key] = len(paths)
                    paths.append(route["nodes"])
    return paths, index


def fixture_case(result, index):
    keep = ("call", "error", "time_index", "loader_time", "roads_layer_bounds", "graph", "orig_node", "dest_node",
            "trip_time_seconds", "weather_conditions", "weights", "files")
    out = {k: result[k] for k in keep}
    out["routes"] = [dict({"path": index[tuple(r["nodes"])]}, **{k: v for k, v in r.items() if k != "nodes"})
                     for r in result["routes"]]
    out["gnn"] = {k: v for k, v in result["gnn"].items() if k not in ("npz", "onnx_max_abs_diff")}
    return out


def versions():
    import geopandas
    import netCDF4
    import networkx
    import numpy
    import osmnx
    import pandas
    import pyogrio
    import scipy
    import sklearn
    import torch
    import torch_geometric

    return {"python": platform.python_version(), "machine": platform.machine(), "torch": torch.__version__,
            "torch_geometric": torch_geometric.__version__, "osmnx": osmnx.__version__,
            "networkx": networkx.__version__, "numpy": numpy.__version__, "pandas": pandas.__version__,
            "netCDF4": netCDF4.__version__, "geopandas": geopandas.__version__, "pyogrio": pyogrio.__version__,
            "gdal": pyogrio.__gdal_version_string__, "scipy": scipy.__version__, "scikit-learn": sklearn.__version__}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--scout", help="a SCOUT checkout at SCOUT_COMMIT")
    parser.add_argument("--catalog", default=str(CATALOG),
                        help="the catalog folder crop_routing_data.py wrote the weather into (datasets/)")
    parser.add_argument("--fixtures", default=str(FIXTURES),
                        help="the folder crop_routing_data.py wrote the road graph into (the proof's fixtures)")
    parser.add_argument("--work", help="a scratch folder for the work folders and logs")
    parser.add_argument("--out", help="the fixture JSON to write")
    parser.add_argument("--report", help="write the validation as JSON here")
    parser.add_argument("--full", action="store_true", help="also run on SCOUT's whole graph and weather")
    parser.add_argument("--onnx", help="also run with this ONNX file in place of the torch GNN")
    parser.add_argument("--only", action="append", help="run only these cases (for trying things)")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    paths = [f"{ROUTING}/scripts/{m}" for m in MODULES] + [CHECKPOINT, EXAMPLE_DATAFLOW, FRONTEND_EXAMPLE,
                                                           ROADS_LAYER, SERVER]
    if args.full:
        paths += [GRAPH_PICKLE] + [f"{ROUTING}/weather_data/{v}.nc" for v in WEATHER_VARIABLES]
    check_scout_checkout(args.scout, paths)
    sys.path.insert(0, str(Path(__file__).parent))
    from crop_routing_data import read_road_graph

    script = Path(__file__).resolve()
    work, catalog = Path(args.work), Path(args.catalog)
    logs = work / "runs"
    logs.mkdir(parents=True, exist_ok=True)
    example, roi = example_arguments(args.scout)
    roads_layer = work / "baselayer_roads.geojson"
    scout_roads_layer(args.scout, roi, roads_layer)
    fixtures = Path(args.fixtures)
    graph = read_road_graph(fixtures / ROAD_NODES_FILE, fixtures / ROAD_EDGES_FILE)
    cut_weather = {name: data_file(catalog, WEATHER_IDS[name]) for name in WEATHER_VARIABLES}
    lay_out(args.scout, work / "crop", cut_weather, graph, roi, roads_layer)
    if args.full:
        whole_weather = {name: Path(args.scout) / ROUTING / "weather_data" / f"{name}.nc" for name in WEATHER_VARIABLES}
        lay_out(args.scout, work / "full", whole_weather, Path(args.scout) / GRAPH_PICKLE, roi, roads_layer)
    all_cases = cases(example)
    names = args.only or list(all_cases)
    results, problems = {}, []
    for name in names:
        print(f"case {name}", flush=True)
        results[name] = run_case(script, work / "crop", name, all_cases[name], logs)
        for r in results[name]:
            problems += [f"{name}: {p}" for p in checks_of(r)]
    validation = {}
    if args.full:
        for name in [n for n in ("default", "custom-k3") if n in names]:
            print(f"case {name} on SCOUT's whole data", flush=True)
            full = run_case(script, work / "full", f"full-{name}", all_cases[name], logs)[0]
            crop = results[name][0]
            v = {"routes_identical": same_routes(crop, full), "metrics": metric_diff(crop, full),
                 "gnn_identical": all(crop["gnn"][k] == full["gnn"][k]
                                      for k in ("x_sha256", "edge_index_sha256", "prediction_sha256")),
                 "graph_order_identical": crop["graph"] == full["graph"],
                 "roads_layer_bounds_identical": crop["roads_layer_bounds"] == full["roads_layer_bounds"],
                 "error_identical": crop["error"] == full["error"], "files_identical": crop["files"] == full["files"]}
            validation[f"full-{name}"] = v
            if not (all(x for k, x in v.items() if k != "metrics") and v["metrics"]["max_abs"] == 0):
                problems.append(f"full-{name}: the cut changes SCOUT's result")
    if args.onnx:
        for name in [n for n in names if n != "loader-time"]:
            print(f"case {name} with the ONNX GNN", flush=True)
            onnx_run = run_case(script, work / "crop", f"onnx-{name}", all_cases[name], logs, Path(args.onnx))[0]
            torch_run = results[name][0]
            v = {"routes_identical": same_routes(onnx_run, torch_run), "metrics": metric_diff(onnx_run, torch_run),
                 "gnn_input_identical": onnx_run["gnn"]["x_sha256"] == torch_run["gnn"]["x_sha256"]
                 and onnx_run["gnn"]["edge_index_sha256"] == torch_run["gnn"]["edge_index_sha256"],
                 "gnn_onnx_max_abs_diff": onnx_run["gnn"]["onnx_max_abs_diff"],
                 "error_identical": onnx_run["error"] == torch_run["error"]}
            validation[f"onnx-{name}"] = v
            if not (v["routes_identical"] and v["gnn_input_identical"] and v["error_identical"]):
                problems.append(f"onnx-{name}: the ONNX GNN changes SCOUT's routes")
    if "loader-time" in results and "default-later" in results:
        first, second = results["loader-time"]
        fresh = results["default-later"][0]
        validation["loader-time"] = {
            "asked": [first["time_index"], second["time_index"]],
            "loader_kept": [first["loader_time"], second["loader_time"]],
            "second_call_routes_as_fresh_process": same_routes(second, fresh),
            "second_call_metrics_vs_fresh": metric_diff(second, fresh),
            "second_call_gnn_as_fresh_process": second["gnn"]["x_sha256"] == fresh["gnn"]["x_sha256"]
            and second["gnn"]["prediction_sha256"] == fresh["gnn"]["prediction_sha256"],
            "loader_slice_as_first_call": second["loader_rain_slice_sha256"] == first["loader_rain_slice_sha256"],
            "loader_slice_as_fresh_process": second["loader_rain_slice_sha256"] == fresh["loader_rain_slice_sha256"],
        }
    report = {"scout_commit": SCOUT_COMMIT, "scout_files": blob_ids(paths), "made_with": versions(),
              "validation": validation, "problems": problems,
              "seconds": {name: [r["seconds"] for r in rs] for name, rs in results.items()}}
    route_paths, index = path_table(results)
    fixture = {
        "about": ("Routes and metrics SCOUT's own calculate_weather_route gives on Curio's cut of SCOUT's road "
                  "graph and weather; written by curio scripts/scout/reference_routing.py. A route's node ids "
                  "are paths[route.path]."),
        "scout_commit": SCOUT_COMMIT, "scout_files": blob_ids(paths), "made_with": report["made_with"],
        # The Data Catalog files SCOUT's run read, by dataset id, and the road
        # graph's, by their name in the proof's fixture folder.
        "datasets": {dataset_id: sha256(data_file(catalog, dataset_id)) for dataset_id in WEATHER_IDS.values()},
        "road_graph": {name: sha256(fixtures / name) for name in (ROAD_NODES_FILE, ROAD_EDGES_FILE)},
        "example": {"arguments": example, "data_layer_roi": roi},
        "routing_box": results[names[0]][0]["roads_layer_bounds"],
        "cases": {name: [fixture_case(r, index) for r in rs] for name, rs in results.items()},
        "scout_bugs": scout_bugs(results, validation),
        "paths": route_paths,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(fixture, indent=1) + "\n")
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"validation": validation, "problems": problems, "seconds": report["seconds"]}, indent=2))
    if problems:
        print("FAILED")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
