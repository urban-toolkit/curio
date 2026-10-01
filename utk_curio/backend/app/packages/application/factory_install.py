"""The Package Builder's install paths for a draft: build it (Save-As preserving the unedited sources on disk), refuse a read-only target, and install the built archive into the user store.

Application layer of the packages package (memo dev/143, B2-b): lifted out of ``routes.py`` so handlers
parse, call and serialize and carry no rules; every function keeps its body.
"""

from __future__ import annotations

from pathlib import Path

from utk_curio.backend.app.packages.application import (
    provisioning as packages_provisioning,
    store_install as packages_store_install,
)
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.builder.factory import (
    BuildResult,
    build_package_archive,
    preserve_unedited_sources,
)
from utk_curio.backend.app.packages.domain.manifest import ManifestError
from utk_curio.backend.app.packages.domain.package_id import PackageIdError
from utk_curio.backend.app.packages.repositories.archive import InstallResult
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.store import package_dir

READ_ONLY_DRAFT_MESSAGE = "this package is read-only - save changes as a new package"


def installed_dir_for_draft(user_key: str, manifest_raw) -> "Path | None":
    """The user's installed directory for a draft's coordinate, if any.

    Save-As rebuilds a whole package from one draft, so both the build and the
    install path need to know whether they are rewriting something that already
    exists on disk - that is what makes source preservation possible.
    """
    if not isinstance(manifest_raw, dict):
        return None
    package_id_raw = manifest_raw.get("id")
    major_raw = (manifest_raw.get("compatibility") or {}).get("major")
    if not isinstance(package_id_raw, str) or not isinstance(major_raw, int):
        return None
    try:
        candidate = package_dir(user_key, f"{package_id_raw}@{major_raw}")
    except PackageIdError:
        return None
    return candidate if candidate.is_dir() else None


def refuse_read_only_draft(user_key: str, manifest_raw: object) -> None:
    """Refuse a draft whose manifest says ``readOnly`` — or whose installed target does.

    Defense-in-depth: a forged draft can omit readOnly, so the installed package at the
    target coordinate is checked too. Catches any attempt to overwrite a read-only
    package that's already installed (e.g. curio.builtin). An unreadable installed
    manifest is left for the install path to surface with a more specific error.
    """
    if not isinstance(manifest_raw, dict):
        return
    if manifest_raw.get("readOnly") is True:
        raise PackageServiceError(READ_ONLY_DRAFT_MESSAGE)
    package_id_raw = manifest_raw.get("id")
    major_raw = (manifest_raw.get("compatibility") or {}).get("major")
    if isinstance(package_id_raw, str) and isinstance(major_raw, int):
        try:
            installed_dir = package_dir(user_key, f"{package_id_raw}@{major_raw}")
        except PackageIdError:
            installed_dir = None
        if installed_dir is not None and installed_dir.is_dir():
            try:
                if load_package_manifest(installed_dir).read_only:
                    raise PackageServiceError(READ_ONLY_DRAFT_MESSAGE)
            except ManifestError:
                pass  # Let the install path surface a more specific error.


def build_draft(user_key: str, draft: dict) -> BuildResult:
    """Validate a draft and produce its ``.curio.zip``.

    Same preservation the install path does: a Save-As draft over an existing
    package carries real source only for the edited template, so building
    without this ships placeholder bodies for every sibling - an exported
    archive that silently destroys code when imported elsewhere.
    """
    existing_dir = installed_dir_for_draft(user_key, draft.get("manifest"))
    draft = preserve_unedited_sources(draft, existing_dir)
    return build_package_archive(draft, onto=existing_dir)


def install_draft(user_key: str, draft: dict, *, replace: bool) -> tuple[BuildResult, InstallResult]:
    """Build a draft and install it into the user store in one shot (the wizard's "Save and install").

    Save-As over an existing package only carries real source bytes for the
    template the user actively edited; every other template comes through
    with the STARTER_CODE placeholder. Read the unedited templates' real
    source from disk before the rebuild so we don't clobber them, and build
    onto the installed package so what the draft does not model survives.
    FactoryError / InstallerError propagate for the route to answer.
    """
    packages_provisioning.assert_may_install()
    manifest_raw = draft.get("manifest")
    refuse_read_only_draft(user_key, manifest_raw)
    existing_dir = installed_dir_for_draft(user_key, manifest_raw)
    draft = preserve_unedited_sources(draft, existing_dir)
    built = build_package_archive(draft, onto=existing_dir)
    result = packages_store_install.install_package_from_archive(
        user_key, built.archive, replace=replace,
    )
    return built, result
