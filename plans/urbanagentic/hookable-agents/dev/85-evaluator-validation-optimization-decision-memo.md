# Dev/85 — Decision memo: resolving OQ-007 (generated-content evaluator) and OQ-011 (Validation & Optimization agents)

Status: **approved by the owner 2026-08-18** — `DEC-055` and `DEC-056` are minted;
OQ-007 and OQ-011 are closed. DEC-055's implementation is memo `dev/86` (roster entry +
net-new prompt + delegation wiring), landed the same day; DEC-056 requires no code.

These are the last two open questions gating the built-in roster. Everything else the
roster planned has shipped: 13 migrations, the three composites, the Node Researcher
(dev/67-4), and Package Recommendation (dev/84). This memo follows the dev/18
decision-memo precedent: it records decisions and their rationale; implementation, if
any, follows as its own memo under the standard.

---

## 1. What each question actually asks

**OQ-007** (`dev/03:159`): *"What is the approved source text and output contract for
`evaluate_generated_content_prompt`?"* — with the guardrail *"Do not infer or substitute
content; do not register, publish, install, or run this package until supplied and
reviewed."* The fourteenth migration target, `agent.generated-content-evaluator`
(capability `content.quality.evaluate`), was documented conceptually but had **no prompt
file and no call site in the repository** (`dev/06:7`). The block was never "this agent
is a bad idea" — it was "there is no legacy source to migrate, and fabricating one and
calling it a migration would be dishonest." Roster and docs have carried the absence
faithfully ever since (`builtin.py:13-14`, `docs/AGENTS.md`).

**OQ-011** (`dev/03:163`): *"Should the two still-unspecified product agents —
Validation and Optimization — be specified with their own manifests/capabilities or
descoped?"* Their entire specification is two concept-table rows (`docs/01:47-48`):
Validation = *"Check code, coherence, data types, outputs, and assumptions"* (node or
canvas); Optimization = *"Improve performance and structure of the graph"* (canvas).
Standing guardrail: treat both as not-installed; the Dataflow Builder never assumes them
present. (`Package Recommendation`, originally flagged alongside them, resolved via
DEC-035/dev/16 and shipped in dev/84.)

## 2. What changed since these were minted

Three facts the original questions did not have:

1. **Net-new built-in prompts are an established, gated practice.** dev/48/50/52
   (composites), dev/67-4 (researcher), and dev/84 (package recommendation) all shipped
   deliberately-authored instructions through the same manifest validation, digest, and
   materialization machinery. "Authored under an explicit product decision" is no longer
   fabrication — it is how five of the eighteen built-ins exist.
2. **Validation's brief is now mostly covered — empirically.** Code checking:
   `agent.syntax-analysis-agent` + `agent.debug-agent` (with `node.runtime.read`).
   Coherence: `agent.plan-coherence-validator`. Outputs and data types: the dev/67-7
   **execute-through validation** (real sandbox runs, self-correcting rounds) feeding
   DEC-054's simulation auto-approve, plus the DEC-052 runtime journal. External facts:
   `agent.node-researcher` (`research.verify`). What remains uncovered is exactly one
   slice: **semantic judgment** — "does this generated content actually do what the goal
   and assumptions say," beyond compiling and running.
3. **The owner already asked for that slice.** dev/57 records it verbatim: *"The user's
   LLM-verification-agent suggestion is recorded against the Validation-agent track
   (OQ-011) as a later semantic layer — deterministic extraction is the primary
   mechanism."* That is demand signal from the product owner, parked pending precisely
   this decision.

The uncovered Validation slice and the evaluator's planned capability
(`content.quality.evaluate`) are **the same thing**. Resolving the two questions
separately would either ship two overlapping agents or descope a capability the owner
asked for.

## 3. Options considered

- **A — descope both.** Honest but wasteful: it discards the dev/57 request, and the
  concept screens' Validation card would map to nothing that judges semantics.
- **B — author the evaluator AND specify a separate Validation agent.** Two agents for
  one uncovered slice; the Validation manifest would either duplicate
  `content.quality.evaluate` or be an empty umbrella over capabilities other agents
  already declare. Rejected as duplication.
- **C — unify (recommended).** Author `agent.generated-content-evaluator` as the
  semantic-validation layer (closing OQ-007 by supplying the approved contract, below),
  declare the Validation concept card **covered by the existing family plus the
  evaluator** (no separate `agent.validation`), and descope Optimization to
  demand-driven with named re-open conditions.

## 4. DEC-055 (proposed) — OQ-007 resolved: the evaluator is authored, not migrated

