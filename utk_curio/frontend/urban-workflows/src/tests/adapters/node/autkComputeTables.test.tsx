/**
 * Compute passes that write a new table, and a document with data and compute
 * and no view (adapters/node/autkComputeBlocks, autkGrammarBehavior).
 *
 * autk-grammar's compute adapter keeps a pass's result under its
 * `outputTableName`, leaving the table it computed over as it was, and else in
 * place of that table; a table a pass names is drawn as the pass's
 * `layerType`, else as the table it computed over (`store` in its
 * adapters/compute.ts). A compute step writes its layers the same way and
 * hands every one on, and a map of a table a pass of its own document writes
 * is drawn: the grammar's run computes it. That table holds the rows of the
 * table it is computed from, so a pick on it names those rows and a selection
 * of them lights it.
 *
 * A document with data and compute and no view runs its compute on what its
 * data section loaded and hands on the result, as a compute step does. A
 * building part it loaded reaches its passes with the height autk-map draws
 * for it, as a part of its input does, so a batched pass that reads every
 * building's height with `required: true` leaves none out.
 *
 * A node's map is drawn by a stand-in grammar that records what the node
 * hands it (_support/autkNodeMocks). Its passes run through autk-grammar's own
 * compute code, the build the app bundles, on a stand-in autk-compute whose
 * GPGPU dispatch writes, under `compute.<outputColumnName>`, twice each
 * feature's `value` (_support/autkComputeStandIns).
 */
import { act, renderHook, waitFor } from '@testing-library/react';

jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class { } }));
// The grammar's own data adapter, which the browser's loader hands a geotiff
// source, as autk-grammar's does: to autk-db's loadGeoTiff.
const mockCreateDataAdapter = () => ({
  async resolveSource(db: any, source: any) {
    const { type, ...params } = source;
    if (type === 'geotiff') await db.loadGeoTiff(params);
    return db;
  },
});
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => ({
    ...require('../../_support/autkComputeStandIns').grammarBuild(),
    ...require('../../_support/autkNodeMocks').autkGrammarModule,
  }),
  { virtual: true },
);
// The grammar's data entry, which the browser's loader takes the data adapter
// from. Plain, as every suite mocks this entry (mockKinds.test.ts).
jest.mock('@urban-toolkit/autk-grammar/data', () => ({
  ...jest.requireActual('@urban-toolkit/autk-grammar/data'),
  createDataAdapter: () => mockCreateDataAdapter(),
}));
jest.mock('@urban-toolkit/autk-compute', () => require('../../_support/autkComputeStandIns').autkComputeModule, { virtual: true });
jest.mock('@urban-toolkit/autk-core', () => require('../../_support/autkComputeStandIns').autkCoreBuild(), { virtual: true });
jest.mock('@urban-toolkit/autk-map', () => require('../../_support/autkComputeStandIns').autkMapModule, { virtual: true });
jest.mock('@urban-toolkit/autk-plot', () => require('../../_support/autkComputeStandIns').autkPlotModule, { virtual: true });
// The tables a data section loads, as the browser's own loader reads them
// back: there is no sandbox here. A raster is read back with getRaster.
const mockLoaded: { layers: Array<{ name: string; type: string; features: any[] }>; rasters: Map<string, any> } = {
  layers: [],
  rasters: new Map(),
};
jest.mock(
  '@urban-toolkit/autk-db',
  () => ({
    AutkDb: class {
      async init() { }
      async loadGeojson() { }
      async loadGeoTiff() { }
      getWorkspaceConfiguration() { return { coordinateFormat: 'EPSG:3395' }; }
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
      async getRaster(name: string) {
        if (!mockLoaded.rasters.has(name)) throw new Error(`Table ${name} is not a compact raster table.`);
        return mockLoaded.rasters.get(name);
      }
    },
    DEFAULT_WORKSPACE_COORDINATE_FORMAT: 'EPSG:3395',
    DEFAULT_WORKSPACE_NAME: 'autk',
  }),
  { virtual: true },
);

