# 69 — Data Loading node fails on Autark (autk-grammar) computed datasets (`.json.zlib`)

Status: implemented 2026-08-11 (branch `bug/datacalog`, changes left unstaged). Backend +
frontend `json` loader snippets are zlib-tolerant; backend/frontend generated Python
verified byte-identical; all backend `test_datasets` (169) and frontend
`datasetCatalog.test.ts` (48) tests pass.

## 1. Problem Statement

**Current behavior.** When a regular Autark node (`curio.builtin/autk-grammar`) runs, its
output — a UTK pool wrapper `dict` (e.g. `{"dataType": "outputs", "data": [{"dataType":
"geodataframe", ...}]}`) — is persisted by the sandbox as **zlib-compressed JSON** at
`.curio/data/artifacts/<id>.json.zlib` (`utk_curio/sandbox/util/parsers.py:545,571-581`,
`dict`/`list` branches of `save_to_duckdb` at `parsers.py:680-710`). Auto-install then
hard-links that file verbatim into the account dataset store, keeping the `.json.zlib`
name, and records `format: "json"` on the manifest (`install/bundle.py:346-365` →
`computed_output_format` at `domain/provenance.py:37-56`: `.zlib` is not in
`SUPPORTED_SUFFIXES`, so the sandbox dataType map resolves `dict` → `"json"`).

When the user drags that installed dataset into a **Data Loading** node, the generated
loader code trusts `format` alone and emits the plain-text JSON reader:

```python
with open(dataset_path) as f:
    data = json.load(f)
```

(`backend/app/datasets/domain/catalog_item.py:102-109`, mirrored in
`frontend/.../services/datasetCatalog/datasetLoaderSnippets.ts:109-117`). Running the node
feeds zlib bytes to a text-mode `json.load`, which raises
`UnicodeDecodeError`/`JSONDecodeError` inside `ns['userCode'](incomingInput)`
(`utk_curio/sandbox/app/worker.py:248`) — the traceback in the screenshot.

**Expected behavior.** A Data Loading node pointed at any installed `format: "json"`
dataset must load it successfully, whether the data file is plain `.json` or
zlib-compressed `.json.zlib`, and return the same Python value the producing node emitted
(the pool wrapper `dict`) so downstream behavior matches a direct edge from the Autark
node.

**Why it matters.** This breaks the core promise of computed datasets — "save a node
output, reload it in another dataflow" — for every non-tabular producer (autk-grammar
pools, plain `dict`/`list` outputs). The catalog badge says JSON, install succeeds, and
the failure only appears at execution time as a raw Python traceback, with no hint that
the file is compressed. The Dataset **preview already handles this exact case**
(`application/preview.py:39-67` `_load_json_maybe_compressed`, used at `preview.py:464`),
so the drawer preview works while the generated loader fails — an inconsistency between
two surfaces reading the same file.

**Non-cause, for the record.** The `gpd.read_parquet` snippet visible in one screenshot
node belongs to a different, genuinely-parquet computed dataset (`*_output.parquet`); the
saved specs confirm the failing `.json.zlib` nodes carry the `json.load` snippet. The bug
is the `json` loader branch, not format misclassification.

## 2. Scope

**In scope**

- Backend loader-snippet generator, `json` branch:
  `utk_curio/backend/app/datasets/domain/catalog_item.py:102-109` (`loader_snippet`).
- Frontend mirror, `json` branch:
  `utk_curio/frontend/urban-workflows/src/services/datasetCatalog/datasetLoaderSnippets.ts:109-117`
  (`snippetForFormat`).
- Tests asserting backend/frontend snippet parity and the new behavior (see §7).

**Checked, not changed**

- Snippet regeneration/consumption sites — they take whatever the generator returns:
  `application/listing.py:208,219,232`, `repositories/installed.py:71`,
  `application/mutations.py:140`, frontend `datasetApplication.ts` (drag payload / node
  merge via `mergeDatasetLoaderCode`).
- Bundle part install decompression (`install/bundle.py:219-226`) — already correct; it is
  the precedent this fix follows in spirit.
