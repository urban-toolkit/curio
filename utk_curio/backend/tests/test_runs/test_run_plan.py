"""The order and the roles of a run on the server.

``topological_levels`` runs the cases in ``providers/flow/runLevels.cases.json``,
which ``src/tests/providers/runLevelsCases.test.ts`` runs through Run All's own
``computeTopologicalLevels``. ``run_plan`` is imported inside each test, so a
checkout without it fails each test on its own.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CASES_FILE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "providers" / "flow" / "runLevels.cases.json"
)

RENDER_SPEC = json.dumps({"map": {"layerRefs": []}})
DATA_SPEC = json.dumps({"data": [{"type": "osm"}]})
COMPUTE_SPEC = json.dumps({"compute": [{"shader": "x"}]})
#: A data section and a compute step over it: the browser computes.
DATA_AND_COMPUTE_SPEC = json.dumps({"data": [{"type": "osm"}], "compute": [{"shader": "x"}]})
#: No data of its own to load: the node reads its input, in the browser.
EMPTY_DATA_SPEC = json.dumps({"data": []})


def _cases():
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    return [pytest.param(case, id=case["name"]) for case in cases]


@pytest.mark.parametrize("case", _cases())
def test_levels_match_run_all(case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.execution.run_plan import topological_levels

    assert topological_levels(case["nodes"], case["edges"]) == case["levels"]


def test_an_interaction_link_is_known_by_its_type_or_its_handles():
    from utk_curio.backend.app.execution.run_plan import is_interaction_edge

    assert is_interaction_edge({"type": "Interaction"})
    assert is_interaction_edge({"sourceHandle": "in/out", "targetHandle": "in/out"})
    assert not is_interaction_edge({"sourceHandle": "out", "targetHandle": "in_1"})
    assert not is_interaction_edge({"sourceHandle": "in/out", "targetHandle": "in"})


def test_ancestors_follow_data_edges_only():
    from utk_curio.backend.app.execution.run_plan import ancestors

    edges = [
        {"source": "a", "target": "b"},
        {"source": "b", "target": "c"},
        {"source": "x", "target": "c", "type": "Interaction",
         "sourceHandle": "in/out", "targetHandle": "in/out"},
        {"source": "c", "target": "d"},
    ]
    assert ancestors("c", edges) == {"a", "b", "c"}
    assert ancestors("a", edges) == {"a"}


@pytest.mark.parametrize("node_type, content, role", [
    ("curio.builtin/computation-analysis", "", "run"),
    ("curio.builtin/data-loading@1", "", "run"),
    ("curio.builtin/js-computation", "", "run"),
    ("curio.builtin/data-pool", "", "forward"),
    ("curio.builtin/parameter@1", "", "forward"),
    ("curio.builtin/note@1", "# Findings\n- one", "forward"),
    ("curio.builtin/vis-vega@1", "{}", "forward"),
    ("curio.builtin/vis-simple", "", "forward"),
    # Its code writes the file its Download saves: a run runs it.
    ("curio.builtin/data-export", "", "run"),
    ("curio.builtin/data-export@1", "return curio_export(input_0, \"trees\")", "run"),
    ("curio.builtin/autk-grammar", RENDER_SPEC, "forward"),
    ("curio.builtin/autk-grammar", DATA_SPEC, "run"),
    ("curio.builtin/autk-grammar", COMPUTE_SPEC, "browser"),
    ("curio.builtin/autk-grammar", DATA_AND_COMPUTE_SPEC, "browser"),
    ("curio.builtin/autk-grammar", EMPTY_DATA_SPEC, "browser"),
    ("curio.builtin/spatial-join", "", "browser"),
])
def test_each_kind_has_the_role_the_canvas_gives_it(node_type, content, role):
    from utk_curio.backend.app.execution.run_plan import node_role

    assert node_role({"id": "n", "type": node_type, "content": content}) == role


def test_the_roster_decides_what_a_package_node_runs():
    from utk_curio.backend.app.execution.run_plan import node_role

    templates = {
        "pkg.example/code": {"executable": True, "engine": "python"},
        "pkg.example/handler": {"executable": False, "engine": "python"},
    }
    assert node_role({"id": "n", "type": "pkg.example/code@1"}, templates) == "run"
    assert node_role({"id": "n", "type": "pkg.example/handler"}, templates) == "browser"


@pytest.mark.parametrize("node_type", [
    # A saved Compare Scenarios node: its package no longer holds the template.
    "curio.builtin/compare-scenarios",
    "curio.builtin/compare-scenarios@1",
    # A package nothing holds.
    "curio.nowhere/missing-node",
    "curio.nowhere/missing-node@1",
])
def test_a_type_no_installed_package_provides_is_failed_by_the_run_not_left_to_the_browser(node_type):
    """The canvas cannot run such a node either: it shows a card in place of
    its body. A run on the server fails it rather than leaving it to a tab,
    whatever it holds, with or without a roster that lacks it."""
    from utk_curio.backend.app.execution.run_plan import node_role

    assert node_role({"id": "n", "type": node_type, "content": ""}) == "missing"
    assert node_role({"id": "n", "type": node_type, "content": "return input_0"}) == "missing"
    roster = {"pkg.example/handler": {"executable": False, "engine": "python"}}
    assert node_role({"id": "n", "type": node_type, "content": ""}, roster) == "missing"


@pytest.mark.parametrize("node_type", ["curio.scout/donuts@1", "curio.scout/lines-with-band"])
def test_a_package_chart_that_draws_with_vega_lite_is_forwarded_as_the_vega_lite_node_is(node_type):
    """Scout's charts draw with the Vega-Lite node's behavior: a run
    hands their input on, as it does a Vega-Lite node's, and a tab draws them
    afterwards. Read off the shipped manifest, or off the project's roster,
    which also answers for a package of the account's own."""
    from utk_curio.backend.app.execution.run_plan import node_role

    assert node_role({"id": "n", "type": node_type, "content": "{}"}) == "forward"
    roster = {"acme.charts/bars": {"executable": False, "engine": "python", "contentKind": "grammar",
                                   "grammar": "vega-lite"}}
    assert node_role({"id": "n", "type": "acme.charts/bars@1", "content": "{}"}, roster) == "forward"
