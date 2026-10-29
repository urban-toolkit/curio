"""In-memory per-room state for real-time collaboration.

Everything in this module is volatile and lives only for the lifetime of
the backend process - room state does not persist across restarts. All
mutations are serialised through a single module-level ``RLock`` because
the SocketIO server is configured with ``async_mode='threading'``.

Each "room" key has the form ``project:<uuid>`` (:func:`room_for`).

A room tells its participants apart by **participant id**, one per socket,
never by account: two tabs of one account, or two hosted guests on the one
guest account, are two participants. A lock names the participant that holds
it, and each participant carries the role its account has on the dataflow
(``projects/access.py``). The socket's own id stays on the server. The
dataflow is not here: it is the server's Yjs doc (``dataflow_docs.py``).
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Dict, List, Optional, Tuple


_lock = threading.RLock()

_room_users: Dict[str, Dict[str, dict]] = {}      # room -> sid -> participant
_room_locks: Dict[str, Dict[str, dict]] = {}      # room -> nodeId -> lock info
_room_meta: Dict[str, dict] = {}                  # room -> bookkeeping
_room_activity: Dict[str, deque] = {}             # room -> ring buffer of events
_sid_index: Dict[str, set] = {}                   # sid -> rooms (for fast cleanup)
_sid_identity: Dict[str, dict] = {}               # sid -> authenticated identity

ACTIVITY_CAP = 200

#: The roles that edit a dataflow (``projects/access.EDIT_ROLES``).
EDIT_ROLES = frozenset({"owner", "editor"})


def room_for(project_id: str) -> str:
    return f"project:{project_id}"


def new_participant_id() -> str:
    return uuid.uuid4().hex


def _now() -> float:
    return time.time()


def _ensure_room(room: str) -> None:
    _room_users.setdefault(room, {})
    _room_locks.setdefault(room, {})
    _room_meta.setdefault(room, {"created_at": _now(), "last_active": _now()})
    _room_activity.setdefault(room, deque(maxlen=ACTIVITY_CAP))


def set_identity(sid: str, identity: dict) -> None:
    """Stash the authenticated identity for a connection.

    Identity must come from the server-side ``UserSession`` (resolved in
    :func:`utk_curio.backend.app.collaboration.auth.authenticate_handshake`),
    never from a client-supplied payload field.
    """
    with _lock:
        _sid_identity[sid] = dict(identity)


def get_identity(sid: str) -> Optional[dict]:
    with _lock:
        ident = _sid_identity.get(sid)
        return dict(ident) if ident is not None else None


def drop_identity(sid: str) -> None:
    with _lock:
        _sid_identity.pop(sid, None)


def add_user(room: str, sid: str, user_info: dict) -> None:
    """Put the participant *user_info* (with its ``participant_id`` and
    ``role``) in *room* for the socket *sid*."""
    with _lock:
        _ensure_room(room)
        _room_users[room][sid] = dict(user_info, joined_at=_now())
        _sid_index.setdefault(sid, set()).add(room)
        _room_meta[room]["last_active"] = _now()


def _release_locks_of(room: str, participant_id: Optional[str]) -> List[str]:
    locks = _room_locks.get(room) or {}
    released = []
    for nid, lock in list(locks.items()):
        if participant_id is not None and lock.get("participant_id") == participant_id:
            locks.pop(nid, None)
            released.append(nid)
    return released


def remove_user(room: str, sid: str) -> Optional[dict]:
    """Remove ``sid`` from ``room`` and release any locks it held.

    Returns the removed participant (with a ``released_locks`` list of
    nodeIds) or ``None`` if the sid wasn't a member.
    """
    with _lock:
        users = _room_users.get(room) or {}
        removed = users.pop(sid, None)
        released_node_ids = _release_locks_of(room, (removed or {}).get("participant_id"))
        rooms = _sid_index.get(sid)
        if rooms is not None:
            rooms.discard(room)
            if not rooms:
                _sid_index.pop(sid, None)
        if removed is not None:
            removed = dict(removed, released_locks=released_node_ids)
        return removed


def release_all_for_sid(sid: str) -> Dict[str, dict]:
    """Drop ``sid`` from every room it joined. Returns ``{room: removed_participant}``."""
    with _lock:
        rooms = list(_sid_index.get(sid, ()))
        result: Dict[str, dict] = {}
        for r in rooms:
            removed = remove_user(r, sid)
            if removed is not None:
                result[r] = removed
        return result


def participant(room: str, sid: str) -> Optional[dict]:
    """The participant the socket *sid* is in *room*, or ``None``."""
    with _lock:
        entry = (_room_users.get(room) or {}).get(sid)
        return dict(entry) if entry is not None else None


def set_user_role(room: str, user_id, role: str) -> Tuple[bool, List[str]]:
    """Give every participant of the account *user_id* in *room* the role
    *role*. Returns whether any changed, and the nodes whose locks they
    released: a watcher holds none."""
    with _lock:
        changed = False
        released: List[str] = []
        for entry in (_room_users.get(room) or {}).values():
            if entry.get("user_id") != user_id or entry.get("role") == role:
                continue
            entry["role"] = role
            changed = True
            if role not in EDIT_ROLES:
                released += _release_locks_of(room, entry.get("participant_id"))
        return changed, released


#: What an agent's lock names besides a person's fields: the agent, and what
#: it writes on the node (``agent_peers.py``).
AGENT_LOCK_FIELDS = ("agent", "writes")


def try_lock(room: str, node_id: str, user_info: dict) -> Optional[dict]:
    """Acquire (or refresh) the soft lock on ``node_id`` for the participant
    *user_info*. An agent's lock also keeps its :data:`AGENT_LOCK_FIELDS`.

    Returns the lock record if it owns it after the call (newly or
    already), otherwise ``None`` (another participant holds it).
    """
    agent = {key: user_info[key] for key in AGENT_LOCK_FIELDS if user_info.get(key) is not None}
    with _lock:
        _ensure_room(room)
        locks = _room_locks[room]
        existing = locks.get(node_id)
        participant_id = user_info.get("participant_id")
        if existing is not None:
            if existing.get("participant_id") == participant_id:
                existing["since"] = _now()
                existing.update(agent)
                return dict(existing)
            return None
        lock = {
            "user_id": user_info.get("user_id"),
            "username": user_info.get("username"),
            "name": user_info.get("name"),
            "participant_id": participant_id,
            "since": _now(),
            **agent,
        }
        locks[node_id] = lock
        return dict(lock)


def release_lock(room: str, node_id: str, participant_id: Optional[str]) -> bool:
    with _lock:
        locks = _room_locks.get(room) or {}
        existing = locks.get(node_id)
        if not existing or participant_id is None or existing.get("participant_id") != participant_id:
            return False
        locks.pop(node_id, None)
        return True


def record_activity(room: str, kind: str, payload: dict) -> dict:
    with _lock:
        _ensure_room(room)
        entry = {"kind": kind, "ts": _now(), "payload": payload}
        _room_activity[room].append(entry)
        return dict(entry)


def snapshot(room: str) -> dict:
    with _lock:
        _ensure_room(room)
        return {
            "users": list(map(dict, _room_users[room].values())),
            "locks": {nid: dict(lock) for nid, lock in _room_locks[room].items()},
            "activity": list(_room_activity[room]),
        }


def users_in(room: str) -> List[dict]:
    with _lock:
        return [dict(entry) for entry in (_room_users.get(room) or {}).values()]


def is_member(room: str, sid: str) -> bool:
    with _lock:
        return sid in (_room_users.get(room) or {})


def reset_for_tests() -> None:
    """Test-only utility - wipe every dict."""
    with _lock:
        _room_users.clear()
        _room_locks.clear()
        _room_meta.clear()
        _room_activity.clear()
        _sid_index.clear()
        _sid_identity.clear()
