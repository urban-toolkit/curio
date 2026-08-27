"""Tests for :mod:`utk_curio.backend.app.packages.build_staging` (dev/89 commit 2).

Content-addressed staging: idempotent writes, verify-on-read, loud
missing/corrupt handling, and TTL expiry.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from utk_curio.backend.app.packages import build_staging
from utk_curio.backend.app.packages.build_staging import (
    StagingError,
    discard_artifact,
    has_artifact,
    read_artifact,
    stage_artifact,
    sweep_expired,
    user_build_staging_dir,
)


def test_stage_and_read_round_trip(tmp_curio):
    data = b"zip-bytes-1"
    digest = stage_artifact("guest", data)
    assert digest == hashlib.sha256(data).hexdigest()
    assert has_artifact("guest", digest)
    assert read_artifact("guest", digest) == data
    path = user_build_staging_dir("guest") / f"{digest}.zip"
    assert path.is_file()
    meta = json.loads((user_build_staging_dir("guest") / f"{digest}.meta.json").read_text())
    assert meta["bytes"] == len(data)


def test_stage_is_idempotent(tmp_curio):
    data = b"same-bytes"
    assert stage_artifact("guest", data) == stage_artifact("guest", data)
    assert read_artifact("guest", stage_artifact("guest", data)) == data


def test_read_missing_raises_loudly(tmp_curio):
    with pytest.raises(StagingError, match="not staged"):
        read_artifact("guest", "0" * 64)


def test_bad_digest_shapes_refused(tmp_curio):
    for bad in ("short", "Z" * 64, "0" * 63, ""):
        with pytest.raises(StagingError, match="64 lowercase hex"):
            read_artifact("guest", bad)


def test_corruption_detected_and_removed(tmp_curio):
    digest = stage_artifact("guest", b"original")
    path = user_build_staging_dir("guest") / f"{digest}.zip"
    path.write_bytes(b"tampered")
    with pytest.raises(StagingError, match="integrity verification"):
        read_artifact("guest", digest)
    # The corrupt file was removed so it can never be promoted.
    assert not path.is_file()
    assert not has_artifact("guest", digest)


def test_stage_rejects_empty_and_oversized(tmp_curio):
    with pytest.raises(StagingError, match="non-empty"):
        stage_artifact("guest", b"")
    with pytest.raises(StagingError, match="staging limit"):
        stage_artifact("guest", b"x" * (build_staging.MAX_ARTIFACT_BYTES + 1))


def test_discard(tmp_curio):
    digest = stage_artifact("guest", b"discard-me")
    assert discard_artifact("guest", digest) is True
    assert discard_artifact("guest", digest) is False
    assert not has_artifact("guest", digest)


def test_sweep_expired_removes_old_keeps_fresh(tmp_curio):
    old = stage_artifact("guest", b"old-artifact")
    fresh = stage_artifact("guest", b"fresh-artifact")
    # Age the old artifact via its metadata timestamp.
    meta_path = user_build_staging_dir("guest") / f"{old}.meta.json"
    meta = json.loads(meta_path.read_text())
    meta["createdAt"] = meta["createdAt"] - build_staging.DEFAULT_TTL_SECONDS - 10
    meta_path.write_text(json.dumps(meta))

    removed = sweep_expired("guest")
    assert removed == [old]
    assert not has_artifact("guest", old)
    assert read_artifact("guest", fresh) == b"fresh-artifact"


def test_sweep_missing_metadata_falls_back_to_mtime(tmp_curio):
    import os

    digest = stage_artifact("guest", b"meta-less")
    (user_build_staging_dir("guest") / f"{digest}.meta.json").unlink()
    path = user_build_staging_dir("guest") / f"{digest}.zip"
    stale = path.stat().st_mtime - build_staging.DEFAULT_TTL_SECONDS - 10
    os.utime(path, (stale, stale))
    assert sweep_expired("guest") == [digest]


def test_sweep_clears_stray_tmp_files(tmp_curio):
    base = user_build_staging_dir("guest")
    base.mkdir(parents=True, exist_ok=True)
    stray = base / ".tmp-abcdef"
    stray.write_bytes(b"half-written")
    assert sweep_expired("guest") == []
    assert not stray.exists()


def test_sweep_without_store_is_empty(tmp_curio):
    assert sweep_expired("guest") == []
