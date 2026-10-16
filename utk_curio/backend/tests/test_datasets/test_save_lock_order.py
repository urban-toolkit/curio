"""A save takes the project's spec lock before it writes to the database (#909).

Each request thread has its own SQLite connection, and a connection that has
written holds SQLite's one write lock until it commits. A save used to update
the project row first and only then wait for the spec lock. A run on the
server, or another save, holding that lock needs the write lock for the
dataset index row of each output it installs, so each waited for the other
until the busy timeout ran out. The index write then failed ("Could not index
dataset dir"), was swallowed, and the save answered 200 about 31 s later with
a stale index row.

The interleavings are forced with events, and every connection's busy timeout
is squeezed to 2 s (the app's is 30 s), so the old order fails in 2 s instead
of 30. The database is a file, as on a server (``file_db_app``).
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import event, select

from utk_curio.backend.app.datasets.repositories import index as index_repo
from utk_curio.backend.app.projects import storage
from utk_curio.backend.extensions import db
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers

TOKEN = "lock-order-token"
NODE_TYPE = "curio.builtin/computation-analysis"
BUSY_TIMEOUT_MS = 2000
# Ample for any step here, and well under what a held thread waits for.
STEP_SECONDS = 10
HOLD_SECONDS = 30
INDEX_LOGGER = "utk_curio.backend.app.datasets.repositories.index"


@pytest.fixture()
def user_id(file_db_app):
    """Alice and her session token, in the file database."""
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username="alice", name="Alice", email="alice@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=TOKEN))
    db.session.commit()
    return user.id


@pytest.fixture()
def squeezed_busy_timeout(file_db_app):
    """Every connection the app checks out waits 2 s for the write lock."""
    engine = db.engine

    def squeeze(dbapi_connection, _record, _proxy):
        dbapi_connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")

    event.listen(engine, "checkout", squeeze)
    yield
    event.remove(engine, "checkout", squeeze)


def _spec() -> dict:
    """Nodes a and b, each with its Save toggle on."""
    return {"dataflow": {"name": "Lock order", "nodes": [
        {"id": "a", "type": NODE_TYPE, "content": "return 1", "saveOutputDataset": True},
        {"id": "b", "type": NODE_TYPE, "content": "return 2", "saveOutputDataset": True},
    ], "edges": []}}


def _create_project(application) -> str:
    response = application.test_client().post(
        "/api/projects",
        data=json.dumps({"name": "Lock order", "spec": _spec(), "outputs": []}),
        headers=auth_headers(TOKEN),
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["id"]


def _artifact(ms: int, payload) -> str:
    """A JSON artifact as the sandbox names it: ``<ms>_<8 hex>.json``."""
    name = f"{ms}_{uuid.uuid4().hex[:8]}.json"
    (Path(os.environ["CURIO_SHARED_DATA"]) / name).write_text(json.dumps(payload), encoding="utf-8")
    return name


def _save(application, project_id, outputs):
    """The canvas's save: its spec and the outputs it holds."""
    return application.test_client().put(
        f"/api/projects/{project_id}",
        data=json.dumps({
            "spec": _spec(),
            "outputs": [
                {"node_id": node_id, "filename": filename, "data_type": "dict"}
                for node_id, filename in outputs
            ],
        }),
        headers=auth_headers(TOKEN),
    )


def _record(application, user_id, project_id, outputs):
    """What a run on the server does when a node finishes (runs/service.py)."""
    from utk_curio.backend.app.projects.schemas import OutputRef
    from utk_curio.backend.app.projects.services import record_node_outputs
    from utk_curio.backend.app.users.models import User

    with application.app_context():
        return record_node_outputs(db.session.get(User, user_id), project_id, [
            OutputRef(node_id=node_id, filename=filename, data_type="dict")
            for node_id, filename in outputs
        ])


def _start(threads: list, name: str, work) -> dict:
    """Run *work* on a thread called *name*, added to *threads*; the dict
    returned gets its outcome."""
    outcome: dict = {}

    def target():
        try:
            outcome["value"] = work()
        except BaseException as exc:  # noqa: BLE001 - asserted by the test
            outcome["error"] = exc
        finally:
            outcome["done_at"] = time.monotonic()

    thread = threading.Thread(target=target, name=name, daemon=True)
    threads.append(thread)
    thread.start()
    return outcome


