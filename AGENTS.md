# AGENTS.md

Curio is a framework for urban visual analytics built on dataflows: a React canvas, a Flask backend, and a Flask sandbox that runs node code. This file is a map of the code. The guides in `docs/` describe behavior, and `docs/ARCHITECTURE.md` describes the design.

## Layout

- `curio.py`: launcher; calls `main()` in `utk_curio/main.py`, which uses the modules in `utk_curio/cli/`.
- `utk_curio/backend/`: Flask API. `app/` has one package per feature, `migrations/` the Alembic migrations, `tests/` the pytest suites.
- `utk_curio/frontend/urban-workflows/`: React and TypeScript canvas, built with webpack. Frontend paths below start at its `src/`.
- `utk_curio/sandbox/`: Flask service that runs node Python and JavaScript and stores results as DuckDB artifacts.
- `utk_curio/llm-prompts/`: built-in agent prompts, and `examples.md`, the index of shipped dataflows that runs get as worked examples (`agents/application/turns/examples.py`).
- `utk_curio/common/`: code shared by backend and sandbox (`redaction.py`).
- `utk_curio/tools/`: operator tools outside the Flask app (`agent_eval.py`, `preview_runner.py`).
- `packages/`: shipped Node Catalog, one directory per node package (`manifest.json`, `sources/`, `integrity.json`).
- `datasets/`: shipped Data Catalog, one directory per dataset (`manifest.json`, `data/`).
- `discovery/`: Discovery Catalog sources, one `manifest.json` per source.
- `models/`: shipped Model Catalog, one directory per model.
- `docs/`: user and developer guides; `docs/examples/` (curated dataflows, their walkthroughs, test dataflows); `docs/schemas/` (`trill.v1.json`).
- `scripts/`: developer and CI scripts (see Scripts).
- `vendor/duckdb-extensions/`: DuckDB extensions bundled with Curio.
- `.github/workflows/`: CI and release workflows (see CI); `.github/actions/`: `start-stack`, `stop-stack`.
- `docker-compose.yml` plus overlays: `docker-compose.ci.yml`, `docker-compose.ci-shards.yml`, `docker-compose.ci-isolated.yml`, `docker-compose.ci-exec-user.yml`, `docker-compose.ci-stress.yml`, `docker-compose.deploy.yml`.

## Entry points

- `utk_curio/main.py` `main()`: the argument parser and the `setup`, `start` and `test` commands. What it calls is in `utk_curio/cli/`: `environment.py` (arguments to environment variables), `frontend_build.py`, `static_server.py`, `services.py` (start the backend, sandbox and frontend), `dependencies.py`, `test_runner.py`, `logs.py`, `lifecycle.py`, `arguments.py`.
- Backend: `utk_curio/backend/server.py` builds the app with `create_app()` from `utk_curio/backend/app/__init__.py`, which registers every blueprint. Settings: `utk_curio/backend/config.py`.
- Sandbox: `utk_curio/sandbox/server.py`. `app/api.py` holds the routes (`/exec`, `/execJs`, `/get`, `/artifact-meta`, `/monitor`); `app/worker.py` runs node code (`execute_code`, `execute_js_code`); `app/auth.py` checks the backend's token.
- Sandbox internals: `utk_curio/sandbox/isolation/` (fork isolation: `zygote.py`, `supervisor.py`, `child.py`, `hardening.py`); `utk_curio/sandbox/util/` (`db.py`, `parsers.py`, `codec.py`).
- Frontend: `src/index.tsx` (routes and provider nesting).

## Catalog features by layer

Each backend feature's `service.py` is its public entry point for routes and other features.

