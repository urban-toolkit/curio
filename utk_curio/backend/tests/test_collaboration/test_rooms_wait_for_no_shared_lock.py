"""A room's tabs and records wait for no lock that every room shares.

In the stress stage of 100 people with agents on one backend (profiling run
42550568338), every room stopped for over half a minute and no person's work
completed: 100 sockets waited at ``dataflow_docs._open_entry`` for the
module's lock, which each tab's update took to find its doc. Nothing held it
long, but a thread given a lock waits for the GIL before it can let it go, so
with hundreds of threads each holder kept it a while, and the queue drained
only once the tabs gave up ("no answer to node_unlock in 60s"). Just before,
every room's changes had queued on ``owner_uses``' one lock for all the
dataflows' records, which each change held across a read and a write of its
file.

So a tab's update finds its doc and notes its change without the module's
lock (``_open_entry``, ``_changed``, which wakes the writing thread with an
event), and each dataflow's record has a lock of its own. The writing thread
still writes a change, and two changes to one record still wait for each
other.
"""
from __future__ import annotations

import threading
import time
from collections import Counter

from ._support import make_project, make_user

#: How long a test waits for a thread before it calls it stuck.
WAIT_S = 10.0

#: A dataflow of one node.
SPEC = {
    "dataflow": {
        "nodes": [{"id": "loader", "type": "curio.builtin/code", "x": 10, "y": 20,
                   "content": "x = 1\n", "out": "DATAFRAME", "in": "DEFAULT", "goal": "",
                   "metadata": {"keywords": []}}],
        "edges": [],
        "name": "Shared", "task": "", "timestamp": 1, "provenance_id": "Shared",
    },
}

#: Two dataflows of one store, for the records' tests.
DATAFLOW = "5e3c0a6e-2b1d-4f7a-9c8e-0d1f2a3b4c5d"
OTHER = "0d1f2a3b-4c5d-4f7a-9c8e-5e3c0a6e2b1d"


def _type(text: str):
    """A person typing *text* at the top of the loader's code."""

    def change(doc) -> None:
        from pycrdt import Map

        doc.get("nodes", type=Map)["loader"]["content"].insert(0, text)

    return change


def _while_held(lock, work):
    """What *work* returns, run on a thread of its own while another thread
    holds *lock*; fails when *work* is still waiting after :data:`WAIT_S`."""
    held, done = threading.Event(), threading.Event()
    outcome: dict = {}

    def hold() -> None:
        with lock:
            held.set()
            done.wait(WAIT_S * 3)

    def run() -> None:
        try:
            outcome["value"] = work()
        except Exception as exc:  # noqa: BLE001 - raised again on the test's thread
            outcome["error"] = exc

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(WAIT_S), "the lock was never taken"
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(WAIT_S)
    waited = worker.is_alive()
    done.set()
    holder.join(WAIT_S)
    worker.join(WAIT_S)
    assert not waited, f"it waited {WAIT_S:.0f}s for a lock another thread held"
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def _loader_code(user_key: str, project_id: str) -> str:
    """The loader's code as the open doc holds it."""
    from utk_curio.backend.app.collaboration import dataflow_docs, doc_mapping

    entry = dataflow_docs._open_entry(project_id, user_key)
    assert entry is not None, "the server holds no doc of the dataflow"
    nodes = doc_mapping.doc_to_dataflow(entry.doc)["nodes"]
    return next(node for node in nodes if node["id"] == "loader")["content"]


