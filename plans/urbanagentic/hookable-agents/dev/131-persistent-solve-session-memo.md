# dev/131 — Solve is a session the user stops, not a pass that gives up: keep managing the dataflow until Stop or fifteen minutes, and let any node be resolved on its own

**Status: IMPLEMENTED (2026-09-10) on `imp/agentcatalog` — `BL-P5-20260910-66`, and **no new
`DEC`**: it is `DEC-073`'s detached job kept alive and `DEC-075`'s pass kept intact inside a loop.
Two commits: `9ea89fd6` (this memo) and `9c583829` (the session loop, the per-node clamp, and the
frontend), plus a tracking commit. Every line number and every piece of evidence below was read on
`c398a4df`.**

**Suites: `tests/test_agents` 2335 passed; jest 2417 across 207 suites; `tsc --noEmit` clean.**

**Six things changed from the plan while building — §12 — two of them because the owner sent two
more instructions mid-build (a disabled Solve while a node depends on the user, and a better
visualization of those nodes), both implemented here.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `c398a4df` (dev/130 memo).
Origin: owner instruction — *"The DFB must continue to manage the data flow until the user requests
to stop by pressing a button, or until a timeout of 15 minutes occurs. Additionally, users should
have the ability to resolve each node individually. The Node Content Builder and the Node Builder
should operate independently to troubleshoot issues and insert the correct code. The system must
consistently attempt to resolve the node content until it either reaches the 15-minute timeout or
the user decides to stop the process. In the project shown in the attached evidence screenshot, it
stops attempting and leaves the nodes empty. This should only occur after reaching the 15-minute
solve attempt."* — with a screenshot of dataflow `224d23a2`.
Family: dev/52 (Solve over an applied plan) → dev/63 (the streamed batch + Cancel) → dev/115
(`DEC-073`, the detached job) → dev/118 (`DEC-075`, waves + the batch deadline) → dev/126
(`DEC-080`, a node awaiting the user's dataset selection) → dev/127/128/129 (the per-node repair
budget, the input contract, validated-before-written) → **dev/131 (this memo)**.
Design decisions consumed: `DEC-073` (the run outlives the request), `DEC-075` (waves, per-wave
persist, honest non-execution), `DEC-021` (nothing replayed after an interruption), `DEC-080`,
`DEC-006`.

---

## 0. What the screenshot shows, from disk

Dataflow `224d23a2`, nine plan nodes, **"Finished in 13s"**, and three nodes left empty:

