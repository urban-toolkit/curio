# dev/112 — The Dataflow Builder can diagnose a cycle but cannot repair it: the plan contract cannot express an Interaction edge, never checks acyclicity, refuses edge-only plans, and under-reports removals

**Status: IMPLEMENTED (2026-08-27) — commits `6d5f89fb` (1, grammar + `plan_topology.py` + 26 tests), `9e224e47` (2, mint rules + 7 tests), `ff2570ca` (3, apply paths + 4 tests), `1a287344` (4, frontend + 2 tests), `c4a30608` (5, contract copy, sha re-pin, AGENTS.md), docs in the closing commit. `DEC-070` minted; backlog `BL-P5-20260827-46`. Backend `test_agents` 929 green; jest 93/1066 green. Assumption in §3.1 (interaction = one data-pool endpoint + one listed visualization) taken as stated. Observed en route: the pre-existing merge-slot stale raises after in-place removals (persisted by `_mark_stale`) — recorded in the BL entry, not fixed here. Owner live re-test pending.**

Date: 2026-08-27
Branch / tree: `feat/agentscatalog` @ `d4bf71ce`. Line numbers pinned to that commit.
Origin: owner report with `~/Desktop/Screenshot 2026-08-26 at 4.21.26 PM.png` — "the agent correctly detected the cycle, even though it had created that invalid topology itself … when I asked it to fix the problem, it was unable to delete and recreate the necessary nodes and connections". Asked to determine whether this is the deferred `connection` attach target (BL-P5 entry 30 follow-up) or a separate gap.
Evidence: the saved session `.curio/users/guest/projects/cb605bfd-…/agent-sessions/78fbbe35….json` (25 turns) and the project's `spec.trill.json` `agentAttachments[e1da0371].activeProposal`.
Family: dev/52 (dataflowPlan grammar + bulk bridge) → dev/54 (correction rounds) → dev/59 (`removeNodes`/`removeEdges`, DEC-049 digest-pinned removals) → dev/62 (reviewed removals path) → dev/67-3 (fan-in validation, DEC-051 — the acyclicity check was noted as "checks … cycles" on the *manual* path and absent on the plan path) → dev/67-8 (per-edge apply) → dev/93 (DEC-062: plan-template vocabulary) → dev/94 (DEC-063: an instruction must be executable on every path its agent runs on — the rule this memo applies to edges).
Design decisions consumed: DEC-049 (removals digest-pinned, reviewed by name), DEC-051 (topology validated before anything materializes), DEC-063. **New decision proposed: DEC-070** (renumbered 2026-08-27 — DEC-069 was minted the same day by dev/110) — *plan edges carry an explicit kind; the plan validator owns acyclicity over data edges at mint AND apply; a reviewed plan may be edge-only.* Minted with the docs commit if approved.
Backlog: closing entry `BL-P5-20260827-46` (minted with the docs commit). Not related to the `connection` attach target — that item stays deferred (see the BL-P5 entry-30 follow-up line); its memo is dev/113.

---

## 1. Problem Statement

**Verdict first.** This is **not** the connection attach target (that is *attaching an agent to an edge*). It is a set of gaps in the Dataflow Builder's only graph-mutation lane, `dataflow.plan.write`. The agent was never "unable to delete": the session shows it deleted the offending edge **five times** and recreated it each time, because the repair it intended cannot be expressed.

**What the session shows (22:44 → 22:47, five identical rounds).**

