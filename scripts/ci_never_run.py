#!/usr/bin/env python3
"""Fail a CI run in which some test ran in no job at all, or compare two runs.

    python scripts/ci_never_run.py <downloaded ci-inputs-* artifacts dir> <job>...
    python scripts/ci_never_run.py --compare <before dir> <after dir>

Each job skips the tests it cannot run, and another job runs them: the
isolated stack boots without auth, the unit container has no checkout around
it, and so on. A test that every job skipped was checked nowhere, however
green the run looks. This reads every job's results (JUnit, and Jest's JSON),
lists the tests no job ran, and exits 1 for any that is not in KNOWN.

KNOWN holds the tests that still run nowhere, each under the reason it gives.
Make one run and delete its line; never add a line.

A skip that depends on the world outside the run (RUNTIME: a portal or PyPI
being reachable, a browser getting a WebGPU adapter, a sandbox already holding
a library) is reported but does not fail: those tests are written to skip
rather than fail for exactly that.

The check needs every job's results: a job that sent none would make every
test only it runs look unrun. So each <job> named on the command line must
have its ci-inputs-<job> results, or nothing is checked (a re-mint run, a
scheduled run, or a job that died before uploading).

--compare reads two runs' downloaded ci-inputs-* folders (main's run and a
PR's run, say; issue-audit/backlog-triage-v15/fetch_run.sh downloads one) and
lists, test by test, what differs between them:

1. tests that ran in one run and not the other;
2. tests whose outcome changed (passed, failed, error, skipped, xfail);
3. tests skipped in both runs, for a different reason;
4. e2e tests that moved between the GPU job (test-gpu) and a CPU job
   (e2e-desktop-*).

The parts of a split suite count as one job, so a test that moved from
e2e-desktop-3 to e2e-desktop-11, or from unit-backend-1 to unit-backend-4, is
no difference. Only each job's first run is read, not the .runN files of a
`repeat` dispatch. No RUNTIME reason excuses a difference here: a test that
passed in one run and skipped in the other is listed, whatever the reason.
It exits 1 when any list has an entry.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utk_curio.backend.tests.parts import case_key  # noqa: E402

_E2E = "tests.test_frontend."
KNOWN = {
    # Recordings and the browser stress tier: CURIO_STRESS=1.
    *(f"{_E2E}test_stress_tour_video.TestCurioStressTour::test_chapter_{chapter}[chromium]"
      for chapter in ("access", "agents", "canvas", "data", "nodes", "views")),
    f"{_E2E}test_user_stress_video.TestSessionAbuse::test_abuse[chromium]",
    f"{_E2E}test_user_stress_video.TestSessionExtending::test_extending[chromium]",
    f"{_E2E}test_user_stress_video.TestSessionFirstHour::test_first_hour[chromium]",
    f"{_E2E}test_user_stress_video.TestSessionMapsAndInteraction::test_maps_and_interaction[chromium]",
    f"{_E2E}test_user_stress_video.TestSessionRealData::test_real_data[chromium]",
    f"{_E2E}test_stress_browser.TestBrowserStressTier::test_concurrent_autark_users[chromium]",
    # The feature tour (CURIO_TOUR=1) and the screenshot gallery (CURIO_UI_GALLERY=1).
    f"{_E2E}test_feature_tour_video::test_record_feature_tour[chromium]",
    f"{_E2E}test_ui_surface_gallery::test_gallery_canvas_and_drawers[chromium]",
    f"{_E2E}test_ui_surface_gallery::test_gallery_modals[chromium]",
    f"{_E2E}test_ui_surface_gallery::test_gallery_pages[chromium]",
    # A stack started with --no-project (CURIO_NO_PROJECT=1).
    f"{_E2E}test_no_project_menu::test_file_menu_has_no_orphan_divider_in_no_project_mode[chromium]",
    f"{_E2E}test_no_project_menu::test_file_menu_hides_project_entries_in_no_project_mode[chromium]",
    # A platform without fork isolation, and Windows.
    "utk_curio.sandbox.tests.test_isolation_fallback.TestExecStillWorksWhenIsolationIsUnavailable"
    "::test_requesting_fork_on_an_unsupported_platform_still_runs_the_node",
    "utk_curio.sandbox.tests.test_isolation_hardening.TestWindowsIsANoop::test_harden_reports_that_it_skipped",
    # Mapillary's live answers, with CURIO_MAPILLARY_TOKEN.
    "tests.test_discovery.test_provider_contracts::test_a_mapillary_search_still_carries_what_the_rows_read",
}

#: Skip reasons that depend on the world outside the run, by the words of the
#: skips that give them.
RUNTIME = re.compile("|".join((
    # test_provider_contracts: a portal down, refusing, or with nothing today.
    r"\bunreachable\b", r"\banswered \d{3}\b", r"did not answer", r"did not report success",
    r"\btoday\b", r"\bthis time\b", r"exceeded \d+ bytes",
    # Installs that need PyPI, and controls a warm sandbox or store cannot arm.
    r"no PyPI access", r"already importable", r"already in this user's store",
    # A browser without a WebGPU adapter, a probe or a layout that missed.
    r"WebGPU adapter", r"could not probe", r"resolves to an edge",
)), re.IGNORECASE)

#: A later run of a repeated suite (scripts/ci_repeat.sh): e2e.run2.xml, jest.run3.json.
REPEAT_RUN = re.compile(r"\.run\d+$")

#: Outcomes from best to worst. A test written twice in one job (a failure,
#: then an error in teardown) keeps the worse.
RANK = {"passed": 0, "xfail": 1, "skipped": 2, "error": 3, "failed": 4}

#: Jest's statuses that are not a pass or a failure.
JEST_PASSED = {"passed", "focused"}


def _key(case) -> str:
    """One id per test across jobs (parts.case_key)."""
    return case_key(case.get("classname") or "", case.get("name") or "")


def _junit_results(path: Path):
    """(test id, outcome, skip reason) for each test case in one JUnit file."""
    for case in ET.parse(path).getroot().iter("testcase"):
        reason = ""
        skipped = case.find("skipped")
        if case.find("failure") is not None:
            outcome = "failed"
        elif case.find("error") is not None:
            outcome = "error"
        elif skipped is not None:
            outcome = "xfail" if skipped.get("type") == "pytest.xfail" else "skipped"
            lines = (skipped.get("message") or skipped.text or "").strip().splitlines()
            reason = lines[0][:200] if lines else ""
        else:
            outcome = "passed"
        yield _key(case), outcome, reason


def _jest_results(path: Path):
    """The same for Jest's --json output, a test named by its file and titles.

    The file is named from the frontend's folder, since the checkout's root
    differs between GitHub-hosted and self-hosted runners.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    for result in data.get("testResults") or []:
        file = (result.get("name") or "").split("/urban-workflows/", 1)[-1]
        for assertion in result.get("assertionResults") or []:
            status = assertion.get("status") or ""
            title = " > ".join([*(assertion.get("ancestorTitles") or []), assertion.get("title") or ""])
            if status in JEST_PASSED:
                yield f"{file}::{title}", "passed", ""
            elif status == "failed":
                yield f"{file}::{title}", "failed", ""
            else:
                yield f"{file}::{title}", "skipped", status


