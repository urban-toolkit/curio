# Overview

## Purpose

The **Nodes Hub** provides a dedicated surface for discovering, installing, exporting, and authoring **node packs**: versioned bundles that contribute new node kinds to the editor without modifying the core `NodeType` enumeration. Installed kinds appear in the **editor palette**: built-in nodes in the left column, and **pack** nodes behind an adjacent **Packs** control with one **collapsible group per installed pack** (see [Frontend — Palette dock](frontend.md#palette-dock-toolsmenu)).

## Core concepts

### Node pack

A **pack** is a directory on disk whose name matches the pattern `<packId>@<major>` — for example, `it.urbanlab.milan-heat@1`. It contains at minimum a validated `manifest.json` and, typically, a `templates/` tree with code assets. Packs may be:

- **Installed** into the current user’s pack store under the Curio data root;
- **Advertised** in the **fixture-backed catalog** (committed packs under `utk_curio/backend/fixtures/packs/`);
- **Sideloaded** as a `.curio-nodepack` ZIP archive;
- **Built** via the Node Factory wizard and installed or exported from there.

The authoritative field-level schema and dependency model live in [Manifest specification](manifest_spec.md). For what the backend **loads today**, see [Backend — Manifest loading](backend.md#manifest-loading); for HTTP payloads, see [REST API reference](api-reference.md).

### Canonical node kind identifier

Each kind in a pack is addressed in Trill, the frontend registry, and backend dispatch by a **canonical string**:

```text
<packId>/<kindId>@<major>
```

Example:

```text
it.urbanlab.milan-heat/mrt-load@1
```

Built-in nodes continue to use `NodeType` enum values; pack kinds use the string form above.

### Warehouse versus installed state

| Concept | Meaning |
|---------|---------|
| **Catalog** | Read-only listing derived from repository fixtures (`GET /api/packs/catalog`). Used for browse and install-by-reference. |
| **Installed packs** | Per-user directories under `<launch_cwd>/.curio/users/<user_key>/packs/` (`GET /api/packs`). |

The UI merges catalog entries with an **installed** flag when both endpoints have been loaded.

### Frontend registry refresh

After any operation that changes the installed pack set, the application must:

1. Reload descriptors from `GET /api/packs` (replacing all `source === 'pack'` entries in the client registry).
2. Re-post the merged node-type port table to `POST /node-types`.

This is encapsulated in `refreshPackRegistry()` (see [Frontend](frontend.md)).

## End-to-end install flow (catalog)

1. User opens **Nodes Hub** (`/nodes`) and selects a catalog pack.
2. UI may call `POST /api/packs/resolve` with the candidate `dirName` plus already-installed packs to obtain a lockfile preview and conflict list. The resolver may read the candidate manifest from the catalog when it is not yet installed.
3. User confirms; UI calls `POST /api/packs/catalog/install` with `{ "dirName": "<packId>@<major>", "replace": false }`.
4. Backend copies or materializes the pack into the user store and returns manifest payload plus integrity metadata.
5. Frontend calls `refreshPackRegistry()`; **`ToolsMenu`** updates the **Packs** palette (grouped by `packId@major` inside the dock next to built-in tools).

## Other materials

Product narratives, mockups, and historical drafts sometimes live in ad-hoc folders elsewhere in the monorepo. The pages under **this** directory (`docs/nodesfactory@docs/`) are the maintained **technical** reference for behaviour that is implemented in `utk_curio/`.
