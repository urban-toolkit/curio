#!/usr/bin/env python3
"""Fail a CI run in which some test ran in no job at all.

    python scripts/ci_never_run.py <downloaded ci-inputs-* artifacts dir> <job>...

Each job skips the tests it cannot run, and another job runs them: the
isolated stack boots without auth, the unit container has no checkout around
it, and so on. A test that every job skipped was checked nowhere, however
green the run looks. This reads every job's JUnit results, lists the tests no
job ran, and exits 1 for any that is not in KNOWN.

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
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

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


def _key(case) -> str:
    """One id per test across jobs.

    The GPU runner appends ``@<module>`` to each name, and a test run from the
    repository root rather than its suite's folder gets a longer class name.
    """
    classname = case.get("classname") or ""
    if classname.startswith("utk_curio.backend."):
        classname = classname[len("utk_curio.backend."):]
    return f"{classname}::{(case.get('name') or '').split('@')[0]}"


def outcomes(root: Path):
    """test id -> {"ran": set of jobs, "skipped": {job: reason}}."""
    seen = defaultdict(lambda: {"ran": set(), "skipped": {}})
    for junit in sorted(root.glob("ci-inputs-*/*.xml")):
        job = junit.parent.name[len("ci-inputs-"):]
        try:
            tree = ET.parse(junit)
        except ET.ParseError:
            continue
        for case in tree.getroot().iter("testcase"):
            entry = seen[_key(case)]
            skipped = case.find("skipped")
            if skipped is None:
                entry["ran"].add(job)
            else:
                lines = (skipped.get("message") or skipped.text or "").strip().splitlines()
                entry["skipped"][job] = lines[0][:200] if lines else ""
    return seen


def main(argv) -> int:
    if len(argv) < 2:
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
