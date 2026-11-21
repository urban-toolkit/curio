/**
 * A map node hands its grammar adapters of its own around the grammar's
 * (autk-grammar 5.6.0's `AutkGrammarOptions`): `wrapDataAdapter`, which hands
 * the run the node's own database (adapters/node/autkDbClose `runDatabase`)
 * and loads its rasters, and `wrapComputeAdapter`, which checks each pass
 * (`checkedPasses`).
 *
 * - The grammar build the app bundles calls each wrap function as it is made
 *   and sends the run's workspaces, every source and every pass through the
 *   host's adapters, on the database the host hands it. A build before 5.6.0
 *   takes no options and says nothing, so a node's passes would run
 *   unchecked and its run would go on a database of the grammar's.
 * - A run that fails ends the node's database. autk-grammar keeps the
 *   database of a run only once the run ends, and the node used to end the
 *   database it found there: after a failed run it found none, and the DuckDB
 *   worker of the database the run had made stayed, one more for each failed
 *   draw.
 *
 * The grammar is the build the app bundles, as CommonJS. jsdom has neither
 * DuckDB nor WebGPU: autk-db is a stand-in that records each database made,
 * the workspaces set up and the tables loaded into it, and the end of its
 * DuckDB worker, and autk-compute the stand-in of _support/autkComputeStandIns.
 * Autark's packages are mocked virtually, as every suite mocks them
 * (tests/mockKinds.test.ts).
 */
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class { } }));
jest.mock('@urban-toolkit/autk-grammar', () => require('../../_support/autkComputeStandIns').grammarBuild(), { virtual: true });
jest.mock('@urban-toolkit/autk-compute', () => require('../../_support/autkComputeStandIns').autkComputeModule, { virtual: true });
jest.mock('@urban-toolkit/autk-core', () => require('../../_support/autkComputeStandIns').autkCoreBuild(), { virtual: true });
jest.mock('@urban-toolkit/autk-map', () => require('../../_support/autkComputeStandIns').autkMapModule, { virtual: true });
jest.mock('@urban-toolkit/autk-plot', () => require('../../_support/autkComputeStandIns').autkPlotModule, { virtual: true });

/** Each database made, in order: the workspaces set up in it, the tables loaded into it, and the end of its DuckDB worker. */
const mockDatabases: Array<{ configured: string[]; loaded: string[]; terminate: jest.Mock }> = [];
/** The table whose load fails, as autk-db fails one it cannot load: none unless a test names one. */
const mockFailing: { table: string | null } = { table: null };
jest.mock('@urban-toolkit/autk-db', () => {
  class AutkDb {
    private tables = new Map<string, { type: string; collection: any }>();
    private workspace = 'autk';
    private configured: string[] = [];
    private loaded: string[] = [];
    // DuckDB-Wasm's database, as autk-db keeps it.
    db = { terminate: jest.fn(async () => undefined) };
    constructor() {
      mockDatabases.push({ configured: this.configured, loaded: this.loaded, terminate: this.db.terminate });
    }
    async init(): Promise<void> { }
    getCurrentWorkspace(): string {
      return this.workspace;
    }
    async setWorkspace(name: string, configuration?: unknown): Promise<void> {
      if (configuration) this.configured.push(name);
      this.workspace = name;
    }
    async loadGeojson({ outputTableName, geojsonObject, layerType }: any): Promise<void> {
      if (outputTableName === mockFailing.table) throw new Error(`Binder Error: ${outputTableName} could not be loaded`);
      this.tables.set(outputTableName, { type: layerType ?? 'polygons', collection: geojsonObject });
      this.loaded.push(outputTableName);
    }
    async getBoundingBoxFromLayer(): Promise<never> {
      throw new Error('this stand-in keeps no bounding boxes');
    }
    getTablesMetadata() {
      return [...this.tables].map(([name, { type }]) => ({ name, type, source: 'geojson', columns: [] }));
    }
    getLayersMetadata() {
      return this.getTablesMetadata();
    }
    async getLayer(name: string) {
      const table = this.tables.get(name);
      if (!table) throw new Error(`Table ${name} not found.`);
      return table.collection;
    }
    getWorkspaceConfiguration() {
      return { coordinateFormat: 'EPSG:3395', precisionGrid: 0.01 };
    }
  }
  return { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT: 'EPSG:3395', DEFAULT_WORKSPACE_NAME: 'autk' };
}, { virtual: true });

