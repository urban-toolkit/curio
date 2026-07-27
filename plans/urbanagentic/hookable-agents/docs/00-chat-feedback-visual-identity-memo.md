# Implementation Memo: Chat Feedback Visual Identity (Claude-like, on Curio tokens)

## 1. Problem Statement

The in-chat feedback components (suggestion cards, confirmation/result cards, radio and
checkbox options, selection states, inline decisions/status, tokens/chips) had grown
inconsistent: stark white cards with hard borders, heavy full-height colored accent bars,
saturated status blocks, filled/segmented option pills, and mixed spacing. They did not read
as one system and diverged from the polished, low-chrome feel of Claude's agent chat.

Desired: update the **visual identity of all chat-related feedback components** so they feel
consistent with Claude's agent chat patterns — clear grouping, subtle surfaces, readable
option states, polished spacing, lightweight interaction feedback — **while remaining
consistent with Curio's overall UI system** (tokens, accents, Rubik/Roboto Mono, radii).

Why it matters: a single, calm, legible feedback language makes every agent's chat feel
trustworthy and predictable, reduces visual noise, and keeps the concept aligned with a
familiar agent-chat aesthetic without inventing a Curio-foreign look.

## 2. Scope

Included (concept renderer + docs only — no product code):

- **Renderer** `sources/render_hookable_agents_png_concepts.py`:
  - New shared tokens: `CHAT_SURFACE` `#f7f7f8`, `CHAT_INNER` `#ffffff`, `CHAT_BORDER`
    `#ececee`, `CHAT_RADIUS` `12`, `CHAT_TITLE`, `CHAT_META`, `OPT_BORDER`, plus per-accent
    `_OPT_SEL` (soft selection tints) and `_TONE` (soft status/result fills + borders).
  - New helpers: `_card_shell` (grouped surface + header row with a small leading accent dot),
    `_radio` (single-select control); restyled `_checkbox` (rounded, hairline) and `_chip`
    (soft filled token, optional hairline, no hard outline).
  - Restyled every chat card: `_card_sources` (grouped rows + soft selected-row wash),
    `_card_behavior` (segmented pills → **radio option rows**), `_card_preview` (raised inner
    code panel + subtle surface), `_card_handoff` / `_card_install` / `_card_result` (soft tone
    surfaces, no full-height bars), `_card_plan` / `_card_agents` (grouped surface + soft
    status chips). Softened `_chat_system` and the "SUGGESTED PROMPTS" chips.
- **Docs**: `03-ui-decisions.md` (new "Chat feedback visual system" subsection),
  `08-unified-agent-chat.md` (visual-style note). Regenerated PNG + SVG + workbook.

Out of scope: layout/IA, the suggested-prompt interaction model (already settled), the
palette/catalog, node cards, and top bar. No new agent behavior.

## 3. Recommended Implementation Approach

- **One token set, one shell.** Centralize the surface/border/radius/typography and the
  selection/tone palettes as tokens; route all cards through `_card_shell` so grouping,
  header rhythm, and identity (leading accent dot) are uniform. This mirrors how a design
  system exposes a `Card` + `Option` primitive.
- **Match Claude's feel, keep Curio's palette.** Subtle neutral surfaces and hairlines like
  Claude; accents/tints derived from Curio's existing `ORANGE / BLUE / GREEN / PURPLE`
  tokens (soft washes for selection, gentle tones for status) so nothing looks foreign.
- **Readable, lightweight option states.** Full-width radio/checkbox rows with a soft accent
  wash + hairline outline + filled control on selection — obvious but not heavy.
- **Group dense content.** Put code/tables/option lists in raised white inner panels within
  the card for clear visual grouping.

## 4. Data and State Handling

Purely presentational. Selection state (`checked` / selected index) already drives the
controls; the restyle maps those states to the soft-wash + filled-control treatment. Status
(`done` / `running` / `queued`) maps to the `_AGENT_STATUS` tone chips. No data flow changes.

## 5. UI and UX Requirements

- Cards: `#f7f7f8` surface, `#ececee` hairline, `12px` radius, no shadow; header = leading
  accent dot + title (`CHAT_TITLE`) + right-aligned meta (`CHAT_META`).
- Options: rounded hairline checkbox / radio; selected row = soft per-accent wash
  (`_OPT_SEL`) + hairline accent outline + filled control.
- Status / result / hand-off / install: soft per-accent tone fill + matching hairline
  (`_TONE`) + leading icon; no saturated blocks or full-height bars.
- Tokens/chips: soft filled surface, optional hairline, `8px` radius; labels accompany colour.
- Spacing: `16px` gutters, roomy headers, even option rhythm; AA-legible text on tints.

## 6. Edge Cases

Long option/label text (rows are full-width, text left-aligned, meta right-aligned so they
don't collide); many plan steps / agents (grouped surface grows with content); light vs. dark
theme (concept renders light — tokens chosen for light; a dark mapping would mirror the same
roles); a card with no accent (neutral group, e.g. specialized-agents — no dot).

## 7. Testing Strategy

Regenerate PNG + SVG and confirm across scenes: 03 (sources: grouped rows + soft selection),
06 (behavior: radio rows + selected state), 08 (preview: raised code panel), 07 (hand-off +
install tone surfaces), 10 (plan + agent-status chips). Verify SVG/PNG parity, that borders
render as hairlines (not doubled), and that the workbook rebuilds with matching annotations.

## 8. Acceptance Criteria

- All chat feedback components share one visual language: subtle grouped surfaces, hairline
  borders, readable radio/checkbox option states, soft status/result tones, soft tokens,
  polished spacing.
- The look reads as Claude-like agent chat while remaining consistent with Curio tokens and
  accents (no foreign palette, no heavy chrome).
- No component still uses stark white + hard border, full-height colored bars, saturated
  status blocks, or segmented filled option pills.

## 9. Recommended Commit Breakdown

1. Add tokens + `_card_shell` / `_radio`; restyle `_checkbox` / `_chip`.
2. Restyle option cards (`_card_sources`, `_card_behavior`) with grouped rows + selection.
3. Restyle status/result/preview cards (tones + raised inner panels) and system line / chips.
4. Update docs (`03`, `08`) + workbook note; regenerate PNG → SVG → workbook.

## 10. Engineering Quality Checklist

- Single token set + shared `_card_shell` / control helpers — no per-card bespoke styling.
- Curio accents reused for tints/tones — no new brand colours introduced.
- Selection/status states derive from existing flags — no new state.
- PNG/SVG parity preserved (shared drawing API); workbook rebuilt after PNG regen.
- Consistent with settled decisions: suggested-prompt actions, no card buttons, no preview
  links beside suggestions.
