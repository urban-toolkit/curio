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
