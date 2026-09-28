"""Adding a storage row, at its edges: the file limit, adding again, a
shapefile's parts, how a CSV is read, the columns a combined table adds, row
ids that carry odd names, frames, metadata tables, and one file's failure."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from utk_curio.backend.app.datalakes.domain.errors import ResourceNotFound
from utk_curio.backend.app.datalakes.domain.manifest import ManifestError, load_source_manifest
from utk_curio.backend.app.datalakes.providers.storage_base import FileEntry
from utk_curio.backend.tests.test_datalakes.conftest import (
    a_storage_manifest,
    write_files,
    write_source,
)

REPO = Path(__file__).resolve().parents[4]
EXAMPLE_FILES = REPO / "docs" / "examples" / "data" / "storage"


def _plain_jpeg() -> bytes:
    """A small JPEG with no EXIF, so nothing in it says where it was taken."""
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (8, 8), (40, 80, 120)).save(out, format="JPEG")
    return out.getvalue()


JPEG = _plain_jpeg()
SOURCE = "lake.example.folder@1"
EXAMPLE = "lake.curio.example-storage@1"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _fresh():
    from utk_curio.backend.app.datalakes.application import scan

    scan.listings.reset()
    yield
    scan.listings.reset()


def listing(client, auth, source=SOURCE, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    for _ in range(200):
        body = client.get(f"/api/datalakes/sources/{source}/search?{query}", headers=auth).get_json()
        if body["sources"][0]["status"] != "scanning":
            return body
        time.sleep(0.05)
    raise AssertionError("the scan never finished")


def start(client, auth, resource_id, source=SOURCE, **body):
    return client.post(
        f"/api/datalakes/sources/{source}/resources/{quote(resource_id, safe='')}/acquire",
        headers=auth, json=body,
    )


def finish(client, auth, res, timeout=15.0):
    assert res.status_code in (200, 202), res.get_data(as_text=True)
    if res.status_code == 200:
        return res.get_json()
    job_id = res.get_json()["jobId"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/datalakes/jobs/{job_id}", headers=auth).get_json()
        if job["status"] in ("completed", "failed", "refused", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def added(client, auth, resource_id, source=SOURCE, **body):
    job = finish(client, auth, start(client, auth, resource_id, source=source, **body))
    assert job.get("status", "completed") == "completed", job.get("error")
    return job["dataset"]


def a_source(lake_root, root, resources, **overrides):
    write_source(lake_root, SOURCE, a_storage_manifest(root, resources, **overrides))


def shapefile_parts(tmp_path, names=("Clark", "State")) -> dict[str, bytes]:
    """The parts of a two-point shapefile, by suffix."""
    import geopandas as gpd
    from shapely.geometry import Point

    folder = tmp_path / f"shp-{'-'.join(names)}"
    folder.mkdir()
    frame = gpd.GeoDataFrame(
        {"name": list(names)}, geometry=[Point(-87.63, 41.88), Point(-87.62, 41.89)], crs=4326
    )
    frame.to_file(folder / "roads.shp")
    return {p.suffix: p.read_bytes() for p in folder.iterdir()}


class MemoryBucket:
    """A remote source held in memory. Its names match exactly, as a bucket's do."""

    type = "s3"

    def __init__(self, files: dict[str, bytes]):
        self.files = dict(files)

    def scan(self, prefix=""):
        for relpath in sorted(self.files):
            if relpath.startswith(prefix):
                data = self.files[relpath]
                yield FileEntry(
                    relpath=relpath, size=len(data), mtime=1_700_000_000.0,
                    etag=hashlib.md5(data).hexdigest(),
                )

    def open(self, relpath, *, byte_range=None, **_kwargs):
        if relpath not in self.files:
            raise ResourceNotFound(f"{relpath}: the bucket answered 404")
        data = self.files[relpath]
        if byte_range is not None:
            data = data[byte_range[0]:byte_range[1]]
        return io.BytesIO(data)

    def local_path(self, relpath):
        return None


def an_acquire(provider, installed: list):
    """The storage add path over *provider*, installing into *installed*."""
    import geopandas as gpd

    from utk_curio.backend.app.datalakes.application.storage_acquire import StorageAcquire

    def install_path(path, filename, fmt, **kwargs):
        frame = gpd.read_parquet(path) if fmt == "parquet" else None
        installed.append({"filename": filename, "format": fmt, "frame": frame, **kwargs})
        return {"id": f"d{len(installed)}", "format": fmt, "lakeSource": kwargs.get("lake_source")}

    return StorageAcquire(
        user_key="guest",
        storage_for=lambda _manifest: provider,
        install_path=install_path,
        import_layers=lambda *a, **k: {},
        find_held=lambda *a: None,
    )


