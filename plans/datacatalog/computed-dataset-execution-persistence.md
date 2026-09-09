# Implementation Memo: Persist JSON (dict/list/scalar) computed datasets on execution + stop silent skips

**Status:** Proposed (memo only — no code written) · **Branch:** `datacatalog` · **Author:** Karla
**Area:** `backend/app/datasets/auto_install.py`, `backend/app/api/routes.py` (execution response), `backend/app/datasets/bundle.py` (`install_node_output`), the execution-result handling in the frontend (`datasetCatalogApi.applyInstalledDatasetToProject`), + tests

---

## 1. Problem Statement

**Current behavior.** Running a dataflow does **not** generate computed datasets for nodes whose
output is a `dict`/`list`/scalar (JSON), and it fails **silently** — no error, warning, or
diagnostic. Affected projects are the Autark "what-if" dataflows whose `autk-grammar` nodes emit
Autark grammar specs (`data_type: list` / `dict`), e.g. `whatif-data`,
`whatif-baseline-compute`, `whatif-modified-compute`, `whatif-*-map`. After execution the Data
Catalog / dataset list shows no computed outputs for these nodes; they only appear after a
separate **project save**, and projects executed-but-not-saved (`02fc08b8`, `2f84bb64`,
`6df85d49`) show nothing at all.

**Root cause.** The pipeline has **two persistence paths that disagree**:

- **Post-execution auto-install** — `auto_install_node_output()`
  (`utk_curio/backend/app/datasets/auto_install.py:8-92`), called per node after the sandbox runs
  (`utk_curio/backend/app/api/routes.py:443-451` and the JS twin). It installs **only**:
  - `output['dataset']` — a parquet that `save_dataset_parquet()` writes **only** for
    `dataframe`/`geodataframe` (`utk_curio/sandbox/app/worker.py:266-271`), or
  - a tuple **bundle** (`dataType == "outputs"`).

  For any other output, `path_ref` is empty and it does `return None` **silently**
  (`auto_install.py:34-40`). All install exceptions are swallowed (`except Exception: pass` at
  `:86-87` and `return None` at `:90-91`). The execution route only logs on **success**
  (`routes.py:452-457`), so a skip/failure is invisible and the response carries
  `installedDataset: null` (`routes.py:464`).

- **Project-save auto-install** — `_auto_install_computed_outputs()`
  (`utk_curio/backend/app/projects/services.py:118-209`). It installs from the recorded output
  refs by `filename` + `data_type` via `install_node_output()`, which **does** handle
  `dict`/`list`/scalar as JSON (`SANDBOX_DATATYPE_TO_FORMAT` in
  `utk_curio/backend/app/datasets/constants.py`), and it **logs** failures
  (`services.py:158`).

So dataframe pipelines (e.g. the Vega/transform project `2b8af75a`, `data_type: dataframe`)
persist on execution, while JSON-producing Autark pipelines do not — they are silently deferred
to save time, and never surface if no save happens.

**Expected behavior.**
- Executing the dataflow generates and persists computed datasets for **all** dataset-producing
  nodes — including JSON (`dict`/`list`/scalar) outputs — immediately, without a manual save.
- A node that does **not** produce a persistable dataset surfaces a clear, per-node diagnostic
  (status + reason), never a silent no-op.
- Install failures are logged with node/output context, not swallowed.

**Why it matters.** Silent, type-dependent persistence makes Autark/JSON dataflows look broken,
breaks "outputs appear immediately after execution," and leaves no trail to debug. The
execution and save paths must agree on what counts as a computed dataset.

---

## 2. Scope

**In scope**
- `auto_install.py::auto_install_node_output` — install JSON-mappable outputs on execution
  (parity with the save path); stop swallowing skips/errors; return a structured result.
- `bundle.py::install_node_output` — reuse it for the non-bundle JSON case (already does
  `resolve_shared_output_path` + `install_computed_file_for_node`); confirm `data_type` →
  format mapping covers `dict`/`list`/scalars.
- `routes.py` (`process_python_code` + `process_javascript_code`) — surface a per-node
  `datasetDiagnostic` in the response alongside `installedDataset`; log skips/failures.
- Frontend execution-result handling (`datasetCatalogApi.applyInstalledDatasetToProject` and its
  caller) — apply the installed dataset / show the diagnostic so the list updates immediately
  and missing outputs are explained.
- Tests (see §7).

**Out of scope / must not regress**
- The DataFrame/GeoDataFrame + tuple-bundle path (already works on execution) — keep behavior.
- The dedup guard: do **not** turn a node's raw **shared intermediate** artifact
  (`output['path']`) into a duplicate dataset (the explicit warning at `auto_install.py:30-33`).
  Persisting JSON outputs must stay keyed on `nodeId` + the node's own output file, the same
  basis the save path uses, so two nodes sharing an artifact don't create twins.
