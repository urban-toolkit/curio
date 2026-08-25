# Dev/104 — Roster consolidation and tracked remainders: the story's additive gaps

Date: 2026-08-25
Status: **implemented 2026-08-25** — documentation-only; completes the additive findings of the 2026-08-25 story review (dev/102 fixed staleness, dev/103 fixed contradictions; this memo adds what was merely absent)
Branch baseline: `feat/agentscatalog` with `BL-P5-20260824-43` (dev/101) as the newest verified ledger entry

## 1. Problem Statement

Four things were true but written down nowhere a story reader would find them:

1. **The 21-agent roster had no consolidated table.** dev/03/dev/05 enumerate only the fourteen
   prompt-backed rows; the three composites, Node Researcher, Package Recommendation, Package Builder,
   and Researcher existed only inside dense decision-row prose. `docs/11` asserts "twenty-one shipped
   built-ins" with no story table to check it against.
2. **The backend-owned spec-section rule was invisible in the story's persistence sections.** dev/29
   (`agents`/`agentAttachments`/`agentDefaults`), dev/81 (`dataflow.datasets`), and dev/101
   (`dataflow.packages`) established that a canvas save cannot clobber these sections — a load-bearing
   persistence invariant absent from dev/03's "Sources of truth"/mutation rules and dev/05 §11.
3. **Two risk rows overstated their mitigations.** `RISK-SECRET-001`'s row read as if the plaintext-key
   migration were handled, though the legacy column persists until T4; dev/03's migration table even
   claimed Explanation-tab retention was "verified by a regression test" that `BL-P4-20260721-11` records
   as recommended-only and unwritten (`RISK-EXPLAIN-002`).
4. **Eight small open items had no tracking home**: the drawer `Unpublish` control, alerts/pricing-date
   surfacing, LLMChat shared-piece adoption, the tsconfig deprecations, `current_input/current_output`
   wiring, the `connection` attach target, `DEC-037` evaluation sub-budgets, and the tab-renders test —
   each recorded once in a build-log follow-up line and nowhere else.

## 2. Scope

Included (additions only; no status or decision changes):

- dev/03: a "Complete shipped roster (21 built-ins)" table after the prompt-backed table; a
  "Backend-owned project-spec sections" row in Sources of truth plus a mutation-rules bullet; the T4
  plaintext-posture note in §10; the two `RISK-EXPLAIN-002` truthfulness corrections (risk row + the
  migration-table cell).
- dev/05: a current-roster pointer after the §13 table; the backend-owned-sections rule in §11 before
  "Transactions".
- `2.1`: current-posture notes on the `RISK-SECRET-001` and `RISK-EXPLAIN-002` rows.
- `3.1` (mutable index summary): one "Minor tracked polish/loose ends" line consolidating the eight items.
- `dev/00`: one index row for this memo.

Out of scope: implementing any of the tracked items (each stays a documentation pointer to its build-log
origin; the loose ends are non-blocking and unscheduled); code, tests, BL entry bodies; committing or
staging (the dev/100 set stays staged by its owning session; dev/102/103/104 edits stay unstaged).

## 3. Recommended Implementation Approach

Additions mirror existing structures rather than inventing new ones: the roster table reuses the
prompt-backed table's column style; the persistence rule lands as one Sources-of-truth row + one mutation
bullet (dev/03's own idiom) and one italic current-rule note (dev/05's idiom); the remainders line joins
`3.1`'s existing remainder/gate/demand-gated family so all four remainder categories live in one block.
Overstated mitigation text is corrected directly (it is falsifiable), with the build-log entry named.

## 4. Data and State Handling

No application data or runtime state changes. Sources: `docs/AGENTS.md` + `docs/11` (roster),
dev/29/81/101 (backend-owned sections), `BL-P2` entry 01 (plaintext column), `BL-P4-20260721-11`
(recommended-only test), and the build-log follow-up lines each loose end cites.

## 5. UI and UX Requirements

None (documentation only). The roster must be checkable in one place; the persistence invariant must be
findable where persistence is specified; no mitigation may claim a test that does not exist.

## 6. Edge Cases

- The roster table names authorities (memo + DEC), not re-specified behavior — the memos stay canonical.
- The loose-ends line marks items non-blocking so they cannot be mistaken for release gates; `DEC-037`
  stays v2-governance-gated, not newly scheduled.
- `BL-P3`'s Unpublish/alerts items carry no stable entry ids in their follow-up lines; they are cited by
  phase log, not invented ids.

## 7. Testing Strategy

Documentation-only: asserted-anchor replacements, relative-link checks for the new dev/00 row, and
`git diff --check`. No application suites.

## 8. Acceptance Criteria

1. dev/03 contains one table enumerating all 21 built-ins consistent with `docs/AGENTS.md`/`docs/11`;
   dev/05 points to it.
2. Both story persistence sections state the dev/29/81/101 backend-owned-sections rule.
3. No document claims the Explanation-tab regression test exists; both `RISK-SECRET-001` rows/sections
   state the plaintext-until-T4 posture.
4. `3.1` lists the eight minor items in one non-blocking tracked line.
5. No status, decision, gate, or remainder classification changed; nothing staged or committed.

## 9. Recommended Commit Breakdown

One documentation commit (this memo + dev/03 + dev/05 + 2.1 + 3.1 + the dev/00 row), pathspec-scoped,
made by the owner adjacent to the dev/100/102/103 documentation commits.

## 10. Engineering Quality Checklist

- [x] Additions only — no historical evidence rewritten, no status flipped, no scope re-litigated.
- [x] The roster table agrees with `docs/AGENTS.md` and `docs/11` (21 built-ins; 14 + 7).
- [x] Every tracked loose end names its build-log origin; none is presented as scheduled work.
- [x] Overstated mitigations corrected with the recording BL entry named.
- [x] All anchors matched exactly once; `git diff --check` passes; nothing staged or committed.

Verification evidence:

- the dev/03 roster table's seven added rows each cite their authorizing DEC + memo; counts reconcile
  (14 prompt-backed + 7 = 21, matching `docs/11`'s "twenty-one shipped built-ins");
- "verified by a regression test" no longer appears for the Explanation tab; both sites say
  recommended-only per `BL-P4-20260721-11`;
- `git diff --check` reports no whitespace errors; application test suites were not run (documentation only).
