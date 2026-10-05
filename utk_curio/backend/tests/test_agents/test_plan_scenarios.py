"""The widgets and scenarios of a Dataflow Builder plan (#662), as the plan
grammar reads them: a planned node declares the widgets its code reads, and a
plan saves scenarios, named selections of its nodes and duplicates of them.
A duplicate is expanded into the plan by the canvas's own Duplicate selection
rule, so the review card names every node and connection it adds.

The mint, the review card and the applies are in
``test_plan_scenario_routes.py``.
"""
from __future__ import annotations

import copy

CA = "curio.builtin/computation-analysis"
VEGA = "curio.builtin/vis-vega"


def _parse(plan: dict):
    from utk_curio.backend.app.agents.domain import content

    return content.parse_dataflow_plan_verbose(copy.deepcopy(plan))


def _plan(**extra) -> dict:
    """Buildings feed shadow lengths, drawn as a chart; a comparison reads the
    shadows of both scenarios."""
    plan = {
        "goal": "compare real and doubled building heights",
        "nodes": [
            {"ref": "buildings", "nodeType": CA, "title": "Buildings", "intent": "a frame of building heights"},
            {"ref": "shadows", "nodeType": CA, "title": "Shadows", "intent": "shadow length per building",
             "widgets": [{"name": "height_factor", "type": "number", "label": "Height factor", "default": 1,
                          "options": {"min": 0.5, "max": 4, "step": 0.5}}]},
            {"ref": "chart", "nodeType": VEGA, "title": "Shadow chart", "intent": "a bar per building"},
            {"ref": "compare", "nodeType": CA, "title": "Compare", "intent": "mean shadow per scenario"},
        ],
        "edges": [
            {"from": "buildings", "to": "shadows"},
            {"from": "shadows", "to": "chart"},
            {"from": "shadows", "to": "compare", "toHandle": "in"},
            {"from": "shadows_tall", "to": "compare", "toHandle": "in_1"},
        ],
        "scenarios": [
            {"name": "Real heights", "nodes": ["shadows", "chart"], "description": "the heights as mapped"},
            {"name": "Twice as tall", "duplicateOf": "Real heights",
             "copies": {"shadows": "shadows_tall", "chart": "chart_tall"},
             "values": {"shadows_tall": {"height_factor": 2}}},
        ],
    }
    plan.update(extra)
    return plan


class TestWidgets:
    def test_a_planned_node_keeps_its_widgets(self):
        plan, errors = _parse(_plan(scenarios=None))
        assert errors == []
        shadows = next(n for n in plan["nodes"] if n["ref"] == "shadows")
        assert shadows["widgets"] == [{"name": "height_factor", "type": "number", "label": "Height factor",
                                       "default": 1, "options": {"min": 0.5, "max": 4, "step": 0.5}}]
        # Byte-absent when a node declares none, as every other optional key.
        assert "widgets" not in plan["nodes"][0]

    def test_a_wrong_widget_comes_back_as_an_error_naming_it(self):
        broken = _plan(scenarios=None)
        broken["nodes"][1]["widgets"][0]["default"] = 9
        plan, errors = _parse(broken)
        assert plan is None
        assert errors == ["nodes[1].widgets[0] ('height_factor'): Enter a number from 0.5 to 4."]

    def test_a_parameter_node_holds_exactly_one_widget(self):
        parameter = {"ref": "season", "nodeType": "curio.builtin/parameter", "title": "Season", "intent": "the season"}
        _, errors = _parse({"goal": "g", "nodes": [parameter]})
        assert errors == ["nodes[0] is a Parameter node, which holds exactly one widget: give it in widgets"]
        parameter["widgets"] = [{"name": "season", "type": "text", "default": "winter"}]
        plan, errors = _parse({"goal": "g", "nodes": [parameter]})
        assert errors == [] and plan["nodes"][0]["widgets"][0]["name"] == "season"


class TestSelections:
    def test_a_plan_without_scenarios_has_no_key(self):
        plan, errors = _parse(_plan(scenarios=None))
        assert errors == [] and "scenarios" not in plan
        assert not any("copyOf" in n for n in plan["nodes"])

    def test_a_selection_names_plan_refs_and_existing_nodes(self):
        plan, errors = _parse(_plan(scenarios=[{"name": "Mine", "nodes": ["shadows", "existing-id"]}]))
        assert errors == []
        assert plan["scenarios"] == [{"name": "Mine", "nodes": ["shadows", "existing-id"]}]

    def test_a_plan_may_only_save_scenarios(self):
        plan, errors = _parse({"goal": "g", "scenarios": [{"name": "Mine", "nodes": ["existing-id"]}]})
        assert errors == [] and plan["nodes"] == [] and plan["scenarios"][0]["name"] == "Mine"

    def test_a_node_belongs_to_one_scenario(self):
        _, errors = _parse(_plan(scenarios=[
            {"name": "One", "nodes": ["shadows"]},
            {"name": "Two", "nodes": ["chart", "shadows"]},
        ]))
        assert errors == ["scenarios[1].nodes[1] 'shadows' is already in the scenario 'One': a node belongs to one scenario"]

    def test_names_are_unique_and_an_entry_is_one_kind(self):
        _, errors = _parse(_plan(scenarios=[{"name": "One", "nodes": ["shadows"]}, {"name": "One", "nodes": ["chart"]}]))
        assert errors == ["scenarios[1].name 'One' names an earlier scenario: each scenario needs its own name"]
        _, errors = _parse(_plan(scenarios=[{"name": "One", "nodes": ["shadows"], "duplicateOf": "Two"}]))
        assert errors == ["scenarios[0] must give either nodes (a selection) or duplicateOf (a duplicate)"]

    def test_a_node_the_plan_removes_is_no_member(self):
        _, errors = _parse(_plan(scenarios=[{"name": "Mine", "nodes": ["old"]}], removeNodes=["old"]))
        assert errors == ["scenarios[0].nodes[0] 'old' is a node this plan removes"]

    def test_unknown_keys_and_bad_colors_are_named(self):
        _, errors = _parse(_plan(scenarios=[{"name": "Mine", "nodes": ["shadows"], "colour": "red"}]))
        assert errors and "has keys a scenario does not: colour" in errors[0]
        _, errors = _parse(_plan(scenarios=[{"name": "Mine", "nodes": ["shadows"], "color": "red"}]))
        assert errors == ["scenarios[0].color 'red' is not a #RRGGBB color"]


