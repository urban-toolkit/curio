"""Public facade for the dataset catalog service layer.

The implementation lives in the layered subpackages (``application``,
``repositories``, ``domain``). This module is the single stable entry point:
external callers import the service API from here rather than from the internal
layer modules.
"""

from __future__ import annotations

from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService
from utk_curio.backend.app.datasets.application.preview import DatasetPreviewService
from utk_curio.backend.app.datasets.domain.computed import ComputedDatasetIndexer
from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.repositories.installed import InstalledDatasetRepository
from utk_curio.backend.app.datasets.repositories.local import LocalDatasetRepository
from utk_curio.backend.app.datasets.repositories.registry import DatasetRegistryRepository

# Private helper kept for tests (imported here as the stable ``service`` entry point).
from utk_curio.backend.app.datasets.domain.provenance import (
    computed_output_format as _computed_output_format,
)

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
