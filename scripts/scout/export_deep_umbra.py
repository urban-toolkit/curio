"""Export SCOUT's Deep Umbra shadow generator to ONNX and check it against SCOUT.

SCOUT (https://github.com/urban-toolkit/scout) predicts accumulated shadow with a
TensorFlow generator restored from
`backend/compute/accumulated_shadow_simulation/tf_model/ckpt-44`. Curio runs the
same generator as an ONNX file through onnxruntime: the Data Catalog dataset
`data.scout.deep-umbra@1`, which the package `scout.shadow@1` runs, so Curio's
environment never takes TensorFlow. This script made that file once, from a
SCOUT checkout, and checks it, and the package's port of SCOUT's code, against
SCOUT's own code and SCOUT's committed results.

It needs a throwaway environment that can restore the checkpoint, with SCOUT's
TensorFlow version (SCOUT's `backend/requirements.txt`). The committed file was
made with:

    Python 3.11.16
    tensorflow 2.12.0 (tensorflow-macos 2.12.0 on Apple silicon), keras 2.12.0
    numpy 1.23.5, protobuf 3.20.3
    tf2onnx 1.16.1, onnx 1.17.0, onnxruntime 1.26.0
    opencv-python-headless 4.7.0.72, matplotlib 3.10.9, pandas 2.3.3, pillow 12.3.0
    (SCOUT's deep_umbra.py imports the last four)

    python scripts/scout/export_deep_umbra.py --scout <SCOUT checkout> --out deep_umbra.onnx

In that environment every run writes the same bytes.

What it does:

1. Checks that the checkout holds SCOUT's files as committed at SCOUT_COMMIT: its
   `deep_umbra.py`, the checkpoint, and the tiles and metrics of SCOUT's shadow
   example (dataflow aedc4c6b73934b14979101108ee51f42, both scenarios run in summer).
2. Imports SCOUT's own `deep_umbra.py` and builds and restores the generator with
   its `get_deep_shadow()`, then checks that every generator variable was restored
   and every generator value in the checkpoint was used.
3. Exports the generator with tf2onnx: three float32 inputs of shape (1, 512, 512, 1)
   named `height`, `latitude` and `date`, in SCOUT's order, and one output `shadow`
   of the same shape, at fp32.
   SCOUT calls the generator with `training=True`, so each BatchNormalization layer
   normalizes with the mean and variance of the tile it is given, not with the
   moving averages stored in the checkpoint. The export keeps that: the layers are
   traced with momentum 0, so TensorFlow's fused batch norm carries an exponential
   average factor of 1.0, which tf2onnx turns into a normalization by the input's
   own mean and variance. Those statistics mix across a batch, so the batch is
   fixed at 1, as SCOUT feeds it: one tile per call.
4. Checks the ONNX file on SCOUT's committed height tiles (`A_rasters`,
   `B_rasters`) with SCOUT's latitude and date inputs:
   - the raw generator output, from the inputs SCOUT's `load_input_grid` and
     `normalize_input` build: ONNX against TensorFlow with `training=True`, and
     both against the same generator run in float64, from which ONNX must be no
     farther than TensorFlow's own float32 run is;
   - that ONNX is far from TensorFlow with `training=False`, and that an export
     made with scrambled moving averages gives the same output, so the file
     cannot be using the moving averages;
   - the inputs the package's port builds with numpy and Pillow
     (`packages/scout.shadow@1/sources/scout_shadow/deep_umbra.py`), against
     SCOUT's TensorFlow-built inputs;
   - the tiles and the mean and median accumulated shadow the port's
     `run_shadow_model` writes with onnxruntime, against SCOUT's committed
     `A_shadows`, `B_shadows` and metrics CSVs, and against SCOUT's own
     `run_shadow_model` rerun here.

With `--onnx-only --out <file>`, it imports no TensorFlow and checks an existing
ONNX file with the package's port and onnxruntime only, as Curio runs it,
against SCOUT's committed tiles and metrics.

It exits with status 1 when a check fails. `--report` writes every number as JSON.
"""

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import platform
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
PORT_SOURCES = REPO / "packages" / "scout.shadow@1" / "sources"

