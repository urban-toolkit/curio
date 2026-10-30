"""A project's package set — the lockfile inside ``spec.trill.json`` (memo dev/101): read with backfill, the ONE writer, install into / uninstall from a project.

Application layer of the packages package (memo dev/143, B2): cut from ``services.py``
by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``packages_<module>.name``) so a test that patches the owner is seen by
every caller, and import order between siblings cannot matter.
"""

from __future__ import annotations

from typing import Iterable

from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.datasets.domain.code_refs import model_ids_in_code
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.domain.spec_packages import (
    project_packages,
    referencing_nodes,
    set_project_packages,
)
from utk_curio.backend.app.packages.application import (
    prune as packages_prune,
    store_install as packages_store_install,
    store_reads as packages_store_reads,
)
from utk_curio.backend.app.packages.repositories import defaults as defaults_io
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.application.seeding import BUILTIN_PACKAGE_ID


class OwnersPackages:
    """The packages of a dataflow's owner that a run of an editor she invited
    reads from her store, *store_key*: those the dataflow *project_id* uses
    (``prune.dataflow_packages``), read from its spec there the first time the
    run asks. Nothing of them is copied into the editor's store, and her other
    packages are not read.

    A run hands this to ``python_modules.modules_for_node`` and
    ``model_packages.resolve_model_dirs`` (*owners*), which resolve a package
    or a model the dataflow uses from her store, as her own run does, and any
    other from the editor's."""

    def __init__(self, store_key: str, project_id: str):
        self.store_key = store_key
        self.project_id = project_id
        self._used: frozenset[str] | None = None

    @property
    def used(self) -> frozenset[str]:
        """The dirNames of the packages the dataflow uses."""
        if self._used is None:
            spec = projects_storage.read_spec(self.store_key, self.project_id)
            majors = packages_store_reads._installed_majors_by_pkg(self.store_key)
            self._used = frozenset(packages_prune.dataflow_packages(spec, majors))
        return self._used

    def uses(self, dir_name: str | None) -> bool:
        """Whether the dataflow uses the package *dir_name*."""
        return dir_name is not None and dir_name in self.used


def get_project_lockfile(user_key: str, project_id: str) -> set[str]:
    """Read the project's declared package dirNames (with backfill for legacy specs)."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise PackageServiceError(f"project {project_id} has no spec", 404)
    return project_packages(spec, packages_store_reads._installed_majors_by_pkg(user_key))


def _lockfile_or_empty(user_key: str, project_id: str) -> set[str]:
    """The project's declared package dirNames, or empty when the project has
    no readable lockfile. A genuine (non-``PackageServiceError``) fault still
    propagates — the callers that swallow everything do so deliberately."""
    try:
        return set(get_project_lockfile(user_key, project_id))
    except PackageServiceError:
        return set()


def _write_lockfile(user_key: str, project_id: str, dirs: Iterable[str]) -> dict:
    # Hold the per-project spec lock across the read-modify-write so a concurrent
    # dataset mutation (replace_dataflow_datasets) or project save can't
    # clobber the package lockfile (or vice versa). The lockfile is written
    # through the dataflow's doc, its one writer, so a tab in its room gets it.
    with projects_storage.spec_write_lock(user_key, project_id):
        spec = dataflow_docs.live(user_key, project_id)
        if spec is None:
            raise PackageServiceError(f"project {project_id} has no spec", 404)
        set_project_packages(spec, dirs)
        dataflow_docs.write(user_key, project_id, spec, dataflow_docs.person(user_key, "packages"))
        return spec


def install_to_project(
    user_key: str, project_id: str, dir_name: str,
) -> dict:
    """Add *dir_name* to *project_id*'s lockfile; install to user store if missing.

    The packages it needs (``dependencies.packages``, and theirs in turn) are
    installed with it and go in the lockfile beside it: the dataflow then uses
    each (``prune.packages_in_use``), and a node of the package finds their
    modules at the major the lockfile names (``python_modules``).

    Returns ``{"packages": [...], "addedToUserStore": bool, "importErrors":
    {lib: reason}}``, plus ``restartRecommended`` when pip actually changed a
    shared library under the running server.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")

    outcome = packages_store_install._ensure_user_store_install(user_key, dir_name)
    # dev/92 B-2: additive restart-honesty field — present exactly when pip
    # actually changed shared libraries under the running server.
    extra: dict = {}
    if outcome.installed:
        extra["restartRecommended"] = {"libs": outcome.installed}
    # The package arrived and one of its libraries does not work. pip counts
    # matching metadata as satisfaction, so this reads as a clean install right
    # up until a node touches the library; the response is the last place the
    # failure is still attached to the package that brought it in. Always
    # present, empty included — an absent key is how an OLD backend answers, and
    # "nothing is broken" is a different statement from "nobody looked".
    extra["importErrors"] = outcome.import_errors

    current = get_project_lockfile(user_key, project_id)
    added = {dir_name, *outcome.packages}
    if not added <= current:
        current |= added
        _write_lockfile(user_key, project_id, current)
    return {
        "packages": sorted(current),
        "addedToUserStore": outcome.copied,
        **extra,
    }


