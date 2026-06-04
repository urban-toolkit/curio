# Nodes Factory — Technical spike (Option A)

**Scope:** Define what must change to support **installed node packs** using a **single additional compile-time `NodeType`** (or a small fixed set of carrier types) whose **behavior is driven by instance data** (manifest slice, template reference, pack id). This is the **generic carrier** path from the epic architecture discussion: **minimal change to the enum and registry model**; the main work shifts to **payload schema, dispatch, and `UniversalNode` reading extended `data`.**

**Relationship to Option B:** Option B treats each pack kind as a **first-class string id** in a dynamic registry — see [`spike_option_b.md`](spike_option_b.md). Option A **does not** add a new enum member per pack; it adds **one** (or few) carrier type(s). **No implementation in this document** — spike code follows the same product gate as the epic ([`epic_nodes_factory.md`](epic_nodes_factory.md)).

---

## 1. Objective

Prove that:

1. An installed **package** (manifest + assets on disk) can supply enough metadata for **one palette entry** that drops a **carrier** node onto the canvas.
2. That node's **React Flow / Trill `data`** holds a **stable reference** to the pack (`packageId`, `semver`, `kindKey` or hash) plus any **descriptor snapshot** needed for ports, labels, and editor mode.
3. **`UniversalNode`** (or a thin wrapper) can render **ports, title, and editor** from that payload without a separate `registerNode()` call per pack kind.
4. The **backend** can **dispatch execution** by reading **carrier type + payload** (e.g. resolve `templateRef` to a file under the user package dir), extending rather than replacing `_node_type_registry` in [`utk_curio/backend/app/api/routes.py`](../../utk_curio/backend/app/api/routes.py).

Success = **one** dev-installed fake pack, **one** carrier palette entry, **one** execution path — without registering hundreds of string kinds in `nodeRegistry.ts`.

---

## 2. Trade-offs (session recap)

| Aspect | Option A (this doc) | Option B ([`spike_option_b.md`](spike_option_b.md)) |
|--------|---------------------|-----------------------------------------------------|
| **Enum / registry** | +1 (or +2) `NodeType`(s); existing `registerNode` pattern unchanged for carriers | Many runtime kinds; `Map<string, NodeDescriptor>` or equivalent |
| **Per-pack surface area** | Payload + validation + dispatch | Descriptor registration + id migration |
| **Trill / JSON** | `type: EXTENSION_NODE` (name TBD) + rich `data` | `type: string` per kind |
| **Risk** | `UniversalNode` and sandbox dispatch grow **conditional branches**; payload must stay versioned and validated | Larger refactors to types, `FlowContext`, and backend registry |
| **Feels like native** | Good if UX hides carrier; weaker if users inspect raw spec | Each kind is naturally distinct in saved spec |

---

## 3. Frontend — carrier type and data

| Area | Current | Spike direction (Option A) |
|------|---------|----------------------------|
| `NodeType` | All kinds enumerated | Add e.g. `EXTENSION_PACK_NODE` (name TBD) — **one** carrier for declarative Python-template packs; optional second carrier later (e.g. grammar-only). |
| `NodeDescriptor` | One per `NodeType` in [`descriptors.ts`](../../utk_curio/frontend/urban-workflows/src/registry/descriptors.ts) | **Single** descriptor for the carrier: generic ports or **dynamic ports** read from node `data` at render time. |
| `registerNode()` | Per kind | **No** per-pack `registerNode`; packs extend **`data` schema**, not the registry map. |
| `UniversalNode` | Driven by descriptor | Merge **descriptor defaults** with **payload overrides** (label, icon ref, port list, `editor`, `templateUri`). |
| Palette | `getPaletteNodeTypes()` | **Virtual rows:** either inject synthetic entries from installed packs that all map to **same** `NodeType` but different **default `data`**, or one **Pack nodes** entry that opens a sub-picker (product choice). |
| Drag / drop | `dataTransfer` = enum | Still **one** enum value; optional secondary channel (e.g. JSON in a custom MIME type) for `kindKey` + `packageId`, or resolve after drop from a global last-selected pack kind store. |