import { AutkDb } from '@urban-toolkit/autk-db';
import { inputsByPath, resetAutkNodeMocks } from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import { grammarBuild, gpuErrors, resetComputeStandIns } from '../../_support/autkComputeStandIns';

const { AutkGrammar } = grammarBuild();

beforeEach(() => {
  resetComputeStandIns();
  mockDatabases.length = 0;
  mockFailing.table = null;
});

/** Each database made: the tables loaded into it, and how many times its DuckDB worker was ended. */
const databasesMade = () => mockDatabases.map(({ loaded, terminate }) => [loaded, terminate.mock.calls.length]);

describe("the grammar build the app bundles takes a host's adapters around its own", () => {
  /** A square of side 40 at *x*, in the workspace's planar units. */
  const tower = (x: number) => ({
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [[[x, 0], [x + 40, 0], [x + 40, 40], [x, 40], [x, 0]]] },
    properties: { height: 150 },
  });
  /** Two towers 20 units apart and a spot, already in the workspace's CRS. */
  const DATA = [
    {
      type: 'geojson', outputTableName: 'towers', coordinateFormat: 'EPSG:3395',
      geojsonObject: { type: 'FeatureCollection', features: [tower(0), tower(60)] },
    },
    {
      type: 'geojson', outputTableName: 'spots', coordinateFormat: 'EPSG:3395',
      geojsonObject: {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [50, 20] }, properties: { spot: 0 } }],
      },
    },
  ];
  const CLUSTERS = { type: 'clusters', dataRef: 'towers', outputColumnName: 'block', outputTableName: 'blocks' };

  test("calls each wrap function once, as the grammar is made, with the grammar's own adapter", () => {
    const wrapDataAdapter = jest.fn((adapter: any) => adapter);
    const wrapComputeAdapter = jest.fn((adapter: any) => adapter);

    new AutkGrammar({}, { wrapDataAdapter, wrapComputeAdapter });

    expect(wrapDataAdapter).toHaveBeenCalledTimes(1);
    const [data] = wrapDataAdapter.mock.calls[0];
    expect([typeof data.resolveSource, typeof data.resolveWorkspaces]).toEqual(['function', 'function']);
    expect(wrapComputeAdapter).toHaveBeenCalledTimes(1);
    expect(typeof wrapComputeAdapter.mock.calls[0][0].resolveCompute).toBe('function');
  });

  test("sends a run's workspaces, every source and every pass through the host's adapters, on the database the host hands it", async () => {
    const host: any = new AutkDb();
    await host.init();
    const calls: Array<[string, unknown]> = [];
    const grammar = new AutkGrammar({}, {
      wrapDataAdapter: (adapter: any) => ({
        resolveWorkspaces: (context: unknown, workspaces: any[]) => {
          calls.push(['workspaces', context]);
          return adapter.resolveWorkspaces(context ?? host, workspaces);
        },
        resolveSource: (context: unknown, source: any) => {
          calls.push([`source ${source.outputTableName}`, context]);
          return adapter.resolveSource(context ?? host, source);
        },
      }),
      wrapComputeAdapter: (adapter: any) => ({
        resolveCompute: (context: unknown, pass: any) => {
          calls.push([`pass ${pass.outputTableName}`, context]);
          return adapter.resolveCompute(context, pass);
        },
      }),
    });

    await grammar.run({ workspaces: [{ coordinateFormat: 'EPSG:3395', precisionGrid: 0.01 }], data: DATA, compute: [CLUSTERS] });

    expect(calls.map(([call]) => call)).toEqual(['workspaces', 'source towers', 'source spots', 'pass blocks']);
    // The first call was handed no database, and each after it the host's.
    expect(calls.map(([, context]) => (context === undefined ? 'none' : context === host ? 'host' : 'another')))
      .toEqual(['none', 'host', 'host', 'host']);
    // The grammar's own adapters ran on the host's database, and made none of their own.
    expect(mockDatabases).toHaveLength(1);
    expect(mockDatabases[0].configured).toEqual(['autk']);
    expect(mockDatabases[0].loaded).toEqual(['towers', 'spots']);
    // The pass went through the grammar's own compute adapter, wired to its caches: the run keeps what it wrote.
    const blocks = await grammar.data.blocks;
    expect(blocks.features.map((feature: any) => feature.properties.compute.block)).toEqual([0, 1]);
  });
});

