"""An agent's changes on the canvas are its actions, one at a time.

``node.create``, a note among them, and each new node of a Dataflow Builder's
plan are dragged in from their template's tile by the agent at work in the
room, and land as the drop ends. A plan is checked whole, then lands a step at
a time under one change id: its removals with no motion, its nodes one by one,
then its connections, starters and scenarios once every node they join is
there. A node someone removes while the plan lands stops it there: what landed
stays, and the card says what was left undone. The plan's Undo puts back the
version before its first write, and is refused when someone changed the
dataflow between its writes. Two agents' queues play side by side, each in its
own order.

A tab is bound in every test (``dataflow_docs.has_tabs``), so drags are paced
as the room's tabs see them; the module's waits are recorded, never slept. What
the room is told (each drag as it starts and ends) and each write of the
dataflow are recorded in the order they happen. Names main lacks are read
inside each test, so a checkout without them fails test by test.
"""

from __future__ import annotations

import copy
import threading

from utk_curio.backend.tests.test_agents.test_agent_changes import (
    _ask,
    _by_id,
    _plan_tail,
    _saved,
    _setup,
    _tail,
    _the_card,
    _undo,
)
from utk_curio.backend.tests.test_agents.test_source_grounding_routes import _attach, _run

NB = "agent.curio.node-builder@1"
DFB = "agent.curio.dataflow-builder@1"
CA = "curio.builtin/computation-analysis"
#: How long the test waits for the other agent's queue before it fails.
WAIT_S = 20.0

#: Two new nodes, the loader replaced: Fetch feeds Clean, which feeds Sum.
PLAN = {
    "goal": "fetch and clean before the sum",
    "nodes": [
        {"ref": "a", "nodeType": CA, "title": "Fetch", "intent": "fetch the parks"},
        {"ref": "b", "nodeType": CA, "title": "Clean", "intent": "clean them"},
    ],
    "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "sum"}],
    "removeNodes": ["load"],
}


def _key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def _opened(user, project) -> int:
    """The dataflow's doc open, as a tab holds it, so its first points are
    the dataflow as it is: how many points it has."""
    from utk_curio.backend.app.collaboration import dataflow_docs, history

    with dataflow_docs._held(project, _key(user)):
        pass
    return len(history.points(_key(user), project))


def _paced(monkeypatch, *, on_wait=None) -> list:
    """A tab bound to the dataflow: drags and the second after a write are
    waited, each recorded and not slept, and *on_wait* called with how many
    waits came before. The waits, in order."""
    from utk_curio.backend.app.collaboration import agent_peers, dataflow_docs

    waits: list = []

    def wait(seconds):
        waits.append(seconds)
        if on_wait is not None:
            on_wait(len(waits) - 1)

    monkeypatch.setattr(dataflow_docs, "has_tabs", lambda project_id: True)
    monkeypatch.setattr(agent_peers, "_sleep", wait)
    return waits


def _graph(key: str, project: str) -> tuple:
    """The dataflow's nodes and connections now, by id and by their ends."""
    from utk_curio.backend.app.collaboration import dataflow_docs

    flow = dataflow_docs.live(key, project)["dataflow"]
    return (sorted(node["id"] for node in flow["nodes"]),
            sorted((edge["source"], edge["target"]) for edge in flow.get("edges") or []))


