"""A resource's thread locks last while something holds them, not for the
life of the process (``common/file_locks.py``).

Every dataflow a backend touches gets a spec lock and a history lock of its
own, and each signup seeds 61 dataflows. Kept for the life of the process,
the stress job's backend held 191,370 of these locks after 1,395 signups,
about 140 a signup (tmp/backend-rss-probe, run 43752339941). A lock that
nothing references cannot be held or waited on, so it can go; one that is
held or waited on must stay the one lock every caller of its resource gets.
"""
from __future__ import annotations

import gc
import threading
import time

from utk_curio.backend.app.common import file_locks

NAMESPACE = "test-lock-lifetime"


def _kept(table) -> list:
    """The keys of this module's resources that *table* still holds."""
    gc.collect()
    return sorted(key for key in list(table.keys()) if key[0] == NAMESPACE)


def _until(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


# ---------------------------------------------------------------------------
# What a resource leaves behind once nothing holds it
# ---------------------------------------------------------------------------

def test_the_locks_of_resources_nothing_holds_are_not_kept(tmp_path):
    for n in range(100):
        with file_locks.exclusive_lock(tmp_path / f"w{n}.lock", namespace=NAMESPACE, key=f"w{n}"):
            pass
        with file_locks.shared_lock(tmp_path / f"r{n}.lock", namespace=NAMESPACE, key=f"r{n}"):
            pass
    kept = _kept(file_locks._thread_locks)
    assert kept == [], f"{len(kept)} thread lock(s) outlived every hold of their resource: {kept[:3]}"
    readers = _kept(file_locks._readers)
    assert readers == [], f"{len(readers)} resource(s) kept their readers' count after the last reader: {readers[:3]}"


def test_a_keyed_lock_is_one_lock_while_it_is_referenced_and_forgotten_after():
    first = file_locks.keyed_thread_lock(NAMESPACE, "referenced")
    assert file_locks.keyed_thread_lock(NAMESPACE, "referenced") is first, "two callers got two locks for one resource"
    with first:
        assert file_locks.keyed_thread_lock(NAMESPACE, "referenced").locked(), "a caller did not get the held lock"
    del first
    kept = _kept(file_locks._thread_locks)
    assert kept == [], f"the lock outlived its last reference: {kept}"


# ---------------------------------------------------------------------------
# What must not change: holders of one resource still exclude each other
# ---------------------------------------------------------------------------

def test_a_second_writer_waits_for_the_first_to_leave(tmp_path):
    path = tmp_path / "one.lock"
    inside, release, second_in = threading.Event(), threading.Event(), threading.Event()
    order = []

    def first():
        with file_locks.exclusive_lock(path, namespace=NAMESPACE, key="one"):
            order.append("first in")
            inside.set()
            release.wait(10)
            order.append("first out")

    def second():
        with file_locks.exclusive_lock(path, namespace=NAMESPACE, key="one"):
            order.append("second in")
            second_in.set()

    holder = threading.Thread(target=first)
    holder.start()
    assert inside.wait(5), "the first writer never got in"
    waiter = threading.Thread(target=second)
    waiter.start()
    assert not second_in.wait(0.3), f"the second writer got in beside the first: {order}"
    release.set()
    holder.join(10)
    waiter.join(10)
    assert order == ["first in", "first out", "second in"], order


def test_a_writer_waits_out_a_reader_and_the_next_reader_waits_out_the_writer(tmp_path):
    """The reader passes through the resource's thread lock and leaves it
    behind, so while it reads nothing but its count of readers stays."""
    path = tmp_path / "shared.lock"
    reading, release = threading.Event(), threading.Event()
    order = []

    def first_reader():
        with file_locks.shared_lock(path, namespace=NAMESPACE, key="shared"):
            order.append("first reader in")
            reading.set()
            release.wait(10)
            order.append("first reader out")

    def writer():
        with file_locks.exclusive_lock(path, namespace=NAMESPACE, key="shared"):
            order.append("writer")

    def next_reader():
        with file_locks.shared_lock(path, namespace=NAMESPACE, key="shared"):
            order.append("next reader")

    first = threading.Thread(target=first_reader)
    first.start()
    assert reading.wait(5), "the first reader never got in"
    writing = threading.Thread(target=writer)
    writing.start()
    # The writer holds the resource's thread lock while it waits for the reader.
    assert _until(lambda: file_locks.keyed_thread_lock(NAMESPACE, "shared").locked()), "the writer never came"
    following = threading.Thread(target=next_reader)
    following.start()
    following.join(0.3)
    writing.join(0.3)
    assert order == ["first reader in"], f"the writer or the next reader got in beside the first reader: {order}"
    release.set()
    for thread in (first, writing, following):
        thread.join(10)
    assert order == ["first reader in", "first reader out", "writer", "next reader"], order
