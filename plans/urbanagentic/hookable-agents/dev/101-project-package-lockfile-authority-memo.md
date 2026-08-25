# Dev/101 — Project package lockfile authority: backend-owned `dataflow.packages`, truthful uninstall, one read truth

Date: 2026-08-24
Status: **IMPLEMENTED — 2026-08-24** (see the implementation record at the end)
Depends on: `822fba01` (per-project lockfile), `dev/81` (backend-owned `dataflow.datasets`), `preserve_agent_state` (backend-owned agent sections), `dev/89` (Package Builder promotion writes the lockfile)
Decision posture: no new decision ID. This extends an already-decided rule — backend-owned spec sections survive a client save — to the third such section, and fixes an uninstall that could not honestly report what it did.

## 1. Problem Statement

Reported: a package created and installed by the Package Builder agent (`curio.postits@1`) cannot be deleted from the node catalog drawer, and it does not appear in the packages palette; its node on the canvas paints "Loading node… curio.postits/post-it-note@1" forever.

Investigated state of the affected project (`guest`, dataflow `a9a1afc7…`):

- The package is healthy in the user store (manifest, integrity, source; installed 2026-08-21).
- The promotion journal shows the Package Builder's Apply **did** add it to the project lockfile (`lockfileAdded: True`, all five steps completed).
- The on-disk spec now has `dataflow.packages: []` and one node of type `curio.postits/post-it-note@1`. The lockfile was written by the promotion and later overwritten with an empty list.

Three defects combine:

**D1 — the canvas save clobbers the lockfile.** `projects/services.py::update_project` carries `dataflow.agents`/`agentAttachments` (`preserve_agent_state`) and `dataflow.datasets` (`preserve_dataset_refs`, dev/81) forward from the on-disk spec, but **not `dataflow.packages`**. Whatever list the client's `projectPackagesStore` holds is written verbatim on every save. Any save from a store that had not learned about the promotion's write (second tab, reload before the `package-nodes-created` mutation, an install-sync save ordering) replaces the lockfile with the stale list. This is the same defect class dev/81 closed for datasets.

**D2 — an empty lockfile is indistinguishable from a legacy one.** `spec_packages.project_packages()` returns the declared list only when it is *non-empty*; for `[]` it backfills from the node types on the canvas. So with `[]` on disk and a `curio.postits/…` node present, `GET /api/packages/projects/<id>` reports `["curio.postits@1"]` — the drawer shows **Installed 1** — and `uninstall_from_project` computes that same backfilled set, discards the package, writes `[]` (already `[]`), then `prune_unreferenced_packages` scans all projects with the same backfill, finds the node still references the package, and does not prune. Reload: backfilled again. **The delete is a permanent no-op with a success response.** While a node of that type exists on any canvas the package cannot be uninstalled, and the UI says nothing.

**D3 — the frontend reads the raw list, the backend reads the backfilled one.** `useWorkflowOperations.loadParsedTrill` seeds `projectPackagesStore` from the raw `spec.dataflow.packages` (`[]`); the palette (`packagesClient.loadInstalledPackages` filters by that set) shows **0**, and the descriptor registry never registers the postits template, so its node cannot resolve. The drawer, meanwhile, re-syncs the store from the backfilled route when opened (`NodeCatalogDrawer.tsx:123`), masking the disagreement intermittently. Two readers, two answers, from one file.

Expected behaviour: the project lockfile has one authority (the backend, on disk); a client save can neither drop nor resurrect a package; the list the frontend loads is the list the backend acts on; and uninstalling a package still used by canvas nodes is refused with a message naming the count, instead of silently doing nothing.

## 2. Scope

Included:

- `projects/services.py::update_project` — carry the on-disk `dataflow.packages` forward over the client's (the on-disk section is authoritative on update; the client's still seeds `save_project`/create).
- `packages/spec_packages.py` — a `preserve_project_packages(effective_spec, existing_spec)` helper (packages domain owns the rule; projects calls it, mirroring `preserve_dataset_refs`), and a `referencing_nodes(spec, dir_name, installed_majors)` helper for D2.
- `projects/services.py::load_project` (and the shared-project read) — normalise `spec.dataflow.packages` in the response to `sorted(get_project_lockfile(...))`, so the frontend loads the backend's truth. Persisting the normalised list happens on the next save via the preservation step (on-disk `[]` + referencing nodes → the preserved value is the backfilled set), so a stuck project heals on its next load-then-save with no manual edit.
- `packages/services.py::uninstall_from_project` — refuse (409) when the target project's canvas still holds nodes of the package's types: `"N node(s) on this canvas use <name> — delete them first"`. The store-level `DELETE /api/packages/<dir>` is unchanged (it is the "remove from my account" action, prune already guards it).
- Frontend: `NodeCatalogDrawer.onUninstall` already surfaces backend errors via `reportActionError`; verify the 409 text reaches the user. After the drawer's lockfile re-sync (`setCurrentProjectPackages(projLock.packages)`) call `refreshPackageRegistry()` so the palette and registry follow the store (the intermittent mask in D3 becomes a correct sync).
- Tests: backend unit + route; frontend hook test for the drawer sync.

