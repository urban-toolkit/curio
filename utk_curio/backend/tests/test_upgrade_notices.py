"""An upgrade that silently changes behavior has to say so.

Three settings changed meaning in this release without breaking a boot, which
is exactly what makes them dangerous: the deployment starts cleanly and a
feature stops working, or starts re-spending a paid quota, with nothing in the
log connecting the two.
"""

from __future__ import annotations

import logging

import pytest

from utk_curio.backend.app import upgrade_notices


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in (
        "HUGGINGFACE_TOKEN",
        "STREETVISION_CACHE_DIR",
        "STREETVISION_MODEL_CACHE_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


def _run(caplog):
    with caplog.at_level(logging.WARNING):
        return upgrade_notices.check_upgrade_notices()


class TestLegacyEnvVars:
    def test_the_old_huggingface_token_is_called_out(self, caplog, monkeypatch):
        monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_old")
        assert "HUGGINGFACE_TOKEN" in _run(caplog)
        assert "CURIO_DEFAULT_HUGGINGFACE_TOKEN" in caplog.text

    @pytest.mark.parametrize(
        "name", ["STREETVISION_CACHE_DIR", "STREETVISION_MODEL_CACHE_DIR"]
    )
    def test_the_ignored_cache_overrides_are_called_out(self, caplog, monkeypatch, name):
        monkeypatch.setenv(name, "/mnt/warm-cache")
        warned = _run(caplog)
        assert name in warned
        # The consequence, not just the fact: a silently abandoned cache costs
        # Google Maps quota and re-downloads model weights per user.
        assert "re-fetched" in caplog.text

    def test_a_clean_deployment_says_nothing(self, caplog, monkeypatch):
        """No stale settings, no noise: the warnings have to stay meaningful."""
        import utk_curio.backend.config as cfg

        monkeypatch.setattr(cfg, "GUEST_LLM_API_KEY", "")
        assert _run(caplog) == []
        assert caplog.text == ""


class TestGuestModel:
    def test_a_guest_key_with_no_model_is_called_out(self, caplog, monkeypatch):
        import utk_curio.backend.config as cfg

        monkeypatch.setattr(cfg, "GUEST_LLM_API_KEY", "gk")
        monkeypatch.setattr(cfg, "GUEST_LLM_MODEL", "")
        assert "GUEST_LLM_MODEL" in _run(caplog)
        assert "guest AI will fail at run time" in caplog.text

    def test_a_configured_guest_provider_is_quiet(self, caplog, monkeypatch):
        import utk_curio.backend.config as cfg

        monkeypatch.setattr(cfg, "GUEST_LLM_API_KEY", "gk")
        monkeypatch.setattr(cfg, "GUEST_LLM_MODEL", "gpt-4o-mini")
        assert "GUEST_LLM_MODEL" not in _run(caplog)
