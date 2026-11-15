"""Only the backend process that owns a dataflow keeps anything live for it
(``collaboration/owner_guard.py``).

A start of several backend processes gives each dataflow one owner: the
process its id names (``backend_processes.shard_of``), or for a hosted guest's
copy, the process the dataflow it copies names. Here this test's process is
set as one of two by the variables the launcher sets. As a process that does
not own a dataflow it keeps no doc of it, and starts no turn, Solve, run or
dashboard run for it: each is refused, naming the dataflow, its owner and this
process. It reads the dataflow as the owner's log holds it, replayed into a
doc it does not keep, and writes a create's files keeping no doc; each such
read and create is logged and counted. With one process nothing is refused.

Each test checks what the process did before it imports anything a checkout
without the guard lacks.
"""

from __future__ import annotations

import copy
import uuid

import pytest
from pycrdt import Map

from ._processes import (
    as_process,
    as_the_one_process,
    assert_names_the_owner,
    owned_by,
    owner_of,
)
from ._support import NAMESPACE, connect, join, make_project, make_user
from .test_dataflow_docs import SPEC, _code, _type, room  # noqa: F401 - room is a fixture


def _guard_lines(caplog, word: str) -> list[str]:
    """The ``[owner-guard]`` lines logged with *word* in them."""
    return [record.getMessage() for record in caplog.records
            if "[owner-guard]" in record.getMessage() and word in record.getMessage()]


# ---------------------------------------------------------------------------
# A live doc
# ---------------------------------------------------------------------------

def test_a_process_that_does_not_own_a_dataflow_keeps_no_live_doc_of_it(room, monkeypatch, caplog):
    """A writer's read of alice's dataflow, its history's open of its doc, a
    joined tab's sync and another tab's join are each refused in the process
    that does not own it, naming the dataflow, its owner and this process. No
    doc of it is open there."""
    from utk_curio.backend.app.collaboration import history

    docs = room.docs
    owner = owner_of(room.project_id)
    here = 1 - owner
    joined = room.tab("alice")
    as_process(monkeypatch, here)

    with pytest.raises(Exception) as refused:
        docs.live(room.owner_key, room.project_id)
    assert_names_the_owner(str(refused.value), room.project_id, owner, here)
    with pytest.raises(Exception) as opened:
        history.versions(room.owner_key, room.project_id)
    assert_names_the_owner(str(opened.value), room.project_id, owner, here)
    synced = joined.sync()
    assert synced["ok"] is False and synced["error"] == "not_the_owner", synced
    assert_names_the_owner(synced["message"], room.project_id, owner, here)
    bob = connect(room.socketio, room.application, room.tokens["bob"])
    joined_again = join(bob, room.project_id)
    assert joined_again["ok"] is False and joined_again["error"] == "not_the_owner", joined_again
    assert_names_the_owner(joined_again["message"], room.project_id, owner, here)
    assert docs._open_entry(room.project_id) is None, "a process that does not own the dataflow keeps its doc"

    from utk_curio.backend.app.collaboration.owner_guard import NotTheOwner

    assert isinstance(refused.value, NotTheOwner) and isinstance(opened.value, NotTheOwner)
    assert refused.value.code == 421, "a request that reaches the wrong process is answered 421 Misdirected"
    assert _guard_lines(caplog, "refused"), "the refusal logged no [owner-guard] line"


def test_its_owner_keeps_the_doc_as_one_process_does(room, monkeypatch):
    """The process that owns alice's dataflow opens its doc and syncs a tab,
    as the one process of every start does today."""
    as_process(monkeypatch, owner_of(room.project_id))
    alice = room.tab("alice")

    synced = alice.sync()
    assert synced["ok"] is True
    alice.edit(_type("# owned\n"))

    assert _code(room.docs.read(room.owner_key, room.project_id)["dataflow"]) == "# owned\nx = 1\n"
    assert room.docs._open_entry(room.project_id) is not None

    from utk_curio.backend.app.collaboration import owner_guard

    assert owner_guard.owner_of(room.project_id, room.owner_key) == owner_of(room.project_id)


# ---------------------------------------------------------------------------
# A read
# ---------------------------------------------------------------------------

def _append_cut_short(room) -> None:
    """Start a record at the end of the doc's log, as the owner's append
    that is still being written leaves it: a length, and fewer bytes."""
    docs = room.docs
    pointer = room.pointer()
    updates = room.folder() / docs.LOG_DIR / pointer["doc"] / f"{pointer['segment']}.updates"
    with open(updates, "ab") as log:
        log.write(bytes([0x40]) + b"\x01\x02\x03")


