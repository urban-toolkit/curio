"""A run that waits for its place in the sandbox keeps its connection busy (#889).

The sandbox runs only so many nodes at once, and a run that finds its place
taken waits for it inside the sandbox:

- without isolation, one Python node at a time, behind ``worker._exec_lock``;
- with isolation, ``CURIO_EXEC_PARALLELISM`` children (``IsolationConfig.slot()``);
- in both modes, ``CURIO_JS_PARALLELISM`` Node processes (``worker._js_slot()``).

The backend reads a reply with a read timeout on every gap between its bytes,
the wait for the first one included. So ``/exec`` and ``/execJs`` answer at
once, send a space every ``run_place.KEEPALIVE_SECONDS`` while the run waits,
one more when it takes its place, and then nothing until the run ends, when
the JSON follows. The backend's timeout then counts the run and not the wait.
The backend's tests (``backend/tests/test_execution/test_node_exec.py``) model
this reply; these prove the real routes send it, through the Flask test client.

Each test holds the real place a run needs from a thread of its own, and lets
it go after ten seconds at most, so a sandbox that sends nothing while a run
waits fails the test instead of hanging it. New modules are imported inside
the tests, so a checkout without them fails each test on its own.
"""

import contextlib
import io
import json
import re
import sys
import textwrap
import threading
import time

import pytest

#: How long a test's node runs once it has its place.
RUN = 1.0

#: The longest a test holds a place before it lets go on its own.
HOLD = 10

#: The longest any one step may take before the test gives up on it.
WAIT = 30


def _exec_body(code, node_type, session_id="session-889"):
    return {
        "code": textwrap.indent(code, "    "),
        "file_path": "",
        "nodeType": node_type,
        "dataType": "",
        "session_id": session_id,
        "save_dataset": False,
    }


@pytest.fixture
def sandbox_log(tmp_path, monkeypatch):
    """A sandbox on a data folder of its own, without isolation unless a queue
    says otherwise. Returns the process's own stderr, where its log lines go."""
    from utk_curio.sandbox.app import api
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", "./.curio/data/")
    monkeypatch.setenv("CURIO_ISOLATION", "off")
    # In process, whatever this host would resolve: the choice is cached for
    # the process, so the variable alone can come too late.
    monkeypatch.setattr(api, "_isolation_state", False)
    (tmp_path / ".curio" / "data").mkdir(parents=True)
    release_connection()
    init_db()
    log = io.StringIO()
    monkeypatch.setattr(sys, "__stderr__", log)
    yield log
    release_connection()


class _ExecLock:
    """Python without isolation: one run at a time, behind ``_exec_lock``."""

    route = "/exec"

    def __init__(self, monkeypatch, tmp_path):
        from utk_curio.sandbox.app import worker

        self._lock = worker._exec_lock

    def take(self):
        return self._lock.hold("held by the test")

    def is_free(self):
        return not self._lock._lock.locked()

    def body(self, node_type):
        return _exec_body(f"import time\ntime.sleep({RUN})\nreturn 1\n", node_type)

    def check(self, reply):
        assert reply["stderr"] == "", reply
        assert reply["output"]["path"] and reply["output"]["dataType"] == "int", reply


class _ChildThatRuns:
    """The zygote's half of an isolated run: the child takes RUN seconds."""

    def __init__(self, socket_path):
        self.socket_path = socket_path

    def run(self, request, wall_timeout=None):
        time.sleep(RUN)
        return 0, None, False


class _IsolatedSlot:
    """Python with isolation: ``IsolationConfig.slot()`` bounds the children,
    to one here. Everything up to the zygote is real; the zygote and the
    child's manifest are faked, so the child reports one printed line."""

    route = "/exec"

    def __init__(self, monkeypatch, tmp_path):
        from utk_curio.sandbox.app import api
        from utk_curio.sandbox.isolation import runner, supervisor

        self.config = runner.IsolationConfig.from_environment({
            "CURIO_EXEC_PARALLELISM": "1",
            "CURIO_EXEC_SOCKET": str(tmp_path / "exec-zygote.sock"),
            "CURIO_LAUNCH_CWD": str(tmp_path),
        })
        monkeypatch.setattr(api, "_isolation_state", (runner.execute_isolated, self.config))
        monkeypatch.setattr(supervisor, "ZygoteClient", _ChildThatRuns)
        monkeypatch.setattr(
            supervisor, "read_child_manifest",
            lambda scratch_dir: {"ok": False, "stdout": ["the child ran"], "stderr": ""},
        )

    def take(self):
        return self.config.slot()

    def is_free(self):
        if not self.config._semaphore.acquire(blocking=False):
            return False
        self.config._semaphore.release()
        return True

    def body(self, node_type):
        return _exec_body("return 1\n", node_type)

    def check(self, reply):
        assert reply["stdout"] == ["the child ran"], reply


