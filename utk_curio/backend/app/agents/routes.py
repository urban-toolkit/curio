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


# ── Global Catalog (built-in definitions) ────────────────────────────────────
@agents_bp.route("/catalog", methods=["GET"])
@require_auth
def list_catalog():
    """The Global Catalog scope — built-in agent definitions available to import/install.

    Optional ``?projectId=`` marks which are already installed in that project.
    """
    project_id = request.args.get("projectId") or None
    agents = agents_services.list_global_catalog(_user_dir_key(g.user), project_id)
    return jsonify({"agents": agents}), 200


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


# ── Publish to the Global Catalog (imported-only) ────────────────────────────
@agents_bp.route("/publications", methods=["POST"])
@require_auth
def publish_agent():
    body = request.get_json(silent=True) or {}
    coord = body.get("coord")
    if not isinstance(coord, str):
        return _error("body must include 'coord'")
    try:
        payload = agents_services.publish_agent(_user_dir_key(g.user), coord)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 201


@agents_bp.route("/publications/<coord>", methods=["DELETE"])
@require_auth
def unpublish_agent(coord: str):
    try:
        payload = agents_services.unpublish_agent(_user_dir_key(g.user), coord)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


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


# ── Attachments (private agent instances on a node/canvas/connection) ─────────
@agents_bp.route("/projects/<project_id>/attachments", methods=["GET"])
@require_auth
def list_attachments(project_id: str):
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        att = agents_services.list_project_attachments(_user_dir_key(g.user), project_id)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify({"attachments": att}), 200


@agents_bp.route("/projects/<project_id>/attachments", methods=["POST"])
@require_auth
def attach_agent(project_id: str):
    body = request.get_json(silent=True) or {}
    coord = body.get("coord")
    target = body.get("target")
    if not isinstance(coord, str):
        return _error("body must include 'coord'")
    if not isinstance(target, dict):
        return _error("body must include a 'target' object")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.attach_agent(_user_dir_key(g.user), project_id, coord, target)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 201


@agents_bp.route("/projects/<project_id>/attachments/<attachment_id>", methods=["DELETE"])
@require_auth
def detach_agent(project_id: str, attachment_id: str):
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.detach_agent(_user_dir_key(g.user), project_id, attachment_id)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route("/projects/<project_id>/attachments/<attachment_id>", methods=["PATCH"])
@require_auth
def update_attachment(project_id: str, attachment_id: str):
    """Update the attachment's editable intent. ``{"intent": null|""}`` clears the
    override so the intent falls back to the definition's prompt source."""
    body = request.get_json(silent=True) or {}
    if "intent" not in body:
        return _error("body must include 'intent' (string or null)")
    intent = body.get("intent")
    if intent is not None and not isinstance(intent, str):
        return _error("'intent' must be a string or null")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.update_attachment_intent(
            _user_dir_key(g.user), project_id, attachment_id, intent
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/session", methods=["GET"]
)
@require_auth
def get_attachment_session(project_id: str, attachment_id: str):
    """The attachment's persisted chat transcript (its session history)."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.get_attachment_session(
            _user_dir_key(g.user), project_id, attachment_id
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/session", methods=["DELETE"]
)
@require_auth
def clear_attachment_session(project_id: str, attachment_id: str):
    """Clear the transcript; the attachment and its session id are kept."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.clear_attachment_session(
            _user_dir_key(g.user), project_id, attachment_id
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route("/projects/<project_id>/attachments/<attachment_id>/run", methods=["POST"])
@require_auth
def run_attachment(project_id: str, attachment_id: str):
    """Run one turn of an attached agent and return its reply."""
    # Lazy import: the provider-config resolver is the request-layer glue in the
    # main api routes; importing it lazily avoids any startup import ordering.
    from utk_curio.backend.app.agents.providers import ProviderConfig
    from utk_curio.backend.app.api.routes import _resolve_llm_config

    body = request.get_json(silent=True) or {}
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return _error("body must include a non-empty 'message'")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        api_key, api_type, base_url, model = _resolve_llm_config()
        config = ProviderConfig(api_key=api_key, api_type=api_type, base_url=base_url, model=model)
        payload = agents_services.run_attachment(
            _user_dir_key(g.user), project_id, attachment_id, message, config
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200
