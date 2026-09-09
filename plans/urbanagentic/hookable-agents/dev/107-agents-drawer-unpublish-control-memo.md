# dev/107 — A published agent can never be unpublished from the drawer: the Unpublish control that `BL-P3-20260720-06` promised was never rendered

**Status: IMPLEMENTED (2026-08-26) — on `feat/agentscatalog`: commits `df249e18` (1, backend ownership predicate + 404 + Delete 409), `1870ebba` (2, shared confirm copy), `47a49273` (3, drawer control), `dd1c5d74` (this memo); backlog `BL-P3-20260826-13` landed in `7bf52e8a`. (The three code commits were cherry-picked from `feat/agentcatalog`, where they are `ce73d694` / `36bfe4c2` / `e832c7fd`.) Defaults taken: §6(a) Delete 409; §3 verification FAILED the optimistic wording — other accounts' installs of a published definition resolve prompt bytes from the shared catalog and stop running after unpublish (pinned by `test_another_accounts_install_stops_resolving_after_unpublish`), so the copy says so. Owner live re-test pending.**

Date: 2026-08-26
Branch / tree: `feat/agentcatalog` @ `1388bc9b`. Line numbers pinned to that commit.
Origin: the 2026-08-26 follow-up sweep of `BL-P3-catalog-install-publish.md` — the only follow-up in that file still open after verification (recorded in the `BL-P3-20260720-06` amendment).
Family: dev/12 lifecycle (immutable definition → explicit import → explicit install; publish/unpublish are distinct operations, `REQ-LIFECYCLE-001`) → `BL-P3-20260720-06` imported-only Publish (`DEC-030`, `REQ-PUBLISH-002`; commits `5154302` backend, `e843502` frontend) → dev/36 upload-import (made Publish user-reachable) → dev/47 (all-scope refresh after lifecycle actions) → dev/87/88 (`DEC-057`/`DEC-058` retention: "Publications — owner or operator unpublishes", `docs/RETENTION.md:21,72`).
Sibling precedents this must match: the Nodes drawer's Unpublish (`NodeCatalogDrawer.tsx:291-310` + `PackageCard.tsx:174-183`) and the Datasets drawer's Unpublish (`useDatasetCatalogDrawer.ts:292-295`) — both a **secondary `Unpublish` button beside the `Published` badge, `window.confirm` gate, copy that states installed copies are not removed**.
Design decisions consumed: `DEC-030` (imported-only publish — its inverse is owner-only unpublish), `DEC-057`/`DEC-058` (retention: unpublish is the documented removal path for publications). **No new DEC is proposed** — this completes an existing decision's UI. A backlog entry `BL-P3-20260826-13` is minted at closure.

---

## 1. Problem Statement

**Current behavior.** In the Agents Catalog drawer, My Imports tab, an owned definition that has been published renders `CatalogPublishPill` in its badge state — a static, non-interactive `Published` span (`CatalogPublishPill.tsx:30-38`). There is no control anywhere in the frontend that reverses publication:

- `agentsApi.unpublish` exists (`agentsApi.ts:742-745`, `DELETE /api/agents/publications/<coord>`).
- `useAgentsCatalogDrawer().unpublish` exists (`useAgentsCatalogDrawer.ts:40,151`) and already runs through the shared `run()` wrapper (busy coord, error banner, palette notify, all-scope refresh).
- The backend route and service exist and are tested (`routes.py:113-120`, `services.py:659-664`, `test_routes.py:337`).
- **Nothing calls the hook's `unpublish`.** `grep -rn unpublish src/components/agents` returns only the hook's own type and implementation.

So the lifecycle has a one-way door: once a user publishes to the deployment-shared Global Catalog (`.curio/agents-catalog/`), the only removal path is an operator on the filesystem. `docs/RETENTION.md` documents "owner … unpublishes" as the user's removal path — today that documentation is false for the UI.

