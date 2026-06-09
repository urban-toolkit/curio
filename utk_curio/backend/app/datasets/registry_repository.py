"""Hub registry-backed dataset repository."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.catalog_items import item_from_manifest

class DatasetRegistryRepository:
    """Manifest-backed Data Catalog at ``<repo_root>/datasets/``."""

    def list_items(self) -> list[dict[str, Any]]:
        from utk_curio.backend.app.datasets.manifest import ManifestError, load_dataset_manifest_from_dir
        from utk_curio.backend.app.datasets.storage import list_catalog_datasets

        items: list[dict[str, Any]] = []
        for dataset_root in list_catalog_datasets():
            try:
                manifest = load_dataset_manifest_from_dir(dataset_root)
            except ManifestError:
                continue
            items.append(item_from_manifest(manifest, dataset_root))
        return items

    def get_catalog_dir(self, dataset_id: str) -> Path | None:
        from utk_curio.backend.app.datasets.manifest import ManifestError, load_dataset_manifest_from_dir
        from utk_curio.backend.app.datasets.storage import list_catalog_datasets

        for dataset_root in list_catalog_datasets():
            try:
                manifest = load_dataset_manifest_from_dir(dataset_root)
            except ManifestError:
                continue
            if manifest.id == dataset_id:
                return dataset_root
        return None
