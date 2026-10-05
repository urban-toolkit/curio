"""Package dependency resolution over the store: the package DAG from ``manifest.dependencies.packages`` (cycles and missing packages up front), the merged Python/JS dependency maps, and the lockfile-ready result.

Application layer of the packages package (memo dev/143, B2): cut from ``resolver.py``
by responsibility; every function keeps its name and body.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from dataclasses import (
    dataclass,
    field,
)

from utk_curio.backend.app.packages.domain.catalog_family import family_key_for_manifest
from utk_curio.backend.app.packages.domain.manifest import (
    ManifestError,
    PackageManifest,
)
from utk_curio.backend.app.packages.domain.versions import (
    DepConflict,
    merge_python_deps,
    ResolverError,
)
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.domain.package_id import PackageIdError
from utk_curio.backend.app.packages.repositories import catalog_dir as packages_catalog_dir
from utk_curio.backend.app.packages.repositories.store import (
    list_user_packages,
    package_dir,
)
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock


@dataclass(frozen=True)
class ResolveResult:
    installed_packages: tuple[dict[str, object], ...]  # lockfile entries (DAG order)
    python_deps: dict[str, str]
    js_deps: dict[str, str]
    conflicts: tuple[DepConflict, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def to_lockfile(self) -> dict[str, object]:
        """Return the JSON-serialisable lockfile shape used by ``spec.trill.json``."""
        return {
            "installedPackages": list(self.installed_packages),
            "pythonDeps": dict(self.python_deps),
            "jsDeps": dict(self.js_deps),
        }


def _load_manifests(
    user_key: str,
    package_dir_names: list[str] | None = None,
    *,
    overrides: dict[str, Path] | None = None,
) -> dict[str, PackageManifest]:
    """Load manifests by directory name. Skips malformed packages silently.

    UNLOCKED core (memo dev/99): the caller must already hold the per-user
    seed lock — :func:`resolve_for_project` and :func:`lockfile_for_user` do.

    ``overrides`` lets the caller point the resolver at an alternate
    manifest source for a given package dir name — e.g. the committed
    catalog fixture for a package the user hasn't installed yet (the
    pre-install conflict probe). When a name is in ``overrides`` *and*
    the user already has it installed, the override wins so the probe
    always reflects the catalog version about to be installed rather
    than whatever stale copy is still on disk.
    """
    overrides = overrides or {}
    if package_dir_names is not None:
        out: dict[str, PackageManifest] = {}
        for name in package_dir_names:
            path = overrides.get(name) or package_dir(user_key, name)
            try:
                out[name] = load_package_manifest(path)
            except ManifestError as exc:
                raise ResolverError(f"package {name} is malformed: {exc}") from exc
        return out
    # Walk every installed package for the user.
    out = {}
    for path in list_user_packages(user_key):
        try:
            out[path.name] = load_package_manifest(path)
        except ManifestError:
            continue
    return out


def _coord_index(
    manifests: dict[str, PackageManifest],
) -> tuple[dict[tuple[str, int], str], dict[str, tuple[str, ...]]]:
    """Maps ``(packageId, major)`` → dir and ``packageId`` → sorted dirs (for ambiguity checks)."""
    coord_to_dir: dict[tuple[str, int], str] = {}
    by_package_id: dict[str, list[str]] = defaultdict(list)
    for dn, m in manifests.items():
        coord_to_dir[(m.package_id, m.major)] = dn
        by_package_id[m.package_id].append(dn)
    for pid in by_package_id:
        by_package_id[pid].sort()
    dirs_map = {pid: tuple(dirs) for pid, dirs in by_package_id.items()}
    return coord_to_dir, dirs_map


def _resolve_package_dep_dir_name(
    from_dir: str,
    dep_key: str,
    coord_to_dir: dict[tuple[str, int], str],
    dirs_by_package_id: dict[str, tuple[str, ...]],
) -> str:
    """Resolve a ``dependencies.packages`` entry to an on-disk ``dirName``."""
    dep_key = dep_key.strip()
    if not dep_key:
        raise ResolverError(f"package {from_dir} has an empty package dependency key")
    if "@" in dep_key:
        pid, sep, maj_s = dep_key.partition("@")
        package_id_part = pid.strip()
        maj_s = maj_s.strip()
        if not package_id_part or not maj_s.isdigit():
            raise ResolverError(
                f"package {from_dir} has malformed package dependency key {dep_key!r}; "
                "expected <packageId> or <packageId>@<major>"
            )
        target = coord_to_dir.get((package_id_part, int(maj_s)))
        if target is None:
            raise ResolverError(
                f"package {from_dir} depends on {dep_key!r} which is not installed"
            )
        return target

    cand = dirs_by_package_id.get(dep_key)
    if not cand:
        raise ResolverError(
            f"package {from_dir} depends on {dep_key} which is not installed"
        )
    if len(cand) > 1:
        raise ResolverError(
            f"package {from_dir} depends on package id {dep_key!r} which is ambiguous "
            f"({list(cand)} installed); specify <packageId>@<major> in dependencies.packages"
        )
    return cand[0]


def _topo_order(
    package_dir_names: list[str],
    manifests: dict[str, PackageManifest],
) -> list[str]:
    """Return *package_dir_names* in topological order; detect cycles + missing deps.

    Each manifest's ``package_deps`` keys may be bare ``packageId`` (only when exactly
    one installed package uses that id) or ``packageId@major`` for an unambiguous edge.
    """
    coord_to_dir, dirs_by_package_id = _coord_index(manifests)
    selected = set(package_dir_names)
    visited: set[str] = set()
    pending: set[str] = set()
    order: list[str] = []

    def visit(dir_name: str) -> None:
        if dir_name in visited:
            return
        if dir_name in pending:
            raise ResolverError(
                f"package dependency cycle involving {dir_name}"
            )
        pending.add(dir_name)
        manifest = manifests[dir_name]
        for dep_key in manifest.package_deps:
            target_dir = _resolve_package_dep_dir_name(
                dir_name,
                dep_key,
                coord_to_dir,
                dirs_by_package_id,
            )
            if target_dir not in selected:
                # Pull transitive dep into the resolve scope.
                selected.add(target_dir)
            visit(target_dir)
        pending.discard(dir_name)
        visited.add(dir_name)
        order.append(dir_name)

    for dn in list(package_dir_names):
        visit(dn)
    return order


def _lockfile_entry_dict(manifest: PackageManifest, dir_name: str) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": manifest.package_id,
        "major": manifest.major,
        "version": manifest.version,
        "dirName": dir_name,
        "familyKey": family_key_for_manifest(manifest),
    }
    lin = manifest.lineage
    if lin is not None:
        entry["lineageRoot"] = {
            "packageId": lin.root.package_id,
            "major": lin.root.major,
        }
    return entry


def resolve_for_project(
    user_key: str,
    project_packages: list[str],
    *,
    overrides: dict[str, Path] | None = None,
) -> ResolveResult:
    """Resolve a set of packages into a lockfile-ready :class:`ResolveResult`.

    Parameters
    ----------
    user_key:
        ``"guest"`` or a numeric user id (validated by the storage layer).
    project_packages:
        The package directory names (``<packageId>@<major>``) the project
        explicitly pins. The resolver pulls in transitive dependencies
        from ``manifest.dependencies.packages`` automatically.
    overrides:
        Optional mapping from package dir name → manifest source directory.
        Used by the pre-install conflict probe to point the resolver at
        the committed catalog fixture for a package the user has not
        installed yet. See :func:`_load_manifests` for the precedence.
    """
    with package_seed_lock(user_key):
        return resolve_for_project_unlocked(
            user_key, project_packages, overrides=overrides,
        )


def resolve_for_project_unlocked(
    user_key: str,
    project_packages: list[str],
    *,
    overrides: dict[str, Path] | None = None,
) -> ResolveResult:
    """:func:`resolve_for_project` for a caller that ALREADY holds the
    per-user seed lock (memo dev/99 §3.2).

    The resolver reads the store twice — the pinned packages, then every
    other installed package for transitive deps — and both reads must see the
    same instant. A caller that has other store reads to make for the same
    payload (the catalog probe in ``services.agent_resolve_report``, the
    override discovery in the resolve routes) takes the lock once around all
    of them and calls this; the lock is not reentrant, so calling
    :func:`resolve_for_project` from inside it would deadlock.
    """
    if not project_packages:
        return ResolveResult(installed_packages=(), python_deps={}, js_deps={})

    # Load the explicitly-selected packages first (raises if malformed),
    # then merge in every other installed package for the user so the
    # topological walk can resolve transitive ``package_deps`` references
    # against package ids that are installed but not explicitly pinned.
    manifests = _load_manifests(user_key, project_packages, overrides=overrides)
    for dn, manifest in _load_manifests(user_key).items():
        manifests.setdefault(dn, manifest)

    order = _topo_order(list(project_packages), manifests)

    python_per_package = [
        (dn, manifests[dn].python_deps) for dn in order
    ]
    py_merged, py_conflicts = merge_python_deps(python_per_package)

    js_per_package = [
        (dn, manifests[dn].js_deps) for dn in order if manifests[dn].js_deps
    ]
    js_merged, js_conflicts = merge_python_deps(js_per_package)

    lockfile_entries: tuple[dict[str, object], ...] = tuple(
        _lockfile_entry_dict(manifests[dn], dn)
        for dn in order
    )
    return ResolveResult(
        installed_packages=lockfile_entries,
        python_deps=py_merged,
        js_deps=js_merged,
        conflicts=tuple(py_conflicts) + tuple(js_conflicts),
    )


def lockfile_for_user(user_key: str) -> dict[str, object]:
    """Convenience: resolve **every** installed package for *user_key*.

    Returns an empty lockfile when the user has no packages.
    """
    with package_seed_lock(user_key):
        names = [p.name for p in list_user_packages(user_key)]
        return resolve_for_project_unlocked(user_key, names).to_lockfile()


def resolver_overrides_for(user_key: str, packages: list[str]) -> dict[str, Path]:
    """Build the ``overrides`` map for :func:`resolve_for_project`.

    The pre-install conflict probe in the catalog UI passes the
    candidate's ``dirName`` alongside the already-installed packages so it
    can show the InstallDialog with a precise conflict report. The
    candidate is by definition *not yet installed* - its manifest lives
    in the committed catalog at ``<repo_root>/packages/<dirName>/``,
    not in ``<user>/packages/<dirName>/``. Without an override, the
    resolver would raise ``package <name> is malformed: missing
    manifest.json`` and the user could never get past the dialog.

    For each requested package that is not currently installed, we point
    the resolver at the catalog directory iff a well-formed manifest is
    present there. Unknown packages are left alone so the resolver still
    surfaces a precise "not installed" error.

    UNLOCKED: the caller holds the per-user seed lock (memo dev/99) so the
    "is it installed?" answer here and the resolver's own store reads describe
    the same instant — otherwise a seeded package caught in the swap window
    would be resolved against its catalog copy instead of its installed one.
    """
    catalog_root = packages_catalog_dir.catalog_root()
    if not catalog_root.is_dir():
        return {}
    out: dict[str, Path] = {}
    for name in packages:
        try:
            user_path = package_dir(user_key, name)
        except PackageIdError:
            continue
        if (user_path / "manifest.json").is_file():
            continue
        candidate = catalog_root / name
        if (candidate / "manifest.json").is_file():
            out[name] = candidate
    return out


def resolve_snapshot(user_key: str, packages: list[str]):
    """Override discovery + resolution against ONE store snapshot (dev/99).

    The seed lock is released before anything slow: both callers hand the
    result to the sandbox / the response after this returns.
    """
    with package_seed_lock(user_key):
        overrides = resolver_overrides_for(user_key, packages)
        return resolve_for_project_unlocked(user_key, packages, overrides=overrides)
