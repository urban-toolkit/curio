"""Where a model package's weights are read from: for a node's ``curio_load_model`` and for an export.

A model package (kind ``model``) ships its weights under ``models/``, and its
``model`` block names the one a node runs (``domain/model_block.py``). Models
behave like nodes: ``curio_load_model("<id>")`` finds only a model package in
the user's store, added (Add, or a dataflow whose lockfile names it) or seeded
for the examples, the highest major of it; ``<id>@<major>`` names one major.
A package the store does not hold gives the node no model, and the sandbox's
``curio_load_model`` says to add it. The weights are read where they are:

- a package imported, published or downloaded into a user's store holds its
  own;
- a user's copy of a shipped package holds none (``seeding``,
  ``store_install.install_package_from_directory``), so they are read from the
  shared catalog's copy, ``packages/<dir>/models/``;
- on a pip install, a weight the pip package leaves out
  (``datasets/infrastructure/left_out_files.py``) is downloaded the first
  time it is needed into ``.curio/fetched/<commit>/packages/<dir>/``, checked
  against the release's record and against the package's ``integrity.json``;
- weights a package's operator fetches (its model block's ``fetch``,
  ``domain/model_fetch.py``) are in neither git nor the pip package:
  ``scripts/fetch_model_weights.py`` puts them in the catalog's copy of the
  package, or under the folder ``--model-weights-dir`` names, where a node
  reads them in place (:func:`fetched_weights_folder`). Without them the
  model still resolves, so its node says how to fetch them; and Export,
  Publish and Save as package node refuse it (:func:`refuse_fetched_weights`).

The Model Catalog lists the model packages through the package listings,
filtered to kind ``model``; each says whether its weights download on first use
(:func:`weights_on_first_use`) or still wait to be fetched
(:func:`weights_not_fetched`), and the text of its weights' license is served
from the account's copy or the catalog's (:func:`weights_license_text`). A
model downloaded from the Discovery Catalog becomes a model package in the
user's store (``model_downloads``). A template that ships no ``source`` opens
with the cell Curio writes for its model's type (:func:`model_default_cell`).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from utk_curio.backend.app.packages.domain.default_cells import CONCEPT_SEGMENTATION, SEGMENTATION, default_cell
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.domain.manifest import ManifestError, PackageManifest
from utk_curio.backend.app.packages.domain.model_block import MODELS_DIR
from utk_curio.backend.app.packages.domain.model_fetch import fetched_root
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.repositories import catalog_dir as packages_catalog_dir
from utk_curio.backend.app.packages.repositories.archive import is_non_content_filename
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.store import list_user_packages, package_dir

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
    """Whether *folder* holds the entry *manifest*'s model block names: for
    weights its operator fetches, every file its ``fetch`` lists."""
    entry = folder / manifest.model.entry
    if manifest.model.fetch is not None:
        return all((entry / item.path).is_file() for item in manifest.model.fetch.files)
    if manifest.model.runtime == "transformers":
        return (entry / "config.json").is_file()
    return entry.is_file()


def fetched_weights_folder(manifest: PackageManifest, shipped: Path) -> Path | None:
    """Where this Curio reads the weights the catalog's model package
    *manifest*, in *shipped*, has its operator fetch (its model block's
    ``fetch``): the package's folder under ``--model-weights-dir`` when that
    flag is set, else *shipped* itself, each laid out as the package is, its
    entry under it. None while that folder lacks a file the block lists:
    before ``scripts/fetch_model_weights.py`` ran, or after a fetch that
    stopped."""
    weights_dir = packages_catalog_dir.model_weights_dir()
    folder = shipped if weights_dir is None else fetched_root(weights_dir, manifest.package_id, manifest.major)
    return folder if holds_weights(folder, manifest) else None


@dataclass(frozen=True)
class ListedModelPackage:
    """A model package one account can add or run, as the Model Catalog lists it.

    *folder* is where its manifest is read: the account's copy when that copy
    holds its own weights (imported, published or downloaded), else the
    catalog's. *in_store* says which: an account's own model package, which it
    may remove, or one that ships with Curio."""

    manifest: PackageManifest
    folder: Path
    in_store: bool


def held_model_packages(user_key: str | None) -> list[ListedModelPackage]:
    """The model packages in *user_key*'s store, the only ones its nodes run:
    each one's copy as *folder*, and *in_store* when the copy holds its own
    weights rather than reading a shipped package's in place. None without an
    account. A lock owner: it reads the user's store under the seed lock
    (memo dev/99)."""
    if not user_key:
        return []
    held: list[ListedModelPackage] = []
    with package_seed_lock(user_key):
        for folder in list_user_packages(user_key):
            manifest = _model_manifest(folder)
            if manifest is not None:
                held.append(ListedModelPackage(manifest, folder, holds_weights(folder, manifest)))
    return held


def find_model_package(user_key: str | None, model_id: str) -> tuple[PackageManifest, Path] | None:
    """The model package *model_id* names (``<id>`` or ``<id>@<major>``) in
    *user_key*'s store, the highest major of it, or None: a model the store
    does not hold is not run, as a node whose package is not added is not.
    Chosen from the snapshot :func:`held_model_packages` reads under the lock."""
    want_id, _, want_major = str(model_id).partition("@")
    if want_major and not want_major.isdigit():
        return None
    wanted = f"{want_id}@{want_major}" if want_major else None
    found = [
        (held.manifest, held.folder) for held in held_model_packages(user_key)
        if held.manifest.package_id == want_id and held.folder.name == (wanted or held.manifest.dir_name)
    ]
    return max(found, key=lambda pair: pair[0].major, default=None)


def list_model_packages(user_key: str | None) -> list[ListedModelPackage]:
    """Every model package *user_key* can add or run, once per
    ``<id>@<major>``: those in the account's store that hold their own
    weights, then the catalog's. A user's copy of a catalog package holds none
    (seeded for the examples, or added), so the catalog's is the one listed. A
    weight a pip install has not fetched yet is not needed to list it."""
    listed: dict[str, ListedModelPackage] = {
        held.folder.name: held for held in held_model_packages(user_key) if held.in_store
    }
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
        for _ in PurePosixPath(rel).parts:
            folder = folder.parent
    return folder


def weights_folder(manifest: PackageManifest, folder: Path) -> Path | None:
    """The folder whose ``models/`` holds the weights of the model package
    *manifest* in *folder*: *folder* itself when it holds them, else the
    catalog's copy of the same package, else the folder a pip install fetches
    that copy's left-out weights into, or, for weights its operator fetches,
    :func:`fetched_weights_folder`. None when none of them has them."""
    if holds_weights(folder, manifest):
        return folder
    shipped = packages_catalog_dir.catalog_root() / manifest.dir_name
    catalog_manifest = _model_manifest(shipped)
    if catalog_manifest is None or catalog_manifest.model.entry != manifest.model.entry:
        return None
    if catalog_manifest.model.fetch is not None:
        return fetched_weights_folder(catalog_manifest, shipped.resolve())
    if holds_weights(shipped, catalog_manifest):
        return shipped.resolve()
    fetched = _fetched(manifest.dir_name, shipped)
    if fetched is None or not holds_weights(fetched, catalog_manifest):
        return None
    return fetched


def local_weights_folder(manifest: PackageManifest, folder: Path) -> Path | None:
    """:func:`weights_folder` without the download: *folder* when it holds the
    weights, else the catalog's copy of the same package when that does (or,
    for weights its operator fetches, :func:`fetched_weights_folder`), else
    None."""
    if holds_weights(folder, manifest):
        return folder
    shipped = packages_catalog_dir.catalog_root() / manifest.dir_name
    catalog_manifest = _model_manifest(shipped)
    if catalog_manifest is None or catalog_manifest.model.entry != manifest.model.entry:
        return None
    if catalog_manifest.model.fetch is not None:
        return fetched_weights_folder(catalog_manifest, shipped.resolve())
    return shipped.resolve() if holds_weights(shipped, catalog_manifest) else None


def weights_on_first_use(manifest: PackageManifest, folder: Path) -> bool:
    """Whether a node's first run downloads the weights of the model package
    *manifest* in *folder*: neither the folder nor the catalog's copy holds
    them, because a pip install leaves them out, and none has been fetched
    yet. Nothing is downloaded to say so."""
    if local_weights_folder(manifest, folder) is not None:
        return False
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    prefix = f"packages/{manifest.dir_name}/{MODELS_DIR}/"
    left_out = [repo_path for repo_path in left_out_files.left_out_paths() if repo_path.startswith(prefix)]
    if not left_out:
        return False
    try:
        record = left_out_files.read_record()
    except ValueError:
        record = None
    if record is None:
        return True
    root = left_out_files.fetched_root(record.commit)
    return not all((root / repo_path).is_file() for repo_path in left_out)


def weights_not_fetched(manifest: PackageManifest, folder: Path) -> bool:
    """Whether the model package *manifest* in *folder* has its operator fetch
    its weights (its model block's ``fetch``) and this Curio does not have
    them yet: a node that loads it stops, naming
    ``scripts/fetch_model_weights.py``. Nothing is fetched to say so."""
    return manifest.model.fetch is not None and local_weights_folder(manifest, folder) is None


#: Why Export, Publish and Save as package node refuse a model package whose
#: weights its operator fetches, after what was refused.
FETCHED_WEIGHTS_REFUSED = (
    "{refused}: its weights come from {publisher} under their terms, and may be larger than the "
    "2 GiB a package carries. Whoever runs a Curio fetches them for it with scripts/fetch_model_weights.py."
)


def refuse_fetched_weights(manifest: PackageManifest | None, refused: str) -> None:
    """Raise a 409 that says why when *manifest* is a model package whose
    weights its operator fetches: they never travel in an archive. *refused*
    says what was refused, ``{name}`` standing for the package's name."""
    if manifest is None or manifest.model is None or manifest.model.fetch is None:
        return
    raise PackageServiceError(
        FETCHED_WEIGHTS_REFUSED.format(
            refused=refused.format(name=manifest.name or manifest.dir_name),
            publisher=manifest.model.publisher or f"Hugging Face ({manifest.model.fetch.huggingface})",
        ),
        409,
    )


def refuse_fetched_weights_in(folder: Path, refused: str) -> None:
    """:func:`refuse_fetched_weights` for the package in *folder*."""
    refuse_fetched_weights(_model_manifest(folder), refused)


def weights_license_text(user_key: str, dir_name: str) -> str:
    """The text of the weights license of the model package *dir_name* (its
    model block's ``licenseFile``): from *user_key*'s copy when it holds the
    file, else from the catalog's. A 404 for a node package, for weights with
    no license file, and for a package neither holds."""
    if not PACKAGE_DIR_RE.match(str(dir_name)):
        raise PackageServiceError(f"no package {dir_name!r}", 404)
    for folder in (package_dir(user_key, dir_name), packages_catalog_dir.catalog_root() / dir_name):
        manifest = _model_manifest(folder)
        if manifest is None or not manifest.model.license_file:
            continue
        path = (folder / manifest.model.license_file).resolve()
        if path.is_file() and folder.resolve() in path.parents:
            return path.read_text(encoding="utf-8", errors="replace")
    raise PackageServiceError(f"{dir_name} has no weights license text", 404)


def _graph_inputs(manifest: PackageManifest, folder: Path):
    """The arrays the ONNX graph of the model package in *folder* takes, read
    from weights already on this machine (``datasets.domain.onnx_model``), or
    None."""
    if manifest.model.runtime != "onnx":
        return None
    weights = local_weights_folder(manifest, folder)
    if weights is None:
        return None
    from utk_curio.backend.app.datasets.domain.onnx_model import graph_inputs

    graph = weights / manifest.model.entry
    try:
        with graph.open("rb") as handle:
            return graph_inputs(handle, graph.stat().st_size)
    except OSError:
        return None


def model_default_cell(manifest: PackageManifest, folder: Path) -> str:
    """The cell a node of the model package *manifest* in *folder* opens with
    when its template ships no ``source`` (``domain/default_cells.py``): a
    segmentation model's runs as it is; a concept segmentation model's names
    its prompts and its checkpoint; another type's is a ``model.run``
    skeleton naming the arrays its graph takes. Nothing is downloaded for it."""
    block = manifest.model
    inputs = None if block.type in (SEGMENTATION, CONCEPT_SEGMENTATION) else _graph_inputs(manifest, folder)
    return default_cell(manifest.package_id, block.type, inputs)


def _used_by_the_dataflow(owners, model_id: str) -> bool:
    """Whether the model package *model_id* names in the dataflow owner's
    store (*owners*, ``project_packages.OwnersPackages``), as
    :func:`find_model_package` picks it there, is one the dataflow uses."""
    try:
        found = find_model_package(owners.store_key, model_id)
        return found is not None and owners.uses(found[1].name)
    except Exception as exc:  # noqa: BLE001 - the run's own store still answers
        log.warning("Could not read whether dataflow %s uses model %s: %s", owners.project_id, model_id, exc)
        return False


@dataclass(frozen=True)
class ResolvedModel:
    """Where a node's ``curio_load_model`` reads one model: *folder* holds its
    manifest and, unless *weights* says otherwise, its weights under
    ``models/``. *weights* is the folder under ``--model-weights-dir`` whose
    entry holds weights its operator fetched, which the sandbox reads in
    place, never staged."""

    folder: Path
    weights: Path | None = None


def _resolved(manifest: PackageManifest, folder: Path) -> ResolvedModel | None:
    """Where the model package *manifest*, the store's copy in *folder*, is
    read from, or None when its weights cannot be had. A package whose weights
    its operator fetches resolves to the catalog's copy even without them, so
    its node says how to fetch them rather than to add it."""
    if manifest.model.fetch is None:
        weights = weights_folder(manifest, folder)
        return None if weights is None else ResolvedModel(weights)
    if holds_weights(folder, manifest):
        return ResolvedModel(folder)
    shipped = (packages_catalog_dir.catalog_root() / manifest.dir_name).resolve()
    catalog_manifest = _model_manifest(shipped)
    if catalog_manifest is None or catalog_manifest.model.fetch is None:
        return ResolvedModel(folder)
    if catalog_manifest.model.entry != manifest.model.entry:
        return None
    weights = fetched_weights_folder(catalog_manifest, shipped)
    return ResolvedModel(shipped, None if weights in (None, shipped) else weights)


def _resolve_models(user_key: str | None, model_ids, owners) -> dict[str, ResolvedModel]:
    """``{model id: ResolvedModel}`` for the model packages *model_ids* name
    that *user_key*'s store holds (:func:`resolve_model_dirs`)."""
    if owners is not None:
        ids = [str(model_id) for model_id in model_ids]
        theirs = [model_id for model_id in ids if _used_by_the_dataflow(owners, model_id)]
        return {
            **_resolve_models(user_key, [model_id for model_id in ids if model_id not in theirs], None),
            **_resolve_models(owners.store_key, theirs, None),
        }
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    out: dict[str, ResolvedModel] = {}
    for model_id in model_ids:
        try:
            found = find_model_package(user_key, model_id)
            if found is None:
                continue
            resolved = _resolved(*found)
        except left_out_files.LeftOutFileUnavailable:
            continue
        except (ManifestError, OSError, ValueError) as exc:
            log.warning("model package %s could not be resolved: %s", model_id, exc)
            continue
        if resolved is not None:
            out[str(model_id)] = resolved
    return out


def resolve_model_dirs(user_key: str | None, model_ids, *, owners=None) -> dict[str, str]:
    """``{model id: folder}`` for the model packages *model_ids* name that
    *user_key*'s store holds: the folder whose ``manifest.json`` and
    ``models/`` a node's ``curio_load_model`` reads. An id that names no model
    package in the store, or whose weights cannot be had, is left out: the
    sandbox's ``curio_load_model`` says to add it, or the run fails with the
    download's own error. A package whose weights its operator fetches gives
    the catalog's copy, whose manifest says what to fetch, with or without
    them; :func:`resolve_model_weights` names where they are read in place.

    With *owners* (``project_packages.OwnersPackages``), the run is one of an
    editor the dataflow's owner invited: an id whose model package in her
    store the dataflow uses resolves from her store, as her own run's does,
    and any other id from *user_key*'s."""
    return {model_id: str(model.folder) for model_id, model in _resolve_models(user_key, model_ids, owners).items()}


def resolve_model_weights(user_key: str | None, model_ids, *, owners=None) -> dict[str, str]:
    """``{model id: folder}`` for the models of :func:`resolve_model_dirs`
    whose weights its operator fetched under ``--model-weights-dir``: the
    folder whose entry holds them, which a node reads in place. Empty without
    that flag, whose weights are in the folder :func:`resolve_model_dirs`
    gives."""
    return {
        model_id: str(model.weights)
        for model_id, model in _resolve_models(user_key, model_ids, owners).items()
        if model.weights is not None
    }


def export_weights_folder(source: Path) -> Path | None:
    """The folder an export of *source* takes its weights from, when *source*
    is a model package that does not hold them (a user's copy of a shipped
    one): downloaded first on a pip install. None for a node package or one
    that holds its weights. Raises :class:`ModelWeightsUnavailable`, and a
    409 for a package whose weights its operator fetches
    (:func:`refuse_fetched_weights`), which never leave this Curio."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    manifest = _model_manifest(source)
    refuse_fetched_weights(manifest, "{name} cannot be exported")
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


def model_copy(user_key: str | None, model_id: str) -> tuple[dict, dict[str, Path]] | None:
    """What a package that copies the model *model_id* takes from it (Save as
    package node of a node that loads it): its manifest as written, whose
    ``model`` block and libraries the copy declares, and its files by
    package-relative path, every file of ``models/`` where its weights are (a
    pip install's left-out weight downloaded first) and its weights' license
    file. None when *user_key*'s store holds no such model, as a node's run
    finds none. Raises :class:`ModelWeightsUnavailable`, and a 409 for a
    model whose weights its operator fetches (:func:`refuse_fetched_weights`)."""
    found = find_model_package(user_key, model_id)
    if found is None:
        return None
    manifest, folder = found
    refuse_fetched_weights(manifest, "A node that loads {name} cannot be saved as a package")
    weights = folder if holds_weights(folder, manifest) else export_weights_folder(folder)
    raw = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    files: dict[str, Path] = {
        path.relative_to(weights).as_posix(): path
        for path in sorted((weights / MODELS_DIR).rglob("*"))
        if path.is_file() and not is_non_content_filename(path.name)
    }
    license_file = manifest.model.license_file
    if license_file:
        for base in (weights, folder):
            candidate = base / license_file
            if candidate.is_file():
                files[license_file] = candidate
                break
    return raw, files
