"""The flake hunt's verdict, from every runner's lanes.

``scripts/ci_flakes.py`` reads the flake-lanes-<r> artifacts the hunt's lanes
jobs upload (scripts/ci_lanes.py) and decides which tests are flaky, which
fail every time, and whether the stacks asked for were really up at the same
moment. A verdict that misses a flaky test, or calls ten stacks at once when
they never overlapped, would make the hunt worthless, so these build the
artifacts by hand.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


flakes = _load("ci_flakes")
lanes = _load("ci_lanes")
ci_report = _load("ci_report")

MODULE = "tests.test_frontend.test_hunt"


def _junit(*cases):
    """JUnit as pytest writes it; each case is (name, status, message)."""
    body = []
    for name, status, message in cases:
        inner = ""
        if status == "failed":
            inner = f"<failure message={quoteattr(message)}>trace of {escape(name)}</failure>"
        elif status == "skipped":
            inner = '<skipped type="pytest.skip" message="skip"/>'
        body.append(f'<testcase classname="{MODULE}" name={quoteattr(name)} time="1.0">{inner}</testcase>')
    return f'<testsuites><testsuite name="pytest">{"".join(body)}</testsuite></testsuites>'


def _health(start, end, healthy):
    return [(t, healthy) for t in range(start, end, lanes.SAMPLE_S)]


def _runner(root, index, *, runners=2, stacks=5, iterations=2, name="", health=(), files=None):
    """One lanes job's artifact, as ci_lanes.py leaves it."""
    folder = root / f"flake-lanes-{index}"
    folder.mkdir(parents=True)
    total = runners * stacks
    info = {"runner": index, "runners": runners, "runner_name": name or f"arcade-cpu-{index:02d}",
            "stacks": stacks, "iterations": iterations, "suite": "e2e", "tests": "", "workflows": "",
            "image": "ghcr.io/urban-toolkit/curio-ci:abc",
            "lanes": [{"g": (index - 1) * stacks + k, "project": f"curio-lane-{k}", "healthy": True,
                       "parts": [f"{lanes.part_for((index - 1) * stacks + k, i, total)}/{total}"
                                 for i in range(1, iterations + 1)]}
                      for k in range(1, stacks + 1)]}
    (folder / "runner.json").write_text(json.dumps(info))
    (folder / "health.csv").write_text("epoch,healthy,running\n"
                                       + "".join(f"{t},{n},{n}\n" for t, n in health))
    for relative, text in (files or {}).items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return folder


def _together(root, files_1=None, files_2=None):
    """Two runners of five stacks each, all ten healthy over the same minutes."""
    _runner(root, 1, health=_health(1000, 1600, 5), files=files_1)
    _runner(root, 2, health=_health(1002, 1602, 5), files=files_2)


def test_a_test_that_passed_and_failed_is_flaky_and_one_that_never_passed_is_failing(tmp_path):
    _together(tmp_path, files_1={
        "lane-1/iter-1/junit.xml": _junit(("test_a", "passed", ""), ("test_b", "passed", ""), ("test_c", "failed", "boom")),
        "lane-2/iter-1/junit.xml": _junit(("test_a", "passed", ""), ("test_b", "failed", "AssertionError: late"),
                                          ("test_c", "failed", "boom")),
        "lane-1/iter-2/junit.xml": _junit(("test_a", "passed", ""), ("test_b", "passed", ""), ("test_c", "failed", "boom")),
    })
    hunt = flakes.collect(tmp_path)
    verdicts = {name.rsplit("::", 1)[-1]: test.verdict for name, test in hunt.tests.items()}
    assert verdicts == {"test_a": "passed", "test_b": "flaky", "test_c": "failing"}
    flaky = hunt.listed("flaky")[0]
    assert (flaky.failed, flaky.passed) == (1, 2)
    assert hunt.failed


def test_xdist_group_suffixes_count_as_one_test(tmp_path):
    _together(tmp_path, files_1={
        "lane-1/iter-1/junit.xml": _junit(("test_x[Vega.json]@wf-Vega.json", "passed", "")),
        "lane-2/iter-1/junit.xml": _junit(("test_x[Vega.json]", "failed", "no")),
    })
    hunt = flakes.collect(tmp_path)
    assert list(hunt.tests) == [f"{MODULE}::test_x[Vega.json]"]
    assert hunt.tests[f"{MODULE}::test_x[Vega.json]"].verdict == "flaky"


def test_a_failure_says_where_it_happened(tmp_path):
    _together(tmp_path, files_2={
        "lane-7/iter-1/junit.xml": _junit(("test_b", "passed", "")),
        "lane-7/iter-2/junit.xml": _junit(("test_b", "failed", "AssertionError: late\nmore lines")),
    })
    hunt = flakes.collect(tmp_path)
    attempt = hunt.listed("flaky")[0].failures()[0]
    assert (attempt.runner, attempt.lane, attempt.iteration) == (2, 7, 2)
    assert attempt.runner_name == "arcade-cpu-02"
    assert attempt.part == f"{lanes.part_for(7, 2, 10)}/10"
    summary = flakes.render_summary(hunt)
    assert "lane 7, iteration 2 (arcade-cpu-02)" in summary
    assert "AssertionError: late" in summary and "more lines" not in summary


