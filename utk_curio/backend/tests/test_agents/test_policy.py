"""Tests for the effective-policy resolver, tighten-only validation, and the
account settings record.

Every case here used to be written against ``quotas.runsPerDay`` or the
``cost`` section, because those were the interesting fields. Both are gone with
the metering they served, so the same resolver contracts - deployment default,
downward-only resolution, clamp-at-read, tighten-only writes, unknown-field
rejection - are now asserted against ``resources.maxOutputTokens``, the one
field left. It survives because it is not a quota: it is passed to the provider
as ``max_tokens`` on every completion, shaping one reply rather than rationing a
day's worth.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import account_settings, policy
from utk_curio.backend.app.agents.policy import (
    DEPLOYMENT_MAX_OUTPUT_TOKENS,
    PolicyValidationError,
    StaleRevisionError,
    effective,
    validate_patch,
)

UKEY = "42"
TOK = "maxOutputTokens"


class TestEffective:
    def test_deployment_default_when_nothing_set(self):
        eff = effective({}, {})
        assert eff["resources"][TOK] == {
            "value": DEPLOYMENT_MAX_OUTPUT_TOKENS,
            "source": "deployment",
        }

    def test_nothing_is_metered_or_priced(self):
        # The sections that configured run caps and spend are not merely empty:
        # they do not exist, so a stored value under either cannot resolve.
        eff = effective({}, {})
        assert set(eff) == {"resources"}
        assert "quotas" not in eff and "cost" not in eff

    def test_account_and_project_sources(self):
        eff = effective({"resources": {TOK: 2048}}, {"resources": {TOK: 512}})
        assert eff["resources"][TOK] == {"value": 512, "source": "project"}
        eff = effective({"resources": {TOK: 2048}}, {})
        assert eff["resources"][TOK] == {"value": 2048, "source": "account"}

    def test_stale_looser_values_clamp_at_read(self):
        # A project value written before the account tightened cannot leak through.
        eff = effective({"resources": {TOK: 512}}, {"resources": {TOK: 2048}})
        assert eff["resources"][TOK]["value"] == 512
        assert eff["resources"][TOK]["source"] == "project"
        # And an account value above the deployment ceiling clamps too.
        eff = effective({"resources": {TOK: 999999}})
        assert eff["resources"][TOK]["value"] == DEPLOYMENT_MAX_OUTPUT_TOKENS


class TestValidatePatch:
    def _dep(self):
        return effective({})  # deployment view = parent of the account scope

    def test_accepts_and_cleans_known_fields(self):
        cleaned = validate_patch({"resources": {TOK: 512.0}}, "account", self._dep())
        assert cleaned == {"resources": {TOK: 512}}

    def test_rejects_unknown_and_bad_types(self):
        parent = self._dep()
        with pytest.raises(PolicyValidationError, match="unknown settings section"):
            validate_patch({"nope": {}}, "account", parent)
        # The retired sections are now unknown sections, which is the point:
        # a client still sending them gets told, rather than silently ignored.
        with pytest.raises(PolicyValidationError, match="unknown settings section"):
            validate_patch({"quotas": {"runsPerDay": 10}}, "account", parent)
        with pytest.raises(PolicyValidationError, match="unknown settings section"):
            validate_patch({"cost": {"dailyBudgetUsd": 5}}, "account", parent)
        with pytest.raises(PolicyValidationError, match="unknown setting"):
            validate_patch({"resources": {"nope": 1}}, "account", parent)
        with pytest.raises(PolicyValidationError, match="must be a number"):
            validate_patch({"resources": {TOK: "512"}}, "account", parent)
        with pytest.raises(PolicyValidationError, match="integer"):
            validate_patch({"resources": {TOK: 2.5}}, "account", parent)
        with pytest.raises(PolicyValidationError, match="positive"):
            validate_patch({"resources": {TOK: 0}}, "account", parent)

    def test_tighten_only_against_parent(self):
        with pytest.raises(PolicyValidationError, match="may not exceed the inherited limit"):
            validate_patch({"resources": {TOK: 999999}}, "account", self._dep())
        acct_eff = effective({"resources": {TOK: 512}})
        with pytest.raises(PolicyValidationError, match="inherited limit \\(512\\)"):
            validate_patch({"resources": {TOK: 1024}}, "project", acct_eff)
        assert validate_patch({"resources": {TOK: 256}}, "project", acct_eff)

    def test_null_clears_an_override(self):
        assert validate_patch({"resources": {TOK: None}}, "account", self._dep()) == {}


class TestAccountSettingsRecord:
    def test_missing_and_corrupt_read_empty(self, tmp_curio):
        assert account_settings.read_record(UKEY) == {"revision": 1, "settings": {}}
        p = account_settings._path(UKEY)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{bad", encoding="utf-8")
        assert account_settings.read_record(UKEY) == {"revision": 1, "settings": {}}

    def test_write_bumps_revision_and_round_trips(self, tmp_curio):
        rec = account_settings.write_settings(UKEY, {"resources": {TOK: 512}}, 1)
        assert rec == {"revision": 2, "settings": {"resources": {TOK: 512}}}
        assert account_settings.read_record(UKEY) == rec

    def test_stale_revision_raises(self, tmp_curio):
        account_settings.write_settings(UKEY, {}, 1)
        with pytest.raises(StaleRevisionError):
            account_settings.write_settings(UKEY, {}, 1)


class TestAttachmentScope:
    """The third, attached-instance layer: resolves like the second, downward
    only, and validates against the project-effective parent."""

    def test_attachment_layer_wins_only_downward(self):
        eff = policy.effective(
            {"resources": {TOK: 2048}},
            {"resources": {TOK: 1024}},
            {"resources": {TOK: 256}},
        )
        assert eff["resources"][TOK] == {"value": 256, "source": "attachment"}
        # A looser stored attachment value is clamped at read, never leaks.
        eff = policy.effective(
            {"resources": {TOK: 2048}},
            {"resources": {TOK: 1024}},
            {"resources": {TOK: 999999}},
        )
        assert eff["resources"][TOK] == {"value": 1024, "source": "attachment"}

    def test_absent_attachment_settings_change_nothing(self):
        two = policy.effective({"resources": {TOK: 2048}}, {"resources": {TOK: 1024}})
        three = policy.effective(
            {"resources": {TOK: 2048}}, {"resources": {TOK: 1024}}, None
        )
        assert two == three

    def test_validate_patch_attachment_scope_tighten_only(self):
        parent = policy.effective({"resources": {TOK: 1024}})
        cleaned = policy.validate_patch({"resources": {TOK: 256}}, "attachment", parent)
        assert cleaned == {"resources": {TOK: 256}}
        with pytest.raises(policy.PolicyValidationError, match="may not exceed"):
            policy.validate_patch({"resources": {TOK: 2048}}, "attachment", parent)
