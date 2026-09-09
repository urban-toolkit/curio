# Design Memo: Agent-View and Roster-Drawer Header Split

Date: 2026-07-21
Status: **implemented** (2026-07-21 — concepts regenerated same day; code in `BL-P4-20260721-14`, commit `39760ab`)
Decision recorded: **`DEC-042`**
Amends: the drawer-anatomy header in `docs/08-unified-agent-chat.md` (formerly one static `📌 🤖 Agents Catalog ✕` top bar above a separate agent identity row)

## 1. Problem Statement

The approved chat-drawer concept stacked two header rows in the opened agent view: a static dark top bar (`📌 🤖 Agents Catalog ✕`, identical to the Data/Nodes Catalog bars) and, below it, the agent identity row (`‹ 🤖 <Agent name> <idx>/<total> ›`, session chip, `Attached to <target>`). The product decision is to merge these in the opened agent view — the identity belongs in the top header itself — and to reserve the static catalog-style bar exclusively for the Agents Roster drawer.

## 2. Decision — `DEC-042`

**Opened agent view (the attachment chat):** one top header only, carrying:
- the agent-cycling arrows `‹ ›` with the master agent icon + name and `<idx>/<total>` (walks all attached agents in the dataflow, unchanged behavior);
- the identification details (session chip / `target · agent · project` label, `Attached to <target>` line);
- the **Close** control (`✕`) — preserved in this header; closing dismisses the agent view and never detaches the agent.
- **No Pin button** in the opened agent view.
- The static `Agents Catalog` title bar does **not** appear in the opened agent view.

**Agents Roster drawer (the three-scope Agents Catalog drawer):** the static dark header (`🤖 Agents Catalog` styling from the former shared bar) is used **exclusively here**, and of the former bar's controls it keeps the **Pin button only** — no Close button, no master-agent identity, no agent-cycling controls. Controls separately required by approved concepts are unaffected — specifically the labeled `Agent settings` cog (account policy entry, memo `11` / `docs/02` §cog entry points) remains valid in this header.

**Unchanged:** everything below each header — the labeled `Attachment settings` cog, initial intent, transcript, chat cards, suggested prompts, input, review-before-apply, dock/badges/palette, and all other approved agent UI decisions (including `DEC-041`).

## 3. Affected Artifacts

- `docs/08-unified-agent-chat.md` — drawer anatomy + "Header navigation" updated (canonical spec).
- `docs/03-ui-decisions.md` — drawer-header bullet updated (identity/cycling/Close in the top header; no Pin).
- `docs/05-png-concepts.md` — generated screens showing the old two-row chrome (`03`, `06`, `07`, `08`, `10`) or the roster drawer with a `✕` (`01`, `02`, `18`, `21`). **Regenerated 2026-07-21**: the renderer (`sources/render_hookable_agents_png_concepts.py` — `draw_panel_frame` pin-only, new `_chat_header`) and the workbook builder callouts were updated, and all PNG/SVG concepts + `Agentic-Functionality-Workbook.xlsx`/`workbook-assets/` re-rendered.
- `kggraph/Stage-2-Design-Phase/2.1-…Design-Traceability.md` — `DEC-042` registered.
- No `dev/19`/`BL-P4` amendment yet: this is a design-phase change; the implementation task will be logged when scheduled.

## 4. Acceptance Criteria (for the later implementation task)

- [ ] The opened agent view has exactly one header: cycling arrows + agent identity + session details + Close; no Pin; no `Agents Catalog` title.
- [ ] The roster drawer header shows the Pin (and the separately approved `Agent settings` cog) — no Close, no agent identity, no cycling controls.
- [ ] All content and interactions below both headers are byte-for-byte the approved behavior.
- [ ] Concept regenerations reflect the split before being cited as visual evidence.
