"""Dragging the scenarios of one set into another project one after the other
(#662). A card drags one scenario: the first of a set makes the set's copy in
the target, and each later one joins it.

``GET /<project>/<scenario>/copy?target=&present=a,b`` plans the drop of one
scenario where the target's copy of its set holds *present* already: its own
nodes, the context that crosses into what it copies, and the set's shared
outcomes that land with it, those whose every input is in once it is (a node
of it or of a scenario present, a context node arriving as data, or another
outcome landing or landed), less those the scenarios present brought before.
``POST`` copies the saved outputs, a shared outcome's own among them.

The project: a loader feeds three scenarios' nodes ``a``, ``b`` and ``c``.
``merge`` reads ``a`` and ``b`` and feeds ``chart_ab``; ``chart_abc`` reads all
three; ``map`` reads ``a`` and the loader.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_scenario_catalog/test_copy_set.py -v
"""
from __future__ import annotations

import json

from utk_curio.backend.tests.test_scenario_catalog.test_copy import _create, _headers, _node, _save_outputs


def _edge(source, target, handle="in"):
    return {"id": f"{source}-{target}", "source": source, "target": target, "sourceHandle": "out", "targetHandle": handle}


SHARED = ["merge", "chart_ab", "chart_abc", "map"]


def _spec():
    return {
        "dataflow": {
            "name": "Shadows",
            "nodes": [
                _node("load", "data-loading", "return 1"),
                _node("a", x=300),
                _node("b", x=300),
                _node("c", x=300),
                _node("merge", x=600),
                _node("chart_ab", "vis-vega", "{}", x=900),
                _node("chart_abc", "vis-vega", "{}", x=900),
                _node("map", x=600),
                _node("other", x=300),
            ],
            "edges": [
                _edge("load", "a"), _edge("load", "b"), _edge("load", "c"), _edge("load", "other"),
                _edge("a", "merge", "in_0"), _edge("b", "merge", "in_1"),
                _edge("merge", "chart_ab"),
                _edge("a", "chart_abc", "in_0"), _edge("b", "chart_abc", "in_1"), _edge("c", "chart_abc", "in_2"),
                _edge("a", "map", "in_0"), _edge("load", "map", "in_1"),
            ],
            "scenarioSets": [{"id": "park", "name": "Park shade"}, {"id": "else", "name": "Elsewhere"}],
            "scenarios": [
                {"id": "s1", "name": "Existing", "color": "#2a9d8f", "nodes": ["a"], "set": "park",
                 "context": ["load"], "outcomes": SHARED},
                {"id": "s2", "name": "Towers", "color": "#e76f51", "nodes": ["b"], "set": "park",
                 "context": ["load"], "outcomes": ["merge", "chart_ab", "chart_abc"]},
                {"id": "s3", "name": "Cap", "color": "#6a4c93", "nodes": ["c"], "set": "park",
                 "context": ["load"], "outcomes": ["chart_abc"]},
                {"id": "s4", "name": "Other", "color": "#264653", "nodes": ["other"], "set": "else",
                 "context": ["load"], "outcomes": []},
            ],
        }
    }


def _projects(client, token):
    source = _create(client, token, "Shadows", _spec())
    target = _create(client, token, "Target", {"dataflow": {"name": "Target", "nodes": [], "edges": []}})
    return source, target


def _plan(client, token, source, target, scenario, present=()):
    query = f"target={target}" + (f"&present={','.join(present)}" if present else "")
    return client.get(f"/api/scenarios/{source}/{scenario}/copy?{query}", headers=_headers(token))


def _shared(plan):
    return [entry["nodeId"] for entry in plan["shared"]]


def test_a_context_node_with_no_title_is_named_as_its_header_names_it(client, user_and_token):
    """The drop names the loader that stands for a context node after it, so
    the name is the node's own: its title, else its template's label ("JS
    Computation"), never its type in words ("Js Computation")."""
    _, token = user_and_token
    spec = {"dataflow": {
        "name": "Heights",
        "nodes": [_node("prep", "js-computation"), _node("a", x=300)],
        "edges": [_edge("prep", "a")],
        "scenarioSets": [{"id": "h", "name": "Heights"}],
        "scenarios": [{"id": "s1", "name": "Taller", "color": "#2a9d8f", "nodes": ["a"], "set": "h",
                       "context": ["prep"], "outcomes": []}],
    }}
    source = _create(client, token, "Heights", spec)
    target = _create(client, token, "Target", {"dataflow": {"name": "Target", "nodes": [], "edges": []}})
    _save_outputs(client, token, source, {"prep": "id\n1\n"})

    plan = _plan(client, token, source, target, "s1").get_json()

    assert [(entry["nodeId"], entry["label"]) for entry in plan["context"]] == [("prep", "JS Computation")]