import { applyComputeBlocks } from '../../../adapters/node/autkComputeBlocks';
import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';
import { withOpaqueRasters } from '../../../adapters/node/autkRasters';
import { autkNeedsInput } from '../../../utils/autkInput';
import { METRES_PER_LEVEL, deriveBuildingHeight } from '../../../utils/buildingHeight';
import {
  drawnExports,
  grammarComputes,
  grammarRuns as mockRuns,
  inputsByPath,
  resetAutkNodeMocks,
} from '../../_support/autkNodeMocks';
import { lastSelection, mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import { computeRuns, resetComputeStandIns } from '../../_support/autkComputeStandIns';
import { UNIT_ROW, drawnAt, unitsCollection } from '../../_support/keyedSelections';

/** Three points, each with a `value`. */
function spots(): any {
  return {
    type: 'FeatureCollection',
    features: [1, 2, 3].map((value, i) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [i, i] },
      properties: { value },
    })),
  };
}

/**
 * What the stand-in GPGPU dispatch writes: a new collection, as autk-compute's
 * is, of the table the pass runs over (its `dataRef`) with each feature's
 * `value` doubled under the pass's `outputColumnName` (`resultField`).
 */
function computed(params: any): any {
  const source = params.collection;
  return {
    ...source,
    features: source.features.map((f: any) => ({
      ...f,
      properties: {
        ...f.properties,
        compute: { ...(f.properties?.compute ?? {}), [params.resultField]: 2 * Number(f.properties?.value ?? 0) },
      },
    })),
  };
}

/** A pass that writes twice each feature's `value` as *column*. */
function pass(dataRef: string, column: string, more: object = {}): any {
  return { dataRef, attributes: { v: 'properties.value' }, wgslFunction: 'return v * 2.0;', outputColumnName: column, ...more };
}

/** The values a layer holds under *column*, feature by feature. */
const valuesOf = (fc: any, column: string) => fc.features.map((f: any) => f.properties?.[column]);

beforeEach(() => {
  resetAutkNodeMocks();
  resetComputeStandIns();
  computeRuns.gpgpu.mockImplementation(async (params: any) => computed(params));
  mockLoaded.layers = [];
  mockLoaded.rasters = new Map();
  stubWebGpu();
});

afterEach(() => {
  unstubWebGpu();
});

describe('a compute step writes each pass where autk-grammar writes it', () => {
  const SPOTS = () => ({ name: 'spots', type: 'points', geojson: spots() });

  test('a pass with an outputTableName writes a new table after the others, as its layerType, and leaves its source as it was', async () => {
    const source = SPOTS();
    const before = JSON.parse(JSON.stringify(source));
    const failures: string[] = [];

    const layers = await applyComputeBlocks(
      [source], [pass('spots', 'twice', { outputTableName: 'doubled', layerType: 'polygons' })], failures,
    );

    expect(failures).toEqual([]);
    expect(layers.map((l) => [l.name, l.type])).toEqual([['spots', 'points'], ['doubled', 'polygons']]);
    expect(layers[0]).toEqual(before);
    expect(valuesOf(layers[1].geojson, 'twice')).toEqual([2, 4, 6]);
    expect(valuesOf(layers[1].geojson, 'value')).toEqual([1, 2, 3]);
  });

  test('without a layerType, the new table is drawn as the table it is computed from', async () => {
    const layers = await applyComputeBlocks([SPOTS()], [pass('spots', 'twice', { outputTableName: 'doubled' })]);
    expect(layers.map((l) => [l.name, l.type])).toEqual([['spots', 'points'], ['doubled', 'points']]);
  });

  test('a layerType without an outputTableName leaves the type of the table the pass writes into', async () => {
    const failures: string[] = [];
    const layers = await applyComputeBlocks([SPOTS()], [pass('spots', 'twice', { layerType: 'polygons' })], failures);
    expect(failures).toEqual([]);
    expect(layers.map((l) => [l.name, l.type])).toEqual([['spots', 'points']]);
    expect(valuesOf(layers[0].geojson, 'twice')).toEqual([2, 4, 6]);
  });

  test('a later pass reads the table an earlier one wrote, and a name a table has replaces that table where it is', async () => {
    const other = { name: 'other', type: 'roads', geojson: spots() };
    const layers = await applyComputeBlocks([SPOTS(), other], [
      pass('spots', 'twice', { outputTableName: 'doubled' }),
      pass('doubled', 'again'),
      pass('spots', 'once', { outputTableName: 'other' }),
    ]);

    // The second pass read what the first wrote.
    expect(valuesOf(computeRuns.gpgpu.mock.calls[1][0].collection, 'twice')).toEqual([2, 4, 6]);
    expect(layers.map((l) => [l.name, l.type])).toEqual([['spots', 'points'], ['other', 'points'], ['doubled', 'points']]);
    expect(valuesOf(layers[2].geojson, 'twice')).toEqual([2, 4, 6]);
    expect(valuesOf(layers[2].geojson, 'again')).toEqual([2, 4, 6]);
    expect(valuesOf(layers[1].geojson, 'once')).toEqual([2, 4, 6]);
    expect(valuesOf(layers[0].geojson, 'twice')).toEqual([undefined, undefined, undefined]);
  });
});

