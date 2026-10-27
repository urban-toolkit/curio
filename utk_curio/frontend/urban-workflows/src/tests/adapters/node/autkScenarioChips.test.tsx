/**
 * A map draws its scenarios through chips (#662). A layer writes
 * `"color": "[!! scenario input_1 !!]"`, which the node's editor resolves
 * before the run, as it resolves every chip, to the color of the box input_1
 * comes from (components/editing/NodeEditor). The map draws exactly the layers
 * it is handed: a layer whose input comes from a box but that writes no chip
 * draws as it is written. A box recolored is drawn so at the map's next run,
 * whose chips are resolved again.
 *
 * The grammar is a stand-in that records what the node hands it
 * (_support/autkNodeMocks). The routing example's map is read from its shipped
 * dataflow, its chips resolved over that dataflow's boxes as the editor's scope
 * labels its inputs.
 */

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

import * as fs from 'fs';
import * as path from 'path';
import { REPO_ROOT } from '../../_support/workflowPaths';
import {
  flowEdges as mockEdges,
  flowNodes as mockNodes,
  flowScenarios as mockScenarios,
  grammarRuns as mockRuns,
  resetAutkNodeMocks,
} from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import { resolveReferences, type InputScope } from '../../../utils/references/codeReferences';
import { inputScenarios } from '../../../utils/scenarios/inputScenarios';
import { normalizeScenarios } from '../../../utils/scenarios/scenarioModel';

const ROUTING = path.join(REPO_ROOT, 'docs', 'examples', 'dataflows', 'chicago-rain-wind-routing.json');
const MAP = '6c0e8a4d-3b9f-4d21-a7e5-9f2b6d1c8e40';
const FLOW = JSON.parse(fs.readFileSync(ROUTING, 'utf-8')).dataflow;
const NODES = FLOW.nodes.map((node: any) => ({
  id: node.id,
  type: '__curioUniversalNode',
  data: { nodeId: node.id, nodeType: node.type, title: node.title },
}));
const EDGES = FLOW.edges.filter((edge: any) => edge.type !== 'Interaction');
const DOCUMENT: string = FLOW.nodes.find((node: any) => node.id === MAP).content;

/** The map's three circles: the roads, then each scenario's route. */
const INPUT = {
  dataType: 'outputs',
  data: [
    { path: 'art-roads', dataType: 'geodataframe' },
    { path: 'art-fast', dataType: 'geodataframe' },
    { path: 'art-weather', dataType: 'geodataframe' },
  ],
};

/** The map's document as the editor writes it over *scenarios*: each circle labelled by the box its node is in. */
function written(scenarios: unknown): any {
  const listed = normalizeScenarios(scenarios, FLOW.nodes.map((node: any) => node.id));
  const inputs: InputScope[] = inputScenarios(MAP, NODES, EDGES, listed).map((input) => ({
    slot: input.slot,
    dataType: 'geodataframe',
    scenario: input.scenario
      ? { ...input.label, rank: listed.findIndex((scenario) => scenario.id === input.scenario!.id) }
      : input.label,
  }));
  const { code, problems } = resolveReferences(DOCUMENT, { widgets: [], inputs }, 'json');
  expect(problems).toEqual([]);
  return JSON.parse(code);
}

/** The layers the grammar was handed on its last run. */
const drawnLayers = () => {
  const map = mockRuns[mockRuns.length - 1].spec.map;
  return (Array.isArray(map) ? map[0] : map).layerRefs;
};

beforeEach(() => {
  resetAutkNodeMocks();
  stubWebGpu();
  // The flow the map sits in: the routing example's boxes, nodes and edges.
  mockScenarios.current = FLOW.scenarios;
  mockNodes.current = NODES;
  mockEdges.current = EDGES;
});

afterEach(unstubWebGpu);

test("the routing map's routes write their inputs' scenario chips, and draw in their boxes' colors", async () => {
  const layers = JSON.parse(DOCUMENT).map.layerRefs;
  expect(layers.map((layer: any) => layer.color)).toEqual([
    undefined, '[!! scenario input_1 !!]', '[!! scenario input_2 !!]',
  ]);

  const map = mountAutkNode(MAP, undefined, { input: INPUT });
  await map.run(written(FLOW.scenarios));

  expect(drawnLayers()).toEqual([
    { dataRef: 'input_0', title: 'Roads' },
    { dataRef: 'input_1', width: 80, title: 'Fastest route', color: '#42A5F5' },
    { dataRef: 'input_2', width: 40, title: 'Weather-aware route', color: '#00838F' },
  ]);
  expect(map.lastOutput()).toEqual({ code: 'success', content: '' });
});

test("a layer whose input comes from a box draws as it is written: no chip, no box color", async () => {
  const map = mountAutkNode(MAP, undefined, { input: INPUT });
  const routes = [
    { dataRef: 'input_0', title: 'Roads' },
    { dataRef: 'input_1', width: 80, title: 'Fastest route' },
    { dataRef: 'input_2', width: 40, title: 'Weather-aware route', color: '#123456' },
  ];

  await map.run({ map: { layerRefs: routes } });

  expect(drawnLayers()).toEqual(routes);
});

test("after a box is recolored, the map's next run draws its route in the new color, through its chip", async () => {
  const map = mountAutkNode(MAP, undefined, { input: INPUT });
  await map.run(written(FLOW.scenarios));
  expect(drawnLayers()[1].color).toBe('#42A5F5');

  const recolored = FLOW.scenarios.map((scenario: any) =>
    scenario.id === 'fastest' ? { ...scenario, color: '#d81b60' } : scenario);
  mockScenarios.current = recolored;
  map.rerender();
  // Nothing is drawn until the map runs again.
  expect(mockRuns).toHaveLength(1);
  // The run's document writes the new color itself: the chip, not the map, colors the route.
  const document = written(recolored);
  expect(document.map.layerRefs.map((layer: any) => layer.color)).toEqual([undefined, '#d81b60', '#00838F']);
  await map.run(document);

  expect(mockRuns).toHaveLength(2);
  expect(drawnLayers().map((layer: any) => layer.color)).toEqual([undefined, '#d81b60', '#00838F']);
});
