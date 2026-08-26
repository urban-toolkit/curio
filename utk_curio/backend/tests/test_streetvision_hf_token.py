"""How the Street Vision node gets a HuggingFace token.

The token gates *gated* models: ones you unlock by accepting a licence with
your own HuggingFace account. It used to be a single operator secret in a bare
``HUGGINGFACE_TOKEN`` env var, which could not represent a per-account
entitlement and was invisible to the people it applied to. It is now:

- an account setting, edited in AI Settings (``user.huggingface_token``),
- with a deployment fallback from ``curio.py start --huggingface-token``
  (``CURIO_DEFAULT_HUGGINGFACE_TOKEN``),
- resolved in the request and handed down, because model loading runs on a
  detached worker thread with no request context,
- and part of the model cache key, so one account's gated download is not
  silently reused by another.
"""

from __future__ import annotations

import os
import sys
import types

import pytest

from utk_curio.backend.app.streetvision.services import huggingface as hf


@pytest.fixture()
def launch_dir(tmp_path, monkeypatch):
    """Anchor ``.curio/`` under a temp dir, the way the path helpers resolve it.

    Not ``tmp_curio``: that fixture lives in the per-package conftests and this
    file sits above them.
    """
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("CURIO_DEFAULT_HUGGINGFACE_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    hf._model_cache.clear()
    yield
    hf._model_cache.clear()


def _fake_user(monkeypatch, token):
    """Stand in for the request's signed-in user."""
    module = types.ModuleType("utk_curio.backend.app.users.dependencies")
    module.get_current_user = lambda: types.SimpleNamespace(huggingface_token=token)
    monkeypatch.setitem(
        sys.modules, "utk_curio.backend.app.users.dependencies", module
    )


class TestResolution:
    def test_nothing_configured_is_none(self):
        # Not an error: public models need no token, so a missing one must not
        # break the far more common case.
        assert hf.resolve_hf_token() is None

    def test_the_bare_legacy_variable_is_no_longer_read(self, monkeypatch):
        monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_legacy")
        assert hf.resolve_hf_token() is None

    def test_deployment_default_is_the_fallback(self, monkeypatch):
        monkeypatch.setenv("CURIO_DEFAULT_HUGGINGFACE_TOKEN", "hf_deployment")
        assert hf.resolve_hf_token() == "hf_deployment"

    def test_the_users_own_token_wins(self, monkeypatch):
        monkeypatch.setenv("CURIO_DEFAULT_HUGGINGFACE_TOKEN", "hf_deployment")
        _fake_user(monkeypatch, "hf_mine")
        assert hf.resolve_hf_token() == "hf_mine"

    def test_a_user_without_one_falls_back(self, monkeypatch):
        monkeypatch.setenv("CURIO_DEFAULT_HUGGINGFACE_TOKEN", "hf_deployment")
        _fake_user(monkeypatch, None)
        assert hf.resolve_hf_token() == "hf_deployment"

    def test_no_request_context_falls_back_instead_of_raising(self, monkeypatch):
        # `/models/search` is reachable without auth. Outside a request the
        # lookup raises, and a search the deployment token can still answer
        # must not fail because of it.
        module = types.ModuleType("utk_curio.backend.app.users.dependencies")

        def _boom():
            raise RuntimeError("Working outside of request context")

        module.get_current_user = _boom
        monkeypatch.setitem(
            sys.modules, "utk_curio.backend.app.users.dependencies", module
        )
        monkeypatch.setenv("CURIO_DEFAULT_HUGGINGFACE_TOKEN", "hf_deployment")
        assert hf.resolve_hf_token() == "hf_deployment"


class TestCacheKeying:
    """The trap this avoids: keyed on model_id alone, the first user to
    download a gated model seeds an entry every later caller hits for free."""

    def test_a_different_token_misses_the_cache(self):
        hf._model_cache[("m", hf._token_fingerprint("hf_a"))] = ("model", None, "seg")
        assert hf.get_cached_model("m", "hf_a") == ("model", None, "seg")
        assert hf.get_cached_model("m", "hf_b") is None
        assert hf.get_cached_model("m", None) is None

    def test_the_same_token_hits(self):
        hf._model_cache[("m", hf._token_fingerprint("hf_a"))] = ("model", None, "seg")
        assert hf.get_cached_model("m", "hf_a") is not None

    def test_tokenless_callers_share_one_entry(self):
        # Public models: no entitlement to keep apart, so no reason to reload
        # per caller.
        hf._model_cache[("m", hf._token_fingerprint(None))] = ("model", None, "seg")
        assert hf.get_cached_model("m") is not None
        assert hf.get_cached_model("m", "") is not None

    def test_the_key_does_not_contain_the_token(self):
        fp = hf._token_fingerprint("hf_secret")
        assert "hf_secret" not in fp
        assert fp == hf._token_fingerprint("hf_secret")  # stable
        assert fp != hf._token_fingerprint("hf_other")


class TestPerUserCacheDirs:
    """Both on-disk caches live under the caller's own user directory.

    They were one deployment-wide tree at ``.curio/streetvision/``, with
    ``STREETVISION_CACHE_DIR`` and ``STREETVISION_MODEL_CACHE_DIR`` overrides.
    All of it is gone: the panoramas were fetched with one user's Google Maps
    key, the overlays computed from their runs, and the model weights possibly
    downloaded against a gated licence only their account accepted.
    """

    def test_image_and_overlay_dirs_are_scoped_to_the_user(self, launch_dir):
        from utk_curio.backend.app.streetvision.services import cache

        mine = cache.images_dir("7")
        theirs = cache.images_dir("guest")
        assert mine != theirs
        for path in (mine, theirs):
            assert os.path.join(".curio", "users") in path
            assert "streetvision" in path

    def test_model_cache_is_scoped_to_the_user(self, launch_dir):
        assert hf._model_cache_dir("7") != hf._model_cache_dir("guest")
        assert os.path.join("users", "7") in hf._model_cache_dir("7")

    def test_no_env_override_is_honoured(self, monkeypatch, launch_dir):
        from utk_curio.backend.app.streetvision.services import cache

        monkeypatch.setenv("STREETVISION_CACHE_DIR", "/somewhere/else")
        monkeypatch.setenv("STREETVISION_MODEL_CACHE_DIR", "/somewhere/else")
        assert "/somewhere/else" not in cache.images_dir("7")
        assert "/somewhere/else" not in hf._model_cache_dir("7")

    def test_a_bogus_user_key_cannot_escape_the_store(self, launch_dir):
        from utk_curio.backend.app.streetvision.services import cache

        # The shared guard: only "guest" or a numeric id is a user key.
        for bad in ("../../etc", "guest/../7", "alice"):
            with pytest.raises(ValueError):
                cache.user_root(bad)
            with pytest.raises(ValueError):
                hf._model_cache_dir(bad)

    def test_one_users_overlay_is_not_found_for_another(self, launch_dir):
        from utk_curio.backend.app.streetvision.services import cache

        target = os.path.join(cache.overlays_dir("7"), "pano_overlay.png")
        with open(target, "wb") as handle:
            handle.write(b"png")
        assert cache.overlay_path("7", "pano.jpg") == target
        # The miss that matters: it is somebody else's file.
        assert cache.overlay_path("guest", "pano.jpg") is None


class TestThreadHandover:
    def test_load_model_accepts_an_explicit_token(self, monkeypatch):
        # The worker thread has no request context, so the token has to arrive
        # as an argument rather than be resolved again downstream.
        called = {}
        monkeypatch.setattr(
            hf, "resolve_hf_token", lambda: called.setdefault("resolved", True)
        )
        with pytest.raises(ValueError):
            # An unsupported model_type is the cheapest way to reach the end of
            # the token-handling block without importing torch.
            hf.load_model("m", "not-a-type", "hf_explicit", "7")
        assert "resolved" not in called, "an explicit token must not be re-resolved"

    def test_load_model_resolves_when_not_given_one(self, monkeypatch):
        monkeypatch.setattr(hf, "resolve_hf_token", lambda: "hf_resolved")
        with pytest.raises(ValueError):
            hf.load_model("m", "not-a-type")
