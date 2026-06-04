# Pack nodes — editing sketches

This folder contains **vector assets** for the pack palette + canvas editing UX (Phase 1 of the pack-editing plan).

## Baseline (pixel-traced)

| File | Description |
|------|-------------|
| [`preview/01_canvas_pack_palette_baseline.svg`](preview/01_canvas_pack_palette_baseline.svg) | Auto-generated from [`base/Screenshot 2026-05-13 at 14.59.40.png`](base/Screenshot%202026-05-13%20at%2014.59.40.png) via [`../extract_single_svg.py`](../extract_single_svg.py) (`--min-area 24 --simplify 0.002 --color-k 32`). Full-canvas trace for Figma reference. |
| `preview/Screenshot_2026-05-13_at_14.59.40.svg` | Same content, original output filename from the extractor. |

## Figma concept overlays (hand-authored)

Curio tokens: `#1E1F23`, `#FBAA69`, `#fbfcf6`, Rubik fallback stack.

| File | Purpose |
|------|---------|
| [`figma/02_pack_palette_edit_mode_off.svg`](figma/02_pack_palette_edit_mode_off.svg) | Read-only dock layout (concept); detailed baseline is `01_canvas…`. |
| [`figma/03_pack_palette_edit_mode_on.svg`](figma/03_pack_palette_edit_mode_on.svg) | Edit toolbar: **Save draft** / **Cancel** + accent border. |
| [`figma/04_pack_section_selected_highlight.svg`](figma/04_pack_section_selected_highlight.svg) | Selected pack group + dashed **selection sync** to canvas node. |
| [`figma/05_palette_kind_row_with_label.svg`](figma/05_palette_kind_row_with_label.svg) | Kind row: **label**, **category** chip, **PACK** badge. |
| [`figma/06_canvas_node_chrome_pack_meta.svg`](figma/06_canvas_node_chrome_pack_meta.svg) | Node title strip: category pill + **pack coordinate** + template name. |

## Pipeline (rebuild baseline)

```bash
cd sketches
./.venv/bin/python extract_single_svg.py \
  "nodesfactoryediting/base/Screenshot 2026-05-13 at 14.59.40.png" \
  --out nodesfactoryediting/preview --min-area 24 --simplify 0.002 --color-k 32
cp nodesfactoryediting/preview/Screenshot_2026-05-13_at_14.59.40.svg \
   nodesfactoryediting/preview/01_canvas_pack_palette_baseline.svg
```

Validate XML: `python -c "import xml.etree.ElementTree as ET; ET.parse('...')"`

## Stakeholder sign-off (exit gate before shipping UI)

- [ ] Edit / Done toggle placement and **Save draft** / **Cancel** labelling
- [ ] Pack group **selection** ring colour and canvas **sync** affordance
- [ ] **Kind row** density (label + category + badge) on small screens
- [ ] **Node header** hierarchy (category vs pack id vs template name)

Record approver + date in your PR or design wiki.

## Implementation alignment

Behaviour and file pointers: [`../../docs/nodesfactory@docs/frontend.md`](../../docs/nodesfactory@docs/frontend.md).
