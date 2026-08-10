# Implementation Memo 67-2: Full Dataflow Awareness + Per-Node Runtime Journal (Foundation A)

Date: 2026-08-05
Status: implemented 2026-08-05 — COMMIT-3e0add6d (journal + seam), COMMIT-cf538d60
(tools + grants), COMMIT-49407f43 (frontend producers). Verification: backend 1075
passed (8 skipped), frontend 702 passed, tsc clean. Ledger: DEC-052 (dev/03 + 2.1),
BL-P5-20260805-07. Deviations: none of substance — outputSchema is recorded as absent
until the sandbox reports column metadata (follow-up), and the journal's staleness
signal surfaces through node.runtime.read's `contentChangedSinceRun` (computed at read
time against the normalized digest, exactly as §3 sketched).

## 1. Problem Statement

Agents building dataflows are blind twice over:

- **No grounded context for the composites.** `composeAgentRunContext`
  (frontend `agents/attach/agentRunContext.ts:122`) maps `attachment.reads` through
  `readFragment`, whose cases cover only the 13 migrated agents' reads
  (`dataflowContext`, `nodeId`, `subtask`, …). The Dataflow Builder reads
  `("mission", "graphContext", "installedTemplates")` (builtin.py:187), the Dataset
  Finder `("mission", "nodeContext", "catalog")` (:171), the Node Builder
  `("nodeIntent", "targetContext", "externalSelection")` (:156) — none has a producer,
  so the composer returns `null` and NO context message is sent. The exact user-facing
  symptom in 67-0 ("I don't have the full dataflow edges in the current context") follows.
- **`dataflow.read` truncates edges away first.** The fallback tool (tools.py:272) dumps
  the saved spec — nodes WITH full `content` first, edges after (trill key order) — and
  cuts at `TOOL_RESULT_MAX_CHARS = 32_000`. On any non-trivial dataflow the edge list is
  precisely what the marker replaces. It also reads the SAVED spec (unsaved canvas work
  is invisible) and `MAX_TOOL_ROUNDS = 2` leaves no "read again, narrower" recovery.
- **Runtime state is unreachable.** The sandbox returns complete failure data
  (`worker.py:161`: full traceback in `stderr`; `output.path == ""` is the canonical
  failure predicate — benign warnings also land in stderr), but nothing persists it:
  it lives in one HTTP response and a transient React string (`useNodeState.output`).
  `nodeProvenance` records types only, `OutputRef` successes only, and the tests
  literally scrape tracebacks out of the DOM (test_workflows.py:271) because they exist
  nowhere else. No agent can answer "why did node X fail?" — 67-0's validation loop,
  the debug agent, and the Node Content Builder's self-correction all starve on this.

## 2. Scope

In scope:
- Frontend `agentRunContext.ts` — producer cases for the composites' reads.
- Backend `app/agents/tools.py` — `dataflow.read` structure-first projection +
  `params.include` selector; new `node.runtime.read` read tool.
- Backend `app/api/routes.py` (`process_python_code` / `process_javascript_code`) —
  journal write at the response seam.
- New `app/execution/runtime_journal.py` (FS store per DEC-040).
- Roster grants: `dataflow.read` for `agent.dataset-finder`; `node.runtime.read` for
  builder/debugger/explainer/NCB coords (builtin.py).
- Tests across all seams.

Out of scope: executing anything (67-7); topology metadata (67-3); UI changes beyond
none (this memo is plumbing); provenance schema changes (the journal is a new store,
not a provenance rewrite); browser-executed node types' outputs (merge/vis/pool pass
data through — journal entries cover sandbox-executed code nodes first, recorded
limitation).

## 3. Recommended Implementation Approach

**A. Grounded context producers (frontend, cheap).** Add `readFragment` cases:
- `graphContext` → the existing `liveTrill(canvas)` JSON (same source as
  `dataflowContext`, labeled for the builder) — full nodes+edges, live, no truncation
  client-side (the server's 120k `CONTEXT_MAX_CHARS` cap already guards).
- `mission` → the user's message is already the mission; emit the workflow goal + name
  fragment (`workflowGoal`, `workflowName`).
- `installedTemplates` → the client registry's template ids/labels (the same list the
  palette renders) — the model plans only in installable vocabulary.
- `targetContext`/`nodeIntent` → the node-target fragments that already exist for
  `nodeId`/`subtask`/`nodeContext`, mapped by name.
