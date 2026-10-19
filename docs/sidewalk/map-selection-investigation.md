# Map-selection compatibility investigation

## Conclusion

Both gates remain failing. The immediate cause is the editor requiring prototype-specific `selectionOrigin` / active-index metadata. Correcting the fixtures to use actual upstream adapter output does not resolve the failures. The general requirement is also blocked by genuine information loss: the published map event reports the resulting selection set, not the individual feature hit. A package-only adaptation cannot reliably recover that hit without the prohibited inference/tracking heuristics.

Only two test files changed during this investigation. No package runtime source, bundles, adapter, Autark code, specifications, connections, dependencies or running installation were changed. Nothing was staged, committed, pushed or published. The saved-grammar investigation remains separate.

## What the failed assertions now exercise

`editorSelectionHandoff.test.tsx:119–137` runs the actual, unchanged Curio adapter using the repository's existing renderer/service stubs. It asserts the emitted payload exactly and feeds that payload to the real Sidewalk behavior. The assertion still requires the second tile image to appear automatically. Both keyed and positional cases fail there, after the adapter-payload assertions pass.

The old hand-written fixture incorrectly used `source:"AUTK_GRAMMAR"`. Upstream's real value is `"curio.builtin/autk-grammar"`. The editor does not inspect that source field, so it was not the root cause. The revised fixture also uses the existing Flow envelope with sender `nodeId` and priority. `input_0` is the actual table name for this direct FeatureCollection fixture; a prepared named table can instead emit `upstream`.

The actual keyed callback, wrapped in Flow's existing envelope, is:

```json
{"nodeId":"before","priority":1,"details":{"autk_selection":{"type":"POINT","data":[{"tile_id":"second"}],"priority":1,"source":"curio.builtin/autk-grammar","layerRef":"input_0"}}}
```

The positional variant is identical except for `data:[1]`. A PCP brush over the same rows emits the same selection **details**; its sender remains `nodeId:"pcp"`, not `"before"`. Sender identity is therefore not lost, and separate one-view nodes can be distinguished when their identities/view kinds are known. The detail itself does not carry event kind. More importantly, even a known map sender still does not identify the individual hit within a post-toggle set.

Full keyed, positional, PCP and empty envelopes are recorded in [upstream-selection-payloads.json](upstream-selection-payloads.json).

## Why package-only recovery is ambiguous

The new `upstreamNativePicking.test.ts` executes the published autk-map picking coordinator with mocked GPU readback and highlighted-layer state. It also executes the published autk-grammar event forwarding with its database stubbed. Test-only internal coordinator access does not constitute a supported package API, and none is used in implementation code.

These distinct actions produce exactly the same native event:

| Highlighted IDs immediately before the action | Actual hit | Native emitted event |
|---|---:|---|
| `[0,1]` | `0` | `{"selection":[1],"layerId":"input_0"}` |
| `[1,2]` | `2` | `{"selection":[1],"layerId":"input_0"}` |

Programmatic/PCP highlighting can set either starting state without a new map-picking event reaching the editor. Both native events become the same Curio positional payload `data:[1]`, or keyed payload `data:[{"tile_id":"second"}]`, from the same Before node. Opening the remaining selected tile would open neither actual hit.

Repeated clicks also expose a collision:

| Highlighted IDs before action | Action | Native event |
|---|---|---|
| `[1]` | Hit `1` again, toggling it off | `{"selection":[],"layerId":"input_0"}` |
| `[1]` | Background miss | `{"selection":[],"layerId":"input_0"}` |

The first click from empty state emits `[1]`; the repeated hit emits `[]`. The events do not say whether the empty result came from a repeated hit or a miss. This establishes what is observable; it does not choose new editor semantics for deselection.

Single-row, multi-row and cleared PCP selections were exercised through the unchanged adapter, keyed and positional. They are converted to the same `POINT`/`UNDETERMINED` selection-set shapes as map picks. Repeated identical sets produce new detail objects but no event revision/sequence. No timing, ordering, first/last candidate or set-difference inference was added. No claim is made that out-of-order native GPU picks are rejected by this contract; existing draft/resource/camera safeguards were not modified.

## Exact source evidence

Paths below are relative to this repository:

