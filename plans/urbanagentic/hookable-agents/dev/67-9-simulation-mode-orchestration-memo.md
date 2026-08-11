# Implementation Memo 67-9: Simulation Mode Orchestration + Apply Plan as Automated Sequence (Assembly)

Date: 2026-08-05
Status: implemented 2026-08-05 — COMMIT-4e35002b (backend driver + the parked-plan
mechanism), COMMIT-7beca0dd (frontend). Verification: backend 1128 passed (8 skipped),
frontend 732 passed, tsc clean. Ledger: DEC-054 (dev/03 + 2.1), BL-P5-20260805-13.
Recorded deviations: (1) THE PARKED PLAN — the single-activeProposal model would have
let the sequence's own content reviews supersede the pending plan; it now parks on
`record.planProposal`, stays addressable through `_pending_plan_proposal`, and is
cleared on completion/replacement (the memo did not anticipate this knot); (2) no
dedicated Pause button — Cancel stops at the boundary and Resume continues from
persisted state, which covers the memo's pause semantics with one less control;
(3) stage chips stay Plan/Review/Simulate(=Solve rank)/Ready — a separate Connect chip
awaits demand.

## 1. Problem Statement

67-2..67-8 deliver the pieces; this memo makes granular Simulation Mode the DEFAULT
build model (67-0) and re-targets Apply Plan to an automated run of the same validated
loop:

`Plan → per node (Review → Create → Solve → Execute-through → Validate → Approve) →
Connections`

replacing `Plan → Create entire graph → Solve entire graph`. Apply Plan must never
revert to bulk generation: it automates the sequence (fewer clicks), preserving
per-node generation, per-node Solve, runtime validation, error isolation,
self-correction, ordering, and topology checks — and a node failure pauses progression
instead of materializing the rest of an invalid graph.

## Expected Behavior (user-visible walkthrough)

1. Simulation Mode is the DEFAULT: a freshly minted plan offers **Step** and
   **Build & validate plan** (the re-targeted Apply Plan), not bulk creation.
   The classic whole-graph apply survives only as an explicit secondary
   "Apply all without validation" action.
2. **Step** performs exactly one stage per click — create the next node,
   propose its content, validate it — so every stage is individually
   inspectable. **Build & validate** runs the same sequence automatically:
   create node 1 → solve → execute-through → validate → auto-approve on PASS
   → node 2 → … → connections, in topological order so downstream generation
   sees real upstream results.
