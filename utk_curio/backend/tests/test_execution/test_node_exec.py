"""A node run through ``execution/node_exec.py`` on a thread of its own, with
no request, does what Play's ``/processPythonCode`` does: the same sandbox
request as the same account and session, the same installed dataset, the same
journal record and the same monitor counts. A node queued behind another in a
sandbox without isolation still has its whole timeout for its own run (#863),
and so does one that waits for a free isolated or JavaScript slot (#889): the
sandbox keeps a waiting run's connection busy, and the backend holds no run
back.

``node_exec`` is imported inside each test, so a checkout without it fails each
test on its own instead of failing the whole collection.
"""

from __future__ import annotations

import io
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests
from urllib3.exceptions import ReadTimeoutError
from urllib3.response import HTTPResponse

from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)


class _Reply:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _fake_sandbox(monkeypatch, output, sent):
    def fake(method, path, **kwargs):
        sent.append((path, json.loads(kwargs["data"])))
        return _Reply({"stdout": ["ran"], "stderr": "", "output": output})

    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)


def _json_artifact(payload) -> str:
    name = f"1790000000100_{uuid.uuid4().hex[:8]}.json"
    (Path(os.environ["CURIO_SHARED_DATA"]) / name).write_text(json.dumps(payload), encoding="utf-8")
    return name


def _start_on_thread(app, fn):
    """Start *fn* on a new thread under an app context and no request, the way
    a run that outlives its browser tab calls it. Returns a function that waits
    for the thread and gives back what *fn* returned, or raises what it raised."""
    box = {}

    def work():
        from flask import has_request_context

        with app.app_context():
            box["had_request"] = has_request_context()
            try:
                box["value"] = fn()
            except BaseException as exc:  # noqa: BLE001 - re-raised on the test's thread
                box["error"] = exc

    thread = threading.Thread(target=work)
    thread.start()

    def result():
        thread.join(timeout=60)
        assert not thread.is_alive()
        assert box["had_request"] is False
        if "error" in box:
            raise box["error"]
        return box["value"]

    return result


def _on_thread(app, fn):
    """Call *fn* on a new thread under an app context and no request."""
    return _start_on_thread(app, fn)()


#: How long the fake sandbox takes over one run, and the timeout the queue
#: tests give a node: one run fits in it, a wait for another run plus a run
#: does not.
RUN_SECONDS = 2.0
SHORT_TIMEOUT = 3

#: How often the modelled sandbox sends a space while a run waits for its
#: place. The sandbox's own interval is ``run_place.KEEPALIVE_SECONDS``; what
#: the model needs is one well within the read timeout, which
#: ``test_a_waiting_runs_reply_sends_well_within_every_read_timeout`` pins for
#: the real one.
KEEPALIVE_SECONDS = 0.5


class _Gaps:
    """A reply's bytes as requests reads them: the gap since the last byte
    must fit the read timeout. Past the headers, requests raises a gap that
    does not as ``ConnectionError`` around urllib3's ``ReadTimeoutError``
    (``Response.iter_content``)."""

    def __init__(self, read_timeout):
        self.read_timeout = read_timeout
        self.last = time.monotonic()

    def byte(self):
        now = time.monotonic()
        if now - self.last > self.read_timeout:
            raise requests.ConnectionError(ReadTimeoutError(None, None, "Read timed out."))
        self.last = now