class _NodeSlot:
    """JavaScript, in both modes: ``worker._js_slot()`` bounds the Node
    processes, to one here."""

    route = "/execJs"

    def __init__(self, monkeypatch, tmp_path):
        from utk_curio.sandbox.app import worker

        self._slots = threading.BoundedSemaphore(1)
        monkeypatch.setattr(worker, "_js_slots", self._slots)

    @contextlib.contextmanager
    def take(self):
        self._slots.acquire()
        try:
            yield
        finally:
            self._slots.release()

    def is_free(self):
        if not self._slots.acquire(blocking=False):
            return False
        self._slots.release()
        return True

    def body(self, node_type):
        return {
            "code": (
                f"const until = Date.now() + {int(RUN * 1000)};\n"
                "while (Date.now() < until) {}\n"
                "return 7;"
            ),
            "file_path": "",
            "nodeType": node_type,
            "dataType": "",
            "session_id": "session-889",
            "save_dataset": False,
        }

    def check(self, reply):
        assert reply["output"]["path"], reply


@pytest.fixture(params=[_ExecLock, _IsolatedSlot, _NodeSlot], ids=["exec_lock", "isolated_slot", "node_slot"])
def queue(request, sandbox_log, monkeypatch, tmp_path):
    return request.param(monkeypatch, tmp_path)


class _Holder:
    """Holds a run's place from a thread of its own until :meth:`let_go`, or
    for *seconds* at most. ``let_go_at`` is when it let go."""

    def __init__(self, take, seconds=HOLD):
        self.let_go_at = None
        self._let_go = threading.Event()
        taken = threading.Event()

        def hold():
            with take():
                taken.set()
                self._let_go.wait(seconds)
                self.let_go_at = time.monotonic()

        self._thread = threading.Thread(target=hold, daemon=True)
        self._thread.start()
        assert taken.wait(WAIT), "the test could not take the place"

    def let_go(self):
        self._let_go.set()
        self.join()

    def join(self):
        self._thread.join(WAIT)
        assert not self._thread.is_alive(), "the test could not give the place back"


class _Reply:
    """A streamed reply, read one chunk at a time, each with when it came."""

    def __init__(self, response):
        self.response = response
        self.chunks = []
        self._rest = iter(response.response)
        # The test client takes the first chunk before it returns the response.
        self.read()

    def read(self):
        chunk = next(self._rest, None)
        if chunk is not None:
            self.chunks.append((time.monotonic(), chunk))
        return chunk

    def read_to_the_end(self):
        while self.read() is not None:
            pass
        self.response.close()
        return self

    def body(self):
        return b"".join(chunk for _, chunk in self.chunks)

    def json(self):
        return json.loads(self.body())


def _post(route, body):
    from utk_curio.sandbox.app import app

    return _Reply(app.test_client().post(route, json=body, buffered=False))


def _finished_line(log, route, node_type):
    return re.search(
        rf"\[sandbox {re.escape(route)}\] finished .*waited=([0-9.]+)s .*node={node_type}\b",
        log.getvalue(),
    )


def test_a_queued_run_hears_from_the_sandbox_until_it_has_its_place(sandbox_log, queue, monkeypatch):
    """#889: while every place is taken, the reply sends a space every
    ``KEEPALIVE_SECONDS``, the first at once. Once the run has its place the
    reply sends nothing until the run ends, then the JSON the sandbox has always
    sent, so the backend's read timeout counts the run alone."""
    from flask import jsonify

    from utk_curio.sandbox import run_place
    from utk_curio.sandbox.app import app

    monkeypatch.setattr(run_place, "KEEPALIVE_SECONDS", 0.05)
    holder = _Holder(queue.take)
    try:
        reply = _post(queue.route, queue.body("QUEUED"))
        # The first space and three more while the place stays taken.
        while len(reply.chunks) < 4 and reply.read() is not None:
            pass
    finally:
        holder.let_go()
    reply.read_to_the_end()

    waiting = [chunk for moment, chunk in reply.chunks if moment < holder.let_go_at]
    assert len(waiting) >= 4 and set(waiting) == {b" "}, (
        f"the sandbox sent {waiting!r} while the run waited for its place"
    )
    (ran_from, _), (ended_at, _) = reply.chunks[-2], reply.chunks[-1]
    assert ended_at - ran_from >= RUN / 2, "the sandbox sent something while the run ran"
    result = reply.json()
    queue.check(result)
    with app.app_context():
        assert reply.body().lstrip(b" ") == jsonify(result).get_data()
    finished = _finished_line(sandbox_log, queue.route, "QUEUED")
    assert finished, sandbox_log.getvalue()
    assert float(finished.group(1)) >= 0.1, "the log does not say how long the run waited"


