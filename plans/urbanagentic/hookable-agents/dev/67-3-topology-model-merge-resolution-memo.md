# Implementation Memo 67-3: Topology Model + Merge-Node Resolution (Foundation B)

Date: 2026-08-05
Status: implemented 2026-08-05 — COMMIT-d746a136 (arity model), COMMIT-33ff906e
(mint/apply/grammar/instruction), COMMIT-e7e1ee6d (frontend guard + bridge).
Verification: backend 1084 passed (8 skipped), frontend 707 passed, tsc clean.
Ledger: DEC-051 (dev/03 + 2.1), BL-P5-20260805-08. Recorded deviation: maxIncomingEdges
derives from RENDERED capacity (port count; merge=5) rather than summed declared maxima —
declared [1,n] (e.g. computation-analysis) is aspirational; the input plumbing is scalar
per handle, so declared maxima ride the `inputs` metadata rows only.

## 1. Problem Statement

Nothing in the system can answer "can node type T accept N independent incoming
edges?" — so invalid fan-in is created silently and discovered at execution:

- Manifests DO declare `inputPorts[].cardinality` (`"1"`, `"[1,n]"`, …), but no parser
  exists anywhere; `available_templates` (packages/services.py:187) strips ports before
  the agents module sees them; the frontend uses port count only for handle presence.
- `isValidConnection` returns `true` unconditionally (FlowProvider.tsx:980); `onConnect`
  checks handle classes, type compatibility, merge slots, and cycles — but has NO
  in-degree rule: a second edge into a plain `in` handle is accepted and
  `data.input`/`data.source` is silently overwritten (last writer wins,
  FlowProvider.tsx:668); deleting either parallel edge blanks the input for both
  (:711). The node runs after both parents (Kahn ordering is correct) but sees one.
- Multi-input is `if (nodeType === NodeType.MERGE_FLOW)` in four FlowProvider sites —
  a type identity check, not a capability check: spatial-join's two named handles
  (`in_points`/`in_polygons`) are excluded from slot bookkeeping and collapse into one
  scalar input; any future multi-input package node inherits the same silent breakage.
- Plan mint validates edges referentially only (services.py:1245-1272 — endpoint ∈
  refs ∪ existing ids); the plan grammar has no handle field; the bridge inserts every
  plan edge with hardcoded `targetHandle: "in"` (useAgentCanvasMutations.ts:100-101) —
  for a merge target that handle DOES NOT EXIST (`in_0..in_4`), so the slot never fills
  and the merge never emits until a reload heals it through the load path.

Expected (67-0): the orchestration layer inspects the target's input structure before
creating edges, introduces the existing Merge node when fan-in requires it, and never
materializes an invalid graph.

## 2. Scope

In scope:
- Backend `app/packages/manifest.py` — `parse_cardinality("[1,n]") -> (min, max|None)`.
- Backend `app/packages/services.py` — `available_templates` gains
  `inputs: [{handle?, types, min, max}]` + derived `maxIncomingEdges`.
- Backend `app/agents/content.py` — plan edge grammar gains optional `toHandle`.
- Backend `app/agents/services.py` — `_mint_dataflow_plan` in-degree validation over
  plan edges ∪ surviving existing edges, with merge-resolution corrective guidance;
  `_apply_dataflow_plan` writes handles (merge targets get free `in_N` slots).
- Frontend `useAgentCanvasMutations.ts` — bridge edges carry the applied handles.
- Frontend `FlowProvider.onConnect` — descriptor-driven in-degree guard (toast parity
  with the merge-slot messages); multi-input becomes a descriptor capability
  (`inputPorts` arity + named handles), consulted where MERGE_FLOW is special-cased.
- `orchestration_instruction.txt` — one added sentence in step 2 (fan-in → route
  through `curio.builtin/merge-flow`).
- Ledgers: DEC-051.

Out of scope: auto-INSERTING merge nodes at mint (the corrective round asks the model
to replan with a merge — self-correcting contract, not silent graph surgery); the
connection review stage UI (67-8); spatial-join's per-handle input plumbing beyond the
capability flag (its runtime fan-in fix rides the same descriptor but its behavior file
is its own change); changing `MERGE_SLOT_COUNT`.

## 3. Recommended Implementation Approach

**A. One arity model, parsed once (DEC-051).** `parse_cardinality` in `manifest.py`
(strings are already schema-validated); `available_templates` serves per-template
`inputs` and `maxIncomingEdges` = 0 (no input ports), N (sum of finite maxima × handles:
merge = 5 rendered slots wins over the declared `[1,n]` — the RENDERED capacity is the
enforceable truth), or `null` (unbounded). The frontend descriptor already receives
ports; add the same parse to `packagesClient.ts` so both layers read one semantics.

