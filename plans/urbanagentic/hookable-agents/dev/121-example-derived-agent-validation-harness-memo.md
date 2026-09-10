# dev/121 — Example-derived agent validation harness: can the Dataflow Builder rebuild the shipped examples from a prompt?

**Status: IMPLEMENTED (2026-09-09) on `imp/agentcatalog` — `DEC-077` minted, `BL-P5-20260909-55`. Seven commits: `37533fce` (fixture contract + canonical form), `a6e4bb18` (the 31 fixtures), `a0cb7e8a` (comparator + scoring + report), `463da635` (oracle + driver + deterministic suite), `292547ba` (browser tier), `d34f766c` (live runner + export), and the docs/ledgers commit. 23 of the 31 fixtures reconstruct to a score of exactly 1.0 through the real plan → review/apply → background Solve path; the other 8 report the `interaction-edge` capability gap their fixture declares. Suites: `tests/test_agents` 1925 passed; the five backend suites 3579 passed / 3 skipped (one pre-existing environmental failure, `test_broken_library_stub…empty_pythonpath_entry`, confirmed failing at `65f91e54` in a throwaway worktree); `tests/test_frontend` collects 464 (435 selected with `--with-examples`). NOT DONE, deliberately and visibly: the four browser tests are written and collect but were NOT executed — the only stack on this machine is the owner's live one and the e2e fixtures reset the database (follow-up F9); and all 31 prompts are committed `review.status = pending-owner-review`, which the deterministic suite does not depend on, the live report labels, and the fine-tuning export refuses until a person approves (F8). Findings the harness produced on its first run are recorded in §11 — the load-bearing one is that Solve's grounding evidence never includes the chat, so two documented DEC-072 routes are unreachable when Solve fills a node (F3). History — PROPOSED 2026-09-09; the memo was amended before any fixture was written when example 09 turned out to declare `curio.weather@1` for its python LIBRARIES while using only builtin templates, which makes "resolution mode" two different routes (§3.5).**

Date: 2026-09-09
Branch / tree: `imp/agentcatalog` @ `65f91e54` (dev/120 closed). Line numbers pinned to that commit. `plans/` is tracked on this branch; `plans/urbanagentic/hookable-agents/knowledge-graph/` (354 MB site copy) stays untracked by intent.
Origin: the owner's brief of 2026-09-09 — *"Plan and implement an evaluation harness that measures whether the Dataflow Builder and its delegated agents can reconstruct Curio's existing example dataflows accurately from natural-language prompts. … The missing layer is model-quality evaluation: existing tests prove that saved workflows work and that the agent runtime functions, but not that a model can reconstruct those workflows correctly. Do not create another agent runtime, workflow parser, node-type classifier, or dependency installer."*
Evidence (what exists): 11 curated examples `docs/examples/[0-9][0-9]-*.json` with paired walkthroughs and 20 legacy `docs/examples/dataflows/*.json`; structural/parity/schema tests (`tests/test_frontend/test_examples.py`, `test_example_docs_parity.py`, `tests/test_projects/test_trill_schema.py` over all 31); the browser matrix `tests/test_frontend/test_workflows.py` driven by the hand-kept `conftest.py::WORKFLOW_FILES` list with example 10 skipped unless `CURIO_E2E_EXTERNAL=1`; the scripted provider `app/agents/testing_provider.py` (`api_type == "testing"`, `POST/GET/DELETE /api/testing/agent-script`) and its e2e helpers `tests/test_frontend/utils.py:2615-2694`; the in-process convention of monkeypatching `services.run_chat_completion` with a call-ordered script (`tests/test_agents/test_routes.py:4014-4075`, `TestDataflowPlanMint`); the Dataflow Builder flow — `run_attachment` (`services.py:9198`) → `_mint_dataflow_plan` (`:1389`) → `apply_proposal`/`_apply_dataflow_plan` (`:922`/`:2860`, one `write_spec` to `.curio/users/<key>/projects/<pid>/spec.trill.json`) → `solve_attachment` (`:3643`) as a detached `agent_jobs.py` job in topological waves (`_solve_waves` `:5095`) through `_verified_content_rounds` (`:5957`) behind the DEC-072 gate (`source_grounding.py`); the template roster `packages_services.available_templates`/`roster_templates` with `executable` derived per DEC-076; the lockfile authority `dataflow.packages` (`spec_packages.py`, dev/101) and the dataset refs `dataflow.datasets` (`mutations.py::_ref_from_item`, dev/81).
Evidence (what is missing): no evaluation, benchmark or golden-example code anywhere (`grep -rn "eval\|benchmark\|harness\|golden"` hits only the report-only evaluator agent, the package *backend* harness, and the e2e "ground-truth harness" wording); no fixture format that pairs a prompt with an expected dataflow; no comparator that tolerates regenerated ids and layout; no report that records provider/model/digests/usage for a live run; no fine-tuning contract on the provider abstraction (`providers.py` exposes `run_chat_completion`, `stream_chat_completion`, `list_provider_models` and nothing else — confirmed).
Evidence (a distinction found while writing this memo): example 09 declares `curio.weather@1` in `dataflow.packages` yet every one of its 13 nodes is a `curio.builtin/*` template — the package is declared for the Python libraries its manifest owns (`pythermalcomfort`, `rasterio`, `rasterstats`), which `install_to_project` reports on as `importErrors`. Example 10 is the only example whose *templates* come from a non-builtin package (`curio.streetvision/*`). So "resolution mode" is two different routes, and the fixtures name them separately (§3.5): a missing template is refused at mint, a missing library fails at Solve — and neither justifies authoring a package.
Evidence (capability gap on THIS branch): the plan grammar keeps only `from`/`to`/`toHandle` on an edge (`content.py:461-496`) and apply hardcodes `sourceHandle: "out"` (`services.py:3004-3026`); `plan_topology.py` and `edges[].kind` (dev/112, `DEC-070`, commit `6d5f89fb`) are NOT ancestors of `imp/agentcatalog` — only the memo text and a stale `__pycache__` exist. Examples 07, 08, 09 and six legacy files (`Interaction_*.json`, `Regression.json`) carry `type: "Interaction"` edges, so no plan can reconstruct them here. That is a fact the harness must report, not a threshold to lower.
Family: dev/52 (`DEC-048`, the plan → review/apply → Solve contract) → dev/93 (`DEC-062`, one vocabulary, one canonicaliser) → dev/114/115/118/119 (`DEC-072/073/075/076`, grounding, verified Solve, waves, executability from the template) → dev/120 (one runner classifier) → **dev/121**. Governance lineage: dev/11 (`DEC-058` Prompt Quality deferred; *"a candidate cannot judge/approve itself"*), dev/85 (`DEC-055` report-only evaluator; `DEC-056` no Validation/Optimization agent), dev/05 §"Prompt quality" (*"curated semantic-output rubric rather than byte equality … Provider live tests are opt-in and never required for normal CI"*).
Design decisions consumed: DEC-048, DEC-051 (merge fan-in), DEC-055 (the evaluator is never a gate), DEC-058 (Prompt Quality stays deferred — this memo is engineering test infrastructure, not that screen), DEC-062, DEC-063 (a legitimate schema-recognised decline is a success, never scored as failure), DEC-072, DEC-073, DEC-075, DEC-076, dev/101 (lockfile authority), dev/81 (dataset refs backend-owned).
Design decision proposed: **`DEC-077` — Agent quality is measured against the shipped examples by a deterministic comparator over the production plan → review/apply → Solve path. Prompts are reviewed, checked-in fixtures that never leak the expected implementation; expected graphs are compared semantically (canonical template ids, edge kinds, handles, cardinality, declared dependencies, absence of invented resources), never byte-for-byte; constructs the agent contract cannot express are named capability gaps, never lowered expectations; live-model runs are opt-in evaluation reports with recorded provider/model/digests/usage, never PR gates; the fixture format is the future fine-tuning export with immutable train/validation/held-out splits, and held-out fixtures are never training data.**
Backlog: `BL-P5-20260909-55` at first implementation change.

