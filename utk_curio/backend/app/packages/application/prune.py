"""The prune sweep: drop user-store copies (and defaults entries, and the python libraries only they asked for) for packages no project references.

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
from utk_curio.backend.app.projects.usage import dataflow_usage
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.datasets.domain.code_refs import model_ids_in_code
from utk_curio.backend.app.packages.domain.spec_packages import (
    model_ref_packages,
    package_usage_in_spec,
    project_packages,
)
from utk_curio.backend.app.packages.repositories import defaults as defaults_io
from utk_curio.backend.app.packages.infrastructure import backend_runtime as packages_backend_runtime
from utk_curio.backend.app.packages.infrastructure.pip_runner import PipInstallError
from utk_curio.backend.app.packages.application import libraries as packages_libraries
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

    Then the libraries only the pruned packages asked for leave from where
    their install put them (:func:`_uninstall_libraries_only_they_asked_for`).

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

    referenced = packages_in_use(user_key, candidates)

    unreferenced = candidates - referenced
    pruned: set[str] = set()
    removed_from_defaults: set[str] = set()
    current_defaults = defaults_io.load_defaults(user_key)
    new_defaults = set(current_defaults)
    # Each pruned package's libraries, read BEFORE its files go, for the
    # sweep after the loop.
    pruned_libraries: dict[str, set[str]] = {}
    for dn in unreferenced:
        try:
            pruned_libraries[dn] = _node_libraries(user_key, dn)
        except Exception:  # noqa: BLE001 — keep prune resilient
            pruned_libraries[dn] = set()
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

    if pruned:
        _uninstall_libraries_only_they_asked_for(
            user_key, set().union(*(pruned_libraries[dn] for dn in pruned)),
        )
    return {"pruned": pruned, "removedFromDefaults": removed_from_defaults}


def _uninstall_libraries_only_they_asked_for(user_key: str, libraries: set[str]) -> None:
    """Uninstall the pruned packages' *libraries* that nothing else asks for,
    and that Curio put there (``libraries.names_to_take_back``, which the
    libraries dialog's Remove asks too), from where their install put them:
    the libraries dialog's removal (``libraries.uninstall_user_libraries``),
    whose route follows the install's.

    A library another package still asks for stays, and its copy in the
    account's tree goes where the image's meets every range left
    (``libraries.give_way_after_a_removal``), as the next start would take
    it."""
    names = packages_libraries.names_to_take_back(user_key, libraries) if libraries else []
    if names:
        try:
            packages_libraries.uninstall_user_libraries(user_key, names)
        except PipInstallError as exc:
            # Don't fail the whole prune over a pip uninstall hiccup;
            # the user can clean up manually if needed.
            log.warning("prune: pip uninstall failed: %s", exc)
    packages_libraries.give_way_after_a_removal(user_key)


def dataflow_packages(spec, installed_majors) -> set[str]:
    """The package dirNames the dataflow *spec* uses: its lockfile, with the
    backfill from its canvas nodes (``project_packages``), and the model
    packages its nodes are bound to (``metadata.modelRefs``,
    ``model_ref_packages``), each read against *installed_majors*, the majors
    its owner's store holds.

    The one rule for "a dataflow uses this package": :func:`packages_in_use`
    holds it for each of an account's dataflows, and a run of an editor the
    dataflow's owner invited reads these from the owner's store
    (``project_packages.OwnersPackages``).
    """
    return project_packages(spec, installed_majors) | model_ref_packages(spec, installed_majors, model_ids_in_code)


def packages_in_use(user_key: str, candidates: Iterable[str] | None = None) -> set[str]:
    """The package dirNames this user's projects use, each project's by
    :func:`dataflow_packages`. With *candidates*, the scan stops once every
    one of them has been found.

    The prune above keeps what it returns, and Remove from account refuses it.
    """
    user_id = _user_id(user_key)
    wanted = set(candidates) if candidates is not None else None
    referenced: set[str] = set()
    installed_majors = packages_store_reads._installed_majors_by_pkg(user_key)
    for project in projects_repo.list_for_user(user_id):
        spec = projects_storage.read_spec(user_key, project.id)
        if spec is None:
            continue
        referenced.update(dataflow_packages(spec, installed_majors))
        if wanted is not None and wanted.issubset(referenced):
            break  # short-circuit: every candidate has at least one reference
    return referenced


def package_usage(user_key: str, dir_name: str) -> list[dict]:
    """The account's dataflows that use the package *dir_name*, one row each
    (``package_usage_in_spec``), through the scan the Data Catalog's usage
    read makes (``projects.usage.dataflow_usage``). ``codeOnly`` marks a
    dataflow whose nodes name the model in their code alone, which keeps
    nothing: the Model Catalog's Remove names it."""
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")
    installed_majors = packages_store_reads._installed_majors_by_pkg(user_key)
    return dataflow_usage(
        _user_id(user_key),
        user_key,
        lambda spec, _project_id: package_usage_in_spec(spec, dir_name, installed_majors, model_ids_in_code),
    )


def _user_id(user_key: str) -> int:
    """The DB id of *user_key*'s account, whose projects a scan enumerates:
    the on-disk segment is the numeric id, or ``guest`` for the shared guest
    user."""
    from utk_curio.backend.app.users.services import _shared_guest_user

    if user_key == "guest":
        return _shared_guest_user().id
    if user_key.isdigit():
        return int(user_key)
    raise PackageServiceError(f"invalid user_key {user_key!r}")


def _read_python_deps(user_key: str, dir_name: str) -> dict[str, str]:
    """Read the installed package's ``manifest.dependencies.python`` map."""
    m = packages_store_reads._read_manifest(user_key, dir_name)
    return dict(m.python_deps or {}) if m is not None else {}


def _node_libraries(user_key: str, dir_name: str) -> set[str]:
    """The libraries *dir_name*'s install put where node code imports from:
    those its manifest declares, when they go there
    (``backend_runtime.dep_destinations``, ``host`` or ``both``). A package
    whose libraries go to its own overlay alone loses them with its backend
    residue, and none of them is anywhere else."""
    manifest = packages_store_reads._read_manifest(user_key, dir_name)
    if manifest is None:
        return set()
    destination, _reason = packages_backend_runtime.dep_destinations(manifest)
    if destination not in ("host", "both"):
        return set()
    return set(manifest.python_deps or {})
