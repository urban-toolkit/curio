#!/usr/bin/env python3
"""Run several Curio stacks on one runner, and the same tests on each of them.

The flake hunt (.github/workflows/flake-hunt.yml) runs this on R runners at
once, S stacks on each, so R x S stacks run at the same time. Each stack, a
*lane*, is the CI image under its own compose project (curio-lane-k), with its
own host ports and its own git worktree (.lanes/k). The worktree is what keeps
the lanes apart: the stack's bind mounts (./.curio, ./instance, ./datasets)
resolve from it, and so do the e2e harness's state dir, the test DB the backend
conftest deletes, and the dist/ copy the SPA test serves.

Each lane runs the chosen suite FLAKE_ITERATIONS times, the way the Full stack
build runs it: e2e as e2e-desktop does (the non-WebGPU half), backend and
sandbox as the unit job does, inside the lane's container. With no filter the
lanes split the suite (CURIO_E2E_PART or CURIO_UNIT_PART, k/N over all N lanes)
and the part a lane runs moves on every iteration, so each test meets other
neighbours. With a filter every lane runs the same tests. scripts/ci_flakes.py
reads what this leaves in FLAKE_OUT.

Subcommands, one step of the lanes job each:

    start    worktrees, stacks and samplers; record which stacks became healthy
    barrier  wait until every lanes job of this run attempt has started its stacks
    run      every lane's iterations, the lanes in parallel
    stop     record OOM kills, stop the samplers, remove the stacks and worktrees

Settings come from the environment, so every step passes only the subcommand:
FLAKE_RUNNER (this runner, from 1), FLAKE_RUNNERS, FLAKE_STACKS,
FLAKE_ITERATIONS, FLAKE_SUITE (e2e, backend or sandbox), FLAKE_TESTS (a pytest
-k expression), FLAKE_WORKFLOWS (e2e workflow files, A.json,B.json),
FLAKE_IMAGE and FLAKE_OUT.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

# Appended, not put first: a test process that imports this keeps every other
# import as it was.
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import ci_pick_runners  # noqa: E402  (the jobs API call)
import ci_report  # noqa: E402  (the JUnit and comparison readers)

STACK = Path(__file__).resolve().parent / "ci_stack.sh"
PROJECT_PREFIX = "curio-lane-"
COMPOSE_FILE = "docker-compose.yml:docker-compose.ci.yml"
SANDBOX_TOKEN = "ci-sandbox-token-not-a-secret"
SUITES = ("e2e", "backend", "sandbox")

#: Lane k's host ports are these bases plus k. The block is clear of every
#: other stack a runner can hold (the table in docker-compose.ci-stress.yml).
BACKEND_BASE, SANDBOX_BASE, FRONTEND_BASE = 5100, 2100, 8200
#: A CPU runner has 32 GB. The first hunt measured five stacks' containers
#: at 21.7 GiB together (4.3 GiB each), before their Chromiums on the host.
MAX_STACKS = 6

START_STAGGER_S = 10
START_WAIT_S = 420  # as test-desktop-stress, whose stack also starts beside others
RUN_LIMIT_S = 3600
BARRIER_LIMIT_S = 1800
BARRIER_POLL_S = 15
SAMPLE_S = 5
#: The lanes job's step that starts the stacks, as the barrier finds it.
START_STEP = "Start the stacks"

#: The classname of the flake hunt's own checks in the JUnit it writes.
HARNESS = "flake_hunt"
THREAD_EXHAUSTION = "can't start new thread"

#: Variables that would point a lane at another stack, state dir or test set.
DROPPED = ("CURIO_STATE_DIR", "BACKEND_PORT", "SANDBOX_PORT", "FRONTEND_PORT",
           "COMPOSE_PROJECT_NAME", "CURIO_E2E_PARALLEL", "PYTEST_ADDOPTS",
           "CURIO_E2E_PART", "CURIO_UNIT_PART", "CURIO_E2E_WORKFLOWS")


@dataclass(frozen=True)
class Config:
    runner: int
    runners: int
    stacks: int
    iterations: int
    suite: str
    tests: str
    workflows: str
    image: str
    out: Path
    workspace: Path

    @property
    def total(self) -> int:
        return self.runners * self.stacks

    @property
    def filtered(self) -> bool:
        return bool(self.tests or self.workflows)


@dataclass(frozen=True)
class Lane:
    k: int  # on this runner, from 1
    g: int  # over every runner, from 1
    project: str
    path: Path
    backend: int
    sandbox: int
    frontend: int

    @property
    def name(self) -> str:
        return f"lane-{self.g}"


def config_from_env(environ) -> Config:
    def number(name, default):
        value = (environ.get(name) or "").strip()
        return int(value) if value else default

    workspace = Path(environ.get("GITHUB_WORKSPACE") or os.getcwd())
    cfg = Config(
        runner=number("FLAKE_RUNNER", 1),
        runners=number("FLAKE_RUNNERS", 1),
        stacks=number("FLAKE_STACKS", 1),
        iterations=number("FLAKE_ITERATIONS", 1),
        suite=(environ.get("FLAKE_SUITE") or "e2e").strip(),
        tests=(environ.get("FLAKE_TESTS") or "").strip(),
        workflows=(environ.get("FLAKE_WORKFLOWS") or "").strip(),
        image=(environ.get("FLAKE_IMAGE") or "").strip(),
        out=Path(environ.get("FLAKE_OUT") or workspace / "flake-out"),
        workspace=workspace,
    )
    if cfg.suite not in SUITES:
        raise ValueError(f"FLAKE_SUITE must be one of {', '.join(SUITES)}, not {cfg.suite!r}")
    if not 1 <= cfg.stacks <= MAX_STACKS:
        raise ValueError(f"FLAKE_STACKS must be 1 to {MAX_STACKS}, not {cfg.stacks}")
    if not 1 <= cfg.runner <= cfg.runners:
        raise ValueError(f"FLAKE_RUNNER must be 1 to FLAKE_RUNNERS ({cfg.runners}), not {cfg.runner}")
    if cfg.iterations < 1:
        raise ValueError(f"FLAKE_ITERATIONS must be at least 1, not {cfg.iterations}")
    if cfg.workflows and cfg.suite != "e2e":
        raise ValueError("FLAKE_WORKFLOWS names e2e workflow files; it needs FLAKE_SUITE=e2e")
    return cfg


def lanes_for(cfg: Config) -> list[Lane]:
    return [Lane(k=k, g=(cfg.runner - 1) * cfg.stacks + k, project=f"{PROJECT_PREFIX}{k}",
                 path=cfg.workspace / ".lanes" / str(k), backend=BACKEND_BASE + k,
                 sandbox=SANDBOX_BASE + k, frontend=FRONTEND_BASE + k)
            for k in range(1, cfg.stacks + 1)]


def part_for(g: int, iteration: int, total: int) -> int:
    """The part lane g runs in an iteration, from 1.

    Each iteration hands every part to exactly one lane, and each lane gets
    the next part every iteration, so over the iterations a test runs beside
    different neighbours and on different stacks.
    """
    return (g - 1 + iteration - 1) % total + 1


def part_of(cfg: Config, lane: Lane, iteration: int) -> str:
    """CURIO_E2E_PART or CURIO_UNIT_PART for this run, or "" for the whole suite."""
    if cfg.filtered or cfg.suite == "sandbox":
        return ""
    return f"{part_for(lane.g, iteration, cfg.total)}/{cfg.total}"


def stack_env(lane: Lane, base) -> dict:
    """The environment compose and the e2e harness need to reach this lane's stack."""
    env = {name: value for name, value in base.items() if name not in DROPPED}
    env.update({
        "COMPOSE_FILE": COMPOSE_FILE,
        "CURIO_E2E_BACKEND_URL": f"http://localhost:{lane.backend}",
        "CURIO_E2E_HOST": "localhost",
        "CURIO_E2E_BACKEND_PORT": str(lane.backend),
        "CURIO_E2E_SANDBOX_PORT": str(lane.sandbox),
        "CURIO_E2E_FRONTEND_PORT": str(lane.frontend),
        "FLASK_SANDBOX_HOST": "localhost",
        "FLASK_SANDBOX_PORT": str(lane.sandbox),
        "CURIO_SANDBOX_TOKEN": SANDBOX_TOKEN,
    })
    return env


