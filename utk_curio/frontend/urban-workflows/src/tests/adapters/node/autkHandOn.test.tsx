/**
 * What an Autark node hands the nodes below it, by one rule for every kind of
 * node (adapters/node/autkGrammarBehavior), the rule a compute step follows:
 *
 * 1. its input's tables, when it has no data section of its own or a view or a
 *    pass names a table only its input brings (`autkNeedsInput`), each as it
 *    came or as a pass changed it;
 * 2. each table its data section loads or makes;
 * 3. each table a pass writes under a name of its own;
 * 4. each table a source after compute makes.
 *
 * A raster goes on as it came. A node whose document only draws its input (a
 * map or a plot, no data source, no pass) hands on its input as it came.
 *
 * So a map that loads tables or runs passes hands on what it loads and
 * computes, as a compute step does: example 38's node hands on its roads with
 * their minutes of sun, and example 35's sky map its streets with the share of
 * sky each sees. Each pass's result is the one the node's own run computed
 * (autk-grammar's `data`, which lists each table a pass wrote under its key):
 * no pass runs twice.
 *
 * A node's maps are drawn by the stand-in grammar of _support/autkNodeMocks,
 * whose passes run through autk-grammar's own compute code on a stand-in
 * autk-compute whose GPGPU dispatch writes, under `compute.<outputColumnName>`,
 * twice each feature's `value` (_support/autkComputeStandIns), as
 * autkComputeTables.test.tsx runs them.
 */
import React from 'react';
import { act, render } from '@testing-library/react';

jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class { } }));
// The dashboard's runs: where a step a viewer's run asked of the page is kept.
const mockKeepStep = jest.fn();
jest.mock('../../../services/runs/dashboardRunsApi', () => ({
  RUN_TOKEN_HEADER: 'X-Curio-Run-Token',
  dashboardRunsApi: { keepStep: (...args: unknown[]) => mockKeepStep(...args) },
}));
// The grammar's own data adapter, which the browser's loader hands a source.
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
jest.mock('@urban-toolkit/autk-grammar/data', () => ({
  ...jest.requireActual('@urban-toolkit/autk-grammar/data'),
  createDataAdapter: () => mockCreateDataAdapter(),
}));
jest.mock('@urban-toolkit/autk-compute', () => require('../../_support/autkComputeStandIns').autkComputeModule, { virtual: true });
jest.mock('@urban-toolkit/autk-core', () => require('../../_support/autkComputeStandIns').autkCoreBuild(), { virtual: true });
jest.mock('@urban-toolkit/autk-map', () => require('../../_support/autkComputeStandIns').autkMapModule, { virtual: true });
jest.mock('@urban-toolkit/autk-plot', () => require('../../_support/autkComputeStandIns').autkPlotModule, { virtual: true });
// The tables a data section loads, as the browser's own loader reads them
// back when no sandbox answers; and the tables of the database a node's run
// goes on, when its sources reach the grammar's data adapter (grammarLoads).
// A table *unreadable* names cannot be read back.
const mockLoaded: { layers: Array<{ name: string; type: string; features: any[] }>; unreadable: string | null } = {
  layers: [], unreadable: null,
};
jest.mock(
  '@urban-toolkit/autk-db',
  () => ({
    AutkDb: class {
      private workspace = 'autk';
      async init() { }
      async loadGeojson() { }
      async loadGeoTiff() { }
      getCurrentWorkspace() { return this.workspace; }
      async setWorkspace(name: string) { this.workspace = name; }
      getWorkspaceConfiguration() { return { coordinateFormat: 'EPSG:3395' }; }
      getLayersMetadata() {
        return mockLoaded.layers.map(({ name, type }) => ({ name, type }));
      }
      getTablesMetadata() {
        return mockLoaded.layers.map(({ name, type }) => ({ name, type }));
      }
      async getLayer(name: string) {
        if (name === mockLoaded.unreadable) throw new Error(`Table ${name} could not be read.`);
        const layer = mockLoaded.layers.find((l) => l.name === name);
        return {
          type: 'FeatureCollection',
          features: (layer?.features ?? []).map((f) => ({ ...f, properties: { ...f.properties } })),
        };
      }
      async getRaster(name: string) {
        throw new Error(`Table ${name} is not a compact raster table.`);
      }
    },
    DEFAULT_WORKSPACE_COORDINATE_FORMAT: 'EPSG:3395',
    DEFAULT_WORKSPACE_NAME: 'autk',
  }),
  { virtual: true },
);

