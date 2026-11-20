// Where an Autark node's layers are loaded and handed on: the data section run
// in the backend sandbox, its DuckDB artifact read back as layers, the
// in-browser AutkDb fallback, and the wrapper a downstream Data Pool reads.
// Used by the node behavior (autkGrammarBehavior.tsx).
//
// A raster table the data section makes (a heatmap, a GeoTIFF) comes back from
// both loaders beside the layers as `{name, type: 'raster', geojson}`, its `geojson`
// autk-db's `getRaster` collection with the grid its cells lie on
// (withRasterGrid), and is handed on in its envelope (rasterEnvelope).

import type { FeatureCollection } from 'geojson';
import { fetchData } from '../../services/api';
import { askedOfPage, keepPageResult } from '../../services/runs/dashboardRunSteps';
import { NodeType } from '../../constants';
import type { JavaScriptInterpreter } from '../../JavaScriptInterpreter';
import { detectCoordinateFormat } from '../../utils/geoCrs';
import { withExtensionRetry } from './duckdbExtensionRetry';
import { closeAutkDb } from './autkDbClose';
import { autkKeyProblem } from '../../contracts/autkGrammar';
import { autkTableName } from '../../utils/autkInput';
import { framesFromPayload } from '../../utils/grammarInput';
import { deriveBuildingHeight } from '../../utils/buildingHeight';
import { decodeRasterEnvelope } from '../../utils/raster/rasterWire';
import {
    GRAMMAR_RASTER_SOURCES,
    MADE_HEIGHT,
    PLAIN_TABLE_SOURCES,
    autkTableKey,
    autkUsesWorkspaces,
    autkWorkspaceOf,
    handedOn,
    inItsWorkspace,
    layerEpsg,
    plainTableRecord,
    rasterEnvelope,
    requestedLayerTables,
    sectionChangedTables,
    sectionInputTables,
    sectionTableProblem,
    withInputTables,
    withOsmIds,
    withRasterGrid,
    workspaceCrsOf,
} from './autkDataCompile';
import { oneRasterAtATime } from './autkRasters';
import { featureCount } from './autkRunDescriptions';

/** A table an Autark node loaded or hands on: its name, its autk-db layer type, its
 * rows, and the workspace it is in when that is not the default one. */
export type AutkLayer = { name: string; type?: string; geojson: any; workspace?: string };

/** autk-db's layer type for a raster table, which both loaders hand on beside the layers. */
export const RASTER_TABLE = 'raster';

/** A loaded table's rows: a layer's features, a raster's cells. */
export function loadedRows(table: { type?: string; geojson: any }): number | undefined {
    if (table.type !== RASTER_TABLE) return featureCount(table.geojson);
    const cells = Number(table.geojson?.grid?.width) * Number(table.geojson?.grid?.height);
    return Number.isFinite(cells) ? cells : undefined;
}

// Message for a load that produced layers, but not the ones the spec asked for.
// Shared by both loaders so the two paths report a short load identically.
//
// `errors` is what makes this safe to throw on rather than merely warn about:
// autk-db propagates rather than swallows, so a table missing *because the load
// broke* always arrives with a caught reason, while a sparse-but-successful
// query area does not (`loadOsmLayer` creates the table even at zero features,
// and autk-db counts rows on it immediately after). Missing with no recorded
// error is therefore a warning, not a failure.
function missingLayerMessage(missing: string[], errors: string[]): string {
    return `autk data load produced ${missing.length} fewer table(s) than the spec asked for`
        + ` - missing: ${missing.join(', ')}`
        + (errors.length > 0 ? ` (${errors.join('; ')})` : '');
}

// Message for a `join` source that failed. A join rewrites a table another
// source created, so a failed one never leaves a table missing and the check
// above cannot see it: regression.json's join died with a Binder Error on every
// run while its node reported Done (#319). Shared by both loaders.
function joinFailureMessage(errors: string[]): string {
    return `spatial join failed - ${errors.join('; ')}`;
}