1. Turn [7]: *"Since the current plan only adds an edge and does not introduce new nodes, I will include a placeholder note node to ensure the plan structure is valid."* The grammar refuses an additive plan with no nodes (`content.py:379-380`: `nodes must be a non-empty list (unless the plan only removes)`), so the model invented filler. The three empty `curio.notes/note-surface` nodes on the canvas are those placeholders.
2. Every "fix the cycle" / "remove the cycle" turn produced a correct diagnosis and a **valid, applied** plan. The stored `activeProposal`:
   ```json
   {"goal": "Break recursive data loop by converting data edge to interaction edge",
    "nodes": [], "edges": [{"from": "75c25f4b…(vis-vega)", "to": "69e3b1c0…(merge-flow)"}],
    "removeEdges": ["acdd7365…"]}
   ```
   The grammar keeps only `from`/`to`/`toHandle` on an edge (`content.py:461-496`); any `type`/`kind` the model wrote is **silently dropped**. Apply then hardcodes `"sourceHandle": "out"` (`services.py:3006-3011`). Result: remove data edge → recreate the **same data edge** with a fresh id (`2480b41b → 8fe92401 → 605b9549 → acdd7365 → a479f59d`). The agent's intent (`default_preamble.txt:290-322` teaches Interaction edges and which nodes accept them) is domain-correct and **inexpressible** in the contract — the exact DEC-063 failure shape.
3. Nothing refused the cycle. Mint validates endpoints and fan-in only (`services.py:1553-1598`; `_validate_plan_fanin` at `:1413`); there is no acyclicity check. The frontend bulk bridge adds edges through `onEdgesChange({type:"add"})` (`useAgentCanvasMutations.ts:118-137`), **bypassing** `onConnect`'s `hasCycle` (`FlowProvider.tsx:930-938`). The only enforcement is the execution runner's refusal (`runner.py:238-244`), which the agent never sees.
4. The applied-turn line says *"removed 0 nodes"* when an edge was removed (`services.py:3041-3045` counts `remove_node_set` only), and the review card's removals block lists **nodes only** (`AgentReviewCard.tsx:304-316`) — the user approved five edge removals without seeing them named.

