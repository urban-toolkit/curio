# Implementation Memo: Streamed Solve Progress with Cancellation (dev/52 follow-up; the user-facing slice of DEC-021)

Date: 2026-08-05
Status: proposed

## 1. Problem Statement

Solve (dev/52, DEC-048) is a single blocking POST: the user clicks Solve, the strip flips to
"Solving…", and then **nothing happens** until every depth-1 child in the batch has finished —
often minutes for a large plan (children run 3-wide over a slow local provider). Concretely:

- **No progress**: `builderSession.nodeRuns` is written once, in the batch's `finally`
  (services.py `solve_attachment`), so the strip's per-node pills stay "pending" throughout
  and jump to their final statuses all at once. The chat run path already streams
  (dev/22 SSE, `run/stream`); Solve — the longest-running action in the product — does not.
  dev/52 §UI recorded this as a deviation: "streaming joins later with DEC-021".
- **No cancellation**: a mis-aimed Solve (wrong Retry subset, wrong provider, a plan the user
  immediately regrets) cannot be stopped. The only outs are waiting or the 15-minute
  `_SOLVE_STALE_SECONDS` crash guard. Closing the tab doesn't stop the server-side batch
  either — children keep burning provider quota into an abandoned request.
- **Solved content arrives late**: `appliedContents` reach the live canvas only after the
  whole batch returns (AgentAttachmentsProvider.solveAttachment loops the final payload), so
  a node solved in second 5 renders at second 300.

Expected: Solve streams per-node lifecycle events over the existing SSE envelope; each solved
node's content lands on the live canvas as it completes; the strip's pills advance live; a
Cancel control stops dispatching new children (in-flight children finish and their results
are kept); whatever completed before cancellation persists exactly as it would have.

Scope boundary against DEC-021: this memo delivers the **user-facing slice** — live progress
and user-initiated cancellation of an in-request batch. DEC-021's full machinery (persisted
leases/heartbeats, `interrupted` executions, background execution surviving the request, the
LangChain re-open condition) remains open and deferred; nothing here forecloses it.

## 2. Scope

In scope:
- `utk_curio/backend/app/agents/services.py` — `solve_attachment_stream` generator (the
  batch re-shaped around `as_completed`), a module-level cancel registry, cancellation
  checks in the worker, `request_solve_cancel`.
- `utk_curio/backend/app/agents/routes.py` — `POST …/attachments/<id>/solve/stream` (SSE,
  mirroring `stream_attachment`) and `POST …/attachments/<id>/solve/cancel`.
- `utk_curio/frontend/urban-workflows/src/api/agentsApi.ts` — `solveAttachmentStream`
  (mirrors `runAttachmentStream`, plus an `AbortSignal`).
- `AgentAttachmentsProvider.tsx` — streaming becomes the solve path; transient per-node
  progress state; per-node live content application; cancel wiring.
- `AgentBuilderStrip.tsx` (+ module.css, agentsApi types) — live pills (`solving` status
  style), a Cancel button during solve.
- Tests: backend route/service SSE + cancellation; frontend api parser, provider progress,
  strip cancel.
- Ledgers/docs: new DEC-050 in dev/03 (+ 2.1 traceability), BL-P5 entry; dev/52's recorded
  deviation gets its closure pointer.

Out of scope (deliberately):
- The blocking `POST …/solve` endpoint — stays as-is (API compatibility, Retry mechanics,
  existing tests); the streaming route is additive, exactly like `run` vs `run/stream`.
- DEC-021 proper: leases, heartbeats, `interrupted` status, cross-restart recovery,
  background execution. The 15-minute stale guard remains the crash story.
- Aborting an in-flight provider call mid-request (the HTTP client has no clean abort;
  DEC-021 records that provider calls are never replayed — finishing them and keeping the
  results is the consistent posture).
- Solve batching semantics, digest guards, delegation resolution — unchanged (dev/52/59).

## 3. Recommended Implementation Approach

**Backend — the batch becomes a generator (the dev/22 shape).**
`solve_attachment_stream(user_key, project_id, attachment_id, config, node_ids)` yields
`(kind, payload)` tuples; the route wraps them in the same `_sse()` envelope as
`stream_attachment`. All pre-flight validation (409 already-solving, 409 nothing-to-solve,
provider config) raises BEFORE the generator is returned, so errors keep their JSON statuses.

Event grammar (additive; unknown events are skipped by the dev/22 client parser):
- `solve_started` — `{executionId, targets: [nodeId…]}` after the in-flight marker persists.
- `node_started` — `{nodeId}` when a worker picks the node up.
- `node_result` — `{nodeId, status: solved|failed|skipped, error?, content?}` as each child
  finishes; `content` is the dev/57-extracted text for solved nodes.
