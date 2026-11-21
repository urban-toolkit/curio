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
 * It hands on, in order: each layer it holds, as a pass left it or as it
 * came; each table a pass wrote under a name of its own; then each table a
 * source after compute made. A table a source after compute wrote (a join
 * into it, an update, a SQL query saved under its name, a load) is read back
 * as autk-db holds it, as the loaders hand one on: an OpenStreetMap table with
 * its OSM ids and its numeric tags as numbers (`withOsmIds`,
 * `withOsmNumbers`), a buildings table a part a row (`explodeBuildingParts`),
 * and a table with no geometry as its rows (`plainTableRecord`). A part the step gave the default holds its own height
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
import { tablesToLoad, writtenTables } from '../../utils/autkInput';
import { deriveBuildingHeight, withDefaultHeight } from '../../utils/buildingHeight';
import {
    GRAMMAR_RASTER_SOURCES,
    autkTableKey,
    autkWorkspaceOf,
    layerEpsg,
    plainTableRecord,
    requestedLayerTables,
    sectionChangedTables,
    withOsmIds,
    withOsmNumbers,
    workspaceCrsOf,
} from './autkDataCompile';
import { RASTER_TABLE, explodeBuildingParts, grammarRaster } from './autkLayerMaterialize';
import { checkedPasses } from './autkComputeScopes';
import { closeAutkDb } from './autkDbClose';
import { withExtensionRetry } from './duckdbExtensionRetry';
import { hasFeatures } from './autkRunDescriptions';

/** A layer a compute step holds, in the workspace it names when it is not the default one. */
type Layer = { name: string; type?: string; geojson: any; workspace?: string };

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

/**
 * The keys of the tables *after*'s drops drop and none of its later sources
 * makes again.
 */
function droppedBy(after: any[]): Set<string> {
    const dropped = new Set<string>();
    after.forEach((source, at) => {
        if (source?.type !== 'drop' || typeof source.dataRef !== 'string' || source.dataRef === '') return;
        const key = autkTableKey(autkWorkspaceOf(source), source.dataRef);
        if (!requestedLayerTables(after.slice(at + 1)).includes(key)) dropped.add(key);
    });
    return dropped;
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
        failures.push(`${what}: ${(e as Error)?.message ?? String(e)}`);
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
        // wrote; and each table a pass wrote, with the key of the table whose
        // rows it holds, as autkComputeBlocks keeps it: a windows pass, and a
        // render pass that looks out of building windows, write a point a
        // window, not the rows they computed over (none).
        const present = new Set(layers.map(keyOf));
        const ran: any[] = [];
        const wroteFrom = new Map<string, string>();
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
            const holdsRows = pass.type !== 'windows'
                && !(pass.type === 'render' && pass?.viewpoints?.strategy?.type === 'building-windows');
            const over = autkTableKey(workspace, source);
            wroteFrom.set(autkTableKey(workspace, name), holdsRows ? wroteFrom.get(over) ?? over : '');
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

        // A table read back from autk-db, in its workspace, as the loaders hand
        // one on: an OpenStreetMap table with its OSM ids and its numeric
        // building tags as numbers, a buildings table a part a row.
        const readBack = async (name: string, workspace: string | undefined): Promise<Layer> => {
            const raster = rasters.get(autkTableKey(workspace, name));
            if (raster) return raster;
            await grammar.enterWorkspace(db, workspace);
            const table = (db.getTablesMetadata() as Array<{ name: string; type?: string; source?: string }>)
                .find((t) => t.name === name);
            if (table && table.type === undefined) {
                return plainTableRecord(name, await db.getTable(name), workspace) as Layer;
            }
            const geojson: any = await db.getLayer(name);
            const type = table?.type ?? 'polygons';
            if (Array.isArray(geojson?.features)) geojson.features = withOsmNumbers(table, withOsmIds(table, geojson.features));
            if (type === 'buildings' && Array.isArray(geojson?.features)) geojson.features = explodeBuildingParts(geojson.features);
            if (geojson && typeof geojson === 'object') {
                const epsg = layerEpsg(geojson, workspace, crsOf, DEFAULT_WORKSPACE_COORDINATE_FORMAT);
                geojson.crs = { type: 'name', properties: { name: `urn:ogc:def:crs:EPSG::${epsg}` } };
            }
            return { name, type, geojson, ...(workspace ? { workspace } : {}) };
        };
        // A table a pass wrote, as the steps hold it: in the CRS of its
        // workspace, the columns it computed also lifted to the top of each
        // feature's properties, as a step without a database hands them on.
        const passResult = async (name: string, workspace: string | undefined, was: Layer | undefined, pass: any): Promise<Layer> => {
            const computed = steps.computed(name, workspace);
            const result: any = computed?.collection;
            const outCols: string[] = pass?.type === 'render'
                ? []
                : (pass?.outputColumns ?? (pass?.outputColumnName ? [pass.outputColumnName] : []));
            for (const feature of Array.isArray(result?.features) ? result.features : []) {
                const properties: any = feature?.properties;
                const computed = properties?.compute;
                if (!properties || !computed) continue;
                for (const column of outCols) {
                    if (column in computed && !(column in properties)) properties[column] = computed[column];
                }
            }
            await grammar.enterWorkspace(db, workspace);
            const epsg = layerEpsg(result, workspace, crsOf, DEFAULT_WORKSPACE_COORDINATE_FORMAT);
            result.crs = { type: 'name', properties: { name: `urn:ogc:def:crs:EPSG::${epsg}` } };
            return { name, type: computed?.layerType ?? was?.type ?? 'polygons', geojson: result, ...(workspace ? { workspace } : {}) };
        };

        const lastPassOf = new Map<string, any>();
        for (const pass of ran) {
            const workspace = autkWorkspaceOf(pass);
            const name = typeof pass.outputTableName === 'string' && pass.outputTableName ? pass.outputTableName : passSource(pass);
            lastPassOf.set(autkTableKey(workspace, String(name)), pass);
        }
        const wroteAfter = new Set([...requestedLayerTables(after), ...sectionChangedTables(after)]);
        const dropped = droppedBy(after);
        const handed: Layer[] = [];
        const listed = new Set<string>();
        // A table handed on with no part marked: each marked part with its own
        // height again where the table holds the rows of the one a pass
        // computed over, or a source after compute wrote it.
        const unmarked = (layer: Layer, restore: boolean): Layer => {
            const geojson = withoutMarks(layer.geojson, restore);
            return geojson === layer.geojson ? layer : { ...layer, geojson };
        };
        const handOn = async (name: string, workspace: string | undefined, was?: Layer) => {
            const key = autkTableKey(workspace, name);
            if (listed.has(key) || dropped.has(key)) return;
            listed.add(key);
            if (steps.computed(name, workspace) !== undefined) {
                handed.push(unmarked(await passResult(name, workspace, was, lastPassOf.get(key)), Boolean(wroteFrom.get(key))));
            } else if (wroteAfter.has(key) || rasters.has(key)) {
                handed.push(unmarked(await readBack(name, workspace), true));
            } else if (was) handed.push(was);
        };
        for (const layer of layers) await handOn(layer.name, layer.workspace, layer);
        for (const { name, workspace } of writtenTables({ compute: ran })) await handOn(name, workspace);
        for (const source of after) {
            const workspace = autkWorkspaceOf(source);
            for (const key of requestedLayerTables([source])) {
                const name = workspace === undefined ? key : key.slice(workspace.length + 1);
                await handOn(name, workspace);
            }
        }
        return handed;
    } catch (e) {
        return failed('compute', e);
    } finally {
        closeAutkDb(db);
    }
}
