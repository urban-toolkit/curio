#!/usr/bin/env python3
"""Export SCOUT's weather GNN to the ONNX graph Curio ships.

WHY
---
``models/model.scout.weather-gnn@1/files/weather_gnn.onnx`` is this export of
the checkpoint SCOUT's weather-aware routing loads
(``backend/models/routing/gnn/rain_model.pth``), so the Model Catalog runs the
GNN on onnxruntime with neither PyTorch nor PyTorch Geometric. SCOUT's model
(``NodeRegressor`` in ``models/routing/scripts/weight_calculation.py``) is two
GraphSAGE layers and a linear head: torch_geometric's ``SAGEConv`` with its
defaults, mean aggregation, is ``lin_l(mean of the neighbours) + lin_r(self)``.
The export writes the same arithmetic in plain torch, a ``scatter_add`` over
the edges for the mean, which the ONNX exporter turns into a ScatterElements
with ``reduction="add"``, so the graph takes any number of nodes and edges.

The script checks the graph against the plain-torch module on a random
graph, and, when torch_geometric is installed (SCOUT's own environment), the
plain-torch module against SCOUT's ``NodeRegressor``: it fails when they
differ by more than ``TOLERANCE``.

HOW
---
Needs a Python with torch, onnx and onnxruntime:

    python scripts/export_scout_weather_gnn_onnx.py \\
        --checkpoint ../scout/backend/models/routing/gnn/rain_model.pth \\
        --out models/model.scout.weather-gnn@1/files/weather_gnn.onnx

The graph's inputs are ``x``, ``(nodes, 7)`` float32, a road node's latitude,
longitude, rain, temperature, wind speed, wind direction and humidity, and
``edge_index``, ``(2, edges)`` int64, each edge's source and target node; its
output ``weather`` is ``(nodes, 5)``: rain, temperature, humidity, wind speed
and wind direction at each node, in SCOUT's order.
"""

from __future__ import annotations

import argparse
import os

import numpy as np

#: The most an output of the ONNX graph may differ from torch's. The sums
#: run in another order on onnxruntime; the export measured about 1e-5 on
#: outputs of order 300 (temperatures in kelvin).
TOLERANCE = 1e-3

IN_CHANNELS, HIDDEN, OUT_CHANNELS = 7, 64, 5


def sage_module():
    import torch

    class Sage(torch.nn.Module):
        """torch_geometric's ``SAGEConv(aggr="mean")`` in plain torch."""

        def __init__(self, in_channels, out_channels):
            super().__init__()
            self.lin_l = torch.nn.Linear(in_channels, out_channels)
            self.lin_r = torch.nn.Linear(in_channels, out_channels, bias=False)

        def forward(self, x, edge_index):
            source, target = edge_index[0], edge_index[1]
            index = target.unsqueeze(1).expand(-1, x.shape[1])
            total = torch.zeros_like(x).scatter_add(0, index, x.index_select(0, source))
            ones = torch.ones_like(target, dtype=x.dtype)
            count = torch.zeros(x.shape[0], dtype=x.dtype).scatter_add(0, target, ones)
            mean = total / count.clamp(min=1).unsqueeze(1)
            return self.lin_l(mean) + self.lin_r(x)

    class NodeRegressor(torch.nn.Module):
        """SCOUT's ``NodeRegressor``, keeping its parameter names."""

        def __init__(self):
            super().__init__()
            self.conv1 = Sage(IN_CHANNELS, HIDDEN)
            self.conv2 = Sage(HIDDEN, HIDDEN)
            self.lin = torch.nn.Linear(HIDDEN, OUT_CHANNELS)

        def forward(self, x, edge_index):
            x = torch.relu(self.conv1(x, edge_index))
            x = torch.relu(self.conv2(x, edge_index))
            return self.lin(x)

    return NodeRegressor()


