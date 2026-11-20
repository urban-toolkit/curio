/**
 * A map layer's `pickedComps` (autk-grammar 5.3.0) lists the features it
 * draws as picked as it is drawn, and the grammar's run lights them once the
 * maps, the plots and their links exist. An Autark node then lights what comes
 * into it (syncHighlights): a Data Pool's flags and a linked chart's
 * selection. With nothing coming in it keeps the features its document picks,
 * as it keeps a plot's `selection`; what does come in is what the layer shows.
 *
 * The grammar is the stand-in of _support/autkNodeMocks, which records each
 * highlight the node asks of the map.
 */
import { waitFor } from '@testing-library/react';

jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => require('../../_support/autkNodeMocks').autkGrammarModule,
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

import { grammarRuns as mockRuns, resetAutkNodeMocks } from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';

/** Three rows, each with its `pop`. */
const ROWS = {
  type: 'FeatureCollection',
  features: [0, 1, 2].map((n) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [n, 0] }, properties: { pop: n } })),
};

/** A map of the input whose one layer picks, with *picked* drawn as picked when given. */
const pickingMap = (picked?: number[]) => ({
  map: { layerRefs: [{ dataRef: 'input_0', isPick: true, ...(picked ? { pickedComps: picked } : {}) }] },
});

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
});

afterEach(unstubWebGpu);

test("a layer's pickedComps stay lit once it is drawn, with nothing coming into the node", async () => {
  const node = mountAutkNode('picked-1', ROWS);
  await node.run(pickingMap([0, 2]));
  expect(node.lastOutput()).toMatchObject({ code: 'success' });

  // The node lights what came in once the map is drawn: nothing here.
  await waitFor(() => expect(mockRuns[0].highlights.length).toBeGreaterThan(0));
  await new Promise((resolve) => setTimeout(resolve, 50));
  const highlights = mockRuns[0].highlights;
  expect(highlights.filter(([table, positions]) => table === 'input_0' && positions.length === 0)).toEqual([]);
  expect(highlights[highlights.length - 1]).toEqual(['input_0', [0, 2]]);
});

test('a layer without pickedComps is cleared when nothing comes in, as before', async () => {
  const node = mountAutkNode('picked-2', ROWS);
  await node.run(pickingMap());

  await waitFor(() => expect(mockRuns[0].highlights.length).toBeGreaterThan(0));
  const highlights = mockRuns[0].highlights;
  expect(highlights[highlights.length - 1]).toEqual(['input_0', []]);
});

test('rows that come in are what the layer lights, in place of its pickedComps', async () => {
  // The Data Pool's flags: the middle row interacted.
  const flagged = {
    ...ROWS,
    features: ROWS.features.map((feature, i) => ({ ...feature, properties: { ...feature.properties, interacted: i === 1 ? '1' : '0' } })),
  };
  const node = mountAutkNode('picked-3', flagged);
  await node.run(pickingMap([0, 2]));
  await waitFor(() => expect(mockRuns[0].highlights.length).toBeGreaterThan(0));
  const highlights = mockRuns[0].highlights;
  expect(highlights[highlights.length - 1]).toEqual(['input_0', [1]]);
});
