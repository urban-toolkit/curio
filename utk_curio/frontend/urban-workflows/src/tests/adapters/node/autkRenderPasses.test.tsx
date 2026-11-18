/**
 * Render compute passes, autk-grammar 5's `"type": "render"`, on a map node
 * and in a compute step (adapters/node/autkGrammarBehavior,
 * autkComputeBlocks, autkComputeScopes, utils/autkInput).
 *
 * A render pass draws the tables its `layers` name from each feature of its
 * `viewpoints` table, on the GPU, and writes what the frames show as the table
 * `outputTableName`: the viewpoints' features, each with
 * `compute.render`, or one point per window with the `building-windows`
 * strategy (`resolveRender` in autk-grammar's adapters/compute.ts).
 *
 * - A map node loads the tables the pass names and hands the pass to the
 *   grammar's run, and counts the table it writes as one it has: a pick on it
 *   names the rows of the viewpoints' input table it holds.
 * - A pass over a table that has no rows is not handed on: autk-db holds no
 *   such table, so the grammar's run would fail on it. A render layer whose
 *   table has no rows draws nothing, and is left out of its pass.
 * - A compute step runs its passes through autk-grammar's own compute adapter
 *   (`createComputeAdapter`), the build the app bundles, and hands on each
 *   table a pass writes after the tables it holds.
 * - Every pass runs in error scopes on autk-compute's device, on a map node as
 *   in a compute step, so a pass the GPU refuses fails its node, named by the
 *   table it writes. A render layer of points fails with the grammar's own
 *   sentence, before anything is rendered.
 *
 * jsdom has no WebGPU: autk-compute is a stand-in whose render pipeline
 * answers what each test says (_support/autkComputeStandIns), and a map
 * node's grammar a stand-in that records what the node hands it
 * (_support/autkNodeMocks).
 */
import { act, renderHook, waitFor } from '@testing-library/react';

jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class { } }));
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => ({
    ...require('../../_support/autkComputeStandIns').grammarBuild(),
    ...require('../../_support/autkNodeMocks').autkGrammarModule,
  }),
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => require('../../_support/autkComputeStandIns').autkComputeModule, { virtual: true });
jest.mock('@urban-toolkit/autk-core', () => require('../../_support/autkComputeStandIns').autkCoreBuild());
jest.mock('@urban-toolkit/autk-map', () => require('../../_support/autkComputeStandIns').autkMapModule);
jest.mock('@urban-toolkit/autk-plot', () => require('../../_support/autkComputeStandIns').autkPlotModule);
// The tables a data section loads, as the browser's own loader reads them
// back: there is no sandbox here.
const mockLoaded: { layers: Array<{ name: string; type: string; features: any[] }> } = { layers: [] };
jest.mock(
  '@urban-toolkit/autk-db',
  () => ({
    AutkDb: class {
      async init() { }
      async loadGeojson() { }
      getLayersMetadata() {
        return mockLoaded.layers.map(({ name, type }) => ({ name, type }));
      }
      async getLayer(name: string) {
        const layer = mockLoaded.layers.find((l) => l.name === name);
        return {
          type: 'FeatureCollection',
          features: (layer?.features ?? []).map((f) => ({ ...f, properties: { ...f.properties } })),
        };
      }
    },
    DEFAULT_WORKSPACE_COORDINATE_FORMAT: 'EPSG:3395',
    DEFAULT_WORKSPACE_NAME: 'autk',
  }),
  { virtual: true },
);

import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';
import { autkNeedsInput, documentTableRefs, writtenTables } from '../../../utils/autkInput';
import {
  grammarComputes,
  grammarRuns as mockRuns,
  inputsByPath,
  resetAutkNodeMocks,
} from '../../_support/autkNodeMocks';
import { computeRuns, gpuErrors, resetComputeStandIns } from '../../_support/autkComputeStandIns';
import { lastSelection, mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import { UNIT_ROW, drawnAt, unitsCollection } from '../../_support/keyedSelections';

type Collection = { type: 'FeatureCollection'; features: any[] };

/** A building of *height* meters on the footprint west to east, south to north. */
function building(name: string, [west, south, east, north]: number[], height: number) {
  return {
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]] },
    properties: { name, height },
  };
}

