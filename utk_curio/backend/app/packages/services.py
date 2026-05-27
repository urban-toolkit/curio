"""Per-project package install / uninstall orchestration.

These services own the three-layer write protocol described in
[docs/CATALOG.md]:

  1. Shared catalog (read-only here)         — ``<repo_root>/packages/``
  2. Per-user package store (implementations) — ``.curio/users/<u>/packages/``
  3. Per-user defaults (auto-seed list)       — ``.curio/users/<u>/default-packages.json``
  4. Per-project lockfile (source of truth)   — ``spec.trill.json``

Every public function in this module touches at least #4 (the lockfile).
Install paths also touch #2 (and #3 when called via "add to defaults").
Uninstall paths touch #4, then run :func:`prune_unreferenced_packages`
which may touch #2 and #3.

The catalog source (#1) is read-only via :func:`catalog_root`; writes
land there only through ``factory/publish-catalog`` in
[routes.py](routes.py), which is gated by
``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from utk_curio.backend.app.packages import defaults as defaults_io
from utk_curio.backend.app.packages.installer import (
    InstallerError,
    install_packageage_from_directory,
    uninstall_packageage,
)
from utk_curio.backend.app.packages.seed import BUILTIN_PACKAGE_ID
from utk_curio.backend.app.packages.spec_packages import (
    project_packages,
    set_project_packages,
)
from utk_curio.backend.app.packages.storage import (
    PACKAGE_DIR_RE,
    list_user_packageages,
    package_dir,
    user_packageages_dir,
)
from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def catalog_root() -> Path:
    """Return ``<repo_root>/packages/`` — the source of catalog installs.

    Duplicates the helpers in [routes.py](routes.py) and [seed.py](seed.py)
    so this module doesn't depend on Flask's request-scoped imports. A
    future cleanup can centralise these three copies in one place.
    """
    # services.py -> packages/ -> app/ -> backend/ -> utk_curio/ -> repo_root/packages/
    return Path(__file__).resolve().parents[4] / "packages"


class PackageServiceError(Exception):
    """Raised for caller-facing package-service errors (bad input, not-found)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# User-store helpers
# ---------------------------------------------------------------------------

def _is_installed_in_user_store(user_key: str, dir_name: str) -> bool:
    try:
        return (package_dir(user_key, dir_name) / "manifest.json").is_file()
    except Exception:  # noqa: BLE001 — invalid dir_name etc.
        return False


def _installed_majors_by_pkg(user_key: str) -> dict[str, list[int]]:
    """Map ``<packageId>`` → sorted majors currently installed in user store.

    Feeds the spec-packages backfill so unversioned node types in legacy
    specs resolve to a concrete dirName when possible.
    """
    base = user_packageages_dir(user_key)
    if not base.is_dir():
        return {}
    out: dict[str, list[int]] = {}
    for entry in base.iterdir():
        if not entry.is_dir() or not PACKAGE_DIR_RE.match(entry.name):
            continue
        pkg_id, _, major = entry.name.rpartition("@")
        try:
            out.setdefault(pkg_id, []).append(int(major))
        except ValueError:
            continue
    for k in out:
        out[k].sort()
    return out


def _ensure_user_store_install(user_key: str, dir_name: str) -> None:
    """No-op if installed; otherwise copy from the shared catalog AND
    pip-install any Python deps the manifest declares.

    The pip step runs synchronously inside the request — heavy installs
    like ``torch`` can take many minutes (see :mod:`.pip_runner`). The
    Install button stays in its busy state for the whole duration. If
    pip fails the catalog copy is rolled back so a retry can re-attempt
    cleanly.
    """
    if _is_installed_in_user_store(user_key, dir_name):
        return
    src = catalog_root() / dir_name
    if not src.is_dir():
        raise PackageServiceError(
            f"catalog has no package {dir_name}", 404,
        )
    try:
        result = install_packageage_from_directory(user_key, src, replace=False)
    except InstallerError as exc:
        raise PackageServiceError(str(exc)) from exc

    py_deps = dict(result.manifest.python_deps or {})
    if not py_deps:
        return
    try:
        from utk_curio.backend.app.packages.pip_runner import (
            PipInstallError, install_python_deps,
        )
        install_python_deps(py_deps)
    except PipInstallError as exc:
        # Roll the just-installed files back so the user-store doesn't
        # show a package that's unusable. Best-effort: log + continue on
        # cleanup failure (the original pip error is the one we surface).
        try:
            import shutil
            from utk_curio.backend.app.packages.storage import package_dir
            shutil.rmtree(package_dir(user_key, dir_name), ignore_errors=True)
        except Exception:  # noqa: BLE001
            log.warning("Failed to roll back %s after pip failure", dir_name, exc_info=True)
        raise PackageServiceError(
            f"package files installed but pip install failed: {exc}",
        ) from exc


