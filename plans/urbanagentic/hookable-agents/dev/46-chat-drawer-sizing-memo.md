# Implementation Memo: Agent Chat Drawer — Catalog-Drawer Sizing Parity

Date: 2026-07-29
Status: implemented 2026-07-29 (same session)
Feature slice: container sizing only; the chat's content, layout rules, and interactions are untouched.

## 1. Problem Statement

The opened agent chat (`AgentChatPanel`) is a 380px-wide right drawer (`max-width: 90vw`), noticeably narrower than the established catalog drawers: the Agents Catalog panel is **560px / max-width 92vw** (its family sibling, dev/43), and the Nodes/Datasets drawers are `min(520px, 100vw)`. The requested behavior: the chat container matches the catalog-drawer dimensions and responsive behavior.

## 2. Scope + Approach

`AgentChatPanel.module.css` `.panel` only: `width: 380px; max-width: 90vw` → **`width: 560px; max-width: 92vw`** — the Agents Catalog drawer's exact sizing (the natural family match, and ≥ the 520px Node/Datasets panels, satisfying "enlarge"). Everything inside already scales: message bubbles are `max-width: 85%`, columns use `min-width: 0`, paddings/gutters are the docs/03 fixed 16px rhythm, and no rule assumes the 380px width — so **no internal spacing needs adjustment**. Full-height right-anchored fixed positioning, z-order, borders, shadow, transitions, and all chat behavior are unchanged.

## 3. Edge Cases / Testing

Narrow viewports: `max-width: 92vw` governs exactly as the catalog drawer does. CSS-module values are identity-proxied in jest — no unit-level assertion for dimensions; verification is visual, with all existing suites green (structure/behavior unchanged).

## 4. Acceptance Criteria

- [x] The chat drawer's width and responsive clamp match the Agents Catalog drawer (560px / 92vw) — same family sizing as the Nodes/Datasets drawers' scale.
- [x] Chat content, layout, spacing rhythm, and interactions are unchanged; only the container is larger.

## 5. Commit

One commit: `fix(agents): size the chat drawer to catalog-drawer dimensions (+ this memo)`.
