# Backend Implementation

## Flask blueprint

The pack API is registered as a Flask blueprint with prefix `/api/packs`. Every route uses `@require_auth`; the storage key for the current user matches project filesystem layout (`_user_dir_key`).

Primary module:

- `utk_curio/backend/app/packs/routes.py`

## Storage layout

Per-user packs live under:

```text
<CURIO_LAUNCH_CWD>/.curio/users/<user_key>/packs/<packId>@<major>/
```

Pack install **staging** (temporary extraction) uses a sibling directory so that writing `.py` files during install does not interact poorly with the development reloader:

```text
.../users/<user_key>/.pack-staging/stage-*/
```

See [Operations and troubleshooting](operations.md) for details.

Helper functions reside in `utk_curio/backend/app/packs/storage.py`, including:

- `user_packs_dir(user_key)`
- `user_pack_staging_dir(user_key)`
- `pack_dir(user_key, dir_name)`
- `list_user_packs(user_key)`

## Installer

Module: `utk_curio/backend/app/packs/installer.py`

Responsibilities:

- **ZIP sideload** (`install_pack_from_archive`): strict layout, zip-slip protection, size bounds, manifest validation in staging, atomic promotion to the final directory name derived from the manifest (never from the archive path).
- **Catalog install** (`install_pack_from_directory`): re-packages a source directory in memory and reuses the archive path for identical validation and integrity hashing.
- **Uninstall** (`uninstall_pack`): removes the pack directory and records user intent for the dev seeder (tombstone).
- **Export** (`export_pack_archive`): builds a deterministic `.curio-nodepack` archive.

Successful (re)install clears the per-pack **uninstall tombstone** via `seed_state.clear`.

## Factory

Module: `utk_curio/backend/app/packs/factory.py`

Accepts a JSON **draft** from the Node Factory UI, validates it, materializes `manifest.json` and template files, and returns a ZIP suitable for installation or download (`POST /api/packs/factory/build` / `factory/install`).

## Resolver and lockfile

Module: `utk_curio/backend/app/packs/resolver.py`

Resolves a requested set of `dirName` values into:

- a topological order respecting pack dependencies;
- merged Python and JS dependency ranges with conflict detection;
- a **lockfile** structure (installed pack coordinates plus merged deps).

For **pre-install** probes, manifests for catalog-only packs are supplied through `overrides` pointing at `utk_curio/backend/fixtures/packs/<dirName>/` (`_resolver_overrides_for` in `routes.py`).

## Dev catalog and seeding

- **Catalog source**: `utk_curio/backend/fixtures/packs/` — each immediate subdirectory matching the pack directory naming rule is a catalog entry.
- **Seeder**: `utk_curio/backend/app/packs/seed.py` copies selected fixtures into the guest (or dev) user pack store on startup when appropriate.
- **Tombstone state**: `utk_curio/backend/app/packs/seed_state.py` persists `.seed-state.json` so that an explicit **uninstall** is not undone by the seeder until the fixture is meaningfully updated (see [Operations](operations.md)).

## Manifest loading

`utk_curio/backend/app/packs/manifest.py` defines `PackManifest`, validation, and `load_pack_manifest` / `load_pack_manifest_from_dir`. The **normative** manifest schema (full target) is [Manifest specification](manifest_spec.md); the Python module implements a **supported subset**. Optional top-level **`lineage`** declares fork provenance (`forkedFrom` + optional `root`, normalized when `root` is omitted); see [Manifest specification — §2.4 `lineage`](manifest_spec.md#24-lineage-fork-provenance-optional) and the `lineage` field on catalog/installed responses in [REST API reference](api-reference.md#get-apipacks). [`routes.py`](../../utk_curio/backend/app/packs/routes.py) `_manifest_to_payload` includes `lineage` on catalog and installed pack responses (`null` when absent). Resolver behaviour is unchanged — lineage does not inject `dependencies.packs`.

Routes skip malformed on-disk packs when listing installed packs and log a warning.

## Tests

Backend pack behaviour is covered under:

```text
utk_curio/backend/tests/test_packs/
```

Run (from repository root, with the project’s Python environment):

```bash
python -m pytest utk_curio/backend/tests/test_packs -q
```
