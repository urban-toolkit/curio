"""Index node-computed outputs for catalog listing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.catalog_items import base_item
from utk_curio.backend.app.datasets.catalog_utils import iso_from_timestamp, stable_id
from utk_curio.backend.app.datasets.provenance import (
    computed_output_format,
    is_catalogable_output,
)

class ComputedDatasetIndexer:
    def list_items(
        self,
        *,
        manifest: dict[str, Any] | None = None,
        live_outputs: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return catalog items for node-computed outputs.

        Sources (merged, with live_outputs taking precedence over manifest):
        - ``manifest``:     project manifest written to disk on save
        - ``live_outputs``: current session outputs from the frontend
                            (present even when the project hasn't been saved yet)
        """
        # Build a merged list of {node_id, filename} entries.
        # live_outputs override manifest entries for the same node_id so a
        # re-execution is reflected immediately without requiring a save.
        merged: dict[str, dict[str, Any]] = {}  # node_id -> entry

        manifest_outputs = (manifest or {}).get("outputs", []) if manifest else []
        for output in manifest_outputs:
            if isinstance(output, dict) and output.get("node_id") and output.get("filename"):
                merged[output["node_id"]] = output

        for output in (live_outputs or []):
            if isinstance(output, dict) and output.get("node_id") and output.get("filename"):
                merged[output["node_id"]] = output

        items: list[dict[str, Any]] = []
        for output in merged.values():
            filename = output.get("filename")
            node_id = output.get("node_id")
            if not filename:
                continue
            raw = str(filename)
            data_type = output.get("data_type") or output.get("dataType")
            if not is_catalogable_output(data_type):
                continue
            fmt = computed_output_format(raw, data_type)
            # Use the same stable node-based ID that install_computed_file_for_node
            # writes to the manifest so that the live-output item and the
            # user-store item share the same ID and are correctly deduped.
            if node_id:
                from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment
                item_id = f"computed.{sanitize_node_id_segment(node_id)}"
            else:
                item_id = stable_id("computed", f"{node_id}:{raw}")
            items.append(base_item(
                id=item_id,
                title=Path(raw).stem.replace("_", " ").replace("-", " ").title() or raw,
                description="Dataset produced by a node output.",
                origin="computed",
                format=fmt,
                uri=f"curio://outputs/{raw}",
                path=raw,
                producerNodeId=node_id,
                updatedAt=iso_from_timestamp(),
                sourceLabel="Computed",
                tags=["computed", fmt],
            ))
        return items