// Run the compiled autk-db loader in the backend sandbox and resolve to the
// DuckDB artifact reference ({path, dataType}) the sandbox returns. Wraps the
// callback-based JavaScriptInterpreter in a Promise. The data spec is inlined in
// the code. *input* is the node's input, sent only for a data section that reads
// tables of it (sectionInputTables), which its code finds in what the sandbox
// gives the run; no circles are named, so the sandbox gives each input under
// its place among the node's inputs, `input_0`, `input_1`, ..., the names the
// node reads them by. Else it is '', and the sandbox loads no input.
function runDataInBackendOnce(
    jsInterpreter: JavaScriptInterpreter,
    code: string,
    nodeId: string,
    input: any,
): Promise<{ path: string; dataType: string }> {
    return new Promise((resolve, reject) => {
        jsInterpreter.interpretCode(
            code,            // unresolvedUserCode (provenance only)
            code,            // userCode — runs in the sandbox
            input,           // input: the node's, or '' for a section that reads none of it
            [],              // inputTypes
            (json: any) => { // callback
                if (!json || !json.output || !json.output.path) {
                    reject(new Error(json?.stderr || 'Backend data load returned no output.'));
                    return;
                }
                resolve(json.output);
            },
            NodeType.AUTK_GRAMMAR,
            nodeId,
            '',              // workflow_name (best-effort)
            () => {},        // nodeExecProv: a part of the node's run, which applyGrammar lists once
        );
    });
}

// The authored OSM/PBF (and other file) sources are local and deterministic, so
// a failed attempt is a transient hiccup — sandbox cold-start, a dropped /file/
// range fetch under thread contention, a momentary connection reset — not a
// real data error. Retry once before giving up: the caller only falls back to
// the in-browser loader (markedly less reliable in a headless browser, where a
// failed PBF fetch crashes autk-db rather than degrading), so absorbing a
// transient failure here keeps the deterministic backend path in control.
// Re-throws the LAST failure so the caller can surface its reason.
export async function runDataInBackend(
    jsInterpreter: JavaScriptInterpreter,
    code: string,
    nodeId: string,
    input: any = '',
    attempts = 2,
): Promise<{ path: string; dataType: string }> {
    let lastErr: any;
    for (let attempt = 1; attempt <= attempts; attempt++) {
        try {
            return await runDataInBackendOnce(jsInterpreter, code, nodeId, input);
        } catch (e: any) {
            lastErr = e;
            if (attempt < attempts) {
                console.warn(
                    `[autk-grammar] backend data load attempt ${attempt}/${attempts} `
                    + `failed; retrying:`,
                    e?.message ?? e,
                );
            }
        }
    }
    throw lastErr ?? new Error('Backend data load failed.');
}

// Resolve the backend data load into in-browser layers for the render path:
// the in-memory fallback layers if present, otherwise fetch + normalize the
// DuckDB artifact (framesFromPayload unwraps it, as it does an input). Each
// layer keeps the workspace it was loaded into, and a raster table in it is read
// back from its envelope as its collection with its grid, in its workspace too.
export async function materializeBackendLayers(
    fallbackLayers: AutkLayer[] | null,
    ref: { path: string; dataType: string } | null,
): Promise<AutkLayer[]> {
    if (fallbackLayers) return fallbackLayers;
    if (!ref) return [];
    const fetched = await fetchData(ref.path);
    const frames = framesFromPayload(fetched, { rasters: true }).frames;
    const layers = frames
        .filter((frame) => frame.dataType === 'geodataframe')
        .map((frame) => ({
            name: autkTableName(frame),
            type: frame.layerType,
            geojson: frame.payload,
            ...(frame.workspace ? { workspace: frame.workspace } : {}),
        }));
    const rasters = frames
        .filter((frame) => frame.dataType === 'raster' && 'envelope' in frame.payload)
        .map((frame) => {
            const decoded = decodeRasterEnvelope(frame.payload.envelope);
            if ('problem' in decoded) throw new Error(`${autkTableName(frame)} cannot be drawn: ${decoded.problem}.`);
            return {
                name: autkTableName(frame),
                type: RASTER_TABLE,
                geojson: decoded.collection,
                ...(frame.workspace ? { workspace: frame.workspace } : {}),
            };
        });
    return [...layers, ...rasters];
}

