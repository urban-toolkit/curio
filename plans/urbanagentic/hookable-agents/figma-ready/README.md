# Figma-Ready Handoff

> **Settings frames pending.** The current handoff predates the shared Agent Settings dialog
> and its six dedicated screens. Do not treat this asset set as complete UI evidence for the
> configuration/prompt-governance plan until regenerated from
> `../dev/11-agent-configuration-modals-and-prompt-governance-memo.md`.
> The regenerated handoff must also cover the account Import/project Install split,
> imported-only Publish, private unversioned attachments, and sanitized output-only sharing
> defined in `../dev/12-agent-template-installation-attachment-sharing-lifecycle-memo.md`
> (its former Node Explainer-only explanation model is superseded — the node Explanation tab
> is retained per `DEC-041`, `../dev/18`).
>
> **Header split (`DEC-042`, `../dev/21`) — the SVG twins were re-rendered 2026-07-21** with
> the agent identity/cycling/Close in the opened agent view's single top header (no Pin) and
> the Pin-only static header on the Agents Roster drawer; re-import the updated
> `../svg-concepts/` frames.

The primary Figma-ready assets are the eleven SVGs in `../svg-concepts/`. They are
the vector twins of the PNGs in `../png-concepts/` — generated from the **same**
renderer (`../sources/render_hookable_agents_png_concepts.py`), so layout,
spacing, typography, and component structure match the PNGs exactly.

Recommended import order (one Figma frame / page each):

1. `01-agents-catalog-drawer.svg`
2. `02-main-dataflow-attached-agents.svg`
3. `03-attachment-dataset-finder-to-data-load.svg`
4. `04-attachment-node-explainer-to-node.svg`
5. `05-attachment-dataflow-builder-to-canvas.svg`
6. `06-agent-refinement-sidebar-open.svg`
7. `07-dataset-finder-overview.svg`
8. `08-dataset-review-modal.svg`
9. `09-datasets-created-in-palette.svg`
10. `10-dataflow-builder-orchestration.svg`
11. `11-agents-palette.svg`

Each frame is **1672 × 941**.

## Fonts

- UI text uses **Rubik** (weights 300–700) — Curio's real typeface.
- Node code previews use **Roboto Mono**.

Both are free Google Fonts; enable them in Figma before/at import so text lands
with the intended metrics. Text is emitted as real `<text>` elements, so every
label stays editable after import.

## What's vector vs raster

- **Icons** (top bar, palette, node toolbars, panel) are editable Font Awesome
  `<path>` vectors.
- **Shapes** (cards, pills, bars, ports, buttons) are SVG primitives.
- **Shadows** are real translucent offset rectangles (kept as layers, not
  filters).
- The **Curio bird logo** is embedded as a data-URI PNG (the only raster asset).
- The canvas **dot grid** is an SVG `<pattern>`.

## Tokens

Colors, radii, spacing, geometry, and type are mirrored in `design-tokens.json`
(sourced from the live `styles/curioTokens.css`).

## Regenerating

```bash
python3 ../sources/render_hookable_agents_png_concepts.py        # png + svg
python3 ../sources/render_hookable_agents_png_concepts.py svg    # svg only
```

SVGs are written to `../svg-concepts/`, PNGs to `../png-concepts/`.

> The older hand-authored SVGs in `../vectors/` (Inter font, earlier palette)
> are superseded by `../svg-concepts/`.
