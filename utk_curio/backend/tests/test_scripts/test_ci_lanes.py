"""Several Curio stacks on one runner, for the flake hunt.

``scripts/ci_lanes.py`` gives each stack on a runner (a lane) its own compose
project, host ports and worktree, and decides which part of the suite each
lane runs in each iteration. Two lanes on one port would make the hunt a
source of flakes of its own, and a part no lane runs would leave tests out, so
these pin the pure helpers. The docker and git side runs only in the
flake-hunt workflow.
"""
from __future__ import annotations

import importlib.util
import shlex
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lanes = _load("ci_lanes")
ci_report = _load("ci_report")

#: Every host port another stack can hold on a runner: prod, curio-dev,
#: curio-ci and its e2e shards, -iso, -exec-user, the zygote repro, the e2e
#: Autark repro and its shards, and the stress stack (the table in
#: docker-compose.ci-stress.yml).
TAKEN = {2000, 5002, 8080, 2010, 5012, 8090, 2020, 5022, 8100, *range(5023, 5030), *range(2021, 2028),
         2030, 5032, 8110, 2040, 5042, 8120, 2050, 5052, 8130, 2060, 5062, 8140,
         *range(5063, 5070), *range(2061, 2068), 2070, 5072, 8150}


def _cfg(**settings):
    env = {"GITHUB_WORKSPACE": "/w", "FLAKE_RUNNER": "1", "FLAKE_RUNNERS": "2", "FLAKE_STACKS": "5",
           "FLAKE_ITERATIONS": "3"}
    env.update({f"FLAKE_{name.upper()}": str(value) for name, value in settings.items()})
    return lanes.config_from_env(env)


def test_lanes_on_one_runner_have_their_own_ports_clear_of_every_other_stack():
    on_runner = lanes.lanes_for(_cfg(stacks=lanes.MAX_STACKS))
    ports = [port for lane in on_runner for port in (lane.backend, lane.sandbox, lane.frontend)]
    assert len(ports) == len(set(ports)) == 3 * lanes.MAX_STACKS
    assert not set(ports) & TAKEN
    assert len({lane.project for lane in on_runner}) == lanes.MAX_STACKS
    assert len({lane.path for lane in on_runner}) == lanes.MAX_STACKS
    assert all(lane.project.startswith("curio-lane-") for lane in on_runner)


def test_lane_numbers_count_every_stack_of_every_runner_once():
    numbers = [lane.g for runner in range(1, 4) for lane in lanes.lanes_for(_cfg(runner=runner, runners=3, stacks=4))]
    assert sorted(numbers) == list(range(1, 13))


def test_every_iteration_hands_each_part_to_exactly_one_lane():
    total = 10
    for iteration in range(1, 6):
        assert sorted(lanes.part_for(g, iteration, total) for g in range(1, total + 1)) == list(range(1, total + 1))


def test_a_lane_runs_a_new_part_every_iteration():
    total = 10
    for g in range(1, total + 1):
        parts = [lanes.part_for(g, iteration, total) for iteration in range(1, total + 1)]
        assert len(set(parts)) == total


def test_e2e_runs_as_e2e_desktop_runs_it_against_the_lane_s_own_stack(tmp_path):
    cfg = _cfg(runner=2)
    lane = lanes.lanes_for(cfg)[2]  # the third lane of runner 2: lane 8 of 10
    argv, env, junit = lanes.run_spec(cfg, lane, 2, tmp_path, {"PATH": "/bin"})
    assert argv == ["bash", "scripts/test.sh", "--e2e-only", "--use-existing"]
    assert junit == tmp_path / "junit.xml"
    assert env["CURIO_E2E_RUNNER"] == "desktop"
    assert env["CURIO_E2E_PART"] == f"{lanes.part_for(8, 2, 10)}/10"
    assert env["CURIO_E2E_BACKEND_PORT"] == str(lane.backend)
    assert env["CURIO_E2E_BACKEND_URL"] == f"http://localhost:{lane.backend}"
    assert env["CURIO_E2E_SANDBOX_PORT"] == env["FLASK_SANDBOX_PORT"] == str(lane.sandbox)
    assert env["CURIO_E2E_FRONTEND_PORT"] == str(lane.frontend)
    assert env["CURIO_E2E_FAILURE_DIR"] == str(tmp_path / "failures")
    assert env["CURIO_E2E_COMPARE_DIR"] == str(tmp_path / "comparisons")
    assert shlex.split(env["PYTEST_ADDOPTS"]) == [f"--junitxml={junit}"]
    assert env["COMPOSE_FILE"] == "docker-compose.yml:docker-compose.ci.yml"
    assert env["PATH"] == "/bin"


def test_a_filter_runs_the_same_tests_on_every_lane(tmp_path):
    cfg = _cfg(tests="test_node_execution and Vega", workflows="Vega.json")
    for lane in lanes.lanes_for(cfg):
        argv, env, _ = lanes.run_spec(cfg, lane, 1, tmp_path, {})
        assert "CURIO_E2E_PART" not in env
        assert shlex.split(env["PYTEST_ADDOPTS"])[1:] == ["-k", "test_node_execution and Vega"]
        assert argv[-3:] == ["--workflows", "Vega.json", "--allow-empty"]


def test_the_lane_s_environment_drops_what_would_point_at_another_stack(tmp_path):
    base = {"CURIO_STATE_DIR": "/shared/.curio", "BACKEND_PORT": "5002", "PYTEST_ADDOPTS": "-x",
            "CURIO_E2E_PART": "1/2", "CURIO_E2E_PARALLEL": "6", "HOME": "/home/runner"}
    lane = lanes.lanes_for(_cfg())[0]
    env = lanes.stack_env(lane, base)
    for name in ("CURIO_STATE_DIR", "BACKEND_PORT", "PYTEST_ADDOPTS", "CURIO_E2E_PART", "CURIO_E2E_PARALLEL"):
        assert name not in env
    assert env["HOME"] == "/home/runner"


