"""Agents catalog / lifecycle service layer.

Sits over the filesystem stores (``storage`` = definition artifacts, ``imports``
= account "My Imports", ``project_agents`` = per-project lockfile) and mirrors
``app/packages/services.py``: the route layer stays thin, this layer owns the
rules, and the project lockfile is read/written through ``projects.storage``.

Import and Install are separate explicit commands and never chain (DEC-029).
User-facing overview: ``docs/AGENTS.md``.
"""

from __future__ import annotations

import time
import uuid

from utk_curio.backend.app.agents import (
    account_settings,
    attachments,
    builtin,
    content,
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
    instruction = builtin.read_prompt_text(coord, "instruction")
    if instruction is None:
        return  # prompt file missing — leave the built-in fallback to handle runtime
    files = {manifest["prompts"]["instruction"]["path"]: instruction}
    preamble = builtin.read_prompt_text(coord, "system")
    if preamble is not None:
        files[manifest["prompts"]["system"]["path"]] = preamble
    storage.write_definition(user_key, coord, manifest, files)


# ── upload-import (user-authored definitions, memo dev/36) ───────────────────
_UPLOAD_MAX_FILES = 16
_UPLOAD_MAX_FILE_BYTES = 256 * 1024
_UPLOAD_MAX_TOTAL_BYTES = 1024 * 1024


def upload_import(user_key: str, manifest_raw: object, prompt_files: object) -> dict:
    """Create a user-owned definition from an uploaded manifest + prompt texts.

    Fail-closed rules (memo dev/36): the manifest must pass the package
    contract; ``provenance.trust`` is forced to ``"imported"`` server-side;
    prompt digests are computed from the uploaded bytes (client digests are
    ignored); the provided files must correspond exactly to the manifest's
    referenced prompt paths; size limits apply; an existing store coordinate is
    a 409 (definitions are immutable — bump the version); the write is atomic.
    Success registers the coordinate in My Imports (upload IS an explicit
    account import) and returns the My Imports card — publishable at last.
    """
    import hashlib

    from utk_curio.backend.app.agents.manifest import AgentManifestError, parse_agent_manifest
    from utk_curio.backend.app.common.safe_paths import PathTraversalError

    if not isinstance(manifest_raw, dict):
        raise AgentServiceError("'manifest' must be an object", 400)
    if not isinstance(prompt_files, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in prompt_files.items()
    ):
        raise AgentServiceError("'prompts' must map file paths to text", 400)
    if len(prompt_files) > _UPLOAD_MAX_FILES:
        raise AgentServiceError(f"at most {_UPLOAD_MAX_FILES} prompt files", 413)
    total = 0
    for rel, text in prompt_files.items():
        size = len(text.encode("utf-8"))
        total += size
        if size > _UPLOAD_MAX_FILE_BYTES:
            raise AgentServiceError(f"prompt file {rel!r} exceeds 256 KB", 413)
    if total > _UPLOAD_MAX_TOTAL_BYTES:
        raise AgentServiceError("prompt files exceed 1 MB total", 413)

    manifest = dict(manifest_raw)
    prov = manifest.get("provenance")
    if not isinstance(prov, dict):
        raise AgentServiceError("manifest.provenance must be an object", 400)
    # Forced provenance: an upload can never claim built-in/global trust —
    # that would corrupt publish gating and roster-first resolution.
    manifest["provenance"] = {**prov, "trust": "imported"}

    # Digests from bytes: stamp each referenced prompt's sha256 from the
    # uploaded text, and require exact file<->manifest correspondence.
    prompts_sect = manifest.get("prompts") or {}
    if not isinstance(prompts_sect, dict):
        raise AgentServiceError("manifest.prompts must be an object", 400)
    referenced: set[str] = set()
    stamped = {}
    for name, asset in prompts_sect.items():
        if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
            raise AgentServiceError(f"manifest.prompts.{name} must declare a path", 400)
        rel = asset["path"]
        if rel not in prompt_files:
            raise AgentServiceError(f"prompt file {rel!r} referenced by the manifest is missing", 400)
        referenced.add(rel)
        stamped[name] = {
            **asset,
            "sha256": hashlib.sha256(prompt_files[rel].encode("utf-8")).hexdigest(),
        }
    if stamped:
        manifest["prompts"] = stamped
    extra = set(prompt_files) - referenced
    if extra:
        raise AgentServiceError(
            f"prompt files not referenced by the manifest: {sorted(extra)}", 400
        )

    try:
        m = parse_agent_manifest(manifest, where="upload")
    except AgentManifestError as exc:
        raise AgentServiceError(str(exc), 400) from exc

    coord = m.dir_name
    if storage.load_installed_agent_definition(user_key, coord) is not None:
        raise AgentServiceError(
            f"{coord!r} already exists in your store — definitions are immutable; bump the version",
            409,
        )
    try:
        storage.write_definition_atomic(user_key, coord, manifest, prompt_files)
    except FileExistsError as exc:
        raise AgentServiceError(
            f"{coord!r} already exists in your store — definitions are immutable; bump the version",
            409,
        ) from exc
    except PathTraversalError as exc:
        raise AgentServiceError(str(exc), 400) from exc

    imports.add_imported_agent(user_key, coord)
    return _manifest_to_card(
        m,
        scope="my-imports",
        imported=True,
        installed_in_project=False,
        published=publications.is_published(coord),
        publishable=True,
    )


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
                "runsPerDay": {**eff["quotas"]["runsPerDay"], "usedToday": used},
                # Actual tokens counted this window (memo dev/37).
                "usageToday": quotas.usage_today(user_key),
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
        # Actual tokens counted this window (memo dev/37) — never estimated.
        "usageToday": quotas.usage_today(user_key),
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


def _resolve_prompt_text(user_key: str, coord: str, name: str) -> str | None:
    """A definition's prompt asset text (``"instruction"`` or ``"system"``).

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
        asset = m.prompts.get(name)
        if asset is not None:
            path = base / asset.path
            if path.is_file():
                return path.read_text(encoding="utf-8")
        elif name == "system":
            # A definition that declares no preamble runs without one — do NOT
            # fall back to the built-in default for a resolvable non-roster def.
            return builtin.read_prompt_text(coord, name)
    return builtin.read_prompt_text(coord, name)


def _resolve_instruction_text(user_key: str, coord: str) -> str | None:
    """The agent's instruction prompt text (see ``_resolve_prompt_text``)."""
    return _resolve_prompt_text(user_key, coord, "instruction")


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
        # The title call is internal housekeeping, not an execution (dev/37):
        # it writes no execution record, but its tokens still cost — count them.
        usage_sink: dict = {}
        raw = run_chat_completion(
            config,
            [
                {"role": "system", "content": TITLE_PROMPT},
                {"role": "user", "content": message},
            ],
            max_output_tokens=TITLE_MAX_OUTPUT_TOKENS,
            usage_out=usage_sink,
        )
        _record_usage(user_key, usage_sink)
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
        # Flat effective-policy snapshot pinned on the execution record
        # (DEC-031): what was admitted, not where each value came from.
        "policy_pins": {
            "runsPerDay": runs["value"],
            "maxOutputTokens": full_eff["resources"]["maxOutputTokens"]["value"],
            "dailyBudgetUsd": full_eff["cost"]["dailyBudgetUsd"]["value"],
            "estimatedCostPerRunUsd": full_eff["cost"]["estimatedCostPerRunUsd"]["value"],
        },
    }


