"""Remembering what a provider was last seen to serve (#241).

This replaced a hand-maintained table of model ids. The table was wrong in a way
that only shows up later - it drifts the moment a provider ships or retires a
model, stale entries still look plausible, and it could say nothing at all about
a custom OpenAI-compatible endpoint. A recording of what an endpoint reported
about itself has none of those problems and needs no maintainer.

What matters here is that the recording is *honest*: scoped to the endpoint it
came from, scoped to the account whose key asked, and never load-bearing - a
store that cannot be read or written must degrade to "no suggestions", never to
an error, because suggestions are a nicety and the Model field is free text.
"""

import json

import pytest

from utk_curio.backend.app.agents.model_catalog import (
    provider_key,
    remember_models,
    remembered_models,
)

# storage.py::_user_key_segment accepts only a numeric user id or "guest",
# so these are ids rather than names.
USER = "1"
OTHER = "2"


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    """Point the per-user store at a temp dir for every case."""
    from utk_curio.backend.app.agents import model_catalog

    monkeypatch.setattr(model_catalog, "_users_base", lambda: tmp_path)
    return tmp_path


class TestProviderKey:
    def test_a_base_url_is_part_of_the_identity(self):
        # openai_compatible covers real OpenAI *and* every self-hosted server;
        # their listings have nothing to do with each other.
        assert provider_key("openai_compatible") != provider_key(
            "openai_compatible", "http://localhost:11434/v1"
        )

    def test_a_trailing_slash_is_not_a_different_endpoint(self):
        assert provider_key("openai_compatible", "http://x.test/v1/") == provider_key(
            "openai_compatible", "http://x.test/v1"
        )

    def test_providers_are_kept_apart(self):
        keys = {provider_key(t) for t in ("anthropic", "gemini", "openai_compatible")}
        assert len(keys) == 3

    def test_a_blank_type_lands_on_the_route_default(self):
        assert provider_key("") == provider_key("openai_compatible")


class TestRemembering:
    def test_a_listing_comes_back_out(self):
        remember_models(USER, "anthropic", "", ["b-model", "a-model"])
        models, seen_at = remembered_models(USER, "anthropic")
        # Order is preserved as reported, not re-sorted: the route already sorts
        # what the SDK returns, and re-ordering here would drift from it.
        assert models == ["b-model", "a-model"]
        assert seen_at, "the panel needs to say when this was true"

    def test_nothing_is_remembered_before_a_first_fetch(self):
        # The honest cold-start state, and the reason the route answers 400
        # there rather than inventing suggestions.
        assert remembered_models(USER, "anthropic") == ([], None)

    def test_a_later_listing_supersedes_the_earlier_one(self):
        remember_models(USER, "gemini", "", ["old"])
        remember_models(USER, "gemini", "", ["new"])
        models, _ = remembered_models(USER, "gemini")
        assert models == ["new"]

    def test_one_endpoint_does_not_answer_for_another(self):
        remember_models(USER, "openai_compatible", "", ["gpt-4o"])
        remember_models(USER, "openai_compatible", "http://ollama.test/v1", ["llama"])
        assert remembered_models(USER, "openai_compatible")[0] == ["gpt-4o"]
        assert remembered_models(
            USER, "openai_compatible", "http://ollama.test/v1"
        )[0] == ["llama"]

    def test_one_account_does_not_answer_for_another(self):
        # What a listing returns depends on the entitlements of the key that
        # asked, so one account's result is not a fact about another's.
        remember_models(USER, "anthropic", "", ["mine"])
        assert remembered_models(OTHER, "anthropic") == ([], None)

    def test_several_providers_coexist_for_one_account(self):
        remember_models(USER, "anthropic", "", ["a"])
        remember_models(USER, "gemini", "", ["g"])
        assert remembered_models(USER, "anthropic")[0] == ["a"]
        assert remembered_models(USER, "gemini")[0] == ["g"]

    def test_an_empty_listing_is_not_worth_recording(self):
        remember_models(USER, "anthropic", "", ["real"])
        remember_models(USER, "anthropic", "", [])
        # Otherwise a provider having a bad minute erases a good recording.
        assert remembered_models(USER, "anthropic")[0] == ["real"]

    def test_junk_entries_are_dropped(self):
        remember_models(USER, "anthropic", "", ["ok", "", "  ", None, 7, "ok"])  # type: ignore[list-item]
        assert remembered_models(USER, "anthropic")[0] == ["ok"]

    def test_a_pathological_endpoint_cannot_grow_the_store_without_bound(self):
        from utk_curio.backend.app.agents.model_catalog import _MAX_REMEMBERED

        remember_models(USER, "anthropic", "", [f"m{i}" for i in range(_MAX_REMEMBERED + 50)])
        assert len(remembered_models(USER, "anthropic")[0]) == _MAX_REMEMBERED


class TestDegradingQuietly:
    def test_a_corrupt_store_reads_as_empty(self, _store):
        from utk_curio.backend.app.agents.model_catalog import _path

        p = _path(USER)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")
        # Never an exception: the Model field is free text, so losing
        # suggestions must cost the user nothing but the suggestions.
        assert remembered_models(USER, "anthropic") == ([], None)

    def test_a_corrupt_store_is_replaced_by_the_next_success(self, _store):
        from utk_curio.backend.app.agents.model_catalog import _path

        p = _path(USER)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[]", encoding="utf-8")
        remember_models(USER, "anthropic", "", ["recovered"])
        assert remembered_models(USER, "anthropic")[0] == ["recovered"]

    def test_a_store_shaped_wrongly_reads_as_empty(self, _store):
        from utk_curio.backend.app.agents.model_catalog import _path

        p = _path(USER)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"providers": "not-a-dict"}), encoding="utf-8")
        assert remembered_models(USER, "anthropic") == ([], None)

    def test_an_entry_with_no_timestamp_still_yields_its_models(self, _store):
        from utk_curio.backend.app.agents.model_catalog import _path, provider_key

        p = _path(USER)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {"version": 1, "providers": {provider_key("anthropic"): {"models": ["m"]}}}
            ),
            encoding="utf-8",
        )
        models, seen_at = remembered_models(USER, "anthropic")
        assert models == ["m"]
        assert seen_at is None
