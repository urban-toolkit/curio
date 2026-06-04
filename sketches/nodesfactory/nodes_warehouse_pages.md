# Nodes warehouse & canvas — UI base and mock-up plan

Visual reference for **mock-up planning** (Figma etc.). Implementation tokens (exact hex, type scale) should be added **after** design sign-off, in the style of [`../auth/auth_pages.md`](../auth/auth_pages.md).

---

## 1. Existing base screens (from screenshots)

These were vectorized from `base/` using [`../extract_single_svg.py`](../extract_single_svg.py).

| Kind | Location | Notes |
|------|----------|--------|
| **Default (clean)** | [`svg_single/Screenshot_*.svg`](svg_single/) | Regenerated with `--min-area 24 --simplify 0.002 --color-k 32` — far fewer groups, lighter paths (Figma-friendly). |
| **Dense archive** | [`svg_single/legacy_dense_trace/`](svg_single/legacy_dense_trace/) | Earlier auto-trace (many tiny regions); keep for comparison only. |
| **Refined copy** | [`svg_single/refined/`](svg_single/refined/) | Same files as root `svg_single/` (synced). |

Regenerate clean traces:

```bash
cd sketches
.venv/bin/python extract_single_svg.py nodesfactory/base --out nodesfactory/svg_single \
  --min-area 24 --simplify 0.002 --color-k 32
```

(Then move prior heavy exports to `legacy_dense_trace/` if you re-run.)

---

## 2. Composites (screenshot + vector UI)

Pixel-accurate [`preview/`](preview/) PNG **underlay** with **vector overlays** for epic UI. Paths are relative to each SVG file (Figma: keep assets next to SVG or re-link images).

| File | Base | Overlay |
|------|------|---------|
| [`svg_single/composites/canvas_with_nodeshub_drawer.svg`](svg_single/composites/canvas_with_nodeshub_drawer.svg) | Dataflow canvas | **Nodes hub** chip in menu, **BUILT-IN / PACKS** labels on palette, right **warehouse drawer** |
| [`svg_single/composites/projects_with_nodepacks_cta.svg`](svg_single/composites/projects_with_nodepacks_cta.svg) | Projects screen | **Node packs** secondary button |
| [`svg_single/composites/node_editor_pack_affordance.svg`](svg_single/composites/node_editor_pack_affordance.svg) | Node editor | **Browse packs** pill on toolbar row |

---

## 3. Existing base screens (roles)

| # | Role | Source PNG | Clean trace (`svg_single/`) | `viewBox` (px) |
|---|------|------------|-----------------------------|----------------|
| A | Node editor chrome | `base/Screenshot 2026-05-04 at 13.38.41.png` | `Screenshot_2026-05-04_at_13.38.41.svg` | `0 0 1082 760` |
| B | Projects hub | `base/Screenshot 2026-05-06 at 08.24.59.png` | `Screenshot_2026-05-06_at_08.24.59.svg` | `0 0 3354 1840` |
| C | Dataflow canvas | `base/Screenshot 2026-05-06 at 08.25.16.png` | `Screenshot_2026-05-06_at_08.25.16.svg` | `0 0 3356 1474` |

**Preview copies:** [`preview/`](preview/) (same PNGs as `base/`).

---

## 4. Screens to design (not only in base)

| Screen | Purpose | Primary inspiration | Status |
|--------|---------|-------------------|--------|
| **Warehouse (browse)** | Search, category rail, card grid, package detail drawer | SketchUp Extension Warehouse | Mock done — `figma_mockups/01` |
| **Install / permissions** | Pack access + dependency summary | Chrome / VS Code extension prompts | Mock done — `figma_mockups/02` |
| **Palette — sectioned** | Built-in vs packs + **Get packs** | [`ToolsMenu.module.css`](../../utk_curio/frontend/urban-workflows/src/components/menus/nodes/ToolsMenu.module.css) | Mock done — `figma_mockups/03` |
| **Node factory wizard** | Author / publish a pack end-to-end | npm `init`, VS Code extension generator, Framer marketplace upload | Mocks done — `figma_mockups/04..08` |

---

## 5. Mock-up workflow

