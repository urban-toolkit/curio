"""What an invited editor asks the owner of a dataflow to add to it, kept for her review.

An editor the owner of a dataflow invited (``access.py``) changes the dataflow
as she does, but an item of his own store is not in hers: her runs cannot read
it, and only her own changes put an item of hers in the lists her editors'
runs read (``collaboration/owner_uses.py``). So when he brings an item of his
own to her dataflow, or an item of a shared catalog her dataflow does not use,
he asks her instead: a request in her install review, the review an install an
agent asks for waits in, shown on the same card
(``src/contracts/agentInstalls.json``). Each kind of item has its module, which
says what is asked and what her Apply does (:data:`KINDS`):

* ``datasets``: a dataset, a layer group or a collection of his Data Catalog,
  or a dataset of the shared one (``datasets/application/editor_requests.py``);
* ``packages``: a node package or a model package of his store, or one of the
  shared catalog (``packages/application/editor_requests.py``).

* :func:`ask` keeps the request beside the dataflow's spec
  (:data:`REQUESTS_FILE`), which the doc does not carry and no tab writes. It
  writes nothing in the owner's store and nothing in the dataflow.
* :func:`apply`, the owner's alone, does what the kind's Apply does, as her
  change. A request whose asker no longer edits the dataflow goes, with the
  reason. One the kind cannot apply stays in her review, with the reason.
* :func:`dismiss`, the owner's alone, drops the request and leaves nothing
  behind.

Each change is told to the dataflow's room (:data:`CHANGED_EVENT`), so every
tab reads the requests again.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The requests of a dataflow, of every kind, beside its spec.
REQUESTS_FILE = "dataset-requests.json"
#: What the dataflow's room is told after a request is made, applied or dismissed.
CHANGED_EVENT = "editor_requests_changed"

#: Each kind of request, by the name its routes give it, and the module that
#: says what is asked and what the owner's Apply does.
KINDS = {
    "datasets": "utk_curio.backend.app.datasets.application.editor_requests",
    "packages": "utk_curio.backend.app.packages.application.editor_requests",
}

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


class RequestError(Exception):
    """A request refused, with what the caller is told and its status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _lock(project_id: str) -> threading.Lock:
    """The lock of one dataflow's requests: a read, a change and its write."""
    with _guard:
        return _locks.setdefault(project_id, threading.Lock())


def kind_of(name: str):
    """The module of the kind of request *name*; a 404 for any other name."""
    module = KINDS.get(name)
    if module is None:
        raise RequestError(f"no requests of {name!r}", 404)
    return importlib.import_module(module)


# ---------------------------------------------------------------------------
# Who asks, and of whom
# ---------------------------------------------------------------------------

