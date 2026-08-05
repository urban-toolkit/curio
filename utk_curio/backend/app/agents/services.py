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
    delegation,
    imports,
    ledger,
    policy,
    pricing,
    project_agents,
    publications,
    quotas,
    sessions,
    storage,
    tools,
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
    """Write a built-in's bytes (manifest + prompt assets) into the user store,
    so an installed agent is self-contained and runs from its own on-disk assets
    rather than the legacy ``llm-prompts/`` dir.

    Heals stale copies (memo dev/44): a built-in store copy that predates a
    roster asset (e.g. the pre-dev/38 missing system preamble) is rewritten to
    the current roster set on the next install/import — idempotent, and never
    touches a non-built-in definition (an owned import deliberately shadowing
    a built-in coord keeps its own bytes)."""
    existing = storage.load_installed_agent_definition(user_key, coord)
    if existing is not None and existing.provenance.trust != "built-in":
        return  # owned/imported shadow — its bytes are authoritative
    spec = builtin.get_builtin_spec(coord)
    if spec is None:
        return
    manifest = builtin.build_builtin_manifest(spec)
    if existing is not None:
        base = storage.agent_definition_dir(user_key, coord)
        declared = manifest["prompts"]
        complete = set(existing.prompts) == set(declared) and all(
            (base / asset["path"]).is_file() for asset in declared.values()
        )
        if complete:
            return  # current copy already matches the roster asset set
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


def list_my_imports(user_key: str, project_id: str | None = None) -> list[dict]:
    """Account "My Imports": each imported coordinate whose definition resolves.

    With *project_id*, ``installedInProject`` is read from the project's
    lockfile — the same single source of truth the Global scope uses (memo
    dev/47; previously hardcoded False, so an installed agent's row could
    show an active Install on this tab)."""
    imported = imports.load_imported_agents(user_key)
    installed: set[str] = set()
    if project_id:
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is not None:
            installed = set(project_agents.project_agents(spec))
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
                installed_in_project=coord in installed,
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


def get_project_agent_defaults(
    user_key: str, project_id: str, coord: str, config: "ProviderConfig | None" = None
) -> dict:
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
    summary = _pricing_summary(config)
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
                # Actual USD settled this window (memo dev/40) — Actual or null.
                "actualSpendTodayUsd": _actual_spend_today(
                    user_key, bool(summary and summary["priced"])
                ),
                "pricing": summary,
            },
            "resources": dict(eff["resources"]),
        },
    }


def update_project_agent_defaults(
    user_key: str,
    project_id: str,
    coord: str,
    revision: object,
    settings: object,
    config: "ProviderConfig | None" = None,
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
    return get_project_agent_defaults(user_key, project_id, coord, config)


def _pricing_summary(config: ProviderConfig | None) -> dict | None:
    """No-secrets pricing view for the Cost screen (memo dev/40): the caller's
    provider/model, whether a deployment price exists, and its effective date.
    ``None`` when no provider config resolves (e.g. keyless guests)."""
    if config is None:
        return None
    snapshot = pricing.price_snapshot(config.api_type, config.model)
    return {
        "provider": config.api_type,
        "model": config.model,
        "priced": snapshot is not None,
        "effectiveDate": snapshot.get("effectiveDate") if snapshot else None,
    }


def _actual_spend_today(user_key: str, priced: bool) -> float | None:
    """Actual USD settled this window — a number once anything real exists to
    show (a price is configured, or priced spend already accrued); ``None``
    otherwise, so the UI never renders a fake $0.00 for unpriced deployments."""
    spend = ledger.aggregates(user_key)["actualSpendUsd"]
    return spend if (priced or spend > 0) else None


def get_account_settings(user_key: str, config: ProviderConfig | None = None) -> dict:
    """The Account-policy scope (memo dev/24): record + effective + ceilings."""
    record = account_settings.read_record(user_key)
    summary = _pricing_summary(config)
    return {
        "revision": record["revision"],
        "settings": record["settings"],
        "effective": policy.effective(record["settings"]),
        "ceilings": policy.deployment_defaults(),
        "usedToday": quotas.runs_used_today(user_key),
        # Actual tokens counted this window (memo dev/37) — never estimated.
        "usageToday": quotas.usage_today(user_key),
        # Actual USD settled this window (memo dev/40) — Actual or null.
        "actualSpendTodayUsd": _actual_spend_today(
            user_key, bool(summary and summary["priced"])
        ),
        "pricing": summary,
    }


def update_account_settings(
    user_key: str, revision: object, settings: object, config: ProviderConfig | None = None
) -> dict:
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
    return get_account_settings(user_key, config)


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
        # The manifest's declared inputs (dev/38) — drives the client-side
        # grounded-context composer (memo dev/44).
        "reads": list(m.inputs_reads) if m else [],
        "intent": record.get("intent") or _resolve_instruction_text(user_key, coord),
        "intentEdited": bool(record.get("intent")),
        # Conversation title (memo dev/25): the custom portion only — the
        # client composes "<name>: <title>" at display time.
        "title": record.get("title") or None,
        "titleEdited": bool(record.get("titleEdited")),
        # Review proposal mirror (memo dev/41) — status card wiring only; the
        # transcript's proposal part remains the display record.
        "activeProposal": _proposal_summary(record.get("activeProposal")),
    }


