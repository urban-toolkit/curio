"""HTTP endpoints for the Agents Catalog — ``/api/agents``.

Thin blueprint over ``app/agents/services.py``, mirroring ``app/packages/routes.py``:
``@require_auth`` + ``_user_dir_key`` for the storage key, and
``projects_repo.get_for_user`` for project ownership. Import and Install are
separate explicit endpoints; nothing auto-chains.
"""

from __future__ import annotations

import functools
import json

from flask import Blueprint, Response, g, jsonify, request, stream_with_context

from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects.repositories import NotFoundError
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.capabilities import settings_refusal
from utk_curio.backend.app.users.dependencies import require_auth

from utk_curio.backend.app.agents import catalog_settings
from utk_curio.backend.app.agents import services as agents_services
from utk_curio.backend.app.agents.provider_config import ProviderConfigError
from utk_curio.backend.app.agents.services import AgentServiceError

agents_bp = Blueprint("agents_api", __name__, url_prefix="/api/agents")


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _provider_error(exc: ProviderConfigError):
    """No LLM configuration answers: a 400 whose remedy opens AI Settings."""
    return jsonify({"error": str(exc), "remedy": exc.remedy}), 400


def _llm_for_attachment(project_id: str, attachment_id: str):
    """The LLM configuration a run of this attachment's agent answers with."""
    from utk_curio.backend.app.agents.provider_config import resolve_llm

    user_key = _user_dir_key(g.user)
    return resolve_llm(
        user_key, agents_services.attachment_agent_id(user_key, project_id, attachment_id),
        guest=bool(getattr(g.user, "is_guest", False)),
    )


def _svc_error(exc: AgentServiceError):
    """One place decides what an AgentServiceError looks like on the wire.

    Kept as the explicit form the handlers already call so the mapping has a
    single definition without rewriting 32 call sites; :func:`_map_agent_errors`
    below reuses it for anything that escapes a handler.
    """
    return _error(str(exc), getattr(exc, "status", 400))


