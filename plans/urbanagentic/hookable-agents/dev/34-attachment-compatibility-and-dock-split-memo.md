# Implementation Memo: Attachment Compatibility Enforcement + Canvas/Node Dock Split

Date: 2026-07-21 (retroactive record, filed 2026-07-27 — this slice ran in a parallel session from conversational direction; the durable evidence until now was build-log entry `BL-P4-20260721-10`)
Status: **implemented** (commits `1abbd3c`, `f34b269`, `108dd7c`, `737d82f`)

## 1. Problem Statement

Four gaps after the first dock/chat shipped:

- **Attach accepted incompatible targets**: nothing enforced the manifest's `compatibleTargets`, so a canvas-only agent could be attached to a node (and vice versa).
- **Built-in metadata was frozen at install**: a materialized store copy shadowed the roster, so evolving a built-in's metadata (e.g. widening its targets) never reached users who had installed earlier.
- **All attachments rendered in one bottom dock**, off-concept: the approved dock model glues node agents to their node and clusters canvas agents in a top bar.
- **Drop targeting was unreliable**: browsers rejected the agent drag without `dropEffect=copy`, and DOM-`closest` hit-testing was brittle over React Flow internals.

## 2. Decisions

1. **Enforce compatibility server-side**: `attach_agent` rejects a target kind absent from the agent's `compatibleTargets` (canvas-only → canvas, node-only → nodes, dual → either); `attachments.attach` still validates target existence.
2. **Dual-target built-ins**: `BuiltinAgentSpec` gains a multi-kind `targets` field; **Chat and Debug are dual (node + canvas)**, emitting two `compatibleTargets` each.
3. **Roster-first metadata for built-ins**: `_resolve_definition` prefers the built-in roster for built-in coordinates (owned/imported store definitions still shadow), so evolved built-in metadata takes effect over a stale materialized copy — while runtime prompt bytes stay store-first.
4. **Dock split per the concept**: node agents render as `NodeAgentBadges` avatar chips glued to their node (inside `UniversalNode`); canvas agents cluster in the top `AgentDock` bar; one shared `AgentAvatarBadge` (category-tinted chip, click = chat, hover = detach) keeps both identical, fed by a single `AgentAttachmentsProvider` source. A macOS-Dock-style hover tooltip (name label below the chip, aria-hidden with the button keeping its aria-label) replaces the duplicating native `title`; the selected agent gets the app's blue focus border.
5. **Reliable DnD**: `dropEffect=copy` on agent drags plus coordinate hit-testing (`pickNodeAtPoint`) instead of DOM `closest`.
6. **Palette compatibility pills**: one pill per compatible target (Canvas/Node/Connection), so dual agents advertise both.

## 3. Verification

Backend compatibility matrix + Chat/Debug dual + stale-materialization refresh tests in `test_routes.py`; frontend `NodeAgentBadges`, `AgentAvatarBadge`, `AgentPaletteRow` suites plus updated dock/drop-target suites — all green at each commit with `tsc` clean.

## 4. Traceability

- `BL-P4-20260721-10` (incl. the `737d82f` focus-border amendment); concept sources `docs/00-attached-agent-dock-memo.md` + `docs/03-ui-decisions.md`; `REQ-ATTACH-003`, `REQ-DOCK`, `REQ-A11Y`.
- The shared badge and provider introduced here are the surfaces later extended by `dev/21` (`DEC-042` headers), `dev/25` (conversation titles on the tooltip/labels), and the chat memos.
