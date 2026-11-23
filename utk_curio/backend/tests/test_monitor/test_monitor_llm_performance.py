"""The performance of this Curio's own LLM models that the monitor keeps: per
5 minutes, hour or day and per model, kept across restarts.

Two halves. The record (``monitor/llm_performance.py``): what a request adds,
what each view of the rows reads (the last 24 hours in 5-minute rows, 7 days
in hourly rows, 90 days in daily rows: requests, failures, average and 95th
percentile time, time to the first token, output tokens per second), the 90
days the history keeps, the file every process writes, which a backend start
keeps, and which model names a public page may show. The hook
(``agents/infrastructure/providers.py``): only a request on this Curio's own
endpoint counts, once, as it ends, timed from before it was asked; one on a
key a user set for their own records nothing. A turn asked again counts each
of its requests, never their running sum (``_summed_usage`` adds every
request's usage up again after each one); a request that raised counts as
failed, with its time; a stream's first token is its first word or call; a
stream its caller stopped counts what its provider had reported by then, and
did not fail; and the scripted provider's turn counts as a request, which is
what lets an e2e test see it.

Each test's history file is in a folder of its own (``conftest.py``), and the
clocks are the test's: the monitor's (``llm_performance._now``), so no test
crosses a 5-minute slot as it runs, and the one requests are timed by
(``providers._clock``), which moves only when a test's request moves it. The
route reads the file, so a test writes what the process holds (:func:`_written`),
as the process's writer does each minute, before it reads.
"""

from __future__ import annotations

import json
import types
from datetime import datetime, timedelta, timezone

import pytest

from utk_curio.backend.app.agents.infrastructure import providers, testing_provider
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn, ProviderConfig, ToolCall
from utk_curio.backend.app.monitor import durations
from utk_curio.backend.app.monitor import history as monitor_history
from utk_curio.backend.app.monitor import llm_performance

NOW = datetime(2026, 11, 6, 15, 20, 7, tzinfo=timezone.utc)
ASKED = [{"role": "user", "content": "How many parks are in the loader?"}]
#: The sums a row holds besides its duration buckets.
SUMS = ("requests", "failed", "ms", "firstTokenMs", "firstTokens", "outputTokens", "outputMs")


@pytest.fixture()
def clock(monkeypatch):
    """The monitor's clock, which a test moves with ``clock.at = ...``."""
    state = types.SimpleNamespace(at=NOW)
    monkeypatch.setattr(llm_performance, "_now", lambda: state.at)
    return state


class _Timer:
    """The clock requests are timed by (``providers._clock``): it moves only
    when a test's request moves it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def wait(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def timer(monkeypatch):
    clock = _Timer()
    monkeypatch.setattr(providers, "_clock", clock)
    return clock


def _buckets(**placed) -> list[int]:
    """Bucket counts with *placed* counts, by bucket number (``b0`` to ``b18``)."""
    out = [0] * durations.BUCKETS
    for name, count in placed.items():
        out[int(name[1:])] = count
    return out


def _record(model: str = "gemma4", *, ms=1000, first_token_ms=None, output_tokens=None, failed=False) -> None:
    llm_performance.record(model, ms=ms, first_token_ms=first_token_ms, output_tokens=output_tokens, failed=failed)


def _written() -> None:
    """What this process holds of the requests, written into the file, as the
    process's writer does each minute."""
    assert llm_performance.HISTORY.flush() is True


def _view(name: str, body: dict | None = None) -> dict:
    """The route's view *name* (``24h``, ``7d`` or ``90d``): of *body*, else of
    the route once what the process holds is written."""
    if body is None:
        _written()
        body = llm_performance.snapshot()
    return body["views"][name]


def _models(name: str = "90d", body: dict | None = None) -> dict:
    """A view's models by name, in the route's order."""
    return {entry["model"]: entry for entry in _view(name, body)["models"]}


def _sums(model: str) -> dict:
    """Every row the file holds of *model*, added up, once what the process
    holds is written."""
    _written()
    rows = [row for row in llm_performance.HISTORY.rows() if row["model"] == model]
    return {field: sum(row[field] for row in rows) for field in SUMS}


# -- the record -----------------------------------------------------------------

