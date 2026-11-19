"""The collections the Data Catalog ships whose files are in a bucket.

Such a collection is the index an add of a bucket's resource makes, committed
under an id of its own (``scripts/build_example_sideseeing.py`` commits the
SideSeeing walk so), and every account reads that index where the catalog
keeps it. For each one ``dataset_catalog_coverage.bucket_collections`` finds:

- where the deployment mounts its bucket, node code reads its files in place,
  as it reads an added collection's, the player streams them from the mount,
  and Cache files is refused;
- elsewhere, Cache files copies its files, here from the recorded corpus, the
  bucket's stand-in that CI's browser cases read too; node code reads the
  copies, and the catalog's files stay as they are committed.

No socket opens: the mount service is the fake rc client of
``test_bucket_mounts_read_in_place.py``, whose mounts show each file with the
bytes the recorded corpus serves for it, and the bucket is that corpus.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from utk_curio.backend.app.discovery.infrastructure import bucket_mounts as bm
from utk_curio.backend.tests.dataset_catalog_coverage import CORPUS, bucket_collections, bucket_source
from utk_curio.backend.tests.test_discovery.test_bucket_mount_sources import Clock
from utk_curio.backend.tests.test_discovery.test_bucket_mounts_read_in_place import FakeRclone, PlainFolders

BUCKETS = bucket_collections()


def _mounts(dataset) -> bool:
    """Whether a deployment that mounts buckets mounts this one's."""
    from utk_curio.backend.app.discovery.domain.bucket_mount import NotMountable, bucket_mount

    try:
        bucket_mount(bucket_source(dataset))
    except NotMountable:
        return False
    return True


MOUNTED = [dataset for dataset in BUCKETS if _mounts(dataset)]


def _ids(datasets) -> list[str]:
    return [dataset.dataset_id for dataset in datasets]


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


def _files(dataset) -> dict[str, bytes]:
    """Each file of the collection, by relpath, with the bytes the recorded
    corpus serves for it whole (``test_catalog_dataset_coverage.py`` checks
    it serves each one)."""
    import pandas as pd

    from utk_curio.backend.app.discovery.providers import build_storage

    index = json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))
    provider = build_storage(bucket_source(dataset), None)
    relpaths = pd.read_parquet(dataset.data_file, columns=["relpath"])["relpath"]
    return {relpath: (CORPUS / index[provider.file_url(relpath)]["file"]).read_bytes() for relpath in relpaths}


def _snapshot(folder: Path) -> dict[str, bytes]:
    """Every file under *folder*, by its path there, with its bytes."""
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


