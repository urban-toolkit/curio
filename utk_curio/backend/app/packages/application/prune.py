"""The prune sweep: drop user-store copies (and defaults entries, and now-unreferenced python libraries) for packages no project references.

Application layer of the packages package (memo dev/143, B2): cut from ``services.py``
by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``packages_<module>.name``) so a test that patches the owner is seen by
every caller, and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging
from typing import Iterable

from utk_curio.backend.app.projects import (
    repositories as projects_repo,
    storage as projects_storage,
)
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.domain.spec_packages import project_packages
from utk_curio.backend.app.packages.repositories import defaults as defaults_io
from utk_curio.backend.app.packages.infrastructure import (
    backend_runtime as packages_backend_runtime,
    pip_runner as packages_pip_runner,
)
from utk_curio.backend.app.packages.infrastructure.pip_runner import PipInstallError
from utk_curio.backend.app.packages.application import store_reads as packages_store_reads
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.application.seeding import BUILTIN_PACKAGE_ID
from utk_curio.backend.app.packages.application.store_install import uninstall_package

log = logging.getLogger(__name__)


def prune_unreferenced_packages(
    user_key: str, candidate_dirs: Iterable[str],
) -> dict[str, set[str]]:
    """Delete user-store copies (and defaults entries) for unreferenced candidates.

    For each candidate dirName:
      - Skip if it's the builtin (never prunable).
      - Scan all of the user's projects' lockfiles.
      - If no project references it, delete from user store AND remove from
        defaults. (Defaults exists explicitly to keep something seeded into
        new projects — if nothing actually uses it, the seed has no future
        purpose.)

    Returns ``{"pruned": <dirs>, "removedFromDefaults": <dirs>}``.
    """
    candidates = {
        d for d in candidate_dirs
        if isinstance(d, str)
        and PACKAGE_DIR_RE.match(d)
        and not d.startswith(f"{BUILTIN_PACKAGE_ID}@")
    }
    if not candidates:
        return {"pruned": set(), "removedFromDefaults": set()}

    # Need a User to enumerate projects. We accept user_key (the on-disk
    # segment) but resolving projects requires the DB id. Detect: numeric
    # user_key → DB id; "guest" → look up the shared guest user.
    from utk_curio.backend.app.users.services import _shared_guest_user

    if user_key == "guest":
        owner = _shared_guest_user()
        user_id = owner.id
    elif user_key.isdigit():
        user_id = int(user_key)
    else:
        raise PackageServiceError(f"invalid user_key {user_key!r}")

    referenced: set[str] = set()
    installed_majors = packages_store_reads._installed_majors_by_pkg(user_key)
    for project in projects_repo.list_for_user(user_id):
        spec = projects_storage.read_spec(user_key, project.id)
        if spec is None:
            continue
        referenced.update(project_packages(spec, installed_majors))
        if candidates.issubset(referenced):
            break  # short-circuit: every candidate has at least one reference

    unreferenced = candidates - referenced
    pruned: set[str] = set()
    removed_from_defaults: set[str] = set()
    current_defaults = defaults_io.load_defaults(user_key)
    new_defaults = set(current_defaults)
    # Track each pruned package's manifest.python_deps BEFORE deletion so
    # we can ref-count and pip-uninstall after the files are gone.
    pruned_python_deps: dict[str, dict[str, str]] = {}
    for dn in unreferenced:
        try:
            pruned_python_deps[dn] = _read_python_deps(user_key, dn)
        except Exception:  # noqa: BLE001 — keep prune resilient
            pruned_python_deps[dn] = {}
        try:
            if uninstall_package(user_key, dn):
                pruned.add(dn)
                # dev/97: the sweep dev/91 §6.7 promised — overlay + data
                # dir + pin go with the package; the audit ledger survives.
                packages_backend_runtime.remove_backend_residue(user_key, dn)
        except Exception as exc:  # noqa: BLE001
            log.warning("prune: uninstall of %s failed: %s", dn, exc)
            continue
        if dn in new_defaults:
            new_defaults.discard(dn)
            removed_from_defaults.add(dn)
    if removed_from_defaults:
        defaults_io.save_defaults(user_key, new_defaults)

    # Pip-uninstall every Python dep that *was* declared by a pruned
    # package and is no longer declared by anything still installed.
    # Walking the surviving manifests by hand is safer than trying to
    # diff before/after — it gives a single authoritative reference set.
    deps_to_remove = _python_deps_unique_to_pruned(user_key, pruned_python_deps, pruned)
    if deps_to_remove:
        try:
            packages_pip_runner.uninstall_python_deps(deps_to_remove)
        except PipInstallError as exc:
            # Don't fail the whole prune over a pip uninstall hiccup;
            # the user can clean up manually if needed.
            log.warning("prune: pip uninstall failed: %s", exc)
    return {"pruned": pruned, "removedFromDefaults": removed_from_defaults}


def _read_python_deps(user_key: str, dir_name: str) -> dict[str, str]:
    """Read the installed package's ``manifest.dependencies.python`` map."""
    m = packages_store_reads._read_manifest(user_key, dir_name)
    return dict(m.python_deps or {}) if m is not None else {}


def _python_deps_unique_to_pruned(
    user_key: str,
    pruned_deps: dict[str, dict[str, str]],
    pruned_names: set[str],
) -> list[str]:
    """Return the dep names that were declared by a pruned package and
    are NOT declared by any other package still in the user store.

    Walks every surviving package's manifest once so cost stays linear
    in the user's installed-package count.
    """
    candidate_dep_names: set[str] = set()
    for dn in pruned_names:
        candidate_dep_names.update(pruned_deps.get(dn, {}).keys())
    if not candidate_dep_names:
        return []
    still_needed: set[str] = set()
    for dir_name, manifest in packages_store_reads._locked_store_index(user_key).items():
        if dir_name in pruned_names or isinstance(manifest, Exception):
            continue  # just removed, or unreadable — declares nothing we can see
        still_needed.update(dict(manifest.python_deps or {}).keys())
    return sorted(candidate_dep_names - still_needed)
