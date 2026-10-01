"""Evaluation mode (memo dev/123, ``DEC-079``).

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

from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import _map_agent_errors
from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.app.agents.infrastructure import agent_jobs as agents_agent_jobs
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.dependencies import require_auth


def _evaluation_error(exc) -> tuple:
    return _error(exc.message, getattr(exc, "status", 400))


@agents_bp.route("/evaluation/readiness", methods=["GET"])
@require_auth
@_map_agent_errors
def evaluation_readiness():
    """Whether an evaluation can run, and which model would answer.

    Reports the SOURCE as well as the answer, because a model configured by the
    deployment's own start flags is as real as one typed into AI Settings — a
    panel that only read the user row would tell an operator who passed
    ``--llm-model`` that they had configured nothing.
    """
    from utk_curio.backend.app.agents.evaluation import service as evaluation_service

    return jsonify(evaluation_service.readiness(g.user)), 200


@agents_bp.route("/evaluation/fixtures", methods=["GET"])
@require_auth
@_map_agent_errors
def evaluation_fixtures():
    """The prompts a person can choose from, with their review state."""
    from utk_curio.backend.app.agents.evaluation import service as evaluation_service

    return jsonify(evaluation_service.list_fixtures()), 200


@agents_bp.route("/evaluation/fixtures/<fixture_id>/review", methods=["POST"])
@require_auth
@_map_agent_errors
def evaluation_review_fixture(fixture_id: str):
    """Record a prompt review from the panel.

    A prompt is drafted by a model and approved by a person; before this route
    the only way to record that was to hand-edit JSON, which produced a
    mistyped status the schema rejected. A review that can be mistyped belongs
    in the interface.
    """
    from utk_curio.backend.app.agents.evaluation import service as evaluation_service

    body = request.get_json(silent=True) or {}
    try:
        return jsonify(evaluation_service.set_review(
            fixture_id, status=str(body.get("status") or ""), user=g.user
        )), 200
    except evaluation_service.EvaluationServiceError as exc:
        return _evaluation_error(exc)


@agents_bp.route("/evaluation/runs", methods=["POST"])
@require_auth
@_map_agent_errors
def evaluation_start_run():
    """Start a run: an isolated project, the normal install/attach, the
    account's own model, the normal lifecycle."""
    from utk_curio.backend.app.agents.evaluation import service as evaluation_service

    body = request.get_json(silent=True) or {}
    try:
        return jsonify(evaluation_service.start(
            g.user, _user_dir_key(g.user), str(body.get("fixtureId") or "")
        )), 201
    except evaluation_service.EvaluationServiceError as exc:
        return _evaluation_error(exc)


@agents_bp.route("/evaluation/runs", methods=["GET"])
@require_auth
@_map_agent_errors
def evaluation_list_runs():
    from utk_curio.backend.app.agents.evaluation import service as evaluation_service

    return jsonify(evaluation_service.listing(_user_dir_key(g.user))), 200


@agents_bp.route("/evaluation/runs/<run_id>", methods=["GET"])
@require_auth
@_map_agent_errors
def evaluation_run_status(run_id: str):
    from utk_curio.backend.app.agents.evaluation import service as evaluation_service

    try:
        return jsonify(evaluation_service.status(_user_dir_key(g.user), run_id)), 200
    except evaluation_service.EvaluationServiceError as exc:
        return _evaluation_error(exc)


@agents_bp.route("/evaluation/runs/<run_id>/cancel", methods=["POST"])
@require_auth
@_map_agent_errors
def evaluation_cancel_run(run_id: str):
    from utk_curio.backend.app.agents.evaluation import service as evaluation_service

    try:
        return jsonify(evaluation_service.cancel(_user_dir_key(g.user), run_id)), 200
    except evaluation_service.EvaluationServiceError as exc:
        return _evaluation_error(exc)


@agents_bp.route("/evaluation/runs/<run_id>/stream", methods=["GET"])
@require_auth
@_map_agent_errors
def evaluation_run_stream(run_id: str):
    """Re-attach to a running evaluation's phases.

    The ``jobs/stream`` shape (dev/115): the job's log replays first, then live
    events tail until it finishes, so a reload rejoins a run in progress rather
    than losing it. A finished run replays and ends.
    """

    user_key = _user_dir_key(g.user)
    job = agents_agent_jobs.latest_job(user_key, run_id)
    if job is None:
        return _error("no evaluation job to attach to", 404)

    def _sse():
        yield f"event: job\ndata: {json.dumps(job.to_payload())}\n\n"
        for kind, payload in agents_agent_jobs.subscribe(job):
            yield f"event: {kind}\ndata: {json.dumps(payload)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
