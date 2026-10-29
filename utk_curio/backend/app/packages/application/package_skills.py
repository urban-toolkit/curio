"""The skills of the packages a dataflow uses, for the agents that work on it.

Application layer of the packages package. A package ships skills for Curio's
agents in its ``skills/`` folder, one folder each (``repositories/skills.py``).
A run on a dataflow holds the skills of the packages its lockfile names
(``dataflow.packages``, read as every backend reader reads it, backfill
included), each read from the account's copy of the package, else from the
package catalog's, as a run finds a node's template (``node_templates``). The
agents feature reads them as skills (``agents/application/skill_runs.py``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import is_within
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.domain.spec_packages import project_packages
from utk_curio.backend.app.packages.repositories import catalog_dir as packages_catalog_dir
from utk_curio.backend.app.packages.repositories.skills import skill_folders
from utk_curio.backend.app.packages.repositories.store import package_dir
from utk_curio.backend.app.packages.application import store_reads as packages_store_reads

log = logging.getLogger(__name__)


def dataflow_skill_folders(user_key: str | None, spec) -> list[tuple[str, Path]]:
    """``(<packageId>@<major>, folder)`` for each skill of each package the
    dataflow *spec* uses: the packages in the lockfile's order, each one's
    skills by name. Never raises: a package that cannot be found or read
    ships none, and the cause is logged."""
    majors: dict[str, list[int]] = {}
    if user_key:
        try:
            majors = packages_store_reads._installed_majors_by_pkg(user_key)
        except Exception as exc:  # noqa: BLE001 - an unreadable store holds no package
            log.warning("Could not list the packages of %s's store for a run's skills: %s", user_key, exc)
    found: list[tuple[str, Path]] = []
    for dir_name in sorted(project_packages(spec, majors)):
        root = _package_root(user_key, dir_name)
        if root is not None:
            found += [(dir_name, folder) for folder in skill_folders(root)]
    return found


def package_skill_names(user_key: str | None) -> dict[str, str]:
    """The skills each package the account can reach ships, by name: the
    package of each, ``<packageId>@<major>``. The account's own copies come
    first, then the package catalog's, each in its folder's order; a name
    two packages ship is the first's. Never raises: a store or a catalog
    that cannot be read ships none, and the cause is logged."""
    roots: list[tuple[str, Path]] = []
    if user_key:
        try:
            majors = packages_store_reads._installed_majors_by_pkg(user_key)
            roots += [(f"{pkg}@{major}", package_dir(user_key, f"{pkg}@{major}"))
                      for pkg, numbers in sorted(majors.items()) for major in numbers]
        except Exception as exc:  # noqa: BLE001 - an unreadable store holds no package
            log.warning("Could not list the packages of %s's store for their skills: %s", user_key, exc)
    try:
        base = packages_catalog_dir.catalog_root().resolve()
        if base.is_dir():
            roots += [(entry.name, entry) for entry in sorted(base.iterdir())
                      if entry.is_dir() and PACKAGE_DIR_RE.match(entry.name)]
    except Exception as exc:  # noqa: BLE001 - an unreadable catalog holds no package
        log.warning("Could not list the package catalog for its skills: %s", exc)
    found: dict[str, str] = {}
    for dir_name, root in roots:
        for folder in skill_folders(root):
            found.setdefault(folder.name, dir_name)
    return found


def _package_root(user_key: str | None, dir_name: str) -> Path | None:
    """The account's copy of the package *dir_name*, else the package
    catalog's; None when neither holds it or *dir_name* names no package."""
    if not PACKAGE_DIR_RE.match(dir_name):
        return None
    try:
        if user_key:
            own = package_dir(user_key, dir_name)
            if (own / "manifest.json").is_file():
                return own
        base = packages_catalog_dir.catalog_root().resolve()
        shared = (base / dir_name).resolve()
        if is_within(shared, base) and (shared / "manifest.json").is_file():
            return shared
    except Exception as exc:  # noqa: BLE001 - a package that cannot be found ships no skill
        log.warning("Could not find the package %s for a run's skills: %s", dir_name, exc)
    return None
