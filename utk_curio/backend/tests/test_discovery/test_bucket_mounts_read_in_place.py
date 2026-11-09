"""A bucket this deployment mounts, read in place: its rows, previews, player,
node code and adds read its files through the mount, and Cache files copies
nothing of it.

The mount service is a fake rc client, as in ``test_bucket_mount_sources.py``,
whose ``mount/mount`` writes the bucket's files into
``<bucket-mounts-dir>/<sourceId>@<major>/``: a plain folder stands in for the
mount, and a fake of how folders look from Curio's container takes it for
one. The bucket's listing is a recorded corpus (``FixtureDiscoveryTransport``),
as in ``test_cache_collection.py``, and serves the body of no file but one
photo: a video, a recording, a table or a record read over HTTP would fail,
so whatever reads one here read it from the mount. No socket opens.

New names are imported inside the tests, so a checkout without them fails
each test on its own.
"""

from __future__ import annotations

import io
import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import pytest

from utk_curio.backend.app.discovery.infrastructure import bucket_mounts as bm
from utk_curio.backend.tests.test_discovery.conftest import SHIPPED_ROOT, write_source
from utk_curio.backend.tests.test_discovery.test_bucket_mount_sources import Clock, a_manifest, canonical

REPO = Path(__file__).resolve().parents[4]
STORAGE = REPO / "docs" / "examples" / "data" / "storage"

HOST = "data.example.org"
#: The bucket ``walks``, path-style at https://data.example.org.
BASE = f"https://{HOST}/walks"
#: A source of its files under ``data/``, mounted at its folder.
SOURCE = "source.example.walks@1"
#: A source of its photos under ``data/photos/IMG_``: the mount shows
#: ``data/photos/``, and each file's path there starts with ``IMG_``.
NUMBERED = "source.example.numbered@1"
#: A bucket that does not mount (no dot in its endpoint's host), read over
#: HTTP and cached as before.
ELSEWHERE = "source.example.elsewhere@1"
ELSEWHERE_BASE = "https://walks.example"
HF = "source.huggingface.documentation-images@1"

WALKS = ("walks/20240501_090000.mp4", "walks/20240501_093000.mp4")
TELEMETRY = (
    "file_name,lat,lon\n"
    "20240501_090000.mp4,41.8826,-87.6233\n"
    "20240501_093000.mp4,41.8790,-87.6359\n"
)
SOUND = "sounds/20240501_060000.wav"
PHOTO = "photos/IMG_0001.jpg"
WALK = "2026-10-26-16-03-17-016"
RECORDS = (f"records/{WALK}/metadata.json", f"records/{WALK}/anonymization.json")
STATIONS = "tables/stations.csv"
DOWN = "the mount service is down"


def _bytes(*parts: str) -> bytes:
    return STORAGE.joinpath(*parts).read_bytes()


def bucket_files() -> dict[str, bytes]:
    """The bucket's files under ``data/``, by their path there."""
    clip = _bytes("survey", "2025", "clip_01.mp4")
    return {
        WALKS[0]: clip,
        WALKS[1]: clip,
        "walks/telemetry.csv": TELEMETRY.encode("utf-8"),
        SOUND: _bytes("noise", "sensor_01", "20240501_060000.wav"),
        PHOTO: _bytes("survey", "2024", "IMG_0001.jpg"),
        RECORDS[0]: json.dumps({"time": {"mediaStartDateTime": "2026-10-26T21:03:17.376Z"}}).encode("utf-8"),
        RECORDS[1]: json.dumps({"capture": WALK, "method": "egoblur"}).encode("utf-8"),
        STATIONS: _bytes("air-quality", "stations.csv"),
    }


def resolver(host):
    if host == HOST:
        return ["93.184.216.34"]
    raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")


# ── The mount service, on plain folders ─────────────────────────────────────


