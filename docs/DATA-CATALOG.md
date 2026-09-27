# Data Catalog

The Data Catalog is where Curio's **datasets** live: files shipped with your deployment, files you import from your machine, and the outputs your own dataflows compute.

Curio has four catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the Data Catalog the datasets they read, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, and the [Data Lake Catalog](DATA-LAKE-CATALOG.md) the open data portals you download datasets from.

This guide is in seven parts, plus operator notes:

- [1. What is the Data Catalog?](#1-what-is-the-data-catalog): datasets, what ships, origins, ids, and the four storage layers.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the three places you manage datasets, the action matrix, and walkthroughs.
- [3. Using a dataset in a dataflow](#3-using-a-dataset-in-a-dataflow): drag and drop, generated loader code, and linkage badges.
- [4. Computed datasets (node outputs)](#4-computed-datasets-node-outputs): the save-output toggle, lineage, and bundles.
- [5. Previews, schema, and export](#5-previews-schema-and-export): what each format supports.
- [6. Importing, publishing, and sharing](#6-importing-publishing-and-sharing): supported formats, OSM PBF and GeoPackage, publish, unpublish, and delete.
- [7. The manifest](#7-the-manifest): the fields a dataset declares.
- [Operator notes](#operator-notes): relocating the catalog, and what needs no care.

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

### What ships with Curio

Twelve datasets ship in the shared catalog at `<repo_root>/datasets/`, grouped by the owner of the data: six under `data.urbanlab.*` (the Chicago boundary and community areas, an ACS profile, and the three Milan heat-exposure inputs), five under `data.cityofchicago.*` (green roofs, neighborhoods, 2010 energy usage, and the speed-camera and red-light violation tables), and one under `data.projectsidewalk.*` (Chicago accessibility labels).

### Origins

Every dataset carries an `origin`, which the browse filters and provenance chips key on:

| Origin | Meaning |
|---|---|
| `hub` | Published into the shared catalog and browsable by every user on this install. |
| `imported` | A file you uploaded from your machine, or downloaded from the [Data Lake Catalog](DATA-LAKE-CATALOG.md). |
| `computed` | The output of a node in one of your dataflows, saved when it ran. |

The UI groups `hub` and `imported` under one **Imported** label, leaving **Computed** as the distinction to filter on.

### Dataset ids

Ids are 2 to 6 dot-separated lowercase segments (`[a-z][a-z0-9-]*`, at most 63 characters each), with a major version between `0` and `9999`. Curio mints the id for everything except the shipped datasets:

| Kind | Id form | Note |
|---|---|---|
| Shipped | `data.urbanlab.chicago-boundary` | Written by hand in the manifest. |
| Imported | `imported.x<uuid12>` | New for every import: uploading the same bytes twice creates **two** datasets. |
| Computed | `computed.<dataflowId>.<nodeId>` | One per node per dataflow, so the same node id in two dataflows never collides. |
| OSM PBF group | `osm.x<uuid8>` | The parent of one import's layers. |

### Storage layers

Dataset state lives in four places. Knowing which one an action writes is the key to predicting what happens after **Add to project**, **Add to all projects**, **Remove from project**, or **Delete**:

| Layer | On disk | Written by |
|---|---|---|
| **Shared catalog**, what every user browses | `<repo_root>/datasets/<datasetId>@<major>/`, or `$CURIO_CATALOG_ROOT` when set | **Publish** adds a dataset; **Unpublish** removes it. Read-only otherwise. |
| **Per-user dataset store**, the bytes you can read | `<CURIO_LAUNCH_CWD>/.curio/users/<user-key>/datasets/<datasetId>@<major>/` | **Import**, a Data Lake download, **Add to project** (which copies a shared dataset in), and saved node outputs. **Delete** removes a dataset permanently, and so does removing your own upload from the last dataflow that uses it. |
| **Per-user defaults**, what new projects start with | `.curio/users/<user-key>/default-datasets.json` | **Add to all projects** adds an entry; **Remove from all projects** drops it. |
| **Per-dataflow refs**, what one dataflow declares it needs | `dataflow.datasets` in the project's `spec.trill.json` | **Add to project** and **Remove from project** in the drawer. **Add to all projects** and **Remove from all projects** change every project. The shipped examples carry theirs already. |

> [!NOTE]
> The example projects declare the datasets they need, and Curio copies those into your store the first time you open one.

**Computed datasets belong to your account, not to a project.** Running a node saves its output into your store and writes *no* `dataflow.datasets` ref. It appears in the catalog at once, but it is only "in" a dataflow once you add it there.

---

## 2. Surfaces and workflows

There are three places you work with datasets, and they are **not** interchangeable:

- **The `/catalog/data` page** is the library view, for your whole account. Reach it from `/projects` and the **Data Catalog** tab. You can browse, filter by status, format and origin, preview, publish, open a dataset's details, and add a dataset to all your projects. You **cannot add a dataset to just one dataflow from here**: that is the drawer's job.
- **The Data Catalog drawer**, inside the canvas, is the working surface. Open it from the top menu **Data ⏷ → Data Catalog**, or from the left Tools panel's **Data Catalog** dropdown and **Browse Data Catalog +**. Everything scoped to the open dataflow happens here: adding, removing, importing, and deleting. Its tabs are **Browse all** (the default), **In project**, and **Computed**.
- **The Data palette**, the **Data Catalog** dropdown in the left Tools panel, holds the datasets already added to this dataflow, ready to drag onto the canvas. It sits below the built-in nodes and the **Node Catalog** dropdown.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **Add to project** | Drawer | This dataflow's refs, plus your store if the dataset came from the shared catalog | The dataset appears in this dataflow's **Data Catalog** palette, ready to drag. |
| **Add to all projects** | `/catalog/data`, in the right-hand drawer or the right-click menu | Your defaults and every project's refs, plus your store if needed | The dataset is in every dataflow's palette, and new projects start with it. |
| **Remove from all projects** | `/catalog/data`, in the right-hand drawer or the right-click menu | Your defaults and every project's refs | It leaves every dataflow. The dataset stays in your account. |
| **Remove from project** | Drawer | This dataflow's refs; your own upload is deleted too when no other dataflow uses it | It leaves this dataflow's palette. The confirmation says when an upload will be deleted, and its button then reads **Remove and delete**. |
| **Import dataset** | Drawer footer | Your store | The file is registered in your catalog. It is **not** added to the open dataflow; add it afterwards. |
| **Publish** | `/catalog/data`, in the right-hand drawer | The shared catalog | Every user on this install can browse the dataset. |
| **Unpublish** | `/catalog/data`, in the right-hand drawer | The shared catalog | The listing goes away. Copies already added to dataflows are untouched. |
| **Delete** | Drawer, on computed datasets and your own imports | Your store, and refs in every project | The dataset is **permanently** removed from your account, and every dataflow's reference to it is stripped. |

### Workflows

**I want to use a catalog dataset in my dataflow.** Open the dataflow, then **Data ⏷ → Data Catalog**. Find the dataset and click **Add to project**. It now appears in the left Tools panel's **Data Catalog** dropdown. Drag it onto the canvas to get a Data Loading node wired to it ([part 3](#3-using-a-dataset-in-a-dataflow)).

**I want to use a file from my computer.** Open the drawer and click **Import dataset** in the footer. Pick the file (`.csv`, `.geojson`, `.json`, `.parquet`, `.tif`, `.tiff`, `.shp`, `.pbf`, `.gpkg`). Import only registers the dataset in your account: click **Add to project** on it to add it to the open dataflow.

**I want a dataset from an open data portal.** Download it from the [Data Lake Catalog](DATA-LAKE-CATALOG.md). It lands here as an imported dataset.

**I want a dataset in all my projects, present and future.** On `/catalog/data`, click the dataset's card and then **Add to all projects** in the drawer. It is added to every dataflow you have, and every project you create from then on starts with it. **Remove from all projects** undoes it and keeps the dataset.

**I want to reuse a node's output somewhere else.** Turn on the node's save-output toggle (the database icon next to its play button) and run it: the output is saved as a computed dataset. Open the drawer's **Computed** tab and click **Add to project** on it, in this dataflow or another one.

**I want to remove a dataset from one dataflow but keep it.** Use **Remove from project** in the drawer. Only the dataflow's ref goes, with one exception: your own upload is deleted when no other dataflow uses it, and the confirmation says so before anything is deleted.

**I want a dataset gone for good.** Use **Delete** in the drawer. It removes your stored copy and strips the references from every dataflow that used it, and its confirmation says how many nodes are affected.

**I want other users on this deployment to see my dataset.** On `/catalog/data`, click the dataset's card, then **Publish** in the drawer. It is copied into the shared catalog, and only you, as its publisher, can unpublish it later. Publishing is per deployment: there is no hosted dataset registry.

---

## 3. Using a dataset in a dataflow

Adding a dataset to a dataflow creates nothing on the canvas. You use it by **dragging** it from the **Data Catalog** palette, or from a card in the drawer:

- **Drop on empty canvas**: Curio creates a **Data Loading** node filled in with loader code for that dataset, and says *"Created a Data Loading node for `<title>`."*
- **Drop onto an existing node**: the loader code is merged into that node's code under a `# Curio dataset loader: <title>` marker, and Curio says *"Applied `<title>` to this node."* If the node's code ends in a `return`, the loader goes before it and the return is rewritten.

The generated Python depends on the format:

| Format | Generated code |
|---|---|
| `csv` | `pd.read_csv(dataset_path)` → `df` |
| `geojson`, `shp` | `gpd.read_file(dataset_path)` → `gdf` |
| `parquet` | `gpd.read_parquet`, falling back to `pd.read_parquet` → `df` |
| `json` | `json.loads(...)` → `data` |
| `geotiff` | `rasterio.open(dataset_path)` → `src` |
| `bundle` | Rebuilds every part and returns a tuple → `bundle` |
| OSM group | A `layers` dict of per-layer GeoParquet reads |

The generated code names the dataset with `curio_dataset_path("<datasetId>")` instead of a file path, so it keeps working when the dataflow is shared or moved.

**Clicking** a palette row, rather than dragging it, highlights every node on the canvas that uses that dataset. If none does, a message says so.

A node tied to a dataset shows a pill on its title bar: **DATASET** on a node created by dropping a dataset on empty canvas, **OUTPUT** when it produced one. Palette rows and drawer cards carry a **connection badge** such as `1↑ 2↓`: one upstream producer and two downstream consumers.

---

## 4. Computed datasets (node outputs)

### The save-output toggle

Every runnable node has a small database-icon toggle to the right of its play button. It is **off by default**, so saving is chosen per node. When it is on, running the node saves its output into your store as `computed.<dataflowId>.<nodeId>@1`.

A `GeoDataFrame` output is stored as **GeoParquet** and reloads as a `GeoDataFrame`. Its CRS survives, and so does *every* geometry column, not only the active one: a frame with both a `geometry` and a `centroid` column comes back with both still typed as geometry. So a node's map output is a reusable input. (A `GeoDataFrame` with no active geometry column is stored as a plain table; GeoParquet cannot represent one.)

In the catalog's preview of a saved output, a geometry column is shown as WKT (`POINT (0.67 0.33)`).

Every output type a node can declare is saved, not only tables:

| Node output | Saved as |
|---|---|
| DataFrame, GeoDataFrame | `parquet` |
| Raster | `geotiff` |
| A plain Python value: dict, list, string, number, boolean, or `None` | `json` |
| A tuple | `bundle`, one part per item (see [Bundles](#bundles)) |
| A list or dict *containing* DataFrames | `bundle`, one part per element; a dict keeps its keys as part labels |

A `json` output is stored as plain, uncompressed JSON, readable with `json.load` and exported as is.

Nothing is saved for:

- **Visualization sinks** (`curio.builtin/vis-vega`, `curio.builtin/vis-simple`), which pass their input straight through.
- **Dataset-palette nodes**, the loader nodes created by dragging a dataset in.

A node's output appears in the drawer's **Computed** tab as soon as the node runs. Running it again rewrites the same dataset.

### Lineage

Each computed dataset records where it came from: the producing node and its type, the dataflow and its name, and the nodes and datasets feeding the producer. That keeps an account-level dataset connected to its workflow even after you remove it from every dataflow.

The details' **Lineage** tab shows this as **Generated by**, **Inputs (N)**, and **Consumed by (N)**, with a status pill (**Stale**, **Missing**, **Unresolved**) on any reference that needs attention. An input node is named from the open canvas when it is there, and from its recorded type otherwise; a dataset input is labelled by its producing node, with the full id on hover. **Used in projects** lists every project of yours that uses the dataset.

Curio tells *carriers* from *consumers*: the producing node and any Data Loading node only carry the dataset, so the count of consuming nodes covers the nodes genuinely downstream of them.

### Bundles

> [!NOTE]
> **"Bundle" here means a multi-part dataset. It has nothing to do with the webpack/JS bundles discussed in [EXTENDING.md](EXTENDING.md) and [DEPLOYMENT.md](DEPLOYMENT.md).**

When a node returns several values (a Python tuple, say), there is no single file to store, so Curio saves a dataset with `format: "bundle"`: one dataset folder holding one file per part.

```
computed.<dataflowId>.<nodeId>@1/
  manifest.json          # format: "bundle", dataFile: "data/bundle.json"
  data/bundle.json       # {version, parentArtifactId, parts: [...]}
  data/parts/00_dataframe.parquet, 01_json.json, ...
```

Scalar parts (numbers, strings, booleans) are stored as `{"value": ...}`. The generated loader reads `bundle.json`, rebuilds each part, and returns a tuple, so a downstream node sees exactly the shape the producing node returned.

Previewing a bundle gives you a **tab per part**; a part with no rows is labelled *"Scalar or metadata part"*. A bundle **cannot be exported** as a single file, and its Export button is disabled.

---

## 5. Previews, schema, and export

A dataset's details have four tabs: **Overview**, **Schema**, **Table Preview**, and **Lineage**. The preview pages six rows at a time.

| Format | Preview |
|---|---|
| `csv`, `json`, `geojson`, `parquet` | Full table preview with inferred schema; GeoJSON also reports geometry type and CRS. |
| `bundle`, OSM group | One tab per part or layer. |
| `geotiff` | Not previewable: *"Raster preview is not available in the catalog yet. Use the map canvas."* |
| `shp` | Not previewable. |

**Export**, in the details, downloads the dataset as a file. A Parquet dataset is exported as **GeoJSON** for geo data or **CSV** for a plain table, matching what the preview showed. Bundles and OSM groups cannot be exported.

---

## 6. Importing, publishing, and sharing

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
| `.gpkg` | **converted** (see below) |

Anything else is rejected with *"Unsupported dataset format"*.

### Text imports are stored as UTF-8

`csv`, `json` and `geojson` uploads are stored as UTF-8, and the encoding they came from is recorded in the manifest as `sourceEncoding`. Curio tries UTF-8 first and only guesses the encoding when that fails.

### Multi-layer imports: OSM PBF and GeoPackage

A `.pbf` extract is not stored as is. On import, Curio reads every non-empty layer (`points`, `lines`, `multilinestrings`, `multipolygons`, `other_relations`), labels a layer with no CRS as EPSG:4326, and stores **each layer as its own GeoParquet dataset**, titled `<name> (<layer>)`. The layers of one import share a group, which the drawer and palette fold into one **OSM PBF** entry that adds or removes all its layers together. Importing the same extract twice gives you two independent groups.

This needs the geospatial extras (`geopandas`, `pyogrio`) and a GDAL build with the OSM driver; Curio says so if either is missing.

A `.gpkg` is handled the same way, since a GeoPackage can hold any number of layers: each layer becomes its own parquet dataset, folded into one **GeoPackage** entry in the drawer. Two things differ from the PBF path:

- **CRS.** A GeoPackage layer that is not in EPSG:4326 is **reprojected**. Only a layer with no CRS at all is labelled 4326.
- **Attribute-only tables.** A table with no geometry is kept, as plain parquet.

A GeoPackage holding exactly one layer is imported as an ordinary parquet dataset with no group. GeoPackage import needs the same geospatial extras, plus GDAL's GPKG driver.

### Publish, unpublish, delete

For a bundle, **Publish** copies the whole `data/` tree, not just the index.

**Unpublish** removes the shared listing only. Copies already added to dataflows keep working, and the confirmation says so.

**Delete** removes a dataset from your account: it deletes the stored copy and strips its references from every one of your dataflows. It is offered on computed datasets and on your own imports, never on a dataset from the shared catalog.

Only the dataset's publisher may unpublish or delete it.

---

## 7. The manifest

There is no JSON Schema for dataset manifests, so this table is the reference. The shipped datasets in `<repo_root>/datasets/` are the canonical examples.

| Field | Required | What it declares |
|---|---|---|
| `id` | Yes | Dataset id (see [Dataset ids](#dataset-ids)). |
| `name` | Yes | Display title. |
| `version` | Yes | Free-form version string (e.g. `"1.0.0"`), independent of `compatibility.major`. |
| `format` | Yes | One of `csv`, `geojson`, `json`, `parquet`, `geotiff`, `shp`, `bundle`. (`osm` and `gpkg` are group cards, never written to a manifest.) |
| `dataFile` | Yes | Path to the data within the dataset folder, e.g. `data/chicago.geojson`. |
| `sourceEncoding` | | For text formats, the encoding the upload was decoded from before it was stored as UTF-8. `"utf-8"` when nothing had to change. |
| `compatibility.major` | | Integer major version; defaults to `1`. Together with `id` it forms the folder name. |
| `description` | | Defaults to `""`. |
| `publisher` | | Defaults to `"Data Catalog"`. It decides who may unpublish or delete (see [part 6](#publish-unpublish-delete)). |
| `license` | | Free text, e.g. `"Open Data"`. |
| `tags` | | Array of strings; feeds search and the Tags panel. |
| `sourceLabel` | | Short provenance label; falls back to `publisher`. |
| `createdAt` / `updatedAt` | | ISO timestamps for the Curio *record*. |
| `sourceUpdatedAt` | | Last-modified date of the *original file* at import time. |
| `lakeSource` | | Where a Data Lake download came from: the portal (`lakeId`, `lakeName`), `resourceId`, `resourceUrl`, `finalUrl`, `fetchedAt`, and the bytes' `contentSha256`. See [DATA-LAKE-CATALOG.md](DATA-LAKE-CATALOG.md). |
| `featureCount` / `rowCount` | | Counts for geo and tabular data. |
| `schema` | | Object describing the fields; inferred from a preview when absent. |
| `groupId` / `layerName` | | Multi-layer imports: every layer of one import shares a `groupId`. |
| `producerNodeId`, `producerNodeType`, `producerDataflowId`, `producerDataflowName`, `upstreamInputs` | | Lineage for computed datasets (see [Lineage](#lineage)). |

---

## Operator notes

| Variable | Flag | Effect |
|---|---|---|
| `CURIO_CATALOG_ROOT` | `--catalog-root` | The shared catalog's location. Defaults to `<repo_root>/datasets/`. |
| `CURIO_LAUNCH_CWD` | none | Where per-user stores live (`.curio/users/<key>/datasets/` under it). Defaults to the process's working directory. |
| `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH` | `--allow-publish` (default), `--no-allow-publish` | Shows or hides **Publish** and **Unpublish** on `/catalog/data`, as it does for node packages. |

**Relocating the catalog.** The default root resolves relative to the installed package. That suits a checkout, but on a `pip` install it lands inside `site-packages`, where it is read-only and publishing fails. Set `CURIO_CATALOG_ROOT` (or `--catalog-root`) to a writable, persistent path there.

**The publish switch only hides the buttons.** The dataset API does not check `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`, so any signed-in user other than a guest can still publish a dataset through it. Only a dataset's publisher can unpublish or delete it.

**The dataset index needs no care.** Listings are served from a database table that mirrors each user's store, checked against disk on every listing. Dropping every row is safe, since the next listing rebuilds it, and there is no cleanup job to schedule.

---

## See also

- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): the node package catalog, whose storage and publish model this one mirrors.
- [`docs/AGENT-CATALOG.md`](AGENT-CATALOG.md): the agents, including the Dataset Finder.
- [`docs/DATA-LAKE-CATALOG.md`](DATA-LAKE-CATALOG.md): the data portals you download datasets from.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#dataset-routes): the dataset routes and backend layout.
- [`docs/USAGE.md`](USAGE.md): installation, launcher flags, and the environment variables.
- [`utk_curio/backend/app/datasets/`](../utk_curio/backend/app/datasets/): the implementation, where [`domain/manifest.py`](../utk_curio/backend/app/datasets/domain/manifest.py) is the manifest contract.
