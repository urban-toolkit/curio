"""Agents catalog / lifecycle service layer.

Sits over the filesystem stores (``storage`` = definition artifacts, ``imports``
= account "My Imports", ``project_agents`` = per-project lockfile) and mirrors
``app/packages/services.py``: the route layer stays thin, this layer owns the
rules, and the project lockfile is read/written through ``projects.storage``.

Import and Install are separate explicit commands and never chain (DEC-029).
User-facing overview: ``docs/AGENTS.md``.
"""

from __future__ import annotations

import logging
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
from utk_curio.backend.app.agents import egress, node_context, verify
from utk_curio.backend.app.agents.policy import PolicyValidationError, StaleRevisionError
from utk_curio.backend.app.agents.attachments import AttachmentError
from utk_curio.backend.app.agents.manifest import AgentManifest
from utk_curio.backend.app.agents.providers import (
    ProviderConfig,
    run_chat_completion,
    stream_chat_completion,
)
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)


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
            # Completeness isn't freshness (dev/60): a roster prompt UPDATE
            # must reach the materialized copy too — rewrite on byte drift.
            fresh = all(
                (base / asset["path"]).read_text(encoding="utf-8")
                == (builtin.read_prompt_text(coord, key) or "")
                for key, asset in declared.items()
            )
            if fresh:
                return  # matches the roster asset set AND bytes
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
        # transcript's proposal part remains the display record. dev/90 A16:
        # when the slot settled but a same-reply sibling is still pending in
        # the queue, the summary shows THAT one (read-only promote).
        "activeProposal": _proposal_summary(_effective_active_proposal(record)),
        # dev/67-9: the parked plan (pending while content reviews cycle).
        "planProposal": _proposal_summary(record.get("planProposal")),
        # The Dataflow Builder orchestration session (dev/52 DR-2) — drives
        # the phase-aware builder panel; absent for every other agent.
        "builderSession": record.get("builderSession"),
    }


def _effective_active_proposal(record: dict) -> dict | None:
    """dev/90 A16, read-only: the proposal the listing should surface — the
    active slot while it is pending, else the first still-pending same-reply
    sibling waiting in the queue (write-path promotion happens in
    ``attachments.reconcile_proposal_queue``)."""
    active = record.get("activeProposal")
    if isinstance(active, dict) and active.get("status") == "pending":
        return active
    queue = record.get("queuedProposals")
    if isinstance(queue, list):
        for queued in queue:
            if isinstance(queued, dict) and queued.get("status") == "pending":
                return queued
    return active if isinstance(active, dict) else None


def _proposal_summary(proposal: object) -> dict | None:
    if not isinstance(proposal, dict):
        return None
    summary = {
        "proposalId": proposal.get("proposalId"),
        "tool": proposal.get("tool"),
        "nodeId": proposal.get("nodeId"),
        "summary": proposal.get("summary"),
        "status": proposal.get("status"),
    }
    # dev/67-5: the per-node review state survives reloads through the mirror.
    if proposal.get("tool") == "dataflow.plan.write":
        summary["editedGoals"] = dict(proposal.get("editedGoals") or {})
        summary["appliedRefs"] = list(proposal.get("appliedRefs") or [])
        summary["edgeStates"] = dict(proposal.get("edgeStates") or {})
    return summary


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
    # dev/90 A16: settle the same-reply queue first, then address the
    # proposal by id in EITHER pending home — active slot or queue.
    attachments.reconcile_proposal_queue(spec, attachment_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id)
    if proposal is None:
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
    if tool == "package.install":
        return _apply_package_install(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "package.draft.apply":
        return _apply_package_draft(
            user_key, project_id, attachment_id, proposal_id, spec, proposal, session_id
        )
    if tool == "dataflow.plan.write":
        return _apply_dataflow_plan(
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
    # dev/67-6: when this node is a plan node, applying its content resolves
    # the Simulation Mode ledger — the row is approved, the run solved.
    # dev/72: the proposal may live on the NODE's agent while the ledger
    # lives on the BUILDER — find the ledger wherever it is.
    session: dict = {}
    ref = None
    for ledger_record in attachments.list_attachments(spec):
        ledger_session = ledger_record.get("builderSession") or {}
        candidate_ref = next(
            (r for r, nid in (ledger_session.get("nodeIds") or {}).items() if nid == node_id),
            None,
        )
        if candidate_ref is not None:
            session = ledger_session
            ref = candidate_ref
            break
    if ref is not None:
        (session.get("nodeStates") or {})[ref] = "approved"
        runs = session.get("nodeRuns")
        if isinstance(runs, dict) and node_id in runs:
            runs[node_id] = "solved"
        # dev/71: the structure may have completed before the content did —
        # the last approval flips the phase to ready.
        if session.get("phase") in ("applied", "simulating") and isinstance(runs, dict):
            if not any(st in ("pending", "failed") for st in runs.values()):
                session["phase"] = "ready"
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
    code = content.extract_node_content(template.get("content"))
    if not code:
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
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
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


import re as _re

# Merge slot handles as the canvas renders them (mergeFlowBehavior in_0..in_4).
_MERGE_HANDLE_RE = _re.compile(r"^in_[0-4]$")
_MERGE_NODE_TYPE = "curio.builtin/merge-flow"


def _strip_type_version(node_type: str) -> str:
    """``curio.builtin/merge-flow@1`` → ``curio.builtin/merge-flow`` — spec
    node types may carry the versioned form; the template registry is
    unversioned-canonical."""
    return node_type.split("@", 1)[0] if isinstance(node_type, str) else node_type


def _validate_plan_fanin(
    plan: dict,
    available: dict,
    existing_nodes: dict,
    existing_edges: list,
    remove_node_set: set,
    remove_edge_set: set,
) -> list[str]:
    """dev/67-3 (DEC-051): every edge target must accept its NET incoming
    degree — plan edges plus the SURVIVING existing edges (dev/59 victims
    excluded) — against the template registry's rendered capacity. Refusals
    name the Merge resolution so the corrective round can replan; unknown or
    out-of-scope templates fail open (no arity metadata → no refusal)."""
    errors: list[str] = []
    plan_nodes = {n["ref"]: n for n in plan.get("nodes", [])}
    surviving_in: dict[str, int] = {}
    for edge in existing_edges:
        if str(edge.get("id")) in remove_edge_set:
            continue
        if edge.get("source") in remove_node_set or edge.get("target") in remove_node_set:
            continue
        target = edge.get("target")
        surviving_in[target] = surviving_in.get(target, 0) + 1
    incoming: dict[str, list[str]] = {}
    for edge in plan.get("edges", []):
        incoming.setdefault(edge["to"], []).append(edge["from"])
    for target, sources in incoming.items():
        if target in plan_nodes:
            node_type = plan_nodes[target]["nodeType"]
            label = plan_nodes[target]["title"]
            existing_count = 0
        else:
            node = existing_nodes.get(target) or {}
            node_type = _strip_type_version(str(node.get("type") or ""))
            label = (node.get("goal") or target)[:60]
            existing_count = surviving_in.get(target, 0)
        entry = available.get(node_type)
        if entry is None:
            continue  # out-of-scope/custom template: fail open
        max_in = entry.get("maxIncomingEdges")
        total = len(sources) + existing_count
        if max_in is None or total <= max_in:
            continue
        src_list = ", ".join(repr(s) for s in sources[:4])
        existing_note = (
            f" (plus {existing_count} existing connection"
            f"{'s' if existing_count != 1 else ''})"
            if existing_count
            else ""
        )
        if max_in == 0:
            errors.append(
                f"target {label!r} ({node_type}) accepts no inputs — remove the "
                f"edge(s) from {src_list}"
            )
        elif max_in == 1:
            errors.append(
                f"target {label!r} ({node_type}) accepts 1 input but the plan wires "
                f"{total}{existing_note} — route {src_list} through a "
                f"{_MERGE_NODE_TYPE} node instead (A → Merge, B → Merge, "
                "Merge → target)"
            )
        else:
            errors.append(
                f"target {label!r} ({node_type}) accepts at most {max_in} inputs "
                f"but the plan wires {total}{existing_note} — reduce the fan-in "
                "or stage merges"
            )
    for i, edge in enumerate(plan.get("edges", [])):
        handle = edge.get("toHandle")
        if not handle:
            continue
        target = edge["to"]
        if target in plan_nodes:
            node_type = plan_nodes[target]["nodeType"]
        else:
            node_type = _strip_type_version(
                str((existing_nodes.get(target) or {}).get("type") or "")
            )
        if node_type == _MERGE_NODE_TYPE and not _MERGE_HANDLE_RE.match(handle):
            errors.append(
                f"edges[{i}].toHandle {handle!r}: merge inputs are in_0..in_4"
            )
    return errors


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
    # dev/67-5: plans describe intent — generated code never rides a plan.
    # There is no "trivial code" shortcut (67-0): every node's content is
    # produced and validated per node after creation. Supersedes dev/52's
    # plan-carried-content allowance at its recorded revisit point.
    content_refs = [n["ref"] for n in plan["nodes"] if n.get("content")]
    if content_refs:
        return (
            "refused",
            "plan nodes must not carry content — plans describe intent; node "
            "content is generated and validated per node after creation. "
            f"Remove the content from: {', '.join(repr(r) for r in content_refs)}",
            None,
        )
    try:
        available = {t["id"]: t for t in packages_services.available_templates(user_key, project_id)}
    except Exception as exc:
        return "refused", f"the node template registry is unavailable: {exc}", None
    # dev/93 D3: the ONE availability gate, shared with node.create — a plan
    # may name any available template (a plan places a typed PLACEHOLDER whose
    # content arrives later from Solve), hence require_authorable=False. The
    # nodeType is already canonical here (canonicalised at the parse boundary),
    # so this used to be an exact-match dict lookup that refused the versioned
    # spelling the model was handed by its own run context.
    for node in plan["nodes"]:
        entry, err = packages_services.resolve_template(
            user_key, project_id, node["nodeType"], require_authorable=False
        )
        if entry is None:
            return "refused", f"plan node {node['ref']!r}: {err}", None
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    # Revision validation against the saved spec (dev/59): removal targets and
    # existing-id edge endpoints must be real; the grammar could only check
    # shape. Errors feed the same correction rounds as every plan failure.
    import hashlib

    dataflow = spec.get("dataflow") or {}
    existing_nodes = {
        n.get("id"): n for n in dataflow.get("nodes") or [] if isinstance(n, dict)
    }
    existing_edges = [e for e in dataflow.get("edges") or [] if isinstance(e, dict)]
    existing_edge_ids = {str(e.get("id")) for e in existing_edges}
    remove_nodes = plan.get("removeNodes", [])
    remove_edges = plan.get("removeEdges", [])
    revision_errors: list[str] = []
    for node_id in remove_nodes:
        if node_id not in existing_nodes:
            revision_errors.append(
                f"removeNodes: {node_id!r} is not a node in the saved dataflow — "
                "use real node ids (dataflow.read shows them)"
            )
    for edge_id in remove_edges:
        if edge_id not in existing_edge_ids:
            revision_errors.append(
                f"removeEdges: {edge_id!r} is not an edge in the saved dataflow"
            )
    plan_refs = {n["ref"] for n in plan["nodes"]}
    for i, edge in enumerate(plan["edges"]):
        for label in ("from", "to"):
            endpoint = edge[label]
            if endpoint not in plan_refs and endpoint not in existing_nodes:
                revision_errors.append(
                    f"edges[{i}].{label} {endpoint!r} is neither a plan ref nor an "
                    "existing node id"
                )
    if revision_errors:
        return "refused", "\n- ".join(["the plan's revision targets are invalid:"] + revision_errors), None
    remove_node_set = set(remove_nodes)
    # dev/67-3 (DEC-051): fan-in validates BEFORE anything materializes — an
    # invalid multi-input topology is unmintable, and the corrective error
    # names the Merge resolution.
    fanin_errors = _validate_plan_fanin(
        plan, available, existing_nodes, existing_edges,
        remove_node_set, set(remove_edges),
    )
    if fanin_errors:
        return "refused", "\n- ".join(["the plan wires invalid fan-in:"] + fanin_errors), None
    # The cascade: edges incident to removed nodes die with them (dev/59) —
    # computed here for the review card, recomputed at apply as the truth.
    cascade_edge_ids = [
        str(e.get("id"))
        for e in existing_edges
        if (e.get("source") in remove_node_set or e.get("target") in remove_node_set)
        and str(e.get("id")) not in set(remove_edges)
    ]
    # dev/67-5: positions are computed ONCE at mint, so per-node applies land
    # exactly where the whole-plan apply would have put them (and both read
    # the same map). Extent from the pre-removal spec — victims may inflate
    # it slightly; a stable layout beats a perfectly tight one.
    xs = [n.get("x") for n in existing_nodes.values() if isinstance(n.get("x"), (int, float))]
    ys = [n.get("y") for n in existing_nodes.values() if isinstance(n.get("y"), (int, float))]
    layout_base_x = (max(xs) + _PLAN_COLUMN_OFFSET) if xs else 80.0
    layout_base_y = min(ys) if ys else 80.0
    layout_depths = _plan_depths(plan["nodes"], plan["edges"])
    layout_rows: dict[int, int] = {}
    positions: dict[str, dict] = {}
    for node in plan["nodes"]:
        depth = layout_depths.get(node["ref"], 0)
        row = layout_rows.get(depth, 0)
        layout_rows[depth] = row + 1
        positions[node["ref"]] = {
            "x": float(layout_base_x + depth * _PLAN_COLUMN_OFFSET),
            "y": float(layout_base_y + row * _PLAN_ROW_OFFSET),
        }
    digest = _graph_shape_digest(spec)
    pins: dict = {"baseGraphDigest": digest}
    if remove_nodes:
        # DEC-049.1: every victim pinned by its content at mint — editing a
        # doomed node between mint and apply makes the apply 409 + stale.
        pins["removeContentSha256"] = {
            node_id: hashlib.sha256(
                (existing_nodes[node_id].get("content") or "").encode("utf-8")
            ).hexdigest()
            for node_id in remove_nodes
        }
    proposal_id = uuid.uuid4().hex
    n_nodes, n_edges = len(plan["nodes"]), len(plan["edges"])
    summary = f"Apply plan · {n_nodes} nodes, {n_edges} edges"
    if remove_nodes or remove_edges:
        summary += f", removes {len(remove_nodes)} node{'s' if len(remove_nodes) != 1 else ''}"
    preview_lines = [
        f"{node['title']} · {node['nodeType']} — {node['intent']}" for node in plan["nodes"]
    ]
    for node_id in remove_nodes:
        victim = existing_nodes[node_id]
        label = (victim.get("goal") or node_id)[:80]
        preview_lines.append(f"− Remove: {label} · {victim.get('type') or 'untyped'}")
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="dataflow.plan.write",
        summary=summary,
        preview="\n".join(preview_lines),
        pins=pins,
    )
    # The display copy for the review card (bounded upstream by the grammar).
    part["plan"] = {
        "goal": plan["goal"],
        **({"templateId": plan["templateId"]} if plan.get("templateId") else {}),
        "nodes": [
            {
                "ref": n["ref"], "nodeType": n["nodeType"], "title": n["title"],
                "intent": n["intent"],
                **({"expects": n["expects"]} if n.get("expects") else {}),
            }
            for n in plan["nodes"]
        ],
        "edgeCount": n_edges,
        # dev/67-8: the connection stage reviews edges BY NAME — labels from
        # plan titles (refs) or spec goals (existing ids), index-stable.
        "edges": [
            {
                "from": e["from"],
                "to": e["to"],
                **({"toHandle": e["toHandle"]} if e.get("toHandle") else {}),
                "fromLabel": _plan_endpoint_label(e["from"], plan, existing_nodes),
                "toLabel": _plan_endpoint_label(e["to"], plan, existing_nodes),
            }
            for e in plan["edges"]
        ],
    }
    if remove_nodes or remove_edges:
        # DEC-049.2: removals reviewed by NAME — every victim listed with a
        # content flag; the cascade counted.
        part["plan"]["removals"] = [
            {
                "id": node_id,
                "label": (existing_nodes[node_id].get("goal") or node_id)[:80],
                "nodeType": existing_nodes[node_id].get("type"),
                "contentChars": len(existing_nodes[node_id].get("content") or ""),
            }
            for node_id in remove_nodes
        ]
        part["plan"]["removedEdgeCount"] = len(remove_edges)
        part["plan"]["cascadeCount"] = len(cascade_edge_ids)
    # The builder session (DR-2) transitions on the SAME spec write: the
    # attachment record is rule-9 share-stripped and save-preserved already.
    record = attachments.get_attachment(spec, loop_ctx["attachment_id"])
    if record is not None:
        session = record.setdefault("builderSession", {})
        session["phase"] = "plan_review"
        session["planProposalId"] = proposal_id
        # dev/67-5: the per-node Simulation Mode ledger — reset per plan.
        session["nodeStates"] = {n["ref"]: "planned" for n in plan["nodes"]}
        session["nodeIds"] = {}
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
            # dev/67-5: per-node application state + the mint-time layout.
            "positions": positions,
            "editedGoals": {},
            "appliedRefs": [],
            "appliedNodeIds": {},
            # DEC-049.1: the apply re-checks each victim against this mirror.
            **(
                {"removeContentSha256": pins["removeContentSha256"]}
                if "removeContentSha256" in pins
                else {}
            ),
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return "proposed", "", part


# dev/67-5: review-stage goal edits are bounded like plan intents.
_PLAN_GOAL_EDIT_MAX_CHARS = 300


def _pending_plan_proposal(spec: dict, attachment_id: str, proposal_id: str) -> dict:
    """The dev/67-5 per-node review preamble: the attachment's active
    dataflow-plan proposal, pending, matching *proposal_id* — or the honest
    404/409."""
    proposal = attachments.get_active_proposal(spec, attachment_id)
    if proposal is None or proposal.get("proposalId") != proposal_id:
        # dev/67-9: the plan may be PARKED while a content review occupies
        # the active slot — its stages stay addressable.
        record = attachments.get_attachment(spec, attachment_id)
        parked = (record or {}).get("planProposal")
        if isinstance(parked, dict) and parked.get("proposalId") == proposal_id:
            proposal = parked
        else:
            raise AgentServiceError(f"proposal {proposal_id!r} not found", 404)
    status = proposal.get("status")
    if status != "pending":
        raise AgentServiceError(
            f"this proposal is {status!r} and can no longer be worked on", 409
        )
    if proposal.get("tool") != "dataflow.plan.write":
        raise AgentServiceError("this proposal is not a dataflow plan", 409)
    return proposal


def set_plan_goal(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    ref: str,
    goal: str,
) -> dict:
    """dev/67-5: review-stage goal editing — an audited overlay applied at
    creation. The PINNED plan bytes stay immutable (the digest model
    survives); the overlay lives on the proposal and rides the mirror so it
    survives reloads. Pending proposals only."""
    spec = _read_spec_or_404(user_key, project_id)
    _record_or_404(spec, attachment_id)
    proposal = _pending_plan_proposal(spec, attachment_id, proposal_id)
    refs = {n["ref"] for n in (proposal.get("plan") or {}).get("nodes", [])}
    if ref not in refs:
        raise AgentServiceError(f"ref {ref!r} is not a node in this plan", 404)
    if not isinstance(goal, str) or not goal.strip():
        raise AgentServiceError("goal must be a non-empty string", 422)
    goal = goal.strip()
    if len(goal) > _PLAN_GOAL_EDIT_MAX_CHARS:
        raise AgentServiceError(
            f"goal exceeds {_PLAN_GOAL_EDIT_MAX_CHARS} characters", 422
        )
    edited = proposal.setdefault("editedGoals", {})
    edited[ref] = goal
    projects_storage.write_spec(user_key, project_id, spec)
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "ref": ref,
        "goal": goal,
        "editedGoals": dict(edited),
    }


