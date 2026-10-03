"""The Discovery Catalog's download ceiling: 1 GiB unless ``curio.py
--discovery-max-download-mb`` says otherwise, lowered per source by a manifest.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.infrastructure import transport as T
from utk_curio.backend.tests.test_discovery.conftest import SHIPPED_ROOT
from utk_curio.backend.tests.test_discovery.test_acquire import acquire, wait_for
from utk_curio.backend.tests.test_discovery.test_storage_buckets import (  # noqa: F401 - fixtures
    _fresh_listings,
    add,
    bucket_corpus,
)

GIB = 1024 ** 3


def _limits():
    from utk_curio.backend.app.discovery.domain import limits

    return limits


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def failing(app, failing_source, fixture_corpus):
    return app


class TestTheCeiling:
    def test_it_is_one_gibibyte_unless_set(self, monkeypatch):
        monkeypatch.delenv("CURIO_DISCOVERY_MAX_DOWNLOAD_MB", raising=False)
        assert _limits().max_download_bytes() == GIB

    def test_the_flag_sets_it_in_megabytes(self, monkeypatch):
        monkeypatch.setenv("CURIO_DISCOVERY_MAX_DOWNLOAD_MB", "2048")
        assert _limits().max_download_bytes() == 2 * GIB

    @pytest.mark.parametrize("value", ["0", "-5", "lots", " "])
    def test_a_value_that_is_not_a_positive_number_is_the_default(self, monkeypatch, value):
        monkeypatch.setenv("CURIO_DISCOVERY_MAX_DOWNLOAD_MB", value)
        assert _limits().max_download_bytes() == GIB

    def test_the_transport_and_the_manifest_read_the_same_ceiling(self):
        assert T.MAX_DISCOVERY_DOWNLOAD_BYTES == M.DEFAULT_MAX_DOWNLOAD_BYTES == GIB


class TestTheShippedSources:
    def test_no_shipped_source_caps_itself_below_the_ceiling(self):
        """A manifest may lower the ceiling; none of the shipped ones does, so
        every download the catalog ships with may be as large as the instance
        allows."""
        for path in sorted(p for p in SHIPPED_ROOT.iterdir() if p.is_dir()):
            raw = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            assert "maxDownloadBytes" not in (raw.get("capabilities") or {}), path.name
            assert M.load_source_manifest(path).capabilities.max_download_bytes == M.DEFAULT_MAX_DOWNLOAD_BYTES


class TestADownload:
    def test_one_over_64_mib_and_under_the_ceiling_is_downloaded(self, client, auth, failing):
        """The response declares 100 MiB; a source that sets no limit of its
        own takes it up to the ceiling."""
        job = wait_for(
            client, auth,
            acquire(client, auth, "source.test.fail@1", "https://portal.test/declares-100mb.csv")
            .get_json()["jobId"],
        )
        assert job["status"] == "completed", job.get("error")
        assert job["dataset"]["format"] == "csv"

    def test_one_over_the_ceiling_is_refused_before_its_body(self, client, auth, failing):
        job = wait_for(
            client, auth,
            acquire(client, auth, "source.test.fail@1", "https://portal.test/declares-huge.csv")
            .get_json()["jobId"],
        )
        assert job["status"] == "failed" and "declares" in job["error"]


class TestABucketFile:
    def test_it_is_written_to_disk_as_it_arrives_never_held_in_memory(self, client, auth, app, bucket_corpus,
                                                                      monkeypatch):
        """A table added from a bucket is streamed to its file. ``open`` without a
        range reads a whole object into memory, so it must not be the way in."""
        import pandas as pd

        from utk_curio.backend.app.discovery.providers.s3 import S3Storage

        whole = S3Storage.open

        def ranged_only(self, relpath, *, byte_range=None, **kwargs):
            assert byte_range is not None, f"{relpath} was read whole into memory"
            return whole(self, relpath, byte_range=byte_range, **kwargs)

        monkeypatch.setattr(S3Storage, "open", ranged_only)
        job = add(client, auth, "source.example.bucket@1", "numbers")
        assert job["status"] == "completed", job.get("error")
        frame = pd.read_parquet(job["dataset"]["path"])
        assert sorted(frame["n"]) == [1, 2]
