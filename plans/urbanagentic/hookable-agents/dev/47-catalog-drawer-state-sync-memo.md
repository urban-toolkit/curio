# Implementation Memo: Agents Catalog Drawer — Tab Transitions + Installation-State Consistency

Date: 2026-07-29
Status: implemented (COMMIT-942e5c31 backend, COMMIT-ab9e92d7 frontend)
Feature slice: rendering transition + state synchronization only; layout and the approved per-scope action patterns are untouched.

## 1. Problem Statement (root causes, confirmed in code)

1. **Tab flicker / content resets**: `useAgentsCatalogDrawer` holds ONE `cards` array for the active scope and `fetchScope` sets `loading: true`, which the drawer renders as `Loading…` **replacing the entire list** — every tab switch and every post-action reload blanks the content and repaints it. The Nodes/Datasets drawers load once and reload in place; the Agents drawer resets visibly on every transition.
2. **Wrong installed state (the Node Content Builder screenshot)**: `services.list_my_imports` **hardcodes `installed_in_project=False`** and its route accepts no `projectId` — so the My Imports tab can never show an installed agent's true state: an imported *and installed* Node Content Builder renders an active **Install** instead of **Uninstall**. The Global scope already resolves this correctly from the project lockfile (`list_global_catalog` marks per-project installs); My Imports simply never consulted the same source of truth.
3. **Cross-tab staleness**: an action refreshes only the active scope's array; other tabs re-fetch from scratch on entry (flash) and can briefly disagree with the tab where the action happened.

The palette is already synchronized (`notifyAgentsPaletteRefresh` fires after every lifecycle action) — verified, no change needed there.

## 2. Scope

**Backend**: `list_my_imports(user_key, project_id=None)` marks `installedInProject` from the **project lockfile** — the same single source of truth the Global scope reads; `GET /api/agents/imports?projectId=` passes it through. Nothing else moves server-side (the lockfile was always the truth; My Imports just never read it).
**Frontend**: the hook becomes a per-scope cache with stale-while-revalidate semantics — `cardsByScope` keeps each tab's last-known rows; switching tabs renders the cache instantly and refreshes in the background; `Loading…` appears only for a scope's *first ever* fetch; errors keep the cached rows (banner over content, not instead of it); a per-scope request sequence guards out-of-order responses from rapid tab switches; lifecycle actions refresh **all** scopes in parallel so every tab agrees immediately. `agentsApi.listImports(projectId?)`.
**Untouched**: drawer layout, `AgentRow`'s per-scope action logic (it already renders Uninstall when `installedInProject` is true — the data was wrong, not the logic), the DEC-042 header, the dev/43 open/close transition, the palette.

## 3. Edge Cases

- Rapid tab switching with slow responses: the sequence guard drops stale responses per scope — a late Global payload can never overwrite fresher Global data, and never bleeds into another tab.
- Action from any tab (e.g. Install on Global): all three scope caches refresh in parallel; the My Imports and Installed tabs are correct the moment they're opened, with no flash (cache renders, refresh lands silently). The `installed` scope refresh is skipped without a project.
- No project open: My Imports omits `projectId` (state renders as before — nothing installed anywhere); Install stays disabled as today.
- First-ever visit to a tab: the one legitimate `Loading…` (nothing cached to preserve).
- Fetch error mid-refresh: cached rows stay; the error banner shows above them.

## 4. Testing

Backend: `list_my_imports` with `projectId` marks an imported+installed built-in `installedInProject: true` (and false when not installed / no project); route passes the query param. Frontend: cached tab switches render instantly with no `Loading…` reset; first visits show it once; an install from Global refreshes all scopes (assert all three endpoints re-hit) and the My Imports card flips to Uninstall (the Node Content Builder regression, by name); error keeps content; out-of-order responses are dropped; existing suites green.

## 5. Acceptance Criteria

- [x] Tab changes never blank or flash previously loaded content; only a scope's first fetch shows `Loading…` (cached-tab-switch + first-visit tests).
- [x] An imported + installed agent (Node Content Builder verified by test) shows **Uninstall** on every tab that lists it; imported/installed/published states come from one source of truth (lockfile / imports registry / publications) on every scope (`TestMyImportsInstalledState`, drawer Uninstall-flip test).
- [x] A lifecycle action updates all tabs and the palette immediately and consistently (all-three-endpoints refresh test; palette already synced via `notifyAgentsPaletteRefresh`).
- [x] Layout, per-scope actions, and drawer chrome unchanged (all pre-existing drawer/row/settings tests pass unmodified).

## 6. Commits

1. `COMMIT-942e5c31` — My Imports reads installed state from the project lockfile (backend + route + 3 tests + this memo).
2. `COMMIT-ab9e92d7` — drawer per-scope cache: stale-while-revalidate tabs, race guard, all-scope refresh after actions (+ 6 tests).

Verification: backend `pytest tests --ignore=tests/test_frontend` → 405 passed (test_agents); frontend `npx jest` full → 617 passed (56 suites); tsc unchanged (pre-existing tsconfig deprecation warnings only).