class _TimedSandbox:
    """The sandbox as the backend's HTTP client meets it, over both clients
    (``sandbox_client``'s session and the ``requests.post`` of
    ``runner._http_exec``).

    It replies as the sandbox's ``/exec`` and ``/execJs`` do (#889; the
    sandbox's ``test_exec_reply_while_queued.py`` proves the real routes do):
    at once, then a space every ``KEEPALIVE_SECONDS`` while the run waits for
    its place, one more when the run takes it, then nothing until the run ends,
    then the JSON. Every gap between those bytes must fit the read timeout.

    The places: *in_process* is a sandbox without isolation, where one Python
    ``/exec`` runs at a time, behind ``_exec_lock``. With isolation, *slots*
    children run at once (``IsolationConfig.slot()``), and *js_slots* Node
    processes run at once in both modes (``worker._js_slot``); left unset,
    those runs overlap freely. With *meet*, every request first waits at that
    barrier, which only requests in the sandbox at the same time can pass.
    """

    def __init__(self, monkeypatch, *, in_process=True, run_seconds=RUN_SECONDS, meet=None,
                 slots=None, js_slots=None):
        self.in_process = in_process
        self.run_seconds = run_seconds
        self.meet = meet
        self.arrived = threading.Event()
        self.running = threading.Event()
        python_slots = 1 if in_process else slots
        self._slots = {
            "/exec": threading.BoundedSemaphore(python_slots) if python_slots else None,
            "/execJs": threading.BoundedSemaphore(js_slots) if js_slots else None,
        }
        self._arrived = 0
        self._started = 0
        self._running = 0
        #: How many runs were running in the sandbox as each request arrived.
        self.running_at_arrival = []
        self._changed = threading.Condition()
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.sandbox_client._sandbox_session",
            SimpleNamespace(post=self.post),
        )
        monkeypatch.setattr(requests, "post", self.post)

    def post(self, url, timeout=None, **_kwargs):
        read_timeout = timeout[1] if isinstance(timeout, tuple) else timeout
        with self._changed:
            self._arrived += 1
            self.running_at_arrival.append(self._running)
            self._changed.notify_all()
        self.arrived.set()
        reply = _Gaps(read_timeout)  # the sandbox answers at once
        if self.meet is not None:
            self.meet.wait()
        slot = self._slots["/execJs" if url.endswith("/execJs") else "/exec"]
        if slot is not None:
            while not slot.acquire(timeout=KEEPALIVE_SECONDS):
                reply.byte()  # a space while the run waits for its place
        try:
            reply.byte()  # one when the run takes it
            self._run()
        finally:
            if slot is not None:
                slot.release()
        reply.byte()  # the JSON
        return _Reply({"stdout": [], "stderr": "", "output": {"path": "art-863", "dataType": "int"}})

    def _run(self):
        with self._changed:
            self._started += 1
            self._running += 1
            self._changed.notify_all()
        self.running.set()
        try:
            time.sleep(self.run_seconds)
        finally:
            with self._changed:
                self._running -= 1

    def wait_started(self, count):
        """Whether *count* runs have started in the sandbox, within ten seconds."""
        with self._changed:
            return self._changed.wait_for(lambda: self._started >= count, timeout=10)

    def wait_arrived(self, count):
        """Whether *count* requests have reached the sandbox, within ten seconds."""
        with self._changed:
            return self._changed.wait_for(lambda: self._arrived >= count, timeout=10)


def _python_run(user, token):
    from utk_curio.backend.app.execution import node_exec

    run = node_exec.NodeRun(code="    return 1", node_type="DATA_LOADING")
    return lambda: node_exec.execute_python_node(user, token, run)


def _js_run(user, token):
    from utk_curio.backend.app.execution import node_exec

    run = node_exec.NodeRun(code="return 1;", node_type="JS_COMPUTATION")
    return lambda: node_exec.execute_js_node(user, token, run)


def _finished(result):
    """The reply of a node run that must not have timed out."""
    from utk_curio.backend.app.execution.sandbox_client import SandboxTransportError

    try:
        reply, status = result()
    except SandboxTransportError as exc:
        pytest.fail(f"the node timed out while it waited for the sandbox: {exc.payload}")
    assert status == 200
    assert reply["output"] == {"path": "art-863", "dataType": "int"}
    return reply


def _play_body(node_id, project_id, **extra):
    return {
        "code": "    return out\n", "nodeType": "PYTHON_COMPUTATION",
        "nodeId": node_id, "dataflowId": project_id,
        "input": {"path": "", "dataType": "str"}, "saveOutputDataset": True,
        **extra,
    }


def test_a_python_node_on_a_thread_runs_as_play_does(app, client, user_and_token, monkeypatch):
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
    from utk_curio.backend.app.execution import node_exec, runtime_journal
    from utk_curio.backend.app.monitor import counters
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    user_key = _user_dir_key(user)
    project_id = create_project(client, token, name="Node run on a thread")
    sent = []
    _fake_sandbox(monkeypatch, {"path": _json_artifact({"hello": "world"}), "dataType": "dict"}, sent)

    via_route = client.post(
        "/processPythonCode",
        data=json.dumps(_play_body("route-node", project_id)),
        headers=auth_headers(token),
    )
    assert via_route.status_code == 200, via_route.get_data(as_text=True)
    route_reply = via_route.get_json()

    before = counters.snapshot()
    run = node_exec.NodeRun.from_request_json(_play_body("thread-node", project_id))
    reply, status = _on_thread(app, lambda: node_exec.execute_python_node(user, token, run))
    after = counters.snapshot()

    assert status == 200
    for key in ("stdout", "stderr", "input", "output", "missingModule"):
        assert reply[key] == route_reply[key], key
    assert route_reply["datasetDiagnostic"]["status"] == "installed"
    assert reply["datasetDiagnostic"]["status"] == "installed"
    assert reply["installedDataset"]["id"] == computed_dataset_id("thread-node", project_id)

    # One sandbox request each, identical, as the same account and session.
    (route_path, route_sent), (thread_path, thread_sent) = sent
    assert route_path == thread_path == "/exec"
    assert thread_sent == route_sent
    assert thread_sent["session_id"] == token
    assert thread_sent["user_key"] == user_key

    record = runtime_journal.read_record(user_key, project_id, "thread-node")
    assert record["status"] == "ok" and record["stdoutTail"] == "ran"
    assert after["total"] - before["total"] == 1
    assert after["python"] - before["python"] == 1
    assert after["ok"] - before["ok"] == 1