- `externalSelection` stays null-producing (it arrives via the confirmation prompt).
- Dataset Finder on canvas targets gets `graphContext` treatment via its `catalog` read?
  No — `catalog` stays tool-served (catalog.search is the truth); only `mission` gains
  a producer for it.

**B. `dataflow.read` becomes structure-first.** The projection orders and bounds for
usefulness under the same 32k cap: `{name, goal, nodes: [{id, type, goal, contentChars,
hasContent}], edges: [ALL], datasets, runtime: {nodeId: {status, updatedAt}}}` — edges
are never the casualty; node CONTENT is elided to lengths by default and fetched
per-node via the existing `node.read`. `params.include: ["content"]` restores the old
dump for callers that want it (budgeted). Byte-parity tests pin the old form behind the
selector.

**C. The runtime journal (DEC-052).** `process_python_code` already holds everything at
one seam: `nodeId`, `dataflowId`, and the sandbox response. Persist per execution:

```
.curio/users/<key>/projects/<dataflowId>/runtime/<nodeId>.json
{ "nodeId", "status": "ok"|"error", "stderrTail": <last 4000 chars>,
  "stdoutTail": <last 2000>, "output": {"path","dataType"}, "outputSchema": <cols/dtypes
  when the sandbox reports them>, "startedAt", "durationMs", "executionSeq" }
```

Latest-per-node (one file per node, overwritten) — history is provenance's job. Failure
predicate is `output.path == ""` (never stderr-nonempty). The write is best-effort and
never blocks the execution response. `node.runtime.read` (read tool, params `{nodeId}`)
returns the record or an honest "never executed"; `dataflow.read`'s `runtime` block
carries the status map so one call answers "what ran, what failed."

## 4. Data and State Handling

- The journal is server-owned, keyed by the same user/project identity as the spec;
  browser execution writes it implicitly by calling `/processPythonCode` (no new
  frontend obligation); 67-7's headless runner writes the same store.
- Staleness: a journal record outliving an edited node is detectable (`markNodeStale`
  is frontend-only) — the record carries `contentSha256` of the executed code so readers
  can flag "result predates the current content".
- No React state changes; the live canvas keeps its transient channel untouched.

## 5. UI and UX Requirements

None visible. Agents stop saying "I don't have the edges"; the debug/explainer agents
start quoting real tracebacks. (Surfacing the journal in the UI is 67-7's validation
panel.)

## 6. Edge Cases

- Spec larger than 32k even structure-first → elide node goals next, never edges;
  marker names what was elided.
- Node executed under a project with no `dataflowId` (unsaved) → no journal write
  (recorded limitation; Simulation Mode always has a project id).
- Concurrent executions of one node → last write wins (executionSeq monotonic).
- JS nodes → same seam via `process_javascript_code`.
- Journal read for a deleted node → "no such node" with the spec as truth.
- Malformed/partial journal file → treated as never-executed (fail-open read).

## 7. Testing Strategy

- Backend: journal write on ok/error (traceback tail captured; path predicate), tool
  reads (never-executed, stale-content flag, deleted node), `dataflow.read` projection
  (edges survive a 100-node spec that previously truncated them — regression pin),
  include-selector byte parity, dataset-finder grant.
- Frontend: `agentRunContext` producer tests per new read (composites now emit
  fragments; null-composition regression for unknown reads stays).
- Integration: a Dataflow Builder run whose `dataflow.read` result contains the full
  edge list + runtime block.

## 8. Acceptance Criteria

- [x] A Dataflow Builder attachment's run carries a grounded context with full nodes and
      edges; the composites never compose `null` on a populated canvas.
- [x] `dataflow.read` on a large dataflow returns ALL edges (content elided), and
      `node.runtime.read` returns the traceback tail of the last failed run.
- [x] Executing a node in the browser leaves a journal record any agent can read on the
      next turn.

## 9. Recommended Commit Breakdown

1. Backend: runtime journal store + `/process*Code` seam write + tests.
2. Backend: `dataflow.read` projection + `node.runtime.read` tool + grants + tests.
3. Frontend: `agentRunContext` producers + tests.
4. Docs: DEC-052 ledgers + BL-P5 entry.

## 10. Engineering Quality Checklist

- One seam per concern: journal writes at the execution route; context at the composer;
  no duplicated projections.
- Fail-open reads, best-effort writes — execution latency and reliability unchanged.
- The saved spec remains the single structural truth; the journal is observational.
- Grants stay explicit per-coord; no blanket tool exposure.
