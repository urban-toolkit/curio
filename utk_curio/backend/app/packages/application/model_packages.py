"""Where a model package's weights are read from: for a node's ``curio_load_model`` and for an export.

A model package (kind ``model``) ships its weights under ``models/``, and its
``model`` block names the one a node runs (``domain/model_block.py``). The
weights are read where they are:

- a package imported or published into a user's store holds its own;
- a user's copy of a shipped package holds none (``seeding``,
  ``store_install.install_package_from_directory``), so they are read from the
  shared catalog's copy, ``packages/<dir>/models/``;
- on a pip install, a weight the pip package leaves out
  (``datasets/infrastructure/left_out_files.py``) is downloaded the first
  time it is needed into ``.curio/fetched/<commit>/packages/<dir>/``, checked
  against the release's record and against the package's ``integrity.json``.

``curio_load_model("<id>")`` names a package id, ``<id>@<major>`` one major.
The user's store answers before the catalog, the highest major of each.

The Model Catalog lists the model packages one account can run
(:func:`list_model_packages`): the catalog's, and those imported or published
into the account's store.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.domain.manifest import ManifestError, PackageManifest
from utk_curio.backend.app.packages.domain.model_block import MODELS_DIR
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.repositories import catalog_dir as packages_catalog_dir
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.store import list_user_packages

log = logging.getLogger(__name__)


class ModelWeightsUnavailable(PackageServiceError):
    """A model package's weights could not be had: not in the copy, not in the
    catalog, or a download that failed. The message says which."""

    def __init__(self, message: str) -> None:
        super().__init__(message, 502)


def _model_manifest(folder: Path) -> PackageManifest | None:
    """The manifest of the model package in *folder*, or None for a node
    package, a missing folder or one that cannot be read."""
    try:
        manifest = load_package_manifest(folder)
    except (ManifestError, OSError, ValueError):
        return None
    return manifest if manifest.kind == "model" and manifest.model is not None else None


def is_model_package(folder: Path) -> bool:
    """Whether *folder* holds a model package (manifest kind ``model``)."""
    return _model_manifest(folder) is not None


def holds_weights(folder: Path, manifest: PackageManifest) -> bool:
    """Whether *folder* holds the entry *manifest*'s model block names."""
    entry = folder / manifest.model.entry
    if manifest.model.runtime == "transformers":
        return (entry / "config.json").is_file()
    return entry.is_file()


def _highest(folders, want_id: str, want_major: str) -> tuple[PackageManifest, Path] | None:
    found = []
    for folder in folders:
        name = folder.name
        if want_major and name != f"{want_id}@{want_major}":
            continue
        if not want_major and not name.startswith(f"{want_id}@"):
            continue
        manifest = _model_manifest(folder)
        if manifest is not None and manifest.package_id == want_id:
            found.append((manifest, folder))
    return max(found, key=lambda pair: pair[0].major, default=None)


def find_model_package(user_key: str | None, model_id: str) -> tuple[PackageManifest, Path] | None:
    """The model package *model_id* names (``<id>`` or ``<id>@<major>``): the
    user's copy before the catalog's, the highest major of each. A lock
    owner: it reads the user's store under the seed lock (memo dev/99)."""
    want_id, _, want_major = str(model_id).partition("@")
    if want_major and not want_major.isdigit():
        return None
    if user_key:
        with package_seed_lock(user_key):
            mine = _highest(list_user_packages(user_key), want_id, want_major)
        if mine is not None:
            return mine
    root = packages_catalog_dir.catalog_root()
    if not root.is_dir():
        return None
    shipped = sorted(entry for entry in root.iterdir() if entry.is_dir() and PACKAGE_DIR_RE.match(entry.name))
    return _highest(shipped, want_id, want_major)


@dataclass(frozen=True)
class ListedModelPackage:
    """A model package one account can run, as the Model Catalog lists it.

    *folder* is where its manifest is read: the account's copy when that copy
    holds its own weights (imported or published), else the catalog's.
    *in_store* says which: an account's own model package, which it may
    remove, or one that ships with Curio."""

    manifest: PackageManifest
    folder: Path
    in_store: bool


