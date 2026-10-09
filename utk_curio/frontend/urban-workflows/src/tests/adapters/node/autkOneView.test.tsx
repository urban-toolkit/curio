/**
 * An Autark node draws one view, a map or a plot (adapters/node/autkGrammarBehavior).
 * A document with a map and a plot, or with a list of more than one map or more
 * than one plot, fails before anything runs, with an error that names the fix:
 * the node is marked errored, so the nodes it feeds say so, and its error is
 * what Solve and the Node Builder read. A document with one map or one plot
 * runs as it always has, and a `map` or `plot` written as a list of one is that
 * view: a map's layers are counted, filtered and picked, and a plot is drawn in
 * the node's pane, checked against the tables at hand and brushed by its layer,
 * as an object's are.
 *
 * The grammar is a stand-in that records what the node hands it.
 */
import React from 'react';
import { render, act } from '@testing-library/react';

// The node reads its input edge from the flow context (hook/useGrammarInputState);
// the real provider would load the whole node registry, vega included.
const mockMarkNodeErrored = jest.fn();
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ edges: [], nodeExecStatus: {}, markNodeErrored: mockMarkNodeErrored }),
}));
const mockShowToast = jest.fn();
jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
// One upstream row, so a layer or a plot naming `input_0` resolves.
jest.mock('../../../services/api', () => ({
  fetchData: jest.fn().mockResolvedValue({
    dataType: 'geodataframe',
    data: {
      type: 'FeatureCollection',
      features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { pop: 1 } }],
    },
  }),
  fetchPreviewData: jest.fn(),
}));
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));

type Run = {
  targets: Record<string, unknown>;
  spec: any;
  /** A pick on the map, as autk-grammar reports one. */
  pick: (selection: number[]) => void;
  /** A brush on the plot, as autk-grammar reports one. */
  brush: (selection: number[]) => void;
};
/** Every run of the stand-in grammar, in order. */
const mockRuns: Run[] = [];
const mockAutkGrammar = jest.fn().mockImplementation((targets: Record<string, unknown>) => {
  const handlers: Record<string, (event: any) => void> = {};
  const grammar: any = {
    data: {},
    interactions: {
      on: (event: string, handler: (event: any) => void) => {
        handlers[event] = handler;
        return () => { delete handlers[event]; };
      },
    },
  };
  grammar.run = jest.fn(async (spec: any) => {
    mockRuns.push({
      targets,
      spec,
      pick: (selection) => handlers['map:picking']?.({ selection }),
      brush: (selection) => handlers['plot:selection']?.({ selection }),
    });
  });
  return grammar;
});
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => ({ AutkGrammar: mockAutkGrammar }),
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';
import { __resetWebGpuSupportCache } from '../../../utils/webgpuSupport';

/** What the node says of a document with more than one view. */
const ONE_VIEW =
  'An Autark node draws one view: one map or one plot. Put each in its own Autark node, '
  + 'and link them with interaction edges.';

const NODE = 'view-1';
/** The one canvas the node draws a map on. */
const CANVAS = 'autk-grammar-map-' + NODE;
/** The one pane the node draws a plot in. */
const PANE = 'autk-grammar-plot-' + NODE;
const MAP = { layerRefs: [{ dataRef: 'input_0', getFnv: 'pop' }] };
const PLOT = {
  dataRef: 'input_0', mark: 'bar', axis: ['pop', '@transform'],
  transform: { preset: 'binning-1d' }, events: ['brushX'],
};

type MountedNode = {
  /** Run *spec* and wait for the run to end. */
  run: (spec: object) => Promise<void>;
  lastOutput: () => any;
  /** What the node tells the nodes it is linked to. */
  interactions: jest.Mock;
};

function mountNode(): MountedNode {
  let apply: (spec: string) => Promise<void> = async () => { };
  const setOutput = jest.fn();
  const interactions = jest.fn();
  const Probe: React.FC = () => {
    const behavior = useAutkGrammarBehavior(
      {
        nodeId: NODE,
        input: { path: 'art-1', dataType: 'geodataframe' },
        defaultCode: '{}',
        interactionsCallback: interactions,
      } as any,
      {
        output: { code: '', content: '' },
        setOutput,
        setCode: jest.fn(),
        templateData: {},
      } as any,
    );
    apply = behavior.applyGrammar as (spec: string) => Promise<void>;
    return <>{behavior.contentComponent}</>;
  };
  render(<Probe />);
  return {
    run: async (spec) => {
      await act(async () => { await apply(JSON.stringify(spec)); });
    },
    lastOutput: () => setOutput.mock.calls[setOutput.mock.calls.length - 1]?.[0],
    interactions,
  };
}