class FakeRclone:
    """The mount service as the backend calls it. ``mount/mount`` writes the
    files its bucket holds into the mount's folder, as rclone would show
    them; a file in *later* was uploaded after rclone last listed its folder,
    and shows once that listing is forgotten or read again. *unreachable*
    makes every call find no service."""

    socket_path = "/run/curio-bucket-mounts/rc.sock"

    def __init__(self, mounts_dir: Path, files: dict[str, dict[str, bytes]]):
        self.mounts_dir = mounts_dir
        self.files = files
        self.later: dict[str, dict[str, bytes]] = {}
        self.calls: list = []
        self.mounts: dict[str, str] = {}
        self.unreachable = False

    def call(self, method, params=None, *, timeout=None):
        params = dict(params or {})
        self.calls.append((method, params))
        if self.unreachable:
            raise bm.RcError("unreachable",
                             f"nothing answers on the mount service's socket {self.socket_path}: No such file or directory")
        if method == "mount/listmounts":
            return {"mountPoints": [{"Fs": canonical(fs), "MountPoint": point} for point, fs in sorted(self.mounts.items())]}
        if method == "operations/mkdir":
            (self.mounts_dir / params["remote"]).mkdir(parents=True, exist_ok=True)
        elif method == "mount/mount":
            self.mounts[params["mountPoint"]] = params["fs"]
            name = params["mountPoint"].rsplit("/", 1)[-1]
            for path, data in self.files.get(name, {}).items():
                self._write(name, path, data)
        elif method == "mount/unmount":
            self.mounts.pop(params["mountPoint"], None)
        elif method in ("vfs/forget", "vfs/refresh"):
            return self._listings(method, params)
        return {}

    def _listings(self, method, params):
        name = next((point.rsplit("/", 1)[-1] for point, fs in self.mounts.items() if canonical(fs) == params["fs"]),
                    None)
        if name is None:
            raise bm.RcError("refused", f"the mount service refused {method}: no VFS found with name {params['fs']!r}")
        dirs = [value for key, value in params.items() if key.startswith("dir")]
        files = [value for key, value in params.items() if key.startswith("file")]
        listed = set(dirs) | {path.rpartition("/")[0] for path in files}
        if method == "vfs/refresh" and not dirs:
            listed.add("")
        waiting = self.later.get(name, {})
        for path in [path for path in waiting if path.rpartition("/")[0] in listed]:
            self._write(name, path, waiting.pop(path))
        if method == "vfs/forget":
            return {"forgotten": files + dirs}
        return {"result": {folder: "OK" for folder in dirs} or {"": "OK"}}

    def _write(self, name, path, data):
        target = self.mounts_dir / name / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def methods(self):
        return [method for method, _ in self.calls]

    def made(self, method, listed):
        """The parameters of each *method* call on the mount *listed* names."""
        return [params for name, params in self.calls if name == method and params.get("fs") == listed]


class PlainFolders:
    """How the service's folders look from Curio's container: a plain folder
    is mounted while the service holds its mount, and dead once marked so."""

    def __init__(self, service: FakeRclone):
        self.service = service
        self.dead: set[str] = set()

    def _held(self, folder: Path) -> bool:
        return f"{bm.SERVICE_MOUNTS}/{folder.name}" in self.service.mounts

    def look(self, folder: Path) -> str:
        if not self._held(folder):
            return "absent"
        return "dead" if folder.name in self.dead else "mounted"

    def list(self, folder: Path) -> bool:
        if not self._held(folder):
            return False
        os.listdir(folder)
        return True


@dataclass
class Rig:
    service: FakeRclone
    folders: PlainFolders
    clock: Clock
    mounts_dir: Path
    catalog: Path
    corpus: Path

    def folder(self, source: str = SOURCE) -> Path:
        return self.mounts_dir / source

    def manifest(self, source: str = SOURCE):
        from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest_from_dir

        return load_source_manifest_from_dir(self.catalog / source)

    def listed(self, source: str = SOURCE) -> str:
        """What rclone names the source's mount by, and its vfs/ calls take."""
        from utk_curio.backend.app.discovery.application.bucket_mount_sources import listed_fs_of
        from utk_curio.backend.app.discovery.domain.bucket_mount import bucket_mount

        return listed_fs_of(bucket_mount(self.manifest(source)))

    def storage(self, source: str = SOURCE, **kwargs):
        from utk_curio.backend.app.discovery.infrastructure.transport import FixtureDiscoveryTransport
        from utk_curio.backend.app.discovery.providers.s3 import S3Storage

        return S3Storage(self.manifest(source), FixtureDiscoveryTransport(self.corpus), **kwargs)

    def down(self) -> None:
        """The service stops: every call finds no service, and its mounts are
        dead in Curio's container once they are looked at again."""
        from utk_curio.backend.app.discovery.application import bucket_mount_sources

        self.service.unreachable = True
        self.folders.dead.update(point.rsplit("/", 1)[-1] for point in self.service.mounts)
        self.clock.now += bucket_mount_sources.LOOK_SECONDS + 1


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


