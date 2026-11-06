#!/usr/bin/env python3
"""The tests a filtered Full stack build selects, and the check that each one ran.

    python scripts/ci_selected_tests.py targets <suite>
    python scripts/ci_selected_tests.py split [--remint] [--remint-filter EXPR]
    python scripts/ci_selected_tests.py holding <listing>... [--job JOB]
    python scripts/ci_selected_tests.py check <ci-inputs dir> <listing>... [--remint-filter EXPR]

A run is filtered when it is a re-mint with a ``remint_filter`` (a pytest -k
expression), or when its ``tests`` dispatch input is set. ``tests`` (the
environment's CURIO_TESTS) is a space-separated list, from the repository root,
of pytest node ids or paths under a suite's folder, and Jest test files:

    utk_curio/backend/tests/test_suite_parts.py::PartsTest::test_a_part_is_k_of_n
    utk_curio/backend/tests/test_frontend/test_spa_deep_link_e2e.py
    utk_curio/sandbox/tests/test_codec.py
    utk_curio/frontend/urban-workflows/src/tests/ciParts.test.ts

A word belongs to the e2e suite under ``test_frontend/``, the backend unit
suite elsewhere under ``utk_curio/backend/tests``, the sandbox suite, or Jest.
A parametrized id with a space in it cannot be one word: name its function.

``targets`` prints the words of one suite, one a line, for scripts/test.sh
(Jest's from its frontend folder). ``split`` checks every word and prints which
suites hold one, as ``e2e=true`` lines for $GITHUB_OUTPUT; a re-mint takes no
``tests``, and its ``--remint-filter`` selects from the e2e suite. Every command
refuses a word that is in no suite's folder or names a path that is not there.

A listing is the JSON a collection with CURIO_LIST_PARTS writes
(utk_curio/backend/tests/parts.py): each CI job's selected tests, by the keys
scripts/ci_never_run.py reads results by. ``holding`` names the jobs that hold
a selected test, for the jobs and parts to start only when they do: the
listed ones, ``unit-sandbox`` for a sandbox word and ``jest`` for a Jest file,
as ``holding=,e2e-desktop-3,unit-backend-1,``; with ``--job``, whether that one
job holds any, as ``CURIO_CI_HOLDS=true`` for $GITHUB_ENV.

``check`` is what ci-report runs on a filtered run instead of
ci_never_run.py's whole-suite check, which cannot hold there (the jobs that
hold no selected test send no results). It fails the run when:

1. a job that holds a selected test sent no results;
2. a listed test ran in no job, or only skipped, unless ci_never_run.py's
   KNOWN names it or a job skipped it for a runtime reason;
3. a word of ``tests`` selects no test that ran;
4. a test in the results only skipped (ci_never_run.py's check, on what ran);
5. a ``remint_filter`` selected no test at all.

Without a listing (build-image's collection failed, so every part ran) it
checks 1 for sandbox and Jest, then 3 to 5 on what ran, and says so.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

E2E = "utk_curio/backend/tests/test_frontend"
BACKEND = "utk_curio/backend/tests"
SANDBOX = "utk_curio/sandbox/tests"
FRONTEND = "utk_curio/frontend/urban-workflows"
JEST = f"{FRONTEND}/src"
SUITES = ("e2e", "backend", "sandbox", "jest")
JEST_FILES = (".ts", ".tsx", ".js", ".jsx")

#: The jobs that run a suite in one job, by the suite, for its words.
WHOLE_SUITE_JOBS = {"sandbox": "unit-sandbox", "jest": "jest"}


class Refused(ValueError):
    """A word of ``tests`` that no suite runs."""


def _within(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + "/")


def suite_of(word: str, root: Path = REPO_ROOT) -> str:
    """The suite a word of ``tests`` is in, checked against the checkout at *root*."""
    path, sep, rest = word.partition("::")
    path = path.rstrip("/")
    parts = path.split("/")
    if not path or path.startswith("/") or "\\" in path or ".." in parts or "." in parts \
            or (sep and not rest):
        raise Refused(f"{word!r} is not a test id or path from the repository root")
    if _within(path, E2E):
        suite = "e2e"
    elif _within(path, BACKEND):
        suite = "backend"
    elif _within(path, SANDBOX):
        suite = "sandbox"
    elif _within(path, JEST) and path != JEST:
        suite = "jest"
    else:
        raise Refused(f"{word!r} is in no suite's folder ({BACKEND}, {SANDBOX}, or Jest files under {JEST})")
    if suite == "jest" and (sep or not path.endswith(JEST_FILES)):
        raise Refused(f"{word!r}: a Jest word is one test file")
    if sep and not path.endswith(".py"):
        raise Refused(f"{word!r}: a node id names a test file, then its tests")
    if not (root / path).exists():
        raise Refused(f"{word!r}: there is no {path} in this checkout")
    return suite


def by_suite(words, root: Path = REPO_ROOT) -> dict[str, list[str]]:
    """The words of each suite, in their order. Refuses the whole list for one bad word."""
    found = {suite: [] for suite in SUITES}
    for word in words:
        found[suite_of(word, root)].append(word)
    return found


def words_of(value: str | None) -> list[str]:
    """The words of a ``tests`` value; split on whitespace only, never globbed."""
    return (value or "").split()


def targets(suite: str, words, root: Path = REPO_ROOT) -> list[str]:
    """One suite's words: pytest's from the repository root, Jest's from its frontend folder."""
    if suite not in SUITES:
        raise Refused(f"no suite {suite!r}; one of {', '.join(SUITES)}")
    chosen = by_suite(words, root)[suite]
    if suite == "jest":
        return [word[len(FRONTEND) + 1:] for word in chosen]
    return chosen