def _map_agent_errors(fn):
    """Catch the service-layer exceptions a handler does not catch itself.

    The Data Catalog's ``datasets/routes.py::_map_catalog_errors`` is the model:
    applied BELOW ``require_auth`` so auth failures are not swallowed, mapping
    a missing dataflow to 404 and an unconfigured provider to a 400 that names
    AI Settings.

    Deliberately additive rather than a replacement for the per-handler
    ``try/except AgentServiceError``. Those 32 blocks work and are covered;
    collapsing them into this decorator is a mechanical dedent across handlers
    with differing shapes (several carry a second ``except``), which is churn
    this phase does not need. The decorator still gives one place to add a new
    mapping, and it widens the guard to a handler's prelude and tail, which the
    inner ``try`` never covered.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AgentServiceError as exc:
            return _svc_error(exc)
        except ProviderConfigError as exc:
            # Curio ships no built-in provider; say where to configure one
            # rather than surfacing a bare 500 from deep in a provider SDK.
            return _provider_error(exc)
        except NotFoundError:
            return _error("Dataflow not found", 404)

    return wrapper


# ── Global Catalog (built-in definitions) ────────────────────────────────────
@agents_bp.route("/catalog", methods=["GET"])
@require_auth
@_map_agent_errors
def list_catalog():
    """The Global Catalog scope - agent definitions available to import/install.

    Optional ``?projectId=`` marks which are already installed in that project.

    The response carries ``facets`` alongside the rows, matching the shape the
    Data Catalog returns (``{"items", "facets"}``): the browse page's category
    rail reads its counts straight off it, and the drawer's tab badges seed
    from it before the rows land. ``agents`` is kept as an alias of ``items``
    so the existing drawer keeps working while the browse page is built.
    """
    project_id = request.args.get("projectId") or None
    agents = agents_services.list_global_catalog(_user_dir_key(g.user), project_id)
    facets = agents_services.agent_catalog_facets(agents)
    return jsonify({"items": agents, "agents": agents, "facets": facets}), 200


# ── Catalog settings (account scope) ────────────────────────────────────────
def _settings_payload():
    refusal = settings_refusal(g.user)
    return {
        "settings": agents_services.catalog_settings_listing(_user_dir_key(g.user)),
        "editable": refusal is None,
        "reason": refusal,
    }


@agents_bp.route("/settings", methods=["GET"])
@require_auth
@_map_agent_errors
def get_catalog_settings():
    """Every catalog setting with the account's value and the agents that read
    it, and whether this account may change them."""
    return jsonify(_settings_payload()), 200


@agents_bp.route("/settings", methods=["PUT"])
@require_auth
@_map_agent_errors
def put_catalog_settings():
    """Change settings: a JSON object of key to value, where ``null`` restores
    the default. Nothing is saved unless every value is valid."""
    refusal = settings_refusal(g.user)
    if refusal:
        return _error(refusal, 403)
    try:
        catalog_settings.update(_user_dir_key(g.user), request.get_json(silent=True))
    except catalog_settings.SettingError as exc:
        return _error(str(exc), 400)
    return jsonify(_settings_payload()), 200


# ── LLM configurations (account scope) ──────────────────────────────────────
def _llm_error(exc):
    return _error(str(exc), getattr(exc, "status", 400))


def _llm_refusal():
    from utk_curio.backend.app.users.capabilities import llm_config_refusal

    return llm_config_refusal(g.user)


def _deployment_offered() -> bool:
    from utk_curio.backend.app.agents.provider_config import deployment_endpoint

    return deployment_endpoint(
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
    from utk_curio.backend.app.agents.llm_configs import LlmConfigError
    from utk_curio.backend.app.agents.provider_config import llm_listing

    try:
        return jsonify(llm_listing(g.user)), 200
    except LlmConfigError as exc:
        return _llm_error(exc)


@agents_bp.route("/llm/configs", methods=["POST"])
@require_auth
def create_llm_config():
    """Add a configuration: ``{label, endpoint?, apiType, baseUrl?, apiKey?, model}``."""
    from utk_curio.backend.app.agents.llm_configs import LlmConfigError, default_store

    refusal = _llm_refusal()
    if refusal:
        return _error(refusal, 403)
    try:
        config = default_store().create(
            _user_dir_key(g.user), request.get_json(silent=True),
            deployment_offered=_deployment_offered(),
        )
    except LlmConfigError as exc:
        return _llm_error(exc)
    return jsonify({"config": config}), 201


@agents_bp.route("/llm/configs/<config_id>", methods=["PATCH"])
@require_auth
def update_llm_config(config_id: str):
    """Change a configuration. A blank ``apiKey`` keeps the stored key and
    ``clearApiKey: true`` removes it."""
    from utk_curio.backend.app.agents.llm_configs import LlmConfigError, default_store

    refusal = _llm_refusal()
    if refusal:
        return _error(refusal, 403)
    try:
        config = default_store().update(
            _user_dir_key(g.user), config_id, request.get_json(silent=True),
            deployment_offered=_deployment_offered(), locked_ids=_training_locked_ids(),
        )
    except LlmConfigError as exc:
        return _llm_error(exc)
    return jsonify({"config": config}), 200


@agents_bp.route("/llm/configs/<config_id>", methods=["DELETE"])
@require_auth
def delete_llm_config(config_id: str):
    """Remove a configuration; the default resets when it was the default."""
    from utk_curio.backend.app.agents.llm_configs import LlmConfigError, default_store

    refusal = _llm_refusal()
    if refusal:
        return _error(refusal, 403)
    try:
        result = default_store().delete(
            _user_dir_key(g.user), config_id, locked_ids=_training_locked_ids()
        )
    except LlmConfigError as exc:
        return _llm_error(exc)
    return jsonify(result), 200


@agents_bp.route("/llm/configs/<config_id>/duplicate", methods=["POST"])
@require_auth
def duplicate_llm_config(config_id: str):
    """Copy a configuration, key included, server-side: ``{label?, model?}``."""
    from utk_curio.backend.app.agents.llm_configs import LlmConfigError, default_store

    refusal = _llm_refusal()
    if refusal:
        return _error(refusal, 403)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict) or set(body) - {"label", "model"}:
        return _error("send {label?, model?}")
    try:
        config = default_store().duplicate(
            _user_dir_key(g.user), config_id, label=body.get("label"), model=body.get("model"),
        )
    except LlmConfigError as exc:
        return _llm_error(exc)
    return jsonify({"config": config}), 201


@agents_bp.route("/llm/default", methods=["PUT"])
@require_auth
def put_llm_default():
    """Choose the default configuration: ``{configId}``, or null for the
    deployment's own."""
    from utk_curio.backend.app.agents.llm_configs import LlmConfigError, default_store
    from utk_curio.backend.app.agents.provider_config import llm_listing

    refusal = _llm_refusal()
    if refusal:
        return _error(refusal, 403)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or "configId" not in body:
        return _error("send {configId}, a configuration id or null")
    try:
        default_store().set_default(_user_dir_key(g.user), body["configId"])
        return jsonify(llm_listing(g.user)), 200
    except LlmConfigError as exc:
        return _llm_error(exc)


