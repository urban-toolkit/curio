"""Dataset catalog service — public facade and backward-compatible imports.

Implementation is split across focused modules; import from here for stable API.
"""

from __future__ import annotations

from utk_curio.backend.app.datasets.catalog_service import DatasetCatalogService
from utk_curio.backend.app.datasets.computed_indexer import ComputedDatasetIndexer
from utk_curio.backend.app.datasets.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.installed_repository import InstalledDatasetRepository
from utk_curio.backend.app.datasets.local_repository import LocalDatasetRepository
from utk_curio.backend.app.datasets.preview_service import DatasetPreviewService
from utk_curio.backend.app.datasets.registry_repository import DatasetRegistryRepository

# Private helpers kept for tests and bundle.py that imported from service.
from utk_curio.backend.app.datasets.provenance import computed_output_format as _computed_output_format

__all__ = [
    "ComputedDatasetIndexer",
    "DatasetCatalogError",
    "DatasetCatalogService",
    "DatasetPreviewService",
    "DatasetRegistryRepository",
    "InstalledDatasetRepository",
    "LocalDatasetRepository",
    "_computed_output_format",
]
