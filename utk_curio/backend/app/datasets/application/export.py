"""Export/download serialization and dataflow lineage helpers.

Module-level pure functions extracted from :mod:`listing`:

* producer / consumer lineage — recover the producing node and downstream
  consumers of a dataset from a dataflow spec (used by list + usage);
* export serialization — re-serialize a stored parquet dataset to the format
  the user sees (GeoJSON / CSV) and build a friendly, filesystem-safe download
  name (used by ``CatalogListing.download_target``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.domain.constants import FORMAT_TO_EXTENSION


def _producer_node_id_for(nodes: list, dataset_id: str) -> str | None:
    """The node id whose computed output is ``dataset_id`` (``computed.<seg>``)."""
    if not dataset_id.startswith("computed."):
        return None
    from utk_curio.backend.app.datasets.install.installer import sanitize_node_id_segment

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
    return path.suffix.lower() or FORMAT_TO_EXTENSION.get(fmt or "", "")


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
