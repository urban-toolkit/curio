"""A dataflow's doc takes its tabs' messages in batches, and no socket waits.

When nothing waits for the doc, a tab's update is applied at once, on its
socket's own thread, and answered in its ack, ``{ok, kept}``. Otherwise it
waits for the doc's thread and its ack is ``{ok, queued}`` at once, so the
socket goes on reading, its Engine.IO pings included. The doc's thread
applies batch after batch of what waits: each socket's updates are one
transaction, the socket its origin; the batch makes one write to the log, a
record a transaction, and sends each tab one message, every change of the
batch but the tab's own merged into one update; and each socket gets one
``yjs_kept`` message answering its updates the batch held. Awareness waits
with the updates: a batch keeps each client's latest state and sends each tab
one message, its own clients' left out (``dataflow_docs._take``).

Each update alone was a write and a message to every other tab, which the
stress tiers' bursts of 50 and 100 typing users could not carry (run
40783748468). With batches, but each socket waiting for its own update's
answer, the burst of 100 still lost every socket at Engine.IO's ping timeout
(run 40799458891).

The tabs are the doc tests' (``_ydoc_client.py``), each on a Flask-SocketIO
test client of its own, sending from a thread of its own. A burst here holds
its first update in a slow apply, which holds the doc's turn, until every
other message reached the server, and :data:`SETTLE_S` more.
"""

from __future__ import annotations

import json
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
#: How long a held apply goes on waiting once every message reached the server.
SETTLE_S = 0.5
#: How long a tab's messages may take while the doc's turn is held, when none
#: of them waits for it.
QUEUED_S = 5.0
#: The longest any wait here takes before the test fails: a hang is a finding.
WAIT_S = 20.0
#: The name of the doc's thread, while it drains what waits for the doc.
DOC_THREAD = "dataflow-doc-batches"
#: What a queued message is answered at once.
QUEUED = {"ok": True, "queued": True}


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
        try:
            _wait_for(lambda: len(self.applies) == 1, "the first update never reached its apply")
            for send in rest:
                threads.append(threading.Thread(target=send))
                threads[-1].start()
            _wait_for(lambda: len(self.arrived) == len(threads), "an update never reached the server")
            time.sleep(SETTLE_S)
        finally:
            self.going.set()
        for thread in threads:
            thread.join(WAIT_S)
            assert not thread.is_alive(), "a tab is still waiting for its update's answer"
        self.idle()

    def idle(self) -> None:
        """Wait until nothing waits for the doc and no thread holds its turn:
        every message the burst sent is applied and answered."""
        entry = self.entry
        with entry.queue:
            assert entry.queue.wait_for(lambda: not entry.applying and not entry.queued, WAIT_S), (
                "the doc's thread never drained its queue"
            )

    def hold(self, first):
        """Send *first* from a thread of its own and hold its apply, and with
        it the doc's turn, until :meth:`let_go`; the thread."""
        self.applies.clear()
        self.writes.clear()
        self.going.clear()
        thread = threading.Thread(target=first)
        thread.start()
        try:
            _wait_for(lambda: len(self.applies) == 1, "the first update never reached its apply")
        except BaseException:
            self.let_go(thread)
            raise
        return thread

    def let_go(self, thread) -> None:
        self.going.set()
        thread.join(WAIT_S)
        assert not thread.is_alive(), "the held update's tab is still waiting for its answer"
        self.idle()


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


def _answered(tab, count: int) -> list:
    """The kept messages the tab got, once they answer *count* of its updates."""
    messages: list = []

    def ready():
        messages.extend(tab.kept())
        return sum(message["answered"] for message in messages) >= count

    _wait_for(ready, f"the server's kept messages never answered {count} of the tab's updates")
    return messages


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


def _states(update: bytes) -> dict:
    """The awareness states an awareness update carries, by client id."""
    from pycrdt import Decoder

    decoder = Decoder(update)
    states = {}
    for _ in range(decoder.read_var_uint()):
        client = decoder.read_var_uint()
        decoder.read_var_uint()
        text = decoder.read_var_string()
        states[client] = json.loads(text) if text else None
    return states


def _room_of_tabs(room) -> tuple[dict, dict]:
    """Four editing tabs, two of alice's and two of bob's, and carol's, a
    watcher's; all synced, and nothing left for them to read."""
    tabs = {name: room.tab(account) for name, account in
            (("alice", "alice"), ("ana", "alice"), ("bob", "bob"), ("bea", "bob"))}
    everyone = {**tabs, "carol": room.tab("carol")}
    _take(everyone)
    for tab in everyone.values():
        tab.presences.clear()
    return tabs, everyone