def _attach_node_builder(spec: dict, node_id: str) -> str | None:
    """dev/71: best-effort Node Builder attachment for a plan-created node.
    Skips (returning None) when the template is not installed or the node
    already carries one — node creation NEVER fails over this."""
    from utk_curio.backend.app.agents import project_agents

    coord = next(
        (
            c for c in project_agents.project_agents(spec)
            if c.split("@", 1)[0] == "agent.node-builder"
        ),
        None,
    )
    if coord is None:
        return None
    for existing in attachments.list_attachments(spec):
        target = existing.get("target") or {}
        if (
            existing.get("coord", "").split("@", 1)[0] == "agent.node-builder"
            and target.get("kind") == "node"
            and target.get("targetId") == node_id
        ):
            return existing.get("attachmentId")
    try:
        record = attachments.attach(
            spec, coord, {"kind": "node", "targetId": node_id},
            attachment_id=uuid.uuid4().hex, session_id=uuid.uuid4().hex,
        )
        return record.get("attachmentId")
    except Exception:
        return None  # best-effort: never block the node over its agent


def apply_plan_node(
    user_key: str, project_id: str, attachment_id: str, proposal_id: str, ref: str
) -> dict:
    """dev/67-5: apply ONE planned node — the per-node narrowing of the plan
    apply (Simulation Mode: create). Edges are the connection stage's concern
    (67-8); the proposal STAYS pending until every ref is applied or it is
    dismissed. A pure node ADD is drift-safe, so the whole-graph digest is not
    re-checked here — the ref's slice of the apply contract is: proposal
    pending (a stale/dismissed one refuses at the status gate) + the template
    still available. Creation uses the mint-time position and the (possibly
    edited) goal; the created node joins ``nodeRuns`` as ``pending`` so Solve
    and the 67-6/67-7 stages pick it up."""
    from utk_curio.backend.app.packages import services as packages_services

    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    proposal = _pending_plan_proposal(spec, attachment_id, proposal_id)
    plan = proposal.get("plan") or {}
    plan_node = next((n for n in plan.get("nodes", []) if n["ref"] == ref), None)
    if plan_node is None:
        raise AgentServiceError(f"ref {ref!r} is not a node in this plan", 404)
    applied_refs = proposal.setdefault("appliedRefs", [])
    applied_ids = proposal.setdefault("appliedNodeIds", {})
    session_id = record.get("sessionId")
    if ref in applied_refs:
        # Idempotent: the node exists; say so honestly, change nothing.
        return {
            "attachmentId": attachment_id,
            "proposalId": proposal_id,
            "status": "already-applied",
            "ref": ref,
            "nodeId": applied_ids.get(ref),
            "appliedRefs": list(applied_refs),
            "builderSession": record.get("builderSession"),
        }
    try:
        available = {t["id"] for t in packages_services.available_templates(user_key, project_id)}
    except Exception as exc:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the node template registry is unavailable: {exc}",
        ) from exc
    # dev/93 D3: canonicalise the COMPARISON, never the stored value — a
    # proposal minted before the parse-boundary change may hold a raw
    # versioned string whose shape digest was computed over exactly that
    # string, so rewriting it here would mark an in-flight proposal stale.
    if packages_services.canonical_template_id(plan_node["nodeType"]) not in available:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"node type {plan_node['nodeType']!r} is no longer available — "
            "ask the agent to replan",
        )
    pos = (proposal.get("positions") or {}).get(ref) or {}
    goal_text = (proposal.get("editedGoals") or {}).get(ref) or (
        f"{plan_node['title']} — {plan_node['intent']}"
    )
    node_id = str(uuid.uuid4())
    created = {
        "id": node_id,
        "type": plan_node["nodeType"],
        "content": "",
        "goal": goal_text,
        "x": float(pos.get("x", 80.0)),
        "y": float(pos.get("y", 80.0)),
    }
    dataflow = spec.setdefault("dataflow", {})
    dataflow.setdefault("nodes", []).append(created)
    applied_refs.append(ref)
    applied_ids[ref] = node_id
    # dev/71: attach the Node Builder to the created node (best-effort,
    # idempotent — creation never fails over it); it operates as the node's
    # creation/content orchestration agent (67-6 modify-existing posture).
    attached_agent_id = _attach_node_builder(spec, node_id)
    # dev/71: PROGRESSIVE CONNECTION — apply every plan edge whose other
    # endpoint already exists (created refs or existing canvas nodes), through
    # the 67-8 per-edge policy. The graph grows connected, not as islands;
    # topology refusals are recorded per edge and never block the node.
    ctx = _plan_edge_context(user_key, project_id, spec, proposal)
    edge_results: dict = {}
    created_edges: list[dict] = []
    for index in range(len(ctx["plan_edges"])):
        if ctx["edge_states"].get(str(index)) == "applied":
            continue
        result_row, created_edge = _apply_one_plan_edge(ctx, index, record_missing=False)
        if result_row is not None:
            edge_results[str(index)] = result_row
        if created_edge is not None:
            created_edges.append(created_edge)
    # Re-pin the shape digest to the spec THIS apply produced: the plan's own
    # per-node progress is legitimate drift for a later whole-plan apply;
    # foreign edits between applies still 409 + stale.
    proposal["baseGraphDigest"] = _graph_shape_digest(spec)
    session = record.setdefault("builderSession", {})
    session["phase"] = "simulating"
    session["appliedPlanId"] = proposal_id
    session.setdefault("nodeStates", {})[ref] = "created"
    session.setdefault("nodeIds", {})[ref] = node_id
    session.setdefault("nodeRuns", {})[node_id] = "pending"
    session["edgeStates"] = dict(ctx["edge_states"])
    # The last apply may complete the STRUCTURE (all refs + edges applied) —
    # content keeps its own lifecycle (dev/71).
    _complete_plan_if_done(record, proposal, session)
    projects_storage.write_spec(user_key, project_id, spec)
    if isinstance(session_id, str):
        # A result card WITHOUT flipping the proposal part: it stays pending
        # for the remaining refs (unlike _log_applied_turn's applied flip).
        sessions.append_turns(
            user_key, project_id, session_id, attachment_id,
            [
                sessions.make_turn(
                    "agent",
                    f"Applied: created node {plan_node['title']!r} from the plan "
                    f"({len(applied_refs)} of {len(plan.get('nodes', []))}).",
                    content=[{
                        "type": "card",
                        "kind": "result",
                        "title": "Applied: plan node created",
                        "lines": [
                            f"{plan_node['title']} · {plan_node['nodeType']}",
                            f"node {node_id[:8]}",
                            f"{len(applied_refs)} of {len(plan.get('nodes', []))} plan nodes created",
                            f"proposal {proposal_id[:8]}",
                        ],
                    }],
                )
            ],
        )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": proposal.get("status", "pending"),
        "ref": ref,
        # The bridge's node-created payload shape (dev/48 §3.3).
        "createdNode": dict(created),
        "appliedRefs": list(applied_refs),
        # dev/71: the progressive sweep's outcomes + the bridge payload.
        "createdEdges": created_edges,
        "edgeResults": edge_results,
        "edgeStates": dict(ctx["edge_states"]),
        "attachedAgentId": attached_agent_id,
        "builderSession": session,
    }


def _plan_endpoint_label(endpoint: str, plan: dict, existing_nodes: dict) -> str:
    """A human label for one plan-edge endpoint: the plan node's title, or the
    existing node's goal (id as the last resort)."""
    for node in plan.get("nodes", []):
        if node["ref"] == endpoint:
            return node["title"][:60]
    existing = existing_nodes.get(endpoint) or {}
    return str(existing.get("goal") or endpoint)[:60]


def _plan_edge_context(
    user_key: str, project_id: str, spec: dict, proposal: dict
) -> dict:
    """Shared lookups + mutable state for per-edge application (dev/71 —
    ONE validation policy for the connect stage and the progressive sweep)."""
    from utk_curio.backend.app.packages import services as packages_services

    plan = proposal.get("plan") or {}
    dataflow = spec.setdefault("dataflow", {})
    nodes = dataflow.setdefault("nodes", [])
    edges = dataflow.setdefault("edges", [])
    try:
        available = {
            t["id"]: t
            for t in packages_services.available_templates(user_key, project_id)
        }
    except Exception:
        available = {}  # arity metadata unavailable: fan-in fails open
    types_by_id = {
        n.get("id"): _strip_type_version(str(n.get("type") or ""))
        for n in nodes
        if isinstance(n, dict)
    }
    merge_slots_taken: dict[str, set[str]] = {}
    incoming_count: dict[str, int] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        target = e.get("target")
        if str(e.get("type") or "") == "Interaction":
            continue
        incoming_count[target] = incoming_count.get(target, 0) + 1
        if types_by_id.get(target) == _MERGE_NODE_TYPE and isinstance(e.get("targetHandle"), str):
            merge_slots_taken.setdefault(target, set()).add(e["targetHandle"])
    return {
        "plan": plan,
        "plan_edges": plan.get("edges", []),
        "plan_refs": {n["ref"] for n in plan.get("nodes", [])},
        "edge_states": proposal.setdefault("edgeStates", {}),
        "applied_ids": proposal.get("appliedNodeIds") or {},
        "nodes_by_id": {n.get("id"): n for n in nodes if isinstance(n, dict)},
        "edges": edges,
        "available": available,
        "types_by_id": types_by_id,
        "merge_slots_taken": merge_slots_taken,
        "incoming_count": incoming_count,
    }


def _apply_one_plan_edge(ctx: dict, index: int, *, record_missing: bool = True):
    """Apply ONE plan edge against the CURRENT spec (the 67-8 policy: endpoint
    resolution, already-connected no-op, DEC-051 fan-in, merge slots).
    Returns ``(result_row | None, created_edge | None)`` — ``None`` result when
    an endpoint is missing and ``record_missing`` is False (the progressive
    sweep skips not-yet-created endpoints silently; the explicit connect
    stage names them)."""
    plan = ctx["plan"]
    plan_edge = ctx["plan_edges"][index]
    edge_states = ctx["edge_states"]
    nodes_by_id = ctx["nodes_by_id"]
    key = str(index)
    row = {
        "from": plan_edge["from"],
        "to": plan_edge["to"],
        "fromLabel": _plan_endpoint_label(plan_edge["from"], plan, nodes_by_id),
        "toLabel": _plan_endpoint_label(plan_edge["to"], plan, nodes_by_id),
    }
    if edge_states.get(key) == "applied":
        return {**row, "status": "already-applied"}, None

    def _resolve_endpoint(endpoint: str):
        if endpoint in ctx["plan_refs"]:
            node_id = ctx["applied_ids"].get(endpoint)
            if not node_id:
                title = _plan_endpoint_label(endpoint, plan, nodes_by_id)
                return None, f"create {title!r} first"
            if node_id not in nodes_by_id:
                return None, f"node {node_id!r} was deleted from the canvas"
            return node_id, None
        if endpoint in nodes_by_id:
            return endpoint, None
        return None, f"node {endpoint!r} is no longer in the dataflow"

    source, source_err = _resolve_endpoint(plan_edge["from"])
    target, target_err = _resolve_endpoint(plan_edge["to"])
    if source_err or target_err:
        if not record_missing:
            return None, None  # progressive sweep: endpoint not created yet
        reason = source_err or target_err
        edge_states[key] = "refused"
        return {**row, "status": "refused", "reason": reason}, None
    already = next(
        (
            e for e in ctx["edges"]
            if isinstance(e, dict)
            and e.get("source") == source and e.get("target") == target
            and str(e.get("type") or "") != "Interaction"
        ),
        None,
    )
    if already is not None:
        edge_states[key] = "applied"
        return {
            **row, "status": "applied", "edgeId": already.get("id"),
            "note": "already connected",
        }, None
    # Fan-in against the CURRENT spec (DEC-051 rendered capacity).
    target_type = ctx["types_by_id"].get(target, "")
    entry = ctx["available"].get(target_type)
    max_in = entry.get("maxIncomingEdges") if entry else None
    incoming = ctx["incoming_count"]
    if max_in is not None and incoming.get(target, 0) + 1 > max_in:
        reason = (
            f"{row['toLabel']!r} accepts "
            + ("no inputs" if max_in == 0 else f"at most {max_in} input{'s' if max_in != 1 else ''}")
            + f" and already has {incoming.get(target, 0)} — "
            f"route through a {_MERGE_NODE_TYPE} node instead"
        )
        edge_states[key] = "refused"
        return {**row, "status": "refused", "reason": reason}, None
    target_handle = plan_edge.get("toHandle") or "in"
    if target_type == _MERGE_NODE_TYPE:
        taken = ctx["merge_slots_taken"].setdefault(target, set())
        wanted_handle = plan_edge.get("toHandle")
        if isinstance(wanted_handle, str) and _MERGE_HANDLE_RE.match(wanted_handle) and wanted_handle not in taken:
            target_handle = wanted_handle
        else:
            target_handle = next(
                (f"in_{i}" for i in range(5) if f"in_{i}" not in taken), None
            )
            if target_handle is None:
                edge_states[key] = "refused"
                return {
                    **row, "status": "refused",
                    "reason": f"merge node {row['toLabel']!r} has no free input slot",
                }, None
        taken.add(target_handle)
    edge = {
        "id": str(uuid.uuid4()),
        "source": source,
        "target": target,
        "sourceHandle": "out",
        "targetHandle": target_handle,
    }
    ctx["edges"].append(edge)
    incoming[target] = incoming.get(target, 0) + 1
    edge_states[key] = "applied"
    return {
        **row, "status": "applied", "edgeId": edge["id"],
        "targetHandle": target_handle,
    }, edge


def _complete_plan_if_done(record: dict, proposal: dict, session: dict) -> bool:
    """The plan proposal completes when every ref AND every edge is applied —
    the reviewed STRUCTURE is fully materialized (content has its own
    lifecycle: nodeStates/nodeRuns keep tracking Solve). dev/71: the parked
    plan is KEPT after completion — the progressive lifecycle (per-row
    Solve/Run, the driver's validate/approve actions) still reads it; a new
    plan mint replaces it."""
    plan = proposal.get("plan") or {}
    plan_refs = {n["ref"] for n in plan.get("nodes", [])}
    edge_states = proposal.get("edgeStates") or {}
    all_refs_applied = plan_refs and plan_refs == set(proposal.get("appliedRefs") or [])
    all_edges_applied = all(
        edge_states.get(str(i)) == "applied"
        for i in range(len(plan.get("edges", [])))
    )
    if not (all_refs_applied and all_edges_applied):
        return False
    proposal["status"] = "applied"
    runs = session.get("nodeRuns") or {}
    unresolved = any(s in ("pending", "failed") for s in runs.values())
    session["phase"] = "applied" if unresolved else "ready"
    session["appliedPlanId"] = proposal.get("proposalId")
    return True


def apply_plan_edges(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    indices: list[int] | None = None,
) -> dict:
    """Apply plan edges — the connection review stage (memo dev/67-8,
    Simulation Mode: connect; per-edge core shared with the dev/71
    progressive sweep).

    All not-yet-applied edges by default, or the given subset (index-stable —
    the pinned plan's order). Each edge validates against the CURRENT spec at
    apply time; refusals are PER EDGE and named — partial success is normal
    and honest. An edge the user already drew manually applies as a no-op.
    When every ref and every edge is applied, the proposal completes."""
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    proposal = _pending_plan_proposal(spec, attachment_id, proposal_id)
    plan = proposal.get("plan") or {}
    plan_edges = plan.get("edges", [])
    if indices is not None:
        bad = [i for i in indices if not isinstance(i, int) or not (0 <= i < len(plan_edges))]
        if bad:
            raise AgentServiceError(f"edge indices out of range: {bad}", 422)
    ctx = _plan_edge_context(user_key, project_id, spec, proposal)
    edge_states = ctx["edge_states"]
    wanted = indices if indices is not None else [
        i for i in range(len(plan_edges)) if edge_states.get(str(i)) != "applied"
    ]
    results: dict = {}
    created_edges: list[dict] = []
    for index in wanted:
        result_row, created = _apply_one_plan_edge(ctx, index)
        if result_row is not None:
            results[str(index)] = result_row
        if created is not None:
            created_edges.append(created)
    # dev/67-5 semantics: the plan's own progress re-pins the shape digest.
    proposal["baseGraphDigest"] = _graph_shape_digest(spec)
    session = record.setdefault("builderSession", {})
    session["edgeStates"] = dict(edge_states)
    session_id = record.get("sessionId")
    completed = _complete_plan_if_done(record, proposal, session)
    applied_now = sum(1 for r in results.values() if r["status"] == "applied")
    refused_now = sum(1 for r in results.values() if r["status"] == "refused")
    if isinstance(session_id, str) and (applied_now or refused_now):
        if completed:
            _log_applied_turn(
                user_key, project_id, session_id, attachment_id, proposal_id,
                f"Applied: {applied_now} connection{'s' if applied_now != 1 else ''} — "
                "the plan is fully applied.",
                "Applied: plan connections",
                [
                    f"+{applied_now} connections"
                    + (f" · {refused_now} refused" if refused_now else ""),
                    "plan complete",
                    f"proposal {proposal_id[:8]}",
                ],
            )
        else:
            sessions.append_turns(
                user_key, project_id, session_id, attachment_id,
                [sessions.make_turn(
                    "agent",
                    f"Applied {applied_now} connection{'s' if applied_now != 1 else ''}"
                    + (f"; {refused_now} refused — see the card." if refused_now else "."),
                    content=[{
                        "type": "card",
                        "kind": "result",
                        "title": "Applied: plan connections",
                        "lines": [
                            f"{r['fromLabel']} → {r['toLabel']} · {r['status']}"
                            + (f" — {r['reason']}" if r.get("reason") else "")
                            for r in list(results.values())[:10]
                        ],
                    }],
                )],
            )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": proposal.get("status"),
        "results": results,
        "edgeStates": dict(edge_states),
        # The bridge inserts these into the LIVE canvas (dev/67-8).
        "createdEdges": created_edges,
        "builderSession": session,
    }


def _plan_correction_message(errors: list[str]) -> dict:
    """The corrective round's feedback (dev/54): precise, model-actionable,
    and explicit that the invalid block never reached the user."""
    listed = "\n".join(f"- {e}" for e in errors[:10])
    return {
        "role": "user",
        "content": (
            "[plan validation] Your dataflowPlan block was invalid and was NOT "
            "shown to the user. Fix exactly these problems and resend the "
            "COMPLETE corrected block (all nodes and edges, same fence syntax):\n"
            + listed
        ),
    }


def _handle_plan_reply(
    user_key: str,
    project_id: str,
    loop_ctx: dict,
    reply: str,
    parts: list,
    minted: list,
    rounds_used: int,
) -> tuple[str, list]:
    """In-loop plan handling (dev/52 mint, dev/54 correction rounds).

    Returns ``(kind, payload, visible_override)``: ``("none", parts, None)``
    — not a plan situation (ungranted agents keep the informational part;
    generic fail-open untouched); ``("mint", parts, override?)`` — the
    proposal was minted (appended to *minted*; the override strips a scanned
    fence block from the persisted text, dev/56); ``("correct", errors,
    None)`` — feed the errors back and re-round (shares the MAX_TOOL_ROUNDS
    budget); ``("cap", parts+card, None)`` — budget exhausted: fail loudly,
    never silently."""
    if "dataflow.plan.write" not in loop_ctx.get("granted", []):
        return "none", parts, None
    visible_override: str | None = None
    fence_guidance = (
        "put the plan in a ```curio.v1 fenced block as the VERY LAST thing in "
        "your reply (not ```json)"
    )
    plan_part = next((p for p in parts if p.get("type") == "dataflowPlan"), None)
    if plan_part is not None:
        status, error_text, part = _mint_dataflow_plan(user_key, project_id, loop_ctx, plan_part)
        if part is not None:
            minted.append(part)
            return "mint", [p for p in parts if p is not plan_part], None
        errors = [error_text]
    else:
        _, tail_body = content.split_tail(reply)
        errors = content.plan_tail_diagnosis(tail_body)
        if not errors:
            # No terminal-tail attempt — the fence-agnostic scanner (dev/56):
            # models emit ```json / bare fences, often mid-reply.
            stripped, raw = content.extract_plan_attempt(reply)
            if raw is None:
                return "none", parts, None  # genuinely not a plan attempt
            if isinstance(raw, str):
                errors = (content.plan_tail_diagnosis(raw) or []) + [fence_guidance]
            else:
                plan, plan_errors = content.parse_dataflow_plan_verbose(raw)
                if not plan_errors:
                    status, error_text, part = _mint_dataflow_plan(
                        user_key, project_id, loop_ctx, plan
                    )
                    if part is not None:
                        minted.append(part)
                        # The review card is the plan's home — the raw JSON
                        # block is stripped from the persisted text.
                        return "mint", parts, stripped
                    errors = [error_text, fence_guidance]
                else:
                    errors = plan_errors + [fence_guidance]
    if rounds_used < MAX_TOOL_ROUNDS:
        return "correct", errors, None
    card = {
        "type": "card",
        "kind": "error",
        "title": "Plan not proposable",
        "lines": [e[:300] for e in errors[:10]],
    }
    return "cap", [p for p in parts if p.get("type") != "dataflowPlan"] + [card], None


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


