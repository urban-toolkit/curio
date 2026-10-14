"""Dragging a scenario into another project (#662): what the server does.

A drop asks first what it copies (``GET .../copy?target=``), which changes
nothing and says why the drop cannot be made, if it cannot. A context with no
saved output is listed to run first (``toRun``): the canvas runs it on the
server, in its own project, and asks again; one only the browser can make is
refused, naming the node. The canvas picks
the copies' ids; then ``POST .../copy`` adds the packages the levers need and
copies each saved output the drop brings to its copy, the target's own:

* each context node's saved output, which a Data Loading node there reads;
* the saved outputs of the levers its outcomes show, so they show without a run.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_scenario_catalog/test_copy.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

BASELINE = {"id": "s1", "name": "Baseline", "color": "#2a9d8f", "nodes": ["a", "chart"]}


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _node(node_id, kind="computation-analysis", content="return input_0", x=0, **extra):
    return {"id": node_id, "type": f"curio.builtin/{kind}@1", "content": content, "x": x, "y": 0, **extra}


def _spec(name, scenarios, nodes=None, edges=None):
    """A loader feeding ``a``, which feeds a chart."""
    return {
        "dataflow": {
            "name": name,
            "nodes": nodes if nodes is not None else [
                _node("load", "data-loading", "return 1"),
                _node("a", x=300),
                _node("chart", "vis-vega", "{}", x=600),
            ],
            "edges": edges if edges is not None else [
                {"id": "e1", "source": "load", "target": "a", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e2", "source": "a", "target": "chart", "sourceHandle": "out", "targetHandle": "in"},
            ],
            "scenarios": scenarios,
        }
    }


def _create(client, token, name, spec):
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": name, "spec": spec, "outputs": []}),
        headers=_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _shared() -> Path:
    return Path(os.environ["CURIO_SHARED_DATA"])


def _save_outputs(client, token, project_id, files: dict[str, str], run: int = 1):
    """Save *files* (``{node: csv text}``) as the project's outputs, as a run
    and a save do. Each run writes new files, as the sandbox does."""
    outputs = []
    for node_id, text in files.items():
        filename = f"{project_id[:8]}_{node_id}_run{run}.csv"
        (_shared() / filename).write_text(text, encoding="utf-8")
        outputs.append({"node_id": node_id, "filename": filename})
    resp = client.put(f"/api/projects/{project_id}", data=json.dumps({"outputs": outputs}), headers=_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {o["node_id"]: o["filename"] for o in outputs}


def _source_and_target(client, token, spec=None):
    source = _create(client, token, "Shadows", spec or _spec("Shadows", [BASELINE]))
    target = _create(client, token, "Elsewhere", _spec("Elsewhere", [], nodes=[_node("mine", content="return 2")], edges=[]))
    return source, target


def _plan(client, token, source, target, scenario="s1"):
    return client.get(f"/api/scenarios/{source}/{scenario}/copy?target={target}", headers=_headers(token))


def _copy(client, token, source, target, outputs, scenario="s1"):
    return client.post(
        f"/api/scenarios/{source}/{scenario}/copy",
        data=json.dumps({"targetProjectId": target, "outputs": outputs}),
        headers=_headers(token),
    )


def _user_dir_key_of(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def _copied_data(user_key: str, node_id: str, project_id: str) -> str:
    dest = dataset_dir(user_key, f"{computed_dataset_id(node_id, project_id)}@1")
    return (dest / load_dataset_manifest(dest).data_file).read_text(encoding="utf-8")


def test_the_plan_names_the_levers_the_context_and_the_outcomes_saved_outputs(client, user_and_token):
    _, token = user_and_token
    source, target = _source_and_target(client, token)
    _save_outputs(client, token, source, {"load": "id,height\n1,10\n", "a": "id,sunlight\n1,0.5\n"})

    resp = _plan(client, token, source, target)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    plan = resp.get_json()
    assert plan["problems"] == []
    assert plan["toRun"] == []
    assert plan["scenario"] == {"id": "s1", "name": "Baseline", "color": "#2a9d8f", "description": ""}
    assert plan["project"] == {"id": source, "name": "Shadows"}
    assert plan["levers"] == ["a", "chart"]
    [load] = plan["context"]
    assert load["nodeId"] == "load" and "parameter" not in load
    assert load["source"] == {"nodeId": "load", "copiedFrom": [], "datasetId": computed_dataset_id("load", source)}
    # The chart saves nothing itself: what it shows is a's saved output.
    assert plan["outcomes"] == [{"nodeId": "chart", "label": "Vis Vega", "sources": ["a"]}]
    assert [n["id"] for n in plan["dataflow"]["nodes"]] == ["a", "chart"]
    assert [(e["source"], e["target"]) for e in plan["dataflow"]["edges"]] == [("load", "a"), ("a", "chart")]
    assert plan["packages"] == []


def test_a_drop_copies_each_saved_output_to_its_copy_and_restores_it(client, user_and_token):
    user, token = user_and_token
    source, target = _source_and_target(client, token)
    saved = _save_outputs(client, token, source, {"load": "id,height\n1,10\n", "a": "id,sunlight\n1,0.5\n"})

    resp = _copy(client, token, source, target, [
        {"source": "load", "node": "loader-1"},
        {"source": "a", "node": "a-copy"},
    ])

    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    ukey = _user_dir_key_of(user)
    assert _copied_data(ukey, "loader-1", target) == "id,height\n1,10\n"
    assert _copied_data(ukey, "a-copy", target) == "id,sunlight\n1,0.5\n"
    # Each copy is the output of its copy, in the target.
    manifest = load_dataset_manifest(dataset_dir(ukey, f"{computed_dataset_id('loader-1', target)}@1"))
    assert (manifest.producer_node_id, manifest.producer_dataflow_id) == ("loader-1", target)
    # The loader is told which dataset it reads; the copies' outputs are restored.
    assert body["datasets"]["loader-1"]["id"] == computed_dataset_id("loader-1", target)
    assert set(body["datasets"]) == {"loader-1"}
    assert sorted((o["node_id"], o["filename"]) for o in body["outputs"]) == [
        ("a-copy", saved["a"]), ("loader-1", saved["load"]),
    ]
    assert body["added"] == []


def test_the_copy_is_the_targets_own_and_a_reload_restores_it(client, user_and_token):
    user, token = user_and_token
    source, target = _source_and_target(client, token)
    saved = _save_outputs(client, token, source, {"load": "id,height\n1,10\n", "a": "id,sunlight\n1,0.5\n"})
    assert _copy(client, token, source, target, [{"source": "load", "node": "loader-1"}]).status_code == 200
    # The canvas saves the dropped loader with its restored output.
    resp = client.put(
        f"/api/projects/{target}",
        data=json.dumps({
            "spec": _spec("Elsewhere", [], nodes=[_node("mine"), _node("loader-1", "data-loading")], edges=[]),
            "outputs": [{"node_id": "loader-1", "filename": saved["load"]}],
        }),
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    # The source runs again: its own saved output changes, not the copy.
    _save_outputs(client, token, source, {"load": "id,height\n1,99\n"}, run=2)
    assert _copied_data(_user_dir_key_of(user), "load", source) == "id,height\n1,99\n"
    assert _copied_data(_user_dir_key_of(user), "loader-1", target) == "id,height\n1,10\n"

    # With the scratch cache emptied, opening the target restores the copy.
    (_shared() / saved["load"]).unlink()
    resp = client.get(f"/api/projects/{target}", headers=_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert {o["node_id"] for o in resp.get_json()["outputs"]} == {"loader-1"}
    assert (_shared() / saved["load"]).read_text(encoding="utf-8") == "id,height\n1,10\n"


def test_a_context_without_a_saved_output_is_listed_to_run_first(client, user_and_token):
    user, token = user_and_token
    source, target = _source_and_target(client, token)

    plan = _plan(client, token, source, target).get_json()

    assert plan["problems"] == []
    assert plan["toRun"] == [{"nodeId": "load", "label": "Data Loading"}]
    # Until it has run there, nothing is copied.
    resp = _copy(client, token, source, target, [{"source": "load", "node": "loader-1"}])
    assert resp.status_code == 409
    error = resp.get_json()["error"]
    assert "Data Loading" in error and "Shadows" in error and "no saved output" in error
    assert not dataset_dir(_user_dir_key_of(user), f"{computed_dataset_id('loader-1', target)}@1").exists()


#: An Autark node that computes over the layers it loads: only the browser
#: runs it (WebGPU), so a run on the server cannot make its output.
_COMPUTE_SPEC = json.dumps({
    "data": [{
        "type": "osm",
        "pbfFileUrl": "docs/examples/data/back_bay.osm.pbf",
        "outputTableName": "table_osm",
        "autoLoadLayers": {"layers": ["roads"]},
    }],
    "compute": [{"dataRef": "table_osm_roads"}],
})


def test_a_context_only_the_browser_can_make_is_still_refused_naming_it(client, user_and_token):
    _, token = user_and_token
    nodes = [
        _node("osm", "autk-grammar", _COMPUTE_SPEC, title="Back Bay layers"),
        _node("a", x=300),
    ]
    edges = [{"id": "e1", "source": "osm", "target": "a", "sourceHandle": "out", "targetHandle": "in"}]
    source, target = _source_and_target(client, token, _spec("Shadows", [{**BASELINE, "nodes": ["a"]}], nodes, edges))

    plan = _plan(client, token, source, target).get_json()

    assert plan["toRun"] == []
    [problem] = plan["problems"]
    assert "Back Bay layers" in problem and "Shadows" in problem and "browser" in problem
    resp = _copy(client, token, source, target, [])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == problem


def test_a_context_fed_by_a_node_only_the_browser_runs_is_refused_naming_that_node(client, user_and_token):
    _, token = user_and_token
    nodes = [
        _node("osm", "autk-grammar", _COMPUTE_SPEC, title="Back Bay layers"),
        _node("roads", content="return input_0", x=300, title="Roads"),
        _node("a", x=600),
    ]
    edges = [
        {"id": "e1", "source": "osm", "target": "roads", "sourceHandle": "out", "targetHandle": "in"},
        {"id": "e2", "source": "roads", "target": "a", "sourceHandle": "out", "targetHandle": "in"},
    ]
    source, target = _source_and_target(client, token, _spec("Shadows", [{**BASELINE, "nodes": ["a"]}], nodes, edges))

    plan = _plan(client, token, source, target).get_json()

    assert plan["toRun"] == []
    [problem] = plan["problems"]
    assert "Roads" in problem and "Back Bay layers" in problem and "browser" in problem


def test_where_runs_on_the_server_are_refused_a_missing_output_stays_a_problem(client, user_and_token, monkeypatch):
    from utk_curio.backend.app.users import capabilities

    monkeypatch.setattr(capabilities, "run_refusal", lambda user: "Runs on the server are not available here.")
    _, token = user_and_token
    source, target = _source_and_target(client, token)

    plan = _plan(client, token, source, target).get_json()

    assert plan["toRun"] == []
    [problem] = plan["problems"]
    assert "Data Loading" in problem and "Shadows" in problem and "no saved output" in problem


def test_with_no_project_page_a_missing_output_stays_a_problem(client, user_and_token, monkeypatch):
    """``--no-project`` runs every dataflow in the browser, as a hosted guest
    does, so a drop there has no run on the server to make the output."""
    from utk_curio.backend import config

    _, token = user_and_token
    source, target = _source_and_target(client, token)
    monkeypatch.setattr(config, "CURIO_NO_PROJECT", True)

    plan = _plan(client, token, source, target).get_json()

    assert plan["toRun"] == []
    [problem] = plan["problems"]
    assert "Data Loading" in problem and "Shadows" in problem and "no saved output" in problem


class _Sandbox:
    """Answers a run's ``/exec`` as the sandbox does, with an output file in
    the shared data folder: ``id,height`` rows named after the node."""

    def __init__(self):
        self.ran: list[str] = []

    def __call__(self, method, path, **kwargs):
        body = json.loads(kwargs["data"])
        node_id = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        self.ran.append(node_id)
        filename = f"run_{node_id}.csv"
        (_shared() / filename).write_text("id,height\n1,10\n", encoding="utf-8")

        class Reply:
            status_code = 200
            text = ""

            def json(_self):
                return {"stdout": [], "stderr": "", "output": {"path": filename, "dataType": "dataframe"}}

        return Reply()


class TestAContextRunsOnTheServerFirst:
    """A run on the server writes from threads of its own, so this database is
    a file, as in the run tests: each thread gets its own connection."""

    @pytest.fixture()
    def app(self, tmp_path):
        from utk_curio.backend.app import create_app
        from utk_curio.backend.extensions import db as _db
        from utk_curio.backend.tests._unit_fixtures import TestConfig
        from utk_curio.sandbox.util.db import release_connection

        class FileConfig(TestConfig):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'copy.db'}"

        release_connection()
        shared = tmp_path / ".curio" / "data"
        shared.mkdir(parents=True)
        previous = {key: os.environ.get(key) for key in ("CURIO_LAUNCH_CWD", "CURIO_SHARED_DATA")}
        os.environ["CURIO_LAUNCH_CWD"] = str(tmp_path)
        os.environ["CURIO_SHARED_DATA"] = str(shared)
        application = create_app(FileConfig)
        with application.app_context():
            _db.create_all()
            yield application
            _db.session.remove()
            _db.drop_all()
            _db.engine.dispose()
        release_connection()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_after_a_run_of_those_nodes_the_plan_is_clean_and_the_copy_brings_the_output(
        self, client, user_and_token, monkeypatch,
    ):
        from utk_curio.backend.app.runs import jobs
        from utk_curio.backend.extensions import db

        jobs.REGISTRY.reset()
        sandbox = _Sandbox()
        monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", sandbox)
        user, token = user_and_token
        nodes = [
            _node("load", "data-loading", "# node load\nreturn 1"),
            _node("a", content="# node a\nreturn input_0", x=300),
            _node("chart", "vis-vega", "{}", x=600),
        ]
        source, target = _source_and_target(client, token, _spec("Shadows", [BASELINE], nodes))
        plan = _plan(client, token, source, target).get_json()
        targets = [entry["nodeId"] for entry in plan["toRun"]]
        assert targets == ["load"], plan

        started = client.post(f"/api/projects/{source}/runs", data=json.dumps({"targets": targets}), headers=_headers(token))
        assert started.status_code == 202, started.get_data(as_text=True)
        job = jobs.REGISTRY.get_job(started.get_json()["id"])
        job.thread.join(timeout=30)
        assert not job.thread.is_alive()
        db.session.rollback()  # see what the run's threads committed
        run = client.get(f"/api/runs/{started.get_json()['id']}", headers=_headers(token)).get_json()
        assert run["status"] == "succeeded", run
        assert sandbox.ran == ["load"], "a run of the context ran more than the context"

        plan = _plan(client, token, source, target).get_json()
        assert plan["problems"] == [] and plan["toRun"] == [], plan
        assert plan["context"][0]["source"]["datasetId"] == computed_dataset_id("load", source)
        resp = _copy(client, token, source, target, [{"source": "load", "node": "loader-1"}])
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert _copied_data(_user_dir_key_of(user), "loader-1", target) == "id,height\n1,10\n"
        assert resp.get_json()["datasets"]["loader-1"]["id"] == computed_dataset_id("loader-1", target)


def test_only_the_scenarios_saved_outputs_are_copied_to_fresh_ids(client, user_and_token):
    _, token = user_and_token
    source, target = _source_and_target(client, token)
    _save_outputs(client, token, source, {"load": "id\n1\n", "a": "id\n2\n"})

    for outputs in (
        [{"source": "chart", "node": "x"}],          # saves nothing of its own
        [{"source": "nope", "node": "x"}],
        [{"source": "load", "node": "../escape"}],
        [{"source": "load", "node": "x"}, {"source": "a", "node": "x"}],
        [{"source": "load", "node": "mine"}],        # a node the target holds
        "not a list",
    ):
        resp = _copy(client, token, source, target, outputs)
        assert resp.status_code == 400, (outputs, resp.get_data(as_text=True))


def test_a_package_the_target_lacks_is_added(client, user_and_token):
    _, token = user_and_token
    nodes = [
        _node("load", "data-loading", "return 1"),
        {"id": "a", "type": "curio.example-ui/column-filter@1", "content": "return input_0", "x": 300, "y": 0},
    ]
    edges = [{"id": "e1", "source": "load", "target": "a", "sourceHandle": "out", "targetHandle": "in"}]
    source, target = _source_and_target(client, token, _spec("Shadows", [{**BASELINE, "nodes": ["a"]}], nodes, edges))
    _save_outputs(client, token, source, {"load": "id\n1\n"})

    assert _plan(client, token, source, target).get_json()["packages"] == ["curio.example-ui@1"]
    resp = _copy(client, token, source, target, [{"source": "load", "node": "loader-1"}])

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["added"] == ["curio.example-ui@1"]
    assert "curio.example-ui@1" in resp.get_json()["packages"]
    lockfile = client.get(f"/api/packages/projects/{target}", headers=_headers(token)).get_json()
    assert "curio.example-ui@1" in json.dumps(lockfile)


def test_what_the_account_cannot_provide_is_refused_naming_it(client, user_and_token):
    user, token = user_and_token
    nodes = [
        _node("load", "data-loading", "return 1"),
        {
            "id": "a", "type": "acme.missing/thing@1", "content": "return input_0", "x": 300, "y": 0,
            "metadata": {"datasetRefs": ["data.nowhere"], "modelRefs": [{"id": "model.nowhere"}]},
        },
    ]
    edges = [{"id": "e1", "source": "load", "target": "a", "sourceHandle": "out", "targetHandle": "in"}]
    source, target = _source_and_target(client, token, _spec("Shadows", [{**BASELINE, "nodes": ["a"]}], nodes, edges))
    _save_outputs(client, token, source, {"load": "id\n1\n"})

    problems = " ".join(_plan(client, token, source, target).get_json()["problems"])
    assert "acme.missing@1" in problems
    assert "data.nowhere" in problems
    assert "model.nowhere" in problems

    resp = _copy(client, token, source, target, [{"source": "load", "node": "loader-1"}])
    assert resp.status_code == 409
    # Refused before anything was copied.
    assert not dataset_dir(_user_dir_key_of(user), f"{computed_dataset_id('loader-1', target)}@1").exists()


DDRNET_DIR = "model.curio.ddrnet23-slim@1"


def _streets_spec():
    """A loader feeding ``a``, a lever that runs DDRNet23-Slim, with the binding
    a model dropped on a node leaves."""
    nodes = [
        _node("load", "data-loading", "return 1"),
        _node(
            "a", content='model = curio_load_model("model.curio.ddrnet23-slim")\nreturn input_0', x=300,
            metadata={"modelRefs": [{"id": "model.curio.ddrnet23-slim", "name": "DDRNet23-Slim (street scenes)"}]},
        ),
    ]
    edges = [{"id": "e1", "source": "load", "target": "a", "sourceHandle": "out", "targetHandle": "in"}]
    return _spec("Streets", [{**BASELINE, "nodes": ["a"]}], nodes, edges)


def test_a_model_the_target_lacks_is_added_as_its_package(client, user_and_token, monkeypatch):
    """A model is a model package: a lever that runs DDRNet23-Slim brings its
    package into the target dataflow, as a lever's node brings its package,
    and the account's store holds it afterwards, so the copy can run it."""
    from utk_curio.backend.app.packages.application import provisioning
    from utk_curio.backend.app.packages.repositories.store import package_dir

    # Its library is the packages' business, tested there; no pip here.
    monkeypatch.setattr(provisioning, "provision_python_deps", lambda *a, **k: provisioning.InstallOutcome())
    user, token = user_and_token
    source, target = _source_and_target(client, token, _streets_spec())
    _save_outputs(client, token, source, {"load": "id\n1\n"})

    plan = _plan(client, token, source, target).get_json()
    assert plan["problems"] == [] and plan["packages"] == [DDRNET_DIR]
    resp = _copy(client, token, source, target, [{"source": "load", "node": "loader-1"}])

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["added"] == [DDRNET_DIR]
    lockfile = client.get(f"/api/packages/projects/{target}", headers=_headers(token)).get_json()
    assert DDRNET_DIR in json.dumps(lockfile)
    assert (package_dir(_user_dir_key_of(user), DDRNET_DIR) / "manifest.json").is_file()


