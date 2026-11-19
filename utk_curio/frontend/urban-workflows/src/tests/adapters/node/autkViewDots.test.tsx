/**
 * The dots of an Autark node of several views (adapters/node/autkGrammarBehavior,
 * `dynamicHandles`): beside the node's own interaction dot, one dot per view
 * that has an `id`, along the top edge, in the order of its panes (maps
 * first, as autk-grammar's `arrangeViews` places them), each named
 * `in/out@<id>`. They come from the document as written, so an edge saved on
 * a view's dot finds its dot before the node runs. A node of one view has only
 * its own dot, as before. A dot an edge still names stays while the edge does,
 * though its view left the document, so the edge can be seen and taken off.
 *
 * The grammar is the stand-in of _support/autkNodeMocks.
 */
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({ JavaScriptInterpreter: class { } }));
jest.mock('@urban-toolkit/autk-grammar', () => require('../../_support/autkNodeMocks').autkGrammarModule, { virtual: true });
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

import { flowEdges, resetAutkNodeMocks } from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import { viewDotLeft } from '../../../adapters/node/handleHelpers';

const NODE = 'views-1';
const LAYER = { dataRef: 'input_0', isPick: true };
const PLOT = { dataRef: 'input_0', mark: 'bar', axis: ['pop'], events: ['brushX'] };
/** A plot written before two maps: the maps' panes come first all the same. */
const SEVERAL = { plot: { id: 'heights', ...PLOT }, map: [{ id: 'north', layerRefs: [LAYER] }, { id: 'south', layerRefs: [LAYER] }] };

/** Each dot the node adds: its handle, its kind, its side, what its tooltip says and the view it rings. */
const dots = (node: ReturnType<typeof mountAutkNode>) =>
  (node.dynamicHandles() ?? []).map((h) => [h.id, h.type, h.position, h.tooltip, h.view]);

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
});

afterEach(unstubWebGpu);

test('a node of several views shows a dot per view with an id, maps first, before it runs', () => {
  const node = mountAutkNode(NODE, undefined, { code: JSON.stringify(SEVERAL) });

  expect(dots(node)).toEqual([
    ['in/out@north', 'source', 'top', 'interaction · north', 'north'],
    ['in/out@south', 'source', 'top', 'interaction · south', 'south'],
    ['in/out@heights', 'source', 'top', 'interaction · heights', 'heights'],
  ]);
});

test('each dot sits right of the node own dot, in pane order, closing up so all stay on the top edge', () => {
  const node = mountAutkNode(NODE, undefined, { code: JSON.stringify(SEVERAL) });

  expect((node.dynamicHandles() ?? []).map((h) => h.style)).toEqual([
    { left: viewDotLeft(0, 3) },
    { left: viewDotLeft(1, 3) },
    { left: viewDotLeft(2, 3) },
  ]);
  // A fixed step right of the middle, smaller when the dots would pass the corner.
  expect(viewDotLeft(0, 3)).toBe('calc(50% + 1 * min(28px, (50% - 24px) / 3))');
  expect(viewDotLeft(2, 3)).toBe('calc(50% + 3 * min(28px, (50% - 24px) / 3))');
});

test('a view without an id gets no dot', () => {
  const node = mountAutkNode(NODE, undefined, {
    code: JSON.stringify({ map: { layerRefs: [LAYER] }, plot: { id: 'heights', ...PLOT } }),
  });

  expect(dots(node)).toEqual([['in/out@heights', 'source', 'top', 'interaction · heights', 'heights']]);
});

test('a node of one view shows only its own dot, its view with an id or not', () => {
  for (const spec of [{ map: { id: 'city', layerRefs: [LAYER] } }, { plot: PLOT }, { map: [{ id: 'city', layerRefs: [LAYER] }] }]) {
    const node = mountAutkNode(NODE, undefined, { code: JSON.stringify(spec) });
    expect(dots(node)).toEqual([]);
    node.unmount();
  }
});

test('the dots follow the document as it is written, and a document that does not read yet keeps the dots it had', () => {
  const node = mountAutkNode(NODE, undefined, { code: JSON.stringify(SEVERAL) });

  node.write(JSON.stringify({ ...SEVERAL, plot: { id: 'counts', ...PLOT } }));
  expect(dots(node).map(([id]) => id)).toEqual(['in/out@north', 'in/out@south', 'in/out@counts']);

  // Halfway through typing: the dots stay as they were.
  node.write('{ "map": [{ "id": "north", ');
  expect(dots(node).map(([id]) => id)).toEqual(['in/out@north', 'in/out@south', 'in/out@counts']);
});

test("a chip in the document is read as its place holder, so the dots still come", () => {
  const node = mountAutkNode(NODE, undefined, {
    code: '{"map": [{"id": "north", "layerRefs": [{"dataRef": [!! input_0 !!]}]}, {"id": "south", "layerRefs": []}]}',
  });

  expect(dots(node).map(([id]) => id)).toEqual(['in/out@north', 'in/out@south']);
});

test('a dot an edge still names stays after its view leaves the document, saying so, after the views it has', () => {
  flowEdges.current = [
    { id: 'gone', source: 'chart', target: NODE, sourceHandle: 'in/out', targetHandle: 'in/out@gone', type: 'Interaction' },
    { id: 'north', source: NODE, target: 'chart', sourceHandle: 'in/out@north', targetHandle: 'in/out', type: 'Interaction' },
    { id: 'other', source: 'chart', target: 'other', sourceHandle: 'in/out', targetHandle: 'in/out@else', type: 'Interaction' },
  ];
  const node = mountAutkNode(NODE, undefined, { code: JSON.stringify(SEVERAL) });

  expect(dots(node)).toEqual([
    ['in/out@north', 'source', 'top', 'interaction · north', 'north'],
    ['in/out@south', 'source', 'top', 'interaction · south', 'south'],
    ['in/out@heights', 'source', 'top', 'interaction · heights', 'heights'],
    ['in/out@gone', 'source', 'top', 'interaction · gone (no view of this node has this id)', 'gone'],
  ]);

  // On a node of one view, the dot its edge names alone.
  const one = mountAutkNode('views-2', undefined, { code: JSON.stringify({ map: { id: 'city', layerRefs: [LAYER] } }) });
  flowEdges.current = [
    { id: 'city', source: 'chart', target: 'views-2', sourceHandle: 'in/out', targetHandle: 'in/out@city', type: 'Interaction' },
  ];
  one.rerender();
  expect(dots(one)).toEqual([['in/out@city', 'source', 'top', 'interaction · city', 'city']]);
});
