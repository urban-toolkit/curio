"""The shared DuckDB connection survives a release from another request.

DuckDB allows one cross-process writer, so every sandbox execution path closes
the shared connection when it finishes and the next one reopens it. On a
threaded server those releases land while other requests are still using the
connection. At ten simultaneous users the stress tiers turned that into node
failures: ``Connection Error: Connection already closed!`` from the INSERT in
``save_to_duckdb``, and ``Catalog Error: Column with name session_id`` from two
threads racing ``init_db``'s migration.

These tests pin the two halves of the fix: a release waits for the requests
still in flight, and ``init_db`` is serialized.
"""
from __future__ import annotations

import threading

import pytest

from utk_curio.sandbox.util import db as db_module


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", "./data/")
    db_module.release_connection(force=True)
    yield tmp_path
    db_module.release_connection(force=True)


def test_release_is_deferred_while_a_request_holds_the_connection(workspace):
    db_module.init_db()
    con = db_module.get_connection()

    with db_module.connection_in_use():
        # Another thread finishing its run asks for the close.
        db_module.release_connection()
        # The holder can still use the connection it was handed.
        assert con.execute("SELECT 1").fetchone() == (1,)
        assert db_module._connection is not None

    # ...and the deferred close happens as soon as the holder is done, so the
    # backend's read-only opens are not blocked any longer than before.
    assert db_module._connection is None


def test_a_forced_release_still_closes_immediately(workspace):
    db_module.init_db()
    with db_module.connection_in_use():
        db_module.release_connection(force=True)
        assert db_module._connection is None


def test_concurrent_writers_do_not_lose_the_connection(workspace):
    """Twelve threads doing what two execution paths do: use, then release."""
    db_module.init_db()
    errors: list[Exception] = []
    ready = threading.Barrier(12)

    def one_request(index: int) -> None:
        try:
            ready.wait(timeout=30)
            for _ in range(20):
                with db_module.connection_in_use():
                    con = db_module.get_connection()
                    con.execute(
                        "INSERT INTO artifacts (id, node_id, kind, value_str) "
                        "VALUES (?, ?, ?, ?)",
                        [f"art-{index}-{_}", f"node-{index}", "str", "v"],
                    )
                    # What every execution path does on the way out.
                    db_module.release_connection()
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=one_request, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, f"{len(errors)} request(s) failed: {errors[:3]}"

    rows = db_module.get_connection().execute(
        "SELECT count(*) FROM artifacts"
    ).fetchone()
    assert rows[0] == 12 * 20


def test_init_db_migration_is_serialized(workspace):
    """Concurrent first-time init must not race the DESCRIBE/ALTER migration."""
    errors: list[Exception] = []
    ready = threading.Barrier(8)

    def initialize() -> None:
        try:
            ready.wait(timeout=30)
            db_module.init_db()
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=initialize) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, f"init_db raced: {errors[:3]}"
    columns = {
        row[0] for row in
        db_module.get_connection().execute("DESCRIBE artifacts").fetchall()
    }
    assert "session_id" in columns


def test_each_thread_reads_what_another_just_committed(workspace):
    """A row committed by one thread is visible to every other, at once.

    Threads used to share one connection object, and therefore one
    transaction context: a reader could run inside a transaction another
    thread had open and miss a row that was already committed. It surfaced as
    "No artifact with id X" for artifacts that were in the database the whole
    time, which failed nodes under the stress tiers at five users.
    """
    db_module.init_db()
    failures: list[str] = []
    ready = threading.Barrier(6)

    def write_then_have_others_read(index: int) -> None:
        art_id = f"visible-{index}"
        with db_module.connection_in_use():
            db_module.get_connection().execute(
                "INSERT INTO artifacts (id, node_id, kind, value_str) "
                "VALUES (?, ?, ?, ?)",
                [art_id, f"node-{index}", "str", "v"],
            )
        ready.wait(timeout=30)
        # Every thread now looks for every other thread's row.
        for other in range(6):
            with db_module.connection_in_use():
                row = db_module.get_read_connection().execute(
                    "SELECT id FROM artifacts WHERE id = ?", [f"visible-{other}"],
                ).fetchone()
            if row is None:
                failures.append(f"thread {index} could not see visible-{other}")

    threads = [
        threading.Thread(target=write_then_have_others_read, args=(i,))
        for i in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not failures, failures[:5]


def test_a_cursor_is_not_reused_after_the_connection_closes(workspace):
    """A thread that outlives a release gets a fresh cursor, not a dead one."""
    db_module.init_db()
    first = db_module.get_connection()
    db_module.release_connection(force=True)

    second = db_module.get_connection()
    assert second is not first
    assert second.execute("SELECT 1").fetchone() == (1,)
