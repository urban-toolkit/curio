"""Agents catalog / lifecycle service layer.

Sits over the filesystem stores (``storage`` = definition artifacts, ``imports``
= account "My Imports", ``project_agents`` = per-project lockfile) and mirrors
``app/packages/services.py``: the route layer stays thin, this layer owns the
rules, and the project lockfile is read/written through ``projects.storage``.

Import and Install are separate explicit commands and never chain (DEC-029).
User-facing overview: ``docs/AGENTS.md``.
"""

from __future__ import annotations

import uuid

from utk_curio.backend.app.agents import (
    account_settings,
    attachments,
    builtin,
    imports,
    policy,
    project_agents,
    publications,
    quotas,
    sessions,
    storage,
)
from utk_curio.backend.app.agents.policy import PolicyValidationError, StaleRevisionError
from utk_curio.backend.app.agents.attachments import AttachmentError
from utk_curio.backend.app.agents.manifest import AgentManifest
from utk_curio.backend.app.agents.providers import (
    ProviderConfig,
    run_chat_completion,
    stream_chat_completion,
)
from utk_curio.backend.app.projects import storage as projects_storage


class AgentServiceError(Exception):
    """Service-layer error carrying an HTTP status for the route layer."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _manifest_to_card(
    m: AgentManifest,
    *,
    scope: str,
    imported: bool,
    installed_in_project: bool,
    published: bool = False,
    publishable: bool = False,
) -> dict:
    """Serialize a definition to the camelCase card the drawer consumes."""
    return {
        "id": m.agent_id,
        "version": m.version,
        "dirName": m.dir_name,
        "name": m.name,
        "category": m.category,
        "purpose": m.purpose,
        "capabilities": m.capability_ids,
        "hooks": [t.kind for t in m.compatible_targets],
        "provenance": {"publisher": m.provenance.publisher, "trust": m.provenance.trust},
        "imported": imported,
        "installedInProject": installed_in_project,
        "published": published,
        "publishable": publishable,
        "scope": scope,
    }


def _resolve_definition(user_key: str, coord: str) -> AgentManifest | None:
    """Resolve a coordinate's canonical metadata.

    An **owned/imported** store definition (trust != ``built-in``) is the
    authority for its coordinate — it may deliberately shadow a built-in id.
    Otherwise the **built-in roster** wins, so evolving built-in metadata (e.g.
    a widened ``compatibleTargets``) always takes effect even when a stale copy
    was materialized into the store by an earlier install. Falls back to the
    store copy, then the published catalog. (Runtime prompt bytes are resolved
    separately by ``_resolve_instruction_text``, still store-first.)
    """
    store_m = storage.load_installed_agent_definition(user_key, coord)
    if store_m is not None and store_m.provenance.trust != "built-in":
        return store_m
    builtin_m = builtin.get_builtin_manifest(coord)
    if builtin_m is not None:
        return builtin_m
    if store_m is not None:
        return store_m
    return publications.get_published_manifest(coord)


def _require_definition(user_key: str, coord: str) -> AgentManifest:
    m = _resolve_definition(user_key, coord)
    if m is None:
        raise AgentServiceError(f"no agent definition {coord!r} available", 404)
    return m


def _materialize_builtin(user_key: str, coord: str) -> None:
    """Write a built-in's bytes (manifest + instruction prompt) into the user store,
    so an installed agent is self-contained and runs from its own on-disk assets
    rather than the legacy ``llm-prompts/`` dir. No-op if already present or not a
    built-in (store/published defs already carry their bytes)."""
    if storage.load_installed_agent_definition(user_key, coord) is not None:
        return
    spec = builtin.get_builtin_spec(coord)
    if spec is None:
        return
    manifest = builtin.build_builtin_manifest(spec)
    rel = manifest["prompts"]["instruction"]["path"]
    text = builtin.read_instruction_text(coord)
    if text is None:
        return  # prompt file missing — leave the built-in fallback to handle runtime
    storage.write_definition(user_key, coord, manifest, {rel: text})


# ── read ────────────────────────────────────────────────────────────────────
def list_global_catalog(user_key: str, project_id: str | None = None) -> list[dict]:
    """The Global Catalog: the built-in agent definitions available to import/install."""
    imported = imports.load_imported_agents(user_key)
    installed: set[str] = set()
    if project_id:
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is not None:
            installed = set(project_agents.project_agents(spec))
    # Global Catalog = built-in roster ∪ published definitions (published wins on dupes).
    by_dir: dict[str, tuple[AgentManifest, bool]] = {}
    for m in builtin.list_builtin_manifests():
        by_dir[m.dir_name] = (m, False)
    for m in publications.list_published():
        by_dir[m.dir_name] = (m, True)
    return [
        _manifest_to_card(
            m,
            scope="global",
            imported=dir_name in imported,
            installed_in_project=dir_name in installed,
            published=published,
        )
        for dir_name, (m, published) in sorted(by_dir.items())
    ]


def list_my_imports(user_key: str) -> list[dict]:
    """Account "My Imports": each imported coordinate whose definition resolves."""
    imported = imports.load_imported_agents(user_key)
    out: list[dict] = []
    for coord in sorted(imported):
        m = _resolve_definition(user_key, coord)
        if m is None:
            continue
        # Publishable only when it is an owned imported definition (trust=imported) —
        # never a built-in, even after its bytes are materialized into the store.
        out.append(
            _manifest_to_card(
                m,
                scope="my-imports",
                imported=True,
                installed_in_project=False,
                published=publications.is_published(coord),
                publishable=(m.provenance.trust == "imported"),
            )
        )
    return out


def list_installed_in_project(user_key: str, project_id: str) -> list[dict]:
    """The project's installed templates from its ``dataflow.agents`` lockfile."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    imported = imports.load_imported_agents(user_key)
    out: list[dict] = []
    for coord in project_agents.project_agents(spec):
        m = _resolve_definition(user_key, coord)
        if m is None:
            continue
        out.append(
            _manifest_to_card(
                m, scope="installed", imported=coord in imported, installed_in_project=True
            )
        )
    return out


