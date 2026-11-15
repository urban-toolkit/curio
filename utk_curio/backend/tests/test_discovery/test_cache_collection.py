"""Cache files on a bucket built here: what a cache reads from the files it
copies, and what keeps two caches from colliding.

No socket opens: the bucket is a recorded corpus, as in
``test_storage_buckets.py``, and the files are the example storage's own clip
and recording.
"""

from __future__ import annotations

import json
import os
import stat
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pytest

from utk_curio.backend.tests.test_discovery.conftest import write_source

REPO = Path(__file__).resolve().parents[4]
STORAGE = REPO / "docs" / "examples" / "data" / "storage"
CLIP = STORAGE / "survey" / "2025" / "clip_01.mp4"
RECORDING = STORAGE / "noise" / "sensor_01" / "20240501_060000.wav"

BUCKET = "https://walks.example"
SOURCE = "source.example.walks@1"
#: Two walks, named by when each began, in the order the index lists them.
WALKS = ("data/walks/20240501_090000.mp4", "data/walks/20240501_093000.mp4")
SOUND = "data/sounds/20240501_060000.wav"
TELEMETRY = (
    "file_name,lat,lon\n"
    "20240501_090000.mp4,41.8826,-87.6233\n"
    "20240501_093000.mp4,41.8790,-87.6359\n"
)


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


def _xml(keys):
    contents = "".join(
        f"<Contents><Key>{key}</Key><Size>{size}</Size>"
        f"<LastModified>2024-05-01T00:00:00.000Z</LastModified><ETag>\"e{i}\"</ETag></Contents>"
        for i, (key, size) in enumerate(keys)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<IsTruncated>false</IsTruncated>{contents}</ListBucketResult>"
    )


@pytest.fixture()
def walks_bucket(tmp_path, monkeypatch, discovery_dir):
    """Two walks, a telemetry table placing each, and a recording."""
    from utk_curio.backend.app.discovery.application import scan
    from utk_curio.backend.app.discovery.infrastructure import transport

    clip, recording = CLIP.read_bytes(), RECORDING.read_bytes()
    root = tmp_path / "corpus"
    files = root / "bucket"
    files.mkdir(parents=True)
    index = {}

    def listing(prefix, keys):
        name = prefix.strip("/").replace("/", "_") + ".xml"
        (files / name).write_text(_xml(keys), encoding="utf-8")
        index[f"{BUCKET}/?list-type=2&max-keys=1000&prefix={quote(prefix, safe='')}"] = {"file": f"bucket/{name}"}

    def body(key, data):
        name = key.replace("/", "_")
        (files / name).write_bytes(data)
        index[f"{BUCKET}/{key}"] = {"file": f"bucket/{name}"}

    listing("data/walks/", [(WALKS[0], len(clip)), (WALKS[1], len(clip)),
                            ("data/walks/telemetry.csv", len(TELEMETRY))])
    listing("data/sounds/", [(SOUND, len(recording))])
    for key in WALKS:
        body(key, clip)
    body("data/walks/telemetry.csv", TELEMETRY.encode("utf-8"))
    body(SOUND, recording)
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setenv(transport.ENV_FIXTURES, str(root))
    monkeypatch.setenv("CURIO_TESTING", "1")
    monkeypatch.delenv("CURIO_MEDIA_CACHE_MAX_GB", raising=False)
    write_source(discovery_dir, SOURCE, {
        "id": "source.example.walks", "name": "Walks", "version": "1.0.0",
        "compatibility": {"major": 1},
        "provider": {"type": "s3", "baseUrl": BUCKET, "options": {"prefix": "data/"}},
        "auth": {"mode": "public"},
        "resources": [
            {"id": "walks", "name": "Walks", "kind": "videos", "time": "began",
             "path": "walks/{began:%Y%m%d_%H%M%S}.mp4",
             "metadata": {"path": "walks/telemetry.csv", "on": "file_name"}},
            {"id": "sounds", "name": "Sounds", "kind": "audio", "time": "recorded",
             "path": "sounds/{recorded:%Y%m%d_%H%M%S}.wav"},
        ],
    })
    scan.listings.reset()
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


def _add(client, auth, resource_id):
    res = client.post(f"/api/discovery/sources/{SOURCE}/resources/{resource_id}/acquire", headers=auth, json={})
    assert res.status_code == 202, res.get_data(as_text=True)
    job = _wait(client, auth, res.get_json()["jobId"])
    assert job["status"] == "completed", job.get("error")
    return job["dataset"]


def _cache(client, auth, dataset_id):
    res = client.post(f"/api/discovery/collections/{dataset_id}/cache", headers=auth)
    assert res.status_code == 202, res.get_data(as_text=True)
    return res.get_json()


