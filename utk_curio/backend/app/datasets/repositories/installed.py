"""Project-installed dataset refs repository."""

from __future__ import annotations

from typing import Any

from utk_curio.backend.app.datasets.domain.catalog_item import (
    base_item,
    item_from_manifest,
    loader_snippet,
    origin_from_dataflow_ref,
)
from utk_curio.backend.app.datasets.infrastructure.catalog_utils import iso_from_timestamp, stable_id
from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

class InstalledDatasetRepository:
    def __init__(self, user: Any | None):
        self.user = user

    def _project_spec_and_manifest(self, dataflow_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects import repositories as projects_repo
        from utk_curio.backend.app.projects import storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        project = projects_repo.get_for_user(dataflow_id, self.user.id)
        user_key = _user_dir_key(self.user)
        spec = storage.read_spec(user_key, project.id) or {}
        manifest = storage.read_manifest(user_key, project.id) or {}
        return spec, manifest

    def list_refs(self, dataflow_id: str | None) -> list[dict[str, Any]]:
        if not dataflow_id:
            return []
        spec, _manifest = self._project_spec_and_manifest(dataflow_id)
        dataflow = spec.get("dataflow") if isinstance(spec, dict) else {}
        refs = dataflow.get("datasets", []) if isinstance(dataflow, dict) else []
        return [r for r in refs if isinstance(r, dict)]

    def list_items(self, dataflow_id: str | None) -> list[dict[str, Any]]:
        refs = self.list_refs(dataflow_id)
        # One index read for the whole project's refs, so hydrating them costs a
        # single query instead of a manifest parse each. ``{}`` when the index is
        # unavailable, which falls back to parsing exactly as before.
        rows: dict[str, Any] = {}
        if refs and self.user is not None:
            from utk_curio.backend.app.datasets.repositories import index as index_repo
            from utk_curio.backend.app.projects.services import _user_dir_key

            rows = index_repo.safe_sync_rows_by_dir(_user_dir_key(self.user))

        items: list[dict[str, Any]] = []
        for ref in refs:
            dir_name = ref.get("dirName")

            # Folder-based datasets (hub OR imported): all metadata lives in the
            # installed manifest.  Any ref that carries a dirName is handled here,
            # regardless of origin.
            if dir_name:
                from utk_curio.backend.app.datasets.install.installer import (
                    InstallerError,
                    resolve_installed_data_path,
                )
                from utk_curio.backend.app.datasets.domain.manifest import (
                    ManifestError,
                    load_dataset_manifest,
                )
                from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
                from utk_curio.backend.app.projects.services import _user_dir_key

                user_key = _user_dir_key(self.user)
                try:
                    installed_dir = dataset_dir(user_key, dir_name)
                    row = rows.get(dir_name)
                    if row is not None:
                        from utk_curio.backend.app.datasets.repositories import (
                            index as index_repo,
                        )

                        manifest = index_repo.manifest_from_row(row)
                    else:
                        manifest = load_dataset_manifest(installed_dir)
                    data_path = resolve_installed_data_path(user_key, manifest)
                    item = item_from_manifest(
                        manifest, installed_dir, origin=origin_from_dataflow_ref(ref)
                    )
                    item["path"] = data_path.as_posix()
                    # Keep loaderSnippet in sync with the resolved path.
                    item["loaderSnippet"] = loader_snippet(
                        item["format"], data_path.as_posix(), dataset_id=item.get("id")
                    )
                    item["sizeBytes"] = data_path.stat().st_size
                    item["installed"] = True
                    # Persisted install time from the project ref — distinct from
                    # the manifest's createdAt/import time (see catalog_item).
                    item["installedAt"] = ref.get("installedAt")
                    item["producerNodeId"] = ref.get("producerNodeId")
                    item["consumerNodeIds"] = ref.get("consumerNodeIds") or []
                    # Propagate publishedToHub flag so computed datasets can be
                    # shown as published without changing their origin.
                    if ref.get("publishedToHub"):
                        item["publishedToHub"] = True
                    items.append(item)
                except (InstallerError, ManifestError, OSError, ValueError):
                    # Dataset not on disk or manifest unreadable – show a
                    # placeholder so the user can see it's broken.
                    items.append(base_item(
                        id=ref.get("datasetId") or ref.get("id") or dir_name,
                        title=dir_name,
                        description="Dataset is not installed on this machine.",
                        origin=ref.get("origin") or "imported",
                        format=ref.get("format") or "csv",
                        uri=f"curio://datasets/{dir_name}",
                        dirName=dir_name,
                        producerNodeId=ref.get("producerNodeId"),
                        consumerNodeIds=ref.get("consumerNodeIds") or [],
                        installedAt=ref.get("installedAt"),
                        installed=True,
                    ))
                continue

            # Legacy fat refs (no dirName): reconstruct from the ref's stored fields.
            fmt = ref.get("format") or "csv"
            items.append(base_item(
                id=ref.get("datasetId") or ref.get("id") or stable_id("installed", ref.get("uri", "")),
                title=ref.get("title") or "Installed dataset",
                description=ref.get("description") or "Dataset installed in this project.",
                origin=ref.get("origin") or "imported",
                format=fmt,
                uri=ref.get("uri") or "",
                path=ref.get("path"),
                dirName=ref.get("dirName"),
                sizeBytes=ref.get("sizeBytes"),
                rowCount=ref.get("rowCount"),
                featureCount=ref.get("featureCount"),
                producerNodeId=ref.get("producerNodeId"),
                consumerNodeIds=ref.get("consumerNodeIds") or [],
                updatedAt=ref.get("updatedAt") or ref.get("installedAt") or iso_from_timestamp(),
                installedAt=ref.get("installedAt"),
                sourceLabel=ref.get("sourceLabel")
                or (
                    "Computed"
                    if ref.get("origin") == "computed" or ref.get("producerNodeId")
                    else "Imported"
                ),
                license=ref.get("license"),
                tags=ref.get("tags") or [fmt],
                installed=True,
            ))
        return items

    def remove_dataset_references(self, dataflow_id: str, dataset_id: str) -> bool:
        """Strip every reference to *dataset_id* from one dataflow's spec.

        Removes the matching ``dataflow.datasets`` ref (preserving non-dict
        junk) AND the id from each node's ``metadata.datasetRefs`` binding —
        dropping the key when it empties — so a deleted dataset leaves no stale
        canvas pill behind (#176). Persists via ``update_project`` like
        :meth:`replace_refs`. Returns True when the spec changed.
        """
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects.schemas import ProjectUpdate
        from utk_curio.backend.app.projects import services as project_services

        spec, _manifest = self._project_spec_and_manifest(dataflow_id)
        dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
        if not isinstance(dataflow, dict):
            return False

        changed = False

        refs = dataflow.get("datasets")
        if isinstance(refs, list):
            next_refs = [
                r for r in refs
                if not (isinstance(r, dict) and dataset_id in (r.get("datasetId"), r.get("id")))
            ]
            if len(next_refs) != len(refs):
                dataflow["datasets"] = next_refs
                changed = True

        for node in dataflow.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            metadata = node.get("metadata")
            if not isinstance(metadata, dict):
                continue
            bindings = metadata.get("datasetRefs")
            if not isinstance(bindings, list) or dataset_id not in bindings:
                continue
            next_bindings = [b for b in bindings if b != dataset_id]
            if next_bindings:
                metadata["datasetRefs"] = next_bindings
            else:
                metadata.pop("datasetRefs", None)
            changed = True

        if not changed:
            return False
        project_services.update_project(
            self.user,
            dataflow_id,
            ProjectUpdate(spec=spec, outputs=None, name=None, description=None, thumbnail_accent=None),
        )
        return True

    def replace_refs(self, dataflow_id: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects.schemas import ProjectUpdate
        from utk_curio.backend.app.projects import services as project_services

        spec, _manifest = self._project_spec_and_manifest(dataflow_id)
        dataflow = spec.setdefault("dataflow", {})
        dataflow["datasets"] = refs
        detail = project_services.update_project(
            self.user,
            dataflow_id,
            ProjectUpdate(spec=spec, outputs=None, name=None, description=None, thumbnail_accent=None),
        )
        return detail.spec or spec