**Affected surfaces.** `AgentsCatalogDrawer` → `AgentRow`, My Imports scope only (`AgentsCatalogDrawer.tsx:319-345`). The Global tab lists the same published card (`published: true`) but carries no ownership signal, so it is not a candidate (see §2).

**Expected behavior.** A published, owned card in My Imports shows the `Published` badge **and** an adjacent secondary `Unpublish` button, exactly like the Nodes and Datasets drawers. Clicking it asks for confirmation with truthful copy (the listing disappears from every account's Global Catalog; project installs and attachments keep working because installed prompt bytes are materialized per account — `BL-P4-20260720-05`), then calls `unpublish`, and the card flips back to the `Publish` pill after the all-scope refresh. The Global tab no longer lists it.

**Why it matters.** Correctness (a documented lifecycle operation is unreachable), consistency (the third catalog drawer is the only one without Unpublish), retention (`DEC-057`/`DEC-058` promise a user-driven removal path), and a latent **authorization gap** on the backend surfaced while reading the service (§3 backend note).

**One thing verified as a non-problem.** `unpublish` through `run()` already triggers `refreshAll()`, so the My Imports badge, the Global tab row, and the AGENTS palette all reconcile without new state (dev/47).

## 2. Scope

**Included**
- `src/components/agents/catalog/AgentsCatalogDrawer.tsx` — `AgentRow`, My Imports branch: render an `Unpublish` secondary button when `card.published && card.publishable`; confirm; call `state.unpublish(card.dirName)`.
- `src/components/agents/catalog/useAgentsCatalogDrawer.ts` — **no behavioral change**; the existing `unpublish` is consumed as-is. (Confirm gate lives in the component, matching the Nodes drawer where the confirm is in the drawer callback — not inside `run()`, which is action-agnostic.)
- Shared copy: one exported constant/function for the confirm text so a future Global-tab or settings-screen Unpublish reuses it (suggested home: `src/services/retentionCopy.ts`, which already owns truthful deletion copy — `permanentDeletionNotice()`; add `unpublishListingNotice(kind, title)` or an agents-specific sibling).
- Backend hardening (**required, small**): `services.unpublish_agent` (`services.py:659-664`) authorizes by "the caller has *any* store copy of this coord", not by ownership. `import_agent` (`services.py:371-376`) calls `_materialize_builtin`, and `_resolve_definition` falls back to the published catalog (`services.py:119-127`), so the exact ownership boundary must be checked in code (§3). At minimum the service must require `trust == "imported"` on the caller's store copy — the same predicate `publish_agent` uses (`services.py:645-651`) — so that an account that merely imported someone else's publication cannot delete it.
- `docs/AGENTS.md` route table row for `DELETE /api/agents/publications/<coord>` (state the ownership predicate), `docs/RETENTION.md` (no wording change needed if the UI now matches; verify).
- Tests: drawer component test, hook test (already covers `unpublish` → reload? verify; add if not), backend route test for the non-owner 403.
- Backlog: `BL-P3-20260826-13` entry in `BL-P3-catalog-install-publish.md`; close the open item in the `BL-P3-20260720-06` amendment.

**Out of scope**
- Unpublish from the **Global** tab. `AgentCard` exposes no owner identity (`agentsApi.ts:29-33`: `imported`, `installedInProject`, `published`, `publishable`); the Global list sets `publishable=(trust == "imported")` only when the caller's store copy is imported (`services.py:341-342`), which is exactly the owner-approximation the backend hardening tightens. Rendering Unpublish on Global would need an explicit `ownedByCaller` field — a reasonable follow-up, not this slice. My Imports is owned-by-construction (the Publish pill already lives there for the same reason).
- Any change to `CatalogPublishPill` itself. It is shared by eight surfaces (packages, datasets, hub pages); the Nodes/Datasets drawers deliberately place Unpublish as a **sibling** button, not inside the pill. Follow that.
- Republish/version bump flows, publication audit trail, operator-side unpublish (`docs/RETENTION.md` §72 remains operator procedure).
- The `Delete` (remove import) action's interaction with publication — see §6; documented, not changed.

## 3. Recommended Implementation Approach

**Frontend (component-only wiring; the data layer is already complete).**

In `AgentRow`, My Imports branch (`AgentsCatalogDrawer.tsx:319-345`), after `CatalogPublishPill` and before `Delete`:

```
{card.published && card.publishable ? (
  <button type="button" className={cardStyles.btnSecondary} disabled={busy}
          title="Remove this definition from the Agents Catalog Hub"
          onClick={() => onUnpublish(card)}>Unpublish</button>
) : null}
```

with `onUnpublish` = confirm-then-`state.unpublish(card.dirName)`. Keep the confirm in the component (`window.confirm`, the drawer family's established gate: `NodeCatalogDrawer.tsx:293`, `useDatasetCatalogDrawer.ts:292`, `AgentSettingsModal.tsx:234`, `AgentChatPanel.tsx:386`). Copy, centralized in `retentionCopy.ts`:

> Unpublish **{name}** ({coord}) from the Agents Catalog Hub?
>
> This removes the listing for every account. Projects that already installed it keep working — their installed copy is not removed.

The second sentence is load-bearing and must be true: verify `_resolve_instruction_text` (store-first) and `BL-P4-20260720-05` prompt-byte materialization cover *other accounts'* installs. If a project in another account resolves prompt bytes from the published catalog at run time (i.e., install did not copy bytes into that account's store), the copy must instead say installs *may stop resolving* — or the backend should refuse/warn. **Resolve this in commit 1 by reading `install_in_project`/`_materialize_*` for the published-source path; the memo takes no position it hasn't verified.**

Order of controls in the action column becomes: `[Install|Uninstall] [Published badge] [Unpublish] [Delete]` — badge and its inverse adjacent, matching `PackageCard.tsx:161-193`.

**Backend hardening (`services.unpublish_agent`).** Replace the presence check with the ownership predicate `publish_agent` already uses: caller's store copy exists **and** `provenance.trust == "imported"` **and** coord is in the caller's imports. Return 403 with the existing message otherwise. Add `is_published` precheck → 404 `"not published"` so the UI never gets a false 200 for a stale badge. Both are one-line changes in `services.py:659-664`; the route needs nothing.

**No new abstraction.** Do not add an `onUnpublish` prop to `CatalogPublishPill`; do not add a second `run()` variant; do not introduce a dialog component — `window.confirm` is the family convention and the dialog-provider migration is a separate concern.

## 4. Data and State Handling

- **Source of truth**: `card.published` from the backend list (`publications.is_published(coord)`, `services.py:281,341`). The frontend never optimistically flips it.
- **Derived**: `showUnpublish = scope === "my-imports" && card.published && card.publishable`. `publishable` guards built-ins that were imported (they report `publishable=false`), so no dead button appears next to a built-in's badge — none should have one, but the guard costs nothing.
- **Busy**: `busyCoord === card.dirName` disables Install/Uninstall, Unpublish, and Delete together (existing `busy`). No second busy flag.
- **Success**: `run()` → `notifyAgentsPaletteRefresh()` → `refreshAll()` repaints My Imports (badge → Publish pill), Global (row gone), Installed (unchanged), palette (unchanged — install state is per project). No new state.
- **Error**: `run()` sets the banner (`error` over content, cached rows kept — dev/47). A 403/404 message from the backend surfaces verbatim, as `dev/106`'s 409 does.
- **Cancel**: confirm returns false → no state change, no request, focus stays on the button.
- **Race**: a second click during `busy` is impossible (disabled). Publish immediately after unpublish is serialized by `busyCoord`; the refresh sequence guard (`seqRef`) drops stale list responses.

## 5. UI and UX Requirements

- Button label `Unpublish`; class `cardStyles.btnSecondary` (same as Uninstall/Delete); tooltip `Remove this definition from the Agents Catalog Hub`. Visible only with the `Published` badge; the badge remains (it is the state, the button is the action).
- Placement immediately after the badge in `.cardAction` — no layout shift when it appears/disappears beyond the button's own width (the action column is already a flex row that grows with Delete/Publish).
- Keyboard: native `<button>`, tab-reachable, Enter/Space; confirm dialog is modal by nature. After success, focus stays on the row's action column (the button unmounts; React moves focus to body — acceptable and identical to Delete's behavior today; do not add focus machinery beyond the family's).
- Screen reader: `aria-label` not needed — visible text is the name; add `aria-describedby` only if the row lacks a title association (it has `cardTitle` — leave as is, matching sibling buttons).
- Dark/light: `btnSecondary` is already themed for the drawer's light panel.
- No toast; the badge→pill flip and the banner are the feedback (Publish has none either).

## 6. Edge Cases

- **Published, then import deleted** (`Delete` on My Imports while published): today allowed; the publication survives in the Global Catalog and the owner loses the My Imports row — and therefore, after this memo, loses the Unpublish button too. Options: (a) backend `remove_import` refuses 409 while published ("unpublish first"), mirroring dev/101's uninstall-409-while-in-use; (b) `Delete` copy warns. **Recommend (a)** — it is the same pattern the project already chose twice (dev/101, dev/106) and prevents an orphaned publication. Include in commit 2 with its route test; make `Delete`'s title mention it. If the owner rejects (a), do (b).
- **Stale badge** (another tab/session unpublished): `DELETE` → 404 → banner "not published"; refresh flips the badge. Acceptable.
- **Operator disabled publishing** (`CURIO_ALLOW_FACTORY_CATALOG_PUBLISH=0` gates *packages*; verify whether agents publish has an equivalent gate — `publishable` is the only signal today). If a gate exists, Unpublish follows the same hide-not-disable rule (`docs/CATALOG.md:208`). If none exists for agents, note it and move on.
- **No project open**: Unpublish is account-scoped; must remain enabled with `projectId === null` (unlike Install). Test it.
- **Same coord published by two accounts**: impossible — `publish_from_dir` overwrites by `dir_name` (`publications.py:54-61`). The hardening in §3 stops account B from unpublishing A's entry; it does not stop B from *republishing over* A's if B has an imported copy under the same coord. Out of scope; note as a risk (`RISK-PUBLISH-001`) in the backlog entry.
- **Other accounts' installs after unpublish**: see §3's verification obligation; copy must match reality.
- **Repeated confirm cancel**: no request; `busyCoord` untouched.
- **Slow network**: button shows disabled (`busy`); no spinner needed (Publish pill shows `…`; a secondary button with `disabled` matches Uninstall/Delete).
- **Reopened drawer mid-flight**: `run()` is hook-owned; unmount during the request drops the `setState`s harmlessly (existing behavior for every action).

## 7. Testing Strategy

**Frontend — `src/tests/catalog/AgentsCatalogDrawer.test.tsx`** (extend; `api.unpublish` is already mocked at line 14):
1. Published + publishable My Imports card renders `Published` badge **and** exactly one `Unpublish` button; a `published:true, publishable:false` card renders the badge only.
2. Click → `window.confirm` called with copy containing the card name; on `true`, `api.unpublish` called with `agent.my-custom@1.0.0`, then every list endpoint refetched (all-scope refresh).
3. Confirm `false` → `api.unpublish` not called.
4. `unpublish` rejects (`Error("only the owning account…")`) → banner shows the message; rows still rendered.
5. `projectId={null}` → Unpublish enabled (account-scoped), Install disabled.
6. Global tab shows **no** Unpublish for a `published:true` row.

**Frontend — `src/tests/catalog/useAgentsCatalogDrawer.test.ts`**: mirror the existing "publish calls the endpoint then reloads" case for `unpublish` if absent (check line 86 region).

**Frontend — `src/tests/services/retentionCopy.test.ts`**: the new copy helper's output includes the name and the "installed copy is not removed" sentence (or the verified alternative).

**Backend — `tests/test_agents/test_routes.py`**:
7. Non-owner (imported the published coord, `trust != imported` store copy) → `DELETE` 403; entry still listed.
8. Unpublishing an unpublished coord → 404.
9. If §6(a) adopted: `DELETE /imports/<coord>` while published → 409; after unpublish → 200.

Gate: `npx jest src/tests/catalog src/tests/services/retentionCopy.test.ts` green; `pytest tests/test_agents/test_routes.py tests/test_agents/test_publications.py` green; `tsc --noEmit` clean in touched files.

## 8. Acceptance Criteria

- In My Imports, a published owned agent shows `Published` + `Unpublish`; a built-in never shows `Unpublish`; the Global and Installed tabs never show it.
- Clicking `Unpublish` opens a confirm whose text names the agent and truthfully states the effect on existing installs; cancel does nothing.
- Confirming removes the entry from `.curio/agents-catalog/`, the card flips to the `Publish` pill without a manual refresh, the Global tab no longer lists it, and no other tab blanks or flickers during the refresh.
- A backend error surfaces in the drawer banner verbatim; rows remain.
- `DELETE /api/agents/publications/<coord>` returns 403 unless the caller's store copy is `trust=imported` and in their imports; 404 when not published.
- (If adopted) `DELETE /api/agents/imports/<coord>` returns 409 while the coord is published.
- `docs/AGENTS.md` route table states the ownership predicate; `docs/RETENTION.md` "owner unpublishes" is now true in the UI.
- All tests in §7 pass; no change to `CatalogPublishPill`, `run()`, or the other drawers.

## 9. Recommended Commit Breakdown

1. **Backend ownership + 404 hardening** — `services.unpublish_agent` predicate, route tests 7–8, `docs/AGENTS.md` row. Include the §3 verification of other-account install resolution as a test asserting the run path still resolves prompt bytes after unpublish (or documenting that it doesn't).
2. **(Conditional) `remove_import` 409 while published** — service + route test 9 + `Delete` tooltip. Separate so it can be dropped if the owner prefers §6(b).
3. **Shared confirm copy** — `retentionCopy.ts` helper + unit test.
4. **Drawer Unpublish control** — `AgentRow` button + confirm + tests 1–6.
5. **Docs/backlog** — `BL-P3-20260826-13`, close the `BL-P3-20260720-06` amendment's open item, memo status → IMPLEMENTED with hashes.

## 10. Engineering Quality Checklist

- No duplicated logic: reuses `run()`, `refreshAll`, `btnSecondary`, `retentionCopy`; no pill fork.
- Types: `AgentCard.published/publishable` already typed; no new fields.
- Component stays focused: one conditional button + one callback in `AgentRow`.
- State predictable: no optimistic flip; single `busyCoord`.
- UI consistent: mirrors `PackageCard` action ordering and the family's `window.confirm` gate.
- Loading/empty/error: inherited from dev/47 semantics; verified by tests 2, 4.
- Accessibility: native button, visible label, modal confirm.
- Tests: component, hook (if gap), copy unit, backend route (403/404/409).
- Conventions: memo → commits with pathspec (`git commit -- <paths>`; foreign `plans/` untracked work exists in the tree), no co-author trailer, no auto-push.
- No re-render cost: one extra boolean per row; `AgentRow` re-renders on the same `state` changes it already does.

## Open questions for the owner (non-blocking — defaults stated)

- **§6(a) vs (b)** — default **(a)**, 409 on `Delete` while published (project precedent dev/101/106).
- **Copy's second sentence** — default to the "installed copy is not removed" wording *only if* commit 1's verification confirms other-account installs resolve from their own store; otherwise the alternative wording ships and the backlog notes it.