def read_listings(paths) -> dict[str, list[str]] | None:
    """Every job's test keys across the listing files and folders, or None when there is none."""
    files = []
    for path in map(Path, paths):
        files += sorted(path.glob("*.json")) if path.is_dir() else [path] if path.is_file() else []
    if not files:
        return None
    listed: dict[str, list[str]] = {}
    for file in files:
        for job, keys in json.loads(file.read_text(encoding="utf-8")).items():
            listed.setdefault(job, []).extend(keys)
    return listed


def holding(listed: dict | None, words, root: Path = REPO_ROOT) -> list[str]:
    """The jobs that hold a selected test, in a stable order."""
    jobs = {job for job, keys in (listed or {}).items() if keys}
    for suite, words_here in by_suite(words, root).items():
        if words_here and suite in WHOLE_SUITE_JOBS:
            jobs.add(WHOLE_SUITE_JOBS[suite])
    return sorted(jobs)


def _dotted(word: str) -> str:
    """A pytest word as the dotted name of what it selects: tests.test_x.TestA.test_b."""
    path, _, rest = word.partition("::")
    path = path.rstrip("/")
    if path.endswith(".py"):
        path = path[:-3]
    dotted = path.replace("/", ".")
    if rest:
        dotted += "." + rest.replace("::", ".")
    # The results name the backend's tests from tests/ (parts.case_key).
    if dotted.startswith("utk_curio.backend."):
        dotted = dotted[len("utk_curio.backend."):]
    return dotted


def selects(word: str, key: str) -> bool:
    """Whether a word of ``tests`` selects the test whose results key is *key*.

    A pytest key is ``classname::name`` (parts.case_key), a Jest one
    ``src/<file>::<titles>`` (ci_never_run.py).
    """
    if _within(word, JEST):
        return key.split("::", 1)[0] == word[len(FRONTEND) + 1:]
    classname, _, name = key.partition("::")
    test, wanted = f"{classname}.{name}", _dotted(word)
    return test == wanted or test.startswith(wanted + ".") or test.startswith(wanted + "[")