**Lifecycle:** Prefer **one generic hook** (`useExtensionPackLifecycle`) that reads `data.templateRef`, `data.engine` (`python` | `js`), and wires to the same execution paths as code nodes with a resolved template path.

---

## 4. Graph spec (Trill / React Flow)

| Concern | Spike note |
|---------|------------|
| Node `type` | Fixed carrier enum string (e.g. `EXTENSION_PACK_NODE`). |
| Node `data` | **Required keys (illustrative):** `packageId`, `packageVersion`, `kindKey`, `displayName`, `ports` (serializable port defs), `editor`, `templateRef`, optional `manifestHash`, optional `capabilities`. |
| Migration | Existing graphs **unchanged**. New nodes only use carrier + payload. |
| Unknown / missing pack | Renderer shows **placeholder**; load warns if `packageId` not installed; offer install-pack flow if warehouse ids exist. |
| Collision | `kindKey` unique **within** a `packageId` + `packageVersion`; global uniqueness = `packageId` + `kindKey`. |

---

## 5. Backend — execution dispatch

| Area | Current | Spike direction (Option A) |
|------|---------|----------------------------|
| Request body | `node_type` from small enum | Accept carrier type plus **extension payload** (`packageId`, `kindKey`, `templateRef`) in a nested object or extended field. |
| Routing | `_node_type_registry` maps to template path | For carrier type: **resolve template** from the per-user pack root (`.curio/users/<u>/packs/<packId>@<major>/templates/<kindKey>/…`) + `templateRef` (validated under that root); reject path escape. **Never** fall back to `<CURIO_LAUNCH_CWD>/templates/` for a carrier-node template. |
| Registry row | One row per logical kind | **One** row for carrier pointing at a handler that **branches on payload** or uses a generic executor. |
| Env isolation | Existing process sandbox; single Python interpreter | Same as Option B: pack `dependencies.python` install into the **shared sandbox interpreter** via the existing `/installPackages` → `/install` path. **No per-pack venv.** Cross-pack semver conflicts fail closed at install. |

Security: path traversal, signing, resource limits — **before** any public marketplace (same bar as Option B).

---

## 6. Package manifest (minimal v0 for spike)

Same **logical** manifest as Option B, but consumption differs:

- Client does **not** call `registerNode()` per `nodeKinds[]` entry.
- Client **indexes** the pack and builds palette **entries** that instantiate **carrier** nodes with pre-filled `data` from each manifest item.

Illustrative fields:

- `id`, `version`, `displayName`, `author`
- `nodeKinds[]`: `kindKey`, `label`, `ports`, `editor`, `templateDir` + `defaultTemplate` (matching [`manifest_spec.md` §3.3](../../docs/nodesfactory@docs/manifest_spec.md)), `paletteOrder`, `category`

Installing = verify manifest, copy assets into `.curio/users/<u>/packs/<packId>@<major>/`, **update per-user pack index** (`packs/index.json`). Palette reads that index. As with Option B, the pack is fully self-contained: no carrier-node template can reference paths outside its pack root.

---

## 7. Deliverables (spike branch)

1. **Design PR / doc:** JSON Schema or TypeScript interface for carrier `data`; sample Trill node JSON; notes on template path resolution and validation.
2. **Spike PR:** one fake installed pack; palette exposes one **virtual** tool; drop creates carrier node with correct `data`; one successful Python execution path through resolved template.
3. **Decision log:** if payload complexity becomes unmaintainable, recommend moving subsets to Option B or splitting carriers (`EXTENSION_PYTHON` vs `EXTENSION_JS`).

---

## 8. Out of scope for spike

- Public warehouse HTTP API.
- Full **Node factory** authoring UI.
- Arbitrary **per-pack React lifecycle** (declarative / template-driven execution only in v0).

---

## 9. When to prefer Option A vs B (later decision)

- **Prefer A** when most packs are **Python template + ports + widgets** variants and the team wants **smaller** type-system churn in the first release.
- **Prefer B** when packs need **distinct type identities** everywhere (analytics, permissions, graph tooling) or **heterogeneous** lifecycles.

Option A and B can both stay documented for planning; the product may choose **A for MVP** and evolve toward **B** for advanced packs.
