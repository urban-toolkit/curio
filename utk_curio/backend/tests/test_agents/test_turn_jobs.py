"""A chat turn is a job of the server (step 15b).

The turn route answers at once, and the turn runs on a thread of the server,
so it goes on when the tab that asked closes. One turn runs at a time per
attachment: a second ask waits its turn, starts once the turn before it ended
and reads that turn's exchange, and whoever asked it can withdraw it while it
waits; asks to different attachments run side by side. Whoever asked, the
owner or any editor can stop a running turn, and what it said until then
stays, named as stopped by whoever stopped it. Every event of a turn reaches
the tabs of the owner and the editors in the dataflow's room, a watcher's
never, and a chat read while a turn runs holds the turn as it stands. A turn
on the server still names the editor who asked it, and holds only the
editor's keys.

alice owns the dataflow, bob is an editor she invited, and carol watches. The
app runs on a SQLite file: a turn's thread and the test's requests use the
database at once, which the in-memory engine's one connection does not allow.

Each test's first check is of what main lacks, so a before-run fails test by
test at an assertion.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_agent_changes import _setup
from utk_curio.backend.tests.test_agents.test_editors_drive_agents import (
    ALICE_KEY,
    BOB_KEY,
    _person,
    _save_key,
    _texts,
)
from utk_curio.backend.tests.test_agents.test_map_edits_grounding import _write_tail
from utk_curio.backend.tests.test_agents.test_source_grounding_routes import _attach

NB = "agent.curio.node-builder@1"
ALICE = "alice-token-turns"
BOB = "bob-token-turns"
CAROL = "carol-token-turns"
NEW_CODE = "return input_0.sum()"
#: The room's namespace, as a tab joins it.
NAMESPACE = "/collab"
#: How long a test waits for a turn's step before it fails.
WAIT_S = 15.0
PROVIDERS = "utk_curio.backend.app.agents.infrastructure.providers"


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
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'turns.db'}"

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


def _end_turns() -> None:
    """Stop, and wait for, any turn a test left running before its tables go."""
    try:
        from utk_curio.backend.app.agents.application.turns import turn_jobs
    except ImportError:  # a checkout whose turns run in their request
        return
    for job in turn_jobs.stop_all():
        if job.thread is not None:
            job.thread.join(WAIT_S)


class _Held:
    """A reply the model writes part of, then waits to write the rest of
    until the test lets it (``go``); ``entered`` once it waits."""

    def __init__(self, *, before=(), after=("Done.",)):
        self.before = tuple(before)
        self.after = tuple(after)
        self.entered = threading.Event()
        self.go = threading.Event()


class _Model:
    """The model: each call's thread and messages, answered with the replies
    scripted for the message asked, else in order. A held reply waits for the
    test. The conversation's title call is answered apart."""

    def __init__(self, monkeypatch, *replies, by_message=None):
        self.replies = list(replies)
        self.by_message = {message: list(answers) for message, answers in (by_message or {}).items()}
        self.calls: list = []
        self.lock = threading.Lock()
        monkeypatch.setattr(f"{PROVIDERS}.stream_chat_turn", self.stream)
        monkeypatch.setattr(f"{PROVIDERS}.run_chat_turn", self.run)

    def _take(self, messages):
        with self.lock:
            self.calls.append((threading.get_ident(), messages))
            asked = next((m.get("content") for m in reversed(messages)
                          if m.get("role") == "user" and m.get("content") in self.by_message), None)
            answers = self.by_message[asked] if asked is not None else self.replies
            return answers.pop(0) if answers else "Nothing more."

    @staticmethod
    def _titled(messages) -> bool:
        from utk_curio.backend.app.agents.application.turns import titles

        return bool(messages) and messages[0].get("content") == titles.title_prompt()

    def stream(self, config, messages, **kwargs):
        reply = self._take(messages)
        if not isinstance(reply, _Held):
            yield reply
            return
        yield from reply.before
        reply.entered.set()
        assert reply.go.wait(WAIT_S), "the test never let the model go on"
        yield from reply.after

    def run(self, config, messages, **kwargs):
        if self._titled(messages):
            return "Title"
        reply = self._take(messages)
        if not isinstance(reply, _Held):
            return reply
        reply.entered.set()
        assert reply.go.wait(WAIT_S), "the test never let the model go on"
        return "".join(reply.before + reply.after)


