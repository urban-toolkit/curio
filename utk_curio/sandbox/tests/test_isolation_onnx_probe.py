"""DIAGNOSTIC, never merged: what an ONNX session costs inside the cap.

Each variant runs DDRNet23-Slim once, at its 2048x1024 input, in a fresh
isolated child at the default budget, and reports VmSize, VmPeak, VmRSS and
Threads from /proc/self/status at each step. Every test fails on purpose so
its numbers land in the JUnit report.
"""

import json
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="isolation needs Linux"
)

REPO = Path(__file__).resolve().parents[3]
DDRNET = REPO / "models" / "model.curio.ddrnet23-slim@1"
MODEL_ID = "model.curio.ddrnet23-slim"

PROBE = '''
    import ctypes, json, os, resource
    import numpy as np
    import onnxruntime as ort

    def status():
        out = {}
        with open("/proc/self/status") as handle:
            for line in handle:
                key, _, value = line.partition(":")
                if key in ("VmSize", "VmPeak", "VmRSS", "Threads"):
                    out[key] = value.strip()
        return out

    stats = {
        "ort": ort.__version__,
        "cpus": os.cpu_count(),
        "as_mb": resource.getrlimit(resource.RLIMIT_AS)[0] // (1 << 20),
        "start": status(),
    }
    if P_MALLOC_MAX:
        ctypes.CDLL("libc.so.6").mallopt(-8, P_MALLOC_MAX)
    options = ort.SessionOptions()
    if P_THREADS:
        options.intra_op_num_threads = P_THREADS
    options.enable_cpu_mem_arena = P_ORT_ARENA
    options.enable_mem_pattern = P_MEM_PATTERN
    folder = curio_model("model.curio.ddrnet23-slim")
    manifest = json.load(open(os.path.join(folder, "manifest.json")))
    try:
        session = ort.InferenceSession(
            os.path.join(folder, manifest["entry"]), sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        stats["session"] = status()
        pixels = np.zeros((1, 3, 1024, 2048), dtype=np.uint8)
        session.run(None, {session.get_inputs()[0].name: pixels})
        stats["run1"] = status()
        session.run(None, {session.get_inputs()[0].name: pixels})
        stats["run2"] = status()
        stats["error"] = None
    except Exception as exc:
        stats["error"] = str(exc)[:400]
    stats["end"] = status()
    return json.dumps(stats)
'''

SEGMENT = '''
    import glob, json, os, resource
    import pandas as pd

    def status():
        out = {}
        with open("/proc/self/status") as handle:
            for line in handle:
                key, _, value = line.partition(":")
                if key in ("VmSize", "VmPeak", "VmRSS", "Threads"):
                    out[key] = value.strip()
        return out

    stats = {"cpus": os.cpu_count(), "as_mb": resource.getrlimit(resource.RLIMIT_AS)[0] // (1 << 20),
             "start": status()}
    frame = pd.DataFrame({"path": PHOTOS})
    try:
        out = curio_segment(frame, curio_model("model.curio.ddrnet23-slim"), ["sky", "road"])
        stats["dominant"] = list(out["dominant_class"])
        stats["error"] = None
    except Exception as exc:
        stats["error"] = str(exc)[:400]
    stats["end"] = status()
    return json.dumps(stats)
'''

VARIANTS = {
    "default": dict(P_THREADS=0, P_ORT_ARENA=True, P_MEM_PATTERN=True, P_MALLOC_MAX=0),
    "t1": dict(P_THREADS=1, P_ORT_ARENA=True, P_MEM_PATTERN=True, P_MALLOC_MAX=0),
    "t16": dict(P_THREADS=16, P_ORT_ARENA=True, P_MEM_PATTERN=True, P_MALLOC_MAX=0),
    "t32": dict(P_THREADS=32, P_ORT_ARENA=True, P_MEM_PATTERN=True, P_MALLOC_MAX=0),
    "t64": dict(P_THREADS=64, P_ORT_ARENA=True, P_MEM_PATTERN=True, P_MALLOC_MAX=0),
    "t64-noarena": dict(P_THREADS=64, P_ORT_ARENA=False, P_MEM_PATTERN=True, P_MALLOC_MAX=0),
    "t64-noarena-nopattern": dict(P_THREADS=64, P_ORT_ARENA=False, P_MEM_PATTERN=False, P_MALLOC_MAX=0),
    "t64-malloc2": dict(P_THREADS=64, P_ORT_ARENA=True, P_MEM_PATTERN=True, P_MALLOC_MAX=2),
    "t64-noarena-malloc2": dict(P_THREADS=64, P_ORT_ARENA=False, P_MEM_PATTERN=True, P_MALLOC_MAX=2),
    "t1-noarena": dict(P_THREADS=1, P_ORT_ARENA=False, P_MEM_PATTERN=True, P_MALLOC_MAX=0),
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
    monkeypatch.setenv("CURIO_EXEC_TIMEOUT", "180")
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


def test_probe_curio_segment(isolated_default):
    photos = sorted(str(p) for p in (REPO / "docs" / "examples" / "data" / "storage").rglob("*.jpg"))[:2]
    stats = _run(isolated_default, SEGMENT.replace("PHOTOS", repr(photos)))
    stats["photos"] = photos
    pytest.fail(f"PROBE segment: {json.dumps(stats)}")
