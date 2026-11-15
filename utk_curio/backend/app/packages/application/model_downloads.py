"""A model downloaded from the Discovery Catalog, added to a user's store as a model package.

The Discovery Catalog's model source (Hugging Face) fetches a model's files;
here they become a model package (kind ``model``) of the user's own, as an
import makes one: the files under ``models/``, and a manifest with the model's
``model`` block and the node its source's manifest names
(``provider.options.node``), a template of the shared catalog, which
:func:`model_node` reads: the template as its manifest holds it, its source
with each ``curio_load_model`` call naming the downloaded model, and the
packages its package names in ``dependencies.packages``, which the node's
code imports. A segmentation model so gets DDRNet23-Slim's Image Segmentation,
whose code calls the Segmentation package's ``segment_images``. It is
installed through the store's archive install, weights and all, so it is
checked, hashed and capped as every package is; the packages it names come
from the shared catalog, and its libraries install by the packages' own path
(:func:`install_downloaded_model_deps`).

Its id is ``imported.x<hex>``. A refresh installs over the package it
replaces, under the same id, so a node naming it runs the new files.

The Discovery Catalog asks here whether an account already holds a source
row's model (:func:`downloaded_model_package`), whether it may add one, and
what to tell a client about the package it added (:func:`model_package_row`).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from utk_curio.backend.app.packages.application import model_packages as packages_model_packages
from utk_curio.backend.app.packages.application import provisioning as packages_provisioning
from utk_curio.backend.app.packages.application import store_install as packages_store_install
from utk_curio.backend.app.packages.builder.factory import rename_model_calls
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.domain.manifest import ManifestError, PackageManifest
from utk_curio.backend.app.packages.domain.model_block import MODELS_DIR
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.domain.spec_packages import dir_name_from_node_type, is_package_node_type
from utk_curio.backend.app.packages.repositories import catalog_dir as packages_catalog_dir
from utk_curio.backend.app.packages.repositories.archive import zip_package_tree_to
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.users.capabilities import install_refusal, package_install_refusal


@dataclass(frozen=True)
class ModelNode:
    """The node of a downloaded model's package (:func:`model_node`)."""

    #: The template, as its package's manifest holds it, its ``source`` among it.
    template: dict
    #: The text of its source, whose ``curio_load_model`` calls name *model_id*.
    code: str
    #: The model the code names: the template's own package's.
    model_id: str
    #: Its package's ``dependencies.packages``, which the node's code imports.
    packages: dict = field(default_factory=dict)

    def code_for(self, model_id: str) -> str:
        """The node's code with every ``curio_load_model`` call naming *model_id*."""
        return rename_model_calls(self.code, self.model_id, model_id)


def model_node(node_type: object) -> ModelNode:
    """The node a Discovery source's manifest names for the models it adds
    (``provider.options.node``): the template *node_type* names in the shared
    catalog, ``<packageId>/<templateId>`` at the highest major the catalog
    holds, or ``@<major>`` for one, with its source and its package's
    ``dependencies.packages``. A ``PackageServiceError`` names what is
    missing: no node named, no such template, or one without a ``source``."""
    text = str(node_type or "").strip()
    if not is_package_node_type(text):
        raise PackageServiceError(
            "this source names no node for the models it adds: its manifest's provider.options.node "
            "names one, as <packageId>/<templateId>", 422,
        )
    package_id, _, template_id = text.partition("@")[0].partition("/")
    root = packages_catalog_dir.catalog_root()
    majors = [
        int(entry.name.rpartition("@")[2]) for entry in (root.iterdir() if root.is_dir() else [])
        if PACKAGE_DIR_RE.match(entry.name) and entry.name.rpartition("@")[0] == package_id
    ]
    dir_name = dir_name_from_node_type(text, {package_id: majors})
    try:
        folder = root / str(dir_name)
        load_package_manifest(folder)
        raw = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, ManifestError) as exc:
        raise PackageServiceError(f"the catalog has no package {package_id} for the node {text} its source names", 422) from exc
    template = next((t for t in raw.get("templates") or [] if isinstance(t, dict) and t.get("id") == template_id), None)
    source = template.get("source") if template is not None else None
    if not isinstance(source, str):
        raise PackageServiceError(f"the catalog's {folder.name} has no node {template_id} with code of its own", 422)
    path = (folder / PurePosixPath(source)).resolve()
    if folder.resolve() not in path.parents or not path.is_file():
        raise PackageServiceError(f"the source {source} of the node {text} is not in its package", 422)
    deps = raw.get("dependencies") if isinstance(raw.get("dependencies"), dict) else {}
    return ModelNode(
        template=json.loads(json.dumps(template)),
        code=path.read_text(encoding="utf-8"),
        model_id=package_id,
        packages=dict(deps.get("packages") or {}),
    )


def install_downloaded_model(
    user_key: str, files: Path, manifest: dict, *, sources: dict[str, str] | None = None, replace: bool = False,
) -> PackageManifest:
    """Add the model whose files are in *files*, which is consumed, to
    *user_key*'s store: they become the package's ``models/``, *manifest*
    (a model package's, whose ``model.entry`` names a file or folder under
    ``models/``) its manifest, and *sources* (``{package-relative path:
    text}``) the code its templates name. *replace* installs over a package
    of the same id, as a refresh does. Returns the installed manifest; raises
    ``InstallerError`` for what the archive install refuses."""
    with packages_store_install.staging_scratch(user_key) as scratch:
        root = scratch / "package"
        root.mkdir()
        shutil.move(str(files), str(root / MODELS_DIR))
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        for relative, text in (sources or {}).items():
            target = root / PurePosixPath(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        zipped = zip_package_tree_to(root, scratch / "package.curio.zip")
        shutil.rmtree(root)
        with open(zipped, "rb") as stream:
            result = packages_store_install.install_package_from_archive(user_key, stream, replace=replace)
    return result.manifest


def install_downloaded_model_deps(user_key: str, manifest: PackageManifest) -> dict:
    """Install what the downloaded model package *manifest* needs: each
    package it names in ``dependencies.packages`` that the store lacks, from
    the shared catalog, with that package's libraries (the Segmentation
    package, whose module its node's code imports), then the libraries it
    declares, as a sideloaded package's install: reported, not raised
    (``provisioning.provision_declared_deps``). A package that cannot be had
    is the report's ``dependencyError``."""
    try:
        brought = packages_store_install.bring_needed_packages(user_key, manifest.dir_name)
    except PackageServiceError as exc:
        report = packages_provisioning.provision_declared_deps(user_key, manifest.dir_name, manifest)
        return {**report, "dependencyError": str(exc)}
    report = packages_provisioning.provision_declared_deps(user_key, manifest.dir_name, manifest)
    if brought.import_errors:
        report["importErrors"] = {**brought.import_errors, **(report.get("importErrors") or {})}
    if brought.installed:
        libs = sorted({*brought.installed, *((report.get("restartRecommended") or {}).get("libs") or [])})
        report["restartRecommended"] = {"libs": libs}
    return report


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
