"""A ``files`` resource: files of any type, listed, added and cached as any
collection's are, with no preview, for node code to read from each row's
``path``.

The fixtures are shaped on a SideSeeing walk on data.urbantk.org: each walk's
folder holds its ``metadata.json`` and ``anonymization.json`` (their real keys,
trimmed), beside the walk's video and GPS table, which the resource's path
leaves out. No socket opens: the bucket is a recorded corpus, as in
``test_cache_collection.py``.
"""

from __future__ import annotations

import json
import time
from urllib.parse import quote

import pytest

from utk_curio.backend.app.discovery.application import index_collection, scan
from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.providers.folder import FolderStorage
from utk_curio.backend.tests.test_discovery.conftest import (
    a_storage_manifest,
    write_files,
    write_source,
)

SOURCE = "source.example.folder@1"
BUCKET = "https://sideseeing.example"
BUCKET_SOURCE = "source.example.sideseeing@1"

#: Two West Loop walks, each named by when its button was pressed, Chicago time.
WALKS = {
    "2026-10-26-15-45-51-706": ("2026-10-26T20:45:51.706Z", "2026-10-26T20:45:52.071Z"),
    "2026-10-26-16-03-17-016": ("2026-10-26T21:03:17.016Z", "2026-10-26T21:03:17.376Z"),
}

RECORDS = {
    "id": "walk-records", "name": "Walk records", "kind": "files",
    "path": "chicago/west-loop/{walk}/{record}.json",
}


def metadata(walk: str) -> str:
    """A walk's ``metadata.json``: when it was recorded, and on what."""
    button, media = WALKS[walk]
    return json.dumps({
        "time": {
            "buttonStartDateTime": button,
            "buttonStopDateTime": "2026-10-26T21:17:41.809Z",
            "mediaStartDateTime": media,
            "mediaStopDateTime": "2026-10-26T21:17:42.434Z",
        },
        "deviceStartAngle": "75.29°",
        "device": {"model": "moto g 5G - 2023", "manufacturer": "motorola", "androidVersion": 34},
    })


def anonymization(walk: str) -> str:
    """A walk's ``anonymization.json``: what was blurred, and whether checked."""
    return json.dumps({
        "capture": walk,
        "status": "processed-not-privacy-validated",
        "method": "egoblur",
        "created_utc": "2026-11-07T05:54:54+00:00",
        "what_changed": "video.mp4 only: faces and licence plates blurred, re-encoded, written upright. "
                        "The other files are the raw capture unchanged.",
        "detector": {"name": "EgoBlur Gen2", "score_threshold": {"face": 0.67416, "plate": 0.74475}},
    })


def walk_files() -> dict[str, str | bytes]:
    files: dict[str, str | bytes] = {}
    for walk in WALKS:
        folder = f"chicago/west-loop/{walk}"
        files[f"{folder}/metadata.json"] = metadata(walk)
        files[f"{folder}/anonymization.json"] = anonymization(walk)
        files[f"{folder}/video.mp4"] = b"not a video"
        files[f"{folder}/gps.csv"] = "datetime_utc,gps_interval,accuracy,latitude,longitude\n" \
                                     "2026-10-26T21:03:21.474Z,1,11.012,41.8815693,-87.6573169\n"
    return files


def parse(raw):
    return M._parse_manifest(raw, where="manifest.json")


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def walks_folder(discovery_dir, tmp_path):
    """The two walks in a folder source declaring :data:`RECORDS`."""
    from utk_curio.backend.app.discovery.application import media

    scan.listings.reset()
    media.index_cache._rows.clear()
    root = write_files(tmp_path / "sideseeing", walk_files())
    write_source(discovery_dir, SOURCE, a_storage_manifest(root, [RECORDS]))
    yield root
    scan.listings.reset()


