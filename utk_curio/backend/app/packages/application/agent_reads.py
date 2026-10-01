"""Agent read surfaces (memo dev/84): plain-dict summaries so the agents module (ADR-AG-007: thin wrappers, no package knowledge) can serve its packages.catalog / packages.resolve tools from the domain's single truth.

Application layer of the packages package (memo dev/143, B2): cut from ``services.py``
by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``packages_<module>.name``) so a test that patches the owner is seen by
every caller, and import order between siblings cannot matter.
"""

from __future__ import annotations

from utk_curio.backend.app.packages.domain.manifest import ManifestError
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.domain.versions import ResolverError
from utk_curio.backend.app.packages.repositories import catalog_dir as packages_catalog_dir
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.application import (
    project_packages as packages_project_packages,
    store_reads as packages_store_reads,
    templates as packages_templates,
)
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.application.resolution import resolve_for_project_unlocked
from utk_curio.backend.app.packages.application.seeding import BUILTIN_PACKAGE_ID


def _catalog_manifests() -> dict[str, "PackageManifest"]:
    """``dirName -> manifest`` for every well-formed committed catalog package."""

    root = packages_catalog_dir.catalog_root()
    out: dict[str, PackageManifest] = {}
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not PACKAGE_DIR_RE.match(entry.name):
            continue
        try:
            out[entry.name] = load_package_manifest(entry)
        except ManifestError:
            continue  # malformed fixtures are skipped, matching the catalog route
    return out


def agent_catalog_overview(user_key: str, project_id: str | None) -> list[dict]:
    """Per-package summaries for the agents' ``packages.catalog`` read tool.

    ``installed`` means the CURRENT project's lockfile (what matters for a node
    running in this project — dev/84); ``builtin`` marks ``curio.builtin``,
    which is always present and never proposable.

    Scope is the committed catalog PLUS whatever is already in this user's
    package store (memo dev/93 D4). The store half matters because an
    agent-authored package (``curio.agent``/``curio.notes``-style) never
    enters the committed catalog: before this, such a package could not be
    enlisted into a second project at all — ``package.install`` refused it as
    "not in the Nodes Catalog" — so an agent asked to reuse it had no move
    left except authoring yet another near-duplicate. A store manifest wins
    over a catalog one of the same dirName: it is the copy an install would
    actually enlist.
    """
    lockfile: set[str] = set()
    if project_id:
        try:
            lockfile = packages_project_packages.get_project_lockfile(user_key, project_id)
        except Exception:  # noqa: BLE001 — an unreadable project reads as empty
            lockfile = set()
    catalog = _catalog_manifests()  # committed catalog, not the store: outside
    return _agent_catalog_overview_unlocked(
        lockfile, packages_store_reads._locked_store_index(user_key), catalog,
    )


def _agent_catalog_overview_unlocked(
    lockfile: set[str],
    store: dict[str, object],
    catalog: dict[str, "PackageManifest"],
) -> list[dict]:
    """:func:`agent_catalog_overview` over existing snapshots (dev/99 R2).
    Takes no locks and performs no I/O."""
    manifests: dict[str, "PackageManifest"] = dict(catalog)
    for dir_name, manifest in store.items():
        if isinstance(manifest, Exception):
            continue  # an unreadable store copy cannot provide working nodes
        manifests[dir_name] = manifest
    rows: list[dict] = []
    for dir_name, manifest in sorted(manifests.items()):
        builtin = manifest.package_id == BUILTIN_PACKAGE_ID
        rows.append(
            {
                "dirName": dir_name,
                "packageId": manifest.package_id,
                "name": manifest.name,
                "description": manifest.description or "",
                "installed": builtin or dir_name in lockfile,
                "builtin": builtin,
            }
        )
    return rows


