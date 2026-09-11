# Authoring nodes

How to build your own Curio node, from a fresh clone to a package you can hand
to someone else.

Curio's palette is not a fixed list. Every node, the built-ins included, comes
from a **package**: a folder with a `manifest.json` declaring one or more node
templates. Adding a node means adding a package, and you can do that without
touching Curio's own source.

There are two kinds of node, and they are very different amounts of work:

| | Tier 1: Python node | Tier 2: custom UI node |
|---|---|---|
| What the user sees | Curio's code editor | Controls you design |
| You write | Python | A React hook (TypeScript) |
| Build step | none | `npm run build:packages` |
| Authored from | the canvas, no restart | files in `packages/`, rebuild + reload |
| Example | [`curio.weather@1`](../packages/curio.weather@1/) | [`curio.example-ui@1`](../packages/curio.example-ui@1/) |

Start with Tier 1 even if you know you want Tier 2. It gets you a working
package in ten minutes and teaches the manifest, which Tier 2 also needs.

**Contents**

- [Setup](#setup)
- [Tier 1: a Python node](#tier-1-a-python-node)
- [Tier 2: a node with its own interface](#tier-2-a-node-with-its-own-interface)
- [Reading upstream data](#reading-upstream-data)
- [Things that will trip you up](#things-that-will-trip-you-up)
- [Submitting your package](#submitting-your-package)
- [Where to go next](#where-to-go-next)

---

## Setup

**Install from a git clone.** Not pip. The pip package ships a pre-built
frontend that cannot be rebuilt, which rules out Tier 2 entirely, and it has no
writable `packages/` directory to author in.

```bash
conda create -n curio python=3.12
conda activate curio

git clone https://github.com/urban-toolkit/curio.git
cd curio

pip install -r requirements.txt
conda install -c conda-forge nodejs=24

python curio.py start
```

The first start takes 10 to 15 minutes: it installs frontend dependencies, runs a
webpack build, and pip-installs the Python dependencies every installed
package's manifest declares. Later starts are fast. When it finishes, Curio is
at <http://localhost:8080>.

Full installation notes, including Docker, are in [USAGE.md](USAGE.md).

---

## Tier 1: a Python node

A Python node reuses Curio's built-in `code` behavior: Curio renders its
standard editor, and your Python runs in the sandbox. You never write any
JavaScript, and you can do the whole thing from the canvas.

### From the canvas

1. Drop a **Data Transformation** node on the canvas and write your Python in
   the **Code** view. `arg` is the upstream node's output; whatever you `return`
   becomes this node's output. Run it until it does what you want.
2. Click the **cog** on the node header to open **Node settings**. Set the label,
   the port types, and the editor mode.
3. Click **Save as package node…**, then **New package…**. Give it a package id
   (reverse-domain, e.g. `me.roughness`).
4. The canvas node rebinds to your new package's kind. It is now in the palette,
   and it survives a restart.

Your package lands in your user store, not in the repo:

```
.curio/users/<user-key>/packages/<id>@<major>/
├── manifest.json
└── sources/<template-id>.py
```

Edit its metadata later (name, description, publisher, license, README) with
the **pencil** button on the package's row in the **Node Catalog** dropdown.

Python dependencies are detected from your source: `import geopandas` in the
node body puts `geopandas` in `manifest.dependencies.python`, and the catalog
install pip-installs it for whoever installs your package.

### From the scaffold

If you would rather start from files, which you will need for Tier 2 anyway:

```bash
python scripts/new_package.py me.roughness
```

That writes a valid `packages/me.roughness@1/` with a manifest, a Python
starter, a README, a LICENSE and an `integrity.json`. Install it from the canvas
via **Node Catalog → Browse Node Catalog + → Browse → Add to dataflow**.

---

## Tier 2: a node with its own interface

A custom-UI node replaces the code editor with controls you write: a React hook
that renders JSX inside the node body, reads upstream data, and pushes results
downstream.

> [!IMPORTANT]
> **Save as package node cannot do this.** The archive it builds carries
> `manifest.json`, `sources/`, `README.md` and `LICENSE`, but never the
> compiled bundle a custom UI needs. So the in-canvas flow always produces a
> code-editor node, and forking a custom-UI package that way silently loses its
> interface. Tier 2 has to be authored from files.

### The loop

```bash
# once per package
python scripts/new_package.py me.mynode --with-ui
#   -> paste the PACKAGE_ENTRIES row it prints into
#      utk_curio/frontend/urban-workflows/webpack.packages.config.js

# after every edit to sources/
cd utk_curio/frontend/urban-workflows
npm run build:packages          # seconds, not the full app build

# then, in the browser
#   first time:  Node Catalog -> Browse Node Catalog + -> Browse -> Add to dataflow
#   after that:  Node Catalog -> Browse Node Catalog + -> In dataflow -> Reload
```

**That last step is the one people miss.** Curio serves your node's bundle from
your *installed copy* in the user store, not from `packages/`. Adding a package
that is already installed does nothing, so without **Reload** your rebuilt code
never runs and it looks as though your edit had no effect. The Reload button
(circular arrows, on each row of the **In dataflow** tab) re-copies the package
from `packages/` over the installed copy and reloads the page.

### What the scaffold gives you

```
packages/me.mynode@1/
├── manifest.json                  behaviorScript: "scripts/behaviors.js"
├── sources/
│   ├── index.tsx                  registerBehavior('my-node', useMyNodeBehavior)
│   └── myNodeBehavior.tsx         your node
└── scripts/behaviors.js           built by npm run build:packages
```

Three things have to agree, and this is the most common source of a node that
renders as an empty code box:

1. the template's `behavior` key in `manifest.json`,
2. the key passed to `registerBehavior` in `sources/index.tsx`,
3. the manifest's top-level `behaviorScript` path, pointing at the built bundle.

### The hook

A behavior hook is a React custom hook. It receives the node's runtime `data`
and the shared `nodeState`, and returns the parts of the node it wants to
override:

```tsx
export const useMyNodeBehavior: NodeBehaviorHook = (data, nodeState) => {
  const [value, setValue] = useState('');

  const contentComponent = (
    <div>
      <input value={value} onChange={(e) => setValue(e.target.value)} />
      <button onClick={() => {
        data.outputCallback(data.nodeId, { data: result, dataType: 'dataframe' });
        nodeState.setOutput({ code: 'success', content: '' });
      }}>
        Send downstream
      </button>
    </div>
  );

  return { contentComponent };
};
```

`contentComponent` is the usual one. The full set (`sendCodeOverride`,
`dynamicHandles`, `handlesOverride`, `defaultValueOverride` and the rest) is
documented in [ARCHITECTURE.md § Behavior Hooks](ARCHITECTURE.md#behavior-hooks)
and typed in
[`registry/types.ts`](../utk_curio/frontend/urban-workflows/src/registry/types.ts).

Read [`packages/curio.example-ui@1`](../packages/curio.example-ui@1/) before
writing your own. It is a complete, minimal custom-UI node: a column filter in
around 150 lines of hook, with no API keys and no Python dependencies, and it
is meant to be forked.

---

## Reading upstream data

This deserves its own section because it is the one part of a custom-UI node
that is not guessable.

`data.input` usually holds a **reference** to a sandbox artifact, not the data:

```js
{ path: 'art-12', dataType: 'dataframe' }   // from any Python or JS node
{ data: {...},    dataType: 'dataframe' }   // from another custom-UI node
```

Python and JS nodes store their output in the sandbox and hand you an id. To get
the actual rows, fetch it:

```ts
const res = await fetch(
  `${BACKEND_URL}/get?fileName=${encodeURIComponent(ref)}`,
  { headers: { Authorization: `Bearer ${token}` } },
);
```

A node that only handles the inline shape appears to work when you wire it to
another custom-UI node, then does nothing at all behind a Data Loading node.
`resolveInput` in
[`columnFilterBehavior.tsx`](../packages/curio.example-ui@1/sources/columnFilterBehavior.tsx)
handles both shapes plus the generic envelopes the sandbox sometimes wraps
around an artifact; copy it.

Two details in that code that are easy to get wrong:

- **`BACKEND_URL` comes from `window.curio.backendUrl`, not
  `process.env.BACKEND_URL`.** The env var is inlined at *your* build time, so a
  bundle built that way points at your machine for everyone who installs it.
- **The session token is in the `session_token` cookie.** The artifact endpoint
  requires it.

A `dataframe` payload is column-oriented. Curio's sandbox serialises with
`DataFrame.to_dict(orient='list')`, so **each column is an array** and the row
index is its position:

```js
{ "population": [2746, 8804], "name": ["Chicago", "…"] }
```

Hand-written specs and a bare `DataFrame.to_dict()` produce the row-map form
instead, where each column is an object keyed by row index:

```js
{ "population": { "0": 2746, "1": 8804 }, "name": { "0": "Chicago", "1": "…" } }
```

**Accept both.** A node that requires the row-map form silently sees no data
from any real Curio DataFrame - it has nothing to render and nothing to throw,
so it just shows its "connect something upstream" hint forever. That is exactly
how #194 happened, in the example package this document describes. Read a cell
through a helper rather than indexing directly:

```js
const cell = (column, key) => (Array.isArray(column) ? column[Number(key)] : column[key]);
```

A `geodataframe` payload is a GeoJSON `FeatureCollection`.

---

## Things that will trip you up

All of these are real, and none of them produce an obvious error message.

- **Your edit did nothing.** You rebuilt but did not click **Reload**. See
  [the loop](#the-loop).
- **Your node renders an empty code editor.** The bundle failed to load or the
  behavior key does not match, so Curio fell back to the generic editor. Open
  the browser console, where a failed bundle logs a warning.
- **`npm run build:packages`, not `npm run build`.** The package target takes
  seconds; the full app build takes minutes and you do not need it. You never
  need `--force-rebuild` for a package change.
- **Hooks live in your package's `sources/`.** The behaviors under
  `utk_curio/frontend/.../adapters/node/` are Curio's own built-ins, registered
  in `builtinBehaviors.ts`. That is a different mechanism, for behaviors that
  must exist before any package is installed. You do not need it.
- **Never bundle your own React.** React, ReactDOM and ReactFlow are
  externalised to `window`; a second copy breaks every hook with an error that
  does not mention React copies at all.
- **An unregistered `iconRef` is not an error.** It silently falls back to a
  cube with one console warning. The registered refs are in
  [`iconRegistry.ts`](../utk_curio/frontend/urban-workflows/src/registry/iconRegistry.ts).
- **One source file per template.** The manifest's `source` field takes a single
  path, so a template cannot ship helper modules next to it. For a Tier 2 node
  the bundle can import as many files as you like; the limit only applies to
  Tier 1 Python sources.
- **`integrity.json` goes stale.** Regenerate it with
  `python scripts/regen_integrity.py packages/<id>@<major>`. Nothing verifies
  these hashes today, so a stale file will not break your node, but keep it
  honest anyway. On Windows, expect every file to show as changed; that is a
  line-ending artifact, not a real diff.
- **Restart Curio for a new backend blueprint.** Only relevant if your node adds
  Flask endpoints; a frontend-only change never needs a restart, just Reload.

---

## Submitting your package

Export it as a single file. In the left **Tools panel**, open the **Node
Catalog** dropdown (cube icon), find your package's row, and click the
**download** icon ("Export package"). You get `<packageId>@<major>.curio.zip`.

The export button is on that dropdown's package rows, not in the Node Catalog
drawer, which handles adding and removing rather than export.

The archive contains everything on disk except `integrity.json`, which the
installer regenerates on the recipient's machine. That includes `scripts/`, so a
Tier 2 submission carries its compiled bundle and the recipient needs no build
step.

Before you submit, check that the archive works from a clean state: uninstall
your package (**In dataflow → remove**), then re-import the archive
(**Import package** in the drawer footer) and confirm the node still behaves.
That catches the most common packaging mistake: a node that only works because
of a file that never made it into the manifest.

If you built a package under `packages/` and never installed it, there is no
export button for it. Zip it by hand: `manifest.json`, `sources/`, `scripts/`,
`README.md` and `LICENSE` at the **root of the zip**, no wrapper directory, and
leave `integrity.json` out.

To open someone else's submission: **Import package** in the drawer footer. An
id collision is rejected rather than merged, so remove the previous package of
the same id first.

---

## Where to go next

- [NODE-CATALOG.md](NODE-CATALOG.md): how packages are stored, installed,
  versioned, forked, published and shared.
- [EXTENDING.md](EXTENDING.md): the reference for backend blueprints, calling
  external APIs, API-key handling, long-running jobs, dependency declaration.
- [ARCHITECTURE.md](ARCHITECTURE.md): how nodes, descriptors, behaviors and the
  execution pipeline fit together.
- [`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json): every
  field a manifest can declare.
- [QUICK-START.md](QUICK-START.md): if you have not built a dataflow yet, start
  here instead.
