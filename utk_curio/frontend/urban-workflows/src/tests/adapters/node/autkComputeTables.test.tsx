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

import { applyComputeBlocks } from '../../../adapters/node/autkComputeBlocks';
import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';
import { withOpaqueRasters } from '../../../adapters/node/autkRasters';
import { autkNeedsInput } from '../../../utils/autkInput';
import {
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
});