def _hold_at_index_write(monkeypatch, thread_name: str, *, when: str):
    """Hold *thread_name* at its first dataset index write: just ``"before"``
    it, or just ``"after"`` it, which is between two installs. Returns the
    (reached, release) events."""
    reached, release = threading.Event(), threading.Event()
    real = index_repo.safe_upsert_from_dir

    def hold(moment: str) -> None:
        if (moment == when and threading.current_thread().name == thread_name
                and not reached.is_set()):
            reached.set()
            release.wait(timeout=HOLD_SECONDS)

    def held(user_key, dataset_root):
        hold("before")
        real(user_key, dataset_root)
        hold("after")

    monkeypatch.setattr(index_repo, "safe_upsert_from_dir", held)
    return reached, release


def _signal_at_spec_lock(monkeypatch, thread_name: str) -> threading.Event:
    """An event set when *thread_name* asks for a spec lock."""
    asked = threading.Event()
    real = storage.spec_write_lock

    @contextlib.contextmanager
    def observed(user_key, project_id):
        if threading.current_thread().name == thread_name:
            asked.set()
        with real(user_key, project_id):
            yield

    monkeypatch.setattr(storage, "spec_write_lock", observed)
    return asked


def _release_and_join(threads: list, release: threading.Event) -> float:
    """Release the held thread and wait for *threads*; returns when it was released."""
    released_at = time.monotonic()
    release.set()
    for thread in threads:
        thread.join(timeout=HOLD_SECONDS)
    hung = [thread.name for thread in threads if thread.is_alive()]
    assert not hung, f"still running {HOLD_SECONDS} s after the release: {hung}"
    return released_at


def _index_warnings(caplog) -> list:
    return [
        f"{record.getMessage()}: {record.exc_info[1] if record.exc_info else ''}"
        for record in caplog.records
        if record.name == INDEX_LOGGER and record.getMessage().startswith("Could not index")
    ]


def _stale_index_rows(user_key: str, *, outputs: int) -> list:
    """Each computed store dir whose index row does not match its manifest on
    disk, as (dir, row's manifest mtime or None, manifest's mtime). The store
    must hold *outputs* dirs, so the check cannot pass on nothing."""
    from utk_curio.backend.app.datasets.infrastructure.storage import list_user_datasets

    db.session.expire_all()
    dirs = [d for d in list_user_datasets(user_key) if d.name.startswith("computed.")]
    assert len(dirs) == outputs, [d.name for d in dirs]
    stale = []
    for dataset_root in dirs:
        on_disk = (dataset_root / "manifest.json").stat().st_mtime_ns
        row = index_repo.get_by_dir(user_key, dataset_root.name)
        row_mtime = row.manifest_mtime_ns if row is not None else None
        if row_mtime != on_disk:
            stale.append((dataset_root.name, row_mtime, on_disk))
    return stale


def _assert_finished_in_time(outcomes: dict, released_at: float) -> None:
    for name, outcome in outcomes.items():
        assert "error" not in outcome, f"{name}: {outcome.get('error')!r}"
        took = outcome["done_at"] - released_at
        assert took < STEP_SECONDS, f"the {name} took {took:.1f} s after the release"


