# Dev/102 — Reconciliation follow-up: entry points advanced from dev/97 to dev/101

Date: 2026-08-25
Status: **implemented 2026-08-25** — documentation-only follow-up to [`dev/100`](100-planning-document-reconciliation-memo.md)
Branch baseline: `feat/agentscatalog` with `BL-P5-20260824-43` (dev/101) as the newest verified ledger entry

## 1. Problem Statement

Dev/100 reconciled the canonical entry points through dev/97, but dev/98 (reference preview runner,
`BL-P5-20260824-41`), dev/99 (package-seed reader locking, `BL-P5-20260824-42`), and dev/101 (project
package lockfile authority, `BL-P5-20260824-43`) landed around it. As a result:

1. Every "current through" claim stopped at dev/97 / `BL-P5-20260824-40` — `README.md`, `dev/03` (status,
   evidence pointer), `dev/05` (status, current overlay), `2.1` (status), and `3.1` (status header, verified-trail
   line, roster line) — while `3.1`'s own remainder line already cited `BL-P5-20260824-42`, so the build-log
   index contradicted its own header.
2. `README.md` and `dev/00` reported dev/99 as "implementation has not started" / "PROPOSED —
   IMPLEMENTATION NOT STARTED", and the dev/03/dev/05 remainder lists still carried "the package-seed
   reader lock", though `dev/99` is **IMPLEMENTED 2026-08-24** (commits `ea802aa7`…`248e3ebf`; R1.1
   resolved by Amendment R2 before implementation).
3. `dev/00` had no index rows at all for dev/98 or dev/101 — breaking dev/100's own acceptance criterion
   that the index link every numbered memo family.
4. `3.1`'s demand-gated line listed "reference-preview runner/screenshot storage" as one demand-gated item,
   though the runner itself shipped (`dev/98`); only screenshot storage and the Linux preview-limits tier
   remain conditional.

A reader following the canonical reading order could re-plan the shipped dev/99 work or miss dev/98/101
entirely.

## 2. Scope

Included (the four mechanical items above, nothing else):

- `README.md`: header status line → dev/101/`BL-43` + this memo linked; shipped-evidence sentence gains
  dev/98/99/101; the stale dev/99 remainder bullet removed.
- `dev/00-development-phase-index.md`: dev/99 row corrected to IMPLEMENTED; new rows for dev/98,
  dev/101, and dev/102; rows reordered numerically (99, 100, 101, 102); the dev/93 row's "seed-reader lock
  remains" tail corrected to "closed by dev/99".
- `dev/03` and `dev/05`: status headers → "verified through dev/101"; overlay dates → 2026-08-25; evidence
  pointer → `BL-P5-20260824-43`; "the package-seed reader lock" removed from both remainder lists (dev/03
  keeps an adjacent closure note; dev/05's overlay names the dev/98–101 additions).
- `2.1`: status line → "implemented through dev/101, 2026-08-24".
- `3.1` (mutable index summary only): status header, verified-trail line, and roster line → dev/101/`BL-43`;
  the demand-gated line now separates the shipped runner from its demand-gated storage/limits tiers.

Out of scope (deliberately — each needs its own supersession pass, not this mechanical one):

- the LangChain-normative sections of dev/03/dev/05 left un-annotated by `DEC-048`'s retirement;
- dev/05's retired `evaluation-disabled` registry mapping and test fixture; the `REQ-PROMPT-002`
  thirteen-vs-twelve caller wording; open-tense OQ-008 obligations; the un-annotated DEC-021/DEC-052/
  DEC-038 rows; a consolidated 21-agent roster table; reflecting dev/101's backend-owned section rule in the
  story's persistence sections;
- append-only BL entry bodies (`BL-P5-…-41` still records the then-open dev/100 renumber item — history,
  not current state);
- implementation code, tests, and generated visual artifacts;
- committing or staging: the dev/100 set is staged by another session; all dev/102 edits stay in the working
  tree for the owner to combine or commit separately.

## 3. Recommended Implementation Approach

Same posture as dev/100: one status vocabulary, the latest verified BL entry as evidence authority,
corrections applied directly where a canonical statement is simply false, and adjacent closure notes where
the old text is useful history (the dev/03 remainder sentence). Exact-string replacements with asserted
occurrence counts so any drifted anchor fails loudly instead of editing the wrong text.

## 4. Data and State Handling

No application data or runtime state changes. Status derives from: dev/98/99/101 memo status headers,
`BL-P5-20260824-41`…`43`, and dev/99's Amendment R2 record. Nothing is inferred from proposals.

## 5. UI and UX Requirements

None (documentation only). The entry points must read consistently: every "current through" pointer names
dev/101/`BL-P5-20260824-43`; no document claims dev/99 is unimplemented; demand-gated lists name only
genuinely demand-gated work.

## 6. Edge Cases

- `3.1`'s remainder line (`BL-42` parenthetical) was already correct — left untouched.
- BL entry bodies remain append-only; only `3.1`'s mutable index summary changed.
- `2.1`/`3.1` keep the 2026-08-24 date (dev/101's implementation date); dev/03/05 overlay dates advance to
  2026-08-25 (the date of this documentation pass).
- The dev/00 list previously ordered 100 before 99; the corrected block restores numeric order without
  touching any other row.

## 7. Testing Strategy

Documentation-only: targeted stale-string searches (see verification), relative-link existence checks for the
new rows, and `git diff --check`. No application suites run.

## 8. Acceptance Criteria

1. No canonical/current document claims implementation stops at dev/97 or `BL-P5-20260824-40`.
2. No document states dev/99 is proposed/unstarted; the remainder lists no longer contain the seed-reader lock.
3. `dev/00` links dev/98 and dev/101 (and this memo) with truthful one-line statuses.
4. `3.1`'s demand-gated line names screenshot storage and the Linux limits tier, not the shipped runner.
5. The canonical three-item remainder (twelve-caller cutover, T4, DEC-058) and the OQ-009/OQ-010 gates are
   unchanged everywhere.
6. No implementation file changes; nothing newly staged or committed by this pass.

## 9. Recommended Commit Breakdown

One documentation commit (this memo + the seven touched documents), pathspec-scoped to those files, made
by the owner when the staged dev/100 set is committed — either folded into that commit or immediately after
it, so the two reconciliation layers land adjacent in history.

## 10. Engineering Quality Checklist

- [x] No historical build evidence was erased or rewritten (BL bodies untouched).
- [x] Current status is derived from verified memos/BL entries `41`–`43`, not assumption.
- [x] Remaining, demand-gated, and deployment-gated work stay separated; only membership was corrected.
- [x] The three-item concrete remainder and both deployment gates are preserved verbatim in meaning.
- [x] Edits used asserted exact-match replacements; every anchor matched exactly once.
- [x] All added links resolve; `git diff --check` passes.
- [x] Changes are limited to planning/documentation files; nothing was staged or committed.

Verification evidence:

- stale-string sweep over the seven documents returns no hits for: "through dev/97" as a current-status claim,
  "CURRENT THROUGH DEV/97", "BL-P5-20260824-40" as the trail terminus, "implementation has not started",
  "IMPLEMENTATION NOT STARTED", "seed-reader lock remains", "the package-seed reader lock" in a
  remainder list, or "reference-preview runner/screenshot storage";
- `dev/00` contains exactly one row each for dev/98 through dev/102, in numeric order;
- relative links added by this pass point at files that exist on disk;
- `git diff --check` reports no whitespace errors;
- application test suites were not run (documentation only).
