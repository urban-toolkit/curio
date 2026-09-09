# Dev/100 — Hookable-agents planning-document reconciliation through dev/97

Date: 2026-08-24
Status: **implemented 2026-08-24** — documentation-only reconciliation complete
Branch baseline: `feat/agentscatalog` at `6807194f` (dev/97 complete)

## 1. Problem Statement

The hookable-agents implementation and its append-only build evidence have advanced through dev/97,
but several canonical entry points still describe the pre-v1 or early-v2 state. The top-level README
says application implementation has not begun; the development index stops at dev/38 and calls the
already-implemented dev/37 tranche proposed; the Stage-3 phase index still calls all composites and
Package Recommendation unimplemented; the Stage-2 requirement matrix repeats those obsolete statuses;
and canonical architecture documents still say the Node Explanation tab is absent and the Generated
Content Evaluator is blocked.

Those contradictions matter because the package instructs developers to use these files as the reading
order and source of truth. A reader can select work that already shipped, revive a superseded decision,
or miss a real remainder. Expected behavior: the entry points accurately summarize implementation
through dev/97, historical statements are either corrected or explicitly labeled historical, and the
remaining-work list distinguishes concrete incomplete requirements from demand-gated or deployment-
gated work.

## 2. Scope

Included:

- `README.md`, `dev/00-development-phase-index.md`, the Stage-2 traceability ledger, and the Stage-3
  build-log index;
- canonical architecture/product documents whose current prose contradicts DEC-041, DEC-055/056,
  DEC-064/065/066, or the shipped 21-agent roster;
- stale status language in the development plan and implementation blueprint where it is presented as
  current rather than as dated evidence;
- a current remaining-work summary covering legacy prompt-caller cutover, the package-seed reader lock,
  provider/governance/deployment gates, and explicitly demand-gated follow-ups;
- targeted text-consistency checks and a documentation-only diff review.

Out of scope:

- implementation code, tests, generated concept images/workbooks, and branch integration with
  `origin/main`;
- rewriting append-only BL entries or erasing the historical state they recorded at their dates;
- closing `OQ-009`/`OQ-010`, implementing provider profiles/governance, migrating raw prompt callers,
  or implementing any demand-gated follow-up;
- modifying or deleting the user's unrelated dirty-worktree files.

## 3. Recommended Implementation Approach

Use one status vocabulary across the entry points: implemented, partially implemented, historical,
demand-gated, deployment-gated, or remaining. Treat the latest verified memo/BL entry as implementation
evidence and the active dev/03 decision table as decision authority. Add compact forward links rather
than copying full design details into every index. Keep append-only logs unchanged except for their
mutable phase/index summaries; later verified entries remain the evidence trail.

Where an older specification is useful history, add an adjacent update or current-status note instead
of silently rewriting its original rationale. Where a canonical product statement is simply false
(for example, “Node UI has no Explanation tab”), correct it directly because DEC-041 requires active
documents not to imply removal.

## 4. Data and State Handling

No application data or runtime state changes. Documentation derives current status from:

1. dev/39–97 memo status headers;
2. Stage-3 verified build entries through `BL-P5-20260824-40`;
3. active decisions through DEC-066 in dev/03;
4. representative implementation/tests for the 21-agent roster, review/apply paths, retention,
   backend sandbox, activation lifecycle, rich review card, and dependency overlays.

The reconciliation must not infer completion from a proposal alone. Remaining and gated items stay
open, and historical verification counts are labeled as recorded evidence rather than rerun results.

## 5. UI and UX Requirements

This change has no application UI. The documentation UX must provide:

- a truthful first-screen status summary;
- a scannable implementation sequence through dev/97;
- unambiguous labels for shipped, remaining, and demand-gated work;
- direct links to the authoritative memo or build entry;
- no contradictory Node Explanation, evaluator, composite, Package Recommendation, or retention copy;
- accessible Markdown structure with descriptive link labels and no meaning conveyed by formatting
  alone.

## 6. Edge Cases

- Historical BL entries may correctly say an item was deferred at that time; do not rewrite them.
- A memo may be a decision/consolidation record rather than implementation (`dev/49`, `dev/85`,
  `dev/87`); label it accordingly.
