"""``execution/node_names.py`` names a node as ``utils/nodeDisplayLabel.ts`` does (#775).

Both sides run the cases in ``nodeDisplayLabel.cases.json`` beside the
TypeScript (``src/tests/utils/nodeDisplayLabelCases.test.ts`` is the other
half): the name a node's canvas header shows, which also titles its computed
dataset, whichever path saves it.

``node_names`` is imported inside each test, so a checkout without it fails
each test on its own instead of failing the whole collection.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CASES_FILE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "utils" / "nodeDisplayLabel.cases.json"
)


def _cases():
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    return [pytest.param(case, id=case["name"]) for case in cases]


@pytest.mark.parametrize("case", _cases())
def test_a_node_is_named_as_the_canvas_names_it(case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.execution import node_names

    got = node_names.display_label(
        case["nodeType"], case.get("customLabel"), case.get("templateLabel"),
    )
    assert got == case["label"]


@pytest.mark.parametrize("case", _cases())
def test_a_saved_node_is_named_as_the_canvas_names_it(case):
    """The same cases, with the node as a saved dataflow holds it: the renamed
    header under ``metadata``, the template label from the project's templates
    keyed by unversioned id."""
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.execution import node_names
    from utk_curio.backend.app.packages.application.templates import canonical_template_id

    node = {"id": "n", "type": case["nodeType"]}
    if case.get("customLabel") is not None:
        node["metadata"] = {"packageTemplateLabel": case["customLabel"]}
    labels = {}
    if case.get("templateLabel") is not None:
        labels[canonical_template_id(case["nodeType"])] = case["templateLabel"]
    assert node_names.saved_node_label(node, labels) == case["label"]


def test_the_older_saved_shape_is_read_too():
    """``data.packageTemplateLabel`` and ``data.nodeType``, which the schema
    still accepts and the save-time title has always read."""
    from utk_curio.backend.app.execution import node_names

    labels = {"curio.builtin/computation-analysis": "Python Computation"}
    assert node_names.saved_node_label(
        {"id": "n", "data": {"nodeType": "curio.builtin/computation-analysis@1"}}, labels,
    ) == "Python Computation"
    assert node_names.saved_node_label(
        {"id": "n", "type": "curio.builtin/computation-analysis@1",
         "data": {"packageTemplateLabel": "My Step"}}, labels,
    ) == "My Step"
    # The renamed header the canvas writes today wins over the older one.
    assert node_names.saved_node_label(
        {"id": "n", "type": "curio.builtin/computation-analysis@1",
         "metadata": {"packageTemplateLabel": "Renamed"},
         "data": {"packageTemplateLabel": "My Step"}}, labels,
    ) == "Renamed"


def test_a_title_set_by_an_agent_does_not_rename_the_node():
    """The canvas header never shows ``title``, so neither does the name."""
    from utk_curio.backend.app.execution import node_names

    node = {"id": "n", "type": "curio.builtin/data-loading@1", "title": "Load the census"}
    assert node_names.saved_node_label(node, {"curio.builtin/data-loading": "Data Loading"}) == "Data Loading"


def test_the_fallback_title_has_no_version_suffix():
    """``_humanize_node_type``, the save-time fallback, drops the ``@N`` of a
    versioned type: ``curio.builtin/data-loading@1`` is "Data Loading"."""
    from utk_curio.backend.app.projects.services import _humanize_node_type

    assert _humanize_node_type("curio.builtin/data-loading@1") == "Data Loading"
    assert _humanize_node_type("curio.builtin/computation-analysis@1") == "Computation Analysis"