| node | status | why |
|---|---|---|
| `420b6d6c` (Brás District Data, `data-loading`) | pending | *awaiting your dataset selection — 3 candidates* (dev/126's gate) |
| `690abcc9` (Feature Harmonization) | pending | *waiting — upstream `420b6d6c` has no content yet* |
| `aa752fde` (Similarity Computation) | pending | same chain |

Six nodes solved. The saved `builderSession` confirms it: `phase: "applied"`, `nodeRuns` with
those three `pending`. So the batch did what dev/118 designed — one pass, waves in topological
order, honest reasons — **and then exited**, thirteen seconds in, with a user-blocked node and two
nodes waiting on it. If the user then confirms a dataset in the Dataset Finder chat, nothing is
watching: the work resumes only when they press Solve again.

That is the whole defect. Not a wrong answer — a **premature exit**.

---

## 1. Problem Statement

**D1 — Solve is one pass, so a blocker that clears later is never picked up.** The batch computes
its waves once (`services.py:4992`), runs them, and yields `done` (`:5178`). `pending` is a
truthful terminal state for that pass, and there is no next pass: a node awaiting the user's
dataset selection (dev/126), a node waiting on an upstream that a later pass could fill, and a node
that failed within its own repair budget all end the session equally.

**D2 — "until the user presses stop" has no button.** The batch has cancellation (dev/63,
`request_solve_cancel`, both the durable session flag and the in-process event), and the strip
accepts `onCancelSolve` (`AgentBuilderStrip.tsx:72`) — but it is offered only *while a batch is
running*, as *Cancel*. There is no control that says "keep going until I say stop", because there
is nothing that keeps going.

**D3 — the fifteen minutes is not the session's.** dev/128/129 gave each NODE a 15-minute repair
budget and left the batch deadline at 45 minutes (`DEFAULT_SOLVE_BATCH_DEADLINE_S`). The owner's
sentence is about the SESSION: *"continue to manage the data flow until … a timeout of 15
minutes"*. Today a session can exit in 13 seconds or run for 45 minutes; neither is what was
asked.

**D4 — "resolve each node individually" is real but hidden.** The per-node Solve exists (dev/115
A2: `solve-node`, the node's own agent, the same verified loop) and it is reachable only from
inside that node's chat panel. The strip shows a pill per node — `420b6d6c pending`,
`aa752fde pending` — and none of them is actionable. The owner is asking for the action to be
where the diagnosis already is.

**D5 — the node's own agents cannot pick up the work by themselves.** *"The Node Content Builder
and the Node Builder should operate independently to troubleshoot issues and insert the correct
code."* The pieces exist — dev/126 attaches a Node Builder to every plan-created node, dev/115's
per-node Solve runs the same loop from it, dev/129 lets it start from a recorded failure — but
nothing invites them: a node left pending by the batch waits for a human to open its chat.

### Expected behavior

- **R1** Solve is a **session**: it keeps making passes while unresolved nodes remain, the session
  budget (15 minutes, configurable) is unspent, and the user has not stopped it.
- **R2** A node blocked on the USER (a dataset selection) does not end the session: the session
  keeps working on everything else, waits, and re-checks — so a selection made while it runs is
  picked up on the next pass, without the user pressing Solve again.
- **R3** A node blocked on an upstream is retried once that upstream has content, in the same
  session.
- **R4** A **Stop** control ends it at the next boundary, keeping everything already written
  (`DEC-021`), and the session says why it ended: stopped, out of budget, or nothing left to do.
- **R5** Every node's pill offers **Solve this node**, which runs the existing per-node loop
  through that node's own agent — the individual resolution the owner asks for, from where the
  status is shown.
- **R6** A node's repair budget never exceeds what remains of the session's, so the session's
  fifteen minutes is the real bound and the per-node one cannot overrun it.

### Why it matters

The owner's dataflow was one dataset selection away from finishing, and the system had already
found the candidates. A session that stays alive turns that into "confirm the source and watch it
complete"; a pass that exits turns it into "press Solve again, and again". R5 is the same argument
at the node level: the diagnosis is on the pill, so the action belongs there.

---

## 2. Scope

**In scope.** `app/agents/services.py`: the batch generator gains an outer **pass loop** with the
session budget, the stop check, and a re-read of the spec per pass; new `solve_session_deadline_s()`
(`CURIO_SOLVE_SESSION_DEADLINE`, default 900); the per-node budget clamped to the session's
remainder; new stream events (`solve_pass`, `solve_waiting`) and a session summary on `done`
(`endedBy: "complete" | "stopped" | "budget"`). Frontend: the strip's **Stop** control (the
existing cancel, renamed and always offered while a session runs), the pass/waiting line, and a
**Solve this node** action per pill wired to the existing `solve-node` endpoint through the node's
own agent. Docs + ledgers + tests.

**Out of scope.** Auto-selecting a dataset on the user's behalf (dev/126's gate is deliberate —
the session waits for the human, it does not decide for them). Raising the sandbox's per-run
timeout or the 45-minute batch ceiling (the session deadline sits under it). A background daemon
that solves without a user action: the session still starts from the user's Solve, and dev/115's
detached job is what keeps it alive across a page reload. Changing what a pass does inside a wave
(dev/118's semantics stay exactly as they are).

**Related code paths.** `_solve_waves`, `_persist_wave`/`_finish` (the persist must stay
once-per-wave and once-per-session), `request_solve_cancel` (both signals), `agent_jobs`
(subscribe/replay across reloads), dev/126's `awaiting-selection` remedy (the reason a wait is a
wait), dev/129's `last_failure` (a later pass starts from what the previous one left), the strip's
pills and the dock badges.

---

## 3. Recommended Implementation Approach

### A. The pass loop

Inside the batch generator, wrap the existing wave sequence:

```python
for pass_no in itertools.count(1):
    spec = _read_spec_or_404(...)          # a selection or an edit since the last pass counts
    targets = [n for n in tracked if status(n) in ("pending", "failed")]
    if not targets: ended = "complete"; break
    if _should_stop(): ended = "stopped"; break
    if _session_spent(started, session_deadline_s): ended = "budget"; break
    yield "solve_pass", {"pass": pass_no, "targets": len(targets), "waiting": waiting_summary}
    …the dev/118 wave sequence, unchanged…
    if made_no_progress and only_user_blocked_remains:
        yield "solve_waiting", {...}       # stop-aware sleep, then the next pass
```

