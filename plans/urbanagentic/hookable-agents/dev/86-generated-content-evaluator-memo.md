# Dev/86 — `agent.generated-content-evaluator`: the DEC-055 authored built-in

Status: implemented (2026-08-18, commits `52863552` roster+prompt / `549b9d34`
delegation wiring; build-log entry BL-P5-20260818-31; implemented on the owner's
DEC-055 approval — dev/85 §4 is the authoritative contract, and its approval is the
"supplied and reviewed" event OQ-007 demanded). No deviations: the entry landed as
§3 specifies, and the byte-parity regression needed no amendment (report-only,
delegates-free — the migrated-manifest shape, as predicted).

---

## 1. Problem Statement

DEC-055 authorized the fourteenth migration-map identity as a net-new authored built-in:
the semantic-validation layer ("does this generated content do what the goal and
assumptions say") that dev/57 parked and dev/85 §2 showed is the one uncovered slice of
the Validation brief. Today the roster carries its absence (`builtin.py` docstring:
"intentionally absent … blocked by OQ-007"), the routes list 18 agents, and no prompt
file exists. Expected: the 19th built-in ships with the dev/85 §4 contract — advisory
report-only, read-only tools, never feeding DEC-054's empirical auto-approve — and the
build composites can delegate to it as an optional post-generation check.

## 2. Scope

In: `builtin.py` (roster entry; docstring note flips to DEC-055; `delegates_to`
additions on node-builder + dataflow-builder), net-new
`llm-prompts/evaluate_generated_content_prompt.txt`, tests (`test_builtin.py`,
`test_routes.py` count, `test_delegation.py`), docs (`docs/AGENTS.md`, `dev/03`
decision/OQ tables per dev/85 §6).
Out: any new tool or proposal lane (read-only existing tools: `node.read`,
`node.runtime.read`, `dataflow.read`); any DEC-054/DEC-028 change (the firewalls are the
point); Optimization (DEC-056: descoped, no code); OQ-008.

## 3. Approach

- **Roster entry**: id `agent.generated-content-evaluator`, name "Generated Content
  Evaluator", category `evaluate`, capabilities `("content.quality.evaluate",)`, roles
  `("validation",)`, `targets=("node","canvas")`, `reads=("nodeContext",
  "targetContext")`, tools `("node.read","node.runtime.read","dataflow.read")`,
  `review_policy="report-only"`, no `delegates_to` of its own. Prompt file keeps the
  long-documented name `evaluate_generated_content_prompt.txt`.
- **Prompt** (net-new, to the dev/85 §4 contract): two modes (attached node vs canvas);
  findings as `[blocker|warn|note] claim — evidence` lines with evidence quoting the
  content/goal/journal; one verdict (`fits` / `fits-with-warnings` / `does-not-fit`)
  strictly derived from the findings; ungroundable claims reported as uncertainty;
  advisory-only (never approve, never propose mutations, never claim to have run
  anything — `node.runtime.read` is the only execution evidence); empirical validation
  named as primary.
- **Delegation**: `agent.node-builder` and `agent.dataflow-builder` append the evaluator
  to `delegates_to` (optional post-generation check; resolution stays current-project-
  only; missing template → the standard missing-specialist proposal). Connection Builder
  is NOT touched (dev/85 scoped the composition to the two generators).
- The byte-parity regression needs no amendment: the evaluator is delegates-free and
  report-only, exactly the migrated-manifest shape — only the extras/count assertions
  and the two composites' delegate lists change.

## 4–8. Data/UI/edge cases/tests/acceptance (delta only)

No new state, endpoints, or UI: the agent rides every existing built-in surface
(catalog card, install, attach node/canvas, chat, materialization). Edge cases are the
contract's honesty rules (never-ran node → the journal says `never-executed` and the
report must say so; no goal on the node → evaluate against what exists and say the goal
is missing). Tests: roster 19 + extras set + `TestGeneratedContentEvaluator` (manifest
surface: capability/targets/tools/report-only/no-delegates; instruction resolves and
carries the verdict vocabulary + advisory rule); routes catalog count 19; delegation —
both parents resolve `content.quality.evaluate` when installed, missing template =
not-installed. Acceptance: `pytest test_agents/ test_packages/` green; the evaluator
imports/installs/attaches like any built-in; no frontend change required (jest baseline
untouched).

## 9. Commit order

1. **Commit 1 — roster + prompt**: entry, docstring flip, prompt file, roster/manifest/
   route-count tests.
2. **Commit 2 — delegation wiring**: the two `delegates_to` additions + delegation and
   composite-manifest test updates.
3. **Docs commit**: this memo + dev/85 flip + BL-P5 entry + `docs/AGENTS.md` (19) +
   `dev/03` tables (DEC-055/056 rows; OQ-007/011 closed; the `evaluation-disabled`
   profile row retired).

## 10. Checklist

- [ ] Report-only, delegates-free entry — the migrated-manifest shape; byte-parity loop
      passes it unamended.
- [ ] Prompt encodes the full §4 contract incl. the never-approve and evidence rules.
- [ ] No DEC-054/DEC-028 surface touched.
- [ ] Suites green before each commit.
