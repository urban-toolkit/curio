"""Several people signing up at the same moment all get an account.

A request reads before it writes -- sign-up checks the username, creates the
user, seeds the examples, then inserts the session -- and SQLite refuses that
last write outright when another connection committed in between. Not after a
wait: ``busy_timeout`` covers a connection queuing for the write lock, not one
whose snapshot went stale, so the failure is immediate and arrives at the
client as a 500. Five simultaneous sign-ups against a real stack lost three
of them; that is what ``extensions.commit_with_retry`` exists to stop.

These tests need a file-backed database: ``sqlite://`` gives every connection
its own private in-memory database, so no two of them can ever contend.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from utk_curio.backend.app import create_app
from utk_curio.backend.extensions import commit_with_retry, db as _db
from utk_curio.backend.tests._unit_fixtures import TestConfig

USERS = 8


@pytest.fixture()
def file_db_app(tmp_path):
    class FileDbConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'concurrent.db'}"

    application = create_app(FileDbConfig)
    with application.app_context():
        _db.create_all()
    yield application
    with application.app_context():
        _db.session.remove()
        _db.drop_all()


def _signup_all(application, count: int):
    """Register *count* users at the same instant; return their responses."""
    results: list[tuple[int, str]] = []
    lock = threading.Lock()
    ready = threading.Barrier(count)

    def register(index: int) -> None:
        with application.test_client() as client:
            ready.wait(timeout=30)
            response = client.post("/api/auth/signup", json={
                "name": f"User {index}",
                "username": f"racer{index}",
                "password": "correct-horse-battery",
            })
            with lock:
                results.append((response.status_code, response.get_data(as_text=True)))

    threads = [threading.Thread(target=register, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def test_simultaneous_signups_all_succeed(file_db_app):
    """A smoke test for the whole path, not the proof.

    Whether these eight collide depends on how long each one holds the write
    lock, which on a bare test database is microseconds. The test below forces
    the collision instead.
    """
    results = _signup_all(file_db_app, USERS)

    assert len(results) == USERS
    failures = [(status, body[:200]) for status, body in results if status != 201]
    assert not failures, f"{len(failures)} of {USERS} sign-ups failed: {failures[:3]}"

    with file_db_app.app_context():
        from utk_curio.backend.app.users.models import User, UserSession
        assert User.query.count() == USERS
        # One session each: the insert that used to be the casualty.
        assert UserSession.query.count() == USERS


@contextlib.contextmanager
def _another_writer_holding_the_lock(db_path: str, seconds: float):
    """Hold SQLite's write lock from a second connection, as a slow request would."""
    released = threading.Event()
    started = threading.Event()

    def hold() -> None:
        conn = sqlite3.connect(db_path, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            started.set()
            time.sleep(seconds)
            conn.execute("COMMIT")
        finally:
            conn.close()
            released.set()

    thread = threading.Thread(target=hold)
    thread.start()
    started.wait(timeout=10)
    try:
        yield
    finally:
        thread.join(timeout=30)
        assert released.is_set()


def test_a_write_that_loses_the_race_still_lands(file_db_app, tmp_path):
    """The retry is what turns a refused write into a successful one.

    ``busy_timeout`` is squeezed to 1ms so the contention fails immediately
    instead of being absorbed by SQLite's own wait -- which is exactly the
    position a request is in when its write arrives after somebody else's
    commit, timeout or no timeout.
    """
    from utk_curio.backend.app.users import repositories as repo
    from utk_curio.backend.app.users.models import UserSession

    db_path = str(tmp_path / "concurrent.db")
    with file_db_app.app_context():
        user = repo.create_user(username="racer", name="Racer", type="programmer")
        _db.session.execute(text("PRAGMA busy_timeout=1"))

        with _another_writer_holding_the_lock(db_path, seconds=0.25):
            # Retries across the holder's transaction rather than 500ing.
            session = repo.create_session(user.id)

        assert session.token
        assert UserSession.query.filter_by(user_id=user.id).count() == 1


def test_without_the_retry_the_same_write_fails(file_db_app, tmp_path):
    """The other half of the proof: the plain commit does not survive it."""
    from utk_curio.backend.app.users import repositories as repo
    from utk_curio.backend.app.users.models import UserSession

    db_path = str(tmp_path / "concurrent.db")
    with file_db_app.app_context():
        user = repo.create_user(username="racer2", name="Racer", type="programmer")
        _db.session.execute(text("PRAGMA busy_timeout=1"))

        with _another_writer_holding_the_lock(db_path, seconds=0.25):
            with pytest.raises(OperationalError, match="(?i)database is locked"):
                _db.session.add(UserSession(
                    user_id=user.id,
                    token="plain-commit",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                    last_seen_at=datetime.now(timezone.utc),
                ))
                _db.session.commit()
        _db.session.rollback()


def test_commit_with_retry_reapplies_the_change_after_a_rollback(file_db_app):
    """The change is replayed, not just the commit.

    A rollback discards the pending object along with the transaction, so a
    helper that retried only ``commit()`` would report success having written
    nothing.
    """
    from utk_curio.backend.app.users.models import User

    attempts = {"count": 0}

    def _apply():
        attempts["count"] += 1
        user = User(username=f"retried", name="Retried", type="programmer")
        _db.session.add(user)
        if attempts["count"] == 1:
            # What SQLite raises when this transaction lost the race.
            raise OperationalError("INSERT", {}, Exception("database is locked"))
        return user

    with file_db_app.app_context():
        created = commit_with_retry(_apply)
        assert attempts["count"] == 2
        assert created.id is not None
        assert User.query.filter_by(username="retried").count() == 1


def test_a_real_error_is_not_retried(file_db_app):
    """Anything that is not a lost race surfaces immediately."""
    attempts = {"count": 0}

    def _apply():
        attempts["count"] += 1
        raise OperationalError("SELECT", {}, Exception("no such table: nope"))

    with file_db_app.app_context():
        with pytest.raises(OperationalError):
            commit_with_retry(_apply)
    assert attempts["count"] == 1


def test_the_session_stamp_is_not_rewritten_on_every_request(file_db_app):
    """The busiest write in the system was a field nothing reads.

    ``last_seen_at`` exists to say roughly when a session was last active;
    expiry is decided by ``expires_at``. Writing it per request turned every
    read-only call into a writer, and on one SQLite file that was what a
    hundred users collided over.
    """
    from utk_curio.backend.app.users import repositories as repo

    with file_db_app.app_context():
        user = repo.create_user(username="toucher", name="T", type="programmer")
        session = repo.create_session(user.id)
        first = session.last_seen_at

        for _ in range(20):
            repo.touch_session(session)

        assert session.last_seen_at == first, (
            "a burst of requests rewrote the session stamp; that write is the "
            "one the 100-user run kept losing"
        )


def test_the_session_stamp_is_refreshed_once_it_is_stale(file_db_app):
    """It is still a liveness stamp: past the interval, it moves."""
    from datetime import timedelta

    from utk_curio.backend.app.users import repositories as repo

    with file_db_app.app_context():
        user = repo.create_user(username="toucher2", name="T", type="programmer")
        session = repo.create_session(user.id)
        stale = datetime.now(timezone.utc) - repo.SESSION_TOUCH_INTERVAL - timedelta(seconds=1)
        session.last_seen_at = stale.replace(tzinfo=None)
        _db.session.commit()

        repo.touch_session(session)

        assert session.last_seen_at.replace(tzinfo=timezone.utc) > stale
