"""The monitor's Usage tab (``monitor/usage.py``, ``monitor/requests.py``):
what this Curio did for the people using it, kept across restarts.

The record: each measure adds a row of sums for its 5 minutes, which each view
reads back (the last 24 hours in 5-minute steps, 7 days hourly, 90 days daily:
count, failures, average and 95th percentile time, the percentile read from
the duration buckets), a restart keeps, and two processes add up exactly. The
recording points: a node's run as Play runs it (Python, JavaScript, and one
whose download failed), a run on the server and a dashboard viewer's, an
agent's turn, and each request the backend answers but those it leaves out
(Socket.IO never reaches the app). The sessions seen, sampled after each 5
minutes for its slot, its hour and its UTC day, accounts and guests apart,
and read back per step. Each start, and the deploys among them.

Each test's history files are in a folder of its own (``conftest.py``), and the
clock is the test's (``usage._now``), so no test crosses a 5-minute slot as it
runs. The route reads the files, so a test writes what the process holds
(:func:`_written`), as the process's writer does each minute.
"""

from __future__ import annotations

import json
import time
import types
from datetime import datetime, timedelta, timezone

import pytest
from flask import Response, request

import utk_curio
from utk_curio.backend.app.monitor import durations
from utk_curio.backend.app.monitor import history as monitor_history
from utk_curio.backend.app.monitor import requests as monitor_requests
from utk_curio.backend.app.monitor import usage

UTC = timezone.utc
NOW = datetime(2026, 11, 6, 15, 20, 7, tzinfo=UTC)
#: A sessions sample that saw nobody.
NOBODY = {"accounts5m": 0, "guests5m": 0, "accounts1h": 0, "guests1h": 0, "accountsDay": 0, "guestsDay": 0}


@pytest.fixture()
def clock(monkeypatch):
    """The monitor's clock, which a test moves with ``clock.at = ...``."""
    state = types.SimpleNamespace(at=NOW)
    monkeypatch.setattr(usage, "_now", lambda: state.at)
    return state


def _buckets(**placed) -> list[int]:
    """Bucket counts with *placed* counts, by bucket number (``b0`` to ``b13``)."""
    out = [0] * durations.BUCKETS
    for name, count in placed.items():
        out[int(name[1:])] = count
    return out


def _written() -> None:
    """What this process holds of the measures, written into the file, as the
    process's writer does each minute."""
    assert usage.HISTORY.flush() is True


def _view(name: str, body: dict | None = None) -> dict:
    """The route's view *name* (``24h``, ``7d`` or ``90d``): of *body*, else of
    the route once what the process holds is written."""
    if body is None:
        _written()
        body = usage.snapshot()
    return body["views"][name]


def _measures(name: str = "90d", body: dict | None = None) -> dict:
    """A view's measures by key."""
    return {each["key"]: each for each in _view(name, body)["measures"]}


def _rows_of(key: str) -> list[dict]:
    """The file's rows of *key*, once what the process holds is written."""
    _written()
    return [row for row in usage.HISTORY.rows() if row["key"] == key]


# -- the record ---------------------------------------------------------------------

