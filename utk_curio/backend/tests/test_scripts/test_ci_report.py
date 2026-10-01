"""The CI report page: one HTML file that has to stand on its own.

``scripts/ci_report.py`` is what the ci-report job uploads as ``curio-ci-report.html``.
Every input is optional because a step that never ran leaves no file, and the
page is the first thing read when a run goes red, so a page that fails to build
on odd input is worse than no page. These build it from synthetic inputs.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses look their own module up while building a class.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ci_report = _load("ci_report")

FAILED_ID = ("tests/test_frontend/test_workflows.py::TestWorkflowCanvas::"
             "test_node_execution[Vega.json-chromium]@wf-Vega.json")

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="2" failures="1" skipped="2" tests="6" time="12.5">
<testcase classname="tests.test_frontend.test_workflows.TestWorkflowCanvas"
  name="test_node_execution[Vega.json-chromium]@wf-Vega.json" time="3.25">
  <failure message="AssertionError: &lt;script&gt;alert(1)&lt;/script&gt; #x1B[31mred#x1B[0m">trace line</failure>
</testcase>
<testcase classname="tests.test_frontend.test_workflows.TestWorkflowCanvas"
  name="test_node_execution[Vega.json-chromium]@wf-Vega.json" time="0.5">
  <error message="failed on teardown with &quot;boom&quot;">teardown trace</error>
</testcase>
<testcase classname="tests.test_frontend.test_a" name="test_passes" time="1.0"/>
<testcase classname="tests.test_frontend.test_a" name="test_skipped" time="0">
  <skipped type="pytest.skip" message="needs an owner">skip detail</skipped>
</testcase>
<testcase classname="tests.test_frontend.test_a" name="test_xfail" time="0">
  <skipped type="pytest.xfail" message="known"/>
</testcase>
<testcase classname="tests.test_frontend.test_b" name="test_crash" time="0">
  <error message="failed on setup with &quot;worker 'gw1' crashed while running 'x'&quot;"/>
</testcase>
</testsuite></testsuites>
"""

JEST = {
    "success": False,
    "startTime": 1000,
    "testResults": [
        {"name": "/src/utk_curio/frontend/urban-workflows/src/a.test.ts", "status": "failed",
         "endTime": 4000, "message": "", "assertionResults": [
             {"ancestorTitles": ["A"], "title": "works", "status": "passed", "duration": 5,
              "failureMessages": []},
             {"ancestorTitles": ["A"], "title": "breaks", "status": "failed", "duration": 7,
              "failureMessages": ["\u001b[31mExpected 1\u001b[39m\n    at Object.<anonymous>"]},
             {"ancestorTitles": [], "title": "later", "status": "todo", "duration": None,
              "failureMessages": []},
         ]},
        {"name": "/src/utk_curio/frontend/urban-workflows/src/b.test.ts", "status": "failed",
         "endTime": 5000, "assertionResults": [],
         "message": "\u001b[1m● Test suite failed to run\u001b[22m\n\nCannot find module './x'"},
    ],
}

TSC = """
> urban-workflows@0.0.0 typecheck
> tsc --noEmit --pretty false

src/a.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'.
  The expected type comes from property 'x'.
error TS5023: Unknown compiler option 'foo'.
"""

JOBS = {"jobs": [{
    "name": "test-gpu", "status": "in_progress",
    "html_url": "https://github.com/o/r/actions/runs/1/job/2",
    "steps": [
        {"name": "Set up job", "status": "completed", "conclusion": "success", "number": 1,
         "started_at": "2026-09-28T02:00:00Z", "completed_at": "2026-09-28T02:00:05Z"},
        {"name": "Run backend unit tests", "status": "completed", "conclusion": "failure",
         "number": 11, "started_at": "2026-09-28T02:01:00Z", "completed_at": "2026-09-28T02:04:10Z"},
        {"name": "Build the CI report page", "status": "in_progress", "conclusion": None,
         "number": 30},
    ],
}]}