// Flatten any (possibly nested) geometry into a single MultiPolygon by collecting
// every Polygon ring set it contains. Returns null if it has no polygonal parts.
function flattenToMultiPolygon(geom: any): any | null {
    const polys: any[] = [];
    const collect = (g: any) => {
        if (!g) return;
        if (g.type === 'Polygon') polys.push(g.coordinates);
        else if (g.type === 'MultiPolygon') polys.push(...g.coordinates);
        else if (g.type === 'GeometryCollection') (g.geometries || []).forEach(collect);
    };
    collect(geom);
    return polys.length > 0 ? { type: 'MultiPolygon', coordinates: polys } : null;
}

// Explode autk-db's grouped building features into one footprint feature per part.
// autk-db keeps a building as one feature: a GeometryCollection of its parts, each
// part's tags in `properties.parts` naming its geometry by `geometryIndex`. An
// Autark node hands buildings on one row per part (#536), a Polygon (or
// MultiPolygon) with that part's tags and height: a table lists every part, Edit
// Features removes a building by `building_id`, and a batched compute packs each
// part's `geometry.coordinates.0`, a Polygon's outer ring. The downstream
// `loadGeojson('buildings')` makes every row a building of its own, so each part
// also carries, as a property, the `building_id` it came from. A part's
// `geometryIndex` is autk-db's bookkeeping, not a tag, and is left out, and so is
// its `id`, which the part carries as its `osm_id` (withOsmIds). A part with no
// height gets the one `deriveBuildingHeight` gives it, and names it beside its
// properties (`MADE_HEIGHT`), so a map layer with `buildingsZeroHeight` can take
// it back.
function explodeBuildingParts(features: any[]): any[] {
    const out: any[] = [];
    for (const f of features ?? []) {
        const geom = f?.geometry;
        const props = f?.properties ?? {};
        const partMeta = new Map<number, any>();
        for (const part of Array.isArray(props.parts) ? props.parts : []) {
            if (!part || typeof part !== 'object') continue;
            const { id: _id, geometryIndex, ...tags } = part;
            partMeta.set(geometryIndex, tags);
        }
        const pushPart = (g: any, meta: any) => {
            if (!g) return;
            const gg = g.type === 'GeometryCollection' ? flattenToMultiPolygon(g) : g;
            if (!gg) return;
            const p = { ...(meta ?? {}) };
            delete p.parts;
            if (props.building_id != null) p.building_id = props.building_id;
            const h = deriveBuildingHeight(p);
            if (h != null) p.height = h;
            out.push(h != null
                ? { type: 'Feature', geometry: gg, properties: p, [MADE_HEIGHT]: h }
                : { type: 'Feature', geometry: gg, properties: p });
        };
        if (geom?.type === 'GeometryCollection' && Array.isArray(geom.geometries)) {
            geom.geometries.forEach((g: any, i: number) => pushPart(g, partMeta.get(i) ?? props));
        } else if (geom) {
            pushPart(geom, props);
        }
    }
    return out;
}

// A raster table a data section makes (a heatmap, a GeoTIFF), as the sandbox's
// loader makes and reads it (compileDataSpecToAutkDbJs): made by the grammar's
// data adapter (*adapter*'s `resolveSource`), then its raster table read back
// at once, in the workspace it was made in, with the grid its cells lie on.
// autk-db keeps a raster's cells in one store for the whole page, so the
// making and the read are one raster at a time (oneRasterAtATime). A raster
// in another workspace than the default one keeps it.
async function grammarRaster(
    db: any,
    source: any,
    adapter: { resolveSource: (db: any, source: any) => Promise<unknown> },
): Promise<{ name: string; type: string; geojson: any; workspace?: string }> {
    const name = source.outputTableName;
    const collection = await oneRasterAtATime(async () => {
        await adapter.resolveSource(db, source);
        return db.getRaster(name);
    });
    const crs = db.getWorkspaceConfiguration().coordinateFormat;
    return {
        name,
        type: RASTER_TABLE,
        geojson: withRasterGrid(collection, crs),
        ...(source.workspace ? { workspace: source.workspace } : {}),
    };
}

// The source types whose failure leaves no table missing: each changes or
// drops a table another source made. The load fails on any of their errors.
const CHANGING_SOURCES = ['join', 'update', 'drop'];

