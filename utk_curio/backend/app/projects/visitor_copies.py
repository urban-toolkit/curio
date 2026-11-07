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
copy (:func:`rename`). Each makes the copy when there is none. The guest's
dashboard of the dataflow shows and runs the copy once there is one
(:func:`dashboard_copy`, ``runs/viewer.py``), and makes none. A node's output
the guest adds to the dataflow is saved in the account's store under the
copy's id (``computed.<copy>.<node>``), which every guest's Data Catalog reads,
so it lists for that guest alone (:func:`lists_for`).

So does a file the guest imports, and a dataset they download from the
Discovery Catalog: each is named after the guest (``imported.<visitor>.x<id>``,
:func:`visitor_of`), whatever dataflow they are in, and goes when the server
starts too. A run the guest's request starts on a thread of its own, an agent's
job or a download, holds no request: it is handed the request's sign-in
(:func:`carrying`, :func:`carried`) and serves it (:func:`serving`), so what is
the guest's is theirs there as in their requests.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.app.projects import storage

logger = logging.getLogger(__name__)

#: Beside a copy's spec: the dataflow it copies.
VISITOR_FILE = "visitor.json"

#: The namespace of the copies' ids.
_NAMESPACE = uuid.UUID("5d3c2a4e-7f1b-4c8e-9a6d-2b0e8f4c1a37")

#: The sign-in of the visitor a run on a thread of its own serves, which a
#: request that started it handed it (:func:`serving`).
_SERVING: ContextVar[Optional[str]] = ContextVar("visitor_copies_serving", default=None)

#: An upload's or a download's name, ``imported.<visitor>.x<id>``, whose
#: middle part names the visitor who added it (:func:`visitor_of`).
_ADDED_BY = re.compile(r"^imported\.([a-z][a-z0-9-]*)\.[a-z][a-z0-9-]*(?:@\d+)?$")


def copies_for(user) -> bool:
    """Whether *user*'s agents work on copies: a hosted guest, whose account
    is the shared guest's."""
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.users.capabilities import is_hosted_guest

    return is_hosted_guest(user) and _user_dir_key(user) == GUEST_KEY


def _sign_in() -> Optional[str]:
    """The token of the sign-in that names one visitor: the request's, or on
    a thread of its own, which holds no request, the one a request handed
    its run (:func:`serving`); None for neither."""
    from flask import has_request_context

    from utk_curio.backend.app.users.dependencies import get_current_session

    if not has_request_context():
        return _SERVING.get()
    session = get_current_session()
    return session.token if session is not None else _SERVING.get()


def current_sign_in() -> Optional[str]:
    """The sign-in the visitor's request or run is made with
    (:func:`_sign_in`)."""
    return _sign_in()


@contextmanager
def serving(sign_in: Optional[str]):
    """The block serves the visitor signed in as *sign_in*: on a thread of
    its own, which holds no request, :func:`_sign_in` answers it, so the
    visitor's copies and datasets are theirs there as in their requests."""
    token = _SERVING.set(sign_in)
    try:
        yield
    finally:
        try:
            _SERVING.reset(token)
        except ValueError:  # closed on another thread, whose context it never set
            pass


def carrying(target):
    """*target*, a thread's work, run for the visitor whose request starts
    it: the sign-in is taken now, in that request, and served while *target*
    runs (:func:`serving`)."""
    sign_in = _sign_in()

    def run(*args, **kwargs):
        with serving(sign_in):
            return target(*args, **kwargs)

    return run


def carried(events):
    """*events*, a generator a job drives on a thread of its own, run for
    the visitor whose request starts it, as :func:`carrying` runs a thread's
    work: the sign-in is taken now and served while the job drives it."""
    sign_in = _sign_in()

    def run():
        with serving(sign_in):
            yield from events

    return run()


def visitor_of(sign_in: Optional[str] = None) -> Optional[str]:
    """What the visitor signed in as *sign_in* (else the request's or the
    run's sign-in) is named in the account's store: the middle part of the
    name of each dataset they upload or download (``imported.<visitor>.x<id>``).
    A digest of the sign-in, never the sign-in itself. None with no sign-in."""
    sign_in = sign_in or _sign_in()
    if not sign_in:
        return None
    return "v" + uuid.uuid5(_NAMESPACE, f"{sign_in}:datasets").hex


