"""An invited editor's own package or model, asked of the dataflow's owner: the ``packages`` kind of request.

The requests and their review are ``projects/editor_requests.py``'s; this
module says what a request for a package asks and what the owner's Apply of
it does. On the owner's dataflow an editor's tab adds no package: his Add to
project of a package or a model, and his drop of its card onto her canvas or
of a model onto a node of hers, each ask her (:func:`asked`), as a
``package.install`` of ``src/contracts/agentInstalls.json``. The dataflow's
own packages, those she put in it (``project_packages.OwnersPackages``), ask
nothing.

* A package or a model of his store: her Apply (:func:`apply`) checks that its
  files are the ones its install recorded (``archive.integrity_mismatch``),
  copies it from his store into hers through the archive install every package
  takes (``store_install.install_package_from_archive``: the manifest, the
  size caps and the modules other packages of hers ship are checked again), a
  model with its weights, installs its libraries under her account, and adds
  it to the dataflow as her Add to project does: her own change, so her
  editors' runs then read it from her store. A package she holds already is
  not copied again.
* A package or a model of the shared catalog is installed from the catalog,
  as her own Add to project installs it. Unlike a dataset of the shared Data
  Catalog, which every account's runs read where it is, a package runs only
  from the store of an account that added it, so his drop of one asks too.

Before her Apply, her review shows what it would install (:func:`review`):
its manifest, and the conflicts its libraries have with her packages'.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.packages.application import (
    catalog as packages_catalog,
    project_packages as packages_project_packages,
    provisioning as packages_provisioning,
    resolution as packages_resolution,
    store_install as packages_store_install,
    store_reads as packages_store_reads,
)
from utk_curio.backend.app.packages.application import package_dependencies as packages_dependencies
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.domain.manifest import ManifestError, PackageManifest
from utk_curio.backend.app.packages.domain.package_closure import required_packages
from utk_curio.backend.app.packages.domain.package_id import BUILTIN_PACKAGE_ID, PACKAGE_DIR_RE, PackageIdError
from utk_curio.backend.app.packages.domain.versions import ResolverError
from utk_curio.backend.app.packages.infrastructure import backend_runtime as packages_backend_runtime
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.infrastructure.pip_runner import PipInstallError, PipSpecError
from utk_curio.backend.app.packages.repositories import catalog_dir as packages_catalog_dir
from utk_curio.backend.app.packages.repositories.archive import InstallerError, integrity_mismatch
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.store import package_dir
from utk_curio.backend.app.packages.schemas.responses import resolve_payload
from utk_curio.backend.app.projects.editor_requests import Asked

#: The install tool of the review a request is (``agentInstalls.json``).
TOOL = "package.install"
#: The request's field naming the package, and its name.
ITEM = "dirName"
NAME = "packageName"
#: What a refusal calls the items of this kind.
ITEMS = "packages"
#: What the owner is told who asks herself.
OWNERS_OWN = "You own this dataflow: add the package to it with Add to project."
NOT_FOUND = "Package not found"


def _manifest_in(folder: Path) -> PackageManifest | None:
    """The manifest of the package in *folder*, or None when there is none
    that reads."""
    try:
        return load_package_manifest(folder)
    except (ManifestError, OSError, ValueError):
        return None


def _catalog_copy(dir_name: str) -> Path | None:
    """The shared catalog's copy of *dir_name*, or None."""
    folder = packages_catalog_dir.catalog_root() / dir_name
    return folder if _manifest_in(folder) is not None else None


def _own_copy(user_key: str, dir_name: str) -> Path | None:
    """The copy of *dir_name* the store *user_key* holds, or None."""
    try:
        folder = package_dir(user_key, dir_name)
    except PackageIdError:
        return None
    return folder if _manifest_in(folder) is not None else None


# ---------------------------------------------------------------------------
# What a request asks for
# ---------------------------------------------------------------------------

def asked(flow, dir_name: str, *, add: bool) -> Asked:
    """What an editor's ask for the package *dir_name* is for: one of the
    shared catalog, or else one of his own store. Built-in, or one the dataflow
    uses already (``OwnersPackages``), it asks nothing: ``listed``. Whether he
    dropped it or added it (*add*) asks the same."""
    from utk_curio.backend.app.projects.services import _history_person

    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}", 400)
    if dir_name.startswith(f"{BUILTIN_PACKAGE_ID}@"):
        return Asked(reason="listed")
    if packages_project_packages.OwnersPackages(flow.owner_key, flow.project_id).uses(dir_name):
        return Asked(reason="listed")
    shared = _catalog_copy(dir_name)
    folder = shared or _own_copy(flow.asker_key, dir_name)
    manifest = _manifest_in(folder) if folder is not None else None
    if manifest is None:
        raise PackageServiceError(NOT_FOUND, 404)
    model = manifest.kind == "model"
    catalog = "Model Catalog" if model else "Node Catalog"
    where = f"from the shared {catalog}" if shared else f"from {_history_person(flow.user)['name']}'s {catalog}"
    return Asked(item=dir_name, fields={
        "summary": f"Add {'model' if model else 'package'} · {manifest.name}",
        "preview": " · ".join(part for part in (manifest.name, f"v{manifest.version}", manifest.publisher, where)
                               if part),
        "packageName": manifest.name,
        "packageKind": manifest.kind,
        "version": manifest.version,
        "publisher": manifest.publisher,
        "permissions": list(manifest.permissions),
        "shared": shared is not None,
        "store": None if shared else flow.asker_key,
    })