def _ask(flow, token, message, *, att=None, ask_id=None):
    return flow.client.post(
        f"/api/agents/projects/{flow.project}/attachments/{att or flow.att}/turns",
        json={"message": message, **({"askId": ask_id} if ask_id else {})}, headers=_auth(token),
    )


def _envelopes(text: str) -> list[dict]:
    """The turn events a follow of an ask said, each its room envelope."""
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if lines.get("event") == "turn":
            out.append(json.loads(lines["data"]))
    return out


def _followed(flow, token, ask_id, *, att=None) -> list[dict]:
    """The ask as it stood, then each of its events until its end."""
    r = flow.client.get(
        f"/api/agents/projects/{flow.project}/attachments/{att or flow.att}/turns/{ask_id}/stream",
        headers=_auth(token),
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    return _envelopes(r.get_data(as_text=True))


def _end(flow, token, ask_id, *, att=None) -> dict:
    """How the ask ended, once it has: its last event, which the ask as it
    stood holds when it had ended before the follow began."""
    envelopes = _followed(flow, token, ask_id, att=att)
    last = envelopes[-1]
    if last["event"] == "snapshot":
        assert last["data"]["state"] == "ended", last
        return last["data"]["events"][-1]
    return last


def _session(flow, token, *, att=None) -> dict:
    r = flow.client.get(f"/api/agents/projects/{flow.project}/attachments/{att or flow.att}/session",
                        headers=_auth(token))
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _said(turns) -> list[tuple]:
    return [(turn["role"], turn["text"]) for turn in turns]


def _eventually(read, until, seconds: float = WAIT_S):
    """What *read* answers once *until* holds of it, or its last answer."""
    deadline = time.monotonic() + seconds
    value = read()
    while not until(value) and time.monotonic() < deadline:
        time.sleep(0.05)
        value = read()
    return value


# ---------------------------------------------------------------------------
# A turn runs on the server
# ---------------------------------------------------------------------------

def test_the_turn_route_answers_at_once_and_the_turn_runs_on_the_server(flow, monkeypatch):
    """bob asks the Node Builder a question. The route answers before the
    model does, the model is asked on a thread of the server, not in bob's
    request, and the reply lands in the chat they share."""
    held = _Held(after=("It sums its input.",))
    model = _Model(monkeypatch, held)
    ask_id = uuid.uuid4().hex

    r = _ask(flow, BOB, "What does it do?", ask_id=ask_id)
    assert r.status_code == 202, r.get_data(as_text=True)
    assert r.get_json() == {"askId": ask_id, "attachmentId": flow.att, "state": "running"}
    assert held.entered.wait(WAIT_S), "the turn never reached the model"
    assert model.calls[0][0] != threading.get_ident(), "the turn ran in the request that asked it"

    held.go.set()
    assert _end(flow, ALICE, ask_id)["event"] == "done"
    turns = _session(flow, ALICE)["turns"]
    assert _said(turns) == [("user", "What does it do?"), ("agent", "It sums its input.")]
    assert turns[0]["by"] == _person(flow.bob)


def test_a_streamed_ask_goes_on_when_its_tab_closes_the_stream(flow, monkeypatch):
    """alice's tab follows its own ask's stream and closes mid-reply. The
    turn goes on: its whole reply lands in the chat, and its run settles, as
    when the tab stays."""
    held = _Held(before=("Half of it.",), after=(" And the rest.",))
    _Model(monkeypatch, held)
    r = flow.client.post(f"/api/agents/projects/{flow.project}/attachments/{flow.att}/run/stream",
                         json={"message": "Explain the sum."}, headers=_auth(ALICE))
    assert r.status_code == 200, r.get_data(as_text=True)
    chunks = iter(r.response)
    assert b"event: execution" in next(chunks)
    assert held.entered.wait(WAIT_S), "the turn never reached the model while its tab followed it"
    r.close()  # the tab closes
    held.go.set()

    turns = _eventually(lambda: _session(flow, ALICE)["turns"], lambda found: len(found) == 2)
    assert _said(turns) == [("user", "Explain the sum."), ("agent", "Half of it. And the rest.")]
    assert turns[1]["execution"]["status"] == "ok"


# ---------------------------------------------------------------------------
# One turn at a time per attachment
# ---------------------------------------------------------------------------

def test_a_second_ask_waits_its_turn_and_reads_the_turn_before_it(flow, monkeypatch):
    """While alice's turn runs, bob asks the same agent: his ask waits, and a
    chat read now holds alice's turn as it stands, her message and the reply
    so far, then bob's ask, waiting. His turn starts once hers ended, and its
    model reads her exchange before his message."""
    first = _Held(before=("Looking at the sum.",), after=(" It adds the loader's rows.",))
    model = _Model(monkeypatch, first, "Yes, every row.")
    one, two = uuid.uuid4().hex, uuid.uuid4().hex

    r1 = _ask(flow, ALICE, "What does the sum do?", ask_id=one)
    assert r1.status_code == 202, r1.get_data(as_text=True)
    assert r1.get_json()["state"] == "running"
    assert first.entered.wait(WAIT_S), "the first turn never reached the model"
    r2 = _ask(flow, BOB, "Does it use every row?", ask_id=two)
    assert r2.status_code == 202, r2.get_data(as_text=True)
    assert r2.get_json()["state"] == "waiting"

    asks = _session(flow, BOB)["asks"]
    assert [(a["askId"], a["state"], a["message"]) for a in asks] == [
        (one, "running", "What does the sum do?"), (two, "waiting", "Does it use every row?"),
    ]
    assert asks[0]["by"] == _person(flow.alice) and asks[1]["by"] == _person(flow.bob)
    assert asks[0]["text"] == "Looking at the sum."
    assert [event["event"] for event in asks[0]["events"]] == ["execution"]
    assert len(model.calls) == 1, "the second turn started while the first ran"

    first.go.set()
    assert _end(flow, BOB, two)["event"] == "done"
    assert _said(_session(flow, ALICE)["turns"]) == [
        ("user", "What does the sum do?"), ("agent", "Looking at the sum. It adds the loader's rows."),
        ("user", "Does it use every row?"), ("agent", "Yes, every row."),
    ]
    second = [(m["role"], m["content"]) for m in model.calls[1][1] if m["role"] in ("user", "assistant")]
    read = [said for said in second if said in (
        ("user", "What does the sum do?"), ("assistant", "Looking at the sum. It adds the loader's rows."),
        ("user", "Does it use every row?"),
    )]
    assert read == [
        ("user", "What does the sum do?"), ("assistant", "Looking at the sum. It adds the loader's rows."),
        ("user", "Does it use every row?"),
    ], second


def test_asks_to_two_attachments_run_side_by_side(flow, monkeypatch):
    """The Node Builder on the loader and the one on the sum are asked at
    once: both turns are at the model before either answers."""
    loader = _attach(flow.client, ALICE, flow.project, NB, target={"kind": "node", "targetId": "load"})
    on_sum, on_loader = _Held(after=("The sum.",)), _Held(after=("The loader.",))
    _Model(monkeypatch, by_message={"About the sum?": [on_sum], "About the loader?": [on_loader]})
    first, second = uuid.uuid4().hex, uuid.uuid4().hex

    r1 = _ask(flow, ALICE, "About the sum?", ask_id=first)
    assert r1.status_code == 202, r1.get_data(as_text=True)
    r2 = _ask(flow, BOB, "About the loader?", att=loader, ask_id=second)
    assert r2.status_code == 202, r2.get_data(as_text=True)
    assert (r1.get_json()["state"], r2.get_json()["state"]) == ("running", "running")
    assert on_sum.entered.wait(WAIT_S) and on_loader.entered.wait(WAIT_S), "one turn waited for the other"

    on_sum.go.set()
    on_loader.go.set()
    assert _end(flow, ALICE, first)["event"] == "done"
    assert _end(flow, BOB, second, att=loader)["event"] == "done"
    assert _said(_session(flow, ALICE)["turns"])[-1] == ("agent", "The sum.")
    assert _said(_session(flow, ALICE, att=loader)["turns"])[-1] == ("agent", "The loader.")


def test_only_whoever_asked_withdraws_a_waiting_ask(flow, monkeypatch):
    """bob's ask waits behind alice's turn. Neither alice nor carol can
    withdraw it; bob can, and then it never runs and the chat keeps nothing
    of it. A withdrawn ask cannot be withdrawn again."""
    first = _Held(after=("Here.",))
    model = _Model(monkeypatch, first, "Never said.")
    one, two = uuid.uuid4().hex, uuid.uuid4().hex

    r1 = _ask(flow, ALICE, "First?", ask_id=one)
    assert r1.status_code == 202, r1.get_data(as_text=True)
    assert first.entered.wait(WAIT_S)
    r2 = _ask(flow, BOB, "Second?", ask_id=two)
    assert (r2.status_code, r2.get_json().get("state")) == (202, "waiting"), r2.get_data(as_text=True)

    path = f"/api/agents/projects/{flow.project}/attachments/{flow.att}/turns/{two}"
    assert flow.client.delete(path, headers=_auth(ALICE)).status_code == 403
    assert flow.client.delete(path, headers=_auth(CAROL)).status_code == 403
    withdrawn = flow.client.delete(path, headers=_auth(BOB))
    assert withdrawn.status_code == 200, withdrawn.get_data(as_text=True)
    assert withdrawn.get_json()["withdrawn"] is True
    assert [a["askId"] for a in _session(flow, ALICE)["asks"]] == [one]
    assert flow.client.delete(path, headers=_auth(BOB)).status_code == 409

    first.go.set()
    assert _end(flow, ALICE, one)["event"] == "done"
    assert _said(_session(flow, ALICE)["turns"]) == [("user", "First?"), ("agent", "Here.")]
    assert len(model.calls) == 1, "a withdrawn ask reached the model"


def test_the_owner_stops_an_editors_running_turn_and_a_watcher_cannot(flow, monkeypatch):
    """bob's turn is writing its reply when alice stops it; carol, who
    watches, may not. It stops at the model's next piece: what it said stays,
    as a reply stopped by alice. A turn no longer running cannot be stopped."""
    held = _Held(before=("I will rewrite it.",), after=(" Starting with the loader.",))
    _Model(monkeypatch, held)
    ask_id = uuid.uuid4().hex

    r = _ask(flow, BOB, "Rewrite the sum.", ask_id=ask_id)
    assert r.status_code == 202, r.get_data(as_text=True)
    assert held.entered.wait(WAIT_S)
    path = f"/api/agents/projects/{flow.project}/attachments/{flow.att}/turns/{ask_id}/stop"
    assert flow.client.post(path, headers=_auth(CAROL)).status_code == 403
    stopping = flow.client.post(path, headers=_auth(ALICE))
    assert stopping.status_code == 200, stopping.get_data(as_text=True)
    assert stopping.get_json()["stopping"] is True

    held.go.set()
    done = _end(flow, BOB, ask_id)
    assert done["event"] == "done" and done["data"]["stopped"] == {"by": _person(flow.alice)}, done
    turns = _session(flow, BOB)["turns"]
    assert _said(turns) == [("user", "Rewrite the sum."), ("agent", "I will rewrite it.")]
    assert turns[1]["execution"]["status"] == "stopped"
    assert turns[1]["execution"]["stoppedBy"] == _person(flow.alice)
    assert flow.client.post(path, headers=_auth(ALICE)).status_code == 409


def test_an_attachment_removed_ends_its_asks(flow, monkeypatch):
    """alice detaches the agent while its turn runs and bob's ask waits: his
    ask is withdrawn, never reaching the model, and the running turn stops at
    its next step, as its chat goes with it."""
    held = _Held(before=("Working on it.",), after=(" Still working.",))
    model = _Model(monkeypatch, held, "Never said.")
    one, two = uuid.uuid4().hex, uuid.uuid4().hex

    r1 = _ask(flow, ALICE, "First?", ask_id=one)
    assert r1.status_code == 202, r1.get_data(as_text=True)
    assert held.entered.wait(WAIT_S)
    r2 = _ask(flow, BOB, "Second?", ask_id=two)
    assert (r2.status_code, r2.get_json().get("state")) == (202, "waiting"), r2.get_data(as_text=True)

    detached = flow.client.delete(f"/api/agents/projects/{flow.project}/attachments/{flow.att}",
                                  headers=_auth(ALICE))
    assert detached.status_code == 200, detached.get_data(as_text=True)
    assert _end(flow, BOB, two)["event"] == "withdrawn"
    held.go.set()
    done = _end(flow, ALICE, one)
    assert done["event"] == "done" and done["data"]["stopped"] == {"by": None}, done
    assert len(model.calls) == 1, "a withdrawn ask reached the model"


# ---------------------------------------------------------------------------
# The room hears every turn; a watcher hears none
# ---------------------------------------------------------------------------

def _tab(flow, token):
    """A tab of the dataflow's room, joined, its join's events read."""
    socketio = flow.app.extensions.get("socketio")
    socket = socketio.test_client(flow.app, namespace=NAMESPACE, auth={"token": token})
    assert socket.is_connected(namespace=NAMESPACE)
    ack = socket.emit("join_session", {"projectId": flow.project}, namespace=NAMESPACE, callback=True)
    assert ack["ok"] is True, ack
    socket.get_received(namespace=NAMESPACE)
    return socket


def _told(socket) -> list[dict]:
    return [e["args"][0] for e in socket.get_received(namespace=NAMESPACE) if e["name"] == "agent_turn"]


def test_every_event_of_a_turn_reaches_the_owners_and_editors_tabs_and_no_watchers(flow, monkeypatch):
    """bob asks the Node Builder to rewrite the sum. alice's tab and his own
    are told each event of the turn, in order: that it was asked and by whom,
    that it started, its tool call, the change it landed, its reply and its
    end. carol's tab, a watcher's, is told nothing of it."""
    _Model(monkeypatch, _write_tail("sum", NEW_CODE), "Written.")
    tabs = {"alice": _tab(flow, ALICE), "bob": _tab(flow, BOB), "carol": _tab(flow, CAROL)}
    try:
        ask_id = uuid.uuid4().hex
        r = _ask(flow, BOB, "Rewrite the sum.", ask_id=ask_id)
        assert r.status_code == 202, r.get_data(as_text=True)
        assert _end(flow, BOB, ask_id)["event"] == "done"

        for name in ("alice", "bob"):
            told = _told(tabs[name])
            assert told, f"{name}'s tab was told nothing of the turn"
            assert {(e["projectId"], e["attachmentId"], e["askId"]) for e in told} == {
                (flow.project, flow.att, ask_id)}
            assert [e["seq"] for e in told] == list(range(len(told))), f"{name}'s tab missed an event"
            names = [e["event"] for e in told]
            assert names[:3] == ["asked", "started", "execution"] and names[-1] == "done", names
            assert {"tool_result", "change", "delta"} <= set(names), names
            assert told[0]["data"]["by"] == _person(flow.bob)
            assert told[0]["data"]["message"] == "Rewrite the sum."
            assert told[-1]["data"]["reply"].endswith("Written."), told[-1]
        assert _told(tabs["carol"]) == [], "a watcher's tab was told of the turn"
    finally:
        for socket in tabs.values():
            socket.disconnect(namespace=NAMESPACE)


# ---------------------------------------------------------------------------
# Who asked, on the server's thread
# ---------------------------------------------------------------------------

def test_an_editors_turn_on_the_server_is_named_after_the_editor_and_holds_only_the_editors_keys(
    flow, monkeypatch,
):
    """bob's turn runs on a thread that holds no request of his, yet it is
    his: its model is handed bob's saved keys and never alice's, and the
    change it lands is a point of the history named after bob."""
    from utk_curio.backend.app.collaboration import history
    from utk_curio.backend.app.projects.services import _user_dir_key

    _save_key(flow.alice, *ALICE_KEY)
    _save_key(flow.bob, *BOB_KEY)
    model = _Model(monkeypatch, _write_tail("sum", NEW_CODE), "Written.")
    ask_id = uuid.uuid4().hex

    r = _ask(flow, BOB, "Rewrite the sum.", ask_id=ask_id)
    assert r.status_code == 202, r.get_data(as_text=True)
    assert _end(flow, BOB, ask_id)["event"] == "done"

    asked = _texts(model.calls[0][1])
    assert "bobs-weather" in asked and "alices-census" not in asked
    newest = history.points(_user_dir_key(flow.alice), flow.project)[-1]
    assert (newest["kind"], newest["by"]) == ("agent", {"kind": "agent", "account": str(flow.bob.id), "agent": NB})
    listed = flow.client.get(f"/api/projects/{flow.project}/history", headers=_auth(BOB)).get_json()
    assert listed["versions"][-1]["what"] == "Node Builder, asked by Bob"
