/**
 * Each Autark draw ends the DuckDB worker of the draw before it
 * (adapters/node/autkDbClose).
 *
 * autk-grammar makes a database for every run, and DuckDB-Wasm runs each in a
 * worker that compiles its own WebAssembly. Nothing ended them, so every map
 * draw kept one more. The Crown Heights dashboard draws three maps a day: in
 * Firefox, which caps the WebAssembly code a page may compile, the second day
 * picked ran out of it ("failed to allocate executable memory for module",
 * then "out of memory") and its three maps stayed gray. Chromium kept them:
 * 5 workers on open, then 4 more with each day, none ended (dev, 0.17.8).
 *
 * The grammar is a stand-in (_support/autkNodeMocks) whose database ends with
 * the `terminate` each run records, as DuckDB-Wasm's does.
 */

jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class { } }));
jest.mock('@urban-toolkit/autk-grammar', () => require('../../_support/autkNodeMocks').autkGrammarModule, { virtual: true });
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });
// A data step's database (loadSpecLayers), with DuckDB-Wasm's database in its
// `db` as autk-db keeps it.
const mockDatabases: Array<{ terminate: jest.Mock; layersRead: () => number }> = [];
jest.mock(
  '@urban-toolkit/autk-db',
  () => ({
    DEFAULT_WORKSPACE_COORDINATE_FORMAT: 'EPSG:3395',
    AutkDb: class {
      private tables: Array<{ name: string; type: string; features: any[] }> = [];
      private read = 0;
      db = { terminate: jest.fn(async () => undefined) };
      constructor() {
        mockDatabases.push({ terminate: this.db.terminate, layersRead: () => this.read });
      }
      async init() { }
      async loadGeojson(source: any) {
        this.tables.push({ name: source.outputTableName, type: 'parks', features: source.geojsonObject.features });
      }
      getLayersMetadata() { return this.tables.map(({ name, type }) => ({ name, type })); }
      async getLayer(name: string) {
        // A read after the database ended fails, as a terminated worker's does.
        if (this.db.terminate.mock.calls.length > 0) throw new Error('the worker was terminated');
        this.read += 1;
        const table = this.tables.find((t) => t.name === name)!;
        return { type: 'FeatureCollection', features: table.features.map((f) => ({ ...f })) };
      }
    },
  }),
  { virtual: true },
);

import { failedDraws, grammarRuns, resetAutkNodeMocks } from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import { loadSpecLayers } from '../../../adapters/node/autkLayerMaterialize';

const MAP = { layerRefs: [{ dataRef: 'input_0', getFnv: 'pop' }] };
const ended = () => grammarRuns.map((run) => run.terminate.mock.calls.length);

beforeEach(() => {
  resetAutkNodeMocks();
  mockDatabases.length = 0;
  stubWebGpu();
});

afterEach(unstubWebGpu);

describe("a map's draws", () => {
  test("the next draw ends the DuckDB worker of the draw before, and keeps its own", async () => {
    const node = mountAutkNode('map-1');

    await node.run({ map: MAP });
    expect(ended()).toEqual([0]);
    await node.run({ map: MAP });

    expect(ended()).toEqual([1, 0]);
  });

  test("four days drawn keep one worker, the last day's", async () => {
    const node = mountAutkNode('map-1');

    for (let day = 0; day < 4; day += 1) await node.run({ map: MAP });

    expect(ended()).toEqual([1, 1, 1, 0]);
  });

  test('a map that leaves the page ends its last draw\'s worker', async () => {
    const node = mountAutkNode('map-1');
    await node.run({ map: MAP });

    node.unmount();

    expect(ended()).toEqual([1]);
  });

  test('a draw that fails ends the worker it started', async () => {
    failedDraws.error = new Error('Binder Error: no table named parks');
    const node = mountAutkNode('map-1');

    await node.run({ map: MAP });

    expect(node.lastOutput()?.code).toBe('error');
    expect(ended()).toEqual([1]);
  });
});

describe("a data step's layers", () => {
  test('are all read before the worker that loaded them ends', async () => {
    const features = [{ type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { pop: 1 } }];

    const layers = await loadSpecLayers({
      data: [{ type: 'geojson', outputTableName: 'parks', geojsonObject: { type: 'FeatureCollection', features } }],
    });

    expect(layers.map((layer) => [layer.name, layer.geojson.features.length])).toEqual([['parks', 1]]);
    expect(mockDatabases.map((database) => [database.layersRead(), database.terminate.mock.calls.length])).toEqual([[1, 1]]);
  });
});
