# Implementation Memo: Chat Panel as a Flush Full-Height Overlay Drawer

Date: 2026-07-21 (retroactive record, filed 2026-07-24 — bug report and fix were handled conversationally; this memo is the missing durable record)
Status: **implemented** (commit `c4f2339`; recorded as the `COMMIT-c4f2339` amendment on `BL-P4-20260721-14`); concepts re-rendered with the matching overlay treatment the same day (`_drawer_edge_shadow`, `docs/05` regeneration note)

## 1. Problem Statement

After the `DEC-042` header implementation, the chat panel's dark identity header rendered **clipped under the main top menu**: the panel was absolutely positioned (`top: 12px`) inside the canvas container, which extends beneath the top menu bar, so the header's first row (cycling, identity, Close) was hidden behind the menu — only the "Attached to … / session" line showed. The approved concept places the chat drawer flush with the viewport top, its dark header at the top-bar level of the right column.

## 2. As-Built Fix

- `AgentDockOverlay` renders `AgentChatPanel` through a **portal to `<body>`** (the same approach as the roster drawer's provider) instead of inside the canvas container.
- `.panel` becomes a **flush full-height right drawer**: `position: fixed; top: 0; right: 0; bottom: 0`, `z-index: 1100` — above the main top menu (z 100–200), below the roster drawer's backdrop (z 1200) so the roster overlays the chat when both are open.
- Floating-card styling replaced by drawer styling: no rounded corners/margins; a left hairline plus the leftward `-8px 0 24px` shadow matching the roster panel.
- Header top padding bumped (10→14px) to optically align the identity row with the adjacent menu bar.
- Concept parity: the renderer's chat and roster drawers gained the soft left edge shadow (`_drawer_edge_shadow`) and all PNG/SVG/workbook artifacts were regenerated, so the concepts show the same flush overlay.

## 3. Verification

Attach suites passed and `tsc` clean at commit time; visually confirmed against the user's screenshot report (header fully visible at the viewport top). Behavior unchanged: Escape/Close, cycling, transcripts, and the dock/badges are untouched — only where and how the panel is mounted and framed.

## 4. Traceability

- Commit `c4f2339`; BL amendment on `BL-P4-20260721-14`; concept regeneration recorded in `docs/05` ("flush full-height overlays", 2026-07-21).
- Complements `dev/21` (`DEC-042`): the header split assumed the header sits at the top-bar level; this memo records the positioning fix that makes that true in the app.
