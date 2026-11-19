/**
 * A plot's `selection` (autk-grammar 5.2.0) lists the rows it selects as it
 * is drawn, and the grammar's run applies it once the plots and their links
 * exist. An Autark node then lights what comes into it (syncHighlights): a
 * Data Pool's flags and a linked chart's selection. With nothing coming in it
 * keeps the selection the document writes; what does come in is what the plot
 * shows.
 *
 * The grammar is the stand-in of _support/autkNodeMocks, which records each
 * selection the node asks of the plot.
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

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
});

afterEach(unstubWebGpu);

test("a plot's selection stays once it is drawn, with nothing coming into the node", async () => {
  const node = mountAutkNode('kept-1', ROWS);
  await node.run({ plot: { id: 'pops', dataRef: 'input_0', mark: 'bar', axis: ['pop'], selection: [2] } });
  expect(node.lastOutput()).toMatchObject({ code: 'success' });

  // The node lights what came in once the plot is drawn: nothing here.
  await waitFor(() => expect(mockRuns[0].plotSelections.length).toBeGreaterThan(0));
  await new Promise((resolve) => setTimeout(resolve, 50));
  const selections = mockRuns[0].plotSelections;
  expect(selections.filter(([plot, rows]) => plot === 'pops' && rows.length === 0)).toEqual([]);
  expect(selections[selections.length - 1]).toEqual(['pops', [2]]);
});

test('a plot without a selection is cleared when nothing comes in, as before', async () => {
  const node = mountAutkNode('kept-2', ROWS);
  await node.run({ plot: { id: 'pops', dataRef: 'input_0', mark: 'bar', axis: ['pop'] } });

  await waitFor(() => expect(mockRuns[0].plotSelections.length).toBeGreaterThan(0));
  const selections = mockRuns[0].plotSelections;
  expect(selections[selections.length - 1]).toEqual(['pops', []]);
});

test('rows that come in are what the plot shows, in place of its own selection', async () => {
  // The Data Pool's flags: the first row interacted.
  const flagged = {
    ...ROWS,
    features: ROWS.features.map((feature, i) => ({ ...feature, properties: { ...feature.properties, interacted: i === 0 ? '1' : '0' } })),
  };
  const node = mountAutkNode('kept-3', flagged);
  await node.run({ plot: { id: 'pops', dataRef: 'input_0', mark: 'bar', axis: ['pop'], selection: [2] } });
  await waitFor(() => expect(mockRuns[0].plotSelections.length).toBeGreaterThan(0));
  const selections = mockRuns[0].plotSelections;
  expect(selections[selections.length - 1]).toEqual(['pops', [0]]);
});
