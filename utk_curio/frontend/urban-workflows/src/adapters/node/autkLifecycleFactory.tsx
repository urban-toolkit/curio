import React, { useCallback, useEffect, useRef } from 'react';
import { NodeLifecycleHook } from '../../registry/types';
import { fetchData } from '../../services/api';

/** Container element kind rendered inside the node body. */
type AutkContainer = 'canvas' | 'div' | 'hidden';

/**
 * Configuration for an Autark client-side lifecycle hook.
 *
 * The factory consolidates the React-y boilerplate (refs, run effect,
 * artifact resolution, code execution, output reporting). Each per-module
 * lifecycle file declares only the variations.
 */
export interface AutkLifecycleConfig {
    /** Lazily import the autk module — keeps it out of the initial bundle. */
    moduleImport: () => Promise<any>;
    /**
     * Names extracted from the imported module and bound as globals in the
     * user's `new Function(...)` call. Order matters and must match the
     * names referenced in `defaultCode`.
     */
    globals: string[];
    /** Container element kind. `'hidden'` mounts a `display:none` `<canvas>` for offscreen GPU work. */
    container: AutkContainer;
    /** Inline style applied to the visible container wrapper. */
    containerStyle?: React.CSSProperties;
    /** Default user code shown in the editor. */
    defaultCode: string;
    /**
     * When true, the user's `return` value is forwarded to downstream nodes
     * via `data.outputCallback`. Used by AUTK_COMPUTE.
     */
    emitsOutput?: boolean;
    /**
     * When true, the user's `return` value is captured as the autk instance
     * and `bindInteractions` is wired up. Used by AUTK_MAP / AUTK_PLOT.
     */
    bidirectional?: boolean;
    /**
     * Subscribe the autk instance to selection events and forward them via
     * the supplied `emit` callback. Called once after the user's code returns
     * the instance.
     */
    bindInteractions?: (instance: any, emit: (interactions: any) => void) => void;
    /**
     * Apply incoming propagation/interaction state to the autk instance.
     * Called whenever `data.newPropagation` changes.
     */
    applyInteractions?: (instance: any, interactions: any) => void;
    /**
     * When true, single FeatureCollections / GeoDataFrames are wrapped as a
     * one-element layer-array so non-Autark upstream nodes (e.g. a Python
     * DataTransformation emitting a GeoDataFrame) can feed AutkMap or
     * AutkCompute directly without a manual JS bridge.
     */
    autoWrapFeatureCollection?: boolean;
    /**
     * Optional serializer called on the OLD instance just before it is torn
     * down by a rerun. Whatever it returns is handed to `restoreState` once
     * the new instance has been built. Used to preserve transient UI state
     * (selection/highlight) across input-driven reruns.
     */
    serializeState?: (instance: any) => any;
    /**
     * Optional restorer called on the NEW instance after the user's code has
     * returned and `bindInteractions` has run. Receives whatever
     * `serializeState` returned for the previous instance.
     */
    restoreState?: (instance: any, state: any) => void;
    /**
     * Optional fast-path. Called when ``data.input`` changes but the
     * resolved ``arg`` differs from the previous one only in selection
     * state (i.e. ``properties.interacted``). When it returns a directive
     * the factory will skip the full ``runCode`` rebuild and instead apply
     * the directive's ``selectionByLayer`` map to the existing instance —
     * avoiding the WebGPU teardown/rebuild that otherwise leaks GPU memory
     * during high-frequency feedback loops (e.g. linked Vega → DataPool →
     * AutkMap on hover).
     *
     * Return ``false`` (or anything falsy) to fall back to the normal
     * full rerun path.
     */
    skipRerunIf?: (newArg: any, oldArg: any) => false | { selectionByLayer: Record<string, number[]> };
}

