# dev/125 — The interaction-edge capability on `imp/agentcatalog`: the Dataflow Builder can still diagnose a cycle it cannot repair

**Status: IMPLEMENTED (2026-09-10) on `imp/agentcatalog` — closes dev/121 **F2**,
`BL-P5-20260910-59`. No new `DEC`: `DEC-070` already states this posture and is already in
the dev/03 table on this branch; the plans tree is shared while the code is not, so what was
missing here was the implementation, not the decision. Ports dev/112 (`6d5f89fb`…`c4a30608`)
from `feat/agentscatalog`, which is never merged back.**

**Suites: `tests/test_agents` 2187 passed (2146 before); `tests/test_projects` +
`tests/test_datasets` 769; `tests/test_packages` 864 passed / 3 skipped, green but for the
pre-existing unrelated `test_teardown_preserves_an_empty_pythonpath_entry` (recorded by
dev/121 and dev/124 before this work); jest 2384 across 205 suites; `tsc --noEmit` clean.
The load-bearing result: all eight `capability-gap:interaction-edge` fixtures reconstruct to
exactly 1.0 through the production path, with no fixture's expected graph edited.**

**Five things changed from the plan while building — each marked §12 below.** Two are
corrections to dev/112 that the shipped corpus forced (the duplicate-edge key must include
the kind; the interaction-capable set must name `autk-grammar`, not the preamble's
non-existent `autk-map`). Two are harness defects that closing the gap exposed, both dead
code paths for as long as the fixtures that would exercise them were blocked at the oracle.
One is a fixture edit the memo said it would not make: fixture 08's `intents` gained an
`outputKind` — an added, scored, truthful assertion, not a weakened expectation.

Date: 2026-09-09
Branch / tree: `imp/agentcatalog` @ `b87eb1b2`. Every line number below was read on that commit.
Origin: owner request — "implement the deferred follow-up: interaction-edge capability", plus
"the agent correctly detected the presence of the cycle; besides, it was it that created it.
But when I asked for a fix, it couldn't delete and recreate some nodes. Is this related to the
deferred follow-ups: connection attach target deferred (BL-30), and interaction-edge
capability? See evidence in `~/Desktop/Screenshot 2026-08-26 at 4.21.26 PM.png`".
Family: dev/52 (dataflowPlan grammar + bulk bridge) → dev/59 (`removeNodes`/`removeEdges`) →
dev/62 (reviewed removals) → dev/67-3 (fan-in, `DEC-051`) → dev/67-8 (per-edge apply) →
dev/93 (`DEC-062`) → dev/94 (`DEC-063`) → **dev/112 (`DEC-070`, implemented on
`feat/agentscatalog` only)** → dev/121 F2 (this port) → dev/122 §"excluded by construction".
Design decisions consumed: `DEC-049`, `DEC-051`, `DEC-063`, `DEC-070`, `DEC-076`, `DEC-077`.

---

## 0. The investigation answer, first

**The screenshot is the origin report of dev/112.** `Screenshot 2026-08-26 at 4.21.26 PM.png`
shows session `78fbbe35`, and dev/112's own header names that same screenshot and that same
session id as its evidence. So the question has already been investigated once, in depth,
against the saved session file (25 turns) rather than the screenshot alone. Its verdict:

- **Not** the `connection` attach target (the BL-P5 entry-30 deferral the owner calls BL-30).
  That item is *attaching an agent to an edge*; it was re-opened and closed the same day by
  dev/113 (`DEC-071`, `BL-P5-20260827-47`). It is unrelated to this failure, and implementing
  it would not have changed a single turn of the owner's session.
- **Yes** the interaction-edge capability — and four sibling gaps in the same lane.

**And the agent was never "unable to delete".** The session shows it deleted the offending
edge five times and recreated it five times (`2480b41b → 8fe92401 → 605b9549 → acdd7365 →
a479f59d`). It removed a data edge and asked for an *Interaction* edge in its place; the
grammar kept only `from`/`to`/`toHandle` and dropped the kind, so the apply materialized the
same data edge with a fresh id. The screenshot catches the loop mid-flight: the reply reads
*"the edge must be changed to an **Interaction** type"* — a domain-correct repair the contract
has no way to carry. That is the `DEC-063` failure shape exactly: an instruction (the
preamble teaches Interaction edges at `default_preamble.txt:290` and lists the four capable
node kinds at `:317-322`) that is not executable on the path its agent runs on.