def _write_corpus(root: Path, files: dict[str, bytes]) -> None:
    """The bucket's listings, its one photo's body, and the bucket that does
    not mount, listed and read as before."""
    stored = root / "bucket"
    stored.mkdir(parents=True)
    index = {}

    def listing(base, prefix, keys):
        name = f"{len(index)}.xml"
        (stored / name).write_text(_xml(keys), encoding="utf-8")
        index[f"{base}/?list-type=2&max-keys=1000&prefix={quote(prefix, safe='')}"] = {"file": f"bucket/{name}"}

    def body(url, data):
        name = f"{len(index)}.bin"
        (stored / name).write_bytes(data)
        index[url] = {"file": f"bucket/{name}"}

    keys = sorted((f"data/{path}", len(data)) for path, data in files.items())
    listing(BASE, "data/", keys)
    for folder in ("walks", "sounds", "photos", "records", "tables"):
        listing(BASE, f"data/{folder}/", [key for key in keys if key[0].startswith(f"data/{folder}/")])
    listing(BASE, "data/photos/IMG_", [key for key in keys if key[0].startswith("data/photos/IMG_")])
    # The one file the bucket serves over HTTP: a photo, drawn while the mount is down.
    body(f"{BASE}/data/{PHOTO}", files[PHOTO])
    listing(ELSEWHERE_BASE, "data/sounds/", [(f"data/{SOUND}", len(files[SOUND]))])
    body(f"{ELSEWHERE_BASE}/data/{SOUND}", files[SOUND])
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")


def _write_sources(root: Path) -> None:
    common = {"version": "1.0.0", "compatibility": {"major": 1}, "auth": {"mode": "public"}}
    sounds = {"id": "sounds", "name": "Sounds", "kind": "audio", "time": "recorded",
              "path": "sounds/{recorded:%Y%m%d_%H%M%S}.wav"}
    write_source(root, SOURCE, {
        **common, "id": "source.example.walks", "name": "Walks",
        "provider": {"type": "s3", "baseUrl": BASE, "options": {"prefix": "data/"}},
        "resources": [
            {"id": "walks", "name": "Walks", "kind": "videos", "time": "began",
             "path": "walks/{began:%Y%m%d_%H%M%S}.mp4",
             "metadata": {"path": "walks/telemetry.csv", "on": "file_name"}},
            sounds,
            {"id": "photos", "name": "Photos", "kind": "images", "path": "photos/{photo}.jpg"},
            {"id": "records", "name": "Walk records", "kind": "files", "path": "records/{walk}/{record}.json"},
            {"id": "stations", "name": "Stations", "kind": "table", "format": "csv", "path": STATIONS},
        ],
    })
    write_source(root, NUMBERED, {
        **common, "id": "source.example.numbered", "name": "Numbered photos",
        "provider": {"type": "s3", "baseUrl": BASE, "options": {"prefix": "data/photos/IMG_"}},
        "resources": [{"id": "numbered", "name": "Numbered photos", "kind": "images", "path": "{number}.jpg"}],
    })
    write_source(root, ELSEWHERE, {
        **common, "id": "source.example.elsewhere", "name": "Elsewhere",
        "provider": {"type": "s3", "baseUrl": ELSEWHERE_BASE, "options": {"prefix": "data/"}},
        "resources": [sounds],
    })


