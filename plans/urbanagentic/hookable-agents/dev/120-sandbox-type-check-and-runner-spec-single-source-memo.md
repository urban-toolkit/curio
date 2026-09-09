# dev/120 — Retire the sandbox's name-keyed I/O check; restore the runner spec's single source

**Status: PROPOSED (2026-09-09). Awaiting owner approval; no code written.**

Date: 2026-09-09
Branch / tree: `imp/agentcatalog` @ `9d220db2` (dev/119 closed). Line numbers pinned to that commit. `plans/` is tracked on this branch; `plans/urbanagentic/hookable-agents/knowledge-graph/` (354 MB site copy) stays untracked by intent.
Origin: the two findings dev/119 recorded as follow-ups F1 and F2 (`BL-P5-20260909-53`), chosen by the owner 2026-09-09 (*"now tackle the two recorded findings about the sandbox type check and the drifted runner copy"*).
Evidence (F1): `sandbox/util/parsers.py:57-112` — `checkIOType(data, nodeType, input)` dispatches on the legacy uppercase names `DATA_EXPORT`, `DATA_TRANSFORMATION`, `DATA_LOADING` only. Every caller sends the namespaced id: the browser (`PythonInterpreter.ts:78` posts `nodeType: NodeTemplateId`, and `constants.ts:22-34` defines `NodeType.DATA_LOADING = "curio.builtin/data-loading"`), the agents' runner (`execution/runner.py:353` — `"nodeType": node.raw_type`), and the e2e runner (`tests/test_frontend/utils.py:740-745`, whose comment says it in so many words: *"Send the on-the-wire namespaced id … so the sandbox's checkIOType matches what the browser frontend posts; otherwise the programmatic runner would enable IO validation that the browser path silently skips"*). The worker calls it three times (`sandbox/app/worker.py:411,415,451`) and seeds it into every node's namespace (`worker.py:229,258`; `isolation/zygote.py:100,124`), and `tests/test_sandbox_namespace.py:103` pins the seeded name. The ONE place the check still fires is the e2e baseline-minting replay (`tests/test_frontend/utils.py:601` — `checkIOType(parsed, node.type, False)` with the LEGACY `NodeSpec.type`), i.e. the expected-output generator enforces a constraint the product never does. The constraints it encodes (`data-loading` out ∈ {dataframe, geodataframe, raster}; `data-transformation` ≤ 2 inputs of the same set; `data-export` no output) are a hand-typed copy of the builtin manifest's port declarations (`packages/curio.builtin@1/manifest.json`: `data-loading` out `[DATAFRAME, GEODATAFRAME, RASTER]`, `data-transformation` in `[1,2]`, `data-export` no output ports) — a second vocabulary of the kind DEC-062 exists to prevent.
Evidence (F2): dev/67-7 (`d2053cf9`) promoted the e2e suite's `workflow_spec.py` into `app/execution/workflow_spec.py` and left a **shim** at `tests/test_frontend/workflow_spec.py` (*"the spec model was PROMOTED to the app package … the e2e suite keeps its historical import path through this re-export"*; dev/67-7 line 6: *"e2e shims verified by identity import"*). The merge `619ab203` (2026-08-26, *"agent catalog onto main's catalog interface"*) resolved that file to main's full 275-line module — main never had the app module, so its copy won — and nothing has pinned the identity since. Today the two disagree in both directions: the copy lacks the dev/119 hotfix (`normalize_type` does not strip `@<major>`), `is_executable_kind`, `_classify_with_roster`, `parse_workflow_dict`, `NodeSpec.engine`; the app module still carries `CONSTANTS` and `FLOW_SWITCH` in `PY_CODE_TYPES`/`CODE_EDITOR_TYPES` (`workflow_spec.py:38-39,49`), which main removed as phantoms (`94ec216d`, `5081b91b`) and which appear nowhere else in the repository — no manifest, no frontend enum, no `NAMESPACED_TO_LEGACY` entry. The e2e suite imports the copy at `test_workflows.py:29` (`NodeSpec`, `CODE_EDITOR_TYPES`), `utils.py:692` (`PY_CODE_TYPES`), `fixtures.py:30,628` (`PY_CODE_TYPES`, `normalize_type`, `parse_workflow`), `test_examples.py:15` (`parse_workflow`). The 20 curated example trill files use unversioned namespaced ids only, so the missing version strip has not yet bitten the suite.
Family: dev/67-7 (the promoted runner and its shim) → dev/93 (DEC-062, one vocabulary / one canonicaliser) → dev/118/119 (DEC-075/076, executability from the template) → **dev/120**.
Design decisions consumed: DEC-062 (one node-type vocabulary; a hand-kept second table is drift), DEC-076 (the template's declared facts are the source of truth; the legacy tables are an offline fallback and say so), DEC-075 (the runner's classification is the ONE predicate). **No new decision proposed** — this memo enforces two existing ones; DEC-062 and DEC-076 each get a one-line note at closure.
Backlog: `BL-P5-20260909-54` at closure; closes dev/119 F1 and F2.