class Dataflow:
    """The dataflow a request names, its owner's store and the asker's role.
    Anyone but its owner and an editor she invited is refused, in the words
    of the kind (*items*)."""

    def __init__(self, user, project_id: str, items: str):
        from utk_curio.backend.app.projects import access
        from utk_curio.backend.app.projects.models import Project
        from utk_curio.backend.app.projects.repositories import NotFoundError
        from utk_curio.backend.app.projects.services import _owner_user_dir_key, _user_dir_key
        from utk_curio.backend.extensions import db

        if user is None:
            raise RequestError("Authorization required", 401)
        project = db.session.get(Project, project_id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        self.role = access.agents_role(user, project)
        if self.role not in access.EDIT_ROLES:
            raise RequestError(
                f"Only the owner and the editors the owner invited add {items} to this dataflow.", 403,
            )
        self.user = user
        self.project = project
        self.project_id = project.id
        self.owner_key = _owner_user_dir_key(project)
        self.asker_key = _user_dir_key(user)
        owner = project.owner
        self.owner_name = (owner.name or owner.username) if owner is not None else "the owner"

    @property
    def owner(self) -> bool:
        from utk_curio.backend.app.projects import access

        return self.role == access.OWNER


def _owners_alone(flow: Dataflow) -> None:
    """Refuse an editor's Apply or Dismiss: a request waits for the owner's
    review, as an install an agent asks for does."""
    if flow.owner:
        return
    from utk_curio.backend.app.projects.access import owners_review

    raise RequestError(owners_review(flow.owner_name), 403)


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


def _kind_name(request: dict[str, Any]) -> str:
    """The kind a held request is of: a request kept before there were kinds
    is a dataset's."""
    kind = request.get("kind")
    return kind if kind in KINDS else "datasets"


def _shown(request: dict[str, Any]) -> dict[str, Any]:
    """A request as the routes answer it: all but the store it copies from."""
    return {key: value for key, value in request.items() if key != "store"}


def _tell_the_room(project_id: str, kind: str) -> None:
    """Tell the dataflow's tabs its requests changed, so each reads them again."""
    from utk_curio.backend import extensions
    from utk_curio.backend.app.collaboration import room_state
    from utk_curio.backend.config import COLLAB_NAMESPACE

    sio = extensions.socketio
    if sio is None:
        return
    try:
        sio.emit(CHANGED_EVENT, {"dataflowId": project_id, "kind": kind}, to=room_state.room_for(project_id),
                 namespace=COLLAB_NAMESPACE)
    except Exception:  # noqa: BLE001 - a request stands whether or not the room heard of it
        logger.exception("the room of dataflow %s could not be told its requests changed", project_id)


# ---------------------------------------------------------------------------
# Ask, read, apply, dismiss
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Asked:
    """What a kind says an editor's ask is for: the item, by its id (*item*),
    and the request's own fields (*fields*), or *reason*, why nothing needs
    asking."""

    item: str = ""
    fields: dict | None = None
    reason: str | None = None


def ask(user, project_id: str, kind_name: str, item: object, *, node_id: object = None,
        add: bool = False) -> dict[str, Any]:
    """An editor's request that the owner add *item*, of the kind *kind_name*,
    to her dataflow: dropped on the node *node_id*, or onto the canvas, which
    made that node, or added with Add to project (*add*). The answer says when
    nothing was asked. One request stands for an item an editor asked for and
    the owner has not reviewed: asking again names the new node too.

    Writes the request beside the dataflow's spec and nothing else: not the
    owner's store, not the dataflow."""
    kind = kind_of(kind_name)
    flow = Dataflow(user, project_id, kind.ITEMS)
    if flow.owner:
        raise RequestError(kind.OWNERS_OWN, 409)
    item_id = str(item or "").strip()
    if not item_id:
        raise RequestError(f"{kind.ITEM} is required", 400)
    asked = kind.asked(flow, item_id, add=add)
    if asked.reason:
        return {"requested": False, "reason": asked.reason}
    node = str(node_id).strip() if isinstance(node_id, str) and node_id.strip() else None

    from utk_curio.backend.app.common.record_clock import utc_now
    from utk_curio.backend.app.projects.services import _history_person

    with _lock(flow.project_id):
        requests = _read(flow.owner_key, flow.project_id)
        mine = next((r for r in requests if r.get("status") == "pending" and _kind_name(r) == kind_name
                     and r.get(kind.ITEM) == asked.item
                     and (r.get("by") or {}).get("account") == str(user.id)), None)
        if mine is not None:
            if node and node not in mine.setdefault("nodeIds", []):
                mine["nodeIds"].append(node)
                _write(flow.owner_key, flow.project_id, requests)
            request = mine
        else:
            request = {
                "proposalId": uuid.uuid4().hex,
                "kind": kind_name,
                "tool": kind.TOOL,
                "status": "pending",
                **(asked.fields or {}),
                kind.ITEM: asked.item,
                "by": _history_person(user),
                "nodeIds": [node] if node else [],
                "requestedAt": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            requests.append(request)
            _write(flow.owner_key, flow.project_id, requests)
    _tell_the_room(flow.project_id, kind_name)
    return {"requested": True, "request": _shown(request)}


def pending(user, project_id: str, kind_name: str) -> list[dict[str, Any]]:
    """The requests of the kind *kind_name* the owner has not reviewed, oldest
    first: for its owner and her editors."""
    kind = kind_of(kind_name)
    flow = Dataflow(user, project_id, kind.ITEMS)
    with _lock(flow.project_id):
        requests = _read(flow.owner_key, flow.project_id)
    return [_shown(r) for r in requests if r.get("status") == "pending" and _kind_name(r) == kind_name]


def _held(flow: Dataflow, kind_name: str, request_id: str, *, take: bool) -> dict[str, Any]:
    """The pending request *request_id* of the kind *kind_name*, taken off the
    dataflow's requests when *take*; 404 when there is none. Under the lock."""
    requests = _read(flow.owner_key, flow.project_id)
    request = next((r for r in requests if r.get("proposalId") == request_id), None)
    if request is None or request.get("status") != "pending" or _kind_name(request) != kind_name:
        raise RequestError(f"request {request_id!r} not found", 404)
    if take:
        _write(flow.owner_key, flow.project_id, [r for r in requests if r is not request])
    return request


def review(user, project_id: str, kind_name: str, request_id: str) -> dict[str, Any]:
    """What the owner's review of a request shows before her Apply, as its
    kind reads it (a package's permissions, dependencies and conflicts with
    hers); the owner's alone."""
    kind = kind_of(kind_name)
    flow = Dataflow(user, project_id, kind.ITEMS)
    _owners_alone(flow)
    if not hasattr(kind, "review"):
        raise RequestError(f"a request for {kind.ITEMS} has no review to show", 404)
    with _lock(flow.project_id):
        request = _held(flow, kind_name, request_id, take=False)
    return kind.review(flow, request)


def dismiss(user, project_id: str, kind_name: str, request_id: str) -> dict[str, Any]:
    """The owner's Dismiss of a request: it goes, and nothing else changes."""
    kind = kind_of(kind_name)
    flow = Dataflow(user, project_id, kind.ITEMS)
    _owners_alone(flow)
    with _lock(flow.project_id):
        _held(flow, kind_name, request_id, take=True)
    _tell_the_room(flow.project_id, kind_name)
    return {"proposalId": request_id, "status": "dismissed"}


def apply(user, project_id: str, kind_name: str, request_id: str) -> dict[str, Any]:
    """The owner's Apply of a request: what its kind's Apply does, as her
    change. The request leaves her review while it is applied, so no second
    Apply runs it again, and the work, a package's install among it, runs
    outside the lock the review's reads take.

    A request whose asker no longer edits the dataflow, or whose store is no
    longer his, goes with a 409 that says why. One the kind cannot apply
    (``kind.refusal`` names why) comes back to her review with a 409 that says
    why, and the kind takes back what this Apply did."""
    kind = kind_of(kind_name)
    flow = Dataflow(user, project_id, kind.ITEMS)
    _owners_alone(flow)
    with _lock(flow.project_id):
        request = _held(flow, kind_name, request_id, take=True)
    name = request.get(kind.NAME) or request.get(kind.ITEM)
    asker = (request.get("by") or {}).get("name") or "the editor"
    if not _still_editing(flow, request):
        _tell_the_room(flow.project_id, kind_name)
        raise RequestError(f"{name} could not be added: {asker} no longer edits this dataflow.", 409)
    try:
        outcome = kind.apply(flow, request)
    except Exception as exc:
        _put_back(flow, request)
        _tell_the_room(flow.project_id, kind_name)
        reason = kind.refusal(exc)
        if reason is None:
            raise
        raise RequestError(f"{name} could not be added: {reason}", 409) from exc
    _tell_the_room(flow.project_id, kind_name)
    return {"proposalId": request_id, "status": "applied", **outcome}


def _put_back(flow: Dataflow, request: dict[str, Any]) -> None:
    """Return *request* to the dataflow's requests, where it waited."""
    with _lock(flow.project_id):
        requests = _read(flow.owner_key, flow.project_id)
        if not any(r.get("proposalId") == request.get("proposalId") for r in requests):
            requests.append(request)
            requests.sort(key=lambda r: str(r.get("requestedAt") or ""))
            _write(flow.owner_key, flow.project_id, requests)


def _still_editing(flow: Dataflow, request: dict[str, Any]) -> bool:
    """Whether the account that asked still edits the dataflow, and the store
    the request copies from is that account's: a request stands only while its
    asker is an editor the owner invited."""
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.users.models import User
    from utk_curio.backend.extensions import db

    account = (request.get("by") or {}).get("account")
    try:
        asker = db.session.get(User, int(account))
    except (TypeError, ValueError):
        return False
    if asker is None or access.agents_role(asker, flow.project) != access.EDITOR:
        return False
    store = request.get("store")
    return store is None or store == _user_dir_key(asker)
