"""A read of a dataflow never waits for its history to reach the disk.

Each change of an open dataflow is a point of its history, a line added to
``history/points.jsonl`` and synced to disk (``history._append_points``): File >
Save, a run, an agent's change, a tab's change to the graph. The sync ran while
its thread held the dataflow's history lock and its doc's lock, and a writer's
change held its spec lock too. The read of the dataflow (``GET
/api/projects/<id>``, ``services.load_project``) takes all three, so on a
strained disk, where one sync takes seconds, every read waited for it: the
canvas opening, the dashboard, a shared link. The Crown Heights sharing e2e
once waited past its 10 s for this read on such a runner (test-gpu job
128298155233, utk-desktop-01, where other stacks' artifact reads took 11 to
12 s at the time); its logs do not say what the read waited on, and this is a
wait it can have.

Here each sync is held: the thread that makes the point waits in ``os.fsync``
until the test lets it go, and the read must answer meanwhile, with the
dataflow as its doc holds it. The point still reaches the disk before its
maker answers. The database is a file, as on a server, so each thread has its
own connection.
"""

from __future__ import annotations

import os
import threading

import pytest

from .test_dataflow_docs import room  # noqa: F401 - room is a fixture
from .test_history import BUILDER, _add_node, _auth, _synced, kept  # noqa: F401 - kept is a fixture

#: How long the read may take while a sync is held: ample for a read here.
READ_SECONDS = 5
#: How long each step may take to begin.
STEP_SECONDS = 10
#: How long a held sync waits before it goes on regardless.
HOLD_SECONDS = 60


@pytest.fixture()
def doc_app(monkeypatch, tmp_path):
    """The app the collaboration tests talk to (``conftest.doc_app``), its
    database a file: a server opens a connection a thread, and the in-memory
    one hands every thread the same connection, which two may not use at
    once."""
    from utk_curio.backend import extensions as _ext
    from utk_curio.backend.app import create_app
    from utk_curio.backend.app.collaboration import dataflow_docs, room_state

    class _FileDbConfig:
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'file.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SECRET_KEY = "test-secret"
        WTF_CSRF_ENABLED = False

    monkeypatch.setattr(_ext, "socketio", None, raising=True)
    monkeypatch.setattr(dataflow_docs, "BACKGROUND", False, raising=True)
    application = create_app(_FileDbConfig)
    # After the app is made, so its start seeds the packages where it always does.
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path))
    with application.app_context():
        _ext.db.create_all()
        room_state.reset_for_tests()
        dataflow_docs.reset_for_tests()
        try:
            yield application, application.extensions.get("socketio")
        finally:
            dataflow_docs.reset_for_tests()
            room_state.reset_for_tests()
            _ext.db.session.remove()
            _ext.db.drop_all()
            _ext.db.engine.dispose()


def _held_syncs(monkeypatch, name: str):
    """Hold each disk sync the thread called *name* makes until the test lets
    it go; the (reached, release) events."""
    reached, release = threading.Event(), threading.Event()
    real = os.fsync

    def fsync(descriptor):
        if threading.current_thread().name == name:
            reached.set()
            release.wait(HOLD_SECONDS)
        return real(descriptor)

    monkeypatch.setattr(os, "fsync", fsync)
    return reached, release


def _start(threads: list, name: str, work) -> dict:
    """Run *work* on a thread called *name*, added to *threads*: the dict
    returned gets its value or its error, and its ``done`` is set once it
    ends."""
    outcome: dict = {"done": threading.Event()}

    def target():
        try:
            outcome["value"] = work()
        except BaseException as exc:  # noqa: BLE001 - asserted by the test
            outcome["error"] = exc
        finally:
            outcome["done"].set()

    thread = threading.Thread(target=target, name=name, daemon=True)
    threads.append(thread)
    thread.start()
    return outcome


def _outcome(outcome: dict) -> str:
    if "error" in outcome:
        return f"it raised {outcome['error']!r}"
    if "value" in outcome:
        return f"it returned {outcome['value']!r}"
    return "it had not ended"


def _opened(room) -> dict:
    """The owner opening the dataflow: ``GET /api/projects/<id>``."""
    answer = room.application.test_client().get(f"/api/projects/{room.project_id}", headers=_auth(room))
    assert answer.status_code == 200, answer.get_data(as_text=True)
    return answer.get_json()


