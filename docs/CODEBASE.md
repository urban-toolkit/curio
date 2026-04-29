# Curio Codebase Documentation

This document explains how Curio is structured and how its core parts work together at runtime.

## 1) What Curio Is

Curio is a workflow-based urban visual analytics system with three runtime services:

- `backend` (Flask): API gateway, provenance, auth, templates, LLM routes.
- `sandbox` (Flask): executes user Python code and converts geospatial data to UTK layers.
- `frontend` (React + ReactFlow): node-based workflow editor and visualization surface.

At launch, these are orchestrated by the CLI in `utk_curio/main.py`.

## 2) Repository Map

Top-level directories and their purpose:

- `utk_curio/main.py`: multi-process launcher (`backend`, `sandbox`, `frontend`).
- `utk_curio/backend/`: Flask backend, provenance DB logic, auth, API routes, migrations.
- `utk_curio/sandbox/`: isolated Python execution service and parser/serialization utilities.
- `utk_curio/frontend/urban-workflows/`: main React app for authoring and running workflows.
- `utk_curio/frontend/utk-workflow/`: embedded UTK codebase and TypeScript bundle source.
- `utk_curio/llm-prompts/`: prompt templates consumed by backend `/openAI`.
- `templates/`: default code templates grouped by box family.
- `tests/`: workflow JSON fixtures and expected artifacts for E2E/frontend scenarios.
- `docs/`: usage guides and examples.

## 3) Runtime Architecture

### 3.1 Launcher and Process Model

Entrypoints:

- `curio.py` (repo mode): sets `CURIO_DEV=1` and delegates to `utk_curio.main:main`.
- `curio` (pip mode): installed console script mapping to `utk_curio.main:main`.

`utk_curio/main.py` does:

- sets shared env vars:
  - `FLASK_BACKEND_HOST`, `FLASK_BACKEND_PORT`
  - `FLASK_SANDBOX_HOST`, `FLASK_SANDBOX_PORT`
  - `CURIO_LAUNCH_CWD` (where command was run)
  - `CURIO_SHARED_DATA` (`<launch_dir>/.curio/data`)
- optionally builds frontend assets in dev mode (`CURIO_DEV=1`).
- initializes provenance DB if needed (`.curio/provenance.db`).
- starts subprocesses:
  - `python -m backend.server`
  - `python -m sandbox.server`
  - frontend:
    - dev: `npm run start` in `urban-workflows`
    - prod/pip/docker: `python -m http.server 8080 --directory dist`

### 3.2 Two Database Paths

Curio uses two distinct persistence tracks:

- Provenance DB (custom SQLite): `.curio/provenance.db`
  - created by `utk_curio/backend/create_provenance_db.py`
  - accessed directly with `sqlite3` in API routes.
- User/Auth DB (Flask-SQLAlchemy): default `sqlite:///urban_workflow.db`
  - models in `utk_curio/backend/app/users/models.py`
  - migrations in `utk_curio/backend/migrations/`.

## 4) Backend Design (`utk_curio/backend`)

### 4.1 App Initialization

- `server.py` creates app via `create_app()` and exposes `/health`.
- `app/__init__.py` registers:
  - API blueprint (`app/api/routes.py`)
  - users blueprint (`app/users`).
- `config.py` loads `.env` and `.flaskenv`.

### 4.2 API Surface by Domain

Core utility routes:

- `GET /live`: backend liveness.
- `GET /cwd`, `GET /launchCwd`, `GET /sharedDataPath`.

File and data access:

- `POST /upload`: forwards multipart upload to sandbox `/upload`.
- `GET /get?fileName=...`: loads compressed `.data` file and returns JSON.
- `GET /get-preview?fileName=...`: returns first rows/features for faster DataPool rendering.
- `GET /datasets`: proxies sandbox dataset listing.

Execution bridge:

- `POST /processPythonCode`: sends user code + input descriptor to sandbox `/exec`.
- `POST /toLayers`: validates GeoJSONs and proxies to sandbox `/toLayers`.

Authentication and users:

- `POST /signin`: Google OAuth code exchange and user/session creation.
- `GET /getUser`: authenticated user info (`Authorization` token header).
- `POST /saveUserType`: updates user role.

