"""Flask blueprint for a dashboard viewer's runs (``runs/viewer.py``).

None of these routes needs a sign-in, as the dashboard payload's does not:
whoever can open a dashboard may change its pinned controls. A run is followed
with the token its start answered, sent in ``RUN_TOKEN_HEADER``. Its outputs
are read through the routes below, which name only what the dashboard's kept
outputs hold.
"""
from __future__ import annotations

import json

from flask import Blueprint, Response, jsonify, request, stream_with_context

from utk_curio.backend.app.runs import kept, viewer
from utk_curio.backend.app.runs.service import RunError

dashboard_runs_bp = Blueprint("dashboard_runs_api", __name__)


def _error(exc: RunError):
    return jsonify({"error": str(exc), **exc.extra}), exc.status


def _token():
    return request.headers.get(viewer.RUN_TOKEN_HEADER) or None


@dashboard_runs_bp.route("/api/projects/<project_id>/dashboard/runs", methods=["POST"])
def start(project_id: str):
    """``{values: {nodeId: {widget: value}}, browserOutputs?}``: run the
    dashboard with those values, or join the run of them already going. 202
    with the run and its token, or 200 with no run when nothing needs to run.
    ``browserOutputs`` (``{nodeId: path}``) are the page's results of the
    steps a run left to it, under that run's token."""
    body = request.get_json(silent=True) or {}
    values = body.get("values", {})
    if not isinstance(values, dict):
        return jsonify({"error": "'values' must map node ids to their widgets' values"}), 400
    try:
        started = viewer.start_viewer_run(
            project_id, values, address=request.remote_addr or "unknown",
            token=_token(), browser_outputs=body.get("browserOutputs"),
        )
    except RunError as exc:
        return _error(exc)
    return jsonify(started), 202 if started["runId"] else 200


@dashboard_runs_bp.route("/api/projects/<project_id>/dashboard/runs/<run_id>/steps/<node_id>", methods=["POST"])
def keep_step(project_id: str, run_id: str, node_id: str):
    """``{value}``: what the page made of *node_id*, a step the run left to
    it. Kept for that page alone; 200 with ``{output, artifactIds}``, 413 past
    ``MAX_TAB_RESULT_BYTES``."""
    if (request.content_length or 0) > viewer.MAX_TAB_RESULT_BYTES:
        mib = viewer.MAX_TAB_RESULT_BYTES // (1024 * 1024)
        return jsonify({"error": f"A page's result of a step may hold at most {mib} MB."}), 413
    body = request.get_json(silent=True) or {}
    try:
        result = viewer.keep_tab_result(project_id, run_id, node_id, _token(), body.get("value"))
    except RunError as exc:
        return _error(exc)
    return jsonify(result)


@dashboard_runs_bp.route("/api/projects/<project_id>/dashboard/runs/<run_id>/stream", methods=["GET"])
def stream(project_id: str, run_id: str):
    """SSE: the run's events, replayed and then followed while it goes."""
    try:
        events = viewer.follow(project_id, run_id, _token())
    except RunError as exc:
        return _error(exc)

    def _sse():
        for kind, payload in events:
            yield f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _kept(project_id: str):
    """The kept output a read names, or the error to answer."""
    try:
        return kept.readable_output(project_id, request.args.get("fileName") or "", _token()), None
    except RunError as exc:
        return None, _error(exc)


@dashboard_runs_bp.route("/api/projects/<project_id>/dashboard/outputs/get", methods=["GET"])
def get_output(project_id: str):
    """``/get`` for an artifact a viewer's run made on this dashboard."""
    from utk_curio.backend.app.api.routes import relay_artifact

    entry, error = _kept(project_id)
    return error or relay_artifact(request.args["fileName"], entry.session_id)


@dashboard_runs_bp.route("/api/projects/<project_id>/dashboard/outputs/get-preview", methods=["GET"])
def get_output_preview(project_id: str):
    """``/get-preview`` for an artifact a viewer's run made on this dashboard."""
    from utk_curio.backend.app.api.routes import relay_preview

    entry, error = _kept(project_id)
    return error or relay_preview(request.args["fileName"], entry.session_id)


@dashboard_runs_bp.route("/api/projects/<project_id>/dashboard/outputs/raster", methods=["GET"])
def get_output_raster(project_id: str):
    """``/raster`` for a raster a viewer's run made on this dashboard."""
    from utk_curio.backend.app.api.routes import relay_raster

    entry, error = _kept(project_id)
    return error or relay_raster(request.args["fileName"], entry.session_id)