// Load a data-only grammar spec's sources with autk-grammar's own data adapter
// (from its `./data` entry), as the grammar's run loads them and as the
// sandbox's loader does (compileDataSpecToAutkDbJs), and return the resulting
// layers, then the tables with no geometry as their rows, then the raster
// tables it makes (a heatmap, a GeoTIFF), so a grammar node can export its
// parsed data downstream. (The grammar engine itself never exposes the loaded
// DB, so this drives the adapter on a database of its own.) The document's
// `workspaces` are set up first (`resolveWorkspaces`); then each source loads
// (`resolveSource`) into its workspace, which the adapter enters as the
// grammar's run does, and each layer comes back with the workspace it is in
// when that is not the default one, in that workspace's CRS. Sources that
// write a key autk-grammar 5 renamed, or one a node does not run yet
// (contracts/autkGrammar), load nothing: the load fails, naming the key. The
// tables of the node's input the section's heatmaps, joins, updates and drops
// read (sectionInputTables) come from *input*, the node's input as it reads it
// (utils/autkInput `autkSourcesFrom`), found by key: each loads just before the
// first entry that reads it, one the input does not carry fails the load
// before anything loads, and none comes back unless a join wrote its columns
// onto it or an update changed it (handedOn), as in the sandbox's loader. An
// OpenStreetMap table a view of the node reads with `osmElements`
// (*options.elements*, by key) is read as one feature per OpenStreetMap element.
export async function loadSpecLayers(
    spec: any,
    input: ReadonlyArray<{
        outputTableName: string; workspace?: string; geojsonObject: any; coordinateFormat?: string; layerType?: string;
    }> = [],
    options: { elements?: string[] } = {},
): Promise<Array<{ name: string; type: string; geojson: FeatureCollection; workspace?: string }>> {
    const keyProblem = autkKeyProblem({ data: spec?.data });
    if (keyProblem) throw new Error(keyProblem);
    const tableProblem = sectionTableProblem(spec?.data ?? []);
    if (tableProblem) throw new Error(tableProblem);
    const authored: any[] = (spec?.data ?? []).map(inItsWorkspace);
    const wanted = sectionInputTables(authored);
    const inputKeys = wanted.map((table) => autkTableKey(table.workspace, table.name));
    const changed = sectionChangedTables(authored);
    const carried = wanted.map((table, at) => {
        const found = input.find((source) => autkTableKey(autkWorkspaceOf(source), source.outputTableName) === inputKeys[at]);
        if (!found) throw new Error(table.missing);
        return {
            before: table.before,
            source: {
                type: 'geojson',
                outputTableName: table.name,
                geojsonObject: found.geojsonObject,
                coordinateFormat: found.coordinateFormat ?? detectCoordinateFormat(found.geojsonObject),
                ...(found.layerType ? { layerType: found.layerType } : {}),
                ...(table.workspace ? { workspace: table.workspace } : {}),
            },
        };
    });
    const sources: any[] = withInputTables(authored, carried);
    // The document's workspaces, and the CRS each keeps its tables in.
    const workspaces = Array.isArray(spec?.workspaces) && spec.workspaces.length > 0 ? spec.workspaces : null;
    const crsOf = workspaceCrsOf(workspaces);
    const elements = options.elements ?? [];
    // autk-grammar's data entry, as the sandbox's code imports it: its data
    // adapter, and `enterWorkspace` to read back the tables of each workspace a
    // section names (autkUsesWorkspaces). A section that names no workspace
    // has its tables in the default one, where the adapter leaves the database.
    const usesWorkspaces = autkUsesWorkspaces({ data: sources });
    const [{ AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT }, grammarData] = await Promise.all([
        import('@urban-toolkit/autk-db'),
        import('@urban-toolkit/autk-grammar/data'),
    ]);
    const enterWorkspace = usesWorkspaces
        ? grammarData.enterWorkspace
        : async (_db: unknown, _workspace?: string) => undefined;
    const adapter = grammarData.createDataAdapter();
    // `init()` downloads the DuckDB spatial extension; a flaky fetch is worth
    // another instance rather than a failed node (#318).
    const db: any = await withExtensionRetry(async () => {
        const instance: any = new AutkDb();
        try {
            await instance.init();
        } catch (err) {
            // A failed attempt ends its own database (autkDbClose).
            closeAutkDb(instance);
            throw err;
        }
        return instance;
    });
    // A workspace autk-db refuses fails the load before any source loads.
    if (workspaces) {
        try {
            await adapter.resolveWorkspaces(db, workspaces);
        } catch (err) {
            closeAutkDb(db);
            throw err;
        }
    }
    // Reasons individual sources / reads failed, surfaced below when the load
    // produced no usable layer at all — so a total failure reports WHY instead
    // of crashing later with an opaque "Cannot read properties of null".
    const loadErrors: string[] = [];
    const joinErrors: string[] = [];
    const changeErrors: string[] = [];
    // The raster tables the data section made, read as they were made.
    const rasters: Array<{ name: string; type: string; geojson: any; workspace?: string }> = [];
    for (const source of sources) {
        const { type } = source ?? {};
        try {
            if (GRAMMAR_RASTER_SOURCES.includes(type)) rasters.push(await grammarRaster(db, source, adapter));
            else await adapter.resolveSource(db, source);
        } catch (e) {
            // Record + skip a source that fails to load; others may still
            // produce layers. The recorded reason is surfaced below if the load
            // produced nothing at all, or left a table it asked for missing; a
            // source that changes a table fails the load.
            const reason = (e as any)?.message || String(e);
            loadErrors.push(`${type}: ${reason}`);
            if (type === 'join') joinErrors.push(reason);
            else if (CHANGING_SOURCES.includes(type)) changeErrors.push(reason);
            console.warn(`[autk-grammar] data-only load failed for source type "${type}"`, e);
        }
    }
    // Tag each layer with the CRS its coordinates are ACTUALLY in (layerEpsg),
    // so a downstream grammar node injects it with the right coordinateFormat:
    // a wrong tag makes the renderer read degree values as meters near the
    // origin, a silently blank map. autk-db lists and reads the tables of the
    // current workspace only, so each workspace the sources load into is
    // entered in turn, in their order, and its tables are read before the next
    // is entered.
    const workspacesOfSources = [...new Set(sources.map((source) => source?.workspace as string | undefined))];
    const layers: Array<{ name: string; type: string; geojson: FeatureCollection; workspace?: string } | null> = [];
    for (const workspace of workspacesOfSources) {
        let tables: Array<{ name: string; type?: string; source?: string }> = [];
        try {
            await enterWorkspace(db, workspace);
            tables = (db.getLayersMetadata() as Array<{ name: string; type?: string; source?: string }>)
                .filter((t) => handedOn(autkTableKey(workspace, t.name), inputKeys, changed));
        } catch (e) {
            // A partially-loaded DB can throw here (rather than return []). Treat it
            // as "no usable tables" and let the empty-result guard below report it,
            // instead of letting an opaque TypeError escape the loader.
            loadErrors.push(`getLayersMetadata: ${(e as any)?.message ?? String(e)}`);
        }
        layers.push(...await Promise.all(
            tables.map(async (t) => {
                try {
                    // An OpenStreetMap table a view reads as elements: one feature per element.
                    const geojson = (elements.includes(autkTableKey(workspace, t.name))
                        ? await db.getLayer(t.name, { osmElements: true })
                        : await db.getLayer(t.name)) as any;
                    // Keep the autk-db layer type ('roads', 'surface', 'water', 'parks',
                    // 'buildings', …) so a downstream grammar node re-loads it with the
                    // right rendering.
                    const type = (t.type as string) ?? 'polygons';
                    // Each OpenStreetMap feature's OSM id in `osm_id`, a building
                    // part's in that part, as the sandbox's loader hands them on.
                    if (Array.isArray(geojson?.features)) geojson.features = withOsmIds(t, geojson.features);
                    // Buildings: explode the grouped GeometryCollection into one footprint
                    // feature per part (each with its own height) and KEEP type 'buildings',
                    // so autk-map extrudes each part by its real height. See
                    // explodeBuildingParts.
                    if (type === 'buildings' && Array.isArray(geojson?.features)) {
                        geojson.features = explodeBuildingParts(geojson.features);
                    }
                    if (geojson && typeof geojson === 'object') {
                        const epsg = layerEpsg(geojson, workspace, crsOf, DEFAULT_WORKSPACE_COORDINATE_FORMAT);
                        geojson.crs = { type: 'name', properties: { name: `urn:ogc:def:crs:EPSG::${epsg}` } };
                    }
                    return {
                        name: t.name, type, geojson: geojson as FeatureCollection,
                        ...(workspace === undefined ? {} : { workspace }),
                    };
                } catch (e) {
                    loadErrors.push(`getLayer(${t.name}): ${(e as any)?.message ?? String(e)}`);
                    return null;
                }
            }),
        ));
    }
    // The section's own CSV, JSON and SQL tables that autk-db made with no
    // geometry, which the loop above passes over: each as its rows, with no
    // layer type.
    const read = new Set(layers.flatMap((l) => (l ? [autkTableKey(l.workspace, l.name)] : [])));
    const plain = await plainTables(db, authored, read, enterWorkspace, loadErrors);
    // Every layer is read: nothing below asks the database again (autkDbClose).
    closeAutkDb(db);
    const usable = [
        ...layers.filter(
            (l): l is { name: string; type: string; geojson: FeatureCollection; workspace?: string } => l != null,
        ),
        ...(plain as any[]),
        ...rasters,
    ];
    // Same contract check as the sandbox emit: a load that came back short is a
    // failure, not a success with fewer layers. Without this, the caller's
    // "backend failed, fall back in-browser" path would quietly publish the same
    // short layer array the backend path just refused to.
    //
    // Diffed against `usable` - what a consumer actually receives. A layer that
    // was never created and one that exists but could not be exported are the
    // same loss downstream: the array comes back short either way. An empty
    // layer is NOT caught by this, because getLayer returns an empty
    // FeatureCollection for it and it stays in `usable`; only a getLayer that
    // throws counts, and that is a defect rather than sparse data.
    const requested = requestedLayerTables(authored);
    if (requested.length > 0) {
        const have = new Set(usable.map((l) => autkTableKey(l.workspace, l.name)));
        const missing = requested.filter((n) => !have.has(n));
        if (missing.length > 0) {
            if (loadErrors.length > 0) {
                throw new Error(missingLayerMessage(missing, loadErrors));
            }
            console.warn(`[autk-grammar] ${missingLayerMessage(missing, [])} - no load `
                + `error recorded, treating as a genuinely empty query area`);
        }
    }
    if (joinErrors.length > 0) throw new Error(joinFailureMessage(joinErrors));
    // An update or a drop that failed fails the load, in the grammar's words.
    if (changeErrors.length > 0) throw new Error(changeErrors.join('; '));
    // A load that asked for sources but produced no usable layer AND hit errors
    // is a real failure (e.g. every PBF range fetch 404'd) — throw an ATTRIBUTED
    // error so the node reports the reason, instead of crashing later with an
    // opaque "Cannot read properties of null (reading 'length')" or silently
    // emitting an empty layer set. A genuinely empty area (no errors) returns [].
    if (
        usable.length === 0
        && loadErrors.length > 0
        && Array.isArray(spec?.data) && spec.data.length > 0
    ) {
        throw new Error(`in-browser AutkDb load produced no layers (${loadErrors.join('; ')})`);
    }
    return usable;
}

