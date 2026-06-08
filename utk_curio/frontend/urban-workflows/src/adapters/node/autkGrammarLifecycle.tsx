import React, { useEffect, useRef } from 'react';
import { FeatureCollection } from 'geojson';
import { NodeLifecycleHook } from '../../registry/types';
import { fetchData } from '../../services/api';
import { useToastContext } from '../../providers/ToastProvider';
import { autkGrammarAdapter } from '../../adapters/autkGrammarAdapter';
import { VisInteractionType, NodeType } from '../../constants';
import { JavaScriptInterpreter } from '../../JavaScriptInterpreter';

export const useAutkGrammarLifecycle: NodeLifecycleHook = (data, nodeState) => {
    const { showToast } = useToastContext();
    const wrapperRef = useRef<HTMLDivElement>(null);

    // Grammar instance and last-run spec, kept in refs so effects can access
    // them without causing re-renders.
    const grammarRef = useRef<any>(null);
    const specRef    = useRef<any>(null);
    // Unsubscribe functions returned by grammar.interactions.on(); cleared and
    // re-populated on every applyGrammar call and on unmount.
    const interactionOffRef = useRef<Array<() => void>>([]);
    // Always-current ref to data so grammar event callbacks never close over a
    // stale data object (grammar subscriptions outlive individual renders).
    const dataRef = useRef(data);
    useEffect(() => { dataRef.current = data; });

    // Memoizes the backend data load (a DuckDB artifact reference) keyed on the
    // authored data sources + upstream identity, so re-running the grammar after
    // an unrelated edit (e.g. tweaking map colors) does not re-load OSM/PBF in
    // the backend. The cached DuckDB artifact stays valid until the data section
    // or the upstream input changes.
    const dataCacheRef = useRef<{ key: string; ref: { path: string; dataType: string } } | null>(null);

    const applyGrammar = async (specString: string) => {
        let spec: any;
        try {
            spec = typeof specString === 'string' ? JSON.parse(specString) : { ...(specString as any) };
        } catch {
            nodeState.setOutput({ code: 'error', content: 'Invalid JSON grammar spec.' });
            return;
        }

        const nodeId = data.nodeId;
        const mapCanvasId = 'autk-grammar-map-' + nodeId;
        const plotDivId = 'autk-grammar-plot-' + nodeId;
        const hasMaps = spec.map != null;
        const hasPlot = spec.plot != null;

        // Reset container children before each run to release the old WebGPU
        // context. AutkGrammar has no destroy() — replacing the canvas element
        // is the only way to prevent context leaks across re-runs.
        const wrapper = wrapperRef.current;
        if (wrapper) {
            while (wrapper.firstChild) wrapper.removeChild(wrapper.firstChild);
            if (hasMaps) {
                const canvas = document.createElement('canvas');
                canvas.id = mapCanvasId;
                canvas.style.cssText = 'display:block;width:100%;height:100%;';
                wrapper.appendChild(canvas);
            } else if (hasPlot) {
                const plotDiv = document.createElement('div');
                plotDiv.id = plotDivId;
                plotDiv.style.cssText = 'width:100%;height:100%;overflow:auto;';
                wrapper.appendChild(plotDiv);
            }
        }

        // The authored data sources (osm / pbf / csv / json / geojson-from-URL)
        // are the heavy "data component": they run in the backend sandbox via
        // autk-db. Capture them before we touch spec.data.
        const specDataSources: any[] = Array.isArray(spec.data) ? spec.data : [];

        // Inject upstream input as 'geojson' data sources the spec can reference.
        // A single upstream frame (e.g. a Python GeoDataFrame) is exposed as
        // "upstream"; a multi-layer array from an upstream grammar node is exposed
        // under each layer's own name (table_osm_buildings, …), with "upstream"
        // kept as an alias for the first layer (back-compat). Upstream geojson is
        // already serialized data the browser holds, so it stays client-side and
        // is NOT sent to the backend.
        let upstreamSources: any[] = [];
        if (data.input) {
            try {
                const layers = await resolveUpstreamLayers(data.input);
                if (layers.length > 0) {
                    upstreamSources = layers.map(({ name, fc, layerType }) => ({
                        type: 'geojson', geojsonObject: fc, outputTableName: name,
                        coordinateFormat: detectCoordinateFormat(fc),
                        // Preserve the autk-db layer type so relation-built layers
                        // (water/parks/buildings) re-load with the right processing.
                        ...(layerType ? { layerType } : {}),
                    }));
                    if (!layers.some((l) => l.name === 'upstream')) {
                        const { fc } = layers[0];
                        upstreamSources.unshift({
                            type: 'geojson', geojsonObject: fc, outputTableName: 'upstream',
                            coordinateFormat: detectCoordinateFormat(fc),
                        });
                    }
                }
            } catch {
                // Non-fatal: upstream injection is best-effort only
            }
        }

        const targets: Record<string, string> = {};
        if (hasMaps) targets.map = mapCanvasId;
        if (hasPlot && !hasMaps) targets.plot = plotDivId;

        // Tear down any listeners from the previous run before creating a new
        // grammar instance, so we never hold stale references.
        interactionOffRef.current.forEach(f => f());
        interactionOffRef.current = [];

        nodeState.setOutput({ code: 'exec', content: '' });
        try {
            // ── Data section → backend sandbox ──────────────────────────────
            // The authored data sources are compiled to autk-db JavaScript and
            // executed in the Node.js sandbox, where the layer array is persisted
            // in DuckDB. The browser only renders. backendRef is the DuckDB
            // artifact reference; backendLayers is set only by the in-browser
            // fallback (sandbox unreachable / source can't run server-side).
            let backendRef: { path: string; dataType: string } | null = null;
            let backendLayers: Array<{ name: string; type?: string; geojson: any }> | null = null;

            if (specDataSources.length > 0) {
                const resolvedForBackend = resolveDataSourceUrls({ data: specDataSources }, true).data;
                // Key only on the authored data sources: the backend load inlines
                // exactly these (upstream input stays client-side and never reaches the
                // sandbox), so the DuckDB artifact is a pure function of them.
                const cacheKey = JSON.stringify(resolvedForBackend);

                if (dataCacheRef.current && dataCacheRef.current.key === cacheKey) {
                    backendRef = dataCacheRef.current.ref;
                } else {
                    try {
                        if (!data.jsInterpreter) throw new Error('No JS interpreter available for backend data load.');
                        const code = compileDataSpecToAutkDbJs(resolvedForBackend);
                        backendRef = await runDataInBackend(data.jsInterpreter, code, data.nodeId);
                        dataCacheRef.current = { key: cacheKey, ref: backendRef };
                    } catch (e: any) {
                        // Graceful fallback: load the data in-browser (the original
                        // path) so the node still works if the sandbox is down.
                        console.warn('[autk-grammar] backend data load failed; falling back to in-browser AutkDb', e);
                        const resolvedForFrontend = resolveDataSourceUrls({ data: specDataSources }, false).data;
                        backendLayers = await loadSpecLayers({ data: resolvedForFrontend });
                        dataCacheRef.current = null;
                    }
                }
            }

            if (hasMaps || hasPlot) {
                // Render node: feed the backend-loaded data in as inline geojson
                // sources (so the grammar engine never re-loads from URL), then run
                // compute/map/plot in the browser. Backend layers are already
                // projected to the workspace CRS (EPSG:3395).
                let dataSectionSources = upstreamSources;
                if (specDataSources.length > 0) {
                    let layers: Array<{ name: string; type?: string; geojson: any }> = [];
                    try {
                        layers = await materializeBackendLayers(backendLayers, backendRef);
                    } catch {
                        layers = [];
                    }
                    // Self-heal: if the backend ref produced no usable layers (artifact
                    // evicted, session changed, or a serialization mismatch), drop the
                    // cache and load in-browser so the node renders instead of silently
                    // showing an empty map/plot. Only applies to the backend-ref path
                    // (backendLayers == null means we did not already fall back).
                    if (layers.length === 0 && backendLayers == null) {
                        console.warn('[autk-grammar] backend layers empty/unresolvable; falling back to in-browser AutkDb');
                        dataCacheRef.current = null;
                        const resolvedForFrontend = resolveDataSourceUrls({ data: specDataSources }, false).data;
                        layers = await loadSpecLayers({ data: resolvedForFrontend });
                    }
                    const backendAsSources = layers.map((l) => ({
                        type: 'geojson',
                        geojsonObject: l.geojson,
                        outputTableName: l.name,
                        coordinateFormat: 'EPSG:3395',
                        ...(l.type && l.type !== 'polygons' ? { layerType: l.type } : {}),
                    }));
                    dataSectionSources = [...upstreamSources, ...backendAsSources];
                }
                spec = { ...spec, data: dataSectionSources };

                const { AutkGrammar } = await import('@urban-toolkit/autk-grammar');
                const grammar = new AutkGrammar(targets);
                await grammar.run(spec);

                // Store for interaction effects
                grammarRef.current = grammar;
                specRef.current    = spec;

                // Grammar → Curio: forward map-picking and plot-selection events to
                // the Curio interaction bus so connected nodes (data-pool, Vega) react.
                // Guard against older package versions that pre-date the interactions API.
                if (grammar.interactions) {
                    const emitInteraction = (selection: number[]) => {
                        const d = dataRef.current;
                        d.interactionsCallback?.({
                            autk_selection: {
                                type: selection.length > 0 ? VisInteractionType.POINT : VisInteractionType.UNDETERMINED,
                                data: selection,
                                priority: 1,
                                source: NodeType.AUTK_GRAMMAR,
                            },
                        }, d.nodeId);
                    };

                    const off1 = grammar.interactions.on('map:picking', ({ selection }) => emitInteraction(selection));
                    const off2 = grammar.interactions.on('plot:selection', ({ selection }) => emitInteraction(selection));
                    interactionOffRef.current = [off1, off2];
                }

                if (data.outputCallback) {
                    data.outputCallback(data.nodeId, data.input ?? null);
                }
            } else {
                // Data-only node: emit the data downstream.
                grammarRef.current = null;
                specRef.current    = null;
                if (specDataSources.length > 0) {
                    // Backend-loaded data lives in DuckDB; pass the artifact
                    // reference downstream (matches main's AUTK_DB) so the next node
                    // loads it straight from the DB. The fallback emits layers inline.
                    const out = backendRef ?? backendLayers;
                    if (data.outputCallback) data.outputCallback(data.nodeId, out);
                } else {
                    // No authored data: preserve the upstream-passthrough behavior —
                    // normalize the injected geojson via AutkDb in-browser and emit.
                    const layers = await loadSpecLayers({ ...spec, data: upstreamSources });
                    if (data.outputCallback) data.outputCallback(data.nodeId, layers);
                }
            }

            nodeState.setOutput({ code: 'success', content: '' });
        } catch (err: any) {
            const msg = err?.message ?? String(err);
            nodeState.setOutput({ code: 'error', content: msg });
            showToast(msg, 'error');
        }
    };

    // Curio → grammar: the Data Pool marks each feature with interacted:'1'/'0'
    // after resolving interactions, then sends updated data via outputCallback.
    // When data.input changes here, read those flags and apply highlights so
    // the grammar map/plot stays in sync with whatever the Data Pool resolved.
    useEffect(() => {
        const grammar = grammarRef.current;
        const spec    = specRef.current;
        if (!grammar || !spec || !data.input) return;

        (async () => {
            const fc = await resolveUpstreamAsGeoJson(data.input);
            if (!fc) return;

            const selectedIndices = fc.features.reduce<number[]>((acc, f, i) => {
                if (f.properties?.interacted === '1') acc.push(i);
                return acc;
            }, []);

            const maps  = spec.map  ? (Array.isArray(spec.map)  ? spec.map  : [spec.map])  : [];
            const plots = spec.plot ? (Array.isArray(spec.plot) ? spec.plot : [spec.plot]) : [];

            for (const mapSpec of maps)
                for (const lr of mapSpec.layerRefs)
                    selectedIndices.length === 0
                        ? grammar.clearHighlightOnMap?.(lr.dataRef)
                        : grammar.highlightOnMap?.(lr.dataRef, selectedIndices);

            for (const plotSpec of plots)
                selectedIndices.length === 0
                    ? grammar.clearHighlightOnPlot?.(plotSpec.dataRef)
                    : grammar.setPlotSelection?.(plotSpec.dataRef, selectedIndices);
        })();
    }, [data.input]);

    // Forward parent container resizes to AutkMap via a synthetic window.resize.
    // AutkMap binds only to window.resize, so node-handle drags are otherwise silent.
    useEffect(() => {
        const wrapper = wrapperRef.current;
        const target = wrapper?.parentElement;
        if (!wrapper || !target || typeof ResizeObserver === 'undefined') return;
        const sync = () => {
            const w = target.clientWidth;
            const h = target.clientHeight;
            if (w <= 0 || h <= 0) return;
            wrapper.style.width = w + 'px';
            wrapper.style.height = h + 'px';
            window.dispatchEvent(new Event('resize'));
        };
        sync();
        const ro = new ResizeObserver(sync);
        ro.observe(target);
        return () => ro.disconnect();
    }, []);

    // Unsubscribe grammar event listeners when the node is removed from the canvas.
    useEffect(() => () => { interactionOffRef.current.forEach(f => f()); }, []);

    // Stable JSX reference across incidental re-renders, but identity changes
    // on run completion so NodeEditor switches to the output tab automatically.
    const contentComponent = React.useMemo<React.ReactNode>(
        () => (
            <div
                className="nodrag nopan nowheel"
                ref={wrapperRef}
                style={{
                    position: 'relative',
                    width: '100%',
                    height: '100%',
                    minHeight: 400,
                    overflow: 'hidden',
                }}
            />
        ),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [nodeState.output],
    );

    const hasExistingCode = !!(data.defaultCode || (data as any).code);

    return {
        applyGrammar,
        contentComponent,
        defaultValueOverride: hasExistingCode
            ? undefined
            : (autkGrammarAdapter.getDefaultSpec?.() as string | undefined),
    };
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Compile a grammar `data` section into autk-db JavaScript to run in the backend
// Node.js sandbox. The single top-level `import` is rewritten to `await import()`
// by execute_js_code; the rest is the body of the async function the sandbox
// wraps user code in. Mirrors loadSpecLayers exactly, with the spec inlined as a
// literal and flattenToMultiPolygon inlined (the module-level helper above is not
// in the sandbox's scope). The function returns Array<{name, type, geojson}>,
// which the sandbox persists to DuckDB.
function compileDataSpecToAutkDbJs(dataSources: any[]): string {
    return `import { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } from '@urban-toolkit/autk-db';
const __sources = ${JSON.stringify(dataSources)};
const db = new AutkDb();
await db.init();
for (const source of __sources) {
  const { type, ...rest } = source ?? {};
  try {
    if (type === 'osm') await db.loadOsm(rest);
    else if (type === 'geojson') await db.loadGeojson(rest);
    else if (type === 'csv') await db.loadCsv(rest);
    else if (type === 'json') await db.loadJson(rest);
  } catch (e) {
    console.log('[autk-grammar] data load failed for source type "' + type + '": ' + (e && e.message));
  }
}
const __epsg = String(DEFAULT_WORKSPACE_COORDINATE_FORMAT).match(/(\\d+)/)?.[1] ?? '3395';
const __crs = { type: 'name', properties: { name: 'urn:ogc:def:crs:EPSG::' + __epsg } };
const __flattenToMultiPolygon = (geom) => {
  const polys = [];
  const collect = (g) => {
    if (!g) return;
    if (g.type === 'Polygon') polys.push(g.coordinates);
    else if (g.type === 'MultiPolygon') polys.push(...g.coordinates);
    else if (g.type === 'GeometryCollection') (g.geometries || []).forEach(collect);
  };
  collect(geom);
  return polys.length > 0 ? { type: 'MultiPolygon', coordinates: polys } : null;
};
const __buildingHeight = (props) => {
  const num = (v) => { const n = parseFloat(String(v)); return Number.isFinite(n) && n > 0 ? n : 0; };
  const L = 3.4; // metres per level (matches autk-map's building renderer)
  const p = props || {};
  // autk-map culls a part when its top height <= its base (min_height) — which also
  // covers the no-height case (0 <= 0). Mirror its height computation and, only when
  // the part would be culled, return a height that clears the base by a visible
  // amount; otherwise return null to leave the real tags untouched.
  const base = num(p.min_height) || L * num(p.min_level) || L * num(p['building:min_level']);
  let top = num(p.height) || L * num(p.levels) || L * num(p['building:levels']);
  if (top === 0 && Array.isArray(p.parts)) {
    for (const q of p.parts) { const h = num(q && q.height) || L * num(q && q.levels); if (h > top) top = h; }
  }
  return top > base ? null : base + 6;
};
const __out = [];
for (const t of (db.getLayerTables ? db.getLayerTables() : [])) {
  const geojson = await db.getLayer(t.name);
  let type = t.type ?? 'polygons';
  if (type === 'buildings' && Array.isArray(geojson?.features)) {
    // autk-db's 3D building model (per-part polygons keyed by building_id, each with
    // its own height) is a loadOsm construct that loadGeojson cannot rebuild from a
    // grouped GeometryCollection. Explode each building back into one footprint
    // feature per part (carrying that part's height) so the downstream
    // loadGeojson('buildings') re-clusters them by building_id and getLayer re-emits
    // proper per-part GeometryCollections — letting autk-map extrude each part by its
    // own height instead of collapsing the whole building into a single box.
    const __exploded = [];
    for (const f of geojson.features) {
      const geom = f && f.geometry;
      const props = (f && f.properties) || {};
      const partMeta = Array.isArray(props.parts) ? props.parts : null;
      const pushPart = (g, meta) => {
        if (!g) return;
        const gg = g.type === 'GeometryCollection' ? __flattenToMultiPolygon(g) : g;
        if (!gg) return;
        const p = { ...(meta || {}) }; delete p.parts;
        const h = __buildingHeight(p); if (h != null) p.height = h;
        __exploded.push({ type: 'Feature', geometry: gg, properties: p });
      };
      if (geom && geom.type === 'GeometryCollection' && Array.isArray(geom.geometries)) {
        geom.geometries.forEach((g, i) => pushPart(g, partMeta && partMeta[i] ? partMeta[i] : props));
      } else if (geom) {
        pushPart(geom, props);
      }
    }
    geojson.features = __exploded;
  }
  if (geojson && typeof geojson === 'object') geojson.crs = __crs;
  __out.push({ name: t.name, type, geojson });
}
return __out;`;
}

// Run the compiled autk-db loader in the backend sandbox and resolve to the
// DuckDB artifact reference ({path, dataType}) the sandbox returns. Wraps the
// callback-based JavaScriptInterpreter in a Promise. No DuckDB input is loaded
// (input is ''); the data spec is inlined in the code, so the wrapper's `arg`
// is unused.
function runDataInBackend(
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

// Resolve the backend data load into in-browser layers for the render path:
// the in-memory fallback layers if present, otherwise fetch + normalize the
// DuckDB artifact (resolveUpstreamLayers handles the {path} fetch and unwrap).
async function materializeBackendLayers(
    fallbackLayers: Array<{ name: string; type?: string; geojson: any }> | null,
    ref: { path: string; dataType: string } | null,
): Promise<Array<{ name: string; type?: string; geojson: any }>> {
    if (fallbackLayers) return fallbackLayers;
    if (!ref) return [];
    const layers = await resolveUpstreamLayers(ref);
    return layers.map((l) => ({ name: l.name, type: l.layerType, geojson: l.fc }));
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

// Guarantee a footprint extrudes instead of being culled as "no valid height
// metadata". autk-map culls a building part when its top height <= its base
// (`min_height`) — which also covers the no-height case (0 <= 0). Mirror that
// computation and, only when the part would be culled, return a height that clears
// the base by a visible amount; otherwise return null to leave the real tags
// untouched. `parts` lifting covers a feature whose height lived only per-part.
function deriveBuildingHeight(props: any): number | null {
    const num = (v: any) => { const n = parseFloat(String(v)); return Number.isFinite(n) && n > 0 ? n : 0; };
    const LEVEL = 3.4; // metres per level (matches autk-map's building renderer)
    const base = num(props?.min_height) || LEVEL * num(props?.min_level) || LEVEL * num(props?.['building:min_level']);
    let top = num(props?.height) || LEVEL * num(props?.levels) || LEVEL * num(props?.['building:levels']);
    if (top === 0 && Array.isArray(props?.parts)) {
        for (const p of props.parts) { const h = num(p?.height) || LEVEL * num(p?.levels); if (h > top) top = h; }
    }
    return top > base ? null : base + 6;
}

// Explode autk-db's grouped building features into one footprint feature per part.
// autk-db's 3D building model — per-part polygons keyed by `building_id`, each with
// its own height, which `getLayer` exports as a GeometryCollection with a parallel
// `properties.parts` metadata array — is a `loadOsm` construct that `loadGeojson`
// cannot rebuild from the grouped GeometryCollection. Splitting each building back
// into its individual part footprints (each carrying that part's height) lets the
// downstream `loadGeojson('buildings')` re-cluster them by `building_id` and have
// `getLayer` re-emit proper per-part GeometryCollections, so autk-map extrudes each
// part by its own height instead of collapsing the whole building into one box.
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
async function loadSpecLayers(spec: any): Promise<Array<{ name: string; type: string; geojson: FeatureCollection }>> {
    const { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } = await import('@urban-toolkit/autk-db');
    const db: any = new AutkDb();
    await db.init();
    for (const source of (spec?.data ?? [])) {
        const { type, ...rest } = source ?? {};
        try {
            if (type === 'osm') await db.loadOsm(rest);
            else if (type === 'geojson') await db.loadGeojson(rest);
            else if (type === 'csv') await db.loadCsv(rest);
            else if (type === 'json') await db.loadJson(rest);
        } catch (e) {
            // Skip a source that fails to load; others may still produce layers.
            console.warn(`[autk-grammar] data-only load failed for source type "${type}"`, e);
        }
    }
    // getLayer() returns geometry already projected into the workspace CRS
    // (DEFAULT_WORKSPACE_COORDINATE_FORMAT, EPSG:3395). Tag each layer with that
    // CRS so a downstream grammar node injects it with the right coordinateFormat
    // instead of mis-detecting it as WGS84 and re-projecting it into garbage.
    const epsg = String(DEFAULT_WORKSPACE_COORDINATE_FORMAT).match(/(\d+)/)?.[1] ?? '3395';
    const crs = { type: 'name', properties: { name: `urn:ogc:def:crs:EPSG::${epsg}` } };
    const tables = (db.getLayerTables ? db.getLayerTables() : []) as Array<{ name: string; type?: string }>;
    return Promise.all(
        tables.map(async (t) => {
            const geojson = (await db.getLayer(t.name)) as any;
            // Keep the autk-db layer type ('roads', 'surface', 'water', 'parks',
            // 'buildings', …) so a downstream grammar node re-loads it with the
            // right rendering.
            const type = (t.type as string) ?? 'polygons';
            // Buildings: explode the grouped GeometryCollection into one footprint
            // feature per part (each with its own height) and KEEP type 'buildings',
            // so the downstream loadGeojson('buildings') re-clusters them and autk-map
            // extrudes each part by its real height. See explodeBuildingParts.
            if (type === 'buildings' && Array.isArray(geojson?.features)) {
                geojson.features = explodeBuildingParts(geojson.features);
            }
            if (geojson && typeof geojson === 'object') geojson.crs = crs;
            return { name: t.name, type, geojson: geojson as FeatureCollection };
        }),
    );
}

// Resolve an upstream input into named GeoJSON layers.
//  - a single frame (e.g. a Python GeoDataFrame) -> one layer named "upstream"
//  - a multi-layer array from an upstream grammar node -> one layer per element,
//    keyed by the layer's own name (table_osm_buildings, …) so the downstream
//    spec can reference each layer individually.
async function resolveUpstreamLayers(raw: any): Promise<Array<{ name: string; fc: FeatureCollection; layerType?: string }>> {
    if (!raw || raw === '') return [];

    let arg: any = raw;

    // Resolve DuckDB artifact reference
    if (typeof arg === 'object' && arg !== null && arg.path) {
        arg = (await fetchData(arg.path)) ?? null;
    }
    if (!arg) return [];

    // Unwrap {dataType, data} envelope
    if (typeof arg === 'object' && 'dataType' in arg && 'data' in arg) {
        arg = arg.data;
    }
    if (!arg) return [];

    // Strip Curio's {dataType, data} envelope. The sandbox's parseOutput (run by
    // GET /get) wraps every artifact, and for a 'list' it ALSO wraps each element,
    // so a backend layer array round-trips as
    //   { dataType:'list', data:[ { dataType:'dict', data:{name,type,geojson} }, … ] }.
    // Unwrap recursively so the real layer record / FeatureCollection underneath is
    // reachable (a raw, un-enveloped value passes through untouched).
    const unwrap = (v: any): any =>
        (v && typeof v === 'object' && 'data' in v && 'dataType' in v) ? unwrap(v.data) : v;

    const asFc = (v: any): FeatureCollection | null => {
        const u = unwrap(v);
        if (!u || typeof u !== 'object') return null;
        if (u.geojson?.type === 'FeatureCollection') return u.geojson as FeatureCollection;
        if (u.type === 'FeatureCollection') return u as FeatureCollection;
        return null;
    };

    // Layer array from an upstream grammar node / backend DuckDB ref: keep every
    // layer, named. Read name/type from the UNWRAPPED record, not the envelope.
    if (Array.isArray(arg)) {
        const out: Array<{ name: string; fc: FeatureCollection; layerType?: string }> = [];
        arg.forEach((item, i) => {
            const fc = asFc(item);
            if (fc) {
                const u = unwrap(item);
                const name = u && typeof u === 'object' && u.name ? String(u.name) : `upstream_${i}`;
                // u.type is the autk-db layer type ('surface'/'roads'/…) on a layer
                // record; ignore a bare FeatureCollection's own type field.
                const layerType = u && typeof u === 'object' && u.geojson && typeof u.type === 'string'
                    ? u.type : undefined;
                out.push({ name, fc, layerType });
            }
        });
        return out;
    }

    // Direct FeatureCollection (e.g. a single Python GeoDataFrame).
    const fc = asFc(arg);
    return fc ? [{ name: 'upstream', fc }] : [];
}

async function resolveUpstreamAsGeoJson(raw: any): Promise<FeatureCollection | null> {
    const layers = await resolveUpstreamLayers(raw);
    return layers.length > 0 ? layers[0].fc : null;
}

// Determine the CRS of a FeatureCollection produced by Python/geopandas so
// the correct coordinateFormat can be passed to autk-db's loadGeojson.
//
// Strategy (in order of reliability):
//   1. Read the "crs" field that geopandas embeds in every to_json() output,
//      e.g. {"type":"name","properties":{"name":"urn:ogc:def:crs:EPSG::3395"}}.
//      This is the most reliable signal and handles any EPSG code, not just 3395.
//   2. Fall back to inspecting coordinate magnitudes: anything outside the
//      WGS84 bounding box (±180° lon / ±90° lat) is clearly projected.
//   3. Default to EPSG:4326 (standards-compliant GeoJSON) when no signal found.
function detectCoordinateFormat(fc: FeatureCollection): string {
    // --- Strategy 1: embedded CRS field ---
    const crsName: string | undefined = (fc as any)?.crs?.properties?.name;
    if (crsName) {
        const m = crsName.match(/EPSG:{1,2}(\d+)/i);
        if (m) return `EPSG:${m[1]}`;
    }

    // --- Strategy 2: coordinate magnitude heuristic ---
    const WGS84_LON_MAX = 180;
    const WGS84_LAT_MAX = 90;
    const SAMPLE = 5;

    for (let i = 0; i < Math.min(fc.features.length, SAMPLE); i++) {
        const geom = fc.features[i]?.geometry;
        if (!geom || !('coordinates' in geom)) continue;

        const coord = firstCoordinate((geom as any).coordinates);
        if (!coord) continue;

        const [x, y] = coord;
        if (
            typeof x === 'number' && typeof y === 'number' &&
            isFinite(x) && isFinite(y) &&
            (Math.abs(x) > WGS84_LON_MAX || Math.abs(y) > WGS84_LAT_MAX)
        ) {
            return 'EPSG:3395';
        }
    }

    // --- Strategy 3: assume standards-compliant WGS84 ---
    return 'EPSG:4326';
}

function firstCoordinate(coords: any): [number, number] | null {
    if (!Array.isArray(coords) || coords.length === 0) return null;
    if (typeof coords[0] === 'number') return coords as [number, number];
    return firstCoordinate(coords[0]);
}

// Resolve relative URLs in data source specs to the Curio backend's /file/
// route, which serves files by their path *relative to CURIO_LAUNCH_CWD* — the
// same root and relative-path convention the Python sandbox uses. So users can
// write the CURIO_LAUNCH_CWD-relative path 'docs/examples/data/file.pbf' (no
// host/port, no route prefix) exactly as a Python node would read it.
// Absolute URIs (http://, https://, data:, blob:, …) are passed through unchanged.
// Applies to all file-URL fields across every data source type.
function resolveDataSourceUrls(spec: any, forBackend = false): any {
    if (!Array.isArray(spec.data) || spec.data.length === 0) return spec;

    let backendUrl = (process.env.BACKEND_URL || 'http://localhost:5002').replace(/\/$/, '');
    // When the URL will be fetched by the sandbox's Node.js subprocess (the data
    // section runs there), force the loopback host to 127.0.0.1 — node's fetch
    // can stall on `localhost` resolving to IPv6 ::1. The /file/ route is
    // unauthenticated, so the node fetch needs no token.
    if (forBackend) backendUrl = backendUrl.replace(/:\/\/localhost(:|\/|$)/, '://127.0.0.1$1');
    const urlFields = ['pbfFileUrl', 'csvFileUrl', 'jsonFileUrl', 'geojsonFileUrl'];
    const isAbsolute = (url: string) => /^[a-z][a-z\d+\-.]*:/i.test(url);

    const resolved = spec.data.map((source: any) => {
        const patch: Record<string, string> = {};
        for (const field of urlFields) {
            const val = source[field];
            if (typeof val === 'string' && !isAbsolute(val)) {
                patch[field] = `${backendUrl}/file/${val.replace(/^\/+/, '')}`;
            }
        }
        return Object.keys(patch).length > 0 ? { ...source, ...patch } : source;
    });

    return { ...spec, data: resolved };
}

