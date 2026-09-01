# Data Catalog

The Data Catalog is where Curio's **datasets** live. It is the counterpart to the [Node Catalog](NODE-CATALOG.md). Where the Node Catalog manages the *nodes* you drop on the canvas, the Data Catalog manages the *data* those nodes read: files shipped with your deployment, files you import from your machine, and the outputs your own dataflows compute.

This guide is in six parts, plus operator notes:

- [1. What is the Data Catalog?](#1-what-is-the-data-catalog): the three storage layers, dataset ids, and the manifest.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the three places you manage datasets, the action matrix between them, and step-by-step walkthroughs.
- [3. Using a dataset in a dataflow](#3-using-a-dataset-in-a-dataflow): drag-and-drop, generated loader code, and linkage badges.
- [4. Computed datasets (node outputs)](#4-computed-datasets-node-outputs): the save-output toggle, lineage, and bundles.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): supported formats, OSM PBF, publish, unpublish, and delete.
- [6. Previews, schema, and export](#6-previews-schema-and-export): what each format supports.
- [Operator notes](#operator-notes): env vars, catalog relocation, and who may unpublish.

---

## 1. What is the Data Catalog?

### Concept

A **dataset** in Curio is a small self-contained folder, shaped like a node package, identified by a reverse-domain id and a major version:

```
<datasetId>@<major>     e.g.   data.urbanlab.chicago-boundary@1
                               computed.a1b2c3.node-7@1
                               imported.xf3c91a08b2d4@1
```

The folder holds a `manifest.json` (the contract) and the data itself under `data/`:

```
data.urbanlab.chicago-boundary@1/
  manifest.json
  data/chicago.geojson
```

Eleven dataset packages ship with Curio in the committed catalog at `<repo_root>/datasets/`, grouped by the owner of the data: six under `data.urbanlab.*` (the Chicago boundary and community areas, an ACS profile, and the three Milan heat-exposure inputs), four under `data.cityofchicago.*` (green roofs, 2010 energy usage, and the speed-camera and red-light violation tables), and one under `data.projectsidewalk.*` (Chicago accessibility labels). Together they are the inputs to the curated example dataflows in `docs/examples/`.

### Where datasets come from: the four origins

Every catalog row carries an `origin`, which is what the browse filters and provenance chips key on:

| Origin | Meaning |
|---|---|
| `hub` | Published into the shared catalog and browsable by every user on this install. |
| `imported` | A file you uploaded from your machine. |
| `computed` | The output of a node in one of your dataflows, saved automatically on run. |
| `source_node` | A dataset carried by a node's own configuration rather than the catalog. |

The UI groups `hub`, `imported`, and `source_node` under a single **Imported** label, leaving **Computed** as the meaningful distinction for filtering.

### The three storage layers

Dataset state lives in three places. As with node packages, knowing which layer each action writes is the key to predicting what happens after an **Add to dataflow**, a **Remove from dataflow**, or a **Delete**:

| Layer | On disk | Who writes |
|---|---|---|
| **Shared catalog**, the "hub" every user browses | `<repo_root>/datasets/<datasetId>@<major>/`, or `$CURIO_CATALOG_ROOT` when set | **Publish** writes here; **Unpublish** removes. Read-only otherwise. The directory is *never created eagerly*; see *Operator notes*. |
| **Per-user dataset store**, the actual bytes you can read | `<CURIO_LAUNCH_CWD>/.curio/users/<user-key>/datasets/<datasetId>@<major>/` | **Import**, **Add to dataflow** (copying a hub dataset in), and the automatic save of node outputs. **Delete** removes it permanently. |
| **Per-dataflow refs**, what one dataflow declares it needs | `spec.trill.json` → `dataflow.datasets: []` | The drawer's **Add to dataflow** adds an entry for the open dataflow; **Remove from dataflow** removes it. The shipped examples carry theirs as committed declarations. |

> [!NOTE]
> Unlike node packages, datasets have **no per-user "defaults" layer**. Nothing auto-seeds a dataset into every new dataflow, and correspondingly there is no "add everywhere" action. Adding a dataset is always scoped to one dataflow.
>
> The seeded **example projects** are the one deliberate exception. Each example declares the datasets it needs in its own `dataflow.datasets` section, exactly as it declares its node packages in `dataflow.packages`, and Curio provisions those into your dataset store when the examples are seeded (`--with-examples` / `--deploy`) and again the first time you open a project. This is a *provisioning* step for a declaration the example already carries, not an "add everywhere": it never touches a dataflow you did not open, and it adds nothing to a new one. See `utk_curio/backend/app/datasets/seed.py`.

The most important consequence: **computed datasets are account-level assets, not project contents.** Running a node saves its output into your per-user store and writes *no* `dataflow.datasets` ref. It appears in the catalog immediately, but it is only "in" a dataflow once you add it there.

> [!NOTE]
> A fourth thing exists, but it is not a storage layer: the **dataset index**, a
> database table mirroring your store's manifests so catalog listings are keyed
> lookups instead of re-parsing every `manifest.json`. It is a cache, and disk
> always wins: it is reconciled against the store on every listing, a manifest
> it cannot read has its row dropped, and any failure falls back to scanning.
> Nothing you do interacts with it directly and nothing is lost if it is wiped;
> see [ARCHITECTURE.md](ARCHITECTURE.md#the-dataset-index) if you are working on
> the backend.

### Dataset ids

Ids are 2 to 6 dot-separated lowercase segments (`[a-z][a-z0-9-]*`, at most 63 chars each), with a major version between `0` and `9999`. Curio mints ids for you in the non-hub cases:

| Kind | Id form | Note |
|---|---|---|
| Catalog / published | `data.urbanlab.chicago-boundary` | Authored by hand in the manifest. |
| Imported | `imported.x<uuid12>` | Fresh per import; re-uploading the same bytes creates a **second** dataset. |
| Computed | `computed.<dataflowId>.<nodeId>` | Namespaced by dataflow, so the same node id in two dataflows never collides. |
| OSM PBF group | `osm.x<uuid8>` | The synthetic parent of one import's layers. |
| Published from a non-conforming id | `local.data.<slug>` | Applied when the original id doesn't match the grammar. |

### The manifest

Dataset manifests are validated in code ([`domain/manifest.py`](../utk_curio/backend/app/datasets/domain/manifest.py)); there is no JSON Schema file for them today, so this table is the reference:

| Field | Required | Meaning |
|---|---|---|
| `id` | Yes | Dataset id (see grammar above). |
| `name` | Yes | Display title. |
| `version` | Yes | Free-form version string (e.g. `"1.0.0"`), independent of `compatibility.major`. |
| `format` | Yes | One of `csv`, `geojson`, `json`, `parquet`, `geotiff`, `shp`, `bundle`. |
| `dataFile` | Yes | Path to the data relative to the dataset folder, e.g. `data/chicago.geojson`. |
| `compatibility.major` | No | Integer major version; defaults to `1`. Together with `id` it forms the directory name. |
| `description` | No | Defaults to `""`. |
| `publisher` | No | Defaults to `"Data Catalog"`. **Load-bearing**: it decides who may unpublish or delete (see *Operator notes*). |
| `license` | No | Free text, e.g. `"Open Data"`. |
| `tags` | No | Array of strings; feeds search and the Tags panel. |
| `sourceLabel` | No | Short provenance label shown on cards; falls back to `publisher`. |
| `createdAt` / `updatedAt` | No | ISO timestamps for the Curio *record*. |
| `sourceUpdatedAt` | No | Last-modified date of the *original file* at import time. |
| `featureCount` / `rowCount` | No | Counts for geo and tabular data respectively. |
| `schema` | No | Object describing fields; inferred from a preview when absent. |
| `groupId` / `layerName` | No | Multi-part imports (OSM PBF): every layer of one import shares a `groupId`. |
| `producerNodeId`, `producerNodeType`, `producerDataflowId`, `producerDataflowName`, `upstreamInputs` | No | Lineage for computed datasets (see [part 4](#4-computed-datasets-node-outputs)). |

---

## 2. Surfaces and workflows

There are three places you interact with datasets, and unlike the Node Catalog, they are **not** interchangeable:

- **The `/catalog/data` page** is a read-only library view. Reach it from `/projects` → **Catalog** in the top nav → the **Data** tab. You can browse, filter, preview, publish, and open a dataset's detail page. You **cannot add a dataset to a dataflow from here**, because adding is always relative to a dataflow and this page has none. (The legacy `/data-hub` URL redirects here.)
- **The Data Catalog drawer** (inside the canvas) is the working surface. Open it from the top menu **Data ⏷ → Data Catalog**, or from the left Tools panel's **Data Catalog** dropdown → **Browse Data Catalog +**. Everything scoped to the open dataflow happens here: Add to dataflow, Remove from dataflow, Import, Publish, Unpublish, Delete.
- **The Data palette** (left Tools panel, the **Data Catalog** dropdown) holds the datasets already added to this dataflow, ready to drag onto the canvas. It sits in the left rail below the built-in nodes and the **Node Catalog** dropdown, mirroring the latter; its panel opens in the strip to the right of the rail.

The drawer has four tabs: **Featured** (published or already added, capped at six), **Browse all** (the default), **In dataflow**, and **Computed**.

### Action matrix

| Action | Where | Endpoint | Layers it writes | What you see |
|---|---|---|---|---|
| **Add to dataflow** | Drawer | `POST /api/dataflows/<id>/datasets/install` | per-dataflow refs (+ user store if the dataset came from the hub) | The dataset appears in this dataflow's **Data Catalog** palette, ready to drag. |
| **Remove from dataflow** | Drawer (**Remove from dataflow**, or the trash icon in the **In dataflow** tab) | `DELETE /api/dataflows/<id>/datasets/<id>` | per-dataflow refs | It leaves this dataflow's palette. The account-level copy is **kept**. |
| **Import** | Drawer footer (**Import dataset**) | `POST /api/datasets/import` | per-user store | The file is registered in your catalog. It is **not** attached to the open dataflow; add it afterwards. |
| **Publish** | Drawer, `/catalog/data` cards, or the detail panel (**Publish to Catalog**) | `POST /api/datasets/publish` | shared catalog | The dataset becomes browsable by every user on this install. |
| **Unpublish** | Drawer or detail panel | `DELETE /api/datasets/publish/<id>` | shared catalog | The listing goes away. Copies already added to dataflows are untouched. |
| **Delete** | Drawer (computed datasets only) | `DELETE /api/datasets/<id>` | per-user store (+ refs in every project) | The dataset is **permanently** removed from your account, and references to it are stripped from all your dataflows. |

Only **Unpublish** and **Delete** ask for confirmation; Add to dataflow, Remove from dataflow, Publish, and Import act immediately.

### Workflows

**I want to use a catalog dataset in my dataflow.** Open the dataflow, then **Data ⏷ → Data Catalog**. Find the dataset, click **Add to dataflow**. It now appears in the left Tools panel's **Data Catalog** dropdown. Drag it onto the canvas to get a Data Loading node wired to it ([part 3](#3-using-a-dataset-in-a-dataflow)).

**I want to use a file from my computer.** Open the drawer and click **Import dataset** in the footer. Pick the file (`.csv`, `.geojson`, `.json`, `.parquet`, `.tif`, `.tiff`, `.shp`, `.pbf`). Import only *registers* the dataset in your account. Switch to the **In dataflow** or **Browse all** tab and click **Add to dataflow** to attach it to the open dataflow.

**I want to reuse a node's output as an input somewhere else.** Turn on the node's save-output toggle (the database icon next to its play button), then run it: the output is saved as a computed dataset. Open the drawer's **Computed** tab and click **Add to dataflow** on it, either in this dataflow or in a different one.

**I want to remove a dataset from one dataflow but keep it.** Use **Remove from dataflow** in the drawer. This only drops the `dataflow.datasets` ref; the bytes stay in your account store and the dataset stays in the catalog.

**I want a dataset gone for good.** Use **Delete** in the drawer (available on computed, non-hub datasets). This is the destructive one: it removes the stored copy and strips references from every dataflow that used it. The confirmation tells you how many nodes are affected.

**I want other users on this deployment to see my dataset.** Click **Publish**. It is copied into the shared catalog at `<repo_root>/datasets/`. Only the person recorded as the manifest's `publisher` can later unpublish it.

> [!NOTE]
> There is no hosted dataset registry. Publishing is per-deployment, exactly like the node catalog's: it writes into the directory this Curio install reads from.

---

## 3. Using a dataset in a dataflow

Adding a dataset to a dataflow does not create anything on the canvas. You consume it by **dragging** it from the **Data Catalog** palette (or from a card in the drawer):

- **Drop on empty canvas** → Curio creates a **Data Loading** node pre-filled with loader code for that dataset, and confirms with *"Created a Data Loading node for `<title>`."*
- **Drop onto an existing node** → the loader code is merged into that node's existing code, under a `# Curio dataset loader: <title>` marker, and confirms with *"Applied `<title>` to this node."* If the node's code already ends in a `return`, the loader block is inserted before it and the return is rewritten.

The generated Python matches the format:

| Format | Generated code |
|---|---|
| `csv` | `pd.read_csv(dataset_path)` → `df` |
| `geojson`, `shp` | `gpd.read_file(dataset_path)` → `gdf` |
| `parquet` | `gpd.read_parquet`, falling back to `pd.read_parquet` → `df` |
| `json` | `json.load(f)` → `data` |
| `geotiff` | `rasterio.open(dataset_path)` → `src` |
| `bundle` | Rebuilds every part and returns a tuple → `bundle` |
| OSM group | A `layers` dict of per-layer GeoParquet reads |

The location line is written as a portable `curio_dataset_path("<datasetId>")` call that the sandbox resolves to a real filesystem path at execution time, so the generated code carries no machine-, user-, or mount-specific absolute path and stays valid when the dataflow is shared or moved. Curio falls back to embedding the literal path only when the dataset has no usable id.

**Clicking** a palette row (rather than dragging it) does something different: it highlights every node on the canvas that uses that dataset. If none do, you get an info toast saying so.

Nodes tied to a dataset show a small pill on their title bar: **DATASET** when the node reads one, **OUTPUT** when the node produced one. Clicking the pill reveals the dataset in the palette. Palette rows and drawer cards carry a **connection badge** like `1↑ 2↓`, meaning one upstream producer and two downstream consumers, computed live from the current dataflows.

---

## 4. Computed datasets (node outputs)

### The save-output toggle

Every runnable node has a small database-icon toggle immediately to the right of its play button. It is **off by default**, so saving is opt-in per node; the deployment-wide default is controlled by `CURIO_DEFAULT_SAVE_NODE_OUTPUT`. When it is on, running the node saves its output into your per-user dataset store as `computed.<dataflowId>.<nodeId>@1`.

Every output type a node can declare is saved, not just tabular ones:

| Node output | Saved as |
|---|---|
| DataFrame, GeoDataFrame | `parquet` |
| Raster | `geotiff` |
| A plain Python value: dict, list, string, number, boolean, or `None` | `json` |
| A tuple | `bundle`, one part per item (see [Bundles](#bundles)) |
| A list or dict *containing* DataFrames | `bundle`, one part per element; a dict keeps its keys as part labels |

JSON is written uncompressed, and a scalar is stored bare rather than wrapped,
so the stored file is readable by a plain `json.load` and exports as-is. That
matters when you drag the dataset back onto the canvas: the generated loader
hands the node the value its producer returned. (Inside a *bundle*, scalar parts
keep a `{"value": ...}` wrapper, because `bundle.json` records each part's kind
and the bundle loader unwraps by it.)

The toggle is forced **off**, and no dataset is saved, for:

- **Visualization sinks** (`curio.builtin/vis-vega`, `curio.builtin/vis-simple`), which pass their input straight through.
- **Dataset-palette nodes**, the loader nodes created by dragging a dataset in, which would otherwise re-save their own input.

Outputs appear in the catalog *before* the project is saved: the frontend passes the just-produced outputs to the catalog API as "live outputs", so the drawer's **Computed** tab and the palette show them immediately. Re-running a node rewrites the same dataset in place.

> [!IMPORTANT]
> **A dataflow must be saved before its node outputs can be persisted.** The dataset id is namespaced by dataflow id, so an unsaved dataflow has nothing to namespace with. Running a node in an unsaved dataflow shows the output as a live catalog row but writes nothing to disk; it is persisted on the next save. This guard exists so Curio never mints a legacy un-namespaced dataset that would duplicate the real one moments later.

### Lineage

Each computed dataset's manifest records where it came from: `producerNodeId`, `producerNodeType`, `producerDataflowId`, `producerDataflowName`, and `upstreamInputs` (the nodes and datasets feeding the producer). This is what keeps an account-level dataset connected to its workflow even after you remove it from every dataflow.

The detail view's **Lineage** tab renders this as **Generated by** / **Inputs (N)** / **Consumed by (N)**, with per-reference status pills (`Active`, `Stale`, `Missing`, `Unresolved`). An input node is named from the open canvas when it is there and from the manifest's recorded type otherwise; a dataset input is labelled by its producing node (a computed id is a pair of uuids) with the full id on hover. `GET /api/datasets/<id>/usage` backs the *"Used in dataflows"* list, scanning every project you own.

Curio distinguishes *carriers* from *consumers*: the producing node and any Data Loading node merely carry the dataset, so the "N nodes consume" count reports the nodes genuinely downstream of them.

If a node's output filename changes between runs, the copy already in the dataflow is flagged `needsReinstall` in the catalog so you can refresh it.

### Bundles

> [!NOTE]
> **"Bundle" here means a multi-part dataset. It has nothing to do with the webpack/JS bundles discussed in [EXTENDING.md](EXTENDING.md) and [DEPLOYMENT.md](DEPLOYMENT.md).**

When a node returns multiple values (a Python tuple, say), the output has no single file to store, so Curio saves it as a dataset with `format: "bundle"`: one dataset folder holding one file per part.

```
computed.<dataflowId>.<nodeId>@1/
  manifest.json          # format: "bundle", dataFile: "data/bundle.json"
  data/bundle.json       # {version, parentArtifactId, parts: [...]}
  data/parts/00_dataframe.parquet, 01_json.json, ...
```

Scalar parts (numbers, strings, booleans) are stored as `{"value": ...}`. The generated loader reads `bundle.json`, rebuilds each part with the right reader, and returns a tuple, so a downstream node sees exactly the shape the producing node emitted.

Previewing a bundle gives you a **tab per part**; a part with no rows is labelled *"Scalar or metadata part"*. Bundles **cannot be exported** as a single file; the Export button is disabled with that explanation.

---

## 5. Importing, publishing, and sharing

### Supported formats

| Extension | Stored as |
|---|---|
| `.csv` | `csv` |
| `.geojson` | `geojson` |
| `.json` | `json` |
| `.parquet` | `parquet` |
| `.tif`, `.tiff` | `geotiff` |
| `.shp` | `shp` |
| `.pbf`, `.osm.pbf` | **converted** (see below) |

Anything else is rejected with *"Unsupported dataset format"*.

### OSM PBF imports

A `.pbf` extract is not stored verbatim. On import, Curio reads every non-empty layer (`points`, `lines`, `multilinestrings`, `multipolygons`, `other_relations`), reprojects to EPSG:4326 when the CRS is missing, and installs **each layer as its own GeoParquet dataset**, titled `<name> (<layer>)`. All layers from one import share a `groupId`, so the drawer and palette can fold them into a single collapsible **OSM PBF** entry that installs or uninstalls all layers together. Each import mints a fresh group, so importing the same extract twice gives you two independent groups.

This requires the geospatial extras (`geopandas`, `pyogrio`) and a GDAL build with the OSM driver; Curio reports both as readable errors if they are missing.

### Publish, unpublish, delete

**Publish** copies the dataset folder into the shared catalog root. For a bundle, the whole `data/` tree is copied, not just the index.

**Unpublish** removes the shared-catalog listing only. Copies already added to dataflows keep working, and the confirmation says so explicitly.

**Delete** is the account-level removal: it deletes the stored dataset and strips its references from every one of your dataflows. Only computed, non-hub datasets expose it.

Who may unpublish or delete is decided by the manifest's `publisher` field: you can only remove datasets you published. Attempting otherwise returns `403` with *"You can only unpublish or delete datasets you published."* The three datasets shipped with Curio have `publisher: "Data Catalog"`, so ordinary users cannot remove them.

---

## 6. Previews, schema, and export

The dataset detail view, either the `/catalog/data/<id>` page or the modal opened from a drawer card, has four tabs: **Overview**, **Schema**, **Table Preview**, and **Lineage**. Previews page six rows at a time and are capped server-side at 500 rows per request.

| Format | Preview |
|---|---|
| `csv`, `json`, `geojson`, `parquet` | Full tabular preview with inferred schema; GeoJSON also reports geometry type and CRS. |
| `bundle`, OSM group | Tabbed preview, one tab per part / layer. |
| `geotiff` | Not previewable. *"Raster preview is not available in the catalog yet. Use the map canvas."* |
| `shp` | Not previewable yet. |

When a manifest carries no `schema`, Curio infers field names, types, and nullability from the first page of the preview.

**Export** (the detail panel's **Export** button, `GET /api/datasets/<id>/download`) streams the dataset as a file. Parquet is a special case: because it is an internal storage format, Curio deserializes it and exports **GeoJSON** for geo data or **CSV** for plain tables, matching what you saw in the preview. Bundles and OSM groups cannot be exported.

---

## Operator notes

### Relocating the catalog root

The shared catalog defaults to `<repo_root>/datasets/`, resolved relative to the installed package. That is correct when Curio runs from a checkout, but on a `pip` install it resolves under `site-packages`, where it is read-only and publishing fails, and in Docker it is not persisted across restarts. Set **`CURIO_CATALOG_ROOT`** (or pass `--catalog-root`) to a writable, persistent path in those deployments.

The catalog root is **never created eagerly**. A missing root simply means nothing is published: catalog listings return empty, and unpublish/delete report `404` *"Dataset is not in the Data Catalog"* rather than failing.

### Environment variables

| Var | Default | Effect |
|---|---|---|
| `CURIO_CATALOG_ROOT` | `<repo_root>/datasets/` | Shared catalog read source and publish target. |
| `CURIO_LAUNCH_CWD` | process CWD | Anchors the per-user store at `.curio/users/<key>/datasets/`. |
| `CURIO_DEFAULT_SAVE_NODE_OUTPUT` | `False` | Default state of every node's save-output toggle. |

### The dataset index

Catalog listings are served from a database table (`dataset_index_entry`, created by alembic revision `d4e5f6a7b8c9`) that mirrors each user's store manifests. Upgrading an existing deployment picks it up through the normal migration run; nothing else is required.

It is a cache, so it needs no operational care: it is reconciled against disk on every listing, and any failure degrades to the old full-scan behaviour. If you ever suspect it has drifted, dropping every row is safe, because the next listing rebuilds it. It is also safe to leave alone; there is no cleanup job to schedule.

### There is no publish gate for datasets

The node catalog's `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH` switch (see [NODE-CATALOG.md](NODE-CATALOG.md#operator-notes)) applies to **node packages only**. Dataset publishing is authenticated but not gated by configuration; the only restriction is the publisher-ownership check described above. On a multi-tenant deployment where the catalog root is writable, any signed-in user can publish a dataset into the shared catalog.

### Legacy computed-dataset ids

Datasets created before ids were namespaced by dataflow live at `computed.<nodeId>@1`. Curio migrates them once per user on first access: the directory is renamed to the namespaced form, the manifest id and `producerDataflowId` are rewritten, and the project's reference is patched. Attribution needs either an explicit `dataflow.datasets` ref or exactly one matching node across your projects; anything ambiguous is left alone.

---

## See also

- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): the node package catalog, whose storage and publish model this mirrors.
- [`docs/USAGE.md`](USAGE.md): installation, launcher flags, and the env-var inventory.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#dataset-routes): the dataset HTTP API reference and backend module layout.
- [`utk_curio/backend/app/datasets/`](../utk_curio/backend/app/datasets/): the implementation, where [`domain/manifest.py`](../utk_curio/backend/app/datasets/domain/manifest.py) is the manifest contract.