- `DEC-041` retains the Explanation tab/direct caller even while the other raw prompt callers remain a
  migration remainder.
- The Generated Content Evaluator is shipped as authored net-new, not retroactively characterized as a
  migrated source-backed prompt.
- The 21-agent roster does not mean prompt governance, provider profiles, multi-instance execution, or
  remote-data classification are complete.
- The latest dev/89→97 follow-up list does not supersede older still-open requirements such as direct
  caller cutover or the seed-reader lock gap.
- Generated visuals remain supporting evidence and may be stale after later UI work; do not claim they
  represent dev/97 without regeneration.

## 7. Testing Strategy

- Search canonical/current documents for obsolete statements: “implementation has not yet been
  performed”, dev/37 “PROPOSED”, composites/Package Recommendation “NOT IMPLEMENTED”, evaluator
  “blocked”, OQ-008 “open”, Explanation tab absent, and Follow-up D deferred.
- Confirm the development index links every numbered memo family through dev/100, including the dev/67
  sub-index.
- Confirm Stage-2/Stage-3 summaries agree with the active dev/03 decisions and the latest BL-P5 entry.
- Confirm remaining-work text still names raw caller cutover, seed-reader locking, T4/governance,
  OQ-009/OQ-010, and the demand-gated dev/97 tail.
- Run `git diff --check` and inspect the final documentation-only diff; do not run application suites for
  prose-only changes.

## 8. Acceptance Criteria

1. The package README states implementation is current through dev/97 and points to the current index.
2. `dev/00` no longer stops at dev/38 or reports shipped work as proposed/blocked.
3. Stage-2 and Stage-3 summaries mark all three composites, Package Recommendation, the evaluator,
   retention implementation, Package Builder/Researcher, sandboxing, activation hardening, rich review,
   and overlays according to their verified evidence.
4. Active documents retain the Node Explanation tab and describe the evaluator as shipped under
   DEC-055.
5. OQ-007/OQ-008/OQ-011 are closed; OQ-009/OQ-010 remain deployment-gated.
6. The direct prompt-caller cutover and seed-reader lock are not lost from the remaining-work summary.
7. Demand-gated recolor, reference preview runner, screenshot storage, and resident services are not
   presented as unconditional next work.
8. No implementation file, generated artifact, or unrelated dirty file changes as part of dev/100.

## 9. Recommended Commit Breakdown

- Commit 1: add dev/100 and reconcile `README.md` plus `dev/00`.
- Commit 2: reconcile Stage-2/Stage-3 summaries and dev/03/blueprint current-status language.
- Commit 3: correct canonical architecture/product contradictions and add consistency verification
  evidence; flip dev/100 to implemented.

## 10. Engineering Quality Checklist

- [x] No historical build evidence was erased or rewritten.
- [x] Current status is derived from verified memos/BL entries, not assumption.
- [x] Remaining, demand-gated, and deployment-gated work are separated.
- [x] DEC-041, DEC-055/056, and DEC-064/065/066 are represented consistently.
- [x] The 21-agent roster and the still-open governance/provider work are both stated truthfully.
- [x] Direct raw prompt-caller migration remains visible as incomplete except for the DEC-041 exemption.
- [x] All added links resolve and Markdown remains readable.
- [x] Dev/100 changes are limited to planning/documentation files; pre-existing unrelated worktree changes were left untouched.
- [x] Targeted stale-language searches and `git diff --check` pass.
- [x] The final status and evidence are recorded in this memo.

Verification evidence:

- repository registration contains 21 `BuiltinAgentSpec` entries;
- the frontend contains 13 direct `llmRequest(...)` call sites: 12 migration remainders plus the
  `DEC-041` Node Explanation exemption;
- the package seeder still documents the two-rename absence interval and required reader-lock follow-up;
- changed-document relative-link validation reported no broken Markdown links;
- targeted obsolete-status searches and fenced-code-block parity checks reported no failures;
- `git diff --check` passed;
- application test suites were not rerun because dev/100 changes documentation only.