def _read_while_a_point_syncs(room, monkeypatch, name: str, make_point) -> dict:
    """Make a point of the dataflow's history on a thread called *name*, its
    disk sync held, and open the dataflow meanwhile. The outcomes: the
    point's maker's and the read's, whether the read answered while the sync
    was held, and whether the maker was still waiting for it then."""
    # The first open seeds the account's packages, which the read here need not do.
    _opened(room)
    reached, release = _held_syncs(monkeypatch, name)
    threads: list = []
    try:
        maker = _start(threads, name, make_point)
        if not reached.wait(STEP_SECONDS):
            maker["done"].wait(STEP_SECONDS)
            pytest.fail(f"the {name} never synced its point to the disk; {_outcome(maker)}")
        reader = _start(threads, "reader", lambda: _opened(room))
        answered = reader["done"].wait(READ_SECONDS)
        maker_waited = not maker["done"].is_set()
    finally:
        release.set()
        for thread in threads:
            thread.join(STEP_SECONDS + HOLD_SECONDS)
    return {"maker": maker, "reader": reader, "answered": answered, "maker_waited": maker_waited}


def _answered_meanwhile(run: dict, what: str) -> dict:
    """The read's answer, which came while *what* was going to the disk."""
    assert run["answered"], (
        f"the dataflow did not open within {READ_SECONDS} s while {what} was going to the disk: "
        "the read waited for the disk"
    )
    reader = run["reader"]
    assert "error" not in reader, _outcome(reader)
    return reader["value"]


def _nodes(opened: dict) -> dict:
    return {node["id"]: node for node in opened["spec"]["dataflow"]["nodes"]}


def _newest_point(room) -> dict:
    from utk_curio.backend.app.collaboration import history

    return history.points(room.owner_key, room.project_id)[-1]


def test_opening_a_dataflow_does_not_wait_for_file_save_to_reach_the_disk(kept, monkeypatch):
    """File > Save's version (``POST .../history/saved``) is a point of the
    history: while it goes to the disk, the dataflow opens as its doc holds
    it, and the save answers once the point is there."""
    _synced(kept, "alice")

    run = _read_while_a_point_syncs(kept, monkeypatch, "save", lambda: kept.application.test_client().post(
        f"/api/projects/{kept.project_id}/history/saved", headers=_auth(kept),
    ))

    opened = _answered_meanwhile(run, "File > Save's version")
    assert list(_nodes(opened)) == ["loader", "shaper", "chart"]
    assert run["maker_waited"], "File > Save answered before its version was on the disk"
    save = run["maker"]
    assert "error" not in save, _outcome(save)
    assert save["value"].status_code == 201, save["value"].get_data(as_text=True)
    newest = _newest_point(kept)
    assert (newest["kind"], newest["what"]) == ("saved", "Saved"), newest


def test_opening_a_dataflow_does_not_wait_for_an_agents_change_to_reach_the_disk(kept, monkeypatch):
    """An agent's change (``dataflow_docs.write``) is a point of the history,
    made under the dataflow's spec lock: while it goes to the disk, the
    dataflow opens with the change, and the write returns once it is there."""
    from utk_curio.backend.app.collaboration import dataflow_docs

    _synced(kept, "alice")
    spec = dataflow_docs.live(kept.owner_key, kept.project_id)
    next(node for node in spec["dataflow"]["nodes"] if node["id"] == "loader")["content"] = "x = 42\n"

    def change():
        with kept.application.app_context():
            return dataflow_docs.write(kept.owner_key, kept.project_id, spec,
                                       dataflow_docs.by_agent(BUILDER, kept.owner_key, "apply"))

    run = _read_while_a_point_syncs(kept, monkeypatch, "agent", change)

    opened = _answered_meanwhile(run, "the agent's change")
    assert _nodes(opened)["loader"]["content"] == "x = 42\n", "the dataflow opened without the agent's change"
    assert run["maker_waited"], "the agent's write returned before its change was on the disk"
    write = run["maker"]
    assert "error" not in write, _outcome(write)
    assert write["value"].wrote
    assert _newest_point(kept)["kind"] == "agent"


def test_opening_a_dataflow_does_not_wait_for_a_tabs_change_to_reach_the_disk(kept, monkeypatch):
    """A node a tab adds is a point of the history, made under the doc's
    lock: while it goes to the disk, the dataflow opens with the node, and
    the tab's update is answered once it is there."""
    alice = _synced(kept, "alice")

    run = _read_while_a_point_syncs(kept, monkeypatch, "tab", lambda: alice.edit(_add_node("added")))

    opened = _answered_meanwhile(run, "the tab's new node")
    assert "added" in _nodes(opened), "the dataflow opened without the node the tab added"
    assert run["maker_waited"], "the tab's update was answered before its node was on the disk"
    edit = run["maker"]
    assert "error" not in edit, _outcome(edit)
    assert [ack.get("ok") for ack in edit["value"]] == [True], edit["value"]
    assert _newest_point(kept)["kind"] == "graph"
