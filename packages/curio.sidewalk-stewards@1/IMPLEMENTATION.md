# Sidewalk Stewards implementation manifest

## Identity and release scope

| Item | Value |
| --- | --- |
| Runtime package | `curio.sidewalk-stewards`, version `1.0.0`, major `1` |
| Directory | `packages/curio.sidewalk-stewards@1` |
| Runtime declaration | [manifest.json](manifest.json), Curio node-package v4 schema |
| Companion package | [curio.streetvision@1/manifest.json](../curio.streetvision@1/manifest.json), version `1.2.0` |
| Sidewalk entry | `sources/index.tsx` → `scripts/behaviors.js` (+ source map) |
| Integrity | Each package's `integrity.json`, regenerated from its included files |
| Review baseline | Curio main `6a4721c0afb0f6bca23c9c1ff55ad851eab86341` (0.16.452) |

This PR delivers Phase 1 of the Sidewalk Stewards integration: the current tile-editing and Street View inspection nodes. Shared Curio/Autark interaction prerequisites and prediction-node integration remain follow-up work.

This is a draft with two known automatic map-opening acceptance failures. It preserves the current editing and inspection implementation without including the prototype's shared Autark changes or inventing replacement click semantics.

## Included nodes, ports and contracts

| Node | Input | Output / interaction | Responsibility |
| --- | --- | --- | --- |
| Sidewalk Prepare | Two required data input circles (`in`, `in_1`), GEODATAFRAME/JSON-compatible wrappers | One data output; bidirectional node declaration | Validate one image reference plus one original network, hydrate the full grid/boundaries, optionally attach sparse measurements, publish independent Before context |
| Sidewalk Tile Edit | One data input, GEODATAFRAME/JSON; interaction edges | One GEODATAFRAME/JSON output and versioned interactions | Edit an active tile, retain drafts/history, apply cumulative corrections to After, request Street View inspection |
| Street View Panorama | One ordinary data input or versioned request interaction | No data output port; bidirectional interaction channels | Accept WGS84 `[longitude, latitude]`, load a navigable panorama, report actual camera location/heading and request status |
| Street View Fetcher | No data input; place/options/session credential UI | One GEODATAFRAME output | Geocode a place, sample coverage and return image-point features with opaque image URLs |

Prepare expects `kind:"sidewalk-image"` and `kind:"sidewalk-network"` dictionaries, one per input. The image declares dataset identity/hash, a GeoTIFF reference/output table/CRS, grid and boundary URLs, a `{tile_id}` image URL template and georeferencing bounds/grid hash/mapping. The network declares the same dataset identity, URL/hash, EPSG:4326 and original FeatureCollection. Input loaders verify bytes; Prepare validates declared resources and derives a source fingerprint. See [beforeAfterContext.ts](sources/beforeAfterContext.ts), [provenance.ts](sources/provenance.ts) and [portable source example](../../docs/examples/28-sidewalk-review-workflow.json).

The context preserves the complete `upstream` tile grid, `sidewalk_network` and `tile_boundaries`. Optional `sidewalk_typology` rows remain sparse measurements; they do not replace the complete editing grid. Autark geometry preparation accounts for its coordinate precision; underlying original geometry remains available for corrections/provenance. Resource inputs must be explicit and accessible after reopening. Direct selected-resource paths are validated by [selectedResources.ts](sources/selectedResources.ts); no private Recife fallback is bundled.

Internal versioned schema identifiers remain `io.github.lzml0.sidewalk-stewards/.../v1` to preserve the existing wire/data contracts. Channels include `sidewalk.active-tile`, `sidewalk.active-tile-request`, `sidewalk.inspection-request`, `sidewalk.camera-context` and `sidewalk.network-edit`. Generic Panorama request, status and camera contracts use `curio.streetvision/.../v1`. Node configuration remains `curio.sidewalk-tile-edit/v1`. Namespace migration does not rewrite these payload fields. The authoritative types, validation and correlation rules are in [streetViewContract.ts](sources/streetViewContract.ts), [networkEditContract.ts](sources/networkEditContract.ts) and [panoramaContract.ts](../curio.streetvision@1/sources/panoramaContract.ts).

## Editing and persistence

- Existing toolbar modes: Inspect Street View, Draw edges, Move nodes and Delete; Undo/Redo are history commands. Save network remains a separate action. Keyboard tools, splitting, topology warnings and existing UI styling are retained.
- Cardinal navigation uses grid adjacency. Each tile owns its network draft, operation list, undo and redo stacks. A → B → A restores its draft/history during the mounted workflow. Resource and source identities protect against reusing incompatible data.
- A **draft** is an unsaved tile edit. **Save network** records that tile's correction and emits a versioned edit plus cumulative After context. It replaces the relevant clipped geometry while preserving untouched network parts. Before continues to use the original context.
- **Workflow Save** serializes node configuration, including per-tile draft/history and saved corrections. It is distinct from Save network. Provider credentials are excluded. A browser reload before Workflow Save can lose unsaved state. Full fresh-upstream browser save/reopen reliability is not established; the observed grammar discrepancy is tracked separately below.
- Relevant components: [SidewalkTileEditor.tsx](sources/SidewalkTileEditor.tsx), `sidewalkTileEditBehavior.tsx`, `sidewalkEditOperations.ts`, `sidewalkTopology.ts`, `tileNeighbors.ts`, `overviewData.ts`, `useSidewalkOverview.ts` and `sidewalkPreparation.tsx`.

