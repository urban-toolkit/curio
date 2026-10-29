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
STATE = {"pid": None, "variant": "baseline", "snaps": []}
HEADER = re.compile(r"^([0-9a-f]+)-([0-9a-f]+) (\S{4}) \S+ \S+ \d+\s*(.*)$")


def variant_env(env):
    env = dict(env)
    variant = STATE["variant"].replace("_thp_off", "").replace("thp_off", "baseline")
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
    return proc


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
            if name in ("MALLOC_ARENA_MAX", "ARROW_DEFAULT_MEMORY_POOL"):
                env[name] = value
    except OSError:
        pass
    return {"status": status, "kinds": kinds, "big": big, "env": env}


def _sleep(seconds):
    time.sleep(seconds)
    if seconds == 1.0 and STATE["pid"]:
        try:
            STATE["snaps"].append(snapshot(STATE["pid"]))
        except OSError as exc:
            STATE["snaps"].append({"error": str(exc)})


rr.subprocess = types.SimpleNamespace(Popen=_popen, STDOUT=subprocess.STDOUT,
                                      TimeoutExpired=subprocess.TimeoutExpired)
rr.time = types.SimpleNamespace(sleep=_sleep, monotonic=time.monotonic)


def one(rows, cycles, workdir):
    STATE["snaps"] = []
    STATE["pid"] = None
    report = rr.run(rows=rows, cycles=cycles, workdir=workdir, log=lambda _: None)
    data = report.to_json()
    data["unit_bytes"] = report.unit
    data["baseline_bytes"] = report.baseline
    data["ratios"] = [round((after - report.baseline) / report.unit, 3) if report.unit else None
                      for after in report.cycle_after]
    data["snaps"] = STATE["snaps"]
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
    args = parser.parse_args()
    STATE["variant"] = args.variant
    results = []
    with tempfile.TemporaryDirectory(prefix="probe-") as workdir:
        for sample in range(args.samples):
            data = one(args.rows, args.cycles, Path(workdir))
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
