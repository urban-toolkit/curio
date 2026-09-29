"""The account's LLM configurations on the wire: the list with the default and the per-agent assignments, create / update / delete / duplicate, the default, the assignments.

Presentation layer of the agents package (memo dev/142, B4-1; re-derived on enh/agent-catalog): the handlers
of ``routes.py`` by resource, bodies verbatim, registered on the one ``agents_bp`` from ``routes/common.py``.
"""

from __future__ import annotations

from flask import g
from flask import jsonify
from flask import request

from utk_curio.backend.app.agents import service as agents_services
from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.app.agents.infrastructure import provider_config as agents_provider_config
from utk_curio.backend.app.agents.application import llm_listing as agents_llm_listing
from utk_curio.backend.app.agents.infrastructure import llm_configs as agents_llm_configs
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.dependencies import require_auth


# ── LLM configurations (account scope) ──────────────────────────────────────
def _llm_error(exc):
    return _error(str(exc), getattr(exc, "status", 400))


def _llm_refusal():
    from utk_curio.backend.app.users.capabilities import llm_config_refusal

    return llm_config_refusal(g.user)


def _deployment_offered() -> bool:

    return agents_provider_config.deployment_endpoint(
        _user_dir_key(g.user), guest=bool(getattr(g.user, "is_guest", False))
    ) is not None


def _training_locked_ids() -> frozenset:
    from utk_curio.backend.app.agents.training import service as training_service

    return frozenset(training_service.running_config_ids(_user_dir_key(g.user)))


@agents_bp.route("/llm", methods=["GET"])
@require_auth
def get_llm():
    """The account's LLM configurations (never a key), its default, what the
    deployment offers, what answers a run now, and whether this account may
    change any of it."""

    try:
        return jsonify(agents_llm_listing.llm_listing(g.user)), 200
    except agents_llm_configs.LlmConfigError as exc:
        return _llm_error(exc)


@agents_bp.route("/llm/configs", methods=["POST"])
@require_auth
def create_llm_config():
    """Add a configuration: ``{label, endpoint?, apiType, baseUrl?, apiKey?, model}``."""

    refusal = _llm_refusal()
    if refusal:
        return _error(refusal, 403)
    try:
        config = agents_llm_configs.default_store().create(
            _user_dir_key(g.user), request.get_json(silent=True),
            deployment_offered=_deployment_offered(),
        )
    except agents_llm_configs.LlmConfigError as exc:
        return _llm_error(exc)
    return jsonify({"config": config}), 201


@agents_bp.route("/llm/configs/<config_id>", methods=["PATCH"])
@require_auth
def update_llm_config(config_id: str):
    """Change a configuration. A blank ``apiKey`` keeps the stored key and
    ``clearApiKey: true`` removes it."""

    refusal = _llm_refusal()
    if refusal:
        return _error(refusal, 403)
    try:
        config = agents_llm_configs.default_store().update(
            _user_dir_key(g.user), config_id, request.get_json(silent=True),
            deployment_offered=_deployment_offered(), locked_ids=_training_locked_ids(),
        )
    except agents_llm_configs.LlmConfigError as exc:
        return _llm_error(exc)
    return jsonify({"config": config}), 200


@agents_bp.route("/llm/configs/<config_id>", methods=["DELETE"])
@require_auth
def delete_llm_config(config_id: str):
    """Remove a configuration. The agents chosen to run on it go back to their
    rules (``moved`` lists them) and a removed default resets, in one write."""

    refusal = _llm_refusal()
    if refusal:
        return _error(refusal, 403)
    try:
        result = agents_llm_configs.default_store().delete(
            _user_dir_key(g.user), config_id, locked_ids=_training_locked_ids()
        )
    except agents_llm_configs.LlmConfigError as exc:
        return _llm_error(exc)
    return jsonify(result), 200


@agents_bp.route("/llm/configs/<config_id>/duplicate", methods=["POST"])
@require_auth
def duplicate_llm_config(config_id: str):
    """Copy a configuration, key included, server-side: ``{label?, model?}``."""

    refusal = _llm_refusal()
    if refusal:
        return _error(refusal, 403)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict) or set(body) - {"label", "model"}:
        return _error("send {label?, model?}")
    try:
        config = agents_llm_configs.default_store().duplicate(
            _user_dir_key(g.user), config_id, label=body.get("label"), model=body.get("model"),
        )
    except agents_llm_configs.LlmConfigError as exc:
        return _llm_error(exc)
    return jsonify({"config": config}), 201


@agents_bp.route("/llm/default", methods=["PUT"])
@require_auth
def put_llm_default():
    """Choose the default configuration: ``{configId}``, or null for the
    deployment's own."""

    refusal = _llm_refusal()
    if refusal:
        return _error(refusal, 403)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or "configId" not in body:
        return _error("send {configId}, a configuration id or null")
    try:
        agents_llm_configs.default_store().set_default(_user_dir_key(g.user), body["configId"])
        return jsonify(agents_llm_listing.llm_listing(g.user)), 200
    except agents_llm_configs.LlmConfigError as exc:
        return _llm_error(exc)


@agents_bp.route("/llm/assignments", methods=["PUT"])
@require_auth
def put_llm_assignments():
    """Choose the configuration an agent runs on: a partial map of agent id to
    a configuration id, ``"deployment"`` or ``null`` (which clears the choice).
    Agent ids are the catalog cards, published definitions and the account's
    imports; an internal agent always runs on its caller's and is refused."""

    refusal = _llm_refusal()
    if refusal:
        return _error(refusal, 403)
    user_key = _user_dir_key(g.user)
    guest = bool(getattr(g.user, "is_guest", False))
    try:
        agents_llm_configs.default_store().set_choices(
            user_key, request.get_json(silent=True),
            choosable=frozenset(row["id"] for row in agents_services.choosable_agents(user_key)),
            deployment_default=agents_provider_config.deployment_config(user_key, guest=guest) is not None,
        )
        return jsonify(agents_llm_listing.llm_listing(g.user)), 200
    except agents_llm_configs.LlmConfigError as exc:
        return _llm_error(exc)