describe('a map of a table a pass of its document writes', () => {
  const NODE = 'tables-map';
  const WRITES = pass('input_0', 'twice', { outputTableName: 'doubled', layerType: 'points' });

  test('is drawn: its layer and the pass reach the grammar, and the table the pass reads is loaded', async () => {
    const node = mountAutkNode(NODE, spots());
    const map = { layerRefs: [{ dataRef: 'doubled', getFnv: 'twice' }] };

    await node.run({ compute: [WRITES], map });

    expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
    expect(mockRuns).toHaveLength(1);
    expect(mockRuns[0].spec.map).toEqual(map);
    expect(mockRuns[0].spec.compute).toEqual([WRITES]);
    expect(mockRuns[0].spec.data.map((s: any) => s.outputTableName)).toEqual(['input_0']);
  });

  test('of an empty table says what a map of that table says', async () => {
    const empty = { type: 'FeatureCollection', features: [] };
    const ofSource = mountAutkNode('source-map', empty);
    await ofSource.run({ map: { layerRefs: [{ dataRef: 'input_0' }] } });
    const ofWritten = mountAutkNode(NODE, empty);
    await ofWritten.run({ compute: [WRITES], map: { layerRefs: [{ dataRef: 'doubled' }] } });

    const said = ofSource.lastOutput();
    expect(said).toEqual(expect.objectContaining({ code: 'error', kind: 'empty-render:no-input-rows' }));
    expect(ofWritten.lastOutput()).toEqual(said);
    expect(mockRuns).toHaveLength(0);
  });

  test("a pick on it names the input rows it holds, by the input's table, and a selection of them lights it", async () => {
    const units = unitsCollection() as any;
    // The input row of unit 103 comes selected, as a Data Pool marks it.
    units.features[UNIT_ROW[103]].properties.interacted = '1';
    const node = mountAutkNode(NODE, units);

    await node.run({
      compute: [pass('input_0', 'twice', { outputTableName: 'tall' })],
      map: { layerRefs: [{ dataRef: 'tall', isPick: true }] },
    });
    expect(node.lastOutput()).toEqual({ code: 'success', content: '' });

    // Lit where the map draws the input's row.
    await waitFor(() => expect(mockRuns[0].highlights).toContainEqual(['tall', [drawnAt(UNIT_ROW[103])]]));
    act(() => mockRuns[0].pick([drawnAt(UNIT_ROW[103])]));
    expect(lastSelection(node)).toEqual(expect.objectContaining({ data: [UNIT_ROW[103]], layerRef: 'input_0' }));
  });

  test('made from its own data asks for no connection', () => {
    expect(autkNeedsInput({
      data: [{ type: 'geojson', outputTableName: 'spots', geojsonObject: spots() }],
      compute: [pass('spots', 'twice', { outputTableName: 'doubled' })],
      map: { layerRefs: [{ dataRef: 'doubled' }] },
    })).toBe(false);
  });

  test('written in place under its own name is drawn as the pass says, a raster or not', () => {
    const drawn = withOpaqueRasters({
      data: [{ type: 'curio-raster', outputTableName: 'lst' }, { type: 'geojson', outputTableName: 'grid' }],
      compute: [
        pass('lst', 'once', { outputTableName: 'lst', layerType: 'points' }),
        pass('grid', 'twice', { outputTableName: 'grid', layerType: 'raster' }),
      ],
      map: { layerRefs: [{ dataRef: 'lst' }, { dataRef: 'grid' }] },
    });
    expect(drawn.map.layerRefs[0].transferFunction).toBeUndefined();
    expect(drawn.map.layerRefs[1].transferFunction).toEqual({ opacityMin: 1, opacityMax: 1 });
  });

  test('guard: written in place over a table of the input still reads the input', () => {
    expect(autkNeedsInput({
      compute: [pass('input_0', 'twice', { outputTableName: 'input_0' })],
      map: { layerRefs: [{ dataRef: 'input_0' }] },
    })).toBe(true);
  });

  test('written from a raster is drawn with every cell opaque, as a raster is, unless the pass draws it as another type', () => {
    const raster = { type: 'curio-raster', outputTableName: 'lst' };
    const drawn = withOpaqueRasters({
      data: [raster],
      compute: [
        pass('lst', 'twice', { outputTableName: 'lst_twice' }),
        pass('lst', 'once', { outputTableName: 'lst_points', layerType: 'points' }),
      ],
      map: { layerRefs: [{ dataRef: 'lst_twice' }, { dataRef: 'lst_points' }] },
    });
    expect(drawn.map.layerRefs[0].transferFunction).toEqual({ opacityMin: 1, opacityMax: 1 });
    expect(drawn.map.layerRefs[1].transferFunction).toBeUndefined();
  });
});