def _recording(monkeypatch, project: str, key: str, timeline: list) -> None:
    """Record, in order, each drag an agent's state shows as it starts (its
    ``carrying``, its ``pointer``, and on which thread) and as it ends, each
    write that changes the dataflow's nodes or connections (what it leaves,
    the change its history point names, and on which thread), and each
    agent's leave with what it did."""
    from utk_curio.backend.app.collaboration import dataflow_docs, room_state

    real_state, real_write, real_activity = dataflow_docs.set_agent_state, dataflow_docs.write, room_state.record_activity

    def set_agent_state(at_project, client_id, fields, *, joining=False):
        if at_project == project and "carrying" in fields:
            name = threading.current_thread().name
            if fields["carrying"]:
                timeline.append(("drag", copy.deepcopy(fields["carrying"]), copy.deepcopy(fields["pointer"]), name))
            else:
                timeline.append(("dropped", name))
        return real_state(at_project, client_id, fields, joining=joining)

    def write(user_key, project_id, spec, actor, **kwargs):
        if project_id != project:
            return real_write(user_key, project_id, spec, actor, **kwargs)
        before = _graph(key, project)
        written = real_write(user_key, project_id, spec, actor, **kwargs)
        after = _graph(key, project)
        if after != before:
            timeline.append(("write", *after, (kwargs.get("point") or {}).get("change"), threading.current_thread().name))
        return written

    def record_activity(room, kind, payload):
        if kind == "agent_left":
            timeline.append(("left", payload.get("name"), payload.get("did")))
        return real_activity(room, kind, payload)

    monkeypatch.setattr(dataflow_docs, "set_agent_state", set_agent_state)
    monkeypatch.setattr(dataflow_docs, "write", write)
    monkeypatch.setattr(room_state, "record_activity", record_activity)


def _person_writes(user, project, change) -> None:
    """A person's own change to the dataflow, through its doc, as their tab's
    edit reaches the server."""
    from utk_curio.backend.app.collaboration import dataflow_docs

    with dataflow_docs.writing(_key(user), project, dataflow_docs.person(user.id, "test")) as spec:
        change(spec["dataflow"])


def _code_of(node_id: str, code: str):
    def change(flow):
        next(node for node in flow["nodes"] if node["id"] == node_id)["content"] = code

    return change


def _without(node_id: str):
    def change(flow):
        flow["nodes"] = [node for node in flow["nodes"] if node["id"] != node_id]
        flow["edges"] = [edge for edge in flow.get("edges") or [] if node_id not in (edge["source"], edge["target"])]

    return change


def _plan_nodes(flow) -> dict:
    """The plan's new nodes in *flow*, by the title their goal starts with."""
    return {node["goal"].split(" ")[0]: node for node in flow["nodes"]
            if node.get("goal") and node["id"] not in ("load", "sum")}


def _only(timeline: list, *kinds) -> list:
    return [entry for entry in timeline if entry[0] in kinds]