- Sink/viz pruning (`vis-vega`/`vis-simple`) in `services.py::_prune_sink_node_dataset_refs` —
  still prune those even if installed on execution.
- The save-path installer `_auto_install_computed_outputs` — leave as the source of truth for
  recorded refs; this change makes execution **match** it, not replace it.
- The "save node output" toggle semantics (`CURIO_DEFAULT_SAVE_NODE_OUTPUT`, `saveOutputDataset`).

---

## 3. Recommended Implementation Approach

**A. Unify execution-time persistence with the save path (the core fix).**
In `auto_install_node_output`, when there is no `output['dataset']` and it is not a bundle,
fall back to installing the node's **own** output artifact as the format implied by `data_type`,
instead of `return None`:
- Resolve the install via the existing `install_node_output(user_key, node_id=…,
  path_ref=<node output file>, data_type=…, node_name=…)` — the same call the save path uses, so
  JSON (`dict`/`list`/`str`/`int`/`float`/`bool`/`null`) maps to a `json` computed dataset and
  rasters/tabular keep their formats.
- Use the sandbox output's **own** file reference for `path_ref` (the per-node output the save
  path records), keyed on `nodeId`, so the dedup concern in `auto_install.py:30-33` is respected
  — we are not promoting a shared upstream artifact, we are installing this node's output under
  `computed.<nodeId>@1`, exactly as `_auto_install_computed_outputs` does.
- Skip genuinely non-persistable cases deliberately (e.g. `data_type` absent / not in
  `SANDBOX_DATATYPE_TO_FORMAT`, or a sink/viz node) and report them as a **diagnostic**, not a
  silent `None`.

**B. Stop swallowing failures.** Replace `except Exception: pass` (`:86-87`) and the outer
silent `return None` (`:90-91`) with `logger.exception("auto-install failed for node %s
(type=%s, ref=%r)", node_id, data_type, path_ref)` and return a structured failure result.

**C. Structured result + diagnostics.** Have `auto_install_node_output` return a small result
object (or `(installed, diagnostic)`), e.g.
`{status: "installed"|"skipped"|"failed", reason?, nodeId, dataType}`. `routes.py` returns it as
`datasetDiagnostic` next to `installedDataset`, and logs skipped/failed cases (today only success
is logged). The frontend applies `installedDataset` (immediate list update) and, when
`status != "installed"`, shows the reason on the node / in a toast.

**D. Keep the two paths consistent.** Factor the "should this output become a computed dataset,
and as what format?" decision into one helper shared by `auto_install_node_output` and
`_auto_install_computed_outputs` so execution and save can never diverge again.

---

## 4. Data and State Handling

- **Source of truth for "is this a dataset / what format":** `SANDBOX_DATATYPE_TO_FORMAT`
  (`constants.py`) + `computed_output_format()`; centralize the gate (Approach D).
- **Install target:** `computed.<sanitizedNodeId>@1/` via `install_node_output` →
  `install_computed_file_for_node`; ref merged into the spec by
  `project_storage.merge_dataflow_dataset_ref` (`auto_install.py:73-87`) so the project state
  reflects it without a manual save. This also makes `producerNodeId` persist on execution —
  consistent with the reinstall/producer work in
  [`dataset-details-lineage-single-hop.md`](./dataset-details-lineage-single-hop.md) and the
  producer-preservation change.
- **Loading/empty/error:** a node that produced no output dict, or a non-persistable type,
  yields `status:"skipped"` with a reason; an install exception yields `status:"failed"` (logged)
  — neither blocks the rest of the run.
- **No stale/dupes:** install keyed on `nodeId` (stable across re-runs; replaces the same
  `computed.<node>@1` dir), so repeated executions don't create duplicates and the existing
  `needsReinstall`/filename-diff logic still applies.

---

## 5. UI and UX Requirements

- Computed datasets for JSON-producing nodes appear in the Data Catalog / dataset list /
  palette **immediately after execution**, without a save (same as dataframe nodes today).
