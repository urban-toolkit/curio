# Build Log — P3: Catalog, Install & Publish

Child log for Phase 3 (see `../3.1-Agents-Catalog-Build-Log.md`). Entries follow the
Build Entry Template and are append-only.

---

## BL-P3-20260719-01: Backend agents catalog / lifecycle API (Feature 5a)

- Date / author: 2026-07-19 / Karla
- Status: verified
- Requirements: `REQ-CAT-001` (browse the scopes), `REQ-IMPORT-002`, `REQ-PROJECT-INSTALL-001` (explicit import/install), `REQ-STATE-002` (project isolation)
- Design decisions/artifacts: `DEC-029` (explicit separate commands), `DEC-040` (filesystem-backed); `SRC-BLUEPRINT-005`; reuse of `app/packages/routes.py` + `app/packages/services.py`
- Tasks: `TASK-P3-agents-api`
- Risks/questions: `RISK-LIFECYCLE-002` (commands must not auto-chain), `RISK-SCOPE-001` (project state leak), `RISK-PRIVACY-001`
- Design-to-code decision or deviation: mirror the packages service/route layering over Feature 3's FS storage — `_user_dir_key`, `@require_auth`, `projects_repo.get_for_user` ownership check, and `projects_storage.read_spec/write_spec` for the `dataflow.agents` lockfile. Import/Install are separate explicit endpoints (no chaining). The global-catalog scope is deferred (no shared agent definitions exist until the prompt-agent migrations author them); this slice serves **My Imports** + **Installed in this project** + the lifecycle commands over the user store.
- Files/modules changed:
  - `utk_curio/backend/app/agents/services.py` (new — list/import/install service layer over Feature 3 storage; project lockfile via `projects.storage`)
  - `utk_curio/backend/app/agents/routes.py` (new — `agents_bp` at `/api/agents`)
  - `utk_curio/backend/app/__init__.py` (register `agents_bp`)
  - `utk_curio/backend/tests/test_agents/conftest.py` (reuse `_unit_fixtures`), `test_routes.py`
  - `docs/AGENTS.md` (§6 endpoint table)
- Tests added/updated: `TEST-P3-routes` = `tests/test_agents/test_routes.py` (10 tests)
- Verification evidence: `pytest test_agents/ test_llm_default_provider.py` → 69 passed. `create_app()` registers 6 `/api/agents` rules. Verified: install into a project does **not** add to My Imports (no chaining); unknown definition/project → 404; unauth → 401/403.
- Commit/PR: `COMMIT-4b9511a`
- Issues/regressions discovered: none (pre-existing SQLAlchemy `Query.get()` deprecation warnings from `users/repositories.py` are unrelated).
- Resolution: n/a

---

## BL-P3-20260720-02: Frontend agents API client (Feature 5b, slice 1)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-CAT-001` (drawer reads the scopes), `REQ-A11Y` (drawer UI later)
- Design decisions/artifacts: `SRC-UI-003`; reuse of `src/api/packagesApi.ts` + `src/utils/authApi.ts`
- Tasks: `TASK-P3-frontend-agents-api`
- Risks/questions: `RISK-STATE-001` (client/server catalog state divergence)
- Design-to-code decision or deviation: mirror `packagesApi.ts` — a typed `agentsApi` object over the shared `apiFetch` (Bearer + JSON). First frontend slice of the three-scope drawer; the `AgentsCatalogDrawer` component + palette entry point follow in the next slices. Coordinates are `encodeURIComponent`-escaped in path params (`@`/`.`).
- Files/modules changed: `src/api/agentsApi.ts` (new typed client), `src/tests/api/agentsApi.test.ts`
- Tests added/updated: `src/tests/api/agentsApi.test.ts` — 7 jest tests (URL/verb/body/coord-escaping per method, `apiFetch` mocked)
- Verification evidence: `npx jest src/tests/api/agentsApi.test.ts` → 7 passed.
- Commit/PR: `COMMIT-0c4e6c1`

---

## BL-P3-20260720-03: Agents Catalog drawer component (Feature 5b, slice 2)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-CAT-001` (three-scope browse), `REQ-A11Y` (drawer labels/actions)
- Design decisions/artifacts: `SRC-UI-003`; reuse of `DrawerTabs.module.css`, `CatalogPublishPill`, and the `useDatasetCatalogDrawer` hook/test pattern
- Tasks: `TASK-P3-agents-drawer`
- Risks/questions: `RISK-STATE-001` (client/server divergence); `RISK-UX-001` (drawer focus/labels)
- Design-to-code decision or deviation: self-contained `useAgentsCatalogDrawer` hook (state + fetch + lifecycle actions over `agentsApi`, only `projectId` coupling) rather than mirroring the provider-heavy dataset hook. Presentational `AgentsCatalogDrawer` reuses the `DrawerTabs` CSS module for the three scope tabs and `CatalogPublishPill` for Publish. **Publish is rendered with `allowPublish=false`** (no dead button) until the backend Publish endpoint exists — the component lights it up when that lands. Install/Uninstall/Delete are wired to real endpoints.
- Files/modules changed: `src/components/agents/catalog/{useAgentsCatalogDrawer.ts, AgentsCatalogDrawer.tsx, AgentsCatalogDrawer.module.css}` (all new)
- Tests added/updated: `src/tests/catalog/useAgentsCatalogDrawer.test.ts` (6), `src/tests/catalog/AgentsCatalogDrawer.test.tsx` (5)
- Verification evidence: `npx jest` on the three agents specs → 18 passed (7 api + 6 hook + 5 drawer-render). Render smoke covers the three scope tabs, card render, scope switch → `listImports`, Install disabled without a project, and Install → `installToProject`. CSS modules resolve via jest `identity-obj-proxy`; jest ts-transform compiles the component.
- Commit/PR: `COMMIT-01eaa06`

