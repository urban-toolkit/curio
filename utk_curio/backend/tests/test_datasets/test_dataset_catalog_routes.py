from __future__ import annotations

import json


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_dataset_catalog_lists_hub_datasets(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    resp = client.get("/api/datasets/catalog", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.get_json()
    titles = {item["title"] for item in body["items"]}
    assert "Chicago Community Areas" in titles
    assert body["facets"]["origin"]["hub"] >= 1


def test_install_hub_dataset_copies_to_user_store(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    create = client.post(
        "/api/projects",
        data=json.dumps({
            "name": "Hub install test",
            "spec": {"dataflow": {"name": "Hub install test", "nodes": [], "edges": []}},
            "outputs": [],
        }),
        headers=_auth(token),
    )
    assert create.status_code == 201, create.get_data(as_text=True)
    project_id = create.get_json()["id"]

    catalog = client.get("/api/datasets/catalog", headers=_auth(token)).get_json()
    dataset = next(item for item in catalog["items"] if item["title"] == "Chicago Community Areas")

    install = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": dataset["id"]}),
        headers=_auth(token),
    )
    assert install.status_code == 200, install.get_data(as_text=True)
    body = install.get_json()
    assert body["installed"] is True
    assert body["path"]
    assert "datasets/data.urbanlab.chicago-community-areas@1" in body["path"]

    user_store = tmp_path / ".curio" / "users"
    copied = list(user_store.rglob("community-areas.geojson"))
    assert copied, "hub install should copy payload into the user dataset store"


def test_hub_dataset_preview_reads_catalog_payload(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    catalog = client.get("/api/datasets/catalog", headers=_auth(token)).get_json()
    dataset = next(item for item in catalog["items"] if item["title"] == "ACS Neighborhood Profile")

    resp = client.get(f"/api/datasets/{dataset['id']}/preview?rowLimit=2", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["rows"][0]["tract_id"] == "17031010100"
    assert body.get("unsupported") is not True