---

## 1. Problem Statement

**F1 — a validator that never validates.** The sandbox worker "validates" every node's input and output against its node type, but the dispatch keys are legacy uppercase names and every producer of `nodeType` has sent the namespaced id since the package registry landed. The check is dead on the browser path, the agents' runner path and the e2e runner path; it costs three calls per execution, a seeded name in every node namespace (in-process and isolated), a pin in the namespace test, and a paragraph in `docs/ARCHITECTURE.md:431` that describes behaviour the product does not have. Worse, the one caller that still reaches it — the e2e baseline replay — enforces a rule the shipping product does not, so a baseline can be refused for output the browser would accept. And the rule itself duplicates the manifest's port declarations by hand.

**F2 — two runner classifiers, both wrong somewhere.** dev/67-7 made the app module the single source and left a shim; a later merge silently replaced the shim with main's full copy. The e2e suite now classifies nodes, orders execution and injects seeds with a module that lacks the dev/119 hotfix and every dev/118/119 addition, while the app module carries two phantom kinds main deleted. The next divergence will be found the way the last one was: by a live failure, not a test.

**Expected behaviour.** One classifier (`app/execution/workflow_spec.py`) imported by everything, with an identity test that fails the moment a copy reappears, and no phantom kinds. No I/O type check keyed on node names anywhere: the type contract of a node is its template's declared ports (DEC-062/076), enforced where it is declared (the frontend refuses an incompatible connection at connect time — `FlowProvider.tsx:1053 isValidConnection`); if a run-time check is ever wanted it is derived from those ports, by its own memo.

## 2. Scope