def _never_run():
    """scripts/ci_never_run.py, for its reading of the results and its KNOWN and RUNTIME."""
    path = Path(__file__).resolve().with_name("ci_never_run.py")
    spec = importlib.util.spec_from_file_location("_ci_never_run", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _has_results(inputs: Path, job: str) -> bool:
    folder = inputs / f"ci-inputs-{job}"
    return any(folder.glob("*.xml")) or any(folder.glob("jest*.json"))


def check(inputs: Path, listed: dict | None, words, remint_filter: str = "",
          root: Path = REPO_ROOT) -> tuple[list[str], list[str]]:
    """(errors, notes) for a filtered run's results, as the module doc lists them."""
    never_run = _never_run()
    seen = never_run.outcomes(inputs)
    suites = by_suite(words, root)
    errors, notes = [], []

    def excused(test: str) -> bool:
        entry = seen.get(test)
        return test in never_run.KNOWN or bool(
            entry and any(never_run.RUNTIME.search(reason) for reason in entry["skipped"].values()))

    wanted = []
    if remint_filter or suites["e2e"]:
        wanted.append("test-gpu")
    if suites["backend"]:
        wanted.append("unit-backend-1")
    if wanted and (listed is None or any(job not in listed for job in wanted)):
        notes.append("no list of the selected tests from build-image (its collection failed, so every "
                     "part ran): each word is checked against what ran, and every test that ran")
        listed = {}
    listed = listed or {}

    for job in holding(listed, words, root):
        if not _has_results(inputs, job):
            errors.append(f"{job} holds a selected test and sent no results")
    for job, tests in sorted(listed.items()):
        for test in tests:
            entry = seen.get(test)
            if not (entry and entry["ran"]) and not excused(test):
                how = f"skipped: {next(iter(entry['skipped'].values()), '')}" if entry else "no result"
                errors.append(f"{test}, selected in {job}, did not run ({how})")
    for word in words:
        ran = [test for test, entry in seen.items() if entry["ran"] and selects(word, test)]
        if not ran:
            errors.append(f"{word} selects no test that ran")
    for test, entry in sorted(seen.items()):
        if entry["skipped"] and not entry["ran"] and not excused(test) \
                and not any(test in tests for tests in listed.values()):
            errors.append(f"{test} only skipped ({next(iter(entry['skipped'].values()))})")
    if remint_filter:
        if listed and not any(listed.values()):
            errors.append(f"the remint_filter {remint_filter!r} selects no test")
        elif not any(entry["ran"] for entry in seen.values()):
            errors.append(f"the remint_filter {remint_filter!r} ran no test")
    ran = sum(1 for entry in seen.values() if entry["ran"])
    jobs = holding(listed, words, root)
    notes.append(f"{ran} test(s) ran" + (f", in {', '.join(jobs)}" if jobs else ""))
    return errors, notes


def _fail(message: str) -> int:
    print(f"::error::{message}")
    return 1


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("targets").add_argument("suite", choices=SUITES)
    splitting = commands.add_parser("split")
    splitting.add_argument("--remint", action="store_true")
    splitting.add_argument("--remint-filter", default="")
    hold = commands.add_parser("holding")
    hold.add_argument("listings", nargs="*", type=Path)
    hold.add_argument("--job")
    checking = commands.add_parser("check")
    checking.add_argument("inputs", type=Path)
    checking.add_argument("listings", nargs="*", type=Path)
    checking.add_argument("--remint-filter", default="")
    args = parser.parse_args(argv)
    words = words_of(os.environ.get("CURIO_TESTS"))
    try:
        if args.command == "targets":
            for target in targets(args.suite, words):
                print(target)
            return 0
        if args.command == "split":
            if args.remint and words:
                return _fail("a re-mint takes remint_filter, not tests: dispatch the two apart")
            suites = by_suite(words)
            # A re-mint's filter selects from the e2e suite.
            if args.remint and args.remint_filter:
                suites["e2e"] = ["-k"]
            for suite in SUITES:
                print(f"{suite}={'true' if suites[suite] else 'false'}")
            return 0
        listed = read_listings(args.listings)
        if args.command == "holding":
            jobs = holding(listed, words)
            print(f"Jobs that hold a selected test: {', '.join(jobs) or 'none'}", file=sys.stderr)
            if args.job:
                print(f"CURIO_CI_HOLDS={'true' if args.job in jobs else 'false'}")
            else:
                print(f"holding=,{''.join(job + ',' for job in jobs)}")
            return 0
        errors, notes = check(args.inputs, listed, words, args.remint_filter)
    except Refused as refused:
        return _fail(f"tests: {refused}")
    for note in notes:
        print(note)
    for error in errors:
        print(f"::error::{error}")
    if errors:
        print(f"{len(errors)} problem(s) with the selected tests")
        return 1
    print("OK: every selected test ran")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
