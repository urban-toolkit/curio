"""A node's run finds each collection it loads without counting dataset usage.

Node code that loads a collection (``curio_load_collection``) has its run ask
the Data Catalog for it: ``exec_collections.resolve_collections``, then
``DiscoveryService.collection``, then ``get_dataset``. ``get_dataset`` lists
the whole catalog to find the item, and that listing counted every item's
consumers, which reads every dataflow of the account: 61 for an account
signed up on a Curio started with its examples. With 100 people in ten rooms
playing their dataflows (``tests/stress``, run 42528241074), these lookups
were on the GIL holder's stack in 9.7% of py-spy's samples, and in 6.1% when
each person also asked an agent.

A run reads only the collection's own fields, so the lookups count none, as
the reads #1446 changed. The details the Data Catalog opens for a dataset
still count (``test_dataset_usage.py``).

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""
from __future__ import annotations

import json
import time
from urllib.parse import quote

import pytest

from utk_curio.backend.tests.test_discovery.conftest import a_storage_manifest, write_files, write_source

SOURCE = "source.example.folder@1"
RECORDS = {"id": "walk-records", "name": "Walk records", "kind": "files", "path": "walks/{walk}/{record}.json"}


@pytest.fixture()
def records_folder(discovery_dir, tmp_path):
    """Two walks' records in a folder source declaring :data:`RECORDS`."""
    from utk_curio.backend.app.discovery.application import media, scan

    scan.listings.reset()
    media.index_cache._rows.clear()
    root = write_files(tmp_path / "records", {
        "walks/one/metadata.json": json.dumps({"walk": "one"}),
        "walks/two/metadata.json": json.dumps({"walk": "two"}),
    })
    write_source(discovery_dir, SOURCE, a_storage_manifest(root, [RECORDS]))
    yield root
    scan.listings.reset()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _added_collection(client, token) -> dict:
    """The records, added to the account's Data Catalog as one collection."""
    for _ in range(100):
        body = client.get(f"/api/discovery/sources/{SOURCE}/search", headers=_headers(token)).get_json()
        if body["sources"][0]["status"] != "scanning":
            break
        time.sleep(0.05)
    res = client.post(
        f"/api/discovery/sources/{SOURCE}/resources/{quote(RECORDS['id'], safe='')}/acquire",
        headers=_headers(token), json={},
    )
    assert res.status_code == 202, res.get_data(as_text=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        job = client.get(f"/api/discovery/jobs/{res.get_json()['jobId']}", headers=_headers(token)).get_json()
        if job["status"] in ("completed", "failed", "refused", "cancelled"):
            assert job["status"] == "completed", job.get("error")
            return job["dataset"]
        time.sleep(0.02)
    raise AssertionError("the collection was never added")


def _dataflow(client, token, name: str) -> str:
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": name, "spec": {"dataflow": {
            "name": name, "nodes": [{"id": "n1", "type": "PYTHON_COMPUTATION", "x": 0, "y": 0}],
            "edges": [], "datasets": [],
        }}, "outputs": []}),
        headers={**_headers(token), "Content-Type": "application/json"},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


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


def test_a_runs_collection_reads_no_dataflow_of_the_account(client, app, records_folder, user_and_token, monkeypatch):
    from utk_curio.backend.app.discovery.application.exec_collections import resolve_collections

    user, token = user_and_token
    dataset = _added_collection(client, token)
    dataflows = {_dataflow(client, token, "One"), _dataflow(client, token, "Two")}
    read = _spec_reads(monkeypatch)

    with app.test_request_context():
        collections = resolve_collections([dataset["id"]], str(user.id), user=user)

    assert collections[dataset["id"]]["kind"] == "files"
    counted = sorted(set(read) & dataflows)
    assert counted == [], (
        f"finding the run's collection read the account's dataflows {counted}: "
        "it counted every dataset's consumers, which a run never shows"
    )
