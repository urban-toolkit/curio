"""Entry point: run the tiers against a live Curio stack.

    python -m utk_curio.backend.tests.stress --backend http://127.0.0.1:5002 \
        --tiers 5,10,50,100 --out .curio/stress

Each tier starts N users behind a barrier so they hit the stack together, and
every tier runs even if an earlier one failed -- the point is to see where the
limits are, not to stop at the first one. The process exits non-zero if any
tier had any failure.

A tier's users are also put in rooms of ``--room-size`` (``sockets.py``): each
opens a tab of its room's shared dataflow over Socket.IO, types and drags in
it while its own dataflow runs, and the report gives how long each update took
to reach the room's other tabs. Around each tier the probe (``--probe``,
``backend_probe.py``) reads the backend's threads and memory, and after it the
doc files the tier's shared dataflows left on disk. After a tier with any
failure it also saves every backend thread's stack in ``--out``
(``thread-stacks-tier-<n>-<users>-users.txt``), so a backend that stalled
shows the lock each thread waits on; ``--stacks-only`` saves them alone.

With ``--shared-canvas`` every member of a room works on the room's one
dataflow instead of a copy of its own: room k is made from example k of the
mix (round-robin), each member adds a Python node of its own below a node of
it (:func:`canvas_parent`), takes the lock of the node it types in, and plays
the dataflow as its tab holds it; the room's owner then runs it on the server
and saves it (``sockets.py``, ``driver.VirtualUser.on_the_canvas``). The solo
baseline runs each example with that node added, twice where it passes on the
output of a node that is not Python, which no tier compared before.

With ``--agents`` as well, every member also asks Node Builder to write its own
node's code, on Curio's scripted model, which is Curio's default for the tier
(``agents.py``): ten agents at work in each canvas while its people type,
drag and play.
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import multiprocessing
import os
import queue
import shlex
import sys
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

from ..test_frontend.workflow_spec import PY_CODE_TYPES, parse_workflow
from . import report as reporting
from . import sockets
from .agents import TURN_WAIT_S, RoomAgents, on_the_scripted_model
from .autk import compile_autk_data
from .backend_probe import (
    BackendProbe, Sampler, reading_now, save_thread_stacks, track_worker, worker_finished,
)
from .driver import AUTK_GRAMMAR, BURST, JS_COMPUTATION, PASS_ON, Pacing, VirtualUser, new_user_name

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
    "11-autark-pbf-loading.json",             # Autark: a PBF load, the heaviest
    "dataflows/regression.json",              # Autark data + compute
    "dataflows/js-computation.json",           # JS node on its own
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
# A session's tab types at a person's pace, three to eight keys a second, and
# stops after each drag as if to look at the canvas.
SESSION_KEY_GAP_MIN_S = 0.12
SESSION_KEY_GAP_MAX_S = 0.35
SESSION_PAUSE_MIN_S = 1.0
SESSION_PAUSE_MAX_S = 4.0

# How often the probe reads the backend while a tier runs, and how long after
# a tier it takes the last reading: long enough for the thread of each socket
# the tier closed to end, so a thread still there then was kept.
PROBE_EVERY_S = 1.0
PROBE_END_WAIT_S = 2.0

# Users per harness process: two rooms of five. Each socket message costs the
# harness about 0.6 ms of Python (tier 10 and the session profile, run
# 40777602350), so one process carrying a 50-user typing burst needed about
# 0.9 of a core and a 100-user one 1.8; ten users need about 0.2.
USERS_PER_PROCESS = 10


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
            key_gap_min=SESSION_KEY_GAP_MIN_S,
            key_gap_max=SESSION_KEY_GAP_MAX_S,
            pause_min=SESSION_PAUSE_MIN_S,
            pause_max=SESSION_PAUSE_MAX_S,
        )
        for _ in range(tier)
    ]


def build_rooms(names: list[str], room_size: int, shared: bool = False) -> list[sockets.Room]:
    """The tier's users in rooms of *room_size*, in order, the last one
    smaller; none for a room size of 0. *shared*: each a shared canvas."""
    if room_size <= 0:
        return []
    return [
        sockets.Room(index, names[index * room_size:(index + 1) * room_size], shared=shared)
        for index in range(math.ceil(len(names) / room_size))
    ]


def example_of(index: int, room_size: int, examples: list, shared_canvas: bool = False):
    """The example user *index* of a tier works on: round-robin over the mix,
    each user its own; on a shared canvas, its room's, room k on example k,
    so a tier of ten rooms makes every example of the mix a shared canvas."""
    if shared_canvas and room_size > 0:
        return examples[(index // room_size) % len(examples)]
    return examples[index % len(examples)]


def canvas_parent(workflow, autk_code: dict) -> dict | None:
    """The node of a dataflow each member of a shared canvas adds its own node
    below: the first, in the order the dataflow runs, whose output a Python
    node reads, a Python node's first, else a JavaScript node's, else an
    Autark node's that loads data (one in *autk_code*). ``{id, x, y,
    engine}``; None for a dataflow with none."""
    order = workflow.topo_sorted_nodes()
    for engine, kinds in (("python", PY_CODE_TYPES), ("javascript", (JS_COMPUTATION,)),
                          ("autark", (AUTK_GRAMMAR,))):
        for node in order:
            if node.type in kinds and (engine != "autark" or node.id in autk_code):
                return {"id": node.id, "x": node.x, "y": node.y, "engine": engine}
    return None


class Example:
    """One dataflow, parsed and pre-compiled once for every user that runs it."""

    def __init__(self, relpath: str):
        self.relpath = relpath
        self.path = os.path.join(EXAMPLES_DIR, relpath)
        if not os.path.exists(self.path):
            raise FileNotFoundError(self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.spec_json = json.loads(handle.read())
        self.workflow = parse_workflow(self.path)
        self.autk_code = compile_autk_data(self.path)
        self.canvas_parent = canvas_parent(self.workflow, self.autk_code)


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


def read_namespace(backend_url: str) -> str:
    """The collaboration namespace, read as the page reads it."""
    try:
        resp = requests.get(f"{backend_url}/api/config/public", timeout=30)
        namespace = (resp.json() or {}).get("collab_namespace")
    except (requests.RequestException, ValueError) as exc:
        raise SystemExit(f"[stress] could not read /api/config/public: {exc}") from exc
    if not isinstance(namespace, str) or not namespace.startswith("/"):
        raise SystemExit(f"[stress] /api/config/public names no collaboration namespace: {namespace!r}")
    return namespace


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


def run_baseline(backend_url: str, run_id: str, examples: list[Example],
                 shared_canvas: bool = False) -> dict:
    """Run each example alone, first, and keep its output hashes.

    This is the yardstick the concurrent users are measured against, and it
    doubles as a sanity check: if an example cannot pass on an idle stack, the
    tiers below would only be reporting that same breakage N times over.

    For shared canvases each example runs with the node a member adds
    (``VirtualUser.add_own_node``), its hash kept as :data:`PASS_ON`. Where
    that node passes on the output of a node that is not Python (an Autark
    node's layers, a JavaScript node's value), which no tier compared before,
    the example runs twice, and the two runs must agree before every member
    of its rooms is held to them.
    """
    baselines: dict[str, dict[str, str]] = {}
    for index, example in enumerate(examples):
        passes = 1
        if shared_canvas:
            if example.canvas_parent is None:
                raise SystemExit(f"[stress] {example.relpath} has no node whose output a Python node "
                                 "reads, so a shared canvas's members have nothing to add a node below")
            passes = 1 if example.canvas_parent["engine"] == "python" else 2
        runs = []
        for attempt in range(passes):
            user = VirtualUser(
                backend_url, new_user_name(0 if attempt == 0 else f"0r{attempt + 1}", index, run_id),
                example.relpath, example.spec_json, example.workflow, example.autk_code,
            )
            if shared_canvas:
                user.add_own_node(example.canvas_parent)
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
            hashes = dict(result.hashes)
            if shared_canvas:
                hashes[PASS_ON] = hashes.pop(user.own_node["id"], None)
            runs.append(hashes)
            print(f"[stress] baseline {example.relpath}: {result.seconds:.1f}s, "
                  f"{len(result.hashes)} hashed output(s)", flush=True)
        differ = sorted(key for key in set(runs[0]) | set(runs[-1]) if runs[0].get(key) != runs[-1].get(key))
        if differ:
            raise SystemExit(f"[stress] two solo runs of {example.relpath} gave different outputs at "
                             f"{', '.join(differ)}, so no member's could be compared with them")
        baselines[example.relpath] = runs[0]
    return baselines


def tier_slices(tier: int, room_size: int, per_process: int = USERS_PER_PROCESS) -> list[list[int]]:
    """The tier's users, by index, in the harness processes that run them:
    whole rooms each, in order, at most *per_process* users a process (or one
    room, when a room is larger)."""
    unit = room_size if room_size > 0 else 1
    groups = [list(range(first, min(first + unit, tier))) for first in range(0, tier, unit)]
    per = max(1, per_process // unit)
    return [sum(groups[k:k + per], []) for k in range(0, len(groups), per)]


def run_slice(job: dict, start_gate, register_gate, results_out) -> None:
    """One harness process's part of a tier: its users' sessions, their rooms
    whole, as threads of this process; what they did goes back to the main
    process through *results_out*, with this process's own CPU seconds."""
    from .backend_probe import process_cpu_seconds

    try:
        room_size, names, examples = job["room_size"], job["names"], job["examples"]
        shared = job.get("shared_canvas", False)
        mine = set(job["indices"])
        rooms = {room.index: room for room in build_rooms(names, room_size, shared=shared)
                 if room.index * room_size in mine}
        for room in rooms.values():
            if shared:
                example = example_of(room.index * room_size, room_size, examples, shared)
                room.example, room.parent = example.relpath, example.canvas_parent
            if job.get("agents"):
                room.agents = RoomAgents(room)
        users = []
        for index in job["indices"]:
            example = example_of(index, room_size, examples, shared)
            users.append(VirtualUser(
                job["backend_url"], names[index], example.relpath, example.spec_json,
                example.workflow, example.autk_code,
                compare_to=job["baselines"].get(example.relpath),
                register_gate=register_gate, start_gate=start_gate,
                pacing=job["pacing"][index],
                room=rooms[index // room_size] if room_size else None,
                namespace=job["namespace"],
                probe_command=job.get("probe_command"),
            ))
        with ThreadPoolExecutor(max_workers=len(users)) as pool:
            futures = [pool.submit(user.run) for user in users]
            results = [f.result(timeout=USER_DEADLINE_S) for f in futures]
        for room in rooms.values():
            if room.agents is not None:
                room.agents.wait_over(TURN_WAIT_S)
        results_out.put({"slice": job["slice"], "results": results,
                         "rooms": [room.outcome() for room in rooms.values()],
                         "cpu_seconds": process_cpu_seconds()})
    except BaseException as exc:  # noqa: BLE001 - the main process reports it for these users
        results_out.put({"slice": job["slice"], "error": f"{type(exc).__name__}: {exc}",
                         "cpu_seconds": process_cpu_seconds()})


def _lost_user(name: str, example: str, why: str):
    """The result of a user whose harness process never reported it."""
    from .driver import Sample, UserResult

    result = UserResult(user=name, example=example, started_at=time.time())
    result.samples.append(Sample(endpoint="harness process", node_id=None, status=None,
                                 seconds=0.0, ok=False, error=why[:2000], kind="transport"))
    return result


def run_tier(backend_url: str, run_id: str, tier: int, examples: list[Example],
             baselines: dict, register_concurrency: int,
             profile: str = "burst", label: str | None = None,
             room_size: int = 0, namespace: str | None = None,
             shared_canvas: bool = False, probe_command: list | None = None,
             agents: bool = False) -> tuple[list, float, list]:
    """Run *tier* users, all doing their dataflow work at the same moment,
    and, in rooms of *room_size*, each with its tab of its room's dataflow;
    the results, the seconds it took, and each room's outcome
    (``sockets.Room.outcome``). With *shared_canvas*, every member works on
    its room's one dataflow, and the room's owner reads the file its save
    wrote through *probe_command* (``backend_probe``), when there is one;
    with *agents* too, every member also asks its agent to write its node
    (``agents.RoomAgents``).

    The users run in harness processes of their own (:func:`tier_slices`,
    :func:`run_slice`), whole rooms each, behind one start gate that spans
    them: one process driving every user's calls and tab was the busier side
    of a 50-user typing burst, so it measured itself.

    ``register_concurrency`` caps how many accounts are created at once (0
    means no cap). Registration is the one step that is throttled; see
    ``VirtualUser.run``.
    """
    context = multiprocessing.get_context("spawn")
    start_gate = context.Barrier(tier)
    register_gate = context.Semaphore(register_concurrency) if register_concurrency else None
    # Seeded on the run id: two runs of the same tier get the same arrival
    # pattern, so their numbers can be compared.
    pacing = build_pacing(profile, tier, random.Random(f"{run_id}-{tier}"))
    label = label or str(tier)
    names = [new_user_name(label, index, run_id) for index in range(tier)]
    slices = tier_slices(tier, room_size)
    results_out = context.Queue()
    processes = []
    started = time.time()
    for number, indices in enumerate(slices):
        job = {"slice": number, "indices": indices, "names": names, "examples": examples,
               "baselines": baselines, "pacing": pacing, "room_size": room_size,
               "namespace": namespace, "backend_url": backend_url,
               "shared_canvas": shared_canvas, "probe_command": probe_command, "agents": agents}
        process = context.Process(target=run_slice, args=(job, start_gate, register_gate, results_out),
                                  name=f"stress-{label}-{number}", daemon=True)
        process.start()
        track_worker(process.pid)
        processes.append(process)

    reported: dict[int, dict] = {}
    deadline = time.monotonic() + USER_DEADLINE_S + 120
    while len(reported) < len(slices) and time.monotonic() < deadline:
        try:
            message = results_out.get(timeout=5)
        except queue.Empty:
            if not any(process.is_alive() for process in processes) and results_out.empty():
                break
            continue
        reported[message["slice"]] = message
        worker_finished(processes[message["slice"]].pid, message["cpu_seconds"])
    for process in processes:
        process.join(timeout=30)
    seconds = time.time() - started

    results, outcomes = [], []
    for number, indices in enumerate(slices):
        message = reported.get(number)
        if message is not None and "results" in message:
            results.extend(message["results"])
            outcomes.extend(message["rooms"])
            continue
        why = (message or {}).get("error") or (
            f"its harness process ended (exit code {processes[number].exitcode}) without reporting"
        )
        results.extend(_lost_user(names[index], example_of(index, room_size, examples, shared_canvas).relpath, why)
                       for index in indices)
    return results, seconds, outcomes


def make_probe(args) -> BackendProbe | None:
    """The probe ``--probe`` names: a command that runs Python where the
    backend runs; this Python by default, for a stack on this machine."""
    if args.no_probe:
        return None
    command = shlex.split(args.probe) if args.probe.strip() else [sys.executable]
    return BackendProbe(command)


def probe_tier(probe: BackendProbe | None, run):
    """Run *run* (a tier) between two readings, sampling while it runs:
    ``(what run returned, backend summary, doc files summary, harness
    summary)``. The backend is read through *probe*; the harness's own CPU is
    read whatever the probe. *run* returns its rooms' outcomes last, whose
    dataflows' doc files are listed."""
    problems = []
    start, problem = reading_now(probe)
    if problem:
        problems.append(f"before the tier: {problem}")
    sampler = Sampler(probe, PROBE_EVERY_S).start()
    try:
        outcome = run()
    finally:
        samples = sampler.stop()
    if sampler.problem:
        problems.append(f"while it ran: {sampler.problem}")
    if probe is not None:
        time.sleep(PROBE_END_WAIT_S)
    project_ids = [room["project_id"] for room in outcome[-1] if room.get("project_id")]
    end, problem = reading_now(probe, project_ids)
    if problem:
        problems.append(f"after the tier: {problem}")
    if probe is None:
        problems = ["not asked for (--no-probe)"]
    problem = "; ".join(problems) or None
    listing = end.get("docs") if project_ids else {}
    return (outcome,
            reporting.backend_summary(start, samples, end, PROBE_EVERY_S, problem),
            reporting.doc_files_summary(listing, problem),
            reporting.harness_summary(start, samples, end))


def tier_lines(summary: dict) -> list[str]:
    """What a tier's tabs and the backend's process did, for the log."""
    lines = []
    tabs = summary.get("sockets")
    if tabs:
        sync = tabs["sync_ms"]
        timing = (f"sync p50 {sync['p50']} ms, p95 {sync['p95']} ms, max {sync['max']} ms"
                  if sync else "no other tab to sync with")
        lines.append(
            f"{tabs['rooms']} room(s), {tabs['tabs']} tab(s) over "
            f"{' and '.join(tabs['transports']) or 'no socket'}: {tabs['updates']} "
            f"update(s), {timing}; {tabs['unsynced']} unsynced, "
            f"{tabs['diverged_rooms']} room(s) diverged"
        )
    canvas = summary.get("canvas")
    if canvas:
        locks, runs, saved = canvas["locks"], canvas["server_runs"], canvas["saved"]
        held = "not read" if locks["held_at_end"] is None else locks["held_at_end"]
        took = runs["seconds"]
        lines.append(
            f"{canvas['rooms']} shared canvas(es): {canvas['nodes_added']} node(s) and "
            f"{canvas['edges_added']} connection(s) added; locks {locks['taken']} taken, "
            f"{locks['refused']} refused, {held} held at the end; {runs['count']} run(s) on the server "
            f"({', '.join(f'{n} {s}' for s, n in sorted(runs['statuses'].items())) or 'none'}"
            + (f", p50 {took['p50']} s, max {took['max']} s" if took else "")
            + f"), {runs['not_done']} step(s) not done; {saved['read']} save(s) read back, "
            f"{saved['lacks']} thing(s) missing from them"
        )
    agents = summary.get("agents")
    if agents:
        ends, writes, took = agents["ends"], agents["writes"], agents["turn_s"]
        present = "not read" if agents["present_at_end"] is None else agents["present_at_end"]
        lines.append(
            f"{agents['asked']} agent turn(s) on the scripted model in {agents['rooms']} canvas(es): "
            f"{ends['done']} done, {ends['error']} error, {ends['never']} never ended"
            + (f", p50 {took['p50']} s, p95 {took['p95']} s, max {took['max']} s" if took else "")
            + f"; writes {writes['landed']} landed, {writes['changed_meanwhile']} refused as changed meanwhile, "
            f"{writes['refused']} refused otherwise, {writes['none']} never made; {agents['unsynced']} "
            f"missing from a tab, {present} agent(s) in the room at the end"
        )
    backend = summary.get("backend") or {}
    if backend.get("measured"):
        threads, rss = backend["threads"], backend["rss_mib"]
        lines.append(
            f"backend threads {threads['start']} -> {threads['peak']} -> {threads['end']}, "
            f"RSS {rss['start']} -> {rss['peak']} -> {rss['end']} MiB "
            f"({backend['samples']} reading(s) while it ran)"
        )
    elif backend:
        lines.append(f"backend not measured: {backend.get('problem')}")
    cpu = []
    for name, track in (("backend", backend.get("cpu")),
                        ("harness", (summary.get("harness") or {}).get("cpu"))):
        if track:
            cpu.append(f"{name} {track['seconds']} s, {track['cores_busy']} cores "
                       f"(peak {track['peak_cores_busy']})")
    if cpu:
        lines.append("CPU: " + "; ".join(cpu))
    files = summary.get("doc_files") or {}
    if files.get("measured"):
        lines.append(
            f"{files['docs']} doc log(s) on disk: .bin {files['bin_bytes']['total']} B, "
            f".updates {files['updates_bytes']['total']} B"
            + (f"; no log for {', '.join(files['without_log'])}" if files["without_log"] else "")
        )
    return lines


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
    parser.add_argument("--room-size", type=int, default=sockets.ROOM_SIZE,
                        help="users per shared dataflow, whose tabs type and "
                             "drag in it together over Socket.IO (0: no tabs)")
    parser.add_argument("--shared-canvas", action="store_true",
                        help="every member of a room works on the room's one "
                             "dataflow (room k on example k of the mix): adds a "
                             "node of its own, takes the lock of the node it "
                             "types in, plays the dataflow as its tab holds it, "
                             "and the room's owner runs it on the server and "
                             "saves it")
    parser.add_argument("--agents", action="store_true",
                        help="with --shared-canvas, every member also asks "
                             "Node Builder to write its own node's code, on "
                             "Curio's scripted model, which is Curio's default "
                             "for the tier (the stack needs --testing)")
    parser.add_argument("--probe", default="",
                        help="the command that runs Python where the backend "
                             "runs, to read its threads, memory and doc files, "
                             "such as 'docker exec <container> python'; this "
                             "Python by default, for a stack on this machine")
    parser.add_argument("--no-probe", action="store_true",
                        help="read nothing of the backend's process")
    parser.add_argument("--run-id", default=uuid.uuid4().hex[:6])
    parser.add_argument("--stacks-only", metavar="NAME", default="",
                        help="run no tier: only ask the backend, through the "
                             "probe, for every thread's stack, saved in --out "
                             "as thread-stacks-NAME.txt (a CI job does after a "
                             "failed step)")
    args = parser.parse_args(argv)

    if args.stacks_only:
        # Before anything that waits on the backend, which may be stalled.
        probe = make_probe(args)
        if probe is None:
            parser.error("--stacks-only asks through the probe, which --no-probe turns off")
        _, line = save_thread_stacks(probe, args.out, args.stacks_only)
        print(f"[stress] {line}", flush=True)
        return 0

    backend_url = args.backend.rstrip("/")
    tiers = [int(t) for t in args.tiers.split(",") if t.strip()]
    room_size = max(0, args.room_size)
    if args.shared_canvas and not room_size:
        parser.error("--shared-canvas puts each room on one dataflow, so it needs a --room-size")
    if args.agents and not args.shared_canvas:
        parser.error("--agents has each member's agent write its own node of a shared canvas, "
                     "so it needs --shared-canvas")
    examples = load_mix([m.strip() for m in args.mix.split(",") if m.strip()])
    if room_size:
        sockets.require_websocket_client()

    wait_for_backend(backend_url)
    namespace = read_namespace(backend_url) if room_size else None
    probe = make_probe(args)
    print(f"[stress] run {args.run_id} against {backend_url}; "
          f"tiers {tiers}; profile {args.profile}; "
          + (f"rooms of {room_size} on {namespace}" if room_size else "no tabs")
          + ("; each room one shared canvas" if args.shared_canvas else "")
          + ("; each member's agent at work on it" if args.agents else ""),
          flush=True)

    baselines = run_baseline(backend_url, args.run_id, examples, shared_canvas=args.shared_canvas)

    def tier_run(tier: int, position: int):
        """The tier, as :func:`probe_tier` runs it; with the agents, on
        Curio's scripted model, its default for the tier alone. Read only
        once the tier runs, the probe's command among it."""
        run = functools.partial(
            run_tier, backend_url, args.run_id, tier, examples, baselines,
            args.register_concurrency, args.profile, label=f"{tier}x{position}",
            room_size=room_size, namespace=namespace, shared_canvas=args.shared_canvas,
            probe_command=probe.command if probe is not None else None, agents=args.agents,
        )
        return on_the_scripted_model(backend_url, run) if args.agents else run()

    tier_reports = []
    all_results = []
    for position, tier in enumerate(tiers):
        print(f"[stress] tier {tier}: starting", flush=True)
        # Bracketing the tier, because the counters are cumulative since the
        # sandbox started and the baseline runs before the first tier.
        lock_before = read_exec_lock(backend_url)
        (results, seconds, outcomes), backend, doc_files, harness = probe_tier(
            probe, functools.partial(tier_run, tier, position))
        all_results.extend(results)
        lock = reporting.exec_lock_delta(lock_before, read_exec_lock(backend_url))
        tabs = reporting.socket_summary(outcomes)
        summary = reporting.tier_summary(tier, results, seconds, args.profile,
                                         exec_lock=lock, sockets=tabs,
                                         backend=backend, doc_files=doc_files,
                                         harness=harness,
                                         canvas=reporting.canvas_summary(outcomes))
        summary["agents"] = reporting.agents_summary(outcomes)
        tier_reports.append(summary)
        print(f"[stress] tier {tier}: {summary['completed']}/{tier} completed in "
              f"{seconds:.1f}s, {summary['failure_count']} failure(s)", flush=True)
        if lock:
            waits = ", ".join(
                f"{label} {stat['wait_seconds']}s over {stat['acquisitions']}"
                for label, stat in sorted(lock["labels"].items())
            )
            print(f"[stress] tier {tier}: exec lock waited {waits}", flush=True)
        for line in tier_lines(summary):
            print(f"[stress] tier {tier}: {line}", flush=True)
        if summary["failure_count"] and probe is not None:
            _, line = save_thread_stacks(probe, args.out, f"tier-{position + 1}-{tier}-users")
            print(f"[stress] tier {tier}: {line}", flush=True)

    report = reporting.build_report(args.run_id, backend_url, tier_reports,
                                    args.stats_log, profile=args.profile,
                                    room_size=room_size, shared_canvas=args.shared_canvas)
    report["agents"] = args.agents
    json_path, md_path = reporting.write_outputs(report, args.out)
    with open(os.path.join(args.out, "samples.json"), "w", encoding="utf-8") as fh:
        json.dump(reporting.raw_samples(all_results), fh)
    print(f"[stress] wrote {json_path} and {md_path}", flush=True)
    print(reporting.markdown(report))

    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