def test_each_measure_adds_up_in_its_5_minutes_and_reads_back_in_every_view(clock):
    usage.record("node.python", ms=1200)
    clock.at = NOW + timedelta(minutes=2)
    usage.record("node.python", ms=800, failed=True)
    usage.record("run", ms=4000)
    usage.record("turn", ms=15000, failed=True)
    usage.record("request", ms=40)

    _written()
    path = usage.HISTORY.path()
    assert path == monitor_history._folder() / "usage.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert (doc["name"], doc["format"]) == ("usage", 2)
    assert doc["rows"] == usage.HISTORY.rows() == [
        {"at": "2026-11-06T15:20:00Z", "span": "5m", "key": "node.python", "count": 2, "failed": 1, "ms": 2000,
         "buckets": _buckets(b4=1, b5=1)},
        {"at": "2026-11-06T15:20:00Z", "span": "5m", "key": "run", "count": 1, "failed": 0, "ms": 4000,
         "buckets": _buckets(b6=1)},
        {"at": "2026-11-06T15:20:00Z", "span": "5m", "key": "turn", "count": 1, "failed": 1, "ms": 15000,
         "buckets": _buckets(b8=1)},
        {"at": "2026-11-06T15:20:00Z", "span": "5m", "key": "request", "count": 1, "failed": 0, "ms": 40,
         "buckets": _buckets(b0=1)},
    ]
    # Sums alone, each a whole number, which every write adds up exactly.
    for row in doc["rows"]:
        assert all(type(row[field]) is int for field in ("count", "failed", "ms")), row
        assert all(type(count) is int for count in row["buckets"]), row

    view = _view("24h")
    # Every measure, in the page's order, one nothing counted among them. The
    # 95th percentile is read from the buckets: 1,000 to 2,500 ms holds the
    # Python runs' rank, 1.9 of their 2.
    assert view["measures"] == [
        {"key": "node.python", "count": 2, "failed": 1, "ms": 2000, "averageMs": 1000, "p95Ms": 2350},
        {"key": "node.javascript", "count": 0, "failed": 0, "ms": 0, "averageMs": None, "p95Ms": None},
        {"key": "run", "count": 1, "failed": 0, "ms": 4000, "averageMs": 4000, "p95Ms": 4875},
        {"key": "turn", "count": 1, "failed": 1, "ms": 15000, "averageMs": 15000, "p95Ms": 29000},
        {"key": "request", "count": 1, "failed": 0, "ms": 40, "averageMs": 40, "p95Ms": 48},
    ]
    assert [(row["at"], row["key"], row["count"], row["failed"], row["ms"], row["p95Ms"]) for row in view["rows"]] == [
        ("2026-11-06T15:20:00Z", "node.python", 2, 1, 2000, 2350),
        ("2026-11-06T15:20:00Z", "run", 1, 0, 4000, 4875),
        ("2026-11-06T15:20:00Z", "turn", 1, 1, 15000, 29000),
        ("2026-11-06T15:20:00Z", "request", 1, 0, 40, 48),
    ]
    # The same work in every view.
    assert _view("7d")["measures"] == _view("90d")["measures"] == view["measures"]


def test_each_view_reads_its_own_rows_and_says_where_it_starts_and_ends(clock):
    """Rows on both sides of each view's start, oldest recorded first, as time runs."""
    seen = [
        (datetime(2026, 8, 8, 23, 20, tzinfo=UTC), 1),  # kept, the day before the 90 days
        (datetime(2026, 8, 9, 0, 0, 30, tzinfo=UTC), 10),  # the first of the 90 days
        (NOW - timedelta(hours=168), 100),  # an hour before the 7 days
        (NOW - timedelta(hours=167), 1000),  # in the first of the 7 days' hours
        (datetime(2026, 11, 5, 15, 24, 59, tzinfo=UTC), 10000),  # before the 24 hours
        (datetime(2026, 11, 5, 15, 25, tzinfo=UTC), 100000),  # the first of the 24 hours' slots
        (NOW, 1000000),
        (NOW + timedelta(minutes=10), 5),  # past now, as a clock set back dates it
    ]
    for at, ms in seen:
        clock.at = at
        usage.record("turn", ms=ms)
    clock.at = NOW

    _written()
    views = usage.snapshot()["views"]
    assert [(name, view["from"], view["to"], view["stepSeconds"]) for name, view in views.items()] == [
        ("24h", "2026-11-05T15:25:00Z", "2026-11-06T15:20:00Z", 300),
        ("7d", "2026-10-30T16:00:00Z", "2026-11-06T15:00:00Z", 3600),
        ("90d", "2026-08-09T00:00:00Z", "2026-11-06T00:00:00Z", 86400),
    ]
    assert [(row["at"], row["count"], row["ms"]) for row in views["24h"]["rows"]] == [
        ("2026-11-05T15:25:00Z", 1, 100000),
        ("2026-11-06T15:20:00Z", 1, 1000000),
    ]
    assert [(row["at"], row["count"], row["ms"]) for row in views["7d"]["rows"]] == [
        ("2026-10-30T16:00:00Z", 1, 1000),
        ("2026-11-05T15:00:00Z", 2, 110000),
        ("2026-11-06T15:00:00Z", 1, 1000000),
    ]
    assert [(row["at"], row["count"], row["ms"]) for row in views["90d"]["rows"]] == [
        ("2026-08-09T00:00:00Z", 1, 10),
        ("2026-10-30T00:00:00Z", 2, 1100),
        ("2026-11-05T00:00:00Z", 2, 110000),
        ("2026-11-06T00:00:00Z", 1, 1000000),
    ]
    # Each view's table reads the rows its charts draw.
    for name, view in views.items():
        turns = _measures(name, {"views": views})["turn"]
        assert turns["count"] == sum(row["count"] for row in view["rows"]), name
        assert turns["ms"] == sum(row["ms"] for row in view["rows"]), name


