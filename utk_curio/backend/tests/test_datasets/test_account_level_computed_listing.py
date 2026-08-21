"""Computed node outputs surface in the account-level Data Catalog.

A saved computed dataset is browsable in the account catalog (``includeHub``,
no/other dataflow) as an available — not installed — item, carrying its
producer/workflow lineage, so it can be installed into a project later.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
    save_project_with_output,
)


def _catalog(client, token, *, dataflow_id=None):
    url = "/api/datasets/catalog?includeHub=true"
    if dataflow_id:
        url += f"&dataflowId={dataflow_id}"
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["items"]


def test_saved_computed_dataset_is_browsable_account_level(client, user_and_token):
    _, token = user_and_token
    project_id = create_project(client, token, name="Producer flow")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "acct_out.csv").write_text("city,count\nChicago,10\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "acct_out.csv", node_id="prod-node")

    expected_id = computed_dataset_id("prod-node", project_id)

    # Account-level browse (no dataflow context): the dataset is present and NOT
    # installed anywhere — available to install later.
    items = _catalog(client, token)
    item = next((i for i in items if i["id"] == expected_id), None)
    assert item is not None, [i["id"] for i in items]
    assert item["origin"] == "computed"
    assert item["installed"] is False
    # Lineage links it to the producing workflow + node.
    assert item["producerNodeId"] == "prod-node"
    assert item["producerDataflowId"] == project_id


def test_computed_dataset_shows_available_in_another_dataflow(client, user_and_token):
    _, token = user_and_token
    producer = create_project(client, token, name="Producer")
    other = create_project(client, token, name="Other flow")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "cross_out.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    save_project_with_output(client, token, producer, "cross_out.csv", node_id="x-node")

    expected_id = computed_dataset_id("x-node", producer)

    # Browsing the catalog from a DIFFERENT dataflow: the dataset is visible
    # (account-level) but not installed in that other dataflow.
    items = _catalog(client, token, dataflow_id=other)
    item = next((i for i in items if i["id"] == expected_id), None)
    assert item is not None, [i["id"] for i in items]
    assert item["installed"] is False
    assert item["producerDataflowId"] == producer
