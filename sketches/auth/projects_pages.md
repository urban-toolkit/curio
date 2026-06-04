# Projects Pages — User Projects Dashboard & File Menu

Visual identity and implementation reference for the project-management surfaces of Curio.

| File | Scope |
| --- | --- |
| `svg_single/user_projects.svg` | In-app workflow editor with the File menu open (dark chrome) and a "YOUR PROJECTS" submenu |
| `svg_single/projects 1.svg` | Standalone projects dashboard page (Figma-exported, inverted top bar variant) |
| `svg_single/projects_1.svg` | Same standalone dashboard with Figma `id="Vector_N"` labels — use as the editable source |
| `svg_single/curio_logo.png` | Dark wordmark for light surfaces |
| `svg_single/curio_logo_white.png` | White wordmark (shared with the auth pages) |

Two distinct surfaces are documented here:

1. **Standalone dashboard** (`projects 1.svg` / `projects_1.svg`) — the Figma-like browse-all-my-projects page.
2. **In-app File menu** (`user_projects.svg`) — the dark editor chrome with the File → Saved workflows submenu.

They share the same core palette but flip the chrome treatment (light dashboard chrome + dark in-app chrome).

---

## 1. Canvas & Layout

### Standalone dashboard

| Property | Value |
| --- | --- |
| `viewBox` | `0 0 3356 1324` |
| Page background | `#F6F6F8` |
| Top bar | Full-bleed strip, `y=0` to `y=128.613`, fill `#0F0F11` |
| Hairline under top bar | `y=128.613`, `stroke="#2A2A2E"`, `stroke-width="2.00958"` |
| Content gutter | Left/right padding ≈ `120px` |
| Card grid | 4 columns × 1 row, card `height≈623px`, `radius≈20px` |

### In-app editor (File menu overlay)

| Property | Value |
| --- | --- |
| `viewBox` | `0 0 3356 1324` (matches the editor screenshot) |
| Canvas background | `#141417` (editor dark) |
| Dropdown fill | `#1E1F23` |
| Dropdown stroke | `#2F3036` (1px hairline) |
| Active row highlight | `#2B2C31` (used on "Saved workflows") |
| Dropdown radius | `10px` |

Both SVGs use the same `3356×1324` viewBox so they can be placed side-by-side in Figma at identical scale.

---

## 2. Color Palette

The palette is a neutral dark/light spine with four accent hues reserved for project thumbnails.

### Neutrals — dashboard chrome

| Token | Hex | Role |
| --- | --- | --- |
| `--ink-900` | `#0F0F11` | Top bar background, primary button, primary text |
| `--ink-800` | `#1C1C1F` | Search pill fill on the dark top bar |
| `--ink-700` | `#2A2A2E` | Hairline under top bar, search pill stroke |
| `--ink-600` | `#434548` | Secondary copy ("4 workflows · Last edited 2 hours ago") |
| `--ink-500` | `#747474` | Tertiary labels |
| `--ink-400` | `#8E929B` | Placeholder text, footer meta, icon strokes on dark |
| `--line-100` | `#E5E5E7` | Card/button borders and separators on light bg |
| `--surface-100` | `#F0F0F2` | Soft surface (filter pill, toggle segment) |
| `--surface-50` | `#F6F6F8` | Page background |
| `--surface-0` | `#FFFFFF` / `white` | Cards, top-bar text/icons, avatar disc |

### Neutrals — in-app editor chrome

| Token | Hex | Role |
| --- | --- | --- |
| `--editor-bg` | `#141417` | Editor canvas background |
| `--editor-panel` | `#1E1F23` (`#1e1f23`) | Dropdown, submenu panels |
| `--editor-hover` | `#2B2C31` | Active / hovered menu row |
| `--editor-line` | `#2F3036` | 1px panel outline |
| `--editor-muted` | `#8E929B` (`#8e929b`) | Section headers ("YOUR PROJECTS"), secondary text |
| `--editor-text` | `#FFFFFF` (`#ffffff` / `#fefefe`) | Primary menu labels, icons |

> The user_projects SVG contains a ladder of near-whites (`#fafafa` → `#fefefe`) inherited from the raster vectorization. Treat them all as `#FFFFFF` when porting to code.

### Accent thumbnails (project cards)

Each card thumbnail uses a pastel tint for the background plus a saturated line color for the abstract motif.

| Card | Tint (fill) | Line / shape (stroke & fill) |
| --- | --- | --- |
| Chicago heat islands | `#FFE3DA` (peach) | `#E86A3C` (burnt orange) |
| NYC mobility study | `#DCE8FF` (sky) | `#3567C7` (royal blue) |
| Milan sidewalk accessibility | `#DFF2E1` (mint) | `#2F8F4A` (forest green) |
| Bay Area bird migration | `#EADCFB` (lilac) | `#7A4BD1` (violet) |

