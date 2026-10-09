/**
 * An Autark node draws its maps on demand and destroys a map once nobody will
 * see it again (adapters/node/autkGrammarBehavior): the map its next run
 * replaces, and its map when the node leaves the page (a deleted node, a
 * closed dataflow), even one its run made after it left. The node keeps
 * working: its new map draws.
 *
 * The grammar is a stand-in that draws one real autk-map map on the node's
 * canvas, as autk-grammar does (`new AutkMap(canvas)`, then `draw()`, which
 * draws on demand), and keeps it as autk-grammar does (`grammarThatRan`).
 * jsdom has no WebGPU, so the map's frames are counted instead of rendered.
 */
import React from 'react';
import * as path from 'path';
import { render, act } from '@testing-library/react';
import { grammarThatRan } from '../../_support/autkGrammarMaps';

// The node reads its input edge from the flow context (hook/useGrammarInputState);
// the real provider would load the whole node registry, vega included.
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ edges: [], nodeExecStatus: {} }),
}));
jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
// One upstream row, so the map's `input_0` table resolves and the node gets as
// far as running the grammar.
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

// The autk-map build the app bundles, as CommonJS.
const { AutkMap: mockAutkMap } = require(path.resolve(
  __dirname, '../../../../node_modules/@urban-toolkit/autk-map/dist/autk-map.umd.cjs',
));

type Drawn = { map: any; frames: number };
/** Every map the stand-in grammar drew, in order. */
const mockDrawn: Drawn[] = [];
/** While set, a run waits for it once its map is drawing. */
let mockHold: Promise<void> | null = null;

const mockAutkGrammar = jest.fn().mockImplementation((targets: Record<string, string>) => {
  const grammar: any = { data: {} };
  grammar.run = jest.fn(async (spec: any) => {
    const map = new mockAutkMap(document.getElementById(targets.map));
    const drawn: Drawn = { map, frames: 0 };
    map.render = () => { drawn.frames += 1; };
    mockDrawn.push(drawn);
    Object.assign(grammar, grammarThatRan(spec, map));
    map.draw();
    if (mockHold) await mockHold;
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

const MAP = JSON.stringify({ map: { layerRefs: [{ dataRef: 'input_0' }] } });

type MountedNode = {
  /** Run the document and wait for the run to end. */
  run: () => Promise<void>;
  /** Start a run, and return it. */
  start: () => Promise<void>;
  unmount: () => void;
  lastOutput: () => any;
  canvases: () => HTMLCanvasElement[];
};

function mountNode(): MountedNode {
  let apply: (spec: string) => Promise<void> = async () => { };
  const setOutput = jest.fn();
  let host: HTMLElement | null = null;
  const Probe: React.FC = () => {
    const behavior = useAutkGrammarBehavior(
      { nodeId: 'map-1', input: { path: 'art-1', dataType: 'geodataframe' }, defaultCode: '{}' } as any,
      {
        output: { code: '', content: '' },
        setOutput,
        setCode: jest.fn(),
        templateData: {},
      } as any,
    );
    apply = behavior.applyGrammar as (spec: string) => Promise<void>;
    return <div ref={(el) => { host = el; }}>{behavior.contentComponent}</div>;
  };
  const { unmount } = render(<Probe />);
  return {
    run: async () => {
      await act(async () => { await apply(MAP); });
    },
    start: () => apply(MAP),
    unmount,
    lastOutput: () => setOutput.mock.calls[setOutput.mock.calls.length - 1]?.[0],
    canvases: () => Array.from(host?.querySelectorAll('canvas') ?? []),
  };
}

/** Let the page draw for *ms* milliseconds. */
async function frames(ms = 150): Promise<void> {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });
}

beforeEach(() => {
  mockDrawn.length = 0;
  mockHold = null;
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
  for (const { map } of mockDrawn) map.destroy();
  jest.restoreAllMocks();
  __resetWebGpuSupportCache();
  Object.defineProperty(navigator, 'gpu', { configurable: true, value: undefined });
});

test('a map the node draws draws its frame, then only when something asks for one', async () => {
  const node = mountNode();
  await node.run();
  const [drawn] = mockDrawn;
  await frames();
  // Started as autk-grammar starts it, it draws its frame, then rests.
  expect(drawn.frames).toBeGreaterThanOrEqual(1);
  const settled = drawn.frames;
  await frames();
  expect(drawn.frames).toBe(settled);

  drawn.map.requestRender();
  await frames();
  expect(drawn.frames).toBe(settled + 1);
});

test('a re-run destroys the map it replaces, and the new map draws', async () => {
  const node = mountNode();
  await node.run();
  expect(mockDrawn).toHaveLength(1);
  const [first] = mockDrawn;
  expect(first.map._isDestroyed).toBe(false);

  await node.run();
  expect(mockDrawn).toHaveLength(2);
  const second = mockDrawn[1];
  expect(first.map._isDestroyed).toBe(true);
  expect(second.map._isDestroyed).toBe(false);
  // The node shows the new map, and its run succeeded.
  expect(node.canvases()).toHaveLength(1);
  expect(node.canvases()[0]).toBe(second.map.canvas);
  expect(node.lastOutput()).toMatchObject({ code: 'success' });

  const replaced = first.frames;
  await frames();
  expect(first.frames).toBe(replaced);
  expect(second.frames).toBeGreaterThanOrEqual(1);
});

test('a node that leaves the page destroys its map', async () => {
  const node = mountNode();
  await node.run();
  const [drawn] = mockDrawn;

  node.unmount();
  expect(drawn.map._isDestroyed).toBe(true);
  const left = drawn.frames;
  await frames();
  expect(drawn.frames).toBe(left);
});

test('a map its run made after the node left is destroyed at once', async () => {
  let release!: () => void;
  mockHold = new Promise<void>((resolve) => { release = resolve; });
  const node = mountNode();
  let running!: Promise<void>;
  await act(async () => {
    running = node.start();
    for (let i = 0; i < 200 && mockDrawn.length === 0; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
  });
  expect(mockDrawn).toHaveLength(1);
  const [drawn] = mockDrawn;

  node.unmount();
  await act(async () => {
    release();
    await running;
  });
  expect(drawn.map._isDestroyed).toBe(true);
});
