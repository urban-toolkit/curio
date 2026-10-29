# Real-Time Collaboration

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

Every tab that opens a saved dataflow (`/dataflow/<UUID>`) while signed in holds one shared copy of it, which the server keeps:

- **Code typed together.** Every keystroke in a node's code or spec shows in every other tab as it is typed, with each person's cursor in their color and their name over it. There is no vote: each change is kept as it is made.
- **Undo is your own.** **Ctrl+Z** (**Cmd+Z** on a Mac) in a node's editor undoes your typing in that node, never someone else's. **Ctrl+Shift+Z** or **Ctrl+Y** redoes it.
- **Everything else, live.** Adding, removing or connecting nodes, a widget's value, a scenario, a node's title, size or settings reach every other tab at once. While someone drags a node, the others see it move; it lands where they drop it.
- **Everyone's cursor on the canvas.** Where each person's pointer is on the canvas shows on everyone else's, in their color with their name, at the same point of the dataflow whatever each of you has panned or zoomed to. A cursor that rests for 5 seconds fades until it moves again, and one that leaves the canvas goes. Your own is not drawn.
- **An agent's drags.** When an agent adds a node, moves one or drops a card onto one, every tab plays its drag, and the change lands as the drop ends. The agent's cursor, in the color of its category with its name, carries a copy of what it drags from where your tab shows it: its card in an open catalog drawer, or its tile or row in the open palette. When that palette is closed, the cursor starts at the edge of the tool rail beside the palette's button and carries the outline of the node. A node it moves goes from its place as its outline. The drop stays at its point of the dataflow as you pan and zoom. With reduced motion, the cursor and what it carries wait where the drop lands. An agent's cursor shows only while it drags.
- **One color per person.** A person's color comes from their account: their cursor has it on the canvas and in the code editors, in each of their tabs, and after a reload.
- **Kept as it is made.** The server keeps each change the moment it arrives and writes the dataflow a second after the last one. A tab that opens the dataflow later finds every change, the last keystroke included.
- **Invited editors edit.** See [Who edits](#who-edits-owner-editors-and-watchers).
- **Who is here.** The dock at the top of the canvas, beside the canvas agents, has a chip for each other person in the dataflow, with their initials in their color. Hover one for their name, their role (owner, editor or watcher) and the node they are editing, and click it to move your view to where they point on the canvas. Your own chip is not in the row. A node someone is in shows their initials in its corner, and their name when you hover them.
- **An agent at work.** A node an agent holds shows the agent's glyph in its corner, in the agent's color; hover it for the agent and who asked it ("Editing: Node Builder (asked by Ana)"). While an agent writes a node, every tab showing it turns it to its code or its spec, or to its **Widgets** tab for a widget's value, and marks the changed lines or widgets for a moment as they land, also when the node stays with whoever asked the agent. A change to a setting turns no tab. When the agent is done, the node goes back to the tab it showed, its **Widgets** tab when it opens on its controls, unless you picked a tab meanwhile. A notebook cell turns the same way.
- **Activity.** The **Activity** button at the end of that row lists who joined, who left and whose role changed, the last 200 of the room's events; see `ACTIVITY_CAP` in [`room_state.py`](../utk_curio/backend/app/collaboration/room_state.py).

A dataflow not saved yet, a hosted guest's canvas of an example, every canvas of a Curio started without `--deploy` or with `--no-project`, and the dashboard page each stay in their own tab.

## Who edits: owner, editors and watchers

Everyone in a dataflow's room has a role, which the server decides when they join and checks on every change:

| Role | Who | What they do |
|------|-----|--------------|
| Owner | The account that owns the dataflow | Edits. Invites and removes editors. Works with the dataflow's agents. |
| Editor | An account the owner invited | Edits: code, nodes, connections, widgets and scenarios, which reach everyone, and works with the dataflow's agents. |
| Watcher | Anyone else signed in who opens the dataflow's link | Watches: every edit, keystroke and cursor shows as it lands, their own cursor shows to the others, and the server keeps nothing their tab changes. |

**Inviting editors.** The owner opens **Share > Invite editors**, types an account's username and presses **Add**. The editors are listed below it, each with a remove button. The editor opens the dataflow's link (**Share > Copy dataflow link**) as anyone does, and edits once the room names them an editor. Adding or removing an editor applies at once, also to someone already in the room. A guest is never an editor, and a guest invites nobody.

**Saving.** Every change is kept by the server as it is made, whoever makes it. **File > Save dataflow** on the owner's tab also saves the outputs the dataflow keeps, and is a version of the dataflow's history. An editor or a watcher saves a copy with **File > Save dataflow**, as on any shared dataflow.

**History.** The server keeps the dataflow's one history, the same in every tab: a version for each node or connection added or removed, each person's typing once they pause or leave the editor ("Ana edited"), an agent's change ("Node Builder, asked by Ana"), each File > Save and each version put back, and each node's runs and edits. The owner and the editors see it in the Provenance drawer, which shows each change as it lands; a watcher and a hosted guest are told it is not theirs to see. Putting a version back changes every tab's canvas. A node's code put back, and a Map Editor node's **Undo** and **Redo**, change the code only if the node still holds what you saw: when someone changed it meanwhile, nothing changes, and Curio says who did ("Ana changed this node after; nothing was undone."). Only the owner can **Clear history before this version**. A copy of the dataflow keeps its history when its owner or an editor makes it.

**Agents.** The owner and the editors work with the dataflow's agents, in chats they share, where a message someone else wrote shows their name above it. An editor's runs answer with the owner's model and key, as the owner's **API Settings** choose them, and use the editor's own saved keys, never the owner's. An agent's change to the dataflow (a node's code or settings, a new node, a plan) reaches every tab as an edit does, and the history names it after the agent and the person who asked, such as *Node Builder, asked by Ana*. Its **Undo**, in the agent's chat, is the own change of whoever clicks it. An install an agent proposes in an editor's chat, such as a package, a dataset or a download from the Discovery Catalog, waits for the owner, who reviews it in the same chat. A watcher sees no agent and no chat, and the server refuses a watcher's every request to the agents. See [Invited editors](AGENT-CATALOG.md#invited-editors).

