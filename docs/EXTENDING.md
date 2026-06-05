# Extending Curio with new node packages

Curio nodes are defined by **packages**, not by code. A package is a directory under [`packages/`](../packages/) that ships a `manifest.json` declaring one or more node *templates*. Each template references a **lifecycle key** that resolves to a React hook implementing the node's behaviour. Optionally, a package can ship a backend Flask blueprint for endpoints the lifecycle hook calls.

This guide walks through adding a new node package end-to-end, using the recent [`curio.streetvision@1`](../packages/curio.streetvision@1/) package — which adds three CV nodes plus a generic Spatial Join — as the worked example. The merge that introduced it is a fairly involved case: it spans the manifest, four lifecycle hooks, a Flask blueprint with eight endpoints, per-package Python dependencies declared in `manifest.dependencies.python`, and a user-facing docs example. Easier packages can skip several of the steps below.

## 1. Anatomy of a package

```
packages/<packageId>@<major>/
├── manifest.json   ← declares templates, ports, lifecycle keys, deps
├── integrity.json  ← sha256 of every other file (regen on every edit)
├── README.md       ← shown in the catalog UI
└── sources/        ← optional Python / JS template starters per template
```

A `template` inside `manifest.json` declares one node kind. It carries:

- `id` + `label` + `description` + `iconRef` — palette presentation
- `category` (`data` | `computation` | `vis_grammar` | `vis_simple` | `flow`) — palette sectioning
- `inputPorts` + `outputPorts` — port types and cardinalities (see [`docs/schemas/node-package.v3.json`](schemas/node-package.v3.json))
- `editor` (`code` | `widgets` | `grammar` | `none`) — what editor surface to mount
- `lifecycle` — string key resolved through [`registry/lifecycleRegistry`](../utk_curio/frontend/urban-workflows/src/registry/lifecycleRegistry.ts) to the React hook that implements the node's behaviour
- `engine` (`python` | `javascript`) — if the node runs user code, which sandbox executes it

The frontend's package loader at [`registry/packagesClient.ts`](../utk_curio/frontend/urban-workflows/src/registry/packagesClient.ts) reads every installed package, calls `buildDescriptor()` per template, and registers them in the canvas's node-type registry. Adding a node is therefore *adding a manifest entry plus a lifecycle hook* — there is no monolithic switch-case anywhere.

## 2. When you do — and don't — need a backend blueprint

Three patterns cover essentially every node Curio ships:

| Pattern | Examples | Backend? |
|---|---|---|
| **Pure-frontend** | `vis-vega`, `vis-simple`, `autk-grammar`, `cv-gallery` | None. The lifecycle hook does its work in the browser. |
| **Sandbox-Python** | `data-loading`, `data-transformation`, `computation-analysis`, `data-summary` | Reuses Curio's existing code sandbox at [`utk_curio/sandbox/`](../utk_curio/sandbox/) via the `code` lifecycle. User-provided Python runs out-of-process. |
| **Custom blueprint** | `streetvision` (calls Google Street View + HuggingFace + runs `torch` inference), `spatial-join` (shapely STRtree) | A new Flask blueprint under [`utk_curio/backend/app/<feature>/`](../utk_curio/backend/app/). Right call when the node needs external APIs, long-running jobs, persistent state, or heavy native dependencies that the sandbox can't reasonably ship. |

Pure-frontend is the right default; reach for the sandbox before a blueprint, and only stand up a blueprint when neither covers it.

## 3. Connecting to external services

Most non-trivial node packages need to call a third-party API. The Street Vision package touches three — HuggingFace Hub (model search), Nominatim (geocoding), and Google Street View (imagery, behind an API key). The patterns below are the conventions the merged code follows, all in [`utk_curio/backend/app/streetvision/services/`](../utk_curio/backend/app/streetvision/services/).

### 3.1 Always proxy through the backend

Never call third-party APIs from the lifecycle hook directly:

1. **API keys leak.** Anything built into the frontend bundle — even read-at-runtime values — is visible in DevTools' network tab.
2. **CORS.** Most public APIs (Google, Nominatim) reject browser-origin requests.
3. **Rate-limit hygiene.** Centralising in the backend lets you add caching, retries, and per-user quota in one place.

