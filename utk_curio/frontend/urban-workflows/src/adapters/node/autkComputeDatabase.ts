/**
 * A compute step whose passes keep their results in autk-db (`writeBack`) or
 * whose data section has sources after compute (`after: 'compute'`), run as
 * autk-grammar's own run runs a document (autk-grammar 5.5.0, our
 * autk-grammar#30).
 *
 * A compute step runs its passes over the layers it holds with no database
 * (autkComputeBlocks). A pass with `writeBack` also keeps its result in
 * autk-db, and a source after compute reads autk-db, so a step with either
 * runs on a database of its own, through the steps of a run the grammar's
 * main entry gives a host (`createComputeSteps`, autk-grammar 5.6.0), wired
 * to one another as a map node's run wires its adapters, each pass checked as
 * a map node's is (`checkedPasses`), with no view to draw:
 *
 * - the document's workspaces set up (`resolveWorkspaces`);
 * - each layer the step holds loaded as a GeoJSON source, in the order a map
 *   node hands its tables to the grammar (utils/autkInput `tablesToLoad`), on
 *   the 1 cm grid it hands them on (utils/geoPrecision); a raster, and a table
 *   with no geometry, which no pass or source reads, stay out; a buildings
 *   layer with each building with no height `DEFAULT_BUILDING_HEIGHT` m tall
 *   above its base, as the step's passes read it with no database
 *   (utils/buildingHeight `withDefaultHeight`), each such part marked with the
 *   height it held (`HELD_HEIGHT`), which stays in the database;
 * - its passes, each checked (autkComputeScopes), each reading its table as
 *   autk-db keeps it and a `fromFeature` table as the source gave it, as a map
 *   node's passes do; a pass whose table the step does not hold is skipped, as
 *   the step skips it without a database;
 * - then its sources after compute, in their order, which read what the
 *   passes kept in autk-db: a heatmap is made and read back one raster at a
 *   time, as the loaders make one (autkLayerMaterialize `grammarRaster`).
 *
 * It hands on as every Autark node hands its tables on (autkHandOn
 * `handOnTables`), in order: each layer it holds, as a pass left it or as it
 * came; each table a pass wrote under a name of its own; then each table a
 * source after compute made. A table a source after compute wrote (a join
 * into it, an update, a SQL query saved under its name, a load) is read back
 * as autk-db holds it, as the loaders hand one on (autkHandOn `readBackTable`):
 * an OpenStreetMap table with its OSM ids and its numeric tags as numbers
 * (`withOsmIds`, `withOsmNumbers`), a buildings table a part a row
 * (`explodeBuildingParts`), and a table with no geometry as its rows
 * (`plainTableRecord`). A part the step gave the default holds its own height
 * again wherever it is handed on with its mark and still holds that default,
 * in a table a pass wrote over its layer and in one a source after compute
 * read back: autk-db keeps a row's properties, its mark among them, through a
 * join, which patches them (`json_merge_patch`), and an update gives the rows
 * it matches the properties it was given, the user's, with no mark and no
 * default. A part a source gave a height of its own, such as a SQL query
 * saved under its table's name, keeps it. A table a pass wrote a point a
 * window into keeps the heights it holds. No mark is handed on. A table a
 * source after compute dropped is gone. Each
 * table a pass or a source wrote says the CRS of its workspace (`crs`), the
 * coordinates autk-db keeps it in. A pass or a source that fails is a failure,
 * named, and the step hands on the layers it was given.
 */
import { detectCoordinateFormat } from '../../utils/geoCrs';
import { snapSourceToGrid } from '../../utils/geoPrecision';
import { tablesToLoad } from '../../utils/autkInput';
import { deriveBuildingHeight, withDefaultHeight } from '../../utils/buildingHeight';
import {
    GRAMMAR_RASTER_SOURCES,
    autkTableKey,
    autkWorkspaceOf,
    workspaceCrsOf,
} from './autkDataCompile';
import { RASTER_TABLE, grammarRaster } from './autkLayerMaterialize';
import { checkedPasses } from './autkComputeScopes';
import { closeAutkDb } from './autkDbClose';
import { withExtensionRetry } from './duckdbExtensionRetry';
import { hasFeatures } from './autkRunDescriptions';
import { computeFailure, handOnTables, readBackTable, workspaceCrs } from './autkHandOn';

