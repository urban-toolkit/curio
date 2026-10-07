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
conda install -c conda-forge nodejs=26

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
JavaScript, and you can do the whole thing from the canvas. An agent's
**Solve** runs your node's code in the sandbox to verify it, as it does for the
built-in nodes, with nothing extra to declare.

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
via **Node Catalog → Browse Node Catalog + → Browse all → Add to project**.

### Widgets in a template

A template's starter can read values the user sets in the node's **Widgets** tab
([Widgets](USAGE.md#widgets)). Declare them in the template's `widgets`, and
place each one in the source as `[!! name !!]`:

```json
{
  "id": "roughness",
  "source": "sources/roughness.py",
  "hasWidgets": true,
  "widgets": [
    { "name": "window", "type": "number", "label": "Window size", "default": 5 },
    { "name": "method", "type": "choice", "default": "std", "options": { "choices": ["std", "range"] } }
  ]
}
```

```python
return arg.rolling([!! window !!]).agg([!! method !!])
```

A node dropped from the palette starts with these widgets and their defaults.
**Save as package node…** writes the node's widgets into the template, with the
values it had as the defaults. The shape of each entry is the `widget`
definition in [docs/schemas/node-package.v4.json](schemas/node-package.v4.json).

A node made from a template can also read a view's selection through a
selection tag, `[!! selection name !!]` ([Selection tags](USAGE.md#selection-tags)).
A template does not declare selection tags: each names a view of one dataflow,
so it is added on the canvas, in the node's **Widgets** tab.

The source can also read its input through input chips
([Several inputs](USAGE.md#several-inputs)): `[!! input 0 !!]` is the input,
`[!! input 0.height !!]` a column's name, and `[!! input 0:table_osm_roads !!]`
one layer of the several an Autark node hands on, as a GeoDataFrame in Python
and a FeatureCollection in JavaScript:

```python
roads = [!! input 0:table_osm_roads !!]
return roads[roads["highway"] == "primary"]
```

This code also takes a single roads GeoDataFrame, from a Python node or Data
Loading: an input that is one frame with no layer name is the layer. The same
holds in a Vega-Lite or Autark spec, where the chip becomes the name the frame
is read by, `"input_0"`.

### Modules beside your template

A template can import Python modules that ship in the package's `sources/`
folder, with ordinary `import` statements:

```
packages/me.heights@1/
├── manifest.json                  # "source": "sources/caller.py"
└── sources/
    ├── caller.py
    └── building_height/
        ├── __init__.py
        └── convert_to_raster.py
```

```python
from building_height.convert_to_raster import convert_raster

return convert_raster(arg, zoom=[!! zoom !!])
```

- A module is a `.py` file, or a folder of `.py` files, directly in `sources/`,
  named like a Python identifier. The files your templates name as their
  `source` are not modules.
- Modules import each other by name or relatively (`from .scale import FACTOR`).
- They are importable while a node of your package runs, or a node of a
  package that names yours in `manifest.dependencies.packages`, and by no
  other node. A new version of the package takes effect on the next run.
- **New node from a Python function** in the Node Catalog drawer writes a
  template that calls one of their functions
  ([Node Catalog](NODE-CATALOG.md#new-node-from-a-python-function)).
- **One name, one package.** Two installed packages cannot ship a module of the
  same name: installing the second is refused, and the message names both
  packages and the module. Name a module after your package
  (`heights_raster/`), not `scripts/` or `utils/`. Two majors of one package may
  keep the same names.
- A module named like a library the node already has loaded (`json`, `pandas`)
  is refused when the node runs.
- Imports inside your modules are not detected: list the libraries they need in
  `manifest.dependencies.python`.

---

## Tier 2: a node with its own interface

A custom-UI node replaces the code editor with controls you write: a React hook
that renders JSX inside the node body, reads upstream data, and pushes results
downstream.

> [!IMPORTANT]
> **Save as package node cannot do this.** A new package it builds carries
> `manifest.json` and `sources/`, never the compiled bundle a custom UI needs.
> So the in-canvas flow always produces a code-editor node, and forking a
> custom-UI package that way loses its interface. Saving into an existing
> package keeps its bundle. Tier 2 has to be authored from files.

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
#   first time:  Node Catalog -> Browse Node Catalog + -> Browse all -> Add to project
#   after that:  reload the page
```

Curio serves your node's bundle from your *installed copy* in the user store,
not from `packages/`. Opening a dataflow, which a page reload does, replaces
that copy with the one in `packages/` when the files there changed and you have
not edited the installed copy yourself.

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
from any real Curio DataFrame: it has nothing to render and nothing to throw,
so it shows its "connect something upstream" hint forever. Read a cell
through a helper rather than indexing directly:

```js
const cell = (column, key) => (Array.isArray(column) ? column[Number(key)] : column[key]);
```

A `geodataframe` payload is a GeoJSON `FeatureCollection` with three extra
keys the sandbox adds, and one rule about `properties` that is easy to miss:

```js
{
  "type": "FeatureCollection",
  "features": [
    { "type": "Feature",
      "geometry": { "type": "Polygon", "coordinates": [...] },   // the ACTIVE column
      "properties": { "zip": "60601",
                      "centroid": { "type": "Point", ... } } }   // everything else
  ],
  "crs": { "type": "name", "properties": { "name": "urn:ogc:def:crs:EPSG::4326" } },
  "geometry_name": "geom"     // the active geometry column's pandas name, or null
}
```

- **`geometry_name`** is the active geometry column's real name. It is not
  always `"geometry"` - `gdf.rename_geometry("geom")` is legal and common - so
  read this rather than assuming. It is `null` when the frame has no active
  geometry column at all.
- **The active column is excluded from `properties`.** geopandas puts it in
  `feature.geometry` instead, which is why a geometry column can keep its own
  name without ever colliding with a real property of the same name.
- **Secondary geometry columns are ordinary properties**, carrying a GeoJSON
  geometry *object* (the `__geo_interface__` mapping), not a `Feature` and not
  WKT. A frame with `gdf["centroid"] = gdf.centroid` has two geometry columns
  and only the first is in `feature.geometry`.
- **`crs`** is absent when the frame has no CRS.

Both payload kinds also carry a top-level **`schema`** alongside `dataType`:
a `{column: dtype}` map straight from `df.dtypes`, e.g.
`{"zip": "str", "pop": "int64", "geom": "geometry"}`. Read it rather than
sniffing values. pandas 3 reports a string column as `"str"` where pandas 2
said `"object"`, so accept both.

A GeoDataFrame with **no active geometry column** arrives as a `dataframe`,
not an empty `geodataframe`.

---

### Pre-filling your editor from the input

A grammar node can offer a starter spec once it knows what the data looks like.
The hook is `defaultValueOverride` in your behavior, which
[`UniversalNode`](../utk_curio/frontend/urban-workflows/src/components/UniversalNode.tsx)
gives top priority in the `defaultValue` chain.
[`useStarterSpec`](../utk_curio/frontend/urban-workflows/src/hook/useStarterSpec.ts)
does the gating for you: it fills only an empty editor, at most
once, only after an input has arrived, and never over `data.defaultCode`. Give
it a reader and a ladder; `vegaBehavior.ts` and `autkGrammarBehavior.tsx` are
the worked examples.

## Things that will trip you up

All of these are real, and none of them produce an obvious error message.

- **Your edit did nothing.** You rebuilt but did not reload the page, or you
  edited the installed copy in the user store, which Curio then keeps as yours.
  See [the loop](#the-loop).
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
- **`integrity.json` goes stale.** Regenerate it with
  `python scripts/regen_integrity.py packages/<id>@<major>`. Nothing verifies
  these hashes today, so a stale file will not break your node, but keep it
  honest anyway. On Windows, expect every file to show as changed; that is a
  line-ending artifact, not a real diff.
- **Restart Curio for a new backend blueprint.** Only relevant if your node adds
  Flask endpoints; a frontend-only change never needs a restart, just a page
  reload.

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
your package (**Remove from project** on its **In project** card), then re-import the archive
(**Import package** in the drawer footer) and confirm the node still behaves.
That catches the most common packaging mistake: a node that only works because
of a file that never made it into the manifest.

To open someone else's submission: **Import package** in the drawer footer. An
archive whose `<packageId>@<major>` you already have is refused.

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
