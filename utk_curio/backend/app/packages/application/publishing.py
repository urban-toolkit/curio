"""Publishing to and withdrawing from the shared catalog directory, with publisher ownership (dev/110): only the account that published a package may remove it.

Application layer of the packages package (memo dev/143, B2-b): lifted out of ``routes.py`` so handlers
parse, call and serialize and carry no rules; every function keeps its body.
"""

from __future__ import annotations

from pathlib import Path

from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories import (
    catalog_dir as packages_catalog_dir,
    publisher_record,
)
from utk_curio.backend.app.packages.repositories.archive import InstallResult, zip_package_tree
from utk_curio.backend.app.packages.repositories.store import package_dir

NOT_THE_PUBLISHER_MESSAGE = (
    "Only the account that published this package can remove it "
    "from the shared catalog."
)
NOT_THE_PUBLISHER_REPLACE_MESSAGE = (
    "Only the account that published this package can replace it "
    "in the shared catalog."
)


def _refuse_replacing_someone_elses(catalog: Path, dir_name: str, user_key: str) -> None:
    """A replace removes what is there, so it follows unpublish's rule: only the
    recorded publisher, and nobody for a package with no record (#563)."""
    if (catalog / dir_name).is_dir() and not publisher_record.is_publisher(catalog, dir_name, user_key):
        raise PackageServiceError(NOT_THE_PUBLISHER_REPLACE_MESSAGE, 403)


def publish_installed_to_catalog(
    user_key: str, dir_name: str, *, replace: bool,
) -> tuple[InstallResult, Path]:
    """Publish the caller's installed copy of *dir_name* into ``<repo_root>/packages/``.

    The store directory goes over as it is, through the same archive the
    Export button downloads: README, LICENSE, ``scripts/``, ``backend/``,
    declared version ranges and every manifest key arrive unchanged (#433).
    Records who published it — without that the catalog is a global tree with
    no recorded owner, so nothing could tell a package the user authored from
    one that shipped with the deployment (see repositories/publisher_record.py).
    InstallerError propagates for the route to answer.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError("dir_name must match <packageId>@<major>")
    source = package_dir(user_key, dir_name)
    if not source.is_dir():
        raise PackageServiceError(f"package {dir_name} is not installed", 404)
    catalog = packages_catalog_dir.catalog_root()
    _refuse_replacing_someone_elses(catalog, dir_name, user_key)
    result = packages_catalog_dir.publish_package_archive_to_catalog_dir(
        zip_package_tree(source),
        catalog,
        replace=replace,
    )
    catalog_path = catalog / result.manifest.dir_name
    publisher_record.record_publisher(catalog, result.manifest.dir_name, user_key)
    return result, catalog_path


def unpublish_from_catalog(user_key: str, dir_name: str) -> None:
    """Remove a package directory from ``<repo_root>/packages/`` (developer catalog only).

    Does **not** uninstall from the user's package store. Existence is checked
    BEFORE authorization, so a package that is simply not there reports 404
    rather than "not yours" - a removed package has no publisher record either,
    and the ownership gate fails closed, so checking that first turned every 404
    into a confusing 403. Only the publisher may withdraw it: fails closed for
    unrecorded packages, which is every package published before the record
    existed. Mirrors the dataset rule in ``CatalogMutations._assert_is_publisher``.
    InstallerError propagates for the route to answer.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError("dir_name must match <packageId>@<major>")
    catalog = packages_catalog_dir.catalog_root()
    if not (catalog / dir_name).is_dir():
        raise PackageServiceError(f"catalog has no package {dir_name}", 404)
    if not publisher_record.is_publisher(catalog, dir_name, user_key):
        raise PackageServiceError(NOT_THE_PUBLISHER_MESSAGE, 403)
    removed = packages_catalog_dir.remove_package_from_catalog_dir(catalog, dir_name)
    if not removed:
        raise PackageServiceError(f"catalog has no package {dir_name}", 404)
    publisher_record.forget_publisher(catalog, dir_name)
