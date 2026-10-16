"""Seeding an account's examples waits for the database instead of failing.

Each example was seeded in its own SAVEPOINT. With the driver's legacy
transaction control the SAVEPOINT opened the transaction, and the reads in it
fixed the connection's snapshot before its ``INSERT``. SQLite refuses such a
write at once, without calling the busy handler, while another connection
holds the write lock or has committed since that snapshot. ``ROLLBACK TO
SAVEPOINT`` kept the snapshot, so every later example failed too ("Failed to
seed example"). Nothing kept two requests for one account from seeding at
once either.

The interleavings are forced with events, every connection's busy timeout is
squeezed to 2 s, and the database is a file, as on a server (``file_db_app``).
"""
from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
from collections import Counter

import pytest
from sqlalchemy import event

from utk_curio.backend.app.common import file_locks
from utk_curio.backend.app.projects import seed, storage
from utk_curio.backend.extensions import db
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_datasets.test_save_lock_order import (  # noqa: F401
    HOLD_SECONDS,
    STEP_SECONDS,
    _assert_finished_in_time,
    _release_and_join,
    _start,
    squeezed_busy_timeout,
)

TOKEN = "seed-waits-token"
SEED_LOGGER = "utk_curio.backend.app.projects.seed"
# How long the second caller waits, at the seeding lock or on the database,
# before the held one goes on.
WAIT_SECONDS = 0.2
_INSERT_PROJECT = re.compile(r"\s*INSERT\s+INTO\s+project\b", re.IGNORECASE)


@pytest.fixture(autouse=True)
def examples_enabled(monkeypatch):
    """Seeding is on, as on a stack started with ``--with-examples``."""
    monkeypatch.setenv("CURIO_SEED_EXAMPLES", "1")


@pytest.fixture()
def user_id(file_db_app):
    """Erin, a new account with no examples yet, and her session token."""
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username="erin", name="Erin", email="erin@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=TOKEN))
    db.session.commit()
    return user.id


def _spec() -> dict:
    return {"dataflow": {"name": "Seed waits", "nodes": [
        {"id": "a", "type": "curio.builtin/computation-analysis", "content": "return 1"},
    ], "edges": []}}


