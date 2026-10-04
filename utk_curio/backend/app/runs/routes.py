"""Flask blueprint for dataflow runs on the server. Every route requires sign-in,
and a user sees only the runs they started."""
from __future__ import annotations

import json

from flask import Blueprint, Response, g, jsonify, request, stream_with_context

from utk_curio.backend.app.runs import service
from utk_curio.backend.app.runs.service import RunError
from utk_curio.backend.app.users.dependencies import get_current_token, require_auth

runs_bp = Blueprint("runs_api", __name__)


def _error(exc: RunError):
    return jsonify({"error": str(exc), **exc.extra}), exc.status


def _kind(value):
    """``?kind=all`` is whole-dataflow runs, ``node`` single-node runs."""
    return {"all": True, "node": False}.get(value)


def _paging():
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError as exc:
        raise RunError("limit and offset must be whole numbers", 400) from exc
    return limit, offset


@runs_bp.route("/api/projects/<project_id>/runs", methods=["POST"])
@require_auth
def start_run(project_id: str):
    body = request.get_json(silent=True) or {}
    target = body.get("target")
    reuse = body.get("reuse")
    if target is not None and not isinstance(target, str):
        return jsonify({"error": "'target' must be a node id"}), 400
    if reuse is not None and not isinstance(reuse, dict):
        return jsonify({"error": "'reuse' must map node ids to outputs"}), 400
    revision = body.get("specRevision")
    if revision is not None and (isinstance(revision, bool) or not isinstance(revision, int)):
        return jsonify({"error": "'specRevision' must be a whole number"}), 400
    try:
        run = service.start_run(
            g.user, get_current_token(), project_id,
            target_node_id=target or None, reuse=reuse, spec_revision=revision,
        )
    except RunError as exc:
        return _error(exc)
    return jsonify(service.run_payload(run, steps=True)), 202


@runs_bp.route("/api/projects/<project_id>/runs", methods=["GET"])
@require_auth
def list_project_runs(project_id: str):
    try:
        limit, offset = _paging()
        runs = service.list_project_runs(
            g.user, project_id, whole_dataflow=_kind(request.args.get("kind")),
            limit=limit, offset=offset,
        )
    except RunError as exc:
        return _error(exc)
    return jsonify({"runs": [service.run_payload(run) for run in runs]})


@runs_bp.route("/api/runs", methods=["GET"])
@require_auth
def list_runs():
    try:
        limit, offset = _paging()
        runs = service.list_user_runs(
            g.user, status=request.args.get("status") or None,
            whole_dataflow=_kind(request.args.get("kind")), limit=limit, offset=offset,
        )
    except RunError as exc:
        return _error(exc)
    return jsonify({"runs": [service.run_payload(run) for run in runs]})


@runs_bp.route("/api/runs/<run_id>", methods=["GET"])
@require_auth
def get_run(run_id: str):
    try:
        run = service.get_run(g.user, run_id)
    except RunError as exc:
        return _error(exc)
    return jsonify(service.run_payload(run, steps=True))


@runs_bp.route("/api/runs/<run_id>/stream", methods=["GET"])
@require_auth
def stream_run(run_id: str):
    """SSE: a ``run`` event with the run as it stands, then its events, replayed
    and then followed while it goes. Closing the stream only stops following."""
    try:
        run = service.get_run(g.user, run_id)
    except RunError as exc:
        return _error(exc)
    head = service.run_payload(run, steps=True)
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


@runs_bp.route("/api/runs/<run_id>/cancel", methods=["POST"])
@require_auth
def cancel_run(run_id: str):
    try:
        run = service.cancel_run(g.user, run_id)
    except RunError as exc:
        return _error(exc)
    return jsonify(service.run_payload(run)), 202


@runs_bp.route("/api/runs/<run_id>/rerun", methods=["POST"])
@require_auth
def rerun(run_id: str):
    try:
        run = service.rerun(g.user, get_current_token(), run_id)
    except RunError as exc:
        return _error(exc)
    return jsonify(service.run_payload(run, steps=True)), 202


@runs_bp.route("/api/runs/<run_id>/steps/<node_id>", methods=["POST"])
@require_auth
def report_step(run_id: str, node_id: str):
    """A tab reports a node only the browser runs: ``{status, message?}``."""
    body = request.get_json(silent=True) or {}
    try:
        run = service.report_browser_step(
            g.user, run_id, node_id,
            status=body.get("status"), message=str(body.get("message") or "")[:4000],
        )
    except RunError as exc:
        return _error(exc)
    return jsonify(service.run_payload(run, steps=True))
