"""Dragging several scenarios of one set into another project at once (#662).

``GET /sets/<project>/<set>/copy?target=&scenarios=a,b`` plans the drop of
the scenarios named, all of the set: their levers, the context they read,
once, and the set's shared outcomes whose every input comes too (a dragged
scenario's node, a context node arriving as data, or another outcome that
comes). ``POST`` copies the saved outputs, an outcome's own among them.

The project: a loader feeds three scenarios' levers ``a``, ``b`` and ``c``.
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


def _plan(client, token, source, target, ids, set_id="park"):
    return client.get(
        f"/api/scenarios/sets/{source}/{set_id}/copy?target={target}&scenarios={','.join(ids)}",
        headers=_headers(token),
    )


def _shared(plan):
    return [entry["nodeId"] for entry in plan["shared"]]


def test_two_scenarios_bring_their_context_once_and_the_outcomes_they_feed_whole(client, user_and_token):
    _, token = user_and_token
    source, target = _projects(client, token)
    _save_outputs(client, token, source, {"load": "id\n1\n"})

    resp = _plan(client, token, source, target, ["s1", "s2"])

    assert resp.status_code == 200, resp.get_data(as_text=True)
    plan = resp.get_json()
    assert plan["problems"] == []
    assert plan["set"] == {"id": "park", "name": "Park shade"}
    assert plan["levers"] == ["a", "b"]
    [load] = plan["context"]
    assert (load["nodeId"], load["scenarios"]) == ("load", ["s1", "s2"])
    # merge and its chart read a and b alone; the map reads a and the loader,
    # which comes as data. The chart of all three would miss c.
    assert _shared(plan) == ["merge", "chart_ab", "map"]
    assert {e["nodeId"]: e["scenarios"] for e in plan["shared"]} == {
        "merge": ["s1", "s2"], "chart_ab": ["s1", "s2"], "map": ["s1"],
    }
    assert [s["id"] for s in plan["scenarios"]] == ["s1", "s2"]
    assert plan["scenarios"][0]["name"] == "Existing"
    assert plan["scenarios"][1]["outcomes"] == ["merge", "chart_ab"]
    assert {n["id"] for n in plan["dataflow"]["nodes"]} == {"a", "b", "merge", "chart_ab", "map"}


def test_one_scenario_brings_only_the_outcomes_it_feeds_alone(client, user_and_token):
    _, token = user_and_token
    source, target = _projects(client, token)
    _save_outputs(client, token, source, {"load": "id\n1\n"})
    plan = _plan(client, token, source, target, ["s1"]).get_json()
    assert _shared(plan) == ["map"]


def test_the_whole_set_brings_every_shared_outcome(client, user_and_token):
    _, token = user_and_token
    source, target = _projects(client, token)
    _save_outputs(client, token, source, {"load": "id\n1\n"})
    plan = _plan(client, token, source, target, ["s1", "s2", "s3"]).get_json()
    assert _shared(plan) == SHARED
    assert plan["context"][0]["scenarios"] == ["s1", "s2", "s3"]


def test_scenarios_of_two_sets_are_refused_and_an_unknown_one_is_not_found(client, user_and_token):
    _, token = user_and_token
    source, target = _projects(client, token)
    assert _plan(client, token, source, target, ["s1", "s4"]).status_code == 400
    assert _plan(client, token, source, target, ["s4"]).status_code == 400
    assert _plan(client, token, source, target, ["s9"]).status_code == 404
    assert _plan(client, token, source, target, []).status_code == 400


def test_a_drop_copies_an_outcomes_own_saved_output(client, user_and_token):
    _, token = user_and_token
    source, target = _projects(client, token)
    _save_outputs(client, token, source, {"load": "id\n1\n", "a": "v\n1\n", "b": "v\n2\n", "merge": "v\n3\n"})
    plan = _plan(client, token, source, target, ["s1", "s2"]).get_json()
    merge = next(e for e in plan["shared"] if e["nodeId"] == "merge")
    assert merge["sources"] == ["merge"]

    resp = client.post(
        f"/api/scenarios/sets/{source}/park/copy",
        data=json.dumps({
            "targetProjectId": target,
            "scenarioIds": ["s1", "s2"],
            "outputs": [
                {"source": "load", "node": "load-copy"},
                {"source": "a", "node": "a-copy"},
                {"source": "b", "node": "b-copy"},
                {"source": "merge", "node": "merge-copy"},
            ],
        }),
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    restored = {o["node_id"] for o in resp.get_json()["outputs"]}
    assert {"a-copy", "b-copy", "merge-copy"} <= restored
