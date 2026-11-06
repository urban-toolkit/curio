"""The LLM tokens the monitor keeps: per UTC hour and per model, for the running process.

Two halves. The record (``monitor/llm_tokens.py``): what a request adds, how
the totals split into 24 hours, 7 days and every hour kept, the 90 days the
history holds, the file it writes, the backend start that starts it over, and
which model names a public page may show. The hook
(``agents/infrastructure/providers.py``): each request is counted once, right
after it. A turn asked again counts each of its requests, never their running
sum (``_summed_usage`` adds every request's usage up again after each one); a
stream its caller stopped counts what its provider had reported by then; and
the scripted provider counts what it scripted, which is what lets an e2e test
see tokens.

Each test's history file is in a folder of its own (``conftest.py``), and the
clock is set by the test, so no test crosses an hour as it runs.
"""

from __future__ import annotations

import json
import types
from datetime import datetime, timedelta, timezone

import pytest

from utk_curio.backend.app.agents.infrastructure import providers, testing_provider
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn, ProviderConfig
from utk_curio.backend.app.monitor import history as monitor_history
from utk_curio.backend.app.monitor import llm_tokens

NOW = datetime(2026, 11, 6, 15, 20, 7, tzinfo=timezone.utc)
ASKED = [{"role": "user", "content": "How many parks are in the loader?"}]


@pytest.fixture()
def clock(monkeypatch):
    """The monitor's clock, which a test moves with ``clock.at = ...``."""
    state = types.SimpleNamespace(at=NOW)
    monkeypatch.setattr(llm_tokens, "_now", lambda: state.at)
    return state


def _usage(input_tokens: int, output_tokens: int, requests: int) -> dict:
    return {"inputTokens": input_tokens, "outputTokens": output_tokens, "requests": requests}


def _models(body: dict | None = None) -> dict:
    """The route's models by ``(model, curio)``, in the route's order."""
    body = body if body is not None else llm_tokens.snapshot()
    return {(entry["model"], entry["curio"]): entry for entry in body["models"]}


# -- the record -----------------------------------------------------------------

