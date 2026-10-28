"""What each process in a CI stack's container holds, while the tests run.

The job's memory sampler (``scripts/ci_memory_budget.py sample``) sees only a
container's total. This one looks inside it, so a stack that grows names the
process that grows:

* ``read`` runs inside the container (as root, so every process's
  ``smaps_rollup`` is readable) and prints one JSON line: the container
  cgroup's ``memory.current`` and ``memory.stat`` split (anonymous memory, file
  cache, shared memory, kernel), and, per role (``backend0``, ``sandbox3``,
  ``node@sandbox3``, ``pages0``, ``launcher0``), its processes' resident and
  anonymous memory, threads and open files. A shard is the backend and sandbox
  pair a worker drives, told apart by ``BACKEND_PORT``; a child takes its
  parent's shard.
* ``sample`` runs on the runner and appends a ``read`` of the container every
  ``--every`` seconds, piping this file to the container's Python, so it needs
  nothing in the image.

    python3 scripts/ci_stack_processes.py sample --project curio-ci \\
        --out ci-report/stack-processes.jsonl
    docker compose -p curio-ci exec -T curio python3 - read < scripts/ci_stack_processes.py

Nothing here may fail a run: a process that ends mid-read is left out, and a
sample that fails is skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CGROUP = Path("/sys/fs/cgroup")
#: The parts of ``memory.stat`` that tell a leak from a cache.
STAT_KEYS = ("anon", "file", "active_file", "inactive_file", "shmem", "kernel",
             "kernel_stack", "pagetables", "sock", "slab", "slab_reclaimable",
             "slab_unreclaimable", "file_mapped", "file_dirty", "anon_thp", "percpu")
#: Ports of shard 0's backend and sandbox in the container (tests/shards.py).
BASE_BACKEND_PORT = 5002
BASE_SANDBOX_PORT = 2000
#: Processes holding at least this much anonymous memory also report their
#: biggest anonymous mappings, which tell glibc's heap from other allocators.
MAPS_FROM_BYTES = 256 * 1024 ** 2


def _text(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def _kib_fields(text: str, names: tuple[str, ...]) -> dict[str, int]:
    found = {}
    for name in names:
        match = re.search(rf"^{name}:\s+(\d+)\s+kB", text, re.MULTILINE)
        if match:
            found[name] = int(match.group(1)) * 1024
    return found


def kind_of(cmdline: str, comm: str) -> str:
    """What a process is, from its command line."""
    if "backend.server" in cmdline:
        return "backend"
    if "sandbox.server" in cmdline:
        return "sandbox"
    if "run_spa_static_server" in cmdline:
        return "pages"
    if "curio.py" in cmdline:
        return "launcher"
    return comm or "?"


def shard_of(environ: str) -> int | None:
    """The shard a server process belongs to, from the ports it was given."""
    for key, base in (("BACKEND_PORT", BASE_BACKEND_PORT), ("SANDBOX_PORT", BASE_SANDBOX_PORT)):
        match = re.search(rf"(?:^|\0){key}=(\d+)(?:\0|$)", environ)
        if match:
            return int(match.group(1)) - base
    return None


#: The ``smaps`` fields kept for each anonymous mapping.
MAP_FIELDS = {"Rss": "rss", "Size": "size", "LazyFree": "lazy"}


def anon_maps(pid: str, proc: Path = Path("/proc")) -> dict:
    """The [heap] and the biggest anonymous mappings of one process: what each
    holds resident (``biggest``), its size (``biggest_size``), and the bytes
    freed lazily (``MADV_FREE``), which count as resident until the kernel
    takes them back under pressure."""
    text = _text(proc / pid / "smaps")
    if not text:
        return {}
    maps, current = [], None
    for line in text.splitlines():
        head = re.match(r"^[0-9a-f]+-[0-9a-f]+ \S+ \S+ \S+ \d+\s*(.*)$", line)
        if head:
            name = head.group(1).strip()
            current = None
            if name in ("", "[heap]"):
                current = {"heap": name == "[heap]", "rss": 0, "size": 0, "lazy": 0}
                maps.append(current)
            continue
        field, _, rest = line.partition(":")
        if current is not None and field in MAP_FIELDS and rest.split():
            current[MAP_FIELDS[field]] = int(rest.split()[0]) * 1024
    anon = sorted((m for m in maps if not m["heap"] and m["rss"]),
                  key=lambda m: m["rss"], reverse=True)
    return {"heap": sum(m["rss"] for m in maps if m["heap"]), "anon_maps": len(anon),
            "anon_total": sum(m["rss"] for m in anon),
            "biggest": [m["rss"] for m in anon[:8]],
            "biggest_size": [m["size"] for m in anon[:8]],
            "lazy_free": sum(m["lazy"] for m in maps),
            "under_1m": sum(m["rss"] for m in anon if m["rss"] < 1024 ** 2)}


def processes() -> list[dict]:
    procs = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        status = _text(entry / "status")
        cmdline = _text(entry / "cmdline")
        if status is None or cmdline is None:
            continue
        comm = re.search(r"^Name:\s+(.*)$", status, re.MULTILINE)
        ppid = re.search(r"^PPid:\s+(\d+)", status, re.MULTILINE)
        threads = re.search(r"^Threads:\s+(\d+)", status, re.MULTILINE)
        record = {
            "pid": int(entry.name),
            "ppid": int(ppid.group(1)) if ppid else 0,
            "comm": comm.group(1).strip() if comm else "?",
            "cmd": cmdline.replace("\0", " ").strip()[:160],
            "threads": int(threads.group(1)) if threads else 0,
        }
        record.update(_kib_fields(status, ("VmRSS", "RssAnon", "RssFile", "RssShmem")))
        rollup = _text(entry / "smaps_rollup") or ""
        record.update(_kib_fields(rollup, ("Pss", "Pss_Anon", "LazyFree")))
        try:
            record["fds"] = len(os.listdir(entry / "fd"))
        except OSError:
            record["fds"] = None
        record["kind"] = kind_of(record["cmd"], record["comm"])
        record["shard"] = shard_of(_text(entry / "environ") or "") \
            if record["kind"] in ("backend", "sandbox", "launcher") else None
        if record.get("RssAnon", 0) >= MAPS_FROM_BYTES:
            record["maps"] = anon_maps(entry.name)
        procs.append(record)
    return procs


def roles(procs: list[dict]) -> dict[str, dict]:
    """Each process's role, its shard taken from the nearest server above it."""
    by_pid = {p["pid"]: p for p in procs}
    out: dict[str, dict] = {}
    for proc in procs:
        role = None
        if proc["kind"] in ("backend", "sandbox", "pages", "launcher"):
            shard = proc["shard"]
            if shard is None:
                parent = by_pid.get(proc["ppid"])
                shard = parent["shard"] if parent and parent.get("shard") is not None else 0
            role = f"{proc['kind']}{shard}"
        else:
            seen, up = set(), by_pid.get(proc["ppid"])
            while up is not None and up["pid"] not in seen:
                seen.add(up["pid"])
                if up["kind"] in ("backend", "sandbox", "pages"):
                    role = f"{proc['kind']}@{up['kind']}{up['shard'] if up['shard'] is not None else 0}"
                    break
                up = by_pid.get(up["ppid"])
            role = role or proc["kind"]
        proc["role"] = role
        total = out.setdefault(role, {"n": 0, "rss": 0, "anon": 0, "pss": 0, "lazy": 0,
                                      "threads": 0, "fds": 0})
        total["lazy"] += proc.get("LazyFree", 0)
        total["n"] += 1
        total["rss"] += proc.get("VmRSS", 0)
        total["anon"] += proc.get("RssAnon", 0)
        total["pss"] += proc.get("Pss", 0)
        total["threads"] += proc["threads"]
        total["fds"] += proc["fds"] or 0
    return out


