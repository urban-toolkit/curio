# dev/106 — Installing an orchestrator leaves its required specialist uninstalled: Solve fails every node in 0 ms and the one install proposal it mints is invisible

**Status: IMPLEMENTED (2026-08-25) — commits `9db3c497` (1, manifest + roster + closure helpers), `69db666c` (2, install closure + uninstall guard + card disclosure), `e438c5a3` (3, the Solve turn carries its proposal + one reason line), `d1abd249` (4, drawer disclosure), `f6b27079` (5, strip Install row + reasons, palette refresh on apply), docs (6); DEC-068 minted; BL-P5-20260825-45. Verification: `test_agents` + `test_packages` 1486 passed / 4 skipped; jest catalog+palette 173, attach 248; tsc baseline unchanged. Owner live re-test of the screenshot flow (fresh project → install Dataflow Builder → plan → Solve) still to be recorded here.**

Date: 2026-08-25
Branch / tree: `feat/agentscatalog` @ `2ba4c953`. Line numbers pinned to that commit.
Origin: live failure, Dataflow Builder session `71488964…` / solve executions `735a4ba5…` and `97f4bcb5…` (the Retry) in project `cb605bfd…` (screenshot `Desktop/Screenshot 2026-08-25 at 3.24.17 PM.png`). Model `gemma4` via `openai_compatible`.
Family: dev/48 (delegation, DEC-046, `REQ-ORCH-001`) → dev/52 (Dataflow Builder composite, DEC-048) → dev/63 (Solve stream) → dev/73 (NCB in `delegatesTo`). Sibling precedent for install-closure semantics: dev/101 (project lockfile authority; uninstall 409 while in use) and `packages/build_deps.py` (package dependency resolution — agents have no analogue).
Prereqs: dev/03 `REQ-ORCH-001` ("never silently imports, installs, attaches…"); dev/12 lifecycle (immutable definition → explicit account import → explicit project install); dev/41 review-before-apply.

---

## 1. Problem Statement

**What the user saw.** With `Dataflow Builder` and `Researcher` installed (palette: "Installed in this project · 2"), the Builder planned six nodes, the plan applied, and Solve reported **"Solved 0 of 6 plan nodes"** with six bare `<id> · failed` lines, "Finished in 0s". "Retry 6 failed" produced the identical card. No reason, no card to act on, nothing in the chat explaining what to do.

**What actually happened** (session file `agent-sessions/71488964….json`, spec `agentAttachments`):

- Both solve executions ran **14 ms / 11 ms with `tools: []`, `usage: null`** — no provider call at all.
- `_solve_events` (`agents/services.py:3759`) resolved capability `node.content.generate` against the project lockfile `['agent.dataflow-builder@1.0.0', 'agent.researcher@1.0.0']` → `Resolution("not-installed", "agent.node-content-builder@1.0.0")` (reproduced live with `delegation.resolve`).
- The not-installed branch (`services.py:3766-3783`) called `_mint_project_install` and stored the proposal: the DFB attachment's `activeProposal` is **`{tool: "project.install", coord: "agent.node-content-builder@1.0.0", status: "pending"}`** right now. Then it marked all six nodes `failed` with `error: "specialist not installed — an install proposal awaits review"`.

So the runtime did what dev/48 designed (`REQ-ORCH-001`: mint a reviewed install, never install silently) — and the user could not see any of it. Four defects, two layers:

**D1 — The Solve path mints the install proposal and drops it.** `services.py:3771`: `status, text, part = _mint_project_install(...)` — `part` is never appended to any transcript turn (contrast the chat path, `services.py:6962-6970`, which does `minted.append(part)`), and `status == "refused"` (no `session_id` / no spec, `services.py:5753-5764`) is never checked, so `reason` claims "an install proposal awaits review" even when none was minted. The proposal exists only in the attachment mirror.

**D2 — Nothing renders a mirror-only `project.install` proposal.** `AgentChatPanel.tsx:713-714` looks the mirror up *by a transcript part's proposalId* — no part, no card. `AgentBuilderStrip.tsx:144-149` reads the mirror directly, but only for `tool === "dataflow.plan.write"`. Result: a pending proposal with a live Apply endpoint and zero UI. Retry re-mints (superseding the previous, `_store_proposal`, `services.py:5420-5450`) the same invisible proposal — an unbounded loop of identical failures.