import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';
import { rasterEnvelope } from '../../../adapters/node/autkDataCompile';
import { askPage, forgetPageSteps } from '../../../services/runs/dashboardRunSteps';
import {
  drawnExports,
  flowDashboard,
  grammarComputes,
  grammarLoads,
  grammarRuns,
  inputsByPath,
  resetAutkNodeMocks,
  showToast,
} from '../../_support/autkNodeMocks';
import { stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import { computeRuns, resetComputeStandIns } from '../../_support/autkComputeStandIns';

/** Three points west to east in World Mercator metres, each with a `value`. */
function spots(): any {
  return {
    type: 'FeatureCollection',
    features: [1, 2, 3].map((value, i) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [-9755100 + 10 * i, 5142400] },
      properties: { value },
    })),
  };
}

/** Two streets, each with a `value`. */
function streets(): any {
  return {
    type: 'FeatureCollection',
    features: [4, 5].map((value, i) => ({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: [[-9755100, 5142390 - 10 * i], [-9755000, 5142390 - 10 * i]] },
      properties: { value },
    })),
  };
}

/** What the stand-in GPGPU dispatch writes: the table it runs over, each `value` doubled under the pass's column. */
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

/** A heatmap's raster of 2 by 2 cells, in the envelope an Autark node hands one on in. */
const DENSITY = rasterEnvelope({
  type: 'FeatureCollection',
  bbox: [-9755100, 5142380, -9755080, 5142400],
  grid: { crs: 'EPSG:3395', width: 2, height: 2, originX: -9755100, originY: 5142400, resX: 10, resY: -10 },
  features: [{
    type: 'Feature',
    geometry: null,
    properties: { rasterResX: 2, rasterResY: 2, bands: [{ id: 'band_1', label: 'count' }], band_1: [1, 2, 3, 4] },
  }],
}, 'density');

/** An upstream node's output of one layer, `lanes`, the spots as roads. */
const LANES = { dataType: 'geodataframe', data: spots(), layerName: 'lanes', layerType: 'roads' };

/** The input those reach the node through, by their artifact. */
const ONE_LAYER = { path: 'art-lanes', dataType: 'geodataframe' };
const LAYER_AND_RASTER = { path: 'art-lanes-density', dataType: 'outputs' };

/** The data section of a node that loads its own streets. */
const OWN_STREETS = [{ type: 'geojson', outputTableName: 'streets', geojsonObject: streets() }];

/** The tables a node handed on: each envelope of its wrapper, or its one envelope. */
function tablesOf(handed: any): any[] {
  if (handed?.dataType === 'outputs' && Array.isArray(handed.data)) return handed.data;
  return handed && typeof handed === 'object' && 'data' in handed ? [handed] : [];
}

/** Each table a node handed on, by its name and its layer type. */
const namesAndTypes = (handed: any) => tablesOf(handed).map((table) => [table.layerName, table.layerType]);

/** The table named *name* that a node handed on. */
const tableNamed = (handed: any, name: string) => tablesOf(handed).find((table) => table.layerName === name);

/** The values a table holds under *column*, feature by feature. */
const valuesOf = (fc: any, column: string) => fc.features.map((f: any) => f.properties?.[column]);

type MountedNode = {
  run: (spec: object) => Promise<void>;
  /** What the node handed the nodes below it, each time it handed something on. */
  handedOn: () => any[];
  lastOutput: () => any;
};

