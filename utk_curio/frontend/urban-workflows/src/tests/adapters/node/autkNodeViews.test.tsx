/**
 * An Autark node's run reads its views as a list (adapters/node/autkViews):
 * each highlight a draw asks of a map names that map, by its index, so two
 * maps of one table light only their own rows; and a pick or a brush is read
 * from the view autk-grammar 5.0.0 names in it (`mapId`, `plotId`).
 *
 * A node draws one view while the one-view rule stands, so these drive the
 * node with one map or one plot, through the stand-in grammar
 * (_support/autkNodeMocks); autkViews.test.ts drives the per-view helpers
 * with two maps.
 */
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class { } }));
jest.mock('@urban-toolkit/autk-grammar', () => require('../../_support/autkNodeMocks').autkGrammarModule, { virtual: true });
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

import { act, waitFor } from '@testing-library/react';
import { grammarRuns, resetAutkNodeMocks } from '../../_support/autkNodeMocks';
import { lastSelection, mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';

/** Two rows, the second picked or lit. */
const TWO_ROWS = {
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { pop: 1 } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [1, 1] }, properties: { pop: 2, interacted: '1' } },
  ],
};

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
});

afterEach(unstubWebGpu);

test('each highlight a draw asks of its map names the map, by its index', async () => {
  const node = mountAutkNode('map-1', TWO_ROWS);
  await node.run({ map: { id: 'buildings', layerRefs: [{ dataRef: 'input_0' }] } });
  const [run] = grammarRuns;
  await waitFor(() => expect(run.highlights.some(([, positions]) => positions.length > 0)).toBe(true));
  expect(run.highlightMaps).toEqual(run.highlights.map(() => 0));
});

test('a layer that lights nothing is cleared on its own map', async () => {
  const node = mountAutkNode('map-1');
  await node.run({ map: { layerRefs: [{ dataRef: 'input_0' }] } });
  const [run] = grammarRuns;
  await waitFor(() => expect(run.highlights.length).toBeGreaterThan(0));
  expect(run.highlights.every(([, positions]) => positions.length === 0)).toBe(true);
  expect(run.highlightMaps).toEqual(run.highlights.map(() => 0));
});

test('a pick that names its map and layer is read from that map', async () => {
  const node = mountAutkNode('map-1', TWO_ROWS);
  await node.run({ map: { id: 'buildings', layerRefs: [{ dataRef: 'input_0', isPick: true }] } });
  await act(async () => {
    grammarRuns[0].pickOn('buildings', 'input_0', [1]);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(lastSelection(node)).toMatchObject({ data: [1], layerRef: 'input_0' });
});

test('a brush that names its plot by its id is read from that plot', async () => {
  const node = mountAutkNode('plot-1', TWO_ROWS);
  await node.run({ plot: { id: 'heights', dataRef: 'input_0', mark: 'bar', axis: ['pop'], events: ['brushX'] } });
  await act(async () => {
    grammarRuns[0].brushOn('heights', [0]);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(lastSelection(node)).toMatchObject({ data: [0], layerRef: 'input_0' });
});