def test_a_javascript_node_on_a_thread_runs_as_play_does(app, client, user_and_token, monkeypatch):
    from utk_curio.backend.app.execution import node_exec, runtime_journal
    from utk_curio.backend.app.monitor import counters
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    user_key = _user_dir_key(user)
    project_id = create_project(client, token, name="JavaScript run on a thread")
    sent = []
    _fake_sandbox(monkeypatch, {"path": "art-js", "dataType": "int"}, sent)

    before = counters.snapshot()
    run = node_exec.NodeRun.from_request_json({
        "code": "return 42;", "nodeType": "JS_COMPUTATION", "nodeId": "js-node",
        "dataflowId": project_id, "input": {}, "saveOutputDataset": False,
    })
    reply, status = _on_thread(app, lambda: node_exec.execute_js_node(user, token, run))
    after = counters.snapshot()

    assert status == 200
    assert reply["output"] == {"path": "art-js", "dataType": "int"}
    assert "missingModule" not in reply  # the libraries route cannot install JavaScript
    ((path, body),) = sent
    assert path == "/execJs"
    assert body["session_id"] == token and body["code"] == "return 42;"
    assert runtime_journal.read_record(user_key, project_id, "js-node")["status"] == "ok"
    assert after["javascript"] - before["javascript"] == 1


def test_the_wired_circles_ride_to_the_sandbox_as_input_slots(app, client, user_and_token, monkeypatch):
    """A node reads the edge on circle k as ``input_k``: Play names the wired
    circles, ``inputSlots``, and both routes hand them to the sandbox."""
    user, token = user_and_token
    project_id = create_project(client, token, name="Input slots")
    sent = []
    _fake_sandbox(monkeypatch, {"path": "art-slots", "dataType": "int"}, sent)

    for route, code in (("/processPythonCode", "    return input_3\n"), ("/processJavaScriptCode", "return input_3;")):
        body = {
            "code": code, "nodeType": "curio.builtin/computation-analysis", "nodeId": "slots-node",
            "dataflowId": project_id, "input": {"path": "", "dataType": "outputs"},
            "saveOutputDataset": False, "inputSlots": [0, 3],
        }
        reply = client.post(route, data=json.dumps(body), headers=auth_headers(token))
        assert reply.status_code == 200, reply.get_data(as_text=True)
    plain = _play_body("plain-node", project_id, saveOutputDataset=False)
    without = client.post("/processPythonCode", data=json.dumps(plain), headers=auth_headers(token))
    assert without.status_code == 200, without.get_data(as_text=True)

    assert [(path, body.get("input_slots")) for path, body in sent] == [
        ("/exec", [0, 3]), ("/execJs", [0, 3]), ("/exec", None),
    ]


def test_a_type_probe_saves_nothing_and_is_journaled_as_one(app, client, user_and_token, monkeypatch):
    """A Data Loading node of unknown type is run once in the background to
    learn the type it returns (plans/data-loading-expressive-preview-memo.md).
    That run is Play's run in every way but two: it never installs a dataset,
    whatever the request says, and the journal records why it ran, so the node
    never shows its failure as its own."""
    from utk_curio.backend.app.execution import node_exec, runtime_journal
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    user_key = _user_dir_key(user)
    project_id = create_project(client, token, name="Type probe")
    sent = []
    _fake_sandbox(monkeypatch, {"path": _json_artifact({"a": 1}), "dataType": "dict"}, sent)

    body = _play_body("probe-node", project_id, saveOutputDataset=True, purpose=node_exec.PURPOSE_TYPE_PROBE)
    reply = client.post("/processPythonCode", data=json.dumps(body), headers=auth_headers(token))

    assert reply.status_code == 200, reply.get_data(as_text=True)
    payload = reply.get_json()
    assert payload["output"]["dataType"] == "dict"
    assert payload["installedDataset"] is None and payload["datasetDiagnostic"] is None
    ((path, sandbox_body),) = sent
    assert path == "/exec" and sandbox_body["save_dataset"] is False
    record = runtime_journal.read_record(user_key, project_id, "probe-node")
    assert record["status"] == "ok"
    assert record["kind"] == node_exec.PURPOSE_TYPE_PROBE