# The model's why-needed rationale rides the proposal card — bounded so a
# runaway reply can't bloat the persisted mirror (dev/84).
_PACKAGE_REASON_MAX_CHARS = 300


def _mint_package_install(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/84 reviewed-install lane: propose installing ONE Nodes Catalog
    package through the existing package flow. Built-ins are never proposable
    (always present) and an already-installed package refuses at mint with
    the state — honest chat instead of a dead proposal (dev/16 idempotence)."""
    from utk_curio.backend.app.packages import services as packages_services

    params = req.get("params") or {}
    dir_name = params.get("dirName")
    if not isinstance(dir_name, str) or not dir_name.strip():
        return "refused", "params.dirName must be a non-empty package dirName string", None
    dir_name = dir_name.strip()
    try:
        rows = {
            r["dirName"]: r
            for r in packages_services.agent_catalog_overview(user_key, project_id)
        }
    except Exception as exc:  # a broken catalog is data, not a run error
        return "refused", f"the Nodes Catalog is unavailable: {exc}", None
    row = rows.get(dir_name)
    if row is None:
        return "refused", (
            f"package {dir_name!r} is not in the Nodes Catalog — propose only "
            "dirNames from packages.catalog results"
        ), None
    if row["builtin"]:
        return "refused", (
            f"package {row['name']!r} is built-in — always present, never proposed; "
            "tell the user it is already available"
        ), None
    if row["installed"]:
        return "refused", (
            f"package {row['name']!r} is already installed in this project — "
            "tell the user instead of proposing"
        ), None
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    reason = params.get("reason")
    reason = reason.strip()[:_PACKAGE_REASON_MAX_CHARS] if isinstance(reason, str) else ""
    proposal_id = uuid.uuid4().hex
    summary = f"Install package · {row['name']}"
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="package.install",
        summary=summary,
        preview=reason or (row.get("description") or dir_name),
        pins={"dirName": dir_name},
    )
    _store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "package.install",
            "dirName": dir_name,
            "packageName": row["name"],
            "reason": reason,
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return (
        "proposed",
        f"proposal {proposal_id} created to install package {row['name']!r}; it awaits "
        "the user's explicit review through the package install dialog — do NOT "
        "assume it was installed",
        part,
    )


def _mint_package_draft_apply(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The dev/89 authoring lane: validate the typed build request, run the
    isolated build service (resolve → compile → preview → package — all
    staged, content-addressed, digest-idempotent), and mint the reviewed
    package-draft proposal from its provenance.

    A build failure is a refusal carrying the findings — the model revises
    the draft; nothing dangles. The proposal persists only bounded
    provenance (digests, diff, findings, preview digests, requested nodes)
    — the artifact itself stays in private staging until Apply promotes the
    exact reviewed digest.
    """
    from utk_curio.backend.app.packages import build_models, build_pipeline

    params = req.get("params") or {}
    try:
        request = build_models.parse_build_request(params)
    except (build_models.BuildRequestError, ValueError) as exc:
        return "refused", f"invalid build request: {exc}", None
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    try:
        job = build_pipeline.run_build(user_key, request)
    except Exception as exc:  # noqa: BLE001 — a broken build service is data
        return "refused", f"the package build service failed to start: {exc}", None
    if job.phase != "ready":
        result = job.result
        details = ""
        if result is not None:
            details = "; ".join(list(result.warnings)[:2] + list(result.policy_findings)[:3])
        if not details:
            details = "; ".join(e["message"] for e in job.events[-2:])
        return "refused", (
            f"the package build did not complete (phase {job.phase}): {details} "
            "— revise the draft and request package.draft.apply again"
        ), None

    result = job.result
    manifest_name = str(request.manifest.get("name") or request.target)
    action = "Extend" if request.mode == "extend" else "Build"
    summary = f"{action} package · {manifest_name}"
    diff = result.diff or {}
    files_diff = diff.get("files") or {}
    preview_line = (
        f"{len(files_diff.get('added') or [])} added / "
        f"{len(files_diff.get('modified') or [])} modified / "
        f"{len(files_diff.get('preserved') or [])} preserved files; "
        f"{len(request.nodes)} node(s) after install"
    )
    # memo dev/91 §5: the trust edge is stated ON the card, before Apply —
    # a backend-bearing draft names its handlers and declared permissions.
    backend_card = None
    if result.backend is not None:
        permissions = [
            p for p in (request.manifest.get("permissions") or [])
            if isinstance(p, str)
        ]
        backend_card = {
            "handlers": list(result.backend.get("handlers") or []),
            "permissions": permissions,
            "network": "server-network" in permissions,
        }
        names = ", ".join(h.get("name", "?") for h in backend_card["handlers"])
        preview_line += (
            f"; runs server-side code in the package sandbox — handlers: {names}"
            + ("; may reach the network (server-network declared)"
               if backend_card["network"] else "")
        )
    proposal_id = uuid.uuid4().hex
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="package.draft.apply",
        summary=summary,
        preview=preview_line,
        pins={"artifactDigest": result.artifact_digest, "target": request.target},
    )
    if backend_card is not None:
        part["backend"] = backend_card
    _store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "package.draft.apply",
            "mode": request.mode,
            "target": request.target,
            "packageName": manifest_name,
            "buildId": job.build_id,
            "artifactDigest": result.artifact_digest,
            "baseDigest": request.base_digest,
            "diff": diff,
            "policyFindings": list(result.policy_findings),
            "preview": result.preview,
            # dev/91: full backend provenance (probe rows, scan findings)
            # persists with the proposal for reload and the apply record.
            "backend": result.backend,
            "requestedNodes": [n.to_payload() for n in request.nodes],
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return (
        "proposed",
        f"proposal {proposal_id} created: {summary.lower()} (artifact "
        f"{result.artifact_digest[:12]}…). It awaits the user's explicit review "
        "of the diff, dependencies, and preview — do NOT claim the package or "
        "its nodes exist until the user applies it",
        part,
    )


# Plan layout (dev/52): topological columns right of the existing extent.
_PLAN_COLUMN_OFFSET = 420
_PLAN_ROW_OFFSET = 240


def _plan_depths(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """Longest-path depth per plan ref (plans are small DAGs; a cycle — which
    the grammar allows structurally — degrades to BFS-capped depths, never an
    infinite loop)."""
    refs = [n["ref"] for n in nodes]
    incoming: dict[str, list[str]] = {r: [] for r in refs}
    for e in edges:
        # dev/59: endpoints may name EXISTING nodes — only plan-local wiring
        # contributes to layout depth (existing nodes keep their positions).
        if e["to"] in incoming and e["from"] in incoming:
            incoming[e["to"]].append(e["from"])
    depths: dict[str, int] = {}

    def depth_of(ref: str, seen: frozenset) -> int:
        if ref in depths:
            return depths[ref]
        if ref in seen:
            return 0  # cycle guard
        parents = incoming.get(ref, [])
        d = 0 if not parents else 1 + max(depth_of(p, seen | {ref}) for p in parents)
        depths[ref] = d
        return d

    for r in refs:
        depth_of(r, frozenset())
    return depths


def _apply_dataflow_plan(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/52 apply, extended by dev/59 revisions: atomically remove the
    plan's listed victims (+ their edge cascade) and insert the new graph.

    Revision safety both ways: the pinned shape digest (node-id + edge-id
    sets) catches structural drift, and every removal victim is pinned by its
    content at mint (DEC-049.1) — editing a doomed node between mint and
    apply 409s + ``stale`` naming it, so user work never dies to a stale
    review. Templates re-validated; server-minted ids for every new node; the
    apply touches ONLY listed elements — unlisted nodes keep their ids,
    positions, and content by construction."""
    import hashlib

    from utk_curio.backend.app.packages import services as packages_services

    plan = proposal.get("plan") or {}
    if _graph_shape_digest(spec) != proposal.get("baseGraphDigest"):
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            "the canvas changed since this plan was proposed — ask the agent to replan",
        )
    # DEC-049.1: per-victim content digests.
    remove_nodes = plan.get("removeNodes", [])
    victim_pins = proposal.get("removeContentSha256") or {}
    spec_nodes_by_id = {
        n.get("id"): n
        for n in (spec.get("dataflow") or {}).get("nodes") or []
        if isinstance(n, dict)
    }
    for node_id in remove_nodes:
        victim = spec_nodes_by_id.get(node_id)
        current = hashlib.sha256(
            ((victim or {}).get("content") or "").encode("utf-8")
        ).hexdigest()
        if victim is None or current != victim_pins.get(node_id):
            label = ((victim or {}).get("goal") or node_id)[:60]
            raise _mark_stale(
                user_key, project_id, proposal_id, spec, proposal, session_id,
                f"the node you were about to remove changed ({label}) — "
                "ask the agent to replan",
            )
    try:
        available = {t["id"] for t in packages_services.available_templates(user_key, project_id)}
    except Exception as exc:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the node template registry is unavailable: {exc}",
        ) from exc
    # Canonicalised comparison, stored value untouched — see the per-node
    # apply above for why (dev/93 D3, in-flight proposals keep their digest).
    missing = [
        n["nodeType"] for n in plan.get("nodes", [])
        if packages_services.canonical_template_id(n["nodeType"]) not in available
    ]
    if missing:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"plan node type(s) no longer available: {', '.join(sorted(set(missing)))} — "
            "ask the agent to replan",
        )
    dataflow = spec.setdefault("dataflow", {})
    nodes = dataflow.setdefault("nodes", [])
    edges = dataflow.setdefault("edges", [])
    # Removals first (dev/59): listed edges + the recomputed cascade of edges
    # incident to removed nodes, then the victims themselves — in place, so
    # unlisted elements are untouched by construction.
    remove_node_set = set(remove_nodes)
    removed_edge_ids = set(plan.get("removeEdges", []))
    for e in edges:
        if isinstance(e, dict) and (
            e.get("source") in remove_node_set or e.get("target") in remove_node_set
        ):
            removed_edge_ids.add(str(e.get("id")))
    if removed_edge_ids:
        edges[:] = [e for e in edges if str(e.get("id")) not in removed_edge_ids]
    if remove_node_set:
        nodes[:] = [n for n in nodes if n.get("id") not in remove_node_set]
        # Agent attachments on removed nodes die with them, exactly as manual
        # canvas deletion (dev/32).
        attachments.prune_orphaned_attachments(spec)
    xs = [n.get("x") for n in nodes if isinstance(n, dict) and isinstance(n.get("x"), (int, float))]
    ys = [n.get("y") for n in nodes if isinstance(n, dict) and isinstance(n.get("y"), (int, float))]
    base_x = (max(xs) + _PLAN_COLUMN_OFFSET) if xs else 80.0
    base_y = min(ys) if ys else 80.0
    depths = _plan_depths(plan.get("nodes", []), plan.get("edges", []))
    rows: dict[int, int] = {}
    # dev/67-5: the mint-time layout + review-stage overlays; refs already
    # applied per-node are REAL nodes — skipped here, their ids seed the edge
    # resolution so mixed per-node/whole-plan flows wire correctly.
    positions = proposal.get("positions") or {}
    edited_goals = proposal.get("editedGoals") or {}
    already_applied = set(proposal.get("appliedRefs") or [])
    ref_to_id: dict[str, str] = dict(proposal.get("appliedNodeIds") or {})
    created_nodes: list[dict] = []
    for plan_node in plan.get("nodes", []):
        depth = depths.get(plan_node["ref"], 0)
        row = rows.get(depth, 0)
        rows[depth] = row + 1
        if plan_node["ref"] in already_applied:
            continue
        node_id = str(uuid.uuid4())
        ref_to_id[plan_node["ref"]] = node_id
        pos = positions.get(plan_node["ref"]) or {}
        created = {
            "id": node_id,
            "type": plan_node["nodeType"],
            "content": plan_node.get("content", ""),
            "goal": edited_goals.get(plan_node["ref"])
            or f"{plan_node['title']} — {plan_node['intent']}",
            "x": float(pos.get("x", base_x + depth * _PLAN_COLUMN_OFFSET)),
            "y": float(pos.get("y", base_y + row * _PLAN_ROW_OFFSET)),
        }
        nodes.append(created)
        created_nodes.append(created)
    # dev/67-3 (DEC-051): handles are explicit end-to-end. Merge targets get a
    # deterministic free in_N slot (a named free toHandle wins; occupied or
    # unnamed falls to the lowest free) — the bridge passes these through
    # instead of hardcoding "in", which left merge slots unfilled until a
    # reload healed them.
    types_by_id = {
        n.get("id"): _strip_type_version(str(n.get("type") or ""))
        for n in nodes
        if isinstance(n, dict)
    }
    merge_slots_taken: dict[str, set[str]] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        if types_by_id.get(e.get("target")) == _MERGE_NODE_TYPE:
            handle = e.get("targetHandle")
            if isinstance(handle, str):
                merge_slots_taken.setdefault(e.get("target"), set()).add(handle)
    created_edges: list[dict] = []
    for plan_edge in plan.get("edges", []):
        # dev/59: endpoints resolve through the ref map ∪ existing ids.
        source = ref_to_id.get(plan_edge["from"], plan_edge["from"])
        target = ref_to_id.get(plan_edge["to"], plan_edge["to"])
        target_handle = plan_edge.get("toHandle") or "in"
        if types_by_id.get(target) == _MERGE_NODE_TYPE:
            taken = merge_slots_taken.setdefault(target, set())
            wanted = plan_edge.get("toHandle")
            if isinstance(wanted, str) and _MERGE_HANDLE_RE.match(wanted) and wanted not in taken:
                target_handle = wanted
            else:
                target_handle = next(
                    (f"in_{i}" for i in range(5) if f"in_{i}" not in taken), None
                )
                if target_handle is None:
                    label = ((spec_nodes_by_id.get(target) or {}).get("goal") or target)[:60]
                    raise _mark_stale(
                        user_key, project_id, proposal_id, spec, proposal, session_id,
                        f"merge node {label!r} has no free input slot — "
                        "ask the agent to replan",
                    )
            taken.add(target_handle)
        edge = {
            "id": str(uuid.uuid4()),
            "source": source,
            "target": target,
            "sourceHandle": "out",
            "targetHandle": target_handle,
        }
        edges.append(edge)
        created_edges.append(edge)
    proposal["status"] = "applied"
    # The builder session (DR-2, merged per dev/59): removed victims leave
    # nodeRuns; surviving prior entries persist; new pending nodes join.
    record = attachments.get_attachment(spec, attachment_id)
    prior_runs = (
        (record.get("builderSession") or {}).get("nodeRuns") or {} if record else {}
    )
    node_runs = {
        node_id: status
        for node_id, status in prior_runs.items()
        if node_id not in remove_node_set
    }
    node_runs.update(
        {n["id"]: "pending" for n in created_nodes if not (n.get("content") or "").strip()}
    )
    unresolved = any(s in ("pending", "failed") for s in node_runs.values())
    if record is not None:
        record["builderSession"] = {
            "phase": "applied" if unresolved else "ready",
            "appliedPlanId": proposal_id,
            "nodeRuns": node_runs,
            # dev/67-5: the whole-plan apply completes every ref's ledger row.
            "nodeStates": {ref: "created" for ref in ref_to_id},
            "nodeIds": dict(ref_to_id),
        }
    projects_storage.write_spec(user_key, project_id, spec)
    removed_summary = (
        f", removed {len(remove_node_set)} node{'s' if len(remove_node_set) != 1 else ''}"
        if remove_node_set or removed_edge_ids
        else ""
    )
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: plan added {len(created_nodes)} nodes and "
        f"{len(created_edges)} connections{removed_summary}.",
        "Applied: dataflow plan",
        [
            f"+{len(created_nodes)} nodes · +{len(created_edges)} connections"
            + (f" · −{len(remove_node_set)} nodes" if remove_node_set else ""),
            f"{sum(1 for s in node_runs.values() if s == 'pending')} pending for Solve",
            f"proposal {proposal_id[:8]}",
        ],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        # Consumed by the frontend bridge (dev/52; removals per dev/59).
        "appliedGraph": {
            "nodes": created_nodes,
            "edges": created_edges,
            "removedNodeIds": sorted(remove_node_set),
            "removedEdgeIds": sorted(removed_edge_ids),
        },
        "builderSession": record.get("builderSession") if record else None,
    }


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
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
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


def _apply_package_install(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/84 apply: the EXISTING package install flow (user-store copy +
    dep provisioning + per-project lockfile — all the packages service's own
    semantics under its spec lock). The frontend shows the package install
    dialog BEFORE posting this apply; the dialog is the review surface, this
    endpoint is the authority — conflicts and catalog absence are re-checked
    here regardless and are the drift analogue: 409 + ``stale``."""
    from utk_curio.backend.app.packages import services as packages_services

    dir_name = proposal.get("dirName", "")
    try:
        report = packages_services.agent_resolve_report(user_key, [dir_name])
    except packages_services.PackageServiceError as exc:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the package is no longer installable ({exc}) — ask the agent to search again",
        ) from exc
    if report["conflicts"]:
        named = ", ".join(sorted({c["package"] for c in report["conflicts"]}))
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"installing would conflict with this project's packages ({named}) — "
            "resolve the conflict in the Nodes Catalog first",
        )
    try:
        packages_services.install_to_project(user_key, project_id, dir_name)
    except Exception as exc:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the package could not be installed: {exc}",
        ) from exc
    # The install wrote the spec (the package lockfile); re-read so the
    # proposal mirror update below does not clobber the new entry.
    spec = _read_spec_or_404(user_key, project_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
    proposal["status"] = "applied"
    projects_storage.write_spec(user_key, project_id, spec)
    name = str(proposal.get("packageName") or dir_name)
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: package installed ({name}).",
        "Applied: package installed",
        [name, dir_name, f"proposal {proposal_id[:8]}"],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "installedPackage": {"dirName": dir_name, "name": name},
    }