class TestTheFileLimit:
    def test_more_files_than_the_limit_is_refused_rather_than_cut(self, client, auth, app, lake_root, tmp_path):
        root = write_files(tmp_path / "f", {f"aq/2024-01-0{d}.csv": "v\n1\n" for d in range(1, 5)})
        a_source(lake_root, root, [
            {"id": "aq", "name": "Readings", "kind": "table", "format": "csv", "path": "aq/{day:date}.csv"}
        ], limits={"maxFiles": 3})
        job = finish(client, auth, start(client, auth, "aq"))
        assert job["status"] == "failed"
        assert "more than 3 files" in job["error"]

    def test_exactly_the_limit_is_all_of_it(self, client, auth, app, lake_root, tmp_path):
        root = write_files(tmp_path / "f", {f"aq/2024-01-0{d}.csv": "v\n1\n" for d in range(1, 4)})
        a_source(lake_root, root, [
            {"id": "aq", "name": "Readings", "kind": "table", "format": "csv", "path": "aq/{day:date}.csv"}
        ], limits={"maxFiles": 3})
        assert listing(client, auth)["truncated"] is False
        assert added(client, auth, "aq")["rowCount"] == 3


class TestAddingAgain:
    def test_a_table_whose_files_did_not_change_is_the_dataset_already_held(
        self, client, auth, app, storage_source
    ):
        first = added(client, auth, "readings")
        job = finish(client, auth, start(client, auth, "readings", refresh=True))
        assert job["status"] == "completed", job.get("error")
        assert job["unchanged"] is True and job["dataset"]["id"] == first["id"]

    def test_a_collection_whose_files_did_not_change_is_the_dataset_already_held(
        self, client, auth, app, shipped_root
    ):
        first = added(client, auth, "orthos", source=EXAMPLE)
        job = finish(client, auth, start(client, auth, "orthos", source=EXAMPLE, refresh=True))
        assert job["unchanged"] is True and job["dataset"]["id"] == first["id"]

    def test_new_files_make_a_new_dataset_and_the_row_holds_it(
        self, client, auth, app, storage_source, storage_folder
    ):
        first = added(client, auth, "readings")
        write_files(storage_folder, {"aq/sensor_C/2024-01-01.csv": "timestamp,pm25\nx,1\n"})
        second = added(client, auth, "readings", refresh=True)
        assert second["id"] != first["id"]
        assert second["rowCount"] == first["rowCount"] + 1
        rows = listing(client, auth, rescan=1)["resources"]
        row = next(r for r in rows if r["resourceId"] == "readings")
        assert row["alreadyHeldDatasetId"] == second["id"]


class TestShapefiles:
    def test_its_parts_are_found_in_the_case_the_bucket_names_them(self, app, lake_root, tmp_path):
        from utk_curio.backend.app.datalakes.application import scan

        parts = shapefile_parts(tmp_path)
        bucket = MemoryBucket({f"city/ROADS{suffix.upper()}": data for suffix, data in parts.items()})
        a_source(lake_root, tmp_path, [
            {"id": "roads", "name": "Roads", "kind": "table", "format": "shp", "path": "city/ROADS.SHP"}
        ])
        manifest = load_source_manifest(lake_root / SOURCE)
        installed: list = []
        result = an_acquire(bucket, installed).acquire(manifest, "roads")
        assert result["dataset"]["format"] == "parquet"
        assert list(installed[0]["frame"]["name"]) == ["Clark", "State"]
        scan.listings.reset()

    def test_a_changed_dbf_is_a_change(self, client, auth, app, lake_root, tmp_path):
        folder = tmp_path / "f"
        write_files(folder, {f"city/roads{suffix}": data for suffix, data in shapefile_parts(tmp_path).items()})
        a_source(lake_root, folder, [
            {"id": "roads", "name": "Roads", "kind": "table", "format": "shp", "path": "city/roads.shp"}
        ])
        first = added(client, auth, "roads")
        renamed = shapefile_parts(tmp_path, names=("Lake", "Wacker"))
        dbf = folder / "city" / "roads.dbf"
        dbf.write_bytes(renamed[".dbf"])
        later = time.time() + 10
        os.utime(dbf, (later, later))
        second = added(client, auth, "roads", refresh=True)
        assert second["id"] != first["id"]

    def test_a_long_or_foreign_name_keeps_its_extension(self):
        from utk_curio.backend.app.datalakes.application.storage_acquire import _filename

        long_name = _filename("folder/" + "x" * 300 + ".csv")
        assert long_name.endswith(".csv") and len(long_name) <= 120
        assert _filename("日本.csv") == "data.csv"


