/**
 * Rasters on an Autark node: loaded with autk-db's `loadGeoTiff`, drawn by the
 * grammar's own map.
 *
 * autk-grammar draws a raster table on a map (`getRaster`, then autk-map's
 * `loadCollection` with `type: 'raster'`). A raster the node's input brings is
 * bytes, not a URL, so it becomes a source of Curio's own, `curio-raster`,
 * which `withRasterSources` loads around the grammar's data adapter, as the
 * node hands it to the grammar (`wrapDataAdapter`): into the database the run
 * goes on, the node's own (autkDbClose `runDatabase`), with `loadGeoTiff`,
 * before its map runs. So does a
 * raster the node's own data section made, a heatmap or the GeoTIFF of a
 * `geotiff` source, which the data load hands the map as a collection
 * (`rasterSourceOf`). Every other source goes to the grammar unchanged. A
 * compute pass reads a table's features, and a raster has none of its own,
 * so a pass over a raster is refused (contracts/autkGrammar
 * `autkRasterPassProblem`). The map then reads
 * the raster by `getRaster`, at its own extent, outlined so autk-map can place
 * a map that starts with it (`framedRaster`), its bands named as they were
 * made (`withBandLabels`). The grammar colors a raster's
 * cells in its layer's scheme; Curio hands it every raster layer with every
 * cell that has a value opaque (`withOpaqueRasters`), the base-map layers a map
 * lists after a raster as plain geometry, which autk-map then draws over it
 * (`withLayersOverRasters`), and once the map is
 * drawn, keeps linear sampling from drawing dark seams at the edges of the
 * cells with no data (`bleedRasterEdges`). Nothing in Autark is changed; the
 * grammar's data adapter, and that database's `getRaster` and `getLayer`, are
 * wrapped.
 *
 * A raster comes as GeoTIFF bytes: a Python node's rasterio dataset is asked
 * of the sandbox by its artifact (`/raster`; a standalone dashboard carries
 * that answer, see `fetchRaster`), and a collection an upstream Autark node
 * handed on is written back to GeoTIFF bytes here. Either way it is loaded at
 * its own size, with `nearest` resampling and its CRS (utils/raster/rasterLoad).
 */
import { fetchRaster } from '../../services/api';
import { writtenTables, type AutkRasterInput } from '../../utils/autkInput';
import { GRAMMAR_RASTER_SOURCES, autkTableKey, autkWorkspaceOf } from './autkDataCompile';
import { mapLayerRefs } from './autkViews';
import { writeGeoTiff } from '../../utils/raster/geotiffWriter';
import {
    RASTER_MAX_CELLS,
    RASTER_MAX_SIDE,
    oversizeSentence,
    planForGrid,
    planForMeta,
    type GeotiffLoad,
    type RasterMaker,
} from '../../utils/raster/rasterLoad';
import {
    decodeRasterEnvelope,
    rasterBandIds,
    type RasterBand,
    type RasterCollection,
    type RasterGrid,
} from '../../utils/raster/rasterWire';

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
    /** Its bands as they were made, labels included, which a GeoTIFF does not keep. */
    bands?: RasterBand[];
    /** The workspace it is loaded into, when it is not the default one. */
    workspace?: string;
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

/**
 * A raster collection with its grid as a source the grammar loads: written to
 * GeoTIFF bytes, loaded at its own size. Both the collection an upstream Autark
 * node handed on and a raster the node's own data section made (a heatmap, a
 * GeoTIFF) come here. Or the sentence that says why it cannot be drawn, and,
 * for one too large, how *madeBy*, what made it, makes it smaller.
 */
export function rasterSourceOf(
    name: string,
    collection: RasterCollection,
    madeBy: RasterMaker = 'node',
): CurioRasterSource | { refused: string } {
    const plan = planForGrid(name, collection.grid, madeBy);
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
        ...(Array.isArray(props.bands) ? { bands: props.bands } : {}),
    };
}