// autk-db exports a table with the rows whose geometry is empty first, each
// group in the order it was handed (a table it loads gets its geometry
// rewritten in place, `normalizeGeometryPrecision`, and its export has no
// order of its own). A pass computes over that export, so a plot of a table a
// pass wrote holds the rows in that order, not in the order Curio loads them:
// for the units, MAP_ORDER (`drawnAt`) and not LOAD_ORDER.
describe('a plot of a table a pass of its document writes', () => {
  const NODE = 'tables-plot';
  const PLOT = (dataRef: string) => ({ dataRef, mark: 'table', axis: ['unit_id', 'height'] });
  const empty = (f: any) => !f?.geometry
    || (f.geometry.type === 'GeometryCollection' && (f.geometry.geometries ?? []).length === 0);

  beforeEach(() => {
    drawnExports.of = (_table, handed) => [...handed.filter(empty), ...handed.filter((f) => !empty(f))];
  });

  test('names the input rows the pass kept where a brush lands, by the input table', async () => {
    const node = mountAutkNode(NODE, unitsCollection());

    await node.run({ compute: [pass('input_0', 'twice', { outputTableName: 'tall' })], plot: PLOT('tall') });
    expect(node.lastOutput()).toEqual({ code: 'success', content: '' });

    act(() => mockRuns[0].brush([drawnAt(UNIT_ROW[103])]));
    await waitFor(() => expect(lastSelection(node)).toEqual(
      expect.objectContaining({ data: [UNIT_ROW[103]], layerRef: 'input_0' }),
    ));
  });

  test('repro: of a table a pass computes in place, it names the rows where a brush lands', async () => {
    const node = mountAutkNode(NODE, unitsCollection());

    await node.run({ compute: [pass('input_0', 'twice')], plot: PLOT('input_0') });
    expect(node.lastOutput()).toEqual({ code: 'success', content: '' });

    act(() => mockRuns[0].brush([drawnAt(UNIT_ROW[103])]));
    await waitFor(() => expect(lastSelection(node)).toEqual(
      expect.objectContaining({ data: [UNIT_ROW[103]], layerRef: 'input_0' }),
    ));
  });

  test('lights the rows a selection names where the pass kept them', async () => {
    const units = unitsCollection() as any;
    units.features[UNIT_ROW[103]].properties.interacted = '1';
    const node = mountAutkNode(NODE, units);

    await node.run({ compute: [pass('input_0', 'twice', { outputTableName: 'tall' })], plot: PLOT('tall') });
    expect(node.lastOutput()).toEqual({ code: 'success', content: '' });

    await waitFor(() => expect(mockRuns[0].plotSelections).toContainEqual(['tall', [drawnAt(UNIT_ROW[103])]]));
  });
});

/** A node whose run hands on what it made, as a node of the canvas does. */
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