def test_a_run_hears_once_more_when_it_takes_its_place(sandbox_log, queue):
    """#889: the reply sends one space the moment the run takes its place, so
    the gap the read timeout measures last starts with the run, not with the
    space before it. A wait shorter than ``KEEPALIVE_SECONDS`` sends exactly
    that space and the one at once."""
    holder = _Holder(queue.take, seconds=1.0)
    reply = _post(queue.route, queue.body("PLACED")).read_to_the_end()
    holder.join()

    moments = [moment for moment, _ in reply.chunks]
    chunks = [chunk for _, chunk in reply.chunks]
    assert chunks[0] == b" " and moments[0] < holder.let_go_at, (
        "the sandbox sent nothing while the run waited for its place"
    )
    assert chunks[1:-1] == [b" "] and moments[1] >= holder.let_go_at, (
        f"expected one space when the run took its place, got {chunks[1:-1]!r}"
    )
    assert moments[-1] - moments[1] >= RUN / 2, "the sandbox sent something while the run ran"
    queue.check(reply.json())


def test_a_run_whose_backend_leaves_while_it_waits_still_runs_and_gives_its_place_back(sandbox_log, queue):
    """#889: a backend that stops reading (its own timeout, a cancelled run)
    closes the reply while the run waits. The run is not cancelled, as before:
    it still runs once it has its place, and then gives back its place and the
    DuckDB connection, so the next run goes through."""
    from utk_curio.sandbox.util import db

    holder = _Holder(queue.take)
    reply = _post(queue.route, queue.body("LEFT_ALONE"))
    answered_while_waiting = holder.let_go_at is None
    reply.response.close()
    holder.let_go()
    assert answered_while_waiting, "the sandbox sent nothing while the run waited for its place"

    deadline = time.monotonic() + WAIT
    while not _finished_line(sandbox_log, queue.route, "LEFT_ALONE"):
        assert time.monotonic() < deadline, f"the run never finished: {sandbox_log.getvalue()}"
        time.sleep(0.05)
    assert queue.is_free(), "the run kept its place after it finished"
    assert db._in_use == 0, "the run kept the DuckDB connection after it finished"

    queue.check(_post(queue.route, queue.body("NEXT")).read_to_the_end().json())


@pytest.mark.parametrize("route, runs", [("/exec", "execute_code"), ("/execJs", "execute_js_code")])
def test_an_error_in_the_run_comes_back_in_the_json_body(sandbox_log, monkeypatch, route, runs):
    """#889: the status went out with the first space, so an error the run
    raises afterwards comes back in the body: ``error`` names it for the
    backend, and ``stderr`` and an empty output say the same to any reader."""
    from utk_curio.sandbox.app import api, app

    def broken(*_args, **_kwargs):
        raise RuntimeError("the run broke")

    monkeypatch.setattr(api, runs, broken)
    response = app.test_client().post(route, json=_exec_body("return 1\n", "BROKEN"))
    assert response.status_code == 200, response.get_data(as_text=True)
    reply = json.loads(response.get_data())
    assert reply["error"] == "RuntimeError", reply
    assert "the run broke" in reply["message"] and "the run broke" in reply["stderr"], reply
    assert reply["stdout"] == [] and reply["output"] == {"path": "", "dataType": "str"}, reply
    assert "the run broke" in sandbox_log.getvalue(), "the traceback is not in the sandbox's log"


@pytest.mark.parametrize("route", ["/exec", "/execJs"])
def test_a_request_without_code_is_still_refused_with_a_400(sandbox_log, route):
    """#889 streams only a run: a request that cannot run is refused before
    any byte goes out, with its own status."""
    from utk_curio.sandbox.app import app

    response = app.test_client().post(route, json={"file_path": "", "nodeType": "NO_CODE", "dataType": ""})
    assert response.status_code == 400