def _wait(client, auth, job_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/discovery/jobs/{job_id}", headers=auth).get_json()
        if body["status"] in ("completed", "failed", "refused", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def _listing(client, auth, source):
    for _ in range(100):
        body = client.get(f"/api/discovery/sources/{source}/search", headers=auth).get_json()
        if body["sources"][0]["status"] != "scanning":
            return body
        time.sleep(0.05)
    raise AssertionError("the scan never finished")


def _add(client, auth, source, resource_id):
    res = client.post(
        f"/api/discovery/sources/{source}/resources/{quote(resource_id, safe='')}/acquire", headers=auth, json={},
    )
    assert res.status_code == 202, res.get_data(as_text=True)
    job = _wait(client, auth, res.get_json()["jobId"])
    assert job["status"] == "completed", job.get("error")
    return job["dataset"]


def _node_rows(app, user, dataset):
    """What ``curio_load_collection`` gives node code for *dataset*, as a run
    resolves it."""
    from utk_curio.backend.app.discovery.application.exec_collections import resolve_collections
    from utk_curio.backend.app.discovery.infrastructure import media_dirs
    from utk_curio.sandbox.util.collections import make_collection_helpers

    with app.test_request_context():
        collections = resolve_collections([dataset["id"]], str(user.id), user=user)
    assert collections[dataset["id"]]["kind"] == "files"
    helpers = make_collection_helpers(
        lambda _id: dataset["path"], collections, str(media_dirs.media_work_root(str(user.id))),
    )
    return helpers["curio_load_collection"](dataset["id"])


class TestTheManifest:
    def test_a_files_resource_takes_every_file_its_path_matches(self):
        spec = parse(a_storage_manifest("/srv/x", [RECORDS])).resources[0]
        assert (spec.kind, spec.extensions, spec.dataset_format) == ("files", (), "collection")
        assert spec.is_collection and not spec.has_previews

    def test_it_may_narrow_the_extensions(self):
        spec = parse(a_storage_manifest("/srv/x", [{**RECORDS, "path": "chicago/{walk}/{record}",
                                                    "extensions": ["json", "csv"]}])).resources[0]
        assert spec.extensions == ("json", "csv")

    def test_it_round_trips_and_lists_no_extensions_it_does_not_narrow(self):
        narrowed = {**RECORDS, "id": "csv-only", "path": "chicago/{walk}/{record}", "extensions": ["csv"]}
        m = parse(a_storage_manifest("/srv/x", [RECORDS, narrowed]))
        written = M.build_manifest_dict(m)["resources"]
        assert "extensions" not in written[0] and written[1]["extensions"] == ["csv"]
        assert parse(M.build_manifest_dict(m)) == m

    def test_its_files_land_as_one_collection_not_one_dataset_each(self):
        with pytest.raises(M.ManifestError, match="row of a collection"):
            parse(a_storage_manifest("/srv/x", [{**RECORDS, "datasets": "per-file"}]))

    def test_a_kind_it_does_not_know_is_still_refused(self):
        with pytest.raises(M.ManifestError, match="kind must be one of"):
            parse(a_storage_manifest("/srv/x", [{**RECORDS, "kind": "file"}]))


class TestTheIndex:
    def test_every_file_is_a_file_row_and_nothing_is_read_from_it(self, tmp_path):
        """A video, a JPEG that is not one, a CSV and a file with no extension:
        each is a ``file`` row, probed for nothing, whatever its name says."""
        root = write_files(tmp_path / "walk", {
            "w/metadata.json": metadata("2026-10-26-16-03-17-016"),
            "w/video.mp4": b"not a video",
            "w/still.jpg": b"not a jpeg",
            "w/gps.csv": "datetime_utc\n",
            "w/README": "notes",
        })
        manifest = parse(a_storage_manifest(root, [{**RECORDS, "path": "{walk}/{part}"}]))
        provider = FolderStorage(manifest)
        group = scan.scan(manifest, provider).groups[0]
        rows = index_collection.build_rows(manifest, provider, group.spec, group.files)
        assert sorted(r["name"] for r in rows) == ["README", "gps.csv", "metadata.json", "still.jpg", "video.mp4"]
        assert {r["kind"] for r in rows} == {"file"}
        read = {"probe_error", "width", "height", "duration_s", "codec", "taken_at", "sample_rate"}
        assert [sorted(read & set(r)) for r in rows] == [[]] * 5
        assert next(r for r in rows if r["name"] == "README")["ext"] == ""


class TestAFolderOfWalks:
    def test_its_row_says_files_and_draws_no_thumbnail(self, client, auth, app, walks_folder):
        row = next(r for r in _listing(client, auth, SOURCE)["resources"] if r["resourceId"] == "walk-records")
        assert row["kind"] == "files"
        assert row["description"].startswith("Files · 4 files"), row["description"]
        assert row["samples"] == []
        thumb = client.get(f"/api/discovery/sources/{SOURCE}/thumbnails/0/walk-records", headers=auth)
        assert thumb.status_code == 404

    def test_its_files_list_has_the_records_and_no_previews(self, client, auth, app, walks_folder):
        _listing(client, auth, SOURCE)
        body = client.get(f"/api/discovery/sources/{SOURCE}/files/walk-records", headers=auth).get_json()
        assert body["previews"] is False and body["total"] == 4
        # The resource's path names the JSON records; the video and the GPS table stay out.
        assert sorted({f["values"]["record"] for f in body["files"]}) == ["anonymization", "metadata"]

    def test_node_code_reads_each_record_from_its_path(self, client, auth, app, walks_folder, user_and_token):
        user, _token = user_and_token
        dataset = _add(client, auth, SOURCE, "walk-records")
        block = dataset["collection"]
        assert (block["kind"], block["counts"], block["fileCount"]) == ("files", {"file": 4}, 4)
        assert block["probeErrors"] == 0

        rows = _node_rows(app, user, dataset)

        assert set(rows["kind"]) == {"file"}
        assert rows[["thumbnail", "image_url", "audio_url"]].isna().all().all()
        # The file itself, in place in the source's folder.
        assert all(str(path).startswith(str(walks_folder.resolve())) for path in rows["path"])
        started = {}
        for _, row in rows.iterrows():
            with open(row["path"], encoding="utf-8") as handle:
                record = json.load(handle)
            if row["record"] == "metadata":
                started[row["walk"]] = record["time"]["mediaStartDateTime"]
            else:
                assert (record["capture"], record["status"]) == (row["walk"], "processed-not-privacy-validated")
        assert started == {walk: media for walk, (_button, media) in WALKS.items()}

    def test_the_media_route_draws_and_serves_none_of_it(self, client, auth, app, walks_folder):
        import pandas as pd

        dataset = _add(client, auth, SOURCE, "walk-records")
        file_id = pd.read_parquet(dataset["path"])["file_id"].iloc[0]
        url = f"/api/datasets/{dataset['id']}/media/{file_id}"
        thumb = client.get(f"{url}?variant=thumb", headers=auth)
        assert thumb.status_code == 400 and "no preview for a file" in thumb.get_json()["error"]
        assert client.get(f"{url}?variant=poster", headers=auth).status_code == 415
        # A JSON file is no format a browser shows, so it is not served as one.
        assert client.get(f"{url}?variant=original", headers=auth).status_code == 415
        assert client.post(f"{url}/link", headers=auth).status_code == 415

    def test_its_details_show_no_strip(self, client, auth, app, walks_folder):
        dataset = _add(client, auth, SOURCE, "walk-records")
        status = client.get(f"/api/discovery/collections/{dataset['id']}", headers=auth).get_json()
        assert (status["fileCount"], status["samples"]) == (4, [])


def _xml(keys):
    contents = "".join(
        f"<Contents><Key>{key}</Key><Size>{size}</Size>"
        f"<LastModified>2026-11-07T05:55:03.265Z</LastModified><ETag>\"e{i}\"</ETag></Contents>"
        for i, (key, size) in enumerate(keys)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<IsTruncated>false</IsTruncated>{contents}</ListBucketResult>"
    )


@pytest.fixture()
def walks_bucket(tmp_path, monkeypatch, discovery_dir):
    """The two walks in a bucket, listed as data.urbantk.org lists them."""
    from utk_curio.backend.app.discovery.application import media
    from utk_curio.backend.app.discovery.infrastructure import transport

    root = tmp_path / "corpus"
    stored = root / "bucket"
    stored.mkdir(parents=True)
    index = {}
    keys = []
    for key, content in walk_files().items():
        data = content.encode("utf-8") if isinstance(content, str) else content
        name = key.replace("/", "_")
        (stored / name).write_bytes(data)
        index[f"{BUCKET}/{key}"] = {"file": f"bucket/{name}"}
        keys.append((key, len(data)))
    (stored / "listing.xml").write_text(_xml(sorted(keys)), encoding="utf-8")
    prefix = "chicago/west-loop/"
    index[f"{BUCKET}/?list-type=2&max-keys=1000&prefix={quote(prefix, safe='')}"] = {"file": "bucket/listing.xml"}
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setenv(transport.ENV_FIXTURES, str(root))
    monkeypatch.setenv("CURIO_TESTING", "1")
    monkeypatch.delenv("CURIO_MEDIA_CACHE_MAX_GB", raising=False)
    write_source(discovery_dir, BUCKET_SOURCE, {
        "id": "source.example.sideseeing", "name": "SideSeeing", "version": "1.0.0",
        "compatibility": {"major": 1},
        "provider": {"type": "s3", "baseUrl": BUCKET},
        "auth": {"mode": "public"},
        "resources": [RECORDS],
    })
    scan.listings.reset()
    media.index_cache._rows.clear()
    yield root
    scan.listings.reset()


class TestABucketOfWalks:
    def test_its_records_are_read_once_cached(self, client, auth, app, walks_bucket, user_and_token):
        import pandas as pd

        user, _token = user_and_token
        dataset = _add(client, auth, BUCKET_SOURCE, "walk-records")
        assert dataset["collection"]["counts"] == {"file": 4}
        # Listed by path and size; until cached, a node has nothing to open.
        assert _node_rows(app, user, dataset)["path"].isna().all()

        cached = _wait(client, auth, client.post(
            f"/api/discovery/collections/{dataset['id']}/cache", headers=auth,
        ).get_json()["jobId"])

        assert cached["status"] == "completed", cached.get("error")
        rows = _node_rows(app, user, dataset)
        assert rows["path"].notna().all()
        for _, row in rows[rows["record"] == "metadata"].iterrows():
            with open(row["path"], encoding="utf-8") as handle:
                assert json.load(handle)["time"]["mediaStartDateTime"] == WALKS[row["walk"]][1]
        # A cache reads nothing from them either, as it reads a video once cached.
        index = pd.read_parquet(dataset["path"])
        assert "duration_s" not in index.columns and index["probe_error"].isna().all()
        status = client.get(f"/api/discovery/collections/{dataset['id']}", headers=auth).get_json()
        assert (status["cachedFiles"], status["fileCount"], status["samples"]) == (4, 4, [])
