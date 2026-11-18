/**
 * An Autark node of several views sends one select per view, as a Vega-Lite
 * chart sends one per param (adapters/node/autkGrammarBehavior,
 * utils/autkSelects): a view with an `id` under `autk_selection@<id>`, one
 * without under `autk_selection@<place>`, its place among the node's views,
 * maps first. Each pick or brush sends every view's select the node holds,
 * oldest first, the one made now at priority 1, and a draw empties each that
 * held a selection. A node of one view sends `autk_selection`, as before.
 *
 * The grammar is the stand-in of _support/autkNodeMocks.
 */
import { act } from '@testing-library/react';

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

import { NodeType, VisInteractionType } from '../../../constants';
import { grammarRuns as mockRuns, resetAutkNodeMocks } from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu, type MountedAutkNode } from '../../_support/autkNode';

const NODE = 'selects-1';
/** A map with an id and a plot without one, of one table. */
const TWO_VIEWS = {
  map: { id: 'city', layerRefs: [{ dataRef: 'input_0', isPick: true }] },
  plot: { dataRef: 'input_0', mark: 'bar', axis: ['pop'], events: ['brushX'] },
};
const ROWS = {
  type: 'FeatureCollection',
  features: [0, 1, 2].map((n) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [n, 0] }, properties: { pop: n } })),
};

/** What the node sent last. */
const lastSent = (node: MountedAutkNode) => node.interactions.mock.calls[node.interactions.mock.calls.length - 1]?.[0];

const select = (data: unknown[], priority: number) => ({
  type: data.length > 0 ? VisInteractionType.POINT : VisInteractionType.UNDETERMINED,
  data,
  priority,
  source: NodeType.AUTK_GRAMMAR,
  layerRef: 'input_0',
});

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
});

afterEach(unstubWebGpu);

async function drawn(): Promise<MountedAutkNode> {
  const node = mountAutkNode(NODE, ROWS);
  await node.run(TWO_VIEWS);
  expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
  return node;
}

test("a pick on a view with an id is sent under that view's key, at priority 1", async () => {
  const node = await drawn();

  act(() => mockRuns[0].pickOn('city', 'input_0', [2]));

  expect(lastSent(node)).toEqual({ 'autk_selection@city': select([2], 1) });
  expect(node.interactions).toHaveBeenLastCalledWith(expect.anything(), NODE);
});

test("a view without an id is keyed by its place, and each pick or brush sends every view's select, oldest first", async () => {
  const node = await drawn();
  act(() => mockRuns[0].pickOn('city', 'input_0', [2]));

  // The plot, the node's second view, brushes: it is known by its table.
  act(() => mockRuns[0].brushOn('input_0', [0, 1]));

  const sent = lastSent(node);
  expect(Object.keys(sent)).toEqual(['autk_selection@city', 'autk_selection@1']);
  expect(sent).toEqual({ 'autk_selection@city': select([2], 0), 'autk_selection@1': select([0, 1], 1) });

  // The map picks again: it is the newest, sent last.
  act(() => mockRuns[0].pickOn('city', 'input_0', [1]));
  expect(Object.keys(lastSent(node))).toEqual(['autk_selection@1', 'autk_selection@city']);
  expect(lastSent(node)).toEqual({ 'autk_selection@1': select([0, 1], 0), 'autk_selection@city': select([1], 1) });
});

test('a draw empties each view select that held a selection, under its own key', async () => {
  const node = await drawn();
  act(() => mockRuns[0].pickOn('city', 'input_0', [2]));
  act(() => mockRuns[0].brushOn('input_0', [0]));

  await node.run(TWO_VIEWS);

  expect(lastSent(node)).toEqual({ 'autk_selection@city': select([], 1), 'autk_selection@1': select([], 1) });
  // A select made after the draw is sent alone: the draw held none.
  act(() => mockRuns[1].brushOn('input_0', [2]));
  expect(lastSent(node)).toEqual({ 'autk_selection@1': select([2], 1) });
});

test('a node of one view sends its select under autk_selection, as before', async () => {
  const node = mountAutkNode(NODE, ROWS);
  await node.run({ map: TWO_VIEWS.map });

  act(() => mockRuns[0].pickOn('city', 'input_0', [2]));

  expect(lastSent(node)).toEqual({ autk_selection: select([2], 1) });
});
