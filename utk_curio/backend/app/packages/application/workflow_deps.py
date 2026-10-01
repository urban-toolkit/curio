"""A dataflow's declared package dependencies on load: which are not ready (missing from the store, a declared library gone, or installed-but-unimportable), and installing them into the store — libraries follow the package.

Application layer of the packages package (memo dev/143, B2-b): lifted out of ``routes.py`` so handlers
parse, call and serialize and carry no rules; every function keeps its body.
"""

from __future__ import annotations

from utk_curio.backend.app.packages.application import (
    prune as packages_prune,
    seeding as packages_seeding,
    store_install as packages_store_install,
)
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.infrastructure import pip_runner as packages_pip_runner
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.repositories.store import list_user_packages


def check_workflow_deps(user_key: str, packages: list) -> dict:
    """Report which of a dataflow's declared packages aren't ready.

    *packages* is the loaded spec's ``dataflow.packages`` lockfile. A package is
    "needed" if it isn't in the user's store, OR it is but some of its declared
    python deps aren't actually installed (e.g. a lib was pip-uninstalled out
    from under it). A dep that is installed at a satisfying version and still
    does not import is reported apart from ``packages`` as ``broken``, because
    reinstalling does not fix that. ``deferred`` is the subset of ``packages``
    whose package id is in ``seeding.INSTALL_ON_DEMAND_PACKAGE_IDS`` — too
    expensive to pull in as a side effect of opening a dataflow.
    Returns ``{"packages": [...], "deferred": [...], "broken": [...]}``.
    """
    wanted = [
        dn for dn in packages if isinstance(dn, str) and PACKAGE_DIR_RE.match(dn)
    ]
    # Store membership + declared deps in ONE seed-lock hold (memo dev/99);
    # the pip presence probes run after release.
    with package_seed_lock(user_key):
        in_store = {p.name for p in list_user_packages(user_key)}
        declared = {
            dn: packages_prune._read_python_deps(user_key, dn)
            for dn in wanted if dn in in_store
        }
    need: set[str] = set()
    # (package, dep) for every dep pip already considers done. Version-satisfied
    # but unimportable is a different problem with a different remedy, so those
    # are probed - and reported, not reinstalled.
    probe: list[tuple[str, str]] = []
    for dir_name in wanted:
        if dir_name not in in_store:
            need.add(dir_name)
            continue
        # Installed in the store - flag only if a declared dep went missing.
        missing = {n for n, spec in declared[dir_name].items() if not packages_pip_runner.is_satisfied(n, spec)}
        if missing:
            need.add(dir_name)
        probe += [(dir_name, dep) for dep in declared[dir_name] if dep not in missing]

    # ONE probe for the whole request: each dep otherwise pays its own
    # interpreter start, which cost 4.7s for curio.weather's three libraries on
    # the first load of a dataflow that declares it.
    failures = packages_pip_runner.import_failures({dep for _, dep in probe})
    broken = [
        {"package": pkg, "dep": dep, "error": failures[dep]}
        for pkg, dep in probe
        if dep in failures
    ]
    deferred = {
        dn for dn in need
        if dn.rsplit("@", 1)[0] in packages_seeding.INSTALL_ON_DEMAND_PACKAGE_IDS
    }
    return {
        "packages": sorted(need),
        "deferred": sorted(deferred),
        "broken": broken,
    }


def install_workflow_deps(user_key: str, pkg_dirs: list[str]) -> dict:
    """Install the catalog packages a dataflow declares it depends on, each via
    :func:`store_install.install_to_store` (copy if missing + pip-install its
    declared python deps). Returns ``{"installedPackages": [...], "importErrors":
    {lib: reason}}``; a package that fails raises :class:`PackageServiceError`
    naming it, with the failure's own status.
    """
    installed_packages: list[str] = []
    import_errors: dict[str, str] = {}
    for dir_name in pkg_dirs:
        try:
            outcome = packages_store_install.install_to_store(user_key, dir_name)
        except PackageServiceError as exc:
            raise PackageServiceError(f"failed to install {dir_name}: {exc}", exc.status) from exc
        installed_packages.append(dir_name)
        import_errors.update(outcome.import_errors)
    return {
        "installedPackages": installed_packages,
        "importErrors": import_errors,
    }
