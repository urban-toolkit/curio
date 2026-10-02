#!/usr/bin/env python
"""Write the synthetic segmentation graph the model fixtures index weights to.

WHY
    The Hugging Face model fixtures record the Hub's real answers (searches,
    file lists, ``config.json``) but no one's weights: each weights file is
    indexed to a synthetic stand-in, as storage fixtures index images to a
    synthetic JPEG. This one is a real ONNX graph, so a test can run it: one
    4x4, stride-4 convolution from ``pixel_values`` [1, 3, H, W] to ``logits``
    [1, LABELS, H/4, W/4], the shape a SegFormer export has. Its weights are
    seeded noise; its answers mean nothing.

USAGE
    pip install onnx numpy   # once; neither is a Curio dependency
    python scripts/make_synthetic_segmentation_onnx.py [labels]

    ``labels`` defaults to 150, ADE20K's count, which the recorded SegFormer
    export's config.json names.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

OUT = (
    Path(__file__).resolve().parents[1]
    / "utk_curio" / "backend" / "tests" / "test_discovery" / "fixtures"
    / "huggingface-models" / "synthetic-segmentation.onnx"
)


def build(labels: int) -> onnx.ModelProto:
    rng = np.random.default_rng(7)
    weight = numpy_helper.from_array(rng.standard_normal((labels, 3, 4, 4)).astype(np.float32), "weight")
    bias = numpy_helper.from_array(np.zeros((labels,), dtype=np.float32), "bias")
    conv = helper.make_node("Conv", ["pixel_values", "weight", "bias"], ["logits"], kernel_shape=[4, 4], strides=[4, 4])
    graph = helper.make_graph(
        [conv], "curio-synthetic-segmentation",
        [helper.make_tensor_value_info("pixel_values", TensorProto.FLOAT, [1, 3, "height", "width"])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, labels, "h4", "w4"])],
        initializer=[weight, bias],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], producer_name="curio-fixtures")
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    OUT.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(build(count), str(OUT))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {count} labels)")
