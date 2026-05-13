"""Flask blueprint: /api/projects — all endpoints require @require_auth."""
from __future__ import annotations

from dataclasses import asdict
from flask import Blueprint, g, jsonify, request

from utk_curio.backend.app.users.dependencies import require_auth
from utk_curio.backend.app.projects import services
from utk_curio.backend.app.projects.repositories import NotFoundError
from utk_curio.backend.app.projects.schemas import (
    OutputRef,
    ProjectCreate,
    ProjectUpdate,
)
from utk_curio.backend.app.projects.services import ProjectError

projects_bp = Blueprint("projects_api", __name__, url_prefix="/api/projects")


def _error(msg: str, status: int = 400):
    return jsonify({"error": msg}), status


# ---------------------------------------------------------------------------
# POST /api/projects — create
# ---------------------------------------------------------------------------
@projects_bp.route("", methods=["POST"])
@require_auth
def create_project():
    body = request.get_json(silent=True) or {}
    try:
        data = ProjectCreate(
            name=body.get("name", ""),
            spec=body.get("spec", {}),
            outputs=[
                OutputRef(**o) if isinstance(o, dict) else o
                for o in body.get("outputs", [])
            ],
            description=body.get("description"),
            thumbnail_accent=body.get("thumbnail_accent", "peach"),
        )
    except (ValueError, TypeError) as exc:
        return _error(str(exc))

    try:
        detail = services.save_project(g.user, data)
    except ProjectError as exc:
        return _error(str(exc), exc.status)

    return jsonify(asdict(detail)), 201


# ---------------------------------------------------------------------------
# PUT /api/projects/:id — update
# ---------------------------------------------------------------------------
@projects_bp.route("/<project_id>", methods=["PUT"])
@require_auth
def update_project(project_id: str):
    body = request.get_json(silent=True) or {}
    raw_outputs = None
    if "outputs" in body and body.get("outputs") is not None:
        raw_outputs = [
            OutputRef(**o) if isinstance(o, dict) else o
            for o in body.get("outputs", [])
        ]
    try:
        data = ProjectUpdate(
            spec=body.get("spec") if "spec" in body else None,
            outputs=raw_outputs,
            name=body.get("name"),
            description=body.get("description"),
            thumbnail_accent=body.get("thumbnail_accent"),
        )
    except (ValueError, TypeError) as exc:
        return _error(str(exc))

    try:
        detail = services.update_project(g.user, project_id, data)
    except NotFoundError:
        return _error("Project not found", 404)
    except ProjectError as exc:
        return _error(str(exc), exc.status)

    return jsonify(asdict(detail)), 200


# ---------------------------------------------------------------------------
# GET /api/projects — list
# ---------------------------------------------------------------------------
@projects_bp.route("", methods=["GET"])
@require_auth
def list_projects():
    scope = request.args.get("scope", "mine")
    sort = request.args.get("sort", "last_opened")
    try:
        summaries = services.list_projects(g.user, scope=scope, sort=sort)
    except ProjectError as exc:
        return _error(str(exc), exc.status)

    return jsonify([asdict(s) for s in summaries]), 200


# ---------------------------------------------------------------------------
# GET /api/projects/:id — detail + hydration
# ---------------------------------------------------------------------------
@projects_bp.route("/<project_id>", methods=["GET"])
@require_auth
def get_project(project_id: str):
    try:
        result = services.load_project(g.user, project_id)
    except NotFoundError:
        return _error("Project not found", 404)
    except ProjectError as exc:
        return _error(str(exc), exc.status)

    return jsonify({
        "project": asdict(result["project"]),
        "spec": result["spec"],
        "outputs": result["outputs"],
    }), 200


# ---------------------------------------------------------------------------
# GET /api/projects/:id/shared — link-based public read (no auth)
# ---------------------------------------------------------------------------
@projects_bp.route("/<project_id>/shared", methods=["GET"])
def get_shared_project(project_id: str):
    try:
        result = services.load_shared_project(project_id)
    except NotFoundError:
        return _error("Project not found", 404)
    except ProjectError as exc:
        return _error(str(exc), exc.status)

    return jsonify({
        "project": asdict(result["project"]),
        "spec": result["spec"],
        "outputs": result["outputs"],
    }), 200


# ---------------------------------------------------------------------------
# DELETE /api/projects/:id
# ---------------------------------------------------------------------------
@projects_bp.route("/<project_id>", methods=["DELETE"])
@require_auth
def delete_project(project_id: str):
    purge = request.args.get("purge", "false").lower() == "true"
    try:
        services.delete_project(g.user, project_id, purge=purge)
    except NotFoundError:
        return _error("Project not found", 404)
    except ProjectError as exc:
        return _error(str(exc), exc.status)

    return "", 204


# ---------------------------------------------------------------------------
# POST /api/projects/:id/duplicate
# ---------------------------------------------------------------------------
@projects_bp.route("/<project_id>/duplicate", methods=["POST"])
@require_auth
def duplicate_project(project_id: str):
    try:
        detail = services.duplicate_project(g.user, project_id)
    except NotFoundError:
        return _error("Project not found", 404)
    except ProjectError as exc:
        return _error(str(exc), exc.status)

    return jsonify(asdict(detail)), 201