- A node that produces no dataset shows a clear reason (e.g. "Output type `dict` saved as JSON
  dataset" on success; or "No persistable output (type `unknown`)" / "Install failed — see
  logs" on skip/fail) rather than completing silently.
- No duplicate palette/card entries for nodes that share an intermediate artifact.
- Upstream connection badge stays correct (producer link persists on execution) — consistent
  with the lineage/badge work already on this branch.

---

## 6. Edge Cases

- **Tuple / bundle outputs** (`dataType=="outputs"`): unchanged path; still install via bundle.
- **`None`/`null` output**: persist as a `json` `null` dataset only if that's the intended
  contract; otherwise `status:"skipped"` with reason — decide explicitly, don't silently drop.
- **Unsupported / `unknown` type**: `status:"skipped"`, reason recorded; never a silent `None`.
- **Sink/viz nodes** (`vis-vega`/`vis-simple`): may install then get pruned by
  `_prune_sink_node_dataset_refs`; ensure the diagnostic reflects "pruned (sink node)" rather
  than "installed" so the UI isn't misleading.
- **Data-pool passthrough**: produces no own output → `status:"skipped"` (expected), not an
  error.
- **Shared intermediate artifact referenced by two nodes**: must not create twin datasets —
  install keyed on `nodeId` + own output file (respect `auto_install.py:30-33`).
- **Missing `dataflowId`**: still install into the user store; the spec-ref merge is best-effort
  (already guarded) — surface a diagnostic if the ref couldn't be merged.
- **Repeated runs**: re-execution replaces `computed.<node>@1`; `needsReinstall`/filename-diff
  semantics preserved.
- **Serialization failure** (e.g. non-JSON-serializable dict): caught, logged with node context,
  `status:"failed"` — the run continues.

---

## 7. Testing Strategy

**Backend (pytest, near `tests/test_datasets/test_computed_catalog_api.py`)**
- Execute a node returning a `dict` (and a `list`) → `auto_install_node_output` installs a `json`
  computed dataset; the route response carries `installedDataset` + `datasetDiagnostic.status ==
  "installed"`; the dataset is listed for the dataflow **without a save**.
- Execute a node returning a `DataFrame` → unchanged (regression): still installs parquet.
- Execute a node returning a scalar / `None` / unsupported type → `status:"skipped"` with a
  reason; no dataset; **no exception**.
- Force an install exception (e.g. unwritable store / bad path) → `status:"failed"`, error
  **logged** (assert via `caplog`), run continues.
- Two nodes sharing one intermediate artifact → no duplicate datasets.
- Sink/viz node output → installed-then-pruned reflected in the diagnostic.

**Frontend**
- Execution result with `installedDataset` updates the dataset list immediately
  (`applyInstalledDatasetToProject`).
- `datasetDiagnostic.status` of `skipped`/`failed` surfaces a node message/toast.

**Integration/regression**
- Reproduce the Autark what-if dataflow (dict/list nodes) → computed datasets appear after
  execution; confirm `producerNodeId` persisted.

---

## 8. Acceptance Criteria

1. Executing an Autark what-if dataflow generates and lists computed datasets for the
   `dict`/`list`-producing `autk-grammar` nodes **immediately, without a manual save**.
2. DataFrame/GeoDataFrame and tuple-bundle nodes behave exactly as before (no regression).
3. A node that produces no persistable dataset returns a per-node diagnostic with a clear
   reason; nothing fails silently.
4. Every install failure is logged with `node_id` + `data_type` + reference; none are swallowed.
5. No duplicate datasets for nodes sharing an intermediate artifact; sink/viz outputs are
   pruned and the diagnostic says so.
6. `producerNodeId` is persisted on execution, so the upstream badge/lineage is correct without
   a save.
7. Execution and save paths use one shared "is-this-a-dataset / format" decision.

---

## 9. Recommended Commit Breakdown

1. **Shared gate + JSON install on execution.** Factor the "persistable? as what format?"
   decision into one helper; make `auto_install_node_output` install JSON-mappable outputs via
   `install_node_output` (parity with the save path); keep the shared-artifact dedup guard.
   Backend unit tests for dict/list/dataframe/scalar/unsupported.
2. **Diagnostics + no swallowing.** Replace silent `return None` / `except: pass` with logging
   and a structured `{status, reason, nodeId, dataType}` result; return it as `datasetDiagnostic`
   from both execution routes; tests asserting logs + diagnostic payloads.
3. **Frontend surfacing.** Apply `installedDataset` for immediate list update and show
   skipped/failed reasons on the node/toast; component tests.
4. **Regression.** End-to-end Autark what-if test (datasets appear post-execution,
   `producerNodeId` persisted).

---

## 10. Engineering Quality Checklist

- [ ] One shared persistability/format decision used by both execution and save paths.
- [ ] JSON (`dict`/`list`/scalar) outputs install on execution; dataframe/bundle unchanged.
- [ ] No silent `return None`; skips/failures are logged and returned as diagnostics.
- [ ] Shared-intermediate-artifact dedup guard preserved (no twin datasets).
- [ ] Sink/viz pruning still applies; diagnostic reflects it.
- [ ] `producerNodeId` persisted on execution (consistent with the lineage/badge work).
- [ ] Best-effort spec-ref merge still non-fatal; surfaced when it can't merge.
- [ ] Tests cover dict/list/dataframe/scalar/unsupported/failure/duplicate/sink cases.
- [ ] No new unnecessary re-renders or list flicker when applying the installed dataset.
