from __future__ import annotations

import json


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_dataset_catalog_lists_hub_and_workspace_files(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sample.csv").write_text("name,value\nA,1\n", encoding="utf-8")
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    resp = client.get("/api/datasets/catalog", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.get_json()
    titles = {item["title"] for item in body["items"]}
    assert "Sample" in titles
    assert "Chicago Community Areas" in titles
    assert body["facets"]["origin"]["imported"] >= 1
    assert body["facets"]["origin"]["hub"] >= 1


def test_dataset_preview_reads_csv_rows(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "blocks.csv").write_text("id,name\n1,Loop\n2,Hyde Park\n", encoding="utf-8")
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    catalog = client.get("/api/datasets/catalog?includeHub=false", headers=_auth(token)).get_json()
    dataset = next(item for item in catalog["items"] if item["title"] == "Blocks")

    resp = client.get(f"/api/datasets/{dataset['id']}/preview", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["rows"][0]["name"] == "Loop"
    assert [field["name"] for field in body["schema"]["fields"]] == ["id", "name"]
    assert body["totalRows"] == 2
    assert body["offset"] == 0

    page_two = client.get(
        f"/api/datasets/{dataset['id']}/preview?offset=1&rowLimit=1",
        headers=_auth(token),
    )
    assert page_two.status_code == 200
    page_body = page_two.get_json()
    assert page_body["rows"][0]["name"] == "Hyde Park"
    assert page_body["offset"] == 1
    assert page_body["totalRows"] == 2


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


def test_install_dataset_persists_dataflow_dataset_ref(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "parcels.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    create = client.post(
        "/api/projects",
        data=json.dumps({
            "name": "Dataset install test",
            "spec": {"dataflow": {"name": "Dataset install test", "nodes": [], "edges": []}},
            "outputs": [],
        }),
        headers=_auth(token),
    )
    assert create.status_code == 201, create.get_data(as_text=True)
    project_id = create.get_json()["id"]

    catalog = client.get("/api/datasets/catalog?includeHub=false", headers=_auth(token)).get_json()
    dataset = next(item for item in catalog["items"] if item["title"] == "Parcels")
    install = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": dataset["id"]}),
        headers=_auth(token),
    )

    assert install.status_code == 200, install.get_data(as_text=True)
    detail = client.get(f"/api/projects/{project_id}", headers=_auth(token)).get_json()
    refs = detail["spec"]["dataflow"]["datasets"]
    assert refs[0]["datasetId"] == dataset["id"]
    assert refs[0]["origin"] == "imported"

    scoped_catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=_auth(token),
    ).get_json()
    matching = [item for item in scoped_catalog["items"] if item["id"] == dataset["id"]]
    assert len(matching) == 1
    assert matching[0]["installed"] is True
