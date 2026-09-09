# Implementation Memo: Dock Refresh on Save + Save-Before-Attach for Node Drops

Date: 2026-07-20 (retroactive record, filed 2026-07-27 — delivered conversationally as a numbered task list (the BL entry still cites tasks "#4"/"#5" from it); the durable evidence until now was build-log entry `BL-P4-20260720-09`)
Status: **implemented** (commits `682cac1` dock refresh, `8dcd661` + `58974e1` save-before-attach)

## 1. Problem Statement

Two seams left by the preserve/prune work and the node-target drop:

- **Stale dock after a save (#5).** The prune step (memo `dev/32`) removes an orphaned attachment server-side, but the dock kept showing its tile until a manual reload — the client had no signal that a save changed the agent sections.
- **Node drops failed on unsaved nodes (#4).** Attach validates the target against the *saved* spec, so dropping an agent onto a freshly-added (not yet saved) node returned the backend's 400 — a save-first caveat users shouldn't have to know.

## 2. Decision

- **#5**: `saveCurrentProject` fires `notifyAgentDockRefresh()` after every successful update save — cheap, and it keeps the dock reconciled with *any* server-side spec change (mirroring the dataset-catalog refresh-on-save pattern), not just prunes.
- **#4**: a node-target drop **persists the graph first**, then attaches — so the freshly-added node is in the spec the backend validates. A never-saved project is auto-created by the same save path, and the attach uses the project id returned by the save. Canvas-target drops skip the pre-save (nothing to validate).

## 3. As-Built Implementation

- `hook/useWorkflowOperations.ts`: dock-refresh event after a successful update save.
- New pure `utils/agentDropAttach.attachAgentOnDrop`: encapsulates the pre-save → attach ordering, the never-saved-project id handling, and the id fallback; throws when no id can be resolved; save failures propagate. Wired into `MainCanvas.handleDrop`, replacing the inline attach and its upfront `projectId` guard.

## 4. Verification

`useWorkflowOperations.installSync.test.ts` (+1: refresh fires on update save); `agentDropAttach.test.ts` (6: node pre-save + ordering, never-saved project id, id fallback, canvas skips the save, no-id throws, save-failure propagates). Hook suite 16 and palette suites 22 passed; `tsc` clean at commit time.

## 5. Traceability

- `BL-P4-20260720-09`; complements `dev/29` (preserve) and `dev/32` (prune); `REQ-ATTACH-003`, `REQ-DOCK`, `RISK-UX-001`.