/**
 * Normalize a node's raw input into a shape Autark code can consume.
 *
 * Handles the four shapes that show up in practice:
 *   1. `{path: <id>}` — a DuckDB artifact reference; fetch + unwrap.
 *   2. `{dataType, data}` — a fetched artifact envelope; unwrap to `data`.
 *   3. `Array<{data, dataType}>` — a JS_COMPUTATION list output where each
 *      element was envelope-wrapped; unwrap each.
 *   4. `FeatureCollection` (raw or in-envelope as a GeoDataFrame) — when
 *      `autoWrap` is true, package as a single-layer array so it's
 *      drop-in compatible with code that expects the layer-array shape.
 */
async function resolveAutkInput(raw: any, autoWrap: boolean): Promise<any> {
    if (raw == null || raw === '') return autoWrap ? [] : raw;

    let arg: any = raw;

    if (typeof arg === 'object' && arg !== null && arg.path) {
        const fetched = await fetchData(arg.path);
        arg = fetched ?? null;
    }

    let envelopeDataType: string | undefined;
    if (arg && typeof arg === 'object' && 'dataType' in arg && 'data' in arg) {
        envelopeDataType = arg.dataType;
        arg = arg.data;
    }

    if (Array.isArray(arg)) {
        arg = arg.map((e: any) =>
            e && typeof e === 'object' && 'data' in e && 'dataType' in e ? e.data : e
        );
    }

    if (autoWrap && arg && typeof arg === 'object' && !Array.isArray(arg) && arg.type === 'FeatureCollection') {
        const inferredType = inferLayerTypeFromGeometry(arg.features?.[0]?.geometry?.type);
        return [{ name: 'layer', type: inferredType, geojson: arg }];
    }

    if (autoWrap && envelopeDataType === 'geodataframe' && arg && arg.type === 'FeatureCollection') {
        const inferredType = inferLayerTypeFromGeometry(arg.features?.[0]?.geometry?.type);
        return [{ name: 'layer', type: inferredType, geojson: arg }];
    }

    return arg;
}

function inferLayerTypeFromGeometry(geomType: string | undefined): string {
    switch (geomType) {
        case 'Point':
        case 'MultiPoint':
            return 'POINTS_2D';
        case 'LineString':
        case 'MultiLineString':
            return 'POLYLINES_2D';
        case 'Polygon':
        case 'MultiPolygon':
            return 'POLYGONS_2D';
        default:
            return 'POLYGONS_2D';
    }
}

/**
 * Build a `NodeLifecycleHook` from a per-module config.
 *
 * Returned hook handles: container ref creation, input resolution, lazy
 * module import, `new Function` execution with module globals bound, output
 * reporting (local node state + downstream callback), and bidirectional
 * interaction wiring for visualization nodes.
 */
