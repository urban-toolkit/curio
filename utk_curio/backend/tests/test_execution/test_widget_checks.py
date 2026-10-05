"""What is wrong with a widget, or with a value for one (#662), read from one
table of cases, ``widgetChecks.cases.json``, which Jest reads too
(``src/tests/utils/widgetChecks.cases.test.ts``) through the Widgets tab's own
``checkWidgetDef`` and ``checkWidgetValue``: an agent's widget declarations are
checked by the rules the Widgets tab checks a person's by.

The checks are imported inside each test, so a before-run fails here and not
the whole collection.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CASES = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "widgets" / "widgetChecks.cases.json"


def _cases() -> dict:
    return json.loads(CASES.read_text(encoding="utf-8"))


def test_a_widget_is_checked_as_the_widgets_tab_checks_it():
    from utk_curio.backend.app.execution.code_references import check_widget_def

    cases = _cases()["definitions"]
    assert cases
    mismatches = [
        f"{case['name']}: {got!r}, the table says {case['expected']!r}"
        for case in cases
        if (got := check_widget_def(case["def"], case.get("others") or [], case.get("parameter", False)))
        != case["expected"]
    ]
    assert not mismatches, "\n".join(mismatches)


def test_a_value_is_checked_as_the_widgets_tab_checks_it():
    from utk_curio.backend.app.execution.code_references import check_widget_value

    cases = _cases()["values"]
    assert cases
    mismatches = [
        f"{case['name']}: {got!r}, the table says {case['expected']!r}"
        for case in cases
        if (got := check_widget_value(case["widget"], case["value"])) != case["expected"]
    ]
    assert not mismatches, "\n".join(mismatches)


def test_the_table_holds_both_answers_for_every_kind():
    """Each kind has a case the Widgets tab accepts and one it refuses, so a
    kind dropped from the twin fails a case."""
    from utk_curio.backend.app.execution.code_references import WIDGET_KINDS

    values = _cases()["values"]
    for kind in WIDGET_KINDS:
        answers = {case["expected"] is None for case in values if case["widget"]["type"] == kind}
        assert answers == {True, False}, (kind, answers)
