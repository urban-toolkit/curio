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
    ("curio.builtin/merge-flow", "", "forward"),
    ("curio.builtin/vis-vega@1", "{}", "forward"),
    ("curio.builtin/vis-simple", "", "forward"),
    ("curio.builtin/data-export", "", "forward"),
    ("curio.builtin/autk-grammar", RENDER_SPEC, "forward"),
    ("curio.builtin/autk-grammar", DATA_SPEC, "browser"),
    ("curio.builtin/autk-grammar", COMPUTE_SPEC, "browser"),
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