**D3 — The failure reason is discarded on both layers.** Backend: `_finish` persists `outcome["status"]` only (`services.py:3690-3691`) and the card lines are `f"{node_id[:8]} · {outcome['status']}"` (`:3714-3717`). Frontend: the SSE handler reads `payload.status` and ignores `payload.error` (`AgentAttachmentsProvider.tsx:647-651`); `AgentSolveResult.results[].error` (`agentsApi.ts:460`) has no read site outside tests. The existing regression test asserts exactly the string the UI never shows (`test_routes.py:4964-4977`).

**D4 — Installing an agent never installs what its built-in phases require (the structural cause).** `install_in_project` (`services.py:371-393`) appends ONE coord; `manifest.delegates_to` is read only at run time (`services.py:5088, 6956`; `delegation.py:75, 125`). The Dataflow Builder's Solve (`services.py:3759`) and Validate (`:4504-4512`, a 409 "install the Node Content Builder first") are **server code paths** that hard-invoke `node.content.generate` — not model-chosen delegations. The only roster agent declaring it is `agent.node-content-builder` (`builtin.py:112-117`). So an install that the drawer reports as successful leaves the Builder's core phase structurally unable to run. The card payload (`_manifest_to_card`, `services.py:57-82`) carries no `delegatesTo`, so the drawer cannot even show the dependency.

**Why it matters.** The Builder is the flagship composite (dev/52); its first post-plan step fails for every fresh project until the user discovers, by reading source, that a third agent must be installed. The `REQ-ORCH-001` design intends a *visible* reviewed install — an invisible one is worse than either a silent install or a plain error.

**Expected behavior.** Installing the Dataflow Builder from the catalog installs the Node Content Builder with it (disclosed on the button, one atomic lockfile write); if a required dependency cannot be resolved, the install fails loudly and nothing is written. Independently, when Solve ever meets a missing specialist again (an old project, a hand-edited lockfile, an uninstall), the Solve card names the reason once and carries the Install card the user can Apply, and Retry works after Apply.

## 2. Scope

**In scope**
- Backend: `agents/manifest.py` (additive field), `agents/builtin.py` (DFB declaration + `BuiltinAgentSpec`), `agents/services.py` (`install_in_project`, `uninstall_from_project`, `_manifest_to_card`, `_solve_events` not-installed branch, `_finish` card), `agents/routes.py` (install response shape; no new route unless the preview needs one), `agents/delegation.py` (a pure `required_closure` helper beside `resolve`).
- Frontend: `api/agentsApi.ts` (card + install response types), `components/agents/catalog/{AgentsCatalogDrawer.tsx,useAgentsCatalogDrawer.ts}` (dependency disclosure on Install / Uninstall), `components/agents/attach/{AgentAttachmentsProvider.tsx,AgentBuilderStrip.tsx}` (reason + mirror-driven install action), `AgentReviewCard.tsx` (`project.install` copy already exists at `:188` — reuse).
- Tests listed in §7. Docs: `docs/AGENTS.md`, dev/03 DEC table, dev/00 index, `3.1`/README status lines (the dev/93 closing convention).

