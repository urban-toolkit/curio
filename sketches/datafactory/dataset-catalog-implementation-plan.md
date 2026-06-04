# Dataset Catalog Implementation Plan

## Overview

Implement the DataFactory dataset screens as a decoupled Dataset Catalog feature. The catalog should support browsing datasets in the catalog, inspecting dataset details, installing datasets into the current dataflow, showing installed/computed/imported datasets in a palette, and applying datasets to Data Loader/code nodes.

The feature must remain independent from node packs. It can reuse UI patterns from the existing package and node catalog surfaces, but dataset logic, APIs, state, and persistence should live behind a dedicated dataset-catalog service.

## Product Goals

- Provide a Data Catalog browse experience for finding reusable datasets.
- Provide a dataset detail view with metadata, schema/preview, install, and publish actions.
- Provide an in-canvas Data Catalog drawer aligned with the project's existing UI components.
- Provide an Installed Dataset Palette similar to the node packs palette menu, but without packs.
- Treat current dataflow datasets as installed, imported, or locally computed.
- Make dataset application easy by dragging a dataset into a Data Loader/code node.
- Autocomplete dataset path and required loader code when a dataset is applied to a loader node.
- Remove product copy that explicitly refers to global/project scope. Use installed, imported, computed, current dataflow, or Data Catalog language instead.

## Non-Goals

- Do not couple datasets to node packs.
- Do not require datasets to be installed through packages.
- Do not add ratings, install counts, or marketplace-style footer metadata to dataset cards.
- Do not build a remote production registry unless one already exists. A fixture-backed or local registry source is acceptable for v1.

## Existing References

- Drawn screens:
  - `sketches/datafactory/idea1/01_data_hub_browse.svg`
  - `sketches/datafactory/idea1/02_dataset_detail.svg`
  - `sketches/datafactory/idea1/03_catalog_drawer.svg`
  - `sketches/datafactory/idea1/04_install_publish.svg`
  - `sketches/datafactory/idea1/05_installed_palette.svg`
- UI style references:
  - `sketches/datafactory/base/`
- Existing frontend patterns to reuse carefully:
  - `NodeCatalogDrawer`
  - `PackageCard`
  - `PackagesPaletteDropdown`
  - `ToolsMenu`
  - `DatasetsWindow`
  - `CodeEditor`
  - `FlowProvider`
- Existing backend dataset routes:
  - `/datasets`
  - `/upload`
  - `/get`
  - `/get-preview`

## Architecture

### Backend Service Boundary

Create a dedicated `DatasetCatalogService` as the only backend entry point for dataset catalog operations.

The service should orchestrate smaller collaborators:

- `DatasetRegistryRepository`
  - Scans the committed Data Catalog at ``<repo_root>/datasets/``.
  - Each catalog entry is a self-contained directory ``<datasetId>@<major>/`` with ``manifest.json``, optional ``integrity.json``, and a ``data/`` payload tree (mirrors node packs under ``<repo_root>/packages/``).
- `UserDatasetStore` / dataset installer
  - Copies catalog datasets into ``<CURIO_LAUNCH_CWD>/.curio/users/<user_key>/datasets/<datasetId>@<major>/`` on install (same layering as node packs).
- `InstalledDatasetRepository`
  - Reads and writes dataset references in the active dataflow spec (`dataflow.datasets`).
  - References point at files inside the user's dataset store after a hub install.
- `ComputedDatasetIndexer`
  - Discovers datasets produced by successful node executions in the current dataflow.
- `DatasetPreviewService`
  - Produces sample rows, schema, columns, geometry hints, and lightweight file stats.
- `DatasetLoaderSnippetService`
  - Produces loader snippets and import requirements for code/Data Loader nodes.

The service should not import node-pack or package registry services. Any shared code should be generic filesystem, preview, or metadata utilities.

### On-Disk Layout (mirrors node packs)

| Layer | Path | Who writes |
| --- | --- | --- |
| **Shared Data Catalog** — browse source for every user | ``<repo_root>/datasets/<datasetId>@<major>/`` | Publish-to-Catalog (future; dev fixtures committed in-repo for v1) |
| **Per-user dataset store** — installed payload on disk | ``<CURIO_LAUNCH_CWD>/.curio/users/<user-key>/datasets/<datasetId>@<major>/`` | Install copies from catalog; uninstall removes only the dataflow reference (store copy may remain until a future prune pass) |
| **Per-dataflow references** — what the canvas/palette reads | ``spec.dataflow.datasets[]`` | Install/uninstall API on the active project |

