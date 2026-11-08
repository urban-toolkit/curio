"""Reads of the Data Catalog that show no usage count read no other dataflow.

A Data Catalog card says how many nodes consume its dataset, summed over every
dataflow of the account (``CatalogListing._consumer_counts``), so a listing
that counts reads each of those dataflows. An account signed up on a Curio
started with its examples holds every shipped dataflow, 61 of them today.

An agent's turn read the catalog twice, for its dataflow block's datasets
(``dataflow_block.read_datasets``) and for its grounding gate's rows
(``grounding._catalog_listing_items``); its catalog.search read it
(``tools._catalog_listing_rows``); and a node's run read it for a dataset the
dataset index does not hold (``resolve_execution_paths``). None of them shows
the count, and each counted it. Here each reads the catalog of one dataflow of
an account that holds two more, and must read neither of those. The browse
listing still counts (``test_dataset_usage.py``).
"""
from __future__ import annotations

import io
import json

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers


def _dataflow(client, token, name: str) -> str:
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": name, "spec": {"dataflow": {
            "name": name, "nodes": [{"id": "n1", "type": "PYTHON_COMPUTATION", "x": 0, "y": 0}],
            "edges": [], "datasets": [],
        }}, "outputs": []}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _account_with_dataflows(client, token) -> tuple[str, set[str]]:
    """The dataflow a read is for, and the account's two others; and one
    dataset of the account's own, so the catalog has an item to count."""
    resp = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(b"a,b\n1,2\n"), "parks.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    asked = _dataflow(client, token, "Asked")
    return asked, {_dataflow(client, token, "Other one"), _dataflow(client, token, "Other two")}


def _spec_reads(monkeypatch) -> list[str]:
    """The ids of the dataflows whose file is read from now on."""
    from utk_curio.backend.app.projects import storage as projects_storage

    read: list[str] = []
    original = projects_storage.read_spec

    def spy(user_key, project_id, *args, **kwargs):
        read.append(project_id)
        return original(user_key, project_id, *args, **kwargs)

    monkeypatch.setattr(projects_storage, "read_spec", spy)
    return read


def _others_read(read: list[str], others: set[str]) -> list[str]:
    return sorted(set(read) & others)


def test_an_agents_dataflow_block_reads_no_other_dataflow(app, client, user_and_token, monkeypatch):
    from utk_curio.backend.app.agents.application import dataflow_block

    user, token = user_and_token
    asked, others = _account_with_dataflows(client, token)
    read = _spec_reads(monkeypatch)

    dataflow_block.read_datasets(asked, user)

    assert _others_read(read, others) == [], (
        f"the block's datasets read the account's other dataflows {_others_read(read, others)}: "
        "it counted every dataset's consumers, which no block shows"
    )


def test_an_agents_grounding_gate_reads_no_other_dataflow(app, client, user_and_token, monkeypatch):
    from utk_curio.backend.app.agents.application.turns import grounding

    user, token = user_and_token
    asked, others = _account_with_dataflows(client, token)
    read = _spec_reads(monkeypatch)

    items = grounding._catalog_listing_items(asked, user=user)

    assert items, "the gate's catalog lists nothing, not even the account's dataset"
    assert _others_read(read, others) == [], (
        f"the gate's catalog read the account's other dataflows {_others_read(read, others)}"
    )


def test_an_agents_catalog_search_reads_no_other_dataflow(app, client, user_and_token, monkeypatch):
    from flask import g

    from utk_curio.backend.app.agents.application import tools

    user, token = user_and_token
    asked, others = _account_with_dataflows(client, token)
    read = _spec_reads(monkeypatch)

    with app.test_request_context():
        g.user = user
        rows = tools._catalog_listing_rows(str(user.id), asked, {})

    assert rows, "catalog.search found no row, not even the account's dataset"
    assert _others_read(read, others) == [], (
        f"catalog.search read the account's other dataflows {_others_read(read, others)}"
    )


def test_a_node_runs_dataset_paths_read_no_other_dataflow(app, client, user_and_token, monkeypatch):
    """An id the dataset index does not hold sends the run's resolution to the
    catalog listing, as a dataset of the hub or of the workspace does."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user, token = user_and_token
    asked, others = _account_with_dataflows(client, token)
    read = _spec_reads(monkeypatch)

    resolved = DatasetCatalogService(user).resolve_execution_paths(["imported.xnotinthestore"], dataflow_id=asked)

    assert resolved == {}
    assert _others_read(read, others) == [], (
        f"a run's dataset paths read the account's other dataflows {_others_read(read, others)}"
    )
