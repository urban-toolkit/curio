"""Tiny Track Objects repeats run to run on the GPU, in each of torch's modes.

Example 31's e2e (``test_workflows.py``) asserts what Track Objects gives on
the GPU runner's GPU, and keeps the swimlane's and the map's frames on
baselines that every GPU kind shares, on the strength of the probes of
11-17: the tiny SAM 3 of ``tests/_support/tiny_sam3.py`` repeats exactly run
to run on every GPU runner, in torch's default mode and in the deterministic
mode examples 27 to 30 switch on in CI's shared sandbox, and deterministic
mode raises nowhere. This keeps that probe as a guard.

Each mode runs in a process of its own: deterministic mode is the process's,
set before CUDA starts. Each runs Track Objects twice on an 8 s clip with
example 31's settings, a frame every 2 s, on CUDA, and the two runs must agree
on the row, the tracks (``largest_share`` included), what SAM 3 found in each
frame (its objects, scores, boxes and masks) and the frames it drew. The
encoded overlay is never compared, since an H.264 encoder may write other
bytes for the same frames, nor one mode against the other.

Marked ``cuda``: test-gpu runs it in its container with ``-m cuda``, beside
``test_cuda_torch.py``. Without a usable GPU it fails, never skips.

Run:  python -m pytest utk_curio/sandbox/tests/test_cuda_sam3.py -m cuda -v -s
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
#: Example 31's labels and settings (docs/examples/31-sideseeing-objects-along-a-walk.json).
LABELS = [
    "curb ramp", "curb cut", "tactile paving", "bollard", "pole",
    "construction barrier", "traffic cone", "person", "wheelchair ramp",
]
SETTINGS = {"every_seconds": 2, "forget_seconds": 10, "width": 960}
#: CI's stand-in for the walk is about this long.
CLIP_SECONDS = 8
MODES = ("default", "deterministic")
#: What one mode's two runs are compared on.
PARTS = ("row", "tracks", "found", "drawn")


def _deterministic_mode() -> None:
    """Examples 27 to 30's lines, which CI's shared sandbox runs in its
    process: before CUDA starts, cuBLAS's workspace, then a seed,
    deterministic kernels only and full float32 precision."""
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    import torch

    torch.manual_seed(27)
    torch.use_deterministic_algorithms(True)
    torch.backends.fp32_precision = "ieee"
    torch.backends.cudnn.benchmark = False


def _plain(value):
    """*value* as JSON compares it: numpy's as Python's, NaN as None, and
    anything else, such as a time, as its text."""
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        value = value.tolist()
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is None or isinstance(value, (bool, int, float, str, list, dict)):
        return value
    return str(value)


def _digest(array) -> str:
    import numpy as np

    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _found(index, found) -> dict:
    """What SAM 3 found in frame *index*: each object's id, score and box, and
    its mask's digest, as the module's clean-up leaves them."""
    masks = found["masks"].detach().cpu().numpy().astype(bool)

    def as_list(value):
        if hasattr(value, "detach"):
            value = value.detach()
            return (value.float() if value.is_floating_point() else value).cpu().tolist()
        return list(value)

    return {
        "index": int(index),
        "object_ids": [int(i) for i in as_list(found["object_ids"])],
        "scores": [float(s) for s in as_list(found["scores"])],
        "boxes": [[float(v) for v in box] for box in as_list(found["boxes"])],
        "masks": [_digest(mask) for mask in masks],
        "labels": {str(k): sorted(int(i) for i in v) for k, v in found["prompt_to_obj_ids"].items()},
    }


class _Folders:
    """pytest's ``tmp_path_factory``, as ``tiny_sam3.weights`` asks it."""

    def __init__(self, base: Path):
        self.base = base

    def mktemp(self, name: str) -> Path:
        return Path(tempfile.mkdtemp(prefix=name, dir=self.base))