def _prompt_digest(user_key: str, coord: str) -> str | None:
    """The resolved definition's instruction-prompt sha256 (a DEC-031 pin).

    Read from the manifest asset, not recomputed — the digest identifies the
    definition bytes that were dispatched. ``None`` when the manifest carries
    no digest (tolerated; pre-upload-import definitions may be unstamped)."""
    m = _resolve_definition(user_key, coord)
    asset = m.prompts.get("instruction") if m is not None else None
    return asset.sha256 if asset is not None else None


def _execution_record(
    execution_id: str, pins: dict, usage: dict, started: float, status: str
) -> dict:
    """Assemble the per-run execution record persisted on the agent turn
    (memo dev/37). ``usage`` is the provider port's ``usage_out`` sink —
    Actual counts or ``None``, never estimated (memo dev/11)."""
    return {
        "executionId": execution_id,
        "pins": pins,
        "usage": dict(usage) if usage else None,
        "durationMs": int((time.monotonic() - started) * 1000),
        "status": status,
    }


def _record_usage(user_key: str, usage_sink: dict) -> None:
    """Fold one provider call's Actual usage into the daily counters (dev/37)."""
    if usage_sink:
        quotas.record_usage(
            user_key, usage_sink.get("inputTokens"), usage_sink.get("outputTokens")
        )


