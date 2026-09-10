"""Agents catalog / lifecycle service layer.

Sits over the filesystem stores (``storage`` = definition artifacts, ``imports``
= account "My Imports", ``project_agents`` = per-project lockfile) and mirrors
``app/packages/services.py``: the route layer stays thin, this layer owns the
rules, and the project lockfile is read/written through ``projects.storage``.

Import and Install are separate explicit commands and never chain (DEC-029).
User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

import logging
import time
import uuid

from utk_curio.backend.app.agents import (
    attachments,
    builtin,
    content,
    delegation,
    imports,
    ledger,
    project_agents,
    publications,
    sessions,
    storage,
    tools,
)
from utk_curio.backend.app.agents import (
    agent_jobs,
    egress,
    failure_text,
    node_context,
    plan_topology,
    source_grounding,
    verify,
)
from utk_curio.backend.app.agents.attachments import AttachmentError
from utk_curio.backend.app.agents.manifest import AGENT_CATEGORIES, AgentManifest
from utk_curio.backend.app.agents.providers import (
    ProviderConfig,
    run_chat_completion,
    stream_chat_completion,
)
from utk_curio.backend.app.projects import storage as projects_storage

#: The output ceiling every agent run is dispatched with.
#:
#: This was ``policy.DEPLOYMENT_MAX_OUTPUT_TOKENS``, the deployment floor of a
#: three-scope resolver (account, per-dataflow, per-attachment) with
#: tighten-only writes and an optimistic revision. All three editors are gone,
#: so no user value can exist to resolve against and the resolver had exactly
#: one input left: this number. Passed to every provider as ``max_tokens``.
DEPLOYMENT_MAX_OUTPUT_TOKENS = 4096

log = logging.getLogger(__name__)


class AgentServiceError(Exception):
    """Service-layer error carrying an HTTP status for the route layer."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def agent_catalog_facets(cards: list[dict]) -> dict[str, dict[str, int]]:
    """Count a card list along the axes the browse page rails on.

    Mirrors ``datasets.domain.dedup.catalog_facets``: every key is seeded at
    zero so a rail renders a complete, stable set of rows rather than only the
    facets that happen to be populated, and the counts come from the same list
    the caller is about to return, never a second query.

    ``category`` is the manifest's own vocabulary. ``origin`` is provenance:
    an agent shipped with Curio, one published into the catalog, or one the
    user imported into their own account.
    """
    facets: dict[str, dict[str, int]] = {
        "category": {c: 0 for c in AGENT_CATEGORIES},
        "origin": {"builtin": 0, "published": 0, "imported": 0},
    }
    for card in cards:
        category = card.get("category")
        if category in facets["category"]:
            facets["category"][category] += 1
        if card.get("published"):
            facets["origin"]["published"] += 1
        elif card.get("imported"):
            facets["origin"]["imported"] += 1
        else:
            facets["origin"]["builtin"] += 1
    return facets


def _manifest_to_card(
    m: AgentManifest,
    *,
    scope: str,
    imported: bool,
    installed_in_project: bool,
    published: bool = False,
    publishable: bool = False,
    requires_agents: list[dict] | None = None,
) -> dict:
    """Serialize a definition to the camelCase card the drawer consumes.

    ``requires_agents`` (dev/106) is the server-resolved hard-dependency list
    (``_requires_agents_rows``) so the drawer can disclose what an Install
    adds without re-deriving it; absent → ``[]``."""
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
        "requiresAgents": list(requires_agents or []),
    }


def _requires_agents_rows(user_key: str, m: AgentManifest, installed: set[str]) -> list[dict]:
    """dev/106: one row per DIRECT hard dependency of *m* — ``{id, name, coord,
    installedInProject, visible}``. ``coord``/``name`` fall back to the id when
    the dependency is visible nowhere (the drawer says so; install refuses)."""
    rows: list[dict] = []
    for agent_id in m.requires_agents:
        coord, dep = delegation.find_visible(user_key, agent_id)
        rows.append({
            "id": agent_id,
            "name": dep.name if dep is not None else agent_id,
            "coord": coord,
            "visible": dep is not None,
            "installedInProject": coord in installed if coord else False,
        })
    return rows


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


def builtin_definition_bundle(coord: str) -> dict | None:
    """A built-in's ``{manifest, prompts}`` straight from the roster and
    ``llm-prompts/``, without materializing anything into a store."""
    spec = builtin.get_builtin_spec(coord)
    if spec is None:
        return None
    manifest = builtin.build_builtin_manifest(spec)
    prompts: dict[str, str] = {}
    for key, asset in manifest["prompts"].items():
        text = builtin.read_prompt_text(coord, key)
        if text is not None:
            prompts[asset["path"]] = text
    return {"manifest": manifest, "prompts": prompts}


def read_definition_bundle_anywhere(user_key: str, coord: str) -> dict | None:
    """The exportable definition of *coord* from wherever it is (#275).

    ``GET /api/agents/definitions/<coord>`` read the user store only, so
    "View details -> Export" on the Agent Catalog page - which lists the whole
    roster and the shared catalog - failed for any agent this account had not
    imported or installed, including every built-in. The precedence here is
    :func:`_resolve_definition`'s: an owned import shadows everything, then
    the built-in roster (so a stale materialized copy does not win over the
    current prompts), then a built-in's store copy, then the published catalog.
    """
    store = storage.read_definition_bundle(user_key, coord)
    if store is not None:
        trust = ((store.get("manifest") or {}).get("provenance") or {}).get("trust")
        if trust != "built-in":
            return store
    roster = builtin_definition_bundle(coord)
    if roster is not None:
        return roster
    if store is not None:
        return store
    try:
        return storage.read_definition_bundle_from_dir(publications.published_agent_dir(coord))
    except (AgentManifestError, PathTraversalError):
        return None


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
        scope="imports",
        imported=True,
        installed_in_project=False,
        published=publications.is_published(coord),
        publishable=True,
        requires_agents=_requires_agents_rows(user_key, m, set()),
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
            scope="browse",
            imported=dir_name in imported,
            installed_in_project=dir_name in installed,
            published=published,
            requires_agents=_requires_agents_rows(user_key, m, installed),
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
                scope="imports",
                imported=True,
                installed_in_project=coord in installed,
                published=publications.is_published(coord),
                publishable=(m.provenance.trust == "imported"),
                requires_agents=_requires_agents_rows(user_key, m, installed),
            )
        )
    return out