def _two_runs(mode: str, work: Path) -> dict:
    """Track Objects twice on one clip in this process, in *mode*: the device,
    and for each run its row, its tracks, what SAM 3 found and the frames it
    drew."""
    import numpy as np
    import pandas as pd
    import torch

    from utk_curio.backend.tests._support import tiny_sam3
    from utk_curio.backend.tests.test_packages.test_sam3_package import (
        MODEL_ID,
        PACKAGE,
        _collection,
        _loaded,
        _staged,
    )

    os.environ["HF_HUB_OFFLINE"] = os.environ["TRANSFORMERS_OFFLINE"] = "1"
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    weights = tiny_sam3.weights(_Folders(work), tiny_sam3.config())
    catalog = work / "catalog" / PACKAGE.name
    catalog.mkdir(parents=True)
    (catalog / "manifest.json").write_bytes((PACKAGE / "manifest.json").read_bytes())
    rows, helpers = _collection(work, seconds=CLIP_SECONDS)
    model = _loaded(catalog, weights)(MODEL_ID)
    runs = []
    with _staged(work) as module:
        device = [str(part) for part in module._device()]
        follow, draw = module._follow, module._draw
        for _ in range(2):
            found, drawn = [], []

            def watched_follow(run, frames, let_go_after=None, found=found):
                for index, seen in follow(run, frames, let_go_after):
                    found.append(_found(index, seen))
                    yield index, seen

            def watched_draw(run, image, seen, label_of, drawn=drawn):
                picture = draw(run, image, seen, label_of)
                drawn.append(_digest(np.asarray(picture)))
                return picture

            module._follow, module._draw = watched_follow, watched_draw
            try:
                out = module.track_objects(rows, model, helpers["curio_derived_file"], labels=LABELS, **SETTINGS)
            finally:
                module._follow, module._draw = follow, draw
            (row,) = out.to_dict("records")
            tracks = pd.read_parquet(row["tracks"]).to_dict("records")
            runs.append({
                "row": {key: _plain(value) for key, value in row.items()},
                "tracks": [{key: _plain(value) for key, value in track.items()} for track in tracks],
                "found": found,
                "drawn": drawn,
            })
    return {"mode": mode, "device": device, "deterministic": torch.are_deterministic_algorithms_enabled(),
            "runs": runs}


def main(argv: list[str]) -> int:
    """``<mode> <work folder> <out.json>``: :func:`_two_runs` in a process of
    its own, in *mode*, set before CUDA starts."""
    mode, work, out = argv
    if mode == "deterministic":
        _deterministic_mode()
    result = _two_runs(mode, Path(work))
    Path(out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


@pytest.mark.cuda
@pytest.mark.parametrize("mode", MODES)
def test_tiny_track_objects_repeats_run_to_run_on_the_gpu(mode, tmp_path, record_property):
    """Two runs of Track Objects in one process, in *mode*, on CUDA, agree on
    the row, the tracks, what SAM 3 found and the frames it drew."""
    out = tmp_path / "runs.json"
    work = tmp_path / "work"
    work.mkdir()
    done = subprocess.run(
        [sys.executable, "-m", "utk_curio.sandbox.tests.test_cuda_sam3", mode, str(work), str(out)],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    assert done.returncode == 0, (
        f"Track Objects in torch's {mode} mode failed:\n{done.stdout[-3000:]}\n{done.stderr[-6000:]}")
    result = json.loads(out.read_text(encoding="utf-8"))
    record_property("sam3_objects", json.dumps({
        "mode": mode, "objects": len(result["runs"][0]["tracks"]),
        "labels": sorted({track["label"] for track in result["runs"][0]["tracks"]}),
    }))
    assert result["device"][0] == "cuda", f"Track Objects ran on {result['device']}, not the GPU"
    assert result["deterministic"] is (mode == "deterministic"), result["deterministic"]
    first, second = result["runs"]
    assert first["tracks"] and len(first["found"]) == CLIP_SECONDS // SETTINGS["every_seconds"], first
    differ = [part for part in PARTS if first[part] != second[part]]
    assert not differ, f"in torch's {mode} mode, two runs of Track Objects differ in their {differ}"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