describe('a document with data and compute and no view', () => {
  const DATA = [{ type: 'geojson', outputTableName: 'spots', geojsonObject: spots() }];

  beforeEach(() => {
    mockLoaded.layers = [{ name: 'spots', type: 'points', features: spots().features }];
  });

  test('runs its compute on what it loaded and hands on the result', async () => {
    const step = mountStep('data-compute');

    await step.run({ data: DATA, compute: [pass('spots', 'twice')] });

    expect(step.lastOutput()).toEqual({ code: 'success', content: 'Computed 1 layer: spots (3 rows)' });
    expect(computeRuns.gpgpu).toHaveBeenCalledTimes(1);
    const [handed] = step.handedOn();
    expect(handed).toEqual(expect.objectContaining({ dataType: 'geodataframe', layerName: 'spots', layerType: 'points' }));
    expect(valuesOf(handed.data, 'twice')).toEqual([2, 4, 6]);
  });

  test('hands on the table a pass writes beside the table it loaded', async () => {
    const step = mountStep('data-compute');

    await step.run({ data: DATA, compute: [pass('spots', 'twice', { outputTableName: 'doubled', layerType: 'polygons' })] });

    const [handed] = step.handedOn();
    expect(handed.dataType).toBe('outputs');
    expect(handed.data.map((l: any) => [l.layerName, l.layerType])).toEqual([['spots', 'points'], ['doubled', 'polygons']]);
    expect(valuesOf(handed.data[0].data, 'twice')).toEqual([undefined, undefined, undefined]);
    expect(valuesOf(handed.data[1].data, 'twice')).toEqual([2, 4, 6]);
  });

  test('reads its input when a pass names a table of it, and hands on both', async () => {
    inputsByPath.current = { 'art-in': { dataType: 'geodataframe', data: spots(), layerName: 'lanes', layerType: 'roads' } };
    const step = mountStep('data-compute', { path: 'art-in', dataType: 'geodataframe' });

    await step.run({ data: DATA, compute: [pass('lanes', 'twice')] });

    const [handed] = step.handedOn();
    expect(handed.data.map((l: any) => [l.layerName, l.layerType])).toEqual([['lanes', 'roads'], ['spots', 'points']]);
    expect(valuesOf(handed.data[0].data, 'twice')).toEqual([2, 4, 6]);
  });

  test('counts a raster it loaded by its cells, as a node that only loads data does, and hands it on', async () => {
    // A GeoTIFF of 4 columns by 3 rows, as autk-db's getRaster gives it.
    mockLoaded.rasters.set('lst', {
      type: 'FeatureCollection',
      bbox: [-4802000, -2604000, -4780000, -2589000],
      features: [{
        type: 'Feature',
        geometry: null,
        properties: {
          rasterResX: 4,
          rasterResY: 3,
          bands: [{ id: 'band_1', label: 'band_1' }],
          band_1: Float32Array.from([27.5, 28, 28.5, 29, 29.5, 30, 30.5, 31, 31.5, 32, 32.5, 33]),
        },
      }],
    });
    const step = mountStep('data-compute');

    await step.run({
      data: [...DATA, { type: 'geotiff', geotiffFileUrl: 'docs/examples/data/lst.tif', outputTableName: 'lst' }],
      compute: [pass('spots', 'twice')],
    });

    expect(step.lastOutput()).toEqual({ code: 'success', content: 'Computed 2 layers: spots (3 rows), lst (12 cells)' });
    const [handed] = step.handedOn();
    expect(handed.data.map((l: any) => [l.dataType, l.layerName])).toEqual([['geodataframe', 'spots'], ['raster', 'lst']]);
  });

  test('a batched pass that reads every building part it loaded with required: true reads each with the height autk-map draws', async () => {
    const footprint = (i: number) => ({
      type: 'Polygon',
      coordinates: [[[10 * i, 0], [10 * i + 5, 0], [10 * i + 5, 5], [10 * i, 0]]],
    });
    // One part with a height, one with only its levels, one with an empty
    // height beside its levels, one with only a building:height, one with none.
    const parts = [{ height: 12 }, { 'building:levels': 3 }, { height: null, 'building:levels': 2 }, { 'building:height': 30 }, {}];
    const features = parts.map((properties, i) => ({ type: 'Feature', geometry: footprint(i), properties }));
    mockLoaded.layers = [
      { name: 'spots', type: 'points', features: spots().features },
      { name: 'blocks', type: 'buildings', features },
    ];
    const info = jest.spyOn(console, 'info').mockImplementation(() => { });
    try {
      const step = mountStep('data-compute');

      await step.run({
        data: [...DATA, { type: 'geojson', outputTableName: 'blocks', geojsonObject: { type: 'FeatureCollection', features } }],
        compute: [pass('spots', 'twice', {
          uniforms: {
            heights: { fromFeature: { layer: 'blocks', iterate: 'batched', path: 'properties.height', required: true } },
          },
        })],
      });

      expect(step.lastOutput()).toEqual({ code: 'success', content: 'Computed 2 layers: spots (3 rows), blocks (5 rows)' });
      // autk-grammar says so when a batched pass leaves a feature out.
      expect(info.mock.calls.filter(([text]) => String(text).includes('batched compute'))).toEqual([]);
      expect(computeRuns.gpgpu).toHaveBeenCalledTimes(1);
      const { uniforms, uniformArrays } = computeRuns.gpgpu.mock.calls[0][0];
      expect(uniforms.num_features).toBe(parts.length);
      expect(uniformArrays.heights).toEqual([12, 3 * METRES_PER_LEVEL, 2 * METRES_PER_LEVEL, 30, 6]);
      // The step hands the parts on as it holds them: the default is the
      // pass's, and the part with no height holds none.
      const [handed] = step.handedOn();
      const blocks = handed.data.find((layer: any) => layer.layerName === 'blocks');
      expect(blocks.data.features.map((f: any) => f.properties)).toEqual([
        { height: 12 },
        { 'building:levels': 3, height: 3 * METRES_PER_LEVEL },
        { height: 2 * METRES_PER_LEVEL, 'building:levels': 2 },
        { 'building:height': 30, height: 30 },
        {},
      ]);
    } finally {
      info.mockRestore();
    }
  });

  test('a pass over the buildings it loaded reads a part with no height at the default, and the step hands it on with none', async () => {
    const footprint = (i: number) => ({
      type: 'Polygon',
      coordinates: [[[10 * i, 0], [10 * i + 5, 0], [10 * i + 5, 5], [10 * i, 0]]],
    });
    // A part with a height, one with none above its base, one with none.
    const parts = [{ height: 12, value: 1 }, { min_height: 4, value: 2 }, { value: 3 }];
    const features = parts.map((properties, i) => ({ type: 'Feature', geometry: footprint(i), properties }));
    mockLoaded.layers = [{ name: 'blocks', type: 'buildings', features }];
    const step = mountStep('data-compute');

    await step.run({
      data: [{ type: 'geojson', outputTableName: 'blocks', geojsonObject: { type: 'FeatureCollection', features } }],
      compute: [pass('blocks', 'twice', { attributes: { v: 'properties.value', h: 'properties.height' } })],
    });

    expect(step.lastOutput()).toEqual({ code: 'success', content: 'Computed 1 layer: blocks (3 rows)' });
    // What the pass read: each part as a map draws it, 6 m above its base
    // where it has no height.
    const { collection } = computeRuns.gpgpu.mock.calls[0][0];
    expect(collection.features.map((f: any) => f.properties.height))
      .toEqual([12, deriveBuildingHeight({ min_height: 4 }), deriveBuildingHeight({})]);
    expect(collection.features.map((f: any) => f.properties.height)).toEqual([12, 10, 6]);
    // What the step hands on: the pass's column, and each part's own height.
    const [handed] = step.handedOn();
    expect(handed.layerName).toBe('blocks');
    expect(handed.data.features.map((f: any) => f.properties)).toEqual([
      { height: 12, value: 1, compute: { twice: 2 }, twice: 2 },
      { min_height: 4, value: 2, compute: { twice: 4 }, twice: 4 },
      { value: 3, compute: { twice: 6 }, twice: 6 },
    ]);
  });
});