def _apply_package_draft(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/89 apply: promote the EXACT reviewed artifact digest through
    the promotion coordinator (verify-on-read, stale/collision protection,
    backup + journal, lockfile after install), then insert the requested
    nodes server-side with their normalized appearance.

    Ordering (dev/89 §3.10): install → lockfile → nodes in the SPEC; the
    apply response carries ``requiresRegistryRefresh`` so the frontend
    refreshes the package/behavior/template registries BEFORE painting the
    created nodes on the live canvas (registry-before-canvas). The backend
    confirms the promotion journal once the spec write lands — the spec is
    the source of truth the registries load from. A node-insertion failure
    compensates through the coordinator's rollback, and the outcome
    (rolled-back vs rollback-failed) rides the stale message honestly.
    """
    from utk_curio.backend.app.packages import build_promotion
    from utk_curio.backend.app.packages.manifest import ManifestError, load_packageage_manifest
    from utk_curio.backend.app.packages.storage import PackageId, package_dir as _package_dir

    target = str(proposal.get("target") or "")
    artifact_digest = str(proposal.get("artifactDigest") or "")
    base_digest = proposal.get("baseDigest")
    try:
        journal = build_promotion.promote(
            user_key,
            target=target,
            artifact_digest=artifact_digest,
            base_digest=base_digest if isinstance(base_digest, str) else None,
            project_id=project_id,
        )
    except build_promotion.PromotionError as exc:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the reviewed build can no longer be applied: {exc} — ask the "
            "agent to rebuild the draft",
        ) from exc

    # The promotion wrote the spec (project lockfile); re-read so the node
    # insertions and proposal mirror below never clobber it.
    spec = _read_spec_or_404(user_key, project_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal

    try:
        installed_manifest = load_packageage_manifest(_package_dir(user_key, target))
        installed_templates = {t.template_id for t in installed_manifest.templates}
        coord = PackageId.parse_dir(target)
        created_nodes: list[dict] = []
        for node in proposal.get("requestedNodes") or []:
            template_id = str(node.get("templateId") or "")
            if template_id not in installed_templates:
                raise AgentServiceError(
                    f"requested node targets template {template_id!r}, which the "
                    f"installed package does not declare", 409,
                )
            created = _insert_node(
                spec,
                coord.canonical(template_id),
                str(node.get("content") or ""),
                node.get("goal"),
                appearance=node.get("appearance"),
                title=node.get("title"),
            )
            created_nodes.append(created)
        proposal["status"] = "applied"
        projects_storage.write_spec(user_key, project_id, spec)
    except Exception as exc:
        rolled = build_promotion.rollback(
            user_key, artifact_digest, f"node insertion failed: {exc}")
        raise _mark_stale(
            user_key, project_id, proposal_id,
            _read_spec_or_404(user_key, project_id),
            attachments.find_proposal(spec, attachment_id, proposal_id) or proposal,
            session_id,
            f"the package installed but its nodes could not be created ({exc}); "
            f"the prior state was {rolled['rollback']['status']} — ask the agent "
            "to rebuild",
        ) from exc

    # Activation from the backend's view: the spec (which the registries load
    # from) now carries the lockfile entry and the nodes. The frontend still
    # refreshes its registries before painting (requiresRegistryRefresh).
    build_promotion.confirm_registry_ready(user_key, artifact_digest)
    build_promotion.confirm_nodes_created(user_key, artifact_digest)

    name = str(proposal.get("packageName") or target)
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: package {name} built and installed"
        + (f"; {len(created_nodes)} node(s) created." if created_nodes else "."),
        "Applied: package draft installed",
        [name, target, f"proposal {proposal_id[:8]}"],
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "installedPackage": {"dirName": target, "name": name,
                             "replaced": bool(journal.get("backupHeld"))},
        # Consumed by the frontend canvas bridge — registry refresh happens
        # BEFORE these nodes are painted (dev/89 registry-before-canvas).
        "createdNodes": created_nodes,
        "requiresRegistryRefresh": True,
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
        proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
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


def _insert_node(
    spec: dict,
    node_type: str,
    node_content: str,
    goal: str | None,
    *,
    appearance: dict | None = None,
    title: str | None = None,
) -> dict:
    """Append one server-minted node to the spec's dataflow (dev/48): fresh
    uuid id (collision-impossible, never from any param), placed right of the
    current node extent. The caller writes the spec.

    ``appearance`` (dev/89, additive) is already normalized by the shared
    node-appearance utility and persists at the canonical
    ``metadata.appearance.backgroundColor`` shape; callers that omit it stay
    byte-for-byte identical.
    """
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
    if title:
        created["title"] = title
    if appearance:
        created["metadata"] = {"appearance": dict(appearance)}
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
    created = _insert_node(
        spec, node_type, proposal.get("content", ""), proposal.get("goal"),
        appearance=proposal.get("appearance"),  # dev/89: typed round-trip
    )
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
    # dev/90 A16: a queued same-reply sibling is dismissible by id too.
    attachments.reconcile_proposal_queue(spec, attachment_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id)
    if proposal is None:
        raise AgentServiceError(f"proposal {proposal_id!r} not found", 404)
    if proposal.get("status") != "pending":
        raise AgentServiceError(
            f"this proposal is {proposal.get('status')!r} and can no longer be dismissed", 409
        )
    proposal["status"] = "dismissed"
    attachments.reconcile_proposal_queue(spec, attachment_id)
    # A dismissed plan review returns the builder session to its prior phase
    # (dev/52 DR-2): applied when an earlier plan landed, else idle.
    if proposal.get("tool") == "dataflow.plan.write":
        session = record.get("builderSession") or {}
        session["phase"] = "applied" if session.get("appliedPlanId") else "idle"
        session.pop("planProposalId", None)
        record["builderSession"] = session
    projects_storage.write_spec(user_key, project_id, spec)
    session_id = record.get("sessionId")
    if isinstance(session_id, str):
        sessions.update_proposal_status(
            user_key, project_id, session_id, proposal_id, "dismissed"
        )
    return {"attachmentId": attachment_id, "proposalId": proposal_id, "status": "dismissed"}


# Solve concurrency (dev/52, DEC-048): the dev/15 manifest's
# maxParallelChildren — a runtime constant until policy demands tuning.
_SOLVE_MAX_WORKERS = 3
# A hard-crashed solve leaves the transient "solving" phase behind; a marker
# older than this is treated as stale so the user is never wedged.
_SOLVE_STALE_SECONDS = 15 * 60
# In-flight cancellation (dev/63): solve executionId → stop event. The
# in-process fast path; the persisted ``cancelRequested`` session flag is the
# durable signal (other workers, a lost registry entry).
_SOLVE_CANCEL_EVENTS: dict[str, object] = {}


def solve_attachment(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    node_ids: list[str] | None = None,
) -> dict:
    """The dev/52 Solve batch (DEC-048), blocking form: drains the streaming
    batch (dev/63 — one implementation) and returns its terminal payload,
    minus the stream-only keys, so the response is byte-compatible. Always
    write mode — propose mode (dev/67-6) is the streaming route's."""
    payload: dict | None = None
    for kind, data in solve_attachment_stream(
        user_key, project_id, attachment_id, config, node_ids
    ):
        if kind == "done":
            payload = dict(data)
    if payload is None:  # the stream ended without a terminal event — loud
        raise AgentServiceError("solve ended without a result", 500)
    payload.pop("cancelled", None)
    payload.pop("notAttempted", None)
    payload.pop("mode", None)
    return payload


def request_solve_cancel(user_key: str, project_id: str, attachment_id: str) -> dict:
    """User-initiated solve cancellation (dev/63, the DEC-021 user slice).

    Sets BOTH signals: the persisted ``cancelRequested`` flag (durable —
    honored by any worker at the next node boundary) and the in-process stop
    event (immediate). In-flight children are never aborted; undispatched
    targets revert to ``pending``. Idempotent while a solve runs; 409 when
    nothing is running.
    """
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    session = record.get("builderSession") or {}
    if session.get("phase") != "solving":
        raise AgentServiceError("no solve is running for this attachment", 409)
    session["cancelRequested"] = True
    projects_storage.write_spec(user_key, project_id, spec)
    event = _SOLVE_CANCEL_EVENTS.get(str(session.get("solveExecutionId") or ""))
    if event is not None:
        event.set()  # type: ignore[attr-defined]
    return {"attachmentId": attachment_id, "cancelRequested": True}


def solve_attachment_stream(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    node_ids: list[str] | None = None,
    mode: str = "write",
):
    """The dev/52 Solve batch (DEC-048) as an event stream (dev/63): ONE
    explicit, authenticated user action authorizes filling the applied plan's
    pending nodes.

    The endpoint is the review: it is scoped to plan-created placeholder
    nodes (the builder session's ``nodeRuns``) and digest-guarded per node
    (only still-empty content is written — user edits are ``skipped``,
    never overwritten). Each node runs a depth-1 child under
    ``delegation.run_delegate`` with every dev/48 guarantee (own ledger pair
    under the child's policy, ``parentExecutionId``, failure isolation) —
    coordinated by a bounded worker pool. The endpoint itself consumes no
    quota; children reserve individually. Retry = the same endpoint with the
    failed subset.

    Validation is eager (409s stay JSON); the returned generator yields
    ``(kind, payload)``: ``solve_started`` → ``node_started`` /
    ``node_result`` per target → ``done``. The terminal state comes from ONE
    re-guarded spec write that also runs on client disconnect and
    cancellation — streamed events are transport, never truth.

    ``mode`` (dev/67-6): ``"write"`` — the classic DEC-048 batch, content
    written under the per-node digest guard; ``"propose"`` — each solved
    child MINTS a reviewed ``node.content.write`` proposal instead (the
    Simulation Mode solve stage): nothing is written, ``node_result`` carries
    the ``proposalId``, the node stays ``pending`` until the user applies,
    and the session returns to its pre-solve phase. The single-activeProposal
    model means a multi-node propose batch supersedes all but the last —
    the 67-9 sequence solves one node at a time by design.
    """
    import threading
    import time as _time

    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    session = record.get("builderSession") or {}
    if not session.get("appliedPlanId"):
        raise AgentServiceError("nothing to solve — apply a plan first", 409)
    now = _time.time()
    if session.get("phase") == "solving" and now - float(session.get("solvingSince") or 0) < _SOLVE_STALE_SECONDS:
        raise AgentServiceError("a solve is already running for this plan", 409)
    node_runs: dict = session.get("nodeRuns") or {}
    targets = [
        node_id
        for node_id, status in node_runs.items()
        if status in ("pending", "failed") and (node_ids is None or node_id in node_ids)
    ]
    if not targets:
        raise AgentServiceError("no pending or failed plan nodes to solve", 409)
    if mode not in ("write", "propose"):
        raise AgentServiceError("mode must be 'write' or 'propose'", 422)
    return_phase = session.get("phase")  # propose mode restores it (dev/67-6)
    nodes_by_id = {
        n.get("id"): n
        for n in (spec.get("dataflow") or {}).get("nodes") or []
        if isinstance(n, dict)
    }
    solve_execution_id = uuid.uuid4().hex
    # The in-flight guard + cancellation identity persist before any provider
    # work; the cancel endpoint finds the run through ``solveExecutionId``.
    session["phase"] = "solving"
    session["solvingSince"] = now
    session["solveExecutionId"] = solve_execution_id
    session.pop("cancelRequested", None)
    projects_storage.write_spec(user_key, project_id, spec)
    stop = threading.Event()
    _SOLVE_CANCEL_EVENTS[solve_execution_id] = stop
    manifest = _resolve_definition(user_key, record.get("coord", ""))
    coord = record.get("coord", "")
    session_id = record.get("sessionId")
    return _solve_events(
        user_key, project_id, attachment_id, config, targets, nodes_by_id,
        manifest, coord, session_id, solve_execution_id, stop,
        spec=spec, mode=mode, return_phase=return_phase,
    )


def _solve_events(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    targets: list[str],
    nodes_by_id: dict,
    manifest: AgentManifest | None,
    coord: str,
    session_id,
    solve_execution_id: str,
    stop,
    *,
    spec: dict | None = None,
    mode: str = "write",
    return_phase: str | None = None,
):
    """The solve batch body (dev/63). Workers report through a thread-safe
    queue — they never touch the response; the generator drains it between
    yields. ``_finish`` is the single idempotent persist + transcript card,
    reached from normal completion, cancellation, client disconnect
    (``GeneratorExit``), and unexpected errors alike."""
    import queue as _queue
    from concurrent.futures import ThreadPoolExecutor

    results: dict[str, dict] = {}
    applied_contents: list[dict] = []
    delegations: list = []
    unstarted: list[str] = []
    started = time.monotonic()
    state = {"finished": False}
    payload_out: dict = {}

    def _flag_requested() -> bool:
        # The durable cancel signal, read lazily at node boundaries only.
        try:
            flag_spec = _read_spec_or_404(user_key, project_id)
            flag_record = _record_or_404(flag_spec, attachment_id)
            return bool((flag_record.get("builderSession") or {}).get("cancelRequested"))
        except Exception:
            return False

    def _should_stop() -> bool:
        if stop.is_set():
            return True
        if _flag_requested():
            stop.set()
            return True
        return False

    def _record_outcome(node_id: str, status: str, text, child) -> dict | None:
        """Fold one worker outcome into the batch state — no yields, so it is
        safe on the disconnect drain. Returns the node_result payload, or
        None for an unstarted (cancelled-before-dispatch) target, which stays
        ``pending`` — it was never attempted, so no new status enters the
        state machine."""
        if child is not None:
            delegations.append(child)
        if status == "solved":
            # The child replies with response formatting around the code —
            # only the executable content is written (dev/57).
            text_out = content.extract_node_content(text)
            results[node_id] = {"status": "solved"}
            applied_contents.append({"nodeId": node_id, "content": text_out})
            return {"nodeId": node_id, "status": "solved", "content": text_out}
        if status == "failed":
            err = (text or "")[:300]
            results[node_id] = {"status": "failed", "error": err}
            return {"nodeId": node_id, "status": "failed", "error": err}
        if status == "skipped":
            results[node_id] = {"status": "skipped"}
            return {"nodeId": node_id, "status": "skipped"}
        unstarted.append(node_id)
        return None

    def _finish() -> dict:
        # One batched spec write: contents (re-guarded against the CURRENT
        # spec under the read-modify-write), statuses, and the exit phase —
        # plus the transcript card. Idempotent: exactly one persist per batch.
        if state["finished"]:
            return payload_out
        state["finished"] = True
        cancelled = stop.is_set()
        spec = _read_spec_or_404(user_key, project_id)
        record = _record_or_404(spec, attachment_id)
        session = record.get("builderSession") or {}
        node_runs = session.get("nodeRuns") or {}
        current_nodes = {
            n.get("id"): n
            for n in (spec.get("dataflow") or {}).get("nodes") or []
            if isinstance(n, dict)
        }
        for item in applied_contents:
            node = current_nodes.get(item["nodeId"])
            if node is None:
                results[item["nodeId"]] = {"status": "skipped"}  # deleted meanwhile
                continue
            if (node.get("content") or "").strip():
                results[item["nodeId"]] = {"status": "skipped"}  # user edit wins
                continue
            node["content"] = item["content"]
        applied = [
            i for i in applied_contents if results.get(i["nodeId"], {}).get("status") == "solved"
        ]
        ids_to_ref = {
            nid: ref for ref, nid in (session.get("nodeIds") or {}).items()
        }
        node_states = session.get("nodeStates")
        for node_id, outcome in results.items():
            if outcome["status"] == "proposed":
                # dev/67-6: nothing was written — the node stays pending
                # until the user applies the content proposal; the plan row
                # advances to "solving" (a review awaits).
                ref = ids_to_ref.get(node_id)
                if node_states is not None and ref is not None:
                    node_states[ref] = "solving"
                continue
            if node_id in node_runs:
                node_runs[node_id] = outcome["status"] if outcome["status"] != "skipped" else "skipped"
        session["nodeRuns"] = node_runs
        session.pop("solvingSince", None)
        session.pop("solveExecutionId", None)
        session.pop("cancelRequested", None)
        if mode == "propose" and return_phase not in (None, "", "solving"):
            # The propose batch resolved nothing — the session returns to the
            # phase the solve interrupted (typically "simulating").
            session["phase"] = return_phase
        else:
            session["phase"] = (
                "ready"
                if all(s not in ("pending", "failed") for s in node_runs.values())
                else "applied"
            )
        record["builderSession"] = session
        projects_storage.write_spec(user_key, project_id, spec)
        solved = sum(1 for r in results.values() if r["status"] == "solved")
        proposed = sum(1 for r in results.values() if r["status"] == "proposed")
        if isinstance(session_id, str):
            lines = [
                f"{node_id[:8]} · {outcome['status']}"
                for node_id, outcome in list(results.items())[:10]
            ]
            if cancelled:
                lines.append(f"cancelled — {len(unstarted)} node(s) not attempted")
            sessions.append_turns(
                user_key, project_id, session_id, attachment_id,
                [
                    sessions.make_turn(
                        "agent",
                        (
                            f"Proposed content for {proposed} of {len(targets)} plan nodes."
                            if mode == "propose"
                            else f"Solved {solved} of {len(targets)} plan nodes."
                        )
                        + (f" Cancelled — {len(unstarted)} not attempted." if cancelled else ""),
                        content=[{
                            "type": "card",
                            "kind": "result",
                            "title": f"Solve: {solved} of {len(targets)} nodes",
                            "lines": lines,
                        }],
                        execution=_execution_record(
                            solve_execution_id,
                            {"coord": coord, "provider": config.api_type,
                             "model": config.model, "tools": [], "intentEdited": False},
                            {}, started, "ok", delegations=delegations,
                        ),
                    )
                ],
            )
        payload_out.update({
            "attachmentId": attachment_id,
            "executionId": solve_execution_id,
            "results": results,
            "appliedContents": applied,
            "builderSession": session,
            "cancelled": cancelled,
            "notAttempted": sorted(unstarted),
            "mode": mode,
        })
        return payload_out

    try:
        yield "solve_started", {"executionId": solve_execution_id, "targets": list(targets)}
        resolution = delegation.resolve(
            user_key, project_id, manifest, "node.content.generate"
        ) if manifest is not None else delegation.Resolution("unresolvable")
        if resolution.outcome != "ok":
            # Missing specialist: ONE reviewed install proposal (not per node),
            # every target failed — the panel explains and Retry works after
            # the user applies the install (REQ-ORCH-001).
            if resolution.outcome == "not-installed":
                loop_ctx = {
                    "attachment_id": attachment_id,
                    "session_id": session_id,
                }
                status, text, part = _mint_project_install(
                    user_key, project_id, loop_ctx,
                    resolution.coord,
                    resolution.manifest.name if resolution.manifest else resolution.coord,
                    "node.content.generate",
                )
                reason = "specialist not installed — an install proposal awaits review"
            else:
                reason = "no installed agent declares node.content.generate"
            for node_id in targets:
                results[node_id] = {"status": "failed", "error": reason}
                yield "node_result", {"nodeId": node_id, "status": "failed", "error": reason}
        else:
            goals = [
                str(nodes_by_id[t].get("goal") or "") for t in targets if t in nodes_by_id
            ]
            outcome_queue: _queue.Queue = _queue.Queue()

            def _solve_one(node_id: str) -> None:
                try:
                    if _should_stop():
                        outcome_queue.put((node_id, "unstarted", None, None))
                        return
                    outcome_queue.put((node_id, "started", None, None))
                    node = nodes_by_id.get(node_id)
                    if node is None:
                        outcome_queue.put((node_id, "skipped", None, None))
                        return
                    if (node.get("content") or "").strip():
                        # User content preserved.
                        outcome_queue.put((node_id, "skipped", None, None))
                        return
                    # dev/67-6: the ONE context composer — the child sees the
                    # node's neighborhood (goals, runtime status, datasets),
                    # not just its own intent.
                    inputs = {
                        "nodeType": node.get("type"),
                        "intent": node.get("goal"),
                        "planSiblings": goals[:20],
                        "nodeContext": node_context.compose_node_context(
                            user_key, project_id, spec, node_id
                        ),
                    }
                    status, text, child, _home = _run_delegate_traced(
                        user_key, project_id, resolution.coord,
                        "node.content.generate", inputs, config,
                        parent_execution_id=solve_execution_id,
                        parent_coord=coord,
                        attachment_id=attachment_id,
                        node_id=node_id,
                        home_create=False,  # workers never write the spec
                    )
                    outcome_queue.put(
                        (node_id, "solved" if status == "ok" else "failed", text, child)
                    )
                except BaseException as exc:  # a lost item would deadlock the drain
                    outcome_queue.put((node_id, "failed", f"solve worker error: {exc}", None))

            pool = ThreadPoolExecutor(max_workers=_SOLVE_MAX_WORKERS)
            try:
                for target in targets:
                    pool.submit(_solve_one, target)
                remaining = len(targets)
                while remaining:
                    node_id, status, text, child = outcome_queue.get()
                    if status == "started":
                        yield "node_started", {"nodeId": node_id}
                        continue
                    remaining -= 1
                    if mode == "propose" and status == "solved":
                        # dev/67-6 (Simulation Mode: solve): nothing is
                        # written — the child's content mints a reviewed
                        # node.content.write proposal through the EXISTING
                        # machinery (digest-pinned against the current
                        # content). dev/72: the review lives with the node's
                        # agent when one exists (find-only — the drain never
                        # writes the spec beyond the mint's own write).
                        if child is not None:
                            delegations.append(child)
                        # dev/73: the shared content→review sequence (also the
                        # chat loops' — one mint policy, three callers).
                        part, home_att, mint_text = _mint_content_review_from_delegate(
                            user_key, project_id,
                            node_id=node_id,
                            generated_text=text,
                            parent_attachment_id=attachment_id,
                            parent_session_id=session_id,
                            local_turn=True,
                        )
                        if part is not None:
                            results[node_id] = {
                                "status": "proposed",
                                "proposalId": part["proposalId"],
                                "proposalAttachmentId": home_att,
                            }
                            node = nodes_by_id.get(node_id) or {}
                            node_label = (node.get('goal') or node_id)[:60]
                            if home_att != attachment_id and isinstance(session_id, str):
                                sessions.append_turns(
                                    user_key, project_id, session_id, attachment_id,
                                    [sessions.make_turn(
                                        "agent",
                                        f"Proposed content for {node_label!r} — "
                                        "the review lives in the node's Node Builder.",
                                        content=[content.make_delegation_part(
                                            capability="node.content.generate",
                                            coord="agent.node-builder",
                                            name="Node Builder",
                                            category="node",
                                            attachment_id=home_att,
                                            status="ok",
                                            summary=f"content proposed for {node_label!r}",
                                        )],
                                    )],
                                )
                            yield "node_result", {
                                "nodeId": node_id,
                                "status": "proposed",
                                "proposalId": part["proposalId"],
                                "proposalAttachmentId": home_att,
                            }
                        else:
                            results[node_id] = {
                                "status": "failed", "error": mint_text[:300]
                            }
                            yield "node_result", {
                                "nodeId": node_id, "status": "failed",
                                "error": mint_text[:300],
                            }
                        continue
                    event = _record_outcome(node_id, status, text, child)
                    if event is not None:
                        yield "node_result", event
            except GeneratorExit:
                # Client gone (dev/63): stop dispatch, let in-flight children
                # finish, fold their results in WITHOUT yielding — the finally
                # persist keeps everything that completed.
                stop.set()
                pool.shutdown(wait=True)
                while not outcome_queue.empty():
                    node_id, status, text, child = outcome_queue.get_nowait()
                    if status != "started":
                        _record_outcome(node_id, status, text, child)
                raise
            finally:
                pool.shutdown(wait=True)
        yield "done", _finish()
    finally:
        _SOLVE_CANCEL_EVENTS.pop(solve_execution_id, None)
        _finish()


# dev/67-9 (DEC-054): the Simulation Mode driver — one transition function,
# step and auto cannot diverge; every state persists before it is emitted.
_SIMULATE_STALE_SECONDS = 15 * 60
_SIMULATE_CANCEL_EVENTS: dict[str, object] = {}
# An auto run is bounded by construction: every action either advances one
# ref's state machine or pauses — this cap is a runaway backstop only.
_SIMULATE_MAX_ACTIONS = 500


def _ordered_plan_refs(plan: dict) -> list[str]:
    """Plan refs in topological order (mint's depth math), stable within a
    level by plan order — upstream validates before downstream generates."""
    depths = _plan_depths(plan.get("nodes", []), plan.get("edges", []))
    return [
        n["ref"]
        for n in sorted(
            plan.get("nodes", []),
            key=lambda n: depths.get(n["ref"], 0),
        )
    ]


def _next_simulation_action(plan: dict, proposal: dict, session: dict) -> dict | None:
    """THE transition function (step and auto share it): the next single
    action for the persisted state, or None when the plan is complete.

    Per ref, in topological order: planned → create; created/failed →
    validate (a failed ref re-validates on resume — the pause happened when
    it FIRST failed); validated → approve (apply its content proposal);
    solving → pause (a content review outside the driver's own loop awaits);
    approved → next ref. All refs approved → connect (the edges stage; with
    zero edges it simply completes the proposal)."""
    node_states = session.get("nodeStates") or {}
    for ref in _ordered_plan_refs(plan):
        state = node_states.get(ref, "planned")
        if state == "planned":
            return {"action": "create", "ref": ref}
        if state in ("created", "failed"):
            return {"action": "validate", "ref": ref}
        if state == "validated":
            return {"action": "approve", "ref": ref}
        if state == "solving":
            return {"action": "await-review", "ref": ref}
        # "approved" → continue to the next ref.
    if proposal.get("status") == "pending":
        return {"action": "connect"}
    return None


def request_simulate_cancel(user_key: str, project_id: str, attachment_id: str) -> dict:
    """Cancel a running simulation (dev/67-9): both dev/63 signals — the
    durable session flag plus the in-process event; the run stops at the next
    action boundary with everything already done persisted."""
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    session = record.get("builderSession") or {}
    if not session.get("simulatingSince"):
        raise AgentServiceError("no simulation is running for this attachment", 409)
    session["simulateCancelRequested"] = True
    projects_storage.write_spec(user_key, project_id, spec)
    event = _SIMULATE_CANCEL_EVENTS.get(str(session.get("simulateExecutionId") or ""))
    if event is not None:
        event.set()  # type: ignore[attr-defined]
    return {"attachmentId": attachment_id, "cancelRequested": True}


def simulate_stream(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    *,
    mode: str = "step",
    exec_fn=None,
):
    """The Simulation Mode driver (memo dev/67-9, DEC-054).

    ``step`` performs exactly the NEXT action and returns; ``auto`` (the
    re-targeted Apply Plan) chains the same actions — create → validate →
    auto-approve on PASS — per node in topological order, then the connection
    stage, PAUSING on any failure with the reason and the pending review
    (nothing downstream of a failure is generated). Every transition persists
    to ``builderSession`` BEFORE it is emitted, so a reload resumes exactly;
    resume = calling this endpoint again.
    """
    import threading
    import time as _time

    if mode not in ("step", "auto"):
        raise AgentServiceError("mode must be 'step' or 'auto'", 422)
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    session = record.get("builderSession") or {}
    plan_proposal_id = session.get("planProposalId")
    if not isinstance(plan_proposal_id, str):
        raise AgentServiceError("no plan to simulate — ask for a plan first", 409)
    proposal = _plan_proposal_any(spec, attachment_id, plan_proposal_id)
    if proposal is None:
        raise AgentServiceError("the plan is no longer available — nothing to simulate", 409)
    if proposal.get("status") not in ("pending", "applied"):
        raise AgentServiceError(
            f"the plan is {proposal.get('status')!r} — nothing to simulate", 409
        )
    if _next_simulation_action(proposal.get("plan") or {}, proposal, session) is None:
        raise AgentServiceError(
            "the plan is complete — nothing to simulate", 409
        )
    now = _time.time()
    if session.get("simulatingSince") and now - float(session.get("simulatingSince") or 0) < _SIMULATE_STALE_SECONDS:
        raise AgentServiceError("a simulation is already running for this attachment", 409)
    simulate_execution_id = uuid.uuid4().hex
    session["simulatingSince"] = now
    session["simulateExecutionId"] = simulate_execution_id
    session.pop("simulateCancelRequested", None)
    session.pop("pauseReason", None)
    record["builderSession"] = session
    projects_storage.write_spec(user_key, project_id, spec)
    stop = threading.Event()
    _SIMULATE_CANCEL_EVENTS[simulate_execution_id] = stop
    return _simulate_events(
        user_key, project_id, attachment_id, config, plan_proposal_id,
        simulate_execution_id, mode, stop, exec_fn,
    )


def _simulate_events(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    plan_proposal_id: str,
    simulate_execution_id: str,
    mode: str,
    stop,
    exec_fn,
):
    """The driver body: read fresh state → one action → persist → emit —
    repeated in auto until completion, a pause, or cancellation. Canvas
    mutations ride the stream (``node_created`` / ``node_content_applied`` /
    ``edges_created``) so the frontend applies them live."""

    def _fresh():
        spec = _read_spec_or_404(user_key, project_id)
        record = _record_or_404(spec, attachment_id)
        session = record.get("builderSession") or {}
        # dev/71: the plan stays readable after its structure completes —
        # validate/approve actions continue on the applied plan.
        proposal = _plan_proposal_any(spec, attachment_id, plan_proposal_id)
        return spec, record, session, proposal

    def _persist_pause(reason: dict):
        spec, record, session, _ = _fresh()
        session["pauseReason"] = reason
        session.pop("currentRef", None)
        record["builderSession"] = session
        projects_storage.write_spec(user_key, project_id, spec)
        return session

    def _set_current(ref: str | None):
        spec, record, session, _ = _fresh()
        if ref is None:
            session.pop("currentRef", None)
        else:
            session["currentRef"] = ref
        record["builderSession"] = session
        projects_storage.write_spec(user_key, project_id, spec)

    def _cancelled() -> bool:
        if stop.is_set():
            return True
        _, _, session, _ = _fresh()
        if session.get("simulateCancelRequested"):
            stop.set()
            return True
        return False

    done: dict = {"status": "completed", "mode": mode}
    try:
        yield "simulate_started", {
            "executionId": simulate_execution_id, "mode": mode,
        }
        for _ in range(_SIMULATE_MAX_ACTIONS):
            if _cancelled():
                done = {"status": "cancelled", "mode": mode}
                break
            spec, record, session, proposal = _fresh()
            if proposal is None:
                done = {"status": "completed", "mode": mode}
                break
            plan = proposal.get("plan") or {}
            action = _next_simulation_action(plan, proposal, session)
            if action is None:
                done = {"status": "completed", "mode": mode}
                break
            ref = action.get("ref")
            yield "stage", {**action, "label": _plan_endpoint_label(ref, plan, {}) if ref else None}
            if action["action"] == "await-review":
                session = _persist_pause({
                    "kind": "content-review-pending", "ref": ref,
                    "message": "review the pending content proposal first, then continue",
                })
                done = {"status": "paused", "mode": mode, "reason": session["pauseReason"]}
                break
            _set_current(ref)
            if action["action"] == "create":
                result = apply_plan_node(
                    user_key, project_id, attachment_id, plan_proposal_id, ref
                )
                if result.get("createdNode"):
                    yield "node_created", {"createdNode": result["createdNode"]}
                if result.get("createdEdges"):
                    # dev/71: the progressive sweep connected what it could.
                    yield "edges_created", {"createdEdges": result["createdEdges"]}
                yield "action_result", {"action": "create", "ref": ref, "outcome": "created"}
            elif action["action"] == "validate":
                validate_done: dict | None = None
                for kind, payload in _validate_node_inline(
                    user_key, project_id, attachment_id, config, ref, exec_fn
                ):
                    if kind == "done":
                        validate_done = payload
                    else:
                        yield kind, payload
                verdict = (validate_done or {}).get("verdict", "fail")
                proposal_id = (validate_done or {}).get("proposalId")
                if proposal_id:
                    # The resume/apply linkage (67-6's deferred nodeProposals;
                    # dev/72: the proposal may live on the node's agent).
                    spec2, record2, session2, _ = _fresh()
                    session2.setdefault("nodeProposals", {})[ref] = {
                        "proposalId": proposal_id,
                        "attachmentId": (validate_done or {}).get("proposalAttachmentId")
                        or attachment_id,
                    }
                    record2["builderSession"] = session2
                    projects_storage.write_spec(user_key, project_id, spec2)
                yield "action_result", {
                    "action": "validate", "ref": ref, "outcome": verdict,
                    **({"proposalId": proposal_id} if proposal_id else {}),
                }
                if verdict == "infrastructure":
                    session = _persist_pause({
                        "kind": "infrastructure", "ref": ref,
                        "message": (validate_done or {}).get("evidence", {}).get("detail")
                        or "the sandbox is unreachable — retry when it is back",
                    })
                    done = {"status": "paused", "mode": mode, "reason": session["pauseReason"]}
                    break
                if verdict == "fail":
                    session = _persist_pause({
                        "kind": "validation-failed", "ref": ref,
                        "proposalId": proposal_id,
                        "message": "validation failed — review the proposed content "
                        "(Apply anyway or edit), then continue",
                    })
                    done = {"status": "paused", "mode": mode, "reason": session["pauseReason"]}
                    break
            elif action["action"] == "approve":
                _, _, session, _ = _fresh()
                entry = (session.get("nodeProposals") or {}).get(ref)
                # dev/72 shape {proposalId, attachmentId}; old string tolerated.
                if isinstance(entry, dict):
                    content_proposal_id = entry.get("proposalId")
                    proposal_attachment_id = entry.get("attachmentId") or attachment_id
                else:
                    content_proposal_id = entry
                    proposal_attachment_id = attachment_id
                if not content_proposal_id:
                    session = _persist_pause({
                        "kind": "content-review-pending", "ref": ref,
                        "message": "the validated proposal is not addressable — review it manually",
                    })
                    done = {"status": "paused", "mode": mode, "reason": session["pauseReason"]}
                    break
                apply_result = apply_proposal(
                    user_key, project_id, proposal_attachment_id, content_proposal_id
                )
                # DEC-054: auto-approval is recorded, never silent.
                spec3, _, _, _ = _fresh()
                approved = attachments.get_active_proposal(spec3, proposal_attachment_id)
                if approved is not None and approved.get("proposalId") == content_proposal_id:
                    approved["approvedBy"] = "simulation-auto"
                    projects_storage.write_spec(user_key, project_id, spec3)
                applied_content = apply_result.get("appliedContent")
                if applied_content:
                    yield "node_content_applied", applied_content
                yield "action_result", {"action": "approve", "ref": ref, "outcome": "approved"}
            elif action["action"] == "connect":
                edges_result = apply_plan_edges(
                    user_key, project_id, attachment_id, plan_proposal_id, None
                )
                if edges_result.get("createdEdges"):
                    yield "edges_created", {"createdEdges": edges_result["createdEdges"]}
                refused = {
                    idx: row for idx, row in (edges_result.get("results") or {}).items()
                    if row.get("status") == "refused"
                }
                yield "action_result", {
                    "action": "connect",
                    "outcome": "refused" if refused else "connected",
                    "refused": {i: r.get("reason") for i, r in refused.items()},
                }
                if refused:
                    session = _persist_pause({
                        "kind": "connection-refused",
                        "message": "; ".join(
                            f"{r.get('fromLabel')} → {r.get('toLabel')}: {r.get('reason')}"
                            for r in list(refused.values())[:3]
                        ),
                    })
                    done = {"status": "paused", "mode": mode, "reason": session["pauseReason"]}
                    break
            if mode == "step":
                spec4, _, session4, proposal4 = _fresh()
                next_action = (
                    _next_simulation_action(
                        (proposal4 or {}).get("plan") or {}, proposal4 or {}, session4
                    )
                    if proposal4 is not None  # dev/71: content work continues
                    else None                  # on the completed structure
                )
                done = {"status": "stepped", "mode": mode, "nextAction": next_action}
                break
        else:
            done = {"status": "paused", "mode": mode,
                    "reason": {"kind": "action-cap", "message": "action cap reached"}}
    finally:
        _SIMULATE_CANCEL_EVENTS.pop(simulate_execution_id, None)
        try:
            spec, record, session, _ = _fresh()
            session.pop("simulatingSince", None)
            session.pop("simulateExecutionId", None)
            session.pop("simulateCancelRequested", None)
            session.pop("currentRef", None)
            record["builderSession"] = session
            projects_storage.write_spec(user_key, project_id, spec)
        except Exception:
            pass
    _, _, final_session, _ = _fresh()
    done["builderSession"] = final_session
    yield "done", done


def _pending_plan_proposal_or_none(spec: dict, attachment_id: str, proposal_id: str):
    """The pending plan proposal (active or parked) or None — the driver's
    loop guard (completion is an outcome, not an error)."""
    try:
        return _pending_plan_proposal(spec, attachment_id, proposal_id)
    except AgentServiceError:
        return None


def _plan_proposal_any(spec: dict, attachment_id: str, proposal_id: str):
    """The plan proposal in ANY status (active or parked) — dev/71: the
    structure may complete (status applied) while content work continues;
    the driver and per-row lifecycle still need the plan."""
    proposal = attachments.get_active_proposal(spec, attachment_id)
    if isinstance(proposal, dict) and proposal.get("proposalId") == proposal_id:
        return proposal
    record = attachments.get_attachment(spec, attachment_id)
    parked = (record or {}).get("planProposal")
    if isinstance(parked, dict) and parked.get("proposalId") == proposal_id:
        return parked
    return None


def _validate_node_inline(
    user_key: str, project_id: str, attachment_id: str, config: ProviderConfig,
    ref: str, exec_fn,
):
    """The 67-7 validation loop, driven inline by the simulator — its
    ``done`` payload is consumed (transformed into an ``action_result``),
    everything else re-yields verbatim."""
    yield from validate_node_stream(
        user_key, project_id, attachment_id, config, ref=ref, exec_fn=exec_fn
    )


def run_node_stream(
    user_key: str,
    project_id: str,
    attachment_id: str,
    *,
    ref: str | None = None,
    node_id: str | None = None,
    exec_fn=None,
):
    """Run the dataflow THROUGH one node (memo dev/71): the 67-7 runner
    WITHOUT a candidate — the SAVED content executes through its upstream
    chain, every execution journals as a REAL run (``validation: false``), and
    the outcome (outputs, schema metadata, logs, warnings, errors) lands in
    the runtime journal where the Node Builder, debug agent, and explainer
    read it (67-2 ``node.runtime.read``). The saved spec is never mutated.

    Streams ``run_started`` → ``node_executed`` per upstream execution →
    ``done {ok, nodes, blocker, error}``; a result card joins the transcript.
    """
    import time as _time

    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    session = record.get("builderSession") or {}
    if ref and not node_id:
        node_id = (session.get("nodeIds") or {}).get(ref)
        if not node_id:
            raise AgentServiceError(f"ref {ref!r} has no created node yet", 409)
    if not node_id:
        raise AgentServiceError("a ref or nodeId is required", 422)
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    if node is None:
        raise AgentServiceError(f"node {node_id!r} not found in the saved spec", 404)
    now = _time.time()
    if session.get("runningSince") and now - float(session.get("runningSince") or 0) < _VALIDATE_STALE_SECONDS:
        raise AgentServiceError("a run is already in progress for this attachment", 409)
    session["runningSince"] = now
    record["builderSession"] = session
    projects_storage.write_spec(user_key, project_id, spec)
    session_id = record.get("sessionId")
    return _run_node_events(
        user_key, project_id, attachment_id, spec, node, session_id, exec_fn
    )


def _run_node_events(
    user_key: str,
    project_id: str,
    attachment_id: str,
    spec: dict,
    node: dict,
    session_id,
    exec_fn,
):
    """The run-node body: a threaded runner drains a queue so upstream
    executions stream live (the dev/63 pattern); the finally clears the
    in-flight guard on every exit, disconnect included."""
    import queue as _queue
    import threading

    from utk_curio.backend.app.execution import runner

    node_id = node.get("id")
    execution_id = uuid.uuid4().hex
    try:
        yield "run_started", {"nodeId": node_id, "executionId": execution_id}
        progress_queue: _queue.Queue = _queue.Queue()

        def _run():
            try:
                report = runner.run_through_node(
                    user_key, project_id, spec, node_id,
                    candidate_content=None,
                    exec_fn=exec_fn,
                    as_validation=False,  # a REAL run, journaled as one
                    progress=lambda nid, i, total: progress_queue.put(
                        ("progress", nid, i, total)
                    ),
                )
            except Exception as exc:  # the runner must never kill the stream
                report = {
                    "ok": False, "target": node_id, "order": [], "nodes": {},
                    "blocker": None, "infrastructure": str(exc)[:300],
                    "error": f"run failed: {str(exc)[:300]}",
                }
            progress_queue.put(("done", report))

        thread = threading.Thread(target=_run)
        thread.start()
        report: dict = {}
        while True:
            item = progress_queue.get()
            if item[0] == "progress":
                _, nid, index, total = item
                yield "node_executed", {"nodeId": nid, "index": index, "total": total}
                continue
            report = item[1]
            break
        thread.join(timeout=5)
        target_record = (report.get("nodes") or {}).get(node_id) or {}
        label = (node.get("goal") or node_id)[:60]
        if isinstance(session_id, str):
            if report.get("ok"):
                lines = [
                    f"{label} · ok",
                    f"output: {(target_record.get('output') or {}).get('dataType') or '?'}",
                    f"{len(report.get('order') or [])} node(s) in the chain",
                ]
                if target_record.get("stderrTail"):
                    lines.append("warnings captured — see node.runtime.read")
                text = f"Ran through {label!r}: ok."
            else:
                blocker = report.get("blocker")
                failed_record = (report.get("nodes") or {}).get(blocker) or {}
                lines = [
                    f"{label} · failed",
                    (report.get("error") or "")[:300],
                ]
                tail = failed_record.get("stderrTail") or ""
                if tail:
                    lines.append(tail[-300:])
                text = f"Ran through {label!r}: FAILED — {report.get('error')}"
            sessions.append_turns(
                user_key, project_id, session_id, attachment_id,
                [sessions.make_turn(
                    "agent", text,
                    content=[{
                        "type": "card", "kind": "result",
                        "title": "Run through node", "lines": lines[:10],
                    }],
                )],
            )
        yield "done", {
            "nodeId": node_id,
            "executionId": execution_id,
            "ok": bool(report.get("ok")),
            "order": report.get("order") or [],
            "nodes": report.get("nodes") or {},
            "blocker": report.get("blocker"),
            "error": report.get("error"),
        }
    finally:
        # Disconnect-safe: the in-flight guard never wedges the attachment.
        try:
            cleanup_spec = _read_spec_or_404(user_key, project_id)
            cleanup_record = _record_or_404(cleanup_spec, attachment_id)
            cleanup_session = cleanup_record.get("builderSession") or {}
            if cleanup_session.pop("runningSince", None) is not None:
                cleanup_record["builderSession"] = cleanup_session
                projects_storage.write_spec(user_key, project_id, cleanup_spec)
        except Exception:
            pass


# dev/67-7: bounded self-correction — initial generation + up to 2 corrective
# regenerations, each re-validated by actually running the dataflow.
_VALIDATE_CORRECTION_ROUNDS = 2
_VALIDATE_STALE_SECONDS = 15 * 60


def validate_node_stream(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    *,
    ref: str | None = None,
    node_id: str | None = None,
    exec_fn=None,
):
    """Generate → execute-through → validate → self-correct → propose, for
    ONE node (memo dev/67-7 — Simulation Mode: validate).

    Eager validation (409s stay JSON); the returned generator yields
    ``validation_started`` → per round: ``generation_round`` →
    ``node_executed`` per upstream execution → ``round_verdict`` → … →
    ``done {verdict, evidence, rounds, proposalId?, builderSession}``.
    The saved spec is never mutated: the candidate runs as an overlay and
    lands as a reviewed ``node.content.write`` proposal carrying the
    validation block — PASS or FAIL, the user decides ("Apply anyway" is a
    labeled choice, never a hidden one). An ``infrastructure`` verdict mints
    nothing and leaves the node's state untouched.
    """
    import time as _time

    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    session = record.get("builderSession") or {}
    if ref and not node_id:
        node_id = (session.get("nodeIds") or {}).get(ref)
        if not node_id:
            raise AgentServiceError(f"ref {ref!r} has no created node yet", 409)
    if not node_id:
        raise AgentServiceError("a ref or nodeId is required", 422)
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    if node is None:
        raise AgentServiceError(f"node {node_id!r} not found in the saved spec", 404)
    now = _time.time()
    if session.get("validatingSince") and now - float(session.get("validatingSince") or 0) < _VALIDATE_STALE_SECONDS:
        raise AgentServiceError("a validation is already running for this attachment", 409)
    manifest = _resolve_definition(user_key, record.get("coord", ""))
    resolution = delegation.resolve(
        user_key, project_id, manifest, "node.content.generate"
    ) if manifest is not None else delegation.Resolution("unresolvable")
    if resolution.outcome != "ok":
        raise AgentServiceError(
            "no installed agent declares node.content.generate — install the "
            "Node Content Builder first",
            409,
        )
    session_id = record.get("sessionId")
    coord = record.get("coord", "")
    if ref is None:
        ref = next(
            (r for r, nid in (session.get("nodeIds") or {}).items() if nid == node_id),
            None,
        )
    # dev/72: the node's Node Builder attachment is the Solve trace's home —
    # the content review and the consolidated trace live with the agent
    # responsible for THIS node (best-effort created; fallback: parent-only).
    home, _created = _delegation_home(
        spec, "agent.node-builder", "node.content.generate", {},
        node_id=node_id, create=True,
    )
    home_attachment_id = (home or {}).get("attachmentId")
    home_session_id = (home or {}).get("sessionId")
    session["validatingSince"] = now
    record["builderSession"] = session
    projects_storage.write_spec(user_key, project_id, spec)
    return _validate_events(
        user_key, project_id, attachment_id, config, spec, node, ref,
        resolution, coord, session_id, exec_fn,
        home_attachment_id=home_attachment_id,
        home_session_id=home_session_id,
    )


def _validate_events(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    spec: dict,
    node: dict,
    ref: str | None,
    resolution,
    coord: str,
    session_id,
    exec_fn,
    *,
    home_attachment_id: str | None = None,
    home_session_id: str | None = None,
):
    """The validate-node body: threaded validation runs drain a queue so
    upstream executions stream live (the dev/63 pattern); the finally clears
    the in-flight guard on every exit, disconnect included."""
    import queue as _queue
    import threading

    from utk_curio.backend.app.agents import validation
    from utk_curio.backend.app.packages import services as packages_services

    node_id = node.get("id")
    execution_id = uuid.uuid4().hex
    verdict_result: dict | None = None
    rounds_used = 0
    candidate = ""
    delegations: list = []
    rounds_trace: list[str] = []  # dev/72: the consolidated per-round story
    label = (node.get("goal") or node_id)[:60]
    if isinstance(home_session_id, str):
        try:
            sessions.append_turns(
                user_key, project_id, home_session_id, home_attachment_id,
                [sessions.make_turn(
                    "user",
                    f"[Delegated by Dataflow Builder] Solve {label!r}: generate, "
                    "execute through the dataflow, validate, self-correct.",
                )],
            )
        except Exception:
            pass
    try:
        yield "validation_started", {"nodeId": node_id, "executionId": execution_id}
        try:
            available = {
                t["id"]: t
                for t in packages_services.available_templates(user_key, project_id)
            }
        except Exception:
            available = None  # arity metadata unavailable: type check fails open
        previous_attempt: str | None = None
        previous_error: str | None = None
        for round_index in range(1 + _VALIDATE_CORRECTION_ROUNDS):
            rounds_used = round_index + 1
            yield "generation_round", {"round": rounds_used}
            inputs = {
                "nodeType": node.get("type"),
                "intent": node.get("goal"),
                "nodeContext": node_context.compose_node_context(
                    user_key, project_id, spec, node_id
                ),
            }
            if previous_attempt is not None:
                # The NCB instruction's self-correction contract: fix
                # precisely the failure, grounded in the real traceback.
                inputs["previousAttempt"] = previous_attempt[:6000]
                inputs["validationError"] = (previous_error or "")[:2000]
            status, text, child = delegation.run_delegate(
                user_key, project_id, resolution.coord,
                "node.content.generate", inputs, config,
                parent_execution_id=execution_id,
                parent_coord=coord,
                attachment_id=attachment_id,
            )
            delegations.append(child)
            if status != "ok":
                verdict_result = {
                    "verdict": "fail",
                    "evidence": {"kind": "generation-error", "detail": (text or "")[:300]},
                }
                break
            candidate = content.extract_node_content(text)
            progress_queue: _queue.Queue = _queue.Queue()

            def _run_validation():
                try:
                    result = validation.validate_candidate(
                        user_key, project_id, spec, node_id, candidate,
                        exec_fn=exec_fn,
                        available_templates=available,
                        progress=lambda nid, i, total: progress_queue.put(
                            ("progress", nid, i, total)
                        ),
                    )
                except Exception as exc:  # the validator must never kill the stream
                    result = {
                        "verdict": "infrastructure",
                        "evidence": {"kind": "infrastructure", "detail": str(exc)[:300]},
                    }
                progress_queue.put(("done", result))

            thread = threading.Thread(target=_run_validation)
            thread.start()
            while True:
                item = progress_queue.get()
                if item[0] == "progress":
                    _, nid, index, total = item
                    yield "node_executed", {"nodeId": nid, "index": index, "total": total}
                    continue
                verdict_result = item[1]
                break
            thread.join(timeout=5)
            yield "round_verdict", {
                "round": rounds_used, "verdict": verdict_result["verdict"],
            }
            round_evidence = (verdict_result.get("evidence") or {})
            rounds_trace.append(
                f"round {rounds_used}: {verdict_result['verdict']}"
                + (
                    f" — {(round_evidence.get('stderrTail') or round_evidence.get('detail') or '')[-160:]}"
                    if verdict_result["verdict"] != "pass"
                    else f" — output {round_evidence.get('outputDataType') or '?'}"
                )
            )
            if verdict_result["verdict"] != "fail":
                break
            previous_attempt = candidate
            evidence = verdict_result.get("evidence") or {}
            previous_error = evidence.get("stderrTail") or evidence.get("detail") or ""
        done: dict = {
            "verdict": verdict_result["verdict"] if verdict_result else "fail",
            "evidence": (verdict_result or {}).get("evidence") or {},
            "rounds": rounds_used,
            "nodeId": node_id,
        }
        if done["verdict"] in ("pass", "fail") and candidate:
            # PASS or FAIL, the user decides — the proposal carries the
            # validation block so the review is informed, never gatekept.
            # dev/72: the review lives with the NODE's agent when it exists —
            # per-node proposals stop contending for the builder's one slot.
            mint_attachment = home_attachment_id or attachment_id
            mint_session = home_session_id or session_id
            p_status, p_error, part = _mint_node_content_write(
                user_key, project_id,
                {"attachment_id": mint_attachment, "session_id": mint_session},
                {"tool": "node.content.write",
                 "params": {"nodeId": node_id, "content": candidate}},
            )
            if part is not None:
                part["validation"] = {
                    "verdict": done["verdict"],
                    "rounds": rounds_used,
                    "evidence": done["evidence"],
                }
                done["proposalId"] = part["proposalId"]
                done["proposalAttachmentId"] = mint_attachment
                trace_card = {
                    "type": "card",
                    "kind": "result" if done["verdict"] == "pass" else "error",
                    "title": f"Solve trace · {done['verdict'].upper()}",
                    "lines": (
                        [f"dependencies executed: {len(done['evidence'].get('executedNodes') or [])} node(s)"]
                        + rounds_trace
                        + [f"outcome: {done['verdict']} after {rounds_used} round{'s' if rounds_used != 1 else ''}"]
                    )[:10],
                }
                if isinstance(mint_session, str):
                    sessions.append_turns(
                        user_key, project_id, mint_session, mint_attachment,
                        [sessions.make_turn(
                            "agent",
                            f"Validated content for {label!r}: "
                            f"{done['verdict'].upper()} after {rounds_used} "
                            f"round{'s' if rounds_used != 1 else ''} — review below.",
                            content=[trace_card, part],
                        )],
                    )
                if (
                    home_attachment_id
                    and home_attachment_id != attachment_id
                    and isinstance(session_id, str)
                ):
                    # The parent references and LINKS; the story lives at home.
                    sessions.append_turns(
                        user_key, project_id, session_id, attachment_id,
                        [sessions.make_turn(
                            "agent",
                            f"Solved {label!r}: {done['verdict'].upper()} after "
                            f"{rounds_used} round{'s' if rounds_used != 1 else ''} — "
                            "the trace and content review live in the node's "
                            "Node Builder.",
                            content=[content.make_delegation_part(
                                capability="node.content.generate",
                                coord="agent.node-builder",
                                name="Node Builder",
                                category="node",
                                attachment_id=home_attachment_id,
                                status="ok" if done["verdict"] == "pass" else "failed",
                                summary=f"Solve {label!r}: {done['verdict']} "
                                f"({rounds_used} round{'s' if rounds_used != 1 else ''})",
                            )],
                        )],
                    )
            else:
                done["evidence"] = {
                    **done["evidence"],
                    "mintError": (p_error or "")[:300],
                }
        # The per-node ledger: validated / failed; infrastructure untouched.
        fresh = _read_spec_or_404(user_key, project_id)
        fresh_record = _record_or_404(fresh, attachment_id)
        fresh_session = fresh_record.get("builderSession") or {}
        if ref and isinstance(fresh_session.get("nodeStates"), dict):
            if done["verdict"] == "pass":
                fresh_session["nodeStates"][ref] = "validated"
            elif done["verdict"] == "fail":
                fresh_session["nodeStates"][ref] = "failed"
        fresh_session.pop("validatingSince", None)
        fresh_record["builderSession"] = fresh_session
        projects_storage.write_spec(user_key, project_id, fresh)
        done["builderSession"] = fresh_session
        yield "done", done
    finally:
        # Disconnect-safe: the in-flight guard never wedges the attachment.
        try:
            cleanup_spec = _read_spec_or_404(user_key, project_id)
            cleanup_record = _record_or_404(cleanup_spec, attachment_id)
            cleanup_session = cleanup_record.get("builderSession") or {}
            if cleanup_session.pop("validatingSince", None) is not None:
                cleanup_record["builderSession"] = cleanup_session
                projects_storage.write_spec(user_key, project_id, cleanup_spec)
        except Exception:
            pass


def _resolve_prompt_text(user_key: str, coord: str, name: str) -> str | None:
    """A definition's prompt asset text (``"instruction"`` or ``"system"``).

    **Built-in trust follows the ROSTER bytes** (dev/60) — the same rule
    ``_resolve_definition`` applies to metadata, for the same reason: an
    updated built-in prompt must take effect for existing installs (the store
    copy is a materialization cache, not an authority). Owned/imported
    definitions — including deliberate shadows of a built-in coordinate —
    run from their own on-disk bytes, store copy first, then the published
    catalog.
    """
    m = storage.load_installed_agent_definition(user_key, coord)
    base = storage.agent_definition_dir(user_key, coord) if m is not None else None
    if m is None:
        m = publications.get_published_manifest(coord)
        base = publications.published_agent_dir(coord) if m is not None else None
    if m is not None and m.provenance.trust == "built-in":
        roster = builtin.read_prompt_text(coord, name)
        if roster is not None:
            return roster
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
    # Reuse-first (dev/48; plans too, dev/52): a grant that can put a template
    # on the canvas, into the project, or author a new one carries the live
    # template roster, composed fresh per run from the packages registry — the
    # prompt bytes never bake in template ids, and the model is never left to
    # guess. dev/93 commit 4 widened this from node.create/dataflow.plan.write
    # to package.install and package.draft.apply so it covers every agent that
    # declares the `installedTemplates` read, which let the duplicate
    # client-side roster be retired: an authoring agent especially needs to see
    # what already exists, since not seeing it is how one weather question
    # produced two near-identical note packages.
    if not _ROSTER_GRANTS.isdisjoint(granted):
        templates_block = _available_templates_block(user_key, project_id)
        if templates_block:
            system_content = f"{system_content}\n\n{templates_block}"
        # dev/93 D4: the second half of the roster — what the user owns but
        # this project has not enlisted — goes only to a run that can act on
        # it. Offering it without the grant would name a door the model
        # cannot open, which is how the Researcher ended up authoring a
        # duplicate package instead.
        if "package.install" in granted:
            enlistable = _enlistable_templates_block(
                user_key, project_id, _TEMPLATES_BLOCK_MAX_ENTRIES
            )
            if enlistable:
                system_content = f"{system_content}\n\n{enlistable}"
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

# The grants that earn the run-time template roster: putting a template on the
# canvas (node.create), planning one (dataflow.plan.write), enlisting a package
# that provides one (package.install), or authoring a new one
# (package.draft.apply). This set covers every built-in that declares the
# `installedTemplates` read, which is what let dev/93 commit 4 retire the
# duplicate client-composed roster — the one that spelled ids VERSIONED while
# this one spelled them unversioned, and listed palette templates the project
# could not actually instantiate.
_ROSTER_GRANTS = frozenset({
    "node.create", "dataflow.plan.write", "package.install", "package.draft.apply",
})


def _template_line(entry: dict, *, suffix: str = "") -> str:
    desc = (entry.get("description") or "")[:_TEMPLATES_BLOCK_DESC_CHARS]
    return f"- {entry['id']} — {entry['label']}" + (f": {desc}" if desc else "") + suffix


def _available_templates_block(user_key: str, project_id: str) -> str | None:
    """The grant-aware node-template listing appended to a node.create or
    dataflow.plan.write run's system content, composed from the
    packages-domain helpers so it is never stale (memo dev/48).

    Two sections, because one bucket could not express the difference that
    matters (memo dev/93 D4). "Available" is what this project can
    instantiate right now. "Installed but not enlisted" is what the user
    already owns and could enlist with one reviewed ``package.install`` —
    without it, a template the user has looks identical to a template that
    does not exist anywhere, and an agent told to reuse concludes "there is
    no installed notes template on your canvas" and authors a duplicate
    package. The second section is offered only to a run that can act on it
    (a ``package.install`` grant); everyone else sees the roster unchanged.
    """
    from utk_curio.backend.app.packages import services as packages_services

    try:
        templates = packages_services.available_templates(user_key, project_id)
    except Exception:  # a broken registry degrades to no listing, not a 500
        return None
    entries = [t for t in templates if t.get("authorable")]
    shown = entries[:_TEMPLATES_BLOCK_MAX_ENTRIES]
    if len(entries) > len(shown):
        log.warning(
            "Template roster truncated for project %s: %d of %d available "
            "templates listed",
            project_id, len(shown), len(entries),
        )
    if not shown:
        return None
    return (
        "Available node templates (a node.create nodeType or a plan nodeType "
        "MUST be one of these ids; the versioned form "
        "'<packageId>/<templateId>@<major>' is also accepted):\n"
        + "\n".join(_template_line(t) for t in shown)
    )


def _enlistable_templates_block(user_key: str, project_id: str, budget: int) -> str | None:
    """The "installed but not enlisted" half of the roster (memo dev/93 D4).

    Separate function, one shared line format: the sections are composed
    together but only this one is grant-gated, and it names the dirName the
    ``package.install`` proposal takes so the model never has to guess it.
    """
    from utk_curio.backend.app.packages import services as packages_services

    if budget <= 0:
        return None
    try:
        rows = packages_services.installed_templates_not_in_project(user_key, project_id)
    except Exception:  # same posture as the available half
        return None
    rows = [r for r in rows if r.get("authorable")]
    shown = rows[:budget]
    if len(rows) > len(shown):
        log.warning(
            "Enlistable roster truncated for project %s: %d of %d listed",
            project_id, len(shown), len(rows),
        )
    if not shown:
        return None
    lines = [
        _template_line(r, suffix=f" (package {r['dirName']})") for r in shown
    ]
    return (
        "Installed but NOT enlisted in this project — you already have these; "
        "propose package.install with the named package to use one, and do NOT "
        "author a duplicate package:\n" + "\n".join(lines)
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
# dev/73: 3 — the Node Builder's documented modify flow (read the node →
# delegate generation → propose) is a three-round sequence; 2 forced models
# that follow their instructions to answer in prose instead of proposing.
MAX_TOOL_ROUNDS = 3

# The mutate tools _mint_proposal dispatches (dev/73): a request for one of
# these dangling at the round cap is a cut-off PROPOSAL — surfaced as an
# error card, never silently dropped under the reply's confident prose.
MUTATE_PROPOSAL_TOOLS = frozenset({
    "node.content.write",
    "node.create",
    "node.template.create",
    "dataset.install",
    "package.install",  # dev/84
    "package.draft.apply",  # dev/89
    "dataflow.plan.write",
})


def _round_cap_cutoff_card(tool: str) -> dict:
    """The visible outcome of a mutate toolRequest dropped at the round cap."""
    return {
        "type": "card",
        "kind": "error",
        "title": "Proposal step cut off",
        "lines": [
            f"the run hit its tool-round limit before the {tool} proposal "
            "could be created — ask the agent to continue",
        ],
    }

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
    if tool == "package.install":
        return _mint_package_install(user_key, project_id, loop_ctx, req)
    if tool == "package.draft.apply":
        return _mint_package_draft_apply(user_key, project_id, loop_ctx, req)
    if tool == "dataflow.plan.write":
        return _mint_plan_from_params(user_key, project_id, loop_ctx, req)
    return "refused", f"no proposal flow exists for tool {tool!r}", None


def _mint_plan_from_params(
    user_key: str, project_id: str, loop_ctx: dict, req: dict
) -> tuple[str, str, dict | None]:
    """The plan's toolRequest form (dev/55): the grants paragraph teaches the
    generic toolRequest syntax, so the runtime honors it as a first-class
    equivalent of the dataflowPlan block. The payload is ``params.dataflowPlan``
    (the nested shape models produce) or ``params`` itself; validation errors
    return as the tool refusal — the existing tool-result round feeds them
    back, so an imperfect attempt self-corrects on the shared budget."""
    params = req.get("params") or {}
    raw = params.get("dataflowPlan", params)
    plan, errors = content.parse_dataflow_plan_verbose(raw)
    if errors:
        listed = "\n".join(f"- {e}" for e in errors[:10])
        return (
            "refused",
            "your dataflowPlan was invalid — fix exactly these problems and "
            f"resend the complete corrected request:\n{listed}",
            None,
        )
    return _mint_dataflow_plan(user_key, project_id, loop_ctx, plan)


def _store_proposal(
    user_key: str,
    project_id: str,
    spec: dict,
    loop_ctx: dict,
    proposal: dict,
    part: dict,
) -> None:
    """Shared proposal persistence (dev/41 semantics + dev/90 A16): a mint
    from a LATER reply supersedes every still-pending proposal in both places
    each lives (mirror/queue + transcript part) — but siblings minted in the
    SAME reply form one jointly-pending sequence: the first keeps the active
    slot, the rest queue behind it. Without the queue, a reply proposing a
    question note then an answer note silently killed the question — its
    card kept a live Apply button pointing at a dead proposal (the same-turn
    part was not yet persisted, so the supersede status never landed)."""
    attachment_id = loop_ctx["attachment_id"]
    session_id = loop_ctx["session_id"]
    # The mint sequence identity: one id per run loop, created lazily at the
    # first mint — solve/simulate children each carry their OWN loop_ctx, so
    # their one-at-a-time supersession (dev/67-9) is untouched.
    proposal["mintSequenceId"] = loop_ctx.setdefault("_mint_sequence_id", uuid.uuid4().hex)
    record = attachments.get_attachment(spec, attachment_id)
    attachments.reconcile_proposal_queue(spec, attachment_id)
    previous = attachments.get_active_proposal(spec, attachment_id)
    if previous is not None and previous.get("status") == "pending":
        if (
            previous.get("tool") == "dataflow.plan.write"
            and proposal.get("tool") != "dataflow.plan.write"
            and record is not None
        ):
            # dev/67-9: the plan PARKS while per-node content reviews occupy
            # the active slot — its per-node/edge stages stay addressable
            # (_pending_plan_proposal falls back to the parked slot); it is
            # never silently superseded by its own sequence.
            record["planProposal"] = previous
        elif (
            record is not None
            and previous.get("mintSequenceId") == proposal["mintSequenceId"]
        ):
            # dev/90 A16: same-reply sibling — jointly pending, applied or
            # dismissed by id in any order, promoted on reconcile.
            record.setdefault("queuedProposals", []).append(proposal)
            projects_storage.write_spec(user_key, project_id, spec)
            return
        else:
            sessions.update_proposal_status(
                user_key, project_id, session_id, previous.get("proposalId", ""), "superseded"
            )
            # A later reply supersedes the WHOLE previous sequence, queued
            # siblings included — their parts are persisted by now.
            for queued in attachments.get_queued_proposals(spec, attachment_id):
                if queued.get("status") == "pending":
                    queued["status"] = "superseded"
                    sessions.update_proposal_status(
                        user_key, project_id, session_id,
                        queued.get("proposalId", ""), "superseded",
                    )
            if record is not None:
                record.pop("queuedProposals", None)
    if proposal.get("tool") == "dataflow.plan.write" and record is not None:
        record.pop("planProposal", None)  # a new plan replaces any parked one
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
    proposed = content.extract_node_content(params.get("content"))
    if not proposed:
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
    """Resolve ``node_type`` for node.create against the packages-domain gate
    (dev/48 reuse-first: the agents module owns no template knowledge).

    Thin wrapper over ``resolve_template`` since dev/93 D3 — the versioned
    tolerance added here for dev/90 A14 lived ONLY here, which is why the plan
    path kept refusing ids the model was handed. One gate now serves both;
    node.create is the caller that needs authored content, so it is the one
    that asks for ``require_authorable``.
    Returns ``(entry | None, error_text)``."""
    from utk_curio.backend.app.packages import services as packages_services

    return packages_services.resolve_template(
        user_key, project_id, node_type, require_authorable=True
    )


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
    proposed = content.extract_node_content(params.get("content"))
    if not proposed:
        return "refused", "params.content must be a non-empty string", None
    if len(proposed) > content.PROPOSAL_CONTENT_MAX_CHARS:
        return "refused", "params.content exceeds the proposal size bound", None
    goal = params.get("goal")
    goal = goal.strip() if isinstance(goal, str) and goal.strip() else None
    # dev/89 (additive): optional appearance, normalized by the ONE shared
    # utility — an invalid or inaccessible color refuses at mint, loudly.
    from utk_curio.backend.app.packages import node_appearance

    try:
        appearance = node_appearance.normalize_appearance(params.get("appearance"))
    except node_appearance.AppearanceError as exc:
        return "refused", f"params.appearance: {exc}", None
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
    if appearance:
        proposal["appearance"] = appearance
    _store_proposal(user_key, project_id, spec, loop_ctx, proposal, part)
    return (
        "proposed",
        f"proposal {proposal_id} created for a new {entry['label']} node; it awaits "
        "the user's explicit review — do NOT assume it was applied",
        part,
    )


def _verify_candidate_parts(parts: list) -> None:
    """dev/67-4 (DEC-053): the Dataset Finder stops laundering — external
    candidate rows are verified DETERMINISTICALLY before they reach the user.
    URL-bearing rows are probed through the egress policy (first 4 — the
    run-budget shape; provider refinements like Socrata add dataset
    name/columns on top of the generic gate, which covers ANY dataset API);
    URL-less rows are loudly UNVERIFIED. The evidence rides the row into the
    card and the Node Builder handoff."""
    probed = 0
    for part in parts:
        if not isinstance(part, dict) or part.get("type") != "datasetCandidates":
            continue
        lanes = part.get("lanes") or {}
        for row in lanes.get("external") or []:
            if not isinstance(row, dict):
                continue
            url = row.get("url")
            if url and probed < egress.MAX_CALLS_PER_RUN:
                probed += 1
                row["verification"] = verify.verify_external_source(url)
            elif url:
                row["verification"] = {
                    "status": "unverified",
                    "detail": "the egress budget was spent before this row — not checked",
                }
            else:
                row["verification"] = verify.verify_external_source(None)


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
    elif tool_id in ("web.fetch", "web.search") and loop_ctx.get("egressCalls", 0) >= egress.MAX_CALLS_PER_RUN:
        # dev/67-4 (DEC-053): the per-run egress budget — verification, never
        # crawling. The refusal is data the model must surface honestly.
        status, text = "error", (
            f"the egress budget is exhausted ({egress.MAX_CALLS_PER_RUN} web "
            "calls per run) — report what you verified so far"
        )
    else:
        if tool_id in ("web.fetch", "web.search"):
            loop_ctx["egressCalls"] = loop_ctx.get("egressCalls", 0) + 1
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


def _delegation_home(
    spec: dict,
    coord: str,
    capability: str,
    inputs: dict,
    *,
    node_id: str | None = None,
    create: bool = True,
) -> tuple[dict | None, bool]:
    """Where a delegated task LIVES (memo dev/72): node-scoped work → the
    target node's Node Builder attachment (dev/71's; best-effort created);
    everything else → an existing attachment of the DELEGATE's agent id
    (canvas-scoped preferred), else a new canvas attachment of the resolved
    coord. Returns ``(record | None, created)`` — best-effort throughout: a
    missing home never fails a delegation."""
    target_node = node_id or (inputs or {}).get("nodeId")
    if isinstance(target_node, str) and target_node:
        for rec in attachments.list_attachments(spec):
            target = rec.get("target") or {}
            if (
                rec.get("coord", "").split("@", 1)[0] == "agent.node-builder"
                and target.get("kind") == "node"
                and target.get("targetId") == target_node
            ):
                return rec, False
        if create:
            att_id = _attach_node_builder(spec, target_node)
            if att_id:
                return attachments.get_attachment(spec, att_id), True
        return None, False
    agent_id = coord.split("@", 1)[0]
    fallback = None
    for rec in attachments.list_attachments(spec):
        if rec.get("coord", "").split("@", 1)[0] == agent_id:
            if (rec.get("target") or {}).get("kind") == "canvas":
                return rec, False
            fallback = fallback or rec
    if fallback is not None:
        return fallback, False
    if not create:
        return None, False
    try:
        rec = attachments.attach(
            spec, coord, {"kind": "canvas"},
            attachment_id=uuid.uuid4().hex, session_id=uuid.uuid4().hex,
        )
        return rec, True
    except Exception:
        return None, False


def _delegation_task_text(capability: str, inputs: dict) -> str:
    """A one-line task summary for the delegated agent's chat — the key
    intent, never the raw inputs dump."""
    parts = [capability]
    for key in ("intent", "question", "url", "endpoint", "nodeType"):
        value = (inputs or {}).get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}: {value.strip()[:160]}")
    return " · ".join(parts)[:480]


def _run_delegate_traced(
    user_key: str,
    project_id: str,
    coord: str,
    capability: str,
    inputs: dict,
    config: ProviderConfig,
    *,
    parent_execution_id: str,
    parent_coord: str,
    attachment_id: str | None,
    parent_name: str | None = None,
    node_id: str | None = None,
    home_create: bool = True,
) -> tuple[str, str, dict, str | None]:
    """One delegated task, TRACED (memo dev/72): the DEC-046 seam stays pure —
    this wrapper resolves the task's home attachment, writes the framed task
    turn, runs the child, writes the result turn (bounded reply + a
    structured trace card + the child's execution record), and returns the
    home id alongside the classic tuple. Exactly two turns per task; every
    trace step is best-effort — no delegation ever fails over it."""
    home_attachment_id: str | None = None
    home_session_id: str | None = None
    try:
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is not None:
            home, created = _delegation_home(
                spec, coord, capability, inputs, node_id=node_id, create=home_create
            )
            if home is not None:
                home_attachment_id = home.get("attachmentId")
                home_session_id = home.get("sessionId")
                if created:
                    projects_storage.write_spec(user_key, project_id, spec)
    except Exception:
        home_attachment_id = home_session_id = None
    parent_label = parent_name or parent_coord.split("@", 1)[0].replace("agent.", "")
    if isinstance(home_session_id, str):
        try:
            sessions.append_turns(
                user_key, project_id, home_session_id, home_attachment_id,
                [sessions.make_turn(
                    "user",
                    f"[Delegated by {parent_label}] "
                    f"{_delegation_task_text(capability, inputs)}",
                )],
            )
        except Exception:
            pass
    started = time.monotonic()
    status, text, child = delegation.run_delegate(
        user_key, project_id, coord, capability, inputs, config,
        parent_execution_id=parent_execution_id,
        parent_coord=parent_coord,
        attachment_id=attachment_id,
    )
    if isinstance(home_session_id, str):
        try:
            lines = [f"{capability} · {status}"]
            verification = (inputs or {}).get("verification")
            if isinstance(verification, dict):
                detail = verification.get("detail") or verification.get("datasetName") or ""
                lines.append(
                    f"runtime-verified: {verification.get('status')}"
                    + (f" — {detail}" if detail else "")
                )
            lines.append(f"{int((time.monotonic() - started) * 1000)} ms")
            sessions.append_turns(
                user_key, project_id, home_session_id, home_attachment_id,
                [sessions.make_turn(
                    "agent",
                    (text or "")[:2000],
                    error=status != "ok",
                    execution=child,
                    content=[{
                        "type": "card",
                        "kind": "result" if status == "ok" else "error",
                        "title": f"Delegated task · {status}",
                        "lines": [l[:300] for l in lines[:10]],
                    }],
                )],
            )
        except Exception:
            pass
    return status, text, child, home_attachment_id


def _delegation_part_for(resolution, capability: str, status: str, text: str, home_attachment_id: str | None) -> dict:
    manifest = getattr(resolution, "manifest", None)
    return content.make_delegation_part(
        capability=capability,
        coord=getattr(resolution, "coord", "") or "",
        name=getattr(manifest, "name", None) or getattr(resolution, "coord", "") or capability,
        category=getattr(manifest, "category", "") or "",
        attachment_id=home_attachment_id,
        status=status,
        summary=(text or "")[:200],
    )


def _delegate_target_node_id(loop_ctx: dict, inputs: dict) -> str | None:
    """The node a content-generation delegation targets: the model's
    ``nodeId`` input, else the parent attachment's node target — the same
    resolution ``_enriched_delegate_inputs`` grounds the child with."""
    node_id = (inputs or {}).get("nodeId")
    if isinstance(node_id, str) and node_id:
        return node_id
    target = loop_ctx.get("target")
    if isinstance(target, dict) and target.get("kind") == "node":
        target_id = target.get("targetId")
        if isinstance(target_id, str) and target_id:
            return target_id
    return None


def _mint_content_review_from_delegate(
    user_key: str,
    project_id: str,
    *,
    node_id: str,
    generated_text: str,
    parent_attachment_id,
    parent_session_id,
    local_turn: bool = False,
) -> tuple[dict | None, str | None, str]:
    """dev/73: the ONE content→review sequence (the Solve drain's, extracted):
    a successful ``node.content.generate`` delegation becomes a reviewed
    ``node.content.write`` proposal minted by the RUNTIME — applyability
    never depends on the model re-emitting the content as a second
    toolRequest.

    Mints at the dev/72 delegation home (the node's own agent) when one
    exists — find-only; the traced delegation already created it when it
    could — else at the parent attachment. The review turn is written at a
    foreign home (the parent's composed turn carries the part locally);
    ``local_turn=True`` (the Solve drain, which composes no parent parts)
    writes it unconditionally. Returns ``(proposal_part | None,
    home_attachment_id, text_for_model)`` — on failure the text is the
    honest refusal to feed back.
    """
    text_out = content.extract_node_content(generated_text)
    home_att, home_sess = parent_attachment_id, parent_session_id
    node_label = node_id
    try:
        fresh_spec = projects_storage.read_spec(user_key, project_id)
        home, _ = _delegation_home(
            fresh_spec or {}, "agent.node-builder", "node.content.generate", {},
            node_id=node_id, create=False,
        )
        if home is not None:
            home_att = home.get("attachmentId")
            home_sess = home.get("sessionId")
        for node in ((fresh_spec or {}).get("dataflow") or {}).get("nodes") or []:
            if isinstance(node, dict) and node.get("id") == node_id:
                node_label = (node.get("goal") or node_id)[:60]
                break
    except Exception:
        pass
    p_status, p_error, part = _mint_node_content_write(
        user_key, project_id,
        {"attachment_id": home_att, "session_id": home_sess},
        {"tool": "node.content.write",
         "params": {"nodeId": node_id, "content": text_out}},
    )
    if part is None:
        return None, home_att, (
            "the generated content could not become a reviewed proposal "
            f"({(p_error or 'unknown error')[:200]}) — report this honestly: "
            "nothing was changed and nothing awaits review"
        )
    if isinstance(home_sess, str) and (local_turn or home_att != parent_attachment_id):
        try:
            sessions.append_turns(
                user_key, project_id, home_sess, home_att,
                [sessions.make_turn(
                    "agent",
                    f"Proposed content for {node_label!r} — review and apply it below.",
                    content=[part],
                )],
            )
        except Exception:
            pass
    where = (
        "in this conversation"
        if home_att == parent_attachment_id
        else "at the node's own Node Builder agent"
    )
    return part, home_att, (
        f"the generated content was minted as reviewed proposal "
        f"{part['proposalId']} for node {node_id!r} ({where}); it awaits the "
        "user's explicit Apply — summarize the change in one or two "
        "sentences, do NOT restate the code, and do NOT say it was applied"
    )


# dev/90: the package-authoring capabilities whose delegation success feeds
# the delegate-draft mint below (the Package Builder's surface; the
# `package.create-or-extend` intent resolves to these). Canonical definition
# lives in content.py (dev/90 A6 — the tail contract sizes their inputs).
PACKAGE_AUTHORING_CAPABILITIES = content.PACKAGE_AUTHORING_CAPABILITIES

# dev/90 A8: the build-request contract, supplied to AUTHORING delegates as
# an input. DEC-046 children are tool-less and never see the grants paragraph
# where the tool schema lives — a live run showed the child inventing a
# plausible-but-wrong shape ("package"/"behaviors"/"behaviorKey") twice, and
# the parent cannot teach a schema it does not carry either. The runtime is
# the one place that always knows the contract (the dev/67-6 enrichment
# pattern: deterministic server-side inputs, never model-invented).
_BUILD_REQUEST_CONTRACT: dict = {
    "reply": (
        "Reply with ONE JSON object of exactly this shape (optionally inside "
        "a ```json fence), nothing after it. Do NOT invent other keys — "
        "there is no 'package', 'behaviors', or 'behaviorKey' key."
    ),
    "shape": {
        "mode": "create | extend",
        "baseDigest": "<64-hex digest of the installed target — extend only>",
        "manifest": {
            "id": ("reverse-DNS: two or more dot-separated lowercase segments, "
                   "e.g. 'curio.notes' — single-segment ids are invalid"),
            "version": "1.0.0",
            "name": "<display name>",
            "publisher": "<author>",
            "description": "<one line>",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "<kebab-case template id>",
                "label": "<display label>",
                "category": "visualization",
                "engine": "python | javascript",
                "editor": "code | widgets | grammar | none",
                "behavior": "<the behavior key your source registers — custom looks only>",
                "hasCode": False,
                "hasWidgets": False,
                "hasGrammar": False,
                "inputPorts": [],
                "outputPorts": [],
                "backendHandler": ("<declared backend handler name this "
                                   "template's Run invokes — backend "
                                   "templates only>"),
            }],
            "backend": {
                "entry": "backend/handler.py",
                "handlers": [{"name": "<a-z0-9- name>",
                              "timeoutClass": "quick | standard"}],
            },
        },
        "files": {"sources/<name>.tsx": {"text": "<complete file body>"}},
        "behaviorEntries": ["sources/<name>.tsx"],
        "previewTemplates": ["<each template id with a custom behavior>"],
        "nodes": [{
            "templateId": "<template id>",
            "title": "<node title>",
            "content": "<the fixed note/body text>",
            "appearance": {"backgroundColor":
                           "yellow|pink|blue|green|orange|lavender|#rrggbb"},
        }],
    },
    "rules": [
        "a presentation-only template is engine 'javascript', editor 'none', "
        "hasCode false, empty ports",
        "the behavior source registers EXACTLY the template's behavior key: "
        "window.curio.registerBehavior(key, (data, nodeState) => "
        "({ contentComponent: <React element> })) — import react normally, "
        "render React elements only, never raw HTML",
        "field contract: the note text arrives as data.code (data.content is "
        "an equivalent alias), the title as data.title, the per-instance "
        "color as data.appearance.backgroundColor (also nodeState.appearance."
        "backgroundColor) — read THESE fields, never invented ones",
        "prefer ZERO JS dependencies — write small rendering logic yourself",
        "the caller's inputs.notes ARE the requested nodes: copy each "
        "{title, content, color} into nodes[] VERBATIM — never invent "
        "placeholder content, never leave content empty when the caller "
        "supplied findings (the runtime enforces this reconciliation)",
        # memo dev/91: the backend authoring contract, stated where the
        # delegate can see it (the A8 lesson — nobody invents a schema they
        # were shown).
        "server-side compute (dev/91): declare manifest.backend "
        "{entry: 'backend/<file>.py', handlers: [{name, timeoutClass}]} plus "
        "the 'server-code' permission in manifest.permissions ('server-network' "
        "too if and only if the code reaches the network); the entry exposes "
        "def handle(payload) (or a HANDLERS dict {name: callable}); a node run "
        "delivers payload {'content': <editor text>, 'input': <upstream JSON "
        "or null>} and the returned value must be JSON-serializable",
        "backend code is pure Python + declared python dependencies, executed "
        "in a per-invocation sandboxed worker with strict limits: NO "
        "subprocess/multiprocessing/ctypes, NO eval/exec/compile/__import__/"
        "importlib, NO flask/blueprints/resident servers (the build's policy "
        "scan blocks these and the probe phase must pass before review); a "
        "capped persistent dir rides CURIO_PKG_DATA_DIR; no secrets and no "
        "dataset store exist in the worker — a need beyond this contract "
        "(resident service, credentials) is a FINDING naming dev/89 "
        "Follow-up B, never smuggled code",
    ],
}


