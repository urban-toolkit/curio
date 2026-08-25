# Dev/103 — Specification supersession notes: dev/03 and dev/05 internal consistency

Date: 2026-08-25
Status: **implemented 2026-08-25** — documentation-only; completes the review items dev/102 §2 listed as out of scope
Branch baseline: `feat/agentscatalog` with `BL-P5-20260824-43` (dev/101) as the newest verified ledger entry

## 1. Problem Statement

Dev/100 reconciled the entry-point statuses and dev/102 advanced them through dev/101, but the story
documents dev/03 and dev/05 still contradicted the active decision table on five fronts:

1. **LangChain** — `DEC-048` retired `DEC-007` and made direct provider-port code the orchestration of
   record, yet dev/03 (§2 scope, the `DEC-007` row, the Phase-2 gate, the layer diagram, all of §7, the
   Phase-2 bullet, commit 9) and dev/05 (ADR-AG-005, the model-bridge migration paragraph, the module
   tree, §10's adapter section, migration step 5, the test matrix, verification prose, step-list and
   commit 12) still mandated a `LangChainRuntimeAdapter`/`LangChainAgentRuntime` with no supersession
   markers — unlike the sharing sections, which dev/100 retro-annotated.
2. **`evaluation-disabled`** — retired by `DEC-055` (struck in dev/03), but dev/05 still mapped it to "the
   blocked Generated Content Evaluator" and required a fail-closed test fixture for it.
3. **Thirteen vs twelve callers** — `REQ-PROMPT-002` demanded parity cutover of "the thirteen current
   prompt callers" with no `DEC-041` carve-out, disagreeing with every remainder statement (twelve
   non-grandfathered + the permanently retained Node Explanation caller).
4. **Closed OQs in open tense** — OQ-008 obligations phrased as future requirements (dev/03 telemetry
   bullet, dev/05 ADR tradeoff and test-fixture prose) and OQ-007 phrased as a live gap (dev/03 out-of-scope
   "unresolved evaluator", `RISK-EVAL-001`'s "OQ-007 unavailable state", dev/05's "OQ-007 package"),
   though `DEC-055`/`DEC-057`/`DEC-058` closed both.
5. **Un-annotated decision rows** — `DEC-021` listed as plainly approved while `DEC-050` records it open;
   `REQ-RUNTIME-002` and ADR-AG-013 specified leases as current requirements without the gate;
   `DEC-052`'s row still advertised the `installedTemplates` producer `DEC-062` retired; `DEC-038` carried
   dev/05's "historical" note only in dev/05; dev/03's §2 scope listed all six settings screens unqualified.

A reader could implement a retired adapter, test a retired profile family, target thirteen callers, re-litigate
closed OQs, or build leases the deployment gate still owns.

## 2. Scope

Included — dev/03 and dev/05 only, using dev/100's two techniques (adjacent supersession/current-status
notes where the original text is useful history; direct correction where a statement is simply false):

- dev/03: §2 scope bullets (LangChain, six screens), the `DEC-007`/`DEC-021`/`DEC-038`/`DEC-052` decision
  rows, the Phase-2 LangChain gate, the layer diagram, a §7 supersession note, the Phase-2 bullet, commit 9,
  `REQ-PROMPT-002`, `REQ-RUNTIME-002`, the telemetry/OQ-008 bullet, the out-of-scope evaluator line, and
  `RISK-EVAL-001`.
- dev/05: ADR-AG-005 and ADR-AG-013 current-status lines, the model-bridge migration paragraph, the
  module-tree comments, §10's adapter supersession note, migration step 5, the `LangChainAgentRuntime`
  test row, the profile-fixture row, the registry mapping sentence, the verification prose (LangChain suite,
  OQ-008 ownership, OQ-007 dependence), the step-6 adapter mention, and commit 12.
- `dev/00`: one index row for this memo.

