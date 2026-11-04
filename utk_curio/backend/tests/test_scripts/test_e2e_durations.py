"""Timing the e2e tests from CI's JUnit, for balancing the parts.

``scripts/e2e_durations.py`` has to name a test exactly as the split names a
collected item (``parts.item_key``), or the balancer prices that test at the
median. The names below are copied from the e2e JUnit of CI run 37090121928,
and the last test has pytest write the JUnit of a run itself, with and
without the GPU runner's xdist workers.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from utk_curio.backend.tests import parts

REPO_ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("_scripts_e2e_durations", REPO_ROOT / "scripts" / "e2e_durations.py")
durations = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = durations
spec.loader.exec_module(durations)


def test_a_worker_run_names_the_group_after_the_at_sign():
    """The GPU runner's xdist names the group after an ``@``; the key leaves it out."""
    assert durations.case_key(
        "tests.test_frontend.test_workflows.TestWorkflowCanvas",
        "test_node_positions[interaction-autark.json-chromium]@wf-interaction-autark.json",
    ) == "tests.test_frontend.test_workflows.TestWorkflowCanvas::test_node_positions[interaction-autark.json-chromium]"
    assert durations.case_key(
        "tests.test_frontend.test_examples", "test_each_example_has_markdown_walkthrough@test_examples",
    ) == "tests.test_frontend.test_examples::test_each_example_has_markdown_walkthrough"
    # An ``@`` inside the parameters is the test's own.
    assert durations.case_key(
        "tests.test_frontend.test_m", "test_drop[curio.scout@1-chromium]@test_m",
    ) == "tests.test_frontend.test_m::test_drop[curio.scout@1-chromium]"


def test_a_run_without_workers_rebuilds_the_group():
    """A desktop part runs without workers: the same test gets the same key there."""
    for classname, name in (
        ("tests.test_frontend.test_workflows.TestWorkflowCanvas", "test_node_execution[07-autark-gpu-shader.json-chromium]"),
        ("tests.test_frontend.test_walkthrough_baselines", "test_walkthrough_baseline[chromium-catalog-add-reports-success]"),
        ("tests.test_frontend.test_monitor_page_e2e", "test_monitor_page_shows_stats_errors_and_polls[chromium]"),
    ):
        group = {"test_workflows": "@wf-07-autark-gpu-shader.json",
                 "test_walkthrough_baselines": "@walk-catalog-add-reports-success"}.get(
                     classname.split(".")[2], "@" + classname.split(".")[2])
        assert durations.case_key(classname, name) == f"{classname}::{name}"
        assert durations.case_key(classname, name + group) == durations.case_key(classname, name)
    # A run from the repository root names the class from utk_curio.backend.
    assert durations.case_key(
        "utk_curio.backend.tests.test_frontend.test_monitor_page_e2e",
        "test_monitor_page_shows_stats_errors_and_polls[chromium]",
    ) == "tests.test_frontend.test_monitor_page_e2e::test_monitor_page_shows_stats_errors_and_polls[chromium]"


def test_a_group_keeps_its_longest_time_across_files(tmp_path, monkeypatch):
    """Each test keeps its longest time, and a repeated suite's later run is not read."""
    def junit(name, seconds):
        path = tmp_path / name
        path.write_text(
            '<testsuites><testsuite>'
            f'<testcase classname="tests.test_frontend.test_alive" name="test_a[chromium]" time="{seconds}"/>'
            f'<testcase classname="tests.test_frontend.test_alive" name="test_b[chromium]" time="{seconds}"/>'
            '</testsuite></testsuites>', encoding="utf-8")
        return str(path)

    out = tmp_path / "e2e_durations.json"
    monkeypatch.setattr(durations, "OUT", out)
    assert durations.main([junit("one.xml", 1.5), junit("two.xml", 4.0), junit("two.run2.xml", 9.0)]) == 0
    assert json.loads(out.read_text()) == {
        "tests.test_frontend.test_alive::test_a[chromium]": 4.0,
        "tests.test_frontend.test_alive::test_b[chromium]": 4.0,
    }


SUITE = '''
import pytest

@pytest.mark.parametrize("dataset", ["curio.scout@1", "plain"])
def test_alone(dataset):
    pass

@pytest.mark.xdist_group("together")
class TestShared:
    def test_first(self):
        pass

    @pytest.mark.parametrize("n", [1, 2])
    def test_second(self, n):
        pass
'''

KEYS = '''
import os

from utk_curio.backend.tests import parts


def pytest_collection_finish(session):
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    with open(os.path.join(os.environ["KEYS_DIR"], worker + ".txt"), "w", encoding="utf-8") as out:
        for item in session.items:
            out.write(parts.item_key(item) + "\\n")
'''


def test_a_collected_test_and_its_junit_case_get_one_key(tmp_path, monkeypatch):
    """The key the split prices a collected item by is the key this script
    writes for its JUnit test case, in a plain run (a desktop part) and under
    ``--dist loadgroup`` (the GPU runner, whose node ids carry ``@<group>``)."""
    suite = tmp_path / "suite"
    suite.mkdir()
    # Its own rootdir, as utk_curio/backend's pytest.ini is the suite's.
    (suite / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (suite / "test_mod.py").write_text(textwrap.dedent(SUITE), encoding="utf-8")
    (suite / "conftest.py").write_text(textwrap.dedent(KEYS), encoding="utf-8")
    for run, extra in (("plain", []), ("workers", ["-n", "2", "--dist", "loadgroup"])):
        keys_dir = tmp_path / f"keys-{run}"
        keys_dir.mkdir()
        junit = tmp_path / f"{run}.xml"
        done = subprocess.run(
            [sys.executable, "-m", "pytest", str(suite), "-q", "-p", "no:cacheprovider",
             f"--junitxml={junit}", *extra],
            cwd=suite, capture_output=True, text=True,
            # PYTEST_ADDOPTS cleared: CI's own --junitxml is not this run's.
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT), "KEYS_DIR": str(keys_dir),
                 "PYTEST_ADDOPTS": ""},
        )
        assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
        names = junit.read_text(encoding="utf-8")
        if run == "workers":
            assert "@together" in names, "the run had no xdist groups to leave out"
        collected = {line for path in keys_dir.glob("*.txt")
                     for line in path.read_text(encoding="utf-8").splitlines()}
        out = tmp_path / f"{run}.json"
        monkeypatch.setattr(durations, "OUT", out)
        assert durations.main([str(junit)]) == 0
        recorded = set(json.loads(out.read_text(encoding="utf-8")))
        assert len(recorded) == 5
        assert recorded == collected
        assert "test_mod::test_alone[curio.scout@1]" in recorded
        assert all(key == parts.case_key(*key.split("::", 1)) for key in recorded)
