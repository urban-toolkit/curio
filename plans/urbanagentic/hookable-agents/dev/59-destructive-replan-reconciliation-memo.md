# Implementation Memo: Destructive Replan Reconciliation (Dataflow Builder — the dev/52 additive-only deferral)

Date: 2026-08-05
Status: implemented 2026-08-05 — the five planned commits landed as four: COMMIT-d0bd2d14
(§9 commit 1, grammar), COMMIT-12e5771d (§9 commits 2+3 combined — mint and apply share one
test class and the apply is untestable without the mint), COMMIT-97fa6c41 (§9 commit 4,
frontend), COMMIT-941e6698 (§9 commit 5, docs + ledgers + instruction). Verification: backend
`pytest tests --ignore=tests/test_frontend` → 1044 passed; frontend `npx jest` → 665 passed
(61 suites); injection-resistance + rule-9 suites included.
Feature slice: the recorded dev/52 deferral (dev/49 DR-2 remainder). Dataflow Builder plans gain
**reviewed removals and rewires** of existing graph elements — the session's reconciliation
contract ("preserve unchanged nodes and their IDs, preserve user-authored content by default,
record explicitly removed nodes as removal constraints, explain conflicts before applying") —
without surrendering any of the review discipline the additive slice established. The same
grammar change also lifts dev/52's *self-contained plan* restriction: new nodes may now wire to
existing ones.
Design sources: `dev/49` DR-2 + the consolidated session §"Preserve user edits" (the
requirement record — this memo cites, never restates), `dev/52`/`DEC-048` (plan grammar,
`baseGraphDigest`, builder session, correction rounds), `dev/54–56` (self-correcting plan
validation — destructive fields ride the same machinery), `dev/41`/`DEC-006` (digest-pinned,
apply-endpoint-only mutation — extended here to deletions), `dev/32`
(`attachments.prune_orphaned_attachments` — the existing orphan-cleanup the apply must run),
`dev/51/58` (canvas bridge; `FlowProvider.applyRemoveChanges` is the existing live-removal
path), rule 9, `REQ-REVIEW-001`.

**New decision required: DEC-049 — destructive plan operations are digest-pinned per victim and
reviewed by name.** dev/52's structural claim was "no code path can remove or rewrite a
pre-existing node"; this memo replaces it deliberately (at its recorded revisit point) with a
stronger discipline than plain review:

1. **Per-removal content digests.** The whole-graph shape digest is blind to content edits (by
   design — content edits must not invalidate additive plans). A removal DELETES content, so
   every node listed for removal is pinned by its content sha256 at mint; if the user edits a
   doomed node between mint and apply, the apply 409s + `stale` ("the node you were about to
   remove changed") — the dev/41 drift rule extended to deletions. User work can never die to a
   stale review.
2. **Removals are reviewed by name, not by count.** The review card lists every node to be
   removed (title/goal, type, and a content flag — "contains N chars of code") in a visually
   destructive section, plus the cascade (incident edges); the effect line states plainly that
   applying deletes their content.
3. **The model never removes uninvited.** The orchestration instruction (updated — v1's
   "removals are theirs to make on the canvas" posture is superseded per its recorded revisit)
   permits `removeNodes`/`removeEdges` only when the user's message asked for
   removal/replacement; unsolicited removals are an instruction violation the review catches by
   design (rule 2).

Register DEC-049 in the dev/03 table + 2.1 ledger with the docs commit.

## 1. Problem Statement

Replanning cannot reconcile: dev/52 plans are additive-only, so "replace the loader with an
API fetch" or "drop the two exploratory nodes and connect the cleaner straight to the chart"
requires the user to hand-delete on the canvas between proposals — exactly the manual bridging
the recording's Replan step eliminates (dev/49 DR-2). Concretely absent:

1. **No reviewed removal.** No grammar, mint, review surface, or apply path can delete a node
   or edge; `builderSession.nodeRuns` never forgets removed placeholders.
2. **No rewires.** Connection changes (the session: "propose connection changes separately")
   have no mechanism — an edge cannot be reviewed away or re-routed.
3. **Plans are islands.** Plan edges may only reference plan-local refs (dev/52 v1), so even an
   ADDITIVE extension cannot connect a new node to an existing one — the most common replan
   ("add a chart fed by my existing cleaner") silently fails validation today.

**Expected behavior.** "Replace the CSV loader with the API fetch node" yields ONE reviewed
revision proposal: the new node, its wiring to existing nodes, and the named removal of the old
loader (content flagged) — applied atomically to the saved spec and the live canvas, with
user-edited victims protected by per-removal digests, attachments on removed nodes pruned by
the existing dev/32 helper, and unchanged nodes untouched (ids, positions, content — the
session's preservation contract holds structurally because the apply only ever touches listed
elements).

## 2. Scope

**Backend (`utk_curio/backend/app/agents/`)**
- `content.py` (grammar, riding the dev/54 verbose parser + correction rounds):
  - `dataflowPlan` gains `removeNodes?: ["<existing node id>"]` and
    `removeEdges?: ["<existing edge id>"]` — backstops 200/600, default empty (**additive
    plans byte-identical**, regression-pinned).
  - Edge endpoints widen: `from`/`to` ∈ plan refs ∪ existing node ids (never a removed id) —
    lifting the self-contained restriction. Existence is a MINT check (the grammar cannot see
    the spec); the grammar checks shape + ref/removal consistency only.
- `services.py`:
  - Mint: validate `removeNodes`/`removeEdges` ids and existing-id endpoints against the saved
    spec (unknown → the usual corrective-round errors); compute the cascade (incident edges of
    removed nodes); pins gain `removeContentSha256: {nodeId: sha256(content-at-mint)}`
    (DEC-049.1); the proposal part carries a `removals` display block (title/goal, type,
    content-size flag, cascade count) for the card (DEC-049.2).
  - Apply: re-check shape digest (unchanged rule) AND every per-removal content digest (drift →
    409 + `stale` naming the node); then atomically: remove listed edges, remove listed nodes +
    cascade, run `attachments.prune_orphaned_attachments(spec)` (dev/32 — agent attachments on
    removed nodes die with them, exactly as canvas deletion), drop removed ids from
    `builderSession.nodeRuns`, insert new nodes/edges (dev/52 semantics; edges may target
    existing ids), one spec write. `appliedGraph` gains `removedNodeIds`/`removedEdgeIds`.
- Instruction (`orchestration_instruction.txt`): the replan procedure — read the live graph
  first (`dataflow.read`); reference existing nodes by their REAL ids; wire new nodes to
  existing ones freely; use `removeNodes`/`removeEdges` ONLY when the user asked for
  removal/replacement, and restate every removal in prose so the user hears it twice.

**Frontend (`utk_curio/frontend/urban-workflows/src/`)**
- Bridge: `graph-created` payload gains removals — applied through the EXISTING removal path
  (`FlowProvider.applyRemoveChanges` for nodes, `onEdgesChange` remove changes for edges;
  `data: {}` parity per dev/58) BEFORE the inserts, then the fit; idempotent per plan id.
- `AgentReviewCard` (`dataflow.plan.write`): a **Removes** section above the additions list —
  destructive styling, one row per victim (name · type · "contains N chars" when non-empty),
  cascade count; the effect line becomes bidirectional ("Applying adds X nodes and removes Y —
  removal deletes their content and cannot be undone."). Additive plans render exactly as
  today (regression).
- `AgentBuilderStrip`: unchanged (the phase machine already covers revision proposals).

**Explicitly out of scope (each with its revisit point)**
- Modifying an EXISTING node's content/title from a plan — single-node content stays with
  `node.content.write`/Solve (single-responsibility; a "modify" op is its own memo if demand
  appears).
- Automatic semantic diffing of the user's canvas against a regenerated plan (the model
  reconciles conversationally through `dataflow.read` + grounded context; a deterministic
  diff/merge engine remains future work — dev/49 DR-2's outer edge).
- Undo/restore of applied removals (version provenance already snapshots the graph;
  surfacing restore is the provenance track's).
- Streamed solve progress / cancellation (`DEC-021`), unchanged by this memo.

## 3. Recommended Implementation Approach

### 3.1 Grammar (dev/54 discipline: every failure is a precise, correctable error)

`removeNodes`/`removeEdges` entries: non-empty bounded strings; duplicates refused; an edge
endpoint naming a removed node refused ("edges[2].to references n7, which this plan removes");
a plan that ONLY removes (no nodes) is valid — `nodes` may be empty when removals exist (the
one grammar relaxation; a fully empty plan stays invalid). All errors flow through
`_parse_dataflow_plan_verbose` → correction rounds → the loud cap card, and the fence-agnostic
scanner (dev/56) picks up destructive plans in any fence shape automatically.

### 3.2 Mint (the spec-aware half)

Resolution against the saved spec: unknown removal ids, unknown existing-id endpoints, and
endpoints pointing at removed nodes are corrective-round errors. The cascade is computed at
mint (display) and recomputed at apply (truth). Pins:
`{baseGraphDigest, removeContentSha256: {…}}`. The part's `removals` display block feeds the
card; `plan.edges` display copy now distinguishes plan-ref endpoints from existing-id endpoints
(the card shows "→ existing: Cleaner").

### 3.3 Apply (atomic, revision-safe both ways)

Order inside one spec write: shape-digest check → per-removal content-digest checks →
edge removals (listed + cascade) → node removals → `prune_orphaned_attachments` →
node inserts → edge inserts (endpoints resolved through the ref map ∪ existing ids) →
`builderSession` update (removed ids dropped from `nodeRuns`; phase per dev/52 rules) →
result-card turn ("Applied: plan added X nodes, removed Y, Z connections"). The response's
`appliedGraph` carries additions AND removals for the bridge.

### 3.4 Bridge

Removals first (the live graph must drop victims before inserts wire to survivors), through the
canvas's own removal machinery so selection, provenance, and dependent cleanups behave exactly
like a manual delete; then dev/52's insert + fit. A removal of a node not present live (already
user-deleted) is a no-op — the digest logic upstream guarantees the SPEC was consistent.

## 4. Data and State Handling

- Truths unchanged (spec / attachment record / registries); no new stores. The per-removal
  digests live only in proposal pins (transient, like every pin).
- Race safety: shape digest (structure) + per-victim content digests (work protection) +
  the existing pending-supersede rules; the bridge idempotent per plan id.
- `nodeRuns` hygiene: removed ids leave the session; phase recomputes (`ready` if nothing
  pending/failed remains).

## 5. UI and UX Requirements

- The Removes section is impossible to miss: destructive color, per-victim rows with content
  flags, cascade count, and the bidirectional effect line. No confirmation dialogs beyond the
  existing Apply (one explicit review — but an *informed* one, DEC-049.2).
- Additive-only plans: pixel-identical card and behavior (regression).
- Accessibility: the removals list is a labeled group; content flags are text, not color-only.

## 6. Edge Cases

- Victim edited between mint and apply → 409 + `stale` naming the node (DEC-049.1).
- Victim deleted by the user between mint and apply → shape digest 409 (existing rule).
- Removal id unknown / endpoint on a removed node / duplicate ids → corrective rounds.
- Remove-only plans (cleanup requests) → valid, reviewed, applied; phase recomputes.
- Removed node carried attachments → pruned via dev/32 (their sessions die with them, as on
  manual delete); removed node in `nodeRuns` → dropped.
- Solve in flight when a revision is applied → the solve batch's per-node digest guards already
  skip missing nodes (`skipped`); no interlock needed.
- Cascade edges also listed in `removeEdges` → deduplicated silently.
- New edge wiring an existing node that another pending proposal would remove → impossible
  (one pending proposal per attachment; supersede rules unchanged).
- Old clients: unknown payload fields degrade — the card shows the additive portion + generic
  shell (T2 tolerance); the apply is server-side regardless.

## 7. Testing Strategy

Backend: grammar (bounds, duplicates, removed-endpoint refusal, remove-only validity, additive
byte-parity re-pin); mint (unknown ids → corrective errors; cascade; pins carry per-victim
digests; removals display block); apply (atomic add+remove; victim content-drift 409 + `stale`
by name; user-deleted-victim shape 409; cascade removal; attachment pruning on removed nodes —
the dev/32 helper invoked; `nodeRuns` cleanup; existing-id edge wiring lands; remove-only
plans); correction rounds + fence-agnostic recognition cover destructive fields (extend one
test each); injection-resistance re-run (no text path removes anything); rule-9 share suite.
Frontend: card Removes section (rows, content flags, effect line; additive regression); bridge
removals-before-inserts through `applyRemoveChanges`/edge remove changes, idempotence,
already-absent no-op; full suites green.

## 8. Acceptance Criteria

- [x] A replan can add, wire-to-existing, and remove in ONE reviewed proposal; **only** the
      authenticated apply mutates, atomically, saved spec + live canvas together.
- [x] Every removal is digest-pinned per victim: editing a doomed node after mint makes the
      apply 409 + `stale` naming it — user work cannot die to a stale review (DEC-049.1).
- [x] The review card names every victim with a content flag and the cascade; the effect line
      states the deletion plainly (DEC-049.2); additive plans render exactly as today.
- [x] Attachments on removed nodes are pruned exactly as manual deletion (dev/32);
      `builderSession` forgets removed nodes; Solve guards tolerate mid-flight removals.
- [x] Plan edges may reference existing nodes (the dev/52 island restriction lifted) — additive
      extensions connect to the current graph.
- [x] Correction rounds, fence-agnostic recognition, and the toolRequest form all carry the
      destructive fields; failures stay loud.
- [x] DEC-049 recorded (dev/03 + 2.1); the instruction supersedes the v1 "removals are theirs
      to make" posture at its recorded revisit point.
- [x] Injection-resistance and rule-9 suites pass.

## 9. Recommended Commit Breakdown

1. `Plan grammar: removeNodes/removeEdges + existing-id edge endpoints, verbose errors, additive byte-parity, with tests`
2. `Revision mint: spec-aware removal validation, per-victim content digests, removals display block, with tests (dev/59)`
3. `Revision apply: atomic add+remove, victim-drift 409, attachment pruning, nodeRuns hygiene, with tests (DEC-049)`
4. `Frontend: bridge removals-before-inserts + review-card Removes section, with tests`
5. `Docs + ledgers: dev/59 implemented, DEC-049 in dev/03 + 2.1, BL-P5 entry, docs/AGENTS.md, instruction update`

## 10. Engineering Quality Checklist

- [ ] Mutation authority unchanged: mint-only loop, apply-endpoint-only execution; removals add
      pins, never shortcuts.
- [ ] The preservation contract is structural: the apply touches ONLY listed elements — ids,
      positions, and content of unlisted nodes cannot change by construction.
- [ ] One grammar, one proposal kind, one card, one apply — destructive fields extend dev/52's
      surfaces instead of forking parallel ones.
- [ ] Reuse over invention: `prune_orphaned_attachments`, `applyRemoveChanges`, the dev/54–56
      correction machinery, the dev/58 edge shape.
- [ ] Additive plans, non-plan agents, and old clients byte-/behavior-identical
      (regressions named).
- [ ] Deviations and deferrals each name a revisit point (§2).