Out of scope:

- Changing the backfill-on-empty rule itself. Every spec the frontend has ever saved carries `packages: []` by default (`TrillGenerator.generateTrill` defaults), so "empty means backfill" is load-bearing for every pre-lockfile project; retiring it would require a migration of every user's specs. D1 + the read normalisation remove the *disagreement*; D2's refusal removes the *lie*. Recorded as a possible later cleanup, not this memo's.
- Removing canvas nodes on uninstall. Refusing is the truthful, reversible choice; node deletion is the user's canvas action.
- Changing `save_project` (create) semantics, defaults seeding, the promotion flow, or any manifest/API schema.
- The `remove_packageage` store-level route and the prune rules.

## 3. Recommended Implementation Approach

### 3.1 Backend-owned lockfile on update (D1)

Add `spec_packages.preserve_project_packages(effective_spec, existing_spec) -> None`: if the on-disk spec has a `dataflow` dict, set `effective_spec["dataflow"]["packages"] = sorted(project_packages(existing_spec, installed_majors))` — i.e. the on-disk *effective* lockfile, backfill included, so a stuck `[]`-with-nodes spec becomes explicit on its first save after this change. If the on-disk spec has no `dataflow` (fresh/corrupt), leave the client's value. Call it in `update_project` next to `preserve_dataset_refs`, inside the spec lock, only when `data.spec is not None`.

The client-sent list remains the seed for `save_project` (create), exactly as datasets work.

### 3.2 One read truth (D3)

In `load_project` and the shared read, before `_to_detail`, set `spec["dataflow"]["packages"] = sorted(get_project_lockfile(ukey, project_id))` when the spec has a `dataflow` dict. Wrap in the existing `PackageServiceError`-tolerant pattern: a failure to compute leaves the raw list (never a 500 on load). This is a response-shape normalisation, not a schema change — the key already exists.

### 3.3 Truthful uninstall (D2)

In `uninstall_from_project`, before mutating: read the project's spec, compute `referencing = referencing_nodes(spec, dir_name, installed_majors)` (node ids whose `type` derives to `dir_name` via `dir_name_from_node_type`). If non-empty raise `PackageServiceError(f"{len(referencing)} node(s) on this canvas use {dir_name} — delete them first", 409)`. Otherwise proceed as today; the write now sticks because nothing backfills the package back.

### 3.4 Frontend follow-through

`NodeCatalogDrawer.reload`: after `setCurrentProjectPackages(projLock.packages)`, `await refreshPackageRegistry()` when the set actually changed. No other frontend change: the loader's `setPackages(incomingPackages)` now receives the normalised list from 3.2.

## 4. Data and State Handling

- Source of truth: `spec.trill.json → dataflow.packages` on disk, read through `get_project_lockfile` (backfill included). Writers: `install_to_project`, `uninstall_from_project`, promotion (via `install_to_project`), and — new — the preservation step on every canvas save, which can only re-assert the on-disk truth.
- `projectPackagesStore` is a mirror seeded from the normalised load response and corrected by drawer/agent actions; it is no longer authoritative on save.
- Loading/empty/error: a project with no packages loads `[]` explicitly; a legacy project with nodes but `[]` loads the backfilled list (and persists it on the next save). Read normalisation failure degrades to the raw list. Uninstall refusal is a 409 with a human message, surfaced by the drawer's existing error banner; the drawer state does not change.
- Races: preservation runs inside `spec_write_lock`, same as datasets; the promotion's `install_to_project` writes under the same lock; there is no window in which a client save can win over a server-side lockfile write.

## 5. UI and UX Requirements

- Palette count and rows match the drawer's Installed tab for the same project, immediately on load and after drawer install/uninstall.
- A node whose package is installed and enlisted never paints "Loading node…" after load.
- Drawer uninstall of a package with canvas nodes shows the refusal message in the existing error banner; the card stays "Installed". No confirm-then-silent-nothing.
- No layout, label, or accessibility changes; existing focus/keyboard behaviour of the drawer is unchanged.

## 6. Edge Cases

- On-disk `[]` with referencing nodes (the reported state) → load shows the backfilled list; next save persists it; uninstall refuses with the node count.
- On-disk `[]` with no referencing nodes → loads/saves `[]`; uninstall is a no-op 200 as today.
- On-disk spec missing `dataflow` → client value used on save (create-like); no preservation.
- Client sends packages the disk lacks (stale tab that installed elsewhere) → dropped; the client must install through the API, which writes the disk. Matches datasets semantics.
- Unversioned node types (`pkg/template`) resolve via installed majors for both backfill and refusal; a package not installed in the store cannot be derived → not counted, uninstall proceeds.
- Shared/foreign project read → normalised with the *owner's* key (already how `load` resolves the user dir); no writes.
- Concurrent promotion and canvas save → both under the spec lock; preservation re-reads inside the lock (`update_project` already re-reads `existing_spec` there).
- `get_project_lockfile` raising `PackageServiceError` (no spec) on read → keep raw list.

