# Implementation Memo 67-5: Plan Cards v2 — Per-Node Review, Editable Goals, Per-Node Apply (Simulation Mode: Create)

Date: 2026-08-05
Status: implemented 2026-08-05 — COMMIT-47ea5648 (backend), COMMIT-238c79c9 (frontend).
Verification: backend 1092 passed (8 skipped), frontend 716 passed (66 suites), tsc clean.
BL-P5-20260805-09. Recorded deviations: (1) per-node applies RE-PIN baseGraphDigest to the
spec they produce (own progress is legitimate drift; foreign edits still 409) — the memo's
"same pins" sketch under-specified this; (2) auto-attaching the Node Builder to created
nodes is deferred to 67-6 (its modify-existing posture is the consumer); (3) the
node.content grammar field survives for other consumers — enforcement is the builder
mint's refusal, exactly as §3 planned.

## 1. Problem Statement

The plan review card is all-or-nothing: one Apply materializes the whole graph as empty
placeholder nodes, deferring every problem to bulk Solve. 67-0 requires the opposite
default — each planned node individually inspectable, its goal editable, created one at
a time, and never as a knowingly-unresolved placeholder. Today:

- The card renders a summary + preview lines; node goals are read-only display; the
  only actions are whole-plan Apply/Dismiss (AgentReviewCard.tsx; the strip mirrors the
  same two, dev/53).
- Plans may embed `content` per node (dev/52 grammar) — 67-0 forbids generated code in
  the plan; content belongs to the Solve/validation stage (67-6/67-7).
- `_apply_dataflow_plan` is atomic whole-plan; `builderSession.nodeRuns` tracks only
  `pending|solved|failed|skipped` after creation — there is no per-node "planned but
  not yet created" state.

## 2. Scope

In scope:
- Backend `content.py` — plan grammar: node `content` REJECTED for the builder's plans
  (grammar error with guidance, superseding dev/52's "trivial code" allowance — 67-0:
  "There is no concept of 'trivial code'"); nodes gain optional `expects`
  (input/output one-liner, bounded) for the card.
- Backend `services.py` — per-node apply:
  `POST …/proposals/<id>/apply-node {ref, goal?}` — applies ONE planned node from the
  pinned plan (same digest/authentication machinery as apply; the proposal stays
  pending until all refs are applied or it is dismissed); an edited `goal` overrides
  the planned intent at creation (bounded, recorded on the proposal as
  `editedGoals[ref]`). Edges are NOT applied here (67-8 owns connections).
  `builderSession` extension: `nodeStates: {ref: planned|created|solving|validated|
  approved|failed}` + `nodeIds: {ref: nodeId}` alongside the existing `nodeRuns`
  (which keeps its Solve semantics).
- Frontend `AgentReviewCard.tsx` — per-node rows: type/existing-match, editable goal
  input, expects line, per-node Apply button (+ the whole-plan Apply retained — 67-9
  re-targets it to the automated sequence); applied rows show created state.
- Frontend bridge — single-node creation already exists (`node-created` mutation path,
  dev/48/51) — reused verbatim.
- Auto-attach: applying a node attaches the Node Builder to it (existing attachment
  create API; dev/48's canvas-only limitation lifts for node targets here if trivial,
  else recorded).

Out of scope: solving/validating the node (67-6/67-7); connection stage (67-8);
the full stage state machine + Apply Plan automation (67-9); removals (dev/59 flow
unchanged — revision plans keep their card).

## 3. Recommended Implementation Approach

- **Grammar first**: builder plans are shape-only (type, title, goal, expects, edges);
  `content` in a plan node → corrective error "plans describe intent; content is
  generated and validated per node after creation". (The plan part type is shared —
  the restriction keys off the minting agent's coord staying honest: enforced at mint,
  not in the shared grammar.)
- **Per-node apply is a narrowing of the existing apply**: same proposal, same pins
  (shape digest still guards the whole plan; a per-node apply verifies the plan digest
  + that ref's slice), same `_mark_stale` behavior on drift, same canvas bridge event
  (single `node-created`). Position comes from the same layout math, computed once at
  mint so sequential applies land where the whole-plan apply would have put them.
- **Goal editing is review-stage data**: the input edits the proposal's `editedGoals`
  map via a small `PATCH …/proposals/<id>/plan-goals {ref, goal}` (pending proposals
  only; recorded for audit; the pinned plan bytes stay immutable — edits are an overlay
  applied at creation, so the digest model survives).
- **builderSession.nodeStates** is the Simulation Mode ledger 67-6..67-9 advance;
  phase vocabulary gains `simulating` (alongside dev/52's phases; the strip maps it).

## 4. Data and State Handling

- The proposal remains the single review truth; per-node application status lives on
  the proposal (`appliedRefs: [ref]`) + builderSession mirrors for the strip.
- A per-node apply after the plan went stale → existing 409 + stale path.
- Reload mid-sequence: nodeStates/appliedRefs persist; the card re-renders rows with
  their states (created rows inert).

## 5. UI and UX Requirements

- Node rows vertical, one per planned node: title, type (or existing-node match),
  editable goal (textarea, saved on blur with busy/error states), expects line,
  Apply button → "Created ✓" (disabled) with the real node centered on canvas
  (existing setCenter path).
- No generated code anywhere on the card.
- Accessibility: rows are a list; the goal input labeled by node title; apply buttons
  named "Create node <title>".

## 6. Edge Cases

- Goal edited then plan re-minted (revision) → editedGoals die with the old proposal.
- Per-node apply of a ref already applied → idempotent no-op with honest message.
- Node type vanished between mint and per-node apply → per-ref 409 naming it.
- Dismiss with some nodes applied → applied nodes stay (they are real reviewed nodes);
  builderSession keeps their states; remaining refs die with the proposal.
- Concurrent per-node applies (double click) → proposal-level lock, second is a no-op.
- Canvas node deleted after creation → nodeStates keeps `created` but 67-7 validation
  will report the absence honestly (spec is truth).

## 7. Testing Strategy

- Grammar: content-in-plan refusal (builder mint), expects bounds.
- Mint: positions precomputed per ref; editedGoals overlay applied at creation.
- Per-node apply: single node created (spec + bridge event), pins verified, stale plan
  409, applied-ref idempotence, dismiss-after-partial semantics.
- Frontend: card rows render/edit/apply per state; goal PATCH busy/error; "Created ✓".
- Route-level: full sequential application of a 3-node plan equals the whole-plan
  apply's spec (byte-parity on nodes).

## 8. Acceptance Criteria

- [x] A minted builder plan shows per-node rows with editable goals and per-node Apply;
      applying creates exactly that node with the (possibly edited) goal.
- [x] No plan can carry generated code; the corrective error teaches the split.
- [x] Partial application survives reload and dismissal keeps created nodes.

## 9. Recommended Commit Breakdown

1. Backend: grammar restriction + expects + editedGoals PATCH + tests.
2. Backend: apply-node endpoint + nodeStates + tests.
3. Frontend: card rows + goal editing + per-node apply + tests.
4. Docs: memo flip + BL-P5 amendment.

## 10. Engineering Quality Checklist

- One review machinery — per-node apply narrows, never forks, the proposal model.
- Pinned plan bytes immutable; edits are an audited overlay.
- The card stays the single review surface; the strip mirrors, never owns.