def test_a_model_the_account_may_not_add_is_refused_naming_it(client, user_and_token, monkeypatch):
    """Guests never install: a drop whose lever runs a model the account's
    store does not hold, and which the account may not add, is refused before
    anything is copied, naming the model's package and why."""
    from utk_curio.backend.app.packages.repositories.store import package_dir
    from utk_curio.backend.app.users import capabilities

    monkeypatch.setattr(capabilities, "package_install_refusal",
                        lambda user: "this Curio does not install packages for guests")
    user, token = user_and_token
    source, target = _source_and_target(client, token, _streets_spec())
    _save_outputs(client, token, source, {"load": "id\n1\n"})

    problems = " ".join(_plan(client, token, source, target).get_json()["problems"])
    assert DDRNET_DIR in problems and "does not install packages for guests" in problems
    resp = _copy(client, token, source, target, [{"source": "load", "node": "loader-1"}])
    assert resp.status_code == 409
    assert not package_dir(_user_dir_key_of(user), DDRNET_DIR).exists()
    assert not dataset_dir(_user_dir_key_of(user), f"{computed_dataset_id('loader-1', target)}@1").exists()


def test_a_shared_parameter_comes_with_the_plan_and_its_value(client, user_and_token):
    _, token = user_and_token
    spec = _spec("Shadows", [BASELINE])
    spec["dataflow"]["nodes"][1]["content"] = "return [!! @season !!]"
    spec["dataflow"]["nodes"].append({
        "id": "season", "type": "curio.builtin/parameter@1", "content": "", "x": 0, "y": 300,
        "metadata": {"widgets": [{"name": "season", "type": "text", "default": "winter", "value": "summer"}]},
    })
    source, target = _source_and_target(client, token, spec)
    _save_outputs(client, token, source, {"load": "id\n1\n"})

    plan = _plan(client, token, source, target).get_json()

    assert plan["problems"] == []
    assert [(c["nodeId"], c.get("parameter", False)) for c in plan["context"]] == [("load", False), ("season", True)]
    season = next(n for n in plan["dataflow"]["nodes"] if n["id"] == "season")
    assert season["metadata"]["widgets"][0]["value"] == "summer"


