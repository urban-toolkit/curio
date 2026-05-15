# Nodes Hub and Pack Warehouse — Documentation

This directory contains **technical documentation** for the Curio **Nodes Hub** implementation: the warehouse UI, per-user pack storage, dependency resolution, Node Factory authoring flow, and integration with the editor palette.

Informal product notes, mockups, and older drafts sometimes appear in other repository folders. **This** directory is the source of truth for shipping behaviour in `utk_curio/`.

## Document map

| Document | Purpose |
|----------|---------|
| [Overview](overview.md) | Terminology, data model, and end-to-end flow |
| [Manifest specification](manifest_spec.md) | Normative `manifest.json` schema (full target); subset enforced in `manifest.py` |
| [Backend](backend.md) | Python modules, storage layout, seeder behaviour |
| [REST API reference](api-reference.md) | `/api/packs` endpoints, payloads, and status codes |
| [Frontend](frontend.md) | Routes, UI surfaces, API client, node registry |
| [Pack warehouse evolution](warehouse_v2.md) | Shipped vs roadmap: fixture catalog, families, resolver, remote registry, semver & channels |
| [Operations and troubleshooting](operations.md) | Development server settings, common failures, recovery |

## Quick reference — source locations

| Layer | Path |
|-------|------|
| Flask blueprint | `utk_curio/backend/app/packs/routes.py` |
| Installer & export | `utk_curio/backend/app/packs/installer.py` |
| Resolver & lockfile | `utk_curio/backend/app/packs/resolver.py` |
| Factory (draft → archive) | `utk_curio/backend/app/packs/factory.py` |
| Dev catalog fixtures | `utk_curio/backend/fixtures/packs/` |
| Frontend API client | `utk_curio/frontend/urban-workflows/src/api/packsApi.ts` |
| Nodes Hub UI | `utk_curio/frontend/urban-workflows/src/pages/nodes/NodesHub.tsx` |
| Node Factory wizard | `utk_curio/frontend/urban-workflows/src/pages/nodes/NodeFactory.tsx` |
| Editor palette (built-in + packs) | `utk_curio/frontend/urban-workflows/src/components/menus/nodes/ToolsMenu.tsx` |
| Canvas fit-view offset (palette) | `utk_curio/frontend/urban-workflows/src/utils/fitViewWithMenuOffset.ts` |
| Pack → palette registration | `utk_curio/frontend/urban-workflows/src/registry/packsClient.ts` |
| Node registry | `utk_curio/frontend/urban-workflows/src/registry/nodeRegistry.ts` |

## Audience

These documents are intended for **engineers** extending or operating the pack system. They assume familiarity with Curio’s Flask backend and React frontend.