/** An Autark node on the canvas, fed *input*, its runs handing on what they make. */
function mountNode(nodeId: string, { input = '', jsInterpreter }: { input?: unknown; jsInterpreter?: unknown } = {}): MountedNode {
  const outputCallback = jest.fn();
  const setOutput = jest.fn();
  let apply: (spec: string) => Promise<void> = async () => { };
  const Probe: React.FC = () => {
    const behavior = useAutkGrammarBehavior(
      {
        nodeId,
        input,
        defaultCode: '{}',
        outputCallback,
        interactionsCallback: jest.fn(),
        ...(jsInterpreter ? { jsInterpreter } : {}),
      } as any,
      { output: { code: '', content: '' }, setOutput, setCode: jest.fn(), templateData: {} } as any,
    );
    apply = behavior.applyGrammar as (spec: string) => Promise<void>;
    return <>{behavior.contentComponent}</>;
  };
  render(<Probe />);
  return {
    run: async (spec) => {
      await act(async () => { await apply(JSON.stringify(spec)); });
    },
    handedOn: () => outputCallback.mock.calls.map((call) => call[1]),
    lastOutput: () => setOutput.mock.calls[setOutput.mock.calls.length - 1]?.[0],
  };
}

beforeEach(() => {
  resetAutkNodeMocks();
  resetComputeStandIns();
  computeRuns.gpgpu.mockImplementation(async (params: any) => computed(params));
  mockLoaded.layers = [];
  mockLoaded.unreadable = null;
  mockKeepStep.mockReset();
  forgetPageSteps();
  inputsByPath.current = { 'art-lanes': LANES, 'art-lanes-density': { dataType: 'outputs', data: [LANES, DENSITY] } };
  // A map node's run, as autk-grammar's: its passes run on its own compute
  // adapter, which keeps each pass's result where `data` lists it, over a
  // database that exports each table as it was handed.
  const { createComputeAdapter } = jest.requireMock('@urban-toolkit/autk-grammar');
  grammarComputes.on = true;
  grammarComputes.adapter = (sources, cache, types) => createComputeAdapter(cache, types, sources);
  drawnExports.of = (_table, handed) => handed;
  stubWebGpu();
});

afterEach(() => {
  forgetPageSteps();
  unstubWebGpu();
});