/** Two towers 150 m tall near the Loop, with a street 20 m wide between them. */
function towers(): Collection {
  return {
    type: 'FeatureCollection',
    features: [
      building('west', [-87.635, 41.88, -87.63452, 41.8818], 150),
      building('east', [-87.63428, 41.88, -87.6338, 41.8818], 150),
    ],
  };
}

/** Where the frames are drawn from: a spot in the street between the towers, and one a kilometer away. */
function spots(): Collection {
  return {
    type: 'FeatureCollection',
    features: [
      { type: 'Feature', geometry: { type: 'Point', coordinates: [-87.6344, 41.8809] }, properties: { spot: 'street' } },
      { type: 'Feature', geometry: { type: 'Point', coordinates: [-87.647, 41.8809] }, properties: { spot: 'far' } },
    ],
  };
}

const none = (): Collection => ({ type: 'FeatureCollection', features: [] });

/** An upstream data node's tables, by name, type and rows: the towers and the spots, unless a test says. */
function city(tables: Array<[string, string, Collection]> = [['towers', 'buildings', towers()], ['spots', 'points', spots()]]) {
  return {
    dataType: 'outputs',
    data: tables.map(([layerName, layerType, data]) => ({ dataType: 'geodataframe', data, layerName, layerType })),
  };
}

/** Where a node finds the city: one input that brings its tables. */
const CITY = { path: 'art-city', dataType: 'outputs' };

const TOWERS = { id: 'towers', dataRef: 'towers', type: 'buildings' };

/** A render pass that writes `sky`: the towers seen from the spots, looking up at 45 degrees in four directions, the sky counted as a class. */
function skyPass(more: object = {}): any {
  return {
    type: 'render',
    outputTableName: 'sky',
    layers: [TOWERS],
    viewpoints: { dataRef: 'spots', sampling: { directions: 4, pitchDeg: 45 } },
    aggregation: { type: 'classes', includeBackground: true, backgroundLayerType: 'sky' },
    tileSize: 64,
    ...more,
  };
}

/** The same pass over the towers' windows, three rows of them on each facade: it writes `panes`. */
function windowsPass(more: object = {}): any {
  return {
    type: 'render',
    outputTableName: 'panes',
    layers: [TOWERS],
    viewpoints: { dataRef: 'towers', strategy: { type: 'building-windows', floors: 3 } },
    aggregation: { type: 'classes' },
    ...more,
  };
}

/** The share of buildings each spot sees, by spot, as the stand-in render pipeline says it. */
const BUILDINGS = [0.75, 0.125];

/** What the stand-in render pipeline writes: each viewpoint with the share of its frames each class covers. */
function seen(params: any): Collection {
  const viewpoints = params.viewpoints.collection;
  return {
    ...viewpoints,
    features: viewpoints.features.map((f: any, i: number) => ({
      ...f,
      properties: {
        ...f.properties,
        compute: {
          ...(f.properties?.compute ?? {}),
          render: { sampleCount: 4, classes: { buildings: BUILDINGS[i], sky: 1 - BUILDINGS[i] } },
        },
      },
    })),
  };
}

/** What the stand-in render pipeline writes of building windows: *count* points, one per window. */
function windowPoints(count: number): Collection {
  return {
    type: 'FeatureCollection',
    features: Array.from({ length: count }, (_, i) => ({
      type: 'Feature',
      id: `0:0:0:0:${i}:0:0`,
      geometry: { type: 'Point', coordinates: [-87.635 + i * 0.0001, 41.88, 25] },
      properties: { windowId: `0:0:0:0:${i}:0:0`, compute: { render: { sampleCount: 3, classes: { buildings: 0.5 } } } },
    })),
  };
}

/** A node fed the city, as a node of the canvas is. */
const mountCity = (nodeId: string) => mountAutkNode(nodeId, undefined, { input: CITY });

