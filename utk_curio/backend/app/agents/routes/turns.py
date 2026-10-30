"""Chat turns on an attachment: asked and answered at once, followed, stopped
and withdrawn; and the older blocking and streamed asks.

Presentation layer of the agents package (memo dev/142, B4-1; re-derived on enh/agent-catalog): the handlers
of ``routes.py`` by resource, bodies verbatim, registered on the one ``agents_bp`` from ``routes/common.py``.
A turn is a job of the server (``turns/turn_jobs.py``): every route here asks or acts on one, and a request
that goes away never ends a turn.
"""

from __future__ import annotations

import json
from flask import Response
from flask import jsonify
from flask import request
from flask import stream_with_context

from utk_curio.backend.app.agents import service as agents_services
from utk_curio.backend.app.agents.infrastructure.provider_config import ProviderConfigError
from utk_curio.backend.app.agents.routes.common import _dataflow
from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import _llm_for_attachment
from utk_curio.backend.app.agents.routes.common import _provider_error
from utk_curio.backend.app.agents.routes.common import _svc_error
from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.app.agents.service import AgentServiceError
from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.users.dependencies import require_auth


def _message_and_context():
    """The body's message and context, or the 400 that refuses them."""
    body = request.get_json(silent=True) or {}
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return None, None, _error("body must include a non-empty 'message'")
    run_context = body.get("context")
    if run_context is not None and not isinstance(run_context, str):
        return None, None, _error("'context' must be a string when present")
    return message, run_context, None


def _event_stream(events):
    """*events*, ``(name, data)`` pairs, as Server-Sent Events."""

    def _sse():
        for kind, data in events:
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@agents_bp.route("/projects/<project_id>/attachments/<attachment_id>/turns", methods=["POST"])
@require_auth
def ask_turn(project_id: str, attachment_id: str):
    """Ask one turn of an attached agent, answered at once (202) with
    ``{askId, attachmentId, state}``: its turn runs on the server, now
    (``running``) or once the asks before it on the attachment are done
    (``waiting``), and its events reach the room's tabs that edit the
    dataflow (``agent_turn``). Body: ``{message, context?, askId?}``;
    *askId*, 32 hexadecimal characters the tab chose, names the ask, and an
    ask asked again by its id is the same ask."""

    message, run_context, refused = _message_and_context()
    if refused is not None:
        return refused
    ask_id = (request.get_json(silent=True) or {}).get("askId")
    try:
        flow = _dataflow(project_id)
        config = _llm_for_attachment(flow, attachment_id)
        payload = agents_services.ask_turn(
            flow.key, flow.project_id, attachment_id, message, config, run_context, ask_id=ask_id
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _provider_error(exc)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 202


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/turns/<ask_id>/stream", methods=["GET"]
)
@require_auth
def follow_turn(project_id: str, attachment_id: str, ask_id: str):
    """Follow one ask as Server-Sent Events, for a tab no room holds: one
    ``turn`` event with the ask as it stands (``event: snapshot`` in its
    envelope), then a ``turn`` event for each of its events, in the room's
    envelope, until it ends. 404 for an ask the attachment does not have."""

    try:
        flow = _dataflow(project_id, make=False)
        envelopes = agents_services.follow_turn(flow.key, flow.project_id, attachment_id, ask_id)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return _event_stream(("turn", envelope) for envelope in envelopes)


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/turns/<ask_id>/stop", methods=["POST"]
)
@require_auth
def stop_turn(project_id: str, attachment_id: str, ask_id: str):
    """Stop a running turn: whoever asked it, the owner or an editor. It stops
    at its next step, and its end names who stopped it. 409 when its turn is
    not running."""
    try:
        flow = _dataflow(project_id, make=False)
        payload = agents_services.stop_turn(flow.key, flow.project_id, attachment_id, ask_id)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/turns/<ask_id>", methods=["DELETE"]
)
@require_auth
def withdraw_turn(project_id: str, attachment_id: str, ask_id: str):
    """Withdraw a waiting ask, for whoever asked it alone (403 for anyone
    else). 409 once its turn started."""
    try:
        flow = _dataflow(project_id, make=False)
        payload = agents_services.withdraw_turn(flow.key, flow.project_id, attachment_id, ask_id)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route("/projects/<project_id>/attachments/<attachment_id>/run", methods=["POST"])
@require_auth
def run_attachment(project_id: str, attachment_id: str):
    """Ask one turn of an attached agent and answer its reply once it ended."""

    message, run_context, refused = _message_and_context()
    if refused is not None:
        return refused
    try:
        flow = _dataflow(project_id)
        config = _llm_for_attachment(flow, attachment_id)
        payload = agents_services.run_attachment(
            flow.key, flow.project_id, attachment_id, message, config, run_context
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
    """Ask one turn and follow it as Server-Sent Events (memo dev/22).

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
    starts. Session persistence matches the blocking run. The turn is a job
    of the server: closing the stream stops following it, not the turn,
    which ``turns/<askId>/stream`` follows again by the ``askId`` the body
    may name.
    """

    message, run_context, refused = _message_and_context()
    if refused is not None:
        return refused
    try:
        flow = _dataflow(project_id)
        config = _llm_for_attachment(flow, attachment_id)
        events = agents_services.stream_attachment(
            flow.key, flow.project_id, attachment_id, message, config, run_context,
            ask_id=(request.get_json(silent=True) or {}).get("askId"),
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _provider_error(exc)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return _event_stream(events)
