"""Dataset catalog service facade.

Coordinates the read-side (:class:`CatalogListing`) and write-side
(:class:`CatalogMutations`) operations over a shared set of collaborators
(repositories, computed indexer, preview service, and :class:`PathResolver`).
Composition — not mixins — so each collaborator owns its own state and the
public method surface stays explicit and overridable.
"""

from __future__ import annotations

from typing import Any

from utk_curio.backend.app.datasets.application.listing import CatalogListing
from utk_curio.backend.app.datasets.application.mutations import CatalogMutations
from utk_curio.backend.app.datasets.application.paths import PathResolver
from utk_curio.backend.app.datasets.application.preview import DatasetPreviewService
from utk_curio.backend.app.datasets.domain.computed import ComputedDatasetIndexer
from utk_curio.backend.app.datasets.repositories.installed import InstalledDatasetRepository
from utk_curio.backend.app.datasets.repositories.local import LocalDatasetRepository
from utk_curio.backend.app.datasets.repositories.registry import DatasetRegistryRepository
from utk_curio.backend.app.datasets.repositories.user_store import UserDatasetRepository


class DatasetCatalogService:
    def __init__(self, user: Any | None = None):
        self.user = user
        self.registry = DatasetRegistryRepository()
        self.local = LocalDatasetRepository()
        self.installed = InstalledDatasetRepository(user)
        self.user_store = UserDatasetRepository(user)
        self.computed = ComputedDatasetIndexer()
        self.preview_service = DatasetPreviewService()

        self._paths = PathResolver(
            user=user, registry=self.registry, installed=self.installed
        )
        self._listing = CatalogListing(
            user=user,
            registry=self.registry,
            local=self.local,
            installed=self.installed,
            user_store=self.user_store,
            computed=self.computed,
            preview_service=self.preview_service,
            paths=self._paths,
            owner=self,
        )
        self._mutations = CatalogMutations(
            user=user,
            installed=self.installed,
            paths=self._paths,
            owner=self,
        )

    # ── Read-side (delegates to CatalogListing) ────────────────────────────
    def list_catalog(self, *args: Any, **kwargs: Any) -> Any:
        return self._listing.list_catalog(*args, **kwargs)

    def get_dataset(self, *args: Any, **kwargs: Any) -> Any:
        return self._listing.get_dataset(*args, **kwargs)

    def resolve_dataset_producer(self, *args: Any, **kwargs: Any) -> Any:
        return self._listing.resolve_dataset_producer(*args, **kwargs)

    def resolve_execution_paths(self, *args: Any, **kwargs: Any) -> Any:
        return self._listing.resolve_execution_paths(*args, **kwargs)

    def preview(self, *args: Any, **kwargs: Any) -> Any:
        return self._listing.preview(*args, **kwargs)

    def download_target(self, *args: Any, **kwargs: Any) -> Any:
        return self._listing.download_target(*args, **kwargs)

    def dataset_usage(self, *args: Any, **kwargs: Any) -> Any:
        return self._listing.dataset_usage(*args, **kwargs)

    # ── Write-side (delegates to CatalogMutations) ─────────────────────────
    def import_dataset(self, *args: Any, **kwargs: Any) -> Any:
        return self._mutations.import_dataset(*args, **kwargs)

    def publish_dataset(self, *args: Any, **kwargs: Any) -> Any:
        return self._mutations.publish_dataset(*args, **kwargs)

    def install_dataset(self, *args: Any, **kwargs: Any) -> Any:
        return self._mutations.install_dataset(*args, **kwargs)

    def uninstall_dataset(self, *args: Any, **kwargs: Any) -> Any:
        return self._mutations.uninstall_dataset(*args, **kwargs)

    def install_dataset_to_defaults(self, *args: Any, **kwargs: Any) -> Any:
        return self._mutations.install_dataset_to_defaults(*args, **kwargs)

    def remove_dataset_from_defaults(self, *args: Any, **kwargs: Any) -> Any:
        return self._mutations.remove_dataset_from_defaults(*args, **kwargs)

    def unpublish_dataset(self, *args: Any, **kwargs: Any) -> Any:
        return self._mutations.unpublish_dataset(*args, **kwargs)

    def delete_dataset(self, *args: Any, **kwargs: Any) -> Any:
        return self._mutations.delete_dataset(*args, **kwargs)
