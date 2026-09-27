# Node Catalog

The Node Catalog is where Curio's nodes live. Every node you can drop on the canvas, whether a built-in that ships with the app or an extra you install, comes from a **package**: a small, self-contained folder with a `manifest.json` describing the nodes inside it.

Curio has four catalogs: the Node Catalog holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, and the [Data Lake Catalog](DATA-LAKE-CATALOG.md) the open data portals you download datasets from.

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
                               ai.urbanlab.uhvi@1
```

A package is a folder with a `manifest.json` (the contract), an optional `sources/` directory (one starter file per node kind), and a few small sibling files (`README.md`, `LICENSE`, `integrity.json`). The manifest declares the **kinds** the package provides, and each kind becomes a draggable node in the palette.

### What ships with Curio

| Package | What it provides |
|---|---|
| `curio.builtin@1` | The 12 default node kinds (Data Loading, Python/JS Computation, Vega-Lite, Autark, and so on). Installed for every user, **read-only** (you can save edits as a new package but cannot overwrite the originals), and cannot be uninstalled. |
| `ai.urbanlab.uhvi@1`, `curio.weather@1` | Example packages you can install from the catalog drawer to see the package workflow end to end. Both are plain Python nodes. `curio.weather@1` is also installed for you when Curio starts with `--with-examples`; you can still uninstall it. |
| `curio.example-ui@1` | A minimal node with its **own interface** rather than a code editor: no API keys and no Python dependencies. The one to read and fork for custom-UI nodes; see [AUTHORING-NODES.md](AUTHORING-NODES.md). |
| `curio.streetvision@1` | A substantial custom-UI package (Street View fetch plus HuggingFace inference). Not installed by default, read-only, and needs a Google Maps API key plus torch and transformers. Read it for the advanced patterns, not as a starting point. |

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

- **The drawer**, inside the canvas, works on the open project only. Open it from the top menu **Data ⏷ → Node Catalog**, or from the **Node Catalog** dropdown in the left Tools panel and **Browse Node Catalog +**. Its two tabs are **Browse all** and **In project**.
- **The `/catalog/nodes` page**, reached from `/projects` and the **Node Catalog** tab, works on your whole account: a package added here goes into every project you have and every new one. It has status and category filters, a details drawer, and no remove button. The **Data Catalog**, **Agent Catalog** and **Data Lake Catalog** tabs beside it are the other three catalogs.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **Add to project** | Drawer | This project's lockfile, plus your package store if the package is not there yet | The package's nodes appear in this project's palette only. |
| **Add to all projects** | `/catalog/nodes` | Your defaults and every project's lockfile, plus your package store | The package appears in every project's palette, and new projects start with it. |
| **Remove from project** | Drawer | This project's lockfile; also your store copy and defaults entry, when no other project uses the package | The package leaves this project's palette. |
| **Publish** | The Tools panel's **Node Catalog** dropdown, or the `/catalog/nodes` details drawer | The shared catalog | Every user on this install can browse the package. The button is hidden when the operator turns publishing off. |

### Workflows

**I want to add a package to one project.** Open the project, click **Node Catalog → Browse Node Catalog +** to open the drawer, find the package, and click **Add to project**. Its nodes appear in this project's palette only; your other projects are unaffected.

**I want a package in all my projects, present and future.** On `/catalog/nodes`, find the package and click **Add to all projects**. It appears in every existing project's palette at once, and every project you create from then on starts with it.

**I want to remove a package.** `/catalog/nodes` has no remove button. Open each project that has the package and use **Remove from project** in the drawer. When you remove it from the last one, Curio deletes your installed copy and drops the package from your defaults, so new projects stop getting it.

**I want other users on this install to be able to add a package I built.** Build it with **Save as package node** ([part 4](#4-creating-a-package-from-a-canvas-node)), then click **Publish** on it in the Tools panel's **Node Catalog** dropdown or in the `/catalog/nodes` details drawer.

---

## 3. Using a node in a dataflow

Once a package is in the open project, its nodes are in the palette: the built-in nodes sit in the left Tools panel, and nodes from other packages in its **Node Catalog** dropdown. Drag one onto the canvas.

---

## 4. Creating a package from a canvas node

The flow is **Save as package node**: build the node on the canvas, then save it into a new or existing package. Package metadata is edited per package from the **Node Catalog** dropdown.

### Save as package node

1. Drop a node onto the canvas, either a built-in or one from an installed package, and edit its code as usual.
2. Click the **cog** on the node header to open the **Node settings** modal. Change the label, ports, or editor mode if you want.
3. Click **Save as package node…**. A picker appears.
4. Choose **New package…** (a fresh package containing this kind) or an installed package as the target. Read-only packages, including `curio.builtin@1`, are not offered; the way to change a read-only package is to fork it into a new one.
5. After the save, the canvas node is rebound to the new package's kind.

> [!IMPORTANT]
> **Save as package node cannot produce a custom-UI node.** The package it
> builds carries `manifest.json` and `sources/`, never a `scripts/` directory,
> so **forking a custom-UI package this way drops its interface**.
>
> To author a node with its own React interface, work from a checkout and build
> the bundle: see [Authoring nodes](AUTHORING-NODES.md) and
> [EXTENDING.md §6](EXTENDING.md).

### Dependencies are detected from the source

`dependencies.python` and `dependencies.js` in the manifest are filled in from each kind's source file when you save. They are not entered by hand:

- Each top-level `import` or `from … import` in a `.py` source is collected, leaving out the standard library and Curio's own modules. The common cases where the import name differs from the install name are mapped (`cv2` → `opencv-python`, `sklearn` → `scikit-learn`, `PIL` → `pillow`, `yaml` → `pyyaml`, `bs4` → `beautifulsoup4`, `skimage` → `scikit-image`); anything else passes through unchanged.
- In `.js`, `.mjs` and `.cjs` sources, `import … from "X"`, dynamic `import("X")` and `require("X")` are collected. Relative paths are skipped, subpaths collapse to the package (`lodash/fp` → `lodash`), and scoped packages keep their scope (`@scope/pkg`).
- Detected names are written with `*` as the version range. The UI does not offer version pins.
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

The manifest is validated before the package is installed, and an archive whose `<packageId>@<major>` you already have is refused.

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

## See also

- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): datasets, installed and published with the same model.
- [`docs/AGENT-CATALOG.md`](AGENT-CATALOG.md): the agents you attach to nodes.
- [`docs/DATA-LAKE-CATALOG.md`](DATA-LAKE-CATALOG.md): the data portals you download datasets from.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#node-packages-and-manifests): how packages load, and how to add a built-in behavior, icon, or grammar adapter.
- [`docs/USAGE.md`](USAGE.md): installing and running Curio, including the [Vega-Lite node](USAGE.md#vega-lite-node).
- [`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json): the manifest JSON Schema.
- [`docs/schemas/trill.v1.json`](schemas/trill.v1.json): the dataflow JSON Schema. A node's `type` points into a manifest's `templates[].id`.
