"""Interaction edges that name a view of an Autark node, in an agent's plan.

An Autark node of several views has a dot per view with an ``id`` beside its
own (``in/out@<id>``). A plan's interaction edge names the view at either end
with ``fromView`` and ``toView``: the parser keeps them on interaction edges
alone, the duplicate key holds them, so two edges between the same nodes on
two views stay apart, the plan's check refuses a view the node at that end
does not have, and the apply draws the edge on the dots they name. Its card
names the views. Each module is imported inside its test, so a checkout
without what it names fails each test on its own.
"""
from __future__ import annotations

import json

VEGA = "curio.builtin/vis-vega@1"
AUTARK = "curio.builtin/autk-grammar@1"
LAYER = {"dataRef": "input_0", "isPick": True}
#: The dataflow's nodes: a node of a map `city` and a plot `heights`, a node of one map, and a chart.
EXISTING = {
    "views": {"id": "views", "type": AUTARK, "goal": "Two views", "content": json.dumps({
        "map": {"id": "city", "layerRefs": [LAYER]},
        "plot": {"id": "heights", "dataRef": "input_0", "mark": "bar", "axis": ["height", "@transform"]},
    })},
    "one": {"id": "one", "type": AUTARK, "goal": "One map", "content": json.dumps({"map": {"id": "city", "layerRefs": [LAYER]}})},
    "chart": {"id": "chart", "type": VEGA, "goal": "Heights chart", "content": "{}"},
}


def _parse(edges: list) -> tuple:
    from utk_curio.backend.app.agents.domain import content

    return content.parse_dataflow_plan_verbose({"goal": "g", "edges": edges})


class TestTheParse:
    def test_an_interaction_edge_keeps_the_views_it_names(self):
        part, errors = _parse([
            {"from": "chart", "to": "views", "kind": "interaction", "toView": " heights "},
            {"from": "views", "to": "chart", "kind": "interaction", "fromView": "city"},
        ])
        assert errors == []
        assert part["edges"] == [
            {"from": "chart", "to": "views", "kind": "interaction", "toView": "heights"},
            {"from": "views", "to": "chart", "kind": "interaction", "fromView": "city"},
        ]

    def test_a_data_edge_naming_a_view_is_refused_with_the_fix(self):
        for field in ("fromView", "toView"):
            part, errors = _parse([{"from": "a", "to": "b", field: "heights"}])
            assert part is None
            assert any("edges[0]" in e and "drop fromView and toView" in e for e in errors), errors

    def test_a_view_that_is_no_short_text_is_refused(self):
        for value in ("x" * 200, 3, " "):
            part, errors = _parse([{"from": "a", "to": "b", "kind": "interaction", "toView": value}])
            assert part is None
            assert any("edges[0].toView" in e for e in errors), (value, errors)

    def test_two_interaction_edges_between_the_same_nodes_on_two_views_stay_apart(self):
        part, errors = _parse([
            {"from": "chart", "to": "views", "kind": "interaction", "toView": "city"},
            {"from": "chart", "to": "views", "kind": "interaction", "toView": "heights"},
            {"from": "chart", "to": "views", "kind": "interaction"},
        ])
        assert errors == []
        assert [edge.get("toView") for edge in part["edges"]] == ["city", "heights", None]

    def test_the_same_views_twice_is_a_duplicate_that_names_them(self):
        part, errors = _parse([
            {"from": "chart", "to": "views", "kind": "interaction", "toView": "heights"},
            {"from": "chart", "to": "views", "kind": "interaction", "toView": "heights"},
        ])
        assert part is None
        assert any(
            "edges[1] duplicates an earlier 'chart'→'views' interaction edge" in e and "'heights'" in e
            for e in errors
        ), errors