def run_spec(cfg: Config, lane: Lane, iteration: int, iter_dir: Path, base):
    """The command, its environment and where its JUnit lands, for one run."""
    env = stack_env(lane, base)
    part = part_of(cfg, lane, iteration)
    select = ["-k", cfg.tests] if cfg.tests else []
    if cfg.suite == "e2e":
        junit = iter_dir / "junit.xml"
        env.update({
            "CURIO_E2E_RUNNER": "desktop",
            "CURIO_E2E_DATAPOOL_TIMEOUT_MS": "120000",
            "CURIO_E2E_TRACE": "1",
            "CURIO_E2E_FAILURE_DIR": str(iter_dir / "failures"),
            "CURIO_E2E_COMPARE_DIR": str(iter_dir / "comparisons"),
            "PYTEST_ADDOPTS": shlex.join([f"--junitxml={junit}", *select]),
        })
        if part:
            env["CURIO_E2E_PART"] = part
        argv = ["bash", "scripts/test.sh", "--e2e-only", "--use-existing"]
        if cfg.workflows:
            argv += ["--workflows", cfg.workflows]
        if cfg.filtered:
            # A filter may name only tests the WebGPU runner owns.
            argv.append("--allow-empty")
        return argv, env, junit
    # Inside the lane's container, as the unit job runs them. The JUnit is
    # written onto the .curio bind mount, so it shows up in the worktree.
    name = f"flake-iter-{iteration}.xml"
    argv = ["docker", "compose", "-p", lane.project, "exec", "-T"]
    if part:
        argv += ["-e", f"CURIO_UNIT_PART={part}"]
    argv += ["-e", "PYTEST_ADDOPTS=" + shlex.join([f"--junitxml=/app/.curio/ci-report/{name}", *select]),
             "curio", "bash", "scripts/test.sh", f"--{cfg.suite}-only", "--use-existing"]
    return argv, env, lane.path / ".curio" / "ci-report" / name