- `packages/curio.sidewalk-stewards@1/sources/autkSelection.ts:26–34`: keyed objects are not positional indices; missing versioned origin becomes `legacy` with no active index.
- `packages/curio.sidewalk-stewards@1/sources/sidewalkTileEditBehavior.tsx:43–60`: automatic activation only follows a `map-pick`; legacy activation requires the explicit chooser.
- `utk_curio/frontend/urban-workflows/src/adapters/node/autkGrammarBehavior.tsx:769–796`: map and plot listeners convert rows/keys through the same emission function; no origin or individual hit is emitted.
- `utk_curio/frontend/urban-workflows/src/providers/flow/useInteractions.ts`: sender node ID and priority are retained through direct interaction edges.
- Installed `@urban-toolkit/autk-map` **4.1.1-curio.1**, `dist/autk-map.js:8383–8393`: raw readback hit `n` is available, used to toggle highlights, then omitted from the emitted `{selection,layerId}`.
- Installed `@urban-toolkit/autk-grammar` **4.4.0**, `dist/autk-grammar.js:677–699`: map forwarding destructures only `selection`. A diagnostic native event containing a hypothetical `pickedIndex` loses it at this boundary, verified by the published-grammar fixture.

## Smallest proposed generic prerequisite (not implemented)

In **urban-toolkit/curio**, extend the existing adapter's interaction payload additively, preserving `data`, sender identity, keys, layer and all existing selection/highlighting behavior:

1. Expose event origin (`map-pick` versus `plot-selection`) directly from the already distinct listeners. This alone requires no Autark library change.
2. For a map event, expose the **explicit native hit** separately from the post-toggle selection set, including an explicit miss/clear representation. Translate its source position with the existing map load order and expose key values through the existing `selectFields` machinery. Do not derive it with MapPickTracker or selection-set differences.

For example, a click on input row 0 that leaves row 1 highlighted could carry `trigger:{kind:"map-pick",hit:{rowIndex:0,keys:{tile_id:"first"}}}` while retaining `data:[{tile_id:"second"}]`. A plot brush would carry its origin without activating an editing tile. This is a generic feature-selection contract, not a Sidewalk-specific routing rule.

If claiming stale native-request rejection, capture/forward a view-generation and pick sequence at request issuance; a counter assigned only when async callbacks arrive cannot establish their original order. That guarantee is not proven or implemented here.

### Which separate repository change is actually necessary?

- **urban-toolkit/autark**, directory **autk-map**: the native event must expose the individual GPU-readback hit (or an equivalent explicit trigger identity) alongside its selection set. The native fixture demonstrates the current loss; the hit already exists locally, so the change can be additive at emission/type level. No new picking request is needed.
- **urban-toolkit/autk-grammar**: forwarding the new field would be the small, direct extension if Curio continues to use `grammar.interactions`. Current forwarding demonstrably drops it. However, a grammar-repository change is **not unconditionally required**: its supported `mapLayer()` / `maps` API exposes the map and its public events, so the generic Curio adapter could subscribe to the extended native event instead, with proper cleanup. That still needs the autk-map event extension. This distinction corrects any earlier implication that both standalone repositories necessarily require changes.
- The Curio adapter changes belong to **urban-toolkit/curio**, not either Autark repository. None of these prerequisites was implemented during this investigation. Cross-layer mapRef routing was not re-investigated or changed; it is outside these two acceptance gates.

## Fresh verification

- Focused handoff and native-picking suites: **9 passed, 2 failed**. The only failed assertions are the two automatic tile-opening gates, now fed by actual unchanged adapter output.
- Relevant existing upstream adapter/keyed-selection parity checks (`--testNamePattern='key|pick|brush'`): **10 passed, 10 other tests not selected**.
- `npm run typecheck`: passed.
- `git diff --check`: passed.
- All other 89 previously prepared files retain their start-of-investigation hashes except the one handoff test; the only new worktree file is the native-picking test. Adapter and dependency files remain byte-for-byte equal to upstream HEAD. No files are staged.

These are fixtures, including execution of the published native libraries, not physical browser/GPU clicks. Compatibility was not restored, so the conditional dedicated browser workflow step was not run. No provider calls were made. Draft/history persistence and save/reopen reliability were not newly validated or claimed.


## Publication updates — October 19, 2026

The Street Vision integrity entries mentioned in the private audit were subsequently regenerated and verified. The package namespace was subsequently renamed; versioned wire schema identifiers remain unchanged. The legacy Street View Context node was removed. The two automatic-opening acceptance gates remain required tests and known failures. See the implementation manifest for fresh Phase 1 checks. Saved-grammar reliability remains separately unverified.
