"""The Package Builder's install paths for a draft: build it (Save-As preserving the unedited sources on disk), refuse a read-only target, and install the built archive into the user store.

Application layer of the packages package (memo dev/143, B2-b): lifted out of ``routes.py`` so handlers
parse, call and serialize and carry no rules; every function keeps its body.

A new package whose node loads a model the account holds is built as a model
package of its own, a copy of that model (:func:`model_source_for_draft`).
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Callable

from utk_curio.backend.app.datasets.domain.code_refs import model_ids_in_code
from utk_curio.backend.app.packages.application import (
    model_packages as packages_model_packages,
    provisioning as packages_provisioning,
    python_modules as packages_python_modules,
    store_install as packages_store_install,
)
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.builder.factory import (
    BuiltArchive,
    ModelSource,
    build_package_archive_to,
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


def imported_modules_for_draft(user_key: str, draft: dict) -> frozenset[str]:
    """The modules the packages a draft depends on ship (``dependencies.packages``,
    resolved in *user_key*'s store): its templates import them, nobody pip-installs them."""
    manifest_raw = draft.get("manifest") if isinstance(draft, dict) else None
    deps = manifest_raw.get("dependencies") if isinstance(manifest_raw, dict) else None
    package_deps = deps.get("packages") if isinstance(deps, dict) else None
    if not isinstance(package_deps, dict) or not package_deps:
        return frozenset()
    return packages_python_modules.dependency_module_names(user_key, package_deps)


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


def model_source_for_draft(user_key: str, draft: dict, existing_dir: Path | None) -> ModelSource | None:
    """The model a new package's one node loads, which the package then
    copies: Save as package node of a node that loads a model makes a model
    package of its own. The first model the node's code names
    (``curio_load_model("<id>")``) that the account's store holds is the one.

    None, and a node package as before, for a draft saved into an installed
    package, a draft of more than one node or of a declared kind, and a node
    that names no model the account holds. Raises ``ModelWeightsUnavailable``
    when the model's weights cannot be had (a pip install's left-out weight
    whose download fails)."""
    manifest = draft.get("manifest") if isinstance(draft, dict) else None
    templates = manifest.get("templates") if isinstance(manifest, dict) else None
    if existing_dir is not None or not isinstance(templates, list) or len(templates) != 1 or "kind" in manifest:
        return None
    codes = [
        entry["code"] for entry in (draft.get("sources") or {}).values()
        if isinstance(entry, dict) and isinstance(entry.get("code"), str)
    ]
    for model_id in model_ids_in_code("\n".join(codes)):
        copy = packages_model_packages.model_copy(user_key, model_id)
        if copy is not None:
            raw, files = copy
            python = (raw.get("dependencies") or {}).get("python") or {}
            return ModelSource(model_id=model_id, block=raw["model"], python=dict(python), files=files)
    return None


def _build_into(user_key: str, draft: dict, folder: Path) -> BuiltArchive:
    """Validate a draft and write its ``.curio.zip`` into *folder*: a model
    package's weights never sit in memory.

    Same preservation the install path does: a Save-As draft over an existing
    package carries real source only for the edited template, so building
    without this ships placeholder bodies for every sibling - an exported
    archive that silently destroys code when imported elsewhere.
    """
    existing_dir = installed_dir_for_draft(user_key, draft.get("manifest"))
    draft = preserve_unedited_sources(draft, existing_dir)
    return build_package_archive_to(
        folder / "draft.curio.zip", draft, onto=existing_dir,
        imported_modules=imported_modules_for_draft(user_key, draft),
        model=model_source_for_draft(user_key, draft, existing_dir),
    )


def build_draft_for_download(user_key: str, draft: dict) -> tuple[BuiltArchive, Callable[[], None]]:
    """A draft's ``.curio.zip`` written to a file, and the call that removes
    it, which the route makes once the response is sent."""
    stack = contextlib.ExitStack()
    folder = stack.enter_context(packages_store_install.staging_scratch(user_key))
    try:
        return _build_into(user_key, draft, folder), stack.close
    except BaseException:
        stack.close()
        raise


def install_draft(user_key: str, draft: dict, *, replace: bool) -> tuple[BuiltArchive, InstallResult]:
    """Build a draft and install it into the user store in one shot (the wizard's "Save and install").

    Save-As over an existing package only carries real source bytes for the
    template the user actively edited; every other template comes through
    with the STARTER_CODE placeholder. Read the unedited templates' real
    source from disk before the rebuild so we don't clobber them, and build
    onto the installed package so what the draft does not model survives.
    A new package whose node loads a model is that model's copy
    (:func:`model_source_for_draft`).
    FactoryError / InstallerError propagate for the route to answer.
    """
    packages_provisioning.assert_may_install()
    refuse_read_only_draft(user_key, draft.get("manifest"))
    with packages_store_install.staging_scratch(user_key) as folder:
        built = _build_into(user_key, draft, folder)
        with open(built.path, "rb") as stream:
            result = packages_store_install.install_package_from_archive(user_key, stream, replace=replace)
    return built, result