class TestTheRecord:
    def test_requests_in_one_slot_add_up_by_model(self, clock):
        _record("gemma4", ms=1200, first_token_ms=300, output_tokens=60)
        clock.at = NOW + timedelta(minutes=2)
        _record("gemma4", ms=800, output_tokens=20, failed=True)
        _record("qwen3", ms=4000)

        _written()
        assert llm_performance.HISTORY.rows() == [
            {"at": "2026-11-06T15:20:00Z", "span": "5m", "model": "gemma4", "requests": 2, "failed": 1,
             "ms": 2000, "buckets": _buckets(b9=1, b10=1), "firstTokenMs": 300, "firstTokens": 1,
             "outputTokens": 80, "outputMs": 2000},
            {"at": "2026-11-06T15:20:00Z", "span": "5m", "model": "qwen3", "requests": 1, "failed": 0,
             "ms": 4000, "buckets": _buckets(b11=1), "firstTokenMs": 0, "firstTokens": 0,
             "outputTokens": 0, "outputMs": 0},
        ]
        view = _view("24h")
        # Most requests first. The 95th percentile is read from the buckets:
        # 1,000 to 2,500 ms holds gemma4's rank, 1.9 of its 2 requests.
        assert view["models"] == [
            {"model": "gemma4", "requests": 2, "failed": 1, "averageMs": 1000, "p95Ms": 2350,
             "firstTokenMs": 300, "tokensPerSecond": 40.0},
            {"model": "qwen3", "requests": 1, "failed": 0, "averageMs": 4000, "p95Ms": 4875,
             "firstTokenMs": None, "tokensPerSecond": None},
        ]
        assert view["all"] == {"requests": 3, "failed": 1, "averageMs": 2000, "p95Ms": 4625,
                               "firstTokenMs": 300, "tokensPerSecond": 40.0}
        assert [(row["at"], row["model"], row["requests"], row["failed"], row["ms"]) for row in view["rows"]] == [
            ("2026-11-06T15:20:00Z", "gemma4", 2, 1, 2000),
            ("2026-11-06T15:20:00Z", "qwen3", 1, 0, 4000),
        ]
        # The same requests in every view.
        assert _view("7d")["models"] == _view("90d")["models"] == view["models"]

    def test_each_view_reads_its_own_rows_and_says_where_it_starts_and_ends(self, clock):
        """Rows on both sides of each view's start, oldest recorded first, as time runs."""
        seen = [
            (datetime(2026, 8, 8, 23, 20, tzinfo=timezone.utc), 1),  # kept, the day before the 90 days
            (datetime(2026, 8, 9, 0, 0, 30, tzinfo=timezone.utc), 10),  # the first of the 90 days
            (NOW - timedelta(hours=168), 100),  # an hour before the 7 days
            (NOW - timedelta(hours=167), 1000),  # in the first of the 7 days' hours
            (datetime(2026, 11, 5, 15, 24, 59, tzinfo=timezone.utc), 10000),  # before the 24 hours
            (datetime(2026, 11, 5, 15, 25, tzinfo=timezone.utc), 100000),  # the first of the 24 hours' slots
            (NOW, 1000000),
            (NOW + timedelta(minutes=10), 5),  # past now, as a clock set back dates it
        ]
        for at, ms in seen:
            clock.at = at
            _record("gemma4", ms=ms)
        clock.at = NOW

        _written()
        # The file keeps every one of them, the day before the 90 days and the
        # row past now among them.
        kept = [(row["at"], row["ms"]) for row in llm_performance.HISTORY.rows()]
        assert (len(kept), kept[0], kept[-1]) == (
            len(seen), ("2026-08-08T23:00:00Z", 1), ("2026-11-06T15:30:00Z", 5))
        views = llm_performance.snapshot()["views"]
        assert [(name, view["from"], view["to"], view["stepSeconds"]) for name, view in views.items()] == [
            ("24h", "2026-11-05T15:25:00Z", "2026-11-06T15:20:00Z", 300),
            ("7d", "2026-10-30T16:00:00Z", "2026-11-06T15:00:00Z", 3600),
            ("90d", "2026-08-09T00:00:00Z", "2026-11-06T00:00:00Z", 86400),
        ]
        assert [(row["at"], row["requests"], row["ms"]) for row in views["24h"]["rows"]] == [
            ("2026-11-05T15:25:00Z", 1, 100000),
            ("2026-11-06T15:20:00Z", 1, 1000000),
        ]
        assert [(row["at"], row["requests"], row["ms"]) for row in views["7d"]["rows"]] == [
            ("2026-10-30T16:00:00Z", 1, 1000),
            ("2026-11-05T15:00:00Z", 2, 110000),
            ("2026-11-06T15:00:00Z", 1, 1000000),
        ]
        assert [(row["at"], row["requests"], row["ms"]) for row in views["90d"]["rows"]] == [
            ("2026-08-09T00:00:00Z", 1, 10),
            ("2026-10-30T00:00:00Z", 2, 1100),
            ("2026-11-05T00:00:00Z", 2, 110000),
            ("2026-11-06T00:00:00Z", 1, 1000000),
        ]
        # Each view's table reads the rows its chart draws.
        for name, view in views.items():
            requests = sum(row["requests"] for row in view["rows"])
            assert view["all"]["requests"] == requests, name
            assert view["all"]["averageMs"] == round(sum(row["ms"] for row in view["rows"]) / requests), name
            assert view["models"] == [{"model": "gemma4", **view["all"]}], name

    def test_the_history_holds_at_most_90_days_of_hours(self, clock):
        """Once full, the oldest hours go first: 90 days of hours counted back
        from the current hour, so a row 2,160 hours before it is gone."""
        hour = NOW.replace(minute=0, second=0)
        for hours, ms in ((90 * 24, 1), (90 * 24 - 1, 10), (0, 100)):
            clock.at = NOW - timedelta(hours=hours)
            _record("gemma4", ms=ms)
        clock.at = NOW

        _written()
        assert [(row["at"], row["span"], row["ms"]) for row in llm_performance.HISTORY.rows()] == [
            ((hour - timedelta(hours=90 * 24 - 1)).strftime("%Y-%m-%dT%H:00:00Z"), "1h", 10),
            ("2026-11-06T15:20:00Z", "5m", 100),
        ]
        # The 90 days' view is the current UTC day and the 89 before it: the
        # oldest hour the file keeps, on the day before them, is left out.
        assert _view("90d")["all"]["requests"] == 1

    def test_the_file_on_disk_holds_what_the_process_recorded(self, clock):
        _record("gemma4", ms=1200, first_token_ms=300, output_tokens=60)
        _record("qwen3", ms=40, failed=True)
        _record("gemma4", ms=800, output_tokens=20)

        _written()
        path = llm_performance.HISTORY.path()
        assert path == monitor_history._folder() / "llm.json"
        text = path.read_text(encoding="utf-8")
        doc = json.loads(text)
        assert (doc["name"], doc["format"]) == ("llm", llm_performance.FILE_FORMAT) == ("llm", 3)
        assert doc["rows"] == llm_performance.HISTORY.rows() == [
            {"at": "2026-11-06T15:20:00Z", "span": "5m", "model": "gemma4", "requests": 2, "failed": 0,
             "ms": 2000, "buckets": _buckets(b9=1, b10=1), "firstTokenMs": 300, "firstTokens": 1,
             "outputTokens": 80, "outputMs": 2000},
            {"at": "2026-11-06T15:20:00Z", "span": "5m", "model": "qwen3", "requests": 1, "failed": 1,
             "ms": 40, "buckets": _buckets(b5=1), "firstTokenMs": 0, "firstTokens": 0,
             "outputTokens": 0, "outputMs": 0},
        ]
        # Sums alone, each a whole number, which every write adds up exactly,
        # and nothing of where a model ran.
        for row in doc["rows"]:
            assert all(type(row[field]) is int for field in SUMS), row
            assert all(type(count) is int for count in row["buckets"]), row
        assert "curio" not in text

    def test_two_writes_of_one_slot_add_up_exactly(self, clock):
        """Each process writes what it holds into the one file: every field is
        a sum, so the rows of one slot and model add up whoever wrote them."""
        _record("gemma4", ms=1200, first_token_ms=300, output_tokens=60)
        _written()
        _record("gemma4", ms=800, first_token_ms=100, output_tokens=20, failed=True)

        assert _sums("gemma4") == {"requests": 2, "failed": 1, "ms": 2000, "firstTokenMs": 400, "firstTokens": 2,
                                   "outputTokens": 80, "outputMs": 2000}
        assert [row["buckets"] for row in llm_performance.HISTORY.rows()] == [_buckets(b9=1, b10=1)]

    def test_a_file_of_the_earlier_buckets_reads_as_empty_and_the_next_write_replaces_it(self, clock):
        """Rows counted in the buckets from 50 ms (format 2) are never joined
        with these: the file reads as no rows until its next write."""
        path = llm_performance.HISTORY.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": "llm", "format": 2, "rows": [
            {"at": "2026-11-06T15:20:00Z", "span": "5m", "model": "gemma4", "requests": 3, "failed": 0,
             "ms": 3000, "buckets": [0, 0, 0, 0, 3] + [0] * 9, "firstTokenMs": 0, "firstTokens": 0,
             "outputTokens": 0, "outputMs": 0},
        ]}), encoding="utf-8")
        assert llm_performance.HISTORY.rows() == []
        assert _view("24h")["all"]["requests"] == 0

        _record("gemma4", ms=1200)
        _written()
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert (doc["format"], [(row["model"], row["requests"], row["buckets"]) for row in doc["rows"]]) == (
            3, [("gemma4", 1, _buckets(b10=1))])
        assert not list(path.parent.glob("llm.json.unreadable-*"))

    def test_a_time_that_is_not_one_reads_as_0_ms_and_a_count_that_is_not_one_as_not_reported(self, clock):
        """Never raised: a request still counts once."""
        llm_performance.record("gemma4", ms="soon", first_token_ms=None, output_tokens=True, failed=False)
        llm_performance.record("gemma4", ms=-5, first_token_ms=float("nan"), output_tokens="12", failed=False)
        assert _sums("gemma4") == {"requests": 2, "failed": 0, "ms": 0, "firstTokenMs": 0, "firstTokens": 1,
                                   "outputTokens": 0, "outputMs": 0}

    def test_a_backend_start_keeps_the_rows(self, clock):
        from utk_curio.backend.app import create_app
        from utk_curio.backend.tests._unit_fixtures import TestConfig

        _record("gemma4", ms=1200, first_token_ms=300, output_tokens=60)
        kept = _models()["gemma4"]
        assert kept["requests"] == 1
        path = llm_performance.HISTORY.path()
        before = path.read_bytes()

        create_app(TestConfig)
        llm_performance.reset()  # the cache and what the process held, as a new process starts

        assert path.read_bytes() == before
        assert _models()["gemma4"] == kept

    def test_a_record_is_on_the_route_once_its_process_wrote_it(self, clock):
        _record("gemma4", ms=1200)
        assert llm_performance.snapshot()["views"]["24h"]["models"] == []
        _written()
        # Well inside the 60 s the body is held for: the file changed.
        assert _models("24h", llm_performance.snapshot())["gemma4"]["requests"] == 1

    def test_a_record_that_cannot_be_written_yet_is_kept_and_never_raises(self, clock, tmp_path, monkeypatch):
        folder = monitor_history._folder()
        blocked = tmp_path / "a-file"
        blocked.write_text("not a folder", encoding="utf-8")
        monkeypatch.setattr(monitor_history, "_folder", lambda: blocked / "monitor")

        _record("gemma4", ms=1200, output_tokens=60)
        assert llm_performance.HISTORY.flush() is False

        monkeypatch.setattr(monitor_history, "_folder", lambda: folder)
        assert _sums("gemma4") == {"requests": 1, "failed": 0, "ms": 1200, "firstTokenMs": 0, "firstTokens": 0,
                                   "outputTokens": 60, "outputMs": 1200}


