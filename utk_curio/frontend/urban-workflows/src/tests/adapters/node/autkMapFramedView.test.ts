/**
 * The map framing check (#773) reads a map its document's `camera` turns at
 * the view the node framed it at (adapters/node/autkMapView,
 * `showFramedViews`, which the page hook `__curio_showMapsFramed` calls):
 * straight down on its layers, before the turn. What it returns turns the map
 * back to its camera's view. A map no camera turns is left as it is, moved or
 * not.
 *
 * `applyCamera` is the grammar's build (_support/autkApplyCamera); the maps
 * are stand-ins of autk-map's, as in autkMapCamera.test.ts.
 */
jest.mock("@urban-toolkit/autk-db", () => ({}), { virtual: true });
jest.mock("@urban-toolkit/autk-map", () => ({}), { virtual: true });
jest.mock("@urban-toolkit/autk-plot", () => ({}), { virtual: true });
jest.mock("@urban-toolkit/autk-core", () => ({}), { virtual: true });
jest.mock("@urban-toolkit/autk-compute", () => ({}), { virtual: true });

import { attachSpecCameras, frameMaps, framingCamera, keepMapViews, mapViews, showFramedViews } from "../../../adapters/node/autkMapView";
import { grammarThatRan } from "../../_support/autkGrammarMaps";
import { grammarApplyCamera } from "../../_support/autkApplyCamera";

const applyCamera = grammarApplyCamera();

const FOVY = (45 * Math.PI) / 180;
const FAR = 5e5;
const WIDTH = 480;
const HEIGHT = 300;
const DEGREE = Math.PI / 180;

type View = { eye: number[]; lookAt: number[]; up: number[] };

/** autk-map's camera: the view `resetCamera` sets, which its getters read. */
function standingCamera() {
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
  return camera;
}

/** An AutkMap drawing a block about 1,200 by 700 around (40, -10), on a canvas laid out at *laid* (480 by 300). */
function blockMap(laid = { width: WIDTH, height: HEIGHT }) {
  const canvas = document.createElement("canvas");
  Object.defineProperty(canvas, "offsetWidth", { get: () => laid.width, configurable: true });
  Object.defineProperty(canvas, "offsetHeight", { get: () => laid.height, configurable: true });
  const camera = standingCamera();
  const block = {
    position: new Float32Array([-560, -360, 640, -360, 640, 340, -560, 340]),
    _dimension: 2,
  };
  const map: any = {
    canvas,
    camera,
    renderer: { pixelWidth: WIDTH * 2, pixelHeight: HEIGHT * 2 },
    layerManager: { layers: [block], hasOrigin: true, origin: [1000, 2000] },
    requestRender: jest.fn(),
  };
  map.resetCamera = jest.fn(() => {
    camera.resetCamera([0, 1, 0], [0, 0, 0], [0, 0, 10000]);
  });
  return map;
}

/** Where the node frames the block: straight down on (40, -10), as high as fits it. */
const FRAMED = framingCamera({ minX: -560, minY: -360, maxX: 640, maxY: 340, top: 0 }, WIDTH / HEIGHT, FOVY, FAR);
const HIGH = FRAMED.eye[2];
const STRAIGHT_DOWN: View = { eye: FRAMED.eye, lookAt: FRAMED.lookAt, up: [0, 1, 0] };

/**
 * The view turned round *lookAt*: the eye *distance* away, *pitch* degrees
 * from straight down, facing *bearing*, its up direction across its line of
 * sight, toward the far side of the view, as autk-map's own tilt leaves it.
 */
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
    up: [Math.cos(p) * Math.sin(b), Math.cos(p) * Math.cos(b), Math.sin(p)],
  };
}

/** *view* holds *expected*'s eye, look-at and up, each number to 6 decimals. */
function expectView(view: View, expected: View): void {
  for (const key of ["eye", "lookAt", "up"] as const) {
    expect(view[key]).toHaveLength(3);
    view[key].forEach((value, i) => expect(value).toBeCloseTo(expected[key][i], 6));
  }
}

