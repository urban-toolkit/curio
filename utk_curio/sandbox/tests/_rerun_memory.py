"""Replay a dataflow the way the canvas runs it and record the sandbox's memory.

Issue #408: a user re-ran a dataflow of four geopandas loaders feeding a chart
on a 16 GB laptop, in a local (not isolated) launch, until the sandbox was
OOM-killed. This module reproduces that shape against a real sandbox process so
the growth can be measured, both from the unit suite (``test_rerun_memory.py``)
and by hand on any machine::

    python -m utk_curio.sandbox.tests._rerun_memory --rows 800000 --cycles 10

What one cycle does, and why:

* **Four loaders sent at the same moment.** ``triggerLevel`` in the canvas
  starts every node of a level at once, so a local sandbox has four request
  threads alive together, queued on its execution lock.
* **One transform** reading the first loader's output, as the next level.
* **A full fetch of every output**, which is what a chart, table or map does
  with its input.

The sandbox is started the way a local launch runs it: in-process execution
(``CURIO_ISOLATION=off``), no auth, the threaded Werkzeug server. Its resident
memory is sampled every 20 ms from outside, so nothing in the process being
measured changes to measure it.

``--variant`` exists to find the cause rather than to change Curio: each one
alters a single thing from outside the sandbox (an allocator setting, a cleanup
injected through ``sitecustomize``, how the level is sent), and whichever one
flattens the curve says what is holding the memory.

``--sandbox-root`` points the same replay at another checkout, for example the
build a report came from.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

ARROW_IPC_MIME = "application/vnd.apache.arrow.stream"

LOADERS = 4
VERTICES = 8
SESSION_ID = "rerun-memory"

# Each changes one thing. They combine with commas ("trim,serial").
VARIANTS = {
    "baseline": "nothing changed",
    "gc": "gc.collect() after every request",
    "trim": "gc.collect(), pyarrow release_unused() and malloc_trim(0) after every request",
    "arena2": "MALLOC_ARENA_MAX=2 in the sandbox's environment",
    "serial": "the loaders of a level are sent one at a time",
    "json": "outputs are fetched as JSON instead of Arrow",
}

MB = 1024 * 1024

# Injected into the sandbox for the gc/trim variants only. The cleanup runs in
# the WSGI close() hook, i.e. after the response has been sent, which is where
# a real fix would put it too.
_SITECUSTOMIZE = '''
import os

_variants = set(filter(None, os.environ.get("CURIO_RERUN_VARIANT", "").split(",")))

if _variants & {"gc", "trim"}:
    import gc
    import sys

    def _release():
        gc.collect()
        if "trim" not in _variants:
            return
        try:
            import pyarrow
            pyarrow.default_memory_pool().release_unused()
        except Exception:
            pass
        if sys.platform.startswith("linux"):
            try:
                import ctypes
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass

    import flask
    from werkzeug.wsgi import ClosingIterator

    _call = flask.Flask.__call__

    def __call__(self, environ, start_response):
        return ClosingIterator(_call(self, environ, start_response), [_release])

    flask.Flask.__call__ = __call__
    print(f"[rerun-memory] cleanup after every request: {sorted(_variants)}",
          file=sys.stderr, flush=True)
'''


def write_dataset(path: Path, rows: int, seed: int) -> None:
    """A building-footprint-like GeoParquet file: small polygons, ten columns."""
    import geopandas as gpd
    import numpy as np
    import shapely

    rng = np.random.default_rng(seed)
    cx = rng.uniform(-87.94, -87.52, rows)
    cy = rng.uniform(41.64, 42.02, rows)
    angles = np.linspace(0.0, 2.0 * np.pi, VERTICES, endpoint=False)
    radius = rng.uniform(5e-5, 3e-4, (rows, 1)) * rng.uniform(0.7, 1.3, (rows, VERTICES))
    ring = np.stack([cx[:, None] + radius * np.cos(angles),
                     cy[:, None] + radius * np.sin(angles)], axis=-1)
    ring = np.concatenate([ring, ring[:, :1]], axis=1)
    ids = np.arange(rows)
    frame = gpd.GeoDataFrame(
        {
            "bldg_id": ids,
            "stories": rng.integers(1, 40, rows),
            "year_built": rng.integers(1870, 2024, rows),
            "area_sqft": rng.uniform(300, 90000, rows),
            "height_ft": rng.uniform(8, 600, rows),
            "status": rng.choice(["ACTIVE", "RETIRED", "PROPOSED"], rows),
            "use_class": rng.choice(["RES", "COM", "IND", "MIX", "CIV"], rows),
            "zip": rng.choice([f"606{n:02d}" for n in range(1, 61)], rows),
            "address": np.char.add(np.char.add(ids.astype(str), " W "),
                                   rng.choice(["MADISON", "STATE", "HALSTED"], rows)),
            "condition": rng.choice(["GOOD", "FAIR", "POOR"], rows),
        },
        geometry=shapely.polygons(ring),
        crs="EPSG:4326",
    )
    frame.to_parquet(path)


def _loader_code(path: Path) -> str:
    return (
        "import geopandas as gpd\n"
        f"buildings = gpd.read_parquet({str(path)!r})\n"
        "return buildings\n"
    )


_TRANSFORM_CODE = (
    "tall = arg[arg['stories'] > 1].copy()\n"
    "tall['footprint'] = tall.geometry.area\n"
    "return tall\n"
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Sampler:
    """The sandbox's RSS every 20 ms, and the highest value since each read."""

    def __init__(self, pid: int):
        import psutil

        self._proc = psutil.Process(pid)
        self._lock = threading.Lock()
        self._peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def rss(self) -> int:
        try:
            return self._proc.memory_info().rss
        except Exception:
            return 0

    def _run(self) -> None:
        while not self._stop.is_set():
            value = self.rss()
            with self._lock:
                self._peak = max(self._peak, value)
            time.sleep(0.02)

    def take_peak(self) -> int:
        """The peak since the last call, which becomes the current RSS."""
        current = self.rss()
        with self._lock:
            peak = max(self._peak, current)
            self._peak = current
        return peak

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1)


