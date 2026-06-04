"""Catalog import, install, publish, and uninstall."""

from __future__ import annotations

import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from utk_curio.backend.app.datasets.catalog_items import item_from_manifest, loader_snippet
from utk_curio.backend.app.datasets.catalog_paths import CatalogPathMixin
from utk_curio.backend.app.datasets.catalog_utils import catalog_id_from_title, iso_from_timestamp
from utk_curio.backend.app.datasets.constants import SUPPORTED_SUFFIXES
from utk_curio.backend.app.datasets.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.file_meta import count_file, patch_manifest_file, write_file_meta
from utk_curio.backend.app.datasets.installed_repository import InstalledDatasetRepository


class CatalogMutationsMixin(CatalogPathMixin):
    installed: InstalledDatasetRepository

    def import_dataset(
        self,
        file: FileStorage,
        *,
        dataflow_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        from utk_curio.backend.app.datasets.installer import (
            InstallerError,
            install_imported_file,
        )

        filename = secure_filename(file.filename or "")
        if not filename:
            raise DatasetCatalogError("No file selected")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise DatasetCatalogError(f"Unsupported dataset format: {suffix or filename}")
        fmt = SUPPORTED_SUFFIXES[suffix]

        user_key = self._user_key()
        file_bytes = file.read()

        try:
            result = install_imported_file(
                user_key, file_bytes, filename, fmt, title=title
            )
        except InstallerError as exc:
            raise DatasetCatalogError(str(exc)) from exc

        # Compute row/feature counts and patch the manifest if they were missing.
        data_path = result.dest / result.manifest.data_file
        row_count, feature_count = count_file(data_path, fmt)
        if (result.manifest.row_count is None and row_count is not None) or (
            result.manifest.feature_count is None and feature_count is not None
        ):
            patch_manifest_file(result.dest / "manifest.json", row_count, feature_count)
            write_file_meta(data_path, row_count, feature_count)

        from utk_curio.backend.app.datasets.manifest import load_dataset_manifest
        manifest = load_dataset_manifest(result.dest)
        item = item_from_manifest(manifest, result.dest, origin="imported")
        item["path"] = data_path.as_posix()
        # Keep loaderSnippet in sync with the resolved path.
        item["loaderSnippet"] = loader_snippet(item["format"], data_path.as_posix())
        item["sizeBytes"] = data_path.stat().st_size
        if row_count is not None:
            item["rowCount"] = row_count
        if feature_count is not None:
            item["featureCount"] = feature_count

        if dataflow_id:
            self.install_dataset(dataflow_id, item["id"], source_item=item)
            item["installed"] = True
        return item

    def publish_dataset(self, dataset_id: str, metadata: dict[str, Any], *, dataflow_id: str | None = None, live_outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        from utk_curio.backend.app.datasets.storage import catalog_root

        item = deepcopy(self.get_dataset(dataset_id, dataflow_id=dataflow_id, live_outputs=live_outputs))
        for key in ("title", "description", "license", "tags"):
            if key in metadata:
                item[key] = metadata[key]

        publish_is_computed = item.get("origin") == "computed" or bool(item.get("producerNodeId"))
        prior_source_label = item.get("sourceLabel")
        prior_producer_node_id = item.get("producerNodeId")

        # ── Compute counts from the local data file ──────────────────────────
        local_path: Path | None = None
        path_value = item.get("path")
        if path_value and not str(path_value).startswith("curio://"):
            p = Path(path_value)
            if p.is_file():
                local_path = p

        if local_path is not None:
            fmt = item.get("format", "")
            row_count, feature_count = count_file(local_path, fmt)
            if row_count is not None and item.get("rowCount") is None:
                item["rowCount"] = row_count
            if feature_count is not None and item.get("featureCount") is None:
                item["featureCount"] = feature_count

        # ── Write to the local catalog ────────────────────────────────────────
        catalog_id = item.get("id", "")
        # Convert file-hash IDs (e.g. "file-abc123") to a valid catalog id
        if not re.match(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*){1,5}$", catalog_id):
            catalog_id = catalog_id_from_title(str(item.get("title") or "dataset"))
            item["id"] = catalog_id

        dir_name = f"{catalog_id}@1"
        dest = catalog_root() / dir_name
        (dest / "data").mkdir(parents=True, exist_ok=True)

        # Copy data file into the catalog data/ subdirectory
        data_file = "data/data." + str(item.get("format", "csv"))
        if local_path is not None:
            dest_data = dest / "data" / local_path.name
            shutil.copy2(local_path, dest_data)
            data_file = f"data/{local_path.name}"

        # ── Write manifest.json with all fields ───────────────────────────────
        from utk_curio.backend.app.datasets.manifest import DatasetManifest, write_manifest

        now = iso_from_timestamp()
        manifest_obj = DatasetManifest(
            id=catalog_id,
            name=item.get("title") or catalog_id,
            version="1.0.0",
            format=item.get("format", "csv"),
            description=item.get("description") or "",
            publisher=str(self.user) if self.user else "Data Catalog",
            license=item.get("license") or "MIT",
            tags=item.get("tags") or [],
            data_file=data_file,
            major=1,
            source_label="Computed" if publish_is_computed else "Data Catalog",
            row_count=item.get("rowCount"),
            feature_count=item.get("featureCount"),
            schema=item.get("schema"),
            created_at=item.get("updatedAt") or now,
            updated_at=now,
        )
        write_manifest(manifest_obj, dest)

        item["dirName"] = dir_name
        item["updatedAt"] = iso_from_timestamp()
        if publish_is_computed:
            item["origin"] = "computed"
            item["producerNodeId"] = prior_producer_node_id
            item["publishedToHub"] = True
            sl = (prior_source_label or "").strip()
            bad = ("data catalog", "data hub", "current dataflow", "current workflow")
            if sl and sl.lower() not in bad:
                item["sourceLabel"] = prior_source_label
            else:
                item["sourceLabel"] = "Computed"
        else:
            item["sourceLabel"] = "Data Catalog"
            item["origin"] = "hub"

        # ── Update dataflow ref so the next catalog reload shows publish state ──
        # The canonical catalog entry is ``origin="hub"`` under ``datasets/``; the
        # dataflow ref still points at the user-store copy and keeps
        # ``imported`` / ``computed`` provenance (``publishedToHub`` for the badge).
        if dataflow_id:
            try:
                refs = self.installed.list_refs(dataflow_id)
                changed = False
                for ref in refs:
                    ref_id = ref.get("datasetId") or ref.get("id")
                    # Match by id, or (computed) any ref for the same producer node so
                    # project refs keyed as ``computed.<node>`` update when publish is
                    # invoked with the hub / remapped catalog id from the Data Catalog page.
                    matches_producer = bool(
                        publish_is_computed
                        and prior_producer_node_id
                        and ref.get("producerNodeId") == prior_producer_node_id,
                    )
                    if ref_id in (dataset_id, catalog_id) or matches_producer:
                        ref["datasetId"] = catalog_id
                        ref["dirName"] = dir_name
                        # Computed datasets keep origin="computed" always; track publish
                        # state with a separate publishedToHub flag so the frontend can
                        # show the correct Published badge without changing the origin.
                        if ref.get("origin") == "computed" or ref.get("producerNodeId"):
                            ref["publishedToHub"] = True
                            # Ensure origin is "computed" (not "hub") for computed datasets
                            ref.setdefault("origin", "computed")
                        else:
                            ref["publishedToHub"] = True
                            # Keep provenance: published copies in the user store stay imported.
                            if ref.get("origin") == "source_node":
                                pass
                            else:
                                ref["origin"] = "imported"
                        changed = True
                if changed:
                    self.installed.replace_refs(dataflow_id, refs)
            except Exception:  # noqa: BLE001 – never block publish on a ref update failure
                pass

        # ── If the dataset ID was remapped, also install the catalog entry into the
        # user's store so the ref's new dirName can be resolved on next list. ─────────
        if catalog_id != dataset_id and dataflow_id:
            try:
                from utk_curio.backend.app.datasets.installer import (
                    InstallerError,
                    install_dataset_from_catalog,
                )
                user_key = self._user_key()
                install_dataset_from_catalog(user_key, dir_name)
            except Exception:  # noqa: BLE001 – best-effort; don't block the publish response
                pass

        return item

    def install_dataset(
        self,
        dataflow_id: str,
        dataset_id: str,
        *,
        source_item: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = deepcopy(source_item or self.get_dataset(dataset_id, dataflow_id=dataflow_id))
        if item.get("origin") == "hub":
            dir_name = item.get("dirName")
            if not dir_name:
                raise DatasetCatalogError("Catalog dataset is missing catalog directory metadata", 500)
            from utk_curio.backend.app.datasets.installer import (
                InstallerError,
                install_dataset_from_catalog,
                resolve_installed_data_path,
            )

            user_key = self._user_key()
            try:
                result = install_dataset_from_catalog(user_key, dir_name)
                data_path = resolve_installed_data_path(user_key, result.manifest)
            except InstallerError as exc:
                raise DatasetCatalogError(str(exc)) from exc
            item["path"] = data_path.as_posix()
            item["sizeBytes"] = data_path.stat().st_size
            item["dirName"] = dir_name

            # Backfill rowCount/featureCount into the user-store manifest when
            # the hub manifest didn't include them (older catalog entries, etc.)
            if item.get("rowCount") is None and item.get("featureCount") is None:
                fmt = item.get("format", "")
                row_count, feature_count = count_file(data_path, fmt)
                if row_count is not None:
                    item["rowCount"] = row_count
                if feature_count is not None:
                    item["featureCount"] = feature_count
                if row_count is not None or feature_count is not None:
                    patch_manifest_file(result.dest / "manifest.json", row_count, feature_count)
                    write_file_meta(data_path, row_count, feature_count)

            # Project install is a user-store copy — not a global hub row.
            item["origin"] = "imported"
            item["uri"] = f"curio://datasets/{dir_name}"

        elif item.get("origin") == "computed":
            # ── Promote a node-computed output to a persistent installed dataset.
            #
            # Computed datasets live as raw files in the shared-data directory
            # while the workflow is active, but they are ephemeral — they
            # disappear when the project is unloaded.  "Installing" a computed
            # dataset copies the file into the user's dataset store, writes a
            # proper manifest.json, and registers it as ``origin="computed"``
            # keyed on the producer node ID.  Re-running "Install" (Reinstall)
            # replaces the same ``computed.<node_id>@1`` folder so the dataset
            # ID remains stable across multiple node executions.
            #
            # If no producerNodeId is known (legacy items) we fall back to the
            # old content-hash naming.
            #
            # Fast-path: if the item was already auto-installed by the execution
            # route (has a dirName pointing to the user's dataset store) we skip
            # re-copying the file and just fall through to the ref-write below.
            already_in_store = bool(item.get("dirName"))
            if not already_in_store:
                resolved = self._resolve_computed_output_path(item)
                if resolved is None:
                    raise DatasetCatalogError(
                        "Computed output file is not available. Run the dataflow node first.",
                        404,
                    )
                data_path = Path(resolved)
                suffix = data_path.suffix.lower()
                fmt = SUPPORTED_SUFFIXES.get(suffix, "json")

                producer_node_id = item.get("producerNodeId")

                if producer_node_id:
                    from utk_curio.backend.app.datasets.installer import (
                        InstallerError,
                        install_computed_file_for_node,
                        resolve_installed_data_path,
                    )

                    user_key = self._user_key()
                    file_bytes = data_path.read_bytes()
                    try:
                        result = install_computed_file_for_node(
                            user_key, file_bytes, data_path.name, fmt,
                            node_id=producer_node_id,
                            title=item.get("title"),
                        )
                    except InstallerError as exc:
                        raise DatasetCatalogError(str(exc)) from exc
                else:
                    from utk_curio.backend.app.datasets.installer import (
                        InstallerError,
                        install_computed_file,
                        resolve_installed_data_path,
                    )

                    user_key = self._user_key()
                    file_bytes = data_path.read_bytes()
                    try:
                        result = install_computed_file(
                            user_key, file_bytes, data_path.name, fmt,
                            title=item.get("title"),
                            node_id=producer_node_id,
                        )
                    except InstallerError as exc:
                        raise DatasetCatalogError(str(exc)) from exc

                inst_data_path = resolve_installed_data_path(user_key, result.manifest)

                # Compute row/feature counts and patch the sidecar.
                row_count, feature_count = count_file(inst_data_path, fmt)
                if (result.manifest.row_count is None and row_count is not None) or (
                    result.manifest.feature_count is None and feature_count is not None
                ):
                    patch_manifest_file(result.dest / "manifest.json", row_count, feature_count)
                    write_file_meta(inst_data_path, row_count, feature_count)

                from utk_curio.backend.app.datasets.manifest import load_dataset_manifest

                installed_manifest = load_dataset_manifest(result.dest)
                installed_item = item_from_manifest(installed_manifest, result.dest, origin="computed")
                installed_item["path"] = inst_data_path.as_posix()
                installed_item["sizeBytes"] = inst_data_path.stat().st_size
                if row_count is not None:
                    installed_item["rowCount"] = row_count
                if feature_count is not None:
                    installed_item["featureCount"] = feature_count
                # Preserve the producer link so the catalog can show the connection.
                installed_item["producerNodeId"] = item.get("producerNodeId")
                item = installed_item

        refs = self.installed.list_refs(dataflow_id)
        existing = next((ref for ref in refs if ref.get("datasetId") == item["id"]), None)
        ref = self._ref_from_item(item)
        if existing:
            existing.update(ref)
        else:
            refs.append(ref)
        self.installed.replace_refs(dataflow_id, refs)
        installed_item = deepcopy(item)
        installed_item["origin"] = ref["origin"]
        installed_item["installed"] = True
        return installed_item

    def uninstall_dataset(self, dataflow_id: str, dataset_id: str) -> dict[str, Any]:
        refs = self.installed.list_refs(dataflow_id)
        removed_ref = next(
            (ref for ref in refs if ref.get("datasetId") == dataset_id or ref.get("id") == dataset_id),
            None,
        )
        next_refs = [ref for ref in refs if ref.get("datasetId") != dataset_id and ref.get("id") != dataset_id]
        if len(next_refs) == len(refs):
            raise DatasetCatalogError("Dataset is not installed in this dataflow", 404)
        self.installed.replace_refs(dataflow_id, next_refs)

        # For computed datasets, also remove the folder from the user's dataset store
        # so the dataset is fully gone (it can be regenerated by re-running the node).
        if removed_ref and removed_ref.get("origin") == "computed" and self.user is not None:
            dir_name = removed_ref.get("dirName")
            if dir_name:
                try:
                    from utk_curio.backend.app.datasets.storage import dataset_dir
                    dest = dataset_dir(self._user_key(), dir_name)
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                except Exception:  # noqa: BLE001
                    pass

        return {"datasets": next_refs}

    def unpublish_dataset(self, dataset_id: str, *, dataflow_id: str | None = None) -> dict[str, Any]:
        """Remove a dataset from the local Data Catalog directory.

        The dataset must exist in the committed catalog tree. Project refs keep
        ``imported`` / ``computed`` provenance; only ``publishedToHub`` is cleared.
        The user's store copy (if any) is left intact.
        """
        from utk_curio.backend.app.datasets.storage import catalog_root

        # Locate the catalog directory for this dataset.
        root = catalog_root()
        catalog_dir: Path | None = None
        for d in root.iterdir():
            if not d.is_dir():
                continue
            # The dir_name is typically <catalog_id>@<major>
            base = d.name.split("@")[0] if "@" in d.name else d.name
            if base == dataset_id or d.name == dataset_id:
                catalog_dir = d
                break

        if catalog_dir is None:
            raise DatasetCatalogError(f"Dataset '{dataset_id}' is not in the Data Catalog", 404)

        dir_name = catalog_dir.name

        # Before removing the catalog folder, ensure the user's own dataset store has
        # a copy so that the spec ref's dirName continues to resolve after unpublish.
        # This also preserves the manifest.json (and therefore the dataset title).
        if self.user is not None:
            try:
                from utk_curio.backend.app.datasets.installer import (
                    install_dataset_from_catalog,
                )
                install_dataset_from_catalog(self._user_key(), dir_name, replace=False)
            except Exception:  # noqa: BLE001
                pass

        # Remove the catalog directory tree.
        shutil.rmtree(catalog_dir, ignore_errors=True)

        # Revert the spec.trill.json ref back to 'imported' origin so the dataset
        # keeps working from the user's store.  Keep dirName so the manifest (and
        # therefore the title) is still readable from the user's local copy.
        if dataflow_id:
            try:
                refs = self.installed.list_refs(dataflow_id)
                changed = False
                for ref in refs:
                    ref_id = ref.get("datasetId") or ref.get("id")
                    if ref_id == dataset_id or ref.get("dirName", "").split("@")[0] == dataset_id:
                        # Computed datasets keep origin="computed"; only clear the publishedToHub flag.
                        # Non-computed datasets revert to "imported".
                        if ref.get("origin") == "computed" or ref.get("producerNodeId"):
                            ref["publishedToHub"] = False
                            ref.setdefault("origin", "computed")
                        else:
                            ref["origin"] = "imported"
                            ref["publishedToHub"] = False
                        # Keep dirName – it now points to the user's store copy.
                        changed = True
                if changed:
                    self.installed.replace_refs(dataflow_id, refs)
            except Exception:  # noqa: BLE001
                pass

        return {"id": dataset_id, "unpublished": True}

    def _ref_from_item(self, item: dict[str, Any]) -> dict[str, Any]:
        origin = item.get("origin")
        dir_name = item.get("dirName")

        # Folder-based datasets (hub OR imported): store only the link to the
        # dataset folder.  All metadata is authoritative in manifest.json.
        if dir_name:
            return {
                "datasetId": item["id"],
                "dirName": dir_name,
                "origin": origin or "imported",
                "producerNodeId": item.get("producerNodeId"),
                "consumerNodeIds": item.get("consumerNodeIds") or [],
                "installedAt": iso_from_timestamp(),
            }

        # Legacy datasets without a folder (computed, source_node, or old
        # imported files): keep a fat ref because there is no manifest to
        # hydrate from at read time.
        ref_origin = origin if origin in {"computed", "source_node"} else "imported"
        return {
            "datasetId": item["id"],
            "title": item.get("title") or "Dataset",
            "description": item.get("description") or "",
            "origin": ref_origin,
            "sourceOrigin": origin,
            "uri": item.get("uri") or "",
            "path": item.get("path"),
            "dirName": dir_name,
            "format": item.get("format") or "csv",
            "sizeBytes": item.get("sizeBytes"),
            "rowCount": item.get("rowCount"),
            "featureCount": item.get("featureCount"),
            "producerNodeId": item.get("producerNodeId"),
            "consumerNodeIds": item.get("consumerNodeIds") or [],
            "sourceLabel": item.get("sourceLabel") or "",
            "license": item.get("license"),
            "tags": item.get("tags") or [],
            "updatedAt": item.get("updatedAt") or iso_from_timestamp(),
            "installedAt": iso_from_timestamp(),
        }
