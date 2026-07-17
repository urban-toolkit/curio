"""One-time, idempotent migrations for the per-user dataset store.

Currently: rename legacy un-namespaced computed datasets
(``computed.<node>@1``) to the dataflow-namespaced form
(``computed.<dataflow>.<node>@1``) introduced so the same node id reused in two
dataflows no longer collides on one account-store folder.

The migration is *best-effort*: a legacy dir it cannot confidently attribute to
a single producing dataflow is left as-is. The id parsers tolerate both forms,
so an un-migrated legacy dir keeps working.
"""

from __future__ import annotations

import json
import logging
import shutil
from typing import Optional

from utk_curio.backend.app.datasets.domain.manifest import (
    ManifestError,
    build_manifest_dict,
    load_dataset_manifest_from_dir,
)
from utk_curio.backend.app.datasets.infrastructure.storage import (
    dataset_dir,
    list_user_datasets,
)
from utk_curio.backend.app.datasets.install.installer import (
    computed_dataset_id,
    node_segment_from_computed_id,
    sanitize_node_id_segment,
)

logger = logging.getLogger(__name__)

# Per-process guard so the migration runs at most once per user per process
# (the account-level listing calls it before surfacing computed datasets).
_migrated_users: set[str] = set()


def ensure_computed_ids_migrated(user_key: str) -> None:
    """Run :func:`migrate_computed_dataset_ids` once per process for *user_key*.

    Best-effort: a migration error must never block a catalog listing.
    """
    if user_key in _migrated_users:
        return
    _migrated_users.add(user_key)
    try:
        migrate_computed_dataset_ids(user_key)
    except Exception:  # noqa: BLE001 — listing must survive a migration hiccup
        logger.warning("Computed-id migration failed for %s", user_key, exc_info=True)


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


def _rewrite_spec_ref(user_key: str, dataflow_id: str, old_id: str, new_id: str) -> None:
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
                ref["dirName"] = f"{new_id}@1"
                changed = True
        if changed:
            project_storage.write_spec(user_key, dataflow_id, spec)


def migrate_computed_dataset_ids(user_key: str) -> int:
    """Rename legacy computed dirs for *user_key* to the namespaced form.

    Idempotent: already-namespaced dirs are skipped, and a re-run finds nothing
    to do. Returns the number of datasets migrated.
    """
    migrated = 0
    for dataset_root in list_user_datasets(user_key):
        dir_name = dataset_root.name
        base_id = dir_name.rsplit("@", 1)[0]
        if not _is_legacy_computed_id(base_id):
            continue
        node_seg = node_segment_from_computed_id(base_id)
        if not node_seg:
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
        new_dir_name = f"{new_id}@1"
        dest = dataset_dir(user_key, new_dir_name)
        if dest.exists():
            # A namespaced copy already exists — leave the legacy dir untouched
            # rather than clobber it; a later delete can clean the duplicate.
            logger.debug("Namespaced dir %s already exists; skipping %s", new_dir_name, dir_name)
            continue

        try:
            manifest = load_dataset_manifest_from_dir(dataset_root)
        except (ManifestError, OSError, ValueError):
            logger.debug("Unreadable manifest in %s; skipping migration", dir_name, exc_info=True)
            continue

        # Rename the folder, then rewrite the manifest id + lineage in place.
        try:
            shutil.move(str(dataset_root), str(dest))
        except OSError:
            logger.warning("Could not rename %s → %s", dir_name, new_dir_name, exc_info=True)
            continue

        raw = build_manifest_dict(manifest)
        raw["id"] = new_id
        raw["producerDataflowId"] = dataflow_id
        if real_node_id:
            raw["producerNodeId"] = real_node_id
        (dest / "manifest.json").write_text(
            json.dumps(raw, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        try:
            _rewrite_spec_ref(user_key, dataflow_id, base_id, new_id)
        except Exception:  # noqa: BLE001 — dir is renamed; ref rewrite is best-effort
            logger.warning(
                "Renamed %s but failed to rewrite its spec ref in %s",
                dir_name, dataflow_id, exc_info=True,
            )

        migrated += 1

    return migrated
