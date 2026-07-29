"""HTTP endpoints for the Agents Catalog — ``/api/agents``.

Thin blueprint over ``app/agents/services.py``, mirroring ``app/packages/routes.py``:
``@require_auth`` + ``_user_dir_key`` for the storage key, and
``projects_repo.get_for_user`` for project ownership. Import and Install are
separate explicit endpoints; nothing auto-chains.
"""

from __future__ import annotations

import json

from flask import Blueprint, Response, g, jsonify, request, stream_with_context

from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.dependencies import require_auth

from utk_curio.backend.app.agents import services as agents_services
from utk_curio.backend.app.agents.quotas import QuotaExceeded
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


@agents_bp.route("/imports/upload", methods=["POST"])
@require_auth
def upload_import():
    """Upload a user-authored definition (memo dev/36): a JSON body with the
    manifest and its prompt texts. Creates an owned, publishable My Imports
    entry; nothing auto-installs or auto-publishes."""
    body = request.get_json(silent=True) or {}
    try:
        payload = agents_services.upload_import(
            _user_dir_key(g.user), body.get("manifest"), body.get("prompts") or {}
        )
    except AgentServiceError as exc:
        return _svc_error(exc)
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


# ── Account agent settings (the Account-policy scope, memo dev/24) ───────────
@agents_bp.route("/settings", methods=["GET"])
@require_auth
def get_agent_settings():
    return jsonify(agents_services.get_account_settings(_user_dir_key(g.user))), 200


@agents_bp.route("/settings", methods=["PATCH"])
@require_auth
def update_agent_settings():
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("revision"), int):
        return _error("body must include an integer 'revision'")
    if not isinstance(body.get("settings"), dict):
        return _error("body must include a 'settings' object")
    try:
        payload = agents_services.update_account_settings(
            _user_dir_key(g.user), body["revision"], body["settings"]
        )
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


@agents_bp.route("/projects/<project_id>/defaults/<coord>", methods=["GET"])
@require_auth
def get_project_agent_defaults(project_id: str, coord: str):
    """The project-agent-default scope for one installed template (memo dev/23):
    the per-project record plus the effective policy with provenance. Read-only
    at v1 — the Cost/Quotas/Resource screens later edit it."""
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.get_project_agent_defaults(
            _user_dir_key(g.user), project_id, coord
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    # No-secrets provider summary (needs the request user, so it lives here).
    try:
        cfg = resolve_provider_config(g.user)
        payload["effective"]["resources"].update(
            {"provider": cfg.api_type, "model": cfg.model}
        )
    except ProviderConfigError:
        pass  # no provider available (e.g. keyless guest) — summary omitted
    return jsonify(payload), 200


@agents_bp.route("/projects/<project_id>/defaults/<coord>", methods=["PATCH"])
@require_auth
def update_project_agent_defaults(project_id: str, coord: str):
    """Edit one installed template's project defaults (tighten-only, revisioned).
    ``{"settings": {}}`` is `Reset to agent default` for this template."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("revision"), int):
        return _error("body must include an integer 'revision'")
    if not isinstance(body.get("settings"), dict):
        return _error("body must include a 'settings' object")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.update_project_agent_defaults(
            _user_dir_key(g.user), project_id, coord, body["revision"], body["settings"]
        )
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
    """Update the attachment's editable fields.

    ``{"intent": null|""}`` clears the override so the intent falls back to the
    definition's prompt source. ``{"title": "..."}`` manually renames the
    conversation (memo dev/25) — non-empty only; a manual title always wins
    over auto-generation and survives conversation clears.
    """
    body = request.get_json(silent=True) or {}
    if "intent" not in body and "title" not in body:
        return _error("body must include 'intent' (string or null) or 'title' (string)")
    intent = body.get("intent")
    if "intent" in body and intent is not None and not isinstance(intent, str):
        return _error("'intent' must be a string or null")
    title = body.get("title")
    if "title" in body and (not isinstance(title, str) or not title.strip()):
        return _error("'title' must be a non-empty string")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        if "intent" in body:
            payload = agents_services.update_attachment_intent(
                _user_dir_key(g.user), project_id, attachment_id, intent
            )
        if "title" in body:
            payload = agents_services.update_attachment_title(
                _user_dir_key(g.user), project_id, attachment_id, title
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


@agents_bp.route("/projects/<project_id>/attachments/<attachment_id>/run", methods=["POST"])
@require_auth
def run_attachment(project_id: str, attachment_id: str):
    """Run one turn of an attached agent and return its reply."""
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    body = request.get_json(silent=True) or {}
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return _error("body must include a non-empty 'message'")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = resolve_provider_config(g.user)
        payload = agents_services.run_attachment(
            _user_dir_key(g.user), project_id, attachment_id, message, config
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _error(str(exc), 400)
    except QuotaExceeded as exc:
        return (
            jsonify(
                {"error": str(exc), "quota": True, "reason": exc.reason, "resetAt": exc.reset_at}
            ),
            429,
        )
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/run/stream", methods=["POST"]
)
@require_auth
def stream_attachment(project_id: str, attachment_id: str):
    """Run one turn and stream the reply as Server-Sent Events (memo dev/22).

    Emits ``event: execution`` (``{executionId}``, memo dev/37) before the
    first delta, repeated ``event: delta`` chunks, ``event: content``
    (``{parts}``, memo dev/39) when the reply carried a valid structured tail,
    then ``event: done`` with ``{reply, executionId, usage, content}``; a
    provider failure emits ``event: error`` and ends the stream. Additive and
    backward-compatible — old clients skip unknown event names. Validation
    errors (404/422/…) return normal JSON statuses before any streaming
    starts. Session persistence matches the blocking run.
    """
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    body = request.get_json(silent=True) or {}
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return _error("body must include a non-empty 'message'")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = resolve_provider_config(g.user)
        events = agents_services.stream_attachment(
            _user_dir_key(g.user), project_id, attachment_id, message, config
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _error(str(exc), 400)
    except QuotaExceeded as exc:
        return (
            jsonify(
                {"error": str(exc), "quota": True, "reason": exc.reason, "resetAt": exc.reset_at}
            ),
            429,
        )
    except AgentServiceError as exc:
        return _svc_error(exc)

    def _sse():
        for kind, payload in events:
            if kind == "delta":
                data = {"text": payload}
            elif kind == "error":
                data = {"error": payload}
            else:  # execution / content / tool_* / done carry typed dict payloads
                data = payload
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
