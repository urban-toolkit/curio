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
"""
from __future__ import annotations

import dataclasses
import json
import uuid
from typing import Optional

from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.app.projects import storage

#: Beside a copy's spec: the dataflow it copies.
VISITOR_FILE = "visitor.json"

#: The namespace of the copies' ids.
_NAMESPACE = uuid.UUID("5d3c2a4e-7f1b-4c8e-9a6d-2b0e8f4c1a37")


def _copies_for(user) -> bool:
    """Whether *user*'s agents work on copies: a hosted guest, whose account
    is the shared guest's."""
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.users.capabilities import is_hosted_guest

    return is_hosted_guest(user) and _user_dir_key(user) == GUEST_KEY


def _sign_in() -> Optional[str]:
    """The token of the request's sign-in, which names one visitor."""
    from utk_curio.backend.app.users.dependencies import get_current_session

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


def for_request(user, project_id: str, *, make: bool = True) -> str:
    """The dataflow the request's agents work on: *project_id* itself, or,
    for a hosted guest, the guest's own copy of it, made now when *make* and
    there is none. A read that finds no copy reads *project_id*: the guest's
    agents have not written it."""
    if not _copies_for(user):
        return project_id
    sign_in = _sign_in()
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
    if not _copies_for(user):
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
    """The dataflow's *detail* as the copy's *spec* gives it."""
    from utk_curio.backend.app.projects import scenarios

    return dataclasses.replace(detail, spec=spec, scenarios=scenarios.scenario_summaries(spec))


def drop_all() -> int:
    """Drop every copy the hosted guests' agents worked on; how many. The
    server does when it starts, as it puts the shared examples back."""
    from utk_curio.backend.app.common.user_storage import user_key_segment, users_base

    try:
        projects = users_base() / user_key_segment(GUEST_KEY) / "projects"
    except (OSError, ValueError):
        return 0
    if not projects.is_dir():
        return 0
    dropped = 0
    for folder in projects.iterdir():
        if folder.is_dir() and (folder / VISITOR_FILE).is_file():
            dataflow_docs.close(folder.name)
            storage.delete_tree(GUEST_KEY, folder.name)
            dropped += 1
    return dropped
