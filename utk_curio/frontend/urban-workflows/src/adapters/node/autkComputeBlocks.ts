// A compute step's `compute` section, applied to the layers it holds. Used by
// the node behavior (autkGrammarBehavior.tsx).

import type { FeatureCollection } from 'geojson';
import { autkKeyProblem } from '../../contracts/autkGrammar';
import { withDefaultHeights, withHeightsAsHeld } from '../../utils/autkInput';
import { autkWorkspaceOf } from './autkDataCompile';
import { checkedPasses } from './autkComputeScopes';

/** A layer a compute step holds, in the workspace it names when it is not the default one. */
type Layer = { name: string; type: string; geojson: FeatureCollection; workspace?: string };

/**
 * The CRS a compute step's database says it keeps its tables in: autk-db's
 * default, World Mercator. A pass compares it only with a data adapter's
 * cache, which a step does not hand its passes, so it reads every table from
 * its own cache as the step holds it.
 */
const HELD_TABLES_CRS = 'EPSG:3395';

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
// compute adapter (`createComputeAdapter`), a GPGPU pass, a render pass, a
// windows pass and a clusters pass alike, over its caches seeded with the
// layers by `tableKey`, each in its own workspace. A pass reads and writes the
// tables of its own workspace. The adapter keeps a pass's result under its
// `outputTableName`, leaving the table it computed over as it was, and else in
// place of that table; a table a pass names has the pass's `layerType`, else
// that table's type, or `points` for windows (`store` in its
// adapters/compute.ts). The layers come back in the order the cache holds
// them: those the step held, as the passes left them, then each table a pass
// wrote under a new name, in the pass's workspace. Every pass the GPU runs is
// checked on the GPU's device (`checkedPasses`).
//
// A pass whose own table (a GPGPU, windows or clusters pass's `dataRef`, a
// render pass's viewpoints) matches no layer of its workspace is skipped quietly: chained
// compute nodes can target different layers, and a no-op pass is far less
// surprising than aborting the whole pipeline. A section that writes a key
// autk-grammar 5 renamed, or one a node does not run yet (contracts/autkGrammar),
// runs no pass and is a failure, named.
//
// A pass reads a buildings layer as a map draws it: a building with no height
// is `DEFAULT_BUILDING_HEIGHT` m tall above its base (utils/autkInput
// `withDefaultHeights`), so a pass that reads every building's height with
// `required: true` leaves none out. The step hands its layers on as it holds
// them: a building with no height keeps none, in a layer no pass wrote and in
// one a pass wrote over it (`withHeightsAsHeld`).
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
    // The grammar's caches, as its own run keeps them: each table by tableKey,
    // with the name and the workspace it is handed on with.
    const cache = new Map<string, FeatureCollection>();
    const types = new Map<string, any>();
    const held = new Map<string, { name: string; workspace?: string }>();
    // Each buildings layer as the step holds it, where its passes read it with
    // the default height (withDefaultHeights), by key; and each table a pass
    // wrote, with the key of the one it computed over.
    const asHeld = new Map<string, FeatureCollection>();
    const wroteFrom = new Map<string, string>();
    for (const layer of layers) {
        const workspace = autkWorkspaceOf(layer);
        const key = tableKey(workspace, layer.name);
        const read = layer.type === 'buildings' ? withDefaultHeights(layer.geojson) : layer.geojson;
        if (read !== layer.geojson) asHeld.set(key, layer.geojson);
        cache.set(key, read);
        types.set(key, layer.type);
        held.set(key, { name: layer.name, ...(workspace ? { workspace } : {}) });
    }
    // The adapter is handed no data adapter's cache: the step's tables are all
    // in its own cache, which a pass reads first.
    const adapter = checkedPasses(createComputeAdapter(cache, types));
    const db = heldTables(types, HELD_TABLES_CRS);
    for (const pass of computeBlocks) {
        // A GPGPU pass's type is `gpgpu` or left out. Every other type reaches
        // the grammar's adapter, which runs a render pass on the GPU, a
        // windows or a clusters pass on the CPU, and refuses any other type by
        // its name.
        const gpgpu = pass?.type === undefined || pass?.type === 'gpgpu';
        const render = pass?.type === 'render';
        const source = render ? pass?.viewpoints?.dataRef : pass?.dataRef;
        if (!pass || !source || (gpgpu && !pass.wgslFunction)) continue;
        const workspace = autkWorkspaceOf(pass);
        if (!cache.has(tableKey(workspace, source))) continue;
        const sourceCrs = (cache.get(tableKey(workspace, source)) as any)?.crs;
        const name = typeof pass.outputTableName === 'string' && pass.outputTableName ? pass.outputTableName : source;
        const key = tableKey(workspace, name);
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
        held.set(key, { name, ...(workspace ? { workspace } : {}) });
        // A windows pass, and a render pass that looks out of building
        // windows, write a point a window, not the rows they computed over.
        const holdsRows = pass.type !== 'windows' && !(render && pass?.viewpoints?.strategy?.type === 'building-windows');
        const over = tableKey(workspace, source);
        wroteFrom.set(key, holdsRows ? wroteFrom.get(over) ?? over : '');
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
    // A table no pass wrote is handed on as the step holds it; one a pass
    // wrote over a buildings layer holds each building's own height.
    const handedOn = (key: string, geojson: FeatureCollection): FeatureCollection => {
        const from = wroteFrom.get(key);
        if (from === undefined) return asHeld.get(key) ?? geojson;
        const source = asHeld.get(from);
        return source ? withHeightsAsHeld(geojson, source) : geojson;
    };
    return [...cache].map(([key, geojson]) => ({
        name: held.get(key)?.name ?? key,
        type: types.get(key) ?? 'polygons',
        geojson: handedOn(key, geojson),
        ...(held.get(key)?.workspace ? { workspace: held.get(key)!.workspace } : {}),
    }));
}

/**
 * The database a compute step's passes read, as autk-grammar's compute
 * adapter reads one: the tables the step holds, of the types *types* gives,
 * the workspace a pass enters its own, kept in autk-db's CRS
 * (*coordinateFormat*), which a GPGPU pass reads before it reads a table. The
 * adapter reads a table from its cache first, which holds them all, so one it
 * asks this database for is a table the step does not hold, which fails its
 * pass as autk-db fails a read of a table it does not hold.
 */
function heldTables(types: Map<string, string>, coordinateFormat: string) {
    let workspace: string | undefined;
    return {
        getCurrentWorkspace: () => workspace,
        setWorkspace: async (name: string) => {
            workspace = name;
        },
        getWorkspaceConfiguration: () => ({ coordinateFormat }),
        getTablesMetadata: () => [...types].map(([name, type]) => ({ name, type })),
        getLayer: async (name: string): Promise<FeatureCollection> => {
            throw new Error(`Table ${name} not found.`);
        },
    };
}
