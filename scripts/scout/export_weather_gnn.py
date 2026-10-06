"""Export SCOUT's weather GNN to ONNX and check it against torch.

SCOUT (https://github.com/urban-toolkit/scout) predicts five weather values at
every node of the road graph it routes on with a small graph network,
`NodeRegressor` in `backend/models/routing/scripts/weight_calculation.py`: two
GraphSAGE layers (`SAGEConv`, mean aggregation, ReLU) and a linear head.
`GNN_weight_calculations` loads its weights from
`backend/models/routing/gnn/rain_model.pth`. The other file there,
`GNN_model.pth`, is loaded by nothing: only a training cell of SCOUT's notebook
names it, and the notebook's loading lines for it are commented out.

Curio runs the network as an ONNX file through onnxruntime (package
`scout.routing@1`, Model Catalog model `model.scout.weather-gnn@1`), so Curio's environment
never takes torch. This script makes that file once, in a throwaway environment
with SCOUT's torch stack (SCOUT's `backend/requirements.txt`):

    Python 3.9.23
    torch 2.2.2, torch-geometric 2.6.1, numpy 1.23.5
    onnx 1.17.0, onnxruntime 1.19.2
    (SCOUT's weight_calculation.py also imports networkx 3.2.1, geopandas 1.0.1,
    shapely 2.0.1 and scipy 1.13.1)

    python scripts/scout/export_weather_gnn.py --scout <SCOUT checkout>

It writes the model into the Model Catalog as `model.scout.weather-gnn@1`, with
its manifest, a `node-regression` model (the repository's `models/`, or
`--models <folder>`); `--out <file>` writes the ONNX file alone, elsewhere.

What it does:

1. Checks that the checkout holds SCOUT's `weight_calculation.py` and both `.pth`
   files as committed (scout_checkout.py), and says how the two checkpoints differ.
2. Imports SCOUT's own `weight_calculation.py`, builds its `NodeRegressor` and loads
   `rain_model.pth`'s `model_state_dict` into it, every key used.
3. Exports it with `torch.onnx.export` (TorchScript, opset OPSET): inputs `x`
   (float32, nodes x 7: latitude, longitude, RAIN, T2, WSPD10, WDIR10, RH2, as
   `prepare_node_features_and_edges` builds them) and `edge_index` (int64,
   2 x edges: source and target node rows, as SCOUT builds them from the graph's
   edges), output `prediction` (float32, nodes x 5: RAIN, T2, RH2, WSPD10,
   WDIR10, the order SCOUT reads them in). The node and edge counts are dynamic.
4. Checks onnxruntime against torch on graphs of other sizes than the one traced:
   repeated edges, nodes without edges, a graph with no edges at all.
5. With `--inputs <npz>` (written by reference_routing.py: the `x`, `edge_index`
   and torch `prediction` of SCOUT's own run on the proof's road graph and
   weather), checks onnxruntime against both that prediction and torch rerun here.

With `--onnx-only`, it imports no torch and checks an existing ONNX file against
the npz's torch prediction with numpy and onnxruntime only, as Curio runs it.

It exits with status 1 when a check fails. `--report` writes every number as JSON.
In the environment above every run writes the same bytes.
"""

import argparse
import collections
import contextlib
import importlib.util
import io
import json
import platform
import sys
from pathlib import Path

import numpy as np

from scout_checkout import (BLOBS, MODELS, ROUTING, SCOUT_COMMIT, WEATHER_GNN, blob_ids, check_scout_checkout,
                            model_file, sha256, write_model_manifest)

WEIGHT_CALCULATION = f"{ROUTING}/scripts/weight_calculation.py"
CHECKPOINT = f"{ROUTING}/gnn/rain_model.pth"
UNUSED_CHECKPOINT = f"{ROUTING}/gnn/GNN_model.pth"
OPSET = 17
INPUT_FEATURES = ("latitude", "longitude", "RAIN", "T2", "WSPD10", "WDIR10", "RH2")
OUTPUTS = ("RAIN", "T2", "RH2", "WSPD10", "WDIR10")
# Tolerance of onnxruntime against torch, both float32: the two sum a node's
# neighbours in different orders, so they may differ by float32 rounding of
# outputs as large as T2's (about 300 K).
ABS_TOLERANCE = 1e-4
REL_TOLERANCE = 1e-5


