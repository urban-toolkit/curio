// A compute-only Autark node's `compute` section, applied to the layers it
// receives. Used by the node behavior (autkGrammarBehavior.tsx).

import type { FeatureCollection } from 'geojson';
import { runComputeChecked } from './autkComputeScopes';

// Apply a grammar `compute` section to an array of named GeoJSON layers,
// returning a new array where each block's target layer has been replaced by a
// FeatureCollection enriched with the WGSL output under `feature.properties.compute.<col>`.
// This is what makes a compute-only autk-grammar node useful: the grammar engine
// only runs compute when it's part of a render pipeline (map/plot), so without
// this helper, a node whose spec contains *only* a `compute` block would pass
// upstream through unchanged.
//
// autk-grammar's `runCompute` does the work the grammar defines: `fromFeature`
// directives, the `all` and `batched` iterations, and the packing of batched
// features. Curio hands it the dispatch, which checks the GPU accepted the pass.
//
// A block whose `dataRef` doesn't match any upstream layer is skipped quietly:
// chained compute nodes can target different layers, and a no-op block is far
// less surprising than aborting the whole pipeline.
export async function applyComputeBlocks(
    layers: Array<{ name: string; type: string; geojson: FeatureCollection }>,
    computeBlocks: any[],
    /** Appended to for every block that failed, so the caller can refuse to
     *  report success. A block whose ``dataRef`` matches no upstream layer is
     *  still skipped quietly - that is a no-op, not a failure. */
    failures: string[] = [],
): Promise<Array<{ name: string; type: string; geojson: FeatureCollection }>> {
    if (!Array.isArray(computeBlocks) || computeBlocks.length === 0) return layers;
    const [{ ComputeGpgpu }, { runCompute }] = await Promise.all([
        import('@urban-toolkit/autk-compute'),
        import('@urban-toolkit/autk-grammar'),
    ]);
    let result = layers;
    for (const block of computeBlocks) {
        if (!block || !block.dataRef || !block.wglsFunction) continue;
        const idx = result.findIndex((l) => l.name === block.dataRef);
        if (idx < 0) continue;
        const outCols: string[] = block.outputColumns ?? (block.outputColumnName ? [block.outputColumnName] : []);
        try {
            const gpgpu = new ComputeGpgpu();
            const tables = new Map(result.map((l) => [l.name, l.geojson]));
            const augmented = await runCompute(block, tables, (params) => runComputeChecked(gpgpu, params));
            // ComputeGpgpu writes outputs under properties.compute.<col>. Also lift them
            // to top-level properties so downstream nodes can reference the column by
            // its bare name (e.g. `height_m`) without worrying about whether the nested
            // `compute` object round-trips through AutkDb's DuckDB storage. Both
            // `compute.<col>` and `<col>` dot-paths then resolve.
            if (outCols.length > 0 && augmented?.features) {
                for (const f of augmented.features) {
                    const p: any = f?.properties;
                    const c = p?.compute;
                    if (!p || !c) continue;
                    for (const col of outCols) {
                        if (col in c && !(col in p)) p[col] = c[col];
                    }
                }
            }
            // Re-attach the source crs hint so downstream re-loads keep coords aligned.
            const sourceCrs = (result[idx].geojson as any)?.crs;
            if (sourceCrs && augmented) (augmented as any).crs = sourceCrs;
            result = result.map((l, i) => (i === idx ? { ...l, geojson: augmented } : l));
        } catch (e) {
            // Recorded, not just warned (#201). A failed block leaves the layer
            // exactly as it arrived, so swallowing this emitted UNCOMPUTED data
            // under a green "Done" badge - the node reported success for work
            // it had not done. The caller turns a non-empty list into an error.
            console.warn(`[autk-grammar] compute block on '${block.dataRef}' failed`, e);
            failures.push(
                `${block.dataRef}: ${(e as Error)?.message ?? "compute failed"}`,
            );
        }
    }
    return result;
}