def _extract_draft_params(child_text: str) -> dict | None:
    """The child reply's build-request payload, or None.

    Accepted shapes (the reply is already bounded by
    ``delegation.DELEGATE_RESULT_MAX_CHARS``): the whole reply as one JSON
    object, or one fenced ```/```json/```curio.v1 block containing it; the
    object may be the build request itself, wrapped as
    ``{"packageDraft": {...}}``, or — dev/90 A7, the instruction-faithful
    delegate shape — a ``package.draft.apply`` toolRequest whose ``params``
    are the request (a tool-less child that follows its own tool teaching
    emits exactly that; the payload is unwrapped, never executed as a tool).
    A candidate must carry ``mode`` + ``manifest`` to count — arbitrary JSON
    in a chatty reply never parses as a draft by accident.
    """
    import json as _json
    import re as _re2

    if not isinstance(child_text, str) or not child_text.strip():
        return None
    candidates: list[str] = []
    stripped = child_text.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)
    for match in _re2.finditer(
            r"```(?:json|curio\.v1)?\s*\n(.*?)```", child_text, _re2.DOTALL):
        candidates.append(match.group(1).strip())
    for candidate in candidates:
        try:
            payload = _json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        tool_req = payload.get("toolRequest")
        if (isinstance(tool_req, dict)
                and tool_req.get("tool") == "package.draft.apply"
                and isinstance(tool_req.get("params"), dict)):
            payload = tool_req["params"]  # dev/90 A7: unwrap, never execute
        wrapped = payload.get("packageDraft")
        inner = wrapped if isinstance(wrapped, dict) else payload
        if (isinstance(inner, dict) and inner.get("mode") in ("create", "extend")
                and isinstance(inner.get("manifest"), dict)):
            return inner
    return None


