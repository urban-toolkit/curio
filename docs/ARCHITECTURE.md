# Curio Architecture

This document describes the internal architecture of Curio for contributors who need to understand how the system is structured and how data moves through it. For setup instructions see [USAGE.md](USAGE.md), for contributing guidelines see [CONTRIBUTING.md](CONTRIBUTING.md), for how node packages are installed and shared see [NODE-CATALOG.md](NODE-CATALOG.md) (to add a built-in behavior hook or grammar adapter, see [Behavior Hooks](#behavior-hooks)), and for an end-to-end walkthrough of adding a new node package (manifest + behavior hook + optional Flask blueprint + optional dependency extras) see [EXTENDING.md](EXTENDING.md).

## Table of Contents

* [System Overview](#system-overview)
* [Three-Tier Architecture](#three-tier-architecture)
* [Frontend: Workflow Canvas](#frontend-workflow-canvas)
  * [Provider Hierarchy](#provider-hierarchy)
  * [API Settings and the Monitor](#api-settings-and-the-monitor)
  * [FlowProvider: Central Workflow State](#flowprovider-central-workflow-state)
  * [The notebook view](#the-notebook-view)
  * [Drawing scenarios](#drawing-scenarios)
  * [Tooltips](#tooltips)
* [Nodes: Types and Structure](#nodes-types-and-structure)
  * [Node Packages and Manifests](#node-packages-and-manifests)
  * [A dataflow's tags and data types](#a-dataflows-tags-and-data-types)
  * [Built-in nodes by their declared behavior](#built-in-nodes-by-their-declared-behavior)
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
* [Shared Constants](#shared-constants)
* [Agent text](#agent-text)
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
│  Auth, user DB, file serving, proxy to sandbox      │
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
| Backend | `utk_curio/backend/` | REST API, user auth, user and project database, file storage |
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

Per dataflow route, in `DataflowProviders` (`src/components/DataflowProviders.tsx`),
which `MainCanvasRoute` and `DashboardRoute` in `src/index.tsx` both render:

1. `DialogProvider`: modal dialogs
2. `CollaborationProvider`: presence, locks, proposals; left out on the dashboard
3. `FlowProvider`: nodes, edges, outputs, interactions. The primary state
4. `CanvasDatasetDetailsProvider`: a dataset's details, opened from any drawer or palette
5. `ApiSettingsDrawerProvider`: API Settings as a drawer (see [API Settings and the Monitor](#api-settings-and-the-monitor))
6. `MonitorDrawerProvider`: the monitor as a drawer
7. `ProvenanceDrawerProvider`: the provenance drawer (see [The provenance drawer](#the-provenance-drawer))
8. `NodeCatalogDrawerProvider`
9. `DatasetCatalogDrawerProvider`
10. `AgentCatalogDrawerProvider`
11. `ModelCatalogDrawerProvider`
12. `DiscoveryCatalogDrawerProvider`
13. `StarterProvider`: per-template starter source snippets
14. `ProjectLoader`
15. `PackagePaletteProvider`
16. `DatasetPaletteProvider`
17. `MainCanvas`, or `DashboardPage` on the dashboard
18. `AgentAttachmentsProvider` (`src/providers/agents/`), on the canvas only: the attached agents, mounted in `MainCanvas.tsx`
    rather than `index.tsx` because it needs React Flow's instance and only
    applies where there is a dataflow to attach agents to

Two of these orderings are load-bearing rather than incidental:

- `CollaborationProvider` must wrap `FlowProvider`. Outside it, FlowProvider's
  mutation paths get the no-op default context and silently drop every peer
  edit.
- The catalog drawer providers must sit inside `FlowProvider`, because a
  drawer's Install writes to the open dataflow. Outside it, `useFlowContext`
  returns no-op defaults and Install appears to succeed while doing nothing.

Each provider exposes its context via a custom hook (e.g., `useFlow()`, `useProvenance()`). Components call these hooks rather than reaching into global variables.

### API Settings and the Monitor

`GlobalPageHeader` (`src/components/layout/`) is the top bar of every signed-in
page: the section pages, the canvas and the dashboard. Its **Monitor** and
**API Settings** read `useMonitorDrawerOptional()` and
`useApiSettingsDrawerOptional()`. Where `DataflowProviders` mounts
`MonitorDrawerProvider` and `ApiSettingsDrawerProvider` (the canvas and the
dashboard), they are buttons that open those drawers, built on `HeaderDrawer`,
and the dataflow stays open. On every other page there is no provider, and they
are links to `/monitor` and `/settings`. The monitor's content is
`MonitorContent` (`src/pages/monitor/`), which the `/monitor` page and
`MonitorDrawer` both render.

API Settings is `ApiSettingsPanel` (`src/components/apiSettings/`), which the
settings page (`src/pages/settings/SettingsPage.tsx`, at `/settings/keys` and
`/settings/agents`) and `ApiSettingsDrawer` both render. The page keeps the tab
in its URL, the drawer in its state. Its two tabs:

- **API keys** (`ApiKeysTab`): one table of every key the account uses. Its
  **Language model** rows come from `GET /api/agents/llm` (the Deployment
  default and each LLM configuration), its **Data source** rows from
  `GET /api/discovery/keys` (a key is listed when one is saved or inherited),
  and its **Node code** rows from `/api/users/me/connection-keys`.
  **Add configuration** opens one editor whose **Kind** select picks the form:
  `LlmConfigEditor`, `SourceKeyForm` for a key without a saved one, or
  `NodeKeyForm`.
- **Agent configuration** (`AgentConfigTab`): the default
  (`PUT /api/agents/llm/default`) and `AgentModelsSection`, the configuration
  each agent runs on (`PUT /api/agents/llm/assignments`).

A card elsewhere asks for a place in API Settings without importing it.
`apiSettingsRequest.ts` dispatches a `curio:api-settings` window event carrying
a focus: the node code key form with a host filled in, a data source key's
form, an LLM configuration's editor, or an agent's row. The one
`ApiSettingsRequestHost` on the page, mounted by the top bar, opens the drawer
on it where there is one, and otherwise navigates to the settings page with the
focus in the URL (`settingsPath`, read back by `focusFromSearch`).

### The provenance drawer

**View > Provenance** calls `openDataflowProvenance()`, and a node's Provenance
button `openNodeProvenance({ nodeId, title, restore })`, from
`ProvenanceDrawerProvider` (`src/providers/`; menus and nodes import the hooks
from `provenanceDrawerContext.ts`). It mounts `ProvenanceDrawer`
(`src/components/provenance/`): a `HeaderDrawer` on the right with the catalog
drawers' pin (`pinnable`) and width (`wide={false}`).

- `ProvenanceHistory` lists a history as Curio's Nest lists work, from items
  that each name the item they were made from. `utils/provenanceTree.ts` lays
  it out: the line through the newest item is the main one, and each branch is
  folded under the item it left from, nested to any depth. Every item has one
  parent, so a history is a tree, and the list shows all of it.
- `DataflowProvenance` reads the versions `TrillGenerator.provenanceJSON`
  holds (`utils/dataflowVersions.ts` numbers and names them) when the drawer
  opens. A click opens a version; its **Put this version on the canvas** calls
  `TrillGenerator.switchProvenanceTrill`, which loads it through
  `useCode().loadTrill(trill, undefined, true)`, keeps the history and marks
  the dataflow unsaved.
- `NodeRunsProvenance` reads the node's runs from `ProvenanceProvider`
  (`utils/nodeRuns.ts` names them by the kinds they read and returned). A
  run's **Put this code back in the node** sets it as the run the next one
  branches from (`setSelectedExec`) and calls the node's `restore`:
  `NodeEditor` hands its editors the code as `restoredCode`, which they write
  in through `useMonacoExternalValue`'s `applyValue`, as a collaborator's
  applied change, and prime the widgets as a load does. It is not a new
  default: a default equal to the loaded code is never applied. The drawer
  closes when its node leaves the flow.
- The Provenance button is the provenance pill among the node's tab pills, but
  not a tab: `NodeEditor`'s `handleTabSelect` sends it to the drawer.

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
| `canvasView` | `"canvas" \| "notebook"` | How the canvas shows the dataflow, kept in the address as `?view=notebook` through the router (`CanvasViewAddress`), also across a navigation that keeps the dataflow open; always `"canvas"` on the dashboard |
| `scenarios` | `Scenario[]` | The dataflow's scenarios (`dataflow.scenarios`), saved with it |

When a node produces output, it calls `outputCallback(nodeId, output)`, which updates `outputs`. React re-renders cause downstream nodes (those connected by an edge from the node that just executed) to detect the new input and request the data from the backend.

Opening a dataflow (`ProjectLoader`) and dropping a scenario restore saved outputs: they go into `outputs`, and `hydrateRestoredOutputs` (`providers/flow/useApplyOutput.ts`) hands each one to the nodes below its producer, once, along the edges the load built. The load's replay of its saved edges through `onConnect` hands over no output of a node the load added. Any other new edge, one the user draws or one from a node already on the canvas (Duplicate selection wiring a copy), hands its source's output to its own target alone; the nodes the source already feeds get nothing.

### The notebook view

The notebook view shows the canvas's own nodes and edges as a column of cells, with
the edges in a bar to the right. It is the same React Flow instance, because Run All,
output propagation, `onConnect` and saves read its store, so `providers/flow/useNotebookView.ts`
moves nodes the way the dashboard page does:

- **Positions.** Each node's canvas spot is stamped into `data.workflowPosition`, which
  `TrillGenerator` saves in place of `position` (`utils/canvasPosition.ts`), and
  `position` holds the cell's slot. The hook owns a map from node id to canvas spot and
  writes every stamp from it on each change of the node list, so an update that rebuilt a
  node's data without its stamp is repaired before a save reads the store. A
  collaborator's drag goes to the map (`useCollaborationSync`'s `takeCanvasPosition`).
  Leaving the view restores every position from the map and deletes every stamp; the
  canvas viewport saved on entry is restored after the canvas props are live.
- **Order and geometry.** Cells follow `utils/dataflowOrder.ts`, the order Export as
  notebook writes, over `directedEdgesOf`: chains stay together, each node followed by
  the nodes it feeds (as soon as their last input is placed, newest connection first)
  before the next node waiting, so a node added on the canvas and wired from another
  lands right below it. `utils/notebookLayout.ts` places the cells below the bar and title
  chips, spanning the page from its left margin to the bar on its right edge (at least
  480px), sets each node's dots on its right edge, gives every edge a lane in the bar
  (shorter spans inside) and draws the bracket each edge follows;
  `components/edges/useEdgePath.ts` picks that path over the canvas bezier.
- **Measured heights.** A cell is as tall as its content. React Flow measures every
  node and writes its `height` onto it (a `dimensions` change through `onNodesChange`),
  again whenever the node resizes, so the layout key holds each node's height and
  `layoutNotebook` stacks the cells by it, 24px apart; a cell not measured yet counts
  as 240px. The lanes are keyed on the rows and the bar only, so a cell that grows
  moves the cells below it without handing every node and edge a new context.
- **Graph edits on the canvas only.** Nodes are added, connected and deleted, and
  connections removed, on the canvas. `graphEditGates` (in `notebookLayout.ts`, read
  through `hook/useGraphEditGates.ts`) turns off React Flow's connecting
  (`nodesConnectable`, `edgesUpdatable`, `onConnect`), its Delete key (`deleteKeyCode`)
  and the page's drop handlers in the notebook view, and a cell's header has no Delete
  node tool (`components/nodes/NodeDeleteTool.tsx` reads the same gate). The
  connections take no focus (`edgesFocusable` in `notebookFlowProps`) and no click
  (`pointer-events: none` under the scroller's `data-curio-notebook`, `MainCanvas.css`),
  so none is selected. The View menu's Duplicate items and the Scenario Catalog
  drawer's Duplicate as scenario (its In project tab) are disabled there. The notebook view renders no `ToolsMenu`, only its `RunAllButton`
  (`components/notebook/NotebookRunAll.tsx`, top right of the page).
- **Dots.** `notebookHandlePlaces` anchors each dot to the cell's top (inputs, at fixed
  offsets), its middle (the interaction dot) or its bottom (outputs, `top: auto` inline,
  since React Flow's right-handle rule sets `top: 50%`), so they follow the cell as it
  grows; `notebookCellMinHeight` keeps a cell tall enough for its dots. React Flow
  measures the dots again on every resize, and each arc follows its two dots.
- **Scrolling.** `MainCanvas` wraps React Flow in a scroller in both views, so switching
  never remounts it. In the notebook view React Flow is as tall as the column, at zoom 1
  with no pan or zoom gestures (`notebookFlowProps`), and leaves the wheel to the page. A
  call that moves its view anyway, such as a load's fit, is put back to the origin.
  `revealNodes` scrolls to a cell where the canvas would frame a node.
- **Cells.** `NotebookViewContext` tells nodes and edges the view is on, and the cells'
  width. `UniversalNode` passes the cell's width and least height (`notebookCellBox`) as
  `cellBox`, apart from the node's canvas size. Every node's handles, the
  `UnresolvedNode` placeholder's too, are drawn by `components/nodes/NodeHandles.tsx`,
  which makes them the cell's dots; the placeholder's card takes the same box.
  `NodeContainer` draws the cell as the node card (see [The node card](#the-node-card))
  with no hairline or shadow, no resize handle and no minimize. `NodeEditor` keeps a
  grammar node's output pane visible under its input (`curio-notebook-split` in
  `Node.css`) without moving either pane, so a chart or map never remounts.
  `notebookOutputBox` gives an output the height its kind gets: a definite one for a
  chart (320px) and an Autark map or plot (400px), which have none of their own; a table, summary or control its own up to 360px; anything else
  360px. `useNotebookEditorHeight` (`components/editing/`) sets a code or spec editor's
  wrapper to Monaco's content height (`onDidContentSizeChange`), at least three lines,
  at most 400px for code and 240px for a spec. The outcome strip sits in the cell's flow
  under the output.
- **Switch.** `CanvasViewSwitch` closes `UpMenu`'s slot, pushed to its end beside
  Monitor; the canvas bar's buttons take `--curio-bar-button-padding-x: 7px` to make room
  for it.
- **Scenarios.** They are drawn on the canvas only: `MainCanvas` hands
  `scenarioCanvasView` no scenarios in the notebook view, so every node is a cell,
  collapsed or not, and no box or frame is drawn.

### Drawing scenarios

How the canvas draws scenarios is not dataflow state. `MainCanvas` passes `nodes`
and `edges` through `scenarioCanvasView` (`src/utils/scenarios/scenarioCanvasView.ts`)
on their way to React Flow: a collapsed scenario's members are hidden with
`hideNode` (`src/utils/hiddenNodes.ts`, which the dashboard uses too) and stay
mounted, the edges they touch are hidden, and expanded members get a class and their
color. The boxes, frames and stand-in edges it returns are drawn by
`components/scenarios/ScenarioLayers.tsx` beside React Flow's renderer, in its
coordinates, not as React Flow nodes and edges. React Flow's store is what
`reactFlow.getNodes()` returns to Run All, a save and an agent's view, so it must
never hold a node that is not in the dataflow. The dashboard page draws its
scenario columns' frames and headers with the same component;
`src/utils/scenarios/scenarioDashboard.ts` decides which column each pinned tile goes
in, and `prepareDashboardNodes` places the columns.

A node drawn hidden is never measured, so code that needs a node's size or hit-tests
nodes leaves it out (`isDrawnHidden`): the load fit (`fitViewWithMenuOffset`) and the
agent drop target do. `src/utils/scenarios/scenarioParts.ts` reads a scenario's fixed
context, levers and outcomes from the live graph, and `savedSourceNodeIds` there is
the one rule, read by a run and by a save, for which outputs are saved whatever a
node's own toggle says: what a pinned tile reads and what a scenario's context and
outcomes produce.

### Scenarios in charts and maps

A chart or a map outside the scenario boxes names what each box feeds it from the
box its input comes from, and draws exactly its spec: the boxes' colors and order
are what its scenario chips write.

- `src/utils/scenarios/inputScenarios.ts` is the one lookup: for each wired circle of a
  node, the node feeding it, the box that node is in and the label the input's rows
  carry (`inputLabelOf`: the box's id, name, color and `rank`, its place in
  `dataflow.scenarios`, else the feeding node's name and `NO_SCENARIO_COLOR`).
  `scenarioColors.ts` holds the label type, the `scenario` and `scenario_name`
  columns, `scaleLabels` (each box once by rank, then each input from no box in
  circle order), `scenarioScale` (each name once, a box in its color and each input
  from no box in a grey of its own from `NO_SCENARIO_GREYS`, past one a box there
  uses), `anyFromABox` and `tableTextColor`. Its Python twin is
  `WorkflowSpec.input_scenarios` (`execution/workflow_spec.py`), with `node_label`
  for a node in no box: its title, else its header, the template's label looked up
  by the canonical template id as `node_names.saved_node_label` looks it up, from
  the project's template labels (`labels`), which a run and the agents' check pass.
- A Vega-Lite spec that names the dataset `inputs` anywhere, its chips resolved
  (`readsInputs` in
  `src/utils/vegaDatasets.ts`, which makes `usesNamedDatasets` true for it) gets every
  input's rows stacked in circle order, each with `__input__`, `scenario` and
  `scenario_name`. `prepareVegaInputs` (`utils/vegaInput.ts`) builds the dataset with
  `stackInputs` (`utils/scenarios/stackedInputs.ts`), from each frame as the sandbox
  writes it (`{dataType, data}`, so a frame with no rows is a table still and a
  GeoDataFrame's rows leave its geometry out) or, for such a spec only, an input that
  is a value (`readGrammarInput`'s `values`; a `float` written as null is NaN). Which
  input a frame came in on is the graph's to say, not the bundle's: the labels are one
  per wired circle, and with one circle wired every frame and value that arrived is
  its own, one entry that a tuple or several layers make a refusal. The `input_<k>`
  datasets are read as before, geometry included where a view draws it. A refusal is
  an `emptyReason` the node shows. `useVega` takes the labels as `inputLabels`, stacks
  again on every compile and every new input, and judges an empty render over the
  stacked rows. A selection that covers the first input's rows (a Data Pool's echo, a
  direct link) flags them in `inputs` too (`__input__` 0), and `setInteracted` skips a
  dataset the view lacks: vega-lite builds only the datasets a spec reads, and vega
  throws for any other. Its twins in Python are `stack_inputs` and `input_rows`
  (`inputRows`, one input's own rows) in `utk_curio/sandbox/util/scenario_stack.py`,
  which read a GeoDataFrame without its geometry and which an exported notebook's
  chart cell imports (`NotebookConvertor.ts`, with the boxes at `dataflow.scenarios`;
  the cell writes the spec as a Python literal). `stackedInputs.cases.json` pins both,
  for Jest and for `test_scenario_inputs.py`.
- The scenario chips are references (`utils/references/codeReferences.ts`, twin
  `execution/code_references.py`): `[!! scenario colors !!]` writes
  `{"domain": [names], "range": [colors]}`, `scenarioScale` over `scaleLabels`, `[!!
  scenario text_colors !!]` the same range in `tableTextColor` shades, `[!! scenario
  order !!]` the names, and `[!! scenario input_1 !!]` input_1's color in that scale.
  With no input from a box (`anyFromABox`), the two scales are `{"domain": [names]}`,
  so the grammar's own palette colors the names. They read the
  label each `InputScope` carries (`scenario`), which `hook/useInputScope.ts` adds from
  the live graph, the notebook export from the saved one and `WorkflowSpec.node_code`
  from the spec, so the canvas, `NotebookConvertor.ts`, a server run and the agents'
  `_resolved_document` write one spec (`scenarioChips.cases.json`, read by Jest and
  `test_scenario_chips.py`). The form is a kind word and a space, as `selection picked`
  is: a widget's name has no space, and `input_1.scenario_color` would be a column of
  input_1. `[!! inputs.<field> !!]` names a field of `inputs`, written as a column
  chip is, and `[!! inputs !!]` the dataset itself (kind `dataset`), written as its
  name, `INPUTS_DATASET` (`STACKED_DATASET` in the twin), in any JSON document, an
  Autark spec's too. A chip in
  Python or JavaScript, a list chip inside quotes, an input with no edge or with no
  label, and the dataset chip on a node with no input are refused, and
  `renumberInputReferences` moves an input's chip with its circle.
  `codeReferences.cases.json` pins both resolvers. With no dataflow to resolve them
  over, the agents' check reads each as a value of its shape, the dataset chip as its
  name over at least one stand-in input, and reports a refused one in its own words
  (`with_stand_in_chips`). No widget takes the name `inputs`, as none takes
  `input_<k>`: `INPUT_NAME_ONLY_PATTERN` (`widgetModel.ts`), its twin
  `INPUT_NAME_ONLY_RE` with `widget_name_problem`, and the widget name's `not` in
  `docs/schemas/node-package.v4.json`, which every full widget check reads (the
  Widgets tab, a package manifest, the agents' widgets). `normalizeWidgets` keeps a
  saved widget of that name, so it can be deleted, while `[!! inputs !!]` names the
  dataset.
- A reader of a spec's shape parses it before its chips are resolved with each chip
  standing on its own held by a string of itself (`withChipPlaceholders`, twin
  `with_chip_placeholders`): `classifyAutkSpecString` (`utils/autkSpecKind.ts`), which
  decides whether an Autark node draws from its input on the canvas and is a
  dashboard's pass-through (`dashboardLayout.ts`), the Autark node's body (whether
  its document needs an input, what a data run on the server loaded,
  `autkGrammarBehavior.tsx`), and its twins
  `execution/autk_spec_kind.py` (a run's plan) and `projects/dashboard_payload.py`.
  `autkSpecKind.cases.json` pins both. A chip that writes one text, an input's
  scenario color, the dataset `inputs` or a field of it, is inserted quoted where JSON
  wants a value (`insertReference` in `monacoCodeReferences.ts`), so the spec stays
  JSON.
- The header above a code or grammar editor, `ReferenceStrip` in
  `components/editing/widgets/WidgetTag.tsx`, lists every chip the node can use,
  whatever its code or spec uses: it reads the editor's language, the grammar
  `NodeEditor` resolves the spec in (`VEGA_LITE` for the built-in node and any template
  whose `grammarId` says so), the node's inputs with their labels (`useInputScope`), its
  widgets and selection tags, and the dataflow's shared tags, never its code, so
  built-in and package nodes of one grammar get the same header. It is one row of
  categories, Inputs, Scenarios, Widgets, Selections and Shared, each with its count and
  only when it has chips. They start closed, a click opens a category's chips under the
  row and closes the one open, and `stripCategories.ts` keeps the open one per node id
  outside React, so a tab switch or a remount keeps it; `ProjectLoader` closes them all
  when another dataflow opens (`closeEveryCategory`). On the canvas the header takes at most half of its
  editor's height (`.strip` in `WidgetTags.module.css`), and the open chips scroll inside
  it with the shared thin scrollbar; in a notebook cell it is as tall as its chips.
  Inputs, `InputsChips`, is a line per input in circle order, and in a Vega-Lite spec
  with an input the line of `inputs`, whose tag drags `[!! inputs !!]` and whose list is
  `stackedFields` (the three the stacking adds, then the inputs' columns, leaving out a
  GeoDataFrame's geometry and every input that carries layers). A line holds its
  expander, its tag and what its input holds: `aboutInput` names where the input comes
  from, the box its node is in, else its label (`resolveNodeDisplayLabel`, the kind its
  node's header shows), then `heldBy` counts its columns, layers or tuple's values
  (`InputScope.tuple`); the line of `inputs` names the inputs it stacks and counts its
  fields (`aboutStacked`). An open list comes right under its line, never in it: a
  layered input's is one grid of a line per layer. `stripCategories.ts` keeps the open
  lists per node id beside the categories, each by the edge that feeds its input
  (`InputScope.edge`), which keeps its id when the circles renumber, so a list never
  opens on another input; and Inputs, open, asks for the columns not read yet of every
  input (`onLoadColumns`). Scenarios shows in a spec whose inputs' labels are all known
  and one comes from a box: in Vega-Lite, the swatches of `scenarioColorScale`, which
  drag `scenario colors`, then **text colors** and **order**; in Vega-Lite and Autark, a
  tag per input, which drags its `scenario input_<k>` chip in `scenarioInputColor`. Each
  drags as `SCENARIO_REF_MIME`. Both helpers are what `scenarioValue` writes, so a swatch
  shows the color its chip writes. Code shows neither the `inputs` tag nor Scenarios.
  `monacoCodeReferences.ts` draws the chips lilac and says what each writes on hover.
  On a node fed from no box, the hover says that no input of the node comes from a
  box, and what the chip writes there: for a scale the names alone, in the grammar's
  own colors; for **order** the names of the nodes its inputs come from; for an input's
  chip its gray.
- A change to any label's id, name, color or rank draws a chart again when what it
  draws moves: `NodeEditor.tsx` hands `applyGrammar` the spec it resolved with a
  `GrammarRedraw` (`registry/types.ts`), which writes the same code again in the same
  scope with the new labels, and `vegaBehavior.ts` keys its redraw on that spec and,
  for one that reads `inputs`, on the ids and names its rows carry, a box drawn around
  a feeder among them: `handleCompileGrammar` with `recordsProvenance` and
  `forwardsInput` off for that draw, so no version and no hand-off. It also sets
  `keepsSelection`, and `useVega` puts a selection made in the chart back in the new
  view (`carriedSelections` and `withMovedIds` in `vegaSelects.ts`), leaving what the
  flow holds as it is. One redraw runs at a time, then the last labels if they moved
  meanwhile: a color dragged through the picker is written at every step, and each
  redraw takes the selection from the view the one before it built. It does not
  redraw during a run, which draws the chart itself.
- A map draws its layers as its document writes them, its chips resolved before the
  run like any other: a layer writes `"color": "[!! scenario input_1 !!]"` to take its
  input's box's color, which it takes anew at its next run. The routing example's two
  routes do, the only shipped layers that drew in a box's color when Curio recolored
  them unasked (`shippedScenarioLayers.test.ts`).

### Comparing scenarios

A dataflow compares its scenarios with ordinary nodes outside the boxes, each
scenario's outcome on a circle of its own:

- A chart is a Vega-Lite node whose spec reads `[!! inputs !!]`
  ([Scenarios in charts and maps](#scenarios-in-charts-and-maps)).
- The Scout package (`packages/curio.scout@1`) holds fifteen Vega-Lite templates
  that compare scenarios. Each names `behavior: vega` and `grammarId: vega-lite`,
  takes `[1,n]` on its input port, a circle per scenario, and its `.vl.json` starter
  is the node's whole content (`starterIsContent`). The starter reads
  `"data": {"name": "[!! inputs !!]"}`, so the node gets its inputs stacked
  ([Scenarios in charts and maps](#scenarios-in-charts-and-maps)), writes the scale
  and the order of `scenario_name` through its scenario chips (Table and Stacked bars
  with totals, whose text marks color by scenario, in `scenario text_colors`), and
  reads the columns it plots from widgets through chips (`"field": "[!! y !!]"`).
  Bars, Grouped bars, Lines, Pie and Lollipops write Combine as the measure's
  Vega-Lite aggregate (`"aggregate": "[!! combine !!]"`), and the Table writes its
  list of columns where a list stands (`"fold": [!! columns !!]`), so a starter is
  JSON once its chips are written.
- A template that names `grammarId: vega-lite` is a Vega-Lite node for every rule
  keyed on the node's kind. On the canvas, `isVegaLiteNodeType`
  (`registry/vegaLiteNodes.ts`) decides drawing from a restored input
  (`UniversalNode.tsx`), `isPassThroughNode`, `isNonProducingNodeType`,
  `notebookOutputBox`, `selectionViewsOf` and the notebook export. In the backend,
  `draws_with_vega_lite` (`projects/template_grammars.py`, which reads the
  account's store, the package catalog, then the shipped packages) decides `passes_through`
  (`projects/dashboard_payload.py`, which `parts.is_pass_through` calls),
  `node_role` (also from the run's roster) and `_is_sink_node_type`, beside the
  template's declared behavior
  ([Built-in nodes by their declared behavior](#built-in-nodes-by-their-declared-behavior)).
  The automatic Vega-Lite and Autark tags read a template's grammar from the
  account's store too ([A dataflow's tags and data types](#a-dataflows-tags-and-data-types)).
- The difference of two rasters is a Raster Calculator's,
  `raster_calculate("subtract", [input_1, input_0], output_file=curio_output_file)`,
  with `absolute=True` for its size ([Raster algebra](#raster-algebra)), and the
  difference of two tables or layers a Python node's, which joins their rows on a
  key column. An Autark node after either draws it on a map.

### Editing features

The Map Editor node (type `curio.builtin/edit-features`) is a Python code node
whose code is its only state: one call of `curio_edit_features`
(`utk_curio/sandbox/util/feature_edits.py`), seeded in the in-process namespace
(`worker._globals_cache`) and the isolated one (`zygote.build_namespace_template`).

- `src/utils/editFeatures/editFeatures.ts` writes the call from the node's edits
  (`editFeaturesCode`) and reads it back (`readEditFeaturesCode`, through
  `pyLiteral.ts`); Jest and pytest share `editFeaturesCode.cases.json`. Code of
  another shape is never rewritten: the body says why it cannot read it and
  offers no actions, and a run still runs it.
- `components/editFeatures/EditFeaturesBody.tsx` reads the edits from the code on
  every render, and each change writes a new code through
  `adapters/node/editFeaturesBehavior.tsx`, which marks the dataflow dirty, marks
  the node and the nodes below it that ran stale (`autoRunTargets`), and adds an
  entry to the node's history (`nodeEditProv`). Undo and Redo put back an entry's
  code and add none. Commit edits calls `runDownstream` for the node.
- The data edge carries the edits. An Autark map a Map Editor node feeds draws that
  node's input with the edits its code holds (`mapEditsPreview.ts`, applied by
  `applyEdits.ts`, the twin of the run's `_edit_fc`), keeps its view, files no
  run for that draw, and hands on what it was fed: the node's last run.
- The interaction edge carries selections, as between two views. A pick on the
  linked map (`MapEditOverlay`) is the map's own selection, sent as autk-map's
  pick is (`sendOwnSelection`), so a draw that is not an edit's preview says it
  is gone. `useInteractions` routes it to the node, matched by the layer's id
  column (`mapEditSelection.ts`, `matchSelections`); what the node picks, or a
  rule matches, goes back the same way, and the map lights it with autk-map's
  own highlight. autk-map highlights its picking layer only, so while an action
  is open the layer it works on is that layer (`showForEdits` in
  `autkMapState.ts`). Nothing is outlined over the map for a pick.
  `mapEditBus.ts` lends the map only the drawing tools: the layer worked on, the
  mode and the shape being drawn. Nothing is drawn over the map either:
  `MapEditOverlay` hears the pointer and holds the tip, and the tools are layers
  of the map itself (`mapEditLayers.ts`), loaded through autk-map's
  `loadCollection` and drawn in its highlight: the shape being drawn and its
  corners, a shape waiting to be added, and a feature being reshaped or moved
  with its corners and midpoints, which a press takes where the map shows them.
  A feature of several rows, as an OSM building of several parts is (one row
  per part, each with its building's `building_id` and its own `osm_id`), shows
  every part's corners, each tagged with its row. The bus hands the node each
  row a gesture changes (`onReshape`), and the node writes an edit for each:
  by `ids` for a feature of one row, else by `where`, the layer's key and the
  part's own `osm_id` (`featureParts.ts`), so the parts a gesture leaves keep
  their shapes. A move writes an edit for every part, in one change; a part
  drawn joins the part the pick was clicked on. A feature whose rows no
  `osm_id` tells apart keeps its shape: its tools are off.
  autk-map draws its buildings over every flat layer, so that feature is
  skipped in its own layer meanwhile, at the positions the map's node
  registers (`registerEditMap`). The tool layers are never kept across a
  redraw, hidden by Show only this layer or picked on. The node edits
  on the maps it feeds and is linked to (`linkedMaps` in `mapLayerEdits.ts`), and
  `plan_topology` allows its interaction edge only to such a map.
- Fed by several nodes, the code hands the step every circle (`by_input=True`),
  and the step names each unnamed layer after its circle, `input_<k>`, as the
  map does.
- Rules (`where`) and `expr` edits are one expression language written twice,
  `edit_expr.py` for runs and `editExpr.ts` for the body, neither through
  `eval`; both read `editExpr.cases.json`.
- `edit_features` matches features by their id column, never by position, edits
  an Autark node's GeoJSON layers in place and a table as a table, and hands on
  every other feature, property and layer as it came. In-process, an Autark
  node's layers reach it as GeoDataFrames that keep `layerName` and `layerType`
  in their `metadata` (`worker._keep_layer_identity`); the isolated child gets
  the envelope itself.
- `utk_curio/sandbox/util/feature_edits_code.py` is the node's reader ported to
  Python line for line (`read_edit_features_code`, `edit_problem`,
  `new_layer_problem`, `read_call_args` for the literals), never through `ast`
  or `eval`. A reason shows a value as JavaScript writes it (`js_values.py`), and
  `edit_expr.py` refuses an expression in `editExpr.ts`'s words, so both readers
  refuse in one sentence: pytest and Jest compare every refused case of
  `editFeaturesCode.cases.json` whole.
- Agents are held to that reader (`agents/domain/map_edits.py`), keyed by the
  template's `behavior`, `edit-features`, read from the account's copy of the
  template as a run finds the node's package (`packages/application/node_templates.py`),
  else from the catalog's. The `node.create` and `node.content.write` mints refuse
  code it refuses. Solve's verified loop fails a round on it before the sandbox
  (`_map_edits_gate`), and on the lines of a run that name ids no feature has
  (`_made_up_ids_check`, `feature_edits.UNKNOWN_IDS_LINE`), read from the
  target's whole output (`run_through_node(keep_stdout=True)`, kept out of the
  streamed `nodes`). The unverified Solve refuses it too. Code the node holds
  already is the user's and is never refused. Solve makes edits in an empty
  Map Editor node only when its goal names them (`goal_names_edits`); otherwise
  a blank one gets the code the node writes for itself when dropped
  (`new_node_code`), persisted with the wave and never handed to the canvas as
  a change. A node's context carries each Map Editor neighbour's call, capped
  (`mapEditsCall`).
- An agent's applied change to a node whose code is its state goes through the
  node's own writer (`utils/nodeCodeWriters.ts`): `applyNodeContent` hands a Map
  Editor node the code and the name of the agent that wrote it, which the
  apply's `appliedContent.agent` and Solve's `node_result.agent` carry, and the
  entry the writer files in the node's history is named after that agent.
- An agent's applied change to a node's settings (`node.settings.write`, see
  [Dataflow plans](#dataflow-plans)) goes through the node's own setters the
  same way (`utils/nodeSettingsWriters.ts`), registered by node id and setting
  while the node is mounted: the Data Pool's, the Simple View's and the Spatial
  Join's behaviors register the setter their selects pick through, `NodeEditor`
  the one its Widgets tab gives a value through (only with a Widgets tab), and
  the Parameter node its own. `applyNodeSettings` hands each setting to its
  setter, so the pool resolves its selections again, the join joins again, and
  a widget's new value marks its node stale, leaves the dataflow Unsaved and
  asks for an automatic run. A setting no mounted setter takes goes into the
  node's data through `updateDataNode`, as a load of its metadata puts it
  there, and a widget's value made there still marks what reads it stale. It
  files no Provenance entry: an entry holds code, so putting one back could
  not put back a setting.
- Agents learn the call from `knowledge/map-edits.md` in the base entry, which
  the preamble includes: its edits and their fields, its keywords, and the words
  a goal names edits by. `test_map_edits_page.py` compares the page with the
  reader's tables (`EDIT_OPS`, `EDIT_FIELDS`, `KEYWORDS`) and with
  `map_edits.EDIT_WORDS`, and reads its example call with the node's reader.

### Notes

The Note node (`curio.builtin/note`) has no port and no code, so a run forwards it
(its `note` behavior is in `_FORWARD_BEHAVIORS`, `execution/run_plan.py`) and Run All counts it done at once
(`disablePlay`). It holds what an agent's note holds: the title in `data.title`, the
text in `data.code` (the spec's `content`) and the color in
`data.appearance.backgroundColor`.

- `adapters/node/noteBehavior.tsx` hands `components/notes/NoteBody.tsx` the node.
  The body draws the note, and its form writes all three through `updateDataNode`;
  neither shows on the dashboard or on a read-only canvas (`useSharedView`).
- `components/notes/NoteMarkdown.tsx` draws the text with react-markdown: no raw
  HTML (`skipHtml`), an element allowlist, URLs kept only when https (`httpsOnly`),
  links in a new tab with the arrow, and an image as its alt text.
- `utils/noteColors.ts` derives the background, ink and link color the way
  the rules of `packages/domain/node_appearance.py` do, from the palette and
  inks of `src/contracts/noteColors.json`, which `packages/application/note_palette.py`
  reads and hands those rules (see [Shared Constants](#shared-constants)).
- A note template is a template with a behavior whose content kind is `note`
  (`is_note_template` in `packages/application/templates.py`): no editor, no
  input, no widgets. `presentation_templates`, the roster's `presentation` flag and
  an enlisted package's notes read it, so the Researcher's notes find the Note
  rather than a Data Pool or a Parameter node.

### Tooltips

Every hover in Curio shows one tooltip, drawn by `components/tooltip/TooltipLayer.tsx`
(mounted once in `index.tsx`) in a portal on `document.body`. It sits outside the
canvas's viewport, so it is the same size at every zoom and no node clips it.

- An element names its tooltip in `data-tooltip`, where it would have written a
  `title`, which draws the browser's own; a control whose only name was its title
  has an `aria-label` too. The layer listens on the document and shows the tooltip of
  the nearest `[data-tooltip]` under the pointer or the keyboard's focus; while it
  shows, the element's `aria-describedby` names it, or, for the keyboard's focus,
  the focused control's. `noOtherTooltips.test.ts` fails on a `title` on an element,
  on a component that hands it to one (React Flow's `Handle`, `FontAwesomeIcon`, any
  MUI component), on an `OverlayTrigger` or on a Monaco `hoverMessage` in `src/`.
- A tooltip with more than words (a list, a preview) comes from
  `useTooltipContent(node)`, whose props, `data-tooltip-content`, go on the element.
- `data-tooltip-side` says where it opens: `top`, the default, above the element and
  centered on it, or below when there is no room; `right`, for the tool rail's
  palette rows; `pointer`, for a chart's marks. `placeTooltip` (`tooltipPlacement.ts`)
  keeps it in the window, 6 px from its target. An open tooltip is placed again
  whenever its size changes (a preview growing as its read comes back), so it never
  covers its target.
- `tooltipStore.ts` holds the timing: the tooltip shows 400 ms after the pointer
  rests, at once when another closed less than 600 ms before, and hides 100 ms after
  the pointer leaves. The pointer may cross over onto the tooltip, and leaving the
  tooltip hides it the same way, whoever opened it; one at the pointer (a chart's)
  lets the pointer through instead. A held touch shows it after 500 ms, the
  keyboard's focus at once. A press hides it, and it stays off while the pointer
  stays on that target (a chart's next mark asks again); a wheel, a drag, Escape or
  the window losing focus hide it, and so does a scroll of what holds the element it
  is placed beside. A flow hides it when its view moves (`useViewportMotionHint`).
  `setTooltipTimings` sets the delays and `resetTooltipStore` starts it afresh, for
  tests.
- Monaco's own hover is off in every editor (`hover: { enabled: false }`).
  `useEditorTooltip` shows, in the Curio tooltip, the markers' messages first, then
  a chip's preview or, in JavaScript, the TypeScript worker's quick info for the
  word under the pointer. It is placed from where Monaco draws what it describes (a
  chip's name, a word), so a redraw of the line keeps it in place. A redraw as the
  pointer lands, which Monaco reports as a leave, keeps it coming too. It hides when
  the editor's text scrolls, not when only the size Monaco can scroll changes.
  Cmd+K Cmd+I (Ctrl on Windows and Linux) shows it at the caret: an action of each
  editor, so it works in the one with the focus.
- A chip's hover, its tag's in the header and its chip's in an editor, is one
  `ChipPreview` (`components/editing/widgets/ChipPreview.tsx`) of what the chip holds:
  an input's source, size and first rows, a column's values and range, the stacked
  `inputs`, a widget's or a Parameter's value, a selection's rows, the scenario
  colors. It reads the node's preview source (`chipPreviewSource.ts`), which
  `NodeEditor` builds from `useInputScope` (each input's `readInputPreview`, the same
  `/get-preview` read as the header's columns), the Parameter nodes and the selection
  tags' views. Its tooltip content, `ChipPreviewTip`, asks the source to read what it
  shows as it mounts, so only a tooltip that shows reads, and it follows the source
  as the read comes back.
- A Vega-Lite chart's tooltip handler is `vegaTooltipHandler` (`vegaTooltip.ts`): it
  writes the hovered mark's fields, as Vega's own handler words them, in the chart
  element's `data-tooltip`, and the tooltip shows at the pointer.
- An e2e capture hides an open tooltip unless the test passes `keep_tooltip`
  (`test_frontend/utils/images.py`).

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
  model.curio.ddrnet23-slim@1/  # model package: its weights and one Python code template
    manifest.json               # kind "model", with the model block
    models/ddrnet23_slim.onnx   # the weights, and the graph's external data beside them
    LICENSE                     # the weights' license
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
| Grammar (Autark) | `autk-grammar`, one node whose UrbanSpec unifies OSM/PBF loading, GPU `compute`, and `map` + `plot` rendering |
| Chart/table visualization | `vis-vega`, `vis-simple` (a table, or a card per row when the frame carries images) |

Third-party packages (or first-party optional ones, like `curio.example-ui@1`) install via the **catalog drawer** in the canvas, which copies the package directory into the user's store at `.curio/users/<user>/packages/`.

### A dataflow's tags and data types

The Projects rail and the canvas's title chips file a dataflow under tags and data types that [`projects/categories.py`](../utk_curio/backend/app/projects/categories.py) `derive` computes on every read and never stores. It has two sources, and neither names a package, model or dataset:

- [`projects/category_rules.json`](../utk_curio/backend/app/projects/category_rules.json) holds what a dataflow shows by itself, as data: the modules its code imports, the file extensions and data URIs it names, the `grammarId` each node's template draws with (and keys of a grammar node's document, such as Autark's `compute`), model types, dataset formats and collection kinds, and the display order.
- A `ManifestLookup`, one per request, reads what the manifests declare in `dataflowCategories`, and the core fields the table reads: a node's package and template, and the model package a `curio_load_model` call names (`TemplateGrammars`, [`projects/template_grammars.py`](../utk_curio/backend/app/projects/template_grammars.py)), and a dataset (`DatasetKinds`). It reads each manifest's raw JSON once, in the account's store and in the catalog, and unions what the two copies declare, since a store copy dates from when the account added it; a grammar, a model type, a format and a collection kind are the first copy's that has one. A node type or model id without a major takes the major the dataflow's lockfile (`dataflow.packages`) names, else the highest. Paths go through `dir_name_from_node_type` and `dir_name_from_model_ref`, so a legacy type with no package matches nothing. Without a lookup, `derive` reads the committed `packages/` and `datasets/`.

The table's names come first, in its `displayOrder`; any other declared name follows, sorted ignoring case, so a new name shows on the rail with no frontend change. Names merge ignoring case, keeping the table's spelling, and a declaration read off a manifest skips a value of the wrong type (`declared_dataflow_categories`, beside the parsers' `clean_dataflow_categories` in `packages/domain/dataflow_categories.py`).

A dataflow's source on the rail (Use cases, Examples, Tests) comes from its project id, never from its file. A shipped dataflow's id is derived from its key (`shipped_sources` in `projects/seed.py`), and [`projects/shipped.py`](../utk_curio/backend/app/projects/shipped.py) gives each key its source: a dataflow in `docs/examples/dataflows/` is a test, and a numbered one in `docs/examples/` is an example unless the use-case index beside it, `docs/examples/use-cases.json`, names its key under `useCases`. The index is not a dataflow and ships with the dataflows, and a copy of a use case under another id is the account's own.

### Built-in nodes by their declared behavior

Curio knows what a node is by what its template declares, never by the name of its type: a package template named like a built-in one is not taken for it, and a template that declares a built-in's behavior is treated as that built-in is, a template of a package in the account's own store included. The backend reads a node's template with `TemplateGrammars` ([`projects/template_grammars.py`](../utk_curio/backend/app/projects/template_grammars.py)): its `behavior`, `grammarId` and flags (`TEMPLATE_FLAGS`, such as `loadsDataset`). A flag counts when either copy of the package declares it, as the agents read flags (`packages.template_flags`). A node type is read only through `dir_name_from_node_type`, so a type of any other shape than `<package id>/<template id>[@<major>]` reads nothing. A caller builds one `TemplateGrammars.for_account(user_key)` per request for the account whose dataflow it reads (the owner, for a dashboard): that account's store, the package catalog, then the packages Curio ships, so a package only the account's store holds counts for that account alone, and the built-in nodes are known wherever `--packages-root` moves the catalog. The canvas reads the same declarations off its registered descriptors ([`src/registry/declaredNodes.ts`](../utk_curio/frontend/urban-workflows/src/registry/declaredNodes.ts), whose descriptors keep their template's `behavior` and `loadsDataset`, from the account's package listing, where a template's flags include those the catalog's copy declares). A type whose template declares no behavior, or that nothing registers, is a built-in node by its id; whether a registered template loads data is its `loadsDataset` flag alone. **Save as package node** copies a template's `loadsDataset` into the template it writes. The agents read flags from the project's template roster and the catalog's copy, and the Data Catalog's lineage, which spans every dataflow of the account, from `TemplateGrammars`; `test_declared_behaviors.py` runs every shipped template through both. `registry/declaredNodes.cases.json` holds the cases both sides run (`declaredNodesCases.test.ts`, `test_declared_node_cases.py`).

| Rule | Backend | Canvas | What the template declares |
|---|---|---|---|
| A dashboard or a scenario walks through the node | `passes_through` in `projects/dashboard_payload.py`, which `parts.is_pass_through` calls | `isPassThroughNode` in `utils/dashboardLayout.ts` | the `vega`, `simple-vis` or `data-pool` behavior, a `grammarId` of `vega-lite`, or the `autk-grammar` behavior with a spec that draws |
| A save keeps no output of the node's own | `_is_sink_node_type` in `projects/services.py` | `isNonProducingNodeType` in `utils/saveOutputDataset.ts` | the `vega` or `simple-vis` behavior, or a `grammarId` of `vega-lite` |
| A node loads the dataset it names: the nodes after it are the dataset's consumers, and a dataset dropped on it applies to it | `loads_data` in `datasets/application/export.py` | `loadsData`, read by `datasetLineageResolver.ts` and `canApplyDatasetToNode` | the `loadsDataset` flag, which the agents read too (`source_grounding.loads_dataset`); the legacy type `DATA_LOADING` too |
| A run on the server forwards the node | `node_role` in `execution/run_plan.py` | | a pass-through, or the `data-export`, `parameter` or `note` behavior |

### A dataflow's thumbnail

The Projects page, the Scenario Catalog and the provenance drawer draw a dataflow as plain boxes ([`components/DataflowThumbnail.tsx`](../utk_curio/frontend/urban-workflows/src/components/DataflowThumbnail.tsx)), each with a bar in the color of its node's category (`colorForCategory` in `constants/nodeCategoryPalette.ts`), or grey for a node with none. The palette maps categories to colors and names no node type.

- A project summary's `graph_preview` (`_extract_graph_preview` in `projects/services.py`) gives each node its id, type, position, size and the `category` its template declares, read through the request's `ManifestLookup` (`template_categories` in `projects/categories.py`), so a package in the account's store counts as one in the catalog does. A node type no manifest holds gets none. The Scenario Catalog's listing and a scenario's details draw the same preview.
- A preview built in the browser gives each node its registered descriptor's category (`utils/graphPreviewCategories.ts`): the Scenario Catalog drawer's In project tab (`liveGraphPreview`) and each version of a dataflow (`TrillGenerator`). The provenance drawer draws a version with the category each node type's descriptor has then, else the one recorded with the version.

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

**1. Built-in (ships with Curio's main bundle).** [`builtinBehaviors.ts`](../utk_curio/frontend/urban-workflows/src/registry/builtinBehaviors.ts) calls `registerBehavior(...)` at import time for the hooks every install needs: `useCodeNodeBehavior`, `useVegaBehavior`, `useAutkGrammarBehavior`, `useDataPoolBehavior`, `useSpatialJoinBehavior`, and so on. Its keys are the ones `curio.builtin@1`'s templates name, no more ([`builtinBehaviors.test.ts`](../utk_curio/frontend/urban-workflows/src/tests/registry/builtinBehaviors.test.ts) scans for it). A package's template may name any of them, most often `code` beside a `source` starter ([Starter Routes](#starter-routes)); a package whose node needs a hook of its own ships it, as below.

**2. Per-package (dynamic, loaded at boot).** A package whose templates need custom UI can declare `"behaviorScript": "scripts/behaviors.js"` in its manifest and ship a pre-built JS bundle alongside the manifest. At boot, [`packagesClient.ts::loadPackageBehaviorScripts`](../utk_curio/frontend/urban-workflows/src/registry/packagesClient.ts) fetches each installed package's bundle with the user's Bearer token and injects the response body as an inline `<script>` *before* descriptors are built. The bundle's top-level side-effect calls `window.curio.registerBehavior(...)` for each hook it ships.

**Worked example: `curio.example-ui@1`** ships one custom behavior:

| Behavior key | Hook | Purpose |
|---|---|---|
| `column-filter` | `useColumnFilterBehavior` | Column, comparison and threshold controls in the node body; sends the matching rows downstream as a DATAFRAME |

The hook sits in `packages/curio.example-ui@1/sources/columnFilterBehavior.tsx` and `sources/index.tsx` registers it; webpack bundles them into `scripts/behaviors.js` (UMD + React/ReactFlow externalized to share Curio's instances at runtime), and the manifest's `behavior` field maps the template to it. The catalog install copies the package directory; boot loads the bundle; the user gets a custom-rendered node without rebuilding Curio. See [EXTENDING.md §4](EXTENDING.md) for the recipe.

**Icons.** A template's `iconRef` names any Font Awesome solid or brands icon, `"fa-solid:<name>"` or `"fa-brands:<name>"`, with no change to Curio. [`src/registry/iconRegistry.ts`](../utk_curio/frontend/urban-workflows/src/registry/iconRegistry.ts) bundles the icons `curio.builtin@1`'s templates name. `packagesClient.ts::loadInstalledPackages` loads any other one while it loads the behavior scripts, before it builds descriptors, so a palette tile never draws a placeholder first: a dynamic `import()` of `@fortawesome/free-solid-svg-icons/<faName>` (or the brands pack), which webpack splits into one chunk per icon (`webpack.config.js` aliases each pack to its folder, so webpack can list it). The icon chunks ship as webpack writes them, without minifying or a source map ([`webpack/iconChunks.js`](../utk_curio/frontend/urban-workflows/webpack/iconChunks.js)). A ref Font Awesome does not have falls back to `faCube`, so a missing icon is visible but not fatal.

#### Adding a built-in behavior or grammar adapter

A package ships its own behavior as a `behaviorScript` bundle (see [Authoring nodes](AUTHORING-NODES.md), Tier 2). The recipes below are for the other case: changing Curio itself, so every install has the behavior or adapter before any package loads.

**A behavior hook.** The built-ins are registered in [`src/registry/builtinBehaviors.ts`](../utk_curio/frontend/urban-workflows/src/registry/builtinBehaviors.ts).

1. Implement the hook under [`src/adapters/node/`](../utk_curio/frontend/urban-workflows/src/adapters/node/), conforming to `NodeBehaviorHook` in [`src/registry/types.ts`](../utk_curio/frontend/urban-workflows/src/registry/types.ts). `useCodeNodeBehavior` and `useVegaBehavior` are the references.
2. Register it in `builtinBehaviors.ts`: `registerBehavior("my-key", useMyHook);`
3. Reference it from a manifest: `"behavior": "my-key"` on each kind that wants it.

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
  interactionsCallback?: Function; // report the node's selection to FlowProvider
  propagationCallback?: Function;  // a Data Pool hands its row flags to the pools linked to it
  interactions?: IInteraction[];
  propagation?: any;
}
```

#### The node card

`NodeContainer` (`src/components/styles.tsx`) draws a node the same way on the canvas and as a notebook cell; only a dashboard tile differs.

- **Surface.** `getNodeContainerStyles` decides the whole border: on the canvas a white card with a `var(--curio-border)` hairline, radius 8, a soft shadow (`--curio-shadow-browse-card-raised`) and the kind's 4px stripe; a notebook cell drops the hairline and the shadow. A selected node gets a 2px ring in its kind's color. A suggestion keeps its dashed border.
- **Header** (`.curio-node-header`). Play first, then the title (`EditableNodeHeaderLabel`), the package and dataset pills, and the run status; `NodeRunControls` draws Play, the status and the Save output toggle, each in its place. The rest are the tools (`.curio-node-tools`): the editor's tabs, which `NodeEditor` renders through a portal into the slot `nodeHeaderSlot` provides (the provenance pill among them opens the provenance drawer rather than a tab), Save output, the gear, about, pin, save template and, on the canvas, minimize, then delete last (`NodeDeleteTool`, only where `graphEditGates` lets the viewer delete, so not on a read-only canvas). They show only while the node is hovered, selected or focused (`Node.css`). Nothing sits under the body, so the editor's panes fill the node.
- **Editors.** `nodeEditorLook` gives a code or spec editor its gray input box (`.curio-node-input`) and Monaco options with no line numbers, gutter, folding, line highlight or overview ruler. A code node's output has no rule or fill. A dashboard tile keeps Monaco's own look.
- **Canvas only.** The resize handle at the bottom-right corner (`NodeResizeHandle`), minimizing to a chip, the node's fixed size and the cardinality markers at its edges. The chip (`.curio-node-chip`) shows the node's icon, then the header's own title (`EditableNodeHeaderLabel`, not editable: one line, cut with an ellipsis, the whole title as its tooltip). Its size is fixed, `MINIMIZED_NODE_WIDTH` x `MINIMIZED_NODE_HEIGHT` in `constants.ts`, never sized to the title, so `utils/nodeBoxSize.ts` mirrors it without measuring text; a load's `deoverlapNodes` measures chips through it, and moves apart chips saved closer than that. A read-only canvas (`useSharedView`, the rule `MainCanvas` and the top bar read) keeps each node at its size: no handle, nothing listening for a drag, and no browser grip under it. A double-click where a press drags the node (`isNodeDragRegion`: nothing from the target up to the node is `nodrag`) frames it with `frameNodesInView`, the framing a focus uses; editors, outputs, charts, maps and handles keep their own double-click. A read-only canvas does not drag nodes, so React Flow leaves them without its `nopan` class (no pan on a press, no zoom on a double-click); `MainCanvas` gives it to them (`keepPaneOffNodes`), and the same double-click frames the node there.

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
| `raster` | `value_str` | File path; raster data stays on disk. A raster an Autark node hands on is a `dict` (see [Referencing Upstream Data in Autark Nodes](#referencing-upstream-data-in-autark-nodes)) |

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
`schema` and its declared geometry column. Several input circles arrive as an
`outputs` bundle, one frame per circle, each recording its circle; an Autark
input that is itself a bundle of layers is expanded into them.
[`vegaInput.ts`](../utk_curio/frontend/urban-workflows/src/utils/vegaInput.ts)
turns each input into the rows of the dataset `input_<k>`, and
[`vegaDatasets.ts`](../utk_curio/frontend/urban-workflows/src/utils/vegaDatasets.ts)
decides whether they go in as the spec's own `data` (one input read by the whole
spec) or as named `datasets`;
[`autkInput.ts`](../utk_curio/frontend/urban-workflows/src/utils/autkInput.ts)
turns the frames into the tables an Autark document names. Both name an input
`input_<k>` through `inputTableName` (`src/contracts/autkGrammar.ts`). A
`DataFrame`'s geometry column is found by value in both, through
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
column roles in `starterSpec.ts`. Neither ladder fills a node that opens with a
starter its package ships (`opensWithPackageStarter`,
[`registry/packageStarter.ts`](../utk_curio/frontend/urban-workflows/src/registry/packageStarter.ts)),
so a package template whose input arrives before the starters feed still opens
with its starter and widgets. Each ladder's rules, in order, and the dtype
roles are in `src/contracts/visDefaults.json`, which the backend reads too (see
[Shared Constants](#shared-constants)). Both mark themselves errored on a failed run,
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

### Field Names in Vega-Lite Specs

Vega-Lite reads a field as a path into the row: `rain.mm` is `mm` inside `rain`,
and `a[0]` indexes `a`. So a column whose name holds a `.`, a `[` or a `]` is
written with a backslash before each (`rain\.mm`, `vegaFieldName` in
`utils/vegaFieldNames.ts`, `vega_field_name` in `code_references.py`). A name
that already holds a backslash is taken as escaped by hand and written as it
is. In a Vega-Lite chart's spec, a reference writes its names so where
Vega-Lite reads a field, and as they are everywhere else: titles, sort values,
expressions such as `datum['rain.mm']`, and the names a transform writes
(`as`).

- **Where.** The resolver reads the spec as JSON with each reference replaced by
  a mark, finds where each mark stands, and writes only then
  (`vegaFieldPlaces` in `codeReferences.ts`, `_vega_field_places` in
  `code_references.py`). A mark is the reference's number between two
  characters of Unicode's private use area that the spec's text holds neither
  as they are nor as a JSON escape, so the spec's own text takes no
  reference's place. The values of `data`, `datasets` and `usermeta` are rows
  and notes, never fields. A spec that does not read as JSON, or nests more than
  100 levels deep, its rows and notes counted, writes every name as it is: the
  depth is measured without recursion, so the browser and the runner agree on
  any spec. The field positions are the
  ones Vega-Lite's schema types as a field name, but `as`: `field` anywhere;
  in a transform, its `groupby`, `fold` and `flatten` lists, the field its own
  key names (`pivot`, `lookup`, `impute`, `stack`, `density`, `loess`,
  `regression`, `quantile`, and `extent` beside `param`), `value` beside
  `pivot`, `key` beside `impute`, `on` beside `loess` or `regression`, and a
  lookup's `from.key` and `from.fields`; a parameter's `select.fields`; an
  encoding's `aggregate.argmax` and `argmin`; and a `repeat`'s lists.
- **Who.** The canvas passes the grammar of a Vega-Lite node's spec, the
  built-in node's or a package template's (`isVegaLiteNodeType`), to
  `resolveReferences`, as the notebook export does; Solve resolves a document
  in the grammar it checks it in (`_resolved_document`).
- **Reading a field back.** Where Vega-Lite escapes a field itself (an
  aggregate, a bin transform, a condition's test), `rain.mm` draws the column
  too. So a field names a column when its text, or its text unescaped, is the
  column's name: the agents' check reads it so (`_named_column` in
  `agents/domain/document_validation.py`), and so do the canvas's geometry
  coercion (`vegaGeoSpec.ts`) and its empty-render count (`vegaUsableRows.ts`),
  through `vegaFieldColumn`. The shape the canvas injects for a geoshape names
  its geometry column escaped. A path through a column, `zone.id` beside a
  column `zone`, names none.
- **Tests.** `codeReferences.cases.json` holds the positions, read by Jest and
  pytest; `scoutDottedColumns.test.ts` draws each Scout chart over columns whose
  names hold a dot or a bracket with the vega-lite the app bundles, and expects
  the marks it draws over the same columns without one.
- **Vega-Lite's own limits.** An encoding over a column whose name holds a
  backslash draws nothing, since Vega-Lite drops the backslash when it writes
  the field again (an aggregate's `mean_<field>`). Its error bar names its
  bounds after its Y field as written, so it draws no error bar over a Y column
  whose name holds a `.` or a `[`. A title Vega-Lite writes itself shows the
  field as written, `rain\.mm`.

### Referencing Upstream Data in Autark Nodes

The `autk-grammar` node consumes upstream data differently from Python nodes: its UrbanSpec refers to data **by name**, through `dataRef` strings in `map.layerRefs[]`, `plot.dataRef` (and `plot.mapRef`), `compute[].dataRef`, and `fromFeature.layer` inside compute uniforms. Before the grammar runs, the behavior hook ([`autkGrammarBehavior.tsx`](../utk_curio/frontend/urban-workflows/src/adapters/node/autkGrammarBehavior.tsx)) reads the input once, through the path shared with the Vega-Lite node (see [Reading a Grammar Node's Input](#reading-a-grammar-nodes-input)), and hands the grammar, as named sources, the tables `tablesToLoad` in [`autkInput.ts`](../utk_curio/frontend/urban-workflows/src/utils/autkInput.ts) picks: the input's tables the document names (`documentTableRefs`), every table the document's own `data` section loads, and the surface of each OSM load a table it names is a layer of. Those surfaces come first; then the input's rasters (see **Rasters** below), its other tables as `geojson` sources in the order they arrive, and the document's own. An OSM load named `X` makes the tables `X_surface`, `X_parks`, `X_water`, `X_roads` and `X_buildings`, and `X_<set>_<type>` for its tag sets, and autk-db types its surface `surface`. So a table of type `surface` named `X_surface` is the surface of load `X`, and a table is a layer of the load whose name, with `_` after it, is the longest one that starts its own. A Discovery Catalog OpenStreetMap download's group loader keys its layers by layer (`surface`, `parks`, `water`, `roads`, `buildings`), each typed as it is named by its frame's `metadata`: a table `surface` of type `surface` is that download's surface, and its layers are the tables named and typed alike. autk-db makes the first table it loads the workspace's extent, and the first polygon table its crop layer, and clips every later table to both. A table the document does not name is not loaded, so it cuts none of the tables it draws, and a map of OSM layers is cropped to its load's query area, so no layer of the load cuts another. The empty-render verdict counts every table the input brings, so a `dataRef` that names none of them blames the document. A document that only loads data of its own does not read its input. Upstream geojson is data the browser already holds, so it stays client-side; only the spec's own authored `data` sources (OSM / PBF / CSV and the like) run in the backend sandbox. There are two cases:

**1. A frame per input, `input_<k>`.** Each input frame (e.g. a Python GeoDataFrame from a computation node, or one routed through a Data Pool) is injected as one source named after its input, `input_0`, `input_1`, ... in circle order; an input chip writes the name:

```json
"map": { "layerRefs": [{ "dataRef": "[!! input_0 !!]", "getFnv": "mean", "getFnvType": "quantitative" }] }
```

A layer chip on such an input writes the same name, whatever layer it names: one frame is that layer, as `curio_layer` reads it in code. The resolver (`isOneFrameInput` in `codeReferences.ts`, `_is_one_frame_input` in `code_references.py`) knows an input is one frame from its data type, a DataFrame or GeoDataFrame, with no layers listed, since a spec is written before the run, often before the input's columns are read. When the input's value names its frame's layer (`layerName`, as a layer a Data Pool passes on inline does), the chip must name that layer, as in code (`knownLayers`, `_known_layers`), and still writes `input_<k>`, which a one-layer input answers to (case 2). A layer chip on any other input writes the layer's name: the layer array an Autark data node hands on arrives as a `list`, and the single layer an Autark compute step hands on as a `dict`, both read by their layers' names. The same holds for a Vega-Lite spec, whose datasets are `input_<k>`. A GeoDataFrame that names its layer only in its `metadata` is named in code alone: the reference does not carry that name, so a spec reads such a frame whatever the chip names.

**2. Layer array, named layer references.** A multi-layer array (emitted by an upstream data-only `autk-grammar` node, e.g. one whose `data` block loads an OSM/PBF stack with `autoLoadLayers`) exposes each layer under its own table name, so the spec can target layers individually, with layer chips (`[!! input_0:table_osm_roads !!]`) or by name. An input holding one named layer also answers to `input_<k>`, always with its own layer. A name two inputs bring is the first input's layer; the second input's is still its `input_<k>` when it is that input's only layer, and is left out otherwise, as the node's message says:

```json
"map": { "layerRefs": [{ "dataRef": "table_osm_buildings" }, { "dataRef": "table_osm_roads" }] }
```

A source loads as the autk-db layer type its frame carries: a layer record's `type`, the envelope's `layerType`, or a geodataframe's `metadata.layerType` (`gdf.metadata`, kept in the artifact's `value_json`, sent as `X-Curio-Frame-Metadata` on the Arrow path and as `data.metadata` on the JSON path). A Discovery OpenStreetMap download's loader sets it. A `buildings` source's features get a `height` (and `min_height`) where autk-map, which reads the first height key a feature has, would read none, and where a feature has no `height` key, so a compute that reads `properties.height` reads the height the map draws (`utils/buildingHeight.ts`): a `height` of null beside `building:levels`, `building:levels` alone (3.4 m a level), or no height at all (6 m above the base). Every other feature is passed as it came, and the table keeps one feature per row.

A `DataFrame` becomes a FeatureCollection from its one geometry column; with none or several, it is refused with a reason, as is an input type the node cannot read, and the tables the document expected from it count as zero rows from upstream (`no-input-rows`, with the reason). A feature without a geometry keeps its row: autk-db refuses a row with no geometry, so it gets an empty one (a GeometryCollection with none in it), which a map draws as nothing and a plot still counts. `loadableFeatures` (`autkDataCompile.ts`) is that rule for every table Curio hands autk-db: a node's inputs, and a data section's GeoJSON sources in the sandbox and in the browser. autk-db reads a layer's kind off its first row, so a first row with no geometry trades places with the first that has one, and it stores the rows whose geometry is empty before the others. A plot reads the table as handed, so its selections go through the table's load order (`loadableSource`). A map draws a layer as autk-db exports it, which can leave rows out and keep the others in an order of its own, and autk-map draws one component for each feature with something to draw, which names its feature (`featureIndex`): each feature Curio hands autk-db for a map carries its input row (`INPUT_ROW`), read back from the export once a draw, the first time a pick or a highlight on that layer needs it (`drawnRows`), so a position always names the input's row. A map pick names the layer that picks when it is made (`pickingTableOf`): autk-map has one, the last a document marks `isPick` or one picked in its layer menu.

The names `input_<k>` are defined once, as the prefix in `src/contracts/autkGrammar.json`: `contracts.py` reads it into `INPUT_TABLE_PREFIX` and `input_table_name`, the Vega-Lite and Autark paths import `inputTableName` (`src/contracts/autkGrammar.ts`), and the preamble states it (see [Shared Constants](#shared-constants)).

**One view.** A node draws one view: one map, on the one canvas it hands autk-grammar as `targets.map`, or one plot, in the one pane it hands it as `targets.plot`. autk-grammar draws every map of a `map` list on that canvas, and draws a plot only into a pane. So a document with a map and a plot, or whose `map` or `plot` lists more than one, is refused before anything runs, the WebGPU probe included: `autkOneViewProblem` (`src/contracts/autkGrammar.ts`, the twin of `autk_one_view_problem` in `contracts.py`) gives the node's error, the sentence `autkGrammar.json` holds as `oneView` (`contracts.AUTK_ONE_VIEW`), which names the fix (each view in its own Autark node, linked with interaction edges). The error marks the node errored and reaches Solve through the node's runtime report. The agents' document check refuses such a document with the same sentence before it is written (see [The Autark Schema](#the-autark-schema)), and the preamble's lines on `map` and `plot` say it. A `map` or `plot` written as a list of one is read as that map or plot, so the layer counts, the dropped `dataRef`s, the picked layer and the plot's layer read it.

**Framing.** autk-map's flat camera starts 10,000 world units above the map's origin whatever its layers hold, and the grammar's document has no camera. Once the grammar has run, `frameMaps` ([`autkMapView.ts`](../utk_curio/frontend/urban-workflows/src/adapters/node/autkMapView.ts)) frames each map it drew (autk-grammar's `maps`, one for each `map` entry of the document, which every reader of a node's maps takes through `grammarMaps`) on the extent of the geometry its layers drew (autk-map keeps it relative to the map's origin) with the arithmetic of autk-map's terrain mode (`fitCameraToTerrainBounds`: the limiting side fills the view with 8% to spare), through the camera's own `resetCamera` and `resize`. The camera is raised by the tallest building and stays under half of its far plane. A map drawn while hidden is framed when it is first shown, and the map's R key frames it again.

**Drawing.** Maps draw on demand. autk-grammar starts each map it makes with autk-map's `draw()`, which draws one frame, then only when the map's picture changes. autk-map asks for that frame itself after every change it can observe: its camera (navigation, a resize, a window resize), its layers (loads, updates, highlights), its style and a pick. Curio asks a map for a frame with its `requestRender()` after it changes the map itself: `frameMaps` after it moves the camera, and `bleedRasterEdges` after it writes a raster's cells in place, which autk-map cannot observe. A map that nothing changes draws nothing, whether it shows, sits out of view or is hidden in a collapsed scenario. The node keeps the maps its grammar made (`trackMaps` in [`autkMapDrawing.ts`](../utk_curio/frontend/urban-workflows/src/adapters/node/autkMapDrawing.ts)), and a map nobody will see again is destroyed with autk-map's `destroy()`, which frees its GPU textures, its window listeners and its controls: the node destroys its maps when its next run replaces their canvas and when it leaves the page (a deleted node, a closed dataflow), including maps a run made after it left. The e2e captures and the map framing check read a map's pixels in the animation frame that renders the map: they call `renderMapsForReading` (`window.__curio_renderMapsForReading`), which asks every map the nodes keep for a frame and resolves inside that frame.

**Layer names and colors.** A layerRef's `title` is its layer's id in autk-map, which titles the legend with it. The grammar finds the layer of a table with `mapLayer(dataRef)`, and its highlights take the table's name, so Curio names layers by their `dataRef` everywhere. A layer's colors are the ones its document writes; one in its scenario's color writes its input's scenario chip as its `color`, resolved before the run (see [Scenarios in charts and maps](#scenarios-in-charts-and-maps)).

**Rasters.** A raster on the input is a table under the same names, read through the same path; the Vega-Lite node still refuses it. Its frame says where the raster is and is not fetched as rows: a Python node's `rasterio` dataset by its artifact (`part` for its place in a tuple), or the envelope another node handed on. [`autkRasters.ts`](../utk_curio/frontend/urban-workflows/src/adapters/node/autkRasters.ts) turns each into GeoTIFF bytes and loads it with autk-db's `loadGeoTiff` into the grammar's own database:

- The bytes of an artifact come from `GET /raster` (backend, proxied to the sandbox's `/raster`, [`sandbox/util/rasters.py`](../utk_curio/sandbox/util/rasters.py)): a GeoTIFF GDAL writes, whatever the source format (a VRT from Mosaic Rasters included), described in the `X-Curio-Raster` header (size, bands, CRS, transform, nodata). A raster over `maxCells` or `maxSide` is a 413 with its size, before anything is written. The artifact is read as `/get` reads one (`parsers.load_artifact`): a saved raster output the session-tagged store cannot serve, after a reopen under a new sign-in, comes from the copy a project load hydrated, the raster's own GeoTIFF or VRT, which `load_shared_output_file` knows by its first bytes and opens with rasterio, as the store does. A Python node reads it the same way, in process and through staging. A standalone dashboard carries these answers in its page: when the page is built, `projects/dashboard_payload.py` asks the sandbox's `/raster` for each raster an Autark map on it reads (`raster_places`, the rules of `readGrammarInput`), with the same limits, and the payload's `rasters` holds each answer by filename and `part`: the GeoTIFF in base64 with its description, or the refusal. A raster the sandbox cannot be asked for refuses the page with the 503 that says to try again. `fetchRaster` answers from it as `fetchData` answers from `outputs`, and the GeoTIFFs count toward the page's 25 MB.
- An envelope's collection is written back to GeoTIFF bytes by [`geotiffWriter.ts`](../utk_curio/frontend/urban-workflows/src/utils/raster/geotiffWriter.ts).
- [`rasterLoad.ts`](../utk_curio/frontend/urban-workflows/src/utils/raster/rasterLoad.ts) sets the parameters: `maxRasterCells` the raster's own size (up to 4096 by 4096 cells, 8192 on a side), so autk-db never resamples it; `resampleMethod: 'nearest'`; and `coordinateFormat` its EPSG CRS, since autk-db reads a raster as EPSG:4326 otherwise. A larger, rotated or unplaceable raster is refused with a sentence that names it.
- autk-grammar's data sources have no GeoTIFF, so `withRasterSources` wraps one grammar instance's data adapter to load the `curio-raster` sources and hands every other source on. It also wraps that database's `getLayer` for those tables: the map gets `getRaster`'s collection, read right after `loadGeoTiff`, at the raster's own extent (autk-db's `getLayer` gives a raster the workspace's extent once a layer with geometry has set one), plus an outline of that extent (`framedRaster`), because autk-map places a map by the geometry of the first collection it loads and a raster has none. autk-db keeps raster cells in one store for the page, keyed `autk.<table>`, so every node's `input_0` shares a key: rasters are loaded and read back one at a time across nodes (`oneRasterAtATime`).
- autk-grammar colors a raster's cells and its legend in the layer's scheme (`updateColorMap`, centered by `colorMapCenter`, reversed by `colorMapReverse`) with the layer's `transferFunction`. autk-map builds the scheme's color function once per raster and colors every cell with it (urban-toolkit/autark#118), so Curio installs autk-map from `vendor/autark/` until Autark releases that change. Before the run, `withOpaqueRasters` gives every layer of a raster table (a `curio-raster` source or a `heatmap`) the transfer function that draws every cell with a value opaque and NaN clear, under what the layer writes itself. Once the grammar has run, `bleedRasterEdges` finds each raster layer through the grammar's `mapLayer(dataRef)`, under its title if it has one, gives each clear cell its nearest colored neighbor's color (still clear) so linear sampling draws no dark seam at nodata edges (`bleedIntoClearCells`), marks the layer's cells for the GPU (`makeLayerDataDirty`) and asks for a frame.

Between nodes a raster travels as autk-db's `getRaster` collection in an envelope, `{dataType: "raster", data, layerName}` ([`rasterWire.ts`](../utk_curio/frontend/urban-workflows/src/utils/raster/rasterWire.ts)): each band base64 of little-endian float32, rows from south to north, and the `grid` (CRS, size, origin, cell size) it was read on, which the collection does not carry. A Python node receives one as a `rasterio` dataset that `rasters_for_python` rebuilds on a GeoTIFF of its own (beside the artifacts in process, in the scratch directory in an isolated child). Both sides run `rasterWire.cases.json`.

### Raster algebra

Operations over rasters are the Scout package's: [`scout_rasters/raster_algebra.py`](../packages/curio.scout@1/sources/scout_rasters/raster_algebra.py). The Raster Calculator's code imports `raster_calculate` and `raster_statistics` from it, and a node of another package imports them when its package names Scout in `dependencies.packages`, which hands the node Scout's modules too (the package modules paragraph of [Running a node](#step-by-step-running-a-node)). The namespace a Python node runs in holds no raster operations. They run in Python, where a node's rasters are: autk-db reads every band as float32 and loads at most 4096 by 4096 cells, which is what a map draws, not what a computation needs. Rasters are combined only on one grid (`grid_differences`: size, origin, resolution, rotation, CRS, to a relative 1e-9), and a refusal names both grids in words (`describe_grid`, numbers written as JavaScript writes them). A cell is nodata where its raster holds its nodata value or a number that is not finite.

- On rasterio datasets (`raster_calculate`, `raster_statistics`) the module computes at the inputs' own number type, at least float32, takes the size of each cell's result with `absolute=True`, and writes a result as a GeoTIFF with NaN as nodata, named after its content, where the node's code says (`output_file=curio_output_file`). Statistics are numpy's `nanmean`, `nanmedian`, `nanmin` and `nanmax` on the band's own 2-D float64 array, nodata and masked-out cells as NaN.

`curio_load_data("<id>", bounds=(west, south, east, north))` reads a GeoTIFF's window (`rasters.read_window`): the whole cells whose centres lie inside the bounds, on the raster's own grid, every band at its own type and nodata, written as a GeoTIFF of its own. Bounds that reach past the raster, or hold no cell centre, are refused. The dataset scanners (`DATASET_PATH_CALL_RE` and `COLLECTION_CALL_RE` in `code_refs.py`, the agents' `_catalog_call_re` over the loaders the functions page names, the frontend's `datasetIdsInCode`) take the id as the call's first argument, so options may follow it, and both loader generators name `bounds=None` on a GeoTIFF's line (`LOADER_OPTIONS`).

`curio_load_data("<id>", part="<file>")` reads one file of a bundle (`catalog_helpers.bundle_part`): the dataset's path comes from the same dataset-path map, and the part must be one `listed_bundle_parts` gives, the `bundle.json` entries that are regular files inside the dataset's folder. Staging stages the same list under isolation, so both modes and the headless runner read the same files; any other name is refused with the dataset's files. The agents' source scanner treats a `part=` value of a `curio_load_data` call, literal or f-string, as a file of the dataset, not a path on disk.

`rasters.mosaic_rasters` lays rasters that lie on one grid side by side (`mosaic_grid`: the tiles' north-west corner, the first tile's cell size or a given one, each tile at the nearest cell): a GDAL VRT that points at their files, or a GeoTIFF of their cells. `curio.media@1`'s Mosaic Rasters calls it through `mosaic_collection` (a raster collection's rows). Scout's [`scout_rasters/web_tiles.py`](../packages/curio.scout@1/sources/scout_rasters/web_tiles.py) calls it too: its `mosaic_web_tiles` places web map tiles on their own grid (`tile_bounds`), a tile it lacks holding `fill` and the file naming `nodata`, for Rasterize Buildings, whose missing tiles are no data, and Deep Umbra (`model.scout.deep-umbra@1`, which names Scout in `dependencies.packages`) places its tiles with its `tile_bounds`. Package modules import `mosaic_rasters` from `utk_curio.sandbox.util.rasters`.

A `dataRef` that names an unavailable table, whether an empty layer, a layer that was never loaded, or one dropped by an upstream node, is dropped before the grammar executes: the behavior removes the `map.layerRefs` entry or `plot` block and logs a console warning, which for a missing table lists the non-empty table names that *are* available; a `compute` block whose `dataRef` matches no layer is skipped. A map that keeps some of its layers renders them, and its success output notes the ones it lost, naming an empty table apart from one the dataflow does not produce. One left with nothing to draw is reported as an empty render (see [Render Outcomes](#render-outcomes)), and a reference to a table that exists but holds no rows is blamed on that table's source rather than on the reference.

[Example 09](examples/09-heterogeneous-data-linked-views.md) demonstrates an input chip; [Example 11](examples/11-autark-pbf-loading.md) demonstrates named layer references.

### Connection Validation

`src/ConnectionValidator.ts` enforces rules when the user draws an edge:

- Source port type must be compatible with target port type.
- Port cardinality is respected (e.g., a `'1'` input port rejects a second incoming edge).
- A node whose one input port takes more than one edge (`"[1,n]"`) grows an input circle per edge, `in`, then `in_1`, `in_2`, up to the port's maximum. [`growingInputs.ts`](../utk_curio/frontend/urban-workflows/src/providers/flow/growingInputs.ts) reads that from the template, and `useConnect` puts each new edge on the next free circle (see [Several inputs](USAGE.md#several-inputs)).

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

3. Backend proxies to Sandbox (execution/node_exec.py)
   POST {SANDBOX_HOST}:{SANDBOX_PORT}/exec    [Python nodes]
   POST {SANDBOX_HOST}:{SANDBOX_PORT}/execJs  [JS Computation nodes]
   Body: { code, nodeType, file_path: <artifact_id>, dataType: <kind>,
           dataset_paths: { <datasetId>: <absPath> } }

   dataset_paths resolves the portable curio_data_path("<id>") calls that
   Data Catalog loader snippets emit. See "Portable dataset paths" below.

4. Sandbox executes user code
   Python: worker.py::execute_code defines it as userCode(input_0=None, ...) and runs it via exec()
   JavaScript: spawns a Node.js subprocess, wraps code in async function(input_0, ...){…}
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

**Backend side:** both routes only parse the request and call [`execution/node_exec.py`](../utk_curio/backend/app/execution/node_exec.py). Its `execute_python_node` and `execute_js_node` take the account and the session token as arguments, so a node runs the same way from a route or from a thread with no request: they resolve dataset paths, collections, connection keys and models, call the sandbox, auto-install the output, write the runtime journal and count the run on the monitor. The HTTP session to the sandbox is in [`execution/sandbox_client.py`](../utk_curio/backend/app/execution/sandbox_client.py): `sandbox_request` raises `SandboxTransportError` when the sandbox times out, cannot be reached or refuses the shared secret, and the routes answer it as JSON with a 504 or 502. The sandbox runs only so many nodes at once: one Python node without isolation (`_exec_lock`), `CURIO_EXEC_PARALLELISM` isolated children, `CURIO_JS_PARALLELISM` Node processes. A run that finds its place taken waits for it in the sandbox, and the backend holds no run back. `/exec` and `/execJs` answer at once and run the node on a thread of their own ([`sandbox/run_place.py`](../utk_curio/sandbox/run_place.py)): while the run waits, the reply sends a space every few seconds; when it takes its place, one more, then nothing until the JSON. The request's read timeout counts every gap between bytes, so it covers the node's run, not its wait. An error the sandbox hits after the first byte comes back in the JSON, under `error`. The browser keeps no timeout of its own on a node run (`utils/nodeRunRequest.ts`), as for a run on the server: the backend's decides, and Run All's stall watchdog leaves a node whose run the backend still holds.

**Package modules (#468).** For a node whose package ships Python modules in `sources/`, `node_exec.resolve_package_modules` adds `package_modules: {"root", "names"}` to the `/exec` body: the package's `sources/` folder in the account's store and its module names, the importable names there that no template names as its `source` ([`packages/domain/python_modules.py`](../utk_curio/backend/app/packages/domain/python_modules.py)). A package that names others in `dependencies.packages` also hands its nodes their modules, transitively: `package_modules` is then a list of `{"root", "names"}`, the node's own package first ([`packages/application/python_modules.py`](../utk_curio/backend/app/packages/application/python_modules.py)). A bare `<packageId>` entry with several majors installed takes the one the dataflow's lockfile names, as a node's own package does. Adding the package adds the packages it names, and theirs in turn, on every add path, and records each in the lockfile: `required_packages` ([`packages/domain/package_closure.py`](../utk_curio/backend/app/packages/domain/package_closure.py)) resolves them before anything is copied, through `packages/application/package_dependencies.py`, and refuses an add whose needed package neither the store nor the catalog holds at a version its entry allows. The headless runner and the ground-truth harness send the same. In both execution modes the sandbox links those modules into a folder of the run's own, a name two packages ship from the first, with `staging.stage_package_modules` (under fork isolation, the child's scratch directory), puts the folder first on `sys.path` for the run, and when the run ends removes it and every module imported from it ([`sandbox/util/package_modules.py`](../utk_curio/sandbox/util/package_modules.py)): the next run, after an update or of another package, imports its own copy. An import of a package's module is not shared with the session's later nodes. A module name that is already loaded from somewhere else fails the node with that name. The installer refuses a package that ships a module another installed package ships (`refuse_a_module_name_in_use`); two majors of one package may share names. Save into a package and an agent's package draft hand the package's module names, and those of the packages it depends on, to the import scanner (`scan_imports_for_filename`), which leaves them out of the detected dependencies. Both hand it each source with its `[!! … !!]` references written as the plain name `input_0` (`code_references.references_as_names`), so a node that reads its inputs through chips parses.

**New node from a Python function.** `GET /api/packages/factory/functions` lists the public functions of every module in the account's store, read with `ast` and never imported ([`packages/domain/function_nodes.py`](../utk_curio/backend/app/packages/domain/function_nodes.py)), with the widget and use each parameter suggests. `POST /api/packages/factory/function-template` reads the module again and writes the template: its code imports the function and returns its call, with `[!! name !!]` for a widget and `[!! input_k !!]` for an input ([`packages/application/function_nodes.py`](../utk_curio/backend/app/packages/application/function_nodes.py)). The dialog (`NodeFromFunctionModal`) installs it the way Save as package node does: `PackageTargetPicker`, `buildTemplateInstallDraft` and `installDraftToProject`, through `/factory/install`. A template in another package than the function's names the function's package in `dependencies.packages`.

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

The harness reads the cause from the `kind`, never from the message. [`result_shape.py`](../utk_curio/backend/app/agents/domain/result_shape.py) asks `is_document_at_fault`, which reads the same table: a cause at fault turns a valid document's round into a failed round and asks for a correction, `no-input-rows` leaves the document untouched and reports the upstream, and a cause the backend does not recognize is treated as at fault. The prefix, the cause names and the at-fault table are defined once, in `src/contracts/renderCauses.json`, which the frontend imports and the backend reads (see [Shared Constants](#shared-constants)).

### Running Python Code

[`sandbox/app/worker.py`](../utk_curio/sandbox/app/worker.py)::`execute_code` runs a Python node's code in the sandbox process; under isolation, the confined child in `sandbox/isolation/child.py` does the same in its own process (see [Sandbox Isolation](#sandbox-isolation)). Each run:

- Builds a fresh namespace from the pre-loaded globals (the libraries, `curio_edit_features` and `curio_layer`), adds the session's earlier import bindings, `curio_secret`, and the catalog helpers `install_catalog_helpers` puts in ([`util/catalog_helpers.py`](../utk_curio/sandbox/util/catalog_helpers.py): `curio_load_data`, `curio_data_path`, `curio_load_collection`, `curio_derived_file`, `curio_output_file`, `curio_load_model` and `curio_segment`), and defines the code as `def userCode(input_0=None, input_1=None, **_curio_unread_inputs):`, one parameter for each `input_k` the code reads, on the code's first line ([`util/input_names.py`](../utk_curio/sandbox/util/input_names.py)). [`node-functions.md`](../agents/agent.curio.builtin@1/knowledge/node-functions.md) gives each function node code calls, with its arguments, and `test_node_functions_sandbox.py` holds it to this namespace, the isolated child's and the JavaScript wrapper's.
- Calls `load_from_duckdb(artifact_id)` to reconstruct the upstream Python object (DataFrame, GeoDataFrame, scalar, tuple, etc.) from the shared DuckDB database, and passes the input on circle k as `input_k`. The request's `input_slots` names the wired circles in order, as the canvas and the runners know them from the edges' handles; a circle with no edge is `None`. Several edges on one circle are that circle's list. The input chips in its code arrive already written as `input_k`. A layer chip arrives as `curio_layer(input_k, "<layer>", <circle>)` ([`util/input_layers.py`](../utk_curio/sandbox/util/input_layers.py), and its JavaScript twin in `util/js_wrapper.mjs`): the input's layer of that name, found as an Autark spec finds a table, read from an Autark node's `{name, type, geojson}` array, its `outputs` envelope of `layerName` layers, or frames whose `metadata` names them (an envelope's layer gets its name there from `_keep_layer_identity`). An input of exactly one frame with no layer name is that layer, whatever the chip names; an input of several frames without the name fails naming input_k and its layers.
- After the code returns, calls `detect_kind(output)` to classify the output. A node's type contract is its template's declared ports, which the canvas enforces when an edge is connected.
- Calls `save_to_duckdb(output)` to persist the result, and returns the new artifact id and kind.

`load_from_duckdb` and `save_to_duckdb` live in `utk_curio/sandbox/util/parsers.py`, `detect_kind` in `utk_curio/sandbox/util/codec.py`, and the DuckDB connection in `utk_curio/sandbox/util/db.py`.

### Sandbox Isolation

The sandbox runs as a separate Flask process. It:

- Binds `127.0.0.1` by default and is not published by the Docker image, so
  only the backend on the same host can reach it.
- Requires a shared secret on every route that can run code or read artifacts
  (`/exec`, `/execJs`, `/get`). The secret is minted per launch by
  `cli/environment.py::set_environment_variables` into `CURIO_SANDBOX_TOKEN`, attached by
  the backend in `execution/sandbox_client.py`, and checked in `sandbox/app/auth.py`. An
  instance started with `--deploy` refuses to boot without one.
- Sends no CORS headers, because no browser calls it directly.
- Returns the memory its allocators keep free to the system whenever no
  request is in flight (`sandbox/util/memory_release.py`): every request runs
  on a thread of its own, and glibc's malloc arenas and pyarrow's pool would
  otherwise keep the pages each run freed.

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
  runs, and a `docs` symlink to the `docs/` Curio ships ([Where the shipped
  folders are](#where-the-shipped-folders-are)) is dropped in so the shipped
  examples' relative reads still resolve. A relative write anywhere else fails,
  since the launch tree is root-owned by then. The child's scratch directory
  also holds numba's cache (`NUMBA_CACHE_DIR`, `child.point_numba_at_scratch`):
  numba refuses to import a library that compiles with `cache=True` unless it
  can write beside the library or under HOME, and the execution account can do
  neither.
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

### Where the shipped folders are

The repository keeps the folders Curio ships beside its code next to `utk_curio/`: `agents/`, `datasets/`, `discovery/`, `packages/`, `scripts/` and `vendor/`, and `docs/`, of which Curio reads the dataflows it ships (`docs/examples/*.json`, with the use-case index `use-cases.json`, and `docs/examples/dataflows/*.json`), the example data their nodes read by its path (the files of `docs/examples/data/` they name), the Example storage source's folder (`docs/examples/data/storage/`), the prompt fixtures (`docs/examples/prompts/`) and two schemas (`docs/schemas/trill.v1.json` and `example-prompt-fixture.v1.json`). [`utk_curio/shipped.py`](../utk_curio/shipped.py) `path` says where one is on this machine, and every reader asks it: the four catalogs' roots, the shipped agents' folders (`agents/domain/builtin.py`), a shipped folder source's root, the launcher's manifest walk and DuckDB seeding, the `/file/vendor/duckdb-extensions/` and `/file/docs/examples/data/` routes, an isolated run's `docs` link, node code's relative paths in `docs/`, `workflow_spec`'s scan of the shipped code nodes, `curio test`, the agents' prompt fields, the shipped dataflows (`projects/shipped.py`) with the worked examples' index, and the agent evaluation's fixtures.

- A clone, the Docker image and CI: next to `utk_curio/`.
- A pip install: `utk_curio/_shipped/<folder>/`. `setup.py` maps each folder into the wheel there, so the wheel installs nothing in site-packages but `utk_curio/` and its dist-info, where a `datasets/` of Curio's would mix with Hugging Face's `datasets` package. The sdist keeps the repository's layout, and `MANIFEST.in` says which files ship: of `docs/`, only the files above and the credits of the Example storage's Mapillary photos. `test_pip_wheel_layout.py` checks that the wheel carries exactly those, the example data as the shipped dataflows' nodes name it.

Node code reads files by a path relative to the folder it runs in: the folder Curio started from, or an isolated run's work directory, whose `docs` link leads to the shipped `docs/`. [`sandbox/util/user_code.py`](../utk_curio/sandbox/util/user_code.py) defines a node's `userCode` for the in-process path and the isolated child: a string literal in the code that is a relative path in `docs/`, which that folder does not hold and Curio ships, becomes the absolute path of the shipped file, and the rest of the code compiles as it is, with its line numbers. A clone, the Docker image and CI run node code in a folder that holds `docs/`, so there nothing is rewritten and nothing is written into the folder Curio started from.

The layout is decided once, by whether `utk_curio/_shipped/` exists, never folder by folder. The `CURIO_CATALOG_ROOT`, `CURIO_DISCOVERY_ROOT` and `CURIO_PACKAGES_ROOT` overrides come first.

### The sandbox's Node.js packages

autk-db runs in Node.js for the sandbox's JS nodes and for OpenStreetMap downloads. [`sandbox/util/node_runtime.py`](../utk_curio/sandbox/util/node_runtime.py) `nodejs_dir` names the folder whose `node_modules` they read and the launcher installs:

- A clone, the Docker image and CI: the folder that holds `utk_curio/` and Curio's `package.json`.
- A pip install: `nodejs/` in Curio's state directory. `setup.py` copies the repository's `package.json` and `package-lock.json` into the wheel at `utk_curio/sandbox/nodejs/`, and the launcher writes them into that folder.

On every start, `cli/dependencies.py::_ensure_root_node_modules` runs `npm install --prefix <folder>` there, only in a folder that holds Curio's `package.json` and is not a link; otherwise it logs an error and runs no npm. `.curio/nodejs` is in the sandbox's `SENSITIVE_PATHS`.

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
- **Node.** autk-db runs in the sandbox's Node (Autark's data path) and in the
  backend's (the Discovery Catalog's OpenStreetMap downloads). Each `curio.py
  start` that runs either one (`all`, `backend` or `sandbox`) calls
  `cli/dependencies.py::seed_duckdb_extensions`, which copies them into
  `~/.duckdb/extensions/extensions.duckdb.org/`, where duckdb-wasm looks before
  downloading. Nothing is intercepted there.

Both fall back to the CDN for a file this checkout does not carry, so a newer
`@duckdb/duckdb-wasm` keeps working before its extensions are vendored; see
`vendor/duckdb-extensions/README.md` for how to vendor the new version.

### Portable dataset paths

Data Catalog loader snippets do not embed absolute paths. They emit
`curio_data_path("<datasetId>")`, resolved per execution, so a saved dataflow
stays valid when it is shared, moved, or opened by another user on the same
install.

The curated examples in `docs/examples/` are the reference consumers of this
mechanism: every one of their loader nodes resolves a committed catalog dataset
by id. Note the argument is the bare manifest `id`, never the `<id>@<major>`
`dirName` that `dataflow.datasets` refs carry - `SAFE_DATASET_ID_RE` permits `@`,
so an id with the major appended passes validation, misses the by-id lookup, and
fails open into a runtime error from the sandbox.

1. `backend/app/api/routes.py` scans the outgoing code for literal
   `curio_data_path("<id>")` calls (single or double quoted), dedupes the
   ids, and caps them at `MAX_EXEC_DATASET_IDS` (32).
2. It resolves them via `DatasetCatalogService.resolve_execution_paths`, which
   refuses any path outside the allowed read roots. Resolution **fails open**: an
   error yields an empty mapping rather than blocking the run.
3. The resulting `{id: absPath}` map rides along on the `/exec` body. The sandbox
   re-validates it (dict-shaped, stringified, ≤32 entries) and injects
   `curio_data_path` into the user namespace, where an unknown id raises an
   actionable `RuntimeError` instead of returning a foreign path.
4. Under fork isolation, `stage_dataset_paths`
   ([`sandbox/util/staging.py`](../utk_curio/sandbox/util/staging.py)) hardlinks
   each file into the run's scratch as `ds_<i>/<file>`, with the files named
   after it: a parquet's `<file>.decode.json`, a shapefile's `.shx`, `.dbf` and
   `.prj`. A bundle is staged as `ds_<i>/data/bundle.json` with the parts its
   `bundle.json` names, at their paths under the dataset's folder.

The id must satisfy the same safe-id pattern on both sides before it is
interpolated into generated Python; an id that fails it falls back to a literal
quoted path. See [DATA-CATALOG.md](DATA-CATALOG.md) for the authoring view.

### Files the pip package leaves out

PyPI takes no file over 100 MiB, so the pip package (the sdist, and the wheel
built from it) leaves out the biggest catalog files: each data file or model
package weight that its dataset's or model package's manifest names in
`downloadOnFirstUse` ([DATA-CATALOG.md](DATA-CATALOG.md#7-the-manifest),
[MODEL-CATALOG.md](MODEL-CATALOG.md#6-the-manifest)). A path there names a
file, or a folder whose files it covers. The small files of their folders,
the manifests among them, still ship.
[`utk_curio/shipped.py`](../utk_curio/shipped.py) `downloaded_on_first_use`
reads the manifests, for the release and for a running Curio.

1. `setup.py`'s `egg_info` drops the named files from `SOURCES.txt`, the list
   of the files the sdist ships and the wheel takes its package data from.
   `test_left_out_files.py` replays `MANIFEST.in` and that step, and
   `test_pip_wheel_layout.py` builds both archives.
2. The release workflow runs `scripts/record_left_out_files.py --commit
   $GITHUB_SHA` before `python -m build`. It writes
   `left_out_files.record.json` beside `left_out_files.py`: the commit, and
   each left-out file's size and sha256. The package ships it; a checkout has
   none.
3. A reader that finds a left-out file missing calls
   [`left_out_files.fetch`](../utk_curio/backend/app/datasets/infrastructure/left_out_files.py):
   `PathResolver._resolve_item_path` (preview, download, extent and
   execution paths), `install_dataset_from_catalog` (install and seeding) and
   `packages/application/model_packages.weights_folder` (a node's
   `curio_load_model`, and an export). `left_out_files.is_left_out` reads the
   shipped manifests. The registry gives a left-out file's recorded size
   before it is fetched.
4. `fetch` downloads
   `https://raw.githubusercontent.com/urban-toolkit/curio/<commit>/<path>`
   through `agents/infrastructure/egress.download`, under one lock per file,
   into `<curio_root>/fetched/<commit>/.partial/`, checks size and sha256
   against the record, makes it 0644, copies the small files of its catalog
   folder beside where it goes, and renames it to
   `<curio_root>/fetched/<commit>/<path>`. A reader resolves the file there
   from then on. A download first removes the folders of other commits under
   `fetched/` (never a symlink, never the current commit's).
5. `<curio_root>/fetched` is created 0700 and is in the sandbox's
   `SENSITIVE_PATHS` and `HARDLINK_SOURCES`, as `packages/*/models` is: an isolated
   child reads a fetched file only through the hardlink its run stages
   (`stage_dataset_paths`, `stage_model_dirs`), and cannot walk the folder or
   rename a file in it.
6. A failed download raises `LeftOutFileUnavailable` with the URL and the path
   to save the file to. The Data Catalog answers it as a 502;
   `node_exec._execute` collects it (`left_out_files.failures()`) and fails the
   run with it, without calling the sandbox.

---

## Interactions and Propagation

Visualization nodes (`Autark`, `Vega-Lite`, `Simple View`) report the user's selections (clicks, hovers, brushes, picks). A selection travels over interaction edges, to a Data Pool or straight to another chart, and each of them highlights the rows it picks; no node runs again for it. A node's code reads a view's selection through a selection tag (below).

### IInteraction

```typescript
interface IInteraction {
  nodeId: string;   // which visualization generated the interaction
  details: any;     // selection payload (indices, ranges, coordinates)
  priority: number; // used when multiple interactions compete
}
```

Interactions are stored in `FlowProvider.interactions[]` and passed down to nodes via `INodeData.interactions`.

`applyNewInteractions` (`src/providers/flow/useInteractions.ts`) routes the selection that just changed along the interaction edges, one hop. A second effect there follows the edges themselves, however they change (drawn, deleted with a node, opened with a dataflow, or added by a collaborator or an agent): an edge that goes takes back from each end what the other end delivered, and a new edge hands each end the other end's latest selection, by the same rules: a pool takes a chart's selection, two views take each other's, and two pools exchange none. A Vega-Lite chart handed an empty list puts back the `interacted` flags its first input carries (`useVega.applyDirectSelection`), and an Autark view drawn again reports its own pick or brush empty, as a Vega-Lite chart's compile reports its selects, so the views linked to it let that selection go.

`onConnect` (`src/providers/flow/useConnect.ts`) refuses an interaction edge neither end of which shows a selection it receives, such as one between two Simple Views (`registry/interactionRoles`, the rule `plan_topology` applies to agents' plans). A saved edge opens as it is. Its cycle check follows data edges only (`runLevels.directedEdgesOf`): a data edge from a Data Pool into a chart linked to it closes no cycle.

### Propagation Strategies

A Data Pool resolves the selections that reach it with two modes, chosen in the two selects at the top of its body, or set by an agent's plan or `node.create` ([Dataflow plans](#dataflow-plans)), and saved with the node (`metadata.dataPool`). The selects' words are `src/contracts/nodeSettings.json`:

- **Conflict inside visualization** (`insideChart`) combines the selects of one chart, such as a Vega chart with two params.
- **Conflict between visualizations** (`betweenCharts`) combines the charts linked to the pool by an interaction edge.

| Mode | Semantics |
|---|---|
| `OVERWRITE` (default) | Only the most recent selection applies |
| `MERGE_AND` | A row must be picked by every active selection |
| `MERGE_OR` | A row must be picked by at least one active selection |

A selection is active when it picks something: a point selection with rows or values, or an interval over at least one column. A select nobody has used, or one that was cleared, takes no part in `MERGE_AND`.

A point selection names rows in one of two ways. Without fields it names row positions, which line up only when both ends read the same rows in the same order. Over fields it names values, `[{unit_id: 103}]`, and picks every row holding them wherever the row sits: a Vega-Lite point select over `fields` (`utils/vegaSelects.pointValues`), or an Autark pick or brush on a map layer or plot whose document names `selectFields`. The Autark node maps the positions autk-grammar reports to input rows (`utils/autkInput.inputRow`) and reads the key columns from the input's features (`keyValues`): a row with no value for a key is left out, and a selection left with none is not active. `selectIndices` looks values up in a tree per set of fields instead of comparing every point with every row, with strict equality and a Date compared by its time; a bin, `[start, end)`, is compared row by row, and a point holding `undefined` or NaN matches nothing. `selectFieldsProblem` fails a run whose keys cannot be read: a table the document loads itself, which autk-grammar's map draws without its features that have no geometry, so its pick ids do not index the input's rows, or a column no feature of the table has.

`applyNewInteractions` (`src/providers/flow/useInteractions.ts`) hands a pool only the chart that just selected. The pool keeps each linked chart's latest selection itself, keyed by the chart's node id (`dataPoolBehavior`): the newest is priority 1, the others 0, and `utils/selectionMatch.matchSelections` resolves them. `OVERWRITE` resolves the priority-1 entry alone. A chart whose interaction edge to the pool is removed, or that is deleted, leaves that map, and the pool resolves what it still holds at once: with no selection left, every layer's flags go. Choosing another mode resolves the selections the pool holds again.

The pool writes its `interacted` flags into a copy of its output (`utils/poolFlagCopy`), never into its input or into an output it already sent, which the charts downstream still hold. Its echo names the chart that just selected (`selectionSource`, see `utils/selectionEcho`) under every mode. An Autark node skips an echo of its own selection, so a plot keeps its brush; a Vega chart applies it, which only recolours rows. Every other chart shows the resolved rows, and an Autark plot shows them as its selection in place of its own brush.

A Data Pool linked to another Data Pool by an interaction edge hands it the flags of the rows its `linked` column names (`INodeData.propagation`, through `applyNewPropagation`), and flips that pool's `newPropagation`, so the other pool flags those rows too.

### Selection tags

A node's code reads a view's current selection as `[!! selection name !!]`: the ids of the selected rows, a list. The tag lives on the node that reads it, in `data.selections` and in the spec at `metadata.selections` (`{name, node, column, ids}`), so a run on the server and the headless runner read the ids from the saved dataflow, as the browser does.

- **Rows.** A view hands over the rows it matches selections against (`utils/references/viewSelections.provideViewRows`): a Vega-Lite node the rows it draws, whose positions or values its point selections name; an Autark node the features of each layer it reads, whose positions its picks name, or whose key values when the view names `selectFields`. Nothing is fetched again.
- **Ids.** `utils/references/selectionTags.selectedIds` resolves the view's latest select with `matchSelections`, as a Data Pool in its default mode does, and reads the tag's column from those rows, each value once. `_vgsid_` and row positions are never stored: a node reads its own upstream artifact, where they mean nothing. `idColumns` offers `osm_id` and `building_id`, then any column whose values are all text or numbers and all different. More than `SELECTION_ID_CAP` (10,000) ids are stored as a `count`, which fails the run with a message.
- **Updates.** `providers/flow/useSelectionTags` records each view's latest selection. On one the user made, or cleared (`changesSelection`: a select at priority 1 that holds a selection, or that empties one the view held), it rewrites the ids of every tag on that view and marks the nodes holding them stale. A chart declaring its selects as it compiles, or reporting them empty as its signal listeners hear the first pulse, changes nothing by itself: what a view drawn again does with its tags is below. `runKeyWithShared` takes the node's tags, so the run cache keys on the ids its code names.
- **Redraws (#884).** A view drawn anew shows no selection, so the selection its tags hold goes back in it, or the tags are emptied: after a run or a reopen, the view and its tags agree. `useVega.compileGrammar` does this for every new view but the redraw of a chart reading `inputs` when its boxes are renamed or recolored (`keepsSelection`), which puts back the selection the view before it held. It finds the rows of the chart's first input that hold the tags' ids (`selectionTags.rowsHeldBy`) and sets the store of its point select (`<name>_store`) to them, in the form vega-lite gives a click's own tuple: `vegaSelects.pointStoreOf` reads the unit and the fields off the compiled `<name>_tuple` signal, and `pointStoreTuples` gives the rows' `_vgsid_` for a select over no fields, else their values of its fields. The listeners stay silent until the store is set; then the chart reports the select as a click does, so the tags are written from what it shows (the same ids change no tag and mark no node stale) and a Data Pool sees the selection too. A chart that cannot do this empties its tags through the flow's `clearSelectionTagsOf` (`useSelectionTags.clearViewTags`), which marks their nodes stale and forgets the view's last selection: one that declares no point select, or an interval one too (a tag does not record which select made its ids), whose select's unit is named per facet cell, or that draws none of the rows. An Autark node empties its tags after each draw (`adapters/node/autkViewBehavior`, the behavior registered for `autk-grammar`), since autk-grammar lights a pick again only through a Data Pool's flags. A run that started before the redraw reads the ids saved before it.
- **Resolution.** The selection kind is one more kind in the reference module (`codeReferences.ts`, `execution/code_references.py`), pinned by the shared cases table. `WorkflowSpec.node_code` passes a node's tags, which `run_engine` and `runner` both call.
- **Agents.** `dataflow.read` lists a node's tags in its row (`agents/application/tools._node_row`), each with its view, its column and how many ids it holds, never the ids. The base entry's `knowledge/selection-chips.md`, which the preamble includes, says how code places one, through the `{{selections.reference:<name>}}` marker.

---

## Provenance Tracking

Curio records a per-node history (start/end time, source code, input/output types, parent entry) so users can replay a node's evolution from the canvas. The browser keeps it: [`src/providers/ProvenanceProvider.tsx`](../utk_curio/frontend/urban-workflows/src/providers/ProvenanceProvider.tsx) holds the graph in React state and persists it as part of the saved workflow JSON (`nodeProvenance`), which no server code writes.

- **Entries.** An entry is a run (`nodeExecProv`) or an edit (`nodeEditProv`), which ran nothing: a change made in a Map Editor node's body, or an agent's change the user applied. A node whose code is its state registers a writer (`utils/nodeCodeWriters.ts`) and files an agent's change as its own changes; for any other node `useGraphEdits.applyNodeContent` writes the code and files the edit, named after the agent the apply names (`appliedContent.agent`), with the code it replaced (`before`), and leaves the dataflow Unsaved (`markDirty`), as the Map Editor writer does, so the next save keeps the entry; it files nothing when the code stays as it was. A node an agent proposed with its code starts with such an edit (`useAgentCanvasMutations`): a `node.create` or package draft apply names the agent on the nodes it hands the canvas (`createdNode.agent`, `createdNodes[].agent`), never on the saved node. A plan's nodes start with none, even one whose template's starter is its code, since a plan apply names no agent on them; the code later written into one is its first edit.
- **Agents.** `node.history.read` ([`agents/application/tools.py`](../utk_curio/backend/app/agents/application/tools.py)) reads the saved spec's `nodeProvenance`, keyed by node id as a load keys it: `utils/nodeProvenanceKeys.ts` and its twin [`projects/node_provenance.py`](../utk_curio/backend/app/projects/node_provenance.py) both run `nodeProvenanceKeys.cases.json`. It lists a node's entries newest first, or gives one entry's code and the code an edit replaced, each cut to the tool's bounds with what was left out counted (`entriesElided`, `codeElided`). The Node Builder and the Dataflow Builder are granted it; the Dataflow Reader is not, since it runs only as delegated modes, which run with no tools. The base entry's `knowledge/provenance.md`, which the preamble includes, says what an entry is and that putting one back is the user's action. An entry filed since the last save is not in what it reads.

The dataflow's own version history is `TrillGenerator`'s (`provenanceJSON`, one version per node or connection added or removed), saved as `dataflowProvenance`. The provenance drawer shows it (see [The provenance drawer](#the-provenance-drawer)).

---

## The Trill Dataflow Format

A saved dataflow is one JSON document, a **trill**, written to `.curio/users/<userKey>/projects/<projectId>/spec.trill.json`. It holds the graph (`dataflow.nodes`, `dataflow.edges`), the dependency lockfiles (`dataflow.packages`, `dataflow.datasets`, `dataflow.agents`), and the two provenance sections described above.

Every trill is validated against [`docs/schemas/trill.v1.json`](schemas/trill.v1.json) (JSON Schema Draft 2020-12). The schema is the source of truth for what fields a dataflow can carry. Note what it deliberately does *not* decide: a node's `type` is a coordinate into a package manifest's `templates[].id`, so which templates exist, which handles are legal, and whether a node has code at all are manifest questions that depend on the installed packages. [`projects/storage.py`](../utk_curio/backend/app/projects/storage.py) performs no validation of its own - it reads and writes the spec as opaque JSON - so the schema and the tests around it are the only enforcement.

Full field reference, ownership rules, and the CLI for checking your own projects: [`docs/TRILL-SPEC.md`](TRILL-SPEC.md).

---

## Shared Constants

Some vocabularies and tables are read by both the frontend and the backend. Each is one JSON file in [`utk_curio/frontend/urban-workflows/src/contracts/`](../utk_curio/frontend/urban-workflows/src/contracts/): the frontend imports it, and the backend reads it through [`utk_curio/common/shared_constants.py`](../utk_curio/common/shared_constants.py) when the module that holds its values is imported. Nothing is generated, so a change to a file reaches both sides.

| File | What it holds | Frontend | Backend |
|---|---|---|---|
| `renderCauses.json` | The empty-render kind prefix, and each cause a render can draw nothing for: whether it blames the document, and what it means (see [Render Outcomes](#render-outcomes)) | `utils/renderOutcome.ts` | `contracts.EMPTY_RENDER_KIND`, `RENDER_CAUSES`, `is_document_at_fault` |
| `solveStopReasons.json` | Each reason a node's repair loop stops for (`stoppedBy`), and the phrase it reads as (see [The Solve loop](#the-solve-loop)) | The attempts card and the per-node Solve row (`AgentSolveAttemptsCard.tsx`) | `contracts.SOLVE_STOP_REASONS` and `STOPPED_BY_PHRASES`, which the failure sentences read |
| `agentCategories.json` | The categories an agent manifest can declare | The agent palette (`agentCategoryStyle.ts`) | `manifest.AGENT_CATEGORIES`, for the validator and the catalog's facets |
| `noteColors.json` | A note's palette, its default color, the two inks and the two link colors, and the contrast an ink must reach (see [Notes](#notes)) | `utils/noteColors.ts` | `packages/application/note_palette.py`, which hands the palette to the rules of `packages/domain/node_appearance.py`: the domain layer reads no file |
| `autkGrammar.json` | The Autark grammar's top-level families, the prefix of the names a grammar node's inputs are read by (`input_<k>`), and what a document with more than one view is told (see [Referencing Upstream Data in Autark Nodes](#referencing-upstream-data-in-autark-nodes)) | `contracts/autkGrammar.ts`, `utils/autkSpecKind.ts` | `contracts.INPUT_TABLE_PREFIX` and `AUTK_ONE_VIEW` |
| `visDefaults.json` | What a visualization node does with its input by itself: the column roles and the pandas dtypes each role comes from, the Vega-Lite and Autark starter ladders (each rule's id, condition, mark or family and description, in ladder order), the Vega-Lite `$schema` URL, and the column names, URL extensions and share of image values behind Simple View's image columns | `starterSpec.ts`, `vegaDefaultSpec.ts`, `autkDefaultSpec.ts` and `imageColumns.ts`, which keep each rule's builder, keyed by its id, and the matching logic | `contracts.py`'s tables, which the prompt fields render into the preamble |
| `nodeSettings.json` | The words of a Data Pool's two selects and of each of its modes, keyed by `ResolutionType`, and of a Simple View's image column (see [Dataflow plans](#dataflow-plans)) | The pool's selects (`DataPoolContent.tsx`), the view's picker (`simpleVisBehavior.tsx`) and an agent's review card (`reviewCardText.ts`) | `agents/domain/data_pool_settings.py` and `simple_vis_settings.py`: the modes an agent may set, and the words of a plan's preview and a `node.create`'s summary |

- **Where.** The folder is in the frontend's source, so the Docker image's frontend build, which copies only `utk_curio/frontend/`, and the Jest job and the release's frontend build, which run before or without Python, read the files where they are. A clone and the Docker image keep the folder there for the backend too, and a pip install has it inside its package, which carries the frontend's source (`MANIFEST.in` and `include-package-data`). `test_pip_wheel_layout.py` checks that a pip install's backend reads them there.
- **Reading.** `shared_constants.read` parses a file as `JSON.parse` does, except that an object naming one key twice raises, where `JSON.parse` and `json.loads` keep the last value.
- **Types.** Where a vocabulary is an object's keys (the render causes, the stop reasons, the note colors), its TypeScript type is the keys of the imported file. A type over a list is declared beside the table that routes it: `ColumnRole` beside `groupColumns`, the Autark families as the keys of `FAMILY_KIND`, `AgentCategory` as the keys of `AGENT_CATEGORY_ICON`. A Jest test holds each table to its file.
- **Code over them.** `inputTableName` and `autkOneViewProblem` in `contracts/autkGrammar.ts` are the twins of `contracts.input_table_name` and `autk_one_view_problem`; `autkGrammar.cases.json` beside them holds the cases Jest and pytest both run.
- **Tests.** `test_shared_constants.py` holds every backend constant to its file, the Autark families to the vendored schema's, and finds no Python module spelling a shared sentence or palette color of its own. `src/tests/contracts/sharedConstants.test.ts` does the same for the frontend.

To change a shared value, edit its file. A new Autark family goes into `autkGrammar.json`: `test_shared_constants.py` fails until it matches the vendored schema, and Jest until `FAMILY_KIND` routes it.

---

## Agent text

Everything an agent reads is hand-written Markdown in `agents/`, the Agent Catalog's folder, and the backend renders it when it starts. No render is generated or committed, and `utk_curio/` holds none of the text: it holds the loader, the code that computes the facts the text states, and the checks, whose words to a model are messages of the base entry (below). Errors people see stay with their feature.

- **Where it lives.**
  - **The base entry**, [`agents/agent.curio.builtin@1/`](../agents/agent.curio.builtin@1/), holds the pages every agent Curio ships reads, as `packages/curio.builtin@1` is the base of the nodes. Its manifest says `kind: base` and lists its pages (`pages`): `default_preamble.md`, the preamble, which holds the Trill block and includes the pages of `knowledge/`, one per feature of Curio (its nodes, their code and chips, the functions node code calls, the catalogs, widgets, selection tags, Autark, Vega-Lite, interaction edges, Map Editor, scenarios, dashboards and the nodes' histories); `examples.md`, the worked examples' index (see [Agent Prompt Composition](#agent-prompt-composition)); `tools.md`, `protocol.md`, `frames.md`, `delegate-contracts.md` and `conversation-title.md`, the text the runtime composes a run's turns from (see [Agent Prompt Composition](#agent-prompt-composition)); `keyword-types.md`, the keyword types Curio ships; `messages.md`, what a check tells a model when it refuses or corrects what the model wrote (see Messages, below); `autark-grammar.md`, the words of the preamble's section on Autark documents (see [The Autark Schema](#the-autark-schema)); and `rules/`, text that prompts and pages include whole. `rules/plan-rules.md` is a dataflow plan's rules, which both of `dataflow.plan.write`'s descriptions include. `rules/package_contract.md` is the package backend contract, which the Node Builder's package-writing mode includes and a delegated call of that mode receives as its build-request contract's `backendContract`. `rules/research_verify_rules.md` and `rules/research_notes_rules.md` are the Researcher's rules for checking a fact and its notes format, each included by two of its prompts. Its README says how to edit a page. The base entry is no agent: `builtin` leaves it out of the roster, so no catalog listing, palette, LLM choice or delegation shows it, and `parse_agent_manifest` refuses a manifest of kind `base`. The loader finds it by its kind (`agent_text.base_dir`), so no code names its id.
  - **Each agent Curio ships** keeps its own prompts in `agents/<id>@<major>/prompts/`, each named by its manifest.
  - **A user's agent** keeps its prompts in its store folder, as uploaded.
- **`curio:<path>`.** A manifest names a page of the base entry as `curio:<path>`, such as `curio:default_preamble.md`, the preamble every agent Curio ships names, or `curio:rules/research_verify_rules.md`. `agent_text.page_file` resolves it, and refuses a path that is not a page the base entry lists or that leads out of it: `..`, an absolute path, or a symbolic link to a file outside. The parser checks every `curio:` path, so an upload that names no page is refused with the list of pages. A page whose file is missing is logged and reads as None. An export or an install's copy carries the page as `prompts/<path>`, its rendered text; publishing an agent and adding a published one keep the name.
- **The functions page.** `knowledge/node-functions.md` gives each function node code calls in fixed line shapes: its call as a Python signature (`### curio_<name>(<arguments>)`), the engines whose code has it (`Engines: python, javascript.`), one line on what it does, and one bullet per argument, which says the catalog item it names in one of `CATALOG_PHRASES`: a Data Catalog dataset or collection, a Model Catalog model, or a Node code key. [`agents/domain/node_functions.py`](../utk_curio/backend/app/agents/domain/node_functions.py) reads it, refusing a line of any other shape, into functions with their engines and arguments, each with its default and the catalog item it names; the agents' checks read which arguments name an item from it. The page holds no markers, since the user guides link to it as written.
- **Markers.** A page or prompt states a fact the code owns through a marker, `{{field}}` or `{{field:argument}}`, which `contracts.render_template` fills from `contracts.PROMPT_FIELDS` (below). `{{include:<path>}}` puts another page of the base entry in its place, rendered, without its final line breaks; a page that includes itself is refused. A marker no field defines, a field given the wrong argument, or a `{{` left in the result raises `PromptTemplateError`.
- **When it is read.** `create_app` calls [`agent_text.render_at_start`](../utk_curio/backend/app/agents/domain/agent_text.py), which renders each page the base entry lists and each prompt each agent Curio ships names, once per process; a marker error stops the start and names the file. Every read returns that render (`agent_text.read`): an agent's prompts (`builtin.read_prompt_text`), a page by its path (`builtin.read_page`), a section of a page by its name (`agent_text.section`), the worked examples' index and the delegated package contract. Under `curio.py start --dev` (`CURIO_DEV=1`), a read renders the file again, so an edit shows on the next run. A user's own prompts are never rendered: they are read as written, `{{` included.
- **Messages.** A check that refuses or corrects what a model wrote says why in a message of [`messages.md`](../agents/agent.curio.builtin@1/messages.md): a tool call the runtime does not run (`tool_rounds.py`), a proposal it does not make (`proposals/`), a plan or a request a parser refuses (`content.py`, `plan_scenarios.py`, `widget_grammar.py`, `plan_topology.py`), a source the grounding gate refuses (`source_grounding.py`), what a delegated run's result tells its parent (`turns/delegates.py`), and what Solve sends the content builder for another attempt (`document_validation.py`, `input_contract.py`, `result_shape.py`, `solve/`). Each message is a section named by its id, and the check reads it with `agent_text.message(<id>, name=value, ...)`: the words are the page's, and each `{name}` is a value the run knows, such as a node's id, the problems found or a bound the code owns. `agent_text.fill` fills the places in one pass, so a value is never read as a place, and refuses a place no value fills or a value with no place; the delegated task's frame is filled the same way. A message is text a check addresses to the model about what the model wrote: a refusal, a correction, or the notes its next attempt is given. One a card or a node's row also shows, such as the first line of a refused call under the reply or a Solve failure, is still the model's message. A feature's own record or data stays with the feature, in Python, even when a run reads it later: a node's error on Play (the sandbox's errors, the chip refusals in `execution/code_references.py`), the run journal's reason, a probe's verdict and a candidate row's access words and download steps (`verify.py`), the reason an Apply or a card gives, an HTTP error, a chat record (an applied proposal's, which a later run reads as history), the command line and the logs.
- **Checks.** [`test_agent_text.py`](../utk_curio/backend/tests/test_agents/test_agent_text.py) starts the backend and fails on a file in `agents/` no manifest lists or a marker left in a render. It also checks that a marker no field defines stops the start, that a page cannot include itself, that a `curio:` path cannot lead out of the base entry, and that no list shows the base entry. [`test_generated_contracts.py`](../utk_curio/backend/tests/test_agents/test_generated_contracts.py) checks each fact the text states against the code that owns it; `test_prompt_references.py` checks every tool, capability, template, helper, dataset and model a page or prompt names against the code and catalogs that define it; `test_pip_wheel_layout.py` renders every page from a pip install. [`test_python_prose.py`](../utk_curio/backend/tests/test_agents/test_python_prose.py) checks that each text the runtime composes a run's turns from is its page's, that each number and name it states is filled from the code that owns it, and that none of it is still a string in Python. [`test_knowledge_pages.py`](../utk_curio/backend/tests/test_agents/test_knowledge_pages.py) fails on a knowledge page no page or prompt includes, a built-in template no page names by its `{{template.label:...}}` marker, a kind of chip the runtime resolves (the shared cases table) that no page shows, and a function node code calls that the functions page does not give. `test_node_functions.py` holds the functions page's shapes and ties the arguments it says name a catalog's item to the calls the backend resolves ids from (`DATASET_PATH_CALL_RE`, `MODEL_CALL_RE`, `SECRET_CALL_RE`), and [`test_node_functions_sandbox.py`](../utk_curio/backend/tests/test_node_functions_sandbox.py) compares the page with the functions node code gets in process, in the isolated child and in JavaScript. [`test_messages.py`](../utk_curio/backend/tests/test_agents/test_messages.py) reads every `agent_text.message` call in `utk_curio/`: each names a section of `messages.md` and gives exactly the values its section has places for, every section is some check's, an edit to the page reaches what the checks say, and no message is still a string in Python. [`test_prose_guard.py`](../utk_curio/backend/tests/test_prose_guard.py) fails on any string in `utk_curio/`'s Python, the tests left out, whose words run past 200 characters, unless it is a message to users or code: the text of a log line, a warning or a command-line argument's help, an exception raised outside the agents package, or an entry of its `USERS` or `CODE` list, each with who reads it.

- **Prompt fields.** `contracts.PROMPT_FIELDS` is the one registry of what a page or prompt may state from code, and each field is one function that reads its source when the file is rendered. Its module-level imports are the standard library and the shared constants' reader: a field imports the module that owns its fact inside its own function.

  | Field | Renders | Source |
  |---|---|---|
  | `trill.schema`, `builtin.nodes`, `builtin.control`, `builtin.inputs`, `builtin.outputs`, `builtin.input_count`, `builtin.output_count`, `builtin.interaction`, `autk.grammar` | The preamble's Trill block, projected from [`docs/schemas/trill.v1.json`](schemas/trill.v1.json) to the fields `contracts.TRILL_PROMPT_FIELDS` names; its lists of built-in templates (description, control, port types, the connections an input accepts, output cardinality, interaction support), naming each template by its label; and its section on Autark documents (see [The Autark Schema](#the-autark-schema)) | The Trill schema, the built-in manifest, `input_capacity`, the vendored Autark schema |
  | `agent.name:<agent id>` | A built-in agent's display name | The shipped agents' manifests (`builtin.list_builtin_manifests`) |
  | `template.label:<package id>/<template id>` | A built-in template's label | The built-in manifest |
  | `inputs.handles` | The handles of a node's input circles, `"in", "in_1", "in_2", ...` | `workflow_spec.slot_handle_id` |
  | `inputs.chip:<k>`, `inputs.chip:<k>.<column>`, `inputs.chip:<k>:<layer>`, `inputs.chip:<k>:<layer>.<column>` | The chip node code reads input *k* by, a column of it, one of its layers or a column of that layer, `[!! input_0:roads !!]` | `code_references.reference_text`, `input_reference_inner` |
  | `inputs.stacked_column:<column>` | The chip of a column of every input's rows stacked, `[!! inputs.sunlight !!]` | `code_references.stacked_reference_inner` |
  | `selections.reference:<name>`, `selections.id_cap` | The reference node code places a selection tag by, `[!! selection picked !!]`, and the most ids a tag holds | `code_references.selection_reference_inner`, `SELECTION_ID_CAP` |
  | `builtin.not_code` | The built-in templates whose nodes hold no Python or JavaScript code, one per line | The built-in manifest, by the rule `builtin.control` uses |
  | `note.palette` | The colour names a node's appearance accepts | `note_palette.NOTE_PALETTE` |
  | `egress.calls_per_run` | The web calls one run may make | `egress_policy.MAX_CALLS_PER_RUN` |
  | `candidates.rows_per_lane` | The rows each lane of a candidates card holds | `content._CANDIDATES_MAX_ROWS_PER_LANE` |
  | `node_context.runtime_keys` | The keys of a node row's `runtime` block | `node_context.RUNTIME_BLOCK_KEYS` |
  | `input_contract.single`, `input_contract.several`, `input_contract.gathered` | The `inputContract` kinds a node's inputs can have | `input_contract.KIND_SINGLE`, `KIND_SEVERAL`, `KIND_GATHERED` |
  | `vega.runtime_field:<name>` | A field Curio adds to every row a Vega-Lite node reads | `document_validation.RUNTIME_FIELDS` |
  | `backend.handler_pattern`, `backend.timeout_classes`, `backend.server_code_permission`, `backend.server_network_permission`, `backend.data_dir_env` | The package backend contract's names | `packages/domain/backend_contract.py` |
  | `include:<path>` | A page of the base entry, rendered, whole | The page |
  | `vega.starter_ladder`, `autk.starter_ladder` | A starter ladder, one line per rule in order: the layers and column roles it needs, the mark or family it writes, and its description | `contracts.VEGA_STARTER_LADDER`, `AUTK_STARTER_LADDER` |
  | `starter.dtype_roles` | Which pandas dtypes give which column role, in the order they are tried | `contracts.DTYPE_ROLES` |
  | `vega.schema_url` | The `$schema` of a Vega-Lite spec Curio writes | `contracts.VEGA_SCHEMA_URL` |
  | `image.columns`, `image.column:<name>`, `image.extensions`, `image.threshold` | The column names Simple View checks for images first, one of them by name, the extensions an image URL has elsewhere, and the share of a column's values that must be images | `contracts.IMAGE_COLUMNS`, `IMAGE_EXTENSIONS`, `IMAGE_MATCH_THRESHOLD` |
  | `suggested_prompts.max_chars`, `suggested_prompts.alternatives` | How many characters a suggested prompt holds, and how many alternatives a block holds | `content._PROMPT_MAX_CHARS`, `_MAX_ALTERNATIVES` |
  | `candidates.source_types`, `candidates.name_chars`, `candidates.text_chars` | The source types a candidates row may name, joined with pipes, and how many characters its name and each other text field hold | `content._CANDIDATE_SOURCE_TYPES`, `_CANDIDATE_NAME_MAX_CHARS`, `_CANDIDATE_TEXT_MAX_CHARS` |
  | `note.palette_choices`, `backend.timeout_class_choices` | The note palette joined with pipes, and the timeout classes joined with " \| ", as a JSON string lists them | `note_palette.NOTE_PALETTE`, `backend_contract.TIMEOUT_CLASSES` |
  | `models.search_max_rows`, `models.max_labels` | The most rows `models.search` returns, and the most labels a row lists | `contracts.MODELS_SEARCH_MAX_ROWS`, `MODEL_LABELS_MAX` |
  | `notes.max` | The most notes a `package.install` carries, which its mint keeps | `contracts.MAX_NOTES` |
  | `tools.wire_name:<tool id>`, `tools.delegate` | The name a run on native tools calls a tool by, and the native delegation tool's name | `tool_names.wire_name`, `DELEGATE_TOOL` |

To change agent text, edit its file in `agents/` (the base entry's README walks through it). A fact the code owns that no field states yet is a new field in `PROMPT_FIELDS`.

### The Autark Schema

The Autark grammar is defined upstream: autk-grammar generates a JSON Schema from its TypeScript types and publishes it with each release. [`schemas/autk-grammar.v1.json`](../utk_curio/backend/app/agents/schemas/autk-grammar.v1.json) is a byte-for-byte copy of the released file, beside the module that reads it so an installed wheel carries it, and `autk-grammar.v1.source.json` records the release and the file's digest. [`scripts/sync_autk_schema.py`](../scripts/sync_autk_schema.py) vendors a release; `test_autk_schema_vendored.py` checks the copy against its record offline, and the weekly `autk-schema` workflow re-fetches the release and fails on a difference.

Everything Curio says about Autark documents is read from that file, except that a node draws one view (`contracts.AUTK_ONE_VIEW`, see [Referencing Upstream Data in Autark Nodes](#referencing-upstream-data-in-autark-nodes)):

- **Validation.** `document_validation.validate_autk_grammar` validates a document against the schema, choosing the validator by the schema's draft. An error inside a field that takes one object or a list of them is explained by the branch that fits the value, and a missing field is named with its description from the schema. Two rules sit on top, because no schema form states them. A document with a map and a plot, or that lists more than one map or more than one plot, is refused first, with the node's own sentence (`contracts.autk_one_view_problem`), whatever its views hold. And the document must load, compute or draw something, and a map must list a layer. Without `jsonschema` or the schema file, any other document is *unchecked*, never invalid.
- **Refusal text.** `contracts.render_autk_shape` renders the schema as one line naming the families and what each requires, for the refusal a reply that is not a document gets; its words are the message `document.autk-shape` of the base entry's `messages.md`.
- **Preamble.** `contracts.render_autk_region` renders the preamble's section on Autark documents: the data source types and what each requires, the compute fields, the map and plot requirements and the closed enums. Its words are the sections of the base entry's [`autark-grammar.md`](../agents/agent.curio.builtin@1/autark-grammar.md), one per line, each filled from the schema (`agent_text.fill`); the code writes the list marks and the lines of the schema's own choices between them. Its lines on `map` and `plot` say `AUTK_ONE_VIEW` in place of the schema's descriptions, which allow several.

---

## Agent Prompt Composition

Every system turn an agent receives is built by one function, `contracts.compose_system`, from fixed slots in a fixed order. The attached run (`services._prepare_run`) and the delegated run (`delegation.run_delegate`) both call it.

| Slot | Holds | Owner |
|---|---|---|
| preamble | The base entry's `default_preamble.md`, which a manifest names `curio:default_preamble.md` (every built-in's), an imported definition's own `prompts.system`, or none | the repository, or the definition |
| instruction | Exactly one: the agent's `instruction` prompt, the invoked mode's, the definition's `autk-grammar` prompt for an Autark document under its reply schema, or the attachment's edited intent | the repository, or the user |
| configuration | The catalog settings the run reads, framed as data | the user |
| tool protocol | How to ask for a tool: the granted tools and the `toolRequest` syntax, or on native tools one line on calling them; with the `datasetCandidates` schema for a run that can search the catalog | the runtime |
| runtime | The template roster and the enlistable templates (one line per template: its id, label, description cut at 140 characters, and the widgets a package template declares, `turns/roster.py`), the worked examples and the delegation paragraph, each its own slot | the runtime |

A run selects its instruction and never appends to one. An edited intent replaces the instruction slot only, and everything a user wrote precedes every runtime-owned slot. A delegated run carries the first three slots, plus the worked examples when its mode takes them: it is tool-less and depth-1.

**The runtime's words.** What the runtime says in these slots is text of the base entry, [`agents/agent.curio.builtin@1/`](../agents/agent.curio.builtin@1/), read from the backend's start-up render like any page. A page the runtime composes from holds one section per text, a `## <name>` line and its text, which `agent_text.section` reads by name:

- `protocol.md`: the tool protocol (the follow-up prompts a run may suggest, the `toolRequest` syntax or the line on native tools, the `datasetCandidates` schema) and the delegation paragraph (`content.tail_instruction`, `content.delegation_instruction`).
- `frames.md`: the line that frames the configuration, the canvas context, the dataflow block and a delegated task's inputs, the worked examples' heading, and the headings of the template rosters.
- `dataflow-block.md`: the dataflow block's headings and the lines of its cut list (below).
- `tools.md`: each tool's description, the one a run on native tools gets in its place, and the text of each of its parameters (`tools.tool_text`). The registry in `tools.py` holds each schema's shape and asks the page for each parameter's text by its path.
- `delegate-contracts.md`: the reply contracts a delegated run receives in its inputs, each one block fenced as `json` (`turns/delegates._contract`), and the rule a delegated Dataset Finder answers to.
- `conversation-title.md`: the title call's prompt. `keyword-types.md`: the keyword types Curio ships, the setting's default.

The code puts a run's own lists after the sections that end in a colon: its granted tools, its delegates, a roster's templates. In `delegated-task`, the agent that delegates and the capability it asks for fill `{parent}` and `{capability}`. A number or name this text states from code is a marker: the web call budget, the bounds of a suggested prompt and of a candidates row, the source types a row may name, the note palette, a package backend's timeout classes and handler name pattern, `models.search`'s bounds, a tool's native name and the delegation tool's, and the Node Builder's name.

**The dataflow block.** A run that writes code also receives what its dataflow can use: one block of at most 8,000 characters (`MAX_CHARS` in [`domain/dataflow_block.py`](../utk_curio/backend/app/agents/domain/dataflow_block.py)), composed in one place, `compose` in [`application/dataflow_block.py`](../utk_curio/backend/app/agents/application/dataflow_block.py). It is no slot: a package's text can come from anyone, so the block rides a user message framed as the canvas context is, its first line the `dataflow-block` section of `frames.md`, the rest of its words the sections of [`dataflow-block.md`](../agents/agent.curio.builtin@1/dataflow-block.md).

- **Who gets it.** A chat run that can write a node's code reads it before the canvas context: one that holds `node.content.write`, or `node.create` when its agent composes no notes (`writes_code`). An agent that declares `research.notes.compose`, as the Researcher does, places notes with `node.create`, so its chat gets none. A delegated run of `node.content.generate` or of a package-writing mode reads it before its task: chat delegations, Solve's runs verified or not, **Solve this node** and validate-node. `run_delegate` takes it as `dataflow_block`, which only the runtime passes, so nothing a model writes into a delegate request's inputs becomes it. A block that would hold nothing is not sent.
- **What it holds.** The Data Catalog's rows installed in the dataflow, each with the loader line the catalog gives it; the model packages the dataflow's lockfile names that the account holds, each with `model_loader_line`; the account's Node code keys by name, host and delivery, never a value; and, for a run that writes one node, its template (`packages.template_for_writing`): the roster entry's whole description, the starter the starters feed reads (`starters.template_starter`), and the functions of the modules `modules_for_node` makes importable for the node, read with `function_nodes.read_functions` (`function_nodes.node_functions`), its own package's first. Other templates stay roster lines.
- **The cut.** `layout` keeps whole lines by priority: the template's description, its starter, the functions the starter imports, the keys, the models, the datasets, then the other functions, those with a docstring first. Its last part says how many of each kind it left out and, to a run that holds `catalog.search`, `models.search` or `packages.resolve`, the tool that lists them.
- **One read.** A chat turn reads the dataset rows once, before it composes its block, and its delegated runs reuse them (`dataflow_datasets` in the turn's loop context). A Solve job holds no request, so the grounding base reads them once, from the listing the gate reads (`dataflow_datasets` in `turns/grounding._solve_grounding_base`), and the batch composes each node's block once.

**Cut lists.** A list an agent reads that stops at a bound says how many it left out, so a run shown part of a list knows it is part. The dataflow block's last part is its cut list (above). Each half of the template roster ends with `frames.md`'s `templates-left-out` line, its `{count}` the number left out (`turns/roster._left_out_line`, 60 lines). A read tool's result carries the count beside its list, first so the tool output bound never cuts it (`tools._cut`): `datasetsElided` from `catalog.search`, `packagesElided` from `packages.catalog` and `scenariosElided` from `scenarios.search`, 40 rows each, `modelsElided` from `models.search`, and `labelsElided` on a model with more than 40 labels. A tool-less Dataset Finder's `catalog` input carries `rowsElided`, and an authoring delegate's `existingPackages` `packagesElided`, 40 each. An upstream schema carries `columnsElided` past 60 columns.

**Worked examples.** The base entry's [`examples.md`](../agents/agent.curio.builtin@1/examples.md) lists every shipped dataflow (`projects/shipped.py`) once, under "Used" or "Not used", with one line on what it shows; its links are relative to its folder. [`turns/examples.py`](../utk_curio/backend/app/agents/application/turns/examples.py) reads it as rendered at start (see [Agent text](#agent-text)) and on every run scores each "Used" dataflow by the words it shares with what the run knows: the user's message, the dataflow's task, and the attached node's goal and template type, or for a delegated run its subtask, workflow goal and node context. Its line, file name, task and categories count; short and common words do not. A dataflow that uses the node's template type or one of the project's datasets ranks higher, but only a shared word selects one. The top two become one block: a heading, then each line and its Trill without layout, categories or datasets, up to `MAX_BLOCK_CHARS`; an example that does not fit is left out. The block is chosen per run, so it is a runtime slot and the cached preamble stays the same. A built-in takes it when its shipped manifest says `workedExamples`, at the top for its instruction or on a mode's capability (`builtin.gets_worked_examples`): the Dataflow Builder, the Node Builder (its chat, and its `node.content.generate` mode under either instruction) and `workflow.suggest`. A project marked by an evaluation (`dataflow.evaluation`) never shows the example its fixture is scored against, nor any example that shares a node or edge id or a code line of `SHARED_LINE_CHARS` (25) or more with it. An install without `docs/examples` gets no block and logs one warning. The Dataflow Builder can also read any "Used" example with the `examples.read` tool: with no key it lists each one's key, title and line (`listing`), and with a key it returns that example as the block shows it (`find`, `shown`). It follows the same `excluded_by` rule, so an evaluation project's example is left out of the list and refused by key.

The slots reach the provider apart. `contracts.system_message` puts the joined text in the system message's `content` and the slots beside it, and [`providers.py`](../utk_curio/backend/app/agents/infrastructure/providers.py) maps them per provider: Anthropic receives one text block per slot, with the preamble marked cacheable; Gemini a list of system instructions; an OpenAI-compatible server the one joined system message, since some local chat templates reject several. A system message without slots (the title call) is sent as its text.

A run loop takes a typed turn, `providers.ChatTurn` (text, native tool calls, stop reason), from `run_chat_turn` or `stream_chat_turn`; a bare string is a text turn, which is what a scripted test fake returns. `run_chat_completion` and `stream_chat_completion` are the text-only forms. The services module binds the two turn functions once, and the title call goes through the same seam, so one test fake answers a whole run.

Usage counts every input token as `inputTokens`, cached or not (Anthropic reports cache reads and writes apart from its input count), plus `cacheReadTokens` and `cacheWriteTokens` when the provider reports them. The ledger, a run's execution record and the evaluation report keep them.

What an endpoint can do beyond text is [`chat_capabilities.py`](../utk_curio/backend/app/agents/infrastructure/chat_capabilities.py)'s answer: native tools and a reply schema. Anthropic, Gemini and OpenAI's own endpoint are known from their APIs; any other OpenAI-compatible server is asked once per model with a charged one-tool trial (`providers.probe_native_tools`), recorded per account in `.curio/users/<u>/chat-capabilities.json`, its tokens on the ledger with the configuration's id. The scripted provider answers what a test scripted, fenced by default. A manifest's `providerRequirements` is a preference: nothing refuses a run over it.

- **Modes.** A capability that names an `instruction` (a `prompts` key) is a mode. A delegated run of it runs that prompt in place of the agent's `instruction`, and pins that prompt's digest. Two internal agents are built this way: each of the Dataflow Planner's six capabilities and the Dataflow Reader's two keeps its own prompt file, and the agent's `instruction` is its first mode's. A card keeps its own instruction for its chat and adds modes beside it. The Node Builder's are `node.content.generate`, `package.recommend`, which receives the `existingPackages` an authoring delegate does as its only candidates, and `package.build`, `package.extend` and `node.kind.author`, three modes on one prompt. The Researcher's are `research.verify` and `research.notes.compose`, and every capability it declares is a mode: its chat is its `instruction` alone. Its chat and its checking mode include the same checking rules, `{{research.verify_rules}}` (`contracts.RESEARCH_VERIFY_RULES`), and its chat and its notes mode the same notes format, `{{research.notes_rules}}` (`contracts.RESEARCH_NOTES_RULES`).
- **Which prompt a call reads.** `turns/prompts._instruction_key` is the lookup, and the code decides it, never the model. A chat run passes no capability and reads `instruction`. A delegated run passes the capability it was asked for and reads that capability's `instruction` key when the manifest declares one (a mode), else `instruction`. `delegation._prepare_child` then swaps in the definition's `autk-grammar` prompt for a `node.content.generate` run on an Autark node when the provider takes the reply schema. A delegated run is composed without the tool protocol, so a mode never calls a tool; what it needs, such as search results, a node's neighbourhood or the build-request contract, Curio puts in its inputs (`turns/delegates._enriched_delegate_inputs`).
- **Scoped delegation.** A `delegatesTo` entry may name the capabilities it delegates (`{"id", "capabilities"}`). `delegation.resolve` and the delegation paragraph honour the scope: an agent an entry names takes only what its entry delegates. The capability fallback reaches only the installed agents `delegatesTo` does not name: never an internal agent, which is reached only through a parent that delegates it, and never the parent itself, whose own capabilities reach it only through an entry naming itself. The delegation paragraph lists what `resolve` would run (`delegation.offered_capability_entries`): each capability `delegatesTo` offers, under the name of the agent that would take it, a visible delegate not installed yet under its own, then each capability only the fallback reaches. The native `delegate` tool and the grounding gate's hint to delegate discovery read the same list.
- **Own modes.** An entry may name the agent itself only in the scoped form, and only with capabilities that are its own modes (`manifest._check_self_entry`). The agent's chat runs its `instruction`; when the model asks for one of those capabilities, the mode runs as a delegated call, tool-less, and its answer returns to the chat. A task for no node opens no home attachment (`turns/delegates._run_delegate_traced`): like an internal agent's, its record rides the parent's turn. A `node.content.generate` task writes for the node its `nodeId` names; with a `nodeType` and no `nodeId`, for a new node of that template, whose content returns to the run for its `node.create`, its inputs and its dataflow block those of that template; with neither, for the node the agent is attached to (`turns/delegates._delegate_target_node_id`). Only a task for a node becomes a review of that node's content. The Node Builder's entry for itself names its content mode and its three package-writing capabilities; a draft its writing mode returns is minted at its own attachment, since it holds `package.draft.apply`. The Researcher names no entry for itself: it checks facts and composes notes in its chat.
- **Catalog settings.** `contracts.CATALOG_SETTINGS` defines each setting once: its key, JSON Schema and renderer, and the page of the base entry that holds its shipped default as one block fenced as `json` (`keyword-types.md` for the keyword types). [`catalog_settings.py`](../utk_curio/backend/app/agents/repositories/catalog_settings.py) stores the values an account changed in `.curio/users/<u>/catalog-settings.json` (the read never raises: a missing, corrupt or invalid value reads as the default) and renders the configuration slot for the keys a run reads, `inputs.requiredConfig` for every run and a delegated capability's own `requiredConfig`. A key no setting defines is skipped with a warning. The slot's digest is pinned as `configurationSha256`.

**Native tools.** An attached run whose configuration calls tools natively is offered its grants and its delegates as tools (`tools.native_tools`): each contract with the JSON Schema of its params (`ToolContract.parameters`), named by its id with each dot written as two underscores (`dataflow__read`), and one `delegate` tool whose `capability` lists what the agent may delegate. Its system turn carries a line on calling them in place of the tool list and the `toolRequest` syntax, and its delegation paragraph names the `delegate` tool in place of the `delegateRequest` syntax.

- **One path.** The model's first call becomes the request part a fenced block parses to, through the same parser and budgets (`parse_tool_request_verbose`, `parse_delegate_request_verbose`), and from there takes the fenced request's path: grant check, mint, delegate, round accounting. A fenced block in a native run is honoured too, and answered in kind.
- **Results.** A tool message answers the call, flagged as an error unless the status is `ok` or `proposed`; a call that cannot be read gets its errors back and spends a round. Every other call of the reply is answered as not run, and the last round offers no call (`tool_choice` none).
- **Per provider.** OpenAI receives `tool_calls` and `tool` messages, Anthropic `tool_use` and `tool_result` blocks, Gemini function calls and responses. Gemini's schema has no open objects, so one (a manifest, a delegate's `inputs`) is offered as a JSON string and read back as an object.
- **The fallback.** An endpoint that answers a request offering tools with a 400 or 422 (`providers.NativeToolsRefused`) gets the same round again on the fenced protocol. `services._RunConversation` keeps the fenced form of every round beside the native one, so the run carries on from where it was. Once that fenced call succeeds, the refusal is recorded for an endpoint the table does not know (`chat_capabilities.record_native_refusal`), and the next run starts fenced.
- **Records.** The execution record pins `toolProtocol` (`native` or `fenced`) for a run that can call anything, and `nativeToolsRefused` after a fallback. Sessions keep text only, so a conversation moves between protocols and configurations freely. A delegated run is tool-less, so it never changes protocol.

**Reply schemas.** A delegated `node.content.generate` run for a node whose grammar (the template roster's `grammarId`) is `autk-grammar`, by a definition that declares an `autk-grammar` prompt, on a configuration that takes a reply schema, holds the reply to the Autark document's schema ([`reply_schemas.py`](../utk_curio/backend/app/agents/application/reply_schemas.py)). The run's instruction is that prompt (`new_content_autk_prompt.md` for the Node Builder's content mode), and the pins record the `replySchema` by name and the prompt's `promptSha256`.

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
which connection keys and Data source keys use too: a 0700 directory and a 0600 file, written to a
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
2. An internal agent (`builtin.internal_agent_ids()`, the shipped agents whose
   `catalog.listed` is false) runs on its caller's configuration, always.
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

The resolved `ProviderConfig` carries `config_id`, `label` and `source`, and
its `api_key` is left out of its `repr`. Run pins record
`llm: {configId, label, baseUrlHost, source}`, ledger entries record
`llmConfigId`, and provider error text is redacted with the call's own key
before it is streamed, persisted, logged or returned.

---

## Agent Runtime

What an agent may change, what Solve checks before anything lands in a node, how saved keys reach node code, and how an evaluation measures a model. The user-facing side is in [AGENT-CATALOG.md](AGENT-CATALOG.md) and [USAGE.md](USAGE.md).

### Dataflow plans

A Dataflow Builder plan may add nodes, add connections, and remove, each part optional, so a plan that only rewires a connection is valid and needs no filler node. Three rules hold:

- **A planned node carries no code.** A plan node with content is refused when the plan is proposed (`proposals/plans._mint_dataflow_plan`), and Solve writes each node's content once the plan is applied. The orchestration rule names no case where a plan carries it.

- **A connection carries a kind.** `interaction` links two visualizations when one of them is a Vega-Lite or Autark node (`plan_topology.interaction_highlighters`), a visualization and a Data Pool node, or two Data Pools, `in/out` at both ends, bidirectional on the canvas, carrying selections, never data. It is refused anywhere else, by a message that names the node it was aimed at. The orchestration rule tells the agent to link two views directly and to add a Data Pool only for a Simple View that shows the selection, merged selections, a Vega-Lite chart that colors its own selection through `interacted`, or three or more views on one selection.
- **Data connections stay a DAG.** A plan whose data edge would close a cycle is refused when it is proposed, with the loop written out and the fix named. The check runs again at Apply against the live canvas, so a cycle drawn in the meantime stops the apply, and so does each connection a row or Connect all applies. A cycle the plan did not create is reported, never blamed on the plan.

Every removed connection is named on the card. A plan applied a part at a time (each row's Apply, Connect all, Simulation Mode) checks each connection against the dataflow the plan leaves, the edges it removes left out, as the proposal did. The whole-plan Apply after some rows creates only what they did not: a planned node a row created, a connection a row applied, or one already in the dataflow between the same two nodes, of its kind and on its input circle (`_existing_plan_edge`, the rule by which a row applies one as a no-op), is not created again. A connection that names no circle is on one no other plan edge between the same two nodes names, so a Spatial Join fed twice by one node keeps both feeds. The row or Connect all that completes it runs the plan's removals as the whole-plan Apply does (`plans._complete_plan_if_done`), first checked as Apply checks them, but for the shape digest the plan's own rows changed (`_check_plan_completion`): each victim's content pin and the cycle check. Its response carries `removedNodeIds` and `removedEdgeIds`, which the canvas bridge removes through the reviewed path (`plan-removals`, or `plan_removals` on Simulation Mode's stream). The result of every Apply ends with a `Topology:` verdict, `acyclic` or the path of a cycle still present (`_log_plan_applied`), which the agent is instructed to read before it claims a repair.

A planned node may declare its widgets, checked by the Widgets tab's own rules (`checkWidgetDef` and `checkWidgetValue` in `widgetModel.ts`, twinned in `execution/code_references.py` and pinned by `widgetChecks.cases.json`), and the apply writes them at `metadata.widgets`. A plan may also save scenarios (`domain/plan_scenarios.py`, `proposals/plan_scenarios.py`): a selection names plan refs or existing node ids, and a duplicate names an earlier selection, the ref each copy takes, and the widget values a copy changes. The grammar expands a duplicate into plan nodes and edges by the canvas's own rule (`scenario_catalog/domain/duplicate.py`, the twin of `duplicateSelection.ts`, pinned by `duplicateSelection.cases.json`), so the card reviews each copy as a node and each copied connection as one. A copy carries `copyOf`, which the apply turns into `metadata.copiedFrom`; it is created after its original, by the whole-plan apply and the per-node one alike. A scenario is saved once all of its nodes exist, with the next of `SCENARIO_COLORS` when the plan gives none, and is refused when another scenario took one of its nodes or its name since the plan was proposed. Its name is one no scenario of the dataflow has: the scenario chips color and order a dataflow's scenarios by name, so the mint sends a plan that repeats one back to the agent (`proposals/plan_scenarios.mint_errors`), and the apply checks names again (`apply_scenarios`). A plan is complete once its nodes, connections and scenarios all exist.

A planned node may also carry `spatialJoin`, a Spatial Join's operation and output (`agents/domain/spatial_join_settings.py`). Its keys are those of `$defs.nodeMetadata.spatialJoin`, and its values are judged by the join's own rule, `common/spatial.settings_problem`, the one the `/spatial_join` route answers with. The mint refuses it on a node whose template's `behavior` is not `spatial-join`, as `packages.template_behavior` reads it: the account's copy of the template, else the catalog's. The choices are the join's own, `common/spatial.PREDICATES` and `OUTPUTS`, which the tool schemas offer; tests hold the Trill enums, the node's two selects and the manifest's description to them. The apply writes it at `metadata.spatialJoin`, by the whole-plan apply and the per-node one alike, and the card's row names it. `node.create` takes it the same way, and a template whose content kind is `none`, such as the Spatial Join, is proposed without content. The canvas bridge hands it to the live node as a load does, and the preamble's Trill block shows its shape.

A Data Pool's conflict modes (`dataPool`, `agents/domain/data_pool_settings.py`) and a Simple View's image column (`simpleVis`, `simple_vis_settings.py`) take the same path, and `agents/domain/node_settings.py` walks the three settings for the grammar, the mint, the card, both applies, `node.create` and the canvas bridge. Each is judged by its node's own rule:

- **The pool's modes.** `utils/dataPoolSpec.ts` reads a value that names no mode as `OVERWRITE` and writes only the modes that are not `OVERWRITE`. So the mint refuses a value the pool would read as `OVERWRITE` without a word, and stores a setting as the pool writes it: an explicit `OVERWRITE` sets nothing. `dataPoolSpec.cases.json` holds the cases Jest and pytest both run, and tests hold the Trill enums, `ResolutionType`, the tool schemas and the agents' modes to one list.
- **The view's image column.** The view trims the name it reads and reads an empty one as every image column (`resolveImageColumnChoice`), so an empty name is refused and a name is kept trimmed.

A setting is refused on a node whose template's `behavior` is not `data-pool` or `simple-vis`. The card's rows, the plan's text preview and a `node.create`'s summary say each in its node's own words, such as `Conflict between visualizations: Merge (AND)` or `Image column: overlay_url`: the pool's selects, the view's picker, the card and the backend all read them from `src/contracts/nodeSettings.json` ([Shared Constants](#shared-constants)). The canvas bridge hands each to the live node as a load does (`dataPoolFromSpec` for the modes). `dataflow.read` rows show what each saved node's setting makes it do, its defaults left out: a pool's modes other than `OVERWRITE`, a view's column, and a join's operation and output other than `intersects` and `pairs`. The preamble's Trill block shows both shapes.

An agent changes a node already on the canvas with `node.settings.write` (`proposals/mint._mint_node_settings_write`): any of `dataPool`, `simpleVis` and `spatialJoin`, and `widgets` as `{name: value}`, for the node it names or the one it is attached to. Each setting is read by its node's own rule (`node_settings.parse_change`): a key it gives is picked as the node's select picks it, `OVERWRITE` and the join's defaults among them, a key it leaves out stays, and `{}` puts the whole setting back to its default, which for a Simple View is every image column. A setting the node's template does not keep is refused as a planned node's is, a widget value by the Widgets tab's rule (`widget_grammar.parse_values`, through `check_widget_value`), and a change that changes nothing is refused too, each in words from `messages.md`. The proposal pins what it touches (`_settings_basis`: the node's type, each setting it names as the node reads it, and each widget it gives a value to), so Apply answers 409 once one of them changed, and not when the node moved or another of its settings changed. Apply writes each setting as the node stores it (`node_settings.write`) and the widget values into `metadata.widgets`, logs the applied turn, and answers `appliedSettings` with the agent's name, which the canvas bridge hands to the node's own setters ([Editing features](#editing-features)). The card's lines say each change in the node's own words (`node_settings.describe_change`, `widget_grammar.describe_value`): a setting's label and value, `Image column: all` for every column, and a widget's label, else its name, with its value.

### Package drafts

A package draft (`package.draft.apply`) is the one way an agent makes a node type. `proposals/mint._mint_package_draft_apply` parses the build request, then holds every template the draft adds (each template of a create; in an extend, each one the installed target does not declare) to three checks before anything is built (`_new_template_checks`):

- **A justification.** The request's `justification` names the closest existing templates and why each is inadequate, in at most `_JUSTIFICATION_MAX_CHARS` (2,000) characters. It is review prose, not build input: it never reaches the build request or its digest, and the review card shows it before the draft's details.
- **No reuse territory.** A new template whose label is the label of a template the project can use (`available_templates`), or whose label's slug (`template_slug`) is that template's id, is refused with that template named.
- **Grounded code.** A new template whose nodes hold code (`template_content_kind` is `code`) passes the [source-grounding gate](#source-grounding) with its source file and the content of each node the draft creates from it. Its `source` block rides the card.

Each refusal names what to change and is a free correction. A draft the Node Builder's writing mode returns takes the same mint (`turns/delegates._mint_package_draft_from_delegate`), so a refusal goes back to the mode as a correction round. The mode learns the justification and the label rule from its prompt and from the build-request contract in its inputs.

### Required agents

The Dataflow Builder requires two agents: the Dataset Finder (resolving a data-loading node asks it for candidates) and the Node Builder (its Solve generates content through the Node Builder's content mode, and every node an applied plan creates is given one). The runtime calls each of them on a fixed path, not at the model's choice. The Node Builder in turn requires the Dataset Finder.

A dataflow that lacks an agent's required agents is repaired the next time the user acts on that agent: a run, an attach, an apply or a Solve. The missing agents are added through the same install path a click uses, and the chat names each one it added. Only declared required agents are added this way; a preferred delegate reaches the user as a review card.

### Source grounding

An agent never decides on its own that a file exists. Every piece of node content an agent authors (a Node Builder `node.create`, a content replacement, the code of each template a package draft adds, and every node the Dataflow Builder's Solve fills) passes one runtime **source-grounding gate** before it can become a review card or reach the saved dataflow:

| The code opens, fetches, calls or imports | Grounded only when |
|---|---|
| A local file path | The user typed that path in the conversation, or the Data Catalog resolves it. The portable `curio_data_path("<id>")` line the catalog's loader recipe emits counts by dataset id. |
| A URL | The runtime probed it in this run (2xx; 401/403 is accepted and labeled *credential-gated*), or a candidates card in this conversation already carried it as **Verified ✓**. A URL in the user's own message is not evidence: the runtime checks it. |
| Nothing (inline data in a data-loading node) | The user asked for synthetic or sample data; the card then says *Synthetic data*. |
| A catalog item, through a function Curio gives node code | The [functions page](../agents/agent.curio.builtin@1/knowledge/node-functions.md) says which argument names a Data Catalog dataset or collection, a Model Catalog model or a Node code key, and the gate reads it from there (`source_grounding.page_functions`). The id is a string in the call, and names one of the project's Data Catalog rows, a model package the account's store holds (what `models.search` lists, `<id>` or `<id>@<major>`), or a saved key. A refused model names **Add** in the Model Catalog. A chip in that argument is written first as the run writes it, with the node's widgets, wired inputs, the dataflow's shared tags and the node's selection tags (`code_references.resolve_references`, as `WorkflowSpec.node_code` calls it; `turns/grounding.py` `_chip_context`); where the gate has no dataflow, or the chip names nothing the node has, that argument is not judged. |
| A function Curio gives node code | Its `Engines:` line on the page names the engine the node's code runs in: the template's `engine` when its content kind is `code` (`source_grounding.code_engine`). A Vega-Lite or Autark template names `python` and its nodes hold a document, so no engine is judged there. A call of a `curio_` name the page does not give, which the code neither defines nor imports, is refused too, naming the functions that engine has. |
| A module a package ships | A run hands the node that module (`packages.modules_for_node`): its own package's, and those of the packages it depends on. A built-in node gets none. `packages.module_index` names the package that ships it, whether the account has it, and the templates whose nodes import it, for the refusal. A library's module is the sandbox's to judge. |

When the message being answered names Data Catalog datasets by id (in a Solve, the node's own goal does), or the user confirmed catalog rows for the node, code that reads catalog data must read one of them; another dataset read beside it is fine. A message that names none, such as "go ahead", takes the ids the user's previous message named; older turns never count. A Solve holds its content to these datasets whether or not it runs the content first.

The two mints (`node.create` and `node.content.write`) and Solve, on its verified loop and its unverified path, give the gate the engine of the node's template from the roster row they already hold and the dataflow they read, and the context (`turns/grounding.py` `_grounding_context`) carries the account's models, what resolves the node's chips and, for a Python node, the modules it gets. The rule Solve hands a content builder (`sourceGrounding`) names the calls the gate reads a Data Catalog id from, from the page. A package draft's templates are held to the page's engines and catalog items; the modules a draft's code imports are its build's to review, as libraries or as modules of the packages it names in `dependencies.packages`. A refusal made only of the code's own violations (an engine, a computed id, a model, a module) lists no source route, and a Solve round it refuses fails as `ungrounded-code` (`source_grounding.failure_kind`): no source is missing, so it starts no Dataset Finder and its failure names no source to pick.

Anything else is refused with the literal named and the allowed routes listed. The refusal is a free correction round for the agent, and a Solve that cannot ground a node marks it failed for an ungrounded source, with the remedy, instead of writing the code. The review card carries a **Source** block above the preview: the catalog dataset by title and id, the URL with its verification chip, the user-provided path marked *not checked by Curio*, or the synthetic label.

Once its sources are grounded, a chart's or a map's document is checked by the same gate as Solve's document check checks it (`turns/grounding._document_refusal`, through `document_validation.validate`, routed by the template's `grammarId`). That covers a `node.create`, a content replacement (so delegated content and a proposing Solve too) and Solve's unverified writes. Its references are resolved as far as the dataflow knows them (`WorkflowSpec.node_code_and_problems`): the saved node, or the node a `node.create` makes with the widgets it declares, and the shared tags. A reference nothing resolves yet, such as the input chip of a circle no edge reaches, is left as written, and the validator reads it as Solve reads one of a node the dataflow does not hold. Its fields are not held to columns, since a proposal's run is never handed them. The refusal is a free correction round, and Solve's unverified path fails the node as `document-invalid`.

Discovery follows the same order. Node Builder holds `catalog.search` (rows include the resolved path and the loader line) and can delegate `dataset.discover` to Dataset Finder: the tool-less child receives the first rows of the runtime's catalog listing as input, never a catalog the request carried (`delegates._dataset_discover_inputs`), its candidates are re-checked against the whole listing (`grounding._grounded_catalog_rows`) and probed by the runtime, and the two-lane card appears in the Node Builder's own chat. Selecting rows prefills an editable prompt, and nothing is proposed until it is sent. In the Dataset Finder's own chat the same card composes the reviewed `dataset.install` or the hand-off to Node Builder. A card in an agent's own reply is checked the same way before it is shown (`turn_loop._check_candidates`, both the blocking and the streamed round): its catalog rows against the whole listing, its external rows by the probe, and a card left with no row becomes an error card.

### The Dataset Finder on data-loading nodes

Applying a plan gives every created node a Node Builder, and every data-loading node its own Dataset Finder as well; the applied card says what it attached. The whole-plan Apply and the per-node apply (each row's Apply, and Simulation Mode's) do this the same way.

Resolving such a node goes to that Dataset Finder:

| The node | What happens |
|---|---|
| Its intent already names a source (a path the user typed, a Data Catalog dataset, a URL the runtime verified, or explicitly synthetic data) | Discovery is skipped, and the skip is recorded with the literal that grounded it. |
| The user's Data Catalog holds datasets | The first attempt is generated against those rows, and the grounding gate enforces them. |
| Nothing could ground it, or the attempt was refused for its source anyway | The runtime asks that node's Dataset Finder. The candidates appear in its chat, and the node's Solve result is pending, awaiting a dataset selection, with an **Open Dataset Finder** button. Nothing is generated, run or written. |

**Confirm source for this node** records the selection against the node. Every later Solve reads the record, so the loader is built from exactly the confirmed source; a round whose code misses it is corrected against that source, and discovery does not run again. A catalog row that is not installed yet keeps the node waiting for its reviewed install, and the applied install says how many nodes it unblocked. The confirmation reads a catalog row from the listing again, as it probes an external row again (`dataset_resolution.resolve_picks`): a dataset the listing no longer holds is refused, and whether one is installed is the listing's answer. A row the runtime cannot reach at confirmation time is recorded with that verdict and does not resolve the node.

Every external row also says what the user can do with it, read from the same probe and never from the model's prose:

| The row's access | What the card offers |
|---|---|
| **fetchable**: the data URL answered with data Curio does not download itself (an XML API, or a plain http link) | Confirming it starts the node's own builder on it at once. The loader is written, verified and lands as ordinary reviewed content. |
| **manual-download**: the data URL answered with a page, gated it (401/403/451), or served an archive the Discovery Catalog does not unpack (a tar, 7z, bzip2 or RAR). A zip or a gzip is data: the download unpacks it, so a plain https link to one is **Downloadable** | The card carries the portal's download steps (its URL, the page as it answered, the file format, the row's stated requirement) and an **Import dataset** button, the same Data Catalog import as the drawer footer. After the import, that dataset becomes the node's source and the builder starts on it, by id. The imported file records the row's link as its `discoverySource`, and a file already held is not registered twice. |
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
| **Nothing** (a Data Pool, a Simple View, a Spatial Join) | Nothing. These nodes are wired, not written: no model is asked for their content. | wired, not written |

A kind nothing here can validate is not written at all: the node stays pending with the reason.

- **Empty results.** A node that filters everything out fails. The common case is a join on two columns whose values are different kinds of thing, such as a community-area number against a census tract id. An empty result that is wanted is written in the editor by hand.
- **Emptied columns.** A result can keep its rows and hold nothing: a left join whose keys do not match fills the other side with nulls. Curio reads the columns a node emptied (all null, and not already null in the input they came from) and fails the round naming them, with the same diagnosis a zero-row result gets. The content contract tells the generator never to fabricate values, never to fill nulls, and never to let a join that matched nothing stand; saying in one line that two datasets cannot be joined is an accepted answer.
- **Absent output.** A node whose code ends in `return None` stores an artifact typed `null`. The run journal, the consumer type check and the shape check each name that absence as a failure, and the refusal quotes the node's own conclusion back: returning that sentence as the whole answer, with no code, records it as the node's outcome. An output type Curio does not recognize is accepted: absent and unknown are different things.
- **Empty renders.** A document that draws nothing is an empty render (see [Render Outcomes](#render-outcomes)). Solve corrects the document when the cause blames it, and when no rows arrived it leaves the document alone and reports the upstream. A chart over rows with nulls counts only the rows that hold a usable value in the plotted fields. A partial loss, such as an Autark map that drew some of its layers, keeps its success. A chart meant to be empty reads as a failure, and a renderer that cannot count what it drew makes no claim.

A failing node carries its reason in its own body, one line, expandable, read from the same runtime record the agents read, so it survives a reload.

### Dashboard tiles

A dashboard draws its tiles from the outputs saved with the dataflow, so the page is refused when a pinned Autark tile's spec has data sources of its own, which it would fetch when the page draws (`projects/dashboard_payload.py`). That check is one public predicate, `tile_loads_its_own_data`: the node is pinned (`is_pinned`, `dashboardPinned` on the saved node), its template declares the Autark node's behavior, and its spec has a non-empty `data` list. The dashboard's refusal asks it, and so do the agents: `agents/domain/dashboards.py` `refusal` asks it of the saved node with the spec an agent wrote as its `content`, reading the templates with `TemplateGrammars.for_account(user_key)` as the dashboard reads the owner's.

- The `node.content.write` mint sends such a spec back with `dashboards.tile-loads-own-data` (`messages.md`), which names the remedy: the data in a node of its own upstream of the tile.
- Solve ends the node on it, since that node is not one Solve can add: the verified loop fails the round in `_dashboard_gate`, after `_map_edits_gate`, and stops with `blocker`, and the unverified path fails the node. Either way the node's result carries the remedy `{"kind": "dashboard-tile", "nodeId": ...}` (`dashboards.remedy`), one of `rounds._USER_ACTION_REMEDIES`: the node waits for the user, so a later pass of the session leaves it until its blocker signature changes, as when a node is added upstream of it. The remedy has no action; the failure says what to do.
- Code the node holds already is the user's own and is never refused. `node.create` and plans need no check: they make only new nodes, and no agent pins a node.
- `dataflow.read` gives a pinned node's row `"pinned": true`. A plan's removals carry `"pinned": true` for a pinned victim, whose preview line says the tile leaves the dashboard; the review card marks such a removal and counts the tiles in its effect line (`reviewCardText.ts`).
- Agents learn the dashboard from `knowledge/dashboards.md`, which the preamble includes; `test_dashboards_grounding.py` holds the page to the row and to `DEFAULT_PAYLOAD_LIMIT_BYTES`.

### The run journal

Every execution leaves a record wherever it ran. A node's code in the sandbox, a validation run the agent runtime drove, and a render in the browser (a Vega-Lite chart, an Autark map, a Data Pool, a Simple View, a Spatial Join, a Data Export) all write the same per-node journal, each stamped with the `origin` that produced it. An agent attached to a node reads that record.

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
| fails | The failure goes back to the content generator with the traceback, the previous attempt, the grounded sources, what its inputs contain (the columns, dtypes and row counts of the frames feeding this node, in circle order), and a fresh probe of the URL it fetched (a `400` after a reachable base URL is a wrong request shape, not a dead endpoint). The corrected code is grounded again and re-run. |
| keeps failing | Corrections continue while the time budget allows, as many attempts as fit: a node solved on its own has its repair budget, 15 minutes by default, and a node in a Solve session has what is left of the session's. The attempt cap sits above what that budget affords. A repeated candidate does not end the loop: after two repeats the next correction is told it repeated itself and must change approach, and only an eighth repeat stops it. Whichever bound stops the loop is named: the attempt cap, the node's or the session's time budget, or a repeated attempt. |
| still fails | Nothing is written. The node shows failed, and every attempt appears in the chat as its own card, with the exception line, the frame that raised it, and the code that attempt ran. |
| cannot run (sandbox unreachable) | The node stays pending with the reason, never failed: an outage is not a content failure. |

The loop reports why it stopped as `stoppedBy`, and the failure sentences, the attempts card and the per-node Solve row say it with that reason's phrase, from [`solveStopReasons.json`](../utk_curio/frontend/urban-workflows/src/contracts/solveStopReasons.json), which the frontend imports and `contracts.SOLVE_STOP_REASONS` reads (see [Shared Constants](#shared-constants)):

| `stoppedBy` | When | Phrase |
|---|---|---|
| `rounds` | The loop makes every attempt `--solve-max-attempts` allows before the time budget is spent | the attempt cap was reached |
| `budget` | A node solved on its own has spent its repair budget (`--solve-node-budget`) before its next attempt | this node's time budget was spent |
| `session` | A node in a Solve session has spent what is left of the session's budget (`--solve-session-deadline`) before its next attempt | this session's time budget was spent |
| `repeat` | The content builder repeats the previous attempt, changing only comments or spacing, for the eighth time | the builder repeated itself |
| `decline` | A data-loading node's content builder answers in one line, in place of code, what its source needs, such as a key, a path or a URL | the builder declined: it needs something from you |
| `answer` | The content builder of any other node whose content is code answers in one line, in place of code, why the node cannot be done, such as two inputs that cannot be joined | the builder answered instead of writing code |
| `generation` | The content builder's run fails, so there is no candidate to check | the builder could not run |
| `blocker` | An upstream node has no content, validation refuses the slice (a cycle, or more nodes to run than `--validation-node-limit`), a valid document's last render drew nothing because no rows reached it, or a pinned dashboard tile's spec loads its own data ([Dashboard tiles](#dashboard-tiles)) | something outside its code blocked it |
| `infrastructure` | The sandbox cannot be reached, or the validation run itself raises an error | the sandbox was unreachable |
| `not-executable` | The sandbox does not run the node's kind, such as a Vega-Lite chart or an Autark grammar, and the document check finds nothing to correct | the sandbox cannot run this kind of node |
| `source` | A data-loading node's last attempt failed on its source (refused by the source gate, or declined for a missing one) and discovery has candidates for the user to confirm; the node waits for them, whatever ended the loop | a source you must confirm |
| `passed` | An attempt runs and passes every check | it passed |

- **Several inputs.** A node with several input circles receives each as its circle's variable, `input_0`, `input_1`, ... (`in`, `in_1`, ...). Play, Solve's validation runner and the generator's contract all read the circles from the handles. The generator receives an `inputContract` for the node with a slot table (each slot's input chip, node, goal and columns): `several` for several circles, each its own `input_k`; `gathered` for several edges on one circle, which is that circle's list, read by index; or `single` for one input, whose chip is that input's value. `list` is refused. Code that treats a gathered list as a value (`input_0.crs`, or `gdf = input_0` then `gdf.to_crs(...)`) is refused before the sandbox runs, judged with its chips resolved, with the slot table in the refusal.
- **One-line answers.** The content builder may answer in one line instead of writing code: its content mode and each refusal a round sends back offer it. The loop reads that line before any gate or the sandbox runs, on every node whose content is code, and stops on it with nothing written. A data-loading node's line declines (`decline`), and its failure ends with the remedy as a sentence of its own: add a connection key for the host, use the saved one, or provide what the line names. Any other node's line is the node's outcome (`answer`), which Solve gives as its answer in the builder's words, asking the user for nothing. A line Python reads as code, such as `input_0[0]`, is corrected like any other code, and a chart's or a map's document is never replaced by a line. Solve with `verify: false` reports such a line the same way instead of writing it. No review of the line is minted either: Simulation Mode's validate and a proposing Solve, run or unrun, report it as Solve does, so **Apply anyway** never writes it into a node.
- **Failure lines.** The exception type and its message lead every failure line and are never cut mid-word, an error the generated code raised itself is labeled as such, and "not fixed after N attempts" is always followed by the phrase of the reason that stopped the loop.
- **Budgets.** `--solve-node-budget` (default 900 seconds, the bound that normally stops a node solved on its own), `--solve-max-attempts` (default 40), `--validation-exec-timeout` (one run, default 300 seconds), `--solve-session-deadline` (how long one Solve session keeps managing the dataflow, default 15 minutes; a node in the session gets what is left of it as its budget) and `--solve-batch-deadline` (the outer bound on a batch, default 45 minutes). The launcher passes each to the backend as the matching `CURIO_SOLVE_*` or `CURIO_VALIDATION_EXEC_TIMEOUT` variable. An unusable value falls back to the default.
- **Apply never executes anything** and is never blocked by verification: Apply places the node as proposed, and the card says Solve is what runs it.
- **Background jobs.** A Solve is a detached job on the server, so closing the chat panel or reloading the page does not stop it. The agent's badge shows a running dot while the job is live, and opening the chat re-attaches to its progress. **Stop** ends the session after the current node finishes; a running fetch cannot be aborted. If the server stops mid-Solve, the session is marked interrupted the next time it is read: nodes that finished keep their content, nothing is replayed, and Retry starts a new execution linked to the interrupted one. This is a single-process job owner; a multi-instance deployment would need a durable one.
- **Waves.** A batch runs the plan the way Play would: in topological waves, roots first, each wave's nodes in parallel. A wave's verified content is written at the wave boundary, so the next wave generates and executes against the upstream code that ran, and a downstream correction is told what its upstreams produced (`upstreamOutputs`). An upstream that passed earlier in the batch is not run again: its recorded output stands in, and if that artifact has vanished the slice runs whole once before the result counts. A process that dies between waves keeps every persisted wave, and Retry continues.
- **Executable kinds.** Whether the sandbox can run a node kind is read from its template: a code editor (`hasCode`), a `python` or `javascript` engine, and no `backendHandler`. That covers every built-in Python and JavaScript kind and every package template that declares the same. A template with no code (Vega and Autark specs, data pools, the spatial join) is written and labeled as having no code to run, on the pill, in a review's attempt trail, and on the Node Builder's proposal card. Without a reachable template roster (the end-to-end runner over a raw file), a fallback name table answers instead.
- **Bounds.** The batch deadline is checked at every wave boundary and before every node; what it did not reach stays pending with the reason, the Solve card names it once, and Retry continues from there. A node whose validation would run more nodes than the validation bound (`--validation-node-limit`, default 25; an ancestor whose earlier output is reused and a pass-through node do not count), or whose upstream slice contains a cycle, is skipped with the bound named, and no correction is spent on it. The stale-run marker (15 minutes) is measured from the last completed wave. `verify: false` on the Solve request writes without running, for every kind.

### Node code keys

A key must never be a literal in node code: the code is saved into the dataflow, replayed in every proposal preview, recorded by the runtime journal on every run and exported with the project. A key node code reads (a connection key in the backend, [`users/connection_keys.py`](../utk_curio/backend/app/users/connection_keys.py)) is saved once under a name bound to a host, as a **Node code** key on the **API keys** tab of API Settings, through a masked field that never reads the value back, and node code reaches it only as `curio_secret("<name>")`. Saving a name already bound to another host is refused with 409 unless the request says `replace`, which the form's **Replace the host binding** sends.

- **At run time.** The runtime resolves the names the code uses, for Play and for Solve alike, and hands the values to the sandbox inside the execution request, where they exist only as that callable in the node's namespace: never an environment variable, never a file, never a log line. A key a node prints is redacted before the output leaves the sandbox. The saved dataflow, the journal, the proposals and the chat carry the name only.
- **For agents.** A content builder's grounded inputs list `availableSecrets` with the line to copy and how the API expects the key (`query:<param>`, `header:<Name>`, or in the code). The grounding gate accepts `curio_secret("<name>")` for a saved name (the Source block reads *Connection key · census · api.census.gov*), refuses an unknown name listing the saved ones, and refuses a credential-shaped literal before anything runs. When a saved key is bound to the host a failing request targets, Solve probes that request with the key and tells the correction what the keyed request answered, redacted. When no key exists, the content builder declines in one line and the node's failure ends with **Add key for** and the host, which opens the node code key form in API Settings with the host filled in.
- **Storage.** The store is a 0600 file under the user's own directory (unreadable by isolated node code), written the same way as `llm-configs.json`; it is not encrypted at rest. A published dataflow carries key names, so whoever installs it saves their own key under the same name. The shared guest account (authentication off) shares one key store with every other guest, and API Settings says so. Under `--deploy` no guest has a key store: `storage_key_for` refuses a guest with a 403, and the store lists and resolves nothing for the `guest` key, so keys saved there without `--deploy` are not sent. On the client, `isHostedGuest` (`components/apiSettings/useHostedGuest.ts`, with its hook `useHostedGuest`) is the one check for such a guest: API Settings shows it no key form, and **Add key for** and **Save as API key** do not render for it.
- **Typed keys.** The code editor watches for a key typed into a node's code and shows a non-blocking hint naming the line, with **Save as API key**, which opens the same form. Nothing is refused, rewritten or sent: the finding stays in the browser tab.

### Evaluation

`agents/evaluation/` is an offline library that the reconstruction tests and `utk_curio/tools/agent_eval.py` use to measure whether the Dataflow Builder can rebuild a shipped example from its prompt fixture under [`docs/examples/prompts/`](examples/prompts/README.md). The agent receives the prompt and nothing else. The run is the ordinary product path in a project marked with `dataflow.evaluation` (the Dataflow Builder attached, one message, Apply, then Solve), and deterministic code compares what lands on disk with the example: template ids and roles, topology, dataset and package references, invented names, node intents and Solve's verdicts. A construct the agent contract cannot express is a named capability gap, and a live run writes a report that gates nothing. `agent_eval run` writes `eval/<runId>/report.json` and `report.md` in Curio's state directory (`.curio/` in the folder it runs from, or `CURIO_STATE_DIR`), or under `--out`; `--model` runs on a temporary copy of the Dataflow Builder's configuration with that model and puts the Builder's choice back afterwards.

```bash
# the deterministic tiers (offline, no stack)
pytest utk_curio/backend/tests/test_agents/test_example_fixtures.py \
       utk_curio/backend/tests/test_agents/test_example_reconstruction.py

# what the fixtures say
python -m utk_curio.tools.agent_eval list

# a live evaluation against a running stack
export CURIO_EVAL_LIVE=1
python -m utk_curio.tools.agent_eval run --token "$CURIO_EVAL_TOKEN" --tier T0
```

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

// packages/model.curio.ddrnet23-slim@1/manifest.json
"dependencies": {
  "python": {
    "onnxruntime": ">=1.17"
  }
}
```

Spec syntax accepts PEP 440 comparators (`>=2.0`, `~=4.30`, `==1.5.0`), bare versions (`1.2.3` → treated as `==1.2.3`), npm-style carets (`^0.14` → rewritten to `~=0.14`), and empty string for "latest".

### Install paths

- **At `curio start`**, the launcher ([`cli/dependencies.py::install_manifest_dependencies`](../utk_curio/cli/dependencies.py)) walks every installed manifest (`packages/curio.builtin@*` from the catalog source + every user store under `.curio/users/<u>/packages/`), unions their `dependencies.python` via [`versions.merge_python_deps`](../utk_curio/backend/app/packages/domain/versions.py) (which surfaces range conflicts as warnings instead of silently last-write-wins), and pip-installs the merged map via [`pip_runner.install_python_deps`](../utk_curio/backend/app/packages/infrastructure/pip_runner.py). Already-satisfied deps are skipped via `importlib.metadata.version`, so the steady-state cost is about a second with no network.

- **At catalog install time** (`/api/packages/projects/<id>/install`), when the user installs a package from the drawer, [`store_install._ensure_user_store_install`](../utk_curio/backend/app/packages/application/store_install.py) copies the files, then calls `pip_runner.install_python_deps` on the freshly-installed manifest. The Install button stays busy until pip finishes; heavy installs (`torch`, ~3 GB) can take minutes.

- **At catalog uninstall time**, `prune_unreferenced_packages` walks every other still-installed package's manifest, finds the deps the pruned package declared that no other surviving package still requires, and pip-uninstalls only those (ref-counted shared deps survive).

### Framework requirements and standalone libraries

The framework needs to boot before any manifests can be walked, so `pip install -r requirements.txt` (or `pip install utk-curio`) seeds enough of an env that the launcher can read `manifest.dependencies.python` and continue. A package's heavy libraries are not in the framework requirements: they install when the user clicks Install in the catalog, and a Transformers model's `torch` installs when the model is added to the Model Catalog.

Standalone libraries the user adds via the [Installed Libraries modal](EXTENDING.md) (canvas → File → Installed libraries) sit in a third bucket, per-user JSON at `.curio/users/<u>/installed-libraries.json`, and pip-install through the same `pip_runner`, with ref-counted uninstall against every installed package's manifest.

The same route is reachable without opening that modal: when a node run ends in `ModuleNotFoundError`, `/processPythonCode` carries a `missingModule` field naming the import and the distribution that provides it (`packages/missing_import.py`, sharing `dependency_scanner`'s alias table and passing `pip_runner.validate_python_requirement` before it is offered), and the node's output panel renders an **Install** button beside the traceback.

---

## Discovery Catalog

The user-facing model is in [DISCOVERY-CATALOG.md](DISCOVERY-CATALOG.md) and the routes are in [Discovery Catalog Routes](#discovery-catalog-routes). The backend is `backend/app/discovery/`: `domain/` (manifest, parameters, source ids, formats, path templates), `application/` (catalog, browse, acquire, jobs, places, for storage sources scan, storage acquire, combine, index, cache and media, and service acquire), `infrastructure/` (credentials, rate limits, storage, transport, media directories) and `providers/` (one module per portal software, one per storage type, and one per service). Every outbound request from Python passes the egress policy described in [DEPLOYMENT.md § Outbound requests](DEPLOYMENT.md#outbound-requests); an OpenStreetMap download's requests leave from autk-db in Node ([Services](#services)).

### Sources and manifests

A source describes one portal or one storage source in `discovery/<sourceId>@<major>/manifest.json`, under the directory `--discovery-root` names when that is set. `infrastructure/storage.py` also reads an instance root, `.curio/discovery/` (`instance_root()`), for an operator's own sources: shipped sources are listed first, and an instance source whose id a shipped one uses is skipped with a log line. Only a shipped `folder` source may give a relative `root`, resolved against the repository. `.curio/discovery` is in `hardening.SENSITIVE_PATHS`, so a node running as `curio-exec` cannot add a folder for the backend to serve. Neither root is created eagerly. [`domain/manifest.py`](../utk_curio/backend/app/discovery/domain/manifest.py) validates a manifest, [`docs/schemas/discovery-source.v1.json`](schemas/discovery-source.v1.json) publishes the same contract, and `tests/test_discovery/test_schema_matches_validator.py` derives its assertions from the validator, so the two cannot drift.

- **Ids** (`domain/source_id.py`) are three to six dot-separated lowercase segments, the first always `source`. They name the publisher, never the software: `provider.type` can change when a portal migrates, and an id cannot.
- **`provider.type`** is one of `PROVIDER_TYPES`: the `PORTAL_PROVIDER_TYPES`, which must equal the keys of `PROVIDERS` in `providers/__init__.py`, the `STORAGE_PROVIDER_TYPES` (`folder`, `s3`, `huggingface`), which must equal the keys of `STORAGE_PROVIDERS`, the `SERVICE_PROVIDER_TYPES` (`autark-osm`, `mapillary`, `google-streetview`), which must equal the keys of `SERVICE_PROVIDERS`, and the `MODEL_PROVIDER_TYPES` (`huggingface-models`), which must equal the keys of `MODEL_PROVIDERS`. Asserts check all four at import time, and that each provider module's `PARAMETER_IDS` agrees with `PROVIDER_PARAMETER_IDS`, the ids a manifest may declare for it.
- **Parameters** ([`domain/parameters.py`](../utk_curio/backend/app/discovery/domain/parameters.py)) are what a download asks: `parse_parameters` reads a source's and a resource's lists, `merge` lets a resource's entry replace the source's by `id`, `validate_values` checks a request's answers on the server (unknown ids, ranges, a box against `maxAreaKm2`, a name holding a quote, bracket, backslash or line break), and `values_hash` keys them, ignoring a box's label. A manifest may declare only the ids its provider reads (`PROVIDER_PARAMETER_IDS`) and only the area forms it can send (`PROVIDER_AREA_FORMS`), and `providers/__init__.py` asserts each module's `PARAMETER_IDS` agrees.
- **Resources** (`_parse_resources`) are a storage or service source's declared contents, at most `MAX_RESOURCES` (64). A service resource (`_parse_service_resource`) has no `path`: it names its `kind`, its `format`, and what to ask for in `options`, `layers` for `autark-osm`. Each `path` compiles through [`domain/templates.py`](../utk_curio/backend/app/discovery/domain/templates.py) into a regex with typed captures (`str`, `int`, ISO `date`, or a strftime `datetime`) and a literal prefix, which a bucket lists under. A capture may not take a name a collection index uses for its own columns (`RESERVED_NAMES`), or `source_file` for a table. A storage source's `capabilities.formats` is derived from its resources, and a manifest that declares it is refused.
- **Formats.** `capabilities.formats` is an upper bound, intersected at download time with `DISCOVERY_ACQUIRABLE_FORMATS` (`csv`, `geojson`, `json`, `parquet`, `geotiff`): what a download lands as. That set is narrower than the Data Catalog's: a bare `shp` needs sibling files a single download cannot bring, and a `bundle` is a node output. An archive is not a format a manifest names: a downloaded zip or gzip is unpacked and what it holds is checked against the same set, a zipped shapefile and a GTFS feed as `parquet`.
- **Size.** `capabilities.maxDownloadBytes` may lower the server's ceiling, never raise it. The ceiling is [`domain/limits.py`](../utk_curio/backend/app/discovery/domain/limits.py) `max_download_bytes()`: `curio.py --discovery-max-download-mb`, passed as `CURIO_DISCOVERY_MAX_DOWNLOAD_MB`, 1 GiB by default. It is read when the backend starts, as `DEFAULT_MAX_DOWNLOAD_BYTES` (the manifest default and clamp) and `transport.MAX_DISCOVERY_DOWNLOAD_BYTES`. A download streams to a file under the account's `discovery/tmp/`, and a table added from a bucket streams to disk through `provider.stream` (`StorageAcquire._copy_remote`); neither is held in memory whole.
- **`provider.options`** is provider wiring and is never sent to a client.
- **`auth.secretId`** names the key a source sends, and `label`, `helpUrl`, `placeholder`, `note` and `operatorDefault` declare it (see [Credentials](#credentials)). Any well-formed id is a key: the sources that send one name the same id and declare it the same way.
- **Icons** are PNG only and resolved inside the source's own folder. An SVG served from the app's own origin can carry script.

Sources have no import route. A manifest names a host the server calls on a user's behalf, with a credential attached, or a folder it reads, so sources ship with the deployment or are written by the operator.

### Search

[`application/browse.py`](../utk_curio/backend/app/discovery/application/browse.py) runs a federated search as one request per searchable source, at most `MAX_FANOUT_WORKERS` (4) at a time.

- Each portal leg takes its own source's rate limit (`limits.requestsPerMinute`, default 30, per user and per portal, in process), so a fan-out cannot multiply one user's rate against a portal. A storage leg answers from its listing and spends none.
- Each leg reports a status from `LEG_STATUSES`: `ok`, `failed`, `refused`, `rate-limited`, `unsupported`, `needs-token`, or `scanning` for a storage source on its first scan. The response is a 200 either way. The page names the portals that did not answer, names the storage sources still being scanned on a line of their own and asks again until they answer, and ignores `unsupported`, which a link-only source reports on every search.
- Rows are interleaved round-robin across portals and storage sources. Only the single-source search paginates.
- The page debounces the search box and aborts the request in flight on every keystroke.
- Where Curio filters rows itself (a WFS server's layers, storage and service rows, and the roster's `q`), [`domain/text_match.py`](../utk_curio/backend/app/discovery/domain/text_match.py) decides a match: each word of the search, with case and accents folded away (`fold`), is in the row's text. A word of four letters or more ending in `s` may instead be found without the `s`, and one of five or more ending in `es` after r, s, z, x, ch or sh without the `es`. A WFS search then ranks its layers (`rank`): more words in the layer's name and title first, then the shorter name, ties in the server's order. Storage and service rows keep their declared order, and the roster stays sorted by name. The portals' own searches are theirs.

The roster is read from disk on every request, and search results are never cached. The one cache on the search path is a WFS server's capabilities document (`providers/wfs.py`, `CAPABILITIES_TTL_S`, 15 minutes per source), which lists layers rather than answering a query.

### Downloads

[`application/acquire.py`](../utk_curio/backend/app/discovery/application/acquire.py) fetches the bytes server-side and hands them to the Data Catalog's own importer, so the result is an ordinary `imported.x<uuid>` dataset.

- **Jobs** ([`application/jobs.py`](../utk_curio/backend/app/discovery/application/jobs.py)) are per account, process-local (a restart loses them), and swept `TTL_SECONDS` (15 minutes) after they finish. A job id owned by another account reads as unknown. Cancel is checked between chunks.
- **Concurrency.** `MAX_CONCURRENT_DOWNLOADS` (2) per account, in `infrastructure/ratelimit.py`, shared by downloads, storage adds and **Cache files**. A job's worker is built inside its `try`, so a worker that cannot start still ends its job and gives its slot back.
- **Provenance and idempotency.** A download writes a `discoverySource` block (`sourceId`, `sourceName`, `resourceId`, `resourceUrl`, `finalUrl`, `fetchedAt`, `contentSha256`, and for a narrowed download `parameters` and `parametersHash`) on the dataset manifest, and `dataset_index_entry` mirrors it: a manifest field missing from the index vanishes from every listing. A request for a `(sourceId, resourceId, format, parametersHash)` already held answers 200 with that dataset and contacts no portal. Search rows carry `heldFormats`, the whole (not narrowed) datasets held by format, and `alreadyHeldDatasetId`, from one `UserDatasetRepository.discovery_resource_formats()` walk per page. A file imported by hand from a Dataset Finder row writes a `discoverySource` too, with `manual: true`, its link as `resourceUrl`, `fetchedAt` and `contentSha256`; a download and a hand import of the same bytes are one dataset, whichever arrived first.
- **`refresh: true`** fetches anyway. Identical bytes (by hash) mint nothing; different bytes mint a new dataset and leave the old one alone, since a saved dataflow loads a dataset by id. A storage row compares its listing's fingerprint first (each file's path, size, time and tag, and a shapefile's parts), which `discoverySource.fingerprint` or the `collection` block records, and a single file then its content sha. When a row is held twice, the lookups take the latest `fetchedAt`.
- **Format detection** (`domain/formats.py`), most trusted first: the format the provider put in the URL; the final URL's suffix after redirects; the `Content-Disposition` filename; the `Content-Type`; the first bytes (`PAR1` for Parquet, the TIFF magic, and a JSON probe that tells GeoJSON from JSON by looking for a geometry type). The result is checked against the source's formats, and anything unidentified is an error.
- **Bounds.** A `Content-Length` over the bound is refused before any body byte is read, and the stream is capped again while writing.
- **Archives** ([`application/archives.py`](../utk_curio/backend/app/discovery/application/archives.py)). `domain/formats.py` tells an archive apart by its first bytes (`PK\x03\x04` for a zip, `\x1f\x8b` for a gzip), its name and its content type (`ARCHIVE_CONTENT_TYPES`, `ARCHIVE_SUFFIX_KINDS`). A zip and a gzip (`UNPACKED_ARCHIVES`) are unpacked; a tar, 7z, bzip2 or RAR is refused by `refuse_archives`: on the provider's file name before any request, and on the response headers before the body, through the `before_body` hook `egress.download` and both transports take. What a zip or gzip holds:
  - a `.gz` is one file, named as the archive less `.gz` (or as its gzip header records), and lands as that file;
  - a zip holding one data file (`DATA_SUFFIXES`), documentation beside it left out, lands as that file; the format ladder runs on its own name and first bytes;
  - a zip holding one shapefile (`.shp` with `.dbf` and `.shx`, and `.prj` and `.cpg` when there) is converted by `convert_shapefile` (`shapefile_to_parquet` in [`datasets/install/shapefile.py`](../utk_curio/backend/app/datasets/install/shapefile.py)) and lands as GeoParquet in EPSG:4326; the Data Catalog's Import dataset reads a zipped shapefile with the same `unpack` and `convert_shapefile`;
  - a zip whose root or single top folder holds `stops.txt` and one of `agency.txt`, `routes.txt`, `trips.txt` or `stop_times.txt` is a GTFS feed. [`application/gtfs.py`](../utk_curio/backend/app/discovery/application/gtfs.py) reads each table with DuckDB, every column as text (`all_varchar`) and only `stop_lat`, `stop_lon`, `shape_pt_lat`, `shape_pt_lon`, `stop_sequence` and `shape_pt_sequence` cast to numbers, and writes `stops` as GeoParquet points, `shapes` as one line per `shape_id` in `shape_pt_sequence` order, and every other table as Parquet. The tables land as one layer group, `gtfs.x<hex>` (`GTFS_GROUP_ID_PREFIX`), each titled `<name> (<table>)`, which the Data Catalog shows as one **GTFS** entry;
  - anything else is refused, naming what the archive holds.

  Every member goes through the shared extractor, [`common/safe_archive.py`](../utk_curio/backend/app/common/safe_archive.py), which the node-package installer uses too: a member name with `..`, a leading `/`, a `:` or a NUL is refused (a backslash is read as a folder separator, so `..\x` is refused too; a package refuses any backslash), as are a symbolic link, a password-protected member and an archive inside the archive. Members are written under names Curio mints, and the bytes are counted as they are written: at most `MAX_ARCHIVE_MEMBERS` (1,000) files, `MAX_UNPACKED_BYTES` (4 GiB) per member and in all, and no member past 1 MiB that expands more than `MAX_COMPRESSION_RATIO` (200) times its compressed size. A download that unpacks records the archive's `contentSha256`, so the same archive downloaded again is held. The Dataset Finder reads the same tables: a zip or gzip link is fetchable and a plain https one downloads through the Direct URL source; any other archive is a manual download.
- **Files.** Bytes are staged under the user's `.curio/users/<id>/` tree. Remote filenames are sanitised, and the importer mints the dataset directory name, so no remote input reaches the filesystem path.
- **Errors** carry the server's reason ("'bundle.7z' is a 7z archive, which Curio does not unpack"), which the page shows as is.

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

**Caching a bucket's files.** [`application/cache_collection.py`](../utk_curio/backend/app/discovery/application/cache_collection.py) streams a bucket collection's objects to `media_work_root(user)/objects/<datasetId>/`, as a job, capped at 4 GiB per object and at `--media-cache-max-gb` (`CURIO_MEDIA_CACHE_MAX_GB`, default 20) per account, checked before any byte is fetched. A service's images land in the same folder, and the same check (`check_room`) runs on them before their collection is added.

### Services

A service is told where and what, and answers with one download. Its rows are its manifest's resources, with no network ([`providers/autark_osm.py`](../utk_curio/backend/app/discovery/providers/autark_osm.py) `rows()`), so they join a federated search the way storage rows do.

- **OpenStreetMap** (`autark-osm`) runs [`providers/autark_osm.mjs`](../utk_curio/backend/app/discovery/providers/autark_osm.mjs) as `node`, from the backend's process tree, with the request on stdin. The script imports the sandbox's autk-db (resolved by [`sandbox/util/node_runtime.py`](../utk_curio/sandbox/util/node_runtime.py), which the sandbox's JS nodes use too; see [The sandbox's Node.js packages](#the-sandboxs-nodejs-packages)) and calls `db.loadOsm` with the area as `{geocodeArea, areas}` or `{bbox}` and the resource's layers. A tag resource (`options.tags`, or a `tags` parameter) sends no layers and three autk-db tag sets instead, `tags_points`, `tags_polylines` and `tags_polygons`, one per geometry autk-db builds, each with the same tags, its entries checked again by `parameters.parse_tag_entry` before Node starts; each set is written as `<set>.geojson`. autk-db's progress phases come back as stage lines, and each layer as autk-db's `getLayer(name, { osmElements: true })` GeoJSON, in its workspace CRS (EPSG:3395): one feature per node, way or relation, with `osm_type`, `osm_id` and, for buildings, `building_id` (autk-db's number for the building the part belongs to). Surface polygons carry none of them.
- **Ceilings.** `MAX_SECONDS` (15 minutes) and `MAX_OUTPUT_BYTES` (512 MiB), each refused with a message naming it. The child runs in its own process group, so Cancel and the time limit kill everything it started.
- **Named areas' size.** Before Node starts, `_check_named_areas_size` measures named areas through the place search: `places.named_areas_box` searches each `"<area>, <place>"`, as the named-areas field does, and takes the box around every boundary with exactly that OSM name. `parameters.check_area_size`, the rule a drawn box passes, refuses that box over the area's `maxAreaKm2`. A name the search does not find is left to autk-db, which refuses it by name.
- **Into the Data Catalog.** [`application/service_acquire.py`](../utk_curio/backend/app/discovery/application/service_acquire.py) moves every position to WGS84 with pyproj (`to_wgs84`), keeping each feature's geometry type and properties and leaving out autk-db's feature id (`way/301`), which `osm_type` and `osm_id` give; [`domain/osm_values.py`](../utk_curio/backend/app/discovery/domain/osm_values.py) (`with_numbers`) writes the tags it lists as numbers in metres, km/h or counts, and a value it cannot read as one number as null. `service_acquire.py` then installs each non-empty layer as GeoJSON through `_install_imported_bytes`: one layer as an ordinary dataset, several under one `osm.x<hex>` group, the group a `.pbf` upload forms. The title names the area (`place_label`). A download counts once against the source's rate limit.
- **Its requests** go from Node to autk-db's fixed Overpass endpoint with `OVERPASS_USER_AGENT`, not through the Python transport. Under `CURIO_DISCOVERY_FIXTURES`, behind the same gate as the transport (`fixture_root()`), the script's `fetch` answers from `tests/test_discovery/fixtures/overpass/` and skips autk-db's pauses. A request is looked up first among the recorded answers, keyed by method, URL and a hash of the body (the script's `record` mode files live answers there), then among the mock answers in `mock.json`, which answer a query by texts it contains. `tests/test_discovery/overpass_mock.py` writes `mock.json`.
- **Mapillary** (`mapillary`), **Google Street View** (`google-streetview`) and **Overture Maps** (`overture`) are asked over HTTP, so `build_service` hands them the catalog's transport. Mapillary and Google Street View answer images: each answers an `ImageSet` of files it downloaded into a work folder; `service_acquire` indexes them with the storage collections' own `build_rows`, `write_index` and `collection_block`, writes the collection, and moves the files by rename into `media_work_root(user)/objects/<datasetId>/<file_id>.<ext>`, where `curio_load_collection` reads a downloaded collection's files (and `grant_to_child` opens each to the isolated child).
- **Mapillary** tiles the box under 0.0099 square degrees, the API's limit, splits a tile that answers its 2000 maximum in four (at most three times), takes images from every tile in turn, newest first, and looks thumbnails up afterwards by `image_ids`, fifty at a time, since a search that names them answers over the metadata ceiling. Thumbnails are fetched only from `options.imageHosts`, matched by host suffix after the address policy.
- **Google Street View** asks the metadata endpoint at points of a grid with the answer's `spacing`, in a fixed shuffled order, keeps each panorama once, stops when it has enough, asks at most `MAX_POINTS`, then downloads one image per panorama and heading and drops Google's grey placeholder.
- **Overture Maps** (`overture`, [`providers/overture.py`](../utk_curio/backend/app/discovery/providers/overture.py)) reads the STAC catalog's `latest` release, the release's `collection.json` for the resource's `options.theme` and `options.type`, and the item of each file whose box (the collection's `extent.spatial.bbox`, in the order of its item links, checked against the item's own `bbox`) meets the area. Each file is read by [`infrastructure/remote_parquet.py`](../utk_curio/backend/app/discovery/infrastructure/remote_parquet.py): its last 8 bytes, then its footer (at least the last 64 KiB, which pyarrow reads first), then each row group whose box statistics meet the area, one `Range` request per group computed from the footer's column chunk offsets. Every request goes through `transport.download`, to the catalog's host or a host in `options.dataHosts`; pyarrow reads from a `SparseFile` holding only the bytes fetched, and a read outside them raises. [`infrastructure/parquet_area.py`](../utk_curio/backend/app/discovery/infrastructure/parquet_area.py) plans the row groups (`plan`) and writes the rows whose box meets the area (and whose `subtype` is `options.subtype`, when set) with a `ParquetWriter`, one row group at a time, then copies them into the dataset's file with the source's GeoParquet `geo` metadata, its geometry box set to the rows kept (`write`). `MAX_JOB_BYTES` (512 MiB) bounds the footers and row groups together and is checked before any row group is fetched. `service_acquire` moves the file in with `_install_imported_path`, with `options.layer` as its `layerName`, so the loader snippet types it for an Autark map. Its recorded answers are made up: `tests/test_discovery/overture_fixture.py` writes GeoParquet files in Overture's layout, its catalog, and each byte range the reader asks for.
- **A GeoParquet file for an area** outside Overture is read by the same `parquet_area.plan` and `write`.
  - A Direct URL link: `DirectProvider.download_url` answers a `.parquet` link asked for an `area` with a `DownloadTarget` whose `area` is the box, and refuses an area for any other link. `DiscoveryAcquire._acquire_area` reads it with a `RemoteParquet` of unknown size, which asks for `bytes=0-0` first and takes the size from `Content-Range`; a server that answers the whole file trips the one-byte bound and is refused by name.
  - A bucket row: `scan.takes_area` gives the area to a `parquet` table row of a source that declares one (`s3` and `huggingface` may; `folder` may not), and `StorageAcquire._add_area` reads each file at the provider's `file_url` with the size its listing gave. One file lands as its part; several are staged as their parts, combined by `combine_tables.combine` as a whole row's files are, and written with the parts' shared `geo` metadata (`parquet_area.combined_geo`, which refuses parts in different coordinate systems). `check_addable(..., for_area=True)` skips the files' sizes, so a row over the download limit stays addable for an area.
  - Row-group boxes come from the `geo` metadata's `covering.bbox` columns, else Overture's `bbox.*`; with neither, every row group is read and each row's box is its WKB geometry's bounds (shapely). A file whose `crs` is not longitude and latitude is read with the area moved into it (`area_in`, pyproj `transform_bounds`). The bound is the download limit, on the bytes read. Both adds record `parameters` and `parametersHash`, so the same area is held. Their recorded answers are made up: `tests/test_discovery/remote_parquet_fixture.py` writes the files and each byte range the reader asks for.
- **A service that needs a token** is refused with 428 before any job when none is set, naming the key's `secretId` and its help link, as a portal search is.

### Models from the Discovery Catalog

The model family (`huggingface-models`) is searched like a portal and added like a storage row, but lands in the [Model Catalog](#model-catalog), as a model package in the user's store.

- **Search** ([`providers/huggingface_models.py`](../utk_curio/backend/app/discovery/providers/huggingface_models.py)) asks `/api/models?pipeline_tag=<options.pipelineTag>` and keeps repos tagged `onnx` or `safetensors`; a next page is the `Link: rel="next"` cursor.
- **`plan(repo)`** reads `/api/models/<repo>?blobs=true` and pins the commit it names. An ONNX export fetches its graph (`model.onnx` first), the external data it names and the two configs; a `...ForSemanticSegmentation` checkpoint fetches its configs and safetensors shards. Pickle-only weights, other architectures, no labels and more than `MAX_MODEL_BYTES` (2 GiB) are refused with `CapabilityUnsupported` or `DownloadTooLarge`.
- **Adding** ([`application/model_acquire.py`](../utk_curio/backend/app/discovery/application/model_acquire.py)) checks `packages.service.model_add_refusal`, then `model_library_refusal` for the libraries the runtime needs (`RUNTIME_DEPS`: `onnxruntime`, or `torch`, `transformers` and `safetensors`), and streams each file from `/<repo>/resolve/<commit>/<path>` through the transport into what becomes the package's `models/` (a checkpoint under `models/checkpoint/`). It writes a model package manifest: an `imported.x<hex>` id (a refresh keeps the id it replaces), the code's license MIT, `dependencies.python` from `RUNTIME_DEPS`, the `model` block (`labels_of` from `config.json`, `onnx_input` from `preprocessor_config.json`, the weights' license from the model card, `discoverySource`), and the segmentation template `packages.service.model_template` gives. `packages.service.install_downloaded_model` zips the folder with its weights and installs it through the store's archive install (a refresh with `replace`), and `install_downloaded_model_deps` installs its libraries by the packages' path (`provision_declared_deps`). A job's `model` (`model_package_row`: the id, folder, name and libraries) and `dependencies` say what landed; its `dataset` is null. `already_held` asks `packages.service.downloaded_model_package` for the model package the account downloaded from the same source and repo, so the same add again fetches nothing, and a search marks the rows the account holds that way from `downloaded_model_ids` (`packages/application/model_downloads.py`).
- A 401 or 403 from the Hub is `CredentialRequired`, so a gated model asks for the Hugging Face token like any source.

### Place search

[`application/places.py`](../utk_curio/backend/app/discovery/application/places.py) answers the area field's place search, `GET /api/discovery/places?q=`, from Nominatim through the catalog's transport: one request a second for the whole process (`MIN_INTERVAL_S`), an in-memory cache of a day (`CACHE_TTL_S`), and a User-Agent naming Curio. Each place has its OpenStreetMap name (from `namedetails`, since Nominatim's `name` follows the request's language), its English label, its box, and whether it is an administrative boundary, which the named-areas field offers. The field's **Within** is the first boundary this search finds for the typed place (`findBoundary` in `pages/discovery/placeSearch.tsx`), looked up on Enter or by **Find areas**, which then searches `"<area>, <OpenStreetMap name>"`. **Download** looks the typed place up again (`withOsmPlaceNames`, answered from this cache) and sends its OpenStreetMap name as `geocodeArea`, so `named_areas_box` asks what the field already asked.

### Collection media

[`infrastructure/media_dirs.py`](../utk_curio/backend/app/discovery/infrastructure/media_dirs.py) names the directories: `media_cache_dir` (`.curio/users/<key>/media-cache/<datasetId>/`, thumbnails the backend draws) and `media_work_root`, which the backend and a node both use: `.curio/users/<key>/media/` with isolation off, and `.curio/exec-scratch/users/<key>/media/` under fork isolation, where `curio-exec` can write. `forget_media` removes a dataset's thumbnails, cached objects and derived frames and clips when the dataset is deleted; the source's files are never touched.

[`application/media.py`](../utk_curio/backend/app/discovery/application/media.py) and [`media_routes.py`](../utk_curio/backend/app/discovery/media_routes.py) serve a collection's files by id:

- **Lookup.** `locate()` resolves `<file_id>` through the index (cached per index file and mtime), or `<file_id>@<t_ms>` and `<file_id>@<t_ms>-<tag>` (`DERIVED_ID_RE`) to a frame, clip or overlay `curio_derived_file` wrote, and never takes a path from the request.
- **Serving.** `original` sniffs the first bytes against `BROWSER_TYPES` (images, video and audio a browser plays) and serves that mimetype with `nosniff`, `Content-Disposition: inline`, and Range. SVG and HTML are never served.
- **Thumbnails.** Pillow for images and frames, rasterio with a 2 to 98 percentile stretch for rasters, a PyAV poster frame for video, and a numpy STFT spectrogram for audio, cached as JPEG and keyed on the file's size and mtime. A bucket's image or raster up to 64 MiB is fetched to draw one; anything else is drawn once cached. A storage row's thumbnails are drawn the same way into a per-source cache under `.curio/discovery-cache/`, or into the account's own media cache for a source that sends a token.
- **Signed links.** `<video>` and `<audio>` cannot send the bearer token, so `POST .../link` signs `{user, key, dataset, file}` with itsdangerous under a key kept in `.curio/media-link.key`, valid `LINK_TTL_SECONDS` (10 minutes), and `GET /api/media/<token>` serves that one file.

### Collections in node code

`curio_load_collection`, `curio_derived_file` and `curio_output_file` come from one function, `make_collection_helpers` ([`sandbox/util/collections.py`](../utk_curio/sandbox/util/collections.py)), injected in process and in the isolated child, so the two paths cannot disagree.

- **Resolution.** `code_refs.py` finds `curio_load_collection("<id>")` calls with `curio_data_path` ones, within the same 32-id cap, so the index resolves and stages like any dataset file. `resolve_exec_collections`, called for every node run by `execution/node_exec.py`, adds, per collection, the folder root or the bucket cache directory, and sends `media_dir` to every node, since a node downstream of the loader writes the frames without naming the collection.
- **Rows.** `curio_load_collection` adds `dataset_id`, `path` (the file, the cached copy, or `None`; the column `curio_segment` reads), `thumbnail` and `image_url` (the columns Simple View shows) and `audio_url`.
- **Derived files.** `curio_derived_file` names `<media_dir>/<frames|clips|overlays>/<datasetId>/<fileId>/<t_ms>.<ext>` and the row the media route serves it back under, `<fileId>@<t_ms>`. A `tag` (1 to 32 lowercase letters and digits) tells two derived files of one file and time apart: the name is then `<t_ms>-<tag>.<ext>` and the id `<fileId>@<t_ms>-<tag>`. `curio_segment` ([`sandbox/util/vision.py`](../utk_curio/sandbox/util/vision.py)) writes each image's overlay this way (kind `image`, `t_ms` 0, the model's tag from `model_tag`), so two models' overlays of one photo are two files. `curio_output_file` names a file a node returns, in the run's scratch directory under isolation, because a RASTER output must be flat-named there. The agents' source scanner treats the name passed to it, literal or f-string, as a file the node writes, not a source it reads.

`curio.media@1` is three Python code templates over these helpers: Sample Video Frames, Split Audio and Mosaic Rasters, which writes a VRT from the index's transform columns.

### Credentials

A source's manifest declares the key it sends in its `auth` block: `secretId` names it, and `label`, `helpUrl`, `placeholder` and `note` say how API Settings shows it. The sources that send one key name the same `secretId` (both Hugging Face sources send `huggingface.token`), and `test_shipped_sources.py` checks that the shipped ones declare it alike. [`infrastructure/credentials.py`](../utk_curio/backend/app/discovery/infrastructure/credentials.py) groups the loaded manifests by `secretId`, shipped sources first: the first source's declaration is the key's, and a source that declares it otherwise is logged once. `key_rows` gives `GET /api/discovery/keys` one row per key, in the order of their labels, which API Settings lists once a key is saved or inherited and offers in the **Kind** select of **Add configuration** otherwise. A key a new source needs is its manifest's `auth` block and nothing else.

- An account's keys live in an owner-only file, `.curio/users/<u>/source-keys.json`, keyed by `secretId` and kept by [`users/source_keys.py`](../utk_curio/backend/app/users/source_keys.py) through `owner_only_file.py`. It is a file of its own, beside `connection-keys.json`, so `curio_secret` in node code never reaches a source's key. `value_for` is the only read that returns a key.
- `PATCH /api/auth/me` saves keys by `secretId` (`source_keys`; `""` removes one, and a key left out stays). It refuses a `secretId` no loaded source declares, and checks every value (one line of text, at most `MAX_VALUE_CHARS`) before it writes any. Responses report keys only as booleans (`has_source_keys` on the user payload). A guest on a `--deploy` instance is refused with a 403, and `storage_key_for` gives a guest there no file, so `own_key` answers nothing for it and a key the shared guest saved without `--deploy` is not sent.
- A source whose manifest sets `auth.operatorDefault` sends the operator's key to every account that has not saved its own. `default_variable` names the variable: `CURIO_DEFAULT_` and the `secretId` in capitals, with every other character as `_`, so the City of Chicago portal reads `CURIO_DEFAULT_SOCRATA_APP_TOKEN`. A manifest never names a variable. Curio's own settings share the prefix (`CURIO_DEFAULT_LLM_*`, the deployment's LLM configuration, and `CURIO_DEFAULT_SAVE_NODE_OUTPUT`), and `is_own_setting` in `domain/manifest.py` keeps them out of reach: a manifest whose `secretId` would read one with `operatorDefault` fails to load, and `deployment_key` refuses one too. `test_credentials.py` checks that every such variable Curio's code names is covered.
- `auth.scheme` is `header` or `query` (`AUTH_SCHEMES`); Google Street View sends its key as `?key=`. The transport adds a query key to the request it sends and nothing else, and takes it out of every URL and message it hands back (`_keyed`, `_redact`), so egress audit records, refusal messages and job records stay safe to store verbatim. The transport binds the credential when it is built, and `CredentialedTransport` sends it only to the source's own origin (the scheme, host and port of `provider.baseUrl`, a missing port being the scheme's default), so no provider ever handles a token.

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
- OpenStreetMap downloads run autk-db in Node with its Overpass requests answered from `fixtures/overpass/`: made-up answers for Golf, Illinois, by name, and an empty one for the coastline autk-db asks for in every area (`overpass_mock.py`), and answers recorded for a box in Golf and a box across Chicago's Loop, gzipped.
- Mapillary's answers (`fixtures/mapillary/`) are recorded with the auth header stripped, every image indexed to a synthetic file. Google Street View's (`fixtures/google-streetview/`) are written, not recorded, from the formats Google documents, by `scripts/write_streetview_fixtures.py` driving the real provider. Hugging Face models' (`fixtures/huggingface-models/`) are the Hub's real answers, every weights file indexed to a synthetic graph or file of the same shape. `test_provider_contracts.py` checks Mapillary live only when `CURIO_MAPILLARY_TOKEN` is set.
- Storage sources are tested on folders built in `tmp_path` and on `source.curio.example-storage@1`, whose files `scripts/build_example_storage.py` generates. That script also adds the resources the storage examples read to `datasets/data.curio.storage-*@1` through `StorageAcquire`, with file times pinned so the output is the same on every run. Buckets and Hugging Face run on the recorded corpus, whose `Range` entries are keyed `"<url> bytes=0-65535"`; the recorder stores synthetic heads rather than third-party imagery.

### Agent tools

The Dataset Finder reaches the catalog through three contracts in `agents/tools.py`:

| Tool | Effect | What it does |
|---|---|---|
| `discovery.sources` | read | The roster, from disk. Costs no web budget. |
| `discovery.search` | read | Live search. The per-run web budget is charged per portal contacted, so a fan-out over five sources costs five. |
| `discovery.acquire` | mutate | Proposes a download. It goes through the review path, and the read executor has no branch for it, so the model loop cannot run it. The proposal card is grounded in a real `describe()` call. |

Storage and service sources are left out of all three: their rows are added through the Discovery Catalog page, where a storage row can be narrowed and a service's area is set.

A candidate row's `acquirable` flag is set server-side only, by `services.py::_mint_row_acquirable`, and a value the model supplies is stripped first. A storage or service source is never acquirable (`_acquirable`). A connector source must be in the roster, offer downloads and describe the resource: `proposals/acquire._source_describes` asks the Discovery Catalog's `describe_resource`, the call a `discovery.acquire` proposal is grounded in, once per resource in a pass (`turns/roster._LazyRoster.describes` keeps the answers and the budget), spending one call of the run's web budget, and a failed describe is a no. Once the budget is spent the source is not asked: the row keeps its coordinate, unconfirmed and not acquirable, the delegated card's summary tells the parent how many ids went unconfirmed (`acquire._unconfirmed`), and confirming the row asks the source then. A Direct URL row must be an https link the probe read as a format the source stores, with the link itself as its `resourceId`. A row that names only an https link is tried as a Direct URL row: the server adds the coordinate, so a plain link to a file is downloaded rather than handed to Node Builder. Any other coordinate, the server's or the model's, leaves a row that does not qualify, so one the source refused reaches no download, builder or file provenance. The rule reads the roster and the probe, never the run's grants: confirming a downloadable row on the card downloads it with the user's own sign-in, and an agent's `discovery.acquire` proposal is checked against its grant where it is minted. The card's **Download** and an approved `discovery.acquire` proposal start the same download job as the catalog page, so a resource shows one download wherever it was started.

---

## Model Catalog

The user-facing model is in [MODEL-CATALOG.md](MODEL-CATALOG.md). A model is a model package: a package of kind `model` ([Nodes: Types and Structure](#nodes-types-and-structure)) whose manifest's `model` block says how to run the weights under its `models/`. The packages code owns them (`backend/app/packages/`, behind `service.py`): [`application/model_packages.py`](../utk_curio/backend/app/packages/application/model_packages.py) (where a model's weights are read, what a listing says about them, the weights license text, the models a node's code names) and [`application/model_downloads.py`](../utk_curio/backend/app/packages/application/model_downloads.py) (a model downloaded from the Discovery Catalog). The Model Catalog reads and writes them through the [Package Routes](#package-routes), as the Node Catalog does node packages.

- **Where they are.** Shipped model packages are in the package catalog, `packages/<id>@<major>/` ([Where the shipped folders are](#where-the-shipped-folders-are)), which `--packages-root` moves. A model added from the Discovery Catalog, imported or published is a package in the account's store, with its weights. A store copy of a shipped package, added or seeded for the examples, holds no weights: they are read where they ship, or from `.curio/fetched` when the pip package leaves them out ([`packages/application/model_packages.py`](../utk_curio/backend/app/packages/application/model_packages.py) `weights_folder`).
- **Listing.** The Model Catalog reads the two package listings with `?kind=model`: `GET /api/packages?kind=model`, the account's store, and `GET /api/packages/catalog?kind=model`, the shared catalog (`application/catalog.py`). Every row (`_listing_payload`) carries `modules`, the Python modules the package ships (`repositories/python_modules.py` `module_names`), and a model package's `model` block carries `downloadsOnFirstUse` (`weights_on_first_use`: neither the copy nor the catalog's holds the weights, a pip install left them out, and none has been fetched; nothing is downloaded to say so). A package whose weights the pip package leaves out is listed before they are fetched, and a folder whose manifest cannot be read is not listed. The surfaces show each `dirName` once, a package in both lists as the catalog's row (`catalogAndOwnPackages`). On the backend, `packages.service.list_model_packages` gives the model packages one account can add or run, for a scenario drop's requirements: the store's that hold their own weights, then the catalog's, once per `<id>@<major>` (`held_model_packages` reads the store under the seed lock).
- **The model block** (`packages/domain/model_block.py`) takes `type` (`semantic-segmentation`, or `image-to-image` or `node-regression` for a graph its node feeds itself), `runtime` (`onnx` or `transformers`), an `entry` under `models/` (a `.onnx` file for `onnx`), up to `MAX_LABELS` labels (none for `image-to-image` or `node-regression`), and for an `onnx` image model an `input` (size 8 to 8192, `uint8` or `float32`, `NCHW`, or `NHWC` for `image-to-image`, `scale`, three-number `mean` and `std`), with the weights' `license`, `licenseFile`, `publisher` and `homepage`.
- **Default cells.** A model package's template without a `source` opens with the cell [`packages/domain/default_cells.py`](../utk_curio/backend/app/packages/domain/default_cells.py) writes for its model's type, served with the starters (`application/starters.py`, named for the template's id) and injected on a fresh drop (`packageNodeBehavior.tsx`, `defaultCellStarter`): a segmentation model's loads it by id and calls `curio_segment`; another type's is a `model.run` skeleton naming each array its ONNX graph takes, with its element type and shape (`datasets/domain/onnx_model.py` `graph_inputs`, read from weights already on the machine, never downloaded). `model_template` is the segmentation node a downloaded model gets, the one DDRNet23-Slim's package ships.
- **Removing.** The drawer's **Remove from project** is `DELETE /api/packages/projects/<id>/<dirName>`, as for a node package: it answers 409 while a canvas node uses the model (`spec_packages.referencing_nodes`: the node's type is the package's, or its `metadata.modelRefs`, written by a drop of the model onto the node, names it while the node's code still names the model, as `nodeLinkedModelIds` reads it), and when no other dataflow uses the model, `prune_unreferenced_packages` deletes the store copy, drops it from the defaults and uninstalls the libraries only it needs. A literal `curio_load_model("<id>")` in node code is only a code reference: it keeps nothing, and the drawer's confirmation names every dataflow whose nodes name the model in their code alone, as the Data Catalog's names those that load a dataset in code (`codeOnlyDataflows` in `services/codeOnlyUsage.ts`, shared by both): the open dataflow from its canvas (`nodesNamingModelInCodeOnly`; for a dataset `canvasLoadsDatasetInCodeOnly`, which counts the dataset as kept while a node is bound to it or saved it as its output, as the dataset usage read does), and the account's others from `GET /api/packages/<dirName>/usage` (`prune.package_usage`, rows from `spec_packages.package_usage_in_spec`, through the scan the dataset usage read makes, `projects/usage.py`), whose `codeOnly` rows have no lockfile entry, no node of the package and no node bound to it. `DELETE /api/packages/<dirName>` removes a package from the account (`remove_package`, then `detach_from_all_projects`). The catalog pages' **Remove from account**, for a package of the account's own (in its store and in no catalog) whose store row says `inUse: false` (`GET /api/packages?usage=true`), sends `?unusedOnly=true`: `remove_unused_package` answers 409 while `packages_in_use` finds the package (every dataflow's lockfile, and the model packages its nodes' `modelRefs` name, `spec_packages.model_ref_packages`), and otherwise removes it and its defaults entry. A node that names a model the store does not hold fails on its next run with `MISSING_MODEL`.
- **Save as package node.** A new package from a node whose code loads a model the account's store holds is a model package of its own (`factory_install.model_source_for_draft`, `model_packages.model_copy`): `builder/factory.py` copies the model's `model` block, declares its package's libraries, writes its weights (and its weights' license file) under `models/`, and renames the node's `curio_load_model` calls to the new id (`rename_model_calls`). The archive is written to a file in the store's staging folder (`build_package_archive_to`), installed from it, and `/factory/install` answers `copiedModel`, the id the frontend renames in the canvas node's code (`renameModelCalls`). A draft saved into an installed package, or a node that names no model the store holds, is built as before. The package build pipeline stages archives up to a model package's caps (`repositories/staging.py` `MAX_ARTIFACT_BYTES`).
- **In node code.** `code_refs` finds `curio_load_model("<id>")` calls; `node_exec.resolve_models` maps each id the code names to its folder through `packages.service.resolve_model_dirs`, from the running account's store only (models behave like nodes), and `/processPythonCode`, a server run and the agents' validation runs send that map with the dataset paths. `curio_load_model` ([`sandbox/util/models.py`](../utk_curio/sandbox/util/models.py)) returns the folder, or raises `MISSING_MODEL`: add the model with Add in the Model Catalog, and, for a model that ships with Curio, how a pip install downloads its weights and where a clone holds them. Under fork isolation, `stage_model_dirs` ([`sandbox/util/staging.py`](../utk_curio/sandbox/util/staging.py)) hardlinks each model's tree into the run's scratch as `model_<i>/`, keeping relative paths, so an ONNX graph finds its external `.data` and a checkpoint its configs; `packages/*/models` is in the hardening allowlists beside `datasets/`.
- **`curio_segment`** ([`sandbox/util/vision.py`](../utk_curio/sandbox/util/vision.py)) runs a model over a collection's rows: `_OnnxRunner` with onnxruntime on the CPU (the manifest's `input` says how to scale, normalize and resize), or `_TransformersRunner` with `AutoModelForSemanticSegmentation` (`local_files_only`, safetensors only). Shares are of all the pixels; the overlay goes through `curio_derived_file` with the `image` kind and a tag for the model (`model_tag`: the first twelve hex digits of the SHA-1 of its id), so the media route serves it at `<file_id>@0-<tag>`, one file per photo and model. It refuses an `image-to-image` model.
- **`CurioModel.run(feeds)`** ([`sandbox/util/catalog_helpers.py`](../utk_curio/sandbox/util/catalog_helpers.py)) runs an ONNX model's graph on the arrays its node prepared, `{input name: array}`, with onnxruntime on the CPU, and returns the graph's outputs in order; the session is opened once per loaded model. The Accumulated Shadow node of `model.scout.deep-umbra@1` runs Deep Umbra this way.
- **Agents.** `models.search` (`agents/application/tools.py`), a read tool of the Node Builder, lists the model packages in the account's store (`held_model_packages`), the only models its node code runs: id, name, task, runtime, origin (`shipped` for a copy of a shipped package, `downloaded` for the account's own), description, up to 40 labels (with `labelsElided` when it has more), and `model_loader_line(id)`, `model = curio_load_model("<id>")`. No tool proposes or downloads a model: the Discovery Catalog's model sources stay out of the agents' tools, as storage sources do.
- **Scenario drops.** A dropped scenario's lever that names a model in `metadata.modelRefs` needs the model's package (`scenario_catalog/infrastructure/requirements.py` `model_package_dir`), added to the target dataflow as a node's package is; a model in neither the store nor the catalog, or one the account may not add, refuses the drop.
- **Frontend.** The Model Catalog is the Node Catalog's code over model packages. `usePackageCatalog` takes `packageKind` (`node` by default, or `model`) and keeps that kind's rows, and `NodeCatalogDrawer`, `NodeCatalogBrowse` and `useNodeCatalogBrowse` take it too: `components/models/catalog/ModelCatalogDrawer.tsx`, opened by `providers/modelCatalog/` from the bar's **Model Catalog** button, and `pages/models/ModelCatalogBrowse.tsx`, the `/catalog/models` page (`/catalog/models/<id>` opens that model's details), render them with `packageKind="model"`. The page's rail narrows by type and runtime (`CATALOG_FACETS` in `useNodeCatalogBrowse.ts`). `components/models/catalog/modelFacts.tsx` holds the model rows the cards, the page's side drawer and `PackageDetailModal` show. In `services/packages/`, `modelPackages.ts` has the kind helpers, the type and runtime labels, `useModelPackages` (the catalog's model packages and the account's own, which the Tools panel palette narrows to the ones the open dataflow's lockfile names, as the drawer's In project tab does, reading the listing again when the lockfile changes) and the refresh event a Discovery add fires; `modelApplication.ts` is a model's drag onto a node or the canvas, and `modelCode.ts` finds and rewrites the `curio_load_model(...)` calls in a node's code. A model's card or palette row writes two drags (`writeModelCardDrag`): the model, which a node takes only when the node's model type and the model's are both known and equal (`modelSwapRefusal`, which says why otherwise; the node's type from the model its code names, `modelTypeOfPackage` in the registry, else its own package's), and its package's card (`packageCardDrag.ts`, its one node naming the model), which the canvas takes through the Node Catalog's card drop (`usePackageCardDrop`, with the Model Catalog drawer's Add when the dataflow lacks the package, and a hosted guest refused). A palette row is a model the dataflow has, so its drop makes the node at once. The node opens with its template's code naming the model and is bound to it (`packageCardNodeOptions`). The Tools panel's Node Catalog dropdown lists no model package's node (`ToolsMenu`, descriptor `package.kind`).

Models come from the Discovery Catalog's model family ([Models from the Discovery Catalog](#models-from-the-discovery-catalog)), are imported as a `.curio.zip`, or ship as model packages in `packages/`.

---

## Scenario Catalog

The user-facing model is in [SCENARIO-CATALOG.md](SCENARIO-CATALOG.md) and the routes are in [Scenario Catalog Routes](#scenario-catalog-routes). The backend is `backend/app/scenario_catalog/`: `domain/parts.py` (a scenario's fixed context, levers and outcomes, read from a saved spec), `domain/copy.py` (what a drop into another dataflow copies), `infrastructure/projects.py` (the account's projects and their saved outputs), `infrastructure/requirements.py` (the packages, datasets and models a drop needs), `service.py` (listing, details and the drop) and `routes.py`.

- **No storage of its own.** Scenarios live in their projects' specs (`dataflow.scenarios`, see `projects/scenarios.py`). A listing reads `projects.services.list_projects`, whose summaries carry each project's scenarios and graph preview; a scenario's details read its project's spec. A scenario's id is unique in its project only (a duplicated project keeps its scenarios' ids), so the catalog keys each one as `<projectId>/<scenarioId>`.
- **Parts.** `scenario_parts` is the twin of `scenarioParts` in `src/utils/scenarios/scenarioParts.ts`, and `saved_sources` the twin of `savedSourcesOf` (the save rule's per-node walk: a chart, a Data Pool or a drawing Autark node stands for the nodes feeding it, the walk pinned dashboard tiles use). Both read `scenarioParts.cases.json`, through Jest and `tests/test_scenario_catalog/test_parts.py`, so the catalog reads a scenario the way its canvas does. Shared tags are found with `code_references.shared_names_in`.
- **Saved results.** For each node of a scenario's parts, the details name the outputs its project saved: the Data Catalog's computed datasets `computed.<projectId>.<nodeId>` of each node `saved_sources` gives, listed with `DatasetCatalogService.list_dataflow_outputs` (the `computed.<projectId>.` prefix), without file paths.
- **Agents.** `scenarios.search` (`agents/application/tools.py`), a read tool of the Dataflow Builder, is the catalog's own listing, `ScenarioCatalogService.list_catalog`, read as the request's account (`g.user`), as `catalog.search` reads the Data Catalog's: each scenario's key, name, description, project name, node count and `inThisDataflow`, never its preview, the first 40 with `scenariosElided`. A run with no signed-in account gets an error and nothing is read. `dataflow.read` gives a dropped scenario's `source` (`{project, scenario}`, the ids the drop writes) by its project's and its scenario's names (`tools._scenario_sources`): it reads only the projects those sources name, each once, with `infrastructure/projects.py` `owned_project`, and says `project-gone` when the project is gone or is not the account's, and `scenario-gone` when it no longer holds the scenario. A dataflow with no dropped scenario reads no other project. The preamble's Trill block leaves `source` out, since agents do not write it.
- **Frontend.** `services/scenarioCatalog/` (client, types, hooks, the drag payload), the page `pages/scenarios/`, the canvas drawer `components/scenarios/catalog/` opened by `providers/scenarioCatalog/` from the bar's **Scenario** button, and the shared plain-box graph `components/DataflowThumbnail.tsx` with a `highlight`.
- **Dragging a scenario into a dataflow.** A drawer card puts `application/x-curio-scenario` on the drag; `MainCanvas` hands the drop to `components/scenarios/useScenarioDrop.ts`, in five steps:
  1. `GET .../copy?target=` returns the plan: the levers and the context's Parameter nodes as spec nodes, the edges into the levers, each context node with the one node whose saved output stands for it (`saved_sources`), the outcomes' saved sources, the packages the target lacks, `toRun` and `problems`. A standing-for node with no saved output goes in `toRun` when a run on the server can make it (`scenario_catalog/infrastructure/runs.py`): the account's runs go to the server (`refusal`: not a hosted guest, not `--no-project`, as `runsOnServer` decides on the canvas), and neither it nor any node it reads from has the run role `browser` or `missing` (`browser_node`, through `run_plan.node_role`). Otherwise it is a problem naming the node. Nothing changes, and a problem refuses the drop.
  2. When `toRun` is not empty, the canvas starts a run of the scenario's project on those nodes (`runsApi.start(projectId, {targets})`), toasts "Running Buildings in Chicago Loop shadow with towers removed or edited for Existing", follows the run (`runsApi.follow`) and asks for the plan again. A 409 that names a run already going in that project follows that run. The run saves the nodes' outputs in their project, since `save_policy.saved_source_node_ids` holds a scenario's context. A run that fails, the two-runs limit (429), or a plan that still lists nodes to run refuses the drop with its message, and `POST .../copy` refuses while `toRun` is not empty.
  3. `utils/scenarios/scenarioDrop.ts` `planScenarioDrop` picks the ids: `duplicateSelection` copies the levers (fresh ids, `copiedFrom`), one Data Loading node stands in for each context node, Parameter nodes are copied, and the scenario is collapsed at the drop point with `source: {project, scenario}`. A context node an earlier drop from the same project brought (outside every scenario, with that lineage) is reused, and a Parameter name the dataflow already uses refuses the drop.
  4. `POST .../copy` adds the packages through `install_to_project`, as the Node Catalog's Add does, then copies each saved output to its copy's id with `datasets/install/copy.py` (the dataset folder, manifest rewritten to the new producer node and dataflow, never re-read from sandbox artifacts), in two steps (`scenario_catalog/infrastructure/projects.py::copy_outputs`). Under the source's spec lock, each folder is copied whole to a staging folder in the account's store (`stage_computed_copy`). Then, under the target's, each copy takes its place (`place_staged_copy`) and the source's output refs are hydrated for the copies (`storage.hydrate_outputs`). The drop holds one lock at a time, so the source may be the target and two drops each way between two projects never wait for each other. A copy that fails is a 409 that says to try again.
  5. The canvas refreshes the package registry, builds the loaders with `buildDatasetLoaderNodeOptions`, loads everything with `loadTrill(..., "none", ..., restored)` as Duplicate selection does, and applies the restored outputs with `utils/restoredOutputs.ts`, which `ProjectLoader` uses too.

  A copy's dataset id is `computed.<targetId>.<nodeId>`, so a reload of the target restores it as that node's output (`_durable_source_for`), and a later run of the source rewrites only the source's.

---

## Backend API Reference

The backend is a Flask application in `utk_curio/backend/`. Routes are split across blueprints per domain: sandbox proxies plus the spatial-join handler in `backend/app/api/routes.py`, node and model packages in `backend/app/packages/routes/` (one module per resource behind one `_map_package_errors`, memo dev/143), datasets in `backend/app/datasets/routes.py`, Discovery Catalog in `backend/app/discovery/routes.py`, agents in `backend/app/agents/routes/` (one module per resource under one blueprint, memo dev/142), projects in `backend/app/projects/routes.py`, and auth in `backend/app/users/routes.py`.

### Core Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/live` | GET | Health check (the container healthcheck uses `/health` on `server.py`) |
| `/version` | GET | Installed `utk_curio` version, as JSON |
| `/processPythonCode` | POST | Execute Python node code (proxies to sandbox `/exec`) |
| `/processJavaScriptCode` | POST | Execute JS node code via Node.js subprocess (proxies to sandbox `/execJs`) |
| `/get` | GET | Download an artifact by id (Arrow IPC when the client asks for it). A name the session-tagged store cannot serve falls back to the shared data directory, where a project load hydrates that project's saved outputs, so they are readable by anyone who can load the project |
| `/get-preview` | GET | First N rows + metadata of an artifact, for DataPool display |
| `/raster` | GET | A raster artifact (or one `part` of a tuple) as GeoTIFF bytes for an Autark node, described in the `X-Curio-Raster` header; 413 with its size over `maxCells` or `maxSide`. A raster output the session-tagged store cannot serve falls back to its hydrated copy, as `/get` does |
| `/file/<path>` | GET | Serve a file relative to `CURIO_LAUNCH_CWD` so browser-side nodes can fetch binary assets (PBF, GeoTIFF) by the same relative path Python nodes use. Unauthenticated, so it refuses hidden paths and Curio's own state: the instance folder, the `.curio` state root, the shared data directory, the dataset hub and the SQLite database. `vendor/duckdb-extensions/` and `docs/examples/data/` come from the folders Curio ships instead ([Where the shipped folders are](#where-the-shipped-folders-are)) |
| `/starters` | GET | Per-template starter source bodies from every installed package |
| `/spatial_join` | POST | Spatial join of two GeoJSON inputs by an operation, on geopandas `sjoin` (see `common/spatial.py`) |

File ingestion is **not** here - it lives in the datasets blueprint as `POST /api/datasets/import`.

### Package Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/packages` | GET | List the user's installed packages (`?kind=node` or `?kind=model` keeps one kind). Each row carries `modules`, the Python modules the package ships, and a model package's `model` block carries `downloadsOnFirstUse`. `?usage=true` adds `inUse`: whether one of the user's dataflows uses the package (`prune.packages_in_use`) |
| `/api/packages/<dirName>/usage` | GET | The user's dataflows that use the package, as `/api/datasets/<id>/usage` answers: `codeOnly` marks one whose nodes name the model in their code alone |
| `/api/packages/catalog` | GET | List packages available in the catalog source (`?kind=` and the row fields as above) |
| `/api/packages/projects/<id>` | GET | Read a project's per-project lockfile |
| `/api/packages/projects/<id>/install` | POST | Install a package into a project (copies files, pip-installs `manifest.dependencies.python`) |
| `/api/packages/projects/<id>/<dirName>` | DELETE | Uninstall a package from a project (ref-counted prune + pip uninstall of unique deps) |
| `/api/packages/<dirName>` | DELETE | Remove a package from the user's store and from every lockfile. With `?unusedOnly=true` (the catalog pages' Remove from account), **409** while a dataflow uses it, and its defaults entry goes too |
| `/api/packages/<dirName>/file/<path>` | GET | Serve a static file from the user's installed copy (behavior bundles, icons, …) |
| `/api/packages/<dirName>/weights-license` | GET | A model package's weights license text, as `{"text": ...}`, from the user's copy or the catalog's. **404** when the weights have no license file |
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
A row is added with `INSERT ... ON CONFLICT DO NOTHING`, so when two listings
reconcile at once, or an install lands during a listing, the writer that comes
second keeps the row the first one added. Reads hydrate in
`repositories/user_store.py` and `repositories/installed.py`.

`application/listing.py::resolve_execution_paths` uses the index as a fast path
for turning dataset ids into filesystem paths at execution time, falling back to
a full listing for hub and live-output ids. Both paths run the same containment
check, so an index row pointing outside the allowed read roots is refused rather
than served.

### Saved outputs and dataflow runs

A dataflow's saved outputs are the `outputs` list of its `manifest.json`: one entry per node with `node_id`, `filename`, `data_type` and `produced_at`. `produced_at` is the time in the output's artifact id (`<ms>_<hex>`), stamped by the server when the output is first recorded and kept while the same file stays recorded.

- A save (`projects/services.py::update_project`) records the outputs it sends. When the manifest already holds a newer output for a node, by `produced_at`, that output stays and the older one sent is not installed. An entry without `produced_at` counts as oldest.
- A canvas save names its tab and carries a number one higher than the tab's last save (`api/saveOrder.ts`). `update_project` refuses with 409, under the spec lock and before writing anything, a number lower than the latest one applied from that tab, which `storage.SAVE_ORDER_FILE` records for the last 32 tabs. The page gives up on a save after 2 minutes (`api/projectsApi.ts` `SAVE_TIMEOUT_MS`) and the save queue sends the next, so the save given up on cannot land after it. At most one 30-second autosave waits in the queue: a tick that finds one waiting joins it, and it reads the canvas when it leaves the queue (`useWorkflowOperations.ts` `requestAutosave`).
- An output on record that a save does not send stays while its node is in the saved dataflow with the code it had before the save, and the node's output is one the dataflow records (`save_policy.records_output_on_save`, with `saved_source_node_ids`); the output of a node the save deletes, edits or turns Save off for goes (`_kept_when_unsent`).
- `record_node_outputs` records outputs without a save: each replaces its node's entry, and the other entries stay. It writes no spec and does not move the dataflow's revision.
- Both read and write the manifest under the spec lock. A project load and a dashboard read the spec and the manifest and hydrate the outputs under it too (`services._saved_outputs`), before any database write, so they never meet an output a save is installing. A scenario drop reads the saved outputs it plans with and copies under the source's spec lock, and puts the copies in place and hydrates them under the target's, one lock at a time (`scenario_catalog/infrastructure/projects.py`: `saved_outputs_of`, `copy_outputs`).
- Both install what they record into the node's computed dataset (`datasets/install/installer.py::install_computed_file_for_node`, `bundle.py::install_computed_bundle_for_node`). Writing again the output the dataset holds, a data file named after the same artifact or a bundle of the same parent artifact, keeps its `createdAt` and `updatedAt`; a new output dates it on the record clock, to the millisecond. The catalog's **Recent activity** sort reads `updatedAt` as a time, then the title, then the id (`listing.py::_sort_catalog_items`), and a layer group takes the date of its latest layer. Both read dates with `datasets/domain/catalog_dates.py`, the twin of `services/datasetCatalog/catalogDates.ts`, with which the canvas's Data palette dates a layer group. The palette shows the datasets it holds in the listing's order and sorts nothing itself. `catalogDates.cases.json` holds the cases both sides run.
- An output the computed dataset already holds, the same data file byte for byte or a bundle of the same parent artifact with every part in place, is not installed again (`installer.keep_installed_output`): the folder stays, and only a changed manifest is replaced, atomically. A new output replaces the folder.

A project load copies each saved output's durable file into the shared data directory under its `filename` (`projects/storage.py::hydrate_outputs`), and a reader the session-tagged store refuses, after a reopen under a new sign-in, reads that copy (`parsers.load_artifact`). An output with no durable file left is left out, with a warning in the log. A dashboard whose tile needs such an output, one the sandbox cannot read, or a raster of one the sandbox cannot be asked for, is refused with a 503 that says to try again (`dashboard_payload.DashboardOutputUnreadableError`), which the page server carries as it carries the 409 and 413 refusals. An output saved as a bundle, a tuple or a list or dict of frames, is also hydrated with its parts in `bundles/<filename>/`, laid out as staging lays out a bundle: `data/bundle.json`, and each part it lists with the files read beside it, at its path under the dataset's folder. Each load copies the parts that are missing, and the `bundle.json` whenever the dataset's differs. `load_shared_output_file` reads that folder back as the value the store gives: the parts in the container `bundle.json` records (`catalog_helpers.bundle_container`: a tuple, a list, or a dict with its keys in their order; a tuple when it records none), each part as `curio_load_data` reads it and only from the files `listed_bundle_parts` gives. It never hands out a `bundle.json` as the output's value, and a `bundle.json` that records any other container reads as missing.

[`execution/save_policy.py`](../utk_curio/backend/app/execution/save_policy.py) decides which outputs a run on the server installs and records, as `utils/saveOutputDataset.ts` decides it on the canvas. `utils/saveOutputDataset.cases.json` holds the cases both sides run.

A computed dataset is titled with the name its node's header shows: the renamed header (`metadata.packageTemplateLabel`), else the template's label from its package manifest, else the type in words without its version. [`execution/node_names.py`](../utk_curio/backend/app/execution/node_names.py) is the twin of `utils/nodeDisplayLabel.ts`, which `resolveNodeDisplayLabel` calls for the header, and `utils/nodeDisplayLabel.cases.json` holds the cases both run. Every writer uses it: a canvas save and a node's play send the canvas's name (`node_name`, `nodeName`); a run on the server names each step with it (`run_engine.node_label`, with `node_names.template_labels` for the project's templates) and installs and records the output under that step label; a save whose output ref carries no name takes it from the spec (`_computed_output_title`).

The run tables `dataflow_run` and `dataflow_run_step` ([`runs/models.py`](../utk_curio/backend/app/runs/models.py), alembic revision `f7a8b9c0d1e2`) hold one row per run and one per node the run touched. A run with no `target_node_id` ran the whole dataflow. `runs/repositories.py` keeps, per dataflow and per kind, the newest 50 runs and every run younger than 30 days, pruning when a run is created. A project's runs and their steps are deleted with it.

#### Runs on the server

A run executes the saved dataflow on a thread of the backend, so it goes on whether or not a browser follows it.

- **Plan.** [`execution/run_engine.py`](../utk_curio/backend/app/execution/run_engine.py)`::plan_run` takes every node, or one node and its ancestors less those whose outputs the canvas sends to reuse. [`execution/run_plan.py`](../utk_curio/backend/app/execution/run_plan.py) orders them: `topological_levels` is the twin of `computeTopologicalLevels` (`providers/flow/runLevels.cases.json` holds the cases both run), and an interaction link, by its type or its `in/out` handles, orders nothing.
- **Roles.** `node_role` gives each node one of four. `run`: the template is executable, or the node is an Autark node whose document only loads data (a non-empty `data` section, and no map, plot or compute step). `forward`: the node passes its input on (a chart, a pool, a Simple View, an Autark render, a Data Export), or has nothing to run (a Parameter node, whose value reaches the nodes that name it through their code). `browser`: only the browser makes its data (an Autark compute node, an Autark node with no data of its own to load, a Spatial Join). `missing`: the type names a package's template that neither the project's roster nor a manifest in the account's store, the catalog or the shipped packages holds (a saved Compare Scenarios node, a node of a package only another account's store holds), which the canvas shows as a card and cannot run either; a type that names no package stays `browser`. [`execution/autk_spec_kind.py`](../utk_curio/backend/app/execution/autk_spec_kind.py) is the twin of `utils/autkSpecKind.ts`; `utils/autkSpecKind.cases.json` holds the cases both run.
- **Walk.** `run_events` runs one level at a time, every node of a level at once. A node fed by a failed or skipped node is skipped, with the reason naming that node; a node fed by a `browser` node waits, and the run ends `needs_canvas`. A `missing` node fails at once, its message naming its type as the canvas's card does (`run_plan.missing_type_message`), so what it feeds is skipped. Each executed node goes through `node_exec` with its references resolved, every line indented as `PythonInterpreter.ts` indents it, and one upstream's output as it is or several as an `outputs` bundle in circle order. A sandbox that cannot be asked fails that node only.
- **Autark data.** An Autark node that only loads data runs as its run in the browser does (`autkLayerMaterialize.ts::runDataInBackend`): its document, references resolved, is compiled by the browser's own compiler, `adapters/node/autkDataCompile.ts`, which `webpack.autk-data.config.js` bundles into the built frontend as `dist/autk-data-compile.cjs` and [`common/autk_data_compiler.py`](../utk_curio/common/autk_data_compiler.py) runs in Node. The JavaScript goes to `/execJs` with no input and `save_dataset` off, and a failed attempt is tried once more. Its output, the layer list, is recorded as a save records it. A build without the compiler is rebuilt on the next start (`cli/frontend_build.py`).
- **Thread.** [`runs/service.py`](../utk_curio/backend/app/runs/service.py) records each event in the run tables, records an output as `save_policy` says, and passes the event on. The sign-in token that started the run tags its artifacts and lives on the thread only.
- **Jobs.** [`common/job_registry.py`](../utk_curio/backend/app/common/job_registry.py) holds live jobs in this process: one per dataflow, two per account (`runs/jobs.py`), keyed by attachment for agent jobs (`agents/infrastructure/agent_jobs.py`). A follower replays a job's events and then tails them; leaving only stops following.
- **Restarts.** A run another backend process left queued or running becomes `interrupted` when this one starts, and when a run is read. Nothing runs again by itself.
- **Cancel.** Nothing new starts once a run is cancelled; the node already running finishes and its output is dropped.
- **Test rig.** `/api/testing/run-hold` holds every run before each node it executes (`runs/jobs.py::hold_point`), so a browser test acts while a run goes; outside a test rig the hold point returns at once.

**The canvas.** [`providers/flow/useServerRun.ts`](../utk_curio/frontend/urban-workflows/src/providers/flow/useServerRun.ts) is what Run All, a node's play and Ctrl+Enter call for whoever may save the dataflow (`runsOnServer` in `FlowProvider.tsx`); hosted guests, shared viewers and `--no-project` keep `usePlayAll` as their whole run.

- It saves through `requestProjectSave`, then starts a run of that revision. A play's `reuse` (`serverRunSteps.reuseFor`) holds the output each ancestor has in the canvas's `outputs`, where a load puts the saved ones, for the ancestors `nodesToRunUpTo` (`runLevels.ts`) does not run again: the same decision the in-browser walk makes. A 409 naming a running run follows that run.
- It follows the stream ([`services/runs/runsApi.ts`](../utk_curio/frontend/urban-workflows/src/services/runs/runsApi.ts), over `utils/sseStream.ts`). A step's reply reaches its node through `utils/executionResult.ts`, the rule `CodeEditor` applies to a run in the browser, and `applyNewOutput`; the provenance takes the step's own times. A node shows it through `data.serverOutput`, which `UniversalNode` hands to the setter its own run uses. A skipped node takes the in-browser walk's `skipExec`. The pure half is `serverRunSteps.ts`.
- `serverRunActive` is apart from `isRunActive`, so a chart draws as its data arrives; the Run All button, a Data Export and the agent strip read both.
- When the server's part ends, the tab that started the run walks the `browser` and `waiting` nodes, with the `forward` nodes above them, through `usePlayAll.playNodes`, and reports each to `/steps/<nodeId>`. Stop cancels the run and gives the button back at once.
- A node with no descriptor, triggered by a run in the browser, reports at once that its run failed, its card's title as the message (`UnresolvedRunAnswer` in `UniversalNode.tsx`, `unresolvedNodeMessage` in `UnresolvedNode.tsx`), so the walk skips what it feeds rather than waiting for it until the stall watchdog gives up. A trigger that comes while the registry may still deliver the descriptor is answered once the registry has settled.
- A run's end, on the server or in the browser, sends the install save its outputs queued at once (`flushInstallSyncRef`), in the tick its last output lands. The save names that output too: `buildOutputRefs` reads `outputsRef`, which `setOutputs` writes before React renders.
- A hosted guest's outputs queue no install save, and its pins neither save nor say they will (`hostedGuest` in `FlowProvider.tsx`, from `isHostedGuest`); `ensureProjectId` creates no dataflow for it. On a dataflow it never saved, an action that needs one tells it to sign in, naming the action (`hostedGuestSignInNote` in `useHostedGuest.ts`): the Data Catalog's Add, Remove and Publish, the Node and Model Catalog drawers' Add, Remove and Import, the Agent Catalog drawer's Add and Remove, Save as package node, New node from a Python function, and a scenario drop. An agent drop says so whenever it would save first (on a node or a connection) or the dataflow has no id. Only File > Save and Save a copy answer such a guest with "Guest users cannot save projects".
- After a load, `ProjectLoader` asks for the dataflow's last run: a run still going is followed; a finished one gives its `ok` steps whose `codeCurrent` is true and whose output the manifest did not restore, restored as a load restores outputs; a run that ended `needs_canvas` offers **Finish run**.
- With the dataflow's `autoRun` on (View > Run stale nodes automatically), [`providers/flow/useAutoRun.ts`](../utk_curio/frontend/urban-workflows/src/providers/flow/useAutoRun.ts) starts a run of `targets`: the nodes a widget or Parameter value change touched (`requestAutoRun`, called by `WidgetsEditor` and the Parameter node) and every node below them, 500 ms after the last change. A change during a run waits for its end and then runs once; Stop drops it. It is offered only where `runsOnServer` holds.

`runner.py::run_through_node`, behind Solve's validation and an agent's run through a node, walks a slice one node at a time and stops at the first failure, sending seeded code straight to the sandbox. It takes upstreams, input circles, references, roles and the ancestor slice from the same places as a run; `tests/test_runs/test_run_parity.py` runs both on the same dataflows.

| Route | Method | Purpose |
|---|---|---|
| `/api/projects/<id>/runs` | POST | Start a run of the saved dataflow: `{target?, targets?, reuse?, specRevision?}`. `targets` lists several nodes, an automatic run (trigger `auto`). 202; 409 for a revision that is not the saved one or while the dataflow runs (with `runId`); 429 over the account's two runs; 403 for a hosted guest |
| `/api/projects/<id>/runs` | GET | The dataflow's runs, newest first; `?kind=all\|node` |
| `/api/runs` | GET | Every run of the account; `?status=`, `?kind=` |
| `/api/runs/<id>` | GET | A run with its steps; each step's `codeCurrent` says whether its node holds, as saved now, the code the step ran |
| `/api/runs/<id>/stream` | GET | SSE: a `run` event, then `run_started`, `step_started`, `step_finished` and `run_finished`, replayed and then followed |
| `/api/runs/<id>/cancel` | POST | Stop before the next node |
| `/api/runs/<id>/rerun` | POST | Run the same thing again |
| `/api/runs/<id>/steps/<nodeId>` | POST | A tab reports a node the browser ran: `{status: ok\|error, message?}` |

#### A dashboard viewer's runs

Opening a dashboard runs it on the server with the saved values, for anyone, signed in or not, and a viewer who changes a pinned control runs it again with that value, with nothing saved to the dataflow or its owner's Data Catalog ([`runs/viewer.py`](../utk_curio/backend/app/runs/viewer.py), routes in `runs/viewer_routes.py`). No sign-in is needed, as for the dashboard payload.

- **Controls.** `dashboard_controls` gives what a viewer may change: every widget of a pinned node, a pinned Parameter node's one included, but the kinds `contracts/dashboardRuns.json` keeps read-only (`text`, `text-list`, `file`), whose free value could name another of the owner's datasets or files. Each value is checked with `check_widget_value`, the Widgets tab's check.
- **Plan.** The saved spec, read with its saved outputs hydrated (`services._saved_outputs`), gets the values laid over it in memory, and is never written. The targets are every node the tiles read (`dashboard_source_node_ids`), and `plan_run` adds the nodes they need. The owner's saved output stands in only for a node a viewer's run cannot run (`_stand_ins`): one whose code reads a connection key, or one whose package is not installed; such a node is no target. With no target, or no step left, the start answers no run.
- **Steps.** Each runs as Play does in the owner's store (`node_exec`, with the owner's datasets, models and packages), with no node id, so nothing is installed or journaled, and `save_dataset` off. A Python step whose code reads a connection key (`curio_secret`) fails at once with `NO_KEYS_MESSAGE`: a viewer's run uses no key.
- **Kept outputs.** Each step's output is kept in `dashboard_step_output` (alembic revision `d2e3f4a5b6c7`) under `step_key`, a digest of the step's code as sent, its inputs (saved outputs or kept ones, each its own artifact), a fingerprint of the owner's package store, the files of the datasets its code reads, and Curio's version. A step whose key is kept answers with the kept output and runs nothing. Each step's artifacts carry a session of their own (`common/dashboard_sessions.py`); `/artifact-sessions/describe` gives the entry its artifact ids and size. A step reads the artifacts of its run's earlier steps and of the outputs kept from earlier runs: the sandbox lets one dashboard session read another's, and no session of another shape reads theirs or is read by them (`parsers.session_may_read`, which the store, its preview and staging for an isolated child all apply). Entries go 7 days after they were made (`KEPT_DAYS`), whatever their use since, and the next visit makes them again. `prune` sweeps them every 6 hours (`start_prune_scheduler`, off under `--testing`), at the end of each run and on the first start after a restart; past 2 GiB on a dashboard the least recently used go first. The sandbox forgets the sessions of the entries that go (`/artifact-sessions/forget`, which names only sessions of the dashboard shape), and a deleted dataflow's entries go with it (an `after_delete` on the entry, forgotten after the commit).
- **Limits.** `common/address_limiter.py`: 10 runs a minute per visitor address, 120 overall, of the values visitors try; opening the page, with the saved values, and a start that joins a run cost nothing. With `--proxy-hops N` the backend reads the address from the `X-Forwarded-For` those proxies add (`ProxyFix` in `app/__init__.py`), as every per-address limit does, and without it from the request itself. The hosted stacks pass 1 (`docker-compose.deploy.yml`). Two live runs per dashboard, in a registry of their own (so an owner's runs never wait on them), and a start whose values already run joins that run. Half the sandbox's isolated pool (`common/exec_pool.py`) is the most nodes viewers' runs execute at once.
- **Following.** A start answers a run id and a token; the stream and a private output's read take the token in `RUN_TOKEN_HEADER` (`X-Curio-Run-Token`, in the CORS Allow-Headers). Events carry no reply and no printed text; a step's `artifactIds` are the artifacts its kept output holds, which the page reads through the routes below.

| Route | Method | Purpose |
|---|---|---|
| `/api/projects/<id>/dashboard/runs` | POST | `{values: {nodeId: {widget: value}}}`: run the dashboard with those values, or join the run of them going. 202 with `{runId, token, joined, nodeIds}`; 200 with no run when nothing needs to run; 422 for a value that is not a control's or does not suit it; 429 over a limit |
| `/api/projects/<id>/dashboard/runs/<runId>/stream` | GET | SSE: `run_started`, `step_started`, `step_finished` and `run_finished`, replayed and then followed; 403 without the run's token |
| `/api/projects/<id>/dashboard/outputs/get` | GET | `/get` for an artifact a kept output of this dashboard holds, read in its own session; 404 for anything else |
| `/api/projects/<id>/dashboard/outputs/get-preview` | GET | `/get-preview` likewise |
| `/api/projects/<id>/dashboard/outputs/raster` | GET | `/raster` likewise |

### Dataset Routes

Defined in `backend/app/datasets/routes.py`; all require authentication. See [DATA-CATALOG.md](DATA-CATALOG.md) for the user-facing model.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/datasets/catalog` | GET | List catalog items (`q`, `format`, `origin`, `sort`, `includeHub`, `groupOsm`, `dataflowId`, `liveOutputs`) |
| `/api/datasets/<id>` | GET | Dataset detail, including resolved producer node for computed datasets |
| `/api/datasets/<id>/preview` | GET | Paginated tabular/geo preview (`rowLimit` 1 to 500, default 50; `offset`; `part` for bundles) |
| `/api/datasets/<id>/usage` | GET | Dataflows across the user's projects that reference this dataset (the scan in `projects/usage.py`, which the package usage read shares) |
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
| `/api/discovery/search` | GET | **Live, federated.** Fans out over every searchable portal and every storage source's listing (`q` required, `format`, `provider`, `auth`, `limit`). A failing leg is reported in `sources[]` and never fails the request |
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
| `/api/discovery/keys` | GET | Every key the sources declare, for API Settings: its `secretId` (`slot`), label, help link, placeholder and note, `present` and `inherited` as booleans, and the sources that send it |
| `/api/datasets/<id>/extent` | GET | The box around a geo dataset, in EPSG:4326, for the area field |
| `/api/discovery/jobs/<id>` | GET | Job progress. Per account: another user's id is indistinguishable from an unknown one |
| `/api/discovery/jobs/<id>` | DELETE | Ask a download to stop; checked between chunks |

Errors map by type: 404 unknown source or resource, **428** a source needing a
token this account does not hold, 429 rate-limited, 502 a portal that answered
badly or an egress refusal (the policy reason, never a resolved address), 503 a
storage source that cannot be read (its folder is not there), 415 a collection
file that cannot be served as asked (no preview, or not a format Curio serves),
400 an unsupported format or an oversized download.

### Scenario Catalog Routes

[Scenario Catalog](#scenario-catalog) describes what these read. Every route needs a signed-in caller and reads only the caller's projects.

| Route | Method | Purpose |
|---|---|---|
| `/api/scenarios/catalog` | GET | Every scenario in the account's projects, each with its project and the project's graph preview (`q` filters by name, description and project name) |
| `/api/scenarios/<projectId>/<scenarioId>` | GET | One scenario: its fixed context, levers and outcomes, each node with the outputs its project saved. **404** for another account's project, a deleted one, or a scenario the project does not have |
| `/api/scenarios/<projectId>/<scenarioId>/copy?target=<projectId>` | GET | What dragging the scenario into the target project copies, `toRun` (the context nodes with no saved output that a run on the server makes first, in the scenario's project, as `{nodeId, label}`), and `problems` naming why it cannot be. Changes nothing. **400** without `target`; **404** when either project is not the caller's |
| `/api/scenarios/<projectId>/<scenarioId>/copy` | POST | Body `{targetProjectId, outputs: [{source, node}]}`: adds the packages the plan names to the target, copies each named saved output to `computed.<targetId>.<node>`, and returns the target's packages, those added, each context loader's dataset, and the restored output refs. **409** while the plan has a problem or a node to run; **400** for a source the scenario does not bring or a node id that is not fresh |

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
| `/api/agents/llm/configs/<id>` | PATCH, DELETE | Change one (a blank key keeps the stored one; a new endpoint needs the key again) or remove it, which resets a removed default and clears the agents chosen for it (`moved`) |
| `/api/agents/llm/configs/<id>/duplicate` | POST | Copy one, its key included, server-side; `{label?, model?}` |
| `/api/agents/llm/default` | PUT | Choose the default, `{configId}`; `null` is the Deployment default |
| `/api/agents/llm/assignments` | PUT | Choose agents' configurations: a partial map of agent id to a configuration id, `"deployment"` or `null` (clears). Nothing is written unless every entry is valid; an internal agent is refused; **403** for a hosted guest |
| `/api/agents/provider-models` | POST | The models API Settings can offer for the endpoint being configured. POST because the editor asks *before* the user saves, carrying the provider, base URL and key on screen. A stored key is borrowed only with `configId`, and only while the endpoint on screen is still that configuration's own, or with `endpoint: "deployment"`; with neither, no key is borrowed. Hybrid, both halves from the API: the live listing (OpenAI-compatible, Anthropic and Gemini, all via `agents/providers.py`), falling back to what that endpoint last reported, recorded per account by `agents/model_catalog.py`. Answers `{models, listable, source, remembered, rememberedAt, warning}`; a failed listing is a 200 with `source: "remembered"` unless nothing was ever recorded, which is a 400 |
| `/api/agents/settings` | GET, PUT | The catalog settings: each one's schema, default, the account's value and the agents that read it, plus whether this account may change them. `PUT` takes key to value (`null` restores the default) and saves nothing unless every value is valid; **403** for a hosted guest |
| `/api/agents/imports` | GET | List the account's imported definitions, as cards |
| `/api/agents/imports` | POST | Record `<id>@<major>` in My imports. Never adds to a dataflow |
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
| `/api/agents/.../proposals/<proposalId>/apply-node` | POST | Apply one planned node from a pending dataflow-plan proposal; the last one completes the plan, runs its removals and returns `removedNodeIds` and `removedEdgeIds` |
| `/api/agents/.../proposals/<proposalId>/apply-edges` | POST | Apply the plan's edges: the connection review stage; the call that completes the plan, a plan of connections only included, runs its removals and returns `removedNodeIds` and `removedEdgeIds` |
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

A template that declares `starterIsContent` gives its starter to a node an
agent's plan or `node.create` creates too. Both plan applies, the whole plan and one node
(`agents/application/proposals/plans.py`), read it with `content_starters`
(`packages/application/starters.py`, each template resolved as the project's
available templates resolve it). The node's content is the starter, and its
widgets are the template's with each one the plan declares set over the one of
its name (`plan_scenarios.created_node_metadata`). It never joins `nodeRuns` as
pending, so Solve does not write it, and its ref is `approved`, so the
Simulation Mode driver does not validate it either. Every other planned node is
created empty for Solve to write.

A `node.create` of such a template gives no content, and any other content is
refused (`mint.starter-is-content`, which names the template's widgets). The
mint reads the starter with `content_starters` and sets the request's widgets
over the template's with `plan_scenarios._set_over`, so the review card shows
the spec and the widgets Apply writes. Neither the source-grounding gate nor
the document check reads the starter, as neither reads a plan's. A template
whose starter is not its whole content keeps its rule: the request gives the
content.

### Auth Routes

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/auth/signup` | POST | Create an account (username + password) |
| `/api/auth/signin` | POST | Username/password sign-in |
| `/api/auth/signin/guest` | POST | Guest sign-in (when enabled) |
| `/api/auth/signout` | POST | Invalidate the session token |
| `/api/auth/me` | GET/PATCH | Current user profile, and the account's Data source keys by `secretId` (`source_keys`; `has_source_keys` says which are saved) |

---

## Key Files at a Glance

### Frontend

| File | Purpose |
|---|---|
| `src/index.tsx` | App entry point and provider nesting order |
| `src/providers/FlowProvider.tsx` | Canonical workflow state (nodes, edges, outputs, interactions) |
| `src/providers/flow/` | FlowProvider's sections as hooks (Run All, connections, graph edits, outputs, interactions, collaboration sync, dashboard pins, auto-install, the notebook view) and its types |
| `src/utils/notebookLayout.ts`, `src/utils/dataflowOrder.ts` | The notebook view's geometry (cells, dots, lanes, edge paths), what each view lets a viewer change in the graph, and the cell order Export as notebook shares |
| `src/providers/ProvenanceProvider.tsx` | In-memory per-node execution history (saved with the workflow JSON) |
| `src/components/UniversalNode.tsx` | Single React component that renders all node types |
| `src/components/tooltip/` | The one Curio tooltip: `TooltipLayer`, `tooltipStore`, `tooltipPlacement`, `useTooltipContent` and the Vega handler (see [Tooltips](#tooltips)) |
| `src/registry/packagesClient.ts` | Fetch installed manifests → build `NodeDescriptor`s → register against `nodeRegistry` |
| `src/registry/builtinBehaviors.ts` | `registerBehavior()` calls for the built-in behavior hooks |
| `src/registry/behaviorRegistry.ts` | `behavior` key → hook lookup (built-in + package-shipped) |
| `src/registry/nodeRegistry.ts` | Singleton store of all `NodeDescriptor`s; subscribed by the palette + canvas |
| `src/registry/packageRegistryBootstrap.ts` | Boot-time orchestration: load installed packages, inject behavior bundles, build descriptors |
| `src/registry/registryReadiness.ts` | Whether the registry has finished a load: a placeholder node waits on it, and the canvas's load fit waits on it while a node has no descriptor |
| `src/registry/index.ts` | Exposes `window.curio.registerBehavior` + `window.curio.backendUrl` for package bundles |
| `src/registry/types.ts` | TypeScript interfaces for descriptors, adapters, behavior hooks |
| `src/constants.ts` | `SupportedType` and `EdgeType` enums, and `NodeType`, the built-in template ids (node types live in package manifests) |
| `src/adapters/node/` | Built-in behavior hook implementations (code, vega, autk family, …) |
| `src/utils/renderOutcome.ts` | The empty-render decision every browser renderer calls (see [Render Outcomes](#render-outcomes)) |
| `src/contracts/` | The constants the frontend shares with the backend, one JSON file each, and `autkGrammar.ts`, the code over two of them (see [Shared Constants](#shared-constants)) |
| `src/ConnectionValidator.ts` | Edge validation logic |
| `src/api/` | API client wrappers (`projectsApi`, `connectionKeysApi`, `llmConfigsApi`, `monitorApi`); `authApi` lives at `src/utils/authApi.ts` and the packages client in `src/services/packages/` |
| `src/services/packages/` | The node-package service layer (memo dev/143): `packagesApi` (the request object) + `packagesBlobTransport` (sideload, archive download, factory build, `triggerBlobDownload`) + `packageBackendApi` (the only transports), `usePackageCatalog` (THE catalog hook the canvas drawers and the `/catalog/nodes` and `/catalog/models` pages render, scope and `packageKind` as options, with `probeInstallConflicts` the one pre-install probe), the pure logic the surfaces share (`packageListUtils`, `forkPackageLineage`, `packageDependencyNotice`, `packageRestartCopy`, `factoryDraft`), the model package helpers (`modelPackages`, `modelApplication`, `modelCode`) and every package type by concern under `types/` (`SortMode` included). Import from its barrel, `services/packages`; `tests/packages/servicesBarrel.test.ts` enforces that the layer renders nothing, that no node-catalog surface reaches transport, and that the layer never imports `registry/` at runtime: the registry consumes the layer, never the reverse |
| `src/providers/packages/` | `NodeCatalogDrawerProvider` and `PackagePaletteContext`, plus the two hooks that compose the layer with the node-kind registry (`usePackageArchiveImport`, the one sideload pathway, and `useEnsureWorkflowDeps`). `index.tsx` composes from the barrel; other consumers name the module (the barrel carries a rendering provider beside registry-touching hooks) |
| `src/components/packages/publishing/NodeCatalogDrawer.tsx` | The canvas drawer that installs node packages from the catalog: a rendering surface over `usePackageCatalog({ kind: "project" })`; `pages/catalog/useNodeCatalogBrowse.ts` is the page's adapter over the same hook. With `packageKind="model"` both are the Model Catalog's (`components/models/catalog/ModelCatalogDrawer.tsx`, `pages/models/ModelCatalogBrowse.tsx`) |
| `src/services/agents/` | The agents service layer (memo dev/142): `agentsApi` over `utils/sseStream` (the only agent transport), the window events and drag helpers (`resolveAgentDropTarget` included), `useAgentCatalog` / `useAgentAttachments` (the hooks over the transport), the pure logic the surfaces share, and every agent type by concern under `types/`. Import from its barrel, `services/agents`; `tests/agents/servicesBarrel.test.ts` enforces that no agents component, page or provider reaches transport itself |
| `src/providers/agents/` | `AgentAttachmentsProvider` composing `useAgentSession`, `useAgentProposals`, `useAgentSolve`, `useAgentSimulation` and `useAgentNodeRuns`; imported from its barrel, `providers/agents` |
| `src/components/agents/catalog/AgentCatalogDrawer.tsx` | The canvas drawer that adds agents to the open dataflow |
| `src/pages/agents/AgentCatalogBrowse.tsx` | The `/catalog/agents` browse page, the account-scope peer of the other two catalogs |
| `src/components/layout/GlobalPageHeader.tsx` | The top bar of every signed-in page; its Monitor and API Settings open a page, or a drawer on the canvas and the dashboard (see [API Settings and the Monitor](#api-settings-and-the-monitor)) |
| `src/components/layout/HeaderDrawer.tsx` | The drawer shell API Settings, the Monitor and provenance open in on the canvas and the dashboard; with `pinnable`, the catalog drawers' pin |
| `src/providers/ApiSettingsDrawerProvider.tsx`, `src/providers/MonitorDrawerProvider.tsx`, `src/providers/ProvenanceDrawerProvider.tsx` | Mount those drawers, inside `DataflowProviders` |
| `src/components/provenance/` | The provenance drawer: `ProvenanceDrawer`, `ProvenanceHistory` (the list), `DataflowProvenance`, `NodeRunsProvenance`; layout in `src/utils/provenanceTree.ts`, versions in `src/utils/dataflowVersions.ts`, runs in `src/utils/nodeRuns.ts` |
| `src/components/apiSettings/` | API Settings: `ApiSettingsPanel` (the two tabs), `ApiKeysTab`, `AgentConfigTab`, `SourceKeyForm`, `NodeKeyForm`, `ApiSettingsDrawer`, `ApiSettingsRequestHost` and `apiSettingsRequest.ts` (the `curio:api-settings` request event) |
| `src/pages/settings/SettingsPage.tsx` | The settings page, `/settings/keys` and `/settings/agents` |
| `src/pages/monitor/MonitorContent.tsx`, `MonitorDrawer.tsx` | The monitor's content, rendered by the `/monitor` page and by its drawer |
| `src/components/llmConfigs/` | The LLM configuration editor, Agent models and the `llm-config` remedy button, over `src/api/llmConfigsApi.ts` |
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
| `backend/app/runs/models.py` + `repositories.py` | `DataflowRun` and `DataflowRunStep`, the run tables, and their reads, writes and retention |
| `backend/app/execution/save_policy.py` | Which outputs a run on the server installs and records, as the canvas decides it |
| `backend/app/datasets/infrastructure/` | Storage helpers, file metadata, output paths, catalog utilities |
| `backend/app/datasets/schemas/` | Request and catalog-item serialization schemas |
| `backend/app/agents/routes/` | `/api/agents/*` endpoints, one module per resource (`catalog`, `lifecycle`, `attachments`, `proposals`, `turns`, `solve`, `llm`); `common.py` holds the blueprint and the shared helpers; the route table is a contract test (`tests/test_agents/route_table.json`) |
| `backend/app/agents/domain/contracts.py` | The contracts the code and the agents agree on: the prompt fields that fill the markers of the agents' text (see [Agent text](#agent-text)), and the constants it reads from the files it shares with the frontend (see [Shared Constants](#shared-constants)) |
| `backend/app/agents/domain/agent_text.py` | The loader of the agents' text: the base entry and its pages (`curio:<path>`, kept inside it), the start-up render every read returns, and `--dev`'s render at each read (see [Agent text](#agent-text)) |
| `backend/app/agents/schemas/autk-grammar.v1.json` | The vendored Autark grammar schema, with its release record beside it (see [The Autark Schema](#the-autark-schema)) |
| `backend/app/agents/domain/document_validation.py` | Validates the documents agents write (Vega-Lite, Autark) before they reach a node |
| `backend/app/agents/service.py` | The facade every agent route and every other feature calls (mirrors `datasets/service.py`, `packages/service.py`); re-exports the use cases under `application/` (`tests/test_agents/test_layering.py` enforces the layering) |
| `backend/app/agents/application/lifecycle.py` | Import/remove, seed, install with its `requiresAgents` closure, uninstall, publish/unpublish |
| `backend/app/agents/application/catalog.py` | Catalog reads: facets, cards, definition bundles, the three listings, the choosable agents, the catalog settings listing |
| `backend/app/agents/application/attachment_management.py` | Attach, detach, intent/title edits, session read/clear |
| `backend/app/agents/application/proposals/` | Review-before-apply: `mint.py`, `apply.py`, `plans.py`, `store.py`, `cards.py`, and `acquire.py` (the Discovery Catalog acquisition) |
| `backend/app/agents/application/turns/` | One chat turn: `attachment_turn.py` (the two entry points), `turn_loop.py` (`AttachmentTurn`: the bounded tool loop once, blocking or streaming), `prepare.py`, `grounding.py`, `delegates.py`, `roster.py`, `examples.py` (worked examples), `policy.py`, `prompts.py`, `titles.py` |
| `backend/app/agents/application/solve/` | Solve: `session.py` (the stream entry points and the session helpers), `batch.py` (`SolveBatch`: passes, waves, the fold, one finish), `rounds.py` (attempts, probes, remedies), `verified_loop.py` (`VerifiedRounds`: the generate → gate → execute → correct loop, one named stage per method), `node_solve.py`, `budgets.py`, `simulation.py` (`SimulationDriver`), `run_node.py`, `validate.py` |
| `backend/app/agents/application/tool_rounds.py` | The bounded tool loop and the native tool-call machinery (`_RunConversation`) |
| `backend/app/agents/application/llm_listing.py` | `GET /api/agents/llm`: the account's configurations, the deployment's offer, what answers each agent |
| `backend/app/agents/domain/manifest.py` | Parse and validate `manifest.json` into a typed `AgentManifest`; `AGENT_CATEGORIES`; the pages of Curio's agent text a manifest names (`curio:<path>`), the `catalog` placement, and the refusal of a base entry's manifest |
| `backend/app/agents/domain/builtin.py` | The loader of the 7 built-in agents: the folders `agents/<agentId>@<major>/` beside `utk_curio/`, each a `manifest.json` and its `prompts/`, read as an imported agent is (`load_agent_manifest`), in the order their `catalog.order` gives, leaving out the base entry beside them. `catalog.listed` marks the four catalog cards; the rest are internal: never listed, installed or attached, and resolved from their shipped folder when delegated to. It reads their prompts and the base entry's pages as rendered at start, and gives the shape an export or an install carries, without the fields only built-ins use (`catalog`, `workedExamples`, a capability's `label`, a prompt's `runs`). Two internal agents run their capabilities as modes, and the Node Builder and the Researcher run modes beside their chat (see [Agent Prompt Composition](#agent-prompt-composition)) |
| `backend/app/agents/repositories/storage.py` | Definition store under `.curio/users/<u>/agents/<coord>/` |
| `backend/app/agents/repositories/imports.py` | My imports registry (`imported-agents.json`) |
| `backend/app/agents/repositories/catalog_settings.py` | The account's catalog settings (`catalog-settings.json`) and the configuration slot a run receives |
| `backend/app/agents/repositories/project_agents.py` | The per-dataflow lockfile in `spec.dataflow.agents` |
| `backend/app/agents/application/attachments.py` | Attachments in `spec.dataflow.agentAttachments`, plus their sessions |
| `backend/app/agents/infrastructure/provider_config.py` | `resolve_llm`, the one LLM resolver, which reads the deployment's LLM settings (see [LLM Configurations and Resolution](#llm-configurations-and-resolution)) |
| `backend/app/agents/infrastructure/llm_configs.py` | The account's LLM configurations (`llm-configs.json`): validation, the default, and the store reads that carry a key |
| `backend/app/common/owner_only_file.py` | Owner-only JSON files: 0700 directory, 0600 file, atomic write under an exclusive lock. Used by connection keys, Data source keys and LLM configurations |
| `backend/app/agents/infrastructure/providers.py` | Provider-neutral dispatch port; the only place an LLM SDK is imported. Typed turns and their text forms, streaming, the system slots per provider, native tools per provider and their refusal, cache usage, the native-tools trial, and the live model listing |
| `backend/app/agents/application/tools.py` | The tool registry: each contract's effect, description and params schema, grant resolution, the read executors, and the native tools a run is offered |
| `backend/app/agents/application/reply_schemas.py` | The Autark document's reply schema, projected from the vendored schema per provider flavor; decoding a reply; which runs send one |
| `backend/app/agents/infrastructure/chat_capabilities.py` | What an endpoint can do beyond text (native tools, a reply schema): the table, the per-model trial and its record, and the scripted provider |
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

### Launcher

`curio.py` calls `main()` in `utk_curio/main.py`, which holds the argument parser and the start sequence. What it calls lives in `utk_curio/cli/`:

| File | Purpose |
|---|---|
| `cli/logs.py` | The log file, terminal colors, verbosity, `log_*` helpers |
| `cli/lifecycle.py` | Child process output streaming, `signal_handler`, `clean_shutdown` |
| `cli/arguments.py` | Argument types (`base_path_arg`, `backend_url_arg`) and `get_command_prefix` |
| `cli/environment.py` | `set_environment_variables` (arguments to environment variables) and the isolation decision |
| `cli/frontend_build.py` | `NODE_MAJOR`, Node and node_modules checks, the frontend build and its stamp |
| `cli/static_server.py` | `run_spa_static_server`, the static server for the built frontend |
| `cli/dependencies.py` | pip and manifest dependency installs, the sandbox's Node.js packages, DuckDB extension seeding |
| `cli/services.py` | `start_frontend`, `start_backend`, `start_sandbox`, the database migration, `_kill_port` |
| `cli/test_runner.py` | `curio test` and its translation to `scripts/test.sh` flags |
