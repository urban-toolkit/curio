"""A hosted guest's own copy of a dataflow, which its agents work on.

Every hosted guest (a guest on a Curio started with ``--deploy``) signs in to
one account, the shared guest's, which owns the shared examples. An agent's
work is kept in the dataflow it works on: its attachment, its chat, the changes
it makes. So one guest's agents wrote the example they opened, and the next
guest to open it met that work, until the next start put the examples back.

Now a hosted guest's agents work on a copy of the dataflow of its own
(:func:`for_request`): the dataflow as it was when they first needed it, beside
the account's dataflows, under an id made from the guest's sign-in and the
dataflow's id. A sign-in is one visitor's, so the copy stays theirs through a
reload, unlike a socket's participant id, which changes with every tab and
reconnect. Every agent request of that guest reads and writes the copy, Solve
and later turns included, and the guest's canvas of the dataflow opens it
(:func:`canvas_spec`), so the guest sees what their agents did there. A copy has
no row in the account's list of dataflows, so no gallery shows it. The copies
go when the server starts (:func:`drop_all`), as the shared examples are put
back then.

What the guest does to the dataflow themselves lands there too: a play's
output is kept on the copy and its outcome recorded in the copy's runtime
journal (``execution/node_exec.py``), a Data Catalog Add or Remove changes the
copy's datasets (``services.mutate_dataflow_datasets``), and a rename names the
copy (:func:`rename`). Each makes the copy when there is none.

So do the guest's own edits on the canvas: the guest's tab joins the room of
its copy (:func:`room_for`), keyed by the copy's id, and syncs the copy's doc
(``collaboration/dataflow_docs.py``). A room opens the doc of a copy not made
yet from the dataflow as it is, in memory, and the guest's first change there
makes the copy (:func:`make`), so a visitor who only looks makes none.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import threading
import uuid
from typing import Optional

from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.app.projects import storage

logger = logging.getLogger(__name__)

#: Beside a copy's spec: the dataflow it copies.
VISITOR_FILE = "visitor.json"

#: The namespace of the copies' ids.
_NAMESPACE = uuid.UUID("5d3c2a4e-7f1b-4c8e-9a6d-2b0e8f4c1a37")


def copies_for(user) -> bool:
    """Whether *user*'s agents work on copies: a hosted guest, whose account
    is the shared guest's."""
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.users.capabilities import is_hosted_guest

    return is_hosted_guest(user) and _user_dir_key(user) == GUEST_KEY


def _sign_in() -> Optional[str]:
    """The token of the request's sign-in, which names one visitor; None
    outside a request."""
    from flask import has_request_context

    from utk_curio.backend.app.users.dependencies import get_current_session

    if not has_request_context():
        return None
    session = get_current_session()
    return session.token if session is not None else None


def copy_id(sign_in: str, project_id: str) -> str:
    """The id of the copy of the dataflow *project_id* that the visitor signed
    in as *sign_in* works on. It names the sign-in by a digest only."""
    return str(uuid.uuid5(_NAMESPACE, f"{sign_in}:{project_id}"))


def _has_copy(own: str) -> bool:
    try:
        return (storage.project_dir(GUEST_KEY, own) / storage.SPEC_FILE).is_file()
    except (OSError, ValueError):
        return False


def _make(project_id: str, own: str) -> None:
    """Copy the dataflow *project_id*, as it is now and without its history,
    as *own*, once."""
    with storage.spec_write_lock(GUEST_KEY, own):
        if _has_copy(own):
            return
        spec = dataflow_docs.read(GUEST_KEY, project_id)
        if not isinstance(spec, dict):
            return
        # Named a copy before it holds a spec, so one cut short is dropped too.
        (storage.project_dir(GUEST_KEY, own) / VISITOR_FILE).write_text(
            json.dumps({"copies": project_id}), encoding="utf-8",
        )
        copied = {key: value for key, value in spec.items() if key not in storage.HISTORY_KEYS}
        dataflow_docs.create(GUEST_KEY, own, copied, dataflow_docs.by_curio(GUEST_KEY, "copy"))