def random_graph(nodes=500, edges=1400, seed=0):
    """Node features shaped like SCOUT's (Chicago coordinates and weather)
    and edges with repeats and nodes that nothing points to."""
    rng = np.random.default_rng(seed)
    x = np.column_stack([
        rng.uniform(41.85, 41.91, nodes), rng.uniform(-87.68, -87.60, nodes),
        rng.exponential(0.5, nodes), rng.uniform(295, 305, nodes),
        rng.uniform(0, 8, nodes), rng.uniform(0, 360, nodes), rng.uniform(40, 90, nodes),
    ]).astype(np.float32)
    edge_index = rng.integers(0, nodes - 20, size=(2, edges)).astype(np.int64)
    return x, edge_index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--checkpoint", required=True, help="SCOUT's rain_model.pth")
    parser.add_argument("--out", required=True, help="the .onnx file to write")
    args = parser.parse_args()

    import onnxruntime as ort
    import torch

    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    state = checkpoint["model_state_dict"]
    model = sage_module()
    model.load_state_dict(state)
    model.eval()

    x, edge_index = random_graph()
    with torch.no_grad():
        expected = model(torch.from_numpy(x), torch.from_numpy(edge_index)).numpy()

    try:
        from torch_geometric.nn import SAGEConv  # noqa: F401
    except ImportError:
        print("  torch_geometric is not installed: the plain-torch module is not checked against SCOUT's")
    else:
        import torch.nn.functional as F

        class ScoutNodeRegressor(torch.nn.Module):  # SCOUT's class, verbatim
            def __init__(self, in_channels, hidden_channels, out_channels=5):
                super().__init__()
                self.conv1 = SAGEConv(in_channels, hidden_channels)
                self.conv2 = SAGEConv(hidden_channels, hidden_channels)
                self.lin = torch.nn.Linear(hidden_channels, out_channels)

            def forward(self, x, edge_index):
                x = F.relu(self.conv1(x, edge_index))
                x = F.relu(self.conv2(x, edge_index))
                return self.lin(x)

        scout = ScoutNodeRegressor(IN_CHANNELS, HIDDEN)
        scout.load_state_dict(state)
        scout.eval()
        with torch.no_grad():
            theirs = scout(torch.from_numpy(x), torch.from_numpy(edge_index)).numpy()
        diff = float(np.abs(theirs - expected).max())
        print(f"  plain torch vs SCOUT's NodeRegressor: max difference {diff:.2e}")
        if diff > TOLERANCE:
            raise SystemExit(f"the plain-torch module differs from SCOUT's by {diff}")

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    export_kwargs = dict(
        input_names=["x", "edge_index"],
        output_names=["weather"],
        dynamic_axes={"x": {0: "nodes"}, "edge_index": {1: "edges"}, "weather": {0: "nodes"}},
        opset_version=17,
    )
    try:
        torch.onnx.export(model, (torch.from_numpy(x), torch.from_numpy(edge_index)), out,
                          dynamo=False, **export_kwargs)
    except TypeError:  # a torch older than 2.5 has no dynamo switch
        torch.onnx.export(model, (torch.from_numpy(x), torch.from_numpy(edge_index)), out, **export_kwargs)

    session = ort.InferenceSession(out, providers=["CPUExecutionProvider"])
    for seed, (nodes, edges) in enumerate([(500, 1400), (37, 0), (3000, 9000)]):
        gx, gei = random_graph(nodes, edges, seed=seed) if edges else (random_graph(nodes, 2)[0],
                                                                       np.zeros((2, 0), np.int64))
        with torch.no_grad():
            want = model(torch.from_numpy(gx), torch.from_numpy(gei)).numpy()
        (got,) = session.run(None, {"x": gx, "edge_index": gei})
        diff = float(np.abs(got - want).max())
        print(f"  onnxruntime vs torch, {nodes} nodes and {edges} edges: max difference {diff:.2e}")
        if diff > TOLERANCE:
            raise SystemExit(f"the ONNX graph differs from torch by {diff}")
    print(f"  -> {out} ({os.path.getsize(out) / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
