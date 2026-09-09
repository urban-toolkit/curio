# dev/119 — Executability is a template fact, not a hand-kept list: `spatial-join` is right to read *not executable* (it has no code — a backend endpoint does its work), `data-summary` and every package Python kind are wrong, and a palette-dragged node's versioned id makes the per-node Solve refuse real code

**Status: IMPLEMENTED (2026-09-09) on `imp/agentcatalog` — commit 3 (frontend + docs) landed as `92901dda` after commit 2 `33308182`: `node.create` mints `pins.executable` from the roster row (display, never a revision pin), `AgentReviewCard.nodeKindExecutable` reads it (registry-descriptor fallback for older parts; unknown says nothing), `utils/executableNodeKinds.ts` deleted, pill/attempt/effect words say *no code to run*; docs `AGENT-CATALOG.md`, `USAGE.md`, `AUTHORING-NODES.md`, `EXTENDING.md`; ledgers `DEC-076` + DEC-075 note, dev/00 row, `BL-P5-20260909-53`, `3.1`, dev/118 F5 closed as re-scoped, docs/09 note. jest full run green, `tsc` clean. Owner live re-test of a palette-dragged node pending. History — Commit 1 (the hotfix) landed on `imp/agentcatalog` as `c43eedaa`: `workflow_spec.normalize_type` strips `@<major>` before the legacy lookup; pins: `parse_workflow_dict` classifies `curio.builtin/data-loading@1` as `code` with the wire id kept on `raw_type`, a versioned data-loading target executes, and the per-node Solve on a `curio.builtin/data-loading@1` node passes instead of answering *not executable*. Backend 1209 passed / 2 skipped. Commit 2 landed as `33308182`: the roster carries `engine`, `editor`, `hasCode`, `backendHandler`, `executable` (`packages_services.template_is_executable`, `roster_templates(user_key, project_id)` → `{canonical_id: {executable, engine}}` or None); `parse_workflow_dict(templates=)` / `is_executable_kind(kind, templates)` classify from the snapshot with the legacy tables as offline fallback (a roster row known and not executable is never `code`, whatever the legacy name said); `NodeSpec.engine` routes `/exec` vs `/execJs`; `run_through_node(templates=)`, `validate_candidate(templates=)`, the loop (its existing `available` roster), the batch (one snapshot) and the per-node Solve (one snapshot per request) all thread it; wording is now *has no code the sandbox could run — it works in the browser or through its own service; Play the dataflow to see it*. Pins: roster flags follow the manifest not the name (an `editor: none` template NAMED `data-loading` is not executable), backend-handler templates are not sandbox-executable, a package JS kind runs on `/execJs`, spatial-join is refused with the service wording, per-node Solve verifies `data-summary@1` and a roster-only `custom-js@1`. Backend 3107 passed / 5 skipped (`test_broken_library_stub…empty_pythonpath_entry` fails on the untouched tree too — environmental; `test_frontend/` Playwright suite errors while the live stack holds :5002). Commit 3 pending.**

