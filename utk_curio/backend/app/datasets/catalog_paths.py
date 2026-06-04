"""Path resolution for catalog items (computed outputs, user store, hub)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.catalog_items import loader_snippet
from utk_curio.backend.app.datasets.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.installed_repository import InstalledDatasetRepository
from utk_curio.backend.app.datasets.registry_repository import DatasetRegistryRepository


class CatalogPathMixin:
    """Requires ``user``, ``registry``, and ``installed`` on the host service."""

    user: Any | None
    registry: DatasetRegistryRepository
    installed: InstalledDatasetRepository

    def _user_key(self) -> str:
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects.services import _user_dir_key

        return _user_dir_key(self.user)

    def _resolve_computed_output_path(self, item: dict[str, Any]) -> str | None:
        """Resolve a ``curio://outputs/{filename}`` URI to an absolute filesystem path.

        Computed datasets live in the shared-data directory written by node
        execution.  This helper maps the virtual URI to the real file so that
        preview and install can both work without any special-casing at call
        sites.

        Falls back to checking the ``artifacts/`` subdirectory for legacy
        DuckDB artifact IDs (bare name, no extension) that were stored in
        project specs before the named-parquet dataset system was introduced.
        """
        uri = item.get("uri") or ""
        if not uri.startswith("curio://outputs/"):
            return None
        filename = uri[len("curio://outputs/"):]
        if not filename:
            return None
        from utk_curio.backend.app.datasets.output_paths import resolve_shared_output_path

        resolved = resolve_shared_output_path(filename)
        return resolved.as_posix() if resolved is not None else None

    def _mark_user_store_computed_installs(
        self,
        items: list[dict[str, Any]],
        user_key: str,
        installed_computed_filenames: dict[str, str],
    ) -> None:
        """Mark computed rows installed when ``computed.<node>@1`` exists on disk."""
        from utk_curio.backend.app.datasets.installer import (
            InstallerError,
            resolve_installed_data_path,
            sanitize_node_id_segment,
        )
        from utk_curio.backend.app.datasets.manifest import ManifestError, load_dataset_manifest
        from utk_curio.backend.app.datasets.storage import dataset_dir

        for item in items:
            if item.get("origin") != "computed":
                continue
            producer = item.get("producerNodeId")
            if not producer:
                continue

            dir_name = f"computed.{sanitize_node_id_segment(producer)}@1"
            try:
                installed_dir = dataset_dir(user_key, dir_name)
                manifest = load_dataset_manifest(installed_dir)
                data_path = resolve_installed_data_path(user_key, manifest)
            except (InstallerError, ManifestError, OSError, ValueError):
                continue

            live_name = ""
            uri = item.get("uri") or ""
            if uri.startswith("curio://outputs/"):
                live_name = Path(uri[len("curio://outputs/"):]).name

            item["installed"] = True
            item["dirName"] = dir_name
            item["path"] = data_path.as_posix()
            item["uri"] = f"curio://datasets/{dir_name}"
            item["loaderSnippet"] = loader_snippet(item["format"], data_path.as_posix())
            if live_name and live_name != data_path.name:
                item["needsReinstall"] = True
            elif producer in installed_computed_filenames:
                installed_name = installed_computed_filenames[producer]
                if live_name and installed_name and live_name != installed_name:
                    item["needsReinstall"] = True

    def _resolve_item_path(self, item: dict[str, Any]) -> str | None:
        # ── Computed datasets must be resolved via the shared-data directory
        # first, regardless of what the ``path`` field says (it is just the
        # bare filename, not an absolute path).
        if item.get("origin") == "computed":
            resolved = self._resolve_computed_output_path(item)
            if resolved:
                return resolved
            return None

        path_value = item.get("path")
        uri_value = item.get("uri") or ""

        # Resolve curio://outputs/ for items that carry that URI scheme (legacy
        # fat refs stored before the origin field existed use this URI even
        # when origin is "imported").  Check the item URI, not just the path,
        # because the path may be a bare artifact ID with no curio:// prefix.
        if uri_value.startswith("curio://outputs/"):
            resolved = self._resolve_computed_output_path(item)
            if resolved:
                return resolved
            return None  # artifact gone – caller will show unsupported preview

        if path_value and not str(path_value).startswith("curio://"):
            return str(path_value)

        dir_name = item.get("dirName")
        if not dir_name:
            catalog_dir = self.registry.get_catalog_dir(item.get("id", ""))
            if catalog_dir is not None:
                dir_name = catalog_dir.name
            else:
                return None

        from utk_curio.backend.app.datasets.installer import resolve_installed_data_path
        from utk_curio.backend.app.datasets.manifest import ManifestError, load_dataset_manifest
        from utk_curio.backend.app.datasets.storage import catalog_root, dataset_dir

        if self.user is not None:
            user_key = self._user_key()
            user_root = dataset_dir(user_key, dir_name)
            if (user_root / "manifest.json").is_file():
                try:
                    manifest = load_dataset_manifest(user_root)
                    return resolve_installed_data_path(user_key, manifest).as_posix()
                except (ManifestError, Exception):
                    pass

        catalog_root_dir = catalog_root() / dir_name
        if (catalog_root_dir / "manifest.json").is_file():
            try:
                manifest = load_dataset_manifest(catalog_root_dir)
                candidate = catalog_root_dir / manifest.data_file
                if candidate.is_file():
                    return candidate.as_posix()
            except ManifestError:
                return None
        return None

    def _project_manifest(self, dataflow_id: str | None) -> dict[str, Any]:
        if not dataflow_id:
            return {}
        _spec, manifest = self.installed._project_spec_and_manifest(dataflow_id)
        return manifest
