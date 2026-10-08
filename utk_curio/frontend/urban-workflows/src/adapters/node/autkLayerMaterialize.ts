// Where an Autark node's layers are loaded and handed on: the data section run
// in the backend sandbox, its DuckDB artifact read back as layers, the
// in-browser AutkDb fallback, and the wrapper a downstream Data Pool reads.
// Used by the node behavior (autkGrammarBehavior.tsx).

import type { FeatureCollection } from 'geojson';
import { fetchData } from '../../services/api';
import { NodeType } from '../../constants';
import type { JavaScriptInterpreter } from '../../JavaScriptInterpreter';
import { detectCoordinateFormat } from '../../utils/geoCrs';
import { withExtensionRetry } from './duckdbExtensionRetry';
import { autkTableName } from '../../utils/autkInput';
import { framesFromPayload } from '../../utils/grammarInput';
import { deriveBuildingHeight } from '../../utils/buildingHeight';
import { requestedLayerTables } from './autkDataCompile';

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
// above cannot see it: Regression.json's join died with a Binder Error on every
// run while its node reported Done (#319). Shared by both loaders.
function joinFailureMessage(errors: string[]): string {
    return `spatial join failed - ${errors.join('; ')}`;
}

// Run the compiled autk-db loader in the backend sandbox and resolve to the
// DuckDB artifact reference ({path, dataType}) the sandbox returns. Wraps the
// callback-based JavaScriptInterpreter in a Promise. No DuckDB input is loaded
// (input is ''); the data spec is inlined in the code, so the wrapper binds
// no input_k.
function runDataInBackendOnce(
    jsInterpreter: JavaScriptInterpreter,
    code: string,
    nodeId: string,
): Promise<{ path: string; dataType: string }> {
    return new Promise((resolve, reject) => {
        jsInterpreter.interpretCode(
            code,            // unresolvedUserCode (provenance only)
            code,            // userCode — runs in the sandbox
            '',              // input — empty: spec is inlined, no DuckDB input
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
            () => {},        // nodeExecProv — no provenance hook here
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
    attempts = 2,
): Promise<{ path: string; dataType: string }> {
    let lastErr: any;
    for (let attempt = 1; attempt <= attempts; attempt++) {
        try {
            return await runDataInBackendOnce(jsInterpreter, code, nodeId);
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
// DuckDB artifact (framesFromPayload unwraps it, as it does an input).
export async function materializeBackendLayers(
    fallbackLayers: Array<{ name: string; type?: string; geojson: any }> | null,
    ref: { path: string; dataType: string } | null,
): Promise<Array<{ name: string; type?: string; geojson: any }>> {
    if (fallbackLayers) return fallbackLayers;
    if (!ref) return [];
    const fetched = await fetchData(ref.path);
    return framesFromPayload(fetched).frames
        .filter((frame) => frame.dataType === 'geodataframe')
        .map((frame) => ({ name: autkTableName(frame), type: frame.layerType, geojson: frame.payload }));
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
// autk-db's 3D building model — per-part polygons keyed by `building_id`, each with
// its own height, which `getLayer` exports as a GeometryCollection with a parallel
// `properties.parts` metadata array — is a `loadOsm` construct that `loadGeojson`
// cannot rebuild from the grouped GeometryCollection. Splitting each building back
// into its individual part footprints (each carrying that part's height) lets
// autk-map extrude each part by its own height instead of collapsing the whole
// building into one box. The downstream `loadGeojson('buildings')` numbers every
// row as its own building, so each part also carries, as a property, the
// `building_id` it came from.
function explodeBuildingParts(features: any[]): any[] {
    const out: any[] = [];
    for (const f of features ?? []) {
        const geom = f?.geometry;
        const props = f?.properties ?? {};
        const partMeta: any[] | null = Array.isArray(props.parts) ? props.parts : null;
        const pushPart = (g: any, meta: any) => {
            if (!g) return;
            const gg = g.type === 'GeometryCollection' ? flattenToMultiPolygon(g) : g;
            if (!gg) return;
            const p = { ...(meta ?? {}) };
            delete p.parts;
            if (props.building_id != null) p.building_id = props.building_id;
            const h = deriveBuildingHeight(p);
            if (h != null) p.height = h;
            out.push({ type: 'Feature', geometry: gg, properties: p });
        };
        if (geom?.type === 'GeometryCollection' && Array.isArray(geom.geometries)) {
            geom.geometries.forEach((g: any, i: number) => pushPart(g, partMeta?.[i] ?? props));
        } else if (geom) {
            pushPart(geom, props);
        }
    }
    return out;
}

// Load a data-only grammar spec's sources directly with AutkDb and return the
// resulting layers, so a grammar node can export its parsed data downstream.
// (The grammar engine itself never exposes the loaded DB — createEngine returns
// no `context` — so we drive the same AutkDb the grammar uses internally.)
export async function loadSpecLayers(spec: any): Promise<Array<{ name: string; type: string; geojson: FeatureCollection }>> {
    const { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } = await import('@urban-toolkit/autk-db');
    // `init()` downloads the DuckDB spatial extension; a flaky fetch is worth
    // another instance rather than a failed node (#318).
    const db: any = await withExtensionRetry(async () => {
        const instance: any = new AutkDb();
        await instance.init();
        return instance;
    });
    // Reasons individual sources / reads failed, surfaced below when the load
    // produced no usable layer at all — so a total failure reports WHY instead
    // of crashing later with an opaque "Cannot read properties of null".
    const loadErrors: string[] = [];
    const joinErrors: string[] = [];
    for (const source of (spec?.data ?? [])) {
        const { type, ...rest } = source ?? {};
        try {
            if (type === 'osm') await db.loadOsm(rest);
            else if (type === 'geojson') await db.loadGeojson(rest);
            else if (type === 'csv') await db.loadCsv(rest);
            else if (type === 'json') await db.loadJson(rest);
            // In-grammar spatial join between already-loaded tables (sources
            // run in spec order, so the join must come after the tables it
            // references). Mirrors the sandbox emit in compileDataSpecToAutkDbJs.
            else if (type === 'join') await db.spatialQuery(rest);
            else console.warn(`[autk-grammar] unsupported data source type "${type}" — skipped`);
        } catch (e) {
            // Record + skip a source that fails to load; others may still
            // produce layers. The recorded reason is surfaced below if the load
            // produced nothing at all.
            loadErrors.push(`${type}: ${(e as any)?.message ?? String(e)}`);
            if (type === 'join') joinErrors.push((e as any)?.message || String(e));
            console.warn(`[autk-grammar] data-only load failed for source type "${type}"`, e);
        }
    }
    // Tag each layer with the CRS its coordinates are ACTUALLY in, so a
    // downstream grammar node injects it with the right coordinateFormat,
    // detected by coordinate magnitude: a wrong tag makes the renderer read
    // degree values as meters near the origin, a silently blank map. Strip any
    // pre-existing crs field first: detectCoordinateFormat trusts it over the
    // heuristic.
    let tables: Array<{ name: string; type?: string }> = [];
    try {
        tables = db.getLayersMetadata() as Array<{ name: string; type?: string }>;
    } catch (e) {
        // A partially-loaded DB can throw here (rather than return []). Treat it
        // as "no usable tables" and let the empty-result guard below report it,
        // instead of letting an opaque TypeError escape the loader.
        loadErrors.push(`getLayersMetadata: ${(e as any)?.message ?? String(e)}`);
    }
    const layers = await Promise.all(
        tables.map(async (t) => {
            try {
                const geojson = (await db.getLayer(t.name)) as any;
                // Keep the autk-db layer type ('roads', 'surface', 'water', 'parks',
                // 'buildings', …) so a downstream grammar node re-loads it with the
                // right rendering.
                const type = (t.type as string) ?? 'polygons';
                // Buildings: explode the grouped GeometryCollection into one footprint
                // feature per part (each with its own height) and KEEP type 'buildings',
                // so autk-map extrudes each part by its real height. See
                // explodeBuildingParts.
                if (type === 'buildings' && Array.isArray(geojson?.features)) {
                    geojson.features = explodeBuildingParts(geojson.features);
                }
                if (geojson && typeof geojson === 'object') {
                    delete geojson.crs;
                    const fmt = detectCoordinateFormat(geojson as FeatureCollection);
                    const epsg = fmt.match(/(\d+)/)?.[1]
                        ?? String(DEFAULT_WORKSPACE_COORDINATE_FORMAT).match(/(\d+)/)?.[1]
                        ?? '3395';
                    geojson.crs = { type: 'name', properties: { name: `urn:ogc:def:crs:EPSG::${epsg}` } };
                }
                return { name: t.name, type, geojson: geojson as FeatureCollection };
            } catch (e) {
                loadErrors.push(`getLayer(${t.name}): ${(e as any)?.message ?? String(e)}`);
                return null;
            }
        }),
    );
    const usable = layers.filter(
        (l): l is { name: string; type: string; geojson: FeatureCollection } => l != null,
    );
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
    const requested = requestedLayerTables(spec?.data ?? []);
    if (requested.length > 0) {
        const have = new Set(usable.map((l) => l.name));
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
            nodeId, '', () => {},
        );
    });
}

// Hand layers downstream in a shape the Data Pool can read: the pool-compatible
// wrapper, persisted to the backend sandbox so downstream nodes see a
// `{path, dataType}` ref — same shape `ia-data` emits, so the Data Pool's normal
// fetch path handles it without a special case. Falls back to the inline
// wrapper when no JS interpreter is available or the persist call fails, and
// to null when there are no layers to wrap.
export async function toPoolOutput(
    layers: Array<{ name: string; type?: string; geojson: FeatureCollection }>,
    jsInterpreter: JavaScriptInterpreter | undefined,
    nodeId: string,
): Promise<any> {
    const wrapper = layersToPoolWrapper(layers);
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
// the original layer identity (e.g. `dataRef: "table_osm_buildings"`).
function layersToPoolWrapper(
    layers: Array<{ name: string; type?: string; geojson: FeatureCollection }>,
): any {
    if (!Array.isArray(layers) || layers.length === 0) return null;
    if (layers.length === 1) {
        return {
            dataType: 'geodataframe',
            data: layers[0].geojson,
            layerName: layers[0].name,
            layerType: layers[0].type,
        };
    }
    return {
        dataType: 'outputs',
        data: layers.map((l) => ({
            dataType: 'geodataframe',
            data: l.geojson,
            layerName: l.name,
            layerType: l.type,
        })),
    };
}