@dataclass
class Report:
    rows: int
    cycles: int
    variants: list
    sandbox_root: str
    baseline: int = 0
    unit: int = 0
    unit_request: str = ""
    cycle_after: list = field(default_factory=list)
    cycle_peak: list = field(default_factory=list)
    samples: list = field(default_factory=list)
    killed: str = ""

    # Thresholds the unit test holds the sandbox to (see test_rerun_memory.py).
    GROWTH_SHARE = 0.25
    REST_UNITS = 1.5

    @property
    def working_set(self) -> int:
        return (self.cycle_peak[0] - self.baseline) if self.cycle_peak else 0

    @property
    def growth_per_cycle(self) -> float:
        if len(self.cycle_after) < 2:
            return 0.0
        return (self.cycle_after[-1] - self.cycle_after[0]) / (len(self.cycle_after) - 1)

    @property
    def at_rest(self) -> int:
        return (self.cycle_after[-1] - self.baseline) if self.cycle_after else 0

    def _phase_cost(self, phase: str) -> int:
        """The most one phase of a cycle raised RSS above where it started."""
        cost = 0
        for before, row in zip(self.samples, self.samples[1:]):
            if row["cycle"] >= 1 and row["phase"] == phase:
                cost = max(cost, int((row["peak_mb"] - before["rss_mb"]) * MB))
        return cost

    @property
    def compute_cost(self) -> int:
        """What running the four loaders adds, at its peak."""
        return self._phase_cost("level 0")

    @property
    def serve_cost(self) -> int:
        """What fetching every output at once adds, at its peak."""
        return self._phase_cost("fetch")

    def checks(self) -> dict:
        """Each property #408 is about: None when it holds, else why not."""
        if self.killed:
            died = f"the sandbox died: {self.killed}"
            return {"serve": died, "growth": died, "at_rest": died}
        found = {"serve": None, "growth": None, "at_rest": None}
        if self.serve_cost > self.compute_cost:
            found["serve"] = (
                f"fetching the {LOADERS + 1} outputs added {self.serve_cost / MB:.0f} MB, "
                f"more than computing them did ({self.compute_cost / MB:.0f} MB)"
            )
        limit = self.GROWTH_SHARE * self.working_set
        if self.growth_per_cycle > limit:
            found["growth"] = (
                f"RSS grew {self.growth_per_cycle / MB:.0f} MB per re-run after the first, "
                f"above {self.GROWTH_SHARE:.0%} of one run's working set "
                f"({self.working_set / MB:.0f} MB)"
            )
        rest_limit = self.REST_UNITS * self.unit
        if self.at_rest > rest_limit:
            found["at_rest"] = (
                f"at rest the sandbox holds {self.at_rest / MB:.0f} MB above its idle "
                f"baseline, more than {self.REST_UNITS}x the largest single request "
                f"({self.unit / MB:.0f} MB, {self.unit_request})"
            )
        return found

    def failures(self) -> list:
        """Why this run shows the #408 shape, or an empty list."""
        return list(dict.fromkeys(v for v in self.checks().values() if v))

    def table(self) -> str:
        lines = [
            f"rows={self.rows} cycles={self.cycles} variant={','.join(self.variants) or 'baseline'} "
            f"sandbox={self.sandbox_root}",
            f"idle baseline {self.baseline / MB:8.0f} MB",
            f"largest single request {self.unit / MB:8.0f} MB above the RSS before it ({self.unit_request})",
            "cycle   rss after   peak   (MB)",
        ]
        for index, (after, peak) in enumerate(zip(self.cycle_after, self.cycle_peak), 1):
            lines.append(f"{index:5d}  {after / MB:10.0f}  {peak / MB:6.0f}")
        lines.append(f"growth per re-run {self.growth_per_cycle / MB:.0f} MB; "
                     f"at rest {self.at_rest / MB:.0f} MB above baseline")
        lines.append(f"computing a cycle added {self.compute_cost / MB:.0f} MB; "
                     f"serving it added {self.serve_cost / MB:.0f} MB")
        verdict = self.failures()
        lines.append("verdict: " + ("; ".join(verdict) if verdict else "flat"))
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {
            "rows": self.rows, "cycles": self.cycles, "variants": self.variants,
            "sandbox_root": self.sandbox_root, "baseline_mb": self.baseline / MB,
            "unit_mb": self.unit / MB, "unit_request": self.unit_request,
            "cycle_after_mb": [v / MB for v in self.cycle_after],
            "cycle_peak_mb": [v / MB for v in self.cycle_peak],
            "growth_per_cycle_mb": self.growth_per_cycle / MB,
            "at_rest_mb": self.at_rest / MB, "killed": self.killed,
            "compute_cost_mb": self.compute_cost / MB, "serve_cost_mb": self.serve_cost / MB,
            "failures": self.failures(),
        }


