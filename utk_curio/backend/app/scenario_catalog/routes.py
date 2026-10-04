"""HTTP routes for the Scenario Catalog."""

from __future__ import annotations

import functools

from flask import Blueprint, g, jsonify, request

from utk_curio.backend.app.scenario_catalog.service import ScenarioCatalogError, ScenarioCatalogService
from utk_curio.backend.app.users.dependencies import require_auth

scenarios_bp = Blueprint("scenario_catalog_api", __name__, url_prefix="/api/scenarios")


def _errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ScenarioCatalogError as exc:
            return jsonify({"error": str(exc)}), exc.status

    return wrapper


def _service() -> ScenarioCatalogService:
    return ScenarioCatalogService(getattr(g, "user", None))


@scenarios_bp.route("/catalog", methods=["GET"])
@require_auth
@_errors
def list_scenarios():
    return jsonify(_service().list_catalog(q=request.args.get("q") or None)), 200


@scenarios_bp.route("/<project_id>/<scenario_id>", methods=["GET"])
@require_auth
@_errors
def get_scenario(project_id: str, scenario_id: str):
    return jsonify(_service().get_scenario(project_id, scenario_id)), 200