class TestModelNames:
    @pytest.mark.parametrize("name", [
        "gemma4", "scripted", "gpt-4.1", "claude-sonnet-4-5", "claude-3-5-sonnet@20240620",
        "models/gemini-2.5-pro", "meta-llama/Llama-3.1-8B-Instruct",
        "us.anthropic.claude-3-5-sonnet-20241022-v2:0", "llama3.1:8b", "qwen2.5-coder:32b",
    ])
    def test_a_model_id_is_shown_as_it_is(self, name):
        assert llm_performance.public_model_name(name) == name

    @pytest.mark.parametrize("name", [
        "https://llm.example.com/v1", "http://localhost:11434", "www.example.com",
        "llm.example.com", "llm.example.com:8443", "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF",
        "localhost", "localhost:11434", "gpu-box:8000", "alice@example.org",
        "10.0.0.1", "10.0.0.1:8000", "fe80::1",
        "sk-proj-abcdef123456", "AIzaSyD-abcdefghijklmnopqrstuvwxyz012", "0123456789abcdef0123456789abcdef",
        "gemma 4", "a" * 101, "", None,
    ])
    def test_a_name_that_is_not_plainly_a_model_is_other(self, name):
        assert llm_performance.public_model_name(name) == llm_performance.OTHER

    def test_an_address_named_as_a_model_is_recorded_as_other(self, clock):
        for named in ("alice@example.org", "https://llm.example.com/v1", "10.0.0.1"):
            _record(named, ms=100)
        assert {model: entry["requests"] for model, entry in _models().items()} == {"other": 3}
        assert _sums("other")["ms"] == 300
        written = llm_performance.HISTORY.path().read_text(encoding="utf-8")
        assert "example" not in written and "10.0.0.1" not in written

    def test_a_day_holds_at_most_its_cap_of_models(self, clock, monkeypatch):
        monkeypatch.setattr(llm_performance, "MAX_MODELS_PER_DAY", 3)
        for name in ("m1", "m2", "m3", "m4", "m5"):
            _record(name)
        # A model the day holds still counts as itself.
        _record("m1")
        assert {model: entry["requests"] for model, entry in _models().items()} == {
            "m1": 2, "m2": 1, "m3": 1, "other": 2,
        }

    def test_the_cap_counts_the_models_the_file_holds_whichever_write_brought_them(self, clock, monkeypatch):
        """Each process writes what it holds every minute, so a day's models
        come in many writes, by many processes: the cap is the day's in the
        file, not one write's."""
        monkeypatch.setattr(llm_performance, "MAX_MODELS_PER_DAY", 3)
        for name in ("m1", "m2"):
            _record(name)
        _written()
        clock.at = NOW + timedelta(hours=2)
        for name in ("m3", "m4", "m1", "m5"):
            _record(name)
        assert {model: entry["requests"] for model, entry in _models().items()} == {
            "m1": 2, "m2": 1, "m3": 1, "other": 2,
        }
        # The next day holds three of its own.
        clock.at = NOW + timedelta(days=1)
        _record("m4")
        assert _models()["m4"]["requests"] == 1

    def test_the_route_lists_the_models_with_most_requests_and_sums_the_rest(self, clock, monkeypatch):
        monkeypatch.setattr(llm_performance, "MAX_MODELS_SHOWN", 2)
        for name, requests in (("big", 4), ("mid", 3), ("small", 1), ("tiny", 1)):
            for _ in range(requests):
                _record(name, ms=100)
        _written()
        body = llm_performance.snapshot()
        for name in ("24h", "7d", "90d"):
            view = body["views"][name]
            assert [(entry["model"], entry["requests"]) for entry in view["models"]] == [
                ("big", 4), ("mid", 3), ("other", 2)], name
            assert [(row["model"], row["requests"], row["ms"]) for row in view["rows"]] == [
                ("big", 4, 400), ("mid", 3, 300), ("other", 2, 200)], name


