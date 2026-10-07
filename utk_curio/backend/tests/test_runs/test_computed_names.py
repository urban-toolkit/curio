"""One node, one name in the Data Catalog, whichever path saves its output (#775).

The name is the one the node's canvas header shows: its renamed header, else
its template's label, else its type in words without the version. A save from
the canvas sends that name (``resolveNodeDisplayLabel``). A run on the server
used to name the same Python Computation node "Computation Analysis@1", from
its type, both when its play installed the output and when the run recorded
it, so the dataset's title depended on which path wrote it last.

Every writer installs through ``bundle.install_node_output``: a spy records the
name each one passes and calls through, so the catalog title is checked as
well. The sandbox is a fake that answers with a real JSON artifact.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pytest

#: (node type as a palette drop saves it, renamed header, the name its header shows)
NODES = [
    pytest.param("curio.builtin/computation-analysis@1", None, "Python Computation", id="python-computation"),
    pytest.param("curio.builtin/data-loading@1", None, "Data Loading", id="data-loading"),
    pytest.param("curio.builtin/computation-analysis@1", "Dict output", "Dict output", id="renamed-header"),
]

NODE_ID = "named-node"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _artifact(payload) -> str:
    """A JSON artifact in shared storage, named as the sandbox names one."""
    name = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.json"
    (Path(os.environ["CURIO_SHARED_DATA"]) / name).write_text(json.dumps(payload), encoding="utf-8")
    return name


@pytest.fixture()
def shared(tmp_curio, monkeypatch):
    from utk_curio.sandbox.util.db import release_connection

    release_connection()
    data = tmp_curio / ".curio" / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CURIO_SHARED_DATA", str(data))
    yield data
    release_connection()


@pytest.fixture()
def names(monkeypatch):
    """The name each install is given, in order; the install still happens."""
    from utk_curio.backend.app.datasets.install import bundle

    seen: list = []
    real = bundle.install_node_output

    def spy(*args, **kwargs):
        seen.append(kwargs.get("node_name"))
        return real(*args, **kwargs)

    monkeypatch.setattr(bundle, "install_node_output", spy)
    return seen


@pytest.fixture()
def sandbox(monkeypatch, shared):
    """Answers every ``/exec`` with a fresh JSON artifact."""
    from utk_curio.backend import config
    from utk_curio.backend.app.runs import jobs

    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    produced: list = []

    def fake(method, path, **kwargs):
        name = _artifact({"value": len(produced) + 1})
        produced.append(name)

        class Reply:
            status_code = 200
            text = ""

            def json(_self):
                return {"stdout": [], "stderr": "", "output": {"path": name, "dataType": "dict"}}

        return Reply()

    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    return produced


def _node(node_type: str, header) -> dict:
    node = {
        "id": NODE_ID,
        "type": node_type,
        "content": "return {'value': 1}",
        "saveOutputDataset": True,
    }
    if header:
        node["metadata"] = {"packageTemplateLabel": header}
    return node


def _create(client, token, node: dict) -> str:
    resp = client.post("/api/projects", data=json.dumps({
        "name": "One name per node",
        "spec": {"dataflow": {"name": "One name per node", "nodes": [node], "edges": []}},
        "outputs": [],
    }), headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _run(client, token, project_id) -> dict:
    """Start a run of the whole dataflow, wait for it, and return it."""
    from utk_curio.backend.app.runs import jobs
    from utk_curio.backend.extensions import db

    resp = client.post(f"/api/projects/{project_id}/runs", data="{}", headers=_auth(token))
    assert resp.status_code in (200, 201, 202), resp.get_data(as_text=True)
    run_id = resp.get_json()["id"]
    job = jobs.REGISTRY.get_job(run_id)
    assert job is not None
    job.thread.join(timeout=30)
    assert not job.thread.is_alive()
    db.session.rollback()
    resp = client.get(f"/api/runs/{run_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _save(client, token, project_id, node: dict, outputs: list) -> None:
    resp = client.put(f"/api/projects/{project_id}", data=json.dumps({
        "spec": {"dataflow": {"name": "One name per node", "nodes": [node], "edges": []}},
        "outputs": outputs,
    }), headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json().get("dataset_install_warnings") == [], resp.get_json()


def _catalog_title(client, token, project_id) -> str:
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    dataset_id = computed_dataset_id(NODE_ID, project_id)
    resp = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}", headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    items = resp.get_json()["items"]
    item = next((i for i in items if i["id"] == dataset_id), None)
    assert item is not None, f"no computed dataset {dataset_id}: {[i['id'] for i in items]}"
    return item["title"]


@pytest.mark.parametrize("node_type, header, expected", NODES)
def test_a_run_on_the_server_names_the_node_as_its_header_does(
    client, user_and_token, sandbox, names, node_type, header, expected,
):
    _, token = user_and_token
    project_id = _create(client, token, _node(node_type, header))

    run = _run(client, token, project_id)

    step = next(s for s in run["steps"] if s["nodeId"] == NODE_ID)
    assert step["status"] == "ok", step
    # The play installs the output, then the run records it: two writes, one name.
    assert len(names) == 2, names
    assert names == [expected, expected], (
        f"a run on the server named the node {names}, its header reads {expected!r}"
    )
    # What the run calls the node, in its steps and in a "the node feeding
    # this one failed" reason, is the same name.
    assert step["label"] == expected
    assert _catalog_title(client, token, project_id) == expected


@pytest.mark.parametrize("node_type, header, expected", NODES)
def test_a_save_that_sends_no_name_names_the_node_as_its_header_does(
    client, user_and_token, shared, names, node_type, header, expected,
):
    """A client that leaves ``node_name`` out of an output ref (anything but
    the canvas) gets the name the canvas would have sent."""
    _, token = user_and_token
    node = _node(node_type, header)
    project_id = _create(client, token, node)

    _save(client, token, project_id, node, [
        {"node_id": NODE_ID, "filename": _artifact({"value": 1}), "data_type": "dict"},
    ])

    assert names == [expected]
    assert _catalog_title(client, token, project_id) == expected


@pytest.mark.parametrize("node_type, header, expected", NODES)
def test_a_run_then_a_canvas_save_keep_one_name(
    client, user_and_token, sandbox, names, node_type, header, expected,
):
    """The order in the issue: a run on the server writes the dataset, then
    the canvas saves and re-installs it under the name its header shows. Every
    write gives the node that one name, with no version suffix."""
    _, token = user_and_token
    node = _node(node_type, header)
    project_id = _create(client, token, node)

    _run(client, token, project_id)
    first_title = _catalog_title(client, token, project_id)
    _save(client, token, project_id, node, [{
        "node_id": NODE_ID, "filename": _artifact({"value": 2}), "data_type": "dict",
        # What ``buildOutputRefs`` sends: ``resolveNodeDisplayLabel`` of the node.
        "node_name": expected,
    }])

    assert set(names) == {expected}, names
    assert first_title == _catalog_title(client, token, project_id) == expected
    assert "@" not in expected
