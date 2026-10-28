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


#: Part of a process's smaps: a file mapping, the brk heap, a large anonymous
#: mapping with lazily freed pages, an arena-sized one, a guard page and a
#: small one.
SMAPS = """\
55d5c3a4e000-55d5c3a50000 r--p 00000000 08:01 1234 /usr/bin/python3.12
Size:                  8 kB
Rss:                   8 kB
VmFlags: rd mr mw me
55d5c4000000-55d5c6000000 rw-p 00000000 00:00 0                          [heap]
Size:              32768 kB
Rss:               26000 kB
7f0000000000-7f0040000000 rw-p 00000000 00:00 0
Size:            1048576 kB
Rss:              500000 kB
LazyFree:         120000 kB
7f1000000000-7f1004000000 rw-p 00000000 00:00 0
Size:              65536 kB
Rss:               40000 kB
7f2000000000-7f2000001000 ---p 00000000 00:00 0
Size:                  4 kB
Rss:                   0 kB
7f3000000000-7f3000080000 rw-p 00000000 00:00 0
Size:                512 kB
Rss:                 512 kB
"""


def test_a_processs_anonymous_mappings_are_kept_by_size_and_lazily_freed_bytes(tmp_path):
    probe = _load()
    (tmp_path / "123").mkdir()
    (tmp_path / "123" / "smaps").write_text(SMAPS)
    kib = 1024
    assert probe.anon_maps("123", proc=tmp_path) == {
        "heap": 26000 * kib, "anon_maps": 3, "anon_total": (500000 + 40000 + 512) * kib,
        "biggest": [500000 * kib, 40000 * kib, 512 * kib],
        "biggest_size": [1048576 * kib, 65536 * kib, 512 * kib],
        "lazy_free": 120000 * kib, "under_1m": 512 * kib,
    }
