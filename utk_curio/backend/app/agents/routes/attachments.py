"""Attachments — private agent instances on a node, the canvas or a

Presentation layer of the agents package (memo dev/142, B4-1; re-derived on enh/agent-catalog): the handlers
of ``routes.py`` by resource, bodies verbatim, registered on the one ``agents_bp`` from ``routes/common.py``.
"""

from __future__ import annotations

import json
from flask import Response
from flask import g
from flask import jsonify
from flask import request
from flask import stream_with_context

from utk_curio.backend.app.agents import service as agents_services
from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import _svc_error
from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.app.agents.service import AgentServiceError
from utk_curio.backend.app.agents.infrastructure import agent_jobs as agents_agent_jobs
from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.dependencies import require_auth


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
    "/projects/<project_id>/attachments/<attachment_id>/dataset-selection",
    methods=["POST"],
)
@require_auth
def record_dataset_selection(project_id: str, attachment_id: str):
    """dev/126: record the confirmed dataset selection for this node.

    ``{"picks": [{"lane": "catalog"|"external", "key": "<datasetId>|<url>"}]}``
    — identifiers only, resolved server-side against the candidates the runtime
    itself proposed in this attachment's session; anything else is a 422. The
    node's next Solve reads the record instead of asking the model what the
    user picked.
    """

    body = request.get_json(silent=True) or {}
    if "picks" not in body:
        return _error("body must include 'picks'")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        # dev/132: a confirmed fetchable source is delegated to the node's own
        # builder, on the builder's LLM configuration. A selection is recorded
        # either way (the delegation says why a build did not start).
        payload = agents_services.record_dataset_selection(
            _user_dir_key(g.user), project_id, attachment_id, body.get("picks"),
            guest=bool(getattr(g.user, "is_guest", False)),
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
    "/projects/<project_id>/attachments/<attachment_id>/jobs/stream", methods=["GET"]
)
@require_auth
def attach_job_stream(project_id: str, attachment_id: str):
    """dev/115 (DEC-021 single-process slice): re-attach to the attachment's
    background job — the running Solve batch or per-node Solve, or the most
    recent finished one still within the replay window. Replays every event
    so far, then tails live ones; 404 when there is nothing to attach to."""

    try:
        projects_repo.get_for_user(project_id, g.user.id)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    job = agents_agent_jobs.latest_job(_user_dir_key(g.user), attachment_id)
    if job is None or job.project_id != project_id:
        return _error("no background job for this attachment", 404)
    events = agents_agent_jobs.subscribe(job)

    def _sse():
        yield f"event: job\ndata: {json.dumps(job.to_payload())}\n\n"
        for kind, payload in events:
            data = {"error": payload} if kind == "error" else payload
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