## Street View state and credentials

Requested point, active editing tile and confirmed camera position are distinct. Missing-key inspection retains the latest valid request and displays the original Stewards pointer in theme gray, identified as “Requested location — Street View not loaded.” The editor and Panorama show inline configuration notices. The latest pending request is processed when the key/provider becomes ready; it remains gray while loading. Only actual camera confirmation produces the original red pointer at the actual coordinate/heading. Failed requests retain a pending/error state, and old visible panoramas are distinguished from the pending target.

Request IDs/revisions, editor/source/selection epochs and camera revisions reject superseded callbacks. A camera move does not select an editing tile. On other tiles the red pointer is hidden and the “Camera outside the active tile” label appears. **Open camera tile** is the explicit navigation action. A tile containing the actual camera displays its red marker without the outside label. Tests cover these paths with fixtures, not new live-provider lookups.

Panorama Settings uses an in-memory browser-restricted Maps JavaScript API key, with Add configuration/Cancel. Fetcher accepts a separate Static API credential. No credential is serialized to node content or examples. A configured key does not prove provider authorization. Reload requires re-entry. Backend Fetcher requests transiently use the supplied credential; returned image URLs expose opaque tokens, not keys. The token cache expires after **two hours**, **512-entry eviction**, or **backend restart**. Rerun Fetcher to restore expired links. The current fetch/image-proxy authentication and access pattern is retained; no new durable credential store is introduced.

Street Vision implementation: `streetViewFetcherBehavior.tsx`, `streetViewPanoramaBehavior.tsx`, `googleStreetView.tsx`, `panoramaContract.ts`, `nodeUiStyles.ts` and `apiAuth.ts`. Sidewalk uses a small re-export of its shared viewer/contract/style source; webpack bundles those modules into the Sidewalk artifact. Both manifests declare no additional JS/Python/catalog package dependencies. They reuse the host's React, Font Awesome and existing libraries. The workflow explicitly includes both packages for inspection. No Autark or model dependency is upgraded.

Required Fetcher backend support is in `utk_curio/backend/app/streetvision/` (`__init__.py`, `routes.py`, and the `services/` helpers). Its `/api/streetvision` blueprint exposes `/health`, `/data/streetview/search_place`, `/data/streetview/coverage`, `/data/streetview/fetch`, and `/data/streetview/image/<token>`. There are no model inference/training endpoints.

## Necessary shared Curio changes

| File | Purpose and evidence |
| --- | --- |
| `utk_curio/backend/app/__init__.py` | Register the Fetcher blueprint; backend fixtures exercise Fetcher output, key omission and cached image proxy requests. Expiry policy is documented from implementation, not a fresh clock-boundary test |
| `utk_curio/frontend/urban-workflows/webpack.packages.config.js` | Add the two shipped package entry points using existing webpack infrastructure |
| `utk_curio/frontend/urban-workflows/src/components/UniversalNode.tsx` | Remount only when the descriptor behavior hook changes, including fallback replacement for the same node type; pass the current descriptor through React.memo. Fresh main's node-type-only key does not handle this package-loading case. Existing normal same-hook updates retain state |
| `src/tests/components/universalNodeAutoRender.test.tsx` (frontend) | Focused regression for replacement without node-type change plus retention across same-hook updates; fresh main's prior tests retained |

The production Autark adapter, selection/routing helpers, library bundles, dependency manifests and lockfiles are unchanged from the base. No runtime monkey patch is introduced.

## Package migration

The established `curio.*@major` convention is used, consistent with Street Vision and shipped Curio packages. Previous identity: `io.github.lzml0.sidewalk-stewards@1`. New identity: `curio.sidewalk-stewards@1`. There is no duplicate alias package in this draft.

For a saved Trill JSON, make a copy and replace the package lock entry with `curio.sidewalk-stewards@1`, and the node type prefixes `io.github.lzml0.sidewalk-stewards/sidewalk-prepare` / `.../sidewalk-tile-edit` with `curio.sidewalk-stewards/...`. Registry-resolved IDs append `@1`; serialized example node types use the unversioned namespace and the packages list supplies the major. Preserve node IDs, edges, node content, `byTile`, source fingerprints and versioned wire schemas. Import the migrated copy with both packages installed. The old Street View Context template/registration is deliberately absent; use Street Vision's Street View Panorama and review any legacy viewer configuration explicitly. No automatic legacy-viewer conversion is claimed.

