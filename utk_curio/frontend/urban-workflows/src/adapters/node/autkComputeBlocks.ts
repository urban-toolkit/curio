// A compute step's `compute` section, applied to the layers it holds. Used by
// the node behavior (autkGrammarBehavior.tsx).

import type { FeatureCollection } from 'geojson';
import { autkKeyProblem } from '../../contracts/autkGrammar';
import { autkWorkspaceOf } from './autkDataCompile';
import { runComputeChecked } from './autkComputeScopes';

/** A layer a compute step holds, in the workspace it names when it is not the default one. */
type Layer = { name: string; type: string; geojson: FeatureCollection; workspace?: string };

// Apply a grammar `compute` section to an array of named GeoJSON layers,
// returning a new array where each pass's result, a FeatureCollection enriched
// with the WGSL output under `feature.properties.compute.<col>`, is written
// where autk-grammar's compute adapter writes it (`writtenLayers`): a pass
// with an `outputTableName` writes a new table and leaves the one it computed
// over as it was, and any other pass writes into that one. This is what makes
// a compute step useful: the grammar engine only runs compute when it's part
// of a render pipeline (map/plot), so without this helper, a node whose spec
// computes and draws nothing would pass its layers through unchanged.
//
// autk-grammar's `runCompute` does the work the grammar defines: `fromFeature`
// directives, the `all` and `batched` iterations, and the packing of batched
// features. Curio hands it the dispatch, which checks the GPU accepted the pass.
//
// A block whose `dataRef` matches no layer of its workspace is skipped quietly:
// chained compute nodes can target different layers, and a no-op block is far
// less surprising than aborting the whole pipeline. A section that writes a key
// autk-grammar 5 renamed, or one a node does not run yet (contracts/autkGrammar),
// runs no block and is a failure, named.
export async function applyComputeBlocks(
    layers: Layer[],
    computeBlocks: any[],
    /** Appended to for every block that failed, so the caller can refuse to
     *  report success. A block whose ``dataRef`` matches no upstream layer is
     *  still skipped quietly - that is a no-op, not a failure. */
    failures: string[] = [],
): Promise<Layer[]> {
    if (!Array.isArray(computeBlocks) || computeBlocks.length === 0) return layers;
    const keyProblem = autkKeyProblem({ compute: computeBlocks });
    if (keyProblem) {
        failures.push(keyProblem);
        return layers;
    }
    const [{ ComputeGpgpu }, { runCompute }] = await Promise.all([
        import('@urban-toolkit/autk-compute'),
        import('@urban-toolkit/autk-grammar'),
    ]);
    let result = layers;
    for (const block of computeBlocks) {
        if (!block || !block.dataRef || !block.wgslFunction) continue;
        // A pass reads the tables of its own workspace, as autk-grammar's
        // compute adapter reads them.
        const workspace = autkWorkspaceOf(block);
        const inWorkspace = result.filter((l) => autkWorkspaceOf(l) === workspace);
        const idx = result.findIndex((l) => l.name === block.dataRef && autkWorkspaceOf(l) === workspace);
        if (idx < 0) continue;
        const outCols: string[] = block.outputColumns ?? (block.outputColumnName ? [block.outputColumnName] : []);
        try {
            const gpgpu = new ComputeGpgpu();
            const tables = new Map(inWorkspace.map((l) => [l.name, l.geojson]));
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
            result = writtenLayers(result, result[idx], block, augmented);
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

/**
 * *layers* with a pass's result written where autk-grammar's compute adapter
 * keeps it (`store` in its adapters/compute.ts): under the pass's
 * `outputTableName`, else in place of *source*, the table it computed over. A
 * table the pass names is drawn and handed on as its `layerType` says, else as
 * *source* is; one written in place keeps its type, since the grammar reads
 * `layerType` only with `outputTableName`. A name none of *layers* has is a
 * new table, after them, which later passes read; a name one of them has
 * replaces that table, as the grammar's result shadows a table of its name.
 * The table is in the pass's workspace, where the grammar keeps it (by
 * `tableKey`), so only a table of that workspace and name is replaced.
 */
function writtenLayers(layers: Layer[], source: Layer, block: any, result: FeatureCollection): Layer[] {
    const named = typeof block.outputTableName === 'string' && block.outputTableName !== '';
    const name = named ? block.outputTableName : source.name;
    const type = named && typeof block.layerType === 'string' && block.layerType ? block.layerType : source.type;
    const workspace = autkWorkspaceOf(block);
    const table: Layer = { name, type, geojson: result, ...(workspace ? { workspace } : {}) };
    const at = layers.findIndex((l) => l.name === name && autkWorkspaceOf(l) === workspace);
    return at < 0 ? [...layers, table] : layers.map((l, i) => (i === at ? table : l));
}
