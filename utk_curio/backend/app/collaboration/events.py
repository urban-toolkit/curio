"""Socket.IO event handlers for real-time collaboration.

Mounted on the namespace declared by ``COLLAB_NAMESPACE`` (default
``/collab``). Every handler enforces these before it changes any state:

1. The sid has a saved session from the handshake (i.e. the user is
   authenticated). Identity is always read from that saved session,
   never from the client-supplied event payload.
2. For room-scoped events, the sid is a current member of the room it
   targets. This is defence-in-depth on top of Socket.IO's own room
   bookkeeping.
3. For an event that changes the room (a node or edge relay, a code-change
   request, a vote, taking a lock, a broadcast output or conflict choice),
   the participant edits the dataflow: ``access.room_role``, asked again for
   each such event, says owner or editor (an account the owner invited). A
   watcher's is refused with ``read_only``.

A join takes the same ``room_role``, which the room's list shows, and a change
to the editors reaches the room at once (``roles.py``). A join is refused for
a dataflow that does not exist, and for a hosted guest's join to a dataflow a
guest owns (``access.joins_room``: the examples every hosted guest opens as
its own), so each such canvas stays its own.

Each socket is one participant, with an id of its own that its join answers
with: two tabs of one account, or two hosted guests on the one guest account,
are told apart by it (``room_state.py``).

The room key is always ``project:<uuid>``; the project UUID matches the
canonical project identifier surfaced by the frontend
``projectPackagesStore``.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Optional

from flask import request
from flask_socketio import ConnectionRefusedError, join_room

from utk_curio.backend.app.collaboration import room_state
from utk_curio.backend.app.collaboration.auth import authenticate_handshake
from utk_curio.backend.config import COLLAB_NAMESPACE


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

#: What a watcher's edit is answered with.
READ_ONLY_REFUSAL = (
    "You are watching this dataflow: only its owner and the editors they "
    "invited can change it."
)
#: What a hosted guest's join to a dataflow a guest owns is answered with.
GUEST_OWNED_REFUSAL = "A guest's canvas of this dataflow is its own, so it joins no room."


def _valid_project_id(value) -> bool:
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def _sender(entry: dict) -> dict:
    """Who sent an event, as its relay names them."""
    return {
        "user_id": entry.get("user_id"),
        "username": entry.get("username"),
        "participant_id": entry.get("participant_id"),
    }


def _account(sess: dict):
    """The socket's account, as ``access.room_role`` reads one."""
    return SimpleNamespace(id=sess.get("user_id"), is_guest=bool(sess.get("is_guest")))


