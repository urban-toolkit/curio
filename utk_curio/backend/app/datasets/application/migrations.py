"""One-time, idempotent migrations for the per-user dataset store.

Currently: rename legacy un-namespaced computed datasets
(``computed.<node>@N``) to the dataflow-namespaced form
(``computed.<dataflow>.<node>@N``) introduced so the same node id reused in two
dataflows no longer collides on one account-store folder.

The migration is *best-effort*: a legacy dir it cannot confidently attribute to
a single producing dataflow is left as-is. The id parsers tolerate both forms,
so an un-migrated legacy dir keeps working.

Hardening (#171): the run-once guard is a lock + double-checked in-process set +
a filesystem marker written only after a fully-successful run with no legacy
dirs left, so a failed or partial run is retried instead of silently frozen.
Each dir move is crash-safe: the updated manifest is staged as a sidecar inside
the source dir, the dir is renamed atomically (``os.rename`` refuses an
existing destination), and the manifest is swapped atomically — every crash
window leaves either an intact legacy dir or a destination the next run
self-heals.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from utk_curio.backend.app.datasets.domain.manifest import (
    ManifestError,
    build_manifest_dict,
    load_dataset_manifest_from_dir,
)
from utk_curio.backend.app.datasets.infrastructure.storage import (
    dataset_dir,
    list_user_datasets,
    user_datasets_dir,
)
from utk_curio.backend.app.datasets.install.installer import (
    computed_dataset_id,
    node_segment_from_computed_id,
    sanitize_node_id_segment,
)

logger = logging.getLogger(__name__)

# Per-process guard so the migration runs at most once per user per process
# (the account-level listing calls it before surfacing computed datasets).
# Entries are added only AFTER an attempt completes without raising, so a
# failed run is retried on the next listing.
_migrated_users: set[str] = set()

# Serializes concurrent first-listings (the dev server runs threaded=True) so
# two threads never race the same user's rename sequence.
_migration_lock = threading.Lock()

# Marker file inside the user's dataset store recording that a run completed
# with no legacy dirs left. Invisible to ``list_user_datasets`` (not a dir) and
# fails ``DATASET_DIR_RE``, so it can never be mistaken for a dataset.
_MARKER_NAME = ".computed-ids-migrated"

# Staged updated manifest, written inside the SOURCE dir before the rename.
_MANIFEST_SIDECAR = "manifest.json.migrated"


def _marker_path(user_key: str) -> Path:
    return user_datasets_dir(user_key) / _MARKER_NAME


def ensure_computed_ids_migrated(user_key: str) -> None:
    """Run :func:`migrate_computed_dataset_ids` once for *user_key*.

    Best-effort: a migration error must never block a catalog listing — but it
    also must not be recorded as done, so the next listing retries it.
    """
    if user_key in _migrated_users:
        return
    with _migration_lock:
        if user_key in _migrated_users:
            return
        if _marker_path(user_key).is_file():
            _migrated_users.add(user_key)
            return
        try:
            migrate_computed_dataset_ids(user_key)
        except Exception:  # noqa: BLE001 — listing must survive a migration hiccup
            logger.warning(
                "Computed-id migration failed for %s; it will be retried on the "
                "next catalog listing",
                user_key,
                exc_info=True,
            )
            return
        # One attempt per process even when unattributable legacy dirs remain…
        _migrated_users.add(user_key)
        # …but only a store with NO legacy dirs left is marked done on disk, so
        # a future process re-attempts dirs whose owning dataflow appears later.
        if not _has_unmigrated_legacy_dirs(user_key):
            try:
                marker = _marker_path(user_key)
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("computed-id migration completed\n", encoding="utf-8")
            except OSError:
                logger.debug(
                    "Could not write migration marker for %s", user_key, exc_info=True
                )


def _has_unmigrated_legacy_dirs(user_key: str) -> bool:
    return any(
        _is_legacy_computed_id(root.name.rsplit("@", 1)[0])
        for root in list_user_datasets(user_key)
    )


def _is_legacy_computed_id(dataset_id: str) -> bool:
    """True for an un-namespaced computed id (``computed.<node>`` — one dotted
    segment after the prefix). The namespaced form has two."""
    if not dataset_id.startswith("computed."):
        return False
    rest = dataset_id[len("computed.") :]
    return "." not in rest


def _owning_dataflow_for(
    user_key: str, legacy_id: str, node_seg: str
) -> tuple[Optional[str], Optional[str]]:
    """Resolve the (dataflow_id, real_node_id) that produced *legacy_id*.

    Prefers an explicit ``dataflow.datasets`` ref (unambiguous). Falls back to a
    node-segment match only when exactly one of the user's dataflows contains a
    matching node. Returns ``(None, None)`` when it can't be placed confidently.
    """
    from utk_curio.backend.app.projects import storage as project_storage

    ref_match: Optional[str] = None
    node_matches: list[tuple[str, str]] = []  # (dataflow_id, node_id)

    for project_id in project_storage.list_project_ids(user_key):
        try:
            spec = project_storage.read_spec(user_key, project_id)
        except Exception:  # noqa: BLE001 — a bad spec must not abort the migration
            continue
        if not isinstance(spec, dict):
            continue
        dataflow = spec.get("dataflow")
        if not isinstance(dataflow, dict):
            continue

        for ref in dataflow.get("datasets") or []:
            if isinstance(ref, dict) and legacy_id in (ref.get("datasetId"), ref.get("id")):
                ref_match = project_id
                break

        for node in dataflow.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            nid = node.get("id")
            if nid and sanitize_node_id_segment(nid) == node_seg:
                node_matches.append((project_id, nid))

        if ref_match:
            # Recover the real node id in the owning dataflow if present.
            real = next((n for (p, n) in node_matches if p == ref_match), None)
            return ref_match, real

    if len(node_matches) == 1:
        return node_matches[0][0], node_matches[0][1]
    return None, None


def _rewrite_spec_ref(
    user_key: str, dataflow_id: str, old_id: str, new_id: str, new_dir_name: str
) -> None:
    """Point a project's computed ref at the renamed dataset (id + dirName)."""
    from utk_curio.backend.app.projects import storage as project_storage

    with project_storage.spec_write_lock(user_key, dataflow_id):
        spec = project_storage.read_spec(user_key, dataflow_id)
        if not isinstance(spec, dict):
            return
        dataflow = spec.get("dataflow")
        if not isinstance(dataflow, dict):
            return
        changed = False
        for ref in dataflow.get("datasets") or []:
            if not isinstance(ref, dict):
                continue
            if old_id in (ref.get("datasetId"), ref.get("id")):
                ref["datasetId"] = new_id
                ref["dirName"] = new_dir_name
                changed = True
        if changed:
            project_storage.write_spec(user_key, dataflow_id, spec)


