"""Catalog list, get, and preview."""

from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.catalog_dedup import (
    catalog_facets,
    dedupe_items,
)
from utk_curio.backend.app.datasets.catalog_items import loader_snippet
from utk_curio.backend.app.datasets.catalog_utils import looks_like_generated_filename
from utk_curio.backend.app.datasets.services.catalog_paths import CatalogPathMixin
from utk_curio.backend.app.datasets.computed_indexer import ComputedDatasetIndexer
from utk_curio.backend.app.datasets.constants import FORMAT_TO_EXTENSION, SUPPORTED_SUFFIXES
from utk_curio.backend.app.datasets.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.installed_repository import InstalledDatasetRepository
from utk_curio.backend.app.datasets.local_repository import LocalDatasetRepository
from utk_curio.backend.app.datasets.services.preview_service import DatasetPreviewService
from utk_curio.backend.app.datasets.provenance import catalog_item_is_computed_provenance
from utk_curio.backend.app.datasets.registry_repository import DatasetRegistryRepository

logger = logging.getLogger(__name__)


class CatalogListingMixin(CatalogPathMixin):
    registry: DatasetRegistryRepository
    installed: InstalledDatasetRepository
    local: LocalDatasetRepository
    computed: ComputedDatasetIndexer
    preview_service: DatasetPreviewService

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
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if include_hub:
            items.extend(self.registry.list_items())
            # Workspace data (``<launch>/data``) and bundled sample data are
            # global, browsable sources like the hub — surface them in the
            # browse view so a dataset imported without an open dataflow (and
            # the shipped samples) are visible, not silently dropped.
            items.extend(self.local.list_items())
        if dataflow_id:
            items.extend(self.installed.list_items(dataflow_id))
            items.extend(self.computed.list_items(
                manifest=self._project_manifest(dataflow_id),
                live_outputs=live_outputs,
            ))
        elif live_outputs:
            # No project yet (unsaved new dataflow) but live outputs provided —
            # still show computed items so outputs are visible immediately.
            items.extend(self.computed.list_items(live_outputs=live_outputs))

        inst_items = self.installed.list_items(dataflow_id)
        installed_ids = {item["id"] for item in inst_items if item.get("id")}

        # Map producerNodeId → installed output basename for computed datasets.
        # Used to determine whether the node has been re-executed since the last
        # install: if the current output filename differs from the installed one
        # the node was re-run and a "Reinstall" prompt is warranted.
        installed_computed_filenames: dict[str, str] = {}
        for inst_item in inst_items:
            pid = inst_item.get("producerNodeId")
            if pid and inst_item.get("origin") == "computed":
                inst_path = inst_item.get("path") or ""
                installed_computed_filenames[pid] = Path(inst_path).name if inst_path else ""

        for item in items:
            if item["id"] in installed_ids:
                item["installed"] = True
            elif item.get("origin") == "computed":
                pid = item.get("producerNodeId")
                if pid and pid in installed_computed_filenames:
                    item["installed"] = True
                    # Only flag needsReinstall when the node produced a NEW output
                    # file after the last install (filenames differ).  If the
                    # filename is unchanged the node has not been re-executed and
                    # the "Reinstall" button should not appear.
                    current_filename = Path(item.get("path") or "").name
                    installed_filename = installed_computed_filenames[pid]
                    if current_filename and installed_filename and current_filename != installed_filename:
                        item["needsReinstall"] = True

        # Post-execution auto-install writes to the user dataset store immediately;
        # reflect that in the catalog even before the next project save syncs spec refs.
        try:
            user_key = self._user_key()
            self._mark_user_store_computed_installs(
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
            self._prefer_user_store_computed_title(items, self._user_key())
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
                contained = bool(path_val) and self._contained_path(path_val) is not None
                if path_val and contained and Path(path_val).is_file():
                    item["loaderSnippet"] = loader_snippet(item["format"], path_val)
                    continue
                resolved = self._resolve_computed_output_path(item)
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
        from utk_curio.backend.app.datasets.manifest import (
            ManifestError,
            load_dataset_manifest,
        )
        from utk_curio.backend.app.datasets.storage import dataset_dir

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
        # ``include_hub=True`` is a strict superset of ``include_hub=False`` (it
        # only *adds* the hub registry items), so a single pass finds any id —
        # no need for the historical two-pass scan.
        result = self.list_catalog(dataflow_id=dataflow_id, include_hub=True, live_outputs=live_outputs)
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
        producer = self.resolve_dataset_producer(item.get("id") or "")
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

        user_key = self._user_key()
        for project in projects_repo.list_for_user(self.user.id):
            spec = project_storage.read_spec(user_key, project.id) or {}
            producer = _dataset_producer_in_spec(spec, dataset_id)
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
        item = deepcopy(self.get_dataset(
            dataset_id,
            dataflow_id=dataflow_id,
            live_outputs=live_outputs,
        ))
        # Always replace ``path`` with the resolved, containment-checked path.
        # A ``None`` result means the stored path could not be safely resolved
        # (e.g. an attacker-supplied absolute path like ``/etc/passwd`` injected
        # via ``liveOutputs``); the preview service then reports the dataset as
        # unavailable instead of reading the raw path off disk.
        item["path"] = self._resolve_item_path(item)
        return self.preview_service.preview(
            item, row_limit=row_limit, offset=offset, part_index=part_index
        )

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
        item = deepcopy(self.get_dataset(
            dataset_id,
            dataflow_id=dataflow_id,
            live_outputs=live_outputs,
        ))
        if item.get("format") == "bundle":
            raise DatasetCatalogError(
                "Multi-part (bundle) datasets cannot be exported as a single file.",
                400,
            )
        resolved = self._resolve_item_path(item)
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

        user_key = self._user_key()
        usages: list[dict[str, Any]] = []
        for project in projects_repo.list_for_user(self.user.id):
            spec = project_storage.read_spec(user_key, project.id) or {}
            consumers = _dataset_consumer_nodes_in_spec(spec, dataset_id)
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

        user_key = self._user_key()
        counts: dict[str, int] = {}
        for project in projects_repo.list_for_user(self.user.id):
            spec = project_storage.read_spec(user_key, project.id) or {}
            for dataset_id in dataset_ids:
                consumers = _dataset_consumer_nodes_in_spec(spec, dataset_id)
                if consumers:
                    counts[dataset_id] = counts.get(dataset_id, 0) + len(consumers)
        return counts


def _producer_node_id_for(nodes: list, dataset_id: str) -> str | None:
    """The node id whose computed output is ``dataset_id`` (``computed.<seg>``)."""
    if not dataset_id.startswith("computed."):
        return None
    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment

    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        if nid and f"computed.{sanitize_node_id_segment(nid)}" == dataset_id:
            return nid
    return None


def _dataset_producer_in_spec(
    spec: dict[str, Any], dataset_id: str
) -> dict[str, Any] | None:
    """The producer node (``{nodeId, nodeType}``) for *dataset_id* in *spec*'s
    dataflow, or ``None`` when this dataflow does not produce it.

    A computed dataset's id encodes its producer node id
    (``computed.<sanitized-nodeId>``), so the producing node — and its type —
    can be recovered from any dataflow that still contains that node.
    """
    if not isinstance(spec, dict):
        return None
    dataflow = spec.get("dataflow")
    if not isinstance(dataflow, dict):
        return None
    nodes = dataflow.get("nodes") or []
    producer_id = _producer_node_id_for(nodes, dataset_id)
    if producer_id is None:
        return None
    node_type = None
    for node in nodes:
        if isinstance(node, dict) and node.get("id") == producer_id:
            node_type = node.get("type")
            break
    return {"nodeId": producer_id, "nodeType": node_type}


def _dataset_consumer_nodes_in_spec(
    spec: dict[str, Any], dataset_id: str
) -> list[dict[str, Any]] | None:
    """Consumer node refs (``[{nodeId, nodeType}]``) if *spec*'s dataflow uses
    *dataset_id*, else ``None``. An empty list means the dataflow uses/owns the
    dataset (e.g. produced or installed) but no node consumes it downstream.

    Mirrors the frontend lineage resolver: the dataset enters the flow through
    *carrier* nodes — the computed producer and any Data Loading node that
    (re)loads it — and is consumed by the nodes wired downstream of those
    carriers. A carrier's own binding is NOT consumption, so a dropped-but-
    unconnected loader registers no downstream usage. A non-loading node with
    the dataset applied (a binding) is a genuine consumer.
    """
    if not isinstance(spec, dict):
        return None
    dataflow = spec.get("dataflow")
    if not isinstance(dataflow, dict):
        return None

    nodes = dataflow.get("nodes") or []
    edges = dataflow.get("edges") or []
    datasets = dataflow.get("datasets") or []

    node_type_by_id = {
        node["id"]: node.get("type")
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }

    def _is_data_loading(node_type: Any) -> bool:
        return isinstance(node_type, str) and (
            node_type == "DATA_LOADING" or "data-loading" in node_type
        )

    uses = False
    consumer_ids: list[str] = []
    seen: set[str] = set()
    carrier_ids: set[str] = set()

    producer_id = _producer_node_id_for(nodes, dataset_id)
    if producer_id is not None:
        uses = True
        carrier_ids.add(producer_id)

    def add_consumer(nid: str | None) -> None:
        if nid and nid not in seen and nid not in carrier_ids:
            seen.add(nid)
            consumer_ids.append(nid)

    for ref in datasets:
        if isinstance(ref, dict) and dataset_id in (ref.get("datasetId"), ref.get("id")):
            uses = True

    for node in nodes:
        if not isinstance(node, dict):
            continue
        refs = (node.get("metadata") or {}).get("datasetRefs") or []
        if dataset_id in refs:
            uses = True
            nid = node.get("id")
            if _is_data_loading(node.get("type")):
                if nid:
                    carrier_ids.add(nid)  # loader = source/carrier, not a consumer
            else:
                add_consumer(nid)  # dataset applied to a node → genuine consumer

    if carrier_ids:
        for edge in edges:
            if not isinstance(edge, dict) or edge.get("type") == "Interaction":
                continue
            if edge.get("source") in carrier_ids and edge.get("target"):
                add_consumer(edge["target"])

    if not uses:
        return None
    return [{"nodeId": nid, "nodeType": node_type_by_id.get(nid)} for nid in consumer_ids]


_DOWNLOAD_MIMETYPES: dict[str, str] = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".parquet": "application/vnd.apache.parquet",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".shp": "application/octet-stream",
}

