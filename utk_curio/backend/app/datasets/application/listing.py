"""Catalog list, get, and preview."""

from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.domain.dedup import (
    catalog_facets,
    dedupe_items,
)
from utk_curio.backend.app.datasets.domain.catalog_item import loader_snippet
from utk_curio.backend.app.datasets.infrastructure.catalog_utils import looks_like_generated_filename
from utk_curio.backend.app.datasets.application.paths import PathResolver
from utk_curio.backend.app.datasets.application.export import (
    _DOWNLOAD_MIMETYPES,
    _dataset_consumer_nodes_in_spec,
    _dataset_producer_in_spec,
    _download_extension,
    _download_name,
    _serialize_parquet_for_export,
)
from utk_curio.backend.app.datasets.domain.computed import ComputedDatasetIndexer
from utk_curio.backend.app.datasets.domain.constants import SUPPORTED_SUFFIXES, is_osm_group_id
from utk_curio.backend.app.datasets.domain.osm_group import (
    build_osm_group_item,
    collapse_osm_groups,
    sort_group_members,
)
from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.repositories.installed import InstalledDatasetRepository
from utk_curio.backend.app.datasets.repositories.local import LocalDatasetRepository
from utk_curio.backend.app.datasets.repositories.user_store import UserDatasetRepository
from utk_curio.backend.app.datasets.application.preview import DatasetPreviewService
from utk_curio.backend.app.datasets.domain.provenance import catalog_item_is_computed_provenance
from utk_curio.backend.app.datasets.repositories.registry import DatasetRegistryRepository
from utk_curio.backend.app.datasets.install.installer import (
    dataflow_segment_from_computed_id,
    node_segment_from_computed_id,
    sanitize_node_id_segment,
)

logger = logging.getLogger(__name__)


def _legacy_installed_alias(
    item_id: str | None, dataflow_id: str | None, installed_ids: set[str]
) -> str | None:
    """Match a computed item namespaced to the OPEN dataflow against a spec ref
    that still carries the legacy un-namespaced ``computed.<node>`` id (written
    before namespacing and not yet migrated).

    Pre-namespacing installs were same-dataflow only, so the alias applies only
    when the item's dataflow segment is the open dataflow's — never across
    dataflows, and never on a bare producer-node match (#168).
    """
    if not item_id or not dataflow_id:
        return None
    df_seg = dataflow_segment_from_computed_id(item_id)
    if df_seg is None or df_seg != sanitize_node_id_segment(dataflow_id):
        return None
    node_seg = node_segment_from_computed_id(item_id)
    if not node_seg:
        return None
    legacy_id = f"computed.{node_seg}"
    return legacy_id if legacy_id in installed_ids else None


