"""An agent's change lands at once, as a person's edit does, and the chat's Undo takes it back by kind.

``proposals/changes.py``: a node's code, its settings, a new node and a plan land
as soon as their checks pass, as the agent's change, with no review; an install
(a package, a dataset, a Discovery download, an agent) still waits for the
person who asked. Undo is a person's change, by kind, through the history's
checked writes, and refused, with nothing changed, when someone changed what it
would put back. A change that would land on a node a person holds waits for
them first. The settings kind is in ``test_node_settings_write.py``; Build &
validate over a landed plan is in ``test_routes_solve.py``.

Each test imports what main lacks inside itself, so a before-run fails test by
test.
"""
from __future__ import annotations

import json

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_map_edits_grounding import _write_tail
from utk_curio.backend.tests.test_agents.test_routes_proposals import TestNodeCreate
from utk_curio.backend.tests.test_agents.test_routes_turns import TestReuseLadder
from utk_curio.backend.tests.test_agents.test_source_grounding_routes import (
    _attach,
    _install,
    _run,
    _script,
    _tool_results,
)

NB = "agent.curio.node-builder@1"
DFB = "agent.curio.dataflow-builder@1"
CA = "curio.builtin/python-computation"


def _nodes() -> list[dict]:
    return [
        {"id": "load", "type": CA, "title": "Load", "goal": "Load the parks", "content": "return 1", "x": 0, "y": 0},
        {"id": "sum", "type": CA, "title": "Sum", "goal": "Sum them", "content": "return input_0", "x": 400, "y": 0},
    ]


def _edges() -> list[dict]:
    return [{"id": "e1", "source": "load", "target": "sum", "sourceHandle": "out", "targetHandle": "in"}]


def _tail(tool: str, **params) -> str:
    return "```curio.v1\n" + json.dumps({"toolRequest": {"tool": tool, "params": params}}) + "\n```"


def _plan_tail(plan: dict) -> str:
    return "```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"


def _project(client, user, token, nodes, edges, task=None) -> str:
    """A dataflow of *nodes* and *edges*, and the goal *task* when given, on
    the test templates the plan and node tests use (``TestNodeCreate``)."""
    from utk_curio.backend.app.projects.services import _user_dir_key

    TestNodeCreate()._write_builtin_package(_user_dir_key(user))
    dataflow = {"nodes": nodes, "edges": list(edges), "packages": [], **({"task": task} if task is not None else {})}
    created = client.post("/api/projects", headers=_auth(token), json={
        "name": "p", "spec": {"dataflow": dataflow}, "outputs": [],
    })
    assert created.status_code == 201, created.get_data(as_text=True)
    return created.get_json()["id"]


def _setup(client, user, token, coord=NB, target=None, nodes=None, edges=None, task=None):
    project = _project(client, user, token, nodes if nodes is not None else _nodes(),
                       edges if edges is not None else _edges(), task)
    _install(client, token, project, *dict.fromkeys((coord, NB)))
    att = _attach(client, token, project, coord, target=target)
    return project, att


def _ask(client, token, project, att, monkeypatch, replies, message="do it"):
    calls = _script(monkeypatch, replies)
    body = _run(client, token, project, att, message)
    return body, calls


def _cards(body) -> list[dict]:
    return [p for p in body["content"] if p["type"] == "change"]


def _the_card(body) -> dict:
    """The turn's one change card; the parts it holds instead when it has none."""
    cards = _cards(body)
    assert len(cards) == 1, [p["type"] for p in body["content"]]
    return cards[0]


def _proposals(body) -> list[dict]:
    return [p for p in body["content"] if p["type"] == "proposal"]


def _saved(client, token, project) -> dict:
    opened = client.get(f"/api/projects/{project}", headers=_auth(token))
    assert opened.status_code == 200, opened.get_data(as_text=True)
    return opened.get_json()["spec"]["dataflow"]


def _by_id(flow) -> dict:
    return {node["id"]: node for node in flow["nodes"]}


def _undo(client, token, project, att, change_id):
    return client.post(f"/api/agents/projects/{project}/attachments/{att}/changes/{change_id}/undo",
                       headers=_auth(token))


def _listing(client, token, project, att) -> dict:
    cards = client.get(f"/api/agents/projects/{project}/attachments", headers=_auth(token)).get_json()
    return next(c for c in cards["attachments"] if c["attachmentId"] == att)


def _user_edits(client, token, project, nodes, edges=()):
    """The person's own edit, saved as the canvas saves it."""
    saved = client.put(f"/api/projects/{project}", headers=_auth(token), json={
        "name": "p", "spec": {"dataflow": {"nodes": nodes, "edges": list(edges), "packages": []}}, "outputs": [],
    })
    assert saved.status_code == 200, saved.get_data(as_text=True)


def _person_writes(user, project, change) -> None:
    """The person's own change to the dataflow: *change* made to its
    ``dataflow`` and written in its doc as a tab's edit is. Never through
    ``_user_edits``, whose save sends no goal."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects.services import _user_dir_key

    key = _user_dir_key(user)
    spec = dataflow_docs.live(key, project)
    change(spec["dataflow"])
    dataflow_docs.write(key, project, spec, dataflow_docs.person(key, "edit"))


def _person_sets_the_goal(user, project, goal: str) -> None:
    """The person writes *goal* on the Goal line: the dataflow's ``task``."""
    _person_writes(user, project, lambda flow: flow.update(task=goal))


def _renamed(scenario_id: str, name: str):
    """The person's change that renames the scenario *scenario_id* to *name*,
    for :func:`_person_writes`."""
    def change(flow):
        for scenario in flow.get("scenarios") or []:
            if scenario.get("id") == scenario_id:
                scenario["name"] = name
    return change


def _note() -> dict:
    """A node with no connections, which a person's scenario can hold."""
    return {"id": "note", "type": CA, "title": "Note", "goal": "Keep a note", "content": "return 0", "x": 800, "y": 0}


def _mutations(step: dict) -> list[dict]:
    """A landed step's canvas mutations: one, or a list when the step also
    gave nodes their starters."""
    canvas = step["canvas"]
    return canvas if isinstance(canvas, list) else [canvas]