def list_installed_in_project(user_key: str, project_id: str) -> list[dict]:
    """The project's installed templates from its ``dataflow.agents`` lockfile."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    imported = imports.load_imported_agents(user_key)
    installed = set(project_agents.project_agents(spec))
    out: list[dict] = []
    for coord in project_agents.project_agents(spec):
        m = _resolve_definition(user_key, coord)
        if m is None:
            continue
        out.append(
            _manifest_to_card(
                m, scope="installed", imported=coord in imported, installed_in_project=True,
                requires_agents=_requires_agents_rows(user_key, m, installed),
            )
        )
    return out


# ── lifecycle commands (explicit, non-chaining) ──────────────────────────────
def _fan_out_imports(user, user_key: str, coord: str, *, install: bool) -> list[dict]:
    """Apply an account-level import decision to every project the user has.

    Recording a coordinate in My Imports writes no project lockfile, and the
    canvas agents palette reads the lockfile (``listProjectAgents`` ->
    ``dataflow.agents``). So an imported agent was reported as "In all projects"
    by the catalog while appearing in none of them - the catalog was describing
    the account, the palette was describing the project, and the label was
    simply false.

    This is the same eager walk ``packages.services.install_to_defaults`` does,
    for the same reason: nothing consults the account list when a project is
    opened, so only a walk at decision time can make the claim true.

    Best-effort per project - one project with a broken spec must not abort the
    rest, and never fails the import itself.
    """
    if user is None:
        return []
    from utk_curio.backend.app.projects import repositories as projects_repo

    results: list[dict] = []
    for project in projects_repo.list_for_user(user.id):
        try:
            if install:
                install_in_project(user_key, project.id, coord)
            else:
                uninstall_from_project(user_key, project.id, coord)
            results.append({"id": project.id, "ok": True})
        except Exception as exc:  # noqa: BLE001 - per-project failure is OK
            log.warning(
                "agent import fan-out (%s) failed for project %s: %s",
                "install" if install else "uninstall", project.id, exc,
            )
            results.append({"id": project.id, "ok": False, "error": str(exc)})
    return results


def import_agent(user_key: str, coord: str, *, user=None) -> dict:
    """Record *coord* in My Imports and install it into every project.

    ``user`` is optional so the many existing callers that only hold a
    ``user_key`` keep working unchanged; without it this records the coordinate
    and nothing else, exactly as before.
    """
    _require_definition(user_key, coord)
    _materialize_builtin(user_key, coord)
    imports.add_imported_agent(user_key, coord)
    projects = _fan_out_imports(user, user_key, coord, install=True)
    return {"coord": coord, "imported": True, "projects": projects}


def remove_import(user_key: str, coord: str, *, user=None) -> dict:
    """Drop *coord* from My Imports and uninstall it from every project."""
    imports.remove_imported_agent(user_key, coord)
    projects = _fan_out_imports(user, user_key, coord, install=False)
    return {"coord": coord, "imported": False, "projects": projects}


def seed_project_with_imported_agents(user_key: str, project_id: str) -> None:
    """Install the account's imported agents into a brand-new project.

    The "future" half of "all your projects, present and future"; the walk above
    is the "present" half. Best-effort: a stale import must degrade to "that
    agent is missing here", never to "the project could not be created".
    """
    try:
        coords = imports.load_imported_agents(user_key)
    except Exception:  # noqa: BLE001
        return
    for coord in sorted(coords):
        try:
            install_in_project(user_key, project_id, coord)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "seed imported agent %s into project %s failed: %s",
                coord, project_id, exc,
            )


def install_in_project(user_key: str, project_id: str, coord: str) -> dict:
    """Add *coord* AND its ``requiresAgents`` closure to the project's lockfile
    (explicit; never auto-imports).

    dev/106: the closure (``delegation.required_closure``) is resolved BEFORE
    anything is written — a dependency visible nowhere refuses with 409 and
    leaves the lockfile untouched. Every coord in the closure is materialized
    and recorded in ONE spec write. This runs at the user's explicit Install
    (drawer button or a reviewed ``project.install`` Apply), so `REQ-ORCH-001`
    — the orchestrator never installs silently — is untouched.

    Also materializes the project-agent-default record (memo dev/23) — an
    independent per-project profile the settings screens later edit. Idempotent:
    reinstalling never resets an existing record.

    Returns ``{"agents": lockfile, "installed": [coords newly added, root
    first], "required": [the closure's coords]}``.
    """
    root = _require_definition(user_key, coord)
    required, missing = delegation.required_closure(user_key, root)
    if missing:
        raise AgentServiceError(
            f"{root.name} ({coord}) requires "
            + ", ".join(missing)
            + ", which " + ("is" if len(missing) == 1 else "are")
            + " not available in the catalog or your imports — nothing was installed",
            409,
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    for c in [coord, *required]:
        _materialize_builtin(user_key, c)
    current = project_agents.project_agents(spec)
    added: list[str] = []
    for c in [coord, *required]:
        if c not in current and c not in added:
            added.append(c)
    dirty = False
    if added:
        project_agents.set_project_agents(spec, current + added)
        dirty = True
    if dirty:
        projects_storage.write_spec(user_key, project_id, spec)
    return {
        "agents": project_agents.project_agents(spec),
        "installed": added,
        "required": required,
    }


def _repair_required_closure(
    user_key: str, project_id: str, coord: str, *, attachment_id: str | None = None
) -> list[str]:
    """``DEC-080`` (memo dev/126): complete an installed agent's declared
    hard-dependency closure at the point the USER acts on the dependent.

    A project whose lockfile predates a ``requiresAgents`` declaration is
    missing an agent a SERVER path of the dependent invokes without model
    choice, and no amount of conversation can fix that: the run stalls on a
    reviewed install for something the user already consented to when they
    installed the dependent (that is what ``DEC-068`` made an install mean).
    So the closure is completed through the ONE install path
    (``install_in_project`` — same materialization, same single spec write,
    same 409 when a member is visible nowhere), bounded to ``requiresAgents``
    members, never a preferred delegate, and never a model decision:
    `REQ-ORCH-001` is untouched.

    Returns the coords added (empty when the closure was already complete, or
    when it could not be completed — a refusal is logged and disclosed by the
    caller's own fallback lane, never raised into the user's action).
    """
    from utk_curio.backend.app.agents import project_agents

    try:
        manifest = _resolve_definition(user_key, coord)
        if manifest is None or not manifest.requires_agents:
            return []
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is None:
            return []
        installed_ids = {
            c.split("@", 1)[0] for c in project_agents.project_agents(spec)
        }
        required, missing = delegation.required_closure(user_key, manifest)
        if missing:
            log.warning(
                "Required agent(s) %s of %s are visible nowhere — project %s keeps the "
                "reviewed install lane", ", ".join(missing), coord, project_id,
            )
            return []
        if all(c.split("@", 1)[0] in installed_ids for c in required):
            return []
        added = install_in_project(user_key, project_id, coord).get("installed") or []
    except Exception:  # noqa: BLE001
        log.warning("Could not repair the required closure of %s in project %s",
                    coord, project_id, exc_info=True)
        return []
    if added and attachment_id:
        _disclose_closure_repair(user_key, project_id, attachment_id, coord, added)
    return added


def _disclose_closure_repair(
    user_key: str, project_id: str, attachment_id: str, coord: str, added: list[str]
) -> None:
    """Say in the transcript what the repair installed and why (dev/126) — an
    install the user did not click on this turn is never silent. Best-effort:
    the disclosure never fails the action it describes."""
    try:
        spec = projects_storage.read_spec(user_key, project_id)
        record = attachments.get_attachment(spec or {}, attachment_id) or {}
        session_id = record.get("sessionId")
        if not isinstance(session_id, str):
            return
        dependent = _resolve_definition(user_key, coord)
        dependent_name = getattr(dependent, "name", None) or coord
        names = []
        for c in added:
            m = _resolve_definition(user_key, c)
            names.append(getattr(m, "name", None) or c)
        sessions.append_turns(
            user_key, project_id, session_id, attachment_id,
            [sessions.make_turn(
                "agent",
                f"Added {', '.join(names)} — required by {dependent_name}.",
                content=[{
                    "type": "card",
                    "kind": "result",
                    "title": "Added required agents",
                    "lines": [c for c in added[:6]] + [f"required by {coord}"],
                }],
            )],
        )
    except Exception:  # noqa: BLE001
        log.warning("Could not disclose the closure repair for %s", coord, exc_info=True)


def uninstall_from_project(user_key: str, project_id: str, coord: str) -> dict:
    """Remove *coord* from the project's lockfile and drop its defaults record.

    dev/106: refused (409) while another INSTALLED template lists *coord*'s
    agent in ``requiresAgents`` — the dependents are named. No cascade."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    current = project_agents.project_agents(spec)
    dependents = delegation.required_by(user_key, current, coord) if coord in current else []
    if dependents:
        names = []
        for d in dependents:
            dm = _resolve_definition(user_key, d)
            names.append(f"{dm.name} ({d})" if dm else d)
        raise AgentServiceError(
            f"{coord} is required by " + ", ".join(names)
            + " — uninstall " + ("that agent" if len(names) == 1 else "those agents") + " first",
            409,
        )
    dirty = False
    if coord in current:
        project_agents.set_project_agents(spec, [c for c in current if c != coord])
        dirty = True
    # ...and take its attachments with it. Without this the agent was removed
    # from the lockfile while its badges stayed on the nodes and it kept
    # running: `attach` is gated on the lockfile but `run_attachment` is not.
    detached = attachments.detach_all_for_coord(spec, coord)
    if detached:
        dirty = True
    if dirty:
        projects_storage.write_spec(user_key, project_id, spec)
    return {
        "agents": project_agents.project_agents(spec),
        "detached": [r.get("attachmentId") for r in detached],
    }


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


def _reconcile_solve_session(user_key: str, project_id: str, spec: dict, record: dict) -> bool:
    """dev/115 (DEC-021, single-process): a builder session left ``solving``
    by an execution this process does not hold becomes ``interrupted`` — the
    transcript says so once, nothing is re-run, and the caller's *spec* is
    persisted when anything changed. Runs wherever a builder session is read
    for action (attachment listing, Solve, cancel)."""
    session = record.get("builderSession")
    if not isinstance(session, dict):
        return False
    before = session.get("solveExecutionId")
    if not agent_jobs.reconcile_builder_session(session):
        return False
    record["builderSession"] = session
    projects_storage.write_spec(user_key, project_id, spec)
    session_id = record.get("sessionId")
    if isinstance(session_id, str):
        try:
            pending = sum(
                1 for status in (session.get("nodeRuns") or {}).values()
                if status in ("pending", "failed")
            )
            sessions.append_turns(
                user_key, project_id, session_id, record.get("attachmentId"),
                [sessions.make_turn(
                    "agent",
                    "Solve was interrupted — the server stopped while it was running. "
                    "Nothing was replayed; finished nodes kept their content. "
                    f"{pending} node{'s' if pending != 1 else ''} still need solving — Retry continues.",
                    content=[{
                        "type": "card", "kind": "error", "title": "Solve interrupted",
                        "lines": [
                            f"execution {str(before or '')[:8]} expired with the process",
                            "Retry starts a new execution linked to it (DEC-021: never a replay)",
                        ],
                    }],
                )],
            )
        except Exception:
            pass
    return True


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
        # dev/115: the running background job this process holds for the
        # attachment (Solve batch / per-node Solve), or null.
        "liveJob": _live_job_payload(user_key, record),
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


def _live_job_payload(user_key: str, record: dict) -> dict | None:
    """dev/115: the attachment's running background job, if this process
    holds one — the dock's running indicator (docs/11:178)."""
    job = agent_jobs.live_job(user_key, str(record.get("attachmentId") or ""))
    return job.to_payload() if job is not None else None


def list_project_attachments(user_key: str, project_id: str) -> list[dict]:
    spec = _read_spec_or_404(user_key, project_id)
    records = attachments.list_attachments(spec)
    # dev/115 (DEC-021): a session left "solving" by a process that is gone is
    # reconciled to "interrupted" the first time anyone reads it.
    for record in records:
        _reconcile_solve_session(user_key, project_id, spec, record)
    return [_attachment_card(spec, r, user_key) for r in records]


def attach_agent(user_key: str, project_id: str, coord: str, target: object) -> dict:
    """Attach an installed template to a target. Requires the template installed
    in this project (no auto-install), and a valid target."""
    spec = _read_spec_or_404(user_key, project_id)
    if coord not in project_agents.project_agents(spec):
        raise AgentServiceError(
            "install the agent in this project before attaching it", 400
        )
    # DEC-080 (dev/126): attaching is acting on this agent — complete its
    # declared closure before it can run.
    if _repair_required_closure(user_key, project_id, coord):
        spec = _read_spec_or_404(user_key, project_id)
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
            # dev/126: ONE reading of the rule — the same predicate the plan
            # apply's automatic attach uses (attachments.node_target_matches).
            if not attachments.node_target_matches(manifest, node_type):
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


def record_dataset_selection(
    user_key: str, project_id: str, attachment_id: str, picks: object
) -> dict:
    """dev/126: record the user's confirmed dataset selection for a node.

    The picks are ``{lane, key}`` pairs — a catalog row's ``datasetId`` or an
    external row's ``url`` — resolved against the LATEST ``datasetCandidates``
    part persisted in this attachment's own session. The client therefore sends
    identifiers only: a source the runtime never proposed (and never probed)
    cannot enter through this endpoint. External picks are re-probed at
    confirmation time through the ``DEC-053`` chokepoint, and the verdict is
    what the record keeps — an unreachable pick does not resolve the node.
    """
    from utk_curio.backend.app.agents import dataset_resolution

    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    if record.get("coord", "").split("@", 1)[0] != dataset_resolution.FINDER_AGENT_ID:
        raise AgentServiceError(
            "a dataset selection belongs to a Dataset Finder attachment", 400
        )
    target = record.get("target") or {}
    if target.get("kind") != "node":
        raise AgentServiceError(
            "a dataset selection belongs to a Dataset Finder attached to a node", 400
        )
    session_id = record.get("sessionId")
    turns = (
        sessions.read_turns(user_key, project_id, session_id)
        if isinstance(session_id, str) else []
    )
    part = next(
        (
            p for turn in reversed(turns) for p in (turn.get("content") or [])
            if isinstance(p, dict) and p.get("type") == "datasetCandidates"
        ),
        None,
    )
    try:
        rows = dataset_resolution.resolve_picks(part, picks)
    except dataset_resolution.DatasetResolutionError as exc:
        raise AgentServiceError(str(exc), 422) from exc
    # Re-probe the external picks: the card may be minutes or days old, and the
    # record must carry what is true NOW (the row keeps its own mint-time
    # verdict in the transcript either way).
    budget = egress.CallBudget(_RUN_EGRESS_CALLS)
    for row in rows:
        if row["lane"] == "external" and row.get("url"):
            row["verification"] = verify.verify_external_source(row["url"], budget=budget)
    with projects_storage.spec_write_lock(user_key, project_id):
        fresh = _read_spec_or_404(user_key, project_id)
        state = dataset_resolution.record_selection(fresh, attachment_id, rows)
        if state is None:
            raise AgentServiceError(f"attachment {attachment_id!r} not found", 404)
        projects_storage.write_spec(user_key, project_id, fresh)
    if isinstance(session_id, str):
        try:
            names = ", ".join(str(r.get("name") or r.get("datasetId") or r.get("url")) for r in rows)
            lines = [
                f"{r['lane']} · {r.get('name') or r.get('datasetId') or r.get('url')}"
                + (f" · {(r.get('verification') or {}).get('status')}"
                   if r["lane"] == "external" else
                   (" · installed" if r.get("installed") else " · not installed yet"))
                for r in rows[:8]
            ]
            sessions.append_turns(
                user_key, project_id, session_id, attachment_id,
                [sessions.make_turn(
                    "agent",
                    f"Source recorded for this node: {names}."
                    + (" The dataset must be installed from the Data Catalog before "
                       "Solve can load it."
                       if state["status"] == dataset_resolution.STATE_AWAITING_INSTALL else
                       " Solve the node to build its loader from this source."
                       if state["status"] == dataset_resolution.STATE_RESOLVED else
                       " Nothing selectable was confirmed — the runtime could not reach it."),
                    content=[{
                        "type": "card",
                        "kind": "result" if state["status"] != dataset_resolution.STATE_CANDIDATES_PENDING
                        else "error",
                        "title": "Dataset selection recorded",
                        "lines": lines,
                    }],
                )],
            )
        except Exception:  # noqa: BLE001
            log.warning("Could not log the dataset selection for %s", attachment_id,
                        exc_info=True)
    return {
        "attachmentId": attachment_id,
        "nodeId": target.get("targetId"),
        "status": state["status"],
        "picks": rows,
    }


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
    # DEC-080 (dev/126): a plan apply attaches the plan-node agents, so the
    # closure is completed BEFORE the apply reads the lockfile it consults.
    if _repair_required_closure(
        user_key, project_id, record.get("coord", ""), attachment_id=attachment_id
    ):
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
    *,
    extra_parts: list[dict] | None = None,
) -> None:
    """Mark applied + append the result-card turn (mutation_applied, dev/03:344).
    ``extra_parts`` (dev/105 A3, additive) ride the same turn after the result
    card — the follow-up proposal cards an apply queued, rendered below it."""
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
                content=[{"type": "card", "kind": "result", "title": title, "lines": lines}]
                + list(extra_parts or []),
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
    # dev/114 (DEC-072): a new type's first-node content passes the same gate
    # for path/URL literals (the no-source rule needs a known data-loading
    # type, which a brand-new template is not).
    verdict, refusal = _gate_generated_content(
        user_key, project_id, loop_ctx,
        code=code, engine=engine, node_type=None, params=params, is_data_loading=False,
    )
    if refusal:
        return _refuse_params(refusal)
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
    if verdict.source:
        part["source"] = verdict.source  # dev/114
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
        if plan_topology.is_interaction_edge(edge):
            continue  # dev/112: feedback edges take no input port (parity with _plan_edge_context)
        target = edge.get("target")
        surviving_in[target] = surviving_in.get(target, 0) + 1
    incoming: dict[str, list[str]] = {}
    for edge in plan.get("edges", []):
        if plan_topology.is_interaction_edge(edge):
            continue  # dev/112
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


def _interaction_spec_edge(source: str, target: str) -> dict:
    """dev/112: the spec shape of a Trill Interaction edge — what
    ``TrillGenerator`` writes and ``loadTrill`` reads (``in/out`` both ends,
    bidirectional on the canvas)."""
    return {
        "id": str(uuid.uuid4()),
        "source": source,
        "target": target,
        "sourceHandle": "in/out",
        "targetHandle": "in/out",
        "type": plan_topology.INTERACTION_EDGE_TYPE,
    }


def _topology_clause(spec: dict) -> str:
    """dev/112 (G5): the applied turn's verdict on the saved graph — what the
    agent reads to confirm a repair instead of asserting one. A cycle the plan
    could not have created (the user drew it) is reported here, never refused."""
    dataflow = spec.get("dataflow") or {}
    nodes = {n.get("id"): n for n in dataflow.get("nodes") or [] if isinstance(n, dict)}
    pairs = plan_topology.net_data_edges(dataflow.get("edges") or [], {"edges": []}, set(), set())
    path = plan_topology.find_data_cycle(pairs)
    if path is None:
        return "Topology: acyclic."
    return "Topology: cycle through " + plan_topology.format_cycle(
        path, lambda x: (nodes.get(x) or {}).get("goal") or x
    ) + "."


def _removal_phrase(n_nodes: int, n_edges: int, *, prefix: str = "removed ") -> str:
    """dev/112: ``, removed 1 node and 2 connections`` — truthful for edges
    (the old copy counted nodes only, so an edge-only removal read "removed 0
    nodes"). Empty when nothing was removed."""
    parts = []
    if n_nodes:
        parts.append(f"{n_nodes} node{'s' if n_nodes != 1 else ''}")
    if n_edges:
        parts.append(f"{n_edges} connection{'s' if n_edges != 1 else ''}")
    return f", {prefix}" + " and ".join(parts) if parts else ""


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
    #
    # dev/99 R1.2: resolved as a BATCH — one store snapshot for the whole plan
    # instead of one per node. Resolving per node re-walked the store (and,
    # once readers hold the seed lock, re-acquired it) once per plan node, so
    # the cost scaled with plan size; it also judged each node against a
    # different instant.
    outcomes = packages_services.resolve_templates(
        user_key, project_id,
        [node["nodeType"] for node in plan["nodes"]],
        require_authorable=False,
    )
    for node, (entry, err) in zip(plan["nodes"], outcomes):
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
    # dev/112 (DEC-070): topology validated BEFORE anything materializes, like
    # fan-in. (1) Interaction edges obey the preamble's rule (visualization ↔
    # data-pool) — an executable rule, not prose the model must infer. (2) No
    # plan DATA edge may close a cycle in the NET graph. Before this, an
    # agent asked to "make it an interaction edge" had its kind dropped by
    # the grammar and re-applied the same data edge — the same cycle — on
    # every round; the only enforcement was the execution runner's refusal,
    # which the agent never saw.
    plan_types = {n["ref"]: n["nodeType"] for n in plan["nodes"]}

    def _type_of_endpoint(endpoint: str):
        if endpoint in plan_types:
            return plan_types[endpoint]
        node = existing_nodes.get(endpoint)
        return node.get("type") if node else None

    kind_errors = plan_topology.interaction_edge_errors(plan, _type_of_endpoint)
    if kind_errors:
        return "refused", "\n- ".join(["the plan wires invalid interaction edges:"] + kind_errors), None
    net_pairs = plan_topology.net_data_edges(
        existing_edges, plan, remove_node_set, set(remove_edges)
    )
    closing = plan_topology.closing_plan_edges(net_pairs, plan)
    if closing:
        def _label(node_id: str) -> str:
            return _plan_endpoint_label(node_id, plan, existing_nodes)
        cycle_errors = [
            f"edge {_label(u)!r} → {_label(v)!r} closes a cycle: "
            + plan_topology.format_cycle(path, _label)
            for u, v, path in closing[:5]
        ]
        return (
            "refused",
            "\n- ".join(
                ["the plan creates a cycle in the dataflow (data edges must form a DAG):"]
                + cycle_errors
                + [
                    "remove one data edge of the loop, or — for a visualization feeding "
                    "back into a data-pool — make that edge \"kind\": \"interaction\""
                ]
            ),
            None,
        )
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
        # dev/112: removed connections counted too — the user approved edge
        # removals five times without seeing them named.
        summary += _removal_phrase(len(remove_nodes), len(remove_edges), prefix="removes ")
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
                **({"kind": e["kind"]} if e.get("kind") else {}),  # dev/112
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
        # dev/112: removed connections reviewed by NAME too (DEC-049.2 applied
        # to edges) — endpoint labels from the saved spec, kind preserved.
        edges_by_id = {str(e.get("id")): e for e in existing_edges}
        part["plan"]["removedEdges"] = [
            {
                "id": edge_id,
                "fromLabel": _plan_endpoint_label(str(edges_by_id[edge_id].get("source")), plan, existing_nodes),
                "toLabel": _plan_endpoint_label(str(edges_by_id[edge_id].get("target")), plan, existing_nodes),
                **(
                    {"kind": "interaction"}
                    if plan_topology.is_interaction_edge(edges_by_id[edge_id])
                    else {}
                ),
            }
            for edge_id in remove_edges
            if edge_id in edges_by_id
        ]
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


#: dev/126: the agents a plan-created node carries. WHICH of them attaches to
#: a given node is the manifests' own compatibility declaration, read through
#: ``attachments.node_target_matches`` — the Node Builder accepts any node, the
#: Dataset Finder only a ``data-loading`` one (dev/50's ``requires``). No second
#: predicate lives here, so this list can never drift from the manifests.
_PLAN_NODE_AGENTS: tuple[str, ...] = ("agent.node-builder", "agent.dataset-finder")


def _installed_project_coord(spec: dict, agent_id: str) -> str | None:
    """The project lockfile's coord for *agent_id*, or None when absent."""
    from utk_curio.backend.app.agents import project_agents

    return next(
        (
            c for c in project_agents.project_agents(spec)
            if c.split("@", 1)[0] == agent_id
        ),
        None,
    )


def _node_attachment_of(spec: dict, agent_id: str, node_id: str) -> dict | None:
    """An existing attachment of *agent_id* on node *node_id*, or None."""
    for existing in attachments.list_attachments(spec):
        target = existing.get("target") or {}
        if (
            existing.get("coord", "").split("@", 1)[0] == agent_id
            and target.get("kind") == "node"
            and target.get("targetId") == node_id
        ):
            return existing
    return None


def _attach_node_agent(
    user_key: str | None, spec: dict, agent_id: str, node_id: str, node_type: object
) -> dict:
    """Attach ONE agent to a node, idempotently, reporting what happened.

    dev/126: the shared body of dev/71's plan-node attachment. Returns
    ``{"agentId", "attachmentId" | None, "status": "attached" | "existing" |
    "skipped", "reason"?}``. Never raises and never writes the spec — the
    caller's own single write persists it, and a node is never blocked over
    its agent."""
    existing = _node_attachment_of(spec, agent_id, node_id)
    if existing is not None:
        return {
            "agentId": agent_id,
            "attachmentId": existing.get("attachmentId"),
            "status": "existing",
        }
    coord = _installed_project_coord(spec, agent_id)
    if coord is None:
        return {"agentId": agent_id, "attachmentId": None, "status": "skipped",
                "reason": "not installed in this dataflow"}
    manifest = _resolve_definition(user_key, coord) if user_key else None
    if manifest is not None and not attachments.node_target_matches(manifest, node_type):
        return {"agentId": agent_id, "attachmentId": None, "status": "skipped",
                "reason": f"does not attach to {attachments.canonical_node_suffix(node_type)} nodes"}
    try:
        record = attachments.attach(
            spec, coord, {"kind": "node", "targetId": node_id},
            attachment_id=uuid.uuid4().hex, session_id=uuid.uuid4().hex,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not attach %s to node %s: %s", agent_id, node_id, exc)
        return {"agentId": agent_id, "attachmentId": None, "status": "skipped",
                "reason": str(exc)[:120]}
    return {"agentId": agent_id, "attachmentId": record.get("attachmentId"),
            "status": "attached"}


def _attach_plan_node_agents(
    user_key: str | None, spec: dict, node_id: str, node_type: object
) -> dict:
    """dev/126: every plan-created node gets its agents — the Node Builder
    always, the Dataset Finder when the node is a data-loading one — on BOTH
    apply paths, idempotently, in the caller's own spec write.

    Returns ``{"attached": [row], "skipped": [row], "byAgent": {agentId: id}}``
    so the apply can SAY what it attached instead of silently dropping it."""
    rows = [
        _attach_node_agent(user_key, spec, agent_id, node_id, node_type)
        for agent_id in _PLAN_NODE_AGENTS
    ]
    return {
        "attached": [
            {"nodeId": node_id, **r} for r in rows if r["status"] in ("attached", "existing")
        ],
        "skipped": [{"nodeId": node_id, **r} for r in rows if r["status"] == "skipped"],
        "byAgent": {
            r["agentId"]: r["attachmentId"] for r in rows if r.get("attachmentId")
        },
    }


def _attached_agent_lines(*results: dict) -> list[str]:
    """The applied card's truthful account of the agents an apply attached
    (dev/126): one line naming each agent and how many nodes carry it, plus a
    line for anything that could not be attached, with its reason."""
    counts: dict[str, int] = {}
    skipped: dict[str, str] = {}
    for result in results:
        for row in result.get("attached") or []:
            counts[row["agentId"]] = counts.get(row["agentId"], 0) + 1
        for row in result.get("skipped") or []:
            skipped.setdefault(row["agentId"], row.get("reason") or "skipped")
    lines: list[str] = []
    if counts:
        lines.append("agents attached: " + " · ".join(
            f"{_agent_label(a)} ×{n}" if n > 1 else _agent_label(a)
            for a, n in sorted(counts.items())
        ))
    for agent_id, reason in sorted(skipped.items()):
        lines.append(f"no {_agent_label(agent_id)}: {reason}")
    return lines


def _agent_label(agent_id: str) -> str:
    """A built-in's display name for a card line, id as the last resort."""
    manifest = builtin.get_builtin_manifest(f"{agent_id}@{builtin.BUILTIN_VERSION}")
    return getattr(manifest, "name", None) or agent_id


def _attach_node_builder(spec: dict, node_id: str, *, user_key: str | None = None,
                         node_type: object = None) -> str | None:
    """dev/71: best-effort Node Builder attachment for a plan-created node.
    Skips (returning None) when the template is not installed or the node
    already carries one — node creation NEVER fails over this. dev/126: one
    call into the shared body above."""
    row = _attach_node_agent(user_key, spec, "agent.node-builder", node_id, node_type)
    return row.get("attachmentId")


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
    # dev/126: and the Dataset Finder when the node is a data-loading one —
    # the same helper the whole-plan apply uses, so the two paths cannot
    # produce different graphs from the same plan.
    attached = _attach_plan_node_agents(user_key, spec, node_id, plan_node["nodeType"])
    attached_agent_id = attached["byAgent"].get("agent.node-builder")
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
                            *_attached_agent_lines(attached),
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
        # dev/126: every agent this apply gave the node, and anything it could
        # not — the apply SAYS what it attached instead of dropping it.
        "attachedAgents": attached["attached"],
        "skippedAgents": attached["skipped"],
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
    wants_interaction = plan_topology.is_interaction_edge(plan_edge)
    already = next(
        (
            e for e in ctx["edges"]
            if isinstance(e, dict)
            and e.get("source") == source and e.get("target") == target
            and plan_topology.is_interaction_edge(e) == wants_interaction
        ),
        None,
    )
    if already is not None:
        edge_states[key] = "applied"
        return {
            **row, "status": "applied", "edgeId": already.get("id"),
            "note": "already connected",
        }, None
    if wants_interaction:
        # dev/112: feedback edge — no input port, no merge slot, no cycle
        # question (interaction edges never carry data flow).
        edge = _interaction_spec_edge(source, target)
        ctx["edges"].append(edge)
        edge_states[key] = "applied"
        return {**row, "status": "applied", "edgeId": edge["id"], "kind": "interaction"}, edge
    # dev/112: a data edge that would close a cycle in the CURRENT graph is
    # refused per edge, named — the same predicate the mint applies.
    current_pairs = [
        (str(e.get("source")), str(e.get("target")))
        for e in ctx["edges"]
        if isinstance(e, dict) and not plan_topology.is_interaction_edge(e)
    ]
    closing = plan_topology.closing_plan_edges(current_pairs, {"edges": [{"from": source, "to": target}]})
    if closing:
        _, _, path = closing[0]
        labels = {nid: (n.get("goal") or nid) for nid, n in nodes_by_id.items()}
        edge_states[key] = "refused"
        return {
            **row, "status": "refused",
            "reason": "closes a cycle: " + plan_topology.format_cycle(path, lambda x: labels.get(x, x)),
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


def _tool_correction_message(errors: list[str]) -> dict:
    """The corrective round's feedback for a tool request (#245) — the
    ``_plan_correction_message`` twin: precise, model-actionable, and explicit
    that the invalid block never reached the user."""
    listed = "\n".join(f"- {e}" for e in errors[:10])
    return {
        "role": "user",
        "content": (
            "[tool validation] Your tool request block was invalid and was NOT "
            "shown to the user. Fix exactly these problems and resend the "
            "COMPLETE corrected block (same fence syntax):\n" + listed
        ),
    }


def _tool_cap_card(errors: list[str]) -> dict:
    """The visible outcome of a request attempt that never became proposable.

    Distinct from :func:`_round_cap_cutoff_card`, which reports a *valid*
    request dangling at the round cap. This one reports a request the runtime
    could never turn into a proposal, and it is the ONLY thing the user sees
    of that block — see ``_handle_tool_reply`` for why the raw JSON is dropped.
    """
    return {
        "type": "card",
        "kind": "error",
        "title": "Proposal not created",
        "lines": [e[:300] for e in errors[:10]],
    }


def _requested_tool_of(payload: object) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get("tool"), str):
        return payload["tool"]
    return None


def _handle_tool_reply(
    loop_ctx: dict,
    reply: str,
    parts: list,
    rounds_used: int,
) -> tuple[str, list, str | None, dict | None]:
    """In-loop toolRequest recovery (#245) — the dev/56 fence-agnostic scan and
    the dev/54 correction rounds that plans already have, for tool requests.

    Consulted ONLY after ``extract_content`` produced no request and
    ``_handle_plan_reply`` returned ``"none"``, so every existing path is
    byte-unchanged. ``extract_content`` itself is not touched: recovery lives
    here, exactly as ``extract_plan_attempt`` does for plans.

    Returns ``(kind, payload, visible_override, request)``:
    ``("none", parts, None, None)`` — not a request attempt, generic fail-open
    applies; ``("request", parts, stripped, req)`` — recovered, and the caller
    runs it through the ordinary request path (grant check, mint, and round
    accounting all unchanged); ``("correct", errors, None, None)`` — feed the
    errors back and re-round (shares the MAX_TOOL_ROUNDS budget, since a
    correction costs a real provider call); ``("cap", parts+card, stripped,
    None)`` — budget exhausted: fail loudly, never silently.
    """
    granted = loop_ctx.get("granted") or []
    if not granted:
        # A run with no tools cannot be attempting one — an agent quoting the
        # protocol keeps the pre-#245 fail-open behaviour exactly.
        return "none", parts, None, None

    def _claimed(payload: object) -> bool:
        """A request is ours to correct only when it names a GRANTED tool.

        Without this the runtime would 'correct' a model that merely echoed
        the literal ``{"tool": "<tool id>", "params": {}}`` out of the tail
        instruction — which is valid JSON — burning rounds on nothing.
        """
        tool = _requested_tool_of(payload)
        return tool is not None and tool in granted

    visible_override: str | None = None
    fence_guidance = (
        "put the tool request in a ```curio.v1 fenced block as the VERY LAST "
        "thing in your reply (not ```json, and with no text after it)"
    )

    _, tail_body = content.split_tail(reply)
    errors = content.tool_tail_diagnosis(tail_body)
    if errors:
        import json as _json

        try:
            tool = _requested_tool_of((_json.loads(tail_body) or {}).get("toolRequest"))
        except (ValueError, TypeError, AttributeError):
            tool = None
        if tool is not None and tool not in granted:
            return "none", parts, None, None
    else:
        # No terminal-tail attempt (or a valid one, which never reaches here):
        # scan every fence, wherever the model put it.
        stripped, raw = content.extract_tool_request_attempt(reply)
        if raw is None:
            return "none", parts, None, None
        if isinstance(raw, str):
            # Broken JSON: claim it only when it names a granted tool, so a
            # malformed block about something else stays the model's text.
            if not any(f'"{t}"' in raw for t in granted):
                return "none", parts, None, None
            errors = (content.tool_tail_diagnosis(raw) or []) + [fence_guidance]
        else:
            if not _claimed(raw):
                return "none", parts, None, None
            request, request_errors = content.parse_tool_request_verbose(raw)
            if request is not None:
                return "request", parts, stripped, request
            errors = request_errors + [fence_guidance]
        visible_override = stripped

    if rounds_used < MAX_TOOL_ROUNDS:
        return "correct", errors, None, None
    # The cap. Unlike a plan tail (dev/54 releases it — a plan is a spec the
    # user can read), a mutate request's params are an entire source file:
    # releasing it IS the bug this fixes (#245 — 60KB of Python rendered as
    # chat prose under an Apply button that never existed). The model's own
    # prose still shows; only the machine block drops, and the card names
    # precisely why, which is more actionable than the JSON ever was.
    if visible_override is None:
        visible_override, _ = content.split_tail(reply)
    return "cap", list(parts) + [_tool_cap_card(errors)], visible_override, None


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


def _resolve_catalog_dir_name(dir_name: str, rows: dict[str, dict]) -> tuple[dict | None, list[str]]:
    """Any spelling the roster teaches → the one Nodes Catalog row (dev/105 D1).

    The roster shows a package three ways — ``curio.notes@1`` (the dirName the
    proposal takes), ``curio.notes`` (the manifest id the model reads in
    prose), and ``curio.notes/note-surface`` (the template id the roster line
    LEADS with, optionally ``@major``). The live failure this fixes: a model
    quoted the second, the mint exact-matched the first, and the refusal
    pointed at a tool the agent did not hold. A spelling the system itself
    produced must never be refused for being that spelling (the dev/93
    posture, extended from node.create to package.install).

    Returns ``(row, [])`` on a unique hit, ``(None, candidates)`` when a bare
    package id matches more than one major — never guess a major — and
    ``(None, [])`` on a true miss. Pure: no store access, no second parser —
    the template-id form goes through :func:`canonical_template_id`.
    """
    from utk_curio.backend.app.packages.services import canonical_template_id

    row = rows.get(dir_name)
    if row is not None:
        return row, []
    package_id = dir_name
    if "/" in dir_name:  # a template id: keep only the package half
        package_id = canonical_template_id(dir_name).split("/", 1)[0]
    elif "@" in dir_name:  # a dirName whose major is not in the catalog
        return None, []
    candidates = sorted(
        name for name in rows if name.rsplit("@", 1)[0] == package_id
    )
    if len(candidates) == 1:
        return rows[candidates[0]], []
    return None, candidates


def _package_install_miss_hint(granted) -> str:
    """The way out of a dirName miss, naming ONLY sources this run can read
    (DEC-063: an instruction must be executable on the path it is given).
    The enlist roster is composed for every run holding package.install, so
    it is always nameable; packages.catalog only when granted."""
    hint = (
        "use the dirName shown in parentheses after '(package …)' in the "
        "'Installed but NOT enlisted in this project' list"
    )
    if "packages.catalog" in (granted or []):
        hint += ", or a dirName from packages.catalog results"
    return hint


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
        return _refuse_params("params.dirName must be a non-empty package dirName string")
    dir_name = dir_name.strip()
    try:
        rows = {
            r["dirName"]: r
            for r in packages_services.agent_catalog_overview(user_key, project_id)
        }
    except Exception as exc:  # a broken catalog is data, not a run error
        return "refused", f"the Nodes Catalog is unavailable: {exc}", None
    row, candidates = _resolve_catalog_dir_name(dir_name, rows)
    if row is None and candidates:
        return _refuse_params(
            f"package {dir_name!r} names more than one major in the Nodes Catalog — "
            f"propose exactly one of: {', '.join(candidates)}"
        )
    if row is None:
        return _refuse_params(
            f"package {dir_name!r} is not in the Nodes Catalog — "
            f"{_package_install_miss_hint(loop_ctx.get('granted'))}"
        )
    dir_name = row["dirName"]  # the canonical dirName is what gets pinned
    if row["builtin"]:
        return _refuse_params(
            f"package {row['name']!r} is built-in — always present, never proposed; "
            "tell the user it is already available"
        )
    if row["installed"]:
        return _refuse_params(
            f"package {row['name']!r} is already installed in this project — "
            "tell the user instead of proposing"
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    reason = params.get("reason")
    reason = reason.strip()[:_PACKAGE_REASON_MAX_CHARS] if isinstance(reason, str) else ""
    # dev/105 A3: the findings ride the ENLIST request as the A12 rows the
    # AUTHOR rung already carries — Apply enlists the package and then queues
    # one node.create card per row below this one (one parser: the dev/90
    # reader). Absent rows → enlist only, said so at Apply.
    notes = _notes_from_delegate_inputs({"notes": params.get("notes")}) or []
    proposal_id = uuid.uuid4().hex
    summary = f"Install package · {row['name']}" + (
        f" · {len(notes)} note{'s' if len(notes) != 1 else ''} to follow" if notes else ""
    )
    preview = reason or (row.get("description") or dir_name)
    if notes:
        preview += "\n\nNotes to follow:\n" + "\n".join(
            f"- {n.get('title') or 'Note'} · {n['content'][:80]}"
            + ("…" if len(n["content"]) > 80 else "")
            for n in notes
        )
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="package.install",
        summary=summary,
        preview=preview,
        pins={"dirName": dir_name},
    )
    proposal = {
        "proposalId": proposal_id,
        "tool": "package.install",
        "dirName": dir_name,
        "packageName": row["name"],
        "reason": reason,
        "summary": summary,
        "status": "pending",
    }
    if notes:
        proposal["notes"] = notes
    _store_proposal(user_key, project_id, spec, loop_ctx, proposal, part)
    return (
        "proposed",
        f"proposal {proposal_id} created to install package {row['name']!r}; it awaits "
        "the user's explicit review through the package install dialog — do NOT "
        "assume it was installed",
        part,
    )


# dev/96: the rich review card's bounded payload — parts persist with every
# turn (the A6 lesson), so every list carries a cap AND its true total; the
# card renders the slice, the overflow count keeps it honest.
_DRAFT_CARD_MAX_FILES = 20
_DRAFT_CARD_MAX_TEMPLATES = 10
_DRAFT_CARD_MAX_DEP_ROWS = 10
_DRAFT_CARD_MAX_FINDINGS = 10
_DRAFT_CARD_MAX_PREVIEW_TEMPLATES = 8
_DRAFT_CARD_MAX_PREVIEW_REASONS = 3
_DRAFT_CARD_MAX_NODES = 8
_FINDING_SEVERITY_ORDER = {"block": 0, "warn": 1, "note": 2}


def _draft_card_payload(request, result) -> dict:
    """dev/96: the diff, dependencies, and preview the Apply text has always
    CLAIMED the user reviewed — composed once at mint from the typed build
    result, bounded per list (cap + honest total, never silent truncation),
    and attached to the transcript part so the card renders it reload-safe.
    Absent sections stay absent; a plain dep-less create carries no
    Dependencies section at all."""
    card: dict = {"mode": request.mode, "target": request.target}

    diff = result.diff or {}
    files = diff.get("files") or {}
    card["files"] = {
        "added": [str(p) for p in (files.get("added") or [])[:_DRAFT_CARD_MAX_FILES]],
        "modified": [str(p) for p in (files.get("modified") or [])[:_DRAFT_CARD_MAX_FILES]],
        "addedTotal": len(files.get("added") or []),
        "modifiedTotal": len(files.get("modified") or []),
        # 0 is information — a create preserves nothing and SAYS so.
        "preservedTotal": len(files.get("preserved") or []),
    }
    templates = diff.get("templates") or {}
    card["templates"] = {
        "added": [str(t) for t in (templates.get("added") or [])[:_DRAFT_CARD_MAX_TEMPLATES]],
        "modified": [str(t) for t in (templates.get("modified") or [])[:_DRAFT_CARD_MAX_TEMPLATES]],
        "addedTotal": len(templates.get("added") or []),
        "modifiedTotal": len(templates.get("modified") or []),
        "preservedTotal": len(templates.get("preserved") or []),
    }

    sbom = (result.dependencies or {}).get("sbom") or {}
    python_rows = [
        {"name": str(r.get("name")), "constraint": str(r.get("constraint") or "*")}
        for r in (sbom.get("python") or []) if isinstance(r, dict)
    ]
    js_rows = [
        {"name": str(r.get("name")),
         "version": str(r.get("resolvedVersion") or r.get("constraint") or "*")}
        for r in ((sbom.get("js") or {}).get("direct") or []) if isinstance(r, dict)
    ]
    findings = [
        {"severity": str(f.get("severity")), "code": str(f.get("code")),
         "message": str(f.get("message"))[:300]}
        for f in (sbom.get("findings") or []) if isinstance(f, dict)
    ]
    # Blocks sort first: the cap must never hide a block behind notes.
    findings.sort(key=lambda f: _FINDING_SEVERITY_ORDER.get(f["severity"], 3))
    if python_rows or js_rows or findings:
        # dev/97: where the python deps will LIVE — the same routing rule
        # promote applies (one core, two adapters — the card can never
        # disagree with the install).
        from utk_curio.backend.app.packages.backend_runtime import (
            dep_destinations_raw,
        )

        home, _home_reason = dep_destinations_raw(request.manifest or {})
        card["dependencies"] = {
            "home": home,
            "python": python_rows[:_DRAFT_CARD_MAX_DEP_ROWS],
            "pythonTotal": len(python_rows),
            "js": js_rows[:_DRAFT_CARD_MAX_DEP_ROWS],
            "jsTotal": len(js_rows),
            "findings": findings[:_DRAFT_CARD_MAX_FINDINGS],
            "findingsTotal": len(findings),
            "blocked": bool(sbom.get("blocked")),
        }

    preview = result.preview
    if isinstance(preview, dict):
        states = preview.get("states") or {}
        template_rows = []
        for template_id in sorted(states)[:_DRAFT_CARD_MAX_PREVIEW_TEMPLATES]:
            per_state = states.get(template_id) or {}
            failed = sorted(
                state for state, payload in per_state.items()
                if isinstance(payload, dict) and payload.get("consoleErrors")
            )
            template_rows.append({
                "templateId": template_id,
                "ok": not failed,
                "failedStates": failed,
            })
        card["preview"] = {
            "status": str(preview.get("status") or "unknown"),
            "reasons": [str(r)[:300] for r in
                        (preview.get("reasons") or [])[:_DRAFT_CARD_MAX_PREVIEW_REASONS]],
            "reasonsTotal": len(preview.get("reasons") or []),
            "templates": template_rows,
            "runnerVersion": str(preview.get("runnerVersion") or ""),
        }

    if request.nodes:
        card["requestedNodes"] = {
            "rows": [
                {"title": node.title or node.template_id,
                 "color": (node.appearance or {}).get("backgroundColor", "")}
                for node in request.nodes[:_DRAFT_CARD_MAX_NODES]
            ],
            "total": len(request.nodes),
        }
    return card


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
    # dev/96: the diff/dependencies/preview slice rides the PART (the card's
    # reload-safe render source) — the Apply text's review claim, finally true.
    draft_card = _draft_card_payload(request, result)
    part["draft"] = draft_card
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
            "draftCard": draft_card,  # mirror copy — listing symmetry (dev/96)
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
    # dev/112 (DEC-070): topology re-checked against the CURRENT spec BEFORE
    # anything mutates (``_mark_stale`` persists the spec, so a later raise
    # would persist the removals). The shape digest already catches most
    # drift; this names the one case it cannot — a plan minted acyclic whose
    # edges now close a loop through edges the user drew since.
    pre_ref_to_id: dict[str, str] = dict(proposal.get("appliedNodeIds") or {})
    closing = plan_topology.closing_plan_edges(
        plan_topology.net_data_edges(
            edges, plan, set(plan.get("removeNodes", [])),
            set(plan.get("removeEdges", [])), pre_ref_to_id,
        ),
        plan, pre_ref_to_id,
    )
    if closing:
        u, v, path = closing[0]
        labels = {n.get("id"): (n.get("goal") or n.get("id")) for n in nodes if isinstance(n, dict)}
        plan_titles = {n["ref"]: n["title"] for n in plan.get("nodes", [])}
        def _lbl(x):  # noqa: E306
            return plan_titles.get(x) or labels.get(x) or x
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            "the canvas changed since this plan was proposed — applying it would now "
            f"close a cycle ({plan_topology.format_cycle(path, _lbl)}) — ask the agent to replan",
        )
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
    attached_results: list[dict] = []
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
        # dev/126: the whole-plan apply gives every created node its agents,
        # in THIS apply's single spec write — the per-node path has done so
        # since dev/71 and the two must not disagree.
        attached_results.append(
            _attach_plan_node_agents(user_key, spec, node_id, plan_node["nodeType"])
        )
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
        if plan_topology.is_interaction_edge(plan_edge):
            # dev/112: the Trill's feedback edge — in/out handles both ends,
            # type Interaction (what loadTrill/TrillGenerator round-trip); no
            # input port, no merge slot.
            edge = _interaction_spec_edge(source, target)
            edges.append(edge)
            created_edges.append(edge)
            continue
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
    # dev/112: truthful for edges (the old copy said "removed 0 nodes" after an
    # edge-only removal), plus the post-apply topology verdict the agent needs
    # to confirm a fix instead of asserting one.
    removed_summary = _removal_phrase(len(remove_node_set), len(removed_edge_ids))
    topology = _topology_clause(spec)
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: plan added {len(created_nodes)} nodes and "
        f"{len(created_edges)} connections{removed_summary}. {topology}",
        "Applied: dataflow plan",
        [
            f"+{len(created_nodes)} nodes · +{len(created_edges)} connections"
            + (f" · −{len(remove_node_set)} nodes" if remove_node_set else "")
            + (f" · −{len(removed_edge_ids)} connections" if removed_edge_ids else ""),
            f"{sum(1 for s in node_runs.values() if s == 'pending')} pending for Solve",
            *_attached_agent_lines(*attached_results),
            topology,
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
        # dev/126: as the per-node apply — what each created node was given.
        "attachedAgents": [row for r in attached_results for row in r["attached"]],
        "skippedAgents": [row for r in attached_results for row in r["skipped"]],
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
    # dev/126: a node that was waiting for exactly this dataset is resolved by
    # this install — the reviewed lane is what "awaiting-install" waited for.
    from utk_curio.backend.app.agents import dataset_resolution

    resolved_nodes = dataset_resolution.mark_dataset_installed(spec, dataset_id)
    projects_storage.write_spec(user_key, project_id, spec)
    name = str(item.get("title") or dataset_id)
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: dataset installed ({name}).",
        "Applied: dataset installed",
        [name, dataset_id,
         *([f"{len(resolved_nodes)} node(s) waiting for it can now be solved"]
           if resolved_nodes else []),
         f"proposal {proposal_id[:8]}"],
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
        install = packages_services.install_to_project(user_key, project_id, dir_name)
    except Exception as exc:
        raise _mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the package could not be installed: {exc}",
        ) from exc
    # pip counts matching metadata as satisfaction, so a wheel whose native
    # extension cannot load installs without complaint. The install already
    # asks whether the libraries import; keeping the answer here is what stops
    # the applied turn saying "package installed" over a package whose first
    # run raises. NOT a stale/refusal: the package is installed and the repair
    # (a matching GDAL, a conda-forge build) is the user's, so this is the last
    # place the failure is still attached to the package that brought it in.
    broken_line = _broken_library_line(install.get("importErrors"))
    # The install wrote the spec (the package lockfile); re-read so the
    # proposal mirror update below does not clobber the new entry.
    spec = _read_spec_or_404(user_key, project_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) or proposal
    proposal["status"] = "applied"
    projects_storage.write_spec(user_key, project_id, spec)
    name = str(proposal.get("packageName") or dir_name)
    # dev/105 A3: the findings that rode the request become the A16 sequence
    # of node.create cards BELOW this one — minted pending, applied one at a
    # time by the frontend walk so each note lands before the next card.
    follow_ups, note_parts, notes_line = _queue_enlisted_notes(
        user_key, project_id, spec, attachment_id, session_id, dir_name,
        proposal.get("notes") or [],
    )
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: package installed ({name}).{broken_line}{notes_line}",
        "Applied: package installed",
        [name, dir_name, f"proposal {proposal_id[:8]}"],
        extra_parts=note_parts,
    )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        "installedPackage": {"dirName": dir_name, "name": name},
        **({"importErrors": install["importErrors"]}
           if install.get("importErrors") else {}),
        # dev/105 A4: the lockfile CHANGED — the frontend must refresh its
        # package registry + project-packages store BEFORE the follow-up notes
        # paint, or they render "Loading node…" for a type it does not hold.
        "requiresRegistryRefresh": True,
        # dev/105 A3: ordered — the frontend applies them one after another.
        "followUpProposals": follow_ups,
    }


def _broken_library_line(import_errors) -> str:
    """`` rasterio cannot be imported (...).`` for the applied turn, or ``""``.

    One sentence, appended to the turn the user reads after Apply. The wording
    matches the frontend's ``dependencyFailureNotice`` deliberately: the same
    failure should not read as a different problem depending on whether a
    button or an agent reached it.
    """
    if not import_errors:
        return ""
    named = "; ".join(
        f"{lib} cannot be imported ({reason})"
        for lib, reason in sorted(import_errors.items())
    )
    return f" But {named}. Nodes needing it will fail until it is repaired."


