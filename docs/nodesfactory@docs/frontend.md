# Frontend Implementation

## Routes

Authentication is required. Routes are declared in `utk_curio/frontend/urban-workflows/src/index.tsx`:

| Path | Component | Role |
|------|-----------|------|
| `/nodes` | `NodesHub` | Browse catalog, manage installed packs, sideload, install/uninstall; opens **Node Factory** as a modal (create / fork-from-installed). |
| `/nodes/factory` | `NodeFactoryRouteBridge` (`NodeFactory.tsx`) | Deep link only: opens the modal with hydration from **`location.state.curioDraft`** or legacy **`sessionStorage`**, then **`replace`** navigates back to **`/nodes`**. |

The authoring UI itself lives in **`NodeFactoryWizard.tsx`**, rendered by **`NodeFactoryModalProvider`** (portal overlay).

Navigation entry: **Data → Nodes hub** (`UpMenu.tsx`).

## API client

Module: `src/api/packsApi.ts`

Design rules (from module docstring):

1. JSON calls use `apiFetch` for Bearer token and error handling.
2. Multipart upload and binary download use `fetch` directly with the same auth header.

Exported object `packsApi`:

```typescript
packsApi.listInstalled()      // GET /api/packs
packsApi.catalog()            // GET /api/packs/catalog
packsApi.uploadArchive(file, filename, { replace? })
packsApi.installFromCatalog(dirName, { replace? })
packsApi.uninstall(dirName)
packsApi.download(dirName)
packsApi.factoryBuild(draft)
packsApi.factoryInstall(draft)
packsApi.resolve(packs: string[])
packsApi.installDeps(packs: string[])
```

After mutating installed packs, callers should await **`refreshPackRegistry()`** from the same module.

## Registry refresh

`refreshPackRegistry()` delegates to `window.curio.refreshPackRegistry`, which is assigned in `index.tsx`:

```typescript
export function refreshPackRegistry(): Promise<void> {
  return loadInstalledPacks().then(() => syncNodeTypeRegistry());
}
```

- **`loadInstalledPacks()`** (`registry/packsClient.ts`): on successful `GET /api/packs`, clears all client descriptors with `source === 'pack'`, then registers each kind from the response. This ensures **uninstalled packs disappear from the palette** without a full page reload.
- **`syncNodeTypeRegistry()`**: builds the port map from `getAllNodeTypes()` and `POST` s it to `/node-types`.

## Palette dock (`ToolsMenu`)

Module: `components/menus/nodes/ToolsMenu.tsx`  
Styles: `ToolsMenu.module.css`

The graph editor mounts a **fixed** horizontal bar at the upper-left (`top: 150px`, `left: 50px`):

| DOM id | Role |
|--------|------|
| `tools-palette-dock` | Flex row container: built-in column + pack control |
| `tools-menu` | Built-in **Built-in** section + **Run all** button only |
| `packs-palette` | Pack trigger + open panel (`ref` for outside-click handling) |

Behaviour:

- **Built-in** node kinds are shown in a two-column grid (existing category grouping: data/flow, computation, visualisation).
- **Pack** kinds are not listed in that column. They are loaded from the same registry (`source === 'pack'`) but **grouped by pack** (`packId` + `major`) and rendered inside **`PacksPaletteDropdown`**:
  - Collapsed: compact **Packs** trigger (cube icon, label, total kind count, chevron).
  - Expanded: panel opens **to the right** of the trigger (toward the canvas). Each installed pack is a **`<details>`** block (summary shows publisher · coordinate and kind count; expandable body lists draggable tiles in a two-column grid).
- **Escape** closes the pack panel; **outside mousedown** (capture phase) closes it while open (unless **pack edit mode** is on — see below).

**Modal Node Factory (`NodeFactoryModalProvider`)**

- The provider wraps authenticated app chrome (see **`index.tsx`**) beneath **`ToastProvider`**. **`useNodeFactoryModal().openNodeFactory`** accepts **`{ blank?, draft?, forkInstallNotice?, onInstallSuccess? }`**, clones optional drafts, traps focus inside the **`role="dialog"`** surface, confirms before close when the wizard is dirty, locks body scroll while open, and handles **Escape / backdrop click** dismissal (backdrop uses the same dirty gate as Close).
- **Successful `factory/install`:** the wizard awaits **`refreshPackRegistry()`**, then the provider shows a **success** toast, runs any **`onInstallSuccess`** callback supplied by the opener, and closes the modal. **Export** / **catalog publish** keep the wizard open unless the user dismisses.

**Edit mode (docked palette only)**

- In the expanded panel toolbar, **Edit** enables pack-authoring affordances. **Save draft** calls **`factoryInstall`** for staged sections (palette save path — does not navigate). **Cancel** exits edit mode.
- While edit mode is active, **outside-click does not close** the panel (avoids losing focus mid-edit). **Escape** still exits edit mode first, then closes the panel on a second press.

**Draft packs & canvas staging**