def results(root: Path, first_run_only: bool = False):
    """(job, test id, outcome, skip reason) for every test in every job's results."""
    for path in sorted(root.glob("ci-inputs-*/*")):
        if first_run_only and REPEAT_RUN.search(path.stem):
            continue
        if path.suffix == ".xml":
            read = _junit_results
        elif path.suffix == ".json" and path.name.startswith("jest"):
            read = _jest_results
        else:
            continue
        try:
            rows = list(read(path))
        except (ET.ParseError, ValueError, OSError):
            continue
        job = path.parent.name[len("ci-inputs-"):]
        for test, outcome, reason in rows:
            yield job, test, outcome, reason


def outcomes(root: Path, first_run_only: bool = False):
    """test id -> {"ran": set of jobs, "skipped": {job: reason}, "outcome": {job: outcome}}.

    An xfail counts as skipped, under its reason.
    """
    seen = defaultdict(lambda: {"ran": set(), "skipped": {}, "outcome": {}})
    for job, test, outcome, reason in results(root, first_run_only):
        entry = seen[test]
        if outcome in ("skipped", "xfail"):
            entry["skipped"][job] = reason
        else:
            entry["ran"].add(job)
        known = entry["outcome"].get(job)
        if known is None or RANK[outcome] > RANK[known]:
            entry["outcome"][job] = outcome
    return seen


def kind_of(job: str) -> str:
    """The job a part belongs to: every e2e job is "e2e", unit-backend-3 is "unit-backend"."""
    if job in ("test-gpu", "e2e-collab") or job.startswith("e2e-desktop-"):
        return "e2e"
    return re.sub(r"-\d+$", "", job)


def _by_kind(seen) -> dict:
    """(kind, test id) -> {"jobs", "outcome", "reason", "runners"} for one run."""
    table = {}
    for test, entry in seen.items():
        for job in sorted(entry["outcome"]):
            outcome = entry["outcome"][job]
            row = table.setdefault((kind_of(job), test),
                                   {"jobs": [], "outcome": outcome, "reason": "", "runners": set()})
            row["jobs"].append(job)
            if RANK[outcome] > RANK[row["outcome"]]:
                row["outcome"] = outcome
            if job in entry["skipped"] and not row["reason"]:
                row["reason"] = entry["skipped"][job]
            if kind_of(job) == "e2e":
                row["runners"].add("GPU" if job == "test-gpu" else "CPU")
    return table