**B. Plan mint validates fan-in.** For each plan-edge target (plan refs AND existing
ids): incoming = plan edges into it + surviving existing edges (minus removeNodes/
removeEdges victims — the dev/59 sets are already computed at mint). If incoming >
maxIncomingEdges, the mint refuses with a corrective error naming the fix:
`"nodes[i] '<title>' (<type>) accepts 1 input but the plan wires 2 (from 'a', 'b') —
route them through a curio.builtin/merge-flow node instead"`. This rides the dev/54
correction rounds — the model replans with the merge; no silent mutation. Merge targets
additionally validate slot capacity (≤5 total).

**C. Handles become explicit end-to-end.** Plan grammar: optional `toHandle` (bounded
string, validated against the target template's declared/known handles; merge accepts
`in_N` or unset). Apply assigns merge slots deterministically (lowest free `in_N`,
mirroring onConnect's logic) and writes `sourceHandle`/`targetHandle` on the spec edge;
`appliedGraph.edges` carries them; the bridge passes them through instead of hardcoding
`"in"` — fixing the dead-merge-until-reload bug outright.

**D. `onConnect` in-degree guard, descriptor-driven.** Before accepting an `in*` edge:
`incomingCount(target, handle)` vs the descriptor's arity — single-input nodes refuse a
second edge with a toast ("<label> accepts one input — route multiple flows through a
Merge node"); the merge special cases collapse into the capability check (behavior
unchanged for merge; spatial-join stops colliding at the connect layer). The guard also
runs in the load path only as a warning (never drop persisted edges — surface, don't
destroy).

## 4. Data and State Handling

- The manifest is the single arity truth; both layers parse the same strings; no new
  stored state. Spec edges gain optional handle fields (already serialized when present
  — TrillGenerator.ts:241).
- Mint-time validation uses the SAVED spec's surviving edges (consistent with dev/59
  victim math); the connect-time guard uses live edges. Both enforce; neither trusts
  the other.

## 5. UI and UX Requirements

- Refused connections toast with the merge suggestion (message parity with the existing
  merge-slot toasts).
- Plan review card unchanged (67-8 adds the connection stage); corrective plan errors
  surface through the existing dev/54 loop.

## 6. Edge Cases

- Existing node already at capacity + plan adds an edge → mint refusal names the
  existing edge.
- Plan removes an edge into T and adds another → net in-degree computed on survivors.
- Unknown/custom template with no ports metadata → unbounded (fail-open, warn in the
  corrective message only when fan-in > 1).
- `toHandle` naming an occupied merge slot → next free slot at apply (deterministic),
  or refusal when full.
- Legacy specs with handle-less multi-input edges → load warning, never edge-dropping.
- Two plan edges same source→target → already deduped (dev/59 grammar).

## 7. Testing Strategy

- `parse_cardinality` table test (all schema forms).
- `available_templates` projection (merge = 5, single-port "1" = 1, no-ports = 0,
  spatial-join = 2 named handles).
- Mint: fan-in refusal message + corrective round replan-with-merge end-to-end; merge
  capacity; survivor math with removals; unknown-template fail-open.
- Apply/bridge: merge target gets `in_0`/`in_1` written to spec AND live canvas (the
  reload-heals bug pinned as a regression).
- Frontend onConnect guard: second edge refused on single-input, merge unchanged,
  spatial-join per-handle accepted.

## 8. Acceptance Criteria

- [x] A plan wiring `A → C, B → C` for single-input `C` never mints — the corrective
      error names the Merge resolution, and the model's replanned `A → Merge, B →
      Merge, Merge → C` mints and applies with real `in_N` handles that work WITHOUT
      a reload.
- [x] Manually dragging a second edge into a single-input node is refused with the
      merge-suggestion toast; merge behavior is byte-identical.
- [x] No layer decides multi-input by `nodeType === MERGE_FLOW` anymore.

## 9. Recommended Commit Breakdown

1. Backend: cardinality parse + `available_templates` arity projection + tests.
2. Backend: plan grammar `toHandle` + mint fan-in validation + apply handle writing +
   instruction sentence + tests.
3. Frontend: bridge handle pass-through + onConnect descriptor guard + tests.
4. Docs: DEC-051 ledgers + BL-P5 entry.

## 10. Engineering Quality Checklist

- One parser, two consumers — no duplicated arity semantics.
- Self-correcting contract preserved: refusal + precise guidance, never silent surgery.
- Persisted data is never destroyed by validation (load warns, apply refuses upfront).
- The rendered capacity (5 slots) is the enforced truth where declaration and rendering
  disagree — recorded in DEC-051.