def load_scout_module(scout):
    path = Path(scout) / WEIGHT_CALCULATION
    spec = importlib.util.spec_from_file_location("scout_weight_calculation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_checkpoint(torch, path):
    # SCOUT saves the optimizer state and the training split with the weights, so
    # it loads the whole pickle (torch 2.2's default); the file is pinned above.
    return torch.load(path, map_location="cpu")


def describe_checkpoints(torch, scout):
    used = load_checkpoint(torch, Path(scout) / CHECKPOINT)
    unused = load_checkpoint(torch, Path(scout) / UNUSED_CHECKPOINT)
    a, b = used["model_state_dict"], unused["model_state_dict"]
    same_keys = list(a) == list(b)
    return used, {
        "keys": sorted(used),
        "epoch": int(used["epoch"]),
        "in_channels": int(used["in_channels"]), "out_channels": int(used["out_channels"]),
        "train_nodes": int(used["train_idx"].numel()), "val_nodes": int(used["val_idx"].numel()),
        "parameters": {k: list(v.shape) for k, v in a.items()},
        "GNN_model.pth": {
            "keys": sorted(unused), "epoch": int(unused["epoch"]),
            "same_parameter_names_and_shapes": same_keys and all(a[k].shape == b[k].shape for k in a),
            "max_abs_weight_difference": (
                max(float((a[k] - b[k]).abs().max()) for k in a) if same_keys else None),
            "train_nodes": int(unused["train_idx"].numel()),
        },
    }


def build_model(torch, module, state):
    in_channels = state["conv1.lin_l.weight"].shape[1]
    hidden = state["conv1.lin_l.weight"].shape[0]
    out_channels = state["lin.weight"].shape[0]
    model = module.NodeRegressor(in_channels, hidden_channels=hidden, out_channels=out_channels)
    missing, unexpected = model.load_state_dict(state, strict=True)
    model.eval()
    return model, (in_channels, hidden, out_channels)


def random_graph(rng, nodes, edges, isolated=0, repeats=0):
    """Features shaped like SCOUT's (Chicago coordinates, plausible weather) and random edges."""
    x = np.column_stack([
        rng.uniform(41.85, 41.90, nodes), rng.uniform(-87.67, -87.61, nodes),
        rng.uniform(0, 5, nodes), rng.uniform(290, 305, nodes), rng.uniform(0, 12, nodes),
        rng.uniform(0, 360, nodes), rng.uniform(30, 100, nodes),
    ]).astype(np.float32)
    linked = max(nodes - isolated, 1)
    edge_index = rng.integers(0, linked, size=(2, edges)).astype(np.int64)
    if repeats and edges:
        edge_index = np.concatenate([edge_index, edge_index[:, :repeats]], axis=1)
    return x, edge_index


def run_torch(torch, model, x, edge_index):
    with torch.no_grad():
        return model(torch.from_numpy(x), torch.from_numpy(edge_index)).numpy()


def onnx_session(path):
    import onnxruntime as ort

    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def run_onnx(session, x, edge_index):
    return session.run(["prediction"], {"x": x, "edge_index": edge_index})[0]


def compare(a, b):
    diff = np.abs(a.astype(np.float64) - b.astype(np.float64))
    scale = np.maximum(np.abs(b.astype(np.float64)), 1.0)
    return {
        "shape": list(a.shape),
        "max_abs_diff": float(diff.max()) if diff.size else 0.0,
        "max_abs_diff_per_output": [float(d) for d in diff.max(axis=0)] if diff.size else [],
        "max_rel_diff": float((diff / scale).max()) if diff.size else 0.0,
        "ok": bool(a.shape == b.shape and np.all(diff <= ABS_TOLERANCE + REL_TOLERANCE * np.abs(b))),
    }


def export(torch, model, in_channels, path):
    rng = np.random.default_rng(0)
    x, edge_index = random_graph(rng, 40, 90)
    buffer = io.BytesIO()
    with contextlib.redirect_stdout(io.StringIO()):
        torch.onnx.export(
            model, (torch.from_numpy(x), torch.from_numpy(edge_index)), buffer,
            input_names=["x", "edge_index"], output_names=["prediction"],
            dynamic_axes={"x": {0: "nodes"}, "edge_index": {1: "edges"}, "prediction": {0: "nodes"}},
            opset_version=OPSET, do_constant_folding=True)
    import onnx

    proto = onnx.load_from_string(buffer.getvalue())
    proto.doc_string = (
        "SCOUT's weather GNN (NodeRegressor: two SAGEConv mean layers with ReLU and a linear head), "
        f"from {CHECKPOINT} at SCOUT {SCOUT_COMMIT}.")
    meta = {
        "source": f"SCOUT {SCOUT_COMMIT} {CHECKPOINT} (git blob {BLOBS[CHECKPOINT]}), model_state_dict",
        "made_by": "curio scripts/scout/export_weather_gnn.py",
        "input_x": "float32 [nodes, 7]: " + ", ".join(INPUT_FEATURES) + " at each node",
        "input_edge_index": "int64 [2, edges]: source and target node rows; messages go from source to target",
        "output_prediction": "float32 [nodes, 5]: " + ", ".join(OUTPUTS) + " at each node",
        "torch": torch.__version__,
    }
    for key, value in meta.items():
        entry = proto.metadata_props.add()
        entry.key, entry.value = key, value
    onnx.checker.check_model(proto, full_check=True)
    data = proto.SerializeToString()
    Path(path).write_bytes(data)
    return data


def inspect_onnx(path):
    import onnx

    proto = onnx.load(str(path))

    def dims(value):
        return [d.dim_param or d.dim_value for d in value.type.tensor_type.shape.dim]

    params = sum(int(np.prod(t.dims)) for t in proto.graph.initializer)
    return {
        "bytes": Path(path).stat().st_size, "sha256": sha256(path),
        "ir_version": proto.ir_version,
        "opsets": {o.domain or "ai.onnx": o.version for o in proto.opset_import},
        "inputs": {i.name: dims(i) for i in proto.graph.input},
        "outputs": {o.name: dims(o) for o in proto.graph.output},
        "ops": dict(sorted(collections.Counter(n.op_type for n in proto.graph.node).items())),
        "initializer_values": params,
        "metadata": {p.key: p.value for p in proto.metadata_props},
    }


def shape_checks(torch, model, session):
    rng = np.random.default_rng(1)
    cases = {
        "1 node, 1 self edge": random_graph(rng, 1, 1),
        "2 nodes, no edges": random_graph(rng, 2, 0),
        "17 nodes, 5 without edges, repeated edges": random_graph(rng, 17, 30, isolated=5, repeats=10),
        "1000 nodes, 3000 edges": random_graph(rng, 1000, 3000),
        "30000 nodes, 34000 edges, 100 repeated": random_graph(rng, 30000, 34000, isolated=200, repeats=100),
    }
    return {name: compare(run_onnx(session, x, e), run_torch(torch, model, x, e))
            for name, (x, e) in cases.items()}


def real_input_checks(npz_path, session, torch=None, model=None):
    data = np.load(npz_path)
    x, edge_index, prediction = data["x"], data["edge_index"], data["prediction"]
    onnx_out = run_onnx(session, x, edge_index)
    result = {"file": str(npz_path), "nodes": int(x.shape[0]), "edges": int(edge_index.shape[1]),
              "onnx_vs_scout_run": compare(onnx_out, prediction)}
    if torch is not None:
        rerun = run_torch(torch, model, x, edge_index)
        result["torch_rerun_vs_scout_run_identical"] = bool(np.array_equal(rerun, prediction))
        result["onnx_vs_torch_rerun"] = compare(onnx_out, rerun)
    return result


def write_gnn_manifest(models):
    """The Model Catalog manifest of the exported file: a ``node-regression``
    model, the task #740 (komar41) added for a graph in and values per node out."""
    write_model_manifest(
        models, WEATHER_GNN, name="SCOUT weather GNN (weather at road nodes)", task="node-regression",
        tags=["weather", "routing", "gnn", "graphsage", "roads", "scout", "onnx"],
        description=(
            "SCOUT's weather graph network: two GraphSAGE layers with mean aggregation and a linear head that "
            "predict five weather values at every node of a road graph from the WRF weather at the node and its "
            "neighbours. Inputs x (float32, nodes by 7: " + ", ".join(INPUT_FEATURES) + ") and edge_index "
            "(int64, 2 by edges: the source and target row of each edge); output prediction (float32, nodes by "
            "5: " + ", ".join(OUTPUTS) + "); node and edge counts are free. Exported once from SCOUT's "
            f"{CHECKPOINT} by scripts/scout/export_weather_gnn.py. The Weather Routing node of scout.routing@1 "
            "runs it to weigh each road before routing. Used with the permission of SCOUT's authors."
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--scout", help="a SCOUT checkout at SCOUT_COMMIT (not needed with --onnx-only)")
    parser.add_argument("--models", default=str(MODELS), help="the Model Catalog folder to write into (models/)")
    parser.add_argument("--out", help="write the ONNX file here alone, or with --onnx-only check this file")
    parser.add_argument("--inputs", action="append", default=[],
                        help="npz of x, edge_index and prediction from SCOUT's run (repeatable)")
    parser.add_argument("--onnx-only", action="store_true", help="check the ONNX file with onnxruntime only")
    parser.add_argument("--report", help="write every number as JSON here")
    args = parser.parse_args()
    into_models = not args.out
    if into_models:
        args.out = str(model_file(args.models))
        if not args.onnx_only:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    import onnxruntime

    report = {"python": platform.python_version(), "machine": platform.machine(),
              "numpy": np.__version__, "onnxruntime": onnxruntime.__version__}
    ok = True
    if args.onnx_only:
        session = onnx_session(args.out)
        report["onnx"] = {"bytes": Path(args.out).stat().st_size, "sha256": sha256(args.out)}
        report["real_inputs"] = [real_input_checks(p, session) for p in args.inputs]
        ok = all(r["onnx_vs_scout_run"]["ok"] for r in report["real_inputs"])
    else:
        if not args.scout:
            parser.error("--scout is needed to export")
        import torch
        import torch_geometric

        paths = [WEIGHT_CALCULATION, CHECKPOINT, UNUSED_CHECKPOINT]
        check_scout_checkout(args.scout, paths)
        torch.manual_seed(0)
        module = load_scout_module(args.scout)
        checkpoint, report["checkpoint"] = describe_checkpoints(torch, args.scout)
        model, sizes = build_model(torch, module, checkpoint["model_state_dict"])
        report.update({"scout_commit": SCOUT_COMMIT, "scout_files": blob_ids(paths),
                       "torch": torch.__version__, "torch_geometric": torch_geometric.__version__,
                       "model": dict(zip(("in_channels", "hidden_channels", "out_channels"), sizes))})
        first = export(torch, model, sizes[0], args.out)
        if into_models:
            write_gnn_manifest(args.models)
        again = export(torch, model, sizes[0], str(args.out) + ".again")
        Path(str(args.out) + ".again").unlink()
        report["export_repeats_bytes"] = first == again
        report["onnx"] = inspect_onnx(args.out)
        session = onnx_session(args.out)
        report["shapes"] = shape_checks(torch, model, session)
        report["real_inputs"] = [real_input_checks(p, session, torch, model) for p in args.inputs]
        ok = (report["export_repeats_bytes"] and all(c["ok"] for c in report["shapes"].values())
              and all(r["onnx_vs_scout_run"]["ok"] and r["onnx_vs_torch_rerun"]["ok"]
                      and r["torch_rerun_vs_scout_run_identical"] for r in report["real_inputs"]))
    report["ok"] = ok
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not ok:
        print("FAILED")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
