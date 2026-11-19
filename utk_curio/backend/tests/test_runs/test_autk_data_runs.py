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
CODE = "curio.builtin/python-computation"
AUTARK = "curio.builtin/autk-grammar"
LAYERS = "art-layers"
BACK_BAY_LAYERS = [
    "table_osm_surface", "table_osm_parks", "table_osm_water", "table_osm_roads", "table_osm_buildings",
]
EXAMPLE_34 = REPO / "docs" / "examples" / "34-autark-park-access-heatmap.json"
#: The tables example 34's data node makes: the tip's layers, then its heatmap.
TIP_TABLES = ["tip_surface", "tip_parks", "tip_water", "tip_roads", "park_access"]
EXAMPLE_36 = REPO / "docs" / "examples" / "36-autark-green-share-summer-heat.json"
#: The tables example 36's data node makes: Niterói's layers, then its GeoTIFF.
GREEN_TABLES = ["table_osm_surface", "table_osm_parks", "table_osm_roads", "lst"]
EXAMPLE_37 = REPO / "docs" / "examples" / "37-autark-park-area-summer-heat.json"
#: The tables example 37's data node makes: Niterói's layers, its GeoTIFF, its
#: parks with their areas, then the heatmap that sums them.
PARK_AREA_TABLES = ["table_osm_surface", "table_osm_roads", "lst", "park_areas", "park_area"]
#: The files examples 36 and 37 load, as their code names them for the sandbox.
NITEROI_EXTRACT = '"pbfFileUrl":"__CURIO_BACKEND_URL__/file/docs/examples/data/niteroi.osm.pbf"'
NITEROI_SUMMERS = '"geotiffFileUrl":"__CURIO_BACKEND_URL__/file/docs/examples/data/niteroi_lst_verao_2001_2024.tif"'
NITEROI_PARKS = '"geojsonFileUrl":"__CURIO_BACKEND_URL__/file/docs/examples/data/niteroi_parks.geojson"'


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

            def json(self):
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
    # below it (the Edit Features node), and it reads them.
    assert steps["whatif-pool"]["status"] == "forwarded"
    for body in sandbox.bodies("/exec"):
        assert (body["file_path"], body["dataType"]) == (LAYERS, "list"), body
    # Only the browser computes the shadows, so the run waits for a tab.
    for compute in ("whatif-baseline-compute", "whatif-modified-compute"):
        assert steps[compute]["role"] == "browser", steps[compute]
    assert run["status"] == "needs_canvas", run["status"]


def test_example_34s_loader_builds_its_heatmap_on_the_server_as_the_browser_does(
    client, user_and_token, sandbox, recorded,
):
    """Example 34's data node loads the tip of Lower Manhattan from the
    repository's extract and bins its parks into a heatmap. On the server it
    posts the code the browser's compiler gives: autk-db, then the grammar's
    ``./data`` entry, which builds the heatmap, the extract's URL left for the
    sandbox to resolve, the layers and the heatmap's table expected, and no
    table the heatmap bins missing. The Python step reads the load's list."""
    from utk_curio.common.autk_data_compiler import compile_data_spec

    user, token = user_and_token
    dataflow = json.loads(EXAMPLE_34.read_text(encoding="utf-8"))["dataflow"]
    run = _run(client, token, _create(client, token, dataflow))
    steps = {s["nodeId"]: s for s in run["steps"]}

    loader = steps["park-access-data"]
    assert (loader["role"], loader["status"]) == ("run", "ok"), loader
    assert (loader["outputPath"], loader["outputType"]) == (LAYERS, "list"), loader
    (load,) = sandbox.bodies("/execJs")
    assert load["code"] == compile_data_spec(_node_content(dataflow, "park-access-data"))
    assert load["code"].splitlines()[:2] == [
        "import { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } from '@urban-toolkit/autk-db';",
        "import { createDataAdapter } from '@urban-toolkit/autk-grammar/data';",
    ]
    assert '"pbfFileUrl":"__CURIO_BACKEND_URL__/file/docs/examples/data/lower_mnt.osm.pbf"' in load["code"]
    assert f"const __expectedTables = {json.dumps(TIP_TABLES, separators=(',', ':'))};" in load["code"]
    assert "const __tableProblem = null;" in load["code"]

    # The Python step reads the load's list, which holds the heatmap.
    (shares,) = sandbox.bodies("/exec")
    assert (shares["file_path"], shares["dataType"]) == (LAYERS, "list"), shares
    assert steps["park-access-shares"]["status"] == "ok", steps["park-access-shares"]
    # The map draws in a browser: the run hands it the load's tables and runs nothing for it.
    assert steps["park-access-map"]["role"] == "forward", steps["park-access-map"]