def test_an_unknown_purpose_is_an_ordinary_run():
    from utk_curio.backend.app.execution import node_exec

    run = node_exec.NodeRun.from_request_json({
        "code": "return 1", "nodeType": "curio.builtin/data-loading", "purpose": "anything", "saveOutputDataset": True,
    })
    assert run.purpose is None and run.save_output_dataset is True


def test_a_sandbox_that_does_not_answer_raises_the_routes_error(app, user_and_token, monkeypatch):
    from utk_curio.backend.app.execution import node_exec, sandbox_client
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the run reads it
    session = MagicMock()
    session.post.side_effect = requests.Timeout("simulated read timeout")
    monkeypatch.setattr(sandbox_client, "_sandbox_session", session)

    run = node_exec.NodeRun(code="    return 1", node_type="DATA_LOADING")
    with pytest.raises(sandbox_client.SandboxTransportError) as caught:
        _on_thread(app, lambda: node_exec.execute_python_node(user, token, run))
    assert caught.value.status == 504
    assert caught.value.payload["error"] == "sandbox_timeout"
    assert caught.value.payload["path"] == "/exec"
    assert caught.value.payload["timeout_seconds"] == node_exec.SANDBOX_EXEC_TIMEOUT == 600


def test_a_node_queued_behind_a_long_run_still_finishes(app, user_and_token, monkeypatch):
    """#863: without isolation the sandbox runs one Python node at a time, and
    the run engine sends a whole level at once. A node that waits behind
    another's run must still have its whole timeout for its own run."""
    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    monkeypatch.setenv("CURIO_ISOLATION", "off")
    monkeypatch.setattr(node_exec, "SANDBOX_EXEC_TIMEOUT", SHORT_TIMEOUT)
    sandbox = _TimedSandbox(monkeypatch)

    first = _start_on_thread(app, _python_run(user, token))
    assert sandbox.running.wait(10)
    queued = _start_on_thread(app, _python_run(user, token))

    _finished(first)
    _finished(queued)


def test_a_node_queued_behind_a_validation_run_still_finishes(app, user_and_token, monkeypatch):
    """#863: Solve's validation runs (``runner._http_exec``) run at the same
    sandbox, so a node that waits behind one keeps its whole timeout too."""
    from utk_curio.backend.app.execution import node_exec, runner
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the run reads it
    monkeypatch.setenv("CURIO_ISOLATION", "off")
    monkeypatch.setattr(node_exec, "SANDBOX_EXEC_TIMEOUT", SHORT_TIMEOUT)
    sandbox = _TimedSandbox(monkeypatch)

    validation = _start_on_thread(app, lambda: runner._http_exec("/exec", {"code": "    return 1"}))
    assert sandbox.running.wait(10)
    queued = _start_on_thread(app, _python_run(user, token))

    assert validation()["output"] == {"path": "art-863", "dataType": "int"}
    _finished(queued)


def test_isolated_python_runs_still_overlap(app, user_and_token, monkeypatch):
    """#863 keeps parallelism: with isolation each node runs in a child of its
    own, so two Python runs are in the sandbox at the same time."""
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    monkeypatch.setenv("CURIO_ISOLATION", "fork")
    sandbox = _TimedSandbox(
        monkeypatch, in_process=False, run_seconds=0, meet=threading.Barrier(2, timeout=10),
    )

    first = _start_on_thread(app, _python_run(user, token))
    assert sandbox.arrived.wait(10)
    second = _start_on_thread(app, _python_run(user, token))

    _finished(first)
    _finished(second)


def test_javascript_runs_still_overlap_without_isolation(app, user_and_token, monkeypatch):
    """#863 keeps parallelism: the sandbox runs JavaScript nodes in parallel
    even without isolation, so two are in the sandbox at the same time."""
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    monkeypatch.setenv("CURIO_ISOLATION", "off")
    sandbox = _TimedSandbox(monkeypatch, run_seconds=0, meet=threading.Barrier(2, timeout=10))

    first = _start_on_thread(app, _js_run(user, token))
    assert sandbox.arrived.wait(10)
    second = _start_on_thread(app, _js_run(user, token))

    _finished(first)
    _finished(second)


#: How many runs at once the #889 tests give the sandbox, for isolated Python
#: children and for Node processes alike.
SLOTS = 2

#: A host with six cores. Unset, ``CURIO_EXEC_PARALLELISM`` and
#: ``CURIO_JS_PARALLELISM`` are half the host's cores, from 2 (docs/USAGE.md),
#: so this host runs three of each at once.
SIX_CORES = 6
DEFAULT_SLOTS_ON_SIX_CORES = 3