## Examples and evidence

- [Current review workflow JSON](../../docs/examples/28-sidewalk-review-workflow.json) and [walkthrough](../../docs/examples/28-sidewalk-review-workflow.md): actual eight-node/twelve-edge layout, preserved map and PCP settings, portable resource substitutions documented.
- [Compact portable example](../../docs/examples/27-sidewalk-street-view.json) and [walkthrough](../../docs/examples/27-sidewalk-street-view.md).
- [CC0 synthetic inputs](../../docs/examples/data/sidewalk-synthetic/README.md), six schematic PNGs, small GeoTIFF, complete grid, sparse measurements and two boundary-crossing original lines. Builder: `scripts/build_example_sidewalk_inspection.py`. No real provider or Recife imagery is distributed.
- [Historical capability audit, October 9](../../docs/sidewalk/autark-grammar-curio-audit.md): original examined versions, findings and limitations retained.
- [Current map-selection investigation, October 19](../../docs/sidewalk/map-selection-investigation.md): actual upstream event fixtures, failed gates and repository ownership.
- [Complete consolidated capability table](../../docs/sidewalk/consolidated-capability-table.md): all 36 rows from the supplied workbook's Sheet2, with exact four columns and original qualifications.
- [Fresh Phase 1 verification](../../docs/sidewalk/phase1-verification.md): commands, counts and browser scope for the final PR version. Earlier prototype results do not validate this version.

## Known compatibility failures and ownership

Additional open [submission review follow-ups](../../docs/sidewalk/phase1-review-followups.md) cover Fetcher server limits/bounds/authentication, provider failures misreported as empty success, the missing reproducible first-tile activation procedure, and integration verification against newer main. They are recorded for later work; no fixes or additional compatibility claims are included in this follow-up.

1. **Confirmed: automatic map → editor activation fails for keyed and positional upstream events.** The package requires prototype `selectionOrigin` and explicit active index. Upstream emits the post-toggle selection set. Different actual hits produce the same event; repeated hit versus miss can both emit `[]`. The two acceptance gates deliberately remain failing. No candidate-order, timing or set-difference heuristic is used.
2. **urban-toolkit/autark (`autk-map`) prerequisite:** add explicit hit/miss information alongside the existing selection set. The hit is already known internally; tests demonstrate its loss. A request-time sequence/generation needs verification before claiming stale native-pick ordering protection.
3. **urban-toolkit/curio adapter prerequisite:** preserve origin from its distinct map/plot listeners and translate the explicit native hit through its existing row/key machinery without changing selection sets. Coordinate active editing tile separately from PCP candidates and camera position. Prototype adapter code is excluded.
4. **urban-toolkit/autk-grammar:** current forwarding drops hypothetical extra hit fields. Extending forwarding is one delivery path. A separate Grammar change is optional if the generic Curio adapter subscribes to the supported public map events after the native extension. Cleanup and layer identity require verification.
5. **Unverified: sparse PCP-to-full-grid cross-layer mapRef routing and independent overview/active-tile highlighting on fresh main.** Existing supported selection/highlighting mechanisms exist, but this draft does not port prototype routing changes or assert full compatibility. Before picking remains enabled in its exported specification.
6. **Separate saved-grammar discrepancy:** the saved running workflow had `{}` for Before while its visible editor showed the intended selectable layer grammar. PCP/After saved and visible grammars matched. The portable export records that visible Before grammar and documents the choice. No running workflow was saved or altered. Production save/reopen reliability is unverified, even if fixture round trips pass.

The historical audit is not proof that every defect persists in current versions. The consolidated table distinguishes required dependencies, conditional verification, optional improvements and unrelated backlog work. Phase 2 does not require every audit finding.

## Exclusions and roadmap

Excluded: HF/prediction/training nodes, implementations, templates, registrations, routes and dependencies; Tile2Net node; synchronized prediction overlays; approximately 1.25 GB full Recife dataset; private corrections/drafts/state/credentials/caches; prototype Curio adapter and native Autark changes; unrelated UI changes. The original working installation and excluded work remain intact outside this PR.

1. **Phase 1 — Current editing and inspection:** preparation, editing, navigation, drafts, undo/redo, Save network corrections and required Street View functionality, with workflow example, manifests, tests and audit documentation.
2. **Phase 2 — Curio/Autark integration and verification:** implement shared prerequisites in their owning repositories. Verify map-to-editor selection, editor-to-map highlighting, independent PCP candidates/active tile, event identity and workflow save/reopen. Broader audit work remains a separate backlog.
3. **Phase 3 — Tile2Net node and model inference (planned):** add a dedicated Tile2Net node producing a network for preparation/editing. Define explicit inputs/outputs. Integrate other inference results through the appropriate package with image, geometry and result contracts before adding overlays.

No training support or complete Sidewalk Stewards parity is claimed.
