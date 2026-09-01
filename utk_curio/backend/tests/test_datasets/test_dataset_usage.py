"""Tests for ``GET /api/datasets/<id>/usage`` — cross-dataflow usage powering
the standalone catalog detail page (issue #141, TODO item 1)."""
from __future__ import annotations

import json

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    save_project_with_output,
)


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
    # The dataset is produced by Flow A, so its id is namespaced by flow_a.
    dataset_id = computed_dataset_id("n1", flow_a)
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
    """A dataset dragged onto a (non-loading) node counts that node as a consumer."""
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
            "datasets": [],
        }
    })

    flows = _usage(client, token, dataset_id)
    by_id = {f["dataflowId"]: f for f in flows}
    assert flow in by_id
    assert by_id[flow]["nodeCount"] == 1


def test_usage_excludes_unconnected_data_loading_box(client, user_and_token):
    """Dropping a dataset's Data Loading box (a carrier, not a consumer) lists the
    dataflow but reports 0 consumers until the loader is wired downstream."""
    _, token = user_and_token
    dataset_id = "it.urbanlab.example"

    # Loader alone → dataflow uses the dataset, but no downstream consumer.
    flow_alone = _create_project(client, token, "Loader Only", {
        "dataflow": {
            "name": "Loader Only",
            "nodes": [
                {"id": "loader", "type": "curio.builtin/data-loading", "x": 0, "y": 0,
                 "metadata": {"datasetRefs": [dataset_id]}},
            ],
            "edges": [],
            "datasets": [],
        }
    })
    # Loader wired to a downstream node → that node is the consumer.
    flow_wired = _create_project(client, token, "Loader Wired", {
        "dataflow": {
            "name": "Loader Wired",
            "nodes": [
                {"id": "loader", "type": "curio.builtin/data-loading", "x": 0, "y": 0,
                 "metadata": {"datasetRefs": [dataset_id]}},
                {"id": "viz", "type": "VEGA", "x": 0, "y": 0},
            ],
            "edges": [{"id": "e1", "source": "loader", "target": "viz"}],
            "datasets": [],
        }
    })

    by_id = {f["dataflowId"]: f for f in _usage(client, token, dataset_id)}
    assert by_id[flow_alone]["nodeCount"] == 0  # unconnected loader → no consumers
    assert by_id[flow_wired]["nodeCount"] == 1
    assert by_id[flow_wired]["nodes"] == [{"nodeId": "viz", "nodeType": "VEGA"}]


def test_usage_empty_for_unused_dataset(client, user_and_token):
    _, token = user_and_token
    _create_project(client, token, "Empty", {
        "dataflow": {"name": "Empty", "nodes": [], "edges": [], "datasets": []}
    })
    assert _usage(client, token, "computed.nothing") == []


# ---------------------------------------------------------------------------
# Browse-card ``consumerNodeCount`` — the "N nodes consume" figure. Regression
# for the hardcoded ``0``: it must be the real graph count, and must agree with
# the ``/usage`` total the detail panel shows.
# ---------------------------------------------------------------------------


def _computed_item(client, token, project_id, dataset_id):
    # A saved computed output is an account-level asset surfaced in the
    # producing dataflow's scoped catalog (not auto-installed into the project).
    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    return next(i for i in catalog["items"] if i["id"] == dataset_id)


def _consumed_project_spec(consumer_ids):
    """Spec with producer ``n1`` wired to each consumer in *consumer_ids*."""
    nodes = [{"id": "n1", "type": "PYTHON_COMPUTATION", "x": 0, "y": 0}]
    edges = []
    for i, cid in enumerate(consumer_ids):
        nodes.append({"id": cid, "type": "VEGA", "x": 0, "y": 0})
        edges.append({"id": f"e{i}", "source": "n1", "target": cid})
    return {"dataflow": {"name": "Consumed", "nodes": nodes, "edges": edges, "datasets": []}}


def _install_producer_output(client, token, project_id):
    """Give ``n1`` a real computed output so it lists as a catalog dataset."""
    import os
    from pathlib import Path

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "n1_out.csv").write_text("city,count\nChicago,10\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "n1_out.csv", node_id="n1")
    return computed_dataset_id("n1", project_id)


def test_catalog_consumer_count_reflects_downstream_nodes(client, user_and_token):
    """A computed dataset consumed by 2 downstream nodes reports
    ``consumerNodeCount == 2`` — not the always-empty persisted ``consumerNodeIds``."""
    _, token = user_and_token
    project_id = _create_project(client, token, "Consumed", _consumed_project_spec(["n2", "n3"]))
    dataset_id = _install_producer_output(client, token, project_id)

    item = _computed_item(client, token, project_id, dataset_id)
    assert item["consumerNodeCount"] == 2

    # Invariant: the browse count equals the detail panel's /usage total.
    usage_total = sum(f["nodeCount"] for f in _usage(client, token, dataset_id))
    assert item["consumerNodeCount"] == usage_total


def test_catalog_consumer_count_singular(client, user_and_token):
    """Exactly one consumer → count of 1 (the UI renders "1 node consumes")."""
    _, token = user_and_token
    project_id = _create_project(client, token, "Consumed", _consumed_project_spec(["n2"]))
    dataset_id = _install_producer_output(client, token, project_id)

    item = _computed_item(client, token, project_id, dataset_id)
    assert item["consumerNodeCount"] == 1


def test_catalog_consumer_count_zero_when_unconsumed(client, user_and_token):
    """A produced-but-unwired dataset reports 0 consumers (real value, not stale)."""
    _, token = user_and_token
    project_id = _create_project(client, token, "Unconsumed", _consumed_project_spec([]))
    dataset_id = _install_producer_output(client, token, project_id)

    item = _computed_item(client, token, project_id, dataset_id)
    assert item["consumerNodeCount"] == 0
