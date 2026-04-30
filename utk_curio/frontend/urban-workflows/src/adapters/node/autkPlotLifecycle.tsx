import { createAutkLifecycle } from './autkLifecycleFactory';

const DEFAULT_CODE = `// 'arg' is the data from the upstream node.
// 'container' is the div element rendered inside this node.
// 'AutkChart' is imported from autk-plot automatically.
//
// AutkChart types: 'scatterplot' | 'barchart' | 'linechart' |
//                  'heatmatrix' | 'parallel-coordinates' | 'table'
//
// 'arg' may be an Autark layer array, a single FeatureCollection, or a
// DataFrame — pick the shape your chart needs:
const collection = Array.isArray(arg) ? arg[0]?.geojson : arg;

// Return the AutkChart instance to enable bidirectional brushing with the map.
return new AutkChart(container, {
    type: 'scatterplot',
    collection,
    attributes: { axis: ['x', 'y'] },
    labels: { title: 'Chart' },
});`;

export const useAutkPlotLifecycle = createAutkLifecycle({
    // autk-plot's package.json points types to a non-existent path; cast to skip resolution.
    moduleImport: () => import('autk-plot' as any),
    globals: ['AutkChart'],
    container: 'div',
    defaultCode: DEFAULT_CODE,
    bidirectional: true,
    autoWrapFeatureCollection: false,
    bindInteractions: (chart, emit) => {
        if (chart?.events?.on) {
            const forward = (kind: string) => ({ selection }: any) => {
                emit({ autk: { kind: 'chart-' + kind, selection } });
            };
            chart.events.on('click', forward('click'));
            chart.events.on('brush', forward('brush'));
            chart.events.on('brushX', forward('brushX'));
            chart.events.on('brushY', forward('brushY'));
        }
    },
    applyInteractions: (chart, interactions) => {
        if (typeof chart?.setSelection !== 'function') return;
        for (const i of interactions) {
            const detail = i?.details?.autk;
            if (!detail) continue;
            if (detail.kind === 'pick' || detail.kind === 'highlight') {
                chart.setSelection(detail.selection ?? []);
            }
        }
    },
});
