# Node Catalog

The Node Catalog is where Curio's nodes live. Every node you can drop on the canvas — the built-ins that ship with the app and any extras you install — comes from a **package**: a small, self-contained folder with a `manifest.json` describing the nodes inside it.

This guide is in four parts, plus a developer appendix:

- [1. What is the Node Catalog?](#1-what-is-the-node-catalog) — the four storage layers and where each kind of action writes.
- [2. Surfaces and workflows](#2-surfaces-and-workflows) — the two places you manage packages (the canvas drawer and the `/catalog` page), the action matrix between them, and step-by-step walkthroughs.
- [3. Creating a new package from a canvas node](#3-creating-a-new-package-from-a-canvas-node) — the **Save as pack node** flow plus the per-package metadata editor.
- [4. Packaging and sharing](#4-packaging-and-sharing) — exporting an archive and importing one.
- [Operator notes](#operator-notes) — env vars and CLI flags that gate Publish.
- [Appendix: adding a new lifecycle or icon (developer-only)](#appendix-adding-a-new-lifecycle-or-icon-developer-only) — code-level extensions when a new node needs runtime behavior the built-in lifecycles don't cover.

---

## 1. What is the Node Catalog?

### Concept

Every node Curio knows about belongs to a **package**, identified by a reverse-domain id and a major version:

```
<packageId>@<major>     e.g.   curio.builtin@1
                            ai.urbanlab.uhvi@1
```

A package is a folder with a `manifest.json` (the contract), an optional `sources/` directory (one starter file per node kind), and a couple of small sibling files (`README.md`, `LICENSE`, `integrity.json`). The manifest declares the **kinds** the package provides — each kind becomes a draggable node in the palette.

Two kinds of packages ship with Curio:

| Package | What it provides |
|---|---|
| `curio.builtin@1` | The default 14 node kinds (Data Loading, Python/JS Computation, Vega-Lite, AutkMap, etc.). Auto-installed for every user; **read-only** (you can save edits as a new package but can't overwrite the originals) and can't be uninstalled. |
| `ai.urbanlab.uhvi@1`, `it.urbanlab.milan-heat@1` | Example third-party packages you can install from the catalog drawer to see the package workflow end-to-end. |

You can install any number of additional packages — your own creations or archives shared by others.

### The four storage layers

Package state in Curio lives in four places. Knowing which one each user action writes to is the key to predicting what happens after an Install or Uninstall:

| Layer | On disk | Who writes |
|---|---|---|
| **Shared catalog** — the source every user browses from | `<repo_root>/packages/<packageId>@<major>/` | **Publish** (gated by `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`; see *Operator notes*). Otherwise read-only. |
| **Per-user package store** — implementations on disk | `.curio/users/<user-key>/packages/<packageId>@<major>/` | Managed implicitly. Install copies in; uninstall (via the drawer) prunes when no project still references the package. No direct UI action writes or deletes here. |
| **Per-user defaults** — what auto-seeds into new projects | `.curio/users/<user-key>/default-packages.json` | The `/catalog` page's **Install** adds an entry; the auto-prune sweep removes it when the last project drops the dep. |
| **Per-project lockfile** — the source of truth for what a project needs | `spec.trill.json` → `dataflow.packages: string[]` (inside each project's `spec.trill.json`) | The canvas drawer's **Install** adds an entry for the open project; **Uninstall** removes it. The `/catalog` page's **Install** also walks every existing project and patches its lockfile. |

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

- **The drawer** (inside the canvas): per-project. Open it from the **Packages** dropdown in the left-edge Tools panel → **Get more packages +**. Installs and uninstalls here affect *only* the open project's lockfile (plus the user-store copy when needed).
- **The `/catalog` page** (linked from the **Catalog** button in the top nav of `/projects`): global. Installs here apply to every existing project of yours AND auto-seed into any new project. There is no Uninstall affordance — see the workflows below for why.

The drawer has just two tabs — **Browse** and **Installed** — with an *Update available* badge surfacing on cards that have a newer catalog version. The `/catalog` page is a single list with **All / Installed / Updates** filter chips.

### Action matrix

| Action | Where | Endpoint | Layers it writes | What you see |
|---|---|---|---|---|
| **Install (one project)** | Drawer | `POST /api/packages/projects/<id>/install` | per-project lockfile (+ user store if missing) | Package shows in this project's palette only. |
| **Install (all your projects)** | `/catalog` page | `POST /api/packages/defaults` | per-user defaults + every project's lockfile (+ user store if missing) | Package appears in every project's palette; future new projects auto-get it too. |
| **Uninstall** | Drawer only | `DELETE /api/packages/projects/<id>/<dirName>` | per-project lockfile; auto-prune may also delete from user store and defaults | Package leaves this project's palette. If no other project still references it, the user-store copy is deleted and the defaults entry (if any) is removed too. |
| **Publish** | Drawer or `/catalog` page | `POST /api/packages/factory/publish-catalog` | shared catalog | Package becomes browseable by every user on this install. Button is hidden entirely when the env gate is off (see *Operator notes*). |

### Workflows

**I want to add a package to one project.** Open the project, click **Packages → Get more packages +** to open the drawer, find the package, click **Install**. The package's nodes appear in this project's palette only. Other projects you have are unaffected.

**I want a package available across all my projects (present and future).** Go to `/projects`, click **Catalog** in the top nav, find the package, click **Install**. Curio adds it to your per-user defaults list AND walks every existing project to patch its lockfile, so the package appears in every project's palette immediately. New projects you create from then on auto-include it too.

**I want to remove a package.** There is *no* global Uninstall on the `/catalog` page — that's deliberate. Open the project (or each project, if it's installed in several) and use the drawer's **Uninstall** button. When you uninstall from the last project that references the package, Curio also deletes the user-store copy AND removes the package from your defaults list so it stops auto-seeding into new projects. (This is the most non-obvious rule in the catalog model — there's no "remove from defaults" button because that fall-through is the only mechanism that ever touches defaults.)

**I want a package I just built to be installable by other users on this Curio install.** Build it via **Save as pack node** (next section), then open the drawer or `/catalog` page and click **Publish** on the package. It writes into the shared catalog at `<repo_root>/packages/`. Note: the Publish button is hidden when the operator disabled catalog writes (see *Operator notes* below).

**I want to make a package a default for new projects without installing it everywhere first.** Just install it once from the `/catalog` page. That's exactly what `/catalog` install does — adds to defaults. The drawer's per-project install does NOT add to defaults; it stays scoped to that one project.

**I want to stop a package from auto-seeding into new projects.** Uninstall it from every project that currently references it. After the last uninstall, Curio's auto-prune sweep removes the package from defaults. There's no separate "remove from defaults" action — by design, the system never leaves a "seed for new projects" entry that no current project actually uses.

---

## 3. Creating a new package from a canvas node

Curio no longer ships the multi-step Node Factory wizard. The single supported flow is **Save as pack node**: build the node on the canvas, then save it into a (new or existing) package. Metadata that used to live in the wizard's steps is now editable per-package from the catalog drawer.

### Save as pack node

1. Drop a node onto the canvas — built-in or from an installed package — and edit its code as usual.
2. Click the **cog** on the node header to open the **Node settings** modal. Tweak the label, ports, or editor mode if you want.
3. Click **Save as pack node…**. A picker appears.
4. Choose **New pack…** (creates a fresh package containing this kind) or an installed package as the target. Read-only packages — including `curio.builtin@1` — are filtered out of the picker; the only way to "modify" a read-only package is to fork into a new one.
5. After save, the canvas node is rebound automatically to the new package's kind, so re-opening **Node settings** resolves to the new descriptor.

When you save **into an existing package**, the backend preserves the unedited templates' on-disk source — your other templates are not clobbered. This is a recent fix; older releases would silently overwrite them with starter-code placeholders.

### Source-driven dependencies

`dependencies.python` and `dependencies.js` in the manifest are derived automatically from each template's source file. You don't (and can't) enter them by hand:

- Each `import` / `from … import` at the top level of a `.py` source is collected. Standard-library modules and Curio-runtime modules are filtered out. A small alias table maps the common cases where the importable name differs from the PyPI install name (`cv2` → `opencv-python`, `sklearn` → `scikit-learn`, `PIL` → `pillow`, `yaml` → `pyyaml`, `bs4` → `beautifulsoup4`, `skimage` → `scikit-image`). Anything not in the alias map passes through unchanged.
- For `.js` / `.mjs` / `.cjs` sources, `import … from "X"`, dynamic `import("X")`, and `require("X")` are scanned. Relative paths are skipped; subpaths collapse to the top-level (`lodash/fp` → `lodash`); scoped packages keep their scope (`@scope/pkg`).
- Detected names land in the manifest with `*` as the version range. Pin-level control isn't exposed in the UI today.
- Detection runs in `/api/packages/factory/install` and `/factory/build`. Uploaded `.curio.zip` archives and catalog installs are **not** re-scanned — those declarations come from the package author verbatim.

### Editing package metadata

Open the **Packages** dropdown in the Tools panel, expand an installed package's accordion, and click the **pencil** button next to the export icon in the row's header. A modal lets you edit:

- Name, description, publisher, license
- Permissions (comma-separated, e.g. `filesystem.read, network.fetch`)
- Curio runtime range (advisory)
- README contents

Read-only packages (`curio.builtin@1` and any third-party package shipped with `readOnly: true`) hide the pencil — the backend also returns `403` if you try to PATCH them. The detected `python` / `js` dependencies are shown as a read-only summary below the editable fields so you can confirm what the source scanner found.

### Where new packages land on disk

When you save (or upload) a package, it lands in your per-user store:

```
<CURIO_LAUNCH_CWD>/.curio/users/<user-key>/packages/<packageId>@<major>/
  manifest.json
  sources/
    <template-id>.{py,js,...}
  starters/<template-id>/        ← optional starter snippets (legacy: templates/)
  integrity.json                 ← SHA-256 of every shipped file
```

Developers can still publish a draft into the repo's local catalog (`<repo_root>/packages/`) via the publish-to-catalog flow in the installed-packages list, gated by the `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH` env var (on by default).

### The manifest schema

Every manifest is validated against [`docs/schemas/node-package.v3.json`](schemas/node-package.v3.json) (JSON Schema Draft 2020-12). The schema is the source of truth for what fields a package can declare. The repo's catalog packages (`packages/curio.builtin@1/`, `packages/ai.urbanlab.uhvi@1/`, `packages/it.urbanlab.milan-heat@1/`) are the canonical examples.

---

## 4. Packaging and sharing

A package is portable: you can export it, send it, and the recipient can drop it back in.

### Exporting

In the catalog drawer, find your installed package under the **Installed** tab. Each row has a download icon — click it to save the package as `<packageId>@<major>.curio.zip` (a deterministic ZIP).

The archive contains exactly what's on disk: `manifest.json`, the `sources/` directory, `README.md` and `LICENSE` if present. `integrity.json` is **not** shipped — the installer regenerates it on the recipient's machine.

### Importing

To install someone else's archive:

1. Open the catalog drawer (Tools panel → **Packages** dropdown → **Get more packages +** in the footer).
2. Click **Import package** in the footer.
3. Pick the archive.

The installer extracts into a tmp directory, validates the manifest, computes integrity hashes, then moves the result into your package store. If the package id collides with one you already have, the upload is rejected — uninstall the existing copy from the **Installed** tab first, then import again.

### Versioning, forks, and lineage

- **Versioning.** Bump the `version` string for patch / minor releases; bump `compatibility.major` (and the directory name suffix) for breaking changes. Two majors of the same package coexist as separate installed coordinates.
- **Forks.** Saving an installed-package node into a fresh package via **Save as pack node** → **New pack…** creates a fork — the new package carries `lineage.forkedFrom` (the immediate parent) and `lineage.root` (the original ancestor). The catalog drawer groups installed forks into accordions under their root, so it's easy to see a family at a glance.
- **Family resolution.** The unversioned ref `<packageId>/<kindId>` resolves to whatever major is installed. If you want a workflow to pin against a specific fork, edit its trill to use the versioned form `<packageId>/<kindId>@<major>`.

### Read-only packages

Set `"readOnly": true` at the top level of a manifest to mark a package as read-only. The flag is honoured end-to-end:

- The factory-install endpoint rejects any draft whose manifest declares `readOnly: true`, *and* it rejects drafts targeting an installed package coordinate whose on-disk manifest is read-only — so a forged draft that omits the flag can't sneak through.
- The Save-As destination picker filters read-only packages out of the dropdown, so the in-canvas authoring flow naturally steers users to a new package.
- The **Node settings** modal shows a **Read-only** badge when the underlying descriptor belongs to a read-only package, and its primary action stays **Save as pack node…**.

The built-in `curio.builtin@1` ships with `readOnly: true`. The same flag is available for **org-curated packs** you want to distribute internally without letting downstream users overwrite kinds in place. Forking via Save-As is unaffected; the new package starts unflagged.

### Caveats

- There is no hosted package registry yet. Sharing is file-based: archives by email, Slack, S3, whatever fits. The committed catalog at `<repo_root>/packages/` is a per-deployment alternative for first-party content.
- The legacy `NodeType` enum strings (`"DATA_LOADING"`, `"VIS_VEGA"`, etc.) used by Curio before the package refactor are no longer recognized. Trill files saved with those strings won't render correctly until the type fields are rewritten to canonical refs (`"curio.builtin/data-loading"`, `"curio.builtin/vis-vega"`, etc.). The example trills in `docs/examples/` are already migrated; legacy user projects need a one-time JSON rewrite.

---

## Operator notes

### Disabling Publish

The Publish / Unpublish actions write into `<repo_root>/packages/`. On a hosted deployment that directory may not be writable, or you may want to lock authoring down for non-dev installs. The env var `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH` gates both the API and the UI:

- **Unset / `1` / `true` / `yes` / `on`** → publishing allowed (the default).
- **`0` / `false` / `no` / `off`** → publishing is forbidden. The backend returns `403` on both `POST /api/packages/factory/publish-catalog` and `DELETE /api/packages/catalog/<dirName>`, and the Publish / Unpublish buttons are **hidden entirely** in the drawer and on the `/catalog` page (not just disabled).

The Curio launcher (`python curio.py start`) exposes the same flag as `--allow-publish` (default on) with the inverse `--no-allow-publish` opt-out. See [`docs/USAGE.md`](USAGE.md) for the full launcher reference and the env-var inventory in [`utk_curio/backend/config.py`](../utk_curio/backend/config.py).

### Backwards compatibility for projects saved before the per-project lockfile

Projects saved before the lockfile became load-bearing have an empty `dataflow.packages` field. On first read, the backend backfills the lockfile by scanning each node's `type` for canonical refs (`<packageId>/<templateId>@<major>`) and the highest installed major of each package id. The reconstructed list is written back to disk the next time the project saves. No migration script is required, and projects can be edited normally while still on the old shape.

---

## Appendix: adding a new lifecycle or icon (developer-only)

Authoring a package via **Save as pack node** or by hand-editing a `manifest.json` covers ~90% of "I want a new node" — the manifest schema already exposes every knob the runtime understands. The remaining 10% is when a kind needs **runtime behavior** that none of the built-in lifecycles provides (e.g. a new visualization library, a node that talks to a custom data source). These are code changes, not package changes.

### Adding a new lifecycle hook

The lifecycles a manifest can reference live in [`src/registry/lifecycleRegistry.ts`](../utk_curio/frontend/urban-workflows/src/registry/lifecycleRegistry.ts); the 11 built-ins are registered in [`src/registry/builtinLifecycles.ts`](../utk_curio/frontend/urban-workflows/src/registry/builtinLifecycles.ts). To add a new one:

1. Implement the hook under [`src/adapters/node/`](../utk_curio/frontend/urban-workflows/src/adapters/node/) — it must conform to the `NodeLifecycleHook` type in [`src/registry/types.ts`](../utk_curio/frontend/urban-workflows/src/registry/types.ts). Look at `useCodeNodeLifecycle` and `useVegaLifecycle` as references.
2. Register it in `builtinLifecycles.ts`: `registerLifecycle("my-key", useMyHook);`
3. Reference it from a package manifest: `"lifecycle": "my-key"` on each kind that wants the new behavior.

Third-party packages can use any key registered at startup. There's no per-package lifecycle code today — manifests can't carry JS.

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

- [`docs/USAGE.md`](USAGE.md) — installation and operating Curio.
- [`docs/schemas/node-package.v3.json`](schemas/node-package.v3.json) — manifest JSON Schema.
- [`packages/curio.builtin@1/manifest.json`](../packages/curio.builtin@1/manifest.json) — the built-in package, used as the canonical example throughout this guide.
