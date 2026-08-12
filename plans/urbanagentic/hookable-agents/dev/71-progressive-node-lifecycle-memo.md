# Implementation Memo 71: Progressive Node Lifecycle — Per-Node Connect/Solve/Run on the Plan Card (dev/67 adjustment)

Date: 2026-08-12
Status: implemented 2026-08-12 — COMMIT-4aa2f6f6 (progressive core + auto-attach),
COMMIT-4ae50b66 (run-node stream), COMMIT-2d9b5c05 (rows + readiness). Verification:
backend 1156 passed (8 skipped), frontend 776 passed, tsc clean. BL-P5-20260812-15.
Recorded deviations: (1) progressive edges complete the plan STRUCTURE earlier than
67-8 assumed — completion stays the all-refs+all-edges milestone, the parked plan is
now KEPT after completion (per-row Solve/Run and the driver's validate/approve continue
on the applied plan), and the last content approval flips the phase to ready; (2) run
outcomes reach the user via the transcript result card and agents via the journal —
a per-row outcome chip is recorded as follow-up; (3) five dev/67 tests were updated
deliberately to the progressive semantics (named in the BL entry).

## 1. Problem Statement

The dev/67 program shipped the granular stages, but their SEQUENCING is still
batch-shaped in three places the owner's adjustment names:

