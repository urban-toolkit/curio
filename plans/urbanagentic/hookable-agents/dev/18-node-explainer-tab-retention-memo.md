# Implementation Memo: Node Explainer Tab Retention (Cancellation of the Explanation-Tab Removal)

Date: 2026-07-21
Status: approved product decision
Decision recorded: **`DEC-041`** (supersedes **`DEC-033`**)
Supersedes: the Explanation-tab-removal provisions of `12-agent-template-installation-attachment-sharing-lifecycle-memo.md`, `REQ-NODE-EXPLAIN-001`, `RISK-EXPLAIN-001`, memo `17` §3.5 (H-7 archival step), and every downstream plan/blueprint/build-log statement that instructs or implies removing the built-in node Explanation tab.

## 1. Problem Statement

The active plan (`DEC-033`, memo `12`) required removing the built-in node Explanation tab, its state/cache, and its direct `single_box_explanation_prompt` provider path after Node Explainer agent-chat parity, making the attached Node Explainer unified chat the sole node-explanation surface. That removal has now been **permanently cancelled** as a product decision: the Explanation tab must remain part of the node UI. Planning documents, acceptance criteria, build-log status lines, and pending-task lists still instructed the removal, so without correction a future implementation task would delete UI the product has decided to keep.

## 2. Decision — `DEC-041`

1. The built-in node Explanation tab (`components/editing/NodeEditor.tsx` tab + `components/editing/NodeExplanation.tsx`), including its direct prompt/provider request path, loading/error states, cache, and `hasExplanation` configuration, **remains part of the node UI permanently**. It is preserved as-is.
2. `DEC-033` is **superseded and must not be implemented**, in whole or in part, by any current or future task. This includes partial removals (tab hidden behind a flag, direct caller stripped, cache deleted, `hasExplanation` propagation removed).
3. The attached **Node Explainer agent** (`agent.node-explainer`) and its install → attach → unified-chat workflow are unchanged and **coexist** with the tab as an additional, optional explanation surface. Nothing in this memo removes, redesigns, or modifies the agent, its attachment behavior, its dock/badge interaction, or any other node or agent functionality.
4. No parity-migration, content-archival, or fallback-elimination work tied to the removal is required. Memo `17` §3.5 (H-7: archive historical Explanation-tab text into a Node Explainer chat entry on removal) is **moot** — the tab and its content stay where they are.

## 3. Identifier Changes

| Identifier | Disposition |
| --- | --- |
| `DEC-033` | Superseded by `DEC-041`. Retired from the active decision set; must not be implemented or cited as current direction. The identifier is not reused. |
| `DEC-041` | Active. The node Explanation tab is retained permanently; the Node Explainer agent chat is a coexisting, not replacing, surface. |
| `REQ-NODE-EXPLAIN-001` | Retired (it required the removal). Not reused. |
| `REQ-NODE-EXPLAIN-002` | Active replacement: the node Explanation tab and its existing behavior remain present and functional; the Node Explainer agent attach/chat path also remains functional; neither path may be removed by agent-feature work. |
| `RISK-EXPLAIN-001` | Retired (it treated the surviving tab as the risk). Not reused. |
| `RISK-EXPLAIN-002` | Active replacement: the obsolete removal requirement is reintroduced from a stale document, plan row, or build-log follow-up line, and the tab (or its direct path) is deleted. Mitigation: this memo, the corrected active tables, retired-ID policy (memo `13` — retired IDs are never reused, gaps communicate retirement), and a regression test asserting the Explanation tab renders. |

## 4. Documentation Corrections Required by This Memo

- `00-development-phase-index.md`: register this memo; annotate the memo-`12` entry so "Node Explainer chat as the sole node-explanation path" is marked superseded.
- `12-...-lifecycle-memo.md`: amendment banner plus in-place correction of every removal instruction (scope, requirement §, UI/UX, edge cases, tests, acceptance criteria, commit plan, checklist).
- `03-agents-catalog-development-plan.md`: `DEC-033` row marked superseded; `REQ-NODE-EXPLAIN-001`/`RISK-EXPLAIN-001` rows replaced per §3; every removal statement in scope, acceptance criteria, module map, phase exits, test plan, commit plan, and checklist corrected to retention.
- `02-development-plan-brief.md`: historical brief — amendment banner (content preserved as the original planning record).
- `13-...-consolidation-memo.md`, `14-...-open-decisions-memo.md`, `17-hardening-resolutions-memo.md`: correct the lines that assert the sole-path/removal model or schedule the H-7 archival.
- `kggraph/Stage-2-Design-Phase/2.1-...Design-Traceability.md`: `DEC-033` marked superseded, `DEC-041` added, requirement/risk rows updated, `ART-PNG-04` note corrected.
- `kggraph/Stage-3-Build-Phase/3.1-...Build-Log.md`: phase-index row, v1 release-cut definition, deferred list, and tracking rules `20`/`21` corrected; this memo added to the source header.
- `agents-catalog/BL-P4-attachments-chat.md`: append a correction entry recording the cancellation; annotate (not erase) the stale "Node Explainer tab removal" follow-up lines in prior entries, per the append-only rules.

## 5. Guardrails Against Reintroduction

- Any document, task list, or generated artifact that still instructs removing the Explanation tab is **stale evidence, not implementation direction**; it must be corrected on contact, citing `DEC-041`.
- Build-log tracking rule `21` (Node Explainer migration evidence) is retired; no phase gate requires tab-removal evidence.
- The v1 release cut (`DEC-038`) no longer contains the "Node Explainer tab removal" item; v1 completeness must not be blocked on, or satisfied by, any removal work.
- Future memos touching node explanation must cite `DEC-041` and `REQ-NODE-EXPLAIN-002`; a memo proposing removal again would require an explicit new product decision that names and supersedes `DEC-041` — silence or omission never reopens the removal.

## 6. Acceptance Criteria

- [ ] No active planning or build-tracking document states or implies that the node Explanation tab will be removed, without an adjacent supersession note citing `DEC-041`.
- [ ] `DEC-033`, `REQ-NODE-EXPLAIN-001`, and `RISK-EXPLAIN-001` appear only as superseded/retired identifiers.
- [ ] The Explanation tab, its direct request path, and `hasExplanation` behavior are untouched by this change (documentation-only; no code changes).
- [ ] The Node Explainer agent attach/chat workflow is untouched.
- [ ] The BL-P4 build log records the cancellation as an append-only correction entry.
