"""HTTP routes for the Model Catalog."""

from __future__ import annotations

import functools

from flask import Blueprint, g, jsonify, request

from utk_curio.backend.app.model_catalog.service import ModelCatalogError, ModelCatalogService
from utk_curio.backend.app.users.dependencies import require_auth

models_bp = Blueprint("model_catalog_api", __name__, url_prefix="/api/models")


def _errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ModelCatalogError as exc:
            return jsonify({"error": str(exc)}), exc.status

    return wrapper


def _service() -> ModelCatalogService:
    return ModelCatalogService(getattr(g, "user", None))


@models_bp.route("/catalog", methods=["GET"])
@require_auth
@_errors
def list_models():
    return jsonify(_service().list_catalog(q=request.args.get("q") or None)), 200


@models_bp.route("/<model_id>", methods=["GET"])
@require_auth
@_errors
def get_model(model_id: str):
    return jsonify(_service().get_model(model_id)), 200


@models_bp.route("/<model_id>/license", methods=["GET"])
@require_auth
@_errors
def get_license(model_id: str):
    return jsonify({"text": _service().license_text(model_id)}), 200


@models_bp.route("/<model_id>", methods=["DELETE"])
@require_auth
@_errors
def delete_model(model_id: str):
    return jsonify(_service().delete_model(model_id)), 200