def _status(client, auth, dataset_id):
    return client.get(f"/api/discovery/collections/{dataset_id}", headers=auth).get_json()


class _Hold:
    """Holds the bucket's answer for one key until :attr:`go` is set, and
    counts how often each URL was asked for."""

    def __init__(self, monkeypatch, key):
        from utk_curio.backend.app.discovery.infrastructure import transport

        self.reached, self.go = threading.Event(), threading.Event()
        self.asked: dict[str, int] = {}
        real = transport.FixtureDiscoveryTransport.download
        hold = self

        def download(self_, url, sink, **kwargs):
            hold.asked[url] = hold.asked.get(url, 0) + 1
            if url == f"{BUCKET}/{key}" and not hold.go.is_set():
                hold.reached.set()
                hold.go.wait(timeout=30)
            return real(self_, url, sink, **kwargs)

        monkeypatch.setattr(transport.FixtureDiscoveryTransport, "download", download)


# ── what a cache reads from the files it copies ─────────────────────────────


class TestACachedFileIsRead:
    def test_a_walk_gets_the_details_its_file_holds(self, client, auth, app, walks_bucket):
        import geopandas as gpd

        dataset = _add(client, auth, "walks")
        # A bucket's videos are listed by path and size alone.
        assert "duration_s" not in gpd.read_parquet(dataset["path"]).columns

        done = _wait(client, auth, _cache(client, auth, dataset["id"])["jobId"])

        assert done["status"] == "completed", done.get("error")
        index = gpd.read_parquet(dataset["path"])
        assert "duration_s" in index.columns, list(index.columns)
        rows = index.set_index("name")
        for name in ("20240501_090000.mp4", "20240501_093000.mp4"):
            assert rows.loc[name, "duration_s"] == pytest.approx(1.0)
            assert rows.loc[name, "codec"] == "h264"
            assert rows.loc[name, "width"] > 0 and rows.loc[name, "height"] > 0 and rows.loc[name, "fps"] > 0
        # The time its path gave stays, and so do the positions its telemetry gave.
        assert str(rows.loc["20240501_090000.mp4", "taken_at"]) == "2024-05-01 09:00:00"
        assert index.geometry.notna().all() and index.crs.to_epsg() == 4326
        # The new columns come before those that say where a file is, as in a folder's index.
        assert list(index.columns)[-4:] == ["bytes", "mtime", "probe_error", "geometry"]

    def test_a_recording_gets_its_duration_and_sample_rate(self, client, auth, app, walks_bucket):
        import pandas as pd

        dataset = _add(client, auth, "sounds")

        done = _wait(client, auth, _cache(client, auth, dataset["id"])["jobId"])

        assert done["status"] == "completed", done.get("error")
        index = pd.read_parquet(dataset["path"])
        assert {"duration_s", "sample_rate", "channels"} <= set(index.columns), list(index.columns)
        row = index.iloc[0]
        assert row["sample_rate"] == 8000 and row["channels"] >= 1 and row["duration_s"] > 0
        assert str(row["recorded_at"]) == "2024-05-01 06:00:00"
        # Its details say how long the recordings run, as a folder's do.
        item = client.get(f"/api/datasets/{dataset['id']}", headers=auth).get_json()
        assert item["collection"].get("totalSeconds") == pytest.approx(row["duration_s"]), item["collection"]

    def test_a_walk_cached_before_is_read_by_the_next_cache(self, client, auth, app, walks_bucket, user_and_token):
        import pandas as pd

        from utk_curio.backend.app.discovery.application import cache_collection

        user, _token = user_and_token
        dataset = _add(client, auth, "walks")
        first = pd.read_parquet(dataset["path"]).iloc[0]
        # As a cache before this change left it: copied, its row never read.
        folder = cache_collection.objects_dir(str(user.id), dataset["id"])
        (folder / cache_collection.cached_name(first["file_id"], first["ext"])).write_bytes(CLIP.read_bytes())

        done = _wait(client, auth, _cache(client, auth, dataset["id"])["jobId"])

        assert done["status"] == "completed" and done["itemsDone"] == 1, done
        index = pd.read_parquet(dataset["path"])
        assert "duration_s" in index.columns and index["duration_s"].notna().all(), index.to_dict("records")

    def test_details_fill_only_what_the_index_lacks(self, tmp_path):
        import geopandas as gpd
        from shapely.geometry import Point

        from utk_curio.backend.app.discovery.application import cache_collection

        path = tmp_path / "index.parquet"
        gpd.GeoDataFrame(
            {
                "file_id": ["a" * 16, "b" * 16], "relpath": ["w/a.mp4", "w/b.mp4"],
                "name": ["a.mp4", "b.mp4"], "ext": ["mp4", "mp4"], "kind": ["video", "video"],
                "taken_at": [datetime(2024, 5, 1, 9), None],
                "bytes": [1, 2], "mtime": [datetime(2024, 5, 1), datetime(2024, 5, 1)],
                "probe_error": [None, None],
            },
            geometry=[Point(-87.62, 41.88), Point(-87.63, 41.87)], crs=4326,
        ).to_parquet(path)
        os.chmod(path, 0o640)

        cache_collection.record_details(str(path), {
            "a" * 16: {"duration_s": 2.5, "codec": "h264", "taken_at": datetime(1999, 1, 1)},
            "b" * 16: {"duration_s": 1.0, "taken_at": datetime(2000, 1, 1)},
        })

        frame = gpd.read_parquet(path)
        index = frame.set_index("name")
        # A time the index has stays; only an empty one is filled.
        assert str(index.loc["a.mp4", "taken_at"]) == "2024-05-01 09:00:00"
        assert str(index.loc["b.mp4", "taken_at"]) == "2000-01-01 00:00:00"
        assert list(index["duration_s"]) == [2.5, 1.0]
        assert index.loc["a.mp4", "codec"] == "h264" and index["codec"].isna().sum() == 1
        assert frame.crs.to_epsg() == 4326 and frame.geometry.notna().all()
        assert list(frame.columns) == [
            "file_id", "relpath", "name", "ext", "kind", "taken_at", "duration_s", "codec",
            "bytes", "mtime", "probe_error", "geometry",
        ]
        # Replaced with its mode, so whoever read the old index reads the new one.
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o640