async function resolveOne(raster: AutkRasterInput): Promise<CurioRasterSource | { refused: string }> {
    const resolved = await resolveCells(raster);
    // It is loaded into the workspace it came from.
    return 'refused' in resolved || !raster.workspace ? resolved : { ...resolved, workspace: raster.workspace };
}

async function resolveCells(raster: AutkRasterInput): Promise<CurioRasterSource | { refused: string }> {
    const name = raster.outputTableName;
    const payload: any = raster.payload;
    if (payload && 'envelope' in payload) {
        const decoded = decodeRasterEnvelope(payload.envelope);
        if ('problem' in decoded) return { refused: `${name} cannot be drawn: ${decoded.problem}.` };
        return rasterSourceOf(name, decoded.collection);
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
            resolved.unusable.push(autkTableKey(autkWorkspaceOf(raster), raster.outputTableName));
            resolved.problems.push(result.refused);
        } else {
            resolved.sources.push(result);
        }
    }
    return resolved;
}

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

/** The rasters Curio loaded into a database, and the database's own reads it wraps. */
const SERVED_RASTERS = Symbol.for('curio.autk.servedRasters');

/** The workspace *db* works in, when it says and it is not the default one. */
function workspaceOfDb(db: any): string | undefined {
    return typeof db?.getCurrentWorkspace === 'function' ? autkWorkspaceOf({ workspace: db.getCurrentWorkspace() }) : undefined;
}

type ServedRasters = {
    /** Each raster Curio loaded, framed, by its key: its workspace and its table (`autkTableKey`). */
    rasters: Map<string, any>;
    /** The database's own `getRaster`, which reads a raster from its store. */
    getRaster: ((name: string, ...rest: any[]) => Promise<any>) | null;
};

/**
 * A raster as the database itself reads it: by its own `getRaster`, never an
 * answer `serveRaster` gives for it.
 */
function readRaster(db: any, table: string): Promise<any> {
    const served: ServedRasters | undefined = db[SERVED_RASTERS];
    if (served?.getRaster) return served.getRaster(table);
    return db.getRaster(table);
}

/**
 * Answer the grammar's reads of a raster Curio loaded, `getRaster` (how its
 * map reads a raster table) and `getLayer`, with the raster's own collection,
 * framed, as it was read right after loading. autk-db's `getLayer` gives a
 * raster the workspace's extent once any layer with geometry has set one,
 * which stretches the raster over that layer's extent instead, and its
 * `getRaster` reads a store the whole page shares (see `oneRasterAtATime`),
 * which can hold another node's raster of the same name by then. Every other
 * table is the database's to answer, as before. A raster is found in the
 * workspace it was loaded into, the one the database works in when it is
 * read, so two workspaces can hold rasters of one name.
 */
function serveRaster(db: any, table: string, collection: any, workspace?: string): void {
    let served: ServedRasters | undefined = db[SERVED_RASTERS];
    if (!served) {
        const rasters = new Map<string, any>();
        const getLayer = typeof db.getLayer === 'function' ? db.getLayer.bind(db) : null;
        const getRaster = typeof db.getRaster === 'function' ? db.getRaster.bind(db) : null;
        const servedAs = (name: string) => autkTableKey(workspaceOfDb(db), name);
        db.getLayer = async (name: string, ...rest: any[]) => {
            if (!rasters.has(servedAs(name))) {
                if (!getLayer) throw new Error(`Table ${name} not found.`);
                return getLayer(name, ...rest);
            }
            return rasters.get(servedAs(name));
        };
        db.getRaster = async (name: string, ...rest: any[]) => {
            if (!rasters.has(servedAs(name))) {
                if (!getRaster) throw new Error(`Table ${name} not found.`);
                return getRaster(name, ...rest);
            }
            return rasters.get(servedAs(name));
        };
        served = { rasters, getRaster };
        db[SERVED_RASTERS] = served;
    }
    served.rasters.set(autkTableKey(autkWorkspaceOf({ workspace }), table), framedRaster(collection));
}

