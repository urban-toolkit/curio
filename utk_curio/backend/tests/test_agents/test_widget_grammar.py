"""The widgets an agent declares on a node (#662): shaped as ``$defs.widget``
and judged by the Widgets tab's own rules, with an error the model can act on
for each one that is wrong.

The grammar is imported inside each test, so a before-run fails here and not
the whole collection.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def _grammar():
    from utk_curio.backend.app.agents.domain import widget_grammar

    return widget_grammar


def test_the_shape_is_the_trill_schemas_widget():
    from utk_curio.backend.app.execution.code_references import WIDGET_KINDS

    wg = _grammar()
    widget = json.loads((REPO_ROOT / "docs" / "schemas" / "trill.v1.json").read_text(encoding="utf-8"))["$defs"]["widget"]
    assert list(widget["properties"]) == list(wg.WIDGET_KEYS)
    assert list(widget["properties"]["options"]["properties"]) == list(wg.OPTION_KEYS)
    assert widget["properties"]["options"]["properties"]["display"]["enum"] == list(wg.CHOICE_DISPLAYS)
    assert widget["properties"]["type"]["enum"] == list(WIDGET_KINDS)


def test_a_declaration_is_kept_as_a_node_stores_it():
    widgets, errors = _grammar().parse_widgets(
        [
            {"name": "factor", "type": "slider", "label": "Height factor", "options": {"min": 0.5, "max": 4, "step": 0.5}},
            {"name": "season", "type": "choice", "default": "summer", "options": {"choices": ["winter", "summer"], "display": "radio"}},
        ],
        "nodes[0].widgets",
    )
    assert errors == []
    # No default: the kind's own, as the canvas gives it (a slider starts at its minimum).
    assert widgets == [
        {"name": "factor", "type": "slider", "label": "Height factor", "options": {"min": 0.5, "max": 4, "step": 0.5}, "default": 0.5},
        {"name": "season", "type": "choice", "default": "summer", "options": {"choices": ["winter", "summer"], "display": "radio"}},
    ]
    assert _grammar().parse_widgets(None, "w") == ([], [])


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("factor", "must be a list of widgets"),
        ([{"name": "f", "type": "number", "kind": "x"}], "has keys a widget does not: kind"),
        ([{"name": "2x", "type": "number"}], "A name is letters, digits and underscores"),
        ([{"name": "f", "type": "colour"}], "Pick a widget type."),
        ([{"name": "f", "type": "number"}, {"name": "f", "type": "text"}], "This node already has a widget named f."),
        ([{"name": "f", "type": "slider"}], "A slider needs a minimum and a maximum."),
        ([{"name": "f", "type": "number", "default": 9, "options": {"min": 0, "max": 4}}], "Enter a number from 0 to 4."),
        ([{"name": "f", "type": "number", "default": 1, "value": "2"}], "Enter a number."),
        ([{"name": "f", "type": "number", "options": {"step": "1"}}], "options.step must be a number"),
        ([{"name": "f", "type": "choice", "options": {"choices": []}}], "Give at least one choice."),
        ([{"name": "f", "type": "choice", "options": {"display": "tabs", "choices": ["a"]}}], "display must be one of"),
        ([{"name": f"w{i}", "type": "number"} for i in range(17)], "has 17 widgets (max 16)"),
    ],
)
def test_each_wrong_declaration_is_named(raw, expected):
    widgets, errors = _grammar().parse_widgets(raw, "nodes[1].widgets")
    assert widgets == []
    assert any(expected in e for e in errors), errors
    assert all(e.startswith("nodes[1].widgets") for e in errors), errors


def test_a_value_is_judged_as_the_widgets_tab_judges_one():
    wg = _grammar()
    factor = {"name": "factor", "type": "number", "default": 1, "options": {"min": 0, "max": 4}}
    assert wg.value_problem(factor, 2, "values.copy.factor") is None
    assert wg.value_problem(factor, 9, "values.copy.factor") == "values.copy.factor: Enter a number from 0 to 4."
    assert wg.value_problem(factor, float("nan"), "v") == "v is not a JSON value"
    assert wg.with_values([factor], {"factor": 2}) == [{**factor, "value": 2}]
    assert "value" not in factor