def _slotted_sandbox(monkeypatch, *, slots=SLOTS, isolation="fork", **kwargs):
    """The sandbox with *slots* isolated children and *slots* Node processes at
    once, and the environment ``curio.py`` starts both servers with saying so.
    The backend reads neither count: it holds no run back (#889)."""
    monkeypatch.setenv("CURIO_ISOLATION", isolation)
    monkeypatch.setenv("CURIO_EXEC_PARALLELISM", str(slots))
    monkeypatch.setenv("CURIO_JS_PARALLELISM", str(slots))
    return _TimedSandbox(monkeypatch, in_process=False, slots=slots, js_slots=slots, **kwargs)


def _sandbox_on_six_cores(monkeypatch, **kwargs):
    """The sandbox on a six-core host with no slot counts set, as a deploy that
    passes neither ``--exec-parallelism`` nor ``--js-parallelism`` runs it."""
    monkeypatch.setattr(os, "cpu_count", lambda: SIX_CORES)
    monkeypatch.setenv("CURIO_ISOLATION", "fork")
    monkeypatch.delenv("CURIO_EXEC_PARALLELISM", raising=False)
    monkeypatch.delenv("CURIO_JS_PARALLELISM", raising=False)
    return _TimedSandbox(
        monkeypatch, in_process=False,
        slots=DEFAULT_SLOTS_ON_SIX_CORES, js_slots=DEFAULT_SLOTS_ON_SIX_CORES, **kwargs,
    )


def _validated(result):
    """The reply of a validation run that must not have timed out."""
    from utk_curio.backend.app.execution.runner import ExecutionTimeout

    try:
        reply = result()
    except ExecutionTimeout as exc:
        pytest.fail(f"the validation run timed out while it waited for the sandbox: {exc}")
    assert reply["output"] == {"path": "art-863", "dataType": "int"}
    return reply


def test_an_isolated_node_queued_for_a_free_slot_still_finishes(app, user_and_token, monkeypatch):
    """#889: with isolation the sandbox runs ``CURIO_EXEC_PARALLELISM`` children
    at once, and a run that finds every slot busy waits inside the sandbox. A
    node sent while every slot runs must still have its whole timeout for its
    own run."""
    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    monkeypatch.setattr(node_exec, "SANDBOX_EXEC_TIMEOUT", SHORT_TIMEOUT)
    sandbox = _slotted_sandbox(monkeypatch)

    running = [_start_on_thread(app, _python_run(user, token)) for _ in range(SLOTS)]
    assert sandbox.wait_started(SLOTS)
    queued = _start_on_thread(app, _python_run(user, token))

    for result in (*running, queued):
        _finished(result)


def test_a_validation_run_queued_for_a_free_slot_still_finishes(app, user_and_token, monkeypatch):
    """#889: Solve's validation runs (``runner._http_exec``) take the same
    isolated slots, so one sent while every slot runs a node keeps its whole
    timeout (``CURIO_VALIDATION_EXEC_TIMEOUT``) for its own run."""
    from utk_curio.backend.app.execution import node_exec, runner
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    monkeypatch.setattr(node_exec, "SANDBOX_EXEC_TIMEOUT", SHORT_TIMEOUT)
    monkeypatch.setenv("CURIO_VALIDATION_EXEC_TIMEOUT", str(SHORT_TIMEOUT))
    sandbox = _slotted_sandbox(monkeypatch)

    running = [_start_on_thread(app, _python_run(user, token)) for _ in range(SLOTS)]
    assert sandbox.wait_started(SLOTS)
    validation = _start_on_thread(app, lambda: runner._http_exec("/exec", {"code": "    return 1"}))

    for result in running:
        _finished(result)
    _validated(validation)


@pytest.mark.parametrize("isolation", ["off", "fork"])
def test_a_javascript_node_queued_for_a_free_slot_still_finishes(app, user_and_token, monkeypatch, isolation):
    """#889: in both modes the sandbox runs ``CURIO_JS_PARALLELISM`` Node
    processes at once (``worker._js_slot``), so a JavaScript node sent while
    every slot runs must still have its whole timeout for its own run."""
    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    monkeypatch.setattr(node_exec, "SANDBOX_EXEC_TIMEOUT", SHORT_TIMEOUT)
    sandbox = _slotted_sandbox(monkeypatch, isolation=isolation)

    running = [_start_on_thread(app, _js_run(user, token)) for _ in range(SLOTS)]
    assert sandbox.wait_started(SLOTS)
    queued = _start_on_thread(app, _js_run(user, token))

    for result in (*running, queued):
        _finished(result)


