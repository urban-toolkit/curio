"""What test-gpu's per-process sampler records (``scripts/ci_stack_processes.py``).

The sampler reads the CI container from the inside, so a stack that grows
over a repeat run names the process that grows. These tests hold its pure
parts: which role and shard each process gets, and the cgroup numbers it
keeps apart.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load():
    path = REPO_ROOT / "scripts" / "ci_stack_processes.py"
    spec = importlib.util.spec_from_file_location("_scripts_ci_stack_processes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proc(pid, ppid, kind, shard=None, anon=0):
    return {"pid": pid, "ppid": ppid, "kind": kind, "shard": shard, "threads": 1,
            "fds": 1, "VmRSS": anon, "RssAnon": anon, "Pss": anon}


def test_each_process_is_named_by_its_server_and_shard():
    probe = _load()
    assert probe.kind_of("python -u -m backend.server", "python") == "backend"
    assert probe.kind_of("python -u -m sandbox.server", "python") == "sandbox"
    assert probe.kind_of("python curio.py start sandbox --sandbox-port 2003", "python") == "launcher"
    assert probe.kind_of("node --input-type=commonjs", "node") == "node"
    assert probe.shard_of("A=1\0BACKEND_PORT=5005\0SANDBOX_PORT=2003\0") == 3
    assert probe.shard_of("SANDBOX_PORT=2004\0") == 4
    assert probe.shard_of("PATH=/bin\0") is None

    procs = [
        _proc(1, 0, "launcher", 0), _proc(10, 1, "backend", 0, 100), _proc(11, 1, "sandbox", 0, 200),
        _proc(12, 11, "node", None, 300), _proc(20, 0, "sh"), _proc(21, 20, "launcher", 2),
        _proc(22, 21, "sandbox", 2, 400), _proc(23, 22, "node", None, 500), _proc(24, 1, "pages", None),
    ]
    roles = probe.roles(procs)
    assert set(roles) == {"launcher0", "backend0", "sandbox0", "node@sandbox0", "sh",
                          "launcher2", "sandbox2", "node@sandbox2", "pages0"}
    assert roles["node@sandbox2"]["anon"] == 500
    assert roles["sandbox0"]["n"] == 1


def test_the_cgroup_reading_keeps_memory_and_processes_apart(tmp_path):
    probe = _load()
    (tmp_path / "memory.current").write_text("8000\n")
    (tmp_path / "memory.peak").write_text("9000\n")
    (tmp_path / "pids.current").write_text("612\n")
    (tmp_path / "memory.stat").write_text("anon 5000\nfile 2000\nactive_file 1500\nunknown 7\n")
    assert probe.cgroup(tmp_path) == {
        "current": 8000, "peak": 9000, "pids": 612, "anon": 5000, "file": 2000, "active_file": 1500,
    }