def test_a_process_that_does_not_own_a_dataflow_reads_it_as_the_owners_log_holds_it(room, monkeypatch, caplog):
    """alice typed in her dataflow, which its owner's doc logged and has not
    written yet. The process that does not own it reads her change, replayed
    from the saved file and the log, and keeps no doc; a record the owner is
    still appending ends the replay without a word of damage. The read is
    logged and counted."""
    docs = room.docs
    owner = owner_of(room.project_id)
    alice = room.tab("alice")
    alice.sync()
    alice.edit(_type("# only in the log\n"))
    # The owner's doc goes from this process unwritten: its change is in the log alone.
    docs.reset_for_tests()
    assert _code(room.on_disk()["dataflow"]) == "x = 1\n"
    as_process(monkeypatch, 1 - owner)

    read = docs.read(room.owner_key, room.project_id)

    assert docs._open_entry(room.project_id) is None, "the read kept a doc in a process that does not own the dataflow"
    assert _code(read["dataflow"]) == "# only in the log\nx = 1\n", "the read missed a change only the log holds"
    assert read["dataflow"]["agents"] == SPEC["dataflow"]["agents"], "the read lost what the file holds beside the doc"
    _append_cut_short(room)
    caplog.clear()
    again = docs.read(room.owner_key, room.project_id)
    assert _code(again["dataflow"]) == "# only in the log\nx = 1\n"
    assert docs._open_entry(room.project_id) is None
    assert "cut short" not in caplog.text, "a record the owner is still appending read as damage"
    lines = _guard_lines(caplog, "read")
    assert lines and room.project_id in lines[0] and f"process {owner}" in lines[0], caplog.text

    from utk_curio.backend.app.collaboration import owner_guard

    assert owner_guard.counts().get("read", 0) >= 2


def test_a_read_that_finds_the_file_written_since_the_log_takes_the_files_change_too(room, monkeypatch):
    """A change written to the file outside the doc after the owner's doc last
    wrote it is in the read too, beside what only the log holds, as the
    owner's doc carries such a write in when it opens."""
    from utk_curio.backend.app.projects import storage

    docs = room.docs
    owner = owner_of(room.project_id)
    alice = room.tab("alice")
    alice.sync()
    alice.edit(_type("# typed\n"))
    docs.flush(room.project_id)
    alice.edit(_type("# logged\n"))
    docs.reset_for_tests()
    on_file = storage.read_spec(room.owner_key, room.project_id)
    on_file["dataflow"]["name"] = "Renamed beside the doc"
    room.write_elsewhere(on_file)
    as_process(monkeypatch, 1 - owner)

    read = docs.read(room.owner_key, room.project_id)["dataflow"]

    assert _code(read) == "# logged\n# typed\nx = 1\n"
    assert read["name"] == "Renamed beside the doc"
    assert docs._open_entry(room.project_id) is None


# ---------------------------------------------------------------------------
# A create
# ---------------------------------------------------------------------------

def test_a_process_that_does_not_own_a_dataflow_writes_its_create_and_keeps_no_doc(doc_app, monkeypatch, caplog):
    """Signup seeds each account's examples in one process, for every
    process's dataflows: a create there writes the dataflow's files and keeps
    no doc, so its owner builds the doc when it first opens it. It is logged
    and counted."""
    from utk_curio.backend.app.collaboration import dataflow_docs as docs
    from utk_curio.backend.app.projects import storage

    user, _session = make_user("dana")
    key = str(user.id)
    project_id = make_project(user, owned_by(0))
    as_process(monkeypatch, 1)

    docs.create(key, project_id, copy.deepcopy(SPEC), docs.by_curio(key, "seed"))

    assert storage.read_spec(key, project_id)["dataflow"]["name"] == SPEC["dataflow"]["name"]
    assert docs._open_entry(project_id) is None
    assert not (storage.project_dir(key, project_id) / docs.POINTER_FILE).exists()
    lines = _guard_lines(caplog, "create")
    assert lines and project_id in lines[0] and "process 0" in lines[0], caplog.text

    from utk_curio.backend.app.collaboration import owner_guard

    assert owner_guard.counts().get("create", 0) >= 1


