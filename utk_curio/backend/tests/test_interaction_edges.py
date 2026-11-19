"""The one rule for interaction edges, on the backend.

An interaction edge carries a selection between two views and never data. A
node's own interaction handle is ``in/out``; a view of a node has one of its
own, ``in/out@<id>``. An edge is an interaction edge when a saved dataflow
types it ``Interaction``, an agent's plan gives it the kind ``interaction``,
or both its handles are interaction handles.

The rule is ``src/contracts/interactionEdges.json``, read through
``utk_curio/common/shared_constants.py`` by ``execution/run_plan.py``, its one
definition here; the plan topology's ``is_interaction_edge`` is that same
function. Every case of ``interactionEdges.cases.json`` runs through both
names, as ``src/tests/contracts/interactionEdgesCases.test.ts`` runs them
through the canvas's ``contracts/interactionEdges.ts``. A guard finds no
module of Curio but ``run_plan.py`` spelling the handle, or comparing a handle
with its constant. Each module is imported inside its test, so a checkout
without one fails each test on its own.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "contracts"
CASES = json.loads((CONTRACTS / "interactionEdges.cases.json").read_text(encoding="utf-8"))

#: The rule's own module, which alone spells the handle's parts and compares with them.
RULE = "utk_curio/backend/app/execution/run_plan.py"
#: A node's own interaction handle, as the contract names it (held to it below).
HANDLE = "in/out"
#: What a view's handle starts with: the handle, then the mark.
VIEW_HANDLE = HANDLE + "@"
#: The modules that may hold the handle's text, each with why. The list is read
#: whole by the last test, so an entry nobody needs is no longer kept.
ALLOWED: dict[str, str] = {}


def _contract() -> dict:
    return json.loads((CONTRACTS / "interactionEdges.json").read_text(encoding="utf-8"))


def test_the_backend_reads_the_rule_from_the_contract():
    from utk_curio.backend.app.execution import run_plan
    from utk_curio.common import shared_constants

    contract = _contract()
    assert shared_constants.read("interactionEdges") == contract
    assert (contract["handle"], contract["viewMark"]) == (HANDLE, "@")
    assert run_plan.INTERACTION_HANDLE == contract["handle"]
    assert run_plan.INTERACTION_EDGE_TYPE == contract["edgeType"]
    assert run_plan.INTERACTION_PLAN_KIND == contract["planKind"]


def test_the_plan_topology_asks_the_same_rule():
    from utk_curio.backend.app.agents.domain import plan_topology
    from utk_curio.backend.app.execution import run_plan

    assert plan_topology.is_interaction_edge is run_plan.is_interaction_edge
    assert plan_topology.INTERACTION_EDGE_TYPE == run_plan.INTERACTION_EDGE_TYPE


@pytest.mark.parametrize("case", CASES["handles"], ids=[case["name"] for case in CASES["handles"]])
def test_each_handle_reads_as_the_cases_file_says(case):
    from utk_curio.backend.app.execution import run_plan

    assert run_plan.is_interaction_handle(case["handle"]) is case["interaction"]
    assert run_plan.interaction_handle_view(case["handle"]) == case["view"]


@pytest.mark.parametrize("case", CASES["viewHandles"], ids=[case["name"] for case in CASES["viewHandles"]])
def test_each_view_s_handle_is_made_as_the_cases_file_says(case):
    """A plan's interaction edge names a view through the handle made from the
    view's id, a node's own handle for none, as the canvas makes a view's dot."""
    from utk_curio.backend.app.execution import run_plan

    assert run_plan.interaction_view_handle(case["view"]) == case["handle"]
    assert run_plan.is_interaction_handle(case["handle"]) is True
    assert run_plan.interaction_handle_view(case["handle"]) == (case["view"] or None)


@pytest.mark.parametrize("case", CASES["edges"], ids=[case["name"] for case in CASES["edges"]])
def test_each_edge_reads_as_the_cases_file_says_on_a_run_and_in_a_plan(case):
    from utk_curio.backend.app.agents.domain import plan_topology
    from utk_curio.backend.app.execution import run_plan

    assert run_plan.is_interaction_edge(case["edge"]) is case["interaction"]
    assert plan_topology.is_interaction_edge(case["edge"]) is case["interaction"]


#: An Autark node feeding a pool, and the pool linked back to the node's view
#: ``heights``, as the canvas holds an edge to a view: its handles alone say
#: what it is.
_FEED = {"id": "feed", "source": "map", "target": "pool", "sourceHandle": "out", "targetHandle": "in"}
_VIEW_LINK = {"id": "link", "source": "pool", "target": "map", "sourceHandle": "in/out", "targetHandle": "in/out@heights"}


def test_a_run_orders_nothing_by_a_link_to_a_view():
    from utk_curio.backend.app.execution.run_plan import ancestors, directed_edges, topological_levels

    assert directed_edges([_FEED, _VIEW_LINK]) == [_FEED]
    assert topological_levels(["map", "pool"], [_FEED, _VIEW_LINK]) == [["map"], ["pool"]]
    assert ancestors("map", [_FEED, _VIEW_LINK]) == {"map"}


