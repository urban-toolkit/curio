# dev/123 — Evaluation mode: run an evaluation through the product, with the model the account actually uses

**Status: IMPLEMENTED (2026-09-09) on `imp/agentcatalog` — `DEC-079` minted, `BL-P5-20260909-57`. Four commits: `9b2d51bb` (one shared policy, both existing copies re-pointed, plus the two test adaptations the owner's first use forced), `94ab1854` (records, the narrow automated approval, the prompt-review action, the service and eight routes), `8c0d8bb5` (the Evaluation mode panel), and `ac03d06f` (docs), with the ledgers alongside. Suites: `tests/test_agents` 2137 passed; full jest 2376 across 204 suites; `tsc --noEmit` clean. Two owner instructions arrived mid-build and are implemented: the panel distinguishes a model configured by the deployment's start command from one in AI Settings, and a prompt can be **approved from the panel** rather than by hand-editing JSON — that instruction came from a real `papproved` typo which broke every suite at collection. NOT DONE, deliberately: **no real-provider run was executed in this slice.** It is user-triggered by design, and the owner's gemma4 configuration is the acceptance scenario (F1). Findings are in §11 — the load-bearing one is that the production paths assume a request context, so an in-process service driving them must supply one or the grounding gate silently loses the Data Catalog. Neither `OQ-009` nor `OQ-010` was closed. Fine-tuning (dev/122) is untouched, as instructed.**

Date: 2026-09-09
Branch / tree: `imp/agentcatalog` @ `463c0493` (dev/122 closed). Line numbers pinned to that commit. `plans/` is tracked on this branch; `plans/urbanagentic/hookable-agents/knowledge-graph/` (354 MB site copy) stays untracked by intent.
Origin: the owner's correction of 2026-09-09 — *"Revise the plan so production evaluations run through Curio's real UI using the LLM provider and model configured in AI Settings. Preserve the existing scripted-provider path as the deterministic automated-testing layer."* With it: audit and **adapt** everything already built, do not discard or duplicate, extend contracts in place, and record fine-tuning as the *next* capability rather than building more of it in this phase.
Evidence — the audit the correction asked for, as it stands at `463c0493`:

| What exists | Where | Verdict under the correction |
|---|---|---|
| 31 reviewed prompt fixtures + schema | `docs/examples/prompts/**`, `docs/schemas/example-prompt-fixture.v1.json` | **Kept unchanged.** They are already the selector's content; the UI reads them through the service. |
| Canonicalization, dependency scan | `evaluation/canonical.py` (487), `dependencies.py` (161) | **Kept unchanged.** Normalization of ids, layout, order, formatting is exactly what the correction asks for. |
| Comparator, scoring | `evaluation/compare.py` (467), `scoring.py` (342) | **Kept unchanged.** Every dimension the correction lists is already measured here. |
| Attempt scoring (the shared step) | `evaluation/attempt.py` (378) | **Kept, and promoted:** it becomes the one scoring entry every tier calls, including the new UI path. |
| The oracle | `evaluation/oracle.py` (262) | **Kept unchanged.** It is the deterministic tier's answer key; the UI path never uses it. |
| Report/record shapes + redaction | `evaluation/report.py` (293) | **Kept and extended** with the run-record fields the correction names (project id, latency, usage, failures). |
| The fine-tuning export | `evaluation/export.py` (139) | **Kept unchanged.** Its splits are the Training-preparation contract. |
| The remote CLI driver | `evaluation/live.py` (389), `utk_curio/tools/agent_eval.py` | **Kept, and de-duplicated:** its fixed user policy moves into a shared module the UI path uses too; the CLI keeps working for a remote stack. |
| The deterministic driver + suites | `tests/test_agents/_reconstruction_driver.py`, `test_example_reconstruction.py` (705), `test_reconstruction_canonical.py` (513), `test_reconstruction_scoring.py` (566), `test_example_fixtures.py` (306), `test_reconstruction_export.py` (255), `test_live_eval.py` (115) | **All kept.** The driver's policy is re-pointed at the shared module so the tiers cannot drift; assertions unchanged. |
| Browser tier | `tests/test_frontend/test_example_reconstruction_e2e.py` | **Kept**, and gains one Evaluation-mode case. |
| Fine-tuning (dev/122) | `providers.py` tuning surface, `app/agents/training/**` (1524), 4 suites (1796 lines), `ModelTrainingSection.tsx` | **Kept, untouched, and not extended.** See §0. |

Evidence (what is missing, and is this memo's whole subject): nothing in the product runs an evaluation. `live.py` talks to a stack from *outside* over `urllib`, needs `CURIO_EVAL_LIVE=1` and a bearer token pasted on a command line, and writes a file to disk. A person with AI Settings open and a model configured has no way to ask *"can this model rebuild one of these examples?"* — which is the question the fixtures exist to answer.
Family: dev/52 (`DEC-048`, the plan → review/apply → Solve lifecycle) → dev/106 (`DEC-068`, the required-delegate install closure) → dev/115/118 (`DEC-073/075`, Solve as a detached job) → dev/121 (`DEC-077`, the fixtures, the comparator, the deterministic tiers) → dev/122 (`DEC-078`, fine-tuning) → **dev/123**.
Design decisions consumed: `DEC-077` (fixtures never leak, semantic comparison, live runs are reports and never CI gates), `DEC-048` (every phase boundary is an explicit action; apply re-checks drift), `DEC-068` (installing an agent installs its required closure at the user's click), `DEC-073` (a Solve is a detached, re-attachable job), `DEC-040` (filesystem/graph-backed state), `DEC-053` (the egress chokepoint), `DEC-022`/`RISK-SECRET-001` (a credential is never returned by any API).
Design decision proposed: **`DEC-079` — An evaluation is a first-class product action, run through the product. Evaluation mode in AI Settings starts a run against the account's own configured provider and model; the run creates an ISOLATED project, installs and attaches the Dataflow Builder through the normal install flow with its required closure, submits the fixture's prompt through the normal agent runtime, and drives the normal plan → review/apply → Solve lifecycle — no bypassed permission, no bypassed review gate. Applying a proposal without a human click is an automated approval, so it is granted EXPLICITLY and NARROWLY: only inside a project the service itself created and marked for exactly that run, only for the proposal kinds the fixture requires, and recorded per apply on the run record; the normal review policy is unchanged everywhere else. The reference Trill stays server-side and never enters a prompt or a run context. One centralized evaluation service owns fixtures, runs, results and scoring; the UI only renders state and calls it, and the deterministic scripted-provider tiers keep running against the same policy and the same scorer, so a UI run and a CI run cannot disagree about what a correct reconstruction is. Runs persist enough to reproduce and inspect one — fixture, provider and model, agent and prompt digests, the generated project id, the normalized comparison, metrics, failures, latency and usage — and never a key. Real-provider runs are user-triggered and stay out of default CI. Fine-tuning is not part of this phase; the fixture/run/result/scoring contracts here are the foundation its next phase builds on.**
Backlog: `BL-P5-20260909-57` at the first implementation change.

---

## 0. What this corrects, and what it deliberately leaves alone

**Corrected assumption (dev/121 §3.7).** dev/121 delivered the live tier as *"an operator tool"* — `utk_curio/tools/agent_eval.py`, opt-in behind `CURIO_EVAL_LIVE=1`, driving a running stack over HTTP from outside and writing `.curio/eval/<runId>/report.{json,md}`. That was a defensible first cut and it is not wrong; it is just not where the question gets asked. The correction moves the *production* path inside the product. dev/121's §3.7 and its F-series keep their text, and this memo records the supersession in one line rather than rewriting history.

**What is superseded, precisely.** Only the *delivery surface* of the live tier: "an operator runs a CLI" becomes "a person runs it from AI Settings, and a CLI still exists for a remote stack". Nothing about the fixtures, the leak rule, the comparator, the scoring, the capability-gap doctrine, or the "reports, never gates" rule changes. `DEC-077` stands; `DEC-079` extends it.

**Fine-tuning (dev/122) is kept and not extended.** The correction says *"Do not implement model fine-tuning in this phase. Record it as the next capability, requiring separate decisions for provider support, data consent and licensing, redaction, job lifecycle, cost, model versioning, evaluation gates, activation, and rollback."* Those nine decisions were taken one phase ago in dev/122 (`DEC-078`) at the owner's explicit instruction, and the lane shipped: eight commits, four offline suites, the panel, the docs. This memo therefore **adds no fine-tuning**, touches none of that code, and records the relationship: dev/122 is the "next capability" the correction asks for, already discharged, and its activation gate consumes exactly the contracts this memo centralizes. If the owner would rather that lane were withdrawn or hidden pending review, that is a one-line instruction and its own small memo — deleting shipped, tested, documented work is not a decision this memo takes on its own.

## 1. Problem Statement

**The question has no home in the product.** Every piece needed to answer *"can the model I configured rebuild this example?"* exists: reviewed prompts, a canonicaliser, a semantic comparator, a scorer, a report shape, and a driver. But the driver lives outside the product, needs an environment flag and a pasted bearer token, and answers onto the filesystem. So the person who chose the model — the one looking at AI Settings, who just typed a base URL for their own Ollama or a campus endpoint — cannot ask it. Model quality stays an operator errand.

**Two consequences, both visible today.** A user configuring a small local model discovers its planning ability by trying to build a dataflow and watching it fail; nothing tells them beforehand. And the deterministic suites, which are excellent at proving the *pipeline* is lossless, cannot tell anyone whether *this* endpoint is any good, because they never call it.

**The specific gaps.**
- No way to pick a fixture and run it from the interface, and no server-side service to run one: the orchestration exists only as a CLI's private methods (`live.py:LiveRun`).
- The fixed user policy — which proposals an evaluation may apply — is written **twice**, in `live.py::_apply_under_policy` and `tests/.../_reconstruction_driver.py::apply_under_policy`. Two copies of a policy is one policy that will drift.
- Applying a plan without a human click is an automated approval, and nothing today says what authorises it or bounds it. `DEC-048` makes every phase boundary an explicit human action for good reasons; an evaluation needs a *narrow, recorded* exception rather than a quiet one.
- Nothing persists a run inside the product: no run record, no link to the project that was built, no per-category scores to look at afterwards.
- An evaluation run creates a project, installs agents and executes code. Doing that in the user's *current* project would be unacceptable; nothing today creates an isolated one.

**Expected behaviour.** AI Settings gains **Evaluation mode**. It names the provider and model that will answer, lists the examples with their prompts, and starts a run. The run creates its own project, installs and attaches the Dataflow Builder with its required closure, sends the prompt, applies what the policy allows, solves, then compares the persisted Trill against the reference — server-side, which the model never sees. Progress, cancellation and failure are visible states. When it finishes, the panel shows per-category and overall accuracy, a link to the generated project so the graph can be inspected, and the comparison in detail. With no provider configured it says so and offers the fix.

## 2. Scope

**Included — new.**
- `app/agents/evaluation/policy.py`: the fixed user policy, extracted **once** from the CLI and the test driver (both re-pointed at it).
- `app/agents/evaluation/records.py`: run records under `.curio/users/<key>/agents/evaluation/<runId>.json` — append-only events, projected state, the metadata the correction lists.
- `app/agents/evaluation/service.py`: the centralized service — `list_fixtures`, `start_run`, `run_status`, `cancel_run`, `run_report`, `list_runs`. In-process, using the production services directly (`projects.services.save_project`, `agents.services.install_in_project` / `attach_agent` / `run_attachment` / `apply_proposal` / `solve_attachment`).
- `app/agents/evaluation/authorization.py`: the narrow automated-approval grant — what it permits, where it applies, and the refusals that keep it there.
- Routes on `app/agents/routes.py`: `GET /api/agents/evaluation/fixtures`, `POST /api/agents/evaluation/runs`, `GET .../runs`, `GET .../runs/<runId>`, `POST .../runs/<runId>/cancel`, `GET .../runs/<runId>/stream`.
- `agent_jobs.JOB_KINDS` gains `"evaluation-run"` (an in-place extension, so progress, per-user backpressure, re-attachment and the existing SSE plumbing are reused rather than rebuilt).
- Frontend: `src/api/evaluationApi.ts`, `src/components/evaluation/EvaluationModeSection.tsx` (+ CSS module) embedded in `AiSettingsModal.tsx` beside Connection keys and Model training.
- Tests: policy (shared, one source), records, authorization refusals, the service against the scripted provider end to end, the routes, jest for the panel's five states, one browser case, and a live-model case that stays user-triggered.

**Included — adapted in place (no duplication, no rewrite).**
- `evaluation/live.py`: keeps its CLI role for a **remote** stack; its policy body is replaced by a call into `policy.py`, and its report writing is unchanged.
- `evaluation/attempt.py`: unchanged in behaviour, promoted in docstring to "the one scoring entry every tier calls".
- `evaluation/report.py`: extended additively with the run-record fields (`projectId`, `failures`, `phase`), so existing payloads keep their keys.
- `tests/.../_reconstruction_driver.py`: its policy method delegates to `policy.py`; every existing assertion stands.
- `docs/AGENT-CATALOG.md` part 7 and `docs/CONTRIBUTING.md`: the CLI stops being the only way in.

**Out of scope (tracked).**
- **Any fine-tuning work.** See §0.
- Weakening `review-before-apply` anywhere outside an evaluation project (§3.4 is the whole point).
- Evaluating anything other than a fixture-backed example (a "run this on my own dataflow" mode is F4).
- A leaderboard, a pass mark, or a recommendation. Scores are reported; Curio draws no conclusion (`DEC-077`).
- Running evaluations on a schedule, or in CI with a real provider.
- Changing the plan contract, the roster, any prompt byte-pin, or any fixture's expected graph.

## 3. Recommended Implementation Approach

### 3.1 One policy, one scorer, three callers (`policy.py`)

The policy is the harness's "user": send the prompt once, apply a plan whole, apply an install **only** for a resource the fixture required, add no correction rounds, solve once with verification, then read the spec. It is currently prose in a memo and code in two places. It becomes:

```python
@dataclass(frozen=True)
class UserPolicy:
    required_datasets: frozenset
    required_packages: frozenset
    def decide(self, proposal) -> Decision   # apply | skip(reason)
```

`Decision` carries the reason a proposal was left pending, so a report can say *"left a dataset.install for X pending (not required by the fixture)"* rather than silently declining. The targets come from the proposal's **pins** — the revision-safety basis the apply endpoint re-checks — not a params echo (dev/122 F-c's lesson, now enforced in one place).

Callers: the new service, `live.py` (remote CLI), and the deterministic test driver. A test asserts all three resolve the same decision for the same proposal, so the tiers cannot drift.

Scoring is already single-sourced in `attempt.score_attempt`; the service calls it with the same `Universe` shape the other tiers build, so a UI run and a CI run cannot disagree about what correct means.

### 3.2 The run, phase by phase (`service.py`)

`start_run(user, user_key, fixture_id)` runs as a detached job (`agent_jobs`, kind `evaluation-run`) so the panel can watch it, cancel it and re-attach after a reload — the machinery `DEC-073` already built for Solve. Phases, each an event on the record:

| Phase | What happens, through which production path |
|---|---|
| `preparing` | The fixture is loaded and validated; the provider config is resolved (no provider → the run refuses before creating anything). |
| `project` | `projects.services.save_project` creates an **isolated** project named for the run, marked as an evaluation project (§3.4). The user's current project is never touched — nothing here reads or writes it. |
| `provisioning` | The fixture's `required.datasets` install through `DatasetCatalogService.install_dataset`; `required.packages` through `packages_services.install_to_project`. Exactly the provisioned mode the deterministic tier already covers. |
| `installing` | `install_in_project(coord)` — which resolves and writes the **required closure** (`DEC-068`), so the Node Content Builder arrives with the Dataflow Builder — then `attach_agent(..., {"kind": "canvas"})`. |
| `prompting` | `run_attachment(...)` with the fixture's prompt and the account's `ProviderConfig`. The normal runtime: the same system turn, the same roster block, the same bounded tool rounds. |
| `reviewing` | Each returned proposal goes through `policy.decide`; an applied one goes through `apply_proposal` — the **same endpoint a click uses**, with its drift re-check intact. Every decision is an event. |
| `solving` | `solve_attachment(..., verify=True)`, the real waves, the real grounding gate, the real sandbox. |
| `scoring` | The persisted `spec.trill.json` is read and compared with `attempt.score_attempt` against the reference example — **server-side**. |
| `done` / `failed` / `cancelled` | Terminal. The project stays, linked from the report. |

Cancellation is checked at every phase boundary and passed to Solve's own cancel; a cancelled run keeps what it built and says where it stopped.

### 3.3 The reference never travels

The model receives the fixture's `prompt` (and `context`) and nothing else. The reference Trill is read in the `scoring` phase, in the service, from `docs/examples/` — after the model has finished. Three enforcements, all tested:
1. The service passes only `fixture.prompt` to `run_attachment`; a test asserts on the captured provider messages that no node id, edge id, content line or expected-graph JSON appears in the planning turn (the dev/121 leak test, now applied to the UI path).
2. `evaluation/records.py` stores the comparison, never the reference document.
3. The fixture loader is not reachable from any prompt-composition path; the service reads it directly.

### 3.4 Automated approval, granted narrowly and recorded (`authorization.py`)

An evaluation cannot wait for clicks, so it applies proposals itself. `DEC-048` makes that a decision, not a detail. The grant:

- **Scope: one run, one project.** `save_project` writes an `evaluation` marker into the project's own spec (`dataflow.evaluation = {runId, fixtureId, createdAt}`) — graph-backed state, per `DEC-040`. `authorization.assert_may_auto_apply(spec, run_id, proposal)` refuses unless the marker exists **and** its `runId` matches the run doing the applying.
- **Scope: one set of kinds.** Only `dataflow.plan.write`, and `dataset.install` / `package.install` / `project.install` for resources the fixture required. Anything else — a content write, a package draft, a node template creation — is refused and recorded as left pending. A test enumerates the refusals.
- **Nothing global changes.** No agent's `review_policy` is edited, no grant is widened, and the apply endpoint keeps its drift re-check. Outside an evaluation project the function refuses every time, which is the assertion that keeps this honest.
- **Recorded per apply.** Each application appends `{kind: "auto-applied", tool, target, proposalId, runId}` to the record, so a reader can see exactly what was approved on the user's behalf and why it was allowed.

An evaluation project is also marked in the UI (its name carries the fixture and the run), so nobody mistakes one for their own work.

### 3.5 What a run persists (`records.py`)

`.curio/users/<key>/agents/evaluation/<runId>.json`, append-only events with a projection — the shape dev/122's records proved out:

```json
{"recordVersion": 1, "runId": "eval-20260909T171200Z-4f2a", "fixtureId": "02-vega-lite-spatial-density",
 "provider": {"apiType": "openai_compatible", "baseUrlHost": "sage200.example.edu", "model": "gemma4"},
 "digests": {"fixtureSha256": "…", "promptSha256": "…", "agentInstructionSha256": "…", "rosterDigest": "…"},
 "projectId": "…", "attachmentId": "…", "phase": "done", "startedAt": "…", "finishedAt": "…",
 "latencyMs": 41230, "usage": {"inputTokens": 5120, "outputTokens": 980},
 "score": {"total": 0.83, "dimensions": {…}, "categories": ["topology"]},
 "comparison": {…normalized…}, "failures": [{"phase": "reviewing", "detail": "…"}],
 "events": [{"at": "…", "kind": "phase", "phase": "project"}, …]}
```

Never stored: the API key (it is never read here — `resolve_provider_config` hands the service a config the record never serializes), the reference document, or any transcript byte that has not been through `report.scrub`.

### 3.6 Evaluation mode in AI Settings

A third collapsed `<details>` beside Connection keys and Model training, body mounted only while open (the dev/116 pattern, third use). Five states, each with its own copy:

- **Blocked** — no provider or model configured: one sentence and a pointer to the fields directly above it, which is the actionable fix. No Start.
- **Ready** — the provider and model that will answer, named; a fixture selector (example, tier, and the prompt itself, so the user sees what will be sent); Start.
- **Running** — the phase, in words (*"installing the agent"*, *"waiting for the model"*, *"solving 6 nodes"*), the elapsed time, and Cancel. Progress arrives on the run's SSE stream; a reload re-attaches.
- **Failed / cancelled** — where it stopped and why, plus the link to whatever project was built.
- **Done** — overall accuracy, the per-dimension breakdown (templates, topology, dependencies, intents, execution), the failure categories, a link to the generated project, and a detail view of the comparison (missing and extra nodes, edge differences, unresolved or fabricated resources).

Accessibility: a labelled disclosure; the phase line is a `role="status"` live region so progress is announced; the selector is a labelled `<select>` with the prompt shown in a read-only region beneath it; Start, Cancel and the project link are ordinary controls whose consequences are in text (`aria-describedby`), not tooltips.

### 3.7 The deterministic tier keeps its job

Nothing is removed. `test_example_reconstruction.py` still drives the oracle through the same production path with the scripted provider and still asserts the 23-at-1.0 / 8-declared-gap property; it simply gets its policy from `policy.py`. Two additions:
- The service's own path is exercised with the scripted provider, so the *orchestration* (isolation, closure, authorization, phases, records) is covered offline with no model.
- A test asserts the CLI, the test driver and the service resolve identical policy decisions.

The live tier stays user-triggered: the panel is a click, `agent_eval` keeps its `CURIO_EVAL_LIVE=1`, and `test_live_eval.py` keeps its marker. Nothing real-provider enters default CI.

### 3.8 Alternatives considered

- **Keep the CLI as the only path.** Rejected by the correction, and rightly: the question belongs where the model is chosen.
- **Have the UI drive the existing HTTP driver from the browser.** Rejected: the browser would need to hold the bearer token through a multi-minute orchestration, cancellation would die with the tab, and the policy would move client-side where a page reload could change it mid-run.
- **A new job runner for evaluations.** Rejected: `agent_jobs` already gives a detached job, per-user backpressure, event replay and SSE re-attachment. A third kind is a one-tuple change; a parallel runner would be a second liveness model (`OQ-009`).
- **Reuse the user's current project.** Rejected outright — an evaluation installs packages, writes nodes and executes code.
- **Widen the Dataflow Builder's `review_policy` for evaluation runs.** Rejected: that is a global change to an agent contract. The grant is a property of the *project*, checked per apply, so it cannot leak.
- **Score in the browser.** Rejected: the reference would have to be sent to the client, which is one network hop away from being in a prompt.

### 3.9 What this is NOT

Not a change to the plan contract, the roster, the comparator's rules, any fixture, or any prompt pin. Not a pass mark or a recommendation. Not a CI gate. Not a fine-tuning feature. Not a weakening of review-before-apply outside an evaluation project. Not a second scorer or a second policy — the whole point is that there is one of each.

## 4. Data and State Handling

**Sources of truth.** The fixtures on disk for what to ask and what to expect; the account's user row (via `resolve_provider_config`) for who answers; the generated project's `spec.trill.json` for what was built; `attempt.score_attempt` for the score; the run record for what happened. The reference example is read only in the scoring phase.

**Derived values.** The comparison and the score are pure functions of (fixture, generated spec, roster snapshot, catalog listing) and are recomputable from the record's inputs — which is what makes a run reproducible.

**States.** *Blocked* (no provider) is refused before a project exists, so a misconfigured account leaves no debris. *Running* carries a phase and an elapsed time. *Failed* keeps the project and names the phase. *Cancelled* is not a failure and says where it stopped. *Done* carries the score. A run whose job this process no longer holds is reconciled to `interrupted` on first read — the `agent_jobs` pattern `DEC-073` established, reused rather than reinvented.

**Isolation and cleanup.** One project per run, marked, named for the fixture and the run, and **kept** (the correction asks for it: the graph is the evidence). Deleting it is the user's ordinary project deletion. The record survives the project's deletion and says so.

**Concurrency.** One evaluation run in flight per account (`agent_jobs`' per-user cap already bounds background work; the service adds a named refusal so a second Start says which run is running). Records are written write-then-rename under the account's lock.

## 5. UI and UX Requirements

Copy is specific and never speculative: *"gemma4 at sage200.evl.uic.edu will answer"* rather than "your model"; *"waiting for the model (2m 10s)"* rather than a bare spinner; *"topology 0.62 — two edges missing, one extra"* rather than a number alone. The blocked state names the two fields that fix it and does not render a disabled Start.

The generated project is reachable in one click and opens like any other dataflow, because inspecting the graph is how a person understands a score. The comparison detail is a table, not prose: missing nodes, extra nodes, edge differences with their kinds and slots, unresolved dependencies, fabricated resources.

Nothing animates for minutes: the phase line updates on the stream, and the elapsed time is a clock, not a progress bar Curio cannot honestly fill.

## 6. Edge Cases

- **No provider or model configured** → blocked before anything is created, with the fix named.
- **A provider that errors mid-run** → the phase fails with the runtime's own normalized message; the project and the record stay.
- **The model returns prose and no plan** → `refused` (`DEC-063`: a decline is an outcome, not a crash), scored as such, with the reply kept.
- **A plan naming an unavailable template** → refused at mint by the runtime; the run records the refusal and the correction round, and scoring reports what actually landed.
- **A proposal the policy will not apply** → left pending with its reason on the record; the run continues.
- **A proposal the authorization refuses** (a content write, a package draft) → recorded as refused-by-authorization, which is a finding about the run, not an error.
- **Solve exceeds its deadline** → `timeout`; the nodes that landed keep their content (`DEC-075`'s per-wave persist).
- **Cancel during any phase** → stops at the next boundary; Solve's own cancel is used for the solving phase; the record says where.
- **The tab is closed / the page reloads** → the job outlives the request (`DEC-073`); re-opening the panel re-attaches to the stream.
- **The backend restarts mid-run** → the record reads `interrupted` on first read; nothing is replayed.
- **A fixture whose graph the contract cannot express** (the eight interaction-edge ones) → runnable, and the capability gap is reported exactly as in the deterministic tier; the score is not silently lowered.
- **A T3 fixture needing the network or a GPU** → selectable, with its skip conditions shown before Start so the user knows what will not be measured.
- **Two evaluation runs at once** → the second is refused, naming the first.
- **A guest account** → refused where the product already refuses (project creation for a shared guest), with that reason.
- **The generated project deleted afterwards** → the record survives and says the project is gone.

## 7. Testing Strategy

**Unit (offline).** `policy.py`'s decisions per proposal kind and per fixture requirement, including the pins-not-params rule and the "left pending" reasons; the three-caller identity test; `records.py`'s append-only events, projection and interrupted reconciliation; `authorization.py`'s refusals — an unmarked project, a mismatched `runId`, a disallowed tool, and the "outside an evaluation project it always refuses" property.

**Deterministic integration (scripted provider, in-process).** The service end to end: isolation (the caller's project is untouched), the required closure installed, the provisioned dependencies, the phases in order on the record, the apply going through `apply_proposal`, the score computed by `attempt.score_attempt`, the record's metadata complete and key-free, cancel at each phase boundary, a provider error, a refusal, and a run whose fixture declares a capability gap. Plus the existing 705-line reconstruction suite, unchanged in behaviour, now sharing the policy.

**Browser (opt-in).** Evaluation mode opens, shows the configured provider and model, lists fixtures, starts a run against the scripted provider, shows a phase, then shows the score with a link to the generated project. DELIVERED as one case in `tests/test_frontend/test_example_reconstruction_e2e.py` (`TestEvaluationModeRunsFromAiSettings`) — five tests collect in that module. Like dev/121's four, it has **not been executed**: the only stack here is the owner's live one and the e2e fixtures reset the database, so running it needs a dedicated stack (dev/121's standing remainder). It asserts a score appears, never a particular number.

**Live (user-triggered, never CI).** The panel itself against a real endpoint — the owner's gemma4 configuration is the acceptance scenario (dev/115 A3's discipline: a live failure the deterministic mirror did not predict becomes a fixture, not a prompt tweak). `agent_eval` keeps working for a remote stack.

Required before this is complete: all unit and deterministic tests green in `scripts/test.sh --backend-only`; jest green; the browser case collecting; and one live run recorded in the memo with its score and whatever it exposed.

## 8. Acceptance Criteria

1. Evaluation mode appears in AI Settings, names the provider and model that will answer, and lists every fixture with its tier and prompt.
2. With no provider configured, the panel is blocked with the fix named and no run can be started.
3. Starting a run creates a NEW project; the user's current project is unmodified (asserted by digest before and after).
4. The Dataflow Builder is installed through `install_in_project` with its required closure and attached through `attach_agent` — no bypass, asserted on the project's agent lockfile.
5. The prompt reaches the model through `run_attachment` with the account's configured provider; the planning turn contains no node id, edge id, content line or expected-graph JSON.
6. Every applied proposal goes through `apply_proposal`; every application is authorized by the run's own marker and recorded; a proposal outside the allowed kinds is refused and recorded.
7. `authorization.assert_may_auto_apply` refuses in any project without a matching evaluation marker — a test proves it refuses in an ordinary project.
8. The score comes from `attempt.score_attempt`; a test asserts the service, the CLI and the deterministic driver produce the same score for the same generated spec.
9. The run record carries fixture, provider, model, all four digests, project id, phase, latency, usage, score, comparison and failures — and no key (asserted by scanning the file).
10. Progress, cancel, failure and completion are all reachable states in the panel; a reload re-attaches to a running evaluation.
11. The generated project is linked from the report and opens like any other dataflow.
12. The deterministic tiers still pass unchanged, and no real-provider evaluation runs in default CI.
13. Fine-tuning is untouched by this phase, and the memo records dev/122's relationship to the correction's "next capability" instruction.
14. Ledgers at closure: dev/03 `DEC-079`, dev/00 row, `BL-P5-20260909-57`, `3.1`, dev/121's §3.7 supersession note, docs/09, and the user docs.

## 9. Recommended Commit Breakdown

1. **One policy** — `policy.py`, `live.py` and `_reconstruction_driver.py` re-pointed at it, the three-caller identity test. Behaviour-preserving; the existing suites are the regression net.
2. **Records and authorization** — `records.py`, `authorization.py`, their unit tests, and `agent_jobs.JOB_KINDS` gaining `evaluation-run`.
3. **The service** — `service.py`, the phase orchestration over the production paths, and the deterministic end-to-end suite.
4. **Routes** — the six endpoints plus the SSE stream, and their integration tests.
5. **Evaluation mode** — `evaluationApi.ts`, `EvaluationModeSection.tsx`, its embedding, jest tests, and the browser case.
6. **Docs + ledgers** — `docs/AGENT-CATALOG.md`, `docs/CONTRIBUTING.md`; tracking commit for dev/03 `DEC-079`, dev/00, `BL-P5-20260909-57`, `3.1`, dev/121's note, docs/09, and this memo's status.

Each commit is a pathspec commit, no push; `plans/` changes ride separate `tracking dev/123 …` commits.

## 10. Engineering Quality Checklist

- No duplicated policy, no duplicated scorer, no second canonicaliser: `policy.py` and `attempt.score_attempt` are each the only one, and tests assert the callers agree.
- Nothing is deleted or replaced: every module the audit lists still exists with its responsibilities intact; the CLI still works against a remote stack.
- The orchestration uses production entry points only (`save_project`, `install_in_project`, `attach_agent`, `run_attachment`, `apply_proposal`, `solve_attachment`) — no private reimplementation of any of them.
- The automated approval is narrow, project-scoped, kind-limited, recorded per apply, and refused everywhere else — with a test for the "everywhere else".
- The reference never enters a prompt, a context, or a client payload.
- No key is read, stored, returned or logged; transcripts pass `report.scrub`.
- Types explicit and frozen for every value (`UserPolicy`, `Decision`, `EvaluationRecord`, `RunPhase`).
- The job reuses `agent_jobs`; no second liveness model, so `OQ-009` is untouched.
- Accessibility: labelled disclosure, live region for phase, labelled selector, consequences in text.
- The `DEC-055` boundary is not bypassed: the comparison is deterministic code and no agent grades a run.
- Docs say plainly that a score is a report, that the project is kept for inspection, and that fine-tuning is a separate capability.

## Open questions for the owner (non-blocking — defaults stated)

1. **Where evaluation projects live.** Default: ordinary projects named `Evaluation · <fixture> · <date>`, marked in their spec and kept until deleted by hand. Alternative: a hidden folder, which would need a projects-list change.
2. **How many runs to keep.** Default: all records (they are small); the projects are the user's to delete.
3. **Whether to offer "run all T0 fixtures".** Default: one fixture per run in v1 — a batch is F3 once one run's cost and duration are known in practice.
4. **Cancel semantics.** Default: stop at the next phase boundary (a fetch in flight cannot be aborted), matching Solve's own contract.
5. **Whether the panel should surface `agent_eval` for remote stacks.** Default: mentioned in docs, not in the UI.

## 11. What implementing it turned up

**F-a. The production paths assume a request context.**
`services._catalog_grounding_refs` reads `g.user` when one is available and
answers *"no catalog"* when it is not. So driving `run_attachment` from a job
thread silently lost the Data Catalog: every `curio_dataset_path` loader was
refused as an ungrounded source, Solve failed those nodes, and the run finished
with a low score and **no error** — the worst shape a defect can take in a
measurement tool. Solve's own workers dodge this by building their grounding
base in the request thread (its docstring says so); a service that drives the
same paths from a job has no request thread to borrow, so it pushes one
carrying the user. The alternative — threading an explicit user through
dev/114's gate — would change product code to accommodate a caller, which is
the wrong way round. Recorded because anything else that later drives these
paths off-request will hit it.

**F-b. Cancel was a lost update.** The run keeps an in-memory record and writes
it whole at every phase, so a cancel written by a *different* request was
clobbered between its read and its write: the flag never reached the run and
the event vanished from the history. A first attempt at merging the two copies
was the wrong fix — it still lost the flag itself. A cancel is now a **sentinel
file**, so the two writers never share one: the run owns its record, the
canceller owns the sentinel, and the run appends the event when it observes one.

**F-c. Two tests encoded the shipped state as an invariant.** Both asserted
*"no prompt in the corpus is approved"*, which the owner's first approval
falsified. A test that fails the moment the feature is used as intended is
testing the wrong thing; both now assert the behaviour per split, and the half
that was missing — that an approved prompt makes its split exportable — was
added, so approving is proven to have an effect rather than only proven not to
break anything.

**F-d. A hand-edited review is a mistyped review.** `papproved` is a
one-character slip that the schema rejects and that broke every suite at
collection. It is also the whole argument for putting review in the panel: it
validates the file before writing, and it asserts that only the review block
moved, so approving cannot smuggle a change into what is measured.

**F-e. Two shapes read rather than guessed, after guessing cost a round each.**
`install_in_project` answers `{"agents": <lockfile of coordinate strings>,
"installed": [coords]}` — the first cut called `.get()` on a string — and a
project's name is on its summary rather than its detail payload.

## Follow-ups (recorded, not delivered)

- **F1 — an owner-run live evaluation** against the configured endpoint (the
  gemma4 setup is the acceptance scenario). Per dev/115 A3: a live failure the
  deterministic mirror did not predict becomes a fixture, not a prompt tweak.
- **F2 — a comparison detail view on the canvas**: open the generated project
  with the differences highlighted on the graph, rather than only in a table.
- **F3 — batch runs** (a whole tier in one click) once one run's real cost and
  duration are known in practice.
- **F4 — evaluate a user's own dataflow** against a prompt they write, which
  needs a fixture-authoring surface.
- **F5 — a two-run comparison view**: the same fixture under two models, still
  without Curio drawing a conclusion.
- **F6 — fine-tuning stays dev/122's.** Untouched by this phase, as instructed;
  §0 records the relationship to the correction's "next capability" line.