def _niteroi_load(client, token, sandbox, example, prefix):
    """Example 36's or 37's run on the server: its steps by node, and the one
    load its data node *prefix*-data posted, which must be the code the
    browser's compiler gives, autk-db and then the grammar's ``./data`` entry,
    which loads the GeoTIFF, with the extract's and the GeoTIFF's URLs left for
    the sandbox to resolve. Its Python step reads the load's list, and its map
    and scatter draw in a browser: the run hands them their inputs and runs
    nothing for them."""
    from utk_curio.common.autk_data_compiler import compile_data_spec

    dataflow = json.loads(example.read_text(encoding="utf-8"))["dataflow"]
    run = _run(client, token, _create(client, token, dataflow))
    steps = {s["nodeId"]: s for s in run["steps"]}

    loader = steps[f"{prefix}-data"]
    assert (loader["role"], loader["status"]) == ("run", "ok"), loader
    assert (loader["outputPath"], loader["outputType"]) == (LAYERS, "list"), loader
    (load,) = sandbox.bodies("/execJs")
    assert load["code"] == compile_data_spec(_node_content(dataflow, f"{prefix}-data"))
    assert load["code"].splitlines()[:2] == [
        "import { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } from '@urban-toolkit/autk-db';",
        "import { createDataAdapter } from '@urban-toolkit/autk-grammar/data';",
    ]
    assert NITEROI_EXTRACT in load["code"]
    assert NITEROI_SUMMERS in load["code"]

    (cells,) = sandbox.bodies("/exec")
    assert (cells["file_path"], cells["dataType"]) == (LAYERS, "list"), cells
    assert steps[f"{prefix}-cells"]["status"] == "ok", steps[f"{prefix}-cells"]
    for drawn in (f"{prefix}-map", f"{prefix}-scatter"):
        assert steps[drawn]["role"] == "forward", steps[drawn]
    return load


def _compiled_sources(code: str) -> list[dict]:
    """The data sources a load's compiled code runs, as it inlines them
    (``const __sources = [...];``). The rest of the code names every kind of
    source its helpers can load, whatever the section holds."""
    prefix = "const __sources = "
    line = next(line for line in code.splitlines() if line.startswith(prefix))
    return json.loads(line[len(prefix):].rstrip(";"))


def test_example_36s_loader_reads_its_geotiff_on_the_server_as_the_browser_does(
    client, user_and_token, sandbox, recorded,
):
    """Example 36's data node loads Niterói's surface, parks and roads from the
    repository's extract and its summer land surface temperature from the
    repository's GeoTIFF: on the server, the layers and the GeoTIFF's table
    are expected, and it runs those two sources alone, no GeoJSON among them."""
    user, token = user_and_token
    load = _niteroi_load(client, token, sandbox, EXAMPLE_36, "green-heat")

    assert f"const __expectedTables = {json.dumps(GREEN_TABLES, separators=(',', ':'))};" in load["code"]
    assert [source["type"] for source in _compiled_sources(load["code"])] == ["osm", "geotiff"]


def test_example_37s_loader_reads_its_parks_and_sums_their_area_on_the_server_as_the_browser_does(
    client, user_and_token, sandbox, recorded,
):
    """Example 37's data node also loads Niterói's parks with their areas from
    the repository's GeoJSON, its URL left for the sandbox to resolve, and sums
    their area in a heatmap: on the server, the layers, the GeoTIFF's, the
    parks' and the heatmap's tables are expected, and the heatmap bins a table
    its data section loads before it."""
    user, token = user_and_token
    load = _niteroi_load(client, token, sandbox, EXAMPLE_37, "park-area")

    assert NITEROI_PARKS in load["code"]
    assert [source["type"] for source in _compiled_sources(load["code"])] == ["osm", "geotiff", "geojson", "heatmap"]
    assert f"const __expectedTables = {json.dumps(PARK_AREA_TABLES, separators=(',', ':'))};" in load["code"]
    assert "const __tableProblem = null;" in load["code"]


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


#: Readings a Python node returns, and an Autark data node whose heatmap bins them,
#: the table the node's input carries as input_0.
POINTS_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n"
    "return gpd.GeoDataFrame({'db': [61, 74]}, geometry=[Point(-9755000, 5142500), Point(-9754000, 5142600)], crs=3395)"
)
HEATMAP_OF_THE_INPUT = {"data": [{
    "type": "heatmap", "joinDataRef": "input_0", "outputTableName": "density",
    "near": {"distance": 400}, "grid": {"rows": 2, "columns": 3},
}]}


def _points_and_heatmap(document=None) -> dict:
    return {
        "name": "Binned readings",
        "nodes": [
            {"id": "points", "type": CODE, "content": POINTS_CODE},
            {"id": "heat", "type": AUTARK, "content": json.dumps(document or HEATMAP_OF_THE_INPUT)},
        ],
        "edges": [{"id": "points-heat", "source": "points", "target": "heat"}],
    }


