# Real-Time Collaboration

> [!IMPORTANT]
> **Invited editors and the people panel are off by default**. Turn them on with `--collab`.

This feature is based on the design proposed by [@kirtanpatel2003](https://github.com/kirtanpatel2003) in [#112](https://github.com/urban-toolkit/curio/pull/112).

## Contents

- [What it does](#what-it-does)
- [Who edits: owner, editors and watchers](#who-edits-owner-editors-and-watchers)
- [When two people change the same thing](#when-two-people-change-the-same-thing)
- [Setup](#setup)
- [Architecture](#architecture)
- [Security model](#security-model)
- [Known limitations](#known-limitations)

## What it does

Every tab that opens a saved dataflow (`/dataflow/<UUID>`) while signed in holds one shared copy of it, which the server keeps, with or without `--collab`:

- **Code typed together.** Every keystroke in a node's code or spec shows in every other tab as it is typed, with each person's cursor in their color and their name over it. There is no vote: each change is kept as it is made.
- **Undo is your own.** **Ctrl+Z** (**Cmd+Z** on a Mac) in a node's editor undoes your typing in that node, never someone else's. **Ctrl+Shift+Z** or **Ctrl+Y** redoes it.
- **Everything else, live.** Adding, removing or connecting nodes, a widget's value, a scenario, a node's title, size or settings reach every other tab at once. While someone drags a node, the others see it move; it lands where they drop it.
- **Kept as it is made.** The server keeps each change the moment it arrives and writes the dataflow a second after the last one. A tab that opens the dataflow later finds every change, the last keystroke included.

A dataflow not saved yet, a hosted guest's canvas of an example, every canvas of a Curio started with `--no-project`, and the dashboard page each stay in their own tab.

Without `--collab`, only the owner's tabs edit, and everyone else's follow the dataflow as it changes. With `--collab`:

- **Invited editors edit.** See [Who edits](#who-edits-owner-editors-and-watchers).
- **Presence.** The side panel, opened from the 👥 button in the top bar, lists everyone in the dataflow with their role (owner, editor or watcher), and a node someone is in shows their initials in its corner.
- **Shared execution output.** When a node finishes running on one person's machine, the rendered output is sent to the others, so they see the same result without running it again and **without crossing the sandbox's session isolation**.
- **Activity log.** The side panel keeps the last 200 room events (joins, locks, conflict resolutions); see `ACTIVITY_CAP` in [`room_state.py`](../utk_curio/backend/app/collaboration/room_state.py).

## Who edits: owner, editors and watchers

Everyone in a dataflow's room has a role, which the server decides when they join and checks on every change:

| Role | Who | What they do |
|------|-----|--------------|
| Owner | The account that owns the dataflow | Edits. Invites and removes editors. |
| Editor | An account the owner invited | With `--collab`, edits: code, nodes, connections, widgets and scenarios, which reach everyone. Without it, watches. |
| Watcher | Anyone else signed in who opens the dataflow's link | Watches: every edit, keystroke and cursor shows as it lands, and the server keeps nothing their tab changes. |

**Inviting editors.** The owner opens **Share > Invite editors**, types an account's username and presses **Add**. The editors are listed below it, each with a remove button. The editor opens the dataflow's link (**Share > Copy dataflow link**) as anyone does, and edits once the room names them an editor. Adding or removing an editor applies at once, also to someone already in the room. A guest is never an editor, and a guest invites nobody.

**Saving.** Every change is kept by the server as it is made, whoever makes it. **File > Save dataflow** on the owner's tab also saves the outputs the dataflow keeps, and is a version of the dataflow's history. An editor or a watcher saves a copy with **File > Save dataflow**, as on any shared dataflow.

**History.** The server keeps the dataflow's one history, the same in every tab: a version for each node or connection added or removed, each person's typing once they pause or leave the editor ("Ana edited"), an agent's change ("Node Builder, asked by Ana"), each File > Save and each version put back, and each node's runs and edits. The owner and the editors see it in the Provenance drawer, which shows each change as it lands; a watcher and a hosted guest are told it is not theirs to see. Putting a version back changes every tab's canvas. A node's code put back, and a Map Editor node's **Undo** and **Redo**, change the code only if the node still holds what you saw: when someone changed it meanwhile, nothing changes, and Curio says who did ("Ana changed this node after; nothing was undone."). Only the owner can **Clear history before this version**. A copy of the dataflow keeps its history when its owner or an editor makes it.

**Hosted guests.** On a Curio started with `--deploy`, every guest shares one account, which also owns the example dataflows. Such a guest watches other accounts' dataflows. It joins no room of an example, so each guest's canvas of one stays its own, and the server refuses its saves.

## When two people change the same thing

| What happens | What you see |
|--------------|--------------|
| You remove a node someone is typing in | Curio asks first: "Ana is editing this node. Remove it anyway?" |
| Someone removes a node while you type in it | "Fabio removed this node while you were editing it." with **Put it back**, which adds it again with your code and the connections whose other end is still there. |
| You connect to a node someone removed at the same moment | The connection is not kept: "Fabio removed that node, so this connection was not kept." |
| Two people set one widget | Every tab shows the same value within a moment, and the node needs a run. |
| Two people drag one node | It lands where one of them dropped it, the same in every tab. |

## Setup

```bash
# Backend + frontend, with the people panel:
python curio.py start --deploy --collab

# Only these frontend origins may connect:
python curio.py start --deploy --collab --collab-origins http://192.168.1.5:8080
```

`--deploy` gives each person an account of their own, which the owner invites as an editor by its username. It needs a host that can isolate node execution, such as Curio's Docker image; see [DEPLOYMENT.md](DEPLOYMENT.md).

Open the project URL (`http://<host>:8080/dataflow/<UUID>`) on each collaborator's browser. The `--collab` flag is read at runtime by the frontend via `/api/config/public`, so **no frontend rebuild is required** to flip the flag.

| Flag | Variable | Default | Purpose |
|------|----------|---------|---------|
| `--collab` | `ENABLE_COLLAB` | off | Lets the editors the owner invited edit, and shows the people panel, its button, the lock chips and the outputs others run. Without it, the owner's tabs still edit the server's copy and every other signed-in tab follows it. |
| `--collab-origins ORIGINS` | `COLLAB_CORS_ORIGINS` | `*` | Comma-separated allowed origins for the Socket.IO handshake. Use `*` only on a trusted network. |
| `--collab-namespace NAMESPACE` | `COLLAB_NAMESPACE` | `/collab` | Socket.IO namespace. Change only if you need to coexist with another SocketIO server on the same backend. |

## Architecture

- **Namespace:** `/collab`, or the one `--collab-namespace` sets; the page reads it from `/api/config/public`.
- **Transport:** Socket.IO over WebSocket (with polling fallback).
- **Async mode:** `threading`, which preserves the existing Flask dev-reloader and avoids the eventlet/gevent monkey-patching trap. Each socket's events are handled one at a time, in the order the socket sent them, on the thread that reads it. Updates that wait for a dataflow's doc together, as a room typing at once sends them, are applied as one batch, and each tab gets one message with the others' changes merged.
- **Room key:** `project:<uuid>`. The UUID is the canonical project identifier from the URL (`/dataflow/:id`) and the source of truth in `projectPackagesStore.getCurrentProjectId()`.
- **Room state:** in-memory dicts in [utk_curio/backend/app/collaboration/room_state.py](../utk_curio/backend/app/collaboration/room_state.py), guarded by a single `threading.RLock`: who is in the room, locks and activity. **Not persisted across restarts.**
- **Each open dataflow's doc:** the dataflow itself is a Yjs doc the backend keeps in memory, synced with each tab over the same socket (the `yjs` event) and kept beside the dataflow's spec, so a restart reloads it; see [ARCHITECTURE.md § Each open dataflow's doc](ARCHITECTURE.md#each-open-dataflows-doc) and [§ The canvas bound to its doc](ARCHITECTURE.md#the-canvas-bound-to-its-doc). One backend process serves them all.

### Backend modules

| File | Role |
|------|------|
| [extensions.py](../utk_curio/backend/extensions.py) | `init_socketio(app)`: the app's SocketIO server. |
| [app/__init__.py](../utk_curio/backend/app/__init__.py) | Mounts the SocketIO server and registers its events, on every backend. |
| [app/collaboration/auth.py](../utk_curio/backend/app/collaboration/auth.py) | Bearer-token handshake; resolves the socket to a real `User` + `UserSession`. |
| [app/collaboration/room_state.py](../utk_curio/backend/app/collaboration/room_state.py) | All in-memory dicts and helpers. Participants and locks are keyed by participant id, one per socket. |
| [app/collaboration/events.py](../utk_curio/backend/app/collaboration/events.py) | The room's `@sio.on(...)` handlers: the join, locks, outputs. Identity is read from `room_state.get_identity(sid)`, populated in the `connect` handler. A join takes the account's role; every change to the room is refused to a watcher. |
| [app/collaboration/roles.py](../utk_curio/backend/app/collaboration/roles.py) | Tells a room that the owner added or removed an editor (`roles_changed`). |
| [app/collaboration/dataflow_docs.py](../utk_curio/backend/app/collaboration/dataflow_docs.py) | Each open dataflow's Yjs doc: its sync and awareness (`yjs`), a watcher's changes dropped, a connection to a removed node dropped (`connection_dropped`), its files beside the spec. Every backend writer of a dataflow (agents, Solve, installs, the PUT) writes through it, so each change reaches the room as it lands. |
| [app/collaboration/doc_mapping.py](../utk_curio/backend/app/collaboration/doc_mapping.py) | A dataflow's Trill to its doc and back, on the layout in `src/contracts/dataflowDoc.json`. |
| [app/collaboration/history.py](../utk_curio/backend/app/collaboration/history.py) | The dataflow's history as points in its doc's log: the versions, the nodes' entries, putting back, the checked code write and clearing (`history_changed` tells the owner's and editors' tabs). |
| [app/projects/access.py](../utk_curio/backend/app/projects/access.py) | The roles, and the editors list behind **Invite editors** (`/api/projects/<id>/editors`). |

### Frontend modules

| File | Role |
|------|------|
| [providers/CollaborationProvider.tsx](../utk_curio/frontend/urban-workflows/src/providers/CollaborationProvider.tsx) | Fetches `/api/config/public`, opens one socket per project, exposes the `useCollab()` API (the tab's participant id and role among them), and starts the dataflow's doc once the room joins the tab. |
| [providers/collab/docProvider.ts](../utk_curio/frontend/urban-workflows/src/providers/collab/docProvider.ts) | Curio's Yjs provider: the doc's sync and awareness on the room's socket. |
| [providers/collab/docMapping.ts](../utk_curio/frontend/urban-workflows/src/providers/collab/docMapping.ts) | A dataflow's Trill to its doc and back, on the server's layout. |
| [providers/flow/useDataflowDoc.ts](../utk_curio/frontend/urban-workflows/src/providers/flow/useDataflowDoc.ts) | Keeps the canvas and the doc in step both ways; live drags; a node removed while you edit it. |
| [components/editing/useYMonacoBinding.ts](../utk_curio/frontend/urban-workflows/src/components/editing/useYMonacoBinding.ts) | Binds a node's code editor to its code in the doc (y-monaco), with each person's cursor and the per-node Ctrl+Z. |
| [providers/collab/presence.ts](../utk_curio/frontend/urban-workflows/src/providers/collab/presence.ts) | What each tab tells the others through awareness: the node it edits, its drags, the nodes it removes, and each person's cursor color. |
| [providers/flow/useRemovalAsk.tsx](../utk_curio/frontend/urban-workflows/src/providers/flow/useRemovalAsk.tsx) | Asks before removing a node someone else is editing. |
| [providers/history/serverHistory.ts](../utk_curio/frontend/urban-workflows/src/providers/history/serverHistory.ts) | Whether the canvas's history is the server's (bound to the doc) or the browser's; the Provenance drawers read the server's through `useHistoryReads.ts`. |
| [providers/collab/participants.ts](../utk_curio/frontend/urban-workflows/src/providers/collab/participants.ts) | Tells participants apart by participant id: whether a lock is this tab's, a tab's role. |
| [hook/useSharedView.ts](../utk_curio/frontend/urban-workflows/src/hook/useSharedView.ts) | Whether the canvas is read-only: a watcher's. Every gate on editing reads it. |
| [components/UniversalNode.tsx](../utk_curio/frontend/urban-workflows/src/components/UniversalNode.tsx) | Lock-on-focus / unlock-on-blur, peer-lock chip, output broadcast on exec completion. |
| [components/collab/CollaborationSidePanel.tsx](../utk_curio/frontend/urban-workflows/src/components/collab/CollaborationSidePanel.tsx) | Right-docked Users / Activity panel. |
| [components/collab/InviteEditorsDialog.tsx](../utk_curio/frontend/urban-workflows/src/components/collab/InviteEditorsDialog.tsx) | **Share > Invite editors**: the owner's list of editors. |
| [components/menus/top/UpMenu.tsx](../utk_curio/frontend/urban-workflows/src/components/menus/top/UpMenu.tsx) | 👥 **Collaboration** button in the top bar that toggles the side panel; only rendered when `collab.enabled`. |

## Security model

- **Identity** is anchored in `UserSession.token` (the same Bearer token used by REST). The token is sent through Socket.IO's `auth` handshake (`io(url, { auth: { token } })`); the server resolves it in [auth.py](../utk_curio/backend/app/collaboration/auth.py) and stashes the `(user_id, username, name, profile_image)` tuple via `room_state.set_identity(sid, ...)`, with a participant id of the socket's own. **Every subsequent event handler reads from that stashed identity, never from the client-supplied payload.** Spoofing `userId`/`username` fields in an event has no effect.
- **Roles are checked on the server.** A join takes the role the account has on the dataflow: its owner, an editor in its editors list ([access.py](../utk_curio/backend/app/projects/access.py)), or a watcher. A watcher's changes to the dataflow's doc are dropped, and its every other change to the room (a lock, an output) is answered `read_only` and reaches nobody. A join to a dataflow that does not exist is refused. Only the owner reads or changes the editors list; anyone else is told the dataflow is not found.
- **Sandbox artifact isolation is preserved.** Outputs flow between collaborators over the socket as `output_produced` payloads, not by one user fetching another user's artifact via `/get`, so the per-session gate on DuckDB artifact reads in [`sandbox/util/parsers.py`](../utk_curio/sandbox/util/parsers.py) still applies. The exception is a project's SAVED outputs: the project's output routes have the sandbox read each one in place, from the file its owner's Data Catalog keeps, so a shared dataflow or dashboard shows its data.
- **Editability of shared dataflows.** Without `--collab`, everyone but the owner who opens a project URL lands in a read-only shared view. With `--collab` on, an editor's canvas is editable and a watcher's stays read-only. The server keeps an editor's change as it arrives, whoever else has the dataflow open.
- **Hosted guests.** The server refuses a hosted guest's save with "Guest users cannot save projects", the words the page shows, and refuses its join to a room of a dataflow a guest owns. Without `--deploy` the shared guest is the one local user, which owns and saves its dataflows.
- **No transport encryption out of the box.** Run behind HTTPS for deployments crossing an untrusted network.

## Known limitations

- **In-memory room state.** Room presence, locks and activity are stored in process memory, and a backend restart drops them. The dataflow's doc is kept on disk.
- **No transport encryption** is enforced by Curio. Run behind HTTPS for any deployment that crosses an untrusted network.
- **Output payload size.** Outputs are relayed as JSON over the socket. Very large outputs (>~256 KB, images, parquet) may render slowly on peers.
- **Lock TTL.** Stale locks are released only on socket disconnect, so a laptop suspended mid-edit holds the lock until the socket times out.
- **Persistence of activity log.** The 200-entry activity ring buffer is lost on restart.
- **`async_mode="threading"`.** 50 people typing at once in their rooms see each other's changes in under a second. At 100 the one backend process falls behind, and their sockets drop at Engine.IO's ping timeout. Production with many concurrent rooms should switch to `eventlet` or `gevent`.