# ---------------------------------------------------------------------------
# A hosted guest's copy
# ---------------------------------------------------------------------------

#: The shared guest's example: a loader feeding a chart.
_EXAMPLE = {
    "dataflow": {
        "nodes": [
            {"id": "loader", "type": "curio.builtin/code", "x": 10, "y": 20,
             "content": "x = 1\n", "out": "DATAFRAME", "in": "DEFAULT", "goal": "",
             "metadata": {"keywords": []}},
        ],
        "edges": [],
        "name": "Example",
    },
}


def _hosted_guest(doc_app, monkeypatch):
    """The shared guest's account on a Curio started with ``--deploy``, and one
    visitor's sign-in to it."""
    from utk_curio.backend import config
    from utk_curio.backend.app.collaboration import dataflow_docs

    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    monkeypatch.setattr(dataflow_docs, "_today", lambda: "2026-11-09")
    return make_user(config.CURIO_SHARED_GUEST_USERNAME, is_guest=True)


def test_a_guests_copy_belongs_with_the_dataflow_it_copies(doc_app, monkeypatch):
    """A visitor's copy of an example has an id of its own, which here names
    the other process; the copy belongs with the example all the same, since
    the guest's page names the example. The example's owner opens the copy's
    room, made or not yet, and the other process refuses it."""
    from utk_curio.backend.app.collaboration import dataflow_docs as docs
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.projects import storage, visitor_copies

    from ._ydoc_client import DocClient

    application, socketio = doc_app
    guest, session = _hosted_guest(doc_app, monkeypatch)
    sign_in = session.token
    example = next(candidate for candidate in (str(uuid.uuid4()) for _ in range(500))
                   if owner_of(candidate) != owner_of(visitor_copies.copy_id(sign_in, candidate)))
    make_project(guest, example)
    storage.write_spec(GUEST_KEY, example, copy.deepcopy(_EXAMPLE))
    own = visitor_copies.copy_id(sign_in, example)
    owner, other = owner_of(example), owner_of(own)
    assert owner != other

    as_process(monkeypatch, owner)
    socket = connect(socketio, application, sign_in)
    joined = join(socket, example)
    assert joined["ok"] is True and joined["projectId"] == own, joined
    socket.get_received(namespace=NAMESPACE)
    tab = DocClient(socket, own)
    started = tab.sync()
    assert started["ok"] is True, f"the example's owner refused its guest's copy, not made yet: {started}"
    acks = tab.edit(lambda doc: doc.get("nodes", type=Map)["loader"]["content"].insert(0, "# mine\n"))
    assert acks and all(ack.get("ok") for ack in acks), acks
    assert visitor_copies.is_copy(own), "the guest's first change made no copy"

    as_process(monkeypatch, other)
    with pytest.raises(Exception) as refused:
        docs.live(GUEST_KEY, own)
    assert_names_the_owner(str(refused.value), own, owner, other)
    elsewhere = connect(socketio, application, sign_in)
    refused_join = join(elsewhere, example)
    assert refused_join["ok"] is False and refused_join["error"] == "not_the_owner", refused_join

    from utk_curio.backend.app.collaboration import owner_guard

    assert owner_guard.owner_of(own, GUEST_KEY) == owner


def test_a_guests_new_dataflow_belongs_where_its_own_id_names(doc_app, monkeypatch):
    """A visitor's File > New copies no dataflow: its page names its own id,
    so it belongs where that id names, never with the home process."""
    from utk_curio.backend.app.collaboration import dataflow_docs as docs
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.projects import visitor_copies

    guest, session = _hosted_guest(doc_app, monkeypatch)
    as_process(monkeypatch, 0)
    own = None
    for _ in range(64):
        made = visitor_copies.new_dataflow(guest, copy.deepcopy(_EXAMPLE), sign_in=session.token)
        if made is not None and owner_of(made) == 1:
            own = made
            break
    assert own is not None, "no new dataflow of this visitor belongs to process 1"

    with pytest.raises(Exception) as refused:
        docs.live(GUEST_KEY, own)
    assert_names_the_owner(str(refused.value), own, 1, 0)
    as_process(monkeypatch, 1)
    assert docs.live(GUEST_KEY, own) is not None


# ---------------------------------------------------------------------------
# Turns, Solves, runs and a dashboard's runs
# ---------------------------------------------------------------------------

