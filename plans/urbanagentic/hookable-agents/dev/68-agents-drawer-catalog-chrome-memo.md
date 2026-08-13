# dev/68 — Agents drawer: shared catalog chrome (search, sort, avatar rows)

Date: 2026-08-13
Status: implemented 2026-08-13 — COMMIT-77bd7ed8 (single commit per §9).
Verification: frontend `npx jest` full → 788 passed across 5 consecutive runs
(one early-run failure never reproduced — environment flake); `tsc --noEmit`
clean (two pre-existing tsconfig deprecation notices only). BL-P5-20260813-18.
Recorded deviations: (1) the version chip renders via the shared
`versionBadge` class rather than a plain tag, matching DatasetCard; (2) the
row uses `<article>`/`<h3>` like DatasetCard (h3 headings are what the DOM-
order sort tests key on); (3) `PackageSearchRow`'s prop extension grew again
immediately after in dev/74 (typed `sortOptions`) — the two landed as
separate commits.

Approved concept: `png-concepts/01-agents-catalog-drawer.png` / `02-main-dataflow-attached-agents.png`
(the same drawer is shown in both; per the png-concepts README, the text spec is
authoritative where an image differs).

## 1. Problem Statement

The Agents Catalog drawer (`components/agents/catalog/AgentsCatalogDrawer.tsx`)
diverges from the approved concept and from the two sibling catalog drawers
(Data Catalog, Node Catalog) in three user-visible ways:

1. **No search bar.** The concept shows a search input ("Search agents, hooks,
   keywords…") directly under the subtitle. Datasets and Nodes both render the
   shared `PackageSearchRow`; Agents renders nothing, so a long roster can only
   be scanned manually.
2. **No sort control.** The concept shows a "Sort: New ⌄" select to the right of
   the search input (the established `PackageSearchRow` pattern). Agents renders
   cards in raw API order with no user control.
3. **Row structure doesn't match the other catalogs.** Concept rows lead with a
   left-aligned, category-tinted agent avatar and a colored left accent bar —
   the exact grid `PackageCard.module.css` provides (`accent | avatar | body |
   action`) and that `DatasetCard` already reuses. The agent row has **no**
   leading avatar at all, and its action column is `align-items: flex-end`, so
   buttons render ragged-right instead of the uniform stretched column the
   other drawers use.

Also, the drawer's vertical hierarchy is `header → tabs → subtitle → list`,
while the concept (and the sibling drawers) put the scope subtitle and
search/sort row **above** the tabs: `header → subtitle → search/sort → tabs →
list → footer`.

Why it matters: the three catalog drawers are meant to read as one family
(consistency), agents are currently un-searchable/un-sortable (usability), and
the Agents drawer duplicates button/tag CSS the shared modules already provide
(maintainability).

## 2. Scope

**In scope**

- `components/agents/catalog/AgentsCatalogDrawer.tsx` — add `PackageSearchRow`,
  reorder subtitle/tabs, restructure `AgentRow` onto the shared card grid with
  a leading avatar, switch buttons/tags to the shared `PackageCard` classes.
- `components/agents/catalog/AgentsCatalogDrawer.module.css` — remove the now
  dead local card/button/tag styles; add light-surface agent category tint
  classes (avatar + accent) keyed by `agentCategoryKey`.
- `components/packages/publishing/PackageSearchRow.tsx` — additive optional
  props (`placeholder`, `sortAriaLabel`) so the shared bar can carry
  agent-flavored strings; defaults preserve current Datasets/Nodes copy.
- **New** `components/agents/catalog/agentListUtils.ts` — `matchesAgentSearch`
  + `sortAgentCards` (client-side, mirroring `packageUtils`).
- Tests: `src/tests/catalog/AgentsCatalogDrawer.test.tsx` (extend), **new**
  `src/tests/catalog/agentListUtils.test.ts`.

**Out of scope (intentionally unchanged)**

- The concept's category filter chips (All / Data / Node / …) — no sibling
  drawer has a chip row; adding one is a new feature, not chrome alignment.
- Drawer data lifecycle (`useAgentsCatalogDrawer` scope cache, race guard,
  refresh-all) — untouched; filtering/sorting is presentation-side.
- Panel width (560px vs the siblings' 520px), skeleton loaders, tab count
  badges, drag-from-drawer — real deltas, but not part of this request.
- Header (DEC-042 pin-only), footer Import package button, all per-scope
  actions and modals — behavior preserved exactly.
- Datasets/Nodes drawers — must render byte-identical UI after the
  `PackageSearchRow` prop addition (defaults match today's strings).
- The known Datasets sort-value mismatch (`"recent"` state vs `"new"` option in
  `PackageSearchRow`) is pre-existing and stays out of this change.

## 3. Recommended Implementation Approach

Reuse the existing shared pieces; add no Agents-specific variants.

1. **Search + sort bar**: render `PackageSearchRow` between the subtitle and
   the scope tabs, exactly where Datasets/Nodes place it relative to their
   header block. Extend `PackageSearchRowProps` with optional
   `placeholder?: string` (default `"Search packages, authors, keywords..."`)
   and `sortAriaLabel?: string` (default `"Sort packages"`). Agents passes
   `placeholder="Search agents, hooks, keywords..."`,
   `sortAriaLabel="Sort agents"`. Sort options stay the shared
   `SortMode = "new" | "name"` pair — no new sort vocabulary.
2. **State**: local `useState` for `search` (`""`) and `sort` (`"new"`) inside
   `AgentsCatalogDrawer`, following `NodeCatalogDrawer` (client-side filtering
   over an already-fetched list; no debounce needed — Datasets debounces only
   because its search round-trips to the server). State persists across scope
   tab switches, matching the sibling drawers.
3. **Filter/sort utils** (`agentListUtils.ts`): `matchesAgentSearch(card, q)`
   matches case-insensitively over `name`, `id`, `purpose`, `category`,
   `capabilities`, `hooks`, and `provenance.publisher` (the concept placeholder
   promises "agents, hooks, keywords"). `sortAgentCards(cards, mode)`:
   `"name"` → `localeCompare` with `sensitivity: "base"` (same comparator as
   `sortPackages`); `"new"` → the server-provided roster order unchanged,
   because `AgentCard` carries no creation timestamp — the API list order is
   the source of truth for recency (documented in the util). Both return
   copies; visible rows are `useMemo(sortAgentCards(cards.filter(...), sort))`.
4. **Row structure**: import `PackageCard.module.css` into the agents drawer
   (the exact pattern `DatasetCard.tsx` uses) and rebuild `AgentRow` on it:
   `card` grid → absolute `cardAccent` + category tint, left-aligned
   `cardAvatar` (`faRobot` glyph) + category tint, `cardBody`
   (`cardTitle`/`cardMeta`/`tagRow`+`tag`), `cardAction` +
   `cardSecondaryActions` for the per-scope buttons using the shared
   `btnInstall`/`btnSecondary`. Category → tint key via the existing
   `agentCategoryKey` (`agentCategoryStyle.ts`). The palette's `avatar_*`
   classes are dark-surface, so the agents module CSS adds light-surface
   equivalents reusing the established hues (data green `#4caf72`, node blue
   `#5b9bd5`, evaluate purple `#9b7fda`, package teal `#26c6da`, canvas orange
   `#f2933f`, neutral default) — the same colors the dataset format
   avatars/accents already use where hues coincide.
5. **Hierarchy**: reorder to `header → subtitle → PackageSearchRow → tabs →
   error/list → Import package footer`, matching the concept and sibling
   drawers. All content and actions inside rows are preserved.
6. **Empty state**: keep "No agents in this scope yet." for a truly empty
   scope; when the scope has cards but the query matches none, show
   "No agents match your search." so filtering is never mistaken for an empty
   catalog.

## 4. Data and State Handling

- **Source of truth**: `useAgentsCatalogDrawer` per-scope card cache
  (unchanged). Search/sort are pure view state layered on top.
- **Derived values**: `visibleCards = useMemo(filter → sort, [cards, search,
  sort])` — no copies stored in state, so refresh-all after install/uninstall
  flows through untouched and the filtered view recomputes automatically.
- **Loading/empty/error**: unchanged semantics; the search-specific empty
  message renders only when `cards.length > 0 && visibleCards.length === 0`.
  The error banner still renders above cached rows.
- **No new races**: filtering is synchronous and client-side; the hook's
  race guard and stale-while-revalidate behavior are untouched. Typing never
  triggers fetches, so there is no flicker or reload.

## 5. UI and UX Requirements

- Search input: shared `PackageSearchRow` styling (magnifier icon, input
  height, focus ring), placeholder "Search agents, hooks, keywords…",
  `type="search"` (native clear affordance), full-width next to the sort
  select.
- Sort select: "Sort: New" / "Sort: Name", identical geometry and chevron to
  the other drawers, `aria-label="Sort agents"`.
- Rows: colored left accent bar + left-aligned 72px category-tinted rounded
  avatar with the `faRobot` glyph (`aria-hidden` — decorative), title, purpose
  line, tag chips (category / hook: X / vN preserved), uniform right-hand
  action column with stretched buttons (shared hover states).
- Typography/spacing/hover come from the shared modules — no bespoke values.
- Accessibility: search row inherits the shared semantics; avatar and accent
  are `aria-hidden`; all existing button names/roles unchanged (DEC-042 header
  untouched); tab order becomes pin → settings → search → sort → tabs → rows.

## 6. Edge Cases

- Empty scope vs. empty search result (distinct messages, §3.6).
- Query matching only whitespace → treated as no filter (trim, like
  `matchesSearch`).
- Cards with empty `purpose` (falls back to capabilities join — preserved),
  unknown/missing `category` → `agentCategoryKey` returns `"default"` →
  neutral tint, never unstyled.
- Duplicate names sort stably by `dirName`? — `"name"` ties keep array order
  (stable sort); `"new"` keeps server order entirely.
- Search persists across scope switches: a filter that matches nothing in the
  next scope shows the search-empty message, not "no agents in this scope".
- Install/uninstall while filtered: refresh-all replaces `cards`; the memo
  recomputes and the row stays or leaves per its new scope truth — busy state
  (`busyCoord`) unaffected.
- Rapid typing: pure client filter, no debounce/fetch → no dropped or
  out-of-order paints.

## 7. Testing Strategy

- **Unit — new `agentListUtils.test.ts`**: matches on name / id / purpose /
  capability / hook / publisher; case-insensitive; trims; empty query passes
  all; `"name"` sorts case-insensitively; `"new"` preserves input order;
  both return new arrays.
- **Component — extend `AgentsCatalogDrawer.test.tsx`**:
  - typing filters rows; clearing restores all rows;
  - no-match query shows "No agents match your search." (scope not empty);
  - sort=Name reorders rows alphabetically (assert DOM order);
  - search input value survives a scope tab switch;
  - each row renders the left avatar with the robot glyph;
  - regression: existing suite (scopes, actions, DEC-042 header, dev/47
    transitions) must pass unmodified — the changes are purely additive to
    assertions.
- **Datasets/Nodes regression**: their existing suites cover
  `PackageSearchRow` rendering; the new props are optional with today's
  strings as defaults, so no updates should be needed (verify by running the
  catalog test suites).

## 8. Acceptance Criteria

1. The Agents drawer shows, under the scope subtitle and above the tabs, the
   shared search bar with the magnifier icon and placeholder "Search agents,
   hooks, keywords…", plus the "Sort: New / Sort: Name" select — visually
   identical (spacing, height, border, focus) to the Datasets/Nodes drawers.
2. Typing narrows the visible rows across name, id, purpose, capabilities,
   hooks, category, and publisher; clearing restores the full scope list; a
   no-match query shows "No agents match your search."
3. "Sort: Name" orders rows alphabetically (case-insensitive); "Sort: New"
   shows the roster's server order.
4. Every agent row leads with a left-aligned, category-tinted avatar (robot
   glyph) and a category-colored left accent bar, on the same card grid as the
   other catalogs; action buttons form a uniform right column.
5. All per-scope actions (Install / Uninstall / Import / Publish pill / Delete
   / Project agent settings), the pin-only header, footer Import package, and
   the dev/47 tab-cache behavior work exactly as before.
6. The Datasets and Nodes drawers are visually and behaviorally unchanged.
7. `npx tsc --noEmit` clean; full catalog test suites green.

## 9. Recommended Commit Breakdown

Single focused commit (the pieces are not independently shippable — the
search row without its utils, or the row grid without its tints, would be a
broken intermediate): **"Agents drawer: shared search/sort bar + catalog row
grid with category avatars (dev/68)"** covering the utils + tests,
`PackageSearchRow` optional props, drawer restructure, and CSS cleanup.
(Per this repo's convention the working tree is left unstaged for review.)

## 10. Engineering Quality Checklist

- No duplicated logic: search/sort comparators live in one util; row/button
  CSS comes from `PackageCard.module.css`; dead local styles removed.
- Types: shared `SortMode` reused; utils typed against `AgentCard`.
- State predictable: pure derived view over the untouched cache hook.
- Consistency: one search/sort bar component across all three drawers.
- A11y: labeled sort select, decorative visuals hidden, roles unchanged.
- Tests: unit + component + regression as in §7.
