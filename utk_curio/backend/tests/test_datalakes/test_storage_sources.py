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
        assert job["status"] == "completed", job.get("error")
        dataset = job["dataset"]
        assert dataset["format"] == "csv"
        assert dataset["rowCount"] == 2
        assert dataset["title"] == "Stations"
        lake = dataset["lakeSource"]
        assert lake["lakeId"] == SOURCE and lake["resourceId"] == "stations"
        assert lake["sourcePath"] == "stations.csv"

    def test_one_file_of_a_per_file_resource(self, client, auth, app, storage_source):
        job = wait_for(client, auth, add(client, auth, "each/aq/sensor_A/2024-01-01.csv").get_json()["jobId"])
        assert job["status"] == "completed", job.get("error")
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
        assert job["status"] == "completed", job.get("error")
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


class TestCombiningATable:
    def _dataset(self, client, auth, resource_id, source=SOURCE):
        job = wait_for(client, auth, add(client, auth, resource_id, source=source).get_json()["jobId"])
        assert job["status"] == "completed", job.get("error")
        return job

    def test_many_files_become_one_parquet_table(self, client, auth, app, storage_source):
        import pandas as pd

        job = self._dataset(client, auth, "readings")
        dataset = job["dataset"]
        assert dataset["format"] == "parquet"
        assert dataset["rowCount"] == 4
        assert job["itemsDone"] == 4 and job["itemsTotal"] == 4
        frame = pd.read_parquet(dataset["path"])
        assert set(frame.columns) >= {"timestamp", "pm25", "sensor", "day", "source_file"}
        assert sorted(frame["sensor"].unique()) == ["sensor_A", "sensor_B"]
        assert str(frame["day"].iloc[0]) == "2024-01-01"
        assert frame["source_file"].iloc[0] == "aq/sensor_A/2024-01-01.csv"
        assert dataset["lakeSource"]["fileCount"] == 4
        assert dataset["lakeSource"]["fields"] == "sensor,day"

    def test_a_split_row_combines_only_its_files(self, client, auth, app, storage_source):
        import pandas as pd

        dataset = self._dataset(client, auth, "by-sensor@sensor=sensor_B")["dataset"]
        frame = pd.read_parquet(dataset["path"])
        assert list(frame["sensor"].unique()) == ["sensor_B"]
        assert len(frame) == 2

    def test_a_column_one_file_lacks_is_null_there(self, client, auth, app, shipped_root):
        import pandas as pd

        dataset = self._dataset(client, auth, "air-quality", source="lake.curio.example-storage@1")["dataset"]
        frame = pd.read_parquet(dataset["path"])
        assert "humidity" in frame.columns
        assert frame.loc[frame["day"].astype(str) == "2024-01-01", "humidity"].isna().all()
        assert frame.loc[frame["day"].astype(str) == "2024-01-03", "humidity"].notna().all()

    def test_a_file_in_another_encoding_is_read_as_utf8(self, client, auth, app, lake_root, tmp_path):
        import pandas as pd

        from utk_curio.backend.app.datalakes.application import scan

        scan.listings.reset()
        # The sample the encoding tests use: short Western text a detector
        # still reads as cp1252 (#280).
        root = write_files(tmp_path / "enc", {
            "a/one.csv": "city,note\nChicago,loop\n".encode("utf-8"),
            "a/two.csv": "city,note\nCafé,naïve\nZürich,Öl\n".encode("cp1252"),
        })
        write_source(lake_root, SOURCE, a_storage_manifest(root, [
            {"id": "cities", "name": "Cities", "kind": "table", "format": "csv", "path": "a/{part}.csv"}
        ]))
        dataset = self._dataset(client, auth, "cities")["dataset"]
        assert sorted(pd.read_parquet(dataset["path"])["city"]) == ["Café", "Chicago", "Zürich"]

    def test_a_capture_named_like_a_column_keeps_both(self, client, auth, app, lake_root, tmp_path):
        import pandas as pd

        from utk_curio.backend.app.datalakes.application import scan

        scan.listings.reset()
        root = write_files(tmp_path / "clash", {
            "s1/x.csv": "sensor,value\ninner,1\n", "s2/x.csv": "sensor,value\ninner,2\n",
        })
        write_source(lake_root, SOURCE, a_storage_manifest(root, [
            {"id": "v", "name": "V", "kind": "table", "format": "csv", "path": "{sensor}/x.csv"}
        ]))
        frame = pd.read_parquet(self._dataset(client, auth, "v")["dataset"]["path"])
        assert list(frame["sensor"]) == ["inner", "inner"]
        assert sorted(frame["sensor_from_path"]) == ["s1", "s2"]

    def test_geojson_files_combine_into_geoparquet(self, client, auth, app, lake_root, tmp_path):
        import geopandas as gpd

        from utk_curio.backend.app.datalakes.application import scan

        scan.listings.reset()

        def feature(x):
            return json.dumps({"type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {"n": x},
                "geometry": {"type": "Point", "coordinates": [x, 1.0]},
            }]})

        root = write_files(tmp_path / "geo", {"2023/p.geojson": feature(1), "2024/p.geojson": feature(2)})
        write_source(lake_root, SOURCE, a_storage_manifest(root, [
            {"id": "p", "name": "P", "kind": "table", "format": "geojson", "path": "{year:int}/p.geojson"}
        ]))
        frame = gpd.read_parquet(self._dataset(client, auth, "p")["dataset"]["path"])
        assert sorted(frame["year"]) == [2023, 2024]
        assert frame.crs.to_epsg() == 4326


