# Consolidation Memo: `dataflow-researcher` Session vs. the Plan of Record

Date: 2026-08-04
Status: approved-analysis (consolidation record — this memo assigns requirements to owners; it is
not an implementation memo and introduces no parallel plan)
Sources consolidated: `dataflow-researcher.md` (the brainstorm session, two parts: the
Plan→Revise→Solve→Run recording analysis, and the agentic research-node idea) against `dev/15`
(composite specs), `dev/16` (package capabilities), `dev/48` (Node Builder memo), `dev/03`
(development plan: DEC-007/009/034/035/045, §Delegation :366, boundary rules :193-198), `dev/05`
(blueprint Step 5, DEC-038 v2 gating), `dev/41`/`DEC-045` (tool loop + LangChain deferral), and
`docs/06`/`docs/09`.

**Verdict up front.** The session is architecturally consistent with the plan of record — its own
key decision ("build the video experience as Dataflow Builder orchestration over Node Builder, not
inside Node Builder") restates `DEC-009`/`DEC-034`. It introduces **five genuinely new requirement
clusters** (DR-1…DR-5 below), all owned by the *future Dataflow Builder implementation memo*, and
**one new product track** (the research node, DR-6) that is a package + tool question, not an
agents-runtime question. Nothing in the session invalidates dev/48; two sentences in the session
conflict with settled boundaries and are resolved below in favor of the plan of record.

## 1. Classification — each proposed behavior vs. current documentation

### Matching (already covered; the session re-derives the plan of record — no doc changes)

| Session behavior | Where it already lives |
| --- | --- |
| Dataflow Builder orchestrates; Node Builder is the per-node specialist; delegation to Task Planner, Coherence Validator, Connection Builder, Node Content Builder | `dev/15` §3.2 delegation graph; `DEC-009`, `DEC-034` |
| Every graph mutation is a reviewed proposal; no unreviewed canvas replacement; plan/evaluate may proceed unconfirmed | `DEC-006`/`REQ-REVIEW-001`; `dev/15` orchestration invariants; `dev/03:366` |
| No arbitrary node types outside installed project packages; no invented types | `dev/48` binding node-creation policy (reuse-first, registry-validated) |
| No automatic package installation; missing packages → reviewed install through the existing flow | `dev/16` (`REQ-PACKAGE-001`, `InstallPermissionsDialog` path) |
| Missing specialist → reviewed `Install in project`, never auto-install/attach/run | `REQ-ORCH-001`; `dev/15` §4; `dev/48` `project.install` proposal |
| Child executions linked, partial failure preserves successful children, targeted retry | `dev/15` §4; `dev/03:670`; `parentExecutionId` (dev/48 §3.4) |
| Bounded concurrent child work under an aggregate reservation | `dev/15` Dataflow Builder manifest (`maxParallelChildren`), `dev/03:296` orchestration-mutation profile |
| Atomic saved-spec + live-canvas apply | `dev/48` §3.3 canvas bridge (the session cites it) |
| Keep React Flow + the existing package/node registry | `dev/48` §3.2 (registry-grounded validation) |

### Partially covered (invariant exists; the session adds implementable detail → assigned to DR-#)

| Session behavior | Covered part | New part |
| --- | --- | --- |
| Reviewable **whole-graph** proposals | `dev/41` explicitly deferred graph-shape apply semantics "until a P5 consumer defines them"; `dev/48` defined the single-node case (`node.create`) | Multi-node/edge graph proposal + one-review apply → **DR-1** |
| Solve = topological, concurrent, validated, staleness-propagating | Bounded fan-out, linking, partial failure, retry (above) | Topological scheduling, per-node digest guards, downstream-stale marking → **DR-4** |
| Placeholder nodes with intent + port contracts, "code pending" | `dev/15` `node.build` contract (intent + reviewable preview); package `TemplateManifest` port model | Typed `DataflowPlan`/`PlannedNode` domain representation + plan↔canvas mapper → **DR-1** |
| Replace the generic LLM panel for this workflow | `dev/03:519` already migrates `LLMChat`/`MainCanvas` prompt paths to installed agents | The phase-aware builder panel spec → **DR-5** |
| Node Builder configures a template instance (question, contract, settings) per plan step | `dev/48` tier-1 `node.create` (type + content + goal) | Instance *configuration* payload (per-node config beyond content) → small `node.create` params extension, owned by the Dataflow Builder memo when the first configured-instance consumer lands (**DR-4**) |

### Genuinely new (no current coverage → the delta requirements, §2)

Persisted orchestration phase state (DR-2); planning templates (DR-3); semantic replan diff
preserving user edits (DR-2/DR-1); the research-node track (DR-6).

### Conflicting (resolved here, in favor of the plan of record)

1. **"[Node Builder] connects it to relevant upstream nodes"** (session part 2) — conflicts with
   `dev/15` (connection.propose belongs to Connection Builder, delegated by Dataflow Builder) and
   `dev/48` out-of-scope (Node Builder creates unconnected nodes). **Resolution**: Node Builder
   returns a node + declared port contract, never edges; Dataflow Builder delegates connection
   proposals to Connection Builder. The session's own diagram (D → Connection Builder) already
   shows this; the sentence was a slip.
2. **Session's `DataflowPlan.nodes[].content` + "write successful content into the node" during
   Solve** could be read as content bypassing review. **Resolution**: solve results are applied
   through the same review boundary — the graph-level proposal (plan apply) and per-node content
   application (`node.content.write` / batched under DR-1's apply semantics) remain the only
   mutation paths (`DEC-006` structural). The recording's UX (one Solve action, progressive fill)
   is achieved by ONE reviewed solve action authorizing the batch, not by unreviewed writes —
   exact contract to be fixed in the Dataflow Builder memo (DR-4).

### Duplicated (do not re-specify anywhere)

The session's §§1-2 problem statement, review invariants, out-of-scope list, and the
"responsibility split" quote restate `dev/15`/`dev/48`/`dev/16` content. The future Dataflow
Builder memo must cite those documents rather than restating them; only DR-1…DR-5 are new
requirements.

## 2. The delta — "crucial orchestration work" still to be implemented

All assigned to the **Dataflow Builder implementation memo** (future; last in the program order:
dev/48 → T4 provider profiles → Dataset Finder → Dataflow Builder), except DR-6.

- **DR-1 — Graph-level proposals + typed plan domain.** `DataflowPlan`/`PlannedNode`/`PlannedEdge`
  contracts; a single plan↔React-Flow mapper; a whole-graph reviewed proposal whose apply updates
  saved spec + live canvas atomically (extends the dev/48 §3.3 bridge from one node to a graph;
  this is the consumer `dev/41` deferred graph-shape semantics to).
- **DR-2 — Persisted orchestration session.** The explicit phase machine
  (`idle→planning→plan_review⇄revising→solving→ready→running→completed|failed`), stored as a
  `DataflowBuilderSession` beside (never inside) node data, with revision digests, reload
  recovery, cancellation that keeps completed children, and stale-response guards. Semantic
  replan diff (preserve IDs/positions/user content; removals as constraints; user-added nodes as
  required elements) is a **deterministic domain service**, not model work.
- **DR-3 — Planning templates.** The browsable template set (Load and Clean, …, From Scratch) as
  plan-seeding inputs; product surface + template storage owner to be decided in that memo.
- **DR-4 — Solve scheduler.** Generalize dev/48's depth-1 single-child delegation to a
  topological, bounded-concurrency fan-out with per-node digest guards, downstream staleness,
  per-node retry, and the one-reviewed-solve batch-apply contract (conflict 2 above). Also the
  configured-instance extension of `node.create` params.
- **DR-5 — Phase-aware builder panel.** Goal/history, template selector, phase indicator, change
  summary, per-node progress, retry/cancel, Run gating — replacing the legacy generic panel for
  this workflow (continues the `dev/03:519` migration; accessibility per the session's list).
- **DR-6 — Agentic research node (separate track, not Dataflow Builder).** Research/Analysis/
  Synthesis as **reusable custom node templates in a node package** (the packages product owns
  them — consistent with `dev/16`'s "agents never author packages" for the curated version, and
  with dev/48 §3.2b's factory seam if ever agent-drafted); a `web.search` **tool contract** with
  egress policy (`dev/03` "provider-and-authorized-tools-only") and provenance/citation bounds;
  and the open product decision the session names: per-node **agent attachment** (fits the
  existing hookable model, zero new runtime) vs. **agent-embedded executable node** (new engine
  concept — packages cannot currently declare agent runtimes). Near-term direction: prototype via
  attachment; the embedded-agent node requires its own memo before any commitment. Node Builder's
  involvement is plain tier-1 reuse once the package exists — no dev/48 change needed.

**Known v1 narrowing to widen at Dataflow Builder** (recorded for consistency): `dev/48` resolves
delegates within `delegatesTo ∩ project-installed` only; `dev/03:366` specifies capability-first
discovery with `delegatesTo` as *preference*. Acceptable for depth-1 with one delegate; the
Dataflow Builder memo must implement full capability resolution (contract/target/trust/source
policy, deterministic tie-breaks per `08` §6).

## 3. LangChain placement (explicit, per DEC-007/DEC-045/DEC-046)

**Use LangChain — behind the existing runtime port (`dev/03` boundary rules: imports only inside
`backend/app/agents/` runtime adapters):**
- **DR-4, the Solve fan-out**: coordinating many concurrent child agent runs in topological waves
  with bounded parallelism, per-child retry, cancellation propagation, and cross-wave
  checkpointing is graph-executor territory — this is the DEC-046 revisit point, decided in the
  Dataflow Builder memo with dev/48's delegation usage data in hand.
- **Open-ended provider tool loops**, if and when one outgrows the bounded 2-round loop — the
  research node's iterative search→read→refine cycle (DR-6) is the first realistic candidate.
- Optionally, **provider adapter normalization** if the T4 provider matrix grows beyond the
  current OpenAI-compatible port.

**Do NOT use LangChain for (existing services / deterministic logic are the right tool):**
- The phase state machine (DR-2) — persisted application state advanced by explicit user actions.
- Semantic graph diffing (DR-2) — a pure function.
- Review/apply gates, proposals, and the apply endpoints — authenticated application services
  (`DEC-006` is structural; an executor must never hold mutation authority).
- Capability/delegation *resolution* — lockfile + policy lookup (deterministic).
- Ledger, quota, budget, policy admission (`DEC-044`) — domain code.
- dev/48's depth-1 single-child delegation — stays direct provider-port code (`DEC-046`).

This keeps `DEC-007` ("LangChain as initial runtime behind a stable boundary") honest in its
narrowed form: the *boundary* is already built (provider port, delegation seam); the adapter is
adopted exactly where an executor adds value, never as a rewrite of working domain services.

## 4. Documentation updates applied with this memo

- `dev/48`: one-line consolidation note added (Node Builder's role under Dataflow Builder
  orchestration = per-step instantiation/configuration; edges stay with Connection Builder;
  research-node instantiation is ordinary tier-1 reuse once its package exists). No requirement
  changes — dev/48 stands as written.
- `dataflow-researcher.md`: header note marking it as brainstorm material consolidated here — it
  is not a plan of record; DR-1…DR-6 are the surviving requirements.
- No change to `dev/15`/`dev/16`/`dev/03`: the session confirmed them; the DR items land in the
  future Dataflow Builder memo (DR-1…DR-5) and a future research-node memo (DR-6), each of which
  must cite this memo instead of restating the session.