Each catalog directory is self-contained:

```text
<datasetId>@<major>/
  manifest.json
  integrity.json          # optional v1+
  data/
    <payload files>         # referenced by manifest.dataFile
```

Manifest fields (v1 subset):

- ``id`` — reverse-DNS dataset id (``data.urbanlab.chicago-community-areas``)
- ``name``, ``description``, ``version``, ``format``, ``publisher``, ``license``, ``tags``
- ``dataFile`` — relative path to the primary payload inside the directory
- ``rowCount`` / ``featureCount`` / ``schema`` — optional catalog metadata for browse/detail UI
- ``compatibility.major`` — major version segment used in the directory name

Committed examples live under ``datasets/data.urbanlab.*@1/`` (parallel to ``packages/curio.builtin@1/``).

Install flow:

1. User installs a hub dataset into a dataflow.
2. Backend copies ``<repo_root>/datasets/<dirName>/`` → ``.curio/users/<u>/datasets/<dirName>/`` if not already present.
3. Backend writes/updates a ``DataflowDatasetRef`` with ``datasetId``, ``dirName``, and the resolved ``path`` to the installed ``dataFile``.
4. Preview/schema reads from the user-store path when installed, otherwise from the shared catalog copy for browse/detail.

### Frontend Service Boundary

Create a frontend dataset catalog service area:

```text
src/services/datasetCatalog/
  datasetCatalogApi.ts
  datasetCatalogTypes.ts
  datasetCatalogHooks.ts
  datasetApplication.ts
  datasetLoaderSnippets.ts
```

Responsibilities:

- `datasetCatalogApi.ts`
  - Own all HTTP calls for dataset catalog behavior.
- `datasetCatalogTypes.ts`
  - Own shared frontend types and DTO mappers.
- `datasetCatalogHooks.ts`
  - Own React query/cache style hooks or local provider hooks.
- `datasetApplication.ts`
  - Own drag/drop payload parsing and node application rules.
- `datasetLoaderSnippets.ts`
  - Own client-side fallback snippets and display helpers.

UI components should consume this service layer instead of calling backend routes directly.

## Data Model

### Dataset Origin

```ts
type DatasetOrigin = "source_node" | "computed" | "imported" | "hub";
```

Origin display labels:

- `source_node`: Source nodes
- `computed`: Computed
- `imported`: Imported
- `hub`: Data Catalog

Left rail filters should use:

- BY ORIGIN
- Source nodes
- Computed
- Imported

Do not display global/project scope labels in the UI.

### Dataset Catalog Item

```ts
type DatasetFormat =
  | "csv"
  | "geojson"
  | "json"
  | "parquet"
  | "geotiff"
  | "shp";

type DatasetCatalogItem = {
  id: string;
  title: string;
  description?: string;
  origin: DatasetOrigin;
  format: DatasetFormat;
  uri: string;
  path?: string;
  sizeBytes?: number;
  rowCount?: number;
  featureCount?: number;
  producerNodeId?: string;
  consumerNodeIds: string[];
  updatedAt: string;
  sourceLabel?: string;
  license?: string;
  tags: string[];
  schema?: DatasetSchema;
  loaderSnippet?: DatasetLoaderSnippet;
};
```

### Dataset Schema

```ts
type DatasetSchema = {
  fields: Array<{
    name: string;
    type: string;
    nullable?: boolean;
    sample?: string | number | boolean | null;
  }>;
  geometryType?: string;
  crs?: string;
};
```

### Loader Snippet

```ts
type DatasetLoaderSnippet = {
  language: "python";
  imports: string[];
  code: string;
  pathVariable: string;
};
```

### Dataflow Persistence

Add optional dataset metadata to the saved dataflow spec:

```ts
type DataflowDatasetRef = {
  datasetId: string;
  origin: DatasetOrigin;
  sourceOrigin?: DatasetOrigin;
  uri: string;
  path?: string;
  dirName?: string;
  title: string;
  format: DatasetFormat;
  installedAt: string;
};
```