def _self_heal_crashed_migration(user_key: str, dataset_root: Path) -> bool:
    """Finish (or unwind) a migration interrupted between its atomic steps.

    A ``manifest.json.migrated`` sidecar inside a NAMESPACED dir means the
    rename happened but the manifest swap didn't — complete the swap and re-run
    the (idempotent) spec-ref rewrite. A sidecar inside a still-LEGACY dir means
    the crash happened before the rename — discard it so the normal flow redoes
    the migration from scratch. Returns True when a crashed migration was
    completed here.
    """
    sidecar = dataset_root / _MANIFEST_SIDECAR
    if not sidecar.is_file():
        return False
    base_id = dataset_root.name.rsplit("@", 1)[0]
    if _is_legacy_computed_id(base_id):
        try:
            sidecar.unlink()
        except OSError:
            logger.debug("Could not remove stale sidecar in %s", dataset_root.name, exc_info=True)
        return False
    try:
        os.replace(sidecar, dataset_root / "manifest.json")
    except OSError:
        logger.warning(
            "Could not complete crashed migration of %s", dataset_root.name, exc_info=True
        )
        return False
    try:
        manifest = load_dataset_manifest_from_dir(dataset_root)
        node_seg = node_segment_from_computed_id(manifest.id)
        if manifest.producer_dataflow_id and node_seg:
            _rewrite_spec_ref(
                user_key,
                manifest.producer_dataflow_id,
                f"computed.{node_seg}",
                manifest.id,
                dataset_root.name,
            )
    except Exception:  # noqa: BLE001 — the dir itself is healed; refs are best-effort
        logger.warning(
            "Healed %s but could not rewrite its spec ref", dataset_root.name, exc_info=True
        )
    return True


