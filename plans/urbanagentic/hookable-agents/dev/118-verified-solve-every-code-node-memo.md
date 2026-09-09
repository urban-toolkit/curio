# dev/118 — "Solved 6 of 6" still means "written" for five of them: widen verified Solve from data-loading nodes to every executable node kind — in topological waves, persisted per wave, honest about the kinds that cannot run, and bounded in time

**Status: IMPLEMENTED (2026-09-09) on `imp/agentcatalog` — commits `1a957ead` (1, `is_executable_kind`, the runner's refusal, the `not-executable` verdict, per-node Solve / validate-node / batch handling), `fdeedfca` (2, `_solve_waves`, the wave loop + `solve_wave`, `_persist_wave`/`_apply_contents` shared with `_finish`, per-wave `nodeRuns` + `solvingSince`, the re-read spec, `upstreamOutputs` + prompt clause, the widened gate, `verification.status = not-executable` on legacy-written kinds), `2387a570` (3, `CURIO_SOLVE_BATCH_DEADLINE` default 45 min → `pending` + reason, `precondition` → `skipped` after one round), `29225ca2` (4, `prior_outputs` reuse across runner/validation/loop/batch, the vanished-artifact retry on the target's input-load failure), `5a1090a8` (5, frontend: `solveWave` status line, `written` pill, `solveNotices`, `isExecutableNodeType` twin, review-card effect line and attempt words; docs: `docs/AGENT-CATALOG.md`, `docs/USAGE.md`; ledgers tracked separately: dev/03 `DEC-075` + DEC-073 note, dev/00 row, `BL-P5-20260909-52`, `3.1`, dev/115 F1 closure, docs/09 note). Suites: backend 1201 passed / 2 skipped, jest 203 suites / 2352 tests, `tsc` clean. Owner questions resolved by default: every code kind incl. JS, per-wave persistence, commit 4 in scope, 45 min, propose mode single-wave-honest. Deviations, all in `BL-P5-20260909-52`: slice-bound skip → `nodeRuns = skipped`; the reuse retry triggers on the TARGET's input-load failure; a not-executable plan node reads `validated` in the plan ledger (F6 names the chip word); `spatial-join` missing from the legacy mapping (F5). Owner live re-test pending: a loader → analysis → chart plan under gemma4 — two verified waves, the chart written *not executable*, the strip reading *wave 2 of 2*.**

