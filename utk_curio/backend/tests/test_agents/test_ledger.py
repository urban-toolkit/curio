"""Tests for the append-only usage ledger (memo dev/40, DEC-044)."""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone

import pytest

from utk_curio.backend.app.agents import ledger, storage
from utk_curio.backend.app.agents.ledger import QuotaExceeded

UKEY = "42"
PRICE = {
    "inputUsdPerMtok": 3.0,
    "outputUsdPerMtok": 15.0,
    "effectiveDate": "2026-07-01",
    "currency": "USD",
}


def _day_file(day=None):
    return ledger._day_path(UKEY, day or ledger._today())


class TestReserveSettle:
    def test_reserve_settle_roundtrip_and_aggregates(self, tmp_curio):
        reservation = ledger.reserve(
            UKEY, account_limit=5, template_key="p1/a@1", price=PRICE
        )
        entry = ledger.settle(
            UKEY, reservation, usage={"inputTokens": 1000, "outputTokens": 2000}
        )
        # 1000 × $3/M + 2000 × $15/M = 0.003 + 0.03
        assert entry["costUsd"] == pytest.approx(0.033)
        agg = ledger.aggregates(UKEY)
        assert agg["runs"] == 1
        assert agg["byTemplate"] == {"p1/a@1": 1}
        assert agg["usage"] == {"inputTokens": 1000, "outputTokens": 2000}
        assert agg["actualSpendUsd"] == pytest.approx(0.033)
        assert agg["heldUsd"] == 0
        assert agg["settledEstimatedUsd"] == 0

    def test_settle_without_price_or_usage_is_null_cost(self, tmp_curio):
        r1 = ledger.reserve(UKEY, account_limit=5, price=None)
        assert ledger.settle(UKEY, r1, usage={"inputTokens": 1, "outputTokens": 2})["costUsd"] is None
        r2 = ledger.reserve(UKEY, account_limit=5, price=PRICE)
        assert ledger.settle(UKEY, r2, usage=None)["costUsd"] is None

    def test_double_settle_is_idempotent(self, tmp_curio):
        reservation = ledger.reserve(UKEY, account_limit=5, price=PRICE)
        first = ledger.settle(UKEY, reservation, usage={"inputTokens": 1000, "outputTokens": 0})
        second = ledger.settle(UKEY, reservation, usage={"inputTokens": 999999, "outputTokens": 0})
        assert second == first  # first-write-wins
        assert ledger.aggregates(UKEY)["usage"]["inputTokens"] == 1000

    def test_settle_without_reserve_still_counts(self, tmp_curio):
        entry = ledger.settle(
            UKEY,
            {"reservationId": "ghost", "day": ledger._today(), "price": None},
            usage={"inputTokens": 5, "outputTokens": 5},
        )
        assert entry["costUsd"] is None
        assert ledger.aggregates(UKEY)["usage"]["inputTokens"] == 5

    def test_settle_appends_never_rewrites(self, tmp_curio):
        reservation = ledger.reserve(UKEY, account_limit=5)
        before = _day_file().read_text(encoding="utf-8")
        ledger.settle(UKEY, reservation, usage={"inputTokens": 1, "outputTokens": 1})
        after = _day_file().read_text(encoding="utf-8")
        assert after.startswith(before)  # append-only: prior bytes untouched

    def test_corrupt_line_is_skipped(self, tmp_curio):
        ledger.reserve(UKEY, account_limit=5)
        with open(_day_file(), "a", encoding="utf-8") as handle:
            handle.write("{torn line\n")
        ledger.reserve(UKEY, account_limit=5)
        assert ledger.aggregates(UKEY)["runs"] == 2

    def test_housekeeping_usage_counts_without_a_run(self, tmp_curio):
        ledger.record_housekeeping_usage(
            UKEY, {"inputTokens": 5, "outputTokens": 3}, price=PRICE, note="title-call"
        )
        agg = ledger.aggregates(UKEY)
        assert agg["runs"] == 0
        assert agg["usage"] == {"inputTokens": 5, "outputTokens": 3}
        assert agg["actualSpendUsd"] == pytest.approx(5 * 3.0 / 1e6 + 3 * 15.0 / 1e6)


