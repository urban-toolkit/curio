# DuckDB extensions, vendored

DuckDB's wasm build downloads extensions at run time from
`https://extensions.duckdb.org/`. autk-db's `init()` runs
`INSTALL spatial; LOAD spatial;`, and DuckDB autoloads `json` for the grammar's
`json_object` SQL, so **every** Autark run used to pull ~24 MB over the network
before a map could draw — once per grammar run in the browser, and once per
cold container in the sandbox. A CDN blip failed the node (#318), and an
air-gapped install could not run an Autark node at all.

These are the exact files that CDN serves, so Curio serves them itself:

| File | Source | SHA-256 |
|---|---|---|
| `v1.5.4/wasm_eh/spatial.duckdb_extension.wasm` | `https://extensions.duckdb.org/v1.5.4/wasm_eh/spatial.duckdb_extension.wasm` | `ccb0599b7203d4b9e4b551421a5685f0a7c988fc762ffafd98dabe1f01934971` |
| `v1.5.4/wasm_eh/json.duckdb_extension.wasm` | `https://extensions.duckdb.org/v1.5.4/wasm_eh/json.duckdb_extension.wasm` | `993b19f7929cc305b2529c548f2842e8e7a5b112d1c88f31c84798b51901ca16` |

`@duckdb/duckdb-wasm` 1.33.1-dev57.0 runs DuckDB v1.5.4.

The layout mirrors the CDN's (`<duckdb version>/<platform>/<name>.wasm`),
because both consumers key off it:

- **Browser** — `utk_curio/frontend/urban-workflows/webpack/duckdbExtensionMirror.js`
  prepends a redirect to duckdb's worker at build time, pointing
  `extensions.duckdb.org` at this directory through the backend's `/file/`
  route. It falls back to the CDN if a requested file is not here.
- **Sandbox (Node)** — `utk_curio/cli/dependencies.py::seed_duckdb_extensions` copies these
  into `~/.duckdb/extensions/extensions.duckdb.org/`, where duckdb-wasm looks
  before downloading.

## Updating after a duckdb-wasm bump

`@duckdb/duckdb-wasm` decides the version in the path: the DuckDB version it
runs. `test_seed_duckdb_extensions.py` asks the installed duckdb-wasm for it
(`SELECT library_version FROM pragma_version()`) and fails, naming that
version, until it is vendored here. It also checks that the frontend and the
repository lockfiles pin the same duckdb-wasm. After a bump, vendor the version
the failing test names, and delete the old one:

```bash
V=v1.5.4   # the version duckdb-wasm runs
for ext in spatial json; do
  curl -fSL -o "vendor/duckdb-extensions/$V/wasm_eh/$ext.duckdb_extension.wasm" \
    "https://extensions.duckdb.org/$V/wasm_eh/$ext.duckdb_extension.wasm"
done
```

Update `VENDORED_EXTENSION` nowhere — nothing hard-codes the version except
this README: the redirect is path-preserving, and the seeding copies whatever
is here. Until a new version is vendored, both paths fall back to the CDN, so a
bump degrades to the old behaviour rather than breaking.
