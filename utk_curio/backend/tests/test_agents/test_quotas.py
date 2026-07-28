"""Tests for the basic quota admission counters (memo dev/22, slice 4)."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents import quotas
from utk_curio.backend.app.agents.quotas import QuotaExceeded, check_and_count

UKEY = "42"


class TestAdmission:
    def test_counts_up_to_limit_then_denies(self, tmp_curio):
        assert check_and_count(UKEY, limit=2) == 1
        assert check_and_count(UKEY, limit=2) == 2
        with pytest.raises(QuotaExceeded) as exc:
            check_and_count(UKEY, limit=2)
        assert "2/day" in str(exc.value)
        assert exc.value.reset_at.endswith("+00:00")

    def test_denial_mutates_nothing(self, tmp_curio):
        check_and_count(UKEY, limit=1)
        before = quotas._quota_path(UKEY).read_text(encoding="utf-8")
        with pytest.raises(QuotaExceeded):
            check_and_count(UKEY, limit=1)
        assert quotas._quota_path(UKEY).read_text(encoding="utf-8") == before

    def test_stale_window_resets(self, tmp_curio):
        check_and_count(UKEY, limit=1)
        path = quotas._quota_path(UKEY)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["window"] = "2001-01-01"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert check_and_count(UKEY, limit=1) == 1  # fresh window admits again

    def test_corrupt_file_reads_as_fresh_window(self, tmp_curio):
        path = quotas._quota_path(UKEY)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        assert check_and_count(UKEY, limit=1) == 1

    def test_accounts_are_isolated(self, tmp_curio):
        check_and_count("42", limit=1)
        assert check_and_count("43", limit=1) == 1


class TestLimitConfig:
    def test_env_override_and_fallbacks(self, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "7")
        assert quotas.runs_per_day_limit() == 7
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "not-a-number")
        assert quotas.runs_per_day_limit() == quotas.DEFAULT_RUNS_PER_DAY
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "0")
        assert quotas.runs_per_day_limit() == quotas.DEFAULT_RUNS_PER_DAY
        monkeypatch.delenv("CURIO_AGENT_RUNS_PER_DAY")
        assert quotas.runs_per_day_limit() == quotas.DEFAULT_RUNS_PER_DAY


class TestAdmit:
    """Policy-aware admission (memo dev/24): template limits + budget gate."""

    def test_template_limit_denies_independently(self, tmp_curio):
        from utk_curio.backend.app.agents.quotas import admit

        assert admit(UKEY, account_limit=10, template_key="p1/a@1", template_limit=1) == 1
        with pytest.raises(QuotaExceeded) as exc:
            admit(UKEY, account_limit=10, template_key="p1/a@1", template_limit=1)
        assert exc.value.reason == "quota"
        assert "project run limit" in str(exc.value)
        # Another template in the same account still admits.
        assert admit(UKEY, account_limit=10, template_key="p1/b@1", template_limit=1) == 2

    def test_budget_gate_uses_estimated_spend(self, tmp_curio):
        from utk_curio.backend.app.agents.quotas import admit

        # $0.30 budget, $0.10/run estimate → 3 runs admitted, 4th denied.
        for _ in range(3):
            admit(UKEY, account_limit=10, daily_budget_usd=0.30, estimated_cost_per_run_usd=0.10)
        with pytest.raises(QuotaExceeded) as exc:
            admit(UKEY, account_limit=10, daily_budget_usd=0.30, estimated_cost_per_run_usd=0.10)
        assert exc.value.reason == "budget"
        assert "budget" in str(exc.value)

    def test_budget_inactive_when_half_configured(self, tmp_curio):
        from utk_curio.backend.app.agents.quotas import admit

        for _ in range(5):
            admit(UKEY, account_limit=10, daily_budget_usd=0.01)  # no estimate → inactive
        assert quotas.runs_used_today(UKEY) == 5

    def test_denial_precedence_and_no_mutation(self, tmp_curio):
        from utk_curio.backend.app.agents.quotas import admit

        admit(UKEY, account_limit=1)
        before = quotas._quota_path(UKEY).read_text(encoding="utf-8")
        with pytest.raises(QuotaExceeded) as exc:
            admit(UKEY, account_limit=1, daily_budget_usd=0.01, estimated_cost_per_run_usd=1.0)
        assert exc.value.reason == "quota"  # account limit checked first
        assert quotas._quota_path(UKEY).read_text(encoding="utf-8") == before


class TestUsageCounters:
    """Daily Actual-token counters in the quota window (memo dev/37).
    Advisory like the run counters; ledgers replace them in T3."""

    def test_record_and_read_accumulates(self, tmp_curio):
        assert quotas.usage_today(UKEY) == {"inputTokens": 0, "outputTokens": 0}
        quotas.record_usage(UKEY, 10, 20)
        quotas.record_usage(UKEY, 1, 2)
        assert quotas.usage_today(UKEY) == {"inputTokens": 11, "outputTokens": 22}

    def test_non_integer_usage_is_ignored(self, tmp_curio):
        quotas.record_usage(UKEY, None, 5)
        quotas.record_usage(UKEY, "10", 5)
        assert quotas.usage_today(UKEY) == {"inputTokens": 0, "outputTokens": 0}

    def test_usage_resets_with_the_window(self, tmp_curio):
        quotas.record_usage(UKEY, 10, 20)
        path = quotas._quota_path(UKEY)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["window"] = "2001-01-01"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert quotas.usage_today(UKEY) == {"inputTokens": 0, "outputTokens": 0}

    def test_usage_survives_an_admit_write(self, tmp_curio):
        # admit() rewrites the window file; the usage counters must ride along.
        quotas.record_usage(UKEY, 10, 20)
        check_and_count(UKEY, limit=5)
        assert quotas.usage_today(UKEY) == {"inputTokens": 10, "outputTokens": 20}

    def test_window_predating_usage_capture_reads_zero(self, tmp_curio):
        # An old window without the "usage" key (or with a malformed one)
        # reads as zeros — no migrations (memo dev/37).
        check_and_count(UKEY, limit=5)
        assert quotas.usage_today(UKEY) == {"inputTokens": 0, "outputTokens": 0}
        path = quotas._quota_path(UKEY)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["usage"] = "junk"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert quotas.usage_today(UKEY) == {"inputTokens": 0, "outputTokens": 0}
        quotas.record_usage(UKEY, 3, 4)
        assert quotas.usage_today(UKEY) == {"inputTokens": 3, "outputTokens": 4}