Use the tint as the card thumbnail background and the saturated hex as the foreground stroke/fill for the generative graphic. Each pair has ≥ 3.5:1 contrast against its paired tint — enough to read as a graphic element without overwhelming the card.

---

## 3. Typography

### Font stack

Same as the auth pages — inherited system stack set at the root of each SVG:

```
-apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif
```

### Dashboard type scale

Sizes are expressed at the native `3356×1324` scale; divide by `2.01` for the pre-scale `1670×660` equivalents.

| Role | Size | Weight | Color |
| --- | --- | --- | --- |
| Curio wordmark (top bar) | auto (logo path) | — | `white` |
| Search placeholder | `~26` | `400` | `#8E929B` |
| User display name | `~24` | `600` | `white` |
| User email | `~20` | `400` | `#8E929B` |
| Page title ("Projects") | `~72` | `700` | `#0F0F11` |
| Page subtitle | `~22` | `400` | `#434548` (separator "·" the same color) |
| "New workflow" button label | `~26` | `600` | `white` on `#0F0F11` |
| Filter tabs | `~22` | `500` / `700` active | `#434548` / `#0F0F11` |
| Tab underline (active) | `4px` | — | `#0F0F11` |
| View toggle | `~22` | — | `#0F0F11` active icon, `#8E929B` inactive |
| Card title | `~30` | `600` | `#0F0F11` |
| Card subtitle | `~22` | `400` | `#434548` |
| Card meta (edited / owner) | `~20` | `400` | `#8E929B` (bullet `·` same color) |
| Footer ("Showing 4 of 4") | `~22` | `400` | `#8E929B` |

### File menu type scale (in-editor)

| Role | Size | Weight | Color |
| --- | --- | --- | --- |
| Menu item label | `28` | `400` | `#FFFFFF` |
| Submenu header ("YOUR PROJECTS") | `22` | `600` | `#8E929B`, `letter-spacing="2"`, uppercase |
| Project name (submenu row) | — | — | `#FFFFFF` |
| Project timestamp | — | — | `#8E929B` |
| "View all projects" footer | `20` | `600` | `#8E929B` |

---

## 4. Component Catalog

### Top bar (standalone dashboard)

Full-bleed dark strip, `128.613px` tall, separated from the page with a `#2A2A2E` hairline.

- **Brand** — white `Curio` wordmark on `#0F0F11`, left-aligned inside the gutter.
- **Search pill** — `x=1165.56..2190.44`, `rx=12`, fill `#1C1C1F`, stroke `#2A2A2E`, magnifier icon stroke `#8E929B`, placeholder "Search projects, datasets, and workflows..." in `#8E929B`.
- **User block** (right cluster):
  - Name `white`, email `#8E929B`
  - Avatar disc: `44px` radius, fill `white`, initials "KL" in `#0F0F11`
  - Chevron: three-segment stroke path, stroke `white`, `stroke-linecap="round"`

### Page header

- `h1` "Projects" in `#0F0F11`, `font-weight=700`
- Subtitle combines workflow count + last-edited in `#434548` joined with a middle dot (`·`)
- **New workflow CTA** — pill button, radius `~38px`, fill `#0F0F11`, `+` icon stroke `white` (`stroke-width≈4`), label `white` `600`.

### Toolbar

- **Tabs** (All / Recent / Shared with me / Archived): text in `#434548`, active tab bumped to `#0F0F11` with a `4px` underline.
- **Sort dropdown** — "Sorted by Last edited" in `#434548` with a chevron stroke `#0F0F11`.
- **View toggle** — two-segment control, rounded `rx≈12`, container fill `white` with `#E5E5E7` stroke; the active segment (grid) has a `#F0F0F2` fill; icons stroke `#0F0F11` (active) / `#8E929B` (inactive).

### Project card

- Shell: `rx≈20px`, fill `white`, stroke `#E5E5E7`, `stroke-width≈2`.
- Thumbnail: upper ~70% of the card, filled with the card's pastel tint (see §2), with abstract motif in the paired saturated hex.
- Body:
  - Title — `#0F0F11`, `600`
  - Subtitle — `#434548`, `400`
  - Meta row (bottom, separated from body with a hairline) — edited timestamp + owner/visibility joined with `·` in `#8E929B`.

### File menu (in-editor overlay)

| Part | Geometry | Fill/Stroke |
| --- | --- | --- |
| `FileMenu_DropdownBg` | `x=184, y=120, w=430, h=340, rx=10` | `#1E1F23` / `#2F3036` |
| Row hit area | `w=430, h=82` each | `transparent` (hover) / `#2B2C31` (active row) |
| Row icon | `transform="translate(row,col)"`, stroke `#FFFFFF`, `stroke-width=3`, rounded caps | — |
| Row label | `font-size=28`, `fill="#FFFFFF"` | — |
| Chevron (on "Saved workflows") | stroke `#FFFFFF`, `stroke-width=3` | — |