- `done` — `{results, appliedContents, builderSession, executionId, cancelled: bool}` after
  the batched finally-write (the same payload the blocking route returns, plus `cancelled`).
- `error` — envelope parity with `run/stream`.

Mechanics: replace `pool.map` with `pool.submit` + `concurrent.futures.as_completed`, and
have `_solve_one` emit through a thread-safe `queue.Queue` (`started` marks, results) that
the generator drains between yields — workers never touch the response. The `finally` block
is unchanged in substance: ONE re-guarded read-modify-write persists contents, statuses, and
the exit phase. Because Flask closes a streaming generator on client disconnect
(`GeneratorExit` at the next yield), the finally-write ALSO runs on disconnect — partial
results persist and the phase exits `solving`, never wedging the strip.

**Cancellation — one predicate, two signals.**
- A module-level registry `_SOLVE_CANCEL_EVENTS: dict[str, threading.Event]` keyed by the
  solve execution id, registered before dispatch, removed in `finally`.
- `request_solve_cancel(user_key, project_id, attachment_id)` (the cancel route): looks up
  the running solve via `builderSession` (phase `solving` + a persisted `solveExecutionId`
  written alongside `solvingSince`), sets the in-process event, AND persists
  `cancelRequested: true` on the session — the durable signal a multi-worker deployment or
  a lost registry entry still honors.
- `_solve_one` checks `should_stop()` (event OR the persisted flag, re-read lazily) at task
  entry: a stopped worker returns `(node_id, "unstarted")` without any provider call.
  In-flight children are never aborted — they finish and their results persist (DEC-021's
  no-replay posture). Client disconnect funnels into the same path: the generator's
  `GeneratorExit` handler sets the event, so an abandoned tab stops dispatch at the next
  node boundary instead of burning the rest of the batch.
- Unstarted targets **revert to `pending`** — they were never attempted, so no new status
  enters the state machine (`interrupted` belongs to DEC-021's lease expiry, not to a user
  cancel); Retry is immediately available and the strip needs no new vocabulary. The solve
  card and `done` payload say plainly: "cancelled — N node(s) not attempted".

**Frontend — streaming is the solve path (fix-primary-paths: no dual mode).**
- `agentsApi.solveAttachmentStream(projectId, attachmentId, onEvent, nodeIds?, signal?)` —
  the `runAttachmentStream` reader verbatim (frame parser, error semantics) with the solve
  event names and an `AbortSignal` passed to `fetch`.
- `AgentAttachmentsProvider.solveAttachment` switches to the stream: `node_result` with
  content → `notifyAgentCanvasMutation({kind: "node-content-applied", …})` immediately (the
  dev/51 bridge path, now per node); transient progress lives in provider state
  `solveProgress: Record<attachmentId, Record<nodeId, status>>`, cleared on `done`/error;
  `cancelSolve(attachmentId)` aborts the fetch AND posts `solve/cancel` (belt and braces —
  the abort alone stops dispatch on the next boundary, the endpoint stops it across workers).
  The `finally` hydrate + reload stays (the durable truth still arrives by refetch).
- `AgentBuilderStrip` renders pills from `nodeRuns` overlaid with the transient
  `solveProgress` (a `solving` status gets its own style + the existing `aria-live` region
  announces changes); while solving, a Cancel button appears beside the disabled Solve;
  cancelled runs surface the "N not attempted" note through the existing error/hint line.

## 4. Data and State Handling

- Source of truth unchanged: `builderSession` on the attachment record, written ONCE in the
  generator's `finally`. Streamed events are display-transport, never state — on reconnect or
  refresh the persisted session is authoritative (transient overlay discarded).
- `solveExecutionId` + `cancelRequested` join `solvingSince` on the session for the solve's
  duration; all three are cleared by the finally-write (rule-9 canvas-save stripping already
  protects agent sections).
- Per-node content still applies to the CURRENT spec under the finally re-guard (user edit
  wins, deleted node skips) — streaming `content` early to the live canvas is the same
  optimistic path node.content.write applies use today (dev/51), reconciled by the reload.
- Races: double-cancel is idempotent (event set + flag write); cancel after completion is a
  404-style no-op ("no solve running"); the stale guard (15 min) still covers a hard crash;
  a second Solve during `solving` keeps its existing 409.

## 5. UI and UX Requirements

- Pills advance live: `pending → solving → solved|failed|skipped` per node, no full-strip
  jump; the `aria-live="polite"` list announces status changes; `solving` gets a distinct
  style consistent with the existing status styles.
