# Implementation Memo 67-8: Connection Review Stage (Simulation Mode: Connect)

Date: 2026-08-05
Status: implemented 2026-08-05 — COMMIT-4e94a0ac (backend), COMMIT-53bacb88 (frontend).
Verification: backend 1123 passed (8 skipped), frontend 727 passed, tsc clean.
BL-P5-20260805-12. Recorded notes: (1) completion semantics — when every ref and every
edge is applied the proposal flips to applied and the phase follows nodeRuns
(applied|ready), so the classic Solve gate works unchanged; a refused edge keeps the
proposal pending (replan territory); (2) the event-bus kind allowlist silently dropped
the new edges-created mutation until the tests caught it — the dev/61 recognition lesson
one layer down.

## 1. Problem Statement

67-0 separates connections into their own review stage AFTER nodes are created and
validated: proposed edges displayed vertically as an inspectable list
(`source → target` with real node names), each approvable, topology-validated BEFORE
application. Today edges apply as an undifferentiated part of the whole-plan apply
(a count on the card: "N connections"), with no per-edge review, and the bridge's
hardcoded handles bug (fixed by 67-3). With 67-5 applying nodes individually, the
plan's edges need a home.

## Expected Behavior (user-visible walkthrough)

1. After the plan's nodes are created (and validated), the review card shows
   a **Connections** section: a vertical list, one row per planned edge, in
   plain words — `Data Load → Merge [in_0]` — with a status chip
   (planned / applied ✓ / refused ✗).
2. A row stays disabled until BOTH its endpoint nodes exist, with the reason
   as its tooltip ("create 'Analyze' first"). You always know exactly which
   two nodes a click will connect before you approve it.
3. Clicking a row's **Connect** applies that single edge to the spec and the
   live canvas — topology-validated at that moment (67-3): an edge that would
   overfill a single-input node or a full merge is refused BY NAME with the
   Merge suggestion, and the other rows stay applicable.
4. **Apply all** walks the valid rows in one click and reports per edge —
   partial success is normal and honest, never all-or-nothing.
5. An edge you already drew manually shows as "already connected" (no-op);
   merge targets take their named slot or the lowest free one; dismissing the
   proposal keeps applied edges and kills only the planned remainder.
6. What no longer happens: edges materializing as an invisible side effect of
   a bulk apply, and topology problems surfacing only when the dataflow runs.

## 2. Scope

In scope:
- Backend: plan edges become a reviewable stage on the same proposal —
  `POST …/proposals/<id>/apply-edges {edges?: [index]}` applies all (default) or a
  subset of the plan's edges whose endpoints exist (created refs resolved to real ids;
  existing-id endpoints verified), running 67-3's fan-in/handle validation against the
  CURRENT spec at apply time; refusals are per-edge and named
  (`"Load CSV → Analyze: target accepts 1 input; already fed by Clean"`).
  `builderSession` gains `edgeStates: {index: planned|applied|refused}`.
- Frontend `AgentReviewCard.tsx` — a Connections section: vertical list, one row per
  edge, `<source title> → <target title>` (+ handle when explicit, e.g. `→ Merge
  [in_1]`), status chip, per-edge and apply-all controls, disabled until both endpoint
  nodes are `created` (67-5 states).
- Bridge: edge application events reuse the existing graph-created edge path (with
  67-3 handles); per-edge application emits a narrower mutation.
- Sequencing default: the card orders stages nodes-then-connections; 67-9 encodes the
  full state machine.

Out of scope: topology semantics themselves (67-3 owns validation; this memo is the
staging + UI); edge removals (dev/59 revision flow unchanged); manual canvas edge
drawing (untouched; onConnect guard arrives with 67-3).

## 3. Recommended Implementation Approach

Same narrowing pattern as 67-5: the proposal stays the single review artifact; edge
application is a second staged apply over the pinned plan. Validation runs at apply
time against live truth (nodes may have been validated/edited since mint), so a refusal
is honest and per-edge — the remaining edges stay applicable. The card renders edges
from the existing `plan.edges` part data joined with node titles (plan refs) and spec
labels (existing ids); no new part type. `edgeStates` mirrors for the strip and reload.

## 4. Data and State Handling

- Edge indices are stable (the pinned plan's order); states persist on the proposal +
  builderSession mirror.
- Endpoint resolution: ref → `nodeIds[ref]` (67-5); missing (node not yet created or
  deleted) → row disabled/refused with the reason.
- Apply-all is a loop over per-edge applies in one request — partial success is
  reported per edge, never all-or-nothing.

## 5. UI and UX Requirements

- Vertical list, compact dict-like row: `Data Load → Merge [in_0]` + status chip
  (planned / applied ✓ / refused ✗ with reason on hover/expand).
- Rows disabled until endpoints exist, with the reason as the title.
- Accessibility: list semantics, per-row buttons named "Connect <source> to <target>".

## 6. Edge Cases

- Endpoint node deleted after creation → refused naming the missing node.
- Edge already exists in the spec (user drew it manually meanwhile) → applied-as-noop
  with "already connected".
- Merge slot filled manually between mint and apply → next free slot (67-3 rule) or
  refusal when full.
- Duplicate apply of an applied edge → idempotent.
- Plan revision dismisses the proposal → unapplied edges die; applied edges persist.

## 7. Testing Strategy

- Backend: per-edge apply (resolution, 67-3 validation invoked, per-edge refusal
  wording, partial apply-all, idempotence, manual-edge noop, merge slot assignment).
- Frontend: list rendering with titles/handles, disabled-until-created, status chips,
  per-edge + apply-all actions.
- Route-level: nodes-then-edges sequential application equals the classic whole-plan
  apply spec (parity pin, joint with 67-5's).

## 8. Acceptance Criteria

- [x] Plan edges render as a vertical, named, per-edge-approvable list; nothing applies
      until its endpoints exist.
- [x] An edge that would create invalid fan-in is refused BY NAME at the review stage,
      never materialized.
- [x] Sequential per-node + per-edge application reproduces the whole-plan result.

## 9. Recommended Commit Breakdown

1. Backend: apply-edges endpoint + edgeStates + tests.
2. Frontend: Connections section + tests.
3. Docs: memo flip + BL-P5 amendment.

## 10. Engineering Quality Checklist

- Validation logic lives in 67-3 only — this memo stages and surfaces it.
- Per-edge honesty: partial success with reasons, never silent all-or-nothing.
- One proposal artifact end-to-end; reload-safe states.