Date: 2026-09-09
Branch / tree: `imp/agentcatalog` @ `49de270d` (dev/117 closed). Line numbers pinned to that commit. `plans/` is untracked on this branch (a staged snapshot of it exists in the index, not authored by these sessions) — this memo lives on disk.
Origin: dev/115 follow-up **F1** — *"Widen verified Solve beyond data-loading nodes (`verifyKinds`); expect longer batches — revisit `_SOLVE_MAX_WORKERS`."* — chosen by the owner 2026-09-09 (*"lets continue with the F1 from dev/115"*). dev/115 §2 recorded the v1 scope as the owner's word *"initially"* and called the widening *"a one-line `verifyKinds` change"*. The survey below shows the line is one, and what it drags behind it is four.
Evidence: `agents/services.py:4191` — the whole kind gate: `if verify and _is_data_loading(node):` → the verified loop; else the legacy single-shot generate → DEC-072 gate → write (`:4231-4240`). `:3752-3759` — targets are the session's `pending|failed` `nodeRuns` in **plan-apply order**; `:4244-4247` — every target is submitted at once to `ThreadPoolExecutor(max_workers=_SOLVE_MAX_WORKERS)` (`_SOLVE_MAX_WORKERS = 3`, `:3630`): **no topological order, no dependency barrier**. `:3917-3920`, `:3970` — nothing is written per node; every solved content is appended to `applied_contents` and `_finish` (`:3982-4104`) writes the spec **once**, at the end (`:4007`, `:4041`), against the batch-start `spec` snapshot the loop was handed (`spec=spec`, `:4210`). Consequence: a verified downstream target would execute against upstream siblings whose content is still empty → the runner seeds an empty body, the sandbox returns no `output.path`, and the round fails `upstream-blocker` (`execution/runner.py:376-383`, `agents/validation.py:123-136`) — systematically, for every non-root target of the same batch. `runner.py:292-305` — a node whose `category != "code"` is **pass-through**: the candidate overlay is computed (`:289-291`) and then never sent; the run ends `ok: True` (`:385`); `validation.py:146-158` then fails open on `outputDataType == ""` → **`verdict: "pass"` on content that never ran**. `workflow_spec.classify_node` (`:81-97`) makes `VIS_VEGA`/`AUTK_GRAMMAR` `"grammar"`, `DATA_POOL` `"datapool"`, `MERGE_FLOW`/`VIS_SIMPLE`/`COMMENTS` **and every unknown type** `"passive"`; only the six Python kinds + `JS_COMPUTATION` are `"code"` (`:36-41`). The per-node Solve (`services.py:4964-5026`) and `/validate-node` (`routes.py:911-953`) accept **any** node kind today with no kind check — so this hazard is live already for a vega or merge target, not merely a widening risk. `runner.py:285`, `:331` — `outputs` is function-local: every validation run re-executes the target's whole ancestor slice from scratch; the runtime journal is written (`:370-375`) and never read; three correction rounds run the slice three times. `runner.py:75` `VALIDATION_NODE_LIMIT = 25` is a **slice** bound; exceeding it returns a bound refusal that `validate_candidate` reports as `fail / precondition` (`validation.py:143-144`) and `_record_outcome` then marks the node **`failed`** (`services.py:3931-3948`) — a bound, reported as a content failure. `services.py:3633` `_SOLVE_STALE_SECONDS = 900` — shorter than a widened batch's plausible wall clock; once passed, the `phase == "solving"` guard (`:3746`) admits a second Solve and only the in-process `agent_jobs.check_can_start` (`:3749`) prevents a double batch. No per-batch deadline exists (`started` at `:3840` is only recorded). `node_context.compose_node_context` (`node_context.py:48-121`) hands the delegate upstream rows with `hasContent`/`runtimeStatus` and states *"outputSchema joins when the runtime journal starts capturing column metadata"* — nothing today tells a correction *"your upstream produced dataType X"*; `attempt["outputDataType"]` (`services.py:5957-5958`) is recorded for cards only. Simulation Mode already sequences nodes by topological level so *"upstream validates before downstream generates"* (dev/67-9 `:73-75`) — the ordering precedent. Tests pinning the v1 scope: `test_verified_rounds.py:771-786` (`"verdict" not in results[stats]`, `exec_payloads == 1`), `TestDetachedSolveJobs` inheriting it, and `test_routes.py::TestStreamedSolve` (`:4800+`), whose two-node computation plans never stub the sandbox and pass only because computation nodes bypass verification.
Family: dev/52 (Solve) → dev/63 (streamed Solve, cancel) → dev/67-7 (execute-through validation; sequential ancestor slice, `≤25`) → dev/67-9 (Simulation Mode: topological levels, validate-then-approve) → dev/71 (one validation policy) → dev/115 (DEC-073: verified Solve for data-loading nodes, detached jobs, `interrupted`) → dev/116 (connection keys ride the loop) → **dev/118**.
Design decisions consumed: DEC-021 (expired nonterminal work → `interrupted`; nothing replayed; Retry is a linked execution — per-wave persistence is what makes an interruption keep verified work), DEC-050 (streamed Solve + cancel at node boundaries), DEC-054 (Simulation Mode's validate-then-approve, topological), DEC-067 (self-correcting refusals; here a skip must name its reason), DEC-072 (the gate runs before every execution — unchanged), DEC-073 (Solve is the engineering loop; the trigger is the user's Solve; v1 "data-loading only" is the line this memo moves), DEC-074 (keys ride the loop — unchanged). **New decision proposed: DEC-075** — *Solve verifies every executable node kind. A Solve batch runs in topological waves: a wave's targets generate and verify in parallel (bounded by the worker pool), each verified content is persisted at the wave boundary under the spec lock with the user-edit guard, and the next wave generates and executes against the real upstream content and its recorded output types. A node kind the sandbox cannot execute (grammar, passive, data-pool, unknown packages) is never called verified: its content follows the generate-and-gate path and its result says so (`verification: "not-executable"`), in the batch, in the per-node Solve and in validate-node alike. A batch has a wall-clock deadline; when it is spent, the remaining targets revert to `pending` with the reason and Retry continues them. A slice-bound refusal is a `skipped` with the bound named, never a `failed`.*
Backlog: `BL-P5-20260909-52` at closure; closes dev/115 F1; flips the "data-loading only" lines in `docs/AGENT-CATALOG.md:351-354`, dev/03 DEC-073's posture note, `3.1`.