export function createAutkLifecycle(config: AutkLifecycleConfig): NodeLifecycleHook {
    return function useAutkLifecycle(data, nodeState) {
        const containerRef = useRef<HTMLCanvasElement | HTMLDivElement | null>(null);
        const instanceRef = useRef<any>(null);
        const interactionsBoundRef = useRef(false);
        // Most recent resolved input arg, kept so ``skipRerunIf`` can diff
        // a fresh input against it before deciding whether to rebuild.
        const lastResolvedArgRef = useRef<any>(null);

        const runCode = useCallback(
            async (code: string) => {
                if (config.container !== 'hidden' && !containerRef.current) return;
                const containerEl = containerRef.current;

                // Fast path: if the new input differs from the last one only in
                // selection state, ``skipRerunIf`` returns a directive telling
                // us which features to highlight. Apply it to the live
                // instance and bail out before any teardown/rebuild. This is
                // what keeps Vega → DataPool → AutkMap feedback loops from
                // leaking WebGPU memory during high-frequency hover events.
                if (
                    config.skipRerunIf
                    && instanceRef.current
                    && lastResolvedArgRef.current != null
                ) {
                    let resolvedNewArg: any;
                    try {
                        resolvedNewArg = await resolveAutkInput(
                            data.input,
                            !!config.autoWrapFeatureCollection,
                        );
                    } catch {
                        resolvedNewArg = undefined;
                    }
                    if (resolvedNewArg !== undefined) {
                        let directive: false | { selectionByLayer: Record<string, number[]> } = false;
                        try {
                            directive = config.skipRerunIf(resolvedNewArg, lastResolvedArgRef.current);
                        } catch (e) {
                            console.warn('Autark skipRerunIf failed:', e);
                            directive = false;
                        }
                        if (directive && directive.selectionByLayer) {
                            try {
                                for (const [layerId, ids] of Object.entries(directive.selectionByLayer)) {
                                    if (typeof instanceRef.current.setHighlightedIds === 'function') {
                                        instanceRef.current.setHighlightedIds(layerId, ids);
                                    }
                                }
                                if (typeof instanceRef.current.draw === 'function') {
                                    instanceRef.current.draw();
                                }
                                lastResolvedArgRef.current = resolvedNewArg;
                                nodeState.setOutput({ code: 'success', content: '' });
                                return;
                            } catch (e) {
                                console.warn('Autark fast-path apply failed; falling back to full rerun:', e);
                                // Fall through to the full rebuild below.
                            }
                        }
                    }
                }

                if (containerEl && config.container === 'div') {
                    containerEl.innerHTML = '';
                }
                // Snapshot transient state (e.g. picking selection) from the
                // outgoing instance before it is replaced. The new instance
                // will rehydrate from this in the post-bindInteractions step
                // so an input-driven rerun does not visibly clear the user's
                // current selection.
                let savedState: any = undefined;
                if (config.serializeState && instanceRef.current) {
                    try {
                        savedState = config.serializeState(instanceRef.current);
                    } catch (e) {
                        console.warn('Autark serializeState failed:', e);
                    }
                }
                // Tear down the outgoing instance before allocating a new one.
                // For AutkMap this releases WebGPU buffers/textures, cancels
                // the animation frame, and removes the legend UI elements
                // appended to the canvas wrapper. Without this, every
                // input-driven rerun (e.g. linked Vega → DataPool feedback)
                // leaks GPU memory and stacks duplicate legend DOM, which
                // eventually surfaces as
                // ``DOMException: Not enough memory left`` and a
                // ``WebGPU is not available`` renderer init failure.
                if (instanceRef.current && typeof instanceRef.current.destroy === 'function') {
                    try {
                        instanceRef.current.destroy();
                    } catch (e) {
                        console.warn('Autark instance destroy failed:', e);
                    }
                }
                interactionsBoundRef.current = false;
                instanceRef.current = null;

                let arg: any;
                try {
                    arg = await resolveAutkInput(data.input, !!config.autoWrapFeatureCollection);
                } catch {
                    nodeState.setOutput({ code: 'error', content: 'Failed to fetch input data.' });
                    return;
                }
                // Cache the resolved input so the next ``data.input`` change
                // can diff against it via ``skipRerunIf``.
                lastResolvedArgRef.current = arg;

                nodeState.setOutput({ code: 'exec', content: '' });
                try {
                    const mod = await config.moduleImport();
                    const globalValues = config.globals.map((name) => mod[name]);

                    const fn = new Function(
                        'arg',
                        'container',
                        ...config.globals,
                        `return (async () => { ${code} })();`
                    );
                    const returnValue = await fn(arg, containerEl, ...globalValues);

                    if (config.bidirectional && returnValue) {
                        instanceRef.current = returnValue;
                        if (config.bindInteractions && !interactionsBoundRef.current) {
                            const emit = (interactions: any) => {
                                if (data.interactionsCallback) {
                                    data.interactionsCallback(interactions, data.nodeId);
                                }
                            };
                            try {
                                config.bindInteractions(returnValue, emit);
                                interactionsBoundRef.current = true;
                            } catch (e) {
                                console.warn('Autark bindInteractions failed:', e);
                            }
                        }
                        if (config.restoreState && savedState !== undefined) {
                            try {
                                config.restoreState(returnValue, savedState);
                            } catch (e) {
                                console.warn('Autark restoreState failed:', e);
                            }
                        }
                    }

                    if (config.emitsOutput && data.outputCallback) {
                        data.outputCallback(data.nodeId, returnValue);
                    }

                    nodeState.setOutput({
                        code: 'success',
                        content: config.emitsOutput ? returnValue : '',
                    });
                } catch (err: any) {
                    nodeState.setOutput({ code: 'error', content: err?.message ?? String(err) });
                }
            },
            // eslint-disable-next-line react-hooks/exhaustive-deps
            [data.input]
        );

        useEffect(() => {
            if (data.input) {
                runCode(nodeState.code || config.defaultCode);
            }
            // eslint-disable-next-line react-hooks/exhaustive-deps
        }, [data.input]);

        useEffect(() => {
            if (!config.bidirectional || !config.applyInteractions || !instanceRef.current) return;
            if (!data.interactions || data.interactions.length === 0) return;
            const fromOthers = data.interactions.filter((i: any) => i.nodeId !== data.nodeId);
            if (fromOthers.length === 0) return;
            try {
                config.applyInteractions(instanceRef.current, fromOthers);
            } catch (e) {
                console.warn('Autark applyInteractions failed:', e);
            }
            // eslint-disable-next-line react-hooks/exhaustive-deps
        }, [data.interactions]);

        // Forward node-container resizes to autk modules.
        // AutkMap binds only to `window.resize`, so when the user drags the
        // node resize handle nothing fires. Sizing the wrapper via CSS
        // `height: 100%` is fragile because it relies on every parent in the
        // Tab.Pane chain having a definite height. Instead, observe the
        // wrapper's parent (the Tab.Pane) and pin the wrapper to its
        // pixel dimensions, then dispatch a synthetic window.resize so
        // AutkMap's existing handler picks the new dims up.
        useEffect(() => {
            if (config.container !== 'canvas') return;
            const wrapper = containerRef.current?.parentElement;
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

        // Memoize so the JSX reference is stable across re-renders that don't
        // change the output. NodeEditor auto-switches to the "output" tab
        // whenever `contentComponent` changes identity. Keying on
        // `nodeState.output` keeps the reference stable on incidental rerenders
        // (e.g. React Flow deselecting the node on a pane click) but rebuilds
        // it when the node finishes a run — so a successful run still moves
        // the user to the output tab.
        const contentComponent = React.useMemo<React.ReactNode>(() => {
            // `nodrag nopan nowheel` opts the autk container out of React Flow's
            // node drag, viewport pan, and wheel handling so clicks/brushes/wheel
            // inside the canvas or chart go to autk-map / autk-plot instead of
            // dragging the node.
            const interactionClass = 'nodrag nopan nowheel';
            if (config.container === 'canvas') {
                // `position: relative` makes the wrapper the canvas's offsetParent.
                // autk-map's UI overlays (legend, menu, perf) are appended here and
                // positioned via `canvas.offsetTop/Left` — without this they'd be
                // measured against a far-up ancestor and land outside the node.
                return (
                    <div
                        className={interactionClass}
                        style={
                            config.containerStyle ?? {
                                position: 'relative',
                                width: '100%',
                                height: '100%',
                                minHeight: 400,
                                overflow: 'hidden',
                            }
                        }
                    >
                        <canvas
                            ref={containerRef as React.RefObject<HTMLCanvasElement>}
                            style={{ display: 'block', width: '100%', height: '100%' }}
                        />
                    </div>
                );
            }
            if (config.container === 'div') {
                return (
                    <div
                        className={interactionClass}
                        style={config.containerStyle ?? { width: '100%', minHeight: 400, overflow: 'auto' }}
                    >
                        <div ref={containerRef as React.RefObject<HTMLDivElement>} />
                    </div>
                );
            }
            return (
                <div style={{ display: 'none' }}>
                    <canvas ref={containerRef as React.RefObject<HTMLCanvasElement>} width={1} height={1} />
                </div>
            );
        }, [nodeState.output]);

        // Only seed the boilerplate when the node has no code yet (fresh palette drop).
        // When loading an example, data.defaultCode carries the example's content and
        // must take precedence.
        const hasExistingCode = !!(data.defaultCode || (data as any).code);

        return {
            contentComponent,
            defaultValueOverride: hasExistingCode ? undefined : config.defaultCode,
            sendCodeOverride: runCode,
        };
    };
}