# ── two caches ──────────────────────────────────────────────────────────────


class TestOneCacheAtATime:
    def test_asked_again_while_it_runs_a_cache_answers_with_its_job(
        self, client, auth, app, walks_bucket, monkeypatch
    ):
        dataset = _add(client, auth, "walks")
        hold = _Hold(monkeypatch, WALKS[0])
        try:
            first = _cache(client, auth, dataset["id"])
            assert hold.reached.wait(10), "the cache never asked for the first walk"
            # A page opened now, as after a reload, finds the cache that runs.
            running = _status(client, auth, dataset["id"]).get("cacheJob") or {}
            assert running.get("jobId") == first["jobId"], running
            assert running.get("status") == "running", running
            again = _cache(client, auth, dataset["id"])
            assert again["jobId"] == first["jobId"], (first, again)
        finally:
            hold.go.set()

        done = _wait(client, auth, first["jobId"])

        assert done["status"] == "completed", done.get("error")
        # One cache ran: each walk was fetched once.
        assert [hold.asked.get(f"{BUCKET}/{key}") for key in WALKS] == [1, 1], hold.asked
        status = _status(client, auth, dataset["id"])
        assert status["cacheJob"] is None and status["cachedFiles"] == 2, status

    def test_two_caches_at_once_cannot_pass_the_accounts_limit(
        self, client, auth, app, walks_bucket, monkeypatch, user_and_token
    ):
        from utk_curio.backend.app.discovery.application import cache_collection

        user, _token = user_and_token
        walks, sounds = _add(client, auth, "walks"), _add(client, auth, "sounds")
        walks_bytes, sound_bytes = 2 * CLIP.stat().st_size, RECORDING.stat().st_size
        held = cache_collection.used_bytes(str(user.id))
        room = held + max(walks_bytes, sound_bytes) + min(walks_bytes, sound_bytes) // 2
        monkeypatch.setenv("CURIO_MEDIA_CACHE_MAX_GB", repr(room / 1024**3))
        # Either collection fits alone; both together do not.
        cap = cache_collection.cap_bytes()
        assert held + max(walks_bytes, sound_bytes) <= cap < held + walks_bytes + sound_bytes
        hold = _Hold(monkeypatch, WALKS[0])
        try:
            first = _cache(client, auth, walks["id"])
            assert hold.reached.wait(10), "the walks' cache never asked for its first file"
            second = _wait(client, auth, _cache(client, auth, sounds["id"])["jobId"])
        finally:
            hold.go.set()

        # The walks' cache had fetched nothing yet, and still held its room.
        assert second["status"] == "failed", second
        assert "CURIO_MEDIA_CACHE_MAX_GB" in second["error"], second["error"]
        done = _wait(client, auth, first["jobId"])
        assert done["status"] == "completed", done.get("error")


# ── one file, one writer ────────────────────────────────────────────────────