describe("a map node's run goes on a database of the node's own, which the node ends when the run fails", () => {
  /** A block of the Chicago Loop at *lon*, in degrees, as an upstream node hands it on. */
  const block = (lon: number) => ({
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [[[lon, 41.88], [lon + 0.001, 41.88], [lon + 0.001, 41.881], [lon, 41.881], [lon, 41.88]]] },
    properties: { value: 2 },
  });
  const BLOCKS = { name: 'blocks', type: 'polygons', geojson: { type: 'FeatureCollection', features: [block(-87.63), block(-87.62)] } };
  const STREETS = {
    name: 'streets',
    type: 'polylines',
    geojson: {
      type: 'FeatureCollection',
      features: [{ type: 'Feature', geometry: { type: 'LineString', coordinates: [[-87.63, 41.879], [-87.62, 41.879]] }, properties: { lanes: 2 } }],
    },
  };
  /** What reaches the node: an upstream Autark node's tables. */
  const INPUT = { path: 'art-tables', dataType: 'list' };
  /** A map of both tables, the blocks first. */
  const BOTH = { map: { layerRefs: [{ dataRef: 'blocks' }, { dataRef: 'streets' }] } };

  beforeEach(() => {
    resetAutkNodeMocks();
    inputsByPath.current = { 'art-tables': { dataType: 'list', data: [BLOCKS, STREETS] } };
    stubWebGpu();
  });

  afterEach(unstubWebGpu);

  test('a run that fails after its first source ends the database the node handed it', async () => {
    mockFailing.table = 'streets';
    const node = mountAutkNode('db-map', undefined, { input: INPUT });

    await node.run(BOTH);

    expect(node.lastOutput()?.code).toBe('error');
    expect(node.lastOutput()?.content).toContain('streets could not be loaded');
    // One database: the blocks went into it, the streets failed, and its worker was ended.
    expect(databasesMade()).toEqual([[['blocks'], 1]]);
  });

  test("so does one whose document sets up workspaces, which the run hands the node's database first", async () => {
    mockFailing.table = 'streets';
    const node = mountAutkNode('db-map', undefined, { input: INPUT });

    await node.run({ workspaces: [{ coordinateFormat: 'EPSG:3395', precisionGrid: 0.01 }], ...BOTH });

    expect(node.lastOutput()?.code).toBe('error');
    // The workspace was set up in the same database the blocks went into.
    expect(mockDatabases.map(({ configured }) => configured)).toEqual([['autk']]);
    expect(databasesMade()).toEqual([[['blocks'], 1]]);
  });

  test("a pass the GPU refuses fails the run through the node's check, named by its table, and ends the database", async () => {
    gpuErrors.next = { internal: 'CreateComputePipelines failed with VK_ERROR_UNKNOWN' };
    inputsByPath.current = { 'art-tables': { dataType: 'list', data: [BLOCKS] } };
    const node = mountAutkNode('db-map', undefined, { input: INPUT });

    await node.run({
      compute: [{
        dataRef: 'blocks', attributes: { v: 'value' }, wgslFunction: 'return v * 2.0;',
        outputColumnName: 'twice', outputTableName: 'doubled',
      }],
      map: { layerRefs: [{ dataRef: 'doubled' }] },
    });

    expect(node.lastOutput()?.code).toBe('error');
    expect(node.lastOutput()?.content).toContain(
      'doubled: the GPU could not run this compute pass: CreateComputePipelines failed with VK_ERROR_UNKNOWN',
    );
    expect(databasesMade()).toEqual([[['blocks'], 1]]);
  });
});
