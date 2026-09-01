# Node Catalog

The Node Catalog is where Curio's nodes live. Every node you can drop on the canvas, whether a built-in that ships with the app or an extra you install, comes from a **package**: a small, self-contained folder with a `manifest.json` describing the nodes inside it.

This guide is in four parts, plus a developer appendix:

- [1. What is the Node Catalog?](#1-what-is-the-node-catalog): the four storage layers and where each kind of action writes.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the two places you manage packages (the canvas drawer and the `/catalog` page), the action matrix between them, and step-by-step walkthroughs.
- [3. Creating a new package from a canvas node](#3-creating-a-new-package-from-a-canvas-node): the **Save as package node** flow plus the per-package metadata editor.
- [4. Packaging and sharing](#4-packaging-and-sharing): exporting an archive and importing one.
- [Operator notes](#operator-notes): env vars and CLI flags that gate Publish.
- [Appendix: adding a new behavior or icon (developer-only)](#appendix-adding-a-new-behavior-or-icon-developer-only): code-level extensions for when a new node needs runtime behavior the built-in behaviors don't cover.

---

## 1. What is the Node Catalog?

### Concept

Every node Curio knows about belongs to a **package**, identified by a reverse-domain id and a major version:

```
<packageId>@<major>     e.g.   curio.builtin@1
                            ai.urbanlab.uhvi@1
```

A package is a folder with a `manifest.json` (the contract), an optional `sources/` directory (one starter file per node kind), and a couple of small sibling files (`README.md`, `LICENSE`, `integrity.json`). The manifest declares the **kinds** the package provides, and each kind becomes a draggable node in the palette.

Several packages ship with Curio:

| Package | What it provides |
|---|---|
| `curio.builtin@1` | The default 12 node kinds (Data Loading, Python/JS Computation, Vega-Lite, Autark, etc.). Auto-installed for every user; **read-only** (you can save edits as a new package but can't overwrite the originals) and can't be uninstalled. |
| `ai.urbanlab.uhvi@1`, `curio.weather@1` | Example packages you can install from the catalog drawer to see the package workflow end-to-end. Both are plain Python nodes (`behavior: "code"`). `curio.weather@1` is also auto-seeded (still uninstallable) when Curio starts with `--with-examples` / `--deploy`, because the seeded example workflows need its Python deps (rasterio, pythermalcomfort, rasterstats). |
| `curio.example-ui@1` | A minimal worked example of a node with its **own React interface** rather than a code editor, with no API keys, no Python deps, and about 150 lines. The reference to read and fork for custom-UI nodes; see [AUTHORING-NODES.md](AUTHORING-NODES.md). |
| `curio.streetvision@1` | A substantial custom-UI package (Street View fetch + HuggingFace inference + gallery). Not auto-installed, `readOnly`, and needs a Google Maps API key plus torch/transformers. Read it for the advanced patterns, not as a starting point. |

You can install any number of additional packages, either your own creations or archives shared by others.

### The four storage layers

Package state in Curio lives in four places. Knowing which one each user action writes to is the key to predicting what happens after an **Add to dataflow**, an **Add to all projects**, or a **Remove from dataflow**:

| Layer | On disk | Who writes |
|---|---|---|
| **Shared catalog** (the source every user browses from) | `<repo_root>/packages/<packageId>@<major>/` | **Publish** (gated by `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`; see *Operator notes*). Otherwise read-only. |
| **Per-user package store** (implementations on disk) | `.curio/users/<user-key>/packages/<packageId>@<major>/` | Managed implicitly. Adding copies in; removing (via the drawer) prunes when no project still references the package. No direct UI action writes or deletes here. |
| **Per-user defaults** (what auto-seeds into new projects) | `.curio/users/<user-key>/default-packages.json` | The **Nodes** tab on `/catalog` (**Add to all projects**) adds an entry; the auto-prune sweep removes it when the last project drops the dep. |
| **Per-project lockfile** (the source of truth for what a project needs) | `spec.trill.json` → `dataflow.packages: string[]` (inside each project's `spec.trill.json`) | The canvas drawer's **Add to dataflow** adds an entry for the open project; **Remove from dataflow** removes it. The **Nodes** tab on `/catalog` (**Add to all projects**) also walks every existing project and patches its lockfile. |

The canvas palette reads from the per-project lockfile (intersected with the user store), so two projects open in different tabs see different palettes even though they share one user store.

### How a node ref looks in your saved workflow

When you save a project, Curio writes each node's type as the **unversioned canonical id**:

```
curio.builtin/data-loading
ai.urbanlab.uhvi/uhvi-load
```

At load time the runtime resolves this to the highest installed major of that package. If you specifically want to pin a workflow to a major version (e.g. when collaborating on a research artefact), edit the saved trill to use the **versioned** form:

```
curio.builtin/data-loading@1
ai.urbanlab.uhvi/uhvi-load@1
```

---

## 2. Surfaces and workflows

There are exactly two places you manage packages:

- **The drawer** (inside the canvas): per-project. Open it from the **Node Catalog** dropdown in the left-edge Tools panel → **Browse Node Catalog +**. Adding and removing here affect *only* the open project's lockfile (plus the user-store copy when needed), which is why its buttons say per-dataflow.
- **The `/catalog` master page** (linked from **Catalog** on `/projects`): opens on the **Nodes** tab (`/catalog/nodes`). Adding there applies to every existing project of yours and auto-seeds into any new project, so the button reads **Add to all projects** rather than the drawer's **Add to dataflow**. There is no removal affordance; the workflows below explain why. The sibling **Data** tab (`/catalog/data`) is the Data Catalog, which manages datasets rather than nodes (see [DATA-CATALOG.md](DATA-CATALOG.md)).

The drawer's two working tabs are **Browse** and **In dataflow**; an *update available* note appears on a row whose catalog copy carries a different `version`. Each row on **In dataflow** also has a **Reload** button (circular-arrows icon) that re-copies the package from the shared catalog over your installed copy. Use it when you are editing a package under `packages/` and want your changes to show up (see [Authoring nodes](AUTHORING-NODES.md)). It is offered for any package the catalog also carries, not only when the version differs, because editing source without bumping `version` is the normal authoring loop. The **Nodes** tab on `/catalog` uses a Data Catalog-style layout with status and category filters plus a preview drawer.

### Action matrix

| Action | Where | Endpoint | Layers it writes | What you see |
|---|---|---|---|---|
| **Add to dataflow** (one project) | Drawer | `POST /api/packages/projects/<id>/install` | per-project lockfile (+ user store if missing) | Package shows in this project's palette only. |
| **Add to all projects** | `/catalog` page | `POST /api/packages/defaults` | per-user defaults + every project's lockfile (+ user store if missing) | Package appears in every project's palette; future new projects auto-get it too. |
| **Remove from dataflow** | Drawer only | `DELETE /api/packages/projects/<id>/<dirName>` | per-project lockfile; auto-prune may also delete from user store and defaults | Package leaves this project's palette. If no other project still references it, the user-store copy is deleted and the defaults entry (if any) is removed too. |
| **Reload** | Drawer (**In dataflow**) | `POST /api/packages/catalog/install` with `replace: true` | per-user package store | The installed copy is overwritten from the shared catalog and the page reloads. The way to pick up edits to a package you are authoring under `packages/`. |
| **Publish** | Drawer or `/catalog` page | `POST /api/packages/factory/publish-catalog` | shared catalog | Package becomes browseable by every user on this install. Button is hidden entirely when the env gate is off (see *Operator notes*). |

### Workflows

**I want to add a package to one project.** Open the project, click **Node Catalog → Browse Node Catalog +** to open the drawer, find the package, click **Add to dataflow**. The package's nodes appear in this project's palette only. Other projects you have are unaffected.

**I want a package available across all my projects (present and future).** Go to `/projects`, click **Catalog** in the top nav, find the package, click **Add to all projects**. Curio adds it to your per-user defaults list AND walks every existing project to patch its lockfile, so the package appears in every project's palette immediately. New projects you create from then on auto-include it too.

**I want to remove a package.** There is *no* global removal on the `/catalog` page, and that is deliberate. Open the project (or each project, if it was added to several) and use the drawer's **Remove from dataflow** button. When you remove it from the last project that references the package, Curio also deletes the user-store copy AND removes the package from your defaults list so it stops auto-seeding into new projects. (This is the most non-obvious rule in the catalog model: there is no "remove from defaults" button, because that fall-through is the only mechanism that ever touches defaults.)

**I want a package I just built to be installable by other users on this Curio install.** Build it via **Save as package node** (next section), then open the drawer or `/catalog` page and click **Publish** on the package. It writes into the shared catalog at `<repo_root>/packages/`. Note: the Publish button is hidden when the operator disabled catalog writes (see *Operator notes* below).

**I want to make a package a default for new projects without adding it everywhere first.** Just use **Add to all projects** once from the `/catalog` page. That's exactly what that action does: it adds to defaults. The drawer's **Add to dataflow** does NOT add to defaults; it stays scoped to that one project.

**I want to stop a package from auto-seeding into new projects.** Remove it from every project that currently references it. After the last removal, Curio's auto-prune sweep removes the package from defaults. There's no separate "remove from defaults" action. By design, the system never leaves a "seed for new projects" entry that no current project actually uses.

---

## 3. Creating a new package from a canvas node

Curio no longer ships the multi-step Node Factory wizard. The single supported flow is **Save as package node**: build the node on the canvas, then save it into a (new or existing) package. Metadata that used to live in the wizard's steps is now editable per-package from the catalog drawer.

### Save as package node

1. Drop a node onto the canvas, either a built-in or one from an installed package, and edit its code as usual.
2. Click the **cog** on the node header to open the **Node settings** modal. Tweak the label, ports, or editor mode if you want.
3. Click **Save as package node…**. A picker appears.
4. Choose **New package…** (creates a fresh package containing this kind) or an installed package as the target. Read-only packages, including `curio.builtin@1`, are filtered out of the picker; the only way to "modify" a read-only package is to fork into a new one.
5. After save, the canvas node is rebound automatically to the new package's kind, so re-opening **Node settings** resolves to the new descriptor.

When you save **into an existing package**, the backend preserves the unedited templates' on-disk source, so your other templates are not clobbered.

> [!IMPORTANT]
> **Save as package node cannot produce a custom-UI node.** The archive it
> builds carries `manifest.json`, `sources/`, `README.md` and `LICENSE`, but
> never a `scripts/` directory (see `build_packageage_archive` in
> [`factory.py`](../utk_curio/backend/app/packages/factory.py)). So every
> package authored this way is a code-editor node, and **forking a custom-UI
> package this way drops its interface**: the fork inherits the manifest's
> `behaviorScript` path but not the compiled bundle, the loader's fetch 404s,
> and the node quietly falls back to the generic code editor. Nothing is
> broken, but if you forked `curio.streetvision@1` expecting its UI, that is
> why you got a code box.
>
> To author a node with its own React interface, work from a checkout and build
> the bundle: see [Authoring nodes](AUTHORING-NODES.md) and
> [EXTENDING.md §6](EXTENDING.md).

### Source-driven dependencies

`dependencies.python` and `dependencies.js` in the manifest are derived automatically from each template's source file. You don't (and can't) enter them by hand:

- Each `import` / `from … import` at the top level of a `.py` source is collected. Standard-library modules and Curio-runtime modules are filtered out. A small alias table maps the common cases where the importable name differs from the PyPI install name (`cv2` → `opencv-python`, `sklearn` → `scikit-learn`, `PIL` → `pillow`, `yaml` → `pyyaml`, `bs4` → `beautifulsoup4`, `skimage` → `scikit-image`). Anything not in the alias map passes through unchanged.
- For `.js` / `.mjs` / `.cjs` sources, `import … from "X"`, dynamic `import("X")`, and `require("X")` are scanned. Relative paths are skipped; subpaths collapse to the top-level (`lodash/fp` → `lodash`); scoped packages keep their scope (`@scope/pkg`).
- Detected names land in the manifest with `*` as the version range. Pin-level control isn't exposed in the UI today.
- Detection runs in `/api/packages/factory/install` and `/factory/build`. Uploaded `.curio.zip` archives and catalog installs are **not** re-scanned; those declarations come from the package author verbatim.

### Editing package metadata

Open the **Node Catalog** dropdown in the Tools panel, expand an installed package's accordion, and click the **pencil** button next to the export icon in the row's header. A modal lets you edit:

- Name, description, publisher, license
- Permissions (comma-separated, e.g. `filesystem.read, network.fetch`)
- Curio runtime range (advisory)
- README contents

Read-only packages (`curio.builtin@1` and any third-party package shipped with `readOnly: true`) hide the pencil, and the backend also returns `403` if you try to PATCH them. The detected `python` / `js` dependencies are shown as a read-only summary below the editable fields so you can confirm what the source scanner found.

### Where new packages land on disk

When you save (or upload) a package, it lands in your per-user store:

```
<CURIO_LAUNCH_CWD>/.curio/users/<user-key>/packages/<packageId>@<major>/
  manifest.json
  sources/
    <template-id>.{py,js,...}
  starters/<template-id>/        ← optional starter snippets
  integrity.json                 ← SHA-256 of every shipped file
```

Developers can still publish a draft into the repo's local catalog (`<repo_root>/packages/`) via the publish-to-catalog flow in the installed-packages list, gated by the `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH` env var (on by default).

### The manifest schema

Every manifest is validated against [`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json) (JSON Schema Draft 2020-12). The schema is the source of truth for what fields a package can declare. The repo's catalog packages (`packages/curio.builtin@1/`, `packages/ai.urbanlab.uhvi@1/`, `packages/curio.weather@1/`) are the canonical examples.

---

## 4. Packaging and sharing

A package is portable: you can export it, send it, and the recipient can drop it back in.

### Exporting

Open the **Node Catalog** dropdown in the left Tools panel and click the **download** icon on your package's row ("Export package"). It saves the package as `<packageId>@<major>.curio.zip` (a deterministic ZIP). The export and metadata-edit buttons live on those rows, next to each other; the catalog drawer handles adding and removing rather than export.

The archive contains exactly what's on disk: `manifest.json`, `sources/`, `README.md`, `LICENSE`, and `scripts/` (so a custom-UI package's compiled `behaviors.js` travels with it and the recipient needs no build step). `integrity.json` is the one exception: it is **not** shipped, because the installer regenerates it on the recipient's machine.

Files sit at the **root of the zip**, not inside a `<packageId>@<major>/` wrapper directory. Worth knowing if you ever hand-zip a package you built under `packages/` but never installed, since the export button only works on packages in your user store. The installer ignores the archive's own name and derives the destination directory from the manifest.

### Importing

To install someone else's archive:

1. Open the catalog drawer (Tools panel → **Node Catalog** dropdown → **Browse Node Catalog +** in the footer).
2. Click **Import package** in the footer.
3. Pick the archive.

The installer extracts into a tmp directory, validates the manifest, computes integrity hashes, then moves the result into your package store. If the package id collides with one you already have, the upload is rejected. Remove the existing copy from the **In dataflow** tab first, then import again.

### Versioning, forks, and lineage

- **Versioning.** Bump the `version` string for patch / minor releases; bump `compatibility.major` (and the directory name suffix) for breaking changes. Two majors of the same package coexist as separate installed coordinates.
- **Forks.** Saving an installed-package node into a fresh package via **Save as package node** → **New package…** creates a fork. The new package carries `lineage.forkedFrom` (the immediate parent) and `lineage.root` (the original ancestor). The catalog drawer groups installed forks into accordions under their root, so it's easy to see a family at a glance.
- **Family resolution.** The unversioned ref `<packageId>/<kindId>` resolves to whatever major is installed. If you want a workflow to pin against a specific fork, edit its trill to use the versioned form `<packageId>/<kindId>@<major>`.

### Read-only packages

Set `"readOnly": true` at the top level of a manifest to mark a package as read-only. The flag is honoured end-to-end:

- The factory-install endpoint rejects any draft whose manifest declares `readOnly: true`, *and* it rejects drafts targeting an installed package coordinate whose on-disk manifest is read-only, so a forged draft that omits the flag can't sneak through.
- The Save-As destination picker filters read-only packages out of the dropdown, so the in-canvas authoring flow naturally steers users to a new package.
- The **Node settings** modal shows a **Read-only** badge when the underlying descriptor belongs to a read-only package, and its primary action stays **Save as package node…**.

The built-in `curio.builtin@1` ships with `readOnly: true`. The same flag is available for **org-curated packages** you want to distribute internally without letting downstream users overwrite kinds in place. Forking via Save-As is unaffected; the new package starts unflagged.

### Caveats

- There is no hosted package registry yet. Sharing is file-based: archives by email, Slack, S3, whatever fits. The committed catalog at `<repo_root>/packages/` is a per-deployment alternative for first-party content.
- To find which of your saved projects are affected, run `python scripts/validate_trill.py --all --resolve`;
  it reports every dataflow that no longer matches [`docs/schemas/trill.v1.json`](schemas/trill.v1.json),
  and `--resolve` additionally flags node types with no installed template. See
  [`docs/TRILL-SPEC.md`](TRILL-SPEC.md).
- The legacy `NodeType` enum strings (`"DATA_LOADING"`, `"VIS_VEGA"`, etc.) used by Curio before the package refactor are no longer recognized. Trill files saved with those strings won't render correctly until the type fields are rewritten to canonical refs (`"curio.builtin/data-loading"`, `"curio.builtin/vis-vega"`, etc.). The example trills in `docs/examples/` are already migrated; legacy user projects need a one-time JSON rewrite.

---

## Operator notes

### Disabling Publish

The Publish / Unpublish actions write into `<repo_root>/packages/`. On a hosted deployment that directory may not be writable, or you may want to lock authoring down for non-dev installs. The env var `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH` gates both the API and the UI:

- **Unset / `1` / `true` / `yes` / `on`** → publishing allowed (the default).
- **`0` / `false` / `no` / `off`** → publishing is forbidden. The backend returns `403` on both `POST /api/packages/factory/publish-catalog` and `DELETE /api/packages/catalog/<dirName>`, and the Publish / Unpublish buttons are **hidden entirely** in the drawer and on the `/catalog` page (not just disabled).

The Curio launcher (`python curio.py start`) exposes the same flag as `--allow-publish` (default on) with the inverse `--no-allow-publish` opt-out. Note the launcher **sets this env var on every start**, so `--no-allow-publish` is the way to turn it off; putting `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH=0` in a `.env` has no effect when you start through `curio.py`. See [`docs/USAGE.md`](USAGE.md) for the full launcher reference and the env-var inventory in [`utk_curio/backend/config.py`](../utk_curio/backend/config.py).

Two things worth knowing before you leave publishing on for a shared install: publishing is allowed for **any** signed-in user, and `DELETE /api/packages/catalog/<dirName>` performs no ownership check, so anyone who can reach the API can replace or remove any package in the shared catalog, `curio.builtin@1` included. On a single-user local install (the normal case for authoring) this is a non-issue. On anything multi-user, start with `--no-allow-publish` and treat `<repo_root>/packages/` as operator-managed.

### Backwards compatibility for projects saved before the per-project lockfile

Projects saved before the lockfile became load-bearing have an empty `dataflow.packages` field. On first read, the backend backfills the lockfile by scanning each node's `type` for canonical refs (`<packageId>/<templateId>@<major>`) and the highest installed major of each package id. The reconstructed list is written back to disk the next time the project saves. No migration script is required, and projects can be edited normally while still on the old shape.

---

## Appendix: adding a new behavior or icon (developer-only)

Authoring a package via **Save as package node** or by hand-editing a `manifest.json` covers almost every case of "I want a new node", because the manifest schema already exposes every knob the runtime understands. The exception is a kind that needs **runtime behavior** none of the built-in behaviors provides, such as a new visualization library or a node that talks to a custom data source. Those are code changes, not package changes.

### Adding a new behavior hook

The behaviors a manifest can reference live in [`src/registry/behaviorRegistry.ts`](../utk_curio/frontend/urban-workflows/src/registry/behaviorRegistry.ts); the 11 built-ins are registered in [`src/registry/builtinBehaviors.ts`](../utk_curio/frontend/urban-workflows/src/registry/builtinBehaviors.ts). To add a new one:

1. Implement the hook under [`src/adapters/node/`](../utk_curio/frontend/urban-workflows/src/adapters/node/). It must conform to the `NodeBehaviorHook` type in [`src/registry/types.ts`](../utk_curio/frontend/urban-workflows/src/registry/types.ts). Look at `useCodeNodeBehavior` and `useVegaBehavior` as references.
2. Register it in `builtinBehaviors.ts`: `registerBehavior("my-key", useMyHook);`
3. Reference it from a package manifest: `"behavior": "my-key"` on each kind that wants the new behavior.

Third-party packages can use any key registered at startup. There's no per-package behavior code today; manifests can't carry JS.

### Adding a new icon

[`src/registry/iconRegistry.ts`](../utk_curio/frontend/urban-workflows/src/registry/iconRegistry.ts) maps `iconRef` strings (e.g. `"fa-solid:upload"`) to FontAwesome `IconDefinition` constants. To expose a new icon to manifests:

1. Import the icon constant at the top of `iconRegistry.ts`.
2. Add a `registerIcon("fa-solid:my-icon", faMyIcon);` line.
3. Reference it in your manifest: `"iconRef": "fa-solid:my-icon"`.

Unknown refs fall back to `faCube`, so missing-icon mistakes are visible but non-fatal.

### Adding a new grammar adapter

Same pattern, [`src/registry/grammarAdapter.ts`](../utk_curio/frontend/urban-workflows/src/registry/grammarAdapter.ts). The Vega-Lite adapter in [`src/adapters/vegaLiteAdapter.ts`](../utk_curio/frontend/urban-workflows/src/adapters/vegaLiteAdapter.ts) is the only one shipped today and is the canonical example.

---

## See also

- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): the Data Catalog, which applies the same install and publish model to datasets.
- [`docs/USAGE.md`](USAGE.md): installation and operating Curio.
- [`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json): the manifest JSON Schema.
- [`docs/schemas/trill.v1.json`](schemas/trill.v1.json): the dataflow JSON Schema. A node's `type` is a
  coordinate into a manifest's `templates[].id`; that schema validates the coordinate's shape, this one
  defines what it points at.
- [`packages/curio.builtin@1/manifest.json`](../packages/curio.builtin@1/manifest.json): the built-in package, used as the canonical example throughout this guide.