/**
 * A layer a compute step holds, in the workspace it names when it is not the
 * default one; a raster of its input as it came (`asItCame`), which goes on as
 * it came.
 */
type Layer = { name: string; type?: string; geojson: any; workspace?: string; asItCame?: any };

/** What a compute step says when the grammar gives a host no steps of a run (`createComputeSteps`). */
export const COMPUTE_DATABASE_MISSING =
    'Autark cannot keep these passes in autk-db or run sources after compute: this autk-grammar build gives no '
    + "createComputeSteps, which Curio's compute step (adapters/node/autkComputeDatabase.ts) runs them with.";

const keyOf = (layer: { name: string; workspace?: string }): string => autkTableKey(layer.workspace, layer.name);

/** Whether a feature of *collection* has a geometry: a table autk-db can load as a layer. */
function hasGeometry(collection: any): boolean {
    return hasFeatures(collection) && (collection.features as any[]).some((feature) => feature?.geometry != null);
}

/**
 * The property a building part the step gives the default height carries in
 * its database, and never out of it: the default it was given, `put`, and the
 * height it held, `held`, left out for none.
 */
export const HELD_HEIGHT = '__curio_held_height';

/**
 * *fc*, a buildings layer, as the step's passes read it: each part with no
 * height above its base `DEFAULT_BUILDING_HEIGHT` m tall above it
 * (`withDefaultHeight`) and marked with that default and the height it held
 * (`HELD_HEIGHT`). The same object when no part changes.
 */
function withMarkedDefaults(fc: any): any {
    const features: any[] = Array.isArray(fc?.features) ? fc.features : [];
    let changed = false;
    const next = features.map((feature) => {
        const own = feature?.properties;
        const read = withDefaultHeight(own);
        if (read === own) return feature;
        changed = true;
        if (deriveBuildingHeight(own ?? {}) === null) return { ...feature, properties: read };
        const held = own != null && typeof own === 'object' && 'height' in own ? { held: own.height } : {};
        return { ...feature, properties: { ...read, [HELD_HEIGHT]: { put: read.height, ...held } } };
    });
    return changed ? { ...fc, features: next } : fc;
}

/**
 * *fc* with no part marked (`HELD_HEIGHT`): with *restore*, each marked part
 * that still holds the default the step put holds the height it held again,
 * none where it held none, and one a source gave a height of its own keeps
 * it. The same object when no part is marked.
 */
function withoutMarks(fc: any, restore: boolean): any {
    const features: any[] = Array.isArray(fc?.features) ? fc.features : [];
    let changed = false;
    const next = features.map((feature) => {
        const properties = feature?.properties;
        if (properties == null || typeof properties !== 'object' || !(HELD_HEIGHT in properties)) return feature;
        changed = true;
        const { [HELD_HEIGHT]: mark, ...rest } = properties;
        const marked = mark != null && typeof mark === 'object';
        if (restore && marked && 'put' in mark && rest.height === mark.put) {
            if ('held' in mark) rest.height = mark.held;
            else delete rest.height;
        }
        return { ...feature, properties: rest };
    });
    return changed ? { ...fc, features: next } : fc;
}

/** The table a pass computes over: a render pass's viewpoints, any other pass's `dataRef`. */
function passSource(pass: any): unknown {
    return pass?.type === 'render' ? pass?.viewpoints?.dataRef : pass?.dataRef;
}