---

## BL-P3-20260720-04: Mount the drawer — provider + menu entry point (Feature 5b, slice 3)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-CAT-001` (drawer reachable in the app)
- Design decisions/artifacts: reuse of `NodeCatalogDrawerProvider` (provider/portal pattern) + `UpMenu` catalog entries
- Tasks: `TASK-P3-agents-drawer-mount`
- Risks/questions: `RISK-UX-001` (focus/close behavior)
- Design-to-code decision or deviation: `AgentsCatalogDrawerProvider` (open/close context + Escape-to-close, portal, reads `useFlowContext().projectId`) mounted inside `FlowProvider` in `index.tsx`; a `Data → Agents Catalog` row in `UpMenu` (faRobot) opens it, mirroring the Node Catalog row. Simpler than the node provider's animation machinery (the agents drawer has no slide transition yet) — kept intentionally minimal.
- Files/modules changed: `src/providers/AgentsCatalogDrawerProvider.{tsx,module.css}` (new), `src/index.tsx` (mount), `src/components/menus/top/UpMenu.tsx` (entry point), `docs/AGENTS.md`
- Tests added/updated: `src/tests/providers/AgentsCatalogDrawerProvider.test.tsx` (5)
- Verification evidence: `npx jest` agents specs → 23 passed (7 api + 6 hook + 5 drawer + 5 provider). `tsc --noEmit` reports zero errors in the touched files. No existing UpMenu test to break.
- Commit/PR: `COMMIT-d1e6a1a`
- Follow-up work: wire Publish when the backend endpoint ships; drawer slide animation for parity.
- **Amendment (2026-08-26, memo `dev/43`, `COMMIT-1ad5b15`):** both follow-ups are closed. Publish landed in `BL-P3-20260720-06`. The drawer slide animation shipped 2026-07-29: `AgentsCatalogDrawerProvider` adopts `NodeCatalogDrawerProvider`'s two-phase presentation (mounted/presented, double-rAF enter, exit timer + `onExitComplete` on the panel's `transform` transitionend, `prefers-reduced-motion` snap guarded for jsdom, focus restore, scroll lock); `AgentsCatalogDrawer` owns the `overlayRoot`/`scrim`/`panel` structure with the sibling drawers' timings (scrim opacity 240ms; panel `translate3d` 300ms `cubic-bezier(0.32,0.72,0,1)`); the provider's static backdrop CSS module was deleted. Provider tests cover mounted-through-exit, transitionend unmount, and reopen-during-exit. Pin semantics (`DEC-042`) and Escape behavior unchanged. No open follow-up remains on this entry.

---

## BL-P3-20260720-05: AGENTS tools-panel palette (Feature 5b, slice 4)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-CAT-001` (project palette lists installed templates), `REQ-ATTACH` (drag source for the later attach flow)
- Design decisions/artifacts: reuse of `PackagesPaletteDropdown`/`DatasetsPaletteDropdown` layout + `ToolsMenu` mount; the AGENTS palette lists only the active project's `ProjectAgentTemplate` records and is action-free (per `dev` plan).
- Tasks: `TASK-P3-agents-palette`
- Risks/questions: `RISK-STATE-001` (palette vs lockfile divergence)
- Design-to-code decision or deviation: a **lean** `AgentsPaletteDropdown` (flat list; no fork-families/publish/registry-snapshot complexity of the packages palette). Lists installed-in-project agents via `agentsApi.listProjectAgents`, refreshes on open + on a `curio:agents-palette-refresh` window event (dispatched by the drawer hook after install/uninstall), and has a "Get more agents +" footer opening the drawer. Rows are **draggable** — the drag source writes `application/curio-agent` = coordinate; the drop/attach handler is Feature 6 (attachments), so the palette is complete *as a palette* but attach-on-drop lands next.
- Files/modules changed: `src/components/menus/nodes/agentsPalette/{AgentsPaletteDropdown.tsx,AgentsPalette.module.css,index.ts}` (new), `src/utils/agentsPaletteEvents.ts` (new), `src/components/agents/catalog/useAgentsCatalogDrawer.ts` (notify after lifecycle), `src/components/menus/nodes/ToolsMenu.tsx` (mount), `docs/AGENTS.md`
- Tests added/updated: `src/tests/palette/AgentsPaletteDropdown.test.tsx` (4)
- Verification evidence: `npx jest` → 4 palette pass; 115 catalog/provider/palette specs pass together (no regressions in the existing dataset-catalog tests). `tsc --noEmit` reports zero errors in the touched files.
- Commit/PR: `COMMIT-269bd49`
- Follow-up work: drop/attach handler (Feature 6) consumes the `application/curio-agent` drag payload.
- **Amendment (2026-08-26):** the drop/attach follow-up is closed — the `application/curio-agent` payload is consumed by the canvas drop-to-attach handler in `BL-P4-20260720-03` (`COMMIT-aac8672`) and the node-target drop in `BL-P4-20260720-06` (`COMMIT-c7f57b4`). No open follow-up remains on this entry.
- **Amendment (`COMMIT-dfde136`):** palette rows (click / Enter / Space) and the empty state now open the drawer, in addition to the footer; rows remain draggable. 6 palette tests pass.

---

