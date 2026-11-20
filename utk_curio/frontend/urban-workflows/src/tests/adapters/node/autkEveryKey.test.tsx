/**
 * Every key of autk-grammar 5.4.0's maps, plots, compute passes and
 * workspaces, as a node runs it, from the documents of
 * fixtures/autk-every-key.json, on the tables an upstream Autark node hands
 * on: `lines`, in the default workspace and in `east`, and `towers`, buildings
 * in `east`.
 *
 * - A map of every layer key, a map of OpenStreetMap elements in a workspace
 *   `workspaces` sets, a plot of every mark with every plot key and with every
 *   key of its colors, ticks, titles and selection, plots of every mark over
 *   one `colorMapRange`, and a map and a plot laid out and linked by every
 *   layout and link key: the node hands the grammar each key as the document
 *   writes it, whatever it adds (a plot's size, the tables it reads).
 * - A compute step's GPGPU and render passes with every pass key: they run
 *   through autk-grammar's own compute code, the build the app bundles, and
 *   reach a stand-in autk-compute that records each dispatch
 *   (_support/autkComputeStandIns), with each key's value there, and the
 *   tables they write are handed on with the type and the workspace the
 *   passes give them.
 * - A compute step's windows and clusters passes: they run on autk-core's
 *   CPU code, the build the app bundles, and their tables are handed on as
 *   those passes write them, in a table of their own or in place.
 *
 * utk_curio/backend/tests/autk_grammar_key_tests.json names these tests for
 * each key, and backend/tests/test_agents/test_autk_every_key_documents.py runs
 * the same documents through the agents' document check.
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
}), { virtual: true });

import fs from 'fs';
import path from 'path';
import { applyComputeBlocks } from '../../../adapters/node/autkComputeBlocks';
import { grammarRuns as mockRuns, inputsByPath, resetAutkNodeMocks } from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import { computeRuns, resetComputeStandIns } from '../../_support/autkComputeStandIns';

type Case = { name: string; document: any };

const FIXTURE: { views: Case[]; passes: Case[] } = JSON.parse(
  fs.readFileSync(path.join(__dirname, '../../fixtures/autk-every-key.json'), 'utf8'),
);

/** The document of the fixture's case *name* in *section*. */
const documentOf = (section: Case[], name: string): any => {
  const found = section.find((c) => c.name === name);
  if (!found) throw new Error(`fixtures/autk-every-key.json has no case "${name}"`);
  return found.document;
};

/** A street of the Loop at longitude *x*, its `rank` and `kind`, and arrays and matrices of its x. */
const line = (x: number, rank: number, kind: string) => ({
  type: 'Feature',
  geometry: { type: 'LineString', coordinates: [[x, 41.88], [x + 0.001, 41.881]] },
  properties: { x, rank, kind, xs: [x, x + 0.001], box: [[x, 41.88], [x + 0.001, 41.881]] },
});

/**
 * A building of the Loop: a footprint from longitude *west* to *east* and
 * latitude 41.88 to 41.8804, *height* metres tall.
 */
const tower = (west: number, east: number, height: number) => ({
  type: 'Feature',
  geometry: { type: 'Polygon', coordinates: [[[west, 41.88], [east, 41.88], [east, 41.8804], [west, 41.8804], [west, 41.88]]] },
  properties: { height },
});

/**
 * What an upstream Autark data node hands on: `lines` in the default workspace
 * and in `east`, and three `towers` in `east`, the first two sharing a wall.
 */
const RECORDS = [
  { name: 'lines', type: 'polylines', geojson: { type: 'FeatureCollection', features: [line(-87.6, 0, 'a')] } },
  {
    name: 'lines', type: 'polylines', workspace: 'east',
    geojson: { type: 'FeatureCollection', features: [line(-87.5, 0, 'a'), line(-87.49, 1, 'b'), line(-87.48, 2, 'a')] },
  },
  {
    name: 'towers', type: 'buildings', workspace: 'east',
    geojson: {
      type: 'FeatureCollection',
      features: [tower(-87.495, -87.4946, 30), tower(-87.4946, -87.4942, 45), tower(-87.49, -87.4896, 20)],
    },
  },
];
const INPUT = { path: 'art-every-key', dataType: 'list' };
/** East's `x`, row by row. */
const EAST_XS = [-87.5, -87.49, -87.48];

