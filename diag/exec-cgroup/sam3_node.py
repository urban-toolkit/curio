"""Track Objects' node code on the SideSeeing walk, as the shipped node runs it (a diagnostic).

sam3_measure.py starts it in a node cgroup. It prints a MARK line with its own
address space and resident peak after each stage, and a DONE line at the end.
With DIAG_RLIMIT_AS_MB it first caps its address space as an isolated child is
capped today: what it has mapped once the zygote's imports are in, plus that
budget.
"""

import json
import os
import sys
import time

STARTED = time.time()
MARKS = []


def mark(name):
    status = {}
    with open("/proc/self/status") as handle:
        for line in handle:
            key, _, value = line.partition(":")
            if key in ("VmPeak", "VmSize", "VmHWM", "VmRSS"):
                status[key + "_GiB"] = round(int(value.split()[0]) / 2**20, 2)
    MARKS.append({"stage": name, "t": round(time.time() - STARTED, 1), **status})
    print("MARK " + json.dumps(MARKS[-1]), flush=True)


mark("start")
# What the zygote imports before it forks a child (zygote.build_namespace_template).
import duckdb  # noqa: E402,F401
import geopandas  # noqa: E402,F401
import numpy  # noqa: E402,F401
import pandas as pd  # noqa: E402
import shapely  # noqa: E402,F401

mark("the zygote's imports")
budget_mb = int(os.environ.get("DIAG_RLIMIT_AS_MB") or 0)
if budget_mb:
    import resource

    with open("/proc/self/statm") as handle:
        baseline = int(handle.read().split()[0]) * os.sysconf("SC_PAGE_SIZE")
    resource.setrlimit(resource.RLIMIT_AS, (baseline + (budget_mb << 20),) * 2)
    print(f"MARK {json.dumps({'stage': 'RLIMIT_AS set', 'cap_GiB': round((baseline + (budget_mb << 20)) / 2**30, 2)})}",
          flush=True)

sys.path.insert(0, os.environ["DIAG_PACKAGE_SOURCES"])
import torch  # noqa: E402

import sam3_tracking as module  # noqa: E402

mark("torch and transformers imported")

real_model = module.Sam3VideoModel
real_sample = module._sample
real_device = module._device


class _Model:
    @staticmethod
    def from_pretrained(*args, **kwargs):
        mark("weights load starts")
        loaded = real_model.from_pretrained(*args, **kwargs)
        mark("weights loaded on the CPU")
        return loaded


def _sample(*args, **kwargs):
    mark("decode starts")
    frames, times = real_sample(*args, **kwargs)
    mark(f"decoded {len(frames)} frames")
    return frames, times


def _device():
    found = real_device()
    mark(f"device {found[0]}")
    return found


module.Sam3VideoModel = _Model
module._sample = _sample
module._device = _device

# The shipped node's settings (packages/model.curio.sam3@1/sources/track-objects.py),
# with TO_SECONDS at the 300 s one run takes.
LABELS = [
    "curb ramp", "curb cut", "tactile paving", "bollard", "pole",
    "construction barrier", "traffic cone", "person",
]
media = pd.DataFrame([{
    "kind": "video", "path": os.environ["DIAG_VIDEO"], "relpath": "chicago/west-loop/walk/video.mp4",
    "name": "video.mp4", "dataset_id": "diag.sideseeing", "file_id": "walk",
}])


class Model:
    path = os.environ["DIAG_WEIGHTS"]


def derived_file(dataset_id, file_id, start_ms, ext, tag=None):
    return {"path": f"/tmp/diag-{file_id}-{start_ms}-{tag}.{ext}", "file_id": f"{file_id}-{tag}"}


try:
    result = module.track_objects(
        media, Model, derived_file, labels=LABELS, every_seconds=0.5, from_seconds=0,
        to_seconds=float(os.environ.get("DIAG_TO_SECONDS", "300")), max_seconds=300, width=960,
    )
except BaseException as exc:  # noqa: BLE001 - the failure is the measurement
    mark("failed")
    import traceback

    print("FAILED " + json.dumps({"error": f"{type(exc).__name__}: {exc}"[:600],
                                  "trace": traceback.format_exc()[-2500:], "marks": MARKS}), flush=True)
    raise SystemExit(1)
mark("tracked")
gpu = {}
if torch.cuda.is_available():
    gpu = {"max_allocated_GiB": round(torch.cuda.max_memory_allocated() / 2**30, 2),
           "max_reserved_GiB": round(torch.cuda.max_memory_reserved() / 2**30, 2),
           "device": torch.cuda.get_device_name(0)}
counts = {column: int(result[column].iloc[0]) for column in result.columns if column.endswith("_objects")}
print("DONE " + json.dumps({"rows": len(result), "counts": counts, "gpu": gpu, "marks": MARKS}), flush=True)