## BL-P3-20260720-06: Imported-only Publish to the Global Catalog (backend + frontend)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-PUBLISH-002` (Publish accepts only an owned validated import; rejects global/built-in/project-template/attachment), `REQ-LIFECYCLE-001` (publish/unpublish are distinct operations)
- Design decisions/artifacts: `DEC-030` (imported-only publish), `DEC-040` (FS-backed); `SRC-MEMO-LIFECYCLE-012`; reuse of `app/packages` publish-to-catalog concept
- Tasks: `TASK-P3-publish`
- Risks/questions: `RISK-PUBLISH-001` (a built-in/global/template/attachment is user-published, or Publish silently installs)
- Design-to-code decision or deviation: a filesystem **shared publications catalog** at `.curio/agents-catalog/<id>@<version>/` (deployment-shared, sibling of `.curio/users/`), populated by copying an **owned, store-backed, non-built-in** definition. Publish rejects a coord that is a built-in or not present in the user's store (nothing to publish yet in practice — user-authored imports need upload-import, a later feature — but the endpoint is correct and tested). Global Catalog = built-ins ∪ published. Card gains `published` + `publishable` flags so the frontend pill only appears for eligible cards.
- Files/modules changed:
  - Backend: `app/agents/publications.py` (new — shared FS catalog), `app/agents/services.py` (publish/unpublish + card `published`/`publishable` flags + Global Catalog = built-ins ∪ published + `_resolve_definition` resolves published), `app/agents/routes.py` (`POST`/`DELETE /api/agents/publications`), `docs/AGENTS.md`
  - Frontend: `src/api/agentsApi.ts` (card flags + `publish`/`unpublish`), `src/components/agents/catalog/useAgentsCatalogDrawer.ts` (publish/unpublish actions), `AgentsCatalogDrawer.tsx` (pill driven by `publishable`/`published`)
- Tests added/updated: `tests/test_agents/test_publications.py` (4) + `TestPublish` in `test_routes.py` (5); frontend `agentsApi.test.ts` (2), `useAgentsCatalogDrawer.test.ts` (1), `AgentsCatalogDrawer.test.tsx` (1)
- Verification evidence: `pytest test_agents/` → 88 passed. `npx jest` agents specs → 31 passed. Verified: publish an owned store-backed import → appears in the Global Catalog with `published=true`; a built-in (or un-imported) coord → 400; `publishable` is true for owned store-backed and false for built-ins; the drawer shows exactly one Publish control for a publishable card and none for a built-in. `tsc --noEmit` clean on touched files.
- Commit/PR: `COMMIT-5154302` (backend), `COMMIT-e843502` (frontend)
- Follow-up work: user-reachable once upload-import (v2) lets users create owned imported definitions; a dedicated Unpublish control in the drawer (API/hook already support it); attach/execution (Feature 6).
- **Amendment (2026-08-26):** two of three follow-ups are closed — upload-import shipped in `BL-P3-20260727-10` (memo `dev/36`, `COMMIT-c630c01`/`COMMIT-018df3d`), making Publish user-reachable; attach/execution shipped in `BL-P4-20260720-02` (`COMMIT-e5ee213`). **Still open:** a dedicated Unpublish control in the drawer — `agentsApi.unpublish` and `useAgentsCatalogDrawer().unpublish` exist, but no drawer UI called them (verified 2026-08-26) — **closed by `BL-P3-20260826-13` (memo `dev/107`)**. No open follow-up remains on this entry.

---

## BL-P3-20260720-07: AGENTS palette approved restyle + shared palette shell (filed as memo `dev/31`)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-A11Y`, palette visual parity with the approved concept
- Design decisions/artifacts: approved AGENTS palette concept (category-tinted rows); shared-chrome extraction to avoid triplicated palette CSS
- Tasks: `TASK-P3-palette-restyle`, `TASK-P3-palette-shell`
- Risks/questions: `RISK-UX-001` — realized once: the palette dropdown was click-through to the canvas (fixed in `COMMIT-c80d217`).
- Design-to-code decision or deviation: introduce a category color map + presentational `AgentPaletteRow` and restyle the AGENTS palette to the approved concept; then extract the shared dropdown chrome into `menus/nodes/paletteShell/` (`paletteShell.module.css`) and migrate the Agents, Datasets, and Packages palettes onto it so the three palettes share one visual system instead of three diverging stylesheets.
- Files/modules changed: `menus/nodes/agentsPalette/{AgentPaletteRow.tsx,AgentPaletteRow.module.css,AgentsPalette.module.css}`, `menus/nodes/paletteShell/{index.ts,paletteShell.module.css}` (new), `datasetsPalette/DatasetsPaletteDropdown.module.css`, `ToolsMenuPackagePalette.module.css`
- Tests added/updated: `AgentPaletteRow.test.tsx`, updated `AgentsPaletteDropdown.test.tsx`; existing datasets/packages palette suites re-run green after the shell migration
- Verification evidence: `npx jest` palette suites green at each commit; `tsc --noEmit` clean; visual check against the approved concept.
- Commit/PR: `COMMIT-c80d217` (click-through fix), `COMMIT-b233517` (color map + row), `COMMIT-bbd2cb5` (restyle), `COMMIT-b8c2a23` (shell extraction + Agents/Datasets migration), `COMMIT-923bacf` (Packages migration)
- Issues/regressions discovered: dropdown click-through (fixed); none after the shell migration.
- Follow-up work: per-target compatibility pills landed later in `BL-P4-20260721-10`.
- Remaining risks/questions: none new.

---

## BL-P3-20260722-08: Project-agent-default cogs (P3 remainder — memo dev/23)

