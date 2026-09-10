# dev/135 — Every execution is journaled, and every agent can read it: a browser-rendered node's outcome is runtime truth too

**Status: PROPOSED (2026-09-10) on `imp/agentcatalog` @ `6b1c51bd`. Every line number below was read
on that commit; every claim about the failing dataflow was read from the owner's screenshot and the
code paths it names.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `6b1c51bd` (dev/133 + dev/134's docs commit).
Origin: owner instruction — *"The Vega Node execution and errors aren't being put in the node
context, since the agent can't detect it, fix this and all the nodes that don't have the output and
execution status written to its own object instance."* Evidence: the screenshot of dataflow
`a29d1ad8-fcaa-43e2-b4a9-233a7fe0fe7d` — the Vega-Lite node's footer reads **Error**, the toast
reads **"outputs is not a valid input type for the 2D Plot (Vega-Lite)"**, and the Node Builder
attached to that very node replies *"Since the node has never been executed, there are no runtime
errors to diagnose"* and then asks to be shown the schema.
Family: dev/67-2 (`DEC-052`, the runtime journal) → dev/111 (the live `current_input`/
`current_output` summaries) → dev/119 (`DEC-076`) → dev/127 (bounded artifact schemas) → dev/129
(**F2**: *"a frontend endpoint reporting render errors into the journal … its own memo, a new write
path with permissions"*) → dev/131 (**F3**, the same gap restated) → dev/133/134 (what Solve checks
before it writes) → **dev/135 (this memo)**.
Design decisions consumed: `DEC-052`, `DEC-076`, `DEC-063`, `DEC-006`.

---

## 1. Problem Statement

A node that ran and failed **in the browser** leaves no trace any agent can read. Three distinct
holes produce the owner's sentence, and they are in three different places.

### D1 — the runtime journal has exactly two writers, and both are the sandbox

`runtime_journal.record_execution` (`DEC-052`) is written from three call sites only:
`/processPythonCode` and `/processJavaScriptCode` (`api/routes.py:461`, `:593`, through
`_record_runtime_outcome`) and the validation runner. So the journal knows about Python and
JavaScript nodes and **nothing else**. Every other kind runs in the browser or through its own
service and journals nothing at all:

| Kind | Where it runs | What it reports today | Journaled |
|---|---|---|---|
| `vis-vega` | `useVega.handleCompileGrammar` → `compileGrammar` | `setOutput({code: "error", content})` (`vegaBehavior.ts`) | **no** |
| `autk-grammar` | `autkGrammarBehavior` (WebGPU, autk-db) | five distinct error paths + a run summary | **no** |
| `data-pool` | `useTableData` / `DataPoolContent` | the four `nodeEmptyState` reasons | **no** |
| `merge-flow` | `mergeFlowBehavior` | *"N of M inputs are ready"* | **no** |
| `vis-simple` | `simpleVisBehavior` | render outcome | **no** |
| `spatial-join` | its own service (`fetch(API_BASE)`) | `setOutput({code: "error", content: e.message})` | **no** |
| `data-export` | `dataExportBehavior` | export failure | **no** |
| *any* kind | `UniversalNode`'s error boundary (`:261`) | *"This node could not render."* | **no** |
| `data-loading`, `computation-analysis`, `data-transformation`, `data-summary`, `js-computation` | the sandbox | stdout/stderr/output/duration | yes |

The consequence is not only a missing error. It is that `node_context.compose_node_context` —
the ONE composer every content generation reads (`node_context.py:70`, `runtime_journal.status_map`)
— reports `runtimeStatus: "never-executed"` for a node that has run a dozen times, and
`runtime_journal.last_failure` (dev/129's repair seed, dev/131's session, dev/133's checks) has
nothing to repair from. dev/129 predicted this precisely as its **F2**, and dev/131 restated it as
**F3**: *"the last gap between 'manages the dataflow' and 'manages the dataflow'."*

### D2 — where the journal DOES have an outcome, the node context passes on one word

`node_context` projects each node — the target and its neighbours — as
`{id, type, goal, hasContent, contentChars, runtimeStatus}` where `runtimeStatus` is `"ok"` /
`"error"` / `"never-executed"`. A delegated child asked to fix a node that failed is told the word
`error` and nothing else: not the message, not the output type, not when, not what ran. The
module's own docstring records the intent (*"`outputSchema` joins when the runtime journal starts
capturing column metadata"*) — the journal has captured `output.dataType`, `stderrTail`,
`startedAt`, `durationMs` and `executedCodeSha256` since dev/67-2, and the context still forwards
none of it.

### D3 — the node-attached agents do not declare the read that carries live runtime state

dev/111 (ported by dev/129) made the chat path carry a bounded, truthful live summary —
`current_input` / `current_output`, including the error text — but **only** under the
`nodeContext` read (`agentRunContext.ts:126-141`). The Node Builder declares
`reads=("nodeIntent", "targetContext", "externalSelection")` (`builtin.py:201`), and
`targetContext` for a node target composes `{id, type, goal, content}` (`agentRunContext.ts:184`)
— no runtime state whatsoever. So the agent in the owner's screenshot, attached to a red node,
had no way to know it had run: its sentence is not a hallucination, it is an accurate report of an
empty context.

### D4 — the error itself, worth naming because the fix makes it fixable

*"outputs is not a valid input type for the 2D Plot (Vega-Lite)"* comes from
`useVega.parseInputData`, which accepts `dataframe` and `geodataframe` only. The Data Pool feeding
it holds **two tabs** (visible in the screenshot), and a pool with more than one table emits
`{dataType: "outputs", data: [...]}` (`useTableData.ts:327`). So the graph has a real type
mismatch — a multi-table pool cannot feed a Vega node — and the manifest already says so
(`vis-vega.inputPorts: [DATAFRAME, GEODATAFRAME]`). This memo does not change that rule; it makes
the failure legible, which is what lets an agent (or the user) fix the wiring instead of guessing
at the grammar. Recorded as **F1** below.

### Are the two open follow-ups the owner asked about implicated?

- **"Run outcomes surfaced as row chips from the journal"** (`BL-P5-20260812-15`) — **related, and
  downstream of this.** Its premise is that the journal already holds the outcomes and only the
  plan row chips have not caught up. For a Python node that is true; for every kind in D1's table
  the journal is empty, so implementing the chips first would print *"never executed"* on nodes the
  user just watched fail — the same lie in a second place. This memo is its prerequisite, and the
  chips stay that entry's follow-up.
- **"The deterministic canvas-diff engine"** (`DEC-049` / dev/59's deferral) — **not related.**
  That is about destructive replan reconciliation (deriving removals and rewires by diffing a
  proposed plan against the live canvas instead of having the plan name its victims). It touches
  neither execution outcomes nor the node context.

The follow-ups this defect IS: **dev/129 F2** and **dev/131 F3**, both recorded as needing their own
memo with a new write path and permissions. This is that memo.

### Expected behavior

- **R1** Every node execution is journaled, whatever ran it — the sandbox, the browser, or a
  node's own service — with its status, its message, its output type, when it ran and how long it
  took, plus which *origin* produced the record.
- **R2** A node's own instance carries its last outcome (`data.output` already does) and that
  outcome is **persisted** as runtime truth rather than being lost on reload.
- **R3** `node_context` forwards the OUTCOME, not a single word: the error message, the output
  type, the origin and the age — bounded — for the target node and its neighbours.
- **R4** Every node-attached agent can read it, whichever read it declares: `targetContext` and
  `nodeContext` both carry the live runtime block, in the same vocabulary the server uses.
- **R5** A browser-reported record can never impersonate a sandbox one: it says `origin:
  "browser"`, it cannot claim an artifact path it did not produce, and its fields are bounded.
- **R6** Nothing regresses for the sandbox path: a Python node's journal entry keeps its exact
  shape, and the two existing writers keep their behavior byte-for-byte.

---

## 2. Scope

**In scope.**
- `app/execution/runtime_journal.py`: an explicit `status` and `origin` on the record (the current
  `ok` predicate is `bool(output.path)`, which no browser render can satisfy), plus a
  `record_browser_execution` entry that takes a message rather than stdout/stderr.
- `app/api/routes.py` (or `app/execution/routes.py` if that is where node-scoped writes belong): one
  authenticated `POST` that journals a browser outcome for `{dataflowId, nodeId}`, bounded and
  ownership-checked.
- `app/agents/node_context.py`: the runtime block per node (status, message, output type, origin,
  ranAt, durationMs), bounded, replacing the bare `runtimeStatus` word (which stays, for the
  callers and tests that read it).
- Frontend: ONE reporter at the single chokepoint every kind already passes through
  (`useNodeState`'s output effect / `UniversalNode`'s `setOutputCallback`), so no behavior file
  needs a per-kind edit; debounced, fire-and-forget, never blocking a render.
- `agentRunContext.ts`: `targetContext` gains the same runtime block as `nodeContext`.
- `builtin.py`: the node-attached agents that read `targetContext` keep it; nothing needs a new
  read (R4 is satisfied by the composer, not by re-declaring), and the two prompt files that
  describe the node context learn the field names.
- Tests: journal unit tests, route tests (auth, ownership, bounds, origin), `node_context` tests,
  jest tests for the reporter and the composed context, and a regression test for the owner's
  shape (a Vega node whose browser error reaches a delegated child).
- Docs + ledgers.

**Out of scope.**
- Changing what the Vega node accepts, or auto-rewiring the pool → Vega edge (D4/F1). The mismatch
  becomes legible here; changing the graph is a plan/proposal act under `DEC-006`.
- Streaming or history: the journal keeps ONE latest record per node, as it does today.
- Provenance. `ProvenanceProvider`'s `nodeExecProv` is a separate, richer track for the provenance
  view; this memo does not fold the two together.
- Rendering verification (dev/129 F1's headless render idea).

---

## 3. Recommended Implementation Approach

### A. The journal learns two facts it never had: an explicit status, and an origin

```python
record_execution(..., status=None, origin="sandbox")   # status=None keeps today's ok/error rule
record_browser_execution(user_key, project_id, node_id, *,
                         status, message="", output=None, duration_ms=0, code="")
```

`status` explicit because `ok = bool(output["path"])` is a sandbox rule: a Vega node that rendered
perfectly produces no artifact and would be journaled as an error. `origin` explicit because a
reader must be able to tell what produced the record — `"sandbox"`, `"validation"`, `"browser"` —
and because `last_failure` already reports an origin and should keep telling the truth. The record
gains nothing else: same file, same one-per-node, same best-effort write that never raises.

### B. One route, bounded and ownership-checked

`POST /api/nodes/runtime` with `{dataflowId, nodeId, status, message?, outputType?, durationMs?}`:

- `@require_auth`, and the project is resolved the way every other project route resolves it, so a
  caller can only write to a dataflow they own;
- `status` is an allowlist (`ok` | `error` | `running`), `message` is truncated on arrival, and
  **no `path` is ever accepted** — a browser cannot mint an artifact id, so nothing downstream can
  mistake a reported record for a stored artifact;
- best-effort by contract: the response is `204` whether or not the write landed, because a render
  must never fail over its journal (`DEC-052`'s own rule).

### C. One reporter, at the chokepoint every kind already crosses

`useNodeState` already mirrors the outcome onto the node's own instance:

```ts
useEffect(() => { data.output = output; if (output?.code === 'success') data.executedCode = code; }, [output]);
```

That is the *object instance* half of the owner's sentence, and it is the right place for the other
half: one effect that reports a settled outcome (`success` / `error`, never the transient `exec`)
for the current project and node. Consequences of putting it there rather than in each behavior:
every kind in D1's table is covered at once, including `UniversalNode`'s render boundary; a kind
added later is covered by construction; and the sandbox kinds do not double-report, because their
server-side record is written by the route that ran them and the reporter's `origin` marks the
browser one (last writer wins, and for a sandbox node the server's write is the later one).

Bounded and quiet: debounced, deduplicated on `(status, message)` so a re-render cannot spam, and
`void`-ed — no await, no toast, no error surfaced to the user.

### D. The node context forwards the outcome

```json
"runtime": {"status": "error", "origin": "browser",
            "message": "outputs is not a valid input type for the 2D Plot (Vega-Lite)",
            "outputType": "", "ranAt": "2026-09-10T23:01:11Z", "durationMs": 12}
```

on the target node and on each neighbour row, beside the existing `runtimeStatus` word (kept, so
every current reader and test stays valid). Bounded: the message is truncated to the same 240
characters dev/111's client-side summary uses, so the two descriptions of one node cannot differ in
size or content.

### E. Both node reads carry it

`targetContext` (what the Node Builder declares) gains the same live runtime block `nodeContext`
already carries, from the same helpers (`summarizeNodeInput`/`summarizeNodeOutput`), so an agent
attached to a node sees the state whichever read its manifest declares — and the chat path and the
server path describe the node in the same words.

---

## 4. Data and State Handling

- **Source of truth**: the per-node journal file (`<project>/runtime/<nodeId>.json`), one latest
  record, exactly as `DEC-052` established. The browser writes through the route; the sandbox
  writes server-side. Last write wins, and `origin` says who wrote it.
- **The node instance**: `data.output` stays the live, in-memory truth the canvas renders from and
  the client-side summary reads. It is deliberately NOT added to the saved spec — the spec is the
  document, the journal is the run log, and mixing them would make a canvas save carry runtime
  state (the `preserve_agent_state` lesson).
- **Derived values**: `node_context.runtime` is projected from the journal at compose time; nothing
  new is cached.
- **Loading/empty/error**: no record → `never-executed`, unchanged. An unreadable record →
  `never-executed`, unchanged. A `running` record older than a wide margin is reported as it is —
  this memo does not invent staleness rules.
- **Races**: a browser report and a sandbox write for the same node are both single-file writes; the
  journal already tolerates that (best-effort, atomic write of one JSON document).

---

## 5. UI and UX Requirements

No new UI. The reporter is invisible: no spinner, no toast, no blocking, and a failed report changes
nothing the user sees. Two existing surfaces get *more truthful* content without changing shape:

- an agent chat attached to a node can now say what the node's last run did, instead of *"the node
  has never been executed"*;
- the plan row chips (`BL-P5-20260812-15`'s follow-up) become implementable for every kind, which
  is called out there rather than built here.

Accessibility: unchanged (nothing new is rendered).

---

## 6. Edge Cases

| Case | Behavior |
|---|---|
| An unsaved canvas (no project id) | Nothing is reported; the journal needs a project identity, as `_record_runtime_outcome` already requires. |
| The same outcome re-rendered (React re-mount, resize) | Deduplicated on `(status, message)`; one write per real change. |
| A sandbox node that also reports from the browser | Both are legal writes; the server's record is the later one for that run, and `origin` distinguishes them. Nothing downstream reads `origin` as authority — it is evidence. |
| A very long error (a WebGPU stack, an autk-db dump) | Truncated on arrival, and again by the journal's own tails. |
| A hostile client posting a fabricated outcome | It can only affect its own project's journal, cannot claim an artifact path, and cannot mark a node `ok` in a way that writes content — the journal is observational (`DEC-052`) and Solve still runs code before writing it. |
| The `exec`/`running` transient | Not reported by default (a render in flight is not an outcome). Reported only if a kind's long run makes it useful; the allowlist has the value so the decision is one flag, not a protocol change. |
| A node deleted after it ran | Its record stays until the project's runtime directory is swept; `node_context` only projects nodes present in the spec, so a ghost is never described. |
| A browser render that succeeds | `status: "ok"` with no artifact path and the declared `outputType`, so a Vega node reads `ok` instead of `never-executed`. |
| Offline / the route returns 500 | Fire-and-forget: the render is unaffected and the journal simply keeps the older record. |
| dev/133's empty-result check | Unaffected: it reads the artifact a *sandbox* run stored. A browser record carries no artifact, so no shape check fires on it. |

---

## 7. Testing Strategy

**Backend unit** — `runtime_journal`: an explicit `ok` status with no artifact path records `ok`
(today it would record `error`); `origin` round-trips; `last_failure` reports a browser failure with
`origin: "browser"`; the sandbox path's record is byte-identical to today's for the same inputs.

**Backend route** — auth required; a project the caller does not own is refused; an unknown status
is refused; `message` is truncated; a `path` in the payload is ignored/refused; a successful post is
readable through `read_record` and `status_map`; a post for an unsaved/unknown project is a no-op
rather than an error.

**Backend `node_context`** — the runtime block appears for the target and for neighbours; a
never-executed node still says `never-executed` and carries no message; the message is bounded; the
legacy `runtimeStatus` word is unchanged for every existing case.

**Integration (the owner's shape)** — a Vega node reports `error: "outputs is not a valid input
type for the 2D Plot (Vega-Lite)"` through the route; a delegated `node.content.generate` for that
node then receives a `nodeContext` whose runtime block carries that message; and the per-node
Solve's own context does too. This is the test that fails today and is the point of the memo.

**Frontend jest** — the reporter posts once for a settled outcome, does not post for `exec`, does
not post without a project id, deduplicates repeats, and never throws when the endpoint fails;
`targetContext` carries the runtime block; `nodeContext` is unchanged.

---

## 8. Acceptance Criteria

1. A Vega-Lite node that fails to render is, within one render cycle, `status: "error"` in the
   project's journal with its message and `origin: "browser"`.
2. An agent attached to that node — reading `targetContext` OR `nodeContext` — is told the node ran
   and what it said, and can no longer answer *"the node has never been executed"*.
3. A delegated content generation for that node receives the same message in its `nodeContext`.
4. Every kind in D1's table reports its outcome, without a per-kind edit in its behavior file.
5. A node that rendered successfully reads `ok`, not `never-executed`, and not `error`.
6. A Python node's journal record and every existing reader of it are unchanged.
7. No render is delayed, failed or visibly changed by reporting, and a failed report is silent.
8. `tests/test_agents` and the datasets/api suites green; jest green; `tsc --noEmit` clean.

---

## 9. Recommended Commit Breakdown

1. `runtime_journal`: explicit `status` + `origin`, `record_browser_execution` (+ unit tests).
2. The route (+ auth/ownership/bounds tests).
3. `node_context`: the runtime block (+ tests), and the two prompts that name the context fields.
4. Frontend: the one reporter at the chokepoint, and `targetContext`'s runtime block (+ jest).
5. The integration regression from the owner's dataflow, docs, memo close, `dev/00` row, BL entry.

---

## 10. Engineering Quality Checklist

- One write path per side: the sandbox's existing server-side call and ONE browser route — no
  per-behavior reporting, so a new node kind is covered by construction.
- One vocabulary: the client summary and the server context use the same status words and the same
  message bound, so the two cannot describe one node differently (`DEC-063`'s spirit).
- The journal stays observational and best-effort: no render, no execution and no agent turn can
  fail because of it.
- Untrusted input is treated as such: allowlisted status, bounded message, no artifact path, own
  project only.
- No runtime state enters the saved spec; the document and the run log stay separate.
- The legacy `runtimeStatus` word survives beside the richer block, so no existing reader is
  rewritten to satisfy a new field.
- The two follow-ups the owner asked about are answered in §1 rather than silently folded in: the
  row chips become implementable (and stay their entry's follow-up), and the canvas-diff engine is
  unrelated.
