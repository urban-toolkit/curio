/**
 * An Autark node that leaves the page while its run is under way (File > New
 * dataflow, a deleted node) takes its map canvas with it, and its run is
 * dropped (adapters/node/autkGrammarBehavior). It makes no grammar once the
 * node is gone, and nothing it says reaches the page: no toast, no error, no
 * rows handed on. That holds even when autk-grammar's run, already under way,
 * then finds no canvas for its map. A map still on the page that finds no
 * canvas still says so.
 *
 * The grammar is a stand-in that runs as autk-grammar 4.4.0 does. It loads its
 * data first (held while a test says so). Then its map adapter (`resolveMap`)
 * looks the map's canvas up by id and throws autk-grammar's own words when
 * there is none. Then the map draws (held while a test says so).
 */
import React from 'react';
import { act, render } from '@testing-library/react';

// The node reads its input edge from the flow context (hook/useGrammarInputState);
// the real provider would load the whole node registry, vega included.
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));

/** While set, a run waits for it before its map looks for its canvas: autk-grammar loads the data first. */
let mockDataLoad: Promise<void> | null = null;
/** While set, a run waits for it once its map has found its canvas: the map draws. */
let mockDraw: Promise<void> | null = null;
/** How many runs began loading their data. */
let mockRunsStarted = 0;
/** Every canvas a run's map looked for, and whether it was there. */
const mockLookups: Array<{ id: string; found: boolean }> = [];

const mockAutkGrammar = jest.fn().mockImplementation((targets: Record<string, string>) => ({
  data: {},
  run: jest.fn(async () => {
    mockRunsStarted += 1;
    if (mockDataLoad) await mockDataLoad;
    // autk-grammar's map adapter (adapters/autk/src/adapters/map.ts, resolveMap).
    const canvas = document.getElementById(targets.map);
    mockLookups.push({ id: targets.map, found: canvas != null });
    if (!canvas) throw new Error('Could not find rendering target for map: ' + targets.map);
    if (mockDraw) await mockDraw;
  }),
}));
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => ({ AutkGrammar: mockAutkGrammar }),
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';
import {
  ONE_ROW,
  apiModule as mockApi,
  markNodeErrored as mockMarkNodeErrored,
  resetAutkNodeMocks,
  showToast as mockShowToast,
} from '../../_support/autkNodeMocks';
import { stubWebGpu, unstubWebGpu } from '../../_support/autkNode';

const NODE = 'map-1';
/** The canvas the node draws its map on. */
const CANVAS = 'autk-grammar-map-' + NODE;
/** What autk-grammar says when a map's canvas is not on the page. */
const NO_TARGET = 'Could not find rendering target for map: ' + CANVAS;
const MAP = JSON.stringify({ map: { layerRefs: [{ dataRef: 'input_0' }] } });

type MountedNode = {
  /** Start a run of the node's map, and return it. */
  start: () => Promise<void>;
  unmount: () => void;
  /** Every output the node was given, in order. */
  outputs: () => any[];
  /** What the node handed to the nodes it feeds. */
  handedOn: jest.Mock;
};

function mountNode(): MountedNode {
  let apply: (spec: string) => Promise<void> = async () => { };
  const setOutput = jest.fn();
  const handedOn = jest.fn();
  const input = { path: 'art-1', dataType: 'geodataframe' };
  const Probe: React.FC = () => {
    const behavior = useAutkGrammarBehavior(
      { nodeId: NODE, input, defaultCode: '{}', outputCallback: handedOn } as any,
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
  const { unmount } = render(<Probe />);
  return {
    start: () => apply(MAP),
    unmount,
    outputs: () => setOutput.mock.calls.map(([output]) => output),
    handedOn,
  };
}

/** Something a test holds the run at, until it releases it. */
function held(): { promise: Promise<void>; release: () => void } {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => { release = resolve; });
  return { promise, release };
}

/** Let the page run until *reached* holds. */
async function until(reached: () => boolean): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 200 && !reached(); i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
  });
  expect(reached()).toBe(true);
}

/**
 * Start a run of *node*'s map. The run comes back still under way, wrapped,
 * since an async function would wait for it.
 */
