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
from utk_curio.backend.app.users.dependencies import require_auth

from utk_curio.backend.app.agents import services as agents_services
from utk_curio.backend.app.agents.provider_config import ProviderConfigError
from utk_curio.backend.app.agents.services import AgentServiceError

agents_bp = Blueprint("agents_api", __name__, url_prefix="/api/agents")


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


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
            return _error(str(exc), 400)
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


# ── My Imports (account scope) ───────────────────────────────────────────────
@agents_bp.route("/provider-default", methods=["GET"])
@require_auth
@_map_agent_errors
def get_provider_default():
    """What a user inherits when they configure no provider of their own.

    ``curio.py start``'s ``--llm-provider`` / ``--llm-base-url`` /
    ``--llm-model`` set exactly these three, so the flags are one more way of
    writing the same account-wide setting AI Settings edits. The panel reads
    this to show the deployment's choice as the inherited value rather than
    inventing a placeholder model of its own.

    The API key is reported only as a boolean. Its value never leaves the
    server, which is also why there is no ``--llm-api-key``.
    """
    from utk_curio.backend import config

    return jsonify({
        "apiType": config.DEFAULT_LLM_API_TYPE or None,
        "baseUrl": config.DEFAULT_LLM_BASE_URL or None,
        "model": config.DEFAULT_LLM_MODEL or None,
        "hasApiKey": bool(config.DEFAULT_LLM_API_KEY),
    }), 200