def _notes_from_delegate_inputs(inputs: dict) -> list[dict] | None:
    """The parent's findings as typed note rows (dev/90 A12), or None.

    Accepts ``inputs.notes`` (or ``inputs.findings``): a list of objects with
    non-empty string ``content`` (the finding text — the reason the note
    exists), optional ``title``, optional ``color`` /
    ``appearance.backgroundColor``. Malformed rows are skipped; an empty
    result is None (nothing to enforce).
    """
    raw = inputs.get("notes") or inputs.get("findings")
    if not isinstance(raw, list):
        return None
    rows: list[dict] = []
    for item in raw[:16]:
        if not isinstance(item, dict):
            continue
        content_text = item.get("content")
        if not isinstance(content_text, str) or not content_text.strip():
            continue
        row: dict = {"content": content_text}
        title = item.get("title")
        if isinstance(title, str) and title.strip():
            row["title"] = title.strip()
        color = item.get("color")
        if not isinstance(color, str) or not color:
            appearance = item.get("appearance")
            color = (appearance or {}).get("backgroundColor") if isinstance(
                appearance, dict) else None
        if isinstance(color, str) and color:
            row["appearance"] = {"backgroundColor": color}
        rows.append(row)
    return rows or None


def _reconcile_draft_notes(params: dict, notes: list[dict]) -> bool:
    """dev/90 A12: the PARENT's findings are authoritative note content.

    When the delegation inputs carried notes, they replace the draft's
    ``nodes[]`` wholesale — the child owns the LOOK (manifest, behavior
    source), the parent owns the FACTS, and the runtime marries them
    deterministically (models are never trusted to relay content; the live
    failure was child-invented filler and empty notes). The template comes
    from the draft itself: the first preview template when declared, else
    the manifest's first template. Returns True when a replacement happened.
    """
    manifest = params.get("manifest")
    if not isinstance(manifest, dict):
        return False
    template_id = None
    preview = params.get("previewTemplates")
    if isinstance(preview, list) and preview and isinstance(preview[0], str):
        template_id = preview[0]
    if template_id is None:
        for template in manifest.get("templates") or []:
            if isinstance(template, dict) and isinstance(template.get("id"), str):
                template_id = template["id"]
                break
    if template_id is None:
        return False
    params["nodes"] = [{"templateId": template_id, **row} for row in notes]
    return True