def test_a_plan_lands_a_step_at_a_time_each_new_node_dragged_from_its_tile_as_its_drop_ends(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """The Dataflow Builder's plan replaces the loader with Fetch and Clean.
    Its removal lands first, with no drag; then Fetch is dragged from its tile
    in the Built-in palette to where its top-left lands, and lands as the drop
    ends, then Clean; then both connections land, with no drag. Each step is a
    point of the history naming the plan's one change, one after another, and
    Provenance lists the plan as one version. Its change event carries each
    step and the drag before it, for a canvas no doc binds, and the agent
    leaves saying what it did."""
    from utk_curio.backend.app.collaboration import history

    user, token = user_and_token
    project, att = _setup(client, user, token, coord=DFB)
    before = _opened(user, project)
    timeline: list = []
    _paced(monkeypatch)
    _recording(monkeypatch, project, _key(user), timeline)

    body, _calls = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(PLAN)])

    card = _the_card(body)
    change_id = card["changeId"]
    flow = _saved(client, token, project)
    planned = _plan_nodes(flow)
    assert set(planned) == {"Fetch", "Clean"}, flow["nodes"]
    fetch, clean = planned["Fetch"]["id"], planned["Clean"]["id"]
    steps = _only(timeline, "drag", "dropped", "write")
    drags = [entry for entry in steps if entry[0] == "drag"]
    assert [entry[1]["node"] for entry in drags] == [{"type": CA, "label": "Fetch"}, {"type": CA, "label": "Clean"}], (
        f"the plan's nodes were not dragged in, one after another in plan order: {steps}"
    )
    for (_, carrying, pointer, _thread), node_id in zip(drags, (fetch, clean)):
        assert (carrying["kind"], carrying["from"], carrying["ms"]) == (
            "add", {"palette": "builtin", "item": CA}, 500), carrying
        node = _by_id(flow)[node_id]
        assert (pointer["x"], pointer["y"]) == (node["x"], node["y"]), "a drag's drop is not where its node landed"
    shapes = [entry[:4] if entry[0] == "write" else entry[0] for entry in steps]
    assert shapes == [
        ("write", ["sum"], [], change_id),
        "drag", ("write", sorted(["sum", fetch]), [], change_id), "dropped",
        "drag", ("write", sorted(["sum", fetch, clean]), [], change_id), "dropped",
        ("write", sorted(["sum", fetch, clean]), sorted([(fetch, clean), (clean, "sum")]), change_id),
    ], f"the plan's steps did not land one at a time, in order: {steps}"

    points = history.points(_key(user), project)[before:]
    assert [point.get("change") for point in points] == [change_id] * 4, points
    assert all(point["by"]["kind"] == "agent" for point in points), points
    assert all(history.follows(_key(user), project, a, b) for a, b in zip(points, points[1:])), points
    listed = history.versions(_key(user), project)["versions"]
    plan_rows = [row for row in listed if row["id"] in {point["id"] for point in points}]
    assert [row["id"] for row in plan_rows] == [points[-1]["id"]], "Provenance lists the plan's steps one by one"
    assert plan_rows[0].get("parent") == points[0].get("parent"), plan_rows[0]

    [landed] = [entry for entry in body["changes"] if entry["tool"] == "dataflow.plan.write"]
    assert [step["canvas"]["step"] for step in landed["steps"]] == [0, 1, 2, 3], landed["steps"]
    assert [bool(step.get("dragged")) for step in landed["steps"]] == [False, True, True, False]
    dragged = landed["steps"][1]["dragged"]
    assert dragged["carrying"] == drags[0][1] and dragged["user"]["name"] == "Dataflow Builder", dragged
    assert sorted(node["id"] for node in landed["canvas"]["nodes"]) == sorted([fetch, clean])
    [left] = _only(timeline, "left")
    assert left[2] == {"removed": {"node": 1, "connection": 1}, "added": {"node": 2, "connection": 2}}, left


def test_a_plans_undo_puts_back_the_version_before_its_first_write(client, user_and_token, tmp_curio, monkeypatch):
    """The plan landed in four writes, each a point naming its change. Its
    Undo puts back the version the first one was made from: the loader and its
    connection come back, Fetch and Clean go."""
    from utk_curio.backend.app.collaboration import history

    user, token = user_and_token
    project, att = _setup(client, user, token, coord=DFB)
    _opened(user, project)
    _paced(monkeypatch)
    body, _calls = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(PLAN)])
    card = _the_card(body)
    steps = [point for point in history.points(_key(user), project) if point.get("change") == card["changeId"]]
    assert len(steps) == 4, f"the plan did not land a step at a time: {steps}"

    undone = _undo(client, token, project, att, card["changeId"])

    assert undone.status_code == 200, undone.get_json()
    flow = _saved(client, token, project)
    assert set(_by_id(flow)) == {"load", "sum"}, flow["nodes"]
    assert [(edge["source"], edge["target"]) for edge in flow["edges"]] == [("load", "sum")]
    [put_back] = [point for point in history.points(_key(user), project) if point.get("kind") == "putBack"]
    assert put_back["restores"] == steps[0]["parent"], (put_back, steps[0])


def test_a_plans_undo_is_refused_when_someone_changed_the_dataflow_between_its_writes(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """While the agent drags Clean in, alice writes Sum's code herself. The
    plan lands around her change; its Undo would put back the version before
    its first write and erase her code, so it is refused, and nothing
    changes."""
    user, token = user_and_token
    project, att = _setup(client, user, token, coord=DFB)
    _opened(user, project)
    edited: list = []

    def during_the_second_drag(waited: int) -> None:
        if waited == 1:
            _person_writes(user, project, _code_of("sum", "return 7  # alice, while the plan landed"))
            edited.append(waited)

    _paced(monkeypatch, on_wait=during_the_second_drag)
    body, _calls = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(PLAN)])
    card = _the_card(body)
    assert edited == [1], "alice's change did not come between the plan's writes"

    refused = _undo(client, token, project, att, card["changeId"])

    assert refused.status_code == 409, refused.get_json()
    assert refused.get_json()["error"].endswith("changed this dataflow after; nothing was undone."), refused.get_json()
    flow = _saved(client, token, project)
    assert _by_id(flow)["sum"]["content"] == "return 7  # alice, while the plan landed"
    assert set(_plan_nodes(flow)) == {"Fetch", "Clean"}, "the refused Undo changed the dataflow"


