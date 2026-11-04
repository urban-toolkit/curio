"""An invited editor's own dataset, asked of the dataflow's owner: the ``datasets`` kind of request.

The requests and their review are ``projects/editor_requests.py``'s; this
module says what a request for a dataset asks and what the owner's Apply of
it does. An editor's drop of a file, his Add to project and his drag of a card
of his Data Catalog onto her dataflow each ask her (:func:`asked`), as a
``dataset.install`` of ``src/contracts/agentInstalls.json``:

* a dataset or a layer group of his Data Catalog: her Apply (:func:`apply`)
  copies its folders from his store into hers, unless hers holds them already,
  and adds it to the dataflow as her Add to project does: her own change, so
  her editors' runs then read it from her store;
* a collection of his Data Catalog: the same, its files coming with its index.
  A collection of a folder on this machine is read where the folder is, and
  one of a bucket or a service reads the copies of its files his media cache
  holds (``discovery/application/cache_collection.py``), which her Apply copies
  into hers, within her cache's bound;
* a dataset of the shared Data Catalog needs no copy: his Add to project of one
  asks her to add it, and his drop of one asks nothing, since every account's
  runs read the shared catalog.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.domain.constants import is_layer_group_id
from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError
from utk_curio.backend.app.projects.editor_requests import Asked

logger = logging.getLogger(__name__)

#: The install tool of the review a request is (``agentInstalls.json``).
TOOL = "dataset.install"
#: The request's field naming the dataset, and its name.
ITEM = "datasetId"
NAME = "datasetName"
#: What a refusal calls the items of this kind.
ITEMS = "datasets"
#: What the owner is told who asks herself.
OWNERS_OWN = "You own this dataflow: add the dataset to it with Add to project."
NOT_FOUND = "Dataset not found"


# ---------------------------------------------------------------------------
# What a request asks for
# ---------------------------------------------------------------------------

def _own_folders(user_key: str, dataset_id: str) -> tuple[list[Any], bool]:
    """The rows of the dataset index of the store *user_key* that hold
    *dataset_id*: its folder, or for a layer group each layer's; and whether
    one of them is a collection."""
    from utk_curio.backend.app.datasets.repositories import index as index_repo

    rows = list(index_repo.safe_sync_rows_by_dir(user_key).values())
    if is_layer_group_id(dataset_id):
        held = [row for row in rows if row.group_id == dataset_id]
    else:
        held = [row for row in rows if row.dataset_id == dataset_id]
    collection = any(row.collection_json or row.format == "collection" for row in held)
    return held, collection


def _shared_item(dataset_id: str) -> dict[str, Any] | None:
    """The shared catalog's dataset *dataset_id*, which every account reads,
    or None."""
    from utk_curio.backend.app.datasets.repositories.local import LocalDatasetRepository
    from utk_curio.backend.app.datasets.repositories.registry import DatasetRegistryRepository

    for repository in (DatasetRegistryRepository(), LocalDatasetRepository()):
        try:
            item = next((i for i in repository.list_items() if i.get("id") == dataset_id), None)
        except Exception:  # noqa: BLE001 - an unreadable catalog holds nothing to ask for
            logger.warning("the shared catalog could not be read for %s", dataset_id, exc_info=True)
            item = None
        if item is not None:
            return item
    return None


def _listed(flow, dataset_ids: list[str]) -> bool:
    """Whether the dataflow lists each of *dataset_ids* already, as the
    asker's listing of it reads its refs."""
    from utk_curio.backend.app.datasets.repositories.installed import InstalledDatasetRepository

    refs = InstalledDatasetRepository(flow.user).list_refs(flow.project_id)
    listed = {ref.get("datasetId") or ref.get("id") for ref in refs}
    return bool(dataset_ids) and all(dataset_id in listed for dataset_id in dataset_ids)


def asked(flow, dataset_id: str, *, add: bool) -> Asked:
    """What an editor's ask for *dataset_id* is for: one of his own Data
    Catalog, which he dropped as a file, dragged as a card or added with Add to
    project (*add*), a collection among them; or one of the shared catalog,
    asked for only by Add to project, since every account's runs read it. The
    answer says why nothing needs asking: the dataflow lists it already, or a
    drop of a shared one."""
    from utk_curio.backend.app.projects.services import _history_person

    folders, collection = _own_folders(flow.asker_key, dataset_id)
    if _listed(flow, [row.dataset_id for row in folders] if folders else [dataset_id]):
        return Asked(reason="listed")
    if folders:
        first = folders[0]
        title = (first.title or dataset_id) if not is_layer_group_id(dataset_id) else _group_title(folders, dataset_id)
        fmt = first.format if len(folders) == 1 else "layers"
        store: str | None = flow.asker_key
        where = f"from {_history_person(flow.user)['name']}'s Data Catalog"
    else:
        shared = _shared_item(dataset_id)
        if shared is None:
            raise DatasetCatalogError(NOT_FOUND, 404)
        if not add:
            # Every account's runs read the shared catalog: nothing to ask.
            return Asked(reason="shared")
        title = str(shared.get("title") or dataset_id)
        fmt = str(shared.get("format") or "")
        store = None
        where = "from the shared Data Catalog"
    noun = "collection" if collection else "dataset"
    return Asked(item=dataset_id, fields={
        "summary": f"Add {noun} · {title}",
        "preview": " · ".join(part for part in (title, (fmt or "").upper(), where) if part),
        "datasetName": title,
        "format": "collection" if collection else fmt,
        "shared": store is None,
        "store": store,
        "dirNames": [row.dir_name for row in folders],
    })