/**
 * autk-db keeps a raster's cells in one store for the whole page, keyed by
 * workspace and table (`autk.input_0`), not by database. Every Autark node's
 * database starts in the workspace `autk`, and a node's input is `input_0`,
 * so two maps that load a raster at once each drew whichever loaded last. A
 * raster is loaded and read back here one at a time, and its node keeps what
 * it read. A heatmap or a GeoTIFF a node's data section makes in the browser
 * (autkLayerMaterialize) is made and read back here too.
 */
let rasterLoads: Promise<unknown> = Promise.resolve();

export function oneRasterAtATime<T>(load: () => Promise<T>): Promise<T> {
    const next = rasterLoads.then(load, load);
    rasterLoads = next.catch(() => undefined);
    return next;
}

/**
 * The page's raster turn, as one caller holds it: `held` when the caller runs
 * inside a turn it took (`runInRasterTurn`), so a raster load it makes
 * (`withRasterSources`) runs at once rather than wait for the turn its own
 * caller holds.
 */
export type RasterTurn = { held: boolean };

/**
 * Whether a run makes a raster after its passes: a source after compute
 * (*afterPasses*, autkDataCompile `sourcesAfterPasses`) of a kind that makes a
 * raster table, a heatmap or a GeoTIFF. autk-grammar makes it in its own run,
 * in autk-db's raster store, which the whole page shares (`oneRasterAtATime`),
 * and its map reads it when it draws.
 */
export function makesRasterAfterCompute(afterPasses: readonly any[]): boolean {
    return afterPasses.some((source) => GRAMMAR_RASTER_SOURCES.includes(source?.type));
}

/**
 * Run *grammar* on *spec*, holding the page's raster turn from the run's start
 * to its end when *turn* is held (`makesRasterAfterCompute`): another node's
 * raster load or run then waits, so no other raster of the same workspace and
 * name lands in the page's store between the run making its raster and its
 * map drawing it. Any other run takes no turn and runs as it is. *then* runs
 * as the run ends, in the same turn: a node reads back there the tables its
 * sources after compute made (autkHandOn `readBackAfterCompute`).
 */
export function runInRasterTurn(grammar: any, spec: any, turn: RasterTurn, then?: () => Promise<void>): Promise<void> {
    const run = async () => {
        await grammar.run(spec);
        if (then) await then();
    };
    return turn.held ? oneRasterAtATime(run) : run();
}

/** A data adapter of autk-grammar's, as far as it loads a source into the database it is handed. */
type SourceAdapter = { resolveSource(db: any, source: any): Promise<unknown> };

/**
 * *adapter*, autk-grammar's data adapter, loading `curio-raster` sources too:
 * each goes into the database the run goes on, by `loadGeoTiff`, and the map
 * is handed what `getRaster` read back. Any other source is *adapter*'s to
 * load, as before. A map node hands the grammar this adapter through
 * `wrapDataAdapter` (autk-grammar 5.6.0), inside the one that hands the run
 * the node's own database wherever it is given none (autkDbClose
 * `runDatabase`), so a raster that comes first goes into that database too.
 * Each raster goes into its workspace, the default one included, entered with
 * *enterWorkspace* (autk-grammar's, which the node passes) as the grammar's
 * data adapter enters a source's: the source before it can have left the
 * database in another. Each raster is loaded and read back in the page's
 * raster turn (`oneRasterAtATime`), unless *turn* says the grammar's run holds
 * it already (`runInRasterTurn`): then at once, since a load that waited for
 * that turn would wait on its own run.
 */
export function withRasterSources<A extends SourceAdapter>(
    adapter: A,
    enterWorkspace?: (db: any, workspace?: string) => Promise<void>,
    turn: RasterTurn = { held: false },
): A & SourceAdapter {
    return {
        ...adapter,
        async resolveSource(db: any, source: any) {
            if (!isCurioRasterSource(source)) return adapter.resolveSource(db, source);
            if (typeof db?.getRaster !== 'function') throw new Error(RASTER_EXPORT_MISSING);
            if (enterWorkspace) await enterWorkspace(db, source.workspace);
            const load = async () => {
                await db.loadGeoTiff(loadGeoTiffParams(source));
                return readRaster(db, source.outputTableName);
            };
            const collection = turn.held ? await load() : await oneRasterAtATime(load);
            serveRaster(db, source.outputTableName, withBandLabels(collection, source.bands), source.workspace);
            return db;
        },
    };
}

