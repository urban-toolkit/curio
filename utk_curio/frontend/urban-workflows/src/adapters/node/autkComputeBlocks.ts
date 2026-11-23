// A compute step's `compute` section, applied to the layers it holds. Used by
// the node behavior (autkGrammarBehavior.tsx).

import type { FeatureCollection } from 'geojson';
import { autkKeyProblem } from '../../contracts/autkGrammar';
import { withDefaultHeights, withHeightsAsHeld } from '../../utils/autkInput';
import { autkWorkspaceOf } from './autkDataCompile';
import { checkedPasses } from './autkComputeScopes';
import { handOnTables } from './autkHandOn';

/**
 * A layer a compute step holds, in the workspace it names when it is not the
 * default one; a raster of its input as it came, which no pass reads
 * (`asItCame`, autkHandOn `inputTablesOf`).
 */
type Layer = { name: string; type: string; geojson: FeatureCollection; workspace?: string; asItCame?: any };

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
// adapters/compute.ts). The layers come back as every Autark node hands its
// tables on (autkHandOn `handOnTables`): those the step held, as the passes
// left them, then each table a pass wrote under a new name, in the pass's
// workspace. Every pass the GPU runs is checked on the GPU's device
// (`checkedPasses`). A raster of the step's input, as it came, is no table a
// pass reads: it goes on as it came.
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
//
// A step whose passes keep a result in autk-db (`writeBack`), or with sources
// that run after its passes (*afterCompute.after*, autkDataCompile
// sourcesAfterPasses), runs on a database of its own, as autk-grammar's run
// runs a document, the document's workspaces (*afterCompute.workspaces*) set
// up first (autkComputeDatabase), its passes reading the heights as here.
export async function applyComputeBlocks(
    layers: Layer[],
    computeBlocks: any[],
    /** Appended to for every pass that failed, named by the table it writes,
     *  so the caller can refuse to report success. A pass whose table matches
     *  no layer is still skipped quietly - that is a no-op, not a failure. */
    failures: string[] = [],
    afterCompute: { after?: any[]; workspaces?: unknown } = {},
): Promise<Layer[]> {
    const after = Array.isArray(afterCompute.after) ? afterCompute.after : [];
    const passes = Array.isArray(computeBlocks) ? computeBlocks : [];
    if (passes.length === 0 && after.length === 0) return layers;
    const keyProblem = autkKeyProblem({ compute: passes });
    if (keyProblem) {
        failures.push(keyProblem);
        return layers;
    }
    if (after.length > 0 || passes.some((pass) => Boolean(pass?.writeBack))) {
        const { computeOnADatabase } = await import('./autkComputeDatabase');
        const handed = await computeOnADatabase(layers, passes, after, { workspaces: afterCompute.workspaces, compute: passes, data: after }, failures);
        return handed.map((layer) => ({ ...layer, type: layer.type ?? 'polygons' }));
    }
    const { createComputeAdapter, tableKey } = await import('@urban-toolkit/autk-grammar');
    // The grammar's caches, as its own run keeps them: each table by tableKey.
    const cache = new Map<string, FeatureCollection>();
    const types = new Map<string, any>();
    // Each buildings layer as the step holds it, where its passes read it with
    // the default height (withDefaultHeights), by key.
    const asHeld = new Map<string, FeatureCollection>();
    for (const layer of layers) {
        if (layer.asItCame !== undefined) continue;
        const workspace = autkWorkspaceOf(layer);
        const key = tableKey(workspace, layer.name);
        const read = layer.type === 'buildings' ? withDefaultHeights(layer.geojson) : layer.geojson;
        if (read !== layer.geojson) asHeld.set(key, layer.geojson);
        cache.set(key, read);
        types.set(key, layer.type);
    }
    // The adapter is handed no data adapter's cache: the step's tables are all
    // in its own cache, which a pass reads first.
    const adapter = checkedPasses(createComputeAdapter(cache, types));
    const db = heldTables(types, HELD_TABLES_CRS);
    // The passes that ran, in order: what wrote each table handed on.
    const ran: any[] = [];
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
        ran.push(pass);
        const result: any = cache.get(key);
        if (!result) continue;
        // The pipelines write each GPGPU output under properties.compute.<col>.
        // Also lift them to top-level properties so later passes can reference
        // the column by its bare name (e.g. `height_m`), as the nodes below do
        // (autkHandOn `withLiftedColumns`, which hands every table on so).
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
    }
    // A table no pass wrote is handed on as the step holds it. One a pass
    // wrote is in the CRS of the table it was computed from, which it says
    // when it says none of its own (a render pass's windows are a new
    // collection), and one it wrote over a buildings layer holds each
    // building's own height.
    const handed = await handOnTables({
        held: layers,
        passes: ran,
        computed: (name, workspace) => {
            const key = tableKey(workspace, name);
            const collection = cache.get(key);
            return collection ? { collection, layerType: types.get(key) } : undefined;
        },
        crs: (collection, _workspace, from) => (collection?.crs ? undefined : (from?.geojson as any)?.crs),
        heights: (table, rows, how) => {
            const held = how === 'computed' && rows ? asHeld.get(tableKey(autkWorkspaceOf(rows), rows.name)) : undefined;
            return held ? { ...table, geojson: withHeightsAsHeld(table.geojson, held) } : table;
        },
    });
    return handed.map((layer) => ({ ...layer, type: layer.type ?? 'polygons' }) as Layer);
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
