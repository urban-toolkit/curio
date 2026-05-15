# REST API Reference — `/api/packs`

All routes require authentication (`Authorization: Bearer <token>` unless the deployment disables auth). Error bodies are JSON objects with an `error` string unless noted.

Base path: **`/api/packs`**

## Summary

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/packs` | List installed packs for the current user |
| `GET` | `/api/packs/catalog` | Fixture-backed catalog listing |
| `POST` | `/api/packs/upload` | Sideload `.curio-nodepack` (multipart `file`) |
| `POST` | `/api/packs/catalog/install` | Install a catalog pack by `dirName` |
| `DELETE` | `/api/packs/<dir_name>` | Uninstall pack |
| `GET` | `/api/packs/<dir_name>/archive` | Download pack as `.curio-nodepack` |
| `POST` | `/api/packs/factory/build` | Build archive from factory draft (returns ZIP) |
| `POST` | `/api/packs/factory/install` | Build and install from draft |
| `GET` | `/api/packs/factory/capabilities` | Wizard flags (`catalogPublish` env-gated) |
| `POST` | `/api/packs/factory/publish-catalog` | Opt-in write into `fixtures/packs` (developer machines) |
| `POST` | `/api/packs/resolve` | Resolve packs → lockfile; `409` on conflicts |
| `POST` | `/api/packs/install-deps` | Resolve + trigger shared sandbox pip install |

`dir_name` / `dirName` must match the on-disk convention: `<packId>@<major>` (see installer validation and `PACK_DIR_RE`).

---

## `GET /api/packs`

Returns installed packs with full manifest projection.

**Response `200`**

```json
{
  "packs": [
    {
      "packId": "ai.urbanlab.uhvi",
      "major": 1,
      "version": "1.0.0",
      "name": "...",
      "publisher": "...",
      "description": "...",
      "license": null,
      "permissions": ["filesystem.read"],
      "dependencies": {
        "packs": {},
        "python": {},
        "js": {}
      },
      "kinds": [
        {
          "id": "ai.urbanlab.uhvi/uhvi-load@1",
          "kindId": "uhvi-load",
          "label": "...",
          "category": "data",
          "engine": "python",
          "description": "...",
          "icon": null,
          "editor": "code",
          "hasCode": true,
          "hasWidgets": false,
          "hasGrammar": false,
          "inputPorts": [{ "types": ["dataframe"], "cardinality": "1" }],
          "outputPorts": [],
          "templateDir": "uhvi-load",
          "defaultTemplate": "UHVI_Load_Basic.py"
        }
      ],
      "dirName": "ai.urbanlab.uhvi@1",
      "lineage": null,
      "familyKey": "ai.urbanlab.uhvi@1",
      "channel": "stable"
    }
  ]
}
```

Malformed directories under the user pack root may be omitted from `packs`.

---

## `GET /api/packs/catalog`

Same payload shape per pack as `GET /api/packs`. Each pack row includes **`familyKey`** (fork family / coordinate) and **`channel`** (from `distribution.channel`, default `stable`).

**Catalog-only top-level fields**

| Field | Type | Notes |
|-------|------|--------|
| `packs` | array | Full pack objects (plus `installed` when not merged client-side). |
| `families` | array | `{ familyKey, dirNames[] }[]` — grouping of fixture `dirName`s by family. |
| `catalogCollisions` | array | Duplicate `(familyKey, channel, version)` entries; empty when the fixture set is clean. |

Optional boolean `installed` may be merged client-side against `GET /api/packs`.

---

## `POST /api/packs/upload`

**Request:** `multipart/form-data` with field **`file`** (`.curio-nodepack`).

**Query:** `replace=true` to overwrite an existing same `dirName`.

**Response `201`**

```json
{
  "pack": { },
  "integrity": { "manifest.json": "<sha256 hex>", "templates/...": "..." },
  "replacedExisting": false
}
```

---

## `POST /api/packs/catalog/install`

**Request**

```json
{
  "dirName": "it.urbanlab.milan-heat@1",
  "replace": false
}
```

**Response `201`:** same shape as upload success.

**Errors:** `404` if catalog has pack; `400` installer/validation errors.

---

## `DELETE /api/packs/<dir_name>`

Removes the installed pack and records uninstall intent for seeding.

**Response `200`:** JSON success body from route implementation.

**Response `404`:** Pack not installed (clients may treat as idempotent success for UI refresh).

---

## `GET /api/packs/<dir_name>/archive`

**Response `200`:** binary ZIP with `Content-Disposition` suggesting `<dir_name>.curio-nodepack`.

---

## `POST /api/packs/factory/build`

**Request:** JSON factory draft (see `factory.py` and Node Factory UI).

**Response `200`:** ZIP body; use `Content-Disposition` for filename.

---

## `POST /api/packs/factory/install`

**Request:** Same draft as build.

**Response `201`:** Install response shape (pack + integrity + `replacedExisting`).

---

## `GET /api/packs/factory/capabilities`

**Response `200`**

```json
{ "catalogPublish": true }
```

`catalogPublish` is **`true`** when **`CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`** is **unset / empty**, or **`1`**, **`true`**, **`yes`**, or **`on`** (case-insensitive). It is **`false`** for **`0`**, **`false`**, **`no`**, **`off`**, or **any other non-empty value**. The Node Factory uses this before enabling “publish to dev catalog.”

---

## `POST /api/packs/factory/publish-catalog`

Builds the same factory draft as `/factory/install`, then extracts it into **`utk_curio/backend/fixtures/packs/<dirName>/`** (committed catalog stub). Intended for developer workflows; may trigger reload when file watchers observe `fixtures/`.

Allowed by default. **Response `403`** with `{ "error": "..." }` when disabled via **`CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`** (same rule as `capabilities`).

**Request:** Factory draft JSON, plus optional **`replace`**: when `true`, overwrite an existing fixture directory with the same `dirName`; when omitted or false, duplicates return **`400`**.

**Response `201`** extends the install-success shape:

- `catalogDir`: absolute filesystem path to the fixture directory written.
- `filename`: suggested `.curio-nodepack` filename from the factory build step.

---

## `POST /api/packs/resolve`

Pack edges in manifests use `dependencies.packs` keys that are either **`<packId>`** (allowed only when a single installed directory matches that id) or **`<packId>@<major>`** (unambiguous).

**Request**

```json
{
  "packs": ["ai.urbanlab.uhvi@1", "it.urbanlab.milan-heat@1"]
}
```

**Response `200`**

```json
{
  "lockfile": {
    "installedPacks": [
      {
        "id": "ai.urbanlab.uhvi",
        "major": 1,
        "version": "1.0.0",
        "dirName": "ai.urbanlab.uhvi@1",
        "familyKey": "ai.urbanlab.uhvi@1",
        "lineageRoot": { "packId": "ai.upstream.example", "major": 1 }
      }
    ],
    "pythonDeps": { "numpy": "^1.26" },
    "jsDeps": {}
  },
  "conflicts": []
}
```

`lineageRoot` is present only when the pack’s manifest declares `lineage` (fork family anchor). `familyKey` always mirrors `GET /api/packs` (`lineage.root` coordinate, or `dirName` when there is no lineage).

**Response `409`:** Non-empty `conflicts` array describing semver or merge failures (exact shape: see `ResolveConflict` in frontend types or resolver implementation).

---

## `POST /api/packs/install-deps`

Resolves the pack set, then forwards merged Python requirements to the shared sandbox install path used elsewhere in Curio. Response includes lockfile, conflicts, and sandbox status metadata (`InstallDepsResponse` in `packsApi.ts`).

---

## Companion: `POST /node-types`

Not under `/api/packs`, but required for runtime consistency. The frontend posts the **union of built-in and pack** node kinds with port shapes so the backend can validate edges and dispatch templates. Invoked from `syncNodeTypeRegistry()` in `index.tsx` after `loadInstalledPacks()`.
