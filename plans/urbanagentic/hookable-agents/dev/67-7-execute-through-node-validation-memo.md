# Implementation Memo 67-7: Execute-Through-Node Validation + Self-Correction (Simulation Mode: Validate)

Date: 2026-08-05
Status: implemented 2026-08-05 — COMMIT-d2053cf9 (runner promotion), COMMIT-6b0b0c71
(validation + validate-node stream), COMMIT-9b51b4ae (frontend). Verification: backend
1119 passed (8 skipped), frontend 722 passed; e2e shims verified by identity import.
BL-P5-20260805-11. Recorded deviations: (1) no dedicated cancel endpoint — client
disconnect clears the in-flight guard in a finally, and pause/cancel UX belongs to the
67-9 driver; (2) validation journal records carry durationMs 0 for now; (3) the
validate-node endpoint refuses eagerly when no node.content.generate specialist is
installed (the solve path already owns the install-proposal mint).

## 1. Problem Statement

Every Solve result must be validated by actually running the dataflow through the node
(67-0): generate → apply candidate → execute upstream-through-node → inspect
output/schema/errors → self-correct on failure → present to the user. No shortcut for
"trivial" code. Today nothing can do this server-side:

- Execution is browser-orchestrated only (`playNodesUpTo`, FlowProvider.tsx:1079); the
  backend executes one node per `/processPythonCode` call and no graph runner exists.
- BUT a working headless topological runner already lives in the test tree:
  `execute_workflow_programmatically` (tests/test_frontend/utils.py:530) over sandbox
  `/exec`, with `WorkflowSpec` (workflow_spec.py) providing Kahn ordering, merge `in_N`
  input assembly, pass-through semantics for browser-only node types, and the
  `output.path == ""` failure predicate. It raises on first failure and lives in tests.
- Failure data is machine-readable at the sandbox (full traceback in stderr) — 67-2's
  journal persists it.

## Expected Behavior (user-visible walkthrough)

1. Validating a node actually RUNS the dataflow: the upstream slice executes
   through the sandbox in dependency order, with progress narrated live
   ("executing upstream 2/5 — Clean Data…"). The saved spec is never touched:
   the candidate content runs as an overlay, and only Apply writes.
2. The content review card gains a validation block: **PASS** (green, with
   the output type/schema line) or **FAIL** (red, with the real traceback
   tail and how many correction rounds were attempted). Apply stays available
   either way — a failing result is labeled "Apply anyway", never hidden.
3. A failing generation self-corrects automatically: the child regenerates
   with the traceback and prior attempt in context, re-validates, and stops
   after 2 rounds with the full evidence trail. You see each round happen.
4. If an UPSTREAM node is the blocker, the verdict names THAT node instead of
   blaming the node under validation; infrastructure failures (sandbox down)
   are reported as infrastructure, never as "your code failed".
5. Every validation run leaves per-node runtime journal records (marked as
   validation), so the debug agent and explainer can quote what happened
   afterwards.
6. What no longer happens: "trivial" code skipping validation, discovering a
   broken node only when you press Run workflow, and validation silently
   mutating the spec.

## 2. Scope

In scope:
- Promote the runner: `app/execution/{workflow_spec.py, runner.py}` — lifted from the
  test utilities (tests then import from the app package; single source).
  `run_through_node(user, project_id, node_id, *, candidate: {nodeId, content} | None,
  seed?) -> {nodes: {id: {status, stderrTail, output, schema?}}, ok}`:
  ancestor-filtered (reverse BFS over the spec, mirroring playNodesUpTo), topological,
  sequential (bounded: ≤25 nodes per validation run, recorded constant), writing 67-2's
  journal per node. `candidate` substitutes content for the node under validation
  WITHOUT writing the spec (validation is pre-apply).
- Validation service: `app/agents/validation.py` —
  `validate_node(...) -> {verdict: pass|fail, evidence}`: executes through the node,
  compares outcome against the node goal + `expects` (67-5) + downstream input types
  (deterministic checks: executed OK, output non-empty, dataType compatible with each
  consumer's declared input types via ConnectionValidator-equivalent sets; the GOAL
  match is reported as evidence for the user/agent, not machine-judged).
- Self-correction loop: on fail, re-delegate `node.content.generate` with the failure
  evidence appended to the 67-6 context (`previousAttempt`, `stderrTail`), bounded
  `_VALIDATE_CORRECTION_ROUNDS = 2`; each round re-validates; exhaustion → `failed`
  with the full evidence trail presented.
