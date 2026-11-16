"""DDRNet23-Slim gives the same results on every x86 CPU.

DDRNet23-Slim's graph is Qualcomm AI Hub's w8a8 QDQ export with its int8 zero
points stored as uint8 by ``scripts/onnx_zero_points_to_uint8.py``, which
computes the same values. onnxruntime fuses the graph into QLinearConv
kernels by the types it finds. With int8 weights, an x86 CPU without VNNI
(AVX2 only: AMD Zen 2 and 3, as GitHub's AMD EPYC 7763 runners, and Intel
before Ice Lake) runs a kernel whose sums of pairs of products saturate at 16
bits: it labelled every one of example 10's 40 photos differently from CPUs
with VNNI or AMX, which compute exactly, and changed the dominant class of
ten. With uint8 weights every x86 CPU computes exactly.

- The shipped graph holds no int8 tensor, as the script reads a graph.
- Its scores of two of example 10's photos are the same, byte for byte, on
  this CPU and on an emulated AVX2 CPU without VNNI (``qemu-x86_64 -cpu
  Haswell``, from the qemu-user CI's image installs). The same child runs the
  model both ways, with the session the Segmentation module's ``_OnnxRunner``
  makes. On a CPU with VNNI or AMX (arcade's, GitHub's Intel runners) this
  compares exact arithmetic with AVX2's; on an AVX2 CPU both runs take the
  same kernels.
- The script, on a small QDQ graph written here: every value it dequantizes
  is the same after the change, and a zero point in external data is refused.

On a machine that is not x86_64 Linux, or has no ``qemu-x86_64``, the
comparison fails and says why.
"""

from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from utk_curio.backend.tests._support.model_files import QDQ_OUTPUTS, tiny_qdq_model

REPO = Path(__file__).resolve().parents[4]
DDRNET = REPO / "packages" / "model.curio.ddrnet23-slim@1"
SCRIPT = REPO / "scripts" / "onnx_zero_points_to_uint8.py"
SAMPLE = "data.curio.mapillary-sample"
STORAGE = REPO / "docs" / "examples" / "data" / "storage"
#: The classes example 10's first Image Segmentation node reports.
STREET = ["vegetation", "terrain", "sky", "road", "sidewalk", "building"]
#: The CPU QEMU emulates: Haswell has AVX2 and FMA, and neither AVX-512 nor VNNI.
EMULATED_CPU = "Haswell"
#: Each run's limit. Under QEMU a photo takes about 25 s on arcade, and up to
#: 1.7 times that when the server is busy.
NATIVE_TIMEOUT_S = 300
EMULATED_TIMEOUT_S = 900
#: The flags of /proc/cpuinfo that choose onnxruntime's integer kernels.
KERNEL_FLAGS = ("avx2", "avx512bw", "avx512_vnni", "avx_vnni", "amx_int8")

#: The child both runs are: the model's raw scores of each input (a saved
#: batch), with the session the Segmentation module's _OnnxRunner makes,
#: saved under the input's name in the output folder.
SCORES = """
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort

model, out, *inputs = sys.argv[1:]
session = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
name = session.get_inputs()[0].name
for path in inputs:
    np.save(str(Path(out) / Path(path).name), session.run(None, {name: np.load(path)})[0])
"""