class TestHowACsvIsRead:
    def test_a_csv_with_a_declared_delimiter_is_read_by_it(self, client, auth, app, lake_root, tmp_path):
        import pandas as pd

        root = write_files(tmp_path / "f", {"sites.csv": "site;count\nClark;3\nState;5\n"})
        a_source(lake_root, root, [
            {"id": "sites", "name": "Sites", "kind": "table", "format": "csv", "path": "sites.csv",
             "options": {"delimiter": ";"}}
        ])
        dataset = added(client, auth, "sites")
        assert dataset["format"] == "parquet"
        frame = pd.read_parquet(dataset["path"])
        assert list(frame["site"]) == ["Clark", "State"] and list(frame["count"]) == [3, 5]


class TestTheColumnsACombinedTableAdds:
    def test_a_files_own_columns_are_never_lost(self, client, auth, app, lake_root, tmp_path):
        import pandas as pd

        header = "filename,source_file,Sensor,value\n"
        root = write_files(tmp_path / "f", {
            "aq/s1/2024-01-01.csv": header + "a.jpg,camera,S-1,1\n",
            "aq/s2/2024-01-01.csv": header + "b.jpg,camera,S-2,2\n",
        })
        a_source(lake_root, root, [
            {"id": "aq", "name": "Readings", "kind": "table", "format": "csv",
             "path": "aq/{sensor}/{day:date}.csv"}
        ])
        frame = pd.read_parquet(added(client, auth, "aq")["path"])
        assert list(frame.columns) == [
            "filename", "source_file", "Sensor", "value", "sensor_from_path", "day",
            "source_file_from_path",
        ]
        assert list(frame["filename"]) == ["a.jpg", "b.jpg"]
        assert list(frame["sensor_from_path"]) == ["s1", "s2"]
        assert list(frame["source_file_from_path"]) == ["aq/s1/2024-01-01.csv", "aq/s2/2024-01-01.csv"]


class TestRowIdsWithOddNames:
    def test_split_values_with_a_semicolon_or_a_percent_are_added(self, client, auth, app, lake_root, tmp_path):
        root = write_files(tmp_path / "f", {
            "aq/a;b/2024-01-01.csv": "v\n1\n",
            "aq/c%20d/2024-01-01.csv": "v\n2\n",
        })
        a_source(lake_root, root, [
            {"id": "by", "name": "By sensor", "kind": "table", "format": "csv",
             "path": "aq/{sensor}/{day:date}.csv", "datasets": "per:sensor"}
        ])
        ids = sorted(r["resourceId"] for r in listing(client, auth)["resources"])
        assert ids == ["by@sensor=a%3Bb", "by@sensor=c%2520d"]
        for resource_id in ids:
            assert added(client, auth, resource_id)["rowCount"] == 1

    def test_a_file_name_with_a_percent_is_listed_and_added(self, client, auth, app, lake_root, tmp_path):
        root = write_files(tmp_path / "f", {"t/x%41.csv": "v\n1\n"})
        a_source(lake_root, root, [
            {"id": "each", "name": "Each", "kind": "table", "format": "csv", "path": "t/{name}.csv",
             "datasets": "per-file"}
        ])
        listing(client, auth)
        resource_id = "each/t/x%41.csv"
        res = client.get(
            f"/api/datalakes/sources/{SOURCE}/resources/{quote(resource_id, safe='')}", headers=auth
        )
        assert res.status_code == 200, res.get_data(as_text=True)
        assert added(client, auth, resource_id)["rowCount"] == 1


