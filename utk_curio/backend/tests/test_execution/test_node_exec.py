"""A node run through ``execution/node_exec.py`` on a thread of its own, with
no request, does what Play's ``/processPythonCode`` does: the same sandbox
request as the same account and session, the same installed dataset, the same
journal record and the same monitor counts. A node queued behind another in a
sandbox without isolation still has its whole timeout for its own run (#863),
and so does one that waits for a free isolated or JavaScript slot (#889).

``node_exec`` is imported inside each test, so a checkout without it fails each
test on its own instead of failing the whole collection.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

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


class _TimedSandbox:
    """The sandbox as the backend's HTTP client meets it, over both clients
    (``sandbox_client``'s session and the ``requests.post`` of
    ``runner._http_exec``).

    It sends nothing until a run ends, so a request's read timeout counts from
    the moment the request was sent. *in_process* is a sandbox without
    isolation: one Python ``/exec`` runs at a time, behind ``_exec_lock``. With
    isolation, *slots* children run at once (``IsolationConfig.slot()``), and
    *js_slots* Node processes run at once in both modes (``worker._js_slot``);
    left unset, those runs overlap freely. With *meet*, every request first
    waits at that barrier, which only requests in the sandbox at the same time
    can pass.
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
        self._started = 0
        self._changed = threading.Condition()
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.sandbox_client._sandbox_session",
            SimpleNamespace(post=self.post),
        )
        monkeypatch.setattr(requests, "post", self.post)

    def post(self, url, timeout=None, **_kwargs):
        sent = time.monotonic()
        self.arrived.set()
        if self.meet is not None:
            self.meet.wait()
        slot = self._slots["/execJs" if url.endswith("/execJs") else "/exec"]
        with slot if slot is not None else contextlib.nullcontext():
            with self._changed:
                self._started += 1
                self._changed.notify_all()
            self.running.set()
            time.sleep(self.run_seconds)
        read_timeout = timeout[1] if isinstance(timeout, tuple) else timeout
        if time.monotonic() - sent > read_timeout:
            raise requests.ReadTimeout(f"no reply within {read_timeout}s")
        return _Reply({"stdout": [], "stderr": "", "output": {"path": "art-863", "dataType": "int"}})

    def wait_started(self, count):
        """Whether *count* runs have started in the sandbox, within ten seconds."""
        with self._changed:
            return self._changed.wait_for(lambda: self._started >= count, timeout=10)


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
    once, and the environment ``curio.py`` starts both servers with saying so."""
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
    at once, and a run that finds every slot busy waits inside the sandbox,
    where its read timeout already counts. A node sent while every slot runs
    must still have its whole timeout for its own run."""
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
    """#889 keeps parallelism: the backend holds a run back only while every
    slot the sandbox has is taken, so three slots still take three runs at the
    same time, whether the counts are set or come from the host's cores."""
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
