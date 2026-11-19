"""A run on the server computes example 25's nine Spatial Joins, no tab open (#576).

The Spatial Join is a code node: its code calls the built-in package's
``spatial_join`` in the sandbox, so a run on the server joins as Play does,
where it once waited for a tab ("Waits for the canvas"). Each test seeds the
dataflow and starts its run over HTTP alone, with no page: nothing ever opens
it. Every join's step is a run that ended ok, and the line its code printed
is the join's account of what it paired, the same line
``test_spatial_join_operations_e2e.py`` reads off each node in the browser.

The second test seeds the dataflow as Curio saved it before the join had
code: each join with no code and its operation and output at
``metadata.spatialJoin``. The server reads such a join with its code and those
settings in its two widgets, so the run joins with the saved operations.
"""
from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path

from .test_spatial_join_operations_e2e import CASES
from .utils import (
    REPO_ROOT,
    api_json,
    require_project_page,
    require_user_auth,
    stub_db_user,
)

EXAMPLE = Path(REPO_ROOT) / "docs" / "examples" / "25-spatial-join-operations.json"
JOIN = "curio.builtin/spatial-join"


def _example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _saved_before_its_code(spec: dict) -> dict:
    """*spec* as Curio saved it before the join had code: each join's
    operation and output at ``metadata.spatialJoin``, the defaults left out
    as the canvas left them, and no code and no widgets."""
    saved = copy.deepcopy(spec)
    for node in saved["dataflow"]["nodes"]:
        if node["type"].split("@", 1)[0] != JOIN:
            continue
        values = {widget["name"]: widget.get("value") for widget in node["metadata"].pop("widgets")}
        setting = {}
        if values["operation"] not in (None, "intersects"):
            setting["predicate"] = values["operation"]
        if values["output"] not in (None, "pairs"):
            setting["output"] = values["output"]
        if setting:
            node["metadata"]["spatialJoin"] = setting
        node["content"] = ""
    return saved


def _run_to_its_end(backend: str, spec: dict, username: str) -> dict:
    """The run on the server of *spec*, seeded and started over HTTP with no
    page, once it ended."""
    login = stub_db_user(
        backend, username=f"{username}_{uuid.uuid4().hex[:8]}", name="Server joins",
        project_name="Spatial Join operations", project_spec=spec,
    )
    token, project_id = login["token"], login["project"]["id"]
    # Read over HTTP, as an agent reads it: the read puts the Data Catalog
    # datasets the dataflow names in the account's store, as opening it does.
    read = api_json(f"{backend}/api/projects/{project_id}", token)
    assert all(
        node["content"] for node in read["spec"]["dataflow"]["nodes"] if node["type"] == JOIN
    ), "the server read a join with no code"
    started = api_json(f"{backend}/api/projects/{project_id}/runs", token, method="POST", payload={})
    deadline = time.monotonic() + 600
    while True:
        run = api_json(f"{backend}/api/runs/{started['id']}", token)
        if run["status"] not in ("queued", "running"):
            return run
        assert time.monotonic() < deadline, f"the run did not end within 600 s: {run['status']}"
        time.sleep(1)


def _assert_every_join_joined(run: dict) -> None:
    steps = {step["nodeId"]: step for step in run["steps"]}
    for case, (join, view, printed) in CASES.items():
        step = steps[join]
        assert (step["role"], step["status"]) == ("run", "ok"), (case, step)
        assert step["outputPath"], (case, step)
        assert printed in (step["stdoutTail"] or ""), (case, step["stdoutTail"])
        assert "No pairs:" not in (step["stdoutTail"] or ""), (case, step["stdoutTail"])
        # The view below it is handed the join's rows, as on the canvas.
        assert steps[view]["status"] in ("forwarded", "ok"), (case, steps[view])
    assert run["status"] == "succeeded", run["status"]


def test_a_server_run_of_example_25_computes_its_nine_joins_with_no_tab_open(current_server):
    require_project_page()
    require_user_auth()
    run = _run_to_its_end(current_server, _example(), "server_joins")
    _assert_every_join_joined(run)


def test_a_server_run_of_example_25_saved_before_its_joins_had_code_joins_with_the_saved_operations(current_server):
    require_project_page()
    require_user_auth()
    saved = _saved_before_its_code(_example())
    joins = [node for node in saved["dataflow"]["nodes"] if node["type"] == JOIN]
    assert len(joins) == 9 and all(node["content"] == "" for node in joins)
    assert {json.dumps(node["metadata"].get("spatialJoin"), sort_keys=True) for node in joins} == {
        "null", '{"output": "counts", "predicate": "within"}', '{"predicate": "contains"}',
        '{"predicate": "touches"}', '{"predicate": "overlaps"}', '{"predicate": "crosses"}',
        '{"predicate": "nearest"}', '{"predicate": "within"}',
    }
    run = _run_to_its_end(current_server, saved, "saved_joins")
    _assert_every_join_joined(run)
