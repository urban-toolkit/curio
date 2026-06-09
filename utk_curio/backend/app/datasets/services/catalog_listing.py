"""Catalog list, get, and preview."""

from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.catalog_dedup import catalog_facets, dedupe_items
from utk_curio.backend.app.datasets.catalog_items import loader_snippet
from utk_curio.backend.app.datasets.services.catalog_paths import CatalogPathMixin
from utk_curio.backend.app.datasets.computed_indexer import ComputedDatasetIndexer
from utk_curio.backend.app.datasets.constants import SUPPORTED_SUFFIXES
from utk_curio.backend.app.datasets.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.installed_repository import InstalledDatasetRepository
from utk_curio.backend.app.datasets.services.preview_service import DatasetPreviewService
from utk_curio.backend.app.datasets.provenance import catalog_item_is_computed_provenance
from utk_curio.backend.app.datasets.registry_repository import DatasetRegistryRepository

logger = logging.getLogger(__name__)


class CatalogListingMixin(CatalogPathMixin):
    registry: DatasetRegistryRepository
    installed: InstalledDatasetRepository
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
                # user's dataset store — do not replace it with the ephemeral
                # shared-data parquet used only for live discovery.
                path_val = item.get("path") or ""
                if path_val and Path(path_val).is_file():
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
                    # The URI looks like an output but the file no longer
                    # exists on disk.  Replace the stale relative path with
                    # None so the loader snippet shows a clear placeholder
                    # rather than a bare artifact ID that Python can't open.
                    path_val = item.get("path") or ""
                    if not path_val or not Path(path_val).is_absolute():
                        item["path"] = None
                        item["loaderSnippet"] = loader_snippet(item["format"], None)

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

        if sort == "name":
            items.sort(key=lambda item: (item.get("title") or "").casefold())
        else:
            items.sort(key=lambda item: item.get("updatedAt") or "", reverse=True)

        return {"items": items, "facets": facets}

    def get_dataset(self, dataset_id: str, *, dataflow_id: str | None = None, live_outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        for include_hub in (True, False):
            result = self.list_catalog(dataflow_id=dataflow_id, include_hub=include_hub, live_outputs=live_outputs)

            for item in result["items"]:
                if item["id"] == dataset_id:
                    return item
        raise DatasetCatalogError("Dataset not found", 404)

    def preview(
        self,
        dataset_id: str,
        *,
        dataflow_id: str | None = None,
        live_outputs: list[dict[str, Any]] | None = None,
        row_limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        item = deepcopy(self.get_dataset(
            dataset_id,
            dataflow_id=dataflow_id,
            live_outputs=live_outputs,
        ))
        resolved = self._resolve_item_path(item)
        if resolved:
            item["path"] = resolved
        return self.preview_service.preview(item, row_limit=row_limit, offset=offset)

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


_DOWNLOAD_MIMETYPES: dict[str, str] = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".parquet": "application/vnd.apache.parquet",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".shp": "application/octet-stream",
}

# Catalog ``DatasetFormat`` → canonical file extension. Used when the resolved
# data file has no suffix on disk (e.g. computed/artifact outputs).
_FORMAT_EXTENSIONS: dict[str, str] = {
    "csv": ".csv",
    "geojson": ".geojson",
    "json": ".json",
    "parquet": ".parquet",
    "geotiff": ".tif",
    "shp": ".shp",
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

    if geo_frame is not None:
        return geo_frame.to_json().encode("utf-8"), ".geojson", "application/geo+json"

    frame = pd.read_parquet(path)
    return frame.to_csv(index=False).encode("utf-8"), ".csv", "text/csv"


def _download_extension(path: Path, fmt: str | None) -> str:
    """Prefer the real file extension; fall back to the dataset format's."""
    suffix = path.suffix.lower()
    if suffix in _DOWNLOAD_MIMETYPES:
        return suffix
    if suffix:
        return suffix
    return _FORMAT_EXTENSIONS.get(fmt or "", "")


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