class _Sandbox:
    """A sandbox process started the way a local launch starts it."""

    def __init__(self, sandbox_root: Path, workdir: Path, variants: set):
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        site = workdir / "site"
        site.mkdir(parents=True, exist_ok=True)
        (site / "sitecustomize.py").write_text(_SITECUSTOMIZE)
        env = {k: v for k, v in os.environ.items() if k != "CURIO_SANDBOX_TOKEN"}
        env.update({
            "FLASK_SANDBOX_HOST": "127.0.0.1",
            "FLASK_SANDBOX_PORT": str(self.port),
            "FLASK_USE_RELOADER": "0",
            "CURIO_ISOLATION": "off",
            "CURIO_NO_AUTH": "1",
            "CURIO_LAUNCH_CWD": str(workdir),
            "CURIO_SHARED_DATA": "./.curio/data/",
            "CURIO_RERUN_VARIANT": ",".join(sorted(variants)),
            "PYTHONPATH": os.pathsep.join([str(site), str(sandbox_root)]),
            "PYTHONUNBUFFERED": "1",
        })
        if "arena2" in variants:
            env["MALLOC_ARENA_MAX"] = "2"
        self.log_path = workdir / "sandbox.log"
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "utk_curio.sandbox.server"],
            cwd=str(sandbox_root), env=env, stdout=self._log, stderr=subprocess.STDOUT,
        )

    def wait_ready(self, timeout: float = 180.0) -> None:
        import requests

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"the sandbox exited during startup:\n{self.log_tail()}")
            try:
                if requests.get(f"{self.url}/live", timeout=2).ok:
                    return
            except Exception:
                pass
            time.sleep(0.25)
        raise RuntimeError(f"the sandbox did not answer /live in {timeout:.0f}s:\n{self.log_tail()}")

    def died(self) -> str:
        code = self.proc.poll()
        if code is None:
            return ""
        return f"exit code {code}" + (" (SIGKILL, as the OOM killer sends)" if code == -9 else "")

    def log_tail(self, lines: int = 40) -> str:
        try:
            return "\n".join(self.log_path.read_text(errors="replace").splitlines()[-lines:])
        except OSError:
            return ""

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        self._log.close()


