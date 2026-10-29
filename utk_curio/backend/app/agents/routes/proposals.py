"""An install an agent asked for, applied or dismissed (memo dev/41); an agent's change, undone.

Presentation layer of the agents package (memo dev/142, B4-1; re-derived on enh/agent-catalog): the handlers
of ``routes.py`` by resource, registered on the one ``agents_bp`` from ``routes/common.py``.
"""

from __future__ import annotations

from flask import g
from flask import jsonify

from utk_curio.backend.app.agents import service as agents_services
from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import _svc_error
from utk_curio.backend.app.agents.routes.common import _working_dataflow
from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.app.agents.service import AgentServiceError
from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.dependencies import require_auth


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/proposals/<proposal_id>/apply",
    methods=["POST"],
)
@require_auth
def apply_proposal(project_id: str, attachment_id: str, proposal_id: str):
    """Apply a pending install the person reviewed (memo dev/41): the only
    path that runs an install an agent asked for.

    Explicit, owner-authenticated, revision-safe: a drifted install returns a
    409 and marks the proposal stale. Consumes no quota."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        project_id = _working_dataflow(project_id)
        payload = agents_services.apply_proposal(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/proposals/<proposal_id>",
    methods=["DELETE"],
)
@require_auth
def dismiss_proposal(project_id: str, attachment_id: str, proposal_id: str):
    """Dismiss a pending install without applying it."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        project_id = _working_dataflow(project_id)
        payload = agents_services.dismiss_proposal(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/changes/<change_id>/undo",
    methods=["POST"],
)
@require_auth
def undo_change(project_id: str, attachment_id: str, change_id: str):
    """Undo a change the attachment's agent made, as the caller's own change,
    by its kind (``proposals/changes.py``): a node's code gets its before
    back, a new node goes with its connections, settings get their old
    values back, a plan puts back the version before it. A 409 says who
    changed it after, when someone did: then nothing is undone. The answer
    carries the canvas mutations a canvas no doc binds takes."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        project_id = _working_dataflow(project_id)
        payload = agents_services.undo_change(
            _user_dir_key(g.user), project_id, attachment_id, change_id, g.user
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200