class TestLimits:
    def test_account_limit_admits_exactly_n(self, tmp_curio):
        for _ in range(2):
            ledger.reserve(UKEY, account_limit=2)
        with pytest.raises(QuotaExceeded) as exc:
            ledger.reserve(UKEY, account_limit=2)
        assert exc.value.reason == "quota"
        assert "2/day" in str(exc.value)
        assert exc.value.reset_at.endswith("+00:00")

    def test_template_limit(self, tmp_curio):
        ledger.reserve(UKEY, account_limit=10, template_key="p1/a@1", template_limit=1)
        with pytest.raises(QuotaExceeded):
            ledger.reserve(UKEY, account_limit=10, template_key="p1/a@1", template_limit=1)
        # Another template still admits.
        ledger.reserve(UKEY, account_limit=10, template_key="p1/b@1", template_limit=1)

    def test_denial_appends_nothing(self, tmp_curio):
        ledger.reserve(UKEY, account_limit=1)
        before = _day_file().read_text(encoding="utf-8")
        with pytest.raises(QuotaExceeded):
            ledger.reserve(UKEY, account_limit=1)
        assert _day_file().read_text(encoding="utf-8") == before


class TestBudgetLadder:
    def test_estimate_holds_gate_the_budget(self, tmp_curio):
        # $0.30 budget, $0.10/run estimate → 3 admitted, 4th denied — the
        # pre-ledger behavior, now atomic.
        for _ in range(3):
            ledger.reserve(
                UKEY, account_limit=10, daily_budget_usd=0.30, estimated_cost_per_run_usd=0.10
            )
        with pytest.raises(QuotaExceeded) as exc:
            ledger.reserve(
                UKEY, account_limit=10, daily_budget_usd=0.30, estimated_cost_per_run_usd=0.10
            )
        assert exc.value.reason == "budget"
        assert "budget" in str(exc.value)

    def test_priced_settlement_replaces_the_hold(self, tmp_curio):
        # A run that actually cost less than its estimate frees budget room.
        r = ledger.reserve(
            UKEY,
            account_limit=10,
            daily_budget_usd=0.30,
            estimated_cost_per_run_usd=0.25,
            price=PRICE,
        )
        ledger.settle(UKEY, r, usage={"inputTokens": 1000, "outputTokens": 1000})  # $0.018
        # actual 0.018 + this hold 0.25 = 0.268 ≤ 0.30 → admitted.
        ledger.reserve(
            UKEY,
            account_limit=10,
            daily_budget_usd=0.30,
            estimated_cost_per_run_usd=0.25,
            price=PRICE,
        )

    def test_unpriced_settlement_keeps_the_estimate_charged(self, tmp_curio):
        # Budget accounting never silently drops a run it admitted.
        r = ledger.reserve(
            UKEY, account_limit=10, daily_budget_usd=0.30, estimated_cost_per_run_usd=0.20
        )
        ledger.settle(UKEY, r, usage=None)
        agg = ledger.aggregates(UKEY)
        assert agg["settledEstimatedUsd"] == pytest.approx(0.20)
        with pytest.raises(QuotaExceeded):
            ledger.reserve(
                UKEY, account_limit=10, daily_budget_usd=0.30, estimated_cost_per_run_usd=0.20
            )

    def test_fail_closed_budget_without_estimate_or_price(self, tmp_curio):
        # REQ-COST-001 — the tranche's one deliberate behavior change: a hard
        # monetary cap with an unknowable per-run cost denies the run.
        with pytest.raises(QuotaExceeded) as exc:
            ledger.reserve(UKEY, account_limit=10, daily_budget_usd=1.0)
        assert exc.value.reason == "budget"
        assert "no cost estimate or price" in str(exc.value)

    def test_budget_with_price_but_no_estimate_admits_on_actuals(self, tmp_curio):
        # A known price makes the estimate optional: holds are 0 and settled
        # actuals gate future runs.
        r1 = ledger.reserve(UKEY, account_limit=10, daily_budget_usd=0.05, price=PRICE)
        ledger.settle(UKEY, r1, usage={"inputTokens": 10_000, "outputTokens": 1_000})  # $0.045
        r2 = ledger.reserve(UKEY, account_limit=10, daily_budget_usd=0.05, price=PRICE)
        ledger.settle(UKEY, r2, usage={"inputTokens": 10_000, "outputTokens": 1_000})  # $0.045
        assert ledger.aggregates(UKEY)["actualSpendUsd"] == pytest.approx(0.09)
        with pytest.raises(QuotaExceeded) as exc:
            ledger.reserve(UKEY, account_limit=10, daily_budget_usd=0.05, price=PRICE)
        assert exc.value.reason == "budget"

    def test_no_budget_means_no_monetary_gate(self, tmp_curio):
        for _ in range(5):
            ledger.reserve(UKEY, account_limit=10)  # no budget, no estimate: fine
        assert ledger.aggregates(UKEY)["runs"] == 5


