"""The catalog packages every hosted guest has (``--guest-packages``).

A hosted guest adds no package and installs no library
(``users.capabilities.install_refusal``), so a node whose package the shared
guest's account lacks fails for every guest. The operator names the packages
every guest has, by their folders in the shared catalog
(``config.CURIO_GUEST_PACKAGES``). Each start, in the home process's startup
work (``server.py``), :func:`add_guest_packages` puts each into the shared
guest's store as an add to all projects puts it there, with every package it
needs (``store_install._ensure_user_store_install``), and into the account's
defaults, which the catalog pages show as added and a new dataflow starts
with. Their libraries are the launcher's to install, at launch, with the
examples' (``cli/dependencies.py``), so the start runs no pip. The account's
dataflows keep their lockfiles: a node of the package reads its modules from
the store.

What the flag gave, the store copies a start's add made and the defaults
entries it wrote, is recorded (``repositories/guest_record.py``), and a later
start takes off what the flag no longer names: never a copy the store held
before the flag named it, the built-in, a package the shipped examples need or
one a dataflow of the account uses.
"""

from __future__ import annotations

import logging

from utk_curio.backend import config
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.packages.domain.package_id import BUILTIN_PACKAGE_ID, PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories import (
    defaults as defaults_io,
    guest_record,
)
from utk_curio.backend.app.packages.repositories.store import list_user_packages
from utk_curio.backend.app.packages.application import (
    prune as packages_prune,
    seeding as packages_seeding,
    store_install as packages_store_install,
    store_reads as packages_store_reads,
)

log = logging.getLogger(__name__)


def named_guest_packages() -> tuple[str, ...]:
    """The folders ``--guest-packages`` names (``config.CURIO_GUEST_PACKAGES``),
    in its order, each once."""
    return tuple(dict.fromkeys(config.CURIO_GUEST_PACKAGES))


def add_guest_packages(user_key: str) -> list[str]:
    """Give the account *user_key*, the shared guest's, the packages
    ``--guest-packages`` names, each with every package it needs, and take
    off what the flag gave it before and no longer names. Answers the
    packages the account has from the flag now.

    A package that cannot be given is logged and the others are given all the
    same; while one cannot, nothing is taken off, since what it needs is not
    known. Without the flag, and with nothing given before, nothing is read
    or written."""
    earlier = guest_record.load(user_key)
    named = named_guest_packages()
    if not named and not earlier:
        return []
    given: dict[str, guest_record.GivenPackage] = {}
    failed = False
    for dir_name in named:
        if not PACKAGE_DIR_RE.match(dir_name):
            log.warning("--guest-packages names %r, which is no package folder", dir_name)
            continue
        try:
            brought, copied, defaulted = _give(user_key, dir_name)
        except Exception as exc:  # noqa: BLE001 - one package must stop neither the others nor the start
            failed = True
            log.warning("Could not give the shared guest the package %s: %s", dir_name, exc)
            continue
        for each in brought:
            before = given.get(each) or earlier.get(each) or guest_record.GivenPackage()
            given[each] = guest_record.GivenPackage(
                store=before.store or each in copied,
                defaults=before.defaults or each in defaulted,
            )
    gone = {dir_name: entry for dir_name, entry in earlier.items() if dir_name not in given}
    if failed:
        given.update(gone)
    else:
        given.update(_take_off(user_key, gone))
    guest_record.save(user_key, given)
    return sorted(dir_name for dir_name in given if dir_name not in gone)


def _give(user_key: str, dir_name: str) -> tuple[tuple[str, ...], set[str], set[str]]:
    """Put *dir_name* and every package it needs into the store of
    *user_key* as an add does, without their libraries, and into its
    defaults: the packages it brought, those of them the add copied in, and
    those whose defaults entry this wrote."""
    held = {path.name for path in list_user_packages(user_key)}
    outcome = packages_store_install._ensure_user_store_install(user_key, dir_name, libraries=False)
    brought = tuple(outcome.packages) or (dir_name,)
    defaults = defaults_io.load_defaults(user_key)
    defaulted: set[str] = set()
    for each in brought:
        if each not in defaults:
            defaults_io.add_to_defaults(user_key, each)
            defaulted.add(each)
    return brought, set(brought) - held, defaulted


def _take_off(user_key: str, gone: dict[str, guest_record.GivenPackage]) -> dict[str, guest_record.GivenPackage]:
    """Take off the account what the flag gave it of each package in *gone*,
    which it no longer names: the defaults entry the flag wrote, and the store
    copy the flag's add made, unless something else keeps the package
    (:func:`_kept_for_another_reason`). Answers what could not be taken off,
    for a later start to take off."""
    examples_need: set[str] | None = None
    left: dict[str, guest_record.GivenPackage] = {}
    for dir_name, entry in sorted(gone.items()):
        try:
            if entry.defaults:
                defaults_io.remove_from_defaults(user_key, dir_name)
            if entry.store:
                if examples_need is None:
                    examples_need = set(packages_seeding.example_dep_package_ids())
                if not _kept_for_another_reason(user_key, dir_name, examples_need):
                    packages_store_install.take_back_copy(user_key, dir_name)
                    log.info("Took %s off the shared guest's account: --guest-packages no longer names it", dir_name)
        except Exception as exc:  # noqa: BLE001 - one package must stop neither the others nor the start
            log.warning("Could not take %s off the shared guest's account: %s", dir_name, exc)
            left[dir_name] = entry
    return left


def _kept_for_another_reason(user_key: str, dir_name: str, examples_need: set[str]) -> bool:
    """Whether the store of *user_key* keeps *dir_name* whatever the flag
    says: the built-in, a package the shipped examples need (*examples_need*,
    by package id), or one a dataflow of the account uses
    (``prune.dataflow_packages``: its lockfile, its nodes and its models), an
    example among them."""
    package_id = dir_name.rsplit("@", 1)[0]
    if package_id == BUILTIN_PACKAGE_ID or package_id in examples_need:
        return True
    majors = packages_store_reads._installed_majors_by_pkg(user_key)
    for project_id in projects_storage.list_project_ids(user_key):
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is not None and dir_name in packages_prune.dataflow_packages(spec, majors):
            return True
    return False
