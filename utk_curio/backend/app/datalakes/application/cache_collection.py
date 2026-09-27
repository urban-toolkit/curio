"""Copy a bucket collection's files to this machine, so nodes can read them.

A collection in a bucket is indexed from the bucket's listing, and its files
stay there. A node reading pixels, samples or frames needs them on disk, and
under isolation a node has no network at all, so the files are fetched once,
by the backend, through the lake transport and its egress policy, into the
user's media directory. Until a file is cached its ``path`` is null.

Bounded twice: one object at a time up to
:data:`~infrastructure.transport.MAX_COLLECTION_OBJECT_BYTES`, and all of a
user's cached objects together up to ``CURIO_MEDIA_CACHE_MAX_GB``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from utk_curio.backend.app.datalakes.domain.errors import CapabilityUnsupported, DownloadTooLarge
from utk_curio.backend.app.datalakes.infrastructure import media_dirs
from utk_curio.backend.app.datalakes.infrastructure.transport import MAX_COLLECTION_OBJECT_BYTES

ENV_CAP = "CURIO_MEDIA_CACHE_MAX_GB"
DEFAULT_CAP_GB = 20


def cap_bytes() -> int:
    raw = os.environ.get(ENV_CAP)
    try:
        gigabytes = float(raw) if raw else DEFAULT_CAP_GB
    except ValueError:
        gigabytes = DEFAULT_CAP_GB
    return int(max(0.0, gigabytes) * 1024**3)


def cached_name(file_id: str, ext: str) -> str:
    return f"{file_id}.{ext}" if ext else file_id


def objects_dir(user_key: str, dataset_id: str, *, create: bool = True) -> Path:
    if create:
        return media_dirs.media_work_dir(user_key, "objects", dataset_id)
    return media_dirs.media_work_root(user_key) / "objects" / dataset_id


def cached_file(user_key: str, dataset_id: str, file_id: str, ext: str) -> Path | None:
    path = objects_dir(user_key, dataset_id, create=False) / cached_name(file_id, ext)
    return path if path.is_file() else None


def cached_count(user_key: str, dataset_id: str) -> tuple[int, int]:
    """How many of a collection's files are on this machine, and their bytes."""
    folder = objects_dir(user_key, dataset_id, create=False)
    if not folder.is_dir():
        return 0, 0
    files = [p for p in folder.iterdir() if p.is_file() and not p.name.endswith(".part")]
    return len(files), sum(p.stat().st_size for p in files)


def used_bytes(user_key: str) -> int:
    root = media_dirs.media_work_root(user_key) / "objects"
    if not root.is_dir():
        return 0
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def cache(
    user_key: str,
    dataset: dict[str, Any],
    provider,
    *,
    items: Callable[[int, int | None], None] | None = None,
    progress: Callable[[int, int | None], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Fetch every file of *dataset* not yet cached. Returns counts."""
    import pandas as pd

    from utk_curio.backend.app.datalakes.application.storage_acquire import Cancelled

    if provider.local_path is None or getattr(provider, "type", "") == "folder":
        raise CapabilityUnsupported("this collection's files are already on this machine")
    index = pd.read_parquet(dataset["path"], columns=["file_id", "relpath", "ext", "bytes"])
    target = objects_dir(user_key, dataset["id"])
    todo = []
    for row in index.itertuples(index=False):
        existing = target / cached_name(row.file_id, row.ext)
        if existing.is_file() and existing.stat().st_size == int(row.bytes):
            continue
        todo.append(row)
    needed = sum(int(r.bytes) for r in todo)
    cap = cap_bytes()
    if used_bytes(user_key) + needed > cap:
        raise DownloadTooLarge(
            f"caching these files needs {needed:,} bytes; this account's media cache is "
            f"limited to {cap:,} ({ENV_CAP})"
        )
    done_bytes = 0
    for count, row in enumerate(todo, start=1):
        if cancelled is not None and cancelled():
            raise Cancelled()
        if int(row.bytes) > MAX_COLLECTION_OBJECT_BYTES:
            raise DownloadTooLarge(f"{row.relpath} is larger than one object may be")
        final = target / cached_name(row.file_id, row.ext)
        part = final.with_name(final.name + ".part")
        with part.open("wb") as handle:
            provider.stream(
                row.relpath,
                handle.write,
                max_bytes=int(row.bytes) + 1024 * 1024,
                ceiling=MAX_COLLECTION_OBJECT_BYTES,
            )
        os.replace(part, final)
        media_dirs.grant_to_child(final)
        done_bytes += int(row.bytes)
        if items is not None:
            items(count, len(todo))
        if progress is not None:
            progress(done_bytes, needed)
    return {"cached": len(todo), "bytes": done_bytes, "total": len(index)}
