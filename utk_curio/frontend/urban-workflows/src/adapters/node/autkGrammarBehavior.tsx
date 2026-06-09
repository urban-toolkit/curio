import React, { useEffect, useRef } from 'react';
import { Feature, FeatureCollection } from 'geojson';
import { NodeBehaviorHook } from '../../registry/types';
import { fetchData } from '../../services/api';
import { useToastContext } from '../../providers/ToastProvider';
import { autkGrammarAdapter } from '../../adapters/autkGrammarAdapter';
import { VisInteractionType, NodeType } from '../../constants';
import { JavaScriptInterpreter } from '../../JavaScriptInterpreter';

export const useAutkGrammarBehavior: NodeBehaviorHook = (data, nodeState) => {
    const { showToast } = useToastContext();
    const wrapperRef = useRef<HTMLDivElement>(null);

    // Grammar instance and last-run spec, kept in refs so effects can access
    // them without causing re-renders.
    const grammarRef = useRef<any>(null);
    const specRef    = useRef<any>(null);
    // Unsubscribe functions returned by grammar.interactions.on(); cleared and
    // re-populated on every applyGrammar call and on unmount.
    const interactionOffRef = useRef<Array<() => void>>([]);
    // Disposer for the map interaction zoom-fix listeners (window-bound), cleared
    // and re-populated on each applyGrammar run with a map, and on unmount.
    const pickFixCleanupRef = useRef<(() => void) | null>(null);
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
            // Dispose the previous run's interaction-zoom-fix listeners (they live on
            // window, so they'd leak and fire for the now-stale canvas otherwise).
            pickFixCleanupRef.current?.();
            pickFixCleanupRef.current = null;
            while (wrapper.firstChild) wrapper.removeChild(wrapper.firstChild);
            if (hasMaps) {
                const canvas = document.createElement('canvas');
                canvas.id = mapCanvasId;
                canvas.style.cssText = 'display:block;width:100%;height:100%;';
                wrapper.appendChild(canvas);
                pickFixCleanupRef.current = attachMapInteractionZoomFix(canvas);
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
                    // Capture which layer each interaction comes from so a downstream
                    // Data Pool can target the right layer in a multi-layer wrapper —
                    // otherwise the pool's legacy path operates on data[0] and a brush
                    // on (say) roads ends up marking surface features. The picked map
                    // layer is the one with isPick:true; the plot's source is its
                    // dataRef. Both are resolved once here and closed over below.
                    const pickedLayerRef: string | undefined =
                        spec.map?.layerRefs?.find?.((l: any) => l.isPick)?.dataRef
                        ?? spec.map?.layerRefs?.[0]?.dataRef;
                    const plotLayerRef: string | undefined = spec.plot?.dataRef;

                    const emitInteraction = (selection: number[], layerRef: string | undefined) => {
                        const d = dataRef.current;
                        d.interactionsCallback?.({
                            autk_selection: {
                                type: selection.length > 0 ? VisInteractionType.POINT : VisInteractionType.UNDETERMINED,
                                data: selection,
                                priority: 1,
                                source: NodeType.AUTK_GRAMMAR,
                                layerRef,
                            },
                        }, d.nodeId);
                    };

                    const off1 = grammar.interactions.on('map:picking',    ({ selection }) => emitInteraction(selection, pickedLayerRef));
                    const off2 = grammar.interactions.on('plot:selection', ({ selection }) => emitInteraction(selection, plotLayerRef));
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
                    // Compute-only node: skip the extra AutkDb round-trip — upstream layers
                    // (from backend, or the in-browser fallback) are already normalized and
                    // exploded. Re-loading them through DuckDB + the buildings clusterer can
                    // strip custom per-feature properties. Apply WGSL blocks directly so the
                    // outputs (feature.properties.compute.<col>) reach downstream untouched.
                    const upstream = await resolveUpstreamLayers(data.input);
                    let layers = upstream.map((u) => ({
                        name: u.name,
                        type: u.layerType ?? 'polygons',
                        geojson: u.fc,
                    }));
                    if (Array.isArray(spec.compute) && spec.compute.length > 0) {
                        layers = await applyComputeBlocks(layers, spec.compute);
                    }
                    // Build the pool-compatible wrapper and persist it to the
                    // backend sandbox so downstream nodes see a `{path, dataType}`
                    // ref — same shape `ia-data` emits, so the Data Pool's normal
                    // fetch path handles it without a special case. Fall back to
                    // inline emit only when no JS interpreter is available or the
                    // persist call fails.
                    const wrapper = layersToPoolWrapper(layers);
                    let out: any = wrapper;
                    if (wrapper && data.jsInterpreter) {
                        try {
                            out = await persistLayersToBackend(data.jsInterpreter, wrapper, data.nodeId);
                        } catch (e) {
                            console.warn('[autk-grammar] backend persist failed; emitting inline wrapper', e);
                        }
                    }
                    if (data.outputCallback) data.outputCallback(data.nodeId, out ?? layers);
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
    //
    // Multi-layer wrappers carry interacted flags on whichever layer the source
    // brush/pick was for; the others have all-zero flags. Read each layer's flags
    // independently and dispatch the highlight per layer name so a roads-only
    // brush only lights up roads even when surface/parks/water are riding along.
    useEffect(() => {
        const grammar = grammarRef.current;
        const spec    = specRef.current;
        if (!grammar || !spec || !data.input) return;

        (async () => {
            const layers = await resolveUpstreamLayers(data.input);
            if (layers.length === 0) return;

            const indicesByLayer = new Map<string, number[]>();
            for (const { name, fc } of layers) {
                const sel = fc.features.reduce<number[]>((acc, f, i) => {
                    if (f.properties?.interacted === '1') acc.push(i);
                    return acc;
                }, []);
                indicesByLayer.set(name, sel);
            }

            const maps  = spec.map  ? (Array.isArray(spec.map)  ? spec.map  : [spec.map])  : [];
            const plots = spec.plot ? (Array.isArray(spec.plot) ? spec.plot : [spec.plot]) : [];

            for (const mapSpec of maps) {
                for (const lr of mapSpec.layerRefs) {
                    const sel = indicesByLayer.get(lr.dataRef) ?? [];
                    sel.length === 0
                        ? grammar.clearHighlightOnMap?.(lr.dataRef)
                        : grammar.highlightOnMap?.(lr.dataRef, sel);
                }
            }
            for (const plotSpec of plots) {
                const sel = indicesByLayer.get(plotSpec.dataRef) ?? [];
                sel.length === 0
                    ? grammar.clearHighlightOnPlot?.(plotSpec.dataRef)
                    : grammar.setPlotSelection?.(plotSpec.dataRef, sel);
            }
        })();
    }, [data.input]);

    // Forward parent container resizes to AutkMap via a synthetic window.resize.
    // AutkMap binds only to window.resize (and exposes no per-instance resize API),
    // so node-handle drags are otherwise silent — but that dispatch is expensive and
    // fragile: each one makes *every* AutkMap on the page rebuild its WebGPU textures
    // and reconfigure its swapchain. Doing that every frame during a drag stalls the
    // canvas, and reconfiguring mid-render races AutkMap's render loop (its
    // getCurrentTexture() ends up invalidated) — which its render-error latch then
    // swallows, leaving the map blank/white.
    //
    // So: keep the *cheap* CSS sizing on every tick (the width/height:100% canvas
    // stretches to fill the node during the drag), but fire the *expensive*
    // window.resize only once the size has settled, and on a macrotask (setTimeout)
    // rather than rAF — outside AutkMap's render window — so the GPU rebuild happens
    // exactly once, cleanly, and the canvas snaps crisp.
    useEffect(() => {
        const wrapper = wrapperRef.current;
        const target = wrapper?.parentElement;
        if (!wrapper || !target || typeof ResizeObserver === 'undefined') return;

        let lastW = -1, lastH = -1;
        let timer: ReturnType<typeof setTimeout> | null = null;

        const commit = () => {
            timer = null;
            const w = target.clientWidth, h = target.clientHeight;
            if (w <= 0 || h <= 0) return;
            // No-op guard: a same-size commit would still rebuild every map's GPU
            // textures, so drop it.
            if (w === lastW && h === lastH) return;
            lastW = w; lastH = h;
            window.dispatchEvent(new Event('resize'));
        };

        const onResize = () => {
            // Cheap: track the parent every tick so the 100% canvas fills the node.
            const w = target.clientWidth, h = target.clientHeight;
            if (w > 0 && h > 0) { wrapper.style.width = w + 'px'; wrapper.style.height = h + 'px'; }
            // Expensive: debounce the GPU rebuild until the drag settles.
            if (timer) clearTimeout(timer);
            timer = setTimeout(commit, 150);
        };

        // Mount: size immediately and do one initial GPU resize.
        const w0 = target.clientWidth, h0 = target.clientHeight;
        if (w0 > 0 && h0 > 0) { wrapper.style.width = w0 + 'px'; wrapper.style.height = h0 + 'px'; }
        commit();

        const ro = new ResizeObserver(onResize);
        ro.observe(target);
        return () => { ro.disconnect(); if (timer) clearTimeout(timer); };
    }, []);

    // Unsubscribe grammar event listeners and remove the interaction zoom-fix
    // window listeners when the node is removed from the canvas.
    useEffect(() => () => {
        interactionOffRef.current.forEach(f => f());
        pickFixCleanupRef.current?.();
    }, []);

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

// Flag stamped on the synthetic events we re-dispatch, so the interceptor
// recognizes its own event and lets it through to autk-map untouched.
const ZOOM_FIX_CORRECTED = '__curioMapZoomCorrected';

// PointerEvent isn't constructable in every test DOM; fall back to MouseEvent
// (autk-map reads only MouseEvent-level fields — clientX/Y, buttons, target — off
// the pointer events it handles).
const PointerEventCtor: typeof MouseEvent =
    typeof PointerEvent !== 'undefined' ? (PointerEvent as unknown as typeof MouseEvent) : MouseEvent;

// Correct autk-map's pointer math for the React Flow viewport scale.
//
// Each node renders inside React Flow's viewport, which is CSS-scaled by the
// current zoom (`transform: scale(zoom)`). autk-map reads pointer positions from
// getBoundingClientRect() — which is *post*-scale — but feeds them to camera /
// picking math sized from the canvas's *unscaled* offsetWidth/offsetHeight (its
// renderer resizes from offsetWidth). At any zoom != 1 the two disagree by the
// zoom factor, so:
//   • picking (double-click) lands toward the canvas's top-left corner,
//   • wheel-zoom recenters on the wrong point,
//   • drag-pan moves the map too slowly — all by the zoom factor.
//
// Curio owns this canvas element, so intercept the relevant events in the capture
// phase on `window` (above autk-map's document/canvas listeners), suppress the
// mis-scaled native event, and re-dispatch an equivalent one *on the canvas* whose
// client coordinates are mapped back into the canvas's unscaled CSS space — exactly
// what autk-map's math assumes (the conversion is the same for all three: each
// divides a screen-space delta by the unscaled cssWidth, so each needs the delta
// un-scaled first). `scale` is read straight off the DOM (rect.width / offsetWidth),
// so this tracks any ancestor transform without needing React Flow's zoom value.
// (The real fix belongs upstream in autk-map's coordinate conversion; this is the
// in-Curio compensation until then.)
//
// Returns a disposer that removes the window listeners — they outlive the canvas,
// so the caller must call it before replacing the canvas and on unmount.
export function attachMapInteractionZoomFix(canvas: HTMLCanvasElement): () => void {
    // Mirrors autk-map's drag state so pointermove/up that wander off the canvas
    // mid-drag stay corrected (autk-map keeps dragging via its document listeners
    // regardless of the event target).
    let dragging = false;

    // The CSS scale ancestors apply to the canvas (React Flow zoom), or null when
    // there's nothing to correct (no layout yet, or scale ~ 1).
    const measure = (): { rect: DOMRect; sx: number; sy: number } | null => {
        const rect = canvas.getBoundingClientRect();
        const lw = canvas.offsetWidth, lh = canvas.offsetHeight;
        if (lw <= 0 || lh <= 0) return null;
        const sx = rect.width / lw, sy = rect.height / lh;
        if (Math.abs(sx - 1) < 0.001 && Math.abs(sy - 1) < 0.001) return null;
        return { rect, sx, sy };
    };

    // Map a client coordinate from rendered (scaled) space back to the unscaled CSS
    // space autk-map expects.
    const cx = (rect: DOMRect, sx: number, clientX: number) => rect.left + (clientX - rect.left) / sx;
    const cy = (rect: DOMRect, sy: number, clientY: number) => rect.top + (clientY - rect.top) / sy;

    const mine = (e: Event) => (e as any)[ZOOM_FIX_CORRECTED] === true;

    const onDblClick = (e: MouseEvent) => {
        if (mine(e) || e.target !== canvas) return;
        const m = measure();
        if (!m) return;
        e.stopImmediatePropagation();
        e.preventDefault();
        const corrected = new MouseEvent('dblclick', {
            bubbles: true, cancelable: true, view: window,
            button: e.button, buttons: e.buttons,
            clientX: cx(m.rect, m.sx, e.clientX),
            clientY: cy(m.rect, m.sy, e.clientY),
        });
        (corrected as any)[ZOOM_FIX_CORRECTED] = true;
        canvas.dispatchEvent(corrected);
    };

    const onWheel = (e: WheelEvent) => {
        if (mine(e) || e.target !== canvas) return;
        const m = measure();
        if (!m) return;
        e.stopImmediatePropagation();
        e.preventDefault();
        const corrected = new WheelEvent('wheel', {
            bubbles: true, cancelable: true, view: window,
            deltaX: e.deltaX, deltaY: e.deltaY, deltaZ: e.deltaZ, deltaMode: e.deltaMode,
            ctrlKey: e.ctrlKey, shiftKey: e.shiftKey, altKey: e.altKey, metaKey: e.metaKey,
            button: e.button, buttons: e.buttons,
            clientX: cx(m.rect, m.sx, e.clientX),
            clientY: cy(m.rect, m.sy, e.clientY),
        });
        (corrected as any)[ZOOM_FIX_CORRECTED] = true;
        canvas.dispatchEvent(corrected);
    };

    const redispatchPointer = (e: PointerEvent, m: { rect: DOMRect; sx: number; sy: number }) => {
        e.stopImmediatePropagation();
        e.preventDefault();
        const init: any = {
            bubbles: true, cancelable: true, view: window,
            button: e.button, buttons: e.buttons,
            ctrlKey: e.ctrlKey, shiftKey: e.shiftKey, altKey: e.altKey, metaKey: e.metaKey,
            clientX: cx(m.rect, m.sx, e.clientX),
            clientY: cy(m.rect, m.sy, e.clientY),
            // Pointer-specific fields (ignored by the MouseEvent fallback).
            pointerId: e.pointerId, pointerType: e.pointerType, isPrimary: e.isPrimary,
        };
        const corrected = new PointerEventCtor(e.type, init);
        (corrected as any)[ZOOM_FIX_CORRECTED] = true;
        canvas.dispatchEvent(corrected);
    };

    const onPointerDown = (e: PointerEvent) => {
        if (mine(e)) return;
        if (e.target === canvas && (e.button === 0 || e.button === 1)) dragging = true;
        if (!dragging) return;
        const m = measure();
        if (!m) return; // scale ~ 1: leave the native event alone (drag still tracked)
        redispatchPointer(e, m);
    };

    const onPointerMove = (e: PointerEvent) => {
        if (mine(e)) return;
        // Mirror autk-map's alternate drag-start (button already held on entry).
        if (!dragging && e.target === canvas && (e.buttons === 1 || e.buttons === 4)) dragging = true;
        if (!dragging) return;
        const m = measure();
        if (!m) return;
        redispatchPointer(e, m);
    };

    const onPointerUp = (e: PointerEvent) => {
        if (mine(e)) return;
        // autk-map's pointerup/cancel use no coordinates; just clear our mirrored
        // state and let the native event through so autk-map ends the drag.
        dragging = false;
    };

    const cap: AddEventListenerOptions = { capture: true };
    const wheelCap: AddEventListenerOptions = { capture: true, passive: false };
    window.addEventListener('dblclick', onDblClick as EventListener, cap);
    window.addEventListener('wheel', onWheel as EventListener, wheelCap);
    window.addEventListener('pointerdown', onPointerDown as EventListener, cap);
    window.addEventListener('pointermove', onPointerMove as EventListener, cap);
    window.addEventListener('pointerup', onPointerUp as EventListener, cap);
    window.addEventListener('pointercancel', onPointerUp as EventListener, cap);

    return () => {
        window.removeEventListener('dblclick', onDblClick as EventListener, cap);
        window.removeEventListener('wheel', onWheel as EventListener, wheelCap);
        window.removeEventListener('pointerdown', onPointerDown as EventListener, cap);
        window.removeEventListener('pointermove', onPointerMove as EventListener, cap);
        window.removeEventListener('pointerup', onPointerUp as EventListener, cap);
        window.removeEventListener('pointercancel', onPointerUp as EventListener, cap);
    };
}

// Compile a grammar `data` section into autk-db JavaScript to run in the backend
// Node.js sandbox. The single top-level `import` is rewritten to `await import()`
// by execute_js_code; the rest is the body of the async function the sandbox
// wraps user code in. Mirrors loadSpecLayers exactly, with the spec inlined as a
// literal and flattenToMultiPolygon inlined (the module-level helper above is not
// in the sandbox's scope). The function returns Array<{name, type, geojson}>,
// which the sandbox persists to DuckDB.
function compileDataSpecToAutkDbJs(dataSources: any[]): string {
    return `import * as __autkDbMod from '@urban-toolkit/autk-db';
// v2.0 frontend builds export AutkDb; the older root-level install of the same
// version still exports AutkSpatialDb. Accept either so the backend sandbox
// (which may be on the older shape) does not throw "AutkDb is not a constructor".
const AutkDb = __autkDbMod.AutkDb || __autkDbMod.AutkSpatialDb;
// Old AutkSpatialDb does NOT export DEFAULT_WORKSPACE_COORDINATE_FORMAT — fall
// back to the hardcoded workspace CRS so the coordinateFormat injection below
// still gets a real value when the destructure resolves to undefined.
const DEFAULT_WORKSPACE_COORDINATE_FORMAT = __autkDbMod.DEFAULT_WORKSPACE_COORDINATE_FORMAT || 'EPSG:3395';
if (typeof AutkDb !== 'function') throw new Error('@urban-toolkit/autk-db: neither AutkDb nor AutkSpatialDb is exported');
const __sources = ${JSON.stringify(dataSources)};
const db = new AutkDb();
await db.init();
for (const source of __sources) {
  const { type, ...rest } = source ?? {};
  // Old AutkSpatialDb (root-level v2.0.1 install) dereferences
  // \`autoLoadLayers.coordinateFormat\` unconditionally — the spec must carry it
  // or loadOsm fails silently inside our try/catch and getLayerTables()
  // returns an empty list. Inject the workspace default when the spec omits it
  // so both export-name shapes work.
  if (type === 'osm' && rest.autoLoadLayers && !rest.autoLoadLayers.coordinateFormat) {
    rest.autoLoadLayers = { ...rest.autoLoadLayers, coordinateFormat: DEFAULT_WORKSPACE_COORDINATE_FORMAT };
  }
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
    const mod: any = await import('@urban-toolkit/autk-db');
    // Accept both the v2.0 frontend export (AutkDb) and the older root-level
    // install (AutkSpatialDb). Same dual-name handling as the backend sandbox JS.
    const AutkDbCtor = mod.AutkDb || mod.AutkSpatialDb;
    if (typeof AutkDbCtor !== 'function') {
        throw new Error('@urban-toolkit/autk-db: neither AutkDb nor AutkSpatialDb is exported');
    }
    // Old AutkSpatialDb does not export this; fall back to the workspace default.
    const DEFAULT_WORKSPACE_COORDINATE_FORMAT = mod.DEFAULT_WORKSPACE_COORDINATE_FORMAT || 'EPSG:3395';
    const db: any = new AutkDbCtor();
    await db.init();
    for (const source of (spec?.data ?? [])) {
        const { type, ...rest } = source ?? {};
        // Old AutkSpatialDb.loadOsm dereferences autoLoadLayers.coordinateFormat
        // unconditionally — inject the default when the spec omits it.
        if (type === 'osm' && rest.autoLoadLayers && !rest.autoLoadLayers.coordinateFormat) {
            rest.autoLoadLayers = { ...rest.autoLoadLayers, coordinateFormat: DEFAULT_WORKSPACE_COORDINATE_FORMAT };
        }
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

// Convert an autk-db-style layer array into a Curio Data Pool-compatible wrapper.
// The pool's `processDataAsync` recognizes `dataType: 'geodataframe'` (single layer)
// and `dataType: 'outputs'` (multi-layer envelope) — but not bare layer arrays. So
// when a compute-only or data-only autk-grammar node feeds a Data Pool, we wrap
// the output in a shape the pool can ingest, carrying `layerName`/`layerType`
// metadata at the wrapper level so downstream `resolveUpstreamLayers` can restore
// the original layer identity (e.g. `dataRef: "table_osm_buildings"`).
function layersToPoolWrapper(
    layers: Array<{ name: string; type: string; geojson: FeatureCollection }>,
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

// Normalize an attribute path used by `compute.attributes` into a dot-path
// `ComputeGpgpu` can resolve via `valueAtPath(feature, path)`. The grammar
// engine accepts bare property names like `"height"` and auto-prefixes them;
// `ComputeGpgpu` does not — it reads paths directly off the raw Feature,
// where `height` would be undefined but `properties.height` resolves. So
// prepend `properties.` for everything except paths the engine already
// understands as feature-root (`geometry.*` and explicit `properties.*`).
function normalizeAttrPath(p: string): string {
    if (typeof p !== 'string') return p;
    if (p === 'geometry' || p === 'properties') return p;
    if (p.startsWith('geometry.') || p.startsWith('properties.')) return p;
    return `properties.${p}`;
}

// Read a value out of a feature using a dot-path — same semantics autk-compute
// uses for its `variableMapping` attributes. Kept local rather than re-imported
// from autk-core because the grammar runtime here has no other dependency on it.
function valueAtPath(item: any, path: string): any {
    return path.split('.').reduce<any>((acc, key) => {
        if (acc == null || typeof acc !== 'object') return undefined;
        return acc[key];
    }, item);
}

// Resolve `fromFeature` directives in a `compute.uniforms` / `compute.uniformMatrices`
// config against the upstream layer array. Each entry in the config can be:
//   - a plain value (passed through unchanged)
//   - an object with a `fromFeature: { layer, index?, iterate?, path }` directive,
//     optionally carrying a `cols` field (signalling a matrix uniform) and/or a
//     `default` to fall back to when the path can't be resolved.
//
// `iterateIndex`, when defined, overrides the directive's own `index` for entries
// that opt into iteration via `iterate: 'all'`. This is how the per-feature
// iteration loop below drives the same spec over N source features.
function resolveFromFeatures(
    config: Record<string, any> | undefined,
    layers: Array<{ name: string; type?: string; geojson: FeatureCollection }>,
    iterateIndex?: number,
): Record<string, any> | undefined {
    if (!config) return config;
    const out: Record<string, any> = {};
    for (const [key, val] of Object.entries(config)) {
        if (val && typeof val === 'object' && (val as any).fromFeature) {
            const ff = (val as any).fromFeature;
            const layer = layers.find((l) => l.name === ff.layer);
            const idx = iterateIndex !== undefined && ff.iterate === 'all'
                ? iterateIndex
                : (ff.index ?? 0);
            const feature = layer?.geojson?.features?.[idx];
            const resolved = feature ? valueAtPath(feature, ff.path) : undefined;
            const hasCols = 'cols' in (val as any);
            if (resolved === undefined || resolved === null) {
                if ('default' in (val as any)) {
                    const def = (val as any).default;
                    out[key] = hasCols ? { ...(val as any), data: def, fromFeature: undefined } : def;
                }
                // No default → drop the entry; ComputeGpgpu will surface the error.
                continue;
            }
            const { fromFeature: _ff, default: _def, ...rest } = (val as any);
            out[key] = hasCols ? { ...rest, data: resolved } : resolved;
        } else {
            out[key] = val;
        }
    }
    return out;
}

// Walk the spec and return the iterate-source layer name + mode, or null when
// no entry opts into per-feature iteration. Two modes are supported:
//   - 'all'     → run the shader once per source feature and accumulate output
//                 columns (sum over features). Slow but trivial WGSL.
//   - 'batched' → pack every source feature's values into uniform arrays and
//                 run the shader exactly once; the WGSL loops over features
//                 inside. Fast and lets the shader express per-hour union /
//                 complement semantics across features.
// All iterating entries must share the same source layer; the first one wins
// (a tensor product over independent sources isn't a use case we need here).
function findIterateSource(
    ...configs: Array<Record<string, any> | undefined>
): { mode: 'all' | 'batched'; layer: string } | null {
    for (const cfg of configs) {
        if (!cfg) continue;
        for (const v of Object.values(cfg)) {
            const ff = v && typeof v === 'object' ? (v as any).fromFeature : undefined;
            if (ff && (ff.iterate === 'all' || ff.iterate === 'batched')) {
                return { mode: ff.iterate, layer: ff.layer };
            }
        }
    }
    return null;
}

// Hard cap on batched source features. ComputeGpgpu exposes uniformArrays via
// WebGPU uniform buffers, which DX12 limits to 64 KB. Each matrix entry packs
// 8 floats per source feature (the AABB's four corners, see below), so 2048
// features = exactly 64 KB; the cap is a margin below that.
const MAX_BATCHED_FEATURES = 1500;

// For the `batched` iteration mode, pack every source feature's resolved value
// into flat typed arrays exposed via ComputeGpgpu.uniformArrays:
//   - scalar uniforms become a length-N array under their original name
//   - matrix entries become a length-(8 × N) array under their original name,
//     holding each source feature's *axis-aligned bounding box* as four corners
//     [xmin,ymin, xmax,ymin, xmax,ymax, xmin,ymax]. Full polygon outlines blow
//     past the uniform buffer cap on Chicago-Loop-scale data; the AABB is a
//     correct conservative envelope (slightly over-estimates the projected
//     shadow for non-axis-aligned buildings, never under-estimates).
//   - a `num_features` uniform exposes the loop bound
// Non-batched entries in the same spec (e.g. `doy: 172`) pass through unchanged.
function buildBatchedUniforms(
    uniforms: Record<string, any> | undefined,
    uniformMatrices: Record<string, any> | undefined,
    sources: Feature<any, any>[],
): { uniforms: Record<string, number>; uniformArrays: Record<string, number[]> } {
    const outUniforms: Record<string, number> = {};
    const outUniformArrays: Record<string, number[]> = {};

    // Drop source features whose required batched paths can't resolve. A path
    // is required when any of its batched `fromFeature` directives carries
    // `required: true` — in 07 the building height is required, so OSM
    // buildings without a `properties.height` tag don't get a fake default
    // height that would over-extrude their shadow. The filter runs once,
    // upfront, so every batched entry sees the same surviving feature list.
    const requiredPaths: string[] = [];
    for (const cfg of [uniforms, uniformMatrices]) {
        if (!cfg) continue;
        for (const val of Object.values(cfg)) {
            const ff = val && typeof val === 'object' ? (val as any).fromFeature : undefined;
            if (ff && ff.iterate === 'batched' && ff.required && ff.path) {
                requiredPaths.push(ff.path);
            }
        }
    }
    if (requiredPaths.length > 0) {
        const before = sources.length;
        sources = sources.filter((f) =>
            requiredPaths.every((p) => {
                const v = valueAtPath(f, p);
                return v !== undefined && v !== null
                    && !(typeof v === 'number' && !Number.isFinite(v));
            }),
        );
        if (sources.length < before) {
            console.info(
                `[autk-grammar] batched compute filtered ${before - sources.length} source` +
                ` feature(s) missing required path(s): ${requiredPaths.join(', ')}`,
            );
        }
    }

    if (sources.length > MAX_BATCHED_FEATURES) {
        console.warn(
            `[autk-grammar] batched compute capped at ${MAX_BATCHED_FEATURES} source features` +
            ` (got ${sources.length}); excess features ignored.`,
        );
        sources = sources.slice(0, MAX_BATCHED_FEATURES);
    }

    for (const [key, val] of Object.entries(uniforms ?? {})) {
        const ff = val && typeof val === 'object' ? (val as any).fromFeature : undefined;
        if (ff && ff.iterate === 'batched') {
            const fallback = (val as any).default;
            const arr: number[] = [];
            for (const f of sources) {
                const v = valueAtPath(f, ff.path);
                const num = Number(v ?? fallback);
                arr.push(Number.isFinite(num) ? num : 0);
            }
            outUniformArrays[key] = arr;
        } else if (typeof val === 'number') {
            outUniforms[key] = val;
        }
    }

    for (const [key, val] of Object.entries(uniformMatrices ?? {})) {
        const ff = val && typeof val === 'object' ? (val as any).fromFeature : undefined;
        if (ff && ff.iterate === 'batched') {
            const data: number[] = [];
            for (const f of sources) {
                const ring = valueAtPath(f, ff.path);
                let xmin =  Infinity, ymin =  Infinity;
                let xmax = -Infinity, ymax = -Infinity;
                if (Array.isArray(ring)) {
                    for (const coord of ring) {
                        if (Array.isArray(coord) && coord.length >= 2) {
                            const x = Number(coord[0]);
                            const y = Number(coord[1]);
                            if (Number.isFinite(x) && Number.isFinite(y)) {
                                if (x < xmin) xmin = x;
                                if (y < ymin) ymin = y;
                                if (x > xmax) xmax = x;
                                if (y > ymax) ymax = y;
                            }
                        }
                    }
                }
                if (!Number.isFinite(xmin)) {
                    // Degenerate feature — emit a zero-area AABB at (0,0) so the
                    // shader's loop still runs but contributes nothing.
                    xmin = 0; ymin = 0; xmax = 0; ymax = 0;
                }
                data.push(xmin, ymin, xmax, ymin, xmax, ymax, xmin, ymax);
            }
            outUniformArrays[key] = data;
        }
    }

    outUniforms.num_features = sources.length;
    return { uniforms: outUniforms, uniformArrays: outUniformArrays };
}

// Apply a grammar `compute` section to an array of named GeoJSON layers,
// returning a new array where each block's target layer has been replaced by a
// FeatureCollection enriched with the WGSL output under `feature.properties.compute.<col>`.
// This is what makes a compute-only autk-grammar node useful: the grammar engine
// only runs compute when it's part of a render pipeline (map/plot), so without
// this helper, a node whose spec contains *only* a `compute` block would pass
// upstream through unchanged. We instead invoke `ComputeGpgpu` ourselves, which
// is the same GPGPU runner the grammar engine drives internally.
//
// A block whose `dataRef` doesn't match any upstream layer is skipped quietly:
// chained compute nodes can target different layers, and a no-op block is far
// less surprising than aborting the whole pipeline.
async function applyComputeBlocks(
    layers: Array<{ name: string; type: string; geojson: FeatureCollection }>,
    computeBlocks: any[],
): Promise<Array<{ name: string; type: string; geojson: FeatureCollection }>> {
    if (!Array.isArray(computeBlocks) || computeBlocks.length === 0) return layers;
    const { ComputeGpgpu } = await import('@urban-toolkit/autk-compute');
    let result = layers;
    for (const block of computeBlocks) {
        if (!block || !block.dataRef || !block.wglsFunction) continue;
        const idx = result.findIndex((l) => l.name === block.dataRef);
        if (idx < 0) continue;
        const variableMapping: Record<string, string> = {};
        for (const [k, v] of Object.entries(block.attributes ?? {})) {
            variableMapping[k] = normalizeAttrPath(String(v));
        }
        // Accept the wglsFunction as either a single string (existing form) or
        // an array of lines. The array form keeps the WGSL readable inside the
        // JSON file — JSON has no multi-line strings, but an array of one-line
        // strings is just as valid and far easier to author / review than one
        // long `\n`-escaped blob.
        const wgslBody: string = Array.isArray(block.wglsFunction)
            ? block.wglsFunction.join('\n')
            : String(block.wglsFunction ?? '');
        const params: any = {
            collection: result[idx].geojson,
            variableMapping,
            wgslBody,
        };
        if (block.attributeArrays) params.attributeArrays = block.attributeArrays;
        if (block.attributeMatrices) params.attributeMatrices = block.attributeMatrices;
        if (block.uniformArrays) params.uniformArrays = block.uniformArrays;
        if (block.outputColumnName) params.resultField = block.outputColumnName;
        if (block.outputColumns) params.outputColumns = block.outputColumns;
        const outCols: string[] = block.outputColumns ?? (block.outputColumnName ? [block.outputColumnName] : []);
        try {
            const gpgpu = new ComputeGpgpu();
            // Compute spec iteration modes — see `findIterateSource` for the full
            // semantics:
            //   - 'batched' → single dispatch; flat per-feature arrays exposed
            //                 as uniformArrays; WGSL loops over features.
            //   - 'all'     → N dispatches, runtime sums output columns.
            //   - undefined → single dispatch, plain spec (today's behaviour).
            const iterSource = findIterateSource(block.uniforms, block.uniformMatrices);
            let augmented: FeatureCollection;
            if (iterSource?.mode === 'batched') {
                const iterLayer = result.find((l) => l.name === iterSource.layer);
                const sources = iterLayer?.geojson?.features ?? [];
                const { uniforms: uf, uniformArrays: ua } = buildBatchedUniforms(
                    block.uniforms, block.uniformMatrices, sources as Feature<any, any>[],
                );
                params.uniforms = uf;
                params.uniformArrays = { ...(params.uniformArrays ?? {}), ...ua };
                // `uniformMatrices` were already absorbed into uniformArrays above.
                delete params.uniformMatrices;
                augmented = await gpgpu.run(params);
            } else if (iterSource?.mode === 'all') {
                const iterLayer = result.find((l) => l.name === iterSource.layer);
                const sources = iterLayer?.geojson?.features ?? [];
                augmented = JSON.parse(JSON.stringify(result[idx].geojson));
                for (const f of augmented.features) {
                    const p: any = (f.properties = f.properties ?? {});
                    const c: any = (p.compute = p.compute ?? {});
                    for (const col of outCols) c[col] = 0;
                }
                for (let i = 0; i < sources.length; i++) {
                    const stepUniforms = resolveFromFeatures(block.uniforms, result, i);
                    const stepMatrices = resolveFromFeatures(block.uniformMatrices, result, i);
                    const stepParams: any = {
                        ...params,
                        collection: augmented,
                    };
                    if (stepUniforms) stepParams.uniforms = stepUniforms;
                    if (stepMatrices) stepParams.uniformMatrices = stepMatrices;
                    const oneShot = await gpgpu.run(stepParams);
                    for (let j = 0; j < augmented.features.length; j++) {
                        const dst = (augmented.features[j].properties as any)?.compute;
                        const src = (oneShot.features[j]?.properties as any)?.compute;
                        if (!dst || !src) continue;
                        for (const col of outCols) {
                            const inc = Number(src[col]);
                            if (Number.isFinite(inc)) dst[col] += inc;
                        }
                    }
                }
            } else {
                if (block.uniforms) params.uniforms = resolveFromFeatures(block.uniforms, result);
                if (block.uniformMatrices) params.uniformMatrices = resolveFromFeatures(block.uniformMatrices, result);
                augmented = await gpgpu.run(params);
            }
            // ComputeGpgpu writes outputs under properties.compute.<col>. Also lift them
            // to top-level properties so downstream nodes can reference the column by
            // its bare name (e.g. `height_m`) without worrying about whether the nested
            // `compute` object round-trips through AutkDb's DuckDB storage. Both
            // `compute.<col>` and `<col>` dot-paths then resolve.
            if (outCols.length > 0 && augmented?.features) {
                for (const f of augmented.features) {
                    const p: any = f?.properties;
                    const c = p?.compute;
                    if (!p || !c) continue;
                    for (const col of outCols) {
                        if (col in c && !(col in p)) p[col] = c[col];
                    }
                }
            }
            // Re-attach the source crs hint so downstream re-loads keep coords aligned.
            const sourceCrs = (result[idx].geojson as any)?.crs;
            if (sourceCrs && augmented) (augmented as any).crs = sourceCrs;
            result = result.map((l, i) => (i === idx ? { ...l, geojson: augmented } : l));
        } catch (e) {
            console.warn(`[autk-grammar] compute block on '${block.dataRef}' failed`, e);
        }
    }
    return result;
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

    // Curio Data Pool wrapper round-trip: recognise the pool-compatible
    // shape produced by `layersToPoolWrapper` (and re-emitted by the pool
    // with `interacted` flags applied) before the generic envelope unwrap
    // strips the layerName/layerType metadata that lives at the wrapper level.
    if (typeof arg === 'object' && arg && arg.dataType === 'outputs' && Array.isArray(arg.data)) {
        const out: Array<{ name: string; fc: FeatureCollection; layerType?: string }> = [];
        arg.data.forEach((item: any, i: number) => {
            if (item && item.dataType === 'geodataframe' && item.data?.type === 'FeatureCollection') {
                out.push({
                    name: item.layerName ?? `upstream_${i}`,
                    fc: item.data as FeatureCollection,
                    layerType: item.layerType,
                });
            }
        });
        if (out.length > 0) return out;
    }
    if (typeof arg === 'object' && arg && arg.dataType === 'geodataframe' && arg.data) {
        const fc = arg.data;
        if (fc.type === 'FeatureCollection') {
            return [{
                name: arg.layerName ?? 'upstream',
                fc: fc as FeatureCollection,
                layerType: arg.layerType,
            }];
        }
    }

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