class TestDuplicates:
    def test_a_duplicate_copies_the_nodes_and_their_edges_by_the_canvas_rule(self):
        plan, errors = _parse(_plan())
        assert errors == []
        copies = {n["ref"]: n for n in plan["nodes"] if n.get("copyOf")}
        assert set(copies) == {"shadows_tall", "chart_tall"}
        # A copy is its original under a ref of its own: type, title and intent kept.
        assert copies["chart_tall"] == {"ref": "chart_tall", "nodeType": VEGA, "title": "Shadow chart",
                                        "intent": "a bar per building", "copyOf": "chart"}
        # The lever: the copy's widget takes the value the duplicate sets, as
        # the Widgets tab sets one; the original keeps its own.
        assert copies["shadows_tall"]["widgets"][0]["value"] == 2
        assert "value" not in plan["nodes"][1]["widgets"][0]
        edges = [(e["from"], e["to"], e.get("toHandle")) for e in plan["edges"]]
        # The edge entering the selection feeds the copy, the edge between its
        # nodes is copied, and the edge leaving it (shadows -> compare) is not:
        # the plan wires the copy into the comparison itself, by its ref.
        assert ("buildings", "shadows_tall", None) in edges
        assert ("shadows_tall", "chart_tall", None) in edges
        assert ("shadows_tall", "compare", "in_1") in edges
        assert edges.count(("shadows", "compare", "in")) == 1
        assert not any(e[0] == "chart_tall" for e in edges)
        assert plan["scenarios"][1] == {"name": "Twice as tall", "duplicateOf": "Real heights",
                                        "values": {"shadows_tall": {"height_factor": 2}},
                                        "nodes": ["shadows_tall", "chart_tall"]}

    def test_an_edge_the_plan_already_names_into_a_copy_is_not_added_twice(self):
        plan, errors = _parse(_plan(edges=_plan()["edges"] + [{"from": "buildings", "to": "shadows_tall"}]))
        assert errors == []
        assert [(e["from"], e["to"]) for e in plan["edges"]].count(("buildings", "shadows_tall")) == 1

    def test_a_duplicate_of_a_duplicate_copies_the_copies(self):
        plan, errors = _parse(_plan(scenarios=_plan()["scenarios"] + [
            {"name": "Thrice", "duplicateOf": "Twice as tall",
             "copies": {"shadows_tall": "shadows_3", "chart_tall": "chart_3"},
             "values": {"shadows_3": {"height_factor": 3}}},
        ]))
        assert errors == []
        third = next(n for n in plan["nodes"] if n["ref"] == "shadows_3")
        assert third["copyOf"] == "shadows_tall" and third["widgets"][0]["value"] == 3
        assert ("buildings", "shadows_3") in [(e["from"], e["to"]) for e in plan["edges"]]

    def test_each_wrong_duplicate_is_named(self):
        def errors_for(entry):
            return _parse(_plan(scenarios=[_plan()["scenarios"][0], entry]))[1]

        base = {"name": "Twice as tall", "duplicateOf": "Real heights",
                "copies": {"shadows": "shadows_tall", "chart": "chart_tall"}}
        assert errors_for({**base, "duplicateOf": "Nowhere"}) == [
            "scenarios[1].duplicateOf 'Nowhere' names no scenario earlier in this list"]
        assert errors_for({**base, "copies": {"shadows": "shadows_tall"}}) == [
            "scenarios[1].copies names no copy for 'chart'"]
        assert errors_for({**base, "copies": {**base["copies"], "extra": "x"}}) == [
            "scenarios[1].copies names 'extra', which 'Real heights' does not hold"]
        assert errors_for({**base, "copies": {"shadows": "compare", "chart": "chart_tall"}}) == [
            "scenarios[1].copies.shadows 'compare' is already a ref of this plan: a copy needs a ref of its own"]
        assert errors_for({**base, "values": {"shadows": {"height_factor": 2}}}) == [
            "scenarios[1].values.shadows: 'shadows' is not a copy this duplicate makes ('shadows_tall', 'chart_tall')"]
        assert errors_for({**base, "values": {"shadows_tall": {"height": 2}}}) == [
            "scenarios[1].values.shadows_tall.height: the node has no widget named 'height' (it has height_factor)"]
        assert errors_for({**base, "values": {"shadows_tall": {"height_factor": 9}}}) == [
            "scenarios[1].values.shadows_tall.height_factor: Enter a number from 0.5 to 4."]
        assert "needs copies" in errors_for({"name": "T", "duplicateOf": "Real heights", "values": {}})[0]

    def test_a_duplicate_copies_only_nodes_this_plan_adds(self):
        _, errors = _parse(_plan(scenarios=[
            {"name": "Mine", "nodes": ["existing-id"]},
            {"name": "Copy", "duplicateOf": "Mine", "copies": {"existing-id": "copy"}},
        ]))
        assert errors == ["scenarios[1]: 'Mine' holds 'existing-id', which is not a node this plan adds; "
                          "a duplicate copies the nodes this plan adds"]