# ── lifecycle commands (explicit, non-chaining) ──────────────────────────────
def import_agent(user_key: str, coord: str) -> dict:
    """Record *coord* in the account's My Imports (does not install into a project)."""
    _require_definition(user_key, coord)
    _materialize_builtin(user_key, coord)
    imports.add_imported_agent(user_key, coord)
    return {"coord": coord, "imported": True}


def remove_import(user_key: str, coord: str) -> dict:
    """Drop *coord* from My Imports (does not touch project installs)."""
    imports.remove_imported_agent(user_key, coord)
    return {"coord": coord, "imported": False}


def _defaults_seed(user_key: str, coord: str) -> dict:
    """Seed for a fresh project-default record from the definition's
    ``settingsDefaults`` (built-ins carry none → empty)."""
    m = _resolve_definition(user_key, coord)
    if m is None:
        return {}
    seed: dict = {}
    if m.settings_profile_id:
        seed["profileId"] = m.settings_profile_id
    if m.settings_profile_version:
        seed["profileVersion"] = m.settings_profile_version
    return seed


def install_in_project(user_key: str, project_id: str, coord: str) -> dict:
    """Add *coord* to the project's lockfile (explicit; never auto-imports).

    Also materializes the project-agent-default record (memo dev/23) — an
    independent per-project profile the settings screens later edit. Idempotent:
    reinstalling never resets an existing record.
    """
    _require_definition(user_key, coord)
    _materialize_builtin(user_key, coord)
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    current = project_agents.project_agents(spec)
    dirty = False
    if coord not in current:
        project_agents.set_project_agents(spec, current + [coord])
        dirty = True
    if coord not in project_agents.agent_defaults(spec):
        project_agents.materialize_defaults(spec, coord, _defaults_seed(user_key, coord))
        dirty = True
    if dirty:
        projects_storage.write_spec(user_key, project_id, spec)
    return {"agents": project_agents.project_agents(spec)}


