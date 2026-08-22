# Example: Custom UI Node

`curio.example-ui@1`

A minimal, readable example of a node that renders **its own React interface**
instead of Curio's code editor. It exists to be read and forked. It is the
starting point referenced throughout
[docs/AUTHORING-NODES.md](https://github.com/urban-toolkit/curio/blob/main/docs/AUTHORING-NODES.md).

No API keys, no Python dependencies, no backend endpoint of its own.

## The node

| Node | Input | Output | What it does |
|---|---|---|---|
| Column Filter | DataFrame | DataFrame | Pick a numeric column, a comparison and a threshold from controls in the node body. Shows how many rows match as you type, and sends just those rows downstream when you press the button. |

Wire any node that emits a DataFrame into it, such as a Data Loading node running the
snippet from the [quick start](https://github.com/urban-toolkit/curio/blob/main/docs/QUICK-START.md)
is enough.

## What to read

[`sources/columnFilterBehavior.tsx`](sources/columnFilterBehavior.tsx) is the
node. In order, it shows:

1. **The hook contract.** A behavior is a React custom hook that returns the
   parts of the node it wants to override. This one returns only
   `contentComponent`.
2. **`resolveInput`**, reading upstream data. This is the part that catches
   people out: `data.input` is usually a *reference* to a sandbox artifact
   (`{ path: 'art-12', dataType: 'dataframe' }`), not the data. Python and JS
   nodes always produce references; other custom-UI nodes produce inline
   payloads. Handle both or your node will work in testing and do nothing in
   a real dataflow.
3. **Local UI state.** The column, operator and threshold live in `useState`
   and nothing reaches the dataflow until the user presses the button.
4. **Emitting.** `data.outputCallback(nodeId, { data, dataType })` pushes the
   result downstream; `nodeState.setOutput` reports success or failure in the
   node's output panel.

[`sources/index.tsx`](sources/index.tsx) is the bundle entry point: its only
job is calling `registerBehavior('column-filter', useColumnFilterBehavior)`
with a key matching the template's `behavior` field in `manifest.json`.

## Forking it

```bash
python scripts/new_package.py me.mynode --with-ui
```

That scaffolds the same structure under your own package id, then copy across
whatever you want from here.

## Building

The compiled bundle at `scripts/behaviors.js` is committed. After editing
anything under `sources/`, rebuild it:

```bash
cd utk_curio/frontend/urban-workflows
npm run build:packages
```

Then click **Reload** on this package in the catalog drawer's **Installed** tab
so your installed copy picks up the new bundle.

## License

MIT
