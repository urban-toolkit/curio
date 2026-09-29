"""One chat turn on an attachment: blocking, or streamed as Server-Sent Events.

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
from utk_curio.backend.app.agents.infrastructure.provider_config import ProviderConfigError
from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import _llm_for_attachment
from utk_curio.backend.app.agents.routes.common import _provider_error
from utk_curio.backend.app.agents.routes.common import _svc_error
from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.app.agents.service import AgentServiceError
from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.dependencies import require_auth


@agents_bp.route("/projects/<project_id>/attachments/<attachment_id>/run", methods=["POST"])
@require_auth
def run_attachment(project_id: str, attachment_id: str):
    """Run one turn of an attached agent and return its reply."""

    body = request.get_json(silent=True) or {}
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return _error("body must include a non-empty 'message'")
    run_context = body.get("context")
    if run_context is not None and not isinstance(run_context, str):
        return _error("'context' must be a string when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = _llm_for_attachment(project_id, attachment_id)
        payload = agents_services.run_attachment(
            _user_dir_key(g.user), project_id, attachment_id, message, config, run_context
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _provider_error(exc)
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
    first delta, repeated ``event: delta`` chunks, ``event: usage``
    (``{usage}``, interim Actual sums once per provider round, memo dev/80),
    ``event: content``
    (``{parts}``, memo dev/39) when the reply carried a valid structured tail,
    then ``event: done`` with ``{reply, executionId, usage, durationMs,
    content}``; a
    provider failure emits ``event: error`` and ends the stream. Additive and
    backward-compatible — old clients skip unknown event names. Validation
    errors (404/422/…) return normal JSON statuses before any streaming
    starts. Session persistence matches the blocking run.
    """

    body = request.get_json(silent=True) or {}
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return _error("body must include a non-empty 'message'")
    run_context = body.get("context")
    if run_context is not None and not isinstance(run_context, str):
        return _error("'context' must be a string when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = _llm_for_attachment(project_id, attachment_id)
        events = agents_services.stream_attachment(
            _user_dir_key(g.user), project_id, attachment_id, message, config, run_context
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _provider_error(exc)
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
