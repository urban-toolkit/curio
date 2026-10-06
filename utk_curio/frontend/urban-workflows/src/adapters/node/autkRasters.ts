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
 * a map that starts with it (`framedRaster`). Once the map is drawn,
 * `recolorRasters` colors every raster layer again in its legend's scheme and
 * domain. Nothing in Autark is changed; the instance's data adapter, and that
 * database's `getLayer`, are wrapped.
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
 * own collection, framed, as it was read right after loading. autk-db's
 * `getLayer` gives a raster the workspace's extent once any layer with
 * geometry has set one, which stretches the raster over that layer's extent
 * instead; `getRaster` gives its own. Every other table is the database's to
 * answer, as before.
 */
function serveRaster(db: any, table: string, collection: any): void {
    let served: Map<string, any> | undefined = db[SERVED_RASTERS];
    if (!served) {
        served = new Map();
        const rasters = served;
        const getLayer = typeof db.getLayer === 'function' ? db.getLayer.bind(db) : null;
        db.getLayer = async (name: string, ...rest: any[]) => {
            if (!rasters.has(name)) {
                if (!getLayer) throw new Error(`Table ${name} not found.`);
                return getLayer(name, ...rest);
            }
            return rasters.get(name);
        };
        db[SERVED_RASTERS] = served;
    }
    served.set(table, framedRaster(collection));
}

/**
 * autk-db keeps a raster's cells in one store for the whole page, keyed by
 * workspace and table (`autk.input_0`), not by database. Every Autark node's
 * database has the workspace `autk`, and a node's input is `input_0`, so two
 * maps that load a raster at once each drew whichever loaded last. A raster
 * is loaded and read back here one at a time, and its node keeps what it
 * read.
 */
let rasterLoads: Promise<unknown> = Promise.resolve();

function oneRasterAtATime<T>(load: () => Promise<T>): Promise<T> {
    const next = rasterLoads.then(load, load);
    rasterLoads = next.catch(() => undefined);
    return next;
}

/**
 * Let one grammar instance load `curio-raster` sources: each goes into the
 * grammar's own database (made with `newDb` when it is the first source), by
 * `loadGeoTiff`, and the map is handed what `getRaster` read back. Any other
 * source is the grammar's to load, as before.
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
            if (typeof target.getRaster !== 'function') throw new Error(RASTER_EXPORT_MISSING);
            const collection = await oneRasterAtATime(async () => {
                await target.loadGeoTiff(loadGeoTiffParams(source));
                return target.getRaster(source.outputTableName);
            });
            serveRaster(target, source.outputTableName, collection);
            return target;
        },
    };
}

/**
 * How every raster layer is drawn, as SCOUT draws its tiles: each cell with a
 * value fully opaque, 0 included, and a cell with no data (NaN) clear.
 * autk-map's own opacity grows with a cell's distance from 0 (`far-zero`), so
 * a 7 m building beside a 527 m tower was drawn 1% opaque.
 */
export const RASTER_TRANSFER_FUNCTION = { opacityMin: 1, opacityMax: 1 };

/**
 * Give each clear cell of *rgba* (autk-map's colored cells, four 0..255
 * values a cell, rows of *width*) the color of the nearest cell with a value,
 * keeping it clear. autk-map samples a raster linearly and a clear cell is
 * black, so every edge between a cell with no data and one with a value was
 * drawn as a dark line. One pass outward from every colored cell.
 */
export function bleedIntoClearCells(rgba: Float32Array, width: number, height: number): void {
    const cells = width * height;
    const seen = new Uint8Array(cells);
    const queue = new Int32Array(cells);
    let head = 0, tail = 0;
    for (let i = 0; i < cells; i++) {
        if (rgba[i * 4 + 3] !== 0) { seen[i] = 1; queue[tail++] = i; }
    }
    if (tail === 0) return;
    while (head < tail) {
        const from = queue[head++];
        const x = from % width;
        const neighbors = [
            x > 0 ? from - 1 : -1, x < width - 1 ? from + 1 : -1,
            from >= width ? from - width : -1, from + width < cells ? from + width : -1,
        ];
        for (const to of neighbors) {
            if (to < 0 || seen[to]) continue;
            seen[to] = 1;
            rgba[to * 4] = rgba[from * 4];
            rgba[to * 4 + 1] = rgba[from * 4 + 1];
            rgba[to * 4 + 2] = rgba[from * 4 + 2];
            queue[tail++] = to;
        }
    }
}

/**
 * Draw every raster layer the same way, in the colors its legend shows.
 * autk-map colors a raster's cells when it loads it, in its default reds, and
 * autk-grammar sets the layer's `colorMapInterpolator` after that, so the
 * legend showed the scheme, with no range, and the cells stayed red.
 * autk-map's `updateColorMap` colors the cells again from the layer's own
 * config (the layerRef's scheme, else autk-map's reds), as
 * `RASTER_TRANSFER_FUNCTION` says, and gives the legend its domain. A
 * raster's cells are colored whatever its `isColorMap`, so on a raster
 * `"isColorMap": false` hides the legend alone; the grammar turns it on for
 * any layer with a scheme. The grammar keeps each map by the dataRefs it
 * draws (`_mapRegistry`); a layer that is not a raster is left as drawn.
 */
export function recolorRasters(grammar: any, spec: any): void {
    const registry: Map<string, any> | undefined = grammar?._mapRegistry;
    if (!registry) return;
    const maps = spec?.map ? (Array.isArray(spec.map) ? spec.map : [spec.map]) : [];
    for (const mapSpec of maps) {
        for (const ref of mapSpec?.layerRefs ?? []) {
            const map = registry.get(ref?.dataRef);
            const layer = map?.layerManager?.searchByLayerId?.(ref.dataRef);
            if (layer?.layerInfo?.typeLayer !== 'raster' || typeof map.updateColorMap !== 'function') continue;
            layer.setTransferFunction?.(RASTER_TRANSFER_FUNCTION);
            map.updateColorMap(ref.dataRef, { colorMap: {} });
            const rgba = layer.rasterData;
            if (rgba instanceof Float32Array && layer.rasterResX > 0 && layer.rasterResY > 0) {
                bleedIntoClearCells(rgba, layer.rasterResX, layer.rasterResY);
            }
            if (ref.isColorMap === false) map.updateRenderInfo(ref.dataRef, { isColorMap: false });
        }
    }
}

/** A fresh autk-db database, as autk-grammar makes its own. */
export async function newAutkDb(): Promise<any> {
    const { AutkDb } = await import('@urban-toolkit/autk-db');
    const db = new AutkDb();
    await db.init();
    return db;
}
