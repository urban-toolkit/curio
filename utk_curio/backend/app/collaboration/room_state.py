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
(``projects/access.py``). Every guest, and every tab of a Curio with no
sign-in, signs in to the one guest account, so the room numbers that
account's tabs (:data:`GUEST_NUMBER`), which name each of them apart. The
socket's own id stays on the server. The dataflow is not here: it is the
server's Yjs doc (``dataflow_docs.py``).
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


#: The number of a tab of the guest account in its room: the lowest no other
#: participant of the room holds when the tab joins (:func:`add_user`), free
#: again once it leaves. Its chip, its cursor, its locks and its Activity lines
#: say it, "Shared Guest 2"; its chip and its cursor are in that number's color.
GUEST_NUMBER = "guest_number"


def numbered(participant: Optional[dict]) -> dict:
    """*participant*'s :data:`GUEST_NUMBER` as a field of its own, for what
    names it; nothing for a participant with none."""
    number = (participant or {}).get(GUEST_NUMBER)
    return {} if number is None else {GUEST_NUMBER: number}


def _free_number(users: Dict[str, dict], sid: str) -> int:
    """The lowest number no participant in *users* but *sid*'s holds."""
    held = {entry.get(GUEST_NUMBER) for other, entry in users.items() if other != sid}
    number = 1
    while number in held:
        number += 1
    return number


def add_user(room: str, sid: str, user_info: dict) -> dict:
    """Put the participant *user_info* (with its ``participant_id`` and
    ``role``) in *room* for the socket *sid*; the participant as the room keeps
    it. A socket signed in to a guest account, the one every guest signs in
    to, is numbered (:data:`GUEST_NUMBER`), and keeps its number when it joins
    again."""
    with _lock:
        _ensure_room(room)
        users = _room_users[room]
        entry = dict(user_info, joined_at=_now())
        if (_sid_identity.get(sid) or {}).get("is_guest"):
            entry[GUEST_NUMBER] = (users.get(sid) or {}).get(GUEST_NUMBER) or _free_number(users, sid)
        users[sid] = entry
        _sid_index.setdefault(sid, set()).add(room)
        _room_meta[room]["last_active"] = _now()
        return dict(entry)


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


def sign_in_of(room: str, participant_id: Optional[str]) -> Optional[str]:
    """The sign-in of the socket that is *participant_id* in *room*, as text:
    the id of the session its handshake signed in with, which tells apart the
    tabs of the one guest account in different browsers. ``None`` when no
    socket of the room is that participant."""
    if participant_id is None:
        return None
    with _lock:
        for sid, entry in (_room_users.get(room) or {}).items():
            if entry.get("participant_id") == participant_id:
                session = (_sid_identity.get(sid) or {}).get("token_session_id")
                return None if session is None else str(session)
    return None


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
    *user_info*. An agent's lock also keeps its :data:`AGENT_LOCK_FIELDS`, and
    a tab of the guest account's its :data:`GUEST_NUMBER`.

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
            **numbered(user_info),
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


def edit_sids(room: str) -> List[str]:
    """The sockets in *room* whose participant edits the dataflow, its owner's
    and its editors' (:data:`EDIT_ROLES`), by the roles they have now."""
    with _lock:
        return [sid for sid, entry in (_room_users.get(room) or {}).items() if entry.get("role") in EDIT_ROLES]


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
