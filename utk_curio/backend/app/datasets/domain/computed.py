"""Index node-computed outputs for catalog listing."""

from __future__ import annotations

from typing import Any

from utk_curio.backend.app.datasets.domain.catalog_item import base_item
from utk_curio.backend.app.datasets.infrastructure.catalog_utils import iso_from_timestamp, stable_id, title_from_filename
from utk_curio.backend.app.datasets.domain.provenance import computed_output_format

class ComputedDatasetIndexer:
    def list_items(
        self,
        *,
        manifest: dict[str, Any] | None = None,
        live_outputs: list[dict[str, Any]] | None = None,
        dataflow_id: str | None = None,
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
            # Every sandbox output kind is catalogable (including tuple bundles),
            # so there is no kind filter here.
            fmt = computed_output_format(raw, data_type)
            # Use the same stable, dataflow-namespaced ID that
            # install_computed_file_for_node writes to the manifest so that the
            # live-output item and the user-store item share the same ID and are
            # correctly deduped.
            if node_id:
                from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
                item_id = computed_dataset_id(node_id, dataflow_id)
            else:
                item_id = stable_id("computed", f"{node_id}:{raw}")
            items.append(base_item(
                id=item_id,
                title=title_from_filename(raw),
                # Session-only outputs have no producing-node name available yet,
                # so the filename remains both title and subtitle until install.
                fileName=title_from_filename(raw),
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
