/**
 * A map layer that names a scenario (`"scenario": "<its id>"`, Curio's own key)
 * is drawn in that scenario's color, the color of its box on the canvas, as
 * Compare Scenarios' charts draw it: the node hands the grammar the layer with
 * autk-grammar's `color` set to it (adapters/node/autkGrammarBehavior). The
 * map shows no legend for such a layer, since a layer with a `color` is not
 * colored by value.
 *
 * The grammar is a stand-in that records what the node hands it
 * (_support/autkNodeMocks), and the flow holds the scenarios.
 */

// The node reads its input edge and the scenarios from the flow context; the
// real provider would load the whole node registry, vega included.
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
  flowScenarios as mockScenarios,
  grammarRuns as mockRuns,
  resetAutkNodeMocks,
} from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';

const NODE = 'routes-map';
const FASTEST = { id: 'fastest', name: 'Fastest', color: '#e15759', nodes: ['route-fast'] };
const WEATHER = { id: 'weather-aware', name: 'Weather-aware', color: '#4e79a7', nodes: ['route-weather'] };

/** The layers the grammar was handed on its last run. */
const drawnLayers = () => mockRuns[mockRuns.length - 1].spec.map.layerRefs;

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
  mockScenarios.current = [FASTEST, WEATHER];
});

afterEach(unstubWebGpu);

test("repro: a layer that names a scenario is drawn in its box's color", async () => {
  const node = mountAutkNode(NODE);

  await node.run({ map: { layerRefs: [{ dataRef: 'input_0', scenario: 'weather-aware', width: 30 }] } });

  expect(mockRuns).toHaveLength(1);
  expect(drawnLayers()).toEqual([{ dataRef: 'input_0', scenario: 'weather-aware', width: 30, color: '#4e79a7' }]);
  expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
});

test("repro: after the box's color changes, the next run draws the layer in the new color", async () => {
  const node = mountAutkNode(NODE);
  await node.run({ map: { layerRefs: [{ dataRef: 'input_0', scenario: 'fastest' }] } });
  expect(drawnLayers()[0].color).toBe('#e15759');

  // The flow holds the new color, and its nodes render again with it.
  mockScenarios.current = [{ ...FASTEST, color: '#59a14f' }, WEATHER];
  node.rerender();
  await node.run({ map: { layerRefs: [{ dataRef: 'input_0', scenario: 'fastest' }] } });

  expect(mockRuns).toHaveLength(2);
  expect(drawnLayers()[0].color).toBe('#59a14f');
});

test("repro: the scenario's color is the layer's, over a color the layer writes", async () => {
  const node = mountAutkNode(NODE);

  await node.run({ map: [{ layerRefs: [{ dataRef: 'input_0', scenario: 'fastest', color: '#000000' }] }] });

  // A list of one map is that map.
  const map = mockRuns[0].spec.map;
  const layers = Array.isArray(map) ? map[0].layerRefs : map.layerRefs;
  expect(layers[0].color).toBe('#e15759');
});

test('guard: a layer that names no scenario, or one the dataflow does not have, is handed on as written', async () => {
  const node = mountAutkNode(NODE);

  await node.run({ map: { layerRefs: [{ dataRef: 'input_0', scenario: 'gone', getFnv: 'pop' }] } });
  expect(drawnLayers()).toEqual([{ dataRef: 'input_0', scenario: 'gone', getFnv: 'pop' }]);

  await node.run({ map: { layerRefs: [{ dataRef: 'input_0', color: '#123456' }] } });
  expect(drawnLayers()).toEqual([{ dataRef: 'input_0', color: '#123456' }]);
});