**Included.**
- `utk_curio/sandbox/util/parsers.py`: delete `checkIOType`, `validate_input`, `validate_output`, `check_dataframe_input`, `check_transformation_input`, `check_valid_output`.
- `utk_curio/sandbox/app/worker.py`: remove the import (`:229`), the seeded name (`:258`), the cache read (`:358`) and the three calls (`:411,415,451`). `node_type` stays: it tags the artifact (`save_to_duckdb(node_id=node_type)`) and the log lines.
- `utk_curio/sandbox/isolation/zygote.py`: remove the import (`:100`) and the seeded name (`:124`).
- `utk_curio/backend/tests/test_sandbox_namespace.py:103`: drop `checkIOType` from `EXPECTED_SEEDED_NAMES` (see §3.2 for why this is not a #158 regression).
- `utk_curio/backend/tests/test_frontend/utils.py`: remove the import (`:530`) and the replay call (`:601`); rewrite the comment at `:740-745` (the id is sent for artifact tagging and logs).
- `utk_curio/backend/tests/test_frontend/workflow_spec.py`: back to the dev/67-7 shim — a re-export of the app module's public names, extended with `normalize_type`, `classify_node`, `parse_workflow_dict`, `is_executable_kind`.
- `utk_curio/backend/app/execution/workflow_spec.py`: drop `CONSTANTS` and `FLOW_SWITCH` from `PY_CODE_TYPES` and `CODE_EDITOR_TYPES` and the comment at `:45`.
- New unit tests (backend suite, no stack): identity of the shim; no phantom in the legacy tables; `checkIOType` absent from the seeded namespace on both paths.
- Docs: `docs/ARCHITECTURE.md:431` (the wrapper paragraph — also names `python_wrapper.txt`, which exists; only the `checkIOType` sentence changes).
- Ledgers at closure: DEC-062 and DEC-076 notes, dev/00 row, `BL-P5-20260909-54`, `3.1`, dev/119 F1/F2 closure.

**Out of scope.**
- A run-time port-type check derived from the template's declared ports (option C in §3.3) — its own memo if there is demand.
- Any change to `detect_kind`, `save_to_duckdb`, or the `dataType` the sandbox reports.
- `test_frontend/test_workflows.py`'s use of `CODE_EDITOR_TYPES` to pick the editor locator — unchanged; it merely stops seeing the two phantoms it never met.
- The two pre-existing e2e failures noted in `BL-P5-20260909-53` (F3 there).

## 3. Recommended Implementation Approach

### 3.1 Commit 1 — the shim restored, the phantoms gone (F2)

`tests/test_frontend/workflow_spec.py` becomes the dev/67-7 shim again:

```python
"""Shim (memo dev/67-7, restored dev/120): the spec model lives in
`utk_curio.backend.app.execution.workflow_spec` — the single source. The e2e
suite keeps its historical import path through this re-export; a test pins
identity so a merge can never turn this back into a copy."""
from utk_curio.backend.app.execution.workflow_spec import (  # noqa: F401
    CODE_EDITOR_TYPES, CODE_TYPES, GRAMMAR_TYPES, NAMESPACED_TO_LEGACY, PY_CODE_TYPES,
    NodeSpec, WorkflowSpec, classify_node, is_executable_kind, normalize_type,
    parse_workflow, parse_workflow_dict,
)
```

`app/execution/workflow_spec.py`: the change is subtractive only. `DATA_SUMMARY` is deliberately NOT added to the legacy code table (dev/119: the roster says it is executable; the legacy table is the offline fallback and is not to grow). Remove `"CONSTANTS"` and `"FLOW_SWITCH"` from `PY_CODE_TYPES` (`:38-39`) and `"FLOW_SWITCH"` from `CODE_EDITOR_TYPES` (`:49`); fix the comment at `:45`.

Tests (new file `tests/test_execution/test_workflow_spec_single_source.py`):
- identity: `from utk_curio.backend.tests.test_frontend import workflow_spec as shim` and `shim.NodeSpec is app.NodeSpec`, `shim.parse_workflow is app.parse_workflow`, `shim.normalize_type is app.normalize_type` — the dev/67-7 "identity import" made durable, and it runs in the plain backend suite (no Playwright, no stack: the import of `test_frontend/__init__` must stay side-effect free — verify; if `conftest.py` there pulls Playwright at import, import the shim module by path instead).
- no phantom: every member of `CODE_TYPES` is a value of `NAMESPACED_TO_LEGACY` (a legacy name with no namespaced spelling can never arrive from a canvas — it is a phantom by construction).
- the shim's `normalize_type("curio.builtin/data-loading@1") == "DATA_LOADING"` — the e2e fixtures' seed injection (`fixtures.py:647`) now reaches palette-dragged nodes.

### 3.2 Commit 2 — the name-keyed I/O check retired (F1)

Delete the six functions in `parsers.py`; remove the worker's and the zygote's import, seed and calls; remove the replay call in the e2e utils.

**Why dropping the seeded name is not a #158 regression.** #158 was the loss of *library* names node code used through the old star import (`np`, `wkt`, `Path`, …). `checkIOType` was a worker-internal validator that leaked with them; it has no user-facing contract (undocumented in USAGE/AUTHORING, absent from every example, every generated prompt and every template body), and calling it from node code with a namespaced type is a no-op today. The namespace pin exists to protect what nodes use; it should not fossilise an internal helper. The test gains the inverse assertion: `"checkIOType" not in worker._globals_cache` and not in the zygote's seeded dict, with this reasoning in the docstring.

The e2e utils comment becomes: *"The on-the-wire namespaced id, as the browser posts it: the sandbox tags the artifact and its log lines with it (no type dispatch happens on it — dev/120)."*

`docs/ARCHITECTURE.md:431`: *"After user code runs, calls `detect_kind(output)` to determine the output type"* — the `checkIOType` clause goes; one sentence says that port-type compatibility is enforced by the canvas at connect time from the template's declared ports.

### 3.3 Alternatives considered

- **B — canonicalise and re-enable.** Map the namespaced id to its legacy name inside `checkIOType` so the dormant rules fire again. Rejected: it would switch on, for every user, constraints that have been off for the life of the package registry (a Data Loading node returning JSON, a Data Export node returning a value, a transformation with three inputs would start failing at run time), and it keeps a hand-typed copy of the manifest's ports — the exact drift DEC-062/076 retire.
- **C — validate against the template's declared ports.** The backend knows the roster (`roster_templates`) and could pass declared `inputTypes`/`outputTypes` in the exec request for the sandbox to check against `detect_kind`. A real feature with real questions (the port vocabulary `DATAFRAME/…/VALUE/LIST/JSON` vs `detect_kind`'s `dataframe/json/str/…` mapping, cardinality `[1,n]`, what a failure looks like to Solve's correction rounds). Deferred to its own memo if demanded; the canvas already refuses incompatible connections.
- **Keep the copy, sync by hand.** Rejected: the merge already showed what hand-sync does.

### 3.4 What this is NOT

Not a change to what the sandbox executes, stores or reports. Not a change to the e2e suite's ordering or seeding semantics (they follow the app module, which the browser tests already agreed with on the 20 curated examples). Not a new DEC.

## 4. Data and State Handling

No persisted data changes. The exec request keeps `nodeType` (artifact tag, logs). `detect_kind` remains the sole source of `dataType`. The runner's `NodeSpec` is unchanged; the e2e suite's `NodeSpec` becomes the same class.

## 5. UI and UX Requirements

None — no user-facing surface changes. A node whose output the dead check would have refused behaves exactly as today.

## 6. Edge Cases

- **Importing the e2e package from the backend suite.** `tests/test_frontend/__init__.py` exists; the identity test must not trigger Playwright fixtures — import the shim module directly, and if `test_frontend/conftest.py` is auto-loaded by that import, load the shim via `importlib` from its path instead. Verified at implementation.
- **A trill with a versioned id under the e2e fixtures.** `normalize_type` now strips the version: seed injection and `PY_CODE_TYPES` membership behave as for unversioned ids. No curated example is versioned; behaviour for them is byte-identical.
- **Node code that called `checkIOType`.** None exists in the repo, the examples or the prompts; after commit 2 such code raises `NameError` like any undefined name — a loud, honest failure rather than a silent no-op.
- **Isolated child vs in-process.** Both seeding sites change together (worker `_globals_cache`, zygote `_seed`); the inverse assertion covers both.
- **Legacy-id trill files.** Old files with uppercase types still normalise through `normalize_type` (pass-through) and classify as before; nothing in this memo touches that path.

## 7. Testing Strategy

- `tests/test_execution/test_workflow_spec_single_source.py` (new): shim identity (three names), no phantom in `CODE_TYPES`, versioned-id normalisation through the shim.
- `tests/test_sandbox_namespace.py`: `checkIOType` removed from `EXPECTED_SEEDED_NAMES`; new inverse assertion on both seeding paths with the #158 reasoning.
- `sandbox/tests`: a worker-level test that a Data Loading node returning a JSON value executes and reports `dataType: json` (the case the dormant rule would have refused) — pins that no name-keyed check silently returns.
- Existing: `test_runner.py`, `test_verified_rounds.py`, `test_available_templates.py` unchanged and green; `tests/test_frontend` collection still imports (a `pytest --collect-only utk_curio/backend/tests/test_frontend` run, no stack needed).
- Required before close: backend suite (without the Playwright directory) green except the known environmental stub test; `--collect-only` of the e2e directory green; one headed/headless e2e smoke (`test_alive.py`) with the stack booted by the fixture.

## 8. Acceptance Criteria

1. `tests/test_frontend/workflow_spec.py` contains no class or function definitions — only the re-export — and the identity test proves it.
2. `CONSTANTS` and `FLOW_SWITCH` appear nowhere in the repository.
3. `grep -rn checkIOType utk_curio docs` returns nothing.
4. A node's namespace (in-process and isolated) no longer contains `checkIOType`; every other pinned name is still present.
5. A Data Loading node returning JSON executes in the sandbox and reports `dataType: json`.
6. `docs/ARCHITECTURE.md` describes the sandbox as it is.
7. The e2e directory collects; `test_alive.py` passes with the fixture-booted stack.

## 9. Recommended Commit Breakdown

- **Commit 1 — F2**: the shim restored; phantoms removed from the app module; the single-source tests.
- **Commit 2 — F1**: `checkIOType` and its validators deleted from `parsers.py`; worker + zygote calls and seeds removed; namespace pin updated with the inverse assertion; the e2e replay call and comment; the JSON-loader sandbox test; `docs/ARCHITECTURE.md`.
- **Tracking**: memo status, DEC-062/076 notes, dev/00 row, `BL-P5-20260909-54`, `3.1`, dev/119 F1/F2 closure — as separate short `tracking …` commits, pathspec-scoped to `plans/urbanagentic/hookable-agents/dev` and `docs/`.

## 10. Engineering Quality Checklist

- No duplicated logic: the second classifier is gone; the second port vocabulary is gone.
- Shared logic centralised: one `workflow_spec` module, imported by the app, the agents and the e2e suite.
- Types explicit: the shim re-exports typed names; nothing is redefined.
- Predictable state: no runtime behaviour change for any node the product accepts today.
- Loading/empty/error states: unaffected.
- Accessibility: not applicable.
- Tests cover the regression (identity, phantom, seeded-name inverse, JSON loader).
- Conventions: pathspec commits, no co-author trailer, never push; the knowledge-graph copy stays untracked.
- No new fallbacks introduced; one dead fallback removed.

---

## Follow-ups

- **F1** Option C — run-time port validation derived from the template's declared ports, if demand appears (needs the `SupportedType` ↔ `detect_kind` mapping decided first).
- **F2** `docs/ARCHITECTURE.md`'s wrapper section predates the in-process worker in places beyond the one sentence fixed here; a docs pass is its own small memo.