def uninstall_from_project(user_key: str, project_id: str, coord: str) -> dict:
    """Remove *coord* from the project's lockfile and drop its defaults record."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    current = project_agents.project_agents(spec)
    dirty = False
    if coord in current:
        project_agents.set_project_agents(spec, [c for c in current if c != coord])
        dirty = True
    if project_agents.drop_defaults(spec, coord):
        dirty = True
    if dirty:
        projects_storage.write_spec(user_key, project_id, spec)
    return {"agents": project_agents.project_agents(spec)}


def get_project_agent_defaults(user_key: str, project_id: str, coord: str) -> dict:
    """The project-agent-default scope for one installed template (memo dev/23).

    Returns the per-project record plus the server-computed **effective** v1
    policy with provenance: the account runs/day quota (+ today's usage) and a
    no-secrets provider summary. Lazily materializes the record for installs
    that predate the section. 404 when the coord isn't installed here.
    """
    spec = _read_spec_or_404(user_key, project_id)
    if coord not in project_agents.project_agents(spec):
        raise AgentServiceError(f"{coord!r} is not installed in this project", 404)
    record = project_agents.agent_defaults(spec).get(coord)
    if record is None:
        record = project_agents.materialize_defaults(
            spec, coord, _defaults_seed(user_key, coord)
        )
        projects_storage.write_spec(user_key, project_id, spec)
    m = _resolve_definition(user_key, coord)
    acct = account_settings.read_record(user_key)["settings"]
    eff = policy.effective(acct, record.get("settings") or {})
    used = quotas.runs_used_today(user_key)
    estimate = eff["cost"]["estimatedCostPerRunUsd"]["value"]
    return {
        "coord": coord,
        "name": m.name if m else coord,
        "revision": record.get("revision", 1),
        "settings": record.get("settings", {}),
        "effective": {
            "quotas": {
                "runsPerDay": {**eff["quotas"]["runsPerDay"], "usedToday": used}
            },
            "cost": {
                **eff["cost"],
                "estimatedSpendTodayUsd": round(used * estimate, 6)
                if estimate is not None
                else None,
            },
            "resources": dict(eff["resources"]),
        },
    }


def update_project_agent_defaults(
    user_key: str, project_id: str, coord: str, revision: object, settings: object
) -> dict:
    """PATCH the project-agent-default record (memo dev/24): tighten-only
    against the account-effective policy, optimistic revision, non-policy seed
    keys (e.g. the manifest profile id) preserved. ``{"settings": {}}`` is
    `Reset to agent default` for this one template."""
    if not isinstance(revision, int):
        raise AgentServiceError("revision must be an integer", 400)
    spec = _read_spec_or_404(user_key, project_id)
    if coord not in project_agents.project_agents(spec):
        raise AgentServiceError(f"{coord!r} is not installed in this project", 404)
    record = project_agents.agent_defaults(spec).get(coord)
    if record is None:
        record = project_agents.materialize_defaults(
            spec, coord, _defaults_seed(user_key, coord)
        )
    if record.get("revision", 1) != revision:
        raise AgentServiceError(
            f"project defaults changed (revision {record.get('revision', 1)}, sent {revision})",
            409,
        )
    acct = account_settings.read_record(user_key)["settings"]
    try:
        cleaned = policy.validate_patch(settings, "project", policy.effective(acct))
    except PolicyValidationError as exc:
        raise AgentServiceError(str(exc), 400) from exc
    existing = record.get("settings") or {}
    preserved = {k: v for k, v in existing.items() if k not in policy._FIELDS}
    record["settings"] = {**preserved, **cleaned}
    record["revision"] = revision + 1
    projects_storage.write_spec(user_key, project_id, spec)
    return get_project_agent_defaults(user_key, project_id, coord)


def get_account_settings(user_key: str) -> dict:
    """The Account-policy scope (memo dev/24): record + effective + ceilings."""
    record = account_settings.read_record(user_key)
    return {
        "revision": record["revision"],
        "settings": record["settings"],
        "effective": policy.effective(record["settings"]),
        "ceilings": policy.deployment_defaults(),
        "usedToday": quotas.runs_used_today(user_key),
    }


def update_account_settings(user_key: str, revision: object, settings: object) -> dict:
    """PATCH the account settings record: tighten-only against the deployment
    ceilings, optimistic revision (409 on stale)."""
    if not isinstance(revision, int):
        raise AgentServiceError("revision must be an integer", 400)
    try:
        cleaned = policy.validate_patch(settings, "account", policy.effective({}))
    except PolicyValidationError as exc:
        raise AgentServiceError(str(exc), 400) from exc
    try:
        account_settings.write_settings(user_key, cleaned, revision)
    except StaleRevisionError as exc:
        raise AgentServiceError(str(exc), 409) from exc
    return get_account_settings(user_key)


def publish_agent(user_key: str, coord: str) -> dict:
    """Publish an owned imported definition to the Global Catalog.

    Imported-only (`DEC-030`): the coordinate must resolve to a store definition
    whose provenance trust is ``imported`` (a user-owned definition) and be in My
    Imports. Built-ins — even after their bytes are materialized into the store —
    carry trust ``built-in`` and are rejected here.
    """
    m = storage.load_installed_agent_definition(user_key, coord)
    if m is None or m.provenance.trust != "imported":
        raise AgentServiceError(
            "only an owned imported definition (trust=imported) can be published; built-in, "
            "global, or absent definitions cannot",
            400,
        )
    if coord not in imports.load_imported_agents(user_key):
        raise AgentServiceError("import the definition before publishing it", 400)
    publications.publish_from_dir(storage.agent_definition_dir(user_key, coord), coord)
    return {"coord": coord, "published": True}


def unpublish_agent(user_key: str, coord: str) -> dict:
    """Remove an owned definition from the Global Catalog (only its owner may)."""
    if storage.load_installed_agent_definition(user_key, coord) is None:
        raise AgentServiceError("only the owning account can unpublish this definition", 403)
    publications.unpublish(coord)
    return {"coord": coord, "published": False}


# ── attachments (private agent instances in the project graph) ───────────────
def _read_spec_or_404(user_key: str, project_id: str) -> dict:
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    return spec


def _attachment_card(spec: dict, record: dict, user_key: str) -> dict:
    """Attachment record + a resolved name/hooks for its source template (best-effort).

    ``intent`` is the record's override when the user edited it, else the
    definition's instruction prompt bytes resolved at read time — so an
    unedited intent always reflects the actual prompt source (memo ``dev/19``;
    nothing duplicates prompt text into stored state).
    """
    coord = record.get("coord", "")
    m = _resolve_definition(user_key, coord)
    return {
        "attachmentId": record.get("attachmentId"),
        "coord": coord,
        "target": record.get("target"),
        "sessionId": record.get("sessionId"),
        "revision": record.get("revision", 1),
        "name": m.name if m else coord,
        "category": m.category if m else None,
        "hooks": [t.kind for t in m.compatible_targets] if m else [],
        "intent": record.get("intent") or _resolve_instruction_text(user_key, coord),
        "intentEdited": bool(record.get("intent")),
        # Conversation title (memo dev/25): the custom portion only — the
        # client composes "<name>: <title>" at display time.
        "title": record.get("title") or None,
        "titleEdited": bool(record.get("titleEdited")),
    }


def list_project_attachments(user_key: str, project_id: str) -> list[dict]:
    spec = _read_spec_or_404(user_key, project_id)
    return [_attachment_card(spec, r, user_key) for r in attachments.list_attachments(spec)]


def attach_agent(user_key: str, project_id: str, coord: str, target: object) -> dict:
    """Attach an installed template to a target. Requires the template installed
    in this project (no auto-install), and a valid target."""
    spec = _read_spec_or_404(user_key, project_id)
    if coord not in project_agents.project_agents(spec):
        raise AgentServiceError(
            "install the agent in this project before attaching it", 400
        )
    # Enforce the agent's declared compatibility: a canvas-only agent can only
    # attach to the canvas, a node-only agent only to nodes, a dual-compatible
    # agent to either. (attachments.attach still validates the target exists.)
    manifest = _resolve_definition(user_key, coord)
    allowed = {t.kind for t in manifest.compatible_targets} if manifest else set()
    kind = target.get("kind") if isinstance(target, dict) else None
    if kind and allowed and kind not in allowed:
        raise AgentServiceError(
            f"this agent attaches to {', '.join(sorted(allowed))}, not {kind}", 400
        )
    try:
        record = attachments.attach(
            spec, coord, target, attachment_id=uuid.uuid4().hex, session_id=uuid.uuid4().hex
        )
    except AttachmentError as exc:
        raise AgentServiceError(str(exc), 400) from exc
    projects_storage.write_spec(user_key, project_id, spec)
    return _attachment_card(spec, record, user_key)


def detach_agent(user_key: str, project_id: str, attachment_id: str) -> dict:
    spec = _read_spec_or_404(user_key, project_id)
    record = attachments.get_attachment(spec, attachment_id)
    removed = attachments.detach(spec, attachment_id)
    if removed:
        projects_storage.write_spec(user_key, project_id, spec)
        # A transcript lives exactly as long as its attachment (dev/20).
        session_id = (record or {}).get("sessionId")
        if isinstance(session_id, str):
            sessions.delete_session(user_key, project_id, session_id)
    return {"attachmentId": attachment_id, "detached": removed}


def update_attachment_intent(
    user_key: str, project_id: str, attachment_id: str, intent: str | None
) -> dict:
    """Set/clear the attachment's intent override; empty falls back to the prompt source."""
    spec = _read_spec_or_404(user_key, project_id)
    try:
        record = attachments.set_intent(spec, attachment_id, intent)
    except AttachmentError as exc:
        raise AgentServiceError(str(exc), 400) from exc
    if record is None:
        raise AgentServiceError(f"attachment {attachment_id!r} not found", 404)
    projects_storage.write_spec(user_key, project_id, spec)
    return _attachment_card(spec, record, user_key)


def update_attachment_title(
    user_key: str, project_id: str, attachment_id: str, title: str
) -> dict:
    """Manually rename the conversation (memo dev/25). A manual title always
    wins over auto-generation and survives conversation clears."""
    spec = _read_spec_or_404(user_key, project_id)
    try:
        record = attachments.set_title(spec, attachment_id, title, edited=True)
    except AttachmentError as exc:
        raise AgentServiceError(str(exc), 400) from exc
    if record is None:
        raise AgentServiceError(f"attachment {attachment_id!r} not found", 404)
    projects_storage.write_spec(user_key, project_id, spec)
    return _attachment_card(spec, record, user_key)


def _record_or_404(spec: dict, attachment_id: str) -> dict:
    record = attachments.get_attachment(spec, attachment_id)
    if record is None:
        raise AgentServiceError(f"attachment {attachment_id!r} not found", 404)
    return record


def get_attachment_session(user_key: str, project_id: str, attachment_id: str) -> dict:
    """The attachment's persisted transcript (empty for a session with no file)."""
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    session_id = record.get("sessionId")
    turns = (
        sessions.read_turns(user_key, project_id, session_id)
        if isinstance(session_id, str)
        else []
    )
    return {"attachmentId": attachment_id, "sessionId": session_id, "turns": turns}


def clear_attachment_session(user_key: str, project_id: str, attachment_id: str) -> dict:
    """Clear the transcript (keeps the attachment and its session id)."""
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    session_id = record.get("sessionId")
    if isinstance(session_id, str):
        sessions.clear_turns(user_key, project_id, session_id, attachment_id)
    # An auto-generated title describes the conversation that was just cleared
    # — drop it so the next first message regenerates one. A manual title is
    # the user's deliberate name for the instance and is kept (memo dev/25).
    if record.get("title") and not record.get("titleEdited"):
        attachments.set_title(spec, attachment_id, None, edited=False)
        projects_storage.write_spec(user_key, project_id, spec)
    return {"attachmentId": attachment_id, "sessionId": session_id, "turns": []}


def _resolve_instruction_text(user_key: str, coord: str) -> str | None:
    """The agent's instruction prompt text.

    Reads the definition's own on-disk asset first — the materialized store copy,
    then the published-catalog copy — so an installed agent runs from its own
    bytes. Falls back to the built-in roster's ``llm-prompts/`` source only when a
    built-in has not been materialized.
    """
    m = storage.load_installed_agent_definition(user_key, coord)
    base = storage.agent_definition_dir(user_key, coord) if m is not None else None
    if m is None:
        m = publications.get_published_manifest(coord)
        base = publications.published_agent_dir(coord) if m is not None else None
    if m is not None and base is not None:
        asset = m.prompts.get("instruction")
        if asset is not None:
            path = base / asset.path
            if path.is_file():
                return path.read_text(encoding="utf-8")
    return builtin.read_instruction_text(coord)


# ── conversation titles (memo dev/25) ────────────────────────────────────────
TITLE_PROMPT = (
    "Summarize the user's request as a short descriptive title of three or "
    "four words. Reply with the title only — no quotes and no trailing period."
)
# A 3–4 word title needs very few tokens; keep the utility call cheap.
TITLE_MAX_OUTPUT_TOKENS = 16


def sanitize_title(raw: object) -> str | None:
    """Normalize LLM title output to plain display text, or ``None`` to discard.

    The model output is untrusted: collapse whitespace/newlines, strip wrapping
    quotes/backticks and a trailing period, truncate to
    ``attachments.TITLE_MAX_CHARS``, and reject anything empty after cleaning.
    """
    if not isinstance(raw, str):
        return None
    text = " ".join(raw.split())
    text = text.strip("\"'`“”‘’ ").rstrip(".").strip()
    if len(text) > attachments.TITLE_MAX_CHARS:
        text = text[: attachments.TITLE_MAX_CHARS].rstrip()
    return text or None


def _generate_conversation_title(
    user_key: str, project_id: str, attachment_id: str, message: str, config: ProviderConfig
) -> None:
    """Best-effort auto title from the first user message (memo dev/25).

    Runs after the reply is persisted so it never delays the answer; a provider
    failure or rejected output leaves the attachment untitled, silently. The
    precondition (untitled, not manually edited) is re-checked on a fresh spec
    read so a manual rename that landed mid-run wins.
    """
    try:
        raw = run_chat_completion(
            config,
            [
                {"role": "system", "content": TITLE_PROMPT},
                {"role": "user", "content": message},
            ],
            max_output_tokens=TITLE_MAX_OUTPUT_TOKENS,
        )
        title = sanitize_title(raw)
        if title is None:
            return
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is None:
            return
        record = attachments.get_attachment(spec, attachment_id)
        if record is None or record.get("title") or record.get("titleEdited"):
            return
        attachments.set_title(spec, attachment_id, title, edited=False)
        projects_storage.write_spec(user_key, project_id, spec)
    except Exception:
        pass  # a missing title is a cosmetic gap, never a run error


def _run_policy(user_key: str, project_id: str, coord: str, spec: dict) -> dict:
    """Admission + dispatch inputs from the effective policy (memo dev/24).

    ``template_limit`` applies only when the project scope is the tightest
    source; the account counter is gated at the account-effective value."""
    acct = account_settings.read_record(user_key)["settings"]
    record = project_agents.agent_defaults(spec).get(coord) or {}
    acc_eff = policy.effective(acct)
    full_eff = policy.effective(acct, record.get("settings") or {})
    runs = full_eff["quotas"]["runsPerDay"]
    return {
        "admit": {
            "account_limit": acc_eff["quotas"]["runsPerDay"]["value"],
            "template_key": f"{project_id}/{coord}",
            "template_limit": runs["value"] if runs["source"] == "project" else None,
            "daily_budget_usd": full_eff["cost"]["dailyBudgetUsd"]["value"],
            "estimated_cost_per_run_usd": full_eff["cost"]["estimatedCostPerRunUsd"]["value"],
        },
        "max_output_tokens": full_eff["resources"]["maxOutputTokens"]["value"],
    }


def _prepare_run(
    user_key: str, project_id: str, attachment_id: str, message: str
) -> tuple[str, str | None, list, dict, bool]:
    """Shared run/stream setup: resolve the attachment, its instruction (intent
    override → prompt source, dev/19), the provider messages including the
    bounded session context (dev/20), and the effective run policy (dev/24).
    Returns ``(coord, session_id, messages, run_policy, wants_title)``;
    ``session_id`` is None for a record without one (stateless fallback), and
    ``wants_title`` is True when this message is the conversation's first —
    an untitled, never-manually-renamed attachment with no prior user turn —
    so a title should be auto-generated after the reply (memo dev/25)."""
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    coord = record.get("coord", "")
    instruction = record.get("intent") or _resolve_instruction_text(user_key, coord)
    if instruction is None:
        raise AgentServiceError(
            f"no instruction prompt available for {coord!r} (not materialized)", 422
        )
    session_id = record.get("sessionId")
    if not isinstance(session_id, str):
        session_id = None
    prior = sessions.read_turns(user_key, project_id, session_id) if session_id else []
    messages = [
        {"role": "system", "content": instruction},
        *sessions.context_messages(prior),
        {"role": "user", "content": message},
    ]
    wants_title = (
        not record.get("title")
        and not record.get("titleEdited")
        and not any(t.get("role") == "user" for t in prior)
    )
    return coord, session_id, messages, _run_policy(user_key, project_id, coord, spec), wants_title


def _persist_exchange(
    user_key: str,
    project_id: str,
    session_id: str | None,
    attachment_id: str,
    message: str,
    reply: str,
    *,
    error: bool = False,
) -> None:
    """Persist one exchange to the session (no-op without a session id). Error
    markers are display-only history, excluded from future context (dev/20)."""
    if session_id is None:
        return
    sessions.append_turns(
        user_key,
        project_id,
        session_id,
        attachment_id,
        [
            sessions.make_turn("user", message),
            sessions.make_turn("agent", reply, error=error),
        ],
    )


def run_attachment(
    user_key: str, project_id: str, attachment_id: str, message: str, config: ProviderConfig
) -> dict:
    """Run one turn of an attached agent through the provider port.

    Session-aware (dev/20): the system turn is the attachment's intent override
    (dev/19) or the resolved instruction prompt, followed by a bounded window of
    the session's prior turns, then the new user message. Both sides of the
    exchange persist to the session file so a reload restores the conversation;
    a provider failure persists the user turn plus a display-only error marker
    (excluded from future context) so history matches what the user saw.
    """
    coord, session_id, messages, run_policy, wants_title = _prepare_run(
        user_key, project_id, attachment_id, message
    )
    # Admission after validation (an invalid request never consumes quota) and
    # before provider dispatch (a denied run never reaches a provider).
    quotas.admit(user_key, **run_policy["admit"])
    try:
        reply = run_chat_completion(
            config, messages, max_output_tokens=run_policy["max_output_tokens"]
        )
    except Exception as exc:
        _persist_exchange(
            user_key, project_id, session_id, attachment_id, message, f"(error) {exc}", error=True
        )
        raise AgentServiceError(f"agent run failed: {exc}", 502) from exc
    _persist_exchange(user_key, project_id, session_id, attachment_id, message, reply)
    if wants_title:
        _generate_conversation_title(user_key, project_id, attachment_id, message, config)
    return {"attachmentId": attachment_id, "coord": coord, "reply": reply}


def stream_attachment(
    user_key: str, project_id: str, attachment_id: str, message: str, config: ProviderConfig
):
    """Streaming twin of :func:`run_attachment` (memo dev/22).

    Validates eagerly (404/422 raise before any streaming starts), then returns
    a generator of ``("delta", text)`` events ending in ``("done", full_reply)``
    — or ``("error", message)`` on a provider failure. Persistence semantics are
    identical to ``run_attachment``: the full exchange is written once at
    completion; a failure persists the user turn plus a display-only error
    marker. Nothing is persisted per-delta.
    """
    coord, session_id, messages, run_policy, wants_title = _prepare_run(
        user_key, project_id, attachment_id, message
    )
    # Eager admission: a quota/budget denial surfaces as a plain 429 before any
    # streaming begins, and consumes/persists nothing.
    quotas.admit(user_key, **run_policy["admit"])

    def _events():
        parts: list[str] = []
        try:
            for delta in stream_chat_completion(
                config, messages, max_output_tokens=run_policy["max_output_tokens"]
            ):
                parts.append(delta)
                yield ("delta", delta)
        except Exception as exc:  # provider failure mid-stream
            _persist_exchange(
                user_key,
                project_id,
                session_id,
                attachment_id,
                message,
                f"(error) {exc}",
                error=True,
            )
            yield ("error", f"agent run failed: {exc}")
            return
        reply = "".join(parts)
        _persist_exchange(user_key, project_id, session_id, attachment_id, message, reply)
        # Title before the done frame: the reply text already streamed via
        # deltas, and the client's post-send refresh must see the title.
        if wants_title:
            _generate_conversation_title(user_key, project_id, attachment_id, message, config)
        yield ("done", reply)

    return _events()