def _project(project_id: str):
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.extensions import db

    return db.session.get(Project, project_id)


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
        room = room_state.room_for(project_id)
        if not room_state.is_member(room, request.sid):
            return None, None, {"ok": False, "error": "not_joined"}
        return sess, room, None

    def _editing(payload):
        """``_gated``, for an event that changes the room: returns (room,
        participant, ack_err), refusing a watcher's. The role is asked again
        here (``access.room_role``), not taken from the join."""
        from utk_curio.backend.app.projects import access

        sess, room, err = _gated(payload)
        if err:
            return None, None, err
        me = room_state.participant(room, request.sid)
        if me is None:
            return None, None, {"ok": False, "error": "not_joined"}
        role = access.room_role(_account(sess), _project(payload["projectId"]))
        if role not in access.EDIT_ROLES:
            return None, None, {"ok": False, "error": "read_only", "message": READ_ONLY_REFUSAL}
        return room, me, None

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
            "participant_id": room_state.new_participant_id(),
        })

    @sio.on("disconnect", namespace=ns)
    def _disconnect():
        # The one disconnect handler of the namespace: the socket's tab also
        # leaves each dataflow doc it synced, and its awareness is cleared.
        from utk_curio.backend.app.collaboration import dataflow_docs

        dataflow_docs.leave(request.sid)
        rooms_left = room_state.release_all_for_sid(request.sid)
        room_state.drop_identity(request.sid)
        for room, info in rooms_left.items():
            users = room_state.users_in(room)
            sio.emit(
                "user_left",
                {
                    "user_id": info.get("user_id"),
                    "username": info.get("username"),
                    "participant_id": info.get("participant_id"),
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
        from utk_curio.backend.app.projects import access

        sess, _room, err = _gated(payload, require_room=False)
        if err:
            return err
        project_id = (payload or {}).get("projectId")
        if not _valid_project_id(project_id):
            return {"ok": False, "error": "invalid_project_id"}
        project = _project(project_id)
        if project is None:
            return {"ok": False, "error": "unknown_project"}
        account = _account(sess)
        if not access.joins_room(account, project):
            return {"ok": False, "error": "guest_owned", "message": GUEST_OWNED_REFUSAL}
        role = access.room_role(account, project)
        room = room_state.room_for(project_id)
        join_room(room, namespace=ns)
        user_info = {
            "user_id": sess["user_id"],
            "username": sess["username"],
            "name": sess.get("name") or sess["username"],
            "profile_image": sess.get("profile_image"),
            "participant_id": sess["participant_id"],
            "role": role,
        }
        room_state.add_user(room, request.sid, user_info)
        room_state.record_activity(room, "user_joined", {
            "user_id": sess["user_id"], "username": sess["username"], "role": role,
        })
        snap = room_state.snapshot(room)
        sio.emit(
            "user_joined",
            {**user_info, "users": snap["users"]},
            to=room, skip_sid=request.sid, namespace=ns,
        )
        return {
            "ok": True,
            "snapshot": snap,
            "participant_id": sess["participant_id"],
            "role": role,
        }

    # ------------------------------------------------------------------
    # Per-node soft locks
    # ------------------------------------------------------------------

    @sio.on("node_lock", namespace=ns)
    def _node_lock(payload):
        room, me, err = _editing(payload)
        if err:
            return err
        node_id = (payload or {}).get("nodeId")
        if not node_id:
            return {"ok": False, "error": "invalid_payload"}
        lock = room_state.try_lock(room, node_id, me)
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
        released = room_state.release_lock(room, node_id, sess.get("participant_id"))
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
            room, me, err = _editing(payload)
            if err:
                return err
            relay_payload = dict(payload or {})
            relay_payload["from"] = _sender(me)
            sio.emit(
                event_name, relay_payload,
                to=room, skip_sid=request.sid, namespace=ns,
            )
            room_state.bump_version(room)
            activity_payload = {
                "by": me["username"],
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
        room, me, err = _editing(payload)
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
            "proposed_by": _sender(me),
        })
        sio.emit(
            "code_change_proposed", proposal,
            to=room, namespace=ns,
        )
        room_state.record_activity(room, "code_change_proposed", {
            "nodeId": node_id, "by": me["username"], "kind": kind,
        })
        return {"ok": True, "proposal": proposal}

    def _vote(payload, approve: bool):
        room, me, err = _editing(payload)
        if err:
            return None, err
        proposal_id = (payload or {}).get("proposalId")
        if not proposal_id:
            return None, {"ok": False, "error": "invalid_payload"}
        prop = room_state.vote_proposal(room, proposal_id, me["participant_id"], approve)
        if prop is None:
            return None, {"ok": False, "error": "unknown_proposal"}
        return (room, me, prop), None

    @sio.on("approve_code_change", namespace=ns)
    def _approve_code_change(payload):
        ctx, err = _vote(payload, True)
        if err:
            return err
        room, me, prop = ctx
        # Everyone else who edits the dataflow approves; a watcher has no vote.
        voters = room_state.voters(room, prop)
        approvals = set(prop.get("approvals") or [])
        all_approved = bool(voters) and all(v in approvals for v in voters)
        sio.emit(
            "code_change_voted",
            {
                "proposalId": prop["id"],
                "by": me["username"],
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
        room, me, prop = ctx
        room_state.remove_proposal(room, prop["id"])
        sio.emit(
            "code_change_rejected",
            {
                "proposalId": prop["id"],
                "by": me["username"],
                "proposal": prop,
            },
            to=room, namespace=ns,
        )
        room_state.record_activity(room, "code_change_rejected", {
            "nodeId": prop.get("nodeId"),
            "kind": prop.get("kind"),
            "by": me["username"],
        })
        return {"ok": True}

    # ------------------------------------------------------------------
    # Output broadcast (preserves sandbox isolation — no cross-session /get)
    # ------------------------------------------------------------------

    @sio.on("output_produced", namespace=ns)
    def _output_produced(payload):
        room, me, err = _editing(payload)
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
                "from": _sender(me),
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
        room, me, err = _editing(payload)
        if err:
            return err
        sio.emit(
            "conflict_resolved",
            {
                **(payload or {}),
                "by": _sender(me),
            },
            to=room, namespace=ns,
        )
        room_state.record_activity(room, "conflict_resolved", {
            "by": me["username"],
            "choice": (payload or {}).get("choice"),
        })
        return {"ok": True}