EXAMPLE = "lake.curio.example-storage@1"


class TestAddingACollection:
    def _collection(self, client, auth, resource_id, source=EXAMPLE):
        res = add(client, auth, resource_id, source=source)
        assert res.status_code == 202, res.get_data(as_text=True)
        job = wait_for(client, auth, res.get_json()["jobId"])
        assert job["status"] == "completed", job.get("error")
        return job["dataset"]

    def test_orthorectified_tiles_become_one_index_of_footprints(self, client, auth, app, shipped_root):
        import geopandas as gpd

        dataset = self._collection(client, auth, "orthos")
        assert dataset["format"] == "collection"
        assert dataset["rowCount"] == 4
        block = dataset["collection"]
        assert block["kind"] == "rasters" and block["fileCount"] == 4
        assert block["counts"] == {"raster": 4} and block["hasGps"] is True
        assert block["sourceId"] == EXAMPLE and block["resourceId"] == "orthos"
        index = gpd.read_parquet(dataset["path"])
        assert sorted(index["year"].unique()) == [2023, 2024]
        assert set(index["crs"]) == {"EPSG:32616"}
        assert index.crs.to_epsg() == 4326
        assert index.geometry.geom_type.unique().tolist() == ["Polygon"]
        assert dataset["loaderSnippet"]["code"] == f'collection = curio_collection("{dataset["id"]}")'

    def test_frames_are_numbered_timed_and_placed_by_their_telemetry(self, client, auth, app, shipped_root):
        import geopandas as gpd

        dataset = self._collection(client, auth, "dashcam")
        index = gpd.read_parquet(dataset["path"])
        assert dataset["collection"]["sequences"] == 2
        trip = index[index["sequence"] == "trip01"].sort_values("frame")
        assert list(trip["frame"]) == [1, 2, 3, 4, 5, 6]
        assert list(trip["t_s"]) == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
        assert index["gps_lat"].notna().all() and index.geometry.notna().all()

    def test_photos_and_a_video_share_one_collection(self, client, auth, app, shipped_root):
        import geopandas as gpd

        dataset = self._collection(client, auth, "survey")
        assert dataset["collection"]["counts"] == {"image": 3, "video": 1}
        index = gpd.read_parquet(dataset["path"]).set_index("name")
        assert index.loc["IMG_0001.jpg", "gps_lat"] == pytest.approx(41.8826)
        assert str(index.loc["IMG_0001.jpg", "taken_at"]) == "2024-07-04 09:30:00"
        assert index.loc["clip_01.mp4", "duration_s"] == pytest.approx(1.0)
        assert index.loc["clip_01.mp4", "codec"] == "h264"

    def test_recordings_take_their_time_from_the_file_name(self, client, auth, app, shipped_root):
        import pandas as pd

        dataset = self._collection(client, auth, "noise")
        index = pd.read_parquet(dataset["path"])
        assert set(index["sensor"]) == {"sensor_01", "sensor_02"}
        assert str(sorted(index["recorded_at"])[0]) == "2024-05-01 06:00:00"
        assert set(index["sample_rate"]) == {8000}
        assert dataset["collection"]["totalSeconds"] == pytest.approx(1.5)

    def test_the_index_is_previewable_and_listed_as_held(self, client, auth, app, shipped_root):
        dataset = self._collection(client, auth, "noise")
        preview = client.get(f"/api/datasets/{dataset['id']}/preview?rowLimit=2", headers=auth).get_json()
        assert preview["totalRows"] == 3 and len(preview["rows"]) == 2
        row = next(r for r in listing(client, auth, source=EXAMPLE)["resources"] if r["resourceId"] == "noise")
        assert row["alreadyHeldDatasetId"] == dataset["id"]
        listed = client.get("/api/datasets/catalog", headers=auth).get_json()
        items = listed.get("items") or listed.get("datasets") or []
        mine = next(i for i in items if i["id"] == dataset["id"])
        assert mine["collection"]["kind"] == "audio"

    def test_a_split_collection_holds_only_its_value(self, client, auth, app, lake_root, tmp_path):
        import geopandas as gpd

        from utk_curio.backend.app.datalakes.application import scan

        scan.listings.reset()
        source = SHIPPED_ROOT.parent / "docs" / "examples" / "data" / "storage"
        write_source(lake_root, SOURCE, a_storage_manifest(source, [
            {"id": "orthos", "name": "Orthos", "kind": "rasters",
             "path": "orthos/{year:int}/{tile}.tif", "datasets": "per:year"}
        ]))
        rows = {r["resourceId"] for r in listing(client, auth)["resources"]}
        assert rows == {"orthos@year=2023", "orthos@year=2024"}
        dataset = self._collection(client, auth, "orthos@year=2024", source=SOURCE)
        assert set(gpd.read_parquet(dataset["path"])["year"]) == {2024}
        assert dataset["collection"]["split"] == {"year": "2024"}

    def test_a_file_that_cannot_be_read_keeps_its_row(self, client, auth, app, lake_root, tmp_path):
        import pandas as pd

        from utk_curio.backend.app.datalakes.application import scan

        scan.listings.reset()
        root = write_files(tmp_path / "bad", {"a.jpg": b"not a jpeg", "b.tif": b"II*\x00junk"})
        write_source(lake_root, SOURCE, a_storage_manifest(root, [
            {"id": "pics", "name": "Pics", "kind": "images", "path": "*"}
        ]))
        dataset = self._collection(client, auth, "pics", source=SOURCE)
        index = pd.read_parquet(dataset["path"])
        assert len(index) == 2 and index["probe_error"].notna().all()
        assert dataset["collection"]["probeErrors"] == 2