def test_the_95th_percentile_is_read_from_the_buckets_interpolated_in_the_one_that_holds_it(clock):
    for _ in range(10):
        usage.record("request", ms=40)  # 0 to 50 ms
    for _ in range(10):
        usage.record("request", ms=700)  # 500 ms to 1 s
    requests = _measures("24h")["request"]
    # The rank is 19 of 20: the 9th of the 10 between 500 ms and 1 s, 0.9 of
    # the way through it.
    assert (requests["count"], requests["averageMs"], requests["p95Ms"]) == (20, 370, 950)
    assert [row["p95Ms"] for row in _view("24h")["rows"]] == [950]

    # A rank in the last bucket, past 600 s, reads as its lower bound.
    usage.record("run", ms=900_000)
    assert _measures("24h")["run"]["p95Ms"] == 600_000


def test_the_rows_are_kept_across_a_restart(clock):
    from utk_curio.backend.app import create_app
    from utk_curio.backend.tests._unit_fixtures import TestConfig

    usage.record("node.python", ms=1200)
    usage.record("request", ms=40, failed=True)
    kept = _measures()
    assert (kept["node.python"]["count"], kept["request"]["failed"]) == (1, 1)
    path = usage.HISTORY.path()
    before = path.read_bytes()

    create_app(TestConfig)
    usage.reset()  # the cache and what the process held, as a new process starts

    assert path.read_bytes() == before
    assert _measures() == kept


def test_two_processes_adding_at_once_sum_exactly(clock, monkeypatch):
    """A forked process writes its measures and stops after its read of the
    file, inside the file's lock; this process's write then waits for the
    lock, and reads what the other wrote. Every field is a sum."""
    from utk_curio.backend.tests._support.two_processes import Window, race

    window = Window()
    read = monitor_history._read_to_write

    def _read_then_stop(each, path, now):
        rows = read(each, path, now)
        window.stop_here()
        return rows

    monkeypatch.setattr(monitor_history, "_read_to_write", _read_then_stop)

    def in_the_other_process():
        usage.record("request", ms=40)
        usage.record("request", ms=700, failed=True)
        assert usage.HISTORY.flush() is True

    def here():
        for ms in (40, 40, 3000):
            usage.record("request", ms=ms)
        return usage.HISTORY.flush()

    raced = race(window, in_the_other_process, here, monkeypatch)

    assert raced.child_exit == 0, raced.child_error
    assert raced.here is True
    assert usage.HISTORY.rows() == [
        {"at": "2026-11-06T15:20:00Z", "span": "5m", "key": "request", "count": 5, "failed": 1, "ms": 3820,
         "buckets": _buckets(b0=3, b4=1, b6=1)},
    ]


def test_a_measure_that_is_not_one_counts_nothing_and_a_time_that_is_not_one_reads_as_0_ms(clock):
    """Never raised: whatever a caller hands it."""
    usage.record("node.r", ms=100)
    usage.record("request", ms="soon")
    usage.record("request", ms=-5, failed=True)
    _written()
    assert usage.HISTORY.rows() == [
        {"at": "2026-11-06T15:20:00Z", "span": "5m", "key": "request", "count": 2, "failed": 1, "ms": 0,
         "buckets": _buckets(b0=2)},
    ]


def test_the_route_answers_its_documented_keys(client, clock):
    usage.record("node.python", ms=1200)
    assert usage.record_start("0.17.400") is True
    _written()
    body = client.get("/api/monitor/usage").get_json()

    assert set(body) == {"computedAt", "maxDays", "measures", "sessionsLast24h", "views", "ageSeconds", "ttlSeconds"}
    assert (body["computedAt"], body["maxDays"], body["ttlSeconds"]) == ("2026-11-06T15:20:07Z", 90, 60)
    assert body["measures"] == list(usage.MEASURES)
    assert body["sessionsLast24h"] == {"accounts": 0, "guests": 0}
    assert list(body["views"]) == ["24h", "7d", "90d"]
    for name, view in body["views"].items():
        assert set(view) == {"from", "to", "stepSeconds", "rows", "measures", "sessions", "deploys"}, name
        assert [set(row) for row in view["rows"]] == [{"at", "key", "count", "failed", "ms", "p95Ms"}], name
        assert [each["key"] for each in view["measures"]] == list(usage.MEASURES), name
        for each in view["measures"]:
            assert set(each) == {"key", "count", "failed", "ms", "averageMs", "p95Ms"}, each
        assert view["deploys"] == [{"at": "2026-11-06T15:20:07Z", "version": "0.17.400"}], name
        assert view["sessions"] == [], name


