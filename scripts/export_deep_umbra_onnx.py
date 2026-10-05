#!/usr/bin/env python3
"""Export SCOUT's Deep Umbra generator to the ONNX graph Curio ships.

WHY
---
``models/model.scout.deep-umbra@1/files/deep_umbra.onnx`` is this export of
the TensorFlow checkpoint SCOUT runs (``backend/models/shadow/tf_model``,
``ckpt-44``), so the Model Catalog runs Deep Umbra on onnxruntime with no
TensorFlow. SCOUT calls the generator with ``training=True``: every
BatchNorm normalizes a tile by its own statistics (resnet9 has no dropout).
tf2onnx cannot convert a FusedBatchNormV3 in training mode and silently
treats it as inference, which draws entirely different shadows, so the
export traces a BatchNorm that computes the batch statistics with plain ops.
The script then checks the graph against TensorFlow on synthetic height
tiles: it fails when they differ by more than ``TOLERANCE``.

HOW
---
Needs SCOUT's backend checkout and a Python with TensorFlow 2.12 (SCOUT's
own environment), tf2onnx, onnx and onnxruntime:

    python scripts/export_deep_umbra_onnx.py --scout ../scout/backend \\
        --out models/model.scout.deep-umbra@1/files/deep_umbra.onnx

The graph's inputs are ``height``, ``latitude`` and ``season``, each
``(1, 512, 512, 1)`` float32 (NHWC) normalized as SCOUT's
``normalize_input``; its output ``shadow`` is ``(1, 512, 512, 1)`` in -1..1.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

#: The most a pixel of the ONNX graph's output may differ from TensorFlow's,
#: on the -1..1 scale. Convolutions sum in another order on onnxruntime; the
#: export measured 0.02 at worst and a mean of about 1e-4.
TOLERANCE = 0.05


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scout", required=True, help="SCOUT's backend folder")
    parser.add_argument("--out", required=True, help="the .onnx file to write")
    args = parser.parse_args()
    out_path = os.path.abspath(args.out)

    import onnx
    import onnxruntime as ort
    import tensorflow as tf
    import tf2onnx

    scout = os.path.abspath(args.scout)
    sys.path.insert(0, os.path.join(scout, "models", "shadow", "scripts"))
    os.chdir(scout)  # get_deep_shadow restores 'models/shadow/tf_model'
    import deep_umbra

    generator = deep_umbra.get_deep_shadow().generator

    def batch_norm_on_batch_statistics(self, inputs, training=None):
        mean, variance = tf.nn.moments(inputs, axes=[0, 1, 2], keepdims=True)
        return (inputs - mean) * tf.math.rsqrt(variance + self.epsilon) * self.gamma + self.beta

    spec = [tf.TensorSpec((1, 512, 512, 1), tf.float32, name=name) for name in ("height", "latitude", "season")]

    @tf.function(input_signature=spec)
    def shadow(height, latitude, season):
        return generator([height, latitude, season], training=True)

    keras_call = tf.keras.layers.BatchNormalization.call
    tf.keras.layers.BatchNormalization.call = batch_norm_on_batch_statistics
    try:
        model, _ = tf2onnx.convert.from_function(shadow, input_signature=spec, opset=17)
    finally:
        tf.keras.layers.BatchNormalization.call = keras_call

    produced = model.graph.output[0].name
    for node in model.graph.node:
        node.output[:] = ["shadow" if name == produced else name for name in node.output]
    model.graph.output[0].name = "shadow"
    onnx.checker.check_model(model)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    onnx.save(model, out_path)

    session = ort.InferenceSession(out_path, providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(0)
    worst = 0.0
    for season in (-1.0, 0.0, 1.0):
        height = np.zeros((1, 512, 512, 1), np.float32)
        for _ in range(40):
            y, x = rng.integers(0, 480, 2)
            rows, cols = rng.integers(8, 40, 2)
            height[0, y:y + rows, x:x + cols, 0] = rng.integers(5, 120)
        feeds = {
            "height": height / 127.5 - 1,
            "latitude": np.full_like(height, (41.88 + 90) / 90.0 - 1),
            "season": np.full_like(height, season),
        }
        want = generator([feeds["height"], feeds["latitude"], feeds["season"]], training=True).numpy()
        got = session.run(None, feeds)[0]
        worst = max(worst, float(np.abs(want - got).max()))
    print(f"wrote {out_path}; largest difference from TensorFlow {worst:.2e}")
    return 0 if worst <= TOLERANCE else 1


if __name__ == "__main__":
    sys.exit(main())
