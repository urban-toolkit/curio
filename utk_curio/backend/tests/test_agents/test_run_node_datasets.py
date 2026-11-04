"""Running a node from an agent's chat reads the Data Catalog datasets its run names.

An agent's chat runs the dataflow through one of its nodes on the server
(``run_node_stream``). Each node that run reaches goes to the sandbox with the
paths of the Data Catalog datasets its code names, as Play sends them: a
literal ``curio_load_data("<id>")``, a Data Loading node's Data widget, whose
id is in no literal call until the run writes it in (``node_run_code``), and
a layer group, whose entry names its layers. Without them the sandbox answers
"Dataset '<id>' is not available in this environment".

Every test imports what it tests inside itself, so a checkout without it fails
test by test.
"""
from __future__ import annotations

import io
import json

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth

LOADER = "curio.builtin/data-loading"
COMPUTATION = "curio.builtin/computation-analysis"
STARTER = "data = curio_load_data([!! data !!])\nreturn data\n"
ATTACHMENT = "att-run-node"


def _import_csv(client, token) -> str:
    resp = client.post(
        "/api/datasets/import",
        headers=_auth(token),
        data={"file": (io.BytesIO(b"tree_id,height\n1,10\n2,12\n"), "trees.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _loader(content: str, widgets: list | None = None) -> dict:
    return {
        "id": "load", "type": LOADER, "content": content, "in": "DEFAULT", "out": "DEFAULT",
        "goal": "", "metadata": {"widgets": widgets or []},
    }


def _save_under_an_agent(user, project_id: str, loader: dict) -> None:
    """Saves *loader* and a Python node after it, with an agent attached to
    that node, as a chat that runs it has one."""
    from utk_curio.backend.app.projects import storage as projects_storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    key = _user_dir_key(user)
    spec = projects_storage.read_spec(key, project_id)
    dataflow = spec["dataflow"]
    dataflow["nodes"] = [
        loader,
        {
            "id": "after", "type": COMPUTATION, "content": "return input_0\n",
            "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {},
        },
    ]
    dataflow["edges"] = [{"id": "reactflow__edge-loadout-afterin", "source": "load", "target": "after"}]
    dataflow["agentAttachments"] = [{
        "attachmentId": ATTACHMENT, "coord": "agent.curio.node-builder@1",
        "target": {"kind": "node", "targetId": "after"},
    }]
    projects_storage.write_spec(key, project_id, spec)


def _run_through_the_node_after(client, token, project_id: str, monkeypatch) -> tuple[dict, list[dict]]:
    """Runs the dataflow through the node after the loader from the agent's
    chat, the sandbox stood in for. Returns the run's ``done`` and what each
    node of the run sent the sandbox, in order."""
    sent: list[dict] = []

    def _exec(_endpoint, payload):
        sent.append(payload)
        return {"stdout": ["ran"], "stderr": "", "output": {"path": f"art-{len(sent)}", "dataType": "dataframe"}}

    monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
    response = client.post(
        f"/api/agents/projects/{project_id}/attachments/{ATTACHMENT}/run-node",
        json={"nodeId": "after"}, headers=_auth(token),
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    events = []
    for block in response.get_data(as_text=True).strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    name, done = events[-1]
    assert name == "done", events
    return done, sent


@pytest.mark.parametrize("held_by", ["data widget", "literal call"])
def test_a_run_through_a_node_after_a_data_loading_node_sends_the_datasets_path(
    client, user_and_token, tmp_curio, alice_project, tmp_path, monkeypatch, held_by,
):
    user, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    dataset_id = _import_csv(client, token)
    if held_by == "data widget":
        data = {"name": "data", "type": "dataset", "label": "Data", "default": "", "value": dataset_id}
        loader = _loader(STARTER, [data])
    else:
        loader = _loader(f'data = curio_load_data("{dataset_id}")\nreturn data\n')
    _save_under_an_agent(user, alice_project, loader)

    done, sent = _run_through_the_node_after(client, token, alice_project, monkeypatch)

    assert done["ok"] is True, done
    assert done["order"] == ["load", "after"], done
    loading = sent[0]
    # The run wrote the id into the loader's code, the widget's included.
    assert f'curio_load_data("{dataset_id}")' in loading["code"], loading["code"]
    paths = loading.get("dataset_paths") or {}
    assert list(paths) == [dataset_id], f"the loader was sent no path for {dataset_id}: {loading}"
    assert paths[dataset_id].endswith("trees.csv"), paths


def test_a_run_through_a_node_after_a_layer_groups_loader_sends_its_layers_and_its_entry(
    client, user_and_token, tmp_curio, alice_project, tmp_path, monkeypatch,
):
    from utk_curio.backend.tests.test_datasets.test_layer_group_execution import _imported_group

    user, token = user_and_token
    group_id, layers = _imported_group(client, token, tmp_path, monkeypatch)
    _save_under_an_agent(user, alice_project, _loader(f'layers = curio_load_data("{group_id}")\nreturn layers\n'))

    done, sent = _run_through_the_node_after(client, token, alice_project, monkeypatch)

    assert done["ok"] is True, done
    loading = sent[0]
    assert set(loading.get("dataset_paths") or {}) == {i for _name, i in layers}, loading
    assert (loading.get("dataset_formats") or {}).get(group_id) == {
        "format": "layer-group", "layers": [[name, i] for name, i in layers],
    }, loading
