/**
 * An Autark node runs a document whose map writes a `camera`
 * (adapters/node/autkGrammarBehavior), a `map` written as a list of one
 * included. The map its grammar draws is framed on the layers it drew, then
 * turned by that camera through the `applyCamera` the node takes from the
 * grammar module it runs. A node that keeps its view across draws keeps the
 * view the map had, and turns a map whose camera the document changed. The
 * page reads each map's view through `window.__curio_mapViews`, as the e2e
 * tests read it.
 *
 * The grammar is the stand-in of _support/autkNodeMocks, and its `applyCamera`
 * is autk-grammar's own (_support/autkApplyCamera).
 */
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => ({
    ...require('../../_support/autkNodeMocks').autkGrammarModule,
    applyCamera: (map: any, camera: any) => mockApplyCamera(map, camera),
  }),
  { virtual: true },
);
// What autk-grammar's build imports, which it reads none of while it loads.
jest.mock('@urban-toolkit/autk-db', () => ({}), { virtual: true });
jest.mock('@urban-toolkit/autk-map', () => ({}), { virtual: true });
jest.mock('@urban-toolkit/autk-plot', () => ({}), { virtual: true });
jest.mock('@urban-toolkit/autk-core', () => ({}), { virtual: true });
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

import { framingCamera } from '../../../adapters/node/autkMapView';
import { drawnMaps, grammarRuns, markNodeErrored, resetAutkNodeMocks } from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';
import { grammarApplyCamera } from '../../_support/autkApplyCamera';

const mockApplyCamera = jest.fn(grammarApplyCamera());

const FOVY = Math.PI / 4;
const FAR = 5e5;
const DEGREE = Math.PI / 180;

type View = { eye: number[]; lookAt: number[]; up: number[] };

/**
 * The map the stand-in grammar draws: its canvas laid out at 960 by 600, its
 * one layer 100 by 50 units from its origin, and a camera that keeps the view
 * `resetCamera` sets.
 */
function shownMap() {
  const camera: any = {
    view: { eye: [0, 0, 10000], lookAt: [0, 0, 0], up: [0, 1, 0] } as View,
    getEye: () => [...camera.view.eye],
    getLookAt: () => [...camera.view.lookAt],
    getUp: () => [...camera.view.up],
    getFovyRadians: () => FOVY,
    getFar: () => FAR,
    resize: jest.fn(),
  };
  camera.resetCamera = jest.fn((up: number[], lookAt: number[], eye: number[]) => {
    camera.view = { eye: [...eye], lookAt: [...lookAt], up: [...up] };
  });
  return {
    camera,
    renderer: { pixelWidth: 1920, pixelHeight: 1200 },
    canvas: { offsetWidth: 960, offsetHeight: 600 },
    layerManager: { layers: [{ position: new Float32Array([0, 0, 100, 50]), _dimension: 2 }], hasOrigin: true, origin: [1000, 2000] },
    resetCamera: jest.fn(),
    requestRender: jest.fn(),
    updateRenderInfo: jest.fn(),
    destroy: jest.fn(),
  };
}

/** Where the node frames that layer: straight down on (50, 25), as high as fits it. */
const FRAMED = framingCamera({ minX: 0, minY: 0, maxX: 100, maxY: 50, top: 0 }, 960 / 600, FOVY, FAR);
const HIGH = FRAMED.eye[2];

/** The view turned round *lookAt*, *distance* away, *pitch* from straight down, facing *bearing*. */
function turned(lookAt: number[], distance: number, pitch: number, bearing: number): View {
  const p = pitch * DEGREE;
  const b = bearing * DEGREE;
  return {
    eye: [
      lookAt[0] - distance * Math.sin(p) * Math.sin(b),
      lookAt[1] - distance * Math.sin(p) * Math.cos(b),
      distance * Math.cos(p),
    ],
    lookAt: [lookAt[0], lookAt[1], 0],
    up: [Math.sin(b), Math.cos(b), 0],
  };
}

function expectView(view: View, expected: View): void {
  for (const key of ['eye', 'lookAt', 'up'] as const) {
    expect(view[key]).toHaveLength(3);
    view[key].forEach((value, i) => expect(value).toBeCloseTo(expected[key][i], 6));
  }
}

const LAYERS = [{ dataRef: 'input_0' }];
const TILTED = { pitch: 50, bearing: 30 };

beforeEach(() => {
  resetAutkNodeMocks();
  mockApplyCamera.mockClear();
  drawnMaps.make = shownMap;
  stubWebGpu();
});

afterEach(unstubWebGpu);

test.each([
  ['a map', { map: { camera: TILTED, layerRefs: LAYERS } }],
  ['a list of one map', { map: [{ camera: TILTED, layerRefs: LAYERS }] }],
])('a document whose %s writes a camera runs, and its map is framed, then turned by it', async (_, spec) => {
  const node = mountAutkNode('cam-1');
  await node.run(spec);

  expect(node.lastOutput()).toMatchObject({ code: 'success' });
  expect(markNodeErrored).not.toHaveBeenCalled();
  expect(grammarRuns).toHaveLength(1);
  expect(grammarRuns[0].spec.map.camera).toEqual(TILTED);
  const [map] = grammarRuns[0].maps;
  expect(mockApplyCamera).toHaveBeenCalledWith(map, TILTED);
  expect(map.camera.resetCamera.mock.calls[0]).toEqual([[0, 1, 0], FRAMED.lookAt, FRAMED.eye]);
  expectView(map.camera.view, turned(FRAMED.lookAt, HIGH, 50, 30));
});

test("the page reads the view of the node's map through window.__curio_mapViews", async () => {
  const node = mountAutkNode('cam-2');
  await node.run({ map: { camera: TILTED, layerRefs: LAYERS } });

  const views = (window as any).__curio_mapViews?.('cam-2');
  expect(views).toHaveLength(1);
  expectView(views[0], turned(FRAMED.lookAt, HIGH, 50, 30));
  expect(views[0].origin).toEqual([1000, 2000]);
  expect((window as any).__curio_mapViews('no-such-node')).toBeNull();
});

test('a node that keeps its view keeps the view its map was moved to, and turns a map whose camera changed', async () => {
  const node = mountAutkNode('cam-3', undefined, { options: { keepsView: true } });
  await node.run({ map: { camera: TILTED, layerRefs: LAYERS } });
  const first = grammarRuns[0].maps[0];
  expectView(first.camera.view, turned(FRAMED.lookAt, HIGH, 50, 30));

  // The person moves the map; the next draw keeps that view, turned no further.
  const moved: View = { eye: [80, -30, 140], lookAt: [90, 10, 0], up: [0, 1, 0] };
  first.camera.resetCamera(moved.up, moved.lookAt, moved.eye);
  await node.run({ map: { camera: TILTED, layerRefs: LAYERS } });
  const second = grammarRuns[1].maps[0];
  expect(second.camera.view).toEqual(moved);

  // A camera the document changed is the view the next draw shows.
  await node.run({ map: { camera: { pitch: 20, bearing: 270 }, layerRefs: LAYERS } });
  const third = grammarRuns[2].maps[0];
  expectView(third.camera.view, turned(FRAMED.lookAt, HIGH, 20, 270));
});
