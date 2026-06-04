# Nodes Factory — Technical spike (Option B, locked)

**Scope:** Define what must change so **node kinds are first-class string ids** registered at runtime (from installed packages), without a per-pack edit to the compile-time `NodeType` enum. **No implementation in this document** — spike code starts only after UI mock-up sign-off per [`epic_nodes_factory.md`](epic_nodes_factory.md). Manifest schema lives in [`manifest_spec.md`](../../docs/nodesfactory@docs/manifest_spec.md).

Option A (single carrier `NodeType` holding pack metadata in node `data`) is **out of scope for the implementation spike** but is **fully specified** for comparison in [`spike_option_a.md`](spike_option_a.md).

---

## 0. Architectural invariants this spike must respect

These align with the locked invariants in [`epic_nodes_factory.md`](epic_nodes_factory.md):

1. **Core `NodeType` enum stays as-is.** [`utk_curio/frontend/urban-workflows/src/constants.ts`](../../utk_curio/frontend/urban-workflows/src/constants.ts) is **append-only** for built-ins. Pack kinds **never** add enum members; they are addressed by **canonical string ids** of the form `<packId>/<kindId>@<major>` (see [`manifest_spec.md` §3.1](../../docs/nodesfactory@docs/manifest_spec.md)).
2. **The existing single-arg [`registerNode(descriptor)`](../../utk_curio/frontend/urban-workflows/src/registry/nodeRegistry.ts) signature does not change.** Built-ins keep calling `registerNode(descriptor)` with `descriptor.id: NodeType`; packs call the same function with `descriptor.id: string` (a canonical id). The only type-level change is widening `NodeDescriptor.id` from `NodeType` to `NodeKindId = NodeType | string`.
3. **Packs are fully self-contained on disk.** Pack code (templates, grammars, widgets, icons) is loaded only from `.curio/users/<u>/packs/<packId>@<major>/`. The built-in `<CURIO_LAUNCH_CWD>/templates/<node_type_lower>/` folder is reserved for built-in `NodeType` presets and is invisible to pack code (see [`manifest_spec.md` §1](../../docs/nodesfactory@docs/manifest_spec.md)).
4. **Shared sandbox env.** Pack Python deps install into the existing single sandbox interpreter via `/installPackages` → sandbox `/install`; **no per-pack venv**.
5. **Manifest is the only source for pack node metadata** — the runtime never invents descriptor fields.
6. **Saved Trill graphs persist canonical string ids verbatim** for pack kinds; built-ins keep persisting current `NodeType` values.

---

## 1. Objective

Prove that:

1. A **descriptor** for a node kind can arrive from an installed **package** (manifest + assets per [`manifest_spec.md`](../../docs/nodesfactory@docs/manifest_spec.md)).
2. The client **registers** that descriptor at runtime and exposes it in the **palette** alongside core kinds.
3. **Trill / project JSON** round-trips the **same canonical string id** (core kinds remain valid; legacy enum values map cleanly).
4. The **backend** can **dispatch execution** for that id (one Python template path), using a **dynamic registry** instead of only `_node_type_registry` literals in [`utk_curio/backend/app/api/routes.py`](../../utk_curio/backend/app/api/routes.py).
5. **Dependencies declared in the manifest** ([`manifest_spec.md` §2.3](../../docs/nodesfactory@docs/manifest_spec.md)) are **resolved at install time** and recorded in a project lockfile.

---

## 2. Frontend — registry and types