# -- what is counted where ------------------------------------------------------------

class _Reply:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _sandbox(monkeypatch, output: dict, *, seconds: float = 0.0) -> None:
    """The sandbox behind ``node_exec``: it takes *seconds* and answers with
    *output*, with a traceback when the output names no file."""

    def answer(method, path, **kwargs):
        time.sleep(seconds)
        stderr = "" if output.get("path") else "Traceback (most recent call last):\nValueError: boom"
        return _Reply({"stdout": [], "stderr": stderr, "output": output})

    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", answer)


@pytest.fixture()
def signed_in(app, db):
    """An account of its own and its sign-in: ``(user, token)``."""
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username="usage-alice", name="Usage Alice", email="usage-alice@test.invalid")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token="usage-alice-token"))
    db.session.commit()
    return user, "usage-alice-token"


def test_a_python_node_counts_once_with_its_time_and_one_that_failed_as_failed(clock, signed_in, tmp_curio,
                                                                              monkeypatch):
    from utk_curio.backend.app.execution import node_exec

    user, token = signed_in
    _sandbox(monkeypatch, {"path": "art-usage", "dataType": "int"}, seconds=0.05)
    reply, status = node_exec.execute_python_node(user, token, node_exec.NodeRun(code="    return 1",
                                                                                 node_type="DATA_LOADING"))
    assert (status, reply["output"]["path"]) == (200, "art-usage")
    _sandbox(monkeypatch, {"path": "", "dataType": "str"})
    reply, status = node_exec.execute_python_node(user, token, node_exec.NodeRun(code="    raise ValueError('boom')",
                                                                                 node_type="DATA_LOADING"))
    assert (status, reply["output"]["path"]) == (200, "")

    (python,) = _rows_of("node.python")
    assert (python["count"], python["failed"]) == (2, 1)
    # From the call's start to its reply: the sandbox's 50 ms and more.
    assert python["ms"] >= 50, python
    assert [row["key"] for row in usage.HISTORY.rows()] == ["node.python"]


def test_a_javascript_node_counts_as_a_measure_of_its_own(clock, signed_in, tmp_curio, monkeypatch):
    from utk_curio.backend.app.execution import node_exec

    user, token = signed_in
    _sandbox(monkeypatch, {"path": "art-js", "dataType": "int"})
    reply, status = node_exec.execute_js_node(user, token, node_exec.NodeRun(code="return 42;",
                                                                             node_type="JS_COMPUTATION"))
    assert (status, reply["output"]["path"]) == (200, "art-js")

    _written()
    assert [(row["key"], row["count"], row["failed"]) for row in usage.HISTORY.rows()] == [("node.javascript", 1, 0)]