---

## 1. Problem Statement

**What exists proves the wrong thing for this question.** Every test over `docs/examples` starts from the saved JSON: the schema suite proves the files are valid trill, the parity suite proves the walkthrough matches the file, the browser matrix proves the saved graph renders and executes. Every agent test starts from a *scripted* reply: `TestDataflowPlanMint` proves a well-formed plan tail mints, `TestDataflowPlanApply` proves it lands, `TestVerifiedSolve` proves the loop corrects and persists. Nothing asks the question the owner asked: given only the natural-language description a person would type, does the configured model, through the real Dataflow Builder and its delegates, produce *this* dataflow? Today that question is answered by the owner running prompts by hand (dev/115 A3, dev/116 §A3.1 — *"Four passes; each failure the deterministic mirror had not predicted became a fixture"*), with no fixture corpus, no comparator, and no record beyond a memo table.

**Concretely missing.**
- A checked-in, versioned prompt fixture per example (31 of them) that names the source example and its digest, the prompt, the required datasets and packages (from `dataflow.datasets` / `dataflow.packages`, the two sources of truth), the normalized expected graph, node intents and output invariants, execution requirements, a capability tier with justified skip conditions, scoring thresholds and provenance.
- A canonical graph form and a semantic comparator: regenerated ids, layout, timestamps, `width`/`height`, `metadata.keywords`, formatting and behaviourally equivalent code must not matter; a missing node, a wrong template, a wrong edge kind or merge slot, an unresolved dependency or an invented template/package/dataset/URL must.
- A driver that walks the *production* path from an empty project — prompt → plan review card → Apply → Solve (background job) → persisted `spec.trill.json` → execution where the sandbox can run it — with a fixed, documented "user" policy for the review clicks, so two runs of one fixture differ only in what the model said.
- Three tiers that are stable in CI (unit, scripted-provider integration, representative browser e2e) and one that is not and must never pretend to be (live-model evaluation), the latter producing a report with provider, model, fixture/prompt/agent digests, attempts, latency, usage, transcripts, generated specs, diffs and categorized failures — with no secret ever written.
- A fixture format that can later be exported as prompt → expected-dataflow pairs under explicit splits, without anyone training anything by accident.

**Why it matters.** Without this, every prompt or roster change is validated by anecdote. The owner's gemma4 field test (memory: *"4/5 links broken, fetch code 400; inside Curio: mid-reply blocks"*) is exactly the class of regression the harness must catch reproducibly. And the interaction-edge gap is the class of *contract* limitation that should be visible on a scorecard as "cannot be expressed" rather than discovered per prompt.

**Expected behaviour after this memo.** `pytest tests/test_agents/test_example_reconstruction.py` runs offline in seconds and proves the pipeline is lossless for every construct the contract can express and names the ones it cannot; `python -m utk_curio.tools.agent_eval run` against a running stack with the account's configured provider writes `.curio/eval/<runId>/report.{json,md}` for the chosen tier; `agent_eval export --split validation` writes JSONL from *approved* fixtures only.

## 2. Scope