// A map node's run hands each pass to autk-grammar's own compute adapter. The
// run's database, autk-db, keeps a building as a GeometryCollection of its
// parts, so the adapter reads a `fromFeature` table but its `dataRef` as the
// node handed it to the run, from its data adapter's cache (autk-grammar
// 5.2.0), as a compute step's pass reads it.
describe("a map node's pass reads its fromFeature tables as a compute step's pass reads them", () => {
  /** A building as autk-db keeps one: a GeometryCollection of its parts, their tags in `properties.parts`. */
  const asAutkDbBuilding = (feature: any) => ({
    ...feature,
    geometry: { type: 'GeometryCollection', geometries: [feature.geometry] },
    properties: { ...feature.properties, parts: [] },
  });
  /** The west, south, east and north of building *i*, 10 m square, in World Mercator metres. */
  const box = (i: number) => [-9755100 + 20 * i, 5142400, -9755090 + 20 * i, 5142410];
  const BLOCKS = [12, 30, 45].map((height, i) => {
    const [west, south, east, north] = box(i);
    return {
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]] },
      properties: { height },
    };
  });
  const STREETS = [1, 2].map((value, i) => ({
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: [[-9755100, 5142390 - 10 * i], [-9755000, 5142390 - 10 * i]] },
    properties: { value },
  }));
  /** One document: the blocks and the streets it loads, and a pass over the streets that reads every block's outline and height. */
  const DOCUMENT = {
    data: [
      { type: 'geojson', outputTableName: 'blocks', geojsonObject: { type: 'FeatureCollection', features: BLOCKS } },
      { type: 'geojson', outputTableName: 'streets', geojsonObject: { type: 'FeatureCollection', features: STREETS } },
    ],
    compute: [pass('streets', 'sunlight', {
      outputTableName: 'street_sun',
      layerType: 'roads',
      uniforms: { bld_height: { fromFeature: { layer: 'blocks', iterate: 'batched', path: 'properties.height', required: true } } },
      uniformMatrices: { ring: { fromFeature: { layer: 'blocks', iterate: 'batched', path: 'geometry.coordinates.0' }, cols: 2 } },
    })],
  };
  const MAP = { layerRefs: [{ dataRef: 'blocks' }, { dataRef: 'street_sun', getFnv: 'compute.sunlight' }] };

  beforeEach(() => {
    mockLoaded.layers = [
      { name: 'blocks', type: 'buildings', features: BLOCKS },
      { name: 'streets', type: 'roads', features: STREETS },
    ];
    // The map node's run: autk-grammar's own compute adapter, made as the
    // grammar makes it, with its data adapter's cache, over a database that
    // exports each table as autk-db does.
    const { createComputeAdapter } = jest.requireMock('@urban-toolkit/autk-grammar');
    grammarComputes.on = true;
    grammarComputes.adapter = (sources) => createComputeAdapter(new Map(), new Map(), sources);
    drawnExports.of = (table, handed) => (table === 'blocks' ? handed.map(asAutkDbBuilding) : handed);
  });

  test("a map node's pass packs each building part's outline and height as a compute step's does", async () => {
    const step = mountStep('blocks-step');
    await step.run(DOCUMENT);
    expect(step.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    expect(computeRuns.gpgpu).toHaveBeenCalledTimes(1);
    const stepped = computeRuns.gpgpu.mock.calls[0][0];
    // Each part's box, its corners from the south-west one around: none is empty.
    const boxes = [0, 1, 2].flatMap((i) => {
      const [west, south, east, north] = box(i);
      return [west, south, east, south, east, north, west, north];
    });
    expect(stepped.uniformArrays).toEqual({ bld_height: [12, 30, 45], ring: boxes });

    computeRuns.gpgpu.mockClear();
    const node = mountAutkNode('blocks-map', undefined, { input: '' });
    await node.run({ ...DOCUMENT, map: MAP });

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    expect(computeRuns.gpgpu).toHaveBeenCalledTimes(1);
    const drawn = computeRuns.gpgpu.mock.calls[0][0];
    expect(drawn.uniformArrays).toEqual(stepped.uniformArrays);
    expect(drawn.uniforms).toEqual(stepped.uniforms);
  });

  test("guard: a map node's pass computes over its dataRef as the run's database exports it", async () => {
    // autk-db's export of the streets, the last first.
    drawnExports.of = (table, handed) => (
      table === 'blocks' ? handed.map(asAutkDbBuilding) : table === 'streets' ? [...handed].reverse() : handed
    );
    const node = mountAutkNode('blocks-map', undefined, { input: '' });
    await node.run({ ...DOCUMENT, map: MAP });

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    expect(computeRuns.gpgpu).toHaveBeenCalledTimes(1);
    expect(valuesOf(computeRuns.gpgpu.mock.calls[0][0].collection, 'value')).toEqual([2, 1]);
  });
});
