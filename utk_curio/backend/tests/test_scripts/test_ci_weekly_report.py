"""The Weekly flake hunt's report on its own run page.

``scripts/ci_weekly_report.py`` runs in weekly-flake-hunt.yml after the hunt
dispatches the Full stack build with repeat 10. It must find the runs the hunt
started and no others, wait for them, put each run's summary on the page, and
turn the hunt red on a failed run or a flaky test. These feed it answers shaped
like the GitHub API's, and a summary ci_report.py itself writes.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


weekly = _load("ci_weekly_report")
ci_report = _load("ci_report")

SINCE = "2026-11-07T08:00:04Z"
URL = "https://github.com/o/r/actions/runs"


def _run(run_id, *, created="2026-11-07T08:00:09Z", login="github-actions[bot]", status="completed",
         conclusion="success"):
    return {"id": run_id, "created_at": created, "triggering_actor": {"login": login},
            "status": status, "conclusion": conclusion, "run_attempt": 1,
            "run_started_at": "2026-11-07T08:00:20Z", "updated_at": "2026-11-07T11:54:20Z",
            "html_url": f"{URL}/{run_id}"}


def _repeated_summary(tmp_path, flaky: bool) -> str:
    """A summary ci_report.py writes for a suite repeated three times."""
    def junit(failed):
        failure = '<failure message="flaked">trace</failure>' if failed else ""
        return ('<testsuites><testsuite name="pytest">'
                f'<testcase classname="tests.test_a" name="test_x">{failure}</testcase>'
                '</testsuite></testsuites>')
    for name, failed in (("e2e.xml", False), ("e2e.run2.xml", flaky), ("e2e.run3.xml", False)):
        (tmp_path / name).write_text(junit(failed), encoding="utf-8")
    summary = tmp_path / "summary.md"
    ci_report.main(["--junit", f"End-to-end tests={tmp_path / 'e2e.xml'}",
                    "--out", str(tmp_path / "page.html"), "--summary", str(summary)])
    return summary.read_text(encoding="utf-8")


def _zip(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("summary.md", text)
    return buffer.getvalue()


def _api(runs, summary):
    def fetch(path):
        if path.startswith("actions/workflows/"):
            return {"workflow_runs": runs}
        if "/jobs" in path:
            return {"jobs": [{"conclusion": "success"}] * 27 + [{"conclusion": "skipped"}]}
        if path.endswith("/artifacts?per_page=100"):
            return {"artifacts": [
                {"id": 7, "name": "ci-summary", "created_at": "2026-11-07T11:54:00Z"},
                {"id": 8, "name": "curio-ci-report.html", "created_at": "2026-11-07T11:54:01Z"},
            ]}
        run_id = int(path.rsplit("/", 1)[-1])
        return next(run for run in runs if run["id"] == run_id)
    return fetch, lambda path: _zip(summary)


def test_finds_only_the_runs_the_hunt_dispatched():
    runs = [_run(1, created="2026-11-07T07:10:00Z"),           # before the hunt
            _run(2, login="fabio-miranda"),                     # someone's own dispatch
            _run(3), _run(4, created="2026-11-07T08:01:00Z")]
    fetch, _ = _api(runs, "")
    assert [run["id"] for run in weekly.started_runs(fetch, SINCE)] == [3, 4]


def test_waits_until_every_run_ended():
    states = iter(["in_progress", "in_progress", "completed"])
    slept = []

    def fetch(path):
        return _run(3, status=next(states))
    runs = weekly.wait_for(fetch, [3], poll=300, deadline=10**9, sleep=slept.append, clock=lambda: 0)
    assert runs[0]["status"] == "completed"
    assert slept == [300, 300]


def test_stops_waiting_at_the_deadline():
    runs = weekly.wait_for(lambda path: _run(3, status="in_progress"), [3], poll=300, deadline=5,
                           sleep=lambda s: None, clock=lambda: 6)
    assert runs[0]["status"] == "in_progress"


def test_a_flaky_test_in_the_summary_ci_report_writes_is_seen(tmp_path):
    (tmp_path / "flaky").mkdir()
    (tmp_path / "steady").mkdir()
    assert weekly.FLAKY_HEADER in _repeated_summary(tmp_path / "flaky", flaky=True)
    assert weekly.FLAKY_HEADER not in _repeated_summary(tmp_path / "steady", flaky=False)


def test_the_page_lists_each_run_then_its_summary(tmp_path, monkeypatch):
    summary = _repeated_summary(tmp_path, flaky=True)
    fetch, fetch_bytes = _api([_run(3)], summary)
    section = weekly.run_section(fetch, fetch_bytes, _run(3))
    page = weekly.render([section], SINCE)
    assert f"| [3]({URL}/3) | 1 | success | 3.9 h | 27 success, 1 skipped | [page]({URL}/3/artifacts/8) |" in page
    assert "### Run 3" in page
    assert "| End-to-end tests | tests.test_a::test_x | 1, 3 | 2 |" in page
    assert section["flaky"] and section["passed"]


def test_the_week_is_red_on_a_flaky_test_or_a_failed_run(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_TOKEN", "t")
    out = tmp_path / "out.md"
    for runs, summary, code in (
        ([_run(3)], "| Suite | Result |", 0),
        ([_run(3)], _repeated_summary(tmp_path, flaky=True), 1),
        ([_run(3, conclusion="failure")], "| Suite | Result |", 1),
        ([], "", 1),
    ):
        fetch, fetch_bytes = _api(runs, summary)
        monkeypatch.setattr(weekly.Api, "json", lambda self, path, fetch=fetch: fetch(path))
        monkeypatch.setattr(weekly.Api, "bytes", lambda self, path, fb=fetch_bytes: fb(path))
        assert weekly.main(["--since", SINCE, "--out", str(out), "--poll", "0"],
                           sleep=lambda s: None) == code
    assert "No Full stack build run started by github-actions[bot]" in out.read_text(encoding="utf-8")
