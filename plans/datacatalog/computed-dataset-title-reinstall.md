# Implementation Memo: Preserve the producing-node title for computed datasets across publish → uninstall → reinstall

> Status: **memo only — implementation deferred.** Decided approach: frontend sends the resolved node label as `nodeTitle` on (re)install; backend falls back to preserved manifest name, then `dirName`, never the raw filename.

## 1. Problem Statement

**Current behavior.** Commit `526493a` titles a computed dataset by its producing node's display label: the frontend resolves the label (`resolveNodeDisplayLabel`) and threads it as `nodeName` → `/processPythonCode|/processJavaScriptCode` → `auto_install_node_output` → `install_node_output` → `manifest.name`. This works on the **first** auto-install.

It breaks on **publish → uninstall → reinstall**:

- On uninstall the local manifest is removed; the dataset still appears as a **session/live output** synthesized by `ComputedDatasetIndexer`, which sets `title = title_from_filename(raw)` and `fileName = title_from_filename(raw)` (`computed_indexer.py:58–62`) — the raw filename in *both* fields.
- When the user reinstalls that item, `install_dataset` passes `title=item.get("title")` into `install_node_output` (`catalog_mutations.py:332,349`). That title is the **filename**, so the rebuilt manifest is titled with the filename — the regression `526493a` set out to fix.

**Frontend workaround that broke tests.** Commit `5f8ed55` changed `datasetDisplayTitle`'s guard from `if (!title || isGeneratedFilename)` to `if (!title || isComputed)` (`datasetCatalogTypes.ts:239`), forcing **every** computed dataset to render `dirName` (`computed.<nodeId>@1`), discarding genuinely-captured node titles and leaving `isGeneratedFilename` dead. It broke the unit test "computed datasets show the producing node's name (title), not the filename".

**Why `dirName` is not the answer.** `dirName` is `computed.<sanitizedNodeId>@1` — an id-encoded folder, not a human name.

**Desired behavior.**
- Title = producing node's display label whenever resolvable — including after reinstall.
- If genuinely unavailable, fall back to `dirName` (never the raw filename).
- Filename appears only as the subtitle, with `.json`/`.Json` stripped.

**Answer to the lineage question.** Lineage (`resolve_dataset_producer`) yields `nodeType`; `dirName` yields the node *id* — neither is a human name. The display name is the node-*type's label*, whose registry (`nodeRegistry`/`resolveNodeDisplayLabel`) lives only in the frontend. So the robust title source on reinstall is the frontend resolving the label and passing it in, with backend fallbacks.

## 2. Scope

**In scope:** backend reinstall title resolution (`services/catalog_mutations.py`, `routes.py` install route), title fallback in `bundle.install_node_output`/`installer.install_computed_file_for_node`, frontend install call sites (`datasetCatalogApi` + palette/catalog drawer/detail callers), `datasetDisplayTitle` guard restore + `datasetSubtitle` extension stripping, tests (`datasetCatalog.test.ts`, `test_computed_catalog_api.py`).

**Out of scope:** auto-install (first execution) path, provenance labels, lineage badge logic, bundle preview, install-state syncing, `producerNodeId` recovery (done in `3cb3e14`).

## 3. Recommended Implementation Approach (decided)

1. Frontend computes the node label from `producerNodeType` (reuse `resolveNodeDisplayLabel({ nodeType: producerNodeType })`) and includes it on the install request as `nodeTitle` (alongside `sourceItem`).
2. Backend `install_dataset` resolves the title with strict precedence, never the session filename:
   1. explicit `nodeTitle` (non-blank, not equal to `fileName`);
   2. preserved on-disk manifest name if a prior manifest exists and isn't the filename;
   3. `dirName`.
   Pass the resolved title into `install_node_output(..., node_name=resolved_title)`.
3. Centralize precedence in one helper (`_resolve_computed_install_title(item, node_title)` in `catalog_mutations.py`) used by both the single-file and bundle branches.
4. Frontend display: restore `datasetDisplayTitle`'s guard to `isGeneratedFilename`; keep the `isDatasetComputed` helper. Add `stripDataFileExtension(name)` (case-insensitive `.json` only) and route `datasetSubtitle`'s computed branch through it.

## 4. Data and State Handling

- Source of truth: producing node's label, resolved frontend-side, persisted to `manifest.name`. `fileName` always holds the generated filename.
- Display title/subtitle are pure functions of `{origin, title, dirName, fileName}`.
- Reinstall: request carries `nodeTitle`; backend applies precedence; persisted ref keeps `title` = resolved label, `origin="computed"`, `producerNodeId`.
- Synchronous resolution from data already on the item (`producerNodeType`) — no extra fetch, no reload, no flicker, deterministic (race-safe).

## 5. UI and UX Requirements

- Palette, browse card, browse drawer, detail panel show the node label (via `datasetDisplayTitle`).
- Subtitle shows filename without `.json`/`.Json`.
- No layout shift or reload on reinstall; row replaced in place.
- Title stays the primary heading; subtitle stays secondary text.

## 6. Edge Cases

- Node deleted everywhere → preserved manifest name, else `dirName`.
- `producerNodeType` missing → no `nodeTitle`; backend uses manifest name / `dirName`.
- `title === fileName` → display falls back to `dirName`.
- Blank/whitespace title → `dirName`.
- Bundle (`outputs`) reinstall → same precedence via shared helper.
- Filename without extension / uppercase `.Json` → subtitle strips case-insensitively.
- Legacy items with no `fileName` → subtitle omitted; title still correct.
- Imported/hub datasets unaffected.

## 7. Testing Strategy

**Frontend (`datasetCatalog.test.ts`):** computed w/ captured node name → title (currently failing); `title===fileName` → `dirName`; blank → `dirName`; imported/hub → real title; `datasetSubtitle` strips extension (update `"...Ef610Da8.Json"` → `"...Ef610Da8"`); `stripDataFileExtension` unit cases.

**Backend (`test_computed_catalog_api.py`):** publish→uninstall→reinstall with `nodeTitle` ⇒ manifest name == label, `fileName` == filename; reinstall with preserved manifest only ⇒ name retained; reinstall with neither ⇒ `dirName`, never filename; bundle mirrors single-file.

## 8. Acceptance Criteria

- After publish→uninstall→reinstall the title is the node label across manifest + all four UI surfaces.
- Raw filename never the title; only subtitle, without `.json`/`.Json`.
- Unavailable label → `dirName`, never filename.
- Failing test passes; new reinstall + subtitle tests pass; suite green.
- No change to imported/hub titles, provenance labels, lineage badges, install-state syncing.

## 9. Recommended Commit Breakdown

1. Frontend display fix + tests (restore `isGeneratedFilename`, add `stripDataFileExtension`, route `datasetSubtitle`, update tests) — makes the suite green.
2. Backend reinstall title resolution (`_resolve_computed_install_title` precedence helper; both branches; prefer preserved manifest over filename; backend tests).
3. Frontend sends resolved `nodeTitle` on (re)install (resolve from `producerNodeType`; wire route + service param).
4. Cleanup/regression (dead code, docs).

> Commit 1 alone makes tests green but reinstalled session items still display `dirName` (title===fileName). Commits 2–3 restore the node name after reinstall.

## 10. Engineering Quality Checklist

- One title-resolution helper (backend), one display/subtitle helper + one extension util (frontend) — no duplicated logic.
- Explicit types (`nodeTitle?: string`).
- Components render-only; resolution centralized.
- Deterministic, no added async/races; in-place row replacement.
- Unresolved producer degrades to `dirName`, never filename or crash.
- Tests cover regression + `526493a` intent + edge cases.