/**
 * An Autark node draws one map (adapters/node/autkGrammarBehavior). A document
 * whose `map` lists more than one map fails before anything runs, with an error
 * that names the fix: the node is marked errored, so the nodes it feeds say so,
 * and its error is what Solve and the Node Builder read. A document with one map
 * runs as it always has, and a `map` written as a list of one map is that map:
 * its layers are counted, filtered and picked as an object map's are.
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
// One upstream row, so a layer naming `input_0` resolves.
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
    mockRuns.push({ targets, spec, pick: (selection) => handlers['map:picking']?.({ selection }) });
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

/** What the node says of a document with more than one map. */
const ONE_MAP =
  'An Autark node draws one map. Put each map in its own Autark node, and link them with interaction edges.';

const NODE = 'map-1';
/** The one canvas the node draws its map on. */
const CANVAS = 'autk-grammar-map-' + NODE;
const MAP = { layerRefs: [{ dataRef: 'input_0', getFnv: 'pop' }] };

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
  const node = mountNode();

  await node.run({ map: Array.from({ length: count }, () => MAP) });

  expect(node.lastOutput()).toEqual({ code: 'error', content: ONE_MAP });
  expect(mockAutkGrammar).not.toHaveBeenCalled();
  // The nodes it feeds say it failed, and the person running it is told.
  expect(mockMarkNodeErrored).toHaveBeenCalledWith(NODE);
  expect(mockShowToast).toHaveBeenCalledWith(ONE_MAP, 'error');
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