def _mint_package_draft_from_delegate(
    user_key: str, project_id: str, loop_ctx: dict, child_text: str,
    delegate_inputs: dict | None = None,
) -> tuple[dict | None, str]:
    """dev/90: the dev/73 one-mint-policy extended to package drafts.

    A successful package-authoring delegation whose bounded child reply
    parses as a build request becomes a reviewed ``package.draft.apply``
    proposal minted by the RUNTIME at the parent's attachment — depth-1
    children are structurally tool-less, so the delegate can never emit the
    toolRequest itself. The mint reuses ``_mint_package_draft_apply``
    verbatim (one build/validation path); a reply that does not parse, a
    parent without the ``package.draft.apply`` grant, or a draft the build
    service refuses are all data the parent recovers from in chat — never a
    silent drop, never an unreviewed mutation.

    Returns ``(proposal_part | None, text_for_model)``.
    """
    if "package.draft.apply" not in (loop_ctx.get("granted") or []):
        return None, (
            "the delegate produced a package draft but this agent is not "
            "granted package.draft.apply — the draft was kept as text only"
        )
    params = _extract_draft_params(child_text)
    if params is None:
        return None, (
            "the authoring delegate returned no parseable package draft "
            "(expected one JSON build request); its reply was kept as text — "
            "refine the delegation inputs and try again"
        )
    # dev/90 A12: the parent's findings override the draft's nodes — the
    # reference contract is "the agent's answer IS the note", and the live
    # failures were child-invented filler / empty notes.
    reconciled = False
    notes = _notes_from_delegate_inputs(delegate_inputs or {})
    if notes:
        reconciled = _reconcile_draft_notes(params, notes)
    status, text, part = _mint_package_draft_apply(
        user_key, project_id, loop_ctx, {"params": params}
    )
    if status == "proposed" and reconciled:
        text += (
            f" (the draft's {len(notes)} note(s) carry the caller's findings "
            "verbatim — runtime-reconciled from the delegation inputs)"
        )
    return (part if status == "proposed" else None), text