@pytest.fixture()
def rig(tmp_path, monkeypatch, discovery_dir):
    """A deployment that mounts buckets, its service's fake, and the bucket."""
    from utk_curio.backend.app.discovery.application import bucket_mount_check, media, scan
    from utk_curio.backend.app.discovery.application import bucket_mount_sources as sources_module
    from utk_curio.backend.app.discovery.infrastructure import transport
    from utk_curio.backend.app.discovery.infrastructure.mount_proxy import MountProxy
    from utk_curio.backend.app.monitor import errors

    files = bucket_files()
    corpus = tmp_path / "corpus"
    _write_corpus(corpus, files)
    monkeypatch.setenv(transport.ENV_FIXTURES, str(corpus))
    monkeypatch.setenv("CURIO_TESTING", "1")
    monkeypatch.delenv("CURIO_MEDIA_CACHE_MAX_GB", raising=False)
    _write_sources(discovery_dir)

    mounts_dir = tmp_path / "bucket-mounts"
    mounts_dir.mkdir()
    monkeypatch.setenv(bm.DIR_VARIABLE, str(mounts_dir))
    monkeypatch.setenv(bm.SOCKET_VARIABLE, FakeRclone.socket_path)
    service = FakeRclone(mounts_dir, {SOURCE: files, NUMBERED: {"IMG_0001.jpg": files[PHOTO]}})
    folders = PlainFolders(service)
    clock = Clock()
    the_sources = sources_module.BucketMountSources(
        service, mounts_dir, proxy=MountProxy(), folders=folders, resolver=resolver, clock=clock,
    )
    errors.reset()
    bucket_mount_check.reset()
    sources_module.reset()
    monkeypatch.setattr(sources_module, "sources", lambda: the_sources)
    scan.listings.reset()
    media.index_cache._rows.clear()
    yield Rig(service, folders, clock, mounts_dir, discovery_dir, corpus)
    scan.listings.reset()
    media.index_cache._rows.clear()
    sources_module.reset()
    bucket_mount_check.reset()
    errors.reset()


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