Out of scope: implementation code and tests; append-only BL entries; docs/09–11 (already consistent);
the remaining structural review findings that are additions rather than corrections (a consolidated 21-agent
roster table; reflecting dev/101's backend-owned `dataflow.packages` rule in the story's persistence
sections; RISK-SECRET-001's plaintext-column posture in the dev/03 risk table) — each is real follow-up
work but new content, not a supersession note; committing or staging anything (the dev/100 set stays
staged by its owning session).

## 3. Recommended Implementation Approach

Never rewrite the July baseline rationale: annotate it. Historical designs (ADR-AG-005/013, §7, §10's
adapter contract, the module tree, commit plans) keep their text and gain an italic or block-quoted
current-status note naming the superseding decision and the recorded re-open condition. Flatly false
current-tense claims (the thirteen-caller requirement, "unresolved evaluator", "OQ-008 must define …
before production release", the blocked-evaluator mapping, the five-fixture requirement) are corrected
directly, each naming its closing decision. All edits are exact-string replacements with asserted occurrence
counts.

## 4. Data and State Handling

No application data or runtime state changes. Authority: the active dev/03 decision table itself
(`DEC-041`/`048`/`050`/`055`/`057`/`058`/`062`), dev/85–88/93 memo records, and `docs/RETENTION.md`.

## 5. UI and UX Requirements

None (documentation only). Every LangChain-normative section must now answer "is this current?" inline;
no section may present a retired dependency, profile family, caller count, or open question as live.

## 6. Edge Cases

- dev/03's `DEC-045`/`DEC-046`/`DEC-053` rows already record the LangChain deferral/declination in their
  own words — left untouched.
- dev/05 §19's step list and DoD checkboxes remain unchecked by design (original blueprint); only falsifiable
  claims inside them were annotated.
- `OQ-009`/`OQ-010` remain genuinely open — no tense change applied to them.
- The `DEC-021` row keeps its full original decision text; the gate note is additive, matching `DEC-050`'s
  recorded "user slice" boundary and the 15-minute stale guard actually shipped.

## 7. Testing Strategy

Documentation-only: asserted-anchor replacements (every anchor matched exactly once), a straggler sweep
(remaining `LangChain`/`OQ-007`/`OQ-008`/`evaluation-disabled`/`thirteen` mentions must each carry a
closure/supersession marker or genuinely refer to open work), and `git diff --check`. No application suites.

## 8. Acceptance Criteria

1. Every LangChain-mandating passage in dev/03/dev/05 carries a `DEC-048` supersession/current-status
   marker naming the `DEC-021` re-open condition; none reads as current work.
2. dev/05 contains no live `evaluation-disabled` mapping or fixture requirement; both sites name `DEC-055`.
3. `REQ-PROMPT-002` counts twelve non-grandfathered callers and names the `DEC-041` exemption.
4. No dev/03/dev/05 sentence phrases OQ-007 or OQ-008 as open; each former obligation names
   `DEC-055` or `DEC-057`/`DEC-058`.
5. The `DEC-021`, `DEC-038`, and `DEC-052` rows carry their gate/historical/partial-supersession notes;
   `REQ-RUNTIME-002`, ADR-AG-013, and the §2 settings bullet state what shipped versus what is gated.
6. No implementation file changes; nothing newly staged or committed.

## 9. Recommended Commit Breakdown

One documentation commit (this memo + dev/03 + dev/05 + the dev/00 row), pathspec-scoped, made by the
owner adjacent to the dev/100/dev/102 documentation commits so the three reconciliation layers land
together in history.

## 10. Engineering Quality Checklist

- [x] No baseline rationale was erased; historical sections were annotated, not rewritten.
- [x] Every correction names its authorizing decision (`DEC-041/048/050/055/057/058/062`).
- [x] Genuinely open work (`OQ-009`/`OQ-010`, T4, DEC-058 surfaces, twelve callers) was not touched.
- [x] All 31 anchors matched exactly once; the straggler sweep is clean.
- [x] `git diff --check` passes; changes are planning/documentation files only; nothing staged or committed.

Verification evidence:

- straggler sweep: every remaining `LangChain` mention in dev/03/dev/05 sits inside a supersession/
  current-status marker or a decision row that already records the deferral; every remaining `OQ-007`/
  `OQ-008` mention states closure or is the closure record itself; both `evaluation-disabled` sites name
  `DEC-055`; no "thirteen callers" requirement remains;
- the sweep-driven second pass extended the same markers to the `DEC-028`/`DEC-039` rows, the
  `LangChainModelBridge` provider line, the Phase-2 gate and §19 test-plan mentions, the two Mermaid
  labels, dev/05's command/event ADR decision line, and the `REQ-RETENTION-001`/DoD OQ-008 items;
  negative boundary guards ("never import LangChain") were deliberately left — they remain true and
  enforced by the import-boundary tests;
- `git diff --check` reports no whitespace errors;
- application test suites were not run (documentation only).