def test_the_plan_topology_counts_no_link_to_a_view_as_a_data_edge():
    """A link to a view closes no loop of data edges, so a plan that keeps it
    is not refused as one that makes a cycle."""
    from utk_curio.backend.app.agents.domain import plan_topology

    pairs = plan_topology.net_data_edges([_FEED, _VIEW_LINK], {"edges": []}, set(), set())
    assert pairs == [("map", "pool")]
    assert plan_topology.find_data_cycle(pairs) is None
    plan = {"edges": [{"from": "pool", "to": "map", "kind": "interaction"}]}
    assert plan_topology.closing_plan_edges(pairs, plan) == []


def test_a_reconstruction_reads_a_link_from_a_view_as_an_interaction_edge():
    from utk_curio.backend.app.agents.evaluation.canonical import edge_kind

    assert edge_kind(_VIEW_LINK) == "interaction"
    assert edge_kind({"sourceHandle": "in/out@heights", "targetHandle": "in_1"}) == "data"


def test_the_dataflows_doc_keeps_the_handles_a_link_from_a_view_names():
    from utk_curio.backend.app.collaboration import doc_mapping

    dataflow = {"name": "Linked views", "nodes": [], "edges": [_FEED, {**_VIEW_LINK, "type": "Interaction"}]}
    doc = doc_mapping.new_doc()
    doc_mapping.dataflow_to_doc(dataflow, doc, doc_id="linked-views")
    assert doc_mapping.doc_to_dataflow(doc)["edges"] == dataflow["edges"]


# ---------------------------------------------------------------------------
# The guard: no module but the rule's spells the handle or compares with it.
# ---------------------------------------------------------------------------


def _docstrings(tree: ast.AST) -> set[int]:
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                nodes.add(id(body[0].value))
    return nodes


def _is_the_constant(node: ast.AST) -> bool:
    return (isinstance(node, ast.Name) and node.id == "INTERACTION_HANDLE") or (
        isinstance(node, ast.Attribute) and node.attr == "INTERACTION_HANDLE"
    )


def _findings(name: str, text: str) -> list[str]:
    """Each place *text* spells the handle, makes a view's handle by hand (an
    f-string's text starts with it), or compares a handle with the rule's
    constant. A docstring that names the handle is no use of it."""
    tree = ast.parse(text, filename=name)
    skip = _docstrings(tree)
    out: list[str] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
                and (node.value == HANDLE or node.value.startswith(VIEW_HANDLE))):
            out.append(f"{name}:{node.lineno}: {node.value!r}")
        elif isinstance(node, ast.Compare) and any(_is_the_constant(side) for side in [node.left, *node.comparators]):
            out.append(f"{name}:{node.lineno}: comparison")
    return sorted(out, key=lambda finding: int(finding.split(":")[1]))


def _modules() -> list[Path]:
    """Every Python module of Curio, the tests left out."""
    found = []
    for folder, dirs, files in os.walk(REPO_ROOT / "utk_curio"):
        dirs[:] = sorted(d for d in dirs if d not in {"tests", "node_modules", "dist", "__pycache__", "vendor", "_shipped"})
        found += [Path(folder, name) for name in sorted(files) if name.endswith(".py")]
    return found


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def test_the_handle_it_looks_for_is_the_contracts():
    contract = _contract()
    assert contract["handle"] == HANDLE
    assert contract["handle"] + contract["viewMark"] == VIEW_HANDLE


def test_the_guard_reads_the_backend_the_sandbox_and_the_rules_module():
    names = {_relative(path) for path in _modules()}
    # A guard on the guard: if the walk stopped short, the rule below would pass.
    assert len(names) > 300
    assert {
        RULE,
        "utk_curio/backend/app/agents/domain/plan_topology.py",
        "utk_curio/backend/app/agents/domain/map_edits.py",
        "utk_curio/backend/app/execution/workflow_spec.py",
        "utk_curio/backend/app/projects/scenario_sets.py",
        "utk_curio/backend/app/scenario_catalog/domain/parts.py",
        "utk_curio/sandbox/app/worker.py",
        *ALLOWED,
    } <= names


def test_the_guard_finds_each_way_of_spelling_or_comparing_the_handle_and_nothing_else():
    probe = "\n".join([
        '"""A module that names in/out in its docstring."""',
        "# in/out, named in a comment, is no use of it",
        'if edge.get("sourceHandle") == "in/out": pass',
        'dot = {"id": "in/out"}',
        'view = f"in/out@{view_id}"',
        'named = "in/out@heights"',
        "if handle != INTERACTION_HANDLE: pass",
        "if run_plan.INTERACTION_HANDLE == handle: pass",
        'said = "An in/out link carries a selection"',
        "own = {'id': INTERACTION_HANDLE}",
        "kept = handle if is_interaction_handle(handle) else INTERACTION_HANDLE",
        'outer = "in/outer"',
    ])
    assert [finding.split(":")[1] for finding in _findings("probe.py", probe)] == ["3", "4", "5", "6", "7", "8"]


def test_no_module_but_the_rules_spells_the_handle_or_compares_a_handle_with_its_constant():
    uses = []
    for path in _modules():
        name = _relative(path)
        if name == RULE or name in ALLOWED:
            continue
        uses += _findings(name, path.read_text(encoding="utf-8"))
    assert uses == []


def test_the_rules_module_is_there_and_every_module_the_list_allows_still_holds_the_handle():
    assert (REPO_ROOT / RULE).is_file()
    for name, why in ALLOWED.items():
        assert why
        assert _findings(name, (REPO_ROOT / name).read_text(encoding="utf-8")), name