- Date / author: 2026-07-22 / Karla
- Status: verified
- Requirements: `REQ-PROJECT-INSTALL-001` (per-project template defaults), `REQ-SETTINGS-001` (v1 subset: scope identity + effective value + inherited source, read-only), `REQ-SETTINGS-A11Y-001` (labeled entry point, dialog semantics), `REQ-STATE-002`
- Design decisions/artifacts: memo `dev/11` (labeled cogs; install materializes an independent project profile), memo `dev/12` (installed-scope actions; no Publish/Release/Share in this scope), `DEC-040` (FS-backed); `SRC-MEMO-SETTINGS-011`, memo `dev/23`
- Tasks: `TASK-P3-default-cogs`
- Risks/questions: `RISK-MODAL-001` (scope confusion — mitigated: persistent scope banner + provenance chips); editing deliberately absent until the settings screens
- Design-to-code decision or deviation: a backend-owned `spec.dataflow.agentDefaults` section (`{coord: {revision, settings}}`) reusing the lockfile ownership pattern — materialized at install (idempotent; seeded from the manifest's `settingsDefaults` profile id/version, built-ins empty), dropped at uninstall, added to `_AGENT_SPEC_KEYS` so `preserve_agent_state` protects it from canvas-save clobbering; lazy materialization on first read covers pre-slice installs. `GET /projects/<pid>/defaults/<coord>` returns the record + server-computed effective policy with provenance (account runs/day limit + `quotas.runs_used_today`, cost unconfigured, no-secrets provider summary added at the route layer from the request user's resolved config). Frontend: labeled `Project agent settings` control on installed-scope cards only (other scopes/palette rows action-free per `docs/02`) opening a read-only `ProjectAgentSettingsModal` (ModalShell, scope banner, three sections with "Inherited from account" chips, no Publish/Release/Share). The settings screens will PATCH exactly this `{revision, settings}` shape.
- Files/modules changed: backend `app/agents/{project_agents.py,services.py,routes.py,quotas.py (runs_used_today)}`; frontend `api/agentsApi.ts`, `components/agents/settings/{ProjectAgentSettingsModal.tsx,ProjectAgentSettingsModal.module.css}` (new), `components/agents/catalog/AgentsCatalogDrawer.tsx`; `docs/AGENTS.md`
- Tests added/updated: `test_agent_defaults.py` (5 pure) + preserve regression + `TestProjectAgentDefaults` in `test_routes.py` (6: effective view, usedToday after a run, 404/uninstall-drop, lazy materialization, per-project isolation + save durability, reinstall keeps revision); frontend `ProjectAgentSettingsModal.test.tsx` (4), drawer cog tests (2), api test (1)
- Verification evidence: `pytest test_agents/` → 178 passed; `npx jest` full → 521 passed (52 suites); `tsc --noEmit` clean.
- Commit/PR: `COMMIT-7942c5e` (spec section), `COMMIT-3a6c2d9` (service/route), `COMMIT-120cdc1` (cog + modal), `COMMIT-8c92a2e2` (docs/AGENTS.md)
- Follow-up work: the Cost/Quotas/Resource settings screens (the last v1 item) edit this record and add the account-scope `Agent settings` cog in the roster header.
- **Amendment (2026-08-26):** closed by `BL-P3-20260723-09` (memo `dev/24`, `COMMIT-5c7fc32`…`COMMIT-acb4316` shell+cogs) — the Cost/Quotas/Resource-policy screens edit `spec.dataflow.agentDefaults` and the account-scope `Agent settings` cog sits in the roster header. No open follow-up remains on this entry.

---

## BL-P3-20260723-09: Settings shell — Cost/Quotas/Resource-policy screens (memo dev/24; closes the v1 cut)

