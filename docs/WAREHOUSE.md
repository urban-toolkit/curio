# Node Warehouse

The Node Warehouse is where Curio's nodes live. Every node you can drop on the canvas — the built-ins that ship with the app and any extras you install — comes from a **package**: a small, self-contained folder with a `manifest.json` describing the nodes inside it.

This guide is in three parts:

- [1. What is the Node Warehouse?](#1-what-is-the-node-warehouse) — the model and where to find the warehouse drawer.
- [2. Creating a new package through the interface](#2-creating-a-new-package-through-the-interface) — the Node Factory wizard.
- [3. Packaging and sharing](#3-packaging-and-sharing) — exporting an archive and importing one.

---

## 1. What is the Node Warehouse?

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
| `ai.urbanlab.uhvi@1`, `it.urbanlab.milan-heat@1` | Example third-party packages you can install from the catalog to see the package workflow end-to-end. |

You can install any number of additional packages — your own creations or archives shared by others.

### Where to find it

Open Curio. The **Tools panel** sits on the left edge of the canvas. Inside it, look for the **Packages** dropdown (cube icon, labelled "Packages" with a count of your installed kinds). Open the dropdown and click the **Get more packages +** button in its footer — this opens the warehouse drawer.

The drawer slides in from the right with four tabs:

- **Featured** — the three newest packages in the catalog.
- **Browse all** — every package the catalog advertises.
- **Installed** — what you have in this dataflow, grouped by fork family.
- **Updates** — only the installed packages that have a newer version available.

Each catalog card has an **Install** button on the right. Clicking it opens the **Install "&lt;package name&gt;"** dialog showing the package's declared permissions and Python / JS / package dependencies (plus a red conflict box if any of those clash with what you already have). Click **Install** again to confirm, or **Cancel** to back out. The package's nodes appear in the canvas palette within a second or two.

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

## 2. Creating a new package through the interface

The **Node Factory** is a five-step wizard that turns a draft into an installable package archive — no manual `manifest.json` editing required.

### Opening the wizard

From the warehouse drawer footer, click **Create new package**. A modal slides in over the canvas. (Power users can also deep-link to `/nodes/factory`.)

### The five steps

The stepper across the top of the modal shows the same titles in order:

1. **Metadata** — reverse-domain `id` (e.g. `me.research.bridges`), human-readable `name`, `publisher`, short `description`, optional `license`, and the `version` string. The package's `major` version is part of its coordinate (`<id>@<major>`); patch / minor bumps stay inside `version`.
2. **Kinds and ports** — add one or more node kinds. For each: kebab-case `id`, label, category (data / computation / vis_grammar / vis_simple / flow), engine (Python or JS), input/output ports (with `SupportedType` enum members and cardinality strings like `"1"` or `"[1,n]"`), and an editor mode. You also pick a **lifecycle key** — `"code"` for plain script nodes, `"vega"` for a Vega-Lite chart, etc. The full list is in [`packages/curio.builtin@1/manifest.json`](../packages/curio.builtin@1/manifest.json).
3. **Source** — for each kind, an optional single starter file. The wizard exposes two fields per kind: a **Source filename** (e.g. `uhvi-load.py`, `chart.vl.json`) and a **Source** text area. The factory writes the file to `sources/<filename>` inside the package archive. Leave the source empty to publish a structural kind with no starter — the editor opens blank when a user drops the node.
4. **Dependencies and permissions** — pip packages, JS packages, and other Curio packages your kinds need. Pip packages install into the shared sandbox at install time via `/installPackages`. You also declare permissions here (e.g. `filesystem.read`); they're surfaced verbatim in the install dialog the consumer sees.
5. **Validate and publish** — two buttons:
   - **Save and install** — runs the same backend validator that gates the install endpoint, then installs the package into your dataflow and refreshes the palette.
   - **Export .curio.zip** — runs the validator, then downloads the archive as a zip so you can share it.

A **Live manifest** panel on the right shows the JSON that will be written, updating as you edit.

### From a canvas node

The wizard isn't the only path. If you already have a working node on the canvas — built-in or installed pack — you can save it (and any code edits you've made in place) directly into a package without leaving the dataflow:

1. Drop the node onto the canvas and edit its code as usual.
2. Click the **cog** on the node header to open the **Node settings** modal. Tweak the label, ports, or editor mode if you want.
3. Click **Save as pack node…**. A picker appears.
4. Choose **New pack…** (creates a fresh package containing this kind) or an installed package as the target. Read-only packages — including `curio.builtin@1` — are filtered out of the picker; the only way to "modify" a read-only package is to fork into a new one.
5. After save, the canvas node is rebound automatically to the new package's kind, so re-opening **Node settings** resolves to the new descriptor.

This path uses the same backend factory endpoint as the wizard — there's no second code path to maintain.

### Where new packages land on disk

When you install via the wizard, the package goes into your per-user store:

```
<CURIO_LAUNCH_CWD>/.curio/users/<user-key>/packages/<packageId>@<major>/
  manifest.json
  sources/
    <kind-id>.py
  integrity.json   ← SHA-256 of every shipped file; written by the installer
```

Developers can also publish a fresh draft into the repo's local catalog (`<repo_root>/packages/`) via the wizard's **Publish to dev catalog** button at the bottom of step 5 (with an optional "Replace existing fixture" checkbox if you're overwriting an earlier publish at the same coordinate). That button is gated by the `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH` env var (on by default; set to `0`/`false`/`no`/`off` to disable in deployments — the button greys out with an explanatory note when disabled).

### The manifest schema

Every manifest is validated against [`docs/schemas/node-package.v3.json`](schemas/node-package.v3.json) (JSON Schema Draft 2020-12). The schema is the source of truth for what fields a package can declare. The repo's catalog packages (`packages/curio.builtin@1/`, `packages/ai.urbanlab.uhvi@1/`, `packages/it.urbanlab.milan-heat@1/`) are the canonical examples.

---

## 3. Packaging and sharing

A package is portable: you can export it, send it, and the recipient can drop it back in.

### Exporting

In the warehouse drawer, find your installed package under the **Installed** tab. Each row has a download icon — click it to save the package as `<packageId>@<major>.curio.zip` (a deterministic ZIP). You can also export from the Node Factory wizard at step 5.

The archive contains exactly what's on disk: `manifest.json`, the `sources/` directory, `README.md` and `LICENSE` if present. `integrity.json` is **not** shipped — the installer regenerates it on the recipient's machine.

### Importing

To install someone else's archive:

1. Open the warehouse drawer (Tools panel → **Packages** dropdown → **Get more packages +** in the footer).
2. Click **Import package** in the footer.
3. Pick the archive.

The installer extracts into a tmp directory, validates the manifest, computes integrity hashes, then moves the result into your package store. If the package id collides with one you already have, the upload is rejected — uninstall the existing copy from the **Installed** tab first, then import again.

### Versioning, forks, and lineage

- **Versioning.** Bump the `version` string for patch / minor releases; bump `compatibility.major` (and the directory name suffix) for breaking changes. Two majors of the same package coexist as separate installed coordinates.
- **Forks.** Save-As in the wizard creates a fork — the new package carries `lineage.forkedFrom` (the immediate parent) and `lineage.root` (the original ancestor). The warehouse drawer groups installed forks into accordions under their root, so it's easy to see a family at a glance.
- **Family resolution.** The unversioned ref `<packageId>/<kindId>` resolves to whatever major is installed. If you want a workflow to pin against a specific fork, edit its trill to use the versioned form `<packageId>/<kindId>@<major>`.

### Read-only packages

Set `"readOnly": true` at the top level of a manifest to mark a package as read-only. The flag is honoured end-to-end:

- The factory-install endpoint rejects any draft whose manifest declares `readOnly: true`, *and* it rejects drafts targeting an installed package coordinate whose on-disk manifest is read-only — so a forged draft that omits the flag can't sneak through.
- The Save-As destination picker filters read-only packages out of the dropdown, so the in-canvas authoring flow naturally steers users to a new package.
- The **Node settings** modal shows a **Read-only** badge when the underlying descriptor belongs to a read-only package, and its primary action stays **Save as pack node…**.

The built-in `curio.builtin@1` ships with `readOnly: true`. The same flag is available for **org-curated packs** you want to distribute internally without letting downstream users overwrite kinds in place. Forking via the wizard or Save-As is unaffected; the new package starts unflagged.

### Caveats

- There is no hosted package registry yet. Sharing is file-based: archives by email, Slack, S3, whatever fits. The committed catalog at `<repo_root>/packages/` is a per-deployment alternative for first-party content.
- The legacy `NodeType` enum strings (`"DATA_LOADING"`, `"VIS_VEGA"`, etc.) used by Curio before the package refactor are no longer recognized. Trill files saved with those strings won't render correctly until the type fields are rewritten to canonical refs (`"curio.builtin/data-loading"`, `"curio.builtin/vis-vega"`, etc.). The example trills in `docs/examples/` are already migrated; legacy user projects need a one-time JSON rewrite.

---

---

## Appendix: adding a new lifecycle or icon (developer-only)

Authoring a package via the wizard or by hand-editing a `manifest.json` covers ~90% of "I want a new node" — the manifest schema already exposes every knob the runtime understands. The remaining 10% is when a kind needs **runtime behavior** that none of the built-in lifecycles provides (e.g. a new visualization library, a node that talks to a custom data source). These are code changes, not package changes.

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
