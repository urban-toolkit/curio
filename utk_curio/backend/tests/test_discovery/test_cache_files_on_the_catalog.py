"""Cache files writes nothing into the Data Catalog's own files.

A collection the catalog ships is listed from the catalog's folder, and a
cache of it used to write there: once its files were copied, what was read
from them (a video's duration, a recording's sample rate) went into the
catalog's ``index.parquet``, and its block's counts into the catalog's
``manifest.json``. That folder is every account's, and a pip install keeps it
inside Curio's own package. What a cache reads of the files goes into the
account's copy of the collection instead, the one Add to project makes, or
nowhere when the account holds none.

Each committed collection here is made as the build scripts make one: an add
of a bucket's resource, moved into a catalog of this test's own
(``CURIO_CATALOG_ROOT``) under a committed id, its rows read from the listing
alone. The bucket is ``test_cache_collection.py``'s recorded one, whose files
are the storage example's clip and recording, listed at their own sizes, so
a cache reads what they hold. No socket opens; new names are imported inside
the tests, so a checkout without them fails each test on its own.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from utk_curio.backend.tests.test_discovery.test_cache_collection import (  # noqa: F401 - fixtures
    _add,
    _cache,
    _wait,
    auth,
    walks_bucket,
)

#: The id each resource's collection is committed under.
COMMITTED = {"walks": "data.example.walks", "sounds": "data.example.sounds"}


@pytest.fixture()
def catalog(tmp_path, monkeypatch):
    """A Data Catalog of this test's own, in place of the shipped one."""
    root = tmp_path / "catalog"
    root.mkdir()
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(root))
    return root


def _commit(added: dict, catalog: Path, dataset_id: str) -> Path:
    """The collection an add made, moved into *catalog* under *dataset_id*,
    as ``scripts/build_example_sideseeing.py`` commits the walk."""
    target = catalog / f"{dataset_id}@1"
    shutil.move(str(Path(added["path"]).parents[1]), str(target))
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    manifest["id"] = dataset_id
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target


def _snapshot(folder: Path) -> dict[str, bytes]:
    """Every file under *folder*, by its path there, with its bytes."""
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


def _changed(before: dict[str, bytes], folder: Path) -> list[str]:
    """The files under *folder* that are not as *before* holds them."""
    after = _snapshot(folder)
    return sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))


@pytest.mark.parametrize("resource_id", sorted(COMMITTED))
class TestACacheOfACommittedCollection:
    def test_leaves_the_catalogs_files_as_they_are_when_the_account_holds_no_copy(
        self, client, auth, app, walks_bucket, catalog, user_and_token, resource_id,
    ):
        import pandas as pd

        from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
        from utk_curio.backend.app.discovery.application import cache_collection

        user, _token = user_and_token
        dataset_id = COMMITTED[resource_id]
        committed = _commit(_add(client, auth, resource_id), catalog, dataset_id)
        index = pd.read_parquet(committed / "data" / "index.parquet")
        # Listed by path and size alone, as a bucket's files are added.
        assert "duration_s" not in index.columns, list(index.columns)
        before = _snapshot(committed)

        done = _wait(client, auth, _cache(client, auth, dataset_id)["jobId"])

        assert done["status"] == "completed", done.get("error")
        assert cache_collection.cached_count(str(user.id), dataset_id)[0] == len(index)
        assert _changed(before, committed) == [], "the cache wrote into the catalog's files"
        assert not dataset_dir(str(user.id), committed.name).exists()

    def test_writes_what_it_reads_of_the_files_into_the_accounts_copy(
        self, client, auth, app, walks_bucket, catalog, user_and_token, resource_id,
    ):
        import pandas as pd

        from utk_curio.backend.app.datasets.install.installer import install_dataset_from_catalog

        user, _token = user_and_token
        dataset_id = COMMITTED[resource_id]
        committed = _commit(_add(client, auth, resource_id), catalog, dataset_id)
        # The account's copy of it, as Add to project makes one.
        copy = install_dataset_from_catalog(str(user.id), committed.name).dest
        before = _snapshot(committed)

        done = _wait(client, auth, _cache(client, auth, dataset_id)["jobId"])

        assert done["status"] == "completed", done.get("error")
        assert _changed(before, committed) == [], "the cache wrote into the catalog's files"
        index = pd.read_parquet(copy / "data" / "index.parquet")
        assert "duration_s" in index.columns, list(index.columns)
        assert (index["duration_s"] > 0).all() and index["probe_error"].isna().all(), index.to_dict("records")
        block = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))["collection"]
        assert block["probeErrors"] == 0, block
        if resource_id == "sounds":
            assert block["totalSeconds"] == pytest.approx(float(index["duration_s"].sum()))
