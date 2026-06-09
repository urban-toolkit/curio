"""Auto-install node outputs into the user dataset store (unpublished)."""

from __future__ import annotations

from typing import Any


def auto_install_node_output(
    *,
    user: Any,
    node_id: str | None,
    sandbox_output: dict[str, Any],
    dataflow_id: str | None = None,
) -> dict[str, Any] | None:
    """Copy a node execution artifact into ``computed.<node_id>@1/`` when possible.

    Does not publish to the Data Catalog hub — only the per-project/user store.
    """
    if user is None or not node_id or not isinstance(sandbox_output, dict):
        return None

    path_ref = sandbox_output.get("dataset") or sandbox_output.get("path")
    if not path_ref:
        return None

    data_type = sandbox_output.get("dataType") or sandbox_output.get("data_type")

    try:
        from datetime import datetime as _dt, timezone as _tz

        from utk_curio.backend.app.datasets.bundle import install_node_output
        from utk_curio.backend.app.projects.services import _user_dir_key

        user_key = _user_dir_key(user)
        result = install_node_output(
            user_key,
            node_id=node_id,
            path_ref=str(path_ref),
            data_type=data_type,
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
