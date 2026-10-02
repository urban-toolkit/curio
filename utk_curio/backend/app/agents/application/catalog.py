"""Catalog reads: facets, cards, definition bundles, materialized built-ins, and the three listings (global hub, My Imports, installed in project).

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain import contracts
from utk_curio.backend.app.agents.domain.manifest import AGENT_CATEGORIES
from utk_curio.backend.app.agents.domain.manifest import AgentManifest
from utk_curio.backend.app.agents.domain.manifest import AgentManifestError
from utk_curio.backend.app.agents.repositories import catalog_settings
from utk_curio.backend.app.agents.repositories import imports
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.agents.repositories import publications
from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.common.safe_paths import PathTraversalError
from utk_curio.backend.app.projects import storage as projects_storage


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
        # An internal built-in runs only as a delegate; no listing shows one.
        "inCatalog": not builtin.is_internal(m.dir_name),
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
    try:
        store = storage.read_definition_bundle(user_key, coord)
    except (AgentManifestError, PathTraversalError):
        # A name no agent directory can have: no definition in the store.
        store = None
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


def _copy_published(user_key: str, coord: str) -> None:
    """Copy a published definition into the user store, stamped ``global``
    trust: it came from the Global Catalog, so it runs from the adder's own
    copy after its publisher unpublishes it (#438), the way a shared dataset
    or node package does, and it is never this account's to publish."""
    try:
        bundle = storage.read_definition_bundle_from_dir(publications.published_agent_dir(coord))
    except (AgentManifestError, PathTraversalError):
        return
    if bundle is None:
        return
    manifest = dict(bundle["manifest"])
    manifest["provenance"] = {**(manifest.get("provenance") or {}), "trust": "global"}
    try:
        storage.write_definition_atomic(user_key, coord, manifest, bundle["prompts"])
    except FileExistsError:
        pass  # a concurrent add wrote it first


def _materialize_definition(user_key: str, coord: str) -> None:
    """Write an added agent's bytes (manifest + prompt assets) into the user
    store, so it is self-contained and runs from its own on-disk assets: a
    built-in's from the roster rather than the legacy ``llm-prompts/`` dir, a
    published one's from the Global Catalog (:func:`_copy_published`).

    Heals stale copies (memo dev/44): a built-in store copy that predates a
    roster asset (e.g. the pre-dev/38 missing system preamble) is rewritten to
    the current roster set on the next install/import — idempotent, and never
    touches a non-built-in definition (an owned import deliberately shadowing
    a built-in coord keeps its own bytes, as does an earlier copy of a
    published one)."""
    existing = storage.load_installed_agent_definition(user_key, coord)
    if existing is not None and existing.provenance.trust != "built-in":
        return  # owned/imported shadow — its bytes are authoritative
    spec = builtin.get_builtin_spec(coord)
    if spec is None:
        if existing is None:
            _copy_published(user_key, coord)
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
    # Every prompt the manifest declares: the preamble, the instruction, and
    # each mode's own.
    files = {}
    for key, asset in manifest["prompts"].items():
        text = builtin.read_prompt_text(coord, key)
        if text is not None:
            files[asset["path"]] = text
    storage.write_definition(user_key, coord, manifest, files)


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
        if not builtin.is_internal(m.dir_name):
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
        m = None if builtin.is_internal(coord) else _resolve_definition(user_key, coord)
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


def choosable_agents(user_key: str) -> list[dict]:
    """The agents whose LLM configuration this account may choose: the catalog
    cards, the published definitions and the account's imports, one row
    (``{id, name, category}``) per agent id, since a choice covers every
    version. Never an internal built-in, which always runs on its caller's."""
    internal = builtin.internal_agent_ids()
    rows: dict[str, dict] = {}

    def _add(m: AgentManifest) -> None:
        if m.agent_id not in internal:
            rows.setdefault(m.agent_id, {"id": m.agent_id, "name": m.name, "category": m.category})

    for m in builtin.list_builtin_manifests():
        _add(m)
    for m in publications.list_published():
        _add(m)
    for coord in sorted(imports.load_imported_agents(user_key)):
        m = None if builtin.is_internal(coord) else _resolve_definition(user_key, coord)
        if m is not None:
            _add(m)
    return sorted(rows.values(), key=lambda row: (row["name"].casefold(), row["id"]))


def list_installed_in_project(user_key: str, project_id: str) -> list[dict]:
    """The project's installed templates from its ``dataflow.agents`` lockfile."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    imported = imports.load_imported_agents(user_key)
    installed = set(project_agents.project_agents(spec))
    out: list[dict] = []
    for coord in project_agents.project_agents(spec):
        m = None if builtin.is_internal(coord) else _resolve_definition(user_key, coord)
        if m is None:
            continue
        out.append(
            _manifest_to_card(
                m, scope="installed", imported=coord in imported, installed_in_project=True,
                requires_agents=_requires_agents_rows(user_key, m, installed),
            )
        )
    return out


def catalog_settings_listing(user_key: str) -> list[dict]:
    """Every catalog setting: its schema and default, the account's value, and
    each agent and capability that reads it. Account-level and independent of
    cards: internal agents are listed as readers, and nothing here depends on
    what a project installed."""
    readers = _settings_readers(user_key)
    stored = catalog_settings.stored_values(user_key)
    current = catalog_settings.values(user_key)
    return [
        {
            "key": key,
            "label": setting.label,
            "description": setting.description,
            "schema": setting.schema,
            "default": setting.default,
            "value": current[key],
            "isDefault": key not in stored,
            "readBy": readers.get(key, []),
        }
        for key, setting in contracts.CATALOG_SETTINGS.items()
    ]


def _settings_readers(user_key: str) -> dict[str, list[dict]]:
    """Setting key to the ``{agentId, agentName, capability, internal}`` entries
    that read it, over the built-ins and the account's own definitions. A
    ``capability`` of ``None`` means every run of the agent."""
    manifests = list(builtin.list_builtin_manifests())
    for coord in sorted(imports.load_imported_agents(user_key)):
        m = _resolve_definition(user_key, coord)
        if m is not None and m.provenance.trust != "built-in":
            manifests.append(m)
    readers: dict[str, list[dict]] = {}
    for m in manifests:
        declared = [(None, key) for key in m.inputs_required_config] + [
            (cap.id, key) for cap in m.capabilities for key in cap.required_config
        ]
        for capability, key in declared:
            readers.setdefault(key, []).append({
                "agentId": m.agent_id,
                "agentName": m.name,
                "capability": capability,
                "internal": builtin.is_internal(m.dir_name),
            })
    return readers