def test_the_first_scenario_of_a_set_brings_only_the_shared_outcomes_it_feeds_alone(client, user_and_token):
    _, token = user_and_token
    source, target = _projects(client, token)
    _save_outputs(client, token, source, {"load": "id\n1\n"})

    plan = _plan(client, token, source, target, "s1").get_json()

    assert plan["problems"] == []
    assert plan["set"] == {"id": "park", "name": "Park shade"}
    assert plan["nodes"] == ["a"]
    assert [entry["nodeId"] for entry in plan["context"]] == ["load"]
    # The map reads a and the loader, which comes as data; merge waits for b.
    assert _shared(plan) == ["map"]
    assert plan["outcomes"] == SHARED
    assert [n["id"] for n in plan["dataflow"]["nodes"]] == ["a", "map"]


def test_a_later_scenario_joins_and_brings_the_shared_outcomes_that_land_now_once(client, user_and_token):
    _, token = user_and_token
    source, target = _projects(client, token)
    _save_outputs(client, token, source, {"load": "id\n1\n"})

    resp = _plan(client, token, source, target, "s2", ["s1"])

    assert resp.status_code == 200, resp.get_data(as_text=True)
    plan = resp.get_json()
    assert plan["problems"] == []
    assert plan["nodes"] == ["b"]
    # With a in, merge and its chart land; the map came with s1, and the chart
    # of all three waits for c.
    assert _shared(plan) == ["merge", "chart_ab"]
    assert {e["nodeId"]: e["scenarios"] for e in plan["shared"]} == {"merge": ["s2", "s1"], "chart_ab": ["s2", "s1"]}
    assert [entry["nodeId"] for entry in plan["context"]] == ["load"]
    assert [n["id"] for n in plan["dataflow"]["nodes"]] == ["b", "merge", "chart_ab"]
    # merge's edge from a comes from the copy of s1 that is there already.
    assert ("a", "merge") in {(e["source"], e["target"]) for e in plan["dataflow"]["edges"]}


def test_the_whole_set_one_after_another_brings_every_shared_outcome_once(client, user_and_token):
    _, token = user_and_token
    source, target = _projects(client, token)
    _save_outputs(client, token, source, {"load": "id\n1\n"})
    landed = []
    for scenario, present in (("s1", []), ("s2", ["s1"]), ("s3", ["s1", "s2"])):
        landed += _shared(_plan(client, token, source, target, scenario, present).get_json())
    assert sorted(landed) == sorted(SHARED)


def test_a_scenario_the_copy_holds_is_refused_and_an_unknown_one_is_not_found(client, user_and_token):
    _, token = user_and_token
    source, target = _projects(client, token)

    refused = _plan(client, token, source, target, "s1", ["s1"])
    assert refused.status_code == 409
    assert refused.get_json()["error"] == '"Existing" is already in the copy of "Park shade".'
    assert _plan(client, token, source, target, "s9").status_code == 404
    # A scenario of another set, or one no longer there, is not what the copy joins.
    assert _shared(_plan(client, token, source, target, "s1", ["s4", "gone"]).get_json()) == ["map"]


def test_a_drop_copies_its_last_nodes_and_an_outcomes_own_saved_outputs_and_no_other_scenarios_node(
    client, user_and_token,
):
    _, token = user_and_token
    source, target = _projects(client, token)
    _save_outputs(client, token, source, {"load": "id\n1\n", "a": "v\n1\n", "b": "v\n2\n", "merge": "v\n3\n"})
    plan = _plan(client, token, source, target, "s2", ["s1"]).get_json()
    merge = next(e for e in plan["shared"] if e["nodeId"] == "merge")
    assert merge["sources"] == ["merge"]
    # b, which merge and the chart of all three read, is its last node: it
    # shows its own saved output.
    assert plan["last"] == [{"nodeId": "b", "sources": ["b"]}]

    def copy(outputs):
        return client.post(
            f"/api/scenarios/{source}/s2/copy",
            data=json.dumps({"targetProjectId": target, "present": ["s1"], "outputs": outputs}),
            headers=_headers(token),
        )

    # A node of another scenario of the set is none this drop copies: its
    # saved output does not come.
    assert copy([{"source": "a", "node": "a-copy"}]).status_code == 400
    resp = copy([
        {"source": "load", "node": "load-copy"},
        {"source": "b", "node": "b-copy"},
        {"source": "merge", "node": "merge-copy"},
    ])
    assert resp.status_code == 200, resp.get_data(as_text=True)
    restored = {o["node_id"] for o in resp.get_json()["outputs"]}
    assert {"load-copy", "b-copy", "merge-copy"} <= restored