def _no_doc_thread() -> bool:
    return not [thread for thread in threading.enumerate() if thread.name == DOC_THREAD and thread.is_alive()]


def test_a_burst_from_several_tabs_is_one_batch_one_write_and_one_message_to_each_tab(room, monkeypatch):
    from utk_curio.backend.app.collaboration import doc_mapping

    from ._ydoc_client import Origins

    tabs, everyone = _room_of_tabs(room)
    burst = _Burst(room, monkeypatch)
    doc_id = tabs["alice"].doc_id

    # An update alone is applied, logged and relayed at once, by the thread
    # that sent it, and answered in its ack with what the doc kept.
    [ack] = tabs["alice"].edit(_type("# alone\n"))
    assert ack == {"ok": True, "kept": _own_clock(tabs["alice"])}, ack
    assert burst.applies == [threading.current_thread()] and burst.writes == [1]
    assert {name: len(got) for name, got in _take(everyone).items()} == {
        "alice": 0, "ana": 1, "bob": 1, "bea": 1, "carol": 1,
    }, "an update alone did not reach each other tab at once"
    assert [tab.kept() for tab in tabs.values()] == [[]] * 4, "an update alone was answered twice"

    # A burst: alice's update holds the doc while ana's, bob's and bea's come.
    before = burst.entry.doc.get_update()
    origins = Origins(room.project_id)
    for tab in tabs.values():
        tab.sent.clear()
    answers: dict = {}
    burst.run(*(_sender(tab, _type(f"# {name}\n"), answers, name) for name, tab in tabs.items()))

    assert answers.get("alice") == [{"ok": True, "kept": _own_clock(tabs["alice"])}], answers.get("alice")
    for name in ("ana", "bob", "bea"):
        assert answers.get(name) == [QUEUED], (name, answers.get(name))
    burst.idle()
    for name in ("ana", "bob", "bea"):
        assert _answered(tabs[name], 1) == [
            {"projectId": room.project_id, "answered": 1, "kept": _own_clock(tabs[name])},
        ], name
    taken = _take(everyone)
    assert len(origins.seen) == 4 and len(set(origins.seen)) == 4, (
        f"each tab's update was not applied in a transaction of its own, its tab the origin: {origins.seen}"
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
    assert len(room.logged(doc_id)) == 5, "the log does not hold a record for each tab's change"

    # Every tab typing at once, a key at a time: each tab's keys stay in the
    # order it typed them, and each is answered once, in that order, with what
    # the doc kept: in its own ack, or by a kept message naming the clock of
    # the last key it answers.
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
    burst.idle()
    for name, typed in keys.items():
        assert len(typed) == len(f"<{name}>"), (name, typed)
        queued = [kept for ack, kept in typed if ack == QUEUED]
        for ack, kept in typed:
            assert ack in (QUEUED, {"ok": True, "kept": kept}), (name, ack, kept)
        at = 0
        for message in _answered(tabs[name], len(queued)):
            at += message["answered"]
            assert message == {"projectId": room.project_id, "answered": message["answered"],
                               "kept": queued[at - 1]}, (name, message, queued)
        assert at == len(queued), f"{name}'s queued keys were answered {at} times, not {len(queued)}"
    _take(everyone)
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

    assert answers.get("alice") == [{"ok": True, "kept": _own_clock(tabs["alice"])}], answers.get("alice")
    assert answers.get("bob") == QUEUED, answers.get("bob")
    for name in ("ana", "bea"):
        assert answers.get(name) == [QUEUED], (name, answers.get(name))
    burst.idle()
    assert _answered(tabs["bob"], 1) == [{
        "projectId": room.project_id, "answered": 1, "kept": {}, "refused": {"invalid_message": 1},
    }], "the update that does not apply was not refused, alone"
    for name in ("ana", "bea"):
        assert _answered(tabs[name], 1) == [
            {"projectId": room.project_id, "answered": 1, "kept": _own_clock(tabs[name])},
        ], name
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


def test_a_tabs_messages_behind_a_batch_are_answered_at_once_and_its_queued_keys_merge(room, monkeypatch):
    """While alice's update holds the doc's turn, ana types three keys and
    moves her pointer, and each is answered at once, ``queued``: her socket
    reads on, its pings with it. Then the doc's thread applies them as one
    batch: her three keys one transaction and one record in the log, one
    message to each other tab, and one kept message answering all three. The
    thread ends once nothing waits."""
    from utk_curio.backend.app.collaboration import doc_mapping

    from ._ydoc_client import Origins

    tabs, everyone = _room_of_tabs(room)
    burst = _Burst(room, monkeypatch)
    doc_id = tabs["alice"].doc_id
    before = burst.entry.doc.get_update()
    origins = Origins(room.project_id)
    answers: dict = {}
    keys: list = []
    pointer: list = []

    def ana_types():
        _typist(tabs["ana"], "abc", keys)()
        pointer.append(tabs["ana"].set_presence({"pointer": {"x": 1, "y": 2}}))

    held = burst.hold(_sender(tabs["alice"], _type("# alice\n"), answers, "alice"))
    try:
        ana = threading.Thread(target=ana_types)
        ana.start()
        ana.join(QUEUED_S)
        assert not ana.is_alive(), (
            "ana's messages waited for the update that held the doc: her socket read nothing more meanwhile"
        )
    finally:
        burst.let_go(held)

    assert [ack for ack, _kept in keys] == [QUEUED] * 3, keys
    assert pointer == [QUEUED], pointer
    assert answers.get("alice") == [{"ok": True, "kept": _own_clock(tabs["alice"])}], answers.get("alice")
    burst.idle()
    assert _answered(tabs["ana"], 3) == [{"projectId": room.project_id, "answered": 3, "kept": keys[-1][1]}], (
        "ana's three keys were not answered by one kept message"
    )
    _wait_for(_no_doc_thread, "the doc's thread did not end once nothing waited")
    assert len(origins.seen) == 2 and len(set(origins.seen)) == 2, (
        f"ana's three keys were not one transaction: {origins.seen}"
    )
    assert burst.writes == [1, 1] and len(room.logged(doc_id)) == 2, (
        f"ana's three keys were not one record in the log: {burst.writes}"
    )
    assert {name: len(got) for name, got in _take(everyone).items()} == {
        "alice": 1, "ana": 1, "bob": 2, "bea": 2, "carol": 2,
    }, "ana's three keys did not reach each other tab as one message"
    one_by_one = _after(before, [update for tab in tabs.values() for update in tab.sent])
    assert doc_mapping.doc_to_dataflow(burst.entry.doc) == one_by_one
    for name, tab in everyone.items():
        assert tab.dataflow() == one_by_one, f"{name}'s tab holds another doc than the server's"
    assert "abc" in _code(one_by_one) and "# alice\n" in _code(one_by_one), _code(one_by_one)
    assert tabs["bob"].others()[tabs["ana"].doc.client_id]["pointer"] == {"x": 1, "y": 2}


def test_awareness_waits_with_the_updates_and_each_tab_gets_each_clients_latest_state_once(room, monkeypatch):
    """While the doc's turn is held, ana and bob each move their pointer three
    times, each move answered at once. The batch keeps each client's latest
    state and sends each tab one message of them, its own clients' left out:
    a cursor's moves cost each tab a message a batch, not one a move."""
    tabs, everyone = _room_of_tabs(room)
    burst = _Burst(room, monkeypatch)
    answers: dict = {}
    moves: dict = {"ana": [], "bob": []}

    def moving(name):
        def run():
            for x in (1, 2, 3):
                moves[name].append(tabs[name].set_presence({"pointer": {"x": x, "y": 0}}))

        return run

    held = burst.hold(_sender(tabs["alice"], _type("# alice\n"), answers, "alice"))
    try:
        movers = [threading.Thread(target=moving(name)) for name in moves]
        for mover in movers:
            mover.start()
        for mover in movers:
            mover.join(QUEUED_S)
            assert not mover.is_alive(), "a pointer move waited for the update that held the doc"
    finally:
        burst.let_go(held)

    assert moves == {"ana": [QUEUED] * 3, "bob": [QUEUED] * 3}, moves
    burst.idle()
    clients = {name: tab.doc.client_id for name, tab in tabs.items()}
    for name, tab in everyone.items():
        tab.pump()
        assert len(tab.presences) == 1, (
            f"{name}'s tab got {len(tab.presences)} awareness messages for one batch of moves"
        )
        states = _states(tab.presences[0])
        movers = {clients[mover] for mover in moves if mover != name}
        assert set(states) == movers, f"{name}'s tab was sent the states of {set(states)}, not {movers}"
        for client in movers:
            assert states[client]["pointer"] == {"x": 3, "y": 0}, (name, states)
