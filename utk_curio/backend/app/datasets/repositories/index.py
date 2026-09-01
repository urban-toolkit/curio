"""Dataset index access: keyed reads, write-through, and disk reconciliation.

The index (:class:`DatasetIndexEntry`) mirrors the manifests in a user's account
dataset store so catalog reads are keyed lookups instead of a scan that parses
every ``manifest.json``. It is a **derived cache**: :func:`reconcile` refreshes it
from disk, and every caller falls back to reading the manifest when a store dir
has no row, so a stale or missing row can never hide a dataset.

Two rules hold everywhere in this module:

* **Never raise into a caller.** Indexing is an accelerator; a DB failure must
  degrade to "no row" and let the filesystem path serve the request. Callers use
  :func:`safe_upsert_from_dir` / :func:`safe_forget` / :func:`safe_reconcile` on
  the write and read paths for exactly this reason.
* **A dir whose manifest fails validation gets no row** — identical to the
  listing's own behaviour (``ManifestError``/``OSError``/``ValueError`` → skip),
  so the index can't resurrect a dataset the catalog considers unreadable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from utk_curio.backend.extensions import db
from utk_curio.backend.app.datasets.domain.manifest import (
    DatasetManifest,
    ManifestError,
    load_dataset_manifest,
)
from utk_curio.backend.app.datasets.models import DatasetIndexEntry
from utk_curio.backend.app.datasets.infrastructure.storage import (
    DATASET_DIR_RE,
    list_user_datasets,
)

logger = logging.getLogger(__name__)

# Dir-name prefixes the index covers, mapped to the catalog ``origin`` the
# listing assigns them. Mirrors UserDatasetRepository's classification: any other
# prefix (a hub copy installed under its own id, say) is not an account-level
# asset and is left to the scan.
_ORIGIN_BY_PREFIX = {"imported.": "imported", "computed.": "computed"}


def origin_for_dir(dir_name: str) -> Optional[str]:
    """Catalog origin for a store dir name, or ``None`` if it isn't indexable."""
    for prefix, origin in _ORIGIN_BY_PREFIX.items():
        if dir_name.startswith(prefix):
            return origin
    return None


def _manifest_stat(dataset_root: Path) -> tuple[Optional[int], Optional[int]]:
    try:
        stat = (dataset_root / "manifest.json").stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None, None


def _dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)


