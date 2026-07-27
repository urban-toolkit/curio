# Implementation Memo: Attached-Agent macOS-Style Dock

> **Attachment/share amendment (2026-07-17).** Each dock tile represents a private configured
> derivation of a project-installed template. It has no SemVer/Publish/Share lifecycle and is
> not exposed in shared flow/Trill results. See
> `../dev/12-agent-template-installation-attachment-sharing-lifecycle-memo.md`.

## 1. Problem Statement

Attached agents were shown as label pills ("tabs") beneath nodes and as a labeled canvas
bar. The request was to **make the dock items a compact square layout showing only the
agent's bot-head icon, with the name in a hover tooltip, following the macOS Dock
interaction pattern** (sizing, spacing, magnification), while staying consistent with the
app's visual style. Two follow-ups: **remove the background shelf so the tiles float**
(as before) and **align the node docks to the node's left edge** (the canvas dock stays
right-aligned).

## 2. Scope

Included: `draw_agent_dock` (new), `draw_nodes` (per-node docks), `draw_dock` (canvas
dock) in the renderer; scenes `02`, `03`, `06`, `10`; docs `02`, `03`, `04`, `08`; the
workbook callouts for the dock scenes.

Out of scope: node/drawer rendering; agent behavior.

## 3. Recommended Implementation Approach

- Replace the pill-based `draw_agent_tab` with `draw_agent_dock`: compact square,
  icon-only tiles (bot-head tinted by agent type). Hovering **magnifies** the tile with
  neighbour falloff (resting ~40px, magnified ~66px), shows the agent **name in a tooltip**
  above it (dark bubble + caret), and a small **running dot** marks active/background
  agents.
- Node docks sit beneath their node; the canvas dock carries whole-dataflow agents near
  the top.
- **Floating (no shelf):** tiles float individually, each with its own soft shadow — no
  background container — matching the earlier tab behavior.
- **Alignment:** node-agent docks are **left-aligned** to the node's left edge; the canvas
  dock is right-aligned (its right edge matches the prior canvas bar).
- The connector from an open agent's dock tile to the chat drawer is preserved.

## 4. Data and State Handling

Static concept. Each tile carries agent type (icon color/name) and a running/active flag
(dot). Status can extend to idle / configured / running / needs-review / error.

## 5. UI and UX Requirements

macOS-Dock feel: consistent square tiles, small gaps, bottom/centre-aligned growth,
tooltip label on hover, running indicator. On-brand: rounded-square tiles with accent-soft
fill and the bot icon; soft shadows; no shelf.

## 6. Edge Cases

A single-agent node (one floating tile); several agents on one node (magnification
falloff); a magnified tile overlapping the node (spacing tuned to avoid it); background
execution (persistent running dot).

## 7. Testing Strategy

Render scenes `02` (resting + hover), `06` (magnified open tile + connector), and `10`
(orchestrated agents), confirming square icon-only tiles, tooltips, running dots, floating
(no shelf), and left/right alignment. Confirm SVG parity.

## 8. Acceptance Criteria

- Attached agents render as compact square, icon-only tiles; the name appears in a hover
  tooltip (macOS Dock pattern) with magnification + running dots.
- Tiles float with no background shelf.
- Node docks are left-aligned to their node; the canvas dock is right-aligned.

## 9. Recommended Commit Breakdown

1. Add `draw_agent_dock` (magnify, tooltip, running dots); replace `draw_agent_tab`.
2. Wire node docks + canvas dock; re-anchor the chat connector.
3. Remove the shelf (float) and set left-align (nodes) / right-align (canvas).
4. Update docs 02/03/04/08 and workbook callouts; regenerate.

## 10. Engineering Quality Checklist

- Sizing/spacing/animation follow macOS Dock best practices.
- Consistent with the app's card/accent style; labels via tooltip.
- Floating tiles; correct per-context alignment.
- Reuses primitives; regenerates deterministically.