def _queue_enlisted_notes(
    user_key: str,
    project_id: str,
    spec: dict,
    attachment_id: str,
    session_id: object,
    dir_name: str,
    notes: list,
) -> tuple[list[str], list[dict], str]:
    """dev/105 A3: mint the enlisted package's notes as ONE pending A16
    sequence of ``node.create`` proposals (row order) — through the ordinary
    mint, so titles and the A13 colors are exactly the commit-6 path — and
    return ``(proposal ids, proposal parts, log suffix)``. Nothing is
    inserted into the graph here; each card is applied by the frontend walk,
    one at a time. Honest degradation: no rows, no presentation template, or
    a row that fails to mint is SAID in the suffix, never silent."""
    if not notes:
        return [], [], " No notes rode this request — ask the Researcher to create them."
    from utk_curio.backend.app.packages.manifest import ManifestError, load_packageage_manifest
    from utk_curio.backend.app.packages.storage import user_packageages_dir

    try:
        manifest = load_packageage_manifest(user_packageages_dir(user_key) / dir_name)
    except (ManifestError, OSError) as exc:
        return [], [], f" Notes skipped: the package manifest is unreadable ({exc})."
    template = next(
        (t for t in manifest.templates if t.behavior and t.editor == "none"), None
    )
    if template is None:
        return [], [], (
            f" Notes skipped: {manifest.package_id} has no presentation (note) "
            "template — ask the Researcher to author one."
        )
    record = _record_or_404(spec, attachment_id)
    loop_ctx = {
        "attachment_id": attachment_id,
        "session_id": session_id if isinstance(session_id, str) else None,
        # The A13 default keys on the attached agent's capability, as in a run.
        "manifest": _resolve_definition(user_key, record.get("coord", "")),
    }
    node_type = f"{manifest.package_id}/{template.template_id}"
    ids: list[str] = []
    parts: list[dict] = []
    skipped: list[str] = []
    for row in notes:
        req = {"params": {
            "nodeType": node_type,
            "content": row["content"],
            **({"title": row["title"]} if row.get("title") else {}),
            **({"appearance": row["appearance"]} if row.get("appearance") else {}),
        }}
        status, text, part = _mint_node_create(user_key, project_id, loop_ctx, req)
        if status == "proposed" and part is not None:
            ids.append(part["proposalId"])
            parts.append(part)
        else:
            skipped.append(f"{row.get('title') or 'Note'}: {text}")
    line = f" {len(ids)} note{'s' if len(ids) != 1 else ''} queued below." if ids else ""
    if skipped:
        line += " Skipped — " + "; ".join(skipped) + "."
    return ids, parts, line


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
    # dev/92 B-2: the restart signal rides the result turn AND the payload —
    # pip actually changed shared libraries under the running server; nodes
    # keep the previously loaded versions until Curio restarts.
    restart = journal.get("restartRecommended")
    restart_line = ""
    if isinstance(restart, dict) and restart.get("libs"):
        restart_line = (
            " Restart Curio to pick up "
            + ", ".join(str(lib) for lib in restart["libs"])
            + " — running nodes keep the previously loaded versions until then."
        )
    # A declared library that installed but cannot be imported. Said here
    # because this turn is what claims the package was installed: pip counts
    # metadata as satisfaction, so without this the user reads "built and
    # installed" and meets the failure later as a node's ImportError.
    broken_imports = journal.get("importErrors")
    if isinstance(broken_imports, dict) and broken_imports:
        restart_line += (
            " Warning: "
            + "; ".join(
                f"{lib} installed but cannot be imported ({reason})"
                for lib, reason in sorted(broken_imports.items())
            )
            + " — nodes needing it will fail until it is repaired."
        )
    _log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: package {name} built and installed"
        + (f"; {len(created_nodes)} node(s) created." if created_nodes else ".")
        + restart_line,
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
        **({"restartRecommended": restart} if isinstance(restart, dict)
           and restart.get("libs") else {}),
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
        title=proposal.get("title"),  # dev/105 A2: the header the note renders
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
#: dev/118: measured from ``solvingSince``, which every wave boundary
#: refreshes — so "stale" means "no wave completed for 15 minutes", not "the
#: batch started 15 minutes ago".
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
    verify: bool = True,
) -> dict:
    """The dev/52 Solve batch (DEC-048), blocking form: drains the streaming
    batch (dev/63 — one implementation) and returns its terminal payload,
    minus the stream-only keys, so the response is byte-compatible. Always
    write mode — propose mode (dev/67-6) is the streaming route's.
    ``verify`` (dev/115): data-loading nodes execute before they are final."""
    payload: dict | None = None
    for kind, data in solve_attachment_stream(
        user_key, project_id, attachment_id, config, node_ids, verify=verify
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
    _reconcile_solve_session(user_key, project_id, spec, record)
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
    verify: bool = True,
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

    ``verify`` (dev/115, DEC-073): a data-loading node's content is not final
    until it has EXECUTED — the worker drives the one verified-content loop
    (generate → gate → run in the sandbox → correct with the traceback → run
    again, ≤2 corrections) and only code that passed is written (write mode)
    or minted (propose mode, with the validation block); exhaustion is
    ``failed`` with the attempt trail, a sandbox outage leaves the node
    ``pending`` with the reason. ``verify=False`` keeps the legacy path.
    """
    import threading
    import time as _time

    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    # DEC-080 (dev/126): Solve hard-invokes node.content.generate and, for a
    # data-loading node, dataset.discover — both required delegates, completed
    # before the batch resolves them.
    if _repair_required_closure(
        user_key, project_id, record.get("coord", ""), attachment_id=attachment_id
    ):
        spec = _read_spec_or_404(user_key, project_id)
        record = _record_or_404(spec, attachment_id)
    _reconcile_solve_session(user_key, project_id, spec, record)
    session = record.get("builderSession") or {}
    if not session.get("appliedPlanId"):
        raise AgentServiceError("nothing to solve — apply a plan first", 409)
    now = _time.time()
    if session.get("phase") == "solving" and now - float(session.get("solvingSince") or 0) < _SOLVE_STALE_SECONDS:
        raise AgentServiceError("a solve is already running for this plan", 409)
    try:
        # dev/115: refuse BEFORE persisting any in-flight state.
        agent_jobs.check_can_start(user_key, attachment_id)
    except agent_jobs.JobRefused as exc:
        raise AgentServiceError(str(exc), exc.status)
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
    # dev/115 (DEC-021): a Solve after an interruption is a NEW execution
    # linked to the expired one — recorded, never replayed.
    retry_of = session.pop("interruptedExecutionId", None) if session.get("phase") == "interrupted" else None
    session.pop("interruptedAt", None)
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
    # dev/115: everything that needs the REQUEST context is resolved here —
    # the job thread holds no ``g``: the batch's grounding base (catalog refs,
    # mission + plan texts) and the sandbox's dataset-path mapping.
    solve_ground = _solve_grounding_base(user_key, project_id, spec, nodes_by_id, targets)
    solve_dataset_paths = (
        _resolve_catalog_execution_paths(project_id, list(solve_ground.get("catalog_ids") or {}))
        if verify else {}
    )
    # dev/126: and the Data Catalog rows the discovery delegate is handed.
    solve_catalog_rows = _catalog_rows_for_discovery(user_key, project_id)
    events = _solve_events(
        user_key, project_id, attachment_id, config, targets, nodes_by_id,
        manifest, coord, session_id, solve_execution_id, stop,
        spec=spec, mode=mode, return_phase=return_phase, verify=verify,
        grounding_base=solve_ground, dataset_paths=solve_dataset_paths,
        catalog_rows=solve_catalog_rows,
        retry_of=retry_of if isinstance(retry_of, str) else None,
    )
    # dev/115 (DEC-021, single-process slice): the batch runs as a detached
    # job — the request only SUBSCRIBES (replay + tail); a disconnect no
    # longer ends the Solve, and a reload re-attaches through the jobs stream.
    job = agent_jobs.start_job(
        user_key=user_key, project_id=project_id, attachment_id=attachment_id,
        kind="solve-batch", job_id=solve_execution_id, events=events,
    )
    return agent_jobs.subscribe(job)


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
    verify: bool = True,
    grounding_base: dict | None = None,
    dataset_paths: dict | None = None,
    retry_of: str | None = None,
    catalog_rows: list | None = None,
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
    # dev/127: one bounded artifact preview per artifact per batch, turned into
    # the columns and dtypes its frame holds. A node that had to join two
    # frames used to be told only their TYPE and spent its whole budget
    # guessing a join key (memo dev/127 §1 D5).
    schema_cache: dict[str, dict | None] = {}

    def _schema_of_artifact(artifact_id: str) -> dict | None:
        if artifact_id in schema_cache:
            return schema_cache[artifact_id]
        from utk_curio.backend.app.agents import upstream_schema
        from utk_curio.backend.app.execution import runner as _runner

        summary = None
        try:
            preview = _runner.load_artifact_preview(artifact_id)
            summary = upstream_schema.summarize(preview) if preview else None
        except Exception:  # noqa: BLE001
            log.warning("Could not describe artifact %s", artifact_id, exc_info=True)
        schema_cache[artifact_id] = summary
        return summary
    delegations: list = []
    unstarted: list[str] = []
    started = time.monotonic()
    state = {"finished": False}
    payload_out: dict = {}
    # dev/106: a batch-level reason (the missing-specialist case) and the
    # proposal parts minted for it — the Solve turn carries them, so the
    # reviewed install is visible where the failure is, not only in the
    # attachment mirror.
    batch_reason: str | None = None
    extra_parts: list[dict] = []
    # dev/118 (DEC-075): waves. The spec the loop and the context composer see
    # is re-read after every wave's persist, so a downstream target executes
    # against the upstream content that actually ran; the outputs recorded for
    # passing upstream targets are handed to their dependents' corrections.
    current: dict = {"spec": spec, "wave": 0}
    wave_outputs: dict[str, dict] = {}
    persisted: set[str] = set()
    # dev/118: the batch's time budget (§3.6) — a bound, never a failure.
    deadline_s = solve_batch_deadline_s()
    deadline_reason = (
        f"the batch's time budget ({max(1, deadline_s // 60)} min) was spent — "
        "Retry continues from here"
    )

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

    # dev/114: ONE grounding base per batch (catalog paths, mission + plan
    # texts), built here in the request thread — workers hold no request
    # context; ONE egress budget for the batch's probes.
    # dev/115: the request thread resolved these (the generator body runs in
    # the job thread, which holds no request context); computing them here is
    # only the fallback for a direct caller.
    solve_ground = (
        grounding_base if grounding_base is not None
        else _solve_grounding_base(user_key, project_id, spec, nodes_by_id, targets)
    )
    solve_ctx: dict = {"granted": [], "manifest": manifest}
    solve_dataset_paths = (
        dataset_paths if dataset_paths is not None
        else (_resolve_catalog_execution_paths(project_id, list(solve_ground.get("catalog_ids") or {}))
              if verify else {})
    )
    from utk_curio.backend.app.packages import services as _pkg_services

    def _is_data_loading(node_obj: dict) -> bool:
        return source_grounding.is_data_loading_type(
            _pkg_services.canonical_template_id((node_obj or {}).get("type"))
        )

    batch_templates = _roster_templates(user_key, project_id)  # dev/119: ONE snapshot per batch

    def _is_executable(node_obj: dict) -> bool:  # dev/118 (DEC-075) → dev/119 (DEC-076)
        return _node_is_executable(node_obj, batch_templates)

    def _record_outcome(node_id: str, status: str, text, child) -> dict | None:
        nonlocal batch_reason
        if status == "deadline":
            # dev/118: the budget ran out before this node was dispatched — it
            # stays pending, says why, and the batch names the reason once.
            results[node_id] = {"status": "pending", "reason": deadline_reason}
            unstarted.append(node_id)
            batch_reason = batch_reason or deadline_reason
            return {"nodeId": node_id, "status": "pending", "reason": deadline_reason}
        """Fold one worker outcome into the batch state — no yields, so it is
        safe on the disconnect drain. Returns the node_result payload, or
        None for an unstarted (cancelled-before-dispatch) target, which stays
        ``pending`` — it was never attempted, so no new status enters the
        state machine."""
        if child is not None:
            delegations.append(child)
        if status == "verified":
            # dev/115 (DEC-073): the verified-content loop's outcome. Only
            # code that PASSED is written; exhaustion is failed with the
            # trail; a sandbox outage is pending with the reason — never a
            # content failure, never silently written.
            outcome = text
            for c in outcome.get("delegations") or []:
                if c is not None:
                    delegations.append(c)
            trail = {
                "verdict": outcome.get("verdict"),
                "rounds": outcome.get("rounds"),
                "attempts": outcome.get("attempts") or [],
                # dev/127: which bound ended the loop, all the way to the UI.
                "stoppedBy": outcome.get("stoppedBy"),
            }
            if outcome.get("verdict") == "pass":
                candidate = outcome.get("candidate") or ""
                results[node_id] = {"status": "solved", **trail}
                applied_contents.append({"nodeId": node_id, "content": candidate})
                wave_outputs[node_id] = {
                    "nodeId": node_id,
                    "goal": str((nodes_by_id.get(node_id) or {}).get("goal") or "")[:200],
                    "outputDataType": (outcome.get("evidence") or {}).get("outputDataType") or "",
                    "wave": current["wave"],
                    # dev/118 commit 4: the artifact a dependent's validation reuses.
                    "output": (outcome.get("evidence") or {}).get("output"),
                }
                return {"nodeId": node_id, "status": "solved", "content": candidate, **trail}
            evidence = outcome.get("evidence") or {}
            if outcome.get("verdict") == "not-executable" and (outcome.get("candidate") or "").strip():
                # dev/118 (DEC-075): a browser-rendered kind — written like the
                # legacy path writes, and SAID to be unexecuted, never "verified".
                candidate = outcome.get("candidate") or ""
                verification = {"status": "not-executable", "reason": str(evidence.get("detail") or "")[:300]}
                results[node_id] = {"status": "solved", "verification": verification, **trail}
                applied_contents.append({"nodeId": node_id, "content": candidate})
                return {"nodeId": node_id, "status": "solved", "content": candidate,
                        "verification": verification, **trail}
            if outcome.get("verdict") == "infrastructure":
                reason = (
                    "not verified — sandbox unreachable: "
                    + str(evidence.get("detail") or "")[:160]
                    + " — nothing was run or written; Retry when the sandbox is back"
                )[:300]
                results[node_id] = {"status": "pending", "reason": reason, **trail}
                return {"nodeId": node_id, "status": "pending", "error": reason, **trail}
            if outcome.get("verdict") == "awaiting-source":
                # dev/126: the node's source is with the USER now — the Dataset
                # Finder on this node proposed candidates (or said it found
                # none). Nothing was generated or written, so this is PENDING
                # with the reason, never a failure of content.
                reason = (
                    "awaiting your dataset selection — "
                    + str(evidence.get("detail") or "")[:240]
                )[:300]
                remedy = evidence.get("remedy") if isinstance(evidence.get("remedy"), dict) else None
                extra = {"remedy": remedy} if remedy else {}
                results[node_id] = {"status": "pending", "reason": reason, **trail, **extra}
                return {"nodeId": node_id, "status": "pending", "reason": reason,
                        **trail, **extra}
            kind = evidence.get("kind") or "fail"
            raw_detail = str(evidence.get("stderrTail") or evidence.get("detail") or "")
            if evidence.get("upstreamEmpty"):
                # dev/118 live fix: the upstream has no content (it failed, or
                # is not a target) — this node waits, pending with the reason;
                # Retry runs it once the upstream is solved or filled.
                reason = f"waiting — {raw_detail[:240]}" if raw_detail else "waiting — an upstream node has no content yet"
                results[node_id] = {"status": "pending", "reason": reason, **trail}
                return {"nodeId": node_id, "status": "pending", "reason": reason, **trail}
            if kind == "precondition":
                # dev/118 (DEC-075): the runner refused the SLICE (the 25-node
                # bound, a cycle) — a bound on validation, not a failure of the
                # content: skipped, with the bound named.
                reason = f"skipped — {raw_detail[:240]}" if raw_detail else "skipped — validation refused the slice"
                results[node_id] = {"status": "skipped", "reason": reason, **trail}
                return {"nodeId": node_id, "status": "skipped", "reason": reason, **trail}
            # dev/127: a refusal's head names the literal; a traceback is read
            # for its exception line and frame, never sliced by character count
            # (the report's "execution-error: das/core/generic.py" was the tail
            # of pandas/core/generic.py, cut mid-path).
            detail = (
                failure_text.excerpt(raw_detail, limit=200, head=True)
                if kind in _HEAD_FIRST_KINDS
                else failure_text.summary(
                    raw_detail,
                    code=_last_attempt_code(trail),
                    limit=200,
                )
            )
            rounds = outcome.get("rounds") or 0
            remedy_payload = evidence.get("remedy") if isinstance(evidence.get("remedy"), dict) else None
            remedy = (
                _ungrounded_remedy(_dataset_finder_attachment_id(spec, node_id))
                if kind == "ungrounded-source" else
                _source_missing_remedy(remedy_payload)
                if kind == "source-missing" else ""
            )
            bound = _stopped_by_clause(outcome.get("stoppedBy"))
            err = (
                f"not fixed after {rounds} attempt{'s' if rounds != 1 else ''}{bound} — "
                f"{kind}: {detail[:200 - len(remedy)] if remedy else detail}{remedy}"
            )[:300]
            extra = {"remedy": remedy_payload} if remedy_payload else {}
            results[node_id] = {"status": "failed", "error": err, **trail, **extra}
            return {"nodeId": node_id, "status": "failed", "error": err, **trail, **extra}
        if status == "solved":
            # The child replies with response formatting around the code —
            # only the executable content is written (dev/57).
            text_out = content.extract_node_content(text)
            # dev/114 (DEC-072): the gate — a fabricated path or an
            # unverified URL never reaches the spec; the node fails LOUDLY
            # with the literal and the remedy named.
            node = nodes_by_id.get(node_id) or {}
            _verdict, refusal = _gate_generated_content(
                user_key, project_id, solve_ctx,
                code=text_out, engine="python", node_type=node.get("type"),
                base=solve_ground,
            )
            if refusal:
                err = (
                    "ungrounded source: " + refusal.split("Allowed sources:")[0]
                    .replace("source grounding refused — ", "").strip()
                )[:220] + _ungrounded_remedy(_dataset_finder_attachment_id(spec, node_id))
                results[node_id] = {"status": "failed", "error": err[:300]}
                return {"nodeId": node_id, "status": "failed", "error": err[:300]}
            result: dict = {"status": "solved"}
            if not _is_executable(node):
                # dev/118 (DEC-075): written like before, and SAID to be unexecuted.
                result["verification"] = {
                    "status": "not-executable",
                    "reason": f"{node.get('type')} has no code the sandbox could run — written, not executed",
                }
            results[node_id] = result
            applied_contents.append({"nodeId": node_id, "content": text_out})
            return {"nodeId": node_id, "status": "solved", "content": text_out, **(
                {"verification": result["verification"]} if "verification" in result else {}
            )}
        if status == "failed":
            err = (text or "")[:300]
            results[node_id] = {"status": "failed", "error": err}
            return {"nodeId": node_id, "status": "failed", "error": err}
        if status == "skipped":
            results[node_id] = {"status": "skipped"}
            return {"nodeId": node_id, "status": "skipped"}
        unstarted.append(node_id)
        return None

    def _apply_contents(spec_doc: dict) -> None:
        """Write every solved content not yet persisted into *spec_doc*,
        re-guarded against the CURRENT nodes (deleted → skipped; a user edit
        wins). Shared by the per-wave persist and the final one (dev/118)."""
        current_nodes = {
            n.get("id"): n
            for n in (spec_doc.get("dataflow") or {}).get("nodes") or []
            if isinstance(n, dict)
        }
        for item in applied_contents:
            if item["nodeId"] in persisted:
                continue
            persisted.add(item["nodeId"])
            node = current_nodes.get(item["nodeId"])
            if node is None:
                results[item["nodeId"]] = {"status": "skipped"}  # deleted meanwhile
                continue
            if (node.get("content") or "").strip():
                results[item["nodeId"]] = {"status": "skipped"}  # user edit wins
                continue
            node["content"] = item["content"]

    def _persist_wave(wave_ids: list[str]) -> None:
        """dev/118 (DEC-075): the wave boundary IS the persist — and the
        heartbeat. Under the spec lock: the wave's solved contents land (the
        same guards as the final write), its nodeRuns say what happened, and
        ``solvingSince`` is refreshed so the stale marker means "no wave
        completed for 15 minutes". A process that dies between waves leaves
        every persisted wave in place (DEC-021: nothing replayed; Retry
        continues). The re-read spec is what the next wave runs against."""
        with projects_storage.spec_write_lock(user_key, project_id):
            spec_doc = _read_spec_or_404(user_key, project_id)
            record = _record_or_404(spec_doc, attachment_id)
            session = record.get("builderSession") or {}
            _apply_contents(spec_doc)
            node_runs = session.get("nodeRuns") or {}
            for nid in wave_ids:
                outcome = results.get(nid)
                if outcome and nid in node_runs and outcome.get("status") in ("solved", "failed", "skipped"):
                    node_runs[nid] = outcome["status"]
            session["nodeRuns"] = node_runs
            if session.get("phase") == "solving":
                session["solvingSince"] = time.time()
            record["builderSession"] = session
            projects_storage.write_spec(user_key, project_id, spec_doc)
        current["spec"] = spec_doc

    def _finish() -> dict:
        # One batched spec write: contents (re-guarded against the CURRENT
        # spec under the read-modify-write), statuses, and the exit phase —
        # plus the transcript card. Idempotent: exactly one persist per batch.
        # dev/118: the LAST wave's persist — earlier waves already landed.
        if state["finished"]:
            return payload_out
        state["finished"] = True
        cancelled = stop.is_set()
        with projects_storage.spec_write_lock(user_key, project_id):
            spec = _read_spec_or_404(user_key, project_id)
            record = _record_or_404(spec, attachment_id)
            session = record.get("builderSession") or {}
            node_runs = session.get("nodeRuns") or {}
            _apply_contents(spec)
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
            lines: list[str] = []
            for node_id, outcome in list(results.items())[:10]:
                line = f"{node_id[:8]} · {outcome['status']}"
                if outcome.get("verdict"):
                    # dev/115: the verified loop's verdict and, on failure,
                    # the attempt trail — one line per round, bounded.
                    rounds = outcome.get("rounds") or 0
                    line += f" · {outcome['verdict']} after {rounds} round{'s' if rounds != 1 else ''}"
                if outcome.get("reason") and outcome["status"] in ("pending", "skipped"):
                    line += f" — {str(outcome['reason'])[:120]}"
                lines.append(line)
                if outcome.get("verdict") == "fail":
                    for attempt in (outcome.get("attempts") or [])[:3]:
                        why = _attempt_why(attempt, limit=160)
                        lines.append(f"  round {attempt.get('round')}: {attempt.get('kind')} — {why}")
                        if attempt.get("endpointEvidence"):
                            lines.append(f"    endpoint: {str(attempt['endpointEvidence'])[:200]}")
            lines = lines[:24]
            # dev/127: every attempt, in the transcript, per node that has a
            # trail — the card's lines cannot carry code, so the trail is its
            # own part. Bounded: the first _MAX_ATTEMPT_PARTS nodes, then a
            # line naming the rest (each still reachable from its own chat).
            attempt_parts: list = []
            trailed = [
                (nid, outcome) for nid, outcome in results.items()
                if (outcome or {}).get("attempts")
                and (outcome or {}).get("status") in ("failed", "pending", "skipped")
            ]
            for nid, outcome in trailed[:_MAX_ATTEMPT_PARTS]:
                node = nodes_by_id.get(nid) or {}
                part = _solve_attempts_part(
                    current.get("spec") or spec, nid,
                    str(node.get("goal") or nid)[:120], outcome,
                )
                if part is not None:
                    attempt_parts.append(part)
            if len(trailed) > _MAX_ATTEMPT_PARTS:
                lines.append(
                    f"{len(trailed) - _MAX_ATTEMPT_PARTS} more node(s) have attempt trails — "
                    "open each node's agent to read them"
                )
            if cancelled:
                lines.append(f"cancelled — {len(unstarted)} node(s) not attempted")
            if batch_reason:
                # ONE reason line for the batch (not six identical ones).
                lines.append(f"reason: {batch_reason}")
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
                        }, *attempt_parts, *extra_parts],
                        execution=_execution_record(
                            solve_execution_id,
                            {"coord": coord, "provider": config.api_type,
                             "model": config.model, "tools": [], "intentEdited": False},
                            {}, started, "ok", delegations=delegations,
                            retry_of=retry_of,
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
        if batch_reason:
            payload_out["reason"] = batch_reason
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
                specialist = resolution.manifest.name if resolution.manifest else resolution.coord
                status, text, part = _mint_project_install(
                    user_key, project_id, loop_ctx,
                    resolution.coord,
                    specialist,
                    "node.content.generate",
                )
                if status == "proposed" and part is not None:
                    extra_parts.append(part)
                    reason = (
                        f"specialist not installed — {specialist} ({resolution.coord}) is not "
                        "installed in this project; an install proposal awaits review below — "
                        "Apply it, then Retry"
                    )
                else:
                    # dev/106: an unminted proposal is never claimed (the
                    # refusal text says what to do instead).
                    reason = f"specialist not installed — {text}"
            else:
                reason = "no installed agent declares node.content.generate"
            batch_reason = reason
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
                    if _batch_deadline_spent(started, deadline_s):
                        outcome_queue.put((node_id, "deadline", None, None))
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
                    wave_spec = current["spec"]
                    upstream_outputs = _upstream_outputs_for(
                        wave_spec, node_id, wave_outputs, schema_fn=_schema_of_artifact,
                    )
                    inputs = {
                        "nodeType": node.get("type"),
                        "intent": node.get("goal"),
                        "planSiblings": goals[:20],
                        "nodeContext": node_context.compose_node_context(
                            user_key, project_id, wave_spec, node_id
                        ),
                    }
                    if upstream_outputs:
                        # dev/118: what the nodes feeding this one actually
                        # produced when they ran — a type to write against.
                        inputs["upstreamOutputs"] = upstream_outputs
                    # dev/114: the seventh DEC-063 application — a data-
                    # loading child is HANDED its grounded sources.
                    from utk_curio.backend.app.packages import services as _pkg

                    if source_grounding.is_data_loading_type(
                        _pkg.canonical_template_id(node.get("type"))
                    ):
                        inputs["sourceGrounding"] = _source_grounding_inputs(
                            _grounding_context(
                                user_key, project_id, solve_ctx,
                                node_type=node.get("type"), base=solve_ground,
                                extra_texts=(str(node.get("goal") or ""),),
                            )
                        )
                    if verify and _is_executable(node):
                        # dev/115 (DEC-073) → dev/118 (DEC-075): the ONE
                        # verified-content loop for EVERY executable kind —
                        # every round traced at the node's home (dev/72), the
                        # loop's progress relayed as node_* events, the outcome
                        # folded by _record_outcome.
                        def _traced(delegate_inputs, _node_id=node_id):
                            st, tx, ch, _h = _run_delegate_traced(
                                user_key, project_id, resolution.coord,
                                "node.content.generate", delegate_inputs, config,
                                parent_execution_id=solve_execution_id,
                                parent_coord=coord,
                                attachment_id=attachment_id,
                                node_id=_node_id,
                                home_create=False,  # workers never write the spec
                            )
                            return st, tx, ch

                        gen = _verified_content_rounds(
                            user_key, project_id,
                            spec=wave_spec, node=node, resolution=resolution, config=config,
                            parent_execution_id=solve_execution_id, parent_coord=coord,
                            attachment_id=attachment_id, exec_fn=None,
                            grounding_loop_ctx=solve_ctx, grounding_base=solve_ground,
                            extra_inputs={"planSiblings": goals[:20],
                                          **({"upstreamOutputs": upstream_outputs} if upstream_outputs else {})},
                            delegate_runner=_traced,
                            dataset_paths_fn=lambda codes: _filter_dataset_paths(
                                solve_dataset_paths, codes
                            ),
                            exec_user_key=user_key,
                            secrets_fn=_exec_secrets_resolver(user_key),
                            prior_outputs_fn=lambda: {
                                nid: o["output"] for nid, o in wave_outputs.items() if o.get("output")
                            },
                            # dev/126: the batch resolves a data-loading node's
                            # source before generating for it.
                            resolve_source=_source_resolver(
                                user_key, project_id, coord=coord,
                                attachment_id=attachment_id,
                                execution_id=solve_execution_id, config=config,
                                manifest=manifest,
                                extra_texts=(str((spec.get("dataflow") or {}).get("task") or ""),),
                                catalog_rows=catalog_rows,
                            ),
                        )
                        try:
                            while True:
                                kind, data = next(gen)
                                outcome_queue.put((node_id, "progress", {"kind": kind, **data}, None))
                        except StopIteration as stop_iter:
                            outcome_queue.put((node_id, "verified", stop_iter.value, None))
                        return
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
            waves = _solve_waves(spec, list(targets))
            try:
                for wave_no, wave in enumerate(waves, 1):
                    current["wave"] = wave_no
                    if _should_stop():
                        # Cancelled between waves: nothing here was dispatched.
                        for nid in wave:
                            _record_outcome(nid, "unstarted", None, None)
                        continue
                    if _batch_deadline_spent(started, deadline_s):
                        # dev/118: out of time before this wave — its targets
                        # stay pending with the reason; Retry continues.
                        for nid in wave:
                            event = _record_outcome(nid, "deadline", None, None)
                            if event is not None:
                                yield "node_result", event
                        continue
                    yield "solve_wave", {"wave": wave_no, "of": len(waves), "nodeIds": list(wave)}
                    for target in wave:
                        pool.submit(_solve_one, target)
                    remaining = len(wave)
                    while remaining:
                        node_id, status, text, child = outcome_queue.get()
                        if status == "started":
                            yield "node_started", {"nodeId": node_id}
                            continue
                        if status == "progress":
                            # dev/115: the verified loop's rounds, live — the strip
                            # shows "verifying" and each round's verdict.
                            progress = dict(text)
                            kind = progress.pop("kind", "")
                            event_name = _SOLVE_PROGRESS_EVENTS.get(kind)
                            if event_name:
                                yield event_name, {"nodeId": node_id, **progress}
                            continue
                        remaining -= 1
                        if mode == "propose" and status == "verified":
                            # dev/115: an EXECUTED review — the validation block
                            # (verdict, rounds, attempts) rides the part, PASS or
                            # FAIL (dev/67-7's labeled choice); a sandbox outage
                            # mints nothing and the node stays pending.
                            outcome = text
                            for c in outcome.get("delegations") or []:
                                if c is not None:
                                    delegations.append(c)
                            if outcome.get("verdict") == "infrastructure":
                                event = _record_outcome(node_id, "verified", outcome, None)
                                if event is not None:
                                    yield "node_result", event
                                continue
                            validation_block = {
                                "verdict": outcome.get("verdict"),
                                "rounds": outcome.get("rounds"),
                                "evidence": outcome.get("evidence") or {},
                                "attempts": outcome.get("attempts") or [],
                            }
                            part, home_att, mint_text = _mint_content_review_from_delegate(
                                user_key, project_id,
                                node_id=node_id,
                                generated_text=outcome.get("candidate") or "",
                                parent_attachment_id=attachment_id,
                                parent_session_id=session_id,
                                local_turn=True,
                                validation=validation_block,
                                grounding_base=solve_ground,
                            )
                            if part is not None:
                                results[node_id] = {
                                    "status": "proposed",
                                    "proposalId": part["proposalId"],
                                    "proposalAttachmentId": home_att,
                                    "verdict": validation_block["verdict"],
                                    "rounds": validation_block["rounds"],
                                    "attempts": validation_block["attempts"],
                                }
                                yield "node_result", {
                                    "nodeId": node_id,
                                    "status": "proposed",
                                    "proposalId": part["proposalId"],
                                    "proposalAttachmentId": home_att,
                                    "verdict": validation_block["verdict"],
                                    "rounds": validation_block["rounds"],
                                }
                            else:
                                results[node_id] = {"status": "failed", "error": mint_text[:300]}
                                yield "node_result", {
                                    "nodeId": node_id, "status": "failed", "error": mint_text[:300],
                                }
                            continue
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
                            # dev/114: the gate runs on the batch base BEFORE the
                            # mint so the node's failure names the source.
                            _pnode = nodes_by_id.get(node_id) or {}
                            _v, _refusal = _gate_generated_content(
                                user_key, project_id, solve_ctx,
                                code=content.extract_node_content(text), engine="python",
                                node_type=_pnode.get("type"), base=solve_ground,
                            )
                            if _refusal:
                                err = ("ungrounded source: " + _refusal.split("Allowed sources:")[0]
                                       .replace("source grounding refused — ", "").strip())[:220] + \
                                      _ungrounded_remedy(
                                          _dataset_finder_attachment_id(spec, node_id))
                                results[node_id] = {"status": "failed", "error": err[:300]}
                                yield "node_result", {"nodeId": node_id, "status": "failed", "error": err[:300]}
                                continue
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
                    if wave_no < len(waves):
                        # dev/118: the wave boundary persists and heartbeats;
                        # the next wave runs against what actually landed.
                        _persist_wave(list(wave))
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


# dev/67-7: bounded self-correction — an initial generation plus corrective
# regenerations, each re-validated by actually running the dataflow.
#
# dev/127: the bound used to be a hard, unconfigurable 2 (three attempts), and
# the owner's failing batch spent it in 25 SECONDS against a 300 s sandbox
# timeout and a 45-minute batch deadline: the loop stopped for want of a round
# with both budgets essentially untouched. It is now a round cap AND a per-node
# wall budget, whichever binds first, both env-overridable on the
# ``exec_timeout_s`` pattern (an unusable value falls back rather than raising).
DEFAULT_SOLVE_CORRECTION_ROUNDS = 5  # → six attempts
DEFAULT_SOLVE_NODE_BUDGET_S = 300  # the owner's five minutes


def _positive_int_env(name: str, default: int) -> int:
    import os as _os

    raw = _os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return value if value > 0 else default


def solve_correction_rounds() -> int:
    """``CURIO_SOLVE_CORRECTION_ROUNDS`` — corrections after the first
    generation (so attempts = this + 1)."""
    return _positive_int_env("CURIO_SOLVE_CORRECTION_ROUNDS", DEFAULT_SOLVE_CORRECTION_ROUNDS)


def solve_node_budget_s() -> int:
    """``CURIO_SOLVE_NODE_BUDGET`` — the wall-clock budget one node's repair
    loop may spend. Checked at round BOUNDARIES: a round already running is
    never killed (its own sandbox timeout bounds it), but no new round starts
    past the budget."""
    return _positive_int_env("CURIO_SOLVE_NODE_BUDGET", DEFAULT_SOLVE_NODE_BUDGET_S)


#: The widest the loop may ever go, whatever the env says — the trail, the
#: transcript part and the egress budget are all sized from it.
MAX_SOLVE_CORRECTION_ROUNDS = 12


def _solve_waves(spec: dict | None, targets: list[str]) -> list[list[str]]:
    """dev/118 (DEC-075): the batch's topological waves over its OWN targets.
    Depth 0 = no target upstream (an upstream that is not a target already has
    content, or will be named as a blocker honestly); depth k = one more than
    the deepest target upstream. Data-flow edges only (Interaction edges carry
    selection state). Targets caught in a cycle land in one last wave — the
    runner refuses a cyclic slice by name. Order within a wave is the
    targets' own."""
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    targets = [t for t in targets if isinstance(t, str)]
    target_set = set(targets)
    try:
        wf = parse_workflow_dict(spec or {})
        upstream = {t: [u for u in wf.upstream_nodes(t) if u in target_set and u != t] for t in targets}
    except Exception:
        return [list(targets)] if targets else []
    depth: dict[str, int] = {}
    remaining = list(targets)
    while remaining:
        progressed = False
        for t in list(remaining):
            ups = upstream.get(t, [])
            if all(u in depth for u in ups):
                depth[t] = 1 + max((depth[u] for u in ups), default=-1)
                remaining.remove(t)
                progressed = True
        if not progressed:
            last = max(depth.values(), default=-1) + 1
            for t in remaining:
                depth[t] = last
            break
    return [[t for t in targets if depth[t] == d] for d in sorted(set(depth.values()))]