def test_a_heatmap_of_an_upstream_python_nodes_table_runs_on_that_table(client, user_and_token, sandbox, recorded):
    """A data node whose heatmap bins its input's table, ``input_0``, runs on
    the server as the node's run in the browser does: the code the browser's
    compiler gives, which finds the table in the run's inputs, posted with the
    Python node's output as its input and no circles named, so the sandbox
    gives that output as ``input_0``."""
    from utk_curio.common.autk_data_compiler import compile_data_spec

    _user, token = user_and_token
    run = _run(client, token, _create(client, token, _points_and_heatmap()))
    steps = {s["nodeId"]: s for s in run["steps"]}
    assert [steps[n]["status"] for n in ("points", "heat")] == ["ok", "ok"], steps
    assert run["status"] == "succeeded"

    (made,) = sandbox.bodies("/exec")
    (load,) = sandbox.bodies("/execJs")
    assert load["code"] == compile_data_spec(json.dumps(HEATMAP_OF_THE_INPUT))
    assert 'const __inputTables = [{"name":"input_0","before":0,' in load["code"]
    # The Python node's output is the load's input, as the canvas sends it.
    points = steps["points"]
    assert points["outputPath"], points
    assert (load["file_path"], load["dataType"]) == (points["outputPath"], points["outputType"]), load
    assert "input_slots" not in load
    assert load["save_dataset"] is False
    assert made["file_path"] == ""
    (saved,) = [ref for ref in recorded if ref.node_id == "heat"]
    assert (saved.filename, saved.data_type) == (LAYERS, "list")


def test_a_data_node_that_reads_no_table_of_its_input_still_runs_on_no_input(client, user_and_token, sandbox, recorded):
    """guard: a data section that loads what it bins reads no input, wired or not."""
    _user, token = user_and_token
    own = {"data": [BACK_BAY_ROADS, {
        "type": "heatmap", "joinDataRef": "table_osm_roads", "outputTableName": "density",
        "near": {"distance": 400}, "grid": {"rows": 2, "columns": 3},
    }]}
    run = _run(client, token, _create(client, token, _points_and_heatmap(own)))
    assert run["status"] == "succeeded", run
    (load,) = sandbox.bodies("/execJs")
    assert (load["file_path"], load["dataType"]) == ("", ""), load
    assert "__inputs" not in load["code"]


def test_a_kept_heatmap_of_an_input_table_is_kept_by_its_input(app):
    """What a run of such a node keeps is keyed by its input too, so a
    dashboard viewer's run and a reopened dataflow find it only for the input
    it binned (``kept.step_call``); one that reads no table of its input keeps
    none in its key."""
    from utk_curio.backend.app.execution.run_engine import plan_run, sent_code
    from utk_curio.backend.app.runs import kept

    with app.app_context():
        plan = plan_run({"dataflow": _points_and_heatmap()})
        step = plan.steps["heat"]
        first = {"path": "art-points-1", "dataType": "geodataframe"}
        second = {"path": "art-points-2", "dataType": "geodataframe"}
        call = kept.step_call(plan, step, sent_code(plan, step), first)
        assert (call.engine, call.input, call.slots) == ("javascript", first, None)
        keys = {
            kept.call_key(kept.step_call(plan, step, sent_code(plan, step), ref),
                          packages="p", node_type=step.node_type, datasets={})
            for ref in (first, second)
        }
        assert len(keys) == 2

        own = {"data": [BACK_BAY_ROADS]}
        plan = plan_run({"dataflow": _points_and_heatmap(own)})
        step = plan.steps["heat"]
        assert kept.step_call(plan, step, sent_code(plan, step), first).input is None


#: The roads of Back Bay, which each document below loads beside the key it writes.
BACK_BAY_ROADS = {"type": "osm", "pbfFileUrl": "docs/examples/data/back_bay.osm.pbf", "outputTableName": "table_osm",
                  "autoLoadLayers": {"layers": ["surface", "roads"]}}


@pytest.mark.parametrize("document, said", [
    ({"data": [BACK_BAY_ROADS,
               {"type": "join", "tableRootName": "table_osm_roads", "joinDataRef": "table_osm_surface"}]},
     'This spec uses "tableRootName" at data[1], which autk-grammar 5 renamed to "dataRef".'),
    # Links describe no step of their own, so the document is still a data
    # node's, which a run on the server loads.
    ({"data": [BACK_BAY_ROADS], "links": [{"source": "roads-plot", "target": "roads-map"}]},
     'This spec uses "links", which Curio does not run yet.'),
], ids=["renamed-key", "not-run-yet"])
def test_a_load_that_writes_a_key_the_node_refuses_fails_with_its_words(
        client, user_and_token, sandbox, recorded, document, said):
    """The compiler refuses the document as the node does
    (``contracts/autkGrammar``), so nothing reaches the sandbox."""
    user, token = user_and_token
    content = json.dumps(document)
    run = _run(client, token, _create(client, token, {
        "name": "Back Bay roads",
        "nodes": [{"id": "roads", "type": AUTARK, "content": content}],
        "edges": [],
    }))
    (step,) = run["steps"]
    assert step["status"] == "error", step
    assert said in (step["stderrTail"] or ""), step
    assert sandbox.bodies("/execJs") == []
    assert recorded == []
    assert run["status"] == "failed"


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
