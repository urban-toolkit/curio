"""Diagnostic only, never merged: what #408's replay sandbox keeps at rest.

Runs the image's own replay (utk_curio/sandbox/tests/_rerun_memory.py, from
/app) several times and records, at the end of every 1 s rest, the sandbox's
/proc status (anonymous and file-backed RSS, threads) and its anonymous RSS
by mapping kind from /proc/<pid>/smaps. Everything is read from outside the
sandbox. A variant changes only the environment the sandbox starts with:

* baseline: as test_rerun_memory.py starts it today;
* launch: through isolation/lifecycle.server_environment, as curio.py's
  start_sandbox starts it since #1210;
* arrow_system: only ARROW_DEFAULT_MEMORY_POOL=system;
* arena16: only MALLOC_ARENA_MAX=16.

Usage, inside the CI image:
    python rerun_memory_probe.py --variant baseline --samples 3 --cycles 10 --out x.json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, "/app")

from utk_curio.sandbox.tests import _rerun_memory as rr  # noqa: E402

MB = 1024 * 1024
KB = 1024
STATE = {"pid": None, "variant": "baseline", "snaps": [], "diag": False, "port": None}

#: Appended to the replay's sitecustomize with --diag: a route the sandbox
#: answers before Flask (so the idle release does not run for it) with what
#: holds its memory, read inside the process.
DIAG_SITE = r'''
import json as _diag_json
import os as _diag_os


def _anon_mb():
    with open("/proc/self/status") as handle:
        for line in handle:
            if line.startswith("RssAnon:"):
                return int(line.split()[1]) / 1024


def _obmalloc():
    import re
    import sys
    import tempfile

    with tempfile.TemporaryFile(mode="w+") as sink:
        saved = _diag_os.dup(2)
        try:
            sys.stderr.flush()
            _diag_os.dup2(sink.fileno(), 2)
            sys._debugmallocstats()
        finally:
            sys.stderr.flush()
            _diag_os.dup2(saved, 2)
            _diag_os.close(saved)
        sink.seek(0)
        text = sink.read()
    found = {}
    for key, pattern in (("arenas_current", r"# arenas allocated current\s*=\s*([\d,]+)"),
                         ("arenas_total", r"# arenas allocated total\s*=\s*([\d,]+)"),
                         ("arenas_highwater", r"# arenas highwater mark\s*=\s*([\d,]+)"),
                         ("bytes_in_blocks", r"# bytes in allocated blocks\s*=\s*([\d,]+)"),
                         ("bytes_in_free_blocks", r"# bytes in available blocks\s*=\s*([\d,]+)"),
                         ("unused_pools_bytes", r"unused pools \* \d+ bytes\s*=\s*([\d,]+)"),
                         ("arena_bytes", r"Total\s*=\s*([\d,]+)")):
        match = re.search(pattern, text)
        if match:
            found[key] = int(match.group(1).replace(",", ""))
    return found


def _counts_by_type(limit=12):
    import gc

    counts = {}
    for obj in gc.get_objects():
        name = type(obj).__name__
        counts[name] = counts.get(name, 0) + 1
    top = sorted(counts.items(), key=lambda item: -item[1])[:limit]
    return {"total": sum(counts.values()), "top": top}


def _diag_payload(intervene=False):
    import ctypes
    import gc
    import re
    import sys
    import tempfile

    out = {"anon_mb": _anon_mb(), "obmalloc": _obmalloc(), "gc_counts": gc.get_count(),
           "gc_objects": _counts_by_type()}
    if intervene:
        started = __import__("time").perf_counter()
        found = gc.collect()
        out["gc_collected"] = found
        out["gc_seconds"] = round(__import__("time").perf_counter() - started, 3)
        out["after_gc"] = {"anon_mb": _anon_mb(), "obmalloc": _obmalloc()}
        from utk_curio.sandbox.util.memory_release import release_free_memory
        release_free_memory()
        out["after_gc_release"] = {"anon_mb": _anon_mb(), "obmalloc": _obmalloc()}
        try:
            from utk_curio.sandbox.util import db

            raw = object.__getattribute__(db._connection, "_con")
            cur = raw.cursor()
            cur.execute("SET GLOBAL allocator_background_threads = true")
            cur.close()
            __import__("time").sleep(4)
            out["after_duckdb_background"] = {"anon_mb": _anon_mb()}
        except Exception as exc:  # noqa: BLE001
            out["duckdb_background_error"] = repr(exc)
        pa_mod = sys.modules.get("pyarrow")
        if pa_mod is not None:
            try:
                pa_mod.jemalloc_set_decay_ms(0)
                pa_mod.jemalloc_memory_pool().release_unused()
                __import__("time").sleep(1)
                out["after_arrow_jemalloc"] = {"anon_mb": _anon_mb()}
            except Exception as exc:  # noqa: BLE001
                out["arrow_jemalloc_error"] = repr(exc)
    pa = sys.modules.get("pyarrow")
    if pa is not None:
        pool = pa.default_memory_pool()
        out["arrow"] = {"backend": pool.backend_name, "pool_allocated": pool.bytes_allocated(),
                        "total_allocated": pa.total_allocated_bytes()}

    class _M2(ctypes.Structure):
        _fields_ = [(n, ctypes.c_size_t) for n in (
            "arena", "ordblks", "smblks", "hblks", "hblkhd", "usmblks", "fsmblks",
            "uordblks", "fordblks", "keepcost")]

    libc = ctypes.CDLL(None)
    try:
        info = libc.mallinfo2
        info.restype = _M2
        got = info()
        out["mallinfo2"] = {n: getattr(got, n) for n, _ in _M2._fields_}
    except AttributeError:
        pass
    try:
        libc.fopen.restype = ctypes.c_void_p
        libc.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        libc.fclose.argtypes = [ctypes.c_void_p]
        libc.malloc_info.argtypes = [ctypes.c_int, ctypes.c_void_p]
        with tempfile.TemporaryDirectory() as folder:
            path = _diag_os.path.join(folder, "m.xml")
            stream = libc.fopen(path.encode(), b"w")
            libc.malloc_info(0, stream)
            libc.fclose(stream)
            xml = open(path).read()
        rows = []
        for nr, body in re.findall(r'<heap nr="(\d+)">(.*?)</heap>', xml, re.S):
            fast = re.search(r'<total type="fast" count="\d+" size="(\d+)"', body)
            rest = re.search(r'<total type="rest" count="\d+" size="(\d+)"', body)
            cur = re.search(r'<system type="current" size="(\d+)"', body)
            rows.append([int(nr), int(fast.group(1)) if fast else 0,
                         int(rest.group(1)) if rest else 0, int(cur.group(1)) if cur else 0])
        out["arenas_nr_fast_rest_current"] = rows
        out["malloc_totals"] = re.findall(
            r'<(total|system|aspace) type="(\w+)"(?: count="\d+")? size="(\d+)"', xml.split("</heap>")[-1])
    except Exception as exc:  # noqa: BLE001
        out["malloc_info_error"] = repr(exc)
    counts, nbytes = {}, {}
    for obj in gc.get_objects():
        name = type(obj).__name__
        if name in ("DataFrame", "GeoDataFrame", "Series", "GeoSeries", "Table", "RecordBatch",
                    "ChunkedArray", "BlockManager", "GeometryArray", "ArrowStringArray"):
            counts[name] = counts.get(name, 0) + 1
            try:
                value = getattr(obj, "nbytes", 0)
                nbytes[name] = nbytes.get(name, 0) + (int(value) if not callable(value) else 0)
            except Exception:  # noqa: BLE001
                pass
    out["objects"] = counts
    out["object_nbytes"] = nbytes
    out["threads"] = [t.name for t in __import__("threading").enumerate()]
    try:
        from utk_curio.sandbox.util import db

        con = db._connection
        if con is not None:
            raw = object.__getattribute__(con, "_con")
            cur = raw.cursor()
            out["duckdb_memory"] = cur.execute(
                "SELECT tag, memory_usage_bytes, temporary_storage_bytes FROM duckdb_memory() "
                "WHERE memory_usage_bytes > 0 OR temporary_storage_bytes > 0").fetchall()
            out["duckdb_settings"] = cur.execute(
                "SELECT name, value FROM duckdb_settings() WHERE name IN ('memory_limit', 'threads', "
                "'enable_external_file_cache', 'allocator_background_threads', "
                "'allocator_flush_threshold', 'allocator_bulk_deallocation_flush_threshold')").fetchall()
            cur.close()
    except Exception as exc:  # noqa: BLE001
        out["duckdb_error"] = repr(exc)
    return out


import flask as _diag_flask

_diag_orig_call = _diag_flask.Flask.__call__


def _diag_call(self, environ, start_response):
    if environ.get("PATH_INFO") == "/__diag_mem":
        intervene = "intervene" in environ.get("QUERY_STRING", "")
        body = _diag_json.dumps(_diag_payload(intervene), default=str).encode()
        start_response("200 OK", [("Content-Type", "application/json"),
                                  ("Content-Length", str(len(body)))])
        return [body]
    return _diag_orig_call(self, environ, start_response)


_diag_flask.Flask.__call__ = _diag_call
'''
HEADER = re.compile(r"^([0-9a-f]+)-([0-9a-f]+) (\S{4}) \S+ \S+ \d+\s*(.*)$")


def variant_env(env):
    env = dict(env)
    if STATE.get("decorate"):
        env["GLIBC_TUNABLES"] = "glibc.mem.decorate_maps=1"
    variant = STATE["variant"].replace("_thp_off", "").replace("thp_off", "baseline")
    if variant == "launch_trim128k":
        # glibc's own default trim threshold, fixed: no dynamic raising, so
        # the mmap threshold stays at 128 KiB too.
        from utk_curio.sandbox.isolation.lifecycle import server_environment
        env = server_environment(env)
        env["MALLOC_TRIM_THRESHOLD_"] = "131072"
        return env
    if variant == "launch_mmap4m":
        from utk_curio.sandbox.isolation.lifecycle import server_environment
        env = server_environment(env)
        env["MALLOC_MMAP_THRESHOLD_"] = str(4 * MB)
        env["MALLOC_TRIM_THRESHOLD_"] = str(8 * MB)
        return env
    if variant == "launch":
        from utk_curio.sandbox.isolation.lifecycle import server_environment
        return server_environment(env)
    if variant == "arrow_system":
        env["ARROW_DEFAULT_MEMORY_POOL"] = "system"
    elif variant == "arena16":
        env["MALLOC_ARENA_MAX"] = "16"
    elif variant != "baseline":
        raise SystemExit(f"unknown variant {variant}")
    return env


_real_popen = subprocess.Popen


def _thp_off():
    """PR_SET_THP_DISABLE (41): no transparent huge pages for this process and
    what it execs, whatever the host's setting."""
    import ctypes

    ctypes.CDLL(None, use_errno=True).prctl(41, 1, 0, 0, 0)