Templates:

- `GET /templates`: scans `templates/*/*.py` and returns template objects.
- `POST /addTemplate`: writes/overwrites template code to disk.

Provenance lifecycle:

- `POST /saveUserProv`
- `POST /saveWorkflowProv`
- `POST /newBoxProv`
- `POST /deleteBoxProv`
- `POST /newConnectionProv`
- `POST /deleteConnectionProv`
- `GET /checkDB`
- `POST /boxExecProv`
- `POST /getBoxGraph`
- `GET /truncateDBProv`
- `POST /insert_attribute_value_change`
- `POST /insert_visualization`
- `POST /insert_interaction`

LLM routes:

- `POST /openAI`: loads prompt files and sends chat request via OpenAI SDK.
- `POST /checkUsageOpenAI`: local token-budget estimate/throttle gate.
- `GET /cleanOpenAIChat?chatId=...`: clears in-memory conversation for a chat key.

### 4.3 Backend Data Contracts

Node execution output from sandbox is normalized as:

- `{ "path": "<relative .data file>", "dataType": "<type>" }`

Supported semantic types used across backend/frontend:

- `DATAFRAME`, `GEODATAFRAME`, `VALUE`, `LIST`, `JSON`, `RASTER`.

## 5) Sandbox Design (`utk_curio/sandbox`)

### 5.1 Responsibilities

- execute Python snippets from workflow nodes (`/exec`).
- serialize/deserialize node inputs/outputs.
- convert GeoJSON into UTK render layers (`/toLayers`).
- list available datasets from package and launch directory (`/datasets`).

### 5.2 Execution Path (`/exec`)

Flow:

- backend sends code, `boxType`, `file_path`, `dataType`.
- sandbox loads `sandbox/python_wrapper.txt`.
- wrapper injects user code inside `def userCode(arg): ...`.
- wrapper loads input from `.data` memory-mapped compressed file(s).
- wrapper validates IO type for the box.
- wrapper calls user function, parses output to transport JSON, saves output to new `.data`.
- wrapper prints final JSON metadata to stdout (last line), which sandbox returns.

### 5.3 Parser and Serialization Layer

`sandbox/util/parsers.py` provides:

- IO validation by box family (`checkIOType`).
- input parsing from transport JSON into Python objects:
  - primitives, list, `pandas.DataFrame`, `geopandas.GeoDataFrame`, raster.
- output parsing from Python objects into transport JSON.
- secure memory-mapped file load/save with path traversal protection.
- compressed storage format: zlib-compressed JSON bytes.

## 6) Frontend Design (`urban-workflows`)

### 6.1 App Composition

App root in `src/index.tsx` composes providers in this order:

- `BackendHealthBanner`
- `ReactFlowProvider`
- `LLMProvider`
- `ProvenanceProvider`
- `UserProvider`
- `DialogProvider`
- `FlowProvider`
- `TemplateProvider`
- `MainCanvas`

### 6.2 Node Registry and Adapter Model

Curio uses a descriptor-based node registry:

- node descriptors: `src/registry/descriptors.ts`
- registry API: `src/registry/nodeRegistry.ts`
- types/contracts: `src/registry/types.ts`
- grammar adapter registry: `src/registry/grammarAdapter.ts`

Each box type defines:

- visual metadata (label/icon/category).
- typed input/output ports.
- editor capabilities (code/grammar/widgets).
- rendering/execution lifecycle hook (`adapter.useLifecycle`).

`UniversalBox` (`src/components/UniversalBox.tsx`) is the runtime shell for every node:

- resolves descriptor by `nodeType`.
- runs `useBoxState`.
- runs lifecycle hook.
- renders handles, editor panes, custom output content, template/description modals.

### 6.3 Workflow State and Dataflow

`FlowProvider` manages:

- ReactFlow nodes/edges.
- output propagation across edges.
- interaction propagation across bidirectional `in/out` edges.
- merge-flow slot assignment for `MERGE_FLOW` handles (`in_0..in_4`).
- provenance callbacks on node/edge create/delete.

`useWorkflowOperations` adds:

- loading/saving parsed Trill specs.
- canvas reset and suggestion acceptance logic.
- keyword/goal/warning overlays from LLM-generated Trill metadata.