SCOUT_COMMIT = "b98369e50b2972c0fc22180f56da0ac99a98a545"
MODEL_DIR = "backend/compute/accumulated_shadow_simulation"
PROOF_DIR = "backend/data/dataflows/aedc4c6b73934b14979101108ee51f42_computed"
PROOF_TILES = (
    "16_16814_24355.png",
    "16_16814_24356.png",
    "16_16815_24355.png",
    "16_16815_24356.png",
)
# Git blob ids of the files this script reads, at SCOUT_COMMIT.
SCOUT_BLOBS = {
    f"{MODEL_DIR}/scripts/deep_umbra.py": "f398cfe72436af872c88ff395156594c1c7db91d",
    f"{MODEL_DIR}/tf_model/checkpoint": "a6903fa7f65ccc085d24c65df421271b74d29918",
    f"{MODEL_DIR}/tf_model/ckpt-44.index": "f8d822332060bbc708bc191a9d32db146f0b1fbe",
    f"{MODEL_DIR}/tf_model/ckpt-44.data-00000-of-00001": "456cc33d0a455806fd6057e37aa365fb89c2b709",
    f"{PROOF_DIR}/A_rasters/16_16814_24355.png": "6df4a2ac62bf936fb35a9e2bcc3ab60ea9950150",
    f"{PROOF_DIR}/A_rasters/16_16814_24356.png": "2b8ed251ea11c176911e82ba4e94876165a9c24c",
    f"{PROOF_DIR}/A_rasters/16_16815_24355.png": "78af7233fc008eb7667815ea2953de6c80b0d0fa",
    f"{PROOF_DIR}/A_rasters/16_16815_24356.png": "5a79dc189015064dff2b01db87e69a9d55490d61",
    f"{PROOF_DIR}/A_shadows/16_16814_24355.png": "5e91df11405730062e00f9cad9bde604d8539c91",
    f"{PROOF_DIR}/A_shadows/16_16814_24356.png": "fc723e811944e6eb832c99da7b5d5a4a5905bd42",
    f"{PROOF_DIR}/A_shadows/16_16815_24355.png": "28f2822d3af86603dabc4e284654942cc02c598b",
    f"{PROOF_DIR}/A_shadows/16_16815_24356.png": "98f3e25190f0196ed1283ba177b7afc9c57d0e2d",
    f"{PROOF_DIR}/A_shadows_metric.csv": "8877fd0f8b23f30bffc938417c3755f6036431a6",
    f"{PROOF_DIR}/B_rasters/16_16814_24355.png": "fa16d3c295de43087d8bce4793a18a246eddbecd",
    f"{PROOF_DIR}/B_rasters/16_16814_24356.png": "ef9abdac87c8538f069a27ddd588f959b79442ac",
    f"{PROOF_DIR}/B_rasters/16_16815_24355.png": "8ce0e2e64cc0fe53bbd2c40384522de0f3da0ee6",
    f"{PROOF_DIR}/B_rasters/16_16815_24356.png": "6f5d6c58dd3a48a85f8e6925374c150c9a0bb6b8",
    f"{PROOF_DIR}/B_shadows/16_16814_24355.png": "a9207768e0064f1489e84cc38e7e94e25e20c22e",
    f"{PROOF_DIR}/B_shadows/16_16814_24356.png": "c09c2d2af35ab0542498fc23cd1a499d47c2378b",
    f"{PROOF_DIR}/B_shadows/16_16815_24355.png": "f9c9080f9d8ec1d3d3d002fee3b640c1cc4d470e",
    f"{PROOF_DIR}/B_shadows/16_16815_24356.png": "f9cfdac6d0112ce08c999625e2bb65ee949ade63",
    f"{PROOF_DIR}/B_shadows_metric.csv": "2ff4b35b83b1d9faf22f81ef4b70835926e84f87",
}
SCENARIOS = ("A", "B")
# The season SCOUT's shadow example ran both scenarios with (its season widget).
SEASON = "summer"
INPUT_NAMES = ("height", "latitude", "date")
OUTPUT_NAME = "shadow"
INPUT_SHAPE = (1, 512, 512, 1)
DEFAULT_OPSET = 15