def ensure_user_packages_initialized(user_key: str) -> None:
    """Idempotently seed the per-user package store with ``curio.builtin``.

    The startup seeder in ``app/__init__.py`` only runs for the shared
    ``guest`` user, so the first time a real authenticated user touches the
    package system, their store is empty and the palette would be missing
    even the built-in nodes. Call this at the project-entry boundaries
    (save_project, load_project) so the user always has builtin available
    by the time the canvas mounts.

    Safe to call repeatedly: :func:`seed_dev_packageages` consults the
    per-user marker file and only re-seeds when fixtures have actually
    moved.
    """
    from utk_curio.backend.app.packages.seed import seed_dev_packageages

    try:
        seed_dev_packageages(user_key=user_key)
    except Exception:  # noqa: BLE001 — seeding must never block a project request
        log.warning("Builtin seed failed for user_key=%s", user_key, exc_info=True)


# ---------------------------------------------------------------------------
# Project lockfile read/write
# ---------------------------------------------------------------------------

def get_project_lockfile(user_key: str, project_id: str) -> set[str]:
    """Read the project's declared package dirNames (with backfill for legacy specs)."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise PackageServiceError(f"project {project_id} has no spec", 404)
    return project_packages(spec, _installed_majors_by_pkg(user_key))


def _write_lockfile(user_key: str, project_id: str, dirs: Iterable[str]) -> dict:
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise PackageServiceError(f"project {project_id} has no spec", 404)
    set_project_packages(spec, dirs)
    projects_storage.write_spec(user_key, project_id, spec)
    return spec


# ---------------------------------------------------------------------------
# Install/uninstall — per-project (drawer)
# ---------------------------------------------------------------------------

def install_to_project(
    user_key: str, project_id: str, dir_name: str,
) -> dict:
    """Add *dir_name* to *project_id*'s lockfile; install to user store if missing.

    Returns ``{"packages": [...], "addedToUserStore": bool}``.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")

    will_install = not _is_installed_in_user_store(user_key, dir_name)
    _ensure_user_store_install(user_key, dir_name)

    current = get_project_lockfile(user_key, project_id)
    if dir_name in current:
        return {
            "packages": sorted(current),
            "addedToUserStore": will_install,
        }
    current.add(dir_name)
    _write_lockfile(user_key, project_id, current)
    return {
        "packages": sorted(current),
        "addedToUserStore": will_install,
    }


