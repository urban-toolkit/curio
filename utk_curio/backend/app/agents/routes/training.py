"""Model training (memo dev/122, ``DEC-078``).

Presentation layer of the agents package (memo dev/142, B4-1; re-derived on enh/agent-catalog): the handlers
of ``routes.py`` by resource, bodies verbatim, registered on the one ``agents_bp`` from ``routes/common.py``.
"""

from __future__ import annotations

from flask import g
from flask import jsonify
from flask import request

from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import _map_agent_errors
from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.dependencies import require_auth


def _training_error(exc) -> tuple:
    return _error(exc.message, getattr(exc, "status", 400))


@agents_bp.route("/training/capability", methods=["GET"])
@require_auth
@_map_agent_errors
def training_capability():
    """Can this configuration's endpoint fine-tune, and if not, why not.

    ``?configId=`` names the LLM configuration (the default when absent); it
    must hold the user's own key. ``?refresh=0`` serves the recording instead of
    asking again, so opening the panel twice in a minute does not re-probe. A
    recording always carries the date it was true.
    """
    from utk_curio.backend.app.agents.training import service as training_service

    user_key = _user_dir_key(g.user)
    refresh = (request.args.get("refresh") or "1").strip() not in ("0", "false", "no")
    try:
        return jsonify(training_service.capability(
            g.user, user_key, config_id=request.args.get("configId") or None, refresh=refresh,
        )), 200
    except training_service.TrainingServiceError as exc:
        return _training_error(exc)


@agents_bp.route("/training/dataset/preview", methods=["POST"])
@require_auth
@_map_agent_errors
def training_dataset_preview():
    """What would be sent: rows, bytes, fixtures, licences, destination host.

    POST because it is an action with a body (the split and ``configId``), and
    because its answer carries the digest and the host a later start must echo.
    """
    from utk_curio.backend.app.agents.training import service as training_service

    body = request.get_json(silent=True) or {}
    split = str(body.get("split") or "train")
    try:
        return jsonify(training_service.preview(
            g.user, _user_dir_key(g.user), config_id=body.get("configId") or None, split=split,
        )), 200
    except training_service.TrainingServiceError as exc:
        return _training_error(exc)


@agents_bp.route("/training/jobs", methods=["POST"])
@require_auth
@_map_agent_errors
def training_start_job():
    """Consent, upload, submit. The consent record is written first."""
    from utk_curio.backend.app.agents.training import service as training_service

    body = request.get_json(silent=True) or {}
    price = body.get("pricePerMTokenTrained")
    try:
        return jsonify(training_service.start(
            g.user,
            _user_dir_key(g.user),
            base_model=str(body.get("baseModel") or ""),
            rows_digest=str(body.get("rowsDigest") or ""),
            confirmed=bool(body.get("confirmed")),
            destination_host=str(body.get("destinationHost") or ""),
            config_id=body.get("configId") or None,
            split=str(body.get("split") or "train"),
            price_per_mtoken=[float(price)] if isinstance(price, (int, float)) else None,
        )), 201
    except training_service.TrainingServiceError as exc:
        return _training_error(exc)


@agents_bp.route("/training/jobs", methods=["GET"])
@require_auth
@_map_agent_errors
def training_list_jobs():
    from utk_curio.backend.app.agents.training import service as training_service

    return jsonify(training_service.listing(_user_dir_key(g.user))), 200


@agents_bp.route("/training/jobs/<job_id>", methods=["GET"])
@require_auth
@_map_agent_errors
def training_job_status(job_id: str):
    """The endpoint's current word on a job, with the time it was read."""
    from utk_curio.backend.app.agents.training import service as training_service

    try:
        return jsonify(
            training_service.status(g.user, _user_dir_key(g.user), job_id)
        ), 200
    except training_service.TrainingServiceError as exc:
        return _training_error(exc)


@agents_bp.route("/training/jobs/<job_id>/cancel", methods=["POST"])
@require_auth
@_map_agent_errors
def training_cancel_job(job_id: str):
    from utk_curio.backend.app.agents.training import service as training_service

    try:
        return jsonify(
            training_service.cancel(g.user, _user_dir_key(g.user), job_id)
        ), 200
    except training_service.TrainingServiceError as exc:
        return _training_error(exc)


@agents_bp.route("/training/jobs/<job_id>/activate", methods=["POST"])
@require_auth
@_map_agent_errors
def training_activate(job_id: str):
    """Give a trained model a configuration and make it the default, refused
    without an evaluation.

    The four refusals live in ``training/gate.py``; this route only carries
    them. Curio does not decide that a trained model is better: it refuses to
    let you activate one you have not evaluated on data it never trained on.
    """
    from utk_curio.backend.app.agents.training import service as training_service

    try:
        return jsonify(
            training_service.activate(g.user, _user_dir_key(g.user), job_id)
        ), 200
    except training_service.TrainingServiceError as exc:
        return _training_error(exc)


@agents_bp.route("/training/jobs/<job_id>/rollback", methods=["POST"])
@require_auth
@_map_agent_errors
def training_rollback(job_id: str):
    """Restore the default configuration this activation replaced."""
    from utk_curio.backend.app.agents.training import service as training_service

    try:
        return jsonify(
            training_service.rollback(g.user, _user_dir_key(g.user), job_id)
        ), 200
    except training_service.TrainingServiceError as exc:
        return _training_error(exc)