def test_a_context_that_passes_on_several_outputs_is_refused(client, user_and_token):
    _, token = user_and_token
    nodes = [
        _node("load", "data-loading", "return 1"),
        _node("load2", "data-loading", "return 2"),
        _node("pool", "data-pool", ""),
        _node("a", x=600),
    ]
    edges = [
        {"id": "e1", "source": "load", "target": "pool", "targetHandle": "in"},
        {"id": "e2", "source": "load2", "target": "pool", "targetHandle": "in_1"},
        {"id": "e3", "source": "pool", "target": "a", "targetHandle": "in"},
    ]
    source, target = _source_and_target(client, token, _spec("Shadows", [{**BASELINE, "nodes": ["a"]}], nodes, edges))
    _save_outputs(client, token, source, {"load": "id\n1\n", "load2": "id\n2\n"})

    [problem] = _plan(client, token, source, target).get_json()["problems"]
    assert "Data Pool" in problem and "2 outputs" in problem


def test_another_accounts_project_is_not_found_either_way(client, user_and_token, other_user_and_token):
    _, token = user_and_token
    _, other_token = other_user_and_token
    source, target = _source_and_target(client, token)
    theirs = _create(client, other_token, "Theirs", _spec("Theirs", [BASELINE]))

    assert _plan(client, token, source, theirs).status_code == 404
    assert _plan(client, token, theirs, target).status_code == 404
    assert _copy(client, other_token, source, theirs, []).status_code == 404


def test_a_drop_needs_a_signed_in_account_and_a_target(client, user_and_token):
    _, token = user_and_token
    assert client.get("/api/scenarios/p/s/copy?target=t").status_code == 401
    assert client.post("/api/scenarios/p/s/copy", data="{}").status_code == 401
    assert client.get("/api/scenarios/p/s/copy", headers=_headers(token)).status_code == 400
    assert client.post("/api/scenarios/p/s/copy", data="{}", headers=_headers(token)).status_code == 400
