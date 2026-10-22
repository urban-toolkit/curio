# AGENTS.md

Curio is a framework for urban visual analytics built on dataflows: a React canvas, a Flask backend, and a Flask sandbox that runs node code. This file is a map of the code. The guides in `docs/` describe behavior, and `docs/ARCHITECTURE.md` describes the design.

## Layout

- `curio.py`: launcher; calls `main()` in `utk_curio/main.py`, which uses the modules in `utk_curio/cli/`.
- `utk_curio/backend/`: Flask API. `app/` has one package per feature, `migrations/` the Alembic migrations, `tests/` the pytest suites.
- `utk_curio/frontend/urban-workflows/`: React and TypeScript canvas, built with webpack. Frontend paths below start at its `src/`.
- `utk_curio/sandbox/`: Flask service that runs node Python and JavaScript and stores results as DuckDB artifacts.
- `utk_curio/llm-prompts/`: the prompts the agents share: the preamble (named `curio:default_preamble.md` in a manifest), every prompt template and the fragments they include, `package_contract.md`, and `examples.md`, the index of shipped dataflows that runs get as worked examples (`agents/application/turns/examples.py`).
- `utk_curio/common/`: code shared by backend, sandbox and the page server (`redaction.py`, `backend_address.py`).
- `utk_curio/shipped.py`: where `agents/`, `packages/`, `datasets/`, `discovery/`, `scripts/`, `vendor/` and the parts of `docs/` Curio reads are: beside `utk_curio/` in a clone, `utk_curio/_shipped/` in a pip install. Every reader of them asks it.
- `utk_curio/tools/`: operator tools outside the Flask app (`agent_eval.py`, `preview_runner.py`).
- `agents/`: shipped Agent Catalog, one directory per agent (`<agentId>@<major>/`: `manifest.json`, `prompts/`), read by `agents/domain/builtin.py` as an imported agent is; its manifest's `catalog` says card or helper and the roster's order.
- `packages/`: shipped Node and Model Catalogs, one directory per package (`manifest.json`, `sources/`, `integrity.json`); a model package (kind `model`) also holds its weights under `models/`.
- `datasets/`: shipped Data Catalog, one directory per dataset (`manifest.json`, `data/`).
- `discovery/`: Discovery Catalog sources, one `manifest.json` per source.
- `docs/`: user and developer guides; `docs/examples/` (curated dataflows, their walkthroughs, test dataflows); `docs/schemas/` (JSON Schemas: `trill.v1.json` for dataflows; `node-package.v4.json`, `dataset.v1.json`, `discovery-source.v1.json` and `agent-package.v1.json` for the catalogs' manifests; `example-prompt-fixture.v1.json` for the agent validation prompts).
- `scripts/`: developer and CI scripts (see Scripts).
- `vendor/duckdb-extensions/`: DuckDB extensions bundled with Curio.
- `.github/workflows/`: CI and release workflows (see CI); `.github/actions/`: `start-stack`, `stop-stack` (its image cleanup on self-hosted runners is `scripts/ci_image_cleanup.sh`), `image-env` (the CI image's Python packages, copied to the runner).
- `docker-compose.yml` plus overlays: `docker-compose.ci.yml`, `docker-compose.ci-shards.yml`, `docker-compose.ci-isolated.yml`, `docker-compose.ci-exec-user.yml`, `docker-compose.ci-stress.yml`, `docker-compose.deploy.yml`.

## Entry points

- `utk_curio/main.py` `main()`: the argument parser and the `setup`, `start` and `test` commands. What it calls is in `utk_curio/cli/`: `environment.py` (arguments to environment variables), `frontend_build.py`, `static_server.py`, `services.py` (start the backend, sandbox and frontend), `dependencies.py`, `test_runner.py`, `logs.py`, `lifecycle.py`, `arguments.py`.
- Backend: `utk_curio/backend/server.py` builds the app with `create_app()` from `utk_curio/backend/app/__init__.py`, which registers every blueprint. Settings: `utk_curio/backend/config.py`.
- Sandbox: `utk_curio/sandbox/server.py`. `app/api.py` holds the routes (`/exec`, `/execJs`, `/get`, `/artifact-meta`, `/monitor`); `app/worker.py` runs node code (`execute_code`, `execute_js_code`); `app/auth.py` checks the backend's token; `run_place.py` is the reply of `/exec` and `/execJs`, which keeps a run's connection busy while it waits for its place.
- Sandbox internals: `utk_curio/sandbox/isolation/` (fork isolation: `zygote.py`, `supervisor.py`, `child.py`, `hardening.py`); `utk_curio/sandbox/util/` (`db.py`, `parsers.py`, `codec.py`, `user_code.py`: the `userCode` both paths run, whose relative paths into `docs/` read the shipped files).
- Frontend: `src/index.tsx` (routes and provider nesting).

## Catalog features by layer

Each backend feature's `service.py` is its public entry point for routes and other features.

| Feature | Backend, under `utk_curio/backend/app/` | Frontend, under `src/`: services, pages, components, providers | Guide |
|---|---|---|---|
| Agents | `agents/`: `domain/`, `application/`, `infrastructure/`, `repositories/`, `routes/`, `schemas/`, `service.py`, `evaluation/` (the offline reconstruction library behind `agent_eval.py`) | `services/agents/`, `pages/agents/`, `components/agents/`, `providers/agents/` | `docs/AGENT-CATALOG.md` |
| Node packages | `packages/`: `domain/`, `application/`, `infrastructure/`, `repositories/`, `routes/`, `schemas/`, `service.py`, `builder/` | `services/packages/`, `pages/catalog/`, `components/packages/`, `providers/packages/` | `docs/NODE-CATALOG.md` |
| Datasets | `datasets/`: `domain/`, `application/`, `infrastructure/`, `repositories/`, `routes.py`, `schemas/`, `service.py`, `install/`, `models.py` | `services/datasetCatalog/`, `pages/dataCatalog/`, `components/datasets/`, `providers/datasetCatalog/` | `docs/DATA-CATALOG.md` |
| Discovery | `discovery/`: `domain/`, `application/`, `infrastructure/`, `routes.py`, `media_routes.py`, `schemas/`, `service.py`, `providers/` | `services/discoveryCatalog/`, `pages/discovery/`, `components/discovery/`, `providers/discoveryCatalog/` | `docs/DISCOVERY-CATALOG.md` |
| Models | The packages service (model packages, kind `model`, through the package routes with `?kind=model`): `packages/application/model_packages.py` (weights, listing fields, weights license, a node's models) and `model_downloads.py` (a model downloaded from the Discovery Catalog) | `services/packages/` (`modelPackages.ts`, `modelApplication.ts`, `modelCode.ts`), `pages/models/`, `components/models/`, `providers/modelCatalog/` | `docs/MODEL-CATALOG.md` |
| Scenarios | `scenario_catalog/`: `domain/`, `infrastructure/`, `routes.py`, `service.py` (reads the projects' scenarios; no storage of its own) | `services/scenarioCatalog/`, `pages/scenarios/`, `components/scenarios/catalog/`, `providers/scenarioCatalog/` | `docs/SCENARIO-CATALOG.md` |

- Backend tests per feature: `utk_curio/backend/tests/test_agents/`, `test_packages/`, `test_datasets/`, `test_discovery/`, `test_model_catalog/`, `test_scenario_catalog/`.
- Shared browse UI: `src/pages/catalog/` (`CatalogMasterPage.tsx`, `CatalogRail.tsx`) and `src/components/catalog/`.
- Layering: `utk_curio/backend/tests/_support/layering.py` is the rule engine, applied by `test_agents/test_layering.py` and `test_packages/test_layering.py`. Frontend: `src/tests/_support/layerRules.ts`, applied by `src/tests/agents/servicesBarrel.test.ts` and `src/tests/packages/servicesBarrel.test.ts`.

## Other backend features

Under `utk_curio/backend/app/`:

- `projects/`: dataflows: routes, services, storage, seeding, categories, dashboard payload.
- `runs/`: dataflow runs on the server: tables and retention (`models.py`, `repositories.py`), starting, following and cancelling one (`service.py`, `routes.py`), live runs (`jobs.py`). The engine is `execution/run_engine.py` with `execution/run_plan.py`; which outputs a run saves is `execution/save_policy.py`.
- `users/`: accounts, sessions, auth routes, capabilities, connection keys, Data source keys (`source_keys.py`), rate limits.
- `execution/`: one node run as Play does it (`node_exec.py`, behind `/processPythonCode` and `/processJavaScriptCode`), the sandbox HTTP client (`sandbox_client.py`), headless dataflow runner (`runner.py`), per-node runtime journal, sandbox token.
- `collaboration/`: real-time co-editing over Socket.IO (`events.py`, `room_state.py`).
- `monitor/`: monitor page backend: counters, stats, hardware, storage, error log.
- `notebooks/`: Jupyter notebook import (`analyzer.py`).
- `api/routes.py`: sandbox proxies, starters, file serving.
- `testing/`: test-only routes for Playwright, registered only in dev mode.
- `common/`: shared helpers (safe paths, file locks, owner-only files, user storage, egress policy, the background job registry, `record_clock.py`: the clock catalog records are dated by, `token_bucket.py`: the token bucket behind the discovery and monitor rate limits).

## Frontend core

- `src/providers/FlowProvider.tsx`: workflow state (nodes, edges, outputs, interactions) and `useFlowContext()`. Its sections are hooks in `src/providers/flow/`: `usePlayAll.ts` (Run All in the browser), `useServerRun.ts` (runs on the server, with `serverRunSteps.ts` and `src/services/runs/runsApi.ts`), `useAutoRun.ts` (a widget or Parameter change runs its stale nodes, #845), `useConnect.ts` (`onConnect`), `useGraphEdits.ts` (adding and deleting, output propagation), `useApplyOutput.ts`, `useInteractions.ts`, `useCollaborationSync.ts`, `useDashboardPins.ts`, `useInstallSave.ts`, `useNotebookView.ts` (the notebook view, with `notebookViewContext.ts`); types in `flowTypes.ts` and `flowContextTypes.ts`, Run All levels in `runLevels.ts`.
- `src/hook/useWorkflowOperations.ts`: workflow operations FlowProvider delegates (Trill loading, canvas management, suggestions).
- `src/adapters/node/`: one behavior hook per built-in node kind (`codeNodeBehavior.tsx`, `vegaBehavior.ts`, `autkGrammarBehavior.tsx`, `dataPoolBehavior.tsx`, ...), exported from `index.ts`.
- `src/components/UniversalNode.tsx`: the component that renders every node.
- `src/registry/`: node descriptors and behaviors, built from installed package manifests.
- `src/generated/`: contracts written by `scripts/generate_contracts.py` from `utk_curio/backend/app/agents/domain/contracts.py`; never edited by hand.
- `src/api/`: REST clients (projects, connection keys, LLM configurations, monitor).

## Tests

Every suite runs on GitHub CI, through `.github/workflows/docker-compose.yml`.

- Backend pytest: `utk_curio/backend/tests/`. `conftest.py` at its root and in `test_agents/`, `test_datasets/`, `test_discovery/`, `test_execution/`, `test_frontend/`, `test_model_catalog/`, `test_monitor/`, `test_packages/`, `test_projects/`, `test_runs/`, `test_scenario_catalog/`, `test_users/`. Shared helpers in `_support/`.
- E2E (Playwright): `utk_curio/backend/tests/test_frontend/`. Helpers in the `utils/` package (below), scripted walkthroughs in the `walkthroughs/` package (below), runner assignment in `runner_split.py`, sign-in skips before a test's fixtures in `early_guards.py`, author guide in `README.md`.
- E2E helpers, `test_frontend/utils/`: `from .utils import X` works for every public name; X is defined in one module, and a patch goes on the module whose code calls X (`screenshots.py` for what `save_workflow_test_screenshot` and `frame_nodes` call):
  - `environment.py`: `REPO_ROOT`, `state_root`, stack flags and public config, `require_*` skips, `debug_log`.
  - `sandbox.py`: direct sandbox calls, `load_artifact_as_dict`, `execute_workflow_programmatically`.
  - `vega_svg.py`: Vega-Lite SVG helpers.
  - `capture_waits.py`: what a capture waits for: `_wait_for_reactflow_ready`, `dismiss_toasts`, `_wait_for_webfont`, running nodes. `images.py`: captures, `_compare_images`.
  - `screenshots.py`: `save_workflow_test_screenshot`, `MAX_DIFF_RATIO`, mint and re-mint, `frame_nodes`, `dump_browser_log`.
  - `closeups.py`: `save_node_closeup`, the close-up budgets, viewport hints. `dialogs.py`: `accept_confirm_dialog`, `wait_for_drawer_closed`, `leave_agent_badge`.
  - `scenario_drawer.py`: the open dataflow's scenarios in the Scenario Catalog drawer's In project tab: `open_in_project_tab`, `in_project_card`, `scenario_card_button`, `open_scenario_details`, `scenario_part`, `close_scenario_drawer`.
  - `interactions.py`: interaction frames, brush and mark probes.
  - `tooltips.py`: the one Curio tooltip as a test reads it: `rest_pointer_on` and `hover_until_tooltip_says` (a fresh hover), `one_tooltip`, `tooltip_saying`, `no_tooltip`, `editor_chip_box` (a chip's box in an editor), and `tooltip_close_up`, the clip of a tooltip's frame.
  - `servers.py`: ports, `e2e_existing_servers`, `serve_built_frontend` (the production page server on the built bundle, host-side).
  - `auth.py`: UI signup, the projects page, `require_owner_view`.
  - `db_stubs.py`: `stub_db_user`, `stub_db_login`, `stub_login_and_enter_workflow`, `api_json`.
  - `catalog_clock.py`: `CATALOG_CALENDAR`, the fixed date that tests marked `catalog_calendar` run on (conftest.py).
  - `palettes.py`: tool palettes. `upload.py`: `upload_workflow`. `page.py`: `FrontendPage`.
  - `canvas_authoring.py`: `drag_to_canvas`, `drag_builtin_to_canvas` (a built-in tile, through the rail's Built-in palette), `drag_to_canvas_with_the_mouse`, `connect_nodes`, `set_node_code`, `play_node`, `run_node_and_wait`.
  - `run_all.py`: Run All state, holding a run open.
  - `node_drawings.py`: `assert_vega_canvas_rendered`, `assert_autark_map_drawn` and the other drawing checks.
  - `webgpu.py`: `require_webgpu` and `webgpu_adapter`, which ask for a WebGPU adapter through the app's own probe (`window.__curio_probeWebGpu`, `src/utils/webgpuSupport.ts`): it waits for a drawn frame, then asks again after a null for up to 3 s. While the page has drawn no frame and no adapter came, the helper runs the probe again, for up to a minute.
  - `offline_install.py`: `offline_catalog_package`, a test package from `test_frontend/packages/` in the backend's catalog with its libraries in a local wheelhouse (`/api/testing/wheelhouse`, `/api/testing/catalog-package`); `offline_package` reads a test package's manifest; the wheels come from `tests/_support/offline_wheels.py`.
  - `scripted_llm.py`: scripted agent turns.
- Walkthroughs, `test_frontend/walkthroughs/`: importing a scene module registers its scenes in `WALKTHROUGHS`, and `__init__.py` imports them in registry order:
  - `framework.py`: `Narrator`, `SilentNarrator`, `Ctx`, `Walkthrough`, `FULL_PAGE_DIFF_FLOOR`, `WALKTHROUGHS` and the `@walkthrough` decorator.
  - `steps.py`: shared steps: `load_example_spec`, `first_node_of_type`, `frame_until_on_top`, the provenance drawer, canvas counts.
  - Scenes, one module per surface: `provenance.py`, `agent_catalog.py`, `cross_catalog.py`, `account_examples.py`, `robustness.py` (dashboard page, Autark without WebGPU, Run All after a failed node), `layout.py`, `visual_claims.py` (#218 to #227), `dataflow_identity.py`, `catalog_chrome.py`, `column_filter.py`, `agent_chat.py`, `simple_view.py`.
- Sandbox: `utk_curio/sandbox/tests/` (`conftest.py`).
- Frontend Jest: `src/tests/` (guide in `src/tests/README.md`); `npm test` and `npm run typecheck` in `utk_curio/frontend/urban-workflows/`.
- Stress harness: `utk_curio/backend/tests/stress/`.

## CI

`.github/workflows/docker-compose.yml` jobs:

- `pick-runners`: picks the runners of the jobs that start at once (`scripts/ci_pick_runners.py`).
- `build-image`: builds the CI image once per commit, pushes it to GHCR, then picks the runners of the jobs that wait on it. Built with the Dockerfile's `CURIO_CI_SETUP=1`, it also holds what `curio.py setup --with-examples` installs, so CI stacks boot with `CURIO_SKIP_DEP_INSTALL=1` and the jobs run `scripts/test.sh --skip-setup`.
- `test-gpu`: e2e tests that need WebGPU, on a GPU runner.
- `unit`: backend pytest in four parts, plus the sandbox suite.
- `jest`: Jest and `npm run typecheck`.
- `e2e-desktop`: e2e tests without WebGPU, split over CPU runners.
- `test-isolated`: Python-node workflows on the fork-isolated stack (`docker-compose.ci-isolated.yml`).
- `test-exec-user`: isolation with an execution account (`docker-compose.ci-exec-user.yml`).
- `preview-runner`: preview runner tests (`utk_curio/tools/preview_runner.py`) in headless Chromium.
- `test-desktop-stress`: memory replay and 1, 5 and 10 user stress on `ubuntu-latest`.
- `test-gpu-stress`: 5 to 100 user stress tiers; on the schedule, a `stress` PR label, or dispatch.
- `ci-report`: one HTML report for the run (`scripts/ci_report.py`); checks that every test ran.
- Dispatch inputs: `stress`, `remint` with `remint_filter`, `remint_force` and `remint_gpu_kind` (re-mints screenshot baselines into the `reminted-baselines` artifact; `remint_gpu_kind` writes named frames as baselines of one GPU kind, `<name>.<kind>.png`, see the test_frontend README), and `repeat` (unit, jest, e2e-desktop, test-gpu and test-isolated run their suite that many times through `scripts/ci_repeat.sh`, and test-gpu-stress runs with its stages repeated; the CI report lists the tests that passed in one run and failed in another).

Other workflows: `autk-schema.yml` (weekly check of the vendored Autark schema), `weekly-flake-hunt.yml` (Saturdays: the Full stack build on main with `repeat` 10), `bump-version.yml` (version bump on main), `deploy.yml` (deploys main), `publish-pip-to-pypi.yml` (PyPI on release); manual diagnostics `e2e-autark-repro.yml`, `rerun-memory-repro.yml`, `zygote-fork-crash-repro.yml`.

## Scripts

- `scripts/test.sh`: boots and runs each suite; CI calls it and `curio test` wraps it.
- `scripts/clean.sh`: removes build artifacts and runtime data. `scripts/kill-curio.sh`: kills leftover Curio server processes.
- `scripts/new_package.py`: scaffolds a node package. `scripts/regen_integrity.py`: rewrites a package's `integrity.json`.
- `scripts/generate_contracts.py`: writes `src/generated/` and the prompt rendered from each `utk_curio/llm-prompts/X.template.md`, into the folder in `agents/` whose manifest names `prompts/X.md`, else beside the template; `--check` lists stale outputs.
- `scripts/ci_requirements.py`: writes `scripts/ci-requirements.txt`, the libraries `curio.py setup --with-examples` installs from the manifests, which CI's image installs before its source; rerun it after changing a manifest's Python dependencies or the packages an example declares (`test_ci_requirements.py` fails on a stale list).
- `scripts/sync_autk_schema.py`: vendors the Autark grammar schema; `--check` compares it with the release.
- `scripts/validate_trill.py`: validates dataflow JSON against `docs/schemas/trill.v1.json`.
- Release (`publish-pip-to-pypi.yml`): the catalog files the pip package leaves out are those the dataset and model package manifests name in `downloadOnFirstUse`, read by `utk_curio/shipped.py` and fetched on first use by `utk_curio/backend/app/datasets/infrastructure/left_out_files.py`; `scripts/record_left_out_files.py` records them; `scripts/check_dist_sizes.py` fails a wheel or sdist over PyPI's 100 MiB limit; `setup.py` lists the wheel's packages, puts the shipped folders in it at `utk_curio/_shipped/` (`utk_curio/shipped.py`), copies the root `package.json` and `package-lock.json` into it (`utk_curio/sandbox/nodejs/`), and leaves the named files out of both archives (its `egg_info`).
- Example builders: `scripts/build_example_*.py`. Test fixtures: `scripts/record_discovery_fixtures.py` and the `generate_*_fixture.py` scripts. CI helpers: `scripts/ci_*.py` and the shard balancers `e2e_*.py`, `unit_durations.py`.

## Big files

Several files run past 1,500 lines. List their sections, then Read only the range you need:

- The e2e helpers (`test_frontend/utils/`) and walkthroughs (`test_frontend/walkthroughs/`) are packages of modules, listed under Tests.
- Test modules with one class per area: `grep -n '^class Test' <file>`.
- FlowProvider's sections are hooks in `src/providers/flow/`, listed under Frontend core.

## Do not read

Generated, vendored or data files:

- `src/components/vega-schema.json`, `package-lock.json` and `utk_curio/frontend/urban-workflows/package-lock.json`, `*.js.map`.
- `*.geojson`, `datasets/*/data/`, `packages/*/models/`, `vendor/`.
- `utk_curio/backend/tests/test_discovery/fixtures/` (recorded portal responses).
- `docs/examples/dataflows/expected_outputs/` (screenshot baselines).
- A prompt `X.md` when `utk_curio/llm-prompts/` holds an `X.template.md` (the preamble and `package_contract.md` there, most agent instructions in `agents/*/prompts/`): generated; edit the template or `contracts.py`, then run `scripts/generate_contracts.py`.
- `test_feature_tour_video.py`, `test_stress_tour_video.py`, `test_user_stress_video.py` in `test_frontend/`, unless working on the video tours.
