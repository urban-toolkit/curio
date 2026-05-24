# Curio Built-in Nodes

`curio.builtin@1` ships with Curio and is auto-installed for every user. It provides the default 14 node kinds:

| Category | Kinds |
|---|---|
| Data | Data Loading, Data Export, Data Transformation, Data Pool, AutkDB |
| Computation | Python Computation, Data Summary, JS Computation, AutkCompute |
| Visualization | Vega-Lite, Simple View, AutkPlot, AutkMap |
| Flow | Merge Flow |

These nodes ship as a manifest pack rather than as TypeScript code — the same registration path third-party packs use. They carry no starter source code: dragging one onto the canvas opens an empty editor, ready for user code.

Re-installs happen automatically on every login (the seeder picks the highest installed `curio.builtin@<X>` from the catalog). Don't edit this folder by hand; bump `version` in `manifest.json` and let the seeder propagate.