@agents_bp.route("/provider-models", methods=["POST"])
@require_auth
@_map_agent_errors
def list_provider_models():
    """The models AI Settings can offer for the endpoint being configured.

    POST rather than GET because AI Settings needs this *before* the user saves:
    they type a base URL and a key, then want to pick a model from what that
    endpoint actually has. A GET reading the stored config could only ever list
    models for the previous configuration.

    The body names the endpoint as it is on screen: ``apiType``, ``baseUrl``
    and ``apiKey``. A stored key is used instead of a typed one in two cases
    only: ``configId`` borrows that configuration's key while the endpoint
    asked about is still that configuration's own, and ``endpoint:
    "deployment"`` asks this Curio install's endpoint with its own key. With
    neither, no key is borrowed.

    **Hybrid, per #241 - and both halves come from the API.** Two sources:

    - *Live*: what the endpoint reports now. Asked of Anthropic and Gemini too,
      not only OpenAI-compatible endpoints. The old code never asked them and
      reported ``listable: false``, which read as "this provider publishes no
      model list" - a claim that was not true.
    - *Remembered*: what this endpoint reported the last time it was asked
      (``agents/model_catalog.py``), recorded per user on every success. Serves
      as the fallback when a live listing cannot happen, labelled with when it
      was seen.

    Nothing here is authored by hand. The first cut of this route carried a
    literal table of model ids, which drifts silently the moment a provider
    ships or retires one, and could never say anything about a custom endpoint.
    A recording of what an endpoint said about itself has neither problem.

    Suggestions are never an allowlist: the Model field stays free text, a live
    listing always wins, and a model typed by hand is always accepted. So a live
    failure is a 200 with ``source: "remembered"`` and the reason in ``warning``
    when something was remembered, because "here is what it said last time, and
    why we could not ask now" beats an error and an empty box. With nothing
    remembered - a new account that has not pasted a key - the reason *is* the
    answer and this is a 400.
    """
    from utk_curio.backend.app.agents.llm_configs import ENDPOINT_DEPLOYMENT, default_store
    from utk_curio.backend.app.agents.model_catalog import (
        provider_key,
        remember_models,
        remembered_models,
    )
    from utk_curio.backend.app.agents.provider_config import (
        deployment_endpoint,
        is_hosted_guest,
    )
    from utk_curio.backend.app.agents.providers import (
        ModelListingUnavailable,
        ProviderConfig,
        list_provider_models as fetch_models,
    )

    data = request.get_json(silent=True) or {}
    api_type = (data.get("apiType") or "").strip()
    base_url = (data.get("baseUrl") or "").strip()
    api_key = (data.get("apiKey") or "").strip()

    user_key = _user_dir_key(g.user)
    guest = bool(getattr(g.user, "is_guest", False))
    if data.get("endpoint") == "deployment":
        endpoint = deployment_endpoint(user_key, guest=guest)
        if endpoint is None:
            return _error("this Curio install offers no endpoint of its own")
        api_type, base_url, api_key = endpoint
    elif data.get("configId"):
        # A key belongs to the endpoint it was saved against, and
        # ``provider_key`` is where Curio says what "the same endpoint" means.
        # Once the caller names a different one - another provider, or a URL
        # typed in the editor - borrowing the key would post it to a host its
        # owner never chose.
        config_id = str(data["configId"])
        record = (
            None if is_hosted_guest(user_key, guest=guest)
            else default_store().record(user_key, config_id)
        )
        if record is None:
            return _error(f"no LLM configuration {config_id!r}", 404)
        if record.get("endpoint") == ENDPOINT_DEPLOYMENT:
            endpoint = deployment_endpoint(user_key, guest=guest)
            if endpoint is None:
                return _error("this Curio install offers no endpoint of its own")
            saved_type, saved_url, saved_key = endpoint
        else:
            saved_type = record.get("apiType") or ""
            saved_url = record.get("baseUrl") or ""
            saved_key = record.get("apiKey") or ""
        api_type = api_type or saved_type
        if provider_key(api_type) == provider_key(saved_type):
            base_url = base_url or saved_url
        if not api_key and provider_key(api_type, base_url) == provider_key(saved_type, saved_url):
            api_key = saved_key

    api_type = api_type or "openai_compatible"

    try:
        live = fetch_models(
            ProviderConfig(
                api_key=api_key, api_type=api_type, base_url=base_url, model="",
            )
        )
    except ModelListingUnavailable as exc:
        remembered, seen_at = remembered_models(user_key, api_type, base_url)
        if not remembered:
            # Nothing was ever recorded for this endpoint, so the reason IS the
            # answer. 400 rather than 500: the user is mid-edit and the message
            # tells them which field to fill in.
            return _error(str(exc), 400)
        return jsonify({
            "models": remembered,
            "listable": False,
            "source": "remembered",
            "remembered": remembered,
            "rememberedAt": seen_at,
            "warning": str(exc),
        }), 200

    # A live answer supersedes the recording, and becomes the next one. Writing
    # is best-effort inside remember_models: a store that cannot be written must
    # not turn a working listing into an error.
    remember_models(user_key, api_type, base_url, live)
    return jsonify({
        "models": live,
        # Kept for callers written against the older shape. It means what it
        # says: the endpoint itself answered.
        "listable": True,
        "source": "live",
        "remembered": [],
        "rememberedAt": None,
        "warning": None,
    }), 200