/**
 * The tables a data section's own CSV, JSON and SQL *sources* made with no
 * geometry, which autk-db lists as no layer, in their sources' order, each read
 * in its source's workspace (*enterWorkspace*) as the load left it and as both
 * loaders hand it on (plainTableRecord). A table that is a layer, among the
 * layers *read* already by its key, is left to them, and one a drop dropped is
 * gone; one that cannot be read is a load error. The sandbox's loader reads
 * them the same way (autkDataCompile's plainTablesCode).
 */
async function plainTables(
    db: any,
    sources: any[],
    read: ReadonlySet<string>,
    enterWorkspace: (db: any, workspace?: string) => Promise<void>,
    loadErrors: string[],
): Promise<AutkLayer[]> {
    const plain: AutkLayer[] = [];
    for (const source of sources) {
        const { type, workspace, outputTableName } = source ?? {};
        if (!PLAIN_TABLE_SOURCES.includes(type) || !outputTableName || read.has(autkTableKey(workspace, outputTableName))) continue;
        try {
            await enterWorkspace(db, workspace);
            const table = (db.getTablesMetadata() as Array<{ name: string; type?: string }>)
                .find((t) => t.name === outputTableName);
            if (!table || table.type !== undefined) continue;
            plain.push(plainTableRecord(outputTableName, await db.getTable(outputTableName), workspace));
        } catch (e) {
            loadErrors.push(`${type}: ${(e as any)?.message ?? String(e)}`);
        }
    }
    return plain;
}

