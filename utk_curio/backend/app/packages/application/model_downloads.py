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
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from utk_curio.backend.app.packages.application import provisioning as packages_provisioning
from utk_curio.backend.app.packages.application import store_install as packages_store_install
from utk_curio.backend.app.packages.domain.manifest import PackageManifest
from utk_curio.backend.app.packages.domain.model_block import MODELS_DIR
from utk_curio.backend.app.packages.repositories.archive import zip_package_tree_to


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