3. The strip narrates the whole run: stage chips (Plan → Review → Simulate →
   Connect → Ready), the current node and step counter ("validating Clean
   Data — 2/5"), and live pills per node.
4. Any failure PAUSES the run with a plain sentence naming the reason and
   the next action ("Validation failed on Clean Data — review the proposed
   content below, then Resume"). Nothing downstream of a failure is
   generated or created; the pending review holds the evidence.
5. Pause, Resume (from exactly where it stopped — including after a browser
   reload), and Cancel (dev/63 semantics) are always available. If you edit
   a node mid-sequence, the run pauses on the digest conflict and Resume
   re-reads the truth — your edit wins.
6. What no longer happens: "Apply Plan" bulk-creating an unvalidated graph,
   a node failure letting the rest of an invalid graph materialize, and any
   approval click being silently skipped without the auto-approve-on-PASS
   rule being recorded on the proposal.

## 2. Scope

In scope:
- Backend: the sequence driver —
  `POST …/attachments/<id>/simulate {mode: "step"|"auto", from?}` streaming (dev/63
  envelope): advances the builderSession state machine
  `plan_review → simulating(nodeStates per ref: planned → created → solving →
  validated → approved) → connecting(edgeStates) → ready`. `step` performs the next
  single action and returns; `auto` (the new Apply Plan) chains them: create node →
  propose content (67-6) → validate (67-7) → AUTO-approve on PASS (the recorded
  reduction of approval clicks; a FAIL pauses the run with the evidence and the
  pending proposal for manual review) → next node in topological order → edges stage
  (67-8 validation, auto-apply of valid edges, pause on refusals).
  Cancellation + progress ride the dev/63 patterns (stop event + durable flag).
- Ordering: nodes sequenced by the plan's topological levels (mint's `_plan_depths`),
  so upstream validates before downstream generates (downstream context then contains
  real schemas — 67-6/67-2).
- Frontend: the builder strip becomes stage-aware: phase chips gain `Simulate` /
  `Connect`; the current step named ("validating Clean Data — 2/5"); controls:
  Step / Run all (auto) / Pause / Cancel; per-node states mirrored from
  builderSession; Apply Plan button on the card = `auto` mode (label "Build & validate
  plan"); dev/52's classic whole-plan apply remains reachable behind an explicit
  "Apply all without validation" secondary action (recorded: kept for revision plans
  and power use — never the default).
- Defaults: builder plans mint into Simulation Mode (`DEC-054`); removals/revision
  plans (dev/59) keep the classic card flow.
- Ledgers: DEC-054.

Out of scope: background/parallel execution (sequential inside the streamed request;
DEC-021 unchanged); multi-plan queueing; retrying infrastructure failures
automatically.

## 3. Recommended Implementation Approach

The driver is deterministic orchestration code (DEC-048 posture) over the endpoints
the earlier memos built — it calls the same per-node apply, propose-solve, validate,
and apply-edges internals in-process (not via HTTP), emits their streamed events under
one stream, and persists every state transition to builderSession before emitting it
(reload lands exactly where the run stopped; `step` and `auto` share one transition
function — auto is a loop with pause rules). Pause rules: validation FAIL, per-edge
refusal, digest conflict (user edited), cancellation, sandbox unreachable. Resume =
the same endpoint with `from` (the stalled ref), after the user resolves the pending
review or edits the goal (67-5) and re-runs.

## 4. Data and State Handling

- builderSession is the single machine state (nodeStates + edgeStates + `currentRef` +
  `pauseReason`); every transition persisted-then-emitted; the strip renders from the
  session, events only animate.
- One simulate run at a time per attachment (the dev/63 in-flight guard pattern,
  15-minute staleness).
- Auto-approve on PASS is recorded on the proposal (`approvedBy: "simulation-auto"`)
  — auditable, distinct from manual applies.

## 5. UI and UX Requirements

- The strip narrates the loop: stage chips, current node, step counter, pause reason
  as a plain sentence with the next action ("Validation failed on Clean Data — review
  the proposed content below, then Resume").
- Step mode gives one action per click for full inspection; Run all requires no clicks
  until a pause.
- Nothing labeled Apply ever bulk-creates unsolved nodes.

## 6. Edge Cases

- User manually edits/solves a node mid-sequence → digest machinery pauses with the
  conflict named; Resume re-reads truth (the node may now be `approved` via user
  content — dev/52 skip semantics).
- Plan revision minted mid-sequence → the old proposal's remaining refs die (67-5
  dismissal semantics); applied work persists; the new plan starts its own sequence.
- Upstream validation failure → downstream refs stay `planned` (never generated
  against a broken upstream).
- Browser closed mid-auto → dev/63 disconnect semantics: current step finishes
  server-side, state persists, strip resumes on reload.
- Step called when a proposal awaits review → honest 409 "review the pending content
  first".

## 7. Testing Strategy

- Transition-function unit tests (every state × event, pause rules, resume points).
- Route/stream: full auto run over a 3-node plan with a seeded validation failure at
  node 2 → node 1 approved, run paused, node 3 untouched; resume after manual apply
  completes; cancellation; disconnect persistence.
- Step-mode parity: N step calls ≡ one auto run (same final session, minus pauses).
- Frontend: strip stage rendering, pause narration, Step/Run all/Resume wiring.
- End-to-end parity pin: a fully-approved simulation equals the classic apply+solve
  result for a plan with no failures.

## 8. Acceptance Criteria

- [x] A new builder plan defaults to Simulation Mode; Apply Plan runs the automated
      validated sequence and PAUSES on the first failure with the evidence and a
      pending review — never materializing the remainder.
- [x] Step mode exposes every stage individually; reload resumes exactly.
- [x] The classic bulk apply exists only as the explicit secondary action.

## 9. Recommended Commit Breakdown

1. Backend: state machine + simulate endpoint (step) + tests.
2. Backend: auto mode + pause/resume + cancellation + tests.
3. Frontend: stage-aware strip + card wiring + tests.
4. Docs: DEC-054 ledgers + BL-P5 entry + dev/52/67-0 closure pointers.

## 10. Engineering Quality Checklist

- One transition function; step and auto cannot diverge.
- Persist-then-emit: no state exists only in a stream.
- Every pause is a named reason with a next action; no silent stalls.
- The validated loop is the only loop — Apply Plan automates it, never bypasses it.