#: Single-number cgroup files and the key each one is recorded under.
CGROUP_NUMBERS = {"memory.current": "current", "memory.peak": "peak", "pids.current": "pids"}


def cgroup(root: Path = CGROUP) -> dict:
    """The container cgroup's memory in bytes, and its process count."""
    found = {}
    for name, key in CGROUP_NUMBERS.items():
        value = _text(root / name)
        if value and value.strip().isdigit():
            found[key] = int(value)
    stat = _text(root / "memory.stat") or ""
    for line in stat.splitlines():
        key, _, value = line.partition(" ")
        if key in STAT_KEYS and value.strip().isdigit():
            found[key] = int(value)
    return found


def read(_args) -> int:
    procs = processes()
    by_role = roles(procs)
    big = sorted(procs, key=lambda p: p.get("RssAnon", 0), reverse=True)[:12]
    keep = ("pid", "ppid", "role", "threads", "fds", "VmRSS", "RssAnon", "RssFile",
            "RssShmem", "Pss", "LazyFree", "maps", "cmd")
    print(json.dumps({"t": int(time.time()), "cgroup": cgroup(), "roles": by_role,
                      "top": [{k: p[k] for k in keep if k in p} for p in big]},
                     separators=(",", ":")))
    return 0


def _container(project: str) -> str | None:
    try:
        out = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}",
             "--filter", "label=com.docker.compose.service=curio"],
            capture_output=True, text=True, timeout=30, check=True).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    return out[0] if out else None


def sample(args) -> int:
    """Append a ``read`` of the container every ``--every`` seconds."""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).read_bytes()
    ends = time.monotonic() + args.minutes * 60
    while time.monotonic() < ends:
        started = time.monotonic()
        cid = _container(args.project)
        if cid:
            try:
                line = subprocess.run(
                    ["docker", "exec", "-i", cid, "python3", "-", "read"],
                    input=source, capture_output=True, timeout=120, check=True,
                ).stdout.decode("utf-8", "replace").strip()
                if line:
                    with out.open("a", encoding="utf-8") as fh:
                        fh.write(line + "\n")
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"sample failed: {exc}", file=sys.stderr)
        time.sleep(max(args.every - (time.monotonic() - started), 1.0))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("read", help="one JSON line for this container (run inside it)")
    sampling = sub.add_parser("sample", help="read the stack's container while the tests run")
    sampling.add_argument("--project", default="curio-ci", help="the stack's compose project")
    sampling.add_argument("--out", required=True)
    sampling.add_argument("--every", type=float, default=20.0, metavar="SECONDS")
    sampling.add_argument("--minutes", type=float, default=340.0,
                          help="stop after this long, inside the job's longest limit")
    args = parser.parse_args(argv[1:])
    return read(args) if args.command == "read" else sample(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