| Feature | Backend, under `utk_curio/backend/app/` | Frontend, under `src/`: services, pages, components, providers | Guide |
|---|---|---|---|
| Agents | `agents/`: `domain/`, `application/`, `infrastructure/`, `repositories/`, `routes/`, `schemas/`, `service.py`, `evaluation/` (the offline reconstruction library behind `agent_eval.py`) | `services/agents/`, `pages/agents/`, `components/agents/`, `providers/agents/` | `docs/AGENT-CATALOG.md` |
| Node packages | `packages/`: `domain/`, `application/`, `infrastructure/`, `repositories/`, `routes/`, `schemas/`, `service.py`, `builder/` | `services/packages/`, `pages/catalog/`, `components/packages/`, `providers/packages/` | `docs/NODE-CATALOG.md` |
| Datasets | `datasets/`: `domain/`, `application/`, `infrastructure/`, `repositories/`, `routes.py`, `schemas/`, `service.py`, `install/`, `models.py` | `services/datasetCatalog/`, `pages/dataCatalog/`, `components/datasets/`, `providers/datasetCatalog/` | `docs/DATA-CATALOG.md` |
| Discovery | `discovery/`: `domain/`, `application/`, `infrastructure/`, `routes.py`, `media_routes.py`, `schemas/`, `service.py`, `providers/` | `services/discoveryCatalog/`, `pages/discovery/`, `components/discovery/`, `providers/discoveryCatalog/` | `docs/DISCOVERY-CATALOG.md` |
| Models | `model_catalog/`: `domain/`, `infrastructure/`, `routes.py`, `service.py` | `services/modelCatalog/`, `pages/models/`, `components/models/`, `providers/modelCatalog/` | `docs/MODEL-CATALOG.md` |
| Scenarios | `scenario_catalog/`: `domain/`, `infrastructure/`, `routes.py`, `service.py` (reads the projects' scenarios; no storage of its own) | `services/scenarioCatalog/`, `pages/scenarios/`, `components/scenarios/catalog/`, `providers/scenarioCatalog/` | `docs/SCENARIO-CATALOG.md` |

- Backend tests per feature: `utk_curio/backend/tests/test_agents/`, `test_packages/`, `test_datasets/`, `test_discovery/`, `test_model_catalog/`, `test_scenario_catalog/`.
- Shared browse UI: `src/pages/catalog/` (`CatalogMasterPage.tsx`, `CatalogRail.tsx`) and `src/components/catalog/`.
- Layering: `utk_curio/backend/tests/_support/layering.py` is the rule engine, applied by `test_agents/test_layering.py` and `test_packages/test_layering.py`. Frontend: `src/tests/_support/layerRules.ts`, applied by `src/tests/agents/servicesBarrel.test.ts` and `src/tests/packages/servicesBarrel.test.ts`.

## Other backend features

Under `utk_curio/backend/app/`:

- `projects/`: dataflows: routes, services, storage, seeding, categories, dashboard payload.
- `runs/`: dataflow runs on the server: tables and retention (`models.py`, `repositories.py`), starting, following and cancelling one (`service.py`, `routes.py`), live runs (`jobs.py`). The engine is `execution/run_engine.py` with `execution/run_plan.py`; which outputs a run saves is `execution/save_policy.py`.
- `users/`: accounts, sessions, auth routes, capabilities, connection keys, rate limits.
- `execution/`: one node run as Play does it (`node_exec.py`, behind `/processPythonCode` and `/processJavaScriptCode`), the sandbox HTTP client (`sandbox_client.py`), headless dataflow runner (`runner.py`), per-node runtime journal, sandbox token.
- `collaboration/`: real-time co-editing over Socket.IO (`events.py`, `room_state.py`).
- `monitor/`: monitor page backend: counters, stats, hardware, storage, error log.
- `notebooks/`: Jupyter notebook import (`analyzer.py`).
- `api/routes.py`: sandbox proxies, starters, file serving.
- `testing/`: test-only routes for Playwright, registered only in dev mode.
- `common/`: shared helpers (safe paths, file locks, owner-only files, user storage, egress policy, the background job registry).

## Frontend core

- `src/providers/FlowProvider.tsx`: workflow state (nodes, edges, outputs, interactions) and `useFlowContext()`. Its sections are hooks in `src/providers/flow/`: `usePlayAll.ts` (Run All), `useConnect.ts` (`onConnect`), `useGraphEdits.ts` (adding and deleting, output propagation), `useApplyOutput.ts`, `useInteractions.ts`, `useCollaborationSync.ts`, `useDashboardPins.ts`, `useInstallSave.ts`; types in `flowTypes.ts` and `flowContextTypes.ts`, Run All levels in `runLevels.ts`.
- `src/hook/useWorkflowOperations.ts`: workflow operations FlowProvider delegates (Trill loading, canvas management, suggestions).
- `src/adapters/node/`: one behavior hook per built-in node kind (`codeNodeBehavior.tsx`, `vegaBehavior.ts`, `autkGrammarBehavior.tsx`, `dataPoolBehavior.tsx`, ...), exported from `index.ts`.
- `src/components/UniversalNode.tsx`: the component that renders every node.
- `src/registry/`: node descriptors and behaviors, built from installed package manifests.
- `src/generated/`: contracts written by `scripts/generate_contracts.py` from `utk_curio/backend/app/agents/domain/contracts.py`; never edited by hand.
- `src/api/`: REST clients (projects, connection keys, LLM configurations, monitor).

## Tests

Every suite runs on GitHub CI, through `.github/workflows/docker-compose.yml`.

- Backend pytest: `utk_curio/backend/tests/`. `conftest.py` at its root and in `test_agents/`, `test_datasets/`, `test_discovery/`, `test_execution/`, `test_frontend/`, `test_model_catalog/`, `test_monitor/`, `test_packages/`, `test_projects/`, `test_runs/`, `test_scenario_catalog/`, `test_users/`. Shared helpers in `_support/`.
- E2E (Playwright): `utk_curio/backend/tests/test_frontend/`. Helpers in the `utils/` package (below), scripted walkthroughs in the `walkthroughs/` package (below), runner assignment in `runner_split.py`, author guide in `README.md`.
- E2E helpers, `test_frontend/utils/`: `from .utils import X` works for every public name; X is defined in one module, and a patch goes on the module whose code calls X (`screenshots.py` for what `save_workflow_test_screenshot` and `frame_nodes` call):
  - `environment.py`: `REPO_ROOT`, `state_root`, stack flags and public config, `require_*` skips, `debug_log`.
  - `sandbox.py`: direct sandbox calls, `load_artifact_as_dict`, `execute_workflow_programmatically`.
  - `vega_svg.py`: Vega-Lite SVG helpers.
  - `capture_waits.py`: what a capture waits for: `_wait_for_reactflow_ready`, `dismiss_toasts`, `_wait_for_webfont`, running nodes. `images.py`: captures, `_compare_images`.
  - `screenshots.py`: `save_workflow_test_screenshot`, `MAX_DIFF_RATIO`, mint and re-mint, `frame_nodes`, `dump_browser_log`.
  - `closeups.py`: `save_node_closeup`, the close-up budgets, viewport hints. `dialogs.py`: `accept_confirm_dialog`, `leave_agent_badge`.
  - `interactions.py`: interaction frames, brush and mark probes.
  - `servers.py`: ports, `e2e_existing_servers`.
  - `auth.py`: UI signup, the projects page, `require_owner_view`.
  - `db_stubs.py`: `stub_db_user`, `stub_db_login`, `stub_login_and_enter_workflow`, `api_json`.
  - `palettes.py`: tool palettes. `upload.py`: `upload_workflow`. `page.py`: `FrontendPage`.
  - `canvas_authoring.py`: `drag_to_canvas`, `connect_nodes`, `set_node_code`, `play_node`, `run_node_and_wait`.
  - `run_all.py`: Run All state, holding a run open.
  - `node_drawings.py`: `assert_vega_canvas_rendered`, `assert_autark_map_drawn` and the other drawing checks.
  - `scripted_llm.py`: scripted agent turns.
- Walkthroughs, `test_frontend/walkthroughs/`: importing a scene module registers its scenes in `WALKTHROUGHS`, and `__init__.py` imports them in registry order:
  - `framework.py`: `Narrator`, `SilentNarrator`, `Ctx`, `Walkthrough`, `FULL_PAGE_DIFF_FLOOR`, `WALKTHROUGHS` and the `@walkthrough` decorator.
  - `steps.py`: shared steps: `load_example_spec`, `first_node_of_type`, `frame_until_on_top`, the Provenance window, canvas counts.
  - Scenes, one module per surface: `provenance.py`, `agent_catalog.py`, `cross_catalog.py`, `account_examples.py`, `robustness.py` (dashboard page, Autark without WebGPU, Run All after a failed node), `layout.py`, `visual_claims.py` (#218 to #227), `dataflow_identity.py`, `catalog_chrome.py`, `column_filter.py`, `agent_chat.py`, `simple_view.py`.
- Sandbox: `utk_curio/sandbox/tests/` (`conftest.py`).
- Frontend Jest: `src/tests/` (guide in `src/tests/README.md`); `npm test` and `npm run typecheck` in `utk_curio/frontend/urban-workflows/`.
- Stress harness: `utk_curio/backend/tests/stress/`.

## CI

`.github/workflows/docker-compose.yml` jobs:

- `pick-runners`: picks the runner for each job (`scripts/ci_pick_runners.py`).
- `build-image`: builds the CI image once per commit and pushes it to GHCR.
- `test-gpu`: e2e tests that need WebGPU, on a GPU runner.
- `unit`: backend pytest in two parts, plus the sandbox suite.
- `jest`: Jest and `npm run typecheck`.
- `e2e-desktop`: e2e tests without WebGPU, split over CPU runners.
- `test-isolated`: Python-node workflows on the fork-isolated stack (`docker-compose.ci-isolated.yml`).
- `test-exec-user`: isolation with an execution account (`docker-compose.ci-exec-user.yml`).
- `preview-runner`: preview runner tests (`utk_curio/tools/preview_runner.py`) in headless Chromium.
- `test-desktop-stress`: memory replay and 1, 5 and 10 user stress on `ubuntu-latest`.
- `test-gpu-stress`: 5 to 100 user stress tiers; on the schedule, a `stress` PR label, or dispatch.
- `ci-report`: one HTML report for the run (`scripts/ci_report.py`); checks that every test ran.
- Dispatch inputs: `stress`, and `remint` with `remint_filter` and `remint_force` (re-mints screenshot baselines into the `reminted-baselines` artifact).

Other workflows: `autk-schema.yml` (weekly check of the vendored Autark schema), `bump-version.yml` (version bump on main), `deploy.yml` (deploys main), `publish-pip-to-pypi.yml` (PyPI on release); manual diagnostics `e2e-autark-repro.yml`, `rerun-memory-repro.yml`, `zygote-fork-crash-repro.yml`.

## Scripts

- `scripts/test.sh`: boots and runs each suite; CI calls it and `curio test` wraps it.
- `scripts/clean.sh`: removes build artifacts and runtime data. `scripts/kill-curio.sh`: kills leftover Curio server processes.
- `scripts/new_package.py`: scaffolds a node package. `scripts/regen_integrity.py`: rewrites a package's `integrity.json`.
- `scripts/generate_contracts.py`: writes `src/generated/` and every `utk_curio/llm-prompts/X.md` that has an `X.template.md`; `--check` lists stale outputs.
- `scripts/sync_autk_schema.py`: vendors the Autark grammar schema; `--check` compares it with the release.
- `scripts/validate_trill.py`: validates dataflow JSON against `docs/schemas/trill.v1.json`.
- Example builders: `scripts/build_example_*.py`. Test fixtures: `scripts/record_discovery_fixtures.py` and the `generate_*_fixture.py` scripts. CI helpers: `scripts/ci_*.py` and the shard balancers `e2e_*.py`, `unit_durations.py`.

## Big files

Several files run past 1,500 lines. List their sections, then Read only the range you need:

- The e2e helpers (`test_frontend/utils/`) and walkthroughs (`test_frontend/walkthroughs/`) are packages of modules, listed under Tests.
- Test modules with one class per area: `grep -n '^class Test' <file>`.
- FlowProvider's sections are hooks in `src/providers/flow/`, listed under Frontend core.

## Do not read

Generated, vendored or data files:

- `src/components/vega-schema.json`, `package-lock.json` and `utk_curio/frontend/urban-workflows/package-lock.json`, `*.js.map`.
- `*.geojson`, `datasets/*/data/`, `models/*/files/`, `vendor/`.
- `utk_curio/backend/tests/test_discovery/fixtures/` (recorded portal responses).
- `docs/examples/dataflows/expected_outputs/` (screenshot baselines).
- `utk_curio/llm-prompts/X.md` when an `X.template.md` sits beside it (the preamble, most agent instructions, `package_contract.md`): generated; edit the template or `contracts.py`, then run `scripts/generate_contracts.py`.
- `test_feature_tour_video.py`, `test_stress_tour_video.py`, `test_user_stress_video.py` in `test_frontend/`, unless working on the video tours.