The lifecycle hook hits `${BACKEND_URL}/api/<feature>/...`; the Flask handler in turn calls the upstream service. See [`streetvision/routes.py`](../utk_curio/backend/app/streetvision/routes.py) for the pattern.

### 3.2 API keys: per-session input on the node (preferred) vs env vars

Curio supports two patterns for third-party API keys; pick by who the key belongs to:

- **Per-user secrets** (Google Maps, Mapbox, OpenAI personal keys, …) → make it a **text input on the node itself**, held in React state for the session. The lifecycle hook passes it to the backend as a request-body field. Never persist to the dataflow spec (it would leak when shared) or to `localStorage` (it would survive logout). The Street View Fetcher node is the worked example — see [`streetViewFetcherLifecycle.tsx`](../packages/curio.streetvision@1/sources/streetViewFetcherLifecycle.tsx) and the `api_key` body field in [`streetvision/routes.py`](../utk_curio/backend/app/streetvision/routes.py).

- **Operator-wide secrets** that every user of a deployment shares (an internal data-source token, a back-of-house HuggingFace token) → keep using `os.environ.get(...)` at the backend, read at request time so editing `.env` + restart picks it up without rebuilding. The Street Vision blueprint still does this for `HUGGINGFACE_TOKEN` because gated-model access is the operator's concern, not the user's.

For the operator pattern, surface presence in `/health` so the frontend can warn the user before they trigger an action that needs the key:

```python
@bp.get("/health")
def health():
    return jsonify({
        "status": "healthy",
        "has_huggingface_token": bool(os.environ.get("HUGGINGFACE_TOKEN")),
    })
```

Document the env var in the package's `README.md` and in the user-facing example doc. Never check secrets into git.

### 3.3 Public APIs without auth

HuggingFace Hub's model search and Nominatim's geocoder are free and public — just use `requests`:

```python
# huggingface.py
from huggingface_hub import HfApi
def search_models(task: str, query: str, limit: int = 20):
    api = HfApi()
    return [...]  # api.list_models(filter=task, search=query, sort='downloads', limit=limit)
```