@agents_bp.route("/imports", methods=["GET"])
@require_auth
def list_imports():
    """Optional ``?projectId=`` marks which imports are installed in that
    project (memo dev/47 — the lockfile is the one source of truth)."""
    project_id = request.args.get("projectId") or None
    return (
        jsonify({"agents": agents_services.list_my_imports(_user_dir_key(g.user), project_id)}),
        200,
    )


@agents_bp.route("/imports", methods=["POST"])
@require_auth
def import_agent():
    body = request.get_json(silent=True) or {}
    coord = body.get("coord")
    if not isinstance(coord, str):
        return _error("body must include 'coord'")
    try:
        payload = agents_services.import_agent(_user_dir_key(g.user), coord, user=g.user)
    except AgentServiceError as exc:
        return _svc_error(exc)
    except ValueError as exc:
        return _error(str(exc))
    return jsonify(payload), 201


@agents_bp.route("/imports/upload", methods=["POST"])
@require_auth
def upload_import():
    """Upload a user-authored definition (memo dev/36): a JSON body with the
    manifest and its prompt texts. Creates an owned, publishable My Imports
    entry; nothing auto-installs or auto-publishes."""
    body = request.get_json(silent=True) or {}
    try:
        payload = agents_services.upload_import(
            _user_dir_key(g.user), body.get("manifest"), body.get("prompts") or {}
        )
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 201