def _enriched_delegate_inputs(
    user_key: str, project_id: str, loop_ctx: dict, capability: str, inputs: dict
) -> dict:
    """dev/67-6: content-generation delegates get the composed node context
    appended server-side (never overwriting the model's own keys) — the child
    stops generating blind to the graph. The node resolves from the model's
    ``nodeId`` input or the parent attachment's node target; no node, no
    enrichment (honest absence beats a fabricated neighborhood)."""
    if capability == "research.verify" and "verification" not in inputs:
        # dev/67-4: DEC-046 children are structurally tool-less — the runtime
        # runs the deterministic validators and the child synthesizes over
        # REAL evidence (the researcher's own attachment runs use the web
        # tools directly).
        url = inputs.get("url") or inputs.get("endpoint")
        if isinstance(url, str) and url.strip():
            return {**inputs, "verification": verify.verify_external_source(url)}
        return inputs
    if capability in PACKAGE_AUTHORING_CAPABILITIES and "buildRequestContract" not in inputs:
        # dev/90 A8: tool-less authoring delegates get the build-request
        # contract server-side — the child answers to a schema it can SEE,
        # never a shape it has to invent (the model's own keys always win).
        return {**inputs, "buildRequestContract": _BUILD_REQUEST_CONTRACT}
    if capability != "node.content.generate" or "nodeContext" in inputs:
        return inputs
    node_id = inputs.get("nodeId")
    if not isinstance(node_id, str) or not node_id:
        target = loop_ctx.get("target")
        node_id = (
            target.get("targetId")
            if isinstance(target, dict) and target.get("kind") == "node"
            else None
        )
    if not node_id:
        return inputs
    spec = projects_storage.read_spec(user_key, project_id)
    composed = node_context.compose_node_context(user_key, project_id, spec, node_id)
    if composed is None:
        return inputs
    return {**inputs, "nodeContext": composed}


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
            _verify_candidate_parts(parts)  # dev/67-4: no unverified laundering
            req = (
                parts[0]
                if parts and parts[0].get("type") in ("toolRequest", "delegateRequest")
                else None
            )
            if req is None:
                # Plan handling (dev/52 mint; dev/54 correction rounds).
                kind, payload, visible_override = _handle_plan_reply(
                    user_key, project_id, loop_ctx, reply, parts, minted, rounds_used
                )
                if kind == "correct":
                    # Corrective prose is not folded: the invalid attempt never
                    # reaches the user; the final round's text is the truth.
                    rounds_used += 1
                    messages_work.append({"role": "assistant", "content": reply})
                    messages_work.append(_plan_correction_message(payload))
                    continue
                effective_visible = visible_override if visible_override is not None else visible
                if effective_visible:
                    folded.append(effective_visible)
                final_parts = payload
                break
            if visible:
                folded.append(visible)
            if rounds_used >= MAX_TOOL_ROUNDS:
                # dev/73: a mutate request cut off at the cap is a visible
                # outcome — never a silent drop under confident prose.
                if req["type"] == "toolRequest" and req.get("tool") in MUTATE_PROPOSAL_TOOLS:
                    minted.append(_round_cap_cutoff_card(req["tool"]))
                break  # dangling read request at the cap: dropped, text kept
            rounds_used += 1
            final = rounds_used >= MAX_TOOL_ROUNDS
            if req["type"] == "delegateRequest":
                status, text, resolution = _resolve_delegate_request(
                    user_key, project_id, loop_ctx, req, minted
                )
                if resolution is not None:
                    # dev/73: node-scoped content generation homes its trace
                    # AND its minted review at the node's own agent.
                    gen_node_id = (
                        _delegate_target_node_id(loop_ctx, req.get("inputs") or {})
                        if req["capability"] == "node.content.generate"
                        else None
                    )
                    status, text, child, home_att = _run_delegate_traced(
                        user_key,
                        project_id,
                        resolution.coord,
                        req["capability"],
                        _enriched_delegate_inputs(
                            user_key, project_id, loop_ctx,
                            req["capability"], req.get("inputs") or {},
                        ),
                        config,
                        parent_execution_id=execution_id,
                        parent_coord=loop_ctx["coord"],
                        attachment_id=loop_ctx.get("attachment_id"),
                        parent_name=getattr(loop_ctx.get("manifest"), "name", None),
                        node_id=gen_node_id,
                    )
                    delegations.append(child)
                    delegate_summary = text
                    if status == "ok" and gen_node_id:
                        # dev/73: generation success ⇒ the review EXISTS —
                        # runtime-minted, never the model's second step.
                        review_part, review_home, text = _mint_content_review_from_delegate(
                            user_key, project_id,
                            node_id=gen_node_id,
                            generated_text=text,
                            parent_attachment_id=loop_ctx.get("attachment_id"),
                            parent_session_id=loop_ctx.get("session_id"),
                        )
                        delegate_summary = text
                        if review_part is not None:
                            delegate_summary = (
                                f"reviewed content change proposed for node "
                                f"{gen_node_id!r} — awaits Apply"
                            )
                            if review_home == loop_ctx.get("attachment_id"):
                                minted.append(review_part)
                    elif status == "ok" and req["capability"] in PACKAGE_AUTHORING_CAPABILITIES:
                        # dev/90: authoring success ⇒ the reviewed draft
                        # EXISTS — runtime-minted from the child's payload,
                        # never the model's second step.
                        draft_part, text = _mint_package_draft_from_delegate(
                            user_key, project_id, loop_ctx, text,
                            delegate_inputs=req.get("inputs") or {},
                        )
                        delegate_summary = text
                        if draft_part is not None:
                            minted.append(draft_part)
                            delegate_summary = (
                                "reviewed package draft proposed — awaits Apply"
                            )
                    # dev/72: the parent keeps the compact, linkable entry.
                    minted.append(_delegation_part_for(
                        resolution, req["capability"], status, delegate_summary, home_att
                    ))
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
        # dev/80: the run's wall-clock duration — matches the persisted record.
        "durationMs": execution["durationMs"],
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
    followed by ``("delta", text)`` events, ``("usage", {usage})`` interim
    Actual sums once per provider round (memo dev/80), optionally
    ``("content", {parts})`` when the reply carried a valid structured tail
    (memo dev/39), ending in
    ``("done", {reply, executionId, usage, durationMs, content})`` — or
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

    def _stream_round(
        messages_work: list, usage_sink: dict, result: dict, hold_plan_tail: bool = False
    ):
        """Stream one provider round: yields ("delta", text) with the dev/39
        tail withholding, then leaves {reply, visible, parts} in *result*.
        ``hold_plan_tail`` (dev/54): an INVALID tail that looks like a plan
        attempt is held (``result["heldPlanTail"]``) instead of flushed — the
        correction round must not leak raw plan JSON to the user; the caller
        releases it at the round cap (fail-open transparency)."""
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
        _verify_candidate_parts(parts)  # dev/67-4: no unverified laundering
        if withheld is not None and not parts:
            if hold_plan_tail and (
                '"dataflowPlan"' in withheld or '"dataflow.plan.write"' in withheld
            ):
                # A failed plan attempt (dev/54): held for the correction
                # round instead of leaking raw JSON into the chat.
                result["heldPlanTail"] = withheld
            else:
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
        # dev/73: reviews minted at a FOREIGN home (the node's agent) — they
        # never ride the parent turn's parts, but still pause at review.
        homed_reviews: list = []
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
                yield from _stream_round(
                    messages_work,
                    usage_sink,
                    result,
                    hold_plan_tail="dataflow.plan.write" in loop_ctx.get("granted", []),
                )
                _add_usage(usage_total, usage_sink)
                if usage_sink:
                    # dev/80: interim Actual sums, once per provider round —
                    # the client's live token counter ticks during long tool
                    # loops. Additive; old clients skip unknown events.
                    yield ("usage", {"usage": dict(usage_total)})
                parts = result["parts"]
                req = (
                    parts[0]
                    if parts and parts[0].get("type") in ("toolRequest", "delegateRequest")
                    else None
                )
                if req is None:
                    # Plan handling (dev/52 mint; dev/54 correction rounds).
                    kind, payload, visible_override = _handle_plan_reply(
                        user_key, project_id, loop_ctx, result["reply"], parts, minted, rounds_used
                    )
                    if kind == "correct":
                        rounds_used += 1
                        yield (
                            "plan_revision",
                            {"attempt": rounds_used, "errors": len(payload)},
                        )
                        messages_work.append(
                            {"role": "assistant", "content": result["reply"]}
                        )
                        messages_work.append(_plan_correction_message(payload))
                        continue
                    if kind == "cap" and result.get("heldPlanTail"):
                        # Fail-open transparency at the cap: the held tail is
                        # the model's text — released, then explained by the
                        # error card in `payload`.
                        yield ("delta", result["heldPlanTail"])
                    effective_visible = (
                        visible_override if visible_override is not None else result["visible"]
                    )
                    if effective_visible:
                        folded.append(effective_visible)
                    final_parts = payload
                    break
                if result["visible"]:
                    folded.append(result["visible"])
                if rounds_used >= MAX_TOOL_ROUNDS:
                    # dev/73: a mutate request cut off at the cap is a visible
                    # outcome — never a silent drop under confident prose.
                    if req["type"] == "toolRequest" and req.get("tool") in MUTATE_PROPOSAL_TOOLS:
                        minted.append(_round_cap_cutoff_card(req["tool"]))
                    break  # dangling read request at the cap: dropped, text kept
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
                        # dev/73: node-scoped content generation homes its
                        # trace AND its minted review at the node's own agent.
                        gen_node_id = (
                            _delegate_target_node_id(loop_ctx, req.get("inputs") or {})
                            if req["capability"] == "node.content.generate"
                            else None
                        )
                        status, text, child, home_att = _run_delegate_traced(
                            user_key,
                            project_id,
                            resolution.coord,
                            req["capability"],
                            _enriched_delegate_inputs(
                                user_key, project_id, loop_ctx,
                                req["capability"], req.get("inputs") or {},
                            ),
                            config,
                            parent_execution_id=execution_id,
                            parent_coord=loop_ctx["coord"],
                            attachment_id=loop_ctx.get("attachment_id"),
                            parent_name=getattr(loop_ctx.get("manifest"), "name", None),
                            node_id=gen_node_id,
                        )
                        delegations.append(child)
                        delegate_summary = text
                        if status == "ok" and gen_node_id:
                            # dev/73: generation success ⇒ the review EXISTS —
                            # runtime-minted, never the model's second step.
                            review_part, review_home, text = _mint_content_review_from_delegate(
                                user_key, project_id,
                                node_id=gen_node_id,
                                generated_text=text,
                                parent_attachment_id=loop_ctx.get("attachment_id"),
                                parent_session_id=loop_ctx.get("session_id"),
                            )
                            delegate_summary = text
                            if review_part is not None:
                                delegate_summary = (
                                    f"reviewed content change proposed for node "
                                    f"{gen_node_id!r} — awaits Apply"
                                )
                                if review_home == loop_ctx.get("attachment_id"):
                                    minted.append(review_part)
                                else:
                                    homed_reviews.append((review_part, review_home))
                        elif status == "ok" and req["capability"] in PACKAGE_AUTHORING_CAPABILITIES:
                            # dev/90: authoring success ⇒ the reviewed draft
                            # EXISTS — runtime-minted from the child's
                            # payload, never the model's second step.
                            draft_part, text = _mint_package_draft_from_delegate(
                                user_key, project_id, loop_ctx, text,
                                delegate_inputs=req.get("inputs") or {},
                            )
                            delegate_summary = text
                            if draft_part is not None:
                                minted.append(draft_part)
                                delegate_summary = (
                                    "reviewed package draft proposed — awaits Apply"
                                )
                        # dev/72: the parent keeps the compact, linkable entry.
                        minted.append(_delegation_part_for(
                            resolution, req["capability"], status, delegate_summary, home_att
                        ))
                        yield (
                            "delegate_result",
                            {
                                "capability": req["capability"],
                                "coord": resolution.coord,
                                # dev/72: the live line can link too.
                                "attachmentId": home_att,
                                "name": getattr(resolution.manifest, "name", None)
                                if resolution.manifest else None,
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
            if part.get("type") != "proposal":
                continue  # dev/72: delegation entries ride the content event
            yield (
                "review_required",
                {
                    "proposalId": part["proposalId"],
                    "tool": part["tool"],
                    "summary": part["summary"],
                },
            )
        # dev/73: reviews homed at the node's agent pause visibly too — the
        # client refreshes and the parent's delegation entry links there.
        for part, review_home in homed_reviews:
            yield (
                "review_required",
                {
                    "proposalId": part["proposalId"],
                    "tool": part["tool"],
                    "summary": part["summary"],
                    "attachmentId": review_home,
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
                # dev/80: the run's wall-clock duration — matches the
                # persisted execution record.
                "durationMs": execution["durationMs"],
                "content": run_parts,
            },
        )

    return _events()