Persist installed/imported dataset references in:

```text
dataflow.datasets
```

Computed datasets may be indexed dynamically from node outputs, but should be normalized into the same catalog response shape.

## Backend API

Add dataset catalog routes under `/api` where possible. If the current backend route structure does not use `/api`, keep naming consistent with the existing app while preserving these route semantics.

### List Catalog Datasets

```http
GET /api/datasets/catalog?q=&format=&origin=&sort=recent
```

Returns:

```ts
{
  items: DatasetCatalogItem[];
  facets: {
    origin: Record<DatasetOrigin, number>;
    format: Record<DatasetFormat, number>;
  };
}
```

Behavior:

- Include hub, installed/imported, source node, and computed datasets according to context.
- Support search by title, description, tags, path, and source label.
- Support origin and format filtering.
- Default sort: recent activity.

### Get Dataset Detail

```http
GET /api/datasets/:datasetId
```

Returns:

```ts
DatasetCatalogItem
```

Behavior:

- Include schema and loader snippet when available.
- Include producer and consumer node references for local dataflow datasets.

### Get Dataset Preview

```http
GET /api/datasets/:datasetId/preview
```

Returns:

```ts
{
  schema: DatasetSchema;
  rows: unknown[];
  rowLimit: number;
  truncated: boolean;
}
```

Behavior:

- CSV: return parsed sample rows and inferred field types.
- JSON: return top-level sample records where possible.
- GeoJSON: return properties, geometry type, CRS if available, and sample features.
- Unsupported or large formats: return metadata with a helpful unsupported-preview state.

### Import Dataset

```http
POST /api/datasets/import
```

Request:

```ts
{
  source: "upload" | "path" | "url";
  file?: File;
  path?: string;
  url?: string;
  title?: string;
}
```

Behavior:

- Store or register the dataset.
- Add it to current dataflow metadata when a dataflow context is present.
- Return a normalized `DatasetCatalogItem`.

### Publish Dataset

```http
POST /api/datasets/publish
```

Request:

```ts
{
  datasetId: string;
  title: string;
  description?: string;
  tags: string[];
  license?: string;
}
```

Behavior:

- Publish into the v1 fixture/local catalog or the real registry if one exists.
- Return the published catalog item.

### Install Dataset Into Dataflow

```http
POST /api/dataflows/:dataflowId/datasets/install
```

Request:

```ts
{
  datasetId: string;
}
```

Behavior:

- Copy the catalog directory into the user's dataset store when the source is a hub dataset (``origin: hub``).
- Add a dataset reference to `dataflow.datasets` with ``dirName`` and resolved ``path``.
- Do not mutate package/node-pack state.
- Return the installed catalog item.

### Remove Installed Dataset

```http
DELETE /api/dataflows/:dataflowId/datasets/:datasetId
```

Behavior:

- Remove only the installed reference.
- Do not delete source files unless a separate destructive delete action is explicitly implemented.

## Loader Snippet Rules

Generate snippets through `DatasetLoaderSnippetService`.

CSV:

```python
import pandas as pd

dataset_path = "<path>"
df = pd.read_csv(dataset_path)
```

GeoJSON and SHP:

```python
import geopandas as gpd

dataset_path = "<path>"
gdf = gpd.read_file(dataset_path)
```

JSON:

```python
import json

dataset_path = "<path>"
with open(dataset_path) as f:
    data = json.load(f)
```

GeoTIFF:

```python
import rasterio

dataset_path = "<path>"
src = rasterio.open(dataset_path)
```

If required Python packages are missing, show a non-blocking helper state near the code insertion rather than failing silently.

## Frontend Implementation

### Dataset Catalog Provider

Add a `DatasetCatalogProvider` or colocated hooks that expose:

- catalog items
- installed/current dataflow datasets
- origin counts
- active filters
- loading/error states
- install/uninstall actions
- import/publish actions
- preview/detail fetching
- apply-to-node action

The provider should be scoped to the active dataflow where possible.

### Data Catalog Browse Screen

Route:

```text
/data-hub
```

UI requirements:

