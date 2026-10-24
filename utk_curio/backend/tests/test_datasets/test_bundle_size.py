"""A bundle dataset's size is the bytes of the parts its ``bundle.json`` lists (#1060).

A bundle's data file is ``data/bundle.json``, an index of a few hundred bytes
that names the bundle's parts. The Data Catalog shows a bundle's size on its
card and in its details, and that size is its parts', wherever it is read:

- the hub listing and the details, built from the catalog's manifest;
- the answer of "Add to project", which reads the size of the copy it made;
- the project's own listing after that, which reads it again.

The shipped Chicago Loop Layers is a bundle of four layers. Each test sums the
parts its ``bundle.json`` lists from the files themselves, so a rebuild of the
dataset can't break it.
"""
from __future__ import annotations

import json
from pathlib import Path

from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    bundle_parts_size,
    create_project,
)

CHICAGO = "data.curio.chicago-loop-layers"


def _get(client, token: str, url: str, **params) -> dict:
    resp = client.get(url, headers=auth_headers(token), query_string=params)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _listed(client, token: str, **params) -> dict:
    """Chicago Loop Layers' row in the catalog listing *params* ask for."""
    rows = [item for item in _get(client, token, "/api/datasets/catalog", **params)["items"]
            if item["id"] == CHICAGO]
    assert len(rows) == 1, rows
    return rows[0]


def _add_to_project(client, token: str, project_id: str) -> dict:
    """The answer of "Add to project" for Chicago Loop Layers."""
    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": CHICAGO}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _assert_the_size_of_its_parts(item: dict) -> None:
    """*item* gives the bytes of the parts its ``bundle.json`` lists, read from
    the copy *item*'s path names, not the bytes of ``bundle.json`` itself."""
    assert item["format"] == "bundle", item
    bundle = Path(item["path"])
    assert bundle.name == "bundle.json", item["path"]
    parts, index = bundle_parts_size(bundle), bundle.stat().st_size
    assert parts != index, f"{bundle}: its parts and its index are both {parts} bytes"
    assert item["sizeBytes"] == parts, (
        f"{item['id']} gives {item['sizeBytes']} bytes: its parts are {parts} bytes "
        f"and its bundle.json {index}"
    )


def test_the_hub_lists_a_bundle_at_the_size_of_its_parts(client, user_and_token):
    _user, token = user_and_token
    _assert_the_size_of_its_parts(_listed(client, token))


def test_a_bundles_details_give_the_size_of_its_parts(client, user_and_token):
    _user, token = user_and_token
    _assert_the_size_of_its_parts(_get(client, token, f"/api/datasets/{CHICAGO}"))


def test_adding_a_bundle_to_a_project_answers_with_the_size_of_its_parts(client, user_and_token):
    _user, token = user_and_token
    project_id = create_project(client, token, name="Bundle size")
    _assert_the_size_of_its_parts(_add_to_project(client, token, project_id))


def test_a_project_lists_its_bundle_at_the_size_of_its_parts(client, user_and_token):
    """The Data palette's listing: the project's own row, with the hub left
    out, so no hub row can win the merge and give the size."""
    _user, token = user_and_token
    project_id = create_project(client, token, name="Bundle size")
    _add_to_project(client, token, project_id)
    row = _listed(client, token, dataflowId=project_id, includeHub="false")
    assert row["installed"] is True, row
    _assert_the_size_of_its_parts(row)