# Checks.
# On SCOUT's tiles, TensorFlow's float32 run of this generator is up to 0.016 from
# a float64 run of it, on a few pixels of its [-1, 1] output (0.00003 on average).
# So the ONNX output is held to TensorFlow's own distance from the float64 run, not
# to TensorFlow's float32 rounding.
FLOAT32_NOISE_FACTOR = 1.5  # ONNX's distance from float64, over TensorFlow float32's
# 0.016 of output moves those pixels by one or two gray levels after SCOUT's
# truncation to 8 bits.
GRAY_TOLERANCE = 2  # gray levels, any tile against SCOUT's committed tile
METRIC_TOLERANCE = 0.05  # minutes, mean and median against SCOUT's CSV
LATITUDE_TOLERANCE = 1e-6  # the port's normalized latitude against SCOUT's
MODE_SEPARATION = 0.5  # ONNX against TensorFlow training=False must differ by more


def load_port():
    """The package's port of SCOUT's ``deep_umbra.py``, ``scout_shadow.deep_umbra``,
    imported without writing bytecode into ``packages/``."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(PORT_SOURCES))
    from scout_shadow import deep_umbra

    return deep_umbra


def port_inputs(port, folder, season, zoom, i, j):
    """The generator's three inputs as the port builds them, (1, 512, 512, 1) each."""
    planes = port.normalize_input(*port.load_input_grid(str(folder), season, zoom, i, j))
    return tuple(plane.reshape(INPUT_SHAPE) for plane in planes)


def tiles_in(folder):
    """The tiles SCOUT's run_shadow_model predicts: every `<zoom>_<x>_<y>.png`, sorted."""
    tiles = []
    for path in sorted(Path(folder).glob("*.png")):
        try:
            zoom, i, j = (int(part) for part in path.stem.split("_"))
        except ValueError:
            continue
        tiles.append((path.name, zoom, i, j))
    return tiles


def crop(output):
    """The middle 256 by 256 of a (1, 512, 512, 1) output, the part SCOUT keeps."""
    return np.asarray(output)[:, 128:-128, 128:-128, :].reshape(256, 256)


def denormalized_height(height):
    """SCOUT's ``input_height`` from a normalized height input."""
    return (crop(height) + 1) * 127.5


def read_metrics(path):
    """SCOUT's metrics CSV: one row, mean then median accumulated shadow."""
    lines = Path(path).read_text().strip().splitlines()
    mean, median = (float(value) for value in lines[1].split(","))
    return mean, median


def metrics_of(vals):
    every = np.concatenate(vals)
    return float(np.mean(every)), float(np.median(every))


def gray_diff(a, b):
    """Largest gray-level difference between two 8-bit tiles, and pixels that differ."""
    d = np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16))
    return int(d.max()), int((d > 0).sum())


def raw_diff(a, b):
    """Largest and mean absolute difference between two generator outputs."""
    d = np.abs(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64))
    return float(d.max()), float(d.mean())


