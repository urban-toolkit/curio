"""Dragging a scenario into another project (#662): what the server does.

A drop asks first what it copies (``GET .../copy?target=``), which changes
nothing and says why the drop cannot be made, if it cannot. The canvas picks
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

from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

BASELINE = {"id": "s1", "name": "Baseline", "color": "#2a9d8f", "nodes": ["a", "chart"]}


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _node(node_id, kind="computation-analysis", content="return arg", x=0, **extra):
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


def test_a_context_without_a_saved_output_is_refused_naming_it(client, user_and_token):
    user, token = user_and_token
    source, target = _source_and_target(client, token)

    plan = _plan(client, token, source, target).get_json()
    [problem] = plan["problems"]
    assert "Data Loading" in problem and "Shadows" in problem and "no saved output" in problem

    resp = _copy(client, token, source, target, [])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == problem


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
        {"id": "a", "type": "curio.example-ui/column-filter@1", "content": "return arg", "x": 300, "y": 0},
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
            "id": "a", "type": "acme.missing/thing@1", "content": "return arg", "x": 300, "y": 0,
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