def _wait(client, auth, job_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/discovery/jobs/{job_id}", headers=auth).get_json()
        if body["status"] in ("completed", "failed", "refused", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def _add_job(client, auth, source, resource_id):
    res = client.post(f"/api/discovery/sources/{source}/resources/{quote(resource_id, safe='')}/acquire",
                      headers=auth, json={})
    assert res.status_code == 202, res.get_data(as_text=True)
    return _wait(client, auth, res.get_json()["jobId"])


def _add(client, auth, source, resource_id):
    job = _add_job(client, auth, source, resource_id)
    assert job["status"] == "completed", job.get("error")
    return job["dataset"]


def _status(client, auth, dataset_id):
    res = client.get(f"/api/discovery/collections/{dataset_id}", headers=auth)
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def _media(client, auth, dataset_id, file_id, variant="thumb", **headers):
    return client.get(f"/api/datasets/{dataset_id}/media/{file_id}?variant={variant}", headers={**auth, **headers})


def _file_ids(dataset) -> dict[str, str]:
    import pandas as pd

    index = pd.read_parquet(dataset["path"], columns=["relpath", "file_id"])
    return dict(zip(index["relpath"], index["file_id"]))


def _node_collections(app, user, dataset):
    """What a run hands the sandbox for *dataset*, and its rows as
    ``curio_load_collection`` gives them there, or what it raises."""
    from utk_curio.backend.app.discovery.application.exec_collections import resolve_collections
    from utk_curio.backend.app.discovery.infrastructure import media_dirs
    from utk_curio.sandbox.util.collections import make_collection_helpers

    with app.test_request_context():
        collections = resolve_collections([dataset["id"]], str(user.id), user=user)
    helpers = make_collection_helpers(
        lambda _id: dataset["path"], collections, str(media_dirs.media_work_root(str(user.id))),
    )
    return collections[dataset["id"]], lambda: helpers["curio_load_collection"](dataset["id"])


def _objects(user) -> list[Path]:
    """What the account's media folder holds of cached bucket files."""
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    objects = media_dirs.media_work_root(str(user.id)) / "objects"
    return sorted(path for path in objects.rglob("*") if path.is_file()) if objects.exists() else []


# ── An add reads the mount ──────────────────────────────────────────────────


class TestAnAdd:
    def test_a_walks_details_are_read_from_its_file_after_its_folder_is_listed_again(
        self, client, auth, app, rig, monkeypatch,
    ):
        import geopandas as gpd

        from utk_curio.backend.app.discovery.application import probe

        real = probe.probe

        def probed(kind, path):
            rig.service.calls.append(("probe", {"path": str(path)}))
            return real(kind, path)

        monkeypatch.setattr(probe, "probe", probed)

        dataset = _add(client, auth, SOURCE, "walks")

        index = gpd.read_parquet(dataset["path"])
        rows = index.set_index("name")
        for name in ("20240501_090000.mp4", "20240501_093000.mp4"):
            assert rows.loc[name, "duration_s"] == pytest.approx(1.0)
            assert rows.loc[name, "codec"] == "h264"
            assert rows.loc[name, "width"] > 0 and rows.loc[name, "height"] > 0 and rows.loc[name, "fps"] > 0
        assert index["probe_error"].isna().all(), index["probe_error"].tolist()
        # Its telemetry table, read from the mount too, placed each walk.
        assert index.geometry.notna().all() and index.crs.to_epsg() == 4326
        # The walks' folder was listed again, with every listing above it,
        # before a file was read; each was read in the mount.
        listed = rig.listed()
        assert rig.service.made("vfs/forget", listed) == [{"fs": listed, "file": "walks"}]
        assert rig.service.made("vfs/refresh", listed) == [{"fs": listed, "dir": "walks"}]
        methods = rig.service.methods()
        assert methods.index("vfs/refresh") < methods.index("probe"), methods
        probed_paths = sorted(Path(params["path"]).resolve() for name, params in rig.service.calls if name == "probe")
        assert probed_paths == sorted((rig.folder() / path).resolve() for path in WALKS)

    def test_a_recordings_details_are_read_from_its_file(self, client, auth, app, rig):
        import pandas as pd

        dataset = _add(client, auth, SOURCE, "sounds")

        row = pd.read_parquet(dataset["path"]).iloc[0]
        assert row["sample_rate"] == 8000 and row["channels"] >= 1 and row["duration_s"] > 0
        assert str(row["recorded_at"]) == "2024-05-01 06:00:00"
        assert dataset["collection"].get("totalSeconds") == pytest.approx(row["duration_s"])

    def test_a_table_is_copied_from_the_mount_and_a_file_opens_there_within_its_limit(self, client, auth, app, rig):
        import pandas as pd

        from utk_curio.backend.app.discovery.application.bucket_mount_sources import BucketReads
        from utk_curio.backend.app.discovery.domain.errors import DownloadTooLarge

        dataset = _add(client, auth, SOURCE, "stations")

        added = pd.read_csv(dataset["path"])
        assert added.shape == pd.read_csv(io.BytesIO(bucket_files()[STATIONS])).shape
        storage = rig.storage(reads=BucketReads(rig.manifest()))
        with storage.open(STATIONS) as handle:
            assert handle.read() == bucket_files()[STATIONS]
        assert storage.open(WALKS[0], byte_range=(4, 12)).read() == bucket_files()[WALKS[0]][4:12]
        with pytest.raises(DownloadTooLarge):
            storage.open(WALKS[0], max_bytes=100)

    def test_a_prefix_that_ends_partway_through_a_name_joins_each_relpath_after_it(
        self, client, auth, app, rig, user_and_token,
    ):
        import pandas as pd

        user, _token = user_and_token
        dataset = _add(client, auth, NUMBERED, "numbered")

        row = pd.read_parquet(dataset["path"]).iloc[0]
        assert row["relpath"] == "0001.jpg"
        # Read from the mount: the corpus serves no part of it at that name.
        assert row["width"] > 0 and pd.isna(row["probe_error"]), row.to_dict()
        entry, load = _node_collections(app, user, dataset)
        assert entry == {"kind": "images", "root": str(rig.folder(NUMBERED)), "tail": "IMG_"}
        path = load()["path"].iloc[0]
        assert path == os.path.join(str(rig.folder(NUMBERED)), "IMG_0001.jpg")
        assert Path(path).read_bytes() == bucket_files()[PHOTO]
        # Its one folder is the mount's root, listed again with no folder named.
        listed = rig.listed(NUMBERED)
        assert rig.service.made("vfs/refresh", listed) == [{"fs": listed}]
        assert rig.service.made("vfs/forget", listed) == []


# ── Node code and Data Loading ──────────────────────────────────────────────


class TestNodeCode:
    def test_every_rows_path_is_its_file_in_the_mount(self, client, auth, app, rig, user_and_token):
        user, _token = user_and_token
        dataset = _add(client, auth, SOURCE, "walks")

        entry, load = _node_collections(app, user, dataset)

        assert entry == {"kind": "videos", "root": str(rig.folder()), "tail": ""}
        rows = load()
        assert sorted(rows["path"]) == sorted(os.path.join(str(rig.folder()), *path.split("/")) for path in WALKS)
        for path in rows["path"]:
            assert Path(path).read_bytes() == bucket_files()[WALKS[0]]

    def test_a_files_collection_reads_each_record_from_the_mount(self, client, auth, app, rig, user_and_token):
        user, _token = user_and_token
        dataset = _add(client, auth, SOURCE, "records")
        assert dataset["collection"]["counts"] == {"file": 2}

        _entry, load = _node_collections(app, user, dataset)

        rows = load()
        assert sorted(rows["path"]) == sorted(os.path.join(str(rig.folder()), *path.split("/")) for path in RECORDS)
        records = {row["record"]: json.loads(Path(row["path"]).read_text(encoding="utf-8"))
                   for _, row in rows.iterrows()}
        assert records["anonymization"]["capture"] == WALK
        status = _status(client, auth, dataset["id"])
        assert (status["readInPlace"], status["samples"]) == (True, [])


# ── Previews and the player ─────────────────────────────────────────────────


class TestMedia:
    def test_a_video_plays_from_the_mount_with_range(self, client, auth, app, rig):
        dataset = _add(client, auth, SOURCE, "walks")
        file_id = _file_ids(dataset)[WALKS[0]]
        clip = bucket_files()[WALKS[0]]

        part = _media(client, auth, dataset["id"], file_id, "original", Range="bytes=0-99")
        assert part.status_code == 206, part.get_data(as_text=True)
        assert (part.mimetype, part.data) == ("video/mp4", clip[:100])

        link = client.post(f"/api/datasets/{dataset['id']}/media/{file_id}/link", headers=auth)
        assert link.status_code == 200, link.get_data(as_text=True)
        seek = client.get(link.get_json()["url"], headers={"Range": f"bytes={len(clip) - 50}-"})
        assert seek.status_code == 206 and seek.data == clip[-50:]

    def test_a_videos_poster_and_a_recordings_spectrogram_need_no_cache(
        self, client, auth, app, rig, user_and_token,
    ):
        user, _token = user_and_token
        walks = _add(client, auth, SOURCE, "walks")
        sounds = _add(client, auth, SOURCE, "sounds")

        poster = _media(client, auth, walks["id"], _file_ids(walks)[WALKS[0]], "poster")
        spectrogram = _media(client, auth, sounds["id"], _file_ids(sounds)[SOUND], "thumb")

        assert poster.status_code == 200, poster.get_data(as_text=True)
        assert spectrogram.status_code == 200, spectrogram.get_data(as_text=True)
        assert poster.mimetype == spectrogram.mimetype == "image/jpeg"
        assert _objects(user) == []

    def test_a_source_pages_thumbnail_of_a_video_is_drawn_from_the_mount(self, client, auth, app, rig):
        for _ in range(100):
            body = client.get(f"/api/discovery/sources/{SOURCE}/search", headers=auth).get_json()
            if body["sources"][0]["status"] != "scanning":
                break
            time.sleep(0.05)

        res = client.get(f"/api/discovery/sources/{SOURCE}/thumbnails/0/walks", headers=auth)

        assert res.status_code == 200, res.get_data(as_text=True)
        assert res.mimetype == "image/jpeg"


# ── Cache files and the details ─────────────────────────────────────────────


class TestCacheFiles:
    def test_it_is_refused_and_the_details_say_the_files_are_read_in_place(
        self, client, auth, app, rig, user_and_token,
    ):
        from utk_curio.backend.app.discovery.application import cache_collection
        from utk_curio.backend.app.discovery.application.bucket_mount_sources import BucketReads
        from utk_curio.backend.app.discovery.domain.errors import CapabilityUnsupported

        user, _token = user_and_token
        dataset = _add(client, auth, SOURCE, "walks")

        status = _status(client, auth, dataset["id"])
        assert status["local"] is True and status["readInPlace"] is True, status
        assert (status["bucketHost"], status["mountProblem"]) == (HOST, None)
        assert status["cachedFiles"] == status["fileCount"] == 2
        res = client.post(f"/api/discovery/collections/{dataset['id']}/cache", headers=auth)
        assert res.status_code == 400, res.get_data(as_text=True)
        assert "is not cached: its files are read in place from the bucket" in res.get_json()["error"]
        # The cache itself refuses, whoever starts it.
        with pytest.raises(CapabilityUnsupported, match="read in place from the bucket"):
            cache_collection.cache(str(user.id), dataset, rig.storage(reads=BucketReads(rig.manifest())))
        assert _objects(user) == []

    def test_nothing_lands_in_the_accounts_media_objects(self, client, auth, app, rig, user_and_token):
        user, _token = user_and_token
        dataset = _add(client, auth, SOURCE, "walks")
        file_id = _file_ids(dataset)[WALKS[1]]

        assert _media(client, auth, dataset["id"], file_id, "original").status_code == 200
        assert _media(client, auth, dataset["id"], file_id, "poster").status_code == 200
        _entry, load = _node_collections(app, user, dataset)
        assert load()["path"].notna().all()

        assert _objects(user) == []
        from utk_curio.backend.app.discovery.infrastructure import media_dirs

        assert not (media_dirs.media_work_root(str(user.id)) / "objects").exists()


# ── A file uploaded since rclone listed its folder ──────────────────────────


class TestAMiss:
    def test_a_file_is_found_once_its_folders_listing_is_forgotten_and_looked_for_again_at_most_so_often(
        self, app, rig,
    ):
        from utk_curio.backend.app.discovery.application.bucket_mount_sources import FORGET_SECONDS, BucketReads

        late = rig.service.files[SOURCE].pop(WALKS[1])
        rig.service.later[SOURCE] = {WALKS[1]: late}
        storage = rig.storage(reads=BucketReads(rig.manifest()))
        listed = rig.listed()

        assert storage.local_path(WALKS[0]) == (rig.folder() / WALKS[0]).resolve()
        assert rig.service.made("vfs/forget", listed) == []
        assert storage.local_path(WALKS[1]) == (rig.folder() / WALKS[1]).resolve()
        assert rig.service.made("vfs/forget", listed) == [{"fs": listed, "dir": "walks"}]

        # A file the bucket does not hold: its folder is not listed again
        # until FORGET_SECONDS have passed.
        assert storage.local_path("walks/20240501_100000.mp4") is None
        assert len(rig.service.made("vfs/forget", listed)) == 1
        rig.clock.now += FORGET_SECONDS
        assert storage.local_path("walks/20240501_100000.mp4") is None
        assert len(rig.service.made("vfs/forget", listed)) == 2

    def test_a_file_at_the_mounts_root_marks_only_the_roots_listing_stale(self, app, rig):
        from utk_curio.backend.app.discovery.application.bucket_mount_sources import BucketReads

        rig.service.later[NUMBERED] = {"IMG_0002.jpg": bucket_files()[PHOTO]}
        storage = rig.storage(NUMBERED, reads=BucketReads(rig.manifest(NUMBERED)))
        listed = rig.listed(NUMBERED)

        assert storage.local_path("0002.jpg") == (rig.folder(NUMBERED) / "IMG_0002.jpg").resolve()
        assert rig.service.made("vfs/forget", listed) == [{"fs": listed, "file": "IMG_0002.jpg"}]


# ── The mount down ──────────────────────────────────────────────────────────


class TestTheMountDown:
    def test_an_add_fails_with_why(self, client, auth, app, rig):
        rig.down()

        job = _add_job(client, auth, SOURCE, "walks")

        assert job["status"] == "failed", job
        assert job["error"] == f"Walks cannot be read now: {DOWN}"

    def test_a_collection_added_before_says_why_wherever_its_files_are_read(
        self, client, auth, app, rig, user_and_token,
    ):
        user, _token = user_and_token
        walks = _add(client, auth, SOURCE, "walks")
        photos = _add(client, auth, SOURCE, "photos")
        video = _file_ids(walks)[WALKS[0]]

        rig.down()

        status = _status(client, auth, walks["id"])
        assert (status["local"], status["readInPlace"]) == (False, False), status
        assert (status["bucketHost"], status["mountProblem"], status["cachedFiles"]) == (HOST, DOWN, 0)
        for variant in ("original", "poster"):
            res = _media(client, auth, walks["id"], video, variant)
            assert res.status_code == 415, res.get_data(as_text=True)
            assert res.get_json()["error"] == f"{WALKS[0]} cannot be read now: {DOWN}"
        # A photo's preview is drawn from the bucket over HTTP, as before mounts.
        thumb = _media(client, auth, photos["id"], _file_ids(photos)[PHOTO], "thumb")
        assert thumb.status_code == 200 and thumb.mimetype == "image/jpeg", thumb.get_data(as_text=True)
        res = client.post(f"/api/discovery/collections/{walks['id']}/cache", headers=auth)
        assert res.status_code == 400 and res.get_json()["error"].endswith(f"cannot be read now: {DOWN}"), res.get_json()
        entry, load = _node_collections(app, user, walks)
        assert entry == {"kind": "videos", "unavailable": DOWN}
        with pytest.raises(RuntimeError, match=f"which cannot be read now: {DOWN}"):
            load()
        assert _objects(user) == []


# ── What does not mount keeps Cache files ───────────────────────────────────


class TestWhatDoesNotMount:
    def test_a_bucket_that_does_not_mount_is_cached_as_before(self, client, auth, app, rig, user_and_token):
        import pandas as pd

        dataset = _add(client, auth, ELSEWHERE, "sounds")
        status = _status(client, auth, dataset["id"])
        assert status["local"] is False and not status.get("readInPlace") and not status.get("mountProblem")

        res = client.post(f"/api/discovery/collections/{dataset['id']}/cache", headers=auth)
        assert res.status_code == 202, res.get_data(as_text=True)
        done = _wait(client, auth, res.get_json()["jobId"])

        assert done["status"] == "completed", done.get("error")
        assert _status(client, auth, dataset["id"])["cachedFiles"] == 1
        assert pd.read_parquet(dataset["path"])["duration_s"].notna().all()
        assert not [params for method, params in rig.service.calls
                    if method == "mount/mount" and params["mountPoint"].endswith(ELSEWHERE)]

    def test_a_hugging_face_repository_and_an_http_bucket_keep_cache_files(self, rig):
        from utk_curio.backend.app.discovery.application.bucket_mount_sources import BucketReads, cache_refusal
        from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest_from_dir
        from utk_curio.backend.app.discovery.providers.s3 import S3Storage

        hugging_face = load_source_manifest_from_dir(SHIPPED_ROOT / HF)
        plain_http = a_manifest("http://data.example.org/walks", "data/")

        for manifest in (hugging_face, plain_http):
            found = BucketReads(manifest).state()
            assert found.state == "not-mountable", found
            assert cache_refusal(found) is None
        assert S3Storage(plain_http, None, reads=BucketReads(plain_http)).local_path(WALKS[0]) is None
        assert rig.service.calls == []
