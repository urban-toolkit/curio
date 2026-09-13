#!/usr/bin/env python3
"""How often does a fresh zygote's first child crash, with and without the warm-up fork?

Background. ``test-gpu-isolated`` failed intermittently because the job's first
isolated node died with signal 11 in DuckDB's ``close()``, inside
``codec._write_dataframe_parquet``. It was always the zygote's first child;
later children doing the same write never crashed. The zygote now forks once
before serving (``zygote._settle_before_serving``) so that no real node is the
first fork. This script checks whether that is what makes the crash go away.

Each iteration starts a fresh zygote, runs the ``DataPool_Dataframe`` node the
moment it is ready (the first fork, exactly as the e2e job does), runs it again
(a later fork), and stops the zygote. Two variants, interleaved so both see the
same load on the host:

    baseline   the zygote without the warm-up fork (the old behaviour)
    warmup     the zygote as it ships now

Limits, seccomp and the absence of an exec user match the isolated e2e job.
Linux only. Run it inside the CI image, where the libraries are the ones that
crashed:

    python scripts/repro_zygote_first_fork.py --iterations 300

Reading the verdict:

    SUPPORTED        baseline crashed on first forks, warmup never did, and
                     the difference is unlikely to be chance
    NOT REPRODUCED   neither variant crashed, so this loop did not recreate
                     the CI conditions and shows nothing either way (try
                     --load, or more iterations)
    NOT ENOUGH       warmup crashed too, so the warm-up fork does not remove
                     the cause

Exits 1 when the warmup variant crashes at all, so a CI job fails on the one
result that means the fix does not work.
"""

import argparse
import importlib.metadata
import json
import math
import os
import platform
import re
import selectors
import shutil
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utk_curio.sandbox.isolation import protocol, supervisor  # noqa: E402

SIGSEGV = 11

# The zygote as it was before the warm-up fork: the same entry point, with the
# settle step replaced by a no-op before main() runs.
_BASELINE_ENTRY = (
    "import sys\n"
    "from utk_curio.sandbox.isolation import zygote\n"
    "zygote._settle_before_serving = lambda: None\n"
    "sys.exit(zygote.main(sys.argv[1:]))\n"
)

ZYGOTE_ARGS = {
    "baseline": ["-c", _BASELINE_ENTRY],
    "warmup": ["-m", "utk_curio.sandbox.isolation.zygote"],
}

# The e2e job's only crash site was this node. "int" is the column shape of
# test_isolation_linux.py::test_a_dataframe_survives_the_boundary, which never
# crashed, for telling "first fork" apart from "first fork with a string column".
_INT_NODE = "import pandas as pd\n\nreturn pd.DataFrame({'a': [1, 2, 3]})\n"

_SETTLE_LINE = re.compile(r"threads before the warm-up fork: (\d+) .*; after: (\d+)")

READY_TIMEOUT_SECONDS = 180


def node_code(shape):
    """The node's body, indented the way /exec receives it."""
    if shape == "int":
        body = _INT_NODE
    else:
        path = os.path.join(REPO_ROOT, "docs", "examples", "dataflows",
                            "DataPool_Dataframe.json")
        with open(path, encoding="utf-8") as handle:
            flow = json.load(handle)
        flow = flow.get("dataflow", flow)
        body = next(node["content"] for node in flow["nodes"]
                    if node.get("type") == "curio.builtin/data-loading")
    return textwrap.indent(body, "    ")


# ---------------------------------------------------------------------------
# One zygote
# ---------------------------------------------------------------------------

def start_zygote(variant, socket_path, env, stderr_file):
    """Spawn a zygote the way lifecycle.ensure_running does, and wait for READY."""
    command = [sys.executable, "-u", *ZYGOTE_ARGS[variant], "--socket", socket_path]
    process = subprocess.Popen(
        command, cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE,
        stderr=stderr_file, text=True, start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"the {variant} zygote exited with {process.returncode} "
                    "before it was ready"
                )
            if selector.select(timeout=0.5) and \
                    process.stdout.readline().strip() == "ZYGOTE_READY":
                return process
        raise RuntimeError(f"the {variant} zygote was not ready within "
                           f"{READY_TIMEOUT_SECONDS}s")
    except BaseException:
        stop_zygote(process)
        raise
    finally:
        selector.close()


