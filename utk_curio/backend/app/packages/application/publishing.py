"""Publishing to and withdrawing from the shared catalog directory, with publisher ownership (dev/110): only the account that published a package may remove it.

Application layer of the packages package (memo dev/143, B2-b): lifted out of ``routes.py`` so handlers
parse, call and serialize and carry no rules; every function keeps its body.
"""

from __future__ import annotations

from pathlib import Path

from utk_curio.backend.app.packages.application import factory_install as packages_factory_install
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.builder.factory import (
    BuildResult,
    build_package_archive,
    preserve_unedited_sources,
)
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories import (
    catalog_dir as packages_catalog_dir,
    publisher_record,
)
from utk_curio.backend.app.packages.repositories.archive import InstallResult

NOT_THE_PUBLISHER_MESSAGE = (
    "Only the account that published this package can remove it "
    "from the shared catalog."
)


def publish_draft_to_catalog(
    user_key: str, body: dict, *, replace: bool,
) -> tuple[BuildResult, InstallResult, Path]:
    """Build a draft and publish it into ``<repo_root>/packages/`` — **developers only**.

    Same trap as the factory install: a draft built from
    ``draftFromInstalledPackagePayload`` only carries real source for the
    template the user actively edited; every other template ships the
    STARTER_CODE placeholder. Read the user's installed sources from disk
    before the rebuild so we don't publish placeholders to the catalog.
    Records who published it — without that the catalog is a global tree with
    no recorded owner, so nothing could tell a package the user authored from
    one that shipped with the deployment (see repositories/publisher_record.py).
    FactoryError / InstallerError propagate for the route to answer.
    """
    catalog = packages_catalog_dir.catalog_root()
    existing_dir = packages_factory_install.installed_dir_for_draft(user_key, body.get("manifest"))
    body = preserve_unedited_sources(body, existing_dir)
    built = build_package_archive(body)
    result = packages_catalog_dir.publish_package_archive_to_catalog_dir(
        built.archive,
        catalog,
        replace=replace,
    )
    catalog_path = catalog / result.manifest.dir_name
    publisher_record.record_publisher(catalog, result.manifest.dir_name, user_key)
    return built, result, catalog_path


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
