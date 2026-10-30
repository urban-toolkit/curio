"""Every agent run is in its dataflow's room, and holds what it changes.

A run joins the room as its agent (``collaboration/agent_peers.py``), with who
asked and the skills its run holds, and leaves before its reply ends. Each
write of a node's code, spec, widgets or settings waits for anyone else in the
node, takes the node's lock as the agent, names the node in the agent's state,
writes, and keeps both a second while a tab is bound. A batch Solve takes the
locks of a wave's nodes before it takes the spec lock to write them, names
them all, and lets them go after it leaves it. On the guest account, which
every guest signs in to, the asker's own locks are those of their sign-in, so
another guest's lock holds the agent back.

The room's events are recorded where the server makes them (its Activity, the
agent's state, the locks), so each test reads the order things happened in.
Names main lacks are imported inside each test, so a checkout without them
fails test by test.
"""

from __future__ import annotations

import json

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_agent_changes import (
    _ask,
    _by_id,
    _cards,
    _saved,
    _setup,
)
from utk_curio.backend.tests.test_agents.test_map_edits_grounding import _write_tail
from utk_curio.backend.tests.test_agents.test_source_grounding_routes import _tool_results

NB = "agent.curio.node-builder@1"
NEW_CODE = "return input_0.sum()"


def _agent_lock(room_state, room: str, node_id: str):
    """The participant whose lock holds *node_id* in *room* now, or None."""
    return (room_state.snapshot(room)["locks"].get(node_id) or {}).get("participant_id")


def _recording(monkeypatch, project_id: str, timeline: list) -> None:
    """Record, in order, what the room is told: each lock taken and let go,
    each change of an agent's ``editing``, and each agent's join and leave."""
    from utk_curio.backend.app.collaboration import dataflow_docs, room_state
    from utk_curio.backend.app.projects import storage

    room = room_state.room_for(project_id)
    real_lock, real_release = room_state.try_lock, room_state.release_lock
    real_state, real_activity = dataflow_docs.set_agent_state, room_state.record_activity

    def try_lock(at, node_id, user_info):
        lock = real_lock(at, node_id, user_info)
        if at == room and lock is not None and str(user_info.get("participant_id") or "").startswith("agent-"):
            timeline.append(("lock", node_id, user_info["participant_id"], _under_spec_lock(storage, project_id)))
        return lock

    def release_lock(at, node_id, participant_id):
        released = real_release(at, node_id, participant_id)
        if at == room and released and str(participant_id or "").startswith("agent-"):
            timeline.append(("unlock", node_id, participant_id, _under_spec_lock(storage, project_id)))
        return released

    def set_agent_state(at_project, client_id, fields, *, joining=False):
        if at_project == project_id and "editing" in fields and not joining:
            timeline.append(("state", fields.get("editing"), fields.get("writes")))
        return real_state(at_project, client_id, fields, joining=joining)

    def record_activity(at, kind, payload):
        if at == room and kind in ("agent_joined", "agent_left"):
            timeline.append((kind, payload.get("name"), (payload.get("agent") or {}).get("askedBy"),
                             payload.get("did")))
        return real_activity(at, kind, payload)

    monkeypatch.setattr(room_state, "try_lock", try_lock)
    monkeypatch.setattr(room_state, "release_lock", release_lock)
    monkeypatch.setattr(dataflow_docs, "set_agent_state", set_agent_state)
    monkeypatch.setattr(room_state, "record_activity", record_activity)


def _under_spec_lock(storage, project_id: str) -> bool:
    """Whether this thread holds the dataflow's spec lock now, under any key."""
    return any(held_project == project_id for _key, held_project in storage._spec_locks_held())


def _at(timeline: list, kind: str, *rest) -> int:
    """Where the first entry of *kind* (whose next fields are *rest*) is."""
    for index, entry in enumerate(timeline):
        if entry[0] == kind and tuple(entry[1:1 + len(rest)]) == rest:
            return index
    raise AssertionError(f"no {(kind, *rest)} in {timeline}")


