"""Updates that wait for a dataflow's doc together are applied as one batch.

A socket's events come one at a time, and an update is answered once the
server has applied it, so a tab never has two updates waiting. Under a burst
of typing in a room, what waits is the doc: an update from each of several
tabs. The thread that finds none being applied applies every update waiting
then, each in a transaction of its own, its tab the origin; the batch makes one
write to the log, a record each, and one message to each tab, every change of
the batch but the tab's own merged into one update (``dataflow_docs._update``).
Each update alone was a write and a message to every other tab, which the
stress tiers' bursts of 50 and 100 typing users could not carry (run
40783748468).

The tabs are the doc tests' (``_ydoc_client.py``), each on a Flask-SocketIO
test client of its own, sending from a thread of its own. A burst here holds
its first update in a slow apply, under the doc's lock, until every other
update reached the server, and :data:`SETTLE_S` more: the time those updates'
threads take to wait for the doc, a few locks no one holds.
"""

from __future__ import annotations

import threading
import time

import pytest

from ._support import invite, make_project, make_user

#: alice's dataflow: one node with code.
SPEC = {
    "dataflow": {
        "nodes": [{"id": "loader", "type": "curio.builtin/code", "x": 10, "y": 20,
                   "content": "x = 1\n", "out": "DATAFRAME", "in": "DEFAULT", "goal": "",
                   "metadata": {"keywords": []}}],
        "edges": [],
        "name": "Shared", "task": "", "timestamp": 1, "provenance_id": "Shared",
    },
}

#: The day the doc's log files its changes under.
DAY = "2026-10-28"
#: How long a held apply goes on waiting once every update reached the server.
SETTLE_S = 0.5
#: The longest any wait here takes before the test fails: a hang is a finding.
WAIT_S = 20.0


class _Room:
    """alice's dataflow, bob invited to edit it, carol not."""

    def __init__(self, application, tokens, project_id, owner_key):
        self.application = application
        self.tokens = tokens
        self.project_id = project_id
        self.owner_key = owner_key

    @property
    def docs(self):
        from utk_curio.backend.app.collaboration import dataflow_docs

        return dataflow_docs

    def tab(self, account: str):
        """A tab of the dataflow, signed in as *account*, joined and synced."""
        from ._ydoc_client import synced_tab

        return synced_tab(self.application, self.tokens[account], self.project_id)

    def logged(self, doc_id: str) -> list:
        return self.docs.logged_updates(self.owner_key, self.project_id, doc_id, DAY)


@pytest.fixture()
def room(doc_app, monkeypatch):
    application, socketio = doc_app
    assert socketio is not None, "every backend serves Socket.IO"
    from utk_curio.backend.app.projects import storage

    users, tokens = {}, {}
    for name in ("alice", "bob", "carol"):
        users[name], session = make_user(name)
        tokens[name] = session.token
    project_id = make_project(users["alice"])
    invite(project_id, users["alice"], users["bob"])
    owner_key = str(users["alice"].id)
    storage.write_spec(owner_key, project_id, SPEC)
    room = _Room(application, tokens, project_id, owner_key)
    monkeypatch.setattr(room.docs, "_today", lambda: DAY)
    return room


def _wait_for(ready, message: str) -> None:
    deadline = time.monotonic() + WAIT_S
    while not ready():
        assert time.monotonic() < deadline, message
        time.sleep(0.005)


class _Burst:
    """The server's doc of the room's dataflow, its applies made slow at will,
    with each apply's thread, each write to its log (the records it held) and
    each message the server took."""

    def __init__(self, room, monkeypatch):
        self.entry = room.docs._open_entry(room.project_id)
        assert self.entry is not None, "the server holds no doc of the dataflow"
        self.applies: list = []
        self.writes: list = []
        self.arrived: list = []
        self.going = threading.Event()
        self.going.set()
        apply_update = self.entry.doc.apply_update
        append = room.docs._append
        receive = room.docs.receive

        def slow(update):
            self.applies.append(threading.current_thread())
            assert self.going.wait(WAIT_S), "the held apply was never let go"
            return apply_update(update)

        def counted(entry, updates):
            self.writes.append(len(updates))
            return append(entry, updates)

        def arriving(sid, payload):
            self.arrived.append(sid)
            return receive(sid, payload)

        monkeypatch.setattr(self.entry.doc, "apply_update", slow)
        monkeypatch.setattr(room.docs, "_append", counted)
        monkeypatch.setattr(room.docs, "receive", arriving)

    def run(self, first, *rest) -> None:
        """Send *first*, a function that sends, and hold its apply; then send
        each of *rest*, each from a thread of its own, and let the apply go
        once they all reached the server."""
        self.applies.clear()
        self.writes.clear()
        self.arrived.clear()
        self.going.clear()
        threads = [threading.Thread(target=first)]
        threads[0].start()
        _wait_for(lambda: len(self.applies) == 1, "the first update never reached its apply")
        for send in rest:
            threads.append(threading.Thread(target=send))
            threads[-1].start()
        _wait_for(lambda: len(self.arrived) == len(threads), "an update never reached the server")
        time.sleep(SETTLE_S)
        self.going.set()
        for thread in threads:
            thread.join(WAIT_S)
            assert not thread.is_alive(), "a tab is still waiting for its update's answer"