describe('a node that draws hands on what it loads and computes, by the compute step rule', () => {
  test('one that draws, loads and runs a pass hands on its own tables, then the table the pass writes', async () => {
    mockLoaded.layers = [{ name: 'spots', type: 'points', features: spots().features }];
    const node = mountNode('loads-computes-draws');

    await node.run({
      data: [{ type: 'geojson', outputTableName: 'spots', geojsonObject: spots() }],
      compute: [pass('spots', 'twice', { outputTableName: 'doubled', layerType: 'points' })],
      map: { layerRefs: [{ dataRef: 'doubled', getFnv: 'twice' }] },
    });

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    const [handed] = node.handedOn();
    expect(namesAndTypes(handed)).toEqual([['spots', 'points'], ['doubled', 'points']]);
    // The pass's column, lifted to the top of each feature as a compute step lifts it.
    expect(valuesOf(tableNamed(handed, 'doubled').data, 'twice')).toEqual([2, 4, 6]);
    expect(valuesOf(tableNamed(handed, 'spots').data, 'twice')).toEqual([undefined, undefined, undefined]);
    // The node's own run computed it, once.
    expect(computeRuns.gpgpu).toHaveBeenCalledTimes(1);
  });

  test('one that draws and runs a pass over its input hands on the input tables as they came, then the table the pass writes', async () => {
    const node = mountNode('computes-draws', { input: ONE_LAYER });

    await node.run({
      compute: [pass('lanes', 'twice', { outputTableName: 'lane_twice', layerType: 'roads' })],
      map: { layerRefs: [{ dataRef: 'lane_twice', getFnv: 'twice' }] },
    });

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    const [handed] = node.handedOn();
    expect(namesAndTypes(handed)).toEqual([['lanes', 'roads'], ['lane_twice', 'roads']]);
    // The input's table as it came: the rows the upstream node handed on.
    expect(tableNamed(handed, 'lanes').data.features.map((f: any) => f.properties)).toEqual(
      spots().features.map((f: any) => f.properties),
    );
    const written = tableNamed(handed, 'lane_twice').data.features;
    expect(written.map((f: any) => f.properties.twice)).toEqual([2, 4, 6]);
    // What Curio marked the rows its map draws with stays in the node.
    expect(written.every((f: any) => !('__curio_row' in f.properties))).toBe(true);
    expect(computeRuns.gpgpu).toHaveBeenCalledTimes(1);
  });

  test('one that draws and loads, whose map names a table of its input, hands on that input table first', async () => {
    mockLoaded.layers = [{ name: 'streets', type: 'roads', features: streets().features }];
    const node = mountNode('loads-draws-input', { input: ONE_LAYER });

    await node.run({ data: OWN_STREETS, map: { layerRefs: [{ dataRef: 'streets' }, { dataRef: 'lanes' }] } });

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    const [handed] = node.handedOn();
    expect(namesAndTypes(handed)).toEqual([['lanes', 'roads'], ['streets', 'roads']]);
  });

  test('one with data of its own that never names its input hands on none of its input', async () => {
    mockLoaded.layers = [{ name: 'streets', type: 'roads', features: streets().features }];
    const node = mountNode('loads-draws', { input: ONE_LAYER });

    await node.run({ data: OWN_STREETS, map: { layerRefs: [{ dataRef: 'streets' }] } });

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    const [handed] = node.handedOn();
    expect(namesAndTypes(handed)).toEqual([['streets', 'roads']]);
  });

  test('on the canvas it keeps what it hands on in the sandbox, as a compute step does', async () => {
    const kept: string[] = [];
    const interpretCode = jest.fn((_unresolved, code: string, _input, _types, callback) => {
      kept.push(code);
      callback({ stdout: [], stderr: '', output: { path: 'art-handed', dataType: 'outputs' } });
    });
    const node = mountNode('computes-draws-kept', { input: ONE_LAYER, jsInterpreter: { interpretCode } });

    await node.run({
      compute: [pass('lanes', 'twice', { outputTableName: 'lane_twice', layerType: 'roads' })],
      map: { layerRefs: [{ dataRef: 'lane_twice' }] },
    });

    expect(node.handedOn()).toEqual([{ path: 'art-handed', dataType: 'outputs' }]);
    expect(kept).toHaveLength(1);
    const wrapper = JSON.parse(kept[0].slice('const __wrapper = '.length, kept[0].lastIndexOf(';\nreturn')));
    expect(namesAndTypes(wrapper)).toEqual([['lanes', 'roads'], ['lane_twice', 'roads']]);
  });
});

