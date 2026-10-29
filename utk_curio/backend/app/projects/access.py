"""Who may edit a dataflow: its owner, the editors the owner invited, and the
rest, who watch.

Three roles, decided on the server:

* the **owner** owns the dataflow (``Project.user_id``);
* an **editor** is an account the owner invited (a ``ProjectEditor`` row),
  by username from the Share menu;
* a **watcher** is anyone else who opens the dataflow's link.

:func:`room_role` is the one rule: a collaboration room asks it when a
participant joins and again for each change the participant sends
(``collaboration/events.py``), and refuses a watcher's. A change to the list
reaches the room at once (:func:`_tell_the_room`). The dataflow's agents ask
it too (:func:`agents_role`): the owner and the editors drive them, and a
watcher is refused.

Only the owner manages the list, and no guest does: the shared guest owns the
examples every hosted guest opens, so a check on ownership alone would let any
visitor invite editors to them. A guest is never an editor either, and a
hosted guest only watches.
"""
from __future__ import annotations

import logging
from typing import List

from utk_curio.backend.extensions import db
from utk_curio.backend.app.projects import repositories as repo
from utk_curio.backend.app.projects.services import ProjectError

logger = logging.getLogger(__name__)

OWNER = "owner"
EDITOR = "editor"
WATCHER = "watcher"
#: The roles that edit a dataflow in its room.
EDIT_ROLES = frozenset({OWNER, EDITOR})

GUEST_INVITE_REFUSAL = "Guests cannot invite editors. Sign in with an account to invite them."
NO_USERNAME = "Name the account to invite by its username."
GUEST_INVITEE = "A guest cannot edit a dataflow. Invite an account."
OWNER_INVITEE = "You own this dataflow, so you edit it already."
#: What anyone but the owner and the editors the owner invited is told who
#: asks the dataflow's agents for anything.
AGENTS_WATCHER_REFUSAL = "Only the owner and the editors the owner invited work with this dataflow's agents."


def room_role(user, project) -> str:
    """The role *user* has in *project*'s room: ``owner``, ``editor`` or
    ``watcher``, read from the database each time it is asked.

    *user* is an account, or anything with its ``id`` and ``is_guest``. A
    hosted guest watches whatever it opens (``capabilities.is_hosted_guest``):
    every visitor shares its account, which owns the examples. Without
    ``--deploy`` the shared guest is the one local user and owns its dataflows.
    """
    from utk_curio.backend.app.users.capabilities import is_hosted_guest

    user_id = getattr(user, "id", None)
    if user_id is None or project is None or is_hosted_guest(user):
        return WATCHER
    if project.user_id == user_id:
        return OWNER
    if repo.editor_row(project.id, user_id) is not None:
        return EDITOR
    return WATCHER


def agents_role(user, project) -> str:
    """The role *user* has with *project*'s agents: ``owner`` for the account
    that owns the dataflow, ``editor`` for an account the owner invited, and
    ``watcher`` for anyone else, whom the agents' routes refuse.

    The owner is told by account before :func:`room_role`, which has every
    hosted guest watch: the hosted guests share the account that owns the
    examples, and each works with an example's agents as with its own. A
    hosted guest on another account's dataflow watches."""
    user_id = getattr(user, "id", None)
    if project is not None and user_id is not None and project.user_id == user_id:
        return OWNER
    return room_role(user, project)


def joins_room(user, project) -> bool:
    """Whether *user* joins *project*'s room at all: everyone does but a hosted
    guest on a dataflow a guest owns (an example), whose canvas of it stays
    its own."""
    from utk_curio.backend.app.users.capabilities import is_hosted_guest

    owner = getattr(project, "owner", None)
    return not (is_hosted_guest(user) and owner is not None and owner.is_guest)


def _entry(row) -> dict:
    user = row.user
    return {
        "user_id": row.user_id,
        "username": user.username if user is not None else None,
        "name": (user.name or user.username) if user is not None else None,
        "added_at": row.added_at.isoformat() if row.added_at else None,
    }


def _owned(owner, project_id: str):
    """The dataflow *owner* owns, or the refusal: a guest manages no editors
    (403), and anyone but the owner is told the dataflow is not found."""
    if owner is None or owner.is_guest:
        raise ProjectError(GUEST_INVITE_REFUSAL, 403)
    return repo.get_for_user(project_id, owner.id)


def list_editors(owner, project_id: str) -> List[dict]:
    project = _owned(owner, project_id)
    return [_entry(row) for row in repo.editors_of(project.id)]


def add_editor(owner, project_id: str, username: str) -> List[dict]:
    """Invite the account *username* to edit the dataflow; the list after it."""
    from utk_curio.backend.app.users import repositories as users

    project = _owned(owner, project_id)
    name = (username or "").strip()
    if not name:
        raise ProjectError(NO_USERNAME, 400)
    user = users.user_by_username(name)
    if user is None:
        raise ProjectError(f"No account is named {name!r}.", 404)
    if user.is_guest:
        raise ProjectError(GUEST_INVITEE, 400)
    if user.id == project.user_id:
        raise ProjectError(OWNER_INVITEE, 400)
    if repo.editor_row(project.id, user.id) is not None:
        raise ProjectError(f"{user.username} already edits this dataflow.", 409)
    repo.add_editor_row(project.id, user.id, owner.id)
    db.session.commit()
    _tell_the_room(project.id, user.id, EDITOR)
    return [_entry(row) for row in repo.editors_of(project.id)]


def remove_editor(owner, project_id: str, user_id: int) -> List[dict]:
    """Take *user_id* off the dataflow's editors; the list after it. In the
    room they watch from then on."""
    project = _owned(owner, project_id)
    if not repo.delete_editor_row(project.id, user_id):
        raise repo.NotFoundError(f"User {user_id} does not edit project {project_id}")
    db.session.commit()
    _tell_the_room(project.id, user_id, WATCHER)
    return [_entry(row) for row in repo.editors_of(project.id)]


def _tell_the_room(project_id: str, user_id: int, role: str) -> None:
    """Give the account's participants in the dataflow's room *role* now,
    rather than when they next join. A room that cannot be told never fails
    the change itself."""
    try:
        from utk_curio.backend.app.collaboration.roles import set_user_role

        set_user_role(project_id, user_id, role)
    except Exception:  # noqa: BLE001 - the list is saved either way
        logger.warning("could not tell the room of %s about user %s", project_id, user_id, exc_info=True)
