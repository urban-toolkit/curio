"""Buckets and Hugging Face repos, on the recorded corpus: no socket opens.

The shipped sources run on what ``scripts/record_discovery_fixtures.py``
recorded from the real endpoints. Pagination, caching and refusals run on a
small corpus built here, so each shape is exact and deliberate.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlsplit

import pytest

from utk_curio.backend.tests.test_discovery.conftest import FIXTURES, workers_finish_first, write_source

REPO = Path(__file__).resolve().parents[4]
SENTINEL = "source.aws.sentinel-2-chicago@1"
HF = "source.huggingface.documentation-images@1"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _fresh_listings():
    from utk_curio.backend.app.discovery.application import scan

    scan.listings.reset()
    yield
    scan.listings.reset()


def listing(client, auth, source):
    for _ in range(100):
        body = client.get(f"/api/discovery/sources/{source}/search", headers=auth).get_json()
        if body["sources"][0]["status"] != "scanning":
            return body
        time.sleep(0.05)
    raise AssertionError("the scan never finished")


def wait_for(client, auth, job_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/discovery/jobs/{job_id}", headers=auth).get_json()
        if body["status"] in ("completed", "failed", "refused", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def add(client, auth, source, resource_id):
    res = client.post(
        f"/api/discovery/sources/{source}/resources/{quote(resource_id, safe='')}/acquire",
        headers=auth, json={},
    )
    assert res.status_code == 202, res.get_data(as_text=True)
    return wait_for(client, auth, res.get_json()["jobId"])


class TestTheShippedBuckets:
    def test_sentinel_lists_its_scenes(self, client, auth, app, shipped_root, fixture_corpus):
        body = listing(client, auth, SENTINEL)
        assert body["sources"][0]["status"] == "ok", body["sources"]
        rows = {r["resourceId"]: r for r in body["resources"]}
        assert set(rows) == {"previews", "thumbnails"}
        # As recorded: two of the month's scenes carry no thumbnail.
        assert rows["previews"]["fileCount"] == 14
        assert rows["thumbnails"]["fileCount"] == 12
        assert rows["previews"]["kind"] == "rasters"

    def test_sentinel_previews_index_with_footprints_from_one_range_read(
        self, client, auth, app, shipped_root, fixture_corpus
    ):
        import geopandas as gpd

        job = add(client, auth, SENTINEL, "previews")
        assert job["status"] == "completed", job.get("error")
        index = gpd.read_parquet(job["dataset"]["path"])
        assert len(index) == 14
        assert index.geometry.notna().all()
        assert set(index["crs"]) == {"EPSG:32616"}
        assert job["dataset"]["collection"]["provider"] == "s3"

    def test_hugging_face_lists_and_indexes_its_images(self, client, auth, app, shipped_root, fixture_corpus):
        import pandas as pd

        rows = listing(client, auth, HF)["resources"]
        assert [r["resourceId"] for r in rows] == ["task-images"]
        assert rows[0]["fileCount"] == 47
        job = add(client, auth, HF, "task-images")
        assert job["status"] == "completed", job.get("error")
        index = pd.read_parquet(job["dataset"]["path"])
        assert len(index) == 47
        assert (index["width"] > 0).all()


# ── a corpus built here ────────────────────────────────────────────────────

BUCKET = "https://bucket.example"


def _xml(keys, *, token=None):
    contents = "".join(
        f"<Contents><Key>{k}</Key><Size>{size}</Size><LastModified>2024-05-01T00:00:00.000Z</LastModified>"
        f"<ETag>\"e{i}\"</ETag></Contents>"
        for i, (k, size) in enumerate(keys)
    )
    truncated = "true" if token else "false"
    tail = f"<NextContinuationToken>{token}</NextContinuationToken>" if token else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<IsTruncated>{truncated}</IsTruncated>{tail}{contents}</ListBucketResult>"
    )


@pytest.fixture()
def bucket_corpus(tmp_path, monkeypatch, discovery_dir):
    """A two-page bucket of two small CSVs and two images."""
    from utk_curio.backend.app.discovery.infrastructure import transport

    root = tmp_path / "corpus"
    (root / "bucket").mkdir(parents=True)
    index = {}

    def entry(url, name, body, *, status=200, headers=None):
        path = root / "bucket" / name
        path.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
        index[url] = {"file": f"bucket/{name}", "status": status, "headers": headers or {}}

    head = (FIXTURES / "download" / "storage" / "head.jpg").read_bytes()
    tile = (REPO / "docs" / "examples" / "data" / "storage" / "orthos" / "2024" / "tile_0001.tif").read_bytes()
    first = f"{BUCKET}/?list-type=2&max-keys=1000&prefix=data%2F"
    entry(first, "page1.xml", _xml([("data/a/1.csv", 8), ("data/pics/x.jpg", len(head))], token="T/2"))
    entry(first + "&continuation-token=T%2F2", "page2.xml",
          _xml([("data/b/1.csv", 8), ("data/pics/y.jpg", len(head)), ("data/tiles/t.tif", len(tile))]))
    entry(f"{BUCKET}/data/tiles/t.tif", "t.tif", tile)
    # Adding one resource lists only under its own folder.
    entry(f"{BUCKET}/?list-type=2&max-keys=1000&prefix=data%2Fpics%2F", "pics.xml",
          _xml([("data/pics/x.jpg", len(head)), ("data/pics/y.jpg", len(head))]))
    entry(f"{BUCKET}/data/a/1.csv", "a.csv", "n\n1\n")
    entry(f"{BUCKET}/data/b/1.csv", "b.csv", "n\n2\n")
    for name in ("x.jpg", "y.jpg"):
        entry(f"{BUCKET}/data/pics/{name}", name, head)
        entry(f"{BUCKET}/data/pics/{name} bytes=0-65535", f"{name}.head", head, status=206)
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setenv(transport.ENV_FIXTURES, str(root))
    monkeypatch.setenv("CURIO_TESTING", "1")
    write_source(discovery_dir, "source.example.bucket@1", {
        "id": "source.example.bucket", "name": "Bucket", "version": "1.0.0",
        "compatibility": {"major": 1},
        "provider": {"type": "s3", "baseUrl": BUCKET, "options": {"prefix": "data/"}},
        "auth": {"mode": "public"},
        "resources": [
            {"id": "numbers", "name": "Numbers", "kind": "table", "format": "csv", "path": "{part}/1.csv"},
            {"id": "pics", "name": "Pictures", "kind": "images", "path": "pics/*"},
            {"id": "tiles", "name": "Tiles", "kind": "rasters", "path": "tiles/{tile}.tif"},
        ],
    })
    return root


class TestABucket:
    def test_listing_follows_the_continuation_token(self, client, auth, app, bucket_corpus):
        rows = {r["resourceId"]: r for r in listing(client, auth, "source.example.bucket@1")["resources"]}
        assert rows["numbers"]["fileCount"] == 2 and rows["pics"]["fileCount"] == 2

    def test_a_listing_past_its_pages_says_it_was_cut_short(self, client, auth, app, bucket_corpus, monkeypatch):
        from utk_curio.backend.app.discovery.providers import s3

        # The bucket's files are two pages, one past a bound of one.
        monkeypatch.setattr(s3, "MAX_PAGES", 1)
        body = listing(client, auth, "source.example.bucket@1")

        assert body["truncated"] is True, "the listing stopped at its first page of two, and did not say so"
        assert body.get("cutShort") == (
            "This source holds more files than are listed here: a folder's listing stops at 1 page."
        )

    def test_a_listing_as_long_as_its_pages_is_whole(self, client, auth, app, bucket_corpus, monkeypatch):
        from utk_curio.backend.app.discovery.providers import s3

        monkeypatch.setattr(s3, "MAX_PAGES", 2)
        body = listing(client, auth, "source.example.bucket@1")

        assert body["truncated"] is False and body.get("cutShort") is None
        rows = {r["resourceId"]: r for r in body["resources"]}
        assert rows["numbers"]["fileCount"] == 2 and rows["tiles"]["fileCount"] == 1

    def test_a_rasters_thumbnail_is_drawn_before_it_is_cached(self, client, auth, app, bucket_corpus):
        listing(client, auth, "source.example.bucket@1")
        res = client.get("/api/discovery/sources/source.example.bucket@1/thumbnails/0/tiles", headers=auth)
        assert res.status_code == 200, res.get_data(as_text=True)
        assert res.mimetype == "image/jpeg"

    def test_its_tables_combine_like_a_folders(self, client, auth, app, bucket_corpus):
        import pandas as pd

        job = add(client, auth, "source.example.bucket@1", "numbers")
        assert job["status"] == "completed", job.get("error")
        frame = pd.read_parquet(job["dataset"]["path"])
        assert sorted(frame["n"]) == [1, 2] and sorted(frame["part"]) == ["a", "b"]

    def test_images_are_indexed_then_cached_on_request(self, client, auth, app, bucket_corpus):
        from utk_curio.backend.app.discovery.application import cache_collection
        from utk_curio.backend.app.discovery.infrastructure import storage
        import pandas as pd

        job = add(client, auth, "source.example.bucket@1", "pics")
        assert job["status"] == "completed", job.get("error")
        dataset = job["dataset"]
        index = pd.read_parquet(dataset["path"])
        assert index["gps_lat"].notna().all()  # from the head's EXIF
        res = client.post(f"/api/discovery/collections/{dataset['id']}/cache", headers=auth)
        assert res.status_code == 202, res.get_data(as_text=True)
        cached = wait_for(client, auth, res.get_json()["jobId"])
        assert cached["status"] == "completed", cached.get("error")
        assert cached["itemsDone"] == 2
        status = client.get(f"/api/discovery/collections/{dataset['id']}", headers=auth).get_json()
        assert status["local"] is False and status["cachedFiles"] == status["fileCount"] == 2
        assert [s["kind"] for s in status["samples"]] == ["image", "image"]
        user_key = "1"
        for row in index.itertuples():
            path = cache_collection.cached_file(user_key, dataset["id"], row.file_id, row.ext)
            assert path is not None and path.stat().st_size == row.bytes

    def test_a_cache_answers_with_its_job_as_it_began_however_fast_it_ends(
        self, client, auth, app, bucket_corpus, monkeypatch
    ):
        job = add(client, auth, "source.example.bucket@1", "pics")
        workers_finish_first(monkeypatch)
        res = client.post(f"/api/discovery/collections/{job['dataset']['id']}/cache", headers=auth)
        started = res.get_json()
        assert res.status_code == 202, started
        assert (started["status"], started["itemsDone"]) == ("queued", 0), started
        cached = wait_for(client, auth, started["jobId"])
        assert (cached["status"], cached["itemsDone"]) == ("completed", 2), cached

    def test_the_cache_cap_refuses_before_downloading(self, client, auth, app, bucket_corpus, monkeypatch):
        job = add(client, auth, "source.example.bucket@1", "pics")
        status = client.get(f"/api/discovery/collections/{job['dataset']['id']}", headers=auth).get_json()
        assert status["cachedFiles"] == 0 and status["fileCount"] == 2
        monkeypatch.setenv("CURIO_MEDIA_CACHE_MAX_GB", "0")
        res = client.post(f"/api/discovery/collections/{job['dataset']['id']}/cache", headers=auth)
        cached = wait_for(client, auth, res.get_json()["jobId"])
        assert cached["status"] == "failed" and "CURIO_MEDIA_CACHE_MAX_GB" in cached["error"]

    def test_a_folder_collection_needs_no_cache(self, client, auth, app, shipped_root):
        job = add(client, auth, "source.curio.example-storage@1", "noise")
        res = client.post(f"/api/discovery/collections/{job['dataset']['id']}/cache", headers=auth)
        assert res.status_code == 400
        assert "already on this machine" in res.get_json()["error"]
        status = client.get(f"/api/discovery/collections/{job['dataset']['id']}", headers=auth).get_json()
        assert status["local"] is True and status["cachedFiles"] == status["fileCount"] == 3

    def test_a_status_is_only_for_ones_own_collection(self, client, auth, app, shipped_root):
        assert client.get("/api/discovery/collections/imported.xnope@1", headers=auth).status_code == 404
        assert client.get("/api/discovery/collections/imported.xnope@1").status_code == 401


# ── a bucket of walks, one larger than a cached file may be by default ─────

#: Over the 4 GiB a cached file may hold when the operator sets no limit.
OVER_THE_FILE_LIMIT = 5 * 1024**3


@pytest.fixture()
def walks_bucket(tmp_path, monkeypatch, discovery_dir):
    """Two videos: a.mp4, a real clip, then b.mp4, listed at 5 GiB.

    b.mp4's recorded body is the same small clip, so a cache that lets it
    through ends rather than fetching 5 GiB.
    """
    from utk_curio.backend.app.discovery.infrastructure import transport

    root = tmp_path / "corpus"
    (root / "bucket").mkdir(parents=True)
    clip = (REPO / "docs" / "examples" / "data" / "storage" / "survey" / "2025" / "clip_01.mp4").read_bytes()
    (root / "bucket" / "walks.xml").write_text(
        _xml([("data/walks/a.mp4", len(clip)), ("data/walks/b.mp4", OVER_THE_FILE_LIMIT)]),
        encoding="utf-8",
    )
    (root / "bucket" / "clip.mp4").write_bytes(clip)
    index = {
        f"{BUCKET}/?list-type=2&max-keys=1000&prefix=data%2Fwalks%2F": {"file": "bucket/walks.xml"},
        f"{BUCKET}/data/walks/a.mp4": {"file": "bucket/clip.mp4"},
        f"{BUCKET}/data/walks/b.mp4": {"file": "bucket/clip.mp4"},
    }
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setenv(transport.ENV_FIXTURES, str(root))
    monkeypatch.setenv("CURIO_TESTING", "1")
    # The limits a deployment has when its operator sets none.
    monkeypatch.delenv("CURIO_MEDIA_CACHE_MAX_GB", raising=False)
    monkeypatch.delenv("CURIO_MEDIA_CACHE_MAX_FILE_GB", raising=False)
    write_source(discovery_dir, "source.example.walks@1", {
        "id": "source.example.walks", "name": "Walks", "version": "1.0.0",
        "compatibility": {"major": 1},
        "provider": {"type": "s3", "baseUrl": BUCKET, "options": {"prefix": "data/"}},
        "auth": {"mode": "public"},
        "resources": [{"id": "walks", "name": "Walks", "kind": "videos", "path": "walks/{walk}.mp4"}],
    })
    return root


def _cache(client, auth, dataset_id):
    res = client.post(f"/api/discovery/collections/{dataset_id}/cache", headers=auth)
    assert res.status_code == 202, res.get_data(as_text=True)
    return wait_for(client, auth, res.get_json()["jobId"])


class TestTheLimitOnOneCachedFile:
    def test_a_file_over_it_refuses_the_cache_before_any_file_is_fetched(
        self, client, auth, app, walks_bucket, user_and_token
    ):
        from utk_curio.backend.app.discovery.application import cache_collection

        user, _token = user_and_token
        job = add(client, auth, "source.example.walks@1", "walks")
        assert job["status"] == "completed", job.get("error")
        dataset_id = job["dataset"]["id"]

        cached = _cache(client, auth, dataset_id)

        assert cached["status"] == "failed", cached
        # Refused up front: a.mp4, which comes first and fits, was not copied
        # either, so no cache is left half done.
        assert cache_collection.cached_count(str(user.id), dataset_id) == (0, 0)
        # The message names the file, its size and the limit it is over.
        error = cached["error"]
        assert "walks/b.mp4" in error and f"{OVER_THE_FILE_LIMIT:,} bytes" in error, error
        assert f"{4 * 1024**3:,}" in error and "CURIO_MEDIA_CACHE_MAX_FILE_GB" in error, error

    def test_the_operator_raises_it_with_media_cache_max_file_gb(
        self, client, auth, app, walks_bucket, user_and_token, monkeypatch
    ):
        from utk_curio.backend.app.discovery.application import cache_collection

        user, _token = user_and_token
        monkeypatch.setenv("CURIO_MEDIA_CACHE_MAX_FILE_GB", "6")
        job = add(client, auth, "source.example.walks@1", "walks")
        dataset_id = job["dataset"]["id"]

        cached = _cache(client, auth, dataset_id)

        assert cached["status"] == "completed", cached.get("error")
        assert cache_collection.cached_count(str(user.id), dataset_id)[0] == 2


class TreePages:
    """Hugging Face's tree API over *pages* pages of one image each: each page
    but the last names the next in a ``Link`` header on the site itself, or,
    for page *elsewhere*, at the same path on another site."""

    def __init__(self, base: str, pages: int, *, elsewhere: int | None = None):
        self.base = base
        self.pages = pages
        self.elsewhere = elsewhere
        self.asked: list[str] = []

    def get_page(self, url, *, credential=None, headers=None):
        self.asked.append(url)
        page = int(dict(parse_qsl(urlsplit(url).query)).get("cursor", "0"))
        body = json.dumps([
            {"type": "file", "path": f"transformers/tasks/{page:03d}.png", "size": 10, "oid": f"o{page}"},
        ])
        if page + 1 == self.pages:
            return body, {}
        following = url.split("&cursor=")[0] + f"&cursor={page + 1}"
        if page == self.elsewhere:
            following = "https://elsewhere.example" + following[len(self.base):]
        return body, {"Link": f'<{following}>; rel="next"'}


def hugging_face_scan(pages: int, *, elsewhere: int | None = None):
    """The shipped Hugging Face source scanned over :class:`TreePages`."""
    from utk_curio.backend.app.discovery.application import scan
    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
    from utk_curio.backend.app.discovery.providers.huggingface import HuggingFaceStorage

    manifest = load_source_manifest(REPO / "discovery" / HF)
    tree = TreePages(manifest.provider.base_url, pages, elsewhere=elsewhere)
    return scan.scan(manifest, HuggingFaceStorage(manifest, tree)), tree


class TestHuggingFacePagination:
    def test_the_link_header_is_followed_only_on_the_hub(self):
        from utk_curio.backend.app.discovery.providers.huggingface import _next_link

        base = "https://huggingface.co"
        assert _next_link({"Link": f'<{base}/api/x?cursor=2>; rel="next"'}, base) == f"{base}/api/x?cursor=2"
        assert _next_link({"link": '<https://evil.example/x>; rel="next"'}, base) is None
        assert _next_link({}, base) is None

    def test_a_listing_past_its_pages_says_it_was_cut_short(self, monkeypatch):
        from utk_curio.backend.app.discovery.providers import huggingface

        # Three pages, one past a bound of two.
        monkeypatch.setattr(huggingface, "MAX_PAGES", 2)
        result, tree = hugging_face_scan(3)

        assert len(tree.asked) == 2
        assert [len(group.files) for group in result.groups] == [2]
        assert result.truncated, (
            "the repository was listed to its second page of three, and the listing did not say it was cut short"
        )

    def test_a_listing_as_long_as_its_pages_is_whole(self, monkeypatch):
        from utk_curio.backend.app.discovery.providers import huggingface

        monkeypatch.setattr(huggingface, "MAX_PAGES", 3)
        result, tree = hugging_face_scan(3)

        assert len(tree.asked) == 3
        assert [len(group.files) for group in result.groups] == [3]
        assert not result.truncated

    def test_a_listing_whose_next_page_is_on_another_site_says_it_stopped_and_why(self):
        from utk_curio.backend.app.discovery.application import scan

        # Three pages, and the second names the third on another site.
        result, tree = hugging_face_scan(3, elsewhere=1)

        # The page on the other site is never asked for.
        assert len(tree.asked) == 2 and all(url.startswith(tree.base + "/") for url in tree.asked)
        assert [len(group.files) for group in result.groups] == [2]
        assert result.truncated, (
            "the repository was listed to its second page of three, whose next page is on another site, "
            "and the listing did not say it stopped"
        )
        assert scan.cut_short_text(result.stopped_at) == (
            "This source holds more files than are listed here: a listing stops after 2 pages, "
            "because its next page is not at the source's address."
        )

    def test_an_add_from_a_listing_that_stopped_there_is_refused_and_says_why(self, app):
        from utk_curio.backend.app.discovery.domain.errors import DownloadTooLarge
        from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
        from utk_curio.backend.app.discovery.providers.huggingface import HuggingFaceStorage
        from utk_curio.backend.tests.test_discovery.test_listing_by_folder import an_add

        manifest = load_source_manifest(REPO / "discovery" / HF)
        tree = TreePages(manifest.provider.base_url, 3, elsewhere=1)
        with pytest.raises(DownloadTooLarge) as refused:
            an_add(HuggingFaceStorage(manifest, tree)).acquire(manifest, "task-images")

        assert str(refused.value) == (
            "Transformers task images has a listing that stops after 2 pages, "
            "because its next page is not at the source's address"
        )


class TestMediaDirectories:
    def test_without_isolation_they_are_in_the_users_store(self, app, monkeypatch):
        from utk_curio.backend.app.common.user_storage import users_base
        from utk_curio.backend.app.discovery.infrastructure import media_dirs

        monkeypatch.setenv("CURIO_ISOLATION", "off")
        assert media_dirs.media_work_root("1") == users_base() / "1" / "media"

    def test_under_isolation_they_are_in_the_users_exec_scratch(self, app, monkeypatch, tmp_path):
        from utk_curio.backend.app.discovery.infrastructure import media_dirs

        monkeypatch.setenv("CURIO_ISOLATION", "fork")
        monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / ".curio" / "data"))
        root = media_dirs.media_work_root("1")
        assert root == tmp_path / ".curio" / "exec-scratch" / "users" / "1" / "media"