def test_a_javascript_validation_run_queued_for_a_free_slot_still_finishes(app, user_and_token, monkeypatch):
    """#889: a JavaScript validation run takes the same Node slots as a node,
    so one sent while every slot runs keeps its whole timeout too."""
    from utk_curio.backend.app.execution import node_exec, runner
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    monkeypatch.setattr(node_exec, "SANDBOX_EXEC_TIMEOUT", SHORT_TIMEOUT)
    monkeypatch.setenv("CURIO_VALIDATION_EXEC_TIMEOUT", str(SHORT_TIMEOUT))
    sandbox = _slotted_sandbox(monkeypatch)

    running = [_start_on_thread(app, _js_run(user, token)) for _ in range(SLOTS)]
    assert sandbox.wait_started(SLOTS)
    validation = _start_on_thread(app, lambda: runner._http_exec("/execJs", {"code": "return 1;"}))

    for result in running:
        _finished(result)
    _validated(validation)


@pytest.mark.parametrize("make_run", [_python_run, _js_run], ids=["python", "javascript"])
def test_a_run_queued_for_a_default_slot_still_finishes(app, user_and_token, monkeypatch, make_run):
    """#889: with no slot counts set, the sandbox sizes its slots from the
    host's cores. A run sent while every one of them runs must still have its
    whole timeout for its own run."""
    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    monkeypatch.setattr(node_exec, "SANDBOX_EXEC_TIMEOUT", SHORT_TIMEOUT)
    sandbox = _sandbox_on_six_cores(monkeypatch)

    running = [_start_on_thread(app, make_run(user, token)) for _ in range(DEFAULT_SLOTS_ON_SIX_CORES)]
    assert sandbox.wait_started(DEFAULT_SLOTS_ON_SIX_CORES)
    queued = _start_on_thread(app, make_run(user, token))

    for result in (*running, queued):
        _finished(result)


@pytest.mark.parametrize("counts", ["set", "default"])
@pytest.mark.parametrize("make_run", [_python_run, _js_run], ids=["python", "javascript"])
def test_as_many_runs_as_slots_are_in_the_sandbox_at_once(app, user_and_token, monkeypatch, make_run, counts):
    """#889 keeps parallelism: the backend holds no run back, so three slots
    still take three runs at the same time, whether the counts are set or come
    from the host's cores."""
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    slots = DEFAULT_SLOTS_ON_SIX_CORES
    meet = threading.Barrier(slots, timeout=10)
    if counts == "set":
        _slotted_sandbox(monkeypatch, slots=slots, run_seconds=0, meet=meet)
    else:
        _sandbox_on_six_cores(monkeypatch, run_seconds=0, meet=meet)

    runs = [_start_on_thread(app, make_run(user, token)) for _ in range(slots)]

    for result in runs:
        _finished(result)


#: The sandbox's three queues: ``_exec_lock`` for a Python run without
#: isolation, an isolated slot for one with isolation, a Node slot for a
#: JavaScript run.
QUEUES = ["exec_lock", "isolated_slot", "node_slot"]


def _sandbox_with_one_place(monkeypatch, queue, **kwargs):
    """The sandbox with a single place in *queue*."""
    if queue == "isolated_slot":
        monkeypatch.setenv("CURIO_ISOLATION", "fork")
        return _TimedSandbox(monkeypatch, in_process=False, slots=1, **kwargs)
    monkeypatch.setenv("CURIO_ISOLATION", "off")
    return _TimedSandbox(monkeypatch, js_slots=1, **kwargs)


def _validation_run(endpoint):
    from utk_curio.backend.app.execution import runner

    code = "return 1;" if endpoint == "/execJs" else "    return 1"
    return lambda: runner._http_exec(endpoint, {"code": code})


def _run_in(queue, kind, user, token):
    """A node run (Play, a server run) or a validation run (Solve) that waits
    in *queue*."""
    endpoint = "/execJs" if queue == "node_slot" else "/exec"
    if kind == "validation":
        return _validation_run(endpoint)
    return (_js_run if endpoint == "/execJs" else _python_run)(user, token)


def _ended(kind, result):
    return _validated(result) if kind == "validation" else _finished(result)


def _timed_out(kind, result):
    """A run that must have ended as a timeout, as a sandbox that never
    answers does: a 504 ``sandbox_timeout`` for a node, ``ExecutionTimeout``
    for a validation run."""
    from utk_curio.backend.app.execution.runner import ExecutionTimeout
    from utk_curio.backend.app.execution.sandbox_client import SandboxTransportError

    if kind == "validation":
        with pytest.raises(ExecutionTimeout) as caught:
            result()
        assert caught.value.seconds == SHORT_TIMEOUT
        return
    with pytest.raises(SandboxTransportError) as caught:
        result()
    assert caught.value.status == 504, caught.value.payload
    assert caught.value.payload["error"] == "sandbox_timeout"
    assert caught.value.payload["timeout_seconds"] == SHORT_TIMEOUT


