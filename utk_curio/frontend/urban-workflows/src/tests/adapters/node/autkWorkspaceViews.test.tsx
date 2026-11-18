/**
 * A map, a plot and a compute pass read the tables of their own `workspace`
 * (autk-grammar 5.0.0), when the node's input holds a table of one name in two
 * workspaces: an upstream Autark node's layers, `lines` in the default
 * workspace and in `east`. The node hands the grammar the table of the view's
 * workspace, says which tables it has when the view names none of them, and
 * names the rows of the table it drew in a pick.
 */
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class { } }));
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => ({
    ...require('../../_support/autkNodeMocks').autkGrammarModule,
    runCompute: (...a: any[]) => mockRunCompute(...a),
  }),
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

const mockRunCompute = jest.fn();

import { act } from '@testing-library/react';
import { applyComputeBlocks } from '../../../adapters/node/autkComputeBlocks';
import {
  drawnExports,
  grammarRuns as mockRuns,
  inputsByPath,
  resetAutkNodeMocks,
} from '../../_support/autkNodeMocks';
import { lastSelection, mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';

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
  mockRunCompute.mockReset();
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
    // autk-db exports east's rows in an order of its own.
    drawnExports.of = (_table, rows) => [...rows].reverse();
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
    mockRunCompute.mockImplementation(async (_pass: any, tables: Map<string, any>) => ({ ...tables.get('lines'), computed: true }));
    const failures: string[] = [];
    const out = await applyComputeBlocks(LAYERS as any, [{ ...PASS, workspace: 'east' }], failures);
    expect(failures).toEqual([]);
    expect(mockRunCompute).toHaveBeenCalledTimes(1);
    // The tables the pass reads are east's.
    const tables: Map<string, any> = mockRunCompute.mock.calls[0][1];
    expect([...tables.keys()]).toEqual(['lines']);
    expect(tables.get('lines').features).toHaveLength(3);
    expect(out.map((layer: any) => [layer.name, layer.workspace, layer.geojson.computed === true])).toEqual([
      ['lines', undefined, false],
      ['lines', 'east', true],
    ]);
  });

  test('with no workspace computes over the default workspace\'s table', async () => {
    mockRunCompute.mockImplementation(async (_pass: any, tables: Map<string, any>) => ({ ...tables.get('lines'), computed: true }));
    const out = await applyComputeBlocks(LAYERS as any, [PASS], []);
    expect(mockRunCompute.mock.calls[0][1].get('lines').features).toHaveLength(1);
    expect(out.map((layer: any) => layer.geojson.computed === true)).toEqual([true, false]);
  });
});