def test_the_hunt_s_own_checks_fail_it(tmp_path):
    _together(tmp_path, files_1={
        "lane-3/harness-start.xml": lanes.harness_xml([("stack_becomes_healthy", "curio-lane-3 did not become healthy", "log")]),
        "lane-1/harness-start.xml": lanes.harness_xml([("stack_becomes_healthy", "", "")]),
        "lane-1/iter-1/harness.xml": lanes.harness_xml([("run_ends_in_time", "iteration 1 did not finish", "")]),
        "lane-1/iter-1/junit.xml": _junit(("test_a", "passed", "")),
    })
    hunt = flakes.collect(tmp_path)
    start = hunt.tests["flake_hunt::stack_becomes_healthy"]
    assert start.harness and (start.failed, start.passed) == (1, 1)
    assert hunt.tests["flake_hunt::run_ends_in_time"].verdict == "failing"
    assert not hunt.listed("flaky") and not hunt.listed("failing")
    assert hunt.failed
    summary = flakes.render_summary(hunt)
    assert "The hunt's own checks that failed" in summary
    assert "curio-lane-3 did not become healthy" in summary


def test_the_peak_adds_the_runners_up_at_the_same_moment(tmp_path):
    _together(tmp_path, files_1={"lane-1/iter-1/junit.xml": _junit(("test_a", "passed", ""))})
    hunt = flakes.collect(tmp_path)
    assert (hunt.requested, hunt.peak) == (10, 10)
    assert not hunt.failed
    assert flakes.render_summary(hunt).startswith("## Flake hunt\n\n**Passed.**")


def test_two_runners_whose_stacks_never_overlap_are_not_ten_at_once(tmp_path):
    passing = {"lane-1/iter-1/junit.xml": _junit(("test_a", "passed", ""))}
    _runner(tmp_path, 1, health=_health(1000, 1600, 5), files=passing)
    _runner(tmp_path, 2, health=_health(5000, 5600, 5))
    hunt = flakes.collect(tmp_path)
    assert (hunt.requested, hunt.peak) == (10, 5)
    assert hunt.failed
    assert "5 of 10 stacks were healthy at once" in flakes.headline(hunt)


def test_a_runner_that_left_no_results_fails_the_hunt(tmp_path):
    _runner(tmp_path, 1, stacks=10, runners=2, health=_health(1000, 1600, 10),
            files={"lane-1/iter-1/junit.xml": _junit(("test_a", "passed", ""))})
    hunt = flakes.collect(tmp_path, requested=10)
    assert hunt.peak == 10
    assert hunt.missing_runners == [2]
    assert hunt.failed


def test_a_hunt_in_which_no_test_ran_fails(tmp_path):
    _together(tmp_path, files_1={"lane-1/iter-1/junit.xml": _junit(("test_s", "skipped", ""))})
    hunt = flakes.collect(tmp_path)
    assert (hunt.peak, hunt.attempts) == (10, 0)
    assert hunt.failed
    assert flakes.headline(hunt).startswith("No test ran")


def test_skipped_attempts_are_not_counted_as_runs(tmp_path):
    _together(tmp_path, files_1={
        "lane-1/iter-1/junit.xml": _junit(("test_s", "skipped", "")),
        "lane-2/iter-1/junit.xml": _junit(("test_s", "passed", "")),
    })
    test = flakes.collect(tmp_path).tests[f"{MODULE}::test_s"]
    assert (test.ran, test.verdict) == (1, "passed")


def test_the_stats_peaks_are_read_from_the_sampler_log(tmp_path):
    log = tmp_path / "docker-stats.log"
    log.write_text("\n".join([
        "TIME|1000",
        "curio-lane-1-curio-1|120.5%|1.5GiB / 31.3GiB|400",
        "curio-lane-2-curio-1|80%|1536MiB / 31.3GiB|900",
        "HOST|210.5|190.0|150.2|192|20000",
        "TIME|1005",
        "curio-lane-1-curio-1|10%|512MiB / 31.3GiB|300",
        "HOST|12.0|50.0|90.0|192|30000",
    ]))
    assert flakes.read_stats(log) == {"peak_memory_gib": 3.0, "peak_pids": 900, "peak_load": 210.5, "cpus": 192}


def test_main_writes_the_page_the_summary_and_the_list_and_exits_1_on_a_flake(tmp_path):
    inputs = tmp_path / "inputs"
    nodeid = next(ci_report.candidate_nodeids(MODULE, "test_b"))
    shot = inputs / "flake-lanes-1" / "lane-2" / "iter-1" / "failures" / ci_report.failure_folder(nodeid) / "screenshot.png"
    _together(inputs, files_1={
        "lane-1/iter-1/junit.xml": _junit(("test_b", "passed", "")),
        "lane-2/iter-1/junit.xml": _junit(("test_b", "failed", "AssertionError: late")),
    })
    shot.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), "red").save(shot)
    page, summary, listed = tmp_path / "flake-report.html", tmp_path / "summary.md", tmp_path / "flakes.json"
    summary.write_text("earlier steps' summary\n")

    code = flakes.main([str(inputs), "--requested", "10", "--out", str(page), "--summary", str(summary),
                        "--json", str(listed), "--workers", "1"])

    assert code == 1
    html = page.read_text()
    assert f"{MODULE}::test_b" in html and "data:image/" in html
    assert summary.read_text().startswith("earlier steps' summary\n## Flake hunt")
    data = json.loads(listed.read_text())
    entry = next(t for t in data["tests"] if t["name"] == f"{MODULE}::test_b")
    assert (entry["verdict"], entry["passed"], entry["failed"]) == ("flaky", 1, 1)
    assert entry["failures"][0]["lane"] == 2 and data["peak"] == 10
