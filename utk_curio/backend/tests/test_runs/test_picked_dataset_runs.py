"""A dataset widget an input picks, in runs on the server: Run All and a node's
play read the value on the circle the widget names, as the node's own run
reads that input, and write the dataset that value picks into the code they
send, so the run reads that dataset and no other.

The Data Loading node here, Load, reads its Data widget, which the camera of
the Settings node wired into its first circle picks
(``options.pickedBy: input_0.camera``) among three choices. The sandbox is a
fake behind ``node_exec.sandbox_request``: it runs a node as an artifact named
after it, Settings' a dict, and answers ``/get`` as the sandbox does, under
its rule for sessions (``parsers.session_may_read``), which a read with no
session does not pass here: a value is read only as the node's own run would
read its input. ``runs`` is imported inside each test, so a checkout without
it fails each test on its own.
"""
from __future__ import annotations

import json
import threading

import pytest

CODE = "curio.builtin/python-computation"
DATA_LOADING = "curio.builtin/data-loading"
CHOICES = {
    "W042": "data.test.w042-records",
    "W065": "data.test.w065-records",
    "W06E": "data.test.w06e-records",
}
#: What a value no read of it may show: the read that would show it is refused.
SECRET = "a value of another tab"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _nodes():
    settings = {
        "id": "settings", "type": CODE,
        "content": '# node settings\nreturn {"camera": "W042"}',
    }
    load = {
        "id": "load", "type": DATA_LOADING,
        "content": "# node load\ndata = curio_load_data([!! data !!])\nreturn data",
        "metadata": {"widgets": [{
            "name": "data", "type": "dataset", "label": "Data", "default": "",
            "options": {"pickedBy": "input_0.camera", "choices": dict(CHOICES)},
        }]},
    }
    return [settings, load]


EDGES = [{"id": "settings-load", "source": "settings", "target": "load", "targetHandle": "in"}]