---

## 1. Problem Statement

**What is broken.** After dev/115, the Solve card can say *"Solved 6 of 6"* and mean "verified" for the one data-loading node and "written, never run" for the five computation, analysis and visualization nodes downstream of it. dev/67-0's standing requirement (*"every node-content generation during Solve must be validated; no shortcut for code considered trivial"*) is met for one kind. The widening was deferred, not declined.

**Why it is not one line.** Flipping `services.py:4191` to every kind today would (a) fail every non-root target with `upstream-blocker`, because siblings' content is written only at batch end and the loop executes against the batch-start spec; (b) call vega, autark, merge, data-pool and third-party nodes *verified* on content that the runner never sent to the sandbox, because a pass-through target ends `ok: True` and the type check fails open; (c) multiply sandbox time with no deadline, past a stale marker that then admits a second batch; (d) turn the runner's 25-node slice bound into a `failed` node.

**Where it shows.** The Dataflow Builder's Solve batch (write and propose modes), the per-node Solve, `/validate-node`, the strip's pills and the Solve card, the review card's "Solve runs it in the sandbox" note (data-loading only today), and `docs/AGENT-CATALOG.md`'s scope paragraph.

**Expected behavior.** Solve runs the plan the way Play would run it: roots first, then their dependents, each wave in parallel. A code node's content is written only when it ran — against upstream content that itself ran. A downstream correction is told what its upstream actually produced. A node kind that cannot run in the sandbox is solved as before and *says* it was not executed, everywhere it appears. A batch stops on time and says what it left for Retry. An interruption between waves loses nothing verified.

**Why it matters.** Trust: the card's word "solved" should mean one thing. Correctness: the models in use (dev/115 §A3.1) get analysis code wrong as often as fetch code, and only a run catches a wrong column name. Consistency: Simulation Mode already works this way one node at a time; Solve should not be the outlier. Honesty: "verified" on a Vega spec that no one executed is worse than "written".

## 2. Scope

**Included**

