"""A map draws a table of a named workspace (autk-grammar 5.0.0's ``workspace``),
and the table reaches the nodes after it in that workspace.

One Autark data node loads ``lines``, three GeoJSON lines in the Loop, into the
workspace ``east``, in the sandbox, as a node's data section loads. A map in
``east`` draws them and hands them on as they came to a second map in
``east``, which draws them too. A Python node fed by the data node reads each
table's workspace. A map with no workspace finds no ``lines`` in the default
workspace: it draws nothing, and its error names the table there is,
``east/lines``. Each map is checked through what its canvas drew, with no
frame of its own.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_workspaces_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .utils import (
    _OUTPUT_ARTIFACT_JS,
    assert_autark_map_drawn,
    frame_nodes,
    load_artifact_as_dict,
    node_execution_timeout_ms,
    node_locator,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_done,
    wait_for_node_settled,
    wait_for_run_all_to_end,
    wait_for_run_guard_released,
    watch_run_all,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

AUTK_TYPE = "curio.builtin/autk-grammar"
PYTHON_TYPE = "curio.builtin/python-computation"

DATA = "ws-data"
EAST_MAP = "ws-east-map"
NEXT_MAP = "ws-next-map"
PLAIN_MAP = "ws-plain-map"
READER = "ws-read"

#: Three lines in the Loop, about 330 m apart.
LINES = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"line": i},
     "geometry": {"type": "LineString", "coordinates": [[-87.632 + 0.004 * i, 41.878], [-87.630 + 0.004 * i, 41.884]]}}
    for i in range(3)
]}

DOCUMENTS = {
    DATA: {"data": [{"type": "geojson", "outputTableName": "lines", "workspace": "east", "geojsonObject": LINES}]},
    EAST_MAP: {"map": {"workspace": "east", "layerRefs": [{"dataRef": "lines", "color": "#d62728", "width": 40}]}},
    NEXT_MAP: {"map": {"workspace": "east", "layerRefs": [{"dataRef": "lines", "color": "#1f77b4", "width": 40}]}},
    PLAIN_MAP: {"map": {"layerRefs": [{"dataRef": "lines"}]}},
}

#: Each table the data node hands on, as `<name>@<workspace>`, whether it
#: arrives as the layer records or as frames.
READ = '''layers = input_0 if isinstance(input_0, (list, tuple)) else [input_0]
def where(layer):
    held = layer if isinstance(layer, dict) else (layer.__dict__.get("metadata") or {})
    return f"{held.get('name')}@{held.get('workspace', 'default')}"
return ",".join(where(layer) for layer in layers)
'''


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _edge(source: str, target: str) -> dict:
    return {
        "id": f"reactflow__edge-{source}out-{target}in",
        "source": source, "target": target, "sourceHandle": "out", "targetHandle": "in",
    }


def _dataflow() -> dict:
    nodes = [
        _node(DATA, AUTK_TYPE, 80, 300, json.dumps(DOCUMENTS[DATA], indent=2)),
        _node(EAST_MAP, AUTK_TYPE, 700, 40, json.dumps(DOCUMENTS[EAST_MAP], indent=2)),
        _node(NEXT_MAP, AUTK_TYPE, 1320, 40, json.dumps(DOCUMENTS[NEXT_MAP], indent=2)),
        _node(PLAIN_MAP, AUTK_TYPE, 700, 600, json.dumps(DOCUMENTS[PLAIN_MAP], indent=2)),
        _node(READER, PYTHON_TYPE, 1320, 600, READ),
    ]
    edges = [_edge(DATA, EAST_MAP), _edge(EAST_MAP, NEXT_MAP), _edge(DATA, PLAIN_MAP), _edge(DATA, READER)]
    return {"dataflow": {"name": "Autark workspaces", "task": "", "nodes": nodes, "edges": edges}}


def _play(page, node_id: str, node_type: str) -> None:
    """Play the node, which runs the nodes before it too, and wait for that run
    to end (the run guard), then for the node to read Done."""
    watch_run_all(page)
    play_node(page, node_id)
    wait_for_run_all_to_end(page, timeout_ms=node_execution_timeout_ms(AUTK_TYPE))
    wait_for_node_done(page, node_id, node_type=node_type)


def test_a_map_draws_a_table_of_its_workspace_and_hands_it_on_in_it(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    spec = _dataflow()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Workspaces",
        username="autk_ws_user",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)

    # The second map draws what the first one, in east, hands on: east's lines.
    _play(page, NEXT_MAP, AUTK_TYPE)
    wait_for_node_done(page, EAST_MAP, node_type=AUTK_TYPE)
    frame_nodes(page, [EAST_MAP, NEXT_MAP])
    assert_autark_map_drawn(page, EAST_MAP, timeout=60000)
    assert_autark_map_drawn(page, NEXT_MAP, timeout=60000)

    # A Python node reads each table with its workspace.
    _play(page, READER, PYTHON_TYPE)
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, READER)
    assert artifact, f"{READER} shows no saved output"
    said = json.dumps(load_artifact_as_dict(artifact))
    assert "lines@east" in said, said

    # A map with no workspace finds no lines in the default workspace, and says
    # which table there is.
    play_node(page, PLAIN_MAP)
    status = wait_for_node_settled(page, PLAIN_MAP, node_type=AUTK_TYPE)
    detail = read_node_error_text(node_locator(page, PLAIN_MAP)) or ""
    assert status == "error" and "available: east/lines" in detail, (status, detail)
    wait_for_run_guard_released(page, timeout_ms=node_execution_timeout_ms(AUTK_TYPE))
