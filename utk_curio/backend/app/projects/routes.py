"""Flask blueprint: /api/projects - all endpoints require @require_auth."""
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
# POST /api/projects - create
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


def _optional_int(value):
    """``None`` for anything that is not a whole number, so a malformed basis
    is "no opinion" rather than a 400 — the guard's default is today's
    behaviour, and refusing the request would be a worse answer than not
    checking it."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# PUT /api/projects/:id - update
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
            # dev/124: the counter this client last synced with. Accepted in
            # either spelling because the wire is camelCase and the dataclass
            # is not; absent means unchecked.
            base_revision=_optional_int(
                body.get("baseRevision", body.get("base_revision"))
            ),
            categories=body.get("categories"),
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
# GET /api/projects - list
# ---------------------------------------------------------------------------
@projects_bp.route("", methods=["GET"])
@require_auth
def list_projects():
    # ``?scope=`` is no longer read: every value it accepted returned the same
    # set once Archive went (#261), so the parameter and the "Recent" tab that
    # sent it were removed (#286). An old client still passing it is ignored
    # rather than rejected — it was always getting these rows anyway.
    sort = request.args.get("sort", "last_opened")
    try:
        summaries = services.list_projects(g.user, sort=sort)
    except ProjectError as exc:
        return _error(str(exc), exc.status)

    return jsonify([asdict(s) for s in summaries]), 200


# ---------------------------------------------------------------------------
# GET /api/projects/:id - detail + hydration
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
# GET /api/projects/:id/shared - link-based public read (no auth)
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
# GET /api/projects/:id/dashboard - everything a standalone dashboard carries
# ---------------------------------------------------------------------------
@projects_bp.route("/<project_id>/dashboard", methods=["GET"])
def get_dashboard_payload(project_id: str):
    """The spec and the rows for one dashboard, in a single response.

    Unauthenticated for the same reason ``/shared`` is: a dashboard is opened by
    whoever holds the link, and this serves exactly what that page would have
    fetched piecemeal anyway.

    A dashboard whose rows will not fit in a page is a 413 carrying the
    breakdown, not a truncated payload. Falling back to fetching would produce a
    page that looks standalone and is not, and the owner would only find out
    when somebody opened it where the server is unreachable.

    Both refusals name the dataflow too: the page server carries a refusal in
    the page instead of the data (``cli/static_server.py``), and the page shows
    it under the dataflow's name.
    """
    from utk_curio.backend.app.projects.dashboard_payload import (
        DashboardCannotBeStandaloneError,
        DashboardTooLargeError,
    )

    try:
        payload = services.build_standalone_dashboard(project_id)
    except NotFoundError:
        return _error("Project not found", 404)
    except DashboardCannotBeStandaloneError as exc:
        # A tile that loads its own data cannot be published as a page that
        # needs no server. Named here so the owner can move the data upstream,
        # where its output is saved and travels with the page.
        return jsonify({"error": exc.describe(), "tiles": exc.offenders, "name": exc.name}), 409
    except DashboardTooLargeError as exc:
        return jsonify({
            "error": exc.describe(),
            "name": exc.name,
            "totalBytes": exc.total_bytes,
            "limitBytes": exc.limit_bytes,
            "heaviest": [
                {
                    "nodeId": w.node_id,
                    "bytes": w.bytes,
                    "dataType": w.data_type,
                }
                for w in exc.weights[:10]
            ],
        }), 413
    except ProjectError as exc:
        return _error(str(exc), exc.status)

    return jsonify(payload), 200


# ---------------------------------------------------------------------------
# DELETE /api/projects/:id
# ---------------------------------------------------------------------------
@projects_bp.route("/<project_id>", methods=["DELETE"])
@require_auth
def delete_project(project_id: str):
    try:
        services.delete_project(g.user, project_id)
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
