"""The global catalog, the provider, My Imports, definitions and publications.

Presentation layer of the agents package (memo dev/142, B4-1; re-derived on enh/agent-catalog): the handlers
of ``routes.py`` by resource, bodies verbatim, registered on the one ``agents_bp`` from ``routes/common.py``.
"""

from __future__ import annotations

from flask import g
from flask import jsonify
from flask import request

from utk_curio.backend.app.agents import service as agents_services
from utk_curio.backend.app.agents.repositories import catalog_settings
from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import _map_agent_errors
from utk_curio.backend.app.agents.routes.common import _svc_error
from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.app.agents.service import AgentServiceError
from utk_curio.backend.app.agents.infrastructure import provider_config as agents_provider_config
from utk_curio.backend.app.agents.infrastructure import providers as agents_providers
from utk_curio.backend.app.agents.infrastructure import llm_configs as agents_llm_configs
from utk_curio.backend.app.agents.repositories import model_catalog as agents_model_catalog
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.capabilities import settings_refusal
from utk_curio.backend.app.users.dependencies import require_auth


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


@agents_bp.route("/provider-models", methods=["POST"])
@require_auth
@_map_agent_errors
def list_provider_models():
    """The models API Settings can offer for the endpoint being configured.

    POST rather than GET because API Settings needs this *before* the user saves:
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

    data = request.get_json(silent=True) or {}
    api_type = (data.get("apiType") or "").strip()
    base_url = (data.get("baseUrl") or "").strip()
    api_key = (data.get("apiKey") or "").strip()

    user_key = _user_dir_key(g.user)
    guest = bool(getattr(g.user, "is_guest", False))
    if data.get("endpoint") == "deployment":
        endpoint = agents_provider_config.deployment_endpoint(user_key, guest=guest)
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
            None if agents_provider_config.is_hosted_guest(user_key, guest=guest)
            else agents_llm_configs.default_store().record(user_key, config_id)
        )
        if record is None:
            return _error(f"no LLM configuration {config_id!r}", 404)
        if record.get("endpoint") == agents_llm_configs.ENDPOINT_DEPLOYMENT:
            endpoint = agents_provider_config.deployment_endpoint(user_key, guest=guest)
            if endpoint is None:
                return _error("this Curio install offers no endpoint of its own")
            saved_type, saved_url, saved_key = endpoint
        else:
            saved_type = record.get("apiType") or ""
            saved_url = record.get("baseUrl") or ""
            saved_key = record.get("apiKey") or ""
        api_type = api_type or saved_type
        if agents_model_catalog.provider_key(api_type) == agents_model_catalog.provider_key(saved_type):
            base_url = base_url or saved_url
        if not api_key and agents_model_catalog.provider_key(api_type, base_url) == agents_model_catalog.provider_key(saved_type, saved_url):
            api_key = saved_key

    api_type = api_type or "openai_compatible"

    try:
        live = agents_providers.list_provider_models(
            agents_providers.ProviderConfig(
                api_key=api_key, api_type=api_type, base_url=base_url, model="",
            )
        )
    except agents_providers.ModelListingUnavailable as exc:
        remembered, seen_at = agents_model_catalog.remembered_models(user_key, api_type, base_url)
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
    agents_model_catalog.remember_models(user_key, api_type, base_url, live)
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
