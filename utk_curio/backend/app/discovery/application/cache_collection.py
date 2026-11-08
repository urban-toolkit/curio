"""Copy a bucket collection's files to this machine, so nodes can read them.

A collection in a bucket is indexed from the bucket's listing, and its files
stay there. A node reading pixels, samples or frames needs them on disk, and
under isolation a node has no network at all, so the files are fetched once,
by the backend, through the discovery transport and its egress policy, into the
user's media directory. Until a file is cached its ``path`` is null.

Bounded twice, both before a byte is fetched: each object up to
``CURIO_MEDIA_CACHE_MAX_FILE_GB`` (:func:`check_sizes`), and all of a user's
cached objects together up to ``CURIO_MEDIA_CACHE_MAX_GB``. A service's
images land in the same folder and are bounded by the same check,
:func:`check_room`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from utk_curio.backend.app.discovery.domain.errors import CapabilityUnsupported, DownloadTooLarge
from utk_curio.backend.app.discovery.infrastructure import media_dirs

ENV_CAP = "CURIO_MEDIA_CACHE_MAX_GB"
DEFAULT_CAP_GB = 20

#: The largest file one cache copies (``curio.py --media-cache-max-file-gb``).
ENV_FILE_CAP = "CURIO_MEDIA_CACHE_MAX_FILE_GB"
DEFAULT_FILE_CAP_GB = 4

#: The files a refusal names at most; it counts the rest.
NAMED_FILES = 3


def _gigabytes(env: str, default: float) -> int:
    raw = os.environ.get(env)
    try:
        gigabytes = float(raw) if raw else default
    except ValueError:
        gigabytes = default
    return int(max(0.0, gigabytes) * 1024**3)


def cap_bytes() -> int:
    """What one account may hold in cached files, in bytes."""
    return _gigabytes(ENV_CAP, DEFAULT_CAP_GB)


def file_cap_bytes() -> int:
    """The largest file a cache copies, in bytes. Read on each call, as
    :func:`cap_bytes` is."""
    return _gigabytes(ENV_FILE_CAP, DEFAULT_FILE_CAP_GB)


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


def check_room(user_key: str, needed: int) -> None:
    """Refuse *needed* more bytes in *user_key*'s media cache past its cap."""
    cap = cap_bytes()
    if used_bytes(user_key) + needed > cap:
        raise DownloadTooLarge(
            f"caching these files needs {needed:,} bytes; this account's media cache is "
            f"limited to {cap:,} ({ENV_CAP})"
        )


def check_sizes(rows) -> None:
    """Refuse a cache of *rows* (index rows, with ``relpath`` and ``bytes``)
    when one is larger than a cached file may be, before any is fetched.

    Checked as it is fetched instead, such a file ended the cache partway:
    the files before it were copied, and those after it never could be.
    """
    cap = file_cap_bytes()
    over = [(str(row.relpath), int(row.bytes)) for row in rows if int(row.bytes) > cap]
    if not over:
        return
    if len(over) == 1:
        relpath, size = over[0]
        raise DownloadTooLarge(
            f"{relpath} is {size:,} bytes; one cached file is limited to {cap:,} ({ENV_FILE_CAP})"
        )
    named = ", ".join(f"{relpath} ({size:,} bytes)" for relpath, size in over[:NAMED_FILES])
    if len(over) > NAMED_FILES:
        named += f" and {len(over) - NAMED_FILES:,} more"
    raise DownloadTooLarge(
        f"{len(over):,} files are larger than one cached file may be, {cap:,} bytes "
        f"({ENV_FILE_CAP}): {named}"
    )


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

    from utk_curio.backend.app.discovery.application.storage_acquire import Cancelled

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
    check_sizes(todo)
    needed = sum(int(r.bytes) for r in todo)
    check_room(user_key, needed)
    ceiling = file_cap_bytes()
    done_bytes = 0
    for count, row in enumerate(todo, start=1):
        if cancelled is not None and cancelled():
            raise Cancelled()
        final = target / cached_name(row.file_id, row.ext)
        part = final.with_name(final.name + ".part")
        with part.open("wb") as handle:
            provider.stream(
                row.relpath,
                handle.write,
                max_bytes=int(row.bytes) + 1024 * 1024,
                ceiling=ceiling,
            )
        os.replace(part, final)
        media_dirs.grant_to_child(final)
        done_bytes += int(row.bytes)
        if items is not None:
            items(count, len(todo))
        if progress is not None:
            progress(done_bytes, needed)
    return {"cached": len(todo), "bytes": done_bytes, "total": len(index)}
