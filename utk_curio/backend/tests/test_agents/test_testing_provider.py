"""The scripted test provider (Phase 1.3).

This is the seam that lets e2e drive a real agent run - tools, policy, quotas,
the ledger, the content parser - without a key, a network, or a model that
answers differently twice. The claims that matter are that it is deterministic,
that it accounts for tokens (so the ledger path is genuinely exercised rather
than skipped), and above all that it refuses to work outside a test run.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents import testing_provider
from utk_curio.backend.app.agents.providers import ProviderConfig, run_chat_completion


@pytest.fixture(autouse=True)
def _clean_queue():
    testing_provider.reset()
    yield
    testing_provider.reset()


def _config() -> ProviderConfig:
    return ProviderConfig(api_key="", api_type="testing", base_url="", model="scripted")


class TestGuard:
    def test_refuses_when_not_testing(self, monkeypatch):
        """The whole point of the guard: a stray `testing` provider config on a
        real deployment must raise, not quietly become a working agent."""
        monkeypatch.setattr(testing_provider, "enabled", lambda: False)
        testing_provider.push_reply("should never be returned")
        with pytest.raises(testing_provider.TestingProviderUnavailable) as exc:
            testing_provider.run_scripted_completion([{"role": "user", "content": "hi"}])
        assert "CURIO_TESTING" in str(exc.value)

    def test_the_guard_reads_the_flag_at_call_time(self, monkeypatch):
        """Import-time evaluation would let a process that started under
        CURIO_TESTING keep serving scripted replies after the flag changed."""
        monkeypatch.setattr(testing_provider, "enabled", lambda: False)
        with pytest.raises(testing_provider.TestingProviderUnavailable):
            testing_provider.run_scripted_completion([])
        monkeypatch.setattr(testing_provider, "enabled", lambda: True)
        assert testing_provider.run_scripted_completion([]) == testing_provider.FALLBACK_REPLY


class TestQueue:
    def test_replies_come_back_in_order(self):
        testing_provider.push_replies("first", "second")
        assert testing_provider.run_scripted_completion([]) == "first"
        assert testing_provider.run_scripted_completion([]) == "second"

    def test_an_empty_queue_falls_back_rather_than_raising(self):
        """A test that forgot to script one leg of a conversation should fail on
        its own assertion, not on an exception from the provider."""
        assert testing_provider.run_scripted_completion([]) == testing_provider.FALLBACK_REPLY

    def test_reset_drops_what_is_queued(self):
        testing_provider.push_reply("stale")
        testing_provider.reset()
        assert testing_provider.pending() == 0
        assert testing_provider.run_scripted_completion([]) == testing_provider.FALLBACK_REPLY

    def test_the_fallback_mints_nothing(self):
        """It must parse as plain prose: a stray ```curio.v1``` block in the
        fallback would have unscripted turns silently minting proposals."""
        assert "curio.v1" not in testing_provider.FALLBACK_REPLY


class TestUsageAccounting:
    def test_default_counts_are_reported(self):
        usage: dict = {}
        testing_provider.run_scripted_completion([], usage_out=usage)
        assert usage == {"inputTokens": 12, "outputTokens": 34}

    def test_counts_are_non_zero_so_the_ledger_is_exercised(self):
        usage: dict = {}
        testing_provider.run_scripted_completion([], usage_out=usage)
        assert usage["inputTokens"] > 0 and usage["outputTokens"] > 0

    def test_a_rule_can_pin_its_own_counts(self):
        testing_provider.push_reply("hi", usage={"in": 5, "out": 7})
        usage: dict = {}
        testing_provider.run_scripted_completion([], usage_out=usage)
        assert usage == {"inputTokens": 5, "outputTokens": 7}


class TestNoFileScript:
    """The out-of-process JSON script path is gone.

    It existed so an e2e running against a live backend could script a
    reply. Nothing ever used it: the agent e2e suite covers the drawer, the
    palette and the requiresAgents closure, none of which runs a turn. If a
    chat e2e is written later, that is the point to add it back."""

    def test_no_env_var_is_read(self, tmp_path, monkeypatch):
        script = tmp_path / "script.json"
        script.write_text('{"default": "from file"}', encoding="utf-8")
        monkeypatch.setenv("CURIO_TESTING_LLM_SCRIPT", str(script))
        monkeypatch.setattr(testing_provider, "enabled", lambda: True)
        testing_provider.reset()
        assert (
            testing_provider.run_scripted_completion([])
            == testing_provider.FALLBACK_REPLY
        )

    def test_the_queue_is_the_only_way_to_script_a_reply(self, monkeypatch):
        monkeypatch.setattr(testing_provider, "enabled", lambda: True)
        testing_provider.reset()
        testing_provider.push_reply("from queue")
        assert testing_provider.run_scripted_completion([]) == "from queue"


class TestDispatch:
    def test_run_chat_completion_routes_testing_to_the_script(self):
        testing_provider.push_reply("dispatched")
        usage: dict = {}
        reply = run_chat_completion(_config(), [{"role": "user", "content": "hi"}], usage_out=usage)
        assert reply == "dispatched"
        assert usage == {"inputTokens": 12, "outputTokens": 34}

    def test_streaming_yields_the_same_reply(self):
        from utk_curio.backend.app.agents.providers import stream_chat_completion

        testing_provider.push_reply("streamed")
        chunks = list(stream_chat_completion(_config(), [{"role": "user", "content": "hi"}]))
        assert "".join(chunks) == "streamed"

    def test_no_provider_sdk_is_imported(self, monkeypatch):
        """Proof there is no network leg: make the SDKs unimportable and run anyway."""
        import builtins

        real_import = builtins.__import__

        def _blocked(name, *args, **kwargs):
            if name.split(".")[0] in {"openai", "anthropic", "google"}:
                raise AssertionError(f"the scripted provider imported {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocked)
        testing_provider.push_reply("offline")
        assert run_chat_completion(_config(), []) == "offline"