class CatalogListing:
    """Read-side catalog operations: list, get, preview, download, usage.

    Collaborators (repositories, computed indexer, preview service, and the
    shared :class:`PathResolver`) are injected by :class:`DatasetCatalogService`.
    """

    def __init__(
        self,
        *,
        user: Any | None,
        registry: DatasetRegistryRepository,
        local: LocalDatasetRepository,
        installed: InstalledDatasetRepository,
        user_store: UserDatasetRepository,
        computed: ComputedDatasetIndexer,
        preview_service: DatasetPreviewService,
        paths: PathResolver,
        owner: Any,
    ):
        self.user = user
        self.registry = registry
        self.local = local
        self.installed = installed
        self.user_store = user_store
        self.computed = computed
        self.preview_service = preview_service
        self._paths = paths
        # Facade back-reference: internal cross-method reads (get_dataset,
        # list_catalog, resolve_dataset_producer) resolve through the public
        # facade so a caller/test override of ``service.get_dataset`` is honored
        # exactly as it was under the former mixin design.
        self._owner = owner

    def list_catalog(
        self,
        *,
        dataflow_id: str | None = None,
        q: str | None = None,
        fmt: str | None = None,
        origin: str | None = None,
        sort: str = "recent",
        include_hub: bool = True,
        live_outputs: list[dict[str, Any]] | None = None,
        group_osm: bool = False,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if include_hub:
            items.extend(self.registry.list_items())
            # Workspace data (``<launch>/data``) and bundled sample data are
            # global, browsable sources like the hub — surface them in the
            # browse view so a dataset imported without an open dataflow (and
            # the shipped samples) are visible, not silently dropped.
            items.extend(self.local.list_items())
            # Account-level imported datasets registered in the user store, so a
            # register-only import stays visible in the catalog even when no
            # project references it. Computed node-output copies are excluded by
            # the repository (their per-project path is unchanged). A dataset
            # that IS installed in the open project also appears via
            # ``installed`` below; ``dedupe_items`` merges the two by id (the
            # ref row wins ``installed=True``).
            items.extend(self.user_store.list_items())
        if dataflow_id:
            items.extend(self.installed.list_items(dataflow_id))
            items.extend(self.computed.list_items(
                manifest=self._paths._project_manifest(dataflow_id),
                live_outputs=live_outputs,
                dataflow_id=dataflow_id,
            ))
            # This dataflow's own computed outputs live in the account store
            # (saved on generation, no project ref). Surface them here so they
            # appear in the open project's catalog — as available, not installed
            # — with their store metadata + lineage, even right after execution.
            # When include_hub is on, ``user_store.list_items()`` above already
            # lists every account-level computed dataset (this dataflow's
            # included), so only add the scoped set when the hub sources are off.
            if not include_hub:
                items.extend(self.user_store.list_dataflow_computed_items(dataflow_id))
        elif live_outputs:
            # No project yet (unsaved new dataflow) but live outputs provided —
            # still show computed items so outputs are visible immediately.
            items.extend(self.computed.list_items(live_outputs=live_outputs))

        inst_items = self.installed.list_items(dataflow_id)
        installed_ids = {item["id"] for item in inst_items if item.get("id")}

        # Map installed dataset id → installed output basename for computed
        # datasets. Keyed on the FULL (namespaced) id — never the bare
        # producerNodeId: node ids recur across dataflows (Duplicate Project,
        # trill re-import), and a bare-node match falsely marks another
        # dataflow's dataset as installed here (#168). The basename comparison
        # detects that the node re-ran since the last install ("Reinstall").
        installed_computed_filenames: dict[str, str] = {}
        for inst_item in inst_items:
            iid = inst_item.get("id")
            if iid and inst_item.get("origin") == "computed":
                inst_path = inst_item.get("path") or ""
                installed_computed_filenames[iid] = Path(inst_path).name if inst_path else ""

        for item in items:
            item_id = item.get("id")
            matched_id: str | None = None
            if item_id and item_id in installed_ids:
                item["installed"] = True
                matched_id = item_id
            elif item.get("origin") == "computed":
                matched_id = _legacy_installed_alias(item_id, dataflow_id, installed_ids)
                if matched_id is not None:
                    item["installed"] = True
            if matched_id is not None and item.get("origin") == "computed":
                # Only flag needsReinstall when the node produced a NEW output
                # file after the last install (filenames differ).  If the
                # filename is unchanged the node has not been re-executed and
                # the "Reinstall" button should not appear.
                current_filename = Path(item.get("path") or "").name
                installed_filename = installed_computed_filenames.get(matched_id) or ""
                if current_filename and installed_filename and current_filename != installed_filename:
                    item["needsReinstall"] = True

        # Post-execution auto-install writes to the user dataset store immediately;
        # reflect that in the catalog even before the next project save syncs spec refs.
        try:
            user_key = self._paths._user_key()
            self._paths._mark_user_store_computed_installs(
                items,
                user_key,
                installed_computed_filenames,
            )
        except DatasetCatalogError:
            logger.warning(
                "Failed to mark computed datasets from user store as installed; continuing without user-store install hints.",
                exc_info=True,
            )

        items = dedupe_items(items)

        # A computed dataset published to the hub keeps the title captured at
        # publish time (often the raw generated filename). When browsing from a
        # dataflow other than the producer's, only that stale hub row is listed,
        # so adopt the friendly node title from the user's store copy (same dir,
        # keyed on the producing node) when the listed title looks generated.
        try:
            self._prefer_user_store_computed_title(items, self._paths._user_key())
        except DatasetCatalogError:
            logger.warning(
                "Could not resolve friendly computed titles from the user store; "
                "continuing with the listed titles.",
                exc_info=True,
            )

        # Enrich computed items: resolve their bare filename to an absolute path
        # so the loader snippet points to a real file.  This must happen after
        # deduplication so we don't do wasted work on duplicates.
        #
        # Also covers legacy "fat refs" stored in old project specs: those refs
        # carry a ``curio://outputs/`` URI but may have ``origin == "imported"``
        # (or no origin at all) because they predate the ``origin`` field.
        for item in items:
            uri = item.get("uri") or ""
            is_outputs_uri = uri.startswith("curio://outputs/")
            if item.get("origin") == "computed" or is_outputs_uri:
                # Auto-installed copies already carry an absolute path into the
                # user's dataset store — keep it (don't replace it with the
                # ephemeral shared-data parquet used only for live discovery),
                # but ONLY when it resolves inside an allowed read root. The
                # path is not trustworthy: a malicious ``liveOutputs`` entry has
                # its ``filename`` copied verbatim into ``item["path"]`` by
                # ``ComputedDatasetIndexer``, so an entry like
                # ``{"filename": "/etc/passwd"}`` would otherwise be echoed back
                # here — disclosing an absolute path and acting as a
                # file-existence oracle in the listing/detail response, even
                # though preview/download are separately gated by
                # ``_resolve_item_path``. Confining it to the same roots is the
                # chokepoint that closes that leak (#143 follow-up).
                path_val = item.get("path") or ""
                contained = bool(path_val) and self._paths._contained_path(path_val) is not None
                if path_val and contained and Path(path_val).is_file():
                    item["loaderSnippet"] = loader_snippet(item["format"], path_val)
                    continue
                resolved = self._paths._resolve_computed_output_path(item)
                if resolved:
                    # If the resolved file is a parquet but the stored format
                    # differs (e.g. legacy "json" artifact), update the format
                    # so the loader snippet uses the right reader.
                    resolved_ext = Path(resolved).suffix.lower()
                    if resolved_ext in SUPPORTED_SUFFIXES:
                        item["format"] = SUPPORTED_SUFFIXES[resolved_ext]
                    item["path"] = resolved
                    item["loaderSnippet"] = loader_snippet(item["format"], resolved)
                elif is_outputs_uri:
                    # The URI looks like an output but it didn't resolve to a
                    # real file in the shared dir. Drop a stale relative path,
                    # and drop an absolute path that escapes the allowed roots
                    # (the attacker case above) so the response never carries a
                    # leaked path. A *contained* absolute path is a legitimate
                    # installed dataset whose file is momentarily missing —
                    # leave it so the loader snippet still points at the right
                    # place once it reappears.
                    abs_uncontained = bool(path_val) and Path(path_val).is_absolute() and not contained
                    if not path_val or not Path(path_val).is_absolute() or not contained:
                        item["path"] = None
                        item["loaderSnippet"] = loader_snippet(item["format"], None)
                    if abs_uncontained:
                        # The same out-of-root absolute path is embedded verbatim
                        # in the ``curio://outputs/<filename>`` URI (the filename
                        # is attacker-controlled via ``liveOutputs``). Drop it so
                        # no out-of-root absolute path is reflected anywhere in
                        # the listing/detail response.
                        item["uri"] = None

        # NOTE: we deliberately do NOT collapse computed datasets by data-file
        # basename here. Distinct saved records (e.g. an Autark map output and its
        # baseline-compute / modified-compute siblings) live in their own
        # ``computed.<node>@1`` dirs with distinct ids, but often share a generated
        # filename — basename-collapsing silently hid all but the "richest" one
        # until the others were deleted. ``dedupe_items`` (by dataset id, above)
        # already merges the only legitimate duplicates: the same dataset's hub
        # registry row and its installed/live copy. Every distinct record must
        # stay visible — the list reflects the actual saved datasets.

        # Fold the per-layer OSM datasets of one import into a single
        # bundle-shaped group entry for grouped surfaces (the catalog drawer).
        # Other surfaces (e.g. the node palette) keep the individual layers so
        # each stays independently draggable/installable.
        if group_osm:
            items = collapse_osm_groups(items)

        if q:
            needle = q.casefold()
            items = [
                item for item in items
                if needle in " ".join([
                    item.get("title") or "",
                    item.get("description") or "",
                    item.get("sourceLabel") or "",
                    item.get("path") or "",
                    " ".join(item.get("tags") or []),
                ]).casefold()
            ]

        # Facet counts should reflect the same universe as search (q), not the
        # narrowed list after format/origin filters — otherwise rails show zeros
        # or misleading counts while other filters are active.
        facets = catalog_facets(items)

        if fmt:
            items = [item for item in items if item.get("format") == fmt]
        if origin:
            if origin == "imported":
                items = [item for item in items if not catalog_item_is_computed_provenance(item)]
            elif origin == "computed":
                items = [item for item in items if catalog_item_is_computed_provenance(item)]
            else:
                items = [item for item in items if item.get("origin") == origin]

        # Real "N nodes consume" count for the browse cards. The persisted
        # ``consumerNodeIds`` ref is structurally empty, so derive the count from
        # the same cross-project graph resolver that powers ``dataset_usage``.
        # Best-effort: never fail the listing because usage couldn't be resolved.
        try:
            counts = self._consumer_counts(
                {item["id"] for item in items if item.get("id")}
            )
        except DatasetCatalogError:
            logger.warning(
                "Could not resolve dataset consumer counts; browse cards will show 0.",
                exc_info=True,
            )
            counts = {}
        for item in items:
            item["consumerNodeCount"] = counts.get(item.get("id"), 0)

        if sort == "name":
            items.sort(key=lambda item: (item.get("title") or "").casefold())
        else:
            items.sort(key=lambda item: item.get("updatedAt") or "", reverse=True)

        return {"items": items, "facets": facets}

    def _prefer_user_store_computed_title(
        self, items: list[dict[str, Any]], user_key: str
    ) -> None:
        """For computed datasets whose listed ``title`` looks like a raw generated
        filename, adopt the friendlier name from the user's store copy (same
        ``dirName``, keyed on the producing node) so the producing-node title
        shows regardless of which dataflow is open. Best-effort per item: a
        missing/unreadable manifest, or one whose own name is also generated,
        leaves the item untouched (the UI then falls back to ``dirName``)."""
        from utk_curio.backend.app.datasets.domain.manifest import (
            ManifestError,
            load_dataset_manifest,
        )
        from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

        for item in items:
            if not catalog_item_is_computed_provenance(item):
                continue
            dir_name = item.get("dirName")
            title = item.get("title")
            if not dir_name or not looks_like_generated_filename(title):
                continue
            try:
                manifest = load_dataset_manifest(dataset_dir(user_key, dir_name))
            except (ManifestError, OSError, ValueError):
                continue
            friendly = (manifest.name or "").strip()
            if friendly and not looks_like_generated_filename(friendly):
                item["title"] = friendly

    def get_dataset(
        self,
        dataset_id: str,
        *,
        dataflow_id: str | None = None,
        live_outputs: list[dict[str, Any]] | None = None,
        resolve_producer: bool = False,
    ) -> dict[str, Any]:
        # A synthetic OSM group id resolves to a bundle-shaped item built from
        # its member layers (which the un-collapsed listing still exposes).
        if is_osm_group_id(dataset_id):
            members = self._osm_group_members(dataset_id, dataflow_id=dataflow_id, live_outputs=live_outputs)
            if not members:
                raise DatasetCatalogError("Dataset not found", 404)
            return build_osm_group_item(dataset_id, members)

        # ``include_hub=True`` is a strict superset of ``include_hub=False`` (it
        # only *adds* the hub registry items), so a single pass finds any id —
        # no need for the historical two-pass scan.
        result = self._owner.list_catalog(dataflow_id=dataflow_id, include_hub=True, live_outputs=live_outputs)
        for item in result["items"]:
            if item["id"] == dataset_id:
                if resolve_producer:
                    self._backfill_authoritative_producer(item)
                return item
        raise DatasetCatalogError("Dataset not found", 404)

    def _backfill_authoritative_producer(self, item: dict[str, Any]) -> None:
        """Augment a computed dataset item with its authoritative producer.

        A computed dataset opened from a dataflow that only *imported* it carries
        that dataflow's ref, whose ``producerNodeId`` is ``null`` — the producing
        node lives in another dataflow. Resolve the real producer (node + type +
        producing dataflow) across all the user's projects so the Dataset Details
        page shows the same generating node as the dataset's producing record,
        regardless of where it was opened from. Mutates *item* in place.
        """
        if not catalog_item_is_computed_provenance(item):
            return
        producer = self._owner.resolve_dataset_producer(item.get("id") or "")
        if producer is None:
            return
        # Don't clobber a producer id already resolved from the open (producing)
        # dataflow — it is identical to the authoritative one. Always surface the
        # node type and producing dataflow so the cross-dataflow case can render.
        if not item.get("producerNodeId"):
            item["producerNodeId"] = producer["nodeId"]
        item["producerNodeType"] = producer.get("nodeType")
        item["producerDataflowId"] = producer.get("dataflowId")
        item["producerDataflowName"] = producer.get("dataflowName")
        item["origin"] = "computed"

    def resolve_dataset_producer(self, dataset_id: str) -> dict[str, Any] | None:
        """Authoritative producer of a computed dataset, resolved across ALL of
        the user's projects (not just the open dataflow).

        Returns ``{nodeId, nodeType, dataflowId, dataflowName}`` for the first
        dataflow whose nodes actually produce *dataset_id*, or ``None`` (the
        dataset is not computed, or no producing node exists anywhere). Mirrors
        the cross-project scan in :meth:`dataset_usage`.
        """
        if not dataset_id.startswith("computed."):
            return None
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects import repositories as projects_repo
        from utk_curio.backend.app.projects import storage as project_storage

        user_key = self._paths._user_key()
        for project in projects_repo.list_for_user(self.user.id):
            spec = project_storage.read_spec(user_key, project.id) or {}
            producer = _dataset_producer_in_spec(spec, dataset_id, project.id)
            if producer is not None:
                return {
                    **producer,
                    "dataflowId": project.id,
                    "dataflowName": project.name,
                }
        return None

    def preview(
        self,
        dataset_id: str,
        *,
        dataflow_id: str | None = None,
        live_outputs: list[dict[str, Any]] | None = None,
        row_limit: int = 50,
        offset: int = 0,
        part_index: int | None = None,
    ) -> dict[str, Any]:
        # An OSM group previews as a bundle: one tab (part) per member layer.
        if is_osm_group_id(dataset_id):
            return self._preview_osm_group(
                dataset_id,
                dataflow_id=dataflow_id,
                live_outputs=live_outputs,
                row_limit=row_limit,
                offset=offset,
                part_index=part_index,
            )
        item = deepcopy(self._owner.get_dataset(
            dataset_id,
            dataflow_id=dataflow_id,
            live_outputs=live_outputs,
        ))
        # Always replace ``path`` with the resolved, containment-checked path.
        # A ``None`` result means the stored path could not be safely resolved
        # (e.g. an attacker-supplied absolute path like ``/etc/passwd`` injected
        # via ``liveOutputs``); the preview service then reports the dataset as
        # unavailable instead of reading the raw path off disk.
        item["path"] = self._paths._resolve_item_path(item)
        return self.preview_service.preview(
            item, row_limit=row_limit, offset=offset, part_index=part_index
        )

    def _osm_group_members(
        self,
        group_id: str,
        *,
        dataflow_id: str | None = None,
        live_outputs: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """The individual layer items of an OSM group, in canonical tab order.

        Uses the un-collapsed listing (``group_osm=False``) so the member
        datasets — each carrying ``groupId`` — are visible and enriched with
        installed state + resolved paths.
        """
        result = self._owner.list_catalog(
            dataflow_id=dataflow_id, include_hub=True, live_outputs=live_outputs
        )
        members = [i for i in result["items"] if i.get("groupId") == group_id]
        return sort_group_members(members)

    def _preview_member(
        self, member: dict[str, Any], *, row_limit: int, offset: int
    ) -> dict[str, Any]:
        item = deepcopy(member)
        item["path"] = self._paths._resolve_item_path(item)
        return self.preview_service.preview(item, row_limit=row_limit, offset=offset)

    def _preview_osm_group(
        self,
        group_id: str,
        *,
        dataflow_id: str | None,
        live_outputs: list[dict[str, Any]] | None,
        row_limit: int,
        offset: int,
        part_index: int | None,
    ) -> dict[str, Any]:
        members = self._osm_group_members(
            group_id, dataflow_id=dataflow_id, live_outputs=live_outputs
        )
        if not members:
            raise DatasetCatalogError("Dataset not found", 404)
        if part_index is not None:
            if part_index < 0 or part_index >= len(members):
                raise DatasetCatalogError("Invalid part index", 400)
            part_preview = self._preview_member(
                members[part_index], row_limit=row_limit, offset=offset
            )
            return {**part_preview, "bundle": True, "partIndex": part_index}
        # Overview: first page of every layer, one tab per layer.
        parts: list[dict[str, Any]] = []
        for member in members:
            preview = self._preview_member(member, row_limit=row_limit, offset=0)
            parts.append({
                "label": member.get("layerName") or member.get("title"),
                "format": member.get("format"),
                "kind": "geodataframe",
                **preview,
            })
        return {
            "schema": {
                "bundleParts": [
                    {"label": p["label"], "format": p["format"], "kind": p.get("kind")}
                    for p in parts
                ]
            },
            "rows": [],
            "rowLimit": row_limit,
            "offset": 0,
            "totalRows": len(members),
            "truncated": False,
            "bundle": True,
            "parts": parts,
        }

    def download_target(
        self,
        dataset_id: str,
        *,
        dataflow_id: str | None = None,
        live_outputs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Resolve a dataset's data file for download/export.

        Returns the absolute filesystem path plus a suggested attachment name
        and mimetype. The serialized file is streamed as-is, so a parquet
        dataset exports the parquet binary, a CSV exports the CSV, etc.
        """
        item = deepcopy(self._owner.get_dataset(
            dataset_id,
            dataflow_id=dataflow_id,
            live_outputs=live_outputs,
        ))
        if item.get("format") == "bundle":
            raise DatasetCatalogError(
                "Multi-part (bundle) datasets cannot be exported as a single file.",
                400,
            )
        resolved = self._paths._resolve_item_path(item)
        if not resolved or not Path(resolved).is_file():
            raise DatasetCatalogError("Dataset file is not available for export.", 404)

        path = Path(resolved)
        fmt = item.get("format")
        title = item.get("title") or dataset_id

        if fmt == "parquet":
            # Parquet is an internal storage format. Export the deserialized data
            # in the type it represents (GeoJSON for geospatial data, CSV for
            # plain tabular data) so it matches the table/map preview.
            try:
                data, extension, mimetype = _serialize_parquet_for_export(path)
            except Exception as exc:  # noqa: BLE001
                raise DatasetCatalogError(
                    f"Could not serialize parquet dataset for export: {exc}",
                    500,
                ) from exc
            return {
                "download_name": _download_name(title, extension),
                "mimetype": mimetype,
                "data": data,
            }

        extension = _download_extension(path, fmt)
        return {
            "download_name": _download_name(title, extension),
            "mimetype": _DOWNLOAD_MIMETYPES.get(extension),
            "path": resolved,
        }

    def dataset_usage(self, dataset_id: str) -> list[dict[str, Any]]:
        """Dataflows across the user's projects that use *dataset_id*.

        Powers the standalone catalog detail page, which has no live canvas:
        a dataflow "uses" a dataset when its persisted spec references it via a
        ``dataflow.datasets`` ref, a node's ``metadata.datasetRefs`` binding, or
        the node that produced it (computed datasets are consumed by their
        downstream nodes through edges). Returns
        ``[{dataflowId, dataflowName, nodeCount, nodes: [{nodeId, nodeType}]}]``
        sorted by name.
        """
        if self.user is None:
            raise DatasetCatalogError("Authorization required", 401)
        from utk_curio.backend.app.projects import repositories as projects_repo
        from utk_curio.backend.app.projects import storage as project_storage

        user_key = self._paths._user_key()
        usages: list[dict[str, Any]] = []
        for project in projects_repo.list_for_user(self.user.id):
            spec = project_storage.read_spec(user_key, project.id) or {}
            consumers = _dataset_consumer_nodes_in_spec(spec, dataset_id, project.id)
            if consumers is None:
                continue
            usages.append({
                "dataflowId": project.id,
                "dataflowName": project.name,
                "nodeCount": len(consumers),
                "nodes": consumers,
            })
        usages.sort(key=lambda u: (u["dataflowName"] or "").casefold())
        return usages

    def _consumer_counts(self, dataset_ids: set[str]) -> dict[str, int]:
        """Total nodes consuming each id in *dataset_ids*, summed across all of
        the user's dataflows — the count rendered as "N nodes consume" on Data
        Hub browse cards.

        Uses the same resolver as :meth:`dataset_usage`
        (``_dataset_consumer_nodes_in_spec``) so the browse count always agrees
        with the detail panel's ``/usage`` total, but reads each project spec
        once and resolves every requested dataset against it — the whole browse
        page costs one pass over the projects, not one per dataset.

        Best-effort: returns ``{}`` when there is no authenticated user (an
        unauth listing) and skips any spec that cannot be read, so the listing
        never fails because usage could not be resolved. Ids with no consumers
        are omitted; callers default missing ids to ``0``.
        """
        if not dataset_ids or self.user is None:
            return {}
        from utk_curio.backend.app.projects import repositories as projects_repo
        from utk_curio.backend.app.projects import storage as project_storage

        user_key = self._paths._user_key()
        counts: dict[str, int] = {}
        for project in projects_repo.list_for_user(self.user.id):
            spec = project_storage.read_spec(user_key, project.id) or {}
            for dataset_id in dataset_ids:
                consumers = _dataset_consumer_nodes_in_spec(spec, dataset_id, project.id)
                if consumers:
                    counts[dataset_id] = counts.get(dataset_id, 0) + len(consumers)
        return counts
