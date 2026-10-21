/**
 * The Autark map's `keepsView` option (adapters/node/autkGrammarBehavior), as
 * the Map Edits node's map uses it: only the first draw frames the layers, and
 * each later draw puts back the camera of the map the draw before it made,
 * taken before that map is destroyed. Without the option every draw frames.
 *
 * The grammar is a stand-in whose run draws the next of the maps a test
 * queues: stubs with autk-map's camera, renderer, canvas and layer manager.
 */
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));
const mockQueuedMaps: any[] = [];
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => ({
    AutkGrammar: jest.fn().mockImplementation(() => {
      const grammar: any = { data: {}, maps: [], interactions: { on: () => () => {} } };
      grammar.run = jest.fn(async () => {
        grammar.maps = [mockQueuedMaps.shift()];
      });
      return grammar;
    }),
  }),
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

import { framingCamera } from '../../../adapters/node/autkMapView';
import { resetAutkNodeMocks } from '../../_support/autkNodeMocks';
import { mountAutkNode, stubWebGpu, unstubWebGpu } from '../../_support/autkNode';

const FOVY = (45 * Math.PI) / 180;
const FAR = 5e5;
const MAP = { map: { layerRefs: [{ dataRef: 'input_0' }] } };

/** A map autk-map drew: its layers about 1,200 by 700 around (40, -10), drawn from *origin*. */
function drawnMap(origin: number[]) {
  const canvas = document.createElement('canvas');
  Object.defineProperty(canvas, 'offsetWidth', { get: () => 480 });
  Object.defineProperty(canvas, 'offsetHeight', { get: () => 300 });
  let view = { up: [0, 1, 0], lookAt: [0, 0, 0], eye: [0, 0, 10000] };
  const camera = {
    resetCamera: jest.fn((up: number[], lookAt: number[], eye: number[]) => {
      view = { up, lookAt, eye };
    }),
    resize: jest.fn(),
    getFovyRadians: () => FOVY,
    getFar: () => FAR,
    getEye: () => view.eye,
    getLookAt: () => view.lookAt,
    getUp: () => view.up,
  };
  return {
    canvas,
    camera,
    renderer: { pixelWidth: 960, pixelHeight: 600 },
    layerManager: {
      layers: [{ position: new Float32Array([-560, -360, 640, -360, 640, 340, -560, 340]), _dimension: 2 }],
      hasOrigin: true,
      origin,
    },
    resetCamera: jest.fn(),
    requestRender: jest.fn(),
    destroy: jest.fn(),
    /** The person zooms and pans to *to*. */
    moveTo: (to: { up: number[]; lookAt: number[]; eye: number[] }) => {
      view = to;
    },
  };
}

const FRAMED = framingCamera({ minX: -560, minY: -360, maxX: 640, maxY: 340, top: 0 }, 1.6, FOVY, FAR);
const ZOOMED = { up: [0, 1, 0], lookAt: [120, -40, 0], eye: [120, -40, 300] };

beforeEach(() => {
  jest.clearAllMocks();
  resetAutkNodeMocks();
  mockQueuedMaps.length = 0;
  stubWebGpu();
});

afterEach(() => {
  unstubWebGpu();
});

test('with keepsView, the first draw frames the layers and a redraw keeps the view the person moved to', async () => {
  const first = drawnMap([1000, 2000]);
  const second = drawnMap([1000, 2000]);
  mockQueuedMaps.push(first, second);
  const node = mountAutkNode('map-edits-1', undefined, { options: { keepsView: true, recordsProvenance: false } });

  await node.run(MAP);
  expect(node.lastOutput()).toMatchObject({ code: 'success' });
  expect(first.camera.resetCamera).toHaveBeenCalledWith([0, 1, 0], FRAMED.lookAt, FRAMED.eye);

  first.moveTo(ZOOMED);
  await node.run(MAP);

  expect(node.lastOutput()).toMatchObject({ code: 'success' });
  // The last draw's map was read before it was destroyed.
  expect(first.destroy).toHaveBeenCalled();
  expect(second.camera.resetCamera).toHaveBeenCalledTimes(1);
  expect(second.camera.resetCamera).toHaveBeenCalledWith([0, 1, 0], ZOOMED.lookAt, ZOOMED.eye);
  expect(second.camera.resize).toHaveBeenCalledWith(960, 600);
  expect(second.requestRender).toHaveBeenCalled();
});

test('with keepsView, a redraw whose layers moved the origin keeps the same ground in view', async () => {
  const first = drawnMap([1000, 2000]);
  const second = drawnMap([1010, 1995]);
  mockQueuedMaps.push(first, second);
  const node = mountAutkNode('map-edits-1', undefined, { options: { keepsView: true } });

  await node.run(MAP);
  first.moveTo(ZOOMED);
  await node.run(MAP);

  expect(second.camera.resetCamera).toHaveBeenCalledWith([0, 1, 0], [110, -35, 0], [110, -35, 300]);
});

test('without keepsView, every draw frames the layers, as an Autark node draws', async () => {
  const first = drawnMap([1000, 2000]);
  const second = drawnMap([1000, 2000]);
  mockQueuedMaps.push(first, second);
  const node = mountAutkNode('autark-1');

  await node.run(MAP);
  first.moveTo(ZOOMED);
  await node.run(MAP);

  expect(second.camera.resetCamera).toHaveBeenCalledTimes(1);
  expect(second.camera.resetCamera).toHaveBeenCalledWith([0, 1, 0], FRAMED.lookAt, FRAMED.eye);
});