def harness_xml(cases) -> str:
    """JUnit for the flake hunt's own checks, read like any other suite.

    *cases* holds (name, failure message or "", details), one per check.
    """
    suites = ET.Element("testsuites")
    suite = ET.SubElement(suites, "testsuite", name=HARNESS, tests=str(len(cases)),
                          failures=str(sum(1 for _, message, _ in cases if message)))
    for name, message, details in cases:
        case = ET.SubElement(suite, "testcase", classname=HARNESS, name=name, time="0")
        if message:
            ET.SubElement(case, "failure", message=message).text = details
    return ET.tostring(suites, encoding="unicode")


def ran_cases(junit: Path) -> int:
    """How many tests a JUnit file says ran (passed, failed or errored)."""
    if not junit.is_file():
        return 0
    return sum(1 for case in ci_report.read_junit("run", str(junit)).cases
               if case.status in ("passed", "failed", "error"))


def run_checks(cfg: Config, iteration: int, junit: Path, returncode, ended: str) -> list:
    """The hunt's own checks on one finished run, as harness_xml takes them.

    A run that died before pytest wrote anything, or a part of the split
    suite that ran nothing (a wrong split, every test skipped), would
    otherwise vanish from the counts and read as a clean run.
    """
    missing = "" if junit.is_file() else (
        f"iteration {iteration} wrote no JUnit (exit {returncode}); see its test-output.log")
    empty = ""
    if junit.is_file() and not cfg.filtered and ran_cases(junit) == 0:
        empty = f"iteration {iteration} ran no test: every one was skipped or none was selected"
    return [("stack_still_running", "", ""), ("run_ends_in_time", ended, ""),
            ("run_writes_results", missing, ""), ("run_runs_tests", empty, "")]


def started_lanes_jobs(jobs) -> int:
    """How many lanes jobs of a run have started their stacks, or ended."""
    started = 0
    for job in jobs:
        if not (job.get("name") or "").startswith("lanes"):
            continue
        if job.get("status") == "completed" or any(
                START_STEP in (step.get("name") or "") and step.get("status") == "completed"
                for step in job.get("steps") or []):
            started += 1
    return started


def prune_comparisons(root: Path, junit: Path) -> None:
    """Keep only the screenshot comparisons of tests that failed.

    The rest is bulk: every comparison holds its frames at full size, and a
    hunt runs each test many times.
    """
    if not root.is_dir():
        return
    failed = set()
    if junit.is_file():
        suite = ci_report.read_junit("e2e", str(junit))
        failed = {case.key for case in suite.cases if case.status in ("failed", "error")}
    for folder in root.iterdir():
        try:
            record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # no record: the run died writing it, which is worth keeping
        if ci_report.junit_key(record.get("nodeid") or "") not in failed:
            shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- docker and git


def sh(argv, *, cwd=None, env=None, check=True, capture=False, timeout=None):
    return subprocess.run([str(a) for a in argv], cwd=cwd, env=env, check=check, text=True,
                          capture_output=capture, timeout=timeout)


