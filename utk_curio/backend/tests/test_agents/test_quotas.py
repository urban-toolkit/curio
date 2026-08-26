"""Tests for the quota facade over the ledger (memos dev/22/dev/40).

Admission semantics (limits, budget ladder, fail-closed, races) live with the
ledger in ``test_ledger.py`` — this file covers what remains here: the
env-derived deployment limit and the ledger-backed today-reads the settings
surfaces consume."""

from __future__ import annotations

from utk_curio.backend.app.agents import ledger, quotas

UKEY = "42"


class TestLimitConfig:
    def test_no_cap_is_shipped(self, monkeypatch):
        # Curio used to default to 200 runs/day, which meant an unconfigured
        # install still enforced a number Curio picked. The operator pays for
        # the tokens, so the ceiling is theirs to set.
        monkeypatch.delenv("CURIO_AGENT_RUNS_PER_DAY", raising=False)
        assert quotas.runs_per_day_limit() is None

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "7")
        assert quotas.runs_per_day_limit() == 7

    def test_invalid_and_nonpositive_read_as_unset(self, monkeypatch):
        # Unset rather than a substitute of our own: a typo must not quietly
        # impose a limit nobody asked for.
        for bad in ("abc", "0", "-3"):
            monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", bad)
            assert quotas.runs_per_day_limit() is None

    def test_no_ceiling_admits_without_counting_against_one(self, tmp_curio):
        # The ledger reads None the way it already reads an unset template or
        # attachment limit: record the run, gate nothing.
        for _ in range(3):
            ledger.reserve(UKEY, account_limit=None)
        assert quotas.runs_used_today(UKEY) == 3


class TestLedgerBackedReads:
    def test_zero_for_a_fresh_account(self, tmp_curio):
        assert quotas.runs_used_today(UKEY) == 0
        assert quotas.usage_today(UKEY) == {"inputTokens": 0, "outputTokens": 0}

    def test_reads_follow_the_ledger(self, tmp_curio):
        reservation = ledger.reserve(UKEY, account_limit=5)
        assert quotas.runs_used_today(UKEY) == 1
        ledger.settle(UKEY, reservation, usage={"inputTokens": 10, "outputTokens": 20})
        ledger.record_housekeeping_usage(UKEY, {"inputTokens": 5, "outputTokens": 3})
        assert quotas.usage_today(UKEY) == {"inputTokens": 15, "outputTokens": 23}

    def test_quota_exceeded_is_the_ledger_class(self):
        # The re-export keeps the route contract: one exception class, one 429.
        assert quotas.QuotaExceeded is ledger.QuotaExceeded

    def test_accounts_are_isolated(self, tmp_curio):
        ledger.reserve("42", account_limit=1)
        assert quotas.runs_used_today("43") == 0