class TestFrames:
    def test_a_frame_number_must_be_captured_as_a_number(self, lake_root, tmp_path):
        write_source(lake_root, SOURCE, a_storage_manifest(tmp_path, [
            {"id": "f", "name": "Frames", "kind": "frames", "path": "{sequence}/{frame}.jpg"}
        ]))
        with pytest.raises(ManifestError, match=r"\{frame:int\}"):
            load_source_manifest(lake_root / SOURCE)

    def test_frames_are_in_number_order_and_timed_by_their_number(self, client, auth, app, lake_root, tmp_path):
        import pandas as pd

        root = write_files(tmp_path / "f", {f"clips/a/f_{n}.jpg": JPEG for n in (1, 2, 10)})
        a_source(lake_root, root, [
            {"id": "f", "name": "Frames", "kind": "frames", "path": "clips/{sequence}/f_{frame:int}.jpg",
             "fps": 2}
        ])
        index = pd.read_parquet(added(client, auth, "f")["path"])
        assert list(index["frame"]) == [1, 2, 10]
        assert list(index["t_s"]) == [0.5, 1.0, 5.0]


class TestMetadataTables:
    def test_a_parquet_table_is_joined(self, client, auth, app, lake_root, tmp_path):
        import pandas as pd

        root = write_files(tmp_path / "f", {f"clips/a/f_{n}.jpg": JPEG for n in (1, 2)})
        pd.DataFrame({"frame": [1, 2], "lat": [41.88, 41.89], "lon": [-87.63, -87.62]}).to_parquet(
            root / "clips" / "telemetry.parquet"
        )
        a_source(lake_root, root, [
            {"id": "f", "name": "Frames", "kind": "frames", "path": "clips/{sequence}/f_{frame:int}.jpg",
             "metadata": {"path": "clips/telemetry.parquet", "on": "frame"}}
        ])
        dataset = added(client, auth, "f")
        index = pd.read_parquet(dataset["path"])
        assert list(index["gps_lat"]) == [41.88, 41.89]
        assert dataset["collection"]["hasGps"] is True

    def test_a_table_in_a_bucket_is_joined(self, app, lake_root, tmp_path):
        import pandas as pd

        from utk_curio.backend.app.datalakes.application import index_collection

        bucket = MemoryBucket({"clips/telemetry.csv": b"file_name,lat,lon\nf_1.jpg,41.88,-87.63\n"})
        a_source(lake_root, tmp_path, [
            {"id": "f", "name": "Frames", "kind": "frames", "path": "clips/{sequence}/f_{frame:int}.jpg",
             "metadata": {"path": "clips/telemetry.csv"}}
        ])
        manifest = load_source_manifest(lake_root / SOURCE)
        frame = pd.DataFrame({"name": ["f_1.jpg"], "sequence": ["a"], "frame": [1]})
        joined = index_collection.join_metadata(manifest, bucket, manifest.resources[0], frame)
        assert list(joined["gps_lat"]) == [41.88]


class TestIndexingOneFileAtATime:
    def test_a_file_gone_before_it_is_read_keeps_its_row(self, app, lake_root, tmp_path):
        from utk_curio.backend.app.datalakes.application import index_collection
        from utk_curio.backend.app.datalakes.application.scan import MatchedFile

        class Vanishing(MemoryBucket):
            def local_path(self, relpath):
                raise ResourceNotFound(f"{relpath} is not a file of this source")

        a_source(lake_root, tmp_path, [{"id": "p", "name": "Pictures", "kind": "images", "path": "*"}])
        manifest = load_source_manifest(lake_root / SOURCE)
        files = [MatchedFile(relpath="gone.jpg", size=10, mtime=1.0, values={})]
        rows = index_collection.build_rows(manifest, Vanishing({}), manifest.resources[0], files)
        assert len(rows) == 1 and "not a file" in rows[0]["probe_error"]

    def test_a_video_in_a_bucket_is_listed_not_counted_unreadable(self, app, lake_root, tmp_path):
        from utk_curio.backend.app.datalakes.application import index_collection
        from utk_curio.backend.app.datalakes.application.scan import MatchedFile

        a_source(lake_root, tmp_path, [{"id": "v", "name": "Clips", "kind": "videos", "path": "*"}])
        manifest = load_source_manifest(lake_root / SOURCE)
        files = [MatchedFile(relpath="c.mp4", size=10, mtime=1.0, values={})]
        rows = index_collection.build_rows(manifest, MemoryBucket({"c.mp4": b"x" * 10}), manifest.resources[0], files)
        assert rows[0].get("probe_error") is None


class TestTheCollectionBlock:
    def test_it_names_the_resource_and_says_what_its_files_cover(self, client, auth, app, shipped_root):
        block = added(client, auth, "orthos", source=EXAMPLE)["collection"]
        assert block["resourceName"] == "Drone orthoimagery"
        assert [f["name"] for f in block["fieldValues"]] == ["year", "tile"]
        assert block["fieldValues"][0]["values"] == ["2023", "2024"]
        assert block["crs"] == ["EPSG:32616"]
        west, south, east, north = block["bounds"]
        assert west < east and south < north and -90 <= south <= 90


