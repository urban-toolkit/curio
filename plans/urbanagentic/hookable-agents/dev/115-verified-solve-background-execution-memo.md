# dev/115 — Solve is the engineering loop: when the user asks to solve a data-loading node, the runtime executes it in the sandbox, fixes the errors, re-runs, and lands only code that passed — in the background, with the attempt trail on the card (DEC-021's single-process slice; the DEC-048 LangChain re-open condition, decided)

**Status: IMPLEMENTED (2026-09-08) on `imp/agentcatalog` — commits `7592497b` (1, runner fixes + the ONE verified-content round loop), `c792442b` (2, verified Solve in write/propose modes, batch dataset-path mapping, per-round stream events, the trail on results and the Solve card), `b575a9a9` (3, `agent_jobs.py` detached re-attachable jobs, `GET …/jobs/stream`, `liveJob` on cards, reconciliation to `interrupted` with linked Retry, `POST …/solve-node`), `617d9834` (4, Dataflow Builder `runtime.execution: background`, running dot, strip states + interrupted/Retry, provider re-attach + `solveNode`, Solve-this-node row, the collapsed attempts trail on the review card), `ea56464f` (5, `docs/AGENT-CATALOG.md`). `DEC-073` minted; backlog `BL-P5-20260908-49`. Owner decisions: Option A (direct code; LangGraph declined with §3.9's criteria recorded), data-loading nodes only in v1, A1 (every offered data-loading node; the trail on the card), A2 (the trigger is the user's Solve — never the mint, never a precondition of Apply), A3 (the three gemma4 tasks are the field scenarios). Backend `test_agents` + `test_execution` 1115 green; jest 199 suites / 2311 green; `tsc` unchanged. Deviations from the memo: no persisted heartbeat — in the single-process topology liveness IS the lease (a `solving` session whose execution this process does not hold is `interrupted` on first read), avoiding a ticker thread racing `_finish` on the spec; the 15-minute guard stays the outer bound; a multi-worker deployment would mis-reconcile and stays OQ-009. Per-node Solve has no cancel in v1 (bounded ≤3×300 s). Propose-mode Solve keeps dev/67-7's labeled choice (PASS or FAIL mints with the trail). Live re-test against gemma4 run 2026-09-08 (all three A3 prompts, driven through the HTTP API against a `curio start` stack): results and the four field-fix commits `cb0332e9`, `0b99b99e`, `421c95c6` are recorded in §A3.1; suites after the fixes: backend `test_agents` + `test_execution` + `test_backend` 1150 passed / 2 skipped, jest 199 suites / 2312 tests, `tsc --noEmit` clean.**