def _group_title(folders: list[Any], group_id: str) -> str:
    """A layer group's name: its layers' title before the layer, else its id."""
    titles = sorted({str(row.title or "") for row in folders if row.title})
    if not titles:
        return group_id
    first = titles[0]
    layer = next((row.layer_name for row in folders if row.title == first and row.layer_name), None)
    if layer and first.endswith(f" ({layer})"):
        return first[: -len(f" ({layer})")]
    return first


# ---------------------------------------------------------------------------
# The owner's Apply
# ---------------------------------------------------------------------------

def apply(flow, request: dict[str, Any]) -> dict[str, Any]:
    """The owner's Apply of a request for a dataset: its folders are copied
    from the asker's store into hers, unless hers holds them already, a
    collection's cached files with them, and the dataset is added to the
    dataflow as her Add to project adds it, as her change. What this Apply
    copied goes when the dataset cannot be added."""
    from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService

    store = str(request.get("store") or "")
    copied: list[Path] = []
    cached: list[Path] = []
    try:
        for dir_name in request.get("dirNames") or []:
            target = _copy(store, flow.owner_key, str(dir_name))
            if target is not None:
                copied.append(target)
        if store and request.get("format") == "collection":
            cached = _copy_cached_files(store, flow.owner_key, str(request["datasetId"]))
        item = DatasetCatalogService(flow.user).install_dataset(flow.project_id, str(request["datasetId"]))
    except Exception:
        for path in cached:
            path.unlink(missing_ok=True)
        for target in copied:
            _forget_copy(flow.owner_key, target)
        raise
    return {"installedDataset": {"id": item.get("id") or request["datasetId"],
                                 "name": request.get("datasetName") or item.get("title")}}


def refusal(exc: Exception) -> str | None:
    """Why an Apply that raised *exc* refused, in the words the owner is told;
    None for a fault that is no refusal."""
    from utk_curio.backend.app.discovery.domain.errors import DiscoveryError

    if isinstance(exc, DatasetCatalogError):
        return str(exc.args[0]) if exc.args else "the dataset could not be added"
    if isinstance(exc, (DiscoveryError, OSError, ValueError)):
        return str(exc)
    return None


def _copy(from_key: str, to_key: str, dir_name: str) -> Path | None:
    """Copy the dataset folder *dir_name* from the store *from_key* into the
    store *to_key*, whole or not at all, and index it there; None when that
    store holds it already. Raises when the first store no longer holds it."""
    from utk_curio.backend.app.datasets.domain.manifest import ManifestError, load_dataset_manifest
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir, user_datasets_dir
    from utk_curio.backend.app.datasets.repositories import index as index_repo

    if not from_key:
        raise DatasetCatalogError(NOT_FOUND, 404)
    source = dataset_dir(from_key, dir_name)
    try:
        load_dataset_manifest(source)
    except (ManifestError, OSError, ValueError) as exc:
        raise DatasetCatalogError("the dataset is no longer in the Data Catalog it was asked from", 409) from exc
    target = dataset_dir(to_key, dir_name)
    if (target / "manifest.json").is_file():
        return None
    user_datasets_dir(to_key).mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{dir_name}.{uuid.uuid4().hex[:8]}.copy")
    try:
        shutil.copytree(source, staging)
        os.replace(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    index_repo.safe_upsert_from_dir(to_key, target)
    return target


def _copy_cached_files(from_key: str, to_key: str, dataset_id: str) -> list[Path]:
    """Copy the files of the collection *dataset_id* that the media cache of
    the store *from_key* holds, a bucket's or a service's, into the cache of the
    store *to_key*, each one it does not hold yet, within that cache's bound
    (``cache_collection.check_room``), each handed to the node that reads it.
    A collection of a folder holds none: its files are read where they are.
    Returns the files copied."""
    from utk_curio.backend.app.discovery.application import cache_collection
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    source = cache_collection.objects_dir(from_key, dataset_id, create=False)
    if not source.is_dir():
        return []
    held = cache_collection.objects_dir(to_key, dataset_id, create=False)
    todo = [path for path in sorted(source.iterdir())
            if path.is_file() and not path.name.endswith(".part") and not (held / path.name).is_file()]
    if not todo:
        return []
    cache_collection.check_room(to_key, sum(path.stat().st_size for path in todo))
    target = cache_collection.objects_dir(to_key, dataset_id)
    copied: list[Path] = []
    try:
        for path in todo:
            final = target / path.name
            part = final.with_name(final.name + ".part")
            shutil.copyfile(path, part)
            os.replace(part, final)
            media_dirs.grant_to_child(final)
            copied.append(final)
    except BaseException:
        for path in copied:
            path.unlink(missing_ok=True)
        raise
    return copied


def _forget_copy(owner_key: str, target: Path) -> None:
    """Take back a copy an Apply made and could not add."""
    from utk_curio.backend.app.datasets.repositories import index as index_repo

    shutil.rmtree(target, ignore_errors=True)
    index_repo.safe_forget(owner_key, target.name)