def added_by(name: Optional[str]) -> Optional[str]:
    """The visitor who uploaded or downloaded the dataset *name*, an id or
    a folder name, as :func:`visitor_of` names them; None for a dataset no
    hosted guest added."""
    found = _ADDED_BY.match(str(name or ""))
    return found.group(1) if found else None


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
    reads a dataflow, without its history (:func:`spec_of`). ``None`` for
    anyone else, and for a guest whose agents never wrote it."""
    if not copies_for(user):
        return None
    sign_in = _sign_in()
    own = copy_id(sign_in, project_id) if sign_in else None
    if own is None or not _has_copy(own):
        return None
    return spec_of(own)


def spec_of(own: str) -> Optional[dict]:
    """The copy *own* as it is now, as a canvas or a dashboard reads a
    dataflow: without its history, with the packages its lockfile gives."""
    from utk_curio.backend.app.projects.services import _with_effective_packages

    spec = dataflow_docs.read(GUEST_KEY, own)
    if not isinstance(spec, dict):
        return None
    shown = {key: value for key, value in spec.items() if key not in storage.HISTORY_KEYS}
    return _with_effective_packages(shown, GUEST_KEY, own)


def dashboard_copy(project_id: str) -> Optional[str]:
    """The copy the dashboard of *project_id* shows and runs for the visitor
    who asks: a hosted guest's own copy of a dataflow their account owns, once
    they have one. None is made here: a visitor who only looks makes none.
    ``None`` for anyone else: a guest with no copy, every other visitor of the
    dashboard's link, an account, and anyone on a Curio started without
    ``--deploy``. A dashboard's routes need no sign-in, so the request's is
    read here, when it sends one."""
    from flask import has_request_context

    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.app.users.dependencies import get_current_user
    from utk_curio.backend.extensions import db

    if not project_id or not has_request_context():
        return None
    user = get_current_user()
    if not copies_for(user):
        return None
    project = db.session.get(Project, project_id)
    if project is None or project.user_id != getattr(user, "id", None):
        return None
    own = for_request(user, project_id, make=False)
    return own if own != project_id else None


def with_spec(detail, spec: dict):
    """The dataflow's *detail* as the copy's *spec* gives it: its spec, its
    scenarios and its name."""
    from utk_curio.backend.app.projects import scenarios

    named = (spec.get("dataflow") or {}).get("name") if isinstance(spec, dict) else None
    fields = {"spec": spec, "scenarios": scenarios.scenario_summaries(spec)}
    if isinstance(named, str) and named:
        fields["name"] = named
    return dataclasses.replace(detail, **fields)


def is_copy(project_id: Optional[str]) -> bool:
    """Whether *project_id* names a hosted guest's copy of a dataflow."""
    if not project_id:
        return False
    try:
        return (storage.project_dir(GUEST_KEY, project_id) / VISITOR_FILE).is_file()
    except (OSError, ValueError):
        return False


def a_visitors(dataflow_id: Optional[str], name: Optional[str] = None) -> bool:
    """Whether a dataset of the guest account's store is a hosted guest's
    own: made by a copy of theirs (*dataflow_id*, the dataflow that made it),
    or uploaded or downloaded by one (*name*, its id or folder)."""
    return added_by(name) is not None or is_copy(dataflow_id)


def lists_for(dataflow_id: Optional[str], sign_in: Optional[str] = None, *, name: Optional[str] = None) -> bool:
    """Whether a dataset of the guest account's store lists for the visitor
    signed in as *sign_in*, else the request's or the run's sign-in: one a
    hosted guest's copy made (*dataflow_id*, the dataflow that made it), and
    one they uploaded or downloaded (*name*, its id or folder), is that
    guest's alone; any other is every guest's."""
    if not a_visitors(dataflow_id, name):
        return True
    sign_in = sign_in or _sign_in()
    if is_copy(dataflow_id) and not is_own_copy(sign_in, dataflow_id):
        return False
    adder = added_by(name)
    return adder is None or adder == visitor_of(sign_in)


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
    plays kept on it and the node outputs they added to it as datasets; how
    many. The files they uploaded and the datasets they downloaded go too.
    The server does when it starts, as it puts the shared examples back."""
    from utk_curio.backend.app.common.user_storage import user_key_segment, users_base
    from utk_curio.backend.app.runs import kept

    # Each names its guest, so one that cannot go now lists for that guest
    # alone until the next start drops it (:func:`lists_for`).
    try:
        from utk_curio.backend.app.datasets.repositories.user_store import drop_uploads

        left = drop_uploads(GUEST_KEY)
        if left:
            logger.warning("%d hosted guest uploads stay until the next start", len(left))
    except Exception:  # noqa: BLE001 - a start goes on; they go at the next one
        logger.warning("could not drop the hosted guests' uploads", exc_info=True)
    try:
        projects = users_base() / user_key_segment(GUEST_KEY) / "projects"
    except (OSError, ValueError):
        return 0
    if not projects.is_dir():
        return 0
    copies = [folder.name for folder in projects.iterdir() if folder.is_dir() and (folder / VISITOR_FILE).is_file()]
    # Their datasets go first, while each copy still names them its own: a
    # copy one of whose datasets stays is kept for the next start, so that
    # dataset never lists for another guest (:func:`lists_for`).
    try:
        from utk_curio.backend.app.datasets.repositories.user_store import drop_dataflow_outputs

        staying = drop_dataflow_outputs(GUEST_KEY, copies)
    except Exception:  # noqa: BLE001 - the copies then stay, with their datasets, for the next start
        logger.warning("could not drop the datasets of %d hosted guest copies", len(copies), exc_info=True)
        staying = set(copies)
    if staying:
        logger.warning("%d hosted guest copies stay until the next start, with datasets that could not go", len(staying))
    dropped = []
    for own in copies:
        if own in staying:
            continue
        dataflow_docs.close(own)
        storage.delete_tree(GUEST_KEY, own)
        dropped.append(own)
    try:
        kept.forget_dataflows(dropped)
    except Exception:  # noqa: BLE001 - the copies go either way, and their kept outputs at the end of their days
        logger.warning("could not forget the outputs kept on %d hosted guest copies", len(dropped), exc_info=True)
    return len(dropped)
