# Implementation Memo: Project-Agent-Default Cogs (P3 remainder)

Date: 2026-07-22
Status: **implemented** (2026-07-22; `BL-P3-20260722-08` — commits `7942c5e`/`3a6c2d9`/`120cdc1`)
Feature slice: P3 — catalog/install (`BL-P3` continuation; the last open P3 item in `3.1`)
Design sources: memo `11` (labeled cog entry points; per-project defaults materialized at install), memo `12` (settings-modal applicability; installed-scope actions), `docs/01`/`02`/`04` (`Project agent settings` + `Uninstall from project` on installed cards; palette rows action-free), `docs/08` §scopes ("Project agent default — edits Cost, Quotas, and Resources for one installed project template"), `DEC-040` (FS-backed)

## 1. Problem Statement

The drawer's **Installed in this project** cards expose only `Uninstall`. The approved plan puts a labeled **`Project agent settings`** cog there — the entry point to the project-agent-default scope (one installed template's own Cost/Quotas/Resource defaults, independent per project per memo 11). Today:

- there is **no entry point** (the cog is the last unchecked P3 deliverable in the master log);
- there is **no per-project defaults record** — the lockfile (`spec.dataflow.agents`) is a bare coordinate list, so the upcoming Cost/Quotas/Resource screens would have nowhere to write;
- a user has **no visibility** into what policy currently governs an installed agent (the account-level runs/day quota from `dev/22` is invisible in the UI).

The six-screen settings shell itself is the next v1 slice; this slice delivers the entry points, the storage they scope to, and an honest read-only effective view — not the editors.

## 2. Scope

**Included**

- Backend: `app/agents/project_agents.py` (a backend-owned `dataflow.agentDefaults` spec section: materialize at install, drop at uninstall, preserve across saves), `app/agents/services.py` (install/uninstall wiring + `get_project_agent_defaults` with effective-quota resolution), `app/agents/routes.py` (`GET /api/agents/projects/<pid>/defaults/<coord>`), `docs/AGENTS.md`.
- Frontend: `AgentsCatalogDrawer` installed-scope card (labeled `Project agent settings` control beside `Uninstall`), new `components/agents/settings/ProjectAgentSettingsModal.tsx` (+ module CSS), `api/agentsApi.ts` (`getProjectAgentDefaults`).
- Tests in §7.

**Out of scope (unchanged)**

- Editing any value: the Cost/Quotas/Resource **screens** (with clamping, `Reset to agent default`, revisions/dirty-guards per memo 11) are the next slice; this modal is read-only.
- The account-scope `Agent settings` cog in the roster header (docs/02 §cogs) — separate entry point, same future shell; deferred to the settings-screens slice so both scopes land against real editors.
- Attachment-scope settings (`Attachment settings` in the chat), prompt governance screens (v2), palette rows (stay action-free per docs/02).
- No manifest changes; built-ins carry no `settingsDefaults`, which the record shape accommodates.

## 3. Recommended Implementation Approach

**Backend — a per-project defaults record, owned like the lockfile.**

