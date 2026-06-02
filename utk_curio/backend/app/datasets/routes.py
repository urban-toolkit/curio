"""HTTP routes for the decoupled dataset catalog service."""

from __future__ import annotations

import base64
import json

from flask import Blueprint, g, jsonify, request

from utk_curio.backend.app.datasets.service import DatasetCatalogError, DatasetCatalogService
from utk_curio.backend.app.projects.repositories import NotFoundError
from utk_curio.backend.app.projects.services import ProjectError
from utk_curio.backend.app.users.dependencies import require_auth


datasets_bp = Blueprint("datasets_api", __name__, url_prefix="/api")


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _service() -> DatasetCatalogService:
    return DatasetCatalogService(getattr(g, "user", None))


def _dataflow_id_from_request() -> str | None:
    return request.args.get("dataflowId") or request.args.get("projectId")


@datasets_bp.route("/datasets/catalog", methods=["GET"])
@require_auth
def list_dataset_catalog():
    include_hub = request.args.get("includeHub", "true").lower() not in {"0", "false", "no"}

    # Parse optional live outputs (base64-encoded JSON array of {node_id, filename}).
    # These are the current execution outputs from the frontend that may not yet be
    # saved in the project manifest, allowing computed datasets to appear immediately
    # after node execution.
    live_outputs = None
    raw_live = request.args.get("liveOutputs")
    if raw_live:
        try:
            decoded = base64.b64decode(raw_live.encode()).decode("utf-8")
            parsed = json.loads(decoded)
            if isinstance(parsed, list):
                live_outputs = [
                    {"node_id": o["node_id"], "filename": o["filename"]}
                    for o in parsed
                    if isinstance(o, dict) and o.get("node_id") and o.get("filename")
                ]
        except Exception:  # noqa: BLE001 – malformed payload is silently ignored
            pass

    try:
        payload = _service().list_catalog(
            dataflow_id=_dataflow_id_from_request(),
            q=request.args.get("q") or None,
            fmt=request.args.get("format") or None,
            origin=request.args.get("origin") or None,
            sort=request.args.get("sort", "recent"),
            include_hub=include_hub,
            live_outputs=live_outputs,
        )
    except (DatasetCatalogError, ProjectError) as exc:
        return _error(str(exc), getattr(exc, "status", 400))
    except NotFoundError:
        return _error("Dataflow not found", 404)
    return jsonify(payload), 200


@datasets_bp.route("/datasets/<dataset_id>", methods=["GET"])
@require_auth
def get_dataset(dataset_id: str):
    try:
        payload = _service().get_dataset(dataset_id, dataflow_id=_dataflow_id_from_request())
    except (DatasetCatalogError, ProjectError) as exc:
        return _error(str(exc), getattr(exc, "status", 400))
    except NotFoundError:
        return _error("Dataflow not found", 404)
    return jsonify(payload), 200


@datasets_bp.route("/datasets/<dataset_id>/preview", methods=["GET"])
@require_auth
def preview_dataset(dataset_id: str):
    row_limit = request.args.get("rowLimit", "50")
    offset = request.args.get("offset", "0")
    try:
        payload = _service().preview(
            dataset_id,
            dataflow_id=_dataflow_id_from_request(),
            row_limit=max(1, min(int(row_limit), 500)),
            offset=max(0, int(offset)),
        )
    except ValueError:
        return _error("rowLimit and offset must be integers")
    except (DatasetCatalogError, ProjectError) as exc:
        return _error(str(exc), getattr(exc, "status", 400))
    except NotFoundError:
        return _error("Dataflow not found", 404)
    return jsonify(payload), 200


@datasets_bp.route("/datasets/import", methods=["POST"])
@require_auth
def import_dataset():
    file = request.files.get("file")
    if file is None:
        return _error("No file part")
    try:
        payload = _service().import_dataset(
            file,
            dataflow_id=request.form.get("dataflowId") or request.form.get("projectId"),
            title=request.form.get("title") or None,
        )
    except (DatasetCatalogError, ProjectError) as exc:
        return _error(str(exc), getattr(exc, "status", 400))
    except NotFoundError:
        return _error("Dataflow not found", 404)
    return jsonify(payload), 201


@datasets_bp.route("/datasets/publish", methods=["POST"])
@require_auth
def publish_dataset():
    body = request.get_json(silent=True) or {}
    dataset_id = body.get("datasetId")
    if not dataset_id:
        return _error("datasetId is required")
    live_outputs = body.get("liveOutputs") or None
    try:
        payload = _service().publish_dataset(
            dataset_id,
            body,
            dataflow_id=body.get("dataflowId") or body.get("projectId"),
            live_outputs=live_outputs,
        )
    except (DatasetCatalogError, ProjectError) as exc:
        return _error(str(exc), getattr(exc, "status", 400))
    except NotFoundError:
        return _error("Dataflow not found", 404)
    return jsonify(payload), 201


@datasets_bp.route("/datasets/publish/<dataset_id>", methods=["DELETE"])
@require_auth
def unpublish_dataset(dataset_id: str):
    try:
        payload = _service().unpublish_dataset(
            dataset_id,
            dataflow_id=_dataflow_id_from_request(),
        )
    except (DatasetCatalogError, ProjectError) as exc:
        return _error(str(exc), getattr(exc, "status", 400))
    except NotFoundError:
        return _error("Dataflow not found", 404)
    return jsonify(payload), 200


@datasets_bp.route("/dataflows/<dataflow_id>/datasets/install", methods=["POST"])
@require_auth
def install_dataset(dataflow_id: str):
    body = request.get_json(silent=True) or {}
    dataset_id = body.get("datasetId")
    if not dataset_id:
        return _error("datasetId is required")
    # sourceItem is optionally provided by the frontend for ephemeral computed
    # datasets (live outputs) that don't exist in the persisted catalog yet.
    source_item = body.get("sourceItem") or None
    try:
        payload = _service().install_dataset(dataflow_id, dataset_id, source_item=source_item)
    except (DatasetCatalogError, ProjectError) as exc:
        return _error(str(exc), getattr(exc, "status", 400))
    except NotFoundError:
        return _error("Dataflow not found", 404)
    return jsonify(payload), 200


@datasets_bp.route("/dataflows/<dataflow_id>/datasets/<dataset_id>", methods=["DELETE"])
@require_auth
def uninstall_dataset(dataflow_id: str, dataset_id: str):
    try:
        payload = _service().uninstall_dataset(dataflow_id, dataset_id)
    except (DatasetCatalogError, ProjectError) as exc:
        return _error(str(exc), getattr(exc, "status", 400))
    except NotFoundError:
        return _error("Dataflow not found", 404)
    return jsonify(payload), 200