/**
 * Where *handed* does not hold what *written* holds, however deep, by path:
 * each object's keys, each list item by item, each value as it is.
 */
function notHanded(written: unknown, handed: unknown, at: string): string[] {
  if (Array.isArray(written)) {
    if (!Array.isArray(handed) || handed.length !== written.length) return [`${at}: ${JSON.stringify(handed)}`];
    return written.flatMap((item, i) => notHanded(item, handed[i], `${at}[${i}]`));
  }
  if (written !== null && typeof written === 'object') {
    if (handed === null || typeof handed !== 'object' || Array.isArray(handed)) return [`${at}: ${JSON.stringify(handed)}`];
    return Object.entries(written as Record<string, unknown>)
      .flatMap(([key, value]) => notHanded(value, (handed as Record<string, unknown>)[key], `${at}.${key}`));
  }
  return Object.is(written, handed) ? [] : [`${at}: ${JSON.stringify(handed)}, written ${JSON.stringify(written)}`];
}

beforeEach(() => {
  resetAutkNodeMocks();
  resetComputeStandIns();
  inputsByPath.current = { 'art-every-key': { dataType: 'list', data: RECORDS } };
  stubWebGpu();
});

afterEach(() => {
  unstubWebGpu();
});

describe('a node hands the grammar every key of its map or its plot as its document writes it', () => {
  test.each(FIXTURE.views.map((c) => [c.name, c.document] as const))('%s', async (_name, document) => {
    const node = mountAutkNode('every-key', undefined, { input: INPUT });
    await node.run(document);
    // A run that failed says why.
    expect(node.lastOutput()?.code === 'error' ? node.lastOutput()?.content : null).toBeNull();
    expect(mockRuns).toHaveLength(1);
    const handed = mockRuns[0].spec;
    const problems = ['$schema', 'workspaces', 'map', 'plot', 'layout', 'links']
      .filter((section) => section in document)
      .flatMap((section) => notHanded(document[section], handed[section], section));
    expect(problems).toEqual([]);
  });
});

