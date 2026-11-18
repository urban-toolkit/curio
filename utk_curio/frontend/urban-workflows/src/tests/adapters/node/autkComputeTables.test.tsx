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
 * data section loaded and hands on the result, as a compute step does.
 *
 * The grammar is a stand-in that records what the node hands it
 * (_support/autkNodeMocks), and `runCompute` one that writes, under
 * `compute.<outputColumnName>`, twice each feature's `value`.
 */
import { act, renderHook, waitFor } from '@testing-library/react';

jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class { } }));
const mockRunCompute = jest.fn();
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
    ...require('../../_support/autkNodeMocks').autkGrammarModule,
    runCompute: (...args: any[]) => mockRunCompute(...args),
  }),
  { virtual: true },
);
// The grammar's data entry, which the browser's loader takes the data adapter
// from. Plain, as every suite mocks this entry (mockKinds.test.ts).
jest.mock('@urban-toolkit/autk-grammar/data', () => ({
  ...jest.requireActual('@urban-toolkit/autk-grammar/data'),
  createDataAdapter: () => mockCreateDataAdapter(),
}));
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });
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
    DEFAULT_WORKSPACE_NAME: 'autk',
    DEFAULT_WORKSPACE_COORDINATE_FORMAT: 'EPSG:3395',
  }),
  { virtual: true },
);

import { applyComputeBlocks } from '../../../adapters/node/autkComputeBlocks';
import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';
import { withOpaqueRasters } from '../../../adapters/node/autkRasters';
import { autkNeedsInput } from '../../../utils/autkInput';
import {
  drawnExports,
  grammarRuns as mockRuns,
  inputsByPath,
  resetAutkNodeMocks,
} from '../../_support/autkNodeMocks';
import { lastSelection, mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
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

/** What the stand-in `runCompute` writes: a new collection, as autk-compute's is. */
function computed(block: any, tables: Map<string, any>): any {
  const source = tables.get(block.dataRef);
  return {
    ...source,
    features: source.features.map((f: any) => ({
      ...f,
      properties: {
        ...f.properties,
        compute: { ...(f.properties?.compute ?? {}), [block.outputColumnName]: 2 * Number(f.properties?.value ?? 0) },
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
  mockRunCompute.mockReset();
  mockRunCompute.mockImplementation(async (block: any, tables: Map<string, any>) => computed(block, tables));
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
    expect(valuesOf(mockRunCompute.mock.calls[1][1].get('doubled'), 'twice')).toEqual([2, 4, 6]);
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

describe('a document with data and compute and no view', () => {
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
  const DATA = [{ type: 'geojson', outputTableName: 'spots', geojsonObject: spots() }];

  beforeEach(() => {
    mockLoaded.layers = [{ name: 'spots', type: 'points', features: spots().features }];
  });

  test('runs its compute on what it loaded and hands on the result', async () => {
    const step = mountStep('data-compute');

    await step.run({ data: DATA, compute: [pass('spots', 'twice')] });

    expect(step.lastOutput()).toEqual({ code: 'success', content: 'Computed 1 layer: spots (3 rows)' });
    expect(mockRunCompute).toHaveBeenCalledTimes(1);
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
});