/** The grammar that drew *map* for a document whose one map writes *camera*, given its camera as the node gives it. */
function drawn(map: any, camera?: Record<string, unknown>) {
  const spec = { map: { ...(camera ? { camera } : {}), layerRefs: [{ dataRef: "input_0" }] } };
  const grammar = grammarThatRan(spec, map);
  attachSpecCameras(grammar, spec, applyCamera);
  return grammar;
}

describe("the framed view of a map its camera turns", () => {
  test("is shown straight down on its layers, as the node framed it, and what it returns turns the map back", () => {
    const map = blockMap();
    const grammar = drawn(map, { pitch: 50, bearing: 30 });
    frameMaps(grammar);
    expectView(map.camera.view, turned(FRAMED.lookAt, HIGH, 50, 30));
    map.requestRender.mockClear();

    const turnBack = showFramedViews(grammar);
    expectView(map.camera.view, STRAIGHT_DOWN);
    expect(map.requestRender).toHaveBeenCalled();
    // Its view still names the camera that turns it, as the check reads it.
    expect(mapViews(grammar)[0]?.camera).toBe(JSON.stringify([null, 50, 30]));

    turnBack();
    expectView(map.camera.view, turned(FRAMED.lookAt, HIGH, 50, 30));
  });

  // The check compares the turned view with the framed one the hook shows:
  // the view the node framed the map at, which a canvas laid out at another
  // size since then would not give if the map were framed anew.
  test("is the view the node framed it at, though its canvas was laid out at another size since", () => {
    const laid = { width: WIDTH, height: HEIGHT };
    const map = blockMap(laid);
    const grammar = drawn(map, { pitch: 50, bearing: 30 });
    frameMaps(grammar);
    // Square now: framed anew, the block's width would set a higher eye.
    laid.width = HEIGHT;
    const anew = framingCamera({ minX: -560, minY: -360, maxX: 640, maxY: 340, top: 0 }, 1, FOVY, FAR);
    expect(anew.eye[2]).toBeGreaterThan(HIGH * 1.2);

    const turnBack = showFramedViews(grammar);
    expectView(map.camera.view, STRAIGHT_DOWN);
    turnBack();
    expectView(map.camera.view, turned(FRAMED.lookAt, HIGH, 50, 30));
  });

  test("drawn again with its view kept, it is still the view the node framed it at", () => {
    const first = blockMap();
    const before = drawn(first, { pitch: 50, bearing: 30 });
    frameMaps(before);
    const views = mapViews(before);
    // Drawn again, as after an upstream run, on a canvas laid out square since.
    const again = blockMap({ width: HEIGHT, height: HEIGHT });
    const grammar = drawn(again, { pitch: 50, bearing: 30 });
    keepMapViews(grammar, views);
    expectView(again.camera.view, turned(FRAMED.lookAt, HIGH, 50, 30));

    const turnBack = showFramedViews(grammar);
    expectView(again.camera.view, STRAIGHT_DOWN);
    turnBack();
    expectView(again.camera.view, turned(FRAMED.lookAt, HIGH, 50, 30));
  });

  test("with a zoom, the turn back puts the eye where the zoom puts it, not at the framed height", () => {
    const map = blockMap();
    const grammar = drawn(map, { zoom: 15, pitch: 40, bearing: 300 });
    frameMaps(grammar);

    const turnBack = showFramedViews(grammar);
    expectView(map.camera.view, STRAIGHT_DOWN);
    turnBack();
    expectView(map.camera.view, turned(FRAMED.lookAt, 312.5, 40, 300));
  });

  test("a map no camera turns stays where it is, framed or moved", () => {
    const map = blockMap();
    const grammar = drawn(map);
    frameMaps(grammar);
    // A person moved it.
    map.camera.resetCamera([0, 1, 0], [5, 5, 0], [5, 5, 900]);
    const moved: View = { eye: [5, 5, 900], lookAt: [5, 5, 0], up: [0, 1, 0] };
    map.camera.resetCamera.mockClear();

    const turnBack = showFramedViews(grammar);
    expectView(map.camera.view, moved);
    turnBack();
    expectView(map.camera.view, moved);
    expect(map.camera.resetCamera).not.toHaveBeenCalled();
  });
});