class TestWindowing:
    def test_settle_lands_in_the_reservation_day(self, tmp_curio, monkeypatch):
        before_midnight = datetime(2026, 7, 28, 23, 59, 59, tzinfo=timezone.utc)
        after_midnight = datetime(2026, 7, 29, 0, 0, 5, tzinfo=timezone.utc)
        monkeypatch.setattr(ledger, "_now", lambda: before_midnight)
        reservation = ledger.reserve(UKEY, account_limit=5, price=PRICE)
        assert reservation["day"] == "2026-07-28"
        monkeypatch.setattr(ledger, "_now", lambda: after_midnight)
        ledger.settle(UKEY, reservation, usage={"inputTokens": 1000, "outputTokens": 0})
        assert ledger.aggregates(UKEY, "2026-07-28")["usage"]["inputTokens"] == 1000
        assert ledger.aggregates(UKEY, "2026-07-29")["runs"] == 0

    def test_windows_are_independent(self, tmp_curio, monkeypatch):
        monkeypatch.setattr(
            ledger, "_now", lambda: datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
        )
        ledger.reserve(UKEY, account_limit=1)
        monkeypatch.setattr(
            ledger, "_now", lambda: datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        )
        ledger.reserve(UKEY, account_limit=1)  # fresh window admits again


class TestLegacySeed:
    def _write_legacy(self, window, runs=190, usage=None):
        path = storage.user_agents_dir(UKEY) / "quota.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "window": window,
                    "runs": runs,
                    "byTemplate": {"p1/a@1": 3},
                    "usage": usage or {"inputTokens": 10, "outputTokens": 20},
                }
            ),
            encoding="utf-8",
        )

    def test_same_day_counts_carry_forward(self, tmp_curio):
        self._write_legacy(ledger._today())
        # Visible even before the first reserve materializes the seed…
        assert ledger.aggregates(UKEY)["runs"] == 190
        # …and a reserve at 190/200 admits exactly the remaining headroom.
        ledger.reserve(UKEY, account_limit=200)
        agg = ledger.aggregates(UKEY)
        assert agg["runs"] == 191
        assert agg["byTemplate"]["p1/a@1"] == 3
        assert agg["usage"] == {"inputTokens": 10, "outputTokens": 20}

    def test_exhausted_legacy_quota_stays_exhausted(self, tmp_curio):
        self._write_legacy(ledger._today(), runs=200)
        with pytest.raises(QuotaExceeded):
            ledger.reserve(UKEY, account_limit=200)

    def test_cross_day_legacy_window_seeds_nothing(self, tmp_curio):
        self._write_legacy("2001-01-01")
        ledger.reserve(UKEY, account_limit=200)
        assert ledger.aggregates(UKEY)["runs"] == 1

    def test_seed_is_written_once(self, tmp_curio):
        self._write_legacy(ledger._today(), runs=1)
        ledger.reserve(UKEY, account_limit=200)
        ledger.reserve(UKEY, account_limit=200)
        entries = ledger._read_entries(UKEY, ledger._today())
        assert sum(1 for e in entries if e.get("kind") == "seed") == 1
        assert ledger.aggregates(UKEY)["runs"] == 3


class TestConcurrency:
    def test_threads_cannot_over_admit_the_last_slots(self, tmp_curio):
        LIMIT = 5
        outcomes: list[bool] = []
        outcomes_lock = threading.Lock()
        barrier = threading.Barrier(16)

        def attempt():
            barrier.wait()
            try:
                ledger.reserve(UKEY, account_limit=LIMIT)
                admitted = True
            except QuotaExceeded:
                admitted = False
            with outcomes_lock:
                outcomes.append(admitted)

        threads = [threading.Thread(target=attempt) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(outcomes) == LIMIT  # exactly N admits, never over
        assert ledger.aggregates(UKEY)["runs"] == LIMIT

    @pytest.mark.skipif(sys.platform == "win32", reason="fork/flock are POSIX-only")
    def test_processes_cannot_double_book_the_last_slot(self, tmp_curio):
        # Fill all but one slot, then two processes race for it: flock
        # guarantees exactly one admit regardless of scheduling.
        LIMIT = 3
        for _ in range(LIMIT - 1):
            ledger.reserve(UKEY, account_limit=LIMIT)
        pids = []
        for _ in range(2):
            pid = os.fork()
            if pid == 0:  # child
                try:
                    ledger.reserve(UKEY, account_limit=LIMIT)
                    os._exit(0)  # admitted
                except QuotaExceeded:
                    os._exit(3)  # denied
                except Exception:
                    os._exit(9)
            pids.append(pid)
        codes = [os.waitpid(pid, 0)[1] >> 8 for pid in pids]
        assert sorted(codes) == [0, 3]  # exactly one admit, one clean denial
        assert ledger.aggregates(UKEY)["runs"] == LIMIT
