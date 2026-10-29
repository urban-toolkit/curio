"""Flask blueprint: /api/projects - all endpoints require @require_auth."""
from __future__ import annotations

import re
from dataclasses import asdict
from flask import Blueprint, current_app, g, jsonify, request

from utk_curio.backend.app.users.dependencies import get_current_token, require_auth
from utk_curio.backend.app.projects import services
from utk_curio.backend.app.projects import visitor_copies
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
            copy_of=body.get("copy_of"),
        )
    except (ValueError, TypeError) as exc:
        return _error(str(exc))

    try:
        detail = services.save_project(g.user, data, sign_in=get_current_token())
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


_TAB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _optional_tab(value):
    """A tab id as the page makes one (a UUID), or ``None`` for anything else,
    which leaves the save unchecked, as a malformed basis does."""
    if isinstance(value, str) and _TAB_ID.fullmatch(value):
        return value
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
            # Which tab sent this save, and its number among the tab's saves.
            save_tab=_optional_tab(body.get("saveTab", body.get("save_tab"))),
            save_number=_optional_int(body.get("saveNumber", body.get("save_number"))),
            # A tab bound to the dataflow's doc sends its history, not the dataflow.
            history=body.get("history"),
        )
    except (ValueError, TypeError) as exc:
        return _error(str(exc))

    try:
        detail = services.update_project(g.user, project_id, data, sign_in=get_current_token())
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
# GET /api/projects/:id - detail and saved outputs
# ---------------------------------------------------------------------------
@projects_bp.route("/<project_id>", methods=["GET"])
@require_auth
def get_project(project_id: str):
    """The dataflow, its spec and its outputs: the saved ones, or, with
    ``?results=last``, the results its canvas was left with, as a canvas
    opens it (``services.load_project``)."""
    try:
        result = services.load_project(
            g.user, project_id, last_results=request.args.get("results") == "last",
        )
    except NotFoundError:
        return _error("Project not found", 404)
    except ProjectError as exc:
        return _error(str(exc), exc.status)

    # A hosted guest's canvas opens the copy its agents work on, once they
    # have written one (visitor_copies.py).
    project, spec = result["project"], result["spec"]
    own = visitor_copies.canvas_spec(g.user, project_id)
    if own is not None:
        project, spec = visitor_copies.with_spec(project, own), own
    return jsonify({
        "project": asdict(project),
        "spec": spec,
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
# /api/projects/:id/editors - who the owner invited to edit (projects/access.py)
# ---------------------------------------------------------------------------
@projects_bp.route("/<project_id>/editors", methods=["GET"])
@require_auth
def list_editors(project_id: str):
    """The dataflow's editors, for its owner alone: anyone else is told it is
    not found, as the other owner routes tell them, and a guest is refused."""
    from utk_curio.backend.app.projects import access

    try:
        editors = access.list_editors(g.user, project_id)
    except NotFoundError:
        return _error("Project not found", 404)
    except ProjectError as exc:
        return _error(str(exc), exc.status)
    return jsonify({"editors": editors}), 200


@projects_bp.route("/<project_id>/editors", methods=["POST"])
@require_auth
def add_editor(project_id: str):
    """Invite an account by ``{"username": ...}``; answers with the list."""
    from utk_curio.backend.app.projects import access

    body = request.get_json(silent=True) or {}
    username = body.get("username")
    try:
        editors = access.add_editor(g.user, project_id, username if isinstance(username, str) else "")
    except NotFoundError:
        return _error("Project not found", 404)
    except ProjectError as exc:
        return _error(str(exc), exc.status)
    return jsonify({"editors": editors}), 201


@projects_bp.route("/<project_id>/editors/<int:user_id>", methods=["DELETE"])
@require_auth
def remove_editor(project_id: str, user_id: int):
    """Take an editor off the list; answers with the list."""
    from utk_curio.backend.app.projects import access

    try:
        editors = access.remove_editor(g.user, project_id, user_id)
    except NotFoundError:
        return _error("Not found", 404)
    except ProjectError as exc:
        return _error(str(exc), exc.status)
    return jsonify({"editors": editors}), 200


# ---------------------------------------------------------------------------
# GET /api/projects/:id/outputs/{get,get-preview,raster} - a canvas's reads
# ---------------------------------------------------------------------------
def _output_read(project_id: str):
    """``(fileName, session, saved path or None)`` for a read on this
    dataflow's canvas, or the error to answer. The sandbox reads the name from
    the store under that session first; a name the dataflow saved is then
    read from the file its owner's store holds, in place.

    The session is the caller's, but for the owner's read of an output their
    runs of this dataflow kept (``runs/kept.py``), which is read under the
    session that made it, from any sign-in. No one else reads a kept output
    here."""
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.extensions import db

    file_name = request.args.get("fileName")
    if not file_name:
        return None, None, None, ("No artifact id specified", 400)
    project = db.session.get(Project, project_id)
    if project is None:
        return None, None, None, _error("Project not found", 404)
    saved = services.saved_output_of(project_id, file_name)
    saved_path = saved.path if saved is not None else None
    if project.user_id == getattr(g.user, "id", None):
        entry = kept.owner_entry(project_id, file_name)
        if entry is not None:
            return file_name, entry.session_id, saved_path, None
    return file_name, get_current_token(), saved_path, None


@projects_bp.route("/<project_id>/outputs/get", methods=["GET"])
@require_auth
def get_output(project_id: str):
    """``/get`` for an output on this dataflow's canvas."""
    from utk_curio.backend.app.api.routes import relay_artifact

    file_name, session, saved_path, error = _output_read(project_id)
    return error or relay_artifact(file_name, session, saved_path=saved_path)


@projects_bp.route("/<project_id>/outputs/get-preview", methods=["GET"])
@require_auth
def get_output_preview(project_id: str):
    """``/get-preview`` for an output on this dataflow's canvas."""
    from utk_curio.backend.app.api.routes import relay_preview

    file_name, session, saved_path, error = _output_read(project_id)
    return error or relay_preview(file_name, session, saved_path=saved_path)


@projects_bp.route("/<project_id>/outputs/raster", methods=["GET"])
@require_auth
def get_output_raster(project_id: str):
    """``/raster`` for a raster on this dataflow's canvas."""
    from utk_curio.backend.app.api.routes import relay_raster

    file_name, session, saved_path, error = _output_read(project_id)
    return error or relay_raster(file_name, session, saved_path=saved_path)


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

    A tile whose saved output, or a raster of it, could not be read is a 503
    that says to try again, not a page with that tile drawn without it (#941).

    Every refusal names the dataflow too: the page server carries a refusal in
    the page instead of the data (``cli/static_server.py``), and the page shows
    it under the dataflow's name.
    """
    from utk_curio.backend.app.projects.dashboard_payload import (
        DashboardCannotBeStandaloneError,
        DashboardOutputUnreadableError,
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
    except DashboardOutputUnreadableError as exc:
        return jsonify({"error": exc.describe(), "nodes": exc.offenders, "name": exc.name}), 503
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

    # Not jsonify, which sorts every key: the payload puts each embedded
    # frame's columns back in the frame's own order (#1166), and sorting them
    # again here would show a table's columns alphabetically.
    return current_app.response_class(
        current_app.json.dumps(payload, sort_keys=False, separators=(",", ":")),
        status=200, mimetype=current_app.json.mimetype,
    )


# ---------------------------------------------------------------------------
# GET /api/projects/:id/dashboard/can-edit - may this session edit the layout
# ---------------------------------------------------------------------------
@projects_bp.route("/<project_id>/dashboard/can-edit", methods=["GET"])
@require_auth
def can_edit_dashboard(project_id: str):
    """Whether this session may edit the dashboard's layout: yes or no.

    A dashboard page served with its data has no session of its own, and names
    no account. A browser that holds a session asks here, and the page offers
    Edit layout, Save layout and Arrange on a yes. The answer is the gate a
    save of the layout passes (``services.may_save``), so the controls appear
    exactly where Save layout would be accepted, and it says nothing else about
    the dataflow: an unknown one is a no.
    """
    return jsonify({"canEdit": services.may_save(g.user, project_id)}), 200


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


# ---------------------------------------------------------------------------
# /api/projects/:id/history - the dataflow's history, for its owner and the
# editors the owner invited (services.project_history and the rest)
# ---------------------------------------------------------------------------
def _history_answer(answer, status: int = 200):
    try:
        return jsonify(answer()), status
    except NotFoundError:
        return _error("Project not found", 404)
    except ProjectError as exc:
        return _error(str(exc), exc.status)


@projects_bp.route("/<project_id>/history", methods=["GET"])
@require_auth
def get_history(project_id: str):
    """The dataflow's versions, the one on the canvas, and whether you may
    clear the history."""
    return _history_answer(lambda: services.project_history(g.user, project_id))


@projects_bp.route("/<project_id>/history/nodes/<node_id>", methods=["GET"])
@require_auth
def get_node_history(project_id: str, node_id: str):
    """A node's runs and edits, each with its code."""
    return _history_answer(lambda: services.node_history(g.user, project_id, node_id))


@projects_bp.route("/<project_id>/history/nodes/<node_id>/runs", methods=["POST"])
@require_auth
def post_node_run(project_id: str, node_id: str):
    """A run of the node: ``{code, inputs, outputs, startTime, endTime}``."""
    body = request.get_json(silent=True) or {}
    return _history_answer(lambda: services.record_run(g.user, project_id, node_id, body), 201)


@projects_bp.route("/<project_id>/history/nodes/<node_id>/edits", methods=["POST"])
@require_auth
def post_node_edit(project_id: str, node_id: str):
    """An edit made in the node's body: ``{label}``."""
    body = request.get_json(silent=True) or {}
    return _history_answer(lambda: services.record_edit(g.user, project_id, node_id, body.get("label")), 201)


@projects_bp.route("/<project_id>/history/nodes/<node_id>/code", methods=["POST"])
@require_auth
def post_node_code(project_id: str, node_id: str):
    """Put code back in the node if it still holds what you saw:
    ``{from, code, label}``; 409 when someone changed it after."""
    body = request.get_json(silent=True) or {}
    return _history_answer(lambda: services.write_node_code(g.user, project_id, node_id, body))


@projects_bp.route("/<project_id>/history/saved", methods=["POST"])
@require_auth
def post_saved_version(project_id: str):
    """File > Save: a version named Saved."""
    return _history_answer(lambda: services.record_saved(g.user, project_id), 201)


@projects_bp.route("/<project_id>/history/<point_id>/put-back", methods=["POST"])
@require_auth
def post_put_back(project_id: str, point_id: str):
    """Put a version back on the canvas, for every tab."""
    return _history_answer(lambda: services.put_back_version(g.user, project_id, point_id))


@projects_bp.route("/<project_id>/history/clear", methods=["POST"])
@require_auth
def post_clear_history(project_id: str):
    """The owner clears the history before a version: ``{before}``."""
    body = request.get_json(silent=True) or {}
    before = body.get("before")
    if not isinstance(before, str) or not before:
        return _error("Name the version to keep the history from (before).")
    return _history_answer(lambda: services.clear_history(g.user, project_id, before))
