"""Where an agent puts the nodes it adds (#499, #410).

The steps were 420 px across and 240 down, less than a node's own 525 x 350,
so a created node covered the right edge of the rightmost one, and an applied
plan stacked its columns and rows over each other.
"""
from utk_curio.backend.app.agents.application.proposals import apply, plans


def _spec(*nodes):
    return {"dataflow": {"nodes": list(nodes), "edges": []}}


def test_a_created_node_lands_a_gutter_past_the_rightmost_node():
    spec = _spec({"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 645, "y": 430})
    created = apply._insert_node(spec, "curio.builtin/data-loading", "", None)
    assert (created["x"], created["y"]) == (645 + 525 + 120, 430)


def test_a_wide_node_is_stepped_past_at_its_own_width():
    spec = _spec({"id": "a", "x": 0, "y": 0}, {"id": "wide", "x": 300, "y": 90, "width": 900})
    created = apply._insert_node(spec, "curio.builtin/data-loading", "", None)
    # The wide node's right edge (1200) is further out than the other one's.
    assert (created["x"], created["y"]) == (300 + 900 + 120, 90)


def test_an_empty_canvas_uses_the_default_spot():
    created = apply._insert_node(_spec(), "curio.builtin/data-loading", "", None)
    assert (created["x"], created["y"]) == apply._NODE_PLACEMENT_DEFAULT


def test_plan_steps_are_a_node_and_a_gutter():
    assert plans._PLAN_COLUMN_OFFSET == 525 + 120
    assert plans._PLAN_ROW_OFFSET == 350 + 80