`agent.generated-content-evaluator` joins the roster as a **net-new authored built-in**
under this decision (the same posture as the composites/researcher), keeping its
documented id and capability. The approved **output contract** — the substance OQ-007
demanded:

- **Inputs**: the target node's content + goal/intent (node target) or the graph
  projection (canvas target); the runtime journal's last outcome when present. Reads
  `nodeContext`/`targetContext`; tools `node.read`, `node.runtime.read`,
  `dataflow.read` — read-only, all optional.
- **Output**: a structured findings report, never a mutation and never a bare verdict:
  per finding `{severity: blocker|warn|note, claim, evidence, suggestion?}` plus one
  overall `verdict: fits|fits-with-warnings|does-not-fit` **strictly derived from the
  findings** (no finding → no verdict language stronger than "nothing found"). Evidence
  must quote the content/goal/journal it judges; a claim it cannot ground is reported as
  uncertainty, not asserted (the dev/67-4 honesty posture).
- **Authority: none.** `report-only` review policy; it proposes nothing, applies
  nothing, and its verdict is **advisory to the user and to delegating parents** —
  DEC-054's simulation auto-approve stays exclusively empirical (execute-through PASS);
  the evaluator can never approve, only inform. Deterministic/empirical mechanisms stay
  primary (dev/57's rule; the fix-primary-paths posture).
- **Self-certification firewall unchanged**: DEC-028's platform prompt-quality gates
  neither depend on nor substitute this agent (RISK-EVAL-001 controls stand); the
  `evaluation-disabled` profile row (`dev/03:306`) retires with this decision.
- **Prompt source text**: authored net-new as
  `llm-prompts/evaluate_generated_content_prompt.txt` (the long-documented filename),
  written to this contract, subject to the same validation gates as every built-in.
  This memo's approval IS the "supplied and reviewed" event the OQ demanded.
- **Composition**: `agent.node-builder` and `agent.dataflow-builder` may add it to
  `delegatesTo` as an optional post-generation check; delegation stays user-visible and
  current-project-only as everywhere else.

Roster count becomes 19; the dev/06 migration map's fourteenth row flips from "blocked"
to "authored under DEC-055" (it is a documentation row, not a migration).

## 5. DEC-056 (proposed) — OQ-011 resolved: Validation is covered; Optimization is descoped demand-driven

- **Validation: no separate agent.** The concept card's brief decomposes onto the
  shipped family — syntax (`code.syntax.analyze`), coherence
  (`workflow.coherence.validate`), outputs/data-types (dev/67-7 execute-through +
  runtime journal), external facts (`research.verify`), semantics (DEC-055's
  `content.quality.evaluate`). The concept screens' "Validation" card is a **category
  view over this family**, not a monolith; docs that name it point here. Nothing new is
  specified, so nothing new can drift.
- **Optimization: descoped, demand-driven.** No user request, no capability contract
  anyone consumes, and its prerequisite evidence doesn't exist yet — the runtime
  journal records outcomes but **not per-node durations** (noted as a dev/67-7
  follow-up), so a performance-improvement agent today could only guess. Named re-open
  conditions: (1) real usage asking for graph restructuring/performance advice, AND
  (2) per-node duration/size evidence in the journal for it to ground claims in. Until
  then the standing guardrail continues: not-installed, never assumed, and the concept
  screens' card is annotated "planned" or removed at the next docs pass.
- The OQ-011 table row closes; the dev/03 open-questions table gains the two DEC
  references.

## 6. Consequences if approved

- The built-in roster has **no remaining blocked or unspecified entries**: 19 shipped
  (after DEC-055's implementation) + one formally descoped concept (Optimization) with
  re-open conditions on record. OQ-008 (retention policy) remains the only open
  question, untouched by this memo.
- Implementation of DEC-055 is one dev/84-shaped unit (roster entry + net-new prompt +
  optional `delegatesTo` additions + tests) and gets its own implementation memo per
  the standard; nothing in this memo changes code.
- Docs to touch at implementation time: `docs/AGENTS.md` (roster + the evaluator's
  advisory posture), `dev/03` decision/OQ tables (DEC-055/056 rows, OQ-007/011 closed),
  `builtin.py`'s module docstring (the "intentionally absent" note becomes a DEC-055
  reference).

## 7. The asks

1. Approve **DEC-055** (author the evaluator to the §4 contract) — or reject toward
   option A (descope it too; the dev/57 parked request would close as won't-do).
2. Approve **DEC-056** (Validation covered / Optimization descoped with the §5 re-open
   conditions).
