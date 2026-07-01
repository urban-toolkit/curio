"""HTTP routes for the decoupled dataset catalog service."""

from __future__ import annotations

import functools

from flask import Blueprint, g, jsonify, request, send_file

from utk_curio.backend.app.datasets.schemas.requests import (
    normalize_live_outputs_list,
    parse_live_outputs,
)
from utk_curio.backend.app.datasets.service import DatasetCatalogError, DatasetCatalogService
from utk_curio.backend.app.projects.repositories import NotFoundError
from utk_curio.backend.app.projects.services import ProjectError
from utk_curio.backend.app.users.dependencies import require_auth


datasets_bp = Blueprint("datasets_api", __name__, url_prefix="/api")


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _map_catalog_errors(fn):
    """Translate service-layer exceptions into JSON error responses.

    Centralizes the mapping every catalog route shares: catalog/project errors
    carry their own status (default 400); a missing dataflow is 404. Applied
    below ``require_auth`` so auth failures are not swallowed here.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (DatasetCatalogError, ProjectError) as exc:
            return _error(str(exc), getattr(exc, "status", 400))
        except NotFoundError:
            return _error("Dataflow not found", 404)

    return wrapper


def _service() -> DatasetCatalogService:
    return DatasetCatalogService(getattr(g, "user", None))


def _dataflow_id_from_request() -> str | None:
    return request.args.get("dataflowId") or request.args.get("projectId")


@datasets_bp.route("/datasets/catalog", methods=["GET"])
@require_auth
@_map_catalog_errors
def list_dataset_catalog():
    include_hub = request.args.get("includeHub", "true").lower() not in {"0", "false", "no"}
    # Live outputs (base64 JSON) are the current execution outputs the frontend
    # holds before the manifest is saved, so computed datasets appear immediately
    # after node execution.
    live_outputs = parse_live_outputs(request.args.get("liveOutputs"))
    payload = _service().list_catalog(
        dataflow_id=_dataflow_id_from_request(),
        q=request.args.get("q") or None,
        fmt=request.args.get("format") or None,
        origin=request.args.get("origin") or None,
        sort=request.args.get("sort", "recent"),
        include_hub=include_hub,
        live_outputs=live_outputs,
    )
    return jsonify(payload), 200


@datasets_bp.route("/datasets/<dataset_id>", methods=["GET"])
@require_auth
@_map_catalog_errors
def get_dataset(dataset_id: str):
    payload = _service().get_dataset(
        dataset_id,
        dataflow_id=_dataflow_id_from_request(),
        live_outputs=parse_live_outputs(request.args.get("liveOutputs")),
        resolve_producer=True,
    )
    return jsonify(payload), 200


@datasets_bp.route("/datasets/<dataset_id>/preview", methods=["GET"])
@require_auth
@_map_catalog_errors
def preview_dataset(dataset_id: str):
    # Parse pagination in isolation: a ValueError here is genuinely a bad query
    # param and returns 400 immediately, so it is not confused with a ValueError
    # raised deep inside preview parsing (e.g. a UnicodeDecodeError on a
    # zlib-compressed output).
    part = request.args.get("part")
    try:
        row_limit = max(1, min(int(request.args.get("rowLimit", "50")), 500))
        offset = max(0, int(request.args.get("offset", "0")))
        part_index = max(0, int(part)) if part is not None else None
    except ValueError:
        return _error("rowLimit, offset and part must be integers")

    payload = _service().preview(
        dataset_id,
        dataflow_id=_dataflow_id_from_request(),
        live_outputs=parse_live_outputs(request.args.get("liveOutputs")),
        row_limit=row_limit,
        offset=offset,
        part_index=part_index,
    )
    return jsonify(payload), 200


@datasets_bp.route("/datasets/<dataset_id>/usage", methods=["GET"])
@require_auth
@_map_catalog_errors
def dataset_usage(dataset_id: str):
    """Dataflows (across the user's projects) that use this dataset."""
    dataflows = _service().dataset_usage(dataset_id)
    return jsonify({"dataflows": dataflows}), 200


@datasets_bp.route("/datasets/<dataset_id>/download", methods=["GET"])
@require_auth
@_map_catalog_errors
def download_dataset(dataset_id: str):
    target = _service().download_target(
        dataset_id,
        dataflow_id=_dataflow_id_from_request(),
        live_outputs=parse_live_outputs(request.args.get("liveOutputs")),
    )

    data = target.get("data")
    if data is not None:
        from io import BytesIO

        return send_file(
            BytesIO(data),
            as_attachment=True,
            download_name=target["download_name"],
            mimetype=target.get("mimetype") or "application/octet-stream",
        )
    return send_file(
        target["path"],
        as_attachment=True,
        download_name=target["download_name"],
        mimetype=target.get("mimetype"),
    )


@datasets_bp.route("/datasets/import", methods=["POST"])
@require_auth
@_map_catalog_errors
def import_dataset():
    file = request.files.get("file")
    if file is None:
        return _error("No file part")
    payload = _service().import_dataset(
        file,
        dataflow_id=request.form.get("dataflowId") or request.form.get("projectId"),
        title=request.form.get("title") or None,
    )
    return jsonify(payload), 201


@datasets_bp.route("/datasets/publish", methods=["POST"])
@require_auth
@_map_catalog_errors
def publish_dataset():
    body = request.get_json(silent=True) or {}
    dataset_id = body.get("datasetId")
    if not dataset_id:
        return _error("datasetId is required")
    payload = _service().publish_dataset(
        dataset_id,
        body,
        dataflow_id=body.get("dataflowId") or body.get("projectId"),
        live_outputs=normalize_live_outputs_list(body.get("liveOutputs")),
    )
    return jsonify(payload), 201


@datasets_bp.route("/datasets/publish/<dataset_id>", methods=["DELETE"])
@require_auth
@_map_catalog_errors
def unpublish_dataset(dataset_id: str):
    payload = _service().unpublish_dataset(
        dataset_id,
        dataflow_id=_dataflow_id_from_request(),
    )
    return jsonify(payload), 200


@datasets_bp.route("/dataflows/<dataflow_id>/datasets/install", methods=["POST"])
@require_auth
@_map_catalog_errors
def install_dataset(dataflow_id: str):
    body = request.get_json(silent=True) or {}
    dataset_id = body.get("datasetId")
    if not dataset_id:
        return _error("datasetId is required")
    # sourceItem: optional, for ephemeral computed datasets (live outputs) not yet
    # in the persisted catalog. nodeTitle: the producing node's display label,
    # resolved client-side, so a computed dataset keeps its node name across
    # publish → uninstall → reinstall (the original manifest is gone by then).
    payload = _service().install_dataset(
        dataflow_id,
        dataset_id,
        source_item=body.get("sourceItem") or None,
        node_title=body.get("nodeTitle") or None,
    )
    return jsonify(payload), 200


@datasets_bp.route("/dataflows/<dataflow_id>/datasets/<dataset_id>", methods=["DELETE"])
@require_auth
@_map_catalog_errors
def uninstall_dataset(dataflow_id: str, dataset_id: str):
    payload = _service().uninstall_dataset(dataflow_id, dataset_id)
    return jsonify(payload), 200