def _prepare_run(
    user_key: str, project_id: str, attachment_id: str, message: str, config: ProviderConfig
) -> tuple[str, str | None, list, dict, bool, dict]:
    """Shared run/stream setup: resolve the attachment, its instruction (intent
    override → prompt source, dev/19), the provider messages including the
    bounded session context (dev/20), and the effective run policy (dev/24).
    Returns ``(coord, session_id, messages, run_policy, wants_title, pins)``;
    ``session_id`` is None for a record without one (stateless fallback),
    ``wants_title`` is True when this message is the conversation's first —
    an untitled, never-manually-renamed attachment with no prior user turn —
    so a title should be auto-generated after the reply (memo dev/25), and
    ``pins`` are the DEC-031 reproducibility pins resolved from what actually
    dispatches (memo dev/37): coord, prompt digest, intent-edited flag,
    provider/model, and the effective-policy snapshot. No secrets."""
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    coord = record.get("coord", "")
    instruction = record.get("intent") or _resolve_instruction_text(user_key, coord)
    if instruction is None:
        raise AgentServiceError(
            f"no instruction prompt available for {coord!r} (not materialized)", 422
        )
    # Migration parity (dev/06): the legacy call sites composed the system
    # preamble + the prompt; an edited intent replaces the instruction portion
    # only, so the preamble still applies.
    preamble = _resolve_prompt_text(user_key, coord, "system")
    system_content = f"{preamble}\n\n{instruction}" if preamble else instruction
    # Structured-tail protocol (memo dev/39): the runtime-owned instruction
    # composes AFTER the preamble + intent, so an edited intent can neither
    # strip nor spoof it. Optional in tone; costs a few hundred prompt tokens.
    system_content = f"{system_content}\n\n{content.TAIL_INSTRUCTION}"
    session_id = record.get("sessionId")
    if not isinstance(session_id, str):
        session_id = None
    prior = sessions.read_turns(user_key, project_id, session_id) if session_id else []
    messages = [
        {"role": "system", "content": system_content},
        *sessions.context_messages(prior),
        {"role": "user", "content": message},
    ]
    wants_title = (
        not record.get("title")
        and not record.get("titleEdited")
        and not any(t.get("role") == "user" for t in prior)
    )
    run_policy = _run_policy(user_key, project_id, coord, spec)
    pins = {
        "coord": coord,
        "promptSha256": _prompt_digest(user_key, coord),
        "intentEdited": bool(record.get("intent")),
        "provider": config.api_type,
        "model": config.model,
        "policy": run_policy["policy_pins"],
    }
    return coord, session_id, messages, run_policy, wants_title, pins


