"""The cell a model package's node opens with when its template ships none.

A model package's template names its own ``source`` when its node has code of
its own: DDRNet23-Slim's Image Segmentation, and the node of a model
downloaded from the Discovery Catalog, call the Segmentation package's
``segment_images``; Deep Umbra's Accumulated Shadow calls its package's
module. A template that ships none (a person's own package) opens with
:func:`run_skeleton` (``application/starters.py``): the model loaded by its
id, its ONNX file (``model.path``) opened in an onnxruntime session on the
CPU, then a ``session.run`` skeleton naming each array the model's graph
takes, with its element type and shape, for the node's author to fill from
``input_0``. A new model type's node is its package's own source, never a
cell of its own here.
"""

from __future__ import annotations

import json
from typing import Iterable


def model_loader_line(model_id: str) -> str:
    """The line node code loads the model package *model_id* with."""
    return f'model = curio_load_model("{model_id}")'


def _shape_text(shape) -> str:
    return "[" + ", ".join("?" if size is None else str(size) for size in shape) + "]"


def run_skeleton(model_id: str, inputs: Iterable | None) -> str:
    """The cell of a model package's node whose template ships no
    ``source``: the model's ONNX file (``model.path``) opened in an
    onnxruntime session on the CPU, then ``session.run`` with one entry for
    each of *inputs* (each with ``name``, ``dtype`` and ``shape``, as
    ``datasets.domain.onnx_model.graph_inputs`` reads them), or an empty one
    when the graph could not be read."""
    lines = [
        "import onnxruntime as ort",
        "",
        model_loader_line(model_id),
        'session = ort.InferenceSession(model.path, providers=["CPUExecutionProvider"])',
        "",
    ]
    listed = [item for item in (inputs or []) if getattr(item, "name", "")]
    if listed:
        lines.append("# The arrays the model reads: make each one from input_0.")
        lines.append("outputs = session.run(None, {")
        for item in listed:
            notes = [note for note in (item.dtype, None if item.shape is None else _shape_text(item.shape)) if note]
            comment = f"  # {' '.join(notes)}" if notes else ""
            lines.append(f"    {json.dumps(item.name)}: ...,{comment}")
        lines.append("})")
    else:
        lines.append("# session.run(None, ...) takes {input name: array}, one array for each input")
        lines.append("# of the model, made from input_0.")
        lines.append("outputs = session.run(None, {})")
    lines.append("")
    lines.append("return outputs[0]")
    return "\n".join(lines) + "\n"
