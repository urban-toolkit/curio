"""Storage sources end to end: a folder listed by its manifest and added to the
Data Catalog, through the real routes, service and importer. No socket opens:
a folder is read from disk."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from utk_curio.backend.app.datalakes.domain.errors import ResourceNotFound
from utk_curio.backend.app.datalakes.domain.manifest import load_source_manifest
from utk_curio.backend.app.datalakes.providers.folder import FolderStorage
from utk_curio.backend.tests.test_datalakes.conftest import (
    SHIPPED_ROOT,
    a_storage_manifest,
    write_files,
    write_source,
)

SOURCE = "lake.example.folder@1"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


def listing(client, auth, source=SOURCE, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    for _ in range(100):
        body = client.get(f"/api/datalakes/sources/{source}/search?{query}", headers=auth).get_json()
        if body["sources"][0]["status"] != "scanning":
            return body
        time.sleep(0.05)
    raise AssertionError("the scan never finished")


def wait_for(client, auth, job_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/datalakes/jobs/{job_id}", headers=auth).get_json()
        if body["status"] in ("completed", "failed", "refused", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def add(client, auth, resource_id, source=SOURCE, **body):
    from urllib.parse import quote

    return client.post(
        f"/api/datalakes/sources/{source}/resources/{quote(resource_id, safe='')}/acquire",
        headers=auth, json=body,
    )


class TestTheFolderProvider:
    def _provider(self, root: Path, lake_root) -> FolderStorage:
        path = write_source(lake_root, SOURCE, a_storage_manifest(root, [
            {"id": "all", "name": "All", "kind": "table", "format": "csv", "path": "**/*"}
        ]))
        return FolderStorage(load_source_manifest(path))

    def test_hidden_and_system_files_are_never_listed(self, tmp_path, lake_root):
        root = write_files(tmp_path / "f", {
            "a.csv": "x", ".hidden.csv": "x", ".git/config": "x", "Thumbs.db": "x",
            "@eaDir/a.csv": "x", "sub/b.csv": "x",
        })
        found = sorted(e.relpath for e in self._provider(root, lake_root).scan())
        assert found == ["a.csv", "sub/b.csv"]

    def test_a_symlink_out_of_the_root_is_not_followed(self, tmp_path, lake_root):
        outside = write_files(tmp_path / "outside", {"secret.csv": "s"})
        root = write_files(tmp_path / "f", {"a.csv": "x"})
        os.symlink(outside / "secret.csv", root / "link.csv")
        os.symlink(outside, root / "linked-dir")
        provider = self._provider(root, lake_root)
        assert sorted(e.relpath for e in provider.scan()) == ["a.csv"]
        with pytest.raises(ResourceNotFound):
            provider.open("link.csv")

    @pytest.mark.parametrize("relpath", ["../x.csv", "/etc/passwd", "a/../../x", ".git/config", "a\\b"])
    def test_a_relpath_cannot_escape(self, tmp_path, lake_root, relpath):
        provider = self._provider(write_files(tmp_path / "f", {"a.csv": "x"}), lake_root)
        with pytest.raises(ResourceNotFound):
            provider.open(relpath)

    def test_a_byte_range_reads_part_of_a_file(self, tmp_path, lake_root):
        provider = self._provider(write_files(tmp_path / "f", {"a.csv": "0123456789"}), lake_root)
        assert provider.open("a.csv", byte_range=(2, 5)).read() == b"234"


class TestTheListing:
    def test_rows_follow_the_manifest(self, client, auth, app, storage_source):
        body = listing(client, auth)
        rows = {r["resourceId"]: r for r in body["resources"]}
        assert set(rows) == {
            "readings", "by-sensor@sensor=sensor_A", "by-sensor@sensor=sensor_B", "stations",
            "each/aq/sensor_A/2024-01-01.csv", "each/aq/sensor_A/2024-01-02.csv",
            "each/aq/sensor_B/2024-01-01.csv", "each/aq/sensor_B/2024-01-02.csv",
        }
        readings = rows["readings"]
        assert readings["fileCount"] == 4
        assert readings["kind"] == "table"
        assert readings["formats"] == ["csv"]
        fields = {f["name"]: f for f in readings["fieldValues"]}
        assert fields["sensor"]["values"] == ["sensor_A", "sensor_B"]
        assert fields["day"]["type"] == "date"
        assert rows["by-sensor@sensor=sensor_A"]["name"] == "Readings · sensor_A"

    def test_undeclared_files_are_counted_not_listed(self, client, auth, app, storage_source):
        body = listing(client, auth)
        assert body["unmatched"] == 1  # notes.txt; .DS_Store is never seen

    def test_a_search_filters_the_declared_rows(self, client, auth, app, storage_source):
        body = listing(client, auth, q="sensor_B")
        assert {r["resourceId"] for r in body["resources"]} == {
            "readings", "by-sensor@sensor=sensor_B",
            "each/aq/sensor_B/2024-01-01.csv", "each/aq/sensor_B/2024-01-02.csv",
        }

    def test_storage_joins_the_federated_search(self, client, auth, app, storage_source):
        listing(client, auth)  # warm the scan
        body = client.get("/api/datalakes/search?q=stations", headers=auth).get_json()
        legs = {leg["sourceId"]: leg for leg in body["sources"]}
        assert legs["lake.example.folder"]["status"] == "ok"
        assert any(r["resourceId"] == "stations" for r in body["resources"])

    def test_a_rescan_sees_a_new_file(self, client, auth, app, storage_source, storage_folder):
        listing(client, auth)
        write_files(storage_folder, {"aq/sensor_C/2024-01-01.csv": "timestamp,pm25\nx,1\n"})
        body = listing(client, auth, rescan=1)
        assert "by-sensor@sensor=sensor_C" in {r["resourceId"] for r in body["resources"]}

    def test_a_missing_folder_is_a_failed_leg_not_a_500(self, client, auth, app, lake_root, tmp_path):
        from utk_curio.backend.app.datalakes.application import scan

        scan.listings.reset()
        write_source(lake_root, SOURCE, a_storage_manifest(tmp_path / "gone", [
            {"id": "x", "name": "X", "kind": "table", "format": "csv", "path": "*.csv"}
        ]))
        body = listing(client, auth)
        assert body["sources"][0]["status"] == "failed"
        assert "not available" in body["sources"][0]["detail"]

    def test_the_source_row_says_storage_and_hides_the_root(self, client, auth, app, storage_source, storage_folder):
        row = client.get(f"/api/datalakes/sources/{SOURCE}", headers=auth).get_json()
        assert row["kind"] == "storage"
        assert [r["resourceId"] for r in row["resources"]] == ["readings", "by-sensor", "each", "stations"]
        assert str(storage_folder) not in json.dumps(row)


class TestAddingATable:
    def test_one_file_is_copied_as_itself(self, client, auth, app, storage_source):
        res = add(client, auth, "stations")
        assert res.status_code == 202, res.get_data(as_text=True)
        job = wait_for(client, auth, res.get_json()["jobId"])
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert dataset["format"] == "csv"
        assert dataset["rowCount"] == 2
        assert dataset["title"] == "Stations"
        lake = dataset["lakeSource"]
        assert lake["lakeId"] == SOURCE and lake["resourceId"] == "stations"
        assert lake["sourcePath"] == "stations.csv"

    def test_one_file_of_a_per_file_resource(self, client, auth, app, storage_source):
        job = wait_for(client, auth, add(client, auth, "each/aq/sensor_A/2024-01-01.csv").get_json()["jobId"])
        assert job["status"] == "completed", job
        assert job["dataset"]["rowCount"] == 1

    def test_adding_it_again_is_the_same_dataset(self, client, auth, app, storage_source):
        first = wait_for(client, auth, add(client, auth, "stations").get_json()["jobId"])
        again = add(client, auth, "stations")
        assert again.status_code == 200
        assert again.get_json()["alreadyPresent"] is True
        assert again.get_json()["dataset"]["id"] == first["dataset"]["id"]
        row = next(r for r in listing(client, auth)["resources"] if r["resourceId"] == "stations")
        assert row["alreadyHeldDatasetId"] == first["dataset"]["id"]

    def test_the_source_folder_is_never_written(self, client, auth, app, storage_source, storage_folder):
        before = sorted(p.relative_to(storage_folder).as_posix() for p in storage_folder.rglob("*"))
        wait_for(client, auth, add(client, auth, "stations").get_json()["jobId"])
        after = sorted(p.relative_to(storage_folder).as_posix() for p in storage_folder.rglob("*"))
        assert before == after

    def test_an_undeclared_resource_is_refused_before_a_job(self, client, auth, app, storage_source):
        assert add(client, auth, "nope").status_code == 404
        assert add(client, auth, "by-sensor").status_code == 404  # needs a sensor
        assert add(client, auth, "by-sensor@sensor=x;extra=1").status_code == 404


class TestTheShippedExample:
    def test_it_lists_every_use_case(self, client, auth, app, shipped_root):
        from utk_curio.backend.app.datalakes.application import scan

        scan.listings.reset()
        body = listing(client, auth, source="lake.curio.example-storage@1")
        rows = {r["resourceId"]: r for r in body["resources"]}
        assert set(rows) == {
            "air-quality", "stations", "roads", "parks", "orthos", "dashcam", "survey", "noise",
        }
        assert body["unmatched"] == 0
        assert rows["orthos"]["kind"] == "rasters" and rows["orthos"]["fileCount"] == 4
        assert rows["dashcam"]["fileCount"] == 10
        assert rows["survey"]["kind"] == "media"
        assert rows["noise"]["formats"] == ["collection"]

    def test_a_shapefile_arrives_as_geoparquet(self, client, auth, app, shipped_root):
        job = wait_for(client, auth, add(client, auth, "roads", source="lake.curio.example-storage@1").get_json()["jobId"])
        assert job["status"] == "completed", job
        dataset = job["dataset"]
        assert dataset["format"] == "parquet"
        import geopandas as gpd

        frame = gpd.read_parquet(dataset["path"])
        assert list(frame["name"]) == ["Madison St", "State St"]
        assert frame.crs.to_epsg() == 4326


class TestTheInstanceRoot:
    def test_an_operator_source_is_listed_beside_the_shipped_ones(self, client, auth, app, shipped_root, tmp_path):
        from utk_curio.backend.app.datalakes.infrastructure import storage

        folder = write_files(tmp_path / "mine", {"a.csv": "x\n1\n"})
        write_source(storage.instance_root(), "lake.me.mine@1", a_storage_manifest(folder, [
            {"id": "a", "name": "A", "kind": "table", "format": "csv", "path": "a.csv"}
        ], id="lake.me.mine"))
        ids = {s["dirName"] for s in client.get("/api/datalakes/catalog", headers=auth).get_json()["sources"]}
        assert "lake.me.mine@1" in ids and "lake.curio.example-storage@1" in ids

    def test_a_shipped_id_cannot_be_shadowed(self, client, auth, app, shipped_root, tmp_path):
        from utk_curio.backend.app.datalakes.infrastructure import storage

        write_source(storage.instance_root(), "lake.curio.example-storage@1", a_storage_manifest(
            tmp_path, [{"id": "a", "name": "A", "kind": "table", "format": "csv", "path": "a.csv"}],
            id="lake.curio.example-storage", name="Impostor",
        ))
        row = client.get("/api/datalakes/sources/lake.curio.example-storage@1", headers=auth).get_json()
        assert row["name"] == "Example storage"

    def test_an_instance_root_must_be_absolute(self, app, tmp_path):
        from dataclasses import replace

        from utk_curio.backend.app.datalakes.domain.manifest import _parse_manifest
        from utk_curio.backend.app.datalakes.infrastructure import storage

        manifest = _parse_manifest(a_storage_manifest("relative/dir", [
            {"id": "a", "name": "A", "kind": "table", "format": "csv", "path": "a.csv"}
        ]), where="m")
        with pytest.raises(storage.StorageRootError, match="absolute"):
            storage.storage_root(replace(manifest, origin=storage.INSTANCE))


def test_a_sandboxed_node_cannot_reach_the_instance_manifests():
    """An operator manifest names a folder the server reads. Under isolation
    the directory is owner-only, so node code can neither read nor add one."""
    from utk_curio.sandbox.isolation import hardening

    assert ".curio/datalakes" in {relative for relative, _ in hardening.SENSITIVE_PATHS}
