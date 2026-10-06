"""Running a CI test command several times, to find flaky tests.

``scripts/ci_repeat.sh`` wraps the test command of every job the Full stack
build's ``repeat`` input repeats. One run must write exactly the file names the
CI report reads, every later run its own, a failed run must neither stop the
rest nor hide that the step failed, and with CURIO_CI_FRESH_STACK every run
after the first must start on a recreated stack.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "ci_repeat.sh"


#: Stands in for docker: logs every call, says the stack is healthy, and fails
#: `compose up` with FAKE_UP_EXIT.
FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$DOCKER_LOG"
case "$*" in
  *inspect*) echo healthy ;;
  *" ps "*) echo cid123 ;;
  *" up "*) exit "${FAKE_UP_EXIT:-0}" ;;
esac
"""


def _repeat(tmp_path, runs, *command, addopts=None, **env_extra):
    env = {**os.environ, "CURIO_CI_REPEAT": str(runs)}
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("CURIO_CI_FRESH_STACK", None)
    if addopts is not None:
        env["PYTEST_ADDOPTS"] = addopts
    env.update(env_extra)
    return subprocess.run(["bash", str(SCRIPT), *command], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=60)


def _fake_docker(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "DOCKER_LOG": str(tmp_path / "docker.log")}


def test_one_run_writes_the_names_the_report_reads(tmp_path):
    result = _repeat(tmp_path, 1, "touch", "e2e{run}.xml")
    assert result.returncode == 0, result.stderr
    assert [p.name for p in tmp_path.iterdir()] == ["e2e.xml"]
    assert "::group::" not in result.stdout


def test_each_later_run_writes_its_own_files(tmp_path):
    result = _repeat(tmp_path, 3, "touch", "e2e{run}.xml")
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["e2e.run2.xml", "e2e.run3.xml", "e2e.xml"]
    assert result.stdout.count("::group::Run ") == 3


def test_pytest_addopts_names_each_run_too(tmp_path):
    result = _repeat(tmp_path, 2, "sh", "-c", 'echo "$PYTEST_ADDOPTS" >> seen.txt',
                     addopts="--junitxml=out/e2e{run}.xml -k 'a and b'")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "seen.txt").read_text().splitlines() == [
        "--junitxml=out/e2e.xml -k 'a and b'", "--junitxml=out/e2e.run2.xml -k 'a and b'"]


def test_a_failed_run_does_not_stop_the_others_and_fails_the_step(tmp_path):
    # Fails in the first run only.
    result = _repeat(tmp_path, 3, "sh", "-c", "echo run >> runs.txt; [ -f failed-once ] || { touch failed-once; exit 1; }")
    assert result.returncode == 1
    assert len((tmp_path / "runs.txt").read_text().splitlines()) == 3
    assert "::error::1 of 3 runs failed" in result.stdout


def test_every_run_after_the_first_gets_a_recreated_stack(tmp_path):
    fake = _fake_docker(tmp_path)
    result = _repeat(tmp_path, 3, "sh", "-c", "echo run >> runs.txt", CURIO_CI_FRESH_STACK="curio-ci", **fake)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len((tmp_path / "runs.txt").read_text().splitlines()) == 3
    calls = (tmp_path / "docker.log").read_text().splitlines()
    assert calls.count("compose -p curio-ci up -d --force-recreate --no-build") == 2


def test_without_a_fresh_stack_the_stack_is_left_alone(tmp_path):
    fake = _fake_docker(tmp_path)
    assert _repeat(tmp_path, 2, "true", **fake).returncode == 0
    assert not (tmp_path / "docker.log").exists()


def test_a_stack_that_cannot_be_recreated_fails_that_run_without_running_it(tmp_path):
    fake = _fake_docker(tmp_path)
    result = _repeat(tmp_path, 3, "sh", "-c", "echo run >> runs.txt",
                     CURIO_CI_FRESH_STACK="curio-ci", FAKE_UP_EXIT="1", **fake)
    assert result.returncode == 1
    assert len((tmp_path / "runs.txt").read_text().splitlines()) == 1
    assert "::error::2 of 3 runs failed" in result.stdout


def test_a_single_failed_run_fails_the_step(tmp_path):
    assert _repeat(tmp_path, 1, "false").returncode == 1


def test_a_repeat_that_is_not_a_positive_number_is_refused(tmp_path):
    for runs in ("0", "two", "-1"):
        result = _repeat(tmp_path, runs, "touch", "ran")
        assert result.returncode == 2
        assert not (tmp_path / "ran").exists()