#: dev/127: how far the walk looks through nodes that produced no artifact of
#: their own (a merge-flow, a data pool) before giving up.
_UPSTREAM_WALK_MAX_DEPTH = 4
_UPSTREAM_ROWS_MAX = 12


def _upstream_outputs_for(
    spec: dict | None,
    node_id: str,
    wave_outputs: dict,
    *,
    schema_fn=None,
) -> list[dict]:
    """What the nodes feeding this one actually produced (dev/118, dev/127).

    dev/118 listed the direct upstreams that had passed earlier in the batch —
    which skipped the case that mattered: a ``merge-flow`` is written but never
    executed (``DEC-075``), so it holds no output, so a node fed THROUGH one
    was handed an empty list and had to invent its inputs (memo dev/127 §1 D5,
    the owner's join that guessed ``community_area`` three times).

    So the walk goes THROUGH a node that produced nothing, into its own
    upstreams, in ``in_0…in_n`` order — which is the order the child will index
    as ``arg[0]``, ``arg[1]`` — and each row carries ``argIndex`` when it
    arrived that way. ``schema_fn`` (optional) turns a recorded artifact into
    the columns and dtypes it holds; an artifact it cannot describe leaves the
    row without a schema rather than with a guess.
    """
    if not wave_outputs:
        return []
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    try:
        graph = parse_workflow_dict(spec or {})
    except Exception:
        return []

    def _row(nid: str, arg_index: int | None) -> dict:
        record = wave_outputs[nid]
        row = {k: v for k, v in record.items() if k != "output"}
        if arg_index is not None:
            row["argIndex"] = arg_index
        if schema_fn is not None:
            artifact = (record.get("output") or {}).get("path")
            if artifact:
                try:
                    schema = schema_fn(artifact)
                except Exception:  # noqa: BLE001
                    schema = None
                if schema:
                    row["schema"] = schema
        return row

    def _walk(target: str, arg_index: int | None, depth: int) -> list[dict]:
        if depth > _UPSTREAM_WALK_MAX_DEPTH:
            return []
        try:
            ups = graph.upstream_nodes(target)
        except Exception:
            return []
        rows: list[dict] = []
        indexed = len(ups) > 1
        for index, up in enumerate(ups):
            slot = index if indexed else arg_index
            if up in wave_outputs:
                rows.append(_row(up, slot))
            else:
                # A node with no recorded output of its own (a merge, a pool,
                # or one that has not run): look through it, keeping the slot
                # order the child will index by.
                rows.extend(_walk(up, slot, depth + 1))
        return rows

    return _walk(node_id, None, 0)[:_UPSTREAM_ROWS_MAX]


_VANISHED_INPUT_MARKERS = (
    "could not be loaded", "not found", "no such file", "does not exist",
    "keyerror", "artifact", "outputs table", "no output",
)


def _looks_like_a_vanished_reused_input(result: dict | None) -> bool:
    """dev/118 commit 4: a failed round that ran with reused ancestor outputs,
    where the TARGET failed while loading its input — the artifact behind a
    reused record is gone, not the code wrong. Only when ancestors were
    actually reused; a failure with a named upstream blocker or of another
    shape is the candidate's own."""
    if not isinstance(result, dict) or result.get("verdict") != "fail":
        return False
    evidence = result.get("evidence") or {}
    if not evidence.get("reusedNodes") or evidence.get("kind") != "execution-error":
        return False
    text = str(evidence.get("stderrTail") or evidence.get("detail") or "").lower()
    return any(marker in text for marker in _VANISHED_INPUT_MARKERS)


def _node_is_executable(node_obj: dict | None, templates: dict | None = None) -> bool:
    """dev/118 (DEC-075) → dev/119 (DEC-076): the ONE executability predicate
    the batch, the per-node Solve and validate-node consult. With the roster
    snapshot the template's own facts decide; without one the legacy tables
    are the fallback."""
    from utk_curio.backend.app.execution.workflow_spec import is_executable_kind

    return is_executable_kind(str((node_obj or {}).get("type") or ""), templates)


def _roster_templates(user_key: str, project_id: str) -> dict | None:
    """dev/119: the roster snapshot for a project, or None when unreachable."""
    from utk_curio.backend.app.packages import services as _pkg

    return _pkg.roster_templates(user_key, project_id)
#: dev/115 F6 closure (2026-09-09): a run's egress budget describes what the
#: run legitimately does — every external candidate row the card may carry,
#: each allowed one redirect (a normal answer, not a cost the user should read
#: as "refused — budget spent"). ``egress.MAX_CALLS_PER_RUN`` stays the bound
#: on the MODEL's own web.fetch/web.search calls, a different budget.
_RUN_EGRESS_CALLS = content._CANDIDATES_MAX_ROWS_PER_LANE * 2
#: dev/118 (DEC-075): a Solve batch's wall-clock budget. Every node may cost
#: up to three rounds of a sandbox run each; the budget is what stops a wide
#: plan from running past any reasonable wait — what it did not reach reverts
#: to ``pending`` with the reason, and Retry continues from there.
DEFAULT_SOLVE_BATCH_DEADLINE_S = 45 * 60


def solve_batch_deadline_s() -> int:
    """``CURIO_SOLVE_BATCH_DEADLINE`` in seconds; an unusable value falls back
    to the default (the ``exec_timeout_s`` pattern)."""
    import os as _os

    raw = _os.environ.get("CURIO_SOLVE_BATCH_DEADLINE")
    if raw is None or not str(raw).strip():
        return DEFAULT_SOLVE_BATCH_DEADLINE_S
    try:
        value = int(str(raw).strip())
    except ValueError:
        return DEFAULT_SOLVE_BATCH_DEADLINE_S
    return value if value > 0 else DEFAULT_SOLVE_BATCH_DEADLINE_S


def _batch_deadline_spent(started: float, deadline_s: int) -> bool:
    """Whether a batch begun at monotonic *started* has used its budget —
    checked at every wave boundary and before every node dispatch."""
    return (time.monotonic() - started) >= deadline_s


#: dev/116: the verified loop's own egress budget — per failed round up to five
#: real requests (the gate's probe, the composed request and its redirect, the
#: keyed probe), over the first round plus the corrections, with slack.
_LOOP_EGRESS_CALLS = 4 * (1 + DEFAULT_SOLVE_CORRECTION_ROUNDS) + 2
_VALIDATE_STALE_SECONDS = 15 * 60


def solve_node_stream(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    *,
    node_id: str,
    exec_fn=None,
):
    """dev/115 (DEC-073, Amendment A2): the per-node Solve — the user's
    explicit ask to run, fix, and re-run ONE node's code from the node's own
    agent (any attachment whose manifest resolves ``node.content.generate``).

    Round 0 executes the node's CURRENT content as-is; corrections run the
    shared loop. A node that already had content lands as a reviewed
    ``node.content.write`` that has already passed (DEC-006 — an existing
    node's content changes only through review); an EMPTY node is written
    directly on PASS; exhaustion mints nothing and says so; a sandbox outage
    says "not verified". Detached like the batch: the request subscribes.

    Eager validation (404/409 stay JSON); the generator yields
    ``solve_node_started`` → the loop's ``generation_round`` /
    ``node_executed`` / ``round_verdict`` → ``done {verdict, rounds,
    attempts, unchanged?, written?, proposalId?, proposalAttachmentId?}``.
    """
    spec = _read_spec_or_404(user_key, project_id)
    record = _record_or_404(spec, attachment_id)
    # DEC-080 (dev/126): as the batch — the per-node Solve resolves the same
    # required delegates.
    if _repair_required_closure(
        user_key, project_id, record.get("coord", ""), attachment_id=attachment_id
    ):
        spec = _read_spec_or_404(user_key, project_id)
        record = _record_or_404(spec, attachment_id)
    if not isinstance(node_id, str) or not node_id:
        raise AgentServiceError("a nodeId is required", 422)
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    if node is None:
        raise AgentServiceError(f"node {node_id!r} not found in the saved spec", 404)
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
    try:
        agent_jobs.check_can_start(user_key, attachment_id)
    except agent_jobs.JobRefused as exc:
        raise AgentServiceError(str(exc), exc.status)
    execution_id = uuid.uuid4().hex
    # Request-context pieces, resolved before the job thread starts.
    base = _solve_grounding_base(user_key, project_id, spec, {node_id: node}, [node_id])
    dataset_paths = _resolve_catalog_execution_paths(project_id, list(base.get("catalog_ids") or {}))
    events = _solve_node_events(
        user_key, project_id, attachment_id, config, spec, node, resolution,
        record.get("coord", ""), record.get("sessionId"), execution_id, exec_fn,
        manifest=manifest, grounding_base=base, dataset_paths=dataset_paths,
        catalog_rows=_catalog_rows_for_discovery(user_key, project_id),
        templates=_roster_templates(user_key, project_id),
    )
    job = agent_jobs.start_job(
        user_key=user_key, project_id=project_id, attachment_id=attachment_id,
        kind="solve-node", job_id=execution_id, events=events,
    )
    return agent_jobs.subscribe(job)


def _solve_node_events(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    spec: dict,
    node: dict,
    resolution,
    coord: str,
    session_id,
    execution_id: str,
    exec_fn,
    *,
    manifest,
    grounding_base: dict,
    dataset_paths: dict,
    templates: dict | None = None,
    catalog_rows: list | None = None,
):
    """The per-node Solve body (dev/115 A2) over the ONE verified loop."""
    node_id = node.get("id")
    label = (node.get("goal") or node_id)[:60]
    started = time.monotonic()
    had_content = bool(str(node.get("content") or "").strip())
    yield "solve_node_started", {
        "nodeId": node_id, "executionId": execution_id, "hasContent": had_content,
    }

    def _traced(delegate_inputs):
        st, tx, ch, _h = _run_delegate_traced(
            user_key, project_id, resolution.coord,
            "node.content.generate", delegate_inputs, config,
            parent_execution_id=execution_id,
            parent_coord=coord,
            attachment_id=attachment_id,
            node_id=node_id,
            home_create=False,
        )
        return st, tx, ch

    if not _node_is_executable(node, templates):
        # dev/118 (DEC-075) → dev/119: a kind with no code the sandbox could
        # run (Vega, Autark, merge, data pool, spatial join, an unknown
        # package). No round, no sandbox, no generation — nothing this loop
        # could verify; say so and change nothing.
        reason = (
            f"{label!r} ({node.get('type')}) has no code the sandbox could run — it works "
            "in the browser or through its own service; Play the dataflow to see it"
        )
        outcome = {
            "verdict": "not-executable",
            "evidence": {"kind": "not-executable", "detail": reason},
            "rounds": 0, "candidate": "", "delegations": [],
            "roundsTrace": [f"not executable — {reason}"], "attempts": [],
        }
    else:
        outcome = yield from _verified_content_rounds(
            user_key, project_id,
            spec=spec, node=node, resolution=resolution, config=config,
            parent_execution_id=execution_id, parent_coord=coord,
            attachment_id=attachment_id, exec_fn=exec_fn,
            grounding_loop_ctx={"granted": [], "manifest": manifest,
                                "attachment_id": attachment_id, "session_id": session_id},
            grounding_base=grounding_base,
            start_from_current=True,
            delegate_runner=_traced,
            dataset_paths_fn=lambda codes: _filter_dataset_paths(dataset_paths, codes),
            exec_user_key=user_key,
            secrets_fn=_exec_secrets_resolver(user_key),
            resolve_source=_source_resolver(
                user_key, project_id, coord=coord, attachment_id=attachment_id,
                execution_id=execution_id, config=config, manifest=manifest,
                extra_texts=(str((spec.get("dataflow") or {}).get("task") or ""),),
                catalog_rows=catalog_rows,
            ),
        )
    verdict = outcome["verdict"]
    attempts = outcome["attempts"]
    rounds = outcome["rounds"]
    done: dict = {"nodeId": node_id, "verdict": verdict, "rounds": rounds,
                  "attempts": attempts, "evidence": outcome["evidence"]}
    trail_lines = []
    for attempt in attempts[:8]:
        why = _attempt_why(attempt, limit=160)
        line = f"round {attempt.get('round')} · {attempt.get('verdict')} · {attempt.get('kind')}"
        if attempt.get("verdict") == "pass":
            line += f" · {attempt.get('outputDataType') or '?'}"
        elif why:
            line += f" — {why}"
        if attempt.get("verdict") != "pass" and attempt.get("endpointEvidence"):
            line += f" · endpoint: {str(attempt['endpointEvidence'])[:200]}"
        trail_lines.append(line)
    unchanged = (
        verdict == "pass" and rounds == 1 and attempts
        and attempts[0].get("source") == "current content"
    )
    parts: list = []
    if verdict == "pass" and unchanged:
        text = f"Verified {label!r}: its current code ran successfully — no change needed."
        done["unchanged"] = True
        card_kind = "result"
    elif verdict == "pass" and not had_content:
        # An empty node (a plan placeholder solved from its own agent) is
        # written directly on PASS — parity with the Dataflow Builder's Solve.
        written = False
        try:
            fresh = _read_spec_or_404(user_key, project_id)
            target = next(
                (n for n in (fresh.get("dataflow") or {}).get("nodes") or []
                 if isinstance(n, dict) and n.get("id") == node_id), None,
            )
            if target is not None and not str(target.get("content") or "").strip():
                target["content"] = outcome["candidate"]
                projects_storage.write_spec(user_key, project_id, fresh)
                written = True
        except Exception:
            written = False
        done["written"] = written
        text = (
            f"Solved {label!r}: the code ran successfully after {rounds} round"
            f"{'s' if rounds != 1 else ''} and was written to the node."
            if written else
            f"Solved {label!r}: the code ran successfully, but the node gained content meanwhile — nothing written."
        )
        card_kind = "result"
    elif verdict == "pass":
        part, home_att, _mint_text = _mint_content_review_from_delegate(
            user_key, project_id,
            node_id=node_id,
            generated_text=outcome["candidate"],
            parent_attachment_id=attachment_id,
            parent_session_id=session_id,
            local_turn=False,
            validation={"verdict": verdict, "rounds": rounds,
                        "evidence": outcome["evidence"], "attempts": attempts},
            grounding_base=grounding_base,
        )
        if part is not None:
            done["proposalId"] = part["proposalId"]
            done["proposalAttachmentId"] = home_att
            if home_att == attachment_id:
                parts.append(part)
            text = (
                f"Solved {label!r}: the corrected code ran successfully after {rounds} "
                f"round{'s' if rounds != 1 else ''} — review and apply it below."
            )
        else:
            text = f"Solved {label!r} but the review could not be minted — nothing was changed."
        card_kind = "result"
    elif verdict == "infrastructure":
        text = (
            f"Not verified: the sandbox was unreachable while solving {label!r} — "
            "nothing was run, corrected, or written. Retry when it is back."
        )
        card_kind = "error"
    elif verdict == "not-executable":
        text = (
            f"Not executable: {label!r} has no code the sandbox could run — it works in the "
            "browser or through its own service. Play the dataflow to see it. Nothing was changed."
        )
        card_kind = "result"
    elif verdict == "awaiting-source":
        # dev/126: the source is with the user. Nothing was generated or
        # written; the node's own Dataset Finder holds the candidates.
        evidence = outcome.get("evidence") or {}
        remedy_payload = evidence.get("remedy")
        if isinstance(remedy_payload, dict):
            done["remedy"] = remedy_payload
        text = (
            f"Awaiting a source for {label!r}: {evidence.get('detail') or 'a dataset must be selected'} "
            "— open Dataset Finder on this node, select the source and confirm, then Solve "
            "again. Nothing was generated or written."
        )
        card_kind = "result"
    elif (outcome.get("evidence") or {}).get("upstreamEmpty"):
        text = (
            f"Not verified: {(outcome.get('evidence') or {}).get('detail') or 'an upstream node has no content yet'} "
            f"— {label!r} waits for it; solve or fill that node, then Solve this one again. Nothing was changed."
        )
        card_kind = "result"
    else:
        text = (
            f"Not fixed after {rounds} attempt{'s' if rounds != 1 else ''}"
            f"{_stopped_by_clause(outcome.get('stoppedBy'))}: {label!r} still "
            "fails — every attempt is listed below with the code it ran; nothing was written."
        )
        remedy_payload = (outcome.get("evidence") or {}).get("remedy")
        if isinstance(remedy_payload, dict):
            done["remedy"] = remedy_payload
            text += _source_missing_remedy(remedy_payload).replace(" — ", " ", 1).capitalize() + "."
        card_kind = "error"
    card = {
        "type": "card", "kind": card_kind,
        "title": f"Solve · {verdict.upper()} after {rounds} round{'s' if rounds != 1 else ''}",
        "lines": trail_lines[:10],
    }
    if verdict != "pass" and attempts:
        # dev/127: the trail itself, with the code each attempt ran — in THIS
        # chat, durably, not only in the transient row above.
        trail_part = _solve_attempts_part(
            spec, node_id, str(node.get("goal") or node_id)[:120],
            {"attempts": attempts, "rounds": rounds, "verdict": verdict,
             "stoppedBy": outcome.get("stoppedBy")},
        )
        if trail_part is not None:
            parts.append(trail_part)
    if isinstance(session_id, str):
        try:
            sessions.append_turns(
                user_key, project_id, session_id, attachment_id,
                [sessions.make_turn(
                    "agent", text, error=(card_kind == "error"),
                    content=[card, *parts],
                    execution=_execution_record(
                        execution_id,
                        {"coord": coord, "provider": getattr(config, "api_type", None),
                         "model": getattr(config, "model", None), "tools": [], "intentEdited": False},
                        {}, started, "ok" if verdict in ("pass", "not-executable") else "error",
                        delegations=[c for c in outcome["delegations"] if c is not None],
                    ),
                )],
            )
        except Exception:
            pass
    yield "done", done


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


#: dev/115: the verified loop's progress, relayed on the Solve stream.
_SOLVE_PROGRESS_EVENTS = {
    "generation_round": "node_round",
    "node_executed": "node_executed",
    "round_verdict": "node_verdict",
}


def _resolve_catalog_execution_paths(project_id: str, dataset_ids: list) -> dict:
    """dev/115: ``{datasetId: absolutePath}`` for every id a Solve batch may
    load — resolved ONCE in the request thread the way ``/processPythonCode``
    does (contained paths only); fail-open to ``{}``."""
    ids = [str(i) for i in dataset_ids if i][:64]
    if not ids:
        return {}
    try:
        from flask import g, has_request_context

        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )

        user = getattr(g, "user", None) if has_request_context() else None
        return dict(
            DatasetCatalogService(user).resolve_execution_paths(ids, dataflow_id=project_id) or {}
        )
    except Exception:
        log.warning("Could not resolve catalog execution paths for project %s",
                    project_id, exc_info=True)
        return {}


def _filter_dataset_paths(mapping: dict, codes: list) -> dict:
    """The subset of a precomputed mapping that *codes* reference — pure, so a
    worker thread can call it."""
    if not mapping:
        return {}
    out: dict = {}
    for code in codes:
        if not isinstance(code, str) or "curio_dataset_path" not in code:
            continue
        for match in source_grounding.DATASET_PATH_CALL_RE.finditer(code):
            dataset_id = match.group(2)
            if dataset_id in mapping:
                out[dataset_id] = mapping[dataset_id]
    return out


#: dev/115: how many URLs a failed round probes for the correction's evidence.
_CORRECTION_URL_PROBES = 2
#: dev/115: bounded attempt-trail fields (the card renders them inert).
_ATTEMPT_DETAIL_CHARS = 300
_ATTEMPT_STDERR_CHARS = 1200
#: dev/127: the candidate a failed round actually ran, kept ON the attempt so
#: the transcript can show what was tried. Bounded — a trail is a record, not
#: a copy of the project (a five-round trail costs tens of KB, not MB).
_ATTEMPT_CODE_CHARS = 4000
_CODE_TRUNCATION_MARKER = "\n… [truncated: the attempt's code exceeded the trail's bound]"
#: dev/127: how many repeated candidates the loop tolerates before it stops.
#: dev/116 tells the model it repeated itself and lets it try again; a second
#: repeat means the budget would buy copies, not corrections.
_MAX_REPEATED_ATTEMPTS = 2
#: dev/127: how many nodes' attempt trails ride ONE Solve turn. Beyond this the
#: card names how many were elided; each is still readable in its own node's
#: agent chat.
_MAX_ATTEMPT_PARTS = 8

#: dev/127: why the repair loop stopped. Every failure sentence names one, so
#: "not fixed after N attempts" can never again read as a verdict on the code
#: when it was a verdict on the round cap.
STOPPED_BY_PHRASES = {
    "rounds": "the round cap",
    "budget": "this node's time budget",
    "repeat": "a repeated attempt",
    "decline": "the builder's decline",
    "blocker": "an upstream blocker",
    "generation": "a generation error",
    "infrastructure": "a sandbox outage",
    "passed": "success",
    # dev/126's lane: the source is with the user, so the loop stopped ON PURPOSE.
    "source": "a source the user must confirm",
}


def _stopped_by_clause(stopped_by: object) -> str:
    """`" (stopped by the round cap)"`, or `""` when nothing is recorded."""
    phrase = STOPPED_BY_PHRASES.get(str(stopped_by or ""))
    return f" (stopped by {phrase})" if phrase and stopped_by != "passed" else ""


def _attempt_code_field(candidate: object, *, prose: bool = False) -> dict:
    """The attempt's ``code`` (+ ``codeIsProse``/``codeTruncated``) fields."""
    text = candidate if isinstance(candidate, str) else ""
    if not text.strip():
        return {}
    field: dict = {}
    if len(text) > _ATTEMPT_CODE_CHARS:
        field["code"] = text[:_ATTEMPT_CODE_CHARS] + _CODE_TRUNCATION_MARKER
        field["codeTruncated"] = True
    else:
        field["code"] = text
    if prose:
        # dev/115: the builder's sanctioned decline is prose, not content — the
        # card must not render it as code the user could run.
        field["codeIsProse"] = True
    return field


def _exec_dataset_paths(project_id: str, *codes: str) -> dict:
    """dev/115: the ``{datasetId: absolutePath}`` mapping the sandbox needs for
    every ``curio_dataset_path("<id>")`` call in *codes* — resolved the way
    ``/processPythonCode`` resolves it (``resolve_execution_paths``, contained
    paths only). Fail-open to ``{}``: an unmapped id raises a clear per-id
    error inside the sandbox, which the correction loop then sees. Needs the
    request context (``g.user``); a Solve batch precomputes it in the request
    thread and hands the mapping to its workers."""
    ids: list[str] = []
    for code in codes:
        if not isinstance(code, str) or "curio_dataset_path" not in code:
            continue
        for match in source_grounding.DATASET_PATH_CALL_RE.finditer(code):
            dataset_id = match.group(2)
            if dataset_id not in ids:
                ids.append(dataset_id)
            if len(ids) >= 32:
                break
    if not ids:
        return {}
    try:
        from flask import g, has_request_context

        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )

        user = getattr(g, "user", None) if has_request_context() else None
        resolved = DatasetCatalogService(user).resolve_execution_paths(
            ids, dataflow_id=project_id
        )
        return dict(resolved or {})
    except Exception:  # resolution must never fail a validation run
        log.warning(
            "Could not resolve dataset paths for a validation run (project %s)",
            project_id, exc_info=True,
        )
        return {}


def _content_sha(text: str) -> str:
    import hashlib

    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


#: Attempt kinds whose detail is read from the HEAD (a refusal names the
#: literal, a decline names the missing input); a traceback reads from its tail.
_HEAD_FIRST_KINDS = ("ungrounded-source", "source-missing", "repeated-attempt")


