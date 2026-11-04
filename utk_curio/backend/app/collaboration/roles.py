"""What a dataflow's room hears by role: a change to its editors, and what
only those who edit it hear.

``projects/access.py`` calls :func:`set_user_role` after it adds or removes an
editor, so the account's participants edit or watch at once, without joining
again. A removed editor's locks go with their edit rights. Nothing happens
when the account is not in the room. :func:`tell_editors` tells only the tabs
of the owner and the editors, as an agent's chat turns reach them
(``agents/application/turns/turn_jobs.py``): a watcher's tab hears nothing.
"""
from __future__ import annotations

from utk_curio.backend.app.collaboration import room_state


def set_user_role(project_id: str, user_id, role: str) -> bool:
    """Give *user_id*'s participants in *project_id*'s room *role*, and tell
    the room. Whether anyone's role changed."""
    from utk_curio.backend import extensions
    from utk_curio.backend.config import COLLAB_NAMESPACE

    sio = extensions.socketio
    if sio is None:
        return False
    room = room_state.room_for(project_id)
    changed, released = room_state.set_user_role(room, user_id, role)
    if not changed:
        return False
    for node_id in released:
        sio.emit("node_unlocked", {"nodeId": node_id}, to=room, namespace=COLLAB_NAMESPACE)
    sio.emit("roles_changed", {"users": room_state.users_in(room)}, to=room, namespace=COLLAB_NAMESPACE)
    room_state.record_activity(room, "role_changed", {"user_id": user_id, "role": role})
    return True


def tell_editors(project_id: str, event: str, payload: dict, *, app=None) -> int:
    """Tell *event* with *payload* to the tabs in *project_id*'s room that
    edit the dataflow, its owner's and its editors', each tab's role read now:
    a watcher's tab is told nothing. *app* is the app whose SocketIO server
    sends it, for a thread that holds no app context; else the app at hand's,
    else the backend's. How many tabs were told."""
    from utk_curio.backend import extensions
    from utk_curio.backend.config import COLLAB_NAMESPACE

    sio = (app.extensions.get("socketio") if app is not None else None) or _app_socketio() or extensions.socketio
    if sio is None:
        return 0
    sids = room_state.edit_sids(room_state.room_for(project_id))
    for sid in sids:
        sio.emit(event, payload, to=sid, namespace=COLLAB_NAMESPACE)
    return len(sids)


def _app_socketio():
    """The SocketIO server of the app at hand, if any."""
    from flask import current_app, has_app_context

    return current_app.extensions.get("socketio") if has_app_context() else None
