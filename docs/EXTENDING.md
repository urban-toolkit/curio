# Extending Curio with new node packages

Curio nodes are defined by **packages**, not by code. A package is a directory under [`packages/`](../packages/) that ships a `manifest.json` declaring one or more node *templates*. Each template references a **behavior key** that resolves to a React hook implementing the node's behaviour. Optionally, a behavior hook calls a backend route in Curio for work the browser and the sandbox cannot do.

This guide walks through adding a new node package end-to-end. Its examples are code in this repository: [`curio.example-ui@1`](../packages/curio.example-ui@1/) for a node with its own React interface (manifest, behavior hook, `behaviorScript` bundle), [`model.scout.deep-umbra@1`](../packages/model.scout.deep-umbra@1/) for a code node with Python dependencies declared in `manifest.dependencies.python`, a module of its own and sandbox helpers, the built-in Spatial Join for a node that calls a backend route, and the [Discovery Catalog](DISCOVERY-CATALOG.md) for third-party APIs, per-account keys and long downloads. Easier packages can skip several of the steps below.

> [!TIP]
> **Writing your first package?** Start with [`docs/AUTHORING-NODES.md`](AUTHORING-NODES.md), a task-ordered walkthrough from `git clone` to a working node, including the edit → rebuild → reload loop. Scaffold with `python scripts/new_package.py <id> [--with-ui]`, and read [`packages/curio.example-ui@1`](../packages/curio.example-ui@1/) for a minimal custom-UI node with no API keys or heavy dependencies. Come back here for the reference detail: backend blueprints, external services, dependency declaration, and the manifest's finer points.

## Every catalog is a folder of manifests

Each catalog lists folders, one per item, each with a `manifest.json` that declares what the item is and brings. The catalog's guide describes its manifest.