def test_a_node_removed_while_the_plan_lands_stops_it_and_its_card_says_what_was_left_undone(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """While the agent drags Fetch in, alice removes Sum, which the plan's
    last step connects Clean to. Fetch and Clean still land, each as its drop
    ends; the connections do not, since a node they join is gone: none of
    them lands, so nothing is half wired. The card, the chat's line, says what
    was left undone, before the Topology verdict it ends with."""
    from utk_curio.backend.app.collaboration import history

    user, token = user_and_token
    project, att = _setup(client, user, token, coord=DFB)
    _opened(user, project)
    removed: list = []

    def during_the_first_drag(waited: int) -> None:
        if waited == 0:
            _person_writes(user, project, _without("sum"))
            removed.append(waited)

    _paced(monkeypatch, on_wait=during_the_first_drag)
    body, _calls = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(PLAN)])

    assert removed == [0], "alice did not remove Sum while the plan landed"
    card = _the_card(body)
    assert card["status"] == "applied", card
    assert "Left undone: 2 connections, since 'Sum them' was removed" in card["lines"], card["lines"]
    assert card["lines"][-1].startswith("Topology"), card["lines"]
    flow = _saved(client, token, project)
    assert set(_plan_nodes(flow)) == {"Fetch", "Clean"} and "sum" not in _by_id(flow), flow["nodes"]
    assert flow["edges"] == [], f"a connection of the stopped plan landed: {flow['edges']}"
    steps = [point for point in history.points(_key(user), project) if point.get("change") == card["changeId"]]
    assert len(steps) == 3, f"the removal and the two nodes are the steps that landed: {steps}"


def test_node_create_is_dragged_from_its_tile_and_lands_as_its_drop_ends(client, user_and_token, tmp_curio, monkeypatch):
    """The Node Builder adds a node: its state carries the drag from the
    template's tile in the Built-in palette to where the node's top-left
    lands, the node lands as the drop ends, and the change event carries the
    same drag, for a canvas no doc binds."""
    user, token = user_and_token
    project, att = _setup(client, user, token)
    timeline: list = []
    waits = _paced(monkeypatch)
    _recording(monkeypatch, project, _key(user), timeline)

    body, _calls = _ask(client, token, project, att, monkeypatch,
                        [_tail("node.create", nodeType=CA, content="return 2"), "Added."])

    [landed] = body["changes"]
    new_id = landed["canvas"]["node"]["id"]
    node = _by_id(_saved(client, token, project))[new_id]
    steps = _only(timeline, "drag", "dropped", "write")
    assert [entry[0] for entry in steps] == ["drag", "write", "dropped"], (
        f"the new node was not dragged in before it landed: {steps}"
    )
    _, carrying, pointer, _thread = steps[0]
    assert (carrying["kind"], carrying["from"], carrying["node"]["type"]) == (
        "add", {"palette": "builtin", "item": CA}, CA), carrying
    assert (pointer["x"], pointer["y"]) == (node["x"], node["y"]), (pointer, node)
    assert new_id in steps[1][1], "the write after the drag is not the new node's"
    assert waits[0] == 0.5, waits
    [step] = landed["steps"]
    assert step["dragged"]["carrying"] == carrying and step["canvas"]["node"]["id"] == new_id, step


