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

One cache of a collection runs at a time for an account (:func:`claim`), and
what the account's running caches have still to fetch counts against its cap.
A bucket's index lists its videos and recordings by path and size alone, so
their details are read from the cached files and written into the index
(:func:`record_details`).
"""

from __future__ import annotations

import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from utk_curio.backend.app.discovery.application import probe as probing
from utk_curio.backend.app.discovery.domain.errors import (
    CapabilityUnsupported,
    DiscoveryError,
    DownloadTooLarge,
)
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
    """What this account's cached files take. A file still being fetched (a
    ``.part``) counts in its cache's pending bytes instead (:func:`check_room`)."""
    root = media_dirs.media_work_root(user_key) / "objects"
    if not root.is_dir():
        return 0
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.name.endswith(".part"))


def check_room(user_key: str, needed: int, *, caching: str | None = None) -> None:
    """Refuse *needed* more bytes in *user_key*'s media cache past its cap.

    What the account's running caches have still to fetch counts as held.
    With *caching*, the id of a collection whose cache this account holds
    (:func:`claim`), *needed* becomes that cache's pending bytes in the same
    step, so two caches started together cannot both pass.
    """
    cap = cap_bytes()
    with _caches_lock:
        pending = _pending(user_key)
        if used_bytes(user_key) + pending + needed > cap:
            coming = f"; caches running now have {pending:,} more to fetch" if pending else ""
            raise DownloadTooLarge(
                f"caching these files needs {needed:,} bytes; this account's media cache is "
                f"limited to {cap:,} ({ENV_CAP}){coming}"
            )
        held = _caches.get((user_key, caching)) if caching is not None else None
        if held is not None:
            held.pending = needed


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
    owner: str | None = None,
    items: Callable[[int, int | None], None] | None = None,
    progress: Callable[[int, int | None], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    describe: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Fetch every file of *dataset* not yet cached, then read the details of
    the videos and recordings among its cached files. Returns counts.

    *owner* is the cache (a job) whose caller claimed the collection already
    (:func:`claim`). Without it this call claims it, and either way it refuses
    while another cache of the collection runs. *describe*, when given, gets
    what the collection's block says of its files once their details are read
    (``probeErrors``, and ``totalSeconds`` for recordings), for the Data
    Catalog to keep.
    """
    owner = owner or uuid.uuid4().hex
    held, claimed = claim(user_key, dataset["id"], lambda: owner)
    if held != owner:
        raise CacheRunning("these files are being cached already")
    try:
        return _cache(
            user_key, dataset, provider,
            items=items, progress=progress, cancelled=cancelled, describe=describe,
        )
    finally:
        if claimed:
            release(user_key, dataset["id"], owner)


def _cache(user_key, dataset, provider, *, items, progress, cancelled, describe) -> dict[str, Any]:
    import pandas as pd
    import pyarrow.parquet as pq

    from utk_curio.backend.app.discovery.application.storage_acquire import Cancelled

    if provider.local_path is None or getattr(provider, "type", "") == "folder":
        raise CapabilityUnsupported("this collection's files are already on this machine")
    names = set(pq.read_schema(dataset["path"]).names)
    index = pd.read_parquet(dataset["path"], columns=[c for c in _READ if c in names])
    target = objects_dir(user_key, dataset["id"])
    _drop_parts(target)
    todo = []
    for row in index[["file_id", "relpath", "ext", "bytes"]].itertuples(index=False):
        existing = target / cached_name(row.file_id, row.ext)
        if existing.is_file() and existing.stat().st_size == int(row.bytes):
            continue
        todo.append(row)
    check_sizes(todo)
    needed = sum(int(r.bytes) for r in todo)
    check_room(user_key, needed, caching=dataset["id"])
    ceiling = file_cap_bytes()
    done_bytes = 0
    try:
        for count, row in enumerate(todo, start=1):
            if cancelled is not None and cancelled():
                raise Cancelled()
            final = target / cached_name(row.file_id, row.ext)
            part = final.with_name(final.name + ".part")
            # Opened before the fetch: when another cache writes it, it stays theirs.
            handle = _open_part(part, row.relpath)
            landed = False
            try:
                with handle:
                    provider.stream(
                        row.relpath,
                        handle.write,
                        max_bytes=int(row.bytes) + 1024 * 1024,
                        ceiling=ceiling,
                    )
                _land(part, final, user_key, dataset["id"], int(row.bytes))
                landed = True
            finally:
                if not landed:
                    part.unlink(missing_ok=True)
            media_dirs.grant_to_child(final)
            done_bytes += int(row.bytes)
            if items is not None:
                items(count, len(todo))
            if progress is not None:
                progress(done_bytes, needed)
    finally:
        # What landed is read even when the cache stops partway.
        _read_cached_details(user_key, dataset, index, describe)
    return {"cached": len(todo), "bytes": done_bytes, "total": len(index)}


# ── the caches running in this process ─────────────────────────────────────


class CacheRunning(DiscoveryError):
    """A cache of this collection runs already for this account."""

    status = 409


@dataclass
class _Cache:
    #: The job that runs it.
    owner: str
    #: What it has still to fetch, once it has counted its files: held
    #: against the account's cap until each file lands.
    pending: int = 0


_caches: dict[tuple[str, str], _Cache] = {}
_caches_lock = threading.Lock()


def claim(user_key: str, dataset_id: str, start: Callable[[], str]) -> tuple[str, bool]:
    """Make one cache the only one of *dataset_id* running for *user_key*.

    With none running, ``start()`` makes it (a job, say) and names its owner,
    and this returns ``(owner, True)``. With one running, ``start`` is not
    called, and this returns ``(that cache's owner, False)``. Both under one
    lock, so two requests at once start one cache.
    """
    key = (user_key, dataset_id)
    with _caches_lock:
        held = _caches.get(key)
        if held is not None:
            return held.owner, False
        owner = start()
        _caches[key] = _Cache(owner)
        return owner, True


def release(user_key: str, dataset_id: str, owner: str) -> None:
    """The cache *owner* of *dataset_id* has ended."""
    key = (user_key, dataset_id)
    with _caches_lock:
        held = _caches.get(key)
        if held is not None and held.owner == owner:
            del _caches[key]


def running_cache(user_key: str, dataset_id: str) -> str | None:
    """The owner of the cache of *dataset_id* running for *user_key*, if one is."""
    with _caches_lock:
        held = _caches.get((user_key, dataset_id))
        return held.owner if held is not None else None


def reset_running() -> None:
    """Forget every running cache. Process state, cleared between tests as
    the rate limiter's is."""
    with _caches_lock:
        _caches.clear()


def _pending(user_key: str) -> int:
    """What *user_key*'s running caches have still to fetch. The lock is held."""
    return sum(held.pending for (key, _dataset), held in _caches.items() if key == user_key)


def _land(part: Path, final: Path, user_key: str, dataset_id: str, size: int) -> None:
    """Put a fetched file in place, and take it off its cache's pending bytes
    in the same step: :func:`check_room` never counts it twice."""
    with _caches_lock:
        os.replace(part, final)
        held = _caches.get((user_key, dataset_id))
        if held is not None:
            held.pending = max(0, held.pending - size)


def _drop_parts(folder: Path) -> None:
    """Remove what a cache that never ended left half fetched. Called holding
    the collection's claim, so no cache in this process is writing one."""
    for part in folder.glob("*.part"):
        part.unlink(missing_ok=True)


def _open_part(part: Path, relpath: str):
    """A new file for one fetch: never one another cache writes, even in
    another process, since it must not exist yet."""
    try:
        return part.open("xb")
    except FileExistsError:
        raise CacheRunning(f"another cache is writing {relpath}") from None


# ── what a cached file says about itself ───────────────────────────────────

#: The kinds a bucket's index lists by path and size alone
#: (``index_collection.build_rows``): their details are read once cached.
READ_ONCE_CACHED = ("video", "audio")

#: The index columns a cache reads, as far as the index has them.
_READ = ("file_id", "relpath", "ext", "bytes", "kind", "duration_s", "probe_error")


def _read_cached_details(user_key: str, dataset: dict[str, Any], index, describe=None) -> None:
    """Read the details of the cached videos and recordings the index lacks,
    those an earlier cache copied among them, and write them into it. A file
    that cannot be read says why in its row's ``probe_error``. *describe* then
    gets what the collection's block says of its files, as indexing a folder
    counts it (``index_collection.collection_block``)."""
    import logging

    try:
        found = {}
        for row in _unread(index):
            path = cached_file(user_key, dataset["id"], row.file_id, row.ext)
            if path is not None and path.stat().st_size == int(row.bytes):
                found[row.file_id] = probing.probe(row.kind, path)
        record_details(dataset["path"], found)
        if found and describe is not None:
            describe(_block_fields(dataset))
    except Exception:  # noqa: BLE001 - the files are cached either way
        logging.getLogger(__name__).warning(
            "Could not record the details of %s's cached files", dataset.get("id"), exc_info=True
        )


def _block_fields(dataset: dict[str, Any]) -> dict[str, Any]:
    """``probeErrors``, and for recordings ``totalSeconds``, from the index as it is now."""
    import pandas as pd
    import pyarrow.parquet as pq

    names = set(pq.read_schema(dataset["path"]).names)
    index = pd.read_parquet(dataset["path"], columns=[c for c in ("duration_s", "probe_error") if c in names])
    fields: dict[str, Any] = {}
    if "probe_error" in index.columns:
        fields["probeErrors"] = int(index["probe_error"].notna().sum())
    kind = (dataset.get("collection") or {}).get("kind")
    if kind == "audio" and "duration_s" in index.columns and index["duration_s"].notna().any():
        fields["totalSeconds"] = round(float(index["duration_s"].fillna(0).sum()), 3)
    return fields


def _unread(index) -> list:
    """The rows of videos and recordings whose details the index has not read."""
    if "kind" not in index.columns:
        return []
    wanted = index["kind"].isin(READ_ONCE_CACHED)
    for column in ("duration_s", "probe_error"):
        if column in index.columns:
            wanted &= index[column].isna()
    return list(index.loc[wanted, ["file_id", "ext", "kind", "bytes"]].itertuples(index=False))


def record_details(index_path: str, details: dict[str, dict[str, Any]]) -> None:
    """Write *details* (``{file_id: what probing its file found}``) into a
    collection's index, filling only what the index lacks: a time a file's
    path or a metadata table gave stays. New columns go before ``bytes``, as
    an index of a folder has them. The file is replaced whole, as GeoParquet
    when it was one and with its mode, so a reader sees the old index or the
    new one."""
    if not details:
        return
    import pandas as pd
    import pyarrow.parquet as pq

    from utk_curio.backend.app.discovery.application.index_collection import TRAILING_COLUMNS

    path = Path(index_path)
    geo = b"geo" in (pq.read_schema(path).metadata or {})
    if geo:
        import geopandas as gpd

        frame = gpd.read_parquet(path)
    else:
        frame = pd.read_parquet(path)
    found = pd.DataFrame.from_dict(details, orient="index")
    added = []
    for column in found.columns:
        values = frame["file_id"].map(found[column])
        if column in frame.columns:
            frame[column] = frame[column].where(frame[column].notna(), values)
        else:
            frame[column] = values
            added.append(column)
    if added:
        last = [c for c in (*TRAILING_COLUMNS, "geometry") if c in frame.columns]
        frame = frame[[c for c in frame.columns if c not in last] + last]
    part = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        if geo:
            frame.to_parquet(part)
        else:
            frame.to_parquet(part, index=False)
        shutil.copymode(path, part)
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
