#!/usr/bin/env python3
"""Write ``docs/examples/data/shape-cnn.npz``, the weights example 27's network classifies with.

Example 27 (``docs/examples/27-pytorch-shape-classifier.json``) draws 60
pictures of circles, squares and triangles and sorts them with a tiny
convolutional network in PyTorch. This trains that network on 1,500 other
pictures drawn the same way and keeps its weights as float32 arrays named as
its ``state_dict`` names them, which ``np.load(..., allow_pickle=False)`` reads.

The pictures and the network are the example's own: this runs the ``draw``
function of its ``shape-pictures`` node and the ``TinyCNN`` class of its
``shape-classifier`` node, so the three cannot drift apart. It trains on the
CPU, seeded, on one thread; on another machine a rerun can differ in the last
bits of the weights, where its float sums run in another order.

    python scripts/build_example_shape_classifier.py

AUTHORING-ONLY tooling: it needs torch, which Curio's image carries, and it
writes the weights file only.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "docs" / "examples" / "27-pytorch-shape-classifier.json"
WEIGHTS_FILE = REPO_ROOT / "docs" / "examples" / "data" / "shape-cnn.npz"

#: The training pictures' seed, not the example's own (27), so the network
#: never sees the pictures the example shows.
SEED = 2701
PICTURES = 1500
EPOCHS = 40
BATCH = 50
#: The example's own pictures: its seed and how many it draws.
EXAMPLE_SEED = 27
EXAMPLE_PICTURES = 60


def node_code(node_id: str) -> str:
    """The code of example 27's node *node_id*."""
    dataflow = json.loads(EXAMPLE.read_text(encoding="utf-8"))["dataflow"]
    return next(node["content"] for node in dataflow["nodes"] if node["id"] == node_id)


def definitions(code: str, names: set[str], namespace: dict) -> dict:
    """*namespace* once *code*'s top-level definitions and assignments of *names* have run in it."""
    kept = [
        statement for statement in ast.parse(code).body
        if (isinstance(statement, (ast.FunctionDef, ast.ClassDef)) and statement.name in names)
        or (isinstance(statement, ast.Assign)
            and any(getattr(target, "id", None) in names for target in statement.targets))
    ]
    exec(compile(ast.Module(body=kept, type_ignores=[]), str(EXAMPLE), "exec"), namespace)
    return namespace


def pictures(draw, shapes: list[str], count: int, seed: int):
    """*count* pictures as the example draws them, shapes in turn, as float32
    tensors from 0 to 1, with the index of each one's shape."""
    import torch

    rng = np.random.default_rng(seed)
    labels = np.arange(count) % len(shapes)
    images = np.stack([draw(shapes[label], rng) for label in labels])
    return torch.from_numpy(images.astype(np.float32).transpose(0, 3, 1, 2) / 255), torch.from_numpy(labels)


def main() -> int:
    import torch

    torch.manual_seed(SEED)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)

    drawing = definitions(node_code("shape-pictures"), {"SHAPES", "SIZE", "draw"}, {"np": np})
    network = definitions(node_code("shape-classifier"), {"SHAPES", "TinyCNN"}, {"torch": torch})
    shapes = drawing["SHAPES"]
    images, labels = pictures(drawing["draw"], shapes, PICTURES, SEED)

    model = network["TinyCNN"]()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.003)
    shuffle = torch.Generator().manual_seed(SEED)
    for epoch in range(1, EPOCHS + 1):
        model.train()
        total = 0.0
        for batch in torch.randperm(PICTURES, generator=shuffle).split(BATCH):
            loss = torch.nn.functional.cross_entropy(model(images[batch]), labels[batch])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total += loss.item() * len(batch)
        print(f"epoch {epoch}: loss {total / PICTURES:.4f}")

    model.eval()
    shown, truth = pictures(drawing["draw"], shapes, EXAMPLE_PICTURES, EXAMPLE_SEED)
    with torch.no_grad():
        right = (model(shown).argmax(dim=1) == truth).sum().item()
    np.savez(WEIGHTS_FILE, **{name: value.numpy() for name, value in model.state_dict().items()})
    print(f"wrote {WEIGHTS_FILE.relative_to(REPO_ROOT)} ({WEIGHTS_FILE.stat().st_size} bytes); "
          f"it names {right} of the example's {EXAMPLE_PICTURES} pictures right")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
