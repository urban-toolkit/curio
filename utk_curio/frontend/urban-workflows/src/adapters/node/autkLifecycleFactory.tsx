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

        const runCode = useCallback(
            async (code: string) => {
                if (config.container !== 'hidden' && !containerRef.current) return;
                const containerEl = containerRef.current;

                if (containerEl && config.container === 'div') {
                    containerEl.innerHTML = '';
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

        let contentComponent: React.ReactNode;
        if (config.container === 'canvas') {
            contentComponent = (
                <div style={config.containerStyle ?? { width: '100%', height: 400, overflow: 'hidden' }}>
                    <canvas
                        ref={containerRef as React.RefObject<HTMLCanvasElement>}
                        width={600}
                        height={400}
                    />
                </div>
            );
        } else if (config.container === 'div') {
            contentComponent = (
                <div style={config.containerStyle ?? { width: '100%', minHeight: 400, overflow: 'auto' }}>
                    <div ref={containerRef as React.RefObject<HTMLDivElement>} />
                </div>
            );
        } else {
            contentComponent = (
                <div style={{ display: 'none' }}>
                    <canvas ref={containerRef as React.RefObject<HTMLCanvasElement>} width={1} height={1} />
                </div>
            );
        }

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
