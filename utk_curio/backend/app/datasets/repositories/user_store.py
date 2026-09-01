"""Account-level user dataset store repository.

The user store (``.curio/users/<user_key>/datasets/``) holds every dataset a
user has registered, independent of any project. This repository lists both
tiers as standalone, account-level catalog items so they stay visible in the
Data Catalog even when no project references them:

* **imported** (``imported.*``) — register-only uploads;
* **computed** (``computed.*``) — node outputs saved to the account catalog.

Computed node outputs are now account-level assets by default: generating one
saves it here (never auto-installed into a project, never auto-published). The
id is dataflow-namespaced (``computed.<dataflowId>.<nodeId>``) so the same node
id reused in two dataflows lists as two distinct datasets. Each carries its
producer/upstream lineage from the manifest, so it stays connected to the
workflow and source node without a project reference. A computed dataset that
IS installed in the open dataflow also appears via the installed repository and
the computed indexer; ``dedupe_items`` merges the rows by id (the richer
account/installed row wins, and installed-marking flips ``installed=True``).
"""

from __future__ import annotations

import logging
from typing import Any

from utk_curio.backend.app.datasets.domain.catalog_item import item_from_manifest
from utk_curio.backend.app.datasets.repositories import index as index_repo

logger = logging.getLogger(__name__)


def _manifest_for(dataset_root: Any, row: Any) -> Any:
    """Manifest for a store dir — from its index row when available, else parsed.

    Store dirs are always enumerated from disk, so the listing is authoritative
    regardless of index state; the row only saves the JSON parse (the part that
    made every listing O(manifests)). Returns ``None`` for a dir whose manifest
    can't be read, which the callers skip exactly as before.
    """
    if row is not None:
        return index_repo.manifest_from_row(row)
    from utk_curio.backend.app.datasets.domain.manifest import (
        ManifestError,
        load_dataset_manifest,
    )

    try:
        return load_dataset_manifest(dataset_root)
    except (ManifestError, OSError, ValueError):
        # Best-effort: a malformed/partial dir must not fail the listing.
        logger.debug(
            "Skipping unreadable user-store dataset dir %s", dataset_root, exc_info=True
        )
        return None

# User-store dir prefixes. ``imported.x<hash>`` from ``install_imported_file``;
# ``computed.<dataflow>.<node>`` from the computed installers.
_IMPORTED_DIR_PREFIX = "imported."
_COMPUTED_DIR_PREFIX = "computed."


class UserDatasetRepository:
    """Lists account-level *imported* and *computed* datasets from the user store."""

    def __init__(self, user: Any | None):
        self.user = user

    def list_items(self) -> list[dict[str, Any]]:
        if self.user is None:
            return []
        from utk_curio.backend.app.datasets.infrastructure.storage import (
            list_user_datasets,
        )
        from utk_curio.backend.app.datasets.application.migrations import (
            ensure_computed_ids_migrated,
        )
        from utk_curio.backend.app.projects.services import _user_dir_key

        user_key = _user_dir_key(self.user)
        # Namespace any legacy computed dirs before surfacing them so the account
        # id matches the dataflow-scoped indexer/installed id (dedupe by id).
        # Runs BEFORE the index sync: it renames dirs on disk, and the index
        # mirrors dirs.
        ensure_computed_ids_migrated(user_key)
        rows = index_repo.safe_sync_rows_by_dir(user_key)

        items: list[dict[str, Any]] = []
        for dataset_root in list_user_datasets(user_key):
            name = dataset_root.name
            if name.startswith(_IMPORTED_DIR_PREFIX):
                origin = "imported"
            elif name.startswith(_COMPUTED_DIR_PREFIX):
                origin = "computed"
            else:
                continue
            manifest = _manifest_for(dataset_root, rows.get(name))
            if manifest is None:
                continue
            items.append(item_from_manifest(manifest, dataset_root, origin=origin))
        return items

    def list_dataflow_computed_items(self, dataflow_id: str) -> list[dict[str, Any]]:
        """Account-store computed datasets produced by *dataflow_id*.

        The computed id is dataflow-namespaced (``computed.<dataflowId>.<node>``),
        so a dataflow's own outputs are matched by id prefix and surfaced in its
        scoped catalog with full store metadata + lineage — even with no project
        ref and before any save (e.g. immediately after node execution).
        """
        if self.user is None or not dataflow_id:
            return []
        from utk_curio.backend.app.datasets.infrastructure.storage import (
            list_user_datasets,
        )
        from utk_curio.backend.app.datasets.application.migrations import (
            ensure_computed_ids_migrated,
        )
        from utk_curio.backend.app.datasets.install.installer import (
            sanitize_node_id_segment,
        )
        from utk_curio.backend.app.projects.services import _user_dir_key

        user_key = _user_dir_key(self.user)
        ensure_computed_ids_migrated(user_key)
        rows = index_repo.safe_sync_rows_by_dir(user_key)
        prefix = f"{_COMPUTED_DIR_PREFIX}{sanitize_node_id_segment(dataflow_id)}."
        items: list[dict[str, Any]] = []
        for dataset_root in list_user_datasets(user_key):
            if not dataset_root.name.startswith(prefix):
                continue
            manifest = _manifest_for(dataset_root, rows.get(dataset_root.name))
            if manifest is None:
                continue
            items.append(item_from_manifest(manifest, dataset_root, origin="computed"))
        return items
