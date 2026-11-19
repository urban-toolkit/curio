/**
 * What an Autark node of several views does with the selections its
 * interaction edges deliver (adapters/node/autkGrammarBehavior,
 * `syncHighlights`). A delivery on the node's own dot reaches every view, as
 * before: each view lights the rows it draws of the table the selection names.
 * A delivery on a view's dot names the view (`toView`) and reaches that view
 * alone, which then acts as if the selection were made in it: the grammar's
 * call for that view carries it on to the views the node's `links` join it to.
 * So the node calls the grammar only for the views whose rows changed, every
 * clear before any light, so no clear of one view undoes what another view's
 * call carried on to it. A node of one view takes a delivery on any of its
 * dots as its own.
 *
 * The grammar is the stand-in of _support/autkNodeMocks, which records each
 * call in order (`calls`); it draws no links, so these hold Curio's side of
 * them, and the e2e test (test_autark_view_edges_e2e.py) the grammar's.
 */
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class { } }));
jest.mock('@urban-toolkit/autk-grammar', () => require('../../_support/autkNodeMocks').autkGrammarModule, { virtual: true });
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

import { act, waitFor } from '@testing-library/react';
import { grammarRuns, resetAutkNodeMocks, type GrammarRun } from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu, type MountedAutkNode } from '../../_support/autkNode';

const NODE = 'views-1';
/** Three points, rows 0 to 2. */
const ROWS = {
  type: 'FeatureCollection',
  features: [0, 1, 2].map((n) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [n, 0] }, properties: { pop: n } })),
};
/** A map `city` and a plot `heights` of the node's input. */
const VIEWS = {
  map: { id: 'city', layerRefs: [{ dataRef: 'input_0', isPick: true }] },
  plot: { id: 'heights', dataRef: 'input_0', mark: 'bar', axis: ['pop'], events: ['brushX'] },
};
/** The same views, the plot linked to the map. */
const LINKED = { ...VIEWS, links: [{ source: 'heights', target: 'city' }] };

/** A chart's click on *row*, delivered to the node: to the view *toView*, else to every view. */
const delivered = (row: number, toView?: string) => [{
  nodeId: 'chart',
  details: { pick: { type: 'POINT', data: [row], priority: 1 } },
  priority: 1,
  ...(toView === undefined ? {} : { toView }),
}];

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
});

afterEach(unstubWebGpu);

/** A node drawn with *spec*, its first highlights after the draw done: each view cleared once. */
async function drawn(spec: object): Promise<{ node: MountedAutkNode; run: GrammarRun }> {
  const node = mountAutkNode(NODE, ROWS);
  await node.run(spec);
  expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
  const run = grammarRuns[0];
  await waitFor(() => expect(run.calls.length).toBeGreaterThan(0));
  return { node, run };
}

/** The calls *run* holds from *from* on, once the node has nothing left to ask. */
async function callsFrom(run: GrammarRun, from: number, wanted: unknown[]) {
  await waitFor(() => expect(run.calls.slice(from)).toEqual(wanted));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  expect(run.calls.slice(from)).toEqual(wanted);
}

test('guard: after a draw, each view is cleared once, every clear before any light', async () => {
  const { run } = await drawn(VIEWS);

  await callsFrom(run, 0, [['map', 'input_0', [], 0], ['plot', 'heights', []]]);
});

test("a selection delivered to a plot's dot lights that plot alone", async () => {
  const { node, run } = await drawn(VIEWS);
  const from = run.calls.length;

  await node.receive(delivered(1, 'heights'));

  await callsFrom(run, from, [['plot', 'heights', [1]]]);
});

test("a selection delivered to a map's dot lights that map alone", async () => {
  const { node, run } = await drawn(VIEWS);
  const from = run.calls.length;

  await node.receive(delivered(1, 'city'));

  await callsFrom(run, from, [['map', 'input_0', [1], 0]]);
});

test("guard: a selection delivered to the node's own dot lights every view, maps first, as an old edge did", async () => {
  const { node, run } = await drawn(VIEWS);
  const from = run.calls.length;

  await node.receive(delivered(1));

  await callsFrom(run, from, [['map', 'input_0', [1], 0], ['plot', 'heights', [1]]]);
});

test('a selection that moves from one view to another clears the first before it lights the second', async () => {
  const { node, run } = await drawn(VIEWS);
  await node.receive(delivered(1, 'heights'));
  await waitFor(() => expect(run.calls[run.calls.length - 1]).toEqual(['plot', 'heights', [1]]));
  const from = run.calls.length;

  await node.receive(delivered(2, 'city'));

  await callsFrom(run, from, [['plot', 'heights', []], ['map', 'input_0', [2], 0]]);
});

test('the same selection delivered again asks the grammar nothing', async () => {
  const { node, run } = await drawn(VIEWS);
  await node.receive(delivered(1, 'heights'));
  await waitFor(() => expect(run.calls[run.calls.length - 1]).toEqual(['plot', 'heights', [1]]));
  const from = run.calls.length;

  await node.receive(delivered(1, 'heights'));

  await callsFrom(run, from, []);
});

test('a selection delivered to a dot naming no view of the node lights nothing', async () => {
  const { node, run } = await drawn(VIEWS);
  const from = run.calls.length;

  await node.receive(delivered(1, 'parks'));

  await callsFrom(run, from, []);
});

test('guard: a node of one view takes a selection delivered on any of its dots as its own', async () => {
  const { node, run } = await drawn({ map: VIEWS.map });
  const from = run.calls.length;

  await node.receive(delivered(1, 'elsewhere'));

  await callsFrom(run, from, [['map', 'input_0', [1], 0]]);
});

// The grammar carries a selection set on a plot to the map layers its links
// join it to (autk-grammar's setPlotSelection), and a clear of the map to the
// plots linked to it: so the map, lit no more by the node itself, is cleared
// first, and the plot's selection is the last call, which its link carries on.
test("a selection a plot receives is carried on by the node's links: the plot's call comes after the map's clear", async () => {
  const { node, run } = await drawn(LINKED);
  await node.receive(delivered(1));
  await waitFor(() => expect(run.calls.slice(-2)).toEqual([['map', 'input_0', [1], 0], ['plot', 'heights', [1]]]));
  const from = run.calls.length;

  await node.receive(delivered(2, 'heights'));

  await callsFrom(run, from, [['map', 'input_0', [], 0], ['plot', 'heights', [2]]]);
});

// autk-map lights a pick on the map that made it, and the grammar's links
// carry it on: after a pick of the node's own, a selection it receives is
// lit again, though it lights what it lit before, as every selection was.
test("guard: after a pick of the node's own, the same selection delivered again lights the map again", async () => {
  const { node, run } = await drawn({ map: VIEWS.map });
  await node.receive(delivered(2));
  await waitFor(() => expect(run.calls[run.calls.length - 1]).toEqual(['map', 'input_0', [2], 0]));

  act(() => run.pickOn('city', 'input_0', [0]));
  const from = run.calls.length;
  await node.receive(delivered(2));

  await callsFrom(run, from, [['map', 'input_0', [2], 0]]);
});

test('a draw starts the views over: the next selection lights each view it reaches again', async () => {
  const { node, run } = await drawn(VIEWS);
  await node.receive(delivered(1, 'heights'));
  await waitFor(() => expect(run.calls[run.calls.length - 1]).toEqual(['plot', 'heights', [1]]));

  await node.run(VIEWS);
  const again = grammarRuns[1];

  // The new draw lights the delivery it holds on the view it names, and clears the other.
  await callsFrom(again, 0, [['map', 'input_0', [], 0], ['plot', 'heights', [1]]]);
});