- **Connections wait for everything.** 67-8 stages edges as a separate review
  AFTER node creation/validation: an edge between two already-applied nodes
  sits unapplied until the user (or the 67-9 driver's final stage) reaches the
  Connections section. The graph is therefore NOT progressively executable —
  a solved upstream node and its solvable downstream neighbor stay
  disconnected while unrelated plan rows are still pending.
- **Solve and Run are not per-node surfaces.** Solving a specific node goes
  through the 67-9 driver (step/auto) or the classic batch; running through a
  node goes through the canvas play button. The plan card's rows — the place
  the user is actually working — expose only Apply (create). There is no
  per-row Solve that lights up when a node's dependencies are ready, and no
  per-row Run that executes through the node and feeds the results back to
  the agents.
- **The deferred auto-attach never landed.** 67-5 deferred attaching the Node
  Builder to each created node (67-6 lifted its canvas-only targets, making
  it possible); the row's node still has no attached agent to operate as its
  creation/content-building orchestrator.
- **Rows show no dependency information.** The card lists title/type/goal/
  expects but not what each node depends on — the user cannot see WHY a
  node's Solve is disabled.

Everything needed already exists as machinery: per-edge validated application
(67-8 `apply_plan_edges`), full-context generation + validated content
proposals with the Get Code apply model (67-6/67-7 `validate-node`),
execute-through with journaled outputs/errors (67-2 journal + 67-7
`run_through_node`), and the `nodeStates`/`edgeStates` ledgers. This memo
re-sequences them progressively and surfaces them per row.

## Expected Behavior (user-visible walkthrough)

1. Each plan row shows, alongside its type and editable goal, its
   **dependencies by name** ("needs: Load CSV, Clean Data") — so a disabled
   Solve explains itself.
2. Clicking a row's **Apply**: creates that node, **attaches the Node
   Builder to it**, and immediately draws every plan edge whose other
   endpoint already exists (created rows or existing canvas nodes) — the
   graph grows connected, not as an island collection. A refused edge
   (topology) shows on the row/Connections section; it never blocks the
   node's creation.
3. Each applied row exposes its own **Solve** button, enabled the moment the
   node's dependencies are connected and its upstream plan nodes carry
   applied content ("sufficiently validated") — downstream work starts as
   soon as ITS inputs are real, never waiting for the whole plan. Solve runs
   the 67-7 loop (full dataflow context → generate → execute-through →
   verdict → self-correct) and lands the reviewed content proposal; applying
   it follows the legacy Get Code interaction exactly (review → Apply →
   content written to the node, live).
4. Each solved row exposes **Run**: executes the dataflow through that node
   (upstream chain included) and reports outputs, schema/metadata, logs,
   warnings, errors, and validation messages — persisted to the runtime
   journal, so the Node Builder, debug agent, and explainer can read exactly
   what happened and self-correct from it.
5. The lifecycle per node is therefore
   `Plan → Apply (create + connect available) → Solve → Apply content →
   Run through node → Validate → Continue` — every stage inspectable, the
   graph executable at every step of the build.
6. What no longer happens: edges waiting for the whole plan, Solve/Run living
   only in batch controls or the canvas, created nodes without their Node
   Builder, and rows whose readiness the user has to guess.

## 2. Scope

In scope (backend):
- `apply_plan_node` (services.py): after creating the node — (a) auto-attach
  the Node Builder (installed → `attachments.attach` with the node target;
  not installed / already attached → skip, noted in the response); (b)
  progressive connection: auto-apply every plan edge whose endpoints both
  resolve now, through the EXISTING 67-8 per-edge machinery (same fan-in/
  merge-slot validation, same `edgeStates`, refusals recorded per edge and
  never blocking the node); response gains `createdEdges` + `attachedAgentId`.
- New `run_node_stream` (services.py) + `POST …/attachments/<id>/run-node
  {ref|nodeId}` (routes.py): the 67-7 runner WITHOUT a candidate — executes
  the SAVED content through the node's upstream chain, streams
  `node_executed` progress, journals every execution (`validation: false` —
  these are real runs), and finishes with the per-node report (status,
  stderr/stdout tails, output metadata) + a result-card turn. Guarded by the
  same in-flight/staleness pattern as validate.
- Mint (plan part): per-node dependency rows are DERIVABLE client-side from
  the 67-8 `plan.edges` labels — no backend display change needed (verified).
- 67-9 driver: inherits progressive connection automatically through
  `apply_plan_node`; its final connect stage now applies only the remainder
  (typically none) — behavior otherwise unchanged.

In scope (frontend):
- Plan card rows (`AgentReviewCard`): dependency line ("needs: …" from
  `plan.edges`); per-row **Solve** (enabled by the readiness rule below;
  calls `validateNode({ref})`) and **Run** (approved rows; calls the new
  `runNode({ref})`); row state chips extend
  `Created ✓ → Solving… → Content review → Solved ✓ → Run ✓/✗`.
- Readiness rule (client-side, from mirror data): a ref is SOLVABLE when
  every incoming plan edge is `applied` in `edgeStates` AND every upstream
  plan-ref is `approved` in `nodeStates` (existing-id upstreams count as
  ready); RUNNABLE when its own state is `approved`.
- Provider/api: `runNode` stream method (maps progress to narration);
  `applyPlanNode` result handling extends to dispatch the new
  `createdEdges` through the existing `edges-created` bridge event.
- Attachment list refresh after apply shows the auto-attached Node Builder
  badge (existing listing mechanics).

Out of scope: the 67-8 Connections section (kept — it reviews/retries the
remainder and refusals); the 67-9 driver's step/auto semantics; the classic
batch Solve; changing solvability into a server-enforced gate (the endpoints
stay honest — the UI gates, the server reports truthfully); removals
(dev/59); multi-plan concurrency.

## 3. Recommended Implementation Approach

- **Progressive connection = a narrowing of 67-8, not a new path.** Extract
  the per-edge application core of `apply_plan_edges` into
  `_apply_one_plan_edge(...)` used by both the endpoint and
  `apply_plan_node`'s post-create sweep (eligible = both endpoints resolve;
  not already applied). One validation policy, two callers.
- **Auto-attach is best-effort and idempotent**: resolve the project's
  installed `agent.node-builder@…` coord from the lockfile; skip when absent
  or when the node already carries a node-builder attachment; the response
  says which happened. Rule-9/preserve-agent-state already covers the new
  attachment's persistence.
