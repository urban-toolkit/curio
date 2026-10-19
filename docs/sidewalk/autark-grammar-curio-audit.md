# Autark → grammar → Curio feature coverage audit

Audit date: October 9, 2026. Read-only examination; all artifacts in this temporary audit directory are in English. No implementation is included.

The public Autark APIs are substantially broader than the declarative grammar. Extending the existing grammar and Autark adapter is sufficient for most small gaps. A new renderer or a new adapter is not warranted. Native runtime ownership, GPU resources and incremental updates must be distinguished from initial declarative configuration.

## Scope and version boundaries

The primary behavioral trace is the running Sidewalk Before/After checkout, not the active prototype. A second inventory covers the newer clean Curio main checkout. Historical checkouts were fingerprinted to establish provenance and package drift, not subjected to a complete behavioral audit. The audit did not fetch Git refs or assert that a cached main is the current GitHub main.

| Checkout | HEAD | Branch | Initial modified/untracked paths | Cached origin/main |
|---|---|---|---:|---|
| `<prototype checkout>` | `fa99d0b51569abddc841f178739f1b2a1c6e1bc9` | `backup/sidewalk-working-prototype-2026-09-29` | 16 | `7449ff32beeceb4a882bdb141acd4407d34bd2e7` |
| `<clean main checkout>` | `d8f8a8b1da69ae4e4a2fa4d67f19d1bb2616ec3a` | `main` | 0 | `d8f8a8b1da69ae4e4a2fa4d67f19d1bb2616ec3a` |
| `<historical-checkout:curio-rgb-geotiff/curio>` | `5966227fbd20199af86406f760660b504d17e992` | `feat/rgb-geotiff-routing` | 0 | `7449ff32beeceb4a882bdb141acd4407d34bd2e7` |
| `<historical-checkout:sidewalk-package/curio>` | `b229380c15159cc8072ab73baf787e3eacc2204a` | `feat/sidewalk-stewards-package` | 82 | `7449ff32beeceb4a882bdb141acd4407d34bd2e7` |
| `<historical-checkout:sidewalk-before-after/curio>` | `b229380c15159cc8072ab73baf787e3eacc2204a` | `codex/sidewalk-before-after` | 105 | `7449ff32beeceb4a882bdb141acd4407d34bd2e7` |
| `<historical-checkout:sidewalk-latest-test/curio>` | `be2303366b366514b9d560b2b04303ae3554277e` | `(detached)` | 74 | `7449ff32beeceb4a882bdb141acd4407d34bd2e7` |
| `<local grammar checkout>` | `278645b769f67659d1c0372877a7f283d5d3c61a` | `feat/geotiff-rgb-source` | 21 | `278645b769f67659d1c0372877a7f283d5d3c61a` |
| `<historical-checkout:autk-rgb-geotiff/autk-grammar>` | `83167431a6ccfe1ccf1a304952de25b784f05353` | `feat/rgb-geotiff-source` | 0 | `278645b769f67659d1c0372877a7f283d5d3c61a` |

The selected Before/After frontend resolves DB **3.0.2-curio.1**, map/plot/compute **3.0.1-curio.1**, core **3.0.1**, and grammar **0.3.0 with local extensions**. Its sandbox resolves DB/core at the same pinned versions; map/plot/compute execute in the browser. The manifests use file tarballs and frontend overrides to keep the grammar's leaf dependencies aligned. The clean RGB-routing checkout instead resolves DB **3.0.2-curio.6**: its package environment is not interchangeable with the selected Sidewalk environment. The experimental prototype resolves DB/map/plot/compute/core **2.1.2** and grammar **0.1.3**.