class _Bucket:
    """A bucket whose every file is the same few bytes. *before(relpath)* runs
    as each fetch begins."""

    type = "s3"

    def __init__(self, before=None, data=b"walk"):
        self.before, self.data = before, data

    def local_path(self, relpath):
        return None

    def stream(self, relpath, sink, *, max_bytes, ceiling, progress=None):
        if self.before is not None:
            self.before(relpath)
        sink(self.data)


def _index(folder: Path, relpaths) -> dict:
    """A collection of *relpaths*, as its Data Catalog entry names it."""
    import pandas as pd

    from utk_curio.backend.app.discovery.application.index_collection import file_id

    rows = [
        {"file_id": file_id(relpath), "relpath": relpath, "name": relpath.rsplit("/", 1)[-1],
         "ext": "mp4", "kind": "video", "bytes": len(b"walk")}
        for relpath in relpaths
    ]
    path = folder / "index.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return {"id": f"imported.x{uuid.uuid4().hex[:12]}", "path": str(path)}


class TestOneWriterPerFile:
    def test_a_second_cache_of_a_collection_is_refused_while_the_first_runs(self, app, tmp_path):
        from utk_curio.backend.app.discovery.application import cache_collection

        dataset = _index(tmp_path, ["walks/a.mp4", "walks/b.mp4"])
        reached, go = threading.Event(), threading.Event()

        def hold(_relpath):
            reached.set()
            go.wait(timeout=30)

        failures: list[BaseException] = []

        def first():
            try:
                cache_collection.cache("9", dataset, _Bucket(before=hold))
            except Exception as exc:  # noqa: BLE001 - reported below
                failures.append(exc)

        worker = threading.Thread(target=first, daemon=True)
        worker.start()
        try:
            assert reached.wait(10), "the first cache never began a fetch"
            with pytest.raises(cache_collection.CacheRunning):
                cache_collection.cache("9", dataset, _Bucket())
        finally:
            go.set()
            worker.join(timeout=30)
        assert not failures, failures
        assert cache_collection.cached_count("9", dataset["id"]) == (2, 8)

    def test_a_file_another_cache_is_writing_is_left_to_it(self, app, tmp_path):
        from utk_curio.backend.app.discovery.application import cache_collection
        from utk_curio.backend.app.discovery.application.index_collection import file_id

        dataset = _index(tmp_path, ["walks/a.mp4", "walks/b.mp4"])
        folder = cache_collection.objects_dir("9", dataset["id"])
        theirs = folder / (cache_collection.cached_name(file_id("walks/b.mp4"), "mp4") + ".part")

        def another_process_begins_b(relpath):
            # As a cache in another process would, while this one fetches a.mp4.
            if relpath == "walks/a.mp4":
                theirs.write_bytes(b"theirs")

        with pytest.raises(cache_collection.CacheRunning, match="walks/b.mp4"):
            cache_collection.cache("9", dataset, _Bucket(before=another_process_begins_b))

        assert theirs.read_bytes() == b"theirs"

    def test_a_cache_in_another_process_waits_for_the_running_one_and_fetches_nothing_again(
        self, app, tmp_path, monkeypatch
    ):
        """Each process kept its own running caches, so a cache another
        backend process ran did not hold this one back: it dropped the other
        cache's half-fetched file, fetched every file again, and the other
        cache then failed to put its file in place. The other process is a
        forked child (``_support/two_processes.py``)."""
        from utk_curio.backend.app.discovery.application import cache_collection
        from utk_curio.backend.tests._support.two_processes import Window, race

        dataset = _index(tmp_path, ["walks/a.mp4", "walks/b.mp4"])
        window = Window()
        fetched_here: list[str] = []

        def first_fetch_stops(relpath):
            if relpath == "walks/a.mp4":
                window.stop_here()

        raced = race(
            window,
            lambda: cache_collection.cache("9", dataset, _Bucket(before=first_fetch_stops)),
            lambda: cache_collection.cache("9", dataset, _Bucket(before=fetched_here.append)),
            monkeypatch,
        )

        assert raced.child_exit == 0, f"the cache in the other process failed: {raced.child_error}"
        assert fetched_here == [], f"this process fetched again what the other was caching: {fetched_here}"
        assert raced.here["cached"] == 0, raced.here
        assert cache_collection.cached_count("9", dataset["id"]) == (2, 8)


# ── the account's cap, across processes ────────────────────────────────────


def _cache_or_refusal(dataset):
    """Cache *dataset* for account 9 here; what the cache returned, or the
    refusal it raised."""
    from utk_curio.backend.app.discovery.application import cache_collection
    from utk_curio.backend.app.discovery.domain.errors import DownloadTooLarge

    try:
        return cache_collection.cache("9", dataset, _Bucket())
    except DownloadTooLarge as refused:
        return refused