def _type(text: str):
    """A change that types *text* at the start of loader's code."""

    def change(doc):
        from pycrdt import Map

        doc.get("nodes", type=Map)["loader"]["content"].insert(0, text)

    return change


def _sender(tab, change, answers: dict, name: str):
    """A function that makes *change* in *tab* and sends it, its acks kept in
    *answers* under *name*, or what it raised."""

    def send():
        try:
            answers[name] = tab.edit(change)
        except Exception as exc:  # noqa: BLE001 - reported by the test, never lost in a thread
            answers[name] = exc

    return send


def _typist(tab, word: str, answers: list):
    """A function that types *word* into loader's code a key at a time, each
    after the tab's own last one, as an editor's cursor stays; each key's ack
    kept in *answers* with what the tab then held of its own changes."""

    def run():
        from pycrdt import Assoc, Map

        sticky = None
        try:
            for char in word:
                def change(doc, char=char):
                    nonlocal sticky
                    content = doc.get("nodes", type=Map)["loader"]["content"]
                    at = 0 if sticky is None else sticky.get_index()
                    content.insert(at, char)
                    sticky = content.sticky_index(at + len(char), Assoc.BEFORE)

                [ack] = tab.edit(change)
                answers.append((ack, _own_clock(tab)))
        except Exception as exc:  # noqa: BLE001 - reported by the test, never lost in a thread
            answers.append(exc)

    return run


def _own_clock(tab) -> dict:
    """The clock *tab* holds for its own client, as an answer's ``kept`` names it."""
    from utk_curio.backend.app.collaboration import dataflow_docs

    client = tab.doc.client_id
    return {str(client): dataflow_docs._clocks(tab.doc)[client]}


def _take(tabs: dict) -> dict:
    """What the server sent each tab since the last take, its updates applied."""
    taken = {}
    for name, tab in tabs.items():
        tab.pump()
        taken[name], tab.received = tab.received, []
    return taken


def _after(state: bytes, updates) -> dict:
    """The dataflow of a doc of *state* once *updates* are applied to it one
    by one."""
    from pycrdt import Doc

    from utk_curio.backend.app.collaboration import doc_mapping

    doc = Doc()
    doc.apply_update(state)
    for update in updates:
        doc.apply_update(update)
    return doc_mapping.doc_to_dataflow(doc)


def _code(dataflow: dict) -> str:
    return next(node for node in dataflow["nodes"] if node["id"] == "loader")["content"]


def _room_of_tabs(room) -> tuple[dict, dict]:
    """Four editing tabs, two of alice's and two of bob's, and carol's, a
    watcher's; all synced, and nothing left for them to read."""
    tabs = {name: room.tab(account) for name, account in
            (("alice", "alice"), ("ana", "alice"), ("bob", "bob"), ("bea", "bob"))}
    everyone = {**tabs, "carol": room.tab("carol")}
    _take(everyone)
    return tabs, everyone


