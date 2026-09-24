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
| `v1.5.1/wasm_eh/spatial.duckdb_extension.wasm` | `https://extensions.duckdb.org/v1.5.1/wasm_eh/spatial.duckdb_extension.wasm` | `30cbac25de353ff51d4ea0399ce8a641a850fb83c5e4e7e5c2c0c6e3cad5db88` |
| `v1.5.1/wasm_eh/json.duckdb_extension.wasm` | `https://extensions.duckdb.org/v1.5.1/wasm_eh/json.duckdb_extension.wasm` | `29844ad96567fbc1f05ff1d4d99a22c1e6723ba290e2e83f019f1777beb240f6` |

The layout mirrors the CDN's (`<duckdb version>/<platform>/<name>.wasm`),
because both consumers key off it:

- **Browser** — `utk_curio/frontend/urban-workflows/webpack/duckdbExtensionMirror.js`
  prepends a redirect to duckdb's worker at build time, pointing
  `extensions.duckdb.org` at this directory through the backend's `/file/`
  route. It falls back to the CDN if a requested file is not here.
- **Sandbox (Node)** — `utk_curio/main.py::seed_duckdb_extensions` copies these
  into `~/.duckdb/extensions/extensions.duckdb.org/`, where duckdb-wasm looks
  before downloading.

## Updating after a duckdb-wasm bump

`@duckdb/duckdb-wasm` decides the version in the path. After changing it in
`package.json`, check what the browser asks for (block the CDN in devtools and
read the failing URL, or watch the network tab), then:

```bash
V=v1.5.1   # the version duckdb-wasm asks for
for ext in spatial json; do
  curl -fSL -o "vendor/duckdb-extensions/$V/wasm_eh/$ext.duckdb_extension.wasm" \
    "https://extensions.duckdb.org/$V/wasm_eh/$ext.duckdb_extension.wasm"
done
```

Update `VENDORED_EXTENSION` nowhere — nothing hard-codes the version except
this README: the redirect is path-preserving, and the seeding copies whatever
is here. Until a new version is vendored, both paths fall back to the CDN, so a
bump degrades to the old behaviour rather than breaking.
