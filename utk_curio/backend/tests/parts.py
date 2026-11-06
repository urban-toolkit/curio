"""Split a test suite into balanced parts, one per CI runner.

Both the e2e suite (``test_frontend/runner_split.py``, ``CURIO_E2E_PART``) and
the backend unit suite (``conftest.py``, ``CURIO_UNIT_PART``) are cut into
``k/n`` parts that run on separate CPU runner jobs, as many as
``E2E_DESKTOP_PARTS`` and ``BACKEND_UNIT_PARTS`` below. The Full stack build's
matrices hold those counts too, and a Jest test (``ciParts.test.ts``) checks
that they agree, since the CI image these tests run in ships no workflow.

A group, whatever must stay together on one runner, goes to exactly one part,
longest first onto the least-loaded part. An e2e group is one test, unless it
shares a session or a server with its neighbours (``runner_split.part_key``);
a unit group is one test file.

A group costs what its tests took in a recorded run: ``e2e_durations.json``
holds seconds per e2e test (``scripts/e2e_durations.py``), and
``unit_durations.json`` seconds per test file (``scripts/unit_durations.py``).
A test or file missing from its file costs the median recorded one, so a stale
file only costs balance, never a test.

The split runs after every other plugin has deselected (``after_deselection``),
so a part's load counts only the tests that will run in it.

``CURIO_LIST_PARTS=<file>`` lists instead of running: after the same
deselection, each split writes the tests every CI job of its suite would run
(``test-gpu``, ``e2e-desktop-<k>``, ``unit-backend-<k>``) into that JSON file,
by the keys of ``case_key``, and no test runs. A filtered Full stack build
(a re-mint's ``remint_filter``, or its ``tests`` input) collects each suite once
this way, so the jobs and parts that hold no selected test start no stack.
"""

from __future__ import annotations

import json
import os
import re
import statistics
from collections import defaultdict
from pathlib import Path

#: The parts CI runs each suite in: e2e-desktop's matrix and the unit job's
#: backend entries in .github/workflows/docker-compose.yml.
E2E_DESKTOP_PARTS = 14
BACKEND_UNIT_PARTS = 4

#: The file a collection lists every CI job's tests in, instead of running them.
LIST_PARTS = "CURIO_LIST_PARTS"

#: What a group costs when no durations were recorded at all.
DEFAULT_GROUP_SECONDS = 30.0

#: What xdist's ``--dist loadgroup`` appends to a node id: ``@<group>``, after
#: the parameters. A parameter may hold an ``@`` of its own
#: (``[curio.notes@1]``), so only a tail with no bracket in it is the group.
XDIST_GROUP = re.compile(r"@[^\[\]@]*$")


def case_key(classname: str, name: str) -> str:
    """One test's name in every job's results: ``tests.test_x.TestY::test_z[p]``.

    From the classname and name pytest's JUnit writer gives it. The GPU
    runner's xdist appends ``@<group>`` to the name, and a run from the
    repository root starts the classname at ``utk_curio.backend``; neither is
    part of the test.
    """
    if classname.startswith("utk_curio.backend."):
        classname = classname[len("utk_curio.backend."):]
    return f"{classname}::{XDIST_GROUP.sub('', name)}"


def nodeid_address(nodeid: str) -> tuple[str, str]:
    """The (classname, name) pytest's JUnit writer gives the test of a node id."""
    from _pytest.junitxml import mangle_test_address

    names = mangle_test_address(nodeid)
    return ".".join(names[:-1]), names[-1]


def item_address(item) -> tuple[str, str]:
    """The (classname, name) pytest's JUnit writer gives a collected item."""
    return nodeid_address(item.nodeid)


def item_key(item) -> str:
    """``case_key`` of a collected item: its name in ``e2e_durations.json``.

    Computed from the same address the JUnit writer records, so the key a
    part prices a test by is the key ``scripts/e2e_durations.py`` wrote.
    """
    return case_key(*item_address(item))


def file_key(classname: str) -> str:
    """The test file of a JUnit classname, dotted from ``tests/``.

    ``tests.test_agents.test_routes_solve.TestX`` -> ``test_agents.test_routes_solve``:
    the key of ``unit_durations.json``, for a collected item and for a JUnit
    test case alike.
    """
    module = [part for part in classname.split(".") if not part[:1].isupper()]
    for prefix in (["utk_curio", "backend", "tests"], ["tests"]):
        if module[:len(prefix)] == prefix:
            return ".".join(module[len(prefix):])
    return ".".join(module)


def parse_part(value: str, name: str = "part") -> tuple[int, int]:
    """``"k/n"`` -> (k-1, n): 1-based on the outside, 0-based inside."""
    try:
        k, n = (int(piece) for piece in value.split("/", 1))
    except ValueError:
        raise ValueError(f"{name} must be k/n, got {value!r}") from None
    if not 1 <= k <= n:
        raise ValueError(f"{name} {value!r}: k must be between 1 and n")
    return k - 1, n


