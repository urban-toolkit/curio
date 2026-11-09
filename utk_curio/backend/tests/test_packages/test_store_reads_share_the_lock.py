"""Readers of an account's package store share its lock; a writer holds it alone.

Every read of a package store took ``package_seed_lock``, a per-account lock
that let one thread in at a time. A dataflow's agents read its owner's store
many times per turn: the templates, the modules, the models, the skills of its
packages. So in a room of ten people, each asking an agent, the ten turns read
the owner's store one at a time. With 100 agent turns at once
(``tests/stress``, run 42528241074 of the stage with agents), turn threads
spent 14.3% of their samples waiting for or holding that lock.

So readers take it shared: any number of them at once, never with a writer.
A writer (the seeder's swap, an install, an uninstall, a metadata edit) still
takes it alone, and once it waits, a reader that comes after it waits behind
it, so a stream of reads cannot keep the seeder out. Across processes,
readers take the lock file shared and writers exclusive.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""
from __future__ import annotations

import threading
import time

import pytest

ACCOUNT = "guest"


def _until(predicate, timeout: float = 10.0) -> bool:
    """Whether *predicate* comes true within *timeout* seconds."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return False
        threading.Event().wait(0.01)
    return True


def test_two_readers_of_one_store_read_it_at_once(tmp_curio, monkeypatch):
    """Two reads of the store's index meet inside the lock: each waits there
    for the other, which only a shared lock lets in."""
    from utk_curio.backend.app.packages.application import store_reads

    both_inside = threading.Barrier(2, timeout=10)
    real = store_reads._store_index

    def _meet_the_other_reader(user_key):
        both_inside.wait()
        return real(user_key)

    monkeypatch.setattr(store_reads, "_store_index", _meet_the_other_reader)
    read: list = []
    errors: list = []

    def _read():
        try:
            read.append(store_reads._locked_store_index(ACCOUNT))
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    readers = [threading.Thread(target=_read) for _ in range(2)]
    for reader in readers:
        reader.start()
    for reader in readers:
        reader.join(30)

    assert not errors, f"two readers of one store waited for each other: {errors!r}"
    assert read == [{}, {}]


def test_a_writer_waits_for_the_reader_inside_and_keeps_the_next_reader_out(tmp_curio):
    from utk_curio.backend.app.common import file_locks
    from utk_curio.backend.app.packages.infrastructure.locks import SEED_LOCK_NAMESPACE, package_seed_lock

    order: list[str] = []
    reading, release = threading.Event(), threading.Event()

    def _first_reader():
        with package_seed_lock(ACCOUNT, shared=True):
            order.append("first reader in")
            reading.set()
            release.wait(10)
            order.append("first reader out")

    def _writer():
        with package_seed_lock(ACCOUNT):
            order.append("writer")

    def _next_reader():
        with package_seed_lock(ACCOUNT, shared=True):
            order.append("next reader")

    first = threading.Thread(target=_first_reader)
    first.start()
    assert reading.wait(5), "the first reader never got in"
    writer = threading.Thread(target=_writer)
    writer.start()
    # The writer holds the store's thread lock while it waits for the reader.
    assert _until(file_locks.keyed_thread_lock(SEED_LOCK_NAMESPACE, ACCOUNT).locked), "the writer never came"
    following = threading.Thread(target=_next_reader)
    following.start()
    following.join(0.3)
    writer.join(0.3)

    assert order == ["first reader in"], f"the writer or the next reader got in beside the first reader: {order}"
    release.set()
    for thread in (first, writer, following):
        thread.join(10)
    assert order == ["first reader in", "first reader out", "writer", "next reader"], order


def test_readers_share_the_lock_file_and_a_writer_waits_for_them(tmp_path):
    """The cross-process layer: two readers' descriptors hold the file shared
    at once, and a writer's cannot take it until both let go."""
    import fcntl

    from utk_curio.backend.app.common import file_locks

    path = tmp_path / ".seed.lock"
    with file_locks.interprocess_lock(path, shared=True):
        with file_locks.interprocess_lock(path, shared=True):
            with open(path, "a") as writer:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with open(path, "a") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(writer, fcntl.LOCK_UN)


def test_a_reader_waits_while_a_writer_changes_the_store(tmp_curio):
    from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock

    writing, release = threading.Event(), threading.Event()
    read = threading.Event()

    def _write():
        with package_seed_lock(ACCOUNT):
            writing.set()
            release.wait(10)

    def _read():
        with package_seed_lock(ACCOUNT, shared=True):
            read.set()

    writer = threading.Thread(target=_write)
    writer.start()
    assert writing.wait(5)
    reader = threading.Thread(target=_read)
    reader.start()
    reader.join(0.3)
    assert not read.is_set(), "a reader read the store inside a writer's hold"
    release.set()
    writer.join(10)
    reader.join(10)
    assert read.is_set()
