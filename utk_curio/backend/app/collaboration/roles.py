"""A change to a dataflow's editors, told to its room as it happens.

``projects/access.py`` calls :func:`set_user_role` after it adds or removes an
editor, so the account's participants edit or watch at once, without joining
again. A removed editor's locks go with their edit rights. Nothing happens
when the account is not in the room.
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