**Hosted guests.** On a Curio started with `--deploy`, every guest shares one account, which also owns the example dataflows. Such a guest watches other accounts' dataflows. It joins no room of an example, so each guest's canvas of one stays its own, and the server refuses its saves. Its agents work on its own copy of an example: their chats and what they change reach no other guest, and stay until the server restarts.

## When two people change the same thing

| What happens | What you see |
|--------------|--------------|
| You remove a node someone is typing in | Curio asks first: "Ana is editing this node. Remove it anyway?" |
| Someone removes a node while you type in it | "Fabio removed this node while you were editing it." with **Put it back**, which adds it again with your code and the connections whose other end is still there. |
| You connect to a node someone removed at the same moment | The connection is not kept: "Fabio removed that node, so this connection was not kept." |
| Two people set one widget | Every tab shows the same value within a moment, and the node needs a run. |
| An agent's change reaches a node someone is working in | The change waits for them to leave the node. After 30 seconds it gives up, nothing changes, and the agent is told who is in it. |
| You undo an agent's change that someone changed after | Nothing is undone: "Ana changed this node after; nothing was undone." |
| Two people drag one node | It lands where one of them dropped it, the same in every tab. |

## Setup

```bash
# Backend and frontend, with an account for each person:
python curio.py start --deploy

# Only these frontend origins may connect:
python curio.py start --deploy --collab-origins http://192.168.1.5:8080
```

`--deploy` gives each person an account of their own, which the owner invites as an editor by its username. It needs a host that can isolate node execution, such as Curio's Docker image; see [DEPLOYMENT.md](DEPLOYMENT.md).

Open the dataflow's link (`http://<host>:8080/dataflow/<UUID>`) in each collaborator's browser.