def _short_timeouts(monkeypatch):
    from utk_curio.backend.app.execution import node_exec

    monkeypatch.setattr(node_exec, "SANDBOX_EXEC_TIMEOUT", SHORT_TIMEOUT)
    monkeypatch.setenv("CURIO_VALIDATION_EXEC_TIMEOUT", str(SHORT_TIMEOUT))


@pytest.mark.parametrize("kind", ["node", "validation"])
@pytest.mark.parametrize("queue", QUEUES)
def test_a_run_waits_for_its_place_inside_the_sandbox(app, user_and_token, monkeypatch, queue, kind):
    """#889: the backend holds no run back, so the three queues work the same
    way. A run sent while its queue's one place is taken reaches the sandbox at
    once and waits there, where the reply keeps its connection busy. (#875 held
    a Python run without isolation in the backend instead.)"""
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    _short_timeouts(monkeypatch)
    sandbox = _sandbox_with_one_place(monkeypatch, queue)

    first = _start_on_thread(app, _run_in(queue, kind, user, token))
    assert sandbox.wait_started(1)
    queued = _start_on_thread(app, _run_in(queue, kind, user, token))
    assert sandbox.wait_arrived(2)

    for result in (first, queued):
        _ended(kind, result)
    assert sandbox.running_at_arrival == [0, 1], (
        "the run waited outside the sandbox while its place was taken"
    )


@pytest.mark.parametrize("queue", QUEUES)
def test_a_node_waiting_for_its_place_counts_as_in_flight(app, user_and_token, monkeypatch, queue):
    """#889: a node whose run waits in the sandbox counts in the monitor's
    ``inFlight``, the same way in all three queues: its request is out, as an
    isolated or JavaScript node's always was. (#875 left a Python node without
    isolation out of the count while the backend held it back.)"""
    from utk_curio.backend.app.monitor import counters
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    _short_timeouts(monkeypatch)
    sandbox = _sandbox_with_one_place(monkeypatch, queue)
    before = counters.snapshot()["inFlight"]

    first = _start_on_thread(app, _run_in(queue, "node", user, token))
    assert sandbox.wait_started(1)
    queued = _start_on_thread(app, _run_in(queue, "node", user, token))
    assert sandbox.wait_arrived(2)
    in_flight = counters.snapshot()["inFlight"] - before

    for result in (first, queued):
        _finished(result)
    assert in_flight == 2, "the waiting node was not counted as in flight"


@pytest.mark.parametrize("queue", QUEUES)
def test_a_run_behind_two_others_still_finishes(app, user_and_token, monkeypatch, queue):
    """#889: a run's wait for its place can outlast its whole timeout. Here a
    node waits behind two runs (4 s) with a 3 s timeout; the reply's spaces
    keep its connection busy for as long as the wait lasts."""
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    _short_timeouts(monkeypatch)
    sandbox = _sandbox_with_one_place(monkeypatch, queue)

    first = _start_on_thread(app, _run_in(queue, "node", user, token))
    assert sandbox.wait_started(1)
    second = _start_on_thread(app, _run_in(queue, "node", user, token))
    assert sandbox.wait_arrived(2)
    third = _start_on_thread(app, _run_in(queue, "node", user, token))

    for result in (first, second, third):
        _finished(result)


@pytest.mark.parametrize("kind", ["node", "validation"])
@pytest.mark.parametrize("queue", QUEUES)
def test_a_queued_run_longer_than_its_timeout_still_times_out(app, user_and_token, monkeypatch, queue, kind):
    """#889 takes the wait out of a run's timeout, not the run: a run that
    waited for its place and then runs past its timeout still ends as a
    timeout, the same error a sandbox that never answers gives. The sandbox
    answers at once now, so requests raises it while it reads the body."""
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the runs read it
    _short_timeouts(monkeypatch)
    sandbox = _sandbox_with_one_place(monkeypatch, queue, run_seconds=SHORT_TIMEOUT + 0.5)

    first = _start_on_thread(app, _run_in(queue, kind, user, token))
    assert sandbox.wait_started(1)
    queued = _start_on_thread(app, _run_in(queue, kind, user, token))

    for result in (first, queued):
        _timed_out(kind, result)


#: What the sandbox sends when it fails a run itself, after the status has
#: gone out (``sandbox/run_place.py``).
_SANDBOX_ERROR = {
    "error": "RuntimeError",
    "message": "the run broke",
    "stdout": [],
    "stderr": "Sandbox error: RuntimeError: the run broke",
    "output": {"path": "", "dataType": "str"},
}