def test_backend_runs_inside_the_lane_s_container_on_a_moving_unit_part(tmp_path):
    cfg = _cfg(suite="backend")
    lane = lanes.lanes_for(cfg)[0]
    argv, _, junit = lanes.run_spec(cfg, lane, 3, tmp_path, {})
    assert argv[:6] == ["docker", "compose", "-p", lane.project, "exec", "-T"]
    assert f"CURIO_UNIT_PART={lanes.part_for(1, 3, 10)}/10" in argv
    assert argv[-5:] == ["curio", "bash", "scripts/test.sh", "--backend-only", "--use-existing"]
    assert "PYTEST_ADDOPTS=--junitxml=/app/.curio/ci-report/flake-iter-3.xml" in argv
    assert junit == lane.path / ".curio" / "ci-report" / "flake-iter-3.xml"


def test_the_sandbox_suite_runs_whole_on_every_lane(tmp_path):
    cfg = _cfg(suite="sandbox")
    argv, _, _ = lanes.run_spec(cfg, lanes.lanes_for(cfg)[0], 1, tmp_path, {})
    assert not any(arg.startswith("CURIO_UNIT_PART=") for arg in argv)
    assert "--sandbox-only" in argv


@pytest.mark.parametrize("settings", [
    {"stacks": lanes.MAX_STACKS + 1},
    {"stacks": 0},
    {"suite": "jest"},
    {"runner": 3, "runners": 2},
    {"iterations": 0},
    {"suite": "backend", "workflows": "Vega.json"},
])
def test_settings_out_of_range_are_refused(settings):
    with pytest.raises(ValueError):
        _cfg(**settings)


def test_the_hunt_s_own_checks_read_back_as_junit(tmp_path):
    path = tmp_path / "harness.xml"
    path.write_text(lanes.harness_xml([("stack_becomes_healthy", "", ""),
                                       ("run_ends_in_time", "iteration 2 did not finish", "a <trace> & more")]))
    suite = ci_report.read_junit("harness", str(path))
    by_name = {case.name: case for case in suite.cases}
    assert by_name["flake_hunt::stack_becomes_healthy"].status == "passed"
    failed = by_name["flake_hunt::run_ends_in_time"]
    assert (failed.status, failed.message, failed.details) == ("failed", "iteration 2 did not finish",
                                                               "a <trace> & more")


def _checks(cfg, junit_text):
    junit = None
    if junit_text is not None:
        junit = Path(cfg.out) / "junit.xml"
        junit.parent.mkdir(parents=True, exist_ok=True)
        junit.write_text(junit_text)
    path = junit or Path(cfg.out) / "missing.xml"
    return {name: message for name, message, _ in lanes.run_checks(cfg, 2, path, 1, "")}


SKIPPED_ONLY = ('<testsuites><testsuite name="pytest"><testcase classname="tests.test_a" name="test_s">'
                '<skipped type="pytest.skip" message="no owner"/></testcase></testsuite></testsuites>')


def test_a_part_of_the_split_suite_that_ran_no_test_fails_its_check(tmp_path):
    checks = _checks(_cfg(out=tmp_path), SKIPPED_ONLY)
    assert checks["run_runs_tests"].startswith("iteration 2 ran no test")
    assert checks["run_writes_results"] == ""


def test_a_filter_may_select_nothing_on_a_lane(tmp_path):
    assert _checks(_cfg(out=tmp_path, tests="test_s"), SKIPPED_ONLY)["run_runs_tests"] == ""


def test_a_run_that_wrote_no_junit_fails_its_check(tmp_path):
    checks = _checks(_cfg(out=tmp_path), None)
    assert checks["run_writes_results"].startswith("iteration 2 wrote no JUnit (exit 1)")
    assert checks["run_runs_tests"] == ""


def test_the_barrier_counts_lanes_jobs_that_started_their_stacks_or_ended():
    def job(name, status, step_status=None):
        steps = [{"name": "▶️ Start the stacks", "status": step_status}] if step_status else []
        return {"name": name, "status": status, "steps": steps}

    jobs = [
        job("plan", "completed"),
        job("image", "completed"),
        job("lanes 1", "in_progress", "completed"),
        job("lanes 2", "in_progress", "in_progress"),
        job("lanes 3", "completed"),  # it ended before its stacks: nothing to wait for
        job("lanes 4", "queued"),
    ]
    assert lanes.started_lanes_jobs(jobs) == 2


def test_only_failed_tests_keep_their_screenshot_comparisons(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite name="pytest">'
        '<testcase classname="tests.test_frontend.test_a" name="test_fails[x]"><failure message="no"/></testcase>'
        '<testcase classname="tests.test_frontend.test_a" name="test_passes"/>'
        "</testsuite></testsuites>")
    root = tmp_path / "comparisons"
    for folder, nodeid in (("fails", "tests/test_frontend/test_a.py::test_fails[x]"),
                           ("passes", "tests/test_frontend/test_a.py::test_passes")):
        (root / folder).mkdir(parents=True)
        (root / folder / "record.json").write_text(f'{{"nodeid": "{nodeid}"}}')
    (root / "unrecorded").mkdir()
    lanes.prune_comparisons(root, junit)
    assert sorted(p.name for p in root.iterdir()) == ["fails", "unrecorded"]
