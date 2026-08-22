"""Catalog import, install, publish, and uninstall."""

from __future__ import annotations

import logging
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from utk_curio.backend.app.datasets.domain.catalog_item import item_from_manifest, loader_snippet
from utk_curio.backend.app.datasets.application.paths import PathResolver
from utk_curio.backend.app.datasets.infrastructure.catalog_utils import (
    catalog_id_from_title,
    iso_from_timestamp,
    looks_like_generated_filename,
)
from utk_curio.backend.app.datasets.domain.constants import (
    JUNK_SOURCE_LABELS,
    OSM_PBF_SUFFIXES,
    SUPPORTED_SUFFIXES,
    is_osm_group_id,
)
from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.infrastructure.file_meta import count_file, patch_manifest_file, write_file_meta
from utk_curio.backend.app.datasets.repositories.installed import InstalledDatasetRepository
from utk_curio.backend.app.datasets.infrastructure.storage import DATASET_ID_RE

logger = logging.getLogger(__name__)


class CatalogMutations:
    """Write-side catalog operations: import, publish, install, uninstall.

    Injected by :class:`DatasetCatalogService` with the installed-datasets
    repository, the shared :class:`PathResolver`, and an ``owner`` reference to
    the facade so cross-cutting reads (``get_dataset``,
    ``resolve_dataset_producer``) resolve through the same public methods callers
    (and tests) may override.
    """

    def __init__(
        self,
        *,
        user: Any | None,
        installed: InstalledDatasetRepository,
        paths: PathResolver,
        owner: Any,
    ):
        self.user = user
        self.installed = installed
        self._paths = paths
        self._owner = owner

    def import_dataset(
        self,
        file: FileStorage,
        *,
        dataflow_id: str | None = None,
        title: str | None = None,
        source_updated_at: str | None = None,
    ) -> dict[str, Any]:
        filename = secure_filename(file.filename or "")
        if not filename:
            raise DatasetCatalogError("No file selected")
        suffix = Path(filename).suffix.lower()
        file_bytes = file.read()

        # OSM PBF is multi-layer, so each non-empty layer (points / lines /
        # multipolygons / …) is registered as its own standalone GeoParquet
        # dataset. The route returns the first; the rest surface via the
        # account-level catalog listing on the next reload.
        if suffix in OSM_PBF_SUFFIXES:
            return self._import_osm_pbf_layers(
                file_bytes, filename, title=title, source_updated_at=source_updated_at
            )

        if suffix not in SUPPORTED_SUFFIXES:
            raise DatasetCatalogError(f"Unsupported dataset format: {suffix or filename}")
        return self._install_imported_bytes(
            file_bytes,
            filename,
            SUPPORTED_SUFFIXES[suffix],
            title=title,
            source_updated_at=source_updated_at,
        )

    def _install_imported_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        fmt: str,
        *,
        title: str | None = None,
        feature_count_override: int | None = None,
        group_id: str | None = None,
        layer_name: str | None = None,
        source_updated_at: str | None = None,
    ) -> dict[str, Any]:
        """Write imported bytes to the account-level user store and build the
        catalog item. Register-only: never attaches the dataset to a dataflow —
        a node/dataflow linkage is created only on explicit install."""
        from utk_curio.backend.app.datasets.install.installer import (
            InstallerError,
            install_imported_file,
        )
        from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest

        user_key = self._paths._user_key()
        try:
            result = install_imported_file(
                user_key,
                file_bytes,
                filename,
                fmt,
                title=title,
                group_id=group_id,
                layer_name=layer_name,
                source_updated_at=source_updated_at,
            )
        except InstallerError as exc:
            raise DatasetCatalogError(str(exc)) from exc

        # Compute row/feature counts and patch the manifest if they were missing.
        data_path = result.dest / result.manifest.data_file
        row_count, feature_count = count_file(data_path, fmt)
        # count_file doesn't parse parquet; use a caller-supplied count if given.
        if feature_count is None and feature_count_override is not None:
            feature_count = feature_count_override
        if (result.manifest.row_count is None and row_count is not None) or (
            result.manifest.feature_count is None and feature_count is not None
        ):
            patch_manifest_file(result.dest / "manifest.json", row_count, feature_count)
            write_file_meta(data_path, row_count, feature_count)

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
        item["installed"] = False
        return item

    def _import_osm_pbf_layers(
        self,
        pbf_bytes: bytes,
        filename: str,
        *,
        title: str | None = None,
        source_updated_at: str | None = None,
    ) -> dict[str, Any]:
        """Import an OSM PBF as one GeoParquet dataset per non-empty layer."""
        import uuid

        from utk_curio.backend.app.datasets.install.osm_pbf import (
            OsmPbfError,
            convert_osm_pbf_layers,
        )

        base = filename
        for pbf_suffix in (".osm.pbf", ".pbf"):
            if base.lower().endswith(pbf_suffix):
                base = base[: -len(pbf_suffix)]
                break
        base = base or "osm"

        try:
            layers = convert_osm_pbf_layers(pbf_bytes)
        except OsmPbfError as exc:
            raise DatasetCatalogError(str(exc)) from exc

        # One unique group id per *import* (never derived from file content) so
        # all layers of the same import share it, but re-importing the same PBF
        # forms a separate group rather than collapsing into the earlier one.
        group_id = f"osm.x{uuid.uuid4().hex[:8]}"
        prefix = title.strip() if title and title.strip() else base
        items: list[dict[str, Any]] = []
        for layer in layers:
            items.append(
                self._install_imported_bytes(
                    layer.geoparquet_bytes,
                    f"{base}_{layer.name}.parquet",
                    "parquet",
                    title=f"{prefix} ({layer.name})",
                    feature_count_override=layer.feature_count,
                    group_id=group_id,
                    layer_name=layer.name,
                    source_updated_at=source_updated_at,
                )
            )

        # The import route returns a single item. Report how many datasets the
        # PBF produced so the client can message "registered N datasets"; the
        # rest are surfaced by the account-level catalog listing on reload.
        primary = items[0]
        primary["importedDatasetCount"] = len(items)
        return primary

    def publish_dataset(self, dataset_id: str, metadata: dict[str, Any], *, dataflow_id: str | None = None, live_outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        from utk_curio.backend.app.datasets.infrastructure.storage import catalog_root

        item = deepcopy(self._owner.get_dataset(dataset_id, dataflow_id=dataflow_id, live_outputs=live_outputs))
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
        if not DATASET_ID_RE.match(catalog_id):
            catalog_id = catalog_id_from_title(str(item.get("title") or "dataset"))
            item["id"] = catalog_id

        dir_name = f"{catalog_id}@1"
        dest = catalog_root() / dir_name
        (dest / "data").mkdir(parents=True, exist_ok=True)

        # Copy data file into the catalog data/ subdirectory. A publishable
        # dataset must have a resolvable on-disk file — otherwise we'd write a
        # manifest pointing at a nonexistent path that lists fine but fails on
        # any later install/preview.
        if local_path is None:
            raise DatasetCatalogError(
                "Cannot publish a dataset whose data file is not available on disk"
            )
        if str(item.get("format")) == "bundle":
            # A bundle's data file is data/bundle.json plus a data/parts/* subtree.
            # Copy the whole data/ dir so the published entry's parts resolve;
            # copying only bundle.json leaves the parts it references missing.
            for child in local_path.parent.iterdir():
                target = dest / "data" / child.name
                if child.is_dir():
                    shutil.copytree(child, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, target)
        else:
            shutil.copy2(local_path, dest / "data" / local_path.name)
        data_file = f"data/{local_path.name}"

        # ── Resolve the published title ───────────────────────────────────────
        # The hub manifest is the title other dataflows see, so it must never be
        # a raw generated filename for a computed dataset (it would otherwise be
        # frozen at publish time and shown verbatim when browsed elsewhere).
        # ``item["title"]`` is already the friendly display name when resolvable
        # (get_dataset backfills the producing node's name); only fall back to the
        # store folder when it still looks generated. Imported datasets keep their
        # title as-is (a ``.csv`` import name is legitimate, not "generated").
        publish_title = (item.get("title") or "").strip()
        if publish_is_computed and looks_like_generated_filename(publish_title):
            # Fall back to the node-scoped folder, never the dataflow-namespaced
            # store id (whose dataflow segment is an opaque project UUID).
            from utk_curio.backend.app.datasets.install.installer import display_folder_name
            publish_title = display_folder_name(dir_name) or dir_name or catalog_id
        publish_title = publish_title or catalog_id
        item["title"] = publish_title

        # ── Write manifest.json with all fields ───────────────────────────────
        from utk_curio.backend.app.datasets.domain.manifest import DatasetManifest, write_manifest

        now = iso_from_timestamp()
        manifest_obj = DatasetManifest(
            id=catalog_id,
            name=publish_title,
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
            # Producer/upstream lineage travels with the published manifest —
            # the committed catalog is the only copy other users / fresh
            # checkouts see, so dropping it here loses it permanently (#170).
            source_updated_at=item.get("sourceUpdatedAt"),
            group_id=item.get("groupId"),
            layer_name=item.get("layerName"),
            producer_node_id=item.get("producerNodeId"),
            producer_node_type=item.get("producerNodeType"),
            producer_dataflow_id=item.get("producerDataflowId"),
            producer_dataflow_name=item.get("producerDataflowName"),
            upstream_inputs=item.get("upstreamInputs"),
        )
        write_manifest(manifest_obj, dest)

        item["dirName"] = dir_name
        item["updatedAt"] = iso_from_timestamp()
        if publish_is_computed:
            item["origin"] = "computed"
            item["producerNodeId"] = prior_producer_node_id
            item["publishedToHub"] = True
            sl = (prior_source_label or "").strip()
            if sl and sl.lower() not in JUNK_SOURCE_LABELS:
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
                from utk_curio.backend.app.datasets.install.installer import (
                    InstallerError,
                    install_dataset_from_catalog,
                )
                user_key = self._paths._user_key()
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
        node_title: str | None = None,
    ) -> dict[str, Any]:
        # "Install all layers": an OSM group id installs every member layer.
        if is_osm_group_id(dataset_id):
            return self._install_osm_group(dataflow_id, dataset_id)
        item = deepcopy(source_item or self._owner.get_dataset(dataset_id, dataflow_id=dataflow_id))
        # A client-supplied ``sourceItem`` may omit ``id``; the route-validated
        # ``dataset_id`` is authoritative, so backfill it rather than KeyError
        # (500) later when building the dataflow ref.
        if not item.get("id"):
            item["id"] = dataset_id
        if item.get("origin") == "hub":
            dir_name = item.get("dirName")
            if not dir_name:
                raise DatasetCatalogError("Catalog dataset is missing catalog directory metadata", 500)
            from utk_curio.backend.app.datasets.install.installer import (
                InstallerError,
                install_dataset_from_catalog,
                resolve_installed_data_path,
            )

            user_key = self._paths._user_key()
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
                resolved = self._paths._resolve_computed_output_path(item)
                if resolved is None:
                    raise DatasetCatalogError(
                        "Computed output file is not available. Run the dataflow node first.",
                        404,
                    )
                data_path = Path(resolved)
                suffix = data_path.suffix.lower()
                fmt = SUPPORTED_SUFFIXES.get(suffix, "json")

                producer_node_id = item.get("producerNodeId")
                user_key = self._paths._user_key()
                # Title the (re)installed dataset by the producing node, never the
                # raw generated filename. On reinstall the item arrives as a session
                # output whose ``title`` is the filename (the original manifest was
                # removed on uninstall), so we prefer the client-resolved node label
                # and on-disk fallbacks instead of ``item["title"]``.
                resolved_title = _resolve_computed_install_title(item, node_title, user_key)

                if producer_node_id:
                    from utk_curio.backend.app.datasets.install.installer import (
                        InstallerError,
                        install_computed_file_for_node,
                        resolve_installed_data_path,
                    )

                    file_bytes = data_path.read_bytes()
                    try:
                        result = install_computed_file_for_node(
                            user_key, file_bytes, data_path.name, fmt,
                            node_id=producer_node_id,
                            # Namespace by the installing dataflow so the promoted
                            # id matches the account-level dataset's id.
                            dataflow_id=dataflow_id,
                            node_type=item.get("producerNodeType"),
                            title=resolved_title,
                        )
                    except InstallerError as exc:
                        raise DatasetCatalogError(str(exc)) from exc
                else:
                    from utk_curio.backend.app.datasets.install.installer import (
                        InstallerError,
                        install_computed_file,
                        resolve_installed_data_path,
                    )

                    file_bytes = data_path.read_bytes()
                    try:
                        result = install_computed_file(
                            user_key, file_bytes, data_path.name, fmt,
                            title=resolved_title,
                            node_id=producer_node_id,
                        )
                    except InstallerError as exc:
                        raise DatasetCatalogError(str(exc)) from exc

                inst_data_path = resolve_installed_data_path(user_key, result.manifest)

                # Carry the parquet object-column decode sidecar (if any) so a
                # manual install round-trips dict/list columns, matching the
                # auto-install (source_path) path. The file_bytes install branch
                # doesn't copy it, so do it here where both paths converge.
                from utk_curio.sandbox.util.parsers import PARQUET_DECODE_SIDECAR_SUFFIX
                src_sidecar = data_path.with_name(data_path.name + PARQUET_DECODE_SIDECAR_SUFFIX)
                if src_sidecar.is_file():
                    shutil.copy2(
                        src_sidecar,
                        inst_data_path.with_name(inst_data_path.name + PARQUET_DECODE_SIDECAR_SUFFIX),
                    )

                # Compute row/feature counts and patch the sidecar.
                row_count, feature_count = count_file(inst_data_path, fmt)
                if (result.manifest.row_count is None and row_count is not None) or (
                    result.manifest.feature_count is None and feature_count is not None
                ):
                    patch_manifest_file(result.dest / "manifest.json", row_count, feature_count)
                    write_file_meta(inst_data_path, row_count, feature_count)

                from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest

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

        # Preserve the producer link across uninstall → reinstall. A computed
        # dataset encodes its producing node in its id/dirName
        # (``computed.[<dataflowSeg>.]<nodeSeg>``); on reinstall the item can
        # arrive with producerNodeId dropped (the ref was deleted on uninstall,
        # so the listing has nothing to carry it), which blanks the upstream
        # connection badge in the catalog card/palette. Resolve the
        # authoritative producer from the producing dataflow, falling back to
        # the id-encoded NODE segment (never the full ``<dataflow>.<node>``
        # pair), so the link — and the computed origin — is never lost.
        from utk_curio.backend.app.datasets.install.installer import (
            node_segment_from_computed_id,
        )

        node_seg = node_segment_from_computed_id(item.get("dirName") or item.get("id"))
        if node_seg and not item.get("producerNodeId"):
            producer = self._owner.resolve_dataset_producer(item.get("id") or "")
            item["producerNodeId"] = producer["nodeId"] if producer else node_seg
            item["origin"] = "computed"

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

    def _osm_group_member_ids(self, dataflow_id: str | None, group_id: str) -> list[str]:
        result = self._owner.list_catalog(dataflow_id=dataflow_id, include_hub=True)
        return [
            i["id"]
            for i in result["items"]
            if i.get("groupId") == group_id and i.get("id")
        ]

    def _install_osm_group(self, dataflow_id: str, group_id: str) -> dict[str, Any]:
        member_ids = self._osm_group_member_ids(dataflow_id, group_id)
        if not member_ids:
            raise DatasetCatalogError("Dataset not found", 404)
        for member_id in member_ids:
            self.install_dataset(dataflow_id, member_id)
        # Return the group item so the response reflects the "all installed" state.
        return self._owner.get_dataset(group_id, dataflow_id=dataflow_id)

    def uninstall_dataset(self, dataflow_id: str, dataset_id: str) -> dict[str, Any]:
        # An OSM group id uninstalls every member layer.
        if is_osm_group_id(dataset_id):
            member_ids = self._osm_group_member_ids(dataflow_id, dataset_id)
            removed = False
            for member_id in member_ids:
                try:
                    self.uninstall_dataset(dataflow_id, member_id)
                    removed = True
                except DatasetCatalogError:
                    # A layer that wasn't installed is fine during a group uninstall.
                    continue
            if not removed:
                raise DatasetCatalogError("Dataset is not installed in this dataflow", 404)
            return {"id": dataset_id, "installed": False}
        refs = self.installed.list_refs(dataflow_id)
        removed_ref = next(
            (ref for ref in refs if ref.get("datasetId") == dataset_id or ref.get("id") == dataset_id),
            None,
        )
        next_refs = [ref for ref in refs if ref.get("datasetId") != dataset_id and ref.get("id") != dataset_id]
        if len(next_refs) == len(refs):
            raise DatasetCatalogError("Dataset is not installed in this dataflow", 404)

        # For computed datasets, uninstall removes ONLY this dataflow's ref — the
        # account-store folder is retained. A computed dataset is an account-level
        # Data Catalog asset; uninstalling it from a project must leave it
        # installable again later. Permanently removing the account asset is a
        # separate explicit action (``delete_dataset``).
        self.installed.replace_refs(dataflow_id, next_refs)

        # For imported datasets, uninstalling must remove *all traces* — the
        # account-level store folder (manifest, data file, and counts sidecar all
        # live inside it), not just this dataflow's ref. Do this AFTER persisting
        # the ref removal so ``dataset_usage`` reflects it, then only delete when
        # no OTHER dataflow (or node binding) still references the dataset — a
        # dataset shared by another project must survive.
        if (
            removed_ref
            and self.user is not None
            and removed_ref.get("origin") not in ("computed", "source_node")
        ):
            dir_name = removed_ref.get("dirName")
            if dir_name and str(dir_name).startswith("imported."):
                self._remove_orphaned_imported_store_dir(dataset_id, dir_name)

        return {"datasets": next_refs}

    def _remove_orphaned_imported_store_dir(self, dataset_id: str, dir_name: str) -> None:
        """Delete an imported dataset's user-store folder when nothing else uses it.

        Best-effort: any failure (still-referenced, usage lookup error, or a
        locked file) leaves the folder in place and never fails the uninstall.
        Archived projects count as users — their refs must keep resolving when
        the project is restored (#176)."""
        try:
            still_used = self._owner.dataset_usage(dataset_id, include_archived=True)
        except Exception:  # noqa: BLE001 – if usage can't be resolved, keep the folder
            return
        if still_used:
            return
        try:
            from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

            dest = dataset_dir(self._paths._user_key(), dir_name)
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

    def _assert_is_publisher(self, catalog_dir: "Path", dataset_id: str) -> None:
        """Raise 403 unless the caller published *catalog_dir*.

        The shared catalog is a global tree; removal must be restricted to the
        recorded publisher (``str(user)`` at publish time). Manifests published
        without a user (factory seeds: ``publisher == "Data Catalog"``) are not
        removable through this API by a regular user. Fail closed on a
        missing/corrupt manifest.
        """
        from utk_curio.backend.app.datasets.domain.manifest import (
            ManifestError,
            load_dataset_manifest_from_dir,
        )

        # No manifest.json => not a properly published dataset (publish always
        # writes one), so there is no recorded owner to protect and nothing to
        # exfiltrate; skip the gate so corrupt/legacy leftovers stay removable.
        if not (catalog_dir / "manifest.json").is_file():
            return
        caller = str(self.user) if self.user is not None else None
        try:
            publisher = load_dataset_manifest_from_dir(catalog_dir).publisher
        except (ManifestError, OSError, ValueError):
            # Present but unreadable manifest is suspicious -> fail closed.
            publisher = None
        if not caller or publisher != caller:
            raise DatasetCatalogError(
                f"You can only unpublish or delete datasets you published "
                f"('{dataset_id}' was published by someone else).",
                403,
            )

    def unpublish_dataset(self, dataset_id: str, *, dataflow_id: str | None = None) -> dict[str, Any]:
        """Remove a dataset from the local Data Catalog directory.

        The dataset must exist in the committed catalog tree. Project refs keep
        ``imported`` / ``computed`` provenance; only ``publishedToHub`` is cleared.
        The user's store copy (if any) is left intact.
        """
        from utk_curio.backend.app.datasets.infrastructure.storage import catalog_root

        # Locate the catalog directory for this dataset. The catalog root is
        # never created eagerly (pip installs / CURIO_CATALOG_ROOT overrides
        # start without one), so guard the scan — a missing root means the
        # dataset is simply not published, i.e. the 404 below.
        root = catalog_root()
        catalog_dir: Path | None = None
        if root.is_dir():
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

        # Ownership gate (security): only the user who published this dataset may
        # remove it from the SHARED catalog tree. Without this, any authenticated
        # user could delete — and, via the store-copy step below, silently copy —
        # another user's published dataset. The published manifest records
        # ``publisher=str(user)`` (see publish_dataset); compare against the same
        # expression. Fail closed if the manifest is missing/unreadable.
        self._assert_is_publisher(catalog_dir, dataset_id)

        # Before removing the catalog folder, ensure the user's own dataset store has
        # a copy so that the spec ref's dirName continues to resolve after unpublish.
        # This also preserves the manifest.json (and therefore the dataset title).
        if self.user is not None:
            try:
                from utk_curio.backend.app.datasets.install.installer import (
                    install_dataset_from_catalog,
                )
                install_dataset_from_catalog(self._paths._user_key(), dir_name, replace=False)
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
                    # ``dirName`` can be a present-but-null legacy field; ``or ""``
                    # guards ``None.split`` so one bad ref doesn't abort the whole
                    # spec reconciliation.
                    if ref_id == dataset_id or (ref.get("dirName") or "").split("@")[0] == dataset_id:
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

    def delete_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Permanently remove an account-level dataset from the user's catalog.

        The single path that deletes the account asset (uninstall keeps it).
        Cascades: unpublish from the hub if published → remove the dataset's ref
        from every dataflow that references it → delete the account-store folder.
        """
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.datasets.infrastructure.storage import (
            list_user_datasets,
        )

        user_key = self._paths._user_key()

        # 1. Unpublish from the hub if a committed catalog copy exists. Best-effort:
        # unpublish restores the manifest into the store, which step 3 then removes.
        try:
            self.unpublish_dataset(dataset_id)
        except DatasetCatalogError as exc:
            # A 403 (caller is not the publisher) must abort the whole delete —
            # otherwise a non-owner would fall through to the ref-removal and
            # store-delete steps below. A 404 (not published / not in the shared
            # catalog, e.g. a purely computed account asset) is expected: there
            # is nothing to unpublish, so continue to the account-store delete.
            if getattr(exc, "status", 400) == 403:
                raise

        # 2. Remove the dataset's references from every dataflow that holds any
        #    (archived included, #176) — both the ``dataflow.datasets`` ref and
        #    node-level ``metadata.datasetRefs`` bindings — so no project is
        #    left pointing at a deleted asset.
        removed_from: list[str] = []
        try:
            usages = self._owner.dataset_usage(dataset_id, include_archived=True)
        except Exception:  # noqa: BLE001 – best-effort; still delete the asset
            usages = []
        for usage in usages:
            df_id = usage.get("dataflowId") if isinstance(usage, dict) else None
            if not df_id:
                continue
            # Per-dataflow isolation: one unreadable (possibly archived) spec
            # must not abort the cascade for the others.
            try:
                if self.installed.remove_dataset_references(df_id, dataset_id):
                    removed_from.append(df_id)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Could not strip references to %s from dataflow %s",
                    dataset_id, df_id, exc_info=True,
                )

        # 3. Delete the account-store folder(s) for this dataset id.
        deleted = False
        for dataset_root in list_user_datasets(user_key):
            base = dataset_root.name.split("@")[0]
            if base == dataset_id or dataset_root.name == dataset_id:
                shutil.rmtree(dataset_root, ignore_errors=True)
                deleted = True

        if not deleted and not removed_from:
            raise DatasetCatalogError(
                f"Dataset '{dataset_id}' was not found in your catalog", 404
            )

        return {"id": dataset_id, "deleted": True, "removedFrom": removed_from}

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


def _resolve_computed_install_title(
    item: dict[str, Any], node_title: str | None, user_key: str | None
) -> str | None:
    """Resolve the title for a (re)installed computed dataset.

    Precedence — the raw generated filename is *never* used as a title:
      1. an explicit node label supplied by the client (``node_title``), which
         is how the producing node's name survives publish → uninstall →
         reinstall (the original manifest is gone by then);
      2. the name on a still-present on-disk manifest (e.g. a user-store copy
         preserved across unpublish), when it isn't just the filename;
      3. the item's own ``title``, when it isn't the generated filename;
      4. the store-folder name with the dataflow segment stripped
         (``display_folder_name`` — never the raw namespaced dirName, which
         would leak the dataflow UUID into the title);
      5. ``None`` — the installer then derives a filename-based title, which the
         frontend renders as ``dirName`` via ``datasetDisplayTitle``.
    """
    file_name = (item.get("fileName") or "").strip()

    def _usable(value: str | None) -> str | None:
        candidate = (value or "").strip()
        if not candidate:
            return None
        # A value equal to the generated filename is not a real node name.
        if file_name and candidate == file_name:
            return None
        return candidate

    # 1. Explicit node label resolved by the client.
    explicit = _usable(node_title)
    if explicit:
        return explicit

    item_id = (item.get("id") or "").strip()
    dir_name = item.get("dirName") or (
        f"{item_id}@1" if item_id.startswith("computed.") else None
    )

    # 2. Name on a preserved on-disk manifest.
    if user_key and dir_name:
        try:
            from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
            from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest

            dest = dataset_dir(user_key, dir_name)
            if dest.exists():
                manifest_name = _usable(load_dataset_manifest(dest).name)
                if manifest_name:
                    return manifest_name
        except Exception:  # noqa: BLE001 – fall through to the next candidate
            pass

    # 3. The item's own title (skipped when it is the generated filename).
    own_title = _usable(item.get("title"))
    if own_title:
        return own_title

    # 4. Store-folder name (dataflow segment stripped); 5. None.
    if dir_name:
        from utk_curio.backend.app.datasets.install.installer import display_folder_name

        return display_folder_name(dir_name)
    return None
