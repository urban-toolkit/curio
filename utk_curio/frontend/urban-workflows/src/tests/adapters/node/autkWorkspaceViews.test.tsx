/**
 * A map, a plot and a compute pass read the tables of their own `workspace`
 * (autk-grammar 5.0.0), when the node's input holds a table of one name in two
 * workspaces: an upstream Autark node's layers, `lines` in the default
 * workspace and in `east`. The node hands the grammar the table of the view's
 * workspace, says which tables it has when the view names none of them, and
 * names the rows of the table it drew in a pick.
 *
 * A compute step's passes run through autk-grammar's own compute code, the
 * build the app bundles, on a stand-in autk-compute that records each GPGPU
 * dispatch (_support/autkComputeStandIns).
 */
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
jest.mock('@urban-toolkit/autk-core', () => require('../../_support/autkComputeStandIns').autkCoreBuild(), { virtual: true });
jest.mock('@urban-toolkit/autk-map', () => require('../../_support/autkComputeStandIns').autkMapModule, { virtual: true });
jest.mock('@urban-toolkit/autk-plot', () => require('../../_support/autkComputeStandIns').autkPlotModule, { virtual: true });
jest.mock('@urban-toolkit/autk-db', () => ({
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: 'EPSG:3395',
  DEFAULT_WORKSPACE_NAME: 'autk',
  // The database a map node's run goes on, the node's own, which the stand-in
  // grammar's run exports its tables from (drawnExports).
  AutkDb: class { async init() { } },
}), { virtual: true });

