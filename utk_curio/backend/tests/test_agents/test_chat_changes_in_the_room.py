"""What the server writes into an agent's chat outside an ask is told to its room.

A chat turn's own events reach every tab of the dataflow's owner and editors
through the room (``agent_turn``, ``turns/turn_jobs.py``). The server also
writes into a chat with no ask of it running: a Solve's turns and the task it
hands a loader's Dataset Finder, a pick's Source recorded turn in the
Finder's chat and in the chat that asked for the candidates, an Undo's card
turned undone, a cleared chat. Each such write tells the same tabs which
chat changed (``agent_chat_changed``, ``{projectId, attachmentIds}``), and a
tab that read that chat reads it again, with no reload. An ask's own
exchange is told by its own events alone, so no tab is told it twice. A
watcher's tab is told nothing, and so is a tab of another dataflow.

The room is told at once, then at most once more per dataflow per wait
(``CHAT_CHANGES_TOLD_EVERY_S``): the chats written during a wait are named,
all in one word, when it ends. Each word is told once its write is in the
chat's file, which a tab told reads at once.

alice owns the dataflows, bob is an editor she invited, and carol watches.
The app runs on a SQLite file, as the room's other tests do. A word can come
from a job's thread, or when a wait ends, so each test reads what its tabs
heard over a while.

On main, where the room is told nothing of these writes, every test fails at
its check of what the tabs were told.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_agent_changes import _ask, _setup, _undo
from utk_curio.backend.tests.test_agents.test_dataset_discovery_routes import URL, _Harness
from utk_curio.backend.tests.test_agents.test_map_edits_grounding import _write_tail
from utk_curio.backend.tests.test_agents.test_turn_jobs import _end_turns, _tab

ALICE = "alice-token-room-chats"
BOB = "bob-token-room-chats"
CAROL = "carol-token-room-chats"
#: The room's namespace, as a tab joins it.
NAMESPACE = "/collab"
#: What the room tells a tab when the server changed one of the dataflow's chats.
EVENT = "agent_chat_changed"
#: How long a test reads what its tabs were told: past the end of any write.
HEARD_FOR_S = 1.5
#: How long the tabs wait before they join: past the wait after a word of the
#: writes made before them, whose last word would come to them otherwise.
QUIET_S = 0.5
NEW_CODE = "return input_0.sum()"


@pytest.fixture()
def flow(tmp_curio, tmp_path):
    """alice's dataflow, a loader feeding a sum, with the Node Builder
    attached to the sum; bob invited to edit it, carol signed in and invited
    to nothing. On a SQLite file, as on a server."""
    from utk_curio.backend.app import create_app
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.app.users.models import User, UserSession
    from utk_curio.backend.extensions import db
    from utk_curio.backend.tests._unit_fixtures import TestConfig

    class FileTestConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'room-chats.db'}"

    application = create_app(FileTestConfig)
    with application.app_context():
        db.create_all()
        people = {}
        for username, name, token in (("alice", "Alice", ALICE), ("bob", "Bob", BOB), ("carol", "Carol", CAROL)):
            person = User(username=username, name=name, email=f"{username}@test.com")
            db.session.add(person)
            db.session.flush()
            db.session.add(UserSession(user_id=person.id, token=token))
            people[username] = person
        db.session.commit()
        client = application.test_client()
        project, att = _setup(client, people["alice"], ALICE, target={"kind": "node", "targetId": "sum"})
        access.add_editor(people["alice"], project, "bob")
        yield SimpleNamespace(app=application, client=client, project=project, att=att, **people)
        _end_turns()
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def _tabs(flow, project: str) -> dict:
    """A tab of alice's, one of bob's and one of carol's in *project*'s room,
    joined once the room was told the writes made before them."""
    time.sleep(QUIET_S)
    room = SimpleNamespace(app=flow.app, project=project)
    return {name: _tab(room, token) for name, token in (("alice", ALICE), ("bob", BOB), ("carol", CAROL))}


def _leave(tabs: dict) -> None:
    for socket in tabs.values():
        socket.disconnect(namespace=NAMESPACE)


def _heard(tabs: dict, seconds: float = HEARD_FOR_S) -> dict[str, list[dict]]:
    """What the room told each tab of the dataflow's chats over *seconds*."""
    heard: dict[str, list[dict]] = {name: [] for name in tabs}
    end = time.monotonic() + seconds
    while True:
        for name, socket in tabs.items():
            heard[name] += [e["args"][0] for e in socket.get_received(namespace=NAMESPACE) if e["name"] == EVENT]
        if time.monotonic() >= end:
            return heard
        time.sleep(0.05)