export async function computeOnADatabase(
    layers: Layer[],
    passes: any[],
    after: any[],
    spec: { workspaces?: unknown; [key: string]: unknown },
    failures: string[],
): Promise<Layer[]> {
    const [grammar, { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT }] = await Promise.all([
        import('@urban-toolkit/autk-grammar'),
        import('@urban-toolkit/autk-db'),
    ]);
    // The steps of a run up to its maps and plots, wired to one another as a
    // run wires its adapters, run each part of the document on the step's own
    // database, and give each table a pass wrote, with its type (`computed`).
    if (typeof grammar.createComputeSteps !== 'function') {
        failures.push(COMPUTE_DATABASE_MISSING);
        return layers;
    }
    const steps = grammar.createComputeSteps();
    const checked = checkedPasses(steps);
    const workspaces = Array.isArray(spec.workspaces) && spec.workspaces.length > 0 ? spec.workspaces : null;
    const crsOf = workspaceCrsOf(workspaces);
    // `init()` downloads the DuckDB spatial extension; a flaky fetch is worth
    // another instance rather than a failed node (#318).
    const db: any = await withExtensionRetry(async () => {
        const instance: any = new AutkDb();
        try {
            await instance.init();
        } catch (err) {
            closeAutkDb(instance);
            throw err;
        }
        return instance;
    });
    const failed = (what: string, e: unknown): Layer[] => {
        failures.push(computeFailure(what, e));
        return layers;
    };
    try {
        if (workspaces) {
            try {
                await steps.resolveWorkspaces(db, workspaces as any);
            } catch (e) {
                return failed('workspaces', e);
            }
        }
        // The layers the step holds, as the sources a map node hands the
        // grammar: a buildings layer as its passes read it, each building with
        // no height at the default and marked with the height it held.
        const loadable = layers
            .filter((layer) => layer.type !== RASTER_TABLE && hasGeometry(layer.geojson))
            .map((layer) => {
                const geojson = layer.type === 'buildings' ? withMarkedDefaults(layer.geojson) : layer.geojson;
                return {
                    type: 'geojson',
                    geojsonObject: geojson,
                    outputTableName: layer.name,
                    coordinateFormat: detectCoordinateFormat(geojson),
                    ...(layer.type && layer.type !== 'polygons' ? { layerType: layer.type } : {}),
                    ...(layer.workspace ? { workspace: layer.workspace } : {}),
                };
            });
        for (const source of tablesToLoad(loadable, spec, loadable)) {
            try {
                await steps.resolveSource(db, snapSourceToGrid(source) as any);
            } catch (e) {
                return failed(autkTableKey(autkWorkspaceOf(source), source.outputTableName), e);
            }
        }
        // The passes, over the tables the step holds and those earlier passes
        // wrote.
        const present = new Set(layers.map(keyOf));
        const ran: any[] = [];
        for (const pass of passes) {
            const gpgpu = pass?.type === undefined || pass?.type === 'gpgpu';
            const source = passSource(pass);
            if (!pass || typeof source !== 'string' || !source || (gpgpu && !pass.wgslFunction)) continue;
            const workspace = autkWorkspaceOf(pass);
            if (!present.has(autkTableKey(workspace, source))) continue;
            try {
                await checked.resolveCompute(db, pass);
            } catch (e) {
                console.warn('[autk-grammar] compute pass failed', e);
                failures.push((e as Error)?.message ?? 'compute failed');
                return layers;
            }
            ran.push(pass);
            const name = typeof pass.outputTableName === 'string' && pass.outputTableName ? pass.outputTableName : source;
            present.add(autkTableKey(workspace, name));
        }
        // The sources after compute, which read autk-db.
        const rasters = new Map<string, Layer>();
        for (const source of after) {
            try {
                if (GRAMMAR_RASTER_SOURCES.includes(source?.type)) {
                    const raster = await grammarRaster(db, source, steps);
                    rasters.set(keyOf(raster), raster);
                } else {
                    await steps.resolveSource(db, source);
                }
            } catch (e) {
                return failed(`${source?.type ?? 'source'} after compute`, e);
            }
        }

        // What the step hands on: each table a pass wrote as the steps hold
        // it, in the CRS of its workspace; each a source after compute wrote
        // read back from autk-db (a raster as it was made); and no part
        // marked, each marked part with its own height again where the table
        // holds the rows of the one a pass computed over, or a source after
        // compute wrote it.
        const unmarked = (layer: Layer, restore: boolean): Layer => {
            const geojson = withoutMarks(layer.geojson, restore);
            return geojson === layer.geojson ? layer : { ...layer, geojson };
        };
        return await handOnTables({
            held: layers,
            passes: ran,
            after,
            computed: (name, workspace) => {
                const computed = steps.computed(name, workspace);
                return computed ? { collection: computed.collection, layerType: computed.layerType } : undefined;
            },
            readBack: (name, workspace) => rasters.get(autkTableKey(workspace, name))
                ?? readBackTable(db, grammar.enterWorkspace, name, workspace, crsOf, DEFAULT_WORKSPACE_COORDINATE_FORMAT),
            crs: (collection, workspace) => workspaceCrs(collection, workspace, crsOf, DEFAULT_WORKSPACE_COORDINATE_FORMAT),
            heights: (table, rows, how) => unmarked(table, how === 'read back' || rows !== undefined),
        });
    } catch (e) {
        return failed('compute', e);
    } finally {
        closeAutkDb(db);
    }
}
