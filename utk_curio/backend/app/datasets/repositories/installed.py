"""Project-installed dataset refs repository."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.common.safe_paths import is_within
from utk_curio.backend.app.datasets.domain.catalog_item import (
    autark_layer_type,
    base_item,
    item_from_manifest,
    loader_snippet,
    origin_from_dataflow_ref,
)
from utk_curio.backend.app.datasets.infrastructure.catalog_utils import iso_from_timestamp, stable_id
from utk_curio.backend.app.datasets.infrastructure.data_size import data_size_bytes
from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

class InstalledDatasetRepository:
    def __init__(self, user: Any | None):
        self.user = user
        #: The folders, in another account's store, of the datasets the
        #: dataflows read here list, each with the key of that store: an
        #: editor the dataflow's owner invited reads those of the owner's
        #: store, and no other (``PathResolver._allowed_read_roots``).
        self._listed: dict[Path, str] = {}

    @property
    def listed_folders(self) -> list[Path]:
        """The folders of another account's store this reader reads: those of
        the datasets the dataflows read here list, once read."""
        return list(self._listed)

    def _dataflow_store(self, dataflow_id: str) -> tuple[Any, str]:
        """The dataflow *dataflow_id* and the key of its owner's store, which
        holds its spec and the datasets it lists, for its owner and for an
        editor the owner invited. ``access.agents_role`` says which: it tells
        the owner by account first, as the agents' routes do, so a hosted
        guest keeps the examples its account owns. Anyone else is told the
        dataflow is not found."""
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects import access
        from utk_curio.backend.app.projects.models import Project
        from utk_curio.backend.app.projects.repositories import NotFoundError
        from utk_curio.backend.app.projects.services import _owner_user_dir_key
        from utk_curio.backend.extensions import db

        project = db.session.get(Project, dataflow_id)
        if project is None or access.agents_role(self.user, project) not in access.EDIT_ROLES:
            raise NotFoundError(f"Project {dataflow_id} not found")
        return project, _owner_user_dir_key(project)

    def _project_spec_and_manifest(self, dataflow_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        from utk_curio.backend.app.projects import storage

        project, store_key = self._dataflow_store(dataflow_id)
        spec = storage.read_spec(store_key, project.id) or {}
        manifest = storage.read_manifest(store_key, project.id) or {}
        return spec, manifest

    def _dataflow_refs(self, dataflow_id: str) -> tuple[str, list[dict[str, Any]]]:
        """The key of the store the dataflow's datasets are in, and the refs
        its spec lists."""
        from utk_curio.backend.app.projects import storage

        project, store_key = self._dataflow_store(dataflow_id)
        spec = storage.read_spec(store_key, project.id) or {}
        dataflow = spec.get("dataflow") if isinstance(spec, dict) else {}
        refs = dataflow.get("datasets", []) if isinstance(dataflow, dict) else []
        return store_key, [r for r in refs if isinstance(r, dict)]

    def list_refs(self, dataflow_id: str | None) -> list[dict[str, Any]]:
        if not dataflow_id:
            return []
        return self._dataflow_refs(dataflow_id)[1]

    def in_listed_folder(self, path: str | Path) -> bool:
        """Whether *path* is in one of :attr:`listed_folders`: a dataset of a
        dataflow's owner, which an editor of the dataflow reads."""
        return self.listed_store(path) is not None

    def listed_store(self, path: str | Path) -> str | None:
        """The key of the store whose folder of :attr:`listed_folders` holds
        *path*: the dataflow owner's, for a dataset of hers the dataflow lists
        and an editor of it reads. None for any other path."""
        return next(
            (key for folder, key in self._listed.items() if is_within(Path(path), folder)),
            None,
        )

    def list_items(self, dataflow_id: str | None) -> list[dict[str, Any]]:
        if not dataflow_id:
            return []
        store_key, refs = self._dataflow_refs(dataflow_id)
        from utk_curio.backend.app.projects.services import _user_dir_key

        # The refs of a dataflow the reader does not own name folders of its
        # owner's store: the reader's catalog may read those, and only those.
        listed_for_an_editor = store_key != _user_dir_key(self.user)
        # One index read for the whole project's refs, so hydrating them costs a
        # single query instead of a manifest parse each. ``{}`` when the index is
        # unavailable, which falls back to parsing exactly as before.
        rows: dict[str, Any] = {}
        if refs:
            from utk_curio.backend.app.datasets.repositories import index as index_repo

            rows = index_repo.safe_sync_rows_by_dir(store_key)

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

                try:
                    installed_dir = dataset_dir(store_key, dir_name)
                    if listed_for_an_editor:
                        self._listed.setdefault(installed_dir, store_key)
                    row = rows.get(dir_name)
                    if row is not None:
                        from utk_curio.backend.app.datasets.repositories import (
                            index as index_repo,
                        )

                        manifest = index_repo.manifest_from_row(row)
                    else:
                        manifest = load_dataset_manifest(installed_dir)
                    data_path = resolve_installed_data_path(store_key, manifest)
                    item = item_from_manifest(
                        manifest, installed_dir, origin=origin_from_dataflow_ref(ref)
                    )
                    item["path"] = data_path.as_posix()
                    # Keep loaderSnippet in sync with the resolved path.
                    item["loaderSnippet"] = loader_snippet(
                        item["format"], data_path.as_posix(), dataset_id=item.get("id"),
                        layer_type=autark_layer_type(item),
                    )
                    # A data file gone since it resolved raises OSError here,
                    # so the placeholder below lists it.
                    data_path.stat()
                    item["sizeBytes"] = data_size_bytes(manifest.format, data_path)
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

        Removes the matching ``dataflow.datasets`` ref AND the id from each
        node's ``metadata.datasetRefs`` binding - dropping the key when it
        empties - so a deleted dataset leaves no stale canvas pill behind
        (#176). Returns True when the spec changed.

        The two halves take different write paths on purpose. The refs list is
        backend-owned (dev/81 Fix 2), so it goes through :meth:`mutate_refs`;
        routing it through ``update_project`` would have the on-disk section
        carried forward over the edit and silently undo the removal. Node
        metadata is not backend-owned, so it still takes the whole-spec write.
        Refs first: the later ``update_project`` then carries forward a section
        that already has the ref gone.
        """
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects.schemas import ProjectUpdate
        from utk_curio.backend.app.projects import services as project_services

        changed = False

        # 1. The refs list, through the section writer.
        hit: list[bool] = []

        def _drop(refs: list[dict[str, Any]], _hit: list[bool] = hit):
            kept = [
                r for r in refs
                if not (isinstance(r, dict) and dataset_id in (r.get("datasetId"), r.get("id")))
            ]
            if len(kept) == len(refs):
                return None
            _hit.append(True)
            return kept

        self.mutate_refs(dataflow_id, _drop)
        if hit:
            changed = True

        # 2. Node-level bindings, through the whole-spec write.
        spec, _manifest = self._project_spec_and_manifest(dataflow_id)
        dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
        if not isinstance(dataflow, dict):
            return changed

        nodes_changed = False
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
            nodes_changed = True

        if nodes_changed:
            # A cleanup for the dataset's removal, not a save: a hosted guest's
            # removal clears its bindings as it clears its refs above.
            project_services.update_project(
                self.user,
                dataflow_id,
                ProjectUpdate(spec=spec, outputs=None, name=None, description=None, thumbnail_accent=None),
                cleanup=True,
            )
            changed = True

        return changed

    def mutate_refs(self, dataflow_id: str, mutate) -> dict[str, Any]:
        """Atomically read-modify-write this dataflow's refs (dev/82).

        *mutate* receives the current refs under the per-project spec lock and
        returns the list to persist, or ``None`` for "no change". Dedicated
        section writer (dev/81 Fix 2) - NOT an update_project round-trip: that
        path carries the on-disk datasets section forward on every client save
        (backend ownership) and would undo these refs. The callback must be a
        pure list transform (it runs while the spec lock is held)."""
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects import services as project_services

        spec = project_services.mutate_dataflow_datasets(self.user, dataflow_id, mutate)
        if spec is None:
            raise DatasetCatalogError("Dataflow not found", 404)
        return spec

    def replace_refs(self, dataflow_id: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
        """Whole-list variant of :meth:`mutate_refs` — for seeding/carry-over
        writes where the caller does not depend on the prior list."""
        return self.mutate_refs(dataflow_id, lambda _current: refs)