def _persist_exchange(
    user_key: str,
    project_id: str,
    session_id: str | None,
    attachment_id: str,
    message: str,
    reply: str,
    *,
    error: bool = False,
    execution: dict | None = None,
    parts: list | None = None,
) -> None:
    """Persist one exchange to the session (no-op without a session id). Error
    markers are display-only history, excluded from future context (dev/20).
    The execution record (dev/37) and content parts (dev/39) ride the agent
    turn."""
    if session_id is None:
        return
    sessions.append_turns(
        user_key,
        project_id,
        session_id,
        attachment_id,
        [
            sessions.make_turn("user", message),
            sessions.make_turn("agent", reply, error=error, execution=execution, content=parts),
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
    coord, session_id, messages, run_policy, wants_title, pins = _prepare_run(
        user_key, project_id, attachment_id, message, config
    )
    # Admission after validation (an invalid request never consumes quota) and
    # before provider dispatch (a denied run never reaches a provider).
    quotas.admit(user_key, **run_policy["admit"])
    execution_id = uuid.uuid4().hex
    usage_sink: dict = {}
    started = time.monotonic()
    try:
        reply = run_chat_completion(
            config,
            messages,
            max_output_tokens=run_policy["max_output_tokens"],
            usage_out=usage_sink,
        )
    except Exception as exc:
        _record_usage(user_key, usage_sink)
        _persist_exchange(
            user_key,
            project_id,
            session_id,
            attachment_id,
            message,
            f"(error) {exc}",
            error=True,
            execution=_execution_record(execution_id, pins, usage_sink, started, "error"),
        )
        raise AgentServiceError(f"agent run failed: {exc}", 502) from exc
    _record_usage(user_key, usage_sink)
    execution = _execution_record(execution_id, pins, usage_sink, started, "ok")
    # Structured tail (dev/39): a valid terminal block becomes typed parts and
    # leaves the visible text; anything else passes through untouched.
    visible, parts = content.extract_content(reply)
    _persist_exchange(
        user_key,
        project_id,
        session_id,
        attachment_id,
        message,
        visible,
        execution=execution,
        parts=parts,
    )
    if wants_title:
        _generate_conversation_title(user_key, project_id, attachment_id, message, config)
    return {
        "attachmentId": attachment_id,
        "coord": coord,
        "reply": visible,
        "executionId": execution_id,
        "usage": execution["usage"],
        "content": parts,
    }


def stream_attachment(
    user_key: str, project_id: str, attachment_id: str, message: str, config: ProviderConfig
):
    """Streaming twin of :func:`run_attachment` (memo dev/22).

    Validates eagerly (404/422 raise before any streaming starts), then returns
    a generator opening with ``("execution", {executionId})`` (memo dev/37),
    followed by ``("delta", text)`` events, optionally ``("content", {parts})``
    when the reply carried a valid structured tail (memo dev/39), ending in
    ``("done", {reply, executionId, usage, content})`` — or
    ``("error", message)`` on a provider failure. Persistence semantics are
    identical to ``run_attachment``: the full exchange is written once at
    completion; a failure persists the user turn plus a display-only error
    marker. Nothing is persisted per-delta.
    """
    coord, session_id, messages, run_policy, wants_title, pins = _prepare_run(
        user_key, project_id, attachment_id, message, config
    )
    # Eager admission: a quota/budget denial surfaces as a plain 429 before any
    # streaming begins, and consumes/persists nothing.
    quotas.admit(user_key, **run_policy["admit"])
    execution_id = uuid.uuid4().hex

    marker = content.TAIL_FENCE

    def _hold_split(buf: str) -> tuple[str, str]:
        """Emit-now / keep split: retain the longest trailing suffix of *buf*
        that could still be the start of the tail-fence marker (≤ ~16 chars
        held back at any moment — imperceptible in the live transcript)."""
        for k in range(min(len(marker) - 1, len(buf)), 0, -1):
            if marker.startswith(buf[-k:]):
                return buf[:-k], buf[-k:]
        return buf, ""

    def _events():
        chunks: list[str] = []
        usage_sink: dict = {}
        started = time.monotonic()
        # The typed-envelope handshake (memo dev/37): the execution identity
        # arrives before the first delta so a client can correlate the stream
        # with the record that will land on the transcript.
        yield ("execution", {"executionId": execution_id})
        # Tail withholding (memo dev/39): a candidate terminal curio.v1 block
        # must not flash into the live transcript and then vanish; it is
        # accumulated silently and either becomes a content event or — on a
        # false positive / invalid block — is flushed as ordinary deltas.
        buf = ""  # pass-mode text not yet emitted
        withheld: str | None = None  # not None → holding a candidate tail
        try:
            for delta in stream_chat_completion(
                config,
                messages,
                max_output_tokens=run_policy["max_output_tokens"],
                usage_out=usage_sink,
            ):
                chunks.append(delta)
                if withheld is not None:
                    withheld += delta
                    close = withheld.find("\n```", len(marker))
                    if close != -1 and withheld[close + 4 :].strip():
                        # Closed fence followed by more content: not terminal —
                        # flush the closed block verbatim and rescan the rest.
                        yield ("delta", withheld[: close + 4])
                        buf = withheld[close + 4 :]
                        withheld = None
                    else:
                        continue
                else:
                    buf += delta
                idx = buf.find(marker)
                if idx != -1:
                    if buf[:idx]:
                        yield ("delta", buf[:idx])
                    withheld = buf[idx:]
                    buf = ""
                else:
                    emit, buf = _hold_split(buf)
                    if emit:
                        yield ("delta", emit)
        except Exception as exc:  # provider failure mid-stream
            _record_usage(user_key, usage_sink)
            _persist_exchange(
                user_key,
                project_id,
                session_id,
                attachment_id,
                message,
                f"(error) {exc}",
                error=True,
                execution=_execution_record(execution_id, pins, usage_sink, started, "error"),
            )
            yield ("error", f"agent run failed: {exc}")
            return
        reply = "".join(chunks)
        visible, parts = content.extract_content(reply)
        if withheld is not None and not parts:
            # Invalid or non-terminal tail: fail-open (dev/39 §4.2) — the
            # withheld text is the model's, so it streams after all.
            yield ("delta", withheld)
        elif withheld is None and buf:
            yield ("delta", buf)  # stream ended on a partial fence prefix
        _record_usage(user_key, usage_sink)
        execution = _execution_record(execution_id, pins, usage_sink, started, "ok")
        _persist_exchange(
            user_key,
            project_id,
            session_id,
            attachment_id,
            message,
            visible,
            execution=execution,
            parts=parts,
        )
        # Title before the done frame: the reply text already streamed via
        # deltas, and the client's post-send refresh must see the title.
        if wants_title:
            _generate_conversation_title(user_key, project_id, attachment_id, message, config)
        if parts:
            yield ("content", {"parts": parts})
        yield (
            "done",
            {
                "reply": visible,
                "executionId": execution_id,
                "usage": execution["usage"],
                "content": parts,
            },
        )

    return _events()