**What is new here is the branch.** dev/112 shipped on `feat/agentscatalog`
(`6d5f89fb`…`c4a30608`). The merge base of `imp/agentcatalog` and `feat/agentscatalog` is
`6f3c07a8` (dev/106 commit 6); `imp` is 654 commits ahead of it, `feat` 41, and feat is never
merged back. I verified this branch has none of it: `utk_curio/backend/app/agents/plan_topology.py`
does not exist, and every defect dev/112 named is present here verbatim (§1). dev/121 recorded
this as **F2**, and its harness was built to detect the moment it closes: eight fixtures
declare `capability.needs: ["interaction-edge"]` and report a named capability gap instead of
a wrong score.

**So: implementing the deferred follow-up does fix the reported issue on this branch**, and
the connection attach target has nothing to do with it.

---

## 1. Problem Statement

The Dataflow Builder's only graph-mutation lane is `dataflow.plan.write`. On this branch it
has five defects, all confirmed by reading the code at `b87eb1b2`.

**G1 — the plan grammar cannot express an edge kind.** `content.py:544-586` parses an edge
into `{from, to}` plus an optional `toHandle` and nothing else; a `kind` or `type` the model
writes is silently dropped, with no error to correct against. Both apply paths then hardcode
`"sourceHandle": "out"` and set no `type` (`services.py:2011-2018` per-edge,
`services.py:3021-3027` whole-plan), so **every** agent-created edge is a data edge. The
canvas already knows the other shape — `useCode.ts:246-251` materializes a Trill
`type: "Interaction"` edge as `in/out` on both handles plus `BIDIRECTIONAL_EDGE` and a
`markerStart`, and `FlowProvider.tsx:1010-1016` does the same for a hand-drawn one — and the
backend already *reads* it (`services.py:1906` and `:1973` exclude `type == "Interaction"`
from fan-in and duplicate detection; dev/118's Solve waves exclude it at `services.py:5099`).
Only the write side is missing.

**G2 — nothing refuses a cycle before it reaches the canvas.** Mint validates templates,
revision targets and fan-in (`services.py:1485-1488`, `_validate_plan_fanin` at `:1312`) —
there is no acyclicity check. The frontend bridge adds edges with
`onEdgesChange({type: "add"})` (`useAgentCanvasMutations.ts:79-93` and `:117-133`), which
bypasses `onConnect` and therefore the canvas's own `hasCycle` refusal
(`FlowProvider.tsx:811-822`, applied at `:977`). **This is why the agent created a topology
the user could not have drawn by hand** — the owner's "it was it that created it". The only
enforcement left is the execution runner (`runner.py:284-291`), which refuses at run time and
whose message the agent never sees.

**G3 — an edge-only plan is refused, which pays the model to invent nodes.**
`content.py:466-467`: `nodes must be a non-empty list (unless the plan only removes)`. A plan
that only adds a connection is invalid. The session's turn [7] is the model reasoning its way
around it — *"I will include a placeholder note node to ensure the plan structure is valid"* —
and the empty `curio.notes/note-surface` node visible on the canvas in the screenshot is that
filler.

**G4 — removals are under-reported, so the user approves what they cannot see.** The applied
line is built at `services.py:3057-3061` from `remove_node_set` only, while it is *emitted*
whenever `remove_node_set or removed_edge_ids` — so removing one edge and zero nodes prints
"removed 0 nodes", which is what the screenshot's card says. The review card's removals block
lists nodes only (`AgentReviewCard.tsx:379-395`, `aria-label="Nodes this plan removes"`),
although the mint already computes edge endpoint labels for other purposes
(`_plan_endpoint_label`, `services.py:1867`, used at `:1566-1567`). The owner approved five
edge removals without one of them being named.

**G5 — the agent gets no topology verdict, and cannot read one either.** The applied turn
reports counts, never the resulting shape, so "is the cycle gone?" is unanswerable from
inside the loop and the model re-diagnoses from a stale reading. Worse on this branch than on
feat: `dataflow.read`'s edge projection (`tools.py:465-471`) carries `id`, `source`, `target`
and the two handles — **not** `type`. Even after G1 lands, an agent that re-reads the graph to
confirm its own repair cannot see that the edge it just made is an interaction edge.

**Two contract texts actively teach the wrong thing.** `tools.py:176-189` still describes the
lane as an "**ADDITIVE** plan" where "existing nodes are never touched" — untrue since dev/59
— and `orchestration_instruction.txt:9` (§2b) permits removals *"ONLY when the user asked to
remove or replace something"*. The owner asked to "fix the cycle", not to remove anything. A
model that reads its own contract literally concludes it may not delete. That is the most
direct textual cause of "it couldn't delete and recreate".

**Expected behavior.** After detecting an invalid cycle the builder can express the whole
repair — remove, add, reconnect, and *choose the edge kind* — as ONE reviewed plan; the plan
is refused at mint if the resulting data graph is cyclic, with a corrective message naming the
cycle and the fix; the check is repeated at apply against the live spec; the review card names
every removed connection; and the applied turn ends with a topology verdict the agent is told
to read before claiming a repair.

**Why it matters.** A five-round loop in which every turn "succeeds" while the canvas silently
degrades is worse than one honest refusal. The failure is contract-level, not model-level — a
stronger model hits the same wall, which is precisely why dev/121's harness reports it as a
capability gap rather than a low score.

## 2. Scope

**Included — the dev/112 port (`DEC-070` applied to this branch)**

| File | Change | Port cost |
|---|---|---|
| `agents/content.py` | `edges[].kind ∈ {data, interaction}`, default `data`, emitted only when `interaction`; edge-only plans valid | patch applies clean |
| `agents/plan_topology.py` | **new** — the one acyclicity + interaction-compatibility helper | new file |
| `agents/services.py` `_mint_dataflow_plan` | interaction rule, acyclicity over the NET data graph, `removedEdges` display block | **manual — conflicts** |
| `agents/services.py` apply paths | materialize kind, re-check before mutating, truthful summary, topology verdict | **manual — conflicts** |
| `agents/tools.py` | `dataflow.plan.write` description; **and** `kind` in the `dataflow.read` edge projection (§3.6) | clean + one addition |
| `llm-prompts/orchestration_instruction.txt` | §2/§2b: kinds, edge-only plans, removals, read the verdict back | clean; **sha re-pin** |
| `useAgentCanvasMutations.ts`, `AgentReviewCard.tsx`, `agentsApi.ts`, `agentCanvasEvents.ts` | one `appliedEdgeToCanvasEdge`; removals name connections | patches apply clean |

**Included — this branch only (absent from dev/112, required to close dev/121 F2)**

- `agents/evaluation/oracle.py` — `EXPRESSIBLE_EDGE_KINDS` gains `"interaction"`; the plan
  serializer emits `kind` instead of raising `Unrepresentable`.
- `agents/evaluation/attempt.py` — `UNEXPRESSIBLE_EDGE_KINDS` empties to `()`.
- The eight fixtures (`07`, `08`, `09`, and legacy `Interaction_Vega`, `Interaction_Vega_Simple`,
  `Interaction_Vega_Autark`, `Interaction_Autark`, `Regression`) start scoring. **No fixture
  file is edited** — that was dev/121's promise and this port must keep it.
- `agents/training/dataset.py` needs no change (it excludes by the gap the oracle *raises*,
  `:217`), but its tests pin the exclusion and must be updated with the eight fixtures now
  representable.
- `docs/AGENT-CATALOG.md` — this branch's replacement for the `docs/AGENTS.md` dev/112 edited.

**Must be checked, not changed**

- `runner.py:284-291` — the runner's cycle refusal stays the last line of defense; this adds
  the first line, it does not replace it.
- `FlowProvider.tsx` `hasCycle` / `onConnect` — the bridge is **not** rerouted through
  `onConnect` (dev/52 chose direct `onEdgesChange` for idempotent, toast-free bulk apply, and
  a server-side check protects every client, not just this one — the `DEC-051` precedent).
- `_validate_plan_fanin` — unchanged; acyclicity runs after it on the same NET inputs, and
  interaction edges are excluded from fan-in (dev/112 commit 2 already does this).
- dev/118's Solve waves (`services.py:5099`) — already data-edge-only; confirm untouched.
- dev/124's save-basis rule — agent applies write through `write_spec` as internal callers
  with no `baseRevision`, so the deliberate escape applies and no interaction is expected.
  Confirm by test, do not weaken.
- `DEC-049` digest pinning — edge removals are already validated against saved ids; this only
  *displays* them.

**Out of scope**

- The `connection` attach target / dev/113 (`node.insert`) — a different concept, and it is
  also absent from this branch. Porting it is a separate decision with its own demand.
- Teaching the model to prefer Vis → DATA_POOL. The compatibility rule turns a wrong target
  into a corrective error; that mechanism is what dev/93 and dev/94 proved works.
- Any change to manual canvas editing, to the legacy `llmRequest` callers, or to the runner.
- Re-scoring or approving the 31 prompts (dev/121 F8) — the eight fixtures change *status*,
  not content.

## 3. Recommended Implementation Approach

The design is `DEC-070`, already approved and recorded. What follows is the port, plus the
three places this branch differs from the one it was written on.

**3.1 Edge kind (G1).** Grammar: `edges[i].kind ∈ {"data","interaction"}`, default `"data"`,
present in the canonical plan **only** when `"interaction"` — dev/59's byte-identity
discipline, so today's additive data-only plans hash exactly as they do now. An unknown value
is a grammar error naming the two accepted kinds; `toHandle` on an interaction edge is a
grammar error (an interaction link consumes no merge slot).

Mint rule, taken from the preamble's own list (`default_preamble.txt:317-322`) and expressed
as template-id suffixes the way dev/50 expressed `requires`:
`_INTERACTION_CAPABLE = {"vis-vega", "autk-map", "vis-simple", "data-pool"}`, at least one
endpoint `data-pool`, the other a visualization from that set. A violation is a corrective
error that names the offender and the fix:
`edges[0]: an interaction edge connects a visualization (vis-vega, autk-map, vis-simple) to a data-pool node; 69e3b1c0… is merge-flow — use a data edge, or target the data-pool`.
**That one message ends the owner's five-round loop at round one.**

**Assumption, carried over from dev/112 §3.1 and re-confirmed here:** the preamble says
"Visualizations can be connected to DATA_POOL"; the rule is read as *one endpoint is
data-pool, the other is a listed visualization*. Direction is free — `in/out` handles are
symmetric on the canvas.

**A tension worth stating rather than hiding.** dev/119 (`DEC-076`) retired hand-kept lists of
node kinds in favour of the template roster, and this rule is a hand-kept list. It is
defensible only because **no template metadata declares interaction capability today**:
`available_templates` exports `maxIncomingEdges` as the rendered arity truth
(`packages/services.py:727`) but nothing equivalent for interaction, and the frontend's
`ContainerConfig.handleType: 'in' | 'out' | 'in/out'` (`registry/types.ts:98`,
`packagesClient.ts:216-222`) is a **different concept wearing the same string** — it means
"this node has both input and output ports", derived from port counts, not "this node accepts
an interaction link". Anyone reading it as the rendered truth will be wrong. So: keep the set
in `plan_topology.py` as the single definition, comment it with this paragraph's reason, and
record a follow-up — if a template ever declares interaction capability, the set reads from
the roster and stops being a list.

Materialization, in both apply paths and the bridge: `sourceHandle: "in/out"`,
`targetHandle: "in/out"`, spec edge `"type": "Interaction"` — the on-disk representation
`TrillGenerator.ts:302` and `useCode.ts:246-251` already round-trip. Data edges byte-identical.

**3.2 Acyclicity at mint and apply (G2).** `plan_topology.py` is **the one helper** — a pure
module beside `node_context.py`, no service imports: Kahn over **data edges only** (interaction
edges excluded, exactly as `FlowProvider.tsx:616`/`:1191` exclude `in/out` and as the runner
orders over data edges). Mint builds the NET graph — saved nodes − `removeNodes` + plan refs,
saved edges − `removeEdges` − cascade + plan edges — and refuses with the path named and the
fix suggested:
`the plan creates a cycle: n1 → 69e3b1c0… → e71a1ebb… → 75c25f4b… → n1 — remove one data edge or make the feedback edge an interaction edge`.
`closing_plan_edges` blames a plan only for cycles **it** closes: a cycle the user drew and the
plan does not touch is *reported*, never refused. Apply recomputes against the CURRENT spec
(the user may have edited since mint): whole-plan → `_mark_stale` 409 with the same message,
before any mutation; per-edge (dev/67-8) → that edge refused by name in its result row, the
rest unaffected. The correction round reuses the existing dev/54 loop untouched.

**3.3 Edge-only plans (G3).** A plan is valid with nodes **or** edges **or** removals; only
"nothing at all" is refused (`the plan changes nothing`). The instruction gains one sentence:
*"A plan may add or remove connections alone — never add filler nodes to make a plan valid."*
The card already renders `0 nodes · 1 connections`.

**3.4 Truthful removals (G4).** `part.plan.removals` keeps its node entries and gains
`removedEdges: [{id, fromLabel, toLabel, kind}]` built from the existing `_plan_endpoint_label`.
Card title becomes `Removes N nodes · M connections`, connections listed by endpoint label
(`Vis "Metric Distribution" → Merge "Pool Input Merge"`), group label
`Nodes and connections this plan removes`. The applied line counts both and drops zero clauses:
`plan added 0 nodes and 1 connections, removed 0 nodes and 1 connections`.

**3.5 The topology verdict (G5).** Every applied turn ends with one clause from the same
helper: `Topology: acyclic.` or `Topology: cycle through ….` The instruction requires reading
it — and re-reading the graph — before claiming a repair. No new tool, no new run.

**3.6 `dataflow.read` carries the edge kind (this branch's addition).** `tools.py:465-471`
projects `id`, `source`, `target`, `sourceHandle`, `targetHandle`. Add
`kind: "interaction"` (emitted only when interaction, matching the plan grammar's discipline)
derived from the spec edge's `type`. Without it §3.5's instruction — *re-read and confirm* —
is not executable, which is the same `DEC-063` defect this memo exists to fix, one layer up.
One function, one field; the projection's stated bound ("if it exceeds the budget, node goals
shrink next — never the edge list") is unaffected by a key present on a minority of edges.

**3.7 The harness closes its own gap (dev/121 F2).** `EXPRESSIBLE_EDGE_KINDS` gains
`"interaction"` and the oracle serializes `kind` on the plan; `UNEXPRESSIBLE_EDGE_KINDS`
empties. `canonical.py` needs nothing — `edge_kind` (`:264`) already reads both spellings the
corpus carries, and `INTERACTION_EDGE_TYPE` (`:45`) is already the Trill `"Interaction"`. The
eight fixtures then reconstruct through the real path and score on their own declared
expectations, with no fixture edited. **This is the acceptance evidence for the whole memo**:
the reconstruction that previously could not be expressed now scores, or the port is
incomplete and the harness says exactly where.

**Why not route the bridge through `onConnect`?** It would inherit the manual cycle check for
free, but it breaks dev/52's idempotent bulk apply, fires a validation toast per edge during a
reviewed apply, and leaves the *server* accepting cyclic plans for every other client.
Server-owned validation is the `DEC-051` precedent, and it is what makes the bridge safe.

## 4. Data and State Handling

- **Source of truth**: the saved spec. Mint and apply both read it; a plan is a delta.
  Acyclicity is *computed*, never stored — there is no new field and nothing to migrate.
- **Derived values**: the NET graph (saved − removals − cascade + plan) is built the same way
  in three places (mint, whole-plan apply, per-edge apply) and therefore lives in exactly one
  function in `plan_topology.py`. Interaction edges persist as Trill `type: "Interaction"`,
  the representation already on disk.
- **Loading / empty / error / success**: unchanged lanes. Grammar and mint errors flow through
  the dev/54 correction rounds; an invalid plan never reaches the user. Apply refusals reuse
  the existing `_mark_stale` 409 + stale-proposal UX.
- **After user actions**: the apply writes once, through `write_spec` — dev/124's one
  chokepoint, bumping `.spec.rev`. The re-check happens **before** any mutation (dev/112's
  rule, and the same ordering dev/112 got wrong once and fixed: `_mark_stale` itself persists
  the spec, so a refusal must be decided before the first edit).
- **Staleness / races / flicker**: mint pins the graph shape digest (`DEC-049`) and apply
  re-checks it; a cycle introduced manually between mint and apply is a 409 with the cycle
  named, never a silent partial apply. The per-edge lane re-checks per edge, so a stale plan
  degrades to named refusals rather than a broken graph. The frontend bridge stays idempotent
  per plan id; no new client state is introduced.

## 5. UI and UX Requirements

- **Review card**: removals block titled `Removes N nodes · M connections`; connections listed
  by endpoint label; interaction edges marked distinguishably in the edges list (`⇄` vs `→`)
  with the marker's meaning in text, not colour or glyph alone.
- **Applied summary**: counts nodes *and* connections, added *and* removed; ends with the
  topology verdict.
- **Canvas**: an applied interaction edge is indistinguishable from a hand-drawn one —
  `BIDIRECTIONAL_EDGE`, arrow markers at both ends, `in/out` handles.
- **Accessibility**: the removals group label becomes `Nodes and connections this plan
  removes`; the `⇄` marker is accompanied by the word *interaction* in the accessible name,
  never by the glyph alone; the card's existing focus order and semantics are unchanged.
- **No new toast** on a reviewed apply, no layout shift, no re-fit beyond the existing one.

## 6. Edge Cases

- Plan removes edge X and adds the same `from→to` as a **data** edge (the owner's loop):
  refused at mint when it closes a cycle; allowed otherwise (a legitimate handle change).
- Interaction edge targeting `merge-flow` (the owner's actual case): compatibility error.
- Interaction edge from `data-pool` **to** a visualization: accepted — handles are symmetric.
- Duplicate `(from,to)` with different kinds: still a duplicate (the existing rule stands).
- `toHandle` on an interaction edge: grammar error.
- The saved spec is **already cyclic** and the plan does not touch the cycle: **do not refuse**
  — the plan did not create it. Report it in the verdict so the agent can propose a repair.
- A removal-only plan that breaks a user-drawn cycle: valid, because validity is computed on
  the NET graph, not on the saved one.
- Cascade: edges incident to removed nodes leave with them before the check.
- Per-edge apply, edges arriving one at a time: each is checked against the spec **plus that
  edge**; pending edges are checked when they are applied.
- Edge-only plan with zero edges and zero removals: refused (`the plan changes nothing`).
- An interaction edge between two nodes the plan itself creates (neither exists yet): the
  compatibility rule reads plan node types, so it works before materialization.
- Malformed spec edges (`type` absent, `None`, or an unexpected string): treated as data, the
  existing default everywhere else in the file.
- A cycle entirely through interaction edges: not a cycle (they carry selection, not data) —
  the runner agrees.

## 7. Testing Strategy

**Backend `test_content.py`** — kind default / explicit / invalid; edge-only plan valid;
`toHandle` on an interaction edge refused; **byte-identity of an additive data-only plan
against today's canonical form** (the regression pin that protects every existing fixture).

**Backend `test_plan_topology.py`** (new, ported) — the helper in isolation: acyclic, simple
cycle, cycle only through interaction edges (not a cycle), `closing_plan_edges` blaming only
the plan's own edges, compatibility matrix over the four capable templates.

**Backend `test_routes.py` — `TestPlanTopology`** — (a) the owner's exact plan against a
fixture spec → refused with the cycle path named; (b) the same plan with `kind: "interaction"`
targeting the data-pool → minted, spec edge carries `type: "Interaction"` and `in/out`;
(c) interaction edge into `merge-flow` → compatibility error; (d) removal-only plan breaking a
user-drawn cycle → minted; (e) plan not touching an existing cycle → minted, verdict reports
it; (f) apply-time drift → 409 + stale, spec unmutated; (g) per-edge apply re-check refuses one
row by name; (h) applied turn counts removed connections and carries the verdict;
(i) `removals.removedEdges` labels; (j) `dataflow.read` projects `kind` (§3.6); (k) an agent
apply still writes through `write_spec` without a `baseRevision` and dev/124's rule does not
fire.

**Backend `test_builtin.py`** — the Dataflow Builder prompt sha256 re-pinned (`:573`, `:624`).

**Backend evaluation suites** — `test_example_reconstruction.py`: the eight interaction
fixtures score against their declared expectations instead of reporting the gap;
`test_reconstruction_scoring.py`: `capability-gap:interaction-edge` is no longer produced for a
declared-and-now-expressible need, while the *mechanism* keeps a test (a synthetic unexpressible
kind) so the gap machinery does not rot; `test_training_dataset.py` / `test_training_routes.py`:
the eight fixtures are no longer excluded by construction (dev/122 §"excluded by construction"
is now satisfied differently — they are representable, so they are eligible subject to review
status, which is `pending-owner-review` and still refuses).

**Frontend** — `useAgentCanvasMutations.test.tsx`: an interaction edge materializes with
`in/out` handles, `BIDIRECTIONAL_EDGE` and `markerStart`, and a data edge is unchanged;
`AgentReviewCard.test.tsx`: removals block names connections, edges list marks interaction,
group label updated; `agentsApi` types compile.

**Regression gates** — `tests/test_agents` green (2146 at dev/124); `tests/test_projects`,
`tests/test_packages`, `tests/test_datasets` unchanged (the one pre-existing
`test_teardown_preserves_an_empty_pythonpath_entry` failure stays recorded, not fixed here);
full jest (2382 / 205 suites at dev/124); `tsc --noEmit` clean. Node/npm via the `curio-feat`
conda env.

**Required before this is considered complete**: `test_content.py` byte-identity,
`TestPlanTopology` (a)–(c) and (f), the eight fixtures scoring, and the frontend
materialization test. The rest is coverage; those five are the memo's claims.

## 8. Acceptance Criteria

1. Replaying the owner's round one against a fixture spec returns a corrective message that
   names the cycle or the compatibility violation, and **no proposal is minted** until the
   plan is acyclic.
2. `{nodes: [], edges: [{from: vis, to: pool, kind: "interaction"}], removeEdges: [vis→merge]}`
   mints; the card shows `0 nodes · 1 connections` and `Removes 0 nodes · 1 connections` with
   the victim edge named; the apply produces a bidirectional `in/out` edge whose spec `type`
   is `Interaction`.
3. The applied turn reads
   `Applied: plan added 0 nodes and 1 connections, removed 0 nodes and 1 connections.` followed
   by `Topology: acyclic.` — no "removed 0 nodes" after an edge removal, ever.
4. No plan whose NET data graph is cyclic can be minted or applied, through either apply lane;
   a cycle the user drew is **reported**, never blamed on the plan.
5. `dataflow.plan.write`'s description and the orchestration instruction no longer claim plans
   are additive-only; both name `kind`, `removeEdges`, edge-only plans and the verdict
   read-back. The prompt sha pin is updated in the same commit as the text.
6. `dataflow.read` shows `kind` on interaction edges, so the instruction's "re-read and confirm"
   is executable.
7. Additive data-only plans are byte-identical to today (pinned by test).
8. No filler-node incentive remains: an edge-only plan is valid.
9. `UNEXPRESSIBLE_EDGE_KINDS == ()`; the eight interaction fixtures score against their own
   expectations; **no fixture file was edited**; and the capability-gap machinery still has a
   test.
10. Full backend and frontend suites green; the owner can re-run the screenshot's scenario and
    get a repair instead of a loop.

## 9. Recommended Commit Breakdown

1. **Grammar + the helper.** `content.py` (kind, edge-only), new `plan_topology.py`,
   `test_content.py`, `test_plan_topology.py`. *(dev/112 commit 1 applies clean.)*
2. **Mint rules.** Compatibility + acyclicity at mint, `removedEdges` display data, corrective
   messages, fan-in ignoring interaction edges; `TestPlanTopology` (a)–(e), (i).
   *(Manual port — conflicts against 654 commits of divergence.)*
3. **Apply paths.** Whole-plan and per-edge materialization, the pre-mutation re-check and
   stale lane, the truthful summary, the topology verdict; tests (f)–(h), (k).
   *(Manual port.)*
4. **Frontend.** One `appliedEdgeToCanvasEdge` for both bridge paths, the review card's
   connections and interaction marks, types, tests. *(dev/112 commit 4 applies clean.)*
5. **Contract copy.** `tools.py` description **and** the `dataflow.read` `kind` projection,
   `orchestration_instruction.txt` with the sha re-pin in `test_builtin.py`,
   `docs/AGENT-CATALOG.md`. *(dev/112 commit 5 applies clean apart from the renamed doc.)*
6. **The harness closes F2.** `oracle.py`, `attempt.py`, the evaluation and training test
   updates; dev/121's F2 marked closed in its memo.
7. **Docs and ledgers.** `BL-P5-<date>-59`, dev/00 index row, dev/03's `DEC-070` row gains a
   note that the decision is now implemented on both lines, dev/121 F2 closed, this memo →
   IMPLEMENTED.

Commits 2 and 3 are the only ones carrying real risk; they are separated from the clean ports
deliberately so a bisect lands on the hand-written code.

## 10. Engineering Quality Checklist

- **No duplicated logic**: one `plan_topology.py` serves mint, both apply lanes and the
  verdict; one `appliedEdgeToCanvasEdge` serves both bridge paths; one `_INTERACTION_CAPABLE`
  set, commented with why it is a set and not a roster read.
- **Types explicit**: `kind` is a closed literal in the grammar, in `agentsApi.ts` and in
  `agentCanvasEvents.ts`; `tsc --noEmit` clean.
- **Components stay focused**: the review card renders what the part carries; no new client
  computation of topology.
- **State predictable, races handled**: the re-check runs before any mutation, on the live
  spec, in both lanes; `_mark_stale` is only reached on a decided refusal.
- **Consistency across surfaces**: an applied interaction edge is identical to a hand-drawn one
  on the canvas, in the spec, in the Trill round-trip, and in what `dataflow.read` reports.
- **Loading / empty / error / success**: existing lanes reused, none widened.
- **Accessibility**: group labels and accessible names updated; no meaning carried by a glyph
  alone.
- **Tests cover behavior and the regression**: byte-identity pin, the owner's exact scenario,
  and the harness's eight fixtures as the end-to-end proof.
- **Conventions followed**: `DEC-070` reused rather than re-minted (dev/124's precedent for not
  minting a second decision for the same rule); memo number checked on disk; plans tracked in
  their own commits.
- **No unnecessary re-renders or visual instability**: the bridge's event shape is unchanged;
  only the edge object it builds gains fields.

## 11. Recorded follow-ups

- **F1 — interaction capability as template metadata.** If a template ever declares that it
  accepts an interaction link, `_INTERACTION_CAPABLE` reads it from the roster and stops being
  a hand-kept list (`DEC-076`'s rule; see §3.1 for why it cannot be read today, and for the
  `ContainerConfig.handleType` name collision that must not be mistaken for it).
- **F2 — dev/113 (`node.insert` / the `connection` attach target) is also absent from this
  branch.** Not needed for this repair and deliberately not ported here. Re-open on demand,
  with its own memo.
- **F3 — the two apply lanes still build the NET graph from three call sites.** They will call
  one helper after this memo, but the *cascade* computation is still written twice (mint at
  `services.py:1489-1496`, apply in place). Worth unifying the next time either is touched.


---

## 12. What changed while building

**§12.1 — the duplicate-edge key must include the kind (deviation from dev/112 §6).**
dev/112 listed "duplicate `(from,to)` with different kinds: still a duplicate (existing
rule)" as a settled edge case. The corpus disproves it. `docs/examples/dataflows/
Interaction_Vega.json` — and `Interaction_Vega_Simple`, `Interaction_Vega_Autark`,
`Interaction_Autark` — carry BOTH a data edge and an `Interaction` edge between the same
data-pool and the same visualization, with the same orientation. That is what a linked view
IS: the pool feeds the chart, the chart feeds selections back. Under the old key those graphs
were unproposable, and all eight fixtures scored **0.000** with the entire plan refused. The
key is now `(from, to, kind)`. dev/112 could not have known this — it had one session's
evidence; this branch has thirty-one reconstructions.

**§12.2 — `_INTERACTION_CAPABLE` must name `autk-grammar` (deviation, same class).**
dev/112 transcribed the preamble's own list (`VIS_VEGA`, `AUTK_MAP`, `VIS_SIMPLE`,
`DATA_POOL`). On this branch `autk-map` appears in the prompt text and **in no manifest**;
the roster's Autark template is `curio.builtin/autk-grammar`, and every shipped Autark
interaction edge wires into it. So the transcribed list refused the product's own examples.
This is precisely the drift `DEC-076` retired hand-kept name lists for — and the memo's §3.1
predicted the risk in the abstract before the corpus demonstrated it concretely. `autk-map`
is kept in the set only so a future roster entry by that name is not refused; it names no
lie and costs nothing. F1 stands: the day a template declares the capability, this set reads
from the roster.

**§12.3 — the fake sandbox's declared-content lookup had never fired.**
`_reconstruction_driver.kind_for` looked up the payload's code in `code_to_kind` by
**equality**. The runtime wraps every dispatched node in a determinism preamble and indents
it into a function body, so the payload is never byte-equal — nor even a superstring — of the
content a fixture declared. The lookup had therefore never matched for any fixture since
dev/121, and every node silently fell through to the word heuristic below it. Now matched
whitespace-insensitively, longest declared content first.

**§12.4 — that heuristic mis-typed fixture 08's JS node.** The heuristic answers "raster" for
any code containing the word. Example 08's JS computation returns an array of layer objects
and only *mentions* raster in its comments, so the fake sandbox reported `raster`, the
downstream Autark grammar (which accepts DATAFRAME, GEODATAFRAME, JSON, LIST) refused the
type, and Solve spent three correction rounds on content that was never wrong — ending
`failed`, with the node's content never persisted. Both §12.3 and §12.4 were unreachable
until this memo let fixture 08 past the oracle for the first time. **Closing a capability gap
is also how you find out what the gap was hiding.**

**§12.5 — one fixture file changed, and §2 said none would.** Fixture 08's `intents` gained
`{"ref": "analysis1", "outputKind": "list"}`. Stated plainly because the memo promised
otherwise: this is an **added** assertion, not a relaxed one — `outputKind` is scored (absent
means *not measured*, so declaring it enlarges the denominator), it is truthful (the example's
JS returns `layers`), and it uses a field the fixture schema defines for exactly this purpose.
No fixture's `expected` graph was touched, and the eight still declare `interaction-edge` in
`capability.needs` — the record of what this branch once could not do, which is worth keeping
even now that it can.