def test_a_tabs_update_is_answered_while_another_thread_holds_the_docs_lock(doc_app):
    """A thread holding ``dataflow_docs._lock``, as one given it and waiting
    for the GIL does, keeps no tab's update waiting: the tab finds its doc and
    its change is noted without that lock."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects import storage

    from ._ydoc_client import synced_tab

    application, _socketio = doc_app
    alice, session = make_user("alice")
    project_id = make_project(alice)
    storage.write_spec(str(alice.id), project_id, SPEC)
    tab = synced_tab(application, session.token, project_id)

    acks = _while_held(dataflow_docs._lock, lambda: tab.edit(_type("# typed\n")))

    assert acks and all(ack.get("ok") for ack in acks), acks
    assert _loader_code(str(alice.id), project_id).startswith("# typed\n")


def test_the_writing_thread_writes_a_tabs_change(doc_app, monkeypatch):
    """The writing thread, which a change wakes with an event, writes the
    change to the spec a second after it."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects import storage

    from ._ydoc_client import synced_tab

    application, _socketio = doc_app
    alice, session = make_user("alice")
    project_id = make_project(alice)
    storage.write_spec(str(alice.id), project_id, SPEC)
    tab = synced_tab(application, session.token, project_id)
    monkeypatch.setattr(dataflow_docs, "BACKGROUND", True)
    try:
        assert all(ack.get("ok") for ack in tab.edit(_type("# kept\n")))
        deadline = time.monotonic() + WAIT_S
        code = None
        while time.monotonic() < deadline:
            spec = storage.read_spec_file(str(alice.id), project_id).spec
            code = next(node for node in spec["dataflow"]["nodes"] if node["id"] == "loader")["content"]
            if code.startswith("# kept\n"):
                break
            time.sleep(0.1)
        assert code is not None and code.startswith("# kept\n"), f"the spec still holds {code!r}"
    finally:
        # With no doc open the thread ends at its next turn, which it is woken
        # for now, so it writes no later test's docs.
        dataflow_docs.reset_for_tests()
        dataflow_docs._ensure_flusher()
        flusher = dataflow_docs._flusher
        if flusher is not None:
            flusher.join(WAIT_S)


def _first_read_held(monkeypatch, project_id: str) -> tuple[threading.Event, threading.Event]:
    """Hold the first read of *project_id*'s record: the event its read sets
    once under way, and the one that lets it go on."""
    from utk_curio.backend.app.collaboration import owner_uses

    entered, release = threading.Event(), threading.Event()
    original = owner_uses._read

    def read(path):
        if path.parent.name == project_id and not entered.is_set():
            entered.set()
            release.wait(WAIT_S * 3)
        return original(path)

    monkeypatch.setattr(owner_uses, "_read", read)
    return entered, release


def _owners_change(project_id: str, dataset: str) -> threading.Thread:
    """The owner's change naming *dataset* in the dataflow, on a thread."""
    from utk_curio.backend.app.collaboration import owner_uses

    after = Counter({(owner_uses.DATASETS, dataset, f"ref:{dataset}"): 1})
    return threading.Thread(target=owner_uses.changed, args=("7", project_id, Counter(), after),
                            kwargs={"by_owner": True}, daemon=True)


def test_one_dataflows_record_waits_for_no_other_dataflows(tmp_path, monkeypatch):
    """A change to one dataflow's record, held up inside its read, keeps no
    change to another dataflow's record waiting."""
    from utk_curio.backend.app.collaboration import owner_uses
    from utk_curio.backend.app.projects import storage

    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
    for project_id in (DATAFLOW, OTHER):
        storage.ensure_project_dir("7", project_id)
    entered, release = _first_read_held(monkeypatch, DATAFLOW)
    first, other = _owners_change(DATAFLOW, "roads"), _owners_change(OTHER, "parks")

    first.start()
    try:
        assert entered.wait(WAIT_S), "the first change never read its record"
        other.start()
        other.join(WAIT_S)
        waited = other.is_alive()
    finally:
        release.set()
    first.join(WAIT_S)
    other.join(WAIT_S)

    assert not waited, f"a change to one dataflow's record waited {WAIT_S:.0f}s for another dataflow's"
    assert owner_uses.recorded("7", OTHER).dataset("parks")
    assert owner_uses.recorded("7", DATAFLOW).dataset("roads")


def test_two_changes_to_one_record_still_wait_for_each_other(tmp_path, monkeypatch):
    """A record's read and write stay whole: a second change to it waits for
    the first, and the record keeps both."""
    from utk_curio.backend.app.collaboration import owner_uses
    from utk_curio.backend.app.projects import storage

    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
    storage.ensure_project_dir("7", DATAFLOW)
    entered, release = _first_read_held(monkeypatch, DATAFLOW)
    first, second = _owners_change(DATAFLOW, "roads"), _owners_change(DATAFLOW, "parks")

    first.start()
    try:
        assert entered.wait(WAIT_S), "the first change never read its record"
        second.start()
        second.join(0.5)
        overtook = not second.is_alive()
    finally:
        release.set()
    first.join(WAIT_S)
    second.join(WAIT_S)

    assert not overtook, "a second change to the record did not wait for the first"
    record = owner_uses.recorded("7", DATAFLOW)
    assert record.dataset("roads") and record.dataset("parks"), record
