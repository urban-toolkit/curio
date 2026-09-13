#!/usr/bin/env python3
"""How often does a forked child crash in DuckDB, with and without the zygote releasing DuckDB?

Background. Isolated execution intermittently failed with "This node was killed
by signal 11": a child forked from the zygote died in DuckDB's ``close()``,
inside ``codec._write_dataframe_parquet``. ``import duckdb`` opens a default
connection with a pool of threads, the zygote imports duckdb while warming up,
and DuckDB's state is not fork-safe (duckdb/duckdb-python#292). The zygote now
closes that connection before serving (``zygote._release_import_time_duckdb``).
This script measures whether that removes the crash.

Each iteration starts a fresh zygote, runs the ``DataPool_Dataframe`` node the
moment it is ready, runs it again, and stops the zygote. Two variants,
interleaved so both see the same load on the host:

    baseline   the zygote without the release (DuckDB's threads stay alive)
    released   the zygote as it ships now

Limits, seccomp and the absence of an exec user match the isolated e2e job.
Linux only. Run it inside the CI image, where the libraries are the ones that
crashed:

    python scripts/repro_zygote_fork_crash.py --iterations 300

It starts with a thread census: which of the zygote's imports start threads,
and what the zygote is left with after the release.

Reading the verdict:

    SUPPORTED        baseline crashed, released never did, and the difference
                     is unlikely to be chance
    NOT REPRODUCED   neither variant crashed, so this run shows nothing either
                     way (try --load, or more iterations)
    NOT ENOUGH       released crashed too, so the release does not remove the
                     cause

Exits 1 when the released variant crashes at all, so a CI job fails on the one
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

# The zygote without the release: the same entry point, with the release
# replaced by a no-op before main() runs.
_BASELINE_ENTRY = (
    "import sys\n"
    "from utk_curio.sandbox.isolation import zygote\n"
    "zygote._release_import_time_duckdb = lambda: None\n"
    "sys.exit(zygote.main(sys.argv[1:]))\n"
)

ZYGOTE_ARGS = {
    "baseline": ["-c", _BASELINE_ENTRY],
    "released": ["-m", "utk_curio.sandbox.isolation.zygote"],
}

# The e2e job's crash site was this node. "int" is the column shape of
# test_isolation_linux.py::test_a_dataframe_survives_the_boundary.
_INT_NODE = "import pandas as pd\n\nreturn pd.DataFrame({'a': [1, 2, 3]})\n"

_RELEASE_LINE = re.compile(r"released DuckDB's import-time connection: threads (\d+) .*-> (\d+)")

# The libraries the zygote imports while warming up, one at a time for the census.
CENSUS_MODULES = ("numpy", "pyarrow", "pandas", "duckdb", "geopandas", "shapely", "pyproj")

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
# Thread census
# ---------------------------------------------------------------------------

_CENSUS_HELPER = textwrap.dedent("""
    import collections, os, sys
    def names():
        try:
            ids = os.listdir("/proc/self/task")
        except OSError:
            return None
        out = []
        for tid in ids:
            try:
                with open(f"/proc/self/task/{tid}/comm") as handle:
                    out.append(handle.read().strip())
            except OSError:
                pass
        return out
    def describe(found):
        if found is None:
            return "n/a (no /proc)"
        counts = collections.Counter(found)
        return f"{len(found)} (" + ", ".join(f"{n} x{c}" for n, c in counts.most_common()) + ")"