- Use existing Curio chrome and visual language.
- Left filter rail with BY ORIGIN and format filters.
- Dataset cards use metadata rows instead of ratings/install counts.
- Metadata row example:
  - `2,408 feat. | 1.8 MB | 3 nodes consume | 1h ago`
- No card footer with `size · free`.
- Search and sort controls should match existing project UI patterns.
- Primary action: install/open detail.

### Dataset Detail Screen

Route:

```text
/data-hub/:datasetId
```

UI requirements:

- Show title, source label, updated time, tags, metadata summary, schema, preview, and loader snippet.
- Primary action: install dataset into current dataflow.
- Secondary actions: copy path, preview, publish where relevant.
- Avoid ratings, global/project scope, or marketplace install count language.

### In-Canvas Data Catalog Drawer

UI requirements:

- Match the base screenshots:
  - dark app chrome
  - right drawer
  - dark header
  - search
  - tabs
  - compact cards
  - import button
- Reuse drawer ergonomics from `NodeCatalogDrawer`.
- Dataset drawer state should be independent from node catalog drawer state.
- Drawer cards should show origin, format, size/features, consumers, and recent activity.

### Installed Dataset Palette

UI requirements:

- Add a palette menu similar to the node packs palette dropdown.
- Do not include packs.
- Show datasets installed, imported, or computed in the current dataflow.
- Support search and origin sections.
- Support drag from palette into the canvas or onto Data Loader/code nodes.
- Show empty states:
  - no installed datasets
  - no computed datasets yet
  - import/install prompt

### Dataset Application Workflow

Drag payload:

```ts
const DATASET_DRAG_MIME = "application/x-curio-dataset";
```

Payload:

```ts
{
  datasetId: string;
  title: string;
  uri: string;
  path?: string;
  format: DatasetFormat;
}
```

Behavior:

- Dragging onto a Data Loader/code node inserts or updates:
  - dataset path
  - required imports
  - loader code
- Dragging onto empty canvas may create a Data Loader node if that is already an established node creation pattern.
- Dragging onto unsupported nodes should show a clear unsupported target state.
- Applying a dataset should update node metadata with a dataset reference:

```ts
{
  datasetRefs: string[];
}
```

Code insertion should preserve existing user code where possible. If the node is empty, insert the full generated snippet. If code exists, insert imports and path/snippet at a safe cursor or configured loader block location.

## UI Copy Rules

Use:

- Data Catalog
- Installed datasets
- Computed
- Imported
- Source nodes
- Current dataflow
- Recent activity
- Nodes consume

Avoid:

- Global
- Project scope
- Project-scoped
- Marketplace ratings
- Install counts as popularity metrics
- Card footer text like `12.3 MB · Free`

## Development Practices

- Keep dataset catalog code decoupled from package and node-pack code.
- Keep backend route handlers thin; delegate behavior to `DatasetCatalogService`.
- Keep frontend components presentation-oriented; delegate data fetching and actions to dataset-catalog hooks.
- Define types in one service area and map backend DTOs at the boundary.
- Prefer small, testable services over large UI-driven logic.
- Preserve existing routes and dataset modal behavior during migration unless replacement is verified.
- Add feature-specific tests before removing compatibility paths.
- Handle loading, empty, error, and unsupported-preview states explicitly.
- Do not introduce unrelated refactors.

## Implementation Phases

### Phase 1: Backend Dataset Catalog Foundation

- [x] Add backend `DatasetCatalogService`.
- [x] Add repository interfaces for registry, installed, and computed datasets.
- [x] Move existing local `/datasets` behavior behind the service.
- [x] Add normalized dataset item DTOs.
- [x] Add manifest-backed Data Catalog at ``<repo_root>/datasets/`` plus user-store install copies.
- [x] Add preview and schema extraction service.
- [x] Add loader snippet generation service.
- [x] Add tests for catalog listing, filtering, previews, and snippets.

### Phase 2: Frontend Service Layer

- [x] Add `src/services/datasetCatalog/`.
- [x] Add typed API client.
- [x] Add DTO mappers and frontend types.
- [x] Add hooks/provider for catalog data.
- [x] Add install, import, publish, preview, and apply-to-node actions.
- [x] Add unit tests for service mapping and actions.

### Phase 3: Data Catalog And Detail Screens

