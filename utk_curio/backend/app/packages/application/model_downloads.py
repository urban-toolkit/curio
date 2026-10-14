"""A model downloaded from the Discovery Catalog, added to a user's store as a model package.

The Discovery Catalog's model source (Hugging Face) fetches a model's files;
here they become a model package (kind ``model``) of the user's own, as an
import makes one: the files under ``models/``, and a manifest with the model's
``model`` block and the node Curio writes for its type
(``domain/default_cells.py``). It is installed through the store's archive
install, weights and all, so it is checked, hashed and capped as every package
is, and its libraries install by the packages' own path.

Its id is ``imported.x<hex>``. A refresh installs over the package it
replaces, under the same id, so a node naming it runs the new files.

The Discovery Catalog asks here whether an account already holds a source
row's model (:func:`downloaded_model_package`), whether it may add one, and
what to tell a client about the package it added (:func:`model_package_row`).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from utk_curio.backend.app.packages.application import model_packages as packages_model_packages
from utk_curio.backend.app.packages.application import provisioning as packages_provisioning
from utk_curio.backend.app.packages.application import store_install as packages_store_install
from utk_curio.backend.app.packages.domain.manifest import PackageManifest
from utk_curio.backend.app.packages.domain.model_block import MODELS_DIR
from utk_curio.backend.app.packages.repositories.archive import zip_package_tree_to
from utk_curio.backend.app.users.capabilities import install_refusal, package_install_refusal


def install_downloaded_model(
    user_key: str, files: Path, manifest: dict, *, replace: bool = False,
) -> PackageManifest:
    """Add the model whose files are in *files*, which is consumed, to
    *user_key*'s store: they become the package's ``models/``, and *manifest*
    (a model package's, whose ``model.entry`` names a file or folder under
    ``models/``) its manifest. *replace* installs over a package of the same
    id, as a refresh does. Returns the installed manifest; raises
    ``InstallerError`` for what the archive install refuses."""
    with packages_store_install.staging_scratch(user_key) as scratch:
        root = scratch / "package"
        root.mkdir()
        shutil.move(str(files), str(root / MODELS_DIR))
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        zipped = zip_package_tree_to(root, scratch / "package.curio.zip")
        shutil.rmtree(root)
        with open(zipped, "rb") as stream:
            result = packages_store_install.install_package_from_archive(user_key, stream, replace=replace)
    return result.manifest


def install_downloaded_model_deps(user_key: str, manifest: PackageManifest) -> dict:
    """Install the libraries the downloaded model package *manifest* declares,
    as a sideloaded package's install: reported, not raised
    (``provisioning.provision_declared_deps``)."""
    return packages_provisioning.provision_declared_deps(user_key, manifest.dir_name, manifest)


def model_package_row(manifest: PackageManifest) -> dict:
    """What the Discovery Catalog tells a client about a model package it
    added: its id (the Model Catalog's link to it), folder, name and the
    libraries it declares. Never a path on this machine."""
    return {
        "id": manifest.package_id,
        "dirName": manifest.dir_name,
        "name": manifest.name,
        "dependencies": sorted(manifest.python_deps),
    }


def _downloaded(user_key: str | None, source_id: str):
    """The model packages *user_key* downloaded from the source *source_id*,
    each with the resource it came from."""
    for held in packages_model_packages.held_model_packages(user_key):
        source = held.manifest.model.discovery_source or {}
        if held.in_store and source.get("sourceId") == source_id and source.get("resourceId"):
            yield str(source["resourceId"]), held.manifest


def downloaded_model_ids(user_key: str | None, source_id: str) -> dict[str, str]:
    """``{resource id: model id}`` for every model *user_key* downloaded from
    the source *source_id*: the rows its search marks as held."""
    return {resource: manifest.package_id for resource, manifest in _downloaded(user_key, source_id)}


def downloaded_model_package(user_key: str | None, source_id: str, resource_id: str) -> dict | None:
    """The row of the model package *user_key* downloaded from *resource_id* of
    the source *source_id*, or None when it holds none."""
    for resource, manifest in _downloaded(user_key, source_id):
        if resource == resource_id:
            return model_package_row(manifest)
    return None


def model_add_refusal(user) -> str | None:
    """Why *user* may not add a model, or None: the rule a package install
    follows. A guest on a ``--deploy`` instance may not, because every guest
    shares one account and its disk (#623)."""
    return install_refusal(user, noun="models")


def model_library_refusal(user) -> str | None:
    """Why *user* may not install the libraries a model's runtime needs, or
    None: the reason a package's own would be refused."""
    return package_install_refusal(user)
