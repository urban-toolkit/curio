"""Tests for the append-only local record of agent runs and token usage.

This file used to be mostly about denial: account/template/attachment run
ceilings, the monetary spend ladder, the fail-closed rule, and the races that
proved exactly one caller won the last slot. None of that exists now - Curio
does not cap or price agent runs - so what is left tests the ledger as a
record: it counts every run exactly once, it never loses usage, and it
tolerates a torn file.

The concurrency case survives with a different claim. It no longer asks
"exactly N admits"; it asks that N concurrent appends all land, which is what a
record has to guarantee once nothing is being rationed.
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime, timezone

import pytest

from utk_curio.backend.app.agents.repositories import ledger

UKEY = "42"


def _day_file(day=None):
    return ledger._day_path(UKEY, day or ledger._today())


class TestReserveSettle:
    def test_reserve_settle_roundtrip_and_aggregates(self, tmp_curio):
        reservation = ledger.reserve(UKEY, template_key="p1/a@1")
        ledger.settle(UKEY, reservation, usage={"inputTokens": 1000, "outputTokens": 2000})
        agg = ledger.aggregates(UKEY)
        assert agg["runs"] == 1
        assert agg["byTemplate"] == {"p1/a@1": 1}
        assert agg["usage"] == {"inputTokens": 1000, "outputTokens": 2000}

    def test_no_usd_is_recorded(self, tmp_curio):
        # Curio ships no price table, so a cost figure would be invented.
        reservation = ledger.reserve(UKEY)
        entry = ledger.settle(UKEY, reservation, usage={"inputTokens": 1, "outputTokens": 2})
        assert "costUsd" not in entry
        assert "actualSpendUsd" not in ledger.aggregates(UKEY)

    def test_reserve_never_denies(self, tmp_curio):
        # There is no ceiling at any scope; a hundred runs all record.
        for _ in range(100):
            ledger.reserve(UKEY)
        assert ledger.aggregates(UKEY)["runs"] == 100

    def test_attachment_runs_are_attributed(self, tmp_curio):
        ledger.reserve(UKEY, template_key="p1/a@1", attachment_key="att-1")
        ledger.reserve(UKEY, template_key="p1/a@1", attachment_key="att-2")
        ledger.reserve(UKEY, template_key="p1/a@1", attachment_key="att-1")
        agg = ledger.aggregates(UKEY)
        assert agg["byAttachment"] == {"att-1": 2, "att-2": 1}
        assert agg["byTemplate"] == {"p1/a@1": 3}

    def test_double_settle_is_idempotent(self, tmp_curio):
        reservation = ledger.reserve(UKEY)
        first = ledger.settle(UKEY, reservation, usage={"inputTokens": 1000, "outputTokens": 0})
        second = ledger.settle(UKEY, reservation, usage={"inputTokens": 999999, "outputTokens": 0})
        assert second == first  # first-write-wins
        assert ledger.aggregates(UKEY)["usage"]["inputTokens"] == 1000

    def test_settle_without_reserve_still_counts(self, tmp_curio):
        ledger.settle(
            UKEY,
            {"reservationId": "ghost", "day": ledger._today()},
            usage={"inputTokens": 5, "outputTokens": 5},
        )
        assert ledger.aggregates(UKEY)["usage"]["inputTokens"] == 5

    def test_an_unsettled_reserve_still_counts_as_a_run(self, tmp_curio):
        # Why the pair is kept rather than collapsed: a reserve with no settle
        # is a run that started and never reported back.
        ledger.reserve(UKEY)
        agg = ledger.aggregates(UKEY)
        assert agg["runs"] == 1
        assert agg["usage"] == {"inputTokens": 0, "outputTokens": 0}

    def test_settle_appends_never_rewrites(self, tmp_curio):
        reservation = ledger.reserve(UKEY)
        before = _day_file().read_text(encoding="utf-8")
        ledger.settle(UKEY, reservation, usage={"inputTokens": 1, "outputTokens": 1})
        after = _day_file().read_text(encoding="utf-8")
        assert after.startswith(before)  # append-only: prior bytes untouched

    def test_corrupt_line_is_skipped(self, tmp_curio):
        ledger.reserve(UKEY)
        with open(_day_file(), "a", encoding="utf-8") as handle:
            handle.write("{torn line\n")
        ledger.reserve(UKEY)
        assert ledger.aggregates(UKEY)["runs"] == 2

    def test_missing_file_reads_as_zeros(self, tmp_curio):
        assert ledger.aggregates(UKEY) == {
            "runs": 0,
            "byTemplate": {},
            "byAttachment": {},
            "usage": {"inputTokens": 0, "outputTokens": 0},
        }

    def test_housekeeping_usage_counts_tokens_but_not_a_run(self, tmp_curio):
        ledger.record_housekeeping_usage(
            UKEY, {"inputTokens": 5, "outputTokens": 3}, note="title-call"
        )
        agg = ledger.aggregates(UKEY)
        assert agg["runs"] == 0
        assert agg["usage"] == {"inputTokens": 5, "outputTokens": 3}

    def test_housekeeping_with_no_usage_writes_nothing(self, tmp_curio):
        ledger.record_housekeeping_usage(UKEY, None)
        assert not _day_file().exists()


class TestWindowing:
    def test_settle_lands_in_the_reservation_day(self, tmp_curio, monkeypatch):
        before_midnight = datetime(2026, 7, 28, 23, 59, 59, tzinfo=timezone.utc)
        after_midnight = datetime(2026, 7, 29, 0, 0, 5, tzinfo=timezone.utc)
        monkeypatch.setattr(ledger, "_now", lambda: before_midnight)
        reservation = ledger.reserve(UKEY)
        assert reservation["day"] == "2026-07-28"
        monkeypatch.setattr(ledger, "_now", lambda: after_midnight)
        ledger.settle(UKEY, reservation, usage={"inputTokens": 1000, "outputTokens": 0})
        assert ledger.aggregates(UKEY, "2026-07-28")["usage"]["inputTokens"] == 1000
        assert ledger.aggregates(UKEY, "2026-07-29")["runs"] == 0

    def test_windows_are_independent(self, tmp_curio, monkeypatch):
        monkeypatch.setattr(
            ledger, "_now", lambda: datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
        )
        ledger.reserve(UKEY)
        monkeypatch.setattr(
            ledger, "_now", lambda: datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        )
        ledger.reserve(UKEY)
        assert ledger.aggregates(UKEY, "2026-07-28")["runs"] == 1
        assert ledger.aggregates(UKEY, "2026-07-29")["runs"] == 1


class TestConcurrency:
    """The lock's remaining job: concurrent appends must not tear or drop."""

    def test_threads_all_record_without_tearing(self, tmp_curio):
        COUNT = 16
        barrier = threading.Barrier(COUNT)

        def attempt():
            barrier.wait()
            ledger.reserve(UKEY)

        threads = [threading.Thread(target=attempt) for _ in range(COUNT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Every append landed, and every line still parses: a dropped or torn
        # line would show up as a lower count here.
        assert ledger.aggregates(UKEY)["runs"] == COUNT

    @pytest.mark.skipif(sys.platform == "win32", reason="fork/flock are POSIX-only")
    def test_processes_all_record(self, tmp_curio):
        ledger.reserve(UKEY)
        pids = []
        for _ in range(2):
            pid = os.fork()
            if pid == 0:  # child
                try:
                    ledger.reserve(UKEY)
                    os._exit(0)
                except Exception:
                    os._exit(9)
            pids.append(pid)
        codes = [os.waitpid(pid, 0)[1] >> 8 for pid in pids]
        assert codes == [0, 0]
        assert ledger.aggregates(UKEY)["runs"] == 3


class TestADiskSyncHoldsNoOneBack:
    """A line is written under the account's lock and synced to disk once the
    lock is let go. On a strained disk one sync takes seconds, and each run
    of an account appends three lines (its reserve, its settle and its title's
    usage), so a sync made under the lock queued every run of the account
    behind every other's: in the 100-agent stress stage of 11-07, ten scripted
    turns of one dataflow each took about 90 s, waiting on each other's 30
    syncs. The run that appends still returns only once its own line is on
    disk."""

    #: Each kind of line, as the slow run appends it: a run's reserve, its
    #: settle, and the usage of its title's call.
    APPENDS = {
        "reserve": lambda: ledger.reserve(UKEY),
        "settle": lambda: ledger.settle(UKEY, {"reservationId": "r-slow", "day": ledger._today()},
                                        usage={"inputTokens": 3, "outputTokens": 1}),
        "usage": lambda: ledger.record_housekeeping_usage(UKEY, {"inputTokens": 2, "outputTokens": 1}),
    }

    @pytest.mark.parametrize("append", sorted(APPENDS))
    def test_a_slow_sync_of_one_runs_line_holds_no_other_run_of_the_account_back(
        self, tmp_curio, monkeypatch, append,
    ):
        syncing, let_go = threading.Event(), threading.Event()
        real_fsync = os.fsync
        synced = []

        def slow_sync(descriptor):
            """The slow run's sync waits for the test, as on a strained disk."""
            name = threading.current_thread().name
            if name == "slow-sync":
                syncing.set()
                assert let_go.wait(30), "the test never let the slow sync end"
            if name in ("slow-sync", "another-run"):
                synced.append(name)
            real_fsync(descriptor)

        monkeypatch.setattr(ledger.os, "fsync", slow_sync)
        slow = threading.Thread(target=self.APPENDS[append], name="slow-sync")
        other = threading.Thread(target=lambda: ledger.reserve(UKEY), name="another-run")
        try:
            slow.start()
            assert syncing.wait(10), f"the {append} line was never synced"
            other.start()
            other.join(5)
            assert not other.is_alive(), (
                f"another run of the account waited for the {append} line's disk sync: the account's "
                "lock was held across it")
            assert slow.is_alive(), f"the {append} returned before its own line was on disk"
        finally:
            let_go.set()
            slow.join(10)
            other.join(10)
        assert not slow.is_alive() and not other.is_alive()
        assert sorted(synced) == ["another-run", "slow-sync"], "each line is synced to disk, once"
        lines = _day_file().read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2, lines
        aggregates = ledger.aggregates(UKEY)
        # Both lines whole: the other run's reserve, and the slow run's line.
        assert (aggregates["runs"], aggregates["usage"]["inputTokens"]) == {
            "reserve": (2, 0), "settle": (1, 3), "usage": (1, 2)}[append]


class TestCachedInput:
    """A caching provider reports cache reads and writes; they are kept and
    summed when reported, and they are part of inputTokens, never added to it."""

    def test_they_are_kept_and_summed_when_reported(self, tmp_curio):
        first = ledger.reserve("43")
        ledger.settle("43", first, usage={
            "inputTokens": 100, "outputTokens": 5, "cacheReadTokens": 80, "cacheWriteTokens": 0,
        })
        second = ledger.reserve("43")
        ledger.settle("43", second, usage={
            "inputTokens": 100, "outputTokens": 5, "cacheReadTokens": 0, "cacheWriteTokens": 90,
        })
        ledger.record_housekeeping_usage("43", {"inputTokens": 10, "outputTokens": 1})
        assert ledger.aggregates("43")["usage"] == {
            "inputTokens": 210, "outputTokens": 11, "cacheReadTokens": 80, "cacheWriteTokens": 90,
        }

    def test_a_provider_that_reports_none_adds_none(self, tmp_curio):
        run = ledger.reserve("44")
        ledger.settle("44", run, usage={"inputTokens": 7, "outputTokens": 3})
        assert ledger.aggregates("44")["usage"] == {"inputTokens": 7, "outputTokens": 3}