def test_a_burst_from_several_tabs_is_one_batch_one_write_and_one_message_to_each_tab(room, monkeypatch):
    from utk_curio.backend.app.collaboration import doc_mapping

    from ._ydoc_client import Origins

    tabs, everyone = _room_of_tabs(room)
    burst = _Burst(room, monkeypatch)
    doc_id = tabs["alice"].doc_id

    # An update alone is applied, logged and relayed at once, by the thread
    # that sent it, and answered with what the doc kept.
    [ack] = tabs["alice"].edit(_type("# alone\n"))
    assert ack == {"ok": True, "kept": _own_clock(tabs["alice"])}, ack
    assert burst.applies == [threading.current_thread()] and burst.writes == [1]
    assert {name: len(got) for name, got in _take(everyone).items()} == {
        "alice": 0, "ana": 1, "bob": 1, "bea": 1, "carol": 1,
    }, "an update alone did not reach each other tab at once"

    # A burst: alice's update holds the doc while ana's, bob's and bea's come.
    before = burst.entry.doc.get_update()
    origins = Origins(room.project_id)
    for tab in tabs.values():
        tab.sent.clear()
    answers: dict = {}
    burst.run(*(_sender(tab, _type(f"# {name}\n"), answers, name) for name, tab in tabs.items()))
    taken = _take(everyone)

    for name, tab in tabs.items():
        assert answers.get(name) == [{"ok": True, "kept": _own_clock(tab)}], (name, answers.get(name))
    assert len(origins.seen) == 4 and len(set(origins.seen)) == 4, (
        f"each update was not applied in a transaction of its own, its tab the origin: {origins.seen}"
    )
    messages = {name: len(got) for name, got in taken.items()}
    assert sum(messages.values()) < 4 * (len(everyone) - 1), (
        f"each update was relayed alone, to every other tab: {messages} "
        "(a batch of ana's, bob's and bea's sends each tab one message)"
    )
    assert sum(burst.writes) == 4 and len(burst.writes) < 4, (
        f"each update was written to the log alone: {burst.writes}, the records of each write"
    )
    for name, got in taken.items():
        code = _code(_after(before, got))
        for other in tabs:
            assert (f"# {other}\n" in code) == (other != name), (
                f"{name}'s tab was sent {'its own change' if other == name else 'no change of ' + other}: {code!r}"
            )
    one_by_one = _after(before, [update for tab in tabs.values() for update in tab.sent])
    assert doc_mapping.doc_to_dataflow(burst.entry.doc) == one_by_one, "the batch left another doc"
    for name, tab in everyone.items():
        assert tab.dataflow() == one_by_one, f"{name}'s tab holds another doc than the server's"
    assert len(room.logged(doc_id)) == 5, "the log does not hold a record for each update"

    # Every tab typing at once, a key at a time: each tab's keys stay in the
    # order it typed them, and each is answered with what the doc kept of it.
    before = burst.entry.doc.get_update()
    for tab in tabs.values():
        tab.sent.clear()
    keys: dict = {name: [] for name in tabs}
    threads = [threading.Thread(target=_typist(tab, f"<{name}>", keys[name])) for name, tab in tabs.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT_S)
        assert not thread.is_alive(), "a tab is still waiting for its key's answer"
    _take(everyone)
    for name, answered in keys.items():
        assert len(answered) == len(f"<{name}>"), (name, answered)
        for ack, kept in answered:
            assert ack == {"ok": True, "kept": kept}, (name, ack, kept)
    one_by_one = _after(before, [update for tab in tabs.values() for update in tab.sent])
    assert doc_mapping.doc_to_dataflow(burst.entry.doc) == one_by_one
    for name, tab in everyone.items():
        assert tab.dataflow() == one_by_one, f"{name}'s tab holds another doc than the server's"
    code = _code(one_by_one)
    for name in tabs:
        assert f"<{name}>" in code, f"{name}'s keys are not in the order typed: {code!r}"


def test_an_update_that_does_not_apply_is_refused_alone_and_the_rest_of_its_batch_lands(room, monkeypatch):
    from pycrdt import create_update_message

    tabs, everyone = _room_of_tabs(room)
    burst = _Burst(room, monkeypatch)
    answers: dict = {}

    def broken():
        answers["bob"] = tabs["bob"].send(create_update_message(b"\x01\x02\x03"))

    burst.run(
        _sender(tabs["alice"], _type("# alice\n"), answers, "alice"),
        _sender(tabs["ana"], _type("# ana\n"), answers, "ana"),
        broken,
        _sender(tabs["bea"], _type("# bea\n"), answers, "bea"),
    )

    assert answers.get("bob") == {"ok": False, "error": "invalid_message"}, answers.get("bob")
    for name in ("alice", "ana", "bea"):
        assert answers.get(name) == [{"ok": True, "kept": _own_clock(tabs[name])}], (name, answers.get(name))
    assert sum(burst.writes) == 3 and len(burst.writes) < 3, (
        f"each update that applied was written to the log alone: {burst.writes}"
    )
    _take(everyone)
    seen = everyone["carol"].dataflow()
    assert sorted(line for line in _code(seen).splitlines() if line.startswith("# ")) == [
        "# alice", "# ana", "# bea",
    ], _code(seen)
    for name, tab in everyone.items():
        assert tab.dataflow() == seen, f"{name}'s tab holds another doc than carol's"


def test_steady_typing_wakes_the_thread_that_writes_the_docs_only_when_a_write_becomes_due(room, monkeypatch):
    """A doc's write is due a second after its last change and at most ten
    after its first, so a later change never makes it due sooner: the thread
    that writes the docs is woken when a doc has a write due, not at each
    keystroke, which a burst of typing made hundreds of times a second."""
    woken = []

    class _Counted(threading.Condition):
        def notify_all(self):
            woken.append(threading.current_thread())
            super().notify_all()

    alice = room.tab("alice")
    monkeypatch.setattr(room.docs, "_wake", _Counted(room.docs._lock))
    for char in "typing":
        assert alice.edit(_type(char))[0]["ok"] is True
    assert len(woken) == 1, f"the writing thread was woken {len(woken)} times for one write due"

    assert room.docs.flush(room.project_id) is True
    assert alice.edit(_type("!"))[0]["ok"] is True
    assert len(woken) == 2, "a change after the doc was written did not make its next write due"
