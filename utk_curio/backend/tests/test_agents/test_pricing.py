"""Tests for the deployment-owned price table (memo dev/40, DEC-044)."""

from __future__ import annotations

import json

from utk_curio.backend.app.agents import ledger, pricing


def _write_table(tmp_path, monkeypatch, table: object) -> None:
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setenv(pricing.PRICE_TABLE_ENV, str(path))


class TestPriceSnapshot:
    def test_table_is_empty_by_default(self, tmp_path, monkeypatch):
        # No fabricated prices: the default deployment (self-hosted aiconn)
        # has no per-token USD price (memo 11 honesty rule).
        monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
        monkeypatch.delenv(pricing.PRICE_TABLE_ENV, raising=False)
        assert pricing.price_snapshot("openai_compatible", "gemma4") is None

    def test_configured_price_resolves_a_snapshot(self, tmp_path, monkeypatch):
        _write_table(
            tmp_path,
            monkeypatch,
            {
                "anthropic/claude-sonnet-5": {
                    "inputUsdPerMtok": 3,
                    "outputUsdPerMtok": 15.0,
                    "effectiveDate": "2026-07-01",
                }
            },
        )
        snap = pricing.price_snapshot("anthropic", "claude-sonnet-5")
        assert snap == {
            "inputUsdPerMtok": 3.0,
            "outputUsdPerMtok": 15.0,
            "effectiveDate": "2026-07-01",
            "currency": "USD",
        }

    def test_unlisted_model_is_none(self, tmp_path, monkeypatch):
        _write_table(
            tmp_path,
            monkeypatch,
            {"anthropic/claude-sonnet-5": {"inputUsdPerMtok": 3, "outputUsdPerMtok": 15}},
        )
        assert pricing.price_snapshot("anthropic", "other-model") is None

    def test_effective_date_is_optional(self, tmp_path, monkeypatch):
        _write_table(
            tmp_path,
            monkeypatch,
            {"p/m": {"inputUsdPerMtok": 1, "outputUsdPerMtok": 2}},
        )
        assert pricing.price_snapshot("p", "m")["effectiveDate"] is None

    def test_malformed_entries_and_files_read_as_absent(self, tmp_path, monkeypatch):
        for table in (
            {"p/m": {"inputUsdPerMtok": "3", "outputUsdPerMtok": 15}},  # non-numeric
            {"p/m": {"inputUsdPerMtok": -1, "outputUsdPerMtok": 15}},  # negative
            {"p/m": "not an object"},
            ["not", "a", "dict"],
        ):
            _write_table(tmp_path, monkeypatch, table)
            assert pricing.price_snapshot("p", "m") is None
        path = tmp_path / "prices.json"
        path.write_text("{corrupt", encoding="utf-8")
        assert pricing.price_snapshot("p", "m") is None

    def test_missing_file_reads_as_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv(pricing.PRICE_TABLE_ENV, str(tmp_path / "ghost.json"))
        assert pricing.price_snapshot("p", "m") is None


class TestSettlementMath:
    def test_snapshot_prices_a_settlement(self, tmp_curio, tmp_path, monkeypatch):
        _write_table(
            tmp_path,
            monkeypatch,
            {"anthropic/claude-sonnet-5": {"inputUsdPerMtok": 3, "outputUsdPerMtok": 15}},
        )
        snap = pricing.price_snapshot("anthropic", "claude-sonnet-5")
        reservation = ledger.reserve("42", account_limit=5, price=snap)
        entry = ledger.settle(
            "42", reservation, usage={"inputTokens": 1_000_000, "outputTokens": 100_000}
        )
        assert entry["costUsd"] == 4.5  # $3 + $1.50, rounded to 6 places

    def test_snapshot_is_pinned_against_mid_day_table_edits(self, tmp_curio, tmp_path, monkeypatch):
        _write_table(tmp_path, monkeypatch, {"p/m": {"inputUsdPerMtok": 3, "outputUsdPerMtok": 15}})
        reservation = ledger.reserve("42", account_limit=5, price=pricing.price_snapshot("p", "m"))
        # The operator retunes the table before the run settles.
        _write_table(tmp_path, monkeypatch, {"p/m": {"inputUsdPerMtok": 300, "outputUsdPerMtok": 1500}})
        entry = ledger.settle(
            "42", reservation, usage={"inputTokens": 1_000_000, "outputTokens": 0}
        )
        assert entry["costUsd"] == 3.0  # the RESERVATION's snapshot, not today's table