**Out of scope (unchanged)**
- `delegation.resolve` order and semantics (dev/48/52) — still current-project-only, still `delegatesTo` = preference.
- Model-chosen delegations (`delegateRequest` tails, `services.py:6745, 7072, 7430`): their missing-specialist path already appends the part and stays a reviewed proposal. The 14 other DFB delegates remain **optional** — no install fan-out of 15 agents.
- Account import ("My Imports"): import is the ownership/publishing step of the dev/12 lifecycle, not a runtime prerequisite — `install_in_project` already materializes a built-in's bytes into the user store (`_materialize_builtin`, `services.py:114`). The request's "imported into the user's agent collection" bullet is therefore satisfied by materialization, not by auto-adding rows to `imported-agents.json` (which would silently mutate a publishing surface — `REQ-ORCH-001`). Flagged as a deliberate reading; see §8 AC-5.
- Node Builder / Researcher / Package Builder: none has a server-authenticated hard dependency today (verified: every other `run_delegate` site takes its capability from the model's request); they declare `requiresAgents: []` and gain the mechanism for free.

## 3. Recommended Implementation Approach

**A. A declared hard-dependency set, distinct from preference.** Add an additive manifest field `requiresAgents: [agentId]` (Python `requires_agents`), validated like `delegatesTo` (agent-id regex, no self-reference) **and** required to be a subset of `delegatesTo` (a hard dependency that isn't a delegate is a manifest error). Semantics: "a server code path of this agent invokes a capability only these agents declare; the agent is not functional in a project without them." `BuiltinAgentSpec` gains `requires_agents` (default empty); the Dataflow Builder declares `("agent.node-content-builder",)`. `delegatesTo` keeps its "composition only — grants nothing" meaning (`builtin.py:78-81`); nothing else moves.

**B. Install-time closure at the user's explicit action (not the agent's).** `delegation.required_closure(user_key, agent_id) -> tuple[list[coord], list[missing_id]]` walks `requires_agents` transitively through `find_visible` (depth-bounded, cycle-safe, deterministic order). `install_in_project(user_key, project_id, coord)` computes the closure, **refuses with 409 listing the unresolvable ids if any is missing** (nothing written), otherwise materializes every built-in in the closure and writes the lockfile + defaults records **once** (one `write_spec`). Return shape grows additively: `{"agents": [...], "installed": [coords newly added], "required": [coords in the closure]}`. This is a user-initiated install, so `REQ-ORCH-001` (which binds the *orchestrator*) is honored; the disclosure in C keeps it non-silent.

**C. Disclosure before the click.** `_manifest_to_card` gains `requiresAgents: [{id, name, coord, installedInProject}]` (resolved server-side so the drawer never re-derives it). The drawer's Install button reads "Install" when the closure is satisfied, "Install +1 required" with a title/tooltip naming the dependency otherwise; the success toast/refresh already exists (`refreshAll`, `notifyAgentsPaletteRefresh`). No modal — one label, one click, consistent with the package drawer's dependency line.

**D. Uninstall guard (dev/101 shape).** `uninstall_from_project` refuses (409) removing a coord that another *installed* template lists in `requires_agents`, naming the dependents; the drawer shows the 409 text verbatim (it already surfaces `AgentServiceError`). No cascading uninstall.

**E. The Solve path stops losing its own proposal (independent of A–D).** In `_solve_events`: check the mint `status`; when `"proposed"`, pass the `part` into `_finish` so the Solve turn's `content` is `[result card, proposal part]` and the card gains one line `"reason: specialist not installed — Install Node Content Builder below"`; when `"refused"`, `reason` states the refusal text. Mirror-first on the frontend: `AgentBuilderStrip` treats a pending `activeProposal.tool === "project.install"` exactly like `planReview` — an inline row "Solve needs Node Content Builder · Install · Dismiss" targeting `onApplyProposal` (works even without a part, per its own `:44` comment). After Apply, `requiresRegistryRefresh`-style follow-through is unnecessary (agents palette already refreshes on install via `notifyAgentsPaletteRefresh`; the provider's apply path dispatches nothing for `project.install`, `AgentAttachmentsProvider.test.tsx:589` — add the palette refresh there).

**F. The reason survives.** Backend: `_finish` persists `nodeRuns` unchanged (status strings are load-bearing for phase computation) but the card lines become `"<id> · failed — <reason>"` **only for the batch-level reason, emitted once** (not per node — six identical lines is the current noise). Frontend: the SSE `node_result` handler records `payload.error` into `solveProgress[attachmentId].errors[nodeId]`; the strip renders one deduplicated reason under the pills (`styles.error` already exists, `AgentBuilderStrip.tsx:355`).

## 4. Data and State Handling

