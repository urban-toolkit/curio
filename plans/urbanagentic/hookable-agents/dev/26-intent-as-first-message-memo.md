# Implementation Memo: Initial Intent as the Conversation's First Message

Date: 2026-07-21 (retroactive record, filed 2026-07-24 — this change was specified and approved conversationally and implemented the same day; this memo is the missing durable record)
Status: **implemented** (commit `c88193a`; recorded as the `COMMIT-c88193a` amendment on `BL-P4-20260721-13`)
Amends: memo `dev/19` §3/§5 (the pinned INITIAL INTENT block) and the `docs/08` drawer anatomy

## 1. Problem Statement

Memo `dev/19` shipped the initial intent as a **pinned, labeled block** between the chat header and the transcript: an "INITIAL INTENT" small-caps label, a raised inner panel, an "edited" chip, and (after the scroll fix) a 45%-height cap. Product feedback: the intent should read as **the conversation's first chat message** — no special styling — because visually it *is* the opening prompt of the conversation, and the dedicated block consumed header real estate and introduced a second visual system for what is semantically a message.

## 2. Decision

The initial intent renders as the **first user bubble at the top of the transcript** — plain `msgUser` styling, scrolling away with the conversation like any message — while keeping the two affordances that make it the intent rather than a mere message:

- **collapsed by default** (4-line clamp) with a `Show more / Show less` toggle beneath the bubble;
- the **edit pencil** beside the toggle, swapping the bubble for the same textarea editor (Save persists via the `PATCH` intent route; emptying restores the prompt source; Cancel reverts).

Dropped with the pinned block: the "INITIAL INTENT" label, the raised inner panel, the "edited" chip, and the 45% height cap (obsolete once the intent scrolls inside the transcript). The intent's data model (`intent`/`intentEdited` on the attachment card, prompt-source resolution, run-uses-intent — all `dev/19`) is unchanged; this is presentation only.

## 3. As-Built Implementation

- `AgentChatPanel.tsx`: the intent block moved inside `.messages` as the first element — view mode (bubble + controls row) and edit mode (full-width textarea + Save/Cancel) — placeholder bubble when the definition has no prompt asset.
- `AgentChatPanel.module.css`: pinned-block classes (`intent`, `intentHead`, `intentLabel`, `intentEditedChip`, `intentText`) replaced by message-styled ones (`intentMsg`, `intentControls`, `intentEdit`, `intentEditor`); clamp and placeholder classes retained; the dark-bubble placeholder restyled for dark background.
- Concept renderer parity: `draw_agent_chat` renders the intent as the first user bubble (`_chat_header` no longer draws a standalone intent field), so the regenerated concepts and the implementation agree.

## 4. Verification

- `AgentChatPanel.test.tsx` updated: the intent renders with `msgUser` (plain first-message) styling, clamps with a working toggle, edits/saves/clears; attach suites 28 passed; `tsc` clean at commit time.
- Documentation: the `docs/08` anatomy's former "INITIAL INTENT [pinned]" line is corrected alongside this memo's filing.

## 5. Traceability

- Commit `c88193a`; BL amendment on `BL-P4-20260721-13`.
- Supersedes the pinned-block presentation of memo `dev/19` §3/§5; everything else in `dev/19` stands.