def _popen(args, **kwargs):
    kwargs["env"] = variant_env(kwargs.get("env") or os.environ)
    if STATE["variant"].endswith("thp_off"):
        kwargs["preexec_fn"] = _thp_off
    proc = _real_popen(args, **kwargs)
    STATE["pid"] = proc.pid
    STATE["port"] = kwargs["env"].get("FLASK_SANDBOX_PORT")
    return proc


def _inside(intervene=False):
    import requests

    query = "?intervene=1" if intervene else ""
    try:
        return requests.get(f"http://127.0.0.1:{STATE['port']}/__diag_mem{query}", timeout=120).json()
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}


def classify(pid):
    kinds = {}
    big = []
    kind = None
    start = size = 0
    perms = ""
    with open(f"/proc/{pid}/smaps") as handle:
        for line in handle:
            match = HEADER.match(line)
            if match:
                start, end = int(match.group(1), 16), int(match.group(2), 16)
                perms, path = match.group(3), match.group(4).strip()
                size = end - start
                if path and not path.startswith("["):
                    kind = "file"
                elif path == "[heap]":
                    kind = "main_heap"
                elif path.startswith("[anon:"):
                    # glibc.mem.decorate_maps names glibc's own mappings.
                    kind = "named:" + re.sub(r"[^a-z: ]", "", path[6:].lower()).strip()[:40]
                elif path.startswith("["):
                    kind = "special"
                elif "w" not in perms:
                    kind = "reserved"
                elif size >= 256 * MB:
                    kind = "big_anon"
                elif start % (64 * MB) == 0 and size <= 64 * MB:
                    kind = "glibc_heap"
                elif size == 8 * MB:
                    kind = "stack_8m"
                else:
                    kind = "other_anon"
                continue
            if line.startswith("Rss:") and kind:
                rss = int(line.split()[1]) * KB
                kinds[kind] = kinds.get(kind, 0) + rss
                if kind != "file" and rss >= 8 * MB:
                    big.append([hex(start), round(size / MB, 1), perms, kind, round(rss / MB, 1)])
            elif line.startswith("AnonHugePages:") and kind:
                huge = int(line.split()[1]) * KB
                if huge:
                    kinds[kind + "_thp"] = kinds.get(kind + "_thp", 0) + huge
            elif line.startswith("THPeligible:") and kind and kind != "file":
                if line.split()[1] == "1":
                    kinds["thp_eligible_maps"] = kinds.get("thp_eligible_maps", 0) + MB
    big.sort(key=lambda row: -row[4])
    return {k: round(v / MB, 1) for k, v in sorted(kinds.items())}, big[:12]