Three properties this must hold, each of which is a test:

1. **No spin.** A pass that changes nothing and leaves only user-blocked or unfixable work waits
   `_SESSION_WAIT_S` (10 s) before the next pass, in stop-aware slices, so a fifteen-minute session
   costs at most ~90 passes rather than a busy loop.
2. **Progress is measured, not assumed.** A pass that solved nothing AND whose failures are
   identical to the previous pass's counts as no progress; a pass that solved anything resets it.
3. **Nothing is replayed.** A solved node is not re-solved (`DEC-021`), and a pass's targets are
   recomputed from the persisted `nodeRuns`, which the per-wave persist already updates.

### B. The session's fifteen minutes, and the node's share of it

`solve_session_deadline_s()` defaults to 900 (`CURIO_SOLVE_SESSION_DEADLINE`), read on the
`exec_timeout_s` pattern. The per-node loop's budget becomes
`min(solve_node_budget_s(), remaining_session_seconds)`, passed into `_verified_content_rounds` as
an override, so one node cannot consume a session it shares and the owner's single number holds at
both levels. The 45-minute batch ceiling stays as the outer guard for a session whose clock
misbehaves.

### C. Stop, and what it means

The control is the existing `request_solve_cancel` (both signals — the durable
`solveCancelRequested` and the in-process event), surfaced as **Stop** for the whole session
rather than *Cancel* for a wave: in-flight nodes finish, nothing dispatched after it, everything
already written stays, and `done.endedBy = "stopped"`. The strip says which of the three endings
happened, and Retry (unchanged) starts a NEW session from what is still pending.

### D. Solve this node, from the pill

Each pill gains an action that calls the existing per-node endpoint against **that node's own Node
Builder attachment** (dev/126 guarantees one exists) — no new backend, no new policy: the same
verified loop, the same budget, the same trail, written on pass or reviewed when the node already
had content. This is D5's answer too: the node's agents are what run it, and the user can invite
them per node while the session runs or after it ends.

---

## 4. Data and State Handling

| Datum | Source of truth | Notes |
|---|---|---|
| What is still unresolved | `builderSession.nodeRuns` (persisted per wave) | the pass loop reads it back each pass |
| Whether the user stopped | `builderSession.solveCancelRequested` + the in-process event | dev/63's two signals, unchanged |
| Session elapsed | the job's own monotonic start | never persisted; a reload re-subscribes to the live job |
| Why a node waits | the per-node result's `reason`/`remedy` (dev/126/127) | what the waiting line summarizes |

The session adds **no new persisted state**: passes are a runtime concept, and everything durable
(content, statuses, phases, trails) is written by the existing per-wave persist and the single
`_finish`. A reload re-attaches to the running job (dev/115) and sees the passes continue.

---

## 5. UI and UX Requirements

- The strip's action row reads **Solve** → while running, **Stop** (destructive-neutral, not red:
  stopping keeps the work) plus a live line: *"pass 3 · 4 nodes left · waiting for your dataset
  selection on 1"*.
- Each pill gains a small **Solve** affordance with an accessible name naming the node
  (*"Solve node 420b6d6c"*), disabled while that node is being solved in the session.
- When the session ends, one line says which ending: *"Finished — nothing left to do"*, *"Stopped
  by you — 3 nodes still pending"*, *"Out of time after 15 minutes — 2 nodes still pending"*.
- The waiting line is `aria-live="polite"`; the per-pill action is a real `<button>`; nothing
  claims a node is solved before its content is written.

---

## 6. Edge Cases