// Persist a pool-compatible wrapper (output of `layersToPoolWrapper`) to the
// backend sandbox so a downstream Data Pool can ingest it via its normal
// `{path, dataType}` fetch path — the same convention `ia-data` uses. The
// augmented FC was computed in the browser (WGSL needs a GPU); this just
// ships the result to the backend for persistence, so every downstream node
// sees a DuckDB artifact reference instead of an inline payload.
function persistLayersToBackend(
    jsInterpreter: JavaScriptInterpreter,
    wrapper: any,
    nodeId: string,
): Promise<{ path: string; dataType: string }> {
    // The sandbox JS just inlines the wrapper as a literal and returns it; the
    // sandbox wraps return values into a `{path, dataType}` artifact ref.
    const code = `const __wrapper = ${JSON.stringify(wrapper)};\nreturn __wrapper;`;
    return new Promise((resolve, reject) => {
        jsInterpreter.interpretCode(
            code, code, '', [],
            (json: any) => {
                if (!json || !json.output || !json.output.path) {
                    reject(new Error(json?.stderr || 'Backend persist returned no path.'));
                    return;
                }
                resolve(json.output);
            },
            NodeType.AUTK_GRAMMAR,
            nodeId, '', () => {}, // nodeExecProv: a part of the node's run, which applyGrammar lists once
        );
    });
}

