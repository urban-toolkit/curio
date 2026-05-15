# Operations and Troubleshooting

## Development server and hot reload

Pack installation writes many **`.py`** files under the Curio user runtime directory (`.curio/`). Werkzeug’s **watchdog** reloader applies `exclude_patterns` using **`pathlib.Path.match`**, which does not reliably ignore **deep paths** under `.curio/`. That can cause the worker to restart **during** an HTTP install request, producing:

- `net::ERR_EMPTY_RESPONSE`
- “Failed to fetch” in the browser with **0-byte** responses

Mitigations implemented in code:

1. **Default reloader type** is **`stat`** (not watchdog), via `DEFAULT_RELOADER_TYPE` / `FLASK_RELOADER_TYPE` in `utk_curio/backend/server.py` and the sandbox `server.py`.
2. **`RELOADER_EXCLUDE_PATTERNS`** excludes runtime paths under `.curio/` for the stat reloader (`fnmatch` semantics).
3. Install **staging** occurs under `users/<u>/.pack-staging/`, not inside `packs/`.

To opt into watchdog reloading (not recommended while testing pack installs):

```bash
export FLASK_RELOADER_TYPE=watchdog
```

To disable reload entirely:

```bash
export FLASK_USE_RELOADER=0
```

## Uninstall versus dev seeding

The dev seeder may copy fixture packs into a guest user directory. An explicit **uninstall** writes a **tombstone** in `seed_state` so the seeder does not restore that pack on the next startup unless the fixture is updated (see `seed_state.py` / `seed.py`). After reinstalling a pack successfully, the tombstone for that pack is cleared.

## Canvas fit and palette width

`fitViewWithMenuOffset` (see [Frontend — `fitViewWithMenuOffset`](frontend.md#fitviewwithmenuoffset)) uses the combined **`#tools-palette-dock`** width. If you change palette layout (e.g. fixed offsets, wider pack panel), confirm fit-view still centers content as expected on small viewports.

## Stale palette entries

If pack kinds still appear after uninstall, ensure the client has called **`refreshPackRegistry()`** after success. The pack loader **`clearPackNodes()`** before re-registering from `GET /api/packs` so the palette matches the server.

## Resolver errors during install dialog

Pre-install **`POST /api/packs/resolve`** must resolve manifests for **catalog-only** candidates. The backend supplies **catalog overrides** for packs not present under the user `packs/` directory. If resolve fails with “missing manifest”, verify the fixture directory exists under `utk_curio/backend/fixtures/packs/<dirName>/` and contains `manifest.json`.

## Where to look in logs

Backend logs (when running via `curio` / `main.py`) aggregate into the user’s Curio message log under `.curio/messages.log`. Search for:

- `Detected change in` — reloader firing on a path (should not be under `.curio/` with the default stat reloader and excludes)
- `InstallerError`, `ManifestError`, `ResolverError` — validation or dependency failures

## Backup and reset

User pack data lives under:

```text
.curio/users/<user_key>/packs/
```

Removing a pack directory manually without going through the API may leave **seed state** or **integrity** inconsistent with UI expectations; prefer **`DELETE /api/packs/<dir_name>`** or the Nodes Hub **Remove** action.
