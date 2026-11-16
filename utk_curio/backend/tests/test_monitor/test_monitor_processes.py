"""The monitor across the backend processes of a start.

``curio.py start --backend-processes N`` runs N backend processes behind nginx,
which sends every monitor route to the home process, process 0
(``cli/backend_group.py``). Each process holds its own part of what the monitor
shows: its node runs and its memory, its error log, the LLM tokens its agents
spent and its open files. So the home process asks every other process for its
part, over 127.0.0.1 at the port the launcher names for it and signed with the
start's secret, as a change to a dataflow reaches its owner, and merges them:
node runs summed, the error logs together by time, token rows by hour and
model, and in each hour the open files of the busiest process against its own
limit. Each monitor route then says which processes answered; one that does
not answer is named and its part left out, and the route still answers. Each
process writes its own history files, the home process's start clears every
other process's, and every process samples its own open files. With one
process nothing is asked, and every answer is as it was.

Here this app is the home process, and each other process is a server in the
test (:class:`_OtherProcess`) that answers with the part this app's own
internal route answered as that process: each test takes it first, as that
process, then goes on as home. New names are imported in each test, so a
checkout without them fails test by test.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests.test_collaboration._processes import as_process, as_the_one_process

#: The secret the start's backends show each other, and the header it travels in.
SECRET = "the start's own secret"
TOKEN_HEADER = "X-Curio-Backend-Token"
NOW = datetime(2026, 11, 6, 15, 20, 7, tzinfo=timezone.utc)
MIB = 1024 * 1024
#: The monitor's routes whose numbers each process holds a part of.
ROUTES = ("/api/monitor", "/api/monitor/errors", "/api/monitor/llm", "/api/monitor/open-files")
#: What a start of one process answers a call from another.
ONE_PROCESS = "a start of one backend process takes no call from another"


class _OtherProcess:
    """Another backend process of the start, as the home process reaches it
    over 127.0.0.1: a server in the test that keeps each call it gets in
    :attr:`calls` and answers ``/internal/monitor/<part>`` as a backend's
    internal route does, with the part :attr:`parts` holds, else as a route
    that has no such part. A context manager: it serves inside the block."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.parts: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._server = None
        self._thread = None

    @property
    def port(self) -> int:
        return self._server.server_port

    def asked(self) -> list:
        """Each call's part and arguments, in the order they came."""
        with self._lock:
            return [(call["part"], call["arguments"]) for call in self.calls]

    def __call__(self, environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = json.loads(environ["wsgi.input"].read(length) or b"{}")
        path = environ.get("PATH_INFO", "")
        part = path.rsplit("/", 1)[-1]
        with self._lock:
            self.calls.append({"path": path, "part": part, "arguments": body.get("arguments"),
                               "token": environ.get("HTTP_X_CURIO_BACKEND_TOKEN")})
        if part in self.parts:
            answer = {"ok": True, "result": self.parts[part]}
        else:
            answer = {"ok": False, "error": f"no part {part!r}"}
        reply = json.dumps(answer).encode("utf-8")
        start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(reply)))])
        return [reply]

    def __enter__(self) -> "_OtherProcess":
        from werkzeug.serving import make_server

        self._server = make_server("127.0.0.1", 0, self, threaded=True)
        self._thread = threading.Thread(target=self._server.serve_forever, name="other-process", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> bool:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()
        return False


def _closed_port() -> int:
    """A port of 127.0.0.1 nothing listens on: a call there is refused at once."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


@contextlib.contextmanager
def _start(monkeypatch, processes: int = 2, *, not_answering=frozenset()):
    """This app as the home process, 0, of a start of *processes*. Process 0's
    port is a server that must get no call; each other process's is a server
    that answers with what the test puts in its ``parts``, but those in
    *not_answering*, whose port nothing listens on."""
    with contextlib.ExitStack() as stack:
        itself = stack.enter_context(_OtherProcess())
        others: dict[int, _OtherProcess] = {}
        ports = [itself.port]
        for number in range(1, processes):
            if number in not_answering:
                ports.append(_closed_port())
                continue
            others[number] = stack.enter_context(_OtherProcess())
            ports.append(others[number].port)
        monkeypatch.setenv("CURIO_BACKEND_PORTS", ",".join(str(port) for port in ports))
        monkeypatch.setenv("CURIO_BACKEND_TOKEN", SECRET)
        as_process(monkeypatch, 0, processes)
        yield SimpleNamespace(itself=itself, others=others)


def _part_as(client, monkeypatch, number: int, processes: int, part: str, arguments: dict | None = None) -> dict:
    """The part *part* this app's own route answers as process *number* of
    *processes*, signed with the start's secret: what that process sends the
    home process. The app goes on as the home process."""
    as_process(monkeypatch, number, processes)
    answer = client.post(f"/internal/monitor/{part}", data=json.dumps({"arguments": arguments or {}}),
                         content_type="application/json", headers={TOKEN_HEADER: SECRET})
    as_process(monkeypatch, 0, processes)
    text = answer.get_data(as_text=True)
    assert answer.status_code == 200, f"process {number}'s route for its {part} part answered {answer.status_code}: {text}"
    body = json.loads(text)
    assert body.get("ok") is True and isinstance(body.get("result"), dict), text
    return body["result"]


def _answer(response) -> dict:
    """A monitor route's answer, which must be a 200."""
    text = response.get_data(as_text=True)
    assert response.status_code == 200, text
    return json.loads(text)


def _signed(other: _OtherProcess) -> None:
    tokens = {call["token"] for call in other.calls}
    assert other.calls and tokens == {SECRET}, f"a call reached another process without the start's secret: {other.calls}"


def _stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _errors_clock(monkeypatch, start: float) -> list:
    """The error log's clock, read from a list the test moves by hand."""
    from utk_curio.backend.app.monitor import errors

    clock = [start]
    monkeypatch.setattr(errors, "time", SimpleNamespace(time=lambda: clock[0], strftime=time.strftime,
                                                        gmtime=time.gmtime))
    return clock


def _rows(path):
    """The rows of the history file at *path*, None when there is none."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("rows")


@pytest.fixture()
def counts(monkeypatch):
    """The open files the sampler counts, on the test's clock: this process's
    ``(open, limit)`` (``counts.backend``) at ``counts.at``, and the sandbox's
    ``/monitor`` answer, with the number of each process that asked for it
    (``counts.sandbox_asked``)."""
    from utk_curio.backend.app.monitor import open_files, routes
    from utk_curio.common import backend_processes
    from utk_curio.common import open_files as common_open_files

    state = SimpleNamespace(at=NOW, backend=(212, 65536), sandbox_asked=[])

    def sandbox():
        state.sandbox_asked.append(backend_processes.this_process())
        return {"open_files": 96, "open_files_limit": 65536}

    monkeypatch.setattr(open_files, "_now", lambda: state.at)
    monkeypatch.setattr(common_open_files, "in_use", lambda: state.backend)
    monkeypatch.setattr(routes, "_sandbox_monitor", sandbox)
    open_files.reset()
    yield state
    open_files.reset()


def _take(counts, at: datetime, backend: tuple) -> dict:
    """This process's sample of its open files, *backend* at *at*."""
    from utk_curio.backend.app.monitor import open_files

    counts.at, counts.backend = at, backend
    return open_files.sample()


# ---------------------------------------------------------------------------
# Every process's part, merged at home
# ---------------------------------------------------------------------------

def test_home_adds_up_the_node_runs_and_memory_of_every_process(client, monkeypatch):
    """Runs, failures, languages and runs in flight are summed, node types
    counted once across processes, and the backend's memory is every
    process's; home asks process 1 once, signed, and never itself."""
    from utk_curio.backend.app.monitor import counters, hardware
    from utk_curio.common import backend_processes

    # Each process's own memory: 100 MiB for home, 100 MiB more for each number after it.
    monkeypatch.setattr(hardware, "process_rss_bytes", lambda: (backend_processes.this_process() + 1) * 100 * MIB)
    with _start(monkeypatch) as start:
        counters.record_execution(language="python", node_type="pkg/a", ok=True, duration_ms=120)
        counters.record_execution(language="javascript", node_type="pkg/b", ok=False, duration_ms=900)
        counters.record_execution(language="python", node_type="pkg/b", ok=True, duration_ms=300)
        with counters.in_flight():
            start.others[1].parts["backend"] = _part_as(client, monkeypatch, 1, 2, "backend")
        counters.reset()
        counters.record_execution(language="python", node_type="pkg/b", ok=True, duration_ms=40)
        counters.record_execution(language="python", node_type="pkg/c", ok=False, duration_ms=5000)
        with counters.in_flight():
            body = _answer(client.get("/api/monitor"))
        asked = start.others[1].asked()

    backend = body["execution"]["backend"]
    assert {key: backend[key] for key in ("total", "ok", "error", "python", "javascript", "inFlight",
                                          "distinctNodeTypes")} == {
        "total": 5, "ok": 3, "error": 2, "python": 4, "javascript": 1, "inFlight": 2, "distinctNodeTypes": 3,
    }, backend
    assert body["hardware"]["processes"]["backendRssBytes"] == 300 * MIB
    assert body.get("backendProcesses") == {"count": 2, "answered": [0, 1], "missing": []}
    assert asked == [("backend", {})]
    _signed(start.others[1])
    assert start.itself.calls == [], "the home process asked itself"

    # The durations are what one process that made all five runs would show.
    counters.reset()
    for duration in (120, 900, 300, 40, 5000):
        counters.record_execution(language="python", ok=True, duration_ms=duration)
    alone = counters.snapshot()
    assert backend["durations"] == alone["durations"]


def test_the_run_durations_are_the_newest_200_of_every_process(client, monkeypatch):
    """The window the percentiles and the histogram read is the newest runs
    of the whole backend, as one process's is its own newest."""
    from utk_curio.backend.app.monitor import counters

    with _start(monkeypatch) as start:
        for duration in range(1, 151):
            counters.record_execution(language="python", ok=True, duration_ms=duration)
        start.others[1].parts["backend"] = _part_as(client, monkeypatch, 1, 2, "backend")
        counters.reset()
        for duration in range(1001, 1151):
            counters.record_execution(language="python", ok=True, duration_ms=duration)
        body = _answer(client.get("/api/monitor"))

    merged = body["execution"]["backend"]
    counters.reset()
    for duration in (*range(101, 151), *range(1001, 1151)):
        counters.record_execution(language="python", ok=True, duration_ms=duration)
    alone = counters.snapshot()
    assert merged["total"] == 300
    assert merged["durations"] == alone["durations"]


def test_home_lists_the_errors_of_every_process_newest_first(client, monkeypatch):
    """Every process's errors in one log, newest first, each naming the
    process that holds it, with the refused browser reports summed."""
    from utk_curio.backend.app.monitor import errors

    clock = _errors_clock(monkeypatch, NOW.timestamp())
    with _start(monkeypatch) as start:
        errors.record("node", summary="KeyError: 'population'", detail="Traceback in process 1")
        clock[0] += 10
        errors.record("backend", summary="GET /api/projects -> RuntimeError", detail="Traceback in process 1")
        errors.record_dropped_client()
        start.others[1].parts["errors"] = _part_as(client, monkeypatch, 1, 2, "errors")
        errors.reset()
        clock[0] += 10
        errors.record("node", summary="ValueError: no rows", detail="Traceback in the home process")
        clock[0] += 10
        errors.record("client", summary="TypeError in the browser", detail="at render")
        errors.record_dropped_client()
        errors.record_dropped_client()
        body = _answer(client.get("/api/monitor/errors"))
        asked = start.others[1].asked()

    listed = [(entry["at"], entry["source"], entry["summary"], entry.get("process")) for entry in body["errors"]]
    assert listed == [
        (_stamp(NOW + timedelta(seconds=30)), "client", "TypeError in the browser", 0),
        (_stamp(NOW + timedelta(seconds=20)), "node", "ValueError: no rows", 0),
        (_stamp(NOW + timedelta(seconds=10)), "backend", "GET /api/projects -> RuntimeError", 1),
        (_stamp(NOW), "node", "KeyError: 'population'", 1),
    ]
    assert body["droppedClient"] == 3
    assert [entry for entry in body["errors"] if "_at" in entry or "_seq" in entry] == []
    assert (body["serverWindow"], body["clientWindow"]) == (errors.SERVER_WINDOW, errors.CLIENT_WINDOW)
    assert body.get("backendProcesses") == {"count": 2, "answered": [0, 1], "missing": []}
    assert asked == [("errors", {})]


def test_the_error_log_keeps_the_newest_server_errors_of_all_processes_to_its_window(client, monkeypatch):
    """As one process's log holds its newest errors to its window, the
    backend's holds the newest of every process's together to that window,
    so the page is no longer for the backend running as several."""
    from utk_curio.backend.app.monitor import errors

    clock = _errors_clock(monkeypatch, NOW.timestamp())
    with _start(monkeypatch) as start:
        for index in range(150):
            clock[0] += 1
            errors.record("node", summary=f"failure {index} in process 1")
        start.others[1].parts["errors"] = _part_as(client, monkeypatch, 1, 2, "errors")
        errors.reset()
        for index in range(100):
            clock[0] += 1
            errors.record("node", summary=f"failure {index} in the home process")
        body = _answer(client.get("/api/monitor/errors"))

    summaries = [entry["summary"] for entry in body["errors"]]
    assert errors.SERVER_WINDOW == 200
    assert summaries == [
        *(f"failure {index} in the home process" for index in reversed(range(100))),
        *(f"failure {index} in process 1" for index in reversed(range(50, 150))),
    ]


def test_home_adds_up_the_llm_tokens_of_every_process_by_hour_and_model(client, monkeypatch):
    """The hourly rows and each model's totals are what one process that
    made every request would show: rows of the same hour and model summed,
    each process's counted against the home process's clock."""
    from utk_curio.backend.app.monitor import llm_tokens

    clock = SimpleNamespace(at=NOW)
    monkeypatch.setattr(llm_tokens, "_now", lambda: clock.at)

    def requests_of_process_1():
        clock.at = NOW - timedelta(hours=2)
        llm_tokens.record("gpt-5", curio=False, input_tokens=40, output_tokens=8)
        clock.at = NOW
        llm_tokens.record("gemma4", curio=True, input_tokens=100, output_tokens=20)

    def requests_of_home():
        clock.at = NOW - timedelta(days=30)
        llm_tokens.record("gemma4", curio=False, input_tokens=7, output_tokens=1)
        clock.at = NOW
        llm_tokens.record("gemma4", curio=True, input_tokens=50, output_tokens=10)

    with _start(monkeypatch) as start:
        requests_of_process_1()
        start.others[1].parts["llm"] = _part_as(client, monkeypatch, 1, 2, "llm", {"now": _stamp(NOW)})
        llm_tokens.reset()
        requests_of_home()
        merged = _answer(client.get("/api/monitor/llm"))
        asked = start.others[1].asked()

    llm_tokens.reset()
    requests_of_process_1()
    requests_of_home()
    alone = llm_tokens.snapshot()
    assert merged["hourly"] == alone["hourly"]
    assert merged["models"] == alone["models"]
    gemma = [row for row in merged["hourly"] if (row["model"], row["curio"]) == ("gemma4", True)]
    assert [(row["inputTokens"], row["outputTokens"], row["requests"]) for row in gemma] == [(150, 30, 2)]
    assert [merged[key] for key in ("computedAt", "hourlyFrom", "hourlyTo", "maxDays")] == [
        alone[key] for key in ("computedAt", "hourlyFrom", "hourlyTo", "maxDays")]
    assert merged.get("backendProcesses") == {"count": 2, "answered": [0, 1], "missing": []}
    assert asked == [("llm", {"now": _stamp(NOW)})]


def test_the_open_files_line_is_the_busiest_process_of_each_hour_against_its_own_limit(client, monkeypatch, counts):
    """In each hour, the sample of the process with the largest share of its
    own limit, which a lower limit makes the busiest with fewer files; the
    sandbox's count is the home process's, which alone asks for it."""
    from utk_curio.backend.app.monitor import open_files

    hour = timedelta(hours=1)
    with _start(monkeypatch, 3) as start:
        as_process(monkeypatch, 1, 3)
        _take(counts, NOW + timedelta(minutes=5), (5000, 65536))
        _take(counts, NOW + hour + timedelta(minutes=5), (300, 65536))
        start.others[1].parts["open-files"] = _part_as(client, monkeypatch, 1, 3, "open-files")
        open_files.reset()
        as_process(monkeypatch, 2, 3)
        _take(counts, NOW + hour + timedelta(minutes=10), (900, 1024))
        start.others[2].parts["open-files"] = _part_as(client, monkeypatch, 2, 3, "open-files")
        open_files.reset()
        _take(counts, NOW, (212, 65536))
        _take(counts, NOW + hour, (230, 65536))
        body = _answer(client.get("/api/monitor/open-files"))

    sandbox = {"open": 96, "limit": 65536}
    assert body["samples"] == [
        {"at": _stamp(NOW + timedelta(minutes=5)), "backend": {"open": 5000, "limit": 65536},
         "backendProcess": 1, "sandbox": sandbox},
        {"at": _stamp(NOW + hour + timedelta(minutes=10)), "backend": {"open": 900, "limit": 1024},
         "backendProcess": 2, "sandbox": sandbox},
    ]
    assert counts.sandbox_asked == [0, 0], "a process other than home asked the sandbox"
    assert body.get("backendProcesses") == {"count": 3, "answered": [0, 1, 2], "missing": []}
    assert (body["maxDays"], body["intervalSeconds"], body["warnAbovePercent"], body["clearBelowPercent"]) == (
        90, 3600, 80, 70)


def test_a_process_that_does_not_answer_is_named_and_its_part_left_out(client, monkeypatch):
    """Process 2's port refuses the call: every route still answers, names
    process 2 as missing by its number, and leaves its part out; why goes to
    the error log, which is raw by decision, once for however many asks."""
    from utk_curio.backend.app.monitor import counters

    with _start(monkeypatch, 3, not_answering={2}) as start:
        counters.record_execution(language="python", ok=True, duration_ms=10)
        counters.record_execution(language="python", ok=True, duration_ms=20)
        for part, arguments in (("backend", {}), ("errors", {}), ("open-files", {}),
                                ("llm", {"now": _stamp(datetime.now(timezone.utc))})):
            start.others[1].parts[part] = _part_as(client, monkeypatch, 1, 3, part, arguments)
        counters.reset()
        counters.record_execution(language="javascript", ok=False, duration_ms=30)
        responses = {route: client.get(route) for route in ROUTES}

    bodies = {route: _answer(response) for route, response in responses.items()}
    lines = {route: body.get("backendProcesses") for route, body in bodies.items()}
    assert lines == {route: {"count": 3, "answered": [0, 1], "missing": [2]} for route in ROUTES}
    backend = bodies["/api/monitor"]["execution"]["backend"]
    assert (backend["total"], backend["ok"], backend["python"], backend["javascript"]) == (3, 2, 2, 1)
    entries = bodies["/api/monitor/errors"]["errors"]
    told = [entry for entry in entries if entry["summary"] == "Backend process 2 did not answer the monitor"]
    assert len(told) == 1 and (told[0]["source"], told[0].get("process")) == ("backend", 0), entries
    assert "127.0.0.1" not in json.dumps(lines)
    assert start.itself.calls == [], "the home process asked itself"


# ---------------------------------------------------------------------------
# Each process's own history files
# ---------------------------------------------------------------------------

def test_each_process_writes_its_own_history_files(monkeypatch):
    """``<name>.<number>.json`` for a process other than home, so none writes
    over another's; ``<name>.json`` for the home process, and for a start of
    one process, as before."""
    from utk_curio.backend.app.monitor import history, llm_tokens, open_files

    folder = history._folder()
    as_process(monkeypatch, 2, 3)
    llm_tokens.record("gemma4", curio=True, input_tokens=120, output_tokens=30)
    paths = {"llm tokens": llm_tokens.HISTORY.path(), "open files": open_files.HISTORY.path()}

    assert paths == {"llm tokens": folder / "llm-tokens.2.json", "open files": folder / "open-files.2.json"}
    written = _rows(folder / "llm-tokens.2.json")
    assert [(row["model"], row["inputTokens"], row["outputTokens"]) for row in written] == [("gemma4", 120, 30)]
    home_rows = _rows(folder / "llm-tokens.json")
    assert home_rows in (None, []), "process 2 wrote the home process's file"

    as_process(monkeypatch, 0, 3)
    home_path = llm_tokens.HISTORY.path()
    as_the_one_process(monkeypatch)
    one_path = llm_tokens.HISTORY.path()
    assert (home_path, one_path) == (folder / "llm-tokens.json", folder / "llm-tokens.json")


def test_the_home_start_clears_the_files_of_every_other_process_and_writes_its_own_anew(monkeypatch):
    """What an earlier start left, of any number of processes, goes before
    the others start; files that are no history's stay."""
    from utk_curio.backend.app import create_app
    from utk_curio.backend.app.monitor import history
    from utk_curio.backend.tests._unit_fixtures import TestConfig

    folder = history._folder()
    folder.mkdir(parents=True, exist_ok=True)
    stale = [{"hour": "2026-11-01T10:00:00Z", "value": 1}]
    left = ("llm-tokens.json", "open-files.json", "llm-tokens.1.json", "llm-tokens.7.json", "open-files.3.json")
    kept = ("notes.json", "llm-tokens.backup.json", "someone-else.2.json")
    for name in (*left, *kept):
        (folder / name).write_text(json.dumps({"name": name, "rows": stale}), encoding="utf-8")

    as_process(monkeypatch, 0, 2)
    create_app(TestConfig)

    files = sorted(path.name for path in folder.iterdir() if path.suffix == ".json")
    assert files == sorted(("llm-tokens.json", "open-files.json", *kept))
    own = {name: _rows(folder / name) for name in ("llm-tokens.json", "open-files.json")}
    assert own == {"llm-tokens.json": [], "open-files.json": []}
    others = {name: _rows(folder / name) for name in kept}
    assert others == {name: stale for name in kept}


def test_another_process_start_writes_its_own_files_anew_and_leaves_the_others(monkeypatch):
    """A process other than home starts its own histories over, as home
    does, and touches no other process's file."""
    from utk_curio.backend.app import create_app
    from utk_curio.backend.app.monitor import history
    from utk_curio.backend.tests._unit_fixtures import TestConfig

    folder = history._folder()
    folder.mkdir(parents=True, exist_ok=True)
    for name, value in (("llm-tokens.json", 0), ("llm-tokens.1.json", 1), ("llm-tokens.2.json", 2)):
        rows = [{"hour": "2026-11-06T14:00:00Z", "value": value}]
        (folder / name).write_text(json.dumps({"name": "llm-tokens", "rows": rows}), encoding="utf-8")
    before = {name: (folder / name).read_bytes() for name in ("llm-tokens.json", "llm-tokens.2.json")}

    as_process(monkeypatch, 1, 3)
    create_app(TestConfig)

    own = {name: _rows(folder / name) for name in ("llm-tokens.1.json", "open-files.1.json")}
    assert own == {"llm-tokens.1.json": [], "open-files.1.json": []}
    after = {name: (folder / name).read_bytes() for name in before}
    assert after == before


# ---------------------------------------------------------------------------
# Open files in every process
# ---------------------------------------------------------------------------

def test_every_process_samples_its_own_open_files_and_only_home_the_sandbox(monkeypatch, counts):
    """The home process samples when it serves (under Werkzeug's reloader,
    the process that does the startup work), and so does every other process
    of a start of several, which serves without the reloader; only home asks
    the sandbox, whose files one count covers."""
    from utk_curio.backend.app.monitor import open_files

    starts = {}
    as_the_one_process(monkeypatch)
    starts["one process, serving"] = open_files.sampler_starts_here(True)
    starts["one process, not serving"] = open_files.sampler_starts_here(False)
    as_process(monkeypatch, 0, 3)
    starts["home, serving"] = open_files.sampler_starts_here(True)
    starts["home, not serving"] = open_files.sampler_starts_here(False)
    as_process(monkeypatch, 2, 3)
    starts["process 2"] = open_files.sampler_starts_here(False)
    assert starts == {"one process, serving": True, "one process, not serving": False,
                      "home, serving": True, "home, not serving": False, "process 2": True}

    row = open_files.sample(wait_for_sandbox=open_files.FIRST_SAMPLE_WAIT_SECONDS)
    assert counts.sandbox_asked == [], "process 2 asked the sandbox"
    assert (row["backend"], row["sandbox"]) == ({"open": 212, "limit": 65536}, None)
    as_process(monkeypatch, 0, 3)
    home = open_files.sample()
    assert (counts.sandbox_asked, home["sandbox"]) == ([0], {"open": 96, "limit": 65536})


def test_each_process_warns_of_its_own_open_files_by_its_number(monkeypatch, counts):
    """Above 80% of its own limit a process records one error naming it, and
    another only after it fell below 70%, as one process does."""
    from utk_curio.backend.app.monitor import errors

    as_process(monkeypatch, 2, 3)
    _take(counts, NOW, (900, 1024))
    _take(counts, NOW + timedelta(hours=1), (950, 1024))
    entries = errors.snapshot()["errors"]

    assert [(entry["source"], entry["summary"], entry["count"]) for entry in entries] == [
        ("backend", "Backend process 2 has 900 open files, 87.9% of its limit of 1,024", 1),
    ]
    assert "backend process 2 opens" in entries[0]["detail"], entries[0]["detail"]


# ---------------------------------------------------------------------------
# The route a process answers for its part
# ---------------------------------------------------------------------------

def test_the_internal_route_answers_only_a_call_signed_with_the_start_secret(client, monkeypatch):
    """Outside /api, which is all the site's proxy sends the backend, and
    answered only with the start's secret; nginx answers /internal/ itself."""
    as_process(monkeypatch, 1, 2)
    monkeypatch.setenv("CURIO_BACKEND_TOKEN", SECRET)

    def post(part: str, headers: dict):
        return client.post(f"/internal/monitor/{part}", data=json.dumps({"arguments": {}}),
                           content_type="application/json", headers=headers)

    responses = {
        "unsigned": post("backend", {}),
        "another secret": post("backend", {TOKEN_HEADER: "another secret"}),
        "no such part": post("nothing", {TOKEN_HEADER: SECRET}),
        "signed": post("backend", {TOKEN_HEADER: SECRET}),
    }
    answers = {name: (response.status_code, response.get_json()) for name, response in responses.items()}

    refused = {"ok": False, "error": "not signed with this start's secret"}
    assert answers["unsigned"] == (403, refused), answers
    assert answers["another secret"] == (403, refused), answers
    assert answers["no such part"] == (404, {"ok": False, "error": "no part 'nothing'"}), answers
    assert answers["signed"][0] == 200 and answers["signed"][1].get("ok") is True, answers


# ---------------------------------------------------------------------------
# One process
# ---------------------------------------------------------------------------

def test_with_one_process_nothing_is_asked_and_every_answer_is_as_it_was(client, monkeypatch, counts):
    """A start of one process, with a port and a secret left in its
    environment: nothing is asked, no answer says which processes answered,
    no entry or sample names a process, and the internal route refuses. The
    route's refusal is what fails before this change; the rest pins that one
    process is as it was."""
    from utk_curio.backend.app.monitor import counters, errors, llm_tokens

    with _OtherProcess() as stray:
        as_the_one_process(monkeypatch)
        monkeypatch.setenv("CURIO_BACKEND_PORTS", f"{stray.port}")
        monkeypatch.setenv("CURIO_BACKEND_TOKEN", SECRET)
        counters.record_execution(language="python", ok=True, duration_ms=10)
        errors.record("node", summary="KeyError: 'x'", detail="Traceback")
        llm_tokens.record("gemma4", curio=True, input_tokens=5, output_tokens=1)
        _take(counts, NOW, (212, 65536))
        responses = {route: client.get(route) for route in ROUTES}
        refused = client.post("/internal/monitor/backend", data=json.dumps({"arguments": {}}),
                              content_type="application/json", headers={TOKEN_HEADER: SECRET})

    bodies = {route: _answer(response) for route, response in responses.items()}
    assert [route for route, body in bodies.items() if "backendProcesses" in body] == []
    assert stray.calls == [], "a start of one process asked another"
    assert bodies["/api/monitor"]["execution"]["backend"]["total"] == 1
    assert [entry for entry in bodies["/api/monitor/errors"]["errors"] if "process" in entry] == []
    assert bodies["/api/monitor/open-files"]["samples"] == [
        {"at": _stamp(NOW), "backend": {"open": 212, "limit": 65536}, "sandbox": {"open": 96, "limit": 65536}},
    ]
    refusal = refused.get_data(as_text=True)
    assert refused.status_code == 404 and json.loads(refusal) == {"ok": False, "error": ONE_PROCESS}, refusal