**Expected behavior (owner's words, made concrete).** After detecting an invalid cycle, the agent can perform the destructive and corrective operations — remove/recreate/replace/reconnect nodes and edges, including choosing the edge *kind* — as ONE reviewed plan; the plan is refused at mint if the resulting data graph is cyclic (with a corrective message naming the cycle), re-checked at apply, and the agent receives a truthful applied summary (nodes AND edges, removed AND added) it can use to confirm the topology is resolved.

**Why it matters.** The builder is the flagship composite; a five-round loop where every turn "succeeds" while the canvas degrades is worse than a refusal. The fix is contract-level (grammar + validator + materialization + copy), not model-level — a stronger model would have hit the same wall.

## 2. Scope

**Included**
- `utk_curio/backend/app/agents/content.py` — plan grammar: `edges[].kind` (`"data"` default | `"interaction"`); allow edge-only additive plans; `removeEdges` display data.
- `utk_curio/backend/app/agents/services.py` — `_mint_dataflow_plan` (`:1499`): interaction-edge compatibility rule; acyclicity over the NET data graph (saved spec ∪ plan − removals); `removals` display block gains edges; whole-plan apply (`~:2860-3060`) and per-edge apply (`_apply_one_plan_edge :2036`, `apply_plan_edges :2165`) materialize kind + re-check acyclicity (drift → 409 + stale, existing `_mark_stale`); `_log_applied_turn` summary counts edges.
- `utk_curio/backend/app/agents/tools.py:173-187` — `dataflow.plan.write` description: no longer "ADDITIVE … existing nodes are never touched" (contradicts dev/59); names `kind`, `removeEdges`, edge-only plans.
- `utk_curio/llm-prompts/orchestration_instruction.txt` — §2/§2b: edge kinds (interaction edges only into the interaction-capable templates, from a visualization), edge-only plans allowed, "after an apply, re-read the graph (dataflow.read) and confirm the topology before claiming it is fixed".
- Frontend: `useAgentCanvasMutations.ts` bulk + per-edge paths materialize interaction edges (`sourceHandle/targetHandle: "in/out"`, `type: EdgeType.BIDIRECTIONAL_EDGE`, `markerStart` — parity with `useCode.ts:233-238`); `AgentReviewCard.tsx` removals block lists edges; `agentsApi.ts` types.
- Tests (backend `test_agents/`, frontend `tests/attach/`, `tests/content/`).
- Docs: `docs/AGENTS.md` plan paragraph, DEC-070 in the dev/03 table + 2.1 ledger, BL-P5 closing entry, this memo.

**Must be checked but not changed**
- The execution runner's cycle refusal (`runner.py:238-244`) stays the last line of defense; we add the first line, not replace it.
- `hasCycle` in `FlowProvider.tsx:770-783` — the manual path's detector. We do NOT route the bridge through `onConnect` (dev/52 chose direct `onEdgesChange` for bulk idempotency and toast-free apply); the server-side check makes the bridge safe instead.
- `_validate_plan_fanin` — unchanged; the new acyclicity check runs after it on the same NET graph inputs.
- DEC-049 digest pinning — edge removals are already pinned (`removeEdges` validated against saved ids); we only *display* them.

**Out of scope**
- The `connection` attach target (dev/113).
- Teaching the model to prefer Vis → DATA_POOL over Vis → Merge — the compatibility rule makes the wrong target a corrective error, which is the mechanism dev/93/94 proved works; no prompt-engineering beyond that.
- Any change to manual canvas editing.
- Retiring the runner's refusal or the legacy `llmRequest` callers.

## 3. Recommended Implementation Approach

**3.1 Edge kind (G1).** Grammar: `edges[i].kind ∈ {"data","interaction"}`, default `"data"`, present in the canonical plan only when `"interaction"` (dev/59's byte-identity discipline for additive plans). Unknown values → grammar error naming the two accepted kinds. Mint rule (from the preamble's own list, `default_preamble.txt:317-322`, expressed as template-id suffixes like dev/50's `requires`): an interaction edge must connect two nodes whose templates are both in `_INTERACTION_CAPABLE = {"vis-vega", "autk-map", "vis-simple", "data-pool"}` and at least one endpoint is `data-pool`… **Assumption to confirm:** the preamble says "Visualizations can be connected to DATA_POOL"; I read the rule as *one endpoint is data-pool, the other is a visualization from the list*. Violation → corrective error: `edges[i]: an interaction edge connects a visualization (vis-vega, autk-map, vis-simple) to a data-pool node; 69e3b1c0… is merge-flow — use a data edge, or target the data-pool`. This one message would have ended the owner's loop at round one.

Materialization (both apply paths + the bridge): `sourceHandle: "in/out"`, `targetHandle: "in/out"`, and the spec edge gets `"type": "Interaction"` so `TrillGenerator.ts:241-243`/`useCode.ts:233-238` round-trip it. Data edges are byte-identical to today.

**3.2 Acyclicity at mint and apply (G2).** One pure helper in `services.py` (or a small `plan_topology.py` beside `node_context.py`): `_data_cycle(nodes, edges) -> list[str] | None` — Kahn over **data edges only** (interaction edges are excluded, exactly as `FlowProvider.tsx:936` excludes `in/out` and `runner.py` orders over data-flow edges). Mint: build the NET graph = saved nodes − `removeNodes` + plan refs; saved edges − `removeEdges` − cascade + plan edges; refuse with `the plan creates a cycle: n1 → 69e3b1c0… → e71a1ebb… → 75c25f4b… → n1 — remove one data edge or make the feedback edge an interaction edge`. Apply: recompute against the CURRENT saved spec (the user may have edited since mint); a cycle → `_mark_stale` 409 with the same message (the existing stale lane, `services.py:3000-3005` pattern). The correction round reuses `_plan_correction_message` (`:2256`) untouched.

**3.3 Edge-only plans (G3).** `content.py:379-380` → a plan is valid when it has nodes OR edges OR removals; `nodes: []` allowed. Card summary already renders `0 nodes · 1 connections`. Instruction §2 sentence: *"A plan may only add or remove connections — never add filler nodes to make a plan valid."*

**3.4 Truthful removal reporting (G4).** `part.plan.removals` keeps its node entries and gains `removedEdges: [{id, fromLabel, toLabel, kind}]` (labels via the existing `_plan_endpoint_label`). Card block title becomes `Removes N nodes · M connections`, edges listed as `Vis "Metric Distribution" → Merge "Pool Input Merge"`. `_log_applied_turn` summary: `plan added A nodes and B connections, removed C nodes and D connections` (omit zero clauses as today).

**3.5 Post-apply revalidation feedback (G5).** The applied turn the agent already receives (the `Applied: …` agent-role turn) gains one clause computed by the same helper: `topology: acyclic` or — impossible after 3.2 for plans, but reachable when the user edits manually — `topology: cycle through …`. The instruction tells the builder to `dataflow.read` after an apply before claiming a fix. No new tool; no new run.

**Why not route the bridge through `onConnect`?** It would give the manual-path toast and cycle check for free but breaks dev/52's idempotent bulk apply, fires validation toasts per edge during a reviewed apply, and still leaves the *server* accepting cyclic plans for other clients. Server-owned validation is the DEC-051 precedent.

## 4. Data and State Handling

- Source of truth for the graph: the saved spec (mint and apply both read it; the plan is a delta). Acyclicity is computed, never stored.
- Interaction edges persist as Trill `type: "Interaction"` — the existing on-disk representation; nothing new to migrate.
- Correction rounds: grammar and mint errors flow through the existing dev/54 loop; the plan block never reaches the user until valid.
- Drift: apply re-checks; a cycle introduced manually between mint and apply → 409 + stale (existing UX), never a silent partial apply.
- Frontend: the bridge receives `createdEdges` with handles + kind; no new state; the fit-view behavior unchanged.

## 5. UI and UX Requirements

- Review card: interaction edges rendered with a distinguishable label (`⇄ interaction` vs `→`) in the edges list; removals block lists connections by endpoint labels; screen-reader group label updated (`Nodes and connections this plan removes`).
- Applied summary text truthful for edges.
- Canvas: applied interaction edges look exactly like manually drawn ones (bidirectional edge component, arrow markers both ends).
- No toasts on reviewed apply (unchanged).

## 6. Edge Cases

- Plan removes edge X and adds the same `from→to` as a data edge (the owner's loop): now refused at mint by the cycle check when it closes a loop, otherwise allowed (a legitimate handle change).
- Interaction edge where the target is `merge-flow` (the owner's case): compatibility error at mint.
- Interaction edge from `data-pool` to a visualization (reverse direction): accepted — `in/out` handles are symmetric on the canvas.
- Duplicate `(from,to)` with different kinds: still a duplicate (existing rule).
- Removing an edge that is part of a cycle the *user* drew: plan validity computed on the NET graph, so removal-only plans that break a cycle are valid even if the saved spec is cyclic.
- Saved spec already cyclic and the plan does not touch the cycle: **do not refuse** — the plan did not create it; report `topology: cycle through …` in the applied summary (G5) so the agent can propose a fix.
- Cascade: edges incident to removed nodes are removed before the check (dev/59's cascade set).
- Merge-slot assignment (`in_N`) unchanged for data edges; interaction edges never consume a merge slot (`toHandle` on an interaction edge → grammar error).
- Per-edge apply (dev/67-8) applying edges one at a time: the acyclicity re-check runs against the spec + THAT edge only; the remaining pending edges are checked when applied.
- Edge-only plan with zero edges and zero removals → still refused (`the plan changes nothing`).

## 7. Testing Strategy

**Backend `test_content.py` (grammar):** kind default/explicit/invalid; edge-only plan valid; `toHandle` on interaction edge refused; byte-identity of an additive data-only plan vs today's canonical form (regression pin).

**Backend `test_routes.py` / `test_services` (mint):** `TestPlanTopology` — (a) the owner's exact plan against a fixture spec (vis → merge data edge closing Merge→Pool→Vis) → refused with the cycle path in the message; (b) same plan with `kind: interaction` and target `data-pool` → minted, spec edge carries `type: "Interaction"` and `in/out` handles; (c) interaction edge into `merge-flow` → compatibility error; (d) removal-only plan that breaks a user-drawn cycle → minted; (e) plan not touching an existing cycle → minted, applied summary carries `topology: cycle through …`; (f) apply-time drift: user adds a closing edge after mint → 409 + stale; (g) per-edge apply re-check; (h) applied turn text counts removed connections; (i) `removals.removedEdges` labels.

**Frontend:** `useAgentCanvasMutations.test.tsx` — interaction edge materialized with `in/out` handles + `BIDIRECTIONAL_EDGE`; `AgentReviewCard.test.tsx` — removals block lists connections, edges list marks interaction; `agentsApi` type compile.

**Regression gates:** backend `pytest tests/test_agents` green; frontend full jest green; the dev/59/67-3/67-8 suites untouched and green.

## 8. Acceptance Criteria

1. The owner's session, replayed against the fixture: round one returns a corrective message naming the cycle (or the compatibility error), and NO proposal is minted until the plan is acyclic.
2. A plan `{nodes: [], edges: [{from: vis, to: pool, kind: "interaction"}], removeEdges: [vis→merge]}` mints, shows `0 nodes · 1 connections`, `Removes 0 nodes · 1 connections` naming the victim edge, and applies as a bidirectional `in/out` edge whose Trill type is `Interaction`.
3. The applied turn reads `plan added 0 nodes and 1 connections, removed 0 nodes and 1 connections · topology: acyclic`.
4. No plan whose NET data graph is cyclic can be minted or applied; manual cycles are reported, not blamed on the plan.
5. The `dataflow.plan.write` description and the instruction no longer claim plans are additive-only; both name `kind`, `removeEdges`, and edge-only plans.
6. Additive data-only plans are byte-identical to today (pinned).
7. No filler-node incentive remains: an edge-only plan is valid.
8. Full backend and frontend suites green.

## 9. Recommended Commit Breakdown

- **Commit 1 — grammar + topology helper + tests.** `content.py` (kind, edge-only), `_data_cycle` helper, `test_content.py`.
- **Commit 2 — mint rules.** Compatibility + acyclicity at mint, removal display data, corrective messages; `TestPlanTopology` (a–e, i).
- **Commit 3 — apply paths.** Whole-plan and per-edge materialization of kind + re-check + stale lane; summary line; tests (f–h).
- **Commit 4 — frontend.** Bridge materialization, review card removals/edge labels, types, tests.
- **Commit 5 — contract copy.** `tools.py` description, `orchestration_instruction.txt` (sha-pinned roster update per dev/90's procedure), `docs/AGENTS.md`.
- **Commit 6 — docs.** DEC-070, BL-P5 closing entry, memo status.

Multi-session protocol applies (pathspec commits; `git status` before every add; `git diff --cached -- <file>` before touching a file another session staged).

## 10. Engineering Quality Checklist

- [ ] One acyclicity helper, used by mint, both apply paths, and the applied summary — no per-caller copies.
- [ ] Interaction-capable template list defined once (backend constant), sourced from the preamble's list; the preamble is not duplicated in code beyond that set.
- [ ] Additive data-only plans byte-identical (test-pinned).
- [ ] Corrective messages name the fix (DEC-062/063 discipline).
- [ ] Drift handled through the existing stale lane; no new status.
- [ ] Card and summary truthful for edges; a11y labels updated.
- [ ] No frontend validation duplicated from the server; the bridge trusts the reviewed, server-validated result.
- [ ] Runner refusal untouched and still tested.