def _source(request: dict[str, Any]) -> Path | None:
    """The asker's copy of the package a request is for, or None for one of
    the shared catalog. Raises when his store no longer holds it."""
    store = request.get("store")
    if not store:
        return None
    folder = _own_copy(str(store), str(request.get("dirName") or ""))
    if folder is None:
        raise PackageServiceError("the package is no longer in the store it was asked from", 409)
    return folder


# ---------------------------------------------------------------------------
# The owner's review and Apply
# ---------------------------------------------------------------------------

def _resolved(owner_key: str, dir_name: str, own: Path | None):
    """The packages of the store *owner_key* resolved with *dir_name* and every
    package it needs, as her Add's review resolves them
    (``resolution.resolve_snapshot``), *dir_name* read from *own*, the asker's
    copy, while her store does not hold it. Raises :class:`ResolverError` when
    a package it needs is held neither by her store nor by the catalog."""
    copies = packages_dependencies.catalog().snapshot()
    with package_seed_lock(owner_key):
        store = packages_dependencies.readable(packages_store_reads._store_index(owner_key))
        overrides: dict[str, Path] = {}
        if own is not None and dir_name not in store:
            store = {**store, dir_name: load_package_manifest(own)}
            overrides[dir_name] = own
        names = required_packages(sorted({*store, dir_name}), store, copies)
        overrides = {**packages_resolution.resolver_overrides_for(owner_key, names), **overrides}
        return packages_resolution.resolve_for_project_unlocked(owner_key, names, overrides=overrides)


def review(flow, request: dict[str, Any]) -> dict[str, Any]:
    """What the owner's review of a request shows before her Apply, the dialog
    her own Add opens: the package as her Apply would install it (her copy
    when she holds it, else the asker's, else the catalog's) and the conflicts
    of its libraries with those of her packages."""
    dir_name = str(request["dirName"])
    held = _own_copy(flow.owner_key, dir_name)
    own = None if held is not None else _source(request)
    folder = held or own or _catalog_copy(dir_name)
    manifest = _manifest_in(folder) if folder is not None else None
    if manifest is None:
        raise PackageServiceError(NOT_FOUND, 404)
    payload = packages_catalog._listing_payload(manifest, folder)
    payload.pop("readme", None)
    try:
        conflicts = resolve_payload(_resolved(flow.owner_key, dir_name, own))["conflicts"]
    except ResolverError as exc:
        raise PackageServiceError(str(exc), 409) from exc
    return {"package": payload, "conflicts": conflicts}


def apply(flow, request: dict[str, Any]) -> dict[str, Any]:
    """The owner's Apply of a request for a package: copied from the asker's
    store into hers when she does not hold it, its files checked first, its
    libraries installed under her account; or installed from the shared
    catalog; then added to the dataflow as her Add to project adds it, as her
    change, with every package it needs. Refused, with nothing of it left in
    her store, when its files are not the ones its install recorded, when its
    libraries conflict with those of her packages, or when a package it needs
    cannot be had."""
    packages_provisioning.assert_may_install()
    owner_key, dir_name = flow.owner_key, str(request["dirName"])
    held = _own_copy(owner_key, dir_name) is not None
    own = None if held else _source(request)
    if own is not None:
        mismatch = integrity_mismatch(own)
        if mismatch:
            raise PackageServiceError(f"its files are not the ones its install recorded: {mismatch}", 409)
    conflicts = _resolved(owner_key, dir_name, own).conflicts
    if conflicts:
        named = ", ".join(sorted({conflict.package for conflict in conflicts}))
        raise PackageServiceError(f"its libraries conflict with those of your packages ({named})", 409)
    copied = own is not None and _copy_into(str(request["store"]), owner_key, dir_name)
    try:
        if copied:
            packages_backend_runtime.record_entry_pin(owner_key, dir_name)
            manifest = load_package_manifest(package_dir(owner_key, dir_name))
            packages_provisioning.provision_python_deps(owner_key, dir_name, manifest)
        installed = packages_project_packages.install_to_project(owner_key, flow.project_id, dir_name)
    except Exception:
        if copied:
            packages_store_install._take_back(owner_key, dir_name)
        raise
    return {"installedPackage": {
        "dirName": dir_name,
        "name": request.get("packageName") or dir_name,
        "importErrors": installed.get("importErrors") or {},
        **({"restartRecommended": installed["restartRecommended"]} if installed.get("restartRecommended") else {}),
    }}


def _copy_into(from_key: str, to_key: str, dir_name: str) -> bool:
    """Copy the package *dir_name* from the store *from_key* into the store
    *to_key*: exported as an archive, a model with its weights, and installed
    from it as every package is, the account's own content."""
    with packages_store_install.staging_scratch(to_key) as scratch:
        archive = packages_store_install.export_package_archive_to(from_key, dir_name, scratch / "package.curio.zip")
        with open(archive, "rb") as stream:
            packages_store_install.install_package_from_archive(to_key, stream, replace=False)
    return True


def refusal(exc: Exception) -> str | None:
    """Why an Apply that raised *exc* refused, in the words the owner is told;
    None for a fault that is no refusal."""
    if isinstance(exc, PipInstallError):
        return f"its libraries did not install: {exc}"
    if isinstance(exc, (PackageServiceError, InstallerError, ResolverError, PipSpecError, PackageIdError,
                        packages_backend_runtime.BackendRuntimeError)):
        return str(exc)
    return None
