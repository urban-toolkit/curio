# Curio Built-in Nodes

`curio.builtin@1` ships with Curio and is auto-installed for every user. Its node kinds are the templates in [manifest.json](manifest.json).

These nodes ship as a manifest package rather than as TypeScript code, using the same registration path third-party packages use. `sources/` holds the code Data Loading, Data Export, Data Summary and Spatial Join open with, and one module, `spatial_join`, whose `spatial_join` function the Spatial Join's code calls; every built-in Python node can import it, and lists it under Functions. Python Computation opens with an empty editor, ready for user code, and Map Editor starts with the code its edits write.

Re-installs happen automatically on every login (the seeder picks the highest installed `curio.builtin@<X>` from the catalog). Don't edit this folder by hand; bump `version` in `manifest.json` and let the seeder propagate.

The agents' prompts describe these templates from `manifest.json`: the backend reads it when it starts, so a template you add or change reaches the agents with no other edit.