def git_blob_id(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def check_scout_checkout(scout):
    wrong = []
    for rel, blob in SCOUT_BLOBS.items():
        path = scout / rel
        if not path.is_file():
            wrong.append(f"{rel} is missing")
        elif git_blob_id(path) != blob:
            wrong.append(f"{rel} is not SCOUT's file at {SCOUT_COMMIT[:8]}")
    if wrong:
        raise SystemExit("The SCOUT checkout does not match:\n  " + "\n  ".join(wrong))


def onnx_session(model):
    import onnxruntime as ort

    return ort.InferenceSession(model, providers=["CPUExecutionProvider"])


def run_onnx(session, inputs):
    return session.run([OUTPUT_NAME], dict(zip(INPUT_NAMES, inputs)))[0]


def session_io(session):
    """The inputs and outputs an onnxruntime session reads and writes, with their shapes."""
    return (
        {i.name: list(i.shape) for i in session.get_inputs()},
        {o.name: list(o.shape) for o in session.get_outputs()},
    )


def inspect_onnx(path):
    """Size and digest of an ONNX file; with the onnx package, its opset, IR version and operators."""
    data = Path(path).read_bytes()
    info = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    try:
        import onnx
    except ImportError:
        return info

    model = onnx.load(str(path))
    graph = model.graph
    initializers = {t.name for t in graph.initializer}
    ops = {}
    for node in graph.node:
        ops[node.op_type] = ops.get(node.op_type, 0) + 1
    constant_stats = [
        node.name for node in graph.node
        if node.op_type == "BatchNormalization" and (node.input[3] in initializers or node.input[4] in initializers)
    ]

    info.update({
        "opset": {o.domain or "ai.onnx": o.version for o in model.opset_import},
        "ir_version": model.ir_version,
        "operators": dict(sorted(ops.items())),
        "batch_norms_with_stored_statistics": constant_stats,
        "weights": int(sum(int(np.prod(t.dims)) for t in graph.initializer)),
        "weight_types": sorted({onnx.TensorProto.DataType.Name(t.data_type) for t in graph.initializer}),
    })
    return info


# TensorFlow side: SCOUT's own code.

def load_scout_module(scout):
    path = scout / MODEL_DIR / "scripts" / "deep_umbra.py"
    spec = importlib.util.spec_from_file_location("deep_umbra", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def quiet():
    """SCOUT's code prints a line per file it reads and writes."""
    return contextlib.redirect_stdout(io.StringIO())


def restore_generator(du):
    """SCOUT's generator, built and restored by SCOUT's get_deep_shadow()."""
    tf = du.tf
    with quiet():
        generator = du.get_deep_shadow().generator
    checkpoint = tf.train.latest_checkpoint(str(Path(du.__file__).resolve().parent.parent / "tf_model"))
    stored = [
        name for name, _ in tf.train.list_variables(checkpoint)
        if name.startswith("generator/") and "OPTIMIZER_SLOT" not in name
    ]
    # Every generator variable has a value in the checkpoint ...
    tf.train.Checkpoint(generator=generator).restore(checkpoint).expect_partial().assert_existing_objects_matched()
    # ... and every generator value in the checkpoint has a variable.
    if len(stored) != len(generator.variables):
        raise SystemExit(f"The checkpoint holds {len(stored)} generator values for {len(generator.variables)} variables.")
    return generator, checkpoint, len(stored)


def float64_generator(du, generator):
    """SCOUT's generator in float64 with the restored weights, built as get_deep_shadow() builds it.

    Keras runs float64 batch norm unfused, from tf.nn.moments, with the same
    training=True arithmetic. Both float32 runs are measured against it.
    """
    tf = du.tf
    tf.keras.backend.set_floatx("float64")
    try:
        with quiet():
            down_stack, up_stack = du.get_generator_arch()
            model = du.Generator(512, 512, down_stack, up_stack, latitude=True, date=True,
                                 type="resnet9", attention=False)
    finally:
        tf.keras.backend.set_floatx("float32")
    model.set_weights([w.astype(np.float64) for w in generator.get_weights()])
    return model


def batch_norm_layers(generator):
    import tensorflow as tf

    return [layer for layer in generator.submodules if isinstance(layer, tf.keras.layers.BatchNormalization)]


def name_constants_in_use_order(model):
    """Names the constants tf2onnx made after the order the graph first uses them.

    tf2onnx numbers the names of the constants it makes, and merges equal ones,
    in an order that changes from run to run, so the same graph would get other
    names, and other bytes, from each export. Renamed, every run writes the same file.
    """
    graph = model.graph
    made = {t.name for t in graph.initializer if re.search(r"__\d+$", t.name)}
    names = {}
    for node in graph.node:
        for name in node.input:
            if name in made and name not in names:
                names[name] = f"const__{len(names)}"
    for name in sorted(made - set(names)):
        names[name] = f"const__{len(names)}"
    for tensor in graph.initializer:
        tensor.name = names.get(tensor.name, tensor.name)
    for node in graph.node:
        for k, name in enumerate(node.input):
            node.input[k] = names.get(name, name)
    for value in list(graph.input) + list(graph.value_info):
        value.name = names.get(value.name, value.name)
    every = [t.name for t in graph.initializer]
    if len(set(every)) != len(every):
        raise SystemExit("Renaming the constants made two of them share a name.")
    return model


def export_onnx(generator, opset):
    """The generator as an ONNX model, normalizing with each tile's own statistics."""
    import onnx
    import tensorflow as tf
    import tf2onnx

    layers = batch_norm_layers(generator)
    momenta = [layer.momentum for layer in layers]
    spec = [tf.TensorSpec(INPUT_SHAPE, tf.float32, name=name) for name in INPUT_NAMES]

    @tf.function(input_signature=spec)
    def deep_umbra(height, latitude, date):
        return {OUTPUT_NAME: generator([height, latitude, date], training=True)}

    try:
        for layer in layers:
            layer.momentum = 0.0
        with quiet():
            model, _ = tf2onnx.convert.from_function(deep_umbra, input_signature=spec, opset=opset)
    finally:
        for layer, momentum in zip(layers, momenta):
            layer.momentum = momentum
    name_constants_in_use_order(model)
    model.ir_version = onnx.helper.find_min_ir_version_for(list(model.opset_import), True)
    onnx.helper.set_model_props(model, {
        "source": f"urban-toolkit/scout {SCOUT_COMMIT[:8]} {MODEL_DIR}/tf_model/ckpt-44",
        "inputs": "height, latitude, date: SCOUT's normalized load_input_grid planes, (1, 512, 512, 1) each",
        "batch_norm": "each tile's own mean and variance, as SCOUT's training=True call",
    })
    onnx.checker.check_model(model)
    return model


def scout_inputs(du, folder, season, zoom, i, j):
    """The generator's inputs as SCOUT's predict_shadow builds them."""
    with quiet():
        height, latitude, date = du.normalize_input(*du.load_input_grid(str(folder), season, zoom, i, j))
    return tuple(np.array(t).reshape(INPUT_SHAPE) for t in (height, latitude, date))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scout", type=Path, required=True, help="a checkout of urban-toolkit/scout")
    parser.add_argument("--out", type=Path, required=True, help="the ONNX file to write (or check, with --onnx-only)")
    parser.add_argument("--work", type=Path, help="folder for the tiles the checks write (default: beside --out)")
    parser.add_argument("--report", type=Path, help="write every number as JSON")
    parser.add_argument("--opset", type=int, default=DEFAULT_OPSET)
    parser.add_argument("--onnx-only", action="store_true",
                        help="check an existing ONNX file with the package's port and onnxruntime only")
    args = parser.parse_args()

    scout = args.scout.resolve()
    work = (args.work or args.out.parent / "deep_umbra_check").resolve()
    work.mkdir(parents=True, exist_ok=True)
    check_scout_checkout(scout)
    proof = scout / PROOF_DIR
    port = load_port()
    report = {"scout_commit": SCOUT_COMMIT, "season": SEASON, "python": platform.python_version(),
              "platform": f"{platform.system()} {platform.machine()}"}
    failures = []

    import onnxruntime

    report["versions"] = {"numpy": np.__version__, "onnxruntime": onnxruntime.__version__}

    if args.onnx_only:
        du = generator = None
    else:
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
        du = load_scout_module(scout)
        tf = du.tf
        import onnx
        import tf2onnx

        report["versions"].update({"tensorflow": tf.__version__, "tf2onnx": tf2onnx.__version__, "onnx": onnx.__version__})
        generator, checkpoint, restored = restore_generator(du)
        report["checkpoint"] = {"path": checkpoint, "generator_values_restored": restored}
        layers = batch_norm_layers(generator)
        stored_stats = [(layer.moving_mean.numpy(), layer.moving_variance.numpy()) for layer in layers]

        model = export_onnx(generator, args.opset)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(model.SerializeToString())

        # TensorFlow in inference mode, from the checkpoint's moving averages,
        # before any training=True call updates them.
        inference = {}
        for prefix in SCENARIOS:
            rasters = proof / f"{prefix}_rasters"
            for name, zoom, i, j in tiles_in(rasters):
                inputs = scout_inputs(du, rasters, SEASON, zoom, i, j)
                inference[prefix, name] = generator(list(inputs), training=False).numpy()

        # The same export with scrambled moving averages.
        rng = np.random.default_rng(0)
        for layer in layers:
            layer.moving_mean.assign(rng.normal(0.0, 1.0, layer.moving_mean.shape).astype(np.float32))
            layer.moving_variance.assign(rng.uniform(0.5, 2.0, layer.moving_variance.shape).astype(np.float32))
        scrambled = onnx_session(export_onnx(generator, args.opset).SerializeToString())
        for layer, (mean, variance) in zip(layers, stored_stats):
            layer.moving_mean.assign(mean)
            layer.moving_variance.assign(variance)
        generator64 = float64_generator(du, generator)

    report["onnx"] = inspect_onnx(args.out)
    session = onnx_session(str(args.out))
    inputs_seen, outputs_seen = session_io(session)
    report["onnx"].update({"inputs": inputs_seen, "outputs": outputs_seen})
    if inputs_seen != {name: list(INPUT_SHAPE) for name in INPUT_NAMES}:
        failures.append(f"ONNX inputs are {inputs_seen}")
    if outputs_seen != {OUTPUT_NAME: list(INPUT_SHAPE)}:
        failures.append(f"ONNX outputs are {outputs_seen}")
    if report["onnx"].get("batch_norms_with_stored_statistics"):
        failures.append("ONNX batch norms read stored statistics: "
                        + ", ".join(report["onnx"]["batch_norms_with_stored_statistics"]))

    for prefix in SCENARIOS:
        rasters = proof / f"{prefix}_rasters"
        committed = proof / f"{prefix}_shadows"
        tiles = tiles_in(rasters)
        if [t[0] for t in tiles] != list(PROOF_TILES):
            failures.append(f"{prefix}: tiles are {[t[0] for t in tiles]}")
        result = {"tiles": {}}

        # The port's run_shadow_model, as SCOUT's example calls SCOUT's.
        port_tiles = work / f"port_{prefix}_shadows"
        start = time.perf_counter()
        port.run_shadow_model(str(rasters), SEASON, str(port_tiles), str(work / f"port_{prefix}_shadows_metric"), session)
        result["port_seconds_per_tile"] = (time.perf_counter() - start) / len(tiles)
        result["port_metrics"] = read_metrics(work / f"port_{prefix}_shadows_metric.csv")
        result["committed_metrics"] = read_metrics(proof / f"{prefix}_shadows_metric.csv")
        result["port_metrics_minutes_diff"] = [
            abs(v - r) for v, r in zip(result["port_metrics"], result["committed_metrics"])
        ]

        if du is not None:
            # SCOUT's own run_shadow_model, rerun here with TensorFlow.
            tf_tiles = work / f"tf_{prefix}_shadows"
            with quiet():
                du.run_shadow_model(str(rasters), SEASON, str(tf_tiles), str(work / f"tf_{prefix}_shadows_metric"))
            result["tensorflow_metrics"] = read_metrics(work / f"tf_{prefix}_shadows_metric.csv")
            vals64 = []

        for name, zoom, i, j in tiles:
            row = {}
            reference = np.asarray(Image.open(committed / name))
            ported = np.asarray(Image.open(port_tiles / name))
            row["port_vs_committed"] = gray_diff(ported, reference)

            if du is not None:
                ours = port_inputs(port, rasters, SEASON, zoom, i, j)
                scout_in = scout_inputs(du, rasters, SEASON, zoom, i, j)
                row["port_inputs_vs_scout"] = {
                    n: float(np.abs(a - b).max()) for n, a, b in zip(INPUT_NAMES, ours, scout_in)
                }
                trained = generator(list(scout_in), training=True).numpy()
                with quiet():
                    _, scout_prediction = du.predict_shadow(generator, str(rasters), SEASON, zoom, i, j)
                exact = generator64([x.astype(np.float64) for x in scout_in], training=True).numpy()
                same_inputs = run_onnx(session, scout_in)
                row["tf_call_equals_scout_predict_shadow"] = bool(np.array_equal(crop(trained), scout_prediction))
                # Raw generator outputs, (largest, mean) absolute difference, from SCOUT's inputs.
                row["raw_onnx_vs_tf"] = raw_diff(same_inputs, trained)
                row["raw_onnx_vs_tf_crop"] = raw_diff(crop(same_inputs), crop(trained))
                row["raw_tf_vs_float64"] = raw_diff(trained, exact)
                row["raw_onnx_vs_float64"] = raw_diff(same_inputs, exact)
                row["raw_onnx_vs_tf_inference_mode"] = raw_diff(same_inputs, inference[prefix, name])
                row["raw_onnx_vs_scrambled_export"] = raw_diff(same_inputs, run_onnx(scrambled, scout_in))
                row["raw_port_inputs_vs_scout_inputs"] = raw_diff(run_onnx(session, ours), same_inputs)
                scout_tile = np.asarray(Image.open(tf_tiles / name))
                _, tile_vals64, gray64 = port.shadow_tile(
                    crop(exact.astype(np.float32)), denormalized_height(scout_in[0]), SEASON)
                vals64.append(tile_vals64)
                row["tf_vs_committed"] = gray_diff(scout_tile, reference)
                row["float64_vs_committed"] = gray_diff(gray64, reference)
                row["port_vs_tf"] = gray_diff(ported, scout_tile)
                row["port_vs_float64"] = gray_diff(ported, gray64)
            result["tiles"][name] = row

        if du is not None:
            result["float64_metrics"] = metrics_of(vals64)
        report[prefix] = result

        for name, row in result["tiles"].items():
            for key in ("port_vs_committed", "tf_vs_committed", "port_vs_tf"):
                if key in row and row[key][0] > GRAY_TOLERANCE:
                    failures.append(f"{prefix} {name}: {key} differs by {row[key][0]} gray levels")
            if du is not None:
                if not row["tf_call_equals_scout_predict_shadow"]:
                    failures.append(f"{prefix} {name}: the TensorFlow call is not SCOUT's predict_shadow")
                for k, label in ((0, "largest"), (1, "mean")):
                    if row["raw_onnx_vs_float64"][k] > FLOAT32_NOISE_FACTOR * row["raw_tf_vs_float64"][k]:
                        failures.append(f"{prefix} {name}: ONNX's {label} difference from float64, "
                                        f"{row['raw_onnx_vs_float64'][k]:.3g}, is over {FLOAT32_NOISE_FACTOR} "
                                        f"times TensorFlow float32's, {row['raw_tf_vs_float64'][k]:.3g}")
                if row["raw_onnx_vs_tf_inference_mode"][0] < MODE_SEPARATION:
                    failures.append(f"{prefix} {name}: ONNX is as close to inference mode as to SCOUT's training=True call")
                if row["raw_onnx_vs_scrambled_export"][0] != 0.0:
                    failures.append(f"{prefix} {name}: the moving averages reach the ONNX output")
                if row["raw_port_inputs_vs_scout_inputs"][0] != 0.0:
                    failures.append(f"{prefix} {name}: the port's inputs change the ONNX output")
                planes = row["port_inputs_vs_scout"]
                if planes["height"] != 0.0 or planes["date"] != 0.0 or planes["latitude"] > LATITUDE_TOLERANCE:
                    failures.append(f"{prefix} {name}: the port's inputs differ from SCOUT's: {planes}")
        for label, diff in zip(("mean", "median"), result["port_metrics_minutes_diff"]):
            if diff > METRIC_TOLERANCE:
                failures.append(f"{prefix}: the {label} differs from SCOUT's CSV by {diff:.3g} minutes")

    report["failures"] = failures
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if failures:
        print("FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    print(f"OK: {args.out} ({report['onnx']['bytes']} bytes) matches SCOUT.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