Always set a **timeout** (`requests`'s default is "wait forever"). Always check the response status. Nominatim has a strict 1 req/sec rate limit and requires a `User-Agent` header that identifies your app — read their usage policy before shipping a node that hits them in a tight loop, and **cache aggressively** (a single user might re-search the same place a dozen times in one session).

### 3.4 APIs with API keys

For per-user keys (the recommended pattern — see 3.2), take the key as a body field and treat it as required:

```python
# routes.py
@bp.post("/data/streetview/coverage")
def streetview_coverage():
    body = request.get_json(silent=True) or {}
    api_key = (body.get("api_key") or "").strip()
    if not api_key:
        return jsonify({
            "error": "Google Maps API key required",
            "hint": "Enter your Google Maps API key in the Street View Fetcher node",
        }), 400
    # ... call streetview.fetch_panorama(..., api_key=api_key)
```

The lifecycle hook holds the key in React state and sends it in the request body:

```tsx
// streetViewFetcherLifecycle.tsx
const [apiKey, setApiKey] = useState('');
// ... <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} />
fetch(`${API_BASE}/data/streetview/coverage`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ bbox, api_key: apiKey }),
});
```

Endpoints that need the key should return a **400 / 503 with a hint** when it's missing — not crash with a stacktrace. The frontend renders that hint inline so the user knows exactly what to do.

### 3.5 Long-running calls — job-id polling

Inference, batch downloads, or any external call that takes more than a few seconds shouldn't hold a connection open. The streetvision pattern, in [`streetvision/jobs.py`](../utk_curio/backend/app/streetvision/jobs.py):

1. `POST /inference/run` returns `{ job_id }` immediately and spawns a `threading.Thread` that does the work and writes progress into a module-level dict guarded by a lock.
2. The frontend polls `GET /inference/results/<job_id>` every ~2 s, reads `{ status, processed, total_images, results }`, and renders a progress bar.
3. On `status === "completed"`, the lifecycle hook pulls the results and pushes them downstream via `data.outputCallback(...)`.

The job store is in-memory. Restarting Curio loses any in-flight jobs — fine for typical interactive use, document it in the package README. If you genuinely need durability (multi-hour jobs, multi-process workers), reach for SQLite or Redis, but most node packages don't.

### 3.6 Caching expensive responses

[`streetvision/services/cache.py`](../utk_curio/backend/app/streetvision/services/cache.py) stores fetched Street View images under `instance/streetvision_cache/` so re-running with the same bbox doesn't re-hit Google (and re-bill the user). Pattern:

- Cache key = hash of the request inputs (e.g., `pano_id + size`).
- TTL: forever for immutable content (an image at a coordinate); a few hours for content that changes (model lists).
- Store under `instance/<package-name>_cache/` so it lives alongside Curio's other ephemeral state (gitignored).

### 3.7 The error contract back to the frontend

| HTTP | Meaning | Lifecycle reaction |
|---|---|---|
| `200` | OK | Render the result |
| `400` | Bad input (missing field, malformed body) | Surface inline message |
| `503` | Service / extras unavailable | Show "install hint" / "backend offline" banner |
| `5xx` | Unhandled backend error | Generic "Lost connection to backend" toast |

Always return JSON bodies with `{ "error": "...", "hint": "..." }` for non-200 responses; the frontend reads `hint` to give the user an actionable next step. Don't return plain-text 500s.

### 3.8 Per-package Python dependencies

Curio's `requirements.txt` / `pyproject.toml::dependencies` carries **only** the framework — what the backend + sandbox Flask apps need at module load (Flask, SQLAlchemy, requests, the LLM SDKs, etc.). **Every node package** ships its own data-ops libs in its manifest's `dependencies.python` — including the bundled `curio.builtin@1` (pandas, geopandas, rasterio, etc.) and the optional `curio.streetvision@1` (torch, transformers, ...). The `curio start` launcher walks every installed manifest at startup, merges them into a single conflict-aware union, and pip-installs the result before booting the subprocesses. See [`main.py::install_manifest_dependencies`](../utk_curio/main.py) for the walker.

Declare your package's deps in `manifest.dependencies.python`:

```json
{
  "id": "curio.streetvision",
  "dependencies": {
    "python": {
      "torch": ">=2.0",
      "transformers": ">=4.30",
      "ultralytics": ">=8.0",
      "huggingface_hub": ">=0.20"
    },
    "js": {},
    "packages": {}
  }
}
```

Accepted spec syntax: PEP 440 comparators (`>=2.0`, `~=4.30`, `==1.5.0`, `!=2.0`), bare versions (`1.2.3` → treated as `==1.2.3`), npm-style carets (`^0.14` → rewritten to `~=0.14`), or empty string for "latest".

#### How the install/uninstall flow handles them

- **Catalog Install** copies the package files, then runs `pip install` (via [`utk_curio/backend/app/packages/pip_runner.py`](../utk_curio/backend/app/packages/pip_runner.py)) for every dep that isn't already importable. Already-satisfied deps are skipped — re-installs of the same package are near-instant. The install request blocks until pip finishes (v1 sync UX); the Install button stays busy.
- **Uninstall** (when a package's user-store copy is being pruned) walks every other still-installed package's manifest, finds the python deps the pruned package declared that **no other package needs**, and pip-uninstalls those. Shared deps stay.
- A failed pip install rolls back the package's user-store copy so the user can retry cleanly. The Flask response carries the tail of pip's stderr so the user knows what failed (network error, version conflict, missing wheel, etc.).

#### When to still lazy-import

Even though deps are installed up front, lazy-import expensive libraries inside the route handler that needs them so a broken install fails per-request with a clean 503 instead of crashing the backend on startup:

```python
@bp.post("/inference/run")
def inference_run():
    try:
        from .services.inference import run_batch  # lazy import
    except ImportError as e:
        return jsonify({
            "error": f"streetvision dependency unavailable: {e}",
            "hint": "Reinstall the Street Vision package from /catalog",
        }), 503
    # ...
```

## 4. Walked example: the Street Vision package

The merge of [PR #120](https://github.com/urban-toolkit/curio/pull/120) decomposed two large student-contributed nodes into four small reusable ones and ported a companion FastAPI service into Curio's Flask backend. The artefacts that landed:

### 4.1 Three templates in [`packages/curio.streetvision@1/manifest.json`](../packages/curio.streetvision@1/manifest.json)

```jsonc
"templates": [
  { "id": "street-view-fetcher", "lifecycle": "street-view-fetcher",
    "inputPorts": [],                                                  "outputPorts": [{"types":["GEODATAFRAME"]}] },
  { "id": "hf-cv-inference",     "lifecycle": "hf-cv-inference",
    "inputPorts": [{"types":["GEODATAFRAME","JSON"]}],                 "outputPorts": [{"types":["JSON"]}] },
  { "id": "cv-gallery",          "lifecycle": "cv-gallery",
    "inputPorts": [{"types":["JSON"]}],                                "outputPorts": [{"types":["GEODATAFRAME"]}] }
]
```

Each entry names a *lifecycle key* (a string), not a JS module path — the same key can be implemented by an entirely different package and still work, which is how forks / overrides happen.

### 4.2 Plus a fourth template in [`packages/curio.builtin@1/manifest.json`](../packages/curio.builtin@1/manifest.json)

A generic Spatial Join that takes points + polygons and tags each point with the containing polygon's properties:

```jsonc
{ "id": "spatial-join", "lifecycle": "spatial-join",
  "inputPorts": [
    {"types":["GEODATAFRAME"]},   // points (handle 0 — top of node)
    {"types":["GEODATAFRAME"]}    // polygons (handle 1 — bottom of node)
  ],
  "outputPorts": [{"types":["GEODATAFRAME"]}]
}
```

This one belongs in `curio.builtin@1`, not `curio.streetvision@1`, because it's reusable for any spatial workflow. Generally: if a capability is reusable outside the package's narrow theme, factor it out into builtin.

### 4.3 Four lifecycle hooks in [`utk_curio/frontend/urban-workflows/src/adapters/node/`](../utk_curio/frontend/urban-workflows/src/adapters/node/)

- [`streetViewFetcherLifecycle.tsx`](../utk_curio/frontend/urban-workflows/src/adapters/node/streetViewFetcherLifecycle.tsx) — place picker + bbox preview + fetch button. Hits `/api/streetvision/data/streetview/{search_place,coverage,fetch}`, emits a GEODATAFRAME via `data.outputCallback`.
- [`hfCvInferenceLifecycle.tsx`](../utk_curio/frontend/urban-workflows/src/adapters/node/hfCvInferenceLifecycle.tsx) — reads upstream image points from `data.input`, runs an inference job, polls `/api/streetvision/inference/results/<id>`. Demonstrates the long-running job pattern from §3.5.
- [`cvGalleryLifecycle.tsx`](../utk_curio/frontend/urban-workflows/src/adapters/node/cvGalleryLifecycle.tsx) — pure frontend node. Gallery + per-image inspector + aggregate stats; re-emits the results as a GEODATAFRAME.
- [`spatialJoinLifecycle.tsx`](../utk_curio/frontend/urban-workflows/src/adapters/node/spatialJoinLifecycle.tsx) — the only node here with two distinct input handles, mounted via `dynamicHandles` (the same mechanism Merge Flow uses). Worth reading if you ever need a 2-input node.

Each is registered as a global lifecycle key in [`registry/builtinLifecycles.ts`](../utk_curio/frontend/urban-workflows/src/registry/builtinLifecycles.ts):

```typescript
registerLifecycle('street-view-fetcher', useStreetViewFetcherLifecycle);
registerLifecycle('hf-cv-inference',     useHfCvInferenceLifecycle);
registerLifecycle('cv-gallery',          useCvGalleryLifecycle);
registerLifecycle('spatial-join',        useSpatialJoinLifecycle);
```

Even though three of those templates live in a separate (non-built-in) package, their lifecycle hooks are registered globally — packages reference lifecycle keys by name, not by import.

### 4.4 The backend Flask blueprint at [`utk_curio/backend/app/streetvision/`](../utk_curio/backend/app/streetvision/)

```
streetvision/
├── __init__.py     # bp = Blueprint("streetvision", __name__)
├── routes.py       # 8 endpoints (health, models/search, search_place,
│                   #              coverage, fetch, inference/run,
│                   #              inference/results, inference/overlay)
├── jobs.py         # threading-based job store (§3.5)
└── services/
    ├── huggingface.py   # search_models + lazy load_model
    ├── streetview.py    # Google API client (§3.4)
    ├── inference.py     # torch + transformers (lazy-imported)
    └── cache.py         # on-disk image cache (§3.6)
```

Registered next to the other blueprints in [`utk_curio/backend/app/__init__.py`](../utk_curio/backend/app/__init__.py):

```python
from utk_curio.backend.app.streetvision import bp as streetvision_bp
app.register_blueprint(streetvision_bp, url_prefix="/api/streetvision")
```

Spatial Join is simpler: a single handler at the end of [`api/routes.py`](../utk_curio/backend/app/api/routes.py) (`POST /spatial_join`) that calls a generic helper at [`utk_curio/backend/app/common/spatial.py`](../utk_curio/backend/app/common/spatial.py). Reusable utilities like that belong under `common/`, not in any specific blueprint.

### 4.5 Shipping the package

The Street Vision package is bundled in-repo under [`packages/`](../packages/) but **not auto-installed** (`readOnly: true`, but no `factoryInstall` entry). Users opt in by clicking *Install* in the catalog. Generally:

- **Bundled-and-auto-installed** → only for `curio.builtin@1`. Anything every user must have.
- **Bundled-and-installable** → optional first-party packages like `curio.streetvision@1`, `ai.urbanlab.uhvi@1`. Visible in the catalog without a remote registry roundtrip.
- **Remote** → publishing through Curio's catalog endpoint, for third-party packages. Same manifest schema.

### 4.6 How lifecycle distribution works (and why)

When you install a package that ships its own custom node UIs, Curio needs to find a way to load the lifecycle JavaScript without rebuilding the main app. The mechanism in place today:

1. **The package directory contains both the manifest *and* a pre-built `scripts/lifecycles.js`.** For first-party packages (in-repo), `npm run build` produces that JS via [`webpack.packages.config.js`](../utk_curio/frontend/urban-workflows/webpack.packages.config.js). Third-party authors compile their own. The bundle lives under `scripts/` because that subdirectory is one of the archive validator's allowed top-level dirs (see [`installer.py::_ALLOWED_TOP_DIRS`](../utk_curio/backend/app/packages/installer.py)), so the bundle survives the catalog install round-trip.
2. **The manifest declares the bundle via `lifecycleScript: "scripts/lifecycles.js"`** (a top-level field, not per-template). The path is relative to the package directory; any allowed-subdirectory location works.
3. **At app boot, the frontend's `loadInstalledPackages` fetches `/api/packages/<dirName>/file/scripts/lifecycles.js` with the user's Bearer token and injects the response body as an inline `<script>` BEFORE building descriptors**. (A plain `<script src>` can't carry an `Authorization` header, so Firefox's OpaqueResponseBlocking would reject the `require_auth` 401 response — the inline-injection path bypasses that.) The bundle's top-level side-effect calls `window.curio.registerLifecycle(...)` for each lifecycle hook it ships. By the time `buildDescriptor` looks up `getLifecycle('street-view-fetcher')`, the key is registered.

   The bundle reads its backend URL at runtime from `window.curio.backendUrl` (exposed by Curio's main bundle in [`src/registry/index.ts`](../utk_curio/frontend/urban-workflows/src/registry/index.ts)) instead of relying on a build-time `process.env.BACKEND_URL`. This keeps catalog-published bundles portable across deployments — the published bundle doesn't bake in the build host's URL.
4. **The lifecycle bundle externalises React, ReactDOM, ReactFlow, and `registerLifecycle`** so it shares Curio's instances at runtime. Curio's main bundle exposes them as `window.React`, `window.ReactDOM`, `window.ReactFlow`, `window.curio.registerLifecycle` ([`src/registry/index.ts`](../utk_curio/frontend/urban-workflows/src/registry/index.ts)). Without this, distinct React copies would break rules-of-hooks.
5. **If the bundle fails to load** (network error, hash mismatch, parse error), the package's templates fall back to `usePackageNodeLifecycle` (a generic code-editor). The palette still renders; the user just gets the default UI instead of the package's custom UI.

This means *adding a new package to a running Curio instance does not require rebuilding Curio* — the package's `scripts/lifecycles.js` is loaded dynamically. Authors bundle once; deployments stay decoupled.

The lifecycles in `curio.builtin@1` (`code`, `vega`, `merge-flow`, `spatial-join`, `data-pool`, …) are an exception — they live in Curio's main bundle because they must be registered before *any* package registry exists.

## 5. Recipe: add a Flask blueprint

When your node needs server-side capabilities the sandbox can't provide (external APIs, long-running jobs, persistent state, native deps), add a blueprint under `utk_curio/backend/app/<feature>/`. The streetvision blueprint (§4.4) is the canonical example.

1. **Create the directory + entry-point.** `utk_curio/backend/app/<feature>/__init__.py`:
   ```python
   from flask import Blueprint
   bp = Blueprint("<feature>", __name__)
   from . import routes  # noqa: E402,F401 — handlers register on import
   ```

2. **Author the handlers.** `utk_curio/backend/app/<feature>/routes.py`:
   ```python
   import os
   from flask import jsonify, request
   from . import bp

   @bp.get("/health")
   def health():
       return jsonify({
           "status": "healthy",
           "has_my_api_key": bool(os.environ.get("MY_API_KEY")),
       })

   @bp.post("/do-thing")
   def do_thing():
       body = request.get_json(silent=True) or {}
       # ... validate, return jsonify({...}) or jsonify({"error": "..."}), 400
   ```
   Surface API-key presence in `/health` (§3.2). Validate `body` against `request.get_json(silent=True) or {}` and return `{ error, hint }` with appropriate status codes (§3.7). Keep route handlers thin — push real work into a sibling `services/` package so handlers stay testable.

3. **Lazy-import heavy deps** inside the handler that needs them so a broken install doesn't crash the whole backend on startup (§3.8):
   ```python
   @bp.post("/run-inference")
   def run_inference():
       try:
           from .services.inference import run  # heavy lazy import
       except ImportError as e:
           return jsonify({"error": f"<feature> dependency unavailable: {e}",
                           "hint": "Reinstall Curio"}), 503
       # ...
   ```

4. **Register the blueprint** next to the others in [`utk_curio/backend/app/__init__.py`](../utk_curio/backend/app/__init__.py):
   ```python
   from utk_curio.backend.app.<feature> import bp as <feature>_bp
   app.register_blueprint(<feature>_bp, url_prefix="/api/<feature>")
   ```

5. **Declare any Python deps your blueprint needs in the *package's* `manifest.dependencies.python`** (see §3.8). The catalog install pip-installs them automatically. Only put a library in Curio's core `pyproject.toml` if *every* install needs it.

6. **Verify the blueprint is mounted** by booting the app and checking the URL map:
   ```bash
   python -c "
   from utk_curio.backend.app import create_app
   app = create_app()
   for r in sorted(str(r) for r in app.url_map.iter_rules() if '/api/<feature>/' in str(r)):
       print(r)
   "
   ```
   Every route handler you wrote should show up.

## 6. Recipe: ship a node package

The smallest possible package adds one template plus its lifecycle hook. Use this when you have a new node kind to introduce.

1. **Create the package directory.** `packages/<publisher>.<name>@<major>/`. Pick a `major` integer; bump it on breaking changes to existing templates (lifecycle keys, port types) — additive changes (new templates, new fields) don't need a bump.

2. **Author the manifest.** `packages/<publisher>.<name>@<major>/manifest.json` — the schema is at [`docs/schemas/node-package.v3.json`](schemas/node-package.v3.json). Minimum viable:
   ```json
   {
     "$schema": "https://raw.githubusercontent.com/urban-toolkit/curio/main/docs/schemas/node-package.v3.json",
     "id": "<publisher>.<name>",
     "name": "Human-readable Package Name",
     "publisher": "Your Org",
     "version": "1.0.0",
     "compatibility": { "curioRuntime": ">=0.5.0", "major": 1 },
     "createdAt": "2026-05-26T00:00:00Z",
     "license": "MIT",
     "dependencies": { "js": {}, "packages": {}, "python": {} },
     "templates": [
       {
         "id": "my-node",
         "label": "My Node",
         "description": "What this node does — shown in the palette tooltip.",
         "category": "computation",
         "editor": "none",
         "lifecycle": "my-node",
         "iconRef": "fa-solid:cube",
         "inputPorts":  [{ "cardinality": "1", "types": ["GEODATAFRAME"] }],
         "outputPorts": [{ "cardinality": "1", "types": ["GEODATAFRAME"] }],
         "hasCode": false, "hasGrammar": false, "hasWidgets": false
       }
     ]
   }
   ```

3. **Write the lifecycle hook inside the package directory.** Put it under `packages/<publisher>.<name>@<major>/sources/myNodeLifecycle.tsx`. The hook must satisfy `NodeLifecycleHook` from `registry/types`:
   ```tsx
   import { NodeLifecycleHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';
   export const useMyNodeLifecycle: NodeLifecycleHook = (data, nodeState) => {
     // Read `data.input` from upstream, push downstream via `data.outputCallback`.
     // Return `{ contentComponent: <YourUI /> }` to render a body, or omit for
     //   icon-only nodes (also set `containerStyle.noContent: true` in the
     //   manifest — see §2 / §4.4 for examples like merge-flow + spatial-join).
     return { /* contentComponent: ..., dynamicHandles?, handlesOverride? */ };
   };
   ```
   The import path back to Curio's `registry/types` resolves at build time only — types are erased at runtime, so the runtime bundle stays decoupled from Curio's internal source tree.

4. **Add a registration entry-point** at `packages/<publisher>.<name>@<major>/sources/index.tsx`:
   ```tsx
   import { useMyNodeLifecycle } from './myNodeLifecycle';

   type CurioGlobal = { registerLifecycle: (key: string, hook: any) => void };
   function registerAll(curio: CurioGlobal) {
     curio.registerLifecycle('my-node', useMyNodeLifecycle);
   }
   if (typeof window !== 'undefined') {
     const w = window as any;
     if (w.curio?.registerLifecycle) registerAll(w.curio);
     else (w.__curioPendingPackages__ ??= []).push(registerAll);
   }
   ```
   This file is what gets compiled into the package's runtime bundle. Its side-effect is calling `window.curio.registerLifecycle(...)` for each lifecycle the package ships. The pending-callbacks fallback handles the race where the bundle loads before Curio's main bundle finishes initialising the global registry.

5. **Declare the bundle in the manifest** so Curio knows to load it. Add at the top-level (not per-template):
   ```json
   {
     "id": "<publisher>.<name>",
     "lifecycleScript": "scripts/lifecycles.js",
     ...
   }
   ```
   `lifecycleScript` is a path relative to the package directory. The archive validator only accepts a small set of top-level dirs (see [`installer.py::_ALLOWED_TOP_DIRS`](../utk_curio/backend/app/packages/installer.py): `sources`, `starters`, `grammars`, `widgets`, `icons`, `scripts`); the bundle goes under `scripts/` so it survives the catalog round-trip. Curio's package registry bootstrap fetches the file with the user's Bearer token and injects the response body as an inline `<script>` BEFORE building descriptors, so the lifecycle keys are registered by the time `getLifecycle('my-node')` looks them up.

6. **Wire up the build for first-party packages.** Add an entry to [`utk_curio/frontend/urban-workflows/webpack.packages.config.js`](../utk_curio/frontend/urban-workflows/webpack.packages.config.js)'s `PACKAGE_ENTRIES` list:
   ```js
   {
     id: "<publisher>.<name>@<major>",
     entry: path.resolve(__dirname, "../../../packages/<publisher>.<name>@<major>/sources/index.tsx"),
     outputDir: path.resolve(__dirname, "../../../packages/<publisher>.<name>@<major>/scripts"),
   },
   ```
   Then `npm run build` (which now chains `npm run build:packages`) compiles `sources/index.tsx` into `<package-dir>/scripts/lifecycles.js` — UMD output, externalizing React / ReactDOM / ReactFlow so the bundle shares Curio's instances at runtime (essential for rules-of-hooks).

   **Third-party packages** ship their own pre-built `scripts/lifecycles.js` and don't need a row in this file — Curio loads any `lifecycleScript` it finds in an installed package regardless of who built it.

7. **(If a custom icon)** register it in [`registry/iconRegistry.ts`](../utk_curio/frontend/urban-workflows/src/registry/iconRegistry.ts):
   ```ts
   import { faSomeIcon } from '@fortawesome/free-solid-svg-icons';
   registerIcon('fa-solid:some-icon', faSomeIcon);
   ```
   Unregistered icons silently fall back to `faCube` with a one-time console warning.

8. **Compute `integrity.json`** — Curio's package loader validates every file's sha256 against this manifest. After every content change, regenerate it:
   ```bash
   cd packages/<publisher>.<name>@<major>/
   python -c "
   import hashlib, json, os, sys
   files = [f for f in sorted(os.listdir('.'))
            if f != 'integrity.json' and os.path.isfile(f)]
   hashes = {fn: hashlib.sha256(open(fn,'rb').read()).hexdigest() for fn in files}
   json.dump({'sha256': hashes}, open('integrity.json','w'), indent=2)
   "
   ```
   Forget this step and the package fails to load with a hash-mismatch error.

9. **Write `README.md`** in the package directory — the catalog UI shows it inline when users browse for packages to install. Cover Python deps the catalog install will auto-fetch from `manifest.dependencies.python` (size, GPU recommendation, etc.), any env vars / API keys the node UI needs at runtime, costs (paid APIs), and limitations.

10. **Validate end-to-end** by booting Curio and checking that:
   - The package shows up in `/catalog` for installation.
   - After install, your node appears in the palette under its declared `category`.
   - Dragging it to the canvas mounts your lifecycle hook (open dev tools → check for warnings).

## 7. Checklist for a new node package

- [ ] `packages/<id>@<major>/manifest.json` — templates with lifecycle keys, port shapes, palette ordering.
- [ ] `packages/<id>@<major>/integrity.json` — sha256 of every other file. Regenerate on every edit (a small script is sufficient — see `regen-integrity` helpers in the existing packages).
- [ ] `packages/<id>@<major>/README.md` — shown in the catalog. Cover setup, env vars, costs.
- [ ] Lifecycle hooks under `utk_curio/frontend/urban-workflows/src/adapters/node/`.
- [ ] Export them from [`adapters/node/index.ts`](../utk_curio/frontend/urban-workflows/src/adapters/node/index.ts).
- [ ] Register lifecycle keys in [`registry/builtinLifecycles.ts`](../utk_curio/frontend/urban-workflows/src/registry/builtinLifecycles.ts).
- [ ] *(If backend)* New Flask blueprint under `utk_curio/backend/app/<feature>/`.
- [ ] *(If backend)* Register the blueprint in [`utk_curio/backend/app/__init__.py`](../utk_curio/backend/app/__init__.py).
- [ ] *(If new Python deps)* Add them to the package's `manifest.dependencies.python` (catalog install pip-installs them automatically; see §3.8); lazy-import in the route layer so a broken install returns 503 instead of crashing startup.
- [ ] User-facing docs example in `docs/examples/<NN>-<name>.md`, linked from [`docs/README.md`](README.md).

Skip any item that doesn't apply — a pure-frontend node typically only needs the first six.