/** A compute step: a node whose run hands on what it made, as a node of the canvas does. */
function mountStep(nodeId: string, input: unknown = '') {
  const outputCallback = jest.fn();
  const setOutput = jest.fn();
  const { result } = renderHook(() => useAutkGrammarBehavior(
    { nodeId, input, defaultCode: '{}', outputCallback, interactionsCallback: jest.fn() } as any,
    { output: { code: '', content: '' }, setOutput, setCode: jest.fn(), templateData: {} } as any,
  ));
  return {
    run: async (spec: object) => {
      await act(async () => { await result.current.applyGrammar!(JSON.stringify(spec)); });
    },
    handedOn: () => outputCallback.mock.calls.map((call) => call[1]),
    lastOutput: () => setOutput.mock.calls[setOutput.mock.calls.length - 1]?.[0],
  };
}

beforeEach(() => {
  resetAutkNodeMocks();
  resetComputeStandIns();
  mockLoaded.layers = [];
  inputsByPath.current = { 'art-city': city() };
  stubWebGpu();
});

afterEach(() => {
  unstubWebGpu();
});

describe('the tables a render pass reads and writes', () => {
  test('it reads its viewpoints and the tables of its layers', () => {
    expect(documentTableRefs({ compute: [skyPass()] }).sort()).toEqual(['spots', 'towers']);
  });

  test("it writes its table: of its viewpoints' rows, typed as the pass says, or of windows, which are points", () => {
    expect(writtenTables({ compute: [skyPass(), windowsPass(), skyPass({ outputTableName: 'sky_shapes', layerType: 'polygons' })] })).toEqual([
      { name: 'sky', from: 'spots', holdsRows: true },
      { name: 'panes', from: 'towers', holdsRows: false, layerType: 'points' },
      { name: 'sky_shapes', from: 'spots', holdsRows: true, layerType: 'polygons' },
    ]);
  });

  test('a document that loads the tables it renders asks for no connection', () => {
    expect(autkNeedsInput({
      data: [
        { type: 'geojson', outputTableName: 'towers', geojsonObject: towers() },
        { type: 'geojson', outputTableName: 'spots', geojsonObject: spots() },
      ],
      compute: [skyPass()],
      map: { layerRefs: [{ dataRef: 'sky' }] },
    })).toBe(false);
  });
});

