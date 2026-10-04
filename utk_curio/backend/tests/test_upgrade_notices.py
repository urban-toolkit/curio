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
def _clean(monkeypatch, tmp_path):
    for name in (
        "HUGGINGFACE_TOKEN",
        "CURIO_DEFAULT_HUGGINGFACE_TOKEN",
        "STREETVISION_CACHE_DIR",
        "STREETVISION_MODEL_CACHE_DIR",
        "CURIO_DATALAKE_ROOT",
        "CURIO_STATE_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    # A .curio of the test's own, so no leftover folder speaks for it.
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))


def _run(caplog):
    with caplog.at_level(logging.WARNING):
        return upgrade_notices.check_upgrade_notices()


class TestLegacyEnvVars:
    @pytest.mark.parametrize("name", ["HUGGINGFACE_TOKEN", "CURIO_DEFAULT_HUGGINGFACE_TOKEN"])
    def test_a_deployment_huggingface_token_is_called_out(self, caplog, monkeypatch, name):
        monkeypatch.setenv(name, "hf_old")
        assert name in _run(caplog)
        assert "API Settings" in caplog.text

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


class TestTheOldDataLake:
    """The Data Lake Catalog became the Discovery Catalog. Its root setting and
    its folder for an operator's own sources are not read, and nothing moves
    them, so a source left there leaves the catalog."""

    def test_the_old_root_setting_is_called_out(self, caplog, monkeypatch):
        monkeypatch.setenv("CURIO_DATALAKE_ROOT", "/srv/lakes")
        assert "CURIO_DATALAKE_ROOT" in _run(caplog)
        assert "--discovery-root" in caplog.text

    def test_the_old_sources_folder_is_called_out(self, caplog):
        from utk_curio.backend.app.common.user_storage import curio_root

        old = curio_root() / "datalakes"
        old.mkdir(parents=True)
        assert ".curio/datalakes" in _run(caplog)
        assert str(old) in caplog.text
        # A moved lake.* folder is skipped as a malformed name: say how to rename it.
        assert "source." in caplog.text


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
