# dev/96 — The rich package-draft review card: the diff, dependencies, and preview the Apply text already claims the user reviewed

**Status: APPROVED (owner, 2026-08-24). Implementation in progress.**
Prereqs: dev/89 (DEC-059 — the build service and its provenance), dev/91 (the card's backend trust-edge block, the pattern this extends), dev/95 complete. This memo implements a surface DEC-059 already promised — no new decision is minted; the dev/89 "rich review card = deferred polish" gap closes.

---

## 0. Evidence — the review claim is stronger than the review surface

- **The mint's own words overpromise.** `_mint_package_draft_apply` tells the model (and the transcript): *"It awaits the user's explicit review of the diff, dependencies, and preview"* — and dev/89 §5's acceptance line says the same. What the card actually renders for `package.draft.apply`: the summary, ONE counts line ("2 added / 0 modified / 0 preserved files; 1 node(s) after install"), the EFFECT_LINE, and (since dev/91) the backend trust-edge block. The diff names, the SBOM, and the preview verdicts never reach the user's eyes before Apply.
- **The full provenance already EXISTS — one seam away.** The proposal mirror persists `diff` (the MergePlan payload: files/templates × preserved/modified/added, by name), `policyFindings`, `preview` (status, reasons, per-template/state report, registered behavior keys), `backend` (dev/91), and `requestedNodes`. The transcript part — what the card renders from, including after reload — carries none of it. Composing a bounded slice onto the part is the whole backend job.
- **Screenshots cannot be rendered, honestly.** `PreviewResult.to_payload` records screenshots as **digest + byte-count only** ("the caller owns byte storage" — and no caller stores them; the workspace is destroyed after every build). The card can therefore show per-template, per-state VERDICTS and the runner version — never images. Persisting screenshot bytes is its own storage/retention feature, out of scope and stated so.
- **Bounded-part discipline is a standing lesson (A6):** parts persist with every turn; an unbounded SBOM or file list in a part is the same class of bug as the 3KB-tail failure. Every list the part gains must carry its own cap plus an honest overflow count.
- **The card already has the patterns to extend:** the dev/91 backend block (a `role="group"` section), the plan card's scrollable node list, severity-styled findings text. Native `<details>/<summary>` gives collapsible sections with zero new interaction machinery (keyboard/screen-reader native) — the counts line stays the collapsed summary, so the default card stays exactly as calm as today.

## 1. Problem Statement

A `package.draft.apply` review card claims the user reviews the diff, dependencies, and preview — but shows only counts, so the real review happens blind: which files a draft adds or modifies, which pinned dependencies (and which warn-level findings) ride it, and whether the preview passed, failed, or was skipped under the operator's A9 declaration are all invisible until after Apply. Expected: the card carries three collapsible, bounded sections — Files, Dependencies, Preview — plus the requested-nodes row, rendered from data minted onto the part (so reloads keep it), with every cap honest about what it elided. Nothing about the apply flow, pins, or proposal lifecycle changes.

## 2. Scope

Included:

- **Backend** — one composer, `_draft_card_payload(request, result)` in `agents/services.py` beside the mint: a bounded `part["draft"]` payload
  — `files`: added/modified name lists (cap 20 each, `+N more` via honest counts), `preservedCount`;
  — `templates`: added/modified id lists (cap 10), `preservedCount`;
  — `dependencies`: python rows (name+constraint, cap 10), js direct rows (name+version, cap 10), findings (severity/code/message, cap 10, blocks first), totals for every capped list;
  — `preview`: `status` (`ok`/`failed`/`skipped` with the A9 policy named when skipped), `reasons` (cap 3), per-template rows `{templateId, ok, failedStates}` (cap 8), `runnerVersion`;
  — `requestedNodes`: `{title, color}` rows (cap 8) + total.
  The SAME payload is stored on the proposal mirror (`draftCard`) for symmetry, but the PART is the render source (reload-safe). Absent sections stay absent — a plain create with no deps renders no Dependencies section.
- **Frontend** — `AgentProposalPart.draft` type; three `<details>` sections on the `package.draft.apply` card between the meta line and the backend block, each `<summary>` carrying the counts it expands (Files, Dependencies — findings severity-styled with the existing error/warn text classes, Preview — per-template rows with failed states named, the skip line verbatim); a requested-nodes line with color names. Collapsed by default; blocking findings and a failed preview render their section OPEN (the user must not be able to miss them — though a failed preview cannot reach a card today, drift-tolerance says render honestly if one ever does).
- **Tests** — backend: composer caps/overflow counts/absent-section omission, mint attaches the payload, E2E part carries it after a real build (extend the existing draft-lane tests); frontend jest: sections render with counts, findings severity classes, skipped-preview honesty line, open-by-default on block findings, absent sections absent.
- **Docs** — BL-P5-…-39 entry; dev/89 memo's "deferred polish" note annotated delivered; memo flip. **No new DEC** — DEC-059 already decided this surface; the ledger records the closure.

Out of scope: screenshot bytes/rendering (no storage exists — its own feature if ever demanded); any change to apply/dismiss, pins, supersession, or proposal size elsewhere; the package-install (catalog) card; markdown rendering of file contents (names only — content review stays the artifact's job).

## 3. Recommended Implementation Approach

One composer, one consumer chain: `_draft_card_payload` reads ONLY the typed `PackageBuildResult`/request already in scope at the mint (no new reads), applies per-list caps with `total` fields (never silent truncation — the workflow no-silent-caps rule), and the card renders what is present. Frontend sections reuse the dev/91 block's structure and the card's existing text classes; `<details>` keeps interaction native. Findings ordering: blocks before warns before notes, so the cap never hides a block behind notes.

## 4. Data and State Handling

The part is the source of truth for rendering (persisted with the turn, reload-safe); the mirror's `draftCard` copy exists only so the attachment listing could surface it later. No state updates after mint — the payload is immutable provenance. Size: worst case ≈ 20+20+10+10+10+8+8 short rows — well under the part-size norms; a composer test pins the ceiling.

## 5. UI and UX Requirements

Default collapsed → the card's height today is preserved; summaries carry the counts ("Files — 2 added · 0 modified · 14 preserved"). Blocking findings/failed preview auto-open with the existing danger styling. All text inert (REQ-SEC-002 — model-authored names render as text, never markup). Keyboard/AT: native disclosure semantics, section summaries are real `<summary>` elements.

## 6. Edge Cases

1. Create mode with no preserved files: preserved shows 0, never omitted (0 is information).
2. 200-file extension draft: 20 names + "…and 180 more" from the totals — nothing silently dropped.
3. Skipped preview (A9): the section states the operator declaration verbatim — unpreviewed must be impossible to mistake for passed.
4. Draft with zero requested nodes: the row is absent.
5. Old proposals minted before dev/96 (no `draft` field): the card renders exactly as today — additive, never a migration.
6. Findings over the cap: blocks sort first; the overflow count says how many more of which severity.

## 7. Testing Strategy

Backend: composer unit matrix (caps, ordering, omission, ceiling), mint attachment, E2E through the existing DFB/PB draft lanes asserting the part's `draft` payload after a REAL build. Frontend: jest section matrix incl. the pre-dev/96 part regression. Full suites both sides.

## 8. Acceptance Criteria

1. A draft card shows, before Apply: the named file/template diff, the pinned dependency rows with severity-styled findings, and the preview verdict (incl. the honest skip line) — all bounded with explicit overflow counts.
2. Blocking findings and failed previews cannot be collapsed-away by default.
3. Pre-dev/96 proposals render unchanged; nothing else about the proposal lifecycle moves.
4. The mint's "explicit review of the diff, dependencies, and preview" sentence is finally true.

## 9. Recommended Commit Breakdown

- Commit 1 — backend composer + mint/part/mirror wiring + tests.
- Commit 2 — frontend type + card sections + jest.
- Commit 3 — docs: BL-39, dev/89 gap note annotated, memo flip.

## 10. Engineering Quality Checklist

- [ ] One composer; the card renders, never re-derives.
- [ ] Every capped list carries its total — no silent truncation anywhere.
- [ ] Additive part field; old proposals untouched.
- [ ] Inert text rendering throughout; native disclosure semantics.
- [ ] No screenshot promises the storage cannot keep.