describe('a map node runs a render pass in the grammar\'s run', () => {
  test('it loads the tables the pass names, hands the pass to the grammar and draws the table it writes', async () => {
    const node = mountCity('render-map');
    const map = { layerRefs: [{ dataRef: 'sky', getFnv: 'compute.render.classes.sky' }] };

    await node.run({ compute: [skyPass()], map });

    expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
    expect(mockRuns).toHaveLength(1);
    expect(mockRuns[0].spec.compute).toEqual([skyPass()]);
    expect(mockRuns[0].spec.map).toEqual(map);
    expect(mockRuns[0].spec.data.map((s: any) => s.outputTableName)).toEqual(['towers', 'spots']);
  });

  test("a pick on its table names the rows of the viewpoints' input table, and a selection of them lights it", async () => {
    const units = unitsCollection() as any;
    // The input row of unit 103 comes selected, as a Data Pool marks it.
    units.features[UNIT_ROW[103]].properties.interacted = '1';
    const node = mountAutkNode('render-pick', units);

    await node.run({
      compute: [{
        type: 'render', outputTableName: 'seen', layers: [{ id: 'units', dataRef: 'input_0', type: 'buildings' }],
        viewpoints: { dataRef: 'input_0' }, aggregation: { type: 'classes' },
      }],
      map: { layerRefs: [{ dataRef: 'seen', isPick: true }] },
    });
    expect(node.lastOutput()).toEqual({ code: 'success', content: '' });

    // Lit where the map draws the input's row.
    await waitFor(() => expect(mockRuns[0].highlights).toContainEqual(['seen', [drawnAt(UNIT_ROW[103])]]));
    act(() => mockRuns[0].pick([drawnAt(UNIT_ROW[103])]));
    expect(lastSelection(node)).toEqual(expect.objectContaining({ data: [UNIT_ROW[103]], layerRef: 'input_0' }));
  });

  test("a pick on a table of building windows names its own rows: they are windows, not the input's", async () => {
    const node = mountAutkNode('render-windows', unitsCollection());

    await node.run({
      compute: [windowsPass({ layers: [{ id: 'units', dataRef: 'input_0', type: 'buildings' }], viewpoints: { dataRef: 'input_0', strategy: { type: 'building-windows', floors: 2 } } })],
      map: { layerRefs: [{ dataRef: 'panes', isPick: true }] },
    });
    expect(node.lastOutput()).toEqual({ code: 'success', content: '' });

    act(() => mockRuns[0].pick([2]));
    expect(lastSelection(node)).toEqual(expect.objectContaining({ data: [2], layerRef: 'panes' }));
  });

  test('a render layer whose table has no rows is left out of its pass, which draws nothing of it', async () => {
    inputsByPath.current = { 'art-city': city([['towers', 'buildings', towers()], ['spots', 'points', spots()], ['parks', 'parks', none()]]) };
    const node = mountCity('render-parks');

    await node.run({
      compute: [skyPass({ layers: [TOWERS, { id: 'parks', dataRef: 'parks', type: 'parks' }] })],
      map: { layerRefs: [{ dataRef: 'sky' }] },
    });

    expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
    expect(mockRuns[0].spec.compute).toEqual([skyPass()]);
    expect(mockRuns[0].spec.data.map((s: any) => s.outputTableName)).toEqual(['towers', 'spots']);
  });

  test('a render pass whose viewpoints have no rows does not run, and a map of its table says what a map of an empty table says', async () => {
    inputsByPath.current = { 'art-city': city([['towers', 'buildings', towers()], ['spots', 'points', none()]]) };
    const ofSource = mountCity('spots-map');
    await ofSource.run({ map: { layerRefs: [{ dataRef: 'spots' }] } });
    const ofWritten = mountCity('sky-map');
    await ofWritten.run({ compute: [skyPass()], map: { layerRefs: [{ dataRef: 'sky' }] } });

    const said = ofSource.lastOutput();
    expect(said).toEqual(expect.objectContaining({ code: 'error', kind: 'empty-render:no-input-rows' }));
    expect(ofWritten.lastOutput()).toEqual(said);
    expect(mockRuns).toHaveLength(0);
  });

  test('a GPGPU pass over a table with no rows is not handed to the grammar, which would fail on it, and the rest is drawn', async () => {
    const blocks = towers().features.map((f) => ({ ...f, properties: { block: f.properties.name } }));
    mockLoaded.layers = [{ name: 'blocks', type: 'polygons', features: blocks }];
    const node = mountAutkNode('empty-pass', none());

    await node.run({
      data: [{ type: 'geojson', outputTableName: 'blocks', geojsonObject: { type: 'FeatureCollection', features: blocks } }],
      compute: [{ dataRef: 'input_0', attributes: { v: 'value' }, wgslFunction: 'return v * 2.0;', outputColumnName: 'twice', outputTableName: 'doubled' }],
      map: { layerRefs: [{ dataRef: 'blocks' }, { dataRef: 'doubled' }] },
    });

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    expect(mockRuns).toHaveLength(1);
    expect(mockRuns[0].spec.compute).toEqual([]);
    expect(mockRuns[0].spec.map.layerRefs).toEqual([{ dataRef: 'blocks' }]);
  });
});