def template_landscape(user_key: str, project_id: str) -> dict:
    """Everything an agent needs to know about what already exists, from ONE
    walk of the package store (memo dev/99 R2).

    Returns ``{"available", "notEnlisted", "catalog", "skipped"}`` — the same
    data as :func:`available_templates`, :func:`installed_templates_not_in_project`
    and :func:`agent_catalog_overview`, plus the availability report's
    degradation signal, all derived from a single snapshot.

    Two reasons this exists rather than callers making three calls. It is
    CHEAPER: each of those public readers independently resolves the project
    lockfile and independently walks the store, so composing three of them for
    one payload cost three spec reads and three traversals. And it is the only
    shape that can be made ATOMIC: when the seed lock reaches readers (dev/99
    proper), one composite acquires it once and every part of the payload
    describes the same instant, where three separately-locked calls would each
    be internally consistent yet able to straddle a seeding pass — which is
    exactly the tear that lets an agent see a package in one half of its
    evidence and not the other, and author a duplicate.

    Callers in the agents domain consume this; they never own the lock
    (`ADR-AG-007` keeps package knowledge here). It calls the unlocked cores
    directly, never the public readers, so the non-reentrant seed lock can be
    acquired exactly once on every path.
    """
    # Non-store I/O first, so the lock covers only the store snapshot (§3.3).
    wanted = packages_project_packages._lockfile_or_empty(user_key, project_id)
    catalog = _catalog_manifests()
    store = packages_store_reads._locked_store_index(user_key)
    report = packages_templates._available_templates_report_unlocked(wanted, store)
    return {
        "available": report["templates"],
        "skipped": report["skipped"],
        "notEnlisted": packages_templates._installed_templates_not_in_project_unlocked(wanted, store),
        "catalog": _agent_catalog_overview_unlocked(wanted, store, catalog),
    }


def agent_resolve_report(user_key: str, dir_names: list[str]) -> dict:
    """Deps/permissions per requested package + a conflict probe (dev/84).

    Mirrors the catalog UI's pre-install probe: the requested packages resolve
    together with everything already in the user's store, with not-yet-installed
    catalog packages overridden to their committed manifests. Raises
    :class:`PackageServiceError` for an unknown/unresolvable package.
    """
    # The committed catalog is not package-store data: read it before the
    # lock (memo dev/99 §3.3). Then ONE acquisition covers the installed set,
    # the resolver's two store reads and the per-package manifests — the
    # report describes a single instant of the store.
    catalog = _catalog_manifests()
    with package_seed_lock(user_key):
        store = packages_store_reads._store_index(user_key)
        installed = set(store)
        unknown = [dn for dn in dir_names if dn not in installed and dn not in catalog]
        if unknown:
            raise PackageServiceError(
                f"unknown package(s): {', '.join(sorted(unknown))}", 404,
            )
        probe = sorted(set(dir_names) | installed)
        overrides = {
            dn: packages_catalog_dir.catalog_root() / dn for dn in probe if dn not in installed and dn in catalog
        }
        try:
            result = resolve_for_project_unlocked(user_key, probe, overrides=overrides)
        except ResolverError as exc:
            raise PackageServiceError(str(exc), 400) from exc

    def _manifest_for(dir_name: str) -> "PackageManifest | None":
        if dir_name in store:
            manifest = store[dir_name]
            return None if isinstance(manifest, Exception) else manifest
        return catalog.get(dir_name)

    packages: list[dict] = []
    for dir_name in dir_names:
        manifest = _manifest_for(dir_name)
        if manifest is None:
            continue
        packages.append(
            {
                "dirName": dir_name,
                "name": manifest.name,
                "permissions": list(manifest.permissions),
                "pythonDeps": dict(manifest.python_deps),
                "jsDeps": dict(manifest.js_deps),
            }
        )
    return {
        "packages": packages,
        "conflicts": [
            {
                "package": c.package,
                "ranges": [{"packageDir": p, "range": r} for (p, r) in c.ranges],
            }
            for c in result.conflicts
        ],
    }