- Date / author: 2026-07-23 / Karla
- Status: verified
- Requirements: `REQ-SETTINGS-001` (scope identity, effective value + inherited source, downward-only overrides), `REQ-POLICY-001`, `REQ-COST-001` (v1 subset: estimated-only budget, labeled, no fake meters), `REQ-QUOTA-001` (v1 subset: windowed counters + stable denial; ledgers v2), `REQ-RESOURCE-001` (v1 subset: maxOutputTokens; profiles v2), `REQ-SETTINGS-A11Y-001` (labeled cogs, dialog semantics, dirty-guard)
- Design decisions/artifacts: memo `dev/11` (screens/scopes/revisions/reset), `dev/12` (settings applicability), `DEC-037` context, `DEC-038` (this closes the v1 release cut), `DEC-040`; `SRC-MEMO-SETTINGS-011`, memo `dev/24`
- Tasks: `TASK-SETTINGS-policy-screens`
- Risks/questions: `RISK-POLICY-001` (mitigated: one resolver for display AND enforcement; tighten-only at write + clamp at read), `RISK-COST-001` (mitigated: estimated-only, labeled, inactive until configured; `DEC-037`-style account-scope estimate), `RISK-MODAL-001` (scope banner + source chips)
- Design-to-code decision or deviation: account record `.curio/users/<key>/agents/settings.json` (`account_settings.py`, revisioned); `policy.py` resolves `project ?? account ?? deployment` per field with sources, clamps downward at read, and validates tighten-only at write (estimate account-only; null clears). Admission (`quotas.admit`) checks account limit → project-template limit (per-template counts in the daily window) → estimated budget gate; 429 carries `reason: quota|budget`; `maxOutputTokens` flows through both provider-port functions (anthropic's hardcoded 4096 replaced). API: GET/PATCH `/api/agents/settings`, PATCH `…/defaults/<coord>` (409 stale, `{}` = Reset to agent default, non-policy seed keys preserved), GET defaults now returns per-field sources + estimated spend. Frontend: the dev/23 read-only modal evolved into the scope-aware `AgentSettingsModal` (three tabs, effective+source per field, single record-level Save with revision — a deliberate deviation from the memo's per-screen Save, since both scopes are one record; 409 → reload+reapply; dirty-guard; project Reset); account entry = labeled `Agent settings` cog in the roster header (the `DEC-042`-noted exception), project entry = the existing installed-card cog. Attachment scope deferred as specced.
- Files/modules changed: backend `app/agents/{account_settings.py (new),policy.py (new),quotas.py,providers.py,services.py,routes.py}`; frontend `api/agentsApi.ts`, `components/agents/settings/AgentSettingsModal.{tsx,module.css}` (replacing `ProjectAgentSettingsModal`), `components/agents/catalog/AgentsCatalogDrawer.{tsx,module.css}`; `docs/AGENTS.md`
- Tests added/updated: `test_policy.py` (12), `TestAdmit` (4), `TestMaxOutputTokens` (2), `TestSettingsScreensApi` (6 end-to-end incl. project-limit gating + reset restoring runs, budget denial with reason + spend reporting, token passthrough, seed preservation); frontend `AgentSettingsModal.test.tsx` (8 across both scopes), drawer account-cog test, api tests
- Verification evidence: backend 704 passed (the one unrelated failure is the user's uncommitted `config.py` default-model change); `npx jest` full → 527 passed (53 suites); `tsc --noEmit` clean.
- Commit/PR: `COMMIT-5c7fc32` (record+resolver), `COMMIT-a121650` (admission+port), `COMMIT-ee11790` (API), `COMMIT-acb4316` (shell+cogs), `COMMIT-763d728` (docs)
- Issues/regressions discovered: none; prior run-path mocks updated for the new `max_output_tokens` kwarg.
- Follow-up work: **none for v1 — this closes the `DEC-038` v1 cut.** v2: attachment-scope tighten-only settings, reservations/ledgers, alerts/pricing dates, token metering ("Actual" cost), provider profiles + secret store, governance screens.

---

## BL-P3-20260727-10: Upload-import — user-authored definitions (memo `dev/36`; v2 entry slice)

- Date / author: 2026-07-27 / Karla
- Status: verified
- Requirements: `REQ-IMPORT-002` (explicit account import), `REQ-PUBLISH-002` (imported-only publish — now user-reachable), `REQ-PROMPT-001` (digest-verified prompt assets)
- Design decisions/artifacts: `DEC-029` (immutability → 409 on collision, rule 7 recorded), `DEC-030` (nothing auto-chains), `DEC-040` (FS store), `RISK-IMPORT-001` (scope decision: **JSON-body upload, no archives** — the extraction attack surface is avoided entirely; archive upload, if ever wanted, is a later P6-hardened addition); memo `dev/36`
- Tasks: `TASK-P3-upload-import`
- Risks/questions: `RISK-IMPORT-001` (addressed by scope + atomic staging), `RISK-PROMPT-001` (digests stamped server-side from the uploaded bytes; client digests ignored), forced `imported` trust so an upload can never corrupt publish gating or roster-first resolution
- Design-to-code decision or deviation: `POST /api/agents/imports/upload` `{manifest, prompts}` → `services.upload_import` (fail-closed: manifest contract via `parse_agent_manifest`, forced provenance trust, digest stamping, exact file↔manifest correspondence, ≤16 files/≤256KB each/≤1MB total → 413, existing store coordinate → 409 incl. materialized built-ins) → `storage.write_definition_atomic` (temp-dir staging + `os.replace`, cleanup on failure — no partially visible artifact) → My Imports registration → the first `publishable: true` card. Frontend: the concept's footer `Import package` button + `AgentImportModal` (multi-file picker, pure `buildUploadPayload`, verbatim server errors, success → My Imports + reload).
- Files/modules changed: backend `app/agents/{storage.py (write_definition_atomic),services.py (upload_import),routes.py}`; frontend `api/agentsApi.ts`, `components/agents/catalog/{buildUploadPayload.ts,AgentImportModal.tsx,AgentImportModal.module.css (new),AgentsCatalogDrawer.tsx,AgentsCatalogDrawer.module.css}`; `docs/AGENTS.md`
- Tests added/updated: `test_upload_import.py` (10, incl. **the full loop**: upload → publish → Global Catalog → install → attach → run with the uploaded instruction as the system turn; forced trust; duplicate/built-in-shadow 409; missing/extra file 400; traversal rejection; size 413; no auto-chain); frontend `AgentImportModal.test.tsx` (6 helper+modal), drawer wiring + api tests
- Verification evidence: `pytest test_agents/` → 241 passed; `npx jest` full → 550 passed; `tsc --noEmit` clean.
- Commit/PR: `COMMIT-c630c01` (backend), `COMMIT-018df3d` (frontend + drawer)
- Follow-up work: this closes the "Publish reachability awaits upload-import" deferral. v2 governance (prompt editing/evaluation/audit) now has real owned content to operate on.

---

## BL-P3-20260728-11: Attachment settings — the Attached-instance policy scope (memo dev/42)

- Date / author: 2026-07-28 / Karla
- Status: verified
- Requirements: the four-scope settings design (docs/08/03/11, dev/11's scope table — "Attachment settings may only tighten Cost, Quotas, and Resources"); `DEC-031` (pins reflect what gated the run); `DEC-042` (the cog lives beneath the opened-view header, never in it)
- Design decisions/artifacts: memo `dev/42` — **no new DEC consumed** (already-approved design; closes the follow-up `BL-P3-…-09`/dev/24 explicitly deferred: "tighten-only per-instance overrides need per-attachment enforcement records"). The enforcement records dev/24 lacked became one field under the `DEC-044` ledger.
- Tasks: `TASK-P3-attachment-settings`
- Risks/questions: none new — settings ride the attachment record (share-stripped wholesale, rule-9 suite re-run green); pre-dev/42 ledger entries lack `attachmentKey` and count nothing per-attachment (tolerated, daily windows).
- Design-to-code decision or deviation: **(1) Resolver** — `policy.effective` gains the attached-instance layer (`attachment ?? project ?? account ?? deployment`, clamped downward at read, source `"attachment"`); `validate_patch("attachment", project_effective)` enforces tighten-only at write; the account-only estimate stays uneditable below account scope. **(2) Enforcement** — ledger reserve entries record `attachmentKey` (always — attribution), aggregates derive `byAttachment`, and an attachment-source runs/day limit gates in the existing critical section (order: account → template → attachment → budget) with a 429 naming the attachment limit; sibling attachments of the same template keep running. **(3) Record + API** — overrides ride the attachment record sharing its optimistic `revision` (an intent/title edit stales a settings draft — one record, one token, deliberate); `GET`/`PATCH /attachments/<id>/settings` mirror the project-defaults pair; `{}` = *Clear overrides*; `usedToday` meters the **binding** scope (attachment-source → this attachment's count; project → template count; else account). Budget semantic deliberately unchanged: an attachment-tightened budget gates the account-wide spend ladder, exactly as project-tightened budgets already do (stated in the memo §4.3 for conscious review; per-attachment spend attribution is a clean later slice on the same ledger). **(4) Pins** — `policy_pins` builds from the three-layer effective view, so `DEC-031` snapshots reflect instance tightening with zero pins-code changes. **(5) Frontend** — the modal's third scope (`Attached instance` banner, `Clear overrides` reset, estimate read-only) and the docs/08 anatomy slot finally filled: the labeled ⚙ `Attachment settings` control at the top of the white content area beneath the `DEC-042` header, opening the shared modal for this attachment.
- Files/modules changed: `app/agents/{policy.py,ledger.py,attachments.py,services.py,routes.py}`; frontend `api/agentsApi.ts`, `components/agents/settings/AgentSettingsModal.tsx`, `components/agents/attach/{AgentChatPanel.tsx,AgentChatPanel.module.css,AgentDockOverlay.tsx}`; `docs/AGENTS.md`
- Tests added/updated: `test_policy.py` `TestAttachmentScope` (5: downward-only third layer, read-time clamp, absent-layer identity, tighten-only patch, estimate refusal), `test_ledger.py` `TestAttachmentLimits` (4 incl. pre-dev/42 tolerance), `test_routes.py` `TestAttachmentSettings` (9: three-layer GET, tighten/bind, loosen 400, estimate 400, shared-revision 409 via intent edit, Clear overrides, per-attachment 429 + sibling isolation + binding-scope meter, tightened maxOutputTokens → provider + pins, settings die with the attachment); frontend modal attachment-scope suite (4) + panel cog tests (2)
- Verification evidence: backend `pytest tests --ignore=tests/test_frontend` → 895 passed; frontend `npx jest` full → 602 passed (55 suites)
- Commit/PR: `COMMIT-58d01e00` (policy), `COMMIT-8675f55d` (ledger), `COMMIT-de1c3b67` (record/API/wiring), `COMMIT-786041bb` (frontend)
- Issues/regressions discovered: none.
- Follow-up work: per-attachment budget *attribution* (only if the account-wide budget semantic proves insufficient); the Imported-definition scope remains v2 governance (`DEC-036`/`DEC-038`).
- Remaining risks/questions: none new.

---

## BL-P3-20260729-12: Catalog drawer tab transitions + installation-state consistency (memo dev/47)

- Date / author: 2026-07-29 / Karla
- Status: verified
- Requirements: post-implementation testing feedback (explicit fix request) — smooth tab changes, one source of truth for imported/installed/published, immediate cross-surface consistency (tabs, drawer, Agents Palette)
- Design decisions/artifacts: memo `dev/47` — no new DEC consumed; follows the Nodes/Datasets drawers' load-once/reload-in-place transition behavior and the lockfile-as-truth precedent already used by the Global scope
- Tasks: `TASK-P3-drawer-state-sync`
- Risks/questions: none new — the palette was already synchronized (`notifyAgentsPaletteRefresh`); pre-existing `AgentRow` action logic untouched (it was fed wrong data, not wrong itself)
- Design-to-code decision or deviation: **(1) Backend truth** — `services.list_my_imports(user_key, project_id=None)` reads `project_agents.project_agents(spec)` (the lockfile) and marks `installedInProject` per coordinate; `GET /api/agents/imports?projectId=` passes it through; without a project the prior behavior (all `false`) is preserved. This closes the hardcoded `installed_in_project=False` that made an installed Node Content Builder show an active Install on My Imports. **(2) Frontend cache** — `useAgentsCatalogDrawer` becomes a per-scope `cardsByScope` cache with stale-while-revalidate tabs: switching renders the cache instantly, refreshes in the background, and `loading` is true only for a scope's first-ever fetch; a per-scope request sequence (`seqRef`) drops out-of-order responses; errors keep cached rows (banner over content); every lifecycle action refreshes **all** scopes in parallel (`Promise.allSettled`) after `notifyAgentsPaletteRefresh`, so all tabs agree immediately; the cache invalidates wholesale on `projectId` change. `agentsApi.listImports(projectId?)` forwards the query param.
- Files/modules changed: backend `app/agents/{services.py,routes.py}`; frontend `api/agentsApi.ts`, `components/agents/catalog/useAgentsCatalogDrawer.ts`
- Tests added/updated: backend `test_routes.py` `TestMyImportsInstalledState` (3: imported+installed→true with projectId, imported-only→false, no projectId→false); frontend drawer suite +6 (cached tab renders instantly with no `Loading…` reset; installed import shows Uninstall — the Node Content Builder regression by name; My Imports fetched with the open project id; a lifecycle action re-hits all three list endpoints; refresh error keeps cached rows; out-of-order response dropped)
- Verification evidence: backend agents suite 405 passed; frontend `npx jest` full → 617 passed (56 suites); tsc unchanged (pre-existing tsconfig deprecation warnings only)
- Commit/PR: `COMMIT-942e5c31` (backend), `COMMIT-ab9e92d7` (frontend)
- Issues/regressions discovered: none.
- Follow-up work: none for this slice.

---

## BL-P3-20260826-13: Drawer Unpublish control + publication ownership hardening (memo `dev/107`)

- Date / author: 2026-08-26 / Karla
- Status: implemented (owner live re-test pending)
- Requirements: `REQ-LIFECYCLE-001` (publish/unpublish are distinct, both user-reachable), `REQ-PUBLISH-002` (owner-only inverse of imported-only publish); `docs/RETENTION.md` "owner … unpublishes" made true in the UI (`DEC-057`/`DEC-058`)
- Design decisions/artifacts: memo `dev/107` — **no new DEC**; completes `DEC-030`'s UI. Sibling precedents followed: `PackageCard` Unpublish-beside-badge, Nodes/Datasets drawers' `window.confirm` gate; `dev/101`/`dev/106` refuse-while-in-use precedent for the Delete 409
- Tasks: `TASK-P3-drawer-unpublish`
- Risks/questions: `RISK-PUBLISH-001` — ownership is still inferred (caller's store copy `trust=imported` + in My Imports), not recorded on the publication; an account holding an imported copy under the same coordinate can still *republish over* another's entry. A recorded publisher on the publication is the eventual fix (not this slice). Global-tab Unpublish needs an explicit `ownedByCaller` card field — follow-up.
- Design-to-code decision or deviation: **(1) Backend** — `unpublish_agent` authorized by store *presence*; importing a built-in materializes a copy, so an owned shadow of a built-in coordinate was unpublishable by any importer of the built-in. Now `_owns_publication` (the predicate `publish_agent` already used); 404 when not published. `remove_import` 409 while the caller's owned definition is published (Delete would otherwise orphan the publication by removing the row that carries Unpublish); a Hub consumer's import drops freely. **(2) Verified, pinned by test**: a non-built-in publication is *not* materialized into other accounts' stores at install — their prompt bytes resolve from the shared catalog and return `None` after unpublish — so the confirm copy says those installs stop running, rather than the Nodes/Datasets "installed copies are not removed" line. **(3) Frontend** — `AgentRow` (My Imports) renders `Unpublish` beside the `Published` badge when `published && publishable`, confirm via the shared `unpublishListingConfirm` (`retentionCopy.ts`), then the pre-existing `useAgentsCatalogDrawer().unpublish` (all-scope refresh, dev/47). Account-scoped (enabled with no project). `CatalogPublishPill` untouched.
- Files/modules changed: backend `app/agents/{services.py,routes.py}`; frontend `services/retentionCopy.ts`, `components/agents/catalog/AgentsCatalogDrawer.tsx`; `docs/AGENTS.md` (two route rows)
- Tests added/updated: backend `test_routes.py` `TestPublish` +6 (404 not published; non-owner with built-in store copy 403; non-owner without copy 403; Delete 409 while published then 200 after unpublish; consumer's import drops; other account's install stops resolving) + `bob_and_token` fixture; frontend `retentionCopy.test.ts` +1, `AgentsCatalogDrawer.test.tsx` +6 (badge+one button / built-in badge alone, confirm→endpoint→all-scope refresh, cancel sends nothing, error banner keeps rows, enabled without project, Global never shows it), `useAgentsCatalogDrawer.test.ts` +1
- Verification evidence: `pytest tests/test_agents/test_routes.py tests/test_agents/test_publications.py` → 306 passed; `npx jest src/tests/catalog src/tests/palette src/tests/providers/AgentsCatalogDrawerProvider.test.tsx src/tests/services/retentionCopy.test.ts` → 188 + 8 passed; `tsc --noEmit` clean in touched files (2 pre-existing errors in the untouched `useAgentAttachments.test.ts` at HEAD)
- Commit/PR (on `feat/agentscatalog`): `COMMIT-df249e18` (backend ownership + 404 + Delete 409), `COMMIT-1870ebba` (shared confirm copy), `COMMIT-47a49273` (drawer control), `COMMIT-dd1c5d74` (memo); this entry landed in `COMMIT-7bf52e8a`. The same three code commits exist on `feat/agentcatalog` as `ce73d694` / `36bfe4c2` / `e832c7fd` (cherry-pick source).
- Follow-up work: recorded publisher on publications (closes the republish-over gap); Global-tab Unpublish via `ownedByCaller`; materialize published bytes into the installer's store so Hub installs survive unpublish (would need ownership recorded first — otherwise the installer's `trust=imported` copy would make them an "owner").

---

## BL-P3-20260826-14: Catalog-drawer providers migrated onto `useSlideDrawerPresentation` (memo `dev/109`)

- Date / author: 2026-08-26 / Karla
- Status: implemented (refactor; owner spot-check of the three drawers pending)
- Requirements: maintainability follow-up from `BL-P4-20260826-17` / `dev/108` — one drawer state machine, not four; `DEC-042` Pin semantics preserved
- Design decisions/artifacts: memo `dev/109` — **no new DEC**. Characterization-first: the Node and Dataset providers received their first tests (against the inline code) before any change.
- Tasks: `TASK-P3-drawer-provider-migration`
- Risks/questions: none new.
- Design-to-code decision or deviation: the three providers had drifted — Dataset used a **single** rAF enter (could skip the slide), Node/Dataset called `matchMedia` unguarded (untestable under jsdom), and Dataset exposed `isOpen = presented` while Node/Agents exposed `mounted`. All three now call `useSlideDrawerPresentation(open, { onExited })` (hook gained the `onExited` option for focus restore) and keep only their own concerns. **Deliberate behavior changes (Dataset only)**: double-rAF enter; `isDatasetCatalogDrawerOpen` and the body scroll lock follow `mounted`, so the Datasets palette no longer dismisses on an Escape during the drawer's ≤380 ms exit slide (verified conservative against `DatasetsPaletteDropdown.tsx:74-92`, which only *suppresses* dismissal while open). Generic-provider consolidation explicitly rejected (three differing context APIs; import churn for no gain).
- Files/modules changed: `hook/useSlideDrawerPresentation.ts` (+`onExited`), `providers/{NodeCatalogDrawerProvider,AgentsCatalogDrawerProvider}.tsx`, `providers/datasetCatalog/DatasetCatalogDrawerProvider.tsx`, `components/agents/catalog/AgentsCatalogDrawer.module.css` (comment), `docs/AGENTS.md`
- Tests added/updated: `tests/providers/NodeCatalogDrawerProvider.test.tsx` (new, 10), `tests/providers/DatasetCatalogDrawerProvider.test.tsx` (new, 11 — two written to target semantics as `it.failing`, flipped in commit 3), `tests/hook/useSlideDrawerPresentation.test.ts` (+1 `onExited`); `AgentsCatalogDrawerProvider.test.tsx` 8/8 unchanged
- Verification evidence: full `npx jest` → 92 suites / 1042 passed; `tsc --noEmit` clean in touched files; `grep` for `requestAnimationFrame|exitTimerRef|exitSettledRef|DRAWER_MOTION_MS|useSyncExternalStore` under `src/providers/` → empty. Lines: 135→96, 154→118, 169→114.
- Commit/PR: `COMMIT-23f2fe9c` (characterization suites + `onExited`), `COMMIT-f1f9cf1f` (Node), `COMMIT-53f33782` (Dataset), `COMMIT-30b88c04` (Agents); docs commit follows
- Follow-up work: none.

---

## BL-P3-20260827-15: Publications record their publisher — ownership by record, no publish-over (memo `dev/110`, `DEC-069`)

- Date / author: 2026-08-27 / Karla
- Status: implemented (owner live re-test pending)
- Requirements: `REQ-PUBLISH-002` (owner-only inverse of imported-only publish, now enforceable), `REQ-LIFECYCLE-001`; `docs/RETENTION.md` "owner unpublishes" made true by construction
- Design decisions/artifacts: **`DEC-069`** minted (publisher record is the authority for publish-over/unpublish/delete-import; legacy fallback + never-guess backfill). Closes both `BL-P3-20260826-13` follow-ups (recorded publisher; Global-tab Unpublish via `ownedByCaller`) and unblocks the third (materialize-at-install) without doing it.
- Tasks: `TASK-P3-publication-record`
- Risks/questions: `RISK-PUBLISH-001` **realized and fixed** — `publish_from_dir` was an idempotent overwrite with no owner, so an account with its own upload under the same author-chosen coordinate could replace another account's published bytes, and (per `dev/107`) every Hub consumer's install would then run the replacement's prompt. Now 409. Residual: shared-guest users share one key (documented commingling); two accounts publishing a brand-new coordinate simultaneously → last rename wins with its own record, the other gets 409 afterwards.
- Design-to-code decision or deviation: **(1) Store** — `publication.json` sidecar `{schema, publisherKey, publishedAt, sourceDigest}`; artifact copied byte-identical (loaders read only `manifest.json`); staged swap moves the previous entry aside and restores it if the final rename fails (test-pinned); a stale record in the source tree is never carried; `list_published` skips staging dirs; `unpublish_all_for(key)` for the retention procedure. **(2) Authorization** — `_owns_publication` record-first; `dev/107`'s heuristic kept only as `_legacy_owns_publication` for record-less entries and claimed on the owner's next publish; `publish_agent` 409 on a foreign-owned coordinate; same-owner republish restamps. **(3) Cards** — `ownedByCaller` boolean on Global/My Imports/upload responses; the key never leaves the backend. **(4) Frontend** — one factored `UnpublishButton` on the Global tab (owned rows) and My Imports (now `published && publishable && ownedByCaller`); a collision note on My Imports for `published && !ownedByCaller`; Delete unblocked for non-owners. **(5) Retention** — no account-deletion service path exists in code, so step 2 stays operator-run but is now one documented call plus the backfill tool. Not done: materialize-at-install (separate memo), publisher display names, audit trail.
- Files/modules changed: backend `app/agents/{publications.py,services.py}`, `utk_curio/tools/backfill_publications.py` (new); frontend `api/agentsApi.ts`, `components/agents/catalog/{AgentsCatalogDrawer.tsx,AgentsCatalogDrawer.module.css}`; `docs/AGENTS.md`, `docs/RETENTION.md`, `dev/03` DEC table, `dev/00` index
- Tests added/updated: backend `test_publications.py` `TestPublicationRecord` (10: record contents/digest, identical bytes + loader ignores sidecar, legacy None, corrupt→legacy, unpublish removes record, restamp + stale-source-record dropped, staged-swap failure keeps the previous entry, key required, `unpublish_all_for` scope, staging dirs skipped); `test_routes.py` `TestPublicationOwnership` (6: record written; same-coordinate 409 + consumers still get the first publisher's bytes + non-owner 403 even though the dev/107 heuristic passes; owner republish restamps; `ownedByCaller` on Global/My Imports and key never serialized; legacy fallback + claim; delete-import guard owner-only); `test_backfill_publications.py` (6); frontend `AgentsCatalogDrawer.test.tsx` (+3 new, 1 rewritten: Global owned/not-owned, collision note, no note when owned, 409 banner), fixtures carry `ownedByCaller`
- Verification evidence: `pytest tests/test_agents` → 885 passed (+6 backfill = 891); full `npx jest` → 92 suites / 1045 passed; `tsc --noEmit` clean in touched files
- Commit/PR (on `feat/agentscatalog`): `COMMIT-ce80668a` (store + record), `COMMIT-de6246ae` (authorization + cards), `COMMIT-25fba5a8` (backfill tool), `COMMIT-6b78a482` + `COMMIT-ce7cdc63` (frontend + fixture); docs commit follows
- Follow-up work: materialize published bytes into installers' stores so Hub installs survive unpublish (now safe — installers' copies cannot make them owners); optional publisher display name on Global rows (needs a privacy decision first).
