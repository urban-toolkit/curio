"""How much of this runner's memory a CI job may use.

A self-hosted runner can be a desktop with 12 GB of memory and 8 GB of video
memory, or an arcade runner with a 64 GB container on an 80 GB H100. Two
numbers follow from what the runner has free when the job starts, and this
writes both to ``$GITHUB_ENV``:

* ``CURIO_E2E_PARALLEL``, test-gpu's e2e workers (``--workers-max``). Each one
  is a Chrome drawing Autark maps on the GPU, a pytest worker, and a backend
  and sandbox pair in the CI container. Six of them stalled utk-desktop-01
  for 20 minutes until a worker died and its runner was stopped (2026-10-25,
  run 40157161068), and filled its 8 GB of video memory until maps came back
  blank (``VK_ERROR_OUT_OF_DEVICE_MEMORY``, run 40201256122's second
  attempt). So the count is what free memory and free video memory hold, at
  most the maximum.
* ``CURIO_CI_MEM_LIMIT``, the CI container's memory limit, which the CI
  overlays set as both ``mem_limit`` and ``memswap_limit``. When the stack
  outgrows it, the kernel kills a process inside the container and the job
  fails with that, instead of the machine swapping until its runner stops
  answering GitHub. It is everything free except the reserve and what the
  workers need outside the container, so it does not squeeze the stack.

Free memory is ``MemAvailable``, and on a runner inside a container (arcade)
also the room under that container's own limit, with its file cache counted as
free the way ``MemAvailable`` counts the host's. Free video memory is
``nvidia-smi``'s, on the fullest GPU it lists.

Nothing here may fail a run: a reading that fails is left out, and with no
reading at all the job keeps the maximum and no limit, with a warning.

    python3 scripts/ci_memory_budget.py --github-env --workers-max 6
    python3 scripts/ci_memory_budget.py --github-env
    python3 scripts/ci_memory_budget.py sample --out ci-report/memory.tsv
    python3 scripts/ci_memory_budget.py report --samples ci-report/memory.tsv
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

GIB = 1024 ** 3
MIB = 1024 ** 2

#: Memory one test-gpu worker takes on a busy test, inside the container and
#: out: its backend and sandbox pair with the Node runs of its Autark loads,
#: its Chrome drawing maps, and its pytest worker. Measured as the drop in free
#: memory (#1154's runs, 10-25): 12.3 GiB at the median and 22.6 at most for
#: six workers on arcade-gpu-02.
WORKER_GIB = 3.5
#: The worker that runs the heaviest test takes this instead.
#: test_node_execution of example 09 (heterogeneous data, linked views) took
#: 13.9 GiB by itself on one worker (utk-desktop-01): 7.3 GiB in the sandbox
#: computing the outputs, then 8.5 GiB in pytest reading them back to compare.
#: A runner with less free than this and the reserve fails that test.
HEAVIEST_WORKER_GIB = 14.0
#: What one worker usually holds outside the container (Chrome, pytest), which
#: the container's limit leaves free. Chrome's 90th percentile was 1.2 GiB a
#: worker on arcade-gpu-02 and 1.5 on utk-desktop-02.
WORKER_OUTSIDE_GIB = 1.5
#: Video memory one worker's Chrome holds at its peak: 0.6 GiB for one worker
#: on utk-desktop-01, 0.8 for three on utk-desktop-02.
WORKER_VRAM_GIB = 0.75
#: Left free for the runner, the desktop around it and the Docker daemon.
RESERVE_GIB = 2.0
#: The least the container gets, so a misread machine still boots a stack.
MIN_LIMIT_GIB = 4.0

#: Cgroup v2's view of this process, and its memory files.
CGROUP_ROOT = Path("/sys/fs/cgroup")
#: The file pages a cgroup can drop, which MemAvailable also counts as free.
RECLAIMABLE = ("inactive_file", "active_file")


def meminfo_available(text: str) -> int | None:
    """``MemAvailable`` in bytes, from the text of ``/proc/meminfo``."""
    match = re.search(r"^MemAvailable:\s+(\d+)\s+kB", text, re.MULTILINE)
    return int(match.group(1)) * 1024 if match else None


def cgroup_room(limit: str, current: str, stat: str) -> int | None:
    """Room under one cgroup's ``memory.max``, its file cache counted as free.

    None when the cgroup has no limit (``max``) or a file does not parse.
    """
    limit = limit.strip()
    if limit == "max":
        return None
    try:
        used = int(current.strip())
        cap = int(limit)
    except ValueError:
        return None
    cache = 0
    for line in stat.splitlines():
        key, _, value = line.partition(" ")
        if key in RECLAIMABLE and value.strip().isdigit():
            cache += int(value)
    return max(cap - max(used - cache, 0), 0)


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def own_cgroup_rooms(root: Path = CGROUP_ROOT, self_cgroup: str | None = None) -> list[int]:
    """The room under every limit between this process's cgroup and the root.

    In a container with its own cgroup namespace (arcade's runners) the path is
    ``/`` and the root's files are the container's. On a host, the runner's
    service and the slices above it.
    """
    if self_cgroup is None:
        self_cgroup = _read(Path("/proc/self/cgroup")) or ""
    path = next((line[3:] for line in self_cgroup.splitlines() if line.startswith("0::")), None)
    if path is None:
        return []
    rooms = []
    here = root / path.strip().lstrip("/")
    while True:
        files = [_read(here / name) for name in ("memory.max", "memory.current", "memory.stat")]
        if None not in files:
            room = cgroup_room(*files)
            if room is not None:
                rooms.append(room)
        if here == root or root not in here.parents:
            break
        here = here.parent
    return rooms


def free_memory() -> int | None:
    """The least of ``MemAvailable`` and every cgroup limit's room, in bytes."""
    readings = list(own_cgroup_rooms())
    available = meminfo_available(_read(Path("/proc/meminfo")) or "")
    if available is not None:
        readings.append(available)
    return min(readings) if readings else None


def nvidia_smi(field: str) -> list[int] | None:
    """One ``nvidia-smi --query-gpu`` field in MiB, per GPU; None without it."""
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={field}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    values = [int(v) for v in out.split() if v.strip().isdigit()]
    return values or None


def free_vram() -> int | None:
    """Free video memory in bytes on the GPU with the least, or None."""
    free = nvidia_smi("memory.free")
    return min(free) * MIB if free else None


def budget(free: int | None, vram: int | None, workers_max: int | None) -> dict:
    """The worker count and container limit for this much free memory.

    ``workers`` is None when no count was asked for; ``limit`` is None when
    nothing was read, which leaves the container without one.
    """
    if free is None:
        return {"workers": workers_max, "limit": None}
    workers = None
    if workers_max is not None:
        # One worker may be on the heaviest test while the others are busy.
        spare = free - (RESERVE_GIB + HEAVIEST_WORKER_GIB) * GIB
        workers = 1 + max(int(spare // (WORKER_GIB * GIB)), 0)
        if vram is not None:
            workers = min(workers, int(vram // (WORKER_VRAM_GIB * GIB)))
        workers = max(1, min(workers_max, workers))
    outside = (workers or 1) * WORKER_OUTSIDE_GIB * GIB
    limit = max(int(free - RESERVE_GIB * GIB - outside), int(MIN_LIMIT_GIB * GIB))
    return {"workers": workers, "limit": limit}


def holds_the_heaviest_test(free: int | None) -> bool:
    """Whether this much free memory holds the heaviest test's worker."""
    return free is None or free >= (RESERVE_GIB + HEAVIEST_WORKER_GIB) * GIB


def _gib(value: int | None) -> str:
    return "unknown" if value is None else f"{value / GIB:.1f} GiB"


def size(args) -> int:
    try:
        free, vram = free_memory(), free_vram()
        chosen = budget(free, vram, args.workers_max)
    except Exception as exc:  # noqa: BLE001 - a reading must never fail the run
        print(f"::warning::could not read this runner's memory ({exc}); keeping the defaults")
        free = vram = None
        chosen = {"workers": args.workers_max, "limit": None}
    if free is None:
        print("::warning::no free memory reading; the container gets no memory limit")
    lines = [f"Free memory {_gib(free)}, free video memory "
             f"{_gib(vram) if vram is not None else 'not read (no nvidia-smi)'}"]
    env = {}
    if chosen["workers"] is not None:
        env["CURIO_E2E_PARALLEL"] = str(chosen["workers"])
        lines.append(f"e2e workers: {chosen['workers']} of at most {args.workers_max}")
        if not holds_the_heaviest_test(free):
            print(f"::warning::{_gib(free)} free holds less than the heaviest e2e test needs "
                  f"({HEAVIEST_WORKER_GIB:.0f} GiB and a {RESERVE_GIB:.0f} GiB reserve): "
                  "expect it to fail, and the tests after it on its worker")
    if chosen["limit"] is not None:
        mib = chosen["limit"] // MIB
        env["CURIO_CI_MEM_LIMIT"] = f"{mib}m"
        lines.append(f"CI container memory limit: {mib / 1024:.1f} GiB, swap included")
    for line in lines:
        print(line)
    if args.github_env and os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as fh:
            fh.writelines(f"{key}={value}\n" for key, value in env.items())
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("### Memory budget\n\n" + "".join(f"- {line}\n" for line in lines) + "\n")
    return 0


_UNITS = {"B": 1, "KIB": 1024, "MIB": MIB, "GIB": GIB, "TIB": 1024 * GIB,
          "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3}


def stack_memory(prefix: str) -> int | None:
    """Memory the containers named ``prefix*`` use, from ``docker stats``."""
    try:
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    total = 0
    for line in out.splitlines():
        name, _, usage = line.partition("\t")
        match = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)", usage)
        if name.startswith(prefix) and match and match.group(2).upper() in _UNITS:
            total += int(float(match.group(1)) * _UNITS[match.group(2).upper()])
    return total


def own_processes() -> dict[str, int]:
    """Proportional memory (PSS) of this user's Chrome, Python and Node outside
    any container, in bytes. The containers' own count is ``stack_memory``'s."""
    groups = {"chrome": 0, "python": 0, "node": 0}
    uid = os.getuid()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid or "docker" in (proc / "cgroup").read_text():
                continue
            name = (proc / "comm").read_text().strip().lower()
            rollup = (proc / "smaps_rollup").read_text()
        except OSError:
            continue
        group = next((g for g in groups if name.startswith(g)), None)
        match = re.search(r"^Pss:\s+(\d+)\s+kB", rollup, re.MULTILINE)
        if group and match:
            groups[group] += int(match.group(1)) * 1024
    return groups


COLUMNS = ("time", "free", "stack", "chrome", "python", "node", "vram_used")


def sample(args) -> int:
    """Append a row every ``--every`` seconds until ``--for`` minutes pass."""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
    ends = time.monotonic() + args.minutes * 60
    while time.monotonic() < ends:
        try:
            used = nvidia_smi("memory.used")
            row = [int(time.time()), free_memory(), stack_memory(args.prefix),
                   *own_processes().values(), max(used) * MIB if used else None]
            with out.open("a", encoding="utf-8") as fh:
                fh.write("\t".join("" if v is None else str(v) for v in row) + "\n")
        except Exception as exc:  # noqa: BLE001 - one bad sample must not end the watch
            print(f"sample failed: {exc}", file=sys.stderr)
        time.sleep(args.every)
    return 0


def peaks(text: str) -> dict:
    """Per column, the highest value (the lowest for free memory) and the first."""
    rows = [line.split("\t") for line in text.splitlines()[1:] if line.strip()]
    result = {}
    for i, column in enumerate(COLUMNS[1:], start=1):
        values = [int(row[i]) for row in rows if len(row) > i and row[i]]
        if values:
            pick = min if column == "free" else max
            result[column] = {"first": values[0], "peak": pick(values)}
    result["samples"] = len(rows)
    return result


def report(args) -> int:
    text = _read(Path(args.samples))
    if not text:
        print(f"no memory samples at {args.samples}")
        return 0
    found = peaks(text)
    names = {"free": "Least free memory", "stack": "CI containers, most",
             "chrome": "Chrome, most (PSS)", "python": "Python outside the containers, most (PSS)",
             "node": "Node outside the containers, most (PSS)", "vram_used": "Video memory used, most"}
    lines = [f"{label}: {_gib(found[key]['peak'])} (first sample {_gib(found[key]['first'])})"
             for key, label in names.items() if key in found]
    lines.append(f"{found['samples']} samples")
    for line in lines:
        print(line)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("### Memory this job used\n\n" + "".join(f"- {line}\n" for line in lines) + "\n")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command")
    sampling = sub.add_parser("sample", help="record memory use while the tests run")
    sampling.add_argument("--out", required=True)
    sampling.add_argument("--prefix", default="curio-ci", help="the CI containers' name prefix")
    sampling.add_argument("--every", type=float, default=5.0, metavar="SECONDS")
    sampling.add_argument("--minutes", type=float, default=95.0,
                          help="stop after this long, past the job's own limit")
    reporting = sub.add_parser("report", help="the peaks of a sample file")
    reporting.add_argument("--samples", required=True)
    parser.add_argument("--github-env", action="store_true",
                        help="write CURIO_E2E_PARALLEL and CURIO_CI_MEM_LIMIT to $GITHUB_ENV")
    parser.add_argument("--workers-max", type=int, metavar="N",
                        help="size test-gpu's e2e workers, at most N")
    args = parser.parse_args(argv[1:])
    if args.command == "sample":
        return sample(args)
    if args.command == "report":
        return report(args)
    return size(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
