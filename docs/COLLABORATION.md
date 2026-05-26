# Real-Time Collaboration (experimental)

> [!IMPORTANT]
> Experimental, LAN/dev use only. **Disabled by default**. Enable with `--collab`.

This feature is based on the design originally proposed by [@kirtanpatel2003](https://github.com/kirtanpatel2003) in [#112](https://github.com/urban-toolkit/curio/pull/112). The implementation in this branch was rewritten against the current manifest-node + auth architecture; the event vocabulary and proposal/lock model carry over directly.

## Contents

- [What it does](#what-it-does)
- [Setup](#setup)
- [Architecture](#architecture)
- [Security model](#security-model)
- [Conflict resolution UX](#conflict-resolution-ux)
- [Known limitations](#known-limitations)

## What it does

When two or more users open the same project (`/dataflow/<UUID>`) on a host that was started with `--collab`, they see:

- **Presence** — a side panel lists everyone currently in the project room, with a connection indicator.
- **Per-node soft locks** — focusing a node's editor records a lock for that user; peers see an avatar chip in the node's corner and the editor becomes read-only on their side.
- **Code-change proposals** — when a user blurs a Monaco editor (Python code or Vega grammar) and the contents differ from the loaded baseline, a proposal is broadcast. Peers see Approve / Reject buttons; once every peer approves, the change is applied to all editors at once.
- **Shared execution output** — when a node finishes running on one user's machine, the rendered output payload is broadcast over the socket so peers see the same result without re-running and **without crossing the sandbox session-isolation boundary**.
- **Activity log** — the side panel keeps the last ~20 room events (joins, locks, proposals, applies, conflict resolutions).

## Setup

```bash
# Backend + frontend, opt-in to collaboration:
python curio.py start --auth --collab

# CORS for non-default frontend origins:
COLLAB_CORS_ORIGINS=http://192.168.1.5:8080 python curio.py start --auth --collab
```

Open the project URL (`http://<host>:8080/dataflow/<UUID>`) on each collaborator's browser. The `--collab` flag is read at runtime by the frontend via `/api/config/public` — **no frontend rebuild is required** to flip the flag.

Useful environment variables:

| Var | Default | Purpose |
|-----|---------|---------|
| `ENABLE_COLLAB` | `0` (set by `--collab`) | Master switch. When unset, the SocketIO server is never instantiated and `flask-socketio` is never imported. |
| `COLLAB_CORS_ORIGINS` | `*` | Comma-separated allowed origins for the Socket.IO handshake. Use `*` only on a trusted LAN. |
| `COLLAB_NAMESPACE` | `/collab` | Socket.IO namespace. Change only if you need to coexist with another SocketIO server on the same backend. |

## Architecture

- **Namespace:** `/collab` (overridable via `COLLAB_NAMESPACE`).
- **Transport:** Socket.IO over WebSocket (with polling fallback).
- **Async mode:** `threading` — preserves the existing Flask dev-reloader and avoids the eventlet/gevent monkey-patching trap. Acceptable for small teams (<~20 concurrent sockets); production with many concurrent rooms should switch to `eventlet` or `gevent`.
- **Room key:** `project:<uuid>`. The UUID is the canonical project identifier from the URL (`/dataflow/:id`) and the source of truth in `projectPackagesStore.getCurrentProjectId()`.
- **Room state:** in-memory dicts in [utk_curio/backend/app/collaboration/room_state.py](../utk_curio/backend/app/collaboration/room_state.py), guarded by a single `threading.RLock`. **Not persisted across restarts.**

### Backend modules

| File | Role |
|------|------|
| [extensions.py](../utk_curio/backend/extensions.py) | `init_socketio(app)` — lazy import of `flask_socketio`. |
| [app/__init__.py](../utk_curio/backend/app/__init__.py) | Mounts the SocketIO singleton and registers events when `ENABLE_COLLAB=True`. |
| [app/collaboration/auth.py](../utk_curio/backend/app/collaboration/auth.py) | Bearer-token handshake; resolves the socket to a real `User` + `UserSession`. |
| [app/collaboration/room_state.py](../utk_curio/backend/app/collaboration/room_state.py) | All in-memory dicts and helpers. |
| [app/collaboration/events.py](../utk_curio/backend/app/collaboration/events.py) | Every `@sio.on(...)` handler. Identity is read from `room_state.get_identity(sid)`, populated in the `connect` handler. |

### Frontend modules

| File | Role |
|------|------|
| [providers/CollaborationProvider.tsx](../utk_curio/frontend/urban-workflows/src/providers/CollaborationProvider.tsx) | Fetches `/api/config/public`, opens one socket per project, exposes the `useCollab()` API. **No-op when disabled.** |
| [providers/FlowProvider.tsx](../utk_curio/frontend/urban-workflows/src/providers/FlowProvider.tsx) | Calls `collabRef.current.broadcast*(...)` in node/edge mutation handlers. |
| [components/UniversalNode.tsx](../utk_curio/frontend/urban-workflows/src/components/UniversalNode.tsx) | Lock-on-focus / unlock-on-blur, peer-lock chip, output broadcast on exec completion. |
| [components/editing/CodeEditor.tsx](../utk_curio/frontend/urban-workflows/src/components/editing/CodeEditor.tsx) | Proposal-on-blur for Python code, banner UI, apply-on-receive. |
| [components/editing/GrammarEditor.tsx](../utk_curio/frontend/urban-workflows/src/components/editing/GrammarEditor.tsx) | Same for grammar specs. |
| [components/collab/CollaborationSidePanel.tsx](../utk_curio/frontend/urban-workflows/src/components/collab/CollaborationSidePanel.tsx) | Right-docked Users / Proposals / Activity panel. |

## Security model

- **Identity** is anchored in `UserSession.token` (the same Bearer token used by REST). The token is sent through Socket.IO's `auth` handshake (`io(url, { auth: { token } })`); the server resolves it in [auth.py](../utk_curio/backend/app/collaboration/auth.py) and stashes the `(user_id, username, name, profile_image)` tuple via `room_state.set_identity(sid, ...)`. **Every subsequent event handler reads from that stashed identity, never from the client-supplied payload.** Spoofing `userId`/`username` fields in an event has no effect.
- **Sandbox artifact isolation is preserved.** The check at [sandbox/util/parsers.py:691-697](../utk_curio/sandbox/util/parsers.py) that gates DuckDB artifact reads on `session_id` is **unchanged**. Outputs flow between collaborators over the socket as `output_produced` payloads, not by one user fetching another user's artifact via `/get`.
- **Room access** today is "any signed-in user who knows the project UUID can join". This matches the existing project share model (the URL is the share). A stricter `ProjectCollaborator` ACL is out of scope for v1.
- **Editability of shared dataflows.** Without `--collab`, a non-owner who opens a project URL lands in a read-only "shared view" (project ownership in Curio is single-user). With `--collab` on, that read-only gate stands down so peers can actually collaborate. Edits flow over the socket to the owner's tab, which persists them via the existing auto-save path. **Only the owner writes to disk**; if the owner is offline, collaborator edits are ephemeral. A multi-writer model needs the `ProjectCollaborator` ACL above.
- **No transport encryption out of the box.** Run behind HTTPS for non-LAN deployments.

## Conflict resolution UX

- **Soft locks** are advisory only — they show "user X is editing" but don't physically block the network. They release when the editor blurs (`onDidBlurEditorText`) or when the user disconnects.
- **Code proposals** require approval from every other connected peer. The proposer's editor stays as-typed; peers see a banner with Approve / Reject buttons. On unanimous approval the backend emits `code_change_applied`, and every peer's editor updates atomically.
- **Conflicts** between simultaneous edits are surfaced via the side panel's "Activity" stream; resolution is currently a broadcast-only signal (peers update their local view based on the resolver's choice). Richer 3-way merge UX is future work.

## Known limitations

- **In-memory state.** Room presence, locks, proposals, and activity are stored in process memory. A backend restart drops everything.
- **No transport encryption** is enforced by Curio. Run behind HTTPS for any non-LAN deployment.
- **No room-membership ACL.** Anyone signed in who knows a project UUID can join. Acceptable for the URL-share model; not acceptable for true tenant isolation.
- **Output payload size.** Outputs are relayed as JSON over the socket. Very large outputs (>~256 KB, images, parquet) may render slowly on peers; large-output gating is future work.
- **Lock TTL.** Stale locks are released only on socket disconnect — a laptop suspended mid-edit holds the lock until the socket times out. A configurable idle-TTL is future work.
- **Persistence of activity log.** The 200-entry activity ring buffer is lost on restart.
- **`async_mode="threading"`.** Fine for dev and small teams. Production with many concurrent rooms should switch to `eventlet` or `gevent`.