def compare(before: Path, after: Path) -> dict:
    """What differs between two runs' results, test by test (see the module doc)."""
    old = _by_kind(outcomes(before, first_run_only=True))
    new = _by_kind(outcomes(after, first_run_only=True))
    both = sorted(set(old) & set(new))
    old_kinds, new_kinds = {kind for kind, _ in old}, {kind for kind, _ in new}
    return {
        "only_before": sorted((key, old[key]["outcome"]) for key in set(old) - set(new)),
        "only_after": sorted((key, new[key]["outcome"]) for key in set(new) - set(old)),
        "outcome": [(key, old[key]["outcome"], new[key]["outcome"], old[key]["reason"] or new[key]["reason"])
                    for key in both if old[key]["outcome"] != new[key]["outcome"]],
        "reason": [(key, old[key]["reason"], new[key]["reason"]) for key in both
                   if old[key]["outcome"] == new[key]["outcome"] and old[key]["reason"] != new[key]["reason"]],
        "moved": [(key[1], old[key]["runners"], new[key]["runners"]) for key in both
                  if key[0] == "e2e" and old[key]["runners"] != new[key]["runners"]],
        # Not one of the four lists, but what explains them: a job with no
        # results in one run, and a test one run ran in two parts of a job.
        "no_results": [("before", kind) for kind in sorted(new_kinds - old_kinds)]
                      + [("after", kind) for kind in sorted(old_kinds - new_kinds)],
        "twice": [(run, key, table[key]["jobs"]) for run, table in (("before", old), ("after", new))
                  for key in sorted(table) if len(table[key]["jobs"]) > 1],
        "counts": (len(old), len(new)),
    }


def _runners(runners) -> str:
    return " and ".join(sorted(runners)) or "nowhere"


def print_comparison(before: Path, after: Path) -> int:
    found = compare(before, after)
    print(f"before: {before} ({found['counts'][0]} tests by job)")
    print(f"after:  {after} ({found['counts'][1]} tests by job)")
    for run, kind in found["no_results"]:
        print(f"::warning::no {kind} results in the {run} run: its tests show as in one run only")
    only = [("before", key, outcome) for key, outcome in found["only_before"]]
    only += [("after", key, outcome) for key, outcome in found["only_after"]]
    print(f"\n1. In one run only: {len(only)}")
    for run, (kind, test), outcome in only:
        print(f"   only {run:<6} [{kind}] {test} ({outcome})")
    print(f"\n2. Outcome changed: {len(found['outcome'])}")
    for (kind, test), was, now, reason in found["outcome"]:
        print(f"   [{kind}] {test}: {was} -> {now}" + (f" ({reason})" if reason else ""))
    print(f"\n3. Skip reason changed: {len(found['reason'])}")
    for (kind, test), was, now in found["reason"]:
        print(f"   [{kind}] {test}\n      before: {was}\n      after:  {now}")
    print(f"\n4. Moved between the GPU job and a CPU job: {len(found['moved'])}")
    for test, was, now in found["moved"]:
        print(f"   {test}: {_runners(was)} -> {_runners(now)}")
    if found["twice"]:
        print(f"\nAlso: {len(found['twice'])} test(s) ran in more than one part of a job")
        for run, (kind, test), jobs in found["twice"]:
            print(f"   {run}: [{kind}] {test} in {', '.join(jobs)}")
    differences = len(only) + len(found["outcome"]) + len(found["reason"]) + len(found["moved"])
    if differences or found["twice"] or found["no_results"]:
        print(f"\n{differences} difference(s)")
        return 1
    print("\nSame tests in both runs, with the same outcomes, skip reasons and runners.")
    return 0


def main(argv) -> int:
    if len(argv) == 3 and argv[0] == "--compare":
        return print_comparison(Path(argv[1]), Path(argv[2]))
    if len(argv) < 2 or argv[0].startswith("--"):
        print(__doc__, file=sys.stderr)
        return 2
    root, jobs = Path(argv[0]), argv[1:]
    missing = [job for job in jobs if not any((root / f"ci-inputs-{job}").glob("*.xml"))]
    if missing:
        print(f"not checked: no results from {', '.join(missing)}")
        return 0

    never = {
        test: entry["skipped"]
        for test, entry in outcomes(root).items()
        if entry["skipped"] and not entry["ran"]
    }
    unknown = sorted(
        test for test, reasons in never.items()
        if test not in KNOWN and not any(RUNTIME.search(r) for r in reasons.values())
    )
    for test in sorted(never):
        reason = next(iter(never[test].values()))
        level = "error" if test in unknown else "notice"
        print(f"::{level}::ran in no job: {test} ({reason})")
    stale = sorted(KNOWN - set(never))
    if stale:
        print(f"{len(stale)} test(s) in KNOWN now run or are gone; delete their lines:")
        for test in stale:
            print(f"  {test}")
    if unknown:
        print(f"{len(unknown)} test(s) ran in no job. Make each one run in a job "
              "that can run it, or delete it.")
        return 1
    print(f"OK: every test ran in some job, except {len(never)} known or skipped for a runtime reason")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