def stack(command, *args, lane=None, base=None, check=True, capture=False):
    """One ci_stack.sh subcommand, in the lane's worktree with its environment."""
    argv = ["bash", STACK, command, *args]
    if lane is None:
        return sh(argv, check=check, capture=capture)
    return sh(argv, cwd=lane.path, env=stack_env(lane, base), check=check, capture=capture)


def container(lane: Lane, base) -> str:
    found = sh(["docker", "compose", "-p", lane.project, "ps", "-a", "-q", "curio"],
               cwd=lane.path, env=stack_env(lane, base), check=False, capture=True)
    ids = found.stdout.split()
    return ids[0] if ids else ""


def inspect(cid: str, template: str) -> str:
    if not cid:
        return ""
    return sh(["docker", "inspect", "--format", template, cid], check=False, capture=True).stdout.strip()


def write_harness(path: Path, cases) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(harness_xml(cases), encoding="utf-8")


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def read_from(path: Path, offset: int) -> str:
    """What a log gained since *offset*; the container's files can be root's."""
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            return handle.read().decode("utf-8", "replace")
    except PermissionError:
        shown = sh(["docker", "run", "--rm", "-v", f"{path.parent}:/c", "alpine",
                    "tail", "-c", f"+{offset + 1}", f"/c/{path.name}"], check=False, capture=True)
        return shown.stdout
    except OSError:
        return ""


# ---------------------------------------------------------------- subcommands