- Cancel: visible only while a solve is in flight; one click; disabled after click
  ("Cancelling…") until `done` arrives; never yanks in-flight results — the card says what
  completed and what was not attempted.
- Solved content appears on the canvas as each node finishes (no flicker on the final
  reload — contents are byte-identical by construction).
- No layout shift: the Cancel button occupies the existing actions row; the strip's height
  is stable across phases.

## 6. Edge Cases

- Cancel before the first child dispatches — every target reverts to pending; `done` says
  "0 solved, N not attempted".
- Cancel when all children already dispatched — nothing to stop; batch completes normally,
  `cancelled: true` still reported honestly with 0 unstarted.
- Client disconnect mid-batch (tab close, network drop) — GeneratorExit → stop event →
  finally persists partial results; the strip on next load shows the persisted truth.
- Missing specialist (delegation unresolvable) — the existing ONE-install-proposal path runs
  before any dispatch; the stream emits `solve_started` then `done` with all-failed results,
  same information as the blocking route.
- Node deleted mid-solve / user typed content mid-solve — the finally re-guard skips, as
  today; the streamed `node_result` may say `solved` while the persisted status says
  `skipped` — the reload reconciles, and the card reflects the persisted truth.
- Streamed content for a node the user is editing — `node-content-applied` goes through
  `applyNodeContent` (provider state), same as an individual apply today (dev/51).
- Old client + new server / new client + old server — additive route and events; the
  blocking endpoint is untouched; `solveAttachmentStream` failing with 404 on an old server
  is a hard error (no silent fallback — fix-primary-paths).
- Two tabs: tab B's cancel endpoint stops tab A's solve via the persisted flag (predicate
  re-read at node boundaries).

## 7. Testing Strategy

Backend (`tests/test_agents/test_routes.py`, mirroring the stream tests' SSE parsing):
- Happy path: `solve_started` → `node_started`/`node_result` per target → `done` with
  results + builderSession; per-node content in `node_result` matches dev/57 extraction.
- Cancellation: fake children gated on an event — cancel after the first result; remaining
  targets pending, phase `applied`, `done.cancelled` true, card notes "not attempted".
- Disconnect: close the generator after the first `node_result`; the persisted session
  carries the partial results and exits `solving`.
- Cancel endpoint: 409/no-op without a running solve; sets the persisted flag; idempotent.
- Pre-flight failures (already solving, nothing to solve, provider config) return JSON
  statuses, never a stream.

Frontend (jest):
- `solveAttachmentStream` frame parser: event fan-out, abort signal, mid-stream `error`.
- Provider: transient progress overlay set/cleared; per-node `node-content-applied`
  notifications fire as results arrive; cancel aborts + posts.
- Strip: pills render the overlay statuses; Cancel appears only while solving, disables
  after click; cancelled note surfaces.

Full backend + frontend suites green.

## 8. Acceptance Criteria

- [ ] Clicking Solve shows per-node pills advancing live (pending → solving → outcome),
      and solved nodes' content appears on the canvas as each completes.
- [ ] Cancel stops new children from starting; in-flight children finish and persist; the
      strip returns to Solve/Retry with unstarted nodes pending; the transcript card states
      solved/failed/not-attempted counts.
- [ ] Closing the tab mid-solve does not wedge the session: partial results persist, the
      phase exits `solving`, and no further children dispatch after the next boundary.
- [ ] The blocking `/solve` endpoint behaves byte-identically (existing tests untouched).
- [ ] DEC-021 remains open: no lease/heartbeat/background machinery was added or implied.

## 9. Recommended Commit Breakdown

1. `Streamed Solve: solve_attachment_stream generator + cancel registry + routes (dev/63)`
   — backend service + routes + SSE/cancel/disconnect tests.
2. `Frontend: solve streams — live pills, per-node canvas content, Cancel (dev/63)` —
   api client + provider + strip + tests.
3. `Docs: dev/63 implemented + DEC-050 + BL-P5 amendment` — ledger row (+2.1), dev/52
   deviation closure pointer, memo status flip.

## 10. Engineering Quality Checklist

- One solve implementation shape (generator); the blocking route can delegate to it later
  without behavior change — no logic duplicated between the two today beyond dispatch.
- Streamed events are transport, not truth: every terminal state comes from the one
  finally-write, so no state can be produced by a dropped frame.
- Cancellation is race-safe: one predicate, checked at task entry; idempotent signals;
  no thread is killed, no provider call replayed.
- The strip's overlay is derived state, cleared on terminal events — no duplicated
  session state in the frontend.
- Accessibility: live region announces progress; Cancel is a real button with a busy state.