- **Run = validate minus generation.** `run_node_stream` wraps
  `runner.run_through_node(spec, node_id, candidate_content=None)` in the
  dev/63 thread+queue streaming pattern (live `node_executed`), writes the
  journal with `validation=False`, appends a result card ("Ran through
  <label>: ok — output dataframe · 4 upstream nodes"; failures carry the
  stderr tail), and returns the report in `done`. Agents read the results via
  the EXISTING `node.runtime.read`/`dataflow.read` runtime block — the
  "accessible to agents" requirement is the 67-2 journal, already wired.
- **Row readiness stays client-computed** from `plan.edges` × `edgeStates` ×
  `nodeStates` (all already on the mirror) — no new persisted state, no new
  sync problem; the server endpoints remain honest on out-of-order calls.

## 4. Data and State Handling

- No new stores: `nodeStates`/`edgeStates`/`nodeProposals` (67-5/8/9) carry
  the lifecycle; run outcomes live in the 67-2 journal; the proposal stays
  the single review artifact and still parks per 67-9.
- Progressive edge refusals mark `edgeStates[i] = "refused"` exactly as the
  connect stage does — the Connections section is the retry surface.
- `run-node` requires the ref/node to exist; running an unsolved (empty)
  node is allowed but will honestly fail — the UI simply doesn't offer Run
  until `approved`.

## 5. UI and UX Requirements

- Dependency line per row, plain words, from labels the user already knows.
- Solve disabled state explains itself via tooltip ("needs 'Clean Data'
  connected and solved first").
- Run progress narrates like validation ("executing upstream 2/4…"); the
  outcome lands as a result chip on the row + the transcript card.
- No layout jumps: the row's action cluster (Apply/Solve/Run/chips) occupies
  one stable slot.

## 6. Edge Cases

- Apply order is free: applying B before A creates B unconnected; applying A
  then draws A→B automatically (eligibility re-swept on every apply).
- An edge to an EXISTING canvas node connects on the FIRST apply that makes
  it resolvable.
- Progressive refusal (fan-in/merge full) → row + Connections section show
  it; the node itself is created normally.
- Node Builder not installed → apply succeeds, response notes the skip.
- Auto-attached agent, node later deleted → dev/32 pruning already handles it.
- Run on a node whose upstream was edited after solving → the run reports the
  real outcome; the journal's contentChangedSinceRun signal already flags it.
- Driver auto mode: create now connects eligible edges immediately, so
  validation of downstream refs sees real wiring earlier; the final connect
  stage applies leftovers only.

## 7. Testing Strategy

- Backend: apply-node sweeps eligible edges (B-then-A ordering; existing-id
  endpoints; refusal recorded, node still created); auto-attach (installed /
  absent / already-attached); run-node stream (progress events, journal rows
  with validation=False, failure report, guards); driver regression (auto
  run's connect stage applies zero leftovers on a linear plan).
- Frontend: dependency line rendering; Solve enablement matrix (edges
  applied × upstream approved); Run visibility on approved; provider
  createdEdges dispatch on apply; api runNode method.
- Full suites green.

## 8. Acceptance Criteria

- [x] Applying nodes in any order yields a progressively CONNECTED graph
      (eligible edges drawn at each apply), with refusals surfaced per edge.
- [x] Each row's Solve activates exactly when its dependencies are connected
      and upstream content is applied; the result is the reviewed Get
      Code-style content apply.
- [x] Each solved row's Run executes through the node and the outcome
      (outputs, schema, logs, errors) is journaled and readable by agents.
- [x] Every created node carries an auto-attached Node Builder when the
      template is installed.

## 9. Recommended Commit Breakdown

1. Backend: `_apply_one_plan_edge` extraction + progressive sweep +
   auto-attach in apply-node + tests.
2. Backend: run-node stream endpoint + tests.
3. Frontend: row dependencies + Solve/Run buttons + readiness rules +
   provider/api wiring + tests.
4. Docs: memo flip + BL-P5 amendment (+ 67-1 index note).

## 10. Engineering Quality Checklist

- One per-edge application policy (extracted, not duplicated).
- No new persisted state; readiness derived from existing ledgers.
- Server endpoints stay honest; only the UI gates.
- Auto-attach is best-effort — node creation never fails over it.