class TestTheExecUserAudit:
    def test_a_closed_parent_hides_an_open_folder(self, tmp_path):
        """Readable means the mode allows it AND every parent can be traversed."""
        from utk_curio.backend.app.datalakes.infrastructure.storage import readable_by

        closed = tmp_path / "closed"
        shared = closed / "shared"
        shared.mkdir(parents=True)
        os.chmod(shared, 0o755)
        os.chmod(closed, 0o700)
        other_uid = os.getuid() + 12345
        try:
            assert not readable_by(shared, other_uid, set())
            assert readable_by(shared, os.getuid(), set())
            os.chmod(shared, 0o300)
            assert not readable_by(shared, os.getuid(), set())
        finally:
            os.chmod(shared, 0o755)
            os.chmod(closed, 0o755)

    def test_without_isolation_nothing_is_audited(self, monkeypatch):
        from utk_curio.backend.app.datalakes.infrastructure.storage import audit_folder_roots

        monkeypatch.setenv("CURIO_ISOLATION", "off")
        assert audit_folder_roots() == []


class TestNarrowingARow:
    def _added(self, client, auth, resource_id, **body):
        res = add(client, auth, resource_id, source=EXAMPLE, **body)
        assert res.status_code == 202, res.get_data(as_text=True)
        job = wait_for(client, auth, res.get_json()["jobId"])
        assert job["status"] == "completed", job.get("error")
        return job["dataset"]

    def test_field_values_keep_only_their_files(self, client, auth, app, shipped_root):
        listing(client, auth, source=EXAMPLE)
        dataset = self._added(client, auth, "orthos", filters={"year": ["2024"]})
        assert dataset["rowCount"] == 2
        assert dataset["collection"]["narrowedBy"] == {"year": ["2024"]}
        # Part of the row is not the row: it stays offered whole.
        row = next(r for r in listing(client, auth, source=EXAMPLE)["resources"] if r["resourceId"] == "orthos")
        assert row["alreadyHeldDatasetId"] is None
        again = self._added(client, auth, "orthos", filters={"year": ["2024"]})
        assert again["id"] != dataset["id"]

    def test_a_range_keeps_the_values_between_its_bounds(self, client, auth, app, shipped_root):
        import pandas as pd

        listing(client, auth, source=EXAMPLE)
        dataset = self._added(client, auth, "air-quality", filters={
            "day": {"min": "2024-01-02", "max": "2024-01-02"},
        })
        frame = pd.read_parquet(dataset["path"])
        assert set(frame["day"].astype(str)) == {"2024-01-02"}
        assert dataset["lakeSource"]["narrowed"] is True

    def test_picked_files_are_the_only_ones_indexed(self, client, auth, app, shipped_root):
        listing(client, auth, source=EXAMPLE)
        page = client.get(f"/api/datalakes/sources/{EXAMPLE}/files/survey", headers=auth).get_json()
        assert page["total"] == 4 and page["previews"] is True
        picked = [f["relpath"] for f in page["files"][:2]]
        dataset = self._added(client, auth, "survey", files=picked)
        assert dataset["rowCount"] == 2 and dataset["collection"]["chosenFiles"] == 2

    @pytest.mark.parametrize("body, needle", [
        ({"filters": {"nope": ["x"]}}, "no field"),
        ({"filters": {"year": []}}, "between 1 and"),
        ({"filters": {"year": {"min": "x", "max": "2024"}}}, "min and a max"),
        ({"files": ["../etc/passwd"]}, "not a file"),
        ({"files": []}, "between 1 and"),
    ])
    def test_a_narrowing_it_cannot_satisfy_is_refused_before_a_job(
        self, client, auth, app, shipped_root, body, needle
    ):
        res = add(client, auth, "orthos", source=EXAMPLE, **body)
        assert res.status_code == 404 and needle in res.get_json()["error"]

    def test_a_split_field_is_not_narrowed_again(self, client, auth, app, lake_root, tmp_path):
        root = write_files(tmp_path / "f", {"a/1.csv": "n\n1\n", "b/1.csv": "n\n2\n"})
        write_source(lake_root, SOURCE, a_storage_manifest(root, [
            {"id": "t", "name": "T", "kind": "table", "format": "csv", "path": "{part}/1.csv",
             "datasets": "per:part"},
        ]))
        res = add(client, auth, "t@part=a", filters={"part": ["b"]})
        assert res.status_code == 404 and "no field" in res.get_json()["error"]