| Area | Current (verified against repo) | Spike direction |
|------|---------------------------------|-----------------|
| Node id | `NodeType` enum in [`constants.ts`](../../utk_curio/frontend/urban-workflows/src/constants.ts) — **stays** | Introduce **`type NodeKindId = NodeType \| string`** alias. Widen `NodeDescriptor.id` in [`types.ts`](../../utk_curio/frontend/urban-workflows/src/registry/types.ts) from `NodeType` to `NodeKindId`. Built-ins keep using enum values, packs use canonical strings. |
| Registry | `Map<NodeType, NodeDescriptor>` in [`nodeRegistry.ts`](../../utk_curio/frontend/urban-workflows/src/registry/nodeRegistry.ts) | **`Map<NodeKindId, NodeDescriptor>`**. The existing single-arg `registerNode(descriptor)` does not change: it keys the map by `descriptor.id`. `getNodeDescriptor` / `getPaletteNodeTypes` are widened in the same direction. |
| Registration | Core via `registerNode(descriptor)` at module load in [`descriptors.ts`](../../utk_curio/frontend/urban-workflows/src/registry/descriptors.ts) | Core unchanged. **Pack registration** calls the **same** `registerNode(descriptor)` after the per-user pack-store fetch on app boot (and again on a fresh install), with `descriptor.id` set to the manifest-derived canonical string id. No second arity. |
| Palette | [`ToolsMenu.tsx`](../../utk_curio/frontend/urban-workflows/src/components/menus/nodes/ToolsMenu.tsx) uses `getPaletteNodeTypes()` | Annotate each descriptor with `source: 'core' \| 'installed' \| 'new'` and group in the palette; tag descriptors installed in the current session as `'new'` for the badge. |
| Drag payload | `event.dataTransfer.setData("application/reactflow", nodeType)` — single string, today always a `NodeType` enum value | Same single-string payload. For pack kinds the string is the canonical id. The React Flow drop handler resolves the descriptor through the widened registry. |
| Icons | Font Awesome `IconDefinition` in descriptor | Pack icons arrive either as a bundled FA name or a **sanitized** SVG asset under `.curio/users/<u>/packs/<packId>@<major>/icons/` (path validated at install). See [`manifest_spec.md` §3.4](../../docs/nodesfactory@docs/manifest_spec.md). |
| Backend port table | Frontend POSTs the entire `_node_type_registry` to `POST /node-types` at boot ([`routes.py`](../../utk_curio/backend/app/api/routes.py)) | At boot, **merge** built-in entries with pack-derived entries (canonical id → `{inputTypes, outputTypes}`) and POST the union. The backend keeps its existing `_node_type_registry` shape; the spike only changes *what gets POSTed*. |
| Templates feed | [`generate_templates()`](../../utk_curio/backend/app/api/routes.py) walks `<CURIO_LAUNCH_CWD>/templates/<node_type_lower>/*.py` and emits `Template` objects whose `type` is a `NodeType` string. [`TemplateProvider.tsx`](../../utk_curio/frontend/urban-workflows/src/providers/TemplateProvider.tsx) filters by `NodeType`. | Add a sibling that walks `.curio/users/<u>/packs/*/templates/<kindId>/*.py` and emits `Template` objects whose `type` is the pack's `canonicalId`. **Pack templates are never read from `<CURIO_LAUNCH_CWD>/templates/`.** Frontend widens `Template.type` to `NodeKindId`. |

**Lifecycle hooks:** Core nodes use dedicated `useXLifecycle` hooks. For the spike, extension nodes use a **generic Python-template lifecycle** driven by manifest fields; per-pack arbitrary lifecycle code is **not** in scope.

**Migration of legacy enum values in saved graphs:** a small versioned table maps numeric/string `NodeType` values (`"DATA_LOADING"`, etc.) to the same canonical id used today. Built-in canonical ids look like `core/<NODE_TYPE_LOWER>` if we ever need a uniform string view; for now built-ins keep persisting their existing `NodeType` values verbatim — the widened registry simply accepts both.

---

## 3. Graph spec (Trill / React Flow serialization)

| Concern | Spike note |
|---------|------------|
| Node `type` field | Built-ins: existing `NodeType` value. Packs: **canonical string id** `<packId>/<kindId>@<major>`. |
| Migration | Legacy values keep working without rewrite. Pack ids cannot collide with built-in enum members (validator rejects pack ids containing `/` segments matching reserved names). |
| Unknown kind | Renderer shows **placeholder** + "install pack X" banner if the project lockfile lists the missing pack. |
| Project lockfile | Persisted alongside the graph: `installedPacks: [{ id, version, integrity }]` so re-opening the project is reproducible. |

---

## 4. Backend — execution dispatch

| Area | Current (verified against repo) | Spike direction |
|------|----------------------------------|-----------------|
| Python routing | `_node_type_registry` dict in [`routes.py`](../../utk_curio/backend/app/api/routes.py); frontend overwrites at boot via `POST /node-types` | Merge static built-in port table with a **per-user pack map** loaded from `.curio/users/<user>/packs/<packId>@<major>/manifest.json` files at boot (and on install); the merged union is what the frontend POSTs to `/node-types`. The dict shape on the backend does not change. |
| Templates feed | [`generate_templates()`](../../utk_curio/backend/app/api/routes.py) walks `<CURIO_LAUNCH_CWD>/templates/<node_type_lower>/*.py` and uses [`create_template_object()`](../../utk_curio/backend/app/api/routes.py) to emit `{ id, type, name, description, accessLevel:'ANY', code, custom:true }` | Add `generate_pack_templates(user_key)` (sibling to `generate_templates()`) that walks `.curio/users/<user>/packs/*/templates/<kindId>/*.py`, reads each file, and emits the same `Template` shape but with `type = canonicalId`. The two walks are **strictly disjoint**: pack canonical ids are never resolved against `<CURIO_LAUNCH_CWD>/templates/`, and built-in `NodeType` lowercase folders are never resolved against the pack store. The `/templates` route returns the union. |
| Execution | `POST /processPythonCode` → `_sandbox_call('post', '/exec', …)`; sandbox `exec` runs the supplied code string in the **single** sandbox interpreter ([`utk_curio/sandbox/app/api.py`](../../utk_curio/sandbox/app/api.py)) | Unchanged. Pack kinds run inside the **same** sandbox interpreter; the code string for a pack node is sourced from its in-pack template (loaded from the pack root, not the global `templates/`). |
| Validation | Request body constrained by known types | Validate **canonical string id** exists in the merged registry; reject unknown ids with a precise error citing the pack id. |
| Env isolation | Existing process sandbox; single Python interpreter | **No per-pack venv.** Pack `dependencies.python` install into the same sandbox interpreter via the existing `/installPackages` → `/install` path. See §5. |