describe('a compute step hands autk-compute every key of its passes', () => {
  const LAYERS = RECORDS.map(({ name, type, geojson, workspace }: any) => ({
    name, type, geojson, ...(workspace ? { workspace } : {}),
  }));

  test('GPGPU passes: attributes and their arrays and matrices, uniforms of every form, and the columns and table they write', async () => {
    const { compute } = documentOf(FIXTURE.passes, 'GPGPU passes of every pass key');
    const failures: string[] = [];
    const out = await applyComputeBlocks(LAYERS as any, compute, failures);
    expect(failures).toEqual([]);
    expect(computeRuns.gpgpu).toHaveBeenCalledTimes(2);
    const [first, second] = computeRuns.gpgpu.mock.calls.map((call) => call[0]);

    // The first reads east's table, row for row.
    expect(first.collection.features.map((f: any) => f.properties.x)).toEqual(EAST_XS);
    expect(first).toEqual(expect.objectContaining({
      variableMapping: { x: 'x', xs: 'xs', box: 'box' },
      wgslBody: 'let y = x * scale;\nreturn y;',
      attributeArrays: { xs: 2 },
      attributeMatrices: { box: { rows: 'auto', cols: 2 } },
      uniformArrays: { weights: [0.5, 0.25] },
      resultField: 'y',
    }));
    // A number as written; a feature's value, by its index and path; a
    // value a feature does not hold, as its default.
    expect(first.uniforms).toEqual({ scale: 2, second: -87.49, missing: 7 });
    expect(first.uniformMatrices).toEqual({
      turn: { data: [[0, 1], [1, 0]], cols: 2 },
      fallback: { data: [[0, 0]], cols: 2 },
    });
    expect(second.collection.features.map((f: any) => f.properties.x)).toEqual(EAST_XS);
    expect(second).toEqual(expect.objectContaining({ outputColumns: ['a', 'b'], wgslBody: 'return array<f32, 2>(x, x);' }));

    // The table the first writes is handed on as the type it gives it, in its workspace.
    expect(out.map((layer: any) => [layer.name, layer.type, layer.workspace])).toContainEqual(['lines_y', 'points', 'east']);
  });

  test('a render pass: its layer with its object ids, its viewpoints sampled from their centroids, objects counted, its camera and tiles, and the table it writes', async () => {
    const { compute } = documentOf(FIXTURE.passes, 'a render pass of every pass key');
    const failures: string[] = [];
    const out = await applyComputeBlocks(LAYERS as any, compute, failures);
    expect(failures).toEqual([]);
    expect(computeRuns.render).toHaveBeenCalledTimes(1);
    const params = computeRuns.render.mock.calls[0][0];

    expect(params.layers.map((l: any) => [l.id, l.type, l.objectIdProperty, l.collection.features.map((f: any) => f.properties.x)]))
      .toEqual([['streets', 'polylines', 'rank', EAST_XS]]);
    expect(params.viewpoints.collection.features.map((f: any) => f.properties.x)).toEqual(EAST_XS);
    expect(params.viewpoints.strategy).toEqual({ type: 'centroid' });
    expect(params.viewpoints.sampling).toEqual({ directions: 4, pitchDeg: 10, azimuthOffsetDeg: 45 });
    expect(params.aggregation).toEqual({ type: 'objects' });
    expect(params.camera).toEqual({ fov: 60, clip: { near: 0.5, far: 2000 } });
    expect(params.tileSize).toBe(32);

    // The table it writes is handed on as the type it gives it, in its workspace.
    expect(out.map((layer: any) => [layer.name, layer.type, layer.workspace])).toContainEqual(['seen', 'points', 'east']);
  });

  test('windows and clusters passes: the windows of the towers as a table of points, and the clusters of the towers and of the lines, in a table of their own and in place', async () => {
    const { compute } = documentOf(FIXTURE.passes, 'windows and clusters passes of every pass key');
    const failures: string[] = [];
    const out = await applyComputeBlocks(LAYERS as any, compute, failures);
    expect(failures).toEqual([]);
    // Both run on the CPU, through autk-core: nothing reaches autk-compute.
    expect(computeRuns.gpgpu).not.toHaveBeenCalled();
    expect(computeRuns.render).not.toHaveBeenCalled();
    const table = (name: string) => out.find((layer: any) => layer.name === name && layer.workspace === 'east') as any;

    // One point a window on each tower, two rows up each facade, drawn as the pass's layerType.
    const windows = table('towers_windows');
    expect(windows?.type).toBe('points');
    expect(new Set(windows.geojson.features.map((f: any) => f.properties.sourceFeatureIndex))).toEqual(new Set([0, 1, 2]));
    expect(new Set(windows.geojson.features.map((f: any) => f.properties.floorIndex))).toEqual(new Set([0, 1]));
    expect(windows.geojson.features.every((f: any) => f.geometry?.type === 'Point')).toBe(true);

    // The two towers that share a wall are one cluster, the third another, in a table of the pass's layerType,
    // its ids also under their own name.
    const blocks = table('towers_blocks');
    expect(blocks?.type).toBe('polygons');
    expect(blocks.geojson.features.map((f: any) => f.properties.compute.block)).toEqual([0, 0, 1]);
    expect(blocks.geojson.features.map((f: any) => f.properties.block)).toEqual([0, 0, 1]);

    // In place: the three lines touch none of the others.
    const lines = table('lines');
    expect(lines?.type).toBe('polylines');
    expect(lines.geojson.features.map((f: any) => f.properties.compute.network)).toEqual([0, 1, 2]);
  });
});