def detach_from_all_projects(user_key: str, dir_name: str) -> list[str]:
    """Drop *dir_name* from every one of this user's project lockfiles.

    A lockfile entry is a reference Curio manages, not something the user
    typed, so removing the package it names is Curio's job too. Leaving them
    behind gave every dataflow that had ever installed the package a
    permanent dangling entry: ``useEnsureWorkflowDeps`` tries to reinstall
    anything in the lockfile that is not in the store, so each open of that
    dataflow retried an install that cannot succeed and ended in "Could not
    install <coordinate>".

    Best-effort per project: a spec that cannot be read or written is skipped
    rather than failing the uninstall, since the package is already gone from
    the store by the time this runs. Returns the project ids it changed.
    """
    detached: list[str] = []
    for project_id in projects_storage.list_project_ids(user_key):
        try:
            current = get_project_lockfile(user_key, project_id)
        except Exception:  # noqa: BLE001 - an unreadable spec is not this call's problem
            continue
        if dir_name not in current:
            continue
        try:
            _write_lockfile(user_key, project_id, current - {dir_name})
        except Exception:  # noqa: BLE001 - same
            continue
        detached.append(project_id)
    return detached


def remove_unused_package(user_key: str, dir_name: str) -> None:
    """Remove from account, on the catalog pages: *dir_name* leaves the user's
    store, with its backend residue and its defaults entry, while no project
    uses it, and is refused with a 409 while one does. "Uses" is the prune's
    rule (``packages_in_use``), so a package the account added to all
    projects before it had a dataflow, in the defaults and in no lockfile,
    leaves too, and new projects stop asking for it."""
    if dir_name in packages_prune.packages_in_use(user_key, {dir_name}):
        raise PackageServiceError(
            f"a dataflow uses {dir_name}: remove it from that dataflow first", 409,
        )
    packages_store_install.remove_package(user_key, dir_name)
    defaults_io.remove_from_defaults(user_key, dir_name)


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

    # memo dev/101: refuse while canvas nodes still use the package. The
    # backfill in ``project_packages`` would re-derive it from those nodes on
    # the next read, so a "successful" uninstall here was a permanent no-op
    # that reported success — the drawer showed the package installed again
    # on every reload with no explanation. Name the count instead.
    spec = projects_storage.read_spec(user_key, project_id)
    users = referencing_nodes(
        spec, dir_name, packages_store_reads._installed_majors_by_pkg(user_key), model_ids_in_code,
    )
    if users:
        raise PackageServiceError(
            f"{len(users)} node{'s' if len(users) != 1 else ''} on this canvas "
            f"use{'s' if len(users) == 1 else ''} {dir_name} — delete "
            f"{'them' if len(users) != 1 else 'it'} first",
            409,
        )

    current = get_project_lockfile(user_key, project_id)
    if dir_name in current:
        current.discard(dir_name)
        _write_lockfile(user_key, project_id, current)

    prune = packages_prune.prune_unreferenced_packages(user_key, {dir_name})
    return {
        "packages": sorted(current),
        "pruned": sorted(prune["pruned"]),
        "removedFromDefaults": sorted(prune["removedFromDefaults"]),
    }
