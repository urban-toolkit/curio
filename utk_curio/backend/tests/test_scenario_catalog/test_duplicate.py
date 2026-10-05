"""Duplicate selection (#662) read from one table of cases,
``duplicateSelection.cases.json``, which Jest reads too
(``src/tests/utils/duplicateSelection.cases.test.ts``) through the canvas's
``duplicateSelection``: a Dataflow Builder plan's duplicate copies a selection
the way the canvas's Duplicate selection does.

The module is imported inside each test, so a before-run fails here and not
the whole collection.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CASES = (
    REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "scenarios"
    / "duplicateSelection.cases.json"
)


def _ids():
    count = {"n": 0}

    def new_id() -> str:
        count["n"] += 1
        return f"copy-{count['n']}"

    return new_id


def test_a_plan_duplicates_a_selection_as_the_canvas_does():
    from utk_curio.backend.app.scenario_catalog.domain.duplicate import duplicate_selection

    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    assert cases
    mismatches = []
    for case in cases:
        got = duplicate_selection(
            case["nodes"], case["edges"], case["selected"], new_id=_ids(), offset={"x": 0, "y": 400}
        )
        expected = case["expected"]
        if [list(pair) for pair in got["ids"].items()] != expected["ids"]:
            mismatches.append(f"{case['name']}: ids {got['ids']!r}, the table says {expected['ids']!r}")
        if got["nodes"] != expected["nodes"]:
            mismatches.append(f"{case['name']}: nodes {got['nodes']!r}, the table says {expected['nodes']!r}")
        if got["edges"] != expected["edges"]:
            mismatches.append(f"{case['name']}: edges {got['edges']!r}, the table says {expected['edges']!r}")
    assert not mismatches, "\n".join(mismatches)


def test_the_originals_are_left_as_they_were():
    from utk_curio.backend.app.scenario_catalog.domain.duplicate import duplicate_selection

    case = json.loads(CASES.read_text(encoding="utf-8"))["cases"][0]
    before = json.dumps(case, sort_keys=True)
    duplicate_selection(case["nodes"], case["edges"], case["selected"], new_id=_ids(), offset={"x": 0, "y": 400})
    assert json.dumps(case, sort_keys=True) == before


def test_the_table_covers_each_rule():
    """A case for every rule the module docstring names, so a rule dropped
    from the twin fails a case and not only a read of the code."""
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    copied = [e for c in cases for e in c["expected"]["edges"]]
    assert any(e["source"] == "load" for e in copied), "an edge entering the selection"
    assert any(e.get("type") == "Interaction" for e in copied), "a link between two copied views"
    assert any(n["metadata"]["copiedFrom"] == ["root", "a"] for c in cases for n in c["expected"]["nodes"])
    assert all("dashboardPinned" not in n for c in cases for n in c["expected"]["nodes"])
    leaving = cases[0]["edges"][2]
    assert leaving["target"] == "after" and not any(e["target"] == "after" for e in cases[0]["expected"]["edges"])