1. Use **composites** when you need the real Curio screenshot plus new chrome; use **clean traces** when you want editable vectors without photo noise.
2. Open [`figma_mockups/`](figma_mockups/) for pure vector concepts — tokens match app: **Rubik**, `#1E1F23`, `#fbfcf6`, `#FBAA69`, menu bar **65px**, palette `#1E1F23` / `rgba(255,255,255,0.08)` border.
3. Wizard screens share a stepper / footer pattern — duplicate the active mockup as a starting point for new factory steps; keep stable group ids (`Header_App`, `Page_Header`, `Stepper`, `Body`, `Footer`).

---

## 6. Figma-ready concept screens (vectors only)

### Consumer surface

| File | Notes | `viewBox` |
|------|-------|-----------|
| [`figma_mockups/01_warehouse_browse.svg`](figma_mockups/01_warehouse_browse.svg) | Curio menu + warehouse browser + detail drawer | `0 0 1440 900` |
| [`figma_mockups/02_install_permissions.svg`](figma_mockups/02_install_permissions.svg) | Install modal — permissions and dependency summary | `0 0 1440 900` |
| [`figma_mockups/03_palette_sectioned_rail.svg`](figma_mockups/03_palette_sectioned_rail.svg) | Tools palette with **BUILT-IN** + **PACKS** sections | `0 0 1440 900` |
| [`figma_mockups/09_nodes_hub_drawer.svg`](figma_mockups/09_nodes_hub_drawer.svg) | **Nodes hub drawer** — right-side slide-over opened from the menu bar's "Nodes hub" link. Pure-vector equivalent of [`svg_single/composites/canvas_with_nodeshub_drawer.svg`](svg_single/composites/canvas_with_nodeshub_drawer.svg) with full drawer fidelity (top bar, search + sort, Featured/Browse-all/Installed/Updates tabs, 3 featured cards with Install/Installed/Update states, "Your packs" list, shared-env info note tying to epic invariant 7, sideload + warehouse footer). Backdrop shows the dim canvas with the sectioned palette and two node tiles. | `0 0 1440 900` |

### Node factory authoring wizard

Drives [`manifest_spec.md`](../../docs/nodesfactory@docs/manifest_spec.md) field-by-field. Each step shares the menu bar (65px, `#1E1F23`), stepper, and a pinned footer with **Cancel / Back / Next** (or **Export / Publish** in step 5).

| File | Step | What it edits in the manifest |
|------|------|-------------------------------|
| [`figma_mockups/04_factory_step1_metadata.svg`](figma_mockups/04_factory_step1_metadata.svg) | 1 — Metadata | `id`, `version`, `displayName`, `description`, `author`, `license`, `category`, pack icon |
| [`figma_mockups/05_factory_step2_ports.svg`](figma_mockups/05_factory_step2_ports.svg) | 2 — Ports | `nodeKinds[].kindId`, `inputPorts`, `outputPorts`, `category`, `paletteOrder` (multi-kind via left rail) |
| [`figma_mockups/06_factory_step3_template.svg`](figma_mockups/06_factory_step3_template.svg) | 3 — Template &amp; engine | `editor`, `engine`, `hasCode/Widgets/Grammar`, `templateDir` + `defaultTemplate` (multi-preset, packs ship `.py` files inside their own archive), dry-run, descriptor preview |
| [`figma_mockups/07_factory_step4_dependencies.svg`](figma_mockups/07_factory_step4_dependencies.svg) | 4 — Dependencies &amp; permissions | `compatibility.curioRuntime`, `dependencies.{packs,python,js}`, `permissions` |
| [`figma_mockups/08_factory_step5_validate_publish.svg`](figma_mockups/08_factory_step5_validate_publish.svg) | 5 — Validate &amp; publish | Validator checklist, dry-run, lockfile preview, **Export .curio-nodepack** vs **Publish to warehouse** with visibility |

All 9 wizard / consumer mocks (01..03, 04..08, 09) are 1440x900, ASCII-only, and parse as well-formed XML.

---

## 7. Legacy: dense trace only

If a screenshot trace explodes in group count, raise `--min-area` (e.g. 32–48) or `simplify` slightly.
