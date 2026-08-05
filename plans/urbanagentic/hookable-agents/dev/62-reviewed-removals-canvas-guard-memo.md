# Implementation Memo: Reviewed Removals vs. the Manual Delete Guard — the Bridge Gets Its Own Removal Path (dev/59 follow-up)

Date: 2026-08-05
Status: proposed (implementing in the same session — explicit fix report: applying a
remove-only plan spams "Connected boxes cannot be removed" warnings, victims stay on the
canvas until a refresh)

## 1. Problem Statement

Applying the remove-only plan works server-side but breaks live on the canvas:

- A toast warning fires **per connected victim**: "Connected boxes cannot be removed. Remove
  the edges first by selecting it and pressing backspace." — the "lot of warnings".
- Connected nodes are **not removed live**; edges and isolated nodes are. After a refresh the
  canvas reloads from the (correctly updated) saved spec and shows the true result — exactly
  the user's observation.

Root cause: the dev/59 bridge routes node victims through
`useWorkflowOperations.applyRemoveChanges` (useWorkflowOperations.ts:388), which is the
canvas's **manual-delete guardrail**: it scans `reactFlow.getEdges()` and refuses any node
that still has an incident edge (that UX rule exists so palette users don't strand edges).
The bridge removes nodes FIRST and edges second (useAgentCanvasMutations.ts:81-89), so every
connected victim is refused while its edges are still live. Reordering cannot fix it: the
guard reads `reactFlow.getEdges()`, and same-tick edge removals via `onEdgesChange` are not
visible there until React commits — the guard would still see the old edges.

The guard is also semantically wrong for this caller. DEC-049: the user reviewed every victim
BY NAME and clicked Apply — that authenticated click *is* the authorization, and the backend
already removed the full edge cascade in the same operation (`removedEdgeIds` includes every
edge incident to a victim, services.py:1637-1645, delivered in the same `graph-created`
event). There are no edges to "remove first"; they are being removed together.

## 2. Scope

In scope:
- `utk_curio/frontend/urban-workflows/src/hook/useWorkflowOperations.ts` — new
  `applyReviewedRemovals(nodeIds, edgeIds)` beside `applyRemoveChanges`.
- `utk_curio/frontend/urban-workflows/src/providers/FlowProvider.tsx` — context type,
  default stubs, value wiring.
- `utk_curio/frontend/urban-workflows/src/components/agents/attach/useAgentCanvasMutations.ts`
  — the bridge's graph-created handler uses the new path.
- Tests: `tests/attach/useAgentCanvasMutations.test.tsx` (mock + dev/59 removal tests),
  new `tests/hook/useWorkflowOperations.reviewedRemovals.test.ts` (installSync harness),
  context-mock parity in `tests/attach/agentCanvasBridge.integration.test.tsx` and
  `tests/providers/playAllFlakiness.test.tsx`.

Out of scope:
- `applyRemoveChanges` itself — the guard stays byte-identical for its real customer, the
  per-node manual delete button (styles.tsx:412).
- Backend — the spec-side removal, cascade, and event payload are correct (dev/59 tests).
- `onNodesDelete` / `onEdgesDelete` — reused as-is for bookkeeping parity.

## 3. Recommended Implementation Approach

Give reviewed removals their own centralized operation, mirroring the house idiom that
`cleanCanvas` (useWorkflowOperations.ts:358) already uses for authorized bulk removal —
edge bookkeeping first, then state filters, no connected-guard:

```ts
const applyReviewedRemovals = useCallback((nodeIds: string[], edgeIds: string[]) => {
    // A reviewed plan apply (DEC-049): the user authorized every victim by
    // name and the cascade arrived with them — the manual-delete guard
    // ("remove the edges first") does not apply; the edges leave in the
    // same operation. Bookkeeping parity with manual deletion.
    const edgeSet = new Set(edgeIds);
    const victimEdges = reactFlow.getEdges().filter((e) => edgeSet.has(e.id));
    if (victimEdges.length) {
        onEdgesDelete(victimEdges);
        setEdges((prev) => prev.filter((e) => !edgeSet.has(e.id)));
    }
    const nodeSet = new Set(nodeIds);
    const live = reactFlow.getNodes().filter((n) => nodeSet.has(n.id));
    if (live.length) {
        const changes = live.map((n) => ({ id: n.id, type: "remove" as const }));
        onNodesDelete(changes);
        onNodesChange(changes);
    }
}, [reactFlow, onEdgesDelete, setEdges, onNodesDelete, onNodesChange]);
```

- `onEdgesDelete` keeps manual-parity bookkeeping: collab broadcast, provenance version,
  survivor-target input reset + staleness (matters for replace flows where the edge dies but
  its target survives).
- `onNodesDelete` keeps output pruning, provenance, collab broadcast.
- Already-absent elements no-op by construction (both filters run against live state) — the
  bridge keeps its own live-filter for node idempotence, and edge idempotence now lives here.

The bridge's graph-created handler replaces the two-step
(`applyRemoveChanges` + `onEdgesChange` removes) with one call:
`applyReviewedRemovals(removedNodeIds, removedEdgeIds)` — still before inserts, so new edges
wire to survivors.

## 4. Data and State Handling

Source of truth unchanged: the backend spec was already correct; this fixes only the live
mirror. Edge removals and node removals land in the same React commit (both state updates are
queued in one handler tick), so no intermediate frame renders an edge without its node.
No new state; the guard path and the reviewed path are separate functions with separate
callers.

## 5. UI and UX Requirements

- Applying a remove-only or replace plan removes victims and their edges live — no toast
  warnings, no refresh needed.
- Manual node deletion keeps its guard and its warning verbatim.
- Provenance records the removals ("Node deleted"/"Connection deleted" versions), and
  collaborators receive the broadcasts — identical to manual deletion.

## 6. Edge Cases

- Victim already deleted live by the user — filtered out; no-op.
- Edge already gone live — filtered out; no-op.
- Replace flow (edge dies, target survives) — survivor's input/source reset + marked stale,
  as a manual edge delete does.
- Remove-only plan (no inserts) — removals run, fit still frames the result.
- Re-fired graph-created event — plan-id idempotence in the bridge (unchanged) plus
  live-filters here.
- Plan with inserts only — `applyReviewedRemovals` not called (empty guard in the bridge).

## 7. Testing Strategy

- New `useWorkflowOperations.reviewedRemovals.test.ts` (renderHook harness): connected
  victims + their edges removed in one call — `onEdgesDelete`/`onNodesDelete` called,
  node/edge state filtered, **no toast**; absent ids no-op; `applyRemoveChanges` guard
  regression-pinned (connected node still refused with the toast).
- `useAgentCanvasMutations.test.tsx`: the dev/59 removal tests updated — the bridge calls
  `applyReviewedRemovals(victims, edges)` before inserts; absent victims filtered from the
  call.
- Context-mock parity in the integration + flakiness suites.
- Full frontend suite green.

## 8. Acceptance Criteria

- [ ] Applying the clear-canvas plan empties the canvas live: no "Connected boxes cannot be
      removed" toasts, no refresh required.
- [ ] Replace flows rewire to survivors whose inputs are reset, live.
- [ ] Manual delete behavior (guard + warning) is byte-identical.

## 9. Recommended Commit Breakdown

1. `Reviewed removals bypass the manual-delete guard: applyReviewedRemovals + bridge rewire
   (dev/62)` — hook + provider + bridge + all tests.
2. `Docs: dev/62 implemented + BL-P5 amendment`.

## 10. Engineering Quality Checklist

- Centralized: one removal policy per authorization kind, both in useWorkflowOperations.
- No duplicated bookkeeping — `onEdgesDelete`/`onNodesDelete` reused.
- No race: one function, one commit; no reliance on state visibility between steps.
- Manual path untouched; regression tests pin both paths.