@agents_bp.route("/imports/<coord>", methods=["DELETE"])
@require_auth
def remove_import(coord: str):
    return jsonify(agents_services.remove_import(_user_dir_key(g.user), coord, user=g.user)), 200


# ── Publish to the Global Catalog (imported-only) ────────────────────────────
@agents_bp.route("/definitions/<coord>", methods=["GET"])
@require_auth
def read_definition(coord: str):
    """One agent's full definition: its manifest and its prompt texts.

    Powers two things the Agent Catalog could not do: show an agent's prompts on
    its details screen, and export it. Agents had an import with no export - a
    definition could go into a Curio and never come back out - and this returns
    exactly the shape ``POST /api/agents/imports/upload`` consumes, so the two
    round-trip.
    """
    bundle = agents_services.read_definition_bundle_anywhere(_user_dir_key(g.user), coord)
    if bundle is None:
        return jsonify({"error": f"no agent definition {coord}"}), 404
    return jsonify(bundle), 200


@agents_bp.route("/publications", methods=["POST"])
@require_auth
def publish_agent():
    body = request.get_json(silent=True) or {}
    coord = body.get("coord")
    if not isinstance(coord, str):
        return _error("body must include 'coord'")
    try:
        payload = agents_services.publish_agent(_user_dir_key(g.user), coord)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 201


@agents_bp.route("/publications/<coord>", methods=["DELETE"])
@require_auth
def unpublish_agent(coord: str):
    try:
        payload = agents_services.unpublish_agent(_user_dir_key(g.user), coord)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200
# ── Installed in this project ────────────────────────────────────────────────
@agents_bp.route("/projects/<project_id>", methods=["GET"])
@require_auth
def list_project_agents(project_id: str):
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        agents = agents_services.list_installed_in_project(_user_dir_key(g.user), project_id)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify({"agents": agents}), 200


@agents_bp.route("/projects/<project_id>/install", methods=["POST"])
@require_auth
def install_in_project(project_id: str):
    body = request.get_json(silent=True) or {}
    coord = body.get("coord")
    if not isinstance(coord, str):
        return _error("body must include 'coord'")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.install_in_project(_user_dir_key(g.user), project_id, coord)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 201