def _loads(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


# ── Row <-> manifest ────────────────────────────────────────────────────────

def manifest_from_row(row: DatasetIndexEntry) -> DatasetManifest:
    """Rebuild the manifest a row mirrors.

    Returning the real :class:`DatasetManifest` (rather than a hand-built item
    dict) is deliberate: callers then pass it to the same
    ``item_from_manifest`` the disk path uses, so an indexed item and a scanned
    item are identical by construction and cannot drift apart.
    """
    return DatasetManifest(
        id=row.dataset_id,
        name=row.title,
        version=row.version or "1.0.0",
        format=row.format,
        description=row.description or "",
        publisher=row.publisher or "",
        license=row.license or "",
        tags=_loads(row.tags_json, []),
        data_file=row.data_file,
        major=row.major,
        created_at=row.created_at_iso,
        updated_at=row.updated_at_iso,
        source_updated_at=row.source_updated_at_iso,
        feature_count=row.feature_count,
        row_count=row.row_count,
        schema=_loads(row.schema_json, None),
        source_label=row.source_label,
        group_id=row.group_id,
        layer_name=row.layer_name,
        producer_node_id=row.producer_node_id,
        producer_node_type=row.producer_node_type,
        producer_dataflow_id=row.producer_dataflow_id,
        producer_dataflow_name=row.producer_dataflow_name,
        upstream_inputs=_loads(row.upstream_inputs_json, None),
    )


def _apply_manifest(
    row: DatasetIndexEntry,
    manifest: DatasetManifest,
    *,
    dir_name: str,
    origin: str,
    mtime_ns: Optional[int],
    size: Optional[int],
) -> None:
    row.dataset_id = manifest.id
    row.dir_name = dir_name
    row.major = manifest.major
    row.origin = origin
    row.title = manifest.name or ""
    row.version = manifest.version
    row.format = manifest.format
    row.description = manifest.description or ""
    row.publisher = manifest.publisher or ""
    row.license = manifest.license or ""
    row.tags_json = _dumps(list(manifest.tags or []))
    row.schema_json = _dumps(manifest.schema)
    row.data_file = manifest.data_file
    row.source_label = manifest.source_label
    row.row_count = manifest.row_count
    row.feature_count = manifest.feature_count
    row.group_id = manifest.group_id
    row.layer_name = manifest.layer_name
    row.created_at_iso = manifest.created_at
    row.updated_at_iso = manifest.updated_at
    row.source_updated_at_iso = manifest.source_updated_at
    row.producer_node_id = manifest.producer_node_id
    row.producer_node_type = manifest.producer_node_type
    row.producer_dataflow_id = manifest.producer_dataflow_id
    row.producer_dataflow_name = manifest.producer_dataflow_name
    row.upstream_inputs_json = _dumps(
        [dict(entry) for entry in manifest.upstream_inputs]
        if manifest.upstream_inputs
        else None
    )
    row.manifest_mtime_ns = mtime_ns
    row.manifest_size = size


# ── Reads ───────────────────────────────────────────────────────────────────

def get(user_key: str, dataset_id: str) -> Optional[DatasetIndexEntry]:
    return (
        DatasetIndexEntry.query.filter_by(user_key=user_key, dataset_id=dataset_id)
        .one_or_none()
    )


def get_by_dir(user_key: str, dir_name: str) -> Optional[DatasetIndexEntry]:
    return (
        DatasetIndexEntry.query.filter_by(user_key=user_key, dir_name=dir_name)
        .one_or_none()
    )


def list_for_user(user_key: str) -> list[DatasetIndexEntry]:
    return (
        DatasetIndexEntry.query.filter_by(user_key=user_key)
        .order_by(DatasetIndexEntry.dir_name)
        .all()
    )


def list_dataflow_computed(user_key: str, dataflow_id: str) -> list[DatasetIndexEntry]:
    """Computed rows produced by *dataflow_id*.

    Computed ids are dataflow-namespaced (``computed.<dataflowSeg>.<nodeSeg>``),
    so the owning dataflow is a prefix match — the indexed equivalent of the
    store scan in ``UserDatasetRepository.list_dataflow_computed_items``.
    """
    from utk_curio.backend.app.datasets.install.installer import (
        sanitize_node_id_segment,
    )

    prefix = f"computed.{sanitize_node_id_segment(dataflow_id)}."
    return (
        DatasetIndexEntry.query.filter_by(user_key=user_key, origin="computed")
        .filter(DatasetIndexEntry.dataset_id.startswith(prefix))
        .order_by(DatasetIndexEntry.dir_name)
        .all()
    )


# ── Writes ──────────────────────────────────────────────────────────────────

def upsert_from_dir(user_key: str, dataset_root: Path) -> Optional[DatasetIndexEntry]:
    """Mirror *dataset_root*'s manifest into the index.

    Returns the row, or ``None`` when the dir isn't indexable (not an
    ``imported.``/``computed.`` store dir, or its manifest is missing/invalid —
    the same dirs the listing skips). Commits, so a caller's dataset write is
    already durable by the time the row lands.
    """
    dir_name = dataset_root.name
    origin = origin_for_dir(dir_name)
    if origin is None or not DATASET_DIR_RE.match(dir_name):
        return None
    try:
        manifest = load_dataset_manifest(dataset_root)
    except (ManifestError, OSError, ValueError):
        # Unreadable/mismatched manifest: the catalog treats this dir as absent,
        # so the index must too rather than caching a half-valid row.
        logger.debug("Not indexing unreadable dataset dir %s", dataset_root, exc_info=True)
        return None

    mtime_ns, size = _manifest_stat(dataset_root)
    # Match on dir_name: a dir keeps its identity across a manifest rewrite that
    # changes the id (the legacy computed-id migration does exactly that, and
    # calls forget() for the old dir itself).
    row = get_by_dir(user_key, dir_name)
    if row is None:
        row = DatasetIndexEntry(user_key=user_key)
        db.session.add(row)
    _apply_manifest(
        row, manifest, dir_name=dir_name, origin=origin, mtime_ns=mtime_ns, size=size
    )
    db.session.commit()
    return row


def forget(user_key: str, dir_name: str) -> bool:
    """Drop the row for a store dir that no longer exists. Idempotent."""
    row = get_by_dir(user_key, dir_name)
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def forget_dataset(user_key: str, dataset_id: str) -> bool:
    """Drop the row for a dataset id, whatever dir it points at. Idempotent."""
    row = get(user_key, dataset_id)
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def reconcile_and_rows(user_key: str) -> dict[str, DatasetIndexEntry]:
    """Reconcile, then return the resulting ``{dir_name: row}`` map.

    The read path needs both, and reconcile already loads every row to do its
    comparison — returning that map saves a second identical query per listing.
    """
    rows = _rows_by_dir(user_key)
    _reconcile_into(user_key, rows)
    return rows


def reconcile(user_key: str) -> dict[str, int]:
    """Refresh *user_key*'s index from its store on disk.

    The self-healing backbone: it repairs anything the write-through path missed
    — a failed upsert, a hand-copied dataset dir, a git checkout, a crash between
    the file write and the commit.

    Cheap by design. A dir is re-parsed only when its ``manifest.json`` stat pair
    (mtime_ns, size) differs from the indexed one, so an unchanged store costs
    one readdir plus a stat per dir and **zero** JSON parses. It also commits only
    when something actually changed, which keeps concurrent listings on the
    threaded dev server from contending on SQLite writes.

    Returns ``{"added", "updated", "removed"}`` counts (for tests and logging).
    """
    return _reconcile_into(user_key, _rows_by_dir(user_key))


def _rows_by_dir(user_key: str) -> dict[str, DatasetIndexEntry]:
    return {row.dir_name: row for row in list_for_user(user_key)}


def _reconcile_into(
    user_key: str, rows: dict[str, DatasetIndexEntry]
) -> dict[str, int]:
    """Reconcile against an already-loaded row map, updating it in place.

    Split out so the read path can reconcile and reuse the same rows for its
    listing instead of querying them twice.
    """
    stats = {"added": 0, "updated": 0, "removed": 0}
    seen: set[str] = set()
    changed = False

    for dataset_root in list_user_datasets(user_key):
        dir_name = dataset_root.name
        if origin_for_dir(dir_name) is None:
            continue
        seen.add(dir_name)
        mtime_ns, size = _manifest_stat(dataset_root)
        row = rows.get(dir_name)
        if (
            row is not None
            and mtime_ns is not None
            and row.manifest_mtime_ns == mtime_ns
            and row.manifest_size == size
        ):
            continue  # unchanged — no parse, no write
        try:
            manifest = load_dataset_manifest(dataset_root)
        except (ManifestError, OSError, ValueError):
            logger.debug(
                "Skipping unreadable dataset dir %s during reconcile",
                dataset_root,
                exc_info=True,
            )
            # A dir that became unreadable must not keep a stale row. Drop it
            # from the caller's map too, so a reused map never hands back a row
            # for a dataset the listing now treats as absent.
            if row is not None:
                db.session.delete(row)
                rows.pop(dir_name, None)
                stats["removed"] += 1
                changed = True
            continue
        if row is None:
            row = DatasetIndexEntry(user_key=user_key)
            db.session.add(row)
            rows[dir_name] = row
            stats["added"] += 1
        else:
            stats["updated"] += 1
        _apply_manifest(
            row,
            manifest,
            dir_name=dir_name,
            origin=origin_for_dir(dir_name),
            mtime_ns=mtime_ns,
            size=size,
        )
        changed = True

    for dir_name in list(rows):
        if dir_name not in seen:
            db.session.delete(rows.pop(dir_name))
            stats["removed"] += 1
            changed = True

    if changed:
        db.session.commit()
    return stats


# ── Degrading wrappers (used by write-through and read paths) ───────────────

def safe_upsert_from_dir(user_key: str | None, dataset_root: Path) -> None:
    """:func:`upsert_from_dir`, but never raises and never blocks the caller.

    Used at the dataset write sites: the files are already on disk and the write
    has succeeded by this point, so a DB hiccup must not turn a successful
    install into an error. :func:`reconcile` repairs the missing row later.
    """
    if not user_key:
        return
    try:
        upsert_from_dir(user_key, dataset_root)
    except Exception:  # noqa: BLE001 — indexing must never fail a dataset write
        _rollback()
        logger.warning(
            "Could not index dataset dir %s for %s", dataset_root, user_key,
            exc_info=True,
        )


def safe_forget(user_key: str | None, dir_name: str | None) -> None:
    if not user_key or not dir_name:
        return
    try:
        forget(user_key, dir_name)
    except Exception:  # noqa: BLE001
        _rollback()
        logger.warning(
            "Could not drop dataset index row %s for %s", dir_name, user_key,
            exc_info=True,
        )


def safe_sync_rows_by_dir(user_key: str | None) -> dict[str, DatasetIndexEntry]:
    """Reconcile and return ``{dir_name: row}``, or ``{}`` if unavailable.

    The one call the read paths make: it refreshes the index from disk and hands
    back the rows in a single query. The read paths still enumerate store dirs
    from disk (authoritative and cheap) and use this map only to skip the
    manifest parse, so returning ``{}`` on any failure — including no app context
    at all, as in the repository unit tests — degrades to exactly the pre-index
    behaviour.
    """
    if not user_key:
        return {}
    try:
        return reconcile_and_rows(user_key)
    except Exception:  # noqa: BLE001 — fall back to parsing manifests
        _rollback()
        logger.debug(
            "Dataset index unavailable for %s; reading manifests from disk",
            user_key,
            exc_info=True,
        )
        return {}


def safe_reconcile(user_key: str | None) -> None:
    if not user_key:
        return
    try:
        reconcile(user_key)
    except Exception:  # noqa: BLE001 — a listing must survive a bad index
        _rollback()
        logger.warning(
            "Dataset index reconcile failed for %s; serving from disk", user_key,
            exc_info=True,
        )


def _rollback() -> None:
    """Clear a failed session so the caller's own DB work isn't poisoned."""
    try:
        db.session.rollback()
    except Exception:  # noqa: BLE001
        logger.debug("Dataset index session rollback failed", exc_info=True)
