"""An invited editor's own dataset, asked of the dataflow's owner.

An editor the owner of a dataflow invited (``projects/access.py``) changes the
dataflow as she does, but a dataset of his own Data Catalog is in his store:
her runs cannot read it, and only her own changes put a dataset in the lists
her editors' runs read (``collaboration/owner_uses.py``). So the editor's drop
of a file, his Add to project and his drag of a card of his own catalog onto
her dataflow ask her instead: each is a request in the owner's install review,
the review an install an agent asks for waits in, a ``dataset.install`` of
``src/contracts/agentInstalls.json`` shown on the same card.

* :func:`ask` keeps the request beside the dataflow's spec
  (:data:`REQUESTS_FILE`), which the doc does not carry and no tab writes. It
  writes nothing in the owner's store and nothing in the dataflow.
* :func:`apply`, the owner's alone, copies the dataset's folder from the
  editor's store into hers and adds it to the dataflow as her Add to project
  does: her own change, so her editors' runs then read it from her store.
* :func:`dismiss`, the owner's alone, drops the request and leaves nothing
  behind.

A dataset of the shared catalog needs no copy: the editor's Add to project of
one asks the owner to add it, and his drop of one asks nothing, since every
account reads the shared catalog. A collection is not asked for: its files
stay where the editor's store keeps them, which a copy of its index does not
bring. Each change is told to the dataflow's room (:data:`CHANGED_EVENT`), so
every tab reads the requests again.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.domain.constants import is_layer_group_id
from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

logger = logging.getLogger(__name__)

#: The requests of a dataflow, beside its spec.
REQUESTS_FILE = "dataset-requests.json"
#: The install tool of the review a request is (``agentInstalls.json``).
TOOL = "dataset.install"
#: What the dataflow's room is told after a request is made, applied or dismissed.
CHANGED_EVENT = "dataset_requests_changed"

#: What anyone but the owner and her editors is told who asks.
WATCHER_REFUSAL = "Only the owner and the editors the owner invited add datasets to this dataflow."
#: What the owner is told who asks herself.
OWNERS_OWN = "You own this dataflow: add the dataset to it with Add to project."
#: What an editor is told who asks for a collection.
COLLECTION_REFUSAL = (
    "A collection cannot be asked for: its files stay where your Data Catalog keeps them. "
    "Ask the dataflow's owner to add it from the Discovery Catalog."
)
NOT_FOUND = "Dataset not found"

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lock(project_id: str) -> threading.Lock:
    """The lock of one dataflow's requests: a read, a change and its write."""
    with _guard:
        return _locks.setdefault(project_id, threading.Lock())


# ---------------------------------------------------------------------------
# Who asks, and of whom
# ---------------------------------------------------------------------------

