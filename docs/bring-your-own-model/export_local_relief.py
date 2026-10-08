"""Export the Local Relief model to ONNX, and check the file against PyTorch.

The worked example of docs/BRINGING-MODELS.md. Local Relief stands in for the
network you trained: a PyTorch module that takes a raster of building heights
and returns, for each cell, how far it stands above the mean height of the
cells around it. Its weights are fixed, so you can check its answer by hand;
yours will be learnt, and everything below is the same for them.

Run it in a throwaway environment that has your training framework, not in
Curio's (Curio only ever needs onnxruntime):

    python -m venv export-env
    export-env/bin/pip install torch onnx onnxruntime numpy
    export-env/bin/python docs/bring-your-own-model/export_local_relief.py

It writes model.example.local-relief@1/files/local_relief.onnx next to this
file and exits with status 1 when a check fails. The committed file was made
with Python 3.12, torch 2.14.1, onnx 1.23.2, onnxruntime 1.30.0 and numpy 2.2.6.
"""

import sys
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch

HERE = Path(__file__).resolve().parent
OUT = HERE / "model.example.local-relief@1" / "files" / "local_relief.onnx"

#: The cells around a cell whose mean it is compared with: a WINDOW by WINDOW square.
WINDOW = 5

#: The input and output names. The node feeds and reads the graph by these.
INPUT = "height"
OUTPUT = "relief"


class LocalRelief(torch.nn.Module):
    """A height raster in, (1, 1, rows, columns) metres; each cell's height
    minus the mean of the WINDOW by WINDOW cells around it out, same shape.
    At the raster's edge the mean is of the cells that are there."""

    def __init__(self, window: int = WINDOW):
        super().__init__()
        self.mean = torch.nn.AvgPool2d(window, stride=1, padding=window // 2, count_include_pad=False)

    def forward(self, height):
        return height - self.mean(height)


def reference(height: np.ndarray, window: int = WINDOW) -> np.ndarray:
    """The same answer computed with numpy alone, cell by cell."""
    rows, cols = height.shape
    half = window // 2
    out = np.empty_like(height, dtype=np.float64)
    for r in range(rows):
        for c in range(cols):
            around = height[max(0, r - half):r + half + 1, max(0, c - half):c + half + 1]
            out[r, c] = height[r, c] - around.mean()
    return out


def export(model: torch.nn.Module) -> None:
    """Trace *model* once and write it as ONNX. Rows and columns are dynamic,
    so one file runs on a raster of any size."""
    model.eval()
    example = torch.zeros(1, 1, 64, 64)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows, cols = torch.export.Dim("rows", min=8), torch.export.Dim("cols", min=8)
    program = torch.onnx.export(
        model,
        (example,),
        input_names=[INPUT],
        output_names=[OUTPUT],
        dynamic_shapes={"height": {2: rows, 3: cols}},
        dynamo=True,
    )
    program.save(str(OUT), external_data=False)


def check() -> list[str]:
    """What is wrong with the written file, or nothing."""
    problems = []
    onnx.checker.check_model(onnx.load(str(OUT)))
    session = ort.InferenceSession(str(OUT), providers=["CPUExecutionProvider"])
    names_in = [i.name for i in session.get_inputs()]
    names_out = [o.name for o in session.get_outputs()]
    if names_in != [INPUT] or names_out != [OUTPUT]:
        problems.append(f"names: inputs {names_in}, outputs {names_out}; want [{INPUT}] and [{OUTPUT}]")

    model = LocalRelief().eval()
    rng = np.random.default_rng(0)
    # Sizes other than the traced one, a flat raster, and a single tall cell.
    cases = {
        "64 by 64 random": rng.uniform(0, 300, (64, 64)),
        "37 by 90 random": rng.uniform(0, 300, (37, 90)),
        "flat": np.full((20, 20), 12.0),
        "one tower": np.pad(np.array([[200.0]]), 9),
    }
    for name, height in cases.items():
        h = height.astype(np.float32)
        (got,) = session.run(None, {INPUT: h[None, None]})
        with torch.no_grad():
            want = model(torch.from_numpy(h)[None, None]).numpy()
        by_hand = reference(h)
        if np.abs(got - want).max() > 1e-4:
            problems.append(f"{name}: onnxruntime differs from PyTorch by {np.abs(got - want).max():.2e}")
        if np.abs(got[0, 0] - by_hand).max() > 1e-3:
            problems.append(f"{name}: onnxruntime differs from the numpy reference by {np.abs(got[0, 0] - by_hand).max():.2e}")
    return problems


if __name__ == "__main__":
    export(LocalRelief())
    found = check()
    for problem in found:
        print("FAIL", problem)
    print(f"wrote {OUT.relative_to(HERE.parent.parent)} ({OUT.stat().st_size} bytes)")
    sys.exit(1 if found else 0)
