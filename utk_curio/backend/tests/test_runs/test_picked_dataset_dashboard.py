"""A dataset widget an input picks, in a dashboard viewer's run: a visitor
picks another camera on the Settings tile, and the Data Loading node below it
loads the dataset that camera picks, read as the step's own run reads its
input.

Settings is pinned, its Camera a control a viewer changes; Load's Data widget
is picked by Settings' camera (``options.pickedBy: input_0.camera``), and Load
feeds a pinned chart. The sandbox is a fake behind ``sandbox_request``: it runs
a node as an artifact named after it, Settings' the dict its code returns, and
answers ``/get`` under the sandbox's rule for sessions. ``viewer`` is imported
inside each test, so a checkout without it fails each test on its own.
"""
from __future__ import annotations

import json
import re
import threading

import pytest

CODE = "curio.builtin/python-computation"
DATA_LOADING = "curio.builtin/data-loading"
CHART = "curio.builtin/vis-vega"
CHOICES = {
    "W042": "data.test.w042-records",
    "W065": "data.test.w065-records",
    "W06E": "data.test.w06e-records",
}


def _nodes():
    camera = {
        "name": "camera", "type": "choice", "label": "Camera", "default": "W042",
        "options": {"choices": sorted(CHOICES), "display": "radio"},
    }
    return [
        {"id": "settings", "type": CODE, "dashboardPinned": True,
         "content": '# node settings\nreturn {"camera": [!! camera !!]}',
         "metadata": {"widgets": [camera]}},
        {"id": "load", "type": DATA_LOADING,
         "content": "# node load\ndata = curio_load_data([!! data !!])\nreturn data",
         "metadata": {"widgets": [{
             "name": "data", "type": "dataset", "label": "Data", "default": "",
             "options": {"pickedBy": "input_0.camera", "choices": dict(CHOICES)},
         }]}},
        {"id": "chart", "type": CHART, "content": "{}", "dashboardPinned": True},
    ]


EDGES = [
    {"id": "settings-load", "source": "settings", "target": "load", "targetHandle": "in"},
    {"id": "load-chart", "source": "load", "target": "chart"},
]


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _create(client, token):
    resp = client.post("/api/projects", data=json.dumps({
        "name": "Picked dashboard",
        "spec": {"dataflow": {"name": "Picked dashboard", "nodes": _nodes(), "edges": EDGES}},
        "outputs": [],
    }), headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


class Reply:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = json.dumps(body)

    def json(self):
        return self._body

    def iter_content(self, chunk_size=1):
        yield self.text.encode("utf-8")

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _may_read(stored, session) -> bool:
    """The sandbox's rule (``parsers.session_may_read``), but for a read that
    names no session, which no read of a picked value may be."""
    from utk_curio.common.kept_sessions import is_kept_session

    if session is None:
        return False
    return stored is None or stored == session or (is_kept_session(stored) and is_kept_session(session))


class FakeSandbox:
    """Runs a node as an artifact named after it, Settings' the dict its code
    returns; answers ``/get`` under the session rule; describes and forgets
    the sessions it is asked about."""

    def __init__(self):
        self.lock = threading.Lock()
        self.runs = []
        self.values = {}
        self.writers = {}
        self.made = {}

    def __call__(self, method, path, **kwargs):
        if path == "/get":
            params = kwargs.get("params") or {}
            name, session = params.get("fileName"), params.get("sessionId")
            with self.lock:
                known = name in self.values and _may_read(self.writers.get(name), session)
                value = self.values.get(name)
            if not known:
                return Reply({"error": "KeyError", "message": f"'No artifact with id {name}'"}, 500)
            return Reply({"data": value, "dataType": "dict", "filename": name})
        body = json.loads(kwargs.get("data") or "{}")
        if path == "/artifact-sessions/describe":
            with self.lock:
                return Reply({"sessions": {
                    sid: {"bytes": 100, "ids": [self.made[sid]] if sid in self.made else []}
                    for sid in body["sessionIds"]
                }})
        if path in ("/artifact-sessions/forget", "/artifact-sessions/store"):
            return Reply({"forgotten": len(body.get("sessionIds") or [])})
        if path not in ("/exec", "/execJs"):
            return Reply({})
        node_id = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        with self.lock:
            self.runs.append((node_id, body))
            name = f"art-{node_id}-{len(self.runs)}"
            self.made[body["session_id"]] = name
            if node_id == "settings":
                camera = re.search(r'"camera": "(\w+)"', body["code"])
                self.values[name] = {"camera": camera.group(1) if camera else None}
                self.writers[name] = body["session_id"]
        kind = "dict" if node_id == "settings" else "dataframe"
        return Reply({"stdout": [f"ran {node_id}"], "stderr": "", "output": {"path": name, "dataType": kind}})


@pytest.fixture(autouse=True)
def _signed_in_instance(monkeypatch):
    """An instance with sign-in (``--deploy``) behind one proxy, as the hosted
    stacks run, where a visitor's dashboard runs."""
    from utk_curio.backend import config

    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    monkeypatch.setattr(config, "CURIO_PROXY_HOPS", 1)


@pytest.fixture()
def app(_signed_in_instance, app):
    """test_runs' app, built once the instance above is set."""
    return app


@pytest.fixture()
def sandbox(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.runs import jobs, viewer

    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    viewer.reset()
    fake = FakeSandbox()
    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    monkeypatch.setattr("utk_curio.backend.app.runs.viewer.sandbox_request", fake)
    monkeypatch.setattr("utk_curio.backend.app.runs.kept.sandbox_request", fake)
    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.infrastructure.sandbox_artifacts.wrapped_names",
        lambda art_id, saved_path=None: [],
    )
    return fake


@pytest.fixture()
def saved(monkeypatch):
    """The dashboard's saved outputs: none, so the run makes every one."""
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.runs import viewer

    monkeypatch.setattr(
        viewer, "_saved_state", lambda user_key, project_id: (storage.read_spec(user_key, project_id), []),
    )


def _run(client, project_id, values):
    from utk_curio.backend.app.runs import viewer
    from utk_curio.backend.extensions import db

    started = client.post(
        f"/api/projects/{project_id}/dashboard/runs",
        data=json.dumps({"values": values}),
        headers={"Content-Type": "application/json", "X-Forwarded-For": "10.0.0.1"},
    )
    assert started.status_code == 202, started.get_data(as_text=True)
    job = viewer.REGISTRY.get_job(started.get_json()["runId"])
    job.thread.join(timeout=30)
    assert not job.thread.is_alive()
    db.session.rollback()
    return started.get_json()


@pytest.mark.parametrize("camera", ["W065", "W06E"])
def test_a_visitors_camera_picks_the_dataset_the_loader_reads(client, user_and_token, sandbox, saved, camera):
    _, token = user_and_token
    project_id = _create(client, token)

    _run(client, project_id, {"settings": {"camera": camera}})

    loads = [body for node_id, body in sandbox.runs if node_id == "load"]
    ran = [node_id for node_id, _ in sandbox.runs]
    assert len(loads) == 1, f"the loader did not run; the steps that ran: {ran}"
    assert f'curio_load_data("{CHOICES[camera]}")' in loads[0]["code"], loads[0]["code"]