def start(cfg: Config, base) -> None:
    cfg.out.mkdir(parents=True, exist_ok=True)
    git = ["git", "-C", cfg.workspace]
    lanes = lanes_for(cfg)
    stack("clean", f"^{PROJECT_PREFIX}")
    for lane in lanes:
        # A cancelled hunt's worktree; the job's reclaim step made it ours.
        shutil.rmtree(lane.path, ignore_errors=True)
    sh(git + ["worktree", "prune"])
    for lane in lanes:
        sh(git + ["worktree", "add", "--detach", lane.path, "HEAD"])
        stack("pull", cfg.image, lane.project)

    samplers = [subprocess.Popen([sys.executable, __file__, name], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for name in ("_health", "_stats")]
    (cfg.out / "samplers.pid").write_text(" ".join(str(p.pid) for p in samplers), encoding="utf-8")

    up = {}
    for index, lane in enumerate(lanes):
        if index:
            time.sleep(START_STAGGER_S)
        up[lane.g] = stack("up", lane.project, lane=lane, base=base, check=False, capture=True)

    def wait(lane):
        if up[lane.g].returncode != 0:
            return up[lane.g]
        return stack("wait", lane.project, START_WAIT_S, lane=lane, base=base, check=False, capture=True)

    with ThreadPoolExecutor(len(lanes)) as pool:
        waited = list(pool.map(wait, lanes))

    healthy = {}
    for lane, result in zip(lanes, waited):
        output = (result.stdout or "") + (result.stderr or "")
        print(f"::group::{lane.name} ({lane.project}, backend {lane.backend})\n{output}::endgroup::")
        ok = result.returncode == 0
        healthy[lane.g] = ok
        message = "" if ok else f"{lane.project} did not become healthy in {START_WAIT_S}s"
        write_harness(cfg.out / lane.name / "harness-start.xml",
                      [("stack_becomes_healthy", message, "" if ok else ci_report.clip(output))])
        if ok:
            prepare(lane, base)

    runner = {
        "runner": cfg.runner,
        "runners": cfg.runners,
        "runner_name": base.get("RUNNER_NAME") or "",
        "stacks": cfg.stacks,
        "iterations": cfg.iterations,
        "suite": cfg.suite,
        "tests": cfg.tests,
        "workflows": cfg.workflows,
        "image": cfg.image,
        "lanes": [{"g": lane.g, "project": lane.project, "backend": lane.backend,
                   "sandbox": lane.sandbox, "frontend": lane.frontend,
                   "healthy": healthy[lane.g],
                   "parts": [part_of(cfg, lane, i) for i in range(1, cfg.iterations + 1)]}
                  for lane in lanes],
    }
    (cfg.out / "runner.json").write_text(json.dumps(runner, indent=2), encoding="utf-8")
    print(f"{sum(healthy.values())} of {len(lanes)} stacks are healthy on this runner")


def prepare(lane: Lane, base) -> None:
    """What e2e-desktop does between start-stack and the tests."""
    curio = lane.path / ".curio"
    if sh(["docker", "run", "--rm", "-v", f"{curio}:/c", "alpine", "chmod", "-R", "a+rwx", "/c"],
          check=False).returncode != 0:
        (curio / "playwright" / "expected").mkdir(parents=True, exist_ok=True)
    # test_spa_deep_link_e2e.py serves the bundle the image ships, and dist/
    # is not in the checkout.
    # A copy that fails shows up as that test failing on this lane.
    dist = lane.path / "utk_curio" / "frontend" / "urban-workflows" / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    sh(["docker", "cp", f"{container(lane, base)}:/app/utk_curio/frontend/urban-workflows/dist", dist],
       check=False)


def barrier(cfg: Config, base) -> None:
    """Hold this runner's lanes until every runner has its stacks up.

    The lanes jobs queue for runners one by one, so without this a runner
    could start its tests after another one finished, and the hunt would
    never have all its stacks up at once.
    """
    api = base.get("GITHUB_API_URL") or "https://api.github.com"
    url = (f"{api}/repos/{base.get('GITHUB_REPOSITORY')}/actions/runs/{base.get('GITHUB_RUN_ID')}"
           f"/attempts/{base.get('GITHUB_RUN_ATTEMPT') or 1}/jobs?per_page=100")
    deadline = time.monotonic() + BARRIER_LIMIT_S
    started, message = 0, ""
    while True:
        try:
            started = started_lanes_jobs(ci_pick_runners._get(url, base.get("GITHUB_TOKEN") or "")["jobs"])
        except Exception as error:  # one failed poll is not a verdict
            print(f"jobs API: {error}")
        if started >= cfg.runners:
            print(f"all {cfg.runners} runners have started their stacks")
            break
        if time.monotonic() > deadline:
            message = (f"only {started} of {cfg.runners} runners had started their stacks after "
                       f"{BARRIER_LIMIT_S // 60} minutes; this one went on alone")
            print(f"::warning::{message}")
            break
        print(f"{started} of {cfg.runners} runners have started their stacks; waiting")
        time.sleep(BARRIER_POLL_S)
    write_harness(cfg.out / "harness-barrier.xml", [("runners_start_together", message, "")])


def run(cfg: Config, base) -> None:
    runner = json.loads((cfg.out / "runner.json").read_text(encoding="utf-8"))
    healthy = {entry["g"] for entry in runner["lanes"] if entry["healthy"]}
    lanes = [lane for lane in lanes_for(cfg) if lane.g in healthy]
    if not lanes:
        print("::warning::no stack became healthy on this runner; nothing to run")
        return

    def one_lane(lane):
        for iteration in range(1, cfg.iterations + 1):
            run_iteration(cfg, lane, iteration, base)

    # The lanes do not wait for each other between iterations, so every stack
    # stays busy until its own last run.
    with ThreadPoolExecutor(len(lanes)) as pool:
        list(pool.map(one_lane, lanes))


def run_iteration(cfg: Config, lane: Lane, iteration: int, base) -> None:
    iter_dir = cfg.out / lane.name / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    cid = container(lane, base)
    if inspect(cid, "{{.State.Running}}") != "true":
        write_harness(iter_dir / "harness.xml", [(
            "stack_still_running", f"{lane.project} was not running before iteration {iteration}",
            inspect(cid, "{{json .State}}"))])
        print(f"[{lane.name}] iteration {iteration}: the stack is not running")
        return

    argv, env, junit = run_spec(cfg, lane, iteration, iter_dir, base)
    messages = lane.path / ".curio" / "messages.log"
    offset = file_size(messages)
    began = time.time()
    ended = ""
    with (iter_dir / "test-output.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(argv, cwd=lane.path, env=env, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            proc.wait(timeout=RUN_LIMIT_S)
        except subprocess.TimeoutExpired:
            ended = f"iteration {iteration} did not finish in {RUN_LIMIT_S // 60} minutes"
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(proc.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    proc.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if cfg.suite != "e2e":
                # Killing `docker compose exec` leaves its pytest running in the container.
                sh(["docker", "compose", "-p", lane.project, "exec", "-T", "curio", "pkill", "-f", "pytest"],
                   cwd=lane.path, env=stack_env(lane, base), check=False)
    seconds = round(time.time() - began, 1)

    if junit != iter_dir / "junit.xml" and junit.is_file():
        shutil.copyfile(junit, iter_dir / "junit.xml")
    logs = sh(["docker", "compose", "-p", lane.project, "logs", "--no-color", "--since", str(int(began))],
              cwd=lane.path, env=stack_env(lane, base), check=False, capture=True)
    container_logs = (logs.stdout or "") + (logs.stderr or "")
    (iter_dir / "container-logs.txt").write_text(container_logs, encoding="utf-8")
    (iter_dir / "curio-messages.txt").write_text(read_from(messages, offset), encoding="utf-8")
    prune_comparisons(iter_dir / "comparisons", iter_dir / "junit.xml")

    part = part_of(cfg, lane, iteration)
    (iter_dir / "run.json").write_text(json.dumps({
        "lane": lane.g, "iteration": iteration, "part": part, "returncode": proc.returncode,
        "seconds": seconds, "began": int(began),
        "thread_exhaustion": container_logs.count(THREAD_EXHAUSTION),
    }, indent=2), encoding="utf-8")
    write_harness(iter_dir / "harness.xml",
                  run_checks(cfg, iteration, iter_dir / "junit.xml", proc.returncode, ended))
    print(f"[{lane.name}] iteration {iteration}{f' part {part}' if part else ''}: "
          f"exit {proc.returncode} after {seconds:.0f}s{' (time limit)' if ended else ''}")


def stop(cfg: Config, base) -> None:
    pids = cfg.out / "samplers.pid"
    if pids.is_file():
        for pid in pids.read_text(encoding="utf-8").split():
            try:
                os.killpg(int(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, ValueError):
                pass
    for lane in lanes_for(cfg):
        if not lane.path.exists():
            continue
        cid = container(lane, base)
        if cid:
            killed = inspect(cid, "{{.State.OOMKilled}}") == "true"
            write_harness(cfg.out / lane.name / "harness-stop.xml", [(
                "stack_not_oom_killed", f"the OOM killer took {lane.project}'s container" if killed else "", "")])
        stack("down", lane.project, lane=lane, base=base, check=False)
        # The containers wrote into the worktree as root.
        sh(["docker", "run", "--rm", "-v", f"{lane.path}:/w", "-w", "/w", "alpine",
            "chown", "-R", f"{os.getuid()}:{os.getgid()}", "/w"], check=False)
        sh(["git", "-C", cfg.workspace, "worktree", "remove", "--force", lane.path], check=False)
        shutil.rmtree(lane.path, ignore_errors=True)
    sh(["git", "-C", cfg.workspace, "worktree", "prune"], check=False)


def sample_health(cfg: Config, base) -> None:
    """How many lane stacks are healthy, every SAMPLE_S seconds.

    In epoch seconds: the arcade runners share one host clock, so
    ci_flakes.py can add the runners' counts up at each moment.
    """
    with (cfg.out / "health.csv").open("a", encoding="utf-8") as out:
        if out.tell() == 0:
            out.write("epoch,healthy,running\n")
        while True:
            shown = sh(["docker", "ps", "--format", '{{.Label "com.docker.compose.project"}}|{{.Status}}'],
                       check=False, capture=True).stdout.splitlines()
            lanes = [line for line in shown if line.startswith(PROJECT_PREFIX)]
            healthy = sum(1 for line in lanes if "(healthy)" in line)
            out.write(f"{int(time.time())},{healthy},{len(lanes)}\n")
            out.flush()
            time.sleep(SAMPLE_S)


def sample_stats(cfg: Config, base) -> None:
    """test-desktop-stress's docker-stats.log lines, each sample after a TIME line."""
    with (cfg.out / "docker-stats.log").open("a", encoding="utf-8") as out:
        while True:
            out.write(f"TIME|{int(time.time())}\n")
            out.write(sh(["docker", "stats", "--no-stream", "--format",
                          "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.PIDs}}"], check=False, capture=True).stdout)
            try:
                load = Path("/proc/loadavg").read_text().split()[:3]
                available = next(int(line.split()[1]) // 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                                 if line.startswith("MemAvailable:"))
                out.write(f"HOST|{'|'.join(load)}|{len(os.sched_getaffinity(0))}|{available}\n")
            except (OSError, StopIteration, AttributeError):
                pass
            out.flush()
            time.sleep(SAMPLE_S)


COMMANDS = {"start": start, "barrier": barrier, "run": run, "stop": stop,
            "_health": sample_health, "_stats": sample_stats}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args(argv)
    # The step log shows each lane's iterations as they end, not at exit.
    sys.stdout.reconfigure(line_buffering=True)
    COMMANDS[args.command](config_from_env(os.environ), dict(os.environ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
