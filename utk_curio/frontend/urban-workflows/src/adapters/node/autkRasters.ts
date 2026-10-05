/**
 * Rasters on an Autark node: loaded with autk-db's `loadGeoTiff`, drawn by the
 * grammar's own map.
 *
 * autk-grammar draws a raster table on a map (`getRaster`, then autk-map's
 * `loadCollection` with `type: 'raster'`), but its document has no way to load
 * one: its data sources are OSM, CSV, JSON, GeoJSON, a heatmap or a join. So a
 * raster the node's input brings becomes a source of Curio's own,
 * `curio-raster`, which `withRasterSources` teaches one grammar instance to
 * load: into the grammar's own database, with `loadGeoTiff`, before its map
 * runs. Every other source goes to the grammar unchanged. The map then reads
 * the raster by `getRaster`, at its own extent, outlined so autk-map can place
 * a map that starts with it (`framedRaster`). Nothing in Autark is changed;
 * the instance's data adapter, and that database's `getLayer`, are wrapped.
 *
 * A raster comes as GeoTIFF bytes: a Python node's rasterio dataset is asked
 * of the sandbox by its artifact (`/raster`), and a collection an upstream
 * Autark node handed on is written back to GeoTIFF bytes here. Either way it
 * is loaded at its own size, with `nearest` resampling and its CRS
 * (utils/raster/rasterLoad).
 */
import { fetchRaster } from '../../services/api';
import type { AutkRasterInput } from '../../utils/autkInput';
import { writeGeoTiff } from '../../utils/raster/geotiffWriter';
import {
    RASTER_MAX_CELLS,
    RASTER_MAX_SIDE,
    oversizeSentence,
    planForGrid,
    planForMeta,
    type GeotiffLoad,
} from '../../utils/raster/rasterLoad';
import { decodeRasterEnvelope, rasterBandIds, type RasterGrid } from '../../utils/raster/rasterWire';

export const CURIO_RASTER_SOURCE = 'curio-raster';

/** A raster for the grammar's database, as `withRasterSources` loads it. */
export type CurioRasterSource = {
    type: typeof CURIO_RASTER_SOURCE;
    outputTableName: string;
    geotiffArrayBuffer: ArrayBuffer;
    load: GeotiffLoad;
    /** The grid its cells lie on, which autk-db does not keep. */
    grid: RasterGrid;
    /** Its cells, the count the run reports for it. */
    cells: number;
};

export function isCurioRasterSource(source: unknown): source is CurioRasterSource {
    return (source as any)?.type === CURIO_RASTER_SOURCE;
}

/** What `loadGeoTiff` is called with for a source. */
export function loadGeoTiffParams(source: CurioRasterSource) {
    return {
        geotiffArrayBuffer: source.geotiffArrayBuffer,
        outputTableName: source.outputTableName,
        coordinateFormat: source.load.coordinateFormat,
        maxRasterCells: source.load.maxRasterCells,
        resampleMethod: source.load.resampleMethod,
    };
}

export type ResolvedRasters = {
    sources: CurioRasterSource[];
    /** Tables the input names but cannot provide. */
    unusable: string[];
    /** Why, one sentence each. */
    problems: string[];
};

async function resolveOne(raster: AutkRasterInput): Promise<CurioRasterSource | { refused: string }> {
    const name = raster.outputTableName;
    const payload: any = raster.payload;
    if (payload && 'envelope' in payload) {
        const decoded = decodeRasterEnvelope(payload.envelope);
        if ('problem' in decoded) return { refused: `${name} cannot be drawn: ${decoded.problem}.` };
        const { collection } = decoded;
        const plan = planForGrid(name, collection.grid);
        if ('refused' in plan) return plan;
        const props = collection.features[0].properties;
        const bands = rasterBandIds(collection).map((id) => props[id] as Float32Array);
        return {
            type: CURIO_RASTER_SOURCE,
            outputTableName: name,
            geotiffArrayBuffer: writeGeoTiff(collection.grid, bands),
            load: plan.load,
            grid: plan.grid,
            cells: plan.cells,
        };
    }
    const fetched = await fetchRaster(payload.artifact, {
        part: payload.part,
        maxCells: RASTER_MAX_CELLS,
        maxSide: RASTER_MAX_SIDE,
    });
    if (!fetched.ok) {
        const meta = fetched.meta;
        const oversize = fetched.status === 413 && meta
            ? oversizeSentence(name, Number(meta.width), Number(meta.height))
            : null;
        return { refused: oversize ?? `${name} cannot be drawn: ${fetched.message}` };
    }
    const plan = planForMeta(name, fetched.meta);
    if ('refused' in plan) return plan;
    return {
        type: CURIO_RASTER_SOURCE,
        outputTableName: name,
        geotiffArrayBuffer: fetched.bytes,
        load: plan.load,
        grid: plan.grid,
        cells: plan.cells,
    };
}

