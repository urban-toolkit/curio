/**
 * A compute step whose passes keep their results in autk-db (`writeBack`) or
 * whose data section has sources after compute (`after: 'compute'`), run as
 * autk-grammar's own run runs a document (autk-grammar 5.5.0, our
 * autk-grammar#30).
 *
 * A compute step runs its passes over the layers it holds with no database
 * (autkComputeBlocks). A pass with `writeBack` also keeps its result in
 * autk-db, and a source after compute reads autk-db, so a step with either
 * runs on a database of its own, through the grammar's own adapters and
 * caches, wired as an AutkGrammar wires them (`createDataAdapter`,
 * `createComputeAdapter`):
 *
 * - the document's workspaces set up (`resolveWorkspaces`);
 * - each layer the step holds loaded as a GeoJSON source, in the order a map
 *   node hands its tables to the grammar (utils/autkInput `tablesToLoad`), on
 *   the 1 cm grid it hands them on (utils/geoPrecision); a raster, and a table
 *   with no geometry, which no pass or source reads, stay out;
 * - its passes, each checked (autkComputeScopes `checkedPasses`), each reading
 *   its table as autk-db keeps it, as a map node's passes do; a pass whose
 *   table the step does not hold is skipped, as the step skips it without a
 *   database;
 * - then its sources after compute, in their order, which read what the
 *   passes kept in autk-db: a heatmap is made and read back one raster at a
 *   time, as the loaders make one (autkLayerMaterialize `grammarRaster`).
 *
 * It hands on, in order: each layer it holds, as a pass left it or as it
 * came; each table a pass wrote under a name of its own; then each table a
 * source after compute made. A table a source after compute wrote (a join
 * into it, an update, a SQL query saved under its name, a load) is read back
 * as autk-db holds it: a buildings table a part a row, as the loaders hand
 * one on (`explodeBuildingParts`), and a table with no geometry as its rows
 * (`plainTableRecord`). A table a source after compute dropped is gone. Each
 * table a pass or a source wrote says the CRS of its workspace (`crs`), the
 * coordinates autk-db keeps it in. A pass or a source that fails is a failure,
 * named, and the step hands on the layers it was given.
 */
import type { FeatureCollection } from 'geojson';
import { detectCoordinateFormat } from '../../utils/geoCrs';
import { snapSourceToGrid } from '../../utils/geoPrecision';
import { tablesToLoad, writtenTables } from '../../utils/autkInput';
import {
    GRAMMAR_RASTER_SOURCES,
    autkTableKey,
    autkWorkspaceOf,
    layerEpsg,
    plainTableRecord,
    requestedLayerTables,
    sectionChangedTables,
    workspaceCrsOf,
} from './autkDataCompile';
import { RASTER_TABLE, explodeBuildingParts, grammarRaster } from './autkLayerMaterialize';
import { checkedPasses } from './autkComputeScopes';
import { closeAutkDb } from './autkDbClose';
import { withExtensionRetry } from './duckdbExtensionRetry';
import { hasFeatures } from './autkRunDescriptions';

/** A layer a compute step holds, in the workspace it names when it is not the default one. */
type Layer = { name: string; type?: string; geojson: any; workspace?: string };

const keyOf = (layer: { name: string; workspace?: string }): string => autkTableKey(layer.workspace, layer.name);

