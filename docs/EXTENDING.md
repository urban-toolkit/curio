# Extending Curio with new node packages

Curio nodes are defined by **packages**, not by code. A package is a directory under [`packages/`](../packages/) that ships a `manifest.json` declaring one or more node *templates*. Each template references a **behavior key** that resolves to a React hook implementing the node's behaviour. Optionally, a behavior hook calls a backend route in Curio for work the browser and the sandbox cannot do.

This guide walks through adding a new node package end-to-end. Its examples are code in this repository: [`curio.example-ui@1`](../packages/curio.example-ui@1/) for a node with its own React interface (manifest, behavior hook, `behaviorScript` bundle), [`curio.streetvision@1`](../packages/curio.streetvision@1/) for a code node with a Python dependency declared in `manifest.dependencies.python` and sandbox helpers, the built-in Spatial Join for a node that calls a backend route, and the [Discovery Catalog](DISCOVERY-CATALOG.md) for third-party APIs, per-account keys and long downloads. Easier packages can skip several of the steps below.

> [!TIP]
> **Writing your first package?** Start with [`docs/AUTHORING-NODES.md`](AUTHORING-NODES.md), a task-ordered walkthrough from `git clone` to a working node, including the edit → rebuild → reload loop. Scaffold with `python scripts/new_package.py <id> [--with-ui]`, and read [`packages/curio.example-ui@1`](../packages/curio.example-ui@1/) for a minimal custom-UI node with no API keys or heavy dependencies. Come back here for the reference detail: backend blueprints, external services, dependency declaration, and the manifest's finer points.

## 1. Anatomy of a package

```
packages/<packageId>@<major>/
├── manifest.json   ← declares templates, ports, behavior keys, deps
├── integrity.json  ← sha256 of every other file (regen with scripts/regen_integrity.py)
├── README.md       ← shown in the catalog UI
├── LICENSE         ← optional
├── sources/        ← Python / JS starters, or the TSX behavior hooks
├── scripts/        ← REQUIRED for custom UI: the compiled behaviors.js bundle
└── starters/       ← optional per-template starter snippets
```

A `template` inside `manifest.json` declares one node kind. It carries:

