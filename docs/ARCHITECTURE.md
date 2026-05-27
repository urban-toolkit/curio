# Curio Architecture

This document describes the internal architecture of Curio for contributors who need to understand how the system is structured and how data moves through it. For setup instructions see [USAGE.md](USAGE.md), for contributing guidelines see [CONTRIBUTING.md](CONTRIBUTING.md), for how nodes and packages work — including how to add a new lifecycle hook or icon — see [CATALOG.md](CATALOG.md), and for an end-to-end walkthrough of adding a new node package (manifest + lifecycle hook + optional Flask blueprint + optional dependency extras) see [EXTENDING.md](EXTENDING.md).

## Table of Contents

* [System Overview](#system-overview)
* [Three-Tier Architecture](#three-tier-architecture)
* [Frontend: Workflow Canvas](#frontend-workflow-canvas)
  * [Provider Hierarchy](#provider-hierarchy)
  * [FlowProvider: Central Workflow State](#flowprovider-central-workflow-state)
* [Nodes: Types and Structure](#nodes-types-and-structure)
  * [Node Packages and Manifests](#node-packages-and-manifests)
  * [NodeDescriptor: Static Metadata](#nodedescriptor-static-metadata)
  * [NodeAdapter: Runtime Wiring](#nodeadapter-runtime-wiring)
  * [Lifecycle Hooks](#lifecycle-hooks)
  * [UniversalNode: One Component for All Types](#universalnode-one-component-for-all-types)
* [Data Between Nodes](#data-between-nodes)
  * [Supported Data Types](#supported-data-types)
  * [File-Based Data Transfer](#file-based-data-transfer)
  * [Connection Validation](#connection-validation)
* [Execution Pipeline](#execution-pipeline)
  * [Step-by-Step: Running a Node](#step-by-step-running-a-node)
  * [The Python Wrapper](#the-python-wrapper)
  * [Sandbox Isolation](#sandbox-isolation)
* [Interactions and Propagation](#interactions-and-propagation)
* [Provenance Tracking](#provenance-tracking)
* [Python Dependencies](#python-dependencies)
* [Backend API Reference](#backend-api-reference)
* [Key Files at a Glance](#key-files-at-a-glance)

---

## System Overview

Curio is a browser-based dataflow editor for urban visual analytics. Users build workflows by connecting **nodes** on a canvas: each node holds Python code, a grammar specification, or a GUI widget. When a node is executed, it receives data from its upstream connections, runs its code in an isolated environment, and passes its output downstream.

The system is designed around three principles:

- **Provenance-awareness**: every node execution, connection, and user interaction is recorded so that workflows can be reproduced and audited.
- **Descriptor-driven UI**: node types are declared in a registry; no new React components are required to add a new node.
- **Isolated execution**: user code always runs in a separate sandbox process, never in the main backend.

---

## Three-Tier Architecture

```
┌─────────────────────────────────────────────────────┐
│  Browser (React + TypeScript)                        │
│  Canvas, node editors, visualizations               │
│  Port: 8080                                         │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP (REST)
┌──────────────────────▼──────────────────────────────┐
│  Backend (Flask / Python)                            │
│  Auth, provenance DB, file serving, proxy to sandbox │
│  Port: 5002                                         │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP (REST)
┌──────────────────────▼──────────────────────────────┐
│  Sandbox (Flask / Python)                            │
│  Executes user code in isolation                    │
│  Port: 2000                                         │
└─────────────────────────────────────────────────────┘
```

| Tier | Location | Responsibility |
|---|---|---|
| Frontend | `utk_curio/frontend/urban-workflows/` | Workflow canvas, editors, visualizations, state management |
| Backend | `utk_curio/backend/` | REST API, user auth, provenance database, file storage |
| Sandbox | `utk_curio/sandbox/` | Isolated Python execution, data serialization |

The backend and sandbox both run as Flask servers. The frontend never talks directly to the sandbox, all execution requests are routed through the backend, which then proxies to the sandbox. This keeps the sandbox unexposed to browser clients.

Execution artifacts (DataFrames, scalars, etc.) are stored in a single DuckDB database at `.curio/data/curio_data.duckdb`, shared by both the backend and sandbox. The frontend references artifacts by ID; the backend loads them from DuckDB and serializes them to JSON for the browser.

---

## Frontend: Workflow Canvas

The frontend is a React/TypeScript application built on [React Flow](https://reactflow.dev/). The canvas renders a graph of nodes and edges; each node is an interactive panel that can contain a code editor, a grammar editor, output content, and interactive widgets.

### Provider Hierarchy

State is managed through a nested context-provider tree rather than a global store. From outermost to innermost (as assembled in `src/index.tsx`):

```
ReactFlowProvider
  LLMProvider          — LLM chat
  ProvenanceProvider   — Provenance tracking
  UserProvider         — Auth / user profile
  DialogProvider       — Modal dialogs
  FlowProvider         — Nodes, edges, outputs, interactions  ← primary state
    StarterProvider    — Per-template starter source snippets (formerly TemplateProvider)
```

Each provider exposes its context via a custom hook (e.g., `useFlow()`, `useProvenance()`). Components call these hooks rather than reaching into global variables.

### FlowProvider: Central Workflow State

`src/providers/FlowProvider.tsx` owns the canonical runtime state:

| Field | Type | Purpose |
|---|---|---|
| `nodes` | `Node[]` | All nodes currently on the canvas |
| `edges` | `Edge[]` | All connections between nodes |
| `outputs` | `IOutput[]` | Most recent execution output per node |
| `interactions` | `IInteraction[]` | Active user selections from visualization nodes |
| `dashboardPins` | `string[]` | Node IDs pinned to the dashboard view |

When a node produces output, it calls `outputCallback(nodeId, output)`, which updates `outputs`. React re-renders cause downstream nodes (those connected by an edge from the node that just executed) to detect the new input and request the data from the backend.

---

## Nodes: Types and Structure

### Node Packages and Manifests

Node types are no longer hardcoded into a TypeScript enum. They live in **node packages** under [`packages/<packageId>@<major>/`](../packages/) — each directory ships a `manifest.json` that declares one or more **templates**, the manifest's name for what becomes a `NodeDescriptor` at runtime.

```
packages/
  curio.builtin@1/        # always-on baseline (data, computation, autk, vis, flow nodes)
    manifest.json
    sources/              # per-template Python starter code (data-loading, …)
    integrity.json        # SHA-256 of every file (verified on install)
  curio.streetvision@1/   # optional package, install from /catalog
    manifest.json
    sources/*.tsx         # custom lifecycle hooks (Street View Fetcher, …)
    scripts/lifecycles.js # pre-built bundle that registers those hooks at boot
    integrity.json
```

A manifest's `templates[*]` entry maps cleanly to a `NodeDescriptor`:

```json
{
  "id": "data-loading",
  "category": "data",
  "lifecycle": "code",
  "engine": "python",
  "editor": "code",
  "inputPorts": [],
  "outputPorts": [{ "cardinality": "1", "types": ["DATAFRAME", "GEODATAFRAME", "RASTER"] }]
}
```

[`packagesClient.ts::buildDescriptor`](../utk_curio/frontend/urban-workflows/src/registry/packagesClient.ts) reads each installed manifest and constructs the corresponding `NodeDescriptor` at boot — there is no longer a static enum or a hand-written descriptors file. The frontend `nodeRegistry` is populated entirely from these manifests.

Built-in templates (in `curio.builtin@1/manifest.json`) currently cover:

| Category | Templates |
|---|---|
| Data | `data-loading`, `data-transformation`, `data-summary`, `data-export`, `data-pool`, `autk-db` |
| Computation | `computation-analysis`, `js-computation`, `merge-flow`, `autk-compute`, `spatial-join` |
| Map visualization | `autk-map` |
| Chart/table visualization | `vis-vega`, `vis-simple`, `autk-plot` |

Third-party packages (or first-party optional ones, like `curio.streetvision@1`) install via the **catalog drawer** in the canvas, which copies the package directory into the user's store at `.curio/users/<user>/packages/`.

### NodeDescriptor: Static Metadata

A `NodeDescriptor` (defined in `src/registry/types.ts`) is the static declaration for a node type. It is read once at render time by `UniversalNode` to configure the node's appearance and behavior:

```typescript
interface NodeDescriptor {
  id: NodeType;
  label: string;
  icon: IconDefinition;
  category: 'data' | 'computation' | 'vis_grammar' | 'vis_simple' | 'flow';
  inputPorts: PortDef[];   // what data types this node accepts and how many
  outputPorts: PortDef[];  // what data types this node produces and how many
  adapter: NodeAdapter;
}
```

Port cardinality strings follow a mini-language:
- `'1'` — exactly one connection
- `'n'` — any number of connections
- `'[1,2]'` — between 1 and 2 connections
- `'[1,n]'` — one or more connections

### NodeAdapter: Runtime Wiring

Each `NodeDescriptor` contains an `adapter` that describes how the node behaves at runtime:

```typescript
interface NodeAdapter {
  handles: HandleDef[];           // connection points (in/out ports)
  editor: EditorConfig;           // which editors to show (code, grammar, widgets)
  container: ContainerConfig;     // visual appearance and layout
  useLifecycle: NodeLifecycleHook; // custom hook (see below)
}
```

### Lifecycle Hooks

Every template in a manifest references a **lifecycle key** (the `lifecycle` field — `"code"`, `"vega"`, `"data-pool"`, `"street-view-fetcher"`, …). A lifecycle is a React custom hook that runs inside `UniversalNode` and controls the node's behaviour:

```typescript
type NodeLifecycleHook = (
  data: NodeLifecycleData,
  nodeState: UseNodeStateReturn,
) => LifecycleResult;
```

The hook can return:

| Return field | Purpose |
|---|---|
| `contentComponent` | Custom JSX to render inside the node's body (used when `editor: "none"`) |
| `sendCodeOverride` | Replace the default HTTP execution with custom logic |
| `defaultValueOverride` | Override the initial code shown in the editor |
| `dynamicHandles` / `handlesOverride` | Add or replace connection handles at runtime |

Lifecycles register against a single global registry — [`lifecycleRegistry.ts::registerLifecycle(name, hook)`](../utk_curio/frontend/urban-workflows/src/registry/lifecycleRegistry.ts) — and the manifest's `lifecycle` key looks them up by name. Two distribution channels:

**1. Built-in (ships with Curio's main bundle).** [`builtinLifecycles.ts`](../utk_curio/frontend/urban-workflows/src/registry/builtinLifecycles.ts) calls `registerLifecycle(...)` at import time for the hooks every install needs — `useCodeNodeLifecycle`, `useVegaLifecycle`, the AUTK family, `useDataPoolLifecycle`, `useMergeFlowLifecycle`, `useSpatialJoinLifecycle`, etc. These power `curio.builtin@1`'s templates.

**2. Per-package (dynamic, loaded at boot).** A package whose templates need custom UI can declare `"lifecycleScript": "scripts/lifecycles.js"` in its manifest and ship a pre-built JS bundle alongside the manifest. At boot, [`packagesClient.ts::loadPackageLifecycleScripts`](../utk_curio/frontend/urban-workflows/src/registry/packagesClient.ts) fetches each installed package's bundle with the user's Bearer token and injects the response body as an inline `<script>` *before* descriptors are built. The bundle's top-level side-effect calls `window.curio.registerLifecycle(...)` for each hook it ships.

**Worked example — `curio.streetvision@1`** ships three custom lifecycles:

| Lifecycle key | Hook | Purpose |
|---|---|---|
| `street-view-fetcher` | `useStreetViewFetcherLifecycle` | Place geocoding, bbox preview, Google Street View image batch fetch |
| `hf-cv-inference` | `useHfCvInferenceLifecycle` | HuggingFace model picker + segmentation/detection job polling |
| `cv-gallery` | `useCvGalleryLifecycle` | Per-image gallery + overlay inspection UI |

Each sits in `packages/curio.streetvision@1/sources/*.tsx`, webpack-bundles them into `scripts/lifecycles.js` (UMD + React/ReactFlow externalized to share Curio's instances at runtime), and the manifest's `lifecycle` field maps each template to one. The catalog install copies the package directory; boot loads the bundle; the user gets three custom-rendered nodes without rebuilding Curio. See [EXTENDING.md §4](EXTENDING.md) for the recipe.

### UniversalNode: One Component for All Types

`src/components/UniversalNode.tsx` is the single React component that renders every node type. At mount time it reads the descriptor from the registry and calls the node's lifecycle hook. This means adding a new node type does **not** require a new React component, only a descriptor entry and a lifecycle hook.

Node instance data is stored in the React Flow node's `data` field as `INodeData`:

```typescript
interface INodeData {
  nodeId: string;
  nodeType: string;
  input?: ICodeDataContent;       // reference to upstream output file
  outputCallback?: Function;      // push output to FlowProvider
  interactionsCallback?: Function; // push user interactions upstream
  propagationCallback?: Function;  // receive interactions from upstream
  interactions?: IInteraction[];
  propagation?: any;
}
```

---

## Data Between Nodes

### Supported Data Types

Nodes communicate using one of these typed payloads (defined as `SupportedType` in `src/constants.ts`):

| Type | Python equivalent | Description |
|---|---|---|
| `DATAFRAME` | `pandas.DataFrame` | Tabular data |
| `GEODATAFRAME` | `geopandas.GeoDataFrame` | Tabular data with geometry |
| `VALUE` | `int / float / bool / str` | Scalar value |
| `LIST` | `list` | Array of values |
| `JSON` | `dict` | Key-value object |
| `RASTER` | raster array | Imagery or elevation grids |

### DuckDB-Based Data Transfer

Data is **never** transferred as a JSON body between nodes. Instead, the sandbox writes each output as a row in the shared DuckDB `artifacts` table and returns only a lightweight artifact ID. That ID is what flows through the dataflow graph.

**artifacts table schema:**

```sql
CREATE TABLE artifacts (
    id          VARCHAR PRIMARY KEY,   -- "{timestamp_ms}_{hash}"
    node_id     VARCHAR,               -- node type that produced this artifact
    kind        VARCHAR NOT NULL,      -- see table below
    value_int   BIGINT,                -- used for int / bool
    value_float DOUBLE,                -- used for float
    value_str   VARCHAR,               -- used for str / raster file path
    value_json  JSON,                  -- used for list / dict / outputs (child IDs)
    blob        BLOB                   -- used for dataframe (Parquet) / geodataframe (GeoParquet)
)
```

**`kind` values and their storage columns:**

| kind | Storage | Notes |
|---|---|---|
| `dataframe` | `blob` (Parquet) | Serialized with `pyarrow`; efficient columnar format |
| `geodataframe` | `blob` (GeoParquet) | CRS preserved automatically; `.metadata` stashed in `value_json` |
| `bool` | `value_int` | `1` = True, `0` = False |
| `int` | `value_int` | |
| `float` | `value_float` | |
| `str` | `value_str` | |
| `list` | `value_json` | JSON array of native values |
| `dict` | `value_json` | JSON object of native values |
| `list_of_ids` | `value_json` | JSON array of child artifact IDs (when list contains DataFrames etc.) |
| `dict_of_ids` | `value_json` | JSON object mapping keys to child artifact IDs |
| `outputs` | `value_json` | JSON array of child artifact IDs; used for multi-output nodes |
| `raster` | `value_str` | File path; raster data stays on disk |

**Transfer flow:**

1. Sandbox executes user code and calls `save_to_duckdb(output)`, which inserts a row and returns the artifact ID.
2. The sandbox prints `{ "path": "<artifact_id>", "dataType": "<kind>" }` to stdout.
3. The backend reads stdout and returns `{ path, dataType }` to the frontend.
4. The frontend stores the artifact ID in `FlowProvider.outputs` and passes it as `INodeData.input` to downstream nodes.
5. When a downstream node executes, it sends the artifact ID to the sandbox, which calls `load_from_duckdb(id)` to reconstruct the Python object — no re-serialization of the original data needed.
6. For previewing data in the UI, the frontend fetches via `GET /get-preview?fileName=<artifact_id>`, which loads the artifact and returns only the first 100 rows as JSON.

### Connection Validation

`src/utils/ConnectionValidator.ts` enforces rules when the user draws an edge:

- Source port type must be compatible with target port type.
- Port cardinality is respected (e.g., a `'1'` input port rejects a second incoming edge).
- `MERGE_FLOW` and `FLOW_SWITCH` nodes have special cardinality rules handled by their lifecycle hooks via `dynamicHandles`.

---

## Execution Pipeline

### Step-by-Step: Running a Node

When a user clicks the play button on a node, the following sequence occurs:

```
1. UniversalNode.sendCode()
   Collects: node code, nodeType, upstream artifact ID + kind

2. POST /processPythonCode  (Backend)   [Python nodes]
   POST /processJavaScriptCode (Backend) [JS_COMPUTATION nodes]
   Body: { code, nodeType, input: { filename: <artifact_id>, dataType: <kind> } }

3. Backend proxies to Sandbox
   POST {SANDBOX_HOST}:{SANDBOX_PORT}/exec    [Python nodes]
   POST {SANDBOX_HOST}:{SANDBOX_PORT}/execJs  [JS_COMPUTATION nodes]
   Body: { code, nodeType, file_path: <artifact_id>, dataType: <kind> }

4. Sandbox executes user code
   Python: wraps in python_wrapper.txt, runs via exec() in-process
   JavaScript: spawns a Node.js subprocess, wraps code in async function(arg){…}
   - Both: load_from_duckdb(artifact_id) → reconstructs the Python/JS value
   - Both: save_to_duckdb(output) → inserts artifact row, returns new artifact ID
   Returns: { "path": "<new_artifact_id>", "dataType": "<kind>" }

5. Backend reads sandbox response
   Returns to Frontend: { stdout, stderr, output: { path: <artifact_id>, dataType } }

6. Frontend: outputCallback(nodeId, output)
   - Updates FlowProvider.outputs[] with new artifact ID
   - Downstream nodes' INodeData.input is updated
   - React re-renders downstream nodes

7. ProvenanceProvider.recordExecution()
   POST /nodeExecProv — records timestamps, types, source
```

**JavaScript execution detail:** `JS_COMPUTATION` nodes call `JavaScriptInterpreter.interpretCode()` which posts to `/processJavaScriptCode`. The sandbox's `/execJs` endpoint calls `execute_js_code()`, which writes a temp `.js` file wrapping user code in an async function, spawns `node <file>` as a subprocess, reads the return value from a second temp file, and saves it to DuckDB. No separate Node.js server is needed — the Node subprocess is per-request and fully isolated.

### The Python Wrapper

`utk_curio/sandbox/python_wrapper.txt` is a Python template that wraps every user code execution. It provides a controlled environment:

- Calls `load_from_duckdb(artifact_id)` to reconstruct the upstream Python object directly (DataFrame, GeoDataFrame, scalar, tuple, etc.) from the shared DuckDB database.
- Exposes the reconstructed object as the variable `input` in the user's code scope.
- After user code runs, calls `detect_kind(output)` to determine the output type, then `checkIOType(...)` to validate it against the node's declared output constraints.
- Calls `save_to_duckdb(output)` to persist the result and obtain a new artifact ID.
- Prints a JSON object containing the artifact ID and kind.

Data loading, saving, and type detection logic lives in `utk_curio/sandbox/util/parsers.py` and `utk_curio/sandbox/util/db.py`.

### Sandbox Isolation

The sandbox runs as a completely separate Flask process. It:

- Is not directly reachable from the browser (only the backend calls it).
- Has its own Python environment for package installation (`POST /install`).
- Supports file uploads for initial data ingestion (`POST /upload`).
- Caches repeated executions of identical code + input combinations (`sandbox/app/utils/cache.py`).

---

## Interactions and Propagation

Visualization nodes (`AUTK_MAP`, `AUTK_PLOT`, `VIS_VEGA`, `VIS_SIMPLE`) can emit user interactions (selections, filters, brushes) that flow **upstream** through the dataflow graph, causing upstream nodes to re-execute with the filtered subset.

### IInteraction

```typescript
interface IInteraction {
  nodeId: string;   // which visualization generated the interaction
  details: any;     // selection payload (indices, ranges, coordinates)
  priority: number; // used when multiple interactions compete
}
```

Interactions are stored in `FlowProvider.interactions[]` and passed down to nodes via `INodeData.interactions`.

### Propagation Strategies

When multiple interactions reach the same node, the node resolves them using a strategy:

| Strategy | Semantics |
|---|---|
| `OVERWRITE` | Only the most recent interaction applies |
| `MERGE_AND` | Row must satisfy all active interactions |
| `MERGE_OR` | Row must satisfy at least one active interaction |

The propagation counter (`INodeData.propagation`) is incremented each time an interaction change needs to trigger a re-execution, allowing nodes to detect when they need to re-run without comparing the full interaction payload.

---

## Provenance Tracking

Curio records a per-node execution history (start/end time, source code, input/output types, parent execution) so users can replay a node's evolution from the canvas. Tracking lives entirely in the browser: [`src/providers/ProvenanceProvider.tsx`](../utk_curio/frontend/urban-workflows/src/providers/ProvenanceProvider.tsx) keeps the graph in React state and persists it as part of the saved workflow JSON. Nothing is stored server-side.

---

## Python Dependencies

Curio's Python deps live in two places:

**1. Framework deps** ([`requirements.txt`](../requirements.txt), mirrored in [`pyproject.toml::dependencies`](../pyproject.toml)) — only what the backend + sandbox Flask apps need at module load (Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-Caching, `requests`, `python-dotenv`, the LLM SDKs, `altair`, `tqdm`, `pygments`) plus test/dev tools. No data-ops libraries.

**2. Per-package deps** — every node package declares the libraries its templates need in its manifest's `dependencies.python`:

```json
// packages/curio.builtin@1/manifest.json
"dependencies": {
  "python": {
    "pandas": "==3.0.2", "geopandas": "==1.1.3", "shapely": ">=2.0",
    "numpy": "", "pyarrow": "==24.0.0", "rasterio": "==1.5.0",
    "duckdb": ">=1.5.0", "fiona": "==1.10.1", "pillow": "==12.2.0"
  }
}

// packages/curio.streetvision@1/manifest.json
"dependencies": {
  "python": {
    "torch": ">=2.0", "transformers": ">=4.30",
    "ultralytics": ">=8.0", "huggingface_hub": ">=0.20"
  }
}
```

Spec syntax accepts PEP 440 comparators (`>=2.0`, `~=4.30`, `==1.5.0`), bare versions (`1.2.3` → treated as `==1.2.3`), npm-style carets (`^0.14` → rewritten to `~=0.14`), and empty string for "latest".

### Install paths

- **At `curio start`** — the launcher ([`main.py::install_manifest_dependencies`](../utk_curio/main.py)) walks every installed manifest (`packages/curio.builtin@*` from the catalog source + every user store under `.curio/users/<u>/packages/`), unions their `dependencies.python` via [`resolver.merge_python_deps`](../utk_curio/backend/app/packages/resolver.py) (which surfaces range conflicts as warnings instead of silently last-write-wins), and pip-installs the merged map via [`pip_runner.install_python_deps`](../utk_curio/backend/app/packages/pip_runner.py). Already-satisfied deps are skipped via `importlib.metadata.version` — the steady-state cost is ~1 s with no network.

- **At catalog install time** (`/api/packages/projects/<id>/install`) — when the user installs a package from the drawer, [`services._ensure_user_store_install`](../utk_curio/backend/app/packages/services.py) copies the files, then calls `pip_runner.install_python_deps` on the freshly-installed manifest. The Install button stays busy until pip finishes; heavy installs (`torch`, ~3 GB) can take minutes.

- **At catalog uninstall time** — `prune_unreferenced_packages` walks every other still-installed package's manifest, finds the deps the pruned package declared that no other surviving package still requires, and pip-uninstalls only those (ref-counted shared deps survive).

### Why this split

The framework needs to boot before any manifests can be walked — so `pip install -r requirements.txt` (or `pip install utk-curio`) seeds enough of an env that the launcher can read `manifest.dependencies.python` and continue. Heavy ML/data libraries are intentionally NOT in the framework requirements: a fresh `pip install utk-curio` is small + fast; the multi-GB pulls happen lazily when the user actually installs the matching package (Street Vision pulls `torch` only after they click Install in the catalog).

Standalone libraries the user adds via the [Installed Libraries modal](EXTENDING.md) (canvas → File → Installed libraries) sit in a third bucket — per-user JSON at `.curio/users/<u>/installed-libraries.json` — and pip-install through the same `pip_runner`, with ref-counted uninstall against every installed package's manifest.

---

## Backend API Reference

The backend is a Flask application in `utk_curio/backend/`. All routes are defined in `backend/app/api/routes.py`.

### Core Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/live` | GET | Health check |
| `/processPythonCode` | POST | Execute Python node code (proxies to sandbox `/exec`) |
| `/processJavaScriptCode` | POST | Execute JS node code via Node.js subprocess (proxies to sandbox `/execJs`) |
| `/upload` | POST | Upload a file to `.curio/data/` |
| `/get` | GET | Download a data file by name |
| `/get-preview` | GET | Download first 100 rows of a data file |
| `/toLayers` | POST | Convert GeoJSON to map layers |
| `/installPackages` | POST | Install Python packages in the sandbox (legacy; per-project pip libs) |
| `/node-types` | GET/POST | Get or register node type metadata |

### Package Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/packages` | GET | List the user's installed packages |
| `/api/packages/catalog` | GET | List packages available in the catalog source |
| `/api/packages/projects/<id>` | GET | Read a project's per-project lockfile |
| `/api/packages/projects/<id>/install` | POST | Install a package into a project (copies files, pip-installs `manifest.dependencies.python`) |
| `/api/packages/projects/<id>/<dirName>` | DELETE | Uninstall a package from a project (ref-counted prune + pip uninstall of unique deps) |
| `/api/packages/<dirName>/file/<path>` | GET | Serve a static file from the user's installed copy (lifecycle bundles, icons, …) |
| `/api/packages/defaults` | GET/POST | Per-user "always installed" set (drives the catalog page's Installed badge) |
| `/api/packages/libraries` | GET/POST/DELETE | Per-user "Installed libraries" surface — list / add / remove standalone pip libs alongside manifest-derived ones |

### Template Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/templates` | GET | List available code templates |
| `/addTemplate` | POST | Save a custom template |

### Auth Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/signin` | POST | Google OAuth sign-in |

---

## Key Files at a Glance

### Frontend

| File | Purpose |
|---|---|
| `src/index.tsx` | App entry point and provider nesting order |
| `src/providers/FlowProvider.tsx` | Canonical workflow state (nodes, edges, outputs, interactions) |
| `src/providers/ProvenanceProvider.tsx` | In-memory per-node execution history (saved with the workflow JSON) |
| `src/components/UniversalNode.tsx` | Single React component that renders all node types |
| `src/registry/packagesClient.ts` | Fetch installed manifests → build `NodeDescriptor`s → register against `nodeRegistry` |
| `src/registry/builtinLifecycles.ts` | `registerLifecycle()` calls for the built-in lifecycle hooks |
| `src/registry/lifecycleRegistry.ts` | `lifecycle` key → hook lookup (built-in + package-shipped) |
| `src/registry/nodeRegistry.ts` | Singleton store of all `NodeDescriptor`s; subscribed by the palette + canvas |
| `src/registry/packageRegistryBootstrap.ts` | Boot-time orchestration: load installed packages, inject lifecycle bundles, build descriptors |
| `src/registry/index.ts` | Exposes `window.curio.registerLifecycle` + `window.curio.backendUrl` for package bundles |
| `src/registry/types.ts` | TypeScript interfaces for descriptors, adapters, lifecycle hooks |
| `src/constants.ts` | `SupportedType`, `EdgeType` enums (node types live in manifests now) |
| `src/adapters/node/` | Built-in lifecycle hook implementations (code, vega, autk family, …) |
| `src/utils/ConnectionValidator.ts` | Edge validation logic |
| `src/api/` | API client wrappers (`packagesApi`, `projectsApi`, `authApi`) |
| `src/components/packages/publishing/NodeCatalogDrawer.tsx` | The canvas drawer that installs node packages from the catalog |
| `src/components/menus/packages/PackageManagerWindow.tsx` | "Installed Libraries" modal (per-user pip libs, manifest-derived libs) |

### Backend

| File | Purpose |
|---|---|
| `backend/server.py` | Flask app factory; Werkzeug reloader exclude patterns |
| `backend/app/api/routes.py` | Legacy REST endpoints (sandbox proxies, node-types) |
| `backend/app/packages/manifest.py` | Parse `manifest.json` into typed `PackageManifest` dataclass |
| `backend/app/packages/installer.py` | Catalog-source-dir → archive → user-store copy + integrity hashing |
| `backend/app/packages/pip_runner.py` | `install_python_deps` / `uninstall_python_deps`; PEP 440 + caret support, idempotent skip |
| `backend/app/packages/resolver.py` | `merge_python_deps` (conflict-aware union across packages) |
| `backend/app/packages/services.py` | Catalog install/uninstall orchestration; calls `pip_runner` on file-copy + prune |
| `backend/app/packages/routes.py` | `/api/packages/*` endpoints (list, catalog, install, libraries, defaults) |
| `backend/app/packages/libraries.py` | Per-user `.curio/users/<u>/installed-libraries.json` storage + aggregator |
| `backend/app/users/models.py` | `User` and `UserSession` SQLAlchemy models |
| `backend/extensions.py` | SQLAlchemy and Flask-Migrate initialization |

### Sandbox

| File | Purpose |
|---|---|
| `sandbox/app/api.py` | Sandbox REST endpoints (`/exec`, `/execJs`, `/install`, `/upload`) |
| `sandbox/python_wrapper.txt` | Execution wrapper template for user code |
| `sandbox/util/db.py` | DuckDB connection, path resolution, and `artifacts` table initialization |
| `sandbox/util/parsers.py` | `save_to_duckdb`, `load_from_duckdb`, `detect_kind`, and type validation |
| `sandbox/app/utils/cache.py` | Execution result caching |