def _last_attempt_code(trail: dict) -> str | None:
    """The code of the last recorded attempt (dev/127) — what the failure's
    exception line is read against, so a self-raised error is named as one."""
    attempts = (trail or {}).get("attempts") or []
    return attempts[-1].get("code") if attempts else None


def _solve_attempts_part(
    spec: dict | None, node_id: str, label: str, result: dict | None
) -> dict | None:
    """dev/127: ONE node's repair attempts as a transcript part, or None.

    The owner's requirement — *"it is important to clearly display all attempts
    to fix in the chat transcript"* — is a durability requirement: the strip is
    transient and the card's lines cannot carry code. Every recorded attempt
    rides here with the code it ran and its error read through
    ``failure_text`` (the exception line first, whole), and the part links the
    node's own agent so the child's replies are one click away.
    """
    attempts = (result or {}).get("attempts") or []
    if not attempts:
        return None
    rows = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        rows.append({
            **attempt,
            "errorSummary": _attempt_why(
                attempt, limit=content.SOLVE_ATTEMPT_ERROR_MAX_CHARS
            ),
        })
    if not rows:
        return None
    home = _node_attachment_of(spec or {}, "agent.node-builder", node_id) or {}
    return content.make_solve_attempts_part(
        node_id=node_id,
        label=label,
        attachment_id=home.get("attachmentId"),
        rounds=(result or {}).get("rounds") or len(rows),
        stopped_by=(result or {}).get("stoppedBy") or "",
        attempts=rows,
        verdict=(result or {}).get("verdict") or "fail",
    )


def _attempt_why(attempt: dict, *, limit: int) -> str:
    """dev/127: ONE reading of a recorded attempt's failure, for every card.

    A refusal (the grounding gate, a decline) says what it refused in its FIRST
    line; a traceback says it in its exception line, which
    ``failure_text.summary`` puts first and keeps whole. The attempt's own code
    rides along so an error the candidate raised itself is labeled as such."""
    raw = str(attempt.get("stderrTail") or attempt.get("detail") or "")
    if not raw.strip():
        return ""
    if attempt.get("kind") in _HEAD_FIRST_KINDS:
        return failure_text.excerpt(raw, limit=limit, head=True)
    return failure_text.summary(raw, code=attempt.get("code"), limit=limit)


def _same_code(a: str, b: str) -> bool:
    """Byte-different but code-identical: comments, blank lines and spacing
    stripped through the tokenizer (a string literal with a '#' survives)."""
    import io
    import tokenize

    def _norm(code: str) -> str:
        try:
            tokens = tokenize.generate_tokens(io.StringIO(code).readline)
            skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                    tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}
            return " ".join(t.string for t in tokens if t.type not in skip and t.string.strip())
        except (tokenize.TokenError, SyntaxError, IndentationError):
            return "\n".join(l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith("#"))

    return bool(a and b) and _norm(a) == _norm(b)


def _dataset_finder_attachment_id(spec: dict | None, node_id: str) -> str | None:
    """The node's own Dataset Finder attachment id, or None (dev/126)."""
    if not isinstance(spec, dict) or not isinstance(node_id, str) or not node_id:
        return None
    record = _node_attachment_of(spec, "agent.dataset-finder", node_id)
    return (record or {}).get("attachmentId")


#: dev/126: the ONE sentence an ``ungrounded-source`` failure ends with. It
#: existed in three copies (the batch Solve's verified and legacy lanes and the
#: per-node stream), which is exactly how the three drifted apart from what the
#: product can now do: discovery is initiated at the node, so the sentence names
#: that node's own Dataset Finder when it has one.
_UNGROUNDED_REMEDY_GENERIC = (
    " — resolve the source with Dataset Finder (attach it to this node) or give the path"
)


def _ungrounded_remedy(attachment_id: str | None = None) -> str:
    """The remedy an ungrounded data source ends with (dev/126)."""
    if attachment_id:
        return (
            " — open Dataset Finder on this node to pick a source, or give the path"
        )
    return _UNGROUNDED_REMEDY_GENERIC


def _source_missing_remedy(remedy: dict | None) -> str:
    """The one sentence a ``source-missing`` failure ends with (dev/116)."""
    if isinstance(remedy, dict) and remedy.get("kind") == "connection-key" and remedy.get("host"):
        return (
            f" — add a connection key for {remedy['host']} (Settings → Connection keys), "
            "then Solve again"
        )
    if isinstance(remedy, dict) and remedy.get("kind") == "use-connection-key" and remedy.get("host"):
        return (
            f" — a connection key {remedy.get('name')!r} is saved for {remedy['host']}; "
            "Solve again so the builder uses it"
        )
    return " — provide what it names (a key, a path or a URL), then Solve again"
_PROSE_DECLINE_MAX_CHARS = 400
_CODE_MARKERS = ("import ", "return ", " = ", "(", "def ", "{")


def _is_prose_decline(candidate: str) -> bool:
    """A short, single-line reply with no code shape — the content builder's
    sanctioned "what source is missing" line rather than content."""
    text = (candidate or "").strip()
    if not text or "\n" in text or len(text) > _PROSE_DECLINE_MAX_CHARS:
        return False
    return not any(marker in text for marker in _CODE_MARKERS)


def _correction_url_evidence(candidate: str, error_text: str, ctx) -> list[dict]:
    """dev/115: when a failed run names an HTTP problem, re-probe the URLs the
    candidate fetches (DEC-053, budgeted through the grounding context) so the
    correction is grounded in the endpoint's real answer — not a guess about
    why a 400 happened."""
    if ctx is None or ctx.probe is None:
        return []
    lowered = (error_text or "").lower()
    named_http = any(
        marker in lowered for marker in ("http", "status", "urlerror", "connection", "timeout")
    )
    # A data-loading node that fetches and then fails is an endpoint question
    # whatever the traceback says: the field case wrapped the request in a
    # bare ``except`` and returned an empty frame, so the only error named was
    # DuckDB's "need at least one column" (dev/115 field fix, 2026-09-08).
    if not named_http and not getattr(ctx, "is_data_loading", False):
        return []
    # The requests the loader actually made come first: a parameterised API's
    # base answers 200 while the composed query is what fails.
    targets = [(url, "composed") for url in source_grounding.composed_requests(candidate)]
    targets += [
        (ref.literal, "literal")
        for ref in source_grounding.scan_sources(candidate, "python")
        if ref.kind == "url" and ref.literal not in {u for u, _ in targets}
    ]
    out: list[dict] = []
    known = getattr(ctx, "verified_urls", None)
    for url, how in targets:
        if how == "composed":
            placeholder = _placeholder_probe(url, ctx)
            if placeholder is not None:
                # The code sends a saved key itself (curio_secret(...) as a
                # parameter): probe ONLY with the value swapped in — a bare probe
                # would send the placeholder text and answer nothing useful.
                out.append(placeholder)
                if len(out) >= _CORRECTION_URL_PROBES:
                    break
                continue
        already_known = isinstance(known, dict) and url in known
        try:
            verdict = ctx.probe(url)
        except Exception as exc:  # a broken prober is absence, never a claim
            verdict = {"status": "unverified", "detail": str(exc)[:200]}
        if how == "composed" and isinstance(known, dict) and not already_known:
            # Evidence for the correction, NOT a new grounded source: a
            # composed query is a derivative of its (already gated) base URL,
            # and a 200 HTML "Missing Key" page must never be listed as a URL
            # the builder may fetch.
            known.pop(url, None)
        entry = {"url": url, "verification": verdict}
        if how == "composed":
            entry["request"] = "the URL composed from the code's url + params"
        note = _endpoint_note(verdict)
        if note:
            entry["note"] = note
        keyed = _keyed_probe(candidate, url, how, ctx) if how == "composed" else None
        if keyed:
            entry.update(keyed)
        out.append(entry)
        if len(out) >= _CORRECTION_URL_PROBES:
            break
    return out


def _placeholder_probe(url: str, ctx) -> dict | None:
    """dev/116 live fix (2026-09-09): a composed request whose parameters carry
    ``curio_secret("<name>")`` placeholders. The saved values are sent in their
    place through the keyed (uncached, never-verified) probe path and the
    outcome is redacted; the entry shows the call, never the value."""
    bare, secret_params = source_grounding.split_secret_params(url)
    if not secret_params:
        return None
    shown = source_grounding.display_composed_url(url)
    names = sorted(set(secret_params.values()))
    entry: dict = {
        "url": shown,
        "request": "the URL composed from the code's url + params; the saved key was sent in place of curio_secret(...)",
        "keyed": ", ".join(names),
    }
    resolver = getattr(ctx, "secret_values", None)
    values: dict = {}
    if resolver is not None:
        try:
            values = resolver(names) or {}
        except Exception:
            values = {}
    missing = [n for n in names if not values.get(n)]
    if missing:
        entry["verification"] = {
            "status": "unverified",
            "detail": f"no connection key named {', '.join(repr(m) for m in missing)} is saved — not probed",
        }
        return entry
    params = {param: values[name] for param, name in secret_params.items()}
    try:
        outcome = ctx.probe(bare, params=params) or {}
    except Exception as exc:
        outcome = {"status": "unverified", "detail": str(exc)[:200]}
    from utk_curio.common.redaction import redact

    outcome = {k: (redact(v, values) if isinstance(v, str) else v) for k, v in outcome.items()}
    entry["verification"] = outcome
    note = _endpoint_note(outcome)
    if note:
        entry["note"] = note
    return entry


def _keyed_probe(candidate: str, url: str, how: str, ctx) -> dict | None:
    """dev/116: when a saved connection key is bound to the composed request's
    host and the API's ``delivery`` is known (``query:<p>`` / ``header:<H>``),
    probe the SAME request with the key and report what the keyed request
    answers — redacted, never cached, never a verified source. ``delivery:
    code`` only names the key (the run is the evidence)."""
    saved = source_grounding.secret_for_host(ctx, url)
    if saved is None:
        return None
    result: dict = {"keyed": saved.name, "keyedDelivery": saved.delivery}
    in_code = saved.name in source_grounding.secret_names(candidate)
    if not saved.delivery.startswith(("query:", "header:")):
        result["keyedNote"] = (
            f"a connection key {saved.name!r} is saved for this host"
            + ("" if in_code else f" — the code does not use it yet: {saved.use_line}")
            + "; the code decides how the API receives it"
        )
        return result
    resolver = getattr(ctx, "secret_values", None)
    if resolver is None:
        return result
    try:
        values = resolver([saved.name]) or {}
    except Exception:
        values = {}
    value = values.get(saved.name)
    if not value:
        return result
    kind, _, target = saved.delivery.partition(":")
    kwargs = {"params": {target: value}} if kind == "query" else {"headers": {target: value}}
    try:
        outcome = ctx.probe(url, **kwargs)
    except Exception as exc:
        outcome = {"status": "unverified", "detail": str(exc)[:200]}
    from utk_curio.common.redaction import redact

    outcome = {
        k: (redact(v, {saved.name: value}) if isinstance(v, str) else v)
        for k, v in (outcome or {}).items()
    }
    result["keyedVerification"] = outcome
    status = outcome.get("status")
    content_type = str(outcome.get("contentType") or "").lower()
    sent = f"as {kind} {target!r}"
    if status == "verified" and content_type and "json" not in content_type:
        result["keyedNote"] = (
            f"even with the saved key {saved.name!r} sent {sent}, the request answered "
            f"{content_type.split(';')[0]}{' (' + str(outcome.get('pageTitle')) + ')' if outcome.get('pageTitle') else ''}"
            " — the key or the way it is sent is wrong; say so instead of guessing parameters"
        )
    elif status == "verified":
        result["keyedNote"] = (
            f"with the saved key {saved.name!r} sent {sent} the request answers data — "
            f"the code must send it the same way: {saved.use_line}"
            + ("" if in_code else " (the code does not use it yet)")
        )
    else:
        result["keyedNote"] = (
            f"with the saved key {saved.name!r} sent {sent}: {status}"
            + (f" {outcome.get('httpStatus')}" if outcome.get("httpStatus") else "")
        )
    return result


_CREDENTIAL_DECLINE_RE = _re.compile(
    r"api[ _-]?key|\bkey\b|token|credential|sign[- ]?in|log[- ]?in|unauthori[sz]ed|missing key|forbidden",
    _re.IGNORECASE,
)


def _decline_remedy(decline: str, previous_attempt: str | None, ctx) -> dict | None:
    """dev/116: a decline about a credential + a host from the failed attempt
    → a concrete remedy the card can act on."""
    if not decline or not _CREDENTIAL_DECLINE_RE.search(decline):
        return None
    host = ""
    for url in source_grounding.composed_requests(previous_attempt or ""):
        host = source_grounding._host_of(url)
        if host:
            break
    if not host:
        for ref in source_grounding.scan_sources(previous_attempt or "", "python"):
            if ref.kind == "url":
                host = source_grounding._host_of(ref.literal)
                if host:
                    break
    if not host:
        return None
    from utk_curio.backend.app.users.connection_keys import suggest_name

    saved = source_grounding.secret_for_host(ctx, f"https://{host}/") if ctx is not None else None
    if saved is not None:
        return {"kind": "use-connection-key", "host": host, "name": saved.name}
    return {"kind": "connection-key", "host": host, "suggestedName": suggest_name(host)}


def _endpoint_note(verdict: dict) -> str:
    """A deterministic reading of a probe outcome for the correction and the
    card — only what the outcome itself shows, never a guess."""
    if not isinstance(verdict, dict):
        return ""
    status = verdict.get("status")
    content_type = str(verdict.get("contentType") or "")
    final_url = verdict.get("finalUrl")
    title = verdict.get("pageTitle")
    sample = verdict.get("bodySample")
    where = f" after redirecting to {final_url}" if final_url else ""
    if status == "verified" and content_type and "json" not in content_type.lower():
        what = f'an HTML page titled "{title}"' if title else f"{content_type.split(';')[0]} content"
        return (
            f"answered {what}{where} — not data. Read the page title: a key or "
            "sign-in requirement cannot be fixed by changing parameters; say what is missing."
        )
    if status == "unreachable" and verdict.get("httpStatus"):
        said = f': "{sample}"' if sample else (f' ("{title}")' if title else "")
        return f"the request itself answered {verdict['httpStatus']}{where}{said}"
    return ""


def _url_evidence_summary(url_evidence: list[dict]) -> str:
    """One line for the attempt trail: what the endpoint actually answered."""
    parts: list[str] = []
    for entry in url_evidence[:2]:
        verdict = entry.get("verification") or {}
        head = str(entry.get("url") or "")
        head = head if len(head) <= 90 else head[:87] + "…"
        status = verdict.get("status", "unverified")
        http = verdict.get("httpStatus")
        bit = f"{head} → {status}" + (f" {http}" if http else "")
        if entry.get("note"):
            bit += f": {entry['note']}"
        elif verdict.get("detail"):
            bit += f": {verdict['detail']}"
        parts.append(bit)
    return "; ".join(parts)[:_ATTEMPT_DETAIL_CHARS * 2]


def _catalog_rows_for_discovery(user_key: str, project_id: str) -> list[dict]:
    """The project's Data Catalog rows, resolved WHILE A REQUEST CONTEXT EXISTS.

    dev/126, learned from dev/123's field finding: ``catalog.search`` rides the
    request context (the datasets domain is user-object keyed), and a detached
    Solve job has none — so the rows are listed at the entry point and handed
    to the discovery delegate, exactly as dev/115 already resolves the
    execution paths eagerly. Empty on failure: the delegate is then TOLD the
    catalog was unavailable rather than left to imagine it.
    """
    try:
        return tools._catalog_search_rows(user_key, project_id, {})
    except Exception:  # noqa: BLE001
        log.warning("Data Catalog listing unavailable for project %s", project_id,
                    exc_info=True)
        return []


def _node_grounded_literal(node: dict, ctx, *, extra_texts=()) -> str | None:
    """The literal that ALREADY grounds this node's source, or None (dev/126).

    Deliberately narrow. Only human-authored text counts — the node's own goal,
    the dataflow's mission and the user's message — never the node's current
    content: a path the model wrote is what the DEC-072 gate exists to refuse,
    and letting it stand in here would ground a node on its own hallucination.
    A batch's grounding context is shared by every target node, so the scan is
    over THIS node's texts rather than over the context's own path set.
    """
    if ctx is None:
        return None
    texts = [str(node.get("goal") or ""), *[str(t or "") for t in extra_texts]]
    joined = " ".join(texts)
    for path in sorted(source_grounding.user_paths(texts)):
        return path
    for dataset_id in sorted(getattr(ctx, "catalog_ids", None) or {}):
        if dataset_id and dataset_id in joined:
            return f'curio_dataset_path("{dataset_id}")'
    for url in sorted(getattr(ctx, "verified_urls", None) or {}):
        if url and url in joined:
            return url
    if source_grounding.synthetic_requested(texts):
        return "synthetic data (the goal asks for it)"
    return None


def _project_grounded_literal(ctx) -> str | None:
    """Project-wide grounding: the Data Catalog the content child is handed.

    dev/126: the catalog IS a grounded source (``DEC-072``) — the child gets
    its rows and the gate accepts the row it loads — so a project that holds
    datasets grounds a FIRST attempt without a review gate. It is not evidence
    about this node, so it ranks below a pending candidates card, and when the
    catalog turns out not to cover the node the ROUND says so and discovery is
    initiated on that evidence instead of on a guess.
    """
    catalog = getattr(ctx, "catalog_ids", None) or {}
    if catalog:
        return f"the project's Data Catalog ({len(catalog)} dataset(s))"
    return None


def _source_resolver(
    user_key: str,
    project_id: str,
    *,
    coord: str,
    attachment_id: str | None,
    execution_id: str,
    config: ProviderConfig,
    manifest=None,
    extra_texts=(),
    catalog_rows: list | None = None,
):
    """dev/126: the callable the content loop consults BEFORE generating for a
    data-loading node — the one place resolution initiates discovery.

    Same policy on all three resolution paths (the Solve batch, the per-node
    Solve, Simulation Mode's validate): a node whose source is already
    grounded proceeds and the skip is recorded; an unresolved one gets ONE
    ``dataset.discover`` delegation whose candidates await the user in that
    node's own Dataset Finder chat; a node already awaiting the user spends
    nothing at all.
    """
    parent_manifest = manifest if manifest is not None else _resolve_definition(user_key, coord)

    def _resolve(node: dict, grounding_ctx, *, stage: str = "pre") -> dict:
        """``stage="pre"``: before round 0, when nothing in the project could
        ground this node's source. ``stage="post"``: after a round failed FOR
        its source — the gate refused the literal the builder wrote, or the
        builder declined — which is evidence no heuristic can override."""
        from utk_curio.backend.app.agents import dataset_resolution
        from utk_curio.backend.app.projects import storage as projects_storage

        node_id = str(node.get("id") or "")
        spec = projects_storage.read_spec(user_key, project_id)
        literal = (
            _node_grounded_literal(node, grounding_ctx, extra_texts=extra_texts)
            if stage == "pre" else None
        )
        project_literal = (
            _project_grounded_literal(grounding_ctx) if stage == "pre" else None
        )
        state = dataset_resolution.node_source_state(
            spec, node_id, grounded_literal=literal, project_literal=project_literal,
        )
        if state["state"] == dataset_resolution.STATE_RESOLVED:
            skip_literal = literal or project_literal
            if skip_literal and state.get("attachmentId"):
                with projects_storage.spec_write_lock(user_key, project_id):
                    fresh = projects_storage.read_spec(user_key, project_id)
                    if fresh is not None and dataset_resolution.mark_skipped(
                        fresh, state["attachmentId"], literal=skip_literal
                    ):
                        projects_storage.write_spec(user_key, project_id, fresh)
            return {
                "state": "resolved",
                "detail": state["detail"] or (skip_literal or ""),
                "confirmedSource": dataset_resolution.confirmed_source(spec, node_id),
            }
        if state["state"] != dataset_resolution.STATE_UNRESOLVED:
            # Candidates (or a reviewed install) already await the user: say so
            # without spending a model call on a second identical card.
            return {"state": "awaiting", "detail": state["detail"],
                    "attachmentId": state["attachmentId"]}
        started = dataset_resolution.initiate(
            user_key, project_id, node,
            config=config,
            parent_manifest=parent_manifest,
            parent_coord=coord,
            parent_execution_id=execution_id,
            parent_attachment_id=attachment_id,
            mission=" — ".join(
                t for t in [str(node.get("goal") or ""), *[str(x or "") for x in extra_texts]]
                if t
            )[:2000],
            catalog_rows=catalog_rows,
        )
        if started["status"] == "awaiting":
            return {"state": "awaiting", "detail": started["detail"],
                    "attachmentId": started.get("attachmentId")}
        # Discovery ran and found nothing usable, or the specialist could not
        # run at all. "Awaiting your selection" would be a lie — there is
        # nothing to select — so the node keeps its own honest outcome and the
        # discovery attempt rides along as the reason it stays unresolved.
        return {"state": "unresolved", "detail": started["detail"],
                "attachmentId": started.get("attachmentId"),
                "discovery": started["status"]}

    return _resolve