@pytest.mark.parametrize("make_run", [_python_run, _js_run], ids=["python", "javascript"])
def test_a_sandbox_error_in_the_reply_fails_the_node_as_the_sandbox_s_error(
    app, user_and_token, monkeypatch, make_run,
):
    """#889: the sandbox's status goes out before the run, so an error the
    sandbox itself hits comes back in the JSON body, named under ``error``. A
    node reads it as it read the sandbox's 500 before: a 500 that says the
    sandbox failed, in the sandbox's words."""
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the run reads it
    monkeypatch.setattr(
        "utk_curio.backend.app.execution.node_exec.sandbox_request",
        lambda method, path, **kwargs: _Reply(dict(_SANDBOX_ERROR)),
    )

    reply, status = _on_thread(app, make_run(user, token))
    assert status == 500, reply
    assert reply["stderr"].startswith("Sandbox error") and "the run broke" in reply["stderr"], reply
    assert reply["output"] == {}, reply


@pytest.mark.parametrize("endpoint", ["/exec", "/execJs"])
def test_a_sandbox_error_in_the_reply_is_an_infrastructure_failure_for_a_validation_run(monkeypatch, endpoint):
    """#889: Solve's validation run reads the sandbox's own error as it read
    the sandbox's 500 before: a failure of the sandbox, which the runner
    reports as ``infrastructure``, never as the node's failure or a timeout."""
    from utk_curio.backend.app.execution import runner

    monkeypatch.setattr(requests, "post", lambda url, **kwargs: _Reply(dict(_SANDBOX_ERROR)))

    with pytest.raises(Exception) as caught:
        _validation_run(endpoint)()
    assert not isinstance(caught.value, runner.ExecutionTimeout)
    assert "the run broke" in str(caught.value)


def test_a_reply_cut_short_says_the_sandbox_could_not_be_reached(app, user_and_token, monkeypatch):
    """#889: the sandbox's reply streams now, and one that stops before its
    JSON (the sandbox died during the run) is the sandbox being unreachable:
    the routes' 502, not an unhandled error."""
    from utk_curio.backend.app.execution import node_exec, sandbox_client
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _user_dir_key(user)  # load the row on this thread before the run reads it
    session = MagicMock()
    session.post.side_effect = requests.exceptions.ChunkedEncodingError("Connection broken: IncompleteRead")
    monkeypatch.setattr(sandbox_client, "_sandbox_session", session)

    run = node_exec.NodeRun(code="    return 1", node_type="DATA_LOADING")
    with pytest.raises(sandbox_client.SandboxTransportError) as caught:
        _on_thread(app, lambda: node_exec.execute_python_node(user, token, run))
    assert caught.value.status == 502
    assert caught.value.payload["error"] == "sandbox_unreachable"
    assert caught.value.payload["path"] == "/exec"


class _StalledBody(io.RawIOBase):
    """A reply body that stalls past the read timeout, as a socket does."""

    def readable(self):
        return True

    def readinto(self, buffer):
        raise socket.timeout("timed out")


def test_requests_reads_a_stalled_reply_body_as_a_timeout():
    """#889: once the sandbox has answered, a stall is a gap inside the body,
    and requests reports it as a ``ConnectionError`` around urllib3's
    ``ReadTimeoutError`` rather than as ``requests.Timeout``.
    ``sandbox_client.read_timed_out`` is what node runs and validation runs
    both ask, so it must know that shape. No socket: a real
    ``requests.Response`` reads a urllib3 response whose body stalls."""
    from utk_curio.backend.app.execution import sandbox_client

    response = requests.Response()
    response.status_code = 200
    response.raw = HTTPResponse(body=_StalledBody(), status=200, preload_content=False)
    with pytest.raises(requests.RequestException) as caught:
        response.content

    assert sandbox_client.read_timed_out(caught.value), repr(caught.value)
    assert sandbox_client.read_timed_out(requests.ReadTimeout("no headers in time"))
    assert not sandbox_client.read_timed_out(requests.ConnectionError("connection refused"))


def test_a_waiting_runs_reply_sends_well_within_every_read_timeout(monkeypatch):
    """#889: while a run waits for its place, the sandbox sends a space every
    ``run_place.KEEPALIVE_SECONDS``. Each gap must fit the read timeout with
    room to spare: a node's (``SANDBOX_EXEC_TIMEOUT``) and a validation run's
    (``CURIO_VALIDATION_EXEC_TIMEOUT``, 300 s unless set)."""
    from utk_curio.backend.app.execution import node_exec, runner
    from utk_curio.sandbox import run_place

    monkeypatch.delenv("CURIO_VALIDATION_EXEC_TIMEOUT", raising=False)
    for read_timeout in (node_exec.SANDBOX_EXEC_TIMEOUT, runner.exec_timeout_s()):
        assert run_place.KEEPALIVE_SECONDS * 10 <= read_timeout, read_timeout
