"""The account's always-installed set (``defaults.json``): install a package into defaults and every existing project, or stop seeding it into new ones.

Application layer of the packages package (memo dev/143, B2): cut from ``services.py``
by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``packages_<module>.name``) so a test that patches the owner is seen by
every caller, and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging

from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories import defaults as defaults_io
from utk_curio.backend.app.packages.application import (
    project_packages as packages_project_packages,
    store_install as packages_store_install,
)
from utk_curio.backend.app.packages.domain.errors import PackageServiceError

log = logging.getLogger(__name__)


def uninstall_from_defaults(user, dir_name: str) -> dict:
    """Stop seeding *dir_name* into new projects.

    The mirror of :func:`install_to_defaults`, and the twin of
    ``datasets.application.mutations.remove_dataset_from_defaults``. Detach
    only: existing projects keep the package in their lockfiles and the user
    store copy stays, because "stop adding this to NEW dataflows" and "take it
    out of the ones I already have" are different decisions and only the first
    one was asked for. Removing it from one dataflow is
    ``DELETE /projects/<id>/<dir_name>``.

    Idempotent: removing something that is not in the defaults is a no-op, so a
    double click (or a retry) reports the same list rather than an error.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")

    user_key = _user_key_from_user(user)
    defaults_io.remove_from_defaults(user_key, dir_name)
    return {"packages": sorted(defaults_io.load_defaults(user_key))}


def install_to_defaults(user, dir_name: str) -> dict:
    """Add *dir_name* to defaults + every user's project lockfile + user store.

    Best-effort per project: a single project failure (e.g. malformed spec)
    is reported and the rest continue. Returns
    ``{"packages": [...], "projects": [{"id", "ok", "error?"}],
    "importErrors": {lib: reason}}``.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")

    user_key = _user_key_from_user(user)
    outcome = packages_store_install._ensure_user_store_install(user_key, dir_name)
    defaults_io.add_to_defaults(user_key, dir_name)

    results: list[dict] = []
    for project in projects_repo.list_for_user(user.id):
        try:
            current = packages_project_packages.get_project_lockfile(user_key, project.id)
            if dir_name in current:
                results.append({"id": project.id, "ok": True, "alreadyPresent": True})
                continue
            current.add(dir_name)
            packages_project_packages._write_lockfile(user_key, project.id, current)
            results.append({"id": project.id, "ok": True, "alreadyPresent": False})
        except Exception as exc:  # noqa: BLE001 — per-project failure is OK
            log.warning(
                "install_to_defaults: failed to patch project %s: %s",
                project.id, exc,
            )
            results.append({"id": project.id, "ok": False, "error": str(exc)})

    payload = {
        "packages": sorted(defaults_io.load_defaults(user_key)),
        "projects": results,
    }
    # Same reason as the per-project install: every project now references a
    # package whose library cannot be imported, and pip said nothing.
    payload["importErrors"] = outcome.import_errors
    return payload


def _user_key_from_user(user) -> str:
    """Local copy of projects.services._user_dir_key to avoid a circular import."""
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    if user.is_guest and user.username == CURIO_SHARED_GUEST_USERNAME:
        return "guest"
    return str(user.id)