def test_a_python_node_whose_download_failed_counts_as_failed(clock, signed_in, tmp_curio, monkeypatch):
    """A file Curio downloads on first use that could not be downloaded fails
    the run before the sandbox is asked: it counts all the same."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.app.execution import node_exec

    user, token = signed_in
    asked = []

    def no_download(code, dataflow_id, account, formats=None):
        left_out_files.unavailable("datasets/usage.probe@1/data/probe.csv", "probe.csv could not be downloaded")
        return {}

    def sandbox(method, path, **kwargs):
        asked.append(path)

    monkeypatch.setattr(node_exec, "resolve_dataset_paths", no_download)
    monkeypatch.setattr(node_exec, "sandbox_request", sandbox)
    reply, status = node_exec.execute_python_node(user, token, node_exec.NodeRun(code="    return 1",
                                                                                 node_type="DATA_LOADING"))

    assert (status, asked) == (200, [])
    assert "probe.csv could not be downloaded" in reply["stderr"]
    assert [(row["count"], row["failed"]) for row in _rows_of("node.python")] == [(1, 1)]


def _ending(status: str | None = None, *, raises: Exception | None = None, seconds: float = 0.0):
    """The engine's events of a run that takes *seconds*, then ends *status*,
    or raises *raises*."""

    def run_events(plan, execute, cancelled=None, wrap=None):
        time.sleep(seconds)
        if raises is not None:
            raise raises
        yield "run_started", {"nodeIds": []}
        yield "run_finished", {"status": status, "ok": 0, "failed": 0, "skipped": 0, "waiting": 0}

    return run_events


def test_a_run_on_the_server_counts_once_as_it_ends_and_failed_only_when_it_failed(app, clock, monkeypatch):
    """Every way a run ends: one waiting for the canvas and one cancelled did
    not fail; one that ended failed, and one the engine stopped with an
    error, did, each counted once."""
    from utk_curio.backend.app.execution import run_engine
    from utk_curio.backend.app.runs import service

    written = []

    def update_run(run_id, **fields):
        written.append((run_id, fields.get("status")))

    monkeypatch.setattr(service.runs_repo, "update_run", update_run)
    for status in ("succeeded", "needs_canvas", "cancelled", "failed"):
        monkeypatch.setattr(run_engine, "run_events", _ending(status, seconds=0.02))
        events = list(service._run_thread(app, f"run-{status}", 1, None, "usage-dataflow", None, None))
        assert events[-1][0] == "run_finished", events
    monkeypatch.setattr(run_engine, "run_events", _ending(raises=RuntimeError("the engine broke")))
    with pytest.raises(RuntimeError, match="the engine broke"):
        list(service._run_thread(app, "run-raised", 1, None, "usage-dataflow", None, None))

    (runs,) = _rows_of("run")
    assert (runs["count"], runs["failed"]) == (5, 2)
    # From each run's start to its end: four of 20 ms and more.
    assert runs["ms"] >= 80, runs
    assert ("run-raised", "failed") in written and ("run-failed", "failed") in written


def test_a_dashboard_viewers_run_counts_as_a_run(app, clock, monkeypatch):
    from utk_curio.backend.app.execution import run_engine
    from utk_curio.backend.app.runs import viewer

    def no_packages(user_key):
        return ""

    def no_sweep():
        return None

    monkeypatch.setattr(viewer, "packages_fingerprint", no_packages)
    monkeypatch.setattr(viewer, "prune_quietly", no_sweep)
    for status in ("succeeded", "failed"):
        monkeypatch.setattr(run_engine, "run_events", _ending(status))
        events = list(viewer._run_events(app, "usage-dataflow", 1, None, "owner-key"))
        assert events[-1][0] == "run_finished", events
    monkeypatch.setattr(run_engine, "run_events", _ending(raises=RuntimeError("the engine broke")))
    with pytest.raises(RuntimeError, match="the engine broke"):
        list(viewer._run_events(app, "usage-dataflow", 1, None, "owner-key"))

    assert [(row["count"], row["failed"]) for row in _rows_of("run")] == [(3, 2)]


def _ask():
    """An ask as ``turn_jobs`` keeps what its events change of it."""
    return types.SimpleNamespace(state="waiting", started_at=None, ended_at=None, text="", kept=[],
                                 execution_id=None, failure=None)


def _told(asked, event: str, data: dict, status=None) -> None:
    from utk_curio.backend.app.agents.application.turns import turn_jobs

    turn_jobs._keep(asked, {"seq": len(asked.kept), "event": event, "data": data}, status)


def test_a_turn_counts_once_from_its_start_to_its_end_and_a_withdrawn_ask_not_at_all(clock):
    done = _ask()
    _told(done, "started", {"startedAt": time.time() - 1.5})
    _told(done, "delta", {"text": "The parks"})
    _told(done, "done", {})
    failed = _ask()
    _told(failed, "started", {"startedAt": time.time() - 0.25})
    _told(failed, "error", {"error": "agent run failed: the model's server is down"}, 502)
    withdrawn = _ask()
    _told(withdrawn, "withdrawn", {"by": None})

    (turns,) = _rows_of("turn")
    assert (turns["count"], turns["failed"]) == (2, 1)
    # From each start to its end: a second and a half, and a quarter of a second.
    assert 1750 <= turns["ms"] < 1750 + 60_000, turns
    assert (withdrawn.state, withdrawn.started_at) == ("ended", None)


@pytest.fixture()
def probed(app):
    """The app with routes of the test's own, as any route answers: with a
    status it names, by raising (the catch-all's 500), after a wait, and as a
    stream. Added before the app's first request."""

    def answer(status):
        return {"status": status}, status

    def broken():
        raise RuntimeError("the usage probe broke")

    def slow():
        time.sleep(0.05)
        return {"slow": True}

    def streamed():
        return Response(iter(["data: 1\n\n", "data: 2\n\n"]), mimetype="text/event-stream")

    app.add_url_rule("/usage-probe/status/<int:status>", "usage_probe_status", answer)
    app.add_url_rule("/usage-probe/broken", "usage_probe_broken", broken)
    app.add_url_rule("/usage-probe/slow", "usage_probe_slow", slow)
    app.add_url_rule("/usage-probe/streamed", "usage_probe_streamed", streamed)
    return app.test_client()


def test_a_request_is_timed_to_its_response_and_a_5xx_counts_as_failed(probed, clock):
    assert probed.get("/usage-probe/slow").status_code == 200
    assert probed.get("/usage-probe/status/201").status_code == 201
    assert probed.get("/usage-probe/status/404").status_code == 404
    assert probed.get("/usage-probe/status/503").status_code == 503
    assert probed.get("/usage-probe/broken").status_code == 500
    assert probed.get("/usage-probe/no-such-route").status_code == 404

    (requests,) = _rows_of("request")
    # Six answers: the 503 and the route that raised failed, a 404 did not.
    assert (requests["count"], requests["failed"]) == (6, 2)
    # The slow route's 50 ms and more.
    assert requests["ms"] >= 50, requests
    assert [row["key"] for row in usage.HISTORY.rows()] == ["request"]


@pytest.mark.parametrize(("method", "path"), [
    ("OPTIONS", "/api/projects"),
    ("GET", "/api/monitor"),
    ("GET", "/api/monitor/usage"),
    ("POST", "/api/monitor/errors/client"),
    ("GET", "/version"),
    ("GET", "/health"),
    ("GET", "/live"),
    ("POST", "/internal/monitor/backend"),
    ("POST", "/internal/dataflows/413a5c1e/write"),
    ("POST", "/api/testing/monitor-flush"),
    ("GET", "/socket.io/"),
])
def test_a_request_the_measure_leaves_out(method, path):
    assert monitor_requests.counted(method, path) is False


@pytest.mark.parametrize(("method", "path"), [
    ("POST", "/processPythonCode"),
    ("GET", "/get"),
    ("GET", "/api/projects"),
    ("PUT", "/api/projects/413a5c1e"),
    ("GET", "/api/auth/me"),
    ("GET", "/api/monitoring"),
])
def test_a_request_the_measure_counts(method, path):
    assert monitor_requests.counted(method, path) is True


def test_through_the_app_a_request_left_out_counts_nothing(probed, clock):
    assert probed.options("/usage-probe/slow").status_code == 204
    assert probed.get("/api/monitor/usage").status_code == 200
    assert probed.get("/live").status_code == 200
    streamed = probed.get("/usage-probe/streamed")
    assert (streamed.status_code, streamed.get_data(as_text=True)) == (200, "data: 1\n\ndata: 2\n\n")
    probed.get("/api/testing/usage-probe")
    probed.post("/internal/monitor/usage-probe")

    _written()
    assert usage.HISTORY.rows() == []
    # Not vacuous: a request the measure counts.
    assert probed.get("/usage-probe/status/200").status_code == 200
    _written()
    assert [(row["key"], row["count"]) for row in usage.HISTORY.rows()] == [("request", 1)]


def test_socket_io_never_reaches_the_app_and_counts_nothing(app, probed, clock):
    """Flask-SocketIO wraps the app's WSGI callable in Engine.IO's, which
    answers ``/socket.io/`` itself: no hook of the app sees it."""
    reached = []

    def seen():
        reached.append(request.path)

    app.before_request(seen)
    handshake = probed.get("/socket.io/?EIO=4&transport=polling")
    assert handshake.status_code == 200, handshake.get_data(as_text=True)
    assert reached == []
    _written()
    assert usage.HISTORY.rows() == []
    # Not vacuous: a request the app answers.
    assert probed.get("/usage-probe/status/200").status_code == 200
    assert reached == ["/usage-probe/status/200"]


# -- the sessions ---------------------------------------------------------------------

@pytest.fixture()
def sign_ins(app, db):
    """Signs in an account or a guest, last seen when given: ``sign_in(who, seen)``."""
    from utk_curio.backend.app.users.models import User, UserSession

    account = User(username="usage-account", name="Usage Account", is_guest=False)
    guest = User(username="usage-guest", name="Usage Guest", is_guest=True)
    db.session.add_all([account, guest])
    db.session.flush()
    made = []

    def sign_in(who: str, seen) -> None:
        token = f"usage-sign-in-{len(made)}"
        owner = guest if who == "guest" else account
        # As a request stamps it (users/repositories.touch_session): aware UTC.
        db.session.add(UserSession(user_id=owner.id, token=token, last_seen_at=seen))
        db.session.commit()
        made.append(token)

    return sign_in


def test_a_sample_counts_the_sessions_of_its_5_minutes_its_hour_and_its_day_accounts_and_guests_apart(
        sign_ins, clock):
    """Rows on both sides of each bound. The bounds are naive UTC, as the
    column is stored, or nothing would match (``stats.py``'s timezone trap)."""
    for who, seen in (
        ("account", datetime(2026, 11, 6, 15, 21, tzinfo=UTC)),  # in the slot
        ("guest", datetime(2026, 11, 6, 15, 24, 30, tzinfo=UTC)),  # in the slot
        ("account", datetime(2026, 11, 6, 15, 10, tzinfo=UTC)),  # in its hour
        ("guest", datetime(2026, 11, 6, 14, 50, tzinfo=UTC)),  # in its day
        ("account", datetime(2026, 11, 6, 0, 10, tzinfo=UTC)),  # in its day
        ("account", datetime(2026, 11, 5, 23, 50, tzinfo=UTC)),  # the day before
        ("guest", None),  # never seen
    ):
        sign_ins(who, seen)

    # Taken 5 seconds after the slot of 15:20 ended.
    sample = usage.sample_sessions(now=datetime(2026, 11, 6, 15, 25, 5, tzinfo=UTC))

    counted = {"accounts5m": 1, "guests5m": 1, "accounts1h": 2, "guests1h": 1, "accountsDay": 3, "guestsDay": 2}
    assert sample == counted
    assert usage.SESSIONS.rows() == [{"at": "2026-11-06T15:20:00Z", "span": "5m", **counted}]
    assert usage.SESSIONS.path() == monitor_history._folder() / "sessions.json"


def test_a_sample_is_its_slots_whenever_the_timer_comes_and_its_day_is_the_slots(sign_ins, clock):
    """The sample of the slot that ends at midnight is taken on the next day:
    its hour and its day are still the slot's."""
    sign_ins("account", datetime(2026, 11, 5, 8, 0, tzinfo=UTC))
    sign_ins("account", datetime(2026, 11, 5, 23, 56, tzinfo=UTC))
    sign_ins("guest", datetime(2026, 11, 6, 0, 0, 2, tzinfo=UTC))

    late = usage.sample_sessions(now=datetime(2026, 11, 6, 0, 0, 5, tzinfo=UTC))
    early = usage.sample_sessions(now=datetime(2026, 11, 5, 23, 59, 58, tzinfo=UTC))

    # The 5th's two sign-ins, though the clock read the 6th.
    counted = {"accounts5m": 1, "guests5m": 1, "accounts1h": 1, "guests1h": 1, "accountsDay": 2, "guestsDay": 1}
    assert late == early == counted
    assert usage.SESSIONS.rows() == [{"at": "2026-11-05T23:55:00Z", "span": "5m", **counted}]


def test_each_view_reads_the_sessions_of_its_steps_the_larger_count_of_its_samples(clock):
    """A 5-minute step reads the sessions of its 5 minutes, an hour those of
    the hour and a day those of the day: the larger count of the samples
    within it, never their sum, whether a write joined them or the view did."""

    def sampled(at: datetime, counts: tuple) -> None:
        written = usage.SESSIONS.put(dict(zip(NOBODY, counts)), at=at)
        assert written is True, at

    sampled(datetime(2026, 11, 6, 15, 10, tzinfo=UTC), (2, 1, 4, 3, 9, 7))
    sampled(datetime(2026, 11, 6, 15, 15, tzinfo=UTC), (1, 0, 5, 3, 10, 7))
    # A second sample of one slot keeps the larger of each count.
    sampled(datetime(2026, 11, 6, 15, 15, tzinfo=UTC), (3, 0, 4, 2, 10, 8))
    # Two slots past the last 24 hours, which a write joins into their hour.
    sampled(datetime(2026, 11, 5, 9, 50, tzinfo=UTC), (2, 0, 5, 3, 11, 5))
    sampled(datetime(2026, 11, 5, 9, 55, tzinfo=UTC), (1, 1, 6, 2, 12, 4))

    assert [(row["at"], row["span"]) for row in usage.SESSIONS.rows()] == [
        ("2026-11-05T09:00:00Z", "1h"), ("2026-11-06T15:10:00Z", "5m"), ("2026-11-06T15:15:00Z", "5m")]
    views = usage.snapshot()["views"]
    assert [(each["at"], each["accounts"], each["guests"]) for each in views["24h"]["sessions"]] == [
        ("2026-11-06T15:10:00Z", 2, 1),
        ("2026-11-06T15:15:00Z", 3, 0),
    ]
    assert [(each["at"], each["accounts"], each["guests"]) for each in views["7d"]["sessions"]] == [
        ("2026-11-05T09:00:00Z", 6, 3),
        ("2026-11-06T15:00:00Z", 5, 3),
    ]
    assert [(each["at"], each["accounts"], each["guests"]) for each in views["90d"]["sessions"]] == [
        ("2026-11-05T00:00:00Z", 12, 5),
        ("2026-11-06T00:00:00Z", 10, 8),
    ]


def test_the_sessions_of_the_last_24_hours_are_read_from_the_database(client, sign_ins, clock):
    for who, seen in (
        ("account", NOW - timedelta(minutes=1)),
        ("account", NOW - timedelta(hours=23)),
        ("guest", NOW - timedelta(hours=2)),
        ("guest", NOW - timedelta(hours=25)),
    ):
        sign_ins(who, seen)
    assert client.get("/api/monitor/usage").get_json()["sessionsLast24h"] == {"accounts": 2, "guests": 1}


def test_the_sessions_sampler_is_off_under_testing_and_samples_after_each_5_minutes(app, clock, monkeypatch):
    from utk_curio.backend import config

    timers = []

    class Timer:
        """A timer that waits for the test to fire it."""

        def __init__(self, interval, function, args=()):
            self.interval, self.function, self.args, self.daemon = interval, function, args, False

        def start(self):
            timers.append(self)

        def fire(self):
            self.function(*self.args)

    monkeypatch.setattr(usage.threading, "Timer", Timer)
    monkeypatch.setattr(usage, "_sampler", {})
    # Off under --testing, as the open-files sampler is.
    assert usage.start_sessions_sampler(app) is False and timers == []

    monkeypatch.setattr(config, "_is_testing", lambda: False)
    assert usage.start_sessions_sampler(app) is True
    assert usage.start_sessions_sampler(app) is False  # the home process samples on one timer
    # At 15:20:07, the next sample is 5 seconds into the next 5 minutes: 15:25:05.
    assert [(timer.interval, timer.daemon) for timer in timers] == [(298, True)]

    timers[0].fire()
    # At 15:20:07 the slot that ended last is 15:15's.
    assert usage.SESSIONS.rows() == [{"at": "2026-11-06T15:15:00Z", "span": "5m", **NOBODY}]
    assert [(timer.interval, timer.daemon) for timer in timers] == [(298, True), (298, True)]


# -- the starts -----------------------------------------------------------------------

def test_each_start_is_kept_and_a_deploy_is_a_start_of_another_version(clock):
    """A restart of the version before it is no deploy, even when the start
    before it is outside the view."""
    starts = (
        (NOW - timedelta(days=3), "0.17.398"),
        (NOW - timedelta(hours=30), "0.17.399"),
        (NOW - timedelta(hours=2), "0.17.399"),  # a restart
        (NOW - timedelta(minutes=10), "0.17.400"),
    )
    for at, version in starts:
        clock.at = at
        assert usage.record_start(version) is True
    clock.at = NOW

    stamps = [(at.strftime("%Y-%m-%dT%H:%M:%SZ"), version) for at, version in starts]
    assert [(row["startedAt"], row["version"]) for row in usage.STARTS.rows()] == stamps
    assert usage.STARTS.path() == monitor_history._folder() / "starts.json"
    assert usage.deploys() == [{"at": at, "version": version} for at, version in (stamps[0], stamps[1], stamps[3])]

    views = usage.snapshot()["views"]
    assert [deploy["version"] for deploy in views["24h"]["deploys"]] == ["0.17.400"]
    assert [deploy["version"] for deploy in views["7d"]["deploys"]] == ["0.17.398", "0.17.399", "0.17.400"]
    assert [deploy["version"] for deploy in views["90d"]["deploys"]] == ["0.17.398", "0.17.399", "0.17.400"]


def test_a_start_keeps_this_curios_version_and_a_version_that_is_not_one_as_unknown(clock):
    assert usage.record_start() is True
    clock.at = NOW + timedelta(seconds=1)
    assert usage.record_start("https://llm.example.com/v1") is True
    clock.at = NOW + timedelta(seconds=2)
    assert usage.record_start("a version with spaces") is True
    assert [row["version"] for row in usage.STARTS.rows()] == [utk_curio.__version__, "unknown", "unknown"]