def test_a_turns_agent_is_in_the_room_while_it_works_and_gone_before_its_reply_is_done(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """alice asks the Node Builder on a node to rewrite its code, as a
    streamed turn. It joins the room before its first round, named after its
    manifest, asked by alice, holding the skills its run holds, and is there
    at every round and as its change lands; it leaves, saying what it did,
    before the reply's content and its done event."""
    from utk_curio.backend.app.agents.application.turns import turn_loop
    from utk_curio.backend.app.collaboration import agent_peers
    from utk_curio.backend.tests.test_agents.test_routes_turns import TestStreamRun

    user, token = user_and_token
    project, att = _setup(client, user, token, target={"kind": "node", "targetId": "sum"})
    timeline: list = []
    _recording(monkeypatch, project, timeline)
    replies = [_write_tail("sum", NEW_CODE), "Written."]
    calls: list = []

    def at_work_now():
        peer = agent_peers.peer_of(project, att)
        if peer is None:
            return None
        return {"name": peer.name, "askedBy": peer.user["agent"]["askedBy"], "skills": peer.skills}

    def fake_stream(config, messages, **kwargs):
        calls.append(messages)
        timeline.append(("model", at_work_now()))
        yield replies[min(len(calls) - 1, len(replies) - 1)]

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn", fake_stream)
    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn",
                        lambda config, messages, **kwargs: "Title")
    real_stream = turn_loop.AttachmentTurn.stream

    def stream(self):
        for name, payload in real_stream(self):
            timeline.append(("event", name))
            yield name, payload

    monkeypatch.setattr(turn_loop.AttachmentTurn, "stream", stream)

    r = client.post(f"/api/agents/projects/{project}/attachments/{att}/run/stream",
                    json={"message": "sum it"}, headers=_auth(token))
    assert r.status_code == 200, r.get_data(as_text=True)
    events = TestStreamRun()._events(r)
    done = events[-1][1]
    assert events[-1][0] == "done", [name for name, _ in events]

    joined = _at(timeline, "agent_joined", "Node Builder")
    left = _at(timeline, "agent_left", "Node Builder")
    asked_by = {"account": str(user.id), "name": "Alice"}
    assert timeline[joined][2] == asked_by, timeline[joined]
    models = [index for index, entry in enumerate(timeline) if entry[0] == "model"]
    assert len(models) == 2, timeline
    held = [name for key in ("handed", "kept", "named") for name in (done.get("skills") or {}).get(key) or []]
    for index in models:
        assert joined < index < left, f"a round ran with its agent out of the room: {timeline}"
        assert timeline[index][1] == {"name": "Node Builder", "askedBy": asked_by, "skills": held}, timeline[index]
    assert joined < _at(timeline, "event", "change") < left, timeline
    # It left before the reply's content and its done event, saying what it did.
    assert left < _at(timeline, "event", "content") < _at(timeline, "event", "done"), timeline
    assert timeline[left][3] == {"changed": {"node": 1}}, timeline[left]
    assert agent_peers.peer_of(project, att) is None
    assert _by_id(_saved(client, token, project))["sum"]["content"] == NEW_CODE


