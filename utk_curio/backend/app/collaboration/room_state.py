"""In-memory per-room state for real-time collaboration.

Everything in this module is volatile and lives only for the lifetime of
the backend process — room state does not persist across restarts. All
mutations are serialised through a single module-level ``RLock`` because
the SocketIO server is configured with ``async_mode='threading'``.

Each "room" key has the form ``project:<uuid>``; see ``events.py``.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Dict, List, Optional


_lock = threading.RLock()

_room_users: Dict[str, Dict[str, dict]] = {}      # room -> sid -> user_info
_room_locks: Dict[str, Dict[str, dict]] = {}      # room -> nodeId -> lock info
_room_graph: Dict[str, dict] = {}                 # room -> {"nodes": {...}, "edges": {...}}
_room_outputs: Dict[str, Dict[str, dict]] = {}    # room -> nodeId -> last output payload
_room_versions: Dict[str, int] = {}               # room -> monotonic counter
_room_meta: Dict[str, dict] = {}                  # room -> bookkeeping
_room_activity: Dict[str, deque] = {}             # room -> ring buffer of events
_room_proposals: Dict[str, Dict[str, dict]] = {}  # room -> proposal_id -> proposal
_sid_index: Dict[str, set] = {}                   # sid -> rooms (for fast cleanup)
_sid_identity: Dict[str, dict] = {}               # sid -> authenticated identity

ACTIVITY_CAP = 200


def _now() -> float:
    return time.time()


def _ensure_room(room: str) -> None:
    _room_users.setdefault(room, {})
    _room_locks.setdefault(room, {})
    _room_graph.setdefault(room, {"nodes": {}, "edges": {}})
    _room_outputs.setdefault(room, {})
    _room_versions.setdefault(room, 0)
    _room_meta.setdefault(room, {"created_at": _now(), "last_active": _now()})
    _room_activity.setdefault(room, deque(maxlen=ACTIVITY_CAP))
    _room_proposals.setdefault(room, {})


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
    with _lock:
        _ensure_room(room)
        _room_users[room][sid] = dict(user_info, sid=sid, joined_at=_now())
        _sid_index.setdefault(sid, set()).add(room)
        _room_meta[room]["last_active"] = _now()


def remove_user(room: str, sid: str) -> Optional[dict]:
    """Remove ``sid`` from ``room`` and release any locks it held.

    Returns the removed user_info dict (with a ``released_locks`` list
    of nodeIds) or ``None`` if the sid wasn't a member.
    """
    with _lock:
        users = _room_users.get(room) or {}
        removed = users.pop(sid, None)
        locks = _room_locks.get(room) or {}
        released_node_ids = []
        for nid, lock in list(locks.items()):
            if lock.get("sid") == sid:
                locks.pop(nid, None)
                released_node_ids.append(nid)
        rooms = _sid_index.get(sid)
        if rooms is not None:
            rooms.discard(room)
            if not rooms:
                _sid_index.pop(sid, None)
        if removed is not None:
            removed["released_locks"] = released_node_ids
        return removed


def release_all_for_sid(sid: str) -> Dict[str, dict]:
    """Drop ``sid`` from every room it joined. Returns ``{room: removed_user_info}``."""
    with _lock:
        rooms = list(_sid_index.get(sid, ()))
        result: Dict[str, dict] = {}
        for r in rooms:
            removed = remove_user(r, sid)
            if removed is not None:
                result[r] = removed
        return result


def try_lock(room: str, node_id: str, user_info: dict, sid: str) -> Optional[dict]:
    """Acquire (or refresh) the soft lock on ``node_id``.

    Returns the lock record if we own it after the call (newly or
    already), otherwise ``None`` (another user holds it).
    """
    with _lock:
        _ensure_room(room)
        locks = _room_locks[room]
        existing = locks.get(node_id)
        if existing is not None:
            if existing.get("sid") == sid:
                existing["since"] = _now()
                return dict(existing)
            return None
        lock = {
            "user_id": user_info.get("user_id"),
            "username": user_info.get("username"),
            "name": user_info.get("name"),
            "sid": sid,
            "since": _now(),
        }
        locks[node_id] = lock
        return dict(lock)


def release_lock(room: str, node_id: str, sid: str) -> bool:
    with _lock:
        locks = _room_locks.get(room) or {}
        existing = locks.get(node_id)
        if not existing or existing.get("sid") != sid:
            return False
        locks.pop(node_id, None)
        return True


def bump_version(room: str) -> int:
    with _lock:
        _ensure_room(room)
        _room_versions[room] += 1
        _room_meta[room]["last_active"] = _now()
        return _room_versions[room]


def record_activity(room: str, kind: str, payload: dict) -> dict:
    with _lock:
        _ensure_room(room)
        entry = {"kind": kind, "ts": _now(), "payload": payload}
        _room_activity[room].append(entry)
        return dict(entry)


def set_output(room: str, node_id: str, output: dict) -> None:
    with _lock:
        _ensure_room(room)
        _room_outputs[room][node_id] = dict(output, ts=_now())


def add_proposal(room: str, proposal: dict) -> dict:
    with _lock:
        _ensure_room(room)
        pid = proposal.get("id") or str(uuid.uuid4())
        record = dict(
            proposal, id=pid, created_at=_now(),
            approvals=[], rejections=[],
        )
        _room_proposals[room][pid] = record
        return dict(record)


def get_proposal(room: str, proposal_id: str) -> Optional[dict]:
    with _lock:
        prop = (_room_proposals.get(room) or {}).get(proposal_id)
        return dict(prop) if prop else None


def vote_proposal(
    room: str, proposal_id: str, sid: str, approve: bool,
) -> Optional[dict]:
    with _lock:
        prop = (_room_proposals.get(room) or {}).get(proposal_id)
        if not prop:
            return None
        bucket = "approvals" if approve else "rejections"
        if sid not in prop[bucket]:
            prop[bucket].append(sid)
        return dict(prop)


def remove_proposal(room: str, proposal_id: str) -> Optional[dict]:
    with _lock:
        return (_room_proposals.get(room) or {}).pop(proposal_id, None)


def snapshot(room: str) -> dict:
    with _lock:
        _ensure_room(room)
        return {
            "users": list(_room_users[room].values()),
            "locks": dict(_room_locks[room]),
            "outputs": dict(_room_outputs[room]),
            "proposals": list(_room_proposals[room].values()),
            "activity": list(_room_activity[room]),
            "version": _room_versions[room],
        }


def users_in(room: str) -> List[dict]:
    with _lock:
        return list((_room_users.get(room) or {}).values())


def is_member(room: str, sid: str) -> bool:
    with _lock:
        return sid in (_room_users.get(room) or {})


def reset_for_tests() -> None:
    """Test-only utility — wipe every dict."""
    with _lock:
        _room_users.clear()
        _room_locks.clear()
        _room_graph.clear()
        _room_outputs.clear()
        _room_versions.clear()
        _room_meta.clear()
        _room_activity.clear()
        _room_proposals.clear()
        _sid_index.clear()
        _sid_identity.clear()
