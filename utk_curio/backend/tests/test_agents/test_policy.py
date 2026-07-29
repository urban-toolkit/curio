"""Tests for the effective-policy resolver, tighten-only validation (memo dev/24),
and the account settings record."""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import account_settings, policy
from utk_curio.backend.app.agents.policy import (
    PolicyValidationError,
    StaleRevisionError,
    effective,
    validate_patch,
)

UKEY = "42"


class TestEffective:
    def test_deployment_defaults_when_nothing_set(self, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "100")
        eff = effective({}, {})
        assert eff["quotas"]["runsPerDay"] == {"value": 100, "source": "deployment"}
        assert eff["resources"]["maxOutputTokens"] == {"value": 4096, "source": "deployment"}
        assert eff["cost"]["dailyBudgetUsd"] == {"value": None, "source": None}
        assert eff["cost"]["configured"] is False

    def test_account_and_project_sources(self, monkeypatch):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "100")
        acct = {"quotas": {"runsPerDay": 50}, "cost": {"dailyBudgetUsd": 2.5, "estimatedCostPerRunUsd": 0.01}}
        proj = {"quotas": {"runsPerDay": 10}}
        eff = effective(acct, proj)
        assert eff["quotas"]["runsPerDay"] == {"value": 10, "source": "project"}
        assert eff["cost"]["dailyBudgetUsd"] == {"value": 2.5, "source": "account"}
        assert eff["cost"]["configured"] is True

    def test_stale_looser_values_clamp_at_read(self, monkeypatch):
        # A project value written before the account tightened cannot leak through.
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", "100")
        eff = effective({"quotas": {"runsPerDay": 20}}, {"quotas": {"runsPerDay": 80}})
        assert eff["quotas"]["runsPerDay"]["value"] == 20
        assert eff["quotas"]["runsPerDay"]["source"] == "project"
        # And an account value above the deployment ceiling clamps too.
        eff = effective({"quotas": {"runsPerDay": 500}})
        assert eff["quotas"]["runsPerDay"]["value"] == 100

    def test_budget_without_estimate_is_unconfigured(self):
        eff = effective({"cost": {"dailyBudgetUsd": 5}})
        assert eff["cost"]["configured"] is False


class TestValidatePatch:
    def _dep(self, monkeypatch, limit="100"):
        monkeypatch.setenv("CURIO_AGENT_RUNS_PER_DAY", limit)
        return effective({})  # deployment view = parent of the account scope

    def test_accepts_and_cleans_known_fields(self, monkeypatch):
        parent = self._dep(monkeypatch)
        cleaned = validate_patch(
            {"quotas": {"runsPerDay": 50.0}, "cost": {"dailyBudgetUsd": 2.5}},
            "account",
            parent,
        )
        assert cleaned == {"quotas": {"runsPerDay": 50}, "cost": {"dailyBudgetUsd": 2.5}}

    def test_rejects_unknown_and_bad_types(self, monkeypatch):
        parent = self._dep(monkeypatch)
        with pytest.raises(PolicyValidationError, match="unknown settings section"):
            validate_patch({"nope": {}}, "account", parent)
        with pytest.raises(PolicyValidationError, match="unknown setting"):
            validate_patch({"quotas": {"nope": 1}}, "account", parent)
        with pytest.raises(PolicyValidationError, match="must be a number"):
            validate_patch({"quotas": {"runsPerDay": "50"}}, "account", parent)
        with pytest.raises(PolicyValidationError, match="integer"):
            validate_patch({"quotas": {"runsPerDay": 2.5}}, "account", parent)
        with pytest.raises(PolicyValidationError, match="positive"):
            validate_patch({"cost": {"dailyBudgetUsd": 0}}, "account", parent)

    def test_tighten_only_against_parent(self, monkeypatch):
        parent = self._dep(monkeypatch)  # ceiling 100
        with pytest.raises(PolicyValidationError, match="may not exceed the inherited limit"):
            validate_patch({"quotas": {"runsPerDay": 200}}, "account", parent)
        acct_eff = effective({"quotas": {"runsPerDay": 30}})
        with pytest.raises(PolicyValidationError, match="inherited limit \\(30\\)"):
            validate_patch({"quotas": {"runsPerDay": 40}}, "project", acct_eff)
        # Unbounded fields (no parent value) accept any positive number.
        assert validate_patch({"cost": {"dailyBudgetUsd": 99}}, "project", acct_eff)

    def test_estimate_is_account_only(self, monkeypatch):
        parent = self._dep(monkeypatch)
        assert validate_patch({"cost": {"estimatedCostPerRunUsd": 0.02}}, "account", parent)
        with pytest.raises(PolicyValidationError, match="not editable at the project scope"):
            validate_patch({"cost": {"estimatedCostPerRunUsd": 0.02}}, "project", effective({}))

    def test_null_clears_an_override(self, monkeypatch):
        parent = self._dep(monkeypatch)
        assert validate_patch({"quotas": {"runsPerDay": None}}, "account", parent) == {}