- **Kind gate → executability**: `_is_data_loading(node)` at the batch gate becomes `_is_executable(node)` = `classify_node(...).category == "code"` (the six Python kinds + `JS_COMPUTATION`, `workflow_spec.py:36-41`), one predicate in `workflow_spec`/`validation` shared by the batch, the per-node Solve and validate-node. Non-executable kinds keep the generate → gate → write path and gain `verification: {"status": "not-executable", "reason": "<kind> runs in the browser, not the sandbox"}` on their result, their proposal (propose mode) and their card line.
- **Honest runner for pass-through targets**: `run_through_node` refuses a target whose category is not `code` *before* executing anything: `{ok: False, infrastructure: None, blocker: None, error: "node '<id>' (<kind>) is not executable in the sandbox", notExecutable: True}`; `validate_candidate` maps it to `verdict: "not-executable"` (new, alongside pass/fail/infrastructure) with `evidence.kind = "not-executable"`. `_verified_content_rounds` returns it as-is after round 1 without a correction (there is nothing to correct). `/validate-node` and the per-node Solve surface it as a labeled outcome, never as `pass`. This fixes the live hazard independently of the widening (commit 1).
- **Topological waves**: `_solve_events` groups targets by depth over the plan's data-flow edges (`WorkflowSpec.topo_sorted_nodes`, Interaction edges excluded; a target whose upstream is *not* a target is depth 0 — its upstream already has content or will be reported as a blocker honestly); waves run in order, each wave's targets submitted to the pool together (`_SOLVE_MAX_WORKERS` stays 3 — the bound is on concurrent sandbox runs, not on plan size); the next wave starts when the previous wave's outcomes are all recorded. Cancel takes effect at the wave boundary *and* the node boundary (dev/63 semantics kept). A new `solve_wave` event `{wave, of, nodeIds}` rides the stream for the strip's status line.
- **Per-wave persistence**: at each wave boundary the job thread writes the wave's `solved` contents into the spec under `spec_write_lock` with `_finish`'s guards (node gone → skipped; non-empty existing content → skipped, "user edit wins") and refreshes `solvingSince` in the same write (a wave boundary is a heartbeat — dev/115 declined a *ticker* because it raced `_finish`; this is the same thread that owns the spec). `_finish` becomes the final, idempotent wave. `nodeRuns` for the wave's nodes are updated in the same write, so a reload mid-batch shows solved pills and an interruption (DEC-021) keeps every persisted wave; Retry targets the rest.
- **Upstream truth for the next wave**: the loop is handed the *updated* spec (re-read after the wave write, or the in-memory overlay kept in step) so the runner executes real upstream content, and the content delegate's inputs gain `upstreamOutputs: [{nodeId, goal, outputDataType, executedAt}]` from the wave's recorded evidence (the `outputDataType` the verified upstream produced). `node_context` is untouched (its schema line stays honest); the new key rides `extra_inputs` like `planSiblings`.
- **Bounds**: `_SOLVE_BATCH_DEADLINE_S` (default 45 min, env `CURIO_SOLVE_BATCH_DEADLINE`): checked at wave boundaries and before dispatching a node; when spent, undispatched targets revert to `pending` with reason *"the batch's time budget (45 min) was spent — Retry continues from here"*, the batch reason names it once (dev/106 shape), and the card says so. The slice-bound refusal (`VALIDATION_NODE_LIMIT`) becomes `skipped` with the bound named, not `failed`; `nodeRuns` keeps `pending` so Retry can run it alone. `_SOLVE_STALE_SECONDS` keeps its value but now measures *since the last wave boundary* (`solvingSince` refresh), which is what "stale" was meant to mean.
- **Ancestor re-execution, same batch** (commit 4 — separable): the runner accepts `prior_outputs: {nodeId: {path, dataType}}`; `_solve_events` supplies the outputs recorded when an ancestor passed *in this batch*; `run_through_node` seeds `outputs` from them and skips those nodes (recorded `{"status": "reused", "executed": False}`); a downstream failure whose blocker is a *reused* node is retried once without reuse before it counts as a round (an expired artifact is infrastructure, not the candidate's fault). Cross-batch reuse (the runtime journal) stays out.
- **Propose mode**: every executable node mints an executed `node.content.write` review with the `validation` block (dev/115's mint, now for all code kinds); non-executable kinds mint without it and carry `verification.status = "not-executable"`.
- **Frontend**: strip status line *"solving wave 2 of 3 — 4 nodes"* from `solve_wave` (through `AgentRunStatusLine`'s existing `runningDetail`); pill label `not executable — written, runs in the browser` for that verification status (`STATUS_LABEL` gains one entry keyed on the result, not a new `nodeRuns` state); the review card's effect line generalizes from *data-loading* to *any executable node* and reads *"runs in the browser — Solve does not execute it"* for the rest; the Solve card lines carry `not-executable` and `skipped (slice bound)` rows.
- **Docs on close**: `docs/AGENT-CATALOG.md` (the Solve section: waves, every executable kind, what "not executable" means, the deadline, per-wave persistence), `docs/USAGE.md` (one paragraph), dev/03 `DEC-075` row + DEC-073 posture note, dev/00 row, `BL-P5-20260909-52`, `3.1`, dev/115 F1 closure.

**Must be checked but not changed**

- `_verified_content_rounds` round policy (gate before run, `repeated-attempt`, `source-missing`, keyed probes, `secrets_fn`) — unchanged; it gains `extra_inputs.upstreamOutputs` from the caller and the `not-executable` early return.
- `agent_jobs` (one live job per attachment, replay, `interrupted` reconciliation) — unchanged; the wave loop is inside the job's generator.
- `runtime_journal` — still written per executed node; still not read (commit 4 reuses the *batch's* recorded outputs, not the journal).
- `verify: false` — keeps the legacy write for every kind, as today.
- Simulation Mode — unchanged (already per-node, topological).
- The DEC-072 gate, the dev/114 grounding inputs, dev/116's keys — unchanged.

**Out of scope (explicitly)**

- Cross-batch artifact reuse (reading the runtime journal's last passing run) — a later memo; the journal's artifacts are session-scoped and their liveness is not tracked.
- Executing browser-only kinds server-side (a headless Vega/Autark render) — a different capability.
- Changing `_SOLVE_MAX_WORKERS` upward — the bound is sandbox concurrency; the memo reasons about it (§3.6) and keeps 3.
- A schema (column) channel to the delegate — dev/67-7 F4 / dev/115 F4, still gated on the journal capturing column metadata; this memo adds `outputDataType` only.
- Multi-instance ownership (OQ-009) — unchanged.

## 3. Recommended Implementation Approach

### 3.1 One executability predicate, three callers

`workflow_spec.py` gains `is_executable_kind(node_type) -> bool` (the `code` category — `classify_node` already knows); `validation.py` re-exports it; `services._is_executable(node)` replaces `_is_data_loading` at the batch gate (`:4191`), and the per-node Solve and `_validate_events` consult it to return the `not-executable` outcome without a delegate round. `source_grounding.is_data_loading_type` keeps its own job (grounding inputs for data-loading nodes only).

### 3.2 The runner refuses what it cannot run, first

`run_through_node`: before the slice loop, `if classify_node(target).category != "code": return {ok: False, infrastructure: None, blocker: None, notExecutable: True, error: …}`. `validate_candidate`: `notExecutable` → `{"verdict": "not-executable", "evidence": {"kind": "not-executable", "detail": …, "goal": …}}`. `_verified_content_rounds`: on that verdict, record one attempt `{round, verdict: "not-executable", kind: "not-executable", source}` and return (no correction, no gate re-run). `_record_outcome`: `"not-executable"` with a candidate → the legacy write path's result shape plus `verification: {"status": "not-executable", "reason"}`; the pill stays `solved` (it *was* written), the card line says *written — runs in the browser, not executed*. Per-node Solve: a node-kind-aware notice (*"This node runs in the browser; Solve cannot execute it — Play the dataflow to see it."*), nothing written for a node that had content, an empty node written from the generation (as today for empty nodes) but labeled.

### 3.3 Waves

```python
depth = _plan_depths(spec, targets)          # 0 = no target upstream; Interaction edges ignored
waves = [[t for t in targets if depth[t] == d] for d in sorted(set(depth.values()))]
for wave_no, wave in enumerate(waves, 1):
    if deadline_spent(): revert(remaining) ; break
    yield "solve_wave", {"wave": wave_no, "of": len(waves), "nodeIds": wave}
    outcomes = run_pool(wave)                # _SOLVE_MAX_WORKERS, cancel at node boundary
    spec = persist_wave(outcomes)            # write_spec under the lock; refresh solvingSince; nodeRuns
    prior_outputs.update(passing outputs)    # commit 4
```

`_plan_depths` reuses the mint's depth helper where it exists (dev/67-9 named `_plan_depths`) or `WorkflowSpec.topo_sorted_nodes` — one implementation. A target with a non-target upstream that has empty content is not the batch's to fix: it runs, fails `upstream-blocker` honestly, and the remedy names the upstream (today's behaviour, now with the right words).

### 3.4 Per-wave persistence and the spec the loop sees

`persist_wave` is `_finish`'s per-node block factored out and called under `projects_storage.spec_write_lock`: re-read the spec, apply the guards, set content for `solved`, update `nodeRuns`, refresh `solvingSince`, write once. `_finish` calls it for the last wave and then completes the session (`phase`, `appliedContents`, the card). The loop for wave *k+1* receives the re-read spec, so `run_through_node` executes real upstream content and `compose_node_context` (reading storage) shows `hasContent: true` and a fresh `runtimeStatus`. Propose mode writes nothing per wave (nothing to write) — its later waves execute against the *current* spec content, which for a proposed-but-unapplied upstream is empty; the memo states this limitation and the card says *"upstream not yet applied"* on such a blocker (edge case 6.6).

### 3.5 What a correction learns

`extra_inputs["upstreamOutputs"] = [{"nodeId", "goal", "outputDataType", "wave"}]` for the target's direct upstreams verified in this batch (from the recorded `evidence.outputDataType`); the new content prompt clause (one sentence in `new_content_prompt.txt`): *"`upstreamOutputs` is what the nodes feeding this one actually produced when they ran — write against those types."* `node_context` unchanged.

### 3.6 Bounds and the worker pool

`_SOLVE_BATCH_DEADLINE_S = 45 * 60` (env-overridable, the dev/115 `exec_timeout_s` pattern). Worst-case arithmetic recorded for the owner: a target costs ≤ 3 rounds × (slice length × `exec_timeout_s`) — with commit 4's reuse, slice length collapses to 1 for same-batch ancestors, so ≤ 3 × 300 s per node; a 25-node plan on 3 workers ≈ 9 sequential batches ≈ 2.25 h worst case, 45 min typical when fetches take tens of seconds — hence a deadline rather than a bigger pool. `_SOLVE_MAX_WORKERS` stays 3: raising it multiplies concurrent sandbox executions on one machine; the honest lever is the deadline plus Retry. `_SOLVE_STALE_SECONDS` measured from the last wave boundary.

### 3.7 What this is NOT

Not a change to how any single node is verified (the loop is the loop). Not a scheduler that skips nodes with content (the target set is still `pending|failed` — a node the user filled is not a target). Not a claim about browser-rendered kinds. Not a new pool size.

## 4. Data and State Handling

- **Source of truth**: the saved spec (content, written per wave), `builderSession.nodeRuns` (updated per wave), the job's event log (replay). Derived: waves (from the spec's edges and the target set, computed once at start), `prior_outputs` (in-memory, batch-scoped).
- **States per node**: `pending → solving → generating/verifying/fixing → solved|verified|failed|skipped|pending(reason)`; `verification.status ∈ {pass, fail, infrastructure, not-executable, skipped}` on the result.
- **After actions**: a wave boundary persists; a reload mid-batch shows the persisted pills and re-attaches; cancel finishes the running wave's in-flight nodes (dev/63) and reverts the rest; the deadline reverts undispatched targets to `pending` with the reason; Retry solves `pending|failed` again — roots first by construction.
- **Races**: the job thread is the only writer of content during a batch; the user-edit guard applies per wave; `solvingSince` is refreshed in the same write; a concurrent Play reads whatever wave has landed (content is only ever *added*, never removed).
- **No duplication**: one depth helper, one persist block (`persist_wave` used by `_finish`), one executability predicate, one loop.

## 5. UI and UX Requirements

- Strip: status line *"solving wave 2 of 3 — 4 nodes"* while a wave runs; pills as today; a `not-executable` result reads *written — runs in the browser*; a slice-bound skip reads *skipped — upstream slice too large (25); Retry alone*; a deadline revert reads *pending — time budget spent; Retry continues*.
- Solve card: the trail lines gain those words; the batch reason line names the deadline once.
- Review card (propose mode / per-node Solve): unchanged for executed reviews; the effect line under a `node.create` reads *"Solve runs it in the sandbox…"* for executable kinds and *"runs in the browser — Solve writes it, Play renders it"* for the rest.
- Per-node Solve row on a browser-only node: the notice above; no spinner longer than the generation.
- Accessibility: all status in words (never colour alone), `aria-live="polite"` on the status line as today.
- No flicker: the wave line updates on `solve_wave` only; pills update per node as today.

## 6. Edge Cases

1. **A target's upstream is not a target and is empty** — the run fails `upstream-blocker`; the error names the upstream and says *"solve or fill that node first"*; `nodeRuns` stays `failed` for Retry.
2. **A diamond** (two upstreams in the same wave, one fails) — the downstream still runs; the blocker is the failed upstream; the passing upstream's content is persisted.
3. **Cycle through data edges** — the runner refuses (`precondition`, cycle named) → `skipped` with the reason; Interaction cycles are ignored by `topo_sorted_nodes`.
4. **Slice > 25 nodes** — `skipped`, bound named, `pending` kept.
5. **Mixed kinds in a wave** — code nodes verify; a Vega node in the same wave is written with `not-executable`; its downstream (a data-pool, say) is also non-executable; a code node downstream of a pass-through node executes with the runner's existing pass-through forwarding (`runner.py:292-305` — unchanged for *upstream* pass-through nodes).
6. **Propose mode, later wave** — the upstream review is not applied yet, so the downstream executes against empty content → `upstream-blocker` with *"apply the upstream review first"*; propose mode is single-wave-honest and the doc says so.
7. **Deadline mid-wave** — the running nodes finish (cancel semantics); undispatched revert with the reason; the wave's passing content persists.
8. **Interruption (process dies) between waves** — persisted waves stay; `interrupted` on read; Retry runs the rest (DEC-021).
9. **User edits a node during the batch** — the wave's persist skips it ("user edit wins"), as today.
10. **Reused artifact gone (commit 4)** — one retry without reuse, not counted as a round; a second failure is the candidate's.
11. **`verify: false`** — one wave, no execution, legacy write for every kind (as today).
12. **A plan with only non-executable targets** — one wave, all written with `not-executable`; the card says none was executed.
13. **Third-party package node kinds** — `passive` today → `not-executable`; a package that declares a sandbox handler (dev/91 `curio.pkgbackend.v1`) is a follow-up: the runner does not execute handlers.
14. **Per-node Solve on a browser-only node with content** — the notice; nothing written, nothing run.

## 7. Testing Strategy

**Backend (required)**

- `test_execution/test_runner.py`: a pass-through target returns `notExecutable` without a sandbox call; an upstream pass-through still forwards; `prior_outputs` seeds and records `reused` (commit 4); reuse-then-retry without reuse.
- `test_agents/test_validation.py`: `not-executable` verdict shape; the slice-bound `precondition` unchanged (the *caller* maps it to `skipped`).
- `test_agents/test_verified_rounds.py`: **flip the pins** — `test_pass_writes_only_after_the_code_ran` asserts the computation sibling now has `verdict == "pass"` and its own sandbox call, executed *after* the loader (wave order asserted on the event stream: `solve_wave {1}` → loader `node_result` → `solve_wave {2}` → sibling); the sibling's exec payload carries the loader's *written* content in the slice (overlay proof) and its correction inputs carry `upstreamOutputs[0].outputDataType == "dataframe"`; `TestDetachedSolveJobs` inherits. New: per-wave persistence (kill the generator after wave 1 → spec has the loader's content, session `interrupted`, sibling `pending`); deadline (monkeypatched `_SOLVE_BATCH_DEADLINE_S = 0` after wave 1 → sibling `pending` with the reason, batch reason once); slice bound → `skipped`; a Vega target in the batch → `solved` + `verification.status == "not-executable"`, no sandbox call; per-node Solve on a Vega node → the notice, nothing run; propose mode mints executed reviews for the computation node; `verify: false` unchanged for all kinds.
- `test_agents/test_routes.py::TestStreamedSolve` and `TestSolve._applied_plan`: stub `runner._http_exec` (the `TestValidateNode._fake_exec` pattern) so two-node computation plans verify honestly; assertions gain `verdict == "pass"`.
- `test_agents/test_source_grounding_routes.py::TestSolveSourceGrounding`: the sibling computation node now executes — the fake sandbox already passes; assert the order.
- Deterministic mirror of a real plan: loader → analysis → Vega (three waves: loader verified, analysis verified with `upstreamOutputs`, Vega written `not-executable`).

**Frontend (jest)**

- `AgentBuilderStrip`: the wave status line from `solve_wave`; the three new pill words; `AgentReviewCard`: the effect line per kind; `AgentAttachmentsProvider.solveEventHandler`: `solve_wave` → `runningDetail`; `agentsApi` types (`verification`, `solve_wave`).
- `tsc --noEmit` clean; colour-literal guard green.

## 8. Acceptance Criteria

1. Solving an applied plan of loader → analysis → Vega runs the loader first, then the analysis against the loader's written content, and writes the Vega spec labeled *not executable*; the card reads *2 verified, 1 written (runs in the browser)*.
2. The analysis node's correction inputs name the loader's output type.
3. Closing the tab or killing the server between waves keeps every persisted wave; the session reads `interrupted`; Retry solves the rest, roots first.
4. A per-node Solve or validate-node on a Vega, Autark, merge, data-pool or unknown-package node never reports `pass`; it reports `not-executable` with the reason, and runs nothing.
5. A batch past its deadline reverts undispatched targets to `pending` with the reason and finishes cleanly; Retry continues.
6. A target whose slice exceeds the bound is `skipped` with the bound named, never `failed`.
7. `verify: false` behaves exactly as before for every kind.
8. Propose mode mints executed reviews for every executable node.
9. With commit 4, a chain of three code nodes executes each node once per passing round (no ancestor re-execution within the batch); a vanished artifact costs one silent retry, not a round.
10. Suites green with the pins flipped; docs describe waves, kinds, the deadline and persistence.

## 9. Recommended Commit Breakdown

- **Commit 1 — honest non-executable outcome (shared, fixes the live hazard)**: `is_executable_kind`, the runner's early refusal, the `not-executable` verdict, the loop's early return, per-node Solve / validate-node outcomes and copy, tests.
- **Commit 2 — waves, per-wave persistence, upstream truth, the widened gate**: `_plan_depths`, the wave loop, `persist_wave` factored from `_finish`, `solve_wave` event, `upstreamOutputs` + prompt clause, `_is_executable` at the gate, the flipped pins and the new wave tests, `TestStreamedSolve` sandbox stub.
- **Commit 3 — bounds**: `_SOLVE_BATCH_DEADLINE_S` + env, `solvingSince` refresh per wave, slice bound → `skipped`, batch reason, tests.
- **Commit 4 — same-batch artifact reuse (separable)**: `prior_outputs` on the runner, `reused` records, retry-without-reuse, tests.
- **Commit 5 — frontend + docs + ledgers**: strip wave line and pill words, review-card effect line, API types; `docs/AGENT-CATALOG.md`, `docs/USAGE.md`; `plans/`: `DEC-075` + DEC-073 note, dev/00 row, `BL-P5-20260909-52`, `3.1`, dev/115 F1 closure, this memo's status.

## 10. Engineering Quality Checklist

- One executability predicate; one depth helper; one persist block shared by waves and `_finish`; the ONE round loop untouched in policy.
- Every non-`pass` outcome has a name and a reason the user reads in words (`not-executable`, `skipped`, `pending` with reason).
- Writes happen in the job thread only, under the spec lock, with the user-edit guard, once per wave.
- The deadline and the stale marker are defined from the same clock and documented.
- Types explicit on the result (`verification.status`), the event (`solve_wave`), and the delegate input (`upstreamOutputs`).
- Tests flip the v1 pins deliberately (named in §7) rather than loosening them; the route-level Solve tests stop passing by accident.
- Frontend: words not colour; the wave line via the existing status-line seam; tokens only.
- Docs say what "verified", "written" and "not executable" each mean.

## Open questions for the owner (non-blocking — defaults stated)

1. **Which kinds verify**: every `code` kind including JavaScript (default) or Python kinds only.
2. **Per-wave persistence** (default: yes — the DEC-021 reason) or keep the single end-of-batch write and accept that an interruption loses the whole batch.
3. **Commit 4 in scope now** (default: yes — the O(N²) re-execution is the main cost of widening) or defer.
4. **Deadline value**: 45 minutes (default), env-overridable.
5. **Propose mode across waves**: accept the single-wave honesty (default: yes, documented) or have propose mode auto-apply nothing and simply stop after wave 1.

## Follow-ups (recorded, not delivered)

- **F1** Cross-batch reuse from the runtime journal once artifact liveness is tracked.
- **F2** Sandbox-handler package kinds (dev/91) as executable targets.
- **F3** A schema/column channel to corrections (dev/67-7 F4 / dev/115 F4) once the journal captures it.
- **F4** Simulation Mode and the Solve batch sharing the wave scheduler (today two orderings, same intent).
- **F6** A plan-chip word for a not-executable plan node — today the plan ledger reads `validated` so Simulation Mode proceeds; the proposal's validation block carries the truth.
- **F5** `spatial-join` and package-provided Python kinds are absent from `NAMESPACED_TO_LEGACY`, so the runner treats them as passive (never executed by validation or the e2e runner) — map them so verification reaches them.