def _two_collections_past_a_cap(tmp_path, monkeypatch) -> tuple[dict, dict]:
    """Two collections of two 4-byte files each, under a 12-byte cap: either
    fits alone, both together do not."""
    from utk_curio.backend.app.discovery.application import cache_collection

    (tmp_path / "theirs").mkdir()
    (tmp_path / "ours").mkdir()
    theirs = _index(tmp_path / "theirs", ["walks/a.mp4", "walks/b.mp4"])
    ours = _index(tmp_path / "ours", ["walks/c.mp4", "walks/d.mp4"])
    monkeypatch.setenv(cache_collection.ENV_CAP, repr(12 / 1024**3))
    assert cache_collection.cap_bytes() == 12
    return theirs, ours


class TestTheCapAcrossProcesses:
    def test_another_processes_cache_holds_its_room_while_it_runs_and_none_once_it_died(
        self, app, tmp_path, monkeypatch
    ):
        """Each process counted only its own running caches against the
        account's cap, so a cache here passed it while a cache in another
        backend process still had its files to fetch. That process then
        dies in its fetch, and the room it held is free again. The other
        process is a forked child (``_support/two_processes.py``)."""
        from utk_curio.backend.app.discovery.application import cache_collection
        from utk_curio.backend.app.discovery.domain.errors import DownloadTooLarge
        from utk_curio.backend.tests._support.two_processes import Window, race

        theirs, ours = _two_collections_past_a_cap(tmp_path, monkeypatch)
        window = Window()
        test_process = os.getpid()

        def dies_in_its_first_fetch(_relpath):
            window.stop_here()
            if os.getpid() != test_process:
                os._exit(9)  # as a crash would: nothing after it runs

        raced = race(
            window,
            lambda: cache_collection.cache("9", theirs, _Bucket(before=dies_in_its_first_fetch)),
            lambda: _cache_or_refusal(ours),
            monkeypatch,
        )

        assert isinstance(raced.here, DownloadTooLarge), (
            f"this process cached its 8 bytes ({raced.here}) while another process's cache had 8 more "
            "to fetch: together past the account's 12-byte cap"
        )
        assert cache_collection.ENV_CAP in str(raced.here)
        assert raced.child_exit == 9, f"the other process did not end where it was made to: {raced.child_error}"
        again = _cache_or_refusal(ours)
        assert not isinstance(again, DownloadTooLarge), (
            f"the other process died, and its cache still held its room: {again}"
        )
        assert again["cached"] == 2, again
        assert cache_collection.used_bytes("9") == 8

    def test_an_owners_apply_copying_an_editors_cached_files_holds_their_room(self, app, tmp_path, monkeypatch):
        """An owner's Apply of an editor's collection copies his cached files
        into her media cache (``editor_requests._copy_cached_files``). It
        checked her cap but held no room while it copied, so a cache of hers
        that started meanwhile, here in another process, passed the cap with
        it. The copy is a forked child that stops after its first file."""
        import shutil
        import types

        from utk_curio.backend.app.datasets.application import editor_requests
        from utk_curio.backend.app.discovery.application import cache_collection
        from utk_curio.backend.app.discovery.domain.errors import DownloadTooLarge
        from utk_curio.backend.tests._support.two_processes import Window, race

        his, hers = _two_collections_past_a_cap(tmp_path, monkeypatch)
        for name in ("a.mp4", "b.mp4"):  # the editor's cached files
            (cache_collection.objects_dir("8", his["id"]) / name).write_bytes(b"walk")
        window = Window()

        def _copies_then_stops(source, part):
            copied = shutil.copyfile(source, part)
            window.stop_here()
            return copied

        monkeypatch.setattr(
            editor_requests, "shutil", types.SimpleNamespace(**{**vars(shutil), "copyfile": _copies_then_stops})
        )

        raced = race(
            window,
            lambda: editor_requests._copy_cached_files("8", "9", his["id"]),
            lambda: _cache_or_refusal(hers),
            monkeypatch,
        )

        assert isinstance(raced.here, DownloadTooLarge), (
            f"her cache ran ({raced.here}) while another process copied 8 bytes of the editor's files "
            "into her media cache: together past its 12-byte cap"
        )
        assert cache_collection.ENV_CAP in str(raced.here)
        assert raced.child_exit == 0, f"the copy in the other process failed: {raced.child_error}"
        assert cache_collection.cached_count("9", his["id"]) == (2, 8)