class TestTheRecord:
    def test_requests_in_one_hour_add_up_by_model_and_endpoint(self, clock):
        llm_tokens.record("gemma4", curio=True, input_tokens=100, output_tokens=20)
        clock.at = NOW + timedelta(minutes=30)
        llm_tokens.record("gemma4", curio=True, input_tokens=50, output_tokens=5)
        # The same name on a key a user set for their own is a model of its own.
        llm_tokens.record("gemma4", curio=False, input_tokens=7, output_tokens=1)
        llm_tokens.record("gpt-5", curio=False, input_tokens=3, output_tokens=2)

        body = llm_tokens.snapshot()
        assert [(row["hour"], row["model"], row["curio"], row["inputTokens"], row["outputTokens"],
                 row["requests"]) for row in body["hourly"]] == [
            ("2026-11-06T15:00:00Z", "gemma4", True, 150, 25, 2),
            ("2026-11-06T15:00:00Z", "gemma4", False, 7, 1, 1),
            ("2026-11-06T15:00:00Z", "gpt-5", False, 3, 2, 1),
        ]
        models = _models(body)
        # Most tokens kept first.
        assert list(models) == [("gemma4", True), ("gemma4", False), ("gpt-5", False)]
        for window in ("last24h", "last7d", "kept"):
            assert models[("gemma4", True)][window] == _usage(150, 25, 2), window
            assert models[("gemma4", False)][window] == _usage(7, 1, 1), window

    def test_the_totals_split_into_24_hours_7_days_and_every_hour_kept(self, clock):
        """Rows on both sides of each boundary, oldest recorded first, as time runs."""
        hour = NOW.replace(minute=0, second=0)
        seen = [
            (NOW - timedelta(days=60), 100000),  # long before the 7 days, still kept
            (NOW - timedelta(hours=168), 10000),  # an hour before the 7 days
            (NOW - timedelta(hours=167), 1000),  # the first of the 7 days' hours
            (NOW - timedelta(hours=24), 100),  # an hour before the 24 hours
            (NOW - timedelta(hours=23), 10),  # the first of the 24 hours
            (NOW - timedelta(hours=1), 1),
        ]
        for at, tokens in seen:
            clock.at = at
            llm_tokens.record("gemma4", curio=True, input_tokens=tokens, output_tokens=0)
        clock.at = NOW

        body = llm_tokens.snapshot()
        totals = _models(body)[("gemma4", True)]
        assert totals["last24h"] == _usage(11, 0, 2)
        assert totals["last7d"] == _usage(1111, 0, 4)
        assert totals["kept"] == _usage(111111, 0, 6)
        assert [row["hour"] for row in body["hourly"]] == [
            (hour - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:00:00Z") for hours in (167, 24, 23, 1)
        ]
        assert body["hourlyFrom"] == (hour - timedelta(hours=167)).strftime("%Y-%m-%dT%H:00:00Z")
        assert body["hourlyTo"] == hour.strftime("%Y-%m-%dT%H:00:00Z")

    def test_the_history_holds_at_most_90_days_of_hours(self, clock):
        """Once full, the oldest hours go first: 90 days of hours counted back
        from the newest, so a row 2,160 hours before it is gone."""
        hour = NOW.replace(minute=0, second=0)
        for hours, tokens in ((90 * 24, 1), (90 * 24 - 1, 10), (0, 100)):
            clock.at = NOW - timedelta(hours=hours)
            llm_tokens.record("gemma4", curio=True, input_tokens=tokens, output_tokens=0)

        assert [row["hour"] for row in llm_tokens.HISTORY.rows()] == [
            (hour - timedelta(hours=90 * 24 - 1)).strftime("%Y-%m-%dT%H:00:00Z"),
            hour.strftime("%Y-%m-%dT%H:00:00Z"),
        ]
        assert _models()[("gemma4", True)]["kept"] == _usage(110, 0, 2)

    def test_the_file_on_disk_holds_what_the_process_recorded(self, clock):
        llm_tokens.record("gemma4", curio=True, input_tokens=100, output_tokens=20)
        llm_tokens.record("gpt-5", curio=False, input_tokens=3, output_tokens=2)
        llm_tokens.record("gemma4", curio=True, input_tokens=1, output_tokens=1)

        path = llm_tokens.HISTORY.path()
        assert path == monitor_history._folder() / "llm-tokens.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["name"] == "llm-tokens"
        assert doc["rows"] == llm_tokens.HISTORY.rows() == [
            {"hour": "2026-11-06T15:00:00Z", "model": "gemma4", "curio": True,
             "inputTokens": 101, "outputTokens": 21, "requests": 2},
            {"hour": "2026-11-06T15:00:00Z", "model": "gpt-5", "curio": False,
             "inputTokens": 3, "outputTokens": 2, "requests": 1},
        ]

    def test_a_backend_start_starts_the_tokens_over(self, clock):
        from utk_curio.backend.app import create_app
        from utk_curio.backend.tests._unit_fixtures import TestConfig

        llm_tokens.record("gemma4", curio=True, input_tokens=120, output_tokens=30)
        assert _models()[("gemma4", True)]["kept"] == _usage(120, 30, 1)
        path = llm_tokens.HISTORY.path()
        assert json.loads(path.read_text(encoding="utf-8"))["rows"]

        create_app(TestConfig)

        # The file the last process wrote is written anew, and the route forgets it at once.
        assert json.loads(path.read_text(encoding="utf-8"))["rows"] == []
        assert llm_tokens.snapshot()["models"] == []

    def test_a_record_is_on_the_route_at_once(self, clock):
        assert llm_tokens.snapshot()["models"] == []
        llm_tokens.record("gemma4", curio=True, input_tokens=5, output_tokens=1)
        # Well inside the 60 s the body is held for.
        assert _models()[("gemma4", True)]["kept"] == _usage(5, 1, 1)

    def test_a_record_that_cannot_be_written_still_counts_and_never_raises(self, clock, tmp_path, monkeypatch):
        blocked = tmp_path / "a-file"
        blocked.write_text("not a folder", encoding="utf-8")
        monkeypatch.setattr(monitor_history, "_folder", lambda: blocked / "monitor")

        llm_tokens.record("gemma4", curio=True, input_tokens=1, output_tokens=1)
        assert _models()[("gemma4", True)]["kept"] == _usage(1, 1, 1)


class TestModelNames:
    @pytest.mark.parametrize("name", [
        "gemma4", "scripted", "gpt-4.1", "claude-sonnet-4-5", "claude-3-5-sonnet@20240620",
        "models/gemini-2.5-pro", "meta-llama/Llama-3.1-8B-Instruct",
        "us.anthropic.claude-3-5-sonnet-20241022-v2:0", "llama3.1:8b", "qwen2.5-coder:32b",
    ])
    def test_a_model_id_is_shown_as_it_is(self, name):
        assert llm_tokens.public_model_name(name) == name

    @pytest.mark.parametrize("name", [
        "https://llm.example.com/v1", "http://localhost:11434", "www.example.com",
        "llm.example.com", "llm.example.com:8443", "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF",
        "localhost", "localhost:11434", "gpu-box:8000", "alice@example.org",
        "10.0.0.1", "10.0.0.1:8000", "fe80::1",
        "sk-proj-abcdef123456", "AIzaSyD-abcdefghijklmnopqrstuvwxyz012", "0123456789abcdef0123456789abcdef",
        "gemma 4", "a" * 101, "", None,
    ])
    def test_a_name_that_is_not_plainly_a_model_is_other(self, name):
        assert llm_tokens.public_model_name(name) == llm_tokens.OTHER

    def test_an_address_typed_as_a_model_is_recorded_as_other(self, clock):
        for typed in ("alice@example.org", "https://llm.example.com/v1", "10.0.0.1"):
            llm_tokens.record(typed, curio=False, input_tokens=2, output_tokens=1)
        assert {key: entry["kept"] for key, entry in _models().items()} == {
            ("other", False): _usage(6, 3, 3),
        }
        written = llm_tokens.HISTORY.path().read_text(encoding="utf-8")
        assert "example" not in written and "10.0.0.1" not in written

    def test_a_day_holds_at_most_its_cap_of_models(self, clock, monkeypatch):
        monkeypatch.setattr(llm_tokens, "MAX_MODELS_PER_DAY", 3)
        for name in ("m1", "m2", "m3", "m4", "m5"):
            llm_tokens.record(name, curio=False, input_tokens=1, output_tokens=0)
        # A model the day holds still counts as itself.
        llm_tokens.record("m1", curio=False, input_tokens=1, output_tokens=0)
        assert {key: entry["kept"]["requests"] for key, entry in _models().items()} == {
            ("m1", False): 2, ("m2", False): 1, ("m3", False): 1, ("other", False): 2,
        }

    def test_the_route_lists_the_models_with_most_tokens_and_sums_the_rest(self, clock, monkeypatch):
        monkeypatch.setattr(llm_tokens, "MAX_MODELS_SHOWN", 2)
        for name, tokens in (("big", 300), ("mid", 200), ("small", 10), ("tiny", 1)):
            llm_tokens.record(name, curio=True, input_tokens=tokens, output_tokens=0)
        body = llm_tokens.snapshot()
        assert [(entry["model"], entry["kept"]["inputTokens"], entry["kept"]["requests"])
                for entry in body["models"]] == [("big", 300, 1), ("mid", 200, 1), ("other", 11, 2)]
        assert {row["model"] for row in body["hourly"]} == {"big", "mid", "other"}


# -- the hook in providers.py -----------------------------------------------------

class TestEachRequestCountsOnce:
    @pytest.fixture(autouse=True)
    def _fresh_endpoints(self, monkeypatch):
        """No endpoint seen thinking or refusing the room, whatever ran before."""
        monkeypatch.setattr(providers, "_thinking_endpoints", set())
        monkeypatch.setattr(providers, "_room_refused", set())
        testing_provider.reset()
        yield
        testing_provider.reset()

    def test_a_turn_asked_again_counts_each_request_once(self, clock, monkeypatch):
        """A reply the cap cut before a word is asked again with room for
        thinking: two requests, each counted as it was, never their sum
        again on top of the first."""
        config = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="monitor-asked-again",
                                on_deployment=True)
        replies = iter([
            ({"inputTokens": 100, "outputTokens": 32}, ChatTurn(text="", stop_reason="max_tokens")),
            ({"inputTokens": 100, "outputTokens": 50}, ChatTurn(text="The reply.", stop_reason="end_turn")),
        ])
        limits = []

        def one_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema):
            limits.append(max_output_tokens)
            usage, turn = next(replies)
            usage_out.update(usage)
            return turn

        monkeypatch.setattr(providers, "_one_turn", one_turn)
        usage: dict = {}
        turn = providers.run_chat_turn(config, ASKED, 32, usage, thinking_tokens=1024)

        assert (turn.text, limits) == ("The reply.", [32, 32 + 1024])
        assert usage == {"inputTokens": 200, "outputTokens": 82}
        assert {key: entry["kept"] for key, entry in _models().items()} == {
            ("monitor-asked-again", True): _usage(200, 82, 2),
        }

    def test_a_request_refused_with_room_counts_nothing_and_its_second_counts(self, clock, monkeypatch):
        config = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="monitor-room-refused")
        monkeypatch.setattr(providers, "_thinking_endpoints", {providers._endpoint(config)})

        class Refused(Exception):
            status_code = 400

        limits = []

        def one_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema):
            limits.append(max_output_tokens)
            if len(limits) == 1:
                raise Refused("max_tokens is too large for this context window")
            usage_out.update(inputTokens=90, outputTokens=12)
            return ChatTurn(text="The reply.", stop_reason="end_turn")

        monkeypatch.setattr(providers, "_one_turn", one_turn)
        usage: dict = {}
        turn = providers.run_chat_turn(config, ASKED, 32, usage, thinking_tokens=1024)

        assert (turn.thinking_room_refused, limits) == (True, [32 + 1024, 32])
        assert usage == {"inputTokens": 90, "outputTokens": 12}
        assert _models()[("monitor-room-refused", False)]["kept"] == _usage(90, 12, 1)

    @staticmethod
    def _streaming(monkeypatch, closed: list):
        """A server that reports its usage as it streams, as vLLM's continuous
        usage stats do: what it has counted so far comes with each piece."""

        def one_stream(config, messages, max_output_tokens, usage_out, tools, tool_choice, finish):
            try:
                usage_out.update(inputTokens=500, outputTokens=1)
                yield "The "
                usage_out.update(inputTokens=500, outputTokens=2)
                yield "parks "
                usage_out.update(inputTokens=500, outputTokens=40)
                yield "are in the loader."
                finish["reason"] = "stop"
            finally:
                closed.append(True)

        monkeypatch.setattr(providers, "_one_stream", one_stream)

    def test_a_stream_its_caller_stopped_counts_what_its_provider_had_reported(self, clock, monkeypatch):
        closed: list = []
        self._streaming(monkeypatch, closed)
        config = ProviderConfig(api_key="k", api_type="openai_compatible", base_url="", model="monitor-stopped")
        usage: dict = {}

        events = providers.stream_chat_turn(config, ASKED, 4096, usage)
        assert next(events) == "The "
        events.close()

        assert closed == [True]
        assert usage == {"inputTokens": 500, "outputTokens": 1}
        assert _models()[("monitor-stopped", False)]["kept"] == _usage(500, 1, 1)

    def test_a_whole_stream_counts_its_last_report_once(self, clock, monkeypatch):
        closed: list = []
        self._streaming(monkeypatch, closed)
        config = ProviderConfig(api_key="k", api_type="openai_compatible", base_url="", model="monitor-whole")
        usage: dict = {}
        finish: dict = {}

        assert "".join(providers.stream_chat_turn(config, ASKED, 4096, usage, finish=finish)) == (
            "The parks are in the loader.")

        assert finish["reason"] == "stop"
        assert usage == {"inputTokens": 500, "outputTokens": 40}
        assert _models()[("monitor-whole", False)]["kept"] == _usage(500, 40, 1)

    def test_the_scripted_provider_counts_what_it_scripted_on_both_paths(self, clock):
        config = ProviderConfig(api_key="", api_type="testing", base_url="", model="scripted-monitor")
        testing_provider.push_reply("Whole.", usage={"in": 7, "out": 3})
        testing_provider.push_reply("Streamed.", usage={"in": 11, "out": 5})
        whole: dict = {}
        streamed: dict = {}

        assert providers.run_chat_turn(config, ASKED, usage_out=whole).text == "Whole."
        assert list(providers.stream_chat_turn(config, ASKED, usage_out=streamed)) == ["Streamed."]

        assert (whole, streamed) == ({"inputTokens": 7, "outputTokens": 3}, {"inputTokens": 11, "outputTokens": 5})
        assert _models()[("scripted-monitor", False)]["kept"] == _usage(18, 8, 2)

    def test_a_scripted_call_that_fails_reports_nothing_and_counts_nothing(self, clock):
        config = ProviderConfig(api_key="", api_type="testing", base_url="", model="scripted-monitor")
        testing_provider.push_reply({"error": "the model's server is down", "status": 503})

        with pytest.raises(testing_provider.ScriptedEndpointError):
            providers.run_chat_turn(config, ASKED)

        assert llm_tokens.snapshot()["models"] == []