def _proposal_summary(proposal: object) -> dict | None:
    if not isinstance(proposal, dict):
        return None
    return {
        "proposalId": proposal.get("proposalId"),
        "tool": proposal.get("tool"),
        "nodeId": proposal.get("nodeId"),
        "summary": proposal.get("summary"),
        "status": proposal.get("status"),
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
    # compatibleTargets[].requires (memo dev/50): a node target must match one
    # of the declared template-id suffixes (e.g. "data-loading" accepts any
    # <packageId>/data-loading node). Empty requires = any node — every
    # pre-dev/50 agent behaves identically.
    if kind == "node" and manifest is not None:
        node_target = next(
            (t for t in manifest.compatible_targets if t.kind == "node"), None
        )
        if node_target is not None and node_target.requires:
            target_id = target.get("targetId") if isinstance(target, dict) else None
            nodes = (spec.get("dataflow") or {}).get("nodes") or []
            node = next(
                (n for n in nodes if isinstance(n, dict) and n.get("id") == target_id), None
            )
            node_type = str((node or {}).get("type") or "")
            # Canonical suffix, tolerant of versioned ids and legacy enum names
            # ("pkg/tmpl@1" → "tmpl"; "DATA_LOADING" → "data-loading").
            suffix = node_type.rsplit("/", 1)[-1].split("@", 1)[0].lower().replace("_", "-")
            if suffix not in {r.lower() for r in node_target.requires}:
                raise AgentServiceError(
                    f"this agent attaches to {', '.join(sorted(node_target.requires))} "
                    f"nodes; that node is {node_type or 'untyped'}",
                    400,
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


# ── attachment settings (the Attached-instance scope, memo dev/42) ───────────
def get_attachment_settings(
    user_key: str, project_id: str, attachment_id: str, config: "ProviderConfig | None" = None
) -> dict:
    """The Attached-instance policy scope: the record's tighten-only overrides
    plus the three-layer effective view. ``usedToday`` meters the **binding**
    scope — an attachment-source limit shows this attachment's ledger count,
    a project-source limit the template count, otherwise the account count —
    so the meter always measures what the limit actually counts."""
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    coord = record.get("coord", "")
    m = _resolve_definition(user_key, coord)
    acct = account_settings.read_record(user_key)["settings"]
    project_record = project_agents.agent_defaults(spec).get(coord) or {}
    attachment_settings = record.get("settings") or {}
    eff = policy.effective(acct, project_record.get("settings") or {}, attachment_settings)
    agg = ledger.aggregates(user_key)
    runs = eff["quotas"]["runsPerDay"]
    if runs["source"] == "attachment":
        used = agg["byAttachment"].get(attachment_id, 0)
    elif runs["source"] == "project":
        used = agg["byTemplate"].get(f"{project_id}/{coord}", 0)
    else:
        used = agg["runs"]
    estimate = eff["cost"]["estimatedCostPerRunUsd"]["value"]
    summary = _pricing_summary(config)
    return {
        "attachmentId": attachment_id,
        "coord": coord,
        "name": m.name if m else coord,
        "revision": record.get("revision", 1),
        "settings": attachment_settings,
        "effective": {
            "quotas": {
                "runsPerDay": {**runs, "usedToday": used},
                "usageToday": quotas.usage_today(user_key),
            },
            "cost": {
                **eff["cost"],
                # Estimated spend is account-wide runs × the account estimate,
                # exactly as the project scope reports it (memo dev/24).
                "estimatedSpendTodayUsd": round(agg["runs"] * estimate, 6)
                if estimate is not None
                else None,
                "actualSpendTodayUsd": _actual_spend_today(
                    user_key, bool(summary and summary["priced"])
                ),
                "pricing": summary,
            },
            "resources": dict(eff["resources"]),
        },
    }


def update_attachment_settings(
    user_key: str,
    project_id: str,
    attachment_id: str,
    revision: object,
    settings: object,
    config: "ProviderConfig | None" = None,
) -> dict:
    """PATCH the attachment's tighten-only overrides (memo dev/42): validated
    against the **project-effective** policy, optimistic on the record's
    shared revision (an intent/title edit invalidates a stale settings draft
    — one record, one token), ``{"settings": {}}`` = *Clear overrides*."""
    if not isinstance(revision, int):
        raise AgentServiceError("revision must be an integer", 400)
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    if record.get("revision", 1) != revision:
        raise AgentServiceError(
            f"attachment changed (revision {record.get('revision', 1)}, sent {revision})",
            409,
        )
    coord = record.get("coord", "")
    acct = account_settings.read_record(user_key)["settings"]
    project_record = project_agents.agent_defaults(spec).get(coord) or {}
    parent = policy.effective(acct, project_record.get("settings") or {})
    try:
        cleaned = policy.validate_patch(settings, "attachment", parent)
    except PolicyValidationError as exc:
        raise AgentServiceError(str(exc), 400) from exc
    attachments.set_settings(spec, attachment_id, cleaned)
    projects_storage.write_spec(user_key, project_id, spec)
    return get_attachment_settings(user_key, project_id, attachment_id, config)


# ── review-before-apply (memo dev/41) ────────────────────────────────────────
def apply_proposal(
    user_key: str, project_id: str, attachment_id: str, proposal_id: str
) -> dict:
    """Apply a pending proposal — the ONLY path that executes a mutate tool.

    Explicit, authenticated, revision-safe (`REQ-REVIEW-001`/`DEC-006`): the
    pinned revision basis is re-checked against current state (content digest
    for ``node.content.write``; template availability for ``node.create``);
    drift marks the proposal ``stale`` and returns 409 instead of applying.
    Success executes the domain-owned write under the project's spec write
    path, logs a result-card turn (docs/08 — results are logged as chat
    turns), and consumes no quota (deterministic, no provider work). No
    model/tool/user *text* can reach this path — only this endpoint."""
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    proposal = attachments.get_active_proposal(spec, attachment_id)
    if proposal is None or proposal.get("proposalId") != proposal_id:
        raise AgentServiceError(f"proposal {proposal_id!r} not found", 404)
    status = proposal.get("status")
    if status != "pending":
        raise AgentServiceError(f"this proposal is {status!r} and can no longer be applied", 409)
    session_id = record.get("sessionId")
    tool = proposal.get("tool", "node.content.write")
    if tool == "node.create":
        return _apply_node_create(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "node.content.write":
        return _apply_node_content_write(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "project.install":
        return _apply_project_install(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "node.template.create":
        return _apply_node_template_create(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "dataset.install":
        return _apply_dataset_install(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    raise AgentServiceError(f"no apply flow exists for tool {tool!r}", 409)


def _mark_stale(
    user_key: str,
    project_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
    message: str,
) -> AgentServiceError:
    """Shared apply-drift path: proposal → ``stale`` in both homes, 409 out."""
    proposal["status"] = "stale"
    projects_storage.write_spec(user_key, project_id, spec)
    if isinstance(session_id, str):
        sessions.update_proposal_status(user_key, project_id, session_id, proposal_id, "stale")
    return AgentServiceError(message, 409)


def _log_applied_turn(
    user_key: str,
    project_id: str,
    session_id: object,
    attachment_id: str,
    proposal_id: str,
    text: str,
    title: str,
    lines: list[str],
) -> None:
    """Mark applied + append the result-card turn (mutation_applied, dev/03:344)."""
    if not isinstance(session_id, str):
        return
    sessions.update_proposal_status(user_key, project_id, session_id, proposal_id, "applied")
    sessions.append_turns(
        user_key,
        project_id,
        session_id,
        attachment_id,
        [
            sessions.make_turn(
                "agent",
                text,
                content=[{"type": "card", "kind": "result", "title": title, "lines": lines}],
            )
        ],
    )


def _apply_node_content_write(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/41 apply: one node's content, digest-checked, nothing else."""
    import hashlib

    node_id = proposal.get("nodeId")
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    current = (node.get("content") if node is not None else None) or ""
    basis = hashlib.sha256(current.encode("utf-8")).hexdigest()
    if node is None or basis != proposal.get("contentSha256"):
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            "the node changed since this was proposed — ask the agent to propose again",
        )
    # The domain-owned mutation (ADR-AG-007): one node's content, nothing else.
    node["content"] = proposal.get("content", "")
    proposal["status"] = "applied"
    projects_storage.write_spec(user_key, project_id, spec)
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: node content updated ({node_id}).",
        "Applied: node content updated",
        [f"node {node_id}", f"proposal {proposal_id[:8]}"],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        # The frontend canvas bridge (dev/48 §3.3) applies this to the LIVE
        # node too, so the next canvas save can't clobber the mutation.
        "appliedContent": {"nodeId": node_id, "content": proposal.get("content", "")},
    }


_TEMPLATE_ENGINES = ("python", "javascript")


def _mint_node_template_create(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/48 §3.2b creation fallback: a reviewed proposal for a NEW
    custom node type. The runtime cannot judge adequacy — the review card is
    the adequacy gate, so a written justification is mandatory, and a label
    that collides with an available template is refused as reuse territory."""
    from utk_curio.backend.app.packages import services as packages_services

    params = req.get("params") or {}
    justification = params.get("justification")
    if not isinstance(justification, str) or not justification.strip():
        return (
            "refused",
            "the review needs your reasoning — state which existing templates you "
            "considered and why they don't fit (params.justification)",
            None,
        )
    template = params.get("template")
    if not isinstance(template, dict):
        return "refused", "params.template must be an object", None
    label = str(template.get("label") or "").strip()
    slug = packages_services.template_slug(label)
    if not slug:
        return "refused", "template.label must be a non-empty name", None
    engine = template.get("engine") or "python"
    if engine not in _TEMPLATE_ENGINES:
        return "refused", "template.engine must be 'python' or 'javascript'", None
    code = template.get("content")
    if not isinstance(code, str) or not code.strip():
        return "refused", "template.content must be a non-empty string", None
    if len(code) > content.PROPOSAL_CONTENT_MAX_CHARS:
        return "refused", "template.content exceeds the proposal size bound", None
    try:
        existing = packages_services.available_templates(user_key, project_id)
    except Exception as exc:
        return "refused", f"the node template registry is unavailable: {exc}", None
    collision = next(
        (
            t
            for t in existing
            if t["id"].rsplit("/", 1)[-1] == slug
            or t["label"].strip().lower() == label.lower()
        ),
        None,
    )
    if collision is not None:
        return (
            "refused",
            f"a template like this already exists ({collision['id']}) — that is reuse "
            "territory: propose a node.create with it instead",
            None,
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    proposal_id = uuid.uuid4().hex
    summary = f"Create a new custom node type · {label}"
    description = str(template.get("description") or "").strip()
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="node.template.create",
        summary=summary,
        preview=code,
        pins={"templateSlug": slug},
    )
    # The justification + definition ride the part for the review card —
    # the justification is what the user judges (memo dev/48 §3.2b).
    part["justification"] = justification.strip()
    part["template"] = {"label": label, "engine": engine, "description": description}
    _store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "node.template.create",
            "justification": justification.strip(),
            "template": {
                "label": label,
                "engine": engine,
                "description": description,
                "content": code,
            },
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return (
        "proposed",
        f"proposal {proposal_id} created for a new custom node type {label!r}; it "
        "awaits the user's explicit review — do NOT assume the type or node exists",
        part,
    )


def _apply_node_template_create(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/48 §3.2b apply: ONE explicit review covering both stated
    effects — register the template through the EXISTING package factory
    (atomic staging; store + project lockfile), then insert the first node.
    Template first, node only on success: a factory failure 409s with the
    verbatim error and nothing is half-registered."""
    from utk_curio.backend.app.packages import services as packages_services

    template = proposal.get("template") or {}
    try:
        created_template = packages_services.create_template_package(
            user_key, project_id, template
        )
    except packages_services.PackageServiceError as exc:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the node type could not be registered: {exc}",
        ) from exc
    # The factory path wrote the spec (lockfile); re-read before inserting the
    # node so we don't clobber the new package entry.
    spec = _read_spec_or_404(user_key, project_id)
    proposal = attachments.get_active_proposal(spec, attachment_id) or proposal
    created = _insert_node(spec, created_template["id"], template.get("content", ""), None)
    proposal["status"] = "applied"
    projects_storage.write_spec(user_key, project_id, spec)
    label = created_template["label"]
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: node type registered and node created ({created['id']}).",
        "Applied: custom node type created",
        [
            f"{label} · {created_template['id']}",
            f"node {created['id']}",
            f"proposal {proposal_id[:8]}",
        ],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "createdTemplate": created_template,
        "createdNode": dict(created),
    }


def _graph_shape_digest(spec: dict) -> str:
    """The whole-graph revision basis for plan proposals (dev/52): sha256 of
    the saved dataflow's sorted node-id and edge-id sets. Content edits do
    NOT change it — deliberate: they don't invalidate an additive plan."""
    import hashlib
    import json as _json

    dataflow = spec.get("dataflow") or {}
    node_ids = sorted(
        str(n.get("id")) for n in (dataflow.get("nodes") or []) if isinstance(n, dict)
    )
    edge_ids = sorted(
        str(e.get("id", f"{e.get('source')}->{e.get('target')}"))
        for e in (dataflow.get("edges") or [])
        if isinstance(e, dict)
    )
    basis = _json.dumps([node_ids, edge_ids])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _mint_dataflow_plan(
    user_key: str, project_id: str, loop_ctx: dict, plan: dict
) -> tuple[str, str, dict | None]:
    """Mint the dev/52 plan proposal from a validated ``dataflowPlan`` part.

    Reuse-first exactly as dev/48: every nodeType must be an available
    template (authorable when the plan carries content for it). Pins the
    whole-graph shape digest; the apply endpoint re-checks it. Returns
    ``(status, user_facing_error, proposal_part | None)``."""
    from utk_curio.backend.app.packages import services as packages_services

    session_id = loop_ctx.get("session_id")
    if not isinstance(session_id, str):
        return "refused", "proposals need a persistent conversation", None
    try:
        available = {t["id"]: t for t in packages_services.available_templates(user_key, project_id)}
    except Exception as exc:
        return "refused", f"the node template registry is unavailable: {exc}", None
    for node in plan["nodes"]:
        entry = available.get(node["nodeType"])
        if entry is None:
            return (
                "refused",
                f"plan node {node['ref']!r} uses {node['nodeType']!r}, which is not an "
                "available template for this project",
                None,
            )
        if node.get("content") and not entry.get("authorable"):
            return (
                "refused",
                f"plan node {node['ref']!r} carries content but template "
                f"{node['nodeType']!r} does not hold authored content",
                None,
            )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    digest = _graph_shape_digest(spec)
    proposal_id = uuid.uuid4().hex
    n_nodes, n_edges = len(plan["nodes"]), len(plan["edges"])
    summary = f"Apply plan · {n_nodes} nodes, {n_edges} edges"
    preview = "\n".join(
        f"{node['title']} · {node['nodeType']} — {node['intent']}" for node in plan["nodes"]
    )
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="dataflow.plan.write",
        summary=summary,
        preview=preview,
        pins={"baseGraphDigest": digest},
    )
    # The display copy for the review card (bounded upstream by the grammar).
    part["plan"] = {
        "goal": plan["goal"],
        **({"templateId": plan["templateId"]} if plan.get("templateId") else {}),
        "nodes": [
            {"ref": n["ref"], "nodeType": n["nodeType"], "title": n["title"], "intent": n["intent"]}
            for n in plan["nodes"]
        ],
        "edgeCount": n_edges,
    }
    # The builder session (DR-2) transitions on the SAME spec write: the
    # attachment record is rule-9 share-stripped and save-preserved already.
    record = attachments.get_attachment(spec, loop_ctx["attachment_id"])
    if record is not None:
        session = record.setdefault("builderSession", {})
        session["phase"] = "plan_review"
        session["planProposalId"] = proposal_id
    _store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "dataflow.plan.write",
            "plan": plan,
            "baseGraphDigest": digest,
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return "proposed", "", part


def _maybe_mint_plan(
    user_key: str, project_id: str, loop_ctx: dict, parts: list, minted: list
) -> list:
    """Post-loop hook (dev/52): a validated ``dataflowPlan`` part on the final
    reply becomes the plan proposal in one step — the runtime mints, the
    model never requests. Ungranted plan parts pass through untouched
    (informational; no mutation path exists for them). A mint refusal
    becomes a visible error card — the loop has ended, so there is no round
    to feed it back to."""
    plan_part = next((p for p in parts if p.get("type") == "dataflowPlan"), None)
    if plan_part is None or "dataflow.plan.write" not in loop_ctx.get("granted", []):
        return parts
    remaining = [p for p in parts if p is not plan_part]
    status, error_text, part = _mint_dataflow_plan(user_key, project_id, loop_ctx, plan_part)
    if part is not None:
        minted.append(part)
        return remaining
    remaining.append(
        {
            "type": "card",
            "kind": "error",
            "title": "Plan not proposable",
            "lines": [error_text[:300]],
        }
    )
    return remaining


def _resolve_catalog_dataset(project_id: str, dataset_id: object) -> tuple[dict | None, str]:
    """Resolve a dataset id against the project's Data Catalog (dev/50 —
    the datasets domain is the single truth; `ADR-AG-007`). Returns
    ``(item | None, error_text)``. The acting user rides the request context
    (the datasets service is user-object keyed)."""
    from flask import g

    from utk_curio.backend.app.datasets.application.catalog_service import (
        DatasetCatalogService,
    )
    from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

    if not isinstance(dataset_id, str) or not dataset_id.strip():
        return None, "params.datasetId must be a non-empty dataset id string"
    try:
        item = DatasetCatalogService(getattr(g, "user", None)).get_dataset(
            dataset_id.strip(), dataflow_id=project_id
        )
    except DatasetCatalogError:
        return None, (
            f"dataset {dataset_id!r} is not in this project's Data Catalog — "
            "propose only ids from catalog.search results"
        )
    except Exception as exc:  # a broken catalog is data, not a run error
        return None, f"the Data Catalog is unavailable: {exc}"
    return item, ""


def _mint_dataset_install(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/50 catalog-lane mutation: propose installing ONE catalog
    dataset through the existing dataset-only install flow. An
    already-installed dataset refuses at mint with the existing state —
    honest chat instead of a dead proposal (docs/06 idempotence)."""
    params = req.get("params") or {}
    item, err = _resolve_catalog_dataset(project_id, params.get("datasetId"))
    if item is None:
        return "refused", err, None
    if item.get("installed"):
        return (
            "refused",
            f"dataset {item.get('title')!r} is already installed in this project — "
            "tell the user instead of proposing",
            None,
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    dataset_id = str(params.get("datasetId")).strip()
    name = str(item.get("title") or dataset_id)
    proposal_id = uuid.uuid4().hex
    summary = f"Install dataset · {name}"
    preview_bits = [name]
    if item.get("format"):
        preview_bits.append(str(item["format"]))
    if item.get("origin"):
        preview_bits.append(str(item["origin"]))
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="dataset.install",
        summary=summary,
        preview=" · ".join(preview_bits),
        pins={"datasetId": dataset_id},
    )
    _store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "dataset.install",
            "datasetId": dataset_id,
            "datasetName": name,
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return (
        "proposed",
        f"proposal {proposal_id} created to install dataset {name!r}; it awaits the "
        "user's explicit review — do NOT assume it was installed",
        part,
    )


def _apply_dataset_install(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/50 apply: the EXISTING dataset-only install flow (duplicate
    collapse, authorization, OSM groups — all the domain service's own
    semantics). A dataset gone from the catalog between mint and apply is
    the drift analogue: 409 + ``stale``. No agent is ever installed here."""
    from flask import g

    from utk_curio.backend.app.datasets.application.catalog_service import (
        DatasetCatalogService,
    )

    dataset_id = proposal.get("datasetId", "")
    item, err = _resolve_catalog_dataset(project_id, dataset_id)
    if item is None:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the dataset is no longer available ({err}) — ask the agent to search again",
        )
    try:
        DatasetCatalogService(getattr(g, "user", None)).install_dataset(
            project_id, dataset_id
        )
    except Exception as exc:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the dataset could not be installed: {exc}",
        ) from exc
    # The install wrote the spec (dataset refs); re-read so the proposal
    # mirror update below does not clobber the new entries.
    spec = _read_spec_or_404(user_key, project_id)
    proposal = attachments.get_active_proposal(spec, attachment_id) or proposal
    proposal["status"] = "applied"
    projects_storage.write_spec(user_key, project_id, spec)
    name = str(item.get("title") or dataset_id)
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: dataset installed ({name}).",
        "Applied: dataset installed",
        [name, dataset_id, f"proposal {proposal_id[:8]}"],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "installedDataset": {"id": dataset_id, "name": name},
    }


def _apply_project_install(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/48 missing-specialist apply: the reviewed ``Install in
    project`` (`REQ-ORCH-001`). Reuses the existing install service — one
    project template, nothing imported/attached/run/published/granted.
    Already-installed re-applies are idempotent success, not an error."""
    coord = proposal.get("coord", "")
    already = coord in set(project_agents.project_agents(spec))
    if not already:
        try:
            # The existing reviewed-install service (spec re-read + written
            # inside; our in-hand spec is only used for the mirror below).
            install_in_project(user_key, project_id, coord)
        except AgentServiceError as exc:
            raise _mark_stale(
                user_key, project_id, proposal_id, spec, proposal, session_id,
                f"the install could not be applied: {exc}",
            ) from exc
        # The install wrote the spec; re-read so the mirror update below
        # does not clobber the new template entry.
        spec = _read_spec_or_404(user_key, project_id)
        proposal = attachments.get_active_proposal(spec, attachment_id) or proposal
    proposal["status"] = "applied"
    projects_storage.write_spec(user_key, project_id, spec)
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: {coord} installed in this project.",
        "Applied: agent installed",
        [coord, f"proposal {proposal_id[:8]}"],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "installedCoord": coord,
    }


# Placement for server-minted nodes (dev/48): right of the current extent,
# aligned with the rightmost node's row. Offsets match typical node width.
_NODE_PLACEMENT_X_OFFSET = 420
_NODE_PLACEMENT_DEFAULT = (80.0, 80.0)


def _insert_node(spec: dict, node_type: str, node_content: str, goal: str | None) -> dict:
    """Append one server-minted node to the spec's dataflow (dev/48): fresh
    uuid id (collision-impossible, never from any param), placed right of the
    current node extent. The caller writes the spec."""
    dataflow = spec.setdefault("dataflow", {})
    nodes = dataflow.setdefault("nodes", [])
    xs = [
        (n.get("x"), n.get("y"))
        for n in nodes
        if isinstance(n, dict) and isinstance(n.get("x"), (int, float))
    ]
    if xs:
        max_x, at_y = max(xs, key=lambda p: p[0])
        x = float(max_x) + _NODE_PLACEMENT_X_OFFSET
        y = float(at_y) if isinstance(at_y, (int, float)) else _NODE_PLACEMENT_DEFAULT[1]
    else:
        x, y = _NODE_PLACEMENT_DEFAULT
    created = {"id": str(uuid.uuid4()), "type": node_type, "content": node_content, "x": x, "y": y}
    if goal:
        created["goal"] = goal
    nodes.append(created)
    return created


def _apply_node_create(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/48 apply: insert ONE new node of a re-validated template.

    The node id is server-minted HERE (collision-impossible, never from any
    param); the template is re-validated against the packages registry — a
    package uninstalled between mint and apply is the creation analogue of
    dev/41's digest drift (409 + ``stale``)."""
    node_type = proposal.get("nodeType")
    entry, err = _available_template(user_key, project_id, node_type)
    if entry is None:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the node type is no longer available ({err}) — ask the agent to propose again",
        )
    created = _insert_node(spec, node_type, proposal.get("content", ""), proposal.get("goal"))
    proposal["status"] = "applied"
    projects_storage.write_spec(user_key, project_id, spec)
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: node created ({created['id']}).",
        "Applied: node created",
        [f"{entry['label']} · {node_type}", f"node {created['id']}", f"proposal {proposal_id[:8]}"],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        # Consumed by the frontend canvas bridge (dev/48 §3.3) — the apply
        # response is the only carrier of the created node.
        "createdNode": dict(created),
    }


def dismiss_proposal(
    user_key: str, project_id: str, attachment_id: str, proposal_id: str
) -> dict:
    """Dismiss a pending proposal (keeps its outcome visible on the card)."""
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    proposal = attachments.get_active_proposal(spec, attachment_id)
    if proposal is None or proposal.get("proposalId") != proposal_id:
        raise AgentServiceError(f"proposal {proposal_id!r} not found", 404)
    if proposal.get("status") != "pending":
        raise AgentServiceError(
            f"this proposal is {proposal.get('status')!r} and can no longer be dismissed", 409
        )
    proposal["status"] = "dismissed"
    projects_storage.write_spec(user_key, project_id, spec)
    session_id = record.get("sessionId")
    if isinstance(session_id, str):
        sessions.update_proposal_status(
            user_key, project_id, session_id, proposal_id, "dismissed"
        )
    return {"attachmentId": attachment_id, "proposalId": proposal_id, "status": "dismissed"}


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
        # it writes no execution record and holds no reservation, but its
        # tokens still cost — the ledger counts them (dev/40).
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
        ledger.record_housekeeping_usage(
            user_key,
            usage_sink,
            price=pricing.price_snapshot(config.api_type, config.model),
            note="title-call",
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


def _run_policy(
    user_key: str,
    project_id: str,
    coord: str,
    spec: dict,
    attachment_record: dict | None = None,
) -> dict:
    """Admission + dispatch inputs from the effective policy (memos dev/24/42).

    ``template_limit``/``attachment_limit`` apply only when their scope is the
    tightest source; the account counter is gated at the account-effective
    value. The attachment key is always recorded (ledger attribution)."""
    acct = account_settings.read_record(user_key)["settings"]
    record = project_agents.agent_defaults(spec).get(coord) or {}
    attachment_settings = (attachment_record or {}).get("settings") or {}
    acc_eff = policy.effective(acct)
    full_eff = policy.effective(acct, record.get("settings") or {}, attachment_settings)
    runs = full_eff["quotas"]["runsPerDay"]
    attachment_id = (attachment_record or {}).get("attachmentId")
    return {
        "admit": {
            "account_limit": acc_eff["quotas"]["runsPerDay"]["value"],
            "template_key": f"{project_id}/{coord}",
            "template_limit": runs["value"] if runs["source"] == "project" else None,
            "attachment_key": attachment_id if isinstance(attachment_id, str) else None,
            "attachment_limit": runs["value"] if runs["source"] == "attachment" else None,
            "daily_budget_usd": full_eff["cost"]["dailyBudgetUsd"]["value"],
            "estimated_cost_per_run_usd": full_eff["cost"]["estimatedCostPerRunUsd"]["value"],
        },
        "max_output_tokens": full_eff["resources"]["maxOutputTokens"]["value"],
        # Flat effective-policy snapshot pinned on the execution record
        # (DEC-031): what was admitted, not where each value came from —
        # instance tightening flows in with zero pins-code changes (dev/42).
        "policy_pins": {
            "runsPerDay": runs["value"],
            "maxOutputTokens": full_eff["resources"]["maxOutputTokens"]["value"],
            "dailyBudgetUsd": full_eff["cost"]["dailyBudgetUsd"]["value"],
            "estimatedCostPerRunUsd": full_eff["cost"]["estimatedCostPerRunUsd"]["value"],
        },
    }


def _prompt_digest(m: AgentManifest | None) -> str | None:
    """The resolved definition's instruction-prompt sha256 (a DEC-031 pin).

    Read from the manifest asset, not recomputed — the digest identifies the
    definition bytes that were dispatched. ``None`` when the manifest carries
    no digest (tolerated; pre-upload-import definitions may be unstamped)."""
    asset = m.prompts.get("instruction") if m is not None else None
    return asset.sha256 if asset is not None else None


def _execution_record(
    execution_id: str,
    pins: dict,
    usage: dict,
    started: float,
    status: str,
    tool_calls: list | None = None,
    cost_usd: float | None = None,
    delegations: list | None = None,
) -> dict:
    """Assemble the per-run execution record persisted on the agent turn
    (memo dev/37). ``usage`` is Actual counts or ``None``, never estimated
    (memo dev/11) — summed across loop rounds when tools ran (dev/41), which
    is also when ``toolCalls`` (additive) records what executed. ``costUsd``
    (dev/40) is the ledger settlement's Actual USD — null unless a deployment
    price existed for the run. ``delegations`` (additive, dev/48) lists the
    run's child execution records — each with its own pins, usage, costUsd,
    and ``parentExecutionId`` back-link."""
    record = {
        "executionId": execution_id,
        "pins": pins,
        "usage": dict(usage) if usage else None,
        "costUsd": cost_usd,
        "durationMs": int((time.monotonic() - started) * 1000),
        "status": status,
    }
    if tool_calls:
        record["toolCalls"] = list(tool_calls)
    if delegations:
        record["delegations"] = list(delegations)
    return record


def _add_usage(total: dict, sink: dict) -> None:
    """Sum one provider call's sink into the run's usage total (dev/41 — a
    tool loop makes several calls; the run settles their sum, dev/40)."""
    for key in ("inputTokens", "outputTokens"):
        if isinstance(sink.get(key), int):
            total[key] = total.get(key, 0) + sink[key]


def _prepare_run(
    user_key: str,
    project_id: str,
    attachment_id: str,
    message: str,
    config: ProviderConfig,
    run_context: str | None = None,
) -> tuple[str, str | None, list, dict, bool, dict]:
    """Shared run/stream setup: resolve the attachment, its instruction (intent
    override → prompt source, dev/19), the provider messages including the
    bounded session context (dev/20), and the effective run policy (dev/24).
    Returns ``(coord, session_id, messages, run_policy, wants_title, pins,
    loop_ctx)``; ``session_id`` is None for a record without one (stateless
    fallback), ``wants_title`` is True when this message is the conversation's
    first — an untitled, never-manually-renamed attachment with no prior user
    turn — so a title should be auto-generated after the reply (memo dev/25),
    ``pins`` are the DEC-031 reproducibility pins resolved from what actually
    dispatches (memo dev/37): coord, prompt digest, intent-edited flag,
    provider/model, granted tools (dev/39), and the effective-policy snapshot
    (no secrets), and ``loop_ctx`` carries what the dev/41 tool loop needs
    (granted ids + the attachment target). A required manifest tool that
    resolves no grant refuses the run here — validation stage, before
    admission, so it consumes no quota."""
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    coord = record.get("coord", "")
    manifest = _resolve_definition(user_key, coord)
    requested_tools = manifest.tools if manifest is not None else []
    missing = tools.missing_required(requested_tools)
    if missing:
        raise AgentServiceError(
            f"required tool(s) not available for this agent: {', '.join(sorted(missing))}", 422
        )
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
    # Structured-tail protocol (memos dev/39/41): the runtime-owned
    # instruction composes AFTER the preamble + intent, so an edited intent
    # can neither strip nor spoof it. Grant-less runs keep the T2 instruction
    # byte-identical; granted runs get the toolRequest paragraph.
    granted = tools.resolve_grants(requested_tools)
    system_content = (
        f"{system_content}\n\n{content.tail_instruction(tools.grant_descriptions(granted))}"
    )
    # Reuse-first (dev/48; plans too, dev/52): a node.create or
    # dataflow.plan.write grant carries the live template roster, composed
    # fresh per run from the packages registry — the prompt bytes never bake
    # in template ids, and the model is never left to guess.
    if "node.create" in granted or "dataflow.plan.write" in granted:
        templates_block = _available_templates_block(user_key, project_id)
        if templates_block:
            system_content = f"{system_content}\n\n{templates_block}"
    # Delegation (dev/48, DEC-046): offered only when the manifest names
    # delegates that resolve to visible definitions — server-resolved, never
    # the manifest's raw list.
    if manifest is not None and manifest.delegates_to:
        entries = delegation.visible_capability_entries(user_key, manifest)
        if entries:
            system_content = f"{system_content}\n\n{content.delegation_instruction(entries)}"
    session_id = record.get("sessionId")
    if not isinstance(session_id, str):
        session_id = None
    prior = sessions.read_turns(user_key, project_id, session_id) if session_id else []
    # Ephemeral grounded context (memo dev/44): the client-composed live-canvas
    # inputs ride ONE provider message per send — recomputed fresh each time
    # (never stale), never persisted (the transcript stays what the user saw),
    # never replayed from history. Absent → byte-identical to before.
    context_block = _bounded_context(run_context)
    messages = [
        {"role": "system", "content": system_content},
        *sessions.context_messages(prior),
        *(
            [{"role": "user", "content": f"{_CONTEXT_FRAME}{context_block}"}]
            if context_block
            else []
        ),
        {"role": "user", "content": message},
    ]
    wants_title = (
        not record.get("title")
        and not record.get("titleEdited")
        and not any(t.get("role") == "user" for t in prior)
    )
    run_policy = _run_policy(user_key, project_id, coord, spec, record)
    pins = {
        "coord": coord,
        "promptSha256": _prompt_digest(manifest),
        "intentEdited": bool(record.get("intent")),
        "provider": config.api_type,
        "model": config.model,
        # Granted tool ids (dev/39): requested ∩ registry ∩ policy.
        "tools": granted,
        "policy": run_policy["policy_pins"],
    }
    loop_ctx = {
        "granted": granted,
        "target": record.get("target"),
        "attachment_id": attachment_id,
        "session_id": session_id,
        # Delegation context (dev/48): the parent's identity + manifest for
        # delegatesTo resolution inside the loop.
        "coord": coord,
        "manifest": manifest,
    }
    return coord, session_id, messages, run_policy, wants_title, pins, loop_ctx


# Bounds for the run-time template roster (dev/48): plenty for every real
# project, small enough to never crowd the context.
_TEMPLATES_BLOCK_MAX_ENTRIES = 60
_TEMPLATES_BLOCK_DESC_CHARS = 140


def _available_templates_block(user_key: str, project_id: str) -> str | None:
    """The grant-aware "Available node templates" listing appended to a
    node.create run's system content — authorable templates only, composed
    from the packages-domain helper so it is never stale (memo dev/48)."""
    from utk_curio.backend.app.packages import services as packages_services

    try:
        templates = packages_services.available_templates(user_key, project_id)
    except Exception:  # a broken registry degrades to no listing, not a 500
        return None
    entries = [t for t in templates if t.get("authorable")][:_TEMPLATES_BLOCK_MAX_ENTRIES]
    if not entries:
        return None
    lines = []
    for t in entries:
        desc = (t.get("description") or "")[:_TEMPLATES_BLOCK_DESC_CHARS]
        suffix = f": {desc}" if desc else ""
        lines.append(f"- {t['id']} — {t['label']}{suffix}")
    return (
        "Available node templates (a node.create nodeType MUST be exactly one "
        "of these ids):\n" + "\n".join(lines)
    )


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


# How many tool executions one run may make (memo dev/41): total provider
# calls per run ≤ MAX_TOOL_ROUNDS + 1. A runtime constant until someone needs
# to tune it (REQ-QUOTA-001 notes tool quotas as the eventual policy home).
MAX_TOOL_ROUNDS = 2

# Ephemeral run context (memo dev/44): the client-composed grounded inputs
# (live Trill, node id, subtask, …) framed as one provider message per send.
# Bounded server-side; legacy call sites sent unbounded payloads, this names
# the limit and truncates visibly instead of failing.
CONTEXT_MAX_CHARS = 120_000
_CONTEXT_TRUNCATION_MARKER = "\n…[truncated: context exceeded the run-context bound]"
_CONTEXT_FRAME = "[attachment context — current canvas state]\n"


def _bounded_context(run_context: str | None) -> str | None:
    if not isinstance(run_context, str) or not run_context.strip():
        return None
    if len(run_context) <= CONTEXT_MAX_CHARS:
        return run_context
    return run_context[:CONTEXT_MAX_CHARS] + _CONTEXT_TRUNCATION_MARKER


def _mint_proposal(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """Turn a granted mutate toolRequest into a review proposal (memos dev/41,
    dev/48 — a per-tool dispatch over one shared persistence path).

    The loop never executes a mutation (`DEC-006`): validation failures come
    back as tool results the model recovers from; success mints a ``proposal``
    part (persisted with the turn) plus the attachment's ``activeProposal``
    mirror, carrying the tool's revision-safety basis the apply endpoint
    re-checks (`REQ-REVIEW-001`).
    Returns ``(status, text_for_model, proposal_part | None)``."""
    session_id = loop_ctx.get("session_id")
    if not isinstance(session_id, str):
        return "refused", "proposals need a persistent conversation; this attachment has none", None
    tool = req.get("tool")
    if tool == "node.content.write":
        return _mint_node_content_write(user_key, project_id, loop_ctx, req)
    if tool == "node.create":
        return _mint_node_create(user_key, project_id, loop_ctx, req)
    if tool == "node.template.create":
        return _mint_node_template_create(user_key, project_id, loop_ctx, req)
    if tool == "dataset.install":
        return _mint_dataset_install(user_key, project_id, loop_ctx, req)
    return "refused", f"no proposal flow exists for tool {tool!r}", None


def _store_proposal(
    user_key: str,
    project_id: str,
    spec: dict,
    loop_ctx: dict,
    proposal: dict,
    part: dict,
) -> None:
    """Shared proposal persistence (dev/41 semantics, unchanged): newest
    supersedes a still-pending earlier proposal in both places it lives
    (mirror + its transcript part), then the mirror + spec are written."""
    attachment_id = loop_ctx["attachment_id"]
    session_id = loop_ctx["session_id"]
    previous = attachments.get_active_proposal(spec, attachment_id)
    if previous is not None and previous.get("status") == "pending":
        sessions.update_proposal_status(
            user_key, project_id, session_id, previous.get("proposalId", ""), "superseded"
        )
    attachments.set_active_proposal(spec, attachment_id, proposal)
    projects_storage.write_spec(user_key, project_id, spec)


def _mint_node_content_write(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/41 mutation: replace one existing node's content, digest-pinned."""
    import hashlib

    params = req.get("params") or {}
    node_id = params.get("nodeId")
    if not isinstance(node_id, str) or not node_id:
        target = loop_ctx.get("target")
        node_id = (
            target.get("targetId")
            if isinstance(target, dict) and target.get("kind") == "node"
            else None
        )
    if not node_id:
        return "refused", "no nodeId given and this agent is not attached to a node", None
    proposed = params.get("content")
    if not isinstance(proposed, str) or not proposed.strip():
        return "refused", "params.content must be a non-empty string", None
    if len(proposed) > content.PROPOSAL_CONTENT_MAX_CHARS:
        return "refused", "params.content exceeds the proposal size bound", None
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    if node is None:
        return "refused", f"node {node_id!r} not found in the saved spec", None
    basis = hashlib.sha256((node.get("content") or "").encode("utf-8")).hexdigest()
    proposal_id = uuid.uuid4().hex
    summary = f"Replace the content of node {node_id!r}"
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="node.content.write",
        summary=summary,
        preview=proposed,
        pins={"nodeId": node_id, "contentSha256": basis},
    )
    _store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "node.content.write",
            "nodeId": node_id,
            "content": proposed,
            "contentSha256": basis,
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return (
        "proposed",
        f"proposal {proposal_id} created for node {node_id!r}; it awaits the user's "
        "explicit review — do NOT assume it was applied",
        part,
    )


def _available_template(user_key: str, project_id: str, node_type: object) -> tuple[dict | None, str]:
    """Resolve ``node_type`` against the packages-domain availability helper
    (dev/48 reuse-first: the agents module owns no template knowledge).
    Returns ``(entry | None, error_text)``."""
    from utk_curio.backend.app.packages import services as packages_services

    if not isinstance(node_type, str) or not node_type:
        return None, "params.nodeType must be a non-empty template id string"
    try:
        templates = packages_services.available_templates(user_key, project_id)
    except Exception as exc:  # unavailable registry is data, not a run error
        return None, f"the node template registry is unavailable: {exc}"
    entry = next((t for t in templates if t["id"] == node_type), None)
    if entry is None:
        return None, (
            f"nodeType {node_type!r} is not an available template for this project — "
            "choose an id from the Available node templates list"
        )
    if not entry.get("authorable"):
        return None, (
            f"template {node_type!r} does not hold authored content — choose an "
            "authorable template from the Available node templates list"
        )
    return entry, ""


def _mint_node_create(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/48 graph-shape mutation: propose ONE new node of an existing,
    project-available template. No digest pin — the node id is server-minted
    at apply (there is no target whose drift can corrupt); the template is
    re-validated at apply instead (`REQ-REVIEW-001` stays structural)."""
    params = req.get("params") or {}
    # Any model-supplied "id" is ignored: ids are server-minted at apply only.
    entry, err = _available_template(user_key, project_id, params.get("nodeType"))
    if entry is None:
        return "refused", err, None
    proposed = params.get("content")
    if not isinstance(proposed, str) or not proposed.strip():
        return "refused", "params.content must be a non-empty string", None
    if len(proposed) > content.PROPOSAL_CONTENT_MAX_CHARS:
        return "refused", "params.content exceeds the proposal size bound", None
    goal = params.get("goal")
    goal = goal.strip() if isinstance(goal, str) and goal.strip() else None
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    proposal_id = uuid.uuid4().hex
    summary = f"Create a new {entry['label']} node"
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="node.create",
        summary=summary,
        preview=proposed,
        pins={"nodeType": entry["id"]},
    )
    proposal = {
        "proposalId": proposal_id,
        "tool": "node.create",
        "nodeType": entry["id"],
        "content": proposed,
        "summary": summary,
        "status": "pending",
    }
    if goal:
        proposal["goal"] = goal
    _store_proposal(user_key, project_id, spec, loop_ctx, proposal, part)
    return (
        "proposed",
        f"proposal {proposal_id} created for a new {entry['label']} node; it awaits "
        "the user's explicit review — do NOT assume it was applied",
        part,
    )


def _execute_tool_request(
    user_key: str, project_id: str, loop_ctx: dict, req: dict, tool_calls: list, minted: list
) -> tuple[str, str]:
    """Handle one model toolRequest inside the loop (memo dev/41).

    Only granted read contracts execute; a granted mutate contract mints a
    review proposal (never executes — `DEC-006`); everything else resolves to
    a synthetic result the model can recover from — loudly to the model,
    invisibly to the user, never a run error. Appends to ``tool_calls`` (the
    execution record's tool history) and ``minted`` (proposal parts for the
    persisted turn)."""
    tool_id = req.get("tool", "")
    started = time.monotonic()
    if tool_id not in loop_ctx["granted"]:
        status, text = "refused", f"tool {tool_id!r} is not granted for this run"
    else:
        contract = tools.REGISTRY.get(tool_id)
        if contract is None:
            status, text = "refused", f"tool {tool_id!r} is not available"
        elif contract.effect == "mutate":
            status, text, part = _mint_proposal(user_key, project_id, loop_ctx, req)
            if part is not None:
                minted.append(part)
        else:
            status, text = tools.execute_read_tool(
                tool_id,
                user_key=user_key,
                project_id=project_id,
                target=loop_ctx.get("target"),
                params=req.get("params") or {},
            )
    tool_calls.append(
        {
            "tool": tool_id,
            "status": status,
            "durationMs": int((time.monotonic() - started) * 1000),
        }
    )
    return status, text


def _tool_result_message(tool_id: str, status: str, text: str, *, final: bool) -> dict:
    """The tool result fed back as provider context (untrusted data, framed)."""
    suffix = (
        "\nNo further tool calls are available this turn — answer with what you have."
        if final
        else ""
    )
    return {"role": "user", "content": f"[tool result] {tool_id}: {status}\n{text}{suffix}"}


def _delegate_result_message(
    coord: str | None, capability: str, status: str, text: str, *, final: bool
) -> dict:
    """The delegate's result fed back as provider context (untrusted data,
    framed — memo dev/48 §3.4)."""
    who = f"{coord} ({capability})" if coord else capability
    suffix = (
        "\nNo further tool calls are available this turn — answer with what you have."
        if final
        else ""
    )
    return {"role": "user", "content": f"[delegate result] {who}: {status}\n{text}{suffix}"}


def _mint_project_install(
    user_key: str, project_id: str, loop_ctx: dict, coord: str, name: str, capability: str
) -> tuple[str, str, dict | None]:
    """The missing-specialist proposal (dev/48 §3.4, `REQ-ORCH-001`): a
    reviewed ``Install in project`` — never a silent install, never an
    install call from the loop. Returns ``(status, text, part | None)``."""
    session_id = loop_ctx.get("session_id")
    if not isinstance(session_id, str):
        return (
            "refused",
            f"specialist {coord} is not installed and this attachment has no "
            "conversation to carry an install proposal — ask the user to install it",
            None,
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    proposal_id = uuid.uuid4().hex
    summary = f"Install {name} in this project"
    preview = (
        f"Capability {capability} is handled by {name} ({coord}), which is not "
        "installed in this project. Applying installs only this project template — "
        "it does not import, attach, run, publish, or grant anything."
    )
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="project.install",
        summary=summary,
        preview=preview,
        pins={"coord": coord},
    )
    _store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "project.install",
            "coord": coord,
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return (
        "proposed",
        f"specialist {coord} is not installed in this project; an Install proposal "
        f"({proposal_id}) awaits the user's explicit review — do NOT assume it was "
        "installed or that the delegate ran",
        part,
    )


def _resolve_delegate_request(
    user_key: str, project_id: str, loop_ctx: dict, req: dict, minted: list
) -> tuple[str, str, "delegation.Resolution | None"]:
    """Resolution half of one delegateRequest (memo dev/48): ``("ok", ...)``
    with the resolution when a child run may start; otherwise the refusal /
    missing-specialist result to feed back (proposals appended to *minted*)."""
    capability = req.get("capability", "")
    manifest = loop_ctx.get("manifest")
    if manifest is None or not manifest.delegates_to:
        return "refused", "this agent declares no delegates", None
    resolution = delegation.resolve(user_key, project_id, manifest, capability)
    if resolution.outcome == "ok":
        return "ok", "", resolution
    if resolution.outcome == "not-installed":
        status, text, part = _mint_project_install(
            user_key,
            project_id,
            loop_ctx,
            resolution.coord,
            resolution.manifest.name if resolution.manifest else resolution.coord,
            capability,
        )
        if part is not None:
            minted.append(part)
        return status, text, None
    return (
        "refused",
        f"no delegate of this agent declares capability {capability!r}",
        None,
    )


def run_attachment(
    user_key: str,
    project_id: str,
    attachment_id: str,
    message: str,
    config: ProviderConfig,
    run_context: str | None = None,
) -> dict:
    """Run one turn of an attached agent through the provider port.

    Session-aware (dev/20): the system turn is the attachment's intent override
    (dev/19) or the resolved instruction prompt, followed by a bounded window of
    the session's prior turns, then the new user message. Both sides of the
    exchange persist to the session file so a reload restores the conversation;
    a provider failure persists the user turn plus a display-only error marker
    (excluded from future context) so history matches what the user saw.
    """
    coord, session_id, messages, run_policy, wants_title, pins, loop_ctx = _prepare_run(
        user_key, project_id, attachment_id, message, config, run_context
    )
    execution_id = uuid.uuid4().hex
    # Atomic admission (dev/40): after validation (an invalid request never
    # consumes quota), before provider dispatch (a denied run never reaches a
    # provider). The reservation IS this execution (one id), and the price
    # snapshot pinned here is what settlement charges.
    reservation = ledger.reserve(
        user_key,
        price=pricing.price_snapshot(config.api_type, config.model),
        reservation_id=execution_id,
        **run_policy["admit"],
    )
    usage_total: dict = {}
    tool_calls: list = []
    delegations: list = []
    minted: list = []
    folded: list[str] = []
    final_parts: list = []
    messages_work = list(messages)
    rounds_used = 0
    started = time.monotonic()
    try:
        # The bounded tool loop (memos dev/41/48): parse → execute granted
        # read tool / mint proposal / run depth-1 delegate → re-prompt, at
        # most MAX_TOOL_ROUNDS request executions per run (one shared budget).
        while True:
            usage_sink: dict = {}
            reply = run_chat_completion(
                config,
                messages_work,
                max_output_tokens=run_policy["max_output_tokens"],
                usage_out=usage_sink,
            )
            _add_usage(usage_total, usage_sink)
            visible, parts = content.extract_content(reply)
            if visible:
                folded.append(visible)
            req = (
                parts[0]
                if parts and parts[0].get("type") in ("toolRequest", "delegateRequest")
                else None
            )
            if req is None:
                final_parts = parts
                break
            if rounds_used >= MAX_TOOL_ROUNDS:
                break  # dangling request at the cap: dropped, text kept
            rounds_used += 1
            final = rounds_used >= MAX_TOOL_ROUNDS
            if req["type"] == "delegateRequest":
                status, text, resolution = _resolve_delegate_request(
                    user_key, project_id, loop_ctx, req, minted
                )
                if resolution is not None:
                    status, text, child = delegation.run_delegate(
                        user_key,
                        project_id,
                        resolution.coord,
                        req["capability"],
                        req.get("inputs") or {},
                        config,
                        parent_execution_id=execution_id,
                        parent_coord=loop_ctx["coord"],
                        attachment_id=loop_ctx.get("attachment_id"),
                    )
                    delegations.append(child)
                    result_msg = _delegate_result_message(
                        resolution.coord, req["capability"], status, text, final=final
                    )
                else:
                    result_msg = _delegate_result_message(
                        None, req["capability"], status, text, final=final
                    )
                messages_work.append({"role": "assistant", "content": reply})
                messages_work.append(result_msg)
                continue
            status, text = _execute_tool_request(
                user_key, project_id, loop_ctx, req, tool_calls, minted
            )
            messages_work.append({"role": "assistant", "content": reply})
            messages_work.append(
                _tool_result_message(req["tool"], status, text, final=final)
            )
    except Exception as exc:
        _add_usage(usage_total, usage_sink)
        # An error settles too: the hold releases and the truth is recorded.
        settled = ledger.settle(
            user_key, reservation, usage=usage_total or None, status="error"
        )
        _persist_exchange(
            user_key,
            project_id,
            session_id,
            attachment_id,
            message,
            f"(error) {exc}",
            error=True,
            execution=_execution_record(
                execution_id, pins, usage_total, started, "error", tool_calls,
                cost_usd=settled["costUsd"], delegations=delegations,
            ),
        )
        raise AgentServiceError(f"agent run failed: {exc}", 502) from exc
    reply_text = "\n\n".join(folded)
    # A validated dataflowPlan on the final reply mints the plan proposal in
    # one step (dev/52) — runtime-minted, never model-requested.
    final_parts = _maybe_mint_plan(user_key, project_id, loop_ctx, final_parts, minted)
    run_parts = minted + final_parts  # proposals ride the turn (dev/41)
    settled = ledger.settle(user_key, reservation, usage=usage_total or None, status="ok")
    execution = _execution_record(
        execution_id, pins, usage_total, started, "ok", tool_calls,
        cost_usd=settled["costUsd"], delegations=delegations,
    )
    _persist_exchange(
        user_key,
        project_id,
        session_id,
        attachment_id,
        message,
        reply_text,
        execution=execution,
        parts=run_parts,
    )
    if wants_title:
        _generate_conversation_title(user_key, project_id, attachment_id, message, config)
    return {
        "attachmentId": attachment_id,
        "coord": coord,
        "reply": reply_text,
        "executionId": execution_id,
        "usage": execution["usage"],
        "content": run_parts,
    }


def stream_attachment(
    user_key: str,
    project_id: str,
    attachment_id: str,
    message: str,
    config: ProviderConfig,
    run_context: str | None = None,
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
    coord, session_id, messages, run_policy, wants_title, pins, loop_ctx = _prepare_run(
        user_key, project_id, attachment_id, message, config, run_context
    )
    execution_id = uuid.uuid4().hex
    # Eager atomic admission (dev/40): a quota/budget denial surfaces as a
    # plain 429 before any streaming begins, and consumes/persists nothing.
    reservation = ledger.reserve(
        user_key,
        price=pricing.price_snapshot(config.api_type, config.model),
        reservation_id=execution_id,
        **run_policy["admit"],
    )

    marker = content.TAIL_FENCE

    def _hold_split(buf: str) -> tuple[str, str]:
        """Emit-now / keep split: retain the longest trailing suffix of *buf*
        that could still be the start of the tail-fence marker (≤ ~16 chars
        held back at any moment — imperceptible in the live transcript)."""
        for k in range(min(len(marker) - 1, len(buf)), 0, -1):
            if marker.startswith(buf[-k:]):
                return buf[:-k], buf[-k:]
        return buf, ""

    def _stream_round(messages_work: list, usage_sink: dict, result: dict):
        """Stream one provider round: yields ("delta", text) with the dev/39
        tail withholding, then leaves {reply, visible, parts} in *result*."""
        chunks: list[str] = []
        buf = ""  # pass-mode text not yet emitted
        withheld: str | None = None  # not None → holding a candidate tail
        for delta in stream_chat_completion(
            config,
            messages_work,
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
        reply = "".join(chunks)
        visible, parts = content.extract_content(reply)
        if withheld is not None and not parts:
            # Invalid or non-terminal tail: fail-open (dev/39 §4.2) — the
            # withheld text is the model's, so it streams after all.
            yield ("delta", withheld)
        elif withheld is None and buf:
            yield ("delta", buf)  # stream ended on a partial fence prefix
        result["reply"] = reply
        result["visible"] = visible
        result["parts"] = parts

    def _events():
        usage_total: dict = {}
        tool_calls: list = []
        delegations: list = []
        minted: list = []
        folded: list[str] = []
        final_parts: list = []
        messages_work = list(messages)
        rounds_used = 0
        usage_sink: dict = {}
        started = time.monotonic()
        # The typed-envelope handshake (memo dev/37): the execution identity
        # arrives before the first delta so a client can correlate the stream
        # with the record that will land on the transcript.
        yield ("execution", {"executionId": execution_id})
        try:
            # The bounded tool loop (memos dev/41/48): each round streams its
            # own deltas; a toolRequest tail becomes tool events and a
            # delegateRequest tail becomes delegate events, never text.
            while True:
                usage_sink = {}
                result: dict = {}
                yield from _stream_round(messages_work, usage_sink, result)
                _add_usage(usage_total, usage_sink)
                if result["visible"]:
                    folded.append(result["visible"])
                parts = result["parts"]
                req = (
                    parts[0]
                    if parts and parts[0].get("type") in ("toolRequest", "delegateRequest")
                    else None
                )
                if req is None:
                    final_parts = parts
                    break
                if rounds_used >= MAX_TOOL_ROUNDS:
                    break  # dangling request at the cap: dropped, text kept
                rounds_used += 1
                final = rounds_used >= MAX_TOOL_ROUNDS
                if req["type"] == "delegateRequest":
                    yield ("delegate_requested", {"capability": req["capability"]})
                    status, text, resolution = _resolve_delegate_request(
                        user_key, project_id, loop_ctx, req, minted
                    )
                    if resolution is not None:
                        yield (
                            "delegate_started",
                            {"capability": req["capability"], "coord": resolution.coord},
                        )
                        status, text, child = delegation.run_delegate(
                            user_key,
                            project_id,
                            resolution.coord,
                            req["capability"],
                            req.get("inputs") or {},
                            config,
                            parent_execution_id=execution_id,
                            parent_coord=loop_ctx["coord"],
                            attachment_id=loop_ctx.get("attachment_id"),
                        )
                        delegations.append(child)
                        yield (
                            "delegate_result",
                            {
                                "capability": req["capability"],
                                "coord": resolution.coord,
                                "status": status,
                                "durationMs": child.get("durationMs"),
                            },
                        )
                        result_msg = _delegate_result_message(
                            resolution.coord, req["capability"], status, text, final=final
                        )
                    else:
                        yield (
                            "delegate_result",
                            {"capability": req["capability"], "status": status},
                        )
                        result_msg = _delegate_result_message(
                            None, req["capability"], status, text, final=final
                        )
                    messages_work.append(
                        {"role": "assistant", "content": result["reply"]}
                    )
                    messages_work.append(result_msg)
                    continue
                yield ("tool_requested", {"tool": req["tool"]})
                yield ("tool_started", {"tool": req["tool"]})
                status, text = _execute_tool_request(
                    user_key, project_id, loop_ctx, req, tool_calls, minted
                )
                yield ("tool_result", {"tool": req["tool"], "status": status})
                messages_work.append({"role": "assistant", "content": result["reply"]})
                messages_work.append(
                    _tool_result_message(req["tool"], status, text, final=final)
                )
        except Exception as exc:  # provider failure mid-stream
            _add_usage(usage_total, usage_sink)
            settled = ledger.settle(
                user_key, reservation, usage=usage_total or None, status="error"
            )
            _persist_exchange(
                user_key,
                project_id,
                session_id,
                attachment_id,
                message,
                f"(error) {exc}",
                error=True,
                execution=_execution_record(
                    execution_id, pins, usage_total, started, "error", tool_calls,
                    cost_usd=settled["costUsd"], delegations=delegations,
                ),
            )
            yield ("error", f"agent run failed: {exc}")
            return
        reply_text = "\n\n".join(folded)
        # A validated dataflowPlan on the final reply mints the plan proposal
        # in one step (dev/52) — runtime-minted, never model-requested.
        final_parts = _maybe_mint_plan(user_key, project_id, loop_ctx, final_parts, minted)
        run_parts = minted + final_parts  # proposals ride the turn (dev/41)
        settled = ledger.settle(
            user_key, reservation, usage=usage_total or None, status="ok"
        )
        execution = _execution_record(
            execution_id, pins, usage_total, started, "ok", tool_calls,
            cost_usd=settled["costUsd"], delegations=delegations,
        )
        _persist_exchange(
            user_key,
            project_id,
            session_id,
            attachment_id,
            message,
            reply_text,
            execution=execution,
            parts=run_parts,
        )
        # Title before the done frame: the reply text already streamed via
        # deltas, and the client's post-send refresh must see the title.
        if wants_title:
            _generate_conversation_title(user_key, project_id, attachment_id, message, config)
        # A pending mutation pauses at review (dev/03:344 review_required).
        for part in minted:
            yield (
                "review_required",
                {
                    "proposalId": part["proposalId"],
                    "tool": part["tool"],
                    "summary": part["summary"],
                },
            )
        if run_parts:
            yield ("content", {"parts": run_parts})
        yield (
            "done",
            {
                "reply": reply_text,
                "executionId": execution_id,
                "usage": execution["usage"],
                "content": run_parts,
            },
        )

    return _events()
