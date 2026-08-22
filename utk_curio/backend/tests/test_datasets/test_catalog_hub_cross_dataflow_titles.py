"""Catalog Hub titles for computed datasets browsed from another dataflow.

A computed dataset published to the hub keeps the title captured at publish time
(often the raw generated filename). When browsed from a dataflow other than the
producer's, only that stale hub row is listed. These tests pin that the listing
adopts the friendly node title from the user's store copy, and that the
generated-filename detector / merge keep title and fileName consistent.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from utk_curio.backend.app.datasets.domain.dedup import merge_catalog_items
from utk_curio.backend.app.datasets.infrastructure.catalog_utils import looks_like_generated_filename
from utk_curio.backend.app.datasets.install.installer import (
    computed_dataset_id,
    install_computed_file_for_node,
    sanitize_node_id_segment,
)
from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)


def _install_computed(client, token, project_id, *, node_id, filename, node_title=None):
    """Install a computed dataset from a shared output file and return its id."""
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / filename).write_text('{"a": 1}', encoding="utf-8")
    # The installed store id is namespaced by the installing dataflow; build the
    # sourceItem id to match so promote/install/publish key on one id.
    dataset_id = computed_dataset_id(node_id, project_id)
    body = {
        "datasetId": dataset_id,
        "sourceItem": {
            "id": dataset_id,
            "origin": "computed",
            "uri": f"curio://outputs/{filename}",
            "producerNodeId": node_id,
            "format": "json",
            "title": "1782757759504 31640Bba.Json",
            "fileName": "1782757759504 31640Bba.Json",
        },
    }
    if node_title is not None:
        body["nodeTitle"] = node_title
    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps(body),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return dataset_id


def test_looks_like_generated_filename():
    # Generated: epoch-ms prefix and/or a data-file extension (incl. .zlib).
    assert looks_like_generated_filename("1782757759504 31640Bba.Json")
    assert looks_like_generated_filename("1782757759504_31640bba")
    assert looks_like_generated_filename("output.json")
    assert looks_like_generated_filename("blocks.parquet")
    assert looks_like_generated_filename("data.json.zlib")
    # Human / node names are not generated.
    assert not looks_like_generated_filename("Autark")
    assert not looks_like_generated_filename("Knowledge Graph")
    assert not looks_like_generated_filename("Chicago Boundary")
    assert not looks_like_generated_filename(None)
    assert not looks_like_generated_filename("")


def test_merge_prefers_live_title_and_filename_together():
    """The live computed row's identity wins over a stale hub row — and title +
    fileName travel together so the pair stays consistent."""
    hub = {
        "id": "computed.node-x",
        "origin": "hub",
        "sourceLabel": "Computed",
        "title": "1782757759504 31640Bba.Json",
        "fileName": "1782757759504 31640Bba.Json",
        "dirName": "computed.node-x@1",
    }
    live = {
        "id": "computed.node-x",
        "origin": "computed",
        "producerNodeId": "node-x",
        "title": "Autark",
        "fileName": "1782840551478 B13Ae490",
        "dirName": "computed.node-x@1",
    }
    merged = merge_catalog_items(hub, live)
    assert merged["title"] == "Autark"
    assert merged["fileName"] == "1782840551478 B13Ae490"


def test_listing_backfills_friendly_title_from_user_store(app, user_and_token):
    """A computed item whose listed title looks generated adopts the friendly
    name from the user's store copy (same dir, keyed on the producing node)."""
    user, _token = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
        node_id = "whatif-data"
        dataflow_id = "flow-titles"
        # User store copy carries the friendly node title (as the Play-All save
        # path would have written it).
        install_computed_file_for_node(
            user_key,
            b'{"a": 1}',
            "1782840551478_b13ae490.json",
            "json",
            node_id=node_id,
            dataflow_id=dataflow_id,
            title="Autark",
        )

        dataset_id = computed_dataset_id(node_id, dataflow_id)
        dir_name = f"{dataset_id}@1"
        # A stale hub row for the same dataset, titled with the raw filename.
        stale_hub_item = {
            "id": dataset_id,
            "origin": "hub",
            "sourceLabel": "Computed",
            "title": "1782757759504 31640Bba.Json",
            "fileName": "1782757759504 31640Bba.Json",
            "dirName": dir_name,
        }

        service = DatasetCatalogService(user)
        service._listing._prefer_user_store_computed_title([stale_hub_item], user_key)
        assert stale_hub_item["title"] == "Autark"


def test_listing_leaves_friendly_titles_untouched(app, user_and_token):
    """An already-friendly title is never overwritten by the backfill."""
    user, _token = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
        node_id = "whatif-baseline"
        install_computed_file_for_node(
            user_key, b'{"a": 1}', "x.json", "json",
            node_id=node_id, dataflow_id="flow-titles", title="Baseline",
        )
        dataset_id = computed_dataset_id(node_id, "flow-titles")
        item = {
            "id": dataset_id,
            "origin": "hub",
            "sourceLabel": "Computed",
            "title": "Knowledge Graph",  # already friendly → must not change
            "dirName": f"{dataset_id}@1",
        }
        DatasetCatalogService(user)._listing._prefer_user_store_computed_title([item], user_key)
        assert item["title"] == "Knowledge Graph"


def test_publish_titles_computed_with_friendly_node_name(client, user_and_token, tmp_path, monkeypatch):
    """Publishing a computed dataset writes the friendly node title to the hub
    manifest — so other dataflows browsing the hub see it, not the filename."""
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(tmp_path / "catalog"))
    _, token = user_and_token
    project_id = create_project(client, token, name="Publish friendly title")
    dataset_id = _install_computed(
        client, token, project_id,
        node_id="whatif-data", filename="1782757759504_31640bba.json",
        node_title="Knowledge Graph",
    )

    resp = client.post(
        "/api/datasets/publish",
        data=json.dumps({"datasetId": dataset_id, "dataflowId": project_id}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert resp.get_json()["title"] == "Knowledge Graph"


def test_publish_never_titles_computed_with_a_generated_filename(client, user_and_token, tmp_path, monkeypatch):
    """Even if the publish request carries a generated-looking title, the hub
    manifest falls back to the store folder — never the raw filename."""
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(tmp_path / "catalog"))
    _, token = user_and_token
    project_id = create_project(client, token, name="Publish guards filename")
    dataset_id = _install_computed(
        client, token, project_id,
        node_id="whatif-data", filename="1782757759504_31640bba.json",
        node_title="Knowledge Graph",
    )

    resp = client.post(
        "/api/datasets/publish",
        data=json.dumps({
            "datasetId": dataset_id,
            "dataflowId": project_id,
            "title": "1782757759504 31640Bba.Json",  # generated-looking override
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    title = resp.get_json()["title"]
    assert title != "1782757759504 31640Bba.Json"
    # Node-scoped folder fallback — never the dataflow-namespaced store id
    # (whose dataflow segment is an opaque project UUID).
    assert title == "computed.whatif-data@1"
