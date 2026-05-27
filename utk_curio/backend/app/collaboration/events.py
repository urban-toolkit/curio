"""Socket.IO event handlers for real-time collaboration.

Mounted on the namespace declared by ``COLLAB_NAMESPACE`` (default
``/collab``). Every handler enforces two invariants before mutating any
state:

1. The sid has a saved session from the handshake (i.e. the user is
   authenticated). Identity is always read from that saved session,
   never from the client-supplied event payload.
2. For room-scoped events, the sid is a current member of the room it
   targets. This is defence-in-depth on top of Socket.IO's own room
   bookkeeping.

The room key is always ``project:<uuid>``; the project UUID matches the
canonical project identifier surfaced by the frontend
``projectPackagesStore``.
"""

from __future__ import annotations

import re
from typing import Optional

from flask import request
from flask_socketio import ConnectionRefusedError, join_room, leave_room

from utk_curio.backend.app.collaboration import room_state
from utk_curio.backend.app.collaboration.auth import authenticate_handshake
from utk_curio.backend.config import COLLAB_NAMESPACE


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _room_for(project_id: str) -> str:
    return f"project:{project_id}"


def _valid_project_id(value) -> bool:
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def register(sio):
    """Attach every collaboration handler to the SocketIO singleton."""
    ns = COLLAB_NAMESPACE

    def _session() -> Optional[dict]:
        # Identity is stored in room_state (our own dict) rather than via
        # ``sio.server.save_session`` so we don't depend on the engineio
        # session-lifecycle quirks that vary between transports / test
        # clients. The store is populated only after a successful Bearer
        # handshake in the ``connect`` handler below.
        return room_state.get_identity(request.sid)

    def _gated(payload, *, require_room: bool = True):
        """Common entry guard. Returns (sess, room, ack_err) where ack_err
        is non-None when the call should be rejected.
        """
        sess = _session()
        if not sess:
            return None, None, {"ok": False, "error": "unauthorized"}
        if not require_room:
            return sess, None, None
        project_id = (payload or {}).get("projectId")
        if not _valid_project_id(project_id):
            return None, None, {"ok": False, "error": "invalid_project_id"}
        room = _room_for(project_id)
        if not room_state.is_member(room, request.sid):
            return None, None, {"ok": False, "error": "not_joined"}
        return sess, room, None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @sio.on("connect", namespace=ns)
    def _connect(auth):
        try:
            session, user = authenticate_handshake(auth, request.environ)
        except ConnectionRefusedError:
            raise
        except Exception as exc:  # noqa: BLE001 — never leak details to client
            raise ConnectionRefusedError("unauthorized") from exc
        room_state.set_identity(request.sid, {
            "user_id": user.id,
            "username": user.username,
            "name": user.name or user.username,
            "profile_image": user.profile_image,
            "is_guest": bool(user.is_guest),
            "token_session_id": session.id,
        })

    @sio.on("disconnect", namespace=ns)
    def _disconnect():
        rooms_left = room_state.release_all_for_sid(request.sid)
        room_state.drop_identity(request.sid)
        for room, info in rooms_left.items():
            users = room_state.users_in(room)
            sio.emit(
                "user_left",
                {
                    "user_id": info.get("user_id"),
                    "username": info.get("username"),
                    "released_locks": info.get("released_locks", []),
                    "users": users,
                },
                to=room, namespace=ns,
            )
            room_state.record_activity(room, "user_left", {
                "user_id": info.get("user_id"),
                "username": info.get("username"),
            })

    # ------------------------------------------------------------------
    # Room membership
    # ------------------------------------------------------------------

    @sio.on("join_session", namespace=ns)
    def _join(payload):
        sess, _room, err = _gated(payload, require_room=False)
        if err:
            return err
        project_id = (payload or {}).get("projectId")
        if not _valid_project_id(project_id):
            return {"ok": False, "error": "invalid_project_id"}
        room = _room_for(project_id)
        join_room(room, namespace=ns)
        user_info = {
            "user_id": sess["user_id"],
            "username": sess["username"],
            "name": sess.get("name") or sess["username"],
            "profile_image": sess.get("profile_image"),
        }
        room_state.add_user(room, request.sid, user_info)
        room_state.record_activity(room, "user_joined", {
            "user_id": sess["user_id"], "username": sess["username"],
        })
        snap = room_state.snapshot(room)
        sio.emit(
            "user_joined",
            {**user_info, "users": snap["users"]},
            to=room, skip_sid=request.sid, namespace=ns,
        )
        return {"ok": True, "snapshot": snap}

    @sio.on("leave_session", namespace=ns)
    def _leave(payload):
        sess, room, err = _gated(payload)
        if err:
            return err
        removed = room_state.remove_user(room, request.sid)
        leave_room(room, namespace=ns)
        if removed:
            sio.emit(
                "user_left",
                {
                    "user_id": removed.get("user_id"),
                    "username": removed.get("username"),
                    "released_locks": removed.get("released_locks", []),
                    "users": room_state.users_in(room),
                },
                to=room, namespace=ns,
            )
        return {"ok": True}

    # ------------------------------------------------------------------
    # Per-node soft locks
    # ------------------------------------------------------------------

    @sio.on("node_lock", namespace=ns)
    def _node_lock(payload):
        sess, room, err = _gated(payload)
        if err:
            return err
        node_id = (payload or {}).get("nodeId")
        if not node_id:
            return {"ok": False, "error": "invalid_payload"}
        user_info = {
            "user_id": sess["user_id"],
            "username": sess["username"],
            "name": sess.get("name") or sess["username"],
        }
        lock = room_state.try_lock(room, node_id, user_info, request.sid)
        if lock is None:
            return {"ok": False, "error": "locked_by_other"}
        sio.emit(
            "node_locked",
            {"nodeId": node_id, "lock": lock},
            to=room, namespace=ns,
        )
        return {"ok": True, "lock": lock}

    @sio.on("node_unlock", namespace=ns)
    def _node_unlock(payload):
        sess, room, err = _gated(payload)
        if err:
            return err
        node_id = (payload or {}).get("nodeId")
        if not node_id:
            return {"ok": False, "error": "invalid_payload"}
        released = room_state.release_lock(room, node_id, request.sid)
        if not released:
            return {"ok": False, "error": "not_lock_owner"}
        sio.emit(
            "node_unlocked",
            {"nodeId": node_id},
            to=room, namespace=ns,
        )
        return {"ok": True}

    # ------------------------------------------------------------------
    # Graph relay (no merge logic — frontend ReactFlow is authoritative)
    # ------------------------------------------------------------------

    def _make_relay(event_name: str, activity_kind: str):
        def _handler(payload):
            sess, room, err = _gated(payload)
            if err:
                return err
            relay_payload = dict(payload or {})
            relay_payload["from"] = {
                "user_id": sess["user_id"],
                "username": sess["username"],
            }
            sio.emit(
                event_name, relay_payload,
                to=room, skip_sid=request.sid, namespace=ns,
            )
            room_state.bump_version(room)
            activity_payload = {
                "by": sess["username"],
                "payload": {
                    k: payload.get(k)
                    for k in ("nodeId", "edgeId", "patch")
                    if payload and k in payload
                },
            }
            room_state.record_activity(room, activity_kind, activity_payload)
            return {"ok": True}
        return _handler

    for event_name in (
        "node_added", "node_updated", "node_removed",
        "edge_added", "edge_removed",
    ):
        sio.on(event_name, namespace=ns)(_make_relay(event_name, event_name))

    # ------------------------------------------------------------------
    # Code-change proposals (peer-approved edits while a lock is held)
    # ------------------------------------------------------------------

    @sio.on("request_code_change", namespace=ns)
    def _request_code_change(payload):
        sess, room, err = _gated(payload)
        if err:
            return err
        node_id = payload.get("nodeId")
        kind = payload.get("kind", "code")  # "code" | "grammar"
        if not node_id or "newValue" not in payload:
            return {"ok": False, "error": "invalid_payload"}
        proposal = room_state.add_proposal(room, {
            "nodeId": node_id,
            "kind": kind,
            "oldValue": payload.get("oldValue"),
            "newValue": payload["newValue"],
            "proposed_by": {
                "user_id": sess["user_id"],
                "username": sess["username"],
                "sid": request.sid,
            },
        })
        sio.emit(
            "code_change_proposed", proposal,
            to=room, namespace=ns,
        )
        room_state.record_activity(room, "code_change_proposed", {
            "nodeId": node_id, "by": sess["username"], "kind": kind,
        })
        return {"ok": True, "proposal": proposal}

    def _vote(payload, approve: bool):
        sess, room, err = _gated(payload)
        if err:
            return None, err
        proposal_id = (payload or {}).get("proposalId")
        if not proposal_id:
            return None, {"ok": False, "error": "invalid_payload"}
        prop = room_state.vote_proposal(room, proposal_id, request.sid, approve)
        if prop is None:
            return None, {"ok": False, "error": "unknown_proposal"}
        return (room, sess, prop), None

    @sio.on("approve_code_change", namespace=ns)
    def _approve_code_change(payload):
        ctx, err = _vote(payload, True)
        if err:
            return err
        room, sess, prop = ctx
        users = room_state.users_in(room)
        proposer_sid = (prop.get("proposed_by") or {}).get("sid")
        peer_sids = [u["sid"] for u in users if u["sid"] != proposer_sid]
        approvals = set(prop.get("approvals") or [])
        all_approved = bool(peer_sids) and all(s in approvals for s in peer_sids)
        sio.emit(
            "code_change_voted",
            {
                "proposalId": prop["id"],
                "by": sess["username"],
                "approve": True,
                "approvals": list(approvals),
                "rejections": list(prop.get("rejections") or []),
            },
            to=room, namespace=ns,
        )
        if all_approved:
            room_state.remove_proposal(room, prop["id"])
            sio.emit(
                "code_change_applied", prop,
                to=room, namespace=ns,
            )
            room_state.record_activity(room, "code_change_applied", {
                "nodeId": prop.get("nodeId"), "kind": prop.get("kind"),
            })
        return {"ok": True, "applied": all_approved}

    @sio.on("reject_code_change", namespace=ns)
    def _reject_code_change(payload):
        ctx, err = _vote(payload, False)
        if err:
            return err
        room, sess, prop = ctx
        room_state.remove_proposal(room, prop["id"])
        sio.emit(
            "code_change_rejected",
            {
                "proposalId": prop["id"],
                "by": sess["username"],
                "proposal": prop,
            },
            to=room, namespace=ns,
        )
        room_state.record_activity(room, "code_change_rejected", {
            "nodeId": prop.get("nodeId"),
            "kind": prop.get("kind"),
            "by": sess["username"],
        })
        return {"ok": True}

    # ------------------------------------------------------------------
    # Output broadcast (preserves sandbox isolation — no cross-session /get)
    # ------------------------------------------------------------------

    @sio.on("output_produced", namespace=ns)
    def _output_produced(payload):
        sess, room, err = _gated(payload)
        if err:
            return err
        node_id = (payload or {}).get("nodeId")
        output = (payload or {}).get("output")
        if not node_id or output is None:
            return {"ok": False, "error": "invalid_payload"}
        room_state.set_output(room, node_id, output)
        sio.emit(
            "output_produced",
            {
                "nodeId": node_id,
                "nodeType": payload.get("nodeType"),
                "output": output,
                "from": {
                    "user_id": sess["user_id"],
                    "username": sess["username"],
                },
            },
            to=room, skip_sid=request.sid, namespace=ns,
        )
        return {"ok": True}

    @sio.on("node_exec_display", namespace=ns)
    def _node_exec_display(payload):
        sess, room, err = _gated(payload)
        if err:
            return err
        node_id = (payload or {}).get("nodeId")
        if not node_id:
            return {"ok": False, "error": "invalid_payload"}
        sio.emit(
            "node_exec_display",
            {"nodeId": node_id, "by": sess["username"]},
            to=room, skip_sid=request.sid, namespace=ns,
        )
        return {"ok": True}

    # ------------------------------------------------------------------
    # Conflict resolution (relay-only — peers update their local view)
    # ------------------------------------------------------------------

    @sio.on("resolve_conflict", namespace=ns)
    def _resolve_conflict(payload):
        sess, room, err = _gated(payload)
        if err:
            return err
        sio.emit(
            "conflict_resolved",
            {
                **(payload or {}),
                "by": {
                    "user_id": sess["user_id"],
                    "username": sess["username"],
                },
            },
            to=room, namespace=ns,
        )
        room_state.record_activity(room, "conflict_resolved", {
            "by": sess["username"],
            "choice": (payload or {}).get("choice"),
        })
        return {"ok": True}