class TestTheFilesList:
    def test_it_pages_a_rows_files_in_order(self, client, auth, app, shipped_root):
        listing(client, auth, source=EXAMPLE)
        url = f"/api/datalakes/sources/{EXAMPLE}/files/dashcam"
        first = client.get(f"{url}?limit=5", headers=auth).get_json()
        rest = client.get(f"{url}?offset=5&limit=100", headers=auth).get_json()
        assert first["total"] == rest["total"] == 10
        names = [f["relpath"] for f in first["files"] + rest["files"]]
        assert names == sorted(names) and len(names) == 10
        assert first["files"][0]["values"]["sequence"] == "trip01"
        assert [f["index"] for f in rest["files"]][:2] == [5, 6]

    def test_a_table_row_lists_its_files_without_previews(self, client, auth, app, shipped_root):
        listing(client, auth, source=EXAMPLE)
        page = client.get(f"/api/datalakes/sources/{EXAMPLE}/files/air-quality", headers=auth).get_json()
        assert page["previews"] is False and page["total"] > 1
        assert client.get(
            f"/api/datalakes/sources/{EXAMPLE}/thumbnails/0/air-quality", headers=auth
        ).status_code == 404

    def test_a_portal_has_no_files(self, client, auth, app, shipped_root):
        res = client.get("/api/datalakes/sources/lake.chicago.data-portal@1/files/x", headers=auth)
        assert res.status_code in (400, 404, 422)

    def test_it_needs_a_sign_in(self, client, app, shipped_root):
        assert client.get(f"/api/datalakes/sources/{EXAMPLE}/files/orthos").status_code == 401
