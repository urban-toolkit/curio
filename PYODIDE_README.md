# Curio — Client-Side Execution via Pyodide

**Branch:** `shubham/pyodide-migration`  
**Feature flag:** `PYODIDE_ENABLED=true`

---

## What this feature does

Curio originally requires three running servers: a backend (Flask, port 5002), a Python sandbox (port 2000), and UTK (port 5001). This makes the tool hard to demo, share, or run offline.

This branch migrates the Python execution layer from the backend sandbox to **Pyodide** — CPython compiled to WebAssembly — so that pandas/numpy workflows run entirely inside the browser. When the feature flag is on, no server infrastructure is needed for standard data analytics workflows.

---

## How to enable it

In `utk_curio/frontend/urban-workflows/.env`, set:

```
PYODIDE_ENABLED=true
BACKEND_URL=http://localhost:5002    # still used for VIS_UTK boxes; ignored otherwise
```

Then start only the frontend:

```bash
cd utk_curio/frontend/urban-workflows
npm install
npm start
```

The app is fully functional for data loading, transformation, computation, and Vega-Lite visualizations without the backend or sandbox running.

---

## Architecture comparison

### Before (client-server)

```
Browser
  └─ user clicks ▶
       └─ POST /processPythonCode ──► Backend sandbox (port 2000)
                                           └─ runs Python
                                           └─ writes result to server FS
       └─ GET /get?fileName=... ──────► Backend (port 5002)
                                           └─ reads file, returns JSON
  └─ VegaBox / downstream node renders
```

### After (Pyodide mode)

```
Browser
  └─ user clicks ▶
       └─ PyodideExecutor.execute(code, input)
            └─ runs Python via CPython/WASM
            └─ stores result in in-memory Map  ← pyodide://timestamp_hash
  └─ fetchData("pyodide://...")
       └─ reads from in-memory Map (no network)
  └─ VegaBox / downstream node renders
```

The `pyodide://` URI is the handoff point. Upstream nodes write to the Map; downstream nodes read from it via the same `fetchData()` call they use in server mode.

---

## Key files changed

| File | What changed |
|------|-------------|
| `src/services/PyodideExecutor.ts` | **New.** Singleton that loads Pyodide, exposes a virtual filesystem at `/data/`, runs user code inside a wrapper, stores results in-memory |
| `src/PythonInterpreter.ts` | Routes execution to Pyodide or backend based on `PYODIDE_ENABLED` and box type |
| `src/services/api.ts` | `fetchData()` intercepts `pyodide://` paths and serves from in-memory store instead of making a network request |
| `src/services/IndexedDBFiles.ts` | **New.** Persists uploaded files across page refreshes (Pyodide's virtual FS is wiped on reload) |
| `src/services/IndexedDBProvenance.ts` | **New.** Persists provenance (execution history) per box across page refreshes |
| `src/index.tsx` | Preloads Pyodide at app boot so it's ready before the user runs anything |
| `src/index.html` | Adds Pyodide CDN `<script>` tag |
| `src/providers/ProvenanceProvider.tsx` | All 7 provenance functions skip backend calls and write to IndexedDB instead |
| `src/providers/UserProvider.tsx` | Skips `/getUser` session restoration on startup |
| `src/providers/templates.ts` | Returns `[]` instead of fetching `/templates` |
| `src/providers/TemplateProvider.tsx` | User-created templates persisted to `localStorage` instead of backend |
| `src/components/menus/datasets/DatasetsWindow.tsx` | Lists files from Pyodide's virtual FS instead of `/datasets` endpoint |
| `src/components/VegaBox.tsx` | Skips `/insert_visualization` and `/insert_interaction` logging; fixed `JSON.parse` type guard |

---

## File upload and persistence

Because Pyodide's virtual filesystem is in-memory (and reset on page load), uploaded files are also saved to **IndexedDB** (`curio_files` database). On the next page load, `PyodideExecutor.load()` reads all stored files from IndexedDB and writes them back into `/data/`, so user code like `pd.read_csv('/data/myfile.csv')` works across sessions.

### How to upload a file

Use the upload button in the toolbar. The file is written to both Pyodide's virtual FS (`/data/<filename>`) and IndexedDB. It appears in the **Available Datasets** panel and can be referenced in any code box via its `/data/<filename>` path.

### Clearing files

The Datasets panel shows a **Clear All Files** button in Pyodide mode that removes all files from both the virtual FS and IndexedDB.

---

## Provenance in Pyodide mode

In server mode, every code execution is recorded in a backend database and the provenance graph is fetched back. In Pyodide mode, execution records are appended to IndexedDB (`curio_provenance` database) instead. The BoxProvenance panel reads from the same in-memory state that is rebuilt from IndexedDB on mount, so execution history is preserved across page refreshes.

---

## What still runs on the backend

| Feature | Status |
|---------|--------|
| Standard Python (pandas, numpy) | Client-side via Pyodide |
| File upload + `/data/` access | Client-side via IndexedDB + virtual FS |
| Vega-Lite visualizations | Client-side |
| User-created templates | Client-side via localStorage |
| Provenance tracking | Client-side via IndexedDB |
| **VIS_UTK (3D urban rendering)** | **Backend only** — requires geopandas/rasterio |
| **geopandas, rasterio, GDAL** | **Not available** — no GDAL in Pyodide |
| **LLM / AI assistant** | **Backend only** — calls `/openAI` endpoint |

---

## Known limitations

- **No geopandas / rasterio**: Pyodide does not ship GDAL, so geospatial libraries that depend on it are unavailable. Workflows using `geopandas.read_file()` or UTK-specific geospatial operations must use server mode.
- **VIS_UTK boxes always use the backend**: The 3D UTK visualization box is hardcoded to the backend path and is unaffected by the feature flag.
- **LLM provider not gated**: The AI assistant still calls the backend even when `PYODIDE_ENABLED=true`.
- **Default templates empty**: The `/templates` endpoint is not called in Pyodide mode, so the default template library is unavailable. User-created templates work and persist via localStorage.
- **First load is slow**: Pyodide downloads ~30 MB from CDN on first use. Subsequent loads are served from browser cache.

---

## Design decisions and tradeoffs

**Why a feature flag instead of a full migration?**  
VIS_UTK and geopandas workflows cannot run in Pyodide (no GDAL). A flag lets both modes coexist in the same codebase so server-mode users are unaffected.

**Why store results in a Map with `pyodide://` URIs instead of, say, React state?**  
Downstream nodes already call `fetchData(path)` to retrieve their input. Intercepting that single call based on the URI prefix meant zero changes to downstream node logic — VegaBox, DataTable, ImageBox all read data the same way regardless of where it was produced.

**Why IndexedDB for file persistence instead of, say, sessionStorage?**  
Uploaded files can be many megabytes. IndexedDB stores binary data (Uint8Array) without serialisation overhead and has no meaningful size limit, unlike localStorage or sessionStorage.

**Why preload Pyodide at boot (index.tsx) rather than on first execution?**  
Loading Pyodide takes a few seconds. Preloading at boot hides that latency behind the time the user spends reading the UI, so clicking ▶ feels instant.