# -- the hook in providers.py -----------------------------------------------------

class TestEachRequestOnCuriosEndpointCountsOnce:
    @pytest.fixture(autouse=True)
    def _fresh_endpoints(self, monkeypatch):
        """No endpoint seen thinking or refusing the room, whatever ran before."""
        monkeypatch.setattr(providers, "_thinking_endpoints", set())
        monkeypatch.setattr(providers, "_room_refused", set())
        testing_provider.reset()
        yield
        testing_provider.reset()

    @staticmethod
    def _streaming(monkeypatch, closed: list, timer: _Timer):
        """A server that reports its usage as it streams, as vLLM's continuous
        usage stats do: what it has counted so far comes with each piece."""

        def one_stream(config, messages, max_output_tokens, usage_out, tools, tool_choice, finish):
            try:
                timer.wait(0.25)
                usage_out.update(inputTokens=500, outputTokens=1)
                yield "The "
                timer.wait(0.25)
                usage_out.update(inputTokens=500, outputTokens=2)
                yield "parks "
                timer.wait(0.5)
                usage_out.update(inputTokens=500, outputTokens=40)
                yield "are in the loader."
                finish["reason"] = "stop"
            finally:
                closed.append(True)

        monkeypatch.setattr(providers, "_one_stream", one_stream)

    def test_a_request_on_a_key_a_user_set_for_their_own_records_nothing(self, clock, timer, monkeypatch):
        """A whole turn, a stream, a scripted turn and a failed one: each
        answers its caller as before, and the monitor holds nothing of any."""
        own = ProviderConfig(api_key="k", api_type="openai_compatible", base_url="", model="own-model")

        def one_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema):
            timer.wait(1.0)
            usage_out.update(inputTokens=7, outputTokens=3)
            return ChatTurn(text="Whole.", stop_reason="stop")

        monkeypatch.setattr(providers, "_one_turn", one_turn)
        whole: dict = {}
        assert providers.run_chat_turn(own, ASKED, 4096, whole).text == "Whole."
        closed: list = []
        self._streaming(monkeypatch, closed, timer)
        streamed: dict = {}
        assert "".join(providers.stream_chat_turn(own, ASKED, 4096, streamed)) == "The parks are in the loader."
        scripted = ProviderConfig(api_key="", api_type="testing", base_url="", model="own-scripted")
        testing_provider.push_reply("Scripted.", usage={"in": 11, "out": 5})
        assert providers.run_chat_turn(scripted, ASKED).text == "Scripted."

        def down(*_asked):
            raise RuntimeError("the model's server is down")

        monkeypatch.setattr(providers, "_one_turn", down)
        with pytest.raises(RuntimeError):
            providers.run_chat_turn(own, ASKED, 4096)

        assert (whole, streamed) == ({"inputTokens": 7, "outputTokens": 3}, {"inputTokens": 500, "outputTokens": 40})
        _written()
        assert llm_performance.HISTORY.rows() == []
        assert [_view(name)["models"] for name in ("24h", "7d", "90d")] == [[], [], []]

    def test_a_whole_request_is_timed_from_before_it_was_asked_to_its_end(self, clock, timer, monkeypatch):
        config = ProviderConfig(api_key="k", api_type="openai_compatible", base_url="", model="monitor-timed",
                                on_deployment=True)

        def one_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema):
            timer.wait(1.5)
            usage_out.update(inputTokens=400, outputTokens=60)
            return ChatTurn(text="The reply.", stop_reason="stop")

        monkeypatch.setattr(providers, "_one_turn", one_turn)
        usage: dict = {}
        timer.wait(10)  # before the request: not its time
        assert providers.run_chat_turn(config, ASKED, 4096, usage).text == "The reply."
        timer.wait(10)  # after it: nor this

        assert usage == {"inputTokens": 400, "outputTokens": 60}
        assert _sums("monitor-timed") == {"requests": 1, "failed": 0, "ms": 1500, "firstTokenMs": 0,
                                          "firstTokens": 0, "outputTokens": 60, "outputMs": 1500}
        # 60 output tokens in 1.5 s; no first token, as the turn was not streamed.
        assert _models("24h")["monitor-timed"] == {
            "model": "monitor-timed", "requests": 1, "failed": 0, "averageMs": 1500, "p95Ms": 2425,
            "firstTokenMs": None, "tokensPerSecond": 40.0,
        }

    def test_a_streams_first_token_is_its_first_word(self, clock, timer, monkeypatch):
        """Stamped as the word comes out of the stream, before its caller has
        it: a blank piece is no word, and the caller's time with the word is
        in the stream's time, which runs to its end, not in its first token's."""
        config = ProviderConfig(api_key="k", api_type="openai_compatible", base_url="", model="monitor-first-word",
                                on_deployment=True)

        def one_stream(config, messages, max_output_tokens, usage_out, tools, tool_choice, finish):
            timer.wait(0.25)
            yield "  "
            timer.wait(0.5)
            yield "The "
            timer.wait(1.25)
            usage_out.update(inputTokens=500, outputTokens=40)
            yield "parks are in the loader."
            finish["reason"] = "stop"

        monkeypatch.setattr(providers, "_one_stream", one_stream)
        usage: dict = {}
        events = providers.stream_chat_turn(config, ASKED, 4096, usage)
        assert [next(events), next(events)] == ["  ", "The "]
        timer.wait(2)
        assert list(events) == ["parks are in the loader."]

        assert usage == {"inputTokens": 500, "outputTokens": 40}
        assert _sums("monitor-first-word") == {"requests": 1, "failed": 0, "ms": 4000, "firstTokenMs": 750,
                                               "firstTokens": 1, "outputTokens": 40, "outputMs": 4000}
        assert _models("24h")["monitor-first-word"] == {
            "model": "monitor-first-word", "requests": 1, "failed": 0, "averageMs": 4000, "p95Ms": 4875,
            "firstTokenMs": 750, "tokensPerSecond": 10.0,
        }

    def test_a_streams_first_call_is_its_first_token_too(self, clock, timer, monkeypatch):
        config = ProviderConfig(api_key="k", api_type="openai_compatible", base_url="", model="monitor-first-call",
                                on_deployment=True)

        def one_stream(config, messages, max_output_tokens, usage_out, tools, tool_choice, finish):
            timer.wait(0.5)
            yield ToolCall("call-1", "dataflow.read", {})
            timer.wait(0.5)
            finish["reason"] = "tool_calls"

        monkeypatch.setattr(providers, "_one_stream", one_stream)
        tools = [{"name": "dataflow.read", "description": "Read the dataflow.", "parameters": {"type": "object"}}]
        events = list(providers.stream_chat_turn(config, ASKED, 4096, {}, tools=tools))

        assert events == [ToolCall("call-1", "dataflow.read", {})]
        assert _sums("monitor-first-call") == {"requests": 1, "failed": 0, "ms": 1000, "firstTokenMs": 500,
                                               "firstTokens": 1, "outputTokens": 0, "outputMs": 0}

    def test_a_request_that_raised_counts_as_failed_with_its_time(self, clock, timer, monkeypatch):
        config = ProviderConfig(api_key="k", api_type="openai_compatible", base_url="", model="monitor-raised",
                                on_deployment=True)

        def one_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema):
            timer.wait(0.5)
            raise RuntimeError("the model's server is down")

        def one_stream(config, messages, max_output_tokens, usage_out, tools, tool_choice, finish):
            timer.wait(0.25)
            yield "The "
            timer.wait(1.0)
            raise RuntimeError("the connection dropped")

        monkeypatch.setattr(providers, "_one_turn", one_turn)
        monkeypatch.setattr(providers, "_one_stream", one_stream)
        with pytest.raises(RuntimeError, match="server is down"):
            providers.run_chat_turn(config, ASKED, 4096)
        events = providers.stream_chat_turn(config, ASKED, 4096)
        assert next(events) == "The "
        with pytest.raises(RuntimeError, match="connection dropped"):
            next(events)

        assert _sums("monitor-raised") == {"requests": 2, "failed": 2, "ms": 1750, "firstTokenMs": 250,
                                           "firstTokens": 1, "outputTokens": 0, "outputMs": 0}
        stats = _models("24h")["monitor-raised"]
        assert (stats["requests"], stats["failed"], stats["averageMs"], stats["tokensPerSecond"]) == (2, 2, 875, None)

    def test_a_turn_asked_again_counts_each_request_once(self, clock, timer, monkeypatch):
        """A reply the cap cut before a word is asked again with room for
        thinking: two requests, each counted as it was, never their sum
        again on top of the first."""
        config = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="monitor-asked-again",
                                on_deployment=True)
        replies = iter([
            (0.5, {"inputTokens": 100, "outputTokens": 32}, ChatTurn(text="", stop_reason="max_tokens")),
            (1.0, {"inputTokens": 100, "outputTokens": 50}, ChatTurn(text="The reply.", stop_reason="end_turn")),
        ])
        limits = []

        def one_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema):
            limits.append(max_output_tokens)
            seconds, usage, turn = next(replies)
            timer.wait(seconds)
            usage_out.update(usage)
            return turn

        monkeypatch.setattr(providers, "_one_turn", one_turn)
        usage: dict = {}
        turn = providers.run_chat_turn(config, ASKED, 32, usage, thinking_tokens=1024)

        assert (turn.text, limits) == ("The reply.", [32, 32 + 1024])
        assert usage == {"inputTokens": 200, "outputTokens": 82}
        assert _sums("monitor-asked-again") == {"requests": 2, "failed": 0, "ms": 1500, "firstTokenMs": 0,
                                                "firstTokens": 0, "outputTokens": 82, "outputMs": 1500}

    def test_a_request_refused_with_room_counts_nothing_and_its_second_counts(self, clock, timer, monkeypatch):
        """The endpoint refused the room (400): Curio asks again without it,
        so the refusal counts nothing, and the request asked again counts as
        it was."""
        config = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="monitor-room-refused",
                                on_deployment=True)
        monkeypatch.setattr(providers, "_thinking_endpoints", {providers._endpoint(config)})

        class Refused(Exception):
            status_code = 400

        limits = []

        def one_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema):
            limits.append(max_output_tokens)
            if len(limits) == 1:
                timer.wait(0.25)
                raise Refused("max_tokens is too large for this context window")
            timer.wait(1.0)
            usage_out.update(inputTokens=90, outputTokens=12)
            return ChatTurn(text="The reply.", stop_reason="end_turn")

        monkeypatch.setattr(providers, "_one_turn", one_turn)
        usage: dict = {}
        turn = providers.run_chat_turn(config, ASKED, 32, usage, thinking_tokens=1024)

        assert (turn.thinking_room_refused, limits) == (True, [32 + 1024, 32])
        assert usage == {"inputTokens": 90, "outputTokens": 12}
        assert _sums("monitor-room-refused") == {"requests": 1, "failed": 0, "ms": 1000, "firstTokenMs": 0,
                                                 "firstTokens": 0, "outputTokens": 12, "outputMs": 1000}

    def test_a_request_refused_for_its_tools_counts_nothing(self, clock, timer, monkeypatch):
        """An endpoint that refuses the offered tools (422) raises
        NativeToolsRefused, and Curio asks again without them: the refusal
        counts nothing."""
        config = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="monitor-tools-refused",
                                on_deployment=True)

        class Refused(Exception):
            status_code = 422

        def one_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema):
            timer.wait(0.25)
            raise Refused("tools are not supported by this model")

        monkeypatch.setattr(providers, "_one_turn", one_turn)
        tools = [{"name": "look", "description": "Look at the loader.", "parameters": {"type": "object"}}]
        with pytest.raises(providers.NativeToolsRefused):
            providers.run_chat_turn(config, ASKED, 4096, tools=tools)

        assert _sums("monitor-tools-refused") == dict.fromkeys(SUMS, 0)

    def test_a_server_error_counts_as_failed(self, clock, timer, monkeypatch):
        """Only a refusal (400 or 422) counts nothing: a server's error, such
        as a 503 while the model loads, is a failed request with its time."""
        config = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="monitor-unavailable",
                                on_deployment=True)

        class Unavailable(Exception):
            status_code = 503

        def one_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema):
            timer.wait(0.5)
            raise Unavailable("the model is loading")

        monkeypatch.setattr(providers, "_one_turn", one_turn)
        tools = [{"name": "look", "description": "Look at the loader.", "parameters": {"type": "object"}}]
        with pytest.raises(Unavailable):
            providers.run_chat_turn(config, ASKED, 4096, tools=tools)

        assert _sums("monitor-unavailable") == {"requests": 1, "failed": 1, "ms": 500, "firstTokenMs": 0,
                                                "firstTokens": 0, "outputTokens": 0, "outputMs": 0}

    def test_a_stream_its_caller_stopped_counts_what_its_provider_had_reported_and_did_not_fail(
            self, clock, timer, monkeypatch):
        closed: list = []
        self._streaming(monkeypatch, closed, timer)
        config = ProviderConfig(api_key="k", api_type="openai_compatible", base_url="", model="monitor-stopped",
                                on_deployment=True)
        usage: dict = {}

        events = providers.stream_chat_turn(config, ASKED, 4096, usage)
        assert next(events) == "The "
        events.close()

        assert closed == [True]
        assert usage == {"inputTokens": 500, "outputTokens": 1}
        assert _sums("monitor-stopped") == {"requests": 1, "failed": 0, "ms": 250, "firstTokenMs": 250,
                                            "firstTokens": 1, "outputTokens": 1, "outputMs": 250}

    def test_a_whole_stream_counts_its_last_report_once(self, clock, timer, monkeypatch):
        closed: list = []
        self._streaming(monkeypatch, closed, timer)
        config = ProviderConfig(api_key="k", api_type="openai_compatible", base_url="", model="monitor-whole",
                                on_deployment=True)
        usage: dict = {}
        finish: dict = {}

        assert "".join(providers.stream_chat_turn(config, ASKED, 4096, usage, finish=finish)) == (
            "The parks are in the loader.")

        assert finish["reason"] == "stop"
        assert usage == {"inputTokens": 500, "outputTokens": 40}
        assert _sums("monitor-whole") == {"requests": 1, "failed": 0, "ms": 1000, "firstTokenMs": 250,
                                          "firstTokens": 1, "outputTokens": 40, "outputMs": 1000}

    def test_the_scripted_provider_counts_each_turn_on_both_paths(self, clock, timer):
        config = ProviderConfig(api_key="", api_type="testing", base_url="", model="scripted-monitor",
                                on_deployment=True)
        testing_provider.push_reply("Whole.", usage={"in": 7, "out": 3})
        testing_provider.push_reply("Streamed.", usage={"in": 11, "out": 5})
        whole: dict = {}
        streamed: dict = {}

        assert providers.run_chat_turn(config, ASKED, usage_out=whole).text == "Whole."
        assert list(providers.stream_chat_turn(config, ASKED, usage_out=streamed)) == ["Streamed."]

        assert (whole, streamed) == ({"inputTokens": 7, "outputTokens": 3}, {"inputTokens": 11, "outputTokens": 5})
        # Its whole reply comes at once, before any of it is yielded: no first token.
        assert _sums("scripted-monitor") == {"requests": 2, "failed": 0, "ms": 0, "firstTokenMs": 0,
                                             "firstTokens": 0, "outputTokens": 8, "outputMs": 0}

    def test_a_scripted_call_that_fails_counts_as_failed_on_curios_endpoint_and_nothing_on_an_own_key(
            self, clock, timer):
        for model, on_deployment in (("scripted-own", False), ("scripted-curio", True)):
            config = ProviderConfig(api_key="", api_type="testing", base_url="", model=model,
                                    on_deployment=on_deployment)
            testing_provider.push_reply({"error": "the model's server is down", "status": 503})
            usage: dict = {}
            with pytest.raises(testing_provider.ScriptedEndpointError):
                providers.run_chat_turn(config, ASKED, usage_out=usage)
            # A failed call is not charged, so it reports no usage.
            assert usage == {}, model

        _written()
        assert [row["model"] for row in llm_performance.HISTORY.rows()] == ["scripted-curio"]
        assert _sums("scripted-curio") == {"requests": 1, "failed": 1, "ms": 0, "firstTokenMs": 0,
                                           "firstTokens": 0, "outputTokens": 0, "outputMs": 0}
