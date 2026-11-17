"""What a run on the server says while a node's first run downloads what it reads.

A node that loads a model whose weights its package's ``fetch`` names downloads
them on its first run, before the sandbox runs it (``execution/node_exec.py``),
as a dataset a pip install leaves out is. The run's stream says how far each
download has come: ``step_progress`` events of the node's step, each with a
message, between its ``step_started`` and its ``step_finished``, and one with
no message once the downloads are over and the node runs. The canvas shows
them on the node while it runs (``providers/flow/useServerRun.ts``).

The model package is the one ``test_model_catalog/test_fetched_weights.py``
makes, in this test's own folder; Hugging Face and the sandbox are fakes. The
code under test is imported inside each test.
"""
from __future__ import annotations

import json

TRACK = "track"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _events(client, token, run_id):
    resp = client.get(f"/api/runs/{run_id}/stream", headers=_auth(token))
    assert resp.status_code == 200
    events = []
    for block in resp.get_data(as_text=True).strip().split("\n\n"):
        kind = block.split("\n", 1)[0].removeprefix("event: ")
        events.append((kind, json.loads(block.split("data: ", 1)[1])))
    return events


def test_a_runs_stream_says_how_far_a_nodes_weights_have_come_while_they_download(
    client, user_and_token, tmp_curio, monkeypatch,
):
    from utk_curio.backend import config
    from utk_curio.backend.app.runs import jobs
    from utk_curio.backend.extensions import db
    from utk_curio.backend.tests._support.fetched_weights import FakeHuggingFace
    from utk_curio.backend.tests.test_model_catalog import test_fetched_weights as weights

    user, token = user_and_token
    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    catalog = tmp_curio / "catalog"
    weights._write_package(catalog / weights.DIR)
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(catalog))
    monkeypatch.delenv("CURIO_MODEL_WEIGHTS_DIR", raising=False)
    weights._add(weights._key(user), catalog)
    FakeHuggingFace(
        weights.REPOSITORY, weights.REVISION, weights.FILES, redirect=("model.safetensors",), chunk_size=16,
    ).serve(monkeypatch)
    asked = []

    class Reply:
        status_code = 200
        text = ""

        def json(self):
            return {"stdout": ["ran"], "stderr": "", "output": {"path": "art-track", "dataType": "int"}}

    monkeypatch.setattr(
        "utk_curio.backend.app.execution.node_exec.sandbox_request",
        lambda method, path, **kwargs: asked.append(json.loads(kwargs["data"])) or Reply(),
    )
    created = client.post("/api/projects", data=json.dumps({
        "name": "Track", "outputs": [],
        "spec": {"dataflow": {"name": "Track", "edges": [], "nodes": [{
            "id": TRACK, "type": "curio.builtin/python-computation",
            "content": f'model = curio_load_model("{weights.PACKAGE_ID}")\nreturn 1',
        }]}},
    }), headers=_auth(token))
    assert created.status_code == 201, created.get_data(as_text=True)
    started = client.post(f"/api/projects/{created.get_json()['id']}/runs", data=json.dumps({}), headers=_auth(token))
    assert started.status_code == 202, started.get_data(as_text=True)
    run_id = started.get_json()["id"]
    job = jobs.REGISTRY.get_job(run_id)
    job.thread.join(timeout=30)
    assert not job.thread.is_alive()
    db.session.rollback()

    events = _events(client, token, run_id)

    kinds = [kind for kind, _payload in events]
    progress = [payload for kind, payload in events if kind == "step_progress"]
    assert progress, f"the run said nothing while the node's weights downloaded: {kinds}"
    first, last = kinds.index("step_progress"), len(kinds) - 1 - kinds[::-1].index("step_progress")
    assert kinds.index("step_started") < first and last < kinds.index("step_finished"), kinds
    assert {payload["nodeId"] for payload in progress} == {TRACK}
    downloading = [payload for payload in progress if "model.safetensors" in payload["message"]]
    assert (downloading[0]["done"], downloading[-1]["done"], downloading[-1]["total"]) == (
        0, len(weights.WEIGHTS), len(weights.WEIGHTS),
    ), downloading
    assert [payload["done"] for payload in downloading] == sorted(payload["done"] for payload in downloading)
    # 256 chunks come, and the node is told of a whole percent at most.
    assert 3 <= len(downloading) <= 101, len(downloading)
    assert "100%" in downloading[-1]["message"], downloading[-1]
    # The downloads over, the node runs: its last word says no more of them.
    assert progress[-1]["message"] == "", progress[-1]
    assert len(asked) == 1, "the sandbox was not asked to run the node once its weights were here"
    finished = next(payload for kind, payload in events if kind == "step_finished")
    assert finished["status"] == "ok", finished
