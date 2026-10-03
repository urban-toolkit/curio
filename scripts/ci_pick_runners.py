"""Choose the runner for each job of a Full stack build run: arcade first.

CPU jobs run on the self-hosted arcade pool (``[self-hosted, cpu]``) while it
has free runners, and on GitHub-hosted ``ubuntu-latest`` once it has none.
The GPU job (test-gpu) runs on arcade-gpu (``[self-hosted, gpu, h100]``) when
it is idle, and on utk-gpu (``[self-hosted, gpu, curio]``) when it is not.
GitHub cannot express "this runner, or that one if busy": ``runs-on`` has no
"or", and it sends ``ubuntu-latest`` jobs only to its own runners. So the
pick-runners job runs this first, and each job reads its runner from the JSON
map this writes to ``runners`` in ``$GITHUB_OUTPUT``:

    runs-on: ${{ fromJSON(needs.pick-runners.outputs.runners)['jest'] }}

How busy arcade is comes from this repository's own queued and running jobs:
its CPU runner group serves this repository alone, so that count is exact. The
GPU runners also take other repositories' jobs, which this cannot see; a job
sent to a busy arcade-gpu waits for it.

``CURIO_CI_POOL`` = ``arcade`` or ``hosted`` sends every CPU job there, and
``CURIO_CI_GPU_POOL`` = ``arcade`` or ``utk`` the GPU job; ``auto`` (or unset)
picks. They come from the dispatch form, or the repository variables of the
same names when the form says ``auto``.

    python scripts/ci_pick_runners.py --gpu test-gpu build-image jest e2e-desktop-1 ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

#: What a job puts in ``runs-on`` for each place it can run.
RUNS_ON = {
    "arcade": ["self-hosted", "cpu"],
    "hosted": "ubuntu-latest",
    "arcade-gpu": ["self-hosted", "gpu", "h100"],
    "utk": ["self-hosted", "gpu", "curio"],
}
CPU_POOLS = ("arcade", "hosted")
GPU_POOLS = ("arcade-gpu", "utk")

#: Runners in the arcade CPU pool (arcade-cpu-01..20).
CPU_RUNNERS = 20

#: A job still queued after this long for a pool with idle runners means the
#: pool is not taking jobs (runners offline). The API does not say whether a
#: runner is online, so this stands in for it.
STUCK_AFTER_S = 300

#: Job states that hold, or are about to hold, a runner.
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}


def pool_of(job: dict) -> str | None:
    """Where a job runs or waits to run, or None for anywhere else."""
    labels = {label.lower() for label in job.get("labels") or []}
    runner = (job.get("runner_name") or "").lower()
    if runner.startswith("arcade-cpu") or "cpu" in labels:
        return "arcade"
    if runner == "arcade-gpu" or "h100" in labels:
        return "arcade-gpu"
    if runner == "utk-gpu" or {"gpu", "curio"} <= labels:
        return "utk"
    if runner.startswith("github actions") or any(l.startswith("ubuntu") for l in labels):
        return "hosted"
    return None


def _age_s(job: dict, now: datetime) -> float:
    created = job.get("created_at")
    if not created:
        return 0.0
    return (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds()


def busy(jobs: list[dict], now: datetime) -> dict:
    """Jobs holding or waiting for each pool, and whether an arcade pool is stuck."""
    counts = {pool: 0 for pool in RUNS_ON}
    running = {pool: 0 for pool in RUNS_ON}
    oldest_queued = {pool: 0.0 for pool in RUNS_ON}
    for job in jobs:
        if job.get("status") not in ACTIVE:
            continue
        pool = pool_of(job)
        if pool is None:
            continue
        counts[pool] += 1
        if job["status"] == "in_progress":
            running[pool] += 1
        elif job["status"] == "queued":
            oldest_queued[pool] = max(oldest_queued[pool], _age_s(job, now))
    counts["arcade_stuck"] = oldest_queued["arcade"] > STUCK_AFTER_S and running["arcade"] < CPU_RUNNERS
    counts["arcade_gpu_stuck"] = oldest_queued["arcade-gpu"] > STUCK_AFTER_S and running["arcade-gpu"] == 0
    return counts


def assign_cpu(keys: list[str], free_arcade: int, pool: str = "auto") -> dict:
    """Arcade for each job while it has free runners, hosted after that."""
    if pool in CPU_POOLS:
        return {key: pool for key in keys}
    chosen = {}
    for key in keys:
        if free_arcade > 0:
            chosen[key] = "arcade"
            free_arcade -= 1
        else:
            chosen[key] = "hosted"
    return chosen


def assign_gpu(keys: list[str], arcade_gpu_busy: bool, pool: str = "auto") -> dict:
    """arcade-gpu when it is idle, utk otherwise; one GPU job takes it."""
    forced = {"arcade": "arcade-gpu", "utk": "utk"}.get(pool)
    chosen = {}
    for key in keys:
        if forced:
            chosen[key] = forced
        elif not arcade_gpu_busy:
            chosen[key] = "arcade-gpu"
            arcade_gpu_busy = True
        else:
            chosen[key] = "utk"
    return chosen


def _get(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


#: Run states whose jobs can hold or wait for a runner. A run with a job held
#: by a concurrency group is `pending`, though its other jobs are running.
RUN_STATES = ("queued", "in_progress", "pending", "waiting", "requested")


def active_jobs(api: str, repo: str, token: str, skip_run: str) -> list[dict]:
    """Every job of this repository's unfinished runs, this run's aside."""
    jobs = []
    for status in RUN_STATES:
        runs = _get(f"{api}/repos/{repo}/actions/runs?status={status}&per_page=100", token)
        for run in runs.get("workflow_runs", []):
            if str(run["id"]) == str(skip_run):
                continue
            page = 1
            while True:
                found = _get(f"{api}/repos/{repo}/actions/runs/{run['id']}/jobs"
                             f"?filter=latest&per_page=100&page={page}", token)["jobs"]
                jobs.extend(found)
                if len(found) < 100:
                    break
                page += 1
    return jobs


def pick(cpu_keys: list[str], gpu_keys: list[str], pool: str, gpu_pool: str, fetch) -> tuple[dict, list[str]]:
    """Where each key runs, and the lines saying how that was decided."""
    how = []
    if pool in CPU_POOLS and gpu_pool in ("arcade", "utk"):
        how.append(f"CPU jobs on {pool}, GPU jobs on {gpu_pool} (forced)")
        return {**assign_cpu(cpu_keys, 0, pool), **assign_gpu(gpu_keys, False, gpu_pool)}, how
    try:
        counts = busy(fetch(), datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 - a pick must never fail the run
        how.append(f"the jobs API failed ({exc}); arcade first as if idle")
        counts = {**{p: 0 for p in RUNS_ON}, "arcade_stuck": False, "arcade_gpu_stuck": False}

    if pool not in CPU_POOLS and counts["arcade_stuck"]:
        pool = "hosted"
        how.append(f"CPU jobs on hosted: an arcade job has waited over {STUCK_AFTER_S} s")
    free = max(CPU_RUNNERS - counts["arcade"], 0)
    if pool in CPU_POOLS:
        how.append(f"CPU jobs on {pool}")
    else:
        how.append(f"CPU jobs: arcade first, {free} of {CPU_RUNNERS} runners free")

    if gpu_pool not in ("arcade", "utk") and counts["arcade_gpu_stuck"]:
        gpu_pool = "utk"
        how.append(f"GPU jobs on utk: an arcade-gpu job has waited over {STUCK_AFTER_S} s")
    gpu_busy = counts["arcade-gpu"] > 0
    if gpu_pool in ("arcade", "utk"):
        how.append(f"GPU jobs on {gpu_pool}")
    else:
        how.append(f"GPU jobs: arcade-gpu first, it is {'busy' if gpu_busy else 'idle'}")
    return {**assign_cpu(cpu_keys, free, pool), **assign_gpu(gpu_keys, gpu_busy, gpu_pool)}, how


def _setting(name: str, allowed: tuple[str, ...]) -> str:
    value = (os.environ.get(name) or "auto").strip().lower()
    if value not in ("auto", *allowed):
        print(f"::warning::{name}={value!r} is not one of auto, {', '.join(allowed)}; picking", file=sys.stderr)
        return "auto"
    return value


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gpu", action="append", default=[], metavar="KEY", help="a GPU job's key")
    parser.add_argument("cpu", nargs="*", metavar="KEY", help="CPU job keys, in critical-path order")
    args = parser.parse_args(argv[1:])
    if not args.cpu and not args.gpu:
        parser.error("no job keys")
    pool = _setting("CURIO_CI_POOL", CPU_POOLS)
    gpu_pool = _setting("CURIO_CI_GPU_POOL", ("arcade", "utk"))

    def fetch():
        return active_jobs(
            os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            os.environ["GITHUB_REPOSITORY"],
            os.environ["GITHUB_TOKEN"],
            os.environ.get("GITHUB_RUN_ID", ""),
        )

    chosen, how = pick(args.cpu, args.gpu, pool, gpu_pool, fetch)
    runners = {key: RUNS_ON[chosen[key]] for key in [*args.gpu, *args.cpu]}
    for line in how:
        print(line)
    for key, place in chosen.items():
        print(f"  {key}: {place}")
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"runners={json.dumps(runners, separators=(',', ':'))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