## 7. Testing Strategy

Backend:
1. `test_lockfile.py`: `preserve_project_packages` — disk wins over client; disk `[]`+nodes yields the backfilled explicit list; no-`dataflow` disk leaves client value. `referencing_nodes` — versioned/unversioned/none.
2. `test_projects/test_services.py`: **the regression** — install to project, then `update_project` with a spec carrying `packages: []` → lockfile still has the package (D1); load returns the normalised list (D3).
3. `test_lockfile.py::TestProjectInstallService`: uninstall with a referencing node → 409 with the count, lockfile and store unchanged; without nodes → unchanged behaviour (prune tests stay green).
4. Route test for `DELETE /api/packages/projects/<id>/<dir>` 409 body.

Frontend (jest, conda `curio-feat` node):
5. `NodeCatalogDrawer` test: reload with a project lockfile differing from the store triggers `refreshPackageRegistry` once.

Verification: backend `test_projects`, `test_packages`, `test_agents`; full backend suite; frontend suite for the touched test.

## 8. Acceptance Criteria

1. A canvas save can neither remove nor add entries to `dataflow.packages`; the on-disk lockfile survives a client save that carries `[]`.
2. `load_project` returns `spec.dataflow.packages` equal to the backend's effective lockfile for that project.
3. The palette and the drawer's Installed tab agree on the same set on load, with no drawer interaction required.
4. Uninstalling a package whose types are used by canvas nodes returns 409 with a message naming the node count; nothing on disk changes.
5. Uninstalling an unreferenced package still removes it from the lockfile and prunes as today.
6. The reported project heals without manual editing: load → palette shows Post-it Notes and its node resolves; delete → refusal naming 1 node; delete node → delete succeeds.
7. No schema, label, or accessibility change; all existing project/package/agent tests pass.

## 9. Recommended Commit Breakdown

- **Commit 1:** `spec_packages.preserve_project_packages` + `referencing_nodes` with unit tests; `update_project` calls the preservation (D1 regression test).
- **Commit 2:** read normalisation in `load_project`/shared read (D3) + uninstall refusal (D2) with service/route tests.
- **Commit 3:** frontend drawer registry refresh after lockfile sync + test; docs (this memo → IMPLEMENTED, Stage-3 entry).

## 10. Engineering Quality Checklist

- [ ] The lockfile rule lives once, in `spec_packages` (packages domain), called from projects — no duplicated backfill logic.
- [ ] Preservation runs inside the spec lock and re-reads disk there.
- [ ] Read normalisation never raises on load.
- [ ] Refusal message is specific (count + dirName) and reaches the drawer banner.
- [ ] Palette/registry follow the store after a drawer sync.
- [ ] Existing datasets/agents preservation untouched.
- [ ] Tests cover D1, D2, D3 and the healed-project path.

---

## Implementation record (2026-08-24) — status: **IMPLEMENTED**

| Commit | What |
| --- | --- |
| `6f372de4` | Commit 1 — `spec_packages.preserve_project_packages` + `referencing_nodes`; `update_project` carries the on-disk effective lockfile forward (D1). 11 tests incl. the clobber regression. |
| `3dcb9d07` | `_with_effective_packages` normalises `dataflow.packages` on `load_project` / `load_shared_project` when the key is already a list (D3); `uninstall_from_project` refuses with a 409 naming the node count while canvas nodes use the package (D2). 6 tests incl. the reported `[]`+nodes state and the route body. |
| (this commit) | `projectPackagesStore.applyProjectLockfile` (returns whether the set changed) + the drawer pulses `refreshPackageRegistry` on change; 4 jest tests; this record; `BL-P5-20260824-43`. |

Deviations from §3: none of substance. One narrowing worth recording: read normalisation applies only when `dataflow.packages` is already a list on disk — a spec without the key stays without it (the existing `test_metadata_only_update_preserves_spec_and_outputs` pins load ≡ saved for such specs, and adding a key the client never wrote would be a schema change by stealth). Every frontend-saved spec carries the key, so the reported class is covered.

Acceptance: AC-1 `test_client_save_cannot_clobber_the_project_lockfile` / `…cannot_add…`; AC-2/3 `test_load_serves_the_effective_lockfile_not_the_raw_list`; AC-4 `TestUninstallRefusesWhileNodesUseThePackage` (service ×3, route ×1); AC-5 the pre-existing prune tests, unchanged and green; AC-6 follows from 2+4+1 in sequence — load heals the palette/registry, delete is refused naming 1 node, deleting the node lets delete succeed, and the first save writes the explicit lockfile; AC-7 full backend suite green at each commit, frontend store test green, `tsc` clean on the touched files.

Healing the reported project needs no manual edit: open it (palette shows Post-it Notes, the node resolves), and the next canvas save writes `["curio.postits@1"]` to disk.