def stop_zygote(process):
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
    if process.stdout:
        process.stdout.close()


def thread_count(pid):
    """Threads in *pid* right now, or None without /proc."""
    try:
        return len(os.listdir(f"/proc/{pid}/task"))
    except OSError:
        return None


def run_node(socket_path, shared_data_dir, code, limits, wall_timeout):
    """One execution through the zygote, classified. Never raises."""
    scratch_dir = supervisor.make_scratch_dir(shared_data_dir)
    try:
        request = protocol.build_exec_request(
            code=code,
            node_type="curio.builtin/data-loading",
            data_type="",
            scratch_dir=scratch_dir,
            input_spec=dict(protocol.INPUT_NONE),
            work_dir=REPO_ROOT,
            limits=limits,
            wall_timeout=wall_timeout,
        )
        exit_code, signal_number, timed_out = supervisor.ZygoteClient(
            socket_path
        ).run(request, wall_timeout=wall_timeout)
        if timed_out:
            return {"outcome": "timeout"}
        if signal_number is not None:
            return {"outcome": "crash" if signal_number == SIGSEGV else "signal",
                    "signal": signal_number}
        if exit_code not in (0, None):
            return {"outcome": "exit", "exit": exit_code}
        manifest = supervisor.read_child_manifest(scratch_dir)
        if not manifest["ok"]:
            return {"outcome": "node-error", "stderr": manifest["stderr"][-2000:]}
        return {"outcome": "ok"}
    except Exception as exc:  # noqa: BLE001 - one bad iteration must not end the run
        return {"outcome": "harness-error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        supervisor.cleanup_scratch(scratch_dir)


def one_iteration(variant, index, workspace, env, args, code, limits):
    """Fresh zygote, N executions, stop. Returns the iteration's record."""
    socket_path = os.path.join(workspace, f"z-{variant}-{index}.sock")
    stderr_path = os.path.join(workspace, f"z-{variant}-{index}.stderr")
    record = {"variant": variant, "iteration": index, "execs": []}
    with open(stderr_path, "w+", encoding="utf-8", errors="replace") as stderr_file:
        try:
            process = start_zygote(variant, socket_path, env, stderr_file)
        except Exception as exc:  # noqa: BLE001
            record["start_error"] = str(exc)
        else:
            try:
                record["threads_at_ready"] = thread_count(process.pid)
                for _ in range(args.execs_per_zygote):
                    record["execs"].append(run_node(
                        socket_path, os.path.join(workspace, "data"), code,
                        limits, args.timeout,
                    ))
            finally:
                stop_zygote(process)
        stderr_file.seek(0)
        stderr_text = stderr_file.read()
    os.remove(stderr_path)
    if os.path.exists(socket_path):
        os.remove(socket_path)

    settle = _SETTLE_LINE.search(stderr_text)
    if settle:
        record["threads_before_warmup"] = int(settle.group(1))
        record["threads_after_warmup"] = int(settle.group(2))
    if any(e["outcome"] == "crash" for e in record["execs"]):
        # The children's faulthandler tracebacks, for comparing with CI's.
        start = stderr_text.find("Fatal Python error")
        record["crash_log"] = stderr_text[start:start + 3000] if start >= 0 \
            else stderr_text[-3000:]
    return record


# ---------------------------------------------------------------------------
# Load and statistics
# ---------------------------------------------------------------------------

# "auto" load: half the CPUs, but never more than this. The runner also hosts
# production, and the e2e job it stands in for runs about six busy workers.
AUTO_LOAD_CAP = 8


def resolve_load(value, cpus):
    """The number of busy processes for ``--load``: an integer, or "auto"."""
    if value == "auto":
        return min(AUTO_LOAD_CAP, max(1, (cpus or 2) // 2))
    count = int(value)
    if count < 0:
        raise ValueError("--load cannot be negative")
    return count


def start_load(count):
    """Busy processes, to mimic the browser and GPU work of the e2e job."""
    return [
        subprocess.Popen([sys.executable, "-c", "while True: pass"],
                         start_new_session=True)
        for _ in range(count)
    ]


def one_sided_fisher(crashes_a, n_a, crashes_b, n_b):
    """P(A gets at least *crashes_a* of the crashes) if the variants were alike."""
    total, crashes = n_a + n_b, crashes_a + crashes_b
    if crashes == 0:
        return 1.0
    ways = sum(
        math.comb(crashes, k) * math.comb(total - crashes, n_a - k)
        for k in range(crashes_a, min(crashes, n_a) + 1)
    )
    return ways / math.comb(total, n_a)


def summarize(records, variants):
    summary = {}
    for variant in variants:
        mine = [r for r in records if r["variant"] == variant]
        first = [r["execs"][0]["outcome"] for r in mine if r["execs"]]
        later = [e["outcome"] for r in mine for e in r["execs"][1:]]
        ready = [r["threads_at_ready"] for r in mine
                 if r.get("threads_at_ready") is not None]
        before = [r["threads_before_warmup"] for r in mine
                  if "threads_before_warmup" in r]
        summary[variant] = {
            "zygotes": len(mine),
            "start_errors": sum(1 for r in mine if "start_error" in r),
            "first_fork": {o: first.count(o) for o in sorted(set(first))},
            "later_forks": {o: later.count(o) for o in sorted(set(later))},
            "first_fork_runs": len(first),
            "later_fork_runs": len(later),
            "threads_at_ready": _spread(ready),
            "threads_before_warmup_fork": _spread(before),
        }
    return summary


def _spread(values):
    if not values:
        return None
    return {"min": min(values), "median": statistics.median(values),
            "max": max(values)}


def verdict(summary):
    base, warm = summary.get("baseline"), summary.get("warmup")
    if not base or not warm:
        return "INCOMPLETE", "run both variants to get a verdict"
    b = base["first_fork"].get("crash", 0)
    w = warm["first_fork"].get("crash", 0)
    later_crashes = (base["later_forks"].get("crash", 0)
                     + warm["later_forks"].get("crash", 0))
    note = (f" ({later_crashes} crash(es) on later forks too, so it is not only "
            "about the first fork)" if later_crashes else "")
    if w or warm["later_forks"].get("crash", 0):
        return "NOT ENOUGH", (
            f"the warmup variant still crashed: {w} of "
            f"{warm['first_fork_runs']} first forks{note}"
        )
    if b == 0:
        return "NOT REPRODUCED", (
            f"neither variant crashed in {base['first_fork_runs']} first forks "
            f"each{note}. This loop did not recreate the CI conditions; try "
            "--load, or more iterations."
        )
    p = one_sided_fisher(b, base["first_fork_runs"], w, warm["first_fork_runs"])
    if p < 0.05:
        return "SUPPORTED", (
            f"baseline crashed on {b} of {base['first_fork_runs']} first forks, "
            f"warmup on none (one-sided Fisher p = {p:.4f}){note}"
        )
    return "SUGGESTIVE", (
        f"baseline crashed on {b} of {base['first_fork_runs']} first forks, "
        f"warmup on none, but p = {p:.3f} could still be chance; run more "
        f"iterations{note}"
    )


def print_table(summary):
    header = (f"{'variant':<10}{'zygotes':>8}  {'threads@ready':<15}"
              f"{'first-fork crashes':<22}{'later-fork crashes':<22}other")
    print(header)
    print("-" * len(header))
    for variant, s in summary.items():
        ready = s["threads_at_ready"]
        ready_text = (f"{ready['median']:g} ({ready['min']}-{ready['max']})"
                      if ready else "n/a")
        first_n, later_n = s["first_fork_runs"], s["later_fork_runs"]
        first_c = s["first_fork"].get("crash", 0)
        later_c = s["later_forks"].get("crash", 0)
        other = {k: v for k, v in {**s["first_fork"], **s["later_forks"]}.items()
                 if k not in ("ok", "crash")}
        if s["start_errors"]:
            other["start-error"] = s["start_errors"]
        print(f"{variant:<10}{s['zygotes']:>8}  {ready_text:<15}"
              f"{f'{first_c} / {first_n}':<22}{f'{later_c} / {later_n}':<22}"
              f"{other or '-'}")


def library_versions():
    versions = {}
    for name in ("numpy", "pandas", "pyarrow", "duckdb", "geopandas", "shapely",
                 "pyproj", "pyseccomp"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--iterations", type=int, default=300,
                        help="fresh zygotes per variant (default 300)")
    parser.add_argument("--variants", default="baseline,warmup",
                        help="comma-separated, from: baseline, warmup")
    parser.add_argument("--node", choices=("string", "int"), default="string",
                        help="DataFrame shape: the e2e node's string column "
                             "(default) or the unit test's int-only one")
    parser.add_argument("--execs-per-zygote", type=int, default=2,
                        help="executions per zygote; the first is the first "
                             "fork (default 2)")
    parser.add_argument("--load", default="0",
                        help="busy processes to run alongside: a number, or "
                             f"'auto' for half the CPUs up to {AUTO_LOAD_CAP} "
                             "(default 0)")
    parser.add_argument("--memory-mb", type=int,
                        default=supervisor.DEFAULT_LIMITS["memory_mb"])
    parser.add_argument("--timeout", type=int,
                        default=supervisor.DEFAULT_WALL_TIMEOUT_SECONDS,
                        help="wall-clock limit per execution, also the CPU "
                             "limit, as in the sandbox (default 300)")
    parser.add_argument("--report", help="write the full JSON report here")
    args = parser.parse_args(argv)

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = [v for v in variants if v not in ZYGOTE_ARGS]
    if unknown:
        parser.error(f"unknown variant(s): {', '.join(unknown)}")
    if not sys.platform.startswith("linux"):
        print("warning: isolation only confines on Linux; elsewhere every child "
              "fails its confinement step and nothing here means anything",
              file=sys.stderr)

    limits = dict(supervisor.DEFAULT_LIMITS, memory_mb=args.memory_mb,
                  cpu_seconds=args.timeout)
    code = node_code(args.node)
    workspace = tempfile.mkdtemp(prefix="zygote-repro-")
    os.makedirs(os.path.join(workspace, "data"), exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (REPO_ROOT, env.get("PYTHONPATH")) if p
    )
    env["CURIO_SHARED_DATA"] = os.path.join(workspace, "data")

    try:
        cpus = len(os.sched_getaffinity(0))
    except AttributeError:
        cpus = os.cpu_count()
    try:
        args.load = resolve_load(args.load, cpus)
    except ValueError as exc:
        parser.error(f"--load: {exc}")
    print(f"zygote first-fork repro: {args.iterations} iterations x "
          f"{len(variants)} variant(s), node={args.node}, "
          f"execs/zygote={args.execs_per_zygote}, load={args.load}, cpus={cpus}")
    print(f"libraries: {library_versions()}")

    load = start_load(args.load)
    records = []
    started = time.monotonic()
    try:
        for index in range(args.iterations):
            # Alternate the order so neither variant always goes first.
            order = variants if index % 2 == 0 else list(reversed(variants))
            for variant in order:
                records.append(one_iteration(variant, index, workspace, env,
                                             args, code, limits))
            if (index + 1) % 25 == 0 or index + 1 == args.iterations:
                crashes = {
                    v: sum(1 for r in records if r["variant"] == v
                           for e in r["execs"] if e["outcome"] == "crash")
                    for v in variants
                }
                print(f"  {index + 1}/{args.iterations} "
                      f"({time.monotonic() - started:.0f}s) crashes so far: "
                      f"{crashes}", flush=True)
    finally:
        for process in load:
            process.kill()
        shutil.rmtree(workspace, ignore_errors=True)

    summary = summarize(records, variants)
    label, detail = verdict(summary)
    print()
    print_table(summary)
    print()
    print(f"verdict: {label}: {detail}")

    crash_logs = [r["crash_log"] for r in records if "crash_log" in r]
    if crash_logs:
        print("\nfirst crash log:\n" + crash_logs[0])

    if args.report:
        report = {
            "config": {**vars(args), "cpus": cpus,
                       "python": platform.python_version()},
            "libraries": library_versions(),
            "summary": summary,
            "verdict": {"label": label, "detail": detail},
            "crash_logs": crash_logs[:5],
            "records": records,
        }
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        print(f"\nreport written to {args.report}")

    warm = summary.get("warmup")
    warm_crashed = bool(warm) and (warm["first_fork"].get("crash", 0)
                                   + warm["later_forks"].get("crash", 0)) > 0
    return 1 if warm_crashed else 0


if __name__ == "__main__":
    sys.exit(main())