Date: 2026-09-08
Branch / tree: `imp/agentcatalog` @ `4039f346` (dev/114 closed). Line numbers pinned to that commit. `plans/` is untracked on this branch — this memo lives on disk.
Origin: owner request 2026-09-08 — *"plan for the background execution implementation, I think it's the DEC-021 follow-up with LangChain, since it is very important to check if the node content is correct by running it before a final solve code for the data loading nodes initially."* Two standing records make this due: dev/67-0 (*"Every node-content generation during Solve must be validated. There should be no shortcut for code considered 'trivial'"* — status COMPLETE, yet Solve's write mode still writes unexecuted content), and dev/114 F1 (the owner's Census fetch answered HTTP 400 after passing the static grounding gate — only a real run can catch a wrong request shape).
Evidence: `services.py:3792-3803` — Solve `write` mode gates the child's content statically (dev/114) and writes it; no `validate_candidate` call. `services.py:4753-4989` — `_validate_events` runs the full generate → execute-through → self-correct loop (`_VALIDATE_CORRECTION_ROUNDS = 2`, `services.py:4671`) but only for `validate-node` and Simulation Mode. `execution/runner.py:240-249` — the validation runner posts `{code, file_path, nodeType, dataType, save_dataset: False}` to the sandbox `/exec` with **no `dataset_paths` and no `user_key`**, while the interactive `/processPythonCode` (`api/routes.py:361-384`) resolves `curio_dataset_path("<id>")` ids first — so the very form dev/114 made canonical for catalog datasets fails under validation and works on Play. `runner.py:36` `SANDBOX_EXEC_TIMEOUT_S = 120` against `api/routes.py:15` `SANDBOX_EXEC_TIMEOUT = 600` and the sandbox's own 300 s wall clock (`sandbox/isolation/supervisor.py:72`); a data fetch is the slow case. `services.py:3714-4133` — Solve runs inside the streamed request: a client disconnect reaches `_finish` through `GeneratorExit` and the batch ends; `solvingSince` is a fixed 15-minute stale guard (`_SOLVE_STALE_SECONDS`, `:3576`), not a heartbeat. `manifest.py:50/365` — `runtime.execution ∈ {foreground, background}` is validated and read by nothing; every built-in declares `foreground` (`builtin.py:407`). `packages/build_jobs.py` — the repo's in-process job registry (phases, `MAX_ACTIVE_JOBS_PER_USER`, cancel, TTL sweep) is the pattern a detached Solve can reuse. No LangChain import exists anywhere in shipped code; `providers.py:11` names itself "the seam a future LangChain adapter would sit behind".
Family: dev/52 (Dataflow Builder, Solve) → dev/63 (DEC-050: streamed Solve + cancel — "the user-facing slice of DEC-021") → dev/67-0/67-7 (execute-through validation, `validate_candidate`, `previousAttempt`) → dev/67-9 (Simulation Mode: create → validate → auto-approve) → dev/71 ("one validation policy, two callers") → dev/72/73 (delegation homes, runtime-minted reviews) → dev/106 (Solve turn carries its remedy) → dev/114 (DEC-072 static gate, `sourceGrounding` inputs, F1) → **dev/115**.
Design decisions consumed: DEC-021 (leases/heartbeats, `interrupted`, no replay, linked retry — the open decision this memo partially delivers), DEC-048 (direct code; re-open condition = background/long-running orchestration through `delegation.py`), DEC-050 (streamed Solve + cancel), DEC-054 (Simulation Mode's validate-then-approve), DEC-064 (the DEC-056 pattern: a recorded decision, never a silent omission), DEC-067 (self-correcting refusals on the path that produced them), DEC-072 (the grounding gate stays; execution comes after it). **New decision proposed: DEC-073** — *Solve is the engineering loop for data-loading nodes: the user's explicit Solve (the Dataflow Builder's batch, or a per-node Solve on any data-loading node from its Node Builder) authorizes a detached, heartbeat-guarded background job that executes the node's code in the sandbox, feeds every failure back to the content generator with the traceback and fresh runtime evidence, re-runs, and lands only code that passed — directly into an empty plan node, or as a reviewed `node.content.write` (already executed) for a node that had content; every attempt is recorded and shown as a collapsed trail; proposals are never executed at mint and Apply is never gated on execution. The job survives the request, re-attaches, and is reconciled to `interrupted` at startup with retry as a linked execution — DEC-021 delivered for the single-process topology (multi-instance stays OQ-009). The DEC-048 LangChain re-open condition is thereby met and decided: not adopted (Option A), with LangGraph adoption criteria recorded.*
Backlog: `BL-P5-20260908-49` at closure; flips the "DEC-021 proper remains open" lines (dev/03 rows DEC-007/021/048/050, `REQ-RUNTIME-002`, docs/09:63-65/152-153, 3.1:28) to "single-process slice delivered by dev/115; multi-instance = OQ-009"; closes dev/114 F1 for the Solve path.

---

## 1. Problem Statement

**What is broken.** When the Dataflow Builder's Solve fills a data-loading node, the generated code is written into the saved dataflow the moment the child returns and the static grounding gate passes. Nothing has run it. The user learns whether the fetch works by pressing Play — which is exactly the moment the owner's Census example failed (HTTP 400: the endpoint existed, the request shape was wrong). dev/67-0 required the opposite (*"Only then consider the node solved"* after executing through the node), dev/67-7 built the loop, and dev/67-9 uses it in Simulation Mode; Solve's write mode — the one-click path the strip advertises — never adopted it. dev/67-7 §"Out of scope" recorded why: *"runs live inside the streamed request, like dev/63 Solve"*, and a real fetch inside a request that dies with the tab was judged too fragile.

**Why the two halves are one problem.** Executing a data fetch takes seconds to minutes (the sandbox wall clock is 300 s), a correction loop multiplies that by up to three, and the browser tab is the process boundary today: closing the panel ends the Solve (`GeneratorExit` → `_finish`). "Verify before you finalize" is only usable if the verifying run survives the request — which is DEC-021's open half. So the plan must deliver both: the verified Solve loop and the detached, re-attachable, heartbeat-guarded execution it needs.

**Affected surfaces.** `_solve_events` (write and propose modes), `_validate_events` (the loop to share), `execution/runner.py` (payload and timeout), the Solve routes and SSE contract, `builderSession` state (`solvingSince`, `solveExecutionId`, `nodeRuns`, `phase`), the builder strip (states, reconnect, verdicts), the dock tile (running indicator), the Dataflow Builder manifest (`runtime.execution`), and the startup path (reconciliation).

**Expected behavior.** For a data-loading node, Solve generates → gates (DEC-072) → executes the one-node slice in the sandbox with the real dataset-path mapping and a fetch-sized timeout → on failure re-generates with `previousAttempt` + the traceback (≤2 corrections) → writes the content only on PASS, records the verdict and evidence, and marks exhaustion `failed` with the last traceback and the remedy. The batch keeps running when the panel closes or the page reloads; reopening re-attaches to the live progress; a crashed or restarted server leaves the session `interrupted`, never "solving forever", and Retry runs a new execution linked to the interrupted one without replaying anything.

**Why it matters.** Correctness: the deployment's models cannot vouch for a request shape (owner's gemma4 test, 2026-09-08); only execution can. Trust: "Solved 6 of 6" today means "written", not "works". Consistency: Simulation Mode already validates before approving; Solve is the outlier. Decision hygiene: DEC-021 has been "open" through nine memos; this delivers its single-process slice honestly and decides the LangChain re-open condition instead of carrying it.

## 2. Scope

**Included**

- **The verified Solve loop** for data-loading nodes (`source_grounding.is_data_loading_type`): the dev/67-7 round loop extracted from `_validate_events` into ONE function both callers use (`_generate_validated_content`), called by `_solve_one` in write mode (PASS → write; exhaustion → `failed` with evidence; `infrastructure` → stays `pending` with the reason) and in propose mode (the minted `node.content.write` carries the `validation` block the review card already renders).
- **Runner fixes** the loop needs: `run_through_node` payload gains `dataset_paths` (resolved in the request thread by scanning candidate + ancestor code with the existing `_DATASET_PATH_CALL_RE` → `DatasetCatalogService.resolve_execution_paths`) and `user_key`; ONE env-overridable validation exec timeout (`CURIO_VALIDATION_EXEC_TIMEOUT`, default 300 = the sandbox wall clock) replacing the hardcoded 120; measured `duration_ms` in the journal (the 67-7 deviation (2) left it at 0).
- **Detached Solve job** (`agents/solve_jobs.py`, the `build_jobs.py` shape): the batch generator runs in a daemon thread; events append to a bounded per-job log; the SSE handler subscribes, replays, tails; disconnect detaches instead of finishing; a new `POST …/solve/attach` (or `GET …/solve/stream?executionId=`) re-attaches; one live job per attachment.
- **Leases/heartbeats, in-process form** (DEC-021 vocabulary): `builderSession.solveHeartbeatAt` refreshed at every node/round boundary; the stale rule becomes "no heartbeat for `_SOLVE_STALE_SECONDS`"; **startup reconciliation** (app boot + first read of a `solving` session) marks a session with a stale heartbeat whose `solveExecutionId` is not live `phase: "interrupted"` with in-flight `nodeRuns` → `interrupted`; the Solve turn card says so; Retry (Solve over `pending|failed|interrupted`) records `retryOf: <executionId>` on the new execution — never a replay.
- **Manifest**: the Dataflow Builder declares `runtime.execution: "background"` — the unclaimed field becomes true for the one agent whose server path outlives a request; the dock tile projects a running indicator from a live job (docs/11:178's stated projection).
- **Frontend**: strip pills gain `verifying` (per `node_executed`), PASS/FAIL verdict with the stderr tail in a `<details>`, `interrupted` with Retry; the panel re-attaches on mount when `phase === "solving"` and a `solveExecutionId` exists; closing the panel no longer aborts the fetch; the solve overlay reads the same stream.
- **Docs on close** (dev/93 convention): `docs/AGENT-CATALOG.md` (Solve verifies data-loading nodes; background job semantics; the interrupted/Retry story), dev/03 `DEC-073` row + the gate-note flips listed under Backlog, dev/00 index row, BL-P5 entry, `3.1` status lines.

**Must be checked but not changed**

- `validation.validate_candidate` verdict vocabulary (pass / fail{execution-error, upstream-blocker, precondition, type-mismatch} / infrastructure) — reused as-is; a data-loading node has no upstream, so `upstream-blocker` cannot occur for it.
- `delegation.run_delegate` (DEC-046 depth-1) — the child is still synchronous per round; the job wraps the batch, not the seam.
- `_gate_generated_content` (DEC-072) — runs BEFORE execution on every round (a fabricated path never reaches the sandbox).
- `_simulate_events` — already validates; unchanged. `_validate_events` keeps its route; only its round loop moves into the shared function.
- `ledger.reserve` per child — unchanged; the job's children reserve as today.
- `request_solve_cancel`'s dual signal — unchanged; cancellation semantics tighten only in wording (§6).

**Out of scope (explicitly)**

- Multi-instance execution and a durable external queue/lease owner — **OQ-009**, untouched; this memo delivers DEC-021 for the documented single-process topology exactly as OQ-009's default posture says ("support execution only in the documented single-process topology").
- Verifying non-data-loading nodes in Solve — v1 verifies data-loading nodes only ("initially", the owner's word); widening to every kind is a one-line `verifyKinds` change recorded as follow-up F1 (Simulation Mode already verifies all kinds).
- Resident generated services (DEC-064) — unrelated; unchanged.
- Aborting a sandbox execution mid-flight — the sandbox has no cancel endpoint; cancel takes effect at the next node/round boundary, bounded by the exec timeout (recorded, §6).
- Replaying provider or tool calls after interruption — forbidden by DEC-021; Retry regenerates.
- Adopting LangChain/LangGraph (Option B) — specified in §3.9 for the owner's decision, not built under Option A.

## 3. Recommended Implementation Approach

### 3.1 One validation policy, three callers

`_validate_events` (`services.py:4753-4989`) already holds the loop: for `round_index in range(1 + _VALIDATE_CORRECTION_ROUNDS)`: delegate `node.content.generate` (with `previousAttempt` + `validationError` after round 1) → `extract_node_content` → **DEC-072 gate** → threaded `validate_candidate` draining `node_executed` events → break on non-`fail`. Extract it as

```python
def _generate_validated_content(user_key, project_id, *, node_id, spec, inputs, resolution,
                                config, parent_execution_id, parent_coord, attachment_id,
                                solve_ctx, grounding_base, exec_timeout, dataset_paths,
                                emit) -> VerifiedOutcome
# VerifiedOutcome: status ∈ solved|failed|infrastructure, content, verdict, evidence, rounds, children
```

so `_validate_events`, `_simulate_events` (through `_validate_node_inline`) and `_solve_one` share it byte-for-byte. dev/71's "one validation policy, two callers" becomes three; no second loop.

### 3.2 Solve, write mode

In `_solve_one`, after the child's first reply: if `is_data_loading_type(node.type)` (and `verify` is on — a Solve request field defaulting to `true`), the worker runs `_generate_validated_content` instead of returning the raw text. `_record_outcome` receives `VerifiedOutcome`:

- `solved` → content written by `_finish` exactly as today (user-edit guard intact); `results[node] = {status: "solved", verdict: "pass", evidence}`; the journal record already exists (the validation run wrote it with `validation: True`).
- `failed` (exhaustion) → `{status: "failed", error: "<evidence.kind>: <detail> — see the traceback", verdict: "fail", evidence}`; nothing written; the Solve card lists it with the last `stderrTail` (bounded).
- `infrastructure` → `results[node] = {status: "pending", reason: "sandbox unreachable — nothing was verified or written"}`; the node stays `pending` (dev/67-7's rule: infrastructure ≠ content failure), the batch reason names it once (dev/106 shape).

Non-data-loading nodes keep today's path (generate → gate → write) in v1.

### 3.3 Solve, propose mode

The validated candidate goes through the existing `_mint_content_review_from_delegate(local_turn=True)`; the minted part gets `part["validation"] = {verdict, rounds, evidence}` — the field the review card renders since dev/67-7 (`AgentReviewCard.tsx:560-593`, "Apply anyway" styling on fail). No new card.

### 3.4 Runner: the two fixes the loop depends on

- `run_through_node(..., dataset_paths: dict | None, user_key: str | None)`: forwarded into the `/exec` payload the way `/processPythonCode` does (`api/routes.py:371-384`). Resolution happens in the request thread before the pool (`_solve_grounding_base` already lists catalog ids — extend it with `resolve_execution_paths` over the ids scanned from the plan's data-loading nodes; the validation-node route resolves per call). Without this, every dev/114-grounded catalog node fails verification with "unmapped dataset id" — a false FAIL that would teach the model to abandon the catalog form.
- `SANDBOX_EXEC_TIMEOUT_S` → `validation_exec_timeout()` reading `CURIO_VALIDATION_EXEC_TIMEOUT` (default 300, the sandbox wall clock; the 600 s interactive bound stays the upper reference). Timeouts are `infrastructure`? No — a timeout is the candidate's behaviour (an endpoint that hangs): classify `requests.Timeout` as `fail/execution-error` with detail "did not finish within N s" so the model can correct (add a timeout parameter, page the request), while connection errors to the sandbox stay `infrastructure`.
- `record_execution(duration_ms=...)` measured around each exec.

### 3.5 The detached job (`agents/solve_jobs.py`)

Modeled on `packages/build_jobs.py`: `_JOBS: dict[(user_key, attachment_id) → SolveJob]` under one lock; `SolveJob{executionId, thread, events: deque(maxlen=N), subscribers: list[Queue], status, startedAt, heartbeatAt, stop: Event}`. `solve_attachment_stream` becomes: preflight as today → create the job → start a daemon thread running `_solve_events` and pushing every `(kind, data)` into the log and to subscribers → return a subscriber generator. The Flask SSE handler consumes the subscriber; on `GeneratorExit` it **unsubscribes** (no cancel, no `_finish`). `POST …/solve/attach` returns a new subscriber that first replays the log (so a reconnecting client sees `solve_started` … up to now) then tails; a finished job replays and closes. One job per attachment: a second Solve while one is live → 409 (today's in-flight guard, kept). Jobs are in-process by design (like build jobs) — they do not survive a restart, which is exactly what reconciliation (§3.6) is for. `MAX_ACTIVE_SOLVE_JOBS_PER_USER = 2` backpressure.

### 3.6 Heartbeat, reconciliation, linked retry (DEC-021 in-process)

- `builderSession.solveHeartbeatAt` is written by `_solve_events` at every node boundary and correction round (the persist points that already exist), and by a 30 s ticker in the job thread while a sandbox exec is in flight (a 300 s fetch must not look dead).
- Stale rule: `now - solveHeartbeatAt > _SOLVE_STALE_SECONDS` (kept at 15 min as the outer bound) **and** no live job for that `solveExecutionId` → the session is expired nonterminal work.
- **Reconciliation** — `solve_jobs.reconcile_session(spec, record)` runs (a) at app start over every project spec that has a `solving` builder session (a bounded sweep, like `sweep_expired_jobs`), and (b) lazily whenever a `solving` session is read (`_record_or_404` for Solve/strip routes): stale + not live → `phase: "interrupted"`, each `nodeRuns[node] == "solving"` → `"interrupted"`, `session["interruptedAt"]`, `session["interruptedExecutionId"]`, and one transcript turn *"Solve was interrupted (server restart or crash) after N of M nodes — nothing was replayed; Retry continues."* Nothing is re-run automatically.
- **Retry** — the existing Solve entry (`nodeRuns ∈ pending|failed`) also takes `interrupted`; the new execution record carries `retryOf: <interruptedExecutionId>` (the DEC-021 "linked execution"); `_finish` clears the interrupted markers.
- Vocabulary: `interrupted` is reserved for lease expiry (dev/63:111) — a user cancel stays `cancelled`; a sandbox outage stays `pending` + reason.

### 3.7 Manifest and projection

`builtin.py`: Dataflow Builder `execution="background"` (a new `BuiltinAgentSpec` field defaulting to `"foreground"`); `build_builtin_manifest` emits it. The attachments listing gains `liveJob: {executionId, phase, startedAt} | null` for Dataflow Builder attachments (read from the registry), and the dock tile shows the running indicator docs/11:178 promised. No behavior keys off the manifest field beyond the projection — the job is started by the Solve route regardless; the declaration documents it (and a future agent declaring `background` gets the same projection for free).

### 3.8 Frontend

`AgentAttachmentsProvider.solveAttachment` keeps its stream consumption but stops treating unmount/close as cancel; `cancelSolve` remains the explicit cancel. On attachment open (and on page load for the DFB attachment) with `builderSession.phase === "solving"` and `solveExecutionId`, call `solve/attach` and feed the same handler. Strip: `verifying` pill (spinner + "running in the sandbox…"), verdict badge, `interrupted` pill with Retry, "Solve continues if you close this panel" copy on the live overlay. The review card is unchanged (it already renders `validation`).

### 3.9 The LangChain decision (DEC-048's re-open condition) — Option B, specified for the owner's choice

DEC-048 recorded ONE re-open condition: *"background/long-running orchestration (DEC-021), through the `delegation.py` seam."* This memo triggers it, so it must be decided, not skipped.

**What Option B would be.** A `langgraph` `StateGraph` for the verified Solve loop — nodes `generate → gate → validate → correct → finalize`, `interrupt()` for review pauses (propose mode), a `SqliteSaver`/`PostgresSaver` checkpointer keyed by `(attachment_id, execution_id)` so a restarted server resumes with `graph.invoke(None, config)` from the last checkpoint instead of marking the session `interrupted`. The adapter sits behind `delegation.py` (DEC-046/048) and calls the provider port for every model turn — **no LangChain LLM wrappers or tool-calling abstractions**, because our model contract is the `curio.v1` tail on weak local models (DEC-063/067), and LangChain's tool-calling path assumes function-calling-capable models. Dependencies: `langgraph`, `langgraph-checkpoint-sqlite` (pinned per dev/03:166's gate). Tests: graph-level doubles plus the same route suites.

**Why Option A is recommended for this slice.**
1. Every seam Option A needs already exists and is tested: `run_through_node`, `validate_candidate`, the 67-7 round loop, `build_jobs.py`'s registry shape, the dev/63 SSE envelope, the persisted `builderSession`. The port is ~600 lines of direct code and zero new dependencies.
2. LangGraph's distinctive payoff — durable checkpoint/resume across restarts — buys little here: the correction loop is three bounded steps whose only expensive state is a sandbox run that cannot be checkpointed anyway (the fetch re-runs), and provider calls must not be replayed (DEC-021). "Interrupted + linked Retry" is the honest resume for this loop.
3. A checkpoint store would be a **second source of truth** beside `builderSession` in the spec (DEC-040: attachments live in the spec) — every read would need reconciliation between them, the exact class of bug dev/106 fixed for the install proposal.
4. Multi-instance (the case where an external durable store earns its keep) is OQ-009, open and deployment-gated; adopting the store before the topology is decided pre-empts OQ-009.
5. The weak-model posture: LangGraph adds a framework between the loop and the provider; the corrective feedback (`previousAttempt` + traceback) is already the self-correcting mechanism DEC-067 demands and works without it.

**Criteria that would make Option B the right call (recorded for re-open, the DEC-056/064 pattern):** OQ-009 resolves to multi-instance (a durable owner is then required anyway); or a second long-running orchestration needs cross-restart resume with re-usable intermediate state (e.g., whole-plan verification with cached upstream outputs); or the correction loop grows beyond a fixed three steps into a graph with branches the current straight-line code cannot express. Any one of these re-opens with its own memo; the seam and the contract (dev/05 §10) remain the recorded design.

## 4. Data and State Handling

- **Source of truth**: `builderSession` in the saved spec (phase, `nodeRuns`, `solveExecutionId`, `solveHeartbeatAt`, `interruptedExecutionId`, `retryOf` on execution records); the in-process job registry is a cache of liveness + the event log, never authoritative — a missing job with a fresh heartbeat means "another thread of this process is running it" (no action); a missing job with a stale heartbeat means interrupted.
- **Derived**: per-node pill state = `nodeRuns[node]` ∪ live events; verdicts ride `results[node]` and the Solve card; `liveJob` on the attachment listing derives from the registry.
- **Loading / empty / error**: a reattach to a finished job replays and closes; to an unknown `executionId` → 404 with the session's current phase; sandbox unreachable → `pending` + reason (never `failed`); catalog unavailable → the dev/114 gate refuses before execution (already).
- **Updates after actions**: Retry clears `interrupted*`, sets a new `solveExecutionId`, records `retryOf`; cancel → `cancelled` at the next boundary; PASS writes content + `nodeRuns[node] = "solved"`; FAIL leaves content empty + `failed` + evidence.
- **Stale/duplicates/race**: one job per attachment (409 otherwise); `_finish` stays idempotent; writes re-guard against the current spec (user edit wins); the heartbeat ticker and the node-boundary persist both write the spec — serialize under the existing per-project spec write (they touch one session field; the ticker reads-modifies-writes the session only).
- **Budgets**: `_SOLVE_MAX_WORKERS = 3` bounds concurrent sandbox runs; per-node worst case = 3 rounds × 300 s; the event log is bounded (`deque(maxlen=2000)`); jobs are swept 15 min after completion.

## 5. UI and UX Requirements

- Strip pills: `pending` → `generating` → `verifying` (sandbox run, elapsed seconds) → `solved ✓ (verified)` | `failed ✗` (verdict kind + one-line detail; stderr tail in `<details>`) | `pending — sandbox unreachable` | `interrupted` (Retry). Counts: "Solved 4 of 6 · 1 failed · 1 interrupted".
- Live overlay copy: "Solve keeps running if you close this panel." Reopen shows the same progress (reattach). Cancel copy: "Cancel — stops after the current node finishes (a running fetch cannot be aborted)."
- Dock tile: a running dot while a Solve job is live for that attachment (docs/11:178).
- Review card (propose mode): unchanged PASS/FAIL block; "Apply anyway" on fail (dev/67-7 — never hidden).
- Interrupted turn in the transcript: plain statement + Retry suggested prompt/button on the strip; never says "replayed".
- Accessibility: pill states as text (never colour alone); `aria-live="polite"` region for progress already exists in the strip — extend with the verifying/verdict words; details disclosure keyboard-operable; the running dot has an `aria-label`.
- No layout shift: pills keep their geometry across states; the stderr `<details>` is collapsed by default.

## 6. Edge Cases

- **Panel closed mid-fetch / page reload**: job continues; reattach replays. **Server restart mid-batch**: heartbeat stops → reconciliation → `interrupted`; content written for already-solved nodes stays (`_finish` per node? — no: `_finish` is one batched write; see below).
- **`_finish` is one batched write today**: if the process dies before `_finish`, solved nodes' content is lost with the batch. Decision: keep the single write for `write` mode but persist each PASS node's content **incrementally at the node boundary** (guarded like `_finish`) so an interruption keeps verified work — the no-replay posture requires that a verified fetch is not thrown away. `_finish` then only reconciles statuses.
- **Sandbox down at start**: every data-loading node → `pending` + one batch reason (dev/106 shape); non-data-loading nodes proceed.
- **Fetch hangs**: exec timeout → `fail/execution-error "did not finish within 300 s"` → correction round (the model adds a timeout/limit) → exhaustion `failed`.
- **HTTP 400/401/404 at run time**: a Python exception (requests raise_for_status) or an empty output → `execution-error` with the traceback → correction with `previousAttempt` — the owner's Census case becomes a fixable round, not a broken node; the DEC-072 gate still refused it earlier if the base URL itself was dead.
- **Type mismatch with a downstream consumer**: `fail/type-mismatch` (dev/67-7) → correction round names the expected type.
- **Cancel during a run**: honoured at the next boundary; the running exec finishes (≤ timeout) and its result is discarded (`cancelled`), never written.
- **Two tabs**: both reattach to the same job (subscribers); a second Solve → 409.
- **Catalog id unmapped** (dataset deleted between gate and run): the sandbox's per-id error → `execution-error` naming the id → correction; the gate would refuse on the next round since the id is no longer listed.
- **Heartbeat ticker vs. spec write races**: the ticker only touches `solveHeartbeatAt`; node-boundary writes re-read the spec (existing pattern).
- **Legacy sessions** created before this memo: no `solveHeartbeatAt` → treated by the old 15-minute `solvingSince` rule once, then upgraded.
- **`verify: false`** (explicit request field): the old unverified write path, kept for automation/tests; the strip never exposes it in v1.

## 7. Testing Strategy

Deterministic providers (the `testing` provider / scripted replies), `runner._http_exec` monkeypatched (the `TestSimulationDriver` fake), no network.

- **Unit — `test_solve_jobs.py`** (new): registry create/get/subscribe/replay/detach/finish/sweep; one job per attachment; backpressure; `reconcile_session` — fresh heartbeat + no job → untouched, stale + no job → `interrupted` with markers, stale + live job → untouched; legacy session without heartbeat.
- **Unit — `test_validation.py`**: timeout classification (`requests.Timeout` → `fail/execution-error`; connection error → `infrastructure`); `dataset_paths`/`user_key` forwarded in the payload; measured `duration_ms`.
- **Unit — runner**: `validation_exec_timeout()` env override.
- **Integration — `test_routes.py`** (new classes):
  1. **Verified Solve PASS**: a data-loading plan node whose child returns a catalog `curio_dataset_path` loader; fake exec passes → `solved` with `verdict: pass`; content written; the exec payload carried `dataset_paths` for the id.
  2. **FAIL → correct → PASS**: fake exec fails on the first content (traceback), the second child call receives `previousAttempt` + `validationError`, passes → `solved`, `rounds == 2`.
  3. **Exhaustion**: three failing rounds → `failed` with `evidence.stderrTail`; content empty; Solve card line carries the kind.
  4. **Infrastructure**: `_http_exec` raises ConnectionError → node `pending` with the batch reason; sibling computation node solves unverified as today.
  5. **Propose mode**: the minted review carries `validation.verdict`.
  6. **Detach/reattach**: start a streamed Solve, drop the client after `node_started`, assert the job continues to `done`; `solve/attach` replays `solve_started … done`.
  7. **Cancel at boundary**: cancel while a node is in flight → that node `cancelled`, nothing written for it.
  8. **Reconciliation + linked retry**: write a `solving` session with a stale heartbeat and no job → the strip/session read returns `interrupted`; Solve again → new `executionId`, `retryOf` set, no provider call replayed (call count asserted).
  9. **Incremental persistence**: after node A passes and the job is killed (stop event) before B, A's content is in the spec.
  10. **`verify: false`** keeps the legacy write path (byte-identical results to today's tests).
  11. **Manifest**: DFB `runtime.execution == "background"`; every other built-in `foreground`; attachments listing carries `liveJob` while a job runs.
- **Jest**: strip pill states (`verifying`, verdict, `interrupted` + Retry), reattach on mount (mocked `solve/attach`), close-panel-does-not-cancel, dock running dot, cancel copy.
- **Required before complete**: 1–11, the unit suites, full `test_agents` and jest green, `tsc` unchanged.

## 8. Acceptance Criteria

1. Solving a plan with a data-loading node runs the generated code in the sandbox before the node is marked solved; a node is `solved` only on PASS.
2. A failing run is fed back to the content generator (traceback + previous attempt) up to two corrections; exhaustion shows `failed` with the traceback tail and the node stays empty.
3. Closing the chat panel or reloading the page while Solve runs does not stop it; reopening shows live progress from where it is.
4. Restarting the server mid-Solve leaves the session `interrupted` (never "solving" forever); Retry creates a new linked execution and replays no provider or tool call; verified nodes completed before the restart keep their content.
5. A sandbox outage marks affected nodes `pending` with one stated reason, never `failed`.
6. Cancel stops at the next node boundary and says so; the running fetch's result is discarded.
7. `curio_dataset_path("<id>")` loaders (dev/114) verify successfully — the validation runner resolves ids like Play does.
8. A fetch that hangs fails after the configured timeout with a correctable message; the timeout is one env-overridable constant aligned to the sandbox wall clock.
9. The Dataflow Builder manifest declares `background`; its dock tile shows a running indicator while a job is live.
10. Propose-mode Solve review cards carry the verdict; Simulation Mode and `validate-node` behave exactly as before (shared loop, no behaviour change).
11. The DEC-048 re-open condition is recorded as decided (DEC-073) with Option B's adoption criteria; no LangChain dependency is added under Option A.

## 9. Recommended Commit Breakdown

- **Commit 1 — runner + shared loop.** `run_through_node(dataset_paths, user_key)`, timeout constant + classification, measured duration; `_generate_validated_content` extracted, `_validate_events` and `_validate_node_inline` on it; tests.
- **Commit 2 — verified Solve.** `_solve_one` / `_record_outcome` / propose mode over the shared loop for data-loading nodes; `verify` request field; incremental PASS persistence; Solve card lines; route tests 1–5, 9, 10.
- **Commit 3 — detached job + reconciliation.** `solve_jobs.py`, stream/attach routes, heartbeat ticker, reconciliation at boot and on read, linked Retry; tests 6–8 + unit.
- **Commit 4 — manifest + frontend.** DFB `background`, `liveJob` projection, strip states, reattach, dock dot; jest; test 11.
- **Commit 5 — docs.** `docs/AGENT-CATALOG.md`, DEC-073 row + DEC-021/048/050/REQ-RUNTIME-002 gate-note flips, index, BL-P5 entry, `3.1`, memo status.

Multi-session protocol applies (pathspec commits; `git status` before every add; `git branch --show-current` must read `imp/agentcatalog`).

## 10. Engineering Quality Checklist

- [ ] ONE validation loop (`_generate_validated_content`) — `validate-node`, Simulation Mode, and Solve call the same function; no second round loop.
- [ ] The DEC-072 gate runs before every sandbox execution; execution never substitutes for grounding.
- [ ] Infrastructure ≠ content failure: sandbox outages leave nodes `pending`; only the candidate's own behaviour can `fail` it.
- [ ] No provider or tool call is ever replayed; Retry is a new execution with `retryOf`.
- [ ] `builderSession` stays the single source of truth; the job registry is liveness + event log only.
- [ ] Verified content is persisted at the node boundary so an interruption never discards a passing fetch.
- [ ] `interrupted` is reserved for expiry; user cancel stays `cancelled`; a sandbox outage stays `pending`.
- [ ] Bounded everything: workers, rounds, exec timeout, event log, jobs per user, sweep TTL.
- [ ] a11y: states in text, live region, keyboard-operable details, labeled running dot.
- [ ] DEC-048's re-open condition is decided in the record (DEC-073), with Option B's criteria — never carried silently.

## Open questions for the owner (non-blocking — defaults stated)

- ~~Option A or Option B (§3.9)?~~ **Decided 2026-09-08: Option A.** LangGraph recorded with adoption criteria (§3.9); dev/03:166's pin gate stays dormant.
- ~~Verify every node kind in Solve, or data-loading only for v1?~~ **Decided 2026-09-08: data-loading only**; F1 widens by one constant.
- **Exec timeout default**: default **300 s** (the sandbox wall clock); 600 s would match the interactive route but a 3-round loop then blocks a worker for 30 min.
- **Should the Dataflow Builder manifest flip to `background`** or should the field stay untouched until a second background agent exists? Default **flip** — the field was reserved for exactly this and the dock projection is specified.

## Follow-ups (recorded, not delivered)

- **F1** Widen verified Solve beyond data-loading nodes (`verifyKinds`); expect longer batches — revisit `_SOLVE_MAX_WORKERS`.
- **F2** OQ-009: multi-instance execution and a durable lease/queue owner; the re-open path to Option B if the criteria in §3.9 are met.
- **F3** Sandbox-side cancellation of an in-flight execution (a `/cancel` on the supervisor) so cancel is immediate.
- **F4** Output-schema evidence (column metadata) in the verdict when the runtime journal captures it (dev/67-7 follow-up, still open).
- **F5** Mint-time execution for Node Builder proposals (dev/114 F1's other half) — an opt-in "verify before proposing" on `node.create`, using the same loop.


## Amendment A1 (2026-09-08) — the guarantee covers every offered data-loading node, not Solve alone

Owner clarification (2026-09-08): *"the suggested and solved data loading nodes should never output failing code; the solved outputs should always run in the background, check the errors (under a collapsed list in the corresponding attached node builder → dataset finder agents) in the node review card, properly fix them, and try again. The main goal of this task should be to output correctly aligned, precise code when the user clicks apply."*

The original §3 verified Solve only. A Node Builder `node.create` that follows a Dataset Finder suggestion — the path dev/114 grounded — still minted a proposal nobody had run. This amendment extends the same machinery to proposals; nothing in §3.1–§3.8 is withdrawn. dev/115 F5 ("mint-time execution") moves INTO scope.

### A1.1 The proposal contract gains a verification stage

A data-loading `node.create` / `node.content.write` (and a Solve `propose`-mode review) is minted exactly as today, plus:

```json
"verification": {
  "state": "running" | "passed" | "failed" | "infrastructure" | "not-required",
  "jobId": "…", "startedAt": "…", "finishedAt": "…",
  "rounds": 2,
  "attempts": [
    {"round": 1, "contentSha256": "…", "verdict": "fail", "kind": "execution-error",
     "detail": "HTTPError: 400 Client Error …", "stderrTail": "…",
     "by": "agent.node-builder@1.0.0", "correctedBy": "agent.node-content-builder@1.0.0",
     "evidence": {"url": "https://api.census.gov/data/…", "verification": {"status": "unreachable", "httpStatus": 400}},
     "changeSummary": "added the required `get`/`for` parameters; timeout 30 s"},
    {"round": 2, "contentSha256": "…", "verdict": "pass", "kind": "executed",
     "outputDataType": "dataframe", "rows": 77, "durationMs": 4120}
  ]
}
```

- `state: "not-required"` is stamped on every non-data-loading proposal (byte-identical behaviour to today; the card shows nothing).
- The **stored proposal's `content`** and the transcript part's `preview` are updated to the LAST candidate (the one that passed) — the user reviews the code that actually ran. The one sanctioned turn edit (`sessions.update_proposal_status`, dev/41 "changes proposal state, never text") is widened by one sibling helper, `sessions.update_proposal_verification(...)`, that writes `verification` + `preview` on the persisted part; both are runtime-only writers.
- `changeSummary` is model-authored (the correction child's one-line statement of what it changed), bounded, rendered inert; the verdict, kind, detail, stderr tail, evidence, and hashes are runtime facts.

### A1.2 Apply is gated on `passed`

`apply_proposal` refuses a data-loading proposal whose `verification.state` is `running` (409 `verifying` — "the code is still being run; wait for the verdict") or `failed` (409 `unverified`) unless the request carries `applyUnverified: true`. The card renders **Apply** enabled only on `passed`; on `failed` and `infrastructure` it shows the trail and two actions: **Retry verification** (a new job, linked by `retryOf`) and the secondary, explicitly labeled **Apply unverified** — kept because dev/67-7 recorded that a failing result is labeled, never hidden, and a sandbox outage must not lock the user out of their own node. Default posture: enabled only after PASS; the override is a visible exception, not the path.

### A1.3 The loop runs in the background, from the mint

`_mint_node_create` / `_mint_node_content_write`, when `is_data_loading_type(entry)` and the DEC-072 gate passed, stamp `verification.state = "running"`, store the proposal, and start a **verification job** (`agents/verify_jobs.py`, the same registry shape as §3.5 — one module `agent_jobs.py` with two job kinds is preferred over two registries) keyed by `proposalId`. The chat turn returns immediately with the card in its `verifying` state; the model is told *"proposal X created and is being verified in the sandbox — do not claim it works; the card reports the verdict"*. The job:

1. resolves `dataset_paths` for the candidate (§3.4) and runs `validate_candidate` on a spec overlay (for `node.create`, a temporary one-node slice: the node does not exist yet, so the runner receives the candidate as a synthetic node of the proposed template with no upstream — a `run_candidate_standalone` variant of `run_through_node`; for `node.content.write`, the existing overlay on the real node);
2. on `fail`: builds the correction inputs — `previousAttempt`, `validationError` (stderr tail), the DEC-072 `sourceGrounding`, and **fresh DEC-053 evidence for any URL the traceback names** (`verify.verify_external_source` over the failing request's constant prefix, budgeted) so an HTTP 400/404 correction is grounded in a probe, not a guess — and delegates `node.content.generate` to the Node Content Builder **homed at the proposing attachment** (dev/72 `_delegation_home`: the node's Node Builder when the node exists, else the parent attachment), so the child turns land under the Node Builder's chat as today; a Dataset Finder suggestion that led here stays linked through the dev/72 delegation entry on the finder's turn;
3. gates the corrected candidate (DEC-072), re-runs, records the attempt; ≤ `_VALIDATE_CORRECTION_ROUNDS` corrections (2) → `passed` with the final content, or `failed` with the full trail; sandbox unreachable → `infrastructure` (nothing corrected, nothing claimed);
4. persists `verification` on the stored proposal and the transcript part after every round (a page reload mid-verification shows the live trail), heartbeats like a Solve job, and pushes `proposal_verification` events on the attachment's job stream (§3.5's attach channel, generalized to `GET …/attachments/<id>/jobs/stream`).

Solve `write` mode records the same `attempts` list per node on `results[node]` and the Solve card's `<details>`; Solve `propose` mode mints the review with the trail already complete.

### A1.4 Who fixes what — visible

The collapsed **"Verification · N attempts"** block on the review card lists each round as one line — `Round 1 · fail · HTTPError 400 … · fixed by Node Content Builder: added the required parameters` — with the stderr tail in a nested `<details>`, and the final `Round N · pass · dataframe, 77 rows, 4.1 s`. The dev/72 delegation entries under the Node Builder's turn link to the child chats where each correction ran, so the "Node Builder → Dataset Finder" chain the owner named is navigable: the finder's turn carries the candidates and the hand-off, the builder's turn carries the proposal with its attempts, and each correction round is a homed child turn. `by`/`correctedBy` are agent coordinates, rendered as names.

### A1.5 What this adds to §2 (Included) and §7/§8

- New: `agent_jobs.py` (Solve jobs + verification jobs), `sessions.update_proposal_verification`, `apply_proposal` gating + `applyUnverified`, `run_candidate_standalone` in the runner, the correction inputs' URL-probe enrichment, `verification` on proposal parts/stored proposals, the card's attempts block and gated Apply, `proposal_verification` job events, the mint's immediate-return posture.
- Tests (added to §7): **12.** a data-loading `node.create` mints with `verification.state = "running"` and the run body says so; the job passes → part/proposal carry `passed`, Apply succeeds. **13.** first run fails (fake exec traceback with HTTP 400), the correction child receives `previousAttempt` + `validationError` + fresh URL evidence, the second run passes → `attempts` has two rows, `preview`/`content` are the corrected code, `changeSummary` recorded. **14.** exhaustion → `failed`; `apply` → 409 `unverified`; `applyUnverified: true` applies; **Retry verification** starts a linked job. **15.** `infrastructure` → nothing corrected, Apply gated, Retry offered. **16.** a non-data-loading proposal carries `not-required` and behaves byte-identically to today's tests. **17.** reload mid-verification: the session shows the running trail; the jobs stream replays `proposal_verification` events. **18.** `node.content.write` on an existing data-loading node verifies on the overlay. Jest: card `verifying` state with disabled Apply; attempts block collapsed by default, rows inert; `failed` shows Retry + labeled Apply unverified; `passed` enables Apply.
- Acceptance (added to §8): **12.** A data-loading proposal's Apply button is disabled until the runtime reports PASS; the card says what is running. **13.** Every attempt is listed under a collapsed block with the error, the evidence, and who fixed it; the code shown on the card is the code that passed. **14.** Applying a passed proposal puts the exact verified content on the canvas. **15.** Exhaustion or a sandbox outage never presents failing code as ready: Apply is gated, Retry is offered, and the override is explicitly labeled unverified.

### A1.6 Edge cases added

- The user edits the target node while a `node.content.write` verification runs → the existing `contentSha256` pin makes Apply refuse 409 + stale (unchanged); the job's later verdict is stamped anyway (history), the card shows stale.
- The proposal is dismissed or superseded while verifying → the job stops at the next boundary; `verification.state` is left as it was with `finishedAt`; nothing else changes.
- Two data-loading proposals in one reply (a note-sequence-style batch is not possible for data-loading today; if it becomes so) → one job per proposal, backpressure `MAX_ACTIVE_JOBS_PER_USER`.
- Correction changes the template? Never — the child returns content only; `nodeType` is pinned at mint.
- The corrected content changes its sources (a new URL) → the DEC-072 gate runs on every round; a fabricated path in a correction is refused and counts as a failed round with the refusal as `detail`.
- Verification of a fetch that legitimately needs a credential (401/403) → `execution-error` with the status; the correction child is told the endpoint is credential-gated (DEC-072 evidence) and should surface the requirement in the node rather than loop; after exhaustion the card's trail says so.

### A1.7 Commit plan adjustment

Commit 2 becomes "verified Solve + verified proposals" (shared loop, both callers); commit 3 is the generalized `agent_jobs.py` + attach stream + reconciliation for both job kinds; commit 4 adds the card's attempts block and gated Apply. Five commits still.


## Amendment A2 (2026-09-08) — the trigger is the user's Solve, not the mint and not Apply

Owner correction (2026-09-08): *"the background engineering loop harness to output the correct code is not before the user asked to apply it — it should be after it asks to solve it."*

**Withdrawn from A1:** A1.2 (Apply gated on `passed`, `applyUnverified` override) and A1.3 (a verification job started by the mint; `verifying` cards; the immediate-return posture). Proposals are minted exactly as today — the DEC-072 static gate is the only pre-Apply check — and Apply places the node with the proposed content. A1.1's `verification` record, A1.4's trail, A1.5's jobs machinery, and A1.6's edge cases stand, re-homed as below.

### A2.1 Two Solve entry points, one loop

1. **Dataflow Builder Solve** (the strip; §3.2/§3.3 unchanged): for each pending data-loading plan node, generate → gate → execute → fix → re-run → write on PASS (write mode) or mint the executed review (propose mode).
2. **Per-node Solve on a data-loading node** — the Node Builder side. The applied `node.create` review card (its `applied` state) and the node's Node Builder chat (the attachment strip that already exists for dev/71's per-row Solve → `validate-node`) expose **Solve**. It starts the same detached job for that node (`POST …/attachments/<id>/solve-node {nodeId}` → `agent_jobs`), which:
   - **round 0 executes the node's CURRENT content as-is** (the code the user just applied) — no regeneration first: if it passes, the outcome is "verified, no change" and nothing is written;
   - on `fail`: corrects through `node.content.generate` with `previousAttempt`, `validationError`, `sourceGrounding`, and fresh DEC-053 evidence for any URL the traceback names (A1.3 step 2), re-gates, re-runs — ≤ `_VALIDATE_CORRECTION_ROUNDS` corrections;
   - lands the result **as a reviewed `node.content.write` proposal that has already passed** (the dev/67-7 contract: an existing node's content changes only through review — DEC-006), carrying `verification` with the full trail and the final code; the user's Apply on THAT card applies code that ran. A node still empty (a plan placeholder solved from its own agent) is written directly on PASS, as DFB Solve does.
   - exhaustion → no proposal; the node's Node Builder chat gets a Solve turn card with the trail and the last traceback; the node badge reads `failed verification`; Retry (linked) is offered. `infrastructure` → `not verified — sandbox unreachable`, nothing corrected.

### A2.2 What "verified" is, and where it lives

No new state store. A node is **verified** when its latest runtime-journal record (dev/67-2, `runtime_journal.read_record`) is a passing run of its CURRENT content (`executedCodeSha256 == sha256(node.content)`, `status ok`). The node badge and the Node Builder card derive `unverified — Solve to run it` / `verified ✓` / `failed verification` from that record plus the live job; nothing is stamped on the spec node (dev/114 F3 stays). The `verification.attempts` trail (A1.1 shape) rides the Solve turn card, the minted `node.content.write` part, and `results[node]` on the batch payload — never the original `node.create` part (history is not rewritten; the one sanctioned turn edit stays status-only, so `sessions.update_proposal_verification` from A1.1 is withdrawn).

### A2.3 Copy and controls

- Review card of a data-loading `node.create`: Apply as today; a one-line note under the effect line — *"Applying adds the node as proposed; Solve runs it in the sandbox and fixes errors before its code is trusted."* After Apply, the card offers **Solve** (and the node badge shows `unverified — Solve to run it`).
- Solve turn card (both entry points): `Round 1 · fail · HTTPError 400 … · fixed by Node Content Builder: added the required parameters` … `Round N · pass · dataframe, 77 rows, 4.1 s` in a collapsed `<details>`; the `node.content.write` card carries the same block above its preview and its effect line reads *"Applying replaces the content with the version that ran successfully."*
- Nothing ever says a node works until a passing run is on record; a Solve card for exhaustion says *"Not fixed after 3 attempts — last error: …"*.

### A2.4 Contract deltas against §3/§7/§8

- `_generate_validated_content` gains a `start_from_current: bool` (round 0 executes existing content) — still ONE loop, four callers.
- Routes: `POST …/solve-node` (detached; SSE via the jobs stream), no changes to `validate-node` (kept for Simulation Mode and dev/71 rows).
- `apply_proposal` unchanged (no gating). `agent_jobs.py` carries two job kinds: `solve-batch`, `solve-node`.
- Tests (replacing A1.5's 12–15): **12.** applying a data-loading `node.create` places the node unexecuted; the badge reads unverified; the card offers Solve. **13.** per-node Solve, round 0 passes → "verified, no change", journal record present, no proposal. **14.** round 0 fails with an HTTP 400 traceback → correction child gets `previousAttempt` + `validationError` + fresh URL evidence → round 1 passes → a `node.content.write` proposal with `verification.attempts` (2 rows) and the corrected preview; Apply writes it; the node is verified. **15.** exhaustion → no proposal, Solve card with the trail, badge `failed verification`, Retry starts a linked job. **16.** `infrastructure` → badge `not verified — sandbox unreachable`, nothing corrected. **17.** reload mid-job → the jobs stream replays; the node's Node Builder chat shows the running Solve. **18.** a plan placeholder solved from its own Node Builder is written directly on PASS (parity with DFB Solve). Jest: card note + Solve action after Apply; badge states; Solve card's collapsed trail; content-write card's trail and effect line.
- Acceptance (replacing A1.5's 12–15): **12.** Apply never executes code and is never blocked by verification. **13.** After the user asks to Solve a data-loading node, the node's code has run in the sandbox; only code that passed lands — directly in an empty node, or as an executed content review for a node that had content. **14.** The error-and-fix trail is on the Solve card and the content review, collapsed, with who fixed what. **15.** A node whose current content has no passing run says so; one that failed says so; nothing implies it works.

### A2.5 Commit plan (final)

- **Commit 1** — runner fixes + shared loop (`start_from_current`). **Commit 2** — DFB Solve verified (write/propose). **Commit 3** — `agent_jobs.py` (both kinds), `solve-node` route, jobs stream, heartbeat, reconciliation, linked Retry. **Commit 4** — manifest `background`, frontend: badge states, card note + Solve action, Solve card trail, content-write trail, reattach, dock dot. **Commit 5** — docs, DEC-073, ledgers.


## Amendment A3 (2026-09-08) — field-validation scenarios for the harness (owner's gemma4 tasks)

The owner's 2026-09-08 gemma4 test (our sage server and Hugging Face, identical results: *"Gemma4 seems to struggle with web searches and providing links"*) is the acceptance bar for this harness. Each task becomes a recorded scenario, run live by the owner after each commit lands and mirrored by a deterministic route test:

| Task | Owner's prompt | gemma4 result outside Curio | What the harness must make happen inside Curio |
|---|---|---|---|
| **1 · Dataset Finder** | "Find datasets related to population, economy, IDH, vulnerability index and total area of the community areas in Chicago. Output the link for the datasets to the user." | 4 of 5 links broken | Every external row is probed (DEC-053); broken links render `Unreachable ✗` with the status, never as usable; the catalog lane shows real installed datasets (dev/114); the hand-off card carries the verdicts; a Node Builder confirmation over a broken link is refused by the DEC-072 gate with the status named. **Pass = no unverified link is ever presented as a source.** Deterministic mirror: `TestVerifiedDiscovery` + dev/114's `TestExternalDiscovery` (4 of 5 probes → 404). |
| **2 · Dataflow Planner** | "I want to compare population, economy, IDH, vulnerability index and total area of the community areas in Chicago. I already got some data to be used, so I want you to help me structure the dataflow and generate good analysis insights. Output the dataflow structure." | A long generic JSON of "agent personas", no real tools | The Dataflow Builder mints ONE typed `dataflowPlan` over the project's real template vocabulary (dev/93) or a correction round names what was wrong (dev/54); "I already got some data" grounds the data-loading placeholders in the catalog (`sourceGrounding`); Solve then runs the loop of this memo. **Pass = a reviewed plan whose data-loading nodes solve to executed code.** Mirror: `TestDataflowPlanMint` + the §7 Solve cases. |
| **3 · Node Builder** | "Generate code to author a fetch node for US Census Bureau — endpoint https://api.census.gov/data, format JSON, requesting economy and vulnerability indicators (ACS) for Chicago community areas." | Code that throws HTTP 400 | The proposal passes the DEC-072 gate (the base endpoint is reachable); the user applies it; **Solve** runs it: round 0 fails with the 400 traceback, the correction child receives the traceback + a fresh probe of the failing request + `sourceGrounding`, round 1 (or 2) passes → an executed `node.content.write` review with the two-row trail. **Pass = the code the user applies from that review returns a dataframe; a 400 is never the user's discovery.** Mirror: §A2.4 test 14 (fake exec: first content → `400 Client Error` traceback, corrected content → pass). |

The owner runs the three prompts live against the deployed gemma4 after commit 4 and again at closure; the results are recorded in the BL-P5 entry beside the deterministic counts. A live failure that the deterministic mirror did not predict is a new fixture, not a prompt tweak (dev/54 doctrine).

### A3.1 Live results (2026-09-08, gemma4 on the sage server, `curio start` stack, driven through the HTTP API)

Each task was run repeatedly; every harness failure the deterministic mirror had not predicted became a fixture and a fix on `imp/agentcatalog` (dev/54 doctrine). The provider key lived only in the launcher's command line — never in a file, memo, or commit.

| Task | Live outcome after the fixes | Harness failures found on the way (all fixed, all pinned by tests) |
|---|---|---|
| **1 · Dataset Finder** | Catalog lane: the project's real installed datasets. External lane: 4 rows — 1 `verified 200` (data.cityofchicago.org), 2 `unreachable 404`, 1 `refused — the per-run egress budget of 4 requests is spent` (the api.census.gov row). No unverified link was presented as a source. **Pass.** | (a) gemma4 emits the `datasetCandidates` block mid-reply and closes with a `suggestedPrompts` block — or with a block that is not valid JSON; `extract_content` dropped the valid candidates in both shapes → earlier valid display blocks now merge with a valid terminal block and survive a broken one (`cb0332e9`, `TestDecoratedDisplayParts`). |
| **2 · Dataflow Planner** | ONE typed `dataflowPlan` of 8 nodes / 9 edges over the real vocabulary (gemma4 needed DEC-067 correction rounds for the `data-pool` input arity and got there). Applied; verified Solve: the boundaries loader **passed** (executed through `curio_dataset_path("<id>")` against an installed dataset, 1 round); the socio-economic loader ended `source-missing` — *"the content builder declined: No dataset in the provided catalog matches the intent…"* — nothing written, the remedy names what to supply; the six non-loading nodes solved as before. **Pass** (a reviewed plan whose data-loading nodes either execute or decline truthfully). | none new beyond Task 3's. |
| **3 · Node Builder** | Proposal grounded on the verified base endpoint; applied; per-node Solve: round 1 ran the current code and failed (`JSONDecodeError` — the composed request 302-redirects to `api.census.gov/data/missing_key.html`, an HTML page titled "Missing Key", header `X-DataWebAPI-KeyError: 1`); the correction was handed the composed request's real answer and **declined in one line naming the missing input**: *"The US Census Bureau API requires an API key to fetch data; the request resulted in a 'Missing Key' error page."* The loop stopped there (2 rounds), the attempt trail carries the endpoint line, the card's error says what to supply. **Pass, re-read:** the A3 criterion "the applied code returns a dataframe" is unattainable without a key the user never supplied; the truthful outcome is that the 400/HTML answer is never the user's discovery and the missing key is named. | (b) the runner never presented `CURIO_SANDBOX_TOKEN` → every round was `infrastructure · 401 UNAUTHORIZED` under `curio start` (invisible to the unit suites, which fake `_http_exec`; a gap since main's `d8cbeb87`) → `execution/sandbox_auth.py`, one helper for the bridge and the runner, a 401 names the disagreement (`0b99b99e`, `TestSandboxSharedSecret`). (c) a URL the gate verified BY PROBE never reached the correction's `verifiedUrls`, so the builder rightly declined and the gate then refused its prose as "no grounded source", twice; (d) the model's `try/except` returned an empty frame, so the only error was DuckDB's "need at least one column" — no `http` marker, no URL evidence; (e) probing the base URL (200 JSON) said nothing about the composed request; (f) the decline was re-asked with identical inputs → all in `421c95c6`: gate-verified URLs join the context's map; a data-loading failure probes the request composed from literal `url + params` first (`source_grounding.composed_requests`), composed probes are evidence never sources; `verify` outcomes carry `finalUrl` / `pageTitle` / `bodySample`; every failed attempt records `endpointEvidence` (review card + Solve card lines); a one-line prose decline is kind `source-missing`, recorded in the builder's words, terminal, with its own remedy; the content prompt forbids catch-and-return-empty loaders and tells the builder to decline on a key/sign-in page (`TestFieldFixes20260908`, `TestComposedRequests`, verifier redirect tests, jest "Endpoint:" row). |

**Findings recorded, not built (follow-ups F6–F7):**
- **F6 — the egress budget starves the last candidate row.** *(Partly answered by dev/116 `ab87e8fb`, 2026-09-09: the verified Solve loop now owns a budget sized for all its rounds — the run-wide 4 had starved every correction of its evidence in the live Census run; the Dataset Finder's per-candidate starvation below is still open.)* `MAX_CALLS_PER_RUN = 4` is charged per hop (correctly), so one redirect among four external rows leaves the fourth row `refused — budget spent`. Honest, but the user reads a budget refusal on a row that was never checked. Options: a per-row sub-budget, or a run budget sized to the candidate cap plus redirects (e.g. 8). Decide with the owner.
- **F7 — key-gated APIs.** The Census API now requires a key for data queries. The harness names it; nothing lets the user supply one to a data-loading node without pasting it into code. A secret input the sandbox injects (env or params) is a memo of its own — never a literal in node content. **Delivered by dev/116 (`DEC-074`, `BL-P5-20260908-50`, 2026-09-09): connection keys — `curio_secret("<name>")`, resolved server-side per run, injected as a callable (not env, not params in code), redacted at the sandbox boundary; the `source-missing` remedy now offers *Add key for <host>*.**