def load_durations(path: Path) -> dict:
    """Recorded seconds by key, or nothing when the file is missing or unreadable."""
    try:
        return {str(k): float(v) for k, v in json.loads(Path(path).read_text()).items()}
    except (OSError, ValueError):
        return {}


def group_seconds(members: dict, durations: dict) -> dict:
    """What each group costs: ``{group: keys of its tests}`` -> ``{group: seconds}``.

    The sum of its keys' recorded seconds, a key with no record at the median
    recorded one. Summed in key order, so every part's process, whatever its
    hash seed, prices a group to the same last digit.
    """
    default = statistics.median(durations.values()) if durations else DEFAULT_GROUP_SECONDS
    return {group: sum(durations.get(key, default) for key in sorted(keys))
            for group, keys in members.items()}


def assign(groups, parts: int, durations: dict,
           default: float = DEFAULT_GROUP_SECONDS) -> dict:
    """Longest-first onto the least-loaded part. Deterministic for a given input."""
    load = [0.0] * parts
    placed = {}
    ordered = sorted(set(groups), key=lambda g: (-durations.get(g, default), g))
    for group in ordered:
        target = min(range(parts), key=lambda i: (load[i], i))
        placed[group] = target
        load[target] += durations.get(group, default)
    return placed


def placement(items, count: int, group_of, key_of, durations: dict) -> list[int]:
    """The 0-based part of each of ``items``, in their order, out of ``count``.

    ``group_of(item)`` is what must stay on one part with the item, and
    ``key_of(item)`` the item's key in ``durations``.
    """
    groups = [group_of(item) for item in items]
    members = defaultdict(set)
    for item, group in zip(items, groups):
        members[group].add(key_of(item))
    seconds = group_seconds(members, durations)
    placed = assign(seconds, count, seconds)
    return [placed[group] for group in groups]


def split(items, count: int, group_of, key_of, durations: dict) -> list[list]:
    """Every part's items, in their order: what ``keep_part`` keeps for each k."""
    pieces = [[] for _ in range(count)]
    for item, part in zip(items, placement(items, count, group_of, key_of, durations)):
        pieces[part].append(item)
    return pieces


def keep_part(items, value: str, group_of, key_of, durations: dict, name: str = "part"):
    """Split ``items`` into (this part's items, the rest) for ``value`` = ``k/n``.

    ``group_of(item)`` is what must stay on one part with the item, and
    ``key_of(item)`` the item's key in ``durations``.
    """
    index, count = parse_part(value, name)
    where = placement(items, count, group_of, key_of, durations)
    kept = [item for item, part in zip(items, where) if part == index]
    dropped = [item for item, part in zip(items, where) if part != index]
    return kept, dropped


def write_listing(path, jobs: dict) -> None:
    """Add ``{job: [test keys]}`` to the listing at ``path``, keeping its other jobs.

    Both splits can list into one file when one session collects both suites.
    """
    path = Path(path)
    try:
        listed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        listed = {}
    listed.update(jobs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(listed, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def after_deselection(select, listing=None):
    """A pytest plugin that keeps one part: ``select(items)`` -> (kept, dropped).

    Its hook wraps every other ``pytest_collection_modifyitems`` and selects
    once they have all run, so the split sees only the tests that will run.
    A conftest's plain hook runs before pytest's own ``-m`` and ``-k``
    deselection, and splitting there counted tours, live evals and other
    deselected tests toward a part's load. Imports pytest when called, so this
    module stays importable without it (scripts/ci_never_run.py reads
    ``case_key`` on a runner that has no pytest).

    With ``CURIO_LIST_PARTS`` set, ``listing(items)`` -> ``({job: its items},
    the items it placed)``, or None for a session without this suite's tests,
    replaces the selection: the placed items are deselected, and once the
    collection has ended without an error their jobs go into the file, by
    ``item_key``. Every item still selected then is deselected too, so a listing
    runs no test (pytest's exit 5). A collection error writes nothing.
    """
    import pytest

    class AfterDeselection:
        listed: dict | None = None

        @pytest.hookimpl(wrapper=True)
        def pytest_collection_modifyitems(self, config, items):
            result = yield
            if listing is not None and os.environ.get(LIST_PARTS, "").strip():
                found = listing(items)
                if found is not None:
                    jobs, placed = found
                    self.listed = {job: [item_key(item) for item in members]
                                   for job, members in jobs.items()}
                    ids = {id(item) for item in placed}
                    config.hook.pytest_deselected(items=list(placed))
                    items[:] = [item for item in items if id(item) not in ids]
                    return result
            kept, dropped = select(items)
            if dropped:
                config.hook.pytest_deselected(items=dropped)
                items[:] = kept
            return result

        def pytest_collection_finish(self, session):
            if self.listed is None:
                return
            if session.items:
                session.config.hook.pytest_deselected(items=list(session.items))
                session.items[:] = []
            if not session.testsfailed:
                write_listing(os.environ[LIST_PARTS].strip(), self.listed)

    return AfterDeselection()
