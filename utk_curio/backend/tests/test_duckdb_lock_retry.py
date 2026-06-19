"""Regression tests for the DuckDB cross-process lock retry (_connect_with_retry).

The sandbox holds a read-write connection during node execution while the backend
opens short-lived read-only connections (auto-install, output resolution). With
save-output-on-by-default the backend hits those reads on every node run, so a
transient "Conflicting lock" must be retried rather than surfaced as a flaky node
failure.
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
