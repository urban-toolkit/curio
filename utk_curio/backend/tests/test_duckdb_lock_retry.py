"""Regression tests for the DuckDB cross-process lock retry (_connect_with_retry).

The sandbox holds a read-write connection during node execution while the backend
opens short-lived read-only connections (auto-install, output resolution). With
save-output-on-by-default the backend hits those reads on every node run, so a
transient "Conflicting lock" must be retried rather than surfaced as a flaky node
failure.

Contention wording is platform-specific, and that matters: Windows reports a
sharing violation that never says "lock", so a predicate written only against
the POSIX phrasing let the retry be skipped entirely on Windows and failed
E2E nodes intermittently. ``test_windows_sharing_violation_is_retried``
pins that case.
"""
from __future__ import annotations

import pytest

from utk_curio.sandbox.util import db


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(db.time, "sleep", lambda *_a, **_k: None)


def test_retries_lock_conflict_then_succeeds(monkeypatch):
    calls = {"n": 0}
    sentinel = object()

    def fake_connect(path, read_only=False):
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("Could not set lock on file: Conflicting lock is held")
        return sentinel

    monkeypatch.setattr(db.duckdb, "connect", fake_connect)
    assert db._connect_with_retry("x.duckdb") is sentinel
    assert calls["n"] == 3  # failed twice, succeeded on the third


def test_non_lock_error_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake_connect(path, read_only=False):
        calls["n"] += 1
        raise Exception("syntax error near FROM")

    monkeypatch.setattr(db.duckdb, "connect", fake_connect)
    with pytest.raises(Exception, match="syntax error"):
        db._connect_with_retry("x.duckdb")
    assert calls["n"] == 1  # surfaced immediately, no retry


def test_persistent_lock_conflict_eventually_raises(monkeypatch):
    calls = {"n": 0}

    def fake_connect(path, read_only=False):
        calls["n"] += 1
        raise Exception("Conflicting lock is held")

    monkeypatch.setattr(db.duckdb, "connect", fake_connect)
    with pytest.raises(Exception, match="Conflicting lock"):
        db._connect_with_retry("x.duckdb")
    assert calls["n"] == db._LOCK_RETRY_ATTEMPTS


# Fake error *text*, not a path this suite touches. Every test below
# monkeypatches ``duckdb.connect`` to raise this string, so nothing is ever
# opened and no file is read -- only the message wording is under test.
#
# This is what DuckDB says on Windows when another process holds the database
# file. It contains neither "lock" nor "conflicting", which is exactly why the
# retry silently no-oped on this platform. The filenames are deliberately
# obvious placeholders so this cannot be mistaken for a real location.
WINDOWS_SHARING_VIOLATION = (
    'IO Error: Cannot open file "<fake-db-path>/curio_data.duckdb": '
    'The process cannot access the file because it is being used by another '
    'process. File is already open in <fake-python-exe> (PID 4048)'
)


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(WINDOWS_SHARING_VIOLATION, id="windows-sharing-violation"),
        pytest.param("Could not set lock on file: Conflicting lock is held", id="posix-conflicting-lock"),
        pytest.param("resource temporarily unavailable", id="posix-eagain"),
    ],
)
def test_contention_messages_are_classified_as_lock_conflicts(message):
    """Every platform's contention wording must be retryable."""
    assert db._is_lock_conflict(Exception(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        pytest.param("syntax error near FROM", id="sql-error"),
        pytest.param("IO Error: Corrupt database file", id="corruption"),
        pytest.param("IO Error: No such file or directory", id="missing-file"),
    ],
)
def test_real_faults_are_not_classified_as_lock_conflicts(message):
    """Widening the predicate must not swallow genuine faults into a retry loop."""
    assert db._is_lock_conflict(Exception(message)) is False


def test_windows_sharing_violation_is_retried(monkeypatch):
    """Regression: the Windows message must engage the retry, not re-raise.

    Before the fix ``_is_lock_conflict`` missed this wording, so the first
    attempt re-raised and a transient collision with a backend read-only open
    surfaced as a hard node failure in the E2E workflow suite.
    """
    calls = {"n": 0}
    sentinel = object()

    def fake_connect(path, read_only=False):
        calls["n"] += 1
        if calls["n"] < 4:
            raise Exception(WINDOWS_SHARING_VIOLATION)
        return sentinel

    monkeypatch.setattr(db.duckdb, "connect", fake_connect)
    assert db._connect_with_retry("x.duckdb") is sentinel
    assert calls["n"] == 4, "the Windows wording must be retried, not surfaced immediately"