def snapshot(pid):
    status = {}
    with open(f"/proc/{pid}/status") as handle:
        for line in handle:
            key, _, value = line.partition(":")
            if key in ("VmRSS", "RssAnon", "RssFile", "RssShmem"):
                status[key] = round(int(value.split()[0]) * KB / MB, 1)
            elif key in ("Threads", "THP_enabled"):
                status[key] = int(value)
    kinds, big = classify(pid)
    env = {}
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        for item in raw:
            name, _, value = item.decode(errors="replace").partition("=")
            if name in ("MALLOC_ARENA_MAX", "ARROW_DEFAULT_MEMORY_POOL", "MALLOC_TRIM_THRESHOLD_",
                        "MALLOC_MMAP_THRESHOLD_"):
                env[name] = value
    except OSError:
        pass
    return {"status": status, "kinds": kinds, "big": big, "env": env}


def _sleep(seconds):
    time.sleep(seconds)
    if seconds == 1.0 and STATE["pid"]:
        try:
            snap = snapshot(STATE["pid"])
        except OSError as exc:
            snap = {"error": str(exc)}
        if STATE["diag"] and len(STATE["snaps"]) in (0, 1, 3, 6, STATE["cycles"]):
            snap["inside"] = _inside(intervene=len(STATE["snaps"]) == STATE["cycles"])
        STATE["snaps"].append(snap)