/**
 * *collection* with each band labelled as *bands* labels the band at its place.
 * `loadGeoTiff` labels a band by its id (`band_1`), and the GeoTIFF Curio writes
 * holds the bands in their order (`rasterSourceOf`), so a map's `getFnv` that
 * names a band by its label, as a heatmap's `count.noise` names `count_noise`,
 * finds it. Without *bands* it is the collection as read.
 */
export function withBandLabels(collection: any, bands: RasterBand[] | undefined): any {
    const [feature, ...rest] = collection?.features ?? [];
    const read: any[] = feature?.properties?.bands;
    if (!Array.isArray(bands) || bands.length === 0 || !Array.isArray(read)) return collection;
    const labelled = read.map((band, at) => (typeof bands[at]?.label === 'string' ? { ...band, label: bands[at].label } : band));
    return { ...collection, features: [{ ...feature, properties: { ...feature.properties, bands: labelled } }, ...rest] };
}

/**
 * How every raster layer is drawn, as SCOUT draws its tiles: each cell with a
 * value fully opaque, 0 included, and a cell with no data (NaN) clear, as
 * autk-map's transfer function. autk-map's own opacity grows with a cell's
 * distance from 0 (`far-zero`), so a 7 m building beside a 527 m tower was
 * drawn 1% opaque.
 */
const OPAQUE_CELLS = { opacityMin: 1, opacityMax: 1 };

/** A document's maps, a list of one map read as that map. */
function mapsOf(spec: any): any[] {
    return spec?.map ? (Array.isArray(spec.map) ? spec.map : [spec.map]) : [];
}

/**
 * The tables of *spec* that are rasters, by key (`autkTableKey`): those of its
 * data that are, Curio's own and the grammar's heatmaps and GeoTIFFs, and each
 * a compute pass writes as one, in the pass's workspace, by its `layerType` or
 * else by the type of the table it is computed from.
 */
export function rasterTables(spec: any): Set<string> {
    const sources: any[] = Array.isArray(spec?.data) ? spec.data : [];
    const rasters = new Set(sources
        .filter((source) => isCurioRasterSource(source) || GRAMMAR_RASTER_SOURCES.includes(source?.type))
        .filter((source) => typeof source.outputTableName === 'string')
        .map((source) => autkTableKey(autkWorkspaceOf(source), source.outputTableName)));
    for (const { name, from, layerType, workspace } of writtenTables(spec)) {
        const key = autkTableKey(workspace, name);
        if (layerType ? layerType === 'raster' : rasters.has(autkTableKey(workspace, from))) rasters.add(key);
        else rasters.delete(key);
    }
    return rasters;
}

/**
 * *spec* with autk-grammar's `transferFunction` on every layer that draws a
 * raster: `OPAQUE_CELLS`, under what the layer writes of it itself. The
 * grammar colors a raster's cells with it as it colors them in the layer's
 * scheme. A document that draws no raster is handed on as it is.
 */
export function withOpaqueRasters(spec: any): any {
    const rasters = rasterTables(spec);
    if (rasters.size === 0 || !spec?.map) return spec;
    let changed = false;
    const opaque = (mapSpec: any) => {
        if (!Array.isArray(mapSpec?.layerRefs)) return mapSpec;
        // A layer draws a table of its map's workspace.
        const layerRefs = mapSpec.layerRefs.map((ref: any) => {
            if (typeof ref?.dataRef !== 'string' || !rasters.has(autkTableKey(autkWorkspaceOf(mapSpec), ref.dataRef))) return ref;
            changed = true;
            const own = ref.transferFunction && typeof ref.transferFunction === 'object' ? ref.transferFunction : {};
            return { ...ref, transferFunction: { ...OPAQUE_CELLS, ...own } };
        });
        return { ...mapSpec, layerRefs };
    };
    const map = Array.isArray(spec.map) ? spec.map.map(opaque) : opaque(spec.map);
    return changed ? { ...spec, map } : spec;
}

