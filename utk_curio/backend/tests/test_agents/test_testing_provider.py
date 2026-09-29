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

from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.app.agents.infrastructure.providers import (
    ProviderConfig,
    run_chat_completion,
)


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


def _delegated(intent: str, siblings: str = "") -> list:
    """A delegated request as the runtime sends it: a header, then JSON."""
    body = json.dumps({"intent": intent, "planSiblings": siblings})
    return [{"role": "user", "content": f"[delegated task from agent.x@1 - capability c]\n{body}"}]


class TestRoutingByIntent:
    def test_a_delegated_call_gets_the_reply_its_intent_names(self):
        """Solve asks per node in wave order, interleaved with other delegations,
        so only the call's own intent can say which node it is asking about."""
        testing_provider.route_by_intent({"load_labels": "LOAD", "plot_counts": "PLOT"})
        assert testing_provider.run_scripted_completion(_delegated("write plot_counts")) == "PLOT"
        assert testing_provider.run_scripted_completion(_delegated("write load_labels")) == "LOAD"

    def test_only_the_intent_is_matched_not_the_siblings(self):
        testing_provider.route_by_intent({"load_labels": "LOAD"})
        testing_provider.push_reply("queued")
        messages = _delegated("write the chart", siblings="load_labels feeds this node")
        assert testing_provider.run_scripted_completion(messages) == "queued"

    def test_the_longest_key_wins(self):
        testing_provider.route_by_intent({"load": "SHORT", "load_labels": "LONG"})
        assert testing_provider.run_scripted_completion(_delegated("write load_labels")) == "LONG"

    def test_an_unrouted_call_still_pops_the_queue(self):
        testing_provider.route_by_intent({"load_labels": "LOAD"})
        testing_provider.push_replies("plan")
        assert testing_provider.run_scripted_completion([{"role": "user", "content": "build it"}]) == "plan"
        assert testing_provider.pending() == 0

    def test_reset_drops_the_routes(self):
        testing_provider.route_by_intent({"load_labels": "LOAD"})
        testing_provider.reset()
        reply = testing_provider.run_scripted_completion(_delegated("write load_labels"))
        assert reply == testing_provider.FALLBACK_REPLY


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


class TestOutOfProcessScripting:
    """The out-of-process door is HTTP, not a file.

    A ``CURIO_TESTING_LLM_SCRIPT`` file once served this purpose and was removed
    as speculative when nothing used it. The e2e agent suite now runs real turns
    and needs to script them from another process; it does that through
    ``/api/testing/agent-script``, which drives this same queue. The env var must
    stay dead so the two cannot disagree about where a reply comes from."""

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
        from utk_curio.backend.app.agents.infrastructure.providers import stream_chat_completion

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


class TestCapture:
    """What reached the model.

    The reply is scripted, so it says nothing about which agent ran. The
    prompt does: the run path composes the system turn from that agent's own
    preamble and instruction. Capturing it is what makes a per-agent e2e a
    claim about that agent rather than about the plumbing.
    """

    def test_messages_are_recorded(self):
        messages = [{"role": "system", "content": "be helpful"},
                    {"role": "user", "content": "hi"}]
        testing_provider.run_scripted_completion(messages)
        assert testing_provider.captured() == [messages]
        assert testing_provider.last_messages() == messages

    def test_each_call_is_a_separate_entry(self):
        """A multi-round run (toolRequest then follow-up) must be legible as
        rounds, not flattened into one blob."""
        testing_provider.push_replies("round one", "round two")
        testing_provider.run_scripted_completion([{"role": "user", "content": "a"}])
        testing_provider.run_scripted_completion([{"role": "user", "content": "b"}])
        captured = testing_provider.captured()
        assert len(captured) == 2
        assert captured[0][0]["content"] == "a"
        assert captured[1][0]["content"] == "b"

    def test_the_prompt_does_not_choose_the_reply(self):
        """Capture must not turn into matching: scripting stays independent of
        prompt wording, or every test becomes hostage to prompt edits."""
        testing_provider.push_reply("scripted")
        assert testing_provider.run_scripted_completion(
            [{"role": "user", "content": "something else entirely"}]
        ) == "scripted"

    def test_capture_survives_a_fallback_call(self):
        """An unscripted call still records - that is how a test discovers it
        made a round it did not expect."""
        testing_provider.run_scripted_completion([{"role": "user", "content": "x"}])
        assert len(testing_provider.captured()) == 1

    def test_reset_clears_the_capture_too(self):
        testing_provider.run_scripted_completion([{"role": "user", "content": "x"}])
        testing_provider.reset()
        assert testing_provider.captured() == []
        assert testing_provider.last_messages() is None

    def test_nothing_captured_before_the_first_call(self):
        assert testing_provider.captured() == []
        assert testing_provider.last_messages() is None

    def test_the_log_is_bounded(self):
        """A backend process serving a whole e2e suite must not grow this
        without limit; oldest drop first."""
        for i in range(testing_provider.MAX_CAPTURED + 5):
            testing_provider.run_scripted_completion(
                [{"role": "user", "content": str(i)}]
            )
        captured = testing_provider.captured()
        assert len(captured) == testing_provider.MAX_CAPTURED
        assert captured[-1][0]["content"] == str(testing_provider.MAX_CAPTURED + 4)

    def test_the_returned_log_is_a_copy(self):
        """A caller iterating it must not be surprised by a concurrent run on
        the backend's other threads, nor able to corrupt the record."""
        testing_provider.run_scripted_completion([{"role": "user", "content": "x"}])
        snapshot = testing_provider.captured()
        snapshot.append("junk")
        snapshot[0].append("junk")
        assert len(testing_provider.captured()) == 1
        assert len(testing_provider.captured()[0]) == 1

    def test_a_guard_refusal_records_nothing(self, monkeypatch):
        """The refusal happens before the call is real."""
        monkeypatch.setattr(testing_provider, "enabled", lambda: False)
        with pytest.raises(testing_provider.TestingProviderUnavailable):
            testing_provider.run_scripted_completion([{"role": "user", "content": "x"}])
        monkeypatch.setattr(testing_provider, "enabled", lambda: True)
        assert testing_provider.captured() == []

    def test_dispatch_through_run_chat_completion_captures(self):
        """The capture has to survive the provider port, since that is the
        entry point every run actually uses."""
        testing_provider.push_reply("ok")
        run_chat_completion(_config(), [{"role": "system", "content": "preamble here"}])
        assert testing_provider.last_messages()[0]["content"] == "preamble here"

    def test_streaming_captures_too(self):
        from utk_curio.backend.app.agents.infrastructure.providers import stream_chat_completion

        testing_provider.push_reply("streamed")
        list(stream_chat_completion(_config(), [{"role": "user", "content": "streamy"}]))
        assert testing_provider.last_messages()[0]["content"] == "streamy"