def migrate_computed_dataset_ids(user_key: str) -> int:
    """Rename legacy computed dirs for *user_key* to the namespaced form.

    Idempotent: already-namespaced dirs are skipped, and a re-run finds nothing
    to do. Returns the number of datasets migrated (including crashed runs
    completed by self-healing).
    """
    migrated = 0
    for dataset_root in list_user_datasets(user_key):
        if _self_heal_crashed_migration(user_key, dataset_root):
            migrated += 1
            continue

        dir_name = dataset_root.name
        base_id = dir_name.rsplit("@", 1)[0]
        if not _is_legacy_computed_id(base_id):
            continue
        node_seg = node_segment_from_computed_id(base_id)
        if not node_seg:
            continue

        # Load the manifest FIRST: its major keys the destination name, and an
        # unreadable manifest must skip before anything on disk is touched.
        try:
            manifest = load_dataset_manifest_from_dir(dataset_root)
        except (ManifestError, OSError, ValueError):
            logger.debug("Unreadable manifest in %s; skipping migration", dir_name, exc_info=True)
            continue

        dataflow_id, real_node_id = _owning_dataflow_for(user_key, base_id, node_seg)
        if not dataflow_id:
            logger.debug(
                "Skipping legacy computed dir %s: no single owning dataflow", dir_name
            )
            continue

        new_id = computed_dataset_id(real_node_id or node_seg, dataflow_id)
        if new_id == base_id:
            continue
        new_dir_name = f"{new_id}@{manifest.major}"
        dest = dataset_dir(user_key, new_dir_name)
        if dest.exists():
            # A namespaced copy already exists — leave the legacy dir untouched
            # rather than clobber it; a later delete can clean the duplicate.
            logger.debug("Namespaced dir %s already exists; skipping %s", new_dir_name, dir_name)
            continue

        # Crash-safe sequence: (1) stage the updated manifest as a sidecar in
        # the SOURCE dir, (2) rename the dir atomically — ``os.rename`` fails if
        # the destination appeared concurrently, so it can never nest or
        # overwrite a fresh dir — then (3) swap the manifest atomically.
        updated = dataclasses.replace(
            manifest,
            id=new_id,
            producer_dataflow_id=dataflow_id,
            producer_node_id=real_node_id or manifest.producer_node_id,
        )
        sidecar = dataset_root / _MANIFEST_SIDECAR
        try:
            sidecar.write_text(
                json.dumps(build_manifest_dict(updated), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.rename(dataset_root, dest)
        except OSError:
            logger.warning("Could not rename %s → %s", dir_name, new_dir_name, exc_info=True)
            try:
                if sidecar.is_file():
                    sidecar.unlink()
            except OSError:
                pass
            continue

        try:
            os.replace(dest / _MANIFEST_SIDECAR, dest / "manifest.json")
        except OSError:
            # The strict loader rejects the dir until the swap completes — the
            # next run's self-heal finishes it.
            logger.warning(
                "Renamed %s but could not swap its manifest; will self-heal on the next run",
                new_dir_name, exc_info=True,
            )

        try:
            _rewrite_spec_ref(user_key, dataflow_id, base_id, new_id, new_dir_name)
        except Exception:  # noqa: BLE001 — dir is renamed; ref rewrite is best-effort
            logger.warning(
                "Renamed %s but failed to rewrite its spec ref in %s",
                dir_name, dataflow_id, exc_info=True,
            )

        migrated += 1

    return migrated