class TestTheCheck:
    """A view a plan names must be a view, by its id, of the Autark node at
    that end, a node of several views. A node the plan adds has no document
    yet: the view it names there is what the plan asks of it."""

    def _errors(self, edges: list, plan_nodes: tuple = ()) -> list:
        from utk_curio.backend.app.agents.domain import plan_topology

        types = {node["ref"]: node["nodeType"] for node in plan_nodes}
        return plan_topology.interaction_view_errors(
            {"nodes": list(plan_nodes), "edges": edges},
            lambda end: types.get(end) or (EXISTING.get(end) or {}).get("type"),
            lambda end: (EXISTING.get(end) or {}).get("content"),
        )

    def test_a_view_of_the_node_named_by_its_id_passes(self):
        assert self._errors([{"from": "chart", "to": "views", "kind": "interaction", "toView": "heights"}]) == []
        assert self._errors([{"from": "views", "to": "chart", "kind": "interaction", "fromView": "city"}]) == []
        # The node's own dot names no view.
        assert self._errors([{"from": "chart", "to": "views", "kind": "interaction"}]) == []

    def test_a_view_the_node_does_not_have_is_refused_naming_the_ones_it_has(self):
        errors = self._errors([{"from": "chart", "to": "views", "kind": "interaction", "toView": "parks"}])
        assert len(errors) == 1 and "edges[0].toView 'parks'" in errors[0], errors
        assert "'city', 'heights'" in errors[0], errors

    def test_a_view_on_a_node_of_one_view_is_refused(self):
        errors = self._errors([{"from": "chart", "to": "one", "kind": "interaction", "toView": "city"}])
        assert len(errors) == 1 and "edges[0].toView 'city'" in errors[0] and "drop toView" in errors[0], errors

    def test_a_view_on_a_node_that_draws_no_views_is_refused(self):
        errors = self._errors([{"from": "chart", "to": "views", "kind": "interaction", "fromView": "bars", "toView": "heights"}])
        assert len(errors) == 1 and "edges[0].fromView 'bars'" in errors[0] and "drop fromView" in errors[0], errors

    def test_a_view_on_an_autark_node_the_plan_adds_is_what_the_plan_asks_of_it(self):
        node = {"ref": "n1", "nodeType": "curio.builtin/autk-grammar", "title": "Views", "intent": "a map and a plot `heights`"}
        assert self._errors([{"from": "chart", "to": "n1", "kind": "interaction", "toView": "heights"}], (node,)) == []
        chart = {"ref": "n2", "nodeType": "curio.builtin/vis-vega", "title": "Chart", "intent": "a chart"}
        errors = self._errors([{"from": "n2", "to": "views", "kind": "interaction", "fromView": "bars"}], (chart,))
        assert len(errors) == 1 and "edges[0].fromView 'bars'" in errors[0], errors


class TestTheApply:
    def test_an_interaction_edge_is_drawn_on_the_dots_of_the_views_it_names(self):
        from utk_curio.backend.app.agents.application.proposals import plans

        drawn = plans._interaction_spec_edge("chart", "views", None, "heights")
        assert (drawn["sourceHandle"], drawn["targetHandle"], drawn["type"]) == ("in/out", "in/out@heights", "Interaction")
        drawn = plans._interaction_spec_edge("views", "chart", "city", None)
        assert (drawn["sourceHandle"], drawn["targetHandle"]) == ("in/out@city", "in/out")
        # Naming none, it joins the two nodes' own dots, as before.
        drawn = plans._interaction_spec_edge("chart", "views")
        assert (drawn["sourceHandle"], drawn["targetHandle"]) == ("in/out", "in/out")

    def test_an_edge_already_on_the_same_views_is_the_plan_s_edge_and_one_on_other_views_is_not(self):
        from utk_curio.backend.app.agents.application.proposals import plans

        on_city = {"id": "e1", "source": "chart", "target": "views", "sourceHandle": "in/out",
                   "targetHandle": "in/out@city", "type": "Interaction"}
        to_city = [{"from": "chart", "to": "views", "kind": "interaction", "toView": "city"}]
        to_heights = [{"from": "chart", "to": "views", "kind": "interaction", "toView": "heights"}]
        to_node = [{"from": "chart", "to": "views", "kind": "interaction"}]
        assert plans._existing_plan_edge([on_city], to_city, 0, "chart", "views") == on_city
        assert plans._existing_plan_edge([on_city], to_heights, 0, "chart", "views") is None
        # The node's own dot carries every view: another edge than one on a view's dot.
        assert plans._existing_plan_edge([on_city], to_node, 0, "chart", "views") is None

    def test_the_plan_s_card_names_the_views(self):
        from utk_curio.backend.app.agents.application.proposals import plans

        plan = {"goal": "g", "nodes": [], "edges": [
            {"from": "chart", "to": "views", "kind": "interaction", "toView": "heights"},
            {"from": "views", "to": "chart", "kind": "interaction", "fromView": "city"},
        ]}
        part = plans._plan_review_part("p1", plan, EXISTING, [], {}, "summary", [])
        assert [(e.get("fromView"), e.get("toView")) for e in part["plan"]["edges"]] == [(None, "heights"), ("city", None)]
