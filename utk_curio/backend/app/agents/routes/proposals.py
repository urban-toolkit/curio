"""Review-before-apply (memo dev/41): apply, apply one plan node, apply plan

Presentation layer of the agents package (memo dev/142, B4-1; re-derived on enh/agent-catalog): the handlers
of ``routes.py`` by resource, bodies verbatim, registered on the one ``agents_bp`` from ``routes/common.py``.
"""

from __future__ import annotations

from flask import g
from flask import jsonify
from flask import request

from utk_curio.backend.app.agents import service as agents_services
from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import _svc_error
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
    """Apply a pending review proposal (memo dev/41) — the only mutation path.

    Explicit, owner-authenticated, revision-safe: a drifted target returns a
    409 and marks the proposal stale. Consumes no quota."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.apply_proposal(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/proposals/<proposal_id>/apply-node",
    methods=["POST"],
)
@require_auth
def apply_plan_node(project_id: str, attachment_id: str, proposal_id: str):
    """Apply ONE planned node from a pending dataflow-plan proposal
    (dev/67-5, Simulation Mode: create). Body: ``{"ref": "<plan ref>"}``.
    The proposal stays pending until every ref is applied or it is dismissed;
    edges are the connection stage's concern (67-8)."""
    body = request.get_json(silent=True) or {}
    ref = body.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        return _error("body must include a non-empty 'ref'")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.apply_plan_node(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id, ref.strip()
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/proposals/<proposal_id>/apply-edges",
    methods=["POST"],
)
@require_auth
def apply_plan_edges(project_id: str, attachment_id: str, proposal_id: str):
    """Apply plan edges — the connection review stage (dev/67-8). Body:
    optional ``{"edges": [index, …]}`` for a subset (default: every
    not-yet-applied edge). Refusals are per-edge and named; partial success
    is reported honestly, never all-or-nothing."""
    body = request.get_json(silent=True) or {}
    indices = body.get("edges")
    if indices is not None and not (
        isinstance(indices, list) and all(isinstance(i, int) for i in indices)
    ):
        return _error("'edges' must be a list of integer indices when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.apply_plan_edges(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id, indices
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/proposals/<proposal_id>/plan-goals",
    methods=["PATCH"],
)
@require_auth
def set_plan_goal(project_id: str, attachment_id: str, proposal_id: str):
    """Edit one planned node's goal before creation (dev/67-5): an audited
    review-stage overlay — the pinned plan bytes stay immutable. Body:
    ``{"ref": "<plan ref>", "goal": "<edited goal>"}``. Pending only."""
    body = request.get_json(silent=True) or {}
    ref = body.get("ref")
    goal = body.get("goal")
    if not isinstance(ref, str) or not ref.strip():
        return _error("body must include a non-empty 'ref'")
    if not isinstance(goal, str):
        return _error("body must include a 'goal' string")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.set_plan_goal(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id,
            ref.strip(), goal,
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
    """Dismiss a pending review proposal without applying it."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.dismiss_proposal(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200