def _create_project(application) -> str:
    response = application.test_client().post(
        "/api/projects",
        data=json.dumps({"name": "Seed waits", "spec": _spec(), "outputs": []}),
        headers=auth_headers(TOKEN),
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["id"]


def _save(application, project_id: str):
    """The canvas's save of Erin's own project."""
    return application.test_client().put(
        f"/api/projects/{project_id}",
        data=json.dumps({"spec": _spec(), "outputs": []}),
        headers=auth_headers(TOKEN),
    )


def _example_ids(user_id: int) -> list:
    """The ids of every example the account should have, sorted."""
    from utk_curio.backend.app.users.models import User

    ids = sorted(seed.shipped_sources(db.session.get(User, user_id)))
    assert ids, "no shipped dataflows to seed"
    return ids


def _seed_and_list(application, user_id: int) -> tuple:
    """A first listing: seed the account's examples, then list its projects.
    Returns how many examples it seeded and the example ids it lists."""
    from utk_curio.backend.app.projects import services
    from utk_curio.backend.app.users.models import User

    with application.app_context():
        user = db.session.get(User, user_id)
        seeded = seed.ensure_user_examples_seeded(user)
        listed = sorted(s.id for s in services.list_projects(user) if s.is_example)
        return seeded, listed


def _hold_at_first_spec_write(monkeypatch, thread_name: str):
    """Hold *thread_name* at its first spec write. A seeder and a save each
    write the project's row just before it, so the held thread holds SQLite's
    write lock. Returns the (reached, release) events."""
    reached, release = threading.Event(), threading.Event()
    real = storage.write_spec

    def held(user_key, project_id, spec):
        if threading.current_thread().name == thread_name and not reached.is_set():
            reached.set()
            release.wait(timeout=HOLD_SECONDS)
        return real(user_key, project_id, spec)

    monkeypatch.setattr(storage, "write_spec", held)
    return reached, release


@contextlib.contextmanager
def _signal_at_project_insert(signal: threading.Event, thread_name: str):
    """Set *signal* when *thread_name* sends an ``INSERT INTO project``."""
    def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
        if threading.current_thread().name == thread_name and _INSERT_PROJECT.match(statement):
            signal.set()

    engine = db.engine
    event.listen(engine, "before_cursor_execute", observe)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def _signal_at_seed_lock(monkeypatch, signal: threading.Event, thread_name: str) -> None:
    """Set *signal* when *thread_name* asks for the account's seeding lock."""
    real = file_locks.exclusive_lock

    @contextlib.contextmanager
    def observed(*args, **kwargs):
        if threading.current_thread().name == thread_name:
            signal.set()
        with real(*args, **kwargs):
            yield

    # ``raising=False``: before the fix the seeder took no lock to observe.
    monkeypatch.setattr(seed, "exclusive_lock", observed, raising=False)


def _seed_errors(caplog) -> list:
    return [
        f"{record.getMessage()}: {record.exc_info[1] if record.exc_info else ''}"
        for record in caplog.records
        if record.name == SEED_LOGGER and record.levelno >= logging.WARNING
    ]


def _not_seeded_once(user_id: int, example_ids: list) -> dict:
    """Each example whose row count or spec write count is not 1, with both."""
    from utk_curio.backend.app.projects.models import Project

    rows = Counter(row.id for row in Project.query.filter_by(user_id=user_id).all())
    counts = {
        project_id: (rows[project_id], storage.spec_revision(str(user_id), project_id))
        for project_id in example_ids
    }
    return {project_id: count for project_id, count in counts.items() if count != (1, 1)}


def test_two_first_listings_seed_the_examples_once(
    file_db_app, user_id, squeezed_busy_timeout, monkeypatch, caplog,
):
    """Two requests list a new account's projects at once, as the Scenario
    Catalog's two requests do when it opens. The first is held while it writes
    its first example. The second must wait for it, then list every example,
    rather than fail every write at once and list none."""
    caplog.set_level(logging.WARNING, logger=SEED_LOGGER)
    examples = _example_ids(user_id)
    reached, release = _hold_at_first_spec_write(monkeypatch, "first listing")
    in_position = threading.Event()
    _signal_at_seed_lock(monkeypatch, in_position, "second listing")

    threads: list = []
    with _signal_at_project_insert(in_position, "second listing"):
        try:
            first = _start(threads, "first listing", lambda: _seed_and_list(file_db_app, user_id))
            assert reached.wait(STEP_SECONDS), "the first listing never wrote its first example"
            second = _start(threads, "second listing", lambda: _seed_and_list(file_db_app, user_id))
            assert in_position.wait(STEP_SECONDS), (
                "the second listing neither asked for the seeding lock nor wrote an example"
            )
            time.sleep(WAIT_SECONDS)
        finally:
            released_at = _release_and_join(threads, release)

    errors = _seed_errors(caplog)
    assert not errors, f"{len(errors)} seeding errors, the first: {errors[:3]}"
    _assert_finished_in_time({"first listing": first, "second listing": second}, released_at)
    for name, outcome in (("first listing", first), ("second listing", second)):
        listed = outcome["value"][1]
        assert listed == examples, f"the {name} listed {len(listed)} of {len(examples)} examples"
    assert sorted([first["value"][0], second["value"][0]]) == [0, len(examples)]
    assert second["done_at"] > released_at, "the second listing did not wait for the first"
    assert _not_seeded_once(user_id, examples) == {}


def test_a_first_listing_during_a_save_waits_for_the_database(
    file_db_app, user_id, squeezed_busy_timeout, monkeypatch, caplog,
):
    """A new account's first listing seeds its examples while a save of one of
    its projects holds SQLite's write lock. Each example's write must wait for
    the save rather than fail at once: the marker then still listed every
    example, so the account never got them."""
    caplog.set_level(logging.WARNING, logger=SEED_LOGGER)
    examples = _example_ids(user_id)
    project_id = _create_project(file_db_app)
    reached, release = _hold_at_first_spec_write(monkeypatch, "save")
    wrote = threading.Event()

    threads: list = []
    with _signal_at_project_insert(wrote, "listing"):
        try:
            save = _start(threads, "save", lambda: _save(file_db_app, project_id))
            assert reached.wait(STEP_SECONDS), "the save never wrote its project's row"
            listing = _start(threads, "listing", lambda: _seed_and_list(file_db_app, user_id))
            assert wrote.wait(STEP_SECONDS), "the listing never wrote its first example"
            time.sleep(WAIT_SECONDS)
        finally:
            released_at = _release_and_join(threads, release)

    errors = _seed_errors(caplog)
    assert not errors, f"{len(errors)} seeding errors, the first: {errors[:3]}"
    _assert_finished_in_time({"save": save, "listing": listing}, released_at)
    assert save["value"].status_code == 200, save["value"].get_data(as_text=True)
    assert listing["value"] == (len(examples), examples)
    # A later listing seeds nothing more and still shows every example.
    assert _seed_and_list(file_db_app, user_id) == (0, examples)
    assert _not_seeded_once(user_id, examples) == {}