def _status(client, auth, dataset_id):
    res = client.get(f"/api/discovery/collections/{dataset_id}", headers=auth)
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def _wait(client, auth, job_id, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/discovery/jobs/{job_id}", headers=auth).get_json()
        if body["status"] in ("completed", "failed", "refused", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def _rows_for_node_code(app, user, dataset_id):
    """What a run hands the sandbox for *dataset_id*, as ``/processPythonCode``
    resolves it: the index's path and where its files are; and its rows as
    ``curio_load_collection`` gives them there."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService
    from utk_curio.backend.app.discovery.application.exec_collections import resolve_collections
    from utk_curio.backend.app.discovery.infrastructure import media_dirs
    from utk_curio.sandbox.util.collections import make_collection_helpers

    with app.test_request_context():
        paths = DatasetCatalogService(user).resolve_execution_paths([dataset_id])
        collections = resolve_collections([dataset_id], str(user.id), user=user)
    helpers = make_collection_helpers(paths.get, collections, str(media_dirs.media_work_root(str(user.id))))
    return paths[dataset_id], collections[dataset_id], helpers["curio_load_collection"](dataset_id)


def test_the_catalog_ships_bucket_collections_and_its_deployments_mount_them():
    """Both lists below are the catalog's, so a catalog without such a
    collection would make every test here collect nothing."""
    assert BUCKETS, "no committed collection's files are in a bucket"
    assert MOUNTED, "no committed bucket collection's bucket mounts"


# ── Where the deployment mounts the bucket ──────────────────────────────────


def _resolver(_host):
    """Every host resolves to a public address, as the mount's host check asks."""
    return ["93.184.216.34"]


@pytest.fixture()
def mounted(tmp_path, monkeypatch, shipped_root):
    """A deployment that mounts buckets, whose fake mount service shows each
    committed bucket collection's files with the bytes the corpus serves."""
    from utk_curio.backend.app.discovery.application import bucket_mount_check, media, scan
    from utk_curio.backend.app.discovery.application import bucket_mount_sources as sources_module
    from utk_curio.backend.app.discovery.domain.bucket_mount import bucket_mount
    from utk_curio.backend.app.discovery.infrastructure.mount_proxy import MountProxy
    from utk_curio.backend.app.monitor import errors

    mounts_dir = tmp_path / "bucket-mounts"
    mounts_dir.mkdir()
    monkeypatch.setenv(bm.DIR_VARIABLE, str(mounts_dir))
    monkeypatch.setenv(bm.SOCKET_VARIABLE, FakeRclone.socket_path)
    monkeypatch.setenv("CURIO_TESTING", "1")
    shows: dict[str, dict[str, bytes]] = {}
    for dataset in MOUNTED:
        mount = bucket_mount(bucket_source(dataset))
        shows.setdefault(mount.name, {}).update(
            {mount.path_of(relpath): data for relpath, data in _files(dataset).items()}
        )
    service = FakeRclone(mounts_dir, shows)
    the_sources = sources_module.BucketMountSources(
        service, mounts_dir, proxy=MountProxy(), folders=PlainFolders(service), resolver=_resolver, clock=Clock(),
    )
    errors.reset()
    bucket_mount_check.reset()
    sources_module.reset()
    monkeypatch.setattr(sources_module, "sources", lambda: the_sources)
    scan.listings.reset()
    media.index_cache._rows.clear()
    yield mounts_dir
    scan.listings.reset()
    media.index_cache._rows.clear()
    sources_module.reset()
    bucket_mount_check.reset()
    errors.reset()


@pytest.mark.parametrize("dataset", MOUNTED, ids=_ids(MOUNTED))
def test_where_the_bucket_mounts_its_files_are_read_in_place(dataset, client, auth, app, mounted, user_and_token):
    from utk_curio.backend.app.discovery.application import media
    from utk_curio.backend.app.discovery.domain.bucket_mount import bucket_mount
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    user, _token = user_and_token
    mount = bucket_mount(bucket_source(dataset))
    folder = mounted / mount.name
    files = _files(dataset)
    committed = _snapshot(dataset.root)

    index_path, entry, rows = _rows_for_node_code(app, user, dataset.dataset_id)

    # Node code reads the catalog's own index, and each file in the mount.
    assert Path(index_path).samefile(dataset.data_file)
    assert entry == {"kind": dataset.manifest.collection["kind"], "root": str(folder), "tail": mount.tail}
    assert sorted(rows["path"]) == sorted(os.path.join(str(folder), *mount.path_of(r).split("/")) for r in files)
    for relpath, path in zip(rows["relpath"], rows["path"]):
        assert Path(path).read_bytes() == files[relpath], relpath
    # The player streams each file a browser shows from the mount, a range at a time.
    for file_id, relpath in zip(rows["file_id"], rows["relpath"]):
        if media.sniff(files[relpath][:32]) not in media.BROWSER_TYPES:
            continue
        part = client.get(f"/api/datasets/{dataset.dataset_id}/media/{file_id}?variant=original",
                          headers={**auth, "Range": "bytes=0-99"})
        assert part.status_code == 206, part.get_data(as_text=True)
        assert part.data == files[relpath][:100], relpath
    # Its details say so, and offer no Cache files, which is refused.
    status = _status(client, auth, dataset.dataset_id)
    assert (status["local"], status["readInPlace"], status["bucketHost"]) == (True, True, mount.host), status
    res = client.post(f"/api/discovery/collections/{dataset.dataset_id}/cache", headers=auth)
    assert res.status_code == 400, res.get_data(as_text=True)
    assert "is not cached: its files are read in place from the bucket" in res.get_json()["error"]
    assert not (media_dirs.media_work_root(str(user.id)) / "objects").exists()
    assert _snapshot(dataset.root) == committed


# ── Where no mount reads the bucket ─────────────────────────────────────────


@pytest.fixture()
def unmounted(tmp_path, monkeypatch, shipped_root, fixture_corpus):
    """A deployment that mounts no bucket and reads buckets from the recorded
    corpus, with a catalog of its own, which holds copies of the committed
    bucket collections."""
    from utk_curio.backend.app.discovery.application import bucket_mount_sources, scan

    for variable in (bm.DIR_VARIABLE, bm.SOCKET_VARIABLE, "CURIO_MEDIA_CACHE_MAX_GB", "CURIO_MEDIA_CACHE_MAX_FILE_GB"):
        monkeypatch.delenv(variable, raising=False)
    bucket_mount_sources.reset()
    catalog = tmp_path / "catalog"
    for dataset in BUCKETS:
        shutil.copytree(dataset.root, catalog / dataset.root.name)
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(catalog))
    scan.listings.reset()
    yield catalog
    scan.listings.reset()
    bucket_mount_sources.reset()


@pytest.mark.parametrize("dataset", BUCKETS, ids=_ids(BUCKETS))
def test_elsewhere_cache_files_copies_its_files_and_leaves_the_catalog_as_committed(
    dataset, client, auth, app, unmounted, user_and_token,
):
    import pandas as pd

    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.app.discovery.application import cache_collection

    user, _token = user_and_token
    folder = unmounted / dataset.root.name
    files = _files(dataset)
    committed = _snapshot(folder)
    status = _status(client, auth, dataset.dataset_id)
    assert (status["local"], status["readInPlace"], status["cachedFiles"]) == (False, False, 0), status

    res = client.post(f"/api/discovery/collections/{dataset.dataset_id}/cache", headers=auth)
    assert res.status_code == 202, res.get_data(as_text=True)
    done = _wait(client, auth, res.get_json()["jobId"])

    assert done["status"] == "completed", done.get("error")
    # Each file is copied as the corpus serves it, however the listing sizes it.
    index = pd.read_parquet(folder / dataset.manifest.data_file, columns=["file_id", "relpath", "ext"])
    for row in index.itertuples(index=False):
        cached = cache_collection.cached_file(str(user.id), dataset.dataset_id, row.file_id, row.ext)
        assert cached is not None and cached.read_bytes() == files[row.relpath], row.relpath
    status = _status(client, auth, dataset.dataset_id)
    assert status["cachedFiles"] == status["fileCount"] == len(index), status
    # Node code reads the catalog's index, and each file from the copies.
    index_path, entry, rows = _rows_for_node_code(app, user, dataset.dataset_id)
    assert Path(index_path).samefile(folder / dataset.manifest.data_file)
    assert set(entry) == {"kind", "objects"}, entry
    assert all(path and Path(path).read_bytes() == files[relpath] for relpath, path in zip(rows["relpath"], rows["path"]))
    # The catalog's files are as committed, and the account was given no copy.
    assert _snapshot(folder) == committed
    assert not dataset_dir(str(user.id), dataset.root.name).exists()
