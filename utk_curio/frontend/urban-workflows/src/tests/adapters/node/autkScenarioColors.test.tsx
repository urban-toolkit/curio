/**
 * A map layer drawn in its scenario's color (#662): on a map outside every
 * scenario box, a layer whose input comes from a node in a box is drawn in that
 * box's color, the color of the box on the canvas, as a Vega-Lite chart reading
 * `inputs` draws its rows. The node hands the grammar the layer with
 * autk-grammar's `color` set to it (adapters/node/autkGrammarBehavior), so the
 * map shows no legend for it. A map inside a box draws its layers as written,
 * and so does a layer whose input comes from no box.
 *
 * The grammar is a stand-in that records what the node hands it
 * (_support/autkNodeMocks), and the flow holds the boxes, the nodes and the
 * edges: the roads' loader in no box, each route's node in its own box.
 */

// The node reads its input edges, the nodes and the scenarios from the flow
// context; the real provider would load the whole node registry, vega included.
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

import {
  ONE_ROW,
  flowEdges as mockEdges,
  flowNodes as mockNodes,
  flowScenarios as mockScenarios,
  grammarRuns as mockRuns,
  inputsByPath as mockInputsByPath,
  resetAutkNodeMocks,
} from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';

const NODE = 'routes-map';
const FASTEST = { id: 'fastest', name: 'Fastest', color: '#e15759', nodes: ['route-fast'] };
const WEATHER = { id: 'weather-aware', name: 'Weather-aware', color: '#4e79a7', nodes: ['route-weather'] };

const node = (id: string, nodeType = 'curio.builtin/computation-analysis@1') => ({
  id,
  type: '__curioUniversalNode',
  data: { nodeId: id, nodeType },
});
const edge = (source: string, targetHandle: string) => ({
  id: `${source}->${NODE}:${targetHandle}`,
  source,
  target: NODE,
  sourceHandle: 'out',
  targetHandle,
});

/** The map's three circles: the roads, then each scenario's route. */
const INPUT = {
  dataType: 'outputs',
  data: [
    { path: 'art-roads', dataType: 'geodataframe' },
    { path: 'art-fast', dataType: 'geodataframe' },
    { path: 'art-weather', dataType: 'geodataframe' },
  ],
};

/** The routes over the roads, as the routing example draws them. */
const ROUTES = [
  { dataRef: 'input_0', title: 'Roads' },
  { dataRef: 'input_1', width: 80, title: 'Fastest route' },
  { dataRef: 'input_2', width: 40, title: 'Weather-aware route' },
];

/** The layers the grammar was handed on its last run. */
const drawnLayers = () => {
  const map = mockRuns[mockRuns.length - 1].spec.map;
  return (Array.isArray(map) ? map[0] : map).layerRefs;
};

const mountMap = (options?: { colorsByScenario?: boolean }) => mountAutkNode(NODE, undefined, { input: INPUT, options });

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
  mockScenarios.current = [FASTEST, WEATHER];
  mockNodes.current = [node('roads'), node('route-fast'), node('route-weather'), node(NODE, 'curio.builtin/autk-grammar@1')];
  mockEdges.current = [edge('roads', 'in'), edge('route-fast', 'in_1'), edge('route-weather', 'in_2')];
});

afterEach(unstubWebGpu);

test("a layer whose input comes from a box is drawn in the box's color, one from no box as written", async () => {
  const map = mountMap();

  await map.run({ map: { layerRefs: ROUTES } });

  expect(mockRuns).toHaveLength(1);
  expect(drawnLayers()).toEqual([
    { dataRef: 'input_0', title: 'Roads' },
    { dataRef: 'input_1', width: 80, title: 'Fastest route', color: '#e15759' },
    { dataRef: 'input_2', width: 40, title: 'Weather-aware route', color: '#4e79a7' },
  ]);
  expect(map.lastOutput()).toEqual({ code: 'success', content: '' });
});

test("after the box's color changes, the next run draws the layer in the new color", async () => {
  const map = mountMap();
  await map.run({ map: { layerRefs: ROUTES } });
  expect(drawnLayers()[1].color).toBe('#e15759');

  // The flow holds the new color, and its nodes render again with it.
  mockScenarios.current = [{ ...FASTEST, color: '#59a14f' }, WEATHER];
  map.rerender();
  await map.run({ map: { layerRefs: ROUTES } });

  expect(mockRuns).toHaveLength(2);
  expect(drawnLayers()[1].color).toBe('#59a14f');
  expect(drawnLayers()[2].color).toBe('#4e79a7');
});

test("the box's color is the layer's, over a color the layer writes", async () => {
  const map = mountMap();

  await map.run({ map: [{ layerRefs: [{ dataRef: 'input_1', color: '#000000' }] }] });

  // A list of one map is that map.
  expect(drawnLayers()[0].color).toBe('#e15759');
});

test('a layer named by its own name takes the color of the box its input comes from', async () => {
  // The fastest route's node hands on a layer it names.
  mockInputsByPath.current = { 'art-fast': { dataType: 'geodataframe', data: ONE_ROW, layerName: 'fast_route' } };
  const map = mountMap();

  await map.run({ map: { layerRefs: [{ dataRef: 'input_0' }, { dataRef: 'fast_route' }] } });

  expect(drawnLayers()).toEqual([{ dataRef: 'input_0' }, { dataRef: 'fast_route', color: '#e15759' }]);
});

test('guard: a map inside a box draws its layers as written; moved out of it, in the boxes\' colors', async () => {
  mockScenarios.current = [{ ...FASTEST, nodes: ['route-fast', NODE] }, WEATHER];
  const map = mountMap();
  await map.run({ map: { layerRefs: ROUTES } });
  expect(drawnLayers()).toEqual(ROUTES);

  mockScenarios.current = [FASTEST, WEATHER];
  map.rerender();
  await map.run({ map: { layerRefs: ROUTES } });
  expect(drawnLayers().map((layer: any) => layer.color)).toEqual([undefined, '#e15759', '#4e79a7']);
});

test("guard: a layer's own scenario key is not read; the box its input comes from is", async () => {
  const map = mountMap();

  // input_0 comes from the roads' loader, in no box.
  await map.run({ map: { layerRefs: [{ dataRef: 'input_0', scenario: 'fastest', getFnv: 'pop' }] } });
  expect(drawnLayers()).toEqual([{ dataRef: 'input_0', scenario: 'fastest', getFnv: 'pop' }]);

  await map.run({ map: { layerRefs: [{ dataRef: 'input_2', color: '#123456' }] } });
  expect(drawnLayers()).toEqual([{ dataRef: 'input_2', color: '#4e79a7' }]);
});

test("guard: the Interaction node's map draws the features it edits as written", async () => {
  const colored = mountMap();
  await colored.run({ map: { layerRefs: ROUTES } });
  expect(drawnLayers()[1].color).toBe('#e15759');

  const edits = mountMap({ colorsByScenario: false });
  await edits.run({ map: { layerRefs: ROUTES } });
  expect(drawnLayers()).toEqual(ROUTES);
});