class TestEachFamilyLandsAtOnce:
    def test_a_nodes_code_lands_with_no_review(self, client, user_and_token, tmp_curio, monkeypatch):
        from utk_curio.backend.app.agents.application.proposals import changes  # noqa: F401 - what main lacks

        user, token = user_and_token
        project, att = _setup(client, user, token, target={"kind": "node", "targetId": "sum"})
        body, calls = _ask(client, token, project, att, monkeypatch,
                           [_write_tail("sum", "return input_0.sum()"), "Written."])
        assert _proposals(body) == []
        card = _the_card(body)
        assert (card["kind"], card["status"], card["nodeId"]) == ("content", "applied", "sum")
        assert card["preview"] == "return input_0.sum()"
        assert _by_id(_saved(client, token, project))["sum"]["content"] == "return input_0.sum()"
        [said] = _tool_results(calls[-1], "node.content.write")
        assert said.startswith("[tool result] node.content.write: applied"), said
        # No review waits: the listing has none.
        assert (_listing(client, token, project, att).get("activeProposal") or {}).get("status") != "pending"
        # A canvas no doc binds takes the code, named after the agent.
        assert [entry["canvas"] for entry in body["changes"]] == [{
            "kind": "node-content-applied", "nodeId": "sum", "content": "return input_0.sum()", "agent": "Node Builder",
        }]

    def test_a_new_node_lands_with_no_review(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att = _setup(client, user, token)
        body, _ = _ask(client, token, project, att, monkeypatch,
                       [_tail("node.create", nodeType=CA, content="return 2"), "Added."])
        card = _the_card(body)
        assert card["kind"] == "node"
        [landed] = body["changes"]
        assert landed["canvas"]["kind"] == "node-created"
        new_id = landed["canvas"]["node"]["id"]
        assert _by_id(_saved(client, token, project))[new_id]["content"] == "return 2"

    def test_a_plan_lands_a_step_at_a_time_as_one_change_its_removals_nodes_and_connections(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        from utk_curio.backend.app.collaboration import dataflow_docs, history
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        # The doc open, as a tab holds it: its first points are the dataflow
        # as it is, so what follows is the plan's alone. A read of the spec
        # opens no doc no one holds (``dataflow_docs.live`` reads the file).
        with dataflow_docs._held(project, _user_dir_key(user)):
            pass
        before = len(history.points(_user_dir_key(user), project))
        assert before, "the open made no first points"
        head = history.points(_user_dir_key(user), project)[-1]["id"]
        plan = {
            "goal": "replace the loader",
            "nodes": [{"ref": "a", "nodeType": CA, "title": "API Fetch", "intent": "fetch from the api"}],
            "edges": [{"from": "a", "to": "sum"}],
            "removeNodes": ["load"],
        }
        body, calls = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(plan)])
        assert _proposals(body) == []
        card = _the_card(body)
        assert card["kind"] == "plan" and card["planId"]
        flow = _saved(client, token, project)
        ids = _by_id(flow)
        assert "load" not in ids
        [new_id] = [node_id for node_id in ids if node_id != "sum"]
        assert ids[new_id]["content"] == ""
        assert [(e["source"], e["target"]) for e in flow["edges"]] == [(new_id, "sum")]
        # One point of the history a step, the removal, the node, the
        # connection, each the agent's and naming the plan's one change, one
        # right after another, the first made from the version before it.
        points = history.points(_user_dir_key(user), project)
        assert len(points) == before + 3, points[before:]
        steps = points[before:]
        assert all(point["by"]["kind"] == "agent" for point in steps), steps
        assert all(point.get("change") == card["changeId"] for point in steps), steps
        assert all(history.follows(_user_dir_key(user), project, a, b) for a, b in zip(steps, steps[1:])), steps
        assert steps[0]["parent"] == head, (steps[0], head)
        # The planner's session holds the plan its Build & validate works on.
        listing = _listing(client, token, project, att)
        assert listing["planProposal"]["proposalId"] == card["planId"]
        assert listing["planProposal"]["status"] == "applied"
        assert listing["planProposal"]["appliedRefs"] == ["a"]
        assert listing["builderSession"]["nodeStates"] == {"a": "created"}
        # Its card carries the topology verdict the agent confirms a fix by.
        assert "Topology" in json.dumps(card["lines"]), card["lines"]

    def test_an_install_still_waits_for_review(self, client, user_and_token, tmp_curio, monkeypatch):
        from utk_curio.backend.app.agents.application import editors
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        project, att = _setup(client, user, token)
        TestReuseLadder()._write_store_package(_user_dir_key(user), "curio.notes@1", "curio.notes", "note-surface", "Note")
        body, _ = _ask(client, token, project, att, monkeypatch,
                       [_tail("package.install", dirName="curio.notes@1", reason="notes need it"), "It needs a package."])
        assert _cards(body) == []
        [proposal] = _proposals(body)
        assert (proposal["tool"], proposal["status"]) == ("package.install", "pending")
        assert "changes" not in body
        # The installs that wait are the account's, read from one contract.
        assert "package.install" in editors.ACCOUNT_INSTALL_TOOLS


