"""Provenance and format resolution for catalog items."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.constants import SANDBOX_DATATYPE_TO_FORMAT, SUPPORTED_SUFFIXES


def catalog_item_is_computed_provenance(item: dict[str, Any]) -> bool:
    """Return True when a row should appear under the Data Catalog *Computed* rail.

    Stored ``origin`` may remain ``hub`` for datasets published from node outputs;
    those rows are still surfaced as *computed* using tags / description / producer.
    """
    if item.get("origin") == "computed":
        return True
    if item.get("producerNodeId"):
        return True
    if item.get("origin") != "hub":
        return False
    tags_cf = [str(t).casefold() for t in (item.get("tags") or [])]
    if "computed" in tags_cf:
        return True
    desc = (item.get("description") or "").casefold()
    if "dataflow node" in desc:
        return True
    if "computed" in desc and "node" in desc:
        return True
    sl = (item.get("sourceLabel") or "").strip().casefold()
    if sl == "computed":
        return True
    return False


def is_catalogable_output(data_type: str | None) -> bool:
    """All sandbox output kinds may be installed (including tuple bundles)."""
    return True


def computed_output_format(filename: str, data_type: str | None = None) -> str:
    """Resolve catalog format from filename suffix and/or sandbox dataType."""
    suffix_fmt = SUPPORTED_SUFFIXES.get(Path(filename).suffix.lower())
    if suffix_fmt:
        return suffix_fmt

    if data_type:
        mapped = SANDBOX_DATATYPE_TO_FORMAT.get(data_type.strip().lower())
        if mapped:
            return mapped

    from utk_curio.backend.app.datasets.output_paths import resolve_shared_output_path

    resolved = resolve_shared_output_path(filename, data_type=data_type)
    if resolved is not None:
        suffix_fmt = SUPPORTED_SUFFIXES.get(resolved.suffix.lower())
        if suffix_fmt:
            return suffix_fmt

    return "json"
