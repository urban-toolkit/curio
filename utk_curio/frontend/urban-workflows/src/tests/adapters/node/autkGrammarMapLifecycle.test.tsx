/**
 * An Autark node draws its maps on demand and destroys a map once nobody will
 * see it again (adapters/node/autkGrammarBehavior): the map its next run
 * replaces, and its map when the node leaves the page (a deleted node, a
 * closed dataflow), even one its run made after it left. The node keeps
 * working: its new map draws.
 *
 * autk-map pans when the pointer moves over its canvas with a button held,
 * wherever the press began. So while a press that began off the node's canvas
 * is held (an edge, a node or a selection box dragged across the map), the
 * canvas ignores the pointer, and takes it again when the press ends. A press
 * on the canvas itself still pans the map.
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

function mountNode(nodeId = 'map-1'): MountedNode {
  let apply: (spec: string) => Promise<void> = async () => { };
  const setOutput = jest.fn();
  let host: HTMLElement | null = null;
  const Probe: React.FC = () => {
    const behavior = useAutkGrammarBehavior(
      { nodeId, input: { path: 'art-1', dataType: 'geodataframe' }, defaultCode: '{}' } as any,
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

/**
 * A pointer event as the page gets it, on *target*, with the primary button
 * held. jsdom has no PointerEvent, and a MouseEvent carries every field read
 * here: the target, `button` and `buttons`.
 */
function pointer(target: EventTarget, type: string, init: MouseEventInit = {}): void {
  target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, buttons: 1, ...init }));
}

describe('a press that began off the map', () => {
  test('makes the map canvas ignore the pointer until the press ends', async () => {
    const node = mountNode();
    await node.run();
    const [canvas] = node.canvases();
    expect(canvas.style.pointerEvents).toBe('');

    // A press on a handle, a node's header or the pane, then moves with it held.
    pointer(document.body, 'pointerdown');
    expect(canvas.style.pointerEvents).toBe('none');
    pointer(document.body, 'pointermove');
    expect(canvas.style.pointerEvents).toBe('none');

    pointer(document.body, 'pointerup', { buttons: 0 });
    expect(canvas.style.pointerEvents).toBe('');
  });

  test.each<[string, (target: EventTarget) => void]>([
    // A native drag and drop, such as a catalog card's, cancels the pointer as
    // it starts, and no pointerup follows its drop.
    ['a cancelled pointer', (target) => pointer(target, 'pointercancel', { buttons: 0 })],
    ['a move with no button held', (target) => pointer(target, 'pointermove', { buttons: 0 })],
    ['the window losing focus', () => window.dispatchEvent(new Event('blur'))],
  ])('ends with %s', async (_, end) => {
    const node = mountNode();
    await node.run();
    const [canvas] = node.canvases();

    pointer(document.body, 'pointerdown');
    expect(canvas.style.pointerEvents).toBe('none');
    end(document.body);
    expect(canvas.style.pointerEvents).toBe('');
  });

  test('on another map makes this one ignore the pointer, and a press on its own canvas does not', async () => {
    const first = mountNode('map-1');
    await first.run();
    const second = mountNode('map-2');
    await second.run();
    const [one] = first.canvases();
    const [other] = second.canvases();

    // The drag that pans the first map passes over the second one.
    pointer(one, 'pointerdown');
    expect(one.style.pointerEvents).toBe('');
    expect(other.style.pointerEvents).toBe('none');
    pointer(one, 'pointerup', { buttons: 0 });
    expect(other.style.pointerEvents).toBe('');
  });

  test('with the right button leaves the canvas alone: autk-map does not pan with it', async () => {
    const node = mountNode();
    await node.run();
    const [canvas] = node.canvases();

    pointer(document.body, 'pointerdown', { button: 2, buttons: 2 });
    expect(canvas.style.pointerEvents).toBe('');
    pointer(document.body, 'pointerup', { button: 2, buttons: 0 });
  });

  test('is no longer watched for a canvas the next run replaced, nor once the node left', async () => {
    const node = mountNode();
    await node.run();
    const [replaced] = node.canvases();
    await node.run();
    const [shown] = node.canvases();
    expect(shown).not.toBe(replaced);

    pointer(document.body, 'pointerdown');
    expect(replaced.style.pointerEvents).toBe('');
    expect(shown.style.pointerEvents).toBe('none');

    // A node that leaves the page during the press gives its canvas the pointer
    // back, and later presses leave the canvas alone.
    node.unmount();
    expect(shown.style.pointerEvents).toBe('');
    pointer(document.body, 'pointerup', { buttons: 0 });
    pointer(document.body, 'pointerdown');
    expect(shown.style.pointerEvents).toBe('');
    pointer(document.body, 'pointerup', { buttons: 0 });
  });
});