def _serialize_parquet_for_export(path: Path) -> tuple[bytes, str, str]:
    """Deserialize a stored parquet dataset and re-serialize it to the data type
    it represents — GeoJSON for geospatial data, CSV for plain tabular data.

    Parquet is an internal storage format; exports should match what the user
    sees in the preview, so a GeoDataFrame round-trips to GeoJSON and a plain
    DataFrame to CSV.

    Returns ``(payload_bytes, extension, mimetype)``.
    """
    import pandas as pd

    # GeoParquet carries geo metadata; ``gpd.read_parquet`` succeeds only for
    # geospatial data and decodes the geometry column to real shapely geometries.
    geo_frame = None
    try:
        import geopandas as gpd

        geo_frame = gpd.read_parquet(path)
    except Exception:  # noqa: BLE001 — not geospatial / no geo metadata
        geo_frame = None

    from utk_curio.sandbox.util.parsers import restore_parquet_sidecar

    if geo_frame is not None:
        # Decode JSON-encoded object columns (the <file>.decode.json sidecar) so
        # list/dict properties export as real values, not double-encoded strings.
        geo_frame = restore_parquet_sidecar(
            geo_frame, path, geometry_col=geo_frame.geometry.name
        )
        # ``to_json`` serializes feature properties via ``json.dumps``, which
        # can't natively encode pandas/numpy temporal values (e.g. Timestamp).
        # Forward ``default=str`` so those fall back to their string form rather
        # than raising "Object of type Timestamp is not JSON serializable".
        return (
            geo_frame.to_json(default=str).encode("utf-8"),
            ".geojson",
            "application/geo+json",
        )

    frame = pd.read_parquet(path)
    frame = restore_parquet_sidecar(frame, path)
    return frame.to_csv(index=False).encode("utf-8"), ".csv", "text/csv"


def _download_extension(path: Path, fmt: str | None) -> str:
    """Prefer the real file extension; fall back to the dataset format's."""
    suffix = path.suffix.lower()
    if suffix in _DOWNLOAD_MIMETYPES:
        return suffix
    if suffix:
        return suffix
    return FORMAT_TO_EXTENSION.get(fmt or "", "")


def _download_name(title: str, extension: str) -> str:
    """Build a friendly, filesystem-safe download filename from the dataset's
    display title plus the canonical extension.

    Preserves the human-readable title (spaces and casing) so the exported file
    matches the name shown in the catalog, only stripping characters that are
    illegal in filenames.
    """
    import re

    # Replace path separators, reserved characters, and dots with a space, then
    # collapse whitespace. Dots are stripped from the stem so the only dot in the
    # final filename is the one separating the extension.
    cleaned = re.sub(r'[\\/:*?"<>|.\x00-\x1f]+', " ", title.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    stem = cleaned or "dataset"
    return f"{stem}{extension}"