def _verified_content_rounds(
    user_key: str,
    project_id: str,
    *,
    spec: dict,
    node: dict,
    resolution,
    config: ProviderConfig,
    parent_execution_id: str,
    parent_coord: str,
    attachment_id: str | None,
    exec_fn,
    grounding_loop_ctx: dict,
    grounding_base: dict | None = None,
    start_from_current: bool = False,
    extra_inputs: dict | None = None,
    delegate_runner=None,
    dataset_paths_fn=None,
    exec_user_key: str | None = None,
    secrets_fn=None,
    prior_outputs_fn=None,
    resolve_source=None,
    clock=time.monotonic,
):
    """dev/115 (DEC-073): the ONE generate → gate → execute → correct loop.

    The dev/67-7 round loop extracted from ``_validate_events`` so every
    caller — validate-node, Simulation Mode, and Solve — runs the same policy:

    - round 0 either delegates ``node.content.generate`` or, with
      ``start_from_current``, executes the node's CURRENT content as-is (the
      per-node Solve on code the user just applied: if it passes, nothing is
      generated, nothing changes);
    - every candidate passes the DEC-072 grounding gate BEFORE it runs — a
      refused candidate is a failed round (``kind: ungrounded-source``) whose
      refusal text is the correction's error, and it never reaches the sandbox;
    - a run's ``dataset_paths`` are resolved for the candidate + its slice;
    - a failed round feeds the next generation ``previousAttempt``,
      ``validationError``, ``sourceGrounding`` (data-loading nodes) and — when
      the failure names an HTTP problem — fresh probe evidence for the URLs
      the candidate fetches;
    - corrections continue while BOTH bounds allow (dev/127): at most
      ``solve_correction_rounds()`` of them, and only while
      ``solve_node_budget_s()`` seconds have not been spent — the outcome's
      ``stoppedBy`` names whichever bound ended it.

    A generator: yields ``("generation_round", …)``, ``("node_executed", …)``
    and ``("round_verdict", …)`` exactly as the validate-node stream always
    did, and RETURNS the outcome dict ``{verdict, evidence, rounds, candidate,
    delegations, roundsTrace, attempts}`` (``outcome = yield from …``).
    ``attempts`` is the bounded trail the cards render: one row per round
    with the content digest, verdict, kind, detail, stderr tail, and output.
    """
    import queue as _queue
    import threading

    from utk_curio.backend.app.agents import validation
    from utk_curio.backend.app.packages import services as packages_services

    run_delegate = delegate_runner or (
        lambda inputs: delegation.run_delegate(
            user_key, project_id, resolution.coord,
            "node.content.generate", inputs, config,
            parent_execution_id=parent_execution_id,
            parent_coord=parent_coord,
            attachment_id=attachment_id,
        )
    )
    node_id = node.get("id")
    node_type = node.get("type")
    is_data_loading = source_grounding.is_data_loading_type(
        packages_services.canonical_template_id(node_type)
    )
    try:
        available = {
            t["id"]: t for t in packages_services.available_templates(user_key, project_id)
        }
    except Exception:
        available = None  # arity metadata unavailable: type check fails open
    # dev/119 (DEC-076): the same roster classifies executability for the runner.
    loop_templates = (
        {tid: {"executable": bool(row.get("executable")), "engine": row.get("engine") or "python"}
         for tid, row in available.items()}
        if available else None
    )
    # ONE grounding context per loop: the same catalog/verified-URL evidence for
    # every round, one probe budget, and the sourceGrounding inputs derive from it.
    # dev/116 live fix (2026-09-09): the budget is the LOOP's own — a failed
    # round spends up to five calls (gate probe, composed request + redirect,
    # keyed probe) and the run-wide four starved every correction of its
    # evidence. The probe cache and the verified map stay shared with the
    # caller's context (a batch probes a base URL once).
    shared = grounding_loop_ctx
    grounding_loop_ctx = dict(shared)
    grounding_loop_ctx["_probe_cache"] = shared.setdefault("_probe_cache", {})
    grounding_loop_ctx["_verified_urls"] = shared.setdefault("_verified_urls", {})
    grounding_loop_ctx["_egress_budget"] = egress.CallBudget(_LOOP_EGRESS_CALLS)
    grounding_ctx = None
    dataflow = (spec or {}).get("dataflow") or {}
    try:
        # The node's goal and the dataflow's mission are human-authored intent
        # (a plan goal saying "synthetic sample data" authorizes inline data).
        grounding_ctx = _grounding_context(
            user_key, project_id, grounding_loop_ctx, node_type=node_type,
            base=grounding_base,
            extra_texts=(str(node.get("goal") or ""), str(dataflow.get("task") or "")),
        )
    except Exception:
        log.warning("Grounding context unavailable for node %s", node_id, exc_info=True)
    verdict_result: dict | None = None
    rounds_used = 0
    candidate = ""
    delegations: list = []
    rounds_trace: list[str] = []
    attempts: list[dict] = []
    previous_attempt: str | None = None
    previous_error: str | None = None
    url_evidence: list[dict] = []
    confirmed_source: dict | None = None
    stopped_by: str | None = None  # dev/127: which bound ended the loop
    repeats = 0
    # dev/126: a data-loading node RESOLVES ITS SOURCE FIRST. Discovery is
    # initiated by the runtime (never left to the model to think of), and a
    # node whose source the user has not confirmed yet waits for them instead
    # of ending in the old dead end — the content builder declining, or the
    # gate refusing a filename it had to invent.
    if is_data_loading and resolve_source is not None:
        try:
            source_state = resolve_source(node, grounding_ctx) or {}
        except Exception:  # noqa: BLE001
            log.warning("Source resolution failed for node %s", node_id, exc_info=True)
            source_state = {}
        if source_state.get("state") == "unresolved" and source_state.get("discovery"):
            # Discovery was initiated and produced nothing selectable: say so
            # in the trail and let the round proceed, so the node still ends
            # with ITS own evidence (a refusal naming the literal, or the
            # builder's own decline) rather than a promise of candidates.
            rounds_trace.append(
                f"discovery found no source — {str(source_state.get('detail'))[:160]}"
            )
        if source_state.get("state") == "awaiting":
            detail = str(source_state.get("detail") or "a source must be selected")
            return {
                "verdict": "awaiting-source",
                "evidence": {
                    "kind": "awaiting-selection",
                    "detail": detail[:2000],
                    **({"remedy": {
                        "kind": "dataset-selection",
                        "attachmentId": source_state["attachmentId"],
                        "nodeId": node_id,
                    }} if source_state.get("attachmentId") else {}),
                },
                "rounds": 0,
                "candidate": "",
                "delegations": delegations,
                "roundsTrace": [f"awaiting dataset selection — {detail[:160]}"],
                "attempts": [],
            }
        confirmed_source = source_state.get("confirmedSource")
        if source_state.get("detail"):
            rounds_trace.append(f"source: {str(source_state['detail'])[:160]}")
    max_rounds = min(1 + solve_correction_rounds(), 1 + MAX_SOLVE_CORRECTION_ROUNDS)
    node_budget_s = solve_node_budget_s()
    loop_started = clock()
    for round_index in range(max_rounds):
        if round_index and (clock() - loop_started) >= node_budget_s:
            # dev/127: the budget is checked BEFORE a new round is dispatched,
            # so a round in flight always finishes and is recorded.
            stopped_by = "budget"
            rounds_trace.append(
                f"stopped after round {rounds_used}: this node's "
                f"{node_budget_s}s repair budget is spent"
            )
            break
        rounds_used = round_index + 1
        yield "generation_round", {"round": rounds_used}
        use_current = (
            round_index == 0 and start_from_current and str(node.get("content") or "").strip()
        )
        if use_current:
            candidate = str(node.get("content") or "")
        else:
            inputs = {
                "nodeType": node_type,
                "intent": node.get("goal"),
                "nodeContext": node_context.compose_node_context(
                    user_key, project_id, spec, node_id
                ),
            }
            if is_data_loading and grounding_ctx is not None:
                # dev/114's seventh DEC-063 application, on every caller.
                inputs["sourceGrounding"] = _source_grounding_inputs(grounding_ctx)
                if confirmed_source is not None:
                    # dev/126: the source the USER confirmed on this node —
                    # handed over, not inferred from what was verified once.
                    inputs["sourceGrounding"]["confirmedSource"] = confirmed_source
            if extra_inputs:
                inputs.update({k: v for k, v in extra_inputs.items() if k not in inputs})
            if previous_attempt is not None:
                # The NCB instruction's self-correction contract: fix
                # precisely the failure, grounded in the real traceback.
                inputs["previousAttempt"] = previous_attempt[:6000]
                inputs["validationError"] = (previous_error or "")[:2000]
                if url_evidence:
                    inputs["urlEvidence"] = url_evidence
            status, text, child = run_delegate(inputs)
            delegations.append(child)
            if status != "ok":
                verdict_result = {
                    "verdict": "fail",
                    "evidence": {"kind": "generation-error", "detail": (text or "")[:300]},
                }
                attempts.append({
                    "round": rounds_used, "verdict": "fail", "kind": "generation-error",
                    "detail": (text or "")[:_ATTEMPT_DETAIL_CHARS],
                })
                stopped_by = "generation"
                break
            candidate = content.extract_node_content(text)
        # DEC-072: the gate runs BEFORE the sandbox does — a fabricated path
        # or an unverified URL never executes, and the refusal is the error
        # the next round corrects.
        if grounding_ctx is not None:
            gate = source_grounding.check_grounding(candidate, "python", grounding_ctx)
            if not gate.ok:
                refusal = source_grounding.refusal_text(gate, grounding_ctx)
                kind = "ungrounded-source"
                declined = not use_current and _is_prose_decline(candidate)
                if declined:
                    # The delegate followed its rule ("return a one-line
                    # explanation of what source is missing instead of code").
                    # Record ITS words as the attempt, not a gate verdict on
                    # prose (dev/115 field fix, 2026-09-08).
                    refusal = f"the content builder declined: {candidate.strip()}"
                    kind = "source-missing"
                verdict_result = {
                    "verdict": "fail",
                    "evidence": {"kind": kind, "detail": refusal[:2000]},
                }
                yield "round_verdict", {"round": rounds_used, "verdict": "fail"}
                rounds_trace.append(f"round {rounds_used}: fail — {refusal[:160]}")
                attempts.append({
                    "round": rounds_used, "contentSha256": _content_sha(candidate),
                    "verdict": "fail", "kind": kind,
                    "detail": refusal[:_ATTEMPT_DETAIL_CHARS],
                    "source": "current content" if use_current else "generated",
                    # dev/127: what was refused, verbatim — the literal the
                    # gate named is IN this text, so showing it is the point.
                    **_attempt_code_field(candidate, prose=declined),
                })
                if declined:
                    # dev/116: when the decline is about a credential and the
                    # failed attempt named a host, the remedy is concrete —
                    # add a connection key for that host (or use the saved one).
                    remedy = _decline_remedy(candidate, previous_attempt, grounding_ctx)
                    if remedy:
                        verdict_result["evidence"]["remedy"] = remedy
                        attempts[-1]["remedy"] = remedy
                    # A decline names an input nobody in this loop can supply
                    # (a key, a path, a URL). Asking the same builder again
                    # with the same inputs only repeats it — the user is the
                    # correction; stop and say so.
                    stopped_by = "decline"
                    break
                previous_attempt = candidate
                previous_error = refusal
                url_evidence = []
                continue
        # A repeat is judged AFTER the gate: a refused candidate keeps its own kind.
        if not use_current and previous_attempt is not None and _same_code(candidate, previous_attempt):
            # dev/116 live fix (2026-09-09): the correction changed only
            # comments or spacing — running it again would fail the same
            # way. Not run; the next round is told so, in plain words.
            detail = (
                "the correction repeated the previous attempt (only comments or spacing "
                "changed) — not run again; change the request that failed: "
                + (previous_error or "")[:400]
            )
            verdict_result = {
                "verdict": "fail",
                "evidence": {"kind": "repeated-attempt", "detail": detail[:2000]},
            }
            yield "round_verdict", {"round": rounds_used, "verdict": "fail"}
            rounds_trace.append(f"round {rounds_used}: fail — repeated the previous attempt")
            attempts.append({
                "round": rounds_used, "contentSha256": _content_sha(candidate),
                "verdict": "fail", "kind": "repeated-attempt",
                "detail": detail[:_ATTEMPT_DETAIL_CHARS], "source": "generated",
                **_attempt_code_field(candidate),
            })
            repeats += 1
            if repeats >= _MAX_REPEATED_ATTEMPTS:
                # dev/127: one repeat is worth telling the model about (dev/116
                # does); a second means more rounds would only buy more copies
                # of the same code. More retries must not mean more identical
                # retries.
                stopped_by = "repeat"
                break
            previous_attempt = candidate
            previous_error = detail
            continue  # url_evidence: unchanged — same request, same answer
        dataset_paths = None
        if dataset_paths_fn is not None:
            try:
                slice_codes = [
                    str(n.get("content") or "")
                    for n in ((spec.get("dataflow") or {}).get("nodes") or [])
                    if isinstance(n, dict)
                ]
                dataset_paths = dataset_paths_fn([candidate, *slice_codes]) or None
            except Exception:
                dataset_paths = None
        # dev/116: the connection keys THIS candidate names, resolved per round
        # so a correction that adopts curio_secret("<name>") runs with it.
        secrets = None
        if secrets_fn is not None:
            try:
                secrets = secrets_fn([candidate]) or None
            except Exception:
                secrets = None
        # dev/118 commit 4: the outputs recorded for ancestors that passed
        # earlier in this batch stand in for their re-run (fresh per round).
        prior_outputs = None
        if prior_outputs_fn is not None:
            try:
                prior_outputs = prior_outputs_fn() or None
            except Exception:
                prior_outputs = None

        def _validate_with(prior, candidate_text=candidate, paths=dataset_paths, secret_values=secrets):
            progress_queue: _queue.Queue = _queue.Queue()

            def _run_validation():
                try:
                    result = validation.validate_candidate(
                        user_key, project_id, spec, node_id, candidate_text,
                        exec_fn=exec_fn,
                        available_templates=available,
                        dataset_paths=paths,
                        exec_user_key=exec_user_key,
                        secrets=secret_values,
                        prior_outputs=prior,
                        templates=loop_templates,
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
                thread.join(timeout=5)
                return item[1]

        verdict_result = yield from _validate_with(prior_outputs)
        reuse_retried = False
        if prior_outputs and _looks_like_a_vanished_reused_input(verdict_result):
            # A reused artifact is gone (the sandbox store moved on): that is
            # not the candidate's fault. Once, silently, the slice runs whole.
            verdict_result = yield from _validate_with(None)
            reuse_retried = True
        yield "round_verdict", {
            "round": rounds_used, "verdict": verdict_result["verdict"],
        }
        round_evidence = (verdict_result.get("evidence") or {})
        rounds_trace.append(
            f"round {rounds_used}: {verdict_result['verdict']}"
            + (
                # dev/127: the exception line, whole — this is the line that
                # reached the owner's chat as "round 2: execution-error — de".
                " — " + failure_text.summary(
                    round_evidence.get("stderrTail") or round_evidence.get("detail") or "",
                    code=candidate, limit=200,
                )
                if verdict_result["verdict"] != "pass"
                else f" — output {round_evidence.get('outputDataType') or '?'}"
            )
        )
        attempt = {
            "round": rounds_used,
            "contentSha256": _content_sha(candidate),
            "verdict": verdict_result["verdict"],
            "kind": round_evidence.get("kind"),
            "source": "current content" if use_current else "generated",
        }
        if round_evidence.get("detail"):
            attempt["detail"] = str(round_evidence["detail"])[:_ATTEMPT_DETAIL_CHARS]
        if round_evidence.get("stderrTail"):
            attempt["stderrTail"] = str(round_evidence["stderrTail"])[-_ATTEMPT_STDERR_CHARS:]
        if round_evidence.get("outputDataType"):
            attempt["outputDataType"] = round_evidence["outputDataType"]
        if round_evidence.get("durationMs") is not None:
            attempt["durationMs"] = round_evidence["durationMs"]
        if round_evidence.get("reusedNodes"):
            attempt["reusedNodes"] = list(round_evidence["reusedNodes"])[:12]
        if reuse_retried:
            attempt["reuseRetried"] = True
        if verdict_result["verdict"] != "pass":
            # dev/127: the code that ran and failed, ON the attempt — the
            # owner could not see any of it without opening another chat.
            attempt.update(_attempt_code_field(candidate))
        attempts.append(attempt)
        if verdict_result["verdict"] != "fail":
            stopped_by = "passed" if verdict_result["verdict"] == "pass" else (
                "infrastructure" if verdict_result["verdict"] == "infrastructure" else None
            )
            break
        if round_evidence.get("kind") == "precondition" or round_evidence.get("upstreamEmpty"):
            # dev/118: the runner refused the SLICE (bound, cycle), or an
            # upstream has no content yet — no correction of THIS content can
            # change that; one round says so.
            stopped_by = "blocker"
            break
        previous_attempt = candidate
        previous_error = round_evidence.get("stderrTail") or round_evidence.get("detail") or ""
        url_evidence = _correction_url_evidence(candidate, previous_error, grounding_ctx)
        if url_evidence:
            # The endpoint's real answer joins the trail the card shows, so a
            # key-gated API reads as such instead of as a JSON decode error.
            attempt["endpointEvidence"] = _url_evidence_summary(url_evidence)
    final_evidence = (verdict_result or {}).get("evidence") or {}
    final_verdict = verdict_result["verdict"] if verdict_result else "fail"
    if (
        is_data_loading
        and resolve_source is not None
        and final_verdict == "fail"
        and final_evidence.get("kind") in ("ungrounded-source", "source-missing")
    ):
        # dev/126: the round itself proved the source is missing — the gate
        # refused the literal the builder wrote, or the builder declined and
        # named what it needs. THIS is where the old dead end was: a failure
        # whose remedy text asked the user to attach the Dataset Finder by
        # hand. Discovery is initiated on that evidence, the attempt trail is
        # kept (the user sees what was tried), and the node WAITS instead of
        # failing.
        try:
            post = resolve_source(node, grounding_ctx, stage="post") or {}
        except Exception:  # noqa: BLE001
            log.warning("Post-failure source resolution failed for node %s",
                        node_id, exc_info=True)
            post = {}
        if post.get("state") == "unresolved" and post.get("detail"):
            final_evidence = {**final_evidence,
                              "discovery": str(post["detail"])[:600]}
            rounds_trace.append(
                f"discovery found no source — {str(post['detail'])[:160]}"
            )
        if post.get("state") == "awaiting":
            detail = str(post.get("detail") or "a source must be selected")
            rounds_trace.append(f"awaiting dataset selection — {detail[:160]}")
            return {
                "verdict": "awaiting-source",
                "evidence": {
                    "kind": "awaiting-selection",
                    "detail": detail[:2000],
                    "after": str(final_evidence.get("detail") or "")[:600],
                    **({"remedy": {
                        "kind": "dataset-selection",
                        "attachmentId": post["attachmentId"],
                        "nodeId": node_id,
                    }} if post.get("attachmentId") else {}),
                },
                "rounds": rounds_used,
                "candidate": "",
                "delegations": delegations,
                "roundsTrace": rounds_trace,
                "attempts": attempts,
                "stoppedBy": "source",
            }
    return {
        "verdict": final_verdict,
        "evidence": final_evidence,
        "rounds": rounds_used,
        "candidate": candidate,
        "delegations": delegations,
        "roundsTrace": rounds_trace,
        "attempts": attempts,
        # dev/127: which bound ended the loop. Unset means the rounds ran out.
        "stoppedBy": stopped_by or "rounds",
    }


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
    """The validate-node body over the ONE verified-content loop (dev/115):
    the loop streams its rounds live; this body owns the framing turns, the
    reviewed mint with the validation block, the per-node ledger, and the
    finally that clears the in-flight guard on every exit, disconnect
    included."""
    node_id = node.get("id")
    execution_id = uuid.uuid4().hex
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
        outcome = yield from _verified_content_rounds(
            user_key, project_id,
            spec=spec, node=node, resolution=resolution, config=config,
            parent_execution_id=execution_id, parent_coord=coord,
            attachment_id=attachment_id, exec_fn=exec_fn,
            grounding_loop_ctx={
                "attachment_id": attachment_id, "session_id": session_id,
                "granted": [], "manifest": None,
            },
            dataset_paths_fn=lambda codes: _exec_dataset_paths(project_id, *codes),
            exec_user_key=user_key,
            secrets_fn=_exec_secrets_resolver(user_key),
            resolve_source=_source_resolver(
                user_key, project_id, coord=coord, attachment_id=attachment_id,
                execution_id=execution_id, config=config,
                extra_texts=(str((spec.get("dataflow") or {}).get("task") or ""),),
            ),
        )
        rounds_used = outcome["rounds"]
        candidate = outcome["candidate"]
        rounds_trace = outcome["roundsTrace"]
        done: dict = {
            "verdict": outcome["verdict"],
            "evidence": outcome["evidence"],
            "rounds": rounds_used,
            "nodeId": node_id,
            "attempts": outcome["attempts"],
        }
        if done["verdict"] in ("pass", "fail", "not-executable") and candidate:
            # PASS or FAIL, the user decides — the proposal carries the
            # validation block so the review is informed, never gatekept.
            # dev/118: NOT-EXECUTABLE (a browser-rendered kind) is proposed
            # too, labeled — nothing ran, and the block says so.
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
                    # dev/115: the attempt trail — every round's error and
                    # fix, rendered as a collapsed list on the card.
                    "attempts": done["attempts"],
                }
                done["proposalId"] = part["proposalId"]
                done["proposalAttachmentId"] = mint_attachment
                trace_card = {
                    "type": "card",
                    "kind": "result" if done["verdict"] in ("pass", "not-executable") else "error",
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
                                status="ok" if done["verdict"] in ("pass", "not-executable") else "failed",
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
            if done["verdict"] in ("pass", "not-executable"):
                # dev/118: a browser-rendered kind proceeds like a pass in the
                # plan's ledger (Simulation Mode auto-approves it); the
                # proposal's validation block carries the honest label.
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
        # tokens are still spent, so the ledger counts them.
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
        ledger.record_housekeeping_usage(user_key, usage_sink, note="title-call")
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
    """Dispatch inputs for one run.

    This was admission, then a policy resolver, and is now neither. It resolved
    account/template/attachment run ceilings and a budget the ledger gated on
    (all removed: Curio does not meter agent runs), then a three-scope
    ``maxOutputTokens``, whose editor had no interface left to reach it. What
    remains is the deployment-wide output cap and the two keys the ledger
    records so a run can be attributed to a template and an attachment.
    """
    attachment_id = (attachment_record or {}).get("attachmentId")
    max_output = DEPLOYMENT_MAX_OUTPUT_TOKENS
    return {
        "admit": {
            "template_key": f"{project_id}/{coord}",
            "attachment_key": attachment_id if isinstance(attachment_id, str) else None,
        },
        "max_output_tokens": max_output,
        # Pinned on the execution record: what the run was actually dispatched
        # with, so a later change of the constant does not rewrite history.
        "policy_pins": {"maxOutputTokens": max_output},
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
    delegations: list | None = None,
    refused_rounds: int = 0,
    retry_of: str | None = None,
) -> dict:
    """Assemble the per-run execution record persisted on the agent turn.

    ``usage`` is actual token counts or ``None``, never estimated - summed
    across loop rounds when tools ran, which is also when ``toolCalls``
    records what executed. There is no ``costUsd``: Curio ships no price
    table, so a USD figure would be invented. ``delegations`` lists the run's
    child execution records, each with its own pins, usage, and
    ``parentExecutionId`` back-link."""
    record = {
        "executionId": execution_id,
        "pins": pins,
        "usage": dict(usage) if usage else None,
        "durationMs": int((time.monotonic() - started) * 1000),
        "status": status,
    }
    if tool_calls:
        record["toolCalls"] = list(tool_calls)
    if delegations:
        record["delegations"] = list(delegations)
    if refused_rounds:
        # dev/105 D2 (additive): parameter refusals that did NOT spend a round
        # — auditable beside toolCalls[].status so a run that leaned on the
        # free corrections is legible after the fact.
        record["refusedRounds"] = refused_rounds
    if retry_of:
        # dev/115 (DEC-021): a retry after an interruption is a NEW execution
        # linked to the one that expired — nothing was replayed.
        record["retryOf"] = retry_of
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
    # DEC-080 (dev/126): a project whose lockfile predates this agent's
    # requiresAgents declaration gets it completed HERE — before the messages
    # are composed, so the run resolves its required delegates instead of
    # stalling on a reviewed install for one of them.
    if _repair_required_closure(user_key, project_id, coord, attachment_id=attachment_id):
        spec = _read_spec_or_404(user_key, project_id)
        record = _record_or_404(spec, attachment_id)
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
        # dev/99 R1.1: ONE snapshot feeds both halves of the roster. Fetching
        # them separately left the two lists able to describe different
        # instants — a package could appear as "not enlisted" in one and be
        # missing from the other — which is the tear the composite exists to
        # remove.
        from utk_curio.backend.app.packages import services as packages_services

        try:
            landscape = packages_services.template_landscape(user_key, project_id)
        except Exception as exc:  # a broken registry degrades to no listing, not a 500
            # dev/105: but never SILENTLY — a vanished roster is the dev/93 D2
            # failure shape (a swallowed cause surfacing layers away as "that
            # template is not available"), so the cause is logged here.
            log.warning(
                "Template roster unavailable for project %s (%s: %s) — run "
                "proceeds without it", project_id, type(exc).__name__, exc,
            )
            landscape = None
        templates_block = _available_templates_block(
            project_id, landscape,
            notes_agent="research.notes.compose" in (
                getattr(manifest, "capability_ids", None) or []
            ),
        )
        if templates_block:
            system_content = f"{system_content}\n\n{templates_block}"
        # dev/93 D4: the second half of the roster — what the user owns but
        # this project has not enlisted — goes only to a run that can act on
        # it. Offering it without the grant would name a door the model
        # cannot open, which is how the Researcher ended up authoring a
        # duplicate package instead.
        if "package.install" in granted:
            enlistable = _enlistable_templates_block(
                project_id, landscape, _TEMPLATES_BLOCK_MAX_ENTRIES
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


_NO_NOTE_TEMPLATE_LINE = (
    "None of these renders a note (no presentation template is enlisted in this "
    "project): code templates and node types you see on the canvas cannot hold "
    "note content — take the 'Installed but NOT enlisted in this project' rung "
    "(when offered) or delegate authoring; do not node.create on any of the above."
)


def roster_block(templates: list, *, notes_agent: bool = False) -> str | None:
    """The roster listing a run's system turn carries, for a caller outside a run.

    A thin public wrapper over :func:`_available_templates_block`, added by memo
    dev/122 so the training-set builder composes its system turn with the SAME
    formatter a live run uses. Building a training example against a
    hand-written roster paragraph would teach the model a prompt shape the
    runtime never sends — a second vocabulary of exactly the kind ``DEC-062``
    exists to prevent.

    ``templates`` is a roster row list as ``packages_services.available_templates``
    returns it. There is no project here, so the log line's project id reads
    ``"training"``.
    """
    return _available_templates_block(
        "training", {"available": list(templates)}, notes_agent=notes_agent
    )


def _available_templates_block(
    project_id: str, landscape: dict | None, *, notes_agent: bool = False
) -> str | None:
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
    entries = [t for t in (landscape or {}).get("available", []) if t.get("authorable")]
    shown = entries[:_TEMPLATES_BLOCK_MAX_ENTRIES]
    if len(entries) > len(shown):
        log.warning(
            "Template roster truncated for project %s: %d of %d available "
            "templates listed",
            project_id, len(shown), len(entries),
        )
    if not shown:
        # dev/105 S1: an EMPTY roster is said, not omitted. The live failure:
        # this project's only available template was a Python compute node
        # (not authorable, so filtered out above), the section vanished, and
        # the model reached for the node type it could see on the canvas via
        # dataflow.read — refused, one round spent. Silence read as "no rule
        # here"; the explicit line names the rule and the way out.
        return (
            "Available node templates: none — nothing enlisted in this project "
            "can hold authored content. Node types you see on the canvas or in "
            "dataflow.read that are not listed here cannot take content; use the "
            "'Installed but NOT enlisted in this project' list (when offered) or "
            "delegate authoring instead of creating a node."
        )
    block = (
        "Available node templates (a node.create nodeType or a plan nodeType "
        "MUST be one of these ids; the versioned form "
        "'<packageId>/<templateId>@<major>' is also accepted):\n"
        + "\n".join(_template_line(t) for t in shown)
    )
    # dev/105 S1: the live roster held twelve built-in CODE templates and no
    # note template; the model took the post-it compute node it saw on the
    # canvas — refused, one round spent. A note-composing run is told, in the
    # roster itself, that nothing here renders a note and where the rung is.
    if notes_agent and not any(t.get("presentation") for t in shown):
        block = f"{block}\n{_NO_NOTE_TEMPLATE_LINE}"
    return block


def _enlistable_templates_block(project_id: str, landscape: dict | None, budget: int) -> str | None:
    """The "installed but not enlisted" half of the roster (memo dev/93 D4).

    Separate function, one shared line format: the sections are composed
    together but only this one is grant-gated, and it names the dirName the
    ``package.install`` proposal takes so the model never has to guess it.
    """
    if budget <= 0:
        return None
    rows = [
        r for r in (landscape or {}).get("notEnlisted", []) if r.get("authorable")
    ]
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
# to tune it.
# dev/73: 3 — the Node Builder's documented modify flow (read the node →
# delegate generation → propose) is a three-round sequence; 2 forced models
# that follow their instructions to answer in prose instead of proposing.
MAX_TOOL_ROUNDS = 3

# dev/105 D2: a PARAMETER refusal — the mint rejected the request's params
# before touching any store, provider, or delegate — is a millisecond
# round-trip that produced exactly the correction the model needs. It does
# not spend a MAX_TOOL_ROUNDS round (that budget is provider cost; a refusal
# costs none) — up to this many per run, after which refusals count as rounds
# again so a model that never corrects still hits the dev/73 cap and its
# cutoff card. The live failure this fixes: search + two refusals = cap, and
# the reuse ladder's last rung (AUTHOR) was unreachable no matter what the
# model decided next.
MAX_REFUSED_ROUNDS = 2


class ParamRefusal(str):
    """The typed marker for a parameter refusal's text (dev/105 D2).

    A ``str`` subclass so every existing consumer — the tool-result message,
    the execution record, tests asserting on the text — sees a plain string;
    only the loop's round accounting asks ``isinstance``. A refusal caused by
    a broken store/catalog/spec is deliberately NOT one of these: that cost
    real work and must keep counting as a round so a dead store cannot loop.
    """


def _refuse_params(text: str) -> tuple[str, str, None]:
    """``("refused", ParamRefusal(text), None)`` — the mint return for a
    request the model can fix by changing its params."""
    return "refused", ParamRefusal(text), None

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
    # dev/114 (DEC-072): the gate, keyed on the EXISTING node's type — the
    # dev/73 runtime review mint inherits it (a refusal is its honest text).
    from utk_curio.backend.app.packages import services as packages_services

    entry, _err = packages_services.resolve_template(user_key, project_id, node.get("type"))
    verdict, refusal = _gate_generated_content(
        user_key, project_id, loop_ctx,
        code=proposed, engine=(entry or {}).get("engine"),
        node_type=node.get("type"), params=params,
        base=loop_ctx.get("_grounding_base"),
    )
    if refusal:
        return _refuse_params(refusal)
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
    proposal = {
        "proposalId": proposal_id,
        "tool": "node.content.write",
        "nodeId": node_id,
        "content": proposed,
        "contentSha256": basis,
        "summary": summary,
        "status": "pending",
    }
    if verdict.source:
        part["source"] = verdict.source
        proposal["source"] = verdict.source
    _store_proposal(user_key, project_id, spec, loop_ctx, proposal, part)
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
        return _refuse_params(err)
    proposed = content.extract_node_content(params.get("content"))
    if not proposed:
        return _refuse_params("params.content must be a non-empty string")
    if len(proposed) > content.PROPOSAL_CONTENT_MAX_CHARS:
        return _refuse_params("params.content exceeds the proposal size bound")
    # dev/114 (DEC-072): the source-grounding gate — BEFORE any store write.
    # A same-run node.create after the runtime minted dataset candidates is
    # refused too: the user reviews and confirms a source first (DEC-006).
    if loop_ctx.get("_candidates_pending_review"):
        return _refuse_params(_CANDIDATES_PENDING_TEXT)
    verdict, refusal = _gate_generated_content(
        user_key, project_id, loop_ctx,
        code=proposed, engine=entry.get("engine"), node_type=entry["id"], params=params,
    )
    if refusal:
        return _refuse_params(refusal)
    goal = params.get("goal")
    goal = goal.strip() if isinstance(goal, str) and goal.strip() else None
    # dev/105 A2 (additive): the node's HEADER. The note behavior renders
    # `title` (falling back to "Note"); `goal` is the purpose line. The mint
    # used to drop this param while the prompt asked for it — the second
    # live test's notes were all headed "Note".
    title = params.get("title")
    title = title.strip()[:_NODE_TITLE_MAX_CHARS] if isinstance(title, str) and title.strip() else None
    # dev/89 (additive): optional appearance, normalized by the ONE shared
    # utility — an invalid or inaccessible color refuses at mint, loudly.
    from utk_curio.backend.app.packages import node_appearance

    raw_appearance = params.get("appearance")
    if raw_appearance is None and _notes_agent_run(loop_ctx) and entry.get("presentation"):
        # dev/105 A2: the A13 default on the Researcher's OWN attachment path
        # — dev/95 already filled it on the delegate path. First note of the
        # run yellow (the question), the rest green (answers). Only a
        # note-composing run on a PRESENTATION template; a supplied color
        # always wins; every other agent/template is byte-unchanged.
        k = loop_ctx.get("_note_creates", 0)
        raw_appearance = {"backgroundColor": _NOTES_DEFAULT_COLORS[min(k, 1)]}
    try:
        appearance = node_appearance.normalize_appearance(raw_appearance)
    except node_appearance.AppearanceError as exc:
        return _refuse_params(f"params.appearance: {exc}")
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    proposal_id = uuid.uuid4().hex
    summary = f"Create a new {entry['label']} node" + (f" · {title}" if title else "")
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="node.create",
        summary=summary,
        preview=proposed,
        # dev/119 (DEC-076): the roster's own answer to "can the sandbox run
        # this kind" rides the card — display, never a revision pin — so no
        # frontend file keeps a list of executable kinds.
        pins={"nodeType": entry["id"], "executable": bool(entry.get("executable"))},
    )
    proposal = {
        "proposalId": proposal_id,
        "tool": "node.create",
        "nodeType": entry["id"],
        "content": proposed,
        "summary": summary,
        "status": "pending",
    }
    if verdict.source:
        # dev/114: what the code opens/fetches and how it was grounded — the
        # card's Source block; display + provenance, never a pin.
        part["source"] = verdict.source
        proposal["source"] = verdict.source
    if goal:
        proposal["goal"] = goal
    if title:
        proposal["title"] = title
    if appearance:
        proposal["appearance"] = appearance
    _store_proposal(user_key, project_id, spec, loop_ctx, proposal, part)
    loop_ctx["_note_creates"] = loop_ctx.get("_note_creates", 0) + 1  # A13 index
    return (
        "proposed",
        f"proposal {proposal_id} created for a new {entry['label']} node; it awaits "
        "the user's explicit review — do NOT assume it was applied",
        part,
    )


def _verify_candidate_parts(parts: list, loop_ctx: dict | None = None) -> None:
    """dev/67-4 (DEC-053): the Dataset Finder stops laundering — external
    candidate rows are verified DETERMINISTICALLY before they reach the user.
    URL-bearing rows are probed through the egress policy (first 4 — the
    run-budget shape; provider refinements like Socrata add dataset
    name/columns on top of the generic gate, which covers ANY dataset API);
    URL-less rows are loudly UNVERIFIED. The evidence rides the row into the
    card and the Node Builder handoff."""
    # One budget for the whole pass, spent per real HTTP request rather than
    # per row. The old counter ticked once per candidate while a single row
    # could issue a dozen requests (a Socrata probe fetched twice, and every
    # fetch follows up to MAX_REDIRECTS hops), so the documented bound of
    # MAX_CALLS_PER_RUN bore no relation to what actually went out.
    # dev/114: the budget is the RUN's when a loop context rides along — the
    # grounding gate's mint-time probes and this pass spend the same four
    # requests — and every verified row is remembered so a same-run
    # confirmation grounds its URL without re-spending.
    budget = (
        _run_egress_budget(loop_ctx)
        if loop_ctx is not None
        else egress.CallBudget(_RUN_EGRESS_CALLS)
    )
    for part in parts:
        if not isinstance(part, dict) or part.get("type") != "datasetCandidates":
            continue
        lanes = part.get("lanes") or {}
        for row in lanes.get("external") or []:
            if not isinstance(row, dict):
                continue
            url = row.get("url")
            if not url:
                row["verification"] = verify.verify_external_source(None)
                continue
            if budget.exhausted:
                row["verification"] = {
                    "status": "unverified",
                    "detail": "the egress budget was spent before this row — not checked",
                }
                continue
            row["verification"] = verify.verify_external_source(url, budget=budget)
            if loop_ctx is not None and row["verification"].get("status") == "verified":
                loop_ctx.setdefault("_verified_urls", {})[url] = row["verification"]


def _run_egress_budget(loop_ctx: dict) -> "egress.CallBudget":
    """dev/114: ONE egress budget per run (or per Solve batch) — created lazily
    on the loop context, shared by candidate verification and the grounding
    gate's probes, so ``MAX_CALLS_PER_RUN`` means the run's total."""
    budget = loop_ctx.get("_egress_budget")
    if budget is None:
        budget = egress.CallBudget(int(loop_ctx.get("_egress_limit") or _RUN_EGRESS_CALLS))
        loop_ctx["_egress_budget"] = budget
    return budget


#: dev/114: the text a same-run node.create/insert gets after the runtime
#: minted dataset candidates — the user reviews first (DEC-006).
_CANDIDATES_PENDING_TEXT = (
    "dataset candidates are shown to the user for review — do not propose a "
    "node in this turn; end your reply by asking the user to select and "
    "confirm a source, then build from the confirmed one on the next turn"
)


def _catalog_grounding_refs(project_id: str) -> tuple[dict, dict]:
    """dev/114: ``(by_path, by_id)`` — the datasets the datasets domain lists
    for this project, the SAME listing ``catalog.search`` serves, so a row the
    tool showed is grounded by construction: by resolved path (the historical
    literal form) and by id (the portable ``curio_dataset_path("<id>")`` call
    the loader recipe emits, resolved by the sandbox at run time). A failing
    catalog read degrades to empty maps (logged): the gate still refuses
    ungrounded sources, honestly, rather than inventing a neighborhood."""
    try:
        from flask import g, has_request_context

        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )

        user = getattr(g, "user", None) if has_request_context() else None
        listing = DatasetCatalogService(user).list_catalog(dataflow_id=project_id)
    except Exception:  # a broken catalog is data, never a run error
        log.warning(
            "Could not read the Data Catalog for source grounding (project %s) — "
            "catalog paths are treated as unknown this run", project_id, exc_info=True,
        )
        return {}, {}
    by_path: dict = {}
    by_id: dict = {}
    for item in (listing or {}).get("items") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        path = item.get("path")
        ref = source_grounding.CatalogRef(
            dataset_id=str(item.get("id")),
            title=str(item.get("title") or item.get("id") or ""),
            format=str(item.get("format") or ""),
            path=path if isinstance(path, str) else "",
        )
        by_id[ref.dataset_id] = ref
        if isinstance(path, str) and path.strip():
            by_path[path] = ref
    return by_path, by_id


