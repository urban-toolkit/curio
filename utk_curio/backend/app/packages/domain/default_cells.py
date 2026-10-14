"""The cell a model package's node opens with when its template ships none, and the node a downloaded model gets.

A model package's template names its own ``source`` when its node has code of
its own (Deep Umbra's Accumulated Shadow). A template that ships none
(DDRNet23-Slim's Image Segmentation, the node of a model downloaded from the
Discovery Catalog) opens with the cell Curio writes for the package's model
type (``application/starters.py``):

- ``semantic-segmentation``: the model loaded by its id, then
  ``curio_segment``, which labels each image's pixels. It runs as it is.
- ``image-to-image`` and ``node-regression``: the model loaded by its id, then
  a ``model.run`` skeleton naming each array the model's graph takes, with its
  element type and shape, for the node's author to fill from ``input_0``.

A model downloaded from the Discovery Catalog becomes a model package with one
template, :func:`model_template`, the same node DDRNet23-Slim's package ships.
"""

from __future__ import annotations

import json
from typing import Iterable

#: The model type whose node Curio writes in full.
SEGMENTATION = "semantic-segmentation"

#: The node of a segmentation model package.
_SEGMENTATION_TEMPLATE = {
    "behavior": "code",
    "category": "computation",
    "description": (
        "Label every pixel of each image with a Model Catalog model: drag a model onto the node to choose it. "
        "Input: a collection's rows, each with a path (Data Loading on street-level images). Output: the same "
        "rows with one column per class asked for (its share of the image's pixels, in percent), "
        "dominant_class, dominant_pct and an overlay_url a Simple View shows."
    ),
    "editor": "code",
    "engine": "python",
    "hasCode": True,
    "hasGrammar": False,
    "hasWidgets": False,
    "iconRef": "fa-solid:wand-magic-sparkles",
    "id": "image-segmentation",
    "inputPorts": [{"cardinality": "1", "types": ["GEODATAFRAME", "DATAFRAME"]}],
    "label": "Image Segmentation",
    "outputPorts": [{"cardinality": "1", "types": ["GEODATAFRAME"]}],
    "paletteOrder": 0,
}


def model_template(model_type: str) -> dict:
    """The template of a model package of *model_type* that Curio writes, as a
    manifest holds it: its node has no ``source``, so it opens with
    :func:`default_cell`. Only a segmentation model has one."""
    if model_type != SEGMENTATION:
        raise ValueError(f"Curio writes a node only for a {SEGMENTATION} model, not for {model_type!r}")
    return json.loads(json.dumps(_SEGMENTATION_TEMPLATE))


def model_loader_line(model_id: str) -> str:
    """The line node code loads the model package *model_id* with."""
    return f'model = curio_load_model("{model_id}")'


def segmentation_cell(model_id: str) -> str:
    """The cell of a segmentation model's node: it runs as it is."""
    return (
        f"{model_loader_line(model_id)}\n"
        "classes = None  # every class the model names\n"
        "\n"
        "return curio_segment(input_0, model, classes)\n"
    )


def _shape_text(shape) -> str:
    return "[" + ", ".join("?" if size is None else str(size) for size in shape) + "]"


def run_skeleton(model_id: str, inputs: Iterable | None) -> str:
    """The cell of an ``image-to-image`` or ``node-regression`` model's node:
    ``model.run`` with one entry for each of *inputs* (each with ``name``,
    ``dtype`` and ``shape``, as ``datasets.domain.onnx_model.graph_inputs``
    reads them), or an empty one when the graph could not be read."""
    lines = [model_loader_line(model_id), ""]
    listed = [item for item in (inputs or []) if getattr(item, "name", "")]
    if listed:
        lines.append("# The arrays the model reads: make each one from input_0.")
        lines.append("outputs = model.run({")
        for item in listed:
            notes = [note for note in (item.dtype, None if item.shape is None else _shape_text(item.shape)) if note]
            comment = f"  # {' '.join(notes)}" if notes else ""
            lines.append(f"    {json.dumps(item.name)}: ...,{comment}")
        lines.append("})")
    else:
        lines.append("# model.run takes {input name: array}, one array for each input of the model,")
        lines.append("# made from input_0.")
        lines.append("outputs = model.run({})")
    lines.append("")
    lines.append("return outputs[0]")
    return "\n".join(lines) + "\n"


def default_cell(model_id: str, model_type: str, inputs: Iterable | None = None) -> str:
    """The cell a node of a model package of *model_type* opens with when its
    template ships none: :func:`segmentation_cell`, else :func:`run_skeleton`
    over the model's *inputs*."""
    if model_type == SEGMENTATION:
        return segmentation_cell(model_id)
    return run_skeleton(model_id, inputs)
