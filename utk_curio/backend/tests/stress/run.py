"""Entry point: run the tiers against a live Curio stack.

    python -m utk_curio.backend.tests.stress --backend http://127.0.0.1:5002 \
        --tiers 5,10,50,100 --out .curio/stress

Each tier starts N users behind a barrier so they hit the stack together, and
every tier runs even if an earlier one failed -- the point is to see where the
limits are, not to stop at the first one. The process exits non-zero if any
tier had any failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

from ..test_frontend.workflow_spec import parse_workflow
from . import report as reporting
from .autk import compile_autk_data
from .driver import BURST, Pacing, VirtualUser, new_user_name

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
EXAMPLES_DIR = os.path.join(REPO_ROOT, "docs", "examples")

# The dataflows each tier's users run, round-robin.
#
# Chosen to cover the three server-side execution paths at once: Python nodes
# (/processPythonCode), JavaScript nodes and the Autark data load
# (/processJavaScriptCode, one Node subprocess per call). Left out on purpose:
# example 10 (street-level computer vision), which needs external services and
# whose dataset URL 404s (#276), and examples 06 and 07, whose value is in the
# WebGPU compute a browser has to run -- the browser tier covers those.
DEFAULT_MIX = [
    "01-vega-lite-chained-transforms.json",   # Python: load + three transforms
    "02-vega-lite-spatial-density.json",      # Python: geopandas, two loaders
    "08-autark-spatial-join-regression.json", # Autark data + a JS node + Python
    "11-autark-pbf-loading.json",             # Autark: two PBF loads, the heaviest
    "dataflows/Regression.json",              # Autark data + compute
    "dataflows/JSComputation.json",           # JS node on its own
]

# A single user's whole session. Generous: under load a node legitimately
# queues behind the sandbox's parallelism limit for minutes.
USER_DEADLINE_S = 20 * 60

# How a tier's users behave. ``burst`` is the worst case: everyone starts at
# the same instant and runs their dataflow flat out, which is what the gated
# tiers measure. ``session`` is a room of people working: they arrive over a
# ramp and read each result before running the next node. A stack can be fine
# for fifty people working and still fall over when all fifty press Run
# together, and only running both tells you which one you have.
SESSION_RAMP_S = 120.0
SESSION_THINK_MIN_S = 3.0
SESSION_THINK_MAX_S = 20.0


def build_pacing(profile: str, tier: int, rng: random.Random) -> list[Pacing]:
    """One Pacing per user of the tier."""
    if profile == "burst":
        return [BURST] * tier
    # Poisson-ish arrivals: uniform offsets over the ramp, which for a fixed
    # population is the same thing and keeps the tier's end time predictable.
    return [
        Pacing(
            arrival_delay=rng.uniform(0, SESSION_RAMP_S),
            think_min=SESSION_THINK_MIN_S,
            think_max=SESSION_THINK_MAX_S,
        )
        for _ in range(tier)
    ]


class Example:
    """One dataflow, parsed and pre-compiled once for every user that runs it."""

    def __init__(self, relpath: str):
        self.relpath = relpath
        self.path = os.path.join(EXAMPLES_DIR, relpath)
        if not os.path.exists(self.path):
            raise FileNotFoundError(self.path)
        self.spec_json = json.loads(open(self.path, encoding="utf-8").read())
        self.workflow = parse_workflow(self.path)
        self.autk_code = compile_autk_data(self.path)


def load_mix(names: list[str]) -> list[Example]:
    examples = [Example(name) for name in names]
    for example in examples:
        print(f"[stress] {example.relpath}: {len(example.workflow.nodes)} nodes, "
              f"{len(example.autk_code)} autark data node(s)", flush=True)
    return examples


def wait_for_backend(backend_url: str, timeout_s: float = 180.0) -> None:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            resp = requests.get(f"{backend_url}/live", timeout=5)
            if resp.status_code == 200:
                return
            last = f"status {resp.status_code}"
        except requests.RequestException as exc:
            last = str(exc)
        time.sleep(2)
    raise SystemExit(f"[stress] backend {backend_url} never came up: {last}")


def read_exec_lock(backend_url: str) -> dict | None:
    """The sandbox's execution-lock counters, or None if unavailable.

    Public and unauthenticated, like the rest of /api/monitor. Best effort:
    a tier that cannot read them reports no lock section rather than failing.
    """
    try:
        resp = requests.get(f"{backend_url}/api/monitor", timeout=10)
        payload = resp.json() or {}
    except (requests.RequestException, ValueError):
        return None
    sandbox = (payload.get("execution") or {}).get("sandbox") or {}
    return sandbox.get("execLock")


def run_baseline(backend_url: str, run_id: str, examples: list[Example]) -> dict:
    """Run each example alone, first, and keep its output hashes.

    This is the yardstick the concurrent users are measured against, and it
    doubles as a sanity check: if an example cannot pass on an idle stack, the
    tiers below would only be reporting that same breakage N times over.
    """
    baselines: dict[str, dict[str, str]] = {}
    for index, example in enumerate(examples):
        user = VirtualUser(
            backend_url, new_user_name(0, index, run_id), example.relpath,
            example.spec_json, example.workflow, example.autk_code,
        )
        result = user.run()
        if not result.completed:
            detail = "; ".join(
                f"{s.node_id or s.endpoint}: {(s.error or '')[:200]}"
                for s in result.failures
            )
            raise SystemExit(
                f"[stress] baseline for {example.relpath} failed on an idle "
                f"stack, so the tiers would be meaningless: {detail}"
            )
        baselines[example.relpath] = result.hashes
        print(f"[stress] baseline {example.relpath}: {result.seconds:.1f}s, "
              f"{len(result.hashes)} hashed output(s)", flush=True)
    return baselines


def run_tier(backend_url: str, run_id: str, tier: int, examples: list[Example],
             baselines: dict, register_concurrency: int,
             profile: str = "burst", label: str | None = None) -> tuple[list, float]:
    """Run *tier* users, all doing their dataflow work at the same moment.

    ``register_concurrency`` caps how many accounts are created at once (0
    means no cap). Registration is the one step that is throttled; see
    ``VirtualUser.run``.
    """
    start_gate = threading.Barrier(tier)
    register_gate = (
        threading.Semaphore(register_concurrency) if register_concurrency else None
    )
    # Seeded on the run id: two runs of the same tier get the same arrival
    # pattern, so their numbers can be compared.
    pacing = build_pacing(profile, tier, random.Random(f"{run_id}-{tier}"))
    label = label or str(tier)
    users = [
        VirtualUser(
            backend_url, new_user_name(label, index, run_id),
            examples[index % len(examples)].relpath,
            examples[index % len(examples)].spec_json,
            examples[index % len(examples)].workflow,
            examples[index % len(examples)].autk_code,
            compare_to=baselines.get(examples[index % len(examples)].relpath),
            register_gate=register_gate,
            start_gate=start_gate,
            pacing=pacing[index],
        )
        for index in range(tier)
    ]

    started = time.time()
    with ThreadPoolExecutor(max_workers=tier) as pool:
        futures = [pool.submit(user.run) for user in users]
        results = [f.result(timeout=USER_DEADLINE_S) for f in futures]
    return results, time.time() - started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m utk_curio.backend.tests.stress")
    parser.add_argument("--backend", default=os.environ.get(
        "CURIO_STRESS_BACKEND", "http://127.0.0.1:5002"))
    parser.add_argument("--tiers", default="5,10,50,100",
                        help="comma-separated user counts, run in order")
    parser.add_argument("--mix", default=",".join(DEFAULT_MIX),
                        help="comma-separated example paths under docs/examples")
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, ".curio", "stress"))
    parser.add_argument("--stats-log", default=None,
                        help="docker stats sample log to fold into the report")
    parser.add_argument("--register-concurrency", type=int, default=0,
                        help="cap on how many accounts may be created at once "
                             "(0, the default, means no cap)")
    parser.add_argument("--profile", choices=("burst", "session"), default="burst",
                        help="burst: everyone starts together and runs flat "
                             "out (the gated worst case). session: arrivals "
                             "over a ramp, with pauses between node runs")
    parser.add_argument("--run-id", default=uuid.uuid4().hex[:6])
    args = parser.parse_args(argv)

    backend_url = args.backend.rstrip("/")
    tiers = [int(t) for t in args.tiers.split(",") if t.strip()]
    examples = load_mix([m.strip() for m in args.mix.split(",") if m.strip()])

    wait_for_backend(backend_url)
    print(f"[stress] run {args.run_id} against {backend_url}; "
          f"tiers {tiers}; profile {args.profile}", flush=True)

    baselines = run_baseline(backend_url, args.run_id, examples)

    tier_reports = []
    all_results = []
    for position, tier in enumerate(tiers):
        print(f"[stress] tier {tier}: starting", flush=True)
        # Bracketing the tier, because the counters are cumulative since the
        # sandbox started and the baseline runs before the first tier.
        lock_before = read_exec_lock(backend_url)
        results, seconds = run_tier(backend_url, args.run_id, tier, examples,
                                    baselines, args.register_concurrency,
                                    args.profile, label=f"{tier}x{position}")
        all_results.extend(results)
        lock = reporting.exec_lock_delta(lock_before, read_exec_lock(backend_url))
        summary = reporting.tier_summary(tier, results, seconds, args.profile,
                                         exec_lock=lock)
        tier_reports.append(summary)
        print(f"[stress] tier {tier}: {summary['completed']}/{tier} completed in "
              f"{seconds:.1f}s, {summary['failure_count']} failure(s)", flush=True)
        if lock:
            waits = ", ".join(
                f"{label} {stat['wait_seconds']}s over {stat['acquisitions']}"
                for label, stat in sorted(lock["labels"].items())
            )
            print(f"[stress] tier {tier}: exec lock waited {waits}", flush=True)

    report = reporting.build_report(args.run_id, backend_url, tier_reports,
                                    args.stats_log, profile=args.profile)
    json_path, md_path = reporting.write_outputs(report, args.out)
    with open(os.path.join(args.out, "samples.json"), "w", encoding="utf-8") as fh:
        json.dump(reporting.raw_samples(all_results), fh)
    print(f"[stress] wrote {json_path} and {md_path}", flush=True)
    print(reporting.markdown(report))

    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
