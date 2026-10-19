# Sidewalk tile editing

This package provides **Sidewalk Prepare** and **Sidewalk Tile Edit**. Use **Street View Panorama** from the Street Vision package for inspection; the legacy Street View Context node is no longer included.

Sidewalk Prepare validates separate image-reference and original-network inputs and publishes their complete grid/network context. Sidewalk Tile Edit supports drawing, node movement, deletion, splitting, undo/redo, cardinal navigation and per-tile drafts. Save network applies cumulative corrections to After; Before retains the original source. Workflow Save persists the node configuration, drafts/history and saved corrections. Reload requires the referenced resources to remain available.

Street View requests are separate from confirmed camera positions. A pending request uses the original pointer in gray; confirmed camera feedback uses red. Camera movement never chooses a new editing tile. Outside-tile feedback and Open camera tile remain explicit.

This PR delivers Phase 1 of the Sidewalk Stewards integration: the current tile-editing and Street View inspection nodes. Shared Curio/Autark interaction prerequisites and prediction-node integration remain follow-up work.

See the [implementation manifest](IMPLEMENTATION.md) for contracts, migration, ownership, verification and the three-phase roadmap, and the [portable review workflow](../../docs/examples/28-sidewalk-review-workflow.md) for usage.

## Known upstream compatibility failures

Automatic Autark map handoff requires a confirmed active map pick distinct from analytical candidates. The prototype supplies selectionOrigin metadata through a Curio adapter modification. Upstream main emits only an aggregated row/key selection, without that metadata or the actual feature hit. This draft intentionally does not port the adapter changes or guess a click from selection-set differences. Its legacy chooser is insufficient for automatic map selection; keyed selections currently yield no chooser candidates. Two acceptance gates remain failing. This is a Phase 1 draft for review, not a claim of full upstream interaction compatibility.

Map highlighting through existing keyed selections is supported by upstream, but sparse measured PCP rows need an explicit mapping to the full grid. Routing through plot.mapRef in the prototype is deferred with the adapter work.

Prepared inputs must declare accessible image/network resources. The synthetic fixture is schematic and CC0, not aerial imagery. Source correspondence with Sidewalk Stewards does not establish complete editing parity.
