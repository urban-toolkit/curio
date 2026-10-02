"""DIAGNOSTIC, never merged: what an ONNX session costs inside the cap.

Each variant runs DDRNet23-Slim at its 2048x1024 input, in a fresh isolated
child at the default budget, and reports VmSize, VmPeak, VmRSS and Threads
from /proc/self/status. Every test fails on purpose so its numbers land in the
JUnit report.

Probe 2: does the BFC arena's growth level off over many runs, does a
many-core host's arena count (M_ARENA_MAX raised as glibc's 8 x cores would
be on 64 cores) exhaust the cap, and does capping the arenas undo it.
"""

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="isolation needs Linux"
)

REPO = Path(__file__).resolve().parents[3]
DDRNET = REPO / "models" / "model.curio.ddrnet23-slim@1"
MODEL_ID = "model.curio.ddrnet23-slim"

STATUS = '''
    def status():
        out = {}
        with open("/proc/self/status") as handle:
            for line in handle:
                key, _, value = line.partition(":")
                if key in ("VmSize", "VmPeak", "VmRSS", "Threads"):
                    out[key] = value.strip()
        return out

    def mb(key):
        return int(status()[key].split()[0]) // 1024
'''

PROBE = STATUS + '''
    import ctypes, json, os, resource
    import numpy as np
    import onnxruntime as ort

    stats = {
        "ort": ort.__version__,
        "cpus": os.cpu_count(),
        "as_mb": resource.getrlimit(resource.RLIMIT_AS)[0] // (1 << 20),
        "start_vm": mb("VmSize"),
    }
    if P_MALLOC_MAX:
        ctypes.CDLL("libc.so.6").mallopt(-8, P_MALLOC_MAX)
    options = ort.SessionOptions()
    if P_THREADS:
        options.intra_op_num_threads = P_THREADS
    options.enable_cpu_mem_arena = P_ORT_ARENA
    folder = curio_model("model.curio.ddrnet23-slim")
    manifest = json.load(open(os.path.join(folder, "manifest.json")))
    stats["vm"], stats["rss"] = [], []
    try:
        session = ort.InferenceSession(
            os.path.join(folder, manifest["entry"]), sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        stats["session_vm"] = mb("VmSize")
        stats["threads"] = status()["Threads"]
        pixels = np.zeros((1, 3, 1024, 2048), dtype=np.uint8)
        for _ in range(P_RUNS):
            session.run(None, {session.get_inputs()[0].name: pixels})
            stats["vm"].append(mb("VmSize"))
            stats["rss"].append(mb("VmRSS"))
        stats["error"] = None
    except Exception as exc:
        stats["error"] = str(exc)[:300]
    stats["peak_vm"] = mb("VmPeak")
    return json.dumps(stats)
'''

SEGMENT = STATUS + '''
    import json, os, resource
    import pandas as pd

    stats = {"cpus": os.cpu_count(), "as_mb": resource.getrlimit(resource.RLIMIT_AS)[0] // (1 << 20),
             "start_vm": mb("VmSize"), "photos": len(PHOTOS)}
    frame = pd.DataFrame({"path": PHOTOS})
    try:
        out = curio_segment(frame, curio_model("model.curio.ddrnet23-slim"), ["sky", "road"])
        stats["dominant"] = sorted(set(out["dominant_class"]))
        stats["error"] = None
    except Exception as exc:
        stats["error"] = str(exc)[:300]
    stats["end_vm"] = mb("VmSize")
    stats["peak_vm"] = mb("VmPeak")
    stats["end_rss"] = mb("VmRSS")
    return json.dumps(stats)
'''

# P_MALLOC_MAX 512 is what glibc allows on a 64-core host (8 x cores): the
# 4-core runner caps the arenas at 32, so without it the runner cannot show
# what a many-core deploy pays per thread.
VARIANTS = {
    "default-12": dict(P_THREADS=0, P_ORT_ARENA=True, P_MALLOC_MAX=0, P_RUNS=12),
    "noarena-12": dict(P_THREADS=0, P_ORT_ARENA=False, P_MALLOC_MAX=0, P_RUNS=12),
    "t32-host64": dict(P_THREADS=32, P_ORT_ARENA=True, P_MALLOC_MAX=512, P_RUNS=6),
    "t64-host64": dict(P_THREADS=64, P_ORT_ARENA=True, P_MALLOC_MAX=512, P_RUNS=6),
    "t64-host64-noarena": dict(P_THREADS=64, P_ORT_ARENA=False, P_MALLOC_MAX=512, P_RUNS=6),
    "t64-cap8": dict(P_THREADS=64, P_ORT_ARENA=True, P_MALLOC_MAX=8, P_RUNS=6),
    "t64-cap16": dict(P_THREADS=64, P_ORT_ARENA=True, P_MALLOC_MAX=16, P_RUNS=6),
    "t64-cap16-noarena": dict(P_THREADS=64, P_ORT_ARENA=False, P_MALLOC_MAX=16, P_RUNS=6),
    "t128-cap16-noarena": dict(P_THREADS=128, P_ORT_ARENA=False, P_MALLOC_MAX=16, P_RUNS=3),
}


@pytest.fixture
def isolated_default(tmp_path, monkeypatch):
    from utk_curio.sandbox.isolation import lifecycle, runner, supervisor
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    release_connection()
    init_db()
    monkeypatch.setenv("CURIO_EXEC_SOCKET", str(tmp_path / "zygote.sock"))
    monkeypatch.setenv("CURIO_EXEC_TIMEOUT", "280")
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", str(supervisor.DEFAULT_LIMITS["memory_mb"]))
    config = runner.IsolationConfig.from_environment()
    lifecycle.ensure_running(config, exec_user=None, require_seccomp=False)
    try:
        yield config
    finally:
        lifecycle.shutdown()
        release_connection()


def _run(config, body):
    from utk_curio.sandbox.isolation import runner
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = runner.execute_isolated(
        body, "", "curio.builtin/computation-analysis", "",
        save_dataset=False, config=config, models={MODEL_ID: str(DDRNET)},
    )
    if result.get("stderr"):
        return {"stderr": result["stderr"][-1500:]}
    return json.loads(load_from_duckdb(result["output"]["path"]))


@pytest.mark.parametrize("variant", list(VARIANTS))
def test_probe_onnx_session(isolated_default, variant):
    body = PROBE
    for name, value in VARIANTS[variant].items():
        body = body.replace(name, repr(value))
    stats = _run(isolated_default, body)
    pytest.fail(f"PROBE {variant}: {json.dumps(stats)}")


def test_probe_curio_segment_every_photo(isolated_default):
    photos = sorted(str(p) for p in (REPO / "docs" / "examples" / "data" / "storage" / "mapillary").glob("*.jpg"))
    stats = _run(isolated_default, SEGMENT.replace("PHOTOS", repr(photos)))
    pytest.fail(f"PROBE segment: {json.dumps(stats)}")
