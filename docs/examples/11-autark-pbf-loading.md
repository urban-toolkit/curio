# Autark PBF loading

A single `autk-grammar` node loading OSM layers for Lower Manhattan (Battery Park City + Financial District) from a local `.pbf` file.

## What it demonstrates

- **100 % browser-side PBF parsing**: the backend serves the raw bytes at `GET /file/docs/examples/data/lower_mnt.osm.pbf`; DuckDB-WASM in the browser handles all OSM parsing — no server-side processing.
- **`CURIO_LAUNCH_CWD`-relative data-source URLs**: the spec writes `"pbfFileUrl": "docs/examples/data/lower_mnt.osm.pbf"` — the same path a Python node would read from disk — and the lifecycle prepends `BACKEND_URL` + `/file/` automatically at run time. The `/file/<path>` endpoint resolves the path relative to `CURIO_LAUNCH_CWD`.
- **Full OSM layer stack**: surface, parks, water, buildings, and roads rendered in a single `map` block.

## Nodes

| Node | Type | Role |
|------|------|------|
| PBF grammar | `autk-grammar` | Loads `lower_mnt.osm.pbf`, auto-extracts all five OSM layers, renders them on a WebGPU map |

## Data

`docs/examples/data/lower_mnt.osm.pbf` — pre-extracted OpenStreetMap extract for Lower Manhattan.