**Included.**
- Fixture schema `docs/schemas/example-prompt-fixture.v1.json` (Draft 2020-12, like `trill.v1.json`), validated the way `test_trill_schema.py` validates trill.
- Fixtures: `docs/examples/prompts/<stem>.prompt.json` for the 11 curated examples and `docs/examples/prompts/dataflows/<Name>.prompt.json` for the 20 legacy ones — 31 files, no exclusions from the corpus; exclusions from *execution* are per-fixture, visible and justified (§4.4).
- Library `utk_curio/backend/app/agents/evaluation/` — pure (no Flask, no provider, no store; the `source_grounding.py` discipline): `fixtures.py` (load, schema-validate, digests), `canonical.py` (spec → `CanonicalGraph`, reusing `packages_services.canonical_template_id` and `workflow_spec.parse_workflow_dict`), `dependencies.py` (declared refs from `dataflow.datasets` / `dataflow.packages`, referenced ids via `source_grounding.DATASET_PATH_CALL_RE`, package dirNames via `spec_packages.dir_name_from_node_type`), `compare.py` (node matching + edge diff), `scoring.py` (dimensions, weights, categories, thresholds), `oracle.py` (deterministic scripted replies from an expected graph — the reachability proof), `report.py` (run/attempt records, redaction through `utk_curio/common`'s redactor from dev/116), `export.py` (JSONL export with splits).
- Drivers (transports, outside `app/agents` so the boundary test `app/agents` ∌ `app/api` holds): `tests/test_agents/_reconstruction_driver.py` (Flask test client + monkeypatched `run_chat_completion` + monkeypatched `runner._http_exec`, the `test_verified_rounds.py:767-774` pattern) and `utk_curio/tools/agent_eval.py` (HTTP against a running stack over the public agent routes and the existing `/api/testing/*` seams; the `utk_curio/tools/preview_runner.py` precedent for an operator tool).
- Tests: unit (schema, completeness, drift, leak, canonicalization, dependency extraction, comparator, scoring, oracle, export splits), deterministic integration (plan → apply → Solve → persisted spec, provisioned and resolution modes, capability-gap recording), browser e2e (one representative fixture plus one resolution case), live-model opt-in (`--live-eval`, never default).
- One authoring aid `scripts/example_fixture_skeleton.py` that prints the canonical `expected` block and the declared dependencies of a given example so a human writes the prompt beside it — it writes nothing and never runs in tests.
- Docs: `docs/AGENT-CATALOG.md` (a section "Measuring the Dataflow Builder against the examples"), `docs/CONTRIBUTING.md` (Running Tests: the new suite and the opt-in runner), `docs/examples/prompts/README.md` (the fixture contract for humans); ledgers at closure (dev/03 `DEC-077`, dev/00 row, `BL-P5-20260909-55`, `3.1`, docs/09 note).

**Out of scope (explicitly tracked, not silently skipped).**
- Any new agent, runtime, parser, classifier or installer. The harness *calls* `_mint_dataflow_plan`, `apply_proposal`, `solve_attachment`, `DatasetCatalogService.install_dataset`, `packages_services.install_to_project`, `canonical_template_id`, `parse_workflow_dict`, `is_executable_kind`. DEC-056 forbids a Validation/Optimization agent; nothing here is one.
- Teaching the plan grammar interaction edges (dev/112 on the feat line) — the harness records `capability-gap:interaction-edge`; when dev/112 reaches this branch the same fixtures flip to scored without edits.
- The Evaluator agent as a scorer or gate (DEC-055 *"Authority: none"*; dev/11:86). An optional advisory column is a follow-up (F4), not this memo.
- Fine-tuning itself and the AI Settings **Model Training** panel — follow-up F1 with its preconditions (§3.9); no cosmetic panel.
- The DEC-058 Prompt Quality screen (versioned suites, rubrics, release gates) — this memo is engineering test infrastructure and says so in its docs section.
- dev/119 F4 (the stale comment in example 10's JSON) — an example edit; left to its own small change so fixture digests are minted once.
- Per-node durations or sizes in the runtime journal (dev/85's Optimization re-open condition #2) — the report records wall-clock per *fixture attempt*, not per node.
- Changing any example JSON or walkthrough.

## 3. Recommended Implementation Approach

### 3.1 The fixture (`example-prompt-fixture.v1`)

One JSON file per example, human-reviewed, committed:

```json
{
  "$schema": "https://curio.dev/schemas/example-prompt-fixture.v1.json",
  "fixtureId": "01-vega-lite-chained-transforms",
  "version": 1,
  "source": {"path": "docs/examples/01-vega-lite-chained-transforms.json",
             "sha256": "<digest of the example file>",
             "walkthrough": "docs/examples/01-vega-lite-chained-transforms.md"},
  "prompt": "Build a dataflow over the Project Sidewalk Chicago accessibility labels from the Data Catalog: load them once, clean and enrich the labels (agreement ratio, a four-level severity tier, EPSG:4326), then fork into two summaries — one by feature type and one by neighborhood — each feeding its own Vega-Lite chart (a bar chart and a bubble chart).",
  "context": null,
  "required": {"datasets": ["data.projectsidewalk.chicago-labels"], "packages": []},
  "expected": {
    "nodes": [{"ref": "load", "type": "curio.builtin/data-loading", "role": "loader"},
              {"ref": "clean", "type": "curio.builtin/data-transformation", "role": "transform"},
              "…"],
    "edges": [{"from": "load", "to": "clean", "kind": "data"}, "…"],
    "sources": {"datasetIds": ["data.projectsidewalk.chicago-labels"], "paths": [], "urls": ["https://vega.github.io/schema/"]}
  },
  "intents": [{"ref": "clean", "mustMention": ["agreement", "severity"], "outputKind": "geodataframe"}],
  "execution": {"mode": "sandbox", "browserOnlyKinds": ["curio.builtin/vis-vega"]},
  "capability": {"tier": "T0", "needs": [], "skip": []},
  "thresholds": {"pass": 0.90, "templates": 1.0, "topology": 0.90, "dependencies": 1.0},
  "split": "validation",
  "review": {"status": "pending-owner-review",
             "draftedBy": "claude-fable-5-1 from the example JSON and walkthrough, 2026-09-09",
             "reviewedBy": null, "reviewedAt": null},
  "notes": "The walkthrough's diagram is the prompt's shape; the prompt names no template id, node id, or code."
}
```

Rules, each pinned by a unit test (§7):
- `source.sha256` must equal the digest of the file on disk (**drift guard**: an example edit forces a fixture re-review — the test fails until the digest and, if needed, `expected` are updated by a person).
- `expected` must equal `canonical.from_spec(example)` (**completeness**: the committed expectation is exactly the example, normalized; the test recomputes and compares — it never *replaces* the committed value).
- `prompt` (and `context`) must contain none of: any node id or edge id of the example, any canonical template id string (`curio.builtin/…`), any line of any node's `content` longer than 24 characters, the word `dataflowPlan`, a `curio.v1` fence, or a JSON object (**leak guard**). Human node-kind names ("Data Transformation", "Vega-Lite") are allowed — the walkthroughs use them and so would a user.
- `required.datasets` ⊆ ids the catalog root `datasets/` ships (or, for legacy fixtures, `required.paths` under `docs/examples/data/` — the DEC-072 *user-typed path* route, so the prompt must name that path verbatim); `required.packages` ⊆ `packages/*` dirNames.
- `expected.nodes[].type` must resolve through the same template index `test_trill_schema.py::_template_index` uses.
- `capability.tier ∈ {T0,T1,T2,T3}`; `needs ⊆ {"package-enlist:templates","package-enlist:dependencies","interaction-edge","external-network","gpu","browser-only-execution"}` — the two package needs are different routes, not one (§3.5); every `skip[]` entry has `{when: "<env or need>", reason: "<sentence>"}`.
- `split ∈ {train, validation, heldout}`; `review.status ∈ {pending-owner-review, approved, rejected}`.

### 3.2 Canonical graph (`canonical.py`)

`CanonicalGraph(nodes: tuple[CNode], edges: tuple[CEdge], datasets: frozenset[str], packages: frozenset[str], sources: Sources)` where `CNode = (type: canonical id via canonical_template_id, role, executable: bool via is_executable_kind over the roster snapshot, has_content: bool)` and `CEdge = (src: int, dst: int, kind: "data"|"interaction", slot: int|None)`. `kind` is `"interaction"` when the spec edge has `type == "Interaction"` or symmetric `in/out` handles (dev/112's materialization); `slot` is the merge index parsed from `targetHandle in_N`, `None` for `DEFAULT`/`in`. Roles are derived from the template's manifest category through the roster row (`loader | transform | analysis | visualization | pool | merge | grammar | js | package:<packageId>`), never a second hand-kept table. Dropped: `id`, `x`, `y`, `width`, `height`, `timestamp`, `provenance_id`, `metadata`, `goal` text (scored separately by `intents`), `content` text (scored by execution, not string equality). Node order is irrelevant by construction: the canonical form sorts nodes by a structural key (§3.3).

### 3.3 Comparator (`compare.py`)

Small graphs (≤ 27 nodes in the corpus, `_PLAN_MAX_NODES = 200` as the hard bound) — no graph library is a dependency and none is added. Algorithm:
1. **Template multiset** — per canonical type, `expected_count` vs `actual_count` → `missing[]`, `extra[]`.
2. **Colour refinement** — three rounds of Weisfeiler–Lehman over `(type, sorted multiset of (in-neighbour colour, kind, slot), sorted multiset of (out-neighbour colour, kind))`.
3. **Matching** — nodes pair within equal colours; where a colour class has k > 1 members on both sides and edge sets still differ, bounded backtracking (k ≤ 8) picks the bijection maximizing agreed edges; larger classes fall back to greedy with the report saying so.
4. **Edge diff** under the bijection — `agreed`, `missing`, `extra`, `kindMismatch`, `slotMismatch`; interaction edges are diffed but attributed to `capability-gap:interaction-edge` when the fixture's `capability.needs` names it and the branch's contract cannot express it (the oracle proves that: §3.5).
5. **Dependencies** — set diffs on `datasets`, `packages`, `sources.datasetIds`, `sources.paths`, `sources.urls` (URL prefixes allowed per fixture; default allowlist is the vega schema host the structural test already tolerates).
6. **Fabrication** — any actual node type not in the roster snapshot, any package dirName not in the catalog, any `curio_dataset_path` id not in the catalog listing, any URL outside the allowlist → `fabricated[]`.

Output: `Comparison(matching, template_diff, edge_diff, dependency_diff, fabricated, capability_gaps)`; a pure value the scorer and the report both consume.

### 3.4 Scoring (`scoring.py`)

| Dimension | Weight | 0…1 measure |
|---|---|---|
| `templates` | 0.25 | F1 over the template multiset |
| `topology` | 0.25 | F1 over edges under the matching, an edge counts only with the right kind and slot |
| `dependencies` | 0.15 | Jaccard over declared `dataflow.datasets` ∪ `dataflow.packages` against `required` |
| `intents` | 0.15 | fraction of `intents[]` satisfied (regex over the matched node's `goal`/`intent`; `outputKind` against Solve's recorded kind when present, else `notMeasured` and excluded from the denominator) |
| `execution` | 0.20 | fraction of executable nodes whose `verification.status` is verified (`not-executable` and `browserOnlyKinds` excluded; a `pending` from a sandbox outage is `notMeasured`, never a failure — DEC-073) |

`fabricated` non-empty → total capped at 0 and category `fabrication` (a fabricated resource is never a partial credit). Categories, one per finding: `capability-gap:<need>`, `fabrication`, `missing-node`, `extra-node`, `topology`, `dependency-unresolved`, `intent-mismatch`, `execution-failed`, `refused` (the agent declined by schema — DEC-063: reported, and *not* a failure when the fixture's `skip[]` predicts it), `timeout`, `provider-error`, `harness-error`. Weights are module constants with a test pinning their sum; fixtures own only `thresholds`. The scorer reads `verification.status` on the node and `nodeRuns`, never the plan ledger's `validated` (dev/118 F6 would over-credit).

### 3.5 The oracle and the deterministic suite (`oracle.py`, `tests/test_agents/test_example_reconstruction.py`)

The oracle turns a fixture's `expected` into the scripted replies the runtime would need: one `dataflowPlan` tail (refs, canonical types, titles from `role`, intents from the fixture, `toHandle: in_N` for merge slots) and, for Solve, one content reply per executable node. **It refuses to serialize what the grammar cannot carry** — an interaction edge raises `Unrepresentable("interaction-edge")` — and the driver records that as `capability-gap:interaction-edge` for the fixture. This is the reachability proof: for every construct the contract *can* express, plan → apply → Solve → persisted spec → canonicalize → compare scores 1.0; for the rest the gap is named by the harness, not hidden by a lowered expectation.

Solve content in scripted mode is the example's own node `content` (there is no model to leak to; the docstring says so), and `runner._http_exec` is monkeypatched to return success with the kind the fixture's `intents[].outputKind` names — the `TestVerifiedSolve` pattern.

The suite, parametrized over the 31 fixtures:
- `test_reachable_or_named_gap` — oracle-driven run; assert `score == 1.0` or `capability_gaps == fixture.capability.needs ∩ {branch gaps}`.
- `test_mutations_fail_for_the_right_reason` — six oracle mutations (drop a node, swap an edge's target, change a type, add a package not in the catalog, add a `curio_dataset_path("data.invented")`, add an unlisted URL) each produce the expected category; one benign mutation (reorder nodes and edges, shift positions) scores 1.0.
- `test_provisioned_mode` — install `required.datasets` via `DatasetCatalogService.install_dataset` and `required.packages` via `install_to_project`; assert `available_templates(project)` contains the package's templates and `list_catalog(dataflow_id)` marks the dataset `installed` (the backend truth the palettes render), then the oracle run scores 1.0 with `dependencies == 1.0`.
- `test_resolution_mode_package_templates` (fixture 10, `needs: ["package-enlist:templates"]`) — leave `curio.streetvision@1` uninstalled; a plan naming `curio.streetvision/street-view-fetcher` must be **refused at mint** by `resolve_templates` with the *installed but NOT enlisted* hint (`_package_install_miss_hint`), the scripted follow-up must be the reviewed `package.install` (the ENLIST rung, dev/93), the driver's policy applies it only because `required.packages` names it, the apply returns `requiresRegistryRefresh: true`, the re-minted plan lands.
- `test_resolution_mode_package_dependencies` (fixture 09, `needs: ["package-enlist:dependencies"]`) — **the other package need, and it is not a template need at all.** Example 09 declares `curio.weather@1` while every one of its nodes is a `curio.builtin/*` template: the package is there for the Python libraries its manifest owns (`pythermalcomfort`, `rasterio`, `rasterstats`). So the plan mints and applies with the package absent, and the miss surfaces at **Solve** as an `ImportError` from the sandbox. The correct route is the same ENLIST rung — `package.install curio.weather@1`, whose apply reports `importErrors` per declared library — and the test asserts that: the run never mints a `package.draft.apply`, never proposes a new template, and after the reviewed install the same node's next Solve round passes. A missing library alone is never a reason to author a package; the dependency belongs in the owning manifest and goes through the existing resolver.
- Both resolution tests assert `package.draft.apply` was never minted (Package Builder authors only when no installed or catalog template fits — dev/89/93).
- `test_resolution_mode_dataset` — leave the dataset uninstalled; assert the run ends with either a reviewed `dataset.install` proposal (applied by policy because `required.datasets` names it) **or** Solve grounding by catalog id; the report records which route, and `dependencies` reads `dataflow.datasets` after the policy ran (open question 2 if the ref never lands).

### 3.6 Drivers and the fixed user policy

Both drivers implement one `ReconstructionDriver` protocol (`create_empty_project`, `install_and_attach_dfb`, `run_turn(prompt)`, `list_proposals`, `apply(proposal)`, `solve(node_ids)`, `wait_for_job`, `read_spec`) and one `UserPolicy`, documented in `docs/examples/prompts/README.md`:
1. Send `fixture.prompt` (plus `context` if present) once; no rephrasing, ever.
2. If the reply carries a `dataflowPlan` proposal → Apply the whole plan (no per-node edits).
3. If it carries `dataset.install` / `package.install` / `project.install` proposals → Apply **only** those whose target is in `required` (or a required delegate closure); anything else is left pending and recorded (`dependency-unrequested`).
4. Correction rounds are the runtime's (`MAX_TOOL_ROUNDS = 3`); the policy adds none.
5. After Apply → `solve(all pending)` with `verify=true`, wait for the job (bounded by `CURIO_EVAL_FIXTURE_BUDGET_S`, default 900 s, always ≤ `CURIO_SOLVE_BATCH_DEADLINE`), re-attaching through `GET …/jobs/stream` if the connection drops.
6. Read `spec.trill.json` (HTTP: `GET /api/projects/<id>`), canonicalize, compare, score.
7. Live only: up to `--attempts N` (default 1) fresh projects per fixture; the report keeps every attempt.

The in-process driver monkeypatches exactly what `test_verified_rounds.py` does; the HTTP driver uses only public routes plus `/api/testing/stub-login`, `stub-project`, `agent-script` (already the e2e seams).

### 3.7 Live-model evaluation (`utk_curio/tools/agent_eval.py`)

> **Superseded in part by dev/123 (`DEC-079`, 2026-09-09) — the delivery surface only.** The production path for a live evaluation is now **AI Settings → Evaluation mode**, an in-product service; this CLI keeps working for a REMOTE stack and keeps its opt-in. Nothing else in this memo changes: the fixtures, the leak rule, the comparator, the scoring, the capability-gap doctrine and "reports, never gates" all stand, and dev/123 shares this tier's policy and scorer rather than copying them.

`python -m utk_curio.tools.agent_eval run --backend-url http://localhost:5002 --fixtures docs/examples/prompts --tier T0,T1 [--include-external] [--attempts 1] [--out .curio/eval]`. Refuses to start unless `CURIO_EVAL_LIVE=1` is exported (the same "visible opt-in" posture as `CURIO_E2E_EXTERNAL`). Provider and model are whatever the eval account saved in AI Settings — the tool never reads, receives, or writes a key; `report.provider` records `apiType`, the base-URL host, and `model` from `GET /api/auth/me`. Per fixture attempt it records: `fixtureId`, `fixtureSha256`, `promptSha256`, `agentInstructionSha256` (the DFB prompt pin dev/95 already tracks), `rosterDigest` (sha over `available_templates` ids), `startedAt`, `latencyMs`, `usage {inputTokens, outputTokens}` from the run responses, `cost: null` unless `--price-per-mtoken IN,OUT` is passed (then labelled `operatorSupplied: true` — Curio has no price table and will not invent one, `docs/AGENT-CATALOG.md:492`), the redacted transcript (every message and content part through the dev/116 redactor), every proposal payload, the generated `spec.trill.json`, the canonical diff, the score, the categories. `report.json` is the machine record; `report.md` is a table per fixture and a category histogram. A pytest wrapper `tests/test_agents/test_live_eval.py` carries marker `live_eval`, deselected unless `--live-eval` is passed (registered beside `video`/`examples` in `tests/conftest.py:370-381`) — **never default, never CI** (dev/05:1602). Results are evaluation reports; nothing here is a release gate.

### 3.8 Fine-tuning export (`export.py`, `agent_eval export`)

`agent_eval export --split validation --out fixtures.validation.jsonl` writes one row per fixture whose `review.status == "approved"` and whose `split` matches: `{fixtureId, fixtureSha256, prompt, context, expected, required, split}`. Refuses `--split train --include heldout` and any fixture still `pending-owner-review`. There is no `train` verb: the tool exports data and stops. The prohibition is a test.

### 3.9 The Model Training panel — follow-up, gated, not built

AI Settings today manages provider/model and connection keys (`AiSettingsModal.tsx`, `ConnectionKeysSection.tsx`); `providers.py` has no fine-tuning contract. Before a panel exists its memo must define, in this order: (1) provider capability detection (a `list_fine_tuning_jobs`/`create_fine_tuning_job` contract per `api_type`, `Unavailable` rendered when absent — the dev/11:115 posture), (2) dataset consent and licensing per fixture (the example datasets' licences are in the walkthroughs; consent is a field on the export, not an assumption), (3) redaction of every exported row through the same redactor, (4) cost disclosure before the job (provider-reported, or "unknown" — never a Curio estimate), (5) job status polling and cancellation, (6) trained-model versioning as a `model_catalog.py` entry labelled with its training digest and date, (7) evaluation gates using *this* harness's held-out split, (8) activation as an explicit AI Settings choice and (9) rollback to the prior model — all reconciled with the deferred DEC-058 Prompt Quality work, and preserving *"a candidate cannot judge/approve itself"*: a fine-tuned model's held-out score is computed by this deterministic comparator, never by the model or by an agent it runs. Until that memo is approved and implemented, AI Settings gets no panel.

### 3.10 Alternatives considered

- **Byte or AST equality of node code.** Rejected: dev/03:788 and dev/05:1602 already rule *"curated semantic-output rubric rather than byte equality"*; the Solve loop legitimately produces different code that passes.
- **Scoring by the Evaluator agent.** Rejected as the gate (DEC-055 *Authority: none*, DEC-028 firewall, dev/11:86); an advisory column is F4.
- **Generating prompts at test time from the walkthroughs.** Rejected by the brief and by sense: a test that writes its own question cannot detect a prompt regression; drafting is a one-time aid, review and commit are the contract.
- **Lowering expected graphs to what the grammar can express (dropping interaction edges).** Rejected: it would silently certify a reconstruction the user would find incomplete; the gap is the finding.
- **A networkx dependency for isomorphism.** Rejected: not in `requirements.txt`, and the corpus is small enough for refinement plus bounded backtracking; the report says when greedy was used.
- **Putting fixtures under `tests/`.** Rejected: they are reviewed product artifacts and the future export corpus; `docs/examples/prompts/` sits beside what they describe. The trill scanners are unaffected: `test_examples.py` globs `[0-9][0-9]-*.json` at the top level only, and `validate_trill.py::_looks_like_trill` requires a top-level `dataflow` key the fixtures do not have (a test pins that).

### 3.11 What this is NOT

Not a Validation or Optimization agent (DEC-056). Not the DEC-058 Prompt Quality screen. Not a CI gate on model quality. Not a change to the plan grammar, the roster, any prompt byte-pin, any example, or any install path. Not a fine-tuning feature.

## 4. Data and State Handling

**Sources of truth.** The example JSON on disk is the truth for `expected` (pinned by digest + recomputation). `dataflow.datasets` / `dataflow.packages` of the *example* are the truth for `required`; of the *reconstructed spec* for the `dependencies` dimension. The roster snapshot (`available_templates` at run start) is the truth for "invented template"; the catalog listing for "invented dataset"; `packages/*` + the account store for "invented package". `verification.status` on the persisted node is the truth for execution — never the plan ledger.

**Derived values.** `CanonicalGraph`, `Comparison`, `Score` are pure functions of (fixture, spec, roster, catalog); the driver holds no derived state between steps except the project id, attachment id and proposal ids it received.

**States.** *Loading*: the HTTP driver waits on the job stream, not on polling sleeps; the in-process driver runs the job synchronously the way `TestDetachedSolveJobs` does. *Empty*: a turn that mints no proposal is `refused` (with the reply text kept) — a schema-recognised decline the fixture predicted in `skip[]` is a pass with category `refused`; otherwise a failure. *Error*: provider errors are `provider-error` with the runtime's normalized text; driver exceptions are `harness-error` with a traceback in the report, never swallowed into a score. *Success*: score ≥ `thresholds.pass` and every per-dimension threshold met.

**No stale data.** Each attempt is a fresh empty project; the driver reads the spec once after the job finishes; `requiresRegistryRefresh` on an install apply triggers a roster re-snapshot before the next turn (the report records both digests). Fixture digests are recomputed per run so a stale fixture is a failure of the *unit* suite, not a wrong score.

**Race conditions.** The solve job is one per attachment with per-user backpressure (`MAX_ACTIVE_JOBS_PER_USER = 2`); the live runner runs fixtures sequentially by default (`--parallel` is refused in v1). The in-process driver reuses the autouse `_fresh_agent_jobs` reset.

## 5. UI and UX Requirements

No product UI changes. The harness *observes* UI in the browser tier: after provisioning, the dataset palette lists the installed dataset by title and the package palette lists the weather templates (`DatasetPaletteContext`, `PackagePaletteContext`); the review card reads *Apply plan · N nodes, M edges* with N and M equal to the fixture's counts; Apply paints the nodes; the Solve strip cycles *generating → verifying — running in the sandbox → solved ✓ verified*; a reload mid-Solve re-attaches (running dot, then the same pills); the Vega node renders a canvas (`assert_vega_canvas_rendered`). `report.md` is plain Markdown readable in a terminal or a PR: one row per fixture (`fixture | tier | score | categories | attempts | latency | tokens`), a category histogram, and a header naming provider/model/digests and the count of fixtures still `pending-owner-review`. Accessibility is unaffected (no new controls).

## 6. Edge Cases

- **Example edited** → digest mismatch → unit failure naming the fixture; `expected` recomputation shows the structural delta.
- **Roster changes** (a template renamed) → `expected.nodes[].type` no longer resolves → unit failure; live report shows `rosterDigest` change.
- **Interaction edges** (07, 08, 09, six legacy) → oracle `Unrepresentable`; deterministic suite asserts the named gap; live report categorizes the missing edges as `capability-gap:interaction-edge`, not `topology`.
- **Merge-flow fan-in** (04, 09, legacy `Merge*`, `Widget`) → slots `in_0..in_4` compared by index; a plan wiring the same two inputs in swapped slots is a `slotMismatch` only when the fixture marks the merge as order-sensitive (`intents[].slotOrderMatters`), default false.
- **Data-pool fan-out** (02, 06–09, legacy `DataPool_*`) → the pool has one input and many outputs; the matcher's colour refinement distinguishes pool children by their own types.
- **Grammar/vega/js nodes** → `not-executable` in the sandbox (DEC-076) → excluded from `execution`; measured only in the browser tier (`browserOnlyKinds`).
- **Legacy relative paths** (`docs/examples/data/*.geojson|.pbf`) → the fixture's prompt names the path; DEC-072 grounds a user-typed path; the fixture declares `required.paths` and the file must exist in the checkout.
- **Example 09's package** declares `curio.weather@1` for its Python libraries while using only builtin templates — a dependency need, not a template need; scored through `dependencies` and surfaced by Solve, per §3.5.
- **Example 10** (streetvision, HF inference, street-view APIs, `spatial-join` backend endpoint) → tier T3, `needs: ["package-enlist:templates","external-network"]`, `skip: [{when: "!CURIO_EVAL_EXTERNAL", reason: "HuggingFace inference and street-view APIs; the spatial-join template has no sandbox code (dev/119)"}]`; the plan/apply half still runs offline.
- **Model declines** ("no available template fits") → `refused`; a pass only if the fixture predicted it.
- **Two identical-type sibling nodes** (05 has five loaders) → refinement by downstream structure; if truly indistinguishable, any pairing is correct by definition.
- **Solve budget exhausted** → `pending` nodes → `notMeasured` + category `timeout`, never `execution-failed`.
- **Sandbox down** → `pending` with reason (DEC-073) → `notMeasured`; the report header flags the stack.
- **Repeated live attempts** → separate projects; the report never averages away a fabrication (max category severity is carried to the fixture row).
- **Fixture `review.status` pending** → deterministic suite indifferent; live report labels; export refuses.
- **Held-out leakage** → `export --split train` cannot include `heldout` rows; a test constructs the attempt and asserts refusal.
- **Provider or key missing on the eval account** → the runner exits before creating any project with the `ProviderConfigError` text.

## 7. Testing Strategy

**Unit (`tests/test_agents/test_example_fixtures.py`, `test_reconstruction_compare.py`, `test_reconstruction_scoring.py`, `test_reconstruction_export.py`; offline, no stack):**
- schema validity of all 31 fixtures against `example-prompt-fixture.v1.json`; `check_schema` of the schema itself; one fixture per example and one example per fixture (completeness both ways over both globs);
- drift: `source.sha256` equals the file; `expected == canonical.from_spec(example)`;
- leak: the six prohibitions of §3.1 over `prompt` and `context`;
- dependencies: `required` equals the declared refs of the example (`dataflow.datasets`, `dataflow.packages`) and `sources.datasetIds` equals the `curio_dataset_path` scan (the same regex `test_dataset_path_parity.py` pins);
- canonicalization: versioned (`@1`), legacy (`DATA_LOADING`) and canonical spellings produce one `CanonicalGraph`; ids/positions/sizes/keywords never change it;
- comparator: identical → 1.0; reordered → 1.0; each mutation → its category; interaction edges → `capability-gap` when declared, `topology` when not;
- scoring: weights sum to 1; fabrication caps at 0; `notMeasured` excluded from denominators; thresholds honoured;
- oracle: every fixture serializes or raises `Unrepresentable` with the declared need; the serialized plan parses through `content.parse_dataflow_plan_verbose` (the real grammar);
- export: split filtering, approved-only, held-out refusal, row shape;
- guard: fixture files are not mistaken for trill by `validate_trill._looks_like_trill`.

**Deterministic integration (`tests/test_agents/test_example_reconstruction.py`, in-process Flask client + scripted `run_chat_completion` + faked `runner._http_exec`):** the five tests of §3.5 parametrized over fixtures (resolution-mode tests only over fixtures whose `needs` include `package-enlist`).

**Browser e2e (`tests/test_frontend/test_example_reconstruction_e2e.py`, scripted provider over HTTP, stack required as for every `test_frontend` test):** fixture 01 provisioned (palette rows visible → plan card counts → Apply → Solve strip → reload re-attach → Vega canvas) and fixture 09 resolution (package palette gains the weather templates after the reviewed install; screenshot baselines minted the existing way, opt-in to the `examples` marker).

**Live-model (`tests/test_agents/test_live_eval.py`, marker `live_eval`, `--live-eval` + `CURIO_EVAL_LIVE=1`):** runs the CLI for tier T0 and asserts only that a report was written with the required fields — the *scores* are never asserted.

Required before the change is complete: all unit and deterministic tests green in `scripts/test.sh --backend-only`; the two browser tests green against a booted stack; one live report produced by the owner against their configured provider and attached to the closure entry (scores recorded as evidence, not as a gate).

## 8. Acceptance Criteria

1. `docs/examples/prompts/` holds 31 fixtures; a unit test fails if an example lacks one or a fixture lacks an example.
2. No fixture prompt contains a node id, edge id, canonical template id, content line, plan grammar token or JSON; a test proves it.
3. The evaluated model receives only `prompt` (+ `context`) through the real `run` route; the driver never passes the example JSON, the expected graph, or node ids — asserted on the captured messages in the deterministic suite.
4. Reordering nodes and edges of a correct reconstruction scores 1.0; a missing node, wrong template, wrong topology, unresolved dependency, or fabricated template/package/dataset/URL fails with the matching category.
5. Interaction-edge examples report `capability-gap:interaction-edge` on this branch; no fixture's `expected` was weakened.
6. Provisioned mode installs through `DatasetCatalogService.install_dataset` and `packages_services.install_to_project`, and the palettes (backend listing in the deterministic suite, DOM in the browser suite) show them.
7. Resolution mode covers both package needs and never mints a `package.draft.apply`: a missing **template** is refused at mint with the not-enlisted hint and resolved by the reviewed `package.install`; a missing **library** (example 09's `curio.weather@1`, whose templates the example never uses) surfaces as a Solve `ImportError` and is resolved by the same reviewed install reporting `importErrors`. For a dataset, resolution produces `dataset.install` or catalog-grounded Solve, and the report says which.
8. The deterministic suite is offline, stack-free, and stable (no sleeps, no network, no provider).
9. The live runner refuses to start without `CURIO_EVAL_LIVE=1`, reads no key, writes `report.json`/`report.md` with provider, model, digests, attempts, latency, usage, redacted transcripts, specs, diffs and categories; `cost` is `null` unless operator-supplied.
10. `agent_eval export` writes only approved fixtures of the requested split and refuses held-out rows in a train export; no code path trains a model.
11. The Model Training panel is a tracked follow-up with the §3.9 preconditions; AI Settings is unchanged.
12. Ledgers updated at closure: dev/03 `DEC-077`, dev/00 row, `BL-P5-20260909-55`, `3.1`, docs/09 note; user docs updated.

## 9. Recommended Commit Breakdown

1. **Fixture contract + canonical form** — `docs/schemas/example-prompt-fixture.v1.json`, `app/agents/evaluation/{__init__,fixtures,canonical,dependencies}.py`, `scripts/example_fixture_skeleton.py`, unit tests (schema, canonicalization, dependencies, trill-scanner guard).
2. **The 31 fixtures** — `docs/examples/prompts/**` + `README.md`, completeness/drift/leak tests. Prompts drafted from the walkthroughs, `review.status = pending-owner-review`.
3. **Comparator + scoring + report model** — `compare.py`, `scoring.py`, `report.py`, unit tests (equivalence, mutations, weights, redaction).
4. **Oracle + deterministic suite** — `oracle.py`, `tests/test_agents/_reconstruction_driver.py`, `test_example_reconstruction.py` (reachability, mutations, provisioned, resolution ×2).
5. **Browser e2e** — `tests/test_frontend/test_example_reconstruction_e2e.py` (fixture 01 provisioned, fixture 09 resolution).
6. **Live runner + export** — `utk_curio/tools/agent_eval.py`, `export.py`, `tests/test_agents/test_live_eval.py` (`live_eval` marker + `--live-eval` option), export tests.
7. **Docs + ledgers** — `docs/AGENT-CATALOG.md`, `docs/CONTRIBUTING.md`; tracking commit: dev/03 `DEC-077`, dev/00, `BL-P5-20260909-55`, `3.1`, docs/09, this memo's status.

Each commit is a pathspec commit (`git commit -- <paths>`), no push; `plans/` changes ride separate `tracking dev/121 …` commits.

## 10. Engineering Quality Checklist

- No second node-type vocabulary, classifier, parser, or installer: `canonical_template_id`, `parse_workflow_dict`, `is_executable_kind`, `DATASET_PATH_CALL_RE`, `dir_name_from_node_type`, `install_dataset`, `install_to_project`, `_mint_dataflow_plan`, `apply_proposal`, `solve_attachment` are called, never re-implemented.
- `app/agents/evaluation/` is pure (no Flask, provider, store imports) and the boundary test (`app/agents` ∌ `app/api`) still passes; drivers live outside it.
- Types explicit (`dataclass(frozen=True)` for `CanonicalGraph`, `Comparison`, `Score`, `AttemptRecord`).
- Weights are constants with a sum test; fixtures own thresholds only.
- No sleeps: the in-process driver runs jobs synchronously; the HTTP driver waits on the job stream with a wall-clock bound.
- Redaction runs on every transcript byte before it is written; the key never enters the tool.
- Categories are an enum; every report row has at least one category or `pass`.
- The DEC-055 report-only boundary is not bypassed (no agent scores; the closure entry states it per tracking rule 17).
- Tests cover the drift guard, the leak guard, equivalence, each failure category, both dependency modes, the capability gap, the export refusals, and the live opt-in refusal.
- Docs say plainly that live scores are evaluation reports, not gates, and that the Model Training panel does not exist yet.

## 11. What the harness found while it was being built

Five of these are the harness doing its job on day one. They are recorded here
because a finding papered over is worse than no harness.

**F-a. Solve's grounding evidence never includes the conversation.**
`_solve_grounding_base` builds its evidence from the dataflow's `task`/`name`
and its target nodes' **goals** — its own docstring says *"the session-free
verified map (empty — Solve has no candidates transcript of its own)"*. So two
routes `DEC-072` documents are unreachable on the Solve path: *"a path the user
typed in this conversation"*, and *"you asked for synthetic or sample data"*. A
user who says "the file is at `docs/examples/data/back_bay.osm.pbf`" in the
Dataflow Builder chat, or "make me a small table", has given evidence the gate
will not see when Solve fills the node — it refuses with *"the user gave no such
path"*. Half the legacy fixtures and every PBF example hit this. The oracle
works **with** the contract rather than around it (a competent planner writes
the source into the node's intent, and Solve does read goals), which is why the
23 expressible fixtures reach 1.0; the inconsistency itself is follow-up F3, not
something the harness hides.

**F-b. A verified run reports no data type.** The Solve payload records each
attempt's *round* kind (`executed`, `ungrounded-source`, `upstream-blocker`) and
never the artifact's type, so a fixture's `outputKind` cannot be measured today.
Reading the round kind as a data type produced four false intent mismatches
before it was caught, so `_output_kinds` now returns nothing rather than
something plausible, and `outputKind` is `notMeasured` — the same channel dev/115
F4 and dev/118 F3 already want (F4 here).

**F-c. Attribute sorting is not a canonical form.** Fourteen of the 31 examples
failed order-independence in the first cut, because attribute-identical nodes
(example 01's three Data Transformation nodes) took their indices from file
order. The node order is now a canonical labeling — colour refinement plus
individualization, keeping the smallest edge tuple — so equality of two
canonical graphs means they are isomorphic. Exact for all 31, test-pinned per
example.

**F-d. Automorphic branches need the words.** Example 01's two aggregation
branches are structurally interchangeable, so no structural matcher can tell
"by feature type" from "by neighborhood": a correct-but-reordered plan failed its
per-node word assertions. A bounded, monotone word-based tie-break now runs
*after* the structural match, only between pairs whose swap provably cannot
change a structural finding.

**F-e. The runtime's gates fire before a bad graph exists.** An invented
template and an edge into a Data Loading node are refused by plan validation; an
invented catalog id is refused by the `DEC-072` gate before the code runs. So
through the real pipeline those mutations produce a **refusal**, which the
report must not confuse with a badly-built graph. Fabrication scoring still
stands and is unit-tested against a spec that carries one.

Smaller ones, each now a test: a proposal's target lives in its **pins**, not a
params echo; the install lanes belong to the agents that hold them
(`dataset.install` → Dataset Finder, `package.install` → Researcher, never the
Dataflow Builder); a fake sandbox must answer with a plausible data type,
because the runtime checks the produced type against the **downstream** node's
declared input ports; and content presence cannot be part of node identity,
since a plan proposes placeholders and Solve fills only what the sandbox can run.

One process note, recorded per tracking rule 11: `git stash -u` was used once on
the shared tree to check whether a failure pre-dated this work — the wrong tool
with a 354 MB untracked directory present. A throwaway `git worktree` answered
the same question safely and is the method to use.

## Open questions for the owner (non-blocking — defaults stated)

1. **Fixture home.** Default `docs/examples/prompts/` (beside the examples, exported later). Alternative: `utk_curio/backend/tests/fixtures/example_prompts/`.
2. **Dataset ref backfill.** When Solve writes a loader grounded by catalog id for a dataset the project never installed, `dataflow.datasets` may stay empty (dev/81 territory). Default: the harness *reports* `dependency-unresolved` and files a finding; it does not change the writer.
3. **DEC-077 vs. no new DEC.** Default: mint it — the "reports never gate / fixtures never leak / held-out never trains" doctrine is new and load-bearing for the Model Training follow-up.
4. **Prompt review.** All 31 prompts are model-drafted and marked pending; the owner approves (or edits) per fixture. Default: deterministic suite and live runner work meanwhile; export refuses until approved.
5. **Live report location.** Default `.curio/eval/<runId>/` (gitignored with the rest of `.curio/`), attach `report.md` to the closure entry by hand.

## Follow-ups (recorded, not delivered)

- **F1 — the AI Settings Model Training panel.** **CLOSED by dev/122 (2026-09-09,
  `DEC-078`, commits `9473e87a`…`2f621127`): the memo settled all nine
  preconditions and the panel ships — capability probed per endpoint, consent
  recorded before any upload, the provider owning the job, and activation
  refused until a held-out evaluation of that exact model id exists, computed by
  this comparator. A real fine-tune is owner-gated.** Its own memo, gated on §3.9's
  preconditions: provider capability detection, dataset consent and licensing,
  redaction, cost disclosure, job status and cancellation, trained-model
  versioning, the held-out evaluation gate computed by *this* comparator,
  activation and rollback — reconciled with the deferred `DEC-058` work, and
  preserving the rule that a model never judges itself.
- **F2 — interaction edges on this branch.** Port dev/112's `edges[].kind` and
  `plan_topology.py`; `attempt.UNEXPRESSIBLE_EDGE_KINDS` then empties and the
  eight T2 fixtures score without a fixture edit.
- **F3 — Solve-path source evidence** (F-a above). Either let a path or a
  synthetic-data request the user typed in the chat count when Solve fills a
  node, or document the node intent as the only route and say so in
  `DEC-072`'s table.
- **F4 — output kind and column schema** (F-b above), once the runtime journal
  carries them (dev/115 F4 / dev/118 F3). One function changes: `_output_kinds`.
- **F5 — an advisory Evaluator column.** Run `agent.generated-content-evaluator`
  over a reconstruction and print its verdict *beside* the deterministic score,
  labelled advisory (`DEC-055`: it has no authority, and this memo gives it
  none).
- **F6 — persisted provenance scoring**, once dev/114 F3 lands.
- **F7 — parallel live runs** (`--parallel`), honouring the per-user job
  backpressure; refused in v1.
- **F8 — owner review of the 31 prompts.** They are drafted and committed
  `pending-owner-review`; the export refuses until a person approves each one.
- **F9 — run the browser tier** on a dedicated stack (see the Status note).