@pytest.mark.parametrize("route, runs", [("/exec", "execute_code"), ("/execJs", "execute_js_code")])
def test_the_run_holds_the_duckdb_connection_while_it_runs(sandbox_log, monkeypatch, route, runs):
    """#889 keeps ``holds_duckdb``'s promise: a run keeps the shared DuckDB
    connection open until it ends, so a release from another thread waits for
    it. The run now ends after the route has returned."""
    from utk_curio.sandbox.app import api, app
    from utk_curio.sandbox.util import db

    seen = []

    def run(*_args, **_kwargs):
        seen.append(db._in_use)
        return {"stdout": [], "stderr": "", "output": {"path": "", "dataType": "str"}}

    monkeypatch.setattr(api, runs, run)
    response = app.test_client().post(route, json=_exec_body("return 1\n", "HOLDS_DUCKDB"))
    assert response.status_code == 200
    assert response.get_json()["output"] == {"path": "", "dataType": "str"}
    assert seen and seen[0] >= 1, f"the run had no hold on the connection: {seen}"


def test_runs_queued_together_each_get_their_own_reply(sandbox_log):
    """#889: three runs that wait for ``_exec_lock`` at once, each on a thread
    of its own, each get the reply of their own code."""
    from utk_curio.sandbox.app import app, worker

    replies = {}

    def send(n):
        response = app.test_client().post(
            "/exec", json=_exec_body(f"print('run {n}')\nreturn {n}\n", f"RUN_{n}", f"session-{n}"),
        )
        replies[n] = (response.status_code, response.get_json())

    holder = _Holder(lambda: worker._exec_lock.hold("held by the test"))
    threads = [threading.Thread(target=send, args=(n,), daemon=True) for n in (1, 2, 3)]
    try:
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + WAIT
        while worker._exec_lock.snapshot()["waiting"] < 3:
            assert time.monotonic() < deadline, f"the runs never queued: {replies}"
            time.sleep(0.01)
    finally:
        holder.let_go()
    for thread in threads:
        thread.join(WAIT)
        assert not thread.is_alive(), "a queued run did not finish"

    for n in (1, 2, 3):
        status, reply = replies[n]
        assert status == 200, reply
        assert f"run {n}" in "".join(reply["stdout"]), (n, reply)
        assert reply["output"]["dataType"] == "int", (n, reply)
    assert len({replies[n][1]["output"]["path"] for n in (1, 2, 3)}) == 3


def test_a_run_that_ends_while_a_node_runs_logs_outside_that_nodes_stderr(sandbox_log, monkeypatch):
    """#889 keeps #770's rule on the thread a run now has: a JavaScript run
    that ends while a Python node runs (and holds the process's stdout and
    stderr) writes its log lines to the process's own stderr, not into that
    node's."""
    from utk_curio.sandbox.app import app, worker

    entered, release = threading.Event(), threading.Event()
    monkeypatch.setitem(worker._globals_cache, "node_a_entered", entered)
    monkeypatch.setitem(worker._globals_cache, "node_a_release", release)
    node_a = (
        "import sys\n"
        "print('a line of node A', file=sys.stderr)\n"
        "node_a_entered.set()\n"
        "node_a_release.wait(60)\n"
        "return 1\n"
    )
    a = {}

    def run_node_a():
        a["reply"] = app.test_client().post("/exec", json=_exec_body(node_a, "NODE_A")).get_json()

    a_thread = threading.Thread(target=run_node_a, daemon=True)
    a_thread.start()
    try:
        assert entered.wait(WAIT), f"node A never ran its code: {a}"
        js = app.test_client().post("/execJs", json={
            "code": "return 40 + 2;", "file_path": "", "nodeType": "NODE_JS",
            "dataType": "", "session_id": "session-js", "save_dataset": False,
        }).get_json()
    finally:
        release.set()
        a_thread.join(WAIT)
    assert not a_thread.is_alive(), "node A did not finish"

    assert js["output"]["path"], js
    assert "a line of node A" in a["reply"]["stderr"]
    assert "[sandbox /execJs]" not in a["reply"]["stderr"]
    assert "[execJs]" not in a["reply"]["stderr"]
    assert re.search(r"\[sandbox /execJs\] finished .*node=NODE_JS\b", sandbox_log.getvalue())