describe('a compute step runs its render passes through autk-grammar\'s compute adapter', () => {
  test('it hands on the table a render pass writes after the tables it holds, typed as its viewpoints', async () => {
    computeRuns.render.mockImplementation(async (params: any) => seen(params));
    const step = mountStep('render-step', CITY);

    await step.run({ compute: [skyPass()] });

    expect(step.lastOutput()).toEqual({ code: 'success', content: 'Computed 3 layers: towers (2 rows), spots (2 rows), sky (2 rows)' });
    const [handed] = step.handedOn();
    expect(handed.dataType).toBe('outputs');
    expect(handed.data.map((l: any) => [l.layerName, l.layerType])).toEqual([['towers', 'buildings'], ['spots', 'points'], ['sky', 'points']]);
    expect(handed.data[2].data.features.map((f: any) => [f.properties.spot, f.properties.compute.render.classes])).toEqual([
      ['street', { buildings: 0.75, sky: 0.25 }],
      ['far', { buildings: 0.125, sky: 0.875 }],
    ]);
    // The spots it was computed from are handed on as they were.
    expect(handed.data[1].data.features.map((f: any) => f.properties)).toEqual([{ spot: 'street' }, { spot: 'far' }]);

    // The grammar handed autk-compute the pass: its layer, its viewpoints, how it counts and its frames.
    expect(computeRuns.render).toHaveBeenCalledTimes(1);
    const params = computeRuns.render.mock.calls[0][0];
    expect(params.layers.map((l: any) => [l.id, l.type, l.collection.features.map((f: any) => f.properties.name)]))
      .toEqual([['towers', 'buildings', ['west', 'east']]]);
    expect(params.viewpoints.collection.features.map((f: any) => f.properties.spot)).toEqual(['street', 'far']);
    expect(params.viewpoints.sampling).toEqual({ directions: 4, pitchDeg: 45 });
    expect(params.aggregation).toEqual(skyPass().aggregation);
    expect(params.tileSize).toBe(64);
  });

  test('it hands on a table of building windows as points, one per window', async () => {
    computeRuns.render.mockImplementation(async () => windowPoints(3));
    const step = mountStep('windows-step', CITY);

    await step.run({ compute: [windowsPass()] });

    const [handed] = step.handedOn();
    expect(handed.data.map((l: any) => [l.layerName, l.layerType, l.data.features.length]))
      .toEqual([['towers', 'buildings', 2], ['spots', 'points', 2], ['panes', 'points', 3]]);
  });

  test('a render layer of points fails the step with the grammar\'s own sentence, and nothing is rendered or handed on', async () => {
    const step = mountStep('points-step', CITY);

    await step.run({ compute: [skyPass({ layers: [{ id: 'spots', dataRef: 'spots', type: 'points' }] })] });

    expect(step.lastOutput()).toEqual({
      code: 'error',
      content: 'Compute failed: sky: Render pass "sky": layer "spots" has the type "points", which a render pass cannot draw. '
        + "A layer's type is one of surface, parks, water, roads, buildings, polygons, polylines.",
    });
    expect(computeRuns.render).not.toHaveBeenCalled();
    expect(step.handedOn()).toEqual([]);
  });
});

describe('a pass the GPU refuses fails its node, named by the table it writes', () => {
  test('a compute step\'s render pass, and nothing is handed on', async () => {
    gpuErrors.next = { validation: 'Binding size is smaller than the minimum binding size' };
    const step = mountStep('refused-step', CITY);

    await step.run({ compute: [skyPass()] });

    expect(step.lastOutput()).toEqual({
      code: 'error',
      content: 'Compute failed: sky: the GPU could not run this compute pass: Binding size is smaller than the minimum binding size',
    });
    expect(step.handedOn()).toEqual([]);
  });

  test('a map node\'s render pass', async () => {
    grammarComputes.on = true;
    gpuErrors.next = { internal: 'CreateRenderPipeline failed with VK_ERROR_UNKNOWN\n - While initializing [RenderPipeline]' };
    const node = mountCity('refused-map');

    await node.run({ compute: [skyPass()], map: { layerRefs: [{ dataRef: 'sky' }] } });

    expect(node.lastOutput()).toEqual({
      code: 'error',
      content: 'sky: the GPU could not run this compute pass: CreateRenderPipeline failed with VK_ERROR_UNKNOWN',
    });
  });

  test('a map node\'s GPGPU pass, as a compute step\'s', async () => {
    grammarComputes.on = true;
    gpuErrors.next = { validation: 'Binding size is smaller than the minimum binding size' };
    const node = mountAutkNode('refused-gpgpu', towers());

    await node.run({
      compute: [{ dataRef: 'input_0', attributes: { h: 'height' }, wgslFunction: 'return h * 2.0;', outputColumnName: 'twice', outputTableName: 'doubled' }],
      map: { layerRefs: [{ dataRef: 'doubled' }] },
    });

    expect(node.lastOutput()).toEqual({
      code: 'error',
      content: 'doubled: the GPU could not run this compute pass: Binding size is smaller than the minimum binding size',
    });
  });
});