@agents_bp.route("/provider-models", methods=["POST"])
@require_auth
@_map_agent_errors
def list_provider_models():
    """The models AI Settings can offer for the endpoint being configured.

    POST rather than GET because AI Settings needs this *before* the user saves:
    they type a base URL and a key, then want to pick a model from what that
    endpoint actually has. A GET reading the stored config could only ever list
    models for the previous configuration.

    The request body is optional; each field falls back to what the account has
    already resolved, so an already-configured user can refresh the list without
    retyping a secret. A blank ``apiKey`` in particular means "use the saved
    one", matching the panel's own "blank means keep" rule.

    **Hybrid, per #241.** Two sources answer this, in that order of authority:

    - *Live*: what the endpoint reports. Now asked of Anthropic and Gemini too,
      not only OpenAI-compatible endpoints. The old code never asked them and
      reported ``listable: false``, which read as "this provider publishes no
      model list" - a claim that was not true.
    - *Curated*: a short per-provider fallback (``agents/model_catalog.py``),
      appended after anything live and returned on its own when the live call
      cannot happen. It is a suggestion list, never an allowlist: the Model
      field stays free text and a saved model is never rejected here.

    A live failure is therefore a 200 with ``source: "curated"`` and the reason
    in ``warning`` whenever a curated list exists, because "here is a shorter
    list and why" beats an error and an empty box. Only a provider with no
    curated list of its own - a custom endpoint, where there is no such thing as
    a model it probably serves - still answers 400.
    """
    from utk_curio.backend.app.agents.model_catalog import curated_for
    from utk_curio.backend.app.agents.provider_config import (
        resolve_provider_config,
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

    # Fall back to the account's resolved provider for whatever the caller left
    # blank. Tolerate the resolve failing: it raises when no model is set, and
    # "no model yet" is the normal state of someone about to choose one here.
    if not (api_type and base_url and api_key):
        try:
            resolved = resolve_provider_config(g.user)
        except Exception:  # noqa: BLE001 - an unconfigured account is expected
            resolved = None
        if resolved is not None:
            api_type = api_type or (resolved.api_type or "")
            base_url = base_url or (resolved.base_url or "")
            api_key = api_key or (resolved.api_key or "")

    api_type = api_type or "openai_compatible"
    curated = curated_for(api_type, base_url)

    try:
        live = fetch_models(
            ProviderConfig(
                api_key=api_key, api_type=api_type, base_url=base_url, model="",
            )
        )
        warning = None
    except ModelListingUnavailable as exc:
        if not curated:
            # Nothing to fall back to, so the reason IS the answer. 400 rather
            # than 500: the user is mid-edit and the message tells them which
            # field is wrong.
            return _error(str(exc), 400)
        live, warning = [], str(exc)

    seen = set(live)
    merged = list(live) + [m for m in curated if m not in seen]
    source = (
        "live+curated" if live and len(merged) > len(live)
        else "live" if live
        else "curated" if merged
        else "none"
    )
    return jsonify({
        "models": merged,
        # Kept for callers written against the old shape. It now means what it
        # says: the endpoint itself answered.
        "listable": bool(live),
        "source": source,
        "curated": curated,
        "warning": warning,
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
    from utk_curio.backend.app.agents import storage as agents_storage

    bundle = agents_storage.read_definition_bundle(_user_dir_key(g.user), coord)
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
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    body = request.get_json(silent=True) or {}
    node_ids = body.get("nodeIds")
    if node_ids is not None and not (
        isinstance(node_ids, list) and all(isinstance(n, str) for n in node_ids)
    ):
        return _error("'nodeIds' must be a list of node id strings when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = resolve_provider_config(g.user)
        payload = agents_services.solve_attachment(
            _user_dir_key(g.user), project_id, attachment_id, config, node_ids
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _error(str(exc), 400)
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
    ``done`` (the blocking payload + ``cancelled``/``notAttempted``).
    Validation errors (409/404/…) return normal JSON statuses before any
    streaming starts; the persisted session stays the single truth."""
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    body = request.get_json(silent=True) or {}
    node_ids = body.get("nodeIds")
    if node_ids is not None and not (
        isinstance(node_ids, list) and all(isinstance(n, str) for n in node_ids)
    ):
        return _error("'nodeIds' must be a list of node id strings when present")
    mode = body.get("mode", "write")
    if mode not in ("write", "propose"):
        return _error("'mode' must be 'write' or 'propose' when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = resolve_provider_config(g.user)
        events = agents_services.solve_attachment_stream(
            _user_dir_key(g.user), project_id, attachment_id, config, node_ids,
            mode=mode,
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _error(str(exc), 400)
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
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    body = request.get_json(silent=True) or {}
    mode = body.get("mode", "step")
    if mode not in ("step", "auto"):
        return _error("'mode' must be 'step' or 'auto' when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = resolve_provider_config(g.user)
        events = agents_services.simulate_stream(
            _user_dir_key(g.user), project_id, attachment_id, config, mode=mode
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _error(str(exc), 400)
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
    "/projects/<project_id>/attachments/<attachment_id>/validate-node", methods=["POST"]
)
@require_auth
def validate_node(project_id: str, attachment_id: str):
    """Generate → execute-through → validate → self-correct → propose, for ONE
    node, as Server-Sent Events (dev/67-7 — Simulation Mode: validate).
    Body: ``{"ref": "<plan ref>"}`` or ``{"nodeId": "<node id>"}``. The
    outcome lands as a reviewed content proposal carrying the validation
    verdict; the saved spec is never mutated by validation itself."""
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    body = request.get_json(silent=True) or {}
    ref = body.get("ref")
    node_id = body.get("nodeId")
    if ref is not None and not isinstance(ref, str):
        return _error("'ref' must be a string when present")
    if node_id is not None and not isinstance(node_id, str):
        return _error("'nodeId' must be a string when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = resolve_provider_config(g.user)
        events = agents_services.validate_node_stream(
            _user_dir_key(g.user), project_id, attachment_id, config,
            ref=ref or None, node_id=node_id or None,
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _error(str(exc), 400)
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
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    body = request.get_json(silent=True) or {}
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return _error("body must include a non-empty 'message'")
    run_context = body.get("context")
    if run_context is not None and not isinstance(run_context, str):
        return _error("'context' must be a string when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = resolve_provider_config(g.user)
        payload = agents_services.run_attachment(
            _user_dir_key(g.user), project_id, attachment_id, message, config, run_context
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _error(str(exc), 400)
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
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    body = request.get_json(silent=True) or {}
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return _error("body must include a non-empty 'message'")
    run_context = body.get("context")
    if run_context is not None and not isinstance(run_context, str):
        return _error("'context' must be a string when present")
    try:
        projects_repo.get_for_user(project_id, g.user.id)
        config = resolve_provider_config(g.user)
        events = agents_services.stream_attachment(
            _user_dir_key(g.user), project_id, attachment_id, message, config, run_context
        )
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    except ProviderConfigError as exc:
        return _error(str(exc), 400)
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
