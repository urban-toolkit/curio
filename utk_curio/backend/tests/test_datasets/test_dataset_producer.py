"""Tests for authoritative-producer resolution on the Dataset Details endpoint.

When a computed dataset is opened from a dataflow that only *imported* it, that
dataflow's ref carries ``producerNodeId: null`` — the producing node lives in
another dataflow. ``GET /api/datasets/<id>`` must resolve the real producer
(node + type + producing dataflow) across the user's projects so the details
page shows the same generating node as the dataset's producing record.
"""
from __future__ import annotations

import json

from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment
from utk_curio.backend.app.datasets.services.catalog_listing import (
    _dataset_producer_in_spec,
)
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers


def _create_project(client, token, name, spec):
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": name, "spec": spec, "outputs": []}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _get_dataset(client, token, dataset_id, dataflow_id=None):
    url = f"/api/datasets/{dataset_id}"
    if dataflow_id:
        url += f"?dataflowId={dataflow_id}"
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def test_dataset_producer_in_spec_resolves_node_and_type():
    dataset_id = f"computed.{sanitize_node_id_segment('n1')}"
    spec = {
        "dataflow": {
            "nodes": [
                {"id": "n1", "type": "PYTHON_COMPUTATION"},
                {"id": "n2", "type": "VEGA"},
            ],
            "edges": [],
            "datasets": [],
        }
    }
    assert _dataset_producer_in_spec(spec, dataset_id) == {
        "nodeId": "n1",
        "nodeType": "PYTHON_COMPUTATION",
    }


def test_dataset_producer_in_spec_none_when_not_produced_here():
    spec = {"dataflow": {"nodes": [{"id": "z", "type": "VEGA"}], "edges": [], "datasets": []}}
    # Producing node absent from this dataflow.
    assert _dataset_producer_in_spec(spec, "computed.n1") is None
    # Non-computed dataset id is never producer-resolved.
    assert _dataset_producer_in_spec(spec, "it.urbanlab.example") is None


def test_get_dataset_resolves_producer_from_another_dataflow(client, user_and_token):
    """Opened from the importing dataflow (producerNodeId null), the details
    payload reflects the producing dataflow's node, type, and name."""
    _, token = user_and_token
    dataset_id = f"computed.{sanitize_node_id_segment('n1')}"

    # Flow A actually produces the dataset (node "n1").
    _create_project(client, token, "Flow A", {
        "dataflow": {
            "name": "Flow A",
            "nodes": [{"id": "n1", "type": "PYTHON_COMPUTATION", "x": 0, "y": 0}],
            "edges": [],
            "datasets": [],
        }
    })
    # Flow B only references it via an installed ref — no producerNodeId.
    flow_b = _create_project(client, token, "Flow B", {
        "dataflow": {
            "name": "Flow B",
            "nodes": [{"id": "m1", "type": "DATA_LOADING", "x": 0, "y": 0}],
            "edges": [],
            "datasets": [
                {"datasetId": dataset_id, "dirName": f"{dataset_id}@1", "origin": "computed"}
            ],
        }
    })

    item = _get_dataset(client, token, dataset_id, dataflow_id=flow_b)
    assert item["producerNodeId"] == "n1"
    assert item["producerNodeType"] == "PYTHON_COMPUTATION"
    assert item["producerDataflowName"] == "Flow A"
    assert item["origin"] == "computed"


def test_get_dataset_no_producer_fields_for_imported_dataset(client, user_and_token):
    """A genuinely imported (non-computed) dataset gets no producer backfill."""
    _, token = user_and_token
    dataset_id = "it.urbanlab.example"
    flow = _create_project(client, token, "Bound", {
        "dataflow": {
            "name": "Bound",
            "nodes": [
                {"id": "viz", "type": "VEGA", "x": 0, "y": 0,
                 "metadata": {"datasetRefs": [dataset_id]}},
            ],
            "edges": [],
            "datasets": [
                {"datasetId": dataset_id, "dirName": f"{dataset_id}@1", "origin": "imported"}
            ],
        }
    })

    item = _get_dataset(client, token, dataset_id, dataflow_id=flow)
    assert item.get("producerNodeId") is None
    assert item.get("producerNodeType") is None
    assert item.get("producerDataflowName") is None