def test_two_agents_queues_play_side_by_side_each_in_its_own_order(client, user_and_token, tmp_curio, monkeypatch):
    """The Dataflow Builder lands its plan while the Node Builder adds two
    nodes of its own, both asked at once. Each agent's drags start only once
    its last one dropped, in its own order and carrying only its own nodes,
    while the other agent's drags go on beside them; the plan's points all
    name the plan, and neither agent's node lands in the other's change."""
    from utk_curio.backend.app.collaboration import history

    user, token = user_and_token
    project, planner = _setup(client, user, token, coord=DFB)
    builder = _attach(client, token, project, NB, target={"kind": "node", "targetId": "sum"})
    before = _opened(user, project)
    replies = {
        "planner": ["Here.\n" + _plan_tail(PLAN)],
        "builder": [_tail("node.create", nodeType=CA, content="return 'one'", title="One"),
                    _tail("node.create", nodeType=CA, content="return 'two'", title="Two"), "Added two."],
    }

    def answer(config, messages, **kwargs):
        from utk_curio.backend.app.agents.application.turns import titles

        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        return replies[threading.current_thread().name].pop(0)

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", answer)
    started = {name: threading.Event() for name in replies}

    def side_by_side(_waited: int) -> None:
        name = threading.current_thread().name
        started[name].set()
        other = next(n for n in replies if n != name)
        assert started[other].wait(WAIT_S), f"the {other}'s queue never began while the {name}'s played"

    _paced(monkeypatch, on_wait=side_by_side)
    timeline: list = []
    _recording(monkeypatch, project, _key(user), timeline)
    bodies: dict = {}

    def ask(name, att, message):
        response = _run(client, token, project, att, message)
        bodies[name] = (response.status_code, response.get_json())

    threads = [threading.Thread(target=ask, args=("planner", planner, "plan it"), name="planner", daemon=True),
               threading.Thread(target=ask, args=("builder", builder, "add two"), name="builder", daemon=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
        assert not thread.is_alive(), f"the {thread.name}'s run never ended"

    assert {name: status for name, (status, _body) in bodies.items()} == {"planner": 200, "builder": 200}, bodies
    moves = _only(timeline, "drag", "dropped")
    by_agent = {name: [entry for entry in moves if entry[-1] == name] for name in replies}
    assert [entry[1]["node"]["label"] for entry in by_agent["planner"] if entry[0] == "drag"] == ["Fetch", "Clean"]
    assert [entry[1]["node"]["label"] for entry in by_agent["builder"] if entry[0] == "drag"] == ["One", "Two"]
    for name, own in by_agent.items():
        assert [entry[0] for entry in own] == ["drag", "dropped", "drag", "dropped"], (
            f"the {name}'s drags overlapped each other: {own}"
        )
    firsts = [moves.index(by_agent[name][0]) for name in replies]
    firsts_dropped = [moves.index(by_agent[name][1]) for name in replies]
    assert max(firsts) < min(firsts_dropped), f"the two agents' drags did not play side by side: {moves}"
    # The plan is one change, all of it the planner's; the builder's nodes are changes of its own.
    card = _the_card(bodies["planner"][1])
    plan_points = [point for point in history.points(_key(user), project)[before:]
                   if point.get("change") == card["changeId"]]
    assert len(plan_points) == 4, plan_points
    plan_writes = [entry for entry in _only(timeline, "write") if entry[3] == card["changeId"]]
    assert len(plan_writes) == 4 and {entry[4] for entry in plan_writes} == {"planner"}, plan_writes
    builder_writes = [entry for entry in _only(timeline, "write") if entry[4] == "builder"]
    assert len(builder_writes) == 2 and {entry[3] for entry in builder_writes} == {None}, builder_writes
    builder_cards = [part for part in bodies["builder"][1]["content"] if part["type"] == "change"]
    assert [part["kind"] for part in builder_cards] == ["node", "node"], builder_cards
    assert card["changeId"] not in {part["changeId"] for part in builder_cards}
    flow = _saved(client, token, project)
    assert set(_plan_nodes(flow)) == {"Fetch", "Clean"}, flow["nodes"]
    assert sorted(node.get("title") for node in flow["nodes"] if node.get("title") in ("One", "Two")) == ["One", "Two"]