def _chats(flow, project: str) -> dict[str, list]:
    """Every chat of *project* as the server holds it, by attachment."""
    listed = flow.client.get(f"/api/agents/projects/{project}/attachments", headers=_auth(ALICE))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    chats = {}
    for card in listed.get_json()["attachments"]:
        read = flow.client.get(
            f"/api/agents/projects/{project}/attachments/{card['attachmentId']}/session", headers=_auth(ALICE),
        )
        assert read.status_code == 200, read.get_data(as_text=True)
        chats[card["attachmentId"]] = read.get_json()["turns"]
    return chats


def _written(before: dict, after: dict) -> set[str]:
    """The chats whose turns differ from *before* to *after*."""
    return {attachment for attachment, turns in after.items() if turns != before.get(attachment, [])}


def _the_editors_are_told_of(project: str, tabs: dict, written: set[str]) -> None:
    """alice's tab and bob's were told of each chat in *written*, and of no
    other, each word naming the dataflow and its chats; carol's of none."""
    heard = _heard(tabs)
    for name in ("alice", "bob"):
        told = {attachment for e in heard[name] for attachment in e.get("attachmentIds") or []}
        assert told == written, (
            f"{name}'s tab was told of the chats {sorted(told)}, not of the chats the server wrote: {sorted(written)}")
        assert all(
            e == {"projectId": project, "attachmentIds": e["attachmentIds"]} and e["attachmentIds"] for e in heard[name]
        ), heard[name]
    assert heard["carol"] == [], "a watcher's tab was told of the dataflow's chats"


def _a_loader_waiting_for_its_source(flow, monkeypatch) -> _Harness:
    """alice's dataflow whose plan, landed by the Dataflow Builder, has a
    loader with no source, and which bob edits."""
    from utk_curio.backend.app.projects import access

    h = _Harness(flow.client, flow.alice, ALICE, monkeypatch)
    access.add_editor(flow.alice, h.pid, "bob")
    return h


def test_a_solves_turns_and_the_task_it_hands_the_dataset_finder_are_told_to_the_owners_and_the_editors_tabs(
    flow, monkeypatch,
):
    """alice's row Solve of a loader with no source hands the loader's Dataset
    Finder a task, whose candidates come to the Finder's chat and to the
    Dataflow Builder's, the chat that asked: writes of the server's, in no
    ask. alice's tab and bob's are told of each chat the Solve wrote, and of
    no other; carol's tab is told nothing."""
    h = _a_loader_waiting_for_its_source(flow, monkeypatch)
    tabs = _tabs(flow, h.pid)
    try:
        before = _chats(flow, h.pid)
        h.validate("load")
        written = _written(before, _chats(flow, h.pid))
        assert {h.finder_attachment_id(), h.att} <= written, (written, h.finder_attachment_id(), h.att)

        _the_editors_are_told_of(h.pid, tabs, written)
    finally:
        _leave(tabs)


