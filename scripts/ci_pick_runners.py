"""Choose the runner for each job of a Full stack build run.

CPU jobs run on GitHub-hosted ``ubuntu-latest`` while the organization's
hosted runners have room, on the self-hosted arcade pool (``[self-hosted,
cpu]``) after that, and on the utk-desktop runners (utk-desktop-01 and -02,
``[self-hosted, desktop]``) when arcade is full too. The GPU job (test-gpu)
runs on the arcade GPU pool (arcade-gpu-01..04, ``[self-hosted, gpu, h100]``)
while it has a free runner, then on utk-gpu (``[self-hosted, gpu, curio]``),
and on a utk-desktop runner (``[self-hosted, gpu, desktop]``, either one) when
utk-gpu is busy too, where it runs as many workers as the desktop holds
(scripts/ci_memory_budget.py). A desktop runs one job of either kind, so the
desktops' room counts the jobs of both.
GitHub cannot express "this runner, or that one if busy": ``runs-on`` has no
"or", and it sends ``ubuntu-latest`` jobs only to its own runners. So a run
picks twice: the pick-runners job, for the jobs that start at once, and
build-image's last step, for the jobs that wait on the image, which start
minutes later. Each job reads its runner from the JSON map this writes to
``runners`` in ``$GITHUB_OUTPUT``:

    runs-on: ${{ fromJSON(needs.pick-runners.outputs.runners)['jest'] }}
    runs-on: ${{ fromJSON(needs.build-image.outputs.runners)['test-isolated'] }}

How busy each pool is comes from this repository's own queued and running
jobs. The hosted limit (``HOSTED_SLOTS`` concurrent jobs) is shared with every
other repository of the organization, which this cannot see, so a curio job
that has waited ``HOSTED_FULL_AFTER_S`` for a hosted runner also counts as the
limit reached. The arcade CPU group serves this repository alone, so its count
is exact. The GPU runners also take other repositories' jobs; a job sent to
the arcade GPU pool while those hold it waits for a runner. The desktops can
be asleep or off: a desktop job queued with a desktop that should be free
means they are not taking jobs, and no more go there.

A pick leaves its own run's jobs out, unless ``--this-run-except`` names the
job that runs it: build-image's pick counts the jobs of its run that are
already running, but not build-image, which ends with the pick. A job that
waits on ``needs`` does not exist in the jobs API until those finish, so no
pick sees it; ``--hosted-reserved`` holds back room for the ones that always
run hosted.

``CURIO_CI_POOL`` = ``hosted``, ``arcade`` or ``desktop`` sends every CPU job
there, and ``CURIO_CI_GPU_POOL`` = ``arcade``, ``utk`` or ``desktop`` the GPU
job; ``auto`` (or unset) picks. They come from the dispatch form, or the repository variables of the
same names when the form says ``auto``.

    python scripts/ci_pick_runners.py --hosted-reserved 1 --gpu test-gpu build-image jest ci-report
    python scripts/ci_pick_runners.py --this-run-except build-image --hosted-reserved 2 test-isolated ...
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
    "desktop": ["self-hosted", "desktop"],
    "desktop-gpu": ["self-hosted", "gpu", "desktop"],
}
CPU_POOLS = ("arcade", "hosted", "desktop")
#: The GPU pools a dispatch can name, and the place each one is.
GPU_POOLS = {"arcade": "arcade-gpu", "utk": "utk", "desktop": "desktop-gpu"}

#: Runners in the arcade CPU pool (arcade-cpu-01..40).
CPU_RUNNERS = 40
#: Runners in the arcade GPU pool (arcade-gpu-01..04, all on one H100).
GPU_RUNNERS = 4
#: utk-gpu, one runner.
UTK_RUNNERS = 1
#: The utk-desktop runners (utk-desktop-01 and -02), each one job at a time.
DESKTOP_RUNNERS = 2
#: Those of them that also take the GPU job: both carry the gpu label (owner,
#: 10-25), utk-desktop-01 with 30 GB and an RTX 3070, utk-desktop-02 with
#: 12 GB and an RTX 4070.
GPU_DESKTOPS = ("utk-desktop-01", "utk-desktop-02")
DESKTOP_GPU_RUNNERS = len(GPU_DESKTOPS)
#: Concurrent GitHub-hosted jobs the organization's plan allows.
HOSTED_SLOTS = 20

#: A job still queued after this long for a pool with idle runners means the
#: pool is not taking jobs (runners offline). The API does not say whether a
#: runner is online, so this stands in for it.
STUCK_AFTER_S = 300
#: A hosted runner normally starts a job within seconds; a curio job queued
#: this long for one means the organization's hosted limit is reached.
HOSTED_FULL_AFTER_S = 60

#: Job states that hold, or are about to hold, a runner.
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}


def pool_of(job: dict) -> str | None:
    """Where a job runs or waits to run, or None for anywhere else."""
    labels = {label.lower() for label in job.get("labels") or []}
    runner = (job.get("runner_name") or "").lower()
    if runner.startswith("utk-desktop") or "desktop" in labels:
        return "desktop-gpu" if "gpu" in labels else "desktop"
    if runner.startswith("arcade-cpu") or "cpu" in labels:
        return "arcade"
    if runner.startswith("arcade-gpu") or "h100" in labels:
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
    """Jobs holding or waiting for each pool, and whether a pool is stuck or full."""
    counts = {pool: 0 for pool in RUNS_ON}
    running = {pool: 0 for pool in RUNS_ON}
    oldest_queued = {pool: 0.0 for pool in RUNS_ON}
    # Jobs running on a desktop that takes the GPU job, and the CPU ones among them.
    on_gpu_desktops = cpu_on_gpu_desktops = 0
    for job in jobs:
        if job.get("status") not in ACTIVE:
            continue
        pool = pool_of(job)
        if pool is None:
            continue
        counts[pool] += 1
        if job["status"] == "in_progress":
            running[pool] += 1
            if (job.get("runner_name") or "").lower() in GPU_DESKTOPS:
                on_gpu_desktops += 1
                cpu_on_gpu_desktops += pool == "desktop"
        elif job["status"] == "queued":
            oldest_queued[pool] = max(oldest_queued[pool], _age_s(job, now))
    counts["arcade_stuck"] = oldest_queued["arcade"] > STUCK_AFTER_S and running["arcade"] < CPU_RUNNERS
    counts["arcade_gpu_stuck"] = oldest_queued["arcade-gpu"] > STUCK_AFTER_S and running["arcade-gpu"] < GPU_RUNNERS
    counts["hosted_full"] = oldest_queued["hosted"] > HOSTED_FULL_AFTER_S
    # A CPU job can take any desktop and the GPU job those in GPU_DESKTOPS, so
    # each kind waits too long only while a desktop it can take runs nothing.
    counts["desktop_stuck"] = (
        (oldest_queued["desktop"] > STUCK_AFTER_S
         and running["desktop"] + running["desktop-gpu"] < DESKTOP_RUNNERS)
        or (oldest_queued["desktop-gpu"] > STUCK_AFTER_S and on_gpu_desktops < DESKTOP_GPU_RUNNERS))
    counts["desktop_cpu_on_gpu"] = cpu_on_gpu_desktops
    return counts


def desktop_room(counts: dict) -> tuple[int, int]:
    """Free desktops for CPU jobs, and for the GPU job.

    A CPU job can take any desktop, the GPU job only those in GPU_DESKTOPS (today
    both, so each desktop job of either kind holds one GPU desktop). A running
    CPU job's runner says which desktop it holds; a queued one's does not, so
    CPU jobs are also taken to fill the desktops without a GPU first, and the
    rest to hold GPU desktops, whichever holds more.
    """
    if counts["desktop_stuck"]:
        return 0, 0
    cpu_free = max(DESKTOP_RUNNERS - counts["desktop"] - counts["desktop-gpu"], 0)
    cpu_on_gpu_desktops = max(counts.get("desktop_cpu_on_gpu", 0),
                              counts["desktop"] - (DESKTOP_RUNNERS - DESKTOP_GPU_RUNNERS))
    gpu_free = max(DESKTOP_GPU_RUNNERS - counts["desktop-gpu"] - cpu_on_gpu_desktops, 0)
    return cpu_free, gpu_free


def assign_cpu(keys: list[str], free_hosted: int, pool: str = "auto",
               free_arcade: int = CPU_RUNNERS, free_desktop: int = 0) -> dict:
    """GitHub-hosted for each job while it has room, arcade after that, then a
    free desktop. With every pool full, a job waits on arcade, the largest."""
    if pool in CPU_POOLS:
        return {key: pool for key in keys}
    chosen = {}
    for key in keys:
        if free_hosted > 0:
            chosen[key] = "hosted"
            free_hosted -= 1
        elif free_arcade > 0 or free_desktop <= 0:
            chosen[key] = "arcade"
            free_arcade -= 1
        else:
            chosen[key] = "desktop"
            free_desktop -= 1
    return chosen


def assign_gpu(keys: list[str], free_arcade_gpu: int, pool: str = "auto",
               free_utk: int = UTK_RUNNERS, free_desktop_gpu: int = 0) -> dict:
    """An arcade GPU runner for each job while one is free, utk after that,
    then a free desktop. With every one busy, a job waits on utk."""
    forced = GPU_POOLS.get(pool)
    if forced:
        return {key: forced for key in keys}
    chosen = {}
    for key in keys:
        if free_arcade_gpu > 0:
            chosen[key] = "arcade-gpu"
            free_arcade_gpu -= 1
        elif free_utk > 0 or free_desktop_gpu <= 0:
            chosen[key] = "utk"
            free_utk -= 1
        else:
            chosen[key] = "desktop-gpu"
            free_desktop_gpu -= 1
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


def active_jobs(api: str, repo: str, token: str, this_run: str,
                this_run_except: str | None = None) -> list[dict]:
    """Every job of this repository's unfinished runs, this run's aside.

    With ``this_run_except``, this run's jobs count too, except the one of that
    name: the job running the pick, which ends with it.
    """
    jobs = []
    for status in RUN_STATES:
        runs = _get(f"{api}/repos/{repo}/actions/runs?status={status}&per_page=100", token)
        for run in runs.get("workflow_runs", []):
            own = str(run["id"]) == str(this_run)
            if own and this_run_except is None:
                continue
            page = 1
            while True:
                found = _get(f"{api}/repos/{repo}/actions/runs/{run['id']}/jobs"
                             f"?filter=latest&per_page=100&page={page}", token)["jobs"]
                jobs.extend(job for job in found if not (own and job.get("name") == this_run_except))
                if len(found) < 100:
                    break
                page += 1
    return jobs


def pick(cpu_keys: list[str], gpu_keys: list[str], pool: str, gpu_pool: str, fetch,
         hosted_reserved: int = 0) -> tuple[dict, list[str]]:
    """Where each key runs, and the lines saying how that was decided.

    ``hosted_reserved`` is how many of this run's jobs always run hosted
    (they are not in ``cpu_keys``), held back from the hosted room.
    """
    how = []
    if pool in CPU_POOLS and gpu_pool in GPU_POOLS:
        how.append(f"CPU jobs on {pool}, GPU jobs on {gpu_pool} (forced)")
        return {**assign_cpu(cpu_keys, 0, pool), **assign_gpu(gpu_keys, 0, gpu_pool)}, how
    try:
        counts = busy(fetch(), datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 - a pick must never fail the run
        how.append(f"the jobs API failed ({exc}); picking as if every pool were idle")
        counts = {**{p: 0 for p in RUNS_ON}, "arcade_stuck": False, "arcade_gpu_stuck": False,
                  "hosted_full": False, "desktop_stuck": False}

    free = max(HOSTED_SLOTS - counts["hosted"] - hosted_reserved, 0)
    arcade_free = max(CPU_RUNNERS - counts["arcade"], 0)
    desktop_free, desktop_gpu_free = desktop_room(counts)
    if counts["desktop_stuck"]:
        how.append(f"No job goes to the desktops: a desktop job has waited over {STUCK_AFTER_S} s")
    after_hosted = (f"then arcade, {arcade_free} of {CPU_RUNNERS} free, "
                    f"then the desktops, {desktop_free} of {DESKTOP_RUNNERS} free")
    if pool in CPU_POOLS:
        how.append(f"CPU jobs on {pool}")
    elif counts["arcade_stuck"]:
        pool = "hosted"
        how.append(f"CPU jobs on hosted: an arcade job has waited over {STUCK_AFTER_S} s")
    elif counts["hosted_full"]:
        free = 0
        how.append(f"CPU jobs not on hosted: a hosted job has waited over {HOSTED_FULL_AFTER_S} s, "
                   f"so the organization's hosted limit is reached; {after_hosted}")
    else:
        how.append(f"CPU jobs: GitHub-hosted first, {free} of {HOSTED_SLOTS} hosted slots free "
                   f"(this repository's jobs, {hosted_reserved} kept for this run's hosted-only jobs), "
                   f"{after_hosted}")

    gpu_free = max(GPU_RUNNERS - counts["arcade-gpu"], 0)
    utk_free = max(UTK_RUNNERS - counts["utk"], 0)
    if gpu_keys:
        if gpu_pool in GPU_POOLS:
            how.append(f"GPU jobs on {gpu_pool}")
        else:
            if counts["arcade_gpu_stuck"]:
                gpu_free = 0
                how.append(f"GPU jobs skip arcade: an arcade GPU job has waited over {STUCK_AFTER_S} s")
            how.append(f"GPU jobs: arcade first, {gpu_free} of {GPU_RUNNERS} arcade GPU runners free, "
                       f"then utk, {utk_free} of {UTK_RUNNERS} free, "
                       f"then the desktops, {desktop_gpu_free} of {DESKTOP_GPU_RUNNERS} free")
    gpu_chosen = assign_gpu(gpu_keys, gpu_free, gpu_pool, utk_free, desktop_gpu_free)
    # A GPU job sent to a desktop holds a desktop a CPU job could have had.
    desktop_free = max(desktop_free - list(gpu_chosen.values()).count("desktop-gpu"), 0)
    return {**assign_cpu(cpu_keys, free, pool, arcade_free, desktop_free), **gpu_chosen}, how


def _setting(name: str, allowed: tuple[str, ...]) -> str:
    value = (os.environ.get(name) or "auto").strip().lower()
    if value not in ("auto", *allowed):
        print(f"::warning::{name}={value!r} is not one of auto, {', '.join(allowed)}; picking", file=sys.stderr)
        return "auto"
    return value


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gpu", action="append", default=[], metavar="KEY", help="a GPU job's key")
    parser.add_argument("--hosted-reserved", type=int, default=0, metavar="N",
                        help="this run's jobs that always run hosted, held back from the hosted room")
    parser.add_argument("--this-run-except", metavar="JOB",
                        help="also count this run's own jobs, except JOB, the one running this pick")
    parser.add_argument("cpu", nargs="*", metavar="KEY", help="CPU job keys, in critical-path order")
    args = parser.parse_args(argv[1:])
    if not args.cpu and not args.gpu:
        parser.error("no job keys")
    pool = _setting("CURIO_CI_POOL", CPU_POOLS)
    gpu_pool = _setting("CURIO_CI_GPU_POOL", tuple(GPU_POOLS))

    def fetch():
        if args.this_run_except:
            print(f"Counting this run's own jobs too, except {args.this_run_except}")
        return active_jobs(
            os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            os.environ["GITHUB_REPOSITORY"],
            os.environ["GITHUB_TOKEN"],
            os.environ.get("GITHUB_RUN_ID", ""),
            args.this_run_except,
        )

    chosen, how = pick(args.cpu, args.gpu, pool, gpu_pool, fetch, args.hosted_reserved)
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