- Preview reader `_load_json_maybe_compressed` (`application/preview.py:39-67`) — already
  correct; the generated snippet adopts its exact try-decompress-fallback semantics.

**Out of scope (explicitly)**

- Changing how the sandbox persists `dict`/`list` artifacts (`.json.zlib` under
  `artifacts/`) or the hard-link auto-install path — the hard-link is a deliberate
  no-copy optimization on the synchronous execution route
  (`install/installer.py:243-271`); decompress-at-install would forfeit it and would
  still leave already-installed `.json.zlib` datasets broken without a migration.
- Unwrapping the pool envelope into a GeoDataFrame in the loader. A downstream node wired
  directly to the Autark node receives the wrapper `dict` (the artifact kind is `dict`);
  the reloaded dataset must return the same value for parity. The preview's per-layer
  rendering (`normalize_pool_layers`) is a display concern, not a contract change.
- `count_file` leaving `rowCount: null` for `.json.zlib` manifests — cosmetic; note as a
  follow-up only.

## 3. Recommended Implementation Approach

Make the generated **`json` loader snippet compression-tolerant**, in both generators,
using the semantics `_load_json_maybe_compressed` already documents as safe ("a plain
JSON document never decompresses as zlib, so the fallback is safe"):

```python
import json
import zlib

dataset_path = "<path>"
with open(dataset_path, "rb") as f:
    _raw = f.read()
try:
    _raw = zlib.decompress(_raw)
except zlib.error:
    pass  # plain .json — bytes are already the document
data = json.loads(_raw.decode("utf-8"))
```

- `returnVariable` stays `data`; `pathVariable` stays `dataset_path` — existing merged
  node code and `mergeDatasetLoaderCode` marker logic are unaffected.
- `imports` gains `"import zlib"` alongside `"import json"` in both generators (the
  snippet carries its own imports even though the sandbox namespace exposes `zlib`).
- Backend and frontend snippets must stay **byte-identical in generated Python** (an
  existing test suite asserts parity; extend it for this branch).

Why loader-side rather than install-side normalization: it fixes datasets **already
installed** on user machines (no migration), preserves the hard-link fast path, keeps a
single invariant ("`format: json` loader reads plain or zlib JSON") in exactly the two
places that generate the reader, and matches the established preview behavior. This is a
primary-path fix — the try/except is not a silent fallback masking failure; a genuinely
corrupt file still fails loudly at `json.loads`.

## 4. Data and State Handling

- **Source of truth:** the manifest's `format` + data file on disk, unchanged. No new
  metadata field for compression; compression stays an encoding detail the reader
  tolerates (same policy as preview).
- **Data flow:** dataset drag/apply → snippet embedded in node `content` → sandbox
  executes it → returns the decompressed JSON value → normal envelope detection
  downstream. Node re-execution after the producing node re-runs picks up the replaced
  file at the same path (install replaces the `computed.<...>@1` folder in place).
- **No state/UI changes:** loading/empty/error states of the drawer and canvas are
  untouched; the only behavioral change is that execution succeeds.
- **Stale nodes:** nodes created *before* the fix hold the old plain-`json.load` code in
  their saved `content`. `mergeDatasetLoaderCode` intentionally does not rewrite code
  that already references the dataset path, so existing broken nodes are repaired by
  re-dragging the dataset (or clearing the node code) — acceptable and consistent with
  how every prior snippet change has rolled out. Call this out in the PR description.

## 5. UI and UX Requirements

No visible UI changes. Requirements are behavioral:

- Dragging an installed Autark/computed JSON dataset into a Data Loading node and pressing
  Play produces output (no `Error` badge, no traceback panel).
- The generated code shown in the node editor is readable, idiomatic Python with the
  imports at the top — same presentation as today's snippets.
- The dataset's catalog chrome (JSON badge, preview, counts) is unchanged.

## 6. Edge Cases

- **Plain `.json` dataset (imported by the user):** `zlib.decompress` raises
  `zlib.error`; raw bytes are parsed — behavior identical to today. This is the critical
  no-regression case.
- **UTF-8 with BOM / non-ASCII payloads:** `json.loads` on decoded UTF-8 handles
  non-ASCII; artifacts are written `ensure_ascii=False` so this path is exercised today.
- **Empty or truncated file:** fails loudly at `json.loads` with a clear message — same
  as current behavior for corrupt plain JSON.
- **Multi-layer pool wrapper vs single-layer:** both are just JSON values; the loader
  returns the wrapper as-is (parity with a direct edge).
- **Dataset replaced between runs (producing node re-executed):** path is stable
  (folder replaced in place), snippet re-reads the current file each run; no caching in
  the generated code.
- **Old nodes with pre-fix code:** still fail until the dataset is re-applied (see §4);
  no data corruption risk.
- **Legacy `computed.x{hash}` datasets with `.json.zlib` files:** same loader branch,
  fixed identically.

## 7. Testing Strategy

- **Backend unit (required):**
  `utk_curio/backend/tests/test_datasets/test_dataset_node_loader.py` — update the
  parametrized `json` case (`:74-76`) to assert the new snippet (binary read +
  `zlib.decompress` + fallback). Add an execution test that `exec`s the generated
  snippet body against (a) a temp plain `.json` file and (b) a temp `.json.zlib` file
  containing an autk pool wrapper, asserting the returned value equals the original
  document in both cases — this is the regression test for this bug.
- **Frontend unit (required):**
  `utk_curio/frontend/urban-workflows/src/tests/services/datasetCatalog.test.ts` — update
  the `json` snippet expectations (`:300-320`) and the backend/frontend parity assertion
  so the two generators emit identical Python.
- **Merge behavior:** one case through `mergeDatasetLoaderCode` confirming the new
  `import zlib` is added once and not duplicated on re-apply.
- **Existing coverage to keep green:** `test_pool_json_preview.py` (zlib pool previews),
  bundle loader tests, parquet/csv/geojson snippet cases.

## 8. Acceptance Criteria

1. Dragging the installed "Autark" computed dataset (manifest `format: "json"`, data file
   `data/<ts>_<hash>.json.zlib`) into a Data Loading node and executing it returns the
   pool wrapper dict; the node shows output, not `Error`.
2. A Data Loading node for a plain `.json` imported dataset still loads it (byte-for-byte
   same result as before the change).
3. Backend `loader_snippet("json", path)` and frontend `snippetForFormat("json", path)`
   emit identical Python, including `import zlib`.
4. The node's generated code reads the file in binary mode and never calls text-mode
   `json.load(f)` for the `json` format.
5. No changes to manifests, install paths, hard-linking, preview, or catalog UI.
6. All updated backend + frontend tests pass (run via the `curio-feat` conda env for
   node/jest).

## 9. Recommended Commit Breakdown

- **Commit 1:** Backend — zlib-tolerant `json` loader snippet in
  `domain/catalog_item.py` + updated/new backend tests (snippet shape + execution
  round-trip on plain and compressed files).
- **Commit 2:** Frontend — mirror the snippet in `datasetLoaderSnippets.ts` + updated
  jest tests including the backend/frontend parity case and `mergeDatasetLoaderCode`
  import handling.

(Two commits, one per side, each independently green.)

## 10. Engineering Quality Checklist

- No duplicated logic beyond the intentional backend/frontend snippet mirror that already
  exists and is parity-tested.
- The decompress-then-fallback semantics are copied from the one canonical precedent
  (`_load_json_maybe_compressed`), not invented anew.
- No new types or metadata fields; `DatasetFormat` unchanged.
- Generated code is race-free (pure file read per execution) and adds no re-renders,
  state, or UI surface.
- Loud failure preserved for genuinely corrupt files.
- Follow-ups noted, not smuggled in: (a) `count_file` row counts for `.json.zlib`
  manifests, (b) whether the sandbox should persist autk pool wrappers in a richer form
  (bundle/parquet) — a producer-side design question, tracked separately.