def _create(client, token):
    resp = client.post("/api/projects", data=json.dumps({
        "name": "Picked loader",
        "spec": {"dataflow": {"name": "Picked loader", "nodes": _nodes(), "edges": EDGES}},
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
    """Runs a node as an artifact named after it, Settings' the dict
    :attr:`settings` holds; answers ``/get`` with a value under the session
    rule; records every ``/exec`` body and every read."""

    def __init__(self):
        self.lock = threading.Lock()
        self.bodies = {}
        self.values = {}
        self.writers = {}
        self.reads = []
        self.settings = {"camera": "W042"}

    def hold(self, name, value, session):
        """*name* holds *value*, written under *session*: an output a tab's
        play made, which a run reuses."""
        with self.lock:
            self.values[name] = value
            self.writers[name] = session

    def __call__(self, method, path, **kwargs):
        if path == "/get":
            params = kwargs.get("params") or {}
            name, session = params.get("fileName"), params.get("sessionId")
            with self.lock:
                self.reads.append({"fileName": name, "sessionId": session, "savedPath": params.get("savedPath")})
                known = name in self.values and _may_read(self.writers.get(name), session)
                value = self.values.get(name)
            if not known:
                return Reply({"error": "KeyError", "message": f"'No artifact with id {name}'"}, 500)
            kind = "dict" if isinstance(value, dict) else type(value).__name__
            return Reply({"data": value, "dataType": kind, "filename": name})
        if path not in ("/exec", "/execJs"):
            return Reply({})
        body = json.loads(kwargs.get("data") or "{}")
        node_id = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        name = f"art-{node_id}"
        with self.lock:
            self.bodies[node_id] = body
            if node_id == "settings":
                self.values[name] = dict(self.settings)
                self.writers[name] = body.get("session_id")
        kind = "dict" if node_id == "settings" else "dataframe"
        return Reply({"stdout": [f"ran {node_id}"], "stderr": "", "output": {"path": name, "dataType": kind}})


@pytest.fixture()
def sandbox(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.runs import jobs

    # Nothing is installed: the fake artifacts are not files.
    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    fake = FakeSandbox()
    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    # Settings' dict is no stored bundle of outputs; asked of no sandbox.
    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.infrastructure.sandbox_artifacts.wrapped_names",
        lambda art_id, saved_path=None: [],
    )
    return fake


def _start(client, token, project_id, **body):
    return client.post(f"/api/projects/{project_id}/runs", data=json.dumps(body), headers=_auth(token))


def _steps(client, token, project_id, **body):
    from utk_curio.backend.app.runs import jobs
    from utk_curio.backend.extensions import db

    started = _start(client, token, project_id, **body)
    assert started.status_code == 202, started.get_data(as_text=True)
    run_id = started.get_json()["id"]
    job = jobs.REGISTRY.get_job(run_id)
    job.thread.join(timeout=30)
    assert not job.thread.is_alive()
    db.session.rollback()
    resp = client.get(f"/api/runs/{run_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {step["nodeId"]: step for step in resp.get_json()["steps"]}


class TestRunAllLoadsTheDatasetTheInputPicks:
    @pytest.mark.parametrize("camera", sorted(CHOICES))
    def test_each_camera_loads_its_own_dataset(self, client, user_and_token, sandbox, camera):
        _, token = user_and_token
        project_id = _create(client, token)
        sandbox.settings = {"camera": camera, "model": "YOLOv8n"}

        steps = _steps(client, token, project_id)

        assert steps["load"]["status"] == "ok", steps["load"].get("stderrTail")
        sent = sandbox.bodies["load"]["code"]
        assert f'curio_load_data("{CHOICES[camera]}")' in sent, sent
        assert all(other not in sent for other in CHOICES.values() if other != CHOICES[camera]), sent

    def test_the_value_is_read_as_the_loaders_own_run_reads_its_input(self, client, user_and_token, sandbox):
        """Settings' output is read once, under a session that may read it as
        the loader's run reads it: no read names no session."""
        _, token = user_and_token
        project_id = _create(client, token)

        steps = _steps(client, token, project_id)

        assert steps["load"]["status"] == "ok", steps["load"].get("stderrTail")
        reads = [read for read in sandbox.reads if read["fileName"] == "art-settings"]
        assert len(reads) == 1, sandbox.reads
        assert reads[0]["sessionId"], reads


class TestAPlayLoadsTheDatasetTheInputPicks:
    def test_a_play_of_the_loader_reads_the_output_its_tab_holds(self, client, user_and_token, sandbox):
        """A play of the loader reuses Settings' output, which the tab's own
        play made: its value picks the dataset."""
        _, token = user_and_token
        project_id = _create(client, token)
        sandbox.hold("art-settings-held", {"camera": "W06E"}, token)

        steps = _steps(
            client, token, project_id,
            target="load", reuse={"settings": {"path": "art-settings-held", "dataType": "dict"}},
        )

        assert list(steps) == ["load"]
        assert steps["load"]["status"] == "ok", steps["load"].get("stderrTail")
        assert 'curio_load_data("data.test.w06e-records")' in sandbox.bodies["load"]["code"]

    def test_an_output_another_session_made_is_not_read(self, client, user_and_token, sandbox):
        """A reused output this account's run may not read is not read for
        the pick either: the loader fails without showing what it holds."""
        _, token = user_and_token
        project_id = _create(client, token)
        sandbox.hold("art-foreign", {"camera": SECRET}, "a tab of someone else")

        steps = _steps(
            client, token, project_id,
            target="load", reuse={"settings": {"path": "art-foreign", "dataType": "dict"}},
        )

        assert steps["load"]["status"] == "error"
        assert "load" not in sandbox.bodies
        stderr = steps["load"].get("stderrTail") or ""
        assert "input_0 could not be read" in stderr, stderr
        assert SECRET not in stderr, stderr


class TestAValueNoChoiceNames:
    def test_is_refused_with_the_value_and_the_choices(self, client, user_and_token, sandbox):
        _, token = user_and_token
        project_id = _create(client, token)
        sandbox.settings = {"camera": "W999"}

        steps = _steps(client, token, project_id)

        assert steps["load"]["status"] == "error"
        assert "load" not in sandbox.bodies
        stderr = steps["load"].get("stderrTail") or ""
        assert 'Data has no choice for "W999", the value of input_0.camera.' in stderr, stderr
        assert 'Its choices are "W042", "W065" and "W06E".' in stderr, stderr