Security (path traversal, code signing, resource limits) is **spike Phase 2** but **must** be listed as blockers before any "public marketplace" release. Path traversal is partly addressed in v1 by §3 of [`manifest_spec.md`](../../docs/nodesfactory@docs/manifest_spec.md) (every asset must resolve inside the pack root).

---

## 5. Dependency resolution (install-time)

Drives Step 4 of the factory wizard ([`figma_mockups/07_factory_step4_dependencies.svg`](figma_mockups/07_factory_step4_dependencies.svg)) and the install dialog ([`figma_mockups/02_install_permissions.svg`](figma_mockups/02_install_permissions.svg)). Full schema in [`manifest_spec.md` §2.3](../../docs/nodesfactory@docs/manifest_spec.md).

| Bucket | Resolver | Where it runs | Failure mode |
|--------|----------|---------------|--------------|
| `compatibility.curioRuntime` | Semver against host app version | Install dialog precheck | Reject install before resolution |
| `dependencies.packs` | DAG walk against the per-user pack cache (`.curio/users/<u>/packs/`) + sideload archives; single version per pack across the project | Backend installer | Reject with cycle / unsatisfiable / missing-pack error |
| `dependencies.python` | pip resolver against PyPI; merges every installed pack's Python requirements for the active project into a **single requirement set**, then installs into the **shared sandbox interpreter** via `POST /installPackages` → sandbox `POST /install` (`subprocess.run([sys.executable, '-m', 'pip', 'install', …])` in [`utk_curio/sandbox/app/api.py`](../../utk_curio/sandbox/app/api.py)). **No per-pack venv.** | Backend installer | Reject with resolver error, **including any cross-pack incompatible semver range for the same package** |
| `dependencies.js` | npm resolver against the **shared sandbox JS runtime**, parallel to Python; only invoked when at least one `nodeKind.engine == "javascript"` | Backend installer | Reject (same conflict policy) |
| `dependencies.system` | Reserved | n/a in v1 | Reject if non-empty |

Outputs:

- **Project lockfile** (inside `spec.trill.json`): `installedPacks[]` with sha-pinned integrity hashes **plus** `resolvedPythonDeps` / `resolvedJsDeps` maps (see [`manifest_spec.md` §6](../../docs/nodesfactory@docs/manifest_spec.md)).
- There is **no per-pack lockfile** — the project is the isolation boundary because the sandbox env is shared.

The spike must demonstrate **deterministic install on a clean machine**: same manifest + same lockfile in `spec.trill.json` → same registry state, same shared-env package versions, same template files on disk under the pack root.

---

## 6. Deliverables (spike branch)

1. **Design PR / doc**: migration table for legacy `NodeType` values; sample Trill snippet for one pack kind; sample `spec.trill.json` with `installedPacks[]` + `resolvedPythonDeps`.
2. **Spike PR**: one hard-coded **fake** "installed" pack extracted into `.curio/users/<dev-user>/packs/<packId>@<major>/` (templates loaded **only** from there) that registers a second kind on the existing single-arg `registerNode(descriptor)` (with `descriptor.id` set to a canonical string id) without a new enum member; one execution round-trip; lockfile written into `spec.trill.json`.
3. **Risks log**: performance of large registries; icon loading; cross-pack semver conflicts on the **shared** sandbox env; template-loader path-validation correctness; eventual need to multiplex multiple shared envs per *project* if pack ecosystems diverge.

---

## 7. Out of scope for spike

- Public warehouse HTTP API and payments (server-side warehouse storage is v2; v1 uses sideloaded `.curio-nodepack` + the per-user `packs/` directory only).
- Author signing infrastructure (key issuance, revocation).
- Native deps (`dependencies.system`) — declared as v2.
- Arbitrary user-defined **lifecycle** code (only declarative / template-driven execution).
- Per-pack virtualenv / per-pack node_modules — explicitly out by invariant 4; v1 is shared-env only.
- Full Node factory authoring UI implementation (mocks ready in [`figma_mockups/04..08`](figma_mockups/) — implementation lands after the spike).
