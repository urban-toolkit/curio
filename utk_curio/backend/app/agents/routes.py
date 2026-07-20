"""HTTP endpoints for the Agents Catalog — ``/api/agents``.

Thin blueprint over ``app/agents/services.py``, mirroring ``app/packages/routes.py``:
``@require_auth`` + ``_user_dir_key`` for the storage key, and
``projects_repo.get_for_user`` for project ownership. Import and Install are
separate explicit endpoints; nothing auto-chains.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.dependencies import require_auth

from utk_curio.backend.app.agents import services as agents_services
from utk_curio.backend.app.agents.services import AgentServiceError

agents_bp = Blueprint("agents_api", __name__, url_prefix="/api/agents")


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _svc_error(exc: AgentServiceError):
    return jsonify({"error": str(exc)}), exc.status


# ── My Imports (account scope) ───────────────────────────────────────────────
@agents_bp.route("/imports", methods=["GET"])
@require_auth
def list_imports():
    return jsonify({"agents": agents_services.list_my_imports(_user_dir_key(g.user))}), 200


@agents_bp.route("/imports", methods=["POST"])
@require_auth
def import_agent():
    body = request.get_json(silent=True) or {}
    coord = body.get("coord")
    if not isinstance(coord, str):
        return _error("body must include 'coord'")
    try:
        payload = agents_services.import_agent(_user_dir_key(g.user), coord)
    except AgentServiceError as exc:
        return _svc_error(exc)
    except ValueError as exc:
        return _error(str(exc))
    return jsonify(payload), 201


@agents_bp.route("/imports/<coord>", methods=["DELETE"])
@require_auth
def remove_import(coord: str):
    return jsonify(agents_services.remove_import(_user_dir_key(g.user), coord)), 200


# ── Installed in this project ────────────────────────────────────────────────
@agents_bp.route("/projects/<project_id>", methods=["GET"])
@require_auth
def list_project_agents(project_id: str):
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        agents = agents_services.list_installed_in_project(_user_dir_key(g.user), project_id)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify({"agents": agents}), 200


@agents_bp.route("/projects/<project_id>/install", methods=["POST"])
@require_auth
def install_in_project(project_id: str):
    body = request.get_json(silent=True) or {}
    coord = body.get("coord")
    if not isinstance(coord, str):
        return _error("body must include 'coord'")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.install_in_project(_user_dir_key(g.user), project_id, coord)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 201


@agents_bp.route("/projects/<project_id>/<coord>", methods=["DELETE"])
@require_auth
def uninstall_from_project(project_id: str, coord: str):
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.uninstall_from_project(_user_dir_key(g.user), project_id, coord)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200