def test_a_save_during_a_run_leaves_the_runs_index_write_free(
    file_db_app, user_id, squeezed_busy_timeout, monkeypatch, caplog,
):
    """A run on the server is installing an output, holding the spec lock, and a
    save arrives. The save must wait for the lock without holding the write lock
    the run's index write needs."""
    caplog.set_level(logging.WARNING, logger=INDEX_LOGGER)
    project_id = _create_project(file_db_app)
    run_output = _artifact(1790000000000, {"v": "run"})
    save_output = _artifact(1790000000100, {"v": "save"})
    reached, release = _hold_at_index_write(monkeypatch, "run", when="before")
    save_asked = _signal_at_spec_lock(monkeypatch, "save")

    threads: list = []
    try:
        run = _start(threads, "run", lambda: _record(
            file_db_app, user_id, project_id, [("a", run_output)],
        ))
        assert reached.wait(STEP_SECONDS), "the run never reached its index write"
        save = _start(threads, "save", lambda: _save(
            file_db_app, project_id, [("b", save_output)],
        ))
        assert save_asked.wait(STEP_SECONDS), "the save never asked for the spec lock"
    finally:
        released_at = _release_and_join(threads, release)

    _assert_finished_in_time({"run": run, "save": save}, released_at)
    assert save["value"].status_code == 200, save["value"].get_data(as_text=True)
    assert not _index_warnings(caplog), _index_warnings(caplog)
    assert _stale_index_rows(str(user_id), outputs=2) == []


def test_a_save_during_another_save_leaves_its_index_writes_free(
    file_db_app, user_id, squeezed_busy_timeout, monkeypatch, caplog,
):
    """Two saves of one dataflow (two tabs, or autosave and Save): the second
    must wait for the first without holding the write lock the first needs to
    index its next output."""
    caplog.set_level(logging.WARNING, logger=INDEX_LOGGER)
    project_id = _create_project(file_db_app)
    a = _artifact(1790000000000, {"v": "a"})
    b = _artifact(1790000000100, {"v": "b"})
    reached, release = _hold_at_index_write(monkeypatch, "first save", when="after")
    second_asked = _signal_at_spec_lock(monkeypatch, "second save")

    threads: list = []
    try:
        first = _start(threads, "first save", lambda: _save(
            file_db_app, project_id, [("a", a), ("b", b)],
        ))
        assert reached.wait(STEP_SECONDS), "the first save never installed its first output"
        # The second tab holds only a's output; b's stays recorded.
        second = _start(threads, "second save", lambda: _save(
            file_db_app, project_id, [("a", a)],
        ))
        assert second_asked.wait(STEP_SECONDS), "the second save never asked for the spec lock"
    finally:
        released_at = _release_and_join(threads, release)

    _assert_finished_in_time({"first save": first, "second save": second}, released_at)
    for outcome in (first, second):
        assert outcome["value"].status_code == 200, outcome["value"].get_data(as_text=True)
    assert not _index_warnings(caplog), _index_warnings(caplog)
    assert _stale_index_rows(str(user_id), outputs=2) == []


def _takes_the_lock(application, user_key: str, project_id: str) -> bool:
    """Whether another thread gets the spec lock within a few seconds."""
    got = threading.Event()

    def take():
        with application.app_context():
            with storage.spec_write_lock(user_key, project_id):
                got.set()

    thread = threading.Thread(target=take, daemon=True)
    thread.start()
    thread.join(timeout=STEP_SECONDS)
    return got.is_set()


def test_the_spec_lock_refuses_a_thread_holding_a_database_write(file_db_app, user_id):
    """The lock order, kept by the lock itself: a thread that has written and
    not committed may not wait for a spec lock."""
    from utk_curio.backend.app.users.models import User

    user = db.session.get(User, user_id)
    user.name = "Alice, renamed"
    db.session.flush()

    try:
        with pytest.raises(RuntimeError, match="uncommitted database write"):
            with storage.spec_write_lock(str(user_id), "refused"):
                pass
    finally:
        db.session.rollback()

    # Refused before taking anything: another thread gets the lock, and after
    # the rollback so does this one.
    assert _takes_the_lock(file_db_app, str(user_id), "refused")
    with storage.spec_write_lock(str(user_id), "refused"):
        pass


def test_reads_do_not_trip_the_spec_lock_guard(file_db_app, user_id):
    """Reading first is fine: every save and run reads the project row before
    it takes the lock, inside the session's open transaction."""
    from utk_curio.backend.app.users.models import User

    assert db.session.execute(select(User.name)).scalars().all() == ["Alice"]
    assert db.session().in_transaction()

    with storage.spec_write_lock(str(user_id), "after-a-read"):
        assert db.session.execute(select(User.name)).scalars().all() == ["Alice"]
