"""Tests for the read-only views over the local usage ledger.

The name is historical and so was most of this file: it covered the
``CURIO_AGENT_RUNS_PER_DAY`` deployment ceiling and the ``QuotaExceeded``
re-export that backed a 429. Curio caps nothing now, so neither exists. What is
left are the two aggregate reads, kept as a facade so callers do not reach into
the ledger's entry format.
"""

from __future__ import annotations

from utk_curio.backend.app.agents import ledger, quotas

UKEY = "42"


class TestNoQuotaSurvives:
    def test_the_module_exposes_no_limit_and_no_denial(self):
        # A guard, not a tautology: re-adding either of these should be a
        # decision made here, not a symbol that quietly reappears.
        assert not hasattr(quotas, "runs_per_day_limit")
        assert not hasattr(quotas, "QuotaExceeded")
        assert not hasattr(ledger, "QuotaExceeded")

    def test_runs_are_recorded_without_a_ceiling(self, tmp_curio):
        for _ in range(3):
            ledger.reserve(UKEY)
        assert quotas.runs_used_today(UKEY) == 3


class TestLedgerBackedReads:
    def test_zero_for_a_fresh_account(self, tmp_curio):
        assert quotas.runs_used_today(UKEY) == 0
        assert quotas.usage_today(UKEY) == {"inputTokens": 0, "outputTokens": 0}

    def test_reads_follow_the_ledger(self, tmp_curio):
        reservation = ledger.reserve(UKEY)
        assert quotas.runs_used_today(UKEY) == 1
        ledger.settle(UKEY, reservation, usage={"inputTokens": 10, "outputTokens": 20})
        ledger.record_housekeeping_usage(UKEY, {"inputTokens": 5, "outputTokens": 3})
        assert quotas.usage_today(UKEY) == {"inputTokens": 15, "outputTokens": 23}

    def test_accounts_are_isolated(self, tmp_curio):
        ledger.reserve("42")
        assert quotas.runs_used_today("43") == 0