def uninstall_from_project(
    user_key: str, project_id: str, dir_name: str,
) -> dict:
    """Drop *dir_name* from *project_id*'s lockfile and run the prune sweep.

    Returns ``{"packages": [...], "pruned": [...], "removedFromDefaults": [...]}``.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")
    if dir_name.startswith(f"{BUILTIN_PACKAGE_ID}@"):
        raise PackageServiceError(
            f"{BUILTIN_PACKAGE_ID} is built-in and cannot be uninstalled",
        )

    current = get_project_lockfile(user_key, project_id)
    if dir_name in current:
        current.discard(dir_name)
        _write_lockfile(user_key, project_id, current)

    prune = prune_unreferenced_packages(user_key, {dir_name})
    return {
        "packages": sorted(current),
        "pruned": sorted(prune["pruned"]),
        "removedFromDefaults": sorted(prune["removedFromDefaults"]),
    }


# ---------------------------------------------------------------------------
# Install — global (catalog page)
# ---------------------------------------------------------------------------

def install_to_defaults(user, dir_name: str) -> dict:
    """Add *dir_name* to defaults + every user's project lockfile + user store.

    Best-effort per project: a single project failure (e.g. malformed spec)
    is reported and the rest continue. Returns
    ``{"packages": [...], "projects": [{"id", "ok", "error?"}]}``.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")

    user_key = _user_key_from_user(user)
    _ensure_user_store_install(user_key, dir_name)
    defaults_io.add_to_defaults(user_key, dir_name)

    results: list[dict] = []
    for project in projects_repo.list_for_user(user.id, scope="mine"):
        try:
            current = get_project_lockfile(user_key, project.id)
            if dir_name in current:
                results.append({"id": project.id, "ok": True, "alreadyPresent": True})
                continue
            current.add(dir_name)
            _write_lockfile(user_key, project.id, current)
            results.append({"id": project.id, "ok": True, "alreadyPresent": False})
        except Exception as exc:  # noqa: BLE001 — per-project failure is OK
            log.warning(
                "install_to_defaults: failed to patch project %s: %s",
                project.id, exc,
            )
            results.append({"id": project.id, "ok": False, "error": str(exc)})

    return {
        "packages": sorted(defaults_io.load_defaults(user_key)),
        "projects": results,
    }


# ---------------------------------------------------------------------------
# Prune
# ---------------------------------------------------------------------------

def prune_unreferenced_packages(
    user_key: str, candidate_dirs: Iterable[str],
) -> dict[str, set[str]]:
    """Delete user-store copies (and defaults entries) for unreferenced candidates.

    For each candidate dirName:
      - Skip if it's the builtin (never prunable).
      - Scan all of the user's non-archived projects' lockfiles.
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
    installed_majors = _installed_majors_by_pkg(user_key)
    for project in projects_repo.list_for_user(user_id, scope="mine"):
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
            if uninstall_packageage(user_key, dn):
                pruned.add(dn)
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
            from utk_curio.backend.app.packages.pip_runner import (
                PipInstallError, uninstall_python_deps,
            )
            uninstall_python_deps(deps_to_remove)
        except PipInstallError as exc:
            # Don't fail the whole prune over a pip uninstall hiccup;
            # the user can clean up manually if needed.
            log.warning("prune: pip uninstall failed: %s", exc)
    return {"pruned": pruned, "removedFromDefaults": removed_from_defaults}


def _read_python_deps(user_key: str, dir_name: str) -> dict[str, str]:
    """Read the installed package's ``manifest.dependencies.python`` map."""
    from utk_curio.backend.app.packages.manifest import (
        ManifestError,
        load_packageage_manifest,
    )
    from utk_curio.backend.app.packages.storage import package_dir

    try:
        m = load_packageage_manifest(package_dir(user_key, dir_name))
    except (ManifestError, OSError):
        return {}
    return dict(m.python_deps or {})


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
    for package_path in list_user_packageages(user_key):
        if package_path.name in pruned_names:
            continue  # this one was just removed
        from utk_curio.backend.app.packages.manifest import (
            ManifestError,
            load_packageage_manifest,
        )
        try:
            m = load_packageage_manifest(package_path)
        except ManifestError:
            continue
        still_needed.update(dict(m.python_deps or {}).keys())
    return sorted(candidate_dep_names - still_needed)


# ---------------------------------------------------------------------------
# New-project seeding
# ---------------------------------------------------------------------------

def seed_spec_with_defaults(user_key: str, spec: dict | None) -> dict:
    """Merge per-user defaults into a new project's spec lockfile.

    Only acts when the spec's existing packages list is empty/missing.
    Returns the (possibly mutated) spec; safe to call with ``None``
    (returns an empty spec template).
    """
    if spec is None or not isinstance(spec, dict):
        spec = {"dataflow": {"nodes": [], "edges": [], "packages": []}}
    existing = project_packages(spec)
    if existing:
        return spec
    defaults = defaults_io.load_defaults(user_key)
    if not defaults:
        return spec
    set_project_packages(spec, defaults)
    return spec


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _user_key_from_user(user) -> str:
    """Local copy of projects.services._user_dir_key to avoid a circular import."""
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    if user.is_guest and user.username == CURIO_SHARED_GUEST_USERNAME:
        return "guest"
    return str(user.id)
