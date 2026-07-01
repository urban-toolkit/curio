"""Auto-install node outputs into the user dataset store (unpublished)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _diagnostic(
    status: str,
    *,
    node_id: str | None,
    data_type: str | None,
    reason: str | None = None,
    dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Structured per-node result so the route/UI can trace why a node did (or
    did not) produce a computed dataset, instead of a silent ``None``.

    ``status`` is ``"installed" | "skipped" | "failed"``; the installed dataset
    payload (when any) is under ``dataset``.
    """
    diag: dict[str, Any] = {"status": status, "nodeId": node_id, "dataType": data_type}
    if reason:
        diag["reason"] = reason
    if dataset is not None:
        diag["dataset"] = dataset
    return diag


def _is_sink_node(node_type: str | None) -> bool:
    """True for visualization / sink node types whose output is a passthrough,
    not a dataset. The project-save installer prunes refs for these
    (``_prune_sink_node_dataset_refs``); skipping them here keeps the execution
    path from creating a transient dataset a later save would just remove."""
    if not node_type:
        return False
    try:
        from utk_curio.backend.app.projects.services import _SINK_NODE_TYPES
    except Exception:  # noqa: BLE001 — never let a diagnostic helper break install
        return False
    return node_type in _SINK_NODE_TYPES


def auto_install_node_output(
    *,
    user: Any,
    node_id: str | None,
    sandbox_output: dict[str, Any],
    dataflow_id: str | None = None,
    node_name: str | None = None,
    node_type: str | None = None,
) -> dict[str, Any]:
    """Copy a node execution artifact into ``computed.<node_id>@1/`` when possible.

    Persists the node's output as a computed dataset in the per-project/user
    store (not the public Data Catalog), matching the project-save installer
    (:func:`_auto_install_computed_outputs`) so JSON outputs (dict/list/scalar)
    are saved on execution too — not only DataFrame/GeoDataFrame parquet.

    Returns a diagnostic dict ``{status, nodeId, dataType, reason?, dataset?}``
    with ``status`` in ``"installed" | "skipped" | "failed"``. Never raises:
    install errors are logged and reported as ``failed`` rather than swallowed.
    """
    data_type = (
        (sandbox_output.get("dataType") or sandbox_output.get("data_type"))
        if isinstance(sandbox_output, dict)
        else None
    )

    if user is None or not node_id or not isinstance(sandbox_output, dict):
        return _diagnostic(
            "skipped", node_id=node_id, data_type=data_type,
            reason="missing user, node id, or output payload",
        )

    # Visualization / sink nodes pass their input through; their result is not a
    # dataset and the save-time installer prunes such refs. Skip proactively.
    if _is_sink_node(node_type):
        return _diagnostic(
            "skipped", node_id=node_id, data_type=data_type,
            reason=f"sink node ({node_type}) — output is not a dataset",
        )

    #   * a bundle (``dataType == "outputs"``) is keyed by the parent artifact
    #     id in ``output['path']``.
    #   * otherwise prefer ``output['dataset']`` — the parquet a (geo)dataframe
    #     deliberately saved (save_dataset_parquet) — and fall back to the node's
    #     own output artifact (``output['path']``) so JSON outputs (dict/list/
    #     scalar), which have no ``dataset`` parquet, are still persisted. Keyed
    #     on ``node_id`` (``computed.<node>@1``), so two nodes sharing a data file
    #     stay distinct datasets — the catalog no longer collapses by basename.
    is_bundle = str(data_type or "").strip().lower() == "outputs"
    if is_bundle:
        path_ref = sandbox_output.get("path")
    else:
        path_ref = sandbox_output.get("dataset") or sandbox_output.get("path")
    if not path_ref:
        return _diagnostic(
            "skipped", node_id=node_id, data_type=data_type,
            reason="node produced no output artifact to persist",
        )

    try:
        from datetime import datetime as _dt, timezone as _tz

        from utk_curio.backend.app.datasets.install.bundle import install_node_output
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
            return _diagnostic(
                "skipped", node_id=node_id, data_type=data_type,
                reason="output artifact could not be resolved or is an unsupported type",
            )

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
            except Exception:  # noqa: BLE001 — dataset is installed; ref merge is best-effort
                logger.exception(
                    "Auto-install: dataset installed for node %s but failed to record its "
                    "spec ref (dataflow %s); it will be reconciled on the next project save",
                    node_id, dataflow_id,
                )

        return _diagnostic(
            "installed", node_id=node_id, data_type=data_type, dataset=installed,
        )
    except Exception:  # noqa: BLE001 — surface as a diagnostic, never crash the run
        logger.exception(
            "Auto-install of computed output failed for node %s (type=%s, ref=%r); "
            "this dataset will not be persisted",
            node_id, data_type, path_ref,
        )
        return _diagnostic(
            "failed", node_id=node_id, data_type=data_type,
            reason="install error (see server logs)",
        )