- `id` + `label` + `description` + `iconRef`: palette presentation
- `category` (`data` | `computation` | `vis_grammar` | `vis_simple` | `flow`): palette sectioning
- `inputPorts` + `outputPorts`: port types and cardinalities (see [`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json))
- `editor` (`code` | `widgets` | `grammar` | `none`): what editor surface to mount
- `behavior`: string key resolved through [`registry/behaviorRegistry`](../utk_curio/frontend/urban-workflows/src/registry/behaviorRegistry.ts) to the React hook that implements the node's behaviour
- `engine` (`python` | `javascript`): if the node runs user code, which sandbox executes it. A template with `hasCode`, an `engine` and no `backendHandler` is one an agent's Solve runs in the sandbox to verify what it writes

The frontend's package loader at [`registry/packagesClient.ts`](../utk_curio/frontend/urban-workflows/src/registry/packagesClient.ts) reads every installed package, calls `buildDescriptor()` per template, and registers them in the canvas's node-type registry. Adding a node is therefore *adding a manifest entry plus a behavior hook*; there is no monolithic switch-case anywhere.

## 2. When you need a backend blueprint, and when you don't

Three patterns cover essentially every node Curio ships:

| Pattern | Examples | Backend? |
|---|---|---|
| **Pure-frontend** | `vis-vega`, `vis-simple`, `autk-grammar`, `column-filter` (`curio.example-ui@1`) | None. The behavior hook does its work in the browser. |
| **Sandbox-Python** | `data-loading`, `data-transformation`, `computation-analysis`, `data-summary`, `image-segmentation` (`curio.streetvision@1`) | Reuses Curio's existing code sandbox at [`utk_curio/sandbox/`](../utk_curio/sandbox/) via the `code` behavior. User-provided Python runs out-of-process. A package template does the same with its own starter file and Python dependencies (§4.2). |
| **Backend route** | `spatial-join` (shapely STRtree) | A route in Curio's backend that the behavior hook calls: Spatial Join's is one handler in [`api/routes.py`](../utk_curio/backend/app/api/routes.py) over a helper in [`common/spatial.py`](../utk_curio/backend/app/common/spatial.py). A feature with several routes gets its own Flask blueprint under [`utk_curio/backend/app/<feature>/`](../utk_curio/backend/app/) (§5). Right call when the node needs server-side work the sandbox can't reasonably do. |

Pure-frontend is the right default; reach for the sandbox before a blueprint, and only stand up a blueprint when neither covers it. Third-party data and models come in through the Discovery Catalog (§3), and a node reads them from the Data or Model Catalog.

## 3. Connecting to external services

A third-party API reaches Curio as a **source** in the [Discovery Catalog](DISCOVERY-CATALOG.md): a manifest at `discovery/<sourceId>@<major>/manifest.json` names the host, the key it sends and what it offers, and a provider module under [`utk_curio/backend/app/discovery/providers/`](../utk_curio/backend/app/discovery/providers/) speaks the API. Street-level photos arrive this way, from [`source.mapillary.imagery@1`](../discovery/source.mapillary.imagery@1/manifest.json) ([`providers/mapillary.py`](../utk_curio/backend/app/discovery/providers/mapillary.py)) and [`source.google.street-view@1`](../discovery/source.google.street-view@1/manifest.json) ([`providers/google_streetview.py`](../utk_curio/backend/app/discovery/providers/google_streetview.py)), and image segmentation models from [`source.huggingface.models@1`](../discovery/source.huggingface.models@1/manifest.json) ([`providers/huggingface_models.py`](../utk_curio/backend/app/discovery/providers/huggingface_models.py)). A download lands in the Data Catalog (a model, in the Model Catalog), and a node reads it from there with `curio_collection("<id>")`, `curio_dataset_path("<id>")` or `curio_model("<id>")`. The patterns below are the conventions that code follows; [ARCHITECTURE.md, Providers](ARCHITECTURE.md#providers) lists the steps to add a provider.

### 3.1 Always proxy through the backend

Never call third-party APIs from the browser directly:

1. **API keys leak.** Anything built into the frontend bundle, even read-at-runtime values, is visible in DevTools' network tab.
2. **CORS.** Most public APIs (Google, Nominatim) reject browser-origin requests.
3. **Rate-limit hygiene.** Centralising in the backend lets you add caching, retries, and per-user quota in one place.

Every Discovery request leaves the backend through one transport, [`discovery/infrastructure/transport.py`](../utk_curio/backend/app/discovery/infrastructure/transport.py): `HttpDiscoveryTransport` sends it under the egress policy with a timeout (`METADATA_TIMEOUT_S`) and a size bound, and refuses an answer that is not a 2xx. A source's `limits.requestsPerMinute` bounds each account's requests to it. A behavior hook that needs the backend calls a Curio route, as [`spatialJoinBehavior.tsx`](../utk_curio/frontend/urban-workflows/src/adapters/node/spatialJoinBehavior.tsx) posts to `${backendUrl()}/spatial_join`.

### 3.2 API keys: a row in API Settings

Pick the pattern by who the key belongs to:

- **Per-account keys** (a Mapillary access token, a Google Maps API key, a Hugging Face token) are rows in **API Settings**, never a node input, a line of node code or a field of the dataflow spec. Each is a `KeySlot` in `SLOTS` ([`discovery/infrastructure/credentials.py`](../utk_curio/backend/app/discovery/infrastructure/credentials.py)): the `User` column that holds it, a label, a help link, a placeholder, an optional note, and an optional deployment-wide fallback (`default_env`) that a user's own key overrides. A source names its slot in `auth.secretId`, and a manifest naming a slot Curio does not hold fails to load. Adding a slot is a `User` column, a migration, a field in `PATCH /api/auth/me` ([`users/routes.py`](../utk_curio/backend/app/users/routes.py)), an entry in `SLOTS` and its id in `KNOWN_SECRET_SLOTS` ([`discovery/domain/manifest.py`](../utk_curio/backend/app/discovery/domain/manifest.py)). API Settings draws one row per slot.

- **Several named secrets per account** (connection keys, LLM configurations) go in an owner-only per-user file written through [`common/owner_only_file.py`](../utk_curio/backend/app/common/owner_only_file.py), as [`users/connection_keys.py`](../utk_curio/backend/app/users/connection_keys.py) and [`agents/infrastructure/llm_configs.py`](../utk_curio/backend/app/agents/infrastructure/llm_configs.py) do.

- **Genuinely operator-wide secrets** that no user should override (an internal data-source token) -> `os.environ.get(...)` at the backend, read at request time so editing `.env` + restart picks it up without rebuilding. Prefer a documented `curio.py start` flag that names the variable, so the knob is discoverable.

Three rules the per-account pattern follows:

**The key goes only to its source's host.** `_transport_for` in
[`discovery/service.py`](../utk_curio/backend/app/discovery/service.py) wraps
the transport in `CredentialedTransport` with the host of the source's
`provider.baseUrl`; a request to any other host, such as a Mapillary photo on
its CDN, goes without the key. `credential_header` turns the slot into a header
(`auth.headerName` plus `auth.valuePrefix`) or, for `auth.scheme: "query"`, a
query parameter (`auth.paramName`). The transport is the only code that adds
it: providers never see the value, and a query key is taken out of every URL
and message the transport hands back (`_keyed`, `_redact`).

**A worker thread loads the user itself.** A download runs on a worker thread,
where `g` is gone. `start_acquire` hands the worker the user's id, never the ORM
row, and the worker loads the user in its own app context before any key is
resolved. A storage scan's transport, key included, is built on the request
thread (`_storage_builder`) and only called from the scan thread.

**What a key fetches stays with its account.** A storage source's listing is
shared by every user when the source sends no key, and kept per account when it
does (`_listing_scope`).

Report presence, never the value. `GET /api/discovery/keys` (`key_rows`) lists
every slot with booleans only: `present` (this account saved one) and
`inherited` (the deployment supplies one). The user payload carries a
`has_<column>` flag per slot (`SLOT_FLAGS`).

A package whose backend needs to know *who* is calling must send the bearer
token: read `window.curio.getAuthToken()` (a getter, because a package bundle
evaluates once at boot, before sign-in) and pass it as an `Authorization`
header. Never check secrets into git.

### 3.3 Public APIs without auth

Nominatim, OpenStreetMap's geocoder, is free and public; it answers the place search of every source's area field. [`discovery/application/places.py`](../utk_curio/backend/app/discovery/application/places.py) follows its usage policy: a `User-Agent` that names Curio, at most one request a second from the server (`MIN_INTERVAL_S`), and answers kept for a day (`CACHE_TTL_S`):

```python
# places.py
with _lock:
    hit = _cache.get(key)
    if hit is not None and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    _wait_for_slot()
    try:
        payload = transport.json_get(
            search_url(text),
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
        )
    finally:
        _last_request = time.monotonic()
```

Read a public API's usage policy before shipping a source that calls it in a loop, and **cache aggressively** (a single user might re-search the same place a dozen times in one session). Code that calls `requests` itself sets a **timeout** (`requests`'s default is "wait forever") and checks the response status; the Discovery transport does both.

### 3.4 APIs with API keys

A source declares its key in the manifest's `auth` block, naming an API Settings slot (§3.2). Mapillary sends its token as a header:

```json
"auth": {
  "mode": "required-token",
  "secretId": "mapillary.token",
  "headerName": "Authorization",
  "valuePrefix": "OAuth ",
  "helpUrl": "https://www.mapillary.com/dashboard/developers"
}
```

Google Street View sends its key as a query parameter:

```json
"auth": {
  "mode": "required-token",
  "secretId": "google.maps-key",
  "scheme": "query",
  "paramName": "key",
  "helpUrl": "https://developers.google.com/maps/documentation/streetview/get-api-key"
}
```

An `optional-token` source (Hugging Face models) sends the key when the account has one and asks without it otherwise. A `required-token` source the account holds no key for is refused before any job exists: `start_acquire` raises `CredentialRequired` (a `428`) naming the slot and the help link, and a search leg reports `needs-token`. A missing key is a message naming what to do, never a stacktrace.

### 3.5 Long-running calls and job-id polling

A batch download, or any external call that takes more than a few seconds, shouldn't hold a connection open. It runs as a Discovery job ([`discovery/application/jobs.py`](../utk_curio/backend/app/discovery/application/jobs.py)):

1. `POST /api/discovery/sources/<source>/resources/<id>/acquire` answers `202` with the job's row (`jobId`, `status`) at once, and starts a daemon thread (`run_in_background`) that does the work and writes its progress onto the job (`bytes_read`, `total_bytes`, `items_done`, `items_total`, `stage_message`). When the account already holds what was asked for, it answers `200` with that and starts no job.
2. The page polls `GET /api/discovery/jobs/<job_id>` and renders `bytesRead`, `totalBytes`, `itemsDone`, `itemsTotal` and `stageMessage` as progress.
3. `DELETE /api/discovery/jobs/<job_id>` asks the job to stop; the worker checks `job.cancelled` between chunks.
4. A job ends in one of the `TERMINAL` states (`completed`, `failed`, `refused`, `cancelled`), carrying the dataset (`dataset`, `datasetId`) or the model (`model`) on success and `error` otherwise.

The store (`JobStore`) is keyed by `(user, job)`, so another account's job id reads as unknown, and a finished job is swept `TTL_SECONDS` (15 minutes) after it ends. It is in memory: restarting Curio loses any job in flight.

### 3.6 Caching expensive responses

The Discovery Catalog's patterns:

- **Key the cache on the request's inputs.** A download already held, by `(sourceId, resourceId, format, parametersHash)`, answers `200` and contacts no portal; the place search keys on the query text.
- **Expire what changes.** A downloaded file stays until its dataset is deleted; a place answer lasts a day (`CACHE_TTL_S` in `places.py`), and a WFS server's capabilities document 15 minutes (`CAPABILITIES_TTL_S` in `providers/wfs.py`).
- **Store per user, serve by id.** A bucket collection's files are cached under the account's own media directory (`media_work_root` in [`discovery/infrastructure/media_dirs.py`](../utk_curio/backend/app/discovery/infrastructure/media_dirs.py)) by [`application/cache_collection.py`](../utk_curio/backend/app/discovery/application/cache_collection.py), capped by `CURIO_MEDIA_CACHE_MAX_GB`, and the files a node derives with `curio_derived_file` go beside them. Both are served by id from `@require_auth` routes in [`discovery/media_routes.py`](../utk_curio/backend/app/discovery/media_routes.py) (`/api/datasets/<dataset_id>/media/<file_id>`), which look the file up in the caller's own dataset and never take a path from the request.

### 3.7 The error contract back to the frontend

| HTTP | Meaning | Behavior reaction |
|---|---|---|
| `200` | OK | Render the result |
| `400` | Bad input (missing field, malformed body) | Surface inline message |
| `403` | Refused (not yours, or not permitted) | Surface the reason; do not retry |
| `404` | No such route or resource | Surface "not found"; do not retry |
| `405` | Wrong method for this route | A client bug; surface it in development |
| `503` | Service / extras unavailable | Show "install hint" / "backend offline" banner |
| `5xx` | Unhandled backend error | Generic "Lost connection to backend" toast |

`403`, `404` and `405` are what `abort()` and werkzeug's own routing errors
produce; `create_app` registers an `HTTPException` handler alongside the
catch-all, so only genuine unhandled exceptions are `500`.

Always return JSON bodies with `{ "error": "...", "hint": "..." }` for non-200 responses; the frontend reads `hint` to give the user an actionable next step. Don't return plain-text 500s.

### 3.8 Per-package Python dependencies

Curio's `requirements.txt` / `pyproject.toml::dependencies` carries **only** the framework: what the backend and sandbox Flask apps need at module load (Flask, SQLAlchemy, requests, the LLM SDKs, etc.). **Every node package** ships its own data-ops libs in its manifest's `dependencies.python`, including the bundled `curio.builtin@1` (pandas, geopandas, etc.) and optional packages like `curio.weather@1` (rasterio, pythermalcomfort, rasterstats) and `curio.streetvision@1` (onnxruntime). The `curio start` launcher walks every installed manifest at startup, merges them into a single conflict-aware union, and pip-installs the result before booting the subprocesses. See [`main.py::install_manifest_dependencies`](../utk_curio/main.py) for the walker.

Declare your package's deps in `manifest.dependencies.python`:

```json
{
  "id": "curio.streetvision",
  "dependencies": {
    "js": {},
    "packages": {},
    "python": {
      "onnxruntime": ">=1.17"
    }
  }
}
```

Accepted spec syntax: PEP 440 comparators (`>=2.0`, `~=4.30`, `==1.5.0`, `!=2.0`), bare versions (`1.2.3` → treated as `==1.2.3`), npm-style carets (`^0.14` → rewritten to `~=0.14`), or empty string for "latest".

A model in the Model Catalog declares its runtime's libraries the same way, in its own manifest's `dependencies.python`, and they install when the model is added (`install_dependencies` in [`model_catalog/service.py`](../utk_curio/backend/app/model_catalog/service.py)). A Transformers model brings `torch`, `transformers` and `safetensors` (`RUNTIME_DEPS` in [`discovery/application/model_acquire.py`](../utk_curio/backend/app/discovery/application/model_acquire.py)); an ONNX model runs on the Street Vision package's `onnxruntime`.

#### How the install/uninstall flow handles them

- **Adding a package from the catalog** copies the package files, then runs `pip install` (via [`utk_curio/backend/app/packages/infrastructure/pip_runner.py`](../utk_curio/backend/app/packages/infrastructure/pip_runner.py)) for every dep that isn't already importable. Already-satisfied deps are skipped, so re-adding the same package is near-instant. The request blocks until pip finishes (v1 sync UX); the confirm button stays busy.
- **Removing a package** (when its user-store copy is being pruned) walks every other still-installed package's manifest, finds the python deps the pruned package declared that **no other package needs**, and pip-uninstalls those. Shared deps stay.
- A failed pip install rolls back the package's user-store copy so the user can retry cleanly. The Flask response carries the tail of pip's stderr so the user knows what failed (network error, version conflict, missing wheel, etc.).

#### When to still lazy-import

Even though deps are installed up front, lazy-import expensive libraries inside the route handler that needs them so a broken install fails per-request with a clean 503 instead of crashing the backend on startup. The Spatial Join route imports its shapely helpers inside the handler:

```python
# api/routes.py
@bp.route('/spatial_join', methods=['POST'])
def spatial_join():
    # ...
    try:
        from utk_curio.backend.app.common.spatial import (
            enrich_points_with_polygons,
            polygons_with_counts,
        )
        enriched, aggregates, tag_column = enrich_points_with_polygons(
            points=point_dicts,
            polygon_fc=polygons_fc,
            name_property=name_property,
            warnings=warnings,
        )
    except ImportError as e:
        return jsonify({
            "error": "spatial extras not installed (shapely required)",
            "hint": "pip install shapely",
            "detail": str(e),
        }), 503
    # ...
```

Sandbox helpers follow the same rule: `curio_segment` imports `onnxruntime`, or `torch` and `transformers`, only when it loads a model of that runtime, and a missing library stops that node's run with a `RuntimeError` saying which runtime is missing (`_OnnxRunner` and `_TransformersRunner` in [`sandbox/util/vision.py`](../utk_curio/sandbox/util/vision.py)).

## 4. Walked example: three nodes

One node per pattern in §2: Column Filter (`curio.example-ui@1`) renders its own interface, Image Segmentation (`curio.streetvision@1`) is a code node in a package, and Spatial Join (`curio.builtin@1`) calls a backend route.

### 4.1 A custom-UI template in [`packages/curio.example-ui@1/manifest.json`](../packages/curio.example-ui@1/manifest.json)

```jsonc
"behaviorScript": "scripts/behaviors.js",
"templates": [
  { "id": "column-filter", "behavior": "column-filter", "editor": "none",
    "inputPorts":  [{"cardinality":"1","types":["DATAFRAME"]}],
    "outputPorts": [{"cardinality":"1","types":["DATAFRAME"]}] }
]
```

Each entry names a *behavior key* (a string), not a JS module path. The same key can be implemented by an entirely different package and still work, which is how forks and overrides happen. `behaviorScript` names the bundle that registers the key (§4.7).

### 4.2 A code template in [`packages/curio.streetvision@1/manifest.json`](../packages/curio.streetvision@1/manifest.json)

```jsonc
"dependencies": { "js": {}, "packages": {}, "python": { "onnxruntime": ">=1.17" } },
"templates": [
  { "id": "image-segmentation", "behavior": "code", "editor": "code", "engine": "python",
    "source": "sources/image-segmentation.py",
    "inputPorts":  [{"cardinality":"1","types":["GEODATAFRAME","DATAFRAME"]}],
    "outputPorts": [{"cardinality":"1","types":["GEODATAFRAME"]}] }
]
```

The template reuses the built-in `code` behavior, so the package ships no JavaScript and no `behaviorScript`. `source` is the starter a new node opens with, [`sources/image-segmentation.py`](../packages/curio.streetvision@1/sources/image-segmentation.py):

```python
model = curio_model("model.curio.ddrnet23-slim")
classes = ["vegetation", "terrain", "sky", "road", "sidewalk", "building"]

return curio_segment(arg, model, classes)
```

Both helpers are in the sandbox's namespace for every Python node:

- `curio_model("<model id>")` ([`sandbox/util/models.py`](../utk_curio/sandbox/util/models.py)) returns the folder of a model in the account's **Model Catalog** ([`utk_curio/backend/app/model_catalog/`](../utk_curio/backend/app/model_catalog/)); the backend resolves every id a node's code names before the run (`resolve_exec_models` in `model_catalog/service.py`). Models ship under [`models/`](../models/), as [`model.curio.ddrnet23-slim@1`](../models/model.curio.ddrnet23-slim@1/manifest.json) does, or are added from the Discovery Catalog's Hugging Face models source (§3).
- `curio_segment(images, model_dir, classes)` ([`sandbox/util/vision.py`](../utk_curio/sandbox/util/vision.py)) runs the model its folder's manifest describes (a `runtime` of `onnx` on onnxruntime, `transformers` on Transformers) over every row's `path`, and returns the rows with `dominant_class`, `dominant_pct`, a `<class>_pct` per class, `overlay_url` and `segment_error` first. Each overlay is written with `curio_derived_file` (kind `"image"`, [`sandbox/util/collections.py`](../utk_curio/sandbox/util/collections.py)) and served back by the media route (§3.6).

### 4.3 A built-in template in [`packages/curio.builtin@1/manifest.json`](../packages/curio.builtin@1/manifest.json)

A generic Spatial Join that takes points + polygons and tags each point with a column of the containing polygon (or emits the polygons with a count of points inside each):

```jsonc
{ "id": "spatial-join", "behavior": "spatial-join",
  "inputPorts": [
    {"types":["GEODATAFRAME"]},   // points (handle 0, top of node)
    {"types":["GEODATAFRAME"]}    // polygons (handle 1, bottom of node)
  ],
  "outputPorts": [{"types":["GEODATAFRAME"]}]
}
```

This one belongs in `curio.builtin@1`, not `curio.streetvision@1`, because it's reusable for any spatial workflow. Generally: if a capability is reusable outside the package's narrow theme, factor it out into builtin.

The agents' shared preamble describes every `curio.builtin@1` template from this manifest: its label, description, control, port types, how many connections its inputs accept, and interaction support. After adding or changing a built-in template, run `python scripts/generate_contracts.py` and commit the regenerated `utk_curio/llm-prompts/default_preamble.txt` with the manifest; the backend suite fails until you do (see [CONTRIBUTING.md, Generated Files](CONTRIBUTING.md#generated-files)).

### 4.4 Behavior hooks

Column Filter's hook ships inside its package, at [`packages/curio.example-ui@1/sources/`](../packages/curio.example-ui@1/sources/); Spatial Join's lives with the built-ins in [`utk_curio/frontend/urban-workflows/src/adapters/node/`](../utk_curio/frontend/urban-workflows/src/adapters/node/). Image Segmentation runs on the built-in `code` behavior and needs no hook of its own.

- [`columnFilterBehavior.tsx`](../packages/curio.example-ui@1/sources/columnFilterBehavior.tsx): reads `data.input` with `resolveInput`, which fetches a sandbox artifact reference and passes an inline payload through; keeps the column, comparison and threshold in `useState`; sends the matching rows downstream with `data.outputCallback` and reports through `nodeState.setOutput`. It returns only `contentComponent`.
- [`spatialJoinBehavior.tsx`](../utk_curio/frontend/urban-workflows/src/adapters/node/spatialJoinBehavior.tsx): the only node here with two distinct input handles, declared with `handlesOverride`. Posts both inputs to `/spatial_join` (§4.5). Worth reading if you ever need a 2-input node.

The package's hook registers from its bundle entry point, [`sources/index.tsx`](../packages/curio.example-ui@1/sources/index.tsx), through `window.curio`:

```tsx
function registerAll(curio: CurioGlobal) {
  curio.registerBehavior('column-filter', useColumnFilterBehavior);
}
```

The built-in one registers in [`registry/builtinBehaviors.ts`](../utk_curio/frontend/urban-workflows/src/registry/builtinBehaviors.ts):

```typescript
registerBehavior('spatial-join', useSpatialJoinBehavior);
```

Both land in one global registry; packages reference behavior keys by name, not by import.

### 4.5 The backend route

Spatial Join's route is a single handler at the end of [`api/routes.py`](../utk_curio/backend/app/api/routes.py) (`POST /spatial_join`) that calls generic helpers at [`utk_curio/backend/app/common/spatial.py`](../utk_curio/backend/app/common/spatial.py) (`enrich_points_with_polygons`, `polygons_with_counts`). Reusable utilities like that belong under `common/`, not in any specific blueprint. Image Segmentation has no route of its own: its work runs in the sandbox.

### 4.6 Shipping the package

The three packages are bundled in-repo under [`packages/`](../packages/). Seeding covers `curio.builtin@1` plus, when Curio starts with `--with-examples`, whatever the shipped example dataflows declare as dependencies (`example_dep_package_ids` in [`backend/app/packages/application/seeding.py`](../utk_curio/backend/app/packages/application/seeding.py)). Example 10 declares `curio.streetvision@1`, so Street Vision is installed with the examples. `curio.example-ui@1` is in neither set: users opt in by clicking **Add to project** in the catalog. Generally:

- **Bundled-and-auto-installed** → `curio.builtin@1`, which every user must have, and, with `--with-examples`, the packages a shipped example declares (`curio.streetvision@1`, `curio.weather@1`).
- **Bundled-and-installable** → optional first-party packages like `curio.example-ui@1`, `ai.utk.uhvi@1`. Visible in the catalog without a remote registry roundtrip.
- **Remote** → publishing through Curio's catalog endpoint, for third-party packages. Same manifest schema.

### 4.7 How behavior distribution works (and why)

When you install a package that ships its own custom node UIs, Curio needs to find a way to load the behavior JavaScript without rebuilding the main app. The mechanism in place today:

1. **The package directory contains both the manifest *and* a pre-built `scripts/behaviors.js`.** For first-party packages (in-repo), `npm run build` produces that JS via [`webpack.packages.config.js`](../utk_curio/frontend/urban-workflows/webpack.packages.config.js). Third-party authors compile their own. The bundle lives under `scripts/` because that subdirectory is one of the archive validator's allowed top-level dirs (see [`archive.py::_ALLOWED_TOP_DIRS`](../utk_curio/backend/app/packages/repositories/archive.py)), so the bundle survives the catalog install round-trip.
2. **The manifest declares the bundle via `behaviorScript: "scripts/behaviors.js"`** (a top-level field, not per-template). The path is relative to the package directory; any allowed-subdirectory location works.
3. **At app boot, the frontend's `loadInstalledPackages` fetches `/api/packages/<dirName>/file/scripts/behaviors.js` with the user's Bearer token and injects the response body as an inline `<script>` BEFORE building descriptors**. (A plain `<script src>` can't carry an `Authorization` header, so Firefox's OpaqueResponseBlocking would reject the `require_auth` 401 response, and the inline-injection path bypasses that.) The bundle's top-level side-effect calls `window.curio.registerBehavior(...)` for each behavior hook it ships. By the time `buildDescriptor` looks up `getBehavior('column-filter')`, the key is registered.

   The bundle reads its backend URL at runtime from `window.curio.backendUrl` (exposed by Curio's main bundle in [`src/registry/index.ts`](../utk_curio/frontend/urban-workflows/src/registry/index.ts)) instead of relying on a build-time `process.env.BACKEND_URL`. This keeps catalog-published bundles portable across deployments, because the published bundle doesn't bake in the build host's URL.
4. **The behavior bundle externalises React, ReactDOM, ReactFlow, and `registerBehavior`** so it shares Curio's instances at runtime. Curio's main bundle exposes them as `window.React`, `window.ReactDOM`, `window.ReactFlow`, `window.curio.registerBehavior` ([`src/registry/index.ts`](../utk_curio/frontend/urban-workflows/src/registry/index.ts)). Without this, distinct React copies would break rules-of-hooks.
5. **If the bundle fails to load** (network error, hash mismatch, parse error), the package's templates fall back to `usePackageNodeBehavior` (a generic code-editor). The palette still renders; the user just gets the default UI instead of the package's custom UI.

This means *adding a new package to a running Curio instance does not require rebuilding Curio*, because the package's `scripts/behaviors.js` is loaded dynamically. Authors bundle once; deployments stay decoupled.

The behaviors in `curio.builtin@1` (`code`, `vega`, `merge-flow`, `spatial-join`, `data-pool`, …) are an exception: they live in Curio's main bundle because they must be registered before *any* package registry exists.

## 5. Recipe: add a Flask blueprint

When your node needs server-side capabilities the sandbox can't provide, add a route. A single route can join an existing blueprint, as Spatial Join's joins the `api` blueprint (§4.5). A feature with several routes gets its own blueprint under `utk_curio/backend/app/<feature>/`, as the Model Catalog does ([`model_catalog/routes.py`](../utk_curio/backend/app/model_catalog/routes.py): `models_bp`, under `/api/models`). Third-party APIs and long downloads are Discovery Catalog sources and jobs (§3).

1. **Create the directory + entry-point.** `utk_curio/backend/app/<feature>/__init__.py`:
   ```python
   from flask import Blueprint
   bp = Blueprint("<feature>", __name__)
   from . import routes  # noqa: E402,F401 (handlers register on import)
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
   Surface API-key presence in `/health` (§3.2). Validate `body` against `request.get_json(silent=True) or {}` and return `{ error, hint }` with appropriate status codes (§3.7). Keep route handlers thin, pushing real work into a sibling `services/` package so handlers stay testable.

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

The smallest possible package adds one template plus its behavior hook. Use this when you have a new node kind to introduce.

1. **Create the package directory.** `packages/<publisher>.<name>@<major>/`. Pick a `major` integer; bump it on breaking changes to existing templates (behavior keys, port types). Additive changes (new templates, new fields) don't need a bump.

2. **Author the manifest.** `packages/<publisher>.<name>@<major>/manifest.json`. The schema is at [`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json). Minimum viable:
   ```json
   {
     "$schema": "https://raw.githubusercontent.com/urban-toolkit/curio/main/docs/schemas/node-package.v4.json",
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
         "description": "What this node does; shown in the palette tooltip.",
         "category": "computation",
         "editor": "none",
         "behavior": "my-node",
         "iconRef": "fa-solid:cube",
         "inputPorts":  [{ "cardinality": "1", "types": ["GEODATAFRAME"] }],
         "outputPorts": [{ "cardinality": "1", "types": ["GEODATAFRAME"] }],
         "hasCode": false, "hasGrammar": false, "hasWidgets": false
       }
     ]
   }
   ```

3. **Write the behavior hook inside the package directory.** Put it under `packages/<publisher>.<name>@<major>/sources/myNodeBehavior.tsx`. The hook must satisfy `NodeBehaviorHook` from `registry/types`:
   ```tsx
   import { NodeBehaviorHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';
   export const useMyNodeBehavior: NodeBehaviorHook = (data, nodeState) => {
     // Read `data.input` from upstream, push downstream via `data.outputCallback`.
     // Return `{ contentComponent: <YourUI /> }` to render a body, or omit for
     //   icon-only nodes (also set `containerStyle.noContent: true` in the
     //   manifest; see §2 / §4.4 for examples like merge-flow + spatial-join).
     return { /* contentComponent: ..., dynamicHandles?, handlesOverride? */ };
   };
   ```
   The import path back to Curio's `registry/types` resolves at build time only. Types are erased at runtime, so the runtime bundle stays decoupled from Curio's internal source tree.

4. **Add a registration entry-point** at `packages/<publisher>.<name>@<major>/sources/index.tsx`:
   ```tsx
   import { useMyNodeBehavior } from './myNodeBehavior';

   type CurioGlobal = { registerBehavior: (key: string, hook: any) => void };
   function registerAll(curio: CurioGlobal) {
     curio.registerBehavior('my-node', useMyNodeBehavior);
   }
   if (typeof window !== 'undefined') {
     const w = window as any;
     if (w.curio?.registerBehavior) registerAll(w.curio);
     else (w.__curioPendingPackages__ ??= []).push(registerAll);
   }
   ```
   This file is what gets compiled into the package's runtime bundle. Its side-effect is calling `window.curio.registerBehavior(...)` for each behavior the package ships. The pending-callbacks fallback handles the race where the bundle loads before Curio's main bundle finishes initialising the global registry.

5. **Declare the bundle in the manifest** so Curio knows to load it. Add at the top-level (not per-template):
   ```json
   {
     "id": "<publisher>.<name>",
     "behaviorScript": "scripts/behaviors.js",
     ...
   }
   ```
   `behaviorScript` is a path relative to the package directory. The archive validator only accepts a small set of top-level dirs (see [`archive.py::_ALLOWED_TOP_DIRS`](../utk_curio/backend/app/packages/repositories/archive.py): `sources`, `starters`, `grammars`, `widgets`, `icons`, `scripts`); the bundle goes under `scripts/` so it survives the catalog round-trip. Curio's package registry bootstrap fetches the file with the user's Bearer token and injects the response body as an inline `<script>` BEFORE building descriptors, so the behavior keys are registered by the time `getBehavior('my-node')` looks them up.

6. **Wire up the build.** Add an entry to [`utk_curio/frontend/urban-workflows/webpack.packages.config.js`](../utk_curio/frontend/urban-workflows/webpack.packages.config.js)'s `PACKAGE_ENTRIES` list. `scripts/new_package.py --with-ui` prints the row ready to paste:
   ```js
   {
     id: "<publisher>.<name>@<major>",
     entry: path.resolve(__dirname, "../../../packages/<publisher>.<name>@<major>/sources/index.tsx"),
     outputDir: path.resolve(__dirname, "../../../packages/<publisher>.<name>@<major>/scripts"),
   },
   ```
   Then `npm run build:packages` compiles `sources/index.tsx` into `<package-dir>/scripts/behaviors.js` as UMD output, externalizing React / ReactDOM / ReactFlow so the bundle shares Curio's instances at runtime (essential for rules-of-hooks). That target takes a couple of seconds and is all you need for a package-only change; `npm run build` chains it after the much slower full app build.

   Rebuilding the bundle is only half of it: the frontend loads `behaviorScript` from your **installed** copy in the user store, so after every rebuild click **Reload** on the package in the catalog drawer's **In project** tab. See [`docs/AUTHORING-NODES.md`](AUTHORING-NODES.md) for the whole loop.

   **Packages built outside this repo** ship their own pre-built `scripts/behaviors.js` and need no row in this file, since Curio loads any `behaviorScript` it finds in an installed package regardless of who built it. There is no separate toolchain for that case: the practical route is to author inside a Curio checkout (where `registry/types` resolves and this build config exists), then distribute the resulting `.curio.zip`.

7. **(If a custom icon)** register it in [`registry/iconRegistry.ts`](../utk_curio/frontend/urban-workflows/src/registry/iconRegistry.ts):
   ```ts
   import { faSomeIcon } from '@fortawesome/free-solid-svg-icons';
   registerIcon('fa-solid:some-icon', faSomeIcon);
   ```
   Unregistered icons silently fall back to `faCube` with a one-time console warning.

8. **Regenerate `integrity.json`**, the sha256 of every shipped file, keyed by
   its POSIX path *relative to the package root* (so `sources/foo.py` and
   `scripts/behaviors.js` are included, not just the top-level files). The
   installer writes it for you on install / import; a package you edit in place
   needs it refreshed:
   ```bash
   python scripts/regen_integrity.py packages/<publisher>.<name>@<major>
   ```
   That calls the same `refresh_package_integrity` the installer uses, so the
   result is byte-identical to a fresh install's. It also re-validates the
   manifest and tells you if it broke.

   Nothing in Curio currently *verifies* these hashes at load time, so a stale
   `integrity.json` will not stop your package from working, but keep it
   current anyway so an archive you hand to someone else carries an honest inventory of
   its own contents. (Note that hashes are line-ending sensitive: re-hashing on
   Windows a package committed from a Unix machine reports every file as
   changed. Expected, and harmless.)

9. **Write `README.md`** in the package directory. The catalog UI shows it inline when users browse for packages to install. Cover Python deps the catalog install will auto-fetch from `manifest.dependencies.python` (size, GPU recommendation, etc.), any env vars or API Settings keys the node needs at runtime (§3.2), costs (paid APIs), and limitations.

10. **Validate end-to-end** by booting Curio and checking that:
   - The package shows up in `/catalog` for installation.
   - After install, your node appears in the palette under its declared `category`.
   - Dragging it to the canvas mounts your behavior hook (open dev tools → check for warnings).

## 7. Checklist for a new node package

`python scripts/new_package.py <id> [--with-ui]` produces the first group for
you. See [`docs/AUTHORING-NODES.md`](AUTHORING-NODES.md) for the walkthrough.

**Every package**

- [ ] `packages/<id>@<major>/manifest.json`: templates with behavior keys, port shapes, palette ordering.
- [ ] `packages/<id>@<major>/README.md`: shown in the catalog. Cover setup, env vars, costs.
- [ ] `packages/<id>@<major>/integrity.json`: regenerate after every edit with `python scripts/regen_integrity.py packages/<id>@<major>` (§6 step 8).

**Behavior hooks in the package** (the normal case: no Curio rebuild needed)

- [ ] Hook at `packages/<id>@<major>/sources/<name>Behavior.tsx` (§6 step 3).
- [ ] Registration entry point at `packages/<id>@<major>/sources/index.tsx`, calling `window.curio.registerBehavior(...)` (§6 step 4).
- [ ] `"behaviorScript": "scripts/behaviors.js"` at the top level of the manifest (§6 step 5).
- [ ] A row in [`webpack.packages.config.js`](../utk_curio/frontend/urban-workflows/webpack.packages.config.js), then `npm run build:packages` (§6 step 6).

**Behavior hooks built into Curio** (core contributors only; for behaviors
every install must have before any package registry exists)

- [ ] Hook under `utk_curio/frontend/urban-workflows/src/adapters/node/`.
- [ ] Export it from [`adapters/node/index.ts`](../utk_curio/frontend/urban-workflows/src/adapters/node/index.ts).
- [ ] Register the key in [`registry/builtinBehaviors.ts`](../utk_curio/frontend/urban-workflows/src/registry/builtinBehaviors.ts).

**If it needs a backend or new dependencies**

- [ ] *(If backend)* New Flask blueprint under `utk_curio/backend/app/<feature>/`.
- [ ] *(If backend)* Register the blueprint in [`utk_curio/backend/app/__init__.py`](../utk_curio/backend/app/__init__.py).
- [ ] *(If new Python deps)* Add them to the package's `manifest.dependencies.python` (catalog install pip-installs them automatically; see §3.8); lazy-import in the route layer so a broken install returns 503 instead of crashing startup.
- [ ] User-facing docs example in `docs/examples/<NN>-<name>.md`, linked from [`docs/README.md`](README.md).

Skip any group that doesn't apply. A Python code-node needs only the first
group, because it reuses the built-in `code` behavior and ships no JavaScript at all.
The two behavior-hook groups are alternatives, not steps: pick the in-package
one unless you are adding a behavior to Curio itself.

## 8. Agent-authored packages

Everything above describes hand-authoring. Packages can also be **authored by
agents**: the **Package Builder** (`agent.package-builder`) turns a described need into one
reviewed draft through the `package.draft.apply` contract, and an **isolated build service**
does what `npm run build:packages` does for first-party packages - without ever touching this
repo's build list:

1. The typed draft (manifest, sources, behavior entries, dependencies, requested nodes) is
   validated under the same rules as §6 - installer path safety, `node-package.v4`, the works.
   `scripts/` is builder-owned: agents ship behavior **source**; the service compiles it.
2. JS dependencies resolve against the operator's approved registry only (pinned versions,
   SRI-verified, SBOM'd); the deployment-pinned compiler (`CURIO_BUILD_ESBUILD`) bundles them
   offline and externalizes React/ReactDOM/ReactFlow to the §5 host globals - the same
   externals contract as the webpack config, enforced rather than configured.
3. The bundle renders in a sandboxed preview (`CURIO_BUILD_PREVIEW_RUNNER`) across five contract
   states - empty, loading, success, malformed-input, error - and a failed preview blocks Apply.
   **Curio ships a reference runner** (Playwright driving headless Chromium, real
   measured dimensions and real screenshots, the host React globals injected exactly as the
   live runtime provides them): generate its pinned wrapper with
   `python -m utk_curio.tools.install_preview_runner` and export the printed
   `CURIO_BUILD_PREVIEW_RUNNER=…` line (prerequisites are named loudly at generation:
   `python -m playwright install chromium` and the frontend's `node_modules`).
   `CURIO_BUILD_PREVIEW_POLICY=skip` remains the fallback it was meant to be -
   for deployments that genuinely cannot run a browser, the draft reaches review unpreviewed
   with the skip recorded in its provenance and stated verbatim on the review card. Drop the
   stale skip once a runner is configured. The preview worker is bounded in CPU time, wall
   time, file size and open files, and not in address space or process count.
4. The user reviews the diff, dependencies, and preview; Apply promotes the **exact reviewed
   artifact digest** through the normal installer (backup held, journaled, rollback honest).

**Looks are prompt-driven, never repo fixtures**: the Package Builder's instruction
carries one generic authoring contract (register exactly the manifest's behavior keys; hook
`(data, nodeState) => { contentComponent }`; React elements only - never raw HTML; per-instance
color via `data.appearance.backgroundColor` with derived ink; self-contained, no network). The
scenario - e.g. the Researcher's post-it notes - lives in the CALLING agent's instruction as
requirements, and two runs may legitimately generate different code for the same look.

**Generated backend code runs in the package backend sandbox**: a package may declare `backend: { entry: "backend/<file>.py", handlers:
[{ name, timeoutClass }] }` plus the `server-code` permission (`server-network` too when its
code reaches the network - both are shown to the user at review), and link a template's Run
to a handler via `backendHandler`. The entry exposes `def handle(payload)` (or a `HANDLERS`
dict); a node run delivers `{"content": <editor text>, "input": <upstream JSON or null>}`
through `POST /api/packages/<dir>/backend/<handler>` - the ONLY caller surface. The code
never runs inside Curio's host process: each invocation spawns a short-lived worker with a
scrubbed from-scratch env (no secrets exist to steal), rlimits, wall-clock kill, and capped
I/O, speaking the versioned `curio.pkgbackend.v1` envelope; a capped persistent directory
rides `CURIO_PKG_DATA_DIR`. At build time a policy scan blocks the escape-hatch families
(subprocess/ctypes/dynamic code/resident frameworks; undeclared network) and a **probing
phase** loads every declared handler in a real sandbox worker - a failed probe blocks Apply
exactly as a failed preview. Both install authorities pin the entry's digest; invocation
verify-on-read refuses drift with reinstall guidance. Every invocation appends an audit row
(sizes and outcomes, never payloads) under `package-backend-ledger/`, archived by the
operator pruning it; nothing expires it automatically.
Operator seams: `CURIO_BACKEND_SANDBOX_PYTHON` pins the worker interpreter, and
`CURIO_BACKEND_OVERLAY_MAX_MB` (default 512) caps the per-package dependency overlay.
**Handler dependencies are isolated**: a backend-bearing package's declared python
deps install at Apply into `.curio/users/<key>/package-backend-overlays/<pkg>/` via
`pip --target` - the shared interpreter is touched only when the manifest also carries
warm-sandbox python templates, so a handler's dependencies cannot disturb the shared
interpreter, and the restart notice fires only for the shared-interpreter portion. Workers
receive the overlay on `PYTHONPATH` automatically; a post-Apply probe with the real overlay
gates activation (rollback on failure). Handlers therefore import declared dependencies
LAZILY inside `handle()` - they do not exist at build time, and the probe's refusal names
exactly that fix when an author forgets. Uninstall sweeps the overlay, data dir, and entry
pin; the invocation ledger survives for retention.

**Activation lifecycle**: invocations and
promotes serialize on one per-target lock, so an Apply and a node Run never interleave
observably; an install whose pip step *actually changed* shared Python libraries says
"Restart Curio to pick up <libs>" on its success surfaces (running nodes keep the previously
loaded versions until then - nothing is inferred, pip's own report is the truth); and a
handler whose sandbox workers fail three times in a row at the infrastructure level is
quarantined for 120s with an honest 503 (handler-level errors never count; a reinstall clears
it immediately). **Resident services, background jobs, and secret mediation remain out of
scope** - and a draft
needing them is refused with a finding naming exactly that.