1. **Only user-blocked work remains** — the session waits and re-checks; the selection lands and
   the next pass solves it (the owner's exact scenario).
2. **The user never selects** — the session ends at 15 minutes with `endedBy: "budget"` and the
   node still pending, honestly.
3. **A node fails repeatedly** — each pass gives it a fresh per-node budget clamped by the
   session's remainder; when the session's time is gone it stays failed with its trail.
4. **Stop pressed mid-wave** — in-flight nodes finish (a running sandbox call cannot be aborted),
   nothing new is dispatched, `endedBy: "stopped"`.
5. **Stop pressed during the wait between passes** — the stop-aware sleep returns immediately.
6. **The page is reloaded mid-session** — the job survives (`DEC-073`); the panel re-subscribes and
   the passes continue.
7. **The server dies mid-session** — the session is marked interrupted as today (`DEC-021`);
   nothing is replayed and Retry starts a new session.
8. **A node solved by the user's own per-node Solve while the session runs** — the next pass reads
   `nodeRuns` and skips it; no double write (the per-node write is digest-guarded).
9. **A user edits a node's content mid-session** — the next pass's `last_failure` digest no longer
   matches, so the loop does not "fix" code that is gone (dev/129).
10. **All nodes solved on pass 1** — one pass, `endedBy: "complete"`, byte-identical behavior to
    today.
11. **The batch ceiling (45 min) is somehow reached first** — it still fires; the reason says so.
12. **A plan with a node type that cannot be validated** (dev/129) — it stays pending, and the
    session does not spin on it: no-progress applies.

---

## 7. Testing Strategy

**Unit/loop.** A fake clock and a scripted spec: a session whose only blocker is user-side waits,
picks up the change on the next pass and completes; a session with nothing left ends `complete` on
pass 1; a stop between passes ends `stopped`; an expired session ends `budget`; no-progress passes
wait rather than spin (assert the pass count over a fake fifteen minutes); the per-node budget is
clamped by the session's remainder.

**Route.** The stream yields `solve_pass` per pass and `solve_waiting` when it waits; `done`
carries `endedBy` and the remaining statuses; Stop through `request_solve_cancel` ends the session
with everything already written intact; a per-node Solve during a session does not produce a
double write.

**Frontend (jest).** The Stop control appears while a session runs and calls the cancel; the
waiting line renders the summary and is announced; each pill's Solve action calls the per-node
endpoint with that node's id and is disabled while that node is in flight; the three endings
render their sentences.

**Required before complete.** The five loop tests, the route tests for `endedBy` and Stop, the
jest tests for the pill action and the endings — and a live re-run of `224d23a2` where confirming
the Brás dataset mid-session completes the remaining three nodes without pressing Solve again.

---

## 8. Acceptance Criteria

1. A Solve keeps making passes while work remains, the 15-minute session budget is unspent, and
   the user has not stopped it.
2. A node awaiting the user's dataset selection does not end the session; a selection made while
   it runs is picked up on the next pass.
3. A node waiting on an upstream is retried in the same session once that upstream has content.
4. **Stop** ends the session at the next boundary, keeps everything written, and says so.
5. The session's ending is always one of *complete*, *stopped* or *budget*, named in the strip.
6. Every pill offers **Solve this node**, running the existing per-node loop through that node's
   own agent.
7. A node's repair budget never exceeds the session's remainder.
8. No spin: a session with no possible progress makes bounded, spaced passes.
9. Nothing solved is re-solved; nothing written is lost to a stop.
10. Suites green, and `224d23a2` completes after a mid-session selection.

---

## 9. Recommended Commit Breakdown

1. `solve_session_deadline_s()` + the per-node budget override and its clamp + tests.
2. The pass loop with stop/budget/no-progress and the `solve_pass`/`solve_waiting` events + tests.
3. `done.endedBy` and the strip's three endings + the Stop control + jest.
4. **Solve this node** per pill + jest + a route test against double writes.
5. Docs + ledgers.

## 10. Engineering Quality Checklist

One pass implementation (dev/118's, unchanged inside), one session loop around it, one stop
mechanism (dev/63's two signals), one per-node entry point (dev/115's endpoint) reached from a new
place, no new persisted state, no new policy, no auto-decision on the user's behalf, every ending
named, every wait bounded and stop-aware.

## 11. Open questions and recorded follow-ups

- **F1** Should a session keep going while the user is *editing* the canvas? Today it re-reads the
  spec per pass, which is the honest behavior; a lock would be worse. Watch for a case where a
  half-typed node is re-solved and, if it appears, gate on dev/124's revision.
- **F2** Whether the Dataset Finder should push a notification when candidates land, so the user
  knows the session is waiting on them (the strip says it; the dock badge could too).
- **F3** dev/129's F2 (render errors into the journal) would let a session repair a browser-side
  failure too, which is the last gap between "manages the dataflow" and "manages the dataflow".
- **F4** A catalog dataset installed MID-session has no sandbox path inside the running job (the
  mapping is resolved eagerly, in the request context — dev/115's rule). Its node stays pending
  until the next Solve. An external URL confirmed mid-session is unaffected. Fixing it needs a
  request context pushed into the job, or a path resolver that does not need one.

---

## 12. What changed while building

1. **A later pass attempts only what CHANGED, not everything unresolved (§3A).** The memo's
   "no-progress → wait" check ran after a pass, so every failing node got a second full set of
   attempts before the loop noticed. Implemented as a per-node **blocker signature** — its own
   content, every upstream's content, and its dataset-selection record — captured **after** the
   pass runs, because taking it before made any pass that solved something trigger another one
   (twenty-nine tests said so). A node is re-attempted when its signature moves; when nothing
   moves the session waits and re-checks, which is what "keep attempting" means without burning
   provider calls on identical conditions.
2. **A session never un-solves a node, and never erases an earlier pass's evidence.** Not in the
   plan, and load-bearing: a node still awaiting the user produces a fresh result with no attempts,
   and overwriting the pass that DID try left a bare "pending". Results are now merged (a result
   with attempts wins; one without keeps the earlier trail and updates only the reason) and a
   solved node's outcome is never replaced.
3. **`endedBy` has four values, not three.** The missing-specialist branch (an install only the
   user can apply, whose proposal is already in the chat) ends the session as `blocked`, and the
   bookkeeping moved above that branch so every exit reports an ending.
4. **The suite pins the session budget and wait** (1 s each, autouse) for the same reason dev/127's
   pin exists: every earlier test asserts on ONE pass, and a session waiting for an absent user
   would hang the suite.
5. **Two owner instructions arrived mid-build and are implemented**: the main Solve is DISABLED,
   with the reason, when every unresolved node depends on the user (pressing it cannot help — the
   action that can is already beside it), and a pill whose node waits for the user is outlined and
   labeled *needs you*, with an upstream wait reading *waiting upstream*.
6. **Cancel became Stop** in name and semantics (a session, not a wave), and its two jest tests
   were renamed to describe the session.

7. **OWNER CORRECTION (2026-09-10, after the first eight commits): a retry must not carry the same
   inputs.** *"the keep attempting it should not carry the same inputs, supossing it doesn't depend
   on user's actions, it should carry the currently error that is being given."* Deviation (1)
   above was too strict: the blocker signature is about the node's SURROUNDINGS, and a node whose
   own attempt just failed has a new input — **its error** — which the signature cannot see. So:
   - a later pass attempts **every** unresolved node that is not parked on a user action
     (`_awaits_user_action`: dev/126's dataset selection, dev/116's missing connection key); the
     signature gate now applies only to those, whose blocker really is elsewhere;
   - the pass carries the node's own last failed candidate and its error into round 0
     (`_carry_forward_error` → the loop's `carry_forward`), so the child is asked for a
     CORRECTION, with `previousAttempt`/`validationError` set exactly as a mid-loop round would
     have them, and the trail says *"carrying forward the previous attempt's error: …"*;
   - kinds that say nothing about the code are never carried (a sandbox outage, a slice bound, an
     upstream blocker) — handing that code back as "your previous attempt" made the repeat
     detector fail a node whose code had never run; and a repeat notice yields to the real error
     behind it;
   - the trail **accumulates across passes** (40 rows kept, the transcript part now carries the 12
     most recent and counts the rest) because the owner asked to see all attempts;
   - the diagnosis stays concrete: when a repeat ended the loop, the sentence names the error the
     node is stuck on and `stoppedBy` still says a repeat ended it;
   - and the spin is bounded: after three consecutive passes in which every attempt was a repeat,
     the session stops re-attempting THAT node (`_MAX_WEAK_PASSES`) — its diagnosis and trail
     stay, and the session moves on to what can progress.
8. **Three defects in (1)'s implementation, found by the correction and fixed.** (a) The waves were
   built from ALL targets, not the pass's — so a pass ran nodes the gate had excluded, and a
   node parked on the user lost its trail to a pass that could not touch it. (b) dev/118 persists a
   wave only at a wave BOUNDARY (the last wave lands in `_finish`, correct for a batch), so a
   pass's last wave never reached `nodeRuns` and the next pass re-solved a node this session had
   just solved; a pass boundary now persists too, and `unresolved` also honors what this session
   settled in memory. (c) The merge in (2) treated `attempts: []` and `rounds: 0` as answers
   rather than absences, so the awaiting path still won over a real trail.

One limit found and not fixed here: the eager, request-context pieces (the Data Catalog listing and
the sandbox dataset-path mapping) are resolved when the session starts, so a CATALOG dataset the
user installs mid-session has no path inside the running job and its node stays pending until the
next Solve. Recorded as **F4**; an external URL confirmed mid-session works, which is the owner's
own case.