def _exec(url: str, code: str, node_type: str, file_path: str = "", data_type: str = "") -> dict:
    import requests

    response = requests.post(f"{url}/exec", json={
        "code": textwrap.indent(code, "    "),
        "file_path": file_path,
        "nodeType": node_type,
        "dataType": data_type,
        "session_id": SESSION_ID,
    }, timeout=900)
    response.raise_for_status()
    body = response.json()
    output = body.get("output") or {}
    if not output.get("path"):
        raise RuntimeError(f"{node_type} produced no output:\n{body.get('stderr')}")
    return output


def _fetch(url: str, path: str, as_json: bool) -> int:
    import requests

    headers = ({"Accept": "application/json"} if as_json
               else {"Accept": ARROW_IPC_MIME, "X-Curio-Accept-Geometry": "wkb"})
    response = requests.get(f"{url}/get", params={"fileName": path, "sessionId": SESSION_ID},
                            headers=headers, timeout=900)
    response.raise_for_status()
    return len(response.content)


class _OverBudget(Exception):
    """The sandbox passed --stop-above-mb; stopped before the OOM killer acts."""


def run(rows: int = 200_000, cycles: int = 5, variants=(), sandbox_root: Path = REPO_ROOT,
        workdir: Path | None = None, stop_above_mb: int = 0, log=print) -> Report:
    """Replay the dataflow ``cycles`` times and return what the sandbox's RSS did.

    ``stop_above_mb`` ends the run, and reports it as the sandbox dying, once
    its peak passes that many MB. On a machine the size of the one in #408 this
    is what separates "would have been OOM-killed" from taking the machine
    (a CI runner, say) down with it.
    """
    variants = {v for v in variants if v and v != "baseline"}
    unknown = variants - set(VARIANTS)
    if unknown:
        raise ValueError(f"unknown variant(s): {', '.join(sorted(unknown))}")
    sandbox_root = Path(sandbox_root).resolve()
    owned = workdir is None
    workdir = Path(tempfile.mkdtemp(prefix="curio-rerun-")) if owned else Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    report = Report(rows=rows, cycles=cycles, variants=sorted(variants),
                    sandbox_root=str(sandbox_root))

    datasets = []
    for index in range(LOADERS):
        path = workdir / f"buildings_{index}.parquet"
        if not path.exists():
            write_dataset(path, rows, seed=index)
        datasets.append(path)

    sandbox = _Sandbox(sandbox_root, workdir, variants)
    sampler = None
    try:
        sandbox.wait_ready()
        sampler = _Sampler(sandbox.proc.pid)
        as_json = "json" in variants

        def record(cycle, phase, request):
            """Log one row; returns the peak since the previous row."""
            peak = sampler.take_peak()
            report.samples.append({
                "cycle": cycle, "phase": phase, "request": request,
                "rss_mb": round(sampler.rss() / MB, 1),
                "peak_mb": round(peak / MB, 1),
                "t": round(time.monotonic(), 3),
            })
            if stop_above_mb and peak > stop_above_mb * MB:
                raise _OverBudget(
                    f"stopped at {peak / MB:.0f} MB during cycle {cycle} ({phase}), "
                    f"above --stop-above-mb {stop_above_mb}"
                )
            return peak

        # Warm up: the first execution imports the data stack in-process.
        _exec(sandbox.url, "import geopandas\nreturn 1\n", "WARMUP")
        time.sleep(1.0)
        report.baseline = sampler.rss()
        sampler.take_peak()
        record(0, "idle", "baseline")

        # One request at a time, once, to learn what a single request costs.
        outputs = []
        for index, path in enumerate(datasets):
            before = sampler.rss()
            sampler.take_peak()
            outputs.append(_exec(sandbox.url, _loader_code(path), "DATA_LOADING"))
            cost = sampler.take_peak() - before
            if cost > report.unit:
                report.unit, report.unit_request = cost, f"loader {index}"
            record(0, "calibrate", f"loader {index}")
        before = sampler.rss()
        sampler.take_peak()
        outputs.append(_exec(sandbox.url, _TRANSFORM_CODE, "DATA_TRANSFORMATION",
                             outputs[0]["path"], outputs[0]["dataType"]))
        cost = sampler.take_peak() - before
        if cost > report.unit:
            report.unit, report.unit_request = cost, "transform"
        record(0, "calibrate", "transform")
        for index, output in enumerate(outputs):
            before = sampler.rss()
            sampler.take_peak()
            _fetch(sandbox.url, output["path"], as_json)
            cost = sampler.take_peak() - before
            if cost > report.unit:
                report.unit, report.unit_request = cost, f"fetch {index}"
            record(0, "calibrate", f"fetch {index}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=LOADERS + 1) as pool:
            for cycle in range(1, cycles + 1):
                sampler.take_peak()
                if "serial" in variants:
                    loaded = [_exec(sandbox.url, _loader_code(p), "DATA_LOADING") for p in datasets]
                else:
                    gate = threading.Barrier(LOADERS)

                    def load(path):
                        gate.wait()
                        return _exec(sandbox.url, _loader_code(path), "DATA_LOADING")

                    loaded = list(pool.map(load, datasets))
                cycle_peak = record(cycle, "level 0", f"{LOADERS} loaders")
                transformed = _exec(sandbox.url, _TRANSFORM_CODE, "DATA_TRANSFORMATION",
                                    loaded[0]["path"], loaded[0]["dataType"])
                cycle_peak = max(cycle_peak, record(cycle, "level 1", "transform"))
                list(pool.map(lambda out: _fetch(sandbox.url, out["path"], as_json),
                              loaded + [transformed]))
                cycle_peak = max(cycle_peak, record(cycle, "fetch", f"{len(loaded) + 1} outputs"))
                time.sleep(1.0)
                cycle_peak = max(cycle_peak, record(cycle, "rest", "after cycle"))
                report.cycle_after.append(sampler.rss())
                report.cycle_peak.append(cycle_peak)
                log(f"cycle {cycle}/{cycles}: rss {report.cycle_after[-1] / MB:.0f} MB, "
                    f"peak {cycle_peak / MB:.0f} MB")
    except _OverBudget as exc:
        report.killed = str(exc)
    except Exception as exc:
        report.killed = sandbox.died()
        if not report.killed:
            raise RuntimeError(f"{exc}\n--- sandbox log ---\n{sandbox.log_tail()}") from exc
    finally:
        if sampler is not None:
            sampler.stop()
        sandbox.stop()
        # Every cycle writes each output again (about nine parquet files at the
        # default size), and nothing reads them afterwards. The inputs stay, so
        # a kept --workdir can be replayed without regenerating them.
        import shutil

        shutil.rmtree(workdir / ".curio", ignore_errors=True)
        if owned:
            shutil.rmtree(workdir, ignore_errors=True)
    return report


def summarize(root: Path) -> str:
    """A markdown table of every report.json under ``root``, one row per run."""
    rows = []
    for path in sorted(Path(root).rglob("report.json")):
        data = json.loads(path.read_text())
        samples = path.with_name("samples.csv")
        if "serve_cost_mb" not in data and samples.exists():
            # A report written before these two were recorded: derive them.
            with open(samples, newline="") as handle:
                recorded = [{**row, "cycle": int(row["cycle"]), "rss_mb": float(row["rss_mb"]),
                             "peak_mb": float(row["peak_mb"])} for row in csv.DictReader(handle)]
            probe = Report(rows=0, cycles=0, variants=[], sandbox_root="", samples=recorded)
            data["compute_cost_mb"] = probe.compute_cost / MB
            data["serve_cost_mb"] = probe.serve_cost / MB
        after = data["cycle_after_mb"]
        rows.append(
            f"| {path.parent.relative_to(root)} | {data['rows']} | "
            f"{','.join(data['variants']) or 'baseline'} | {data['baseline_mb']:.0f} | "
            f"{data['unit_mb']:.0f} | {' / '.join(f'{v:.0f}' for v in after)} | "
            f"{max(data['cycle_peak_mb'] or [0]):.0f} | {data['growth_per_cycle_mb']:.0f} | "
            f"{data['at_rest_mb']:.0f} | {data.get('compute_cost_mb', 0):.0f} | "
            f"{data.get('serve_cost_mb', 0):.0f} | "
            f"{'; '.join(data['failures']) or 'flat'} |"
        )
    header = (
        "| run | rows | variant | idle MB | one request MB | RSS after each cycle MB | "
        "peak MB | growth per re-run MB | at rest above idle MB | compute adds MB | "
        "serve adds MB | verdict |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|"
    )
    return header + "\n" + "\n".join(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rows", type=int, default=200_000, help="polygons per loader")
    parser.add_argument("--cycles", type=int, default=5, help="re-runs of the whole dataflow")
    parser.add_argument("--variant", default="baseline",
                        help="comma-separated: " + ", ".join(VARIANTS))
    parser.add_argument("--sandbox-root", default=str(REPO_ROOT),
                        help="checkout whose sandbox to run (default: this one)")
    parser.add_argument("--workdir", default=None, help="keep data and logs here")
    parser.add_argument("--out", default=None, help="write samples.csv and report.json here")
    parser.add_argument("--stop-above-mb", type=int, default=0,
                        help="stop, and report the sandbox as killed, past this RSS")
    parser.add_argument("--summarize", default=None, metavar="DIR",
                        help="print a markdown table of the report.json files under DIR, then exit")
    args = parser.parse_args(argv)

    if args.summarize:
        print(summarize(Path(args.summarize)))
        return 0

    report = run(rows=args.rows, cycles=args.cycles, variants=args.variant.split(","),
                 sandbox_root=Path(args.sandbox_root),
                 workdir=Path(args.workdir) if args.workdir else None,
                 stop_above_mb=args.stop_above_mb)
    print(report.table())
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "samples.csv", "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["cycle", "phase", "request",
                                                        "rss_mb", "peak_mb", "t"])
            writer.writeheader()
            writer.writerows(report.samples)
        (out / "report.json").write_text(json.dumps(report.to_json(), indent=2))
    return 1 if report.failures() else 0


if __name__ == "__main__":
    sys.exit(main())
