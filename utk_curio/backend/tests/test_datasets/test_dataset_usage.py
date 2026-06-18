"""Tests for ``GET /api/datasets/<id>/usage`` — cross-dataflow usage powering
the standalone catalog detail page (issue #141, TODO item 1)."""
from __future__ import annotations

import json

from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers


def _create_project(client, token, name, spec):
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": name, "spec": spec, "outputs": []}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _usage(client, token, dataset_id):
    resp = client.get(
        f"/api/datasets/{dataset_id}/usage", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["dataflows"]


def test_usage_lists_dataflows_for_computed_dataset_with_downstream(client, user_and_token):
    _, token = user_and_token

    # Flow A: producer node "n1" → consumer node "n2" via a data edge.
    flow_a = _create_project(client, token, "Flow A", {
        "dataflow": {
            "name": "Flow A",
            "nodes": [
                {"id": "n1", "type": "PYTHON_COMPUTATION", "x": 0, "y": 0},
                {"id": "n2", "type": "VEGA", "x": 0, "y": 0},
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
            "datasets": [],
        }
    })
    # Flow B: references the dataset through an installed dataflow ref only.
    dataset_id = f"computed.{sanitize_node_id_segment('n1')}"
    flow_b = _create_project(client, token, "Flow B", {
        "dataflow": {
            "name": "Flow B",
            "nodes": [{"id": "m1", "type": "DATA_LOADING", "x": 0, "y": 0}],
            "edges": [],
            "datasets": [{"datasetId": dataset_id, "dirName": f"{dataset_id}@1", "origin": "computed"}],
        }
    })
    # Flow C: unrelated — must NOT appear.
    _create_project(client, token, "Flow C", {
        "dataflow": {"name": "Flow C", "nodes": [{"id": "z", "type": "VEGA", "x": 0, "y": 0}], "edges": [], "datasets": []}
    })

    flows = _usage(client, token, dataset_id)
    by_id = {f["dataflowId"]: f for f in flows}

    assert flow_a in by_id, "producing dataflow with a downstream consumer must be listed"
    assert by_id[flow_a]["nodeCount"] == 1  # n2 consumes n1's output via the edge
    # Consumer node refs are returned so the catalog detail can show them.
    assert by_id[flow_a]["nodes"] == [{"nodeId": "n2", "nodeType": "VEGA"}]

    assert flow_b in by_id, "dataflow referencing the dataset via an installed ref must be listed"

    assert all(f["dataflowName"] != "Flow C" for f in flows), "unrelated dataflow must be excluded"
    # Sorted by name.
    names = [f["dataflowName"] for f in flows]
    assert names == sorted(names, key=str.casefold)


def test_usage_lists_dataflow_for_node_bound_dataset(client, user_and_token):
    """A dataset dragged onto a node (metadata.datasetRefs) counts as usage."""
    _, token = user_and_token
    dataset_id = "it.urbanlab.example"
    flow = _create_project(client, token, "Bound", {
        "dataflow": {
            "name": "Bound",
            "nodes": [
                {"id": "loader", "type": "DATA_LOADING", "x": 0, "y": 0,
                 "metadata": {"datasetRefs": [dataset_id]}},
            ],
            "edges": [],
            "datasets": [],
        }
    })

    flows = _usage(client, token, dataset_id)
    by_id = {f["dataflowId"]: f for f in flows}
    assert flow in by_id
    assert by_id[flow]["nodeCount"] == 1


def test_usage_empty_for_unused_dataset(client, user_and_token):
    _, token = user_and_token
    _create_project(client, token, "Empty", {
        "dataflow": {"name": "Empty", "nodes": [], "edges": [], "datasets": []}
    })
    assert _usage(client, token, "computed.nothing") == []