/** Run *spec* and expect it refused: nothing ran, and the node failed with the fix. */
async function expectRefused(spec: object): Promise<void> {
  const node = mountNode();

  await node.run(spec);

  expect(node.lastOutput()).toEqual({ code: 'error', content: ONE_VIEW });
  expect(mockAutkGrammar).not.toHaveBeenCalled();
  // The nodes it feeds say it failed, and the person running it is told.
  expect(mockMarkNodeErrored).toHaveBeenCalledWith(NODE);
  expect(mockShowToast).toHaveBeenCalledWith(ONE_VIEW, 'error');
}

beforeEach(() => {
  mockRuns.length = 0;
  mockAutkGrammar.mockClear();
  mockMarkNodeErrored.mockClear();
  mockShowToast.mockClear();
  __resetWebGpuSupportCache();
  Object.defineProperty(navigator, 'gpu', {
    configurable: true,
    value: {
      requestAdapter: jest.fn().mockResolvedValue({ name: 'fake' }),
      getPreferredCanvasFormat: () => 'bgra8unorm',
    },
  });
});

afterEach(() => {
  __resetWebGpuSupportCache();
  Object.defineProperty(navigator, 'gpu', { configurable: true, value: undefined });
});

test.each([2, 3])('a document with %i maps fails before anything runs, and its error names the fix', async (count) => {
  await expectRefused({ map: Array.from({ length: count }, () => MAP) });
});

test.each([2, 3])('a document with %i plots fails before anything runs, and its error names the fix', async (count) => {
  await expectRefused({ plot: Array.from({ length: count }, () => PLOT) });
});

test.each([
  ['a map and a plot', { map: MAP, plot: PLOT }],
  ['a list of one map and a plot', { map: [MAP], plot: PLOT }],
  ['a map and a list of one plot', { map: MAP, plot: [PLOT] }],
])('a document with %s fails before anything runs, and its error names the fix', async (_, spec) => {
  await expectRefused(spec);
});

test('a document with one map runs as before', async () => {
  const node = mountNode();

  await node.run({ map: MAP });

  expect(mockRuns).toHaveLength(1);
  expect(mockRuns[0].targets).toEqual({ map: CANVAS });
  expect(mockRuns[0].spec.map).toEqual(MAP);
  expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
  expect(mockMarkNodeErrored).not.toHaveBeenCalled();
});

test('a document with one plot runs as before', async () => {
  const node = mountNode();

  await node.run({ plot: PLOT });

  expect(mockRuns).toHaveLength(1);
  expect(mockRuns[0].targets).toEqual({ plot: PANE });
  expect(mockRuns[0].spec.plot).toEqual(PLOT);
  expect(node.lastOutput()).toEqual({ code: 'success', content: '' });
  expect(mockMarkNodeErrored).not.toHaveBeenCalled();
});

test('a list of one map is that map: its layers are counted, filtered and picked', async () => {
  const node = mountNode();
  const picked = { dataRef: 'input_0', isPick: true };

  await node.run({ map: [{ layerRefs: [picked, { dataRef: 'parks' }] }] });

  // Drawn as one map on the node's canvas, less the layer that names a table
  // the dataflow does not produce, which the run's note names.
  expect(mockRuns).toHaveLength(1);
  expect(mockRuns[0].targets).toEqual({ map: CANVAS });
  expect(mockRuns[0].spec.map).toEqual({ layerRefs: [picked] });
  expect(node.lastOutput()).toEqual({ code: 'success', content: expect.stringMatching(/^drew 1 of 2 layers: /) });

  // A pick on it names the layer it came from.
  mockRuns[0].pick([0]);
  expect(node.interactions).toHaveBeenCalledWith(
    { autk_selection: expect.objectContaining({ layerRef: 'input_0' }) },
    NODE,
  );
});

test("a list of one plot is that plot: drawn in the node's pane, and its brush names its layer", async () => {
  const node = mountNode();

  await node.run({ plot: [PLOT] });

  expect(mockRuns).toHaveLength(1);
  expect(mockRuns[0].targets).toEqual({ plot: PANE });
  expect(mockRuns[0].spec.plot).toEqual(PLOT);
  expect(node.lastOutput()).toEqual({ code: 'success', content: '' });

  // A brush on it names the layer it came from.
  mockRuns[0].brush([0]);
  expect(node.interactions).toHaveBeenCalledWith(
    { autk_selection: expect.objectContaining({ layerRef: 'input_0' }) },
    NODE,
  );
});

test('a list of one plot that names a table the dataflow does not produce is reported, not drawn', async () => {
  const node = mountNode();

  await node.run({ plot: [{ ...PLOT, dataRef: 'parks' }] });

  expect(mockAutkGrammar).not.toHaveBeenCalled();
  expect(node.lastOutput()).toMatchObject({
    code: 'error',
    content: expect.stringContaining('(asked for: parks; available: input_0)'),
  });
});