def test_a_process_that_does_not_own_a_dataflow_starts_nothing_for_it(room, monkeypatch):
    """An agent's turn, a Solve's job, a run on the server and a dashboard's
    run of alice's dataflow are each refused in the process that does not own
    it, naming its owner, before anything of them is kept."""
    from utk_curio.backend.app.agents.application.turns import turn_jobs
    from utk_curio.backend.app.agents.infrastructure import agent_jobs
    from utk_curio.backend.app.runs import service as runs_service
    from utk_curio.backend.app.runs import viewer
    from utk_curio.backend.app.runs.models import DataflowRun

    owner = owner_of(room.project_id)
    here = 1 - owner
    alice = room.users["alice"]
    as_process(monkeypatch, here)
    agent_jobs.reset_registry()
    try:
        ask_id = uuid.uuid4().hex
        with room.application.test_request_context():
            with pytest.raises(Exception) as turn:
                turn_jobs.ask(room.owner_key, room.project_id, "t1", "Put a line on top", None, ask_id=ask_id)
        assert_names_the_owner(str(turn.value), room.project_id, owner, here)
        assert ask_id not in turn_jobs._asks, "a refused turn was kept"

        for start in (
            lambda: agent_jobs.register_job(user_key=room.owner_key, project_id=room.project_id,
                                            attachment_id="t1", kind="solve-batch", job_id=uuid.uuid4().hex),
            lambda: agent_jobs.start_job(user_key=room.owner_key, project_id=room.project_id,
                                         attachment_id="t1", kind="solve-node", job_id=uuid.uuid4().hex,
                                         events=iter(())),
            lambda: agent_jobs.start_turn(user_key=room.owner_key, project_id=room.project_id,
                                          attachment_id="t1", job_id=uuid.uuid4().hex, events=iter(())),
        ):
            with pytest.raises(Exception) as solve:
                start()
            assert_names_the_owner(str(solve.value), room.project_id, owner, here)
        assert agent_jobs.live_job(room.owner_key, "t1") is None and not agent_jobs.live_turns()

        with room.application.test_request_context():
            with pytest.raises(Exception) as run:
                # A node the dataflow lacks: a run that got past the guard plans
                # nothing and starts no thread.
                runs_service.start_run(alice, room.tokens["alice"], room.project_id, target_node_id="missing")
        assert_names_the_owner(str(run.value), room.project_id, owner, here)
        assert DataflowRun.query.filter_by(project_id=room.project_id).count() == 0, "a refused run was kept"

        with room.application.test_request_context():
            with pytest.raises(Exception) as dashboard:
                viewer.start_viewer_run(room.project_id, {}, address="127.0.0.1")
        assert_names_the_owner(str(dashboard.value), room.project_id, owner, here)
    finally:
        agent_jobs.reset_registry()


# ---------------------------------------------------------------------------
# One process
# ---------------------------------------------------------------------------

def test_with_one_process_nothing_is_refused_and_nothing_is_looked_up(room, monkeypatch):
    """A start of one backend, every install's today: each dataflow is its
    own, nothing is refused or counted, and no dataflow's owner is even
    looked up."""
    from utk_curio.backend.app.agents.infrastructure import agent_jobs
    from utk_curio.backend.app.collaboration import owner_guard

    def looked_up(*_args, **_kwargs):
        raise AssertionError("a start of one backend looked up which process owns a dataflow")

    docs = room.docs
    as_the_one_process(monkeypatch)
    owner_guard.reset_for_tests()
    monkeypatch.setattr(owner_guard, "room_key", looked_up)
    agent_jobs.reset_registry()
    try:
        alice = room.tab("alice")
        synced = alice.sync()
        assert synced["ok"] is True
        spec = docs.live(room.owner_key, room.project_id)
        spec["dataflow"]["name"] = "Renamed"
        written = docs.write(room.owner_key, room.project_id, spec, docs.person(room.owner_key, "save"))
        assert written.wrote
        assert docs.read(room.owner_key, room.project_id)["dataflow"]["name"] == "Renamed"
        made = make_project(room.users["alice"])
        docs.create(room.owner_key, made, copy.deepcopy(SPEC), docs.by_curio(room.owner_key, "seed"))
        job = agent_jobs.register_job(user_key=room.owner_key, project_id=room.project_id,
                                      attachment_id="t1", kind="solve-batch", job_id=uuid.uuid4().hex)
        assert job is not None
    finally:
        agent_jobs.reset_registry()
    assert owner_guard.counts() == {}, owner_guard.counts()
