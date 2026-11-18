// A compute step's `compute` section, applied to the layers it holds. Used by
// the node behavior (autkGrammarBehavior.tsx).

import type { FeatureCollection } from 'geojson';
import { autkKeyProblem } from '../../contracts/autkGrammar';
import { checkedPasses } from './autkComputeScopes';

type Layer = { name: string; type: string; geojson: FeatureCollection };

// Apply a grammar `compute` section to an array of named GeoJSON layers,
// returning the layers as its passes leave them: each pass's result, a
// FeatureCollection with what the pass computed under
// `feature.properties.compute`, is written where autk-grammar writes it. This
// is what makes a compute step useful: the grammar engine only runs compute
// when it's part of a render pipeline (map/plot), so without this helper, a
// node whose spec computes and draws nothing would pass its layers through
// unchanged.
//
// Each pass runs as the grammar's own run runs it: through autk-grammar's
// compute adapter (`createComputeAdapter`), a GPGPU pass and a render pass
// alike, over its caches seeded with the layers by `tableKey`. The adapter
// keeps a pass's result under its `outputTableName`, leaving the table it
// computed over as it was, and else in place of that table; a table a pass
// names has the pass's `layerType`, else that table's type, or `points` for a
// render pass's building windows (`store` in its adapters/compute.ts). The
// layers come back in the order the cache holds them: those the step held, as
// the passes left them, then each table a pass wrote under a new name. Every
// pass is checked on the GPU's device (`checkedPasses`).
//
// A pass whose own table (a GPGPU pass's `dataRef`, a render pass's
// viewpoints) matches no layer is skipped quietly: chained compute nodes can
// target different layers, and a no-op pass is far less surprising than
// aborting the whole pipeline. A section that writes a key autk-grammar 5
// renamed, or one a node does not run yet (contracts/autkGrammar), runs no
// pass and is a failure, named.
export async function applyComputeBlocks(
    layers: Layer[],
    computeBlocks: any[],
    /** Appended to for every pass that failed, named by the table it writes,
     *  so the caller can refuse to report success. A pass whose table matches
     *  no layer is still skipped quietly - that is a no-op, not a failure. */
    failures: string[] = [],
): Promise<Layer[]> {
    if (!Array.isArray(computeBlocks) || computeBlocks.length === 0) return layers;
    const keyProblem = autkKeyProblem({ compute: computeBlocks });
    if (keyProblem) {
        failures.push(keyProblem);
        return layers;
    }
    const { createComputeAdapter, tableKey } = await import('@urban-toolkit/autk-grammar');
    // The grammar's caches, as its own run keeps them: each table by tableKey.
    const cache = new Map<string, FeatureCollection>();
    const types = new Map<string, any>();
    const names = new Map<string, string>();
    for (const layer of layers) {
        const key = tableKey(undefined, layer.name);
        cache.set(key, layer.geojson);
        types.set(key, layer.type);
        names.set(key, layer.name);
    }
    const adapter = checkedPasses(createComputeAdapter(cache, types));
    const db = heldTables(types);
    for (const pass of computeBlocks) {
        const render = pass?.type === 'render';
        const source = render ? pass?.viewpoints?.dataRef : pass?.dataRef;
        if (!pass || !source || (!render && !pass.wgslFunction)) continue;
        if (!cache.has(tableKey(pass.workspace, source))) continue;
        const sourceCrs = (cache.get(tableKey(pass.workspace, source)) as any)?.crs;
        const name = typeof pass.outputTableName === 'string' && pass.outputTableName ? pass.outputTableName : source;
        const key = tableKey(pass.workspace, name);
        const before = { table: cache.get(key), type: types.get(key) };
        try {
            await adapter.resolveCompute(db, pass);
        } catch (e) {
            // A failed pass leaves the layers as they were: one the GPU
            // refused has stored what it read back. And it is recorded, not
            // just warned (#201): the caller turns a non-empty list into an
            // error, so the node never hands on, under a green "Done", layers
            // a pass did not compute.
            if (before.table === undefined) cache.delete(key);
            else cache.set(key, before.table);
            if (before.type === undefined) types.delete(key);
            else types.set(key, before.type);
            console.warn('[autk-grammar] compute pass failed', e);
            failures.push((e as Error)?.message ?? 'compute failed');
            continue;
        }
        names.set(key, name);
        const result: any = cache.get(key);
        if (!result) continue;
        // The pipelines write each GPGPU output under properties.compute.<col>.
        // Also lift them to top-level properties so downstream nodes, and later
        // passes, can reference the column by its bare name (e.g. `height_m`)
        // without worrying about whether the nested `compute` object
        // round-trips through AutkDb's DuckDB storage. Both `compute.<col>`
        // and `<col>` dot-paths then resolve.
        const outCols: string[] = render ? [] : (pass.outputColumns ?? (pass.outputColumnName ? [pass.outputColumnName] : []));
        if (outCols.length > 0 && Array.isArray(result.features)) {
            for (const f of result.features) {
                const p: any = f?.properties;
                const c = p?.compute;
                if (!p || !c) continue;
                for (const col of outCols) {
                    if (col in c && !(col in p)) p[col] = c[col];
                }
            }
        }
        // Re-attach the source crs hint so downstream re-loads keep coords
        // aligned: a render pass's windows are a new collection.
        if (sourceCrs && !result.crs) result.crs = sourceCrs;
    }
    return [...cache].map(([key, geojson]) => ({
        name: names.get(key) ?? key,
        type: types.get(key) ?? 'polygons',
        geojson,
    }));
}

/**
 * The database a compute step's passes read, as autk-grammar's compute
 * adapter reads one: the tables the step holds, of the types *types* gives,
 * in autk-db's default workspace. The adapter reads a table from its cache
 * first, which holds them all, so one it asks this database for is a table
 * the step does not hold, which fails its pass as autk-db fails a read of a
 * table it does not hold.
 */
function heldTables(types: Map<string, string>) {
    let workspace: string | undefined;
    return {
        getCurrentWorkspace: () => workspace,
        setWorkspace: async (name: string) => {
            workspace = name;
        },
        getTablesMetadata: () => [...types].map(([name, type]) => ({ name, type })),
        getLayer: async (name: string): Promise<FeatureCollection> => {
            throw new Error(`Table ${name} not found.`);
        },
    };
}