describe('a raster of the input goes on as it came', () => {
  test('from a compute step', async () => {
    const node = mountNode('compute-step', { input: LAYER_AND_RASTER });

    await node.run({ compute: [pass('lanes', 'twice')] });

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    const [handed] = node.handedOn();
    expect(tablesOf(handed).map((table) => table.layerName)).toEqual(['lanes', 'density']);
    expect(valuesOf(tableNamed(handed, 'lanes').data, 'twice')).toEqual([2, 4, 6]);
    expect(tableNamed(handed, 'density')).toEqual(DENSITY);
  });

  test('from a node that draws and loads', async () => {
    mockLoaded.layers = [{ name: 'streets', type: 'roads', features: streets().features }];
    const node = mountNode('loads-draws-raster', { input: LAYER_AND_RASTER });

    await node.run({ data: OWN_STREETS, map: { layerRefs: [{ dataRef: 'streets' }, { dataRef: 'lanes' }] } });

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    const [handed] = node.handedOn();
    expect(tablesOf(handed).map((table) => table.layerName)).toEqual(['lanes', 'density', 'streets']);
    expect(tableNamed(handed, 'density')).toEqual(DENSITY);
  });

  test("guard: a compute step hands on a raster its own data section makes, read back from the sandbox's load", async () => {
    // The brief of the dataflow audit's step 12 suspected the empty-layer
    // drop (`hasFeatures`) of leaving such a raster out: its cells are one
    // feature, so it is kept.
    inputsByPath.current = {
      'art-loaded': {
        dataType: 'list',
        data: [{ dataType: 'dict', data: { name: 'spots', type: 'points', geojson: spots() } }, DENSITY],
      },
    };
    const kept: string[] = [];
    const interpretCode = jest.fn((_unresolved, code: string, _input, _types, callback) => {
      if (code.startsWith('const __wrapper = ')) {
        kept.push(code);
        callback({ stdout: [], stderr: '', output: { path: 'art-handed', dataType: 'outputs' } });
      } else {
        callback({ stdout: [], stderr: '', output: { path: 'art-loaded', dataType: 'list' } });
      }
    });
    const node = mountNode('compute-own-raster', { jsInterpreter: { interpretCode } });

    await node.run({
      data: [
        { type: 'geojson', outputTableName: 'spots', geojsonObject: spots() },
        { type: 'geotiff', geotiffFileUrl: 'docs/examples/data/density.tif', outputTableName: 'density' },
      ],
      compute: [pass('spots', 'twice')],
    });

    expect(node.lastOutput()).toEqual({ code: 'success', content: 'Computed 2 layers: spots (3 rows), density (4 cells)' });
    expect(kept).toHaveLength(1);
    const wrapper = JSON.parse(kept[0].slice('const __wrapper = '.length, kept[0].lastIndexOf(';\nreturn')));
    expect(tablesOf(wrapper).map((table) => [table.dataType, table.layerName])).toEqual([
      ['geodataframe', 'spots'], ['raster', 'density'],
    ]);
  });
});

describe('guards: what does not change', () => {
  test('a node that only draws its input hands on its input as it came', async () => {
    const node = mountNode('only-draws', { input: ONE_LAYER });

    await node.run({ map: { layerRefs: [{ dataRef: 'lanes' }] } });

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    expect(node.handedOn()).toHaveLength(1);
    expect(node.handedOn()[0]).toBe(ONE_LAYER);
  });

  test('a data node whose section reads a table of its input still leaves that table out', async () => {
    // autk-db holds the input table the join reads beside the section's own.
    mockLoaded.layers = [
      { name: 'streets', type: 'roads', features: streets().features },
      { name: 'lanes', type: 'roads', features: spots().features },
    ];
    const node = mountNode('data-node', { input: ONE_LAYER });

    await node.run({ data: [...OWN_STREETS, { type: 'join', dataRef: 'streets', joinDataRef: 'lanes' }] });

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    const [handed] = node.handedOn();
    expect(namesAndTypes(handed)).toEqual([['streets', 'roads']]);
  });
});

describe("on a viewer's dashboard page", () => {
  /** A pinned map that runs a pass over its input and draws the table it writes. */
  const TILE = {
    compute: [pass('lanes', 'twice', { outputTableName: 'lane_twice', layerType: 'roads' })],
    map: { layerRefs: [{ dataRef: 'lane_twice' }] },
  };

  beforeEach(() => {
    flowDashboard.on = true;
  });

  test("a pinned tile that computes gives its result to the viewer's run that asked the page for it, as a compute step does", async () => {
    askPage('project-1', 'run-1', 'token-1', ['sky-tile']);
    mockKeepStep.mockResolvedValue({ output: { path: 'kept-sky', dataType: 'outputs' }, artifactIds: [] });
    const interpretCode = jest.fn();
    const node = mountNode('sky-tile', { input: ONE_LAYER, jsInterpreter: { interpretCode } });

    await node.run(TILE);

    expect(mockKeepStep).toHaveBeenCalledTimes(1);
    const [projectId, runId, token, nodeId, value] = mockKeepStep.mock.calls[0];
    expect([projectId, runId, token, nodeId]).toEqual(['project-1', 'run-1', 'token-1', 'sky-tile']);
    expect(namesAndTypes(value)).toEqual([['lanes', 'roads'], ['lane_twice', 'roads']]);
    expect(node.handedOn()).toEqual([{ path: 'kept-sky', dataType: 'outputs' }]);
    expect(interpretCode).not.toHaveBeenCalled();
  });

  test('guard: a draw no run asked of the page makes no call to the sandbox, which a viewer has no session for', async () => {
    const interpretCode = jest.fn();
    const node = mountNode('sky-tile', { input: ONE_LAYER, jsInterpreter: { interpretCode } });

    await node.run(TILE);

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    expect(interpretCode).not.toHaveBeenCalled();
    expect(mockKeepStep).not.toHaveBeenCalled();
  });
});