- Endpoint + events: `POST …/attachments/<id>/validate-node {ref|nodeId}` streaming
  (dev/63 envelope): `validation_started`, `node_executed {nodeId, status}` per
  upstream node, `correction_round {n}`, `done {verdict, evidence, proposalId?}` —
  the validated candidate lands as the 67-6 content proposal (propose mode) carrying
  a `validation` block the review card renders.
- Frontend: validation evidence on the content review card (verdict badge, stderr tail
  collapsible, output schema line); nodeStates advance `solving → validated` /
  `failed`.
- JS nodes via sandbox `/execJs` (the runner gains the second endpoint the tests skip);
  browser-only types (vis/pool/merge) pass through per the existing runner semantics.

Out of scope: DEC-021 background execution (runs live inside the streamed request, like
dev/63 Solve); parallel validation runs (sequential by construction); replacing the
browser play paths (unchanged); machine-judging goal semantics (evidence, not verdict);
widget-bearing dataflows beyond `resolve_widget_placeholders` defaults.

## 3. Recommended Implementation Approach

Promotion is a move-plus-generalize, not a rewrite: keep the input-resolution,
seeding, and artifact retrieval logic byte-equivalent (the Playwright suite becomes the
consumer of the promoted module, proving parity). The runner accumulates per-node
results instead of raising; the candidate substitution is an in-memory spec overlay.
Validation composes: runner → deterministic checks → (on fail) bounded correction
rounds through the SAME delegate machinery (DEC-046 depth-1 children; each round is a
child run on the execution record's delegations list). The proposal is minted only
after the final round, pinned against the current node content — the user approves
VALIDATED content, with the evidence attached.

## 4. Data and State Handling

- Validation never mutates the spec: candidates are overlays; only the approved Apply
  writes (67-6 machinery). Journal writes ARE persisted (real executions happened) —
  marked `validation: true` so the UI can distinguish.
- Sandbox session scoping: validation runs use the caller's session identity
  (artifacts land in their scope like browser runs).
- Evidence bounds: stderr 4000 tail, schema ≤40 columns, one output sample line —
  everything user-visible and part-persisted.

## 5. UI and UX Requirements

- The content review card gains a validation block: PASS (green, schema line) /
  FAIL (red, error tail, "N correction rounds attempted"); Apply enabled either way
  (the user may accept a failing node deliberately — honesty over gatekeeping), with
  the failing state named on the button ("Apply anyway").
- The stream renders progress lines ("executing upstream 3/5…") in the existing
  transient activity channel.

## 6. Edge Cases

- Upstream node itself fails → validation reports THAT node as the blocker (evidence
  names it; the node under validation stays `solving`); the sequence (67-9) walks back.
- Cycles in the upstream slice → refused with the cycle named (Kahn remnant check).
- Validation exceeding the node budget (≤25) → refused honestly, suggesting manual run.
- Candidate identical to current content → still validated (no trivial-code shortcut).
- Sandbox down → `sandbox_unreachable` as evidence, node stays `solving`, never `failed`
  (infrastructure failure ≠ content failure).
- User cancels mid-validation → dev/63 cancellation pattern (stop dispatching, journal
  keeps completed upstream results).

## 7. Testing Strategy

- Runner promotion parity: the Playwright suite green importing from the app package.
- `run_through_node`: ancestor filter, candidate overlay (spec untouched), failure
  accumulation, JS node path, pass-through types — over a fake sandbox transport.
- Validation verdicts: ok / node-fail with traceback evidence / upstream-blocker /
  dtype-mismatch-with-consumer; correction rounds bounded and evidence-chained.
- Route/stream: event order, proposal carries validation block, cancellation.
- Frontend: card validation block render, Apply-anyway labeling.

## 8. Acceptance Criteria

- [x] Validating a node executes its upstream slice through the sandbox and yields a
      reviewable verdict with real runtime evidence — no spec mutation before Apply.
- [x] A failing generation self-corrects up to 2 rounds with the traceback in context,
      then fails loudly with the trail.
- [x] The Playwright dataflow tests pass against the promoted runner (single source).

## 9. Recommended Commit Breakdown

1. Backend: runner promotion + parity tests (tests re-pointed).
2. Backend: run_through_node + validation service + tests.
3. Backend: validate-node streaming endpoint + correction rounds + tests.
4. Frontend: card validation block + nodeStates wiring + tests.
5. Docs: memo flip + BL-P5 amendment.

## 10. Engineering Quality Checklist

- One runner for tests, validation, and (future) automation — no forked semantics.
- Deterministic checks decide; the model corrects; the user approves — three roles,
  never blurred.
- Infrastructure failures are never reported as content failures.
- Every execution leaves a journal record (67-2) — validation is observable after the
  fact.