// Hand layers downstream in a shape the Data Pool can read: the pool-compatible
// wrapper, persisted to the backend sandbox so downstream nodes see a
// `{path, dataType}` ref — same shape `ia-data` emits, so the Data Pool's normal
// fetch path handles it without a special case. Falls back to the inline
// wrapper when no JS interpreter is available or the persist call fails, and
// to null when there are no layers to wrap. A step a dashboard viewer's run
// left to this page goes to that run instead, which keeps it for this page
// (#1117): a viewer has no session to persist it with.
export async function toPoolOutput(
    layers: AutkLayer[],
    jsInterpreter: JavaScriptInterpreter | undefined,
    nodeId: string,
): Promise<any> {
    const wrapper = layersToPoolWrapper(layers);
    if (wrapper && askedOfPage(nodeId)) return keepPageResult(nodeId, wrapper);
    if (wrapper && jsInterpreter) {
        try {
            return await persistLayersToBackend(jsInterpreter, wrapper, nodeId);
        } catch (e) {
            console.warn('[autk-grammar] backend persist failed; emitting inline wrapper', e);
        }
    }
    return wrapper;
}

// Convert an autk-db-style layer array into a Curio Data Pool-compatible wrapper.
// The pool's `processDataAsync` recognizes `dataType: 'geodataframe'` (single layer)
// and `dataType: 'outputs'` (multi-layer envelope) — but not bare layer arrays. So
// when a compute-only or data-only autk-grammar node feeds a Data Pool, we wrap
// the output in a shape the pool can ingest, carrying `layerName`/`layerType`
// metadata at the wrapper level so a downstream Autark node's input can restore
// the original layer identity (e.g. `dataRef: "table_osm_buildings"`). A raster
// table goes in its envelope (rasterEnvelope), as the sandbox's loader hands it
// on. A layer or a raster in another workspace than the default one names it
// (`workspace`), so the node it is handed to loads it there.
export function layersToPoolWrapper(layers: AutkLayer[]): any {
    if (!Array.isArray(layers) || layers.length === 0) return null;
    const envelope = (l: AutkLayer) => ({
        ...(l.type === RASTER_TABLE
            ? rasterEnvelope(l.geojson, l.name)
            : { dataType: 'geodataframe', data: l.geojson, layerName: l.name, layerType: l.type }),
        ...(l.workspace ? { workspace: l.workspace } : {}),
    });
    if (layers.length === 1) return envelope(layers[0]);
    return { dataType: 'outputs', data: layers.map(envelope) };
}