### 6.4 Execution in the Frontend

Code boxes use `PythonInterpreter` (`src/PythonInterpreter.ts`):

- sends code to backend `/processPythonCode`.
- tracks execution provenance through `boxExecProv`.

Visualization boxes:

- Vega (`useVega`):
  - compiles Vega-Lite specs.
  - parses dataframe/gdf input.
  - binds selection signals into interaction payloads.
- UTK (`useUTK`):
  - requires geodataframe input (or outputs of geodataframes).
  - calls backend `/toLayers`.
  - auto-builds UTK grammar scaffolding and initializes UTK `GrammarInterpreter`.
  - supports interaction resolution widget (`NONE`, `PICKING`, `BRUSHING`).

### 6.5 Trill Specification

`TrillGenerator` serializes the workflow graph into a JSON spec:

- `dataflow.name`, `task`, `timestamp`, `provenance_id`
- `dataflow.nodes[]`: id, type, position, content, in/out, goal, metadata.keywords
- `dataflow.edges[]`: id, source, target, optional `type: "Interaction"`, metadata.keywords

This is used for:

- workflow import/export (`UpMenu`).
- local provenance timeline in frontend memory.
- LLM prompt context and suggestion workflows.

## 7) Data and Template Files

### 7.1 Shared Runtime Data

- uploaded and intermediate node outputs live in `.curio/data/*.data`.
- files are compressed JSON payloads referenced by relative path.

### 7.2 Built-in Templates

Default templates are physical `.py` files under:

- `templates/data_loading`
- `templates/data_cleaning`
- `templates/data_transformation`
- `templates/computation_analysis`
- `templates/data_export`
- `templates/vega_lite`

Backend `/templates` reads these dynamically on each request.

## 8) LLM Integration

Prompt files are in `utk_curio/llm-prompts/`.

Backend `/openAI`:

- reads `preamble` and `prompt` text files.
- appends a simple metadata summary of local CSV/JSON/GeoJSON files.
- maintains in-memory conversation history keyed by `chatId`.
- reads API key from `api.env`.

Frontend calls this via `LLMProvider.openAIRequest(...)`.

## 9) Build, Packaging, and Deployment

### 9.1 Docker

- multi-stage Dockerfile:
  - Python runtime base.
  - Node build stage for `utk-ts` and `urban-workflows`.
  - final runtime image serves built frontend statically and runs all services.
- exposed ports:
  - `2000` sandbox
  - `5002` backend
  - `8080` frontend

### 9.2 PyPI Packaging

- package name: `utk-curio`.
- script: `curio`.
- release workflow writes version into `utk_curio/__init__.py` from tag.
- includes frontend/backend/sandbox assets in wheel/sdist via `MANIFEST.in`.

## 10) Testing Strategy

### 10.1 Backend and Sandbox

- unittest-based tests under:
  - `utk_curio/backend/tests`
  - `utk_curio/sandbox/tests`

### 10.2 Frontend Unit Tests

- Jest tests under `urban-workflows/src/tests`.

### 10.3 End-to-End Frontend Tests

- Playwright + pytest under `utk_curio/backend/tests/test_frontend`.
- validates:
  - service health (`/live`).
  - workflow file loading.
  - node/edge counts.
  - node execution outcomes.
- can target existing running stack with `CURIO_E2E_USE_EXISTING=1`.

## 11) Extension Guide (Developer Checklist)

To add a new box type end-to-end:

- add enum in `src/constants.ts` if needed.
- register descriptor in `src/registry/descriptors.ts`.
- implement lifecycle in `src/adapters/box/*Lifecycle*`.
- if code execution semantics change, update sandbox parser/validation.
- if provenance type mapping changes, update backend type maps in `routes.py`.
- add templates if needed under `templates/`.
- add tests:
  - frontend registry/lifecycle tests
  - workflow fixture for E2E
  - backend route tests if new endpoints are added.

## 12) Notable Operational Notes

- Curio resolves file paths relative to where Curio is launched (`CURIO_LAUNCH_CWD`).
- Backend and sandbox CORS are permissive (`*`) for local tool interoperability.
- Some provenance/auth flows intentionally trade strictness for UX in local/research settings.