def test_a_content_write_holds_its_node_from_before_the_write_to_a_second_after_behind_a_persons_lock(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """Ana, another person, is in the node when alice's Node Builder writes it.
    The write waits for her; once she leaves, the agent takes the node's lock,
    names the node and what it writes in its state, writes, keeps both a
    second while a tab is bound (the code in place by then), and lets go."""
    import time as real_time
    from types import SimpleNamespace

    from utk_curio.backend.app.agents.application.proposals import changes
    from utk_curio.backend.app.collaboration import agent_peers, dataflow_docs, room_state
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    project, att = _setup(client, user, token, target={"kind": "node", "targetId": "sum"})
    key = _user_dir_key(user)
    room = room_state.room_for(project)
    ana = {"participant_id": "p-ana", "user_id": "someone-else", "username": "ana", "name": "Ana"}
    assert room_state.try_lock(room, "sum", ana) is not None
    timeline: list = []
    _recording(monkeypatch, project, timeline)
    polls: list = []

    def poll(seconds):
        # Ana leaves the node after the change waited for her twice.
        polls.append(seconds)
        if len(polls) == 2:
            assert room_state.release_lock(room, "sum", "p-ana")
            timeline.append(("ana left",))

    monkeypatch.setattr(changes, "time", SimpleNamespace(monotonic=real_time.monotonic, sleep=poll))
    # A tab is bound to the dataflow's doc: the second after the write is kept.
    monkeypatch.setattr(dataflow_docs, "has_tabs", lambda project_id: True)

    def kept(seconds):
        code = _by_id(dataflow_docs.live(key, project)["dataflow"])["sum"]["content"]
        timeline.append(("kept", seconds, _agent_lock(room_state, room, "sum"), code))

    monkeypatch.setattr(agent_peers, "_sleep", kept)
    real_write = dataflow_docs.write

    def write(user_key, project_id, spec, actor, **kwargs):
        if project_id == project and _by_id(spec["dataflow"]).get("sum", {}).get("content") == NEW_CODE:
            timeline.append(("write", _agent_lock(room_state, room, "sum")))
        return real_write(user_key, project_id, spec, actor, **kwargs)

    monkeypatch.setattr(dataflow_docs, "write", write)

    body, _calls = _ask(client, token, project, att, monkeypatch, [_write_tail("sum", NEW_CODE), "Written."])

    assert [card["status"] for card in _cards(body)] == ["applied"], body["content"]
    locked = _at(timeline, "lock", "sum")
    agent = timeline[locked][2]
    assert _at(timeline, "ana left") < locked, f"the agent took the node before Ana left it: {timeline}"
    named = _at(timeline, "state", "sum", "code")
    wrote = _at(timeline, "write")
    held = _at(timeline, "kept")
    cleared = _at(timeline, "state", None, None)
    unlocked = _at(timeline, "unlock", "sum")
    assert locked < named < wrote < held < cleared < unlocked, timeline
    assert timeline[wrote][1] == agent, f"the code landed while the agent did not hold the node: {timeline}"
    assert timeline[held] == ("kept", agent_peers.KEEP_AFTER_WRITE_S, agent, NEW_CODE), timeline[held]
    assert timeline[unlocked][2] == agent
    assert room_state.snapshot(room)["locks"] == {}, "a lock outlived the turn"


def test_a_batch_solves_wave_holds_its_nodes_outside_the_spec_lock_and_names_them_all(
    client, user_and_token, tmp_curio, alice_project, monkeypatch,
):
    """alice solves a plan of two nodes with nothing between them: one wave.
    The batch's agent takes both nodes' locks before it takes the spec lock to
    write their code, its state names both while it writes, the code lands
    under the spec lock while both are its, and it lets them go after it left
    the spec lock. Its agent joined before and left after."""
    from utk_curio.backend.app.collaboration import dataflow_docs, room_state
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.tests.test_agents.test_routes_proposals import TestDataflowPlanMint
    from utk_curio.backend.tests.test_agents.test_routes_solve import TestSolve

    user, token = user_and_token
    helper = TestSolve()
    att, canvas, _calls = helper._applied_plan(
        client, user, token, alice_project, monkeypatch,
        replies=["Here is the plan.\n" + TestDataflowPlanMint()._plan_tail(edges=[])],
    )
    wave = sorted(node["id"] for node in canvas["nodes"])
    assert len(wave) == 2, canvas
    room = room_state.room_for(alice_project)
    timeline: list = []
    _recording(monkeypatch, alice_project, timeline)
    real_write = dataflow_docs.write

    def write(user_key, project_id, spec, actor, **kwargs):
        nodes = _by_id(spec["dataflow"])
        if project_id == alice_project and all((nodes.get(node_id) or {}).get("content") for node_id in wave):
            timeline.append(("write", _under_spec_lock(storage, project_id),
                             {node_id: _agent_lock(room_state, room, node_id) for node_id in wave}))
        return real_write(user_key, project_id, spec, actor, **kwargs)

    monkeypatch.setattr(dataflow_docs, "write", write)

    solved = helper._solve(client, token, alice_project, att)
    assert solved.status_code == 200, solved.get_data(as_text=True)
    assert {result["status"] for result in solved.get_json()["results"].values()} == {"solved"}, solved.get_json()

    locks = [entry for entry in timeline if entry[0] == "lock"]
    assert sorted(entry[1] for entry in locks) == wave, f"the wave's nodes were not both locked: {timeline}"
    agent = locks[0][2]
    assert all(entry[2] == agent and entry[3] is False for entry in locks), (
        f"a node's lock was taken under the spec lock, or not by the batch's agent: {locks}"
    )
    wrote = _at(timeline, "write")
    assert timeline[wrote][1] is True, "the wave's code was written outside the spec lock"
    assert timeline[wrote][2] == {node_id: agent for node_id in wave}, f"the wave landed on nodes not held: {timeline}"
    named = [index for index, entry in enumerate(timeline) if entry[0] == "state" and entry[1] is not None]
    assert len(named) == 1, timeline
    editing, writes = timeline[named[0]][1:]
    assert isinstance(editing, list) and sorted(editing) == wave and writes == "code", timeline[named[0]]
    assert max(timeline.index(entry) for entry in locks) < named[0] < wrote, timeline
    unlocks = [entry for entry in timeline if entry[0] == "unlock"]
    assert sorted(entry[1] for entry in unlocks) == wave and all(entry[3] is False for entry in unlocks), timeline
    assert min(timeline.index(entry) for entry in unlocks) > wrote, timeline
    joined = _at(timeline, "agent_joined", "Dataflow Builder")
    left = _at(timeline, "agent_left", "Dataflow Builder")
    assert joined < timeline.index(locks[0]) and timeline.index(unlocks[-1]) < left, timeline
    assert timeline[left][3] == {"changed": {"node": 2}}, timeline[left]


def test_on_the_guest_account_another_guests_lock_holds_the_agent_back_and_the_askers_own_does_not(
    client, db, tmp_curio, monkeypatch,
):
    """A Curio with no sign-in signs every browser in to the one shared guest
    account, each with a sign-in of its own. The first guest asks the Node
    Builder to rewrite a node the second guest has open: their account is the
    asker's, but their sign-in is not, so the agent waits for them and, still
    held once the wait ends, writes nothing and says who is editing. Then the
    asker holds the node themself, and the write lands."""
    from utk_curio.backend import config
    from utk_curio.backend.app.agents.application.proposals import changes
    from utk_curio.backend.app.collaboration import room_state
    from utk_curio.backend.app.users.models import User, UserSession

    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    for name, value in (("GUEST_LLM_API_TYPE", "openai_compatible"), ("GUEST_LLM_BASE_URL", "http://127.0.0.1:9/v1"),
                        ("GUEST_LLM_MODEL", "test-model"), ("GUEST_LLM_API_KEY", "test-key")):
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(changes, "LOCK_WAIT_S", 0.6)
    monkeypatch.setattr(changes, "_LOCK_POLL_S", 0.02)
    guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Shared Guest", is_guest=True)
    db.session.add(guest)
    db.session.flush()
    first = UserSession(user_id=guest.id, token="guest-first-browser")
    second = UserSession(user_id=guest.id, token="guest-second-browser")
    db.session.add_all([first, second])
    db.session.commit()
    project, att = _setup(client, guest, first.token, target={"kind": "node", "targetId": "sum"})
    room = room_state.room_for(project)

    def tab(sid: str, session, participant_id: str) -> dict:
        """A tab of the guest account signed in as *session*, in the room, as
        the socket's handshake and join make it (``events.py``)."""
        room_state.set_identity(sid, {
            "user_id": guest.id, "username": guest.username, "name": guest.name, "is_guest": True,
            "token_session_id": session.id, "participant_id": participant_id,
        })
        return room_state.add_user(room, sid, {
            "user_id": guest.id, "username": guest.username, "name": guest.name,
            "participant_id": participant_id, "role": "owner",
        })

    try:
        seconds = tab("sid-second", second, "p-second")
        assert room_state.try_lock(room, "sum", seconds) is not None

        body, calls = _ask(client, first.token, project, att, monkeypatch,
                           [_write_tail("sum", NEW_CODE), "The other guest is in it."])

        [said] = _tool_results(calls[-1], "node.content.write")
        assert said.startswith("[tool result] node.content.write: refused"), (
            f"another guest's lock did not hold the agent the first guest asked: {said}"
        )
        assert "Shared Guest is editing" in said, said
        assert _cards(body) == []
        assert _by_id(_saved(client, first.token, project))["sum"]["content"] == "return input_0"

        # The second guest leaves the node, and the first, who asked, is in it.
        assert room_state.release_lock(room, "sum", "p-second")
        firsts = tab("sid-first", first, "p-first")
        assert room_state.try_lock(room, "sum", firsts) is not None

        body, calls = _ask(client, first.token, project, att, monkeypatch, [_write_tail("sum", NEW_CODE), "Written."])

        [said] = _tool_results(calls[-1], "node.content.write")
        assert said.startswith("[tool result] node.content.write: applied"), (
            f"the asker's own lock held their agent back: {said}"
        )
        assert _by_id(_saved(client, first.token, project))["sum"]["content"] == NEW_CODE
        assert _agent_lock(room_state, room, "sum") == "p-first", "the agent took the asker's lock"
    finally:
        for sid in ("sid-first", "sid-second"):
            room_state.release_all_for_sid(sid)
            room_state.drop_identity(sid)


def test_the_change_event_says_what_the_agents_state_said_as_it_wrote(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """A tab no doc binds shows an agent's write from the run's stream: the
    change's event carries the agent's state as it wrote, its ``user``, the
    node in ``editing`` and ``writes``."""
    user, token = user_and_token
    project, att = _setup(client, user, token, target={"kind": "node", "targetId": "sum"})
    body, _calls = _ask(client, token, project, att, monkeypatch, [_write_tail("sum", NEW_CODE), "Written."])

    [landed] = body["changes"]
    writing = landed.get("writing")
    assert writing is not None, f"the change's event says nothing of the agent's state: {json.dumps(landed)}"
    assert (writing["editing"], writing["writes"]) == ("sum", "code"), writing
    assert writing["user"]["name"] == "Node Builder" and writing["user"]["user_id"] is None, writing
    assert writing["user"]["agent"]["attachmentId"] == att, writing
    assert writing["user"]["agent"]["askedBy"] == {"account": str(user.id), "name": "Alice"}, writing
