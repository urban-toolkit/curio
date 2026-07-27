# Implementation Memo: AGENTS Palette Restyle + Shared Palette Shell

Date: 2026-07-20 (retroactive record, filed 2026-07-27 — specified conversationally against the approved palette concept; the durable evidence until now was build-log entry `BL-P3-20260720-07`)
Status: **implemented** (commits `c80d217` → `923bacf`)

## 1. Problem Statement

The first AGENTS palette shipped functional but off-concept, and its dropdown was click-through to the canvas (clicks fell through to React Flow). Separately, the three tools-panel palettes (Agents, Datasets, Packages) each carried their own copy of the dark dropdown chrome — three diverging stylesheets for what the concept treats as one visual system.

## 2. Decision

1. Restyle the AGENTS palette to the approved concept (`png-concepts/11-agents-palette.png`): category-tinted rows via a shared **category color map** (canvas=orange, data=green, node=blue, evaluate=purple, package=teal) and a presentational `AgentPaletteRow`.
2. Extract the shared dropdown chrome into **`menus/nodes/paletteShell/`** (`paletteShell.module.css`) and migrate all three palettes onto it, so palette chrome changes land once.

## 3. As-Built Implementation

- `COMMIT-c80d217`: click-through fix (the realized `RISK-UX-001`).
- `COMMIT-b233517`: category color map + `AgentPaletteRow`.
- `COMMIT-bbd2cb5`: AGENTS palette restyled to the concept.
- `COMMIT-b8c2a23`: `paletteShell` extraction; Agents + Datasets migrated.
- `COMMIT-923bacf`: Packages palette migrated.

The category color map became the single tint source later reused by the avatar badges, the chat header bot, and the palette compatibility pills — one palette-to-chat color system.

## 4. Verification

`AgentPaletteRow.test.tsx` + updated `AgentsPaletteDropdown.test.tsx`; the datasets/packages palette suites re-ran green after each shell migration; `tsc` clean; visual check against the approved concept at each commit.

## 5. Traceability

- `BL-P3-20260720-07`; concept sources `docs/03-ui-decisions.md` + `png-concepts/11`; rows stay action-free per `docs/02` (actions live on the drawer cards).
