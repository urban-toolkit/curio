# Implementation Memo: Dataflow Builder — the Third P5 Composite (Plan → Revise → Solve → Run)

Date: 2026-08-04
Status: implemented 2026-08-05 — COMMIT-d4afe271 (roster + capability-first resolution),
COMMIT-6156a1b5 (dataflowPlan part + mint), COMMIT-3e48fb58 (plan apply + builder session),
COMMIT-67a3bef3 (Solve, DEC-048), COMMIT-5471a5bd (frontend). Verification: backend `pytest
tests --ignore=tests/test_frontend` → 998 passed; frontend `npx jest` → 651 passed (60 suites);
injection-resistance + rule-9 share suites included. Implementation note: the capability-first
widening also gained a visible-roster missing-specialist fallback (dev/03:366's "a definition
already visible to that actor" verbatim), superseding dev/48's delegatesTo-scoped proposal
targeting — regression tests updated accordingly.
Feature slice: the final Phase-5 composite. `agent.dataflow-builder` joins the roster with the
dev/15 §3.4 manifest surface and delivers the recording's guided loop as consolidated in dev/49:
**DR-1** (typed graph-level plan proposals with one-review apply), **DR-2** (the persisted
orchestration session — phases, revision digests, reload recovery), **DR-3** (planning templates),
**DR-4** (the bounded Solve batch over depth-1 children, with the capability-first resolution
widening), and **DR-5** (the phase-aware builder panel). It is also the `DEC-046` LangChain
revisit point — resolved below as **DEC-048**.
Design sources: `dev/15` §3.4 (manifest: `dataflow.orchestrate`, the ten-agent `delegatesTo`
graph, orchestration invariants, `maxParallelChildren: 3`), `dev/49` (DR-1…DR-5 requirement
record + the LangChain placement map — this memo must not restate the session, only cite it),
`DEC-046`/`dev/48` (delegation seam, depth-1 structural guarantees, missing-specialist
`project.install`), `DEC-047`/`dev/50` (user-mediated handoffs; `requires` gating),
`dev/41`/`DEC-045` (proposal/apply machinery), `dev/51` (apply→canvas bridge + `applyNodeContent`
+ viewport handling), `DEC-044` (ledger absorbs per-child reservations), `dev/03:366`
(capability-first delegation resolution — the recorded dev/48 narrowing to widen HERE),
`docs/02:64-83` (canvas hook), `REQ-ORCH-001`, `REQ-REVIEW-001`/`DEC-006` (structural review),
rule 9 (agent-private state never enters shares — the builder session rides the attachment
record, which is already share-stripped).

**New decision required: DEC-048 — the orchestration runtime is direct code; `DEC-007` is
retired.** The deferred question (LangChain as the runtime, deferred at DEC-045, narrowed at
DEC-046 to exactly this memo) is now answerable with three composites of usage data:

1. **The phase structure eliminates the graph-executor workload.** Plan → Revise → Solve → Run is
   *user-paced*: every phase boundary is an explicit human action (send, apply, Solve, Run), so
   orchestration decomposes into short, bounded, synchronous segments — one provider call
   producing a typed plan; one authenticated apply; one bounded batch of depth-1 children. There
   is no long-lived autonomous graph execution for LangGraph to host; its checkpointing/resume
   value duplicates state the app already owns (the persisted session, the ledger, the
   transcript), and its executor would sit dangerously close to mutation authority that
   `DEC-006` keeps structural.
2. **The Solve fan-out is a worker pool, not a graph.** N independent, already-atomic child runs
   (each its own reserve→settle, framed result, `parentExecutionId`) coordinated by a bounded
   `ThreadPoolExecutor(maxParallelChildren)` with per-child error isolation — ~50 lines of
   direct code against seams that already exist.
3. **Where LangChain would still fit** (recorded so the door stays marked, per dev/49 §3): if
   background, long-running, interruptible orchestration ever lands (`DEC-021`), the
   `delegation.py` module boundary remains the swap seam. Until then `DEC-007` is retired —
   the runtime architecture of record is the provider port + the delegation seam.
   `DEC-039`'s provider-defaults seeding is unaffected (it configures the port, not an adapter).

Also folded into DEC-048: **the Solve authorization model** (dev/49 conflict-2 resolution made
concrete): ONE explicit, authenticated Solve action authorizes the batch — the endpoint is the
review, scoped to plan-created placeholder nodes and digest-guarded per node, so user-authored
content can never be overwritten and the model loop still cannot mutate anything. Register
DEC-048 in the dev/03 table + 2.1 ledger with the docs commit.

## 1. Problem Statement

The recording's core experience — state a goal, review a proposed connected graph of placeholder
nodes, edit it, fill all unresolved nodes, run — has no mechanism. Concretely (dev/49 DR items,
each currently absent):

1. **No graph-level proposal.** The runtime mutates one node at a time (`node.create`). A plan
   ("load → clean → join → visualize") cannot be proposed, reviewed, or applied as a connected
   graph; dev/41 deferred graph-shape apply semantics to exactly this consumer, and dev/48
   deferred edges to "a consumer that defines reviewed edge semantics" — this memo is both.
2. **No orchestration state.** Nothing records that a plan is awaiting review, was applied at
   revision X, or is half-solved; a reload loses everything but the transcript (DR-2).
3. **No planning templates** (DR-3) and **no phase-aware surface** (DR-5): the generic chat
   cannot show plan/solve progress, per-node status, or a Run gate.
4. **No batch solve.** Filling N placeholder nodes means N manual chat round-trips with N
   review clicks; the recording shows one Solve filling all unresolved nodes with progress
   (DR-4). Delegation exists (dev/48) but only one child per loop round, model-initiated.
5. **Resolution is narrower than designed.** dev/48 resolves delegates within `delegatesTo`
   only; `dev/03:366` specifies capability-first discovery over ALL current-project templates
   with `delegatesTo` as preference — recorded in dev/49 as the widening owed here.

**Expected behavior.** Dataflow Builder installs/attaches to the canvas like any built-in. A
goal (optionally seeded by a planning template) yields a reviewable **plan proposal** — a
connected graph of typed placeholder nodes ("code pending") with titles and intents. Apply
inserts the whole graph into the saved spec *and* the live canvas atomically (never clearing
existing work — additive by construction). The builder panel shows the phase; **Solve** (one
authenticated click) fills unresolved plan nodes via bounded-concurrency child runs with
per-node progress and per-node retry; user-edited nodes are never overwritten. **Run workflow**
triggers the existing `playAllNodes`. Reload restores the phase and progress.

## 2. Scope

**Backend (`utk_curio/backend/app/agents/`)**
- `builtin.py`: roster entry `agent.dataflow-builder` (net-new `orchestration_instruction.txt`;
  dev/15 §3.3), category `canvas`, tools `dataflow.read` + `dataflow.plan.write`,
  `delegatesTo` = the nine dev/15 agents that exist in the runtime (deviation:
  `agent.package-recommendation` deferred exactly as in dev/48).
- `delegation.py`: **capability-first resolution** (the dev/49 widening): after the
  `delegatesTo` preference walk, fall back to ANY current-project installed template declaring
  the capability, deterministic tie-break (delegatesTo order, then coord sort); still never
  another project, still depth-1.
- `content.py`: `dataflowPlan` **model-emitted part** — the DR-1 typed plan:
  `{goal≤300, templateId?≤64, nodes: [{ref, nodeType, title≤120, intent≤300, content?≤bound}],
  edges: [{from, to}]}` — `ref` = plan-local handles (`n1`…), edge endpoints must reference
  plan refs (additive graphs are self-contained in v1); one per reply; malformed → fail-open.
  **Bounds are abuse backstops, never product ceilings**: ≤ 200 nodes and ≤ 600 edges per plan
  proposal — far above anything a single review can meaningfully cover, present only so a
  hostile tail can't allocate unbounded structures. The 4,096-byte whole-tail cap
  (`TAIL_MAX_BYTES`, sized in dev/39 for prompts/tool requests) does NOT bound plans: a tail
  whose payload carries `dataflowPlan` gets its own budget (`PLAN_TAIL_MAX_BYTES = 256 KiB`) in
  `parse_parts`, all other tails keeping the existing cap byte-identically. The *practical*
  governors of plan size are elsewhere and already policy-controlled: the provider's
  `maxOutputTokens` bounds what one reply can carry (a truncated tail fails open to text, and
  the instruction tells the model to split very large designs into successive additive plans —
  additive-by-construction composes, so big dataflows chain across proposals with no ceiling),
  and per-child quota admission governs Solve cost regardless of plan size. Exclusive with
  tool/delegate requests? No — the plan rides the tail of a normal reply; the runtime (not the
  model) turns it into the proposal, exactly like `proposal` parts: **model-emitted
  `dataflowPlan` + runtime-minted `dataflow.plan.write` proposal in one step** (the loop mints
  when the part validates — no second round needed).
- `tools.py`: `dataflow.plan.write` (mutate) registry entry — the contract the proposal/apply
  dispatch keys on; the model never requests it directly (the `dataflowPlan` part is the
  request); grant gates whether plan parts mint proposals for this agent.
- `services.py`: plan mint (validates every `nodeType` via `available_templates` — reuse-first
  exactly as dev/48; edge endpoint/duplicate checks; pins `{baseGraphDigest}` = sha256 of the
  saved dataflow's node-id+edge-id sets — whole-graph revision safety); plan apply (atomic:
  server-minted ids for all nodes, placeholder semantics — `content` empty unless the plan
  carried it, `goal` = intent, laid out left-to-right by topological depth right of the
  existing extent; edges inserted with the id map; digest drift → 409 + `stale`; response
  carries `appliedGraph {nodes, edges}` for the bridge); **builder session** on the attachment
  record (`builderSession: {phase, planProposalId?, appliedPlanId?, nodeRuns: {nodeId:
  "pending"|"solving"|"solved"|"failed"|"skipped"}}` — server-owned transitions, share-stripped
  with the record by rule 9, preserved by `preserve_agent_state`); **Solve endpoint**
  `POST /projects/<pid>/attachments/<aid>/solve {nodeIds?}` — authenticated batch (DEC-048):
  resolves `node.content.generate` capability-first, runs children through
  `delegation.run_delegate` under a `ThreadPoolExecutor(3)` (`maxParallelChildren`, a runtime
  constant until policy demands it), writes each result through a per-node digest guard (only a
  node whose content still equals its plan-applied state is written — user edits are skipped as
  `"skipped"`, never overwritten), records children on a solve execution record, returns
  per-node outcomes + `appliedContents` for the bridge. Solve consumes no quota itself; each
  child reserves under its own policy (deviation from dev/15's aggregate reservation: the
  DEC-044 ledger derives aggregates from entries, so shared-reservation bookkeeping adds
  nothing — recorded).
- SSE: none new in v1 — Solve is a synchronous batch endpoint returning outcomes; progressive
  streaming joins later with `DEC-021` (recorded deviation from the session's live progress;
  the panel shows per-node results as the response lands).

**Frontend (`utk_curio/frontend/urban-workflows/src/`)**
- `api/agentsApi.ts`: `AgentDataflowPlanPart`, plan-proposal kind, `solveAttachment`,
  `appliedGraph`/`appliedContents` payloads.
- Bridge (`agentCanvasEvents` + `useAgentCanvasMutations`): new `graph-created` mutation — bulk
  node insert through the same `createCodeNode` factory + edge insertion via the FlowProvider
  connect path, then `fitViewWithMenuOffset` framing the new nodes (a whole plan deserves a fit,
  not a center); `appliedContents` reuses `applyNodeContent` per node. Idempotent per applied
  plan id.
- `AgentReviewCard`: `dataflow.plan.write` kind — summary first (node/edge counts, template
  name), then the titled node list with types + intents in the card's existing scrollable
  preview region (plans can be large — the count line is the at-a-glance truth, the list the
  detail), and the effect line ("Applying adds these N connected nodes to the canvas —
  existing work is untouched.").
- **Builder panel strip** (DR-5, inside the existing chat drawer for dataflow-builder
  attachments — no new drawer): phase indicator (Plan · Review · Solve · Ready), the DR-3
  template picker (six static templates seeding the goal prompt via the prefill rule), a
  **Solve** button (enabled in `applied` phase; per-node status lines from `nodeRuns`; failed
  nodes get a Retry that re-solves the subset), and **Run workflow** wiring to the existing
  `FlowProvider.playAllNodes` (enabled when no plan node is `pending`/`failed`).
- Templates (DR-3): a static frontend constant (six entries from the session: Load and Clean;
  Geospatial Join and Visualize; Compute Statistics and Chart; Time-Series Exploration; Build a
  Dashboard; From Scratch) — each a labeled goal-prompt seed. Server-owned/governed templates
  are a later slice (recorded deviation).

**Explicitly out of scope (each with its revisit point)**
- **Destructive replan reconciliation** (semantic diff applying removals/rewires): v1 plans are
  **additive-only** — "planning must not clear the canvas" holds structurally, and Revise =
  a new additive plan proposal superseding the pending one; a reconciliation engine that
  proposes removals is its own memo once additive plans prove out (dev/49 DR-2 remainder).
- Background execution, cancellation mid-solve, streamed solve progress (`DEC-021`).
  type-checker at interaction time; the spec never validated edge types server-side —
  parity kept, noted for the validation-agent track, OQ-011).
- `agent.package-recommendation` in `delegatesTo` (dev/16 runtime slice, as in dev/48).
- Aggregate parent/child reservations (see above — DEC-044 makes them derivable).
- LangChain/LangGraph adoption (**closed** by DEC-048; seam preserved in `delegation.py`).
- Cross-composite orchestration (Dataset Finder lanes inside plans) — the DEC-047 handoffs
  remain user-mediated; batch composition is a later slice.

## 3. Recommended Implementation Approach

### 3.1 Roster entry

```python
BuiltinAgentSpec(
    "agent.dataflow-builder", "Dataflow Builder", "canvas",
    "Plan a connected dataflow from a goal as one reviewable proposal; solve "
    "unresolved nodes through delegated specialists. Never mutates without review.",
    "orchestration_instruction.txt",
    ("dataflow.orchestrate",), ("orchestration",),
    reads=("mission", "graphContext", "installedTemplates"),
    tools=("dataflow.read", "dataflow.plan.write"),
    delegates_to=("agent.dataset-finder", "agent.node-builder",
                  "agent.connection-builder", "agent.dataflow-task-planner",
                  "agent.execution-subtask-planner", "agent.task-refresh-agent",
                  "agent.workflow-suggester", "agent.plan-coherence-validator",
                  "agent.dataflow-explainer"),
    review_policy="review-before-apply",
)
```

The net-new instruction teaches: read the live graph (context + `dataflow.read`) before
planning; propose ONE `dataflowPlan` tail — typed placeholder nodes chosen ONLY from the
Available node templates list (the dev/48 grant-time roster rides `dataflow.plan.write` grants
too), connected edges, honest intents; plans are additive — never propose removing or replacing
the user's existing nodes, and say so when asked; content may be left pending for Solve; you may
delegate planning support (`workflow.plan.create`, `workflow.coherence.validate`) before
proposing; never claim the plan exists before the user applies it.

### 3.2 The plan proposal (DR-1)

Mint (runtime, on a valid `dataflowPlan` part when `dataflow.plan.write` is granted): validate
every `nodeType` against `available_templates` (authorable for nodes carrying content; any
registered template for pending placeholders), edge refs resolve within the plan, no duplicate
edges, bounds. Pins `{baseGraphDigest}` — apply re-computes it from the saved spec; any
node/edge added or removed meanwhile → 409 + `stale` (the whole-graph analogue of dev/41's
digest). Apply (authenticated endpoint only, as ever): one spec write inserting all nodes
(server-minted ids; plan `ref`→id map; topological columns right of the existing extent;
`goal` = intent; pending content = `""`) and all edges; the builder session moves to
`applied` with `nodeRuns` seeded `pending` for content-less nodes; the response's
`appliedGraph` feeds the bridge (bulk insert + edges + fit). Everything additive: the apply
never touches an existing node or edge.

### 3.3 Solve (DR-4, DEC-048)

`POST …/solve {nodeIds?}` — the explicit user action IS the review for this bounded batch:
- Scope: plan-created nodes in `nodeRuns` with status `pending`/`failed` (or the given subset
  for Retry). Per-node digest guard: the node's current content must still equal its
  plan-applied content (normally `""`); a user-edited node → `skipped`, listed as preserved.
- Each node: capability-first resolution of `node.content.generate` → a depth-1 child run
  (`delegation.run_delegate`; inputs = the node's type/title/intent + the plan goal + bounded
  graph context), all dev/48 guarantees intact (own ledger pair under the child's policy,
  `parentExecutionId` = the solve execution id, framed results, failure isolation).
- Concurrency: `ThreadPoolExecutor(max_workers=3)`; the ledger is flock+thread safe (DEC-044
  tests); provider calls are independent; results written under the project's spec write lock
  in one batch at the end (one spec write, no interleaving).
- Outcome: `nodeRuns` updated per node (`solved`/`failed`/`skipped`), a solve execution record
  on the transcript turn ("Solved 3 of 4 nodes…" result card + `delegations`), response carries
  `appliedContents: [{nodeId, content}]` for the bridge. Retry = the same endpoint with the
  failed subset — a new linked batch, no side-effect replay.

### 3.4 Phases (DR-2)

`builderSession.phase ∈ {idle, plan_review, applied, solving, ready}` — server-owned:
mint → `plan_review`; apply → `applied`; solve start/end → `solving` → (`ready` when no
`pending`/`failed` remain, else back to `applied`); dismiss/supersede → back to `idle` when no
applied plan exists. The record rides the attachment (rule-9 stripped from shares, preserved
across saves by `preserve_agent_state`, deleted with the attachment); reload restores phase and
per-node status from it — the transcript stays the human history, the session the machine state.

## 4. Data and State Handling

- **Truths**: saved spec (graph), attachment record (builder session + proposals mirror),
  transcript turns (history + result cards), packages registry (creatable node types), agents
  lockfile (delegation resolution). No new stores.
- **Race safety**: plan apply is digest-pinned against graph shape; Solve writes are per-node
  digest-guarded and batched under the spec lock; the bridge is idempotent per plan id; two
  tabs conflict through the existing revision/409 surfaces.
- **Loading/error/success**: pending proposal renders the plan review card; Solve button
  disables while a batch is in flight; child failures surface per node with Retry; a failed
  node never blocks siblings (executor isolation); the panel derives everything from
  `builderSession` + the attachment card (no duplicated client state).

## 5. UI and UX Requirements

- Builder strip only for `agent.dataflow-builder` attachments; every other agent's chat is
  pixel-identical (regression). Phase chips labeled, not color-only; template picker
  keyboard-operable; per-node status lines aria-live polite; Solve/Run buttons disabled states
  explain why (pending review / unsolved nodes). Run = the existing `playAllNodes`, no new
  execution surface. Review card lists every planned node (title · type · intent) so the user
  reviews the actual graph, not a count.

## 6. Edge Cases

- Plan referencing an unavailable template → mint refusal naming it (reuse-first, as dev/48);
  template uninstalled before apply → 409 + `stale`.
- Graph edited between mint and apply (node added/removed) → digest 409 + `stale`; content-only
  edits don't change the digest basis (id sets) — deliberate: content edits don't invalidate an
  additive plan.
- Empty canvas, empty goal, `From Scratch` template → plain plan flows; plan with content on
  every node → `nodeRuns` empty → apply lands directly in `ready`.
- Solve with node-content-builder not installed → capability-first fallback (any installed
  template declaring `node.content.generate`); none → per-node `failed` with the reviewed
  `project.install` proposal minted once (not per node).
- Child 429/provider failure → that node `failed`, siblings complete; Retry re-runs the subset.
- Solve clicked twice → the in-flight batch guard (session `solving` phase) 409s the second.
- Reload mid-solve → phase restores; an interrupted batch leaves nodes `pending`/`failed`
  (children settle their own ledger pairs); Retry is safe.
- Node deleted by the user after apply → its `nodeRuns` entry resolves `skipped` (digest guard
  finds no node); Run gating ignores deleted nodes.
- Old client: unknown part/proposal kinds degrade to the generic shell; the solve endpoint 404s
  on old servers — the panel hides Solve when the attachment card lacks `builderSession`.

## 7. Testing Strategy

Backend: roster/manifest + byte-parity re-pin (sixteen agents); capability-first resolution
(preference order still wins; fallback finds a non-delegatesTo template; deterministic
tie-break; never cross-project); `dataflowPlan` grammar (bounds, refs, fail-open, one-per-reply);
plan mint (template validation, edge checks, digest pin, grant gating) → `review_required`;
plan apply (atomic multi-insert, id map, placeholder semantics, additive — existing graph
untouched, drift 409+stale, `appliedGraph`); builder session transitions incl. reload
restoration and rule-9 share-strip re-run; plan-tail budget (a large valid plan well over
4,096 bytes parses; a non-plan tail over the classic cap still fails; the 200/600 backstop
refuses beyond, and a large plan applies + bulk-inserts end-to-end — sized-for-real-graphs
regression); Solve (batch outcomes, per-node digest guard skips
user edits, concurrency-safe ledger pairs with `parentExecutionId`, missing-specialist single
proposal, failure isolation, double-solve 409, retry subset, quota-free endpoint itself);
injection resistance re-run (no text path applies a plan or solves).
Frontend: bridge `graph-created` (bulk insert + edges + fit + idempotence); plan review card
(node list, effect line); builder strip (phase rendering, template seeding via the prefill rule,
Solve/Retry/Run wiring incl. `playAllNodes`, disabled-state reasons, aria-live); other agents'
chat unchanged (regression); full suites green.

## 8. Acceptance Criteria

- [x] `agent.dataflow-builder` browsable/importable/installable/attachable (canvas) and runnable;
      fifteen prior manifests byte-identical.
- [x] A goal yields ONE reviewable plan proposal (typed, connected, registry-validated,
      additive); **only** the authenticated apply inserts it — saved spec + live canvas
      atomically, existing work untouched; drift → 409 + `stale`.
- [x] One authenticated Solve fills pending plan nodes via bounded-concurrency depth-1 children
      (own ledger pairs, `parentExecutionId`); user-edited nodes are skipped, never overwritten;
      failures isolate per node with subset Retry; nothing is model-triggerable.
- [x] Capability-first resolution implemented (dev/03:366) with `delegatesTo` as preference;
      depth-1 guarantees unchanged.
- [x] The builder panel shows phases/templates/per-node progress/Run (via `playAllNodes`);
      reload restores phase + progress; every other agent's chat is unchanged.
- [x] DEC-048 recorded (dev/03 + 2.1): direct-code orchestration, DEC-007 retired, the Solve
      authorization model; deviations recorded in §2 with revisit points.
- [x] Injection-resistance and rule-9 suites pass.

## 9. Recommended Commit Breakdown

1. `Roster: agent.dataflow-builder + capability-first delegation resolution, with byte-parity + resolution tests`
2. `dataflowPlan part + dataflow.plan.write: grammar, registry-validated mint, baseGraphDigest pins, with tests (dev/52)`
3. `Plan apply: atomic graph insertion + builder session phases on the attachment record, with tests`
4. `Solve: authenticated bounded batch over depth-1 children, per-node digest guards, retry, with tests (DEC-048)`
5. `Frontend: graph-created bridge + plan review card + builder panel strip (templates, phases, Solve/Run), with tests`
6. `Docs + ledgers: dev/52 implemented, DEC-048 in dev/03 + 2.1, BL-P5 entry, docs/AGENTS.md`

## 10. Engineering Quality Checklist

- [ ] Mutation authority stays structural: the loop mints, only authenticated endpoints (apply,
      solve) execute; no flag flips this.
- [ ] Additive-by-construction planning: no code path in this memo can remove or rewrite a
      pre-existing node or edge.
- [ ] Depth-1 and injection-resistance guarantees untouched; the executor coordinates children,
      it never parses them.
- [ ] One source of truth per fact (spec / attachment record / transcript / registries); the
      panel derives, never duplicates.
- [ ] Reuse over invention: `available_templates`, `delegation.run_delegate`,
      `applyNodeContent`, `createCodeNode`, `playAllNodes`, `fitViewWithMenuOffset` — no
      parallel machinery.
- [ ] DEC-048's LangChain disposition is recorded with its re-open condition (`DEC-021`); the
      seam stays one module boundary.
- [ ] Deviations from dev/15 and the session each name a revisit point (§2).