/** The rasters an input brings, as sources the grammar can load. */
export async function resolveRasterInputs(rasters: AutkRasterInput[]): Promise<ResolvedRasters> {
    const resolved: ResolvedRasters = { sources: [], unusable: [], problems: [] };
    for (const raster of rasters) {
        const result = await resolveOne(raster);
        if ('refused' in result) {
            resolved.unusable.push(raster.outputTableName);
            resolved.problems.push(result.refused);
        } else {
            resolved.sources.push(result);
        }
    }
    return resolved;
}

/** Said when an autk-grammar build no longer loads data the way this expects. */
export const RASTER_ADAPTER_MISSING =
    'Autark cannot draw this raster: this autk-grammar build loads its data differently, '
    + "and Curio's raster loader (adapters/node/autkRasters.ts) has to follow it.";

/** Said when the database the grammar uses cannot export a raster. */
export const RASTER_EXPORT_MISSING =
    'Autark cannot draw this raster: this autk-db build has no getRaster, '
    + "and Curio's raster loader (adapters/node/autkRasters.ts) has to follow it.";

/**
 * A raster collection as the grammar's map is handed it: `features[0]` is the
 * raster, untouched, and a second feature outlines its extent. autk-map places
 * a map by the geometry of the first collection it loads, and a raster has
 * none, so a map that starts with a raster would otherwise sit around (0, 0),
 * thousands of kilometres from the raster. The outline is for that alone: it
 * is never handed on to another node, and the raster layer reads `features[0]`.
 */
export function framedRaster(collection: any): any {
    const [minX, minY, maxX, maxY] = collection.bbox;
    const outline = {
        type: 'Feature',
        geometry: {
            type: 'Polygon',
            coordinates: [[[minX, minY], [maxX, minY], [maxX, maxY], [minX, maxY], [minX, minY]]],
        },
        properties: {},
    };
    return { ...collection, features: [collection.features[0], outline] };
}

/** The rasters Curio loaded into a database, and the getLayer it wraps. */
const SERVED_RASTERS = Symbol.for('curio.autk.servedRasters');

/**
 * Answer the grammar's `getLayer` for a raster Curio loaded with the raster's
 * own collection, framed. autk-db's `getLayer` gives a raster the workspace's
 * extent once any layer with geometry has set one, which stretches the raster
 * over that layer's extent instead; `getRaster` gives its own. Every other
 * table is the database's to answer, as before.
 */
function serveRaster(db: any, table: string): void {
    let served: Set<string> | undefined = db[SERVED_RASTERS];
    if (!served) {
        served = new Set();
        const names = served;
        const getLayer = typeof db.getLayer === 'function' ? db.getLayer.bind(db) : null;
        db.getLayer = async (name: string, ...rest: any[]) => {
            if (!names.has(name)) {
                if (!getLayer) throw new Error(`Table ${name} not found.`);
                return getLayer(name, ...rest);
            }
            if (typeof db.getRaster !== 'function') throw new Error(RASTER_EXPORT_MISSING);
            return framedRaster(await db.getRaster(name));
        };
        db[SERVED_RASTERS] = served;
    }
    served.add(table);
}

/**
 * Let one grammar instance load `curio-raster` sources: each goes into the
 * grammar's own database (made with `newDb` when it is the first source), by
 * `loadGeoTiff`, and the map reads it back by `getRaster`. Any other source
 * is the grammar's to load, as before.
 */
export function withRasterSources(grammar: any, newDb: () => Promise<any>): void {
    const adapter = grammar?.dataAdapter;
    if (!adapter || typeof adapter.resolveSource !== 'function') throw new Error(RASTER_ADAPTER_MISSING);
    const resolveSource = adapter.resolveSource.bind(adapter);
    grammar.dataAdapter = {
        ...adapter,
        async resolveSource(db: any, source: any) {
            if (!isCurioRasterSource(source)) return resolveSource(db, source);
            const target = db ?? await newDb();
            await target.loadGeoTiff(loadGeoTiffParams(source));
            serveRaster(target, source.outputTableName);
            return target;
        },
    };
}

/** A fresh autk-db database, as autk-grammar makes its own. */
export async function newAutkDb(): Promise<any> {
    const { AutkDb } = await import('@urban-toolkit/autk-db');
    const db = new AutkDb();
    await db.init();
    return db;
}
