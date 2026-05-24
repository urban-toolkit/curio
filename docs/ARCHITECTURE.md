# Curio Architecture

This document describes the internal architecture of Curio for contributors who need to understand how the system is structured and how data moves through it. For setup instructions see [USAGE.md](USAGE.md), for contributing guidelines see [CONTRIBUTING.md](CONTRIBUTING.md), and for how nodes and packs work — including how to add a new lifecycle hook or icon — see [WAREHOUSE.md](WAREHOUSE.md).

## Table of Contents

* [System Overview](#system-overview)
* [Three-Tier Architecture](#three-tier-architecture)
* [Frontend: Workflow Canvas](#frontend-workflow-canvas)
  * [Provider Hierarchy](#provider-hierarchy)
  * [FlowProvider: Central Workflow State](#flowprovider-central-workflow-state)
* [Nodes: Types and Structure](#nodes-types-and-structure)
  * [Node Type Registry](#node-type-registry)
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
    TemplateProvider   — Node code templates
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

### Node Type Registry

All node types are enumerated in `src/constants.ts` as the `NodeType` enum. There are currently these types across five categories:

| Category | Node Types |
|---|---|
| Data | `DATA_LOADING`, `DATA_TRANSFORMATION`, `DATA_SUMMARY`, `DATA_EXPORT`, `DATA_POOL`, `AUTK_DB` |
| Computation | `COMPUTATION_ANALYSIS`, `JS_COMPUTATION`, `MERGE_FLOW`, `FLOW_SWITCH`, `CONSTANTS`, `AUTK_COMPUTE` |
| Map visualization | `AUTK_MAP` |
| Chart/table visualization | `VIS_VEGA`, `VIS_SIMPLE`, `AUTK_PLOT` |
| Annotation | `COMMENTS` |

Each type is registered in `src/registry/descriptors.ts` with a `NodeDescriptor` and in the backend route file with its allowed input/output data types.

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

The `useLifecycle` field is a React custom hook with this signature:

```typescript
type NodeLifecycleHook = (
  data: NodeLifecycleData,
  nodeState: UseNodeStateReturn,
) => LifecycleResult;
```

The hook runs inside `UniversalNode` and can return:

| Return field | Purpose |
|---|---|
| `contentComponent` | Custom JSX to render inside the node's output area |
| `sendCodeOverride` | Replace the default HTTP execution with custom logic |
| `defaultValueOverride` | Override the initial code shown in the editor |
| `dynamicHandles` | Generate connection handles at runtime (used by `MERGE_FLOW`) |

Lifecycle hooks live in `src/adapters/node/`. Current implementations:

| Hook | Used by |
|---|---|
| `useCodeNodeLifecycle` | Most data and computation nodes |
| `useVegaLifecycle` | `VIS_VEGA` |
| `useAutkMapLifecycle` | `AUTK_MAP` (built via `createAutkLifecycle`) |
| `useAutkPlotLifecycle` | `AUTK_PLOT` (built via `createAutkLifecycle`) |
| `useAutkComputeLifecycle` | `AUTK_COMPUTE` (built via `createAutkLifecycle`) |
| `useAutkDbLifecycle` | `AUTK_DB` (server-side, default code template) |
| `useDataPoolLifecycle` | `DATA_POOL` |
| `useMergeFlowLifecycle` | `MERGE_FLOW` |
| `useFlowSwitchLifecycle` | `FLOW_SWITCH` |

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
| `/installPackages` | POST | Install Python packages in sandbox |
| `/node-types` | GET/POST | Get or register node type metadata |

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
| `src/registry/descriptors.ts` | Node descriptor registrations for all 17 types |
| `src/registry/types.ts` | TypeScript interfaces for descriptors and adapters |
| `src/constants.ts` | `NodeType`, `SupportedType`, `EdgeType` enums |
| `src/adapters/node/` | Lifecycle hook implementations per node type |
| `src/utils/ConnectionValidator.ts` | Edge validation logic |
| `src/services/` | API call wrappers for frontend → backend communication |

### Backend

| File | Purpose |
|---|---|
| `backend/server.py` | Flask app factory |
| `backend/app/api/routes.py` | All REST endpoints |
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