class TestUndoByKind:
    def _content(self, client, user, token, monkeypatch):
        project, att = _setup(client, user, token, target={"kind": "node", "targetId": "sum"})
        body, _ = _ask(client, token, project, att, monkeypatch,
                       [_write_tail("sum", "return input_0.sum()"), "Written."])
        card = _the_card(body)
        return project, att, card

    def test_undo_gives_a_nodes_code_its_before_back(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att, card = self._content(client, user, token, monkeypatch)
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        assert undone.get_json()["status"] == "undone"
        assert _by_id(_saved(client, token, project))["sum"]["content"] == "return input_0"
        [canvas] = undone.get_json()["canvas"]
        assert (canvas["kind"], canvas["nodeId"], canvas["content"]) == ("node-content-applied", "sum", "return input_0")
        assert canvas["agent"] == "Undid Node Builder's change"

    def test_undo_of_code_someone_changed_after_is_refused_and_keeps_theirs(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project, att, card = self._content(client, user, token, monkeypatch)
        nodes = _nodes()
        nodes[1]["content"] = "return input_0.mean()"
        _user_edits(client, token, project, nodes, _edges())
        refused = _undo(client, token, project, att, card["changeId"])
        assert refused.status_code == 409, refused.get_json()
        assert "changed this node after; nothing was undone." in refused.get_json()["error"]
        assert _by_id(_saved(client, token, project))["sum"]["content"] == "return input_0.mean()"

    def test_undo_takes_a_new_node_away_with_its_connections(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att = _setup(client, user, token)
        body, _ = _ask(client, token, project, att, monkeypatch,
                       [_tail("node.create", nodeType=CA, content="return 2"), "Added."])
        card = _the_card(body)
        new_id = body["changes"][0]["canvas"]["node"]["id"]
        flow = _saved(client, token, project)
        # The person connects it before the Undo.
        _user_edits(client, token, project, flow["nodes"],
                    _edges() + [{"id": "e2", "source": new_id, "target": "sum", "sourceHandle": "out", "targetHandle": "in"}])
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        flow = _saved(client, token, project)
        assert set(_by_id(flow)) == {"load", "sum"}
        assert [e["id"] for e in flow["edges"]] == ["e1"]
        assert undone.get_json()["canvas"] == [{
            "kind": "plan-removals", "planId": f"undo:{card['changeId']}", "removedNodeIds": [new_id],
            "removedEdgeIds": ["e2"],
        }]

    def test_undo_of_a_new_node_someone_wrote_in_is_refused(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att = _setup(client, user, token)
        body, _ = _ask(client, token, project, att, monkeypatch,
                       [_tail("node.create", nodeType=CA, content="return 2"), "Added."])
        card = _the_card(body)
        new_id = body["changes"][0]["canvas"]["node"]["id"]
        flow = _saved(client, token, project)
        for node in flow["nodes"]:
            if node["id"] == new_id:
                node["content"] = "return 3  # mine"
        _user_edits(client, token, project, flow["nodes"], flow["edges"])
        refused = _undo(client, token, project, att, card["changeId"])
        assert refused.status_code == 409, refused.get_json()
        assert "nothing was undone" in refused.get_json()["error"]
        assert new_id in _by_id(_saved(client, token, project))

    def _plan(self, client, user, token, monkeypatch):
        project, att = _setup(client, user, token, coord=DFB)
        plan = {
            "goal": "replace the loader",
            "nodes": [{"ref": "a", "nodeType": CA, "title": "API Fetch", "intent": "fetch from the api"}],
            "edges": [{"from": "a", "to": "sum"}],
            "removeNodes": ["load"],
        }
        body, _ = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(plan)])
        card = _the_card(body)
        return project, att, card

    def test_undo_of_a_plan_puts_back_the_version_before_it_removed_nodes_and_their_connections_included(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project, att, card = self._plan(client, user, token, monkeypatch)
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        flow = _saved(client, token, project)
        assert _by_id(flow)["load"]["content"] == "return 1"
        assert set(_by_id(flow)) == {"load", "sum"}
        assert [(e["source"], e["target"]) for e in flow["edges"]] == [("load", "sum")]
        # The planner holds no plan any more: nothing is left to build.
        listing = _listing(client, token, project, att)
        assert listing.get("planProposal") is None
        [canvas] = undone.get_json()["canvas"]
        assert canvas["kind"] == "graph-created"
        assert [n["id"] for n in canvas["nodes"]] == ["load"]

    def test_undo_of_a_plan_someone_changed_around_after_is_refused(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project, att, card = self._plan(client, user, token, monkeypatch)
        flow = _saved(client, token, project)
        for node in flow["nodes"]:
            if node["id"] == "sum":
                node["content"] = "return input_0.max()  # after the plan"
        _user_edits(client, token, project, flow["nodes"], flow["edges"])
        refused = _undo(client, token, project, att, card["changeId"])
        assert refused.status_code == 409, refused.get_json()
        assert "changed this dataflow after; nothing was undone." in refused.get_json()["error"]
        assert _by_id(_saved(client, token, project))["sum"]["content"] == "return input_0.max()  # after the plan"

    def test_undo_of_a_plan_leaves_the_goal_someone_changed_after(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """The dataflow's goal is not the plan's: a goal changed after a plan
        that did not set it leaves the plan's Undo free, and the Undo leaves
        the goal as it is now. On main the Undo was refused (409) when only
        the goal had changed."""
        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        _person_sets_the_goal(user, project, "Map the parks")
        plan = {
            "goal": "replace the loader",
            "nodes": [{"ref": "a", "nodeType": CA, "title": "API Fetch", "intent": "fetch from the api"}],
            "edges": [{"from": "a", "to": "sum"}],
            "removeNodes": ["load"],
        }
        body, _ = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(plan)])
        card = _the_card(body)
        assert _saved(client, token, project)["task"] == "Map the parks"
        _person_sets_the_goal(user, project, "Map the parks in the shade")
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        flow = _saved(client, token, project)
        assert set(_by_id(flow)) == {"load", "sum"}
        assert [(e["source"], e["target"]) for e in flow["edges"]] == [("load", "sum")]
        assert flow["task"] == "Map the parks in the shade"

    def _plan_with_a_write_while_it_lands(self, client, user, token, monkeypatch, change):
        """A plan landed on an empty goal while the person's *change* to the
        dataflow landed between the plan's first write and its next: the
        project, the attachment, the plan's card and the dataflow as it was
        before the plan."""
        from utk_curio.backend.app.agents.application import in_the_room
        from utk_curio.backend.app.collaboration import history
        from utk_curio.backend.app.projects.services import _user_dir_key

        project, att = _setup(client, user, token, coord=DFB)
        before = _saved(client, token, project)
        act = in_the_room.act
        between: list = []

        def acting(peer, action, **kwargs):
            acted = act(peer, action, **kwargs)
            if acted.landed and not between:
                between.append(action.what)
                _person_writes(user, project, change)
            return acted

        monkeypatch.setattr(in_the_room, "act", acting)
        plan = {
            "goal": "replace the loader",
            "nodes": [{"ref": "a", "nodeType": CA, "title": "API Fetch", "intent": "fetch from the api"}],
            "edges": [{"from": "a", "to": "sum"}],
            "removeNodes": ["load"],
        }
        body, _ = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(plan)])
        card = _the_card(body)
        # The person's write came between the plan's first two writes.
        key = _user_dir_key(user)
        points = [p for p in history.points(key, project) if p.get("change") == card["changeId"]]
        assert len(points) == 3 and not history.follows(key, project, points[0], points[1]), (between, points)
        assert "load" not in _by_id(_saved(client, token, project))
        return project, att, card, before

    def test_undo_of_a_plan_leaves_a_goal_saved_while_it_landed(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """A goal saved between two of the plan's writes never holds its Undo
        back either: the Undo takes the plan away, leaves that goal as it is,
        and puts back the rest of the dataflow as it was before the plan. On
        main the Undo was refused (409)."""
        user, token = user_and_token
        project, att, card, before = self._plan_with_a_write_while_it_lands(
            client, user, token, monkeypatch, lambda flow: flow.update(task="Map the parks in the shade"),
        )
        assert _saved(client, token, project)["task"] == "Map the parks in the shade"
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        flow = _saved(client, token, project)
        assert _by_id(flow) == _by_id(before)
        assert flow["edges"] == before["edges"]
        assert flow["task"] == "Map the parks in the shade"

    def test_undo_of_a_plan_someone_changed_more_than_the_goal_of_while_it_landed_is_refused(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """A write between two of the plan's writes that changes anything but
        the goal still refuses the Undo, as on main: here a node's code
        outside the plan, written with the goal."""
        user, token = user_and_token

        def goal_and_code(flow):
            flow["task"] = "Map the parks in the shade"
            for node in flow["nodes"]:
                if node.get("id") == "sum":
                    node["content"] = "return input_0.max()  # while the plan landed"

        project, att, card, _ = self._plan_with_a_write_while_it_lands(client, user, token, monkeypatch, goal_and_code)
        refused = _undo(client, token, project, att, card["changeId"])
        assert refused.status_code == 409, refused.get_json()
        assert "changed this dataflow after; nothing was undone." in refused.get_json()["error"]
        flow = _saved(client, token, project)
        assert _by_id(flow)["sum"]["content"] == "return input_0.max()  # while the plan landed"
        assert "load" not in _by_id(flow)
        assert flow["task"] == "Map the parks in the shade"

    def test_undo_of_a_plan_keeps_what_a_person_wrote_before_it_with_no_version_of_its_own(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """A goal or a description written makes no version of its own, so the
        version before a plan can be older than them: the plan's Undo puts
        back the dataflow as the plan's first write found it, and what the
        person wrote stays as they left it. Here they cleared the goal and
        wrote a description before the plan, which then filled the goal.
        Before the fix the Undo put back the version before those writes: the
        goal they had cleared, and no description."""
        from utk_curio.backend.app.collaboration import dataflow_docs
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB, task="Find the old parks")
        # The doc open, as a tab holds it: its first version holds that goal.
        with dataflow_docs._held(project, _user_dir_key(user)):
            pass

        def cleared_and_described(flow):
            flow["task"] = ""
            flow["description"] = "Parks a short walk from home"

        _person_writes(user, project, cleared_and_described)
        plan = {
            "goal": "replace the loader",
            "nodes": [{"ref": "a", "nodeType": CA, "title": "API Fetch", "intent": "fetch from the api"}],
            "edges": [{"from": "a", "to": "sum"}],
            "removeNodes": ["load"],
        }
        body, _ = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(plan)])
        card = _the_card(body)
        assert card["goalSet"] == "replace the loader", card
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        flow = _saved(client, token, project)
        assert set(_by_id(flow)) == {"load", "sum"}
        assert flow.get("task", "") == ""
        assert flow.get("description") == "Parks a short walk from home"
        # A canvas no doc binds gets the goal the plan found, not the one cleared.
        [canvas] = undone.get_json()["canvas"]
        assert canvas["task"] == "", canvas

    def _land_replacing_the_loader(self, client, token, project, att, monkeypatch) -> dict:
        """The plan these tests land on *project*: it removes the loader and
        wires a new node into ``sum``. Its card."""
        plan = {
            "goal": "replace the loader",
            "nodes": [{"ref": "a", "nodeType": CA, "title": "API Fetch", "intent": "fetch from the api"}],
            "edges": [{"from": "a", "to": "sum"}],
            "removeNodes": ["load"],
        }
        body, _ = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(plan)])
        return _the_card(body)

    def test_undo_of_a_plan_keeps_a_description_written_after_it(self, client, user_and_token, tmp_curio, monkeypatch):
        """The plan's Undo takes back what the plan wrote, and no more: the
        description, which the plan did not write, written after it landed
        (with no version of its own), stays as the person left it, and holds
        the Undo back no more than the goal does. Before the fix the Undo was
        refused (409), as for any field of the dataflow changed after a plan."""
        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        card = self._land_replacing_the_loader(client, token, project, att, monkeypatch)
        _person_writes(user, project, lambda flow: flow.update(description="Parks a short walk from home"))
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        flow = _saved(client, token, project)
        assert set(_by_id(flow)) == {"load", "sum"}
        assert [(e["source"], e["target"]) for e in flow["edges"]] == [("load", "sum")]
        assert flow.get("description") == "Parks a short walk from home"

    def test_undo_of_a_plan_keeps_a_scenario_renamed_after_it(self, client, user_and_token, tmp_curio, monkeypatch):
        """The same for a scenario the plan did not write, renamed after it
        landed: the name stays, and the Undo goes ahead. The scenario is on a
        node with no connections, so the plan's writes leave it as it was."""
        user, token = user_and_token
        note = {"id": "note", "type": CA, "title": "Note", "goal": "Keep a note", "content": "return 0", "x": 800, "y": 0}
        project, att = _setup(client, user, token, coord=DFB, nodes=_nodes() + [note])
        _person_writes(user, project, lambda flow: flow.update(
            scenarios=[{"id": "s1", "name": "Cool roofs", "color": "#4477aa", "nodes": ["note"]}]))
        card = self._land_replacing_the_loader(client, token, project, att, monkeypatch)

        def renamed(flow):
            for scenario in flow.get("scenarios") or []:
                if scenario.get("id") == "s1":
                    scenario["name"] = "Cool roofs on every block"

        _person_writes(user, project, renamed)
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        flow = _saved(client, token, project)
        assert set(_by_id(flow)) == {"load", "sum", "note"}
        assert [(e["source"], e["target"]) for e in flow["edges"]] == [("load", "sum")]
        assert [s.get("name") for s in flow.get("scenarios") or [] if s.get("id") == "s1"] == ["Cool roofs on every block"]

    @pytest.mark.parametrize("place", ["nodes", "context", "outcomes"])
    def test_undo_of_a_plan_is_refused_when_a_scenario_made_after_it_names_its_node(
        self, client, user_and_token, tmp_curio, monkeypatch, place,
    ):
        """A scenario someone makes after a plan that saved none, naming the
        plan's node among its nodes (*place*), its context or its outcomes:
        the Undo, which takes that node away, would take it out of their
        scenario too, so it is refused and changes nothing, as on main. Before
        the fix it went ahead, and the write took the node out of what the
        scenario named there."""
        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        card = self._land_replacing_the_loader(client, token, project, att, monkeypatch)
        [new_id] = [node_id for node_id in _by_id(_saved(client, token, project)) if node_id != "sum"]
        scenario = {"id": "s1", "name": "Fetched by hand", "color": "#4477aa", "nodes": ["sum"],
                    "context": [], "outcomes": [], place: [new_id]}
        _person_writes(user, project, lambda flow: flow.update(scenarios=[scenario]))
        held = [s for s in _saved(client, token, project).get("scenarios") or [] if s.get("id") == "s1"]
        assert [s[place] for s in held] == [[new_id]], held
        refused = _undo(client, token, project, att, card["changeId"])
        assert refused.status_code == 409, refused.get_json()
        assert "changed this dataflow after; nothing was undone." in refused.get_json()["error"]
        flow = _saved(client, token, project)
        assert set(_by_id(flow)) == {new_id, "sum"}
        assert [s for s in flow.get("scenarios") or [] if s.get("id") == "s1"] == held

    def _land_saving_a_scenario(self, client, user, token, monkeypatch):
        """A dataflow with a scenario a person made on its note, and a plan
        that replaced its loader and saved a scenario of its own on the node
        it added. The project, the attachment, the plan's card, and the
        scenarios and their sets as the plan found them."""
        project, att = _setup(client, user, token, coord=DFB, nodes=_nodes() + [_note()])
        _person_writes(user, project, lambda flow: flow.update(
            scenarios=[{"id": "s1", "name": "Cool roofs", "color": "#4477aa", "nodes": ["note"]}]))
        found = _saved(client, token, project)
        before = {key: found.get(key) for key in ("scenarios", "scenarioSets")}
        plan = {
            "goal": "replace the loader",
            "nodes": [{"ref": "a", "nodeType": CA, "title": "API Fetch", "intent": "fetch from the api"}],
            "edges": [{"from": "a", "to": "sum"}],
            "removeNodes": ["load"],
            "scenarios": [{"name": "Fetched", "nodes": ["a"]}],
        }
        body, _ = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(plan)])
        card = _the_card(body)
        names = sorted(s.get("name") for s in _saved(client, token, project).get("scenarios") or [])
        assert names == ["Cool roofs", "Fetched"], names
        return project, att, card, before

    def test_undo_of_a_plan_that_saved_scenarios_takes_them_back(self, client, user_and_token, tmp_curio, monkeypatch):
        """A plan that saved a scenario wrote the scenarios: its Undo takes its
        scenario away with its node, and the scenarios are as the plan found
        them, the person's own as they made it."""
        user, token = user_and_token
        project, att, card, before = self._land_saving_a_scenario(client, user, token, monkeypatch)
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        flow = _saved(client, token, project)
        assert set(_by_id(flow)) == {"load", "sum", "note"}
        assert {key: flow.get(key) for key in ("scenarios", "scenarioSets")} == before

    def test_undo_of_a_plan_that_saved_scenarios_is_refused_when_someone_changed_another_scenario(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """After a plan that saved a scenario, a change to any other scenario
        refuses the plan's Undo, which would put every scenario back as the
        plan found it: here the person renamed their own."""
        user, token = user_and_token
        project, att, card, _ = self._land_saving_a_scenario(client, user, token, monkeypatch)
        _person_writes(user, project, _renamed("s1", "Cool roofs on every block"))
        refused = _undo(client, token, project, att, card["changeId"])
        assert refused.status_code == 409, refused.get_json()
        assert "changed this dataflow after; nothing was undone." in refused.get_json()["error"]
        flow = _saved(client, token, project)
        assert "load" not in _by_id(flow)
        assert sorted(s.get("name") for s in flow.get("scenarios") or []) == ["Cool roofs on every block", "Fetched"]

    def test_undo_of_a_plan_whose_removal_changed_a_scenario_is_refused_when_someone_renamed_it(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """A plan that saves no scenario still writes the scenarios when it
        removes a node a scenario names: its write takes the node out of the
        scenario, here out of its context. A rename of that scenario after
        the plan then refuses the plan's Undo, which would put the scenario
        back as the plan found it."""
        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB, nodes=_nodes() + [_note()])
        _person_writes(user, project, lambda flow: flow.update(scenarios=[
            {"id": "s1", "name": "Cool roofs", "color": "#4477aa", "nodes": ["note"], "context": ["load"],
             "outcomes": []}]))
        assert [s.get("context") for s in _saved(client, token, project).get("scenarios") or []] == [["load"]]
        card = self._land_replacing_the_loader(client, token, project, att, monkeypatch)
        # The plan's removal of the loader took it out of the scenario's context.
        assert [s.get("context") for s in _saved(client, token, project).get("scenarios") or []] == [[]]
        _person_writes(user, project, _renamed("s1", "Cool roofs on every block"))
        refused = _undo(client, token, project, att, card["changeId"])
        assert refused.status_code == 409, refused.get_json()
        assert "changed this dataflow after; nothing was undone." in refused.get_json()["error"]
        flow = _saved(client, token, project)
        assert "load" not in _by_id(flow)
        assert [s.get("name") for s in flow.get("scenarios") or []] == ["Cool roofs on every block"]

    def test_undo_of_a_second_plan_gives_the_planner_back_the_first(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        first = {"goal": "one", "nodes": [{"ref": "a", "nodeType": CA, "title": "A", "intent": "a"}], "edges": []}
        second = {"goal": "two", "nodes": [{"ref": "b", "nodeType": CA, "title": "B", "intent": "b"}], "edges": []}
        body, _ = _ask(client, token, project, att, monkeypatch, ["One.\n" + _plan_tail(first)])
        card_one = _the_card(body)
        body, _ = _ask(client, token, project, att, monkeypatch, ["Two.\n" + _plan_tail(second)])
        card_two = _the_card(body)
        assert _undo(client, token, project, att, card_two["changeId"]).status_code == 200
        assert _listing(client, token, project, att)["planProposal"]["proposalId"] == card_one["planId"]

    def test_an_unknown_change_is_not_found(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att = _setup(client, user, token)
        assert _undo(client, token, project, att, "no-such-change").status_code == 404


class TestAPlanFillsAnEmptyGoal:
    """A plan the Dataflow Builder lands gives a dataflow whose goal is empty,
    or only whitespace, the plan's own goal, trimmed, in the plan's first write
    and so in its change: its card says so (``goalSet``), the step that set it
    carries it to a canvas no doc binds, and its Undo takes it back while the
    goal still reads what the plan wrote. A goal someone wrote stays as it is."""

    GOAL = "Find the parks a short walk from home"

    def _land(self, client, token, project, att, monkeypatch) -> tuple[dict, dict]:
        """The plan landed: its card, and what landed with it for a canvas no
        doc binds (its steps, and its canvas mutation whole)."""
        plan = {
            "goal": self.GOAL,
            "nodes": [{"ref": "a", "nodeType": CA, "title": "API Fetch", "intent": "fetch from the api"}],
            "edges": [{"from": "a", "to": "sum"}],
            "removeNodes": ["load"],
        }
        body, _ = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(plan)])
        card = _the_card(body)
        [landed] = [c for c in body.get("changes") or [] if c["changeId"] == card["changeId"]]
        return card, landed

    @pytest.mark.parametrize("before", ["", "   "], ids=["empty", "whitespace"])
    def test_a_plan_fills_an_empty_goal_in_its_first_write(
        self, client, user_and_token, tmp_curio, monkeypatch, before,
    ):
        from utk_curio.backend.app.collaboration import dataflow_docs, history
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        project, att = _setup(client, user, token, coord=DFB)
        if before:
            _person_sets_the_goal(user, project, before)
        # The doc open, as a tab holds it, so the plan's points follow its first ones.
        with dataflow_docs._held(project, key):
            pass
        card, landed = self._land(client, token, project, att, monkeypatch)
        assert _saved(client, token, project)["task"] == self.GOAL
        assert card["goalSet"] == self.GOAL, card
        # In the plan's change, from its first write: the first point naming
        # the change holds the goal, and the version before it, as that write
        # found it and the plan's Undo puts it back, the person's. A goal
        # written makes no version of its own, so the version listed before
        # the plan (the first point's parent) can be older than it.
        points = [p for p in history.points(key, project) if p.get("change") == card["changeId"]]
        assert len(points) == 3, points
        assert history.dataflow_at(key, project, points[0]["id"])["task"] == self.GOAL
        assert history.dataflow_found_by(key, project, points[0]).get("task", "") == before
        # A canvas no doc binds takes it with the plan's first step, and with the plan whole.
        assert _mutations(landed["steps"][0])[0].get("task") == self.GOAL, landed["steps"][0]
        assert [m for step in landed["steps"][1:] for m in _mutations(step) if "task" in m] == [], landed["steps"]
        assert landed["canvas"]["task"] == self.GOAL, landed["canvas"]

    def test_a_goal_someone_wrote_stays_as_it_was(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        _person_sets_the_goal(user, project, "  Map the parks  ")
        card, landed = self._land(client, token, project, att, monkeypatch)
        assert _saved(client, token, project)["task"] == "  Map the parks  "
        assert "goalSet" not in card, card
        assert [m for step in landed["steps"] for m in _mutations(step) if "task" in m] == [], landed["steps"]
        assert "task" not in landed["canvas"], landed["canvas"]

    def test_undo_takes_back_the_goal_the_plan_set(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        before = _saved(client, token, project).get("task", "")
        assert not before.strip(), before
        card, _ = self._land(client, token, project, att, monkeypatch)
        assert _saved(client, token, project)["task"] == self.GOAL
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        flow = _saved(client, token, project)
        assert flow.get("task", "") == before, flow.get("task")
        assert set(_by_id(flow)) == {"load", "sum"}
        # A canvas no doc binds takes the goal back with the Undo.
        [canvas] = undone.get_json()["canvas"]
        assert canvas["task"] == before, canvas

    def test_undo_after_someone_changed_the_goal_keeps_theirs(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        card, _ = self._land(client, token, project, att, monkeypatch)
        assert _saved(client, token, project)["task"] == self.GOAL
        _person_sets_the_goal(user, project, "Find the shaded parks")
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        # The plan is undone, what it removed is back and its node gone, and the goal is theirs.
        flow = _saved(client, token, project)
        assert set(_by_id(flow)) == {"load", "sum"}
        assert [(e["source"], e["target"]) for e in flow["edges"]] == [("load", "sum")]
        assert flow["task"] == "Find the shaded parks"
        [canvas] = undone.get_json()["canvas"]
        assert "task" not in canvas, canvas

    def test_a_goal_saved_between_the_plans_read_and_its_write_stays(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """A goal someone saves after the plan's first step read the empty
        goal, and before that step's write, is theirs: the write gives the
        dataflow the plan's goal only while the doc still holds the goal the
        step read, in the write's own transaction. The change keeps no
        ``goalSet``, so the card does not say *Goal set to* and no step
        carries the goal to a canvas, and the Undo leaves their goal. Before
        the fix the plan's goal replaced theirs."""
        from utk_curio.backend.app.collaboration import dataflow_docs, history
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        key = _user_dir_key(user)
        project, att = _setup(client, user, token, coord=DFB)
        write = dataflow_docs.write
        carried: list = []

        def someone_saves_a_goal_first(user_key, project_id, spec, actor, **kwargs):
            if (kwargs.get("point") or {}).get("change") and not carried:
                # The plan's first write: its step read the dataflow already.
                carried.append(spec["dataflow"].get("task"))
                _person_sets_the_goal(user, project, "Map the parks")
            return write(user_key, project_id, spec, actor, **kwargs)

        monkeypatch.setattr(dataflow_docs, "write", someone_saves_a_goal_first)
        card, landed = self._land(client, token, project, att, monkeypatch)
        # The step read an empty goal and wrote the plan's; theirs landed first.
        assert carried == [self.GOAL], carried
        points = [p for p in history.points(key, project) if p.get("change") == card["changeId"]]
        assert history.dataflow_found_by(key, project, points[0]).get("task") == "Map the parks"
        assert _saved(client, token, project)["task"] == "Map the parks"
        assert "goalSet" not in card, card
        assert [m for step in landed["steps"] for m in _mutations(step) if "task" in m] == [], landed["steps"]
        assert "task" not in landed["canvas"], landed["canvas"]
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        flow = _saved(client, token, project)
        assert set(_by_id(flow)) == {"load", "sum"}
        assert flow["task"] == "Map the parks"
        [canvas] = undone.get_json()["canvas"]
        assert "task" not in canvas, canvas

    def test_undo_leaves_a_goal_saved_while_it_puts_back(self, client, user_and_token, tmp_curio, monkeypatch):
        """A goal someone saves while the Undo puts the dataflow back, after
        the put-back read the plan's goal and before its write, is theirs:
        the put-back takes the goal back only while the doc still holds the
        plan's goal, in its own transaction, and its mutation then carries no
        goal for a canvas. Before the fix the Undo emptied their goal."""
        from utk_curio.backend.app.collaboration import dataflow_docs

        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        card, _ = self._land(client, token, project, att, monkeypatch)
        assert card["goalSet"] == self.GOAL, card
        write = dataflow_docs.write
        read: list = []

        def someone_saves_a_goal_first(user_key, project_id, spec, actor, **kwargs):
            if actor.what == "putBack" and not read:
                # The put-back's write: it read the plan's goal already.
                read.append(spec.base["dataflow"].get("task"))
                _person_sets_the_goal(user, project, "Find the shaded parks")
            return write(user_key, project_id, spec, actor, **kwargs)

        monkeypatch.setattr(dataflow_docs, "write", someone_saves_a_goal_first)
        undone = _undo(client, token, project, att, card["changeId"])
        assert read == [self.GOAL], read
        assert undone.status_code == 200, undone.get_json()
        flow = _saved(client, token, project)
        assert set(_by_id(flow)) == {"load", "sum"}
        assert flow.get("task") == "Find the shaded parks"
        [canvas] = undone.get_json()["canvas"]
        assert "task" not in canvas, canvas

    def test_undo_names_the_plans_goal_to_a_canvas_no_doc_binds(self, client, user_and_token, tmp_curio, monkeypatch):
        """The Undo's mutation carries the goal it put back (``task``) and the
        plan's (``goalSet``): a canvas no doc binds takes the goal back only
        while its own goal still reads the plan's, so a goal set there while
        its room's socket was down stays."""
        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        card, _ = self._land(client, token, project, att, monkeypatch)
        undone = _undo(client, token, project, att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        [canvas] = undone.get_json()["canvas"]
        assert (canvas.get("task"), canvas.get("goalSet")) == ("", self.GOAL), canvas

    @pytest.mark.parametrize("goal", ["", "   "], ids=["empty", "whitespace"])
    def test_a_plan_with_no_goal_of_its_own_fills_nothing(
        self, client, user_and_token, tmp_curio, monkeypatch, goal,
    ):
        """The grammar refuses a plan with no goal (``plan.field-empty``), so
        this one is given *goal* after its checks: what keeps the dataflow's
        goal empty then is the landing's own check."""
        from utk_curio.backend.app.agents.domain import content

        parse = content._parse_dataflow_plan_verbose

        def without_its_goal(raw):
            plan, errors = parse(raw)
            if plan is not None:
                plan["goal"] = goal
            return plan, errors

        monkeypatch.setattr(content, "_parse_dataflow_plan_verbose", without_its_goal)
        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        card, landed = self._land(client, token, project, att, monkeypatch)
        assert card["kind"] == "plan"
        assert not _saved(client, token, project).get("task", "").strip()
        assert "goalSet" not in card, card
        assert [m for step in landed["steps"] for m in _mutations(step) if "task" in m] == [], landed["steps"]


#: A review of each kind of change, as a dataflow saved one before agents
#: changed it directly: pending, waiting for an Apply that lands nothing now.
SAVED_REVIEWS = {
    "node.content.write": {"nodeId": "sum", "content": "return 99"},
    "node.create": {"nodeType": CA, "content": "return 2"},
    "node.settings.write": {"nodeId": "sum", "settings": {"widgets": {}}},
    "dataflow.plan.write": {"plan": {"goal": "replace the loader", "removeNodes": ["load"], "edges": [],
                                     "nodes": [{"ref": "a", "nodeType": CA, "title": "API Fetch"}]}},
}


class TestAReviewSavedBeforeAgentsEditedDirectly:
    """A chat saved while a review of a change waited still holds it. Its
    Apply is refused, saying why, and changes nothing; its Dismiss settles it,
    on the card the chat shows too. A plan parked beside a later review is
    found where it was kept."""

    @staticmethod
    def _saved_review(client, user, token, tool, *, parked=False):
        from utk_curio.backend.app.agents.application import attachments
        from utk_curio.backend.app.agents.application import spec_reads
        from utk_curio.backend.app.agents.application.proposals import store
        from utk_curio.backend.app.agents.domain import content
        from utk_curio.backend.app.agents.repositories import sessions
        from utk_curio.backend.app.collaboration import dataflow_docs
        from utk_curio.backend.app.projects.services import _user_dir_key

        project, att = _setup(client, user, token, coord=DFB if tool == "dataflow.plan.write" else NB)
        ukey = _user_dir_key(user)
        session_id = _listing(client, token, project, att)["sessionId"]
        loop_ctx = {"attachment_id": att, "session_id": session_id}

        def _review(kind):
            """A pending review of *kind* and its card, in the chat as a reply holds it."""
            review = {"proposalId": f"saved-{kind}", "tool": kind, "summary": f"Saved review of {kind}",
                      "status": "pending", **SAVED_REVIEWS[kind]}
            part = content.make_proposal_part(proposal_id=review["proposalId"], tool=kind, summary=review["summary"],
                                              preview="what the agent wrote then", pins={})
            sessions.append_turns(ukey, project, session_id, att,
                                  [sessions.make_turn("agent", "Review it below.", content=[part])])
            return review, part

        review, part = _review(tool)
        spec = spec_reads._live_spec_or_404(ukey, project)
        if parked:
            # A pending plan parked beside a later review, which took the active slot.
            attachments.get_attachment(spec, att)["planProposal"] = review
            dataflow_docs.write(ukey, project, spec, dataflow_docs.by_agent(None, ukey, "proposal"))
            later, later_part = _review("node.content.write")
            store._store_proposal(ukey, project, spec_reads._live_spec_or_404(ukey, project), loop_ctx,
                                  later, later_part)
        else:
            store._store_proposal(ukey, project, spec, loop_ctx, review, part)
        return project, att, review["proposalId"]

    @staticmethod
    def _part_status(client, token, project, att, proposal_id):
        turns = client.get(f"/api/agents/projects/{project}/attachments/{att}/session",
                           headers=_auth(token)).get_json()["turns"]
        [status] = [p["status"] for t in turns for p in t.get("content") or []
                    if p.get("type") == "proposal" and p.get("proposalId") == proposal_id]
        return status

    def test_every_kind_of_change_has_a_saved_review_here(self):
        from utk_curio.backend.app.agents.application.proposals.changes import CHANGE_TOOLS

        assert set(SAVED_REVIEWS) == CHANGE_TOOLS

    @pytest.mark.parametrize("tool", sorted(SAVED_REVIEWS))
    def test_its_apply_is_refused_saying_why_and_changes_nothing(self, client, user_and_token, tmp_curio, tool):
        user, token = user_and_token
        project, att, proposal_id = self._saved_review(client, user, token, tool)
        before = _saved(client, token, project)
        refused = client.post(f"/api/agents/projects/{project}/attachments/{att}/proposals/{proposal_id}/apply",
                              headers=_auth(token))
        assert refused.status_code == 409, refused.get_data(as_text=True)
        said = refused.get_json()["error"]
        # Words the card can show, not "no apply flow exists for tool ...".
        assert "can no longer be applied" in said and "dismiss it" in said, said
        from utk_curio.backend.app.agents.application.proposals.apply import MADE_BEFORE_DIRECT_CHANGES

        assert said == MADE_BEFORE_DIRECT_CHANGES
        after = _saved(client, token, project)
        assert (after["nodes"], after["edges"]) == (before["nodes"], before["edges"])
        assert _listing(client, token, project, att)["activeProposal"]["status"] == "pending"
        assert self._part_status(client, token, project, att, proposal_id) == "pending"

    @pytest.mark.parametrize("tool", sorted(SAVED_REVIEWS))
    def test_its_dismiss_settles_it_on_the_card_too(self, client, user_and_token, tmp_curio, tool):
        user, token = user_and_token
        project, att, proposal_id = self._saved_review(client, user, token, tool)
        dismissed = client.delete(f"/api/agents/projects/{project}/attachments/{att}/proposals/{proposal_id}",
                                  headers=_auth(token))
        assert dismissed.status_code == 200, dismissed.get_data(as_text=True)
        assert dismissed.get_json()["status"] == "dismissed"
        assert _listing(client, token, project, att)["activeProposal"]["status"] == "dismissed"
        assert self._part_status(client, token, project, att, proposal_id) == "dismissed"

    def test_a_plan_parked_beside_a_later_review_is_refused_and_dismissed_where_it_was_kept(
        self, client, user_and_token, tmp_curio,
    ):
        user, token = user_and_token
        project, att, proposal_id = self._saved_review(client, user, token, "dataflow.plan.write", parked=True)
        before = _saved(client, token, project)
        path = f"/api/agents/projects/{project}/attachments/{att}/proposals/{proposal_id}"
        refused = client.post(f"{path}/apply", headers=_auth(token))
        assert refused.status_code == 409, refused.get_data(as_text=True)
        from utk_curio.backend.app.agents.application.proposals.apply import MADE_BEFORE_DIRECT_CHANGES

        assert refused.get_json()["error"] == MADE_BEFORE_DIRECT_CHANGES
        after = _saved(client, token, project)
        assert (after["nodes"], after["edges"]) == (before["nodes"], before["edges"])
        dismissed = client.delete(path, headers=_auth(token))
        assert dismissed.status_code == 200, dismissed.get_data(as_text=True)
        listing = _listing(client, token, project, att)
        assert listing["planProposal"]["status"] == "dismissed"
        # The later review that took the active slot is left as it was.
        assert listing["activeProposal"]["proposalId"] == "saved-node.content.write"
        assert listing["activeProposal"]["status"] == "pending"
        assert self._part_status(client, token, project, att, proposal_id) == "dismissed"


class TestAChangeWaitsForAPersonInTheNode:
    @pytest.fixture(autouse=True)
    def _quick(self, monkeypatch):
        from utk_curio.backend.app.agents.application.proposals import changes

        monkeypatch.setattr(changes, "LOCK_WAIT_S", 0.6)
        monkeypatch.setattr(changes, "_LOCK_POLL_S", 0.02)

    @staticmethod
    def _hold(monkeypatch, holder, node="sum"):
        """*holder*, ``(user_id, name)``, holds the node *node* in the room
        while the returned dict's ``held`` is true."""
        from utk_curio.backend.app.collaboration import room_state

        state = {"held": True}
        real = room_state.snapshot

        def _snapshot(room):
            out = dict(real(room) or {})
            if state["held"]:
                out["locks"] = {node: {"user_id": holder[0], "name": holder[1]}}
            return out

        monkeypatch.setattr(room_state, "snapshot", _snapshot)
        return state

    def test_the_change_lands_once_the_person_leaves_the_node(self, client, user_and_token, tmp_curio, monkeypatch):
        import time as real_time
        from types import SimpleNamespace

        from utk_curio.backend.app.agents.application.proposals import changes

        user, token = user_and_token
        project, att = _setup(client, user, token, target={"kind": "node", "targetId": "sum"})
        state = self._hold(monkeypatch, ("someone-else", "Ana"))
        waits: list = []

        def _sleep(seconds):
            # The person leaves the node after the change waited three times.
            waits.append(seconds)
            if len(waits) >= 3:
                state["held"] = False

        monkeypatch.setattr(changes, "time", SimpleNamespace(monotonic=real_time.monotonic, sleep=_sleep))
        body, _ = _ask(client, token, project, att, monkeypatch, [_write_tail("sum", "return input_0.sum()"), "Written."])
        card = _the_card(body)
        assert card["status"] == "applied"
        assert len(waits) == 3, waits
        assert _by_id(_saved(client, token, project))["sum"]["content"] == "return input_0.sum()"

    def test_the_change_is_refused_naming_who_still_holds_the_node(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project, att = _setup(client, user, token, target={"kind": "node", "targetId": "sum"})
        self._hold(monkeypatch, ("someone-else", "Ana"))
        body, calls = _ask(client, token, project, att, monkeypatch,
                           [_write_tail("sum", "return input_0.sum()"), "Ana is in it."])
        assert _cards(body) == []
        [said] = _tool_results(calls[-1], "node.content.write")
        assert said.startswith("[tool result] node.content.write: refused"), said
        assert "Ana" in said, said
        assert _by_id(_saved(client, token, project))["sum"]["content"] == "return input_0"

    def test_a_plan_is_refused_when_the_person_changed_a_node_it_removes_while_holding_it(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """The plan's check that each node it removes holds the code it read
        runs after the wait, so what the person wrote while in the node stays."""
        import time as real_time
        from types import SimpleNamespace

        from utk_curio.backend.app.agents.application.proposals import changes
        from utk_curio.backend.app.collaboration import dataflow_docs
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        project, att = _setup(client, user, token, coord=DFB)
        state = self._hold(monkeypatch, ("someone-else", "Ana"), node="load")

        def _sleep(seconds):
            # Ana rewrites the node the plan removes, then leaves it.
            if state["held"]:
                spec = dataflow_docs.live(_user_dir_key(user), project)
                for node in spec["dataflow"]["nodes"]:
                    if node["id"] == "load":
                        node["content"] = "return 10  # Ana's"
                dataflow_docs.write(_user_dir_key(user), project, spec, dataflow_docs.person("someone-else", "edit"))
                state["held"] = False

        monkeypatch.setattr(changes, "time", SimpleNamespace(monotonic=real_time.monotonic, sleep=_sleep))
        plan = {
            "goal": "replace the loader",
            "nodes": [{"ref": "a", "nodeType": CA, "title": "API Fetch", "intent": "fetch from the api"}],
            "edges": [{"from": "a", "to": "sum"}],
            "removeNodes": ["load"],
        }
        body, calls = _ask(client, token, project, att, monkeypatch, ["Here.\n" + _plan_tail(plan), "Ana changed it."])
        assert state["held"] is False, "the plan never waited for Ana"
        assert _cards(body) == [] and _proposals(body) == []
        flow = _saved(client, token, project)
        assert set(_by_id(flow)) == {"load", "sum"}
        assert _by_id(flow)["load"]["content"] == "return 10  # Ana's"
        assert [(e["source"], e["target"]) for e in flow["edges"]] == [("load", "sum")]
        # The model is told why, and plans again from what the dataflow holds.
        assert "changed after you read it" in calls[-1][-1]["content"], calls[-1][-1]["content"]

    def test_the_askers_own_focus_in_the_node_never_holds_their_agent_back(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project, att = _setup(client, user, token, target={"kind": "node", "targetId": "sum"})
        state = self._hold(monkeypatch, (str(user.id), "Me"))
        body, _ = _ask(client, token, project, att, monkeypatch,
                       [_write_tail("sum", "return input_0.sum()"), "Written."])
        card = _the_card(body)
        assert card["status"] == "applied"
        assert state["held"] is True

    def test_a_job_that_runs_outside_the_request_waits_for_anyone_but_its_asker(self, tmp_curio, monkeypatch):
        """The node Solve's job thread holds no request: its landing names
        its asker (``asker_id``), so the asker's own focus does not hold it,
        and another person's does."""
        from utk_curio.backend.app.agents.application.proposals import changes
        from utk_curio.backend.app.collaboration import room_state

        monkeypatch.setattr(room_state, "snapshot", lambda room: {"locks": {"sum": {"user_id": "7", "name": "Me"}}})
        monkeypatch.setattr(changes.agents_spec_reads, "_acting_user", lambda: None)
        assert changes.wait_for_people("p", ["sum"], "7") is None
        assert changes.wait_for_people("p", ["sum"], "8") == "Me"