class TestNativeCalls:
    """A scripted reply may call tools natively, as a model offered tools does."""

    TOOLS = [{"name": "node__read", "description": "", "parameters": {}}]

    def test_an_entry_makes_its_calls_under_their_native_names(self):
        from utk_curio.backend.app.agents.infrastructure.providers import ToolCall

        testing_provider.push_reply({"text": "Reading.", "toolCalls": [
            {"name": "node.read", "arguments": {"nodeId": "n1"}, "id": "c1"},
            {"name": "node__read"},
        ]})
        turn = testing_provider.run_scripted_turn([], tools=self.TOOLS)
        assert turn.text == "Reading."
        first, second = turn.tool_calls
        assert first == ToolCall("c1", "node__read", {"nodeId": "n1"})
        assert (second.name, second.arguments) == ("node__read", {})
        assert second.id and second.id != first.id

    def test_a_call_needs_a_call_that_offered_tools(self):
        testing_provider.push_replies(
            {"toolCalls": [{"name": "node.read"}]}, {"toolCalls": [{"name": "node.read"}]},
        )
        with pytest.raises(ValueError, match="offered no tool"):
            testing_provider.run_scripted_turn([])
        with pytest.raises(ValueError, match="last round"):
            testing_provider.run_scripted_turn([], tools=self.TOOLS, tool_choice="none")

    def test_an_error_entry_fails_the_call_uncharged(self):
        testing_provider.push_reply({"error": "no tools here", "status": 400})
        sink: dict = {}
        with pytest.raises(testing_provider.ScriptedEndpointError) as raised:
            testing_provider.run_scripted_turn([], usage_out=sink, tools=self.TOOLS)
        assert raised.value.status_code == 400 and sink == {}

    def test_what_each_call_offered_is_recorded(self):
        testing_provider.run_scripted_turn([], tools=self.TOOLS)
        testing_provider.run_scripted_turn([])
        assert testing_provider.offered() == [
            {"tools": ["node__read"], "toolChoice": "auto", "replySchema": None},
            {"tools": [], "toolChoice": None, "replySchema": None},
        ]
        testing_provider.reset()
        assert testing_provider.offered() == []

    def test_the_stream_yields_the_text_then_the_calls(self):
        from utk_curio.backend.app.agents.infrastructure.providers import (
            ToolCall,
            stream_chat_turn,
        )

        testing_provider.push_reply({"toolCalls": [{"name": "node.read", "id": "c1"}]})
        events = list(stream_chat_turn(_config(), [], tools=self.TOOLS))
        assert events == [ToolCall("c1", "node__read", {})]
        testing_provider.push_reply("plain")
        assert list(stream_chat_turn(_config(), [])) == ["plain"]

    def test_an_endpoint_error_on_a_call_offering_tools_is_a_refusal_of_them(self):
        from utk_curio.backend.app.agents.infrastructure.providers import (
            NativeToolsRefused,
            run_chat_turn,
        )

        testing_provider.push_reply({"error": "no tools here", "status": 422})
        with pytest.raises(NativeToolsRefused):
            run_chat_turn(_config(), [], tools=self.TOOLS)
