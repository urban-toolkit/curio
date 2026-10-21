"""A run on the server runs an Autark node whose document only loads data, as
the node's own run in the browser does (``autkGrammarBehavior`` and
``autkLayerMaterialize.ts::runDataInBackend``):

- the document, its references resolved, compiled by the browser's own
  compiler, the frontend's ``dist/autk-data-compile.cjs``;
- that JavaScript posted to the sandbox's ``/execJs`` with no input and no
  dataset of its own, and tried once more when it fails;
- its output, the sandbox's layer list, recorded in the dataflow as the canvas
  saves it, so a node below a Data Pool reads the layers from it.

The sandbox is a fake behind ``node_exec.sandbox_request``; the compiler is
the one the frontend build ships. ``runs`` is imported inside each test, so a
checkout without it fails each test on its own.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
EXAMPLE_06 = REPO / "docs" / "examples" / "06-back-bay-road-sunlight.json"
CODE = "curio.builtin/computation-analysis"
AUTARK = "curio.builtin/autk-grammar"
LAYERS = "art-layers"
BACK_BAY_LAYERS = [
    "table_osm_surface", "table_osm_parks", "table_osm_water", "table_osm_roads", "table_osm_buildings",
]


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class LayerSandbox:
    """Answers ``/execJs`` with the layer list an Autark data load leaves (a
    ``list`` artifact) and ``/exec`` with a table; *fail_loads* loads fail
    first. Keeps every request, in order."""

    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        self.fail_loads = 0

    def bodies(self, path):
        return [body for sent, body in self.requests if sent == path]

    def __call__(self, method, path, **kwargs):
        body = json.loads(kwargs["data"])
        self.requests.append((path, body))
        if path == "/execJs" and self.fail_loads > 0:
            self.fail_loads -= 1
            reply = {"stdout": [], "stderr": "TypeError: fetch failed", "output": {"path": "", "dataType": "str"}}
        elif path == "/execJs":
            reply = {"stdout": ["OSM data loaded"], "stderr": "", "output": {"path": LAYERS, "dataType": "list"}}
        else:
            reply = {"stdout": [], "stderr": "",
                     "output": {"path": f"art-table-{len(self.requests)}", "dataType": "dataframe"}}

        class Reply:
            status_code = 200
            text = ""

            def json(_self):
                return reply

        return Reply()


@pytest.fixture()
def sandbox(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.runs import jobs

    # Nothing is installed: the fake artifacts are not files.
    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    fake = LayerSandbox()
    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    return fake


@pytest.fixture()
def recorded(monkeypatch):
    """The outputs a run records in the dataflow, as it hands them over."""
    from utk_curio.backend.app.projects import services as project_services

    outputs = []
    monkeypatch.setattr(
        project_services, "record_node_outputs",
        lambda user, project_id, refs, warnings=None: outputs.extend(refs) or [],
    )
    return outputs


def _create(client, token, dataflow):
    resp = client.post("/api/projects", data=json.dumps({
        "name": dataflow.get("name") or "Autark data run",
        "spec": {"dataflow": dataflow},
        "outputs": [],
    }), headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _run(client, token, project_id):
    from utk_curio.backend.app.runs import jobs
    from utk_curio.backend.extensions import db

    started = client.post(f"/api/projects/{project_id}/runs", data="{}", headers=_auth(token))
    assert started.status_code in (200, 201, 202), started.get_data(as_text=True)
    run_id = started.get_json()["id"]
    job = jobs.REGISTRY.get_job(run_id)
    assert job is not None
    job.thread.join(timeout=60)
    assert not job.thread.is_alive()
    db.session.rollback()
    resp = client.get(f"/api/runs/{run_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _node_content(dataflow, node_id):
    return next(n["content"] for n in dataflow["nodes"] if n["id"] == node_id)


def test_example_06s_loader_runs_on_the_server_as_the_browser_runs_it(client, user_and_token, sandbox, recorded):
    from utk_curio.common.autk_data_compiler import compile_data_spec

    user, token = user_and_token
    dataflow = json.loads(EXAMPLE_06.read_text(encoding="utf-8"))["dataflow"]
    run = _run(client, token, _create(client, token, dataflow))
    steps = {s["nodeId"]: s for s in run["steps"]}

    loader = steps["whatif-data"]
    assert (loader["role"], loader["status"]) == ("run", "ok"), loader
    assert (loader["outputPath"], loader["outputType"]) == (LAYERS, "list"), loader

    # The JavaScript the node's run in the browser posts: its document through
    # the browser's compiler, the extract's URL left for the sandbox to resolve.
    (load,) = sandbox.bodies("/execJs")
    assert load["code"] == compile_data_spec(_node_content(dataflow, "whatif-data"))
    assert load["code"].startswith(
        "import { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } from '@urban-toolkit/autk-db';"
    )
    assert '"pbfFileUrl":"__CURIO_BACKEND_URL__/file/docs/examples/data/back_bay.osm.pbf"' in load["code"]
    assert f"const __expectedTables = {json.dumps(BACK_BAY_LAYERS, separators=(',', ':'))};" in load["code"]
    # No input, no input circles, and no dataset of its own: the layer list is
    # its output, as runDataInBackend posts it.
    assert (load["file_path"], load["dataType"]) == ("", "")
    assert "input_slots" not in load
    assert load["save_dataset"] is False
    assert load["nodeType"] == AUTARK

    # Saved as the canvas saves it: the list artifact itself, which the save
    # installs as one JSON dataset. It is the scenarios' fixed context.
    (saved,) = [ref for ref in recorded if ref.node_id == "whatif-data"]
    assert (saved.filename, saved.data_type) == (LAYERS, "list")

    # The pool hands the layers on: the only node the run can execute next is
    # below it (the Map Edits node), and it reads them.
    assert steps["whatif-pool"]["status"] == "forwarded"
    for body in sandbox.bodies("/exec"):
        assert (body["file_path"], body["dataType"]) == (LAYERS, "list"), body
    # Only the browser computes the shadows, so the run waits for a tab.
    for compute in ("whatif-baseline-compute", "whatif-modified-compute"):
        assert steps[compute]["role"] == "browser", steps[compute]
    assert run["status"] == "needs_canvas", run["status"]


def test_a_node_below_a_pool_reads_the_layers_the_load_made(client, user_and_token, sandbox, recorded):
    user, token = user_and_token
    load = json.dumps({"data": [{
        "type": "osm", "pbfFileUrl": "docs/examples/data/chicago_loop.osm.pbf", "outputTableName": "table_osm",
        "autoLoadLayers": {"layers": ["roads"]},
    }]})
    run = _run(client, token, _create(client, token, {
        "name": "Loop roads",
        "nodes": [
            {"id": "loop", "type": AUTARK, "content": load},
            {"id": "pool", "type": "curio.builtin/data-pool", "content": ""},
            {"id": "count", "type": CODE, "content": "return len(input_0)"},
        ],
        "edges": [{"id": "loop-pool", "source": "loop", "target": "pool"},
                  {"id": "pool-count", "source": "pool", "target": "count"}],
    }))
    steps = {s["nodeId"]: s for s in run["steps"]}
    assert [steps[n]["status"] for n in ("loop", "pool", "count")] == ["ok", "forwarded", "ok"]
    assert run["status"] == "succeeded"
    (counted,) = sandbox.bodies("/exec")
    # The artifact the canvas sends it too: the load's, which the pool read.
    assert (counted["file_path"], counted["dataType"]) == (LAYERS, "list")
    assert counted["input_slots"] == [0]


def test_a_failed_load_is_tried_once_more(client, user_and_token, sandbox, recorded):
    user, token = user_and_token
    sandbox.fail_loads = 1
    content = json.dumps({"data": [{"type": "osm", "pbfFileUrl": "docs/examples/data/back_bay.osm.pbf",
                                    "outputTableName": "table_osm", "autoLoadLayers": {"layers": ["water"]}}]})
    run = _run(client, token, _create(client, token, {
        "name": "Back Bay water",
        "nodes": [{"id": "water", "type": AUTARK, "content": content, "saveOutputDataset": True}],
        "edges": [],
    }))
    (step,) = run["steps"]
    assert (step["status"], step["outputPath"]) == ("ok", LAYERS), step
    first, second = sandbox.bodies("/execJs")
    assert first["code"] == second["code"]
    assert [(ref.node_id, ref.filename, ref.data_type) for ref in recorded] == [("water", LAYERS, "list")]


def test_a_load_that_fails_twice_fails_the_node(client, user_and_token, sandbox, recorded):
    user, token = user_and_token
    sandbox.fail_loads = 2
    content = json.dumps({"data": [{"type": "osm", "pbfFileUrl": "docs/examples/data/back_bay.osm.pbf",
                                    "outputTableName": "table_osm", "autoLoadLayers": {"layers": ["water"]}}]})
    run = _run(client, token, _create(client, token, {
        "name": "Back Bay water",
        "nodes": [{"id": "water", "type": AUTARK, "content": content, "saveOutputDataset": True}],
        "edges": [],
    }))
    (step,) = run["steps"]
    assert step["status"] == "error", step
    assert "fetch failed" in (step["stderrTail"] or "")
    assert len(sandbox.bodies("/execJs")) == 2
    assert recorded == []
    assert run["status"] == "failed"