**Menu order** (top to bottom):

1. `FileMenu_Item_NewWorkflow` — `data-action="new-workflow"`
2. `FileMenu_Item_SavedWorkflows` — `data-action="open-saved-workflows"`, opens the right-hand submenu, shown in its active (`#2B2C31`) state.
3. `FileMenu_Item_ImportSpec` — `data-action="import-specification"` (renamed from "Load specification")
4. `FileMenu_Item_SaveSpec` — `data-action="save-specification"`

### Saved-workflows submenu

| Part | Geometry | Fill/Stroke |
| --- | --- | --- |
| `FileMenu_Submenu_Bg` | `x=626, y=202, w=520, h=334, rx=10` | `#1E1F23` / `#2F3036` |
| Header "YOUR PROJECTS" | `font-size=22`, `font-weight=600`, `letter-spacing=2`, uppercase | `#8E929B` |
| Project rows | 4 rows, each carries `data-project-id` | icons `#FFFFFF`, names `#FFFFFF`, timestamps `#8E929B` |
| "View all projects" | footer text, centered | `#8E929B`, `600` |

The submenu is deliberately anchored to the right edge of the "Saved workflows" row (`x=626` ≈ dropdown right edge + 12px gutter) so hover + mouse traversal into it is unobstructed.

---

## 5. Data-attribute Contract

The SVGs carry semantic `data-*` attributes so the mockup can be wired to real handlers without re-authoring the markup:

| Attribute | Values | Purpose |
| --- | --- | --- |
| `data-action` | `new-workflow`, `open-saved-workflows`, `import-specification`, `save-specification` | Dispatch targets for each menu row |
| `data-project-id` | integer (`1`..`N`) | Identifies which saved workflow the submenu row points to |
| `data-role` | `saved-workflows-submenu` | Marks the submenu panel for show/hide wiring |

Consumers (e.g. the React File menu) should key off these rather than the cosmetic `id=""` values, which may be renamed during redesigns.

---

## 6. Reusable Tokens (suggested names)

```css
/* chrome (dashboard) */
--color-surface-50:   #F6F6F8;  /* page bg */
--color-surface-0:    #FFFFFF;  /* card */
--color-surface-100:  #F0F0F2;  /* soft surface */
--color-line-100:     #E5E5E7;  /* card border */
--color-ink-900:      #0F0F11;  /* top bar, h1, primary btn */
--color-ink-800:      #1C1C1F;  /* search pill on dark */
--color-ink-700:      #2A2A2E;  /* hairline on dark */
--color-ink-600:      #434548;  /* body copy */
--color-ink-500:      #747474;  /* tertiary */
--color-ink-400:      #8E929B;  /* meta + placeholder */

/* chrome (editor) */
--color-editor-bg:    #141417;
--color-editor-panel: #1E1F23;
--color-editor-hover: #2B2C31;
--color-editor-line:  #2F3036;

/* accents (project thumbnails) */
--accent-peach-tint:    #FFE3DA;  --accent-peach:    #E86A3C;
--accent-sky-tint:      #DCE8FF;  --accent-sky:      #3567C7;
--accent-mint-tint:     #DFF2E1;  --accent-mint:     #2F8F4A;
--accent-lilac-tint:    #EADCFB;  --accent-lilac:    #7A4BD1;

/* radii */
--radius-card:   20px;
--radius-pill:   38px;
--radius-button: 12px;
--radius-menu:   10px;
```

---

## 7. Accessibility Notes

- Page title `#0F0F11` on `#F6F6F8` = **17.5:1** (AAA).
- Subtitle `#434548` on `#F6F6F8` = **8.5:1** (AAA).
- Meta `#8E929B` on `#FFFFFF` = **3.0:1** — passes for large/meta text only; do not use for body copy.
- Top bar text `white` on `#0F0F11` = **19.7:1** (AAA).
- Search placeholder `#8E929B` on `#1C1C1F` = **5.5:1** — fine for placeholders.
- Menu label `#FFFFFF` on `#1E1F23` = **15.9:1** (AAA).
- Active menu row `#FFFFFF` on `#2B2C31` = **12.2:1** (AAA).
- All colored thumbnail fills sit behind **decorative** motifs, not text — their contrast ratios do not gate compliance.

---

## 8. File Relationships

```
user_projects.svg          projects_1.svg  (edit here)
    │                             │
    │ (same 3356×1324 viewBox)    │ (copied, re-exported)
    ▼                             ▼
editor chrome with         projects 1.svg (Figma export
File menu overlay          with inverted top bar applied)
```

When touching shared primitives (logo, top bar height, type scale), update both families. Card thumbnails are unique to the dashboard.
