# Implementation Memo: Node Builder — Post-Creation Canvas Synchronization (dev/48 bridge fixes)

Date: 2026-08-04
Status: implemented 2026-08-04 — COMMIT-e48603dc. Verification: frontend `npx jest` → 635 passed
(58 suites), including the new real-provider integration regression
(`agentCanvasBridge.integration.test.tsx`) that reproduced defect 2 before the fix.

## 1. Problem Statement (root causes, reproduced)

Node Builder creates nodes correctly (the apply succeeds, the saved spec gains the node, the chat
transcript's result card is right — all unchanged by this memo), but the new node does not appear
on the canvas until a manual page refresh. Three defects in the dev/48 bridge, found by a NEW
integration test that drives the REAL `FlowProvider` + REAL `reactflow` + REAL `useCode`
(the dev/48 unit suite mocked exactly the seams where these live):

1. **Off-viewport placement with no post-insert viewport move — the reported symptom.** The
   backend places a created node right of the ENTIRE saved-graph extent (`max_x + 420`). The
   bridge inserts it there but never moves the viewport, so on any realistically-sized canvas the
   node lands off-screen and reads as "not created". A refresh "fixes" it because project load
   runs the fit-view-on-load pass (`useWorkflowOperations:186` → `fitViewWithMenuOffset`), which
   frames every node — exactly matching the report.
2. **React Flow store writes are dropped in controlled mode (reproduced).** The bridge's
   follow-up `useReactFlow().setNodes(...)` writes (setting `data.code` after insert; the whole
   `node-content-applied` branch) mutate the RF internal store, which the controlled
   `<ReactFlow nodes={FlowProvider state}>` re-sync clobbers. The integration test shows the
   inserted node's `data.code` is `undefined` — so the next canvas save would post the node
   without its content (the very clobber dev/48 §3.3 set out to close), and applied
   `node.content.write` content never reaches the live editor at all.
3. **Double-event guard race.** The idempotence check reads `useReactFlow().getNodes()`, which
   lags FlowProvider state by a render; two quick events could double-insert before the store
   syncs.

Expected behavior (unchanged from dev/48 §3.3, now actually delivered): the created node appears
immediately — in view — after apply; the live node carries the applied content so a later save
round-trips it; insertion is once-only; `node.content.write` applies reach the live editor; the
chat feedback and all creation behavior stay byte-identical.

## 2. Scope

- `hook/useCode.ts` — `generateCodeNode` also seeds `data.code` when the `code` option is given
  (serialization source of truth; `undefined` when absent — palette drops byte-identical).
- `providers/FlowProvider.tsx` — one new context helper `applyNodeContent(nodeId, content)`
  setting `data.defaultCode` (the editor's value) **and** `data.code` (the serializer's value)
  through the provider's own `setNodes` — the sanctioned programmatic-update path
  (`updateDefaultCode`'s documented purpose), left untouched itself to preserve its consumers.
- `components/agents/attach/useAgentCanvasMutations.ts` — drop every RF-store write; route
  content through `applyNodeContent`; center the viewport on the inserted node
  (`setCenter`, current zoom, gentle duration); add a processed-ids ref beside the store check.
- Tests: the new REAL-provider integration suite (kept as the regression net) + updated unit
  expectations.
- **Untouched**: backend (placement stays spec-side and correct), proposal/apply flow, chat
  transcript feedback, review cards, `node.template.create` registry refresh, palette/catalog
  surfaces (the roster/palette were never stale — only the canvas), all existing
  `updateDefaultCode` consumers.

## 3. Recommended Implementation Approach

- **Visibility**: after `createCodeNode`, `setCenter(x + NODE_W/2, y + NODE_H/2, {zoom: getZoom(),
  duration: 400})` — the node is on-screen the moment it exists, for unsaved and persisted flows
  alike (the payload coordinates are the saved ones, so live and saved agree).
- **Content**: creation content rides the node object itself (`data.code` + `data.defaultCode`
  from the factory — no post-insert write to race); `node-content-applied` goes through the
  FlowProvider state path (`applyNodeContent`), never the RF store.
- **Idempotence**: `processedRef: Set<nodeId>` (event-level) + the existing live-graph check
  (state-level) — a re-fired event or a not-yet-synced store can no longer double-insert; a
  later refresh renders the saved node once (same id — React Flow keys by id).

## 4-6. Data/State, UI, Edge Cases (delta only)

- FlowProvider state remains the single live-canvas truth; the bridge never writes the RF store.
- Centering uses the current zoom (no surprise zoom jumps); dashboard mode untouched (the bridge
  only fires from apply actions on the canvas surface).
- Rapid double events, StrictMode double-subscription, template-create path (registry refresh
  then insert), and empty-canvas placement all covered by tests.

## 7-8. Testing + Acceptance

- Integration (REAL FlowProvider/reactflow/useCode; IO stubbed): node-created lands in provider
  state immediately with `data.code`/`data.defaultCode` set; duplicate events insert once;
  node-content-applied updates the live node's content fields; viewport centering invoked.
- Unit: bridge calls `setCenter` with the node center; no RF-store `setNodes` calls remain.
- Full suites green; chat-feedback and apply-flow tests unchanged (behavior preserved).
- [ ] Created node visible immediately, once, with content; content survives a subsequent save.
- [ ] `node.content.write` apply updates the live editor content.
- [ ] No regression in palette drops, dataset drag-drop, or `updateDefaultCode` consumers.

## 9. Commits

1. `Canvas sync: seed data.code at creation, FlowProvider applyNodeContent, viewport centering, event idempotence — with real-provider integration regression (dev/51)`
2. Docs: memo implemented + BL-P5 amendment.
