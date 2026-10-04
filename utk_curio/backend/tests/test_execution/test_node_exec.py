"""A node run through ``execution/node_exec.py`` on a thread of its own, with
no request, does what Play's ``/processPythonCode`` does: the same sandbox
request as the same account and session, the same installed dataset, the same
journal record and the same monitor counts.

``node_exec`` is imported inside each test, so a checkout without it fails each
test on its own instead of failing the whole collection.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
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


def _fake_sandbox(monkeypatch, output, sent):
    def fake(method, path, **kwargs):
        sent.append((path, json.loads(kwargs["data"])))
        return _Reply({"stdout": ["ran"], "stderr": "", "output": output})

    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)


def _json_artifact(payload) -> str:
    name = f"1790000000100_{uuid.uuid4().hex[:8]}.json"
    (Path(os.environ["CURIO_SHARED_DATA"]) / name).write_text(json.dumps(payload), encoding="utf-8")
    return name


def _on_thread(app, fn):
    """Call *fn* on a new thread under an app context and no request, the way
    a run that outlives its browser tab calls it."""
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
    thread.join(timeout=60)
    assert not thread.is_alive()
    assert box["had_request"] is False
    if "error" in box:
        raise box["error"]
    return box["value"]


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
