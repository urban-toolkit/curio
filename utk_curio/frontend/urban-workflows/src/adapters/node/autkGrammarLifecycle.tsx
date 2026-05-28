import React, { useEffect, useRef } from 'react';
import { FeatureCollection } from 'geojson';
import { NodeLifecycleHook } from '../../registry/types';
import { fetchData } from '../../services/api';
import { useToastContext } from '../../providers/ToastProvider';
import { autkGrammarAdapter } from '../../adapters/autkGrammarAdapter';

export const useAutkGrammarLifecycle: NodeLifecycleHook = (data, nodeState) => {
    const { showToast } = useToastContext();
    const wrapperRef = useRef<HTMLDivElement>(null);

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
                    spec = {
                        ...spec,
                        data: [
                            { type: 'geojson', geojsonObject: fc, outputTableName: 'upstream' },
                            ...(spec.data ?? []),
                        ],
                    };
                }
            } catch {
                // Non-fatal: upstream injection is best-effort only
            }
        }

        const targets: Record<string, string> = {};
        if (hasMaps) targets.map = mapCanvasId;
        if (hasPlot && !hasMaps) targets.plot = plotDivId;

        nodeState.setOutput({ code: 'exec', content: '' });
        try {
            const { AutkGrammar } = await import('@urban-toolkit/autk-grammar');
            const grammar = new AutkGrammar(targets);
            await grammar.run(spec);

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
