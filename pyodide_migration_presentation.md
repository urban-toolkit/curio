# Curio: Migrating to Pure Client-Side Execution with Pyodide

## Slide 1: Title

**Curio — From Client-Server to In-Browser Execution**
Eliminating backend dependency for data workflows using Pyodide (CPython in WebAssembly)

---

## Slide 2: Problem Statement

**Why migrate?**

- Curio requires a running Flask backend + sandbox server just to execute a single Python cell
- Deployment friction: users must install Python, Flask, and all dependencies locally
- Network latency on every code execution (frontend → backend → sandbox → backend → frontend)
- Backend unavailability = blank screen (infinite spinner bug)
- Goal: Run Python workflows entirely in the browser — zero server required

---

## Slide 3: Current Architecture (Before)

**Three-server setup**

```
Browser (React + ReactFlow)
        │
        ▼
Flask Backend  (:5002)     ← orchestration, provenance DB, file I/O
        │
        ▼
Flask Sandbox  (:2000)     ← isolated Python execution (exec)
        │
Flask UTK      (:5001)     ← 3D geospatial visualization (UTK)
```

**Every code run = 2 HTTP round-trips + disk I/O**

Data files stored as zlib-compressed `.data` files on backend filesystem.

---

## Slide 4: New Architecture (After — Phase 1)

**Single-server (or zero-server) setup**

```
Browser (React + ReactFlow)
        │
        ├── Pyodide (WASM)         ← Python execution in-browser
        │       └── pandas, numpy  ← scientific stack loaded from CDN
        │
        └── In-Memory DataStore    ← Map<"pyodide://uuid", data>
                                      replaces filesystem .data files
```

**Code run = function call in WebWorker — no network**

UTK geospatial boxes still routed to backend (3D rendering requires native libs).

---

## Slide 5: What Changed — Feature by Feature

| Feature | Before | After (Pyodide mode) |
|---|---|---|
| Python execution | Flask sandbox (:2000) | Pyodide WASM in browser |
| Data storage | Zlib `.data` files on disk | `Map<pyodide://uuid, data>` in memory |
| Data fetching | `GET /get?fileName=...` | Direct in-memory lookup |
| Provenance tracking | SQLite via Flask backend | **Skipped** (Phase 2: IndexedDB) |
| User authentication | Google OAuth via backend | **Skipped** (Phase 2) |
| Templates | Fetched from backend DB | Returns empty `[]` |
| Dataset listing | `GET /datasets` | **Skipped** (no filesystem) |
| Vega-Lite save | `POST /insert_visualization` | **Skipped** (local only) |
| UTK 3D maps | UTK server (:5001) | Still uses backend (permanent) |

---

## Slide 6: Key Engineering Changes

**6 files modified + 2 new files created**

1. **`PyodideExecutor.ts`** *(new)* — Singleton executor: loads Pyodide, wraps user code, manages DataStore
2. **`PythonInterpreter.ts`** — Routes to Pyodide or backend based on `PYODIDE_ENABLED` flag
3. **`api.ts`** — Intercepts `pyodide://` paths, returns data from memory instead of network
4. **`index.tsx`** — Preloads Pyodide at app boot in background
5. **`index.html`** — CDN script tag for Pyodide runtime
6. **`ProvenanceProvider.tsx`** — All 7 provenance functions no-op in Pyodide mode
7. **`FlowProvider.tsx`** — Fixed infinite spinner (try/finally guarantees `setLoading(false)`)
8. **`styles.tsx`** — Fixed `JSON.parse` crash when input is already an object

---

## Slide 7: Feature Flag — Zero Breaking Changes

Single environment variable controls everything:

```
PYODIDE_ENABLED=true   → pure browser mode (no backend needed)
PYODIDE_ENABLED=false  → original client-server mode (unchanged)
```

- All backend paths preserved
- No existing functionality removed
- Gradual rollout possible per-user or per-deployment
- Webpack bakes the flag into the bundle at build time

---

## Slide 8: What Works Today

**Verified end-to-end in Pyodide mode:**

- Load Data box: inline pandas DataFrame creation
- Transform/Compute boxes: arbitrary Python with pandas + numpy
- Data flows between nodes via in-memory `pyodide://` references
- Vega-Lite charts render correctly from Pyodide output
- App loads without any backend running (no infinite spinner)
- Box output displayed in node UI

**Demo flow:**
1. Create Load Data box → write inline DataFrame
2. Run (▶) → data stored as `pyodide://uuid`
3. Connect to Vega-Lite box → configure chart grammar
4. Chart renders in browser — no server involved

---

## Slide 9: What Is Still Left

**Phase 2 (Provenance — optional):**
- Replace SQLite provenance with IndexedDB
- Replace template storage with localStorage

**Phase 3 (File I/O):**
- File upload → Pyodide virtual filesystem
- `pd.read_csv('/data/file.csv')` support via Emscripten FS

**Permanent backend (not replaceable):**
- UTK 3D geospatial visualization (requires native C++ libs)
- Multi-user collaboration (shared state)
- Large dataset processing (>500MB — WASM memory limits)

---

## Slide 10: Trade-offs

| Dimension | Client-Server | Pyodide (In-Browser) |
|---|---|---|
| Setup | Install Python + Flask | Open URL — done |
| Execution speed | Fast (native CPython) | ~2-5x slower (WASM) |
| Memory limit | Unlimited (server RAM) | ~2GB (browser tab) |
| Package support | Any pip package | Pyodide-built packages only |
| Offline use | No | Yes |
| Multi-user | Yes (shared backend) | No (isolated tabs) |
| 3D / Geo support | Yes (UTK) | No (still needs server) |
| Data persistence | Filesystem (durable) | In-memory (lost on refresh) |

---

## Slide 11: Recommended Path Forward

**Hybrid model:**

```
┌─────────────────────────────────────┐
│  Pyodide mode (default)             │
│  - Data science workflows           │
│  - No setup required                │
│  - Works offline                    │
├─────────────────────────────────────┤
│  Backend mode (opt-in)              │
│  - UTK 3D geospatial visualization  │
│  - Large datasets                   │
│  - Provenance & collaboration       │
└─────────────────────────────────────┘
```

Ship Pyodide mode as the default experience. Keep backend as an optional power-user feature.

---

## Slide 12: Summary

- **Problem:** Curio required 3 servers to run a single Python cell
- **Solution:** Pyodide — full CPython in WebAssembly, runs in browser
- **Result:** Core data workflows work with zero backend
- **Approach:** Feature-flagged, backward-compatible, no regressions
- **Next:** File upload support + IndexedDB provenance
- **Permanent exception:** 3D geospatial (UTK) stays on server