rr.subprocess = types.SimpleNamespace(Popen=_popen, STDOUT=subprocess.STDOUT,
                                      TimeoutExpired=subprocess.TimeoutExpired)
rr.time = types.SimpleNamespace(sleep=_sleep, monotonic=time.monotonic)


def one(rows, cycles, workdir, replay_variants=()):
    STATE["snaps"] = []
    STATE["pid"] = None
    STATE["cycles"] = cycles
    report = rr.run(rows=rows, cycles=cycles, variants=replay_variants, workdir=workdir,
                    log=lambda _: None)
    data = report.to_json()
    data["unit_bytes"] = report.unit
    data["baseline_bytes"] = report.baseline
    data["ratios"] = [round((after - report.baseline) / report.unit, 3) if report.unit else None
                      for after in report.cycle_after]
    data["snaps"] = STATE["snaps"]
    data["samples"] = report.samples
    data["table"] = report.table()
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="baseline")
    parser.add_argument("--label", default="")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--rows", type=int, default=200_000)
    parser.add_argument("--out", required=True)
    parser.add_argument("--diag", action="store_true")
    parser.add_argument("--decorate", action="store_true",
                        help="name glibc's mappings (glibc.mem.decorate_maps)")
    parser.add_argument("--replay-variant", default="",
                        help="comma-separated _rerun_memory variants, such as gc")
    args = parser.parse_args()
    STATE["variant"] = args.variant
    STATE["diag"] = args.diag
    STATE["decorate"] = args.decorate
    if args.diag:
        rr._SITECUSTOMIZE = rr._SITECUSTOMIZE + DIAG_SITE
    results = []
    with tempfile.TemporaryDirectory(prefix="probe-") as workdir:
        for sample in range(args.samples):
            data = one(args.rows, args.cycles, Path(workdir),
                       tuple(v for v in args.replay_variant.split(",") if v))
            data.update({"variant": args.variant, "label": args.label, "sample": sample})
            results.append(data)
            base = data["snaps"][0] if data["snaps"] else {}
            last = data["snaps"][-1] if data["snaps"] else {}
            print(f"### {args.label} {args.variant} sample {sample}")
            print("```")
            print(data["table"])
            print("at_rest/unit per cycle:", data["ratios"])
            print("sandbox env:", base.get("env"))
            print("baseline status:", base.get("status"), "kinds:", base.get("kinds"))
            print("last rest status:", last.get("status"), "kinds:", last.get("kinds"))
            print("last rest biggest anon mappings:", last.get("big"))
            print("```", flush=True)
            Path(args.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
