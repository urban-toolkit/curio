"""Dataset catalog service facade."""

from __future__ import annotations

from typing import Any

from utk_curio.backend.app.datasets.services.catalog_listing import CatalogListingMixin
from utk_curio.backend.app.datasets.services.catalog_mutations import CatalogMutationsMixin
from utk_curio.backend.app.datasets.computed_indexer import ComputedDatasetIndexer
from utk_curio.backend.app.datasets.installed_repository import InstalledDatasetRepository
from utk_curio.backend.app.datasets.local_repository import LocalDatasetRepository
from utk_curio.backend.app.datasets.services.preview_service import DatasetPreviewService
from utk_curio.backend.app.datasets.registry_repository import DatasetRegistryRepository


class DatasetCatalogService(CatalogListingMixin, CatalogMutationsMixin):
    def __init__(self, user: Any | None = None):
        self.user = user
        self.registry = DatasetRegistryRepository()
        self.local = LocalDatasetRepository()
        self.installed = InstalledDatasetRepository(user)
        self.computed = ComputedDatasetIndexer()
        self.preview_service = DatasetPreviewService()

    def legacy_dataset_paths(self) -> list[str]:
        """Return paths for backwards-compatible /datasets route."""
        items = self.registry.list_items()
        return [item["path"] for item in items if item.get("path")]