def for_request(user, project_id: str, *, make: bool = True, sign_in: Optional[str] = None) -> str:
    """The dataflow the request's agents work on: *project_id* itself, or,
    for a hosted guest, the guest's own copy of it, made now when *make* and
    there is none. A read that finds no copy reads *project_id*: the guest's
    agents have not written it. *sign_in* names the visitor, the request's
    sign-in when it is not given."""
    if not copies_for(user):
        return project_id
    sign_in = sign_in or _sign_in()
    if not sign_in:
        return project_id
    own = copy_id(sign_in, project_id)
    if not _has_copy(own):
        if not make:
            return project_id
        _make(project_id, own)
        if not _has_copy(own):
            return project_id
    return own


def canvas_spec(user, project_id: str) -> Optional[dict]:
    """The spec a hosted guest's canvas of *project_id* opens with, when the
    guest's agents have a copy of it: the copy as it is now, as the canvas
    reads a dataflow, without its history. ``None`` for anyone else, and for
    a guest whose agents never wrote it."""
    if not copies_for(user):
        return None
    sign_in = _sign_in()
    own = copy_id(sign_in, project_id) if sign_in else None
    if own is None or not _has_copy(own):
        return None
    from utk_curio.backend.app.projects.services import _with_effective_packages

    spec = dataflow_docs.read(GUEST_KEY, own)
    if not isinstance(spec, dict):
        return None
    shown = {key: value for key, value in spec.items() if key not in storage.HISTORY_KEYS}
    return _with_effective_packages(shown, GUEST_KEY, own)


def with_spec(detail, spec: dict):
    """The dataflow's *detail* as the copy's *spec* gives it: its spec, its
    scenarios and its name."""
    from utk_curio.backend.app.projects import scenarios

    named = (spec.get("dataflow") or {}).get("name") if isinstance(spec, dict) else None
    fields = {"spec": spec, "scenarios": scenarios.scenario_summaries(spec)}
    if isinstance(named, str) and named:
        fields["name"] = named
    return dataclasses.replace(detail, **fields)


