# Sidewalk review workflow: portable Phase 1 export

Import [28-sidewalk-review-workflow.json](28-sidewalk-review-workflow.json). It exports the current review's eight nodes and twelve connections: two Data Loading sources → Sidewalk Prepare → Before/PCP/editor; editor → After and mutual editor/Panorama/overview interactions. Node IDs, titles, positions/dimensions, handles, Before/After layer settings and PCP configuration are preserved. It uses `curio.sidewalk-stewards@1` and `curio.streetvision@1`; the legacy Street View Context node is absent.

This PR delivers Phase 1 of the Sidewalk Stewards integration: the current tile-editing and Street View inspection nodes. Shared Curio/Autark interaction prerequisites and prediction-node integration remain follow-up work.

## Portable adaptations

The running review used the full Recife dataset. This example uses the repository's [CC0 six-tile synthetic fixture](data/sidewalk-synthetic/README.md): schematic PNGs/GeoTIFF, six-cell grid, three sparse measurement rows and two original lines. Input loader code, Prepare measurement URL, editor templates and resource-dependent goal text were changed accordingly. Private per-tile corrections, draft/history, active selection, runtime outputs and resource bindings were cleared. Only required package locks are included. Credentials and private provenance are omitted. No Recife data is needed.

The Before map's **visible** grammar had the network at opacity `0.9` and the `upstream` full grid at `0.14`, `isPick:true`, `selectFields:["tile_id"]`. Its **saved** code was `{}`. This export uses the visible intended grammar; PCP and After matched saved data. That discrepancy was recorded without saving or changing the running installation. It is separate from selection-event compatibility and does not establish save/reopen reliability.

PCP retains `sidewalk_typology`, `brushY`, all eight axes and `mapRef:"upstream"`. It intentionally contains fewer rows than the complete grid. It has not been redirected to a different table to bypass cross-layer routing. Before remains selectable.

## Run and review

1. Start a clean checkout with examples enabled. Install/discover the renamed Sidewalk and Street Vision packages. Import the JSON through Curio's workflow import. All declared resources are repository-relative and included; the Python source loaders use only the standard library. Rebuild synthetic assets only if needed with `python scripts/build_example_sidewalk_inspection.py` (Pillow/rasterio are builder requirements, not new runtime package dependencies).
2. Run **Satellite imagery source**, **Original sidewalk network**, then **Sidewalk Prepare**. It should publish a complete six-cell grid, original network and three measured PCP rows. Run/render Before and PCP as needed.
3. **Known limitation:** automatic map-to-editor opening does not work on current upstream for keyed or positional selections. The legacy positional chooser may permit explicit selection; keyed events currently yield no candidates. Do not interpret this as successful automatic selection. Once an active tile is available, cardinal arrows support navigation; edit tools and tile drafts/history are implemented and fixture-tested.

   **Open review follow-up:** this keyed example does not yet provide a verified, reproducible clean-import procedure to activate the first editing tile. Arrows require an active tile and cannot establish it. Steps 4–5 are conditional on activation; the import/Run all evidence does not prove those steps work end-to-end. See the [first-tile follow-up](../sidewalk/phase1-review-followups.md#3-reproducible-first-tile-activation-in-the-portable-example).
4. Draw/move/delete, Undo/Redo and return A → B → A to inspect per-tile state. Save network emits cumulative corrections to After; Before remains original. Workflow Save serializes node state separately. Untouched geometry preservation is covered by package tests. Full browser save/reopen is unverified.
5. Inspect Street View on an active tile without a key to see a gray requested marker and inline notices. Configure a browser-restricted Maps JavaScript API key in **Panorama Settings** if deliberately testing live service access. A confirmed actual camera event produces red; failures do not. Camera movement does not change the editing tile. Outside labels and **Open camera tile** use the actual camera context. Synthetic coordinates near the equator are intended for fixture checks, not useful live panoramas. No live lookup is required for importing this example.

The Fetcher is available in Street Vision but is not an extra node in this exported review graph. It uses its own Static API credential; proxy image links expire after two hours, eviction or backend restart. All credentials are session-only and must be re-entered after reload.

## Compatibility and further work

The two automatic-opening acceptance gates remain failing because upstream reports a post-toggle selection set without the actual clicked feature. Independent sparse PCP routing and overview synchronization need Phase 2 verification. No prototype adapter or native library changes are included. See the [implementation manifest](../../packages/curio.sidewalk-stewards@1/IMPLEMENTATION.md), [current investigation](../sidewalk/map-selection-investigation.md), [complete capability table](../sidewalk/consolidated-capability-table.md) and [fresh checks](../sidewalk/phase1-verification.md).