def _session_grounding_evidence(
    user_key: str, project_id: str, loop_ctx: dict
) -> tuple[list[str], dict]:
    """dev/114: what this conversation already established — the user's own
    texts (the current message first) and every candidate row the runtime
    verified (persisted turns + this run's ``_verified_urls``)."""
    texts: list[str] = []
    verified: dict = {}
    message = loop_ctx.get("message")
    if isinstance(message, str) and message.strip():
        texts.append(message)
    session_id = loop_ctx.get("session_id")
    if isinstance(session_id, str):
        try:
            turns = sessions.read_turns(user_key, project_id, session_id)
        except Exception:
            turns = []
        for turn in turns:
            if turn.get("role") == "user" and isinstance(turn.get("text"), str):
                texts.append(turn["text"])
            for part in turn.get("content") or []:
                if not isinstance(part, dict) or part.get("type") != "datasetCandidates":
                    continue
                for row in ((part.get("lanes") or {}).get("external") or []):
                    if not isinstance(row, dict):
                        continue
                    evidence = row.get("verification")
                    if (
                        isinstance(row.get("url"), str)
                        and isinstance(evidence, dict)
                        and evidence.get("status") == "verified"
                    ):
                        verified[row["url"]] = evidence
    for url, evidence in (loop_ctx.get("_verified_urls") or {}).items():
        verified[url] = evidence
    return texts, verified


def _grounding_context(
    user_key: str,
    project_id: str,
    loop_ctx: dict,
    *,
    node_type: object,
    params: dict | None = None,
    extra_texts: tuple = (),
    base: dict | None = None,
    is_data_loading: bool | None = None,
) -> "source_grounding.GroundingContext":
    """dev/114 (DEC-072): everything the gate needs for ONE mint — catalog
    paths, the conversation's evidence, the run-budgeted prober, and the
    grant-aware corrective routes. ``base`` (a Solve batch's precomputed
    catalog paths / texts / verified map) replaces the per-mint reads."""
    from utk_curio.backend.app.packages import services as packages_services

    canonical = packages_services.canonical_template_id(node_type) if node_type else ""
    if is_data_loading is None:
        is_data_loading = source_grounding.is_data_loading_type(canonical)
    if base is not None:
        catalog_paths = base.get("catalog_paths") or {}
        catalog_ids = base.get("catalog_ids") or {}
        texts = list(base.get("texts") or [])
        verified = dict(base.get("verified") or {})
        secrets = dict(base["secrets"]) if "secrets" in base else _connection_key_refs(user_key)
    else:
        catalog_paths, catalog_ids = _catalog_grounding_refs(project_id)
        texts, verified = _session_grounding_evidence(user_key, project_id, loop_ctx)
        secrets = _connection_key_refs(user_key)
    texts.extend(t for t in extra_texts if isinstance(t, str) and t.strip())
    budget = _run_egress_budget(loop_ctx)
    cache: dict = loop_ctx.setdefault("_probe_cache", {})

    def _probe(url: str, *, headers=None, params=None) -> dict:
        keyed = bool(headers or params)
        if not keyed and url in cache:
            return cache[url]
        if budget.exhausted:
            return {
                "status": "unverified",
                "detail": "the egress budget was spent before this URL — not checked",
            }
        if keyed:
            # dev/116: a probe carrying a connection key is evidence for ONE
            # correction — never cached under the bare URL, never a verified
            # source (the caller redacts the outcome).
            return verify.verify_external_source(url, budget=budget, headers=headers, params=params)
        result = verify.verify_external_source(url, budget=budget)
        cache[url] = result
        if result.get("status") == "verified":
            loop_ctx.setdefault("_verified_urls", {})[url] = result
            # The context's own map too: a URL the gate verified THIS run is
            # evidence the next correction round is handed (dev/115 field fix,
            # 2026-09-08 — the current content's Census URL passed the gate by
            # probe, the correction saw an empty ``verifiedUrls`` and the
            # content builder rightly declined to write code).
            verified[url] = result
        return result

    hints: list[str] = []
    if "catalog.search" in (loop_ctx.get("granted") or []):
        hints.append("a `path` from a catalog.search row (granted — search first)")
    manifest = loop_ctx.get("manifest")
    if "agent.dataset-finder" in (getattr(manifest, "delegates_to", None) or []):
        hints.append(
            "a URL the runtime verified — delegate the dataset.discover capability "
            "to find and verify candidates first, then build from the one the user confirms"
        )
    elif verified:
        hints.append("a URL already verified in this conversation")
    hints.append(
        'declare "synthetic": true in the params ONLY when the user asked for made-up data'
    )
    if secrets:
        hints.append(
            "a saved connection key by name — " + "; ".join(
                ref.use_line for ref in list(secrets.values())[:6]
            )
        )
    secret_values = _exec_secrets_resolver(user_key)
    return source_grounding.GroundingContext(
        catalog_paths=catalog_paths,
        catalog_ids=catalog_ids,
        user_paths=source_grounding.user_paths(texts),
        verified_urls=verified,
        synthetic_requested=source_grounding.synthetic_requested(texts, params),
        is_data_loading=is_data_loading,
        probe=_probe,
        hints=hints,
        secrets=secrets,
        secret_values=lambda names: secret_values(
            [f'curio_secret("{n}")' for n in names]
        ),
    )


def _gate_generated_content(
    user_key: str,
    project_id: str,
    loop_ctx: dict,
    *,
    code: str,
    engine: object,
    node_type: object,
    params: dict | None = None,
    extra_texts: tuple = (),
    base: dict | None = None,
    is_data_loading: bool | None = None,
) -> tuple["source_grounding.GroundingVerdict", str | None]:
    """The ONE call every agent-authored-content boundary makes (dev/114):
    ``(verdict, refusal_text | None)``. The refusal is model-correctable
    (DEC-067) and names only routes this run can take."""
    ctx = _grounding_context(
        user_key, project_id, loop_ctx, node_type=node_type, params=params,
        extra_texts=extra_texts, base=base, is_data_loading=is_data_loading,
    )
    engine_name = engine if isinstance(engine, str) and engine else "python"
    verdict = source_grounding.check_grounding(code, engine_name, ctx)
    if verdict.ok:
        return verdict, None
    return verdict, source_grounding.refusal_text(verdict, ctx)


def _source_grounding_inputs(ctx: "source_grounding.GroundingContext") -> dict:
    """dev/114: the grounding a tool-less content delegate is HANDED (the
    DEC-063 pattern — evidence as inputs): the catalog datasets with their
    real paths, the paths the user typed, the URLs already verified, and the
    rule. Bounded; plain data."""
    datasets = [
        {
            "datasetId": ref.dataset_id,
            "title": ref.title,
            "format": ref.format,
            "use": f'dataset_path = curio_dataset_path("{ref.dataset_id}")',
            **({"path": ref.path} if ref.path else {}),
        }
        for ref in list(ctx.catalog_ids.values())[:24]
    ]
    secrets = [
        {
            "name": ref.name,
            "host": ref.host,
            "delivery": ref.delivery,
            "use": ref.use_line,
        }
        for ref in list((ctx.secrets or {}).values())[:24]
    ]
    return {
        "catalogDatasets": datasets,
        "userPaths": sorted(ctx.user_paths)[:24],
        "verifiedUrls": sorted(ctx.verified_urls)[:24],
        "availableSecrets": secrets,
        "syntheticRequested": bool(ctx.synthetic_requested),
        "rule": (
            "Load catalog datasets ONLY through their `use` line "
            "(curio_dataset_path(\"<id>\") — the sandbox resolves it), open ONLY the "
            "local paths listed (catalogDatasets[].path or userPaths), and fetch ONLY "
            "these URLs (verifiedUrls). Never invent a filename, never "
            "assume a file exists, never write a URL from memory — the runtime "
            "refuses ungrounded content. If none of these fits the intent, return "
            "a one-line explanation of what source is missing instead of code."
            + (
                " A key-gated host is reachable ONLY through a saved connection key: "
                "copy its `use` line (curio_secret(\"<name>\") — the sandbox resolves "
                "it) and send the value the way `delivery` says (query:<param> / "
                "header:<Name> / code = as the API documents). Never write a key "
                "value into the code; if the host needs a key and availableSecrets "
                "lists none for it, return the one-line explanation naming the host."
                if secrets else
                " A key-gated host has no saved connection key here: do not invent one — "
                "return the one-line explanation naming the host that needs a key."
            )
            + (
                " The user asked for synthetic data: build it inline and say so."
                if ctx.synthetic_requested else ""
            )
        ),
    }


def _connection_key_refs(user_key: str) -> dict:
    """dev/116: the user's saved connection keys as ``SecretRef``s (names,
    hosts, delivery — never values). Read in the request thread; a missing or
    unreadable store is simply no keys."""
    from utk_curio.backend.app.users.connection_keys import default_store

    try:
        return {
            ref.name: source_grounding.SecretRef(ref.name, ref.host, ref.delivery)
            for ref in default_store().list(user_key)
        }
    except Exception:
        return {}


def _exec_secrets_resolver(user_key: str):
    """dev/116: ``codes -> {name: value}`` for the ``curio_secret("<name>")``
    calls in *codes* — the ONE reader of values on the agent path. The user
    key is captured here (request thread); the store needs no request context,
    so a job thread may call the closure per round (dev/115 lesson 1)."""
    from utk_curio.backend.app.users.connection_keys import default_store, secret_names

    def _resolve(codes) -> dict:
        names: list[str] = []
        for code in codes or ():
            for name in secret_names(code):
                if name not in names:
                    names.append(name)
        if not names:
            return {}
        try:
            return default_store().resolve(user_key, names)
        except Exception:
            return {}

    return _resolve


def _solve_grounding_base(
    user_key: str, project_id: str, spec: dict | None, nodes_by_id: dict, targets: list
) -> dict:
    """dev/114: ONE grounding base per Solve batch, built in the request
    thread (workers hold no request context): catalog paths, the mission and
    plan texts (the human-authored intents), and the session-free verified
    map (empty — Solve has no candidates transcript of its own)."""
    dataflow = (spec or {}).get("dataflow") or {}
    texts = [str(dataflow.get("task") or ""), str(dataflow.get("name") or "")]
    for node_id in targets:
        node = nodes_by_id.get(node_id) or {}
        texts.append(str(node.get("goal") or ""))
    by_path, by_id = _catalog_grounding_refs(project_id)
    return {
        "catalog_paths": by_path,
        "catalog_ids": by_id,
        "texts": [t for t in texts if t.strip()],
        "verified": {},
        "secrets": _connection_key_refs(user_key),
    }


#: dev/114: the sixth runtime-supplied-inputs application (DEC-063) — the
#: rule a tool-less Dataset Finder child answers to. The row schema itself is
#: content.CANDIDATES_INSTRUCTION (#269): ONE schema, never a second copy.
_DISCOVERY_RULE = (
    "You are running as a delegate without tools. The `catalog` input IS the "
    "project's Data Catalog (catalog.search was run for you): catalog-lane rows "
    "must come ONLY from it, quoting each row's id as datasetId — any other id is "
    "dropped. External rows are suggestions the runtime will probe; do not claim "
    "verification. Reply with the datasetCandidates block described below and a "
    "one-line summary; nothing else."
)


def _extract_candidates_reply(child_text: str) -> dict | None:
    """dev/114: the child reply's ``datasetCandidates`` payload, or None —
    schema-only recognition (DEC-063): a JSON object, bare or inside ONE fence
    of any language tag (the #269 schema teaches a curio.v1 fence), whose
    ``datasetCandidates.lanes`` is a dict. Chat JSON never matches."""
    import json as _json
    import re as _re2

    if not isinstance(child_text, str) or not child_text.strip():
        return None
    candidates = [child_text.strip()]
    candidates += [m.group(1).strip() for m in _re2.finditer(
        r"```[A-Za-z0-9_.-]*[ \t]*\n(.*?)\n?```", child_text, _re2.DOTALL)]
    for candidate in candidates:
        try:
            payload = _json.loads(candidate)
        except ValueError:
            continue
        block = payload.get("datasetCandidates") if isinstance(payload, dict) else None
        if isinstance(block, dict) and isinstance(block.get("lanes"), dict):
            return block
    return None


def _mint_candidates_from_delegate(
    loop_ctx: dict, child_text: str, catalog_rows: list
) -> tuple[dict | None, str, str]:
    """dev/114: a successful ``dataset.discover`` delegation becomes the
    two-lane ``datasetCandidates`` part on the PARENT's turn — runtime-minted:
    catalog rows not in the runtime's own catalog listing are dropped (tool-
    grounded, never model-claimed), external rows get the DEC-053 verdict, and
    the run is marked so a same-turn node.create is refused (the user reviews
    first). Returns ``(part | None, text_for_model, outcome)``."""
    block = _extract_candidates_reply(child_text)
    if block is None:
        return None, (
            "the Dataset Finder returned no recognizable datasetCandidates block — "
            "report that honestly; do not invent candidates or a source"
        ), "no-candidates"
    known = {str(r.get("id")) for r in catalog_rows if isinstance(r, dict) and r.get("id")}
    lanes = block.get("lanes") or {}
    catalog_raw = lanes.get("catalog") if isinstance(lanes.get("catalog"), list) else []
    kept = [r for r in catalog_raw if isinstance(r, dict) and str(r.get("datasetId")) in known]
    dropped = len(catalog_raw) - len(kept)
    for row in kept:
        # Installed state is the LISTING's, never the child's claim.
        listed = next((r for r in catalog_rows if str(r.get("id")) == str(row.get("datasetId"))), None)
        if listed is not None:
            row["installed"] = bool(listed.get("installed"))
            row.setdefault("name", listed.get("name"))
            row.setdefault("sourceType", "catalog")
    parsed = content._parse_dataset_candidates({"lanes": {
        "external": lanes.get("external") if isinstance(lanes.get("external"), list) else [],
        "catalog": kept,
    }})
    if parsed is None:
        note = f" ({dropped} catalog row(s) dropped — not in the Data Catalog)" if dropped else ""
        return None, (
            "the Dataset Finder returned no usable candidates" + note +
            " — report that honestly; ask the user for a path or URL instead of guessing"
        ), "no-candidates"
    _verify_candidate_parts([parsed], loop_ctx)
    loop_ctx["_candidates_pending_review"] = True
    total = sum(len(v) for v in parsed["lanes"].values())
    note = f" {dropped} catalog row(s) were dropped (not in the Data Catalog)." if dropped else ""
    return parsed, (
        f"{total} dataset candidate(s) are shown to the user for review; external rows "
        "carry the runtime's verification verdict." + note +
        " Do NOT propose a node in this turn — ask the user to select and confirm; "
        "you will build from the confirmed source on the next turn."
    ), "ok"


def _dataset_discover_inputs(user_key: str, project_id: str, inputs: dict) -> dict:
    """dev/114: the sixth DEC-063 application — a tool-less Dataset Finder
    child gets the catalog listing and the reply schema as INPUTS."""
    enriched = dict(inputs)
    if "catalog" not in enriched:
        try:
            rows = tools._catalog_search_rows(user_key, project_id, {})
        except Exception:
            log.warning("Could not list the Data Catalog for a dataset.discover "
                        "delegate (project %s)", project_id, exc_info=True)
            rows = []
        enriched["catalog"] = {
            "note": (
                "The project's Data Catalog as catalog.search returned it"
                if rows else
                "The Data Catalog listing was empty or unavailable — the catalog lane "
                "must stay empty; say so."
            ),
            "rows": rows,
        }
    if "discoveryReplyContract" not in enriched:
        enriched["discoveryReplyContract"] = _DISCOVERY_RULE + "\n\n" + content.CANDIDATES_INSTRUCTION
    return enriched


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


#: dev/126: capabilities whose node-scoped work homes at the DELEGATE's own
#: node attachment rather than dev/72's Node Builder default — discovery
#: belongs in the chat of the agent that owns it, which is also where the user
#: selects a source. One declaration; every other capability keeps dev/72's
#: behavior byte-for-byte, and so does this one when that agent cannot live on
#: the node (its manifest's compatibleTargets decide).
_HOME_AGENT_BY_CAPABILITY: dict[str, str] = {
    "dataset.discover": "agent.dataset-finder",
    "dataset.select": "agent.dataset-finder",
}


def _delegation_home(
    spec: dict,
    coord: str,
    capability: str,
    inputs: dict,
    *,
    node_id: str | None = None,
    create: bool = True,
    user_key: str | None = None,
) -> tuple[dict | None, bool]:
    """Where a delegated task LIVES (memo dev/72): node-scoped work → the
    target node's Node Builder attachment (dev/71's; best-effort created);
    everything else → an existing attachment of the DELEGATE's agent id
    (canvas-scoped preferred), else a new canvas attachment of the resolved
    coord. Returns ``(record | None, created)`` — best-effort throughout: a
    missing home never fails a delegation. dev/126: a capability in
    ``_HOME_AGENT_BY_CAPABILITY`` homes at its own agent's node attachment."""
    target_node = node_id or (inputs or {}).get("nodeId")
    if isinstance(target_node, str) and target_node:
        home_agent = _HOME_AGENT_BY_CAPABILITY.get(capability)
        if home_agent:
            existing = _node_attachment_of(spec, home_agent, target_node)
            if existing is not None:
                return existing, False
            if create:
                node_type = next(
                    (
                        n.get("type") for n in (spec.get("dataflow") or {}).get("nodes") or []
                        if isinstance(n, dict) and n.get("id") == target_node
                    ),
                    None,
                )
                row = _attach_node_agent(
                    user_key, spec, home_agent, target_node, node_type
                )
                if row.get("attachmentId"):
                    return attachments.get_attachment(spec, row["attachmentId"]), True
            # That agent cannot live on this node — dev/72's default applies.
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
                spec, coord, capability, inputs, node_id=node_id, create=home_create,
                user_key=user_key,
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
    parent_loop_ctx: dict | None = None,
    validation: dict | None = None,
    grounding_base: dict | None = None,
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
    # dev/114: the mint's grounding gate reads the PARENT run's evidence
    # (current message, verified rows, probe cache, grants) — the home
    # session alone would not know what the user just typed.
    mint_ctx = {
        k: v for k, v in (parent_loop_ctx or {}).items()
        if k in ("message", "_verified_urls", "_egress_budget", "_probe_cache", "granted", "manifest")
    }
    mint_ctx.update({"attachment_id": home_att, "session_id": home_sess})
    if grounding_base is not None:
        # dev/115: a job thread holds no request context — the gate grounds
        # against the batch's precomputed catalog refs, not a live listing.
        mint_ctx["_grounding_base"] = grounding_base
    p_status, p_error, part = _mint_node_content_write(
        user_key, project_id,
        mint_ctx,
        {"tool": "node.content.write",
         "params": {"nodeId": node_id, "content": text_out}},
    )
    if part is None:
        return None, home_att, (
            "the generated content could not become a reviewed proposal "
            f"({(p_error or 'unknown error')[:200]}) — report this honestly: "
            "nothing was changed and nothing awaits review"
        )
    if validation:
        # dev/115: an EXECUTED review carries its verdict and attempt trail —
        # stamped before the turn is written so the persisted part has it.
        part["validation"] = dict(validation)
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
    # memo dev/94: the SECOND legal reply. "Reuse first" was previously a rule
    # with no reachable outcome on this path — the delegate had no shape in
    # which to say "one of these already does it", so the only reply the
    # runtime recognised was a draft, and authoring was the only way to answer
    # at all. Teaching the shape is the A8 lesson again: nobody emits a
    # protocol they were never shown.
    "insteadOfAuthoring": (
        "When one of inputs.existingPackages already satisfies the need, "
        "author NOTHING and reply with ONE JSON object of exactly this shape "
        "instead of a draft: {\"reuseExisting\": {\"dirName\": \"<its "
        "dirName>\", \"reason\": \"<one line: what it already does>\"}}. That "
        "is a complete, successful answer — the caller acts on it (enlisting "
        "the package if it is not yet in the project). Prefer extending an "
        "existing package (mode 'extend') over creating a near-duplicate."
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
        "import declared python dependencies INSIDE the handler function "
        "(lazily), never at module level — they install at Apply into the "
        "package's isolated overlay and do not exist when the build's probe "
        "loads the entry (a module-level import of a declared dependency "
        "fails the probe by construction)",
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


def _extract_reuse_finding(child_text: str) -> dict | None:
    """The child's "one of these already does it" answer, or None (dev/94).

    Deterministic and schema-keyed, never a heuristic over prose: the contract
    teaches exactly ``{"reuseExisting": {"dirName": …, "reason": …}}``, and
    only that shape counts. Guessing at intent from free text would put model
    wording in charge of control flow, which is precisely the mistake the
    typed-tail protocol exists to avoid.
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
        finding = payload.get("reuseExisting")
        if not isinstance(finding, dict):
            continue
        dir_name = finding.get("dirName")
        if isinstance(dir_name, str) and dir_name.strip():
            reason = finding.get("reason")
            return {
                "dirName": dir_name.strip()[:120],
                "reason": reason.strip()[:300] if isinstance(reason, str) else "",
            }
    return None


def _reuse_finding_text(user_key: str, project_id: str, finding: dict) -> str:
    """What the parent is told when the delegate declines to author.

    Names the package and, load-bearing for the parent's next move, whether
    this project has it: an enlisted package can be used straight away, a
    store-only one needs the reviewed ``package.install`` first (dev/93 D4's
    middle rung). Unknown enlistment state simply omits the hint.
    """
    dir_name = finding["dirName"]
    reason = f" — {finding['reason']}" if finding.get("reason") else ""
    hint = ""
    try:
        from utk_curio.backend.app.packages import services as packages_services

        enlisted = dir_name in packages_services.get_project_lockfile(user_key, project_id)
        hint = (
            " It is already in this project: use it directly."
            if enlisted else
            " It is installed but NOT in this project: propose package.install "
            f"for {dir_name} first, then use its template."
        )
    except Exception:  # noqa: BLE001 — an unknown lockfile just omits the hint
        pass
    return (
        f"the authoring delegate reports that {dir_name} already does this{reason}. "
        f"Nothing was authored, which is the correct outcome.{hint} Do NOT ask for "
        "a new package that duplicates it."
    )


#: dev/95 (Follow-up D): the server-owned reply schema for a delegated
#: ``research.notes.compose`` — taught via inputs (the A8 posture: the child
#: answers to a schema it can SEE, never a shape it must invent) and
#: recognized ONLY by this schema at the mint (DEC-063: never by reading
#: intent out of prose).
_NOTES_REPLY_CONTRACT: dict = {
    "reply": (
        "Reply with ONE JSON object of exactly this shape (optionally inside "
        "a ```json fence), nothing after it."
    ),
    "shape": {
        "answer": "<the prose answer to the question — always present>",
        "nodeType": ("<one 'id' from inputs.notesTemplates — omit when that "
                     "list is empty>"),
        "notes": [{
            "title": "<short note title>",
            "content": "<the finding as clean markdown — bold fact labels, "
                       "'- ' bullets, [source](https://...) links>",
            "color": "yellow|pink|blue|green|orange|lavender|#rrggbb",
        }],
    },
    "rules": [
        "compose findings ONLY from inputs.searchResults — when it carries "
        "an 'error', say in 'answer' that search was unavailable and reply "
        "with an empty notes list; NEVER invent findings from memory",
        "the reference row (dev/90 A13): the FIRST note carries the user's "
        "question verbatim (title 'Question', color yellow); then one green "
        "note per answer with a subject title and every web-gathered fact "
        "linked to its source",
        "an empty notes list is valid when nothing should be placed "
        "(no template installed, or no findings)",
    ],
}

#: Bounds on the runtime-gathered search rows injected into a delegation —
#: the child's context is finite; five sourced rows beat fifty raw ones.
_DELEGATED_SEARCH_MAX_ROWS = 5
_DELEGATED_SEARCH_FIELD_CHARS = 300


def _delegated_search_results(question: object) -> dict:
    """dev/95: ONE egress-policed search, executed by the RUNTIME for a
    tool-less ``research.notes.compose`` child (the dev/67-4 posture —
    exactly how ``research.verify`` children get runtime-run validator
    evidence). Failures ride in as their honest error text: the child must
    SAY search was unavailable, never invent findings."""
    if not isinstance(question, str) or not question.strip():
        return {"error": "no 'question' input was supplied to the delegation"}
    from utk_curio.backend.app.agents import tools as agent_tools

    status, text = agent_tools._execute_web_search({"q": question.strip()})
    if status != "ok":
        return {"error": text}
    import json as _json

    try:
        rows = _json.loads(text).get("results") or []
    except (ValueError, AttributeError):
        return {"error": "the search provider returned malformed JSON"}
    bounded = []
    for row in rows[:_DELEGATED_SEARCH_MAX_ROWS]:
        if not isinstance(row, dict):
            continue
        bounded.append({
            key: str(row.get(key) or "")[:_DELEGATED_SEARCH_FIELD_CHARS]
            for key in ("title", "url", "snippet")
        })
    return {"query": question.strip(), "results": bounded}


def _extract_notes_reply(child_text: str) -> dict | None:
    """The child reply's ``notesReplyContract`` payload, or None.

    Schema-only recognition (DEC-063): a JSON object — bare, or inside one
    ```/```json fence — whose ``notes`` key is a LIST counts; nothing else
    does. Answer-only replies still carry ``"notes": []`` per the contract,
    so arbitrary chat JSON never matches by accident."""
    import json as _json
    import re as _re2

    if not isinstance(child_text, str) or not child_text.strip():
        return None
    candidates = [child_text.strip()]
    candidates += [m.group(1).strip() for m in _re2.finditer(
        r"```(?:json)?[ \t]*\n(.*?)\n?```", child_text, _re2.DOTALL)]
    for candidate in candidates:
        try:
            payload = _json.loads(candidate)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("notes"), list):
            return payload
    return None


#: dev/95: the A13 defaults the runtime fills when a reply row omits its
#: color — question note yellow, answer notes green (user/model-chosen colors
#: always win; defaults only fill absences).
_NOTES_DEFAULT_COLORS = ("yellow", "green")

#: dev/105 A2: a node header is a short line — bounded like the goal.
_NODE_TITLE_MAX_CHARS = 120


def _notes_agent_run(loop_ctx: dict) -> bool:
    """True when the run's manifest declares ``research.notes.compose`` — the
    ONE capability whose node.create defaults follow the A13 row (dev/105
    A2). Keyed on the capability, never the agent id."""
    manifest = loop_ctx.get("manifest")
    return "research.notes.compose" in (getattr(manifest, "capability_ids", None) or [])


def _mint_notes_from_delegate(
    user_key: str, project_id: str, loop_ctx: dict, child_text: str,
) -> tuple[list, str, str]:
    """dev/95 (Follow-up D): the one-mint-policy extended to note sequences.

    A successful ``research.notes.compose`` delegation whose bounded child
    reply matches the notes schema becomes reviewed ``node.create``
    proposals minted by the RUNTIME at the parent's attachment — one per
    note, a same-run A16 jointly-pending sequence (apply in any order), each
    row re-validated through ``_mint_node_create`` (the ONE creation lane:
    dev/93 template vocabulary, A12 content bounds, dev/89 appearance
    normalization). Gated on the PARENT's ``node.create`` grant (the
    ``_mint_package_draft_from_delegate`` posture). Degradations land as
    text with the way out named: no grant, no/invalid template (→ the
    Researcher's own attachment owns the enlist/author ladder — depth-1
    keeps it out of reach here), every row refused.

    Returns ``(proposal_parts, text_for_model, outcome)`` — outcome "ok"
    when the delegation produced its answer (notes minted, legitimately
    empty, or honestly skipped for a missing template), "failed" when the
    reply broke the contract or notes existed but nothing could mint.
    """
    payload = _extract_notes_reply(child_text)
    if payload is None:
        return [], (
            "the delegate's reply did not match the notes reply contract "
            "(ONE JSON object with 'answer' and a 'notes' list) — nothing "
            "was placed; the reply was kept as text"
        ), "failed"
    answer = payload.get("answer")
    answer = answer.strip() if isinstance(answer, str) else ""
    rows = _notes_from_delegate_inputs({"notes": payload.get("notes")}) or []
    if not rows:
        # Empty notes is a VALID reply (no findings / no template offered) —
        # the answer is the product (dev/93 D5: this run produced it).
        return [], (answer or "the delegate returned no answer and no notes"), "ok"
    if "node.create" not in (loop_ctx.get("granted") or []):
        return [], (
            (f"{answer}\n\n" if answer else "")
            + "the delegate composed notes but this agent is not granted "
              "node.create — the notes were kept as text only"
        ), "failed"
    node_type = payload.get("nodeType")
    entry = err = None
    if isinstance(node_type, str) and node_type.strip():
        entry, err = _available_template(user_key, project_id, node_type.strip())
    if entry is None:
        reason = (
            f"the chosen notes template was not available ({err})"
            if err else "no installed notes template was available"
        )
        return [], (
            (f"{answer}\n\n" if answer else "")
            + f"notes skipped: {reason} — ask the Researcher (attached to a "
              "node or the canvas) to enlist or author a notes package; its "
              "own runs hold the reuse ladder a delegate cannot reach"
        ), "ok"
    parts: list = []
    last_refusal = ""
    for index, row in enumerate(rows):
        appearance = row.get("appearance") or {
            "backgroundColor": _NOTES_DEFAULT_COLORS[min(index, 1)]}
        req = {"params": {
            "nodeType": entry["id"],
            "content": row["content"],
            # dev/105 A2: the row's title is the note's HEADER (what the
            # behavior renders), not its purpose line.
            **({"title": row["title"]} if row.get("title") else {}),
            "appearance": appearance,
        }}
        status, text, part = _mint_node_create(user_key, project_id, loop_ctx, req)
        if status == "proposed" and part is not None:
            parts.append(part)
        else:
            last_refusal = text
    if not parts:
        return [], (
            (f"{answer}\n\n" if answer else "")
            + f"no notes could be proposed: {last_refusal}"
        ), "failed"
    summary = (
        (f"{answer}\n\n" if answer else "")
        + f"{len(parts)} reviewed note proposal(s) created"
        + (f" ({last_refusal})" if last_refusal else "")
        + " — they await the user's explicit Apply; do NOT claim the notes exist"
    )
    return parts, summary, "ok"


def _extract_draft_params(child_text: str) -> dict | None:
    """The child reply's build-request payload, or None.

    Thin wrapper over :func:`_extract_draft_params_verbose` — see there for
    the accepted shapes and for why the failure reason matters.
    """
    params, _ = _extract_draft_params_verbose(child_text)
    return params


def _extract_draft_params_verbose(child_text: str) -> tuple[dict | None, str]:
    """The child reply's build-request payload, or ``(None, why_not)``.

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

    The REASON is the point (memo dev/93 D5). Returning a bare ``None`` made
    this a dead end for the parent: the runtime discarded the reply and said
    "refine the delegation inputs and try again" with no parse error, no
    offending fragment, and no line number — so the parent's "refinement" was
    to re-delegate under a DIFFERENT package id, which is how one weather
    question produced two near-identical note packages in a single run. A
    correction round needs something to correct against; the shape here
    mirrors ``_parse_dataflow_plan_verbose``, which plans have had since
    dev/54.
    """
    import json as _json
    import re as _re2

    if not isinstance(child_text, str) or not child_text.strip():
        return None, "the delegate replied with no text at all"
    candidates: list[str] = []
    stripped = child_text.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)
    for match in _re2.finditer(
            r"```(?:json|curio\.v1)?\s*\n(.*?)```", child_text, _re2.DOTALL):
        candidates.append(match.group(1).strip())
    if not candidates:
        return None, (
            "no JSON build request found in the reply: it must be ONE JSON "
            "object, either the whole reply or a single ```json fenced block. "
            "Prose describing the package is not a build request"
        )
    decode_errors: list[str] = []
    shape_errors: list[str] = []
    for candidate in candidates:
        try:
            payload = _json.loads(candidate)
        except (ValueError, TypeError) as exc:
            decode_errors.append(str(exc))
            continue
        if not isinstance(payload, dict):
            shape_errors.append(f"the JSON is a {type(payload).__name__}, not an object")
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
            return inner, ""
        keys = ", ".join(sorted(k for k in inner if isinstance(k, str))[:12]) or "none"
        shape_errors.append(
            "the JSON parsed but is not a build request — it must carry "
            f"\"mode\" ('create' or 'extend') and a \"manifest\" object (top-level "
            f"keys were: {keys})"
        )
    if decode_errors and not shape_errors:
        # The overwhelmingly common weak-model failure: a long body containing
        # an embedded source file, cut off mid-string. Say so explicitly —
        # "invalid JSON" alone does not tell the model what to do differently.
        return None, (
            f"the JSON did not parse ({decode_errors[0]}). If the reply was cut "
            "off mid-object, re-emit the COMPLETE build request and keep the "
            "file bodies short enough to finish"
        )
    return None, (shape_errors or decode_errors)[0]


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


# How many extra attempts a delegated draft gets, mirroring the node-content
# path's ``_VALIDATE_CORRECTION_ROUNDS``. Plans have had correction rounds
# since dev/54 and generated node content since dev/67; the delegated package
# draft was the ONE mutation lane with none, and a weak local model emitting a
# long JSON body containing an embedded source file gets it slightly wrong as
# the NORMAL case, not the exception (memo dev/93 D5).
_DRAFT_CORRECTION_ROUNDS = 2


def _mint_package_draft_from_delegate(
    user_key: str, project_id: str, loop_ctx: dict, child_text: str,
    delegate_inputs: dict | None = None,
    redelegate=None,
) -> tuple[dict | None, str, str]:
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

    dev/93 D5 adds the CORRECTION ROUNDS every other mutation lane already
    had. ``redelegate(inputs) -> (status, text)`` re-runs the SAME delegate
    with ``previousAttempt`` + ``validationError`` appended to its inputs, so
    the model that made the mistake is the one that fixes it, against the real
    error. The package id from the first parseable draft is PINNED across
    rounds: a delegate that renames its package mid-correction is failing the
    correction, not authoring a new package — renaming is exactly what
    happened when the parent had no error to act on (curio.notes, then
    curio.postits, in one run).

    Returns ``(proposal_part | None, text_for_model, outcome)`` where outcome
    is ``"ok"`` only when a proposal was minted. The caller passes that to the
    delegation part instead of the child RUN's status, so a card can never
    read "Delegated task · ok" beside a summary saying nothing was produced.
    """
    if "package.draft.apply" not in (loop_ctx.get("granted") or []):
        return None, (
            "the delegate produced a package draft but this agent is not "
            "granted package.draft.apply — the draft was kept as text only"
        ), "failed"

    notes = _notes_from_delegate_inputs(delegate_inputs or {})
    pinned_package_id: str | None = None
    attempt_text = child_text
    last_error = ""
    rounds = 1 + (_DRAFT_CORRECTION_ROUNDS if redelegate is not None else 0)

    for round_index in range(rounds):
        # dev/94: "one of these already does it" is a COMPLETE answer, checked
        # before the draft parse — the doctrine is reuse-first, so a reply that
        # names a reuse target is deliberately declining to author and must not
        # be read as a failed draft. It spends NO correction rounds (nothing
        # failed) and reports "ok": dev/93 D5's rule is that a run producing
        # NOTHING must not claim success, and this run produced the answer.
        finding = _extract_reuse_finding(attempt_text)
        if finding is not None:
            return None, _reuse_finding_text(user_key, project_id, finding), "ok"
        params, parse_error = _extract_draft_params_verbose(attempt_text)
        if params is not None:
            draft_id = (params.get("manifest") or {}).get("id")
            if pinned_package_id is None and isinstance(draft_id, str):
                pinned_package_id = draft_id
            if (pinned_package_id is not None and isinstance(draft_id, str)
                    and draft_id != pinned_package_id):
                parse_error = (
                    f"this correction changed the package id from "
                    f"{pinned_package_id!r} to {draft_id!r}. Fix the SAME "
                    "package — a rename does not resolve the error, it just "
                    "creates a duplicate package"
                )
                params = None
        if params is not None:
            # dev/90 A12: the parent's findings override the draft's nodes —
            # the reference contract is "the agent's answer IS the note", and
            # the live failures were child-invented filler / empty notes.
            reconciled = _reconcile_draft_notes(params, notes) if notes else False
            status, text, part = _mint_package_draft_apply(
                user_key, project_id, loop_ctx, {"params": params}
            )
            if status == "proposed":
                if reconciled:
                    text += (
                        f" (the draft's {len(notes)} note(s) carry the caller's "
                        "findings verbatim — runtime-reconciled from the "
                        "delegation inputs)"
                    )
                if round_index:
                    text += f" (after {round_index} correction round(s))"
                return part, text, "ok"
            # The build service refused. Some refusals cannot improve by
            # re-authoring (a policy or permission verdict); retrying those
            # would burn the parent's rounds to reach the same answer.
            last_error = text
            if not _draft_refusal_is_correctable(text):
                return None, text, "failed"
        else:
            last_error = parse_error

        if redelegate is None or round_index == rounds - 1:
            break
        status, attempt_text = redelegate({
            "previousAttempt": (attempt_text or "")[:6000],
            "validationError": last_error[:2000],
        })
        if status != "ok":
            return None, (
                "the authoring delegate could not be re-run to correct its "
                f"draft ({attempt_text or 'no reply'}); the last error was: "
                f"{last_error}"
            ), "failed"

    spent = f" after {rounds} attempt(s)" if rounds > 1 else ""
    return None, (
        f"the authoring delegate produced no usable package draft{spent}. The "
        f"last error was: {last_error} — fix THAT and keep the same package id, "
        "or tell the user plainly that authoring failed. Do NOT re-delegate "
        "under a different package name, and if a package that already does "
        "this job is listed as installed, use it instead of authoring one"
    ), "failed"


