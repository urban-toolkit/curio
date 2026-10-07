"""Hub registry-backed dataset repository."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from utk_curio.backend.app.datasets.domain.catalog_item import item_from_manifest


def _left_out_size(dir_name: str, data_file: str) -> int | None:
    """The size of a shipped data file the pip package leaves out, as its
    release recorded it, so the catalog gives it before the file is
    downloaded (``infrastructure/left_out_files.py``)."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    return left_out_files.recorded_size(f"datasets/{dir_name}/{data_file}")


class DatasetRegistryRepository:
    """Manifest-backed Data Catalog at ``<repo_root>/datasets/``.

    Instances are request-scoped (one per ``DatasetCatalogService``), so the
    ``id -> dir`` index is memoized for the life of the request — turning the
    historical O(N) manifest scan *per id lookup* into a single scan shared with
    ``list_items``.
    """

    def __init__(self) -> None:
        self._dir_index: dict[str, Path] | None = None

    def _iter_manifests(self) -> Iterator[tuple[Any, Path]]:
        from utk_curio.backend.app.datasets.domain.manifest import ManifestError, load_dataset_manifest_from_dir
        from utk_curio.backend.app.datasets.infrastructure.storage import list_catalog_datasets

        for dataset_root in list_catalog_datasets():
            try:
                manifest = load_dataset_manifest_from_dir(dataset_root)
            except ManifestError:
                continue
            yield manifest, dataset_root

    def list_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        index: dict[str, Path] = {}
        for manifest, dataset_root in self._iter_manifests():
            item = item_from_manifest(manifest, dataset_root)
            if item.get("sizeBytes") is None:
                item["sizeBytes"] = _left_out_size(dataset_root.name, manifest.data_file)
            items.append(item)
            index[manifest.id] = dataset_root
        # Reuse this scan for subsequent get_catalog_dir lookups in the request.
        self._dir_index = index
        return items

    def _catalog_dir_index(self) -> dict[str, Path]:
        if self._dir_index is None:
            self._dir_index = {manifest.id: root for manifest, root in self._iter_manifests()}
        return self._dir_index

    def get_catalog_dir(self, dataset_id: str) -> Path | None:
        return self._catalog_dir_index().get(dataset_id)
