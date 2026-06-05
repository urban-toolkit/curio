import React, { useEffect, useRef } from 'react';
import { FeatureCollection } from 'geojson';
import { NodeLifecycleHook } from '../../registry/types';
import { fetchData } from '../../services/api';
import { useToastContext } from '../../providers/ToastProvider';
import { autkGrammarAdapter } from '../../adapters/autkGrammarAdapter';
import { VisInteractionType, NodeType } from '../../constants';

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

        // Inject upstream input as a 'geojson' data source named 'upstream' so
        // users can reference "dataRef": "upstream" in the grammar spec.
        if (data.input) {
            try {
                const fc = await resolveUpstreamAsGeoJson(data.input);
                if (fc) {
                    const coordinateFormat = detectCoordinateFormat(fc);
                    spec = {
                        ...spec,
                        data: [
                            { type: 'geojson', geojsonObject: fc, outputTableName: 'upstream', coordinateFormat },
                            ...(spec.data ?? []),
                        ],
                    };
                }
            } catch {
                // Non-fatal: upstream injection is best-effort only
            }
        }

        // Resolve relative data-source URLs to the backend's /file/ route so
        // users can write the CURIO_LAUNCH_CWD-relative path
        // 'docs/examples/data/file.pbf' instead of 'http://localhost:5002/...'.
        spec = resolveDataSourceUrls(spec);

        const targets: Record<string, string> = {};
        if (hasMaps) targets.map = mapCanvasId;
        if (hasPlot && !hasMaps) targets.plot = plotDivId;

        // Tear down any listeners from the previous run before creating a new
        // grammar instance, so we never hold stale references.
        interactionOffRef.current.forEach(f => f());
        interactionOffRef.current = [];

        nodeState.setOutput({ code: 'exec', content: '' });
        try {
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

            if (hasMaps || hasPlot) {
                // Visual output: pass input through downstream (mirrors VIS_VEGA behaviour)
                if (data.outputCallback) {
                    data.outputCallback(data.nodeId, data.input ?? null);
                }
            } else {
                // Data/compute only: emit processed tables as a layer array
                const tableNames = Object.keys(grammar.data);
                const layers = await Promise.all(
                    tableNames.map(async (name) => {
                        const geojson = await grammar.data[name];
                        return { name, type: 'POLYGONS_2D', geojson };
                    }),
                );
                if (data.outputCallback) {
                    data.outputCallback(data.nodeId, layers);
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
            : (autkGrammarAdapter.getDefaultSpec() as string),
    };
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function resolveUpstreamAsGeoJson(raw: any): Promise<FeatureCollection | null> {
    if (!raw || raw === '') return null;

    let arg: any = raw;

    // Resolve DuckDB artifact reference
    if (typeof arg === 'object' && arg !== null && arg.path) {
        const fetched = await fetchData(arg.path);
        arg = fetched ?? null;
    }

    if (!arg) return null;

    // Unwrap {dataType, data} envelope
    if (typeof arg === 'object' && 'dataType' in arg && 'data' in arg) {
        arg = arg.data;
    }

    if (!arg) return null;

    // Layer array: extract the first layer's geojson
    if (Array.isArray(arg)) {
        const first = arg[0];
        if (!first || typeof first !== 'object') return null;
        if ('data' in first && 'dataType' in first) {
            return first.data?.type === 'FeatureCollection' ? (first.data as FeatureCollection) : null;
        }
        if (first.geojson?.type === 'FeatureCollection') return first.geojson as FeatureCollection;
        if (first.type === 'FeatureCollection') return first as FeatureCollection;
        return null;
    }

    // Direct FeatureCollection
    if (arg.type === 'FeatureCollection') return arg as FeatureCollection;

    return null;
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
function resolveDataSourceUrls(spec: any): any {
    if (!Array.isArray(spec.data) || spec.data.length === 0) return spec;

    const backendUrl = (process.env.BACKEND_URL || 'http://localhost:5002').replace(/\/$/, '');
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