def is_own_copy(sign_in: Optional[str], own: str) -> bool:
    """Whether *own* is the copy the visitor signed in as *sign_in* works on:
    a copy (its ``visitor.json``) of the dataflow whose id makes *own* with
    that sign-in."""
    if not sign_in or not own:
        return False
    try:
        copied = json.loads((storage.project_dir(GUEST_KEY, own) / VISITOR_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    source = copied.get("copies") if isinstance(copied, dict) else None
    return isinstance(source, str) and copy_id(sign_in, source) == own


def rename(user, project_id: str, name: str) -> Optional[dict]:
    """Name the hosted guest's own copy of *project_id*, a dataflow the
    account owns, *name*: its ``dataflow.name``, the copy made now when there
    is none. The dataflow's row keeps its name, which every guest's gallery
    lists. The copy's spec as the guest's canvas opens it, or ``None`` for
    anyone else, and for a dataflow the account does not own."""
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.extensions import db

    if not copies_for(user):
        return None
    project = db.session.get(Project, project_id)
    if project is None or project.user_id != getattr(user, "id", None):
        return None
    own = for_request(user, project_id, make=True)
    if own == project_id:
        return None
    with dataflow_docs.writing(GUEST_KEY, own, dataflow_docs.person(GUEST_KEY, "rename")) as spec:
        dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
        if isinstance(dataflow, dict):
            dataflow["name"] = name
    return canvas_spec(user, project_id)


def drop_all() -> int:
    """Drop every copy the hosted guests worked on, with the outputs their
    plays kept on it; how many. The server does when it starts, as it puts
    the shared examples back."""
    from utk_curio.backend.app.common.user_storage import user_key_segment, users_base
    from utk_curio.backend.app.runs import kept

    try:
        projects = users_base() / user_key_segment(GUEST_KEY) / "projects"
    except (OSError, ValueError):
        return 0
    if not projects.is_dir():
        return 0
    dropped = []
    for folder in projects.iterdir():
        if folder.is_dir() and (folder / VISITOR_FILE).is_file():
            dataflow_docs.close(folder.name)
            storage.delete_tree(GUEST_KEY, folder.name)
            dropped.append(folder.name)
    try:
        kept.forget_dataflows(dropped)
    except Exception:  # noqa: BLE001 - the copies go either way, and their kept outputs at the end of their days
        logger.warning("could not forget the outputs kept on %d hosted guest copies", len(dropped), exc_info=True)
    with _rooms_lock:
        _rooms.clear()
    return len(dropped)


# ---------------------------------------------------------------------------
# A copy's room: the guest's own edits on the canvas
# ---------------------------------------------------------------------------

#: The copies whose rooms a hosted guest's tab joined, made or not yet: each
#: copy's id and the dataflow it copies (:func:`room_for`).
_rooms: dict[str, str] = {}
_rooms_lock = threading.Lock()


@dataclasses.dataclass(frozen=True)
class Copy:
    """A hosted guest's copy of a dataflow, read as the room reads a
    dataflow's row (``collaboration/events.py``): it has no row, so its owner
    is the account that owns the dataflow it copies, the shared guest's, and
    its one member is the sign-in its id names (:func:`is_room_of`)."""

    #: The copy's id (:func:`copy_id`).
    id: str
    #: The dataflow it copies.
    copies: str
    #: Its owner, the account that owns the dataflow it copies.
    user_id: int
    owner: object


def _source(own: str) -> Optional[str]:
    """The dataflow the copy *own* copies: its ``visitor.json`` says, or, for
    a copy not made yet, the room that opened it (:func:`room_for`)."""
    try:
        copied = json.loads((storage.project_dir(GUEST_KEY, own) / VISITOR_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        copied = None
    source = copied.get("copies") if isinstance(copied, dict) else None
    if isinstance(source, str) and source:
        return source
    with _rooms_lock:
        return _rooms.get(own)


def as_row(own: str) -> Optional[Copy]:
    """The copy *own* as the room reads a dataflow's row (:class:`Copy`), or
    ``None`` when *own* is no copy a room or a request made, or the dataflow
    it copies is gone."""
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.extensions import db

    source = _source(own)
    project = db.session.get(Project, source) if source else None
    if project is None:
        return None
    return Copy(id=own, copies=project.id, user_id=project.user_id, owner=project.owner)


def room_for(user, project, sign_in: Optional[str]) -> Optional[Copy]:
    """The copy whose room the tab of a hosted guest signed in as *sign_in*
    joins for *project*, a dataflow the guest's account owns: the guest's
    own copy of it (:func:`copy_id`), made or not yet. Nothing is written:
    the copy is made on the guest's first change (:func:`make`). ``None`` for
    anyone else, for another account's dataflow, and for a copy itself."""
    if isinstance(project, Copy) or not sign_in or not copies_for(user):
        return None
    if project is None or getattr(project, "user_id", None) != getattr(user, "id", None):
        return None
    own = copy_id(sign_in, project.id)
    with _rooms_lock:
        _rooms[own] = project.id
    return Copy(id=own, copies=project.id, user_id=project.user_id, owner=project.owner)


def is_room_of(sign_in: Optional[str], project) -> bool:
    """Whether *project* is the copy the visitor signed in as *sign_in*
    edits: a :class:`Copy` whose id that sign-in and the dataflow it copies
    make. Another guest's copy is not, nor any dataflow's row."""
    return isinstance(project, Copy) and bool(sign_in) and copy_id(sign_in, project.copies) == project.id


def make(own: str) -> bool:
    """Make the copy *own*, whose room a guest's tab joined, on the guest's
    first change there: the dataflow it copies as it is now, without its
    history. The doc the room opened for it becomes the copy's
    (``dataflow_docs.create``), so its tabs sync on. Whether it is made."""
    source = _source(own)
    if source is None:
        return False
    _make(source, own)
    return _has_copy(own)


def own_copy_source(user, project_id: str) -> Optional[str]:
    """The dataflow *project_id* copies, when *project_id* is the copy the
    request's visitor works on (a hosted guest's own, by its sign-in): an
    agent's tool names the copy by its id. ``None`` for anything else."""
    if not copies_for(user):
        return None
    sign_in = _sign_in()
    if not is_own_copy(sign_in, project_id):
        return None
    return _source(project_id)
