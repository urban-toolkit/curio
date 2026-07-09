"""Account-level user dataset store repository.

The user store (``.curio/users/<user_key>/datasets/``) holds every dataset a
user has registered, independent of any project. This repository lists the
**imported** datasets there as standalone, account-level catalog items so a
registered import stays visible in the Data Catalog even when no project
references it.

Computed node-output copies (``computed.*`` dirs) are deliberately **not**
listed here: they are surfaced per-project through
:class:`InstalledDatasetRepository` and the computed indexer, and their
auto-install behavior must stay unchanged. Listing them from the account store
too would double-source them and could show a node's output as a standalone
item in a dataflow that never produced it.
"""

from __future__ import annotations

import logging
from typing import Any

from utk_curio.backend.app.datasets.domain.catalog_item import item_from_manifest

logger = logging.getLogger(__name__)

# User-store dir prefix for imported (register-only) datasets. Mirrors the
# ``imported.x<hash>`` id minted by ``install_imported_file``.
_IMPORTED_DIR_PREFIX = "imported."


class UserDatasetRepository:
    """Lists account-level *imported* datasets from the user store."""

    def __init__(self, user: Any | None):
        self.user = user

    def list_items(self) -> list[dict[str, Any]]:
        if self.user is None:
            return []
        from utk_curio.backend.app.datasets.domain.manifest import (
            ManifestError,
            load_dataset_manifest,
        )
        from utk_curio.backend.app.datasets.infrastructure.storage import (
            list_user_datasets,
        )
        from utk_curio.backend.app.projects.services import _user_dir_key

        user_key = _user_dir_key(self.user)
        items: list[dict[str, Any]] = []
        for dataset_root in list_user_datasets(user_key):
            # Account-level tier is imported datasets only; computed node-output
            # copies keep their existing per-project path (see module docstring).
            if not dataset_root.name.startswith(_IMPORTED_DIR_PREFIX):
                continue
            try:
                manifest = load_dataset_manifest(dataset_root)
            except (ManifestError, OSError, ValueError):
                # Best-effort: a malformed/partial dir must not fail the listing.
                logger.debug(
                    "Skipping unreadable user-store dataset dir %s",
                    dataset_root,
                    exc_info=True,
                )
                continue
            items.append(item_from_manifest(manifest, dataset_root, origin="imported"))
        return items
