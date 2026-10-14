"""Routes of published dashboards (``service.py``).

The owner publishes, republishes and unpublishes a dataflow's dashboard under
``/api/projects/<id>/publish`` (signed in). Whoever holds the link reads what
it lets them set and starts runs under ``/api/published/<token>`` (signed in
only when the owner asked for it), and follows a run, cancels it and reads its
artifacts under ``/api/published/runs/<runId>`` with the run's key, which the
start returned and nothing else knows.
"""
from __future__ import annotations

import json
import time

from flask import Blueprint, Response, g, jsonify, request, stream_with_context

from utk_curio.backend.app.published import service
from utk_curio.backend.app.published.service import PublishError
from utk_curio.backend.app.users.dependencies import get_current_user, require_auth

published_bp = Blueprint("published", __name__)

#: The largest run request a viewer may send: values only, never code.
MAX_RUN_BODY = 64 * 1024


def _error(exc: PublishError):
    return jsonify({"error": str(exc)}), exc.status


# ---------------------------------------------------------------------------
# The owner
# ---------------------------------------------------------------------------

@published_bp.route("/api/projects/<project_id>/publish", methods=["GET"])
@require_auth
def get_publication(project_id: str):
    try:
        return jsonify({"published": service.get_publication(g.user, project_id)})
    except PublishError as exc:
        return _error(exc)


@published_bp.route("/api/projects/<project_id>/publish", methods=["PUT"])
@require_auth
def publish(project_id: str):
    body = request.get_json(silent=True) or {}
    try:
        return jsonify({"published": service.publish(g.user, project_id, body.get("access", "link"))})
    except PublishError as exc:
        return _error(exc)


@published_bp.route("/api/projects/<project_id>/publish", methods=["DELETE"])
@require_auth
def unpublish(project_id: str):
    try:
        service.unpublish(g.user, project_id)
    except PublishError as exc:
        return _error(exc)
    return "", 204


# ---------------------------------------------------------------------------
# Whoever holds the link
# ---------------------------------------------------------------------------

@published_bp.route("/api/published/<token>", methods=["GET"])
def describe(token: str):
    try:
        return jsonify(service.describe(token))
    except PublishError as exc:
        return _error(exc)


@published_bp.route("/api/published/<token>/runs", methods=["POST"])
def start_run(token: str):
    if (request.content_length or 0) > MAX_RUN_BODY:
        return jsonify({"error": "The request is too large."}), 413
    body = request.get_json(silent=True) or {}
    try:
        started = service.start_run(
            token, body.get("inputs"), user=get_current_user(), address=request.remote_addr or "",
        )
    except PublishError as exc:
        return _error(exc)
    return jsonify(started), 202


def _run_for_request(run_id: str):
    return service.get_run(run_id, request.args.get("key") or "")


@published_bp.route("/api/published/runs/<run_id>", methods=["GET"])
def get_run(run_id: str):
    try:
        return jsonify(service.run_payload(_run_for_request(run_id)))
    except PublishError as exc:
        return _error(exc)


@published_bp.route("/api/published/runs/<run_id>/stream", methods=["GET"])
def stream_run(run_id: str):
    """SSE in the shape of ``/api/runs/<id>/stream``: a ``run`` event, then the
    run's events, replayed and then followed while it goes."""
    try:
        run = _run_for_request(run_id)
    except PublishError as exc:
        return _error(exc)
    head = service.run_payload(run)
    events = service.follow(run)

    def _sse():
        yield f"event: run\ndata: {json.dumps(head)}\n\n"
        for kind, payload in events:
            yield f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@published_bp.route("/api/published/runs/<run_id>/cancel", methods=["POST"])
def cancel_run(run_id: str):
    try:
        run = _run_for_request(run_id)
    except PublishError as exc:
        return _error(exc)
    service.cancel(run)
    return jsonify(service.run_payload(run)), 202


def _artifact(run_id: str, *, path: str, label: str, timeout: int, extra: dict):
    """Relay one of the run's artifacts from the sandbox, read under the run's key."""
    from utk_curio.backend.app.api.routes import (
        ARROW_IPC_MIME,
        GEOMETRY_ACCEPT_HEADER,
        _relay_sandbox_reply,
        _sandbox_call,
    )

    try:
        run = _run_for_request(run_id)
    except PublishError as exc:
        return _error(exc)
    file_name = request.args.get("fileName") or ""
    if not service.allows_artifact(run, file_name):
        return jsonify({"error": "This run has no such result."}), 404
    params = {"fileName": file_name, "sessionId": run.key, **extra}
    t0 = time.perf_counter()
    wants_arrow = path == "/get" and request.accept_mimetypes.best == ARROW_IPC_MIME
    if wants_arrow:
        headers = {"Accept": ARROW_IPC_MIME}
        if request.headers.get(GEOMETRY_ACCEPT_HEADER):
            headers[GEOMETRY_ACCEPT_HEADER] = request.headers[GEOMETRY_ACCEPT_HEADER]
        resp = _sandbox_call("get", path, label=label, timeout=timeout, stream=True, params=params, headers=headers)
        if isinstance(resp, tuple):
            return resp
        return _relay_sandbox_reply(resp, label=label, file_name=file_name, t0=t0)
    if path == "/raster":
        resp = _sandbox_call("get", path, label=label, timeout=timeout, stream=True, params=params)
        if isinstance(resp, tuple):
            return resp
        return _relay_sandbox_reply(resp, label=label, file_name=file_name, t0=t0)
    # JSON: read whole, so the parts a bundle names can be read next.
    resp = _sandbox_call("get", path, label=label, timeout=timeout, params=params)
    if isinstance(resp, tuple):
        return resp
    if resp.ok:
        try:
            service.note_artifacts(run, resp.json())
        except ValueError:
            pass
    return Response(resp.content, status=resp.status_code, content_type=resp.headers.get("Content-Type", "application/json"))


@published_bp.route("/api/published/runs/<run_id>/get", methods=["GET"])
def get_artifact(run_id: str):
    from utk_curio.backend.app.api.routes import SANDBOX_GET_TIMEOUT

    return _artifact(run_id, path="/get", label="/published/get", timeout=SANDBOX_GET_TIMEOUT, extra={})


@published_bp.route("/api/published/runs/<run_id>/get-preview", methods=["GET"])
def get_artifact_preview(run_id: str):
    from utk_curio.backend.app.api.routes import SANDBOX_PREVIEW_TIMEOUT

    return _artifact(
        run_id, path="/get", label="/published/get-preview", timeout=SANDBOX_PREVIEW_TIMEOUT,
        extra={"maxRows": 100},
    )


@published_bp.route("/api/published/runs/<run_id>/raster", methods=["GET"])
def get_raster(run_id: str):
    from utk_curio.backend.app.api.routes import SANDBOX_RASTER_TIMEOUT

    extra = {k: request.args[k] for k in ("part", "maxCells", "maxSide") if request.args.get(k) is not None}
    return _artifact(run_id, path="/raster", label="/published/raster", timeout=SANDBOX_RASTER_TIMEOUT, extra=extra)