def _png(path, color=(255, 255, 255), size=(8, 6)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def _comparison(root, folder, *, status, ratio, budget=0.2, nodeid="tests/x.py::test_y",
                images=("expected", "created", "diff"), baseline=None, **extra):
    out = root / folder
    out.mkdir(parents=True)
    for kind in images:
        _png(out / f"{kind}.png")
    record = {
        "nodeid": nodeid, "baseline": baseline or f"screenshot_{folder}.png", "status": status,
        "pixel_threshold": 30, "max_diff_ratio": budget, "ratio": ratio,
        "mismatched": None if ratio is None else int(ratio * 48), "total": 48,
        "max_delta": 200, "expected_size": [8, 6], "created_size": [8, 6], "compared_size": [8, 6],
        "capture": "full page", "error": None,
        "images": {kind: f"{kind}.png" for kind in images},
        **extra,
    }
    (out / "record.json").write_text(json.dumps(record), encoding="utf-8")


def _inputs(tmp_path):
    (tmp_path / "e2e.xml").write_text(JUNIT, encoding="utf-8")
    (tmp_path / "jest.json").write_text(json.dumps(JEST), encoding="utf-8")
    (tmp_path / "tsc.txt").write_text(TSC, encoding="utf-8")
    (tmp_path / "jobs.json").write_text(json.dumps(JOBS), encoding="utf-8")
    compare = tmp_path / "compare"
    _comparison(compare, "a_pass", status="passed", ratio=0.01)
    _comparison(compare, "b_near", status="passed", ratio=0.18)
    _comparison(compare, "c_over", status="failed", ratio=0.3, nodeid=FAILED_ID)
    _comparison(compare, "d_missing", status="missing", ratio=None, images=("created",))
    (compare / "e_half_written").mkdir()  # a run killed before record.json
    failures = tmp_path / "failures"
    _png(failures / ci_report.failure_folder(FAILED_ID) / "screenshot.png", color=(200, 0, 0))
    return compare, failures


def _build(tmp_path, *extra):
    compare, failures = _inputs(tmp_path)
    out = tmp_path / "report.html"
    summary = tmp_path / "summary.md"
    argv = [
        "--junit", f"End-to-end tests={tmp_path / 'e2e.xml'}",
        "--jest", f"Frontend unit tests={tmp_path / 'jest.json'}",
        "--tsc", f"TypeScript typecheck={tmp_path / 'tsc.txt'}",
        "--comparisons", str(compare), "--failures", str(failures),
        "--jobs", str(tmp_path / "jobs.json"), "--job-name", "test-gpu",
        "--out", str(out), "--summary", str(summary), *extra,
    ]
    assert ci_report.main(argv) == 0
    return out.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8")


def test_junit_counts_merge_the_teardown_duplicate(tmp_path):
    (tmp_path / "e2e.xml").write_text(JUNIT, encoding="utf-8")
    suite = ci_report.read_junit("e2e", str(tmp_path / "e2e.xml"))
    assert len(suite.cases) == 5
    assert (suite.count("passed"), suite.count("failed"), suite.count("error"),
            suite.count("skipped", "xfailed")) == (1, 1, 1, 2)
    failed = next(c for c in suite.cases if c.status == "failed")
    assert "boom" in failed.message and "trace line" in failed.details
    assert "#x1B" not in failed.message
    crash = next(c for c in suite.cases if c.status == "error")
    assert crash.kind == "crash"
    assert suite.seconds == 12.5


def test_jest_counts_and_a_suite_that_failed_to_run(tmp_path):
    (tmp_path / "jest.json").write_text(json.dumps(JEST), encoding="utf-8")
    suite = ci_report.read_jest("jest", str(tmp_path / "jest.json"))
    assert (suite.count("passed"), suite.count("failed"), suite.count("error"),
            suite.count("skipped")) == (1, 1, 1, 1)
    assert suite.seconds == 4.0
    names = [c.name for c in suite.cases]
    assert "src/a.test.ts > A > breaks" in names and "src/b.test.ts" in names
    assert all("\u001b" not in c.message + c.details for c in suite.cases)


def test_tsc_errors_and_a_clean_run(tmp_path):
    (tmp_path / "tsc.txt").write_text(TSC, encoding="utf-8")
    suite = ci_report.read_tsc("tsc", str(tmp_path / "tsc.txt"))
    assert [(e["file"], e["line"], e["code"]) for e in suite.tsc_errors] == [
        ("src/a.ts", "12", "TS2322"), (None, None, "TS5023")]
    assert "comes from property 'x'" in suite.tsc_errors[0]["message"]
    assert suite.status == "failed"

    clean = ("\n> x typecheck\n> tsc --noEmit\n\n"
             "npm notice New minor version of npm available! 11.1.0 -> 11.2.0\n")
    (tmp_path / "clean.txt").write_text(clean, encoding="utf-8")
    assert ci_report.read_tsc("tsc", str(tmp_path / "clean.txt")).status == "passed"

    (tmp_path / "odd.txt").write_text("> x typecheck\nnpm error Missing script\n", encoding="utf-8")
    odd = ci_report.read_tsc("tsc", str(tmp_path / "odd.txt"))
    assert odd.status == "unclear" and "Missing script" in odd.raw_tail


def test_the_page_is_self_contained(tmp_path):
    page, _ = _build(tmp_path)
    assert page.startswith("<!doctype html>")
    assert "<link" not in page and "<script src" not in page
    assert not re.search(r'(?:src|href)="(?!data:|#|https://github\.com/)', page)
    assert page.count('src="data:image/') == 3 * 3 + 1 + 1  # three full trios, one created, one screenshot


def test_failure_text_is_escaped(tmp_path):
    page, _ = _build(tmp_path)
    assert "<script>alert(1)" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_comparisons_are_ordered_over_missing_then_near_misses(tmp_path):
    page, _ = _build(tmp_path)
    order = [page.index(f"screenshot_{name}.png") for name in ("c_over", "d_missing", "b_near", "a_pass")]
    assert order == sorted(order)
    assert "e_half_written" not in page
    assert "30.00%</strong> of pixels differ by more than 30 per channel" in page
    assert "budget <strong>20.00%</strong>" in page


def test_a_failed_test_gets_its_screenshot_and_its_comparison_says_so(tmp_path):
    page, _ = _build(tmp_path)
    assert "Screenshot at the moment of failure" in page
    assert "without a matching test" not in page
    card = page[page.index('id="cmp-1"'):]
    assert "screenshot_c_over.png" in card[:card.index("</article>")]
    assert "test failed" in card[:card.index("</article>")]
    # ...and the failed test links back to that card.
    assert '<a href="#cmp-1">screenshot_c_over.png</a> (over budget)' in page


def test_the_steps_come_from_the_jobs_api(tmp_path):
    page, _ = _build(tmp_path)
    assert "https://github.com/o/r/actions/runs/1/job/2#step:11:1" in page
    assert "1 of 2 completed steps failed" in page
    assert "Build the CI report page" not in page  # still running when the page was built


def test_the_summary_table(tmp_path):
    _, summary = _build(tmp_path)
    assert "| End-to-end tests | failed | 1 | 1 | 1 | 2 |" in summary
    assert "| TypeScript typecheck | failed | | 2 errors | | |" in summary
    assert "Screenshot comparisons: 4 recorded, 1 over budget, 1 without a baseline" in summary


def _card(page, baseline):
    at = page.index(f"<h3>{baseline}</h3>")
    return page[page.rindex("<article", 0, at):page.index("</article>", at)]


def _remint_page(tmp_path):
    compare = tmp_path / "compare"
    floor = {"remint_min_ratio": 0.0005}
    _comparison(compare, "r_small", status="reminted", ratio=0.02, remint_ratio=0.02,
                recapture_ratio=0.0, volatile_pixels=0, forced=True, **floor)
    _comparison(compare, "r_big", status="reminted", ratio=0.3, remint_ratio=0.25,
                recapture_ratio=0.0, volatile_pixels=3, **floor)
    _comparison(compare, "r_moved", status="reminted", ratio=0.05, remint_ratio=0.05,
                recapture_ratio=0.004, volatile_pixels=0, **floor)
    _comparison(compare, "u_kept", status="unchanged", ratio=0.001, remint_ratio=0.0002,
                volatile_pixels=2, **floor)
    out, summary = tmp_path / "report.html", tmp_path / "summary.md"
    assert ci_report.main(["--comparisons", str(compare), "--out", str(out),
                           "--summary", str(summary)]) == 0
    return out.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8")


def test_a_remint_run_shows_what_replaced_each_baseline_biggest_change_first(tmp_path):
    page, summary = _remint_page(tmp_path)
    order = [page.index(f"<h3>screenshot_{name}.png</h3>") for name in ("r_big", "r_moved", "r_small")]
    assert order == sorted(order)
    assert "A re-mint run: 3 baselines were replaced by what this run captured and 1 were kept" in page
    assert "more than 0.05% of its pixels changed" in page
    assert "<figcaption>Committed baseline</figcaption>" in page
    assert "<figcaption>Re-minted</figcaption>" in page
    # The re-mint never fails the page; the budget and recapture facts are flags.
    assert ci_report.overall(ci_report.build(ci_report.parse_args([
        "--comparisons", str(tmp_path / "compare"), "--out", "x"]))) == "passed"
    assert "over the budget until committed" in _card(page, "screenshot_r_big.png")
    assert "over the budget" not in _card(page, "screenshot_r_small.png")
    assert "moved on recapture" in _card(page, "screenshot_r_moved.png")
    assert "moved on recapture" not in _card(page, "screenshot_r_small.png")
    assert "swatch volatile" in page
    # A frame named by --remint-force says so.
    assert "requested" in _card(page, "screenshot_r_small.png")
    assert "requested" not in _card(page, "screenshot_r_big.png")
    assert "1 of them were requested by name" in page
    assert summary.rstrip().endswith("Re-mint: 3 baselines replaced, 1 kept.")


def test_a_minted_baseline_has_its_own_group_ahead_of_the_passes(tmp_path):
    compare = tmp_path / "compare"
    _comparison(compare, "a_pass", status="passed", ratio=0.0)
    _comparison(compare, "z_new", status="minted", ratio=0.0)
    out, summary = tmp_path / "report.html", tmp_path / "summary.md"
    assert ci_report.main(["--comparisons", str(compare), "--out", str(out),
                           "--summary", str(summary)]) == 0
    page = out.read_text(encoding="utf-8")
    assert page.index("<h3>screenshot_z_new.png</h3>") < page.index("<h3>screenshot_a_pass.png</h3>")
    card = _card(page, "screenshot_z_new.png")
    assert 'data-group="minted"' in card
    assert "<figcaption>New baseline</figcaption>" in card
    assert "<figcaption>Captured again</figcaption>" in card
    assert 'data-group="minted" aria-pressed="false">Minted <span class="num">1</span>' in page
    assert "1 baselines did not exist, so this run wrote them" in page
    assert "A re-mint run" not in page
    assert summary.read_text(encoding="utf-8").rstrip().endswith("Minted: 1 new baselines.")


def test_close_ups_get_a_badge_and_a_filter_across_the_groups(tmp_path):
    compare = tmp_path / "compare"
    _comparison(compare, "full", status="passed", ratio=0.0)
    _comparison(compare, "near", status="passed", ratio=0.01, closeup=True)
    _comparison(compare, "new", status="minted", ratio=0.0, closeup=True)
    out = tmp_path / "report.html"
    assert ci_report.main(["--comparisons", str(compare), "--out", str(out)]) == 0
    page = out.read_text(encoding="utf-8")
    assert 'data-group="closeup" aria-pressed="false">Close-ups <span class="num">2</span>' in page
    for name in ("near", "new"):
        card = _card(page, f"screenshot_{name}.png")
        assert "close-up" in card and 'data-closeup="1"' in card
    full = _card(page, "screenshot_full.png")
    assert "close-up" not in full and 'data-closeup=""' in full
    assert "card.dataset.closeup === '1'" in page


def _interaction(step, phase, role):
    return {"workflow": "Interaction_Vega_Autark.json", "step": step, "gesture": "hover",
            "phase": phase, "role": role, "node": f"{role}-node",
            "source": "source-node", "target": "target-node"}


def test_interaction_frames_pair_up_before_and_after_with_what_changed(tmp_path):
    compare = tmp_path / "compare"
    for phase in ("before", "after"):
        for role in ("source", "target"):
            _comparison(compare, f"hover_{phase}_{role}", status="minted", ratio=0.0,
                        interaction=_interaction("bar-hover", phase, role))
    # The target lit up: 12 of its 48 pixels are red after the hover.
    after = Image.new("RGB", (8, 6), (255, 255, 255))
    after.paste((255, 0, 0), (0, 0, 4, 3))
    after.save(compare / "hover_after_target" / "expected.png")
    # A kept baseline still shows in its pair, which the cards leave out.
    _comparison(compare, "pick_before_source", status="unchanged", ratio=0.0,
                interaction=_interaction("map-pick", "before", "source"))
    out, summary = tmp_path / "report.html", tmp_path / "summary.md"
    assert ci_report.main(["--comparisons", str(compare), "--out", str(out),
                           "--summary", str(summary)]) == 0
    page = out.read_text(encoding="utf-8")

    assert '<a href="#interactions">Interaction pairs (2)</a>' in page
    section = page[page.index('<section id="interactions">'):page.index('<section id="comparisons">')]
    hover = section[section.index("Interaction_Vega_Autark.json: bar-hover"):
                    section.index("Interaction_Vega_Autark.json: map-pick")]
    source = hover[hover.index("Source <code>source-node</code>"):hover.index("Target <code>target-node</code>")]
    target = hover[hover.index("Target <code>target-node</code>"):]
    assert "What changed: 0 pixels (0.00%)" in source
    assert "What changed: 12 pixels (25.00%)" in target
    assert target.count('src="data:image/') == 3
    pick = section[section.index("Interaction_Vega_Autark.json: map-pick"):]
    assert pick.count('src="data:image/') == 1 and "not captured" in pick and "needs both frames" in pick
    assert "before unchanged" in pick

    assert 'data-group="interaction" aria-pressed="false">Interactions <span class="num">4</span>' in page
    card = _card(page, "screenshot_hover_before_target.png")
    assert "bar-hover, before" in card and 'data-interaction="1"' in card
    assert "card.dataset.interaction === '1'" in page
    assert "Interaction pairs: 2 steps." in summary.read_text(encoding="utf-8")


def test_a_run_without_interaction_frames_has_no_pairs_section(tmp_path):
    page, summary = _build(tmp_path)
    assert "Interaction pairs" not in page and "Interaction pairs" not in summary
    assert 'data-interaction=""' in page


def test_a_kept_baseline_is_listed_without_its_images(tmp_path):
    page, _ = _remint_page(tmp_path)
    kept = page[page.index('id="unchanged"'):]
    assert "1 baselines kept as committed" in kept
    assert "screenshot_u_kept.png" in kept and "0.02%" in kept
    assert "<h3>screenshot_u_kept.png</h3>" not in page
    assert page.count('src="data:image/') == 3 * 3  # the three re-minted trios only


def test_the_image_budget_leaves_images_out_instead_of_growing_the_page(tmp_path):
    page, _ = _build(tmp_path, "--max-image-mb", "0")
    assert 'src="data:image/' not in page
    assert "image budget" in page


def test_missing_inputs_still_make_a_page(tmp_path):
    out = tmp_path / "report.html"
    assert ci_report.main([
        "--junit", f"Backend unit tests={tmp_path / 'nope.xml'}",
        "--jest", f"Frontend unit tests={tmp_path / 'nope.json'}",
        "--comparisons", str(tmp_path / "nope"), "--failures", str(tmp_path / "nope"),
        "--jobs", str(tmp_path / "nope.json"), "--out", str(out),
    ]) == 0
    page = out.read_text(encoding="utf-8")
    assert page.count("did not run") >= 2
    assert "No comparisons were recorded" in page


def test_an_unreadable_input_is_shown_not_fatal(tmp_path):
    (tmp_path / "broken.xml").write_text("<testsuites><testcase", encoding="utf-8")
    out = tmp_path / "report.html"
    assert ci_report.main(["--junit", f"Backend unit tests={tmp_path / 'broken.xml'}",
                           "--out", str(out)]) == 0
    assert "unreadable" in out.read_text(encoding="utf-8")


def test_a_failure_folder_is_found_from_its_junit_name():
    classname, name = ci_report.junit_key(FAILED_ID)
    assert (classname, name) == ("tests.test_frontend.test_workflows.TestWorkflowCanvas",
                                 "test_node_execution[Vega.json-chromium]@wf-Vega.json")
    folders = [ci_report.failure_folder(n) for n in ci_report.candidate_nodeids(classname, name)]
    # diagnostics.failure_dir names the folder from the real node id.
    assert ci_report.failure_folder(FAILED_ID) in folders


RUN_JOBS = {"jobs": [
    {"name": "test-gpu", "status": "completed", "conclusion": "success",
     "html_url": "https://github.com/o/r/actions/runs/1/job/2",
     "started_at": "2026-09-30T12:00:00Z", "completed_at": "2026-09-30T12:08:00Z",
     "steps": [{"name": "Run e2e tests", "status": "completed", "conclusion": "success",
                "number": 9}]},
    {"name": "e2e-desktop (3)", "status": "completed", "conclusion": "failure",
     "html_url": "https://github.com/o/r/actions/runs/1/job/3",
     "started_at": "2026-09-30T12:02:00Z", "completed_at": "2026-09-30T12:11:00Z",
     "steps": [{"name": "Run this part of the e2e tests", "status": "completed",
                "conclusion": "failure", "number": 7}]},
    {"name": "ci-report", "status": "in_progress", "steps": []},
]}


def test_a_run_wide_page_lists_every_job_and_what_failed_in_each(tmp_path):
    (tmp_path / "jobs.json").write_text(json.dumps(RUN_JOBS), encoding="utf-8")
    out = tmp_path / "report.html"
    assert ci_report.main(["--jobs", str(tmp_path / "jobs.json"), "--all-jobs",
                           "--out", str(out)]) == 0
    page = out.read_text(encoding="utf-8")
    assert "<h2>Jobs</h2>" in page
    assert "1 of 2 jobs failed" in page  # the page's own job is still running
    assert "e2e-desktop (3)" in page and "Run this part of the e2e tests" in page
    assert "job/3#step:7:1" in page
    # A failed job fails the run even with no test suite to say so.
    assert ci_report.overall(ci_report.build(ci_report.parse_args(
        ["--jobs", str(tmp_path / "jobs.json"), "--all-jobs", "--out", str(out)]))) == "failed"
