# Real-Time Collaboration

> [!IMPORTANT]
> **Disabled by default**. Enable with `--collab`.

This feature is based on the design proposed by [@kirtanpatel2003](https://github.com/kirtanpatel2003) in [#112](https://github.com/urban-toolkit/curio/pull/112).

## Contents

- [What it does](#what-it-does)
- [Who edits: owner, editors and watchers](#who-edits-owner-editors-and-watchers)
- [Setup](#setup)
- [Architecture](#architecture)
- [Security model](#security-model)
- [Conflict resolution UX](#conflict-resolution-ux)
- [Known limitations](#known-limitations)

## What it does

When two or more users open the same project (`/dataflow/<UUID>`) on a host that was started with `--collab`, they see:

- **Presence.** Open the side panel from the 👥 button in the top bar. It lists everyone currently in the project room with their role (owner, editor or watcher), with a connection indicator.
- **Live graph sync.** Adding, removing, or dragging a node propagates to every peer's canvas in real time. Same for edges: connecting two nodes or deleting an edge applies on every other client immediately.
- **Per-node soft locks.** Focusing a node's editor records a lock for that tab; peers see an avatar chip in the node's corner and the editor becomes read-only on their side. Two tabs of one account hold locks of their own.
- **Code-change proposals.** When an editor blurs a Monaco editor (Python code or Vega grammar) and the contents differ from the loaded baseline, a proposal is broadcast. Everyone else who edits sees Approve / Reject buttons; once they all approve, the change is applied to all editors at once.
- **Shared execution output.** When a node finishes running on one user's machine, the rendered output payload is broadcast over the socket so peers see the same result without re-running and **without crossing the sandbox session-isolation boundary**.
- **Activity log.** The side panel keeps the last 200 room events (joins, locks, proposals, applies, conflict resolutions); see `ACTIVITY_CAP` in [`room_state.py`](../utk_curio/backend/app/collaboration/room_state.py).

## Who edits: owner, editors and watchers

Everyone in a dataflow's room has a role, which the server decides when they join and checks on every change:

| Role | Who | What they do |
|------|-----|--------------|
| Owner | The account that owns the dataflow | Edits, and saves the dataflow from their tab. Invites and removes editors. |
| Editor | An account the owner invited | Edits the canvas: nodes and edges they add, move or remove, and code changes the room approves, reach everyone. |
| Watcher | Anyone else signed in who opens the dataflow's link | Watches read-only: the canvas shows every change as it lands, and the server refuses theirs. |

**Inviting editors.** The owner opens **Share > Invite editors**, types an account's username and presses **Add**. The editors are listed below it, each with a remove button. The editor opens the dataflow's link (**Share > Copy dataflow link**) as anyone does, and edits once the room names them an editor. Adding or removing an editor applies at once, also to someone already in the room. A guest is never an editor, and a guest invites nobody.

**Saving.** The owner's tab saves the dataflow: an editor's change marks it Unsaved there, and the owner's next save, or its auto-save, keeps it. An editor or a watcher saves a copy with **File > Save dataflow**, as on any shared dataflow.

**Hosted guests.** On a Curio started with `--deploy`, every guest shares one account, which also owns the example dataflows. Such a guest watches other accounts' dataflows. It joins no room of an example, so each guest's canvas of one stays its own, and the server refuses its saves.

## Setup

```bash
# Backend + frontend, opt-in to collaboration:
python curio.py start --deploy --collab

# Only these frontend origins may connect:
python curio.py start --deploy --collab --collab-origins http://192.168.1.5:8080
```

`--deploy` gives each person an account of their own, which the owner invites as an editor by its username. It needs a host that can isolate node execution, such as Curio's Docker image; see [DEPLOYMENT.md](DEPLOYMENT.md).

Open the project URL (`http://<host>:8080/dataflow/<UUID>`) on each collaborator's browser. The `--collab` flag is read at runtime by the frontend via `/api/config/public`, so **no frontend rebuild is required** to flip the flag.

| Flag | Variable | Default | Purpose |
|------|----------|---------|---------|
| `--collab` | `ENABLE_COLLAB` | off | Master switch. When off, the SocketIO server is never instantiated and `flask-socketio` is never imported. |
| `--collab-origins ORIGINS` | `COLLAB_CORS_ORIGINS` | `*` | Comma-separated allowed origins for the Socket.IO handshake. Use `*` only on a trusted network. |
| `--collab-namespace NAMESPACE` | `COLLAB_NAMESPACE` | `/collab` | Socket.IO namespace. Change only if you need to coexist with another SocketIO server on the same backend. |

## Architecture

- **Namespace:** `/collab`, or the one `--collab-namespace` sets; the page reads it from `/api/config/public`.
- **Transport:** Socket.IO over WebSocket (with polling fallback).
- **Async mode:** `threading`, which preserves the existing Flask dev-reloader and avoids the eventlet/gevent monkey-patching trap. Acceptable for small teams (<~20 concurrent sockets); production with many concurrent rooms should switch to `eventlet` or `gevent`.
- **Room key:** `project:<uuid>`. The UUID is the canonical project identifier from the URL (`/dataflow/:id`) and the source of truth in `projectPackagesStore.getCurrentProjectId()`.
- **Room state:** in-memory dicts in [utk_curio/backend/app/collaboration/room_state.py](../utk_curio/backend/app/collaboration/room_state.py), guarded by a single `threading.RLock`. **Not persisted across restarts.**

### Backend modules

| File | Role |
|------|------|
| [extensions.py](../utk_curio/backend/extensions.py) | `init_socketio(app)`, a lazy import of `flask_socketio`. |
| [app/__init__.py](../utk_curio/backend/app/__init__.py) | Mounts the SocketIO singleton and registers events when `ENABLE_COLLAB=True`. |
| [app/collaboration/auth.py](../utk_curio/backend/app/collaboration/auth.py) | Bearer-token handshake; resolves the socket to a real `User` + `UserSession`. |
| [app/collaboration/room_state.py](../utk_curio/backend/app/collaboration/room_state.py) | All in-memory dicts and helpers. Participants, locks, proposals and votes are keyed by participant id, one per socket. |
| [app/collaboration/events.py](../utk_curio/backend/app/collaboration/events.py) | Every `@sio.on(...)` handler. Identity is read from `room_state.get_identity(sid)`, populated in the `connect` handler. A join takes the account's role; every change to the room is refused to a watcher. |
| [app/collaboration/roles.py](../utk_curio/backend/app/collaboration/roles.py) | Tells a room that the owner added or removed an editor (`roles_changed`). |
| [app/projects/access.py](../utk_curio/backend/app/projects/access.py) | The roles, and the editors list behind **Invite editors** (`/api/projects/<id>/editors`). |

### Frontend modules

| File | Role |
|------|------|
| [providers/CollaborationProvider.tsx](../utk_curio/frontend/urban-workflows/src/providers/CollaborationProvider.tsx) | Fetches `/api/config/public`, opens one socket per project, exposes the `useCollab()` API: the tab's participant id and role among them. **No-op when disabled.** |
| [providers/collab/participants.ts](../utk_curio/frontend/urban-workflows/src/providers/collab/participants.ts) | Tells participants apart by participant id: whether a lock or a proposal is this tab's, a tab's role, who votes. |
| [hook/useSharedView.ts](../utk_curio/frontend/urban-workflows/src/hook/useSharedView.ts) | Whether the canvas is read-only: a watcher's. Every gate on editing reads it. |
| [providers/flow/useGraphEdits.ts](../utk_curio/frontend/urban-workflows/src/providers/flow/useGraphEdits.ts), [providers/flow/useConnect.ts](../utk_curio/frontend/urban-workflows/src/providers/flow/useConnect.ts) | Call `collabRef.current.broadcast*(...)` in node/edge mutation handlers. |
| [providers/flow/useCollaborationSync.ts](../utk_curio/frontend/urban-workflows/src/providers/flow/useCollaborationSync.ts) | Applies peers' node and edge changes to the canvas without broadcasting them again. |
| [components/UniversalNode.tsx](../utk_curio/frontend/urban-workflows/src/components/UniversalNode.tsx) | Lock-on-focus / unlock-on-blur, peer-lock chip, output broadcast on exec completion. |
| [components/editing/CodeEditor.tsx](../utk_curio/frontend/urban-workflows/src/components/editing/CodeEditor.tsx) | Proposal-on-blur for Python code, banner UI, apply-on-receive. |
| [components/editing/GrammarEditor.tsx](../utk_curio/frontend/urban-workflows/src/components/editing/GrammarEditor.tsx) | Same for grammar specs. |
| [components/collab/CollaborationSidePanel.tsx](../utk_curio/frontend/urban-workflows/src/components/collab/CollaborationSidePanel.tsx) | Right-docked Users / Proposals / Activity panel. |
| [components/collab/InviteEditorsDialog.tsx](../utk_curio/frontend/urban-workflows/src/components/collab/InviteEditorsDialog.tsx) | **Share > Invite editors**: the owner's list of editors. |
| [components/menus/top/UpMenu.tsx](../utk_curio/frontend/urban-workflows/src/components/menus/top/UpMenu.tsx) | 👥 **Collaboration** button in the top bar that toggles the side panel; only rendered when `collab.enabled`. |

## Security model

- **Identity** is anchored in `UserSession.token` (the same Bearer token used by REST). The token is sent through Socket.IO's `auth` handshake (`io(url, { auth: { token } })`); the server resolves it in [auth.py](../utk_curio/backend/app/collaboration/auth.py) and stashes the `(user_id, username, name, profile_image)` tuple via `room_state.set_identity(sid, ...)`, with a participant id of the socket's own. **Every subsequent event handler reads from that stashed identity, never from the client-supplied payload.** Spoofing `userId`/`username` fields in an event has no effect.
- **Roles are checked on the server.** A join takes the role the account has on the dataflow: its owner, an editor in its editors list ([access.py](../utk_curio/backend/app/projects/access.py)), or a watcher. A watcher's every change to the room (a node or edge, a lock, a proposal, a vote) is answered `read_only` and reaches nobody. A join to a dataflow that does not exist is refused. Only the owner reads or changes the editors list; anyone else is told the dataflow is not found.
- **Sandbox artifact isolation is preserved.** Outputs flow between collaborators over the socket as `output_produced` payloads, not by one user fetching another user's artifact via `/get`, so the per-session gate on DuckDB artifact reads in [`sandbox/util/parsers.py`](../utk_curio/sandbox/util/parsers.py) still applies. The exception is a project's SAVED outputs: the project's output routes have the sandbox read each one in place, from the file its owner's Data Catalog keeps, so a shared dataflow or dashboard shows its data.
- **Editability of shared dataflows.** Without `--collab`, everyone but the owner who opens a project URL lands in a read-only shared view. With `--collab` on, an editor's canvas is editable and a watcher's stays read-only. Edits flow over the socket to the owner's tab, which saves them. **Only the owner writes to disk**; if the owner's tab is closed, an editor's edits are not kept.
- **Hosted guests.** The server refuses a hosted guest's save with "Guest users cannot save projects", the words the page shows, and refuses its join to a room of a dataflow a guest owns. Without `--deploy` the shared guest is the one local user, which owns and saves its dataflows.
- **No transport encryption out of the box.** Run behind HTTPS for deployments crossing an untrusted network.

## Conflict resolution UX

- **Soft locks** are advisory only. They show "user X is editing" but don't physically block the network. They release when the editor blurs (`onDidBlurEditorText`) or when the user disconnects.
- **Code proposals** require approval from everyone else in the room who edits; a watcher has no vote. The proposer's editor stays as-typed; the others see a banner with Approve / Reject buttons. On unanimous approval the backend emits `code_change_applied`, and every peer's editor updates atomically.
- **Conflicts** between simultaneous edits are surfaced via the side panel's "Activity" stream; resolution is currently a broadcast-only signal (peers update their local view based on the resolver's choice). Richer 3-way merge UX is future work.

## Known limitations

- **In-memory state.** Room presence, locks, proposals, and activity are stored in process memory. A backend restart drops everything.
- **No transport encryption** is enforced by Curio. Run behind HTTPS for any deployment that crosses an untrusted network.
- **Output payload size.** Outputs are relayed as JSON over the socket. Very large outputs (>~256 KB, images, parquet) may render slowly on peers; large-output gating is future work.
- **Lock TTL.** Stale locks are released only on socket disconnect, so a laptop suspended mid-edit holds the lock until the socket times out. A configurable idle-TTL is future work.
- **Persistence of activity log.** The 200-entry activity ring buffer is lost on restart.
- **`async_mode="threading"`.** Fine for dev and small teams. Production with many concurrent rooms should switch to `eventlet` or `gevent`.