class TestAccountSettingsRecord:
    def test_missing_and_corrupt_read_empty(self, tmp_curio):
        assert account_settings.read_record(UKEY) == {"revision": 1, "settings": {}}
        p = account_settings._path(UKEY)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{bad", encoding="utf-8")
        assert account_settings.read_record(UKEY) == {"revision": 1, "settings": {}}

    def test_write_bumps_revision_and_round_trips(self, tmp_curio):
        rec = account_settings.write_settings(UKEY, {"quotas": {"runsPerDay": 5}}, 1)
        assert rec == {"revision": 2, "settings": {"quotas": {"runsPerDay": 5}}}
        assert account_settings.read_record(UKEY) == rec

    def test_stale_revision_raises(self, tmp_curio):
        account_settings.write_settings(UKEY, {}, 1)
        with pytest.raises(StaleRevisionError):
            account_settings.write_settings(UKEY, {}, 1)


class TestAttachmentScope:
    """The third, attached-instance policy layer (memo dev/42): resolves like
    the second — downward only — and validates against the project-effective
    parent."""

    def test_attachment_layer_wins_only_downward(self):
        eff = policy.effective(
            {"quotas": {"runsPerDay": 50}},
            {"quotas": {"runsPerDay": 20}},
            {"quotas": {"runsPerDay": 5}},
        )
        assert eff["quotas"]["runsPerDay"] == {"value": 5, "source": "attachment"}
        # A looser stored attachment value is clamped at read, never leaks.
        eff = policy.effective(
            {"quotas": {"runsPerDay": 50}},
            {"quotas": {"runsPerDay": 20}},
            {"quotas": {"runsPerDay": 999}},
        )
        assert eff["quotas"]["runsPerDay"] == {"value": 20, "source": "attachment"}

    def test_absent_attachment_settings_change_nothing(self):
        two = policy.effective({"quotas": {"runsPerDay": 50}}, {"quotas": {"runsPerDay": 20}})
        three = policy.effective(
            {"quotas": {"runsPerDay": 50}}, {"quotas": {"runsPerDay": 20}}, None
        )
        assert two == three

    def test_attachment_budget_and_tokens_resolve(self):
        eff = policy.effective(
            {"cost": {"dailyBudgetUsd": 5.0}},
            None,
            {"cost": {"dailyBudgetUsd": 1.0}, "resources": {"maxOutputTokens": 256}},
        )
        assert eff["cost"]["dailyBudgetUsd"] == {"value": 1.0, "source": "attachment"}
        assert eff["resources"]["maxOutputTokens"] == {"value": 256, "source": "attachment"}

    def test_validate_patch_attachment_scope_tighten_only(self):
        parent = policy.effective({"quotas": {"runsPerDay": 20}})
        cleaned = policy.validate_patch({"quotas": {"runsPerDay": 5}}, "attachment", parent)
        assert cleaned == {"quotas": {"runsPerDay": 5}}
        with pytest.raises(policy.PolicyValidationError, match="may not exceed"):
            policy.validate_patch({"quotas": {"runsPerDay": 21}}, "attachment", parent)

    def test_estimate_is_not_editable_at_the_attachment_scope(self):
        parent = policy.effective({})
        with pytest.raises(policy.PolicyValidationError, match="not editable"):
            policy.validate_patch(
                {"cost": {"estimatedCostPerRunUsd": 0.1}}, "attachment", parent
            )