- **`Add new pack`** (accent dashed row at the **top** of the scroll stack) inserts a **`New pack (draft)`** `<details>` block **immediately beneath that button**, so it becomes the **first** draft section; older drafts shift down (still listed above installed packs). Opening **Edit** is required — the row is hidden in read-only mode.
- Draft sections (and installed pack sections while editing) append a **dashed rounded drop slot** **after** all listed kinds plus any **already staged canvas instances**. Each successful drop adds one **staging row** and keeps **one trailing** drop zone at the bottom of that section’s queue.
- **Duplicate drops:** dropping the **same** canvas node onto a section multiple times creates **multiple staging rows**, each with its own **`rowId`** but pointing at the same **`canvasNodeId`** (React Flow node id). **`buildDraftForPaletteSection`** (`palettePackFactoryDraft.ts`) preserves that order and emits **distinct draft kinds** when needed (e.g. fork when template bodies collide).
- **`draftForkFromInstalledPackPayload`** — clones an installed **`PackPayload`** into a wizard **`Draft`** with a fresh **`packId`** and **`forkedFrom` / `root` lineage**. Entered from the palette (**Edit**, **no** staging — sectional **title / pencil** or fork-toolbar **title / pencil**) or from **Hub → My packs** (**name / pencil**) via **`useNodeFactoryModal().openNodeFactory`**. Installed-pack sections **with staged nodes** keep using **`buildDraftForPaletteSection`** (**lineage** + merged template bodies).
- **`draftFromInstalledPackPayload`** — exact-coordinate copy for **dev catalog fixture publish**, not fork flows.
- Staging lives in **`PackPaletteContext`** as **`draftPackSectionIds`** and **`stagedRowsByPackKey`**: values are **`PackStagedRow[]`** `{ rowId, canvasNodeId }`. Removing a row uses **`rowId`** so only one copy is removed. Turning **Edit** off (**Cancel**, **Escape** clearing edit, or **Save draft**) **discards drafts and staged rows** (local UX until backend / Factory persists them).
- On each **`NodeContainer`**, when packs **Edit** is on and not in dashboard-only mode, a **`nodrag` grip** in the title bar carries MIME **`application/x-curio-pack-staging-node`** + JSON **`{ nodeId }`** (`urban-workflows/src/constants/packPaletteStaging.ts`), so dragging from the grip does not interfere with React Flow’s node-drag behaviour.

**Active pack section & canvas sync**

- The app keeps an **`activePackKey`** (`packId@major`) in `PackPaletteProvider` (wraps `MainCanvas` in `index.tsx`).
- Selecting a node on the canvas whose type is a pack canonical id (`<packId>/<kindId>@<major>`) updates **`activePackKey`** so the matching **Pack** `<details>` block gets a **blue outline** in the palette (`ToolsMenu.module.css` → `.packDetailsSelected`).
- **Fork families:** multiple installed forks that share **`manifest.lineage.root`** (`packId@major`) are collapsed into **one palette row**, with a **native `<select>`** to switch which fork’s expandable body (kinds grid, edit-mode staging rows, dashed drop zones) is shown. Staging stays keyed per **install** **`packId@major`** — **`stagedRowsByPackKey`** and **`PackCanvasDropSlot`** never merge rows across forks. When **`activePackKey`** names a fork in that family but the family header’s **`selectedForkKey`** differs (e.g. user previously picked another fork), a **`useEffect`** syncs selection to **`activePackKey`**; **`sessionStorage`** under **`curio.forkFamilySelection.v1:<rootKey>`** (`FORK_SELECTION_SESSION_PREFIX` in **`src/utils/forkPackLineage.ts`**) remembers the last fork choice per root.
- Clicking a pack section summary sets **`activePackKey`** to that pack.
- Each pack kind row shows an **icon drag target** (left) and a **label + category chip** (right). The **label/button** selects all nodes whose type matches that canonical id (via `useReactFlow().setNodes`).

**Pack node header (canvas)**

- For `source === 'pack'`, `NodeContainer` renders a **category pill** and **`packId@major`** above the usual title row (`styles.tsx`).
- When **`descriptor.pack.lineage`** is set, a second muted monospace line (**`Fork of …`**, **`title`** holds root when it differs from **forkedFrom**) sits under the coord, kept to **≤9px**.

The component subscribes to registry mutations via `useSyncExternalStore(subscribeToRegistry, ...)` so installs, uninstalls, and `refreshPackRegistry()` update the dock without a full reload.

### `fitViewWithMenuOffset`

`utils/fitViewWithMenuOffset.ts` adjusts React Flow’s viewport after `fitView` so content is centered in the **visible** canvas. It measures **`#tools-palette-dock`**’s `getBoundingClientRect().right` and shifts the viewport by **half** of that value (same geometric model as a single left occlusion strip: the dock includes both built-in and pack UI, including an open pack panel).

## Pack descriptors and palette data flow

