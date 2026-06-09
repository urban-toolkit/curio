"""Public facade for the dataset catalog service layer.

The implementation lives in the ``services`` subpackage. This module is the
single stable entry point: import the service API from here rather than from the
internal ``services.*`` modules.
"""

from __future__ import annotations

from utk_curio.backend.app.datasets.services.service import (
    ComputedDatasetIndexer,
    DatasetCatalogError,
    DatasetCatalogService,
    DatasetPreviewService,
    DatasetRegistryRepository,
    InstalledDatasetRepository,
    LocalDatasetRepository,
    _computed_output_format,
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