/** Whether a feature of *collection* has a geometry: a table autk-db can load as a layer. */
function hasGeometry(collection: any): boolean {
    return hasFeatures(collection) && (collection.features as any[]).some((feature) => feature?.geometry != null);
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
    // The grammar's caches, as an AutkGrammar keeps them: each GeoJSON table a
    // source loaded, and each table a pass wrote with its type, by tableKey.
    const sources = new Map<string, FeatureCollection>();
    const cache = new Map<string, FeatureCollection>();
    const types = new Map<string, any>();
    const dataAdapter = grammar.createDataAdapter(undefined, sources, cache, types);
    const computeAdapter = checkedPasses(grammar.createComputeAdapter(cache, types, sources));
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
                await dataAdapter.resolveWorkspaces(db, workspaces);
            } catch (e) {
                return failed('workspaces', e);
            }
        }
        // The layers the step holds, as the sources a map node hands the grammar.
        const loadable = layers
            .filter((layer) => layer.type !== RASTER_TABLE && hasGeometry(layer.geojson))
            .map((layer) => ({
                type: 'geojson',
                geojsonObject: layer.geojson,
                outputTableName: layer.name,
                coordinateFormat: detectCoordinateFormat(layer.geojson),
                ...(layer.type && layer.type !== 'polygons' ? { layerType: layer.type } : {}),
                ...(layer.workspace ? { workspace: layer.workspace } : {}),
            }));
        for (const source of tablesToLoad(loadable, spec, loadable)) {
            try {
                await dataAdapter.resolveSource(db, snapSourceToGrid(source) as any);
            } catch (e) {
                return failed(autkTableKey(autkWorkspaceOf(source), source.outputTableName), e);
            }
        }
        // The passes, over the tables the step holds and those earlier passes wrote.
        const present = new Set(layers.map(keyOf));
        const ran: any[] = [];
        for (const pass of passes) {
            const gpgpu = pass?.type === undefined || pass?.type === 'gpgpu';
            const source = passSource(pass);
            if (!pass || typeof source !== 'string' || !source || (gpgpu && !pass.wgslFunction)) continue;
            const workspace = autkWorkspaceOf(pass);
            if (!present.has(autkTableKey(workspace, source))) continue;
            try {
                await computeAdapter.resolveCompute(db, pass);
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
                    const raster = await grammarRaster(db, source, dataAdapter);
                    rasters.set(keyOf(raster), raster);
                } else {
                    await dataAdapter.resolveSource(db, source);
                }
            } catch (e) {
                return failed(`${source?.type ?? 'source'} after compute`, e);
            }
        }

        // A table read back from autk-db, in its workspace, as the loaders hand one on.
        const readBack = async (name: string, workspace: string | undefined): Promise<Layer> => {
            const raster = rasters.get(autkTableKey(workspace, name));
            if (raster) return raster;
            await grammar.enterWorkspace(db, workspace);
            const table = (db.getTablesMetadata() as Array<{ name: string; type?: string }>).find((t) => t.name === name);
            if (table && table.type === undefined) {
                return plainTableRecord(name, await db.getTable(name), workspace) as Layer;
            }
            const geojson: any = await db.getLayer(name);
            const type = table?.type ?? 'polygons';
            if (type === 'buildings' && Array.isArray(geojson?.features)) geojson.features = explodeBuildingParts(geojson.features);
            if (geojson && typeof geojson === 'object') {
                const epsg = layerEpsg(geojson, workspace, crsOf, DEFAULT_WORKSPACE_COORDINATE_FORMAT);
                geojson.crs = { type: 'name', properties: { name: `urn:ogc:def:crs:EPSG::${epsg}` } };
            }
            return { name, type, geojson, ...(workspace ? { workspace } : {}) };
        };
        // A table a pass wrote, as the cache holds it: in the CRS of its
        // workspace, the columns it computed also lifted to the top of each
        // feature's properties, as a step without a database hands them on.
        const passResult = async (name: string, workspace: string | undefined, was: Layer | undefined, pass: any): Promise<Layer> => {
            const key = autkTableKey(workspace, name);
            const result: any = cache.get(key);
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
            return { name, type: types.get(key) ?? was?.type ?? 'polygons', geojson: result, ...(workspace ? { workspace } : {}) };
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
        const handOn = async (name: string, workspace: string | undefined, was?: Layer) => {
            const key = autkTableKey(workspace, name);
            if (listed.has(key) || dropped.has(key)) return;
            listed.add(key);
            if (cache.has(key)) handed.push(await passResult(name, workspace, was, lastPassOf.get(key)));
            else if (wroteAfter.has(key) || rasters.has(key)) handed.push(await readBack(name, workspace));
            else if (was) handed.push(was);
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
