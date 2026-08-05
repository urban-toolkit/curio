# Implementation Memo: Plan Review Visibility — Fallback Parts + Strip Apply (dev/52 follow-up)

Date: 2026-08-05
Status: proposed (implementing in the same session — explicit fix request; post-implementation
testing feedback on dev/52: "the apply plan button is not appearing after showing the planned
nodes and connections")

## 1. Problem Statement (root causes)

The backend mints and streams the plan proposal correctly (verified end-to-end: chunked stream →
`review_required` → `done` content carries the pending proposal part; the tail never leaks as
text). Two client-side defects hide the Apply control:

1. **The pre-delta stream fallback drops content parts (a dev/41-era gap, now user-visible).**
   When streaming fails before the first delta (transport hiccup, SSE-hostile proxy), the
   provider falls back to the blocking run — but `useAgentAttachments.run` returns **only
   `r.reply`**, and the fallback appends a text-only turn. Every content part is silently
   discarded: the plan proposal (this report), and equally `node.create`/`dataset.install`
   proposals, suggested prompts, and dataset candidates over the same fallback. The user sees
   the model's prose describing the planned nodes and connections — and no review card.
2. **The builder strip names the review but offers no control.** In `plan_review` the strip
   disables Solve with "Apply or dismiss the plan review first", yet the Apply/Dismiss buttons
   live only on the transcript's review card — invisible exactly when defect 1 eats the part,
   and non-obvious even when present. The user's report phrasing ("the apply plan button")
   shows where they look: the builder strip.

## 2. Scope & Approach

- `useAgentAttachments.run` returns the full run payload (`reply`, `executionId`, `usage`,
  `content`); the provider's fallback appends the turn with execution + content and counts
  proposals for the post-send reload — **payload parity with the streamed path**.
- `AgentBuilderStrip` gains the sanctioned system review controls during `plan_review`:
  **Apply plan** / **Dismiss** wired to the SAME `applyProposal`/`dismissProposal` callbacks,
  targeting the attachment's `activeProposal` mirror (tool `dataflow.plan.write`, pending) —
  the mirror is exactly the "fast lookup" home dev/41 built for this, so the control works even
  when a transcript part is missing. No new action pattern: these are the existing review
  actions surfaced where the phase indicator already points.
- Untouched: backend (verified correct), the transcript review card (still renders and still
  works), every other agent's chat.

## 3. Tests / Acceptance

- Provider: a pre-delta stream failure falls back AND the appended turn carries the content
  parts (the proposal card renders; regression for all part kinds over the fallback).
- Strip: `plan_review` + a pending `dataflow.plan.write` activeProposal → Apply plan / Dismiss
  buttons calling the callbacks with the mirror's proposalId; no buttons for other phases or
  other proposal kinds; busy state during apply.
- [ ] The Apply control is reachable from the strip whenever a plan review is pending,
      regardless of transport path; fallback runs lose no content parts.

## 4. Commits

1. `Plan review visibility: fallback keeps content parts + builder-strip Apply/Dismiss (dev/53)`
2. Docs: memo implemented + BL-P5 amendment.