- **Source of truth**: the project lockfile `dataflow.agents` (backend-owned per dev/29/81/101; canvas saves omit it). `requiresAgents` is immutable manifest data; the closure is derived on every install call, never cached in the spec.
- **Atomicity**: one `read_spec` → mutate → `write_spec` per install; a partial closure must never land (refuse before writing). Idempotent: re-installing a satisfied closure writes nothing.
- **Derived card state**: `requiresAgents[].installedInProject` is computed against the requested `projectId` in the same pass that sets `installedInProject` today (`list_global_catalog(..., project_id)`), so Global/My Imports/Installed tabs agree after `refreshAll`.
- **Solve**: the not-installed branch keeps failing every target (no partial solve), keeps ONE proposal (not per node), and now records `reason` on the batch (`payload_out["reason"]`, additive) beside per-node `error`.
- **Race**: Apply on the install proposal and a concurrent Retry — Retry re-resolves at start; if the install landed first it proceeds, else it re-mints and supersedes (existing dev/41 semantics). No new lock; the spec lock from dev/82 covers the write.
- **Stale UI**: after Apply, the strip's mirror clears (`activeProposal.status` → applied) and `refreshAll` repaints the drawer; no full reload.

## 5. UI and UX Requirements

- Catalog drawer card (Global / My Imports): a small dependency line under capabilities — "Requires: Node Content Builder" with an installed check or a "not installed" pill; Install button label per §3-C; tooltip lists exact names. Installed tab: the dependent's card shows "Required by: Dataflow Builder"; Uninstall on a required dependency is enabled but the 409 text renders in the drawer's existing error slot.
- Builder strip: when `activeProposal` is a pending `project.install`, a review row identical in style to the plan review row: text "Solve needs **Node Content Builder** (not installed in this project)", buttons Install / Dismiss; "Retry N failed" stays enabled; a single reason line under the node pills. `aria-live="polite"` on the reason (the strip's error div pattern).
- Transcript: the Solve turn carries the result card + the existing `project.install` review card (`AgentReviewCard` copy at `:188` — "installs only this project template").
- No layout shift: the review row mounts in the strip's existing review area; pills unchanged.

## 6. Edge Cases

1. Dependency visible in neither roster nor store (imported parent naming a private agent) → install 409 naming the id; nothing written; drawer shows it.
2. Dependency already installed → closure satisfied, single-coord behavior byte-identical to today.
3. Cycle / self-reference in `requiresAgents` → manifest error at parse; closure walker also bounded (depth ≤ 8) as defense.
4. Dependent installed at version X, dependency visible at BUILTIN_VERSION only → closure uses `find_visible` (same rule as runtime `resolve`), so install-time and run-time agree.
5. Uninstall the parent → dependency stays installed (no cascade); it is a normal template thereafter.
6. `_mint_project_install` refused (attachment without session) → reason says so; no phantom "awaits review".
7. Retry pressed twice quickly → second call 409s on `solvingSince` (existing); proposal not double-minted.
8. Old project with DFB but no NCB (every pre-dev/106 project) → the §3-E path is the migration: first Solve shows the Install row; Apply installs; Retry succeeds. No lockfile backfill.
9. Solve via the non-stream route (`routes.py:549-582`) → same `_solve_events` body; `reason` in the JSON payload.
10. `requiresAgents` absent in an uploaded manifest → default `[]` (additive, no migration).

## 7. Testing Strategy

**Backend (`tests/test_agents`)**
- `test_manifest.py`: `requiresAgents` parses; rejects self-reference, non-agent-id, and an id not in `delegatesTo`; absent → `[]`.
- `test_builtin.py`: DFB pins `requires_agents == ["agent.node-content-builder"]`; every roster `requires_agents` ⊆ `delegates_to` (roster-wide invariant).
- `test_delegation.py`: `required_closure` — transitive, deterministic, missing ids reported, cycle-bounded.
- `test_routes.py` install: installing DFB into an empty project yields a lockfile containing NCB, one spec write (spy on `write_spec`), response `installed`/`required`; unresolvable dependency → 409 and lockfile untouched; idempotent re-install; uninstall NCB while DFB installed → 409 naming DFB; uninstall DFB then NCB → 200.
- `test_routes.py` catalog: cards carry `requiresAgents` with `installedInProject` per project.
- `test_routes.py` solve (extend `test_missing_specialist_fails_batch_with_one_install_proposal`): the Solve **transcript turn** contains a `proposal` part with `tool == "project.install"` (the assertion D1 lacked); card carries one reason line; a refused mint yields a reason without "awaits review"; Apply → Retry solves (extend `test_child_failure_isolation…` fixture).

**Frontend (`src/tests`)**
- `useAgentsCatalogDrawer.test.ts` / `AgentsCatalogDrawer.test.tsx`: Install label "+1 required" when unsatisfied; plain "Install" when satisfied; 409 text surfaces on uninstall.
- `AgentBuilderStrip.test.tsx`: pending mirror `project.install` renders the Install row and calls `onApplyProposal(proposalId)`; the reason line renders once for six failed nodes.
- `AgentAttachmentsProvider.test.tsx`: `node_result` with `error` populates `solveProgress.errors`; `project.install` apply triggers the palette refresh.

**Gate**: `pytest utk_curio/backend/tests/test_agents` and `npm test -- agents catalog attach` green (conda `curio-feat` for node, per memory).

## 8. Acceptance Criteria

- AC-1: Installing Dataflow Builder from the drawer into a fresh project writes `agent.node-content-builder@1.0.0` into `dataflow.agents` in the same write; the palette shows 2 installed; Solve on an applied plan makes provider calls (execution `tools`/`usage` non-empty) and never fails in <100 ms for "not installed".
- AC-2: The Install button discloses the dependency before the click; the response names what was added.
- AC-3: An install whose required dependency cannot be resolved returns 409 with the missing ids and writes nothing; the drawer shows the message.
- AC-4: Uninstalling a required dependency while a dependent is installed is refused with the dependents named.
- AC-5: No `imported-agents.json` mutation happens on install (import stays explicit); the dependency's definition bytes exist in the user store after install.
- AC-6: On a project missing the specialist, the Solve turn shows one reason line and an actionable Install card/row; Apply then Retry solves the nodes; the six bare `failed` lines with no reason no longer occur.
- AC-7: `delegation.resolve` results for every existing test are unchanged; the 14 optional DFB delegates are not installed by AC-1.
- AC-8: Existing `test_agents` (1457 as of dev/105) stay green.

## 9. Recommended Commit Breakdown

1. **Manifest + roster**: `requiresAgents` field, validation, `BuiltinAgentSpec.requires_agents`, DFB declaration, `required_closure` helper — with `test_manifest`/`test_builtin`/`test_delegation` coverage.
2. **Install closure + uninstall guard**: `install_in_project` atomic closure + 409s, `uninstall_from_project` dependents 409, response shape, `_manifest_to_card.requiresAgents` — `test_routes` install/catalog lanes.
3. **Solve path honesty (backend)**: mint status checked, part appended to the Solve turn, one reason line, `payload_out.reason` — extend the missing-specialist solve test to assert the transcript part.
4. **Frontend drawer**: types, dependency line, Install label, 409 surfacing — drawer/hook tests.
5. **Frontend strip/provider**: mirror-driven `project.install` review row, `error` capture and single reason line, palette refresh on apply — strip/provider tests.
6. **Docs**: `docs/AGENTS.md` (required vs. optional delegates; `REQ-ORCH-001` reading: closure rides the user's install), DEC-068 row in dev/03, dev/00 index, `3.1`/README status, BL-P5-20260825-45; memo status → IMPLEMENTED after the owner's live re-test of the screenshot flow.

## 10. Engineering Quality Checklist

- Closure logic lives once (`delegation.required_closure`), consumed by install, card, and uninstall guard — no drawer-side re-derivation.
- `requiresAgents` typed end-to-end (`AgentManifest`, card type in `agentsApi.ts`); default `[]`, additive, no migration.
- One spec write per install; refuse-before-write; idempotent.
- `delegation.resolve` untouched; runtime `REQ-ORCH-001` proposal path preserved and made visible rather than replaced.
- Reason rendered once, `aria-live`; no per-node duplicate text; no layout shift (existing review-row slot).
- Regression lane asserts the transcript part — the gap that let D1 ship silently.
- Follows dev/101's 409-while-in-use shape and dev/93's docs-closing convention.
