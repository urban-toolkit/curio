# Curio node pack — manifest specification

Normative reference for the JSON **`manifest.json`** inside a **`.curio-nodepack`** archive. The Node Factory wizard, Nodes Hub, installer, and resolver all use the manifest as the contract for pack identity, kinds, dependencies, lineage, and permissions.

**Implementation today:** [`utk_curio/backend/app/packs/manifest.py`](../../utk_curio/backend/app/packs/manifest.py) validates a **supported subset** of this document (some fields and shapes below are aspirational or differ from on-wire JSON—see [Backend — Manifest loading](backend.md#manifest-loading) and [REST API reference](api-reference.md)). Catalogue semantics (`familyKey`, channels, collisions) are documented in [Pack warehouse evolution](warehouse_v2.md). Product flow is summarised in [Overview](overview.md) and [Frontend](frontend.md).

**Runtime model:** the core `NodeType` enum in [`constants.ts`](../../utk_curio/frontend/urban-workflows/src/constants.ts) stays append-only for built-ins. Pack kinds use **canonical string ids** `<packId>/<kindId>@<major>` and register at runtime through [`registerNode(descriptor)`](../../utk_curio/frontend/urban-workflows/src/registry/nodeRegistry.ts) with `NodeKindId = NodeType | string`.

> **Scope:** Sections below describe the **full** target schema and validation story. The Python loader intentionally enforces a narrower subset until the spec and UI fully align.

---

## 1. Pack archive (`.curio-nodepack`)

### 1.1 Self-containment invariant

A pack is **fully self-contained**:

- Every Python template preset, grammar spec, widget spec, and icon used by any of the pack's `nodeKinds` **must** live inside the archive root.
- The manifest is the only place that names file paths, and every path is **relative to the archive root** and **must not escape** it (no `..`, no absolute paths, no symlinks).
- Pack code MUST NOT reference files under `<CURIO_LAUNCH_CWD>/templates/` or any other path outside its own pack root. The built-in `templates/<node_type_lower>/` folder served by [`generate_templates()` in `routes.py`](../../utk_curio/backend/app/api/routes.py) is reserved for built-in `NodeType` presets and is invisible to pack code.
- The installer rejects archives that contain executables, native binaries, or files outside the directories below; it also rejects manifests referencing files that do not exist inside the archive.

This is the rule that makes packs portable: copying a `<packId>@<major>/` directory to another machine and re-running the resolver is enough to reproduce the kind end-to-end.

### 1.2 Archive layout

```
<pack>.curio-nodepack/
├── manifest.json              # required, validated against schema below
├── README.md                  # optional, surfaced in warehouse detail
├── LICENSE                    # optional but strongly recommended
├── icons/                     # optional pack-shipped icon assets (svg/png)
│   └── <kindId>.svg
├── templates/                 # required when nodeKinds[].engine != "none"
│   └── <kindId>/
│       ├── <Preset_Name>.py   # one or more presets per kind (matches today's built-in
│       │                      #   templates/<node_type_lower>/<Preset>.py layout)
│       └── requirements.txt   # optional; mirrors manifest deps for reproducibility
├── grammars/                  # optional, for "grammar" editor kinds
│   └── <kindId>/<Preset_Name>.json
└── widgets/                   # optional, declarative widget specs
    └── <kindId>/<Preset_Name>.json
```

### 1.3 On-disk install location

After install, the archive is extracted verbatim into the per-user pack store (layout and paths: [Backend — Storage layout](backend.md#storage-layout)):

```
<CURIO_LAUNCH_CWD>/.curio/users/<user_key>/packs/<packId>@<major>/
```

`<major>` is the integer major version from `manifest.version`. A user may have **one** directory per `(packId, major)` pair installed at any time. The same `_users_base()` + `safe_join` plumbing as [`utk_curio/backend/app/projects/storage.py`](../../utk_curio/backend/app/projects/storage.py) applies.

### 1.4 Path constraints (enforced by the installer)

- All paths in the manifest are **relative**, **POSIX-style**, and rooted at the archive.
- File names match `^[A-Za-z0-9._-]+$`. Each `kindId` must be a stable folder name (see §3.4).
- The archive **must not** contain executables, native binaries, or files outside the directories above; the installer rejects unknown top-level entries.
- Path resolution at runtime: every reference resolves under `.curio/users/<u>/packs/<packId>@<major>/`. The runtime template / grammar / widget / icon loader **never** falls back to `<CURIO_LAUNCH_CWD>/templates/` for a pack canonical id.

---

## 2. `manifest.json` — top-level schema

| Field | Type | Required | Notes |
|-------|------|---------:|-------|
| `schemaVersion` | integer | yes | `1` for this spec. |
| `id` | string | yes | Reverse-DNS, lowercase. Pattern `^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$`, max 96 chars. Example `ai.urbanlab.uhvi`. |
| `version` | string | yes | [Semver 2.0.0](https://semver.org/) (`MAJOR.MINOR.PATCH`, optional `-prerelease`, `+build`). |
| `displayName` | string | yes | 1–64 chars, no leading/trailing whitespace. |
| `description` | string | yes | Plain text, 10–500 chars. Markdown allowed in `README.md`. |
| `author` | object | yes | `{ name, email?, url? }`. |
| `license` | string | yes | [SPDX identifier](https://spdx.org/licenses/) (e.g. `MIT`, `Apache-2.0`, `BSD-3-Clause`). |
| `homepage` | string | no | URL. |
| `repository` | object | no | `{ type: "git" \| "https", url }`. |
| `keywords` | string[] | no | Up to 10, lowercase. |
| `compatibility` | object | yes | See §2.1. |
| `permissions` | object | yes | See §2.2. |
| `dependencies` | object | yes | See §2.3 (may be empty `{}` but the field must exist). |
| `nodeKinds` | object[] | yes | At least 1 entry. Each follows §3. |
| `signing` | object | no | See §2.5. Optional in v1; required for partner / verified packs. |
| `integrity` | object | no | Auto-filled by the installer at extract time (`sha256` over manifest + asset tree). Must be omitted by the author. |
| `lineage` | object | no | Fork provenance; see §2.4. **Implemented** in [`utk_curio/backend/app/packs/manifest.py`](../../utk_curio/backend/app/packs/manifest.py). Omit for catalog originals. |
| `createdAt` | string | no | **Implemented:** ISO 8601 instant (`…Z` or offset). Canonical pack authoring / creation timestamp. ``GET /api/packs`` returns ``createdAt`` (when present) and parsed ``createdAtMs`` for ordering (newest-first). Factories stamp UTC when the field is missing; installers persist ``createdAt`` on first unpack if absent. Missing or unset timestamps sort as epoch `0`. |

### 2.1 `compatibility`

| Field | Type | Required | Notes |
|-------|------|---------:|-------|
| `curioRuntime` | string | yes | Semver range against the host app version (e.g. `>=1.4.0 <2.0.0`). |
| `frontend` | string | no | Optional UI runtime range (e.g. `>=24.0.0 <26.0.0`). |
| `os` | string[] | no | Subset of `["macos","linux","windows"]`. Empty/absent = all. |

The installer rejects packs whose `curioRuntime` does not satisfy the host's running version.

### 2.2 `permissions`

A pack must explicitly declare every elevated capability. The install dialog in [Nodes Hub](frontend.md#nodes-hub-nodeshubtsx) renders this list verbatim.

| Field | Type | Default | Notes |
|-------|------|--------:|-------|
| `fileRead` | boolean | `true` | Read project inputs the user opens in Curio. Cannot be disabled today (sandbox). |
| `fileWrite` | boolean | `false` | Write into the project's output cache only; never the user's filesystem. |
| `network` | object \| `false` | `false` | If object: `{ allowlist: string[] }` of host patterns (e.g. `*.openstreetmap.org`). Wildcards limited to host segment. |
| `pythonStdlibOnly` | boolean | `true` | If `false`, pack relies on declared `dependencies.python` packages installed inside the sandbox. |
| `registerNodeKinds` | integer | required | Must equal `nodeKinds.length`. Surfaced verbatim ("Adds N nodes to your palette"). |
| `subprocess` | boolean | `false` | Reserved; rejected by v1 installer. |

### 2.3 `dependencies`

Strict, **declared up front**, and resolved at install. The installer fails closed if any constraint cannot be satisfied.

```jsonc
"dependencies": {
  "packs":   { "ai.urbanlab.geo-base": "^1.2.0" },   // semver range over other Curio packs
  "python":  { "rasterio": "^1.3", "shapely": ">=2.0,<3.0" },
  "js":      {},                                     // npm-style, only when engine == "javascript"
  "system":  []                                      // reserved (e.g. "gdal"); v1 installer rejects non-empty
}
```

| Field | Type | Required | Notes |
|-------|------|---------:|-------|
| `packs` | `{ [packId \| packId\@major]: semverRange }` | yes (may be `{}`) | Other Curio packs **must be installed.** Keys should be **`&lt;packId&gt;@&lt;major&gt;`** when more than one on-disk directory shares the same `packId`; bare `packId` is accepted only when it maps to exactly one installed entry. Resolver enforces a DAG. |
| `python` | `{ [pkg]: semverRange }` | yes (may be `{}`) | PyPI packages installed into the sandbox virtualenv. Wheels preferred; the installer caches resolutions per pack version. |
| `js` | `{ [pkg]: semverRange }` | yes (may be `{}`) | npm registry packages. Only honored when at least one `nodeKind.engine == "javascript"`. |
| `system` | string[] | no | Reserved for future native dependencies (e.g. GDAL). Rejected if non-empty in v1. |

**Resolution rules**

1. **Compatibility first:** if `compatibility.curioRuntime` is unsatisfied, install fails before resolving deps.
2. **Pack graph:** `dependencies.packs` is a DAG. Cycles, missing packs, or unsatisfiable ranges fail with a precise error citing the offending edge.
3. **Single version per pack:** a project pins one pack version at a time; conflicting upgrades produce an explicit "upgrade plan" the user must accept.
4. **Python / JS in a shared sandbox env, fail closed on conflicts:** there is **one** Python interpreter (`sys.executable`) in the sandbox today and **one** JS runtime; pack `dependencies.python` and `dependencies.js` from every installed pack in the project are merged into a single requirement set, resolved against PyPI / npm, and installed via the existing [`POST /installPackages`](../../utk_curio/backend/app/api/routes.py) → sandbox [`POST /install`](../../utk_curio/sandbox/app/api.py) (`subprocess.run([sys.executable, '-m', 'pip', 'install', …])`). **No per-pack venv.** If two installed packs request incompatible semver ranges for the same package, the install is **rejected** with an error citing both pack ids and the offending range — the resolver does not silently pick a winner. The project's `spec.trill.json` records the resolved sha-pinned lockfile.
5. **Optional dependency hints (`?`)** are out of scope for v1; declare optional features as **separate `nodeKinds`** instead.

### 2.4 `lineage` (fork provenance, optional)

When present, records that this pack was derived from another installed/catalog pack without implying an automatic dependency edge (`dependencies.packs` remains authoritative for the resolver).

```jsonc
"lineage": {
  "forkedFrom": { "packId": "ai.upstream.example", "major": 1 },
  "root": { "packId": "ai.upstream.example", "major": 1 }
}
```

| Field | Type | Required when `lineage` set | Notes |
|-------|------|---------------------------:|-------|
| `forkedFrom` | `{ packId, major }` | yes | Immediate parent coordinate (`packId` + non-negative `major`; must match on-disk naming rules). Must **not** equal this manifest’s own `id` + `compatibility.major`. |
| `root` | `{ packId, major }` | no | Stable family anchor (typically the original catalog pack). If omitted, loaders normalize `root` to equal `forkedFrom`. Must **not** equal this manifest’s own coordinate. |

Downstream (`GET /api/packs`) exposes this block as JSON `lineage` or `null` when absent. Each listing also carries a derived **`familyKey`** (typically `packId\@major` of `root`, or `dirName` when there is no lineage) for warehouse grouping — see [Pack warehouse evolution](warehouse_v2.md).

### 2.4.2 `curio.paletteDock` (optional, runtime / installer)

Vendor extension subtree for **local** behaviours that should **persist in `manifest.json`** but are **not** edited in Node Factory authoring.

| Field | Type | Required | Notes |
|-------|------|---------:|-------|
| `curio` | object | no | Root for reserved Curio-managed keys only. **`paletteDock`** is the only child defined today; other sibling keys MUST be tolerated by loaders but SHOULD NOT collide with documented Curio-managed fields. Malformed **`curio`** or **`paletteDock`** shapes (`curio.paletteDock.hiddenFromForkPaletteDock` anything other than a JSON boolean when present) **fail manifest load.** |
| `curio.paletteDock.hiddenFromForkPaletteDock` | boolean | no | When **`true`**, **`ToolsMenu`’s PACKS dropdown omits palette sections for this install coordinate** (fork-parent packs after a fork install, or manual batch Hide via Nodes Hub while at least one installed fork references this parent). Omit or **`false`** ⇒ show in dock. **Does not** unregister kinds or affect **`GET /api/packs`** canonical listing shape beyond this flag and optional **`paletteDock`** on pack payloads (`false` payloads omit **`paletteDock`**). |

Semantics after a **fork** install (`lineage.forkedFrom` present):

1. The backend sets **`hiddenFromForkPaletteDock: true`** on each installed **`forkedFrom`** coordinate that remains referenced by ≥1 fork (see **`resync_fork_palette_parent_flags`** in [`palette_dock_manifest.py`](../../utk_curio/backend/app/packs/palette_dock_manifest.py)).
2. Uninstalling forks **recomputes** those flags so orphaned parents lose **`hidden`**.
3. **Nodes Hub → My packs** exposes an **eye toggle** mapped to **`POST /api/packs/palette-dock/fork-parents`** with **`{ "visible": true \| false }`**, which clears or restores **`hidden`** for all currently referenced fork parents (same-tab coherence via **`refreshPackRegistry()`**, not browser storage).

### 2.4.3 `distribution` (optional, warehouse / catalog)

Used for release-channel labels in the Nodes Hub catalog and collision reporting; does **not** change resolver behaviour today.

```jsonc
"distribution": {
  "channel": "stable"
}
```

| Field | Type | Required | Notes |
|-------|------|---------:|-------|
| `channel` | string | no | Implemented in [`utk_curio/backend/app/packs/manifest.py`](../../utk_curio/backend/app/packs/manifest.py). Normalised loader default is `stable`; common values include `stable`, `beta`, `rc`, `dev`. Malformed tokens fall back to `stable`. Returned on `GET /api/packs` and `GET /api/packs/catalog` as top-level **`channel`**. |

### 2.5 `signing` (optional in v1, required to be marked "Verified")

```jsonc
"signing": {
  "signer": "ai.urbanlab",
  "algorithm": "ed25519",
  "publicKeyId": "ulab-2026-01",
  "signature": "<base64 over canonical manifest hash>"
}
```

Verified packs display a badge in the warehouse and skip the "trust this source?" copy in the install dialog. Unsigned packs always show the trust prompt.

---

## 3. `nodeKinds[]` entries

Each kind becomes one **palette entry** and is registered at runtime as a `NodeDescriptor` (see [`registry/types.ts`](../../utk_curio/frontend/urban-workflows/src/registry/types.ts)). The shape mirrors today's descriptor so a pack-authored kind is indistinguishable from a built-in once registered.

### 3.1 Identity & metadata

| Field | Type | Required | Notes |
|-------|------|---------:|-------|
| `kindId` | string | yes | Stable within the pack. Pattern `^[a-z][a-z0-9-]{1,48}$`. Folder name under `templates/`. |
| `canonicalId` | string | derived | `<packId>/<kindId>@<majorVersion>` (e.g. `ai.urbanlab.uhvi/uhvi-load@1`). **Persisted in saved Trill graphs.** Authors do not write this; the manifest validator computes and rejects pack publishes if it would collide. |
| `label` | string | yes | 1–48 chars; shown in palette + node header. |
| `description` | string | yes | 10–280 chars. |
| `category` | enum | yes | One of `data`, `computation`, `vis_grammar`, `vis_simple`, `flow`. Same set as core `NodeCategory`. |
| `paletteOrder` | number | yes | Within the **PACKS** palette section only. |
| `tutorialId` | string | no | Reserved for future onboarding hooks. |

### 3.2 Ports

```jsonc
"inputPorts":  [ { "label": "raster",  "types": ["RASTER"], "cardinality": "1" } ],
"outputPorts": [ { "label": "summary", "types": ["JSON"],   "cardinality": "1" } ]
```

- `types` ⊂ `SupportedType` enum: `DATAFRAME`, `GEODATAFRAME`, `VALUE`, `LIST`, `JSON`, `RASTER`.
- `cardinality` ∈ `"0" | "1" | "2" | "n" | "[1,n]" | "[1,2]"` (matches existing `PortDef`).
- `label` is shown next to the handle in the node UI.

### 3.3 Editor & engine

| Field | Type | Required | Notes |
|-------|------|---------:|-------|
| `editor` | enum | yes | `code` \| `grammar` \| `widgets` \| `none`. |
| `engine` | enum | yes | `python` \| `javascript` \| `none` (declarative widgets-only kinds). |
| `hasCode` | bool | yes | Mirrors core descriptor flag. |
| `hasWidgets` | bool | yes | Must be `true` for any Python-execution kind that uses widget markers. |
| `hasGrammar` | bool | yes | `true` for Vega/UTK-style grammar kinds. |
| `templateDir` | string | yes when `engine != "none"` | Relative directory under `templates/<kindId>/`. **All `.py` files inside become individual Template presets** for this kind (matches today's built-in layout: `<CURIO_LAUNCH_CWD>/templates/<node_type_lower>/*.py` → one preset per file in [`generate_templates()`](../../utk_curio/backend/app/api/routes.py)). |
| `defaultTemplate` | string | yes when `engine != "none"` | Relative path to the **default** preset under `templateDir/`, used when a user drops a fresh node on the canvas. Must exist inside `templateDir`. |
| `grammarDir` | string | yes when `editor == "grammar"` | Relative directory under `grammars/<kindId>/`. All `.json` files inside become grammar presets exposed to the existing `TemplateModal`. |
| `widgetDir` | string | no | Relative directory under `widgets/<kindId>/` for declarative widget spec presets. |

**Template-loader contract for packs.** At runtime, a sibling to [`generate_templates()`](../../utk_curio/backend/app/api/routes.py) walks `.curio/users/<u>/packs/<packId>@<major>/<templateDir>/*.py` and emits one `Template` object per file:

```jsonc
{
  "id": "<uuid>",
  "type": "<canonicalId>",     // e.g. "ai.urbanlab.uhvi/uhvi-load@1" — NOT a NodeType
  "name": "<file name without .py, underscores → spaces>",
  "description": "",
  "accessLevel": "ANY",
  "code": "<file contents>",
  "custom": true
}
```

This makes pack templates indistinguishable from today's built-in presets from the frontend's perspective ([`TemplateProvider.tsx`](../../utk_curio/frontend/urban-workflows/src/providers/TemplateProvider.tsx) just needs to filter on `NodeType | canonicalId`). Packs ship multiple `.py` files inside their archive to expose multiple presets; the loader never reads any file outside `.curio/users/<u>/packs/<packId>@<major>/`.

### 3.4 Icon

```jsonc
"icon": { "source": "fa",  "value": "faSatelliteDish" }       // bundled FontAwesome subset
"icon": { "source": "svg", "value": "icons/uhvi-load.svg" }   // pack-shipped SVG (whitelisted attrs)
"icon": { "source": "lucide", "value": "thermometer" }        // optional future pack
```

- v1 supports `source: "fa"` (allowlisted icon names) and `source: "svg"` (sanitized at install).
- SVG icons are scrubbed at install: scripts, foreign objects, external references stripped.

### 3.5 Capabilities snapshot

Each `nodeKind` may pin extra capabilities used at runtime:

```jsonc
"capabilities": {
  "showTemplateModal": true,
  "containerHandleType": "in/out",
  "inputIconType":  "1",
  "outputIconType": "1"
}
```

These map directly to fields on `NodeAdapter` / `ContainerConfig` so that the runtime descriptor built from the manifest looks identical to a hand-coded one.

---

## 4. Validation

The [Node Factory](frontend.md#node-factory-nodefactorytsx) wizard validates **before** producing an archive; the backend factory and installer re-run the same rules server-side. Errors are surfaced in the wizard's final step and from API responses.

| Class | Examples |
|-------|----------|
| **Schema** | `id` not reverse-DNS; `version` not semver; required field missing. |
| **Identity** | `canonicalId` collides with an existing public pack at the same major version. |
| **Filesystem (self-containment)** | `templateDir` / `defaultTemplate` / `grammarDir` / `widgetDir` / `icon.value` escapes the archive root; referenced file does not exist in the archive; binary file under `templates/`; `defaultTemplate` lives outside its `templateDir`; archive contains files outside the directories listed in §1.2. |
| **Dependency graph** | Cycles, unsatisfiable semver, unknown pack id; **cross-pack conflict in the shared sandbox env** (two installed packs request incompatible semver ranges for the same PyPI / npm package). |
| **Permissions** | `network.allowlist` malformed; `subprocess: true` (rejected in v1). |
| **Runtime** | Sample dry-run fails; ports type set is empty. |

---

## 5. Worked example

```jsonc
{
  "schemaVersion": 1,
  "id": "ai.urbanlab.uhvi",
  "version": "2.1.0",
  "displayName": "UHVI heat layers",
  "description": "Urban Heat Vulnerability Index loaders, raster ops, and summary widgets.",
  "author":  { "name": "Urban Lab", "url": "https://urbanlab.example" },
  "license": "Apache-2.0",
  "keywords": ["heat", "raster", "uhvi"],

  "compatibility": { "curioRuntime": ">=1.4.0 <2.0.0" },

  "permissions": {
    "fileRead": true,
    "fileWrite": false,
    "network": { "allowlist": ["*.urbanlab.example"] },
    "pythonStdlibOnly": false,
    "registerNodeKinds": 3
  },

  "dependencies": {
    "packs":  { "ai.urbanlab.geo-base": "^1.2.0" },
    "python": { "rasterio": "^1.3", "numpy": ">=1.24,<3" },
    "js":     {},
    "system": []
  },

  "nodeKinds": [
    {
      "kindId": "uhvi-load",
      "label": "UHVI Load",
      "description": "Load LST raster + SVI table for a city.",
      "category": "data",
      "paletteOrder": 10,
      "icon": { "source": "fa", "value": "faSatelliteDish" },
      "inputPorts":  [],
      "outputPorts": [{ "label": "raster", "types": ["RASTER"], "cardinality": "1" },
                      { "label": "svi",    "types": ["DATAFRAME"], "cardinality": "1" }],
      "editor": "code",
      "engine": "python",
      "hasCode": true, "hasWidgets": true, "hasGrammar": false,
      "templateDir":     "templates/uhvi-load",
      "defaultTemplate": "templates/uhvi-load/UHVI_Load_From_GeoTIFF.py",
      "capabilities": { "showTemplateModal": true, "containerHandleType": "out", "outputIconType": "N" }
    },
    {
      "kindId": "uhvi-merge",
      "label": "UHVI Merge",
      "description": "Resample + align rasters on a shared grid.",
      "category": "computation",
      "paletteOrder": 20,
      "icon": { "source": "svg", "value": "icons/merge.svg" },
      "inputPorts":  [{ "label": "rasters", "types": ["RASTER"], "cardinality": "[1,n]" }],
      "outputPorts": [{ "label": "raster",  "types": ["RASTER"], "cardinality": "1" }],
      "editor": "code", "engine": "python",
      "hasCode": true, "hasWidgets": true, "hasGrammar": false,
      "templateDir":     "templates/uhvi-merge",
      "defaultTemplate": "templates/uhvi-merge/UHVI_Merge_Nearest.py"
    },
    {
      "kindId": "uhvi-summary",
      "label": "UHVI Summary",
      "description": "Per-zone descriptive stats; emits JSON for downstream cards.",
      "category": "computation",
      "paletteOrder": 30,
      "icon": { "source": "fa", "value": "faRectangleList" },
      "inputPorts":  [{ "label": "raster", "types": ["RASTER"], "cardinality": "1" },
                      { "label": "zones",  "types": ["GEODATAFRAME"], "cardinality": "1" }],
      "outputPorts": [{ "label": "summary","types": ["JSON"], "cardinality": "1" }],
      "editor": "code", "engine": "python",
      "hasCode": true, "hasWidgets": false, "hasGrammar": false,
      "templateDir":     "templates/uhvi-summary",
      "defaultTemplate": "templates/uhvi-summary/UHVI_Summary_Per_Zone.py"
    }
  ]
}
```

On disk after install, with two presets shipped per kind:

```
.curio/users/<user>/packs/ai.urbanlab.uhvi@2/
├── manifest.json
├── integrity.json
├── templates/
│   ├── uhvi-load/
│   │   ├── UHVI_Load_From_GeoTIFF.py
│   │   └── UHVI_Load_From_S3.py
│   ├── uhvi-merge/
│   │   ├── UHVI_Merge_Nearest.py
│   │   └── UHVI_Merge_Bilinear.py
│   └── uhvi-summary/
│       ├── UHVI_Summary_Per_Zone.py
│       └── UHVI_Summary_Global.py
└── icons/
    └── merge.svg
```

Every `.py` under `templates/<kindId>/` becomes a Template preset users can pick from the existing `TemplateModal` (matching today's built-in behaviour for `<CURIO_LAUNCH_CWD>/templates/<node_type_lower>/*.py`). No file outside this directory tree is ever read for this pack's kinds.

---

## 6. Trill / project graph round-trip

When a node from this pack is dropped on the canvas, the saved Trill node looks like:

```jsonc
{
  "id": "n_5fa2",
  "type": "ai.urbanlab.uhvi/uhvi-load@1",   // canonicalId — frontend registry + backend dispatch key
  "data": { "code": "...", "widgets": [], "outputs": [] },
  "position": { "x": 220, "y": 140 }
}
```

Project files additionally persist the **resolved pack lockfile** inside `spec.trill.json` — the project itself is the isolation boundary, since the sandbox env is shared:

```jsonc
"installedPacks": [
  { "id": "ai.urbanlab.uhvi",     "version": "2.1.0",  "integrity": "sha256-..." },
  { "id": "ai.urbanlab.geo-base", "version": "1.2.4",  "integrity": "sha256-..." }
],
"resolvedPythonDeps": {
  "rasterio": "1.3.10",
  "numpy":    "1.26.4",
  "shapely":  "2.0.4"
},
"resolvedJsDeps": {}
```

Loading a graph on a clean machine triggers the resolver against this list:

1. Missing pack id → **"Install required packs"** banner with deep links into the warehouse (no silent failures).
2. Pack present but `integrity` mismatch → reject load with a tampering error.
3. `resolvedPythonDeps` / `resolvedJsDeps` are re-applied via `/installPackages`, giving the project an identical shared-env state.

There is **no per-pack venv** to reproduce; the lockfile is sufficient because the runtime env is the single sandbox interpreter (see [Backend — Installer](backend.md#installer) and [Resolver and lockfile](backend.md#resolver-and-lockfile)).

---

## 7. Versioning & deprecation

- **Minor / patch** updates may add fields to `nodeKinds[]` and `permissions` (additive).
- **Major** updates require a new `<packId>@<major>` line in `canonicalId`, so existing graphs continue to use the prior major until explicitly upgraded.
- A pack may mark a `nodeKind` as `"deprecated": true` (v1.1) — palette dims it; existing graphs keep working.

---

## 8. Open items (intentionally deferred)

- **Author signing infrastructure** (key issuance, revocation list).
- **Native deps (`dependencies.system`)** — needs sandbox plumbing.
- **Cross-pack ports** (custom `SupportedType` extensions) — would require evolving the core enum and is out of scope for the current release.