Date: 2026-09-09
Branch / tree: `imp/agentcatalog` @ `efa8fdac` (dev/118 closed and live re-tested). Line numbers pinned to that commit. `plans/` is tracked on this branch since `7f990e88`; `plans/urbanagentic/hookable-agents/knowledge-graph/` (a 354 MB site copy) stays untracked by intent.
Origin: dev/118 follow-up **F5** — *"`spatial-join` and package-provided Python kinds are absent from `NAMESPACED_TO_LEGACY`, so the runner treats them as passive — map them so verification reaches them"* — chosen by the owner 2026-09-09 (*"plan for the built-in spatial-join node"*). **The premise was half wrong**, and the survey that tested it found the defect that matters.
Evidence: `packages/curio.builtin@1/manifest.json` — `spatial-join`: `engine: python`, **`editor: "none"`, `hasCode: false`**, `behavior: "spatial-join"`, two `GEODATAFRAME` input ports, one output; no `source`, no body. `frontend/.../adapters/node/spatialJoinBehavior.tsx:32` — `const API_BASE = \`${backendUrl()}/spatial_join\``; `:139-176` — a `useEffect` on the two filled slots POSTs `{points, polygons, name_property}` to `api/routes.py:674 @bp.route('/spatial_join')` (`common/spatial.py`); `registry/packagesClient.ts:211-215` — `editor === 'none'` → no editor, no `sendCode`; `UniversalNode.tsx:114-118` — Play with no `sendCode` signals done and posts nothing. **Spatial join is not node code; nothing about it can run in the sandbox. "Not executable" is the truth, and the label's words ("runs in the browser") are the only thing wrong.** `manifest.json` — `data-summary`: `engine: python`, **`editor: "code"`, `hasCode: true`**; `adapters/node/dataSummaryBehavior.tsx:144` `DEFAULT_CODE = "import pandas as pd … return summary"` posted through `PythonInterpreter.ts:64-80` to `/processPythonCode` like any code node — **a genuine Python node**. `execution/workflow_spec.py:61-73` `NAMESPACED_TO_LEGACY` maps `data-summary` → `DATA_SUMMARY`, but `CODE_TYPES` (`:36-41`) never contained `DATA_SUMMARY`, so `classify_node` → `passive` → `is_executable_kind` → **False**: dev/118 writes it *not executable*, wrongly. `workflow_spec.normalize_type` (`:76-78`) is a plain `dict.get` — **it does not strip `@<major>`** — while `is_executable_kind` (`:81-90`) does. Measured on this tree: `curio.builtin/data-loading@1 → normalize = curio.builtin/data-loading@1, category = passive, is_executable_kind = True`. `TrillGenerator.ts:188-189` persists the versioned id for every palette-dragged node (`trill.v1.json:596`: *"palette-dragged nodes persist the versioned form and there is no load-time normalizer"*). **Consequence, live today:** a user drags a Data Loading node, writes code, asks **Solve this node** → the gate says executable, the loop runs, `run_through_node` (`runner.py:270-278`) sees `target.category != "code"` and answers `notExecutable` — *"runs in the browser"* — on a Python node. The dev/118 live runs never hit it only because plan-applied nodes carry the unversioned id (`task2_apply.json`: `curio.builtin/data-loading`). Third-party kinds: `packages/curio.weather@1/manifest.json` (`mrt-load`, `weather-load`, `census-load`, `utci-compute`, `utci-zonal`, `census-reproject`, `gt65-projection`) and `packages/ai.urbanlab.uhvi@1/manifest.json` (`uhvi-load`, `uhvi-zones`, `uhvi-zonal`) — ten `engine: python`, `editor: code` templates with real starter bodies, all `passive` to the runner and *not executable* to Solve. `runner.py:318` `is_py = node.type in PY_CODE_TYPES` — a package Python kind that were made executable by list would still be routed to `/execJs`. `packages/services.py:691-719` `_template_entry` — the roster row every agent sees carries `authorable` and `presentation` but **neither `engine` nor `editor` nor `hasCode`**, although `packages/manifest.py:263-350` parses all three (`engine` validated `python|javascript`, `editor` validated `code|widgets|grammar|none`, `has_code` defaults to `editor == "code"`, `backend_handler`); `docs/schemas/node-package.v4.json:174` makes `engine` and `editor` **required** on every template. `packages/services.py:510-539` `canonical_template_id` already derives legacy names by rule and its docstring names *"built-in templates that never got an enum member (spatial-join)"*. `packages/spec_packages.py:44` `unversioned_node_type` is the existing normalizer the trill contract mandates. `frontend/.../utils/executableNodeKinds.ts:8-22` (dev/118 commit 5) is a third hand-kept copy of the same fact and omits `data-summary` too; the registry descriptor already carries `editor: EditorType` and `hasCode: boolean` (`registry/types.ts:217,224`). `tests/test_frontend/workflow_spec.py` is a **divergent copy** of the app module (its `PY_CODE_TYPES` lacks `CONSTANTS`/`FLOW_SWITCH`) although the app docstring says the e2e suite imports it through a shim; `utils.py:701` pass-throughs every non-code node with **no expected-output entry**, so `spatial-join` and `data-summary` are never asserted by the e2e matrix — and the one example carrying a `spatial-join` (`docs/examples/10-street-vision-cv-analysis.json:71`) is the one workflow the matrix skips (`conftest.py:115-121`). `sandbox/util/parsers.py:57-116` `checkIOType` matches legacy uppercase ids only and has no `else`: for the namespaced ids every caller sends, IO validation is dead code (a separate finding).
Family: dev/67-7 (the runner promoted from the e2e utilities, with its legacy-id classifier) → dev/93 (DEC-062: ONE node-type vocabulary, ONE canonicaliser — `canonical_template_id`) → dev/89–98 (packages declare `engine`/`editor`/`backendHandler`; dev/91 `curio.pkgbackend.v1`) → dev/118 (DEC-075: `is_executable_kind` as THE predicate — built on the legacy list) → **dev/119**.
Design decisions consumed: DEC-062 (one vocabulary, one canonicaliser — the legacy list is the drift DEC-062 exists to prevent), DEC-061 (a `backendHandler` template runs through the package sandbox, a different path — not this memo's), DEC-072/073/075 (the gate and the loop consult one executability predicate; only its *source of truth* changes). **New decision proposed: DEC-076** — *Whether the sandbox can run a node kind is read from its template — `engine` ∈ {python, javascript} and an editable code surface (`hasCode`), and no `backendHandler` — through the template roster the agents already receive; never from a hand-kept list of legacy names. Node type ids are normalised through the one canonicaliser (`@<major>` stripped) before any classification. The legacy `NAMESPACED_TO_LEGACY`/`CODE_TYPES` tables remain only as the offline fallback when no roster is available (the e2e runner over a raw file), and they say so. A template that has no code — `spatial-join`, `merge-flow`, `data-pool`, the grammars — is "not executable" with the honest reason: it has no code the sandbox could run (its work happens in the browser or a dedicated backend endpoint); the frontend reads executability from the proposal (`pins.executable`) or the registry descriptor, never from its own list.*
Backlog: `BL-P5-20260909-53` at closure; closes dev/118 F5 as **re-scoped** (spatial-join needs no mapping; `data-summary`, versioned ids and package kinds are the fixes); the `checkIOType` dead code and the e2e copy drift are recorded findings.

---

## 1. Problem Statement

**What is wrong.** Since dev/118, whether a node's code is verified — or written and labeled *not executable* — is decided by `is_executable_kind`, and that predicate is a hand-kept list of eleven legacy names from 2024. Three things it gets wrong, in order of harm:

1. **A palette-dragged node cannot be solved.** Its saved type is the versioned canonical id (`curio.builtin/data-loading@1`). The gate normalises it and says "executable"; the runner does not normalise it, classifies it `passive`, and refuses the run as *not executable — runs in the browser*. Every user-authored node on the canvas is versioned. This is live now.
2. **`data-summary` is a Python code node that Solve refuses to verify.** It is in the mapping, mapped to a legacy name that was never in the code set. Its content is written unexecuted and labeled *runs in the browser*, which is false.
3. **Ten shipped package kinds are Python code nodes the runner treats as passive** (`curio.weather@1`, `ai.urbanlab.uhvi@1`). Solve writes them unverified; the e2e runner forwards their inputs untouched. Any future package Python kind inherits the same fate, and a list-based fix would also route them to `/execJs`.

**What is right and only mislabeled.** `spatial-join` has no code: it is a behaviour node whose work is a dedicated backend endpoint, driven by the frontend when both inputs arrive. "Not executable" is correct; "runs in the browser" is not the reason. dev/118 F5 asked to map it into the code set — that would make Solve try to generate and run code for a node that has none.

**Why it matters.** Correctness: the per-node Solve, dev/118's headline feature, is broken for the nodes users actually create. Honesty: two labels are false today. Architecture: DEC-062 made `canonical_template_id` the one canonicaliser and the manifest the one vocabulary precisely so that no table of legacy names would drift — and three copies of that table now exist (the app module, the e2e copy, the frontend twin), already drifted from each other.

## 2. Scope

**Included**

- **Hotfix first (commit 1):** `workflow_spec.normalize_type` strips `@<major>` (the `unversioned_node_type` rule) before the legacy lookup, so `NodeSpec.category` and `is_executable_kind` agree on every versioned id; a regression test drives the per-node Solve on a `curio.builtin/data-loading@1` node end to end (it runs). This lands alone because it is the live defect.
- **The roster states executability (commit 2):** `_template_entry` gains `engine`, `editor`, `hasCode`, `backendHandler` (bool) and the derived `executable` (= `engine ∈ {python, javascript}` ∧ `hasCode` ∧ ¬`backendHandler`). One derivation, in `packages/services.py`, documented against the schema.
- **Classification from the roster (commit 2):** `parse_workflow_dict(spec, templates=None)` accepts `{canonical_id: {"executable": bool, "engine": str}}`; when given, `NodeSpec.category` is `code` iff executable and `NodeSpec.engine` is the template's; when absent, the legacy tables apply (the offline fallback, so the e2e runner over a raw file still works). `run_through_node(..., templates=None)` threads it and routes by `engine` (`javascript` → `/execJs`, else `/exec`) instead of `PY_CODE_TYPES`. `validate_candidate(..., templates=None)` passes it; the loop derives it from the `available` roster snapshot it already loads; `_node_is_executable(node, available)` reads the roster (fallback to the legacy predicate when the roster is unavailable).
- **Honest wording:** the not-executable reason becomes *"has no code the sandbox could run — <kind> works in the browser or through its own service; Play the dataflow to see it"*; the frontend pill and effect line follow.
- **Frontend reads, never lists (commit 3):** `node.create` proposals carry `pins.executable` (the mint knows the template); the review card's effect line reads it, falling back to the registry descriptor's `hasCode`/`editor` for older parts, and `utils/executableNodeKinds.ts` is deleted (its test moves to the descriptor-driven helper).
- **Pins for the two kinds the survey named:** `data-summary` executable and verified; `spatial-join` not executable with the new reason; a `curio.weather@1` Python kind verified through `/exec` when its package is installed in the project.
- **Docs on close:** `docs/AGENT-CATALOG.md` (what "not executable" means, one paragraph corrected), `docs/AUTHORING-NODES.md` (a package Python template is verified by Solve because of its `engine`/`editor`, nothing to declare), dev/03 `DEC-076` + a note on DEC-075, dev/00 row, `BL-P5-20260909-53`, `3.1`, dev/118 F5 closure (re-scoped).

**Must be checked but not changed**

- `canonical_template_id` (dev/93) — the normaliser; reused, not duplicated.
- `available_templates` and its consumers (`_available_templates_block`, the reuse ladder) — additive fields only.
- The sandbox's `checkIOType` legacy matching — out of scope; recorded (§"Follow-ups").
- `backendHandler` templates — stay not executable here (dev/91's runtime is a different execution path); the reason names it.
- The e2e Playwright suite's own `workflow_spec.py` copy — untouched in this memo (follow-up F1: import the app module as the docstring claims).

**Out of scope (explicitly)**

- Making `spatial-join` a code node or generating code for it — it has none by design.
- Running `backendHandler` templates through validation (dev/91 runtime) — F2.
- Reviving the sandbox's IO validation for namespaced ids — F3.
- Unifying the e2e copy — F1.

## 3. Recommended Implementation Approach

### 3.1 Commit 1 — the hotfix

`workflow_spec.normalize_type(node_type)`: `bare = node_type.split("@", 1)[0]` then the legacy lookup. `is_executable_kind` keeps its own strip (harmless). Test: `parse_workflow_dict` on `curio.builtin/data-loading@1` → `category == "code"`; `TestSolveNode` gains a node typed `curio.builtin/data-loading@1` whose current content runs and passes (today: `not-executable`). Also `run_through_node` on a versioned data-loading target executes.

### 3.2 Commit 2 — executability from the roster

```python
# packages/services.py — _template_entry
"engine": template.engine,
"editor": template.editor,
"hasCode": bool(template.has_code),
"backendHandler": bool(template.backend_handler),
"executable": bool(template.has_code and template.engine in ("python", "javascript") and not template.backend_handler),
```

```python
# execution/workflow_spec.py
def parse_workflow_dict(spec_dict, *, templates: dict | None = None) -> WorkflowSpec
#   templates: {canonical_id: {"executable": bool, "engine": "python"|"javascript"}} (unversioned keys)
#   category = "code" if templates and templates.get(canonical(id), {}).get("executable") else legacy classify_node(...)
#   NodeSpec.engine = templates[...]["engine"] or ("javascript" if legacy JS_COMPUTATION else "python")
```

`run_through_node(..., templates=None)` → `parse_workflow_dict(spec, templates=templates)`; `endpoint = "/execJs" if node.engine == "javascript" else "/exec"`. `validate_candidate(..., templates=None)` passes it. In the loop: `available` is already loaded (`packages_services.available_templates(user_key, project_id)`); `templates = {t["id"]: {"executable": t.get("executable"), "engine": t.get("engine")} for t in available.values()}`; `_node_is_executable(node, templates)` → `templates[canonical_template_id(type)]["executable"]` when known, else the legacy predicate. The per-node Solve and validate-node load the same roster (they resolve templates already for arity).

The runner's not-executable message: *"node '<id>' (<kind>) has no code the sandbox could run — it works in the browser or through its own service; Play the dataflow to see it"*; `_record_outcome`'s `verification.reason` and the per-node Solve text say the same.

### 3.3 Commit 3 — the frontend reads

`_mint_node_create` puts `executable: bool` on the proposal's `pins` (from the roster row). `AgentReviewCard`: `part.pins?.executable ?? descriptorFor(part.pins?.nodeType)?.hasCode` — the registry descriptor (`hasCode`, `editor`) is the fallback for parts minted before this; `utils/executableNodeKinds.ts` is removed. The pill text: *written — no code to run; renders in the browser or its own service*.

### 3.4 What this is NOT

Not a change to what Solve does with an executable node. Not a new execution path for handlers. Not a change to `spatial-join`'s behaviour — only to its label.

## 4. Data and State Handling

- **Source of truth**: the installed templates' manifests, through the roster (`available_templates`) — resolved once per loop / per validation / per batch in the request thread (the roster needs `user_key`/`project_id`; the runner does not).
- **Derived**: `templates` map per call; `NodeSpec.category`/`engine`; `pins.executable` at mint time.
- **Fallback**: no roster (offline runner, tests over raw files) → the legacy tables, with the module docstring saying they are a fallback.
- **No new state**; no persistence.

## 5. UI and UX Requirements

- Pill: *written — no code to run; renders in the browser or its own service* (was "runs in the browser, not executed").
- Review card effect line: executable → unchanged; not executable → *"This kind has no code to run — Solve writes it, Play renders it; it is never called verified."*
- Attempt row: *not executable — no code to run*.
- No colour changes; words carry the state.

## 6. Edge Cases

1. **Versioned and unversioned ids in one spec** — both normalise to the same roster key.
2. **A template not in the roster** (an uninstalled package's node in a loaded dataflow) — legacy fallback; if still unknown, not executable with the reason *"its package is not installed in this project"*.
3. **`backendHandler` template** — not executable; reason names the package sandbox.
4. **`editor: widgets` with `engine: python`** — `hasCode` decides (the manifest default makes `widgets` code-less unless declared); documented.
5. **A `javascript` package kind** — routed to `/execJs`.
6. **Roster read fails mid-batch** — the loop keeps the snapshot it loaded at start; a failed load at start → legacy fallback, logged once.
7. **Frontend part without `pins.executable`** (minted before this) — descriptor fallback; unknown → the not-executable wording is *not* shown (no claim either way).

## 7. Testing Strategy

- `test_execution/test_runner.py`: `normalize_type` strips versions (commit 1); `parse_workflow_dict(templates=…)` makes a package Python kind `code` with `engine`, a `javascript` kind routes to `/execJs`, `spatial-join` stays passive with the new message; fallback without templates unchanged.
- `test_packages/…`: `_template_entry` fields for `data-loading` (executable), `data-summary` (executable), `spatial-join` (not), `js-computation` (executable, javascript), a handler template (not).
- `test_verified_rounds.py`: per-node Solve on `curio.builtin/data-loading@1` runs and passes (the live-defect regression); `data-summary` verified; `spatial-join` not executable with the new reason; a `curio.weather@1` kind verified via `/exec` (package installed in the fixture).
- `test_routes.py`: `node.create` proposals carry `pins.executable`.
- jest: review card reads `pins.executable`, falls back to the descriptor, shows nothing when unknown; the strip pill words.
- `tsc` clean; the colour-literal guard green.

## 8. Acceptance Criteria

1. A palette-dragged Data Loading node with working code passes **Solve this node** (today: refused as not executable).
2. A `data-summary` node is verified by Solve and shows *pass* on the card.
3. A `curio.weather@1` Python node in a project with the package installed is verified through `/exec`; a JavaScript kind through `/execJs`.
4. `spatial-join`, `merge-flow`, `data-pool`, `vis-*`, `autk-grammar` read *no code to run*, never *pass*.
5. The roster row of every template carries `engine`, `editor`, `hasCode`, `executable`.
6. No frontend file holds a list of executable node kinds.
7. The legacy tables remain and are documented as the offline fallback.

## 9. Recommended Commit Breakdown

- **Commit 1 — hotfix**: `normalize_type` strips `@<major>`; regression tests (runner + per-node Solve on a versioned id).
- **Commit 2 — roster executability**: `_template_entry` fields; `parse_workflow_dict(templates=)`, `NodeSpec.engine`, engine-based endpoint; `validate_candidate`/loop/batch/per-node Solve/validate-node thread the roster snapshot; the new reason wording; tests incl. `data-summary`, `spatial-join`, a package kind.
- **Commit 3 — frontend + docs + ledgers**: `pins.executable` at mint, the card reads it, the twin list deleted; docs; `DEC-076`, dev/00, `BL-P5-20260909-53`, `3.1`, dev/118 F5 re-scoped closure.

## 10. Engineering Quality Checklist

- One canonicaliser (`canonical_template_id` / `unversioned_node_type`) before every classification.
- One derivation of `executable`, in the roster row, from schema-required fields.
- The legacy tables survive only as a fallback and say so.
- The runner stays import-pure: the roster is resolved by callers with a user context and passed in.
- Words for every not-executable case; no false "runs in the browser".
- Tests pin the two mislabeled kinds and the live defect.
- Frontend: no list; the proposal or the descriptor is the source.

## Open questions for the owner (non-blocking — defaults stated)

1. **Keep the legacy tables as the offline fallback** (default) or delete them and require a roster everywhere (the e2e runner would need one).
2. **`backendHandler` templates** stay not executable (default) until dev/91's runtime is wired into validation.
3. **Land the hotfix alone first** (default — it is the live defect) or with commit 2.

## Follow-ups (recorded, not delivered)

- **F1** The e2e suite's `tests/test_frontend/workflow_spec.py` is a drifted copy of the app module — import the app module as its docstring claims; assert `spatial-join`/`data-summary` in the matrix (example 10 is skipped offline).
- **F2** Validation through the package sandbox for `backendHandler` templates (dev/91).
- **F3** `sandbox/util/parsers.py:checkIOType` matches legacy ids only and is dead code for the namespaced ids every caller sends.
- **F4** `docs/examples/10-street-vision-cv-analysis.json:71` still carries the pre-#262 workaround comment about the spatial-join tag column.
