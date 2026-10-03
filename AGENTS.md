# AGENTS.md

Curio is a framework for urban visual analytics built on dataflows: a React canvas, a Flask backend, and a Flask sandbox that runs node code. This file is a map of the code. The guides in `docs/` describe behavior, and `docs/ARCHITECTURE.md` describes the design.

## Layout

- `curio.py`: launcher; calls `main()` in `utk_curio/main.py`, which uses the modules in `utk_curio/cli/`.
- `utk_curio/backend/`: Flask API. `app/` has one package per feature, `migrations/` the Alembic migrations, `tests/` the pytest suites.
- `utk_curio/frontend/urban-workflows/`: React and TypeScript canvas, built with webpack. Frontend paths below start at its `src/`.
- `utk_curio/sandbox/`: Flask service that runs node Python and JavaScript and stores results as DuckDB artifacts.
- `utk_curio/llm-prompts/`: built-in agent prompts.
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
| Agents | `agents/`: `domain/`, `application/`, `infrastructure/`, `repositories/`, `routes/`, `schemas/`, `service.py`, `evaluation/`, `training/` | `services/agents/`, `pages/agents/`, `components/agents/`, `providers/agents/` | `docs/AGENT-CATALOG.md` |
| Node packages | `packages/`: `domain/`, `application/`, `infrastructure/`, `repositories/`, `routes/`, `schemas/`, `service.py`, `builder/` | `services/packages/`, `pages/catalog/`, `components/packages/`, `providers/packages/` | `docs/NODE-CATALOG.md` |
| Datasets | `datasets/`: `domain/`, `application/`, `infrastructure/`, `repositories/`, `routes.py`, `schemas/`, `service.py`, `install/`, `models.py` | `services/datasetCatalog/`, `pages/dataCatalog/`, `components/datasets/`, `providers/datasetCatalog/` | `docs/DATA-CATALOG.md` |
| Discovery | `discovery/`: `domain/`, `application/`, `infrastructure/`, `routes.py`, `media_routes.py`, `schemas/`, `service.py`, `providers/` | `services/discoveryCatalog/`, `pages/discovery/`, `components/discovery/`, `providers/discoveryCatalog/` | `docs/DISCOVERY-CATALOG.md` |
| Models | `model_catalog/`: `domain/`, `infrastructure/`, `routes.py`, `service.py` | `services/modelCatalog/`, `pages/models/`, `components/models/`, `providers/modelCatalog/` | `docs/MODEL-CATALOG.md` |

- Backend tests per feature: `utk_curio/backend/tests/test_agents/`, `test_packages/`, `test_datasets/`, `test_discovery/`, `test_model_catalog/`.
- Shared browse UI: `src/pages/catalog/` (`CatalogMasterPage.tsx`, `CatalogRail.tsx`) and `src/components/catalog/`.
- Layering: `utk_curio/backend/tests/_support/layering.py` is the rule engine, applied by `test_agents/test_layering.py` and `test_packages/test_layering.py`. Frontend: `src/tests/_support/layerRules.ts`, applied by `src/tests/agents/servicesBarrel.test.ts` and `src/tests/packages/servicesBarrel.test.ts`.

## Other backend features

Under `utk_curio/backend/app/`:

- `projects/`: dataflows: routes, services, storage, seeding, categories, dashboard payload.
- `users/`: accounts, sessions, auth routes, capabilities, connection keys, rate limits.
- `execution/`: headless dataflow runner (`runner.py`), per-node runtime journal, sandbox token.
- `collaboration/`: real-time co-editing over Socket.IO (`events.py`, `room_state.py`).
- `monitor/`: monitor page backend: counters, stats, hardware, storage, error log.
- `notebooks/`: Jupyter notebook import (`analyzer.py`).
- `api/routes.py`: sandbox proxies, starters, file serving.
- `testing/`: test-only routes for Playwright, registered only in dev mode.
- `common/`: shared helpers (safe paths, file locks, owner-only files, user storage, egress policy).

## Frontend core

- `src/providers/FlowProvider.tsx`: workflow state (nodes, edges, outputs, interactions, propagation, Run All) and `useFlowContext()`.
- `src/hook/useWorkflowOperations.ts`: workflow operations FlowProvider delegates (Trill loading, canvas management, suggestions).
- `src/adapters/node/`: one behavior hook per built-in node kind (`codeNodeBehavior.tsx`, `vegaBehavior.ts`, `autkGrammarBehavior.tsx`, `dataPoolBehavior.tsx`, ...), exported from `index.ts`.
- `src/components/UniversalNode.tsx`: the component that renders every node.
- `src/registry/`: node descriptors and behaviors, built from installed package manifests.
- `src/generated/`: contracts written by `scripts/generate_contracts.py` from `utk_curio/backend/app/agents/domain/contracts.py`; never edited by hand.
- `src/api/`: REST clients (projects, connection keys, LLM configurations, monitor, evaluation, training).

## Tests

Every suite runs on GitHub CI, through `.github/workflows/docker-compose.yml`.

- Backend pytest: `utk_curio/backend/tests/`. `conftest.py` at its root and in `test_agents/`, `test_datasets/`, `test_discovery/`, `test_execution/`, `test_frontend/`, `test_model_catalog/`, `test_monitor/`, `test_packages/`, `test_projects/`, `test_users/`. Shared helpers in `_support/`.
- E2E (Playwright): `utk_curio/backend/tests/test_frontend/`. Helpers in `utils.py`, scripted walkthroughs in `walkthroughs.py`, runner assignment in `runner_split.py`, author guide in `README.md`.
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
- `scripts/generate_contracts.py`: writes `src/generated/` and `utk_curio/llm-prompts/default_preamble.md`; `--check` lists stale outputs.
- `scripts/sync_autk_schema.py`: vendors the Autark grammar schema; `--check` compares it with the release.
- `scripts/validate_trill.py`: validates dataflow JSON against `docs/schemas/trill.v1.json`.
- Example builders: `scripts/build_example_*.py`. Test fixtures: `scripts/record_discovery_fixtures.py` and the `generate_*_fixture.py` scripts. CI helpers: `scripts/ci_*.py` and the shard balancers `e2e_*.py`, `unit_durations.py`.

## Big files

Several files run past 1,500 lines. List their sections, then Read only the range you need:

- `utk_curio/backend/tests/test_frontend/utils.py` and `walkthroughs.py`: section banners, `grep -n -A1 '^# ----' <file>`.
- Test modules with one class per area: `grep -n '^class Test' <file>`.
- `src/providers/FlowProvider.tsx`: `grep -n 'useCallback(' <file>` lists its operations; Run All is around `playAllNodes`; collaboration sync starts at the comment `Collaboration: receive-side`.

## Do not read

Generated, vendored or data files:

- `src/components/vega-schema.json`, `package-lock.json` and `utk_curio/frontend/urban-workflows/package-lock.json`, `*.js.map`.
- `*.geojson`, `datasets/*/data/`, `models/*/files/`, `vendor/`.
- `utk_curio/backend/tests/test_discovery/fixtures/` (recorded portal responses).
- `docs/examples/dataflows/expected_outputs/` (screenshot baselines).
- `utk_curio/llm-prompts/default_preamble.md`: generated; edit `default_preamble.template.md` or `contracts.py`, then run `scripts/generate_contracts.py`.
- `test_feature_tour_video.py`, `test_stress_tour_video.py`, `test_user_stress_video.py` in `test_frontend/`, unless working on the video tours.