- [x] Add Data Catalog route and browse screen.
- [x] Add dataset detail route.
- [x] Implement metadata-first dataset cards.
- [x] Implement BY ORIGIN filters.
- [x] Remove ratings/install-count UI from dataset surfaces.
- [x] Remove card footer metadata.
- [x] Add detail preview, schema, and snippet sections.

### Phase 4: In-Canvas Drawer

- [x] Add Data Catalog drawer entry point.
- [x] Build drawer using existing project UI patterns.
- [x] Add search, sort, tabs, filters, cards, and import action.
- [x] Keep drawer state independent from node catalog/package state.
- [x] Add empty/error/loading states.

### Phase 5: Installed Dataset Palette And Apply Workflow

- [x] Add Installed Dataset Palette near existing node pack palette affordances.
- [x] Show installed, computed, imported, and source-node datasets for the current dataflow.
- [x] Add dataset drag payload support.
- [x] Add Data Loader/code node drop handling.
- [x] Insert path and loader code from snippets.
- [x] Track applied dataset references in node metadata.
- [ ] Add interaction tests for drag-to-apply.

### Phase 6: Migration And Cleanup

- [ ] Route legacy dataset modal actions through the new service.
- [ ] Keep or remove the legacy modal based on verified replacement coverage.
- [ ] Remove duplicate direct fetch logic.
- [ ] Confirm no dataset UI imports package/node-pack services.
- [ ] Confirm copy avoids global/project scope wording.

## Test Plan

### Backend Tests

- Catalog list returns hub, imported, source-node, and computed datasets.
- Origin and format filters return correct facets and counts.
- Search matches title, tags, path, and source label.
- Installing a hub dataset copies ``<repo_root>/datasets/<dirName>/`` into ``.curio/users/<u>/datasets/<dirName>/`` and writes a dataflow ref with ``path`` + ``dirName``.
- Installing a workspace/imported dataset writes only dataflow dataset metadata (path already local).
- Removing a dataset removes only the dataflow reference.
- Preview service handles CSV, JSON, GeoJSON, and unsupported formats.
- Loader snippet service returns correct imports and code for each supported format.

### Frontend Unit Tests

- API client maps backend DTOs into frontend types.
- Dataset hooks expose loading, error, empty, and success states.
- Origin filters use Source nodes, Computed, and Imported labels.
- Dataset card metadata row replaces rating/install UI.
- Dataset application helper builds the correct drag payload.

### Component And Interaction Tests

- Data Catalog browse screen filters and sorts datasets.
- Dataset detail screen renders schema, preview, and install action.
- Data Catalog drawer opens, searches, filters, and imports.
- Installed Dataset Palette lists current dataflow datasets.
- Dragging a dataset onto a Data Loader/code node inserts path and loader code.
- Unsupported drop targets show a clear non-destructive state.

### Regression Tests

- Dataset catalog UI does not depend on package/node-pack APIs.
- Existing dataset upload/listing behavior still works during migration.
- Existing node catalog and packages palette behavior is unchanged.

## Acceptance Criteria

- Dataset catalog screens match the intent and visual language of the drawn SVGs and base screenshots.
- Project-scoped/global copy is removed from dataset UI.
- Dataset cards show operational metadata instead of ratings/install counts.
- The left rail includes BY ORIGIN with Source nodes, Computed, and Imported filters.
- Installed Dataset Palette shows current dataflow datasets without pack grouping.
- Dragging a dataset into a Data Loader/code node autocompletes path and loader code.
- Dataset catalog behavior is routed through a decoupled dataset-catalog service.
- Backend and frontend tests cover core catalog, preview, install, and apply workflows.

## Assumptions

- Data Catalog is manifest-backed under ``<repo_root>/datasets/``; installed hub payloads live under ``.curio/users/<user>/datasets/`` like node packs under ``packages/``.
- Installed datasets are persisted in `dataflow.datasets`.
- Computed datasets are discovered from successful node outputs in the active dataflow.
- `curio://` style URIs may be used for display, but runtime snippets should use resolvable file paths.
- Data Loader/code node application is the primary apply workflow.
- Creating a new Data Loader node from a canvas drop is optional unless an existing canvas node creation pattern makes it straightforward.