""")


def thread_census(env):
    """Threads started by each import, and what the warmed-up zygote keeps."""
    lines = []
    for module in CENSUS_MODULES:
        code = _CENSUS_HELPER + f"import {module}\nprint(describe(names()))\n"
        lines.append((f"import {module}", _run_census(code, env, lines=1)[0]))
    code = _CENSUS_HELPER + textwrap.dedent("""
        from utk_curio.sandbox.isolation import zygote
        zygote.build_namespace_template()
        print(describe(names()))
        zygote._release_import_time_duckdb()
        print(describe(names()))
    """)
    before, after = _run_census(code, env, lines=2)
    lines.append(("zygote imports", before))
    lines.append(("  after the release", after))
    return lines


def _run_census(code, env, *, lines):
    """The last *lines* lines the census interpreter printed."""
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env,
                            capture_output=True, text=True, timeout=300)
    output = result.stdout.strip().splitlines()
    if result.returncode != 0 or len(output) < lines:
        tail = (result.stderr.strip().splitlines() or ["no output"])[-1]
        return [f"failed: {tail}"] * lines
    return output[-lines:]


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

    release = _RELEASE_LINE.search(stderr_text)
    if release:
        record["threads_before_release"] = int(release.group(1))
        record["threads_after_release"] = int(release.group(2))
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
# production, and the e2e job this stands in for runs about six busy workers.
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
        summary[variant] = {
            "zygotes": len(mine),
            "start_errors": sum(1 for r in mine if "start_error" in r),
            "first_fork": {o: first.count(o) for o in sorted(set(first))},
            "later_forks": {o: later.count(o) for o in sorted(set(later))},
            "first_fork_runs": len(first),
            "later_fork_runs": len(later),
            "crashes": first.count("crash") + later.count("crash"),
            "runs": len(first) + len(later),
            "threads_at_ready": _spread(ready),
        }
    return summary


def _spread(values):
    if not values:
        return None
    return {"min": min(values), "median": statistics.median(values),
            "max": max(values)}


def verdict(summary):
    base, released = summary.get("baseline"), summary.get("released")
    if not base or not released:
        return "INCOMPLETE", "run both variants to get a verdict"
    b, r = base["crashes"], released["crashes"]
    if r:
        return "NOT ENOUGH", (
            f"the released variant still crashed: {r} of {released['runs']} "
            f"executions (baseline {b} of {base['runs']})"
        )
    if b == 0:
        return "NOT REPRODUCED", (
            f"neither variant crashed in {base['runs']} executions each. This "
            "run did not recreate the CI conditions; try --load, or more "
            "iterations."
        )
    p = one_sided_fisher(b, base["runs"], r, released["runs"])
    if p < 0.05:
        return "SUPPORTED", (
            f"baseline crashed in {b} of {base['runs']} executions, released "
            f"in none of {released['runs']} (one-sided Fisher p = {p:.4f})"
        )
    return "SUGGESTIVE", (
        f"baseline crashed in {b} of {base['runs']} executions, released in "
        f"none, but p = {p:.3f} could still be chance; run more iterations"
    )


def print_table(summary):
    header = (f"{'variant':<10}{'zygotes':>8}  {'threads@ready':<15}"
              f"{'crashes (1st fork)':<20}{'crashes (later)':<18}"
              f"{'crashes (all)':<16}other")
    print(header)
    print("-" * len(header))
    for variant, s in summary.items():
        ready = s["threads_at_ready"]
        ready_text = (f"{ready['median']:g} ({ready['min']}-{ready['max']})"
                      if ready else "n/a")
        first = f"{s['first_fork'].get('crash', 0)} / {s['first_fork_runs']}"
        later = f"{s['later_forks'].get('crash', 0)} / {s['later_fork_runs']}"
        total = f"{s['crashes']} / {s['runs']}"
        other = {k: v for k, v in {**s["first_fork"], **s["later_forks"]}.items()
                 if k not in ("ok", "crash")}
        if s["start_errors"]:
            other["start-error"] = s["start_errors"]
        print(f"{variant:<10}{s['zygotes']:>8}  {ready_text:<15}{first:<20}"
              f"{later:<18}{total:<16}{other or '-'}")


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
    parser.add_argument("--variants", default="baseline,released",
                        help="comma-separated, from: baseline, released")
    parser.add_argument("--node", choices=("string", "int"), default="string",
                        help="DataFrame shape: the e2e node's string column "
                             "(default) or the unit test's int-only one")
    parser.add_argument("--execs-per-zygote", type=int, default=2,
                        help="executions per zygote (default 2)")
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
    parser.add_argument("--no-census", action="store_true",
                        help="skip the thread census at the start")
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

    try:
        cpus = len(os.sched_getaffinity(0))
    except AttributeError:
        cpus = os.cpu_count()
    try:
        args.load = resolve_load(args.load, cpus)
    except ValueError as exc:
        parser.error(f"--load: {exc}")

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

    print(f"zygote fork-crash repro: {args.iterations} iterations x "
          f"{len(variants)} variant(s), node={args.node}, "
          f"execs/zygote={args.execs_per_zygote}, load={args.load}, cpus={cpus}")
    print(f"libraries: {library_versions()}")

    census = []
    if not args.no_census:
        census = thread_census(env)
        print("thread census (a fresh interpreter per line):")
        for label, result in census:
            print(f"  {label:<22} {result}")

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
            "thread_census": census,
            "summary": summary,
            "verdict": {"label": label, "detail": detail},
            "crash_logs": crash_logs[:5],
            "records": records,
        }
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        print(f"\nreport written to {args.report}")

    released = summary.get("released")
    return 1 if released and released["crashes"] else 0


if __name__ == "__main__":
    sys.exit(main())