async function startRun(node: MountedNode): Promise<{ running: Promise<void> }> {
  let running!: Promise<void>;
  await act(async () => { running = node.start(); });
  return { running };
}

/** Let the held step go on, and wait for the run to end. */
async function finish(step: { release: () => void }, { running }: { running: Promise<void> }): Promise<void> {
  await act(async () => {
    step.release();
    await running;
  });
}

/** The page heard nothing from the node's run: no toast, no error, nothing handed on. */
function expectNothingReported(node: MountedNode): void {
  expect(mockShowToast).not.toHaveBeenCalled();
  expect(node.outputs().filter((output) => output?.code === 'error')).toEqual([]);
  expect(mockMarkNodeErrored).not.toHaveBeenCalled();
  expect(node.handedOn).not.toHaveBeenCalled();
}

beforeEach(() => {
  resetAutkNodeMocks();
  mockAutkGrammar.mockClear();
  mockDataLoad = null;
  mockDraw = null;
  mockRunsStarted = 0;
  mockLookups.length = 0;
  stubWebGpu();
});

afterEach(unstubWebGpu);

test("repro: a node that leaves the page while autk-grammar loads its map's data says nothing when the map finds no canvas", async () => {
  const dataLoad = held();
  mockDataLoad = dataLoad.promise;
  const node = mountNode();
  const run = await startRun(node);
  await until(() => mockRunsStarted === 1);

  // File > New dataflow: the node leaves the page, and its canvas with it.
  node.unmount();
  await finish(dataLoad, run);

  // autk-grammar's run went on, and its map found no canvas...
  expect(mockLookups).toEqual([{ id: CANVAS, found: false }]);
  // ...which is the node's leaving, not a failure to report.
  expectNothingReported(node);
});

test('repro: a node that leaves the page while its input loads makes no grammar and says nothing', async () => {
  const inputLoad = held();
  let inputAsked = false;
  (mockApi.fetchData as jest.Mock).mockImplementationOnce(async () => {
    inputAsked = true;
    await inputLoad.promise;
    return { dataType: 'geodataframe', data: ONE_ROW };
  });
  const node = mountNode();
  const run = await startRun(node);
  await until(() => inputAsked);

  node.unmount();
  await finish(inputLoad, run);

  expectNothingReported(node);
  // No grammar was made for a canvas that is gone.
  expect(mockAutkGrammar).not.toHaveBeenCalled();
});

test('repro: a node that has left the page starts no run', async () => {
  const node = mountNode();
  node.unmount();

  // A draw asked for as the node left: a run queued behind the one under
  // way, or a restored input's draw once the WebGPU probe answers.
  await act(async () => { await node.start(); });

  expectNothingReported(node);
  expect(node.outputs()).toEqual([]);
  expect(mockAutkGrammar).not.toHaveBeenCalled();
});

test('repro: a run whose map draws after its node left hands nothing on', async () => {
  const draw = held();
  mockDraw = draw.promise;
  const node = mountNode();
  const run = await startRun(node);
  await until(() => mockLookups.length === 1);
  expect(mockLookups).toEqual([{ id: CANVAS, found: true }]);

  node.unmount();
  await finish(draw, run);

  expectNothingReported(node);
  expect(node.outputs()).not.toContainEqual(expect.objectContaining({ code: 'success' }));
});

test('guard: a map still on the page that finds no canvas says so, as any failed run does', async () => {
  const dataLoad = held();
  mockDataLoad = dataLoad.promise;
  const node = mountNode();
  const run = await startRun(node);
  await until(() => mockRunsStarted === 1);

  // The node stays on the page; only its canvas goes.
  document.getElementById(CANVAS)!.remove();
  await finish(dataLoad, run);

  expect(mockLookups).toEqual([{ id: CANVAS, found: false }]);
  expect(mockShowToast).toHaveBeenCalledWith(NO_TARGET, 'error');
  const outputs = node.outputs();
  expect(outputs[outputs.length - 1]).toEqual({ code: 'error', content: NO_TARGET });
  expect(mockMarkNodeErrored).toHaveBeenCalledWith(NODE);
  expect(node.handedOn).not.toHaveBeenCalled();
});
