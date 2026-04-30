# Collaboration

How to run Curio so multiple people on the same LAN can edit a workflow at the same time. For solo local dev see [USAGE.md](USAGE.md). For hosted, public, HTTPS-fronted deployment see [DEPLOYMENT.md](DEPLOYMENT.md) — collaboration is a different shape and uses a different setup.

This guide assumes one person hosts (their laptop runs Docker), the others join from their browsers via the host's LAN IP. No reverse proxy, no certs, no path prefix — just `http://<host-LAN-IP>:8080`.

> [!IMPORTANT]
> Collaboration exposes Curio on every interface of the host machine. Anyone reachable on the same network (office LAN, conference Wi-Fi, hotel Wi-Fi) can open the URL. Use this on a network you trust, or behind a VPN like Tailscale. There is no per-user auth between collaborators inside a session.

## Contents

- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [1. Enable the flag](#1-enable-the-flag)
- [2. Build and run](#2-build-and-run)
- [3. Share the URL](#3-share-the-url)
- [Conflict model](#conflict-model)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Differences from production deployment](#differences-from-production-deployment)

## What you get

Real-time multi-user editing of a single workflow:

- **Live cursor of presence** — the right sidebar shows who's connected, each with their own color.
- **Per-node locking** — when you focus a node's editor, a colored border + "Editing: Name" badge appears for everyone else; they can't edit until you blur.
- **Code change proposals** — when you finish editing a node's code (Monaco blur), the change goes into a proposal queue visible to all collaborators. Anyone can **Accept** or **Decline**. First Accept wins; competing proposals on the same node are auto-cancelled.
- **Live execution output sync** — when one collaborator runs a node, the result (stdout, file path) propagates so others' Data Pool / visualization nodes show the same data without re-running.
- **Edge / node conflict resolution** — when one user deletes an edge or node and another user's lock or downstream dependency blocks it, both see a conflict card with **Accept** (let the deletion through) and **Decline** (keep the current state).
- **Local-only position** — moving a node on your canvas does not move it on theirs. Positions are intentionally not synced.

## How it works

Architecture:

- **Backend**: Flask + Flask-SocketIO mounted on port `5002`. Socket events live in [`utk_curio/backend/app/collaboration/events.py`](../utk_curio/backend/app/collaboration/events.py). Per-room state (connected users, locked nodes, pending proposals, output snapshots, graph) is held in-memory dicts keyed by session id.
- **Session id**: derived client-side from `workflowNameRef.current` in `FlowProvider`. Two browsers with the same workflow open share a room; opening different workflows isolates them.
- **Frontend transport**: socket.io-client connects to `http://<page-host>:5002`, falling back from polling to websocket.
- **Backend URL resolution**: the bundle resolves `BACKEND_URL` at runtime from `window.location` (see [`src/utils/backendUrl.ts`](../utk_curio/frontend/urban-workflows/src/utils/backendUrl.ts)). REST + socket both follow whichever host served the page, so a single bundle works for `localhost`, Docker, and LAN with no rebuild.
- **Artifact reads are not session-isolated**: collaborators share the same backend, so the sandbox's `/get` endpoint serves any artifact in the room regardless of which user's auth session created it. Writes still tag artifacts with the originating session for provenance.

Notable invariants in [`src/providers/CollaborationProvider.tsx`](../utk_curio/frontend/urban-workflows/src/providers/CollaborationProvider.tsx):

- `nodeFingerprintPayload` excludes `position`, so dragging never emits `node_updated`.
- `hydrateNodeForRuntime` preserves the local position when applying a remote update — initial position comes from `node_added`, every update after is local-only.
- Runtime fields (`pythonInterpreter`, `outputCallback`, `interactionsCallback`, `propagationCallback`) are stripped before broadcast and re-attached on receive.
- A small allowlist (`LOCAL_ONLY_DATA_FIELDS = ['_approvedCodeStamp']`) marks fields that are local-only stamps and never sync.

## 1. Enable the flag

Edit `utk_curio/frontend/urban-workflows/.env`:

```bash
ENABLE_COLLAB=true
```

That's the entire toggle. With this on:

- The Python launcher binds `--backend-host`, `--sandbox-host`, `--frontend-host` to `0.0.0.0`.
- The webpack dev server (when used) binds to `0.0.0.0` with `allowedHosts: "all"`.
- The startup log prints `Share this URL with collaborators: http://<lan-ip>:8080`.

Leave it `false` for solo loopback-only dev.

## 2. Build and run

The frontend bundle is built **inside the Docker image**. After flipping the flag (or pulling new code), rebuild so the change actually lands in the running container:

```bash
docker compose down
docker compose build --no-cache curio
docker compose up
```

`--no-cache` matters for the same reason as in DEPLOYMENT.md — Docker's layer cache occasionally keeps an old `npm run build` artifact even when `.env` changed.

Verify from the host:

```bash
curl http://localhost:5002/health   # → OK
curl http://localhost:8080          # → frontend HTML
```

And from a peer device on the same network:

```bash
curl http://<host-LAN-IP>:5002/health
```

If the peer gets `OK`, you're done. If not, see [Troubleshooting](#troubleshooting).

## 3. Share the URL

Collaborators open `http://<host-LAN-IP>:8080/` in any browser. They join automatically — there's no invite link or room code. Two browsers that load the same workflow name end up in the same socket room.

Each collaborator's display name and color is in the right-side panel. Click the name to rename yourself; the change is broadcast.

## Conflict model

The default behavior is "first action wins." Conflicts only surface when the system can't apply an action without input:

| Situation | What happens |
|---|---|
| You edit code; nobody else is editing | Your change becomes a **proposal** that others can Accept/Decline. |
| Two users edit the same node simultaneously | Both proposals queue. First Accept wins; the loser's proposal is auto-cancelled (`code_change_superseded`). |
| You delete an edge/node, but a dependency or another user's lock blocks it | Both you and the affected user see a conflict card with **Accept** / **Decline**. |
| You drag a node to a new position | Local only. Nothing is broadcast or conflicted. |
| You run a Python node | The execution output (stdout + file path) propagates so others' downstream Data Pool / visualization nodes see the same artifact. |

The buttons have role-aware semantics — clicking **Accept** as the actor forces your action through; clicking **Accept** as a bystander agrees to the actor's action. **Decline** is the inverse. The UI hides this asymmetry; you only see "Accept" / "Decline."

## Limitations

These are real and worth knowing before you depend on it:

- **Room state is in-memory.** `_room_users`, `_room_outputs`, `_pending_code_proposals`, `_room_graph` in `events.py` are plain dicts. Restarting the container wipes every active session. For a more durable setup, migrate to a Flask-SocketIO message queue backend (Redis) or persist room state to the existing `./instance` SQLite file.
- **Single host.** All collaborators talk to one Flask process. If that machine sleeps or its IP changes, the session ends. There's no clustering.
- **No transport encryption.** This is plain HTTP on the LAN. Don't use it on networks you don't trust without wrapping it in Tailscale, WireGuard, or a reverse proxy doing TLS.
- **No per-collaborator auth.** Anyone who reaches the URL is in. Lock scopes are trust-based, not enforced.
- **Position is intentionally local.** Late joiners see whichever position was last `node_added`'d, not the current placement on any participant's canvas. This is a deliberate choice (dragging shouldn't fight other users), not a bug.
- **Artifact reads bypass session isolation.** The sandbox's per-user session check is dropped on `/get` and `/get-preview` so collaborators can see each other's outputs. If you re-introduce per-user isolation, collab data sharing breaks again.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Banner: *Backend server is not reachable* on peer device | Bundle was built before runtime URL resolution landed. Rebuild with `--no-cache`. After that the banner shows `Configured URL: http://<host-LAN-IP>:5002`. |
| Peer browser loads the page but socket never connects | Host-side firewall is blocking 5002. macOS: turn off the firewall or allow `python` and Docker. Verify with `lsof -iTCP:5002 -sTCP:LISTEN` — should show `*:5002`, not `127.0.0.1:5002`. |
| `lsof` returns nothing | Curio isn't running. Check `docker compose ps`. |
| Banner shows `localhost:5002` after rebuild | Docker layer cache reused the old bundle. `docker compose build --no-cache curio`. |
| `Auto-merge failed` for `docker-compose.yml` after `git merge upstream/main` | Volumes section conflict (your local mounts vs. upstream's `.curio` / `instance`). Keep both. |
| Data Pool shows data on one user, *no data available* on another | Only happens with the old per-user artifact isolation. Confirm `/get` no longer forwards `sessionId`. |
| Collaborators see different node positions | Working as designed — positions are local. |
| Two users approved different proposals on the same node | First-accept-wins. The later one is silently dropped (status `superseded`). Check the activity log to see which won. |

## Differences from production deployment

DEPLOYMENT.md describes a hosted, multi-tenant, HTTPS deployment behind Caddy. Collaboration is a different shape:

| | Deployment ([DEPLOYMENT.md](DEPLOYMENT.md)) | Collaboration |
|---|---|---|
| Audience | Public users on the internet | Peers on the same LAN |
| Transport | HTTPS via Caddy reverse proxy | Plain HTTP, direct to Docker |
| Hostname | `lab-name.your-uni.edu` | `<host-LAN-IP>` |
| URL prefix | `/curio/` | none |
| `BACKEND_URL` | runtime-resolved from `window.location` (was previously baked at image build, see note below) | runtime-resolved from `window.location` |
| Feature flag | n/a | `ENABLE_COLLAB=true` |
| Persistence | `instance/` (SQLite users + projects), `data/` (artifacts) | `instance/` is still mounted, but room state is in-memory and resets on restart |
| Auth | Google OAuth, per-user sessions | None between collaborators |
| Concurrency model | Stateless requests, isolated per user session | Stateful socket rooms, shared graph |

> **Note on DEPLOYMENT.md**: that doc currently states `BACKEND_URL` is baked into the image and changing it requires a rebuild. After the runtime-URL refactor, that's no longer strictly true — the bundle resolves the backend from `window.location` at load time. The build arg still gates which `.env` ships in the image, but the running app no longer reads it. DEPLOYMENT.md should be updated to match.

## Future work

If/when collab moves beyond "demo on a LAN":

1. **Redis-backed Flask-SocketIO** so room state survives restarts and you can horizontally scale beyond one process.
2. **Room persistence in `instance/`** for code change proposals and output snapshots, so a late joiner can replay history.
3. **Per-collaborator auth** — issue a short-lived token at the host's prompt, require it to join. Currently anyone who reaches the URL is in.
4. **TLS for cross-LAN collab** — wrap with Caddy + Let's Encrypt (mirroring DEPLOYMENT.md), or run over Tailscale.
5. **Bridge to the deployment story** — a hosted Curio that supports collab sessions out of the box, instead of toggling between two modes.