def test_a_picks_source_recorded_turns_are_told_to_the_owners_and_the_editors_tabs(flow, monkeypatch):
    """The dev check's gap: bob picks the loader's source on its candidates
    card. Its Source recorded turn goes into the Finder's chat and into the
    Dataflow Builder's, which asked for the candidates. alice's tab and bob's
    are told of both chats, so a chat open in either shows the turn with no
    reload. carol's tab is told nothing, and nor is alice's tab on her other
    dataflow."""
    h = _a_loader_waiting_for_its_source(flow, monkeypatch)
    h.validate("load")
    finder = h.finder_attachment_id()
    tabs = _tabs(flow, h.pid)
    elsewhere = _tab(flow, ALICE)
    try:
        before = _chats(flow, h.pid)
        r = flow.client.post(
            f"/api/agents/projects/{h.pid}/attachments/{finder}/dataset-selection",
            json={"picks": [{"lane": "external", "key": URL}]}, headers=_auth(BOB),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        written = _written(before, _chats(flow, h.pid))
        assert {finder, h.att} <= written, (written, finder, h.att)

        _the_editors_are_told_of(h.pid, tabs, written)
        assert _heard({"elsewhere": elsewhere}, seconds=0)["elsewhere"] == [], (
            "a tab of another dataflow was told of this one's chats")
    finally:
        _leave({**tabs, "elsewhere": elsewhere})


def test_an_undo_is_told_and_an_asks_own_exchange_only_by_its_ask(flow, monkeypatch):
    """alice asks the Node Builder to rewrite the sum. Its reply and the
    change card it holds reach the tabs as the ask's own events, so no tab is
    told of the chat besides them. bob then undoes the change, a write of the
    server's into the chat: its card turns undone. alice's tab and bob's are
    told of the chat once, for the Undo; carol's tab is told nothing."""
    tabs = _tabs(flow, flow.project)
    try:
        body, _ = _ask(flow.client, ALICE, flow.project, flow.att, monkeypatch,
                       [_write_tail("sum", NEW_CODE), "Written."])
        [card] = [part for part in body["content"] if part["type"] == "change"]
        assert _heard(tabs) == {"alice": [], "bob": [], "carol": []}, "an ask's own exchange was told twice"

        undone = _undo(flow.client, BOB, flow.project, flow.att, card["changeId"])
        assert undone.status_code == 200, undone.get_json()
        assert undone.get_json()["status"] == "undone"

        heard = _heard(tabs)
        for name in ("alice", "bob"):
            assert heard[name] == [{"projectId": flow.project, "attachmentIds": [flow.att]}], (
                f"{name}'s tab was not told once that the Undo changed the Node Builder's chat: {heard[name]}")
        assert heard["carol"] == [], "a watcher's tab was told of the dataflow's chats"
    finally:
        _leave(tabs)


def test_a_cleared_chat_is_told_to_the_owners_and_the_editors_tabs(flow):
    """bob clears the Node Builder's chat. alice's tab and bob's are told of
    it, so a tab that shows the chat empties it; carol's tab is told nothing."""
    from utk_curio.backend.app.agents.repositories import sessions
    from utk_curio.backend.app.projects.services import _user_dir_key

    listed = flow.client.get(f"/api/agents/projects/{flow.project}/attachments", headers=_auth(ALICE)).get_json()
    session_id = next(c["sessionId"] for c in listed["attachments"] if c["attachmentId"] == flow.att)
    sessions.append_turns(_user_dir_key(flow.alice), flow.project, session_id, flow.att, [
        sessions.make_turn("user", "What does it do?"), sessions.make_turn("agent", "It sums its input."),
    ])
    tabs = _tabs(flow, flow.project)
    try:
        r = flow.client.delete(f"/api/agents/projects/{flow.project}/attachments/{flow.att}/session",
                               headers=_auth(BOB))
        assert r.status_code == 200, r.get_data(as_text=True)
        assert _chats(flow, flow.project)[flow.att] == []

        heard = _heard(tabs)
        for name in ("alice", "bob"):
            assert heard[name] == [{"projectId": flow.project, "attachmentIds": [flow.att]}], (
                f"{name}'s tab was not told once that bob cleared the Node Builder's chat: {heard[name]}")
        assert heard["carol"] == [], "a watcher's tab was told of the dataflow's chats"
    finally:
        _leave(tabs)


def test_a_burst_of_writes_is_told_at_once_then_in_one_word_naming_every_chat_when_the_wait_ends(
    flow, monkeypatch,
):
    """Four writes in a row into three chats, well inside one wait, as a
    build's turns come: each tab is told the first at once, naming its chat,
    and the three after it in one word when the wait ends, naming every chat
    they wrote, so each tab reads each of those chats once more and no more.
    At most one word per wait: a build that writes many turns costs each tab
    a read of each chat per wait, not one per write."""
    from utk_curio.backend.app.agents.application.turns import turn_jobs
    from utk_curio.backend.app.agents.repositories import sessions
    from utk_curio.backend.app.projects.services import _user_dir_key

    monkeypatch.setattr(turn_jobs, "CHAT_CHANGES_TOLD_EVERY_S", 3.0)
    ukey = _user_dir_key(flow.alice)
    chats = {attachment: uuid.uuid4().hex for attachment in ("att-one", "att-two", "att-three")}
    tabs = _tabs(flow, flow.project)
    try:
        for attachment in ("att-one", "att-two", "att-one", "att-three"):
            sessions.append_turns(ukey, flow.project, chats[attachment], attachment, [
                sessions.make_turn("agent", f"Solved a node for {attachment}."),
            ])

        at_once = _heard(tabs)
        for name in ("alice", "bob"):
            assert at_once[name] == [{"projectId": flow.project, "attachmentIds": ["att-one"]}], (
                f"{name}'s tab was not told the burst's first write at once, and only it, "
                f"before the wait ended: {at_once[name]}")
        when_it_ends = _heard(tabs, seconds=3.0)
        for name in ("alice", "bob"):
            words = when_it_ends[name]
            assert len(words) == 1, (
                f"{name}'s tab was told the burst's other writes in {len(words)} words, not one: {words}")
            assert words[0]["projectId"] == flow.project, words
            assert sorted(words[0]["attachmentIds"]) == ["att-one", "att-three", "att-two"], (
                f"the word at the end of the wait did not name every chat written during it: {words}")
        assert at_once["carol"] == [] and when_it_ends["carol"] == [], "a watcher's tab was told of the chats"
    finally:
        _leave(tabs)


def test_each_word_is_told_once_its_write_is_in_the_chats_file(flow, monkeypatch):
    """A tab told of a chat reads it at once, from whichever backend process
    owns the dataflow, which reads the chat's file. So when the room tells a
    word, the write it is for is already in the file: a turn appended, a
    card's status set, a cleared chat. Each write here comes after the wait of
    the one before it has ended, so each is told at once."""
    from utk_curio.backend.app.agents.repositories import sessions
    from utk_curio.backend.app.collaboration import roles
    from utk_curio.backend.app.projects.services import _user_dir_key

    ukey = _user_dir_key(flow.alice)
    listed = flow.client.get(f"/api/agents/projects/{flow.project}/attachments", headers=_auth(ALICE)).get_json()
    session_id = next(c["sessionId"] for c in listed["attachments"] if c["attachmentId"] == flow.att)
    # What the chat's file held each time the room told a word of the dataflow's chats.
    on_disk: list[list[dict]] = []
    telling = roles.tell_editors

    def tell_editors(project_id, event, payload, *, app=None):
        if event == EVENT and project_id == flow.project:
            on_disk.append(sessions.read_turns(ukey, flow.project, session_id))
        return telling(project_id, event, payload, app=app)

    monkeypatch.setattr(roles, "tell_editors", tell_editors)
    change = {"type": "change", "changeId": "change-1", "kind": "content", "summary": "Rewrote the sum",
              "status": "applied"}
    tabs = _tabs(flow, flow.project)
    try:
        turn = sessions.make_turn("agent", "Rewrote the sum.", content=[change])
        sessions.append_turns(ukey, flow.project, session_id, flow.att, [turn])
        heard = _heard(tabs)
        assert heard["alice"], "the room told alice's tab nothing of the turn appended"
        assert on_disk and on_disk[-1] == [turn], (
            f"the room told of the appended turn before the chat's file held it: {on_disk}")

        on_disk.clear()
        assert sessions.update_change_status(ukey, flow.project, session_id, "change-1", "undone")
        heard = _heard(tabs)
        assert heard["alice"], "the room told alice's tab nothing of the card's new status"
        assert on_disk and on_disk[-1][0]["content"][0]["status"] == "undone", (
            f"the room told of the card's new status before the chat's file held it: {on_disk}")

        on_disk.clear()
        sessions.clear_turns(ukey, flow.project, session_id, flow.att)
        heard = _heard(tabs)
        assert heard["alice"], "the room told alice's tab nothing of the cleared chat"
        assert on_disk == [[]], f"the room told of the cleared chat before its file was empty: {on_disk}"
    finally:
        _leave(tabs)