class TestRowProfiles:
    def test_a_row_counts_its_files_by_what_they_are(self, client, auth, app, shipped_root):
        rows = {r["resourceId"]: r["description"] for r in listing(client, auth, source=EXAMPLE)["resources"]}
        assert "3 images, 1 video" in rows["survey"]
        assert re.search(r"2 sequences · \d+ frames", rows["dashcam"])
        assert re.search(r"\d+ recordings", rows["noise"])
        assert re.search(r"\d+ files", rows["orthos"])


class TestUnknownTimes:
    def test_a_time_of_zero_is_no_time(self):
        from utk_curio.backend.app.datalakes.application import index_collection, scan

        assert scan._iso(0) is None and scan._iso(0.0) is None
        assert index_collection._utc(0.0) is None

    def test_an_object_tag_is_part_of_the_fingerprint(self):
        from utk_curio.backend.app.datalakes.application.index_collection import fingerprint
        from utk_curio.backend.app.datalakes.application.scan import MatchedFile

        before = MatchedFile(relpath="a.jpg", size=1, mtime=0.0, values={}, etag="one")
        after = MatchedFile(relpath="a.jpg", size=1, mtime=0.0, values={}, etag="two")
        assert fingerprint([before]) != fingerprint([after])


class TestWhatUsersAreTold:
    def test_a_missing_folder_is_reported_without_its_path(self, client, auth, app, lake_root, tmp_path):
        gone = tmp_path / "gone"
        a_source(lake_root, gone, [{"id": "x", "name": "X", "kind": "table", "format": "csv", "path": "*.csv"}])
        body = listing(client, auth)
        assert body["sources"][0]["status"] == "failed"
        assert str(gone) not in json.dumps(body)

    def test_a_manifest_that_does_not_parse_is_logged_once(self, client, auth, app, lake_root, caplog):
        write_source(lake_root, "lake.example.broken@1", {"id": "lake.example.broken"})
        with caplog.at_level("WARNING"):
            client.get("/api/datalakes/catalog", headers=auth)
            client.get("/api/datalakes/catalog", headers=auth)
        said = [r.getMessage() for r in caplog.records if "lake.example.broken@1" in r.getMessage()]
        assert len(said) == 1 and "is not listed" in said[0]

    def test_the_audit_names_the_folder_in_the_way(self, tmp_path):
        from utk_curio.backend.app.datalakes.infrastructure.storage import unreadable_part

        closed = tmp_path / "closed"
        shared = closed / "shared"
        shared.mkdir(parents=True)
        assert unreadable_part(shared, os.getuid(), set()) is None
        os.chmod(closed, 0o600)  # its owner can list it, not pass through it
        try:
            assert unreadable_part(shared, os.getuid(), set()) == closed.resolve()
        finally:
            os.chmod(closed, 0o755)


class TestJobsAlwaysEnd:
    def test_a_worker_that_cannot_start_ends_its_job_and_frees_its_slot(
        self, client, auth, app, storage_source, monkeypatch
    ):
        from utk_curio.backend.app.datalakes import service as service_module

        def broken(_user_id):
            raise RuntimeError("the database is gone")

        monkeypatch.setattr(service_module, "_user_by_id", broken)
        # More than one user's download slots, so a leaked slot would refuse.
        for _ in range(3):
            job = finish(client, auth, start(client, auth, "stations"), timeout=5.0)
            assert job["status"] == "failed" and "database is gone" in job["error"]


class TestTheLinkKey:
    def test_workers_making_the_key_at_once_all_get_the_whole_key(self, app, monkeypatch):
        from utk_curio.backend.app.datalakes.application import media

        real_fdopen = os.fdopen

        def slow_fdopen(*args, **kwargs):
            # Holds a key's file open, unwritten, the way a busy host might.
            handle = real_fdopen(*args, **kwargs)
            time.sleep(0.05)
            return handle

        monkeypatch.setattr(os, "fdopen", slow_fdopen)
        racers = 8
        barrier = threading.Barrier(racers)
        keys: list[bytes] = []

        def run():
            barrier.wait(timeout=10)
            keys.append(media._link_secret())

        threads = [threading.Thread(target=run) for _ in range(racers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(keys) == racers
        assert {len(key) for key in keys} == {32}
        assert len(set(keys)) == 1
