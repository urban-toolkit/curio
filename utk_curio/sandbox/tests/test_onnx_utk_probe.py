"""DIAGNOSTIC, never merged: example 10's Image Segmentation on the deploy host.

Runs the node's own code in an isolated child, at the deployment's limits,
on the machine dev runs on, and reports how it ends and what it spent: wall
time, CPU time over all threads (``getrusage``), threads, peak address space
and peak resident memory. Every test fails on purpose so its numbers land in
the JUnit report.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs Linux")

REPO = Path(__file__).resolve().parents[3]
SAMPLE = "data.curio.mapillary-sample"
MODEL = "model.curio.ddrnet23-slim"
INDEX = REPO / "datasets" / f"{SAMPLE}@1" / "data" / "index.parquet"
STORAGE = REPO / "docs" / "examples" / "data" / "storage"
DDRNET = REPO / "models" / f"{MODEL}@1"

HOST = r'''
    import json, os, resource
    def status():
        out = {}
        with open("/proc/self/status") as fh:
            for line in fh:
                key, _, value = line.partition(":")
                if key in ("VmPeak", "VmSize", "VmHWM", "VmRSS", "Threads"):
                    out[key] = value.strip()
        return out
    def read(path):
        try:
            with open(path) as fh:
                return fh.read().strip()[:200]
        except OSError as exc:
            return f"<{exc.__class__.__name__}>"
    physical = set()
    sockets = set()
    current = {}
    with open("/proc/cpuinfo") as fh:
        for line in fh:
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if key == "physical id":
                current["socket"] = value
            elif key == "core id":
                current["core"] = value
            elif not key and current:
                physical.add((current.get("socket"), current.get("core")))
                sockets.add(current.get("socket"))
                current = {}
    host = {
        "cpu_count": os.cpu_count(),
        "affinity": len(os.sched_getaffinity(0)),
        "physical_cores": len(physical),
        "sockets": len(sockets),
        "cgroup_cpu_max": read("/sys/fs/cgroup/cpu.max"),
        "cgroup_memory_max": read("/sys/fs/cgroup/memory.max"),
        "overcommit": read("/proc/sys/vm/overcommit_memory"),
        "rlimit_cpu": resource.getrlimit(resource.RLIMIT_CPU),
        "rlimit_as_mb": resource.getrlimit(resource.RLIMIT_AS)[0] // (1 << 20),
        "malloc_arena_max": os.environ.get("MALLOC_ARENA_MAX"),
    }
'''

# The node's own code, as example 10 runs it (Data Loading feeding Image
# Segmentation), in chunks so the cost of each part is visible.
MEASURE = HOST + r'''
    import time
    import pandas as pd
    classes = ["vegetation", "terrain", "sky", "road", "sidewalk", "building"]
    t0 = time.monotonic()
    photos = curio_load_collection("data.curio.mapillary-sample")
    model = curio_load_model("model.curio.ddrnet23-slim")
    steps = []
    def mark(label):
        ru = resource.getrusage(resource.RUSAGE_SELF)
        steps.append({"step": label, "wall": round(time.monotonic() - t0, 2),
                      "cpu": round(ru.ru_utime + ru.ru_stime, 1), **status()})
    mark("loaded")
    model.runner
    mark("session")
    for start in range(0, len(photos), CHUNK):
        curio_segment(photos.iloc[start:start + CHUNK], model, classes)
        mark(f"photos {start + 1}-{min(start + CHUNK, len(photos))}")
    return json.dumps({"host": host, "photos": len(photos), "steps": steps})
'''

DEPLOYED = r'''
    photos = curio_load_collection("data.curio.mapillary-sample")
    model = curio_load_model("model.curio.ddrnet23-slim")
    classes = ["vegetation", "terrain", "sky", "road", "sidewalk", "building"]
    out = curio_segment(photos, model, classes)
    return len(out)
'''


def _isolated(tmp_path, monkeypatch, timeout):
    from utk_curio.sandbox.isolation import lifecycle, runner, supervisor
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    release_connection()
    init_db()
    monkeypatch.setenv("CURIO_EXEC_SOCKET", str(tmp_path / "zygote.sock"))
    monkeypatch.setenv("CURIO_EXEC_TIMEOUT", str(timeout))
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", str(supervisor.DEFAULT_LIMITS["memory_mb"]))
    config = runner.IsolationConfig.from_environment()
    lifecycle.ensure_running(config, exec_user=None, require_seccomp=False)
    return config


def _run(config, code, tmp_path):
    from utk_curio.sandbox.isolation import runner

    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    started = time.monotonic()
    result = runner.execute_isolated(
        code, "", "curio.streetvision/image-segmentation", "",
        save_dataset=False, config=config,
        dataset_paths={SAMPLE: str(INDEX)},
        dataset_formats={SAMPLE: {"format": "collection"}},
        collections={SAMPLE: {"kind": "images", "root": str(STORAGE)}},
        media_dir=str(media),
        models={MODEL: str(DDRNET)},
    )
    return result, round(time.monotonic() - started, 1)


@pytest.fixture
def stop_zygote():
    yield
    from utk_curio.sandbox.isolation import lifecycle
    from utk_curio.sandbox.util.db import release_connection

    lifecycle.shutdown()
    release_connection()


def test_probe_as_deployed(tmp_path, monkeypatch, stop_zygote):
    """The deployment's limits: 300 s wall, so 300 s of CPU."""
    config = _isolated(tmp_path, monkeypatch, 300)
    result, wall = _run(config, DEPLOYED, tmp_path)
    pytest.fail("PROBE deployed: " + json.dumps({
        "wall_from_parent": wall, "limits": config.limits,
        "stderr": (result.get("stderr") or "")[-800:],
        "output": str(result.get("output"))[:300],
    }))


@pytest.mark.parametrize("chunk", [5])
def test_probe_measured(tmp_path, monkeypatch, stop_zygote, chunk):
    """The same work with a wall and CPU allowance of 1500 s, measured."""
    config = _isolated(tmp_path, monkeypatch, 1500)
    result, wall = _run(config, MEASURE.replace("CHUNK", str(chunk)), tmp_path)
    if result.get("stderr"):
        stats = {"stderr": result["stderr"][-1500:]}
    else:
        from utk_curio.sandbox.util.parsers import load_from_duckdb

        stats = json.loads(load_from_duckdb(result["output"]["path"]))
    stats["wall_from_parent"] = wall
    pytest.fail("PROBE measured: " + json.dumps(stats))