`registry/packsClient.ts` maps each raw pack kind to a `NodeDescriptor` with:

- `id`: canonical `<packId>/<kindId>@<major>`
- `source: 'pack'`
- `pack`: provenance metadata
- `inPalette: true`, `paletteOrder` after built-ins
- `badge: 'PACK'`

`ToolsMenu` partitions `getPaletteNodeTypes()` into **core** (`source !== 'pack'`) vs **pack** (`source === 'pack'`). Pack descriptors are further **grouped** in-memory by `${pack.packId}@${pack.major}` for the dropdown sections (sort order: section label; within a pack, `paletteOrder`).

## Node registry primitives

`registry/nodeRegistry.ts`:

- `registerNode(descriptor)` — add or overwrite by `id`
- **`clearPackNodes()`** — remove entries with `source === 'pack'` (internal to pack reload path)
- `subscribeToRegistry(listener)` — notify palette subscribers

## Nodes Hub (`NodesHub.tsx`)

Responsibilities:

- Load catalog and installed lists; merge `installed` flags.
- Filter by tab (e.g. all / data / computation / visualisation) and search.
- **Install flow:** optional `resolve` probe; permissions and dependency summary; `installFromCatalog` or upload.
- **Uninstall:** `DELETE` via `packsApi.uninstall`, treats `404` as success for idempotency, then `refreshPackRegistry()` and list reload.
- **Export:** `packsApi.download`.
- Sideload: hidden file input + `uploadArchive`.
- **Fork in Node Factory:** **Create new pack** opens a blank wizard; each installed singleton / fork-member row (**name** or pencil) opens **`draftForkFromInstalledPackPayload`** with **`forkInstallNotice`** so Step 5 and the banner remind installers the source pack stays on disk (**new** `factory/install`).
- **Fork families (“My packs” rail):** same **`partitionPacksByForkFamily`** grouping (**`forkPackLineage.ts`**) as the palette — groups installed packs by **`lineage.root`**. Families with multiple members render a toolbar + fork **`<select>`** (warehouse styling); every fork keeps its own **Export** / **Remove** (**`dirName`**). Singles with lineage behave as singletons. **Catalog** grid stays flat; cards show **`Fork of …`** when **`pack.lineage`** exists, **`familyKey`** on every row from the API, **`families`** and **`catalogCollisions`** only on **`GET /api/packs/catalog`**, plus a non-**stable** **`channel`** chip when **`distribution.channel`** is set in the manifest (`packsApi` types aligned).
- **Fork sources in the dock:** When at least one installed pack has **`lineage`**, the My packs header gains an **eye** control: **`packsApi.forkParentsPaletteDockVisibility(visible)`** posts to **`POST /api/packs/palette-dock/fork-parents`**, which rewrites **`curio.paletteDock.hiddenFromForkPaletteDock`** on fork-parent installs (see [Manifest §2.4.2](manifest_spec.md)). The hub then **`refreshPackRegistry()`** and reloads the list so **`ToolsMenu`’s PACKS dropdown** picks up **`pack.hiddenFromForkPaletteDock`** on descriptors — **no `localStorage`**.

## Node Factory (`NodeFactoryWizard.tsx`)

Five-step modal wizard (hosted by **`NodeFactoryModalProvider`**; route **`/nodes/factory`** is a bridge that **`replace`**-navigates to **`/nodes`** after hydrating). Behaviour matches [Manifest specification](manifest_spec.md); backend gates live in [`manifest.py`](../../utk_curio/backend/app/packs/manifest.py)). Calls **`factoryBuild`**, **`factoryInstall`**, and **`factoryPublishCatalog`** unchanged. **`draft.lineage`** renders provenance captions in Step 1; forks opened with **`forkInstallNotice`** surface a banner plus Step 5 text that install targets a **new** coordinate (`palettePackFactoryDraft.ts`, **`draftForkFromInstalledPackPayload`**).

## TypeScript types

Key interfaces in `packsApi.ts`: `PackPayload` (includes **`familyKey`**, **`channel`**, and optional flattened **`paletteDock.hiddenFromForkPaletteDock`** only when **`true`** in the manifest), `PackLineagePayload`, `PackKindPayload`, `ResolveResponse`, `Lockfile`, `InstallDepsResponse`, `ResolveConflict`. These mirror the JSON emitted by `_manifest_to_payload` and resolver routes (lockfile **`installedPacks`** entries may include **`familyKey`** and **`lineageRoot`**). Installed/catalog packs include **`lineage`** (`{ forkedFrom, root } | null`) when the manifest declares fork provenance; pack descriptors expose it as optional **`pack.lineage`** on `NodePackMeta` (`registry/types.ts`), plus **`pack.hiddenFromForkPaletteDock`** derived from **`curio.paletteDock`** for **PACKS** palette filtering. `factoryDraftModel.ts` defines **`Draft.lineage`** and **`toApiPayload`** emits **`manifest.lineage`** when palette-forking an installed pack.
