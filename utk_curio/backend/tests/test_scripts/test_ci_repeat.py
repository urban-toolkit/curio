"""Running a CI test command several times, to find flaky tests.

``scripts/ci_repeat.sh`` wraps the test command of every job the Full stack
build's ``repeat`` input repeats. One run must write exactly the file names the
CI report reads, every later run its own, and a failed run must neither stop
the rest nor hide that the step failed.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "ci_repeat.sh"


def _repeat(tmp_path, runs, *command, addopts=None):
    env = {**os.environ, "CURIO_CI_REPEAT": str(runs)}
    env.pop("PYTEST_ADDOPTS", None)
    if addopts is not None:
        env["PYTEST_ADDOPTS"] = addopts
    return subprocess.run(["bash", str(SCRIPT), *command], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=60)


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


def test_a_single_failed_run_fails_the_step(tmp_path):
    assert _repeat(tmp_path, 1, "false").returncode == 1


def test_a_repeat_that_is_not_a_positive_number_is_refused(tmp_path):
    for runs in ("0", "two", "-1"):
        result = _repeat(tmp_path, runs, "touch", "ran")
        assert result.returncode == 2
        assert not (tmp_path / "ran").exists()
