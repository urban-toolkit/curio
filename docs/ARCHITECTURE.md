# Curio Architecture

This document describes the internal architecture of Curio for contributors who need to understand how the system is structured and how data moves through it. For setup instructions see [USAGE.md](USAGE.md), for contributing guidelines see [CONTRIBUTING.md](CONTRIBUTING.md), for how node packages are installed and shared see [NODE-CATALOG.md](NODE-CATALOG.md) (to add a built-in behavior hook, icon or grammar adapter, see [Behavior Hooks](#behavior-hooks)), and for an end-to-end walkthrough of adding a new node package (manifest + behavior hook + optional Flask blueprint + optional dependency extras) see [EXTENDING.md](EXTENDING.md).

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
  * [Behavior Hooks](#behavior-hooks)
  * [UniversalNode: One Component for All Types](#universalnode-one-component-for-all-types)
* [Data Between Nodes](#data-between-nodes)
  * [Supported Data Types](#supported-data-types)
  * [DuckDB-Based Data Transfer](#duckdb-based-data-transfer)
  * [Resolving Geometry in Vega-Lite Nodes](#resolving-geometry-in-vega-lite-nodes)
  * [Referencing Upstream Data in Autark Nodes](#referencing-upstream-data-in-autark-nodes)
  * [Connection Validation](#connection-validation)
* [Execution Pipeline](#execution-pipeline)
  * [Step-by-Step: Running a Node](#step-by-step-running-a-node)
  * [Render Outcomes](#render-outcomes)
  * [Running Python Code](#running-python-code)
  * [Sandbox Isolation](#sandbox-isolation)
* [Interactions and Propagation](#interactions-and-propagation)
* [Provenance Tracking](#provenance-tracking)
* [The Trill Dataflow Format](#the-trill-dataflow-format)
* [Generated Contracts](#generated-contracts)
  * [The Autark Schema](#the-autark-schema)
* [Agent Prompt Composition](#agent-prompt-composition)
* [LLM Configurations and Resolution](#llm-configurations-and-resolution)
* [Agent Runtime](#agent-runtime)
* [Python Dependencies](#python-dependencies)
* [Discovery Catalog](#discovery-catalog)
* [Model Catalog](#model-catalog)
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
│  Executes user code in a separate process           │
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

State is managed through a nested context-provider tree rather than a global
store. Every provider wraps exactly one child, so the tree is really a single
chain: the lists below run from outermost to innermost, each entry containing
the one after it.

The chain comes in two parts, and the split matters. Only the first is app-wide;
the rest exists on the dataflow route alone, which is why a component rendered
on `/projects` or `/catalog/*` can call `useUserContext` but not
`useFlowContext`.

App-wide, in `src/index.tsx`:

1. `BrowserRouter`
2. `BackendHealthBanner`: offline / unreachable-backend notice
3. `ToastProvider`: app-wide toasts
4. `ReactFlowProvider`
5. `ProvenanceProvider`: provenance tracking
6. `UserProvider`: auth / user profile
7. `Routes`: every route lives below this point

Per dataflow route, inside `MainCanvasRoute` in the same file:

1. `DialogProvider`: modal dialogs
2. `CollaborationProvider`: presence, locks, proposals
3. `FlowProvider`: nodes, edges, outputs, interactions. The primary state
4. `NodeCatalogDrawerProvider`
5. `DatasetCatalogDrawerProvider`
6. `AgentCatalogDrawerProvider`
7. `StarterProvider`: per-template starter source snippets
8. `ProjectLoader`
9. `PackagePaletteProvider`
10. `DatasetPaletteProvider`
11. `MainCanvas`
12. `AgentAttachmentsProvider` (`src/providers/agents/`): the attached agents, mounted in `MainCanvas.tsx`
    rather than `index.tsx` because it needs React Flow's instance and only
    applies where there is a dataflow to attach agents to

Two of these orderings are load-bearing rather than incidental:

- `CollaborationProvider` must wrap `FlowProvider`. Outside it, FlowProvider's
  mutation paths get the no-op default context and silently drop every peer
  edit.
- The three catalog drawer providers must sit inside `FlowProvider`, because a
  drawer's Install writes to the open dataflow. Outside it, `useFlowContext`
  returns no-op defaults and Install appears to succeed while doing nothing.

Each provider exposes its context via a custom hook (e.g., `useFlow()`, `useProvenance()`). Components call these hooks rather than reaching into global variables.

### FlowProvider: Central Workflow State

`src/providers/FlowProvider.tsx` owns the canonical runtime state:

| Field | Type | Purpose |
|---|---|---|
| `nodes` | `Node[]` | All nodes currently on the canvas |
| `edges` | `Edge[]` | All connections between nodes |
| `outputs` | `IOutput[]` | Most recent execution output per node |
| `interactions` | `IInteraction[]` | Active user selections from visualization nodes |
| `dashboardPins` | `{[nodeId]: boolean}` | Which nodes are pinned to the dataflow's dashboard page |
| `dashboardOn` | `boolean` | A PROP, not state: true when this tree is the dashboard page rather than the canvas |

When a node produces output, it calls `outputCallback(nodeId, output)`, which updates `outputs`. React re-renders cause downstream nodes (those connected by an edge from the node that just executed) to detect the new input and request the data from the backend.

---

## Nodes: Types and Structure

### Node Packages and Manifests

Node types live in **node packages** under [`packages/<packageId>@<major>/`](../packages/). Each directory ships a `manifest.json` that declares one or more **templates**, the manifest's name for what becomes a `NodeDescriptor` at runtime.

```
packages/
  curio.builtin@1/        # always-on baseline (data, computation, autk, vis, flow nodes)
    manifest.json
    integrity.json        # SHA-256 of every file (written on install, not verified)
  curio.example-ui@1/     # optional package, install from /catalog
    manifest.json
    sources/*.tsx         # custom behavior hook (Column Filter) and its bundle entry
    scripts/behaviors.js  # pre-built bundle that registers that hook at boot
    integrity.json
  curio.streetvision@1/   # optional package: one Python code template, no bundle
    manifest.json
    sources/image-segmentation.py
    integrity.json
```

A manifest's `templates[*]` entry maps cleanly to a `NodeDescriptor`:

```json
{
  "id": "data-loading",
  "category": "data",
  "behavior": "code",
  "engine": "python",
  "editor": "code",
  "inputPorts": [],
  "outputPorts": [{ "cardinality": "1", "types": ["DATAFRAME", "GEODATAFRAME", "RASTER"] }]
}
```

[`packagesClient.ts::buildDescriptor`](../utk_curio/frontend/urban-workflows/src/registry/packagesClient.ts) reads each installed manifest and constructs the corresponding `NodeDescriptor` at boot. The frontend `nodeRegistry` is populated entirely from these manifests.

Built-in templates (in `curio.builtin@1/manifest.json`) currently cover:

| Category | Templates |
|---|---|
| Data | `data-loading`, `data-transformation`, `data-export`, `data-pool`, `spatial-join` |
| Computation | `computation-analysis`, `data-summary`, `js-computation` |
| Flow | `merge-flow` |
| Grammar (Autark) | `autk-grammar`, one node whose UrbanSpec unifies OSM/PBF loading, GPU `compute`, and `map` + `plot` rendering |
| Chart/table visualization | `vis-vega`, `vis-simple` (a table, or a card per row when the frame carries images) |

Third-party packages (or first-party optional ones, like `curio.example-ui@1`) install via the **catalog drawer** in the canvas, which copies the package directory into the user's store at `.curio/users/<user>/packages/`.

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
- `'1'`: exactly one connection
- `'n'`: any number of connections
- `'[1,2]'`: between 1 and 2 connections
- `'[1,n]'`: one or more connections

### NodeAdapter: Runtime Wiring

Each `NodeDescriptor` contains an `adapter` that describes how the node behaves at runtime:

```typescript
interface NodeAdapter {
  handles: HandleDef[];           // connection points (in/out ports)
  editor: EditorConfig;           // which editors to show (code, grammar, widgets)
  container: ContainerConfig;     // visual appearance and layout
  useBehavior: NodeBehaviorHook; // custom hook (see below)
}
```

### Behavior Hooks

Every template in a manifest references a **behavior key** (the `behavior` field, holding values such as `"code"`, `"vega"`, `"data-pool"`, or `"column-filter"`). A behavior is a React custom hook that runs inside `UniversalNode` and controls the node's behaviour:

```typescript
type NodeBehaviorHook = (
  data: NodeBehaviorData,
  nodeState: UseNodeStateReturn,
) => NodeBehaviorResult;
```

The hook can return:

| Return field | Purpose |
|---|---|
| `contentComponent` | Custom JSX to render inside the node's body (used when `editor: "none"`) |
| `sendCodeOverride` | Replace the default HTTP execution with custom logic |
| `defaultValueOverride` | Override the initial code shown in the editor |
| `dynamicHandles` / `handlesOverride` | Add or replace connection handles at runtime |

Behaviors register against a single global registry, [`behaviorRegistry.ts::registerBehavior(name, hook)`](../utk_curio/frontend/urban-workflows/src/registry/behaviorRegistry.ts), and the manifest's `behavior` key looks them up by name. Two distribution channels:

**1. Built-in (ships with Curio's main bundle).** [`builtinBehaviors.ts`](../utk_curio/frontend/urban-workflows/src/registry/builtinBehaviors.ts) calls `registerBehavior(...)` at import time for the hooks every install needs: `useCodeNodeBehavior`, `useVegaBehavior`, `useAutkGrammarBehavior`, `useDataPoolBehavior`, `useMergeFlowBehavior`, `useSpatialJoinBehavior`, and so on. These power `curio.builtin@1`'s templates.

**2. Per-package (dynamic, loaded at boot).** A package whose templates need custom UI can declare `"behaviorScript": "scripts/behaviors.js"` in its manifest and ship a pre-built JS bundle alongside the manifest. At boot, [`packagesClient.ts::loadPackageBehaviorScripts`](../utk_curio/frontend/urban-workflows/src/registry/packagesClient.ts) fetches each installed package's bundle with the user's Bearer token and injects the response body as an inline `<script>` *before* descriptors are built. The bundle's top-level side-effect calls `window.curio.registerBehavior(...)` for each hook it ships.

**Worked example: `curio.example-ui@1`** ships one custom behavior:

| Behavior key | Hook | Purpose |
|---|---|---|
| `column-filter` | `useColumnFilterBehavior` | Column, comparison and threshold controls in the node body; sends the matching rows downstream as a DATAFRAME |

The hook sits in `packages/curio.example-ui@1/sources/columnFilterBehavior.tsx` and `sources/index.tsx` registers it; webpack bundles them into `scripts/behaviors.js` (UMD + React/ReactFlow externalized to share Curio's instances at runtime), and the manifest's `behavior` field maps the template to it. The catalog install copies the package directory; boot loads the bundle; the user gets a custom-rendered node without rebuilding Curio. See [EXTENDING.md §4](EXTENDING.md) for the recipe.

#### Adding a built-in behavior, icon, or grammar adapter

A package ships its own behavior as a `behaviorScript` bundle (see [Authoring nodes](AUTHORING-NODES.md), Tier 2). The recipes below are for the other case: changing Curio itself, so every install has the behavior, icon, or adapter before any package loads.

**A behavior hook.** The built-ins are registered in [`src/registry/builtinBehaviors.ts`](../utk_curio/frontend/urban-workflows/src/registry/builtinBehaviors.ts).

1. Implement the hook under [`src/adapters/node/`](../utk_curio/frontend/urban-workflows/src/adapters/node/), conforming to `NodeBehaviorHook` in [`src/registry/types.ts`](../utk_curio/frontend/urban-workflows/src/registry/types.ts). `useCodeNodeBehavior` and `useVegaBehavior` are the references.
2. Register it in `builtinBehaviors.ts`: `registerBehavior("my-key", useMyHook);`
3. Reference it from a manifest: `"behavior": "my-key"` on each kind that wants it.

**An icon.** [`src/registry/iconRegistry.ts`](../utk_curio/frontend/urban-workflows/src/registry/iconRegistry.ts) maps `iconRef` strings (e.g. `"fa-solid:upload"`) to FontAwesome `IconDefinition` constants.

1. Import the icon constant at the top of `iconRegistry.ts`.
2. Add `registerIcon("fa-solid:my-icon", faMyIcon);`
3. Reference it in a manifest: `"iconRef": "fa-solid:my-icon"`.

An unknown ref falls back to `faCube`, so a missing icon is visible but not fatal.

**A grammar adapter.** Same pattern, in [`src/registry/grammarAdapter.ts`](../utk_curio/frontend/urban-workflows/src/registry/grammarAdapter.ts). The Vega-Lite adapter, [`src/adapters/vegaLiteAdapter.ts`](../utk_curio/frontend/urban-workflows/src/adapters/vegaLiteAdapter.ts), is the canonical example.

### UniversalNode: One Component for All Types

`src/components/UniversalNode.tsx` is the single React component that renders every node type. At mount time it reads the descriptor from the registry and calls the node's behavior hook. This means adding a new node type does **not** require a new React component, only a descriptor entry and a behavior hook.

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
| `GEODATAFRAME` | `geopandas.GeoDataFrame` | Tabular data with geometry, in one or more geometry columns |
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
| `geodataframe` | `blob` (GeoParquet) | CRS and *every* geometry column preserved, not only the active one; `.metadata` stashed in `value_json`. A GeoDataFrame with no active geometry column is stored as `dataframe`; GeoParquet cannot represent one |
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
5. When a downstream node executes, it sends the artifact ID to the sandbox, which calls `load_from_duckdb(id)` to reconstruct the Python object, with no re-serialization of the original data needed.
6. For previewing data in the UI, the frontend fetches via `GET /get-preview?fileName=<artifact_id>`, which loads the artifact and returns only the first 100 rows as JSON.

### Reading a Grammar Node's Input

The `vis-vega` and `autk-grammar` nodes read their input through one path,
[`grammarInput.ts`](../utk_curio/frontend/urban-workflows/src/utils/grammarInput.ts):
the same gate on the input's type and the same refusal sentence, the same fetch
(Arrow first, JSON as the fallback), and frames that carry the payload, its
`schema` and its declared geometry column. [`vegaInput.ts`](../utk_curio/frontend/urban-workflows/src/utils/vegaInput.ts)
turns the one frame a Vega-Lite spec draws into rows;
[`autkInput.ts`](../utk_curio/frontend/urban-workflows/src/utils/autkInput.ts)
turns a frame or a bundle of named layers into the tables an Autark document
names. A `DataFrame`'s geometry column is found by value in both, through
[`geometryField.ts`](../utk_curio/frontend/urban-workflows/src/utils/geometryField.ts).

The rest is shared too. Both nodes resolve their pre-run state with
`resolveGrammarEmptyReason` in
[`nodeEmptyState.ts`](../utk_curio/frontend/urban-workflows/src/utils/nodeEmptyState.ts),
from the edge state
[`useGrammarInputState.ts`](../utk_curio/frontend/urban-workflows/src/hook/useGrammarInputState.ts)
reads, and write it into the element they draw into with
[`writeEmptyState.ts`](../utk_curio/frontend/urban-workflows/src/utils/writeEmptyState.ts);
an Autark document that loads everything it draws passes `needsInput: false`.
Both fill an empty editor through
[`useStarterSpec.ts`](../utk_curio/frontend/urban-workflows/src/hook/useStarterSpec.ts),
each with its own ladder (`vegaDefaultSpec.ts`, `autkDefaultSpec.ts`) over the
column roles in `starterSpec.ts`. Both mark themselves errored on a failed run,
so a node they feed shows `upstream-errored`.

### Resolving Geometry in Vega-Lite Nodes

The `vis-vega` node also resolves upstream data in its own way, for a narrower
reason: Vega-Lite needs to be told *which column holds the geometry*, and a
`GeoDataFrame` can have several.

The payload carries `geometry_name` (see **Supported Data Types** above), so the
node does not guess. [`vegaGeoSpec.ts`](../utk_curio/frontend/urban-workflows/src/utils/vegaGeoSpec.ts)
applies one rule with three outcomes: use the declared active column; or, when
none is declared, the single column whose values are geometry; or, when there
are none or several, inject nothing and show the user which columns it found.
Each geometry column keeps its own pandas name in the row, so `"field": "geom"`
addresses it exactly as an attribute column would.

Two things are then filled in that Vega-Lite would otherwise get wrong:
`encoding.shape` on a `geoshape` mark, and an explicit `projection`:
`identity`+`reflectY` for projected coordinates, `mercator` for lon/lat. Both
are skipped whenever the author has written their own.

This is gated on **the spec**, not the payload: a bar chart over a GeoDataFrame
never has geometry attached, so it carries exactly the columns it always did.
That matters because shipped dataflows chart multi-megabyte GeoJSON as bar
charts, and the rows are re-shipped through `changeset()` on every brush.

### Referencing Upstream Data in Autark Nodes

The `autk-grammar` node consumes upstream data differently from Python nodes: its UrbanSpec refers to data **by name**, through `dataRef` strings in `map.layerRefs[]`, `plot.dataRef` (and `plot.mapRef`), `compute[].dataRef`, and `fromFeature.layer` inside compute uniforms. Before the grammar runs, the behavior hook ([`autkGrammarBehavior.tsx`](../utk_curio/frontend/urban-workflows/src/adapters/node/autkGrammarBehavior.tsx)) reads the input once, through the path shared with the Vega-Lite node (see [Reading a Grammar Node's Input](#reading-a-grammar-nodes-input)), and injects it as named `geojson` sources the spec can reference. A document that only loads data of its own does not read its input. Upstream geojson is data the browser already holds, so it stays client-side; only the spec's own authored `data` sources (OSM / PBF / CSV and the like) run in the backend sandbox. There are two cases:

**1. Single frame, the `upstream` keyword.** A single upstream frame (e.g. a Python GeoDataFrame from a computation node, or one routed through a Data Pool) is injected as one source named `upstream`:

```json
"map": { "layerRefs": [{ "dataRef": "upstream", "getFnv": "mean", "getFnvType": "quantitative" }] }
```

**2. Layer array, named layer references.** A multi-layer array (emitted by an upstream data-only `autk-grammar` node, e.g. one whose `data` block loads an OSM/PBF stack with `autoLoadLayers`) exposes each layer under its own table name, so the spec can target layers individually:

```json
"map": { "layerRefs": [{ "dataRef": "table_osm_buildings" }, { "dataRef": "table_osm_roads" }] }
```

A source loads as the autk-db layer type its frame carries: a layer record's `type`, the envelope's `layerType`, or a geodataframe's `metadata.layerType` (`gdf.metadata`, kept in the artifact's `value_json`, sent as `X-Curio-Frame-Metadata` on the Arrow path and as `data.metadata` on the JSON path). A Discovery OpenStreetMap download's loader sets it. A `buildings` source's features get a `height` (and `min_height`) where autk-map, which reads the first height key a feature has, would read none (`utils/buildingHeight.ts`): a `height` of null beside `building:levels`, or no height at all (6 m above the base). Every other feature is passed as it came, and the table keeps one feature per row.

A `DataFrame` becomes a FeatureCollection from its one geometry column; with none or several, it is refused with a reason, as is an input type the node cannot read, and the tables the document expected from it count as zero rows from upstream (`no-input-rows`, with the reason). A feature without a geometry keeps its place in the table. autk-db refuses a collection whose first feature has none, so that one trades places with the first that has one, and a map leaves such features out: map picks, plot selections and highlights go through the table's load order (`loadableSource`), so a position always names the input's row.

The name `upstream` is defined once, as `AUTK_UPSTREAM_LAYER` in `contracts.py`; the behavior hook imports the generated copy, and the preamble states it (see [Generated Contracts](#generated-contracts)).

A `dataRef` that names an unavailable table, whether an empty layer, a layer that was never loaded, or one dropped by an upstream node, is dropped before the grammar executes: the behavior removes the `map.layerRefs` entry or `plot` block and logs a console warning, which for a missing table lists the non-empty table names that *are* available; a `compute` block whose `dataRef` matches no layer is skipped. A map that keeps some of its layers renders them, and its success output notes the ones it lost, naming an empty table apart from one the dataflow does not produce. One left with nothing to draw is reported as an empty render (see [Render Outcomes](#render-outcomes)), and a reference to a table that exists but holds no rows is blamed on that table's source rather than on the reference.

[Example 09](examples/09-heterogeneous-data-linked-views.md) demonstrates the `upstream` keyword; [Example 11](examples/11-autark-pbf-loading.md) demonstrates named layer references.

### Connection Validation

`src/ConnectionValidator.ts` enforces rules when the user draws an edge:

- Source port type must be compatible with target port type.
- Port cardinality is respected (e.g., a `'1'` input port rejects a second incoming edge).
- `Merge Flow` nodes have special cardinality rules handled by their behavior hook via `dynamicHandles`.

---

## Execution Pipeline

### Step-by-Step: Running a Node

When a user clicks the play button on a node, the following sequence occurs:

```
1. UniversalNode.sendCode()
   Collects: node code, nodeType, upstream artifact ID + kind

2. POST /processPythonCode  (Backend)   [Python nodes]
   POST /processJavaScriptCode (Backend) [JS Computation nodes]
   Body: { code, nodeType, input: { filename: <artifact_id>, dataType: <kind> } }

3. Backend proxies to Sandbox
   POST {SANDBOX_HOST}:{SANDBOX_PORT}/exec    [Python nodes]
   POST {SANDBOX_HOST}:{SANDBOX_PORT}/execJs  [JS Computation nodes]
   Body: { code, nodeType, file_path: <artifact_id>, dataType: <kind>,
           dataset_paths: { <datasetId>: <absPath> } }

   dataset_paths resolves the portable curio_dataset_path("<id>") calls that
   Data Catalog loader snippets emit. See "Portable dataset paths" below.

4. Sandbox executes user code
   Python: worker.py::execute_code defines it as userCode(arg) and runs it via exec()
   JavaScript: spawns a Node.js subprocess, wraps code in async function(arg){…}
   - Both: load_from_duckdb(artifact_id) → reconstructs the Python/JS value
   - Both: save_to_duckdb(output) → inserts artifact row, returns new artifact ID
   Returns: { "path": "<new_artifact_id>", "dataType": "<kind>" }

5. Backend reads sandbox response
   Returns to Frontend: { stdout, stderr, output: { path: <artifact_id>, dataType }, missingModule }

6. Frontend: outputCallback(nodeId, output)
   - Updates FlowProvider.outputs[] with new artifact ID
   - Downstream nodes' INodeData.input is updated
   - React re-renders downstream nodes

7. ProvenanceProvider.nodeExecProv()
   records timestamps, types, source; in-browser only, no backend call
```

**JavaScript execution detail:** `JS Computation` nodes call `JavaScriptInterpreter.interpretCode()` which posts to `/processJavaScriptCode`. The sandbox's `/execJs` endpoint calls `execute_js_code()`, which writes a temp `.js` file wrapping user code in an async function, spawns `node <file>` as a subprocess, reads the return value from a second temp file, and saves it to DuckDB. No separate Node.js server is needed; the Node subprocess is per-request and fully isolated.

### Render Outcomes

A node the browser renders (Vega-Lite, Autark) can run without an error and still draw nothing. [`renderOutcome.ts`](../utk_curio/frontend/urban-workflows/src/utils/renderOutcome.ts) is the one decision every such renderer calls. It takes what the renderer could count (`RenderCounts`: rows handed in, rows the node's own data sources loaded, rows holding a usable value in the plotted fields, marks drawn, layers requested and resolved) and returns whether the render is empty and why. An empty render is reported as an error whose runtime journal `kind` is `empty-render:<cause>`. The rules run in order and the first match is the cause:

| Cause | When | At fault |
|---|---|---|
| `no-layers` | Every layer the document asks for names data the dataflow does not produce | the document |
| `empty-source` | The node's own data sources loaded zero rows, and no other rows arrived to draw from | the document |
| `no-input-rows` | Zero rows arrived from upstream | the upstream node |
| `nothing-drawn` | Rows arrived and none of them holds a usable value in the plotted fields, or none became a mark | the document |

A renderer that already knows why nothing was drawn (a `geoshape` over data with no geometry column, for example) passes that sentence as `explanation`, and a `nothing-drawn` message carries it in place of the generic reason. One that knows why its input cannot be drawn (a `DataFrame` with no geometry column, a refused input type) passes `inputProblem`: a `no-input-rows` message carries it, the upstream stays at fault, and a partial note adds it. A count the renderer could not make stays `undefined`, and an uncounted render gets no verdict. The default Autark data path is the common case: the sandbox hands back a DuckDB artifact reference rather than the layers, so a data-only node there lists the tables it loaded without claiming anything about their rows. Autark counts are taken before empty sources are dropped, so an empty table is still known to exist.

The harness reads the cause from the `kind`, never from the message. [`result_shape.py`](../utk_curio/backend/app/agents/domain/result_shape.py) asks `is_document_at_fault`, which reads the same table: a cause at fault turns a valid document's round into a failed round and asks for a correction, `no-input-rows` leaves the document untouched and reports the upstream, and a cause the backend does not recognize is treated as at fault. The prefix, the cause names and the at-fault table are defined once and generated for the frontend (see [Generated Contracts](#generated-contracts)).

### Running Python Code

[`sandbox/app/worker.py`](../utk_curio/sandbox/app/worker.py)::`execute_code` runs a Python node's code in the sandbox process; under isolation, the confined child in `sandbox/isolation/child.py` does the same in its own process (see [Sandbox Isolation](#sandbox-isolation)). Each run:

- Builds a fresh namespace from the pre-loaded library globals, adds the session's earlier import bindings, `curio_dataset_path` and `curio_secret`, and defines the code as `def userCode(arg):`.
- Calls `load_from_duckdb(artifact_id)` to reconstruct the upstream Python object (DataFrame, GeoDataFrame, scalar, tuple, etc.) from the shared DuckDB database, and passes it as `arg`. A Merge Flow's inputs arrive as a list.
- After the code returns, calls `detect_kind(output)` to classify the output. A node's type contract is its template's declared ports, which the canvas enforces when an edge is connected.
- Calls `save_to_duckdb(output)` to persist the result, and returns the new artifact id and kind.

`load_from_duckdb` and `save_to_duckdb` live in `utk_curio/sandbox/util/parsers.py`, `detect_kind` in `utk_curio/sandbox/util/codec.py`, and the DuckDB connection in `utk_curio/sandbox/util/db.py`.

### Sandbox Isolation

The sandbox runs as a separate Flask process. It:

- Binds `127.0.0.1` by default and is not published by the Docker image, so
  only the backend on the same host can reach it.
- Requires a shared secret on every route that can run code or read artifacts
  (`/exec`, `/execJs`, `/get`). The secret is minted per launch by
  `main.py::set_environment_variables` into `CURIO_SANDBOX_TOKEN`, attached by
  the backend in `_sandbox_call`, and checked in `sandbox/app/auth.py`. An
  instance started with `--deploy` refuses to boot without one.
- Sends no CORS headers, because no browser calls it directly.
- Caches repeated executions of identical code + input combinations (`sandbox/app/utils/cache.py`).

> [!WARNING]
> **By default this is a network boundary, not an execution boundary.** Unless
> isolation is on, node code runs with `exec()` inside the sandbox
> process itself (`worker.py::execute_code`), with unrestricted builtins, as the
> same OS user, with no memory cap and no timeout. Anyone who can author or edit
> a node can read and write everything that process can, including
> `instance/urban_workflow.db`. Treat node-authoring rights as equivalent to
> shell access on the host, and do not offer them to untrusted users.

### Isolated node execution (opt-in, Linux only)

Isolation runs each node's Python in a short-lived child process
instead of in-process. `utk_curio/sandbox/isolation/`:

| Module | Role |
|---|---|
| `mode.py` | Resolves whether isolation is active, and whether a missing capability is fatal |
| `protocol.py` | The JSON manifest crossing the boundary, and the validation applied to anything a child returns |
| `zygote.py` | A warm, single-threaded process that forks one child per execution |
| `child.py` | The confinement steps and the node run itself |
| `supervisor.py` | Parent side: scratch directories, the wall-clock deadline, process-group kill |
| `runner.py` | One execution end to end |
| `lifecycle.py` | Starting and replacing the zygote |
| `util/staging.py` | Artifacts in and out of a child's scratch directory |
| `hardening.py` | Filesystem permissions, and the startup audit that verifies them |

**Linux, not POSIX, and what happens elsewhere.** Three of the primitives are
POSIX (`os.fork`, `resource.setrlimit`, `os.killpg`), but confinement also
calls `prctl(PR_SET_NO_NEW_PRIVS)` through `libc.so.6`, and hosting needs
seccomp on top of that. macOS has neither, Windows has none of it. Curio is
developed on both, so the rule is deliberately asymmetric:

- **Local launch** (no `--deploy`): `CURIO_ISOLATION=fork` off Linux
  degrades to the in-process path and logs one warning naming what is missing.
  Your nodes run **unisolated**. That is the trade, because breaking a
  developer's laptop to enforce a boundary that only matters on a shared
  instance would be the wrong one.
- **Hosted launch**: the same request is fatal. The sandbox refuses to start
  rather than serve while appearing isolated.

macOS is a local development platform for Curio, not a deployment target, so it
is not expected to isolate. Run the Docker image to exercise the isolated path.

Five design points worth knowing:

- **The parent keeps every privilege the child must not have.** It owns the
  DuckDB connection, resolves artifacts, and enforces session scoping. The child
  sees only a scratch directory of staged files. Frames are already stored as
  parquet files, so staging an input is a hardlink and persisting an output is a
  rename: the parent never parses bytes a child produced.
- **One execution account, not one per Curio user.** `CURIO_EXEC_USER` names a
  single OS account that every user's nodes run as. The boundary this buys is
  therefore *node code against the host*, not *user A against user B*. What
  keeps two users apart is session scoping in the parent, which the child cannot
  reach at all: `staging._read_row` reports another session's artifact as
  **missing** rather than forbidden, so its existence cannot be probed. Two
  consequences follow from the shared uid, and neither is fixed by a mode bit:
  concurrent children can reach each other's scratch directories, and a node can
  find a sibling through `/proc`. Per-user OS accounts would close that, at the
  cost of copying instead of hardlinking every staged input, because `chown`
  acts on the inode. That is the trade being made, deliberately.
- **A node's writes go through the parent, never straight into a store.** The
  path is child, then scratch directory, then the parent's validated
  `persist_output`, then the backend's `auto_install_node_output`. Because the
  child never writes into an indexed store, it cannot forge a manifest or a
  catalog entry. With an execution account the child's cwd is a per-user work
  directory (`.curio/exec-scratch/users/<key>/`), which is the one place it may
  write: it is `0700` and owned by the execution account, it persists between
  runs, and a `docs` symlink is dropped in so the bundled examples' relative
  reads still resolve. A relative write anywhere else fails, since the launch
  tree is root-owned by then.
- **No pickle in either direction.** A child's manifest carries a kind tag,
  JSON scalars, and flat filenames only. Unpickling a hostile child's output in
  the privileged parent would hand back most of what isolation removed.
- **Node code loses direct store access.** The in-process path seeds
  `load_from_duckdb` / `save_to_duckdb` / `save_dataset_parquet` into user
  scope; under isolation those names raise instead. Nodes exchange data through
  inputs and return values.

**Syscall confinement is not enough on its own.** seccomp does not stop
`open()`, and reading files is what a data node legitimately does, so a
world-readable `instance/urban_workflow.db` is readable by node code with no
escape required. `hardening.py` tightens those paths to owner-only at startup
and then audits them; a hosted instance that is still exposed refuses to serve
rather than pretend. This is also why the execution account matters: without an
unprivileged execution account the child shares the sandbox's own filesystem
access, and only the resource limits and syscall filter apply.

Network denial uses a seccomp **denylist** (`socket`, `connect`, `ptrace`,
`mount`, and friends), not an allowlist. An allowlist for arbitrary Python with
arbitrary C extensions would break constantly and get widened until it meant
nothing. The denylist promises less and is honest about it. `unshare(CLONE_NEWNET)`
would be stronger but needs `CAP_SYS_ADMIN`, which Docker does not grant by
default.

> [!IMPORTANT]
> **Implementation status.** The confinement code runs in CI. Three jobs cover
> it, and each covers a different half:
>
> - `unit` runs `tests/test_isolation_linux.py` in the sandbox suite on Linux: the
>   fork, the seccomp filter (socket, connect and ptrace denied), the rlimits,
>   the deadline kill, session scoping across the boundary, and the zygote
>   holding no DuckDB handle. This is where the *boundary* is demonstrated.
> - `test-isolated` boots a second stack with `CURIO_ISOLATION=fork` and runs
>   the Python-node workflows against it. This is where *ordinary nodes still
>   work* is demonstrated. It asserts the stack actually came up isolated
>   before trusting the result.
> - `test-exec-user` boots a third stack with isolation and the
>   `curio-exec` account, the same shape `docker-compose.deploy.yml` ships,
>   and asserts the **filesystem** half over the sandbox's HTTP API
>   (`tests/live/test_exec_user_boundary.py`). This is the only job whose
>   children are unprivileged: everywhere else they run as root, and root reads
>   through any mode bit. It pins that node code really is `curio-exec` and not
>   uid 0, that a hardlinked input still reaches the child, that the work
>   directory is `0700` and owned by the execution account, and that
>   `instance/`, `.curio/data`, `.curio/users`, `datasets/` and another user's
>   file named by absolute path are all denied.
>
> It is a separate job because an execution account and the e2e harness cannot
> coexist: hardening `.curio/data` breaks the host-side ground-truth step, which
> executes every code node in the test process and writes artifacts there as the
> runner user. So that job drops the workflow comparison and asserts over the
> API instead (see `docker-compose.ci-exec-user.yml`).
>
> `--deploy` turns isolation on, and refuses to start where the host cannot
> provide it. A local `curio start` without `--deploy` leaves
> it off: isolation separates users from each other, and locally there is one.

**Where an install lands.** There is no switch for whether `pip install` may
run; there is only the question of *whose* environment it changes, and that is
decided by isolation.

Without isolation the backend and the sandbox are launched from one
interpreter, so a library installed by anyone is importable by every user's
nodes. Under isolation it goes to the caller's own tree instead. A guest is
refused either way (`users/capabilities.py::library_install_refusal`): the
shared guest is every anonymous visitor at once, so one visitor's install still
changes what the next one's nodes import, and the disk it costs has no owner.
Without auth the one local user *is* the shared guest, so that rule applies
only when auth is on and the everyday single-user install keeps working.

The sandbox has no install route. Library installs go through the backend's
`packages/infrastructure/pip_runner.py`, which is auth-gated and records what it installed per
user.

**Per-user node libraries.** Under isolation, a package's declared
python deps and anything installed through the Installed-libraries dialog go to
`.curio/exec-overlays/users/<key>/`, which the child prepends to `sys.path`
after the fork. Three things follow, and none of them is a mode bit:

- It needs the fork. The in-process worker is one process with one
  `sys.modules`; whoever imports a library first makes it importable by
  everybody, whatever the path says. So a local or Windows launch keeps the
  shared interpreter, unchanged.
- It scopes imports, not files. The execution account is still shared
  (see above), so one user's node can read another's tree by path. What it
  cannot do is have it on its own `sys.path`.
- It cannot give two users different versions of the same library. pandas,
  geopandas, shapely and duckdb are resident in the zygote before the fork;
  additions are what this serves. Per-user versions would need a zygote each.

The tree is deliberately not under `.curio/users/<key>/`, which is 0700
root-owned so a node cannot reach another user's datasets, and unlike the
per-user work directory it is **not** owned by the execution account: it is an
import path, so node code writing there could shadow a later import. The
startup audit reports it if it ever becomes writable.

### DuckDB extensions come from this instance

autk-db's `init()` runs `INSTALL spatial; LOAD spatial;`, and DuckDB autoloads
`json` for the grammar's `json_object` SQL. duckdb-wasm resolves both against
`https://extensions.duckdb.org/`.

Curio ships both extensions in `vendor/duckdb-extensions/`, laid out exactly as
the CDN serves them (`<duckdb version>/<platform>/<name>.wasm`), and both
runtimes read that copy:

- **Browser.** `frontend/urban-workflows/webpack/duckdbExtensionMirror.js` is a
  loader that prepends a redirect to duckdb's worker asset as webpack emits it,
  so the worker's request goes to the backend's `/file/vendor/duckdb-extensions/`
  instead. DuckDB's own setting for this (`custom_extension_repository`) is not
  reachable: autk-db installs the extension inside `init()`, before Curio holds
  a connection, and the worker has its own global scope.
- **Sandbox.** `main.py::seed_duckdb_extensions` copies them into
  `~/.duckdb/extensions/extensions.duckdb.org/`, which is where duckdb-wasm
  looks before downloading. Nothing is intercepted there.

Both fall back to the CDN for a file this checkout does not carry, so a newer
`@duckdb/duckdb-wasm` keeps working before its extensions are vendored; see
`vendor/duckdb-extensions/README.md` for how to vendor the new version.

### Portable dataset paths

Data Catalog loader snippets do not embed absolute paths. They emit
`curio_dataset_path("<datasetId>")`, resolved per execution, so a saved dataflow
stays valid when it is shared, moved, or opened by another user on the same
install.

The curated examples in `docs/examples/` are the reference consumers of this
mechanism: every one of their loader nodes resolves a committed catalog dataset
by id. Note the argument is the bare manifest `id`, never the `<id>@<major>`
`dirName` that `dataflow.datasets` refs carry - `SAFE_DATASET_ID_RE` permits `@`,
so an id with the major appended passes validation, misses the by-id lookup, and
fails open into a runtime error from the sandbox.

1. `backend/app/api/routes.py` scans the outgoing code for literal
   `curio_dataset_path("<id>")` calls (single or double quoted), dedupes the
   ids, and caps them at `MAX_EXEC_DATASET_IDS` (32).
2. It resolves them via `DatasetCatalogService.resolve_execution_paths`, which
   refuses any path outside the allowed read roots. Resolution **fails open**: an
   error yields an empty mapping rather than blocking the run.
3. The resulting `{id: absPath}` map rides along on the `/exec` body. The sandbox
   re-validates it (dict-shaped, stringified, ≤32 entries) and injects
   `curio_dataset_path` into the user namespace, where an unknown id raises an
   actionable `RuntimeError` instead of returning a foreign path.

The id must satisfy the same safe-id pattern on both sides before it is
interpolated into generated Python; an id that fails it falls back to a literal
quoted path. See [DATA-CATALOG.md](DATA-CATALOG.md) for the authoring view.

---

## Interactions and Propagation

Visualization nodes (`Autark`, `Vega-Lite`, `Simple View`) can emit user interactions (selections, filters, brushes) that flow **upstream** through the dataflow graph, causing upstream nodes to re-execute with the filtered subset.

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

A Data Pool resolves the selections that reach it with two modes, chosen in the two selects at the top of its body and saved with the node (`metadata.dataPool`):

- **Conflict inside visualization** (`insideChart`) combines the selects of one chart, such as a Vega chart with two params.
- **Conflict between visualizations** (`betweenCharts`) combines the charts linked to the pool by an interaction edge.

| Mode | Semantics |
|---|---|
| `OVERWRITE` (default) | Only the most recent selection applies |
| `MERGE_AND` | A row must be picked by every active selection |
| `MERGE_OR` | A row must be picked by at least one active selection |

A selection is active when it picks something: a point selection with rows, or an interval over at least one column. A select nobody has used, or one that was cleared, takes no part in `MERGE_AND`.

`FlowProvider.applyNewInteractions` hands a pool only the chart that just selected. The pool keeps each linked chart's latest selection itself, keyed by the chart's node id (`dataPoolBehavior`): the newest is priority 1, the others 0, and `utils/selectionMatch.matchSelections` resolves them. `OVERWRITE` resolves the priority-1 entry alone. A chart whose interaction edge to the pool is removed leaves that map. Choosing another mode resolves the selections the pool holds again.

The pool writes its `interacted` flags into a copy of its output (`utils/poolFlagCopy`), never into its input or into an output it already sent, which the charts downstream still hold. Its echo names the chart that just selected (`selectionSource`, see `utils/selectionEcho`) under every mode. An Autark node skips an echo of its own selection, so a plot keeps its brush; a Vega chart applies it, which only recolours rows. Every other chart shows the resolved rows, and an Autark plot shows them as its selection in place of its own brush.

The propagation counter (`INodeData.propagation`) is incremented each time an interaction change needs to trigger a re-execution, allowing nodes to detect when they need to re-run without comparing the full interaction payload.

---

## Provenance Tracking

Curio records a per-node execution history (start/end time, source code, input/output types, parent execution) so users can replay a node's evolution from the canvas. Tracking lives entirely in the browser: [`src/providers/ProvenanceProvider.tsx`](../utk_curio/frontend/urban-workflows/src/providers/ProvenanceProvider.tsx) keeps the graph in React state and persists it as part of the saved workflow JSON. Nothing is stored server-side.

---

## The Trill Dataflow Format

A saved dataflow is one JSON document, a **trill**, written to `.curio/users/<userKey>/projects/<projectId>/spec.trill.json`. It holds the graph (`dataflow.nodes`, `dataflow.edges`), the dependency lockfiles (`dataflow.packages`, `dataflow.datasets`, `dataflow.agents`), and the two provenance sections described above.

Every trill is validated against [`docs/schemas/trill.v1.json`](schemas/trill.v1.json) (JSON Schema Draft 2020-12). The schema is the source of truth for what fields a dataflow can carry. Note what it deliberately does *not* decide: a node's `type` is a coordinate into a package manifest's `templates[].id`, so which templates exist, which handles are legal, and whether a node has code at all are manifest questions that depend on the installed packages. [`projects/storage.py`](../utk_curio/backend/app/projects/storage.py) performs no validation of its own - it reads and writes the spec as opaque JSON - so the schema and the tests around it are the only enforcement.

Full field reference, ownership rules, and the CLI for checking your own projects: [`docs/TRILL-SPEC.md`](TRILL-SPEC.md).

---

## Generated Contracts

Some contracts are read on both sides of the stack: by Python and TypeScript, or by the code and a model prompt. Each one is defined once and every other copy is generated from it, so the copies cannot disagree.

- **Source module.** [`utk_curio/backend/app/agents/domain/contracts.py`](../utk_curio/backend/app/agents/domain/contracts.py) holds each definition and one render function per output. It lives in the app package, so runtime code imports it from an installed wheel, and its module-level imports are the standard library only. Python callers such as `result_shape.py`, `services.py` and `execution/runtime_journal.py` import the values directly.
- **Registry.** `contracts.GENERATED_OUTPUTS` maps each repo-relative output path to the function that renders it. The generator and the drift test both iterate it, so a new output is one entry.
- **Generator.** [`scripts/generate_contracts.py`](../scripts/generate_contracts.py) is a thin CLI over the registry. It writes every output that differs from a fresh render; with `--check` it writes nothing, lists the stale files and exits non-zero.
- **Outputs.** Committed to the repository. Code outputs start with a header that names the generator and the source module, and TypeScript outputs pass the frontend's `prettier` and `eslint` configs as generated. A prompt output has no header, since the model reads it verbatim; its hand-written text is a template beside it (`default_preamble.template.txt`), whose `{{...}}` fields are the generated parts.

  | Output | Contract |
  |---|---|
  | `utk_curio/frontend/urban-workflows/src/generated/renderCauses.ts` | The empty-render kind prefix, the render causes, the `RenderCause` type and which causes blame the document (see [Render Outcomes](#render-outcomes)) |
  | `utk_curio/frontend/urban-workflows/src/generated/autkGrammar.ts` | The Autark grammar's top-level families and the name of the layer an Autark node makes of its input (see [Referencing Upstream Data in Autark Nodes](#referencing-upstream-data-in-autark-nodes)) |
  | `utk_curio/frontend/urban-workflows/src/generated/agentCategories.ts` | The agent manifest's category vocabulary and the `AgentCategory` type, from `manifest.AGENT_CATEGORIES` |
  | `utk_curio/llm-prompts/default_preamble.txt` | The shared agent preamble: the Trill block, projected from [`docs/schemas/trill.v1.json`](schemas/trill.v1.json) to the fields `contracts.TRILL_PROMPT_FIELDS` names; every list of built-in templates (description, control, port types, the connections an input accepts, output cardinality, interaction support), read from the built-in manifest and the packages layer's `input_capacity`, and naming each template by its label; the Merge Flow's socket names; and the section on Autark documents, rendered from the vendored schema (see [The Autark Schema](#the-autark-schema)) |

- **Drift test.** [`test_generated_contracts.py`](../utk_curio/backend/tests/test_agents/test_generated_contracts.py) re-renders every registered output and fails on any difference, printing the diff and the command to run. It is pure Python, so it runs in the normal backend suite and a hand edit to an output turns it red.

To change a contract, edit `contracts.py`, run `python scripts/generate_contracts.py`, and commit the source and the regenerated outputs together.

### The Autark Schema

The Autark grammar is defined upstream: autk-grammar generates a JSON Schema from its TypeScript types and publishes it with each release. [`schemas/autk-grammar.v1.json`](../utk_curio/backend/app/agents/schemas/autk-grammar.v1.json) is a byte-for-byte copy of the released file, beside the module that reads it so an installed wheel carries it, and `autk-grammar.v1.source.json` records the release and the file's digest. [`scripts/sync_autk_schema.py`](../scripts/sync_autk_schema.py) vendors a release; `test_autk_schema_vendored.py` checks the copy against its record offline, and the weekly `autk-schema` workflow re-fetches the release and fails on a difference.

Everything Curio says about Autark documents is read from that file:

- **Validation.** `document_validation.validate_autk_grammar` validates a document against the schema, choosing the validator by the schema's draft. An error inside a field that takes one object or a list of them is explained by the branch that fits the value, and a missing field is named with its description from the schema. One rule sits on top, because no schema form states it: the document must load, compute or draw something, and a map must list a layer. Without `jsonschema` or the schema file, a document is *unchecked*, never invalid.
- **Refusal text.** `contracts.render_autk_shape` renders the schema as one line naming the families and what each requires, for the refusal a reply that is not a document gets.
- **Preamble.** `contracts.render_autk_region` renders the preamble's section on Autark documents: the data source types and what each requires, the compute fields, the map and plot requirements and the closed enums.

---

## Agent Prompt Composition

Every system turn an agent receives is built by one function, `contracts.compose_system`, from fixed slots in a fixed order. The attached run (`services._prepare_run`), the delegated run (`delegation.run_delegate`) and a training example (`training/dataset.py`) all call it.

| Slot | Holds | Owner |
|---|---|---|
| preamble | The built-ins' shared `default_preamble.txt`, an imported definition's own `prompts.system`, or none | the repository, or the definition |
| instruction | Exactly one: the agent's `instruction` prompt, the invoked mode's, the definition's `autk-grammar` prompt for an Autark document under its reply schema, or the attachment's edited intent | the repository, or the user |
| configuration | The catalog settings the run reads, framed as data | the user |
| tool protocol | How to ask for a tool: the granted tools and the `toolRequest` syntax, or on native tools one line on calling them; with the `datasetCandidates` schema for a run that can search the catalog | the runtime |
| runtime | The template roster, the enlistable templates and the delegation paragraph, each its own slot | the runtime |

A run selects its instruction and never appends to one. An edited intent replaces the instruction slot only, and everything a user wrote precedes every runtime-owned slot. A delegated run carries the first three slots: it is tool-less and depth-1.

The slots reach the provider apart. `contracts.system_message` puts the joined text in the system message's `content` and the slots beside it, and [`providers.py`](../utk_curio/backend/app/agents/infrastructure/providers.py) maps them per provider: Anthropic receives one text block per slot, with the preamble marked cacheable; Gemini a list of system instructions; an OpenAI-compatible server the one joined system message, since some local chat templates reject several. A system message without slots (the title call) is sent as its text.

A run loop takes a typed turn, `providers.ChatTurn` (text, native tool calls, stop reason), from `run_chat_turn` or `stream_chat_turn`; a bare string is a text turn, which is what a scripted test fake returns. `run_chat_completion` and `stream_chat_completion` are the text-only forms. The services module binds the two turn functions once, and the title call goes through the same seam, so one test fake answers a whole run.

Usage counts every input token as `inputTokens`, cached or not (Anthropic reports cache reads and writes apart from its input count), plus `cacheReadTokens` and `cacheWriteTokens` when the provider reports them. The ledger, a run's execution record and the evaluation record keep them.

What an endpoint can do beyond text is [`chat_capabilities.py`](../utk_curio/backend/app/agents/infrastructure/chat_capabilities.py)'s answer: native tools and a reply schema. Anthropic, Gemini and OpenAI's own endpoint are known from their APIs; any other OpenAI-compatible server is asked once per model with a charged one-tool trial (`providers.probe_native_tools`), recorded per account in `.curio/users/<u>/chat-capabilities.json`, its tokens on the ledger with the configuration's id. A model trained in Curio stays on the fenced protocol, and the scripted provider answers what a test scripted, fenced by default. A manifest's `providerRequirements` is a preference: nothing refuses a run over it.

- **Modes.** A capability that names an `instruction` (a `prompts` key) is a mode. A delegated run of it runs that prompt in place of the agent's `instruction`, and pins that prompt's digest. Two internal agents are built this way: each of the Dataflow Planner's six capabilities and the Dataflow Reader's two keeps its own prompt file (`builtin.BuiltinMode`).
- **Scoped delegation.** A `delegatesTo` entry may name the capabilities it delegates (`{"id", "capabilities"}`). `delegation.resolve` and the delegation paragraph honour the scope, and the capability fallback never reaches an internal agent, which is reached only through a parent that delegates it.
- **Catalog settings.** `contracts.CATALOG_SETTINGS` defines each setting once: its key, JSON Schema, shipped default and renderer. [`catalog_settings.py`](../utk_curio/backend/app/agents/repositories/catalog_settings.py) stores the values an account changed in `.curio/users/<u>/catalog-settings.json` (the read never raises: a missing, corrupt or invalid value reads as the default) and renders the configuration slot for the keys a run reads, `inputs.requiredConfig` for every run and a delegated capability's own `requiredConfig`. A key no setting defines is skipped with a warning. The slot's digest is pinned as `configurationSha256`.

**Native tools.** An attached run whose configuration calls tools natively is offered its grants and its delegates as tools (`tools.native_tools`): each contract with the JSON Schema of its params (`ToolContract.parameters`), named by its id with each dot written as two underscores (`dataflow__read`), and one `delegate` tool whose `capability` lists what the agent may delegate. Its system turn carries a line on calling them in place of the tool list and the `toolRequest` syntax, and its delegation paragraph names the `delegate` tool in place of the `delegateRequest` syntax.

- **One path.** The model's first call becomes the request part a fenced block parses to, through the same parser and budgets (`parse_tool_request_verbose`, `parse_delegate_request_verbose`), and from there takes the fenced request's path: grant check, mint, delegate, round accounting. A fenced block in a native run is honoured too, and answered in kind.
- **Results.** A tool message answers the call, flagged as an error unless the status is `ok` or `proposed`; a call that cannot be read gets its errors back and spends a round. Every other call of the reply is answered as not run, and the last round offers no call (`tool_choice` none).
- **Per provider.** OpenAI receives `tool_calls` and `tool` messages, Anthropic `tool_use` and `tool_result` blocks, Gemini function calls and responses. Gemini's schema has no open objects, so one (a manifest, a delegate's `inputs`) is offered as a JSON string and read back as an object.
- **The fallback.** An endpoint that answers a request offering tools with a 400 or 422 (`providers.NativeToolsRefused`) gets the same round again on the fenced protocol. `services._RunConversation` keeps the fenced form of every round beside the native one, so the run carries on from where it was. Once that fenced call succeeds, the refusal is recorded for an endpoint the table does not know (`chat_capabilities.record_native_refusal`), and the next run starts fenced.
- **Records.** The execution record pins `toolProtocol` (`native` or `fenced`) for a run that can call anything, and `nativeToolsRefused` after a fallback. Sessions keep text only, so a conversation moves between protocols and configurations freely. A delegated run is tool-less, so it never changes protocol.

**Reply schemas.** A delegated `node.content.generate` run for a node whose grammar (the template roster's `grammarId`) is `autk-grammar`, by a definition that declares an `autk-grammar` prompt, on a configuration that takes a reply schema, holds the reply to the Autark document's schema ([`reply_schemas.py`](../utk_curio/backend/app/agents/application/reply_schemas.py)). The run's instruction is that prompt (`new_content_autk_prompt.txt` for Node Content Builder), and the pins record the `replySchema` by name and the prompt's `promptSha256`.

- **The projection.** Both providers take a subset of JSON Schema, so what is sent is projected from the vendored schema when first asked for: objects closed; a map as a list of `{key, value}` entries; an open object, and a reference into a recursive definition (a GeoJSON geometry), as a JSON string; the conditional unions as `anyOf`; a constant as a one-value enum; every other keyword dropped. OpenAI's strict mode also requires every key, so optional ones may be null; Anthropic keeps them optional. Gemini's SDK schema cannot express the document, so Gemini is never sent one, and neither is an endpoint the capability table does not know.
- **Decoding.** The reply is decoded back into the document (entries into maps, JSON strings into what they encode, nulls removed) before the correction loop sees it. The vendored schema and `document_validation` decide whether it is valid, including for what the projection drops. A test encodes every shipped Autark document into the projection, checks it validates there, and decodes it back.
- **The fallback.** A 400 or 422 on a request carrying the schema (`providers.ReplySchemaRefused`) sends the same request again without it, under the capability's own instruction, and the pins say `replySchemaRefused`. That endpoint and model are not sent one again in the process.

---

## LLM Configurations and Resolution

An account's LLM configurations live in one owner-only file,
`.curio/users/<u>/llm-configs.json` (`{version, configs, default, agents}`),
kept by [`llm_configs.py`](../utk_curio/backend/app/agents/infrastructure/llm_configs.py).
`agents` maps an agent id (the coordinate before `@`, so one choice covers
every version and project) to a configuration id or `"deployment"`. Nothing
about the choice goes into a project, attachment or manifest.
Only the store's own reads (`LlmConfigStore.read` and `record`) carry a key:
every response carries `hasApiKey` and `baseUrlHost` instead. The file is written through
[`owner_only_file.py`](../utk_curio/backend/app/common/owner_only_file.py),
which connection keys use too: a 0700 directory and a 0600 file, written to a
temp file, fsynced and renamed under an exclusive lock.

A configuration names its own endpoint (`endpoint: "own"`, with `apiType`,
`baseUrl` and `apiKey`) or this Curio install's (`endpoint: "deployment"`),
whose type, URL and key are read from the deployment when a run resolves it. A
key never follows a configuration to another endpoint: an update that changes
the type, or the URL's scheme, host or port, needs the key again or
`clearApiKey`.

[`provider_config.resolve_llm`](../utk_curio/backend/app/agents/infrastructure/provider_config.py)
is the one resolver, and it reads `config.DEFAULT_LLM_*` and `GUEST_LLM_*`
at call time. It needs only the storage key, so it
works in job threads:

1. A hosted guest (a guest on a `--deploy` instance) runs on the guest
   configuration, `GUEST_LLM_*`, and never opens the file; so does every
   delegate of a guest's run.
2. An internal agent (`builtin.internal_agent_ids()`, from `in_catalog`) runs
   on its caller's configuration, always.
3. Any other agent runs on the configuration chosen for it (`source:
   "assigned"`).
4. With no choice, a delegated agent runs on its caller's (`source: "caller"`),
   and an attached one on the account's default configuration, else the
   Deployment default (the deployment's endpoint with
   `CURIO_DEFAULT_LLM_MODEL`), else the run is refused.

A reference that does not resolve (a choice or a default naming no
configuration, a withdrawn Deployment default or This Curio install endpoint,
an unreadable file) is refused, never replaced with another configuration. A
refusal is a `ProviderConfigError`, answered as a 400 with
`remedy: {kind: "llm-config", agentId}`. The local shared guest (a launch
without `--deploy`) owns a file like any account, and its Deployment default
reads `GUEST_LLM_*`.

Where it is called:

- An attached run resolves once per request, from the attachment's agent
  (`routes._llm_for_attachment`), and detached jobs keep that configuration.
- `delegation.run_delegate` resolves the child when it starts, with the parent's
  configuration as `caller`. Every fan-out passes through it, so a choice
  changed during a Solve reaches the delegates started after it; a refusal is
  the child's "could not start", never the parent's error.
- The Solve batch, the per-node Solve, validation and simulation resolve the
  delegates they always call (`node.content.generate`, and `dataset.discover`
  when a data-loading node is involved) before writing any in-flight state
  (`services._check_delegate_llms`), so a broken choice refuses once.
- A confirmed dataset selection starts the node's builder on the builder's
  configuration, resolved when it is picked (`_delegate_confirmed_fetch`),
  never the Dataset Finder's.
- `choosable_agents` lists who may have a choice: the catalog cards, published
  definitions and the account's imports, one row per agent id.

The resolved `ProviderConfig` carries `config_id`, `label`, `source` and
`trained`, and its `api_key` is left out of its `repr`. Run pins record
`llm: {configId, label, baseUrlHost, source}`, ledger entries record
`llmConfigId`, and provider error text is redacted with the call's own key
before it is streamed, persisted, logged or returned. Training runs only on a
configuration that holds the user's own key (by default, the Dataflow Builder's),
and activating a trained model adds a configuration with `origin: "trained"`
and chooses it for the Dataflow Builder.

---

## Agent Runtime

What an agent may change, what Solve checks before anything lands in a node, how connection keys reach node code, and how an evaluation measures a model. The user-facing side is in [AGENT-CATALOG.md](AGENT-CATALOG.md) and [USAGE.md](USAGE.md).

### Dataflow plans

A Dataflow Builder plan may add nodes, add connections, and remove, each part optional, so a plan that only rewires a connection is valid and needs no filler node. Two rules hold:

- **A connection carries a kind.** `interaction` is the Trill's feedback link: between a visualization and a Data Pool node, or between two visualizations when one of them is a Vega-Lite or Autark node (`plan_topology.interaction_highlighters`), `in/out` at both ends, bidirectional on the canvas, carrying selections rather than data. It is refused anywhere else, by a message that names the node it was aimed at.
- **Data connections stay a DAG.** A plan whose data edge would close a cycle is refused when it is proposed, with the loop written out and the fix named. The check runs again at Apply against the live canvas, so a cycle drawn in the meantime stops the apply. A cycle the plan did not create is reported, never blamed on the plan.

Every removed connection is named on the card, and every applied result ends with a `Topology:` verdict, `acyclic` or the path of a cycle still present, which the agent is instructed to read before it claims a repair.

### Required agents

The Dataflow Builder requires three agents: the Node Content Builder (its Solve generates content through it), the Dataset Finder (resolving a data-loading node asks it for candidates) and the Node Builder (every node an applied plan creates is given one). The runtime calls each of them on a fixed path, not at the model's choice. The Node Builder in turn requires the Dataset Finder.

A dataflow that lacks an agent's required agents is repaired the next time the user acts on that agent: a run, an attach, an apply or a Solve. The missing agents are added through the same install path a click uses, and the chat names each one it added. Only declared required agents are added this way; a preferred delegate reaches the user as a review card.

### Source grounding

An agent never decides on its own that a file exists. Every piece of node content an agent authors (a Node Builder `node.create`, a content replacement, a new node type's first node, and every node the Dataflow Builder's Solve fills) passes one runtime **source-grounding gate** before it can become a review card or reach the saved dataflow:

| The code opens or fetches | Grounded only when |
|---|---|
| A local file path | The user typed that path in the conversation, or the Data Catalog resolves it. The portable `curio_dataset_path("<id>")` line the catalog's loader recipe emits counts by dataset id. |
| A URL | The runtime probed it in this run (2xx; 401/403 is accepted and labeled *credential-gated*), or a candidates card in this conversation already carried it as **Verified ✓**. A URL in the user's own message is not evidence: the runtime checks it. |
| Nothing (inline data in a data-loading node) | The user asked for synthetic or sample data; the card then says *Synthetic data*. |

Anything else is refused with the literal named and the allowed routes listed. The refusal is a free correction round for the agent, and a Solve that cannot ground a node marks it failed for an ungrounded source, with the remedy, instead of writing the code. The review card carries a **Source** block above the preview: the catalog dataset by title and id, the URL with its verification chip, the user-provided path marked *not checked by Curio*, or the synthetic label.

Discovery follows the same order. Node Builder holds `catalog.search` (rows include the resolved path and the loader line) and can delegate `dataset.discover` to Dataset Finder: the tool-less child receives the catalog listing as input, its candidates are re-checked against that listing and probed by the runtime, and the two-lane card appears in the Node Builder's own chat. Selecting rows prefills an editable prompt, and nothing is proposed until it is sent. In the Dataset Finder's own chat the same card composes the reviewed `dataset.install` or the hand-off to Node Builder.

### The Dataset Finder on data-loading nodes

Applying a plan gives every created node a Node Builder, and every data-loading node its own Dataset Finder as well; the applied card says what it attached. The whole-plan Apply and Simulation Mode's per-node apply do this the same way.

Resolving such a node goes to that Dataset Finder:

| The node | What happens |
|---|---|
| Its intent already names a source (a path the user typed, a Data Catalog dataset, a URL the runtime verified, or explicitly synthetic data) | Discovery is skipped, and the skip is recorded with the literal that grounded it. |
| The user's Data Catalog holds datasets | The first attempt is generated against those rows, and the grounding gate enforces them. |
| Nothing could ground it, or the attempt was refused for its source anyway | The runtime asks that node's Dataset Finder. The candidates appear in its chat, and the node's Solve result is pending, awaiting a dataset selection, with an **Open Dataset Finder** button. Nothing is generated, run or written. |

**Confirm source for this node** records the selection against the node. The record is what the next Solve reads, so the loader is built from exactly the confirmed source. A catalog row that is not installed yet keeps the node waiting for its reviewed install, and the applied install says how many nodes it unblocked. A row the runtime cannot reach at confirmation time is recorded with that verdict and does not resolve the node.

Every external row also says what the user can do with it, read from the same probe and never from the model's prose:

| The row's access | What the card offers |
|---|---|
| **fetchable**: the data URL answered with data Curio does not download itself (an XML API, or a plain http link) | Confirming it starts the node's own builder on it at once. The loader is written, verified and lands as ordinary reviewed content. |
| **manual-download**: the data URL answered with a page, gated it (401/403/451), or served an archive | The card carries the portal's download steps (its URL, the page as it answered, the file format, the row's stated requirement) and an **Import dataset** button, the same Data Catalog import as the drawer footer. After the import, that dataset becomes the node's source and the builder starts on it, by id. The imported file records the row's link as its `discoverySource`, and a file already held is not registered twice. |
| **unknown**: nothing was probed, the policy refused the URL, or the answer was neither | The row says so, and nothing upgrades it. |

A row marked **Downloadable** is one Curio fetches itself (see [Agent tools](#agent-tools)). Its **Download** runs the Discovery Catalog's own download job, and the dataset it lands becomes the node's source. Confirming the row does the same: a small file lands before the confirmation answers and the builder starts on it, and a larger one keeps the node waiting until the next Solve finds it landed. A downloadable row carries no portal steps and no fetch code.

The download steps are the portal's: when a page title is all the portal gave, the step says the portal describes the click path. Curio does not script a click-through portal's download.

A dataset imported or installed while a Solve session runs is picked up by it: the session watches the moved selection record, and the dataset's sandbox path is resolved for the running job. The Dataflow Builder therefore plans first and never blocks a plan on dataset identity: a data-loading node is planned with an intent naming the data it needs, and its source is resolved at the node.

### What Solve checks

What lands in a node is something the runtime has checked. The routing comes from the node template's declared facts, never from a list of node names:

| The node carries | What Solve does | What it reports |
|---|---|---|
| **Code** the sandbox runs (`hasCode`) | Generates, gates the sources, runs it, and reads the shape of the result. A table or geotable with no rows, produced from inputs that had rows, is a failed round with the diagnosis: the inputs' row counts, their key columns and their sample values. | verified, or a failure naming what happened |
| A **document** (`hasGrammar`: a Vega-Lite chart, an Autark grammar) | Validates it against its grammar's JSON Schema: the one Vega-Lite publishes, or the vendored autk-grammar schema (see [The Autark Schema](#the-autark-schema)). An invalid document is a correction round; a reply that is not a document at all is refused the same way. | validated as a document, not executed |
| **Nothing** (a Merge Flow, a Data Pool, a Simple View, a Spatial Join) | Nothing. These nodes are wired, not written: no model is asked for their content. | wired, not written |

A kind nothing here can validate is not written at all: the node stays pending with the reason.

- **Empty results.** A node that filters everything out fails. The common case is a join on two columns whose values are different kinds of thing, such as a community-area number against a census tract id. An empty result that is wanted is written in the editor by hand.
- **Emptied columns.** A result can keep its rows and hold nothing: a left join whose keys do not match fills the other side with nulls. Curio reads the columns a node emptied (all null, and not already null in the input they came from) and fails the round naming them, with the same diagnosis a zero-row result gets. The content contract tells the generator never to fabricate values, never to fill nulls, and never to let a join that matched nothing stand; saying in one line that two datasets cannot be joined is an accepted answer.
- **Absent output.** A node whose code ends in `return None` stores an artifact typed `null`. The run journal, the consumer type check and the shape check each name that absence as a failure, and the refusal quotes the node's own conclusion back: returning that sentence as the whole answer, with no code, records it as the node's outcome. An output type Curio does not recognize is accepted: absent and unknown are different things.
- **Empty renders.** A document that draws nothing is an empty render (see [Render Outcomes](#render-outcomes)). Solve corrects the document when the cause blames it, and when no rows arrived it leaves the document alone and reports the upstream. A chart over rows with nulls counts only the rows that hold a usable value in the plotted fields. A partial loss, such as an Autark map that drew some of its layers, keeps its success. A chart meant to be empty reads as a failure, and a renderer that cannot count what it drew makes no claim.

A failing node carries its reason in its own body, one line, expandable, read from the same runtime record the agents read, so it survives a reload.

### The run journal

Every execution leaves a record wherever it ran. A node's code in the sandbox, a validation run the agent runtime drove, and a render in the browser (a Vega-Lite chart, an Autark map, a Data Pool, a Merge Flow, a Simple View, a Spatial Join, a Data Export) all write the same per-node journal, each stamped with the `origin` that produced it. An agent attached to a node reads that record.

- **A browser record is evidence, never authority.** It carries a status, a short message and the output type the node declares, never the data, and never an artifact id, which only the sandbox can mint.
- **A render never overwrites a run.** What a node's code did keeps its artifact, its output type and its traceback, and what its picture did is recorded beside it. A node that ran cleanly and drew nothing reports both.
- **A failed upstream travels with the node.** An agent asked to fix a chart whose input never arrived is told which upstream failed and what it said.
- **A node that has not run reports exactly that**, and nothing invents a schema or a result for it.

Solve's repair loop starts from the last recorded failure and checks it against the content the node still holds, so a chart that failed in the browser is corrected from its real message.

### The Solve loop

Solve runs from the Dataflow Builder's **Solve** over an applied plan, or from **Solve this node** in the chat of an agent attached to the node. The runtime executes the node's code in the sandbox exactly as Play would (the same dataset-path mapping, and a fetch-sized timeout aligned to the sandbox's own wall clock), and only code that ran successfully lands:

| The run | Then |
|---|---|
| passes | An empty plan node gets the content written. A node that already had content is untouched: "verified, no change needed". |
| fails | The failure goes back to the content generator with the traceback, the previous attempt, the grounded sources, what its inputs contain (the columns, dtypes and row counts of the frames feeding this node, through a merge in `arg` order), and a fresh probe of the URL it fetched (a `400` after a reachable base URL is a wrong request shape, not a dead endpoint). The corrected code is grounded again and re-run. |
| keeps failing | Corrections continue while the node's repair budget allows, 15 minutes by default, as many attempts as fit; the attempt cap sits above what that budget affords. A repeated candidate does not end the loop: after two repeats the next correction is told it repeated itself and must change approach, and only an eighth repeat stops it. Whichever bound stops the loop is named: the round cap, the node's time budget, or a repeated attempt. |
| still fails | Nothing is written. The node shows failed, and every attempt appears in the chat as its own card, with the exception line, the frame that raised it, and the code that attempt ran. |
| cannot run (sandbox unreachable) | The node stays pending with the reason, never failed: an outage is not a content failure. |

- **Merge inputs.** A merge hands the next node a list, one item per connected input, in the order of its input handles (`in_0`, `in_1`, ...). Play, Solve's validation runner and the generator's contract all read that order from the handles. The generator receives an `inputContract` for the node, `list` with a slot table (each slot's node, goal and columns) or `single`, and code that treats a list-shaped `arg` as a value (`arg.crs`, or `gdf = arg` then `gdf.to_crs(...)`) is refused before the sandbox runs, with the slot table in the refusal. A merge with one connected input passes its value straight through.
- **Failure lines.** The exception type and its message lead every failure line and are never cut mid-word, an error the generated code raised itself is labeled as such, and "not fixed after N attempts" is always followed by the bound that stopped the loop.
- **Budgets.** `CURIO_SOLVE_NODE_BUDGET` (default 900 seconds, the bound that normally stops a node), `CURIO_SOLVE_MAX_ATTEMPTS` (default 40), `CURIO_VALIDATION_EXEC_TIMEOUT` (one run, default 300 seconds), `CURIO_SOLVE_SESSION_DEADLINE` (how long one Solve session keeps managing the dataflow, default 15 minutes, which also caps each node's budget) and `CURIO_SOLVE_BATCH_DEADLINE` (the outer bound on a batch, default 45 minutes). An unusable value falls back to the default.
- **Apply never executes anything** and is never blocked by verification: Apply places the node as proposed, and the card says Solve is what runs it.
- **Background jobs.** A Solve is a detached job on the server, so closing the chat panel or reloading the page does not stop it. The agent's badge shows a running dot while the job is live, and opening the chat re-attaches to its progress. **Stop** ends the session after the current node finishes; a running fetch cannot be aborted. If the server stops mid-Solve, the session is marked interrupted the next time it is read: nodes that finished keep their content, nothing is replayed, and Retry starts a new execution linked to the interrupted one. This is a single-process job owner; a multi-instance deployment would need a durable one.
- **Waves.** A batch runs the plan the way Play would: in topological waves, roots first, each wave's nodes in parallel. A wave's verified content is written at the wave boundary, so the next wave generates and executes against the upstream code that ran, and a downstream correction is told what its upstreams produced (`upstreamOutputs`). An upstream that passed earlier in the batch is not run again: its recorded output stands in, and if that artifact has vanished the slice runs whole once before the result counts. A process that dies between waves keeps every persisted wave, and Retry continues.
- **Executable kinds.** Whether the sandbox can run a node kind is read from its template: a code editor (`hasCode`), a `python` or `javascript` engine, and no `backendHandler`. That covers every built-in Python and JavaScript kind and every package template that declares the same. A template with no code (Vega and Autark specs, merge nodes, data pools, the spatial join) is written and labeled as having no code to run, on the pill, in a review's attempt trail, and on the Node Builder's proposal card. Without a reachable template roster (the end-to-end runner over a raw file), a fallback name table answers instead.
- **Bounds.** The batch deadline is checked at every wave boundary and before every node; what it did not reach stays pending with the reason, the Solve card names it once, and Retry continues from there. A node whose upstream slice exceeds the validation bound (25 nodes) or contains a cycle is skipped with the bound named, and no correction is spent on it. The stale-run marker (15 minutes) is measured from the last completed wave. `verify: false` on the Solve request writes without running, for every kind.

### Connection keys

A key must never be a literal in node code: the code is saved into the dataflow, replayed in every proposal preview, recorded by the runtime journal on every run and exported with the project. A **connection key** is saved once under a name bound to a host, in **API Settings → Connection keys**, through a masked field that never reads the value back, and node code reaches it only as `curio_secret("<name>")`.

- **At run time.** The runtime resolves the names the code uses, for Play and for Solve alike, and hands the values to the sandbox inside the execution request, where they exist only as that callable in the node's namespace: never an environment variable, never a file, never a log line. A key a node prints is redacted before the output leaves the sandbox. The saved dataflow, the journal, the proposals and the chat carry the name only.
- **For agents.** A content builder's grounded inputs list `availableSecrets` with the line to copy and how the API expects the key (`query:<param>`, `header:<Name>`, or in the code). The grounding gate accepts `curio_secret("<name>")` for a saved name (the Source block reads *Connection key · census · api.census.gov*), refuses an unknown name listing the saved ones, and refuses a credential-shaped literal before anything runs. When a saved key is bound to the host a failing request targets, Solve probes that request with the key and tells the correction what the keyed request answered, redacted. When no key exists, the content builder declines in one line and the node's failure ends with **Add key for** and the host, which opens the settings section with the host filled in.
- **Storage.** The store is a 0600 file under the user's own directory (unreadable by isolated node code), written the same way as `llm-configs.json`; it is not encrypted at rest. A published dataflow carries key names, so whoever installs it saves their own key under the same name. The shared guest account (authentication off) shares one key store with every other guest, and the section says so.
- **Typed keys.** The code editor watches for a key typed into a node's code and shows a non-blocking hint naming the line, with **Save as connection key**. Nothing is refused, rewritten or sent: the finding stays in the browser tab.

### Evaluation and training

Every shipped example has a prompt fixture under [`docs/examples/prompts/`](examples/prompts/README.md): a reviewed prompt paired with the example's digest, its declared datasets and packages, its normalized expected graph, node intents, an execution mode, a capability tier and scoring thresholds. During an evaluation the agent receives the prompt and nothing else, never the example JSON, the node ids, the code or the expected graph, which a test enforces.

The run is the ordinary product path: an empty project, the Dataflow Builder attached, one message, the plan's review card, Apply, then Solve. What lands on disk is compared semantically: canonical template ids and their roles, topology with edge kinds and merge slots, the declared dataset and package references, the absence of invented templates, packages, datasets, paths and URLs, node intents, and Solve's own verdicts. Regenerated ids, layout, formatting and behaviourally equivalent code are ignored, and a graph built in a different order scores the same. Three rules hold:

- **No expectation is weakened to pass.** A construct the agent contract cannot express is reported as a named capability gap, and the fixture keeps it.
- **Nothing is gated on a model.** A live-model run writes an evaluation report, opt-in and never in CI.
- **No agent grades an agent.** The comparison is deterministic code; the Generated Content Evaluator is advisory and has no authority here.

**Evaluation mode** creates its own project, installs and attaches the Dataflow Builder through the normal install flow with the agents it requires, sends the prompt through the normal runtime on the configuration the user's Dataflow Builder runs on, applies the plan through the Apply endpoint, and solves; the comparison runs server-side, so the reference never reaches the model. The automated apply is granted only inside the project that run created, only for the plan and the installs the example requires, refused for anything a person should decide, and recorded per apply. A save that would delete a node, a connection or a node's code that the browser never saw is refused and says what would be lost, which protects the graph an evaluation built from a canvas that was open before the run finished. A run is recorded per account under `.curio/users/<key>/agents/evaluation/`, with the fixture, the configuration, provider and model, the prompt and agent digests, the generated project id, the phases, latency, token usage, the comparison and the score, and never a key.

```bash
# the deterministic tiers (offline, no stack, seconds)
pytest utk_curio/backend/tests/test_agents/test_example_fixtures.py \
       utk_curio/backend/tests/test_agents/test_example_reconstruction.py \
       utk_curio/backend/tests/test_agents/test_evaluation_service.py

# what the fixtures say
python -m utk_curio.tools.agent_eval list

# the same evaluation against a remote stack, from a terminal
export CURIO_EVAL_LIVE=1
python -m utk_curio.tools.agent_eval run --token "$CURIO_EVAL_TOKEN" --tier T0
```

The command-line runner writes `.curio/eval/<runId>/report.json` (provider, model, prompt and instruction digests, attempts, latency, token usage, redacted transcripts, the generated dataflow, the diff, the score and its failure categories) and `report.md`, the same as a table. No USD figure is computed unless a rate is supplied: Curio has no price table.

**Model training** asks the endpoint of the configuration it trains on whether it can fine-tune. An Anthropic key (no tuning endpoint), a local Ollama or LM Studio (chat routes only) and a key without the scope to list tuning jobs each get their own sentence; the last one says the endpoint may still support tuning. When the endpoint cannot be asked, its last answer is replayed with the date it was true.

- **What is sent.** Only fixtures on the `train` split that a person approved. Each row is the system turn a real run carries, the fixture's prompt, and the plan block the runtime's own parser accepts; an example whose graph the plan contract cannot express is excluded with that reason. Every row is scrubbed and re-checked, and anything still resembling a credential stops the upload. No dataset row, column, geometry or file is included.
- **Consent.** The user sees the row and byte counts, the examples, their licences and the host. Consent is a tick plus the digest of that exact set, recorded before the first byte leaves; Start sends back the host the user was shown, and a set that would go elsewhere is refused.
- **The job.** The provider owns it: Curio holds its id and asks the endpoint when the panel is open, and every status carries the time it was read. Cancel asks the endpoint and reports its answer. Trained tokens are shown as the provider reported them.
- **Switching on.** A trained model can be used only after an evaluation of that exact model on the held-out examples, whose fixture digests still match the corpus; there are four refusals, each naming what to fix, and no pass mark. Switching adds an LLM configuration with `origin: "trained"` and chooses it for the Dataflow Builder, whose prompts built the training set. The Builder's previous choice is recorded, so going back is one click until that choice is changed by hand.

```bash
export CURIO_EVAL_LIVE=1
python -m utk_curio.tools.agent_eval run \
    --model ft:your-base:curio-plans:abc --gate-for train-20260909T161200Z-a1b2
```

`--model` runs on a temporary copy of the Dataflow Builder's configuration with that model, chosen for the Builder for the run, and puts its choice back afterwards.

---

## Python Dependencies

Curio's Python deps live in two places:

**1. Framework deps** ([`requirements.txt`](../requirements.txt), mirrored in [`pyproject.toml::dependencies`](../pyproject.toml)) carries only what the backend and sandbox Flask apps need at module load (Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-Caching, `requests`, `python-dotenv`, the LLM SDKs, `altair`, `tqdm`, `pygments`) plus test/dev tools. No data-ops libraries.

**2. Per-package deps.** Every node package declares the libraries its templates need in its manifest's `dependencies.python`:

```json
// packages/curio.builtin@1/manifest.json
"dependencies": {
  "python": {
    "pandas": ">=3.0.2", "geopandas": ">=1.1.3", "pyproj": ">=3.7.2",
    "shapely": ">=2.0", "numpy": "", "pyarrow": ">=24.0.0",
    "duckdb": ">=1.5.0", "fiona": ">=1.10.1", "pillow": ">=12.2.0"
  }
}

// packages/curio.streetvision@1/manifest.json
"dependencies": {
  "python": {
    "onnxruntime": ">=1.17"
  }
}
```

Spec syntax accepts PEP 440 comparators (`>=2.0`, `~=4.30`, `==1.5.0`), bare versions (`1.2.3` → treated as `==1.2.3`), npm-style carets (`^0.14` → rewritten to `~=0.14`), and empty string for "latest".

### Install paths

- **At `curio start`**, the launcher ([`main.py::install_manifest_dependencies`](../utk_curio/main.py)) walks every installed manifest (`packages/curio.builtin@*` from the catalog source + every user store under `.curio/users/<u>/packages/`), unions their `dependencies.python` via [`versions.merge_python_deps`](../utk_curio/backend/app/packages/domain/versions.py) (which surfaces range conflicts as warnings instead of silently last-write-wins), and pip-installs the merged map via [`pip_runner.install_python_deps`](../utk_curio/backend/app/packages/infrastructure/pip_runner.py). Already-satisfied deps are skipped via `importlib.metadata.version`, so the steady-state cost is about a second with no network.

- **At catalog install time** (`/api/packages/projects/<id>/install`), when the user installs a package from the drawer, [`store_install._ensure_user_store_install`](../utk_curio/backend/app/packages/application/store_install.py) copies the files, then calls `pip_runner.install_python_deps` on the freshly-installed manifest. The Install button stays busy until pip finishes; heavy installs (`torch`, ~3 GB) can take minutes.

- **At catalog uninstall time**, `prune_unreferenced_packages` walks every other still-installed package's manifest, finds the deps the pruned package declared that no other surviving package still requires, and pip-uninstalls only those (ref-counted shared deps survive).

### Framework requirements and standalone libraries

The framework needs to boot before any manifests can be walked, so `pip install -r requirements.txt` (or `pip install utk-curio`) seeds enough of an env that the launcher can read `manifest.dependencies.python` and continue. A package's heavy libraries are not in the framework requirements: they install when the user clicks Install in the catalog, and a Transformers model's `torch` installs when the model is added to the Model Catalog.

Standalone libraries the user adds via the [Installed Libraries modal](EXTENDING.md) (canvas → Data → Installed libraries) sit in a third bucket, per-user JSON at `.curio/users/<u>/installed-libraries.json`, and pip-install through the same `pip_runner`, with ref-counted uninstall against every installed package's manifest.

The same route is reachable without opening that modal: when a node run ends in `ModuleNotFoundError`, `/processPythonCode` carries a `missingModule` field naming the import and the distribution that provides it (`packages/missing_import.py`, sharing `dependency_scanner`'s alias table and passing `pip_runner.validate_python_requirement` before it is offered), and the node's output panel renders an **Install** button beside the traceback.

---

## Discovery Catalog

The user-facing model is in [DISCOVERY-CATALOG.md](DISCOVERY-CATALOG.md) and the routes are in [Discovery Catalog Routes](#discovery-catalog-routes). The backend is `backend/app/discovery/`: `domain/` (manifest, parameters, source ids, formats, path templates), `application/` (catalog, browse, acquire, jobs, places, for storage sources scan, storage acquire, combine, index, cache and media, and service acquire), `infrastructure/` (credentials, rate limits, storage, transport, media directories) and `providers/` (one module per portal software, one per storage type, and one per service). Every outbound request from Python passes the egress policy described in [DEPLOYMENT.md § Outbound requests](DEPLOYMENT.md#outbound-requests); an OpenStreetMap download's requests leave from autk-db in Node ([Services](#services)).

### Sources and manifests

A source describes one portal or one storage source in `discovery/<sourceId>@<major>/manifest.json`, under `CURIO_DISCOVERY_ROOT` when that is set. `infrastructure/storage.py` also reads an instance root, `.curio/discovery/` (`instance_root()`), for an operator's own sources: shipped sources are listed first, and an instance source whose id a shipped one uses is skipped with a log line. Only a shipped `folder` source may give a relative `root`, resolved against the repository. `.curio/discovery` is in `hardening.SENSITIVE_PATHS`, so a node running as `curio-exec` cannot add a folder for the backend to serve. Neither root is created eagerly. [`domain/manifest.py`](../utk_curio/backend/app/discovery/domain/manifest.py) validates a manifest, [`docs/schemas/discovery-source.v1.json`](schemas/discovery-source.v1.json) publishes the same contract, and `tests/test_discovery/test_schema_matches_validator.py` derives its assertions from the validator, so the two cannot drift.

- **Ids** (`domain/source_id.py`) are three to six dot-separated lowercase segments, the first always `source`. They name the publisher, never the software: `provider.type` can change when a portal migrates, and an id cannot.
- **`provider.type`** is one of `PROVIDER_TYPES`: the `PORTAL_PROVIDER_TYPES`, which must equal the keys of `PROVIDERS` in `providers/__init__.py`, the `STORAGE_PROVIDER_TYPES` (`folder`, `s3`, `huggingface`), which must equal the keys of `STORAGE_PROVIDERS`, the `SERVICE_PROVIDER_TYPES` (`autark-osm`, `mapillary`, `google-streetview`), which must equal the keys of `SERVICE_PROVIDERS`, and the `MODEL_PROVIDER_TYPES` (`huggingface-models`), which must equal the keys of `MODEL_PROVIDERS`. Asserts check all four at import time, and that each provider module's `PARAMETER_IDS` agrees with `PROVIDER_PARAMETER_IDS`, the ids a manifest may declare for it.
- **Parameters** ([`domain/parameters.py`](../utk_curio/backend/app/discovery/domain/parameters.py)) are what a download asks: `parse_parameters` reads a source's and a resource's lists, `merge` lets a resource's entry replace the source's by `id`, `validate_values` checks a request's answers on the server (unknown ids, ranges, a box against `maxAreaKm2`, a name holding a quote, bracket, backslash or line break), and `values_hash` keys them, ignoring a box's label. A manifest may declare only the ids its provider reads (`PROVIDER_PARAMETER_IDS`) and only the area forms it can send (`PROVIDER_AREA_FORMS`), and `providers/__init__.py` asserts each module's `PARAMETER_IDS` agrees.
- **Resources** (`_parse_resources`) are a storage or service source's declared contents, at most `MAX_RESOURCES` (64). A service resource (`_parse_service_resource`) has no `path`: it names its `kind`, its `format`, and what to ask for in `options`, `layers` for `autark-osm`. Each `path` compiles through [`domain/templates.py`](../utk_curio/backend/app/discovery/domain/templates.py) into a regex with typed captures (`str`, `int`, ISO `date`, or a strftime `datetime`) and a literal prefix, which a bucket lists under. A capture may not take a name a collection index uses for its own columns (`RESERVED_NAMES`), or `source_file` for a table. A storage source's `capabilities.formats` is derived from its resources, and a manifest that declares it is refused.
- **Formats.** `capabilities.formats` is an upper bound, intersected at download time with `DISCOVERY_ACQUIRABLE_FORMATS` (`csv`, `geojson`, `json`, `parquet`, `geotiff`). That set is narrower than the Data Catalog's: a `shp` needs sibling files a single download cannot bring, and a `bundle` is a node output.
- **Size.** `capabilities.maxDownloadBytes` may lower the 64 MiB ceiling (`DEFAULT_MAX_DOWNLOAD_BYTES`), never raise it.
- **`provider.options`** is provider wiring and is never sent to a client.
- **`auth.secretId`** must name a slot in `SLOT_COLUMNS` (see [Credentials](#credentials)), or the manifest fails to load.
- **Icons** are PNG only and resolved inside the source's own folder. An SVG served from the app's own origin can carry script.

Sources have no import route. A manifest names a host the server calls on a user's behalf, with a credential attached, or a folder it reads, so sources ship with the deployment or are written by the operator.

### Search

[`application/browse.py`](../utk_curio/backend/app/discovery/application/browse.py) runs a federated search as one request per searchable source, at most `MAX_FANOUT_WORKERS` (4) at a time.

- Each portal leg takes its own source's rate limit (`limits.requestsPerMinute`, default 30, per user and per portal, in process), so a fan-out cannot multiply one user's rate against a portal. A storage leg answers from its listing and spends none.
- Each leg reports a status from `LEG_STATUSES`: `ok`, `failed`, `refused`, `rate-limited`, `unsupported`, `needs-token`, or `scanning` for a storage source on its first scan. The response is a 200 either way. The page names the portals that did not answer, names the storage sources still being scanned on a line of their own and asks again until they answer, and ignores `unsupported`, which a link-only source reports on every search.
- Rows are interleaved round-robin across portals and storage sources. Only the single-source search paginates.
- The page debounces the search box and aborts the request in flight on every keystroke.

The roster is read from disk on every request, and search results are never cached. The one cache on the search path is a WFS server's capabilities document (`providers/wfs.py`, `CAPABILITIES_TTL_S`, 15 minutes per source), which lists layers rather than answering a query.

### Downloads

[`application/acquire.py`](../utk_curio/backend/app/discovery/application/acquire.py) fetches the bytes server-side and hands them to the Data Catalog's own importer, so the result is an ordinary `imported.x<uuid>` dataset.

- **Jobs** ([`application/jobs.py`](../utk_curio/backend/app/discovery/application/jobs.py)) are per account, process-local (a restart loses them), and swept `TTL_SECONDS` (15 minutes) after they finish. A job id owned by another account reads as unknown. Cancel is checked between chunks.
- **Concurrency.** `MAX_CONCURRENT_DOWNLOADS` (2) per account, in `infrastructure/ratelimit.py`, shared by downloads, storage adds and **Cache files**. A job's worker is built inside its `try`, so a worker that cannot start still ends its job and gives its slot back.
- **Provenance and idempotency.** A download writes a `discoverySource` block (`sourceId`, `sourceName`, `resourceId`, `resourceUrl`, `finalUrl`, `fetchedAt`, `contentSha256`, and for a narrowed download `parameters` and `parametersHash`) on the dataset manifest, and `dataset_index_entry` mirrors it: a manifest field missing from the index vanishes from every listing. A request for a `(sourceId, resourceId, format, parametersHash)` already held answers 200 with that dataset and contacts no portal. Search rows carry `heldFormats`, the whole (not narrowed) datasets held by format, and `alreadyHeldDatasetId`, from one `UserDatasetRepository.discovery_resource_formats()` walk per page. A file imported by hand from a Dataset Finder row writes a `discoverySource` too, with `manual: true`, its link as `resourceUrl`, `fetchedAt` and `contentSha256`; a download and a hand import of the same bytes are one dataset, whichever arrived first.
- **`refresh: true`** fetches anyway. Identical bytes (by hash) mint nothing; different bytes mint a new dataset and leave the old one alone, since a saved dataflow loads a dataset by id. A storage row compares its listing's fingerprint first (each file's path, size, time and tag, and a shapefile's parts), which `discoverySource.fingerprint` or the `collection` block records, and a single file then its content sha. When a row is held twice, the lookups take the latest `fetchedAt`.
- **Format detection** (`domain/formats.py`), most trusted first: the format the provider put in the URL; the final URL's suffix after redirects; the `Content-Disposition` filename; the `Content-Type`; the first bytes (`PAR1` for Parquet, the TIFF magic, and a JSON probe that tells GeoJSON from JSON by looking for a geometry type). The result is checked against the source's formats, and anything unidentified is an error.
- **Bounds.** A `Content-Length` over the bound is refused before any body byte is read, and the stream is capped again while writing. Archives are refused by content type and by suffix (`ARCHIVE_CONTENT_TYPES`, `ARCHIVE_SUFFIXES` in [`domain/formats.py`](../utk_curio/backend/app/discovery/domain/formats.py)); nothing is unpacked. The Dataset Finder reads the same list, so it offers an archive as a manual download, never as data.
- **Files.** Bytes are staged under the user's `.curio/users/<id>/` tree. Remote filenames are sanitised, and the importer mints the dataset directory name, so no remote input reaches the filesystem path.
- **Errors** carry the server's reason ("that resource is a application/zip archive"), which the page shows as is.

### Storage sources

A storage source is read through a `StorageProvider` ([`providers/storage_base.py`](../utk_curio/backend/app/discovery/providers/storage_base.py)): `scan(prefix)` yields a `FileEntry` (relpath, size, mtime, etag) per file, `open(relpath, byte_range=None)` returns one (a bucket's is read into memory, up to the download ceiling, and `stream()` writes one to a sink as it arrives), and `local_path(relpath)` is its path when it is on this machine. Hidden and system files are never yielded, and every relpath passes `validate_relpath` before it is used.

- **`folder`** resolves its root once and checks `is_within` on every real path, so a symlink out of the root is skipped. It never writes. `audit_folder_roots()` runs at boot and logs each folder root `curio-exec` cannot read, with the folder or file that stops it (`unreadable_part`), from the root and a sample of its files.
- **`s3`** lists with ListObjectsV2 under the resources' common prefix, parsing the XML with the standard library within the metadata cap, and follows continuation tokens. It reads objects with plain GETs, and a `Range` header for probes. Public buckets only.
- **`huggingface`** lists a dataset repository with its tree API and reads through `resolve/`. The listing gives no file times, so a file's `oid` is what tells a change. It follows the `Link` pagination header only when it points at `baseUrl`. The `huggingface.token` credential is sent with `auth.valuePrefix` (`Bearer `).

**Listing.** [`application/scan.py`](../utk_curio/backend/app/discovery/application/scan.py) walks a source once, matches each file against every resource's template, and groups the matches into rows: a resource, one value of `per:<field>`, or one file for `per-file`. Files a metadata template names are attached, and the rest are counted as unmatched. The summary lives in `ListingCache` (`listings`), one per source shared by every user, or one per user for a source that sends a token. A request waits up to `LISTING_WAIT_SECONDS` (2) for a scan it starts, and otherwise answers with a `scanning` leg; the federated search does not wait. A summary older than `SUMMARY_TTL_SECONDS` (15 minutes) is rescanned in the background while the last one is served, and `?rescan=1` rescans at once. A walk stops at `limits.maxFiles` matched files and marks the summary truncated. For a shapefile resource the walk keeps the sidecars, so each `.shp` carries its parts, found in any letter case. The cache keeps each row's matched files, which the Files list pages through and the row thumbnails are drawn from by position, so no path ever comes from a client.

**Resource ids.** A row's id is `<resource>`, `<resource>@<field>=<value>[;...]` for a split row (a `;` or `%` in a value is written `%3B` or `%25`), or `<resource>/<relpath>` for one file. The routes take a storage id as the client sent it; a portal id is decoded once more. `parse_resource_id` turns it back into a `Selection`, and `narrow()` adds the acquire body's `filters` (values, or `{min, max}` typed like the capture) and `files` (relpaths, validated). A narrowed add skips the held lookup and writes `discoverySource.narrowed`, which `find_by_discovery_resource` and `discovery_resource_index` ignore.

**Adding.** [`application/storage_acquire.py`](../utk_curio/backend/app/discovery/application/storage_acquire.py) scans the one resource again and adds what it finds. A scan that stops at `limits.maxFiles` refuses the add rather than adding part of it.

- **One table file** streams into staging, capped at 4 GiB from a folder and at the download ceiling from a bucket, and goes through `install_imported_path()` ([`datasets/install/installer.py`](../utk_curio/backend/app/datasets/install/installer.py)), which moves it into the dataset folder with `os.replace` and transcodes text to UTF-8 as a stream (`transcode_file_to_utf8`). Portal downloads install through the same seam. A shapefile's parts are staged beside it as `data.*`, their sha taken together, and the whole converts to GeoParquet; a GeoPackage or PBF goes through the multi-layer importer. A CSV declared with `options` goes through the combine path, to be read with them.
- **Several table files** go through [`application/combine_tables.py`](../utk_curio/backend/app/discovery/application/combine_tables.py): DuckDB reads them with `union_by_name`, numbers each file's rows as they are scanned, joins the captured fields and `source_file`, and writes Parquet ordered by file and row. The file name and row number are named `__curio_file` and `__curio_row` while they are needed. A capture, or `source_file`, whose name a file's column already uses, compared without case, gets a `_from_path` suffix. Geographic formats combine with GeoPandas into GeoParquet in EPSG:4326, refusing files whose CRS differ. Bounds: `MAX_COMBINED_FILES` (10,000) and 16 GiB local or 2 GiB remote.
- **A collection** goes through [`application/index_collection.py`](../utk_curio/backend/app/discovery/application/index_collection.py): a pool of four probes each file with Pillow (size, EXIF time, GPS IFD), PyAV (video and audio streams, BWF origination time) or rasterio (CRS, transform, footprint in EPSG:4326). A remote image or raster is probed from one 64 KiB `Range` read; a remote video or recording is not read. Frames are ordered by sequence and frame and get `t_s`, the frame number over `fps`; a `time` capture fills `taken_at` or `recorded_at`; and `metadata` joins a CSV, Parquet or JSON table, from the folder or the bucket, by `file_name`, `frame` or a capture. A file that fails to probe keeps its row, with `probe_error`. The index is written as `data/index.parquet`, GeoParquet when rows have positions, and installed as format `collection` with the `collection` block, which `dataset_index_entry.collection_json` mirrors.

`av` and `rasterio` are declared in `curio.builtin@1`, because the backend probes and draws thumbnails and, under fork isolation, a user's package overlay is not importable by the backend.

**Caching a bucket's files.** [`application/cache_collection.py`](../utk_curio/backend/app/discovery/application/cache_collection.py) streams a bucket collection's objects to `media_work_root(user)/objects/<datasetId>/`, as a job, capped at 4 GiB per object and at `CURIO_MEDIA_CACHE_MAX_GB` (default 20) per account, checked before any byte is fetched.

### Services

A service is told where and what, and answers with one download. Its rows are its manifest's resources, with no network ([`providers/autark_osm.py`](../utk_curio/backend/app/discovery/providers/autark_osm.py) `rows()`), so they join a federated search the way storage rows do.

- **OpenStreetMap** (`autark-osm`) runs [`providers/autark_osm.mjs`](../utk_curio/backend/app/discovery/providers/autark_osm.mjs) as `node`, from the backend's process tree, with the request on stdin. The script imports the repo-root autk-db (resolved by [`sandbox/util/node_runtime.py`](../utk_curio/sandbox/util/node_runtime.py), which the sandbox's JS nodes use too) and calls `db.loadOsm` with the area as `{geocodeArea, areas}` or `{bbox}` and the resource's layers. A tag resource (`options.tags`, or a `tags` parameter) sends no layers and one autk-db tag set named `tags` instead, its entries checked again by `parameters.parse_tag_entry` before Node starts; autk-db loads its `points`, `polylines` and `polygons`, written as `tags_<geometry>.geojson`. autk-db's progress phases come back as stage lines, and each layer as autk-db's `getLayer(name, { osmElements: true })` GeoJSON, in its workspace CRS (EPSG:3395): one feature per node, way or relation, with `osm_type`, `osm_id` and, for buildings, `building_id`. Surface polygons carry none of them.
- **Ceilings.** `MAX_SECONDS` (15 minutes) and `MAX_OUTPUT_BYTES` (512 MiB), each refused with a message naming it. The child runs in its own process group, so Cancel and the time limit kill everything it started.
- **Into the Data Catalog.** [`application/service_acquire.py`](../utk_curio/backend/app/discovery/application/service_acquire.py) moves every position to WGS84 with pyproj (`to_wgs84`), keeping each feature's geometry type and properties; [`domain/osm_values.py`](../utk_curio/backend/app/discovery/domain/osm_values.py) (`with_numbers`) writes the tags it lists as numbers in metres, km/h or counts, and a value it cannot read as one number as null. `service_acquire.py` then installs each non-empty layer as GeoJSON through `_install_imported_bytes`: one layer as an ordinary dataset, several under one `osm.x<hex>` group, the group a `.pbf` upload forms. The title names the area (`place_label`). A download counts once against the source's rate limit.
- **Its requests** go from Node to autk-db's fixed Overpass endpoint with `OVERPASS_USER_AGENT`, not through the Python transport. Under `CURIO_DISCOVERY_FIXTURES`, behind the same gate as the transport (`fixture_root()`), the script's `fetch` answers from `tests/test_discovery/fixtures/overpass/` and skips autk-db's pauses. A request is looked up first among the recorded answers, keyed by method, URL and a hash of the body (the script's `record` mode files live answers there), then among the mock answers in `mock.json`, which answer a query by texts it contains. `tests/test_discovery/overpass_mock.py` writes `mock.json`.
- **Mapillary** (`mapillary`) and **Google Street View** (`google-streetview`) are asked over HTTP, so `build_service` hands them the catalog's transport. Each answers an `ImageSet` of files it downloaded into a work folder; `service_acquire` indexes them with the storage collections' own `build_rows`, `write_index` and `collection_block`, writes the collection, and moves the files by rename into `media_work_root(user)/objects/<datasetId>/<file_id>.<ext>`, where `curio_collection` reads a downloaded collection's files (and `grant_to_child` opens each to the isolated child).
- **Mapillary** tiles the box under 0.0099 square degrees, the API's limit, splits a tile that answers its 2000 maximum in four (at most three times), takes images from every tile in turn, newest first, and looks thumbnails up afterwards by `image_ids`, fifty at a time, since a search that names them answers over the metadata ceiling. Thumbnails are fetched only from `options.imageHosts`, matched by host suffix after the address policy.
- **Google Street View** asks the metadata endpoint at points of a grid with the answer's `spacing`, in a fixed shuffled order, keeps each panorama once, stops when it has enough, asks at most `MAX_POINTS`, then downloads one image per panorama and heading and drops Google's grey placeholder.
- **A service that needs a token** is refused with 428 before any job when none is set, naming the slot and its help link, as a portal search is.

### Models from the Discovery Catalog

The model family (`huggingface-models`) is searched like a portal and added like a storage row, but lands in the [Model Catalog](#model-catalog).

- **Search** ([`providers/huggingface_models.py`](../utk_curio/backend/app/discovery/providers/huggingface_models.py)) asks `/api/models?pipeline_tag=<options.pipelineTag>` and keeps repos tagged `onnx` or `safetensors`; a next page is the `Link: rel="next"` cursor.
- **`plan(repo)`** reads `/api/models/<repo>?blobs=true` and pins the commit it names. An ONNX export fetches its graph (`model.onnx` first), the external data it names and the two configs; a `...ForSemanticSegmentation` checkpoint fetches its configs and safetensors shards. Pickle-only weights, other architectures, no labels and more than `MAX_MODEL_BYTES` (2 GiB) are refused with `CapabilityUnsupported` or `DownloadTooLarge`.
- **Adding** ([`application/model_acquire.py`](../utk_curio/backend/app/discovery/application/model_acquire.py)) checks `install_refusal()` first when the runtime needs libraries (`RUNTIME_DEPS`), streams each file from `/<repo>/resolve/<commit>/<path>` through the transport, writes the manifest (`labels_of` from `config.json`, `onnx_input` from `preprocessor_config.json`), and calls `install_downloaded`, then `install_dependencies`. A job's `model` and `dependencies` say what landed; its `dataset` is null. `already_held` finds a model added before from the same source and repo, so the same add again fetches nothing.
- A 401 or 403 from the Hub is `CredentialRequired`, so a gated model asks for the Hugging Face token like any source.

### Place search

[`application/places.py`](../utk_curio/backend/app/discovery/application/places.py) answers the area field's place search, `GET /api/discovery/places?q=`, from Nominatim through the catalog's transport: one request a second for the whole process (`MIN_INTERVAL_S`), an in-memory cache of a day (`CACHE_TTL_S`), and a User-Agent naming Curio. Each place has its name, its label, its box, and whether it is an administrative boundary, which the named-areas field offers.

### Collection media

[`infrastructure/media_dirs.py`](../utk_curio/backend/app/discovery/infrastructure/media_dirs.py) names the directories: `media_cache_dir` (`.curio/users/<key>/media-cache/<datasetId>/`, thumbnails the backend draws) and `media_work_root`, which the backend and a node both use: `.curio/users/<key>/media/` with isolation off, and `.curio/exec-scratch/users/<key>/media/` under fork isolation, where `curio-exec` can write. `forget_media` removes a dataset's thumbnails, cached objects and derived frames and clips when the dataset is deleted; the source's files are never touched.

[`application/media.py`](../utk_curio/backend/app/discovery/application/media.py) and [`media_routes.py`](../utk_curio/backend/app/discovery/media_routes.py) serve a collection's files by id:

- **Lookup.** `locate()` resolves `<file_id>` through the index (cached per index file and mtime), or `<file_id>@<t_ms>` to a frame or clip `curio_derived_file` wrote, and never takes a path from the request.
- **Serving.** `original` sniffs the first bytes against `BROWSER_TYPES` (images, video and audio a browser plays) and serves that mimetype with `nosniff`, `Content-Disposition: inline`, and Range. SVG and HTML are never served.
- **Thumbnails.** Pillow for images and frames, rasterio with a 2 to 98 percentile stretch for rasters, a PyAV poster frame for video, and a numpy STFT spectrogram for audio, cached as JPEG and keyed on the file's size and mtime. A bucket's image or raster up to 64 MiB is fetched to draw one; anything else is drawn once cached. A storage row's thumbnails are drawn the same way into a per-source cache under `.curio/discovery-cache/`, or into the account's own media cache for a source that sends a token.
- **Signed links.** `<video>` and `<audio>` cannot send the bearer token, so `POST .../link` signs `{user, key, dataset, file}` with itsdangerous under a key kept in `.curio/media-link.key`, valid `LINK_TTL_SECONDS` (10 minutes), and `GET /api/media/<token>` serves that one file.

### Collections in node code

`curio_collection`, `curio_derived_file` and `curio_output_file` come from one function, `make_collection_helpers` ([`sandbox/util/collections.py`](../utk_curio/sandbox/util/collections.py)), injected in process and in the isolated child, so the two paths cannot disagree.

- **Resolution.** `code_refs.py` finds `curio_collection("<id>")` calls with `curio_dataset_path` ones, within the same 32-id cap, so the index resolves and stages like any dataset file. `_resolve_exec_collections` in `api/routes.py` adds, per collection, the folder root or the bucket cache directory, and sends `media_dir` to every node, since a node downstream of the loader writes the frames without naming the collection.
- **Rows.** `curio_collection` adds `dataset_id`, `path` (the file, the cached copy, or `None`; the column `curio_segment` reads), `thumbnail` and `image_url` (the columns Simple View shows) and `audio_url`.
- **Derived files.** `curio_derived_file` names `<media_dir>/<frames|clips|overlays>/<datasetId>/<fileId>/<t_ms>.<ext>` and the row the media route serves it back under, `<fileId>@<t_ms>`. `curio_segment` ([`sandbox/util/vision.py`](../utk_curio/sandbox/util/vision.py)) writes each image's overlay this way (kind `image`, `t_ms` 0). `curio_output_file` names a file a node returns, in the run's scratch directory under isolation, because a RASTER output must be flat-named there.

`curio.media@1` is three Python code templates over these helpers: Sample Video Frames, Split Audio and Mosaic Rasters, which writes a VRT from the index's transform columns.

### Credentials

[`infrastructure/credentials.py`](../utk_curio/backend/app/discovery/infrastructure/credentials.py) owns the registry of credential slots, `SLOTS`, one `KeySlot` per slot: the column on the `user` row, a label, a help link, a placeholder, an optional note, a deployment-wide fallback, and the other features that read the column. The slots are `socrata.app-token`, `huggingface.token` (the `huggingface_token` column, which the Hugging Face sources send), `google.maps-key` and `mapillary.token`. `SLOT_COLUMNS` and `SLOT_DEFAULTS` derive from it, and `GET /api/discovery/keys` lists every slot for API Settings, which draws one row each. Adding a slot is a column, a migration, a field in `PATCH /api/auth/me`, one entry there, and its id in `KNOWN_SECRET_SLOTS` in `domain/manifest.py`.

- A key is saved through `PATCH /api/auth/me` and read back only as a boolean. A guest on a `--deploy` instance is refused with a 403.
- `CURIO_DEFAULT_SOCRATA_APP_TOKEN` is inherited by every account that has not saved its own.
- `auth.scheme` is `header` or `query` (`AUTH_SCHEMES`); Google Street View sends its key as `?key=`. The transport adds a query key to the request it sends and nothing else, and takes it out of every URL and message it hands back (`_keyed`, `_redact`), so egress audit records, refusal messages and job records stay safe to store verbatim. The transport binds the credential when it is built, and `CredentialedTransport` sends it only to the source's own host, so no provider ever handles a token.

### Providers

A provider is one module in [`providers/`](../utk_curio/backend/app/discovery/providers/) implementing `DiscoveryProvider` (`providers/base.py`): `search`, `describe` and `download_url`. To add one:

1. Write the module, subclassing `BaseProvider`.
2. Add its type to `PROVIDER_TYPES` (`domain/manifest.py`), to `PROVIDERS` (`providers/__init__.py`), and to the schema's `provider.type` enum.
3. Export a transport-free `recognize(url)` and `metadata_evidence(payload)`, and add the module to `RECOGNISERS`. `agents/verify.py` uses them to refine an agent's external-source check, so a provider's URL knowledge lives in one place.

Every provider keeps two invariants:

1. A `resourceId` is validated against the provider's own pattern **before** it goes into any URL. Ids arrive from search results, saved agent proposals and typed URLs, so none is trusted.
2. Every URL a provider builds starts with the manifest's `baseUrl` (`assert_on_base`). Redirects off the base are allowed and each hop is re-checked; it is construction that is pinned. The `direct` provider has no base and relies on the egress check alone.

### Tests

Providers take their transport as a required constructor argument, so a missing fake is a `TypeError` rather than a request, and the suite-wide guard in [CONTRIBUTING.md § Tests do not reach the network](CONTRIBUTING.md#tests-do-not-reach-the-network) catches anything else.

- `tests/test_discovery/fixtures/` is a corpus recorded from the live portals by `scripts/record_discovery_fixtures.py`. Socrata, CKAN and ArcGIS put the page size in the URL and the corpus is keyed on the exact URL, so the recorder searches with the app's `DEFAULT_SEARCH_LIMIT`.
- `test_provider_contracts.py` (`@pytest.mark.contract`) hits the real portals in CI, asserts only the response shape, and skips on any unreachable, non-2xx or non-JSON answer.
- The Playwright specs drive the real backend against the corpus through `CURIO_DISCOVERY_FIXTURES`, which `docker-compose.ci.yml` and `docker-compose.ci-isolated.yml` set for the container.
- OpenStreetMap downloads run autk-db in Node with its Overpass requests answered from `fixtures/overpass/`: made-up answers for Golf, Illinois, by name (`overpass_mock.py`), and answers recorded for a box in Golf and a box across Chicago's Loop, gzipped.
- Mapillary's answers (`fixtures/mapillary/`) are recorded with the auth header stripped, every image indexed to a synthetic file. Google Street View's (`fixtures/google-streetview/`) are written, not recorded, from the formats Google documents, by `scripts/write_streetview_fixtures.py` driving the real provider. Hugging Face models' (`fixtures/huggingface-models/`) are the Hub's real answers, every weights file indexed to a synthetic graph or file of the same shape. `test_provider_contracts.py` checks Mapillary and Google live only when `CURIO_MAPILLARY_TOKEN` or `CURIO_GOOGLE_MAPS_KEY` is set.
- Storage sources are tested on folders built in `tmp_path` and on `source.curio.example-storage@1`, whose files `scripts/build_example_storage.py` generates. That script also adds the resources the storage examples read to `datasets/data.curio.storage-*@1` through `StorageAcquire`, with file times pinned so the output is the same on every run. Buckets and Hugging Face run on the recorded corpus, whose `Range` entries are keyed `"<url> bytes=0-65535"`; the recorder stores synthetic heads rather than third-party imagery.

### Agent tools

The Dataset Finder reaches the catalog through three contracts in `agents/tools.py`:

| Tool | Effect | What it does |
|---|---|---|
| `discovery.sources` | read | The roster, from disk. Costs no web budget. |
| `discovery.search` | read | Live search. The per-run web budget is charged per portal contacted, so a fan-out over five sources costs five. |
| `discovery.acquire` | mutate | Proposes a download. It goes through the review path, and the read executor has no branch for it, so the model loop cannot run it. The proposal card is grounded in a real `describe()` call. |

Storage and service sources are left out of all three: their rows are added through the Discovery Catalog page, where a storage row can be narrowed and a service's area is set.

A candidate row's `acquirable` flag is set server-side only, by `services.py::_mint_row_acquirable`, and a value the model supplies is stripped first. A storage or service source is never acquirable (`_acquirable`). A connector source must be in the roster and offer downloads; a Direct URL row must be an https link the probe read as a format the source stores, with the link itself as its `resourceId`. A row that names only an https link is tried as a Direct URL row: the server adds the coordinate and keeps it only when the row qualifies, so a plain link to a file is downloaded rather than handed to Node Builder. The rule reads the roster and the probe, never the run's grants: confirming a downloadable row on the card downloads it with the user's own sign-in, and an agent's `discovery.acquire` proposal is checked against its grant where it is minted. The card's **Download** and an approved `discovery.acquire` proposal start the same download job as the catalog page, so a resource shows one download wherever it was started.

---

## Model Catalog

The user-facing model is in [MODEL-CATALOG.md](MODEL-CATALOG.md) and the routes are in [Model Catalog Routes](#model-catalog-routes). The backend is `backend/app/model_catalog/`: `domain/manifest.py` (the manifest and its checks), `infrastructure/storage.py` (where models live), `service.py` (listing, details, install, delete, execution resolution) and `routes.py`.

- **Storage.** `models_root()` is `<repo>/models`, or `CURIO_MODELS_ROOT`; `user_models_dir(user_key)` is `.curio/users/<key>/models/`. A model is a folder named `<id>@<major>` with a `manifest.json`. There is no index table: a listing reads the folders, the account's then the shipped ones, and an account holds few models.
- **The manifest** (`parse_manifest`) takes `runtime` (`onnx` or `transformers`), `task` (`semantic-segmentation`), an `entry` inside the folder (a `.onnx` file for `onnx`), up to `MAX_LABELS` labels, and for `onnx` an `input` (size 8 to 8192, `uint8` or `float32`, `NCHW`, `scale`, three-number `mean` and `std`). A folder whose manifest fails is not listed, and the server's log names it and why.
- **Install.** `install_downloaded(folder, manifest)` mints `imported.x<hex>@1`, moves the folder to a `.part` folder beside its place in the account's store, writes the manifest, and renames it in with `os.replace`, so a half-written model is never listed. `install_dependencies(id)` installs a Transformers model's `python_deps` through `provision_declared_deps`, the path a package's `dependencies.python` takes: the shared interpreter, or the account's node libraries under isolation. `install_refusal()` is the package rule (`package_install_refusal`).
- **Delete** removes the folder. A shipped model is refused with 403. Nodes that name it fail on their next run.
- **In node code.** `code_refs` finds `curio_model("<id>")` calls; `resolve_exec_models` maps each id the code names to its folder, and `/processPythonCode` sends that map with the dataset paths. `curio_model` ([`sandbox/util/models.py`](../utk_curio/sandbox/util/models.py)) returns the folder, or raises a message saying to add the model. Under fork isolation, `stage_model_dirs` ([`sandbox/util/staging.py`](../utk_curio/sandbox/util/staging.py)) hardlinks each model's tree into the run's scratch as `model_<i>/`, keeping relative paths, so an ONNX graph finds its external `.data` and a checkpoint its configs; `models/` is in the hardening allowlists beside `datasets/`.
- **`curio_segment`** ([`sandbox/util/vision.py`](../utk_curio/sandbox/util/vision.py)) runs a model over a collection's rows: `_OnnxRunner` with onnxruntime on the CPU (the manifest's `input` says how to scale, normalize and resize), or `_TransformersRunner` with `AutoModelForSemanticSegmentation` (`local_files_only`, safetensors only). Shares are of all the pixels; the overlay goes through `curio_derived_file` with the `image` kind, so the media route serves it at `<file_id>@0`.
- **Agents** never see models: no tool lists or proposes one, as storage sources are kept out of the agents' tools.

Models come from the Discovery Catalog's model family ([Models from the Discovery Catalog](#models-from-the-discovery-catalog)), or ship in `models/`.

---

## Backend API Reference

The backend is a Flask application in `utk_curio/backend/`. Routes are split across blueprints per domain: sandbox proxies plus the spatial-join handler in `backend/app/api/routes.py`, node packages in `backend/app/packages/routes/` (one module per resource behind one `_map_package_errors`, memo dev/143), datasets in `backend/app/datasets/routes.py`, Discovery Catalog in `backend/app/discovery/routes.py`, agents in `backend/app/agents/routes/` (one module per resource under one blueprint, memo dev/142), projects in `backend/app/projects/routes.py`, and auth in `backend/app/users/routes.py`.

### Core Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/live` | GET | Health check (the container healthcheck uses `/health` on `server.py`) |
| `/version` | GET | Installed `utk_curio` version, as JSON |
| `/processPythonCode` | POST | Execute Python node code (proxies to sandbox `/exec`) |
| `/processJavaScriptCode` | POST | Execute JS node code via Node.js subprocess (proxies to sandbox `/execJs`) |
| `/get` | GET | Download an artifact by id (Arrow IPC when the client asks for it). A name the session-tagged store cannot serve falls back to the shared data directory, where a project load hydrates that project's saved outputs, so they are readable by anyone who can load the project |
| `/get-preview` | GET | First N rows + metadata of an artifact, for DataPool display |
| `/file/<path>` | GET | Serve a file relative to `CURIO_LAUNCH_CWD` so browser-side nodes can fetch binary assets (PBF, GeoTIFF) by the same relative path Python nodes use. Unauthenticated, so it refuses hidden paths and Curio's own state: the instance folder, the `.curio` state root, the shared data directory, the dataset hub and the SQLite database |
| `/starters` | GET | Per-template starter source bodies from every installed package |
| `/spatial_join` | POST | Spatial join of two GeoJSON inputs (see `common/spatial.py`) |

File ingestion is **not** here - it lives in the datasets blueprint as `POST /api/datasets/import`.

### Package Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/packages` | GET | List the user's installed packages |
| `/api/packages/catalog` | GET | List packages available in the catalog source |
| `/api/packages/projects/<id>` | GET | Read a project's per-project lockfile |
| `/api/packages/projects/<id>/install` | POST | Install a package into a project (copies files, pip-installs `manifest.dependencies.python`) |
| `/api/packages/projects/<id>/<dirName>` | DELETE | Uninstall a package from a project (ref-counted prune + pip uninstall of unique deps) |
| `/api/packages/<dirName>/file/<path>` | GET | Serve a static file from the user's installed copy (behavior bundles, icons, …) |
| `/api/packages/defaults` | GET/POST | Per-user "always installed" set (drives the catalog page's Installed badge) |
| `/api/packages/libraries` | GET/POST/DELETE | Per-user "Installed libraries" surface: list, add, or remove standalone pip libs alongside manifest-derived ones |

### The dataset index

`backend/app/datasets/repositories/index.py` serves catalog listings from keyed
lookups against `DatasetIndexEntry` (`backend/app/datasets/models.py`, alembic
revision `d4e5f6a7b8c9`), so a listing does not parse every `manifest.json` in
the user's store.

The index is a **derived cache**, and two invariants keep it from ever becoming a
source of truth:

- **Disk wins.** `reconcile()` walks the store, compares each manifest's
  `(mtime_ns, size)` against the row, and re-parses only what changed. It
  commits nothing when nothing moved. A dir whose manifest fails validation has
  its row **deleted**, matching the listing's own skip behavior, so the index
  cannot resurrect a dataset the catalog considers unreadable.
- **Never raise into a caller.** Every entry point has a `safe_*` wrapper
  (`safe_upsert_from_dir`, `safe_forget`, `safe_sync_rows_by_dir`,
  `safe_reconcile`) that rolls back and degrades to "no row". Callers fall back
  to parsing the manifest, so a DB failure costs speed, never correctness.

Rows are keyed on `user_key`, deliberately **not** a foreign key to `user.id`:
the literal `"guest"` is a valid key. Writes go through on every install path
(`install/installer.py`, `install/bundle.py`) and rows are dropped on delete.
Reads hydrate in `repositories/user_store.py` and `repositories/installed.py`.

`application/listing.py::resolve_execution_paths` uses the index as a fast path
for turning dataset ids into filesystem paths at execution time, falling back to
a full listing for hub and live-output ids. Both paths run the same containment
check, so an index row pointing outside the allowed read roots is refused rather
than served.

### Dataset Routes

Defined in `backend/app/datasets/routes.py`; all require authentication. See [DATA-CATALOG.md](DATA-CATALOG.md) for the user-facing model.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/datasets/catalog` | GET | List catalog items (`q`, `format`, `origin`, `sort`, `includeHub`, `groupOsm`, `dataflowId`, `liveOutputs`) |
| `/api/datasets/<id>` | GET | Dataset detail, including resolved producer node for computed datasets |
| `/api/datasets/<id>/preview` | GET | Paginated tabular/geo preview (`rowLimit` 1 to 500, default 50; `offset`; `part` for bundles) |
| `/api/datasets/<id>/usage` | GET | Dataflows across the user's projects that reference this dataset |
| `/api/datasets/<id>/download` | GET | Download the dataset file as an attachment |
| `/api/datasets/import` | POST | Upload a local file into the user's catalog (multipart: `file`, `dataflowId`, `title`, `sourceUpdatedAt`, and `discoverySource` for a file downloaded by hand, as JSON). **201** with the new dataset; with `discoverySource`, **200** with the held dataset when the resource or the bytes are already there |
| `/api/datasets/publish` | POST | Publish a dataset into the shared catalog |
| `/api/datasets/publish/<id>` | DELETE | Unpublish (remove from the shared catalog). **403** unless you published it |
| `/api/datasets/<id>` | DELETE | Permanently delete an account-level dataset. **403** unless you published it. Returns `failedDirs: string[]`; `deleted` is `false` when a directory survived (still HTTP 200) |
| `/api/dataflows/<dataflowId>/datasets/install` | POST | Attach a dataset to one dataflow (`datasetId`, optional `sourceItem`, `nodeTitle`) |
| `/api/dataflows/<dataflowId>/datasets/<id>` | DELETE | Detach a dataset from one dataflow (keeps the account asset) |

### Discovery Catalog Routes

Defined in `backend/app/discovery/routes.py` over `backend/app/discovery/service.py`.
The **unit is a source, not a dataset**: manifests under `discovery/` and
`.curio/discovery/` describe where datasets can be fetched from. A portal's
datasets are discovered live; a storage source's resources are declared, and
listed from a scan of its files. A download hands the bytes to the Data Catalog's own importer, so what
comes out is an ordinary dataset carrying a `discoverySource` provenance block.
[Discovery Catalog](#discovery-catalog) describes the mechanism behind these
routes.

It is the one path a remote file takes into the Data Catalog. The Discovery Catalog
page's Download, the Dataset Finder card's Download and confirmation, and an
agent's approved `discovery.acquire` all call `DiscoveryService.start_acquire`.
A file a person downloads by hand is imported with its origin (the `discoverySource`
field on `/api/datasets/import`), and both paths match by resource and by
content digest, so one file is one dataset.

| Route | Method | Purpose |
|---|---|---|
| `/api/discovery/catalog` | GET | List the sources (`q`, `provider`, `auth`). Disk only - makes no outbound request |
| `/api/discovery/sources/<dir>` | GET | One source, with its capabilities and credential state, and a storage source's declared resources |
| `/api/discovery/sources/<dir>/icon` | GET | The source's mark. Fixed `image/png`, `nosniff`, `ETag`, 256 KiB cap; 404 when absent so the UI falls back to a glyph |
| `/api/discovery/search` | GET | **Live, federated.** Fans out over every searchable portal and every storage source's listing (`q` required, `format`, `provider`, `limit`). A failing leg is reported in `sources[]` and never fails the request |
| `/api/discovery/sources/<dir>/search` | GET | **Live**, one source. The only paginated search - a fan-out has no coherent cursor. A storage source answers from its listing, with `unmatched` and `scannedAt`; `rescan=1` walks it again |
| `/api/discovery/sources/<dir>/files/<id>` | GET | A storage row's files, `offset` and `limit` (at most 100), each with its `index`, from the last listing |
| `/api/discovery/sources/<dir>/thumbnails/<n>/<id>` | GET | A thumbnail of file `n` of a storage collection row |
| `/api/discovery/sources/<dir>/resources/<id>` | GET | **Live** resource detail: fields, licence, provider extras |
| `.../resources/<id>/acquire` | POST | Download or add into the Data Catalog. **202** with a job, or **200** with the dataset when it is already held (no portal contacted). `refresh` asks again anyway. `parameters` carries the answers to what the resource declares, checked before a job exists. A storage row also takes `filters` and `files` |
| `/api/discovery/collections/<datasetId>` | GET | Where a collection's files are: `local`, `cachedFiles` of `fileCount`, and a few samples by id |
| `/api/discovery/collections/<datasetId>/cache` | POST | Cache a bucket collection's files, as a job. 400 for a folder's |
| `/api/datasets/<id>/media/<file_id>` | GET | A collection file: `variant=thumb`, `poster` or `original`. By id only |
| `/api/datasets/<id>/media/<file_id>/link` | POST | A signed URL for `<video>` and `<audio>`, valid 10 minutes |
| `/api/media/<token>` | GET | The one file a signed link names, with Range. No bearer token |
| `/api/discovery/places` | GET | Places for the area field (`q`), from Nominatim: name, label, box, and whether each is a boundary |
| `/api/discovery/keys` | GET | Every key slot API Settings lists: label, field, help link, `present` and `inherited` as booleans, and the sources and features that use it |
| `/api/datasets/<id>/extent` | GET | The box around a geo dataset, in EPSG:4326, for the area field |
| `/api/discovery/jobs/<id>` | GET | Job progress. Per account: another user's id is indistinguishable from an unknown one |
| `/api/discovery/jobs/<id>` | DELETE | Ask a download to stop; checked between chunks |

Errors map by type: 404 unknown source or resource, **428** a source needing a
token this account does not hold, 429 rate-limited, 502 a portal that answered
badly or an egress refusal (the policy reason, never a resolved address), 503 a
storage source that cannot be read (its folder is not there), 415 a collection
file that cannot be served as asked (no preview, or not a format Curio serves),
400 an unsupported format or an oversized download.

### Model Catalog Routes

[Model Catalog](#model-catalog) describes what these read and write. Every route needs a signed-in caller.

| Route | Method | Purpose |
|---|---|---|
| `/api/models/catalog` | GET | The account's models and the shipped ones (`q` filters by name, id, description, publisher and tags) |
| `/api/models/<id>` | GET | One model: its runtime, task, labels, input, license, size and where it came from |
| `/api/models/<id>/license` | GET | The text of the model's license file, as `{"text": ...}` |
| `/api/models/<id>` | DELETE | Delete a model the account added. **403** for a shipped model |

A model is added only through the Discovery Catalog's acquire route, on a model source's row.

### Agent Routes

Defined in `backend/app/agents/routes/` (one module per resource) over the `backend/app/agents/service.py` facade; all
require authentication, and every project endpoint checks ownership (404 when the
project is not the caller's). See [AGENT-CATALOG.md](AGENT-CATALOG.md) for the
user-facing model, the manifest contract, and the storage layers.

Catalog and account scope:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/agents/catalog` | GET | List the agent definitions available to add: the catalog cards and published definitions, never an internal built-in (`projectId` marks those already in that dataflow). Returns `{items, agents, facets}`, the same envelope the dataset catalog returns |
| `/api/agents/llm` | GET | The account's LLM configurations (never a key: `hasApiKey` and `baseUrlHost` instead), its default, what the deployment offers, what answers a run now, and the agents whose configuration may be chosen, each with its choice and what it answers with. A hosted guest gets the guest configuration and `editable: false` |
| `/api/agents/llm/configs` | POST | Add a configuration. **400** on an unknown field or an invalid one, **403** for a hosted guest |
| `/api/agents/llm/configs/<id>` | PATCH, DELETE | Change one (a blank key keeps the stored one; a new endpoint needs the key again) or remove it, which resets a removed default and clears the agents chosen for it (`moved`). **409** while a training job runs on it: for a change, when the change touches its endpoint or key |
| `/api/agents/llm/configs/<id>/duplicate` | POST | Copy one, its key included, server-side; `{label?, model?}` |
| `/api/agents/llm/default` | PUT | Choose the default, `{configId}`; `null` is the Deployment default |
| `/api/agents/llm/assignments` | PUT | Choose agents' configurations: a partial map of agent id to a configuration id, `"deployment"` or `null` (clears). Nothing is written unless every entry is valid; an internal agent is refused; **403** for a hosted guest |
| `/api/agents/provider-models` | POST | The models API Settings can offer for the endpoint being configured. POST because the panel asks *before* the user saves, carrying the provider, base URL and key on screen. A stored key is borrowed only with `configId`, and only while the endpoint on screen is still that configuration's own, or with `endpoint: "deployment"`; with neither, no key is borrowed. Hybrid, both halves from the API: the live listing (OpenAI-compatible, Anthropic and Gemini, all via `agents/providers.py`), falling back to what that endpoint last reported, recorded per account by `agents/model_catalog.py`. Answers `{models, listable, source, remembered, rememberedAt, warning}`; a failed listing is a 200 with `source: "remembered"` unless nothing was ever recorded, which is a 400 |
| `/api/agents/settings` | GET, PUT | The catalog settings: each one's schema, default, the account's value and the agents that read it, plus whether this account may change them. `PUT` takes key to value (`null` restores the default) and saves nothing unless every value is valid; **403** for a hosted guest |
| `/api/agents/imports` | GET | List the account's imported definitions, as cards |
| `/api/agents/imports` | POST | Record `<id>@<version>` in My imports. Never adds to a dataflow |
| `/api/agents/imports/upload` | POST | Upload a user-authored definition (`manifest` + `prompts` as JSON, no archives). Trust forced to `imported`, digests stamped from the bytes, **409** on an existing coordinate |
| `/api/agents/imports/<coord>` | DELETE | Drop it from My imports. The definition stays on disk |
| `/api/agents/publications` | POST | Publish an owned, imported, store-backed definition to the shared catalog |
| `/api/agents/publications/<coord>` | DELETE | Unpublish it. Owner only |

Per-dataflow scope:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/agents/projects/<projectId>` | GET | The dataflow's added agents, from its `dataflow.agents` lockfile |
| `/api/agents/projects/<projectId>/install` | POST | Add `{coord}` **and its `requiresAgents` closure** in one spec write. Resolves the closure before writing: **409** naming the missing ids, nothing written |
| `/api/agents/projects/<projectId>/<coord>` | DELETE | Remove it and its defaults record. **409** naming the dependents while another added agent requires it |

Attachments and runs:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/agents/projects/<projectId>/attachments` | GET, POST | List, or bind an added agent to a `{kind: node\|canvas\|connection, targetId?}`. Never auto-adds |
| `/api/agents/projects/<projectId>/attachments/<id>` | DELETE, PATCH | Detach (also deletes the transcript), or set the editable initial intent |
| `/api/agents/projects/<projectId>/attachments/<id>/session` | GET, DELETE | The persisted chat transcript, or clear it (the attachment survives) |
| `/api/agents/projects/<projectId>/attachments/<id>/run` | POST | Run one turn. Returns `{reply, executionId, usage, content}`; persists both turns |
| `/api/agents/projects/<projectId>/attachments/<id>/run/stream` | POST | The same turn as Server-Sent Events: `execution` then `delta` chunks, tool rounds, `review_required`, `content`, `done` |
| `/api/agents/projects/<projectId>/attachments/<id>/proposals/<proposalId>` | POST `/apply`, DELETE | Apply a pending review proposal (the only mutation path; re-checks the pinned digest, **409** on drift) or dismiss it |

Solve and planning. The Dataflow Builder drives a batch that plans, generates,
executes and self-corrects; each stage is a reviewed proposal the user applies,
never an automatic write:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/agents/projects/<projectId>/attachments/<id>/solve` | POST | Run the Solve batch over a plan's nodes |
| `/api/agents/projects/<projectId>/attachments/<id>/solve/stream` | POST | The same batch as Server-Sent Events |
| `/api/agents/projects/<projectId>/attachments/<id>/solve/cancel` | POST | Stop dispatching new children; undispatched targets revert to pending. **409** when nothing is running |
| `/api/agents/projects/<projectId>/attachments/<id>/simulate` | POST | Simulation Mode, as Server-Sent Events |
| `/api/agents/projects/<projectId>/attachments/<id>/simulate/cancel` | POST | Stop at the next action boundary; what is done stays done |
| `/api/agents/projects/<projectId>/attachments/<id>/run-node` | POST | Execute the dataflow *through* one node, using its saved content, as Server-Sent Events |
| `/api/agents/projects/<projectId>/attachments/<id>/validate-node` | POST | Generate, execute-through, validate, self-correct, then propose, for one node, as Server-Sent Events |
| `/api/agents/.../proposals/<proposalId>/apply-node` | POST | Apply one planned node from a pending dataflow-plan proposal |
| `/api/agents/.../proposals/<proposalId>/apply-edges` | POST | Apply the plan's edges: the connection review stage |
| `/api/agents/.../proposals/<proposalId>/plan-goals` | PATCH | Edit one planned node's goal before it is created |

Every run appends to a per-day ledger under a file lock
(`.curio/users/<key>/agents/ledger/`), written from the token counts each
provider returns on the completion itself. It is a record, not a gate: no run is
refused for usage, no USD is computed, and no endpoint exposes it. A
completion's output cap is the deployment constant
`services.DEPLOYMENT_MAX_OUTPUT_TOKENS`.

### Starter Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/starters` | GET | Per-template starter source bodies from every installed package, keyed on `<packageId>/<templateId>@<major>` |

Starters come from each installed package's optional per-template `source` file.
`curio.builtin@1` ships no sources, so dragging a built-in node onto the canvas
yields an empty editor; third-party packages may ship a starter per template.
When a template declares both `behavior: "code"` and a `source`, the frontend
composes `withPackageStarter` over the behavior hook so the starter is injected
on a fresh drop (see [Behavior Hooks](#behavior-hooks)).

### Auth Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/auth/signup` | POST | Create an account (username + password) |
| `/api/auth/signin` | POST | Username/password sign-in |
| `/api/auth/signin/guest` | POST | Guest sign-in (when enabled) |
| `/api/auth/signout` | POST | Invalidate the session token |
| `/api/auth/me` | GET/PATCH | Current user profile |

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
| `src/registry/builtinBehaviors.ts` | `registerBehavior()` calls for the built-in behavior hooks |
| `src/registry/behaviorRegistry.ts` | `behavior` key → hook lookup (built-in + package-shipped) |
| `src/registry/nodeRegistry.ts` | Singleton store of all `NodeDescriptor`s; subscribed by the palette + canvas |
| `src/registry/packageRegistryBootstrap.ts` | Boot-time orchestration: load installed packages, inject behavior bundles, build descriptors |
| `src/registry/index.ts` | Exposes `window.curio.registerBehavior` + `window.curio.backendUrl` for package bundles |
| `src/registry/types.ts` | TypeScript interfaces for descriptors, adapters, behavior hooks |
| `src/constants.ts` | `SupportedType` and `EdgeType` enums, and `NodeType`, the built-in template ids (node types live in package manifests) |
| `src/adapters/node/` | Built-in behavior hook implementations (code, vega, autk family, …) |
| `src/utils/renderOutcome.ts` | The empty-render decision every browser renderer calls (see [Render Outcomes](#render-outcomes)) |
| `src/generated/` | Contract copies written by `scripts/generate_contracts.py`; never edited by hand |
| `src/ConnectionValidator.ts` | Edge validation logic |
| `src/api/` | API client wrappers (`projectsApi`, `connectionKeysApi`, `evaluationApi`, `trainingApi`); `authApi` lives at `src/utils/authApi.ts` and the packages client in `src/services/packages/` |
| `src/services/packages/` | The node-package service layer (memo dev/143): `packagesApi` (the request object) + `packagesBlobTransport` (sideload, archive download, factory build, `triggerBlobDownload`) + `packageBackendApi` (the only transports), `usePackageCatalog` (THE catalog hook the canvas drawer and the `/catalog/nodes` page both render, scope as an option, with `probeInstallConflicts` the one pre-install probe), the pure logic the surfaces share (`packageListUtils`, `forkPackageLineage`, `packageDependencyNotice`, `packageRestartCopy`, `factoryDraft`) and every package type by concern under `types/` (`SortMode` included). Import from its barrel, `services/packages`; `tests/packages/servicesBarrel.test.ts` enforces that the layer renders nothing, that no node-catalog surface reaches transport, and that the layer never imports `registry/` at runtime: the registry consumes the layer, never the reverse |
| `src/providers/packages/` | `NodeCatalogDrawerProvider` and `PackagePaletteContext`, plus the two hooks that compose the layer with the node-kind registry (`usePackageArchiveImport`, the one sideload pathway, and `useEnsureWorkflowDeps`). `index.tsx` composes from the barrel; other consumers name the module (the barrel carries a rendering provider beside registry-touching hooks) |
| `src/components/packages/publishing/NodeCatalogDrawer.tsx` | The canvas drawer that installs node packages from the catalog: a rendering surface over `usePackageCatalog({ kind: "project" })`; `pages/catalog/useNodeCatalogBrowse.ts` is the page's adapter over the same hook |
| `src/services/agents/` | The agents service layer (memo dev/142): `agentsApi` + `agentStream` (the only two agent transports), the window events and drag helpers (`resolveAgentDropTarget` included), `useAgentCatalog` / `useAgentAttachments` (the hooks over the transport), the pure logic the surfaces share, and every agent type by concern under `types/`. Import from its barrel, `services/agents`; `tests/agents/servicesBarrel.test.ts` enforces that no agents component, page or provider reaches transport itself |
| `src/providers/agents/` | `AgentAttachmentsProvider` composing `useAgentSession`, `useAgentProposals`, `useAgentSolve`, `useAgentSimulation` and `useAgentNodeRuns`; imported from its barrel, `providers/agents` |
| `src/components/agents/catalog/AgentCatalogDrawer.tsx` | The canvas drawer that adds agents to the open dataflow |
| `src/pages/agents/AgentCatalogBrowse.tsx` | The `/catalog/agents` browse page, the account-scope peer of the other two catalogs |
| `src/components/ApiSettingsModal.tsx` | API Settings: the account's LLM configurations, tokens, connection keys, Evaluation mode and Model training |
| `src/components/llmConfigs/` | The LLM configurations table, its editor, Agent models and the `llm-config` remedy button, over `src/api/llmConfigsApi.ts` |
| `src/components/menus/libraries/LibraryManagerWindow.tsx` | "Installed Libraries" modal (per-user pip libs, manifest-derived libs) |

### Backend

| File | Purpose |
|---|---|
| `backend/server.py` | Builds the Flask app from `create_app` (`backend/app/__init__.py`); Werkzeug reloader exclude patterns |
| `backend/app/api/routes.py` | REST endpoints for sandbox proxies, starters, and file serving |
| `backend/app/packages/domain/manifest.py` | Parse `manifest.json` into typed `PackageManifest` dataclass |
| `backend/app/packages/repositories/archive.py` + `application/store_install.py` | The `.curio.zip` format (member safety, integrity hashing) and catalog-source-dir → archive → user-store copy |
| `backend/app/packages/infrastructure/pip_runner.py` | `install_python_deps` / `uninstall_python_deps`; PEP 440 + caret support, idempotent skip |
| `backend/app/packages/domain/versions.py` + `application/resolution.py` | `merge_python_deps` (conflict-aware union across packages) and the package DAG over the store |
| `backend/app/packages/service.py` | The facade every packages route and every other feature calls (mirrors `datasets/service.py`, `agents/service.py`); re-exports the use cases under `application/` (`store_install`, `project_packages`, `defaults_install`, `prune`, `templates`, `agent_reads`, …) and the cross-feature surface (spec readers, ids, manifest read, store paths, the runtime seams). `tests/test_packages/test_layering.py` enforces the layers |
| `backend/app/packages/routes/` | `/api/packages/*` endpoints by resource (`store`, `catalog`, `factory`, `dependencies`, `projects`, `defaults`, `libraries`, `backend`) under one blueprint and one `_map_package_errors`; the route table is a contract test (`tests/test_packages/route_table.json`) |
| `backend/app/packages/application/libraries.py` | Per-user `.curio/users/<u>/installed-libraries.json` storage + aggregator |
| `backend/app/datasets/service.py` | `DatasetCatalogService`, the façade every dataset route calls |
| `backend/app/datasets/routes.py` | `/api/datasets/*` and `/api/dataflows/<id>/datasets/*` endpoints |
| `backend/app/datasets/domain/` | Dataset manifest parsing, catalog items, computed-dataset identity, dedup, provenance |
| `backend/app/datasets/application/` | Listing, preview, export, mutations, path resolution, auto-install |
| `backend/app/datasets/install/` | Dataset installer, multi-part bundles, OSM/PBF layer extraction |
| `backend/app/datasets/repositories/` | Installed / local / registry / user-store persistence, plus the per-user dataset index |
| `backend/app/datasets/repositories/index.py` | The dataset index: write-through, disk reconciliation, never-raise `safe_*` wrappers |
| `backend/app/datasets/models.py` | `DatasetIndexEntry`, the index's SQLAlchemy table |
| `backend/app/datasets/infrastructure/` | Storage helpers, file metadata, output paths, catalog utilities |
| `backend/app/datasets/schemas/` | Request and catalog-item serialization schemas |
| `backend/app/agents/routes/` | `/api/agents/*` endpoints, one module per resource (`catalog`, `lifecycle`, `attachments`, `proposals`, `turns`, `solve`, `llm`, `training`, `evaluation`); `common.py` holds the blueprint and the shared helpers; the route table is a contract test (`tests/test_agents/route_table.json`) |
| `backend/app/agents/domain/contracts.py` | The single source of every generated contract, and the registry of its outputs (see [Generated Contracts](#generated-contracts)) |
| `backend/app/agents/schemas/autk-grammar.v1.json` | The vendored Autark grammar schema, with its release record beside it (see [The Autark Schema](#the-autark-schema)) |
| `backend/app/agents/domain/document_validation.py` | Validates the documents agents write (Vega-Lite, Autark) before they reach a node |
| `backend/app/agents/service.py` | The facade every agent route and every other feature calls (mirrors `datasets/service.py`, `packages/service.py`); re-exports the use cases under `application/` (`tests/test_agents/test_layering.py` enforces the layering) |
| `backend/app/agents/application/lifecycle.py` | Import/remove, seed, install with its `requiresAgents` closure, uninstall, publish/unpublish |
| `backend/app/agents/application/catalog.py` | Catalog reads: facets, cards, definition bundles, the three listings, the choosable agents, the catalog settings listing |
| `backend/app/agents/application/attachment_management.py` | Attach, detach, intent/title edits, session read/clear |
| `backend/app/agents/application/proposals/` | Review-before-apply: `mint.py`, `apply.py`, `plans.py`, `store.py`, `cards.py`, and `acquire.py` (the Discovery Catalog acquisition) |
| `backend/app/agents/application/turns/` | One chat turn: `attachment_turn.py` (the two entry points), `turn_loop.py` (`AttachmentTurn`: the bounded tool loop once, blocking or streaming), `prepare.py`, `grounding.py`, `delegates.py`, `roster.py`, `policy.py`, `prompts.py`, `titles.py` |
| `backend/app/agents/application/solve/` | Solve: `session.py` (the stream entry points and the session helpers), `batch.py` (`SolveBatch`: passes, waves, the fold, one finish), `rounds.py` (attempts, probes, remedies), `verified_loop.py` (`VerifiedRounds`: the generate → gate → execute → correct loop, one named stage per method), `node_solve.py`, `budgets.py`, `simulation.py` (`SimulationDriver`), `run_node.py`, `validate.py` |
| `backend/app/agents/application/tool_rounds.py` | The bounded tool loop and the native tool-call machinery (`_RunConversation`) |
| `backend/app/agents/application/llm_listing.py` | `GET /api/agents/llm`: the account's configurations, the deployment's offer, what answers each agent |
| `backend/app/agents/infrastructure/llm_configs.py` | The account's LLM configurations (`llm-configs.json`), beside the provider resolver that reads them |
| `backend/app/agents/repositories/storage.py` | Definition store under `.curio/users/<u>/agents/<coord>/` |
| `backend/app/agents/repositories/imports.py` | My imports registry (`imported-agents.json`) |
| `backend/app/agents/repositories/project_agents.py` | The per-dataflow lockfile in `spec.dataflow.agents` |
| `backend/app/agents/application/attachments.py` | Attachments in `spec.dataflow.agentAttachments`, plus their sessions |
| `backend/app/agents/domain/manifest.py` | Parse and validate `manifest.json` into a typed `AgentManifest`; `AGENT_CATEGORIES` |
| `backend/app/agents/domain/builtin.py` | The 13 built-in agents, as a data-driven roster. `in_catalog` marks the ten catalog cards; the rest are internal: never listed, installed or attached, and resolved from the roster when delegated to. Two run their capabilities as modes (see [Agent Prompt Composition](#agent-prompt-composition)) |
| `backend/app/agents/repositories/storage.py` | Definition store under `.curio/users/<u>/agents/<coord>/` |
| `backend/app/agents/repositories/imports.py` | My imports registry (`imported-agents.json`) |
| `backend/app/agents/repositories/catalog_settings.py` | The account's catalog settings (`catalog-settings.json`) and the configuration slot a run receives |
| `backend/app/agents/repositories/project_agents.py` | The per-dataflow lockfile in `spec.dataflow.agents` |
| `backend/app/agents/application/attachments.py` | Attachments in `spec.dataflow.agentAttachments`, plus their sessions |
| `backend/app/agents/infrastructure/provider_config.py` | `resolve_llm`, the one LLM resolver, which reads the deployment's LLM settings (see [LLM Configurations and Resolution](#llm-configurations-and-resolution)) |
| `backend/app/agents/infrastructure/llm_configs.py` | The account's LLM configurations (`llm-configs.json`): validation, the default, and the store reads that carry a key |
| `backend/app/common/owner_only_file.py` | Owner-only JSON files: 0700 directory, 0600 file, atomic write under an exclusive lock. Used by connection keys and LLM configurations |
| `backend/app/agents/infrastructure/providers.py` | Provider-neutral dispatch port; the only place an LLM SDK is imported. Typed turns and their text forms, streaming, the system slots per provider, native tools per provider and their refusal, cache usage, the native-tools trial, and the live model listing |
| `backend/app/agents/application/tools.py` | The tool registry: each contract's effect, description and params schema, grant resolution, the read executors, and the native tools a run is offered |
| `backend/app/agents/application/reply_schemas.py` | The Autark document's reply schema, projected from the vendored schema per provider flavor; decoding a reply; which runs send one |
| `backend/app/agents/infrastructure/chat_capabilities.py` | What an endpoint can do beyond text (native tools, a reply schema): the table, the per-model trial and its record, trained and scripted configurations |
| `backend/app/agents/repositories/model_catalog.py` | Per-account record of what each provider endpoint last reported, replayed when a live listing is impossible. Derived from the API, never hand-authored; a suggestion, never an allowlist |
| `backend/app/agents/infrastructure/testing_provider.py` | Scripted provider under `CURIO_TESTING`, re-guarded at call time; what e2e drives. A reply is text, native tool calls, or an endpoint error |
| `backend/app/agents/repositories/ledger.py` | Append-only per-day record of runs and tokens; flock-guarded. A record, not a gate |
| `backend/app/users/models.py` | `User` and `UserSession` SQLAlchemy models |
| `backend/extensions.py` | SQLAlchemy and Flask-Migrate initialization |

### Sandbox

| File | Purpose |
|---|---|
| `sandbox/app/api.py` | Sandbox REST endpoints (`/exec`, `/execJs`, `/get`) |
| `sandbox/app/worker.py` | `execute_code` and `execute_js_code`: run a node's Python or JavaScript |
| `sandbox/util/db.py` | DuckDB connection, path resolution, and `artifacts` table initialization |
| `sandbox/util/parsers.py` | `save_to_duckdb`, `load_from_duckdb` and the artifact path helpers |
| `sandbox/util/codec.py` | Value to bytes conversion, and `detect_kind` |
| `sandbox/app/utils/cache.py` | Execution result caching |
