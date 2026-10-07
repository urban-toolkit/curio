# Node Catalog

The Node Catalog is where Curio's nodes live. Every node you can drop on the canvas, whether a built-in that ships with the app or an extra you install, comes from a **package**: a small, self-contained folder with a `manifest.json` describing the nodes inside it.

Curio has six catalogs: the Node Catalog holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Model Catalog](MODEL-CATALOG.md) the models they run, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, the [Discovery Catalog](DISCOVERY-CATALOG.md) the portals, storage, services and models you take datasets and models from, and the [Scenario Catalog](SCENARIO-CATALOG.md) the scenarios saved in your projects.

This guide is in six parts, plus operator notes:

- [1. What is the Node Catalog?](#1-what-is-the-node-catalog): packages, what ships, and the four storage layers.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the canvas drawer and the `/catalog/nodes` page, the action matrix, and walkthroughs.
- [3. Using a node in a dataflow](#3-using-a-node-in-a-dataflow): the palette.
- [4. Creating a package from a canvas node](#4-creating-a-package-from-a-canvas-node): **Save as package node** and the metadata editor.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): archives, publishing, and versions.
- [6. The manifest](#6-the-manifest): the schema, and where packages live on disk.
- [Operator notes](#operator-notes): the publish switch, and what an operator can repair.

---

## 1. What is the Node Catalog?

### Concept

Every node Curio knows about belongs to a **package**, identified by a reverse-domain id and a major version:

```
<packageId>@<major>     e.g.   curio.builtin@1
                               ai.utk.uhvi@1
```

A package is a folder with a `manifest.json` (the contract), an optional `sources/` directory (one starter file per node kind, and the Python modules those starters import), and a few small sibling files (`README.md`, `LICENSE`, `integrity.json`). The manifest declares the **kinds** the package provides, and each kind becomes a draggable node in the palette.

### What ships with Curio

| Package | What it provides |
|---|---|
| `curio.builtin@1` | The 16 default node kinds (Data Loading, Python/JS Computation, Vega-Lite, Autark, Raster Calculator, Edit Features, and so on). Installed for every user, **read-only** (you can save edits as a new package but cannot overwrite the originals), and cannot be uninstalled. |
| `ai.utk.uhvi@1`, `curio.weather@1` | Example packages you can install from the catalog drawer to see the package workflow end to end. Both are plain Python nodes. `curio.weather@1` is also installed for you when Curio starts with `--with-examples`; you can still uninstall it. |
| `curio.example-ui@1` | A minimal node with its **own interface** rather than a code editor: no API keys and no Python dependencies. The one to read and fork for custom-UI nodes; see [AUTHORING-NODES.md](AUTHORING-NODES.md). |
| `curio.streetvision@1` | One **Image Segmentation** code node: runs a Model Catalog model over a collection's images and reports each class's share of every image (DDRNet23-Slim ships with Curio; Hugging Face models are added from the Discovery Catalog). Read-only, depends only on `onnxruntime`, and installed with the example that declares it ([example 10](examples/10-street-vision-cv-analysis.md)). |
| `scout.raster-conversion@1` | SCOUT's building rasterizer, ported from [SCOUT](https://github.com/urban-toolkit/scout): one **Rasterize Buildings** code node turns a buildings layer into the height tiles SCOUT's Deep Umbra shadow model reads, and a mosaic of them an Autark map draws. Read-only, depends on `datashader`, `spatialpandas`, `dask` and `rasterio`, and installed when Curio starts with `--with-examples`. See its [README](../packages/scout.raster-conversion@1/README.md). |
| `scout.shadow@1` | SCOUT's shadow model, ported from [SCOUT](https://github.com/urban-toolkit/scout): one **Accumulated Shadow** code node runs Deep Umbra on the zoom-16 tiles of that height mosaic and returns the accumulated shadow in minutes, a raster on the same grid that an Autark map draws and a Raster Statistics node sums up over the ground. Its model is Deep Umbra in the [Model Catalog](MODEL-CATALOG.md), which a pip install downloads the first time the node runs. Read-only, depends on `onnxruntime` and `rasterio`, and installed when Curio starts with `--with-examples`. See its [README](../packages/scout.shadow@1/README.md). |
| `scout.routing@1` | SCOUT's weather-aware routing, ported from [SCOUT](https://github.com/urban-toolkit/scout): one **Weather Routing** code node finds routes between two points over a roads layer, weighing each road by the weather SCOUT's graph network predicts on it from the WRF forecast in the Data Catalog, and gives the routes for an Autark map and their duration, distance and rain and wind exposure for Compare Scenarios. Its graph network is SCOUT's weather GNN in the [Model Catalog](MODEL-CATALOG.md). Read-only, depends on `osmnx`, `networkx`, `netCDF4`, `scipy`, `scikit-learn` and `onnxruntime`, and installed when Curio starts with `--with-examples`. See its [README](../packages/scout.routing@1/README.md). |

You can install any number of other packages, your own or archives shared by others.

### Storage layers

Package state lives in four places. Knowing which one an action writes is the key to predicting what happens after **Add to project**, **Add to all projects**, or **Remove from project**:

| Layer | On disk | Written by |
|---|---|---|
| **Shared catalog**, what every user browses | `<repo_root>/packages/<packageId>@<major>/` | **Publish**, when the operator allows it (see [Operator notes](#operator-notes)). Read-only otherwise. |
| **Per-user package store**, your installed copies | `.curio/users/<user-key>/packages/<packageId>@<major>/` | Managed for you. Adding copies a package in; removing it from the last project that uses it deletes the copy. |
| **Per-user defaults**, what new projects start with | `.curio/users/<user-key>/default-packages.json` | **Add to all projects** adds an entry. Removing the package from the last project that uses it drops the entry. |
| **Per-project lockfile**, what one project needs | `dataflow.packages` in the project's `spec.trill.json` | **Add to project** and **Remove from project** in the drawer. **Add to all projects** also patches every existing project. |

The palette reads the open project's lockfile, so two projects open in different tabs can show different palettes even though they share one package store.

---

## 2. Surfaces and workflows

There are two places you manage packages:

- **The drawer**, inside the canvas, works on the open project only. Open it from the **Node Catalog** button in the top bar, or from the **Node Catalog** dropdown in the left Tools panel and **Browse Node Catalog +**. Its two tabs are **Browse all** and **In project**.
- **The `/catalog/nodes` page**, reached from `/projects` and the **Node Catalog** tab, works on your whole account: a package added here goes into every project you have and every new one. It has status and category filters, a details drawer, and no remove button. The **Data Catalog**, **Agent Catalog**, **Discovery Catalog** and **Model Catalog** tabs beside it are the other four catalogs.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **Add to project** | Drawer | This project's lockfile, plus your package store if the package is not there yet | The package's nodes appear in this project's palette only. |
| **Add to all projects** | `/catalog/nodes` | Your defaults and every project's lockfile, plus your package store | The package appears in every project's palette, and new projects start with it. |
| **Update** (drawer), **Update all projects** (`/catalog/nodes`) | Shown when the shared catalog has a higher version than your copy | Your store copy, replaced by the catalog's version | Every project that uses the package gets the new version. A package with its own interface runs the new one after you reload the page. |
| **Remove from project** | Drawer | This project's lockfile; also your store copy and defaults entry, when no other project uses the package | The package leaves this project's palette. |
| **New node from a Python function** | Drawer | A new package, or one of yours, and this project's lockfile | A node that calls the function appears in this project's palette ([part 4](#new-node-from-a-python-function)). |
| **Publish** | The Tools panel's **Node Catalog** dropdown, or the `/catalog/nodes` details drawer | The shared catalog | Every user on this install can browse the package. The button is hidden when the operator turns publishing off. |

### Workflows

**I want to add a package to one project.** Open the project, click **Node Catalog → Browse Node Catalog +** to open the drawer, find the package, and click **Add to project**. Its nodes appear in this project's palette only; your other projects are unaffected.

**I want a package in all my projects, present and future.** On `/catalog/nodes`, find the package and click **Add to all projects**. It appears in every existing project's palette at once, and every project you create from then on starts with it.

**I want to remove a package.** `/catalog/nodes` has no remove button. Open each project that has the package and use **Remove from project** in the drawer. When you remove it from the last one, Curio deletes your installed copy and drops the package from your defaults, so new projects stop getting it.

**I want other users on this install to be able to add a package I built.** Build it with **Save as package node** ([part 4](#4-creating-a-package-from-a-canvas-node)), then click **Publish** on it in the Tools panel's **Node Catalog** dropdown or in the `/catalog/nodes` details drawer.

---

## 3. Using a node in a dataflow

Once a package is in the open project, its nodes are in the palette: the built-in nodes sit in the left Tools panel, and nodes from other packages in its **Node Catalog** dropdown. Drag one onto the canvas.

A Python node that calls a key-gated API reads the key by name, never as a literal: `api_key = curio_secret("<name>")` returns the key saved under that name as a **Node code** key on the **API keys** tab of **API Settings** (see [USAGE.md](USAGE.md#keys-for-node-code)). Like `curio_data_path("<id>")`, the name travels with the dataflow, and the value reaches the sandbox for the run only.

---

## 4. Creating a package from a canvas node

The flow is **Save as package node**: build the node on the canvas, then save it into a new or existing package. **New node from a Python function** writes a node from a function in a package's module instead. Package metadata is edited per package from the **Node Catalog** dropdown.

### Save as package node

1. Drop a node onto the canvas, either a built-in or one from an installed package, and edit its code as usual.
2. Click the **cog** on the node header to open the **Node settings** modal. Change the label, ports, or editor mode if you want.
3. Click **Save as package node…**. A picker appears.
4. Choose **New package…** (a fresh package containing this kind) or an installed package as the target. Read-only packages, including `curio.builtin@1`, are not offered; the way to change a read-only package is to fork it into a new one.
5. After the save, the canvas node is rebound to the new package's kind.

Saving into a package you added from the catalog makes that copy your own. Curio keeps it as you saved it when the shared catalog's copy changes, and **Update** replaces it with the catalog's version when the catalog has a higher one. The same holds after you edit the package's metadata or import an archive over it.

> [!IMPORTANT]
> **Save as package node cannot produce a custom-UI node.** A new package it
> builds carries `manifest.json` and `sources/`, never a `scripts/` directory,
> so **forking a custom-UI package this way drops its interface**. Saving into
> an existing package keeps every file it already has.
>
> To author a node with its own React interface, work from a checkout and build
> the bundle: see [Authoring nodes](AUTHORING-NODES.md) and
> [EXTENDING.md §6](EXTENDING.md).

### New node from a Python function

A package that ships Python modules in its `sources/` folder ([Modules beside your template](AUTHORING-NODES.md#modules-beside-your-template)) can give you a node for any of their functions without writing its code:

1. Open the Node Catalog drawer and click **New node from a Python function** in its footer.
2. Pick the function. The list holds every public function of every module your installed packages ship, as `module.function(parameters)`. A function that takes `*args` or `**kwargs`, or is `async`, is listed but cannot be picked, and says why; so is a module that does not parse.
3. For each parameter, choose what it is given:
   - **A widget**: a tag in the node's **Widgets** tab ([Widgets](USAGE.md#widgets)). Curio suggests its type from the parameter's annotation or default: `bool` is a checkbox, `int` and `float` a number, `str` a text, `Literal["a", "b"]` a choice, a list of texts or numbers a list, `datetime` a date and time. **Edit widget** changes its type, label, default and options.
   - **A fixed value**, written as Python writes it: `2`, `'winter'`, `[1, 2]`.
   - **An input**: the node gets one input per parameter given one, in parameter order.
   - **Its default**, when the parameter has one: the call leaves it out.
4. Name the node, choose the destination package as for **Save as package node**, and click **Create node**.

The node joins this project's palette. Its code imports the function and returns its call, with the widgets and inputs as references:

```python
from scout_shadow.deep_umbra import season_factor

return season_factor(season=[!! season !!])
```

The function's parameters are read from the module's source; the module is not imported or run until the node runs. A node saved into another package than the function's names the function's package in `dependencies.packages`, which lets its code import that package's modules.

### Dependencies are detected from the source

`dependencies.python` and `dependencies.js` in the manifest are filled in from each kind's source file when you save. They are not entered by hand:

- Each top-level `import` or `from … import` in a `.py` source is collected, leaving out the standard library, Curio's own modules, and the modules the package and the packages in its `dependencies.packages` ship. The common cases where the import name differs from the install name are mapped (`cv2` → `opencv-python`, `sklearn` → `scikit-learn`, `PIL` → `pillow`, `yaml` → `pyyaml`, `bs4` → `beautifulsoup4`, `skimage` → `scikit-image`); anything else passes through unchanged.
- In `.js`, `.mjs` and `.cjs` sources, `import … from "X"`, dynamic `import("X")` and `require("X")` are collected. Relative paths are skipped, subpaths collapse to the package (`lodash/fp` → `lodash`), and scoped packages keep their scope (`@scope/pkg`).
- Detected names are written with `*` as the version range. The UI does not offer version pins.
- Saving into an existing package keeps every dependency it already declares, with its range, and adds newly detected names.
- Imported archives and catalog installs are not re-scanned: their dependencies are what the package author declared.

### Editing package metadata

Open the **Node Catalog** dropdown in the Tools panel, expand an installed package, and click the **pencil** next to the export icon in its header. A modal lets you edit:

- Name, description, publisher, license
- Permissions (comma-separated, e.g. `filesystem.read, network.fetch`)
- Curio runtime range (advisory)
- README contents

Read-only packages have no pencil. The detected `python` and `js` dependencies are shown below the editable fields, read-only, so you can check what the scanner found.

---

## 5. Importing, publishing, and sharing

A package is portable: you can export it, send it, and the recipient can import it.

### Exporting

Open the **Node Catalog** dropdown in the Tools panel and click the **download** icon on your package's row (**Export package**). It saves the package as `<packageId>@<major>.curio.zip`.

The archive holds `manifest.json`, `sources/`, `README.md`, `LICENSE`, and `scripts/`, so a custom-UI package's compiled `behaviors.js` travels with it and the recipient needs no build step. `integrity.json` is left out; the recipient's install regenerates it.

Files sit at the **root of the zip**, not inside a `<packageId>@<major>/` folder, which matters if you zip a package by hand. The installer ignores the archive's own name and takes the destination from the manifest.

### Importing

1. Open the catalog drawer (Tools panel → **Node Catalog** → **Browse Node Catalog +**).
2. Click **Import package** in the footer.
3. Pick the archive.

The `/catalog/nodes` page has the same **Import package** button in its header.

The manifest is validated before the package is installed. An archive whose `<packageId>@<major>` you already have is refused, and so is one that ships a Python module another installed package ships ([Modules beside your template](AUTHORING-NODES.md#modules-beside-your-template)).

### Publishing

**Publish** adds a package from your store to the shared catalog at `<repo_root>/packages/`, where every user on this install can browse and add it. **Unpublish** removes it from there. Both buttons are hidden when the operator turns publishing off (see [Operator notes](#operator-notes)).

### Versioning

- **Versioning.** Bump the `version` string for patch and minor releases; bump `compatibility.major` (and the folder name's suffix) for breaking changes. Two majors of one package install side by side.
- **Node types.** A node type without a version, `<packageId>/<kindId>`, resolves to whatever major is installed; `<packageId>/<kindId>@<major>` names one.

### Read-only packages

A manifest with `"readOnly": true` at the top level marks its package read-only. Nothing can be saved into it: **Save as package node** does not offer it as a target, and **Node settings** shows a **Read-only** badge on its nodes, with **Save as package node…** as the way forward.

`curio.builtin@1` is read-only, and the same flag suits org-curated packages you distribute without letting users overwrite their kinds. A fork of a read-only package starts without the flag.

### Caveats

- There is no hosted package registry. Sharing is by archive (email, Slack, S3, whatever fits), or through a deployment's shared catalog at `<repo_root>/packages/`.
- To check your saved projects, run `python scripts/validate_trill.py --all --resolve`. It reports every dataflow that does not match [`docs/schemas/trill.v1.json`](schemas/trill.v1.json), and `--resolve` also flags node types with no template under `<repo_root>/packages/`. See [TRILL-SPEC.md](TRILL-SPEC.md).

---

## 6. The manifest

[`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json) (JSON Schema Draft 2020-12) is the reference for what a package can declare. The catalog packages in `<repo_root>/packages/` are the canonical examples, starting with [`packages/curio.builtin@1/manifest.json`](../packages/curio.builtin@1/manifest.json). To write a package by hand, follow [Authoring nodes](AUTHORING-NODES.md).

A package you save or import lands in your package store:

```
<CURIO_LAUNCH_CWD>/.curio/users/<user-key>/packages/<packageId>@<major>/
  manifest.json
  sources/
    <template-id>.{py,js,...}
  integrity.json                 ← SHA-256 of every shipped file
```

---

## Operator notes

| Variable | Flag | Effect |
|---|---|---|
| `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH` | `--allow-publish` (default), `--no-allow-publish` | Allows or forbids **Publish** and **Unpublish**. When forbidden, both are refused and their buttons are hidden. |
| `CURIO_PACKAGES_ROOT` | none | Reads and publishes the shared catalog in this directory instead of `<repo_root>/packages/`. |

**`curio.py start` sets the publish variable on every start**, so `--no-allow-publish` is the way to turn publishing off. A `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH=0` in `.env` has no effect when you start through `curio.py`. See [USAGE.md](USAGE.md) for the launcher reference.

**On a multi-user install, start with `--no-allow-publish`.** Any signed-in user can publish, and publishing can replace a package already in the shared catalog. Only a package's publisher can remove it. Treat `<repo_root>/packages/` as operator-managed. On a single-user local install this does not arise.

**Who may install a package.** A local run installs freely. On a hosted deployment installing can be restricted, and the UI says so where it is: see [DEPLOYMENT.md § Security checklist](DEPLOYMENT.md#security-checklist). Installing a package runs its setup code, so install packages you trust, as with any other dependency.

**Detaching a package from a user's defaults.** `DELETE /api/packages/defaults/<dirName>` removes one entry from that user's `default-packages.json` and touches nothing else: no lockfile changes and nothing is uninstalled. It has no UI, and is meant for scripted installs and repair.

---

### Where the code lives

Since memo dev/143 the catalog is layered like the Data Catalog. The backend is `utk_curio/backend/app/packages/{domain,schemas,repositories,infrastructure,application,builder,routes}` behind the one `service.py` facade, and the agents feature is layered the same way, `utk_curio/backend/app/agents/{domain,repositories,infrastructure,application,routes}` behind its `service.py`, with `src/services/agents/` + `src/providers/agents/` on the frontend (memo dev/142) (`builder/` is the Package Builder pipeline beside the layers; dependency rule `domain ← schemas ← repositories ← infrastructure ← application ← routes`, enforced by `tests/test_packages/test_layering.py`). The frontend is `src/services/packages/`, holding the transport (`packagesApi`, `packagesBlobTransport`, `packageBackendApi`), `usePackageCatalog` (the one hook both the canvas drawer and the `/catalog/nodes` page render, scoped per project or to the account defaults) and the pure logic and types they share (import it from its barrel, `services/packages`), and `src/providers/packages/` (the drawer provider, the palette context, and the two hooks that also refresh the node-kind registry: `usePackageArchiveImport`, the one sideload pathway, and `useEnsureWorkflowDeps`). The surfaces (`components/packages/`, `pages/catalog/`, the palette dropdown under `components/menus/nodes/`) only render: `tests/packages/servicesBarrel.test.ts` refuses transport there and refuses any runtime import of `registry/` inside the layer (see [ARCHITECTURE.md](ARCHITECTURE.md)).

## See also

- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): datasets, installed and published with the same model.
- [`docs/AGENT-CATALOG.md`](AGENT-CATALOG.md): the agents you attach to nodes.
- [`docs/DISCOVERY-CATALOG.md`](DISCOVERY-CATALOG.md): the data portals you download datasets from.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#node-packages-and-manifests): how packages load, and how to add a built-in behavior, icon, or grammar adapter.
- [`docs/USAGE.md`](USAGE.md): installing and running Curio, including the [Vega-Lite node](USAGE.md#vega-lite-node).
- [`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json): the manifest JSON Schema.
- [`docs/schemas/trill.v1.json`](schemas/trill.v1.json): the dataflow JSON Schema. A node's `type` points into a manifest's `templates[].id`.