1. `project_agents.py`:
   - `agent_defaults(spec) -> dict` — reads `spec["dataflow"]["agentDefaults"]` (`{coord: record}`; missing/malformed → `{}`).
   - `materialize_defaults(spec, coord, seed: dict | None) -> dict` — creates `{"revision": 1, "settings": seed or {}}` for the coord if absent (idempotent — reinstalling never resets an existing record, matching memo 11's "install materializes its **own** profile" without clobbering).
   - `drop_defaults(spec, coord)` — removes the record on uninstall (the profile is project-private state of the installation).
   - Add `"agentDefaults"` to `_AGENT_SPEC_KEYS` so `preserve_agent_state` carries it across canvas saves (the same clobber-protection attachments/lockfile already have).
2. `services.py`:
   - `install_in_project` materializes defaults (seed from the resolved manifest's `settings_defaults` when the contract exposes one; built-ins → empty) in the same spec write; `uninstall_from_project` drops them.
   - `get_project_agent_defaults(user_key, project_id, coord)` → `{coord, name, revision, settings, effective}` where `effective` is the v1 truth: `{"quotas": {"runsPerDay": {"value": quotas.runs_per_day_limit(), "usedToday": <current counter>, "source": "account"}}}` plus `{"cost": {"configured": false}, "resources": {"provider": <ProviderConfig.model/api_type summary — no secrets>, "source": "account"}}`. 404 when the coord isn't installed.
3. Route: `GET /api/agents/projects/<project_id>/defaults/<coord>` (auth + ownership like siblings).

**Frontend — labeled cog + read-only scope modal.**

4. Installed-scope card: a secondary `Project agent settings` button (cog icon + label, matching the card's existing `.btnSecondary` treatment) beside `Uninstall`. Global/My-Imports scopes are untouched.
5. `ProjectAgentSettingsModal` (reuse the app's `ModalShell`): scope banner ("Project agent default · <agent name>"), then three read-only sections mirroring the future screens — **Quotas** (runs/day effective value, used-today meter text, "Inherited from account"), **Cost** ("No project budget set — inherited account policy"), **Resource policy** (provider/model summary, "Inherited from account") — and a footnote that editing arrives with the settings screens. No Publish/Release/Share controls exist in this scope (memo 11/12 invariant).
6. `agentsApi.getProjectAgentDefaults(projectId, coord)`; the modal fetches on open, with loading/error states.

## 4. Data and State Handling

- **Source of truth**: the `agentDefaults` record in the project spec (backend-owned; written only by agent endpoints; preserved by `preserve_agent_state`; never serialized by the canvas save). Effective values are computed server-side at read time — nothing caches policy client-side.
- **Lifecycle**: created at install, kept across saves/reinstalls, deleted at uninstall. Cross-project isolation is inherent (the record lives in one project's spec).
- **Loading/error/empty**: modal shows a loading line, a retryable error, and renders the inherited-only view when `settings` is empty (the common case until the screens ship).
- **No stale UI**: opening the modal always fetches fresh (effective limits can change via env/deployment).

## 5. UI and UX Requirements

- The cog is **labeled** (`Project agent settings`, cog icon + text — memo 11 requires labeled entry points, not bare gear glyphs), keyboard reachable, `aria-haspopup="dialog"`.
- Modal: focus-trapped via the existing `ModalShell`, titled, Escape/close supported; scope identity always visible; values accompanied by their source ("Inherited from account") — memo 11's effective-value+provenance rule, applied read-only.
- Visual language: existing drawer/modal tokens; no new styling system.
- Installed cards keep `Uninstall` exactly as-is; no palette/roster/chat changes.

## 6. Edge Cases

- Installed coord whose definition can't resolve (store wiped): defaults endpoint still returns the record with `name` falling back to the coord; modal renders.
- Legacy projects installed before this slice: no record exists — `get_project_agent_defaults` materializes lazily on read (same idempotent helper) without writing unless absent, so old installs behave like new ones.
- Reinstall after uninstall: fresh empty record (uninstall dropped it) — matches template-profile lifecycle.
- Canvas save mid-flow: `preserve_agent_state` keeps the section (regression test).
- Quota file missing/corrupt: `usedToday` reads 0 (mirrors `dev/22` posture).
- Shared/read-only view: the drawer isn't mounted there; no new surface (rule 9 unaffected — records live in the spec's backend-owned section, which the share pipeline already excludes from agent-private exposure guarantees).

## 7. Testing Strategy

Backend (`tests/test_agents/`):
- `test_project_agents.py` additions (pure): materialize idempotency, drop on uninstall, malformed-spec tolerance, preserve-across-save carries `agentDefaults` (extend `test_preserve_agent_state.py`).
- `test_routes.py`: install → GET defaults returns record + effective quota (limit + usedToday after a run); uninstall → 404; not-installed coord → 404; lazy materialization for a pre-existing install (write the lockfile without a record, GET succeeds); reinstall does not reset revision.
- Regression: `TestSavePreservesAgentState` extended for the new section.

Frontend (`src/tests/`):
- `agentsApi.test.ts`: URL/verb for `getProjectAgentDefaults`.
- `AgentsCatalogDrawer.test.tsx`: installed scope shows the labeled cog; clicking opens the modal; Global/My-Imports scopes show none.
- `ProjectAgentSettingsModal.test.tsx` (new): loading → rendered effective values with "Inherited from account"; error + retry; close restores focus; no Publish/Release controls present.

## 8. Acceptance Criteria

- [ ] Every **Installed in this project** card shows a labeled `Project agent settings` control beside `Uninstall`; no other scope or surface gains controls.
- [ ] Opening it shows the project-agent-default scope with the real effective policy: the account runs/day limit and today's usage, provider summary, and explicit "Inherited from account" provenance — read-only, with no Publish/Release/Share.
- [ ] Installing materializes a per-project `agentDefaults` record (empty settings for built-ins); uninstalling removes it; canvas saves never wipe it; projects installed before this slice work via lazy materialization.
- [ ] The record is per-project: two projects with the same template hold independent records.
- [ ] All existing suites pass; drawer install/uninstall/publish flows unchanged.

## 9. Recommended Commit Breakdown

1. `feat(agents): per-project agentDefaults spec section — materialize/drop/preserve, with pure tests`.
2. `feat(agents): GET project agent defaults with effective quota/provider view + install/uninstall wiring, with route tests`.
3. `feat(agents): Project agent settings cog + read-only scope modal in the drawer, with component tests`.
4. Build-log entry `BL-P3-2026…-08` + `docs/AGENTS.md` alongside commit 2 or 3 (tracking rule 13).

## 10. Engineering Quality Checklist

- The defaults record reuses the lockfile's ownership pattern (backend-owned spec section + preserve step) — no new persistence mechanism.
- Effective-value computation lives server-side in one place; the modal displays, never derives.
- Idempotent materialization; explicit lifecycle (install→exists, uninstall→gone); isolation by construction.
- Read-only slice — no premature editing paths for the screens slice to fight with; `settings`/`revision` shape is exactly what those screens will PATCH.
- Labeled, accessible entry point per memo 11; no unrelated UI touched (`DEC-041`/`DEC-042` intact).