@agents_bp.route("/projects/<project_id>/<coord>", methods=["DELETE"])
@require_auth
def uninstall_from_project(project_id: str, coord: str):
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.uninstall_from_project(_user_dir_key(g.user), project_id, coord)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


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
        # builder right here, so the config is resolved with the selection. A
        # user with no provider still records the selection (the delegation
        # says why it did not start).
        try:
            config = _llm_for_attachment(project_id, attachment_id)
        except ProviderConfigError:
            config = None
        payload = agents_services.record_dataset_selection(
            _user_dir_key(g.user), project_id, attachment_id, body.get("picks"),
            config=config,
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
    "/projects/<project_id>/attachments/<attachment_id>/proposals/<proposal_id>/apply",
    methods=["POST"],
)
@require_auth
def apply_proposal(project_id: str, attachment_id: str, proposal_id: str):
    """Apply a pending review proposal (memo dev/41) — the only mutation path.

    Explicit, owner-authenticated, revision-safe: a drifted target returns a
    409 and marks the proposal stale. Consumes no quota."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.apply_proposal(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/proposals/<proposal_id>/apply-node",
    methods=["POST"],
)
@require_auth
def apply_plan_node(project_id: str, attachment_id: str, proposal_id: str):
    """Apply ONE planned node from a pending dataflow-plan proposal
    (dev/67-5, Simulation Mode: create). Body: ``{"ref": "<plan ref>"}``.
    The proposal stays pending until every ref is applied or it is dismissed;
    edges are the connection stage's concern (67-8)."""
    body = request.get_json(silent=True) or {}
    ref = body.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        return _error("body must include a non-empty 'ref'")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.apply_plan_node(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id, ref.strip()
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/proposals/<proposal_id>/apply-edges",
    methods=["POST"],
)
@require_auth
def apply_plan_edges(project_id: str, attachment_id: str, proposal_id: str):
    """Apply plan edges — the connection review stage (dev/67-8). Body:
    optional ``{"edges": [index, …]}`` for a subset (default: every
    not-yet-applied edge). Refusals are per-edge and named; partial success
    is reported honestly, never all-or-nothing."""
    body = request.get_json(silent=True) or {}
    indices = body.get("edges")
    if indices is not None and not (
        isinstance(indices, list) and all(isinstance(i, int) for i in indices)
    ):
        return _error("'edges' must be a list of integer indices when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.apply_plan_edges(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id, indices
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/proposals/<proposal_id>/plan-goals",
    methods=["PATCH"],
)
@require_auth
def set_plan_goal(project_id: str, attachment_id: str, proposal_id: str):
    """Edit one planned node's goal before creation (dev/67-5): an audited
    review-stage overlay — the pinned plan bytes stay immutable. Body:
    ``{"ref": "<plan ref>", "goal": "<edited goal>"}``. Pending only."""
    body = request.get_json(silent=True) or {}
    ref = body.get("ref")
    goal = body.get("goal")
    if not isinstance(ref, str) or not ref.strip():
        return _error("body must include a non-empty 'ref'")
    if not isinstance(goal, str):
        return _error("body must include a 'goal' string")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.set_plan_goal(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id,
            ref.strip(), goal,
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


@agents_bp.route(
    "/projects/<project_id>/attachments/<attachment_id>/proposals/<proposal_id>",
    methods=["DELETE"],
)
@require_auth
def dismiss_proposal(project_id: str, attachment_id: str, proposal_id: str):
    """Dismiss a pending review proposal without applying it."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        payload = agents_services.dismiss_proposal(
            _user_dir_key(g.user), project_id, attachment_id, proposal_id
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except AgentServiceError as exc:
        return _svc_error(exc)
    return jsonify(payload), 200


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
    "/projects/<project_id>/attachments/<attachment_id>/jobs/stream", methods=["GET"]
)
@require_auth
def attach_job_stream(project_id: str, attachment_id: str):
    """dev/115 (DEC-021 single-process slice): re-attach to the attachment's
    background job — the running Solve batch or per-node Solve, or the most
    recent finished one still within the replay window. Replays every event
    so far, then tails live ones; 404 when there is nothing to attach to."""
    from utk_curio.backend.app.agents import agent_jobs

    try:
        projects_repo.get_for_user(project_id, g.user.id)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    job = agent_jobs.latest_job(_user_dir_key(g.user), attachment_id)
    if job is None or job.project_id != project_id:
        return _error("no background job for this attachment", 404)
    events = agent_jobs.subscribe(job)

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


# ---------------------------------------------------------------------------
# Model training (memo dev/122, ``DEC-078``)
# ---------------------------------------------------------------------------
#
# Eight routes, and one shape borrowed from ``provider-models`` on purpose: a
# capability is ASKED of the endpoint and recorded, and a replay is labelled
# with the date it was true. There is no provider→capability table here or
# anywhere else.
#
# There is no streaming route and no job worker. A fine-tune belongs to the
# provider; these routes read what it says.


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


# ---------------------------------------------------------------------------
# Evaluation mode (memo dev/123, ``DEC-079``)
# ---------------------------------------------------------------------------
#
# An evaluation is a product action: the panel calls these, the service does
# the work through the product's own entry points, and the reference dataflow
# never leaves the server. There is no route that returns an expected graph.


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
    from utk_curio.backend.app.agents import agent_jobs

    user_key = _user_dir_key(g.user)
    job = agent_jobs.latest_job(user_key, run_id)
    if job is None:
        return _error("no evaluation job to attach to", 404)

    def _sse():
        yield f"event: job\ndata: {json.dumps(job.to_payload())}\n\n"
        for kind, payload in agent_jobs.subscribe(job):
            yield f"event: {kind}\ndata: {json.dumps(payload)}\n\n"

    return Response(
        stream_with_context(_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