| Catalog | Shipped folder | Schema | Its manifest |
|---|---|---|---|
| Node | [`packages/`](../packages/) | [`node-package.v4.json`](schemas/node-package.v4.json) | [NODE-CATALOG §6](NODE-CATALOG.md#6-the-manifest) |
| Model | [`packages/`](../packages/), packages of kind `model` | [`node-package.v4.json`](schemas/node-package.v4.json) | [MODEL-CATALOG §6](MODEL-CATALOG.md#6-the-manifest) |
| Data | [`datasets/`](../datasets/) | [`dataset.v1.json`](schemas/dataset.v1.json) | [DATA-CATALOG §7](DATA-CATALOG.md#7-the-manifest) |
| Discovery | [`discovery/`](../discovery/) | [`discovery-source.v1.json`](schemas/discovery-source.v1.json) | [DISCOVERY-CATALOG §8](DISCOVERY-CATALOG.md#8-the-manifest) |
| Agent | [`agents/`](../agents/) | [`agent-package.v1.json`](schemas/agent-package.v1.json) | [AGENT-CATALOG §6](AGENT-CATALOG.md#6-the-manifest) |
| Skills the agents read | [`skills/`](../skills/), and a package's `skills/` | The frontmatter of the [Agent Skills format](https://agentskills.io/specification) | [§9 Writing a skill](#9-writing-a-skill) |

The Scenario Catalog has no manifests: it lists the scenarios saved in your projects. A skill's folder holds a `SKILL.md` in place of a `manifest.json`, and its frontmatter says what the skill is.

Curio's code names no artifact these folders ship: it reads what each one brings off its manifest, so yours gets what Curio's own get. [`test_no_artifact_ids_in_core.py`](../utk_curio/backend/tests/test_no_artifact_ids_in_core.py) fails on a shipped id in Curio's code, outside its short list of exceptions.

## 1. Anatomy of a package

```
packages/<packageId>@<major>/
├── manifest.json   ← declares templates, ports, behavior keys, deps
├── integrity.json  ← sha256 of every other file (regen with scripts/regen_integrity.py)
├── README.md       ← shown in the catalog UI
├── LICENSE         ← optional
├── sources/        ← Python / JS starters, or the TSX behavior hooks
├── scripts/        ← REQUIRED for custom UI: the compiled behaviors.js bundle
├── skills/         ← optional: what the package tells Curio's agents, one folder per skill (§9)
└── starters/       ← optional per-template starter snippets
```

A `template` inside `manifest.json` declares one node kind. It carries:

- `id` + `label` + `description` + `iconRef`: palette presentation. `iconRef` names any Font Awesome solid or brands icon, as `fa-solid:<name>` or `fa-brands:<name>` (`fa-solid:tree`, `fa-brands:github`)
- `category` (`data` | `computation` | `vis_grammar` | `vis_simple` | `flow`): palette sectioning, and the node's color: its border on the canvas, and its box in a dataflow's thumbnail on the **Projects** page, in the Scenario Catalog and in the provenance drawer
- `inputPorts` + `outputPorts`: port types and cardinalities (see [`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json))
- `editor` (`code` | `widgets` | `grammar` | `none`): what editor surface to mount
- `behavior`: string key resolved through [`registry/behaviorRegistry`](../utk_curio/frontend/urban-workflows/src/registry/behaviorRegistry.ts) to the React hook that implements the node's behaviour
- `engine` (`python` | `javascript`): if the node runs user code, which sandbox executes it. A template with `hasCode`, an `engine` and no `backendHandler` is one an agent's Solve runs in the sandbox to verify what it writes
- `source` + `starterIsContent`: the starter a fresh node opens with, and whether it is the node's whole content, set through the template's `widgets`. With `starterIsContent`, a node an agent's plan creates starts with the starter too, and Solve leaves it as it is ([Authoring nodes](AUTHORING-NODES.md#widgets-in-a-template))
- `widgets` + `opensOnControls`: the widgets a fresh node starts with, a node an agent creates included, and whether the node's Widgets tab shows only their controls and the node opens there ([Authoring nodes](AUTHORING-NODES.md#widgets-in-a-template))
- `loadsDataset`: a node of this template loads a dataset into the dataflow. The Dataset Finder attaches to it, Solve finds it a source before writing its code ([Agent Catalog](AGENT-CATALOG.md#solve)), and the Data Catalog counts the nodes after it as the dataset's consumers ([Data Catalog](DATA-CATALOG.md#lineage))
- `dataflowCategories` (`{"tags": [...], "dataTypes": [...]}`): the tags and data types a dataflow with a node of this template is filed under on the **Projects** page. At the top level of the manifest it covers every template of the package. Curio finds the rest in the dataflow itself, such as Pandas for code that imports it, so declare only what a node's code does not show ([Authoring nodes](AUTHORING-NODES.md#tags-and-data-types))

The frontend's package loader at [`registry/packagesClient.ts`](../utk_curio/frontend/urban-workflows/src/registry/packagesClient.ts) reads every installed package, calls `buildDescriptor()` per template, and registers them in the canvas's node-type registry. Adding a node is therefore *adding a manifest entry plus a behavior hook*; there is no monolithic switch-case anywhere.

## 2. When you need a backend blueprint, and when you don't

Three patterns cover essentially every node Curio ships:

| Pattern | Examples | Backend? |
|---|---|---|
| **Pure-frontend** | `vis-vega`, `vis-simple`, `autk-grammar`, `column-filter` (`curio.example-ui@1`) | None. The behavior hook does its work in the browser. |
| **Sandbox-Python** | `data-loading`, `data-transformation`, `computation-analysis`, `data-summary`, `accumulated-shadow` (`model.scout.deep-umbra@1`), `image-segmentation` (`model.curio.ddrnet23-slim@1`) | Reuses Curio's existing code sandbox at [`utk_curio/sandbox/`](../utk_curio/sandbox/) via the `code` behavior. User-provided Python runs out-of-process. A package template does the same with its own starter file and Python dependencies (§4.2). |
| **Backend route** | `spatial-join` (geopandas `sjoin`) | A route in Curio's backend that the behavior hook calls: Spatial Join's is one handler in [`api/routes.py`](../utk_curio/backend/app/api/routes.py) over a helper in [`common/spatial.py`](../utk_curio/backend/app/common/spatial.py). A feature with several routes gets its own Flask blueprint under [`utk_curio/backend/app/<feature>/`](../utk_curio/backend/app/) (§5). Right call when the node needs server-side work the sandbox can't reasonably do. |

Pure-frontend is the right default; reach for the sandbox before a blueprint, and only stand up a blueprint when neither covers it. Third-party data and models come in through the Discovery Catalog (§3), and a node reads them from the Data or Model Catalog.

## 3. Connecting to external services

A third-party API reaches Curio as a **source** in the [Discovery Catalog](DISCOVERY-CATALOG.md): a manifest at `discovery/<sourceId>@<major>/manifest.json` names the host, the key it sends and what it offers, and a provider module under [`utk_curio/backend/app/discovery/providers/`](../utk_curio/backend/app/discovery/providers/) speaks the API. Street-level photos arrive this way, from [`source.mapillary.imagery@1`](../discovery/source.mapillary.imagery@1/manifest.json) ([`providers/mapillary.py`](../utk_curio/backend/app/discovery/providers/mapillary.py)) and [`source.google.street-view@1`](../discovery/source.google.street-view@1/manifest.json) ([`providers/google_streetview.py`](../utk_curio/backend/app/discovery/providers/google_streetview.py)), and image segmentation models from [`source.huggingface.models@1`](../discovery/source.huggingface.models@1/manifest.json) ([`providers/huggingface_models.py`](../utk_curio/backend/app/discovery/providers/huggingface_models.py)). A download lands in the Data Catalog (a model, in the Model Catalog), and a node reads it from there with `curio_load_collection("<id>")`, `curio_data_path("<id>")` or `curio_load_model("<id>")`. The patterns below are the conventions that code follows; [ARCHITECTURE.md, Providers](ARCHITECTURE.md#providers) lists the steps to add a provider.

### 3.1 Always proxy through the backend

Never call third-party APIs from the browser directly:

1. **API keys leak.** Anything built into the frontend bundle, even read-at-runtime values, is visible in DevTools' network tab.
2. **CORS.** Most public APIs (Google, Nominatim) reject browser-origin requests.
3. **Rate-limit hygiene.** Centralising in the backend lets you add caching, retries, and per-user quota in one place.

Every Discovery request leaves the backend through one transport, [`discovery/infrastructure/transport.py`](../utk_curio/backend/app/discovery/infrastructure/transport.py): `HttpDiscoveryTransport` sends it under the egress policy with a timeout (`METADATA_TIMEOUT_S`) and a size bound, and refuses an answer that is not a 2xx. A source's `limits.requestsPerMinute` bounds each account's requests to it. A behavior hook that needs the backend calls a Curio route, as [`spatialJoinBehavior.tsx`](../utk_curio/frontend/urban-workflows/src/adapters/node/spatialJoinBehavior.tsx) posts to `${backendUrl()}/spatial_join`.

### 3.2 API keys: a row in API Settings

Pick the pattern by who the key belongs to:

- **Per-account keys** (a Mapillary access token, a Google Maps API key, a Hugging Face token) are **Data source** keys on the **API keys** tab of **API Settings**, never a node input, a line of node code or a field of the dataflow spec. A new key needs only its source manifest's `auth` block (§3.4): no column, migration or list in Curio's code.
  - `secretId` names the key, and the sources that send one key name the same id.
  - `label` is what API Settings calls it (the `secretId` when absent), `helpUrl` where a person gets one, `placeholder` what the empty field shows, and `note` a sentence under the field. Sources that send one key declare these the same way.
  - `"operatorDefault": true` lets whoever runs Curio set one key every account inherits until it saves its own, in the variable `CURIO_DEFAULT_` followed by the `secretId` in capitals, with every other character as `_` (`CURIO_DEFAULT_SOCRATA_APP_TOKEN` for `socrata.app-token`). A manifest never names a variable, and a manifest whose `secretId` would read one of Curio's own settings under that prefix (`CURIO_DEFAULT_LLM_*`, `CURIO_DEFAULT_SAVE_NODE_OUTPUT`) with `operatorDefault` fails to load.
  - API Settings lists one row per `secretId` (`key_rows` in [`discovery/infrastructure/credentials.py`](../utk_curio/backend/app/discovery/infrastructure/credentials.py)): it offers each key without a saved one in the **Kind** list of **Add configuration**, and lists a key once one is saved or the operator supplies one.
  - `PATCH /api/auth/me` saves an account's keys by `secretId` under `source_keys`, in an owner-only file beside its other per-user stores ([`users/source_keys.py`](../utk_curio/backend/app/users/source_keys.py)), and refuses a `secretId` no source declares.

- **Several named secrets per account** (node code keys, LLM configurations) go in an owner-only per-user file written through [`common/owner_only_file.py`](../utk_curio/backend/app/common/owner_only_file.py), as [`users/connection_keys.py`](../utk_curio/backend/app/users/connection_keys.py) and [`agents/infrastructure/llm_configs.py`](../utk_curio/backend/app/agents/infrastructure/llm_configs.py) do.

- **Genuinely operator-wide secrets** that no user should override (an internal data-source token) -> `os.environ.get(...)` at the backend, read at request time so editing `.env` + restart picks it up without rebuilding. Prefer a documented `curio.py start` flag that names the variable, so the knob is discoverable.

Three rules the per-account pattern follows:

**The key goes only to its source's origin.** `_transport_for` in
[`discovery/service.py`](../utk_curio/backend/app/discovery/service.py) wraps
the transport in `CredentialedTransport` with the source's `provider.baseUrl`;
a request to any other scheme, host or port, such as a Mapillary photo on its
CDN, goes without the key. `credential_header` turns the key into a header
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
every key with booleans only: `present` (this account saved one) and
`inherited` (the deployment supplies one). The user payload's
`has_source_keys` maps the `secretId` of each key the account saved to `true`.

A package whose backend needs to know *who* is calling must send the bearer
token: read `window.curio.getAuthToken()` (a getter, because a package bundle
evaluates once at boot, before sign-in) and pass it as an `Authorization`
header. Never check secrets into git.

### 3.3 Public APIs without auth

Nominatim, OpenStreetMap's geocoder, is free and public; it answers the place search of every source's area field. [`discovery/application/places.py`](../utk_curio/backend/app/discovery/application/places.py) follows its usage policy: a `User-Agent` that names Curio, at most one request a second from the server (`MIN_INTERVAL_S`), and answers kept for a day (`CACHE_TTL_S`). A search takes the next free second under the lock and waits for it outside, so a cached answer never waits on Nominatim:

```python
# places.py
with _lock:
    hit = _cache.get(key)
    if hit is not None and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    slot = _take_slot()
wait = slot - time.monotonic()
if wait > 0:
    time.sleep(wait)
payload = transport.json_get(
    search_url(text),
    headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
)
```

Read a public API's usage policy before shipping a source that calls it in a loop, and **cache aggressively** (a single user might re-search the same place a dozen times in one session). Code that calls `requests` itself sets a **timeout** (`requests`'s default is "wait forever") and checks the response status; the Discovery transport does both.

### 3.4 APIs with API keys

A source declares its key in the manifest's `auth` block, which is also its row in API Settings (§3.2). Mapillary sends its token as a header:

```json
"auth": {
  "mode": "required-token",
  "secretId": "mapillary.token",
  "headerName": "Authorization",
  "valuePrefix": "OAuth ",
  "label": "Mapillary access token",
  "helpUrl": "https://www.mapillary.com/dashboard/developers",
  "placeholder": "MLY|...",
  "note": "Mapillary images are CC BY-SA 4.0: each one keeps its creator for attribution."
}
```

Google Street View sends its key as a query parameter:

```json
"auth": {
  "mode": "required-token",
  "secretId": "google.maps-key",
  "scheme": "query",
  "paramName": "key",
  "label": "Google Maps API key",
  "helpUrl": "https://developers.google.com/maps/documentation/streetview/get-api-key",
  "placeholder": "AIza..."
}
```

An `optional-token` source (Hugging Face models) sends the key when the account has one and asks without it otherwise. A `required-token` source the account holds no key for is refused before any job exists: `start_acquire` raises `CredentialRequired` (a `428`) naming the key's `secretId` and the help link, and a search leg reports `needs-token`. A missing key is a message naming what to do, never a stacktrace.

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
- **Store per user, serve by id.** A bucket collection's files are cached under the account's own media directory (`media_work_root` in [`discovery/infrastructure/media_dirs.py`](../utk_curio/backend/app/discovery/infrastructure/media_dirs.py)) by [`application/cache_collection.py`](../utk_curio/backend/app/discovery/application/cache_collection.py), capped by `--media-cache-max-gb` (`CURIO_MEDIA_CACHE_MAX_GB`), and the files a node derives with `curio_derived_file` go beside them. Both are served by id from `@require_auth` routes in [`discovery/media_routes.py`](../utk_curio/backend/app/discovery/media_routes.py) (`/api/datasets/<dataset_id>/media/<file_id>`), which look the file up in the caller's own dataset and never take a path from the request.

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

Curio's `requirements.txt` / `pyproject.toml::dependencies` carries **only** the framework: what the backend and sandbox Flask apps need at module load (Flask, SQLAlchemy, requests, the LLM SDKs, etc.). **Every node package** ships its own data-ops libs in its manifest's `dependencies.python`, including the bundled `curio.builtin@1` (pandas, geopandas, etc.) and optional packages like `curio.weather@1` (rasterio, pythermalcomfort, rasterstats) and the model package `model.curio.ddrnet23-slim@1` (onnxruntime). The `curio start` launcher walks every installed manifest at startup, merges them into a single conflict-aware union, and pip-installs the result before booting the subprocesses. See [`cli/dependencies.py::install_manifest_dependencies`](../utk_curio/cli/dependencies.py) for the walker.

Declare your package's deps in `manifest.dependencies.python`:

```json
{
  "id": "model.curio.ddrnet23-slim",
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

A model in the Model Catalog is a model package, so it declares its runtime's libraries the same way, and they install when the model is added, by the path every package takes. A model added from the Discovery Catalog declares `onnxruntime` for an ONNX graph, or `torch`, `transformers` and `safetensors` for a Transformers checkpoint (`RUNTIME_DEPS` in [`discovery/application/model_acquire.py`](../utk_curio/backend/app/discovery/application/model_acquire.py)).

#### How the install/uninstall flow handles them

- **Adding a package from the catalog** copies the package files, then runs `pip install` (via [`utk_curio/backend/app/packages/infrastructure/pip_runner.py`](../utk_curio/backend/app/packages/infrastructure/pip_runner.py)) for every dep that isn't already importable. Already-satisfied deps are skipped, so re-adding the same package is near-instant. The request blocks until pip finishes (v1 sync UX); the confirm button stays busy.
- **Removing a package** (when its user-store copy is being pruned) walks every other still-installed package's manifest, finds the python deps the pruned package declared that **no other package needs**, and pip-uninstalls those. Shared deps stay.
- A failed pip install rolls back the package's user-store copy so the user can retry cleanly. The Flask response carries the tail of pip's stderr so the user knows what failed (network error, version conflict, missing wheel, etc.).

#### Packages a package needs

A package whose code imports another package's modules names that package in `dependencies.packages`, as `"<packageId>@<major>": "<version range>"`, or a bare `"<packageId>"` for any major:

```json
"dependencies": {
  "js": {},
  "packages": { "ai.example.shared@1": "*" },
  "python": {}
}
```

Its nodes can import the modules the named package ships in `sources/`, and those of the packages that one names in turn ([`packages/application/python_modules.py`](../utk_curio/backend/app/packages/application/python_modules.py)). Adding the package adds them all, the same way on every path: **Add to project** and a card dropped on the canvas, **Add to all projects**, opening a dataflow whose lockfile names the package, and the examples' seeding at launch (`--with-examples`).

- One function resolves what an add brings: `required_packages` in [`packages/domain/package_closure.py`](../utk_curio/backend/app/packages/domain/package_closure.py), the package and every package it needs, transitively, each once, a cycle included. An entry takes the account's copy when its range allows that copy's version, and an add never replaces a copy in the account. Otherwise it takes the shared catalog's copy at the highest major the range allows.
- Everything is resolved before anything is copied. A package that neither the account nor the catalog holds at an allowed version refuses the add and names that package and the one that needs it. The packages it needs are copied first, each with its Python libraries, and a failure part way takes back every copy the add made.
- The dataflow's lockfile records each package. A bare `<packageId>` entry with several majors in the account takes the major the lockfile names, as a node's own package does.
- The review before an add lists them under **Dependencies**, and its conflict probe (`POST /api/packages/resolve`) resolves them from the catalog with the package, their libraries included.

#### When to still lazy-import

Even though deps are installed up front, lazy-import expensive libraries inside the code that needs them so a broken install fails per-request with a clean 503 instead of crashing the backend on startup. The Spatial Join's helper in [`common/spatial.py`](../utk_curio/backend/app/common/spatial.py) imports geopandas inside its functions, and the route turns the `ImportError` into a 503:

```python
# api/routes.py
@bp.route('/spatial_join', methods=['POST'])
def spatial_join():
    # ...
    try:
        result = join(
            body.get("left"),
            body.get("right"),
            predicate=body.get("predicate") or DEFAULT_PREDICATE,
            output=body.get("output") or DEFAULT_OUTPUT,
        )
    except JoinInputError as e:
        return jsonify({"error": str(e)}), 400
    except ImportError as e:
        return jsonify({
            "error": "spatial extras not installed (geopandas required)",
            "hint": "pip install geopandas",
            "detail": str(e),
        }), 503
    # ...
```

Sandbox helpers follow the same rule: `curio_segment` imports `onnxruntime`, or `torch` and `transformers`, only when it loads a model of that runtime, and a missing library stops that node's run with a `RuntimeError` saying which runtime is missing (`_OnnxRunner` and `_TransformersRunner` in [`sandbox/util/vision.py`](../utk_curio/sandbox/util/vision.py)).

## 4. Walked example: three nodes

One node per pattern in §2: Column Filter (`curio.example-ui@1`) renders its own interface, Accumulated Shadow (`model.scout.deep-umbra@1`) is a code node in a package, and Spatial Join (`curio.builtin@1`) calls a backend route.

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

### 4.2 A code template in [`packages/model.scout.deep-umbra@1/manifest.json`](../packages/model.scout.deep-umbra@1/manifest.json)

```jsonc
"kind": "model",
"dependencies": { "js": {}, "packages": { "curio.scout@1": "*" },
                  "python": { "numpy": "", "onnxruntime": ">=1.17", "pyproj": ">=3.7.2", "rasterio": ">=1.4" } },
"model": { "type": "image-to-image", "runtime": "onnx", "entry": "models/deep_umbra.onnx", ... },
"templates": [
  { "id": "accumulated-shadow", "behavior": "code", "editor": "code", "engine": "python",
    "source": "sources/accumulated-shadow.py",
    "widgets": [{ "name": "season", "type": "choice", "default": "summer",
                  "options": { "choices": ["spring", "summer", "winter"], "display": "radio" } }],
    "inputPorts":  [{"cardinality":"1","types":["RASTER"]}],
    "outputPorts": [{"cardinality":"1","types":["RASTER"]}] }
]
```

An input port's `cardinality` sets how many edges the node takes. `"1"` takes one. A single port whose maximum is more than one (`"[1,2]"`, `"[1,n]"`) gives the node a new input circle for each edge, up to that maximum; its code receives them as a list in circle order and reads each through an input chip, `[!! input_1 !!]` (USAGE.md, "Several inputs"). Several input ports take one edge each, on the circles `in`, `in_1` and so on, as Spatial Join's input_0 and input_1.

The template reuses the built-in `code` behavior, so the package ships no JavaScript and no `behaviorScript`. `source` is the starter a new node opens with, [`sources/accumulated-shadow.py`](../packages/model.scout.deep-umbra@1/sources/accumulated-shadow.py); it imports the package's own module, `deep_umbra` (`sources/deep_umbra/`), and reads the Season widget through its chip:

```python
from deep_umbra import accumulated_shadow
model = curio_load_model("model.scout.deep-umbra")
return accumulated_shadow(input_0, season=[!! season !!], model=model, output_file=curio_output_file)
```

`deep_umbra` imports `tile_bounds` from `scout_rasters`, the module of the Scout package, which Deep Umbra names in `dependencies.packages`. Adding Deep Umbra adds Scout too (§3.8, "Packages a package needs").

Agents read the same files. A run that writes an Accumulated Shadow node's code gets the template's whole `description`, this starter, and the public functions of `deep_umbra` and of `scout_rasters`, each by its signature and the first paragraph of its docstring, the functions the starter imports first. They are read from the sources with `ast`, never imported (`read_functions` in [`packages/domain/function_nodes.py`](../utk_curio/backend/app/packages/domain/function_nodes.py)), from the modules the sandbox makes importable for the node (`modules_for_node`), in the run's dataflow block ([ARCHITECTURE.md, Agent Prompt Composition](ARCHITECTURE.md#agent-prompt-composition)). `packages.resolve` gives an agent a package's functions and its `dependencies.packages` too. The preamble names no package's templates or functions, so a package documents its functions in their docstrings and shows their use in its starters: that is what an agent knows of them.

A model package's template may ship no `source`: DDRNet23-Slim's Image Segmentation ([`packages/model.curio.ddrnet23-slim@1`](../packages/model.curio.ddrnet23-slim@1/manifest.json)) opens with the cell the backend writes for its model's type (`model_default_cell` in [`packages/application/model_packages.py`](../utk_curio/backend/app/packages/application/model_packages.py), served with the starters):

```python
model = curio_load_model("model.curio.ddrnet23-slim")
classes = None  # every class the model names

return curio_segment(input_0, model, classes)
```

These helpers are in the sandbox's namespace for every Python node, with the other functions node code calls, each given with its arguments in [the functions page](../skills/node-functions/SKILL.md):

- `curio_load_model("<model id>")` ([`sandbox/util/catalog_helpers.py`](../utk_curio/sandbox/util/catalog_helpers.py)) loads a model package's model: its `folder`, its `manifest`, its `labels`, the `runner` that labels an image's pixels, opened on first use, and `run`, which feeds an ONNX graph the arrays a node prepared. Before the run the backend resolves every id a node's code names to the folder of a model package in the account's store (`resolve_models` in [`execution/node_exec.py`](../utk_curio/backend/app/execution/node_exec.py), over `packages.service.resolve_model_dirs`); a model the store does not hold gets none, and the call says to add it. Models ship as model packages under [`packages/`](../packages/), or are added from the Discovery Catalog's Hugging Face models source (§3).
- `curio_segment(images, model, classes=None, *, overlays=True)` ([`sandbox/util/vision.py`](../utk_curio/sandbox/util/vision.py)) runs a loaded segmentation model the way its manifest describes (a `runtime` of `onnx` on onnxruntime, `transformers` on Transformers) over every row's `path`, and returns the rows with `dominant_class`, `dominant_pct`, a `<class>_pct` per class, `overlay_url` and `segment_error` first. With `overlays`, each overlay is written with `curio_derived_file` (kind `"image"`, [`sandbox/util/collections.py`](../utk_curio/sandbox/util/collections.py)) and served back by the media route (§3.6).

### 4.3 A built-in template in [`packages/curio.builtin@1/manifest.json`](../packages/curio.builtin@1/manifest.json)

A generic Spatial Join that pairs the rows of two inputs whose shapes meet, by an operation picked on the node (or emits input_1's rows with a count of their pairs):

```jsonc
{ "id": "spatial-join", "behavior": "spatial-join",
  "inputPorts": [
    {"types":["GEODATAFRAME"]},   // input_0, the left side (circle `in`, top of node)
    {"types":["GEODATAFRAME"]}    // input_1, the right side (circle `in_1`, bottom of node)
  ],
  "outputPorts": [{"types":["GEODATAFRAME"]}]
}
```

This one belongs in `curio.builtin@1`, not in a model package, because it's reusable for any spatial workflow. Generally: if a capability is reusable outside the package's narrow theme, factor it out into builtin.

The agents' prompts describe every `curio.builtin@1` template from this manifest: the shared preamble gives its label, description, control, port types, how many connections its inputs accept, and interaction support, and other prompts name templates by label. The backend reads them from the manifest when it starts, so those lists follow a built-in template you add or change with no other edit (see [CONTRIBUTING.md, Agent Text](CONTRIBUTING.md#agent-text)).

A new feature of Curio, a built-in template among them, also gets a skill in [`skills/`](../skills/), in the same change: what the feature does, written for the agents, in a skill the agents that work with it name in their manifests ([§9](#9-writing-a-skill)). A built-in template is in a skill when a skill names it as `{{template.label:curio.builtin/<id>}}`, a kind of chip when a skill shows one through its marker, and a function node code calls when [the functions page](../skills/node-functions/SKILL.md) gives it, in that page's fixed line shapes (`agents/domain/node_functions.py` reads them). `test_feature_skills.py` fails while one is in no skill, and `test_node_functions_sandbox.py` while the functions page and what node code gets in each engine differ.

### 4.4 Behavior hooks

Column Filter's hook ships inside its package, at [`packages/curio.example-ui@1/sources/`](../packages/curio.example-ui@1/sources/); Spatial Join's lives with the built-ins in [`utk_curio/frontend/urban-workflows/src/adapters/node/`](../utk_curio/frontend/urban-workflows/src/adapters/node/). Accumulated Shadow runs on the built-in `code` behavior and needs no hook of its own.

- [`columnFilterBehavior.tsx`](../packages/curio.example-ui@1/sources/columnFilterBehavior.tsx): reads `data.input` with `resolveInput`, which reads a sandbox artifact reference with `window.curio.fetchData` and passes an inline payload through; keeps the column, comparison and threshold in `useState`; sends the matching rows downstream with `data.outputCallback` and reports through `nodeState.setOutput`. It returns only `contentComponent`.
- [`spatialJoinBehavior.tsx`](../utk_curio/frontend/urban-workflows/src/adapters/node/spatialJoinBehavior.tsx): the only node here with two input ports, whose circles it draws with `handlesOverride`. Keeps what each circle holds apart (`data.portInputs`) and posts both inputs to `/spatial_join` (§4.5). Worth reading if you ever need a 2-input node.

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

Spatial Join's route is a single handler at the end of [`api/routes.py`](../utk_curio/backend/app/api/routes.py) (`POST /spatial_join`) that calls the generic `spatial_join` helper at [`utk_curio/backend/app/common/spatial.py`](../utk_curio/backend/app/common/spatial.py), on geopandas `sjoin`. Reusable utilities like that belong under `common/`, not in any specific blueprint. Accumulated Shadow has no route of its own: its work runs in the sandbox.

### 4.6 Shipping the package

The three packages are bundled in-repo under [`packages/`](../packages/). Seeding covers `curio.builtin@1` plus, when Curio starts with `--with-examples`, whatever the shipped example dataflows declare as dependencies (`example_dep_package_ids` in [`backend/app/packages/application/seeding.py`](../utk_curio/backend/app/packages/application/seeding.py)). Example 24 declares `model.scout.deep-umbra@1`, so Deep Umbra is installed with the examples. `curio.example-ui@1` is in neither set: users opt in by clicking **Add to project** in the catalog. Generally:

- **Bundled-and-auto-installed** → `curio.builtin@1`, which every user must have, and, with `--with-examples`, the packages a shipped dataflow declares (`curio.weather@1`, `curio.media@1`, `curio.scout@1`, and the model packages `model.curio.ddrnet23-slim@1`, `model.scout.deep-umbra@1` and `model.scout.weather-gnn@1`).
- **Bundled-and-installable** → optional first-party packages like `curio.example-ui@1`, `ai.utk.uhvi@1`. Visible in the catalog without a remote registry roundtrip.
- **Remote** → publishing through Curio's catalog endpoint, for third-party packages. Same manifest schema.

### 4.7 How behavior distribution works (and why)

When you install a package that ships its own custom node UIs, Curio needs to find a way to load the behavior JavaScript without rebuilding the main app. The mechanism in place today:

1. **The package directory contains both the manifest *and* a pre-built `scripts/behaviors.js`.** For first-party packages (in-repo), `npm run build` produces that JS via [`webpack.packages.config.js`](../utk_curio/frontend/urban-workflows/webpack.packages.config.js). Third-party authors compile their own. The bundle lives under `scripts/` because that subdirectory is one of the archive validator's allowed top-level dirs (see [`archive.py::_ALLOWED_TOP_DIRS`](../utk_curio/backend/app/packages/repositories/archive.py)), so the bundle survives the catalog install round-trip.
2. **The manifest declares the bundle via `behaviorScript: "scripts/behaviors.js"`** (a top-level field, not per-template). The path is relative to the package directory; any allowed-subdirectory location works.
3. **At app boot, the frontend's `loadInstalledPackages` fetches `/api/packages/<dirName>/file/scripts/behaviors.js` with the user's Bearer token and injects the response body as an inline `<script>` BEFORE building descriptors**. (A plain `<script src>` can't carry an `Authorization` header, so Firefox's OpaqueResponseBlocking would reject the `require_auth` 401 response, and the inline-injection path bypasses that.) The bundle's top-level side-effect calls `window.curio.registerBehavior(...)` for each behavior hook it ships. By the time `buildDescriptor` looks up `getBehavior('column-filter')`, the key is registered.

   The bundle reads an upstream output with `window.curio.fetchData`, the function the canvas reads outputs with, which reads on the open dataflow's route. It reads its backend URL at runtime from `window.curio.backendUrl`, never from a build-time `process.env.BACKEND_URL`. Curio's main bundle exposes both in [`src/registry/index.ts`](../utk_curio/frontend/urban-workflows/src/registry/index.ts).
4. **The behavior bundle externalises React, ReactDOM, ReactFlow, and `registerBehavior`** so it shares Curio's instances at runtime. Curio's main bundle exposes them as `window.React`, `window.ReactDOM`, `window.ReactFlow`, `window.curio.registerBehavior` ([`src/registry/index.ts`](../utk_curio/frontend/urban-workflows/src/registry/index.ts)). Without this, distinct React copies would break rules-of-hooks.
5. **If the bundle fails to load** (network error, hash mismatch, parse error), the package's templates fall back to `usePackageNodeBehavior` (a generic code-editor). The palette still renders; the user just gets the default UI instead of the package's custom UI.

This means *adding a new package to a running Curio instance does not require rebuilding Curio*, because the package's `scripts/behaviors.js` is loaded dynamically. Authors bundle once; deployments stay decoupled.

The behaviors in `curio.builtin@1` (`code`, `vega`, `spatial-join`, `data-pool`, …) are an exception: they live in Curio's main bundle because they must be registered before *any* package registry exists.

## 5. Recipe: add a Flask blueprint

When your node needs server-side capabilities the sandbox can't provide, add a route. A single route can join an existing blueprint, as Spatial Join's joins the `api` blueprint (§4.5). A feature with several routes gets its own blueprint under `utk_curio/backend/app/<feature>/`, as the Scenario Catalog does ([`scenario_catalog/routes.py`](../utk_curio/backend/app/scenario_catalog/routes.py): `scenarios_bp`, under `/api/scenarios`). Third-party APIs and long downloads are Discovery Catalog sources and jobs (§3).

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
     //   manifest; see §4.4 for the spatial-join hook).
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
   `behaviorScript` is a path relative to the package directory. The archive validator only accepts a small set of top-level dirs (see [`archive.py::_ALLOWED_TOP_DIRS`](../utk_curio/backend/app/packages/repositories/archive.py): `sources`, `starters`, `grammars`, `widgets`, `icons`, `scripts`, `backend`, and `models` in a model package); the bundle goes under `scripts/` so it survives the catalog round-trip. Curio's package registry bootstrap fetches the file with the user's Bearer token and injects the response body as an inline `<script>` BEFORE building descriptors, so the behavior keys are registered by the time `getBehavior('my-node')` looks them up.

6. **Build the bundle.** `npm run build:packages` compiles `sources/index.tsx` into the file `behaviorScript` names, `<package-dir>/scripts/behaviors.js`, as UMD output, externalizing React / ReactDOM / ReactFlow so the bundle shares Curio's instances at runtime (essential for rules-of-hooks). Its config, [`webpack.packages.config.js`](../utk_curio/frontend/urban-workflows/webpack.packages.config.js), bundles every package under `packages/` whose manifest declares `behaviorScript` and that holds `sources/index.tsx`. That target takes a couple of seconds and is all you need for a package-only change; `npm run build` chains it after the much slower full app build.

   Rebuilding the bundle is only half of it: the frontend loads `behaviorScript` from your **installed** copy in the user store, so after every rebuild reload the page: opening a dataflow replaces the installed copy with the rebuilt one, unless you edited the installed copy yourself. See [`docs/AUTHORING-NODES.md`](AUTHORING-NODES.md) for the whole loop.

   **Packages built outside this repo** ship their own pre-built `scripts/behaviors.js`, with no `sources/index.tsx`, since Curio loads any `behaviorScript` it finds in an installed package regardless of who built it. There is no separate toolchain for that case: the practical route is to author inside a Curio checkout (where `registry/types` resolves and this build config exists), then distribute the resulting `.curio.zip`.

7. **Pick an icon.** A template's `iconRef` names any icon of Font Awesome's free solid or brands set, by the name [fontawesome.com](https://fontawesome.com/icons) gives it: `"iconRef": "fa-solid:tree"` or `"iconRef": "fa-brands:github"`. Curio loads it when it builds the palette; nothing in Curio needs editing. A name Font Awesome does not have shows a cube, with a one-time console warning.

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

- [ ] `packages/<id>@<major>/manifest.json`: templates with behavior keys, port shapes, palette ordering, and an `iconRef` naming any Font Awesome solid or brands icon (§6 step 7).
- [ ] `packages/<id>@<major>/README.md`: shown in the catalog. Cover setup, env vars, costs.
- [ ] `packages/<id>@<major>/integrity.json`: regenerate after every edit with `python scripts/regen_integrity.py packages/<id>@<major>` (§6 step 8).
- [ ] *(If a dataflow that uses it belongs under a tag or a data type its code does not show)* `dataflowCategories` in the manifest (§1).

**Behavior hooks in the package** (the normal case: no Curio rebuild needed)

- [ ] Hook at `packages/<id>@<major>/sources/<name>Behavior.tsx` (§6 step 3).
- [ ] Registration entry point at `packages/<id>@<major>/sources/index.tsx`, calling `window.curio.registerBehavior(...)` (§6 step 4).
- [ ] `"behaviorScript": "scripts/behaviors.js"` at the top level of the manifest (§6 step 5).
- [ ] `npm run build:packages`, which writes the bundle `behaviorScript` names (§6 step 6).

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
agents**: the **Node Builder** (`agent.curio.node-builder`) writes them in its package-writing mode
(`package.build`, `package.extend`, `node.kind.author`), which its own chat, the Researcher
and the Dataflow Builder ask for. The mode turns a described need into one reviewed draft
through the `package.draft.apply` contract, and an **isolated build service**
does what `npm run build:packages` does for first-party packages - without ever touching this
repo's build list:

1. The typed draft (manifest, sources, behavior entries, dependencies, requested nodes) is
   validated under the same rules as §6 - installer path safety, `node-package.v4`, the works.
   `scripts/` is builder-owned: agents ship behavior **source**; the service compiles it.
   Every template the draft adds needs the draft's `justification` (the closest existing
   templates and why each is inadequate) and a label no template of the dataflow has, and
   when its nodes hold code, that code reads only sources Curio can ground. A draft that
   misses one of these is refused before it is built, with what to change.
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
   stale skip once a runner is configured. Every package worker (the compiler, the preview,
   a backend probe or call) is bounded in CPU time, wall time, file size and open files, and
   on Windows in process count. On Linux all but the preview are also bounded in address
   space.
4. The user reviews the justification, the diff, dependencies, and preview; Apply promotes
   the **exact reviewed artifact digest** through the normal installer (backup held,
   journaled, rollback honest).

**Looks are prompt-driven, never repo fixtures**: the package-writing mode's prompt
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

## 9. Writing a skill

A skill tells Curio's agents how to do a specific task: instructions, procedural knowledge and reference facts, written for an agent. Curio's skills are in [`skills/`](../skills/), one folder each, in the open [Agent Skills format](https://agentskills.io/specification), and a package's in its own `skills/` (below).

**The folder.** A skill is `skills/<name>/SKILL.md`, in a folder named as the skill: YAML frontmatter between two `---` lines, then the body, the Markdown an agent reads. Files a skill keeps beside its `SKILL.md`, such as `references/REFERENCE.md`, sit one level below its folder, as the format asks; a run reads the body of `SKILL.md`, and a chat reads one of those files with skill.read when the body names it. The skill's evaluations, in its `evals/` folder, are never among them ([Evaluating a skill](#evaluating-a-skill)).

**The frontmatter** holds the format's fields and no other:

```yaml
---
name: widgets
description: >-
  Use this skill when a node declares, places or changes a widget, such as a threshold, a year or
  a dataset the user sets without editing code, or when several nodes share one value.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
  curio-behaviors: code data-export data-summary edit-features vega autk-grammar
---
```

- `name`: the folder's name, 1 to 64 lowercase letters, digits and hyphens, with no hyphen first or last and none twice in a row.
- `description`: when to use the skill, in 1 to 1,024 characters. Start it with "Use this skill when", name the task in the words a user types for it, not in the words of the skill's own mechanics, including requests that never name the skill's subject ("even if they never say catalog"), and say what the skill gives beyond the tools that could answer alone. Where a near task belongs to another skill, say so. In the format, the description is what an agent reads of a skill before it loads it, so it says when to use the skill, not only what the skill is ([optimizing descriptions](https://agentskills.io/skill-creation/optimizing-descriptions)).
- `license`, `compatibility` (at most 500 characters) and `metadata`, strings by string keys, which holds Curio's facts about the skill: Curio's skills give `MIT`, the compatibility above, and `author` and `version`, the version quoted so YAML reads it as a string. Three more keys say what the skill serves, each a list of names with a space between each: `curio-behaviors`, the node behaviors (a template's `behavior`, such as `code`, `vega`, `autk-grammar` or `edit-features`) whose nodes a run writing one is handed the skill for; `curio-features`, the features of a dataflow (`scenario-boxes`, `interaction-edges`, `pinned-tiles`) a run reading one with them is handed it for; and `curio-refusals`, the kinds a Solve check records when it refuses an attempt, whose next attempt is handed the skill. A package's skill can name a fourth, `curio-templates` (below). The format's `allowed-tools` is allowed too, and Curio's skills leave it out.
- A value that holds `: ` or ` #` goes in a folded block (`>-`), as the description above does, or in quotes: YAML reads those as a field's end and a comment.

**The body** starts on the line after the closing `---`. It may hold Curio's markers wherever it states a fact the code owns, as the pages of the base entry do ([its README](../agents/agent.curio.builtin@1/README.md#editing-a-page)), and the backend fills them when it starts. A page or a prompt places a skill as `{{skill:<name>}}`, its body rendered without its frontmatter; the preamble places the core skills, `nodes`, `node-control` and `compatibility`, so every agent reads them. Keep `SKILL.md` under 500 lines.

**Who reads it.** An agent reads a skill its manifest names in `skills` ([AGENT-CATALOG § Skills](AGENT-CATALOG.md#skills)): its chat lists the skill and loads it when a task matches the description, and its modes are handed it when what they work on is what the skill serves. Add a new skill to the `skills` of each agent in `agents/` that should read it; an agent of a user's that names no skills reads every skill Curio ships. A skill that holds a procedure a prompt follows, such as `reuse-first`, serves no behavior or feature: the prompt's runs are handed it by name, a mode's in its capability's `skills` and a chat's in its instruction's (`prompts.instruction.skills`), and the prompt keeps its role and its rules, not the procedure's text.

**A user's skills.** A user's skill is kept in their account, not in `skills/`: **Import skill** reads it leniently and keeps it in the format, and an agent of theirs holds it when the agent's manifest names it in `skills`, as the agents in `agents/` name Curio's. The worked example of [Add skills and agents](AGENT-CATALOG.md#add-skills-and-agents) is such a skill and an agent that names it: [`docs/examples/skills/street-trees/`](examples/skills/street-trees/SKILL.md) and [`docs/examples/agents/agent.you.tree-counter@1/`](examples/agents/agent.you.tree-counter@1/manifest.json). `test_skill_and_agent_example.py` imports both as a user does and loads the skill in a chat, and `test_user_skills_e2e.py` imports the same skill through the Agent Catalog page.

**A package's skills.** A package keeps its skills in its own `skills/`, as `packages/<packageId>@<major>/skills/<name>/SKILL.md`, in the same format and held to the same rules: an install, an import or a publish of a package whose skill breaks one is refused, and the message names the file. A package's skill is read as written, so it holds no marker: nothing fills one. Every agent on a dataflow that uses the package holds the package's skills, whatever the agent's manifest names: its chat lists them after the agent's own, and a run is handed the ones that serve what it works on, as Curio's are. A package's templates often share their behaviors with Curio's nodes (Scout's Raster Calculator is `code` and its charts `vega`, like Curio's Python and Vega-Lite nodes), so `curio-behaviors` would hand a package's skill to every Python node or chart. `curio-templates` names templates of the skill's own package instead, by their `id` in its manifest, and a run that writes or checks a node of one of them is handed the skill. A name means one skill: Curio's skills come first, then the account's own skills the agent holds ([AGENT-CATALOG](AGENT-CATALOG.md#skills)), then the packages' in the order of the dataflow's lockfile (`dataflow.packages`), and a skill whose name an earlier one has is left out, with a warning in the backend's log. [Scout's skill](../packages/curio.scout@1/skills/scout/SKILL.md) is an example.

**The checks.** The backend reads each skill in `skills/` strictly when it starts ([`agents/domain/skills.py`](../utk_curio/backend/app/agents/domain/skills.py)), so a skill that breaks the format's rules, or names a marker no field defines, stops the start and names its file. In the backend suite, `test_skills.py` and `test_agent_text.py` hold every skill to the format's rules, `test_skills_ref.py` runs agentskills.io's reference validator on each and on each skill a shipped package ships, `test_skill_listing.py` lists the skills each agent's runs hold and fails on a skill no agent's run reaches and on a run of a prompt that no longer holds a procedure's text and is not handed its skill, and `test_package_skills.py` holds a package's skills in runs to the rules above. To run the validator yourself, `pip install skills-ref==0.1.1`, then `agentskills validate skills/<name>`.

### Evaluating a skill

Each skill Curio ships holds its evaluations in `evals/evals.json`, as agentskills.io's guide on [evaluating skills](https://agentskills.io/skill-creation/evaluating-skills) lays them out. A skill's listing leaves that folder out, so no run is offered it and no export carries it.

- `skill_name`, and `evals`: test cases, each an `id`, a `prompt` a user would type, an `expected_output` and its `assertions`, which a grader checks each answer against.
- `trigger_queries`, for a skill a chat loads: about twenty, each a `query` and whether it `should_trigger` the skill, eight to ten of each ([optimizing descriptions](https://agentskills.io/skill-creation/optimizing-descriptions)). A skill the preamble holds, or one an instruction hands to every chat, has none.
- Curio's fields, at the top level or on a test case: `agent`, whose chat runs it; `dataflow`, the dataflow its project starts as (a shipped example, or a file under the skill's `evals/`); `target`, the canvas (the default, and where trigger queries run) or `{"kind": "node", "node": "<id>"}`.

`agent_eval.py skills` runs them against an OpenAI-compatible endpoint you name in three variables, from a Python environment with Curio's requirements (`pip install -r requirements.txt`). It needs no running Curio: each worker is a backend of its own, and no node runs. Each run sends its message with the context a browser's chat sends beside it: the node its agent is attached to, or the whole dataflow, as the agent's reads say.

```bash
CURIO_EVAL_BASE_URL='<base URL>' CURIO_EVAL_API_KEY='<key>' CURIO_EVAL_MODEL='<model>' \
  python utk_curio/tools/agent_eval.py skills --pilot --out ../skill-evals
```

- Each trigger query runs three times (`--runs`). Its trigger rate is the share of its runs that loaded the skill with skill.read, and it passes above one half when it should trigger, below it when it should not. A trigger run stops once its chat loads the skill, or once it delegates its work, before loading it, to a run Curio hands the skill, such as a node's content writer: that run did not load it, and `triggers.json` counts it as handed off. Any other delegation runs on. `--full-trigger-runs` lets every run finish.
- A run whose model call the server failed (a 5xx or a lost connection) runs again, up to twice, after 15 and 45 seconds; its `run.json` counts the attempts. A run that still fails is an error, which no rate counts.
- Each test case runs three times with the skill, as Curio ships it, and three times without it: the same agent, with the skill taken out of its run's catalog, of what it is handed and of its preamble. The same model grades each answer, with the words of [`skill-evals.md`](../agents/agent.curio.builtin@1/skill-evals.md). `--hand` hands the skill over as `/<name>` in the runs with it.
- `--pilot` runs one skill (the first, or the one it names) and says how long the whole run would take. `--skills a,b` picks skills, `--only trigger` or `--only task` one kind of run, `--jobs` the workers that run at once (4), and `--resume <folder>` goes on with an interrupted run.
- Under `--out`, a run writes one folder: for each skill, `triggers.json`, `benchmark.json` and a folder per run with its reply, what it changed in its dataflow and the installs it asked for, its transcript, `timing.json` and `grading.json`; then `summary.md`. The endpoint's key and base URL come from the variables alone: nothing written holds them or its host, and the tool reads every file again at the end and fails if one does.
- CI never runs it. `test_skill_evals.py` holds every skill's `evals/evals.json` to the rules above.