import { act } from '@testing-library/react';
import { applyComputeBlocks } from '../../../adapters/node/autkComputeBlocks';
import { layersToPoolWrapper } from '../../../adapters/node/autkLayerMaterialize';
import { rasterTables } from '../../../adapters/node/autkRasters';
import { madeTables } from '../../../utils/autkInput';
import {
  drawnExports,
  grammarLoads,
  grammarRuns as mockRuns,
  inputsByPath,
  resetAutkNodeMocks,
} from '../../_support/autkNodeMocks';
import { lastSelection, mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import { computeRuns, resetComputeStandIns } from '../../_support/autkComputeStandIns';

const line = (x: number) => ({
  type: 'Feature',
  geometry: { type: 'LineString', coordinates: [[x, 41.88], [x + 0.001, 41.881]] },
  properties: { x },
});
const lines = (...xs: number[]) => ({ type: 'FeatureCollection', features: xs.map(line) });

/** What an upstream Autark data node hands on: `lines` in the default workspace and in `east`. */
const RECORDS = [
  { name: 'lines', type: 'polylines', geojson: lines(-87.6) },
  { name: 'lines', type: 'polylines', geojson: lines(-87.5, -87.49, -87.48), workspace: 'east' },
];
const INPUT = { path: 'art-ws', dataType: 'list' };

/** The tables a run handed the grammar: name, workspace, and the `x` of each row. */
const handed = (spec: any) => (spec.data as any[]).map((source) => [
  source.outputTableName, source.workspace, source.geojsonObject.features.map((f: any) => f.properties.x),
]);

beforeEach(() => {
  resetAutkNodeMocks();
  resetComputeStandIns();
  inputsByPath.current = { 'art-ws': { dataType: 'list', data: RECORDS } };
  stubWebGpu();
});

afterEach(() => {
  unstubWebGpu();
});

describe('a map', () => {
  test('in a workspace draws the table of that workspace, and one with none the default\'s', async () => {
    const node = mountAutkNode('ws-map', undefined, { input: INPUT });
    await node.run({ map: { workspace: 'east', layerRefs: [{ dataRef: 'lines' }] } });
    expect(mockRuns).toHaveLength(1);
    expect(handed(mockRuns[0].spec)).toEqual([['lines', 'east', [-87.5, -87.49, -87.48]]]);
    expect(mockRuns[0].spec.map.workspace).toBe('east');
    await node.run({ map: { layerRefs: [{ dataRef: 'lines' }] } });
    expect(mockRuns).toHaveLength(2);
    expect(handed(mockRuns[1].spec)).toEqual([['lines', undefined, [-87.6]]]);
  });

  test('in a workspace that holds none of its tables draws nothing, and says what there is', async () => {
    const node = mountAutkNode('ws-map', undefined, { input: INPUT });
    await node.run({ map: { workspace: 'west', layerRefs: [{ dataRef: 'lines' }] } });
    expect(mockRuns).toHaveLength(0);
    expect(node.lastOutput().code).toBe('error');
    expect(node.lastOutput().content).toContain('(asked for: west/lines; available: lines, east/lines)');
  });

  test('names in a pick the row of its own workspace\'s table, as autk-db exported it', async () => {
    // autk-db exports east's rows in an order of its own, from the database
    // the run went on, which the run's sources load into.
    drawnExports.of = (_table, rows) => [...rows].reverse();
    grammarLoads.on = true;
    const node = mountAutkNode('ws-map', undefined, { input: INPUT });
    await node.run({ map: { workspace: 'east', layerRefs: [{ dataRef: 'lines', isPick: true }] } });
    await act(async () => {
      mockRuns[0].pick([0]);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    // The first feature drawn is east's third row.
    expect(lastSelection(node)?.data).toEqual([2]);
  });
});

describe('a map of a table a pass writes', () => {
  test('in a workspace draws the table the pass writes there', async () => {
    const node = mountAutkNode('ws-map', undefined, { input: INPUT });
    await node.run({
      compute: [{
        workspace: 'east', dataRef: 'lines', attributes: { x: 'x' }, wgslFunction: 'return x;',
        outputColumnName: 'y', outputTableName: 'lines_y',
      }],
      map: { workspace: 'east', layerRefs: [{ dataRef: 'lines_y' }] },
    });
    expect(node.lastOutput()?.code).not.toBe('error');
    expect(mockRuns).toHaveLength(1);
    expect(mockRuns[0].spec.map.layerRefs.map((ref: any) => ref.dataRef)).toEqual(['lines_y']);
    expect(handed(mockRuns[0].spec)).toEqual([['lines', 'east', [-87.5, -87.49, -87.48]]]);
  });
});

describe('a plot', () => {
  test('in a workspace plots the table of that workspace', async () => {
    const node = mountAutkNode('ws-plot', undefined, { input: INPUT });
    await node.run({ plot: { workspace: 'east', dataRef: 'lines', mark: 'bar', axis: ['x'] } });
    expect(mockRuns).toHaveLength(1);
    expect(handed(mockRuns[0].spec)).toEqual([['lines', 'east', [-87.5, -87.49, -87.48]]]);
    expect(mockRuns[0].spec.plot.workspace).toBe('east');
  });
});

describe('a compute pass', () => {
  const LAYERS = RECORDS.map(({ name, type, geojson, workspace }: any) => ({
    name, type, geojson, ...(workspace ? { workspace } : {}),
  }));
  const PASS = { dataRef: 'lines', attributes: { x: 'x' }, wgslFunction: 'return x;', outputColumnName: 'y' };

  test('in a workspace computes over that workspace\'s table, which keeps its workspace', async () => {
    computeRuns.gpgpu.mockImplementation(async (params: any) => ({ ...params.collection, computed: true }));
    const failures: string[] = [];
    const out = await applyComputeBlocks(LAYERS as any, [{ ...PASS, workspace: 'east' }], failures);
    expect(failures).toEqual([]);
    expect(computeRuns.gpgpu).toHaveBeenCalledTimes(1);
    // The table the pass reads is east's, row for row.
    const read = computeRuns.gpgpu.mock.calls[0][0].collection;
    expect(read.features.map((f: any) => f.properties.x)).toEqual([-87.5, -87.49, -87.48]);
    expect(out.map((layer: any) => [layer.name, layer.workspace, layer.geojson.computed === true])).toEqual([
      ['lines', undefined, false],
      ['lines', 'east', true],
    ]);
  });

  test('in a workspace writes its new table there, and a compute step hands it on with that workspace', async () => {
    computeRuns.gpgpu.mockImplementation(async (params: any) => ({ ...params.collection, computed: true }));
    const out = await applyComputeBlocks([LAYERS[1]] as any, [{ ...PASS, workspace: 'east', outputTableName: 'lines_y' }], []);
    expect(out.map((layer: any) => [layer.name, layer.workspace, layer.geojson.computed === true])).toEqual([
      ['lines', 'east', false],
      ['lines_y', 'east', true],
    ]);
    expect(layersToPoolWrapper(out as any).data.map((envelope: any) => [envelope.layerName, envelope.workspace])).toEqual([
      ['lines', 'east'],
      ['lines_y', 'east'],
    ]);
  });

  test('passes of two workspaces that write tables of one name write two tables', async () => {
    computeRuns.gpgpu.mockImplementation(async (params: any) => ({ ...params.collection }));
    const passes = [
      { ...PASS, outputTableName: 'out' },
      { ...PASS, workspace: 'east', outputTableName: 'out' },
    ];
    const out = await applyComputeBlocks(LAYERS as any, passes, []);
    expect(out.map((layer: any) => [layer.name, layer.workspace, layer.geojson.features.length])).toEqual([
      ['lines', undefined, 1],
      ['lines', 'east', 3],
      ['out', undefined, 1],
      ['out', 'east', 3],
    ]);
    expect(madeTables({ compute: passes })).toEqual(['out', 'east/out']);
    // A raster a pass writes in a workspace is that workspace's.
    expect([...rasterTables({ compute: [{ ...PASS, workspace: 'east', outputTableName: 'cells', layerType: 'raster' }] })])
      .toEqual(['east/cells']);
  });

  test('with no workspace computes over the default workspace\'s table', async () => {
    computeRuns.gpgpu.mockImplementation(async (params: any) => ({ ...params.collection, computed: true }));
    const out = await applyComputeBlocks(LAYERS as any, [PASS], []);
    expect(computeRuns.gpgpu.mock.calls[0][0].collection.features).toHaveLength(1);
    expect(out.map((layer: any) => layer.geojson.computed === true)).toEqual([true, false]);
  });
});