The clean `<clean main checkout>` checkout resolves DB/plot/compute/core/grammar **4.0.0**, and a vendored map **4.0.0-curio.1**. Its vendor README identifies map source commit `9bba938c1f04bb97c1eff000dcfdd3b501568a7d` (Autark PR #115). Native 4.x adds OSM bounding-box/tag-set interfaces, workspace precision/configuration, per-element OSM export options, building normalization and on-demand map rendering. **Installed grammar 4.0.0 does not contain the local GeoTIFF/RGB, layerOrder or fixed vector color additions.** A migration to a higher package version does not preserve these features automatically.

### Official and local source provenance

- Official Autark monorepo snapshot `77c8b32108c90d4f949519771540d152dfda83a6` was downloaded into this audit directory, without changing any checkout or Git ref. The module structure is `autk-db`, `autk-map`, `autk-plot`, `autk-compute`, `autk-core` and umbrella **`autk`**, all in one repository.
- The selected vendored packages document that base plus merged source contributions: #101 `f494891a8b1545c3de5d81cbe28288edcc1ac51d`, #102 `2a551f37e160cd76477882ae35548bb84d601195`, #103 `c053f976d7eb4b4754ba918ff5461bdc97345133`, #105 `fdddab989ad74220afb4e3f304ad9001e2a856ed`. No single combined source commit is asserted; installed artifacts and embedded source hashes identify the actual implementation.
- Official cached grammar base: `278645b769f67659d1c0372877a7f283d5d3c61a`. Approved local RGB commit: `83167431a6ccfe1ccf1a304952de25b784f05353`. Local uncommitted layer ordering and fixed color source resides in `<historical-artifact:grammar-build>`, and is temporarily installed only in the Before/After checkout.
- The installed grammar artifact matches all **11 embedded authored source records** against that temporary source/build tree. The source-map record for the generic engine matches its existing compiled JavaScript; this is not a fresh rebuild or proof of a TS-source reproducible build. See `grammar-artifact-source-match.json`. The existing packed local grammar SHA-256 is `2f6088efebecc1c9c5d2d4fe8add1df55e1e1ae1af6e609b19ad8c362050aaf3` (recorded independently below).
- Native 4.0.0 package release source commits and the 4.x umbrella source SHA cannot be established from the installed metadata alone. Their declarations and embedded implementation snapshots are identified by package file hashes. **Unresolved provenance is not filled in using an assumed upstream main.** The umbrella at the downloaded 3.x snapshot only reexports the five leaf namespaces/subpaths; it introduces no independent algorithm surface.

Exact resolved packages, export maps, package manifests and fingerprints are in `versions.json`; initial file and installed-package hashes are in `initial-repositories.json` and `installed-initial.json`.

## Inventory boundaries

The TypeScript compiler walked each root export and recorded constructors, callable exports, public instance and static members, configuration signatures, callbacks and inherited public members. The export definition records retain discriminated variants; nested callback/option signatures are also retained. Complete declaration snapshots (346 files), including indirectly referenced option unions, are indexed by `declaration-manifest.json`. Private/protected members and standard-library Array/Map/typed-array methods are excluded. Relevant public inherited plot behavior is included through `PlotBaseInteractive` and `PlotBaseData`. Signatures are an inventory, not proof of executable behavior.

| Snapshot | Module | Root exports | Public member/option records |
|---|---|---:|---:|
| Selected 3.x/local | autk-compute | 12 | 29 |
| Selected 3.x/local | autk-core | 57 | 146 |
| Selected 3.x/local | autk-db | 56 | 151 |
| Selected 3.x/local | autk-grammar | 69 | 218 |
| Selected 3.x/local | autk-map | 24 | 175 |
| Selected 3.x/local | autk-plot | 35 | 104 |
| Clean main 4.x | autk-compute | 12 | 29 |
| Clean main 4.x | autk-core | 59 | 150 |
| Clean main 4.x | autk-db | 65 | 165 |
| Clean main 4.x | autk-grammar | 69 | 211 |
| Clean main 4.x | autk-map | 25 | 181 |
| Clean main 4.x | autk-plot | 35 | 104 |

`public-api-inventory.csv/json` and `public-api-v4.csv/json` contain the complete **root-export declaration inventory for these installed packages**. `export-crosswalk.csv` accounts for every export as a direct capability reference or ancillary module type/constant. It explicitly marks ancillary semantics that were not individually tested. The 73 capability rows are a bounded, grouped feature audit, **not an exhaustive runtime certification** of every overload, geometry, shader, browser or database path. The 4.x behavioral comparison focuses on implementation/type deltas; unchanged methods are inventoried, not independently re-certified. Umbrella namespaces are accounted for by their leaf exports at the downloaded 3.x source snapshot.

## Important findings

1. **Layer ordering and colors are existing native primitives, locally exposed through grammar extensions.** `map.layerOrder` is a local static grammar field using public `Layer.updateLayerInfo({zIndex})` and the layer stack; it is not a newly discovered native AutkMap command. `layerRefs.color` uses native byte RGB conversion and render-state updates. Ordering is applied after load, and does not define persistent ordering of future layer additions/removals. Curio filters unavailable/empty layerRefs but retains layerOrder, which can then fail its exact-permutation check. This is a Curio integration gap.
2. **Line width exists natively and is missing from grammar.** `loadCollection(...,{loadConfig:{polylinesWidth}})` applies full width while constructing road/polyline meshes. Neither the types/schema nor adapter forwarding expose it. A render-state color/opacity patch cannot alter that geometry width. `buildingsZeroHeight` is another missing load option. The smallest useful change is typed load options in the current adapter.
3. **Schema acceptance is permissive, and run does not validate the schema.** Unsupported `camera`, `polylinesWidth`, `maxRasterCells` and `resampleMethod` fields validate against the installed schema. The GeoTIFF adapter forwards exactly URL/name/CRS; the other raster fields are dropped. Plot tick formats, color domains and palettes are similarly absent from the typed spec and constructor projection. Curio's authored runtime parses JSON; its agent schema lacks the local RGB/order/color extensions. Do not describe accepted extras as implemented features.
4. **Declared fields are also ignored or conditionally consumed.** In the Autark map adapter, `colorMapLabels`, `pickedComps`, `getFnvType` and `defaultFnv` are not consumed. Domain/normalization configuration is applied only inside `if (colorMapInterpolator)`, so normalization on its own does nothing. Categorical catch-all is implemented through cloned thematic data; it does not require a separate adapter. The isolated adapter trace confirmed these omissions. The runtime interface also declares `IEngine.updatedSpec()`/`destroy()`, but those implementations are stubs.
5. **Selection identity has a confirmed defect at two layers.** A shared map is registered under each layer's dataRef, then the grammar forwards native map events under the first registry entry's captured ID, ignoring native `MapEventData.layerId`. An actual installed artifact probe sent `layerId:'second'` and received `'first'`. Curio also selects the first authored isPick layer instead of routing by each event's actual layer. Null-geometry row permutations are handled locally, but do not solve this multi-layer source-identity problem. Registries keyed only by dataRef also collide across multiple views of the same source.
6. **GeoTIFF support is bounded and version-specific.** Local authored single-map specs and explicitly typed ordinary-input references work through browser-only GeoTIFF routing; vector/backend/cache/fallback paths remain separate. Inputs are validated dict/list/outputs references, not arbitrary TIFF paths or Python generic raster arrays. GeoTIFF data-only outputs, multiple maps, raster cross-source joins and raster GPU compute are not supported by the local host contract. Raster pixels must not be expanded into GeoJSON cell geometries.
7. **Raster size caps do not bound total memory.** The selected native loader defaults to **1,000,000 cells** and **bilinear** downsampling, then stores all decoded bands as Float32 arrays. It first fetches the whole TIFF with `response.arrayBuffer()` and `readRasters` can decode full intermediates; the cap does not limit compressed download size, all bands, decoder buffers, or GPU copies. RGB packing has a separate 1,000,000-pixel guard and produces RGBA bytes, while native map processing also creates Float32 RGBA storage. No maximum-value scaling/normalization is inferred. Source CRS changes transform four extent corners; this is not pixel reprojection/warping.
8. **NoData has a native defect beyond the documented common-sentinel limitation.** The loader's `Number(image.getGDALNoData())` converts a missing tag (`null`) to **0**, then masks legitimate zero samples. Installed geotiff returns null for absent tags. The helper probe confirms the conversion; both selected 3.x and installed 4.0.0 embedded DB source contain it. The real 128×128 fixture explicitly declares NoData **256**, so it does not exercise the absent-tag case. Finite shared sentinels, per-band masks and source alpha remain separate policy limitations. Nonfinite RGB channels correctly make the whole pixel transparent.
9. **Heatmap support exists in the grammar adapter but is lost in Curio.** Direct `createDataAdapter` calls `db.buildHeatmap`. Curio's backend compiler and in-browser fallback skip heatmap, requestedLayerTables omits it, and export uses vector-only getLayersMetadata. This needs a raster output/routing contract, not another renderer. Plain non-geometric CSV/JSON tables are also lost in vector-only materialization.
10. **Compute supports custom WGSL, not native render analytics.** The GPGPU parameters, attributes/arrays/matrices and constants are forwarded; fromFeature/all/batched is composition on top. Native `renderPipeline` scene visibility/classes/object analysis and viewpoint/camera sampling are missing from grammar. Local grammar retains the 2000-feature batch cap, although vendored native compute has storage-array changes; grammar 4.0.0 introduces storage-aware capacity. Computed FCs reside in a cache: maps and later compute use it, but plots read their separate GeoJSON cache/DB, and DB operations do not automatically see computed columns. This is an adapter data-authority gap.
11. **Runtime updates and disposal are incomplete.** Native AutkMap can update render/thematic/raster values, remove/reload layers and destroy resources; AutkPlot can updateCollection/redraw. Grammar supports selection helpers but no public geometry/style/data patch or destroy. Curio recreates canvas/grammar and cleans its listeners; that is not proof that native animation loops/devices are destroyed. Save network should remain corrected GeoJSON plus a versioned edit/provenance envelope followed by a rerun. There is no supported live geometry patch to promise.
12. **Camera and plot configuration gaps are smaller than renderer changes.** Native Camera pose/orthographic reset and map reset are accessible, but grammar exposes no initial pose/fit policy. Scene-origin initialization is not equivalent to fitting all layers. Plots cover all six native types and transforms, but axes/legend labels, tickFormats, palette/domain options are partial. Native APIs do not expose a general axis scale-type selector; such a selector cannot be obtained by simple forwarding.

## Coverage summary

One primary status per grouped capability. Counts include selected 3.x/local, explicitly separate 4.x deltas, umbrella and unresolved runtime proof; they are not percentages of methods.

| Coverage status | Rows |
|---|---:|
| Fully exposed | 12 |
| Partially exposed | 28 |
| Available through documented or demonstrated composition | 4 |
| Available in the grammar/adapter but limited by Curio | 2 |
| Missing from the grammar specification/schema | 16 |
| Not applicable to declarative specifications | 8 |
| Declared by the grammar but missing or incomplete in the Autark adapter | 2 |
| Unresolved because evidence is insufficient | 1 |

The matrix includes exact symbols/options, primary status, Curio limitations, source versions, absolute evidence paths/lines, probe commands/results, confidence, responsible layer, architectural assessment, urban analytics/Sidewalk value, scope and compatibility concerns. “Not applicable” rows justify why helper math, namespace wrapping, metadata/resource mechanics or raw GPU operations should remain runtime APIs; absence of a field is not evidence that every omission was intentional.

## Fresh verification performed

Existing Homebrew runtime only: Node `v26.10.0`, npm `11.19.1`, resolved executable `/opt/homebrew/Cellar/node/26.10.0_2/bin/node`. No installs, builds, schema regeneration, formatter, browser mutation or server configuration.

Commands and results:

- `/opt/homebrew/bin/node` plus `inventory.cjs`: root exports, constructors, static/inherited members and signatures for both installed snapshots. Bundler resolution is used for the packages' extensionless declarations. Standard-library members are excluded.
- `/opt/homebrew/bin/node` plus `probes.cjs`: installed schema validation; exact adapter source parameter traces with isolated doubles; RGB packing; NoData helper; Curio partition/URL/compiler helpers; compute parameters; shared-map event forwarding; fixed-color validation; normalization/ignored map fields. Results in `probe-results.json`. These are executed logic/forwarding probes, **not native GPU/DB end-to-end rendering tests**.
- `/opt/homebrew/bin/node` plus `artifact-probe.mjs`: directly imported installed ESM AutkGrammar/Core and installed geotiff reader; reproduced wrong map layer ID, verified native cyan RGB bytes/alpha and read actual fixture dimensions and NoData=256. Results in `artifact-probe-results.json`. No WebGPU/DB initialization.
- `python3 preservation.py`: complete pre/post worktree file hashes/status/refs/remotes and installed package hashes. Results below. Source-map/source equality in `grammar-artifact-source-match.json`.

Existing source tests were inspected as coverage intent, **not run**: GeoTIFF routing/input/cache/failure/scalar cases, null-geometry identity, selection origin, plot sizing/fit, compute scopes, input handling, and E2E RGB/vector input/redraw/edit tests. Their earlier pass results are not evidence for a new source snapshot or 4.x migration.

## Use immediately

- Current local RGB reference + vector network overlay, explicit local order, fixed hex vector color, initial isSkip/opacity and native floating UI controls.
- Existing vector CSV/JSON/GeoJSON/PBF loading with explicit CRS, spatial join/aggregation followed by map thematic or plot transform configuration.
- GPGPU feature metrics, array/matrix/uniform mappings, fromFeature composition within current capacity, and Curio upstream compute outputs.
- Native plot marks/transforms/brush-to-Data-Pool composition and rerun after editor Save network. Preserve row/source provenance and use one unambiguous picked layer until identity routing is repaired.

These are availability conclusions from inspected current local artifacts, not a claim of fresh manual/browser verification.

## Recommended candidate PRs

Keep a small sequence, each owning a concrete behavior:

1. **Autark DB: preserve zero samples when NoData is absent.** Small native loader fix plus fixtures for absent, zero, finite nonzero and nonfinite sentinels; test scalar and RGB. No new grammar field is needed. Reproduce on both release targets before backporting.
2. **Grammar/Curio: preserve actual interaction layer identity.** Small grammar forwarding fix, Curio routing follow-up using emitted IDs and load-order maps. Tests: multiple pick-enabled layers, null geometry, additive toggle and linked brush. Keep payload backward compatibility; separate view-ID redesign if it grows.
3. **Grammar: expose vector load options and apply domain config independently.** Small types/schema/adapter PR for polylinesWidth/buildingsZeroHeight and existing normalization behavior. Validate width units and defaults, confirm geometry rebuild on rerun, test over RGB imagery. Add diagnostics for unsupported map fields rather than accepting them silently.
4. **Grammar/Curio: versioned extension migration.** Choose a concrete 4.x source baseline, port already-approved RGB/order/color behavior deliberately, reconcile Curio filtered layerRefs with order, then synchronize authored/agent capability schema in a separate reviewable integration change. Keep runtime artifact fingerprints and existing vector/scalar paths explicit. This is a port, not a rewrite.

Documentation-only follow-ups: native preset IDs, byte color/opacity contract, ordering vs runtime z-order, raster memory/NoData/extent-only reprojection, join result paths, transform source provenance and editor rerun output contract.

Small extensions after priorities above: raster maxRasterCells/resampleMethod with validation; plot labels/tickFormats/palettes/domains; initial camera pose or deterministic fit policy. Reuse present adapters.

Curio-specific gaps: heatmap/plain-table materialization; multi-view targets; agent schema parity; filtered layerOrder; render-vs-compute output contracts. Raster output work needs a generic reference contract before broad enablement.

Larger design: scene-render compute specification, durable raster operations/cross-source analysis, coherent computed-table authority, stable IDs across multiple views/geometry replacement, idempotent lifecycle/disposal, optional runtime patches. Keep renderer passes, GPU handles, shader bind groups, math utilities and namespace wrappers outside JSON specs.

## Verification recommended before any implementation is committed

For each PR, use its own source/artifact versions. Focused schema/forwarding tests must prove accepted fields affect native parameters. Native DB tests should prove NoData, bands, resampling, size/error behavior and CRS extents. Browser GPU checks should cover one/multiple selectable layers, RGB/scalar overlays, ordering after filtering, widths, plot computed columns, camera initial framing, actual interaction IDs, failed loads, reruns and resource disposal. Retain vector/PBF, null-geometry, plot brush and editor Save network/output-envelope regressions. Repeated GPU draw/dispose memory measurements require a separately authorized isolated test environment; current running servers were not touched.

Unresolved: exact combined vendored native source commit; exact 4.0.0 release/umbrella source SHA; reproducible TS-to-bundle rebuild equivalence; WebGPU/DB end-to-end execution and device/resource leak severity; rotated/nonlinear raster georeferencing; advanced mixed geometry and every transform parameter combination. The inventoried exported surface is broader than the executed probes.

## Environment preservation

Compared **16,214 tracked/nonignored untracked files across 8 roots** and **2,799 installed-package files across 63 directories**. No file hashes changed. HEAD, branches, worktree status, manifests/lockfiles and remotes are unchanged; all pre-existing dirty/untracked files remain. All branch/tag/remote-tracking refs remain unchanged. No staging/commit/push/publish/install/build/server stop or package replacement occurred.

The shared Curio Git repository's internal `refs/codex/turn-diffs/...` capture/checkpoint references changed during the session, while keeping the same target commit. The audit issued no reference-writing Git command. These application metadata changes are recorded explicitly in `reference-differences.json`; complete all-ref equality is therefore **false**, rather than incorrectly reported as unchanged. No attempt was made to restore or modify them.

Initial/final Git state and file hash artifacts retain the complete evidence. Outputs and downloaded upstream sources are confined to this audit directory; no temporary artifact was put inside a protected checkout.

## Capability index

The CSV is the detailed comparison; the table below is a readable index.

| ID | Capability | Primary status | Snapshot |
|---|---|---|---|
| C001 | OSM named-area/PBF and semantic extraction | Fully exposed | live3 |
| C002 | OSM refresh/progress and ignored drop flag | Partially exposed | live3 |
| C003 | CSV and JSON URL/inline geometry loading | Fully exposed | live3 |
| C004 | Plain tabular data, row export and metadata | Partially exposed | live3 |
| C005 | GeoJSON CRS and bounding-box loading | Partially exposed | live3 |
| C006 | Spatial join and per-root aggregation | Fully exposed | live3 |
| C007 | Join results and thematic plotting composition | Available through documented or demonstrated composition | live3 |
| C008 | Heatmap construction and scalar rendering | Available in the grammar/adapter but limited by Curio | live3 |
| C009 | Arbitrary SQL, filtering and relational queries | Missing from the grammar specification/schema | live3 |
| C010 | Persistent keyed/replace updates | Missing from the grammar specification/schema | live3 |
| C011 | Workspace lifecycle and coordinate configuration | Partially exposed | live3 |
| C012 | Metadata, bounds, type guards and layer removal | Not applicable to declarative specifications | live3 |
| C013 | GeoTIFF URL/reference loading | Partially exposed | live3 |
| C014 | Raster downsampling and peak memory | Missing from the grammar specification/schema | live3 |
| C015 | Raster extent, source CRS and orientation | Partially exposed | live3 |
| C016 | NoData handling and absent-tag defect | Partially exposed | live3 |
| C017 | RGB byte raster rendering | Fully exposed | live3 |
| C018 | Scalar band selection and color ramp | Partially exposed | live3 |
| C019 | Scalar opacity transfer functions | Missing from the grammar specification/schema | live3 |
| C020 | Raster downstream export and cross-source computation | Partially exposed | live3 |
| C021 | Vector families and semantic layers | Partially exposed | live3 |
| C022 | Map style presets | Fully exposed | live3 |
| C023 | Custom map style, highlight and invalid-value color | Missing from the grammar specification/schema | live3 |
| C024 | Fixed vector layer color | Fully exposed | live3 |
| C025 | Polyline/road mesh width and zero-height buildings | Missing from the grammar specification/schema | live3 |
| C026 | Point size, borders and stroke variations | Partially exposed | live3 |
| C027 | Static visibility and opacity | Fully exposed | live3 |
| C028 | Runtime visibility/color/thematic/raster patches | Partially exposed | live3 |
| C029 | Default and explicit layer ordering | Partially exposed | live3 |
| C030 | Thematic value paths, continuous/category palettes | Partially exposed | live3 |
| C031 | Normalization/domain parameters and catch-all composition | Partially exposed | live3 |
| C032 | Legend labels, initial picked components and default thematic value | Declared by the grammar but missing or incomplete in the Autark adapter | live3 |
| C033 | Camera initialization and framing | Missing from the grammar specification/schema | live3 |
| C034 | Interactive camera navigation and animation | Partially exposed | live3 |
| C035 | Terrain heightfield mode | Missing from the grammar specification/schema | live3 |
| C036 | Picking, highlighting and row identity | Partially exposed | live3 |
| C037 | Per-feature hide/filter and initial picked IDs | Partially exposed | live3 |
| C038 | Updating geometry on an existing map | Available through documented or demonstrated composition | live3 |
| C039 | Mesh inputs and advanced triangulation | Missing from the grammar specification/schema | live3 |
| C040 | UI, render loop and GPU lifecycle | Partially exposed | live3 |
| C041 | All six plot types and aliases | Fully exposed | live3 |
| C042 | Axis/color encoding and basic layout | Partially exposed | live3 |
| C043 | Plot tick formatting, palettes and color domains | Missing from the grammar specification/schema | live3 |
| C044 | Transforms, binning, reduction and source provenance | Partially exposed | live3 |
| C045 | Brushing/click and linked map selections | Partially exposed | live3 |
| C046 | Data replacement and plot redraw | Missing from the grammar specification/schema | live3 |
| C047 | Brushing-to-filter workflow composition | Available through documented or demonstrated composition | live3 |
| C048 | Plot destruction and low-level style/render hooks | Partially exposed | live3 |
| C049 | Custom WGSL per-feature arithmetic | Fully exposed | live3 |
| C050 | Array/matrix attributes and shared uniform constants | Fully exposed | live3 |
| C051 | Cross-table fromFeature and batched/all dispatch composition | Available through documented or demonstrated composition | live3 |
| C052 | Compute result persistence and chaining across stages | Partially exposed | live3 |
| C053 | Visibility/classes/per-object render analytics | Missing from the grammar specification/schema | live3 |
| C054 | Viewpoint generation and matrix helpers | Not applicable to declarative specifications | live3 |
| C055 | GPU pipelines/buffers and device lifecycle | Not applicable to declarative specifications | live3 |
| C056 | Color conversion/domain/texture helper surfaces | Not applicable to declarative specifications | live3 |
| C057 | Geometry utilities and building/window triangulators | Not applicable to declarative specifications | live3 |
| C058 | Shared selection bus and listener lifecycle | Partially exposed | live3 |
| C059 | Validation, layer enums, geometry/data helpers | Not applicable to declarative specifications | live3 |
| C060 | Schema validation versus executable support | Partially exposed | live3 |
| C061 | Multiple maps/plots and view identities | Available in the grammar/adapter but limited by Curio | live3 |
| C062 | Engine updatedSpec/destroy interface stubs | Declared by the grammar but missing or incomplete in the Autark adapter | live3 |
| C063 | Data-only, browser render and output contracts | Partially exposed | live3 |
| C064 | Adapter interface breadth and DeckGL separation | Fully exposed | live3 |
| C065 | 4.0.0 named/bbox OSM areas and tag-selected geometry | Missing from the grammar specification/schema | main4 |
| C066 | 4.0.0 workspace precision and CRS configuration | Missing from the grammar specification/schema | main4 |
| C067 | 4.0.0 per-OSM-element layer export identity | Missing from the grammar specification/schema | main4 |
| C068 | 4.x on-demand rendering and border option | Partially exposed | main4 |
| C069 | 4.0.0 storage-based batched feature capacity | Fully exposed | main4 |
| C070 | 4.0.0 grammar RGB/order/fixed color omission | Missing from the grammar specification/schema | main4 |
| C071 | 4.0.0 building normalization and window identity | Not applicable to declarative specifications | main4 |
| C072 | Umbrella namespaces/subpath exports | Not applicable to declarative specifications | live3 |
| C073 | GPU rendering, cleanup and complex CRS runtime proof | Unresolved because evidence is insufficient | live3 |


## Publication note — October 19, 2026

This is the historical October 9 audit, not verification of the Phase 1 PR. Private checkout prefixes were replaced with logical labels; dates, examined versions, capability IDs, findings and limitations are retained. Supporting local artifact filenames are provenance references, not repository attachments. See [the current map-selection investigation](map-selection-investigation.md) for current failures and [the implementation manifest](../../packages/curio.sidewalk-stewards@1/IMPLEMENTATION.md) for shipped scope. Broader audit findings are follow-up backlog; Phase 2 does not require implementing every finding.
