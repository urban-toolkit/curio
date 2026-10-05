"""Solve and its relatives, mostly as Server-Sent Events: the batch, its

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


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/solve", methods=["POST"]
)
@require_auth
def solve_attachment(project_id: str, attachment_id: str):
    """The dev/52 Solve batch (DEC-048): one explicit, owner-authenticated
    action fills the applied plan's pending nodes through bounded-concurrency
    depth-1 children. The endpoint consumes no quota; each child reserves
    under its own policy. Body: optional ``{"nodeIds": [...]}`` for Retry."""

    body = request.get_json(silent=True) or {}
    node_ids = body.get("nodeIds")
    if node_ids is not None and not (
        isinstance(node_ids, list) and all(isinstance(n, str) for n in node_ids)
    ):
        return _error("'nodeIds' must be a list of node id strings when present")
    verify = body.get("verify", True)
    if not isinstance(verify, bool):
        return _error("'verify' must be a boolean when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = _llm_for_attachment(project_id, attachment_id)
        payload = agents_services.solve_attachment(
            _user_dir_key(g.user), project_id, attachment_id, config, node_ids,
            verify=verify,
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _provider_error(exc)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/solve/stream", methods=["POST"]
)
@require_auth
def solve_attachment_stream(project_id: str, attachment_id: str):
    """The Solve batch as Server-Sent Events (dev/63, the DEC-021 user
    slice): ``solve_started`` → ``node_started``/``node_result`` per target →
    ``done`` (the blocking payload + ``cancelled``/``notAttempted``). dev/115:
    a verified data-loading node also streams ``node_round`` /
    ``node_executed`` / ``node_verdict`` while its code runs in the sandbox;
    ``verify: false`` in the body keeps the legacy unexecuted write.
    Validation errors (409/404/…) return normal JSON statuses before any
    streaming starts; the persisted session stays the single truth."""

    body = request.get_json(silent=True) or {}
    node_ids = body.get("nodeIds")
    if node_ids is not None and not (
        isinstance(node_ids, list) and all(isinstance(n, str) for n in node_ids)
    ):
        return _error("'nodeIds' must be a list of node id strings when present")
    mode = body.get("mode", "write")
    if mode not in ("write", "propose"):
        return _error("'mode' must be 'write' or 'propose' when present")
    verify = body.get("verify", True)
    if not isinstance(verify, bool):
        return _error("'verify' must be a boolean when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = _llm_for_attachment(project_id, attachment_id)
        events = agents_services.solve_attachment_stream(
            _user_dir_key(g.user), project_id, attachment_id, config, node_ids,
            mode=mode, verify=verify,
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _provider_error(exc)
    except AgentServiceError as exc:
        return _svc_error(exc)

    def _sse():
        for kind, payload in events:
            data = {"error": payload} if kind == "error" else payload
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/simulate", methods=["POST"]
)
@require_auth
def simulate(project_id: str, attachment_id: str):
    """The Simulation Mode driver (dev/67-9, DEC-054) as Server-Sent Events.
    Body: ``{"mode": "step"|"auto"}`` (default step). Auto runs
    create → validate → auto-approve-on-PASS per node in topological order,
    then the connection stage — pausing on any failure with the reason and
    the pending review. Resume = calling this endpoint again."""

    body = request.get_json(silent=True) or {}
    mode = body.get("mode", "step")
    if mode not in ("step", "auto"):
        return _error("'mode' must be 'step' or 'auto' when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = _llm_for_attachment(project_id, attachment_id)
        events = agents_services.simulate_stream(
            _user_dir_key(g.user), project_id, attachment_id, config, mode=mode
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _provider_error(exc)
    except AgentServiceError as exc:
        return _svc_error(exc)

    def _sse():
        for kind, payload in events:
            data = {"error": payload} if kind == "error" else payload
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/simulate/cancel", methods=["POST"]
)
@require_auth
def cancel_simulate(project_id: str, attachment_id: str):
    """Cancel a running simulation (dev/67-9): stops at the next action
    boundary; everything already done stays done."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.request_simulate_cancel(
            _user_dir_key(g.user), project_id, attachment_id
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/run-node", methods=["POST"]
)
@require_auth
def run_node(project_id: str, attachment_id: str):
    """Run the dataflow THROUGH one node (dev/71): the saved content executes
    through its upstream chain; every execution journals as a real run, so
    agents can read the outcome via node.runtime.read. Body:
    ``{"ref": "<plan ref>"}`` or ``{"nodeId": "<node id>"}``. SSE."""
    body = request.get_json(silent=True) or {}
    ref = body.get("ref")
    node_id = body.get("nodeId")
    if ref is not None and not isinstance(ref, str):
        return _error("'ref' must be a string when present")
    if node_id is not None and not isinstance(node_id, str):
        return _error("'nodeId' must be a string when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        events = agents_services.run_node_stream(
            _user_dir_key(g.user), project_id, attachment_id,
            ref=ref or None, node_id=node_id or None,
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)

    def _sse():
        for kind, payload in events:
            data = {"error": payload} if kind == "error" else payload
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/solve-node", methods=["POST"]
)
@require_auth
def solve_node(project_id: str, attachment_id: str):
    """dev/115 (DEC-073, Amendment A2): the per-node Solve — the user's
    explicit ask to run, fix, and re-run ONE node's code from the node's own
    agent. Body: ``{"nodeId": "<node id>"}``. Round 0 executes the current
    content; corrections run the shared loop; a node that had content lands
    as an already-executed content review, an empty one is written on PASS.
    Detached: the response subscribes to the job (replay + tail); closing it
    does not stop the run — ``GET …/jobs/stream`` re-attaches."""

    body = request.get_json(silent=True) or {}
    node_id = body.get("nodeId")
    if not isinstance(node_id, str) or not node_id:
        return _error("'nodeId' is required")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = _llm_for_attachment(project_id, attachment_id)
        events = agents_services.solve_node_stream(
            _user_dir_key(g.user), project_id, attachment_id, config, node_id=node_id,
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _provider_error(exc)
    except AgentServiceError as exc:
        return _svc_error(exc)

    def _sse():
        for kind, payload in events:
            data = {"error": payload} if kind == "error" else payload
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/validate-node", methods=["POST"]
)
@require_auth
def validate_node(project_id: str, attachment_id: str):
    """Generate → execute-through → validate → self-correct → propose, for ONE
    node, as Server-Sent Events (dev/67-7 — Simulation Mode: validate).
    Body: ``{"ref": "<plan ref>"}`` or ``{"nodeId": "<node id>"}``. The
    outcome lands as a reviewed content proposal carrying the validation
    verdict; the saved spec is never mutated by validation itself."""

    body = request.get_json(silent=True) or {}
    ref = body.get("ref")
    node_id = body.get("nodeId")
    if ref is not None and not isinstance(ref, str):
        return _error("'ref' must be a string when present")
    if node_id is not None and not isinstance(node_id, str):
        return _error("'nodeId' must be a string when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = _llm_for_attachment(project_id, attachment_id)
        events = agents_services.validate_node_stream(
            _user_dir_key(g.user), project_id, attachment_id, config,
            ref=ref or None, node_id=node_id or None,
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _provider_error(exc)
    except AgentServiceError as exc:
        return _svc_error(exc)

    def _sse():
        for kind, payload in events:
            data = {"error": payload} if kind == "error" else payload
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/solve/cancel", methods=["POST"]
)
@require_auth
def cancel_solve(project_id: str, attachment_id: str):
    """Cancel a running Solve (dev/63): stops dispatching new children at the
    next node boundary; in-flight children finish and their results persist;
    undispatched targets revert to pending. 409 when nothing is running."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.request_solve_cancel(
            _user_dir_key(g.user), project_id, attachment_id
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200
