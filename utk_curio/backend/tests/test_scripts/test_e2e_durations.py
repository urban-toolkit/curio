"""Timing the e2e groups from CI's JUnit, for balancing the shards.

``scripts/e2e_durations.py`` has to name a test's group exactly as
``runner_split.group_of`` does, or the balancer prices that group at the
default. The names below are copied from the e2e JUnit of CI run 37090121928.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("_scripts_e2e_durations", REPO_ROOT / "scripts" / "e2e_durations.py")
durations = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = durations
spec.loader.exec_module(durations)


def test_a_worker_run_names_the_group_after_the_at_sign():
    assert durations.group_of(
        "tests.test_frontend.test_workflows.TestWorkflowCanvas",
        "test_node_positions[Interaction_Autark.json-chromium]@wf-Interaction_Autark.json",
    ) == "wf-Interaction_Autark.json"
    assert durations.group_of(
        "tests.test_frontend.test_examples", "test_each_example_has_markdown_walkthrough@test_examples",
    ) == "test_examples"


def test_a_run_without_workers_rebuilds_the_group():
    assert durations.group_of(
        "tests.test_frontend.test_workflows.TestWorkflowCanvas",
        "test_node_execution[07-autark-gpu-shader.json-chromium]",
    ) == "wf-07-autark-gpu-shader.json"
    assert durations.group_of(
        "tests.test_frontend.test_walkthrough_baselines",
        "test_walkthrough_baseline[chromium-catalog-add-reports-success]",
    ) == "walk-catalog-add-reports-success"
    assert durations.group_of(
        "tests.test_frontend.test_monitor_page_e2e", "test_monitor_page_shows_stats_errors_and_polls[chromium]",
    ) == "test_monitor_page_e2e"


def test_a_group_keeps_its_longest_time_across_files(tmp_path, monkeypatch):
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
    assert durations.main([junit("one.xml", 1.5), junit("two.xml", 4.0)]) == 0
    assert json.loads(out.read_text()) == {"test_alive": 8.0}