def _draft_corrector(
    user_key: str, project_id: str, loop_ctx: dict, req: dict, resolution,
    config, execution_id: str, delegations: list,
):
    """A ``redelegate(extra_inputs) -> (status, text)`` for the draft loop.

    Re-runs the SAME delegate, at the same coordinate and capability, with the
    original inputs plus ``previousAttempt``/``validationError`` — the shape
    the node-content path has used since dev/67, so a delegate that already
    understands self-correction there needs no new teaching here. Every
    attempt is traced: its execution record joins ``delegations`` exactly like
    the first, so the rounds are visible in the transcript rather than being
    an invisible retry.
    """
    def _redelegate(extra: dict) -> tuple[str, str]:
        inputs = dict(req.get("inputs") or {})
        inputs.update(extra)
        status, text, child, _home = _run_delegate_traced(
            user_key,
            project_id,
            resolution.coord,
            req["capability"],
            _enriched_delegate_inputs(
                user_key, project_id, loop_ctx, req["capability"], inputs,
            ),
            config,
            parent_execution_id=execution_id,
            parent_coord=loop_ctx["coord"],
            attachment_id=loop_ctx.get("attachment_id"),
            parent_name=getattr(loop_ctx.get("manifest"), "name", None),
        )
        delegations.append(child)
        return status, text

    return _redelegate


def _draft_refusal_is_correctable(refusal: str) -> bool:
    """Whether re-authoring could plausibly fix a build-service refusal.

    A malformed manifest, a bad file, a failed probe: the model can fix those.
    A permission or policy verdict is the build service's answer, not a typo —
    re-running the delegate would spend the parent's rounds arriving at the
    same refusal (memo dev/93 edge cases 31/37).
    """
    text = (refusal or "").lower()
    terminal = (
        "policy blocked", "permission", "not granted", "conflict",
        "is built-in", "already installed",
    )
    return not any(marker in text for marker in terminal)


# Bounds for the authoring delegate's reuse evidence (memo dev/94). The payload
# has to bound ITSELF: delegation._frame_inputs applies no size limit to the
# inputs body (only the child's REPLY is capped), so an account with a large
# package store would otherwise crowd the child's context.
_REUSE_EVIDENCE_MAX_PACKAGES = 40
_REUSE_EVIDENCE_MAX_TEMPLATES = 8
_REUSE_EVIDENCE_DESC_CHARS = 200


def _authoring_reuse_evidence(user_key: str, project_id: str) -> dict | None:
    """What already exists, for a TOOL-LESS authoring delegate (memo dev/94).

    The Package Builder's instruction opens with "Reuse first. Before authoring
    anything, read packages.catalog … never a duplicate package" — and it holds
    that tool only as a direct attachment. As a DEC-046 delegate it runs
    structurally tool-less, which is the path packages are actually authored
    on, so its first instruction was unexecutable and it had no way to know:
    one weather question produced two near-identical note packages while a
    usable one sat in the user's store. The runtime therefore serves the
    evidence the instruction depends on, exactly as it already serves the
    build-request contract (dev/90 A8) and verification results (dev/67-4).

    ``installedInProject`` is CARRIED, not filtered on: both answers are
    actionable and they differ — an enlisted package means "extend or reuse
    it", an installed-but-not-enlisted one means "report it, the parent can
    enlist it" (dev/93 D4's middle rung). Collapsing them would recreate the
    one-bucket mistake that caused this.

    Returns None when there is nothing to report (or the registry is
    unreadable) — honest absence, and the delegation proceeds either way.
    """
    from utk_curio.backend.app.packages import services as packages_services

    try:
        # ONE snapshot for the whole payload (memo dev/99 R2). This used to
        # call three public readers, each of which independently resolved the
        # project lockfile and walked the package store — three spec reads and
        # three traversals to build one piece of evidence. The composite also
        # makes the payload coherent once the seed lock reaches readers: every
        # part of it then describes the same instant, instead of three
        # individually-consistent reads that can straddle a seeding pass.
        landscape = packages_services.template_landscape(user_key, project_id)
        rows = landscape["catalog"]
        # Template ids make ``mode: "extend"`` followable rather than a guess.
        # Both listings are canonical and unversioned; keyed by packageId so a
        # row can name what it would be extending.
        by_package: dict[str, list[str]] = {}
        for entry in landscape["available"] + landscape["notEnlisted"]:
            package_id = str(entry["id"]).split("/", 1)[0]
            ids = by_package.setdefault(package_id, [])
            if entry["id"] not in ids:
                ids.append(entry["id"])
    except Exception:  # a broken registry degrades to no evidence, never a 500
        log.warning(
            "Could not compose reuse evidence for project %s — the authoring "
            "delegate will run without it", project_id, exc_info=True,
        )
        return None

    packages: list[dict] = []
    for row in rows[:_REUSE_EVIDENCE_MAX_PACKAGES]:
        item = {
            "dirName": row["dirName"],
            "name": row["name"],
            "description": (row.get("description") or "")[:_REUSE_EVIDENCE_DESC_CHARS],
            "installedInProject": bool(row.get("installed")),
        }
        templates = by_package.get(row["packageId"]) or []
        if templates:
            item["templates"] = templates[:_REUSE_EVIDENCE_MAX_TEMPLATES]
        packages.append(item)
    if len(rows) > len(packages):
        log.warning(
            "Reuse evidence truncated for project %s: %d of %d packages listed",
            project_id, len(packages), len(rows),
        )
    if not packages:
        return None
    return {
        "note": (
            "Packages that already exist for this user. If one of these already "
            "satisfies the requested need, say so and author nothing — name its "
            "dirName so the caller can use it (installedInProject false means the "
            "caller must enlist it first). Extend one by name instead of creating "
            "a near-duplicate."
        ),
        "packages": packages,
    }


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
    if capability in PACKAGE_AUTHORING_CAPABILITIES:
        # dev/90 A8: tool-less authoring delegates get the build-request
        # contract server-side — the child answers to a schema it can SEE,
        # never a shape it has to invent (the model's own keys always win).
        if "buildRequestContract" not in inputs:
            inputs = {**inputs, "buildRequestContract": _BUILD_REQUEST_CONTRACT}
        # dev/94: and the reuse evidence its instruction's first line depends
        # on — "read packages.catalog before authoring" names a tool a
        # delegate does not have.
        if "existingPackages" not in inputs:
            evidence = _authoring_reuse_evidence(user_key, project_id)
            if evidence:
                inputs = {**inputs, "existingPackages": evidence}
        return inputs
    if capability == "research.notes.compose":
        # dev/95 (Follow-up D) — the FIFTH runtime-supplied-inputs application
        # (dev/67-4 verification, dev/67-6 nodeContext, A8 contract, dev/94
        # existingPackages): a DEC-046 child holds no web tools and cannot
        # browse the roster, so the runtime gathers the ONE policed search,
        # offers the installed presentation templates as candidates, and
        # teaches the reply schema. Model-supplied keys always win.
        enriched = dict(inputs)
        if "searchResults" not in enriched:
            enriched["searchResults"] = _delegated_search_results(
                enriched.get("question"))
        if "notesTemplates" not in enriched:
            from utk_curio.backend.app.packages import services as packages_services

            enriched["notesTemplates"] = packages_services.presentation_templates(
                user_key, project_id)
        if "notesReplyContract" not in enriched:
            enriched["notesReplyContract"] = _NOTES_REPLY_CONTRACT
        return enriched
    if capability == "dataset.discover":
        # dev/114 — the SIXTH runtime-supplied-inputs application (DEC-063):
        # a tool-less Dataset Finder child cannot run catalog.search, so the
        # runtime lists the catalog for it and teaches the ONE reply schema
        # (#269's). Model-supplied keys always win.
        return _dataset_discover_inputs(user_key, project_id, inputs)
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
    enriched = {**inputs, "nodeContext": composed}
    # dev/114 — the SEVENTH application: a data-loading node's content child
    # is HANDED its grounded sources (catalog paths, the user's paths, the
    # URLs already verified) instead of guessing a filename.
    from utk_curio.backend.app.packages import services as packages_services

    node_type = composed.get("nodeType")
    if "sourceGrounding" not in enriched and source_grounding.is_data_loading_type(
        packages_services.canonical_template_id(node_type)
    ):
        enriched["sourceGrounding"] = _source_grounding_inputs(
            _grounding_context(user_key, project_id, loop_ctx, node_type=node_type,
                               extra_texts=(str(inputs.get("intent") or ""),))
        )
    return enriched


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
        # DEC-080 (dev/126): a REQUIRED delegate that is missing is a closure
        # the user already consented to — repaired once, here, instead of
        # stalling the conversation on an install proposal for it. A merely
        # PREFERRED delegate keeps the reviewed install lane below
        # (`REQ-ORCH-001`), unchanged.
        dependency_id = (resolution.coord or "").split("@", 1)[0]
        required_ids = {
            c.split("@", 1)[0]
            for c in delegation.required_closure(user_key, manifest)[0]
        }
        if dependency_id in required_ids and _repair_required_closure(
            user_key, project_id, loop_ctx.get("coord") or "",
            attachment_id=loop_ctx.get("attachment_id"),
        ):
            retried = delegation.resolve(user_key, project_id, manifest, capability)
            if retried.outcome == "ok":
                return "ok", "", retried
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
    # dev/114: the current user text — turns persist AFTER the run, so the
    # grounding gate cannot read it from the session; a path the user typed
    # is the one human-trusted source of a local path.
    loop_ctx["message"] = message
    execution_id = uuid.uuid4().hex
    # Atomic admission (dev/40): after validation (an invalid request never
    # consumes quota), before provider dispatch (a denied run never reaches a
    # provider). The reservation IS this execution (one id), and the price
    # snapshot pinned here is what settlement charges.
    reservation = ledger.reserve(
        user_key,
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
    refusals_used = 0  # dev/105 D2: free parameter corrections taken
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
            _verify_candidate_parts(parts, loop_ctx)  # dev/67-4: no unverified laundering
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
                if kind == "none":
                    # #245: only once the plan handler has declined — a
                    # toolRequest the parser could not take (wrong fence,
                    # trailing prose, correctable params) must never fold into
                    # the chat as raw JSON.
                    kind, payload, visible_override, req = _handle_tool_reply(
                        loop_ctx, reply, parts, rounds_used
                    )
                    if kind == "correct":
                        rounds_used += 1
                        messages_work.append({"role": "assistant", "content": reply})
                        messages_work.append(
                            _tool_correction_message(payload)
                        )
                        continue
                if req is None:
                    effective_visible = (
                        visible_override if visible_override is not None else visible
                    )
                    if effective_visible:
                        folded.append(effective_visible)
                    final_parts = payload
                    break
                # A RECOVERED request falls through to the shared request path
                # below, so grant re-check, mint, cap card and the dev/105 D2
                # free-refusal accounting all apply to it unchanged.
                visible = visible_override if visible_override is not None else visible
            if visible:
                folded.append(visible)
            if rounds_used >= MAX_TOOL_ROUNDS:
                # dev/73: a mutate request cut off at the cap is a visible
                # outcome — never a silent drop under confident prose.
                if req["type"] == "toolRequest" and req.get("tool") in MUTATE_PROPOSAL_TOOLS:
                    minted.append(_round_cap_cutoff_card(req["tool"]))
                break  # dangling read request at the cap: dropped, text kept
            if req["type"] == "delegateRequest":
                rounds_used += 1
                final = rounds_used >= MAX_TOOL_ROUNDS
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
                            parent_loop_ctx=loop_ctx,
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
                        draft_part, text, draft_outcome = _mint_package_draft_from_delegate(
                            user_key, project_id, loop_ctx, text,
                            delegate_inputs=req.get("inputs") or {},
                            redelegate=_draft_corrector(
                                user_key, project_id, loop_ctx, req, resolution,
                                config, execution_id, delegations,
                            ),
                        )
                        delegate_summary = text
                        if draft_part is not None:
                            minted.append(draft_part)
                            delegate_summary = (
                                "reviewed package draft proposed — awaits Apply"
                            )
                        # dev/93 D5: the delegation card reports the OUTCOME,
                        # not merely that the child ran — "ok" beside "returned
                        # no parseable draft" is how the parent learned nothing.
                        status = draft_outcome
                    elif status == "ok" and req["capability"] == "dataset.discover":
                        # dev/114: discovery success ⇒ the two-lane candidates part
                        # EXISTS on this turn — runtime-minted (catalog rows tool-
                        # grounded, external rows probed), never the model's claim.
                        cand_part, text, cand_outcome = _mint_candidates_from_delegate(
                            loop_ctx, text,
                            ((req.get("inputs") or {}).get("catalog") or {}).get("rows")
                            or _dataset_discover_inputs(user_key, project_id, {})["catalog"]["rows"],
                        )
                        delegate_summary = text
                        if cand_part is not None:
                            minted.append(cand_part)
                            delegate_summary = "dataset candidates shown for review — select and confirm"
                        status = cand_outcome
                    elif status == "ok" and req["capability"] == "research.notes.compose":
                        # dev/95 (Follow-up D): notes success ⇒ the reviewed
                        # A16 sequence EXISTS — runtime-minted from the
                        # child's schema reply, never the model's second step.
                        note_parts, text, notes_outcome = _mint_notes_from_delegate(
                            user_key, project_id, loop_ctx, text,
                        )
                        delegate_summary = text
                        if note_parts:
                            minted.extend(note_parts)
                            delegate_summary = (
                                f"{len(note_parts)} reviewed note proposal(s) "
                                "— await Apply"
                            )
                        status = notes_outcome
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
            if isinstance(text, ParamRefusal) and refusals_used < MAX_REFUSED_ROUNDS:
                refusals_used += 1  # dev/105 D2: a free correction, not a round
            else:
                rounds_used += 1
            final = rounds_used >= MAX_TOOL_ROUNDS
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
                     delegations=delegations,
            ),
        )
        raise AgentServiceError(f"agent run failed: {exc}", 502) from exc
    reply_text = "\n\n".join(folded)
    run_parts = minted + final_parts  # proposals ride the turn (dev/41)
    settled = ledger.settle(user_key, reservation, usage=usage_total or None, status="ok")
    execution = _execution_record(
        execution_id, pins, usage_total, started, "ok", tool_calls,
                     delegations=delegations,
        refused_rounds=refusals_used,
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
    # dev/114: the current user text — turns persist AFTER the run, so the
    # grounding gate cannot read it from the session; a path the user typed
    # is the one human-trusted source of a local path.
    loop_ctx["message"] = message
    execution_id = uuid.uuid4().hex
    # Eager atomic admission (dev/40): a quota/budget denial surfaces as a
    # plain 429 before any streaming begins, and consumes/persists nothing.
    reservation = ledger.reserve(
        user_key,
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
        messages_work: list, usage_sink: dict, result: dict,
        hold_plan_tail: bool = False, hold_request_tail: bool = False,
    ):
        """Stream one provider round: yields ("delta", text) with the dev/39
        tail withholding, then leaves {reply, visible, parts} in *result*.
        ``hold_plan_tail`` (dev/54): an INVALID tail that looks like a plan
        attempt is held (``result["heldPlanTail"]``) instead of flushed — the
        correction round must not leak raw plan JSON to the user; the caller
        releases it at the round cap (fail-open transparency).
        ``hold_request_tail`` (#245): the same for a mutate toolRequest tail —
        held in ``result["heldToolTail"]`` and, unlike the plan tail, never
        released: the params are a whole source file, and streaming them as
        chat prose IS the bug (see ``_handle_tool_reply``)."""
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
        _verify_candidate_parts(parts, loop_ctx)  # dev/67-4: no unverified laundering
        if withheld is not None and not parts:
            if hold_plan_tail and (
                '"dataflowPlan"' in withheld or '"dataflow.plan.write"' in withheld
            ):
                # A failed plan attempt (dev/54): held for the correction
                # round instead of leaking raw JSON into the chat.
                result["heldPlanTail"] = withheld
            elif hold_request_tail and '"toolRequest"' in withheld and any(
                f'"{tool}"' in withheld for tool in MUTATE_PROPOSAL_TOOLS
            ):
                # #245: a failed mutate request. The old code fell to the
                # fail-open branch below and streamed the whole node source
                # into the transcript as it arrived.
                result["heldToolTail"] = withheld
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
        refusals_used = 0  # dev/105 D2: free parameter corrections taken
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
                    hold_request_tail=bool(
                        set(loop_ctx.get("granted") or []) & MUTATE_PROPOSAL_TOOLS
                    ),
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
                    if kind == "none":
                        # #245: the toolRequest twin, after the plan handler.
                        kind, payload, visible_override, req = _handle_tool_reply(
                            loop_ctx, result["reply"], parts, rounds_used
                        )
                        if kind == "correct":
                            rounds_used += 1
                            yield (
                                "tool_revision",
                                {"attempt": rounds_used, "errors": len(payload)},
                            )
                            messages_work.append(
                                {"role": "assistant", "content": result["reply"]}
                            )
                            messages_work.append(
                                _tool_correction_message(payload)
                            )
                            continue
                        # A held request tail is NOT released at the cap: see
                        # _handle_tool_reply — a source file is not a spec.
                    if kind == "cap" and result.get("heldPlanTail"):
                        # Fail-open transparency at the cap: the held tail is
                        # the model's text — released, then explained by the
                        # error card in `payload`.
                        yield ("delta", result["heldPlanTail"])
                    if req is not None:
                        # A RECOVERED request: fall through to the shared
                        # request path with the block stripped from the text.
                        if visible_override is not None:
                            result["visible"] = visible_override
                    else:
                        effective_visible = (
                            visible_override if visible_override is not None
                            else result["visible"]
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
                if req["type"] == "delegateRequest":
                    rounds_used += 1
                    final = rounds_used >= MAX_TOOL_ROUNDS
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
                                parent_loop_ctx=loop_ctx,
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
                            draft_part, text, draft_outcome = _mint_package_draft_from_delegate(
                                user_key, project_id, loop_ctx, text,
                                delegate_inputs=req.get("inputs") or {},
                                redelegate=_draft_corrector(
                                    user_key, project_id, loop_ctx, req, resolution,
                                    config, execution_id, delegations,
                                ),
                            )
                            delegate_summary = text
                            if draft_part is not None:
                                minted.append(draft_part)
                                delegate_summary = (
                                    "reviewed package draft proposed — awaits Apply"
                                )
                            # dev/93 D5: the card reports the OUTCOME (see the
                            # non-streaming path).
                            status = draft_outcome
                        elif status == "ok" and req["capability"] == "dataset.discover":
                            # dev/114: discovery success ⇒ the two-lane candidates part
                            # EXISTS on this turn — runtime-minted (catalog rows tool-
                            # grounded, external rows probed), never the model's claim.
                            cand_part, text, cand_outcome = _mint_candidates_from_delegate(
                                loop_ctx, text,
                                ((req.get("inputs") or {}).get("catalog") or {}).get("rows")
                                or _dataset_discover_inputs(user_key, project_id, {})["catalog"]["rows"],
                            )
                            delegate_summary = text
                            if cand_part is not None:
                                minted.append(cand_part)
                                delegate_summary = "dataset candidates shown for review — select and confirm"
                            status = cand_outcome
                        elif status == "ok" and req["capability"] == "research.notes.compose":
                            # dev/95: see the non-streaming path.
                            note_parts, text, notes_outcome = _mint_notes_from_delegate(
                                user_key, project_id, loop_ctx, text,
                            )
                            delegate_summary = text
                            if note_parts:
                                minted.extend(note_parts)
                                delegate_summary = (
                                    f"{len(note_parts)} reviewed note "
                                    "proposal(s) — await Apply"
                                )
                            status = notes_outcome
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
                if isinstance(text, ParamRefusal) and refusals_used < MAX_REFUSED_ROUNDS:
                    refusals_used += 1  # dev/105 D2: a free correction, not a round
                else:
                    rounds_used += 1
                final = rounds_used >= MAX_TOOL_ROUNDS
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
                     delegations=delegations,
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
                     delegations=delegations,
            refused_rounds=refusals_used,
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