def list_model_packages(user_key: str | None) -> list[ListedModelPackage]:
    """Every model package *user_key* can run, once per ``<id>@<major>``:
    those in the account's store that hold their own weights, then the
    catalog's. A user's copy of a catalog package holds none (seeded for the
    examples, or added), so the catalog's is the one listed. A weight a pip
    install has not fetched yet is not needed to list it. A lock owner: it
    reads the user's store under the seed lock, as :func:`find_model_package`
    does."""
    listed: dict[str, ListedModelPackage] = {}
    if user_key:
        with package_seed_lock(user_key):
            for folder in list_user_packages(user_key):
                manifest = _model_manifest(folder)
                if manifest is not None and holds_weights(folder, manifest):
                    listed[folder.name] = ListedModelPackage(manifest, folder, True)
    root = packages_catalog_dir.catalog_root()
    if root.is_dir():
        for folder in sorted(entry for entry in root.iterdir() if entry.is_dir() and PACKAGE_DIR_RE.match(entry.name)):
            if folder.name in listed:
                continue
            manifest = _model_manifest(folder)
            if manifest is not None:
                listed[folder.name] = ListedModelPackage(manifest, folder.resolve(), False)
    return list(listed.values())


def _integrity(folder: Path) -> dict[str, str]:
    try:
        listed = json.loads((folder / "integrity.json").read_text(encoding="utf-8")).get("sha256")
    except (OSError, ValueError, AttributeError):
        return {}
    return listed if isinstance(listed, dict) else {}


def _fetched(dir_name: str, shipped: Path) -> Path | None:
    """The folder a pip install downloads the catalog copy's left-out weights
    into, each downloaded now if it is not there yet, or None when none of its
    weights is left out. Raises ``LeftOutFileUnavailable``, which the node's
    run reports (``left_out_files.failures``)."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    prefix = f"packages/{dir_name}/"
    missing = [
        repo_path for repo_path in left_out_files.left_out_paths()
        if repo_path.startswith(f"{prefix}{MODELS_DIR}/") and not (shipped / repo_path[len(prefix):]).exists()
    ]
    if not missing:
        return None
    integrity = _integrity(shipped)
    folder = None
    for repo_path in missing:
        rel = repo_path[len(prefix):]
        placed = left_out_files.fetch(repo_path, shipped / rel, expected_sha256=integrity.get(rel))
        folder = placed
        for _part in PurePosixPath(rel).parts:
            folder = folder.parent
    return folder


def weights_folder(manifest: PackageManifest, folder: Path) -> Path | None:
    """The folder whose ``models/`` holds the weights of the model package
    *manifest* in *folder*: *folder* itself when it holds them, else the
    catalog's copy of the same package, else the folder a pip install fetches
    that copy's left-out weights into. None when none of them has them."""
    if holds_weights(folder, manifest):
        return folder
    shipped = packages_catalog_dir.catalog_root() / manifest.dir_name
    catalog_manifest = _model_manifest(shipped)
    if catalog_manifest is None or catalog_manifest.model.entry != manifest.model.entry:
        return None
    if holds_weights(shipped, catalog_manifest):
        return shipped.resolve()
    fetched = _fetched(manifest.dir_name, shipped)
    if fetched is None or not holds_weights(fetched, catalog_manifest):
        return None
    return fetched


def resolve_model_dirs(user_key: str | None, model_ids) -> dict[str, str]:
    """``{model id: folder}`` for the model packages *model_ids* name that
    *user_key* can use: the folder whose ``manifest.json`` and ``models/`` a
    node's ``curio_load_model`` reads. An id that names no model package, or
    whose weights cannot be had, is left out: the sandbox's ``curio_load_model``
    names it, or the run fails with the download's own error."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    out: dict[str, str] = {}
    for model_id in model_ids:
        try:
            found = find_model_package(user_key, model_id)
            if found is None:
                continue
            weights = weights_folder(*found)
        except left_out_files.LeftOutFileUnavailable:
            continue
        except (ManifestError, OSError, ValueError) as exc:
            log.warning("model package %s could not be resolved: %s", model_id, exc)
            continue
        if weights is not None:
            out[str(model_id)] = str(weights)
    return out


def export_weights_folder(source: Path) -> Path | None:
    """The folder an export of *source* takes its weights from, when *source*
    is a model package that does not hold them (a user's copy of a shipped
    one): downloaded first on a pip install. None for a node package or one
    that holds its weights. Raises :class:`ModelWeightsUnavailable`."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    manifest = _model_manifest(source)
    if manifest is None or holds_weights(source, manifest):
        return None
    try:
        weights = weights_folder(manifest, source)
    except left_out_files.LeftOutFileUnavailable as exc:
        raise ModelWeightsUnavailable(str(exc)) from exc
    if weights is None:
        raise ModelWeightsUnavailable(
            f"{manifest.dir_name} cannot be exported: its weights ({manifest.model.entry}) are "
            "neither in your copy nor in the catalog"
        )
    return weights