class _Dataflow:
    """The dataflow a request names, its owner's store and the asker's role."""

    def __init__(self, user, project_id: str):
        from utk_curio.backend.app.projects import access
        from utk_curio.backend.app.projects.models import Project
        from utk_curio.backend.app.projects.repositories import NotFoundError
        from utk_curio.backend.app.projects.services import _owner_user_dir_key
        from utk_curio.backend.extensions import db

        if user is None:
            raise DatasetCatalogError("Authorization required", 401)
        project = db.session.get(Project, project_id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        self.role = access.agents_role(user, project)
        if self.role not in access.EDIT_ROLES:
            raise DatasetCatalogError(WATCHER_REFUSAL, 403)
        self.user = user
        self.project = project
        self.project_id = project.id
        self.owner_key = _owner_user_dir_key(project)
        owner = project.owner
        self.owner_name = (owner.name or owner.username) if owner is not None else "the owner"

    @property
    def owner(self) -> bool:
        from utk_curio.backend.app.projects import access

        return self.role == access.OWNER


def _owners_alone(flow: _Dataflow) -> None:
    """Refuse an editor's Apply or Dismiss: a request waits for the owner's
    review, as an install an agent asks for does."""
    if flow.owner:
        return
    from utk_curio.backend.app.agents.service import owners_review

    raise DatasetCatalogError(owners_review(flow.owner_name), 403)


# ---------------------------------------------------------------------------
# The requests file
# ---------------------------------------------------------------------------

def _path(owner_key: str, project_id: str) -> Path:
    from utk_curio.backend.app.projects import storage

    return storage.project_dir(str(owner_key), project_id) / REQUESTS_FILE


def _read(owner_key: str, project_id: str) -> list[dict[str, Any]]:
    path = _path(owner_key, project_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        logger.warning("%s does not read; the dataflow holds no request", path, exc_info=True)
        return []
    held = data.get("requests") if isinstance(data, dict) else None
    return [entry for entry in held if isinstance(entry, dict)] if isinstance(held, list) else []


def _write(owner_key: str, project_id: str, requests: list[dict[str, Any]]) -> None:
    """Write *requests* whole, so a reader never sees half of them; with none
    left, the file goes."""
    path = _path(owner_key, project_id)
    if not path.parent.is_dir():
        return
    if not requests:
        path.unlink(missing_ok=True)
        return
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps({"requests": requests}, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _shown(request: dict[str, Any]) -> dict[str, Any]:
    """A request as the routes answer it: all but the store it copies from."""
    return {key: value for key, value in request.items() if key != "store"}


def _tell_the_room(project_id: str) -> None:
    """Tell the dataflow's tabs its requests changed, so each reads them again."""
    from utk_curio.backend import extensions
    from utk_curio.backend.app.collaboration import room_state
    from utk_curio.backend.config import COLLAB_NAMESPACE

    sio = extensions.socketio
    if sio is None:
        return
    try:
        sio.emit(CHANGED_EVENT, {"dataflowId": project_id}, to=room_state.room_for(project_id),
                 namespace=COLLAB_NAMESPACE)
    except Exception:  # noqa: BLE001 - a request stands whether or not the room heard of it
        logger.exception("the room of dataflow %s could not be told its requests changed", project_id)


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


def _listed(flow: _Dataflow, dataset_ids: list[str]) -> bool:
    """Whether the dataflow lists each of *dataset_ids* already, as the
    asker's listing of it reads its refs."""
    from utk_curio.backend.app.datasets.repositories.installed import InstalledDatasetRepository

    refs = InstalledDatasetRepository(flow.user).list_refs(flow.project_id)
    listed = {ref.get("datasetId") or ref.get("id") for ref in refs}
    return bool(dataset_ids) and all(dataset_id in listed for dataset_id in dataset_ids)


def ask(user, project_id: str, dataset_id: object, *, node_id: object = None, add: bool = False) -> dict[str, Any]:
    """An editor's request that the owner add *dataset_id* to her dataflow:
    one of his own Data Catalog, which he dropped as a file, dragged as a card
    (onto the node *node_id*, or onto the canvas, which made it) or added with
    Add to project (*add*). A dataset of the shared catalog is asked for only
    by Add to project, since every account's runs read it; the answer says
    when nothing was asked. One request stands for a dataset an editor asked
    for and the owner has not reviewed: asking again names the new node too.

    Writes the request beside the dataflow's spec and nothing else: not the
    owner's store, not the dataflow."""
    flow = _Dataflow(user, project_id)
    if flow.owner:
        raise DatasetCatalogError(OWNERS_OWN, 409)
    dataset_id = str(dataset_id or "").strip()
    if not dataset_id:
        raise DatasetCatalogError("datasetId is required", 400)

    from utk_curio.backend.app.projects.services import _history_person, _user_dir_key

    asker_key = _user_dir_key(user)
    folders, collection = _own_folders(asker_key, dataset_id)
    if _listed(flow, [row.dataset_id for row in folders] if folders else [dataset_id]):
        return {"requested": False, "reason": "listed"}
    if collection:
        raise DatasetCatalogError(COLLECTION_REFUSAL, 400)
    if folders:
        first = folders[0]
        title = (first.title or dataset_id) if not is_layer_group_id(dataset_id) else _group_title(folders, dataset_id)
        fmt = first.format if len(folders) == 1 else "layers"
        store: str | None = asker_key
        where = f"from {_history_person(user)['name']}'s Data Catalog"
    else:
        shared = _shared_item(dataset_id)
        if shared is None:
            raise DatasetCatalogError(NOT_FOUND, 404)
        if not add:
            # Every account's runs read the shared catalog: nothing to ask.
            return {"requested": False, "reason": "shared"}
        title = str(shared.get("title") or dataset_id)
        fmt = str(shared.get("format") or "")
        store = None
        where = "from the shared Data Catalog"
    node = str(node_id).strip() if isinstance(node_id, str) and node_id.strip() else None

    from utk_curio.backend.app.common.record_clock import utc_now

    with _lock(flow.project_id):
        requests = _read(flow.owner_key, flow.project_id)
        mine = next((r for r in requests if r.get("status") == "pending" and r.get("datasetId") == dataset_id
                     and (r.get("by") or {}).get("account") == str(user.id)), None)
        if mine is not None:
            if node and node not in mine.setdefault("nodeIds", []):
                mine["nodeIds"].append(node)
                _write(flow.owner_key, flow.project_id, requests)
            request = mine
        else:
            request = {
                "proposalId": uuid.uuid4().hex,
                "tool": TOOL,
                "status": "pending",
                "summary": f"Add dataset · {title}",
                "preview": " · ".join(part for part in (title, (fmt or "").upper(), where) if part),
                "datasetId": dataset_id,
                "datasetName": title,
                "format": fmt,
                "by": _history_person(user),
                "store": store,
                "dirNames": [row.dir_name for row in folders],
                "nodeIds": [node] if node else [],
                "requestedAt": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            requests.append(request)
            _write(flow.owner_key, flow.project_id, requests)
    _tell_the_room(flow.project_id)
    return {"requested": True, "request": _shown(request)}


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


def pending(user, project_id: str) -> list[dict[str, Any]]:
    """The requests of the dataflow the owner has not reviewed, oldest
    first: for its owner and her editors."""
    flow = _Dataflow(user, project_id)
    with _lock(flow.project_id):
        requests = _read(flow.owner_key, flow.project_id)
    return [_shown(r) for r in requests if r.get("status") == "pending"]


def _taken(flow: _Dataflow, request_id: str) -> dict[str, Any]:
    """Take the pending request *request_id* off the dataflow's requests,
    under its lock; 404 when there is none."""
    requests = _read(flow.owner_key, flow.project_id)
    request = next((r for r in requests if r.get("proposalId") == request_id), None)
    if request is None or request.get("status") != "pending":
        raise DatasetCatalogError(f"request {request_id!r} not found", 404)
    _write(flow.owner_key, flow.project_id, [r for r in requests if r is not request])
    return request


def dismiss(user, project_id: str, request_id: str) -> dict[str, Any]:
    """The owner's Dismiss of a request: it goes, and nothing else changes."""
    flow = _Dataflow(user, project_id)
    _owners_alone(flow)
    with _lock(flow.project_id):
        _taken(flow, request_id)
    _tell_the_room(flow.project_id)
    return {"proposalId": request_id, "status": "dismissed"}


def apply(user, project_id: str, request_id: str) -> dict[str, Any]:
    """The owner's Apply of a request: the dataset's folders are copied from
    the asker's store into hers, unless hers holds them already, and the
    dataset is added to the dataflow as her Add to project adds it, as her
    change. A dataset the asker's store no longer holds, or one that cannot be
    added, is not applied: the request goes, with a 409 that says why, and
    what this Apply copied goes with it."""
    from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService

    flow = _Dataflow(user, project_id)
    _owners_alone(flow)
    with _lock(flow.project_id):
        request = _taken(flow, request_id)
        asker = (request.get("by") or {}).get("name") or "the editor"
        copied: list[Path] = []
        try:
            for dir_name in request.get("dirNames") or []:
                target = _copy(str(request.get("store") or ""), flow.owner_key, str(dir_name))
                if target is not None:
                    copied.append(target)
            item = DatasetCatalogService(user).install_dataset(flow.project_id, str(request["datasetId"]))
        except (DatasetCatalogError, OSError, ValueError) as exc:
            for target in copied:
                _forget_copy(flow.owner_key, target)
            reason = str(exc.args[0]) if isinstance(exc, DatasetCatalogError) and exc.args else str(exc)
            raise DatasetCatalogError(
                f"{request.get('datasetName') or request.get('datasetId')} could not be added ({reason}): "
                f"ask {asker} to ask again.",
                409,
            ) from exc
    _tell_the_room(flow.project_id)
    return {
        "proposalId": request_id,
        "status": "applied",
        "installedDataset": {"id": item.get("id") or request["datasetId"],
                             "name": request.get("datasetName") or item.get("title")},
    }


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


def _forget_copy(owner_key: str, target: Path) -> None:
    """Take back a copy an Apply made and could not add."""
    from utk_curio.backend.app.datasets.repositories import index as index_repo

    shutil.rmtree(target, ignore_errors=True)
    index_repo.safe_forget(owner_key, target.name)
