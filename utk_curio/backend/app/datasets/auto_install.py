"""Auto-install node outputs into the user dataset store (unpublished)."""

from __future__ import annotations

from typing import Any


def auto_install_node_output(
    *,
    user: Any,
    node_id: str | None,
    sandbox_output: dict[str, Any],
    dataflow_id: str | None = None,
    node_name: str | None = None,
) -> dict[str, Any] | None:
    """Copy a node execution artifact into ``computed.<node_id>@1/`` when possible.

    Does not publish to the Data Catalog hub — only the per-project/user store.
    """
    if user is None or not node_id or not isinstance(sandbox_output, dict):
        return None

    data_type = sandbox_output.get("dataType") or sandbox_output.get("data_type")

    # Only auto-install a genuinely SAVED dataset or a multi-output bundle:
    #   * ``output['dataset']`` is the parquet a node deliberately saved
    #     (save_dataset_parquet); its filename is unique per output.
    #   * a bundle (``dataType == "outputs"``) is keyed by the parent artifact
    #     id in ``output['path']``.
    # Do NOT fall back to ``output['path']`` for an ordinary output: that turns a
    # node's raw intermediate artifact into a "computed dataset", and two nodes
    # referencing the same artifact then surface as duplicate, identically-named
    # palette entries (the data file the catalog collapse step has to clean up).
    is_bundle = str(data_type or "").strip().lower() == "outputs"
    if is_bundle:
        path_ref = sandbox_output.get("path")
    else:
        path_ref = sandbox_output.get("dataset")
    if not path_ref:
        return None

    try:
        from datetime import datetime as _dt, timezone as _tz

        from utk_curio.backend.app.datasets.bundle import install_node_output
        from utk_curio.backend.app.projects.services import _user_dir_key

        user_key = _user_dir_key(user)
        # The node's canvas display name becomes the dataset title; ignore blank
        # values so the installer keeps its filename-derived fallback.
        clean_node_name = (node_name or "").strip() or None
        result = install_node_output(
            user_key,
            node_id=node_id,
            path_ref=str(path_ref),
            data_type=data_type,
            node_name=clean_node_name,
        )
        if result is None:
            return None

        fmt = result.manifest.format
        installed = {
            "id": result.manifest.id,
            "dirName": result.manifest.dir_name,
            "origin": "computed",
            "format": fmt,
            "path": (result.dest / result.manifest.data_file).as_posix(),
            "producerNodeId": node_id,
            "replaced": result.replaced,
        }

        if dataflow_id:
            try:
                from utk_curio.backend.app.projects import storage as project_storage

                now_iso = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                ref = {
                    "datasetId": result.manifest.id,
                    "dirName": result.manifest.dir_name,
                    "origin": "computed",
                    "producerNodeId": node_id,
                    "installedAt": now_iso,
                }
                project_storage.merge_dataflow_dataset_ref(user_key, dataflow_id, ref)
            except Exception:  # noqa: BLE001
                pass

        return installed
    except Exception:  # noqa: BLE001
        return None
