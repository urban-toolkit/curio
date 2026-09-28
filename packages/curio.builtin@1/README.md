# Curio Built-in Nodes

`curio.builtin@1` ships with Curio and is auto-installed for every user. Its node kinds are the templates in [manifest.json](manifest.json).

These nodes ship as a manifest package rather than as TypeScript code, using the same registration path third-party packages use. They carry no starter source code: dragging one onto the canvas opens an empty editor, ready for user code.

Re-installs happen automatically on every login (the seeder picks the highest installed `curio.builtin@<X>` from the catalog). Don't edit this folder by hand; bump `version` in `manifest.json` and let the seeder propagate.

The agents' shared preamble describes these templates from `manifest.json`. After changing a template, run `python scripts/generate_contracts.py` and commit the regenerated `utk_curio/llm-prompts/default_preamble.txt` with it.