/**
 * The layer types autk-map draws in places of their own under every other
 * layer, whatever the order a map lists its layers in: the base map's, which
 * its LayerManager sorts first (surface, parks, water, roads). Every other
 * type, a raster included, comes after them, in the order the map adds them.
 * Buildings, which stand up from the ground, keep their type.
 */
const BASE_MAP_TYPES: ReadonlySet<string> = new Set(['surface', 'parks', 'water', 'roads']);

/**
 * *spec* with each table of a base-map type a map draws after a raster handed
 * to the grammar as the plain geometry it is: loaded with no `layerType`, so
 * autk-db types it by its geometry (polygons, polylines, points) and autk-map
 * draws it in the map's order, over the raster. Every raster cell is drawn
 * opaque (withOpaqueRasters), and autk-map would draw a base-map layer under
 * every raster whatever the map's order, so a GeoTIFF hid the parks and roads
 * a map listed after it. A table drawn before every raster of its map, or by
 * no map, keeps its type, and a document that draws no raster is handed on as
 * it is.
 */
export function withLayersOverRasters(spec: any): any {
    const rasters = rasterTables(spec);
    if (rasters.size === 0 || !Array.isArray(spec?.data)) return spec;
    const over = new Set<string>();
    for (const mapSpec of mapsOf(spec)) {
        // A layer draws a table of its map's workspace.
        const workspace = autkWorkspaceOf(mapSpec);
        let afterRaster = false;
        for (const ref of Array.isArray(mapSpec?.layerRefs) ? mapSpec.layerRefs : []) {
            if (typeof ref?.dataRef !== 'string') continue;
            const key = autkTableKey(workspace, ref.dataRef);
            if (rasters.has(key)) afterRaster = true;
            else if (afterRaster) over.add(key);
        }
    }
    let changed = false;
    const data = spec.data.map((source: any) => {
        if (!BASE_MAP_TYPES.has(source?.layerType)
            || !over.has(autkTableKey(autkWorkspaceOf(source), source.outputTableName))) return source;
        changed = true;
        const { layerType: _type, ...plain } = source;
        return plain;
    });
    return changed ? { ...spec, data } : spec;
}

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
 * Give the clear cells of every raster each map drew their nearest colored
 * neighbor's color (`bleedIntoClearCells`), once the grammar has run. The
 * grammar's lookup (`mapLayers`) finds the layers each map drew for a table,
 * on that map alone (by its index, `autkViews`), and each layer of the
 * document is the one of its own id there, its title if it has one; a layer
 * that is not a raster is left as drawn. The cells are written in place,
 * which autk-map cannot see, so the layer is marked for the GPU
 * (`makeLayerDataDirty`) and its map, which draws on demand
 * (`autkMapDrawing`), is asked for a frame.
 */
export function bleedRasterEdges(grammar: any, spec: any): void {
    if (typeof grammar?.mapLayers !== 'function') return;
    for (const { index, ref } of mapLayerRefs(spec)) {
        if (typeof ref?.dataRef !== 'string') continue;
        const layerId = typeof ref.title === 'string' && ref.title !== '' ? ref.title : ref.dataRef;
        const found = (grammar.mapLayers(ref.dataRef, index) as Array<{ map: any; layerId: string }>)
            .find((drawn) => drawn.layerId === layerId);
        const layer = found?.map?.layerManager?.searchByLayerId?.(found.layerId);
        if (layer?.layerInfo?.typeLayer !== 'raster') continue;
        const rgba = layer.rasterData;
        if (!(rgba instanceof Float32Array) || !(layer.rasterResX > 0) || !(layer.rasterResY > 0)) continue;
        bleedIntoClearCells(rgba, layer.rasterResX, layer.rasterResY);
        layer.makeLayerDataDirty?.();
        found!.map.requestRender?.();
    }
}