describe('a node that draws reads back the tables its sources after compute make, from the database its run went on', () => {
  // A map over its input whose pass writes `lane_twice`, then a SQL query after
  // compute that keeps the pass's rows as `lane_copy`. The run's sources reach
  // the grammar's data adapter, which goes on the node's own database, the
  // stand-in autk-db: it holds the input's table as the node handed it, each
  // row marked with the input row it stands for, and once the run is over the
  // table the query saved, as autk-db keeps the pass's rows: each with its mark
  // and the pass's column under `compute`.
  const AFTER_COMPUTE = {
    data: [{ type: 'sql', query: 'SELECT * FROM "lane_twice"', outputTableName: 'lane_copy', layerType: 'roads', after: 'compute' }],
    compute: [pass('lanes', 'twice', { outputTableName: 'lane_twice', layerType: 'roads' })],
    map: { layerRefs: [{ dataRef: 'lane_twice', getFnv: 'twice' }] },
  };
  /** The spots as the run's database holds them: each with its input row's mark, and *column* doubled under `compute`. */
  const heldRows = (column?: string) => spots().features.map((feature: any, row: number) => ({
    ...feature,
    properties: {
      ...feature.properties,
      __curio_row: row,
      ...(column ? { compute: { [column]: 2 * feature.properties.value } } : {}),
    },
  }));

  beforeEach(() => {
    grammarLoads.on = true;
    drawnExports.of = null;
    mockLoaded.layers = [
      { name: 'lanes', type: 'roads', features: heldRows() },
      { name: 'lane_copy', type: 'roads', features: heldRows('twice') },
    ];
  });

  test("hands on the table a source after compute made, without its map's marks, each pass's column lifted", async () => {
    const node = mountNode('reads-back', { input: ONE_LAYER });

    await node.run(AFTER_COMPUTE);

    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'success' }));
    const [handed] = node.handedOn();
    expect(namesAndTypes(handed)).toEqual([['lanes', 'roads'], ['lane_twice', 'roads'], ['lane_copy', 'roads']]);
    expect(tableNamed(handed, 'lane_copy').data.features.map((f: any) => f.properties)).toEqual(
      [1, 2, 3].map((value) => ({ value, compute: { twice: 2 * value }, twice: 2 * value })),
    );
  });

  test('a read-back that fails fails the run as a compute step fails, names it, hands on nothing, and leaves its maps drawn', async () => {
    mockLoaded.unreadable = 'lane_copy';
    const node = mountNode('reads-back', { input: ONE_LAYER });

    await node.run(AFTER_COMPUTE);

    const message = 'Compute failed: compute: Table lane_copy could not be read.';
    expect(node.lastOutput()).toEqual(expect.objectContaining({ code: 'error', content: message }));
    expect(showToast).toHaveBeenLastCalledWith(message, 'error');
    expect(node.handedOn()).toEqual([]);
    // It drew: its grammar, and the maps it made, are the node's until its next run.
    expect(grammarRuns).toHaveLength(1);
    expect(grammarRuns[0].destroy).not.toHaveBeenCalled();
  });
});
