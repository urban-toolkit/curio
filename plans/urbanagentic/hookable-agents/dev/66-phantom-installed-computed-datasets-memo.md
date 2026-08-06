# Dev/66 — Phantom "installed" computed datasets: disk-existence marker + un-namespaced execution saves

Implementation memo for the 2026-08-06 bug report: the trash icon on the Data Catalog
drawer's Installed tab fails with `DELETE /api/dataflows/<id>/datasets/computed.niteroi-join
→ 404 (NOT FOUND)`, and the dataset is "considered installed although it is not installed".

Two fixes:

1. **Fix 1 — remove the disk-existence install marker** (`_mark_user_store_computed_installs`):
   `installed` must derive only from the dataflow's spec refs.
2. **Fix 2 — stop minting un-namespaced computed dirs on execution**: `auto_install_node_output`
   skips (with a clear diagnostic) when no `dataflow_id` accompanies the execution.

---

## 1. Problem Statement

### Observed behavior

With a dataflow whose spec contains **no** `dataflow.datasets` section (verified on disk:
`.curio/users/guest/projects/fefb7f58…/spec.trill.json` has no refs; the canvas DATASETS
panel correctly shows "0 installed"), the drawer's Installed tab still lists "JS
Computation" as installed. Its trash (Remove/uninstall) icon calls
`DELETE /api/dataflows/<id>/datasets/computed.niteroi-join`, and the backend correctly
404s ("Dataset is not installed in this dataflow") because no ref exists. The user cannot
remove the row, and the drawer contradicts both the palette and the persisted spec.

### Root cause A — the phantom `installed` flag

`_mark_user_store_computed_installs` (`backend/app/datasets/application/paths.py:68-113`,
called from `application/listing.py:156-169`) stamps `installed: True` on any computed
catalog row whose producer has a **legacy un-namespaced store dir** on disk
(`computed.<sanitizedNode>@1`) — without ever consulting the open dataflow's refs.

The marker is a leftover bridge from the old auto-install model, where execution
auto-installed computed outputs into the project and a store dir genuinely implied
installation (it covered the window before the next save synced spec refs). Under the
current model — computed outputs are **account-level assets saved on execution, installed
into a project only by explicit user action** (see `user_store.py` module docstring and
`listing.py:112-115` "as available, not installed") — every saved computed output has a
store dir, so "dir exists ⇒ installed" is categorically wrong. It only fires for
un-namespaced dirs because the probe builds the legacy dir name; namespaced dirs
(`computed.<dataflow>.<node>@1`) never match, which is why only some datasets show the
phantom state.

### Root cause B — un-namespaced dirs are still being minted

The offending dir `.curio/users/guest/datasets/computed.niteroi-join@1` was created
**today** (manifest `createdAt: 2026-08-06T15:49:23Z`, `producerNodeId: "niteroi-join"`,
`producerDataflowId: null`). The path that mints it:

- `CodeEditor.tsx:217` passes `projectId` as `dataflowId` to the interpreter — `null` for
  a never-saved dataflow, so the execution request omits it
  (`JavaScriptInterpreter.ts:45`, same for Python).
- `/processPythonCode` / `/processJavaScriptCode` (`api/routes.py:424`, `:524`) forward
  `dataflowId=None` to `auto_install_node_output` (`application/auto_install.py:47`),
  which calls `install_node_output` → `install_computed_file_for_node` →
  `computed_dataset_id(node_id, None)` → legacy fallback `computed.<node>` (`installer.py:129-141`).

Consequences of each un-namespaced dir: it collides across dataflows that reuse the node
id (the "collapsed installations" symptom), the id migration cannot repair it
(`migrations.py` is best-effort and skips dirs it cannot attribute — `producerDataflowId`
is null), and — until Fix 1 lands — it triggers the phantom-installed marker.

### Why it matters

Correctness (the drawer shows installs that do not exist; the only offered action 404s),
cross-surface consistency (drawer vs. palette vs. spec disagree), and data hygiene (new
legacy-format dirs keep being created two years after namespacing was introduced,
re-poisoning the catalog each time).

---

## 2. Scope

### In scope

Backend only — no frontend changes are required:

- `backend/app/datasets/application/paths.py` — delete `_mark_user_store_computed_installs`.
- `backend/app/datasets/application/listing.py` — delete its call site (`:156-169`) and the
  stale "Post-execution auto-install … before the next project save syncs spec refs"
  comment; drop imports that become unused.
- `backend/app/datasets/application/auto_install.py` — skip when `dataflow_id` is missing.
- Backend tests (see §7).

### Out of scope (intentionally)

- Existing legacy dirs (e.g. `computed.niteroi-join@1`): after Fix 1 they list as
  *available* account-level computed datasets — truthful state — and can be removed with
  the card's account-level Delete. No data migration: `migrate_computed_dataset_ids`
  already namespaces every dir it can attribute, and un-attributable dirs keep working by
  design.
- The `computed_dataset_id` legacy fallback itself: still needed by id *parsers* and
  read-side callers that tolerate both forms. Only the execution-time *writer* stops
  using it (it no longer gets a null dataflow id past `auto_install_node_output`).
- `install_computed_file` (deprecated content-hash naming) and the explicit-install path
  in `mutations.py` (always has a `dataflow_id` — the route requires one).
- The frontend execution call sites: `CodeEditor` already passes `projectId` when it
  exists; the unsaved-project case is handled by the save-time installer (below).
- dev/65 Fixes 2–3 (ref ownership, install-replace) — separate workstream.

---

## 3. Recommended Implementation Approach

### Fix 1 — delete the marker; refs are the only source of `installed`

Remove `_mark_user_store_computed_installs` and its `listing.py` call. The listing already
derives `installed` from the authoritative sources immediately above the call site
(`listing.py:140-154`): spec-ref ids (`installed_ids`) and, for computed rows, a
producer-match against **installed refs** (`installed_computed_filenames`) — including the
`needsReinstall` filename comparison. Nothing else needs to move: the marker's other side
effects (rewriting `dirName`/`path`/`uri`/`loaderSnippet` onto live rows) are only
meaningful when its phantom install fires; genuinely installed rows get those fields from
the installed repository, and account-store rows from their manifests.

This follows the repo convention (fix primary paths, no compensating fallbacks) and makes
`listing.py`'s own newer comment ("surface them … as available, not installed") true.

### Fix 2 — execution auto-save requires a dataflow id

In `auto_install_node_output`, before resolving the artifact: if `dataflow_id` is falsy,
return the `skipped` diagnostic with a reason that names the real condition (e.g.
"dataflow not saved yet — the dataset is saved on the first project save"). Loud and
observable: the routes already print the reason, and the response carries
`datasetDiagnostic` to the client.

No dataset is lost by skipping: the frontend already persists the project after a
producing node runs without an `installedDataset` payload
(`useWorkflowOperations.ts:827-839`), and the save-time installer
(`_auto_install_computed_outputs`, `projects/services.py:172`) runs with
`dataflow_id=project_id` — producing the correctly **namespaced** dir. The net effect of
Fix 2 is that the one writer that could still mint `computed.<node>@1` no longer does.

---

## 4. Data and State Handling

- **Source of truth for `installed`:** the open dataflow's `spec.dataflow.datasets` refs,
  exclusively (`installed.list_items` / `installed_ids` / producer-matched refs). Disk
  state (store dirs) means "exists in the account catalog", never "installed".
- **Computed dataset identity:** always dataflow-namespaced at write time on every
  remaining execution/save path; the legacy form remains read-only compatibility.
- **Derived UI state:** the drawer's Installed tab and palette counts already key off the
  `installed` flag — they become consistent with the spec automatically once the flag is
  truthful. No frontend state changes.
- **After Fix 2's skip:** execution returns `installedDataset: null` + a skipped
  diagnostic; the client save path persists the project and the dataset appears (as
  available) after that save's catalog refresh — the same flow raster/raw outputs use
  today. No race: the save-time installer is idempotent per node dir.

---

## 5. UI and UX Requirements

- The Installed tab lists exactly the datasets with refs in the open dataflow — matching
  the palette's "Installed datasets" count and the saved spec.
- An account-level computed dataset with no ref appears under Browse/Computed as
  available (Install button), not with Uninstall/trash.
- The trash icon on Installed rows never produces a 404 in normal operation: every listed
  row corresponds to a deletable ref.
- Executing a node in a never-saved dataflow still ends with the dataset visible in the
  catalog after the automatic first save — no new user steps, no error toast for the
  skip (it is a normal, transient condition).
- No layout, labeling, or accessibility changes — this is purely a data-truthfulness fix.

---

## 6. Edge Cases

1. **Legacy dir exists for a producer that IS genuinely installed** (ref present): row
   stays installed via `installed_ids`/producer-match — no behavior change; uninstall
   removes the ref and the row leaves the Installed tab.
2. **Legacy dir exists, no ref anywhere** (this bug): row lists as available; Uninstall is
   no longer offered; account-level Delete works.
3. **Execution in a saved dataflow:** unchanged — namespaced dir, `installed` diagnostic,
   `installedDataset` payload.
4. **Execution in a never-saved dataflow:** skipped diagnostic with the new reason; first
   project save installs the namespaced dataset from output refs; catalog refresh shows it.
5. **Execution with `saveOutputDataset` off:** unchanged (auto-install not attempted).
6. **needsReinstall:** still computed for genuinely installed producer-matched rows
   (`listing.py:147-154`); the marker's duplicate branch disappears with it.
7. **Two dataflows reusing a node id:** both save namespaced dirs — no collision; neither
   marks the other installed.
8. **Old clients/specs:** id parsers (`node_segment_from_computed_id`,
   `display_folder_name`) still accept legacy ids; nothing breaks on read.

---

## 7. Testing Strategy

Backend (pytest, `backend/tests/test_datasets/`):

- **Regression (Fix 1):** create a legacy un-namespaced store dir
  (`computed.<node>@1`, manifest with `producerNodeId`, no `producerDataflowId`) for a
  user; list the catalog with a dataflow that has **no** refs → the row's `installed` is
  falsy; it does not satisfy an Installed-tab filter. (Encodes the exact reported bug.)
- **Ref-derived install still works:** explicit install → row `installed: true`;
  uninstall → flag clears (existing suites `test_computed_catalog_api.py`,
  `test_computed_uninstall_and_delete.py` already cover; verify they pass unchanged).
- **Fix 2 skip:** POST `/processPythonCode` with `saveOutputDataset: true` and **no**
  `dataflowId` → `installedDataset` is `None`, diagnostic `skipped` with the
  dataflow-not-saved reason, and no `computed.<node>@1` dir is created in the user store.
- **Fix 2 non-regression:** existing `test_execution_dataset_persistence.py` tests (all
  pass a `project_id`) still produce namespaced installs.

Required before completion: the two new tests above plus a green run of the existing
dataset test suites.

---

## 8. Acceptance Criteria

1. With no refs in the open dataflow's spec, the catalog listing returns no
   `installed: true` computed rows — drawer Installed tab, palette count, and spec agree.
2. The reported repro is gone: a legacy account-store computed dataset shows as available
   (Install/Delete), never with a trash/Uninstall action that 404s.
3. Node execution without a saved dataflow creates **no** un-namespaced
   `computed.<node>@1` dir and returns a `skipped` diagnostic naming the reason; after the
   automatic first save the dataset exists under `computed.<dataflow>.<node>@1`.
4. Node execution in a saved dataflow behaves exactly as before (namespaced dir,
   `installed` diagnostic, dataset payload).
5. `_mark_user_store_computed_installs` no longer exists; no other code path sets
   `installed` from disk existence.
6. All existing dataset suites pass; the two new regression tests pass.

---

## 9. Recommended Commit Breakdown

Single commit — the two fixes are one causal chain (the marker misfires *because*
un-namespaced dirs exist) and individually small:

- Remove `_mark_user_store_computed_installs` + call site + stale comment (Fix 1).
- Add the missing-`dataflow_id` skip to `auto_install_node_output` (Fix 2).
- Add both regression tests.

If review prefers separation: Commit 1 = Fix 1 + its test; Commit 2 = Fix 2 + its test.

---

## 10. Engineering Quality Checklist

- [ ] No duplicated "is installed" logic remains — refs are the single source.
- [ ] No new fallbacks introduced; the skip is loud (diagnostic + route log), not silent.
- [ ] Unused imports removed from `listing.py`/`paths.py` after the deletion.
- [ ] Behavior preserved for genuinely installed datasets, `needsReinstall`, sink-node
      skips, and `saveOutputDataset: false`.
- [ ] Tests encode the reported symptom (phantom install) and the writer-side cause
      (un-namespaced dir), not just the mechanism.
- [ ] Follows existing conventions: diagnostics via `_diagnostic`, best-effort migration
      untouched, read-side legacy-id tolerance untouched.