| Flag | Variable | Default | Purpose |
|------|----------|---------|---------|
| `--collab-origins ORIGINS` | `COLLAB_CORS_ORIGINS` | `*` | Comma-separated allowed origins for the Socket.IO handshake. Use `*` only on a trusted network. |
| `--collab-namespace NAMESPACE` | `COLLAB_NAMESPACE` | `/collab` | Socket.IO namespace. Change only if you need to coexist with another SocketIO server on the same backend. |

## Architecture

- **Namespace:** `/collab`, or the one `--collab-namespace` sets; the page reads it from `/api/config/public`.
- **Transport:** Socket.IO over WebSocket (with polling fallback).
- **Async mode:** `threading`, which preserves the existing Flask dev-reloader and avoids the eventlet/gevent monkey-patching trap. Each socket's events are handled one at a time, in the order the socket sent them, on the thread that reads it, and none waits for a dataflow's doc: what comes while the doc is busy, as a room typing at once sends it, is answered at once and waits for the doc's own thread. That thread applies what waits in batches, each socket's updates in one go, and each tab gets one message a batch with the others' changes merged, and one with their latest presence.
- **Room key:** `project:<uuid>`. The UUID is the canonical project identifier from the URL (`/dataflow/:id`) and the source of truth in `projectPackagesStore.getCurrentProjectId()`.
- **Room state:** in-memory dicts in [utk_curio/backend/app/collaboration/room_state.py](../utk_curio/backend/app/collaboration/room_state.py), guarded by a single `threading.RLock`: who is in the room, locks and activity. **Not persisted across restarts.**
- **Agents in the room:** an agent at work is in the room too, which the server runs as a peer of the dataflow's doc ([agent_peers.py](../utk_curio/backend/app/collaboration/agent_peers.py)): its presence, which names the node it is writing and what it writes there (`editing`, `writes`) from just before each write to a second after, the locks of the nodes it writes, and its join and leave in Activity; see [ARCHITECTURE.md § Agents in the room](ARCHITECTURE.md#agents-in-the-room).
- **Each open dataflow's doc:** the dataflow itself is a Yjs doc the backend keeps in memory, synced with each tab over the same socket (the `yjs` event) and kept beside the dataflow's spec, so a restart reloads it; see [ARCHITECTURE.md § Each open dataflow's doc](ARCHITECTURE.md#each-open-dataflows-doc) and [§ The canvas bound to its doc](ARCHITECTURE.md#the-canvas-bound-to-its-doc). One backend process serves them all.

### The room's events

What a tab sends on the room's socket, and what the server does with it. The server answers no other event.

| Event | What the server does |
|-------|----------------------|
| `connect` | Checks the Bearer token in the Socket.IO handshake's `auth`, and refuses a socket without a valid one. |
| `join_session` | Puts the tab in the dataflow's room with its account's role, and answers with its participant id and the room's people, locks and activity; the others get `user_joined`. A join to a dataflow that does not exist, or a hosted guest's to an example, is refused. |
| `node_lock` | Locks the node the tab edits, and tells the room (`node_locked`). A watcher's is refused (`read_only`). |
| `node_unlock` | Releases the tab's lock on the node, and tells the room (`node_unlocked`). |
| `yjs` | Syncs the dataflow's doc and everyone's presence in it, and drops a watcher's changes; see [ARCHITECTURE.md § Each open dataflow's doc](ARCHITECTURE.md#each-open-dataflows-doc). |
| `disconnect` | Releases the tab's locks, takes it out of each doc it synced, clears its presence, and tells the room (`user_left`). |

### Backend modules

| File | Role |
|------|------|
| [extensions.py](../utk_curio/backend/extensions.py) | `init_socketio(app)`: the app's SocketIO server. |
| [app/__init__.py](../utk_curio/backend/app/__init__.py) | Mounts the SocketIO server and registers its events, on every backend. |
| [app/collaboration/auth.py](../utk_curio/backend/app/collaboration/auth.py) | Bearer-token handshake; resolves the socket to a real `User` + `UserSession`. |
| [app/collaboration/room_state.py](../utk_curio/backend/app/collaboration/room_state.py) | All in-memory dicts and helpers. Participants are keyed by participant id, one per socket, and a lock names the participant that holds it, a tab or an agent at work, whose lock also names the agent and what it writes. |
| [app/collaboration/events.py](../utk_curio/backend/app/collaboration/events.py) | The room's `@sio.on(...)` handlers: the join and locks. Identity is read from `room_state.get_identity(sid)`, populated in the `connect` handler. A join takes the account's role; every change to the room is refused to a watcher. |
| [app/collaboration/roles.py](../utk_curio/backend/app/collaboration/roles.py) | Tells a room that the owner added or removed an editor (`roles_changed`). |
| [app/collaboration/agent_peers.py](../utk_curio/backend/app/collaboration/agent_peers.py) | An agent at work in the room, run by the server: its presence in the doc's awareness, its locks, its actions one at a time, and its join and leave in Activity (`agent_joined`, `agent_left`). |
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
| [components/editing/useYMonacoBinding.ts](../utk_curio/frontend/urban-workflows/src/components/editing/useYMonacoBinding.ts) | Binds a node's code editor to its code in the doc (y-monaco), with each person's cursor and the per-node Ctrl+Z, and marks the lines of an agent's change as it lands (`agentChangeMarks.ts`). |
| [providers/collab/presence.ts](../utk_curio/frontend/urban-workflows/src/providers/collab/presence.ts) | What each tab tells the others through awareness: the node it edits, its drags, the nodes it removes, where its pointer is on the canvas; and each person's color, from their account (`personColor`). |
| [providers/collab/cursors.ts](../utk_curio/frontend/urban-workflows/src/providers/collab/cursors.ts) | A pointer on the canvas as awareness carries it, `pointer: {x, y, t}` in flow coordinates: sent about 20 times a second at most, and faded once it rests. A state that carries a drag draws no pointer of its own. |
| [components/collab/CanvasCursors.tsx](../utk_curio/frontend/urban-workflows/src/components/collab/CanvasCursors.tsx) | Sends this tab's pointer while it is on the canvas, and draws everyone else's on the scenario layers' pan-and-zoom plane (`ParticipantCursors` in `components/scenarios/ScenarioLayers.tsx`), and their drags (`AgentDrags`). |
| [providers/collab/agentDrags.ts](../utk_curio/frontend/urban-workflows/src/providers/collab/agentDrags.ts) | An agent's drag as awareness carries it, `carrying: {id, kind, from, onto, node: {type, label}, ms}` with `pointer` at its drop point, and where it starts in this tab: the element whose `data-palette` and `data-palette-item` name its item (a card in an open drawer, then a tile or row in the open palette), the rail's edge beside a closed palette's button, or a node's place. |
| [components/collab/AgentDrags.tsx](../utk_curio/frontend/urban-workflows/src/components/collab/AgentDrags.tsx) | Plays each drag on the same plane, in a layer over the tool rail and the catalog drawers: the agent's cursor and a ghost of what it drags, from its start to its drop point in `ms`, or at the drop point under reduced motion. |
| [providers/flow/useRemovalAsk.tsx](../utk_curio/frontend/urban-workflows/src/providers/flow/useRemovalAsk.tsx) | Asks before removing a node someone else is editing. |
| [providers/history/serverHistory.ts](../utk_curio/frontend/urban-workflows/src/providers/history/serverHistory.ts) | Whether the canvas's history is the server's (bound to the doc) or the browser's; the Provenance drawers read the server's through `useHistoryReads.ts`. |
| [providers/collab/participants.ts](../utk_curio/frontend/urban-workflows/src/providers/collab/participants.ts) | Tells participants apart by participant id: whether a lock is this tab's, a tab's role, and an agent's lock from a person's (`agentHolding`). |
| [providers/collab/agentHolds.ts](../utk_curio/frontend/urban-workflows/src/providers/collab/agentHolds.ts) | The nodes agents are writing, from their states in the doc's awareness (`editing`, `writes`): a node's editor shows what the agent writes while it writes the node (`NodeEditor.tsx`). |
| [hook/useSharedView.ts](../utk_curio/frontend/urban-workflows/src/hook/useSharedView.ts) | Whether the canvas is read-only: a watcher's. Every gate on editing reads it. |
| [components/UniversalNode.tsx](../utk_curio/frontend/urban-workflows/src/components/UniversalNode.tsx) | Lock-on-focus / unlock-on-blur, peer-lock chip: a person's initials, or an agent's glyph in its tint. |
| [providers/collab/people.ts](../utk_curio/frontend/urban-workflows/src/providers/collab/people.ts) | Who else is in the room, from awareness: one entry per participant, none of yours, each with their role, the node they edit and where they point. |
| [components/agents/attach/PeopleHere.tsx](../utk_curio/frontend/urban-workflows/src/components/agents/attach/PeopleHere.tsx) | The people in the canvas's dock (`AgentDock.tsx`, beside the canvas agents): a chip each, which moves the view to where they point, and the **Activity** list. |
| [components/collab/InviteEditorsDialog.tsx](../utk_curio/frontend/urban-workflows/src/components/collab/InviteEditorsDialog.tsx) | **Share > Invite editors**: the owner's list of editors. |

## Security model

- **Identity** is anchored in `UserSession.token` (the same Bearer token used by REST). The token is sent through Socket.IO's `auth` handshake (`io(url, { auth: { token } })`); the server resolves it in [auth.py](../utk_curio/backend/app/collaboration/auth.py) and stashes the `(user_id, username, name, profile_image)` tuple via `room_state.set_identity(sid, ...)`, with a participant id of the socket's own. **Every subsequent event handler reads from that stashed identity, never from the client-supplied payload.** Spoofing `userId`/`username` fields in an event has no effect.
- **Presence is the server's to name.** Each presence state carries who the server knows its tab to be, and a tab sets only its own person's presence: never another account's, never another guest's (every guest signs in to the one guest account, and each sign-in is its own), and never an agent's.
- **Roles are checked on the server.** A join takes the role the account has on the dataflow: its owner, an editor in its editors list ([access.py](../utk_curio/backend/app/projects/access.py)), or a watcher. A watcher's changes to the dataflow's doc are dropped, and a lock it asks for is answered `read_only` and reaches nobody. A join to a dataflow that does not exist is refused. Only the owner reads or changes the editors list; anyone else is told the dataflow is not found. The agents' routes take the same roles: the owner and the editors drive the dataflow's agents, and anyone else, a hosted guest on another account's dataflow included, is refused with a 403.
- **Sandbox artifact isolation is preserved.** Each person's runs are their own, and no one reads another user's artifact via `/get`, so the per-session gate on DuckDB artifact reads in [`sandbox/util/parsers.py`](../utk_curio/sandbox/util/parsers.py) applies to collaborators too. The exception is a project's SAVED outputs: the project's output routes have the sandbox read each one in place, from the file its owner's Data Catalog keeps, so a shared dataflow or dashboard shows its data.
- **Editability of shared dataflows.** An editor's canvas is editable, and anyone else who opens a dataflow's link gets a watcher's, which stays read-only. The server keeps an editor's change as it arrives, whoever else has the dataflow open.
- **Hosted guests.** The server refuses a hosted guest's save with "Guest users cannot save projects", the words the page shows, and refuses its join to a room of a dataflow a guest owns. Without `--deploy` the shared guest is the one local user, which owns and saves its dataflows.
- **No transport encryption out of the box.** Run behind HTTPS for deployments crossing an untrusted network.

## Known limitations

- **In-memory room state.** Room presence, locks and activity are stored in process memory, and a backend restart drops them. The dataflow's doc is kept on disk.
- **No transport encryption** is enforced by Curio. Run behind HTTPS for any deployment that crosses an untrusted network.
- **Lock TTL.** Stale locks are released only on socket disconnect, so a laptop suspended mid-edit holds the lock until the socket times out.
- **Persistence of activity log.** The 200-entry activity ring buffer is lost on restart.
- **`async_mode="threading"`.** 100 people typing at once in their rooms see each other's changes within about a second. A backend busier than that delays the changes rather than dropping the sockets. Production with many concurrent rooms should switch to `eventlet` or `gevent`.