def _script():
    """``scripts/onnx_zero_points_to_uint8.py``, read by its path."""
    spec = importlib.util.spec_from_file_location("_curio_onnx_zero_points_to_uint8", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model() -> tuple[Path, dict]:
    block = json.loads((DDRNET / "manifest.json").read_text(encoding="utf-8"))["model"]
    return DDRNET / block["entry"], block


def _photos(tmp_path, count: int = 2) -> list[str]:
    """The first *count* of example 10's photos, as a node's curio_load_collection gives them."""
    from utk_curio.sandbox.util.collections import make_collection_helpers

    index = REPO / "datasets" / f"{SAMPLE}@1" / "data" / "index.parquet"
    helpers = make_collection_helpers(
        lambda _id: str(index), {SAMPLE: {"kind": "images", "root": str(STORAGE)}}, str(tmp_path / "media")
    )
    return list(helpers["curio_load_collection"](SAMPLE)["path"].head(count))


def _batch(path: str, model_input: dict) -> np.ndarray:
    """What the Segmentation module's ``_OnnxRunner`` feeds a uint8 model for
    the image at *path*: its RGB pixels resized to the manifest's input,
    channels first."""
    from PIL import Image

    with Image.open(path) as source:
        image = source.convert("RGB")
    pixels = np.asarray(image.resize((int(model_input["width"]), int(model_input["height"]))), dtype=np.uint8)
    return pixels.transpose(2, 0, 1)[None]


def _scores(command: list[str], model: Path, out: Path, inputs: list[Path], timeout: int) -> list[np.ndarray]:
    """The model's scores of each input, from the child run with *command*."""
    out.mkdir()
    what = " ".join([*command[:-1], "python"])
    try:
        run = subprocess.run(
            [*command, "-c", SCORES, str(model), str(out), *map(str, inputs)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"DDRNet23-Slim did not score {len(inputs)} photos in {timeout} s under {what}")
    assert run.returncode == 0, f"DDRNet23-Slim's run under {what} exited {run.returncode}:\n{run.stderr[-3000:]}"
    return [np.load(out / path.name) for path in inputs]


def _cpu() -> str:
    """This machine's CPU and the flags of it that choose onnxruntime's integer kernels."""
    try:
        first = Path("/proc/cpuinfo").read_text(encoding="utf-8").split("\n\n")[0]
    except OSError:
        return platform.processor() or "a CPU /proc/cpuinfo does not name"
    info = {key.strip(): value.strip() for key, _, value in (line.partition(":") for line in first.splitlines())}
    flags = [flag for flag in KERNEL_FLAGS if flag in info.get("flags", "").split()]
    return f"{info.get('model name', 'a CPU /proc/cpuinfo does not name')} ({', '.join(flags) or 'no AVX2'})"


def _dominant(classes: np.ndarray, labels: list[str]) -> str:
    """The street class covering most of a photo, and its share, as ``segment_images`` gives them."""
    shares = np.bincount(classes.ravel().astype(np.int64), minlength=len(labels)) / classes.size
    best = max(STREET, key=lambda name: shares[labels.index(name)])
    return f"{best} {shares[labels.index(best)] * 100:.2f}%"


def _difference(here: np.ndarray, there: np.ndarray, labels: list[str]) -> str:
    """How two runs' scores of one photo differ, and what the node would show of it."""
    if here.dtype != there.dtype or here.shape != there.shape:
        return f"scores of {here.dtype} {here.shape} here, {there.dtype} {there.shape} there"
    levels = int(np.abs(here.astype(np.int64) - there.astype(np.int64)).max())
    classes_here, classes_there = here[0].argmax(axis=0), there[0].argmax(axis=0)
    pixels = int((classes_here != classes_there).sum())
    return (
        f"{int((here != there).sum())} of {here.size} scores differ, by up to {levels} levels, and {pixels} of "
        f"{classes_here.size} pixels change class; the dominant street class reads "
        f"{_dominant(classes_here, labels)} here, {_dominant(classes_there, labels)} there"
    )


# ---------------------------------------------------------------------------
# DDRNet23-Slim
# ---------------------------------------------------------------------------

def test_ddrnets_graph_holds_no_int8_tensor():
    model = _model()[0]
    found = _script().int8_tensors(model.read_bytes())
    assert not found, (
        f"DDRNet23-Slim's graph holds {len(found)} int8 tensors ({', '.join(found[:3])}, ...), so onnxruntime runs "
        "its convolutions on int8 weights, which an x86 CPU without VNNI sums with 16-bit saturation: store them "
        f"as uint8 with python scripts/onnx_zero_points_to_uint8.py {model.relative_to(REPO).as_posix()}"
    )


def test_ddrnet_scores_photos_alike_on_this_cpu_and_an_avx2_one_without_vnni(tmp_path):
    assert platform.system() == "Linux" and platform.machine() == "x86_64", (
        "This test runs DDRNet23-Slim on this machine's CPU and on an emulated AVX2 CPU without VNNI "
        f"(qemu-x86_64 -cpu {EMULATED_CPU}) with the same Python, so it needs x86_64 Linux, as CI's image is; "
        f"this machine is {platform.system()} {platform.machine()}."
    )
    qemu = shutil.which("qemu-x86_64")
    assert qemu, (
        "qemu-x86_64 is not on PATH: CI's image installs it (qemu-user, in the Dockerfile's ci_deps_1 stage); "
        "on another x86_64 Linux machine, install qemu-user."
    )
    model, block = _model()
    photos = _photos(tmp_path)
    inputs = []
    for index, photo in enumerate(photos):
        inputs.append(tmp_path / f"photo-{index}.npy")
        np.save(str(inputs[-1]), _batch(photo, block["input"]))
    here = _scores([sys.executable], model, tmp_path / "native", inputs, NATIVE_TIMEOUT_S)
    there = _scores([qemu, "-cpu", EMULATED_CPU, sys.executable], model, tmp_path / "emulated", inputs,
                    EMULATED_TIMEOUT_S)
    differences = [
        f"  photo {index} ({Path(photo).name}): {_difference(a, b, block['labels'])}"
        for index, (photo, a, b) in enumerate(zip(photos, here, there))
        if a.dtype != b.dtype or a.shape != b.shape or a.tobytes() != b.tobytes()
    ]
    assert not differences, (
        f"DDRNet23-Slim scores {len(differences)} of {len(photos)} photos differently on this CPU, {_cpu()}, and "
        f"on an emulated AVX2 CPU without VNNI (qemu-x86_64 -cpu {EMULATED_CPU}):\n" + "\n".join(differences)
    )


# ---------------------------------------------------------------------------
# The script
# ---------------------------------------------------------------------------

def test_the_script_keeps_every_value_it_dequantizes(tmp_path):
    """Each tensor the graph dequantizes (``tiny_qdq_model``: per-row weights,
    the input, stored int8 weights, saturating both ends of int8) is the same,
    byte for byte, once the script rewrote the graph in place; ``--list``
    first writes nothing."""
    import onnxruntime as ort

    script = _script()
    path = tmp_path / "model.onnx"
    original = tiny_qdq_model()
    path.write_bytes(original)
    assert script.main([str(path), "--list"]) == 0 and path.read_bytes() == original
    assert script.main([str(path)]) == 0
    rewritten = path.read_bytes()
    assert len(script.int8_tensors(original)) == 6 and script.int8_tensors(rewritten) == []
    conversion = script.convert(original)
    assert (conversion.model, sorted(conversion.zero_points), sorted(conversion.quantized), conversion.retyped) == (
        rewritten, ["b_zero_point", "w_zero_point", "x_zero_point"], ["B"], ["W_quantized", "X_quantized"])
    feeds = {"X": np.array([[-10.0, 0.3, 6.6], [0.0, -0.02, 100.0]], dtype=np.float32)}
    before = ort.InferenceSession(original, providers=["CPUExecutionProvider"]).run(None, feeds)
    after = ort.InferenceSession(rewritten, providers=["CPUExecutionProvider"]).run(None, feeds)
    # The input saturates both ends: -10 and 100 quantize to -128 and 127,
    # (-128 - 7) * 0.05 and (127 - 7) * 0.05 once dequantized.
    assert np.isclose(before[1].min(), -6.75) and np.isclose(before[1].max(), 6.0), before[1]
    for name, a, b in zip(QDQ_OUTPUTS, before, after):
        assert (a.dtype, a.shape, a.tobytes()) == (b.dtype, b.shape, b.tobytes()), (name, a, b)


def test_the_script_refuses_a_zero_point_in_external_data(tmp_path, capsys):
    script = _script()
    path = tmp_path / "model.onnx"
    path.write_bytes(tiny_qdq_model(external_zero_point=True))
    with pytest.raises(script.Refused, match="w_zero_point is in external data"):
        script.convert(path.read_bytes())
    out = tmp_path / "out.onnx"
    assert script.main([str(path), "--out", str(out)]) == 1
    assert not out.exists() and sorted(p.name for p in tmp_path.iterdir()) == ["model.onnx"]
    assert "w_zero_point is in external data" in capsys.readouterr().err
